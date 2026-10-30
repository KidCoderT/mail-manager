import http.client
import json
import os
import sys
import threading
import time

from mailbrief.session import remote_login as rl


def serve(win):
    server = rl.Server(("127.0.0.1", 0), rl.handler(win))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def call(server, method, path, body=None, cookie=None, ctype="application/json"):
    c = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    headers = {"Content-Type": ctype} if body is not None else {}
    if cookie:
        headers["Cookie"] = cookie
    c.request(method, path, body=json.dumps(body) if isinstance(body, dict) else body, headers=headers)
    r = c.getresponse()
    out = (r.status, dict(r.getheaders()), r.read())
    c.close()
    return out


def bound(server, win):
    status, headers, _ = call(server, "POST", "/login", {"token": win.token})
    assert status == 200
    return headers["Set-Cookie"].split(";")[0]


def test_token_is_single_use_and_becomes_a_cookie():
    win = rl.Window(secure=True)
    win.frame = b"\xff\xd8jpeg"
    s = serve(win)
    try:
        assert call(s, "POST", "/login", {"token": "wrong"})[0] == 404
        status, headers, page = call(s, "GET", "/login")  # GET never binds (link previews)
        assert status == 200 and win.cookie is None and b"Start" in page
        assert "nonce-" in headers["Content-Security-Policy"] and headers["X-Frame-Options"] == "DENY"
        assert headers["Cache-Control"] == "no-store" and headers["Referrer-Policy"] == "no-referrer"
        assert b"naturalWidth / r.width" in page  # taps are scaled to the real viewport on a phone
        _, h, _ = call(s, "POST", "/login", {"token": win.token})
        flags = h["Set-Cookie"]
        assert "HttpOnly" in flags and "SameSite=Strict" in flags and "Secure" in flags
        cookie = flags.split(";")[0]
        assert call(s, "POST", "/login", {"token": win.token})[0] == 404  # burned
        assert call(s, "GET", "/frame")[0] == 404  # no cookie
        assert call(s, "GET", "/frame", cookie="mb_login=guess")[0] == 404
        status, h, body = call(s, "GET", "/frame", cookie=cookie)
        assert status == 200 and h["Content-Type"] == "image/jpeg" and body == win.frame
        assert json.loads(call(s, "GET", "/status", cookie=cookie)[2]) == {"state": "open"}
        assert call(s, "GET", "/status")[0] == 404 and call(s, "GET", "/anything")[0] == 404
    finally:
        s.shutdown()
        s.server_close()


def test_input_checks():
    win = rl.Window(secure=False)
    s = serve(win)
    try:
        cookie = bound(s, win)
        assert "Secure" not in call(s, "GET", "/login")[1].get("Set-Cookie", "")
        good = [{"type": "click", "x": 10, "y": 20}, {"type": "text", "text": "me@u.nus.edu"}, {"type": "key", "key": "Enter"}]
        for ev in good:
            assert call(s, "POST", "/input", ev, cookie=cookie)[0] == 204
        bad = [{"type": "click", "x": rl.VIEW_W, "y": 0}, {"type": "click", "x": -1, "y": 0}, {"type": "click", "x": True, "y": 0},
               {"type": "text", "text": "x" * (rl.MAX_TEXT + 1)}, {"type": "text", "text": ""},
               {"type": "key", "key": "Control+A"}, {"type": "eval"}]
        for ev in bad:
            assert call(s, "POST", "/input", ev, cookie=cookie)[0] == 400, ev
        assert call(s, "POST", "/input", good[0])[0] == 404  # not your browser
        assert call(s, "POST", "/input", json.dumps(good[0]), cookie=cookie, ctype="text/plain")[0] == 404  # other sites
        assert [win.inputs.get_nowait() for _ in good] == good and win.inputs.empty()
    finally:
        s.shutdown()
        s.server_close()


