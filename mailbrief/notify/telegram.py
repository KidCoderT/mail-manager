"""Send-only Telegram bot. It never polls: getUpdates runs only during `mailbrief add-destination`.

A digest that fits goes as one message. A longer one goes as one message per section (header + first
section, then KEY EVENTS, NOISE, …); a section that is still too long is split on line breaks, with
"<HEADING> (cont.)" on the follow-ups. Every message of a multi-part digest is tagged "· k/n".
"""

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
        if is_heading(line):
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


def _chunk_block(lines: list[str]) -> list[str]:
    """One block → messages ≤ LIMIT, split on line breaks; follow-ups start with '<HEADING> (cont.)'."""
    heading = next((l.strip() for l in lines if is_heading(l)), None)
    cont = f"{heading.split('(')[0].rstrip(' :')} (cont.)" if heading else None
    # Balanced, not greedy: 4100 units → two ~2050 messages, never 3990 + a lonely 110.
    pieces_needed = -(-size("\n".join(lines)) // LIMIT)
    target = min(LIMIT, -(-size("\n".join(lines)) // pieces_needed) + 200)
    chunks, current = [], []
    for line in lines:
        for piece in (_hard_cut(line, LIMIT - 100) if size(line) > LIMIT - 100 else [line]):
            if current and size("\n".join(current + [piece])) > target:
                chunks.append(current)
                current = [cont] if cont else []
            current.append(piece)
    if current:
        chunks.append(current)
    return ["\n".join(_trim(c)) for c in chunks if _trim(c)]


def messages(text: str) -> list[str]:
    """The Telegram messages for `text`: one if it fits, else one per section (split further if needed)."""
    text = text.strip()
    if size(text) <= LIMIT:
        return [text] if text else []
    out = [m for block in split_sections(text) for m in _chunk_block(_trim(block))]
    if len(out) > 1:  # "· k/n" on each first line, so a missing part is obvious
        out = [m.replace("\n", f" · {k}/{len(out)}\n", 1) if "\n" in m else f"{m} · {k}/{len(out)}"
               for k, m in enumerate(out, 1)]
    return out


def send(chat_id: str, text: str) -> int:
    """Send every message (paced). Keeps going past a failure; raises a summary if any failed. Returns the count."""
    parts = messages(text)
    failures = []
    for k, part in enumerate(parts, 1):
        if k > 1:
            time.sleep(PAUSE_S)
        try:
            _api("sendMessage", {"chat_id": chat_id, "text": part, "disable_web_page_preview": True})
        except TelegramError as e:
            failures.append(f"message {k} failed: {e}")
    if failures:
        raise TelegramError(f"sent {len(parts) - len(failures)}/{len(parts)}; " + "; ".join(failures))
    return len(parts)


def find_chats() -> list[dict]:
    """Chats that recently messaged the bot: [{id, label}]. Used once, during setup."""
    chats = {}
    for update in _api("getUpdates").get("result", []):
        chat = (update.get("message") or update.get("my_chat_member") or {}).get("chat")
        if chat:
            label = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username")
            chats[str(chat["id"])] = {"id": str(chat["id"]), "label": f"{label} ({chat.get('type')})"}
    return list(chats.values())
