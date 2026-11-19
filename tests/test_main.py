from mailbrief.main import _kept


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
