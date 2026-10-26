import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet

os.environ.setdefault("SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode())  # a throwaway key, never yours

from mailbrief import index  # noqa: E402

SG = ZoneInfo("Asia/Singapore")
WORDS = ["midterm", "hackathon", "fee", "pizza", "schema", "library"]


def mail(i, subject, body, days=0, sender="Ana", cat="FYI", **kw):
    return {"id": f"e{i}", "subject": subject, "sender_name": sender, "sender_email": f"{sender.lower()}@x.com",
            "body_text": body, "received_at": datetime(2026, 10, 20 - days, 9, tzinfo=SG), "body_source": "getitem",
            "classification": {"category": cat, "priority": 3, "one_line_summary": subject}, **kw}


def fake_embed(texts):
    """Deterministic 'meaning': one dimension per keyword, so tests know which email is closest."""
    calls.append(len(texts))
    return [[float(t.lower().count(w)) + 0.01 for w in WORDS] for t in texts]


calls: list[int] = []


def test_chunks():
    e = mail(1, "Notes", ("Para one. " * 120) + "\n\n" + ("Para two. " * 120)
             + "\n\nOn Mon, 1 Oct 2026, Bob <b@x.com> wrote:\n> quoted old stuff",
             attachment_names=["a.pdf"], classification={"category": "FYI", "events": [{"name": "Talk", "date": "2026-10-23"}]})
    out = index.chunks(e)
    assert out[0].startswith("Subject: Notes\nFrom: Ana <ana@x.com>") and "Attachments: a.pdf" in out[0] and "Event: Talk 2026-10-23" in out[0]
    body = out[1:]
    assert len(body) >= 2 and all(len(c) <= index.CHUNK + 50 for c in body)
    assert all(c.startswith("Notes\n") for c in body) and not any("quoted old stuff" in c for c in body)  # quotes trimmed
    long = mail(2, "Huge", "word " * 20_000)
    assert len(index.chunks(long)) == 1 + index.MAX_BODY_CHUNKS  # capped
    assert not index.indexable({**e, "body_source": "preview"})


def test_update_incremental_and_search():
    emails = [mail(1, "Midterm logistics", "The midterm is on Saturday in MPSH. Bring a cheat sheet."),
              mail(2, "Hackathon signups", "Hack and roll hackathon signups open, free pizza.", days=2, sender="Hackers"),
              mail(3, "Fee reminder", "Your fee is due on 30 October.", days=5, sender="Office", cat="Urgent"),
              mail(4, "Old fee note", "fee fee fee", days=15, sender="Office")]
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "index.enc"
        calls.clear()
        assert index.update(emails, embed=fake_embed, path=path) == (4, 0)
        assert index.update(emails, embed=fake_embed, path=path) == (0, 0) and len(calls) == 1  # nothing new: no calls
        changed = [{**emails[0], "body_text": "The midterm moved to Sunday."}] + emails[1:3]  # e4 pruned from archive
        assert index.update(changed, embed=fake_embed, path=path) == (1, 1)
        s = index.status(path)
        assert s["emails"] == 3 and s["chunks"] == 6 and s["bytes"] > 0

        found = index.search(changed, {"search": "hackathon pizza"}, k=2, embed=fake_embed, path=path)
        assert [e["id"] for e in found][0] == "e2"
        found = index.search(changed, {"search": "fee due", "sender": "office"}, embed=fake_embed, path=path)
        assert [e["id"] for e in found] == ["e3"]  # sender filter
        found = index.search(changed, {"search": "fee", "after": date(2026, 10, 19)}, embed=fake_embed, path=path)
        assert {e["id"] for e in found} == {"e1"}  # date filter (only e1 is on/after 19 Oct)
        found = index.search(changed, {"search": "midterm", "labels": ["urgent"]}, embed=fake_embed, path=path)
        assert [e["id"] for e in found] == ["e3"]  # label filter (category)
        found = index.search(changed, {"search": "midterm", "sender": "nobody"}, embed=fake_embed, path=path)
        assert found and found[0]["id"] == "e1"  # a filter matching nothing is dropped, not an empty answer

        assert index.update(changed, embed=fake_embed, path=path, rebuild=True) == (3, 0)  # rebuild re-embeds all


def test_update_never_raises():
    def broken(texts):
        raise OSError("endpoint down")

    with tempfile.TemporaryDirectory() as d:
        assert index.update([mail(1, "x", "y")], embed=broken, path=Path(d) / "i.enc") == (0, 0)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
