"""Running MailBrief on its own: `serve` (runs forever, fires runs on a schedule), `stop`, `status`, `autostart`.

The same `serve` runs on your PC (started hidden at logon by Windows Task Scheduler) and on a server (as the
Docker container's command). Each scheduled run is a child process (`mailbrief run --send --quiet …`), so a
crash or hang in Outlook/the AI never takes `serve` down. OS file locks keep two runs (or two serves) apart.

Schedule (RUN_AT in .env, or `serve --at`): entries separated by ";", each "<days> <HH:MM> [scope]".
    days  = daily | weekdays | weekends | mon,tue,… | day-N (day of the month); comma lists mix freely
    scope = new (default) | this-week | this-month | last-month | older | all
"""

import io
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, time as clock, timedelta
from pathlib import Path

DATA = Path("data")
STATE_PATH = DATA / "schedule.json"
STOP_PATH = DATA / "stop.request"
LOG_DIR = DATA / "logs"
DEFAULT_SCHEDULE = "daily 07:30"
SCOPES = ("new", "this-week", "this-month", "last-month", "older", "all")
TICK_S = 30  # how often the clock is checked; checking (not one long sleep) survives the PC sleeping
RUN_TIMEOUT_S = 45 * 60  # a run that takes longer is stuck: kill it and retry
RETRY_S = 15 * 60
MAX_ATTEMPTS = 3
LOOKBACK_DAYS = 35  # far enough back to find a missed monthly ("day-1") slot
TASK_NAME = "MailBrief"
DAY_NAMES = {d: i for i, d in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}
DAY_GROUPS = {"daily": set(range(7)), "weekdays": set(range(5)), "weekends": {5, 6}}


class Busy(Exception):
    pass


# ── schedule ──────────────────────────────────────────────────────────────────────────────────────

def parse_schedule(text: str) -> list[dict]:
    """'daily 07:30; sun 20:00 this-week' → [{weekdays, monthdays, at, scope}, …]. Raises ValueError with the bad entry."""
    entries = []
    for raw in (text or "").split(";"):
        parts = raw.split()
        if not parts:
            continue
        if len(parts) not in (2, 3):
            raise ValueError(f"{raw.strip()!r}: expected '<days> <HH:MM> [scope]'")
        weekdays, monthdays = set(), set()
        for day in parts[0].lower().split(","):
            if day in DAY_GROUPS:
                weekdays |= DAY_GROUPS[day]
            elif day in DAY_NAMES:
                weekdays.add(DAY_NAMES[day])
            elif (m := re.fullmatch(r"day-(\d{1,2})", day)) and 1 <= int(m[1]) <= 31:
                monthdays.add(int(m[1]))
            else:
                raise ValueError(f"{raw.strip()!r}: unknown day {day!r} (daily, weekdays, weekends, mon…sun, day-N)")
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", parts[1])
        if not m or int(m[1]) > 23 or int(m[2]) > 59:
            raise ValueError(f"{raw.strip()!r}: time must look like 07:30")
        scope = parts[2].lower() if len(parts) == 3 else "new"
        if scope not in SCOPES:
            raise ValueError(f"{raw.strip()!r}: scope must be one of {', '.join(SCOPES)}")
        entries.append({"weekdays": weekdays, "monthdays": monthdays, "at": clock(int(m[1]), int(m[2])), "scope": scope})
    if not entries:
        raise ValueError("the schedule is empty")
    return entries


def _slots(schedule: list[dict], start: datetime, end: datetime):
    """Every (time, scope) the schedule fires in (start, end]. Times carry start's timezone."""
    day = start.date()
    while day <= end.date():
        for e in schedule:
            if day.weekday() in e["weekdays"] or day.day in e["monthdays"]:
                at = datetime.combine(day, e["at"], tzinfo=start.tzinfo)
                if start < at <= end:
                    yield at, e["scope"]
        day += timedelta(days=1)


