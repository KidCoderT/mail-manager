from pathlib import Path

from mailbrief.storage.crypto import decrypt, encrypt

# ponytail: single user, single file; per-user paths + sessions table when multi-user lands
SESSION_PATH = Path("data/session.enc")


def load() -> dict | None:
    """Return {"state": storage_state, "user_agent": str}, or None if never logged in."""
    if not SESSION_PATH.exists():
        return None
    return decrypt(SESSION_PATH.read_bytes())


def save(context, user_agent: str) -> None:
    SESSION_PATH.parent.mkdir(exist_ok=True)
    blob = encrypt({"state": context.storage_state(), "user_agent": user_agent})
    tmp = SESSION_PATH.with_suffix(".tmp")
    tmp.write_bytes(blob)
    tmp.replace(SESSION_PATH)  # atomic: a crash mid-write never leaves a broken session
