"""Send-only Telegram bot. It never polls: getUpdates runs only during `mailbrief add-destination`."""

import json
import os
import urllib.request

LIMIT = 4096


def _api(method: str, payload: dict | None = None) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set (create a bot with @BotFather)")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:  # never log the URL: it contains the token
        return json.load(r)


def split(text: str, limit: int = LIMIT) -> list[str]:
    """Chunks of at most `limit` chars, broken on line boundaries where possible."""
    parts, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:  # a single overlong line: hard split
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            parts.append(current)
            current = ""
        current += line
    if current.strip():
        parts.append(current)
    return [p.rstrip("\n") for p in parts]


def send(chat_id: str, text: str) -> None:
    for part in split(text):
        _api("sendMessage", {"chat_id": chat_id, "text": part, "disable_web_page_preview": True})


def find_chats() -> list[dict]:
    """Chats that recently messaged the bot: [{id, label}]. Used once, during setup."""
    chats = {}
    for update in _api("getUpdates").get("result", []):
        chat = (update.get("message") or update.get("my_chat_member") or {}).get("chat")
        if chat:
            label = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username")
            chats[str(chat["id"])] = {"id": str(chat["id"]), "label": f"{label} ({chat.get('type')})"}
    return list(chats.values())
