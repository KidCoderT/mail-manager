from mailbrief.main import _kept


def test_caught_up_digest_excludes_mail_after_the_slot_day(monkeypatch):
    import io
    from datetime import date, datetime, timezone

    from mailbrief import archive
    from mailbrief.main import digest_set

    emails = [{"id": str(day), "received_at": datetime(2026, 11, day, tzinfo=timezone.utc),
               "classification": {"category": "FYI"}} for day in (20, 22, 23)]
    monkeypatch.setattr(archive, "load", lambda: (emails, []))
    found = digest_set("this-week", [], {}, timezone.utc, io.StringIO(), as_of=date(2026, 11, 22))
    assert [e["id"] for e in found] == ["20", "22"]


def test_kept_keeps_only_real_classifications():
    real = {"category": "FYI", "priority": 4, "events": [{"name": "Talk"}]}
    assert _kept({"classification": real}) == real  # filed away later: its summary and events survive
    for none in (None, {}, {"classification": None}, {"classification": {"category": "Elsewhere"}},
                 {"classification": {"category": "Sent"}}, {"classification": {"category": "Unclassified"}}):
        assert _kept(none) is None


def test_setup_failures_get_one_line_and_bugs_keep_their_traceback():
    from cryptography.fernet import InvalidToken

    from mailbrief.main import _explain

    assert "SESSION_ENCRYPTION_KEY" in _explain(InvalidToken()) and "mailbrief login" in _explain(InvalidToken())
    fake = type("Error", (Exception,), {"__module__": "playwright._impl._errors"})
    assert "playwright install chromium" in _explain(fake("BrowserType.launch: Executable doesn't exist at /ms-playwright/chromium"))
    assert "network" in _explain(fake("Page.goto: net::ERR_INTERNET_DISCONNECTED at https://outlook.office.com/mail/"))
    assert _explain(fake("Locator.click: something else")) is None and _explain(KeyError("x")) is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
