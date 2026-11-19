"""Atomic file replacement that also works on Windows."""

import os
import time
from pathlib import Path


def replace(tmp: Path, path: Path, tries: int = 15, wait: float = 0.2) -> None:
    """os.replace, retried: on Windows it fails with PermissionError while another process has `path` open
    (`mailbrief emails` or the chat reading a month, a virus scanner, the search indexer). Those reads last
    milliseconds, so a short wait gets through; after ~3 s the error is real and is raised."""
    for n in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if n == tries - 1:
                raise
            time.sleep(wait)
