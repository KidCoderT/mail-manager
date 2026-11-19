import json
import os

from cryptography.fernet import Fernet

from mailbrief import ConfigError


def _fernet() -> Fernet:
    key = os.environ.get("SESSION_ENCRYPTION_KEY")
    if not key:
        raise ConfigError("SESSION_ENCRYPTION_KEY is not set (see .env.example)")
    return Fernet(key)


def encrypt(data: dict) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode())


def decrypt(blob: bytes) -> dict:
    return json.loads(_fernet().decrypt(blob))
