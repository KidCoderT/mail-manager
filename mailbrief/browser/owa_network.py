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
    "ToRecipients", "CcRecipients",
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
IMAGE_MIN = 15_000     # attached images smaller than this are icons
INLINE_MIN = 30_000    # inline images (in the body): signature logos are smaller, posters are hundreds of KB
IMAGE_MAX = 5_000_000  # ponytail: bigger posters are skipped, not resized (resizing needs Pillow)
IMAGES_PER_EMAIL = 4  # the NUS endpoint refuses more: "At most 4 image(s) may be provided in one prompt"
IMAGE_BUDGET = 8_000_000  # bytes of images per email, attachments and linked images together


def addresses(recipients: list | None) -> list[str]:
    """Lowercased addresses from a To/Cc list (entries are bare mailboxes or wrapped in "Mailbox")."""
    out = []
    for r in recipients or []:
        if isinstance(r, dict):
            addr = (r.get("Mailbox") or r).get("EmailAddress") or ""
            if addr:
                out.append(addr.lower())
    return out


def attachment_list(attachments: list) -> list[dict]:
    """Every file attachment's id, name, size, type and inline flag (never its content): what the chat can send.
    Attached emails (ItemAttachment) aren't files and are left out."""
    return [{"id": _id(a["AttachmentId"]), "name": a.get("Name") or "file", "size": a.get("Size") or 0,
             "content_type": a.get("ContentType") or "", "inline": bool(a.get("IsInline"))}
            for a in attachments or []
            if _id(a.get("AttachmentId")) and "ItemAttachment" not in str(a.get("__type", ""))]


def image_attachments(attachments: list) -> list[dict]:
    """Image attachments worth showing the vision model: attached images, and inline ones big enough to be
    posters rather than signature logos. In order, within IMAGES_PER_EMAIL and IMAGE_BUDGET."""
    keep, used = [], 0
    for a in attachments or []:
        name, ctype, size = a.get("Name") or "", a.get("ContentType") or "", a.get("Size") or 0
        is_image = ctype.startswith("image/") or name.lower().endswith(IMAGE_EXTS)
        low = INLINE_MIN if a.get("IsInline") else IMAGE_MIN
        if is_image and low <= size <= IMAGE_MAX and used + size <= IMAGE_BUDGET and _id(a.get("AttachmentId")):
            keep.append({"id": _id(a["AttachmentId"]), "name": name, "content_type": ctype, "size": size})
            used += size
            if len(keep) == IMAGES_PER_EMAIL:
                break
    return keep


_SKIP_IMAGE = re.compile(r"logo|icon|avatar|facebook|instagram|linkedin|twitter|tiktok|youtube|whatsapp|telegram|"
                         r"spacer|pixel|track|beacon|/open\.|badge|signature|social", re.I)


def image_urls(html: str) -> list[str]:
    """Linked images in an HTML body worth downloading: https, no query string (tracking images usually carry one),
    not obviously an icon or logo by name. In page order, de-duplicated.
    ponytail: name heuristics; web_images' size check catches the icons they miss."""
    urls = []
    for src in re.findall(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", html or "", re.I):
        src = src.strip().replace("&amp;", "&")
        if src.lower().startswith("https://") and "?" not in src and not _SKIP_IMAGE.search(src) and src not in urls:
            urls.append(src)
    return urls


def html_getitem_body(header: dict, ids: list[str]) -> dict:
    """Read-only GetItem for just the HTML body, to find linked images (the HTML is never kept)."""
    body = getitem_body(header, ids)
    shape = body["Body"]["ItemShape"]
    shape["BodyType"] = "HTML"
    shape["AdditionalProperties"] = [{"__type": "PropertyUri:#Exchange", "FieldURI": "Body"}]
    return body


def html_bodies(response: dict) -> dict[str, str]:
    """{email id: HTML body} from an html_getitem_body response."""
    out = {}
    for msg in (response.get("Body") or {}).get("ResponseMessages", {}).get("Items", []):
        if msg.get("ResponseClass") == "Success":
            for it in msg.get("Items", []):
                if _id(it.get("ItemId")):
                    out[_id(it["ItemId"])] = (it.get("Body") or {}).get("Value") or ""
    return out


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
                "attachments": attachment_list(it.get("Attachments")),
                "to": addresses(it.get("ToRecipients")),
                "cc": addresses(it.get("CcRecipients")),
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
        "attachments": [],
        "to": [],
        "cc": [],
        "is_read": None,
        "importance": c["importance"],
        "body_source": "preview",
        "conversation_index": "",
        "in_reply_to": "",
        "internet_message_id": "",
        "in_inbox": True,
        "from_me": False,
    } for c in conversations]


