"""Exercise the run pipeline's data-loss boundaries without a browser or network."""

from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mailbrief import archive, cursor, events, index, labels, main, rules
from mailbrief.ai import classifier, client
from mailbrief.ai import digest as digest_module
from mailbrief.browser import connect, outlook_reader
from mailbrief.session import manager


@pytest.fixture
def pipeline(monkeypatch):
    import playwright.sync_api

    now = datetime.now(timezone.utc)
    record = {"id": "mail-1", "conversation_id": "thread-1", "received_at": now,
              "in_inbox": True, "from_me": False, "body_source": "getitem", "subject": "Example",
              "sender_name": "Invented Sender", "sender_email": "sender@example.edu", "body_text": "Hello"}
    result = {"expired": False, "messages": [{"id": "thread-1", "received_at": now}],
              "auth": {}, "me": "demo@example.edu", "total": 1, "urls": []}
    browser = Mock()
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", lambda: nullcontext(None))
    monkeypatch.setattr(connect, "get_browser", lambda *a, **kw: browser)
    monkeypatch.setattr(client, "settings", lambda: ("https://ai.example.com/v1", "test"))
    monkeypatch.setattr(manager, "load", lambda: {"state": {}, "user_agent": "test"})
    monkeypatch.setattr(manager, "save", Mock())
    monkeypatch.setattr(outlook_reader, "read_inbox", lambda page: result)
    monkeypatch.setattr(outlook_reader, "fetch_emails", lambda *args: ([record], True))
    monkeypatch.setattr(outlook_reader, "collect_images", lambda *args: {record["id"]: []})
    monkeypatch.setattr(archive, "load", lambda: ([], []))
    save = Mock(return_value=[])
    monkeypatch.setattr(archive, "save", save)
    monkeypatch.setattr(archive, "prune", Mock())
    monkeypatch.setattr(rules, "load", rules.empty)
    monkeypatch.setattr(cursor, "load", lambda: {"last_processed_at": None, "recent_ids": []})
    cursor_save = Mock()
    monkeypatch.setattr(cursor, "save", cursor_save)
    monkeypatch.setattr(classifier, "classify", lambda *args: {"category": "FYI", "priority": 3})
    monkeypatch.setattr(digest_module, "digest", lambda *args, **kw: "Example digest")
    monkeypatch.setattr(labels, "run_step", Mock())
    monkeypatch.setattr(index, "update", Mock(return_value=(0, 0)))
    monkeypatch.setattr(events, "build", lambda *args, **kw: None)
    deliver = Mock(return_value=True)
    monkeypatch.setattr(main, "deliver", deliver)
    return SimpleNamespace(result=result, record=record, save=save, cursor_save=cursor_save, deliver=deliver, browser=browser)


def test_failed_archive_does_not_advance_cursor(pipeline):
    pipeline.save.side_effect = OSError("disk full")
    assert main.run(commit=True, send=True, quiet=True) == 4
    pipeline.cursor_save.assert_not_called()
    pipeline.deliver.assert_called_once()
    pipeline.browser.close.assert_called_once()


def test_invalid_pruning_setting_does_not_prevent_saving(pipeline, monkeypatch):
    monkeypatch.setattr(archive, "prune", Mock(side_effect=ValueError("30d")))
    assert main.run(commit=True, quiet=True) == 0
    assert pipeline.save.call_count == 2
    assert pipeline.cursor_save.call_args.args[0]["recent_ids"] == ["mail-1"]


def test_failed_delivery_keeps_cursor(pipeline):
    pipeline.deliver.return_value = False
    assert main.run(commit=True, send=True, quiet=True) == 1
    pipeline.cursor_save.assert_not_called()


def test_broken_inbox_format_fails_instead_of_reporting_success(pipeline):
    pipeline.result["messages"] = []
    assert main.run(quiet=True) == 5
    pipeline.save.assert_not_called()


def test_previews_are_not_archived_and_cannot_advance_cursor(pipeline):
    pipeline.record["body_source"] = "preview"
    assert main.run(commit=True, quiet=True) == 4
    assert pipeline.save.call_args_list[0].args[0] == []
    pipeline.cursor_save.assert_not_called()