def due_slots(now: datetime, schedule: list[dict], last_done: datetime) -> list[tuple[datetime, str]]:
    """Slots missed since last_done, keeping only the latest per scope (3 days off → one 'new' digest, not 3)."""
    start = max(last_done, now - timedelta(days=LOOKBACK_DAYS))
    latest: dict[str, datetime] = {}
    for at, scope in _slots(schedule, start, now):
        latest[scope] = max(at, latest.get(scope, at))
    return sorted((at, scope) for scope, at in latest.items())


def next_slot(now: datetime, schedule: list[dict]) -> datetime | None:
    return min((at for at, _ in _slots(schedule, now, now + timedelta(days=LOOKBACK_DAYS))), default=None)


def run_args(scope: str) -> list[str]:
    """'new' advances the cursor; a period summary doesn't, so it never swallows emails the next daily digest needs."""
    return ["run", "--send", "--quiet"] + (["--commit"] if scope == "new" else ["--digest", scope])


# ── locks and state ───────────────────────────────────────────────────────────────────────────────

@contextmanager
def lock(name: str):
    """An OS lock on data/<name>.lock. The OS drops it when the process dies, so it can never go stale."""
    DATA.mkdir(exist_ok=True)
    f = open(DATA / f"{name}.lock", "a+")
    try:
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Busy(name) from None
        yield
    finally:
        f.close()


def is_locked(name: str) -> bool:
    try:
        with lock(name):
            return False
    except Busy:
        return True


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def save_state(state: dict) -> None:
    DATA.mkdir(exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_PATH)


def _tz():
    from mailbrief.main import _tz
    return _tz()


def log_path() -> Path:
    return LOG_DIR / f"{datetime.now(_tz()):%Y-%m}.log"


def log(msg: str) -> None:
    """A timestamped line in data/logs/YYYY-MM.log, and on screen when there is one."""
    line = f"{datetime.now(_tz()):%Y-%m-%d %H:%M:%S} {msg}"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with log_path().open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    if sys.stdout:  # None under pythonw (autostart): no screen, the log is enough
        print(line, flush=True)


# ── serve ─────────────────────────────────────────────────────────────────────────────────────────

def _python() -> str:
    exe = Path(sys.executable)
    return str(exe.with_name("python.exe")) if exe.name.lower() == "pythonw.exe" else str(exe)


def _run_child(scope: str) -> int:
    """One scheduled run as a child process; its output goes to the log (and the screen). Returns its exit code."""
    cmd = [_python(), "-m", "mailbrief.main", *run_args(scope)]
    if os.name == "nt":  # own process group: your Ctrl+C reaches serve only, which lets the run finish
        extra = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    else:
        extra = {"start_new_session": True}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, **extra)
    _children.add(proc)  # serve waits for (or kills) these when it stops, /sync runs included

    def copy_output():
        with log_path().open("a", encoding="utf-8") as f:
            for raw in proc.stdout:
                line = "    " + raw.decode("utf-8", "replace").rstrip()
                f.write(line + "\n")
                f.flush()
                if sys.stdout:
                    print(line, flush=True)

    reader = threading.Thread(target=copy_output, daemon=True)
    reader.start()
    t0 = time.monotonic()
    try:
        while True:
            try:
                code = proc.wait(timeout=1)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() - t0 > RUN_TIMEOUT_S:
                    proc.kill()
                    proc.wait()
                    log(f"run took over {RUN_TIMEOUT_S // 60} min and was stopped")
                    code = -1
                    break
    except KeyboardInterrupt:  # second Ctrl+C: stop now, run included
        proc.kill()
        raise
    finally:
        _children.discard(proc)
    reader.join(timeout=5)
    return code


_children: set = set()  # runs started by _run_child that haven't finished


def _alert_login(state: dict) -> None:
    """Once a day: tell the destinations the Outlook login needs renewing (unattended runs can't ask)."""
    today = datetime.now(_tz()).date().isoformat()
    if state.get("alert_day") == today:
        return
    from mailbrief.main import deliver

    out = io.StringIO()
    from mailbrief.notify import bot

    how = "send /login here to sign in again" if bot.enabled() else "run `mailbrief login`"
    if deliver(f"⚠️ MailBrief: the Outlook login has expired, so no digest until you {how}.", out):
        state["alert_day"] = today
    for line in out.getvalue().splitlines():
        log(line)