# ── Categories (Outlook "labels") ─────────────────────────────────────────────────────────────────
# The only writes MailBrief ever makes. Shapes copied from what Outlook itself sends (UpdateMasterCategoryList,
# ApplyCategoryOperation) plus the standard per-email UpdateItem. check_request() is the code-enforced guard.

PREFIX = "MB: "  # every category MailBrief creates or removes starts with this
READ_ACTIONS = {"GetItem", "GetAttachment"}
WRITE_ACTIONS = {"UpdateItem", "UpdateMasterCategoryList", "ApplyCategoryOperation"}


class UnsafeRequest(Exception):
    pass


def categories_getitem_body(header: dict, ids: list[str]) -> dict:
    """Read-only GetItem for just the categories (the reply's ItemId also carries the ChangeKey)."""
    return {
        "__type": "GetItemJsonRequest:#Exchange",
        "Header": header,
        "Body": {
            "__type": "GetItemRequest:#Exchange",
            "ItemShape": {"__type": "ItemResponseShape:#Exchange", "BaseShape": "IdOnly",
                          "AdditionalProperties": [{"__type": "PropertyUri:#Exchange", "FieldURI": "Categories"}]},
            "ItemIds": [{"__type": "ItemId:#Exchange", "Id": i} for i in ids],
        },
    }


def parse_categories(response: dict, ids: list[str]) -> dict[str, tuple[str, list[str]] | None]:
    """{id: (change_key, categories)} in request order; None for an item that's gone (deleted or moved away)."""
    out: dict[str, tuple[str, list[str]] | None] = {}
    for i, msg in zip(ids, (response.get("Body") or {}).get("ResponseMessages", {}).get("Items", [])):
        items = msg.get("Items") or []
        if msg.get("ResponseClass") != "Success" or not items:
            out[i] = None
            continue
        item_id = items[0].get("ItemId") or {}
        out[i] = (item_id.get("ChangeKey") or "", list(items[0].get("Categories") or []))
    return out


def merge_categories(current: list[str], wanted: list[str]) -> list[str]:
    """Your own categories kept in their order; every MailBrief one replaced by `wanted`."""
    return [c for c in current if not c.startswith(PREFIX)] + list(wanted)


def update_categories_body(header: dict, changes: list[tuple[str, str, list[str]]]) -> dict:
    """UpdateItem that sets (or, when empty, deletes) ONLY the Categories field of each (id, change_key, categories)."""
    def update(categories):
        path = {"__type": "PropertyUri:#Exchange", "FieldURI": "Categories"}
        if not categories:
            return {"__type": "DeleteItemField:#Exchange", "Path": path}
        return {"__type": "SetItemField:#Exchange", "Path": path, "Item": {"__type": "Message:#Exchange", "Categories": categories}}

    return {
        "__type": "UpdateItemJsonRequest:#Exchange",
        "Header": header,
        "Body": {
            "__type": "UpdateItemRequest:#Exchange",
            "ConflictResolution": "AlwaysOverwrite",
            "MessageDisposition": "SaveOnly",
            "SuppressReadReceipts": True,
            "ItemChanges": [{
                "__type": "ItemChange:#Exchange",
                "ItemId": {"__type": "ItemId:#Exchange", "Id": i, **({"ChangeKey": ck} if ck else {})},
                "Updates": [update(cats)],
            } for i, ck, cats in changes],
        },
    }


