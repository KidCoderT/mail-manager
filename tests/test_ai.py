from datetime import date

from mailbrief.ai.classifier import BODY_LIMIT, PROMPT, rules_block, trim_body, validate, validate_events
from mailbrief.ai.client import extract_json


def test_extract_json():
    assert extract_json('```json\n{"category": "FYI"}\n```') == {"category": "FYI"}
    assert extract_json('Sure! {"a": {"b": 1}} hope that helps') == {"a": {"b": 1}}
    assert extract_json("no json here") is None
    assert extract_json("{not: valid}") is None


def test_validate():
    ok = validate({"category": "Urgent", "priority": 1, "one_line_summary": " x ", "action_items": ["a", ""], "deadline": "2026-10-20"})
    assert ok == {"category": "Urgent", "priority": 1, "one_line_summary": "x", "action_items": ["a"], "deadline": "2026-10-20",
                  "tags": [], "boost": False, "events": []}
    assert validate({"category": "Spam"}) is None
    assert validate(None) is None
    loose = validate({"category": "FYI", "priority": 9, "deadline": "next Friday"})
    assert loose["priority"] == 3 and loose["deadline"] is None and loose["action_items"] == []


def test_trim_body():
    reply = "Sounds good, see you then.\n\nOn Tue, 14 Oct 2026 at 10:00, Ana <ana@x.com> wrote:\n> old stuff"
    assert trim_body(reply) == "Sounds good, see you then."
    outlook = "Approved.\n\nFrom: Bob\nSent: Monday\nSubject: Re: budget\nold thread"
    assert trim_body(outlook) == "Approved."
    assert len(trim_body("x" * (BODY_LIMIT + 50))) == BODY_LIMIT
    assert trim_body("On Monday we ship.\nThanks") == "On Monday we ship.\nThanks"  # not a quote header


def test_tags_and_rules_prompt():
    topics = ("Networking", "CS jobs")
    c = validate({"category": "FYI", "priority": 2, "tags": ["networking", "Spam", "CS jobs", "Networking", 3], "boost": "yes"}, topics)
    assert c["tags"] == ["Networking", "CS jobs"] and c["boost"] is False  # only your topics; boost must be true itself
    assert validate({"category": "FYI", "tags": "Networking", "boost": True}, topics)["tags"] == []
    assert validate({"category": "FYI", "boost": True}, topics)["boost"] is True
    assert rules_block(None) == "" and rules_block({"profile": "", "topics": []}) == ""  # benchmarked prompt untouched
    block = rules_block({"profile": "CS student", "topics": [{"name": "Networking", "description": "meetups"}]})
    assert "CS student" in block and "Networking = meetups" in block and '"tags"' in block and '"boost"' in block


def test_events():
    got = date(2026, 10, 20)
    raw = [
        {"name": "  Google  talk ", "detail": "Resume review,\n free pizza", "date": "2026-10-23", "time": "7pm",
         "place": "COM3", "link": "https://x.com/g", "signup_deadline": "2026-10-22"},
        {"name": "Google talk", "date": "2026-10-23"},                      # repeat: dropped
        {"name": "Fair", "date": "2025-01-01", "link": "javascript:alert(1)", "signup_deadline": "soon"},  # bad date/link
        {"name": "", "date": "2026-10-24"}, "not a dict", {"date": "2026-10-24"},  # no name
        {"name": "Movie night", "date": "2026-13-40", "time": "x" * 50},   # impossible date, long time
    ]
    ev = validate_events(raw, got)
    assert [e["name"] for e in ev] == ["Google talk", "Fair", "Movie night"]
    assert ev[0] == {"name": "Google talk", "detail": "Resume review, free pizza", "date": "2026-10-23", "time": "7pm",
                     "place": "COM3", "link": "https://x.com/g", "signup_deadline": "2026-10-22"}
    assert ev[1]["date"] is None and ev[1]["link"] is None and ev[1]["signup_deadline"] is None  # >1 year off; not http
    assert ev[2]["date"] is None and len(ev[2]["time"]) == 30
    assert len(validate_events([{"name": f"e{i}"} for i in range(15)], got)) == 10
    assert validate_events("nope") == [] and validate_events(None) == []
    assert validate({"category": "FYI", "events": raw}, (), got)["events"] == ev
    assert '"events"' in PROMPT and "Received date" in PROMPT


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