def serve(spec: str) -> int:
    schedule = parse_schedule(spec)  # bad schedules fail before anything starts
    try:
        with lock("serve"):
            return _serve(spec, schedule)
    except Busy:
        print("MailBrief is already running (see `mailbrief status`; stop it with `mailbrief stop`).")
        return 3


def _serve(spec: str, schedule: list[dict]) -> int:
    tz = _tz()
    STOP_PATH.unlink(missing_ok=True)
    state = load_state()
    state.setdefault("last_done", datetime.now(tz).isoformat())  # first start: no catch-up, wait for the next slot
    state.update(schedule=spec, pid=os.getpid(), started=datetime.now(tz).isoformat())
    save_state(state)

    stopping = threading.Event()

    def on_signal(signum, frame):
        if stopping.is_set():
            raise KeyboardInterrupt  # asked twice: stop immediately
        stopping.set()
        log("stop requested: finishing up (press Ctrl+C again to stop immediately)")

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):  # Ctrl+C · docker stop · Ctrl+Break / console closed
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), on_signal)

    def stop_wanted() -> bool:
        if STOP_PATH.exists() and not stopping.is_set():
            stopping.set()
            log("stop requested by `mailbrief stop`")
        return stopping.is_set()

    log(f"MailBrief service started (pid {os.getpid()}), schedule: {spec}")
    from mailbrief.notify import bot

    from mailbrief.session import remote_login

    try:
        if (web := remote_login.start_always()):  # Render: a web service must keep a port open
            log(f"web: listening on port {web} (everything is 404 except an open /login sign-in)")
    except (OSError, ValueError) as e:
        log(f"web: couldn't open the port ({e})")
    if bot.start(stopping):  # Telegram chat (M7) in a thread; CHAT=off or no token: send-only, as before
        log("chat: on (only your registered private chats get answers)")
    announced, retry_at, attempts, done_now = None, None, 0, set()
    try:
        while not stop_wanted():
            now = datetime.now(tz)
            due = [s for s in due_slots(now, schedule, datetime.fromisoformat(state["last_done"])) if s not in done_now]
            if due and (retry_at is None or now >= retry_at):
                attempts += 1
                for at, scope in due:
                    log(f"run started ({scope}, slot {at:%a %d %b %H:%M})")
                    t0 = time.monotonic()
                    code = _run_child(scope)
                    secs = int(time.monotonic() - t0)
                    result = {0: "ok", 2: "login needed", 4: "sent, but only previews (cursor kept)"}.get(code, f"failed (exit {code})")
                    log(f"run finished: {result} in {secs}s")
                    state["last_run"] = {"at": datetime.now(tz).isoformat(), "scope": scope, "result": result, "seconds": secs}
                    if code == 2:
                        _alert_login(state)  # not retried: only you can log in again
                    if code in (0, 2, 4):  # 4: digest already sent; retrying would only send it again
                        done_now.add((at, scope))
                    if stopping.is_set():
                        break
                complete = all(s in done_now for s in due)
                if complete or (attempts >= MAX_ATTEMPTS and not stopping.is_set()):
                    if not complete:
                        log(f"giving up on this slot after {MAX_ATTEMPTS} attempts; the next scheduled run goes ahead as normal")
                    state["last_done"] = max(at for at, _ in due).isoformat()
                    retry_at, attempts, done_now = None, 0, set()
                elif not stopping.is_set():  # stopping with work left: the next start catches up instead
                    retry_at = datetime.now(tz) + timedelta(seconds=RETRY_S)
                    log(f"will retry at {retry_at:%H:%M} (attempt {attempts + 1} of {MAX_ATTEMPTS})")
                save_state(state)
                continue
            upcoming = retry_at or next_slot(now, schedule)
            if upcoming != announced:
                announced = upcoming
                state["next"] = upcoming.isoformat() if upcoming else None
                save_state(state)
                log(f"next run: {upcoming:%a %d %b %H:%M}" if upcoming else "nothing scheduled in the next 35 days")
            for _ in range(TICK_S):  # short sleeps: a stop request is noticed within a second
                if stop_wanted():
                    break
                time.sleep(1)
        if _children:  # a /sync run (bot thread): it would outlive serve, without its 45-minute limit
            log("waiting for the /sync run to finish (press Ctrl+C again to stop it now)")
            while _children:
                time.sleep(1)
    except KeyboardInterrupt:
        for proc in list(_children):
            proc.kill()
        log("stopped immediately")
        return 130
    finally:
        STOP_PATH.unlink(missing_ok=True)
        state.update(pid=None, next=None)
        save_state(state)
    log("MailBrief service stopped")
    return 0


