import tempfile
from pathlib import Path

from mailbrief import rules
from mailbrief.rules import RulesError, add, effective, empty, load, matches, remove, save, validate

R = validate({
    "profile": "Year 2 CS student looking for internships and hackathons",
    "courses": ["cs1101s", {"code": "MA1521", "priority": 2}],
    "senders": [{"match": "tan@nus.edu.sg", "label": "Prof Tan", "direct_only": True, "priority": 1},
                {"match": "career", "label": "Careers", "boost": True}],
    "topics": [{"name": "Networking", "description": "career fairs, meetups, hackathons", "priority": 2}],
})


def mail(**kw):
    base = {"subject": "", "sender_name": "", "sender_email": "", "body_text": "", "direct": False,
            "classification": {"category": "FYI", "priority": 4, "tags": [], "boost": False}}
    return {**base, **kw}


def bad(data):
    try:
        validate(data)
    except RulesError:
        return True
    return False


def test_validate():
    assert R["courses"][0] == {"code": "CS1101S", "priority": None, "boost": False}  # bare strings, upper-cased
    assert validate({}) == empty()
    assert bad({"courses": ["Urgent"]})  # clashes with a built-in label
    assert bad({"courses": ["P2"]})
    assert bad({"courses": ["CS1101S", "cs1101s"]})  # same label twice
    assert bad({"senders": [{"match": "x@y.z"}]})  # no label
    assert bad({"senders": [{"match": "", "label": "X"}]})
    assert bad({"topics": [{"name": "Jobs"}]})  # no description
    assert bad({"courses": [{"code": "CS1101S", "priority": 7}]})
    assert bad({"courses": [{"code": "A,B"}]})
    assert bad({"courses": "CS1101S"}) and bad([])


def test_courses():
    labels = lambda e: [m[0] for m in matches(e, R)]
    assert labels(mail(subject="[CS1101S] Mission 7 released")) == ["MB: CS1101S"]
    assert labels(mail(body_text="Reminder for cs1101s tutorial")) == ["MB: CS1101S"]
    assert labels(mail(subject="CS1101SX and XCS1101S")) == []  # whole codes only
    assert labels(mail(body_text="x" * 1200 + " CS1101S")) == []  # only the start of the body
    assert labels(mail(subject="MA1521 + CS1101S")) == ["MB: CS1101S", "MB: MA1521"]


def test_senders_and_direct():
    labels = lambda e: [m[0] for m in matches(e, R)]
    assert labels(mail(sender_email="TAN@nus.edu.sg", direct=True)) == ["MB: Prof Tan"]
    assert labels(mail(sender_email="tan@nus.edu.sg", direct=False)) == []  # class announcement, not private
    assert labels(mail(sender_name="NUS Career Centre")) == ["MB: Careers"]  # name substring


def test_topics_boost_and_priority():
    tagged = mail(classification={"category": "FYI", "priority": 4, "tags": ["Networking"], "boost": True})
    eff = effective(tagged, R)
    assert eff == {"labels": ["MB: Networking"], "priority": 2, "boosted": True}
    not_for_you = mail(classification={"category": "FYI", "priority": 4, "tags": ["Networking"], "boost": False})
    assert effective(not_for_you, R) == {"labels": ["MB: Networking"], "priority": 2, "boosted": False}
    no_profile = {**R, "profile": ""}
    assert effective(not_for_you, no_profile)["boosted"]  # no profile: any topic tag boosts
    gone_topic = mail(classification={"category": "FYI", "priority": 4, "tags": ["Old topic"]})
    assert effective(gone_topic, R)["labels"] == []
    careers = effective(mail(sender_name="Career Fair"), R)  # rule boost without a floor → at least P2
    assert careers["boosted"] and careers["priority"] == 2
    prof = effective(mail(sender_email="tan@nus.edu.sg", direct=True), R)
    assert prof["priority"] == 1 and not prof["boosted"]
    assert effective(mail(), R) == {"labels": [], "priority": 4, "boosted": False}


def test_add_remove_save_load():
    r = add(empty(), "courses", {"code": "cs2040s"})
    r = add(r, "courses", {"code": "CS2040S", "priority": 3})  # same key: replaced, not duplicated
    assert r["courses"] == [{"code": "CS2040S", "priority": 3, "boost": False}]
    r, gone = remove(r, "courses", "cs2040s")
    assert gone["code"] == "CS2040S" and r["courses"] == []
    assert remove(r, "courses", "nope")[1] is None
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "rules.json"
        assert load(path) == empty()  # no file yet
        save(R, path)
        assert load(path) == R
        path.write_text("{not json", encoding="utf-8")
        try:
            load(path)
            raise AssertionError("broken file loaded")
        except RulesError:
            pass


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
