"""Ask your inbox in Telegram (M7): a listener `serve` runs in a thread, or `mailbrief bot` in the foreground.

Long-polls getUpdates (no webhook, no open port). It acts ONLY on private chats that are your registered
destinations (`mailbrief add-destination`); every other chat and every group is ignored without a reply.
Logs hold counts and timings, never questions, answers or email content. CHAT=off: no listener at all.
"""

import os
import secrets
import shlex
import threading
import time
from argparse import Namespace
from datetime import datetime
from io import StringIO

from mailbrief.notify import telegram

POLL_S = 20             # long-poll wait; telegram._api's own timeout (30 s) is longer
MAX_BUTTONS = 8
HELP = """Ask me anything about your email, e.g. "when is the CS1101S midterm?" or "any hackathons this month?".
Each answer cites its emails: tap ↗ or a source to open it in Outlook.

/new: start a fresh conversation
/sync: check for new mail now (sends the digest)
/digest: send the latest digest again
/events [days]: upcoming events (default 14 days)
/labels: your label rules
/label add course CS2040S | sender a@b.c "Prof X" [direct] [boost] [p2] | topic Name "description" [p2]
/label remove course|sender|topic KEY
/profile your profile text"""
COMMANDS = [("new", "start a fresh conversation"), ("sync", "check for new mail now"),
            ("digest", "send the latest digest again"), ("events", "upcoming events"),
            ("labels", "your label rules"), ("help", "what I can do")]


def enabled() -> bool:
    return os.environ.get("CHAT", "on").strip().lower() not in ("off", "0", "false", "no") \
        and bool(os.environ.get("TELEGRAM_BOT_TOKEN"))


def _log(msg: str) -> None:
    from mailbrief import service

    service.log(f"chat: {msg}")


