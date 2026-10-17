# MailBrief: Command Reference

Every command in this repository: what it does, step by step, what it reads and writes, each flag, exit codes, and common combinations.

Run all commands from the project folder (`mail-manager/`). They are run with **`uv run`**, which uses the project's own Python environment (`.venv`), so you never need to activate a virtualenv.

- [1. One-time setup commands](#1-one-time-setup-commands)
- [2. `mailbrief login`](#2-mailbrief-login)
- [3. `mailbrief run`](#3-mailbrief-run)
- [4. `mailbrief emails`](#4-mailbrief-emails)
- [5. `mailbrief add-destination`](#5-mailbrief-add-destination)
- [6. Developer commands (tests, checks)](#6-developer-commands)
- [7. Configuration (`.env`) that changes command behaviour](#7-configuration-env)
- [8. Files the commands create](#8-files-the-commands-create)
- [9. Recipes: common workflows](#9-recipes)
- [10. Exit codes at a glance](#10-exit-codes-at-a-glance)

---

## 1. One-time setup commands

### `uv sync`
Installs every dependency listed in `pyproject.toml`, pinned by `uv.lock`, into `.venv/`. It also installs MailBrief itself in editable mode, so code changes take effect immediately.
- **When:** after cloning, or after `pyproject.toml` / `uv.lock` change.
- **Installs:** `playwright` (browser automation), `cryptography` (encryption), `python-dotenv` (reads `.env`), `tzdata` (time-zone data; Windows has none built in).

### `uv run playwright install chromium --no-shell`
Downloads the Chromium build that Playwright drives, about 200 MB, into `%LOCALAPPDATA%\ms-playwright\`.
- `--no-shell` skips the separate "headless shell" binary. MailBrief uses the **full** Chromium for both the visible login and the headless runs (`channel="chromium"`), so Microsoft sees the same browser both times.
- **When:** once, and again after upgrading the `playwright` package (each version expects a specific Chromium build).

### Creating `.env`
Copy `.env.example` to `.env`, then generate an encryption key:
```
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Put the output in `SESSION_ENCRYPTION_KEY=`. **Keep it safe.** It decrypts your Outlook session and your email archive. Lose it and both are unreadable, so you'd need to log in again and the archive is gone.

The AI key is read from the `SOCLAAS_API_KEY` **system** environment variable (or `AI_API_KEY` if you set one). `TELEGRAM_BOT_TOKEN` can live in `.env` or a user environment variable.

---

## 2. `mailbrief login`

```
uv run mailbrief login
```

**What it does:** signs you in to Outlook **once**, in a browser window you can see, and saves the session so later runs can work headless (invisible) without asking you again.

**Step by step:**
1. Starts Chromium **headed**, so a window opens.
2. Reads the browser's identity string (`navigator.userAgent`) on a blank page, *before* going to Outlook. Outlook redirects several times while loading, and each redirect destroys the page's script context. Reading it afterwards used to crash with "Execution context was destroyed".
3. Opens `https://outlook.office.com/mail/`.
4. Waits for you to sign in: password, MFA, and **tick "Stay signed in"**.
5. When your inbox is visible, press **Enter** in the terminal.
6. Saves the browser's cookies and local storage (Playwright's `storage_state`) plus the user agent, **encrypted** with your `SESSION_ENCRYPTION_KEY`, to `data/session.enc`.

**Writes:** `data/session.enc` (encrypted; treat it like a password).

**When to run it again:**
- the first time;
- whenever `run` says *"Outlook session expired. Run `mailbrief login` again."*;
- after changing `SESSION_ENCRYPTION_KEY`.

How often Microsoft expires sessions is set by your organisation's security policy.

**Tips:**
- Log in on **the same machine** that runs the daily job. Copying sessions between machines or networks often forces a re-login.
- No email is read during login.

---

## 3. `mailbrief run`

```
uv run mailbrief run [--all] [--backfill] [--digest SCOPE] [--json] [--send] [--commit] [--no-password]
```

**What it does (default):** opens Outlook headless and finds emails that arrived since the last *committed* run. For each one it:
- fetches the full text, and image attachments where it has any;
- classifies it with the AI, using thread context;
- writes a morning **digest**;
- prints everything;
- saves the emails and digest to the encrypted archive.

It **never** deletes, moves, sends or marks anything as read. Every Outlook call it makes is read-only.

### Step by step (default run)
1. **Loads your session** from `data/session.enc`. If it's missing: *"No saved session. Run `mailbrief login` first."* (exit 2).
2. **Loads the archive** (`data/archive/*.enc|.json`) to learn which emails were already classified, so they're never sent to the AI twice.
3. **Loads the cursor** (`data/cursor.json`): the time of the newest processed email plus the last 500 processed IDs. With no cursor it looks back **24 hours**.
4. **Opens Outlook headless**:
   - listens to Outlook's own network traffic;
   - waits for the message list (or detects a redirect to the Microsoft login page, which means the session expired: exit 2);
   - **scrolls the list with the mouse wheel** until every conversation is loaded, in the **Focused** tab and then the **Other** tab;
   - picks up your email address from Outlook's startup data.
5. **Picks conversations** whose latest email is on or after the cursor time.
6. **Fetches every message** in those conversations, in any folder, so your Sent replies are included. It uses Outlook's own read-only `GetItem` call, 20 at a time.
7. **Selects the new inbox emails:** received ≥ cursor, ID not already processed, not sent by you.
8. **Downloads image attachments**, but only for emails that still need the AI. Real images only, 15 KB–5 MB, at most 3 per email, memory only.
9. **Saves the refreshed session.** Microsoft rotates cookies, so saving keeps the login alive longer.
10. **Builds threads:** groups messages by conversation, orders them parent-before-reply, marks emails you already answered as `replied`.
11. **Classifies** new emails with the AI, 4 conversations in parallel and each conversation's emails oldest first, so a reply sees its parent's summary:
    - text-only emails go to `AI_CLASSIFIER_MODEL` (qwen3.6:35b);
    - emails with images go to `AI_VISION_MODEL` (qwen3.8:27b).
12. **Saves** all fetched messages with their classifications to `data/archive/YYYY-MM.enc`. This happens *before* the digest, because a period digest reads them back from the archive.
13. **Writes the digest** for the chosen scope (default: the new emails) with `AI_DIGEST_MODEL` (qwen3.8:27b), from the classifications only, never from email bodies. The digest is saved to the archive too, with its scope.
14. **Prints** one line per email (`[Category/priority] date sender — subject ✓ replied`), then the digest, then timings and where it saved.
15. With `--send`, delivers the digest. With `--commit`, advances the cursor.

### Progress output (what you see while it runs)
Every phase announces itself on **stderr**, so it never mixes into `--json` output:
```
[00:00] Loading saved emails…
[00:04] Opening Outlook…
[00:05] Signed in; loading the inbox list…
[00:17] Loading Focused tab 288/288          ← counts up live as Outlook sends pages
[00:20] Loading Other tab 57/57
[00:50] Fetching full text 366/366           ← GetItem batches of 20
[00:51] Fetching images 2/2
[00:52] Classifying 9 emails with the AI…
[00:58] Classifying 9/9
[00:58] Saving to the archive…
|  Writing the new digest of 9 emails… 23s  ← spinner + seconds; "(part 3/6)" / "(merging 6 parts)" for big digests
[01:30] ✓ Writing the new digest of 9 emails (32s)
```
- `[mm:ss]` is the time since the command started.
- **On a terminal**, counters and the spinner redraw one line in place.
- **When piped or redirected** (`> log.txt`, the scheduler), there are no redraws: counters print at 25/50/75/100% and the spinner becomes a start line plus a ✓ line, so log files stay readable.
- A step that fails ends with **✗** instead of ✓.
- If a step is slow, the counter or spinner shows it's still working. Nothing silently hangs.

### Output (default)
```
9 inbox emails (since 2026-10-15 15:55), 9 need the AI, 0 already saved; inbox: 344 of 344 conversations; 2 of your replies / other-folder messages.
  [Urgent/p2] 15 Oct 23:07  OSA Hostel Admission Services — Reminder: AY2627 Sem 2 Acceptance Fee
  ...
📬 9 new emails — Newsletter 2 · Low Priority 2 · FYI 2 · ...
TOP PRIORITIES TODAY
• ...
timing: read 17s, classify 3s (9 emails, 0 with images), digest 35s
Saved (encrypted): 2026-10.enc in data\archive  (view with `mailbrief emails`)
```
If there are no new emails (and no `--digest` scope was asked for), it prints `No new emails, so no digest.` and stops.

### Flags

#### `--all`
Ignores the cursor and **processes every** inbox email, not just new ones: fetches, classifies anything not yet saved, and saves everything.
- Emails already in the archive **reuse their saved classification** (no AI call). Only unsaved ones go to the AI.
- **The digest still covers only new mail** (since the last commit). `--all` changes what's processed, not what's summarised. To summarise more, add `--digest` (below).

#### `--digest SCOPE`
Chooses **what the digest summarises**. Default: `new`.

| Scope | The digest covers | Typical size / time |
|---|---|---|
| `new` *(default)* | Emails new since the last `--commit`: the morning digest | a handful · ~30 s |
| `this-week` | Every saved inbox email since Monday | dozens · 1–2 min |
| `this-month` | Every saved inbox email since the 1st | ~150 · ~5 min |
| `last-month` | All of last calendar month | ~200 · ~5 min |
| `older` | Everything before last month | varies |
| `all` | Every saved inbox email | ~360 · several minutes |

- **Every email in the scope is read**, nothing is truncated:
  - up to 40 emails go in one AI call;
  - above that, the emails are split into **parts of 25**, summarised **4 at a time in parallel** (thinking off: plain summarising);
  - the parts are then **merged** by one call with thinking on, which connects related emails across the whole period.
  - The spinner shows `(part 3/6)`, then `(merging 6 parts)`.
- **Period scopes are read from the saved archive**, after this run's emails are saved. They also include mail saved by earlier runs or the backfill, and need no extra Outlook or classification work.
- Only real incoming mail counts: your sent replies and other-folder copies are left out.
- **Period digests use different headings:** `STILL OPEN` (needs action or a reply and doesn't look done), `DEADLINES & MEETINGS` (passed ones are marked), `KEY EVENTS`, `NOISE` (what made up the bulk). The morning digest keeps `TOP PRIORITIES TODAY / NEEDS A REPLY / DEADLINES & MEETINGS / FYI`.
- `--send` sends whichever digest was written.
- The digest is saved with its scope, and `mailbrief emails --digest` shows it, e.g. `── this month digest, written 17 Oct 09:12 ──`.
- If the scope has no emails: `No emails for a '<scope>' digest.`, and nothing is sent.

```
uv run mailbrief run --digest this-month             # month summary, printed
uv run mailbrief run --digest last-month --send      # last month's summary to Telegram
uv run mailbrief run --backfill --digest all         # archive the whole inbox, then summarise all of it
```

#### `--backfill`
Saves your **whole inbox** to the archive, once. Implies `--all`, plus:
- **no digest** (unless you add `--digest SCOPE`): it's for building history, not a morning summary;
- **oldest conversations first**, so when a later reply is classified, its earlier messages already have summaries;
- **saves every 25 classified emails**, so pressing **Ctrl+C keeps everything done so far**;
- **resumable:** run it again and it skips everything already saved, continuing where it stopped;
- **advances the cursor** to the newest email at the end, so the next normal `run` only sees new mail. This works even with `--send` and no digest (an earlier bug refused to advance in that case).

The progress line `Classifying 125/346` shows how far it has got. If Outlook loads fewer conversations than it reports, it warns you to run again. Re-running is safe and cheap.

#### `--json`
Prints the selected emails as a **JSON array on stdout** instead of the readable list. Each record includes the full body, classification, `replied`, `thread_size` and so on. All other messages (summary, digest, timings, warnings) go to **stderr**, so you can pipe the JSON:
```
uv run mailbrief run --json > today.json          # file contains only JSON
uv run mailbrief run --json | python -m json.tool  # pretty-print / validate
```
⚠️ The output contains full email text, unencrypted. Don't leave such files in the repo, because `*.json` exports aren't git-ignored.

#### `--send`
Sends the digest to every active destination in `data/destinations.json` (see `add-destination`).
- **Fits in one message** (≤ 4,000 units): sent as one message.
- **Too long:** sent as **one message per section**:
  - the `📬` header line plus the first section, then `DEADLINES & MEETINGS`, `KEY EVENTS`, `NOISE` and so on;
  - each message's first line is tagged `· k/n` (e.g. `NOISE · 5/5`), so you can see that all parts arrived.
- **A single section still too long:** split **on line breaks** into roughly equal parts (never one full message plus a tiny leftover). Follow-ups start with `<SECTION> (cont.)`. Lines are never cut in the middle, except a single line longer than a whole message.
- **Size is measured the way Telegram counts it** (UTF-16 units, so an emoji counts as 2), with a safety margin under Telegram's 4,096 limit.
- **Messages are paced** (0.5 s apart). If Telegram's flood control replies `429 Too Many Requests`, it waits the time Telegram asks for and retries (up to 3 times).
- **One failed message doesn't stop the rest.** The result is printed per destination:
  - `Sent to telegram: Tejas (private) (5 messages)`
  - `Failed to send to telegram: Tejas (private) (TelegramError: sent 4/5; message 3 failed: 400 Bad Request: …)`, with Telegram's own explanation rather than a bare "HTTP Error 400".
- One failing destination never blocks the others. Each result is printed.
- If there are no destinations, it says so.
- If no digest was written (no new mail, or `--backfill` without `--digest`), nothing is sent and that doesn't count as a failure.

#### `--commit`
Marks this run's emails as **processed** by advancing the cursor, so the next `run` won't show them again. It **refuses** (exit 1) in two cases:
- any email has only the list **preview**, not full text (the GetItem fallback was used). Moving the cursor would lose those emails' full text for good;
- `--send` was used and the digest reached **no** destination.

Without `--commit` you can rerun as often as you like and see the same emails (the AI isn't called again for saved ones).

#### `--no-password`
Saves this run's archive month files as **plain JSON** (`YYYY-MM.json`) instead of encrypted `.enc`, so you can open them in an editor.
- Each month has only one file. Saving a month in the other format deletes the old file.
- To go back to encrypted, run without the flag; the months it touches are rewritten as `.enc`.

### Common combinations
| Command | Use |
|---|---|
| `mailbrief run` | Try it / preview today's digest; nothing is marked processed |
| `mailbrief run --send --commit` | **The daily job:** digest to Telegram, then mark processed |
| `mailbrief run --backfill` | One-off: save the whole inbox to the archive |
| `mailbrief run --all` | Re-check the whole inbox (cheap: saved emails skip the AI); digest of new mail only |
| `mailbrief run --digest this-month` | Summary of everything this month (from the archive) |
| `mailbrief run --digest all --send` | Summary of every saved email, sent to Telegram |
| `mailbrief run --json > out.json` | Export today's new emails with classifications |
| `mailbrief run --no-password` | Same as `run`, but archive files are readable JSON |

### Exit codes
| Code | Meaning |
|---|---|
| 0 | Success (including "0 new emails") |
| 1 | Cursor not advanced (preview-only emails, or the digest wasn't delivered) |
| 2 | No saved session, or the session expired: run `mailbrief login` |

---

## 4. `mailbrief emails`

```
uv run mailbrief emails [--period P | --day YYYY-MM-DD | --search TEXT] [--show N | --thread N | --digest | --export FILE]
```

**What it does:** browses the **saved archive** offline. It never touches Outlook or the AI, so it's instant and works without internet. It reads encrypted `.enc` and plain `.json` month files alike, decrypting in memory only.

### Listing (no action flag)
```
uv run mailbrief emails
```
Shows **this week's** emails (since Monday), **grouped by thread**:
- threads are sorted by their latest activity;
- inside a thread, messages are in reply order (parent before replies), indented with `↳` by reply depth;
- your own messages appear as **You**;
- emails you already answered end with **✓ replied**;
- other-folder copies are tagged `[elsewhere]`, your sent messages `[sent]`.

```
   1  22 Sep 14:10  [Needs Reply/p3]     Amirhassan Monajemi — I need a student to help me with setting up a robot   ✓ replied
   2  22 Sep 14:37  [sent]                  ↳ You — Fw: I need a student to help me with setting up a robot

2 shown. ── this week 56 · this month 148 · last month 205 · older 3 ──  (--period NAME, --show N, --thread N)
```
The footer counts **inbox emails** in each period across the whole archive. The numbers on the left are what `--show` and `--thread` take.

### Filters (combine freely; they decide which emails are listed and numbered)
| Flag | Selects |
|---|---|
| *(none)* | This week (Monday 00:00 → now) |
| `--period this-week` | Monday of this week → now |
| `--period this-month` | 1st of this month → now (includes this week) |
| `--period last-month` | The whole previous calendar month |
| `--period older` | Everything before last month |
| `--day 2026-10-16` | Emails received on that date (in `DEFAULT_TIMEZONE`) |
| `--search fee` | Case-insensitive match in sender name, sender address, subject or body, across **all** periods unless you also give `--period` |

Periods are **computed when you view**, from the received date. Files never move, so "this week" is always correct.

### Actions
| Flag | Does |
|---|---|
| `--show N` | Opens email **#N from the same filtered list**: From, Subject, Received, attachments, the AI's category/priority/model, ✓ you replied, summary, action items, deadline. Then the **thread outline** (every message in the conversation, ▶ marking this one) and the full body. |
| `--thread N` | Prints the **whole conversation** of email #N, every message in reply order with its full body, indented by depth. |
| `--digest` | Prints the digest(s) saved on `--day` (default **today**), each headed with its scope and the time it was written, e.g. `── this month digest, written 17 Oct 09:12 ──`. |
| `--export FILE` | Writes the listed emails (same filters) to `FILE` as **plain JSON**. ⚠️ Unencrypted: keep it out of the repo. |
| `--digest --send` | **Resends** the latest digest saved on `--day` (default today) to all destinations, split exactly as `run --send` would. No Outlook and no AI involved, so it's instant. Use it when a send failed or you want a digest again. Exits 1 if there's no saved digest or no destination received it. `--send` without `--digest` is rejected (exit 2). |

Numbering is shared: use the **same filters** with `--show`/`--thread` as when you listed:
```
uv run mailbrief emails --search fee             # list: find the one you want, e.g. #2
uv run mailbrief emails --search fee --show 2    # open it
uv run mailbrief emails --search fee --thread 2  # read the whole conversation
```

### Errors and exit codes
| Code | Meaning |
|---|---|
| 0 | OK (also when nothing matches) |
| 1 | `--show/--thread N` is out of range, or an `.enc` file can't be decrypted. The message names the file: `can't decrypt 2026-10.enc: SESSION_ENCRYPTION_KEY is not the key it was saved with` |
| 2 | `--day` isn't a valid `YYYY-MM-DD` date |

---

## 5. `mailbrief add-destination`

```
uv run mailbrief add-destination telegram [--chat-id ID]
```

**What it does:** registers where digests are sent. Destinations can **only** be added this way, from your own machine: the bot never listens for messages, so nobody can sign themselves up.

### Interactive (recommended)
1. Create a bot with **@BotFather** (`/newbot`) and put `TELEGRAM_BOT_TOKEN=` in `.env`.
2. In BotFather: `/setjoingroups` → your bot → **Disable**, so nobody can add your bot to their groups.
3. Send your bot any message in Telegram.
4. Run `uv run mailbrief add-destination telegram`:
   - it calls Telegram's `getUpdates` **once** to list chats that recently messaged the bot;
   - you pick one by number;
   - it's saved to `data/destinations.json` and a **test message** ("✅ MailBrief will send your morning digest here.") is sent there.

### Direct
`--chat-id 123456789` skips the lookup and saves that chat ID directly. No test message is sent.

**Writes:** `data/destinations.json`: `[{"type": "telegram", "target": "<chat id>", "label": "...", "active": true}]`. Adding the same chat again replaces its entry; there are no duplicates. To pause a destination, set `"active": false` by hand.

### Exit codes
| Code | Meaning |
|---|---|
| 0 | Added |
| 1 | No chats found (message the bot first) or invalid choice |
| 2 | Unknown destination type (only `telegram` exists so far) |

---

## 6. Developer commands

### Run the tests
Each test file is a plain script: `assert`s plus a `__main__` runner, with no test framework. It prints `ok` or raises:
```
uv run python tests/test_owa_network.py   # Outlook JSON parsing, GetItem records, image filter, your-address lookup
uv run python tests/test_cursor.py        # new-email selection, dedupe, cursor refusal on previews
uv run python tests/test_ai.py            # JSON extraction, classification validation, quote trimming
uv run python tests/test_telegram.py      # one message per section, "(cont.)" splits on lines, k/n tags, UTF-16 sizing, heading detection
uv run python tests/test_archive.py       # encryption, merge/dedupe, months, migration, periods, pruning
uv run python tests/test_threads.py       # reply ordering, depth, "you replied", AI context lines
uv run python tests/test_progress.py      # progress output when piped: quarter counters, ✓/✗ lines, no "\r"
```
All of them in one go (Git Bash):
```
for t in tests/test_*.py; do echo -n "$t: "; uv run python $t || break; done
```
The tests need **no network, no Outlook and no AI**: they use made-up data shaped like the real responses.

### Help for any command
```
uv run mailbrief --help
uv run mailbrief run --help
uv run mailbrief emails --help
```

### Add a dependency
```
uv add <package>      # updates pyproject.toml + uv.lock and installs it
```

---

## 7. Configuration (`.env`)

| Variable | Default | Affects |
|---|---|---|
| `SESSION_ENCRYPTION_KEY` | *(required)* | Encrypts `session.enc` and archive `.enc` files |
| `AI_BASE_URL` | `https://soclaas-api.comp.nus.edu.sg/v1` | Which OpenAI-compatible endpoint `run` calls |
| `AI_API_KEY` / `SOCLAAS_API_KEY` | system env var | AI key (`AI_API_KEY` wins if set) |
| `AI_CLASSIFIER_MODEL` | `qwen3.6:35b` | Classifies text-only emails |
| `AI_VISION_MODEL` | `qwen3.8:27b` | Classifies emails with image attachments |
| `AI_DIGEST_MODEL` | `qwen3.8:27b` | Writes the digest (thinking on) |
| `TELEGRAM_BOT_TOKEN` | *(none)* | Needed by `add-destination` and `run --send` |
| `DEFAULT_TIMEZONE` | `Asia/Singapore` | Displayed times, `--day`, periods, which month file an email goes in |
| `ARCHIVE_DAYS` | `0` (forever) | If > 0, `run` deletes month files that ended more than this many days ago |
| `BROWSER_WS_URL` | *(empty)* | Empty = local Chromium. Set it to connect to a Browserless/CDP browser instead |

Listed in `.env.example` but **not used by the code yet** (planned for later milestones): `FALLBACK_AGENT`, `DATABASE_URL`, `DEFAULT_RUN_TIME`, `SORT_MODE`, `RESTORE_UNREAD`.

---

## 8. Files the commands create

| File | Created by | Contents | Sensitive? |
|---|---|---|---|
| `data/session.enc` | `login`, refreshed by every `run` | Outlook cookies + browser identity, encrypted | **Yes**: full mailbox access |
| `data/cursor.json` | `run --commit`, `run --backfill` | Newest processed time + last 500 email IDs | No (IDs only) |
| `data/archive/YYYY-MM.enc` | every `run` | That month's emails, classifications, digests, encrypted | Yes (encrypted) |
| `data/archive/YYYY-MM.json` | `run --no-password` | Same, **plain text** | **Yes, unencrypted** |
| `data/destinations.json` | `add-destination` | Telegram chat IDs | Mildly |
| whatever `--export FILE` / `--json >` names | you | Plain email JSON | **Yes, unencrypted** |

All of `data/` and `.env` are git-ignored. Exported files elsewhere are **not**.

---

## 9. Recipes

**First-time setup**
```
uv sync
uv run playwright install chromium --no-shell
# create .env (see section 1)
uv run mailbrief login
uv run mailbrief run --backfill        # optional: archive the whole inbox once
uv run mailbrief add-destination telegram
```

**Every morning** (by hand now, by the scheduler from M5)
```
uv run mailbrief run --send --commit
```

**"What did that email say?"**
```
uv run mailbrief emails --search "acceptance fee"
uv run mailbrief emails --search "acceptance fee" --thread 1
```

**Re-read this morning's digest**
```
uv run mailbrief emails --digest
```

**A digest didn't arrive in Telegram: send it again** (no regeneration)
```
uv run mailbrief emails --digest --send                  # today's latest digest
uv run mailbrief emails --digest --day 2026-10-16 --send # an earlier day's
```

**"What happened this month / last month?"**
```
uv run mailbrief run --digest this-month           # or last-month, older, all; add --send for Telegram
```

**Keep a log of a run** (clean lines, no spinner frames)
```
uv run mailbrief run --send --commit > run.log 2>&1
```

**Session expired** (`run` exits with code 2)
```
uv run mailbrief login
```

**Start "new mail" tracking from scratch**: delete `data/cursor.json`. The next run looks back 24 h. The archive is unaffected and still prevents repeat AI calls.

---

## 10. Exit codes at a glance

| Command | 0 | 1 | 2 |
|---|---|---|---|
| `login` | saved | (n/a) | (n/a) |
| `run` | success | cursor not advanced | no session / session expired |
| `emails` | success | bad number / can't decrypt | bad `--day` |
| `add-destination` | added | no chats / bad choice | unknown type |
