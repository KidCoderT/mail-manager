# Delivery, the chat bot and the always-on service

<!-- TOC -->
**Contents**

- [`notify/telegram.py`](#notifytelegrampy)
   - [Sizing: how long is a message?](#sizing-how-long-is-a-message)
   - [`_api`: one API call](#_api-one-api-call)
   - [Splitting a long digest into messages](#splitting-a-long-digest-into-messages)
   - [Sending](#sending)
   - [Files and setup](#files-and-setup)
   - [Rebuilding it](#rebuilding-it)
   - [Try it](#try-it)
- [`notify/` and `destinations.py`](#notify-and-destinationspy)
   - [`notify/__init__.py`](#notify__init__py)
   - [`destinations.py`](#destinationspy)
   - [Rebuilding it](#rebuilding-it-1)
   - [Try it](#try-it-1)
- [`progress.py`](#progresspy)
   - [Lines and counters](#lines-and-counters)
   - [A spinner for one long job](#a-spinner-for-one-long-job)
   - [Rebuilding it](#rebuilding-it-2)
   - [Try it](#try-it-2)
- [`service.py`](#servicepy)
   - [The big decision: one long-running `serve`, everywhere](#the-big-decision-one-long-running-serve-everywhere)
   - [The schedule: parse once, then plain date arithmetic](#the-schedule-parse-once-then-plain-date-arithmetic)
   - [When is a run due?](#when-is-a-run-due)
   - [Locks: the OS remembers, so they can't go stale](#locks-the-os-remembers-so-they-cant-go-stale)
   - [State and the log](#state-and-the-log)
   - [The loop](#the-loop)
   - [Each run is a child process](#each-run-is-a-child-process)
   - [Retries and alerts](#retries-and-alerts)
   - [Stopping properly](#stopping-properly)
   - [Autostart on Windows](#autostart-on-windows)
   - [Hosting: the same `serve`, in a container](#hosting-the-same-serve-in-a-container)
   - [Rebuilding it](#rebuilding-it-3)
   - [Try it](#try-it-3)
- [`notify/bot.py`](#notifybotpy)
   - [Who may talk to it](#who-may-talk-to-it)
   - [The loop](#the-loop-1)
   - [Handling one update](#handling-one-update)
   - [Questions and attachment buttons](#questions-and-attachment-buttons)
   - [Commands](#commands)
   - [Starting it](#starting-it)
   - [Rebuilding it](#rebuilding-it-4)
   - [Try it](#try-it-4)
<!-- /TOC -->

## `notify/telegram.py`
**Job:** deliver the digest, alerts, chat replies and files to Telegram. It only *sends*. Reading incoming messages is `notify/bot.py`'s job (and `add-destination`'s, once, during setup).

Everything here talks to the [Telegram Bot API](https://core.telegram.org/bots/api): plain HTTPS POSTs to `https://api.telegram.org/bot<TOKEN>/<method>` with a JSON body, and a JSON reply `{"ok": true, "result": …}` or `{"ok": false, "description": "…"}`.

### Sizing: how long is a message?
```
LIMIT = 4000                       (Telegram allows 4096; the margin fits "· k/n" and "(cont.)")
size(text)      = UTF-16 length    (how Telegram counts: an emoji is 2)
visible(text)   = the text with HTML tags removed and &amp; etc. turned back into characters
html_size(text) = size(visible(text))      (in HTML mode Telegram counts what shows, not the markup)

is_heading(line):   UPPERCASE words like "NOISE", "KEY EVENTS", "DEADLINES & MEETINGS",
                    optionally "(a note)" and/or ":", and never a "•", "-" or "*" bullet
```

```python
# mailbrief/notify/telegram.py::LIMIT,size,visible,html_size,is_heading
LIMIT = 4000  # Telegram allows 4096 (UTF-16 units); the margin leaves room for "· k/n" and "(cont.)"
PAUSE_S = 0.5  # between messages, to stay under Telegram's flood control
RETRIES_429 = 3
# A section heading: uppercase words ("NOISE", "KEY EVENTS", "DEADLINES & MEETINGS"), optionally followed
# by a "(…)" note and/or ":". Bullets and normal sentences never match.
HEADING = re.compile(r"^[A-Z][A-Z0-9&/'’\- ]{2,}?(\s*\([^)]*\))?\s*:?$")
# ...
def size(text: str) -> int:
    """Length the way Telegram counts it: UTF-16 code units (an emoji counts as 2)."""
    return len(text.encode("utf-16-le")) // 2


def visible(text: str) -> str:
    """What an HTML-mode message shows: tags removed, &amp; etc. turned back into characters."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def html_size(text: str) -> int:
    """Telegram's limit counts the text after its HTML is parsed, so links don't use up room."""
    return size(visible(text))


def is_heading(line: str) -> bool:
    line = line.strip()
    return bool(line) and not line.startswith(("•", "-", "*")) and bool(HEADING.match(line))
```

**How it works and why it's written this way:**
- **`len(text.encode("utf-16-le")) // 2`.** Python's `len()` counts code points, so 📬 is 1. Telegram counts UTF-16 code units, where anything outside the Basic Multilingual Plane (most emoji) is a *surrogate pair*, 2 units. Encoding to UTF-16 and halving the byte count gives Telegram's number exactly. The `-le` matters: plain `"utf-16"` adds a 2-byte byte-order mark, which would make every count one too high.
- **Why the margin (4000, not 4096)?** The `· k/n` tag and the `HEADING (cont.)` line are added after a part is sized. 96 units is far more than they need, so a part can never go over after tagging. Counting Python characters instead of UTF-16 units once let a piece land just over the real limit, and Telegram rejected it.
- **`visible()` is a regex, not an HTML parser.** `<[^>]+>` removes any tag, then `html.unescape` turns `&amp;` back into `&`. This only works because *we* wrote the HTML (see `links.py`): every `<` that came from an email was escaped to `&lt;`, so the only real tags are ours. On arbitrary HTML a regex like this is fragile. Here it is enough and needs no dependency.
- **`HEADING`.** `^[A-Z]` then at least two more of uppercase, digits, `& / ' ’ -` and spaces. `{2,}?` is a *lazy* quantifier, so the optional `(\s*\([^)]*\))?` note and the `:` get a chance to match. The `’` (a curly apostrophe) is there because the AI writes "TODAY’S" as often as "TODAY'S".
- **Why check bullets separately?** `"- NOTE"` would match the regex (a dash is allowed inside), so `is_heading` refuses any line that starts with a bullet marker first.

### `_api`: one API call
```
_api(method, payload):
    no TELEGRAM_BOT_TOKEN → TelegramError (a setup message)
    POST https://api.telegram.org/bot<TOKEN>/<method>, JSON body, 30 s timeout   (never logged: the URL holds the token)
    on HTTP 429 (flood control): wait Telegram's retry_after + 1 seconds, retry (up to 3 times)
    on any other HTTP error: raise TelegramError("<code> <Telegram's description>")
```

```python
# mailbrief/notify/telegram.py::_api
def _api(method: str, payload: dict | None = None) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set (create a bot with @BotFather)")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"},
    )
    for attempt in range(RETRIES_429 + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # never log the URL: it contains the token
                return json.load(r)
        except urllib.error.HTTPError as e:
            # Telegram explains every error in a JSON body; keep its words instead of "HTTP Error 400".
            try:
                body = json.loads(e.read() or b"{}")
            except ValueError:
                body = {}
            wait = (body.get("parameters") or {}).get("retry_after")
            if e.code == 429 and wait and attempt < RETRIES_429:
                time.sleep(int(wait) + 1)  # flood control: Telegram says how long to wait
                continue
            raise TelegramError(f"{e.code} {body.get('description') or e.reason}") from None
    raise TelegramError("429 Too Many Requests (still rate-limited after retries)")
```

**How it works and why it's written this way:**
- **`urllib.request`, not `requests`.** The whole Telegram side needs one kind of call (POST JSON, read JSON). The standard library does that in a dozen lines, so there is no dependency to install, pin and audit. `requests` would be nicer to read and would give you retries and multipart for free. It wasn't worth a dependency for this.
- **`urllib.request.Request(url, data=...)`.** Passing `data` makes it a POST. `json.load(r)` reads the reply straight from the response stream.
- **`except urllib.error.HTTPError as e` then `e.read()`.** `urlopen` *raises* for any 4xx/5xx status. The exception object is also a response, so `e.read()` gets the body. Telegram puts its explanation there: "message is too long", "chat not found", "bot was blocked by the user". Each needs a different fix, and "HTTP Error 400" says nothing. The inner `try/except ValueError` handles a body that isn't JSON (a proxy's HTML error page).
- **`retry_after`.** On a 429 Telegram's body says `{"parameters": {"retry_after": 7}}`. Waiting exactly that long (plus a second) is better than guessing with exponential back-off. Only 429 is retried. A 400 will fail the same way every time, and a retry would just waste the wait.
- **`raise … from None`.** Without it, Python prints "During handling of the above exception, another exception occurred" and the whole `HTTPError` chain. `from None` keeps the error to one clear line. The `HTTPError` object also carries the URL (with the token) as an attribute, so not chaining it is one less way for the token to end up in a log.
- **`for attempt in range(RETRIES_429 + 1)` with a final `raise` after the loop.** The loop either returns, raises, or `continue`s after a 429. Falling out of the bottom means every attempt was rate-limited.
- **What it doesn't handle:** a network error (`URLError`, `TimeoutError`) is not caught here and goes to the caller. `send` doesn't catch it either, so a dead network fails the whole send. That is reasonable: if one message can't reach Telegram, the next won't either.

### Splitting a long digest into messages
```
messages(text, html_mode):
    measure ← html_size in HTML mode, else size
    fits in LIMIT → [text]                                   (the usual morning digest: one message)
    else:
        blocks ← split_sections(text)       a heading starts a new block (judged on its visible text);
                                            the "📬 …" header line joins the FIRST section (alone it would be noise)
        for each block:
            fits → one message
            else → split on line breaks into BALANCED parts (≈ equal sizes, each ≤ LIMIT);
                   parts after the first start with "<HEADING> (cont.)"   (HTML-escaped in HTML mode)
                   a single line longer than a message is the only thing ever cut mid-line,
                   and in HTML mode it is cut between links, tags and entities, never inside one
        more than one message → tag the first line of every message " · k/n"
```

```python
# mailbrief/notify/telegram.py::split_sections,messages
def split_sections(text: str) -> list[list[str]]:
    """Blocks of lines: the text before the first heading joins the first section; each heading starts a block."""
    blocks: list[list[str]] = [[]]
    seen_heading = False
    for line in text.splitlines():
        if is_heading(visible(line)):  # judged on what shows: an HTML heading line may carry a link
            if seen_heading:
                blocks.append([])
            seen_heading = True
        blocks[-1].append(line)
    return blocks
# ...
def messages(text: str, html_mode: bool = False) -> list[str]:
    """The Telegram messages for `text`: one if it fits, else one per section (split further if needed)."""
    text = text.strip()
    measure = html_size if html_mode else size
    if measure(text) <= LIMIT:
        return [text] if text else []
    out = [m for block in split_sections(text) for m in _chunk_block(_trim(block), measure)]
    if len(out) > 1:  # "· k/n" on each first line, so a missing part is obvious
        out = [m.replace("\n", f" · {k}/{len(out)}\n", 1) if "\n" in m else f"{m} · {k}/{len(out)}"
               for k, m in enumerate(out, 1)]
    return out
```

```python
# mailbrief/notify/telegram.py::_hard_cut,_chunk_block
# What an HTML line may be cut between: a whole link, any other tag, an entity (&amp;), or one character.
_HTML_ATOM = re.compile(r"<a\b[^>]*>.*?</a>|<[^>]+>|&[#\w]{1,10};|.", re.S)


def _hard_cut(line: str, limit: int, measure=size) -> list[str]:
    """Cut one overlong line into pieces of at most `limit` UTF-16 units (only for very odd output).
    HTML text is cut between links, tags and entities, never inside one: half an <a> makes Telegram refuse
    the message, and the plain-text resend would then show the broken tag."""
    pieces, current = [], ""
    for atom in _HTML_ATOM.findall(line) if measure is html_size else line:
        if current and measure(current + atom) > limit:
            pieces.append(current)
            current = ""
        current += atom
    return pieces + ([current] if current else [])
# ...
def _chunk_block(lines: list[str], measure=size) -> list[str]:
    """One block → messages ≤ LIMIT, split on line breaks; follow-ups start with '<HEADING> (cont.)'.
    `measure` is html_size for HTML text: lines are never cut inside a tag (only absurdly long ones are cut)."""
    heading = next((visible(l).strip() for l in lines if is_heading(visible(l))), None)
    cont = f"{heading.split('(')[0].rstrip(' :')} (cont.)" if heading else None
    if cont and measure is html_size:
        cont = html.escape(cont, quote=False)  # the copied heading is plain text; "&" must be "&amp;" here
    # Balanced, not greedy: 4100 units → two ~2050 messages, never 3990 + a lonely 110.
    pieces_needed = -(-measure("\n".join(lines)) // LIMIT)
    target = min(LIMIT, -(-measure("\n".join(lines)) // pieces_needed) + 200)
    chunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        for piece in (_hard_cut(line, LIMIT - 100, measure) if measure(line) > LIMIT - 100 else [line]):
            if current and measure("\n".join(current + [piece])) > target:
                chunks.append(current)
                current = [cont] if cont else []
            current.append(piece)
    if current:
        chunks.append(current)
    return ["\n".join(_trim(c)) for c in chunks if _trim(c)]
```

**How it works and why it's written this way:**
- **Why one message per section?** A digest cut wherever 4,096 characters happened to fall reads badly: a section starts at the bottom of one message and finishes at the top of the next. Sections are the natural reading units, so each gets its own message. That is easy to scroll and easy to find later ("where's the NOISE part?").
- **`blocks = [[]]` and `seen_heading`.** The list starts with one empty block, so lines before any heading (the `📬` header) have somewhere to go. The *first* heading doesn't open a new block. That is how the header line joins the first section instead of being sent alone.
- **Why balanced parts instead of filling each message?** Greedy filling turned a 4,100-unit section into a 3,990-unit message plus a lonely 110-unit "(cont.)". `-(-a // b)` is the integer *ceiling* of `a / b` (Python's `//` rounds down, so negating twice rounds up). `pieces_needed` is how many messages the block must become, and `target` is the even share, plus 200 units of slack so a long line near a boundary doesn't force an extra part. `min(LIMIT, …)` keeps the slack from ever passing the real limit.
- **Why split on lines?** Cutting mid-line would break a bullet in two. Line boundaries keep every bullet whole.
- **`_hard_cut` and `_HTML_ATOM`.** Only a single line longer than `LIMIT - 100` is cut. For plain text it walks character by character. For HTML, `_HTML_ATOM.findall` yields whole `<a …>…</a>` links, other tags, entities like `&amp;`, or single characters, and the cut only falls between atoms. Half an `<a href="…` makes Telegram refuse the message, and the plain-text fallback would then show the broken tag. The atom regex is tried left to right, so a link is matched whole before the "any tag" branch can grab just its opening tag. The cost is that this is O(n²) on one absurd line (it re-measures `current + atom` each time). Real digest lines are a few hundred characters, so it doesn't matter.
- **`measure is html_size`** compares *function objects*. One splitter serves both modes. The `measure` argument decides how to count, and the identity check decides whether the text is HTML. A boolean flag would have been as good. Passing the function avoids threading two parameters that must agree.
- **`html.escape(cont, quote=False)`.** The heading copied into "(cont.)" comes from `visible()`, so it's plain text. In HTML mode a `&` in it ("DEADLINES & MEETINGS") must go back to `&amp;`, or Telegram can't parse the message.
- **Why `· k/n`?** With five messages arriving together, a missing one is obvious at a glance. `m.replace("\n", …, 1)` puts the tag at the end of the first line only.

### Sending
```
send(chat_id, text, html=False, buttons=None):
    for each message from messages(text), 0.5 s apart:
        payload: chat_id, text, no link previews; HTML mode if asked;
                 buttons (an inline keyboard) on the LAST message only
        try to send
            HTML part Telegram can't parse → send the same words as plain text instead
        on failure remember "message k failed: <description>" and CONTINUE
    any failures → raise "sent 4/5; message 3 failed: …"
    else → return how many messages were sent
```

```python
# mailbrief/notify/telegram.py::send
def send(chat_id: str, text: str, html: bool = False, buttons: list | None = None) -> int:
    """Send every message (paced). Keeps going past a failure; raises a summary if any failed. Returns the count.
    html=True: Telegram's HTML mode (links); a part Telegram can't parse is resent as plain text instead.
    buttons: inline keyboard rows ([[{"text", "url" | "callback_data"}]]) under the last message."""
    parts = messages(text, html_mode=html)
    failures = []
    for k, part in enumerate(parts, 1):
        if k > 1:
            time.sleep(PAUSE_S)
        payload = {"chat_id": chat_id, "text": part, "disable_web_page_preview": True}
        if html:
            payload["parse_mode"] = "HTML"
        if buttons and k == len(parts):
            payload["reply_markup"] = {"inline_keyboard": buttons}
        try:
            try:
                _api("sendMessage", payload)
            except TelegramError as e:
                if not html or "parse" not in str(e).lower():
                    raise
                # Never lose the text over markup: same words, no links.
                _api("sendMessage", {**{k2: v for k2, v in payload.items() if k2 != "parse_mode"}, "text": visible(part)})
        except TelegramError as e:
            failures.append(f"message {k} failed: {e}")
    if failures:
        raise TelegramError(f"sent {len(parts) - len(failures)}/{len(parts)}; " + "; ".join(failures))
    return len(parts)
```

**How it works and why it's written this way:**
- **Why pacing and continuing past failures?** Several messages in a burst can trip Telegram's flood control. Half a second between them avoids most 429s, and `_api` handles the rest. If one message still fails, the others are still worth delivering. The summary says exactly which one failed and why.
- **The parse fallback.** In HTML mode, a stray `<` the escaping missed makes Telegram answer `400 Bad Request: can't parse entities`. The nested `try` catches exactly that ("parse" in the description) and resends `visible(part)`, which is the same words without links. Losing the links is better than losing the message. Any other error is re-raised to the outer `try`, which records it.
- **`{**{k2: v for … if k2 != "parse_mode"}, "text": …}`** builds a copy of the payload without `parse_mode` and with the plain text. The variable is `k2` because `k` is already the message number in the loop.
- **`disable_web_page_preview`.** Each digest bullet carries a link, and Telegram would otherwise put a big preview card under the message. Newer Bot API versions call this `link_preview_options`. The old name is still accepted.
- **`reply_markup: {"inline_keyboard": rows}`.** These are the buttons under a message: rows of `{"text", "url"}` or `{"text", "callback_data"}`. They go on the last part only, so they sit under the end of the answer.
- **Why does `send` raise instead of returning the failures?** The caller (`main.deliver`) treats a raised error as "this destination failed" and reports it. A partial send is a failure you should hear about. The message says how much did arrive.

### Files and setup
```
send_file(chat_id, name, content_type, data, caption=""):
    over 50 MB → TelegramError (the Bot API limit)
    a PNG/JPEG up to 10 MB → sendPhoto (shows inline); anything else → sendDocument
    build a multipart/form-data body by hand, from memory (the file never touches the disk)

find_chats():  getUpdates → chats that recently messaged the bot: [{id, label}]   (setup only)
```

```python
# mailbrief/notify/telegram.py::send_file
FILE_LIMIT = 50_000_000  # Telegram bots can send files up to 50 MB


def send_file(chat_id: str, name: str, content_type: str, data: bytes, caption: str = "") -> None:
    """Send a file from memory (never written to disk): images as photos, everything else as a document."""
    if len(data) > FILE_LIMIT:
        raise TelegramError(f"{name} is over Telegram's 50 MB limit for bots")
    photo = content_type in ("image/png", "image/jpeg") and len(data) <= 10_000_000  # sendPhoto: 10 MB max
    method, field = ("sendPhoto", "photo") if photo else ("sendDocument", "document")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
    boundary = f"----mailbrief{int(time.time() * 1000)}"
    safe_name = re.sub(r'["\r\n]', "_", name)
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode()]
    if caption:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{caption[:1000]}\r\n'.encode())
    parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{safe_name}"\r\n'
              f"Content-Type: {content_type or 'application/octet-stream'}\r\n\r\n".encode(), data,
              f"\r\n--{boundary}--\r\n".encode()]
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:  # never log the URL: it contains the token
            json.load(r)
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        raise TelegramError(f"{e.code} {body.get('description') or e.reason}") from None
```

```python
# mailbrief/notify/telegram.py::find_chats
def find_chats() -> list[dict]:
    """Chats that recently messaged the bot: [{id, label}]. Used once, during setup."""
    chats = {}
    for update in _api("getUpdates").get("result", []):
        chat = (update.get("message") or update.get("my_chat_member") or {}).get("chat")
        if chat:
            label = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username")
            chats[str(chat["id"])] = {"id": str(chat["id"]), "label": f"{label} ({chat.get('type')})"}
    return list(chats.values())
```

**How it works and why it's written this way:**
- **Uploading a file needs `multipart/form-data`**, the same encoding a browser uses for a file input. `urllib` has no helper for it, so the body is assembled by hand: each field is `--boundary`, a `Content-Disposition` header, a blank line, the value. The file part also has a `Content-Type`. The body ends with `--boundary--`. `requests` would do this with `files=`. Twenty lines of byte strings were cheaper than a dependency.
- **The boundary** is `----mailbrief<milliseconds>`. A boundary must not appear inside the data. A time-based string almost never will, but it's not guaranteed. A random one (`secrets.token_hex`) would be safer for the same cost.
- **`safe_name = re.sub(r'["\r\n]', "_", name)`.** The attachment name comes from an email, so it's untrusted. A `"` would end the `filename="…"` early, and a newline would let the name inject its own headers into the request. Replacing them closes both.
- **`caption[:1000]`.** Telegram allows 1,024 characters in a caption.
- **Why photos only up to 10 MB, and only PNG/JPEG?** That is `sendPhoto`'s limit and what it accepts. Telegram also recompresses photos. Anything else goes as a document, which arrives byte for byte.
- **`find_chats` reads `getUpdates` once**, during `add-destination`. A message from you to the bot shows up as an update with your chat id. `my_chat_member` updates cover being added to a group. The dict keyed by id removes duplicates.
- **Why only your registered chats count.** If anyone who sent `/start` could register, any stranger who found the bot could receive your digest. Registration happens only on your machine, through `add-destination`. The chat listener (`bot.py`) then answers only those chats. Disabling group joins in BotFather closes the last gap.

### Rebuilding it
- **Inputs:** a chat id, the text (plain or Telegram-HTML), optional buttons; a bot token in the environment.
- **Output:** the number of messages sent, or a `TelegramError` that says what failed.
- **Depends on:** only the standard library. `links.py` calls `is_heading` and `visible` from here, so headings are judged the same way everywhere.
- **Write it in this order:** `_api` (one POST, with Telegram's error text), then `send` for a short message, then `messages()` once you have a digest longer than 4,096. Get the UTF-16 count right first. It's the bug you won't see until an emoji-heavy day.
- **Adapting it:**
  - **Slack:** `chat.postMessage` with a bot token in an `Authorization: Bearer` header. The limit is about 40,000 characters, so splitting rarely matters, but Slack's markup is `<url|text>`, not HTML. You'd replace `links.to_html` with a Slack formatter.
  - **Discord:** a webhook URL takes `{"content": …}` up to 2,000 characters. The same `messages()` works with `LIMIT = 1900` and a `size` that counts code points.
  - **Email:** one message, no splitting. `smtplib` plus `email.message.EmailMessage`, with the HTML version as an alternative part.

### Try it
`tests/test_telegram.py`: `test_short_text_is_one_unchanged_message`, `test_long_digest_goes_one_message_per_section`, `test_oversize_section_splits_on_lines_with_cont`, `test_utf16_sizing_with_emoji`, `test_overlong_single_line_is_hard_cut`, `test_html_hard_cut_never_splits_a_link_or_an_entity`, `test_heading_detection`, `test_html_mode`, `test_send_html_buttons_and_parse_fallback`.

---

## `notify/` and `destinations.py`
**Job:** say *how* to reach each channel, and *where* digests go. (`notify/telegram.py`, the one channel so far, has its own section above.)

### `notify/__init__.py`
```
ADAPTERS = {"telegram": telegram.send}
deliver(text):  for each active destination → ADAPTERS[its type](target, text, html=…)
```

```python
# mailbrief/notify/__init__.py::ADAPTERS
from mailbrief.notify import telegram

# Add a channel: write send_<channel>(target, text) and register it here.
ADAPTERS = {"telegram": telegram.send}
```

`main.deliver` is the caller:

```python
# mailbrief/main.py::deliver
def deliver(text: str, log, html: bool = False) -> bool:
    """Send to every active destination; True if at least one got it. One failure never blocks the others.
    html=True: `text` is Telegram HTML (↗ links to the emails, see links.py)."""
    from mailbrief import destinations
    from mailbrief.notify import ADAPTERS

    targets = [d for d in destinations.load() if d["active"]]
    if not targets:
        print(
            "No destinations yet: run `mailbrief add-destination telegram`.", file=log
        )
        return False
    sent = 0
    for d in targets:
        try:
            n = ADAPTERS[d["type"]](d["target"], text, html=html)
            sent += 1
            print(
                f"Sent to {d['type']}: {d['label']} ({n} message{'s' if n != 1 else ''})",
                file=log,
            )
        except Exception as err:  # noqa: BLE001 - report and continue with the next destination
            print(
                f"Failed to send to {d['type']}: {d['label']} ({type(err).__name__}: {err})",
                file=log,
            )
    return sent > 0
```

**How it works and why it's written this way:**
- **Why a dictionary?** Adding WhatsApp or Slack later is one function plus one entry. No class hierarchy is needed for one method.
- **The real adapter contract** is `(target, text, html=False) -> int`: `deliver` passes `html=`, and prints the returned count (`Sent to telegram: Alex Tan (private) (5 messages)`). The comment in `__init__.py` still says `send_<channel>(target, text)`. A new adapter written to that comment would fail with `TypeError: unexpected keyword argument 'html'`, which `deliver` would report as a failed send.
- **`except Exception` per destination.** One broken channel must not block the others. `deliver` returns `True` if at least one got it, and the caller only advances the cursor then.
- **Resending:** `mailbrief emails --digest --send` hands the latest *saved* digest to the same `deliver()`. A month digest costs about 5 minutes of AI time. If sending failed, rewriting it would be waste: the text and its `refs` are already in the archive.

### `destinations.py`
```
load()                  → the list in data/destinations.json ([] if there's no file)
add(type, target, label) → re-adding the same (type, target) replaces it; new entries are active
```

```python
# mailbrief/destinations.py::load,add
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
```

**How it works and why it's written this way:**
- **A JSON file** because there is one user and a handful of entries. A list comprehension filters out the old entry, so `add` is also "update".
- **It's written only by the local CLI.** The bot reads it as its allowlist (`Bot.allowed`), so nothing that arrives over Telegram can add itself.
- **Honest limits:** `add` writes the file directly, not through the temp-file-and-rename (`storage.files.replace`) that every other data file uses. A crash mid-write could leave a broken file, and `load()` would then raise. It's written once at setup, so the risk is small. The `ponytail:` comment about moving to a table "in M5" is out of date: multi-user hosting was dropped, so this stays a file.

### Rebuilding it
A dictionary of `name → send function`, and a list of `{type, target, label, active}`. That's the whole delivery layer. To add a channel, write `send_slack(target, text, html=False) -> int` (convert or ignore `html`), add it to `ADAPTERS`, and add `"slack"` destinations with `add()`.

### Try it
There is no direct test of `deliver` itself. `tests/test_pipeline.py::test_failed_delivery_keeps_cursor` mocks it and shows what a failed delivery means for the cursor. `tests/test_bot.py::test_only_your_private_chats` shows the destinations file working as the bot's allowlist.

---

## `progress.py`
**Job:** show what the app is doing right now, so a long run never looks stuck.

It exists because of a real moment: `run --all --send` printed one line and then sat silent for over 15 minutes while it wrote a huge digest. From the outside, "working hard" and "hung" looked identical.

### Lines and counters
```
step(msg)               → "[00:12] Opening Outlook…"                one line, time since start
count(label, n, total)  → on a terminal: redraw ONE line in place   "[00:20] Fetching full text 120/366"
                          when piped:   print only at 25/50/75/100%
```

```python
# mailbrief/progress.py::OUT,_tty,_write,step,count
OUT = None  # tests swap in a StringIO; None = sys.stderr
START = time.monotonic()
SPINNER = "|/-\\"
_lock = threading.Lock()
_open_line = False  # a "\r" line is on screen and needs a newline before normal output
_quarters: dict[str, int] = {}


def _out():
    return OUT or sys.stderr


def _tty() -> bool:
    try:
        return _out().isatty()
    except (AttributeError, ValueError):
        return False


def _stamp() -> str:
    s = int(time.monotonic() - START)
    return f"[{s // 60:02d}:{s % 60:02d}]"


def _write(text: str, live: bool = False) -> None:
    """Print a line; `live` lines are redrawn in place on a terminal."""
    global _open_line
    with _lock:
        out = _out()
        if live:
            out.write("\r" + text + "   ")
            _open_line = True
        else:
            out.write(("\n" if _open_line else "") + text + "\n")
            _open_line = False
        out.flush()


def step(msg: str) -> None:
    """A phase starting: '[00:12] Loading Focused tab…'."""
    _write(f"{_stamp()} {msg}")


def count(label: str, n: int, total: int) -> None:
    """A counter: live on a terminal; every 25% (and at the end) when piped."""
    if total <= 0:
        return
    line = f"{_stamp()} {label} {n}/{total}"
    if _tty():
        _write(line, live=n < total)
        return
    quarter = 4 * n // total
    if n >= total or quarter > _quarters.get(label, 0):
        _quarters[label] = quarter
        _write(line)
```

**How it works and why it's written this way:**
- **Everything goes to stderr.** `run --json` promises pure JSON on stdout. Progress is about the run, not its result, which is exactly what stderr is for. `OUT` lets tests swap in a `StringIO`.
- **`time.monotonic()`, not `time.time()`.** The monotonic clock never jumps backwards when the wall clock is corrected, so elapsed times stay right. `START` is set when the module is imported, which is about when the program starts.
- **The terminal check (`isatty`).** Redrawing a line uses `\r` (carriage return: jump back to the start of the line). In a terminal that animates nicely. In a log file every redraw would be saved as junk. So on a terminal it's live, and when piped it prints plain lines at 25% steps. A scheduled job's log stays readable (verified: zero mid-line `\r` in a real log). `_tty` catches `AttributeError` and `ValueError` (a closed stream) and says "not a terminal".
- **`4 * n // total`** is which quarter we're in (0 to 4). A line is printed only when the quarter goes up, or at the end. `_quarters` remembers the last quarter per label.
- **The trailing `"   "` on live lines** overwrites leftovers when a new line is shorter than the old one ("9/10" after "10/10" would otherwise leave a stray character).
- **One lock around writing.** The spinner thread and the main thread both print. The lock stops their output interleaving mid-line. `_open_line` remembers that a `\r` line is on screen, so the next normal line starts on a fresh line.
- **Honest limits:**
  - `_quarters` is never reset, so the same label counted twice in one process prints only its final line the second time.
  - Under `pythonw` (Windows autostart), `sys.stderr` is `None`. `_tty` copes with that, but `_write` calls `out.write` on `None` and raises `AttributeError`. Runs are child processes started with `python.exe`, so they're fine. The chat thread inside `serve` is not: opening Outlook for an attachment button calls `progress.step`, which fails there. That's a real bug, reported rather than fixed.

### A spinner for one long job
```
working(label)          → a context ("with" block) around one long job:
    on a terminal: a background thread redraws "| label (part 3/6)… 23s" every 0.2 s
    when piped:    "label…" at the start
    at the end:    "✓ label (41s)", or "✗ label (41s)" if the job raised an error
    .note(text)    → extra live detail, e.g. "(part 3/6)" / "(merging 6 parts)"
```

```python
# mailbrief/progress.py::_Working,working
class _Working:
    def __init__(self, label: str):
        self.label, self.detail, self.t0 = label, "", time.monotonic()

    def note(self, detail: str) -> None:
        """Extra live detail, e.g. 'part 7/15' (shown on a terminal only)."""
        self.detail = detail

    def _line(self, frame: str) -> str:
        detail = f" {self.detail}" if self.detail else ""
        return f"{frame} {self.label}{detail}… {int(time.monotonic() - self.t0)}s"


@contextmanager
def working(label: str):
    """A long single job (an AI call): spinner + elapsed seconds on a terminal, then '✓ label (41s)'."""
    w = _Working(label)
    stop = threading.Event()
    spinner = None
    if _tty():
        def spin():
            i = 0
            while not stop.wait(0.2):
                _write(w._line(SPINNER[i % len(SPINNER)]), live=True)
                i += 1
        spinner = threading.Thread(target=spin, daemon=True)
        spinner.start()
    else:
        _write(f"{_stamp()} {label}…")
    mark = "✗"
    try:
        yield w
        mark = "✓"
    finally:
        stop.set()
        if spinner:
            spinner.join()
        _write(f"{_stamp()} {mark} {label} ({int(time.monotonic() - w.t0)}s)")
```

**How it works and why it's written this way:**
- **`@contextmanager`** turns a generator into a `with` block. Code before `yield` runs on entry, the `yield w` hands the caller its object (`with progress.working("Writing the digest") as w:`), and the `finally` runs on exit, however the block ends.
- **A spinner thread for single long calls.** A counter can't move while you wait on *one* AI call that takes 40 s. A small background thread redrawing elapsed seconds proves the program is alive.
- **`stop.wait(0.2)` instead of `time.sleep(0.2)`.** `Event.wait` returns `True` the moment the event is set, so the spinner stops at once instead of finishing its sleep. `while not stop.wait(0.2)` reads as "every 0.2 s until told to stop".
- **`daemon=True`** means a stuck spinner can't keep Python alive at exit. `spinner.join()` in `finally` waits for it, so its last redraw can't land after the ✓ line.
- **✗ on failure.** `mark` starts as ✗ and becomes ✓ only after `yield` returns normally. If the block raised, the `finally` prints ✗ and the exception carries on. A ✓ printed by a `finally` alone would lie when something crashed.
- **Plain ASCII spinner (`|/-\`).** It renders in every Windows terminal. The ✓ and ✗ marks are safe because `main()` makes stderr UTF-8.

### Rebuilding it
- **Where it's called:** the reader (Opening, Signed in, Loading the inbox list, Fetching full text, Fetching images) and `main.run` (Loading saved emails, Classifying n/N, Saving, the digest spinner, Sending). The modules call it directly. It's one small module with no setup, so threading a callback through every function would add code for no benefit. The trade-off: it's global state, which is why tests reset `OUT`.
- **To write it yourself:** three functions and one lock. Decide terminal versus pipe once per line with `isatty()`. If you want a library, `rich.progress` or `tqdm` do the same with more polish, and both also detect pipes.

### Try it
`tests/test_progress.py`: `test_step_is_one_timestamped_line`, `test_count_when_piped_prints_quarters_only`, `test_working_when_piped_prints_start_and_done`, `test_working_marks_failure`.

---

## `service.py`
**Job:** run MailBrief by itself, on a schedule. Start, stop and check on it, and do it the same way on your PC and on a server.

### The big decision: one long-running `serve`, everywhere
There were two ways to make it "run every morning":
1. Ask the operating system to launch `run` at 07:30 (a Task Scheduler time trigger, or cron on Linux).
2. Keep one program running that watches the clock and launches `run` itself.

MailBrief uses **option 2, `mailbrief serve`**, started by Task Scheduler **at logon** on Windows, or by Docker on a server. Why:
- **One mental model.** Hosting means "a constantly running app" (that's what a container is), and option 2 *is* that. With option 1 you'd learn two systems: Task Scheduler time triggers on the PC, something else on the server.
- **The schedule is ours.** `RUN_AT="daily 07:30; sun 20:00 this-week; day-1 09:00 last-month"` can say things like "a weekly summary on Sundays", with a different digest per entry. Task Scheduler and cron can't attach a digest scope to a time without a separate task per line.
- **Start / stop / status are ours** too, and identical everywhere.
- **The chat bot needs a long-running process anyway.** `serve` hosts it as a thread.

The cost is one idle Python process (a few MB of RAM, asleep almost all the time), and a scheduler you have to get right yourself. Most of the fixes listed in this section's history (DST, retries, catch-up) are bugs cron would never have had.

### The schedule: parse once, then plain date arithmetic
```
parse_schedule("daily 07:30; sun 20:00 this-week")
  → [ {weekdays: Mon..Sun, monthdays: {}, at: 07:30, scope: new},
      {weekdays: {Sun},    monthdays: {}, at: 20:00, scope: this-week} ]
  each entry: "<days> <HH:MM> [scope]"; days = daily | weekdays | weekends | mon..sun | day-N, comma-separated
  anything else → ValueError naming the bad entry   (serve refuses to start: a typo must not mean "never runs")
```

```python
# mailbrief/service.py::parse_schedule
DATA = Path("data")
STATE_PATH = DATA / "schedule.json"
STOP_PATH = DATA / "stop.request"
LOG_DIR = DATA / "logs"
DEFAULT_SCHEDULE = "daily 07:30"
SCOPES = ("new", "this-week", "this-month", "last-month", "older", "all")
TICK_S = 30  # how often the clock is checked; checking (not one long sleep) survives the PC sleeping
RUN_TIMEOUT_S = 45 * 60  # a run that takes longer is stuck: kill it and retry
RETRY_S = 15 * 60
MAX_ATTEMPTS = 3
LOOKBACK_DAYS = 35  # far enough back to find a missed monthly ("day-1") slot
TASK_NAME = "MailBrief"
DAY_NAMES = {d: i for i, d in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}
DAY_GROUPS = {"daily": set(range(7)), "weekdays": set(range(5)), "weekends": {5, 6}}
# ...
def parse_schedule(text: str) -> list[dict]:
    """'daily 07:30; sun 20:00 this-week' → [{weekdays, monthdays, at, scope}, …]. Raises ValueError with the bad entry."""
    entries = []
    for raw in (text or "").split(";"):
        parts = raw.split()
        if not parts:
            continue
        if len(parts) not in (2, 3):
            raise ValueError(f"{raw.strip()!r}: expected '<days> <HH:MM> [scope]'")
        weekdays, monthdays = set(), set()
        for day in parts[0].lower().split(","):
            if day in DAY_GROUPS:
                weekdays |= DAY_GROUPS[day]
            elif day in DAY_NAMES:
                weekdays.add(DAY_NAMES[day])
            elif (m := re.fullmatch(r"day-(\d{1,2})", day)) and 1 <= int(m[1]) <= 31:
                monthdays.add(int(m[1]))
            else:
                raise ValueError(f"{raw.strip()!r}: unknown day {day!r} (daily, weekdays, weekends, mon…sun, day-N)")
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", parts[1])
        if not m or int(m[1]) > 23 or int(m[2]) > 59:
            raise ValueError(f"{raw.strip()!r}: time must look like 07:30")
        scope = parts[2].lower() if len(parts) == 3 else "new"
        if scope not in SCOPES:
            raise ValueError(f"{raw.strip()!r}: scope must be one of {', '.join(SCOPES)}")
        entries.append({"weekdays": weekdays, "monthdays": monthdays, "at": clock(int(m[1]), int(m[2])), "scope": scope})
    if not entries:
        raise ValueError("the schedule is empty")
    return entries
```

**How it works and why it's written this way:**
- **Days are numbers.** `date.weekday()` gives Monday = 0 … Sunday = 6, so `DAY_NAMES` maps `"mon"` to 0 with `enumerate`, and the groups are sets of those numbers. `weekdays |= …` is set union, so `"mon,weekends"` is `{0, 5, 6}`.
- **`(m := re.fullmatch(…))`** is the walrus operator: assign and test in one expression. `fullmatch` (not `match`) means `day-1x` fails instead of matching its first part. `m[1]` is the same as `m.group(1)`.
- **`time as clock`.** `datetime.time` is imported under another name because the module also uses the `time` module for sleeping.
- **Why strict?** Every error names the entry and says what was expected. A schedule that silently drops a bad entry would look like it works and then never run.
- **`day-31`** is accepted and simply doesn't fire in shorter months. That's honest behaviour, but surprising. "Last day of the month" would need a new keyword.

### When is a run due?
```
_slots(schedule, start, end)   → every (time, scope) the schedule fires in (start, end]
                                 walk the days; an entry fires on a day if the weekday OR the day-of-month matches
due_slots(now, schedule, last_done)
    → start = the later of last_done and 35 days ago, converted to now's time zone
    → the slots in (start, now], keeping only the LATEST per scope
next_slot(now, schedule)       → the earliest slot after now   (for "next run: …")
run_args(scope, at)            → new: run --send --quiet --commit
                                 others: run --send --quiet --digest <scope> --as-of <the slot's date>
```

```python
# mailbrief/service.py::_slots,due_slots,next_slot,run_args
def _slots(schedule: list[dict], start: datetime, end: datetime):
    """Every (time, scope) the schedule fires in (start, end]. Times carry start's timezone."""
    day = start.date()
    while day <= end.date():
        for e in schedule:
            if day.weekday() in e["weekdays"] or day.day in e["monthdays"]:
                at = datetime.combine(day, e["at"], tzinfo=start.tzinfo)
                if start < at <= end:
                    yield at, e["scope"]
        day += timedelta(days=1)


def due_slots(now: datetime, schedule: list[dict], last_done: datetime) -> list[tuple[datetime, str]]:
    """Slots missed since last_done, keeping only the latest per scope (3 days off → one 'new' digest, not 3)."""
    # In now's zone: last_done comes from ISO text with a fixed offset, which is an hour out after a clock change.
    start = max(last_done, now - timedelta(days=LOOKBACK_DAYS)).astimezone(now.tzinfo)
    latest: dict[str, datetime] = {}
    for at, scope in _slots(schedule, start, now):
        latest[scope] = max(at, latest.get(scope, at))
    return sorted((at, scope) for scope, at in latest.items())


def next_slot(now: datetime, schedule: list[dict]) -> datetime | None:
    return min((at for at, _ in _slots(schedule, now, now + timedelta(days=LOOKBACK_DAYS))), default=None)


def run_args(scope: str, at: datetime | None = None) -> list[str]:
    """'new' advances the cursor; a period summary doesn't, so it never swallows emails the next daily digest needs.
    A period summary gets its slot's date: caught up a day late, 'this-week' must still mean the slot's week."""
    if scope == "new":
        return ["run", "--send", "--quiet", "--commit"]
    return ["run", "--send", "--quiet", "--digest", scope] + (["--as-of", at.date().isoformat()] if at else [])
```

**How it works and why it's written this way:**
- **`_slots` is a generator** (`yield`). It produces slots one at a time, and `due_slots` and `next_slot` each consume them differently. Walking day by day is simple and obviously right. A 35-day walk is 35 iterations, so cleverness would buy nothing.
- **`datetime.combine(day, e["at"], tzinfo=start.tzinfo)`** builds "that day at 07:30" in the same time zone as `start`. With a `zoneinfo.ZoneInfo` zone, Python works out the right UTC offset for *that* date, so 07:30 stays 07:30 local on both sides of a daylight-saving change.
- **The DST fix: `.astimezone(now.tzinfo)`.** `last_done` is saved as ISO text, like `2026-03-28T07:30:00+01:00`. Parsed back, it has a *fixed* `+01:00` offset, not the named zone. Slots built with that tzinfo were an hour off after the clocks changed. Converting to `now`'s zone (a real `ZoneInfo`) first means every slot is built in the real local zone.
- **Why "latest per scope"?** If the laptop was closed for three days, three morning digests are due. But a `new` digest covers *everything since the cursor*, so one run covers all three days. Running it three times would send one full digest and two empty ones. A weekly `this-week` slot is a different scope, so it still gets its own run.
- **Why `last_done` and not "did it run today?"** One timestamp handles every schedule shape (twice a day, weekly, monthly) and every gap (one hour asleep or a month away) with the same comparison. The look-back is capped at 35 days (`LOOKBACK_DAYS`), enough to find a missed monthly slot.
- **`min(…, default=None)`** returns `None` instead of raising when nothing fires in the next 35 days (a `day-31` schedule in February, say).
- **Why only `new` entries use `--commit`?** `--commit` advances the cursor ("these emails are done"). If the Sunday weekly summary committed, Monday's morning digest would skip Sunday afternoon's mail: it would have been "done" by a summary that may have mentioned it in one line. Period digests read the archive and leave the cursor alone.
- **Why `--as-of`?** A Sunday `this-week` slot caught up on Monday used to count "this week" from Monday, find nothing, and be marked done. The slot's own date now travels with it, so a late weekly digest still covers its own week.

### Locks: the OS remembers, so they can't go stale
```
with lock("run"):  → open data/run.lock and ask the OS for an exclusive lock on it, without waiting
                     (msvcrt.locking on Windows, fcntl.flock on Linux)
                     not available → Busy
is_locked(name)    → try the lock: got it → False (and release it at once); Busy → True
```

```python
# mailbrief/service.py::lock,is_locked
@contextmanager
def lock(name: str):
    """An OS lock on data/<name>.lock. The OS drops it when the process dies, so it can never go stale."""
    DATA.mkdir(exist_ok=True)
    f = open(DATA / f"{name}.lock", "a+")
    try:
        try:
            if sys.platform == "win32":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Busy(name) from None
        yield
    finally:
        f.close()


def is_locked(name: str) -> bool:
    try:
        with lock(name):
            return False
    except Busy:
        return True
```

**How it works and why it's written this way:**
- `run` holds `run.lock`: a scheduled run and a run you typed can't overlap. Overlapping runs would fight over the cursor and archive, and send two digests. Labelling, attachment fetches and remote login take it too, so Outlook is never driven twice at once.
- `serve` holds `serve.lock`: two services would fire every run twice. `mailbrief bot` takes it as well, because two listeners would fight over `getUpdates`.
- `status` and `stop` find out "is serve running?" by *trying* the lock.
- **`LK_NBLCK` and `LOCK_NB`** mean "non-blocking": fail at once instead of waiting. Waiting would make a second `serve` hang silently.
- **Windows locks a byte range.** `msvcrt.locking(fd, mode, 1)` locks one byte from the current position, so `f.seek(0)` first makes every process lock the *same* byte. The file is opened `"a+"` so it is created if missing and never truncated.
- **`f.close()` in `finally` releases the lock.** The `yield` inside `try` means the lock is held for exactly the `with` block.
- **Why not a PID file** (write "I'm process 1234" to a file, delete it on exit)? Because a crash, kill or power cut never deletes it. Then you'd need "is 1234 still alive, and is it really us?" checks, which are full of traps. On Windows even the obvious check, `os.kill(pid, 0)`, sends a Ctrl+C. An OS lock is **released by the OS when the process ends, however it ends**. There's never a stale lock to clean up.
- **The limit:** these are advisory locks on a local disk. They work between processes on one machine, which is the only case here. On a network share they're unreliable.

### State and the log
```
load_state()  → data/schedule.json, or {} if it's missing or broken
save_state()  → write a temp file, then replace; never raises (a warning in the log instead)
log(msg)      → "2026-10-18 07:30:02 msg" appended to data/logs/YYYY-MM.log, and printed if there's a screen
```

```python
# mailbrief/service.py::load_state,save_state,log
def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def save_state(state: dict) -> None:
    """Never raises: schedule.json is bookkeeping, and a write that fails must not take `serve` down."""
    try:
        DATA.mkdir(exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        replace(tmp, STATE_PATH)
    except OSError as e:
        log(f"warning: schedule.json not saved ({type(e).__name__}); trying again at the next change")


def _tz():
    from mailbrief.main import _tz
    return _tz()


def log_path() -> Path:
    return LOG_DIR / f"{datetime.now(_tz()):%Y-%m}.log"


def log(msg: str) -> None:
    """A timestamped line in data/logs/YYYY-MM.log, and on screen when there is one."""
    line = f"{datetime.now(_tz()):%Y-%m-%d %H:%M:%S} {msg}"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with log_path().open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    if sys.stdout:  # None under pythonw (autostart): no screen, the log is enough
        print(line, flush=True)
```

**How it works and why it's written this way:**
- **`save_state` never raises.** On Windows, `os.replace` fails with `PermissionError` while another process has the file open (a virus scanner, say). `storage.files.replace` retries for about 3 s. If it still fails, losing one bookkeeping write is far better than crashing the service.
- **`if sys.stdout`.** Under `pythonw` there is no console and `sys.stdout` is `None`. Printing would raise, so the log file is the only output.
- **One log file per month** keeps files small and makes "delete old logs" a matter of deleting files.

### The loop
```
serve(spec):
    schedule ← parse_schedule(spec)                       bad → ValueError before anything starts
    hold the "serve" lock                                 already held → "already running", exit 3
    state ← data/schedule.json; first start → last_done = now   (no catch-up on the very first start)
    on Ctrl+C / SIGTERM / Ctrl+Break: set "stopping" (a second Ctrl+C → stop immediately)
    open the web port if hosting needs one; start the chat bot thread (unless CHAT=off)
    loop until stopping (or data/stop.request appears):
        due ← due_slots(now, schedule, last_done) minus ones already done this round
        if due and not waiting for a retry:
            for each due slot: run it as a child process; log "run finished: ok in 40s"
                exit 2 (login expired) → Telegram alert (once a day), counts as done
                exit 0 or 4 → done
            all done → last_done ← the latest slot done this round
            3 attempts used → the same, plus a Telegram "gave up" alert (once a day)
            otherwise → retry in 15 min
        else:
            log "next run: Sun 18 Oct 07:30" (only when it changes)
            sleep 30 × 1 s, checking for a stop request every second
    a /sync run still going → wait for it
```

```python
# mailbrief/service.py::serve,_serve
def serve(spec: str) -> int:
    schedule = parse_schedule(spec)  # bad schedules fail before anything starts
    try:
        with lock("serve"):
            return _serve(spec, schedule)
    except Busy:
        print("MailBrief is already running (see `mailbrief status`; stop it with `mailbrief stop`).")
        return 3


def _serve(spec: str, schedule: list[dict]) -> int:
    tz = _tz()
    STOP_PATH.unlink(missing_ok=True)
    state = load_state()
    state.setdefault("last_done", datetime.now(tz).isoformat())  # first start: no catch-up, wait for the next slot
    state.update(schedule=spec, pid=os.getpid(), started=datetime.now(tz).isoformat())
    save_state(state)

    stopping = threading.Event()

    def on_signal(signum, frame):
        if stopping.is_set():
            raise KeyboardInterrupt  # asked twice: stop immediately
        stopping.set()
        log("stop requested: finishing up (press Ctrl+C again to stop immediately)")

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):  # Ctrl+C · docker stop · Ctrl+Break / console closed
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), on_signal)

    def stop_wanted() -> bool:
        if STOP_PATH.exists() and not stopping.is_set():
            stopping.set()
            log("stop requested by `mailbrief stop`")
        return stopping.is_set()

    log(f"MailBrief service started (pid {os.getpid()}), schedule: {spec}")
    from mailbrief.notify import bot
# ...
    if bot.start(stopping):  # Telegram chat (M7) in a thread; CHAT=off or no token: send-only, as before
        log("chat: on (only your registered private chats get answers)")
    announced, retry_at, attempts, done_now = None, None, 0, set()
    try:
        while not stop_wanted():
            now = datetime.now(tz)
            due = [s for s in due_slots(now, schedule, datetime.fromisoformat(state["last_done"])) if s not in done_now]
            if due and (retry_at is None or now >= retry_at):
                attempts += 1
                for at, scope in due:
                    log(f"run started ({scope}, slot {at:%a %d %b %H:%M})")
                    t0 = time.monotonic()
                    code = _run_child(scope, at)
                    secs = int(time.monotonic() - t0)
                    result = {0: "ok", 2: "login needed", 4: "sent, but not marked processed (cursor kept)"}.get(code, f"failed (exit {code})")
                    log(f"run finished: {result} in {secs}s")
                    state["last_run"] = {"at": datetime.now(tz).isoformat(), "scope": scope, "result": result, "seconds": secs}
                    if code == 2:
                        _alert_login(state)  # not retried: only you can log in again
                    if code in (0, 2, 4):  # 4: digest already sent; retrying would only send it again
                        done_now.add((at, scope))
                    if stopping.is_set():
                        break
                complete = all(s in done_now for s in due)
                if complete or (attempts >= MAX_ATTEMPTS and not stopping.is_set()):
                    if not complete:
                        log(f"giving up on this slot after {MAX_ATTEMPTS} attempts; the next scheduled run goes ahead as normal")
                        _alert_failed(state, result)
                    # done_now too: `due` holds only what was left for this attempt, and a slot that already
                    # succeeded on an earlier attempt may be the latest one (else it would fire again)
                    state["last_done"] = max(at for at, _ in [*due, *done_now]).isoformat()
                    retry_at, attempts, done_now = None, 0, set()
                elif not stopping.is_set():  # stopping with work left: the next start catches up instead
                    retry_at = datetime.now(tz) + timedelta(seconds=RETRY_S)
                    log(f"will retry at {retry_at:%H:%M} (attempt {attempts + 1} of {MAX_ATTEMPTS})")
                save_state(state)
                continue
            upcoming = retry_at or next_slot(now, schedule)
            if upcoming != announced:
                announced = upcoming
                state["next"] = upcoming.isoformat() if upcoming else None
                save_state(state)
                log(f"next run: {upcoming:%a %d %b %H:%M}" if upcoming else "nothing scheduled in the next 35 days")
            for _ in range(TICK_S):  # short sleeps: a stop request is noticed within a second
                if stop_wanted():
                    break
                time.sleep(1)
        if _children:  # a /sync run (bot thread): it would outlive serve, without its 45-minute limit
            log("waiting for the /sync run to finish (press Ctrl+C again to stop it now)")
            while _children:
                time.sleep(1)
    except KeyboardInterrupt:
        for proc in list(_children):
            proc.kill()
        log("stopped immediately")
        return 130
    finally:
        STOP_PATH.unlink(missing_ok=True)
        state.update(pid=None, next=None)
        save_state(state)
    log("MailBrief service stopped")
    return 0
```

**How it works and why it's written this way:**
- **`threading.Event` as the "stopping" flag.** It's a thread-safe boolean. The signal handler sets it, the loop checks it, and the bot thread gets the same object so it stops too.
- **`signal.signal(…, on_signal)`** replaces Python's default handler. Python's default for SIGINT raises `KeyboardInterrupt` wherever the code happens to be, which could be in the middle of a run. The custom handler only sets the flag the first time, and raises `KeyboardInterrupt` itself the second time ("I really mean it"). `hasattr(signal, name)` skips signals the platform doesn't have: SIGBREAK exists only on Windows.
- **Why check every 30 s instead of sleeping until 07:30?** A laptop that sleeps from 23:00 to 08:00 would wake up with `sleep()` still counting. Depending on the OS, the program might not notice it was late until far after. Re-reading the wall clock every 30 s means it notices within half a minute of waking. The cost is nothing: one date comparison.
- **Why sleep in 1-second steps?** So `mailbrief stop` (which just creates a file) is noticed within a second, not after up to 30.
- **`done_now`** is the set of slots that succeeded during this round of attempts. If `new` fails and `this-week` succeeds, the retry runs only `new`. `last_done` then takes the latest of *both* `due` and `done_now`. Using only the slots left for the last attempt once set `last_done` before the weekly slot, and the weekly digest was sent again.
- **`continue` after a round** skips the sleep and goes straight back to the top, so a retry or the next due slot is looked at with a fresh `now`.
- **`state.setdefault("last_done", now)`.** With no `last_done` yet, "missed" has no meaning. Starting the service for the first time shouldn't fire off a run unasked.
- **The `finally`** removes the stop file and clears `pid` and `next`, so `status` doesn't show a dead service as running. It runs on a normal stop, a double Ctrl+C, or a crash.
- **Waiting for `_children`.** A `/sync` from the chat runs a child process from the bot thread. If `serve` exited without waiting, that run would carry on with no 45-minute limit. So `serve` waits, and a second Ctrl+C kills it.

### Each run is a child process
`serve` doesn't call `run()` directly. It starts `python -m mailbrief.main run --send --quiet …` as a **separate process**.

```
_run_child(scope, at):
    start python -m mailbrief.main run … in its own process group, no window, stdin closed
    a reader thread copies each output line, indented, into the log (and the screen)
    wait in 1 s steps; over 45 minutes → kill it, exit code -1
    a second Ctrl+C → kill it and pass the interrupt on
    return the exit code
```

```python
# mailbrief/service.py::_python,_run_child
def _python() -> str:
    exe = Path(sys.executable)
    return str(exe.with_name("python.exe")) if exe.name.lower() == "pythonw.exe" else str(exe)


def _run_child(scope: str, at: datetime | None = None) -> int:
    """One scheduled run as a child process; its output goes to the log (and the screen). Returns its exit code."""
    cmd = [_python(), "-m", "mailbrief.main", *run_args(scope, at)]
    extra: dict[str, Any]
    if sys.platform == "win32":  # own process group: your Ctrl+C reaches serve only, which lets the run finish
        extra = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    else:
        extra = {"start_new_session": True}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, **extra)
    _children.add(proc)  # serve waits for (or kills) these when it stops, /sync runs included

    def copy_output():
        with log_path().open("a", encoding="utf-8") as f:
            for raw in proc.stdout:
                line = "    " + raw.decode("utf-8", "replace").rstrip()
                f.write(line + "\n")
                f.flush()
                if sys.stdout:
                    print(line, flush=True)

    reader = threading.Thread(target=copy_output, daemon=True)
    reader.start()
    t0 = time.monotonic()
    try:
        while True:
            try:
                code = proc.wait(timeout=1)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() - t0 > RUN_TIMEOUT_S:
                    proc.kill()
                    proc.wait()
                    log(f"run took over {RUN_TIMEOUT_S // 60} min and was stopped")
                    code = -1
                    break
    except KeyboardInterrupt:  # second Ctrl+C: stop now, run included
        proc.kill()
        raise
    finally:
        _children.discard(proc)
    reader.join(timeout=5)
    return code


_children: set = set()  # runs started by _run_child that haven't finished
```

**How it works and why it's written this way:**
- **Isolation.** A run drives a whole browser and makes dozens of network calls. If any of that crashes, hangs or leaks memory, it dies with the child. `serve` keeps going, and the next run starts fresh.
- **A hard timeout is possible.** You can't safely kill a function running inside your own process, but you can kill a process. A run taking over 45 minutes is stuck, so it's killed and retried.
- **The exit code is the result.** `run` already returns meaningful codes: 0 ok, 1 not delivered, 2 login needed, 3 another run going, 4 sent but the cursor kept, 5 Outlook opened but its inbox list couldn't be read. `serve` just reads them. No new interface was needed.
- **`subprocess.Popen`, not `subprocess.run`.** `run` waits until the child finishes, with no way to watch the clock or react to Ctrl+C meanwhile. `Popen` starts it and returns. `proc.wait(timeout=1)` then waits one second at a time and raises `TimeoutExpired` when the child is still going, which is the moment to check the 45-minute limit.
- **`stdout=PIPE, stderr=STDOUT`** merges both streams into one pipe, so progress lines (stderr) and results (stdout) stay in order in the log. `stdin=DEVNULL` means a run can never sit waiting for keyboard input that will never come.
- **The reader thread.** A pipe has a small buffer. If nobody reads it, the child blocks on its next `print` and looks hung. A daemon thread reads line by line and writes each to the log at once. `raw.decode("utf-8", "replace")` turns any bad byte into `�` instead of crashing the reader. `PYTHONIOENCODING=utf-8` makes the child write UTF-8 even on a Windows console set to cp1252.
- **Its own process group** (`CREATE_NEW_PROCESS_GROUP` on Windows, `start_new_session` on Linux). Ctrl+C in a terminal is delivered to the whole group, so without this it would hit the run in the middle of a step. With its own group, only `serve` hears Ctrl+C, and `serve` decides to *let the run finish*.
- **No flashing window** (`CREATE_NO_WINDOW`), and `_python()` uses `python.exe` even when `serve` is `pythonw.exe`, so the child has real output streams to log.
- **`_children`** is a set of running children. `/sync` and scheduled runs both register here, so shutdown can wait for or kill all of them.
- **Its output is logged without content.** Scheduled runs pass **`--quiet`**, which leaves out the per-email lines and the digest text. The log keeps timings, counts, progress and results, enough to debug, but **no subjects or bodies**. The archive is encrypted, and a plain-text log full of subjects would quietly undo that.

### Retries and alerts
```
_alert(state, key, text):  already sent today under this key → nothing
                           else deliver(text) to every destination; remember today if it arrived
login expired (exit 2)     → "the Outlook login has expired … send /login" (or `mailbrief login` without the bot)
gave up after 3 attempts   → "the scheduled run failed 3 times (<last result>) … `mailbrief status`"
```

```python
# mailbrief/service.py::_alert,_alert_login,_alert_failed
def _alert(state: dict, key: str, text: str) -> None:
    """Tell the destinations something only you can fix, at most once a day per kind (`key` in schedule.json)."""
    today = datetime.now(_tz()).date().isoformat()
    if state.get(key) == today:
        return
    from mailbrief.main import deliver

    out = io.StringIO()
    try:
        if deliver(text, out):
            state[key] = today
    except Exception as e:  # noqa: BLE001 - an alert that can't be sent must never stop the service
        log(f"alert not sent ({type(e).__name__})")
    for line in out.getvalue().splitlines():
        log(line)


def _alert_login(state: dict) -> None:
    """The Outlook login needs renewing (unattended runs can't ask)."""
    from mailbrief.notify import bot

    how = "send /login here to sign in again" if bot.enabled() else "run `mailbrief login`"
    _alert(state, "alert_day", f"⚠️ MailBrief: the Outlook login has expired, so no digest until you {how}.")


def _alert_failed(state: dict, result: str) -> None:
    """A slot was given up on: without this, a broken install looks exactly like a day with no mail."""
    _alert(state, "fail_alert_day", f"⚠️ MailBrief: the scheduled run failed {MAX_ATTEMPTS} times ({result}), so there's "
           "no digest this time. On the machine it runs on: `mailbrief status`, then the log file it names.")
```

**How it works and why it's written this way:**
- **Exit 1, 3 or 5, or a timeout:** worth retrying. Typical causes are no network yet after waking, a run you started by hand still going, or Outlook loading slowly. So it retries in 15 min, up to 3 attempts, then moves on to the next scheduled time.
- **When it gives up it sends one Telegram message** (at most once a day) naming the last result. Silence should mean "no new mail", never "broken". Before this, giving up only wrote to the log, so a broken install and a quiet day looked the same on your phone.
- **Exit 4** (digest sent, but the cursor kept because only previews were available, or the archive couldn't be saved): treated as done. A retry would only send the same digest again.
- **Exit 2 (login expired):** retrying can't help, because only you can log in. An unattended service that just logs "login needed" would leave you wondering why the digests stopped. So it sends a Telegram message, **at most once a day** (remembered in `schedule.json`), so a week of failed runs doesn't spam you. With the chat bot on, the message tells you to send `/login`.
- **`deliver(text, out)` into a `StringIO`.** `deliver` prints "Sent to …" lines. Capturing them and passing each to `log` puts them in the log file with timestamps. The `except Exception` is deliberate: an alert that can't be sent must never stop the service.
- **Imports inside functions** (`from mailbrief.main import deliver`). `main` imports `service`, so a top-level import back would be circular. Importing at call time breaks the cycle. The cost is that a typo in the import only shows up when the alert fires; tests cover these paths.

### Stopping properly
| Signal | Where it comes from |
|---|---|
| SIGINT | Ctrl+C in the terminal |
| SIGTERM | `docker stop` / `docker compose down` |
| SIGBREAK | Ctrl+Break, or closing the console window (Windows) |
| `data/stop.request` | `mailbrief stop`, which works even when there's no console (autostart) |

```
stop():  serve not running → say so
         create data/stop.request, then check the lock once a second for 10 s
         still locked → "it's finishing the current run"
```

```python
# mailbrief/service.py::stop
def stop(wait_s: int = 10) -> int:
    if not is_locked("serve"):
        print("MailBrief isn't running.")
        return 0
    STOP_PATH.parent.mkdir(exist_ok=True)
    STOP_PATH.write_text("")
    print("Stop requested…")
    for _ in range(wait_s):
        time.sleep(1)
        if not is_locked("serve"):
            print("MailBrief stopped.")
            return 0
    print("It's finishing the current run and will stop when that's done (check with `mailbrief status`).")
    return 0
```

All four just set one flag, `stopping`. The loop checks it:
- **between runs**, it exits at once;
- **during a run**, it waits for the child to finish (save, digest, send, cursor), then exits;
- a **second** Ctrl+C means "now": the child is killed and `serve` exits with 130 (the shell convention for "ended by Ctrl+C", 128 + SIGINT's number 2).

**Why a file instead of a signal for `mailbrief stop`?** On Windows, `os.kill(pid, signal.SIGTERM)` kills the process outright, with no chance to finish the run, and Ctrl+C events can only be sent to processes sharing a console. A file in `data/` works the same on every OS and needs no process id.

**Why is even killing it safe?** Two decisions from earlier milestones pay off here:
1. **Atomic writes:** every file is written to `.tmp` and then renamed. A file is either the old version or the new one, never half.
2. **The cursor only moves after delivery:** if a run dies before that point, the next run simply redoes the same emails (saved emails skip the AI).

The only imperfect case is a kill between "digest sent" and "cursor saved": you'd get that digest twice. That's a fair price for never losing an email.

### Autostart on Windows
`mailbrief autostart on` asks PowerShell's `Register-ScheduledTask` for a task:
```
trigger:   at logon of you
action:    .venv\Scripts\pythonw.exe -m mailbrief.main serve
start in:  the project folder              ← data/ and .env paths are relative to it
settings:  run on battery, no time limit, ignore a second start, restart up to 3 times 5 minutes apart
```

```python
# mailbrief/service.py::autostart
def autostart(on: bool) -> int:
    """Windows Task Scheduler task 'MailBrief': at logon, start `serve` hidden (pythonw: no window)."""
    if os.name != "nt":
        print("autostart is for Windows. On a server, run it with Docker (see commands.md, 'Hosting').")
        return 2
    if not on:
        if not _task_exists():
            print("Autostart is already off.")
            return 0
        ps = f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false"
    else:
        root = Path(__file__).resolve().parents[1]  # the project folder: data/ and .env live here
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        q = lambda p: str(p).replace("'", "''")  # noqa: E731 - PowerShell single-quote escaping
        ps = (f"$a = New-ScheduledTaskAction -Execute '{q(pythonw)}' -Argument '-m mailbrief.main serve' "
              f"-WorkingDirectory '{q(root)}'; "
              "$t = New-ScheduledTaskTrigger -AtLogOn -User \"$env:USERDOMAIN\\$env:USERNAME\"; "
              "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
              "-ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew "
              "-RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5); "
              f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $a -Trigger $t -Settings $s "
              "-Description 'MailBrief: scheduled email digests (mailbrief serve)' -Force | Out-Null")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Task Scheduler refused: {r.stderr.strip() or r.stdout.strip()}")
        return 1
    if on:
        print(f"Autostart on: MailBrief starts hidden each time you log in to Windows.\n"
              f"Start it now without logging out: schtasks /Run /TN {TASK_NAME}")
    else:
        print("Autostart off." + (" It's still running now; stop it with `mailbrief stop`." if is_locked("serve") else ""))
    return 0
```

**How it works and why it's written this way:**
- **Why PowerShell and not `schtasks /Create`?** `schtasks` can't set "run on battery" or "no time limit". The `ScheduledTasks` PowerShell cmdlets can. `subprocess.run([...], capture_output=True, text=True)` runs it and collects any error text to show you.
- **`q = lambda p: str(p).replace("'", "''")`.** Inside a PowerShell single-quoted string, a `'` is written `''`. A project folder like `C:\Users\o'brien\…` would otherwise break the command, or worse, let the path inject PowerShell.
- **`-ExecutionTimeLimit ([TimeSpan]::Zero)`** means "no limit". The default kills a task after 3 days, which would stop a service. **`-MultipleInstances IgnoreNew`** stops a second copy at the Task Scheduler level, and `serve.lock` stops it anyway. **`-RestartCount 3`** brings it back if it crashes.
- **Why `pythonw.exe`?** It's Python without a console window, so there's no black box on your screen all day. The catch: there's no stdout. `print` goes nowhere, and `sys.stdout.reconfigure(...)` would crash because `sys.stdout` is `None`. So `main()` skips the reconfigure when there's no stream, and `serve` writes everything to its log file.
- **Why at logon, not at boot?** It runs **as you**: your user environment variables (an `AI_API_KEY` set in Windows, say) and your files. A boot-time task would need your Windows password stored in Task Scheduler, or would run as a system account that doesn't have them. The cost: nothing runs until you log in.
- **Why the working directory matters:** paths like `data/session.enc` are relative. Started from `C:\Windows\System32`, it would look for your session there. `Path(__file__).resolve().parents[1]` is the project folder, found from where this file lives.

### Hosting: the same `serve`, in a container
```
Dockerfile:   python:3.11-slim + uv (pinned) + locked dependencies + Chromium (playwright install --with-deps)
              runs as user "app" (uid 1000), not root
              CMD mailbrief serve
compose.yaml: restart: unless-stopped   → always on: back after crashes and reboots, until you `down` it
              env_file: .env            → secrets come in at runtime…
              volumes: ./data           → …and so does the data: neither is ever inside the image
              shm_size: 1gb             → Chromium crashes with Docker's tiny 64 MB default
.dockerignore: .env, data/, out.json    → the build can't accidentally copy them in
```

```yaml
# compose.yaml
services:
  mailbrief:
    build: .
    restart: unless-stopped   # always on: back after a crash or a server reboot, until you `down` it
    init: true                # a tiny PID 1 that passes `docker stop` (SIGTERM) on to serve
    stop_grace_period: 10m    # time for a run in progress to finish before Docker force-kills
    env_file: .env            # must hold AI_API_KEY too (on your PC it may be a Windows variable instead)
    environment:
      TZ: Asia/Singapore
    volumes:
      - ./data:/app/data      # session.enc, archive, cursor, logs: survive rebuilds
    # ports: ["127.0.0.1:8080:8080"]   # /login sign-in page: put an https proxy/tunnel in front, set PUBLIC_URL
    shm_size: 1gb             # Chromium needs more shared memory than Docker's 64 MB default
```

- **Why does Docker get `stop_grace_period: 10m`?** `docker stop` sends SIGTERM, waits (10 s by default), then force-kills. Ten minutes lets a run in progress finish.
- **Why `init: true`?** It adds a tiny first process (PID 1) that passes the signal on to `serve`. Linux gives PID 1 no default signal behaviour. `serve` installs its own SIGTERM handler, so it would hear the signal anyway. The init's other job matters more here: it reaps finished child processes, and Chromium leaves plenty of them.
- **Why build our own image** rather than use Microsoft's Playwright image? Theirs is published per Playwright version, and there isn't one for the 1.64 we use yet. Installing Chromium ourselves with `playwright install --with-deps` always matches the locked version.
- **Why can't the server log in by itself?** `login` needs a visible browser and you at the keyboard (MFA). So you either log in on your PC and copy `data/session.enc` across, with the **same** `SESSION_ENCRYPTION_KEY`, or send `/login` to the bot, which opens a one-time sign-in page. The Telegram alert tells you when it's time.

### Rebuilding it
- **Inputs:** a schedule string, the clock, `data/schedule.json`. **Outputs:** child processes, log lines, alerts. **Depends on:** `main` (for `deliver` and `_tz`), `notify.bot` (the chat thread), `storage.files.replace`.
- **Build it in this order:** `parse_schedule` and `_slots` (pure functions, easy to test with fixed datetimes), then `lock`, then `_run_child`, then the loop. Test the date maths with real `ZoneInfo` zones on both sides of a DST change; that's where the bugs were.
- **Adapting it:**
  - **A different schedule:** add a keyword to `DAY_GROUPS` (`"fortnightly"` would need a reference date, which this shape doesn't have). For something like cron syntax, the `croniter` library returns the next fire time and could replace `_slots`.
  - **Use the OS scheduler after all:** delete the loop and keep `run` with its exit codes. Cron or Task Scheduler then runs `mailbrief run --send --commit` at 07:30. You lose catch-up and the bot thread.
  - **systemd on Linux instead of Docker:** a unit file with `ExecStart=… mailbrief serve`, `Restart=always`, `KillSignal=SIGTERM` and `TimeoutStopSec=10min` gives the same behaviour.

### Try it
- `tests/test_service.py`: `test_parse_every_form`, `test_parse_rejects_bad_entries`, `test_due_slots_daily_and_catch_up_latest_only`, `test_due_slots_per_scope_weekly_and_monthly`, `test_weekends_and_next_slot`, `test_due_slots_survive_a_clock_change`, `test_run_args_commit_only_for_new`, `test_lock_is_exclusive_and_released`.
- `tests/test_service_retry.py::test_retry_does_not_repeat_a_successful_later_slot`.
- `tests/test_main.py::test_caught_up_digest_excludes_mail_after_the_slot_day` (the `--as-of` side).
- `tests/test_files.py::test_replace_waits_out_a_file_another_process_has_open`.

---

## `notify/bot.py`
**Job:** the Telegram side of the chat. It runs as a thread inside `serve`, or as `mailbrief bot` on its own.

### Who may talk to it
```
enabled()      → CHAT isn't "off" and there is a bot token
allowed(chat)  → a PRIVATE chat whose id is an active telegram destination; everything else → False
```

```python
# mailbrief/notify/bot.py::enabled,Bot.allowed
def enabled() -> bool:
    return os.environ.get("CHAT", "on").strip().lower() not in ("off", "0", "false", "no") \
        and bool(os.environ.get("TELEGRAM_BOT_TOKEN"))
# ...
    @staticmethod
    def allowed(chat: dict | None) -> bool:
        from mailbrief import destinations

        if not chat or chat.get("type") != "private":
            return False
        return any(d["type"] == "telegram" and d["active"] and str(d["target"]) == str(chat.get("id"))
                   for d in destinations.load())
```

**How it works and why it's written this way:**
- **The allowlist** is the destinations file, written only by the local CLI. A stranger who finds the bot gets no reply, so they can't even tell it's alive.
- **Only private chats.** In a group, every member would see your email answers. A group whose id happened to be a destination is still refused.
- **`str(d["target"]) == str(chat.get("id"))`.** Telegram sends ids as numbers, the file stores strings. Comparing both as strings avoids a silent mismatch.
- **It re-reads the file for every update.** That's a small JSON file, and it means a destination you add or deactivate takes effect without a restart.

### The loop
```
run(stop):
    setMyCommands (the "/" menu); failure is fine
    until stop:
        poll_once()
        409 (another getUpdates is running, e.g. add-destination) → wait 30 s
        any other error → wait 10 s; the listener never dies

poll_once():
    getUpdates(timeout 20 s, offset, only messages and button taps)
    got some → offset ← last id + 1, and CONFIRM it at once with a quick getUpdates(offset, timeout 0)
    for each update: not an allowed chat → count it, ignore it; else handle it
    log "ignored N message(s)" (counts only)
```

```python
# mailbrief/notify/bot.py::Bot.poll_once,Bot.run
    def poll_once(self) -> int:
        payload = {"timeout": POLL_S, "allowed_updates": ["message", "callback_query"]}
        if self.offset is not None:
            payload["offset"] = self.offset
        updates = self.api("getUpdates", payload).get("result", [])
        ignored = 0
        if updates:
            # Tell Telegram these are taken BEFORE acting on them. It only forgets a batch when the next call
            # names a higher offset, so a restart right after /sync or /login would otherwise run them again.
            self.offset = updates[-1]["update_id"] + 1
            try:
                self.api("getUpdates", {"offset": self.offset, "timeout": 0, "limit": 1,
                                        "allowed_updates": payload["allowed_updates"]})
            except Exception:  # noqa: BLE001 - the next poll confirms them anyway
                pass
        for u in updates:
            chat = (u.get("message") or (u.get("callback_query") or {}).get("message") or {}).get("chat")
            if chat is None or not self.allowed(chat):
                ignored += 1
                continue
            self.handle(u)
        if ignored:
            _log(f"ignored {ignored} message(s) from chats that aren't your destinations")
        return len(updates)

    def run(self, stop: threading.Event) -> None:
        try:
            self.api("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in COMMANDS]})
        except Exception:  # noqa: BLE001 - the menu is a nicety
            pass
        _log("listening")
        while not stop.is_set():
            try:
                self.poll_once()
            except telegram.TelegramError as e:
                if str(e).startswith("409"):  # someone else is polling (add-destination?): give them room
                    _log("another getUpdates is running (409); retrying in 30s")
                    stop.wait(30)
                else:
                    _log(f"poll failed ({e}); retrying in 10s")
                    stop.wait(10)
            except Exception as e:  # noqa: BLE001 - network blips: never let the listener die
                _log(f"poll failed ({type(e).__name__}); retrying in 10s")
                stop.wait(10)
        _log("stopped")
```

**How it works and why it's written this way:**
- **Long-polling instead of a webhook.** `getUpdates` with `timeout: 20` holds the HTTP request open until a message arrives or 20 s pass. That gives near-instant replies with no open port, no public address and no certificate, so it works on a home PC. A webhook (Telegram POSTs to you) needs all three. `_api`'s 30 s socket timeout is longer than the 20 s poll, so a quiet poll returns normally instead of timing out.
- **The offset is Telegram's acknowledgement.** Telegram keeps returning an update until a later call asks for `offset` greater than its id. The early confirm (`timeout: 0, limit: 1`) tells Telegram right away. Before this, a restart right after `/sync`, `/login` or `/rule add` got the same update again and ran it twice. The trade-off: if the bot crashes *while* handling a message, that message is lost rather than repeated. For commands that start runs, "at most once" is the right side to fail on.
- **`allowed_updates`** asks Telegram for only messages and button taps, not edits, reactions or member changes.
- **`stop.wait(30)`, not `time.sleep(30)`.** It returns early when `serve` is stopping, so shutdown isn't held up by a back-off.
- **Plain Python instead of a bot library.** The popular libraries (`python-telegram-bot`, `aiogram`) are asyncio-based, and Playwright's sync API (used to fetch attachments) refuses to run inside an asyncio loop. They also want the main thread and the stop signals, which `serve` already owns. We need a handful of API calls on top of the existing tested sender.
- **Injected `api`, `ask`, `fetch_files`, `run_sync`, `login`.** The constructor takes each outside dependency as an optional argument. Tests pass fakes and get a bot that never touches the network. Production passes nothing and gets the real ones.

### Handling one update
```
handle(update):
    a button tap → allowed chat? → _button
    a message from an allowed chat:
        no text (photo, voice, sticker) → "I can only read text for now…"
        "/…"  → command          text → question
        ConfigError (a missing key in .env) → "MailBrief isn't set up for that: …"
        any other error → "Sorry, that failed: <why(e)>"   (the bot keeps going)
```

```python
# mailbrief/notify/bot.py::Bot.handle
    def handle(self, update: dict) -> None:
        if "callback_query" in update:
            q = update["callback_query"]
            chat = (q.get("message") or {}).get("chat")
            if chat is None or not self.allowed(chat):
                return
            self._button(str(chat["id"]), q)
            return
        msg = update.get("message") or {}
        chat = msg.get("chat")
        if chat is None or not self.allowed(chat):
            return  # strangers and groups learn nothing, not even that the bot is alive
        text = (msg.get("text") or "").strip()
        chat_id = str(chat["id"])
        if not text:  # a photo, voice note, sticker, file…
            self.say(chat_id, "I can only read text for now: type your question, or /help for what I can do.")
            return
        try:
            if text.startswith("/"):
                self._command(chat_id, text)
            else:
                self._question(chat_id, text)
        except ConfigError as e:  # a missing key in .env: only you can fix it, so say which
            _log("failed (setup)")
            self.say(chat_id, f"MailBrief isn't set up for that: {e}")
        except Exception as e:  # noqa: BLE001 - one bad message must not stop the bot
            _log(f"failed ({type(e).__name__})")
            self.say(chat_id, f"Sorry, that failed: {why(e)}")
```

```python
# mailbrief/notify/bot.py::why
def why(e: Exception) -> str:
    """An error in plain words with a next step, for a chat reply: you can't read the server's log from a phone.
    Never includes email content (only the kind of failure)."""
    import urllib.error

    from mailbrief import archive, labels

    if isinstance(e, labels.LoginNeeded):
        return "Outlook needs you to sign in again. Send /login."
    if isinstance(e, archive.ArchiveError):
        return f"the saved emails couldn't be read ({e})."
    if isinstance(e, urllib.error.HTTPError):
        return f"the AI endpoint refused the request (HTTP {e.code}). Check the AI settings in .env."
    if isinstance(e, (TimeoutError, urllib.error.URLError, ConnectionError)):
        return "the AI didn't answer (it may be busy or unreachable). Try again in a minute."
    if isinstance(e, telegram.TelegramError):
        return f"Telegram refused it ({e})."
    return (f"something unexpected went wrong ({type(e).__name__}). Try again, or /new to start fresh; the details "
            "are in the log on the machine MailBrief runs on.")
```

**How it works and why it's written this way:**
- **Never dies:** each update is handled inside a `try`. One bad message must not stop the bot.
- **`ConfigError` is caught first.** A missing key used to raise `SystemExit`, which is *not* an `Exception`, so it went past the `except` and silently killed the listener thread. Now it's a normal exception with a message only you can act on.
- **`why(e)`** turns an exception into a sentence with a next step: you can't read the server's log from your phone. It uses only the exception's *type* and code, never its content, so no email text can leak into a reply.
- **A reply to a photo.** Ignoring it made the bot look broken. One line explains what it can do.

### Questions and attachment buttons
```
question(text):
    a "typing…" indicator every 4.5 s while the answer is written (its own thread)
    result ← answer.ask(text, this chat's history, today)
    remember (question, answer); keep the last HISTORY_TURNS
    reply in HTML with ↗ links, plus a button per attachment of the cited emails (at most 8)
    log "answered in 14s (4 sources)"
    the answer asked to send files → send them

button "a:<token>" → answerCallbackQuery ("Fetching from Outlook…" or "expired")
                   → fetch that attachment from Outlook → sendDocument / sendPhoto
```

```python
# mailbrief/notify/bot.py::Bot._typing,Bot._question,Bot._buttons,Bot._button
    def _typing(self, chat_id: str, done: threading.Event) -> None:
        while not done.is_set():
            try:
                self.api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
            except Exception:  # noqa: BLE001 - only a nicety
                pass
            done.wait(4.5)
# ...
    def _question(self, chat_id: str, text: str) -> None:
        from mailbrief.ai import answer

        ask = self.ask or answer.ask
        done = threading.Event()
        threading.Thread(target=self._typing, args=(chat_id, done), daemon=True).start()
        t0 = time.monotonic()
        try:
            result = ask(text, self.history.get(chat_id, []), self._today())
        finally:
            done.set()
        self.history.setdefault(chat_id, []).append((text, result["text"]))
        self.history[chat_id] = self.history[chat_id][-answer.HISTORY_TURNS:]
        self.say(chat_id, answer.render(result, html=True), html=True, buttons=self._buttons(result["sources"]))
        _log(f"answered in {time.monotonic() - t0:.0f}s ({len(result['sources'])} sources)")
        if result.get("send"):
            self._send_files(chat_id, result["send"])

    def _buttons(self, sources: list[dict]) -> list | None:
        rows, count = [], 0
        for e in sources:
            for a in e.get("attachments") or []:
                if a.get("inline") or count >= MAX_BUTTONS:
                    continue
                token = secrets.token_hex(4)
                self.tokens[token] = (e, a)
                icon = "🖼" if (a.get("content_type") or "").startswith("image/") else "📎"
                rows.append([{"text": f"{icon} {a['name'][:40]}", "callback_data": f"a:{token}"}])
                count += 1
        return rows or None

    def _button(self, chat_id: str, q: dict) -> None:
        data = q.get("data") or ""
        hit = self.tokens.get(data[2:]) if data.startswith("a:") else None
        try:
            self.api("answerCallbackQuery", {"callback_query_id": q.get("id"),
                                             "text": "Fetching from Outlook…" if hit else "That button has expired; ask again."})
        except Exception:  # noqa: BLE001
            pass
        if hit:
            self._send_files(chat_id, [hit])
```

```python
# mailbrief/notify/bot.py::Bot._send_files,fetch_files
    def _send_files(self, chat_id: str, wanted: list[tuple[dict, dict]]) -> None:
        from mailbrief.service import Busy

        try:
            files = (self.fetch_files or fetch_files)(wanted)
        except Busy:
            self.say(chat_id, "A MailBrief run is using Outlook right now; tap the button again in a minute.")
            return
        except Exception as e:  # noqa: BLE001
            _log(f"file fetch failed ({type(e).__name__})")
            self.say(chat_id, f"Couldn't fetch that file from Outlook: {why(e)}")
            return
        for f in files:
            try:
                if self.api is telegram._api:
                    telegram.send_file(chat_id, f["name"], f["content_type"], f["data"])
                else:
                    self.api("sendFile", {"chat_id": chat_id, "name": f["name"]})
            except telegram.TelegramError as e:
                self.say(chat_id, f"Couldn't send {f['name']}: {e}")
        if len(files) < len(wanted):
            self.say(chat_id, f"{len(wanted) - len(files)} file(s) are no longer in Outlook.")
        _log(f"sent {len(files)} file(s)")
# ...
def fetch_files(wanted: list[tuple[dict, dict]]) -> list[dict]:
    """Fetch attachments from Outlook (read-only), never while a run is using it (raises service.Busy)."""
    from mailbrief import labels
    from mailbrief.browser.outlook_reader import fetch_attachment
    from mailbrief.service import lock

    out = []
    with lock("run"), labels.outlook() as (page, auth, _startup):
        for _email, att in wanted:
            f = fetch_attachment(page, auth, att["id"])
            if f:
                out.append(f)
    return out
```

**How it works and why it's written this way:**
- **The typing thread.** Telegram's "typing…" shows for about 5 s, so it's repeated every 4.5 s. `done.wait(4.5)` doubles as the sleep and the stop check. The `finally: done.set()` stops it even when `ask` fails.
- **History in memory only.** `self.history` is a dict per chat, trimmed to the last few turns, and never written to disk. A restart forgets it; `/new` forgets it on purpose.
- **Buttons carry a short random token.** `callback_data` is limited to 64 bytes, and an Outlook attachment id is far longer. `secrets.token_hex(4)` makes 8 hex characters that map, in memory, to the email and attachment. The trade-off: buttons expire when `serve` restarts, and the bot says so.
- **`answerCallbackQuery` straight away.** Until it's answered, Telegram shows a spinner on the button. The short text appears as a toast.
- **Threads, not processes, for the listener.** Runs stay child processes. The listener only reads the archive and index, which are written atomically, so it always sees a whole old or new copy.
- **The run lock, without waiting.** `fetch_files` takes `lock("run")`. If a run holds it, `Busy` comes back at once and the reply is "tap again in a minute". Outlook is never opened twice at once.
- **Logs are counts only:** "answered in 14s (4 sources)", "sent 2 file(s)", never questions or answers.

### Commands
```
/start, /help → HELP           /new → forget this chat's history
/sync   → a normal `new` run as a child process; "✅ No new mail" if no digest was written
/login  → a one-time sign-in page in its own thread; a second /login while one is open says so
/digest → the latest saved digest again, plus the events message
/events [days] → the calendar; days must be ASCII digits 1..365
/rules (/labels) → list your rules     /rule (/label) add|remove …  → the same code as `mailbrief rules`
/profile <text> → set your profile
```

```python
# mailbrief/notify/bot.py::Bot._command,Bot._sync,_last_digest
    def _command(self, chat_id: str, text: str) -> None:
        name, _, rest = text.partition(" ")
        name = name.split("@")[0].lower()  # "/new@MyBot" in some clients
        rest = rest.strip()
        if name in ("/start", "/help"):
            self.say(chat_id, HELP)
        elif name == "/new":
            self.history.pop(chat_id, None)
            self.say(chat_id, "Fresh start: I've forgotten this conversation.")
        elif name == "/sync":
            self._sync(chat_id)
        elif name == "/login":
            self._login(chat_id)
        elif name == "/digest":
            self._digest(chat_id)
        elif name == "/events":
            self._events(chat_id, rest)
        # "rules" as in `mailbrief rules`; /labels and /label are the older names and still work. (`mailbrief
        # labels` is something else: the MB: categories in Outlook.)
        elif name in ("/rules", "/labels"):
            self.say(chat_id, rules_reply(Namespace(action="list")))
        elif name in ("/rule", "/label"):
            self.say(chat_id, label_command(rest))
        elif name == "/profile":
            self.say(chat_id, rules_reply(Namespace(action="profile", text=rest)) if rest else
                     "Usage: /profile Year 2 CS student looking for internships and hackathons")
        else:
            self.say(chat_id, f"I don't know {name}. /help lists what I can do.")

    def _sync(self, chat_id: str) -> None:
        if self.syncing.is_set():
            self.say(chat_id, "Already checking for new mail; the digest arrives when it's done.")
            return
        self.syncing.set()
        self.say(chat_id, "Checking for new mail now (about a minute). The digest arrives here if there's anything new.")

        def work():
            try:
                before = _last_digest()
                code = (self.run_sync or run_sync)()
                # Exit 0 covers "digest sent" and "nothing new": only the second needs a word from here.
                quiet = "✅ No new mail since the last check." if _last_digest() == before else None
                note = {0: quiet, 3: "A run was already in progress; its digest comes as usual.",
                        2: "Outlook needs you to sign in again: send /login.",
                        1: "The check ran, but the digest couldn't be delivered. I'll try again at the next scheduled run.",
                        4: "The digest was sent, but those emails couldn't be marked as processed, so they'll be read again next time.",
                        5: "Outlook opened, but its inbox list couldn't be read (Outlook may have changed). Try /sync again later.",
                        -1: "The check took too long and was stopped. Try /sync again in a few minutes.",
                        }.get(code, f"The check failed unexpectedly (exit code {code}). The details are in the log "
                                    "on the machine MailBrief runs on (`mailbrief status` names the file).")
                if note:
                    self.say(chat_id, note)
            finally:
                self.syncing.clear()

        threading.Thread(target=work, daemon=True).start()
# ...
def _last_digest() -> str | None:
    """When the newest saved digest was written (digests go in the current month's file). None if unknown."""
    from mailbrief import archive

    try:
        return max((d["at"] for d in archive.load(archive.months()[-1:])[1]), default="")
    except Exception:  # noqa: BLE001 - can't tell: say nothing rather than a wrong "no new mail"
        return None
```

```python
# mailbrief/notify/bot.py::Bot._login,Bot._digest,Bot._events
    def _login(self, chat_id: str) -> None:
        """A one-time sign-in page (session/remote_login.py) for when the server's Outlook login has expired."""
        from mailbrief.service import Busy
        from mailbrief.session import remote_login

        if self.logging_in.is_set():
            self.say(chat_id, "A sign-in page is already open: use the link I sent (or wait 10 minutes for it to close).")
            return
        self.logging_in.set()

        def work():
            try:
                (self.login or remote_login.run)(lambda t: self.say(chat_id, t),
                                                 lambda link: self.say(chat_id, remote_login.link_html(link), html=True))
# ...
            except Exception as e:  # noqa: BLE001
                _log(f"sign-in page failed ({type(e).__name__})")
                self.say(chat_id, f"The sign-in page failed: {why(e)} Send /login to try again.")
            finally:
                self.logging_in.clear()

        _log("sign-in page opened")
        threading.Thread(target=work, daemon=True).start()

    def _digest(self, chat_id: str) -> None:
        from mailbrief import archive, events, links

        digests = archive.load()[1]
        if not digests:
            self.say(chat_id, "No digest saved yet.")
            return
        last = max(digests, key=lambda d: d["at"])
        self.say(chat_id, links.to_html(last["text"], last.get("refs") or {}), html=True)
        ev = events.build(self._today(), (), None, html=True)
        if ev:
            self.say(chat_id, ev, html=True)

    def _events(self, chat_id: str, rest: str) -> None:
        from mailbrief import archive, events, rules

        # isascii: "²" and "٣" pass isdigit() but int() refuses them
        if rest and not (rest.isascii() and rest.isdigit() and 1 <= int(rest) <= 365):
            self.say(chat_id, "Usage: /events, or /events 30 for the next 30 days (1 to 365).")
            return
        # the same default as the morning message and `mailbrief events`: EVENTS_DAYS (0 there means 14 here)
        days = int(rest) if rest else events.days() or events.DEFAULT_DAYS
        try:
            your_rules = rules.load()
        except rules.RulesError:
            your_rules = rules.empty()
        today = self._today()
        text = events.render(events.upcoming(archive.load()[0], today, days, (), your_rules), today, days, html=True)
        self.say(chat_id, text or f"No events in the next {days} days.", html=bool(text))
```

```python
# mailbrief/notify/bot.py::rules_reply,label_command
def rules_reply(args: Namespace) -> str:
    """What `mailbrief rules …` would print, as a chat reply (same code, same checks)."""
    from mailbrief.main import rules_command

    defaults = dict(kind=None, key=None, description=None, label=None, direct=False, priority=None, boost=False, text="")
    out = StringIO()  # its own buffer: other threads' output (service log lines) never leaks into the reply
    rules_command(Namespace(**{**defaults, **vars(args)}), out=out)
    return out.getvalue().strip() or "Done."


def label_command(rest: str) -> str:
    """/rule add course CS2040S [p2] [boost] | add sender a@b.c "Prof X" [direct] [boost] [p1]
    | add topic Name "description" [p2] | remove course|sender|topic KEY"""
    usage = ('Usage: /rule add course CS2040S | /rule add sender a@b.c "Prof X" direct | '
             '/rule add topic Networking "career fairs, meetups" p2 | /rule remove course MA1521')
    try:
        words = shlex.split(rest)
    except ValueError:
        return usage
    if len(words) < 3 or words[0] not in ("add", "remove") or words[1] not in ("course", "sender", "topic"):
        return usage
    action, kind, key, extra = words[0], words[1], words[2], words[3:]
    if action == "remove":
        return rules_reply(Namespace(action="remove", kind=kind, key=key))
    flags = {w.lower() for w in extra}
    priority = next((int(w[1]) for w in flags if len(w) == 2 and w[0] == "p" and w[1] in "12345"), None)
    plain = [w for w in extra if w.lower() not in ("direct", "boost") and not (len(w) == 2 and w.lower()[0] == "p" and w[1] in "12345")]
    args = Namespace(action="add", kind=kind, key=key, priority=priority, boost="boost" in flags,
                     direct="direct" in flags, label=plain[0] if kind == "sender" and plain else None,
                     description=" ".join(plain) if kind == "topic" and plain else None)
    return rules_reply(args)
```

**How it works and why it's written this way:**
- **`text.partition(" ")`** splits at the first space into command and the rest, and never fails. `name.split("@")[0]` handles `/new@MyBot`, which some clients send.
- **`/sync`** starts a normal `new` run as a child process (`service._run_child`), the same as a scheduled one, so the digest arrives as usual. It runs in a thread so the bot keeps answering. `self.syncing` stops two at once.
- **"No new mail" detection.** Exit code 0 means both "digest sent" and "nothing new". `_last_digest()` compares the newest digest's timestamp before and after. If it can't tell, it returns `None` and the bot says nothing, rather than a wrong "no new mail".
- **One message per exit code.** The dict maps each code to what you can do about it. `.get(code, …)` covers anything unexpected.
- **`/events` and `isascii()`.** `"²".isdigit()` is `True`, but `int("²")` raises. Checking `isascii()` first keeps the validation and the conversion in agreement.
- **`/rule …` and `/profile …`** call the same `rules_command` as the terminal, so the checks and messages are identical. `rules_reply` gives it its own `StringIO`: printing to the shared stdout would mix in log lines from other threads.
- **`shlex.split`** parses shell-style quoting, so `"Prof Tan"` stays one word. An unclosed quote raises `ValueError`, which becomes the usage message.
- **A small parsing quirk:** `priority` is taken from a *set* of the flag words, so `/rule add course CS2040S p1 p3` picks one of the two arbitrarily. One flag is the normal case.
- **`/login`** runs `remote_login.run` in its own thread and sends you the link. `self.logging_in` makes a second `/login` say so instead of opening a second page.

### Starting it
```
start(stop)       → inside serve: a daemon thread running Bot().run(stop), unless CHAT=off or no token
run_foreground()  → `mailbrief bot`: takes the serve lock (serve already runs a listener), then listens until Ctrl+C
```

```python
# mailbrief/notify/bot.py::start,run_foreground
def start(stop: threading.Event) -> threading.Thread | None:
    """Start the listener in a background thread (serve does this), unless CHAT=off or there's no bot token."""
    if not enabled():
        return None
    t = threading.Thread(target=Bot().run, args=(stop,), name="mailbrief-chat", daemon=True)
    t.start()
    return t


def run_foreground() -> int:
    """`mailbrief bot`: just the listener, until Ctrl+C."""
    if not enabled():
        print("Chat is off: set TELEGRAM_BOT_TOKEN and CHAT=on in .env.")
        return 2
    from mailbrief.service import Busy, lock

    stop = threading.Event()
    try:
        with lock("serve"):  # serve already runs this listener: two readers would fight over getUpdates (409)
            print("Listening for your Telegram messages (Ctrl+C to stop)…")
            try:
                Bot().run(stop)
            except KeyboardInterrupt:
                stop.set()
    except Busy:
        print("`mailbrief serve` is running and already answers your chat; stop it first to run the bot alone.")
        return 3
    return 0
```

**How it works and why it's written this way:**
- **Why the serve lock?** Two programs calling `getUpdates` on one bot token get a 409 from Telegram and steal each other's updates. Holding `serve.lock` means `mailbrief bot` and `serve` can't both run.
- **`daemon=True`** lets the process exit without joining the thread. `serve`'s shutdown sets `stop`, so the thread ends at its next poll anyway.

### Rebuilding it
- **Inputs:** Telegram updates; your destinations; `answer.ask` for questions. **Outputs:** replies, files, child runs. **Depends on:** `telegram` (sending), `service` (lock, `_run_child`, log), `answer`, `archive`, `events`, `rules`, `labels.outlook`.
- **The core is twenty lines:** a `getUpdates` loop with an offset, an allowlist check, and a dispatch on the first word. Start there, add commands one at a time, and put each outside dependency behind a constructor argument so tests can fake it.
- **Adapting it:**
  - **Slack:** use Socket Mode (a WebSocket the app opens outward, so no public URL), check `event["channel"]` against an allowlist, and reply with `chat.postMessage`. Buttons are Block Kit `actions` with a `value` instead of `callback_data`.
  - **Discord:** the gateway is a WebSocket, so a library (`discord.py`) is the practical choice. It is asyncio-based, so attachment fetching would have to run in a thread pool, or in a child process like `/sync`.
  - **Email as the chat:** poll a mailbox for replies from your own address. Slow, but it needs no third-party service.

### Try it
`tests/test_bot.py`: `test_only_your_private_chats`, `test_question_buttons_and_history`, `test_commands_and_errors`, `test_chat_replies_never_tell_you_to_type_cli_flags`, `test_label_command_parsing`, `test_login_only_from_your_chat_and_once_at_a_time`, `test_switch`.
