from datetime import datetime, timezone
from pathlib import Path

from demo.run import sample_emails, tour
from mailbrief import archive, events, threads


def test_demo_has_threads_and_upcoming_events():
    now = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
    emails = sample_emails(now)
    assert len(emails) == 15
    assert all(e["sender_email"].endswith("@example.edu") for e in emails)
    assert len(threads.group(emails)["lab-demo"]) == 3
    assert len(events.upcoming(emails, now.date(), 14)) == 7


def test_offline_tour_restores_paths_and_never_uses_real_archive(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    real = tmp_path / "data" / "archive"
    monkeypatch.setattr(archive, "ARCHIVE_DIR", real)
    for view in ("emails", "email", "thread", "events", "digest", "chat"):
        assert tour(view) == 0
        assert Path.cwd() == tmp_path and archive.ARCHIVE_DIR == real
        assert not (tmp_path / "data").exists()
    assert "OFFLINE DEMO" in capsys.readouterr().out