class Bot:
    def __init__(self, api=None, ask=None, fetch_files=None, run_sync=None, tz=None):
        self.api = api or telegram._api
        self.ask = ask              # answer.ask (injectable for tests)
        self.fetch_files = fetch_files  # [(email, attachment)] → [file dicts]; default opens Outlook
        self.run_sync = run_sync    # () → exit code of a `new` run with --send
        self.tz = tz
        self.offset = None
        self.history: dict[str, list[tuple[str, str]]] = {}  # memory only, never on disk
        self.tokens: dict[str, tuple[dict, dict]] = {}      # button token → (email, attachment); until restart
        self.syncing = threading.Event()

    # ── who may talk to the bot ──────────────────────────────────────────────────────────────────
    @staticmethod
    def allowed(chat: dict | None) -> bool:
        from mailbrief import destinations

        if not chat or chat.get("type") != "private":
            return False
        return any(d["type"] == "telegram" and d["active"] and str(d["target"]) == str(chat.get("id"))
                   for d in destinations.load())

    # ── sending ──────────────────────────────────────────────────────────────────────────────────
    def say(self, chat_id: str, text: str, html: bool = False, buttons=None) -> None:
        if self.api is telegram._api:
            telegram.send(chat_id, text, html=html, buttons=buttons)
        else:  # tests: record what would be sent
            self.api("sendMessage", {"chat_id": chat_id, "text": text, "html": html, "buttons": buttons})

    def _typing(self, chat_id: str, done: threading.Event) -> None:
        while not done.is_set():
            try:
                self.api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
            except Exception:  # noqa: BLE001 - only a nicety
                pass
            done.wait(4.5)

    # ── one update ───────────────────────────────────────────────────────────────────────────────
    def handle(self, update: dict) -> None:
        if "callback_query" in update:
            q = update["callback_query"]
            chat = (q.get("message") or {}).get("chat")
            if not self.allowed(chat):
                return
            self._button(str(chat["id"]), q)
            return
        msg = update.get("message") or {}
        chat = msg.get("chat")
        if not self.allowed(chat):
            return  # strangers and groups learn nothing, not even that the bot is alive
        text = (msg.get("text") or "").strip()
        if not text:
            return
        chat_id = str(chat["id"])
        try:
            if text.startswith("/"):
                self._command(chat_id, text)
            else:
                self._question(chat_id, text)
        except Exception as e:  # noqa: BLE001 - one bad message must not stop the bot
            _log(f"failed ({type(e).__name__})")
            self.say(chat_id, "Sorry, that failed (it's in the log). Try again, or /new to start fresh.")

    def _question(self, chat_id: str, text: str) -> None:
        from mailbrief.ai import answer

        ask = self.ask or answer.ask
        done = threading.Event()
        threading.Thread(target=self._typing, args=(chat_id, done), daemon=True).start()
        t0 = time.monotonic()
        try:
            result = ask(text, self.history.get(chat_id, []), self._today())
        finally:
            done.set()
        self.history.setdefault(chat_id, []).append((text, result["text"]))
        self.history[chat_id] = self.history[chat_id][-answer.HISTORY_TURNS:]
        self.say(chat_id, answer.render(result, html=True), html=True, buttons=self._buttons(result["sources"]))
        _log(f"answered in {time.monotonic() - t0:.0f}s ({len(result['sources'])} sources)")
        if result.get("send"):
            self._send_files(chat_id, result["send"])

    def _buttons(self, sources: list[dict]) -> list | None:
        rows, count = [], 0
        for e in sources:
            for a in e.get("attachments") or []:
                if a.get("inline") or count >= MAX_BUTTONS:
                    continue
                token = secrets.token_hex(4)
                self.tokens[token] = (e, a)
                icon = "🖼" if (a.get("content_type") or "").startswith("image/") else "📎"
                rows.append([{"text": f"{icon} {a['name'][:40]}", "callback_data": f"a:{token}"}])
                count += 1
        return rows or None

    def _button(self, chat_id: str, q: dict) -> None:
        data = q.get("data") or ""
        hit = self.tokens.get(data[2:]) if data.startswith("a:") else None
        try:
            self.api("answerCallbackQuery", {"callback_query_id": q.get("id"),
                                             "text": "Fetching from Outlook…" if hit else "That button has expired; ask again."})
        except Exception:  # noqa: BLE001
            pass
        if hit:
            self._send_files(chat_id, [hit])

    def _send_files(self, chat_id: str, wanted: list[tuple[dict, dict]]) -> None:
        from mailbrief.service import Busy

        try:
            files = (self.fetch_files or fetch_files)(wanted)
        except Busy:
            self.say(chat_id, "A MailBrief run is using Outlook right now; tap the button again in a minute.")
            return
        except Exception as e:  # noqa: BLE001
            _log(f"file fetch failed ({type(e).__name__})")
            self.say(chat_id, "Couldn't fetch that file from Outlook (it's in the log).")
            return
        for f in files:
            try:
                if self.api is telegram._api:
                    telegram.send_file(chat_id, f["name"], f["content_type"], f["data"])
                else:
                    self.api("sendFile", {"chat_id": chat_id, "name": f["name"]})
            except telegram.TelegramError as e:
                self.say(chat_id, f"Couldn't send {f['name']}: {e}")
        if len(files) < len(wanted):
            self.say(chat_id, f"{len(wanted) - len(files)} file(s) are no longer in Outlook.")
        _log(f"sent {len(files)} file(s)")

    # ── commands ─────────────────────────────────────────────────────────────────────────────────
    def _command(self, chat_id: str, text: str) -> None:
        name, _, rest = text.partition(" ")
        name = name.split("@")[0].lower()  # "/new@MyBot" in some clients
        rest = rest.strip()
        if name in ("/start", "/help"):
            self.say(chat_id, HELP)
        elif name == "/new":
            self.history.pop(chat_id, None)
            self.say(chat_id, "Fresh start: I've forgotten this conversation.")
        elif name == "/sync":
            self._sync(chat_id)
        elif name == "/digest":
            self._digest(chat_id)
        elif name == "/events":
            self._events(chat_id, rest)
        elif name == "/labels":
            self.say(chat_id, rules_reply(Namespace(action="list")))
        elif name == "/label":
            self.say(chat_id, label_command(rest))
        elif name == "/profile":
            self.say(chat_id, rules_reply(Namespace(action="profile", text=rest)) if rest else
                     "Usage: /profile Year 2 CS student looking for internships and hackathons")
        else:
            self.say(chat_id, f"I don't know {name}. /help lists what I can do.")

    def _sync(self, chat_id: str) -> None:
        if self.syncing.is_set():
            self.say(chat_id, "Already checking for new mail; the digest arrives when it's done.")
            return
        self.syncing.set()
        self.say(chat_id, "Checking for new mail now (about a minute). The digest arrives here if there's anything new.")

        def work():
            try:
                code = (self.run_sync or run_sync)()
                note = {0: None, 3: "A run was already in progress; its digest comes as usual.",
                        2: "Outlook needs `mailbrief login` on your PC first."}.get(code, f"The check failed (exit {code}); it's in the log.")
                if note:
                    self.say(chat_id, note)
            finally:
                self.syncing.clear()

        threading.Thread(target=work, daemon=True).start()

    def _digest(self, chat_id: str) -> None:
        from mailbrief import archive, events, links

        digests = archive.load()[1]
        if not digests:
            self.say(chat_id, "No digest saved yet.")
            return
        last = max(digests, key=lambda d: d["at"])
        self.say(chat_id, links.to_html(last["text"], last.get("refs") or {}), html=True)
        ev = events.build(self._today(), (), None, html=True)
        if ev:
            self.say(chat_id, ev, html=True)

    def _events(self, chat_id: str, rest: str) -> None:
        from mailbrief import archive, events, rules

        days = int(rest) if rest.isdigit() and 1 <= int(rest) <= 365 else events.DEFAULT_DAYS
        try:
            your_rules = rules.load()
        except rules.RulesError:
            your_rules = rules.empty()
        today = self._today()
        text = events.render(events.upcoming(archive.load()[0], today, days, (), your_rules), today, days, html=True)
        self.say(chat_id, text or f"No events in the next {days} days.", html=bool(text))

    def _today(self):
        from mailbrief import service

        return datetime.now(self.tz or service._tz()).date()

    # ── the loop ─────────────────────────────────────────────────────────────────────────────────
    def poll_once(self) -> int:
        payload = {"timeout": POLL_S, "allowed_updates": ["message", "callback_query"]}
        if self.offset is not None:
            payload["offset"] = self.offset
        updates = self.api("getUpdates", payload).get("result", [])
        ignored = 0
        for u in updates:
            self.offset = u["update_id"] + 1
            chat = (u.get("message") or (u.get("callback_query") or {}).get("message") or {}).get("chat")
            if not self.allowed(chat):
                ignored += 1
                continue
            self.handle(u)
        if ignored:
            _log(f"ignored {ignored} message(s) from chats that aren't your destinations")
        return len(updates)

    def run(self, stop: threading.Event) -> None:
        try:
            self.api("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in COMMANDS]})
        except Exception:  # noqa: BLE001 - the menu is a nicety
            pass
        _log("listening")
        while not stop.is_set():
            try:
                self.poll_once()
            except telegram.TelegramError as e:
                if str(e).startswith("409"):  # someone else is polling (add-destination?): give them room
                    _log("another getUpdates is running (409); retrying in 30s")
                    stop.wait(30)
                else:
                    _log(f"poll failed ({e}); retrying in 10s")
                    stop.wait(10)
            except Exception as e:  # noqa: BLE001 - network blips: never let the listener die
                _log(f"poll failed ({type(e).__name__}); retrying in 10s")
                stop.wait(10)
        _log("stopped")


# ── defaults wired to the real world ─────────────────────────────────────────────────────────────────

def fetch_files(wanted: list[tuple[dict, dict]]) -> list[dict]:
    """Fetch attachments from Outlook (read-only), never while a run is using it (raises service.Busy)."""
    from mailbrief import labels
    from mailbrief.browser.outlook_reader import fetch_attachment
    from mailbrief.service import lock

    out = []
    with lock("run"), labels.outlook() as (page, auth, _startup):
        for _email, att in wanted:
            f = fetch_attachment(page, auth, att["id"])
            if f:
                out.append(f)
    return out


def run_sync() -> int:
    """A `new` run with --send (the same as a scheduled one), as a child process logging to the service log."""
    from mailbrief import service

    return service._run_child("new")


def rules_reply(args: Namespace) -> str:
    """What `mailbrief rules …` would print, as a chat reply (same code, same checks)."""
    from mailbrief.main import rules_command

    defaults = dict(kind=None, key=None, description=None, label=None, direct=False, priority=None, boost=False, text="")
    out = StringIO()  # its own buffer: other threads' output (service log lines) never leaks into the reply
    rules_command(Namespace(**{**defaults, **vars(args)}), out=out)
    return out.getvalue().strip() or "Done."


def label_command(rest: str) -> str:
    """/label add course CS2040S [p2] [boost] | add sender a@b.c "Prof X" [direct] [boost] [p1]
    | add topic Name "description" [p2] | remove course|sender|topic KEY"""
    usage = ('Usage: /label add course CS2040S | /label add sender a@b.c "Prof X" direct | '
             '/label add topic Networking "career fairs, meetups" p2 | /label remove course MA1521')
    try:
        words = shlex.split(rest)
    except ValueError:
        return usage
    if len(words) < 3 or words[0] not in ("add", "remove") or words[1] not in ("course", "sender", "topic"):
        return usage
    action, kind, key, extra = words[0], words[1], words[2], words[3:]
    if action == "remove":
        return rules_reply(Namespace(action="remove", kind=kind, key=key))
    flags = {w.lower() for w in extra}
    priority = next((int(w[1]) for w in flags if len(w) == 2 and w[0] == "p" and w[1] in "12345"), None)
    plain = [w for w in extra if w.lower() not in ("direct", "boost") and not (len(w) == 2 and w.lower()[0] == "p" and w[1] in "12345")]
    args = Namespace(action="add", kind=kind, key=key, priority=priority, boost="boost" in flags,
                     direct="direct" in flags, label=plain[0] if kind == "sender" and plain else None,
                     description=" ".join(plain) if kind == "topic" and plain else None)
    return rules_reply(args)


def start(stop: threading.Event) -> threading.Thread | None:
    """Start the listener in a background thread (serve does this), unless CHAT=off or there's no bot token."""
    if not enabled():
        return None
    t = threading.Thread(target=Bot().run, args=(stop,), name="mailbrief-chat", daemon=True)
    t.start()
    return t


def run_foreground() -> int:
    """`mailbrief bot`: just the listener, until Ctrl+C."""
    if not enabled():
        print("Chat is off: set TELEGRAM_BOT_TOKEN and CHAT=on in .env.")
        return 2
    from mailbrief.service import Busy, lock

    stop = threading.Event()
    try:
        with lock("serve"):  # serve already runs this listener: two readers would fight over getUpdates (409)
            print("Listening for your Telegram messages (Ctrl+C to stop)…")
            try:
                Bot().run(stop)
            except KeyboardInterrupt:
                stop.set()
    except Busy:
        print("`mailbrief serve` is running and already answers your chat; stop it first to run the bot alone.")
        return 3
    return 0
