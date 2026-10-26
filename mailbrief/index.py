"""The search index behind "ask your inbox" (M7): every saved email cut into chunks, each turned into a vector by the
embedding model (bge-m3), so a question finds emails by meaning, plus keywords for exact words.

Stored encrypted in data/index.enc as {"model", "items": {email id: {"hash", "vecs": [base64 float32]}}}. Chunk text
is NOT stored: it's recomputed from the archive, so the index holds no second copy of your mail. It's only derived
data: `mailbrief index rebuild` recreates it any time.
"""

import base64
import hashlib
import math
import os
import re
from array import array
from datetime import datetime, timezone
from operator import mul
from pathlib import Path

from mailbrief.storage.crypto import decrypt, encrypt

INDEX_PATH = Path("data/index.enc")
CHUNK = 1500         # characters per body chunk
OVERLAP = 200
MAX_BODY_CHUNKS = 6  # ponytail: very long newsletters are cut off after ~9k characters
MEANING, KEYWORDS = 0.65, 0.35
_cache: tuple = (None, None)  # (file stamp, loaded index), so a long-running bot decodes it once per change


def _model() -> str:
    return os.environ.get("AI_EMBED_MODEL", "bge-m3")


def indexable(email: dict) -> bool:
    """Full-text emails: inbox mail and your own replies (for "what did I tell them?"), not list previews."""
    return email.get("body_source") == "getitem" and (email.get("classification") or {}).get("category") is not None


def _split(text: str) -> list[str]:
    """~CHUNK-character pieces, cut at a paragraph or sentence break when there's one nearby, with OVERLAP."""
    out, start = [], 0
    while start < len(text) and len(out) < MAX_BODY_CHUNKS:
        end = min(len(text), start + CHUNK)
        if end < len(text):
            cut = max(text.rfind("\n\n", start + CHUNK // 2, end), text.rfind(". ", start + CHUNK // 2, end))
            end = cut + 1 if cut > 0 else end
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - OVERLAP, start + 1)
    return [c for c in out if c]


def chunks(email: dict) -> list[str]:
    """What gets embedded for one email: a header chunk (who, when, what, labels, events) + body chunks."""
    from mailbrief.ai.classifier import QUOTE_START

    c = email.get("classification") or {}
    when = email["received_at"] if isinstance(email["received_at"], datetime) else datetime.fromisoformat(email["received_at"])
    labels = [n.removeprefix("MB: ") for n in email.get("outlook_labels") or []] or [c.get("category") or ""]
    header = [f"Subject: {email.get('subject', '')}",
              f"From: {email.get('sender_name', '')} <{email.get('sender_email', '')}>",
              f"Date: {when:%a %d %b %Y}",
              f"Summary: {c.get('one_line_summary') or ''}",
              f"Labels: {', '.join(x for x in labels if x)}"]
    if email.get("attachment_names"):
        header.append(f"Attachments: {', '.join(email['attachment_names'])}")
    for ev in c.get("events") or []:
        header.append(f"Event: {ev.get('name')} {ev.get('date') or ''} {ev.get('time') or ''} {ev.get('place') or ''}".strip())
    body = email.get("body_text") or ""
    quote = QUOTE_START.search(body)  # quoted history is indexed with the email it came from, not again here
    body = (body[: quote.start()] if quote and quote.start() > 0 else body).strip()
    return ["\n".join(header)] + [f"{email.get('subject', '')}\n{piece}" for piece in _split(body)]


def _hash(texts: list[str]) -> str:
    return hashlib.sha1("\x00".join(texts).encode()).hexdigest()[:16]


def _unit(vec: list[float]) -> array:
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return array("f", (x / n for x in vec))


def _pack(vec: array) -> str:
    return base64.b64encode(vec.tobytes()).decode()


def _unpack(text: str) -> array:
    a = array("f")
    a.frombytes(base64.b64decode(text))
    return a


def load(path: Path | None = None) -> dict:
    """{"model", "updated", "items": {id: {"hash", "vecs": [array]}}}; empty when there's no index yet."""
    global _cache
    path = path or INDEX_PATH
    if not path.exists():
        return {"model": _model(), "updated": None, "items": {}}
    stamp = (str(path), path.stat().st_mtime_ns)
    if _cache[0] != stamp:
        data = decrypt(path.read_bytes())
        data["items"] = {i: {"hash": it["hash"], "vecs": [_unpack(v) for v in it["vecs"]]} for i, it in data["items"].items()}
        _cache = (stamp, data)
    return _cache[1]


def save(data: dict, path: Path | None = None) -> None:
    path = path or INDEX_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    out = {**data, "items": {i: {"hash": it["hash"], "vecs": [_pack(v) for v in it["vecs"]]} for i, it in data["items"].items()}}
    tmp = path.with_suffix(".enc.tmp")
    tmp.write_bytes(encrypt(out))
    tmp.replace(path)  # atomic: a reader (the chat bot) sees the old or the new index, never half of one


def update(emails: list[dict], log=None, embed=None, path: Path | None = None, rebuild: bool = False) -> tuple[int, int]:
    """Embed emails that are new or changed, forget ones no longer saved. Returns (embedded, removed).
    Never raises: the index is a convenience; the next run catches up."""
    from mailbrief import progress

    try:
        if embed is None:
            from mailbrief.ai.client import embed
        data = load(path)
        if rebuild or data.get("model") != _model():
            data = {"model": _model(), "updated": None, "items": {}}
        keep = {e["id"]: e for e in emails if indexable(e)}
        todo = []
        for i, e in keep.items():
            texts = chunks(e)
            if data["items"].get(i, {}).get("hash") != _hash(texts):
                todo.append((i, texts))
        removed = [i for i in data["items"] if i not in keep]
        for i in removed:
            del data["items"][i]
        flat = [t for _, texts in todo for t in texts]
        vecs = []
        for n in range(0, len(flat), 256):  # progress per ~256 chunks; embed() batches further
            vecs += embed(flat[n : n + 256])
            progress.count("Indexing", min(n + 256, len(flat)), len(flat))
        pos = 0
        for i, texts in todo:
            data["items"][i] = {"hash": _hash(texts), "vecs": [_unit(v) for v in vecs[pos : pos + len(texts)]]}
            pos += len(texts)
        if todo or removed or not (path or INDEX_PATH).exists():
            data["updated"] = datetime.now(timezone.utc).isoformat()
            save(data, path)
        return len(todo), len(removed)
    except Exception as e:  # noqa: BLE001
        if log:
            print(f"warning: search index not updated ({type(e).__name__}: {e}); the next run retries", file=log)
        return 0, 0


def status(path: Path | None = None) -> dict:
    path = path or INDEX_PATH
    data = load(path)
    return {"emails": len(data["items"]), "chunks": sum(len(it["vecs"]) for it in data["items"].values()),
            "model": data.get("model"), "updated": data.get("updated"),
            "bytes": path.stat().st_size if path.exists() else 0}


# ── search ──────────────────────────────────────────────────────────────────────────────────────────

def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _bm25(query: list[str], docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    n = len(docs) or 1
    avg = sum(map(len, docs)) / n or 1
    df = {w: sum(w in set(d) for d in docs) for w in set(query)}
    scores = []
    for d in docs:
        tf = {w: d.count(w) for w in set(query)}
        scores.append(sum(math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5)) * tf[w] * (k1 + 1)
                          / (tf[w] + k1 * (1 - b + b * len(d) / avg)) for w in tf if tf[w]))
    return scores


