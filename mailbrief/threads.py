"""Thread structure: which emails belong together, in what order, and whether you already replied.

Outlook never edits an email when someone replies or forwards: the reply is a new email with the same
ConversationId. ConversationIndex (base64) is Exchange's thread-tree key: a 22-byte root, plus 5 bytes
per reply level. Sorting by the decoded bytes puts every parent before its replies, siblings by time.
"""

import base64
import binascii

from mailbrief.ai.classifier import trim_body

ROOT_BYTES, CHILD_BYTES = 22, 5
CONTEXT_LINES = 6


def _index(msg: dict) -> bytes:
    try:
        return base64.b64decode(msg.get("conversation_index") or "")
    except (binascii.Error, ValueError):
        return b""


def order(msgs: list[dict]) -> list[dict]:
    """A thread's messages in logical order (parents before replies); by time if any index is missing."""
    if all(_index(m) for m in msgs):
        return sorted(msgs, key=lambda m: (_index(m), m["received_at"]))
    return sorted(msgs, key=lambda m: m["received_at"])


def depth(msg: dict) -> int:
    """0 for a thread's first email, 1 for a reply to it, 2 for a reply to that…"""
    return max(0, (len(_index(msg)) - ROOT_BYTES) // CHILD_BYTES)


def group(msgs: list[dict]) -> dict[str, list[dict]]:
    """{conversation_id: ordered messages}. Messages without a conversation id are their own thread."""
    threads: dict[str, list[dict]] = {}
    for m in msgs:
        threads.setdefault(m.get("conversation_id") or m["id"], []).append(m)
    return {cid: order(ms) for cid, ms in threads.items()}


def _who(msg: dict) -> str:
    return "You" if msg.get("from_me") else (msg.get("sender_name") or msg.get("sender_email") or "?")


def _gist(msg: dict) -> str:
    summary = (msg.get("classification") or {}).get("one_line_summary")
    if summary and not msg.get("from_me"):
        return summary
    return " ".join(trim_body(msg.get("body_text") or "").split())[:150] or msg.get("subject", "")


def context_lines(email: dict, thread: list[dict]) -> list[str]:
    """Up to CONTEXT_LINES messages that come before `email` in its (ordered) thread, oldest first."""
    ids = [m["id"] for m in thread]
    earlier = thread[: ids.index(email["id"])] if email["id"] in ids else [m for m in thread if m["received_at"] < email["received_at"]]
    return [f"{m['received_at']:%d %b %H:%M} · {_who(m)} · {_gist(m)}" for m in earlier[-CONTEXT_LINES:]]


def replied(email: dict, thread: list[dict]) -> bool:
    """True if you sent something in this thread after this email arrived."""
    return any(m.get("from_me") and m["received_at"] > email["received_at"] for m in thread)
