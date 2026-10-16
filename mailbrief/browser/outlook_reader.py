import json
import sys
from urllib.parse import unquote, urlparse

from mailbrief.browser.owa_network import getitem_body, parse_items, parse_messages, preview_records, view_total

INBOX_URL = "https://outlook.office.com/mail/"
LOGIN_HOSTS = ("login.microsoftonline.com", "login.live.com")
MESSAGE_LIST = '[role="listbox"]'
MESSAGE_ROW = f'{MESSAGE_LIST} [role="option"]'
# Headers Outlook's own service.svc calls carry that GetItem needs. Kept in memory only, never logged.
REPLAY_HEADERS = ("authorization", "x-anchormailbox", "x-owa-sessionid", "x-req-source", "x-owa-hosted-ux", "x-client-version", "prefer")
GETITEM_BATCH = 20


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
    last, stale = -1, 0
    for _ in range(max_scrolls if box else 0):
        drain()
        count, total = len(parse_messages(payloads)), view_total(payloads)
        if (total is not None and count >= total) or stale >= 6:  # all loaded, or nothing new for ~5 s
            break
        stale = stale + 1 if count == last else 0
        last = count
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(800)
    drain()
    return payloads


def read_inbox(page, timeout_s: int = 60, max_scrolls: int = 300) -> dict:
    """Open the inbox, load every conversation in Focused and Other, return what Outlook's network calls revealed.

    Returns {"expired", "messages", "total", "urls", "auth"}; "auth" is in-memory replay state for fetch_emails.
    """
    responses, auth = [], {}  # responses: (view, response)
    page.on("response", lambda r: responses.append((_view_of(r.request), r)) if _is_outlook_json(r) else None)
    page.on("request", lambda r: _track_auth(auth, r))
    page.goto(INBOX_URL, wait_until="domcontentloaded")

    # Wait for either the message list or a redirect to the Microsoft login page.
    for _ in range(timeout_s * 2):
        if (urlparse(page.url).hostname or "") in LOGIN_HOSTS:
            return {"expired": True, "messages": [], "total": None, "urls": [], "auth": auth}
        if page.locator(MESSAGE_ROW).count():
            break
        page.wait_for_timeout(500)
    page.wait_for_timeout(3000)  # let the list's follow-up requests finish

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
    return {
        "expired": False,
        "messages": parse_messages([p for v in views for p in v]),
        "total": None if None in totals else sum(totals),
        "urls": urls,
        "auth": auth,
    }


def fetch_emails(page, auth: dict, conversations: list[dict]) -> tuple[list[dict], bool]:
    """Full emails for these conversations via read-only GetItem calls (nothing is opened or marked read).

    Returns (records, True), or (preview records, False) if GetItem can't be used.
    """
    ids = [i for c in conversations for i in c["item_ids"]]
    records = []
    for n in range(0, len(ids), GETITEM_BATCH):
        batch = ids[n : n + GETITEM_BATCH]
        resp = None
        for _ in range(2):  # retry once: a 401 usually means the token refreshed after we copied it
            if not auth:
                break
            url = urlparse(auth["url"])._replace(query="action=GetItem&app=Mail").geturl()
            resp = page.request.post(
                url,
                headers={**auth["headers"], "action": "GetItem", "content-type": "application/json; charset=utf-8"},
                data=json.dumps(getitem_body(auth["header"], batch)),
            )
            if resp.status != 401:
                break
            page.wait_for_timeout(2000)
        if resp is None or not resp.ok:
            status = resp.status if resp else "no auth captured"
            print(f"warning: GetItem failed ({status}); falling back to list previews", file=sys.stderr)
            return preview_records(conversations), False
        records += parse_items(resp.json())
    return records, True
