"""Your own labels: data/rules.json (personal, git-ignored), edited by hand or with `mailbrief rules`.

Courses and senders are matched here in code (no AI); topics are tagged by the classifier from your descriptions.
labels.labels_for() asks effective() what an email should carry, so a rule change relabels the archive by itself.
"""

import json
import re
from pathlib import Path

RULES_PATH = Path("data/rules.json")
KINDS = ("courses", "senders", "topics")
RESERVED = {"urgent", "needs reply", "fyi", "meetings", "newsletter", "low priority", "unclassified",
            "p1", "p2", "p3", "p4", "p5"}  # the built-in MB: labels
BODY_SCAN = 1000  # ponytail: course codes only from the start of the body, so course-listing newsletters don't
#                   collect every code; "subject only for bulk senders" if that's still noisy
BOOST_FLOOR = 2   # a boosted email is at least P2 unless a rule says otherwise


class RulesError(Exception):
    pass


def empty() -> dict:
    return {"profile": "", "courses": [], "senders": [], "topics": []}


def _priority(value, where: str):
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
        raise RulesError(f"{where}: priority must be 1-5 or null, not {value!r}")
    return value


def _name(value, where: str) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 40 or any(c in name for c in ",;"):
        raise RulesError(f"{where}: a label name must be 1-40 characters without , or ; (got {value!r})")
    if name.lower() in RESERVED:
        raise RulesError(f"{where}: {name!r} is a built-in MailBrief label; pick another name")
    return name


def validate(data) -> dict:
    """A clean copy of the rules, or RulesError saying what's wrong (and where)."""
    if not isinstance(data, dict):
        raise RulesError("rules.json must hold a JSON object")
    out = empty()
    out["profile"] = str(data.get("profile") or "").strip()
    for kind in KINDS:
        if not isinstance(data.get(kind, []), list):
            raise RulesError(f"{kind} must be a list")
    for n, c in enumerate(data.get("courses", []), 1):
        c = {"code": c} if isinstance(c, str) else c
        where = f"courses #{n}"
        if not isinstance(c, dict):
            raise RulesError(f"{where}: expected a course code or an object")
        out["courses"].append({"code": _name(c.get("code"), where).upper(),
                               "priority": _priority(c.get("priority"), where), "boost": bool(c.get("boost"))})
    for n, s in enumerate(data.get("senders", []), 1):
        where = f"senders #{n}"
        if not isinstance(s, dict) or not str(s.get("match") or "").strip():
            raise RulesError(f"{where}: needs \"match\" (an address, or part of a sender's name)")
        out["senders"].append({"match": str(s["match"]).strip(), "label": _name(s.get("label"), where),
                               "direct_only": bool(s.get("direct_only")),
                               "priority": _priority(s.get("priority"), where), "boost": bool(s.get("boost"))})
    for n, t in enumerate(data.get("topics", []), 1):
        where = f"topics #{n}"
        if not isinstance(t, dict) or not str(t.get("description") or "").strip():
            raise RulesError(f"{where}: needs \"name\" and \"description\"")
        out["topics"].append({"name": _name(t.get("name"), where), "description": str(t["description"]).strip(),
                              "priority": _priority(t.get("priority"), where)})
    names = [label_name(k, r) for k in KINDS for r in out[k]]
    dupes = sorted({x for x in names if names.count(x) > 1})
    if dupes:
        raise RulesError(f"two rules give the same label: {', '.join(dupes)}")
    return out


def label_name(kind: str, rule: dict) -> str:
    """The Outlook label a rule gives: "MB: CS1101S", "MB: Prof Tan", "MB: Networking"."""
    return "MB: " + rule[{"courses": "code", "senders": "label", "topics": "name"}[kind]]


def rule_labels(r: dict) -> set[str]:
    return {label_name(k, rule) for k in KINDS for rule in r[k]}


_cache: tuple = (None, None)


def load(path: Path | None = None) -> dict:
    """The current rules (empty when there's no file). Re-read only when the file changes."""
    global _cache
    path = path or RULES_PATH
    if not path.exists():
        return empty()
    stamp = (str(path), path.stat().st_mtime_ns)
    if _cache[0] != stamp:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise RulesError(f"can't read {path}: {e}") from None
        _cache = (stamp, validate(data))
    return _cache[1]


def save(r: dict, path: Path | None = None) -> None:
    r, path = validate(r), path or RULES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)  # atomic, like the archive


def _key(kind: str, rule: dict) -> str:
    return rule[{"courses": "code", "senders": "match", "topics": "name"}[kind]].lower()


def add(r: dict, kind: str, rule: dict) -> dict:
    """Rules with this one added, or replacing the rule with the same key (code / match / name)."""
    if kind not in KINDS:
        raise RulesError(f"unknown kind {kind!r}; use course, sender or topic")
    new = validate({kind: [rule]})[kind][0]  # the rule on its own first, so a replacement isn't a "duplicate"
    return validate({**r, kind: [x for x in r[kind] if _key(kind, x) != _key(kind, new)] + [new]})


def remove(r: dict, kind: str, key: str) -> tuple[dict, dict | None]:
    """(rules without it, the removed rule or None)."""
    gone = next((x for x in r[kind] if _key(kind, x) == key.strip().lower()), None)
    return {**r, kind: [x for x in r[kind] if x is not gone]}, gone


def _sender_fits(rule: dict, email: dict) -> bool:
    m = rule["match"].lower()
    hit = (email.get("sender_email") or "").lower() == m if "@" in m else m in (email.get("sender_name") or "").lower()
    return hit and (not rule["direct_only"] or bool(email.get("direct")))


def matches(email: dict, r: dict) -> list[tuple[str, int | None, bool]]:
    """(label, priority floor, boosted) for every rule this email fits."""
    found = []
    text = " ".join([email.get("subject") or "", email.get("sender_name") or "", (email.get("body_text") or "")[:BODY_SCAN]])
    for c in r["courses"]:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(c['code'])}(?![A-Za-z0-9])", text, re.I):
            found.append((label_name("courses", c), c["priority"], c["boost"]))
    for s in r["senders"]:
        if _sender_fits(s, email):
            found.append((label_name("senders", s), s["priority"], s["boost"]))
    c = email.get("classification") or {}
    tags = {t.lower() for t in c.get("tags") or []}
    fits_profile = bool(c.get("boost")) or not r["profile"]  # no profile: any topic tag boosts
    for t in r["topics"]:
        if t["name"].lower() in tags:
            found.append((label_name("topics", t), t["priority"], fits_profile))
    return found


def effective(email: dict, r: dict) -> dict:
    """{"labels": rule labels, "priority": AI priority lowered by floors and boosts, "boosted": bool}."""
    found = matches(email, r)
    boosted = any(b for _, _, b in found)
    priority = (email.get("classification") or {}).get("priority")
    floors = [f for _, f, _ in found if f] + ([BOOST_FLOOR] if boosted and not any(f for _, f, b in found if b) else [])
    if isinstance(priority, int) and floors:
        priority = min([priority] + floors)
    return {"labels": [label for label, _, _ in found], "priority": priority, "boosted": boosted}
