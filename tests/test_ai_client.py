import io
import json
import os
import urllib.error

from mailbrief.ai import client


class Fake:
    """Stands in for urlopen: replays `outcomes` (an exception to raise, or a dict to answer) and records timeouts."""

    def __init__(self, outcomes):
        self.outcomes, self.timeouts, self.models = list(outcomes), [], []

    def __call__(self, req, timeout):
        self.timeouts.append(timeout)
        self.models.append(json.loads(req.data).get("model"))
        out = self.outcomes.pop(0) if self.outcomes else self.last
        self.last = out
        if isinstance(out, Exception):
            raise out
        return io.BytesIO(json.dumps(out).encode())


def patched(fake, fn, fallback=""):
    real_open, real_sleep = client.urllib.request.urlopen, client.time.sleep
    old = os.environ.get("AI_FALLBACK_MODEL")
    os.environ.setdefault("AI_API_KEY", "test")
    os.environ["AI_FALLBACK_MODEL"] = fallback  # "" = never switch (the plain retry behaviour)
    client.urllib.request.urlopen, client.time.sleep = fake, lambda s: None
    try:
        return fn()
    finally:
        client.urllib.request.urlopen, client.time.sleep = real_open, real_sleep
        os.environ.pop("AI_FALLBACK_MODEL") if old is None else os.environ.__setitem__("AI_FALLBACK_MODEL", old)


def test_no_answer_gives_up_after_a_few_tries():
    for thinking, limit in ((False, 120), (True, 300)):
        fake = Fake([TimeoutError("timed out")])
        try:
            patched(fake, lambda: client.complete("m", [{"role": "user", "content": "hi"}], thinking=thinking))
            raise AssertionError("must give up")
        except TimeoutError:
            pass
        assert fake.timeouts == [limit] * (client.TIMEOUT_RETRIES + 1), fake.timeouts


def test_busy_endpoint_is_still_waited_out():
    busy = urllib.error.HTTPError("u", 429, "busy", {}, None)
    answer = {"choices": [{"message": {"content": "<think>x</think> ok"}}]}
    fake = Fake([busy] * 4 + [answer])
    assert patched(fake, lambda: client.complete("m", [{"role": "user", "content": "hi"}])) == "ok"
    assert len(fake.timeouts) == 5


def test_other_errors_are_not_retried():
    fake = Fake([urllib.error.HTTPError("u", 401, "no", {}, None)])
    try:
        patched(fake, lambda: client.complete("m", []))
        raise AssertionError("401 must raise")
    except urllib.error.HTTPError:
        assert len(fake.timeouts) == 1


OK = {"choices": [{"message": {"content": "fast answer"}}]}


def test_slow_model_falls_back_to_the_fast_one():
    fake = Fake([TimeoutError("timed out"), OK])
    got = patched(fake, lambda: client.complete("slow", [], thinking=True), fallback="fast")
    assert got == "fast answer" and fake.models == ["slow", "fast"] and fake.timeouts == [300, 300]


def test_fallback_model_itself_retries_normally():
    fake = Fake([TimeoutError("timed out")])
    try:
        patched(fake, lambda: client.complete("fast", []), fallback="fast")
        raise AssertionError("must give up")
    except TimeoutError:
        assert fake.models == ["fast"] * (client.TIMEOUT_RETRIES + 1)


def test_refusals_do_not_fall_back():
    fake = Fake([urllib.error.HTTPError("u", 400, "bad", {}, None)])
    try:
        patched(fake, lambda: client.complete("slow", []), fallback="fast")
        raise AssertionError("400 must raise")
    except urllib.error.HTTPError:
        assert fake.models == ["slow"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
