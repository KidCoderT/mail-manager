from mailbrief.browser.owa_network import BODY_CAP, parse_items, parse_messages, preview_records, view_total

# Shaped like Outlook's FindConversation response (conversation view).
CONVERSATIONS = {
    "Body": {
        "Conversations": [
            {
                "ConversationId": {"Id": "c1"},
                "ConversationTopic": "Q3 numbers",
                "UniqueSenders": ["Ana"],
                "LastDeliveryTime": "2026-10-16T08:12:33+08:00",
                "ItemIds": [{"__type": "ItemId:#Exchange", "ChangeKey": "k", "Id": "i-a"}, {"Id": "i-b"}],
                "Preview": "Need the Q3 figures",
                "HasAttachments": True,
            },
            {
                "ConversationId": {"Id": "c2"},
                "ConversationTopic": "Late night",
                "UniqueSenders": ["Bob"],
                "LastDeliveryTime": "2026-10-15T15:30:00Z",
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


def test_conversation_item_ids_and_preview_fallback():
    c1 = next(m for m in parse_messages([CONVERSATIONS]) if m["id"] == "c1")
    assert c1["item_ids"] == ["i-a", "i-b"] and c1["preview"] == "Need the Q3 figures"
    [rec] = preview_records([c1])
    assert rec["body_source"] == "preview" and rec["body_text"] == "Need the Q3 figures" and rec["has_attachments"]


# Shaped like a real GetItem response (key names from a shape-only probe of Outlook).
GETITEM = {
    "Body": {
        "ResponseMessages": {
            "Items": [
                {
                    "ResponseClass": "Success",
                    "ResponseCode": "NoError",
                    "Items": [
                        {
                            "__type": "Message:#Exchange",
                            "ItemId": {"Id": "i-a", "ChangeKey": "k"},
                            "ConversationId": {"__type": "ItemId:#Exchange", "Id": "c1"},
                            "Subject": "Q3 numbers",
                            "DateTimeReceived": "2026-10-16T00:12:33Z",
                            "From": {"Mailbox": {"Name": "Ana", "EmailAddress": "ana@x.com", "RoutingType": "SMTP", "MailboxType": "OneOff"}},
                            "Body": {"BodyType": "Text", "Value": "Hi,\r\n\r\n\r\n   please   send Q3.\r\n" + "x" * 30_000},
                            "Importance": "High",
                            "IsRead": False,
                            "HasAttachments": True,
                            "Attachments": [{"Name": "q3.xlsx", "Size": 10, "AttachmentId": {"Id": "a"}}],
                        }
                    ],
                },
                {"ResponseClass": "Error", "ResponseCode": "ErrorItemNotFound", "Items": []},
            ]
        }
    }
}


def test_parse_items():
    [r] = parse_items(GETITEM)
    assert (r["id"], r["conversation_id"], r["sender_name"], r["sender_email"]) == ("i-a", "c1", "Ana", "ana@x.com")
    assert r["body_text"].startswith("Hi,\n\nplease send Q3.") and len(r["body_text"]) == BODY_CAP
    assert r["attachment_names"] == ["q3.xlsx"] and r["importance"] == "High" and r["is_read"] is False
    assert r["received_at"].isoformat() == "2026-10-16T00:12:33+00:00" and r["body_source"] == "getitem"
    assert parse_items({"unexpected": 1}) == []


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
