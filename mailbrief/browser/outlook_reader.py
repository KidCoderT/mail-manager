import json
import sys
import time
from urllib.parse import unquote, urlparse

from mailbrief import progress
from mailbrief.browser.owa_network import (
    check_request,
    find_user_email,
    getitem_body,
    parse_items,
    parse_messages,
    preview_records,
    view_total,
)

INBOX_URL = "https://outlook.office.com/mail/"
LOGIN_HOSTS = ("login.microsoftonline.com", "login.live.com")
MESSAGE_LIST = '[role="listbox"]'
MESSAGE_ROW = f'{MESSAGE_LIST} [role="option"]'
# Headers Outlook's own service.svc calls carry that GetItem needs. Kept in memory only, never logged.
REPLAY_HEADERS = ("authorization", "x-anchormailbox", "x-owa-sessionid", "x-req-source", "x-owa-hosted-ux", "x-client-version", "prefer")
GETITEM_BATCH = 20
STALL_S = 15


def _is_outlook_json(response) -> bool:
    host = urlparse(response.url).hostname or ""
    return host.startswith("outlook.") and "json" in response.headers.get("content-type", "")


def _request_json(request) -> dict:
    """service.svc sends its JSON either as the POST body or URL-encoded in an x-owa-urlpostdata header."""
    raw = request.post_data or unquote(request.headers.get("x-owa-urlpostdata", ""))
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _view_of(request):
    """FindConversation's FocusedViewFilter: 0 = Focused, 1 = Other, -1/None = no Focused Inbox."""
    return (_request_json(request).get("Body") or {}).get("FocusedViewFilter")


def _track_auth(auth: dict, request) -> None:
    """Remember the latest service.svc call's auth headers and JSON Header (the token can refresh mid-run)."""
    if "service.svc" not in request.url or "authorization" not in request.headers:
        return
    header = _request_json(request).get("Header")
    if header:
        auth.update(url=request.url, header=header, headers={k: v for k, v in request.headers.items() if k in REPLAY_HEADERS})


def _load_view(page, responses: list, view, max_scrolls: int) -> list:
    """Scroll the visible list until Outlook has sent every conversation in `view`; return that view's payloads."""
    payloads, read = [], 0

    def drain():
        nonlocal read
        for v, r in responses[read:]:
            if v != view:  # Outlook also refreshes the other tab in the background
                continue
            try:
                payloads.append(r.json())
            except Exception:  # redirects, empty bodies, non-JSON despite the header
                pass
        read = len(responses)

    # The list is virtualized and pages in ~50 at a time, only when the mouse wheel scrolls it.
    # ponytail: always scrolls the whole view; stop early at the cursor (LastDeliveryOrRenewTime) if inboxes get huge.
    box = page.locator(MESSAGE_LIST).first.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    label = {0: "Loading Focused tab", 1: "Loading Other tab"}.get(view, "Loading inbox")
    last, last_growth = -1, time.monotonic()
    for _ in range(max_scrolls if box else 0):
        drain()
        count, total = len(parse_messages(payloads)), view_total(payloads)
        if total:
            progress.count(label, min(count, total), total)
        if count != last:
            last, last_growth = count, time.monotonic()
        # Done when everything is loaded, or Outlook sent nothing new for STALL_S (it can be slow per page).
        if (total is not None and count >= total) or time.monotonic() - last_growth > STALL_S:
            break
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(800)
    drain()
    return payloads


def open_outlook(page, timeout_s: int = 60) -> dict:
    """Open Outlook and wait until signed in. Returns {"expired", "auth", "startup"}: auth is the in-memory replay
    state for _service_call, startup the parsed StartupData payloads (your address, your category list)."""
    auth, startup_responses = {}, []
    # StartupData is JSON served as application/x-javascript, so a JSON content-type filter would miss it.
    page.on("response", lambda r: startup_responses.append(r) if "startupdata" in r.url.lower() else None)
    page.on("request", lambda r: _track_auth(auth, r))
    progress.step("Opening Outlook…")
    page.goto(INBOX_URL, wait_until="domcontentloaded")

    # Wait for either the message list or a redirect to the Microsoft login page.
    for _ in range(timeout_s * 2):
        if (urlparse(page.url).hostname or "") in LOGIN_HOSTS:
            progress.step("Session expired (redirected to the Microsoft login page)")
            return {"expired": True, "auth": auth, "startup": []}
        if page.locator(MESSAGE_ROW).count():
            break
        page.wait_for_timeout(500)
    progress.step("Signed in")
    page.wait_for_timeout(3000)  # let the list's follow-up requests finish (and auth be captured)
    startup = []
    for r in startup_responses:
        try:
            startup.append(r.json())
        except Exception:
            pass
    return {"expired": False, "auth": auth, "startup": startup}


