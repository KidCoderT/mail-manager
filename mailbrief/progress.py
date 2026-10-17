"""Progress output: what the app is doing right now, so a long run never looks stuck.

Everything goes to stderr (so `run --json` keeps stdout pure JSON). On a terminal, counters and spinners
redraw one line with "\\r"; when piped or redirected (a log file, the scheduler) only plain lines are
printed, so logs stay readable.
"""

import sys
import threading
import time
from contextlib import contextmanager

OUT = None  # tests swap in a StringIO; None = sys.stderr
START = time.monotonic()
SPINNER = "|/-\\"
_lock = threading.Lock()
_open_line = False  # a "\r" line is on screen and needs a newline before normal output
_quarters: dict[str, int] = {}


def _out():
    return OUT or sys.stderr


def _tty() -> bool:
    try:
        return _out().isatty()
    except (AttributeError, ValueError):
        return False


def _stamp() -> str:
    s = int(time.monotonic() - START)
    return f"[{s // 60:02d}:{s % 60:02d}]"


def _write(text: str, live: bool = False) -> None:
    """Print a line; `live` lines are redrawn in place on a terminal."""
    global _open_line
    with _lock:
        out = _out()
        if live:
            out.write("\r" + text + "   ")
            _open_line = True
        else:
            out.write(("\n" if _open_line else "") + text + "\n")
            _open_line = False
        out.flush()


def step(msg: str) -> None:
    """A phase starting: '[00:12] Loading Focused tab…'."""
    _write(f"{_stamp()} {msg}")


def count(label: str, n: int, total: int) -> None:
    """A counter: live on a terminal; every 25% (and at the end) when piped."""
    if total <= 0:
        return
    line = f"{_stamp()} {label} {n}/{total}"
    if _tty():
        _write(line, live=n < total)
        return
    quarter = 4 * n // total
    if n >= total or quarter > _quarters.get(label, 0):
        _quarters[label] = quarter
        _write(line)


class _Working:
    def __init__(self, label: str):
        self.label, self.detail, self.t0 = label, "", time.monotonic()

    def note(self, detail: str) -> None:
        """Extra live detail, e.g. 'part 7/15' (shown on a terminal only)."""
        self.detail = detail

    def _line(self, frame: str) -> str:
        detail = f" {self.detail}" if self.detail else ""
        return f"{frame} {self.label}{detail}… {int(time.monotonic() - self.t0)}s"


@contextmanager
def working(label: str):
    """A long single job (an AI call): spinner + elapsed seconds on a terminal, then '✓ label (41s)'."""
    w = _Working(label)
    stop = threading.Event()
    spinner = None
    if _tty():
        def spin():
            i = 0
            while not stop.wait(0.2):
                _write(w._line(SPINNER[i % len(SPINNER)]), live=True)
                i += 1
        spinner = threading.Thread(target=spin, daemon=True)
        spinner.start()
    else:
        _write(f"{_stamp()} {label}…")
    mark = "✗"
    try:
        yield w
        mark = "✓"
    finally:
        stop.set()
        if spinner:
            spinner.join()
        _write(f"{_stamp()} {mark} {label} ({int(time.monotonic() - w.t0)}s)")
