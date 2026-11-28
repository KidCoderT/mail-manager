# Rebuilding MailBrief from scratch

This file is for someone who wants to build the app again from an empty folder, to understand it by making it, or to start a similar project. It gives a build order where each step only needs the steps before it, the minimum interface each module must offer (quoted from the real code), what to test before moving on, and which file explains the module in depth. It doesn't repeat those explanations.

<!-- TOC -->
**Contents**

- [The order, at a glance](#the-order-at-a-glance)
- [Step 1: project set-up](#step-1-project-set-up)
   - [The configuration (`.env.example`)](#the-configuration-envexample)
- [Step 2: storage](#step-2-storage)
- [Step 3: a browser and a saved session](#step-3-a-browser-and-a-saved-session)
- [Step 4: reading Outlook](#step-4-reading-outlook)
- [Step 5: what's new, and threads](#step-5-whats-new-and-threads)
- [Step 6: the AI](#step-6-the-ai)
- [Step 7: the archive](#step-7-the-archive)
- [Step 8: delivery](#step-8-delivery)
- [Step 9: the conductor](#step-9-the-conductor)
- [Step 10: always on](#step-10-always-on)
- [Step 11: the extras](#step-11-the-extras)
- [Exercising the pipeline offline: the demo](#exercising-the-pipeline-offline-the-demo)
<!-- /TOC -->

## The order, at a glance

```
 1  project set-up         pyproject.toml, uv, .env
 2  storage                ConfigError, storage/crypto.py, storage/files.py
 3  browser + session      browser/connect.py, session/manager.py, session/login_once.py
 4  reading Outlook        browser/owa_network.py (pure), progress.py, browser/outlook_reader.py
 5  what's new             cursor.py, threads.py
 6  the AI                 ai/client.py → ai/classifier.py → ai/digest.py
 7  history                archive.py
 8  delivery               notify/telegram.py, notify/__init__.py, destinations.py
 9  the conductor          main.py (run, deliver, build_parser)       ← first useful milestone
10  always on              service.py
11  extras                 rules, labels + outlook_writer, events, links, web_images,
                           index, ai/answer, notify/bot, session/remote_login
```

Each step is runnable on its own. Step 4 is the riskiest (it depends on Outlook's private JSON), so prove it early. Step 9 gives a working morning digest; everything in step 11 is optional.

**Three places where the real code reaches forward.** The order above is the right way to *think* about the layers, but three imports in the current code point to a later step. When you rebuild, either build the small piece early or cut the import:

| Module | Imports | Do this |
|---|---|---|
| `threads.py` (step 5) | `ai.classifier.trim_body` | write `trim_body` first (it's a regex, no AI), or move it into `threads.py` |
| `ai/digest.py` (step 6) | `rules.empty`, `rules.effective` | start `rules.py` with just `empty()` and an `effective()` that returns no labels |
| `browser/outlook_reader.py` (step 4) | `web_images` (inside `collect_images`) | until step 11, return attached images only |

---

## Step 1: project set-up

**What to build.** A package folder `mailbrief/` with an empty `__init__.py`, a `pyproject.toml`, and a `.env` made from `.env.example`.

The real `pyproject.toml`'s working parts:

```toml
requires-python = ">=3.11"
dependencies = [
    "cryptography>=50.0.2",
    "playwright>=1.64.0",
    "python-dotenv>=1.2.4",
    "tzdata>=2026.5",
]

[project.scripts]
mailbrief = "mailbrief.main:main"

[build-system]
requires = ["uv_build>=0.11.19,<0.12.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-root = ""

[dependency-groups]
dev = [
    "mypy>=1.13",
    "pytest>=8",
    "ruff>=0.6",
]
```

**Why each dependency is there, and why there are only four:**
- **`playwright`**: drives a real Chromium. It is the only way in: a work or university account can't use Microsoft Graph without an app registration ([overview](01-overview.md)). It also gives `page.request`, which sends requests with the page's own cookies.
- **`cryptography`**: Fernet, for the session and archive files. Never write your own encryption.
- **`python-dotenv`**: reads `.env` into environment variables. It is about 20 lines of work, but quoting and comments in `.env` files have edge cases it already handles.
- **`tzdata`**: `zoneinfo` needs a time-zone database. Linux and macOS have one; Windows doesn't, so `ZoneInfo("Asia/Singapore")` fails there without this package.
- **Not there:** `requests` or `httpx` (the AI and Telegram calls use the standard library's `urllib`), a database (JSON files), a scheduler library (`service.py` is a plain loop), an AI SDK (the endpoint is OpenAI-compatible JSON over HTTP). Each was left out on purpose; see principle 9 in the [overview](01-overview.md).
- **Dev only:** `pytest`, `ruff` (lint for real mistakes only), `mypy`.

**`module-root = ""`** tells uv's build backend that the package sits at the repository root, not under `src/`. **`[project.scripts]`** makes `mailbrief` a command that calls `mailbrief.main:main`.

**Commands:**

```
uv sync                                         # creates .venv, installs the exact versions in uv.lock
uv run playwright install chromium --no-shell   # the browser itself (once)
cp .env.example .env                            # then fill it in
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Why uv.** One tool creates the virtual environment, installs from a lock file (`uv.lock`, so every machine gets the same versions) and runs commands inside it (`uv run …`). pip + venv + pip-tools can do the same with three tools.

### The configuration (`.env.example`)

Every setting is an environment variable. `.env.example` is the documented template; `.env` (git-ignored) holds your values. Grouped by step:

| Setting | Used from | Meaning |
|---|---|---|
| `SESSION_ENCRYPTION_KEY` | step 2 | Fernet key for `data/session.enc`, the archive and the index. Required |
| `BROWSER_WS_URL` | step 3 | empty = local Chromium; else a CDP browser (Browserless) |
| `DEFAULT_TIMEZONE` | step 5 | where "today" and "this week" are counted (default `Asia/Singapore`) |
| `AI_BASE_URL`, `AI_API_KEY` | step 6 | the OpenAI-compatible endpoint; no default on purpose. The key may be empty for a local server |
| `AI_CLASSIFIER_MODEL`, `AI_VISION_MODEL`, `AI_DIGEST_MODEL`, `AI_FALLBACK_MODEL` | step 6 | model names as your endpoint lists them |
| `AI_CHAT_TEMPLATE_KWARGS` | step 6 | `on` sends Qwen/Ollama's `enable_thinking`; strict servers reject it |
| `ARCHIVE_DAYS` | step 7 | delete month files older than this (0 = keep forever) |
| `TELEGRAM_BOT_TOKEN` | step 8 | from @BotFather |
| `RUN_AT` | step 10 | `"daily 07:30; sun 20:00 this-week"` |
| `OUTLOOK_LABELS`, `REMOTE_IMAGES`, `EVENTS_DAYS`, `CHAT`, `AI_EMBED_MODEL`, `AI_ANSWER_MODEL`, `PUBLIC_URL`, `PORT`, `LOGIN_PAGE`, `LOGIN_TUNNEL` | step 11 | the extras |

**Why environment variables.** The same code runs on your PC (from `.env`) and in a container (from the host's settings) with no config file format to parse. Real environment variables win over `.env`, because `load_dotenv()` doesn't override what is already set.

---

## Step 2: storage

**What to build.** The one exception type every module uses for bad settings, encryption with a key from the environment, and an atomic file replace.

```python
# mailbrief/__init__.py
class ConfigError(Exception):
```

```python
# mailbrief/storage/crypto.py
def check_key() -> None:
    # ...
def encrypt(data: dict) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode())


def decrypt(blob: bytes) -> dict:
    return json.loads(_fernet().decrypt(blob))
```

```python
# mailbrief/storage/files.py
def replace(tmp: Path, path: Path, tries: int = 15, wait: float = 0.2) -> None:
```

**The rule this sets for every later module:** write to `x.tmp`, then `replace(tmp, x)`. A crash never leaves a half-written file.

**Test before moving on.** A round trip (`decrypt(encrypt(d)) == d`), a missing key raising `ConfigError` with the command to make one, and `replace` surviving a file that another handle has open. See `tests/test_files.py`.

**In depth:** [`storage/crypto.py`](02-storage-session-browser.md#storagecryptopy).

---

## Step 3: a browser and a saved session

**What to build.** A function that gives you a browser, a one-time visible login that saves the browser's cookies encrypted, and load/save for that session.

```python
# mailbrief/browser/connect.py
def get_browser(p, headless: bool = True):
```

```python
# mailbrief/session/manager.py
SESSION_PATH = Path("data/session.enc")


def load() -> dict | None:
    """Return {"state": storage_state, "user_agent": str}, or None if never logged in."""
    # ...
def save(context, user_agent: str, account_: str | None = None) -> None:
```

```python
# mailbrief/session/login_once.py
def login_once() -> None:
    from mailbrief.storage.crypto import check_key

    check_key()  # before the browser opens: a bad key would otherwise only show after password and MFA
    with sync_playwright() as p:
        browser = get_browser(p, headless=False)
        context = browser.new_context()
        page = context.new_page()
        # Read before navigating: Outlook keeps redirecting, which destroys the page's JS context.
        user_agent = page.evaluate("navigator.userAgent")
        page.goto(INBOX_URL)
        print("Sign in to Outlook in the browser window (MFA, tick 'Stay signed in').")
        input("When your inbox is visible, press Enter here... ")
        manager.save(context, user_agent)
```

**Test before moving on.** Run the login once by hand. Then, in a script, `manager.load()`, open a *headless* context with `storage_state=session["state"]`, go to Outlook and check you land on the inbox, not on `login.microsoftonline.com`. If that works, the whole app is possible.

**In depth:** [`browser/connect.py`](02-storage-session-browser.md#browserconnectpy), [`session/`](02-storage-session-browser.md#session).

---

## Step 4: reading Outlook

**What to build.** Two layers. `owa_network.py` is **pure**: it only turns Outlook's JSON into Python dicts and builds request bodies, with no browser. `outlook_reader.py` drives the page: open it, listen to its JSON responses, scroll, and replay read-only `GetItem` calls. `progress.py` prints the progress lines both use.

```python
# mailbrief/browser/owa_network.py
def parse_messages(payloads: list) -> list[dict]:
    # ...
def view_total(payloads: list) -> int | None:
    # ...
def getitem_body(header: dict, ids: list[str]) -> dict:
    # ...
def parse_items(response: dict) -> list[dict]:
    # ...
def find_user_email(payloads: list) -> str | None:
    # ...
def preview_records(conversations: list[dict]) -> list[dict]:
    # ...
def check_request(action: str, body: dict) -> None:
```

```python
# mailbrief/browser/outlook_reader.py
def open_outlook(page, timeout_s: int = 60) -> dict:
    # ...
def read_inbox(page, timeout_s: int = 60, max_scrolls: int = 300) -> dict:
    """Open the inbox, load every conversation in Focused and Other, return what Outlook's network calls revealed.

    Returns {"expired", "messages", "total", "urls", "auth", "me"}; "auth" is in-memory replay state for fetch_emails.
    """
    # ...
def fetch_emails(page, auth: dict, conversations: list[dict], me: str | None = None) -> tuple[list[dict], bool]:
    # ...
def collect_images(page, auth: dict, emails: list[dict]) -> dict[str, list[str]]:
    # ...
def _service_call(page, auth: dict, action: str, make_body):
```

```python
# mailbrief/progress.py
def step(msg: str) -> None:
    # ...
def count(label: str, n: int, total: int) -> None:
    # ...
def working(label: str):
```

**Why split pure from browser.** Outlook's JSON is the part that changes and breaks. Keeping the parsing pure means you can save a real response once (with invented content), and test the parser against it in milliseconds, forever, with no account. **Put `check_request` in from the first day**, even before you write anything, and route every `service.svc` call through `_service_call`, which calls it.

The record `parse_items` returns is the **EmailRecord**, the shape every later step reads. It is quoted in full in [the adapting guide](09-adapting.md#the-data-contract).

**Test before moving on.** `tests/test_owa_network.py` (parsers against hand-made JSON). Then, by hand: `read_inbox` reports a `total` equal to the number of conversations it parsed, and `fetch_emails` returns `(records, True)`. Print counts only, never subjects, while you test against your own mailbox.

**In depth:** [`browser/outlook_reader.py`](02-storage-session-browser.md#browseroutlook_readerpy), [`browser/owa_network.py`](02-storage-session-browser.md#browserowa_networkpy).

---

## Step 5: what's new, and threads

**What to build.** The cursor ("how far did we get?") and thread grouping.

```python
# mailbrief/cursor.py
def load() -> dict:
    # ...
def since(cursor: dict, now: datetime | None = None) -> datetime:
    # ...
def select_new(records: list[dict], cursor: dict, retry=frozenset()) -> list[dict]:
    # ...
def advance(cursor: dict, records: list[dict]) -> dict:
    # ...
def save(cursor: dict) -> None:
```

```python
# mailbrief/threads.py
def order(msgs: list[dict]) -> list[dict]:
    # ...
def depth(msg: dict) -> int:
    # ...
def group(msgs: list[dict]) -> dict[str, list[dict]]:
    # ...
def context_lines(email: dict, thread: list[dict]) -> list[str]:
    # ...
def replied(email: dict, thread: list[dict]) -> bool:
```

**The one rule to get right:** `select_new` uses "received at or after the cursor, *and* not in the recent ids", and `advance` refuses preview records. Get either wrong and emails are skipped forever or processed twice.

**Test before moving on.** `tests/test_cursor.py` (same-second emails, retries, refusing previews), `tests/test_threads.py` (order by `ConversationIndex`, falling back to time).

**In depth:** [`cursor.py`](03-ai-pipeline.md#cursorpy), [`threads.py`](03-ai-pipeline.md#threadspy).

---

## Step 6: the AI

**What to build.** One module that talks to the endpoint, then the two passes that use it: classify each email, then write a digest from the classifications only.

```python
# mailbrief/ai/client.py
def complete(model: str, messages: list[dict], thinking: bool = False, max_tokens: int = 1500) -> str:
    # ...
def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    # ...
def settings() -> tuple[str, str]:
    # ...
def extract_json(text: str) -> dict | None:
```

```python
# mailbrief/ai/classifier.py
CATEGORIES = ("Urgent", "Needs Reply", "FYI", "Meetings", "Newsletter", "Low Priority")
# ...
def validate(data: dict | None, topics: tuple[str, ...] = (), received: date | None = None) -> dict | None:
    # ...
def classify(email: dict, images: list[str], context: list[str] | None = None, rules: dict | None = None) -> dict:
```

```python
# mailbrief/ai/digest.py
def refs(emails: list[dict]) -> dict[int, str]:
    # ...
def digest(emails: list[dict], results: list[dict], scope: str = "new", on_part=None,
           your_rules: dict | None = None) -> str:
```

**The contract:** `classify` never raises on bad model output. It returns a validated dict, or an "Unclassified" one. It does raise on network and HTTP errors, and the caller (`run`) decides what those mean.

**Test before moving on.** `tests/test_ai.py` (`extract_json`, `validate`, deadlines that must be real dates, digest batching) and `tests/test_ai_client.py` (backoff and fallback with a fake server). Then one real call: classify an invented email (`From: Dr Ada Reed <ada@example.edu>`, "Can you help on Thursday?") and check you get "Needs Reply". Never test prompts with real mail you'd paste into a log.

**In depth:** [`ai/client.py`](03-ai-pipeline.md#aiclientpy), [`ai/classifier.py`](03-ai-pipeline.md#aiclassifierpy), [`ai/digest.py`](03-ai-pipeline.md#aidigestpy).

---

## Step 7: the archive

**What to build.** Encrypted month files of emails with their classifications, and the digests written each day.

```python
# mailbrief/archive.py
def save(emails: list[dict], results: list[dict], digest: str | None, plain: bool, tz,
         now: datetime | None = None, digest_scope: str = "new", digest_refs: dict | None = None) -> list[Path]:
    # ...
def load(month_list: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    # ...
def in_period(email: dict, name: str, today: date, tz) -> bool:
    # ...
def prune(today: date) -> int:
```

`update_fields(changes)` (between `save` and `load` in the file) is needed later, by labels.

**The two rules:** saving the same email twice replaces it (merge by id), and `received_at` is a `datetime` in memory but an ISO string on disk; `load` converts it back.

**Test before moving on.** `tests/test_archive.py`: round trip, reruns never duplicate, month split, a wrong key gives a clear error.

**In depth:** [`archive.py`](03-ai-pipeline.md#archivepy).

---

## Step 8: delivery

**What to build.** Send text to a Telegram chat, split to fit the 4,096-character limit, and a list of destinations.

```python
# mailbrief/notify/telegram.py
def send(chat_id: str, text: str, html: bool = False, buttons: list | None = None) -> int:
    # ...
def find_chats() -> list[dict]:
```

```python
# mailbrief/notify/__init__.py
# Add a channel: write send_<channel>(target, text) and register it here.
ADAPTERS = {"telegram": telegram.send}
```

```python
# mailbrief/destinations.py
def load() -> list[dict]:
    return json.loads(PATH.read_text()) if PATH.exists() else []


def add(type_: str, target: str, label: str) -> None:
```

**Test before moving on.** `tests/test_telegram.py` (splitting by section, UTF-16 sizing for emoji, the HTML fallback). Then by hand: `mailbrief add-destination telegram` once step 9 exists, or call `send` with your chat id.

**In depth:** [`notify/` and `destinations.py`](04-delivery-and-service.md#notify-and-destinationspy).

---

## Step 9: the conductor

**What to build.** `main.py`: the parser, `run`, and `deliver`. This is where the modules meet, in the order given in [the full run](06-main-and-full-run.md#the-full-run-end-to-end).

```python
# mailbrief/main.py
def run(
    show_all=False,
    as_json=False,
    commit=False,
    send=False,
    plain=False,
    backfill=False,
    digest_scope=None,
    quiet=False,
    as_of=None,
) -> int:
    # ...
def digest_set(scope: str, targets: list[dict], cursor: dict, tz, log, retry=frozenset(), as_of=None) -> list[dict]:
    # ...
def deliver(text: str, log, html: bool = False) -> bool:
    # ...
def main() -> None:
    # ...
def build_parser() -> argparse.ArgumentParser:
```

**A first version can be much smaller.** Read, select new, classify, save, digest, deliver, advance the cursor. That is the core. Labels, the index and the events calendar are each one call inside `run` that you add in step 11. Keep these from the start, though, because they are what makes a daily job safe: the run lock, the cursor last, and "nothing parsed" as a failure rather than a quiet day.

**Test before moving on.** `tests/test_pipeline.py` runs `run()` with every outside part faked (no browser, no network): copy its fixture and you can test your own `run`. Then the real thing: `uv run mailbrief run` (prints, sends nothing, moves nothing), then `uv run mailbrief run --send --commit`.

**In depth:** [`main.py`](06-main-and-full-run.md#mainpy).

---

## Step 10: always on

**What to build.** `serve`: parse a schedule once, check the clock every 30 seconds, run each due slot as a child process, retry, alert, stop cleanly.

```python
# mailbrief/service.py
def parse_schedule(text: str) -> list[dict]:
    # ...
def due_slots(now: datetime, schedule: list[dict], last_done: datetime) -> list[tuple[datetime, str]]:
    # ...
def run_args(scope: str, at: datetime | None = None) -> list[str]:
    # ...
def lock(name: str):
    # ...
def serve(spec: str) -> int:
```

**Why a child process per run.** A hung browser or a crash in a run can't take `serve` down, and a run that takes over 45 minutes can be killed. The child's exit code is the whole interface between them (see [exit codes](06-main-and-full-run.md#exit-codes)).

**Test before moving on.** `tests/test_service.py` (every schedule form, catch-up, clock changes, the lock) and `tests/test_service_retry.py`. Then `mailbrief serve --at "daily HH:MM"` with a time two minutes ahead.

**In depth:** [`service.py`](04-delivery-and-service.md#servicepy).

---

## Step 11: the extras

Each one is independent, and each attaches to `run` or `serve` with a call or two. Build them in any order.

| Module | What it adds | Minimum interface | Tests | In depth |
|---|---|---|---|---|
| `rules.py` | your own labels, priority floors, a profile | `load`, `matches`, `effective`, `empty` | `test_rules.py` | [rules](05-labels-rules-extras.md#rulespy) |
| `labels.py`, `browser/outlook_writer.py` | `MB:` categories in Outlook | `labels.run_step(log)`, `labels.apply(emails)`, `outlook_writer.set_labels(...)` | `test_labels.py` | [labels](05-labels-rules-extras.md#labelspy-and-outlook_writerpy) |
| `events.py` | the UPCOMING EVENTS message, by code | `upcoming(...)`, `render(...)`, `build(today, new_ids, log, html)` | `test_events.py` | [events](05-labels-rules-extras.md#eventspy) |
| `links.py` | ↗ links from `[n]` refs | `to_html(text, refs)`, `plain(text)` | `test_links.py` | [links](05-labels-rules-extras.md#linkspy) |
| `web_images.py` | images linked from newsletters, with SSRF checks | `download(urls, room, budget)`, `allowed(url)` | `test_web_images.py` | [web_images](05-labels-rules-extras.md#web_imagespy) |
| `index.py` | the search index for chat | `update(emails, log)`, `search(emails, plan, k)` | `test_index.py` | [index](03-ai-pipeline.md#indexpy) |
| `ai/answer.py` | answers from your mail, with sources | `ask(question, history, today, emails)` | `test_answer.py` | [answer](03-ai-pipeline.md#aianswerpy) |
| `notify/bot.py` | chat in Telegram | `start(stop)`, `run_foreground()` | `test_bot.py` | [bot](04-delivery-and-service.md#notifybotpy) |
| `session/remote_login.py` | sign in from your phone | `run(say, show_link, ttl)`, `run_cli()` | `test_remote_login.py` | [remote login](02-storage-session-browser.md#sessionremote_loginpy) |

Their real signatures:

```python
# mailbrief/rules.py
def empty() -> dict:
    return {"profile": "", "courses": [], "senders": [], "topics": []}
# ...
def load(path: Path | None = None) -> dict:
    # ...
def matches(email: dict, r: dict) -> list[tuple[str, int | None, bool]]:
    # ...
def effective(email: dict, r: dict) -> dict:
```

```python
# mailbrief/labels.py
def apply(emails: list[dict]) -> str:
    # ...
def run_step(log) -> None:
```

```python
# mailbrief/browser/outlook_writer.py
def set_labels(page, auth: dict, wanted: dict[str, list[str]], label: str = "Labelling in Outlook") -> dict[str, str]:
```

```python
# mailbrief/events.py
def upcoming(emails: list[dict], today: date, window: int, new_ids=(), your_rules: dict | None = None,
             past: int = 0) -> list[dict]:
    # ...
def build(today: date, new_ids=(), log=None, html: bool = False) -> str | None:
```

```python
# mailbrief/links.py
def to_html(text: str, refs: dict) -> str:
    # ...
def plain(text: str) -> str:
```

```python
# mailbrief/web_images.py
def allowed(url: str, resolve=_resolve) -> bool:
    # ...
def download(urls: list[str], room: int, budget: int, fetch=_fetch, check=allowed) -> list[str]:
```

```python
# mailbrief/index.py
def update(emails: list[dict], log=None, embed=None, path: Path | None = None, rebuild: bool = False) -> tuple[int, int]:
    # ...
def search(emails: list[dict], plan: dict, k: int = 12, your_rules: dict | None = None, embed=None,
           path: Path | None = None) -> list[dict]:
```

```python
# mailbrief/ai/answer.py
def ask(question: str, history: list[tuple[str, str]] | None = None, today: date | None = None,
        emails: list[dict] | None = None, your_rules: dict | None = None) -> dict:
```

```python
# mailbrief/notify/bot.py
def start(stop: threading.Event) -> threading.Thread | None:
    # ...
def run_foreground() -> int:
```

```python
# mailbrief/session/remote_login.py
def run(say, show_link, ttl: float = WINDOW_S) -> bool:
    # ...
def run_cli() -> int:
```

Note the injectable parameters: `embed=` in `index`, `fetch=` and `check=` in `web_images`, `resolve=` in `allowed`, and `Bot(api=…, ask=…)`. They exist so the tests can swap the network for a function, with no mocking library. Keep that habit as you build.

---

## Exercising the pipeline offline: the demo

`demo/run.py` saves 15 invented emails (people at `example.edu`, threads, events, one reply from "You") into a temporary archive and runs the real viewer and events code on them. It never opens Outlook, never calls an AI and never touches `data/`.

```
uv sync
uv run python demo/run.py            # the threaded list (show_emails)
uv run python demo/run.py thread     # one whole conversation
uv run python demo/run.py email      # one email, with its thread outline
uv run python demo/run.py events     # the events calendar (events_command)
uv run python demo/run.py digest     # a prewritten digest (not a live AI answer)
uv run python demo/run.py chat       # a prewritten chat exchange
```

How it keeps away from your data:

```python
# demo/run.py::tour
    old_cwd, old_archive = Path.cwd(), archive.ARCHIVE_DIR
    with tempfile.TemporaryDirectory(prefix="mailbrief-demo-") as folder:
        try:
            os.chdir(folder)  # rules and all other relative paths also stay away from the real data/
            archive.ARCHIVE_DIR = Path(folder) / "archive"
            archive.save(emails, [e["classification"] for e in emails], digest, True, timezone.utc, now)
```

Every data path in the app is relative (`Path("data/…")`), so changing directory into a temporary folder moves all of them at once. `ARCHIVE_DIR` is also swapped, in case it was already resolved. The `finally:` block puts both back.

**Use it while rebuilding.** Once steps 2, 5 and 7 exist (storage, threads, archive) and you have `show_emails`, the demo is a full test of the browsing side with no account. Each invented email has the full EmailRecord shape plus a classification, so `sample_emails(now)` is also a ready-made fixture for your own tests. What the demo can't exercise is steps 3, 4, 6 and 8 (Outlook, the AI, Telegram): those need `tests/test_pipeline.py`'s fakes or the real services.

**Try it:** `tests/test_demo.py` checks that every view returns 0 and that no `data/` folder appears.
