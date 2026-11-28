# Storage, sessions and reading Outlook

<!-- TOC -->
**Contents**

- [`browser/connect.py`](#browserconnectpy)
   - [How it works and why it's written this way](#how-it-works-and-why-its-written-this-way)
   - [Rebuilding it](#rebuilding-it)
   - [Try it](#try-it)
- [`storage/crypto.py`](#storagecryptopy)
   - [How it works and why it's written this way](#how-it-works-and-why-its-written-this-way-1)
   - [Rebuilding it](#rebuilding-it-1)
   - [Try it](#try-it-1)
- [`storage/files.py`](#storagefilespy)
   - [How it works and why it's written this way](#how-it-works-and-why-its-written-this-way-2)
   - [Rebuilding it](#rebuilding-it-2)
   - [Try it](#try-it-2)
- [`session/`](#session)
   - [`manager.py`](#managerpy)
   - [`login_once.py`](#login_oncepy)
   - [Rebuilding it](#rebuilding-it-3)
   - [Try it](#try-it-3)
- [`browser/outlook_reader.py`](#browseroutlook_readerpy)
   - [The listeners](#the-listeners)
   - [`open_outlook(page)`: open and wait until signed in](#open_outlookpage-open-and-wait-until-signed-in)
   - [`read_inbox(page)`: the main routine](#read_inboxpage-the-main-routine)
   - [`_load_view(view)`: scrolling until complete](#_load_viewview-scrolling-until-complete)
   - [`fetch_emails(page, auth, conversations, me)`](#fetch_emailspage-auth-conversations-me)
   - [`fetch_images(page, auth, email)` and `fetch_attachment(page, auth, id)`](#fetch_imagespage-auth-email-and-fetch_attachmentpage-auth-id)
   - [`fetch_image_urls(page, auth, emails)` and `collect_images(page, auth, emails)`](#fetch_image_urlspage-auth-emails-and-collect_imagespage-auth-emails)
   - [`_service_call(page, auth, action, make_body)`](#_service_callpage-auth-action-make_body)
   - [Rebuilding it](#rebuilding-it-4)
   - [Try it](#try-it-4)
- [`browser/owa_network.py`](#browserowa_networkpy)
   - [Finding messages in any JSON: `_walk` and `_to_message`](#finding-messages-in-any-json-_walk-and-_to_message)
   - [`parse_messages(payloads)`](#parse_messagespayloads)
   - [`view_total(payloads)`](#view_totalpayloads)
   - [`getitem_body(header, ids)`](#getitem_bodyheader-ids)
   - [`parse_items(response)` → EmailRecords](#parse_itemsresponse--emailrecords)
   - [`image_attachments(attachments)`](#image_attachmentsattachments)
   - [`image_urls(html)`](#image_urlshtml)
   - [`preview_records(conversations)`](#preview_recordsconversations)
   - [`find_user_email(payloads)`](#find_user_emailpayloads)
   - [Categories and the write guard](#categories-and-the-write-guard)
   - [Rebuilding it](#rebuilding-it-5)
   - [Try it](#try-it-5)
- [`session/remote_login.py`](#sessionremote_loginpy)
   - [The window: token, cookie, state](#the-window-token-cookie-state)
   - [Checking every input](#checking-every-input)
   - [The web server](#the-web-server)
   - [Driving the browser](#driving-the-browser)
   - [Check, then save](#check-then-save)
   - [Hosting variations](#hosting-variations)
   - [Rebuilding it](#rebuilding-it-6)
   - [Try it](#try-it-6)
<!-- /TOC -->

This chapter covers the bottom layer: how MailBrief gets a browser, keeps secrets on disk, stays signed in, and reads Outlook without clicking anything. Read it in order. Each module only uses the ones before it.

## `browser/connect.py`
**Job:** hand back a browser.

```
function get_browser(playwright, headless):
    if BROWSER_WS_URL is set:
        connect to that remote browser (Browserless / any Chrome DevTools endpoint)
    else:
        launch the local full Chromium, visible or invisible
```

```python
# mailbrief/browser/connect.py::get_browser
import os


def get_browser(p, headless: bool = True):
    """Local Chromium by default; a Browserless (or any CDP) browser if BROWSER_WS_URL is set."""
    ws_url = os.environ.get("BROWSER_WS_URL")
    if ws_url:
        return p.chromium.connect_over_cdp(ws_url)
    # Full Chromium build for both login and runs, so the session sees the same browser.
    return p.chromium.launch(channel="chromium", headless=headless)
```

### How it works and why it's written this way
- **`p` is the Playwright object** you get from `with sync_playwright() as p:`. The caller owns that `with` block, so the caller also decides when everything shuts down. `get_browser` only picks *which* browser.
- **`connect_over_cdp(ws_url)`** attaches to a Chromium that is already running somewhere else, over the Chrome DevTools Protocol (a WebSocket). Browserless and `chrome --remote-debugging-port` both speak it. `headless` is ignored on this path: the remote browser was started with its own setting.
- **`launch(channel="chromium", headless=...)`** starts a local Chromium. Without `channel="chromium"`, recent Playwright versions run headless mode with a separate, slimmer build (the "headless shell"). Login happens in a visible browser and the daily runs are invisible. Asking for the full build both times means Microsoft sees the same browser, so the session is less likely to be challenged. The cost is a bigger download and a little more memory per run.
- **Why so small?** It's the single switch between "browser on my PC" and "browser in a Docker container or the cloud". Everything else asks this function for a browser (`main.run`, `labels`, `login_once`, `remote_login`), so moving the browser means changing one setting, not the code.
- **Why an environment variable and not a parameter?** Every caller would otherwise need to pass it through. A setting that changes per machine, not per call, belongs in `.env`.

### Rebuilding it
Input: a Playwright handle and a headless flag. Output: a `Browser`. It depends on nothing else in MailBrief. To use Firefox, change `p.chromium` to `p.firefox` (and drop `channel`). Note that `connect_over_cdp` is Chromium-only. If you only ever run locally, you could inline `p.chromium.launch(...)` and skip this file. It is kept because there are four callers.

### Try it
No test of its own: it needs a real browser. `tests/test_pipeline.py` replaces it (`monkeypatch.setattr(connect, "get_browser", …)`), which shows the seam it gives you.

---

## `storage/crypto.py`
**Job:** turn a Python dictionary into unreadable bytes and back.

```
function _fernet():   key ← SESSION_ENCRYPTION_KEY
                      missing or malformed → ConfigError that says how to make one
function check_key(): _fernet()                      ← fail early, before anything is spent
function encrypt(dictionary):  return Fernet(key).encrypt(JSON text)
function decrypt(bytes):       return JSON parse of Fernet(key).decrypt(bytes)
```

```python
# mailbrief/storage/crypto.py
import json
import os

from cryptography.fernet import Fernet

from mailbrief import ConfigError


MAKE_KEY = 'uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'


def _fernet() -> Fernet:
    key = (os.environ.get("SESSION_ENCRYPTION_KEY") or "").strip()
    if not key:
        raise ConfigError(f"SESSION_ENCRYPTION_KEY is not set. Make one and put it in .env:\n  {MAKE_KEY}")
    try:
        return Fernet(key)
    except ValueError:  # not 32 url-safe base64 bytes: a placeholder ("...") or a mangled paste
        raise ConfigError(f"SESSION_ENCRYPTION_KEY in .env isn't a valid key. Make one and paste it in whole:\n  {MAKE_KEY}") from None


def check_key() -> None:
    """Raise ConfigError now if the key is missing or malformed (before a sign-in is spent on it)."""
    _fernet()


def encrypt(data: dict) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode())


def decrypt(blob: bytes) -> dict:
    return json.loads(_fernet().decrypt(blob))
```

### How it works and why it's written this way
- **Why Fernet?** It's the standard, hard-to-misuse recipe in the `cryptography` library: AES-128 encryption plus an HMAC-SHA256 tamper check, with a random IV each time. You don't choose a mode, a padding or an IV, so you can't choose them wrong. A wrong key or a corrupted file fails loudly (`cryptography.fernet.InvalidToken`) instead of returning garbage. Rolling your own with raw AES is the alternative that loses: it is easy to forget the tamper check, and then a flipped bit silently becomes a wrong cookie.
- **The key** is 32 random bytes written as url-safe base64 (44 characters). `Fernet(key)` raises `ValueError` if it isn't exactly that. A base64 decoding error (`binascii.Error`) is a subclass of `ValueError`, so one `except` covers both "not base64" and "wrong length".
- **`.strip()`** removes the stray space or newline a copy-paste into `.env` often adds. `or ""` turns a missing variable (`None`) into an empty string, so one `if not key` covers both cases.
- **`raise ... from None`** drops the chained "During handling of the above exception…" traceback. The user sees one clear sentence with the command to fix it, not a stack of `binascii` internals.
- **`ConfigError`, not `SystemExit`.** This code also runs inside the chat bot's thread. A `SystemExit` there would end that thread silently. `main()` turns `ConfigError` into one line for you (`mailbrief/__init__.py` explains this).
- **`check_key()`** exists only to fail early. `login_once` calls it before the browser opens: otherwise a bad key would only show up after you had typed your password and done MFA.
- **`json.dumps(data).encode()`** turns the dict into UTF-8 bytes, which is what Fernet encrypts. `json.loads` accepts bytes directly, so `decrypt` needs no `.decode()`. Anything you encrypt must be JSON-friendly: a `datetime` would make `json.dumps` raise `TypeError`. That is why `archive.save` converts `received_at` to ISO text first.
- **The key is read on every call**, not once at import. It is cheap, and it means a test or `.env` reload that changes the variable takes effect straight away.

**Why one key in `.env`, not a password?** The morning job runs unattended; nobody is there to type a password. The key protects **copies** of `data/` (cloud sync, backups, a zip you send someone, an accidental commit). It doesn't protect against someone logged into your Windows account, because they have `.env` too. That trade-off was chosen on purpose (see the security model in [main.py and the full run](06-main-and-full-run.md)).

**Trade-offs to know.** The whole file is one token, so changing one email means re-encrypting its whole month file. That is fine at a few MB a month. There is no key rotation: change the key and old files raise `InvalidToken`. `cryptography`'s `MultiFernet` (decrypt with any of several keys, encrypt with the first) is the upgrade if you ever need it. A Fernet token is base64, about a third bigger than the data.

### Rebuilding it
Input: a dict (or bytes). Output: bytes (or a dict). It depends on one environment variable and the `cryptography` package. To encrypt something other than JSON, drop the `json` calls and pass bytes straight through. Generate a key once with the `MAKE_KEY` command, and keep it somewhere other than the data it protects.

### Try it
`tests/test_files.py::test_a_missing_or_placeholder_key_is_explained` (empty, `...` and a junk key all give the "how to make one" message). `tests/test_archive.py::test_encrypted_roundtrip_monthly` and `::test_wrong_key_is_a_clear_error` show `encrypt`/`decrypt` in use.

---

## `storage/files.py`
**Job:** replace a file with a new version in one step, even on Windows.

```
function replace(tmp, path, tries=15, wait=0.2s):
    repeat up to `tries` times:
        os.replace(tmp, path)          ← one atomic step: the old file or the new, never half
        done
        if Windows says the file is in use (PermissionError):
            last try → raise it
            else wait 0.2 s and try again
```

```python
# mailbrief/storage/files.py::replace
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
```

### How it works and why it's written this way
- **The pattern it serves:** write the new content to `x.tmp` next to the real file, then `replace(x.tmp, x)`. If the program crashes mid-write, only the `.tmp` is broken; the real file is still the old good one. `session/manager.py`, `cursor.py` and `archive.py` all save this way.
- **`os.replace`** renames `tmp` over `path`, overwriting it. On Linux and macOS this is one atomic step. On Windows it maps to `MoveFileEx` with "replace existing", which is atomic enough for this purpose. `os.rename` is the alternative that loses: on Windows it refuses to overwrite an existing file. The two files must be on the same disk, which is why `tmp` always sits next to `path`.
- **Why the retry?** On Windows, a file another process has open can't be replaced. `mailbrief emails`, the chat bot, an antivirus scan or the search indexer reading a month file is enough, and a save fails with `PermissionError` ("Access is denied"). Those readers hold the file for milliseconds, so 15 tries 0.2 s apart (about 3 s) gets through. After that, something really holds the file, and the error is raised, not hidden.
- **Only `PermissionError` is retried.** A full disk or a missing folder is a real error and is raised straight away.
- **What it doesn't do: `fsync`.** On a power cut (not a crash), some filesystems can lose the last write and leave the new file empty. Calling `os.fsync` on the `.tmp` before the rename would close that gap, at the cost of a slower save. For a personal tool on a laptop it was left out. Add it if you run this on hardware that loses power.

### Rebuilding it
Input: two paths in the same folder. Output: nothing; afterwards `path` holds what `tmp` held. Stdlib only. On Linux only, plain `os.replace` would do. You'd still want the retry if anyone might run it on Windows.

### Try it
`tests/test_files.py::test_replace_waits_out_a_file_another_process_has_open` fakes a locked file twice, then a file that stays locked (which must raise).

---

## `session/`
**Job:** log in once by hand, then reuse that login invisibly every day.

### `manager.py`
```
SESSION_PATH = data/session.enc
function load():     if session.enc exists → decrypt it, else → nothing (not logged in)
function account():  the address recorded with the session, or nothing; never fails
function save(browser_context, user_agent, account?):
    who  ← the account given, or the one already recorded
    blob ← encrypt({state: browser cookies & storage, user_agent, account: who})
    write blob to session.tmp, then replace session.enc with it       ← atomic
```

```python
# mailbrief/session/manager.py
# ponytail: single user, single file; per-user paths + sessions table when multi-user lands
SESSION_PATH = Path("data/session.enc")


def load() -> dict | None:
    """Return {"state": storage_state, "user_agent": str}, or None if never logged in."""
    if not SESSION_PATH.exists():
        return None
    return decrypt(SESSION_PATH.read_bytes())


def account() -> str | None:
    """The address the saved session belongs to, if a run has recorded it yet. Never raises."""
    try:
        return (load() or {}).get("account")
    except Exception:  # noqa: BLE001 - an unreadable session has no known account
        return None


def save(context, user_agent: str, account_: str | None = None) -> None:
    """account_: the signed-in address when the caller knows it; otherwise the recorded one is kept."""
    SESSION_PATH.parent.mkdir(exist_ok=True)
    who = account_ or account()
    blob = encrypt({"state": context.storage_state(), "user_agent": user_agent, **({"account": who} if who else {})})
    tmp = SESSION_PATH.with_suffix(".tmp")
    tmp.write_bytes(blob)
    replace(tmp, SESSION_PATH)  # atomic: a crash mid-write never leaves a broken session
```

#### How it works and why it's written this way
- **`context.storage_state()`** is Playwright's snapshot of a browser context: every cookie plus each site's `localStorage`, as a plain dict. Its opposite is `browser.new_context(storage_state=that_dict)`, which starts a fresh context already signed in. That pair is the whole trick behind "log in once": `main.run` and `labels` call `new_context(storage_state=session["state"], user_agent=session["user_agent"])`. The alternative, a persistent browser profile folder (`launch_persistent_context`), holds the same cookies but as hundreds of unencrypted files.
- **`load()` returns `None` for "never logged in"** and lets a decryption error (`InvalidToken`) propagate. The two mean different things. "Not logged in" is normal ("run `mailbrief login`"). "Can't decrypt" means the key changed, and `main` reports that separately.
- **`account()` never raises.** It is a nice-to-have (the remote sign-in uses it to warn when you sign in to a different mailbox), so a broken session file must not turn it into a crash.
- **`account_ or account()`.** A caller that knows the address (a run reads it from StartupData) records it. A caller that doesn't (`login_once`) keeps the one already recorded. `**({"account": who} if who else {})` adds the key only when there is a value, so a session never stores `"account": null`.
- **`with_suffix(".tmp")`** turns `data/session.enc` into `data/session.tmp`, in the same folder, so `replace` is a same-disk rename. `mkdir(exist_ok=True)` creates `data/` on first use and does nothing after.
- **Why does every `run` re-save the session?** Microsoft rotates authentication cookies. Saving the fresh ones at the end of each run keeps the session alive much longer than the original login cookies would last.
- **Relative path.** `Path("data/session.enc")` is relative to the folder you run the command from. Run from another folder and you get a fresh, empty `data/`. That's simple and fine for one user; the `ponytail:` comment names the upgrade.

### `login_once.py`
```
check the encryption key                                ← before anything is typed
open a VISIBLE browser
user_agent ← ask the blank page for its identity        ← BEFORE navigating (see below)
go to Outlook
tell the user: "sign in, then press Enter"
wait for Enter
manager.save(browser cookies + storage, user_agent)
```

```python
# mailbrief/session/login_once.py::login_once
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
        browser.close()
```

#### How it works and why it's written this way
- **`page.evaluate("navigator.userAgent")`** runs a line of JavaScript inside the page and returns its value to Python.
- **Why read the user agent before navigating?** Outlook redirects several times while loading (to the Microsoft login page and back). Each redirect destroys the page's JavaScript context. Asking the page anything during a redirect crashes ("Execution context was destroyed"). This happened in practice (see [lessons from real bugs](10-lessons-and-limits.md)). The identity string is the same on every page, so reading it on the blank page first is safe.
- **Why save the user agent at all?** An invisible browser announces itself as `HeadlessChrome`. If the login was made by "Chrome" and the next visit says "HeadlessChrome", Microsoft may treat it as a different device. So every run reuses the login's exact identity.
- **Why `input()`?** The program can't know when MFA is finished; you can. Pressing Enter is the simplest reliable signal. The cost: whatever state the browser is in when you press Enter is what gets saved (see "Known gaps" below).

#### Known gaps
`login_once` saves without checking that you actually reached the inbox. Press Enter too early and a not-signed-in session replaces the saved one; the next run then reports "expired". It also doesn't record the account, so after signing in to a different mailbox the old address stays recorded until the next run's save corrects it. The remote sign-in below does both checks. Copying its "check, then save" step here would close the gap.

### Rebuilding it
`manager` needs only `crypto` and `files`. Input: a Playwright `BrowserContext`. Output: an encrypted file, and later the dict you pass back into `new_context`. For another site, nothing changes except `INBOX_URL`: any site that keeps you signed in with cookies and `localStorage` works the same way. For several users, make `SESSION_PATH` per user.

### Try it
No direct tests: both need a browser. `tests/test_pipeline.py` replaces `manager.load` and `manager.save` with stand-ins to test what a run does around them. To try `login_once` by hand: `mailbrief login`.

---

## `browser/outlook_reader.py`
**Job:** drive Outlook: open it, listen to its data, scroll until everything is loaded, and make read-only data calls. It's the only module that "operates" Outlook for reading.

The names at the top hold everything that is specific to Outlook's page:

```python
# mailbrief/browser/outlook_reader.py
INBOX_URL = "https://outlook.office.com/mail/"
LOGIN_HOSTS = ("login.microsoftonline.com", "login.live.com")
MESSAGE_LIST = '[role="listbox"]'
MESSAGE_ROW = f'{MESSAGE_LIST} [role="option"]'
# Headers Outlook's own service.svc calls carry that GetItem needs. Kept in memory only, never logged.
REPLAY_HEADERS = ("authorization", "x-anchormailbox", "x-owa-sessionid", "x-req-source", "x-owa-hosted-ux", "x-client-version", "prefer")
GETITEM_BATCH = 20
STALL_S = 15
```

**Why ARIA roles (`role="listbox"`, `role="option"`) and not CSS classes?** Outlook's class names are generated and change with every release. The roles are there for screen readers, so they have to stay meaningful. They are the most stable handle the page offers.

### The listeners
Two functions attach listeners, before Outlook is opened, so no early request is missed:
```
read_inbox, on every RESPONSE:   if it's JSON from an outlook.* host
                                 → remember (which Focused/Other view it belongs to, the response)
open_outlook, on every RESPONSE: if its URL contains "startupdata"
                                 → remember it separately   (it's JSON labelled as JavaScript)
open_outlook, on every REQUEST:  if it's a service.svc call carrying an authorization header
                                 → remember its URL, its auth headers, and its JSON "Header"   (_track_auth)
```

```python
# mailbrief/browser/outlook_reader.py::_request_json
def _is_outlook_json(response) -> bool:
    host = urlparse(response.url).hostname or ""
    return host.startswith("outlook.") and "json" in response.headers.get("content-type", "")


def _request_json(request) -> dict:
    """service.svc sends its JSON either as the POST body or URL-encoded in an x-owa-urlpostdata header."""
    raw = request.post_data or unquote(request.headers.get("x-owa-urlpostdata", ""))
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _view_of(request):
    """FindConversation's FocusedViewFilter: 0 = Focused, 1 = Other, -1/None = no Focused Inbox."""
    return (_request_json(request).get("Body") or {}).get("FocusedViewFilter")


def _track_auth(auth: dict, request) -> None:
    """Remember the latest service.svc call's auth headers and JSON Header (the token can refresh mid-run)."""
    if "service.svc" not in request.url or "authorization" not in request.headers:
        return
    header = _request_json(request).get("Header")
    if header:
        auth.update(url=request.url, header=header, headers={k: v for k, v in request.headers.items() if k in REPLAY_HEADERS})
```

```python
# mailbrief/browser/outlook_reader.py::read_inbox
    responses = []  # (view, response)
    page.on("response", lambda r: responses.append((_view_of(r.request), r)) if _is_outlook_json(r) else None)
```

#### How it works and why it's written this way
- **`page.on("response", handler)`** makes Playwright call `handler` with every network response the page receives. The handler here is a one-line `lambda` with a conditional expression: append if it's Outlook JSON, else do nothing (`None`). It only stores the `Response` object. The body is read later with `r.json()`, inside a `try`, because some responses (redirects, empty bodies) have no JSON despite their content type.
- **Why listen instead of asking?** Outlook's own page already makes exactly the right requests for the inbox list. Listening gets them for free, perfectly formed, with no need to reverse-engineer how to build them.
- **`urlparse(...).hostname or ""`**: `hostname` is `None` for odd URLs like `data:`. `or ""` makes `.startswith` safe.
- **`_request_json` reads two places.** Outlook sends its request JSON either as the POST body or, URL-encoded, in an `x-owa-urlpostdata` header. `unquote` undoes the URL encoding. Anything that isn't a JSON object gives `{}`, so callers can chain `.get` without checks.
- **Why "which view"?** Responses are tagged with their `FocusedViewFilter` (0 = Focused, 1 = Other), read from the *request* that produced them (`r.request`). When you switch tabs, Outlook also refreshes the *other* tab in the background. Without the tag those responses got mixed up (a real bug; see [lessons](10-lessons-and-limits.md)).
- **`_track_auth` keeps the latest, not the first.** `auth.update(...)` overwrites on every qualifying request. The authorization token can refresh while the program is scrolling, and the newest one avoids "401 Unauthorized". `auth` is a dict passed in by the caller and changed in place, so the caller's reference always sees the newest values with no return value to thread through.
- **Only the headers in `REPLAY_HEADERS` are kept.** That's the minimum a `GetItem` call needs. They stay in memory and are never written or logged. The dict comprehension `{k: v for k, v in ... if k in REPLAY_HEADERS}` filters them. Playwright gives header names in lower case, so the tuple is lower case too.

### `open_outlook(page)`: open and wait until signed in
Shared by `read_inbox`, `labels` (to write categories) and `remote_login` (to check a new sign-in).
```
attach the StartupData and auth listeners; open outlook.office.com/mail
repeat every 0.5 s for up to 60 s:
    if the host is a Microsoft login host → return "expired"
    if message rows are visible → stop waiting
if no rows appeared and the browser isn't on an outlook.* host → "expired"
      (an organisation's own sign-in page, a consent or "stay signed in?" screen)
wait 3 s for the follow-up requests
return { expired: no, auth, startup: the parsed StartupData }
```

```python
# mailbrief/browser/outlook_reader.py::open_outlook
    auth: dict = {}
    startup_responses: list = []
    # StartupData is JSON served as application/x-javascript, so a JSON content-type filter would miss it.
    page.on("response", lambda r: startup_responses.append(r) if "startupdata" in r.url.lower() else None)
    page.on("request", lambda r: _track_auth(auth, r))
    progress.step("Opening Outlook…")
    page.goto(INBOX_URL, wait_until="domcontentloaded")

    # Wait for either the message list or a redirect to the Microsoft login page.
    loaded = False
    for _ in range(timeout_s * 2):
        if (urlparse(page.url).hostname or "") in LOGIN_HOSTS:
            progress.step("Session expired (redirected to the Microsoft login page)")
            return {"expired": True, "auth": auth, "startup": []}
        if page.locator(MESSAGE_ROW).count():
            loaded = True
            break
        page.wait_for_timeout(500)
    host = urlparse(page.url).hostname or ""
    if not loaded and not host.startswith("outlook."):
        # Parked somewhere that isn't Outlook: an organisation's own sign-in page, a consent or "stay signed in?"
        # screen. That is a sign-in to finish, not an empty inbox.
        progress.step("Session expired (Outlook sent the browser to a sign-in page)")
        return {"expired": True, "auth": auth, "startup": []}
# ...
    page.wait_for_timeout(3000)  # let the list's follow-up requests finish (and auth be captured)
```

#### How it works and why it's written this way
- **`wait_until="domcontentloaded"`** returns as soon as the HTML is parsed. The default (`"load"`) waits for every image and script, and Outlook's page keeps loading things for a long time. The loop below does the real waiting, for the thing that matters.
- **`page.locator(MESSAGE_ROW).count()`** counts matching elements right now, without waiting. That suits a polling loop. Most locator methods (`click`, `bounding_box`) instead wait up to 30 s for the element, which would freeze the loop.
- **`page.wait_for_timeout(500)`, not `time.sleep(0.5)`.** In Playwright's sync API, event handlers (the listeners above) only run while Playwright is in control, during one of its own calls. During a `time.sleep` they would queue up and not run. `wait_for_timeout` waits *and* lets the listeners run. Playwright's docs call it "for debugging"; here it is a deliberate polling interval.
- **Why detect expiry by URL?** When cookies are no longer valid, Outlook redirects to the Microsoft login page. That is the clearest signal there is. The second check catches organisations whose sign-in page is on their own domain: if no rows appeared and the browser isn't on an `outlook.*` host, it is a sign-in to finish, not an empty inbox. If the browser *is* on Outlook but no rows appeared, it carries on and reports "slow network, or an empty inbox".
- **Why a fixed 3 s wait at the end?** After the first rows appear, Outlook fires more requests (the Focused/Other counts, the first `service.svc` call `_track_auth` needs). There is no event that says "done". A fixed wait is crude but reliable; it costs 3 s per run.

### `read_inbox(page)`: the main routine
```
attach the JSON-response listener; open_outlook
if expired → return "expired"

first_view ← the view of the first list response (0 = Focused, -1/none if Focused Inbox is off)
payloads ← _load_view(first_view)
if first_view is Focused and there's an "Other" tab:
    click "Other"; wait 3 s; payloads += _load_view(Other)
    click "Focused" again                      ← leave Outlook as we found it

return:
    messages ← parse_messages(all payloads)     (conversations)
    total    ← sum of each view's TotalConversationsInView (none if any is unknown)
    auth     ← remembered headers (for GetItem later)
    me       ← your address from StartupData
    urls     ← endpoint paths seen (for debugging; no query strings, so no tokens)
```

```python
# mailbrief/browser/outlook_reader.py::read_inbox
    # With Focused Inbox on, the list only shows one tab; load "Other" too, then switch back.
    first_view = next((v for v, _ in responses if v is not None), None)
    views = [_load_view(page, responses, first_view, max_scrolls)]
    other = page.get_by_role("tab", name="Other")
    if first_view == 0 and other.count():
        other.first.click()
        page.wait_for_timeout(3000)
        views.append(_load_view(page, responses, 1, max_scrolls))
        page.get_by_role("tab", name="Focused").first.click()

    totals = [view_total(v) for v in views]
    urls = sorted({urlparse(r.url).path for _, r in responses})  # paths only: no tokens in query strings
    startup = opened["startup"]
    return {
        "expired": False,
        "messages": parse_messages([p for v in views for p in v]),
        "total": None if None in totals else sum(totals),
        "urls": urls,
        "auth": auth,
        "me": find_user_email(startup),  # your address, to recognise your own replies in threads
    }
```

#### How it works and why it's written this way
- **`next((... for ... if ...), None)`** is the idiom for "the first item that matches, or `None`". The generator stops at the first match, so it doesn't scan the whole list.
- **`get_by_role("tab", name="Other")`** finds the tab by its accessible name, the same way a screen reader would. `.count()` checks it exists without waiting. Only Focused Inbox users have it, so `first_view == 0` is checked too.
- **This click is the only one MailBrief makes while reading.** Switching tabs doesn't open or mark any email. Clicking "Focused" again at the end leaves Outlook as it found it.
- **`[p for v in views for p in v]`** flattens a list of lists. Read it left to right like nested `for` loops.
- **`None if None in totals else sum(totals)`.** A partial total would be wrong, and `main` prints "inbox: N of TOTAL"; an honest "?" is better.
- **`urls` keeps only paths.** Query strings can carry tokens, so they never reach the output.
- **The expired return** has no `"me"` key. Callers check `expired` first and stop.

### `_load_view(view)`: scrolling until complete
```
move the mouse over the message list
loop (max 300 scrolls):
    collect new responses that belong to THIS view
    count ← how many distinct conversations so far
    total ← what Outlook says this view holds (TotalConversationsInView)
    if count went up → remember the time
    if count ≥ total → done (everything loaded)
    if nothing new for 15 s → give up (Outlook stalled)
    scroll the wheel down; wait 0.8 s
collect once more
```

```python
# mailbrief/browser/outlook_reader.py::_load_view
    payloads, read = [], 0

    def drain():
        nonlocal read
        for v, r in responses[read:]:
            if v != view:  # Outlook also refreshes the other tab in the background
                continue
            try:
                payloads.append(r.json())
            except Exception:  # redirects, empty bodies, non-JSON despite the header
                pass
        read = len(responses)
# ...
    box = page.locator(MESSAGE_LIST).first.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    label = {0: "Loading Focused tab", 1: "Loading Other tab"}.get(view, "Loading inbox")
    last, last_growth = -1, time.monotonic()
    for _ in range(max_scrolls if box else 0):
        drain()
        count, total = len(parse_messages(payloads)), view_total(payloads)
        if total:
            progress.count(label, min(count, total), total)
        if count != last:
            last, last_growth = count, time.monotonic()
        # Done when everything is loaded, or Outlook sent nothing new for STALL_S (it can be slow per page).
        if (total is not None and count >= total) or time.monotonic() - last_growth > STALL_S:
            break
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(800)
    drain()
    return payloads
```

#### How it works and why it's written this way
- **`drain` and `nonlocal read`.** `responses` keeps growing as the listener appends to it. `read` remembers how far `drain` got, so each call only looks at new entries (`responses[read:]`). `nonlocal` lets the inner function change the outer function's `read`; without it, `read = ...` would create a new local variable. It's safe without a lock because sync Playwright runs the listener on this same thread, only during Playwright calls such as `wait_for_timeout`.
- **Why the mouse wheel?** The list is virtualized: it only renders rows on screen and only fetches more when it sees a real scroll event. Programmatic "scroll element into view" didn't trigger loading; the wheel does (found by experiment). `mouse.wheel` scrolls whatever is under the pointer, which is why the mouse is first moved to the middle of the list's `bounding_box()`.
- **`bounding_box()` waits.** Like most locator methods it waits (30 s by default) for a matching element. It returns `None` only when the list exists but isn't visible; then `range(max_scrolls if box else 0)` means no scrolling, and the final `drain()` still collects what arrived. If there is no list element at all, `bounding_box()` raises a Playwright timeout error instead, so `if box:` doesn't cover that case.
- **Why stop at `TotalConversationsInView`?** Outlook tells us how many conversations exist, so we know exactly when we're done instead of guessing.
- **Why a 15-second stall rule?** A safety net in case the total never arrives or Outlook is slow. It was 5 s at first, but one real run gave up at 180 of 344 because Outlook paused between pages. 15 s fixed that.
- **`time.monotonic()`, not `time.time()`.** It never jumps when the system clock is changed, so a clock sync mid-run can't fake or hide a stall.
- **`max_scrolls=300` is a hard ceiling.** At about 50 conversations per page, that's far more than any real inbox needs. It exists so that a bug can never scroll forever.
- **Known cost.** Each round re-parses *every* payload so far (`parse_messages(payloads)`), so the work grows with the square of the inbox size. At a few hundred conversations it's milliseconds. The `ponytail:` comment in the code names the other ceiling: it always loads the whole view, even when only today's mail is new. Stopping at the cursor's date is the upgrade for a huge inbox.

### `fetch_emails(page, auth, conversations, me)`
```
inbox_ids ← every item_id of these conversations
ids       ← every global_item_id (all folders)
for each batch of 20 ids:
    response ← _service_call("GetItem", body built by getitem_body)
    if it failed → warn, return (preview_records(conversations), False)
    records += parse_items(response)
for each record:
    in_inbox ← record.id in inbox_ids
    from_me  ← record.sender_email == me   (case-insensitive)
    direct   ← you are the only To recipient
return (records, True)
```

```python
# mailbrief/browser/outlook_reader.py::fetch_emails
    inbox_ids = {i for c in conversations for i in c["item_ids"]}
    ids = [i for c in conversations for i in c["global_item_ids"]]
    records = []
    for n in range(0, len(ids), GETITEM_BATCH):
        resp = _service_call(page, auth, "GetItem", lambda header: getitem_body(header, ids[n : n + GETITEM_BATCH]))
        if resp is None or not resp.ok:
            status = resp.status if resp else "no auth captured"
            print(f"warning: GetItem failed ({status}); falling back to list previews", file=sys.stderr)
            return preview_records(conversations), False
        records += parse_items(resp.json())
        progress.count("Fetching full text", min(n + GETITEM_BATCH, len(ids)), len(ids))
    for r in records:
        r["in_inbox"] = r["id"] in inbox_ids
        r["from_me"] = me is not None and r["sender_email"].lower() == me.lower()
        r["direct"] = me is not None and r.get("to") == [me.lower()]  # you're the only To recipient
    return records, True
```

#### How it works and why it's written this way
- **Why `GetItem` instead of clicking emails?** It returns the full plain-text body with no clicking, so emails stay **unread** (verified: unread counts didn't change). It's also fast: 20 emails per request.
- **`inbox_ids` is a set, `ids` a list.** The set is only used for `in` tests, which are instant on a set. The list keeps Outlook's order for the batches.
- **`range(0, len(ids), GETITEM_BATCH)` and `ids[n : n + 20]`** walk the list 20 at a time; the last slice is just shorter. Why 20? It keeps each request small and quick while still cutting hundreds of emails down to a handful of calls.
- **The `lambda header: ...` in a loop.** A lambda looks up `n` when it *runs*, not when it's made. That's safe here only because `_service_call` calls it straight away, inside the same loop turn. If you ever stored these lambdas to run later, they would all see the last `n`. The fix then is `lambda header, n=n: ...`.
- **Why the preview fallback?** If `GetItem` ever breaks (format change, auth failure), you still get a digest built from the list's preview snippets instead of nothing. The `False` tells `main`. The cursor refuses to move on a preview run (see [the cursor](03-ai-pipeline.md)), so no email is lost.
- **`me is not None and ...`** short-circuits: with no known address, `from_me` is `False` and `.lower()` is never called on `None`. Addresses are compared lower-cased because Exchange doesn't keep one spelling.
- **`direct`** compares the whole `to` list with `[your address]`: only To, only you. `parse_items` already lower-cased `to`. Sender rules with `--direct` use it.

### `fetch_images(page, auth, email)` and `fetch_attachment(page, auth, id)`
```
fetch_images:
    if the email has no qualifying image attachments → []
    response ← _service_call("GetAttachment", the attachment ids)
    turn each returned base64 image into a "data:image/png;base64,…" URL
    return them                      (kept in memory only, never written to disk)
fetch_attachment:                    (the chat bot's "send me that file")
    one GetAttachment → {name, content_type, data: decoded bytes}, or nothing
```

```python
# mailbrief/browser/outlook_reader.py::fetch_images
    if resp is None or not resp.ok:
        return []
    urls = []
    for msg in resp.json().get("Body", {}).get("ResponseMessages", {}).get("Items", []):
        for a in msg.get("Attachments") or []:
            if a.get("Content"):
                ctype = a.get("ContentType") if str(a.get("ContentType", "")).startswith("image/") else "image/png"
                urls.append(f"data:{ctype};base64,{a['Content']}")
    return urls
```

#### How it works and why it's written this way
- **A data URL** (`data:image/png;base64,…`) puts the image bytes inside the URL itself. The AI endpoint's image input accepts that directly. Outlook already returns the content as base64, so no decoding or re-encoding is needed: the string just gets a prefix.
- **The content type falls back to `image/png`** when Outlook sends none or a non-image one (some mailers label images `application/octet-stream`). Vision models sniff the real format from the bytes, so the label only has to say "image".
- **`.get("Body", {}).get(...)` chains** walk the nested reply without a `KeyError` at any level. A missing level just gives an empty list.
- **Fail soft.** Any failure returns `[]`, and the email is simply classified without its images. Images are a bonus, not a requirement.
- `fetch_attachment` is the same call for one id. It decodes with `base64.b64decode` because Telegram needs real bytes, and the bytes live only in memory until they are sent:

```python
# mailbrief/browser/outlook_reader.py::fetch_attachment
    for msg in resp.json().get("Body", {}).get("ResponseMessages", {}).get("Items", []):
        for a in msg.get("Attachments") or []:
            if a.get("Content"):
                return {"name": a.get("Name") or "file", "content_type": a.get("ContentType") or "application/octet-stream",
                        "data": base64.b64decode(a["Content"])}
    return None
```

### `fetch_image_urls(page, auth, emails)` and `collect_images(page, auth, emails)`
Newsletters rarely attach their posters: they load them from the web, and the plain-text body MailBrief reads has no trace of them. So:
```
fetch_image_urls:  only for emails with full text (body_source "getitem")
                   read-only GetItem with BodyType HTML (Body only), 20 at a time
                   → image_urls(html) per email; the HTML is dropped right there
                   a failed batch → stop; no linked images this time
collect_images:    linked URLs only if REMOTE_IMAGES is on
                   for each email with attached images or linked ones:
                       attached + inline images first (fetch_images)
                       then linked ones (web_images.download)
                         to fill what's left of 4 images / 8 MB
                   every email gets an entry, [] if nothing
```

```python
# mailbrief/browser/outlook_reader.py::fetch_image_urls
    ids = [e["id"] for e in emails if e.get("body_source") == "getitem"]
    out = {}
    for n in range(0, len(ids), GETITEM_BATCH):
        resp = _service_call(page, auth, "GetItem", lambda header: html_getitem_body(header, ids[n : n + GETITEM_BATCH]))
        if resp is None or not resp.ok:
            break
        out.update({i: image_urls(html) for i, html in html_bodies(resp.json()).items()})
    return out
```

```python
# mailbrief/browser/outlook_reader.py::collect_images
    links = fetch_image_urls(page, auth, emails) if web_images.enabled() else {}
    wanted = [e for e in emails if e.get("image_attachments") or links.get(e["id"])]
    images: dict[str, list[str]] = {e["id"]: [] for e in emails}
    for n, e in enumerate(wanted, 1):
        got = fetch_images(page, auth, e)
        used = sum(a.get("size") or 0 for a in (e.get("image_attachments") or [])[: len(got)])
        if links.get(e["id"]) and len(got) < IMAGES_PER_EMAIL:
            got += web_images.download(links[e["id"]], IMAGES_PER_EMAIL - len(got), IMAGE_BUDGET - used)
        images[e["id"]] = got
        progress.count("Fetching images", n, len(wanted))
    return images
```

#### How it works and why it's written this way
- **`{e["id"]: [] for e in emails}`** gives every email a key up front, so `main` can write `images[e["id"]]` without checking. Only `wanted` emails cost a network call.
- **`enumerate(wanted, 1)`** counts from 1, which is what the progress line shows ("3 of 7").
- **`used`** estimates how much of the 8 MB budget the attachments took, from their listed sizes. It assumes the first `len(got)` attachments are the ones that came back, which is true when every requested attachment returns content. It's an estimate: if one came back empty, the sizes are off by one attachment. `web_images` checks real sizes as it downloads, so the cost of the error is a slightly smaller or larger budget for linked images, not a refused request.
- **The HTML is dropped at once.** `html_bodies` returns the HTML, and the dict comprehension keeps only `image_urls(html)` for each email. The HTML itself is never stored or logged.
- **Same browser session.** All of this happens before the browser closes, for the emails that need the AI only (`todo` in `main`).

### `_service_call(page, auth, action, make_body)`
```
repeat up to 2 times:
    if no auth was captured → nothing
    body ← make_body(Outlook's newest JSON Header)
    check_request(action, body)       ← the write guard: raises before anything is sent
    POST to the same service.svc URL Outlook uses, with ?action=<action>&app=Mail
         headers = Outlook's own auth headers + action name + JSON content type
         timeout 60 s
    if not 401 → stop
    wait 2 s                      (the token may have just refreshed; try again)
return the response
```

```python
# mailbrief/browser/outlook_reader.py::_service_call
    resp = None
    for _ in range(2):  # retry once: a 401 usually means the token refreshed after we copied it
        if not auth:
            return None
        body = make_body(auth["header"])
        check_request(action, body)  # raises before anything leaves this machine
        url = urlparse(auth["url"])._replace(query=f"action={action}&app=Mail").geturl()
        resp = page.request.post(
            url,
            headers={**auth["headers"], "action": action, "content-type": "application/json; charset=utf-8"},
            data=json.dumps(body),
            timeout=60_000,  # a 20-email update can take Outlook a while
        )
        if resp.status != 401:
            break
        page.wait_for_timeout(2000)
    return resp
```

#### How it works and why it's written this way
- **Why `page.request` (the browser's request context)?** It automatically carries the browser's cookies, so the call looks exactly like the page's own. Python's `urllib` would need the cookies copied out and kept in sync by hand.
- **Why `make_body` is a function and not a ready-made body:** the body contains Outlook's `Header`, which can change when the token refreshes. Building it at the last moment, inside the retry loop, uses the newest one on the second try too.
- **`check_request` runs on every call, reads included.** Reads (`GetItem`, `GetAttachment`) pass straight through. Writes are only allowed for MailBrief's own `MB:` categories, and any other action raises `UnsafeRequest` before a byte leaves the machine. Because *every* call goes through this one function, there is no way to send a request that skips the guard. The guard is explained in [labels](05-labels-rules-extras.md).
- **`urlparse(...)._replace(query=...).geturl()`** reuses the exact host and path Outlook used and swaps only the query string. `_replace` is the public method of the named tuple `urlparse` returns, despite the underscore. The old query string (which might carry other parameters) is dropped.
- **`{**auth["headers"], "action": ...}`** copies the saved headers and adds two. The saved dict itself is never changed.
- **`timeout=60_000`** is in milliseconds, as everywhere in Playwright. The `_` is just a digit separator.
- **Why retry only once, and only on 401?** A 401 right after copying a token usually means it was just refreshed; the page's next request gives `_track_auth` the new one, and 2 s is enough for that. Other errors (500, 403) won't fix themselves in 2 s, so they go back to the caller, which falls back softly.

### Rebuilding it
Inputs: a Playwright `Page` built from a saved session. Outputs: plain dicts (conversations, EmailRecords, data URLs). It depends on `owa_network` for every bit of format knowledge and on `progress` for the status line. To adapt it to another web app that draws from JSON:
1. Change `INBOX_URL`, `LOGIN_HOSTS` and the ARIA selectors.
2. Open the site with your browser's developer tools (Network tab, filter "Fetch/XHR"), and find the request that carries the list and the headers it sends. Put those headers in `REPLAY_HEADERS`.
3. Keep the shape: listen first, open, wait for a real signal (rows, or a login redirect), scroll while counting, then make your own read calls through one function that checks each request.

For a provider with a real API (Gmail, Microsoft Graph with an app registration), you'd delete this module and `owa_network` and call the API instead. That's simpler and more stable whenever it's allowed.

### Try it
No direct tests: everything here needs a live Outlook. `tests/test_pipeline.py` replaces `read_inbox`, `fetch_emails` and `collect_images` with stand-ins and tests what `main.run` does with their results (e.g. `test_previews_are_not_archived_and_cannot_advance_cursor` uses the `False` from the preview fallback). The parsing it relies on is tested in `tests/test_owa_network.py`, below. `mailbrief run` without `--send` or `--commit` is the safe way to watch it work.

---

## `browser/owa_network.py`
**Job:** understand Outlook's JSON. These are **pure functions**: data in, data out, no browser and no network. That's why they're easy to test, and why all format knowledge lives here. It also builds every request body MailBrief sends, and holds the write guard `check_request`.

### Finding messages in any JSON: `_walk` and `_to_message`
Outlook's responses are deeply nested, and the nesting differs between endpoints. Instead of hard-coding paths, the code **walks the whole tree** and recognises message-shaped objects by their keys:
```
function walk(node):
    if node is an object:
        if it looks like a message → record it; don't go deeper
            (ConversationTopic → a conversation; Subject → an item;
             either way it needs a time that parses)
        otherwise → walk each value
    if node is a list → walk each element
```

```python
# mailbrief/browser/owa_network.py::_walk
def _lower(d: dict) -> dict:
    return {k.lower(): v for k, v in d.items() if isinstance(k, str)}


def _id(value) -> str | None:
    if isinstance(value, dict):
        value = _lower(value).get("id")
    return value if isinstance(value, str) else None
# ...
def _parse_time(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
# ...
def _walk(node, found: list) -> None:
    if isinstance(node, dict):
        msg = _to_message(node)
        if msg:
            found.append(msg)
            return
        children = list(node.values())
    elif isinstance(node, list):
        children = node
    else:
        return
    for child in children:
        _walk(child, found)
```

`_to_message` itself is quoted in full with the Conversation shape in [the overview](01-overview.md).

#### How it works and why it's written this way
- **Keys are compared case-insensitively** (`_lower` makes a lower-cased copy of the keys). **Why?** Robustness: if Microsoft moves the list one level deeper, renames the wrapper or changes the case of a key, this still finds the messages. The cost: an unrelated object that happens to have `Subject` and a date would be taken for a message. `parse_messages` then prefers conversations, which limits the damage.
- **`_id`** accepts both shapes Outlook uses for an id: a bare string, or an object like `{"__type": "ItemId:#Exchange", "Id": "…", "ChangeKey": "…"}`. Anything else is `None`, and `[i for i in map(_id, ...) if i]` drops those.
- **`_parse_time`** uses `datetime.fromisoformat`. Since Python 3.11 it reads Outlook's `2026-03-04T08:15:00Z` and offsets like `+05:30`. A time with no zone is assumed UTC (`replace(tzinfo=...)`), so every `received_at` in the program is timezone-aware and they can all be compared. Mixing aware and naive datetimes raises `TypeError`.
- **Recursion** suits a tree of unknown shape. Outlook's JSON is a few dozen levels deep at most, far below Python's limit of 1000. `view_total` and `find_user_email` below use an explicit stack instead; both styles work, and the stack can't hit the limit.
- **"Don't go deeper"** once something is recorded, so a message's own nested parts (its sender, its attachments) are never mistaken for more messages.

### `parse_messages(payloads)`
```
found ← walk all payloads
if any conversations were found → keep only conversations   (list view and item view describe the same mail)
deduplicate by id (or subject + time if there's no id)      (the same page is often downloaded twice)
sort newest first
```

```python
# mailbrief/browser/owa_network.py::parse_messages
    found: list[dict] = []
    for payload in payloads:
        _walk(payload, found)
    # Conversation view and item view describe the same mail; prefer conversations if present.
    if any(m["kind"] == "conversation" for m in found):
        found = [m for m in found if m["kind"] == "conversation"]
    unique: dict = {}
    for m in found:
        unique.setdefault(m["id"] or (m["subject"], m["received_at"]), m)
    return sorted(unique.values(), key=lambda m: m["received_at"], reverse=True)
```

**`setdefault(key, m)`** stores `m` only if the key isn't there yet: the first copy wins. A dict keeps insertion order and finds keys instantly, so this deduplicates in one pass. The fallback key is a tuple, which works as a dict key because tuples are immutable.

### `view_total(payloads)`
Walks the JSON looking for `TotalConversationsInView` / `TotalItemsInView` and returns the largest. This is how `_load_view` knows when scrolling is finished.

```python
# mailbrief/browser/owa_network.py::view_total
    best = None
    stack = list(payloads)
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str) and k.lower() in ("totalconversationsinview", "totalitemsinview") and isinstance(v, int):
                    best = v if best is None else max(best, v)
                else:
                    stack.append(v)
        elif isinstance(node, list):
            stack.extend(node)
    return best
```

**Why the largest?** Each page of results repeats the total, and a page fetched before new mail arrived can carry a smaller one. **Why `None`, not 0?** "Outlook didn't say" and "the view is empty" are different. `_load_view` stops at a known total but keeps scrolling (until the stall rule) when there isn't one.

### `getitem_body(header, ids)`
Builds the JSON for a read-only `GetItem` request: ask for "IdOnly" plus exactly the fields we need, with the body as **Text**.

```python
# mailbrief/browser/owa_network.py::getitem_body
_GETITEM_FIELDS = (
    "Subject", "From", "DateTimeReceived", "Body", "Importance",
    "IsRead", "HasAttachments", "Attachments", "ConversationId",
    "ConversationIndex", "InReplyTo", "InternetMessageId", "DateTimeSent",
    "ToRecipients", "CcRecipients",
)


def getitem_body(header: dict, ids: list[str]) -> dict:
    """JSON for a read-only GetItem call (plain-text bodies). `header` is copied from Outlook's own request."""
    return {
        "__type": "GetItemJsonRequest:#Exchange",
        "Header": header,
        "Body": {
            "__type": "GetItemRequest:#Exchange",
            "ItemShape": {
                "__type": "ItemResponseShape:#Exchange",
                "BaseShape": "IdOnly",
                "BodyType": "Text",
                "AdditionalProperties": [{"__type": "PropertyUri:#Exchange", "FieldURI": f} for f in _GETITEM_FIELDS],
            },
            "ItemIds": [{"__type": "ItemId:#Exchange", "Id": i} for i in ids],
        },
    }
```

- **Why list the fields explicitly?** Asking for exactly what's needed keeps responses small, and the field list doubles as documentation of what the app uses. Requesting the body as **Text** has Exchange convert the HTML for us, which saves an HTML parser.
- **`__type` keys** are how Exchange's JSON API names the type of each object (it comes from its older SOAP/XML interface). Leave one out and Exchange rejects the request. These shapes were copied from requests Outlook itself sends, not guessed.
- **`html_getitem_body`** builds the same request, then swaps in `BodyType: HTML` and asks for `Body` only: it's used once, to find linked images. **`html_bodies`** reads that reply into `{id: html}`. **`categories_getitem_body`** asks for just `Categories` (used by labels).

### `parse_items(response)` → EmailRecords
```
for each response message:
    skip unless ResponseClass == "Success"    (e.g. an email deleted a moment ago)
    for each item:
        skip it if its received time doesn't parse
        build an EmailRecord: ids, sender, subject, time,
            body ← _clean(body text)
            attachment_names, image_attachments(…), attachment_list(…)
            to, cc ← addresses(…)
            thread fields (conversation_index, in_reply_to, …)
            in_inbox ← true, from_me ← false     (the reader corrects these; it knows more)
```

```python
# mailbrief/browser/owa_network.py::parse_items
    records = []
    for msg in (response.get("Body") or {}).get("ResponseMessages", {}).get("Items", []):
        if msg.get("ResponseClass") != "Success":
            continue
        for it in msg.get("Items", []):
            received = _parse_time(it.get("DateTimeReceived") or "")
            if received is None:
                continue
            box = (it.get("From") or {}).get("Mailbox") or {}
```

The rest of the function is the record itself, quoted in [the overview](01-overview.md) with the EmailRecord shape.

**Why skip failures instead of raising?** Between the list load and `GetItem`, you might delete an email on your phone. One missing email must not cost you the other 19 in the batch.

`_clean(text)`: turns Windows line endings into `\n`, squeezes runs of spaces, tabs and non-breaking spaces, squeezes runs of blank lines to one, and caps at 20,000 characters.

```python
# mailbrief/browser/owa_network.py::_clean
def _clean(text: str) -> str:
    text = re.sub(r"[ \t\u00a0]+", " ", text.replace("\r\n", "\n"))
    text = re.sub(r"\s*\n\s*\n\s*", "\n\n", text).strip()
    return text[:BODY_CAP]
```

**Why?** Emails are full of formatting junk. Cleaner text means fewer AI tokens and easier reading, and the cap protects against giant emails. `\u00a0` is the non-breaking space HTML-to-text conversion leaves everywhere; `\s` in the second pattern already includes it. The order matters: spaces are squeezed first, so the blank-line pattern sees simple `"\n \n"` runs.

`addresses(recipients)` lower-cases each To/Cc address; Outlook sends an entry either as a bare mailbox or wrapped in `"Mailbox"`, and `(r.get("Mailbox") or r)` handles both. `attachment_list(attachments)` keeps each file attachment's id, name, size, type and inline flag (never its content) and leaves out attached emails (`ItemAttachment`), which aren't files.

### `image_attachments(attachments)`
```
keep an attachment if:
    it's an image (content type image/*, or a .png/.jpg/.jpeg/.gif/.webp name)
    AND size ≥ 30 KB if inline, ≥ 15 KB if attached     (signature logos and icons are smaller)
    AND size ≤ 5 MB
    AND it still fits the 8 MB budget for this email
    AND it has an attachment id
stop at 4                                             (many endpoints refuse more images per prompt)
```

```python
# mailbrief/browser/owa_network.py::image_attachments
    keep, used = [], 0
    for a in attachments or []:
        name, ctype, size = a.get("Name") or "", a.get("ContentType") or "", a.get("Size") or 0
        is_image = ctype.startswith("image/") or name.lower().endswith(IMAGE_EXTS)
        low = INLINE_MIN if a.get("IsInline") else IMAGE_MIN
        if is_image and low <= size <= IMAGE_MAX and used + size <= IMAGE_BUDGET and _id(a.get("AttachmentId")):
            keep.append({"id": _id(a["AttachmentId"]), "name": name, "content_type": ctype, "size": size})
            used += size
            if len(keep) == IMAGES_PER_EMAIL:
                break
    return keep
```

- **`str.endswith` takes a tuple** (`IMAGE_EXTS`): true if the name ends with any of them. **`low <= size <= IMAGE_MAX`** is Python's chained comparison, the same as `low <= size and size <= IMAGE_MAX`.
- **Greedy, in order.** A 6 MB image that doesn't fit is skipped, and a smaller one after it can still go in. That isn't the "best" packing, but attachments come in the order the sender put them, which is usually the order of importance.
- **Why these numbers?** A structure-only look at real mail (sizes and flags, no content) found inline signature images under about 20 KB and inline posters of hundreds of KB and more, so 30 KB separates them with room to spare. Before M6b every inline image was skipped, which threw away the posters staff emails embed. The endpoint accepted 7.9 MB of synthetic images in one request, so 8 MB per email is safe. Posters over 5 MB are skipped rather than resized, because resizing needs an image library (Pillow). Every image costs AI time, so logos and pixels are worth keeping out.

### `image_urls(html)`
```
every <img src="…"> in page order, de-duplicated, kept only if:
    it starts with https://
    AND it has no query string            (tracking images usually carry one: open.gif?u=123)
    AND its name doesn't look like an icon (logo, icon, avatar, facebook, spacer, pixel, track…)
```

```python
# mailbrief/browser/owa_network.py::image_urls
    urls = []
# ...
        src = src.strip().replace("&amp;", "&")
        if src.lower().startswith("https://") and "?" not in src and not _SKIP_IMAGE.search(src) and src not in urls:
            urls.append(src)
    return urls
```

The elided line is the loop: `for src in re.findall(PATTERN, html or "", re.I):`, where `PATTERN` is `<img\b[^>]*?\bsrc\s*=\s*` followed by a quoted value (single or double quotes) captured as a group. (It's left out of the quote only because its brackets confuse this guide's link checker.)

**A regex, not an HTML parser.** It only needs `src` values from `<img>` tags, and email HTML is often broken in ways that trip strict parsers. `[^>]*?` skips other attributes without running past the end of the tag; `\b` stops `<imgx` matching; `re.I` ignores case. It will miss an unquoted `src=` and anything set by CSS. Those are rare in email, and a missed image only means one picture fewer. `&amp;` is undone because HTML escapes `&` in attributes. Name rules are a cheap first filter. Whatever slips through is caught by the size check in `web_images`.

### `preview_records(conversations)`
The fallback: one record per conversation, with the list preview as the body and `body_source = "preview"` so later code knows it isn't full text. It has every key `parse_items` produces (`is_read` is `None`: unknown), so no later code needs a special case.

### `find_user_email(payloads)`
Walks StartupData looking for `SessionSettings.UserEmailAddress`.

```python
# mailbrief/browser/owa_network.py::find_user_email
    stack = list(payloads)
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            settings = node.get("SessionSettings")
            if isinstance(settings, dict) and "@" in str(settings.get("UserEmailAddress", "")):
                return settings["UserEmailAddress"]
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None
```

**Why there?** Outlook's request headers identify you by an internal ID (a "PUID"), not your address, so the address had to be found elsewhere. A probe found it in the startup data. The `"@"` check skips an empty or placeholder value. Without an address the run still works; it just can't tell your replies apart.

### Categories and the write guard
The rest of the file builds and checks the only writes MailBrief makes: `update_categories_body`, `master_list_body`, `remove_everywhere_body`, `parse_categories`, `parse_update`, `master_categories`, and the guard `check_request`, which `_service_call` runs on every request. They are explained in [labels](05-labels-rules-extras.md).

### Rebuilding it
Input: parsed JSON (dicts and lists). Output: plain dicts in the shapes of [the overview](01-overview.md). It depends only on `re` and `datetime`. To adapt it to another provider, rewrite `_to_message` and `parse_items` for that provider's field names and keep the rest: the tree walk, the deduplication and the "skip what doesn't parse" rule carry over. Keep all format knowledge in this one file, so a format change is a one-file fix.

### Try it
`tests/test_owa_network.py`: `test_conversations`, `test_items_and_preference` (conversations win over items), `test_conversation_item_ids_and_preview_fallback`, `test_global_ids_and_user_email`, `test_parse_items`, `test_view_total`, `test_image_attachments_filter`, `test_image_urls_and_html_request`, and `test_garbage_is_ignored` (random junk must never crash the parser). The guard is tested in `tests/test_labels.py` (`test_built_requests_pass_the_guard`, `test_guard_refuses_everything_else`).

---

## `session/remote_login.py`
**The problem:** `login_once` needs a screen and a keyboard. A server (Railway, Render, Docker) has neither, and the login has to be renewed every few months.

**The idea:** run the browser on the server, and show *you* a picture of it in any browser, through a web page that lives only for the sign-in.
```
/login (your chat only)  or  mailbrief login --remote
  take the run lock                                    ← never two Chromiums; a run can't start mid-sign-in
  token ← 32 random bytes;  start a web server on $PORT (or reuse serve's, on Render)
  maybe start a cloudflared tunnel (LOGIN_TUNNEL=cloudflared, on your PC)
  headless Chromium, FRESH profile, phone-sized (480×860), user agent with "HeadlessChrome" → "Chrome"
  send you  https://<app>/login#<token>
  loop until signed in or 10 minutes pass:
      apply your queued taps / typing / keys;  screenshot → the page shows it every 0.5 s
      an inbox row is visible? → stop looping
  CHECK the new cookies in a second, separate context with open_outlook
  only if that shows the inbox → manager.save (with your address)
  stop the tunnel, the server and the browser          ← the link is dead
  tell you: signed in / didn't stick / timed out  (+ a warning if it's a different account)
```

The start of `run` is the first half of that flow: the lock, the window, and either serve's always-on server or a new one.

```python
# mailbrief/session/remote_login.py::run
    url = public_url()
    local = is_local(url)
    with lock("run"):
        win = Window(ttl, secure=not local)
        if _always is not None:  # Render: serve's server is already on the port; hand it this window
            server, _active = None, win
        else:
            server, url = listen(url, local, handler(win))
            threading.Thread(target=server.serve_forever, daemon=True).start()
```

`serve_forever` blocks, so it runs on its own daemon thread, and this thread goes on to drive the browser. `is_local` runs before the lock, so a plain-http `PUBLIC_URL` is refused before anything starts.

### The window: token, cookie, state
```python
# mailbrief/session/remote_login.py::Window
    def __init__(self, ttl: float = WINDOW_S, secure: bool = True):
        self.token = secrets.token_urlsafe(32)
        self.cookie: str | None = None
        self.expires = time.monotonic() + ttl
        self.secure = secure
        self.state = "open"  # open → done | failed (signed in, but it didn't stick) | expired (ran out of time)
        self.frame = b""
        self.hidden = False  # the browser is on Outlook itself: no picture
        self.inputs: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
# ...
    def bind(self, token) -> str | None:
        """The first correct token becomes a cookie; the token can never be used again."""
        with self._lock:
            if not self.live() or self.cookie or not isinstance(token, str) \
                    or not hmac.compare_digest(token.encode(), self.token.encode()):
                return None
            self.cookie = secrets.token_urlsafe(32)
            return self.cookie
```

- **The token is in the `#fragment`.** Browsers never send the fragment to the server, so the token can't appear in Railway's request logs, a proxy's logs or synced browser history. The page's own script reads it, then wipes it from the address bar (`history.replaceState`).
- **`secrets.token_urlsafe(32)`** is 32 bytes (256 bits) from the operating system's secure random source, written in URL-safe base64. Never use `random` for this: its output can be predicted.
- **`hmac.compare_digest`** compares in constant time. A plain `==` stops at the first wrong character, and in principle the timing tells an attacker how many characters were right.
- **The `threading.Lock`.** The web server answers each request on its own thread. Without the lock, two `POST /login` at the same moment could both see "no cookie yet" and both get one. With it, exactly one wins.
- **The token turns into a cookie, once.** `GET /login` only shows a Start button. The button **POSTs** the token, which burns it (`bind`) and sets a random cookie: `HttpOnly` (scripts can't read it), `SameSite=Strict` (other sites can't send it), and `Secure` on https. Every other route (`/frame`, `/input`, `/status`) needs that cookie. Link-preview bots only GET, so they can't burn the token, and a copied link is useless once you've tapped Start.
- **`state` is set from what happened, not from the clock:** `done` (saved and checked), `failed` (signed in, but the check failed), `expired` (never signed in). The page shows a different message for each.

### Checking every input
```python
# mailbrief/session/remote_login.py::parse_input
    kind = ev.get("type")
    if kind == "click":
        x, y = ev.get("x"), ev.get("y")
        if (isinstance(x, int) and not isinstance(x, bool) and isinstance(y, int) and not isinstance(y, bool)
                and 0 <= x < VIEW_W and 0 <= y < VIEW_H):
            return {"type": "click", "x": x, "y": y}
    elif kind == "text":
        text = ev.get("text")
        if isinstance(text, str) and 0 < len(text) <= MAX_TEXT:
            return {"type": "text", "text": text}
    elif kind == "key" and ev.get("key") in KEYS:
        return {"type": "key", "key": ev["key"]}
    return None
```

- A click must land inside the 480×860 viewport. **`not isinstance(x, bool)`** is there because in Python `True` *is* an `int` (`isinstance(True, int)` is `True`), and JSON `true` would otherwise pass as a click at 1.
- Typed text is at most 200 characters (`MAX_TEXT`), and a request body at most 1000 bytes (`MAX_BODY`).
- Keys come from a short allowlist: Enter, Tab, Backspace, Escape, ArrowUp, ArrowDown.
- The function builds a **new** dict from checked values, so no extra keys from the request survive.
- **Taps are scaled.** A phone shows the 480-pixel picture smaller. The page converts a tap with `x × naturalWidth / shownWidth` so it lands where you meant.
- The page has separate fields for email, password and a code, each with a "Type it" button and a "press Enter after typing" box, so the phone keyboard's Go key moves the sign-in on.

### The web server
```python
# mailbrief/session/remote_login.py::handler
        timeout = 10

        def log_message(self, *args):  # no request lines in any log
            pass

        def version_string(self) -> str:  # the Server header: don't name the software or the Python version
            return "web"
# ...
        do_HEAD = do_PUT = do_DELETE = do_OPTIONS = do_PATCH = lambda self: self._nope()
# ...
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
# ...
        def _body(self) -> bytes | None:
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return None
            body = self.rfile.read(size) if 0 < size <= MAX_BODY else None  # read first: unread bytes reset the connection
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return None  # forces a CORS preflight from any other site, which we never answer
            return body
# ...
                flags = "; HttpOnly; SameSite=Strict; Path=/" + ("; Secure" if win.secure else "")
                self._send(200, b"ok", headers={"Set-Cookie": f"{COOKIE}={cookie}{flags}"})
```

- **Why the stdlib `http.server`, not Flask or FastAPI?** It's four routes, used a few times a year. No new dependency, nothing extra to keep patched. The cost is doing by hand what a framework does for you, which is what this code is: the headers, the body size check, the error pages.
- **`handler(win)` returns a class.** `BaseHTTPRequestHandler` is instantiated by the server once per request, so it can't take your `Window` as an argument. Defining the class inside a function lets its methods see `win` through the closure. `win` may also be a function returning the open window, for the always-on server below.
- **`timeout = 10`.** The stdlib default is "wait forever". Without it, anyone could open idle connections, or send half a request, and pin a thread and a socket each.
- **Nothing names the software.** `version_string` hides the `Server: BaseHTTP/0.6 Python/3.11` header, `send_error` is overridden because the stdlib's HTML error pages name it too, and every other HTTP method gets the same 404. **A wrong token, a missing cookie and an unknown path all get the same 404.** A prober can't tell that a sign-in is open.
- **Headers on every reply:** `Cache-Control: no-store` (no screenshot or page in any cache), `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` (no hidden-frame tricks), `X-Content-Type-Options: nosniff`, and on the page a Content-Security-Policy that allows only this page's own script and style, by a random nonce per load.
- **`/input` and `/login` demand `Content-Type: application/json`.** A plain HTML form on another site can't send that without a CORS preflight (an `OPTIONS` request first), and the server answers `OPTIONS` with 404. The body is read *before* the check: unread bytes left on the socket make the connection reset, and the browser would show a network error instead of a clean 404.
- **https only.** `is_local` allows `http://` only for localhost, and then binds to 127.0.0.1. Anything else must be `https://`, or it raises `ValueError`, so the password never crosses the internet in clear text. On Railway the https is Railway's own; the app sits behind it.

```python
# mailbrief/session/remote_login.py::Server
class Server(ThreadingHTTPServer):
    # Windows' SO_REUSEADDR lets a second program bind a port already in use (and share its traffic): never there.
    allow_reuse_address = os.name != "nt"
    daemon_threads = True


def listen(url: str, local: bool, h) -> tuple[Server, str]:
    """The web server on $PORT. On this PC without PUBLIC_URL, a blocked port (Windows often reserves 8080) falls
    back to any free one, and the link says which. Raises OSError otherwise."""
    try:
        return Server(("127.0.0.1" if local else "0.0.0.0", port()), h), url
    except OSError:
        if not local or os.environ.get("PUBLIC_URL"):
            raise
        server = Server(("127.0.0.1", 0), h)
        return server, f"http://localhost:{server.server_address[1]}"
```

- **`ThreadingHTTPServer`** answers each request on a new thread, so a slow `/frame` doesn't hold up a tap. **`daemon_threads = True`** means those threads never keep the program alive after it's done.
- **`allow_reuse_address`** is the `SO_REUSEADDR` socket option. The stdlib's `HTTPServer` already turns it on; this line exists to turn it *off* on Windows. On Linux it lets a restarted server take its port back at once. On Windows it means something else and dangerous (two programs sharing one port).
- **Port 0** asks the operating system for any free port; `server_address[1]` says which one it gave. That fallback is only used on your PC with no `PUBLIC_URL`, where the link can simply say the new port. On a server, the port is fixed by the host, so failing loudly is right.

### Driving the browser
```python
# mailbrief/session/remote_login.py::drive
    while win.live():
        try:
            events = [win.inputs.get(timeout=step_s)]
        except queue.Empty:
            events = []
        while not win.inputs.empty():
            events.append(win.inputs.get_nowait())
        for ev in events:
            try:
                _apply(page, ev)
            except Exception:  # noqa: BLE001 - a tap mid-navigation can miss; you just tap again
                pass
        try:
            shot = page.screenshot(type="jpeg", quality=60)
            # checked after the shot, so one taken just as Outlook opened is dropped too. Not sticky: the first load
            # passes through Outlook on its way to the sign-in page.
            win.hidden = urlparse(page.url).hostname == OUTLOOK_HOST
            win.frame = b"" if win.hidden else shot
            if signed_in(page):
                return True
        except Exception:  # noqa: BLE001 - mid-navigation; the next round works
            pass
    return False
```

- **Threads.** **Playwright** is driven only from the thread that called `run`, because the sync API isn't thread-safe. **The web server's threads** only put events on a `queue.Queue` and read the latest screenshot bytes. `queue.Queue` is the stdlib's thread-safe hand-over; assigning `win.frame` a new `bytes` object is a single reference swap, so a reader sees the old picture or the new one, never half.
- **`inputs.get(timeout=0.5)`** waits for up to half a second, but returns at once when you tap. So taps feel immediate without a busy loop, and the picture still refreshes twice a second when you do nothing. Then `get_nowait()` collects any taps that arrived together.
- **JPEG at quality 60** keeps each 480×860 picture small (tens of KB, not the hundreds a PNG of the same page can take), so polling every half second works on a phone connection.
- **Your inbox is never shown.** Once the browser is on `outlook.office.com` itself, the picture is dropped: `/frame` gives 404 and the page says *"Opening your inbox… the picture is hidden"*. It checks the address *after* each screenshot, so one taken just as Outlook opened is dropped too. It isn't sticky, because the first load passes through Outlook on its way to the sign-in page.
- **"Done" means an inbox row is visible** (`signed_in` is `pg.locator(MESSAGE_ROW).count() > 0`), the same signal `open_outlook` waits for. It doesn't mean "the URL is Outlook": an organisation's sign-in hops through several hosts, and saving too early would save half the cookies.
- **The broad `except Exception`** is deliberate: during a page change, screenshots and clicks can fail for a moment, and the next round works. Ending the sign-in for that would be worse.

### Check, then save
```python
# mailbrief/session/remote_login.py::run
                    probe = browser.new_page()
                    ua = probe.evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome")
                    probe.close()
                    context = browser.new_context(viewport={"width": VIEW_W, "height": VIEW_H}, user_agent=ua)
                    page = context.new_page()
                    show_link(f"{url}/login#{win.token}")
                    page.goto(INBOX_URL, wait_until="domcontentloaded")
                    if drive(win, page, lambda pg: pg.locator(MESSAGE_ROW).count() > 0):
                        signed_in = True
                        page.wait_for_timeout(3000)  # let Outlook finish setting its cookies
                        # Checked from memory first: a sign-in that doesn't work must not replace a saved one that does.
                        check = browser.new_context(storage_state=context.storage_state(), user_agent=ua)
                        cp = check.new_page()  # open_outlook alone can't tell "stuck on a sign-in page" from "slow"
                        opened = open_outlook(cp)
                        ok = not opened["expired"] and cp.locator(MESSAGE_ROW).count() > 0
                        check.close()
                        if ok:
                            me, before = find_user_email(opened["startup"]), manager.account()
                            manager.save(context, ua, me)
                            other = me if before and me and before.lower() != me.lower() else None
                finally:
                    browser.close()
        finally:
            # From what happened, not from the clock: a check that fails just after the 10 minutes is still "failed".
            win.state = "done" if ok else "failed" if signed_in else "expired"
```

- **A fresh browser profile,** never the saved session. Even someone who did get in would see a Microsoft sign-in box, not your inbox.
- **The user agent.** A headless browser says `HeadlessChrome`; the probe page reads it and `.replace` makes it plain `Chrome`, the same identity every later run will use. A separate throw-away page is used so the real context can be created with that user agent from the start.
- **Checked from memory, then saved.** `context.storage_state()` is passed straight into a second, separate context, which opens Outlook as a run would. Only if that shows inbox rows is `manager.save` called. A sign-in that didn't stick (you didn't tick "Stay signed in", or your organisation refused the device) never replaces a saved session that still works. The old version saved first and checked after.
- **A different account is reported.** `manager.account()` is read before saving and compared with the new address. Your archive, labels and rules belong to the old mailbox, so you're told: "⚠️ This is a different account from before".
- **Nested `try/finally`.** The inner one always closes the browser; the outer one always sets the final state, waits 2 s (so the page's next poll shows the outcome), stops the tunnel and shuts the server. That is what makes the link die even if something in between raises.
- **The run lock** (`with lock("run")`) is taken around all of it. A scheduled run can't start while you sign in, and two Chromiums never compete for a small server's memory. If a run holds it, `run` raises `service.Busy` and you're told to try again in a minute.
- **Nothing is kept:** screenshots and keystrokes live in memory, the request log is switched off (`log_message`), and the bot logs only "sign-in page opened/closed".

### Hosting variations
- **Render needs a port open all the time** (a deploy without one fails). There, `serve` starts the same server once (`start_always`), with a handler that asks "which window is open?" (`lambda: _active`). With none, every path is 404, so the server says nothing about itself. `/login` sets `_active` for the 10 minutes instead of opening a new server. `always_bind` listens on every interface only when the page's address is https; with plain `http://localhost` it stays on 127.0.0.1. Railway and your PC keep the open-only-while-signing-in behaviour.
- **A tunnel from your PC (`LOGIN_TUNNEL=cloudflared`).** A `localhost` link doesn't open on your phone, so `tunnel()` starts a Cloudflare quick tunnel to the page and uses its `https://….trycloudflare.com` address instead. The page still binds 127.0.0.1, and the cookie gets `Secure` since the browser now sees https. Points to know:
  - **The pipe is drained all the time.** A thread keeps reading cloudflared's output for the whole run; a full pipe would freeze it.
  - **It waits for "Registered tunnel connection", then 10 more seconds.** A brand-new name takes a few seconds to reach DNS, and a lookup that comes too early is cached as "doesn't exist" for minutes. That happened on a campus resolver in testing.
  - **It points at `127.0.0.1`, not `localhost`,** because `localhost` can resolve to the IPv6 `::1`, where the page isn't listening.
  - **The process is stopped in the same `finally` that closes the server,** so the address dies with the window. A tested request afterwards gets Cloudflare's 502.
  - **It's opt-in,** because Cloudflare ends the https in the middle and so sees your password. Tailscale Serve is the private alternative: set `PUBLIC_URL` to its address.

```python
# mailbrief/session/remote_login.py::tunnel
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")
    lines: queue.Queue = queue.Queue()

    def read():  # keeps draining for the whole run: a full pipe would freeze cloudflared
        for line in proc.stderr:
            lines.put(line)
        lines.put(None)
```

`errors="replace"` means an odd byte in cloudflared's output becomes `?` instead of raising `UnicodeDecodeError` in the reader thread. The `None` at the end is a "pipe closed" marker: the waiting loop treats it as "cloudflared exited" and stops with a clear error.

`ponytail:` screenshots every half second, not a video stream. That's fine for something you do every few months; CDP's `Page.startScreencast` is the upgrade if it ever feels slow.

### Rebuilding it
Inputs: two callbacks, `show_link(url)` and `say(text)`, so the same code serves the chat bot (sends the link to Telegram) and the command line (prints it). Output: `True` if a working session was saved. It depends on `connect`, `outlook_reader.open_outlook`, `manager` and `service.lock`. To reuse it for another site: change `INBOX_URL`, the "signed in" test passed to `drive`, the check, and `OUTLOOK_HOST` (the host whose pictures are hidden). The security pieces (fragment token, one-time bind, cookie, input checks, same 404 everywhere, https only) carry over unchanged. They are the part worth copying.

### Try it
`tests/test_remote_login.py` runs the real server on a free local port with no browser:
`test_token_is_single_use_and_becomes_a_cookie`, `test_a_silent_connection_is_dropped`, `test_the_server_says_nothing_about_itself`, `test_input_checks`, `test_expired_window_is_dead`, `test_done_state_is_shown_then_frames_stop`, `test_drive_applies_inputs_until_signed_in`, `test_outlook_itself_is_never_shown`, `test_drive_stops_when_the_window_closes`, `test_urls`, `test_blocked_port_falls_back_only_on_this_pc`, `test_always_on_server_is_404_until_a_window_opens`, `test_render_address_and_switch`, `test_tunnel_reads_the_address_and_stops`, `test_tunnel_gives_up_cleanly`, `test_tunnel_is_opt_in`, `test_link_message_escapes`.