# ── stop / status / autostart ─────────────────────────────────────────────────────────────────────

def stop(wait_s: int = 10) -> int:
    if not is_locked("serve"):
        print("MailBrief isn't running.")
        return 0
    STOP_PATH.parent.mkdir(exist_ok=True)
    STOP_PATH.write_text("")
    print("Stop requested…")
    for _ in range(wait_s):
        time.sleep(1)
        if not is_locked("serve"):
            print("MailBrief stopped.")
            return 0
    print("It's finishing the current run and will stop when that's done (check with `mailbrief status`).")
    return 0


def _task_exists() -> bool | None:
    if os.name != "nt":
        return None
    return subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True).returncode == 0


def status(spec: str) -> int:
    tz = _tz()
    state = load_state()
    running = is_locked("serve")
    if running and STOP_PATH.exists():
        print("Service:   stopping (finishing the current run)")
    elif running:
        print(f"Service:   running (pid {state.get('pid')}, since "
              f"{datetime.fromisoformat(state['started']).astimezone(tz):%a %d %b %H:%M})" if state.get("started") else "Service:   running")
    else:
        print("Service:   not running (start: `mailbrief serve`)")
    print(f"Schedule:  {state.get('schedule') if running and state.get('schedule') else spec}")
    if running and state.get("next"):
        print(f"Next run:  {datetime.fromisoformat(state['next']).astimezone(tz):%a %d %b %H:%M}")
    if running and is_locked("run"):
        print("Right now: a run is in progress")
    last = state.get("last_run")
    if last:
        print(f"Last run:  {datetime.fromisoformat(last['at']).astimezone(tz):%a %d %b %H:%M} ({last['scope']}): "
              f"{last['result']}, {last['seconds']}s")
    task = _task_exists()
    if task is not None:
        print(f"Autostart: {'on (starts at logon)' if task else 'off'}")
    print(f"Log:       {log_path()}")
    return 0


def autostart(on: bool) -> int:
    """Windows Task Scheduler task 'MailBrief': at logon, start `serve` hidden (pythonw: no window)."""
    if os.name != "nt":
        print("autostart is for Windows. On a server, run it with Docker (see commands.md, 'Hosting').")
        return 2
    if not on:
        if not _task_exists():
            print("Autostart is already off.")
            return 0
        ps = f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false"
    else:
        root = Path(__file__).resolve().parents[1]  # the project folder: data/ and .env live here
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        q = lambda p: str(p).replace("'", "''")  # noqa: E731 - PowerShell single-quote escaping
        ps = (f"$a = New-ScheduledTaskAction -Execute '{q(pythonw)}' -Argument '-m mailbrief.main serve' "
              f"-WorkingDirectory '{q(root)}'; "
              "$t = New-ScheduledTaskTrigger -AtLogOn -User \"$env:USERDOMAIN\\$env:USERNAME\"; "
              "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
              "-ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew "
              "-RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5); "
              f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $a -Trigger $t -Settings $s "
              "-Description 'MailBrief: scheduled email digests (mailbrief serve)' -Force | Out-Null")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Task Scheduler refused: {r.stderr.strip() or r.stdout.strip()}")
        return 1
    if on:
        print(f"Autostart on: MailBrief starts hidden each time you log in to Windows.\n"
              f"Start it now without logging out: schtasks /Run /TN {TASK_NAME}")
    else:
        print("Autostart off." + (" It's still running now; stop it with `mailbrief stop`." if is_locked("serve") else ""))
    return 0
