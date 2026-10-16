from urllib.parse import urlparse

from mailbrief.browser.owa_network import parse_messages, view_total

INBOX_URL = "https://outlook.office.com/mail/"
LOGIN_HOSTS = ("login.microsoftonline.com", "login.live.com")
MESSAGE_LIST = '[role="listbox"]'
MESSAGE_ROW = f'{MESSAGE_LIST} [role="option"]'


def _is_outlook_json(response) -> bool:
    host = urlparse(response.url).hostname or ""
    return host.startswith("outlook.") and "json" in response.headers.get("content-type", "")


def read_inbox(page, timeout_s: int = 60, max_scrolls: int = 300) -> dict:
    """Open the inbox, scroll until Outlook has sent every message, return what its network calls revealed.

    Returns {"expired": bool, "messages": [...], "total": int | None, "urls": [json endpoints seen]}.
    """
    responses = []
    page.on("response", lambda r: responses.append(r) if _is_outlook_json(r) else None)
    page.goto(INBOX_URL, wait_until="domcontentloaded")

    # Wait for either the message list or a redirect to the Microsoft login page.
    for _ in range(timeout_s * 2):
        if (urlparse(page.url).hostname or "") in LOGIN_HOSTS:
            return {"expired": True, "messages": [], "total": None, "urls": []}
        if page.locator(MESSAGE_ROW).count():
            break
        page.wait_for_timeout(500)
    page.wait_for_timeout(3000)  # let the list's follow-up requests finish

    payloads, read = [], 0

    def drain():
        nonlocal read
        for r in responses[read:]:
            try:
                payloads.append(r.json())
            except Exception:  # redirects, empty bodies, non-JSON despite the header
                pass
        read = len(responses)

    # The list is virtualized and pages in ~50 at a time, only when the mouse wheel scrolls it.
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

    urls = sorted({urlparse(r.url).path for r in responses})  # paths only: no tokens in query strings
    return {"expired": False, "messages": parse_messages(payloads), "total": view_total(payloads), "urls": urls}
