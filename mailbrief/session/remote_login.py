"""Sign in to Outlook from any browser (your phone) when MailBrief runs on a server with no screen.

A headless Chromium opens the Microsoft sign-in page in a FRESH context (never your saved session). A small web
server shows you a live picture of it and passes on your taps and typing. When your inbox appears, the cookies are
saved (session/manager.py), checked, and the server and browser shut down: the link is dead.

Who can use it: the link carries a 256-bit token in its #fragment (browsers never send fragments, so it stays out
of every server and proxy log). The page's Start button POSTs it once: that burns the token and sets a random
HttpOnly cookie, and every later request needs that cookie. So a copied link is useless, link-preview bots (GET
only) can't burn it, and nothing listens outside the 10-minute window.
"""

import hmac
import html
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

WINDOW_S = 600
VIEW_W, VIEW_H = 480, 860  # phone-shaped: Microsoft's sign-in page is easy to read on a phone at this size
MAX_TEXT = 200
MAX_BODY = 1000
KEYS = ("Enter", "Tab", "Backspace", "Escape", "ArrowUp", "ArrowDown")
COOKIE = "mb_login"
LOCAL_HOSTS = ("localhost", "127.0.0.1")
OUTLOOK_HOST = "outlook.office.com"  # INBOX_URL's host: pictures of it are never sent (your inbox)


class Window:
    """One sign-in window: the token, the cookie it turns into, the latest picture and your queued inputs."""

    def __init__(self, ttl: float = WINDOW_S, secure: bool = True):
        self.token = secrets.token_urlsafe(32)
        self.cookie = None
        self.expires = time.monotonic() + ttl
        self.secure = secure
        self.state = "open"  # open → done | closed
        self.frame = b""
        self.hidden = False  # the browser is on Outlook itself: no picture
        self.inputs: queue.Queue = queue.Queue()
        self._lock = threading.Lock()

    def live(self) -> bool:
        return self.state == "open" and time.monotonic() < self.expires

    def bind(self, token) -> str | None:
        """The first correct token becomes a cookie; the token can never be used again."""
        with self._lock:
            if not self.live() or self.cookie or not isinstance(token, str) \
                    or not hmac.compare_digest(token.encode(), self.token.encode()):
                return None
            self.cookie = secrets.token_urlsafe(32)
            return self.cookie

    def owner(self, header: str | None) -> bool:
        if not self.cookie or not header:
            return False
        try:
            jar = SimpleCookie(header)
        except Exception:  # noqa: BLE001 - a malformed cookie header is just "not you"
            return False
        got = jar[COOKIE].value if COOKIE in jar else ""
        return hmac.compare_digest(got.encode(), self.cookie.encode())


