from datetime import date, datetime
from zoneinfo import ZoneInfo

from mailbrief import rules
from mailbrief.events import render, upcoming
from mailbrief.notify.telegram import messages

SG = ZoneInfo("Asia/Singapore")
TODAY = date(2026, 10, 22)  # a Thursday


def ev(name, d=None, **kw):
    return {"name": name, "detail": None, "date": d, "time": None, "place": None, "link": None,
            "signup_deadline": None, **kw}


def mail(i, events, category="Newsletter", **kw):
    return {"id": f"m{i}", "sender_name": f"Sender {i}", "subject": "", "body_text": "",
            "received_at": datetime(2026, 10, 20, 9, tzinfo=SG),
            "classification": {"category": category, "priority": 4, "tags": kw.pop("tags", []),
                               "boost": kw.pop("boost", False), "events": events}, **kw}


def test_window_undated_and_skipped():
    emails = [
        mail(1, [ev("Past talk", "2026-10-21"), ev("Today fair", "2026-10-22"), ev("Last day", "2026-11-05"),
                 ev("Too far", "2026-11-06"), ev("No date")]),
        mail(2, [ev("Undated but new")]),
        mail(3, [ev("My own invite", "2026-10-25")], category="Sent"),   # your sent mail: ignored
    ]
    names = sorted(e["name"] for e in upcoming(emails, TODAY, 14, new_ids={"m2"}))
    assert names == ["Last day", "Today fair", "Undated but new"]  # old undated ones don't repeat forever


def test_merge_new_and_boost():
    r = rules.validate({"profile": "CS student", "topics": [{"name": "Networking", "description": "meetups"}]})
    emails = [
        mail(1, [ev("Google SWE Talk!", "2026-10-23", time="7pm")]),
        mail(2, [ev("google swe talk", "2026-10-23", place="COM3 LT19", detail="Resume review")],
             tags=["Networking"], boost=True),
    ]
    [one] = upcoming(emails, TODAY, 14, new_ids={"m2"}, your_rules=r)
    assert (one["time"], one["place"], one["detail"]) == ("7pm", "COM3 LT19", "Resume review")  # gaps filled
    assert one["new"] and one["boosted"]
    [plain] = upcoming(emails[:1], TODAY, 14)
    assert not plain["new"] and not plain["boosted"]


def test_render():
    events = [
        {**ev("Hack info", "2026-10-25", time="10am", place="Zoom"), "new": False, "boosted": False},
        {**ev("Late talk", "2026-10-23", time="9pm"), "new": False, "boosted": False},
        {**ev("Google talk", "2026-10-23", time="7pm", place="COM3", detail="Free pizza", link="https://x.com/g",
              signup_deadline="2026-10-22"), "new": True, "boosted": True},
        {**ev("Early thing", "2026-10-23", time="10:30am", signup_deadline="2026-10-21"), "new": False, "boosted": False},
        {**ev("Volunteer call"), "new": True, "boosted": False},
    ]
    text = render(events, TODAY, 14)
    assert text.splitlines() == [
        "📅 UPCOMING EVENTS · next 14 days (5)",
        "",
        "FRI 23 OCT",
        "⭐🆕 7pm · Google talk · COM3",            # boosted first within its day
        "   Free pizza",
        "   sign up by Thu 22 Oct · https://x.com/g",
        "• 10:30am · Early thing",
        "   sign-up closed",
        "• 9pm · Late talk",
        "",
        "SUN 25 OCT",
        "• 10am · Hack info · Zoom",
        "",
        "DATE NOT GIVEN",
        "🆕 Volunteer call",
    ]
    assert render([], TODAY) is None


def test_past_window_and_render():
    emails = [mail(1, [ev("Five days ago", "2026-10-17", signup_deadline="2026-10-15", link="https://x.com/p"),
                       ev("Eleven days ago", "2026-10-11"), ev("Today talk", "2026-10-22"),
                       ev("Next week", "2026-10-29")])]
    names = lambda found: sorted(e["name"] for e in found)  # noqa: E731
    assert names(upcoming(emails, TODAY, 14, past=10)) == ["Five days ago", "Next week", "Today talk"]
    assert names(upcoming(emails, TODAY, 0, past=10)) == ["Five days ago", "Today talk"]  # nothing ahead
    assert names(upcoming(emails, TODAY, 14)) == ["Next week", "Today talk"]  # default: no past

    both = render(upcoming(emails, TODAY, 14, past=10), TODAY, 14, past=10).splitlines()
    assert both[0] == "📅 EVENTS · last 10 days + next 14 days (3)"
    assert both[2:5] == ["SAT 17 OCT (PAST)", "• Five days ago", "   https://x.com/p"]  # no "sign-up closed"
    assert "THU 22 OCT" in both and "THU 22 OCT (PAST)" not in both  # today isn't past
    only_past = render(upcoming(emails, TODAY, 0, past=10), TODAY, 0, past=10)
    assert only_past.splitlines()[0] == "📅 PAST EVENTS · last 10 days (2)"

    many = [{**ev(f"Old {d}-{i} " + "x" * 60, f"2026-10-{d:02d}", detail="y" * 150), "new": False, "boosted": False}
            for d in range(1, 21) for i in range(4)]
    parts = messages(render(many, TODAY, 0, past=30))
    assert len(parts) > 1 and all("(PAST)" in p.splitlines()[0] or p.startswith("📅") for p in parts)


def test_long_calendar_splits_per_day():
    events = [{**ev(f"Event {d}-{i} " + "x" * 60, f"2026-10-{d}", detail="y" * 150), "new": False, "boosted": False}
              for d in range(22, 30) for i in range(5)]
    parts = messages(render(events, TODAY, 14))
    assert len(parts) > 1
    assert all(p.splitlines()[0].startswith(("📅", "THU", "FRI", "SAT", "SUN", "MON", "TUE", "WED")) for p in parts)


def test_html_links():
    from mailbrief.links import anchor
    emails = [mail(1, [ev("Talk <live> & Q&A", "2026-10-23", detail="Pizza & drinks")]),
              mail(2, [ev("Talk <live> & Q&A", "2026-10-23", place="LT19")])]
    found = upcoming(emails, TODAY, 14)
    assert found[0]["email_id"] == "m1"  # merged: the first email's link
    lines = render(found, TODAY, 14, html=True).splitlines()
    assert lines[3] == f"• Talk &lt;live&gt; &amp; Q&amp;A · LT19 {anchor('m1')}"
    assert lines[4] == "   Pizza &amp; drinks"
    assert "<a " not in render(found, TODAY, 14)  # plain text (terminal) has no links


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
