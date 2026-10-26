"""Send-only Telegram bot. It never polls: getUpdates runs only during `mailbrief add-destination`.

A digest that fits goes as one message. A longer one goes as one message per section (header + first
section, then KEY EVENTS, NOISE, …); a section that is still too long is split on line breaks, with
"<HEADING> (cont.)" on the follow-ups. Every message of a multi-part digest is tagged "· k/n".
"""

import html
import json
import os
import re
import time
import urllib.error
import urllib.request

LIMIT = 4000  # Telegram allows 4096 (UTF-16 units); the margin leaves room for "· k/n" and "(cont.)"
PAUSE_S = 0.5  # between messages, to stay under Telegram's flood control
RETRIES_429 = 3
# A section heading: uppercase words ("NOISE", "KEY EVENTS", "DEADLINES & MEETINGS"), optionally followed
# by a "(…)" note and/or ":". Bullets and normal sentences never match.
HEADING = re.compile(r"^[A-Z][A-Z0-9&/'’\- ]{2,}?(\s*\([^)]*\))?\s*:?$")


class TelegramError(Exception):
    pass


def size(text: str) -> int:
    """Length the way Telegram counts it: UTF-16 code units (an emoji counts as 2)."""
    return len(text.encode("utf-16-le")) // 2


def visible(text: str) -> str:
    """What an HTML-mode message shows: tags removed, &amp; etc. turned back into characters."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def html_size(text: str) -> int:
    """Telegram's limit counts the text after its HTML is parsed, so links don't use up room."""
    return size(visible(text))


def is_heading(line: str) -> bool:
    line = line.strip()
    return bool(line) and not line.startswith(("•", "-", "*")) and bool(HEADING.match(line))


def _api(method: str, payload: dict | None = None) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set (create a bot with @BotFather)")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"},
    )
    for attempt in range(RETRIES_429 + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # never log the URL: it contains the token
                return json.load(r)
        except urllib.error.HTTPError as e:
            # Telegram explains every error in a JSON body; keep its words instead of "HTTP Error 400".
            try:
                body = json.loads(e.read() or b"{}")
            except ValueError:
                body = {}
            wait = (body.get("parameters") or {}).get("retry_after")
            if e.code == 429 and wait and attempt < RETRIES_429:
                time.sleep(int(wait) + 1)  # flood control: Telegram says how long to wait
                continue
            raise TelegramError(f"{e.code} {body.get('description') or e.reason}") from None
    raise TelegramError("429 Too Many Requests (still rate-limited after retries)")


def _hard_cut(line: str, limit: int) -> list[str]:
    """Cut one overlong line into pieces of at most `limit` UTF-16 units (only for very odd output)."""
    pieces, current = [], ""
    for ch in line:
        if size(current + ch) > limit:
            pieces.append(current)
            current = ""
        current += ch
    return pieces + ([current] if current else [])


def split_sections(text: str) -> list[list[str]]:
    """Blocks of lines: the text before the first heading joins the first section; each heading starts a block."""
    blocks: list[list[str]] = [[]]
    seen_heading = False
    for line in text.splitlines():
        if is_heading(visible(line)):  # judged on what shows: an HTML heading line may carry a link
            if seen_heading:
                blocks.append([])
            seen_heading = True
        blocks[-1].append(line)
    return blocks


def _trim(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return lines


def _chunk_block(lines: list[str], measure=size) -> list[str]:
    """One block → messages ≤ LIMIT, split on line breaks; follow-ups start with '<HEADING> (cont.)'.
    `measure` is html_size for HTML text: lines are never cut inside a tag (only absurdly long ones are cut)."""
    heading = next((visible(l).strip() for l in lines if is_heading(visible(l))), None)
    cont = f"{heading.split('(')[0].rstrip(' :')} (cont.)" if heading else None
    if cont and measure is html_size:
        cont = html.escape(cont, quote=False)  # the copied heading is plain text; "&" must be "&amp;" here
    # Balanced, not greedy: 4100 units → two ~2050 messages, never 3990 + a lonely 110.
    pieces_needed = -(-measure("\n".join(lines)) // LIMIT)
    target = min(LIMIT, -(-measure("\n".join(lines)) // pieces_needed) + 200)
    chunks, current = [], []
    for line in lines:
        for piece in (_hard_cut(line, LIMIT - 100) if measure(line) > LIMIT - 100 else [line]):
            if current and measure("\n".join(current + [piece])) > target:
                chunks.append(current)
                current = [cont] if cont else []
            current.append(piece)
    if current:
        chunks.append(current)
    return ["\n".join(_trim(c)) for c in chunks if _trim(c)]


def messages(text: str, html_mode: bool = False) -> list[str]:
    """The Telegram messages for `text`: one if it fits, else one per section (split further if needed)."""
    text = text.strip()
    measure = html_size if html_mode else size
    if measure(text) <= LIMIT:
        return [text] if text else []
    out = [m for block in split_sections(text) for m in _chunk_block(_trim(block), measure)]
    if len(out) > 1:  # "· k/n" on each first line, so a missing part is obvious
        out = [m.replace("\n", f" · {k}/{len(out)}\n", 1) if "\n" in m else f"{m} · {k}/{len(out)}"
               for k, m in enumerate(out, 1)]
    return out


def send(chat_id: str, text: str, html: bool = False, buttons: list | None = None) -> int:
    """Send every message (paced). Keeps going past a failure; raises a summary if any failed. Returns the count.
    html=True: Telegram's HTML mode (links); a part Telegram can't parse is resent as plain text instead.
    buttons: inline keyboard rows ([[{"text", "url" | "callback_data"}]]) under the last message."""
    parts = messages(text, html_mode=html)
    failures = []
    for k, part in enumerate(parts, 1):
        if k > 1:
            time.sleep(PAUSE_S)
        payload = {"chat_id": chat_id, "text": part, "disable_web_page_preview": True}
        if html:
            payload["parse_mode"] = "HTML"
        if buttons and k == len(parts):
            payload["reply_markup"] = {"inline_keyboard": buttons}
        try:
            try:
                _api("sendMessage", payload)
            except TelegramError as e:
                if not html or "parse" not in str(e).lower():
                    raise
                # Never lose the text over markup: same words, no links.
                _api("sendMessage", {**{k2: v for k2, v in payload.items() if k2 != "parse_mode"}, "text": visible(part)})
        except TelegramError as e:
            failures.append(f"message {k} failed: {e}")
    if failures:
        raise TelegramError(f"sent {len(parts) - len(failures)}/{len(parts)}; " + "; ".join(failures))
    return len(parts)


FILE_LIMIT = 50_000_000  # Telegram bots can send files up to 50 MB


def send_file(chat_id: str, name: str, content_type: str, data: bytes, caption: str = "") -> None:
    """Send a file from memory (never written to disk): images as photos, everything else as a document."""
    if len(data) > FILE_LIMIT:
        raise TelegramError(f"{name} is over Telegram's 50 MB limit for bots")
    photo = content_type in ("image/png", "image/jpeg") and len(data) <= 10_000_000  # sendPhoto: 10 MB max
    method, field = ("sendPhoto", "photo") if photo else ("sendDocument", "document")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
    boundary = f"----mailbrief{int(time.time() * 1000)}"
    safe_name = re.sub(r'["\r\n]', "_", name)
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode()]
    if caption:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{caption[:1000]}\r\n'.encode())
    parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{safe_name}"\r\n'
              f"Content-Type: {content_type or 'application/octet-stream'}\r\n\r\n".encode(), data,
              f"\r\n--{boundary}--\r\n".encode()]
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:  # never log the URL: it contains the token
            json.load(r)
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        raise TelegramError(f"{e.code} {body.get('description') or e.reason}") from None


def find_chats() -> list[dict]:
    """Chats that recently messaged the bot: [{id, label}]. Used once, during setup."""
    chats = {}
    for update in _api("getUpdates").get("result", []):
        chat = (update.get("message") or update.get("my_chat_member") or {}).get("chat")
        if chat:
            label = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username")
            chats[str(chat["id"])] = {"id": str(chat["id"]), "label": f"{label} ({chat.get('type')})"}
    return list(chats.values())