def read_inbox(page, timeout_s: int = 60, max_scrolls: int = 300) -> dict:
    """Open the inbox, load every conversation in Focused and Other, return what Outlook's network calls revealed.

    Returns {"expired", "messages", "total", "urls", "auth", "me"}; "auth" is in-memory replay state for fetch_emails.
    """
    responses = []  # (view, response)
    page.on("response", lambda r: responses.append((_view_of(r.request), r)) if _is_outlook_json(r) else None)
    opened = open_outlook(page, timeout_s)
    auth = opened["auth"]
    if opened["expired"]:
        return {"expired": True, "messages": [], "total": None, "urls": [], "auth": auth}
    progress.step("Loading the inbox list…")

    # With Focused Inbox on, the list only shows one tab; load "Other" too, then switch back.
    first_view = next((v for v, _ in responses if v is not None), None)
    views = [_load_view(page, responses, first_view, max_scrolls)]
    other = page.get_by_role("tab", name="Other")
    if first_view == 0 and other.count():
        other.first.click()
        page.wait_for_timeout(3000)
        views.append(_load_view(page, responses, 1, max_scrolls))
        page.get_by_role("tab", name="Focused").first.click()

    totals = [view_total(v) for v in views]
    urls = sorted({urlparse(r.url).path for _, r in responses})  # paths only: no tokens in query strings
    startup = opened["startup"]
    return {
        "expired": False,
        "messages": parse_messages([p for v in views for p in v]),
        "total": None if None in totals else sum(totals),
        "urls": urls,
        "auth": auth,
        "me": find_user_email(startup),  # your address, to recognise your own replies in threads
    }


def fetch_emails(page, auth: dict, conversations: list[dict], me: str | None = None) -> tuple[list[dict], bool]:
    """Every message in these conversations, from any folder (so your Sent replies too), via read-only
    GetItem calls: nothing is opened or marked read. Records are flagged in_inbox / from_me.

    Returns (records, True), or (preview records, False) if GetItem can't be used.
    """
    inbox_ids = {i for c in conversations for i in c["item_ids"]}
    ids = [i for c in conversations for i in c["global_item_ids"]]
    records = []
    for n in range(0, len(ids), GETITEM_BATCH):
        resp = _service_call(page, auth, "GetItem", lambda header: getitem_body(header, ids[n : n + GETITEM_BATCH]))
        if resp is None or not resp.ok:
            status = resp.status if resp else "no auth captured"
            print(f"warning: GetItem failed ({status}); falling back to list previews", file=sys.stderr)
            return preview_records(conversations), False
        records += parse_items(resp.json())
        progress.count("Fetching full text", min(n + GETITEM_BATCH, len(ids)), len(ids))
    for r in records:
        r["in_inbox"] = r["id"] in inbox_ids
        r["from_me"] = bool(me) and r["sender_email"].lower() == me.lower()
    return records, True


def fetch_images(page, auth: dict, email: dict) -> list[str]:
    """The email's image attachments as data URLs (memory only). Failures just mean no images."""
    if not email.get("image_attachments"):
        return []
    resp = _service_call(page, auth, "GetAttachment", lambda header: {
        "__type": "GetAttachmentJsonRequest:#Exchange",
        "Header": header,
        "Body": {
            "__type": "GetAttachmentRequest:#Exchange",
            "AttachmentIds": [{"__type": "AttachmentId:#Exchange", "Id": a["id"]} for a in email["image_attachments"]],
        },
    })
    if resp is None or not resp.ok:
        return []
    urls = []
    for msg in resp.json().get("Body", {}).get("ResponseMessages", {}).get("Items", []):
        for a in msg.get("Attachments") or []:
            if a.get("Content"):
                ctype = a.get("ContentType") if str(a.get("ContentType", "")).startswith("image/") else "image/png"
                urls.append(f"data:{ctype};base64,{a['Content']}")
    return urls


def _service_call(page, auth: dict, action: str, make_body):
    """POST an action to Outlook's service.svc as the page itself would. None if no auth was captured.

    Every call passes check_request first: reads are free, writes may only touch MailBrief's categories.
    """
    resp = None
    for _ in range(2):  # retry once: a 401 usually means the token refreshed after we copied it
        if not auth:
            return None
        body = make_body(auth["header"])
        check_request(action, body)  # raises before anything leaves this machine
        url = urlparse(auth["url"])._replace(query=f"action={action}&app=Mail").geturl()
        resp = page.request.post(
            url,
            headers={**auth["headers"], "action": action, "content-type": "application/json; charset=utf-8"},
            data=json.dumps(body),
            timeout=60_000,  # a 20-email update can take Outlook a while
        )
        if resp.status != 401:
            break
        page.wait_for_timeout(2000)
    return resp
