import base64
from datetime import datetime, timedelta, timezone

from mailbrief import threads

T0 = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
ROOT = bytes(range(22))  # real ConversationIndex: 22-byte root, +5 bytes per reply level


def idx(*children: int) -> str:
    return base64.b64encode(ROOT + b"".join(bytes([0, 0, 0, c, 0]) for c in children)).decode()


def msg(id, minutes, index, from_me=False, summary=None, body="body"):
    return {"id": id, "conversation_id": "c1", "received_at": T0 + timedelta(minutes=minutes), "conversation_index": index,
            "from_me": from_me, "sender_name": "Ana", "sender_email": "ana@x.com", "subject": "Thursday?",
            "body_text": body, "classification": {"one_line_summary": summary} if summary else None}


ORIGINAL = msg("a", 0, idx(), summary="Ana asks you to cover Thursday")
MY_REPLY = msg("b", 120, idx(1), from_me=True, body="Sure, I can do it.\n\nOn Tue, Ana wrote:\n> old")
HER_REPLY = msg("c", 180, idx(1, 1), summary="Ana says thanks")
SIDE_REPLY = msg("d", 150, idx(2), summary="Bob replied to the original")  # second reply to the original


def test_logical_order_and_depth():
    ordered = threads.order([HER_REPLY, SIDE_REPLY, ORIGINAL, MY_REPLY])
    # parent before its replies; Ana's reply to *my* reply stays under it even though Bob's came earlier
    assert [m["id"] for m in ordered] == ["a", "b", "c", "d"]
    assert [threads.depth(m) for m in ordered] == [0, 1, 2, 1]


def test_falls_back_to_time_without_index():
    no_index = [dict(HER_REPLY, conversation_index=""), dict(ORIGINAL, conversation_index="")]
    assert [m["id"] for m in threads.order(no_index)] == ["a", "c"]


def test_group():
    other = dict(ORIGINAL, id="z", conversation_id="c2")
    groups = threads.group([HER_REPLY, other, ORIGINAL, MY_REPLY])
    assert set(groups) == {"c1", "c2"} and [m["id"] for m in groups["c1"]] == ["a", "b", "c"]


def test_replied_only_counts_later_messages_from_me():
    thread = threads.order([ORIGINAL, MY_REPLY, HER_REPLY])
    assert threads.replied(ORIGINAL, thread)          # I answered after it arrived
    assert not threads.replied(HER_REPLY, thread)     # nothing from me after her latest
    assert not threads.replied(ORIGINAL, [ORIGINAL, HER_REPLY])


def test_context_lines():
    thread = threads.order([ORIGINAL, MY_REPLY, HER_REPLY])
    lines = threads.context_lines(HER_REPLY, thread)
    assert len(lines) == 2 and "Ana asks you to cover Thursday" in lines[0]
    assert "You · Sure, I can do it." in lines[1] and "old" not in lines[1]  # my reply: body, quote trimmed
    assert threads.context_lines(ORIGINAL, thread) == []
    many = [msg(str(i), i, idx(*([1] * i)), summary=f"s{i}") for i in range(10)]
    assert len(threads.context_lines(many[-1], many)) == threads.CONTEXT_LINES


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
