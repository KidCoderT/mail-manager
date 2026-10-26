"""The UPCOMING EVENTS message: a rolling calendar built by code (no AI) from the events the classifier found.

Every saved inbox email's classification.events, next EVENTS_DAYS days (default 14; 0 = no message), grouped by
day. 🆕 = from this digest's emails, ⭐ = from a boosted email (your rules), listed first within its day.
"""

import html as _html
import os
import re
from datetime import date, timedelta

from mailbrief import links

DEFAULT_DAYS = 14


def days() -> int:
    try:
        return max(0, int(os.environ.get("EVENTS_DAYS", DEFAULT_DAYS)))
    except ValueError:
        return DEFAULT_DAYS


def _key(ev: dict) -> tuple:
    return re.sub(r"[^a-z0-9]", "", ev["name"].lower()), ev.get("date")


def upcoming(emails: list[dict], today: date, window: int, new_ids=(), your_rules: dict | None = None,
             past: int = 0) -> list[dict]:
    """Events dated today-past … today+window (undated ones only from new emails), merged across emails."""
    from mailbrief import rules

    your_rules = your_rules or rules.empty()
    new_ids, first, last = set(new_ids), today - timedelta(days=past), today + timedelta(days=window)
    merged: dict[tuple, dict] = {}
    for e in emails:
        c = e.get("classification") or {}
        if c.get("category") in (None, "Sent", "Elsewhere") or not c.get("events"):
            continue
        boosted = rules.effective(e, your_rules)["boosted"]
        for ev in c["events"]:
            d = date.fromisoformat(ev["date"]) if ev.get("date") else None
            if (d is None and e["id"] not in new_ids) or (d is not None and not first <= d <= last):
                continue
            item = {**ev, "new": e["id"] in new_ids, "boosted": boosted, "from": e.get("sender_name") or "",
                    "email_id": e["id"]}  # merged events keep the first email's id (for the ↗ link)
            old = merged.get(_key(ev))
            if old is None:
                merged[_key(ev)] = item
            else:  # the same event in two emails: keep one, fill its gaps from the other
                merged[_key(ev)] = {**{k: v for k, v in item.items() if v}, **{k: v for k, v in old.items() if v},
                                    "new": old["new"] or item["new"], "boosted": old["boosted"] or item["boosted"]}
    return list(merged.values())


def _time_key(t: str | None) -> int:
    """Minutes since midnight for sorting "7pm", "10:30am", "14:00"; unknown times go last."""
    m = re.match(r"\s*(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?", (t or "").lower())
    if not m:
        return 24 * 60
    h, mins = int(m.group(1)) % 24, int(m.group(2) or 0)
    if m.group(3) and m.group(3).startswith("p") and h < 12:
        h += 12
    if m.group(3) and m.group(3).startswith("a") and h == 12:
        h = 0
    return h * 60 + mins


def _line(ev: dict, today: date, html_mode: bool = False) -> list[str]:
    esc = (lambda t: _html.escape(t, quote=False)) if html_mode else (lambda t: t)
    mark = ("⭐" if ev["boosted"] else "") + ("🆕" if ev["new"] else "") or "•"
    head = esc(" · ".join(x for x in (ev.get("time"), ev["name"], ev.get("place")) if x))
    if html_mode and ev.get("email_id"):
        head += f" {links.anchor(ev['email_id'])}"  # ↗ opens the email that announced it
    lines = [f"{mark} {head}"]
    if ev.get("detail"):
        lines.append(f"   {esc(ev['detail'])}")
    signup = ev.get("signup_deadline")
    is_past = bool(ev.get("date")) and date.fromisoformat(ev["date"]) < today
    tail = []
    if signup and not is_past:  # "sign-up closed" on every past event is just noise
        d = date.fromisoformat(signup)
        tail.append(f"sign up by {d:%a %d %b}" if d >= today else "sign-up closed")
    if ev.get("link"):
        tail.append(ev["link"])
    if tail:
        lines.append("   " + esc(" · ".join(tail)))
    return lines


def render(events: list[dict], today: date, window: int = DEFAULT_DAYS, past: int = 0, html: bool = False) -> str | None:
    """The message text, or None when there's nothing to show. Day headings are uppercase (past days get a
    "(PAST)" note), so long messages split per day in telegram.messages(). html=True: Telegram HTML, every event
    ending with a ↗ link to its email."""
    if not events:
        return None
    if not past:
        title = f"UPCOMING EVENTS · next {window} days"
    elif not window:
        title = f"PAST EVENTS · last {past} days"
    else:
        title = f"EVENTS · last {past} days + next {window} days"
    out = [f"📅 {title} ({len(events)})"]
    dated = sorted({e["date"] for e in events if e.get("date")})
    for day in dated + [None]:
        group = [e for e in events if e.get("date") == day]
        if not group:
            continue
        if day:
            d = date.fromisoformat(day)
            heading = f"{d:%a %d %b}".upper() + (" (PAST)" if d < today else "")
        else:
            heading = "DATE NOT GIVEN"
        out += ["", heading]
        for ev in sorted(group, key=lambda e: (not e["boosted"], _time_key(e.get("time")), e["name"].lower())):
            out += _line(ev, today, html)
    return "\n".join(out)


def build(today: date, new_ids=(), log=None, html: bool = False) -> str | None:
    """The events message from the saved archive and your rules (html=True: for Telegram, with ↗ links).
    Never raises: events are a bonus."""
    from mailbrief import archive, rules

    window = days()
    if not window:
        return None
    try:
        try:
            your_rules = rules.load()
        except rules.RulesError:
            your_rules = rules.empty()
        return render(upcoming(archive.load()[0], today, window, new_ids, your_rules), today, window, html=html)
    except Exception as e:  # noqa: BLE001
        if log:
            print(f"warning: events message not built ({type(e).__name__}: {e})", file=log)
        return None
