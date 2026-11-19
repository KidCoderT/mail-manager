from pathlib import Path

from mailbrief.storage.files import replace

from mailbrief.storage.crypto import decrypt, encrypt

# ponytail: single user, single file; per-user paths + sessions table when multi-user lands
SESSION_PATH = Path("data/session.enc")


def load() -> dict | None:
    """Return {"state": storage_state, "user_agent": str}, or None if never logged in."""
    if not SESSION_PATH.exists():
        return None
    return decrypt(SESSION_PATH.read_bytes())


def account() -> str | None:
    """The address the saved session belongs to, if a run has recorded it yet. Never raises."""
    try:
        return (load() or {}).get("account")
    except Exception:  # noqa: BLE001 - an unreadable session has no known account
        return None


def save(context, user_agent: str, account_: str | None = None) -> None:
    """account_: the signed-in address when the caller knows it; otherwise the recorded one is kept."""
    SESSION_PATH.parent.mkdir(exist_ok=True)
    who = account_ or account()
    blob = encrypt({"state": context.storage_state(), "user_agent": user_agent, **({"account": who} if who else {})})
    tmp = SESSION_PATH.with_suffix(".tmp")
    tmp.write_bytes(blob)
    replace(tmp, SESSION_PATH)  # atomic: a crash mid-write never leaves a broken session
