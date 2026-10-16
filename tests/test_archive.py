import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet

from mailbrief import archive

SGT = ZoneInfo("Asia/Singapore")
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=SGT)


def email(id, when, subject="s"):
    return {"id": id, "subject": subject, "sender_name": "A", "sender_email": "a@x.com", "received_at": when,
            "body_text": "secret body", "attachment_names": [], "image_attachments": [], "body_source": "getitem"}


RESULT = {"category": "FYI", "priority": 3}


def fresh():
    os.environ["SESSION_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    os.environ.pop("ARCHIVE_DAYS", None)
    archive.ARCHIVE_DIR = Path(tempfile.mkdtemp()) / "archive"


def test_encrypted_roundtrip_monthly():
    fresh()
    [path] = archive.save([email("1", NOW)], [RESULT], "digest!", plain=False, tz=SGT, now=NOW)
    assert path.name == "2026-10.enc" and b"secret body" not in path.read_bytes()
    emails, digests = archive.load()
    assert emails[0]["body_text"] == "secret body" and emails[0]["received_at"] == NOW
    assert emails[0]["classification"] == RESULT and digests[0]["text"] == "digest!"


def test_plain_is_readable_json():
    fresh()
    [path] = archive.save([email("1", NOW)], [RESULT], None, plain=True, tz=SGT, now=NOW)
    assert path.name == "2026-10.json" and json.loads(path.read_text())["emails"][0]["body_text"] == "secret body"


def test_rerun_never_duplicates_and_months_split():
    fresh()
    sept = NOW - timedelta(days=30)
    archive.save([email("1", NOW), email("2", sept)], [RESULT, RESULT], None, plain=False, tz=SGT, now=NOW)
    archive.save([email("1", NOW, subject="updated")], [RESULT], None, plain=False, tz=SGT, now=NOW)
    emails, _ = archive.load()
    assert [e["id"] for e in emails] == ["1", "2"] and emails[0]["subject"] == "updated"
    assert archive.months() == ["2026-09", "2026-10"]
    assert set(archive.known(["1", "nope"])) == {"1"}


def test_sorted_across_timezone_offsets():
    fresh()
    utc = datetime(2026, 10, 16, 0, 30, tzinfo=timezone.utc)                              # 08:30 SGT
    ist = datetime(2026, 10, 16, 5, 45, tzinfo=timezone(timedelta(hours=5, minutes=30)))  # 08:15 SGT
    archive.save([email("utc", utc), email("ist", ist)], [RESULT, RESULT], None, plain=True, tz=SGT, now=NOW)
    stored = json.loads(archive._path("2026-10", True).read_text())["emails"]
    assert [e["id"] for e in stored] == ["ist", "utc"]


def test_format_switch_keeps_one_file():
    fresh()
    archive.save([email("1", NOW)], [RESULT], None, plain=False, tz=SGT, now=NOW)
    archive.save([email("2", NOW)], [RESULT], None, plain=True, tz=SGT, now=NOW)
    assert sorted(p.name for p in archive.ARCHIVE_DIR.iterdir()) == ["2026-10.json"]
    assert {e["id"] for e in archive.load()[0]} == {"1", "2"}


def test_migrates_old_daily_files():
    fresh()
    archive.ARCHIVE_DIR.mkdir(parents=True)
    rec = lambda id, when: {**email(id, when), "received_at": when.isoformat(), "classification": RESULT}
    (archive.ARCHIVE_DIR / "2026-10-15.json").write_text(json.dumps({"emails": [rec("a", NOW - timedelta(days=1))], "digests": []}))
    from mailbrief.storage.crypto import encrypt
    (archive.ARCHIVE_DIR / "2026-10-16.enc").write_bytes(encrypt({"emails": [rec("b", NOW)], "digests": [{"at": NOW.isoformat(), "text": "d"}]}))
    assert archive.months() == ["2026-10"]
    assert not any(p.stem.count("-") == 2 for p in archive.ARCHIVE_DIR.iterdir())  # daily files gone
    emails, digests = archive.load()
    assert {e["id"] for e in emails} == {"a", "b"} and len(digests) == 1


def test_wrong_key_is_a_clear_error():
    fresh()
    archive.save([email("1", NOW)], [RESULT], None, plain=False, tz=SGT, now=NOW)
    os.environ["SESSION_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    try:
        archive.load()
    except archive.ArchiveError as e:
        assert "2026-10.enc" in str(e)
        return
    raise AssertionError("expected ArchiveError")


def test_period_ranges():
    thu = date(2026, 10, 15)
    assert archive.period_range("this-week", thu) == (date(2026, 10, 12), None)  # Monday
    assert archive.period_range("this-month", thu) == (date(2026, 10, 1), None)
    assert archive.period_range("last-month", thu) == (date(2026, 9, 1), date(2026, 10, 1))
    assert archive.period_range("older", thu) == (None, date(2026, 9, 1))
    jan = date(2027, 1, 5)  # year rollover
    assert archive.period_range("last-month", jan) == (date(2026, 12, 1), date(2027, 1, 1))
    assert archive.period_range("older", jan) == (None, date(2026, 12, 1))
    e = lambda d: {"received_at": datetime(d.year, d.month, d.day, 12, tzinfo=SGT)}
    assert archive.in_period(e(date(2026, 9, 30)), "last-month", thu, SGT)
    assert not archive.in_period(e(date(2026, 9, 30)), "older", thu, SGT)
    assert archive.in_period(e(date(2026, 8, 31)), "older", thu, SGT)


def test_prune_by_month():
    fresh()
    for days_ago in (0, 40, 80):
        archive.save([email(str(days_ago), NOW - timedelta(days=days_ago))], [RESULT], None, plain=False, tz=SGT, now=NOW)
    assert archive.prune(NOW.date()) == 0 and len(archive.months()) == 3  # default: keep forever
    os.environ["ARCHIVE_DAYS"] = "30"  # cutoff 16 Sep: September still has days inside the window
    assert archive.prune(NOW.date()) == 1
    assert archive.months() == ["2026-09", "2026-10"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