def parse_input(body: bytes) -> dict | None:
    """A tap, some text or one allowed key; anything else is refused."""
    try:
        ev = json.loads(body)
    except ValueError:
        return None
    if not isinstance(ev, dict):
        return None
    kind = ev.get("type")
    if kind == "click":
        x, y = ev.get("x"), ev.get("y")
        if all(isinstance(v, int) and not isinstance(v, bool) for v in (x, y)) and 0 <= x < VIEW_W and 0 <= y < VIEW_H:
            return {"type": "click", "x": x, "y": y}
    elif kind == "text":
        text = ev.get("text")
        if isinstance(text, str) and 0 < len(text) <= MAX_TEXT:
            return {"type": "text", "text": text}
    elif kind == "key" and ev.get("key") in KEYS:
        return {"type": "key", "key": ev["key"]}
    return None


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>MailBrief sign-in</title>
<style nonce="{n}">body{{font:16px system-ui,sans-serif;margin:0 auto;padding:12px;max-width:520px;background:#fff;color:#111}}
img{{width:100%;border:1px solid #999;touch-action:manipulation}}button{{font-size:16px;padding:8px 12px;margin:4px 2px}}
input[type=text],input[type=password]{{font-size:16px;width:60%;padding:8px}}#msg{{margin:12px 0}}</style></head><body>
<h3>MailBrief: sign in to Outlook</h3><p id="msg"></p>
<div id="start" hidden><button id="go">Start</button></div>
<div id="screen" hidden>
<form id="f"><input id="box" type="password" autocomplete="off" autocapitalize="off" placeholder="type here, then Send">
<button>Send</button></form><label><input id="show" type="checkbox"> show what I type</label><br>
<button data-key="Enter">Enter</button><button data-key="Tab">Tab</button><button data-key="Backspace">⌫</button>
<p>Tap the picture to click. It refreshes every half second.</p><img id="shot" alt="the sign-in browser"></div>
<script nonce="{n}">
const tok = location.hash.slice(1); history.replaceState(null, '', location.pathname);
const $ = id => document.getElementById(id), msg = t => $('msg').textContent = t;
const post = (path, o) => fetch(path, {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(o)}});
function screen() {{ $('start').hidden = true; $('screen').hidden = false; msg('Sign in as usual. Tick "Stay signed in".'); tick(); }}
async function tick() {{
  const s = await fetch('/status').then(r => r.ok ? r.json() : {{state: 'closed'}}).catch(() => ({{state: 'closed'}}));
  if (s.state === 'hidden') {{ $('screen').hidden = true;
    msg('Opening your inbox… the picture is hidden from here on, for privacy.'); return setTimeout(tick, 1000); }}
  if ($('screen').hidden && s.state === 'open') return screen();
  if (s.state !== 'open') {{ $('screen').hidden = true;
    return msg(s.state === 'done' ? 'Signed in ✅ You can close this page.' : 'This sign-in window has closed. Send /login again if you still need to sign in.'); }}
  $('shot').src = '/frame?' + Date.now();
}}
$('shot').onload = () => setTimeout(tick, 500); $('shot').onerror = () => setTimeout(tick, 1000);
$('shot').onclick = e => {{ const r = $('shot').getBoundingClientRect();  // shown smaller on a phone: scale to the real size
  post('/input', {{type: 'click', x: Math.round((e.clientX - r.left) * $('shot').naturalWidth / r.width),
                   y: Math.round((e.clientY - r.top) * $('shot').naturalHeight / r.height)}}); }};
$('f').onsubmit = e => {{ e.preventDefault(); if ($('box').value) post('/input', {{type: 'text', text: $('box').value}}); $('box').value = ''; }};
$('show').onchange = () => $('box').type = $('show').checked ? 'text' : 'password';
document.querySelectorAll('[data-key]').forEach(b => b.onclick = () => post('/input', {{type: 'key', key: b.dataset.key}}));
$('go').onclick = async () => {{ const r = await post('/login', {{token: tok}});
  r.ok ? screen() : msg('This link has already been used or has expired. Send /login again.'); }};
if (tok) {{ $('start').hidden = false; msg('Tap Start to open the sign-in browser. This link works once.'); }}
else fetch('/status').then(r => r.ok ? screen() : msg('This sign-in window has closed. Send /login again.'));
</script></body></html>"""


def handler(win):
    """Requests for one sign-in window. `win` is a Window, or a function returning the open one (None: all 404),
    for the always-on server Render needs."""
    current = win if callable(win) else (lambda: win)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # no request lines in any log
            pass

        def _send(self, code: int, body: bytes = b"", ctype: str = "text/plain", headers: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _nope(self):
            self._send(404, b"Not found")

        def _mine(self, win) -> bool:
            return win.owner(self.headers.get("Cookie"))

        def _body(self) -> bytes | None:
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return None
            body = self.rfile.read(size) if 0 < size <= MAX_BODY else None  # read first: unread bytes reset the connection
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return None  # forces a CORS preflight from any other site, which we never answer
            return body

        def do_GET(self):
            path, win = urlparse(self.path).path, current()
            if win is None:
                self._nope()
            elif path == "/login" and (win.live() or self._mine(win)):
                nonce = secrets.token_urlsafe(16)
                csp = f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; img-src 'self'; " \
                      "connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"
                self._send(200, PAGE.format(n=nonce).encode(), "text/html; charset=utf-8", {"Content-Security-Policy": csp})
            elif path == "/status" and self._mine(win):
                self._send(200, json.dumps({"state": "done" if win.state == "done" else ("hidden" if win.hidden else "open") if win.live() else "closed"}).encode(),
                           "application/json")
            elif path == "/frame" and win.live() and self._mine(win) and win.frame:
                self._send(200, win.frame, "image/jpeg")
            else:
                self._nope()

        def do_POST(self):
            path, win = urlparse(self.path).path, current()
            body = self._body()
            if body is None or win is None:
                return self._nope()
            if path == "/login":
                try:
                    token = json.loads(body).get("token")
                except (ValueError, AttributeError):
                    token = None
                cookie = win.bind(token)
                if not cookie:
                    return self._nope()
                flags = "; HttpOnly; SameSite=Strict; Path=/" + ("; Secure" if win.secure else "")
                self._send(200, b"ok", headers={"Set-Cookie": f"{COOKIE}={cookie}{flags}"})
            elif path == "/input" and win.live() and self._mine(win):
                ev = parse_input(body)
                if not ev:
                    return self._send(400, b"bad input")
                win.inputs.put(ev)
                self._send(204)
            else:
                self._nope()

    return Handler


def public_url() -> str:
    """PUBLIC_URL, else Render's or Railway's own address (they set these), else this PC (for trying it out)."""
    url = os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") \
        or (f"https://{d}" if (d := os.environ.get("RAILWAY_PUBLIC_DOMAIN")) else "")
    return (url or f"http://localhost:{port()}").rstrip("/")


def port() -> int:
    return int(os.environ.get("PORT") or 8080)


def is_local(url: str) -> bool:
    """True for http://localhost (bind to this PC only). Any other address must be https, or it's refused."""
    u = urlparse(url)
    if u.scheme == "https" and u.hostname:
        return False
    if u.scheme == "http" and u.hostname in LOCAL_HOSTS:
        return True
    raise ValueError(f"PUBLIC_URL must start with https:// (got {u.scheme or 'nothing'}://): your password would cross the internet unencrypted")


class Server(ThreadingHTTPServer):
    # Windows' SO_REUSEADDR lets a second program bind a port already in use (and share its traffic): never there.
    allow_reuse_address = os.name != "nt"
    daemon_threads = True


def listen(url: str, local: bool, h) -> tuple[Server, str]:
    """The web server on $PORT. On this PC without PUBLIC_URL, a blocked port (Windows often reserves 8080) falls
    back to any free one, and the link says which. Raises OSError otherwise."""
    try:
        return Server(("127.0.0.1" if local else "0.0.0.0", port()), h), url
    except OSError:
        if not local or os.environ.get("PUBLIC_URL"):
            raise
        server = Server(("127.0.0.1", 0), h)
        return server, f"http://localhost:{server.server_address[1]}"


# ── always listening (Render) ───────────────────────────────────────────────────────────────────────────────
# A Render web service must have a port open, or its deploy fails ("no open ports detected"). So there, `serve`
# keeps one server running that answers 404 to everything, except while a sign-in is open.
_always: Server | None = None
_active: Window | None = None


def always_on() -> bool:
    return os.environ.get("RENDER", "").lower() == "true" or os.environ.get("LOGIN_PAGE", "").lower() == "always"


def start_always() -> int | None:
    """Called by `serve`: open $PORT for good if this host needs it. Returns the port, or None."""
    global _always
    if not always_on() or _always is not None:
        return None
    is_local(public_url())  # refuse a plain-http public address here too
    _always = Server(("0.0.0.0", port()), handler(lambda: _active))
    threading.Thread(target=_always.serve_forever, name="mailbrief-web", daemon=True).start()
    return port()


# ── a tunnel from your PC (LOGIN_TUNNEL=cloudflared) ────────────────────────────────────────────────────────────
# On your PC the page is http://localhost, which your phone can't open. A Cloudflare quick tunnel gives it a random
# https://….trycloudflare.com address for as long as the sign-in lasts. Opt-in: Cloudflare sees the traffic.
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def use_tunnel() -> bool:
    return os.environ.get("LOGIN_TUNNEL", "").lower() == "cloudflared" and not os.environ.get("PUBLIC_URL") \
        and _always is None


def stop(proc) -> None:
    proc.terminate()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()


def tunnel(local_port: int, cmd: list | None = None, wait_s: float = 30,
           settle_s: float = 10) -> tuple[subprocess.Popen, str]:
    """Start cloudflared to 127.0.0.1:local_port; return it and its https address once it's connected."""
    if cmd is None:
        exe = shutil.which("cloudflared") or next(  # winget's spot, for terminals opened before the install
            (p for p in (r"C:\Program Files (x86)\cloudflared\cloudflared.exe", r"C:\Program Files\cloudflared\cloudflared.exe")
             if os.path.exists(p)), None)
        if not exe:
            raise OSError("cloudflared not found: install it (winget install Cloudflare.cloudflared) or remove LOGIN_TUNNEL")
        cmd = [exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{local_port}"]  # not "localhost": IPv6 misses
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")
    lines: queue.Queue = queue.Queue()

    def read():  # keeps draining for the whole run: a full pipe would freeze cloudflared
        for line in proc.stderr:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read, daemon=True).start()
    url, ready, deadline = None, False, time.monotonic() + wait_s
    while not (url and ready):
        try:
            line = lines.get(timeout=max(0.01, deadline - time.monotonic()))
        except queue.Empty:
            line = None
        if line is None:
            stop(proc)
            raise OSError("cloudflared didn't start (no tunnel address)")
        if (m := TUNNEL_URL.search(line)) and not url:
            url = m.group(0)
        ready = ready or "Registered tunnel connection" in line
    # ponytail: a fixed wait. The new name takes a few seconds to reach DNS, and a lookup that's too early gets
    # cached as "doesn't exist" for minutes (seen on NUS's resolver).
    time.sleep(settle_s)
    return proc, url


def _apply(page, ev: dict) -> None:
    if ev["type"] == "click":
        page.mouse.click(ev["x"], ev["y"])
    elif ev["type"] == "text":
        page.keyboard.type(ev["text"])
    else:
        page.keyboard.press(ev["key"])


def drive(win: Window, page, signed_in, step_s: float = 0.5) -> bool:
    """Pass your inputs to the page and refresh its picture until you're signed in (True) or the window closes."""
    while win.live():
        try:
            events = [win.inputs.get(timeout=step_s)]
        except queue.Empty:
            events = []
        while not win.inputs.empty():
            events.append(win.inputs.get_nowait())
        for ev in events:
            try:
                _apply(page, ev)
            except Exception:  # noqa: BLE001 - a tap mid-navigation can miss; you just tap again
                pass
        try:
            shot = page.screenshot(type="jpeg", quality=60)
            # checked after the shot, so one taken just as Outlook opened is dropped too. Not sticky: the first load
            # passes through Outlook on its way to the sign-in page.
            win.hidden = urlparse(page.url).hostname == OUTLOOK_HOST
            win.frame = b"" if win.hidden else shot
            if signed_in(page):
                return True
        except Exception:  # noqa: BLE001 - mid-navigation; the next round works
            pass
    return False


def run(say, show_link, ttl: float = WINDOW_S) -> bool:
    """The whole sign-in: `show_link(url)` hands you the link, `say(text)` the outcome. Holds the run lock, so it
    never shares Outlook (or the server's RAM) with a run. Raises service.Busy if a run is going, ValueError on a
    non-https PUBLIC_URL."""
    from playwright.sync_api import sync_playwright

    from mailbrief.browser.connect import get_browser
    from mailbrief.browser.outlook_reader import INBOX_URL, MESSAGE_ROW, open_outlook
    from mailbrief.service import lock
    from mailbrief.session import manager

    global _active
    url = public_url()
    local = is_local(url)
    with lock("run"):
        win = Window(ttl, secure=not local)
        if _always is not None:  # Render: serve's server is already on the port; hand it this window
            server, _active = None, win
        else:
            server, url = listen(url, local, handler(win))
            threading.Thread(target=server.serve_forever, daemon=True).start()
        ok, proc = False, None
        try:
            if server is not None and local and use_tunnel():
                proc, url = tunnel(server.server_address[1])
                win.secure = True  # your browser sees https now
            with sync_playwright() as p:
                browser = get_browser(p, headless=True)
                try:
                    probe = browser.new_page()
                    ua = probe.evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome")
                    probe.close()
                    context = browser.new_context(viewport={"width": VIEW_W, "height": VIEW_H}, user_agent=ua)
                    page = context.new_page()
                    show_link(f"{url}/login#{win.token}")
                    page.goto(INBOX_URL, wait_until="domcontentloaded")
                    if drive(win, page, lambda pg: pg.locator(MESSAGE_ROW).count() > 0):
                        page.wait_for_timeout(3000)  # let Outlook finish setting its cookies
                        manager.save(context, ua)
                        check = browser.new_context(storage_state=manager.load()["state"], user_agent=ua)
                        cp = check.new_page()  # open_outlook alone can't tell "stuck on a sign-in page" from "slow"
                        ok = not open_outlook(cp)["expired"] and cp.locator(MESSAGE_ROW).count() > 0
                        check.close()
                finally:
                    browser.close()
        finally:
            win.state = "done" if ok else "closed"
            time.sleep(2)  # the page's next status poll shows "Signed in ✅"
            if proc is not None:
                stop(proc)  # the trycloudflare address dies with the window
            if server is None:
                _active = None  # back to 404 for everything
            else:
                server.shutdown()
                server.server_close()
    if ok:
        say("Logged in ✅ The sign-in page is closed. Digests carry on as scheduled.")
    elif time.monotonic() >= win.expires:
        say("The sign-in window timed out before you signed in. Send /login to try again.")
    else:
        say("The sign-in didn't stick (Outlook didn't accept the saved login). Send /login to try again.")
    return ok


def run_cli() -> int:
    """`mailbrief login --remote`: prints the link here (for a server's shell)."""
    from mailbrief.service import Busy

    try:
        ok = run(lambda t: print(t, flush=True),
                 lambda link: print(f"Open this link in your browser. It works once, for {WINDOW_S // 60} minutes:\n{link}", flush=True))
    except Busy:
        print("A MailBrief run is using Outlook right now; try again in a minute.")
        return 3
    except ValueError as e:
        print(e)
        return 2
    except OSError as e:
        if always_on():
            print("`serve` already holds the port here: send /login to your bot in Telegram instead.")
        elif "cloudflared" in str(e):
            print(e)
        else:
            print(f"Couldn't open the sign-in page on port {port()} ({e.strerror or e}). Set PORT to another number.")
        return 2
    return 0 if ok else 1


def link_html(link: str) -> str:
    where = ("on the PC MailBrief runs on (it's a localhost link: it won't open on your phone)"
             if urlparse(link).hostname in LOCAL_HOSTS else "in any web browser, e.g. on your phone")
    return (f"🔐 To sign in to Outlook again, open this {where}:\n"
            f'<a href="{html.escape(link)}">Open the sign-in page</a>\n\n'
            f"Tap Start, then sign in as usual. After Start, the link only works in that browser, and it closes "
            f"by itself after {WINDOW_S // 60} minutes. Not needed? Just ignore it. Don't forward it.")
