"""Saved emails: one file per received month in data/archive/ (YYYY-MM.enc, or YYYY-MM.json with --no-password).

Encrypted with SESSION_ENCRYPTION_KEY by default; a month only ever has one of the two files. Files never
move: "this week / this month / last month / older" are computed when viewing (period_range).
Images are never stored, only their names.
"""

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from cryptography.fernet import InvalidToken

from mailbrief.storage.crypto import decrypt, encrypt

ARCHIVE_DIR = Path("data/archive")
EXTS = (".enc", ".json")
PERIODS = ("this-week", "this-month", "last-month", "older")
_MONTH = re.compile(r"^\d{4}-\d{2}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ArchiveError(Exception):
    pass


def _path(month: str, plain: bool) -> Path:
    return ARCHIVE_DIR / f"{month}{'.json' if plain else '.enc'}"


def _read(path: Path) -> dict:
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        return decrypt(path.read_bytes())
    except InvalidToken:
        raise ArchiveError(f"can't decrypt {path.name}: SESSION_ENCRYPTION_KEY is not the key it was saved with") from None


def _load_month(month: str) -> dict:
    for plain in (False, True):
        path = _path(month, plain)
        if path.exists():
            return _read(path)
    return {"emails": [], "digests": []}


def _write_month(month: str, data: dict, plain: bool) -> Path:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(month, plain)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if plain:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        tmp.write_bytes(encrypt(data))
    tmp.replace(path)  # atomic: a crash mid-write never leaves a broken file
    _path(month, not plain).unlink(missing_ok=True)  # one file per month
    return path


LABEL_KEYS = ("outlook_labels", "labels_cleared", "outlook_gone")  # Outlook-label bookkeeping (labels.py)


def _merge(data: dict, new: list[dict]) -> None:
    merged = {m["id"]: m for m in data["emails"]}
    for m in new:  # a re-run replaces the stored copy, never duplicates…
        old = merged.get(m["id"], {})
        merged[m["id"]] = {**{k: old[k] for k in LABEL_KEYS if k in old}, **m}  # …but keeps what Outlook was given
    data["emails"] = sorted(merged.values(), key=lambda m: datetime.fromisoformat(m["received_at"]))


def update_fields(changes: dict[str, dict]) -> int:
    """Set fields on archived emails: {id: {field: value}}. Each touched month is rewritten in its own format."""
    left, done = dict(changes), 0
    for month in months():
        if not left:
            break
        path = next(p for p in (_path(month, False), _path(month, True)) if p.exists())
        data = _read(path)
        hit = False
        for m in data["emails"]:
            if m["id"] in left:
                m.update(left.pop(m["id"]))
                hit, done = True, done + 1
        if hit:
            _write_month(month, data, plain=path.suffix == ".json")
    return done


def _migrate() -> None:
    """One-time: fold the old per-day files (YYYY-MM-DD.*) into their month file."""
    if not ARCHIVE_DIR.exists():
        return
    for path in sorted(ARCHIVE_DIR.iterdir()):
        if path.suffix in EXTS and _DAY.match(path.stem):
            month, day_data = path.stem[:7], _read(path)
            data = _load_month(month)
            _merge(data, day_data["emails"])
            data["digests"] = sorted(data["digests"] + day_data["digests"], key=lambda d: d["at"])
            _write_month(month, data, plain=path.suffix == ".json")
            path.unlink()


def months() -> list[str]:
    """Months that have a file, oldest first ("YYYY-MM")."""
    _migrate()
    if not ARCHIVE_DIR.exists():
        return []
    return sorted({p.stem for p in ARCHIVE_DIR.iterdir() if p.suffix in EXTS and _MONTH.match(p.stem)})


def save(emails: list[dict], results: list[dict], digest: str | None, plain: bool, tz,
         now: datetime | None = None, digest_scope: str = "new") -> list[Path]:
    """Merge emails (by id, with their classification) into month files; the digest goes into this month's."""
    _migrate()
    now = now or datetime.now(tz)
    by_month: dict[str, list[dict]] = {}
    for email, result in zip(emails, results):
        record = {**email, "received_at": email["received_at"].isoformat(), "classification": result}
        by_month.setdefault(f"{email['received_at'].astimezone(tz):%Y-%m}", []).append(record)
    if digest:
        by_month.setdefault(f"{now:%Y-%m}", [])
    paths = []
    for month, new in sorted(by_month.items()):
        data = _load_month(month)
        _merge(data, new)
        if digest and month == f"{now:%Y-%m}":
            data["digests"].append({"at": now.isoformat(), "scope": digest_scope, "text": digest})
        paths.append(_write_month(month, data, plain))
    return paths


def load(month_list: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """(emails newest first with received_at as datetime, digests) for these months (default: all)."""
    emails, digests = [], []
    for month in months() if month_list is None else month_list:
        data = _load_month(month)
        emails += [{**m, "received_at": datetime.fromisoformat(m["received_at"])} for m in data["emails"]]
        digests += data["digests"]
    emails.sort(key=lambda m: m["received_at"], reverse=True)
    return emails, digests


def known(ids) -> dict[str, dict]:
    """Already-archived emails among these ids: {id: stored email}. Lets runs skip repeat AI work."""
    wanted = set(ids)
    if not wanted:
        return {}
    emails, _ = load()
    return {e["id"]: e for e in emails if e["id"] in wanted}


def _month_start(d: date, back: int = 0) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - back, 12)
    return date(y, m + 1, 1)


def period_range(name: str, today: date) -> tuple[date | None, date | None]:
    """[start, end) dates for a period; None means open-ended."""
    if name == "this-week":
        return today - timedelta(days=today.weekday()), None
    if name == "this-month":
        return _month_start(today), None
    if name == "last-month":
        return _month_start(today, 1), _month_start(today)
    if name == "older":
        return None, _month_start(today, 1)
    raise ValueError(f"unknown period {name!r}; use one of {', '.join(PERIODS)}")


def in_period(email: dict, name: str, today: date, tz) -> bool:
    start, end = period_range(name, today)
    d = email["received_at"].astimezone(tz).date()
    return (start is None or d >= start) and (end is None or d < end)


def prune(today: date) -> int:
    """Delete month files that ended before ARCHIVE_DAYS ago (default 0 = keep forever). Returns files deleted."""
    keep = int(os.environ.get("ARCHIVE_DAYS", "0"))
    if keep <= 0:
        return 0
    cutoff = today - timedelta(days=keep)
    deleted = 0
    for month in months():
        y, m = map(int, month.split("-"))
        if _month_start(date(y, m, 1), -1) <= cutoff:  # the month ended before the cutoff
            for ext in EXTS:
                path = ARCHIVE_DIR / f"{month}{ext}"
                if path.exists():
                    path.unlink()
                    deleted += 1
    return deleted
