from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from mailbrief.browser.owa_network import (
    UnsafeRequest,
    categories_getitem_body,
    check_request,
    master_categories,
    master_list_body,
    merge_categories,
    parse_categories,
    parse_update,
    remove_everywhere_body,
    update_categories_body,
)
from mailbrief import rules
from mailbrief.labels import ALL_LABELS, is_custom, labelled, labels_for, pending, select

rules.RULES_PATH = Path(__file__).with_name("no-such-rules.json")  # never read your real data/rules.json

SG = ZoneInfo("Asia/Singapore")
H = {"RequestServerVersion": "V2018"}


def email(i, category="Urgent", priority=1, **extra):
    return {"id": f"id{i}", "received_at": datetime(2026, 10, i, 9, tzinfo=SG), "in_inbox": True, "from_me": False,
            "body_source": "getitem", "classification": {"category": category, "priority": priority}, **extra}


def refused(action, body):
    try:
        check_request(action, body)
    except UnsafeRequest:
        return True
    return False


def test_labels_for():
    assert labels_for(email(1)) == ["MB: Urgent", "MB: P1"]
    assert labels_for(email(1, "Low Priority", 5)) == ["MB: Low Priority", "MB: P5"]
    assert labels_for(email(1, "FYI", None)) == ["MB: FYI"]  # no valid priority → category only
    for skip in (email(1, "Sent"), email(1, "Elsewhere"), email(1, "Unclassified"), email(1, from_me=True),
                 email(1, in_inbox=False), email(1, body_source="preview")):
        assert labels_for(skip) == []
    assert set(ALL_LABELS) >= {"MB: Needs Reply", "MB: Meetings", "MB: P3"} and len(ALL_LABELS) == 11


def test_merge_keeps_your_categories_and_swaps_ours():
    assert merge_categories(["Red category", "MB: FYI", "Project X", "MB: P4"], ["MB: Urgent", "MB: P1"]) == \
        ["Red category", "Project X", "MB: Urgent", "MB: P1"]
    assert merge_categories(["Red category", "MB: FYI"], []) == ["Red category"]
    assert merge_categories([], ["MB: FYI"]) == ["MB: FYI"]


def test_pending_labelled_and_cleared():
    done = email(1, outlook_labels=["MB: Urgent", "MB: P1"])
    changed = email(2, "FYI", 4, outlook_labels=["MB: Urgent", "MB: P1"])  # reclassified since
    new = email(3)
    cleared = email(4, outlook_labels=[], labels_cleared=True)
    gone = email(5, outlook_gone=True)
    sent = email(6, "Sent")
    all_ = [done, changed, new, cleared, gone, sent]
    assert [e["id"] for e in pending(all_)] == ["id2", "id3"]
    assert [e["id"] for e in pending(all_, include_cleared=True)] == ["id2", "id3", "id4"]
    assert [e["id"] for e in labelled(all_)] == ["id1", "id2"]


def test_select_by_period_days_all():
    emails = [email(d) for d in (1, 10, 17, 18)]
    today = date(2026, 10, 18)
    assert len(select(emails, None, None, today, SG)) == 4
    assert [e["id"] for e in select(emails, None, 2, today, SG)] == ["id17", "id18"]  # today and yesterday
    assert [e["id"] for e in select(emails, "this-week", None, today, SG)] == ["id17", "id18"]  # Mon 12 – Sun 18
    assert len(select(emails, "this-month", None, today, SG)) == 4 and not select(emails, "last-month", None, today, SG)


def test_parse_categories_and_update():
    ids = ["a", "b"]
    resp = {"Body": {"ResponseMessages": {"Items": [
        {"ResponseClass": "Success", "Items": [{"ItemId": {"Id": "a", "ChangeKey": "CK"}, "Categories": ["X"]}]},
        {"ResponseClass": "Error", "ResponseCode": "ErrorItemNotFound"}]}}}
    assert parse_categories(resp, ids) == {"a": ("CK", ["X"]), "b": None}
    upd = {"Body": {"ResponseMessages": {"Items": [{"ResponseClass": "Success"},
                                                   {"ResponseClass": "Error", "ResponseCode": "ErrorItemNotFound"}]}}}
    assert parse_update(upd, ids) == {"a": "ok", "b": "gone"}


