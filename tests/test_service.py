import os
import tempfile
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from mailbrief import service
from mailbrief.service import Busy, due_slots, lock, next_slot, parse_schedule, run_args

SG = ZoneInfo("Asia/Singapore")


def at(s: str) -> datetime:  # "2026-10-17 07:30" (a Saturday) in Singapore time
    return datetime.fromisoformat(s).replace(tzinfo=SG)


def test_parse_every_form():
    s = parse_schedule("daily 07:30; weekdays 8:05 this-week; sat,sun 10:00; day-1 09:00 last-month;")
    assert [e["scope"] for e in s] == ["new", "this-week", "new", "last-month"]
    assert s[0]["weekdays"] == set(range(7)) and s[1]["weekdays"] == {0, 1, 2, 3, 4} and s[1]["at"] == time(8, 5)
    assert s[2]["weekdays"] == {5, 6} and s[3]["monthdays"] == {1} and not s[3]["weekdays"]
    assert parse_schedule("Mon,day-15 07:00")[0] == {"weekdays": {0}, "monthdays": {15}, "at": time(7), "scope": "new"}


def test_parse_rejects_bad_entries():
    for bad in ("", " ; ", "daily", "daily 25:00", "daily 7.30", "funday 07:30", "day-32 07:30", "daily 07:30 yesterday",
                "daily 07:30 new extra"):
        try:
            parse_schedule(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_due_slots_daily_and_catch_up_latest_only():
    daily = parse_schedule("daily 07:30")
    assert due_slots(at("2026-10-17 07:29"), daily, at("2026-10-16 07:30")) == []
    assert due_slots(at("2026-10-17 07:30"), daily, at("2026-10-16 07:30")) == [(at("2026-10-17 07:30"), "new")]
    # Off for 3 days: one catch-up run, not three.
    assert due_slots(at("2026-10-17 12:00"), daily, at("2026-10-14 07:30")) == [(at("2026-10-17 07:30"), "new")]
    # Already done: nothing.
    assert due_slots(at("2026-10-17 12:00"), daily, at("2026-10-17 07:30")) == []


def test_due_slots_per_scope_weekly_and_monthly():
    s = parse_schedule("daily 07:30; sun 20:00 this-week; day-1 09:00 last-month")
    # Away from Sat 10 Oct to Sat 17 Oct 21:00: the latest daily, last Sunday's weekly; day-1 was before the gap.
    due = due_slots(at("2026-10-17 21:00"), s, at("2026-10-10 08:00"))
    assert due == [(at("2026-10-11 20:00"), "this-week"), (at("2026-10-17 07:30"), "new")]
    assert (at("2026-11-01 09:00"), "last-month") in due_slots(at("2026-11-01 10:00"), s, at("2026-10-31 08:00"))


def test_weekends_and_next_slot():
    s = parse_schedule("weekdays 08:00; weekends 10:00")
    assert next_slot(at("2026-10-17 09:00"), s) == at("2026-10-17 10:00")  # Saturday
    assert next_slot(at("2026-10-18 10:00"), s) == at("2026-10-19 08:00")  # Sunday after → Monday
    assert next_slot(at("2026-10-17 09:00"), parse_schedule("day-31 09:00")) == at("2026-10-31 09:00")


def test_run_args_commit_only_for_new():
    assert run_args("new") == ["run", "--send", "--quiet", "--commit"]
    assert run_args("this-week") == ["run", "--send", "--quiet", "--digest", "this-week"]


def test_lock_is_exclusive_and_released():
    old = service.DATA
    with tempfile.TemporaryDirectory() as d:
        service.DATA = Path(d)
        try:
            with lock("run"):
                assert service.is_locked("run")
                try:
                    with lock("run"):
                        raise AssertionError("second lock was granted")
                except Busy:
                    pass
                assert not service.is_locked("serve")  # different name, different lock
            assert not service.is_locked("run")
        finally:
            service.DATA = old


if __name__ == "__main__":
    os.environ.setdefault("DEFAULT_TIMEZONE", "Asia/Singapore")
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
