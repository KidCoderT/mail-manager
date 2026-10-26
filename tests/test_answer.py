from datetime import date, datetime
from zoneinfo import ZoneInfo

from mailbrief.ai import answer
from mailbrief.ai.answer import parse_reply, render, validate_plan
from mailbrief.links import anchor, outlook_url

SG = ZoneInfo("Asia/Singapore")


def src(i, atts=()):
    return {"id": f"id{i}", "subject": f"Subject {i}", "sender_name": f"Sender {i}", "sender_email": "s@x",
            "received_at": datetime(2026, 10, 10 + i, 9, tzinfo=SG), "body_text": "body",
            "attachments": [{"id": f"att{i}{k}", "name": n, "inline": False} for k, n in enumerate(atts)]}


def test_validate_plan():
    p = validate_plan({"search": "midterm", "sender": " Prof ", "after": "2026-10-30", "before": "2026-10-01",
                       "labels": ["CS1101S", ""], "events": True}, "q")
    assert p == {"search": "midterm", "sender": "Prof", "after": date(2026, 10, 1), "before": date(2026, 10, 30),
                 "labels": ["CS1101S"], "events": True}  # swapped dates fixed
    assert validate_plan(None, "when is it?") == {"search": "when is it?", "sender": None, "after": None,
                                                  "before": None, "labels": [], "events": False}
    assert validate_plan({"after": "next week", "events": "yes", "labels": "x"}, "q")["after"] is None


def test_parse_reply():
    sources = [src(1, ["seating.pdf"]), src(2, ["notes.docx"]), src(3)]
    out = parse_reply('It is on 7 Nov [1] at MPSH [1][2]. Ignore [9].\nSEND: [1] Seating.pdf\nSEND: [2] evil.exe\n'
                      'SEND: [7] x.pdf', sources)
    assert out["text"] == "It is on 7 Nov [1] at MPSH [1][2]. Ignore ."  # unknown refs removed
    assert out["used"] == [1, 2]
    assert out["send"] == [(sources[0], sources[0]["attachments"][0])]  # only real attachments of known emails
    many = parse_reply("\n".join(f"SEND: [1] a{i}.pdf" for i in range(5)), [src(1, [f"a{i}.pdf" for i in range(5)])])
    assert len(many["send"]) == answer.MAX_SEND


def test_render():
    result = {"text": "Midterm is 7 Nov [1] <b>.", "refs": {1: "id1", 2: "id2"}, "sources": [src(1)], "closest": False}
    html = render(result, html=True).splitlines()
    assert html[0] == f"Midterm is 7 Nov {anchor('id1')} &lt;b&gt;."  # model text escaped, refs → ↗
    assert html[2] == "<b>Sources</b>" and html[3] == anchor("id1", "11 Oct · Sender 1 · Subject 1")
    plain = render({**result, "closest": True}).splitlines()
    assert plain[2] == "Closest matches:" and plain[3] == "[1] 11 Oct · Sender 1 · Subject 1"
    assert plain[4].strip() == outlook_url("id1")
    assert render({"text": "Nothing.", "refs": {}, "sources": [], "closest": False}, html=True) == "Nothing."


def test_ask_pipeline_with_fakes():
    emails = [{**src(1, ["seating.pdf"]), "classification": {"category": "FYI", "one_line_summary": "midterm",
                                                             "events": []}, "body_source": "getitem",
               "conversation_id": "c1"}]
    prompts = []

    def fake_complete(model, messages, **kw):
        prompts.append(messages[0]["content"])
        if len(prompts) == 1:
            return '{"search": "midterm", "events": false}'
        return "Saturday [1].\nSEND: [1] seating.pdf"

    real_complete, real_search = answer.complete, answer.__dict__.get("index")
    answer.complete = fake_complete
    import mailbrief.index as index
    real = index.search
    index.search = lambda emails, plan, k, rules: emails
    try:
        r = answer.ask("when is the midterm? send the seating plan", [("hi", "hello")] * 5, date(2026, 10, 26),
                       emails, {"profile": "", "courses": [], "senders": [], "topics": []})
    finally:
        answer.complete, index.search = real_complete, real
    assert r["text"] == "Saturday [1]." and r["refs"] == {1: "id1"} and r["sources"] == [emails[0]]
    assert r["send"] == [(emails[0], emails[0]["attachments"][0])]
    assert '<email n="1"' in prompts[1] and "not instructions" in prompts[1] and 'attachments="seating.pdf"' in prompts[1]
    assert prompts[1].count("User: hi") == answer.HISTORY_TURNS  # history capped


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