def parse_update(response: dict, ids: list[str]) -> dict[str, str]:
    """{id: "ok" | "gone" | "failed: <code>"} for an UpdateItem reply, in request order."""
    out = {}
    for i, msg in zip(ids, (response.get("Body") or {}).get("ResponseMessages", {}).get("Items", [])):
        code = msg.get("ResponseCode") or "?"
        out[i] = "ok" if msg.get("ResponseClass") == "Success" else "gone" if code == "ErrorItemNotFound" else f"failed: {code}"
    return out


def master_list_body(add: list[tuple[str, int]] = (), remove: list[str] = (), now: str = "", new_id=None) -> dict:
    """Outlook's own UpdateMasterCategoryList request: add (name, colour) pairs and/or remove names."""
    import uuid

    new_id = new_id or (lambda: str(uuid.uuid4()))
    return {"request": {
        "__type": "UpdateMasterCategoryListRequest:#Exchange",
        "AddCategoryList": [{"Name": n, "Color": c, "Id": new_id(), "LastTimeUsed": now, "KeyboardShortcut": 0}
                            for n, c in add],
        "RemoveCategoryList": list(remove),
        "ChangeCategoryColorList": [],
        "UpdateCategoryLastTimeUsedList": [],
        "ChangeCategoryKeyboardShortcutList": [],
    }}


def remove_everywhere_body(name: str) -> dict:
    """Outlook's ApplyCategoryOperation, Action 1: take this category off every email in the mailbox."""
    return {"request": {"__type": "ApplyCategoryOperationRequest:#Exchange",
                        "categoryOperation": {"Action": 1, "CategoryName": name}}}


def master_categories(payloads: list) -> dict[str, int] | None:
    """{name: colour} from StartupData's owaUserConfig.MasterCategoryList.MasterList; None if not found."""
    stack = list(payloads)
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            mcl = node.get("MasterCategoryList")
            if isinstance(mcl, dict) and isinstance(mcl.get("MasterList"), list):
                return {c.get("Name"): c.get("Color") for c in mcl["MasterList"] if isinstance(c, dict)}
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None


def check_request(action: str, body: dict) -> None:
    """The guard: every service.svc call passes here first. Reads are free; writes may touch categories only."""
    if action in READ_ACTIONS:
        return
    if action not in WRITE_ACTIONS:
        raise UnsafeRequest(f"{action} is not an allowed Outlook action")
    if action == "UpdateItem":
        b = body.get("Body") or {}
        changes = b.get("ItemChanges") or []
        if b.get("MessageDisposition") != "SaveOnly" or not changes:
            raise UnsafeRequest("UpdateItem must be SaveOnly with at least one change")
        for ch in changes:
            for u in ch.get("Updates") or [None]:
                if not isinstance(u, dict) or u.get("__type") not in ("SetItemField:#Exchange", "DeleteItemField:#Exchange") \
                        or (u.get("Path") or {}).get("FieldURI") != "Categories" \
                        or set((u.get("Item") or {}).keys()) - {"__type", "Categories"}:
                    raise UnsafeRequest("UpdateItem may only set or delete the Categories field")
    elif action == "UpdateMasterCategoryList":
        r = body.get("request") or {}
        names = [c.get("Name", "") for c in r.get("AddCategoryList") or []] + list(r.get("RemoveCategoryList") or [])
        if any(r.get(k) for k in ("ChangeCategoryColorList", "UpdateCategoryLastTimeUsedList", "ChangeCategoryKeyboardShortcutList")) \
                or not names or not all(str(n).startswith(PREFIX) for n in names):
            raise UnsafeRequest("the category list may only gain or lose MailBrief (\"MB: \") categories")
    elif action == "ApplyCategoryOperation":
        name = ((body.get("request") or {}).get("categoryOperation") or {}).get("CategoryName", "")
        if not str(name).startswith(PREFIX):
            raise UnsafeRequest("only MailBrief (\"MB: \") categories can be removed everywhere")
