"""The only place that talks to the LLM: any OpenAI-compatible /chat/completions endpoint."""

import json
import os
import re
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://soclaas-api.comp.nus.edu.sg/v1"
RETRIES = 5  # backoff 3, 6, 12, 24, 48 s


def complete(model: str, messages: list[dict], thinking: bool = False, max_tokens: int = 1500) -> str:
    """Reply text from `model`, with any <think>…</think> block removed."""
    key = os.environ.get("AI_API_KEY") or os.environ.get("SOCLAAS_API_KEY")
    if not key:
        raise SystemExit("No AI key: set AI_API_KEY or SOCLAAS_API_KEY")
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        # Qwen-style switch; servers that don't know it ignore it.
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    url = os.environ.get("AI_BASE_URL", DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(RETRIES + 1):
        wait = min(60, 3 * 2**attempt)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            break
        except urllib.error.HTTPError as e:
            # 429 = the shared endpoint's rate limit: back off (honouring Retry-After) and try again.
            if (e.code != 429 and e.code < 500) or attempt == RETRIES:
                raise
            retry_after = e.headers.get("Retry-After", "")
            wait = int(retry_after) if retry_after.isdigit() else wait
        except (TimeoutError, urllib.error.URLError):
            if attempt == RETRIES:
                raise
        time.sleep(wait)
    text = data["choices"][0]["message"].get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


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
