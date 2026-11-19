"""The only place that talks to the LLM: any OpenAI-compatible /chat/completions endpoint."""

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request

from mailbrief import ConfigError

RETRIES = 5  # busy (429) or server errors: backoff 3, 6, 12, 24, 48 s
MAX_WAIT_S = 120  # the longest a Retry-After is obeyed: a run holds the run lock while it waits
# No answer: a timeout, a refused or reset connection, or a reply cut off half way.
NO_ANSWER = (TimeoutError, urllib.error.URLError, ConnectionError, http.client.HTTPException)
TIMEOUT_RETRIES = 2  # no answer at all: a hung endpoint usually stays hung, so give up within minutes
LEGACY_KEY = "SOCLAAS_API_KEY"  # the key's name in the first setup: still read, so that install keeps running


EMBED_BATCH = 64  # measured: 64 texts of ~1k chars in about 2 s


def complete(model: str, messages: list[dict], thinking: bool = False, max_tokens: int = 1500) -> str:
    """Reply text from `model`, with any <think>…</think> block removed."""
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    # This extension is rejected by strict OpenAI-compatible servers; opt in for Qwen/Ollama.
    if os.environ.get("AI_CHAT_TEMPLATE_KWARGS", "off").lower() in ("on", "1", "true"):
        body["chat_template_kwargs"] = {"enable_thinking": thinking}
    # a thinking merge legitimately takes minutes; anything else answers in seconds
    timeout = 300 if thinking else 120
    # Default: your own fast model (the classifier's), so the fallback is always one your endpoint serves.
    fallback = os.environ.get("AI_FALLBACK_MODEL", os.environ.get("AI_CLASSIFIER_MODEL", ""))
    if fallback and fallback != model:
        # The strong model gets one try: on the shared endpoint it sometimes crawls (11 tokens/s measured), and the
        # fast model is better than a run that never finishes.
        try:
            data = _post("/chat/completions", body, timeout=timeout, timeout_retries=0)
        except NO_ANSWER as e:
            if isinstance(e, urllib.error.HTTPError):
                raise
            print(f"AI: {model} didn't answer in {timeout}s; using {fallback} instead", flush=True)
            data = _post("/chat/completions", {**body, "model": fallback}, timeout=timeout)
    else:
        data = _post("/chat/completions", body, timeout=timeout)
    try:
        text = data["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError, AttributeError):  # a 200 that isn't a completion ({"error": …})
        text = ""  # an empty reply: callers already retry or fall back on those
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    """One vector per text (search index, M7), in batches of EMBED_BATCH."""
    model = model or os.environ.get("AI_EMBED_MODEL", "bge-m3")
    out = []
    for n in range(0, len(texts), EMBED_BATCH):
        data = _post("/embeddings", {"model": model, "input": texts[n : n + EMBED_BATCH]})
        out += [d["embedding"] for d in sorted(data["data"], key=lambda d: d.get("index", 0))]
    return out


def settings() -> tuple[str, str]:
    """(endpoint, key) from .env, or ConfigError saying what's missing. Commands call this before they open
    Outlook, so a missing setting shows in a second, not after a minute of reading the inbox."""
    base = (os.environ.get("AI_BASE_URL") or "").strip()
    if not base:  # no built-in default: where your email text goes is your decision, never an assumption
        raise ConfigError("AI_BASE_URL is not set: put your OpenAI-compatible endpoint in .env, "
                          "e.g. AI_BASE_URL=http://localhost:11434/v1 (see .env.example)")
    key = os.environ.get("AI_API_KEY") or os.environ.get(LEGACY_KEY)
    if not key:
        raise ConfigError("AI_API_KEY is not set: put your endpoint's key in .env "
                          "(a local server that needs none still wants any value, e.g. AI_API_KEY=local)")
    return base, key


def _post(path: str, body: dict, timeout: float = 120, timeout_retries: int = TIMEOUT_RETRIES) -> dict:
    """POST JSON to the endpoint, backing off on rate limits (429) and server errors, and retrying a request that
    got no answer only `timeout_retries` times. Every retry is printed, so a stall shows in the log."""
    base, key = settings()
    url = base.rstrip("/") + path
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    busy = hung = 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            # 429 = the shared endpoint's rate limit: back off (honouring Retry-After) and try again.
            if (e.code != 429 and e.code < 500) or busy == RETRIES:
                raise
            retry_after = e.headers.get("Retry-After", "")
            wait = min(MAX_WAIT_S, int(retry_after)) if retry_after.isdigit() else min(60, 3 * 2**busy)
            busy += 1
            print(f"AI: busy ({e.code}), retrying in {wait}s ({busy}/{RETRIES})", flush=True)
        except NO_ANSWER as e:  # HTTPError is caught above
            if hung >= timeout_retries:
                raise
            hung += 1
            wait = 3 * hung
            print(f"AI: no answer from {path} after {timeout:.0f}s ({type(e).__name__}); "
                  f"retrying {hung}/{timeout_retries}", flush=True)
        time.sleep(wait)


def extract_json(text: str) -> dict | None:
    """The JSON object in a model reply, tolerating code fences and stray prose around it."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