def _labels(email: dict, your_rules: dict) -> set[str]:
    from mailbrief import rules

    c = email.get("classification") or {}
    names = {c.get("category") or ""} | {n.removeprefix("MB: ") for n in rules.effective(email, your_rules)["labels"]}
    return {n.lower() for n in names if n}


def matches(email: dict, plan: dict, your_rules: dict) -> bool:
    """The plan's hard filters (sender, date range, labels), applied in code before any ranking."""
    when = email["received_at"].date()
    who = f"{email.get('sender_name', '')} {email.get('sender_email', '')}".lower()
    if plan.get("sender") and plan["sender"].lower() not in who:
        return False
    if plan.get("after") and when < plan["after"]:
        return False
    if plan.get("before") and when > plan["before"]:
        return False
    if plan.get("labels") and not {x.lower() for x in plan["labels"]} & _labels(email, your_rules):
        return False
    return True


def search(emails: list[dict], plan: dict, k: int = 12, your_rules: dict | None = None, embed=None,
           path: Path | None = None) -> list[dict]:
    """The k best emails for plan["search"] among those passing the plan's filters: meaning (best chunk's cosine)
    and keywords (BM25, best chunk), plus a small nudge for recent mail. Filters that match nothing are dropped
    rather than answering from nothing.
    ponytail: a flat pure-Python scan, ~0.2 s at 1k chunks; numpy, then sqlite-vec, past ~20k chunks."""
    from mailbrief import rules

    your_rules = your_rules or rules.empty()
    pool = [e for e in emails if indexable(e)]
    filtered = [e for e in pool if matches(e, plan, your_rules)]
    if not filtered and (plan.get("sender") or plan.get("labels")):
        filtered = [e for e in pool if matches(e, {**plan, "sender": None, "labels": []}, your_rules)]
    if not filtered:
        return []
    query = plan.get("search") or ""
    items = load(path)["items"]
    meaning = {}
    if query and any(e["id"] in items for e in filtered):
        if embed is None:
            from mailbrief.ai.client import embed
        q = _unit(embed([query])[0])
        for e in filtered:
            vecs = items.get(e["id"], {}).get("vecs") or []
            meaning[e["id"]] = max((sum(map(mul, q, v)) for v in vecs), default=0.0)
    texts = [(e["id"], _words(t)) for e in filtered for t in chunks(e)]
    kw_raw = _bm25(_words(query), [t for _, t in texts]) if query else [0.0] * len(texts)
    best_kw: dict[str, float] = {}
    for (i, _), s in zip(texts, kw_raw):
        best_kw[i] = max(best_kw.get(i, 0.0), s)
    top_kw = max(best_kw.values(), default=0.0) or 1.0
    newest = max(e["received_at"] for e in filtered)

    def score(e: dict) -> float:
        age_days = (newest - e["received_at"]).total_seconds() / 86400
        return MEANING * meaning.get(e["id"], 0.0) + KEYWORDS * best_kw.get(e["id"], 0.0) / top_kw \
            + 0.02 * max(0.0, 1 - age_days / 365)

    return sorted(filtered, key=score, reverse=True)[:k]
