from mailbrief.main import _kept


def test_kept_keeps_only_real_classifications():
    real = {"category": "FYI", "priority": 4, "events": [{"name": "Talk"}]}
    assert _kept({"classification": real}) == real  # filed away later: its summary and events survive
    for none in (None, {}, {"classification": None}, {"classification": {"category": "Elsewhere"}},
                 {"classification": {"category": "Sent"}}, {"classification": {"category": "Unclassified"}}):
        assert _kept(none) is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
