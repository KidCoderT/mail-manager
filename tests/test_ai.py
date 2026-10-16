from mailbrief.ai.classifier import BODY_LIMIT, trim_body, validate
from mailbrief.ai.client import extract_json


def test_extract_json():
    assert extract_json('```json\n{"category": "FYI"}\n```') == {"category": "FYI"}
    assert extract_json('Sure! {"a": {"b": 1}} hope that helps') == {"a": {"b": 1}}
    assert extract_json("no json here") is None
    assert extract_json("{not: valid}") is None


def test_validate():
    ok = validate({"category": "Urgent", "priority": 1, "one_line_summary": " x ", "action_items": ["a", ""], "deadline": "2026-10-20"})
    assert ok == {"category": "Urgent", "priority": 1, "one_line_summary": "x", "action_items": ["a"], "deadline": "2026-10-20"}
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
