"""Where digests go. Written only by the local CLI (`mailbrief add-destination`).

ponytail: a JSON file for one user; moves to the `destinations` table in M5.
"""

import json
from pathlib import Path

PATH = Path("data/destinations.json")


def load() -> list[dict]:
    return json.loads(PATH.read_text()) if PATH.exists() else []


def add(type_: str, target: str, label: str) -> None:
    items = [d for d in load() if not (d["type"] == type_ and d["target"] == target)]
    items.append({"type": type_, "target": target, "label": label, "active": True})
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(items, indent=2))
