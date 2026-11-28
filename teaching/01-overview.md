# Overview: the problem, Outlook, principles, map, lifecycles, data

<!-- TOC -->
**Contents**

- [The problem and the big idea](#the-problem-and-the-big-idea)
- [Background: how Outlook on the web works](#background-how-outlook-on-the-web-works)
- [The guiding principles](#the-guiding-principles)
- [The map: files and folders](#the-map-files-and-folders)
- [The lifecycles](#the-lifecycles)
   - [A. Login (once, or every few months)](#a-login-once-or-every-few-months)
   - [B. Run (every morning)](#b-run-every-morning)
   - [C. Browse (any time, offline)](#c-browse-any-time-offline)
   - [D. Serve (always on)](#d-serve-always-on)
- [The data shapes](#the-data-shapes)
   - [Conversation (from the inbox list)](#conversation-from-the-inbox-list)
   - [EmailRecord (one real message)](#emailrecord-one-real-message)
   - [Classification (Pass 1's answer)](#classification-pass-1s-answer)
   - [Cursor (`data/cursor.json`)](#cursor-datacursorjson)
   - [Archive month file (`data/archive/YYYY-MM.enc`)](#archive-month-file-dataarchiveyyyy-mmenc)
<!-- /TOC -->

## The problem and the big idea

**The problem:** every morning there's a pile of email. Some of it is urgent, some needs a reply, most is noise. Reading it all to find the three things that matter takes time.

**The idea:** a program that, every morning:
1. reads everything that arrived since yesterday,
2. asks an AI to sort each email (Urgent, Needs Reply, FYI, Meetings, Newsletter, Low Priority),
3. writes a short **digest** ("pay the hostel fee by the 22nd; it looks like you already paid"),
4. sends that digest to your phone (Telegram),
5. keeps a searchable, encrypted history.

**The hard constraint:** it's a **work/university** Outlook account. Microsoft's official API (Microsoft Graph) needs an "app registration" set up for the organisation, which is a bigger thing than a personal tool for one mailbox. So MailBrief works through **the same website you already use**, Outlook on the web, in a browser it drives: it uses the session you signed in to yourself, and can only do what you can do there by hand. Whether automating your own mailbox like this is allowed is your organisation's call: check its IT acceptable-use policy before you use it.

**What it never does:** delete, move, send, reply, or even mark email as read. The **one** thing it changes is its own labels: Outlook categories named `MB: …` (see [labels](05-labels-rules-extras.md)), and code refuses every other kind of write.

**If you are rebuilding it for something else:** the shape carries over. Replace "Outlook on the web" with any site you are signed in to, "classify" with whatever judgement you need, and "Telegram" with any place you read messages. The browser, storage and session layers in [the next chapter](02-storage-session-browser.md) are the reusable part.

---

## Background: how Outlook on the web works

You need this picture to understand almost every design choice.

When you open `outlook.office.com/mail` in a browser:

```
Your browser                                   Microsoft's servers
────────────                                   ───────────────────
1. Loads the Outlook web app (JavaScript)  ◄──
2. The app asks for data, in JSON:
   POST /owa/service.svc?action=FindConversation   ──►  "give me the inbox list"
                                                    ◄── JSON: 50 conversations
   POST /owa/service.svc?action=GetItem            ──►  "give me this email's body"
                                                    ◄── JSON: subject, from, body…
3. The app draws the list on screen from that JSON
```

Key facts this project relies on:

- **The page is drawn from JSON.** The list you see is rendered from structured data that Outlook downloads. That data has real IDs, exact timestamps, sender addresses and so on. Reading the JSON is far more reliable than reading the screen.
- **`service.svc` is Outlook's internal API.** Each request names an *action* (`FindConversation`, `GetItem`, `GetAttachment`, …) and carries an **authorization token** in its headers. The page's own JavaScript adds that token. MailBrief runs inside that same signed-in page session, so its read requests carry the headers the page itself just used (kept in memory only, never saved or logged).
- **The list is "virtualized".** Outlook only downloads about 50 conversations at first. More are fetched only when you **scroll with the mouse wheel**. A program that wants everything has to scroll.
- **Focused Inbox** splits the inbox into two tabs, *Focused* and *Other*. Each is a separate `FindConversation` request (`FocusedViewFilter` 0 or 1). Load only one and you miss the other.
- **A conversation** is a thread. Every reply or forward is a **new, separate email** that shares the thread's `ConversationId`. Nothing is ever edited in place.
- **Your session** is a set of cookies. If the browser has valid cookies, Outlook doesn't ask you to log in. Microsoft rotates (refreshes) them over time.
- **Read state:** clicking an email in the UI marks it read. Calling `GetItem` directly does not.
- **StartupData** is one big JSON blob the page loads first. It holds your own address and your category list. It is served with a JavaScript content type, which matters when you filter responses by type (see `open_outlook` in [the next chapter](02-storage-session-browser.md)).

---

## The guiding principles

These ideas explain most decisions in the code. When something looks odd, one of these is usually why.

1. **Read the data, not the screen.** Screens change with every Outlook redesign; data formats change much less. So the app listens to Outlook's JSON instead of scraping text off the page.
2. **Never click what you don't need to.** Clicking opens emails (marking them read) and depends on fragile button positions. The app clicks exactly one kind of thing: the Focused/Other **tab**. Everything else uses data calls. (The remote sign-in page passes on *your* taps, but only on Microsoft's sign-in screens.)
3. **Read-only by design, with one guarded exception.** No code path can delete, send or move mail. The only write is MailBrief's own `MB:` categories, and one function (`check_request`) inspects every outgoing request and refuses anything else. A bug can't do damage that the code simply can't do.
4. **AI reads and decides; code does the rest.** Navigation, parsing, deduplication and ordering are plain code: fast, free, predictable. The AI only does what code can't: understand language and images.
5. **Email content is untrusted.** Anyone can send you an email saying "ignore your instructions and…". The AI that reads email has no tools and can only return a label. The model that writes the digest never sees email bodies, only the first model's labels.
6. **Your data stays as local as possible.** The browser runs on your PC, the archive is encrypted on your disk, the AI is whichever endpoint you configure (ideally one your organisation runs). Besides that, only the summary-level digest leaves, to Telegram.
7. **Idempotent and resumable.** Running the same command twice must never double anything up: no duplicate archive entries, no repeated AI calls, no lost emails. Interrupting must never corrupt anything.
8. **Fail soft, never silently.** If one part fails (an image, one AI call, one destination), the rest carries on, and you're told what happened.
9. **The simplest thing that works** (the "ponytail" rule). JSON files before databases, stdlib `urllib` before an HTTP library, plain-`assert` tests before a framework. Each shortcut carries a `ponytail:` comment naming its limit and when to upgrade.

---

## The map: files and folders

```
mail-manager/
├── pyproject.toml          project definition: name, dependencies, the `mailbrief` command
├── uv.lock                 exact versions of every dependency (reproducible installs)
├── .python-version         the Python version uv uses
├── .env / .env.example     your settings & secrets / the template for them
├── README.md               what it is, quick start, configuration
├── docs/design.md          architecture & roadmap
├── commands.md             every command, in detail
├── CHANGELOG.md, SECURITY.md, LICENSE
├── teaching/               this guide, one file per part (start at teaching/README.md)
├── Dockerfile, compose.yaml, .dockerignore   running `serve` always-on on a server
├── .github/workflows/      ci.yml (tests on every push), pages.yml (publishes website/)
├── website/                the static project website (GitHub Pages)
├── demo/run.py             an offline tour on invented mail: no Outlook, no AI
├── scripts/
│   ├── check_website.py    checks the website's pages
│   └── teaching_toc.py     rewrites the table of contents in teaching/*.md
├── data/                   (git-ignored) everything the app saves
│   ├── session.enc         your Outlook login, encrypted
│   ├── cursor.json         "where did we get to?"
│   ├── destinations.json   where digests go
│   ├── rules.json          your own labels: profile, courses, senders, topics
│   ├── index.enc           the search index for chat: vectors only, encrypted
│   ├── archive/YYYY-MM.enc saved emails, one file per month (YYYY-MM.json with --plain)
│   ├── schedule.json       the service's memory: last scheduled time done, last result, next run
│   ├── logs/YYYY-MM.log    what the service did (no email content)
│   ├── stop.request        written by `mailbrief stop`; the service sees it and exits
│   └── run.lock, serve.lock   locked by the OS while a run / the service is active
├── mailbrief/              the program
│   ├── __init__.py         ConfigError: "a setting in .env is missing or wrong"
│   ├── main.py             the command line + the run pipeline (the conductor)
│   ├── browser/
│   │   ├── connect.py          get a browser (local, or a remote one via BROWSER_WS_URL)
│   │   ├── outlook_reader.py   drive Outlook: open, listen, scroll, call GetItem
│   │   ├── owa_network.py      understand Outlook's JSON + build requests + the write guard (pure)
│   │   └── outlook_writer.py   the ONLY code that changes Outlook: categories only
│   ├── session/
│   │   ├── login_once.py       the one-time visible login
│   │   ├── remote_login.py     sign in from any browser via a one-time link (/login, servers)
│   │   └── manager.py          save/load the encrypted session
│   ├── storage/
│   │   ├── crypto.py           encrypt/decrypt with your key
│   │   └── files.py            atomic file replace that survives Windows file locks
│   ├── ai/
│   │   ├── client.py           the only code that talks to the AI
│   │   ├── classifier.py       Pass 1: label one email
│   │   ├── digest.py           Pass 2: write the summary
│   │   └── answer.py           ask your inbox: plan, search, answer, checks
│   ├── notify/
│   │   ├── telegram.py         sending to Telegram (plain or HTML with links, files)
│   │   └── bot.py              the Telegram chat listener (allowlisted)
│   ├── threads.py          conversation order, "you replied", context
│   ├── progress.py         live progress lines, counters, spinner (to stderr)
│   ├── service.py          serve / stop / status / autostart: runs on a schedule, by itself
│   ├── cursor.py           which emails are new
│   ├── archive.py          the saved history (monthly files, periods)
│   ├── destinations.py     the list of Telegram chats
│   ├── labels.py           which emails need which MB: labels; apply / clear / status
│   ├── rules.py            your own labels: load/check rules.json, match courses and senders in code
│   ├── events.py           the UPCOMING EVENTS calendar, built by code from saved events
│   ├── web_images.py       linked images in emails: guarded downloads for the vision model
│   ├── links.py            ↗ links to emails in Outlook, built by code from item ids
│   └── index.py            the search index: chunks, embeddings, hybrid search
└── tests/                  plain-function tests run by pytest, on made-up data
```

**Why this split?** Each file has **one job**, and the files that touch the outside world are separate from the files that only compute:

| Touches the outside world | Pure logic (easy to test) |
|---|---|
| `outlook_reader.py` (browser, network) | `owa_network.py` (JSON → records) |
| `ai/client.py` (HTTP) | `ai/classifier.py`'s `validate`, `trim_body` |
| `notify/telegram.py` (HTTP) | `telegram.messages` |
| `archive.py`, `cursor.py` (disk) | `threads.py`, `archive.period_range`, `cursor.select_new` |
| `session/remote_login.py`'s `run` (browser) | its `Window`, `parse_input`, `handler` (tested with a real local server) |

That's why the tests run without internet: they exercise the pure half with made-up data. The browser half (`outlook_reader`, `connect`, `manager`, `login_once`) has no direct tests, because it needs a live Outlook; `tests/test_pipeline.py` replaces it with stand-ins to test what `main.run` does with its results.

**Why one `owa_network.py` for all Outlook formats?** Outlook's JSON format is **undocumented** and can change without notice. If it does, exactly one file needs fixing.

---

## The lifecycles

Everything the app does falls into three flows, plus a fourth (D) that simply runs flow B for you on a schedule. Each flow has one "conductor" function; the quotes below show its spine, and the later chapters explain each step.

### A. Login (once, or every few months)
```
you run `mailbrief login`
  → the encryption key is checked first (a bad key would only show after your password and MFA)
  → visible Chromium opens Outlook
  → you sign in (MFA, "Stay signed in"), press Enter
  → cookies + browser identity are encrypted into data/session.enc

or, on a server with no screen: /login in the chat, or `mailbrief login --remote`
  → a one-time link to a live picture of a headless browser; same result
```

```python
# mailbrief/session/login_once.py::login_once
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
        browser.close()
    print(f"Session saved (encrypted) to {manager.SESSION_PATH}")
```

The whole thing is twelve lines because each step is a call into a module that does one job: `get_browser` (connect.py), `manager.save` (session/manager.py), and the key check (storage/crypto.py). [The next chapter](02-storage-session-browser.md) covers each one, and the remote version.

### B. Run (every morning)
```
check the AI endpoint is configured        ← before Outlook opens, not after reading the whole inbox
load session, archive, rules, cursor
  → headless Chromium opens Outlook with your cookies
  → listen to Outlook's JSON while scrolling Focused + Other
  → pick conversations with something new
  → GetItem: full text of every message in them (any folder)
  → choose the new inbox emails; fetch their images
  → re-save the session (fresh cookies); close the browser
  → build threads; mark what you've replied to
  → AI Pass 1: label each new email (with thread context), several conversations at once
  → save to the archive
  → open Outlook again briefly: put MB: labels on emails that need them
  → update the search index
  → AI Pass 2: write the digest from the labels; save it to the archive
  → print, maybe send, maybe advance the cursor
```

```python
# mailbrief/main.py::run
    client.settings()  # no endpoint or key: say so now (ConfigError), not after reading the whole inbox
    session = manager.load()
# ...
    with sync_playwright() as p:
        browser = get_browser(p, headless=True)
        try:
            context = browser.new_context(
                storage_state=session["state"], user_agent=session["user_agent"]
            )
            page = context.new_page()
            result = read_inbox(page)
# ...
            records, full_text = fetch_emails(page, result["auth"], convs, result["me"])
# ...
            images = collect_images(page, result["auth"], todo)  # memory only
# ...
        paths = archive.save(keep, [r["classification"] for r in keep], None, plain, tz)
# ...
        labels.run_step(
            log
        )  # MB: labels in Outlook for whatever is pending; never fails the run
# ...
        added, _ = index.update(archive.load()[0], log)  # new mail becomes searchable in chat; never fails the run
# ...
                text = digest(
# ...
    delivered = deliver(links.to_html(text, digest_refs(digest_emails)), log, html=True) if send and text else True
# ...
            cur.save(cur.advance(cursor, targets))
```

**Why this order?** Each step only happens once the step it depends on is safe. The browser is closed before the AI starts, so a slow AI never holds a Chromium open. The archive is saved before the digest, because a period digest ("this week") reads this run's emails back from it. The cursor moves last, and only if the digest was delivered and the emails were saved: anything earlier could lose an email. The full walk-through is in [main.py and the full run](06-main-and-full-run.md).

### C. Browse (any time, offline)
```
you run `mailbrief emails …`
  → decrypt the archive in memory
  → filter (period / day / search), group by thread, number
  → list, or show one, or show a whole thread, or digest, or export
```

```python
# mailbrief/main.py::show_emails
    try:
        all_emails, all_digests = archive.load()
        on_day = date.fromisoformat(day) if day else None
    except archive.ArchiveError as err:
        print(err)
        return 1
```

No browser and no AI: everything comes from `archive.load()`, which decrypts the month files into memory and never writes plain text to disk.

### D. Serve (always on)
```
Task Scheduler at logon (your PC) or Docker (a server) starts `mailbrief serve`
  → starts the Telegram chat listener (and, on Render, the always-open sign-in port)
  → every 30 s: is a scheduled time due (or missed while asleep)?
      yes → start flow B as a child process: `run --send --quiet [--commit | --digest SCOPE]`
            log the result; retry in 15 min (3 tries); alert on Telegram if the login expired
  → until Ctrl+C / `mailbrief stop` / `docker stop`: finish any run in progress, then exit
```

```python
# mailbrief/service.py::_serve
        while not stop_wanted():
            now = datetime.now(tz)
            due = [s for s in due_slots(now, schedule, datetime.fromisoformat(state["last_done"])) if s not in done_now]
            if due and (retry_at is None or now >= retry_at):
                attempts += 1
                for at, scope in due:
                    log(f"run started ({scope}, slot {at:%a %d %b %H:%M})")
                    t0 = time.monotonic()
                    code = _run_child(scope, at)
# ...
            for _ in range(TICK_S):  # short sleeps: a stop request is noticed within a second
                if stop_wanted():
                    break
                time.sleep(1)
```

**Why a child process, not a function call?** A run opens Chromium, uses a lot of memory and can hang on a stuck page. As a separate process it can be timed out and killed, and its memory is returned to the system when it ends, while the service keeps running. The details are in [delivery and the service](04-delivery-and-service.md).

---

## The data shapes

Five shapes of data flow through the program. Knowing them makes every function easier to read. They are all plain `dict`s, not classes. That is a deliberate choice: they go straight into `json.dumps` for the archive with no conversion code. The cost is that a typo in a key name is only caught when the code runs, which is why each shape is built in exactly one place, quoted below.

### Conversation (from the inbox list)
Made by `owa_network._to_message` (called by `parse_messages`) from `FindConversation` JSON. One per thread in the list:
```
conversation:
  kind               "conversation" (or "item" if Outlook sent a flat item list instead)
  id                 Exchange ConversationId
  subject, sender, received_at (latest delivery in the thread, a timezone-aware datetime)
  item_ids           the thread's emails that are IN THE INBOX
  global_item_ids    ALL the thread's messages in ANY folder (incl. your Sent replies)
  preview            the grey snippet Outlook shows in the list
  has_attachments, importance
```

```python
# mailbrief/browser/owa_network.py::_to_message
def _to_message(d: dict) -> dict | None:
    low = _lower(d)
    if "conversationtopic" in low:
        kind, subject, when, ident = "conversation", low["conversationtopic"], low.get("lastdeliverytime"), low.get("conversationid")
    elif "subject" in low:
        when = low.get("datetimereceived") or low.get("receiveddatetime")
        kind, subject, ident = "item", low["subject"], low.get("itemid") or low.get("id")
    else:
        return None
    if not isinstance(subject, str) or not isinstance(when, str):
        return None
    received = _parse_time(when)
    if received is None:
        return None
    item_ids = low.get("itemids") if kind == "conversation" else [ident]
    return {
        "kind": kind,
        "id": _id(ident),
        "subject": subject or "(no subject)",
        "sender": _sender(low),
        "received_at": received,
        "item_ids": [i for i in map(_id, item_ids or []) if i],
        # Every message in the thread, in any folder (your Sent replies too); ItemIds is inbox only.
        "global_item_ids": [i for i in map(_id, low.get("globalitemids") or item_ids or []) if i],
        "preview": low.get("preview") if isinstance(low.get("preview"), str) else "",
        "has_attachments": bool(low.get("hasattachments")),
        "importance": low.get("importance") or "Normal",
    }
```

**Why both ID lists?** `item_ids` says which messages are your incoming mail (what the digest is about). `global_item_ids` lets the app see the whole thread, including what *you* sent, which is how "you replied" is detected. The fallback `or item_ids` covers a response with no `GlobalItemIds`: you then lose "you replied", not the email.

### EmailRecord (one real message)
Built in three steps, by three files, because each step knows something the one before doesn't:
```
email:
  id, conversation_id
  sender_name, sender_email, subject, received_at
  body_text            plain text, whitespace-tidied, max 20,000 chars
  has_attachments
  attachment_names, image_attachments (metadata only)
  attachments          every file attachment's id, name, size, type, inline flag (never content)
  is_read, importance
  conversation_index   Exchange's thread-tree key (base64)
  in_reply_to, internet_message_id
  to, cc               lowercased recipient addresses
  body_source          "getitem" (full text) or "preview" (fallback)
  in_inbox             is it one of the inbox's item_ids?          ← set by the reader
  from_me              is the sender your address?                 ← set by the reader
  direct               are you the ONLY To recipient?              ← set by the reader
  classification, replied, thread_size                             ← set by main.run
```

Step 1, `owa_network.parse_items`, turns one `GetItem` reply into records. It doesn't know which ids are in the inbox or what your address is, so it writes placeholders:

```python
# mailbrief/browser/owa_network.py::parse_items
            records.append({
                "id": _id(it.get("ItemId")),
                "conversation_id": _id(it.get("ConversationId")),
                "sender_name": box.get("Name") or "",
                "sender_email": box.get("EmailAddress") or "",
                "subject": it.get("Subject") or "(no subject)",
                "received_at": received,
                "body_text": _clean((it.get("Body") or {}).get("Value") or ""),
                "has_attachments": bool(it.get("HasAttachments")),
                "attachment_names": [a.get("Name") for a in it.get("Attachments") or [] if a.get("Name")],
                "image_attachments": image_attachments(it.get("Attachments")),
                "attachments": attachment_list(it.get("Attachments")),
                "to": addresses(it.get("ToRecipients")),
                "cc": addresses(it.get("CcRecipients")),
                "is_read": bool(it.get("IsRead")),
                "importance": it.get("Importance") or "Normal",
                "body_source": "getitem",
                # Thread position: ConversationIndex is Exchange's thread-tree key (see threads.py).
                "conversation_index": it.get("ConversationIndex") or "",
                "in_reply_to": it.get("InReplyTo") or "",
                "internet_message_id": it.get("InternetMessageId") or "",
                # Set by the reader, which knows the inbox ids and your address.
                "in_inbox": True,
                "from_me": False,
            })
```

Step 2, `outlook_reader.fetch_emails`, knows the inbox ids and your address, and corrects them:

```python
# mailbrief/browser/outlook_reader.py::fetch_emails
    for r in records:
        r["in_inbox"] = r["id"] in inbox_ids
        r["from_me"] = me is not None and r["sender_email"].lower() == me.lower()
        r["direct"] = me is not None and r.get("to") == [me.lower()]  # you're the only To recipient
```

Step 3, `main.run`, knows the archive and the threads:

```python
# mailbrief/main.py::run
    for r in records:
        stored = archived.get(r["id"])
        if r["from_me"]:
            r["classification"] = {"category": "Sent"}  # context only, no AI
        elif not r["in_inbox"]:
            # Filed or deleted since it was classified: keep that work (summary, events), don't blank it.
            r["classification"] = _kept(stored) or {"category": "Elsewhere"}
        elif stored and not _needs_ai(stored):
            r["classification"] = stored[
                "classification"
            ]  # never classify the same email twice
        else:
            r["classification"] = None
    thread_map = threads.group(list(pool.values()))
    for r in records:
        thread = thread_map[r.get("conversation_id") or r["id"]]
        r["replied"] = threads.replied(r, thread)
        r["thread_size"] = len(thread)
```

**Why `or ""` and `or []` everywhere?** Outlook leaves fields out, or sends `null`, when they are empty. `it.get("Subject") or "(no subject)"` handles both a missing key and a `None` value in one step. Every later function can then assume the key is there and has the right type, so none of them need their own checks. **Why `received_at` as a `datetime` here but text in the archive?** Comparing and sorting need a real `datetime`; JSON can't hold one. `archive.save` converts to ISO text on the way in and `archive.load` converts back on the way out, so the rest of the program only ever sees `datetime`s.

A preview record (GetItem failed) has the same keys, made by `owa_network.preview_records`, with `body_source = "preview"` and empty thread fields.

### Classification (Pass 1's answer)
```
classification:
  category          Urgent | Needs Reply | FYI | Meetings | Newsletter | Low Priority
                    (or Unclassified on failure)
  priority          1 (deal with first) … 5 (safe to ignore)
  one_line_summary
  action_items      list of short strings
  deadline          YYYY-MM-DD or null
  tags              your topic names that fit (only names from rules.json survive)
  boost             does it fit your profile as an opportunity/event? (true/false)
  events            every event it announces: [{name, detail (one line), date, time, place, link,
                    signup_deadline}], [] for most mail; checked by validate_events
  model             which model produced it (added by classify, not validate)

context-only messages get a one-key classification instead:
  {category: "Sent"}       your own message in the thread
  {category: "Elsewhere"}  filed or deleted since (or its earlier real classification, kept)
```

```python
# mailbrief/ai/classifier.py::validate
def validate(data: dict | None, topics: tuple[str, ...] = (), received: date | None = None) -> dict | None:
    if not data or data.get("category") not in CATEGORIES:
        return None
    priority = data.get("priority")
    deadline = data.get("deadline")
    names = {t.lower(): t for t in topics}
    tags = data.get("tags")
    tags = tags if isinstance(tags, list) else []
    return {
        "category": data["category"],
        "priority": priority if isinstance(priority, int) and 1 <= priority <= 5 else 3,
        "one_line_summary": str(data.get("one_line_summary") or "").strip(),
        "action_items": _strings(data.get("action_items")),
        "deadline": _date(deadline, received),  # a real calendar date: "2026-02-30" would crash every date lookup later
        # Only topics from your list survive, spelled as you wrote them.
        "tags": list(dict.fromkeys(names[t.lower()] for t in tags if isinstance(t, str) and t.lower() in names)),
        "boost": data.get("boost") is True,
        "events": validate_events(data.get("events"), received),
    }
```

```python
# mailbrief/ai/classifier.py::classify
        result = validate(extract_json(reply), topics, email["received_at"].date())
        if result:
            return {**result, "model": model}
    return {"category": "Unclassified", "priority": 3, "one_line_summary": email["subject"],
            "action_items": [], "deadline": None, "tags": [], "boost": False, "events": [], "model": model}
```

**Why is this shape built by `validate` and not taken from the model as-is?** The model's JSON is untrusted text. `validate` rebuilds the dict key by key, so whatever extra keys the model invents are dropped and every kept value has the right type. A wrong category means "invalid, try again" (`None`); a wrong priority is just reset to 3, because one bad number shouldn't throw away a good summary. Readers of a classification should use `.get()`: the `Sent` and `Elsewhere` dicts have only `category`. The classifier itself is covered in [the AI pipeline](03-ai-pipeline.md).

### Cursor (`data/cursor.json`)
```
cursor:
  last_processed_at   newest email time processed so far (ISO text), or null before the first commit
  recent_ids          last 500 processed email IDs
```

```python
# mailbrief/cursor.py::load
def load() -> dict:
    if CURSOR_PATH.exists():
        return json.loads(CURSOR_PATH.read_text())
    return {"last_processed_at": None, "recent_ids": []}
```

```python
# mailbrief/cursor.py::advance
    return {
        "last_processed_at": latest.isoformat(),
        "recent_ids": (cursor["recent_ids"] + [r["id"] for r in records])[-KEEP_IDS:],
    }
```

**Why a time *and* a list of ids?** The time alone would miss a second email in the same second as the last one; the ids alone would grow forever. Together they are exact and bounded: `[-KEEP_IDS:]` keeps only the last 500, and the time does the coarse filtering. The file is plain JSON, not encrypted: it holds only times and opaque ids.

### Archive month file (`data/archive/YYYY-MM.enc`)
```
month file:
  emails:   [ EmailRecord + classification + replied + thread_size
              (+ outlook_labels / labels_cleared / outlook_gone, the label bookkeeping), … ]   (sorted by time)
  digests:  [ {at: time written, scope: "new" | "this-month" | …, text: "📬 …",
               refs: {n: email id} (optional, for the ↗ links)} , … ]
```

```python
# mailbrief/archive.py::save
    for email, result in zip(emails, results):
        record = {**email, "received_at": email["received_at"].isoformat(), "classification": result}
        by_month.setdefault(f"{email['received_at'].astimezone(tz):%Y-%m}", []).append(record)
# ...
        if digest and month == f"{now:%Y-%m}":
            data["digests"].append({"at": now.isoformat(), "scope": digest_scope, "text": digest,
                                    **({"refs": digest_refs} if digest_refs else {})})  # [n] → email id, for links
```

**Why `{**email, …}`?** It makes a new dict: a copy of the record with two keys replaced. The record the rest of the run is still using keeps its `datetime`. **Why `**({"refs": …} if … else {})`?** It adds the key only when there is something to add, so old digests and new ones without links look the same. **Why the month of `astimezone(tz)`?** An email received at 00:30 on the 1st in your timezone is still the previous month in UTC; filing by your own clock puts it where you'd look for it. The archive is covered in [the AI pipeline](03-ai-pipeline.md).
