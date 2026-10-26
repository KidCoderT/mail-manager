import json
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from mailbrief import archive, destinations, rules, service
from mailbrief.notify import bot as botmod
from mailbrief.notify.bot import Bot, label_command

SG = ZoneInfo("Asia/Singapore")
TMP = Path(tempfile.mkdtemp())
destinations.PATH = TMP / "destinations.json"
destinations.PATH.write_text(json.dumps([{"type": "telegram", "target": "111", "label": "me", "active": True},
                                         {"type": "telegram", "target": "222", "label": "old", "active": False}]))
rules.RULES_PATH = TMP / "rules.json"
archive.ARCHIVE_DIR = TMP / "archive"  # an empty archive: never your real data/
service.LOG_DIR = TMP / "logs"  # bot logs (counts only) go here, not into data/


class Recorder:
    def __init__(self, updates=()):
        self.calls, self.updates = [], list(updates)

    def __call__(self, method, payload=None):
        self.calls.append((method, payload))
        if method == "getUpdates":
            out, self.updates = self.updates, []
            return {"result": out}
        return {"ok": True}

    def sent(self, method="sendMessage"):
        return [p for m, p in self.calls if m == method]


def msg(uid, chat_id, text, kind="private"):
    return {"update_id": uid, "message": {"chat": {"id": int(chat_id), "type": kind}, "text": text}}


def fake_ask(question, history, today):
    src = {"id": "id1", "subject": "Midterm", "sender_name": "CS", "sender_email": "c@x",
           "received_at": datetime(2026, 10, 20, 9, tzinfo=SG),
           "attachments": [{"id": "A1", "name": "seating.pdf", "inline": False, "content_type": "application/pdf"},
                           {"id": "A2", "name": "logo.png", "inline": True, "content_type": "image/png"}]}
    return {"text": f"Answer to {question} [1]", "refs": {1: "id1"}, "sources": [src], "closest": False, "send": []}


def test_only_your_private_chats():
    api = Recorder([msg(1, 999, "hello stranger"), msg(2, 111, "hi group", kind="group"),
                    msg(3, 222, "inactive destination"),
                    {"update_id": 4, "callback_query": {"id": "q", "data": "a:x", "message": {"chat": {"id": 999, "type": "private"}}}}])
    b = Bot(api=api, ask=fake_ask, tz=SG)
    assert b.poll_once() == 4 and b.offset == 5
    assert api.sent() == [] and api.sent("answerCallbackQuery") == []  # strangers learn nothing


def test_question_buttons_and_history():
    api = Recorder([msg(1, 111, "when is the midterm?")])
    b = Bot(api=api, ask=fake_ask, tz=SG)
    b.poll_once()
    [reply] = api.sent()
    assert reply["chat_id"] == "111" and reply["html"] and "Answer to when is the midterm?" in reply["text"]
    assert "<b>Sources</b>" in reply["text"] and reply["text"].count("<a href=") == 2  # ↗ + the source line
    [[button]] = reply["buttons"]  # the inline logo gets no button
    assert button["text"] == "📎 seating.pdf" and button["callback_data"].startswith("a:")
    assert b.history["111"] == [("when is the midterm?", "Answer to when is the midterm? [1]")]

    fetched = []
    b.fetch_files = lambda wanted: fetched.extend(wanted) or [{"name": "seating.pdf", "content_type": "application/pdf", "data": b"%PDF"}]
    api.updates = [{"update_id": 2, "callback_query": {"id": "q1", "data": button["callback_data"],
                                                        "message": {"chat": {"id": 111, "type": "private"}}}}]
    b.poll_once()
    assert fetched[0][1]["id"] == "A1" and api.sent("sendFile") == [{"chat_id": "111", "name": "seating.pdf"}]
    api.updates = [{"update_id": 3, "callback_query": {"id": "q2", "data": "a:unknown",
                                                        "message": {"chat": {"id": 111, "type": "private"}}}}]
    b.poll_once()
    assert "expired" in api.sent("answerCallbackQuery")[-1]["text"]

    api.updates = [msg(4, 111, "/new")]
    b.poll_once()
    assert "111" not in b.history


def test_commands_and_errors():
    api = Recorder([msg(1, 111, "/help"), msg(2, 111, "/nonsense"), msg(3, 111, "/label add course cs2040s p2")])
    b = Bot(api=api, ask=lambda *a: 1 / 0, tz=SG)
    b.poll_once()
    texts = [p["text"] for p in api.sent()]
    assert texts[0].startswith("Ask me anything") and "/nonsense" in texts[1]
    assert "Added MB: CS2040S" in texts[2] and rules.load()["courses"][0]["priority"] == 2
    api.updates = [msg(4, 111, "a question that crashes")]
    b.poll_once()
    assert api.sent()[-1]["text"].startswith("Sorry, that failed")  # answered politely, bot still alive

    synced = []
    b.run_sync = lambda: synced.append(1) or 0
    api.updates = [msg(5, 111, "/sync")]
    b.poll_once()
    import time
    for _ in range(50):
        if synced:
            break
        time.sleep(0.02)
    assert synced and "Checking for new mail" in api.sent()[-1]["text"]


def test_label_command_parsing():
    assert label_command("add").startswith("Usage")
    assert "Added MB: Prof X" in label_command('add sender x@y.z "Prof X" direct boost p1')
    s = next(r for r in rules.load()["senders"] if r["match"] == "x@y.z")
    assert (s["label"], s["direct_only"], s["boost"], s["priority"]) == ("Prof X", True, True, 1)
    assert "Added MB: Networking" in label_command('add topic Networking "career fairs, meetups" p2')
    assert "Removed MB: CS2040S" in label_command("remove course CS2040S")
    assert label_command('add sender "unclosed').startswith("Usage")


def test_switch():
    import os
    old = {k: os.environ.get(k) for k in ("CHAT", "TELEGRAM_BOT_TOKEN")}
    try:
        os.environ["TELEGRAM_BOT_TOKEN"] = "t"
        os.environ["CHAT"] = "off"
        assert not botmod.enabled()
        os.environ["CHAT"] = "on"
        assert botmod.enabled()
        os.environ.pop("TELEGRAM_BOT_TOKEN")
        assert not botmod.enabled()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