def test_expired_window_is_dead():
    win = rl.Window(ttl=0.05)
    s = serve(win)
    try:
        time.sleep(0.1)
        assert call(s, "POST", "/login", {"token": win.token})[0] == 404
        assert call(s, "GET", "/login")[0] == 404
    finally:
        s.shutdown()
        s.server_close()


def test_done_state_is_shown_then_frames_stop():
    win = rl.Window()
    win.frame = b"jpg"
    s = serve(win)
    try:
        cookie = bound(s, win)
        win.state = "done"
        assert json.loads(call(s, "GET", "/status", cookie=cookie)[2]) == {"state": "done"}
        assert call(s, "GET", "/frame", cookie=cookie)[0] == 404
    finally:
        s.shutdown()
        s.server_close()


class FakePage:
    def __init__(self, rows_after=None):
        self.did, self.rows_after = [], rows_after
        self.url = "https://login.microsoftonline.com/common/oauth2"
        page = self

        class Mouse:
            def click(self, x, y):
                page.did.append(("click", x, y))

        class Keyboard:
            def type(self, t):
                page.did.append(("type", t))

            def press(self, k):
                page.did.append(("press", k))

        self.mouse, self.keyboard = Mouse(), Keyboard()

    def screenshot(self, **kw):
        return b"shot%d" % len(self.did)


def test_drive_applies_inputs_until_signed_in():
    win = rl.Window()
    page = FakePage()
    for ev in ({"type": "click", "x": 5, "y": 6}, {"type": "text", "text": "pw"}, {"type": "key", "key": "Enter"}):
        win.inputs.put(ev)
    assert rl.drive(win, page, lambda pg: len(pg.did) >= 3, step_s=0.01)
    assert page.did == [("click", 5, 6), ("type", "pw"), ("press", "Enter")] and win.frame == b"shot3"


def test_outlook_itself_is_never_shown():
    win = rl.Window()
    page = FakePage()
    page.url = "https://outlook.office.com/mail/"
    win2 = rl.Window(ttl=0.05)
    rl.drive(win2, page, lambda pg: False, step_s=0.01)
    assert win2.hidden and win2.frame == b""
    s = serve(win)
    try:
        cookie = bound(s, win)
        win.hidden, win.frame = True, b""
        assert json.loads(call(s, "GET", "/status", cookie=cookie)[2]) == {"state": "hidden"}
        assert call(s, "GET", "/frame", cookie=cookie)[0] == 404
    finally:
        s.shutdown()
        s.server_close()
    page.url = "https://login.microsoftonline.com/x"  # back on a sign-in page: the picture returns
    win3 = rl.Window(ttl=0.05)
    rl.drive(win3, page, lambda pg: False, step_s=0.01)
    assert not win3.hidden and win3.frame.startswith(b"shot")


def test_drive_stops_when_the_window_closes():
    win = rl.Window(ttl=0.1)
    t0 = time.monotonic()
    assert rl.drive(win, FakePage(), lambda pg: False, step_s=0.02) is False
    assert time.monotonic() - t0 < 2


