"""The only place that talks to the LLM: any OpenAI-compatible /chat/completions endpoint."""

import json
import os
import re
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://soclaas-api.comp.nus.edu.sg/v1"
RETRIES = 5  # busy (429) or server errors: backoff 3, 6, 12, 24, 48 s
TIMEOUT_RETRIES = 2  # no answer at all: a hung endpoint usually stays hung, so give up within minutes


EMBED_BATCH = 64  # measured: 64 texts of ~1k chars in ~2 s on the NUS endpoint


def complete(model: str, messages: list[dict], thinking: bool = False, max_tokens: int = 1500) -> str:
    """Reply text from `model`, with any <think>…</think> block removed."""
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        # Qwen-style switch; servers that don't know it ignore it.
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    # a thinking merge legitimately takes minutes; anything else answers in seconds
    timeout = 300 if thinking else 120
    fallback = os.environ.get("AI_FALLBACK_MODEL", "qwen3.6:35b")
    if fallback and fallback != model:
        # The strong model gets one try: on the shared endpoint it sometimes crawls (11 tokens/s measured), and the
        # fast model is better than a run that never finishes.
        try:
            data = _post("/chat/completions", body, timeout=timeout, timeout_retries=0)
        except (TimeoutError, urllib.error.URLError) as e:
            if isinstance(e, urllib.error.HTTPError):
                raise
            print(f"AI: {model} didn't answer in {timeout}s; using {fallback} instead", flush=True)
            data = _post("/chat/completions", {**body, "model": fallback}, timeout=timeout)
    else:
        data = _post("/chat/completions", body, timeout=timeout)
    text = data["choices"][0]["message"].get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    """One vector per text (search index, M7), in batches of EMBED_BATCH."""
    model = model or os.environ.get("AI_EMBED_MODEL", "bge-m3")
    out = []
    for n in range(0, len(texts), EMBED_BATCH):
        data = _post("/embeddings", {"model": model, "input": texts[n : n + EMBED_BATCH]})
        out += [d["embedding"] for d in sorted(data["data"], key=lambda d: d.get("index", 0))]
    return out


def _post(path: str, body: dict, timeout: float = 120, timeout_retries: int = TIMEOUT_RETRIES) -> dict:
    """POST JSON to the endpoint, backing off on rate limits (429) and server errors, and retrying a request that
    got no answer only `timeout_retries` times. Every retry is printed, so a stall shows in the log."""
    key = os.environ.get("AI_API_KEY") or os.environ.get("SOCLAAS_API_KEY")
    if not key:
        raise SystemExit("No AI key: set AI_API_KEY or SOCLAAS_API_KEY")
    url = os.environ.get("AI_BASE_URL", DEFAULT_BASE_URL).rstrip("/") + path
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
            wait = int(retry_after) if retry_after.isdigit() else min(60, 3 * 2**busy)
            busy += 1
            print(f"AI: busy ({e.code}), retrying in {wait}s ({busy}/{RETRIES})", flush=True)
        except (TimeoutError, urllib.error.URLError) as e:  # HTTPError is caught above
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
