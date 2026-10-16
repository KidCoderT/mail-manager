"""Parse the JSON that Outlook on the web fetches for its own message list.

The format is internal and undocumented, so instead of depending on endpoint
names this walks any payload and picks out objects that look like messages.
All format knowledge lives in this file.
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


def _lower(d: dict) -> dict:
    return {k.lower(): v for k, v in d.items() if isinstance(k, str)}


def _id(value) -> str | None:
    if isinstance(value, dict):
        value = _lower(value).get("id")
    return value if isinstance(value, str) else None


def _sender(low: dict) -> str:
    senders = low.get("uniquesenders")
    if isinstance(senders, list) and senders and isinstance(senders[0], str):
        return senders[0]
    frm = low.get("from")
    if isinstance(frm, dict):
        box = _lower(frm)
        box = box.get("mailbox") or box.get("emailaddress") or {}
        if isinstance(box, dict):
            box = _lower(box)
            return box.get("name") or box.get("emailaddress") or box.get("address") or ""
    return ""


def _parse_time(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _to_message(d: dict) -> dict | None:
    low = _lower(d)
    if "conversationtopic" in low:
        kind, subject, when, ident = "conversation", low["conversationtopic"], low.get("lastdeliverytime"), low.get("conversationid")
    elif "subject" in low:
        when = low.get("datetimereceived") or low.get("receiveddatetime")
        kind, subject, ident = "item", low["subject"], low.get("itemid") or low.get("id")
    else:
        return None
    if not isinstance(subject, str) or not isinstance(when, str):
        return None
    received = _parse_time(when)
    if received is None:
        return None
    return {
        "kind": kind,
        "id": _id(ident),
        "subject": subject or "(no subject)",
        "sender": _sender(low),
        "received_at": received,
    }


def _walk(node, found: list) -> None:
    if isinstance(node, dict):
        msg = _to_message(node)
        if msg:
            found.append(msg)
            return
        children = node.values()
    elif isinstance(node, list):
        children = node
    else:
        return
    for child in children:
        _walk(child, found)


def parse_messages(payloads: list) -> list[dict]:
    """Messages found in captured JSON payloads, newest first, deduplicated."""
    found: list[dict] = []
    for payload in payloads:
        _walk(payload, found)
    # Conversation view and item view describe the same mail; prefer conversations if present.
    if any(m["kind"] == "conversation" for m in found):
        found = [m for m in found if m["kind"] == "conversation"]
    unique = {}
    for m in found:
        unique.setdefault(m["id"] or (m["subject"], m["received_at"]), m)
    return sorted(unique.values(), key=lambda m: m["received_at"], reverse=True)


def view_total(payloads: list) -> int | None:
    """How many conversations/items Outlook says the folder holds (TotalConversationsInView etc.)."""
    best = None
    stack = list(payloads)
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str) and k.lower() in ("totalconversationsinview", "totalitemsinview") and isinstance(v, int):
                    best = v if best is None else max(best, v)
                else:
                    stack.append(v)
        elif isinstance(node, list):
            stack.extend(node)
    return best


def received_on(messages: list[dict], day: date, tz: ZoneInfo) -> list[dict]:
    return [m for m in messages if m["received_at"].astimezone(tz).date() == day]
