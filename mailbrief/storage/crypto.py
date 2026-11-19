import json
import os

from cryptography.fernet import Fernet

from mailbrief import ConfigError


MAKE_KEY = 'uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'


def _fernet() -> Fernet:
    key = (os.environ.get("SESSION_ENCRYPTION_KEY") or "").strip()
    if not key:
        raise ConfigError(f"SESSION_ENCRYPTION_KEY is not set. Make one and put it in .env:\n  {MAKE_KEY}")
    try:
        return Fernet(key)
    except ValueError:  # not 32 url-safe base64 bytes: a placeholder ("...") or a mangled paste
        raise ConfigError(f"SESSION_ENCRYPTION_KEY in .env isn't a valid key. Make one and paste it in whole:\n  {MAKE_KEY}") from None


def check_key() -> None:
    """Raise ConfigError now if the key is missing or malformed (before a sign-in is spent on it)."""
    _fernet()


def encrypt(data: dict) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode())


def decrypt(blob: bytes) -> dict:
    return json.loads(_fernet().decrypt(blob))