def test_urls():
    assert rl.is_local("http://localhost:8080") and not rl.is_local("https://mb.up.railway.app")
    for bad in ("http://mb.up.railway.app", "ftp://x", "nothing"):
        try:
            rl.is_local(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    old = {k: os.environ.get(k) for k in ("PUBLIC_URL", "RAILWAY_PUBLIC_DOMAIN", "PORT")}
    try:
        for k in old:
            os.environ.pop(k, None)
        assert rl.public_url() == "http://localhost:8080"
        os.environ["RAILWAY_PUBLIC_DOMAIN"] = "mb.up.railway.app"
        assert rl.public_url() == "https://mb.up.railway.app"
        os.environ["PUBLIC_URL"] = "https://my.example/"
        assert rl.public_url() == "https://my.example"
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_blocked_port_falls_back_only_on_this_pc():
    taken = rl.Server(("127.0.0.1", 0), rl.handler(rl.Window()))
    old = {k: os.environ.get(k) for k in ("PORT", "PUBLIC_URL")}
    try:
        os.environ.pop("PUBLIC_URL", None)
        os.environ["PORT"] = str(taken.server_address[1])
        server, url = rl.listen(f"http://localhost:{rl.port()}", True, rl.handler(rl.Window()))
        assert server.server_address[1] != taken.server_address[1] and url == f"http://localhost:{server.server_address[1]}"
        server.server_close()
        os.environ["PUBLIC_URL"] = f"http://localhost:{rl.port()}"  # an address you set must be kept as is
        try:
            rl.listen(os.environ["PUBLIC_URL"], True, rl.handler(rl.Window()))
            raise AssertionError("a set PUBLIC_URL must not silently move ports")
        except OSError:
            pass
    finally:
        taken.server_close()
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_always_on_server_is_404_until_a_window_opens():
    holder = {"win": None}
    s = rl.Server(("127.0.0.1", 0), rl.handler(lambda: holder["win"]))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        assert call(s, "GET", "/login")[0] == 404 and call(s, "GET", "/")[0] == 404
        assert call(s, "POST", "/login", {"token": "x"})[0] == 404
        win = holder["win"] = rl.Window()
        cookie = bound(s, win)
        assert json.loads(call(s, "GET", "/status", cookie=cookie)[2]) == {"state": "open"}
        holder["win"] = None  # closed: back to 404, even with the cookie
        assert call(s, "GET", "/status", cookie=cookie)[0] == 404
    finally:
        s.shutdown()
        s.server_close()


def test_render_address_and_switch():
    keys = ("PUBLIC_URL", "RENDER_EXTERNAL_URL", "RAILWAY_PUBLIC_DOMAIN", "RENDER", "LOGIN_PAGE")
    old = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            os.environ.pop(k, None)
        assert not rl.always_on()
        os.environ.update(RENDER="true", RENDER_EXTERNAL_URL="https://mailbrief.onrender.com")
        assert rl.always_on() and rl.public_url() == "https://mailbrief.onrender.com"
        os.environ.pop("RENDER")
        os.environ["LOGIN_PAGE"] = "always"
        assert rl.always_on()
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


FAKE_CLOUDFLARED = ("import sys, time\n"
                    "print('INF |  https://quiet-fox-12.trycloudflare.com  |', file=sys.stderr, flush=True)\n"
                    "print('INF Registered tunnel connection', file=sys.stderr, flush=True)\n"
                    "time.sleep(60)\n")


def test_tunnel_reads_the_address_and_stops():
    proc, url = rl.tunnel(1, cmd=[sys.executable, "-c", FAKE_CLOUDFLARED], wait_s=20, settle_s=0)
    assert url == "https://quiet-fox-12.trycloudflare.com" and proc.poll() is None
    rl.stop(proc)
    assert proc.poll() is not None


def test_tunnel_gives_up_cleanly():
    try:
        rl.tunnel(1, cmd=[sys.executable, "-c", "print('nothing')"], wait_s=20)
        raise AssertionError("no address must raise")
    except OSError as e:
        assert "cloudflared" in str(e)


def test_tunnel_is_opt_in():
    old = {k: os.environ.get(k) for k in ("LOGIN_TUNNEL", "PUBLIC_URL")}
    try:
        for k in old:
            os.environ.pop(k, None)
        assert not rl.use_tunnel()
        os.environ["LOGIN_TUNNEL"] = "cloudflared"
        assert rl.use_tunnel()
        os.environ["PUBLIC_URL"] = "https://my.example"
        assert not rl.use_tunnel()  # an address you set wins
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_link_message_escapes():
    assert '<a href="https://x/login#a&amp;b">' in rl.link_html("https://x/login#a&b")
    assert "your phone" in rl.link_html("https://x/login#t") and "localhost link" in rl.link_html("http://localhost:5/login#t")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