def test_built_requests_pass_the_guard():
    check_request("GetItem", categories_getitem_body(H, ["a"]))
    body = update_categories_body(H, [("a", "CK", ["Mine", "MB: FYI"]), ("b", "", [])])
    changes = body["Body"]["ItemChanges"]
    assert changes[0]["ItemId"]["ChangeKey"] == "CK" and "ChangeKey" not in changes[1]["ItemId"]
    assert changes[1]["Updates"][0]["__type"] == "DeleteItemField:#Exchange"  # empty → delete the field
    check_request("UpdateItem", body)
    mcl = master_list_body(add=[("MB: Urgent", 0)], now="2026-10-18T00:00:00Z", new_id=lambda: "uuid")
    assert mcl["request"]["AddCategoryList"][0] == {"Name": "MB: Urgent", "Color": 0, "Id": "uuid",
                                                    "LastTimeUsed": "2026-10-18T00:00:00Z", "KeyboardShortcut": 0}
    check_request("UpdateMasterCategoryList", mcl)
    check_request("UpdateMasterCategoryList", master_list_body(remove=["MB: P1"]))
    check_request("ApplyCategoryOperation", remove_everywhere_body("MB: P1"))


def test_guard_refuses_everything_else():
    for action in ("MoveItem", "DeleteItem", "SendItem", "ApplyConversationAction", "CreateItem", "UpdateFolder"):
        assert refused(action, {})
    body = update_categories_body(H, [("a", "CK", ["MB: FYI"])])
    body["Body"]["ItemChanges"][0]["Updates"][0]["Path"]["FieldURI"] = "IsRead"  # mark as read: refused
    assert refused("UpdateItem", body)
    body = update_categories_body(H, [("a", "CK", ["MB: FYI"])])
    body["Body"]["ItemChanges"][0]["Updates"][0]["Item"]["IsRead"] = True  # sneaked into the Item: refused
    assert refused("UpdateItem", body)
    body = update_categories_body(H, [("a", "CK", ["MB: FYI"])])
    body["Body"]["MessageDisposition"] = "SendAndSaveCopy"
    assert refused("UpdateItem", body)
    assert refused("UpdateItem", update_categories_body(H, []))  # no changes
    assert refused("UpdateMasterCategoryList", master_list_body(add=[("Red category", 0)]))  # not ours
    assert refused("UpdateMasterCategoryList", master_list_body(remove=["Project X"]))
    assert refused("ApplyCategoryOperation", remove_everywhere_body("Red category"))


def test_master_categories_from_startup():
    startup = [{"owaUserConfig": {"MasterCategoryList": {"MasterList": [{"Name": "MB: FYI", "Color": 7}, {"Name": "Red", "Color": 0}],
                                                         "DefaultList": []}}}]
    assert master_categories(startup) == {"MB: FYI": 7, "Red": 0}
    assert master_categories([{"other": 1}]) is None


def test_your_own_labels():
    r = rules.validate({"courses": ["CS1101S"], "senders": [{"match": "tan@nus.edu.sg", "label": "Prof Tan", "priority": 1}],
                        "topics": [{"name": "Networking", "description": "meetups"}]})
    course = email(1, "FYI", 4, subject="CS1101S: Mission 7")
    assert labels_for(course, r) == ["MB: FYI", "MB: P4", "MB: CS1101S"]
    prof = email(2, "Needs Reply", 3, sender_email="tan@nus.edu.sg")
    assert labels_for(prof, r) == ["MB: Needs Reply", "MB: P1", "MB: Prof Tan"]  # priority floor raises MB: P<n>
    # A retired rule's label stays as history; one whose rule still exists but no longer matches goes.
    old = email(3, "FYI", 4, subject="hello", outlook_labels=["MB: FYI", "MB: P4", "MB: MA1521", "MB: CS1101S"])
    assert labels_for(old, r) == ["MB: FYI", "MB: P4", "MB: MA1521"]
    assert labels_for(email(4, "Sent", subject="CS1101S"), r) == []  # still only classified inbox mail
    assert is_custom("MB: CS1101S") and not is_custom("MB: FYI") and not is_custom("Red category")
    assert pending([email(5)]) and labels_for(email(5)) == ["MB: Urgent", "MB: P1"]  # no rules file: built-ins only


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
