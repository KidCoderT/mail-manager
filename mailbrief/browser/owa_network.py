"""Parse the JSON that Outlook on the web fetches for its own message list.

The format is internal and undocumented, so instead of depending on endpoint
names this walks any payload and picks out objects that look like messages.
All format knowledge lives in this file.
"""

import re
from datetime import datetime, timezone

BODY_CAP = 20_000


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
    item_ids = low.get("itemids") if kind == "conversation" else [ident]
    return {
        "kind": kind,
        "id": _id(ident),
        "subject": subject or "(no subject)",
        "sender": _sender(low),
        "received_at": received,
        "item_ids": [i for i in map(_id, item_ids or []) if i],
        # Every message in the thread, in any folder (your Sent replies too); ItemIds is inbox only.
        "global_item_ids": [i for i in map(_id, low.get("globalitemids") or item_ids or []) if i],
        "preview": low.get("preview") if isinstance(low.get("preview"), str) else "",
        "has_attachments": bool(low.get("hasattachments")),
        "importance": low.get("importance") or "Normal",
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


_GETITEM_FIELDS = (
    "Subject", "From", "DateTimeReceived", "Body", "Importance",
    "IsRead", "HasAttachments", "Attachments", "ConversationId",
    "ConversationIndex", "InReplyTo", "InternetMessageId", "DateTimeSent",
)


def getitem_body(header: dict, ids: list[str]) -> dict:
    """JSON for a read-only GetItem call (plain-text bodies). `header` is copied from Outlook's own request."""
    return {
        "__type": "GetItemJsonRequest:#Exchange",
        "Header": header,
        "Body": {
            "__type": "GetItemRequest:#Exchange",
            "ItemShape": {
                "__type": "ItemResponseShape:#Exchange",
                "BaseShape": "IdOnly",
                "BodyType": "Text",
                "AdditionalProperties": [{"__type": "PropertyUri:#Exchange", "FieldURI": f} for f in _GETITEM_FIELDS],
            },
            "ItemIds": [{"__type": "ItemId:#Exchange", "Id": i} for i in ids],
        },
    }


def _clean(text: str) -> str:
    text = re.sub(r"[ \t\u00a0]+", " ", text.replace("\r\n", "\n"))
    text = re.sub(r"\s*\n\s*\n\s*", "\n\n", text).strip()
    return text[:BODY_CAP]


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
IMAGE_MIN, IMAGE_MAX, IMAGES_PER_EMAIL = 15_000, 5_000_000, 3


def image_attachments(attachments: list) -> list[dict]:
    """Image attachments worth showing the vision model: real images, not inline signature logos."""
    keep = []
    for a in attachments or []:
        name, ctype, size = a.get("Name") or "", a.get("ContentType") or "", a.get("Size") or 0
        is_image = ctype.startswith("image/") or name.lower().endswith(IMAGE_EXTS)
        if is_image and not a.get("IsInline") and IMAGE_MIN <= size <= IMAGE_MAX and _id(a.get("AttachmentId")):
            keep.append({"id": _id(a["AttachmentId"]), "name": name, "content_type": ctype, "size": size})
    return keep[:IMAGES_PER_EMAIL]


def parse_items(response: dict) -> list[dict]:
    """EmailRecords from a GetItem response. Items that failed (e.g. deleted meanwhile) are skipped."""
    records = []
    for msg in (response.get("Body") or {}).get("ResponseMessages", {}).get("Items", []):
        if msg.get("ResponseClass") != "Success":
            continue
        for it in msg.get("Items", []):
            received = _parse_time(it.get("DateTimeReceived") or "")
            if received is None:
                continue
            box = (it.get("From") or {}).get("Mailbox") or {}
            records.append({
                "id": _id(it.get("ItemId")),
                "conversation_id": _id(it.get("ConversationId")),
                "sender_name": box.get("Name") or "",
                "sender_email": box.get("EmailAddress") or "",
                "subject": it.get("Subject") or "(no subject)",
                "received_at": received,
                "body_text": _clean((it.get("Body") or {}).get("Value") or ""),
                "has_attachments": bool(it.get("HasAttachments")),
                "attachment_names": [a.get("Name") for a in it.get("Attachments") or [] if a.get("Name")],
                "image_attachments": image_attachments(it.get("Attachments")),
                "is_read": bool(it.get("IsRead")),
                "importance": it.get("Importance") or "Normal",
                "body_source": "getitem",
                # Thread position: ConversationIndex is Exchange's thread-tree key (see threads.py).
                "conversation_index": it.get("ConversationIndex") or "",
                "in_reply_to": it.get("InReplyTo") or "",
                "internet_message_id": it.get("InternetMessageId") or "",
                # Set by the reader, which knows the inbox ids and your address.
                "in_inbox": True,
                "from_me": False,
            })
    return records


def find_user_email(payloads: list) -> str | None:
    """Your own address, from Outlook's StartupData (owaUserConfig.SessionSettings.UserEmailAddress)."""
    stack = list(payloads)
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            settings = node.get("SessionSettings")
            if isinstance(settings, dict) and "@" in str(settings.get("UserEmailAddress", "")):
                return settings["UserEmailAddress"]
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None


def preview_records(conversations: list[dict]) -> list[dict]:
    """Fallback when GetItem fails: one record per conversation, body = Outlook's list preview."""
    return [{
        "id": c["id"],
        "conversation_id": c["id"],
        "sender_name": c["sender"],
        "sender_email": "",
        "subject": c["subject"],
        "received_at": c["received_at"],
        "body_text": _clean(c["preview"]),
        "has_attachments": c["has_attachments"],
        "attachment_names": [],
        "image_attachments": [],
        "is_read": None,
        "importance": c["importance"],
        "body_source": "preview",
        "conversation_index": "",
        "in_reply_to": "",
        "internet_message_id": "",
        "in_inbox": True,
        "from_me": False,
    } for c in conversations]
