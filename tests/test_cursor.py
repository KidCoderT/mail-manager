from datetime import datetime, timedelta, timezone

from mailbrief import cursor as cur

T0 = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)


def rec(id, minutes, source="getitem"):
    return {"id": id, "received_at": T0 + timedelta(minutes=minutes), "body_source": source}


def test_first_run_looks_back_24h():
    c = {"last_processed_at": None, "recent_ids": []}
    assert cur.since(c, now=T0) == T0 - timedelta(hours=24)


def test_select_new_and_dedupe():
    c = {"last_processed_at": T0.isoformat(), "recent_ids": ["seen"]}
    records = [rec("old", -1), rec("seen", 0), rec("same-second", 0), rec("new", 5)]
    assert [r["id"] for r in cur.select_new(records, c)] == ["same-second", "new"]


def test_advance():
    c = {"last_processed_at": T0.isoformat(), "recent_ids": [f"x{i}" for i in range(cur.KEEP_IDS)]}
    out = cur.advance(c, [rec("a", 3), rec("b", 9)])
    assert out["last_processed_at"] == (T0 + timedelta(minutes=9)).isoformat()
    assert out["recent_ids"][-2:] == ["a", "b"] and len(out["recent_ids"]) == cur.KEEP_IDS
    assert cur.advance(c, []) == c


def test_advance_refuses_previews():
    c = {"last_processed_at": None, "recent_ids": []}
    try:
        cur.advance(c, [rec("a", 1), rec("p", 2, source="preview")])
    except ValueError:
        return
    raise AssertionError("advance accepted preview-only records")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
