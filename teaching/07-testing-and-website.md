# Testing and the static website

<!-- TOC -->
**Contents**

- [Testing](#testing)
   - [Running the checks](#running-the-checks)
   - [Technique: plain asserts on pure functions](#technique-plain-asserts-on-pure-functions)
   - [Technique: inputs built from the real format](#technique-inputs-built-from-the-real-format)
   - [Technique: a fake for the AI's HTTP layer](#technique-a-fake-for-the-ais-http-layer)
   - [Technique: `monkeypatch` for settings and attributes](#technique-monkeypatch-for-settings-and-attributes)
   - [Technique: `capsys` for what's printed](#technique-capsys-for-whats-printed)
   - [Technique: a scripted fake model](#technique-a-scripted-fake-model)
   - [Technique: a fake embedder with known "meaning"](#technique-a-fake-embedder-with-known-meaning)
   - [Technique: temporary folders instead of `data/`](#technique-temporary-folders-instead-of-data)
   - [Technique: faking the browser and the whole run](#technique-faking-the-browser-and-the-whole-run)
   - [Technique: faking the clock](#technique-faking-the-clock)
   - [Technique: testing the command line without running it](#technique-testing-the-command-line-without-running-it)
   - [What's covered](#whats-covered)
   - [Rebuilding it](#rebuilding-it)
- [Static website and parser coverage](#static-website-and-parser-coverage)
   - [What's in `website/`](#whats-in-website)
   - [The CLI parser as the source of truth](#the-cli-parser-as-the-source-of-truth)
   - [The checker: `scripts/check_website.py`](#the-checker-scriptscheck_websitepy)
   - [The offline demo: `demo/run.py`](#the-offline-demo-demorunpy)
   - [The guide's own checks: `teaching_toc.py` and `test_teaching.py`](#the-guides-own-checks-teaching_tocpy-and-test_teachingpy)
   - [Rebuilding it](#rebuilding-it-1)
   - [Try it](#try-it)
<!-- /TOC -->

## Testing

**Job:** prove that the logic works without Outlook, the AI, Telegram or the internet, so the tests run anywhere in a few seconds, on Windows and Linux.

Each module with real logic has one small test file, `tests/test_<module>.py`. Tests are plain functions named `test_…` that use plain `assert`. pytest runs them, and a few use pytest's built-in fixtures (`monkeypatch`, `capsys`, `tmp_path`). Most files also end with a small `__main__` block, so `uv run python tests/test_cursor.py` runs that file alone and prints `ok`. That shortcut doesn't work for files whose tests take pytest fixtures. `tests/test_ai_client.py` and `tests/test_main.py` crash with `TypeError: … missing 1 required positional argument`, so use pytest for those.

### Running the checks
These are the commands CI runs (`.github/workflows/ci.yml`, on Ubuntu and Windows):

```
uv sync --frozen                            # install exactly what uv.lock says, dev tools included
uv run ruff check mailbrief tests demo scripts
uv run mypy mailbrief
uv run pytest -q
```

Useful variants:

```
uv run pytest -q tests/test_index.py                    # one file
uv run pytest -q -k fallback                            # tests whose name contains "fallback"
uv run python tests/test_cursor.py                      # one file without pytest (prints ok)
uv run python scripts/teaching_toc.py                   # refresh the tables of contents in teaching/
uv run pytest -q tests/test_teaching.py                 # check this guide's quotes, links and contents
```

The tools are configured in `pyproject.toml`:

```toml
[dependency-groups]
dev = [
    "mypy>=1.13",
    "pytest>=8",
    "ruff>=0.6",
]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 140
target-version = "py311"

[tool.ruff.lint]
# Real mistakes only (syntax, undefined and unused names): the code has its own style for the rest.
select = ["E4", "E7", "E9", "F"]
ignore = ["E731", "E741"]  # small lambdas and short loop names are used on purpose
```

- **`dependency-groups.dev`** keeps the test tools out of the installed package. `uv sync` installs them for development; `pip install mailbrief` doesn't.
- **ruff with only `E4`, `E7`, `E9` and `F`**: syntax errors, undefined names, unused imports and variables. These are real bugs. Style rules are off, because reformatting the whole codebase would bury real changes in noise.
- **mypy on `mailbrief/` only**: type checking catches `None` slipping into places that expect a value. Tests are left out, since their fakes are deliberately loose.

**Why pytest, when the files could run alone?** The first versions used plain scripts only. As the suite grew, three things made pytest worth it: one command runs everything, a failure shows the values on both sides of the `assert`, and `monkeypatch` undoes its changes even when a test fails. The plain `assert` style stays, so a test still reads like ordinary Python.

**Why made-up data?** The tests must run without Outlook, the AI or the internet, and they must never contain your mail. They're still realistic: the fake payloads use **the exact key names observed in real responses**. Those were found with read-only "shape probes" that printed key names, never content. An early version of the parser was tested on *guessed* shapes, which is exactly how mistakes slip through. After that, every new format was probed first.

### Technique: plain asserts on pure functions
Most logic is written as functions that take data and return data, with no files or network. Testing them needs nothing but inputs and expected outputs.

```python
# tests/test_cursor.py::test_select_new_and_dedupe
def rec(id, minutes, source="getitem"):
    return {"id": id, "received_at": T0 + timedelta(minutes=minutes), "body_source": source}
# ...
def test_select_new_and_dedupe():
    c = {"last_processed_at": T0.isoformat(), "recent_ids": ["seen"]}
    records = [rec("old", -1), rec("seen", 0), rec("same-second", 0), rec("new", 5)]
    assert [r["id"] for r in cur.select_new(records, c)] == ["same-second", "new"]
```

A tiny builder (`rec`) makes each case one line, so the interesting part, the same-second email, is easy to see. `T0` is a fixed time, so the test gives the same answer every day.

Testing that something *raises* can be done without pytest helpers:

```python
# tests/test_cursor.py::test_advance_refuses_previews
def test_advance_refuses_previews():
    c = {"last_processed_at": None, "recent_ids": []}
    try:
        cur.advance(c, [rec("a", 1), rec("p", 2, source="preview")])
    except ValueError:
        return
    raise AssertionError("advance accepted preview-only records")
```

`pytest.raises(ValueError)` is the shorter form, used in `test_cli_parser.py`. The try/except form also works when the file runs without pytest.

### Technique: inputs built from the real format
When the real data has a precise binary shape, build it the same way instead of inventing strings:

```python
# tests/test_threads.py::idx
ROOT = bytes(range(22))  # real ConversationIndex: 22-byte root, +5 bytes per reply level


def idx(*children: int) -> str:
    return base64.b64encode(ROOT + b"".join(bytes([0, 0, 0, c, 0]) for c in children)).decode()
```

`idx(1, 1)` is "a reply to the first reply", encoded exactly like Exchange does. The ordering test then proves the branch case (Ana answering your reply after Bob answered the original) with keys that have the real shape.

### Technique: a fake for the AI's HTTP layer
`client.py` calls `urllib.request.urlopen`. The test swaps that one function for an object that replays a script of outcomes and records what was asked:

```python
# tests/test_ai_client.py::Fake
class Fake:
    """Stands in for urlopen: replays `outcomes` (an exception to raise, or a dict to answer) and records timeouts."""

    def __init__(self, outcomes):
        self.outcomes, self.timeouts, self.models = list(outcomes), [], []

    def __call__(self, req, timeout):
        self.timeouts.append(timeout)
        self.models.append(json.loads(req.data).get("model"))
        out = self.outcomes.pop(0) if self.outcomes else self.last
        self.last = out
        if isinstance(out, Exception):
            raise out
        return io.BytesIO(json.dumps(out).encode())


def patched(fake, fn, fallback=""):
    real_open, real_sleep = client.urllib.request.urlopen, client.time.sleep
    old = os.environ.get("AI_FALLBACK_MODEL")
    os.environ.setdefault("AI_API_KEY", "test")
    os.environ.setdefault("AI_BASE_URL", "https://ai.example.com/v1")  # never called: urlopen is the fake
    os.environ["AI_FALLBACK_MODEL"] = fallback  # "" = never switch (the plain retry behaviour)
    client.urllib.request.urlopen, client.time.sleep = fake, lambda s: None
    try:
        return fn()
    finally:
        client.urllib.request.urlopen, client.time.sleep = real_open, real_sleep
        os.environ.pop("AI_FALLBACK_MODEL") if old is None else os.environ.__setitem__("AI_FALLBACK_MODEL", old)
```

- **`__call__`** makes an instance callable like a function, so it can stand in for `urlopen` and still remember every call.
- **`io.BytesIO(...)`** is a file-like object in memory. `json.load(r)` in the client can't tell it from a network response. `BytesIO` also supports `with`, which the client uses.
- **`time.sleep` is replaced with `lambda s: None`**, so a test of "five retries with backoff" takes milliseconds, not 93 seconds.
- **`try/finally` restores everything**, even when the test fails, so one test can't break the next.

With the fake in place, each behaviour is a few lines:

```python
# tests/test_ai_client.py::test_slow_model_falls_back_to_the_fast_one
def test_slow_model_falls_back_to_the_fast_one():
    fake = Fake([TimeoutError("timed out"), OK])
    got = patched(fake, lambda: client.complete("slow", [], thinking=True), fallback="fast")
    assert got == "fast answer" and fake.models == ["slow", "fast"] and fake.timeouts == [300, 300]
```

**Why fake `urlopen` rather than `complete`?** Faking at the lowest level tests all of the client's own logic: retries, waits, the fallback, header building and reply parsing. Callers of the client (the classifier, the digest) fake one level higher, at `complete`, because the client is already tested.

### Technique: `monkeypatch` for settings and attributes
`patched` above does by hand what pytest's `monkeypatch` fixture does for you. Newer tests use the fixture:

```python
# tests/test_ai_client.py::test_keyless_endpoint_sends_no_authorization_header
def test_keyless_endpoint_sends_no_authorization_header(monkeypatch):
    monkeypatch.setenv("AI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv(client.LEGACY_KEY, raising=False)

    def urlopen(req, timeout):
        assert not req.has_header("Authorization")
        return io.BytesIO(b'{}')

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    assert client._post("/embeddings", {}) == {}
```

pytest passes a `monkeypatch` object to any test that names it as a parameter. Every `setenv`, `delenv` and `setattr` is undone after the test, pass or fail. `raising=False` means "fine if it wasn't set". The fake `urlopen` makes its assertion *inside* the call, which is the simplest way to check what a function sends.

**Patch where it's looked up.** `client` does `import urllib.request` and calls `urllib.request.urlopen(...)` at call time, so patching the attribute on `client.urllib.request` works. Had it done `from urllib.request import urlopen`, the test would have to patch `client.urlopen` instead. That is the most common monkeypatching mistake.

### Technique: `capsys` for what's printed
```python
# tests/test_ai_client.py::test_retry_messages_leave_json_stdout_clean
def test_retry_messages_leave_json_stdout_clean(capsys):
    fake = Fake([ConnectionResetError("reset"), OK])
    assert patched(fake, lambda: client.complete("m", [])) == "fast answer"
    output = capsys.readouterr()
    assert output.out == "" and "retrying" in output.err
```

`capsys` captures stdout and stderr separately. This test pins down a real fix: retry messages once went to stdout and broke commands that print JSON.

### Technique: a scripted fake model
Higher-level code takes `complete` as given and fakes it with a function that answers by call number:

```python
# tests/test_answer.py::test_ask_pipeline_with_fakes
    prompts = []

    def fake_complete(model, messages, **kw):
        prompts.append(messages[0]["content"])
        if len(prompts) == 1:
            return '{"search": "midterm", "events": false}'
        return "Saturday [1].\nSEND: [1] seating.pdf"

    real_complete = answer.complete
    answer.complete = fake_complete
    import mailbrief.index as index
    real = index.search
    index.search = lambda emails, plan, k, rules: emails
    try:
        r = answer.ask("when is the midterm? send the seating plan", [("hi", "hello")] * 5, date(2026, 10, 26),
                       emails, {"profile": "", "courses": [], "senders": [], "topics": []})
    finally:
        answer.complete, index.search = real_complete, real
    assert r["text"] == "Saturday [1]." and r["refs"] == {1: "id1"} and r["sources"] == [emails[0]]
    assert r["send"] == [(emails[0], emails[0]["attachments"][0])]
    assert '<email n="1"' in prompts[1] and "not instructions" in prompts[1] and 'attachments="seating.pdf"' in prompts[1]
    assert prompts[1].count("User: hi") == answer.HISTORY_TURNS  # history capped
```

The first call is the planner, so it gets JSON. The second is the answer, so it gets text with a ref and a file request. The test then checks both directions: what came out (refs and the verified file) and what went *in* (the prompt has the data tags, the injection warning, the attachment list and only 3 history turns). Recording prompts is how you test prompt construction without a model.

The digest test uses the same trick to check batching. It replaces `_ask` and reads back the JSON each part was given (`tests/test_ai.py::test_digest_batches_keep_threads_together_in_time_order`).

### Technique: a fake embedder with known "meaning"
Real embeddings are opaque, so a test can't predict which email is closest. The fake makes each dimension count one keyword:

```python
# tests/test_index.py::fake_embed
WORDS = ["midterm", "hackathon", "fee", "pizza", "schema", "library"]
# ...
def fake_embed(texts):
    """Deterministic 'meaning': one dimension per keyword, so tests know which email is closest."""
    calls.append(len(texts))
    return [[float(t.lower().count(w)) + 0.01 for w in WORDS] for t in texts]
```

The `+ 0.01` keeps vectors non-zero. `calls` records each batch, so the test can prove that a second `update` with nothing new makes no embedding calls at all.

### Technique: temporary folders instead of `data/`
Anything that writes files is pointed at a fresh temp folder, so a test never touches your real `data/` and never sees another test's files. Three styles appear:

```python
# tests/test_archive.py::fresh
def fresh():
    os.environ["SESSION_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    os.environ.pop("ARCHIVE_DAYS", None)
    archive.ARCHIVE_DIR = Path(tempfile.mkdtemp()) / "archive"
```

`fresh()` gives each archive test a new folder and a new throwaway encryption key. It works because `archive.py` reads the module-level `ARCHIVE_DIR` at call time. That's the reason modules keep their paths as module constants rather than hard-coding them inside functions. The trade-off: `mkdtemp` folders aren't deleted, and the module attribute isn't restored. The OS cleans temp folders eventually, and every archive test calls `fresh()` first.

```python
# tests/test_index.py::test_update_incremental_and_search
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "index.enc"
        calls.clear()
        assert index.update(emails, embed=fake_embed, path=path) == (4, 0)
        assert index.update(emails, embed=fake_embed, path=path) == (0, 0) and len(calls) == 1  # nothing new: no calls
```

`index.py` takes `path=` and `embed=` as parameters, so the test passes them in. Nothing global is patched. `TemporaryDirectory()` deletes the folder when the `with` block ends. Designing functions to accept their dependencies is the cleanest kind of testability. It costs one extra parameter.

```python
# tests/test_demo.py::test_offline_tour_restores_paths_and_never_uses_real_archive
def test_offline_tour_restores_paths_and_never_uses_real_archive(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    real = tmp_path / "data" / "archive"
    monkeypatch.setattr(archive, "ARCHIVE_DIR", real)
    for view in ("emails", "email", "thread", "events", "digest", "chat"):
        assert tour(view) == 0
        assert Path.cwd() == tmp_path and archive.ARCHIVE_DIR == real
        assert not (tmp_path / "data").exists()
    assert "OFFLINE DEMO" in capsys.readouterr().out
```

`tmp_path` is pytest's own temp folder fixture, and `monkeypatch.chdir` changes the working directory for the test only. The test pretends `tmp_path/data/archive` is the "real" archive, runs every demo view, and checks the demo never created it and put the path back afterwards.

### Technique: faking the browser and the whole run
`main.run` drives the browser, the AI, the archive, the cursor and Telegram. To test its safety rules (never advance the cursor after a failure), every one of those is replaced in a pytest fixture:

```python
# tests/test_pipeline.py::pipeline
@pytest.fixture
def pipeline(monkeypatch):
    import playwright.sync_api

    now = datetime.now(timezone.utc)
    # ...
    browser = Mock()
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", lambda: nullcontext(None))
    monkeypatch.setattr(connect, "get_browser", lambda *a, **kw: browser)
    monkeypatch.setattr(client, "settings", lambda: ("https://ai.example.com/v1", "test"))
    # ...
    monkeypatch.setattr(outlook_reader, "read_inbox", lambda page: result)
    monkeypatch.setattr(outlook_reader, "fetch_emails", lambda *args: ([record], True))
    # ...
    save = Mock(return_value=[])
    monkeypatch.setattr(archive, "save", save)
    # ...
    cursor_save = Mock()
    monkeypatch.setattr(cursor, "save", cursor_save)
    monkeypatch.setattr(classifier, "classify", lambda *args: {"category": "FYI", "priority": 3})
    # ...
    deliver = Mock(return_value=True)
    monkeypatch.setattr(main, "deliver", deliver)
    return SimpleNamespace(result=result, record=record, save=save, cursor_save=cursor_save, deliver=deliver, browser=browser)


def test_failed_archive_does_not_advance_cursor(pipeline):
    pipeline.save.side_effect = OSError("disk full")
    assert main.run(commit=True, send=True, quiet=True) == 4
    pipeline.cursor_save.assert_not_called()
    pipeline.deliver.assert_called_once()
    pipeline.browser.close.assert_called_once()
```

- **`@pytest.fixture`** turns a function into a reusable setup. Any test that names `pipeline` as a parameter gets a fresh one, and its `monkeypatch` changes are undone afterwards.
- **`unittest.mock.Mock()`** accepts any call and remembers it. `browser.new_page().goto(...)` all "work" and return more mocks. `assert_called_once()` and `assert_not_called()` check what happened. `side_effect = OSError(...)` makes the mock raise when called.
- **`contextlib.nullcontext(None)`** stands in for `with sync_playwright() as p:`. It's a `with`-able object that does nothing.
- **`SimpleNamespace`** bundles the handles the tests need, with attribute access and no class to write.

The test reads like the rule it protects: when saving fails, the run exits with code 4, the cursor isn't saved, the digest still goes out, and the browser is closed.

**Why `Mock` here and hand-written fakes elsewhere?** A `Mock` is quick when you only care *whether* something was called. A hand-written fake is better when the fake must *behave* (replay errors, answer by keyword), because a misspelt attribute on a `Mock` silently returns another `Mock` instead of failing.

### Technique: faking the clock
`service.py` sleeps and reads the time in a loop. The test subclasses `datetime` so `now()` returns a controlled value, and makes `sleep` advance that value instead of waiting:

```python
# tests/test_service_retry.py::test_retry_does_not_repeat_a_successful_later_slot
    current = [datetime(2026, 11, 19, 8, tzinfo=timezone.utc)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current[0]
# ...
    monkeypatch.setattr(service, "datetime", Clock)
# ...
    monkeypatch.setattr(service.time, "sleep", lambda seconds: current.__setitem__(0, current[0] + timedelta(seconds=30)))
```

`current` is a one-item list so the lambda can change it. A lambda can't assign to an outer variable, but it can call a method on it. Hours of schedule run in milliseconds. Patching `service.datetime` (the name `service` looks up) rather than `datetime.datetime` (which you can't patch, since it's a built-in type) is the "patch where it's looked up" rule again.

### Technique: testing the command line without running it
```python
# tests/test_cli_parser.py::test_build_parser_has_no_setup_side_effects
def test_build_parser_has_no_setup_side_effects(monkeypatch):
    import mailbrief.main as cli

    monkeypatch.setattr(cli, "load_dotenv", lambda: (_ for _ in ()).throw(AssertionError("read .env")))
    parser = build_parser()
    assert parser.prog == "mailbrief"
    assert parser.parse_args(["stop"]).command == "stop"
```

`(_ for _ in ()).throw(...)` is a one-expression way to raise inside a lambda: it makes an empty generator and throws into it. If `build_parser` ever reads `.env`, this test fails. That matters because the website checker imports the parser to read the command list, and it must not load anyone's settings.

### What's covered

| Test file | Proves |
|---|---|
| `test_owa_network` | finding conversations/items anywhere in JSON, dedupe, totals, GetItem records, body cleaning & cap, image filter, global IDs, your address |
| `test_cursor` | 24 h first run, ≥ plus ID dedupe at the same second, failed emails retried past the cursor, keeps 500 IDs, refuses previews |
| `test_ai` | JSON extraction from messy replies, validation (real deadlines, bare-string action items), quote trimming, tags and the rules prompt, events, digest refs, digest batches keep threads together in time order |
| `test_ai_client` | no answer gives up after 2 retries (120 s / 300 s), 429s waited out, retry notes on stderr only, dropped connections retried, `Retry-After` capped, a 200 that isn't a completion is `""`, no endpoint is a clear error, no key = no `Authorization` header, 401 not retried, the thinking extension is opt-in, slow model falls back, refusals don't |
| `test_telegram` | short text = one message; long digest = one message per section with the header on the first and `k/n` tags; oversize sections split on lines with "(cont.)"; nothing lost and order kept; UTF-16 sizing with emoji; hard-cut only for absurd lines; heading detection (yes: "FYI (one line each…)"; no: bullets, normal sentences) |
| `test_archive` | encryption round-trip, plain JSON, merge without duplicates, month split, time-zone sorting, format switch, migration, wrong key, period boundaries incl. a year rollover, pruning, label bookkeeping kept on merge |
| `test_files` | `replace` waits out a file another process has open, and raises if it stays locked; a missing or placeholder key is explained |
| `test_threads` | reply-tree ordering (the "Ana replies to your reply after Bob" case), depth, time fallback, grouping, `replied` only counting later messages, context lines |
| `test_progress` | when piped: timestamped step lines, counters only at 25% steps, `working` start and ✓ lines, ✗ on failure, never a `\r` |
| `test_labels` | label names (and what gets none: sent, other-folder, unclassified, previews); merging keeps your categories and swaps ours; pending/labelled/cleared/gone selection; period and day selection; parsing GetItem/UpdateItem replies incl. "gone"; built requests pass the guard; the guard refuses moves/deletes/sends, an `IsRead` change (as the field or hidden in the item), `SendAndSaveCopy`, empty updates and non-`MB:` category edits; reading the category list from StartupData; your own labels beside the built-ins, floors raising `MB: P<n>`, kept labels from removed rules |
| `test_events` | the 14-day window and today/past edges; undated events only from new emails; sent mail ignored; merging fills gaps and keeps 🆕/⭐; the exact rendered layout (⭐ first, time order, sign-up closed, DATE NOT GIVEN); a long calendar splits per day; `past` keeps the last N days only, `(PAST)` headings, both headers, no sign-up line on past events, past calendars split per day too |
| `test_links` | the Outlook URL format and encoding; `[n]` and `[n][m]` refs become ↗ links, unknown refs vanish, string keys work; text is escaped, so links in email text stay text; `plain` |
| `test_index` | chunking (header fields, quote trimming, size and count caps); incremental updates (no re-embedding, changed and pruned emails); status; hybrid search with a fake embedder; sender, date and label filters; an over-strict sender filter is dropped; rebuild; a failing endpoint never raises; a damaged index is rebuilt and search still answers |
| `test_answer` | plan validation (swapped dates, junk values, fallback); impossible dates never raise; reply parsing (unknown refs removed, only real attachments of known emails, the 3-file cap); HTML and plain rendering; the whole pipeline with a fake model (data tags, history capped) |
| `test_pipeline` | the run with every outside part faked: a failed archive save or a failed delivery keeps the cursor; a bad pruning setting doesn't stop saving; a broken inbox format fails instead of reporting success; previews aren't archived and can't advance the cursor |
| `test_main` | a caught-up digest excludes mail after its slot day; only real classifications are kept; setup failures get one line while bugs keep their traceback |
| `test_cli_parser` | building the parser has no side effects; `--version` from package metadata (and when not installed); values and defaults; required and mutually exclusive arguments fail; a hidden old flag parses but stays out of help |
| `test_bot` | strangers, groups and inactive destinations get nothing (not even button answers); questions reply with links, sources and attachment buttons (no inline logos); buttons fetch and send files, unknown ones say "expired"; `/new`, `/help`, `/sync`, `/label` parsing; a crash is answered politely; the CHAT switch |
| `test_remote_login` | the token works once and becomes a cookie; GET never binds; wrong token/cookie/path → 404; expired → 404; `/frame` only with the cookie; input checks (bounds, length, key allowlist, JSON only); security headers; tap scaling in the page; the run loop applies inputs and stops on sign-in or timeout; https-only addresses |
| `test_web_images` | https and public addresses only (private, loopback, link-local, CGNAT, IPv6, multicast, mixed and unresolvable hosts refused); downloads filtered by type and size, stopped by room, budget and 12 tries; a failing fetch is skipped; redirects never followed; `REMOTE_IMAGES` defaults on |
| `test_rules` | `rules.json` checks (built-in name clashes, duplicates, missing labels/descriptions, bad priorities); whole-word course codes, only the start of the body; sender address/name and direct-only; topic tags, boosts with and without a profile, removed topics; adding replaces, save/load, a broken file raises |
| `test_service` | every `RUN_AT` form parses (daily, weekdays, weekends, day lists, `day-N`, scopes) and bad ones are rejected; due runs: on time, not early, three days off = one catch-up, latest per scope (daily + weekly + monthly), nothing when done; next run across weekends and months; only `new` commits; the lock is exclusive and released |
| `test_service_retry` | a failed slot is retried without repeating a later slot that already succeeded |
| `test_demo` | the invented mailbox has a 3-message thread and upcoming events; every demo view runs, restores the working directory and archive path, and never creates `data/` |
| `test_teaching` | every quoted block in `teaching/` still matches its source, relative links resolve, and each table of contents is current |

**Real-world checks** were also done against the real inbox during development:
- unread emails stayed unread;
- all 344 conversations captured;
- backfill interrupted and resumed;
- a rerun made 0 AI calls;
- a thread with your forward was shown correctly;
- `run --all` dropped from 15+ silent minutes to 58 s with live progress;
- a redirected log had no `\r` redraws;
- a `this-month` digest of 149 emails ran in 6 parallel parts and produced STILL OPEN / DEADLINES / KEY EVENTS / NOISE;
- **the service:**
  - `serve` fired on time, delivered to Telegram and logged no subjects;
  - a manual `run` and a second `serve` were refused while it ran;
  - `mailbrief stop` during a run let it finish, then stopped;
  - `autostart on` + `schtasks /Run` started it hidden and caught up a missed 07:30 slot;
  - `stop` and `autostart off` cleaned up;
  - a simulated Ctrl+C stopped an idle service at once;
- **labels:** the trials listed in [labels](05-labels-rules-extras.md), including an unread email staying unread and a full clear-and-restore of 360 emails.

### Rebuilding it
Start with the pure functions: cursor selection, thread ordering, validation, chunking. They need only `assert`. Then make every outside dependency replaceable in one of three ways, best first:
1. **A parameter** (`embed=`, `path=`, `now=`): no patching needed.
2. **A module attribute read at call time** (`archive.ARCHIVE_DIR`, `client.urllib.request.urlopen`): patch it with `monkeypatch.setattr`.
3. **A whole-run fixture with `Mock`s**, for the orchestration code that only wires parts together.

For your own project, the rule that kept these tests honest is the shape probe: before faking a payload, print the key names of a real one (never the values), and copy those names into the fake.

---

## Static website and parser coverage

**Job:** a public, static website that explains MailBrief and documents every command, and a checker that fails when the site and the real CLI disagree.

### What's in `website/`
```
website/index.html   introduction, a Telegram-style digest preview, a terminal you can type into
website/setup.html   install through the first digest
website/docs.html    every command and flag, Telegram commands, configuration, privacy
website/style.css    one stylesheet;  website/site.js  one script;  website/assets/  images
```

It needs no build step and no server: open `index.html` from disk, or let GitHub Pages serve the folder. The "terminal" matches what you type against prewritten responses. It can't run commands, and the page's Content-Security-Policy forbids network connections, so it can't leak anything either. Without JavaScript the pages and the sample digest still read fine. Only the prompt and buttons are hidden.

**Why hand-written HTML instead of a site generator?** Three pages don't need a toolchain. A generator would add a build step to CI and a dependency to keep updated. The cost is some repeated header and footer markup across the three pages. The checker enforces that they stay consistent.

`site.js` keeps one usage line per real command in a list called `MAN`, which powers `man <command>` in the fake terminal. Opening any page with `#selftest` at the end of the URL runs the script's own assertions in the browser console.

### The CLI parser as the source of truth
`mailbrief/main.py` splits building the parser from running it:

```python
# mailbrief/main.py::build_parser
def build_parser() -> argparse.ArgumentParser:
    """The CLI parser, without reading .env, touching streams, or running a command."""
```

```python
# mailbrief/main.py::_main
def _main() -> None:
    load_dotenv()
    # ...
    parser = build_parser()
    args = parser.parse_args()
```

`_main` loads `.env`, fixes the console encoding and then parses. `build_parser` only builds. So the checker can import the parser and list every command and flag without reading anyone's settings (`test_build_parser_has_no_setup_side_effects` guards this).

### The checker: `scripts/check_website.py`
```
check(folder = website/):
    missing folder or pages → stop with a clear message
    static checks (parse the HTML with the stdlib):
        one h1 per page, shared header/footer, no duplicate ids, no external assets,
        every local link and #anchor exists, tables wrapped, palette and font stacks in the CSS,
        no network APIs in site.js
        for every command path in the REAL parser:
            docs.html has #cmd-<path>, that section shows the command and mentions every public flag,
            site.js's MAN list has an entry for it
        every Telegram command is mentioned somewhere
    browser checks (headless Chromium via Playwright, file:// URLs):
        three viewport widths: no sideways scroll, no network requests, no JavaScript errors
        dark by default, with and without JavaScript; themes; the terminal and its history;
        the tour can be cancelled; XSS input stays text; reduced motion; the docs filter and copy buttons
```

The parser walk reads `argparse`'s internals to list commands and flags:

```python
# scripts/check_website.py::parser_commands
    def walk(parser, path):
        public = []
        for action in parser._actions:
            if isinstance(action, argparse._HelpAction):
                continue
            if isinstance(action, argparse._SubParsersAction):
                continue
            if not action.option_strings:
                continue
            if action.help is argparse.SUPPRESS:
                private.update(action.option_strings)
            else:
                public.extend(action.option_strings)
        commands.append((path, public))
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    walk(child, path + [name])

    walk(build_parser(), [])
    return commands, private
```

- **`parser._actions`** is every argument the parser knows. `option_strings` is empty for positional arguments and holds `["--send"]` and the like for flags.
- **`help=argparse.SUPPRESS`** marks a hidden flag (such as the old `--no-password`). Hidden flags are collected as private and aren't required in the docs.
- **`_SubParsersAction.choices`** maps each subcommand name to its own parser, so the walk recurses into `labels apply`, `rules add` and so on.

The underscore names are private API. They've been stable in `argparse` for over a decade, and the alternative (parsing `--help` text) is far more fragile. If a Python release changes them, this script breaks loudly, not silently.

Then each command is matched against the docs:

```python
# scripts/check_website.py::static_checks
    commands, _private = parser_commands()
    for path, flags in commands:
        ident = "cmd-global" if not path else "cmd-" + "-".join(path)
        label = "mailbrief" + (" " + " ".join(path) if path else "")
        assert ident in anchors, f"docs: #{ident} is missing (for {label})"
        node = anchors[ident]
        if node.tag in ("section", "article"):
            assert "doc-section" in node.classes, f"docs.html: #{ident} section is not a .doc-section"
        body = command_text(node)
        if path:
            assert phrase(label).search(body), f"docs: #{ident} does not show `{label}`"
        for flag in flags:
            assert flag_pattern(flag).search(body), f"docs: #{ident} does not mention {flag}"
        if path:  # the terminal's own man pages (the MAN list in site.js)
            assert f"['{' '.join(path)}'," in js, f"site.js: MAN has no entry for `{label}`"
```

```python
# scripts/check_website.py::flag_pattern
def phrase(command):
    return re.compile(r"(?<![\w-])" + r"\s+".join(map(re.escape, command.split())) + r"(?![\w-])", re.I)


def flag_pattern(flag):
    return re.compile(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])")
```

`(?<![\w-])` and `(?![\w-])` are lookarounds: "not preceded / followed by a letter, digit, `_` or `-`". So `--send` doesn't count as mentioned just because `--send-test` is. `re.escape` makes `--days` safe inside a pattern. `\s+` between words lets `mailbrief labels apply` wrap across lines in the HTML.

The HTML is parsed with the standard library's `html.parser.HTMLParser` into a small tree (the `Tree` class). It's tolerant of unclosed tags and needs no BeautifulSoup. The browser half uses Playwright, which the app already depends on for Outlook:

```python
# scripts/check_website.py::browser_checks
            for width, height in ((320, 900), (390, 844), (1280, 800)):
                ctx = context(viewport={"width": width, "height": height}, color_scheme="light")
                for name in PAGES:
                    page = ctx.new_page()
                    requests = external_requests(page)
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(urls[name])
                    assert page.locator("body").evaluate("e => e.scrollWidth <= innerWidth + 1"), (name, width)
                    assert not requests, f"{name}: network requests {requests}"
                    assert not errors, f"{name}: JavaScript errors {errors}"
                    page.close()
                ctx.close()
```

`page.on("request", ...)` (inside `external_requests`) and `page.on("pageerror", ...)` collect events while the page loads. `scrollWidth <= innerWidth + 1` is the check for "no sideways scrolling on a 320-pixel phone", with 1 pixel allowed for rounding.

Run it:

```
uv sync --frozen
uv run playwright install chromium --no-shell     # once; CI adds --with-deps on Linux
uv run python scripts/check_website.py            # or: ... check_website.py path/to/site
```

`.github/workflows/pages.yml` runs the same checker before uploading `website/` to GitHub Pages, on every push to `main` that touches `website/`, `mailbrief/`, the checker or `uv.lock`. A new command without docs blocks the deploy.

**Why check the docs against the parser?** Docs drift. A flag gets renamed, and the website keeps showing the old one for months. Generating docs from the parser would fix that too, but would lose the hand-written explanations. Checking keeps the prose and catches the drift.

### The offline demo: `demo/run.py`
```
tour(view):
    make 15 invented emails (example.edu senders, dates relative to now, one 3-message thread, events)
    in a temporary folder: chdir there, point the archive at it, save the emails and a prewritten digest
    show the chosen view with the REAL commands (emails, email, thread, events) or print the prewritten one (digest, chat)
    always: chdir back and restore the archive path
```

```python
# demo/run.py::tour
    old_cwd, old_archive = Path.cwd(), archive.ARCHIVE_DIR
    with tempfile.TemporaryDirectory(prefix="mailbrief-demo-") as folder:
        try:
            os.chdir(folder)  # rules and all other relative paths also stay away from the real data/
            archive.ARCHIVE_DIR = Path(folder) / "archive"
            archive.save(emails, [e["classification"] for e in emails], digest, True, timezone.utc, now)
            print("OFFLINE DEMO — invented mail; no Outlook, Telegram, AI, or real data used.\n")
            if view == "events":
                return events_command(14, False)
            # ...
        finally:
            os.chdir(old_cwd)
            archive.ARCHIVE_DIR = old_archive
```

Run it:

```
uv run python demo/run.py                 # the email list
uv run python demo/run.py thread          # also: email, events, digest, chat
```

- **The archive is saved with `plain=True`** (the `True` argument), so the demo needs no encryption key.
- **`os.chdir(folder)`** matters as much as the archive path. `rules.json`, the cursor and the index all use relative `data/` paths, so changing directory keeps every one of them away from your real data.
- **The digest and chat are prewritten and say so.** The demo must work with no AI endpoint, and it must never pretend to be a live AI answer.
- **`finally`** restores the directory and path even if a view fails. `test_demo.py` checks exactly that.

### The guide's own checks: `teaching_toc.py` and `test_teaching.py`
This guide quotes real code, so it has tests too. The quote check:

Two regular expressions find the quotes. `FENCE` matches a python fence whose first line is `# ` plus a path under `mailbrief/`, `tests/`, `scripts/` or `demo/` ending in `.py`, and captures the path and the body. `ELIDE` matches a line that is only `# ...`. The check itself:

```python
# tests/test_teaching.py::test_quoted_code_matches_the_source
def test_quoted_code_matches_the_source():
    stale = []
    for doc in _docs():
        for path, body in FENCE.findall(doc.read_text(encoding="utf-8")):
            source = (ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n")
            at = 0
            for piece in ELIDE.split(body):
                piece = piece.strip("\n")
                if not piece:
                    continue
                found = source.find(piece, at)
                if found < 0:
                    stale.append(f"{doc.name}: {path}: {piece.splitlines()[0][:70]!r}")
                    break
                at = found + len(piece)
    assert not stale, "quotes no longer match the code:\n" + "\n".join(stale)
```

```
for each ```python block whose first line is "# <path>.py…":
    split the block at lines that are only "# ..."
    each piece must appear in the source file, exactly, AFTER the previous piece
```

- **`source.find(piece, at)`** searches from position `at`, so pieces must appear in order. A quote can skip code but can't reorder it.
- **`.replace("\r\n", "\n")`** makes the check work on Windows checkouts with CRLF line endings.
- **Only blocks that start with a path comment are checked.** Pseudocode uses plain fences and is free text.
- **The match is exact, indentation included.** Reformatting a quoted function fails the test. That's the point: the guide can't silently drift from the code.

The contents lists are generated, not hand-written:

```python
# scripts/teaching_toc.py::toc
def anchor(heading: str) -> str:
    # GitHub: lowercase, drop everything but letters, digits, spaces, hyphens and underscores; spaces -> hyphens
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def toc(text: str) -> str:
    lines, seen, fenced = [], {}, False
    for line in text.splitlines():
        # ...
        m = None if fenced else re.match(r"^(##|###) (.+)$", line)
        if not m:
            continue
        a = anchor(m.group(2))
        n = seen.get(a, 0)
        seen[a] = n + 1
        indent = "   " if m.group(1) == "###" else ""
        lines.append(f"{indent}- [{m.group(2).strip()}](#{a}{f'-{n}' if n else ''})")
    return "<!-- TOC -->\n**Contents**\n\n" + "\n".join(lines) + "\n<!-- /TOC -->"
```

- **`fenced`** flips at every line that starts a code fence (the two lines left out above), so a `# comment` inside a Python block is never mistaken for a heading.
- **`seen`** counts repeated headings. GitHub gives the second "Try it" the anchor `#try-it-1`, and this matches it.
- **`render`** (not shown) replaces the `<!-- TOC --> … <!-- /TOC -->` block, and the test fails if running it would change a file.

Run `uv run python scripts/teaching_toc.py`, then `uv run pytest -q tests/test_teaching.py`.

### Rebuilding it
For a static site for your own CLI:
- Keep `build_parser()` separate from `main()`, with no side effects. That one design choice makes every docs check possible.
- Give each command a stable anchor (`#cmd-<path>`) and have a script walk the parser and assert each anchor exists and mentions each public flag.
- Load the pages over `file://` in Playwright and assert "no network requests, no JS errors, no sideways scroll" at a phone width. Those three checks catch most regressions.
- For docs that quote code, use the `FENCE`/`ELIDE` test above as is. It's about 20 lines.

### Try it
`uv run python scripts/check_website.py` (needs Chromium from `uv run playwright install chromium --no-shell`), `uv run python demo/run.py events`, `uv run pytest -q tests/test_cli_parser.py tests/test_demo.py tests/test_teaching.py`.
