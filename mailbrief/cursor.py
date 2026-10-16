"""Which emails are new since the last committed run.

ponytail: a JSON file for one user; moves to the SQLite `cursors` table in M5.
ponytail: mail moved into the inbox late (rules, Junk) can have received_at before the cursor and is
skipped; fix with a small look-back window, since recent_ids already dedupes.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

CURSOR_PATH = Path("data/cursor.json")
FIRST_RUN_LOOKBACK = timedelta(hours=24)
KEEP_IDS = 500


def load() -> dict:
    if CURSOR_PATH.exists():
        return json.loads(CURSOR_PATH.read_text())
    return {"last_processed_at": None, "recent_ids": []}


def since(cursor: dict, now: datetime | None = None) -> datetime:
    if cursor["last_processed_at"]:
        return datetime.fromisoformat(cursor["last_processed_at"])
    return (now or datetime.now(timezone.utc)) - FIRST_RUN_LOOKBACK


def select_new(records: list[dict], cursor: dict) -> list[dict]:
    start, seen = since(cursor), set(cursor["recent_ids"])
    # >= plus the id check: a second email at the exact cursor second is still picked up.
    return [r for r in records if r["received_at"] >= start and r["id"] not in seen]


def advance(cursor: dict, records: list[dict]) -> dict:
    if any(r["body_source"] != "getitem" for r in records):
        raise ValueError("refusing to advance the cursor: some emails only have list previews, not full text")
    if not records:
        return cursor
    latest = max(r["received_at"] for r in records)
    if cursor["last_processed_at"]:
        latest = max(latest, datetime.fromisoformat(cursor["last_processed_at"]))
    return {
        "last_processed_at": latest.isoformat(),
        "recent_ids": (cursor["recent_ids"] + [r["id"] for r in records])[-KEEP_IDS:],
    }


def save(cursor: dict) -> None:
    CURSOR_PATH.parent.mkdir(exist_ok=True)
    tmp = CURSOR_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cursor))
    tmp.replace(CURSOR_PATH)
