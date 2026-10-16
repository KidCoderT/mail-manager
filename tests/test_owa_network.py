from datetime import date
from zoneinfo import ZoneInfo

from mailbrief.browser.owa_network import parse_messages, received_on, view_total

SGT = ZoneInfo("Asia/Singapore")

# Shaped like Outlook's FindConversation response (conversation view).
CONVERSATIONS = {
    "Body": {
        "Conversations": [
            {
                "ConversationId": {"Id": "c1"},
                "ConversationTopic": "Q3 numbers",
                "UniqueSenders": ["Ana"],
                "LastDeliveryTime": "2026-10-16T08:12:33+08:00",
            },
            {
                "ConversationId": {"Id": "c2"},
                "ConversationTopic": "Late night",
                "UniqueSenders": ["Bob"],
                "LastDeliveryTime": "2026-10-15T15:30:00Z",  # 23:30 SGT on the 15th
            },
            {"ConversationId": {"Id": "c3"}, "ConversationTopic": "", "LastDeliveryTime": "2026-10-16T01:00:00Z"},
        ]
    }
}

# Shaped like FindItem (item view).
ITEMS = {
    "Body": {
        "ResponseMessages": {
            "Items": [
                {
                    "RootFolder": {
                        "Items": [
                            {
                                "ItemId": {"Id": "i1"},
                                "Subject": "Standup moved",
                                "DateTimeReceived": "2026-10-16T02:00:00Z",
                                "From": {"Mailbox": {"Name": "Cara", "EmailAddress": "cara@x.com"}},
                            },
                            {"Subject": "missing date"},
                        ]
                    }
                }
            ]
        }
    }
}


def test_conversations():
    msgs = parse_messages([CONVERSATIONS, CONVERSATIONS])  # captured twice -> deduped
    assert [m["id"] for m in msgs] == ["c3", "c1", "c2"], msgs
    assert msgs[1]["sender"] == "Ana"
    assert msgs[0]["subject"] == "(no subject)"


def test_items_and_preference():
    items = parse_messages([ITEMS])
    assert len(items) == 1 and items[0]["sender"] == "Cara" and items[0]["subject"] == "Standup moved"
    mixed = parse_messages([ITEMS, CONVERSATIONS])  # same mail in both views -> conversations win
    assert {m["kind"] for m in mixed} == {"conversation"}


def test_today_in_local_timezone():
    msgs = parse_messages([CONVERSATIONS])
    today = received_on(msgs, date(2026, 10, 16), SGT)
    assert [m["id"] for m in today] == ["c3", "c1"]  # c2 is the 15th in SGT


def test_view_total():
    assert view_total([{"Body": {"TotalConversationsInView": 286, "Conversations": []}}, {"x": 1}]) == 286
    assert view_total([{"a": 1}]) is None


def test_garbage_is_ignored():
    assert parse_messages([None, "x", 3, [], {"a": [{"b": 1}]}]) == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
