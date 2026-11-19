from datetime import datetime, timedelta, timezone

from mailbrief import service
from mailbrief.notify import bot
from mailbrief.session import remote_login


def test_retry_does_not_repeat_a_successful_later_slot(tmp_path, monkeypatch):
    current = [datetime(2026, 11, 19, 8, tzinfo=timezone.utc)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current[0]

    state = {"last_done": "2026-11-18T08:00:00+00:00"}
    calls, saved = [], []
    stop = tmp_path / "stop.request"

    def save(new):
        saved.append(dict(new))
        if new["last_done"] == "2026-11-19T07:45:00+00:00":
            stop.touch()

    def run(scope, at):
        calls.append(scope)
        return 1 if len(calls) == 1 else 0

    monkeypatch.setattr(service, "datetime", Clock)
    monkeypatch.setattr(service, "_tz", lambda: timezone.utc)
    monkeypatch.setattr(service, "STOP_PATH", stop)
    monkeypatch.setattr(service, "load_state", lambda: state)
    monkeypatch.setattr(service, "save_state", save)
    monkeypatch.setattr(service, "log", lambda text: None)
    monkeypatch.setattr(service, "_run_child", run)
    monkeypatch.setattr(service.signal, "signal", lambda *args: None)
    monkeypatch.setattr(service.time, "sleep", lambda seconds: current.__setitem__(0, current[0] + timedelta(seconds=30)))
    monkeypatch.setattr(bot, "start", lambda stopping: False)
    monkeypatch.setattr(remote_login, "start_always", lambda: None)
    spec = "daily 07:30; daily 07:45 this-week"
    assert service._serve(spec, service.parse_schedule(spec)) == 0
    assert calls == ["new", "this-week", "new"]
    assert saved[-1]["last_done"] == "2026-11-19T07:45:00+00:00"
