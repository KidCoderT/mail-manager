# MailBrief: Command Reference

Every command in this repository: what it does, step by step, what it reads and writes, each flag, exit codes, and common combinations.

Run all commands from the project folder (`mail-manager/`). They are run with **`uv run`**, which uses the project's own Python environment (`.venv`), so you never need to activate a virtualenv.

- [1. One-time setup commands](#1-one-time-setup-commands)
- [2. `mailbrief login`](#2-mailbrief-login)
- [3. `mailbrief run`](#3-mailbrief-run)
- [4. `mailbrief emails` (and `mailbrief events`, the UPCOMING EVENTS calendar)](#4-mailbrief-emails)
- [5. `mailbrief labels` and `mailbrief rules`: MB: labels in Outlook, and your own](#5-mailbrief-labels)
- [6. `mailbrief add-destination`](#6-mailbrief-add-destination)
- [7. Running automatically: `serve`, `stop`, `status`, `autostart`, hosting](#7-running-automatically)
- [8. Developer commands (tests, checks)](#8-developer-commands)
- [9. Configuration (`.env`) that changes command behaviour](#9-configuration-env)
- [10. Files the commands create](#10-files-the-commands-create)
- [11. Recipes: common workflows](#11-recipes)
- [12. Exit codes at a glance](#12-exit-codes-at-a-glance)
- [13. Ask your inbox: `index`, `chat`, `bot` and the Telegram chat](#13-ask-your-inbox)

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
- whenever `run` says *"Outlook session expired. Run `mailbrief login` again."* (on a server: `/login` in Telegram, or `login --remote`);
- after changing `SESSION_ENCRYPTION_KEY`.

How often Microsoft expires sessions is set by your organisation's security policy.

**Tips:**
- Log in on **the same machine** that runs the daily job. Copying sessions between machines or networks often forces a re-login.
- No email is read during login.

### `mailbrief login --remote`: sign in from any browser (servers with no screen)
```
uv run mailbrief login --remote      # prints a one-time link
```
The same as **`/login`** in Telegram. Use it when MailBrief runs on a server (Railway, Docker) where no window can open. **Step by step:**

1. **The link.** A headless Chromium opens the Microsoft sign-in page in a **fresh** browser profile, never your saved session. A small web server starts on `$PORT` (default 8080), and you get a link: `https://<your-app>/login#<random token>`.
2. **Start.** Open the link, then tap **Start**. You see a live picture of that browser, refreshed every half second:
   - tap the picture to click;
   - type in the box and press **Send**, which hides your typing unless you tick "show";
   - the **Enter**, **Tab** and **⌫** buttons press those keys.
3. **Sign in** as usual: NUS SSO, MFA, and tick **Stay signed in**.
4. **Saved and checked.** When your inbox list shows, the session is saved to `data/session.enc`, then checked by opening Outlook again with it.
   - On success you get **"Logged in ✅"**.
   - Then the web server and browser stop, and the link is dead.

**Only you can use the link:**
- **The token is in the `#` part,** which browsers never send to servers, so it isn't in any log.
- **It works once.** Tapping Start uses up the token and gives *your* browser a random private cookie. Every later request needs that cookie, so a forwarded or copied link does nothing. Link previews can't use it up either.
- **It's open for at most 10 minutes,** and closes as soon as you're signed in. Otherwise nothing listens at all.
- **`https://` only.** It refuses any other address, so your password never crosses the internet unencrypted. The exception is `http://localhost`, for trying it on your PC, where it listens on this PC only.
- **Your inbox is never shown.** Only Microsoft's sign-in pages are pictured; once Outlook itself opens, the picture is hidden.
- **Nothing is written down.** Screenshots and your typing stay in memory, and logs only say "sign-in page opened/closed".
- **It holds the run lock,** so a scheduled run waits for it, and vice versa: *"A MailBrief run is using Outlook right now"*.

**The address:** `PUBLIC_URL`, else `RENDER_EXTERNAL_URL` on Render or `https://$RAILWAY_PUBLIC_DOMAIN` on Railway (both set automatically), else `http://localhost:$PORT`.

**Try it on your PC:** `uv run mailbrief login --remote`, or `/login` while `serve` runs, then open the link **on this PC**. A `localhost` link only works on the machine itself, not on your phone.
- **If the port is blocked:** Windows often reserves 8080, so on your PC without `PUBLIC_URL` it falls back to any free port, and the link shows which one.
- **On a server,** or with `PUBLIC_URL` set, the port is never changed silently. A blocked port is reported instead: *"Couldn't open the sign-in page on port …"*.

**Sign in from your phone while MailBrief runs on your PC:**
1. Install cloudflared once: `winget install --id Cloudflare.cloudflared`.
2. Add `LOGIN_TUNNEL=cloudflared` to `.env` and restart `serve`.
3. Send `/login`. About 15 seconds later you get a `https://….trycloudflare.com` link that opens on your phone.

- **How it works:** a Cloudflare quick tunnel to the page, which itself still listens on 127.0.0.1 only. It needs no account, and it's stopped when the sign-in ends, so the address dies with it.
- **Privacy:** Cloudflare decrypts the traffic in the middle, your password included. That's why it's opt-in.
- **If cloudflared is missing or doesn't connect within 30 s,** you get *"Couldn't open the sign-in page: cloudflared …"* (exit code 2).

**Exit codes:**
| Code | Meaning |
|---|---|
| 0 | Signed in |
| 1 | Timed out, or the saved login didn't work |
| 2 | `PUBLIC_URL` isn't `https://`, the port is in use or blocked, or cloudflared didn't start |
| 3 | A run is using Outlook |

---

## 3. `mailbrief run`

```
uv run mailbrief run [--all] [--backfill] [--digest SCOPE] [--json] [--send] [--commit] [--no-password] [--quiet]
```

**What it does (default):** opens Outlook headless and finds emails that arrived since the last *committed* run. For each one it:
- fetches the full text, and image attachments where it has any;
- classifies it with the AI, using thread context;
- writes a morning **digest**;
- prints everything;
- saves the emails and digest to the encrypted archive;
- puts **MB: labels** (categories) on the emails in Outlook (section 5).

It **never** deletes, moves, sends or marks anything as read. The only thing it ever changes in Outlook is MailBrief's own `MB:` categories, and a code-level guard refuses any other kind of write.

### Step by step (default run)
1. **Loads your session** from `data/session.enc`. If it's missing: *"No saved session. Run `mailbrief login` first."* (exit 2).
2. **Loads the archive** (`data/archive/*.enc|.json`) to learn which emails were already classified, so they're never sent to the AI twice.
3. **Loads the cursor** (`data/cursor.json`): the time of the newest processed email plus the last 500 processed IDs. With no cursor it looks back **24 hours**.
4. **Opens Outlook headless**:
   - listens to Outlook's own network traffic;
   - waits for the message list (or detects a redirect to the Microsoft login page, which means the session expired: exit 2);
   - **scrolls the list with the mouse wheel** until every conversation is loaded, in the **Focused** tab and then the **Other** tab;
   - picks up your email address from Outlook's startup data.
5. **Picks conversations** whose latest email is on or after the cursor time, plus any holding an email the AI failed on in the last 7 days.
6. **Fetches every message** in those conversations, in any folder, so your Sent replies are included. It uses Outlook's own read-only `GetItem` call, 20 at a time.
7. **Selects the new inbox emails:** received ≥ cursor, ID not already processed, not sent by you. **Emails the AI failed on** (saved as Unclassified) in the last 7 days are selected again, even though the cursor has moved past them, and are classified and put in this digest. The log says *"Retrying N email(s) the AI failed on earlier"*.
8. **Collects images**, but only for emails that still need the AI, in memory only, at most 4 images (the endpoint's limit) and 8 MB per email:
   - attached images of 15 KB–5 MB and inline ones (posters in the body) of 30 KB–5 MB, through `GetAttachment`;
   - with `REMOTE_IMAGES=on` (the default), **linked images**: a read-only GetItem reads the emails' HTML, keeps https image URLs that don't look like icons, logos or trackers, and downloads them with safety checks (no local-network addresses, no redirects, size and type limits). The senders' image servers see your IP. Details: README §3.10.
9. **Saves the refreshed session.** Microsoft rotates cookies, so saving keeps the login alive longer.
10. **Builds threads:** groups messages by conversation, orders them parent-before-reply, marks emails you already answered as `replied`.
11. **Classifies** new emails with the AI, 4 conversations in parallel and each conversation's emails oldest first, so a reply sees its parent's summary:
    - text-only emails go to `AI_CLASSIFIER_MODEL` (qwen3.6:35b);
    - emails with images go to `AI_VISION_MODEL` (qwen3.6:35b, which reads images too);
    - besides category and priority, each email's **events** are listed (name, one-line detail, date, time, place, link, sign-up deadline), from its text and images.
12. **Saves** all fetched messages with their classifications to `data/archive/YYYY-MM.enc`. This happens *before* the digest, because a period digest reads them back from the archive.
13. **Labels emails in Outlook** (unless `OUTLOOK_LABELS=off`): every archived inbox email whose `MB:` labels aren't what they should be, up to 400 per run. On the first run that's your whole archive; after that, just the new ones. A failure here only prints a warning. Details: section 5.
14. **Writes the digest** for the chosen scope (default: the new emails) with `AI_DIGEST_MODEL` (qwen3.8:27b), from the classifications only, never from email bodies. The digest is saved to the archive too, with its scope.
15. **Prints** one line per email (`[Category/priority] date sender — subject ✓ replied`), then the digest, then timings and where it saved.
16. With `--send`, delivers the digest, then the **UPCOMING EVENTS** calendar (built by code from the whole archive: events in the next `EVENTS_DAYS` days, 🆕 for this digest's emails). With `--commit`, advances the cursor.

### Progress output (what you see while it runs)
Every phase announces itself on **stderr**, so it never mixes into `--json` output:
```
[00:00] Loading saved emails…
[00:04] Opening Outlook…
[00:04] Signed in
[00:07] Loading the inbox list…
[00:17] Loading Focused tab 288/288          ← counts up live as Outlook sends pages
[00:20] Loading Other tab 57/57
[00:50] Fetching full text 366/366           ← GetItem batches of 20
[00:51] Fetching images 2/2
[00:52] Classifying 9 emails with the AI…
[00:58] Classifying 9/9
[00:58] Saving to the archive…
[00:59] Labelling 9 emails in Outlook…         ← opens Outlook again briefly (no scrolling)
[01:07] Labelling in Outlook 9/9
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
- **Every bullet ends with ↗ links** to the emails it's about; tap one to open that email in Outlook. The AI writes `[3]`-style refs, and code turns them into links (section 13). Saved digests keep the refs, so `emails --digest --send` resends them with links.
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
- **After the digest, the UPCOMING EVENTS calendar** goes as its own message (see [`mailbrief events`](#mailbrief-events-the-upcoming-events-calendar)). It's sent only when the digest reached a destination, and if it fails it's reported but never holds back the cursor. `EVENTS_DAYS=0` turns it off.

#### `--commit`
Marks this run's emails as **processed** by advancing the cursor, so the next `run` won't show them again. It **refuses** in two cases (exit 4 for previews, exit 1 for no delivery):
- any email has only the list **preview**, not full text (the GetItem fallback was used). Moving the cursor would lose those emails' full text for good;
- `--send` was used and the digest reached **no** destination.

Without `--commit` you can rerun as often as you like and see the same emails (the AI isn't called again for saved ones).

#### `--no-password`
Saves this run's archive month files as **plain JSON** (`YYYY-MM.json`) instead of encrypted `.enc`, so you can open them in an editor.
- Each month has only one file. Saving a month in the other format deletes the old file.
- To go back to encrypted, run without the flag; the months it touches are rewritten as `.enc`.

#### `--quiet`
Leaves out the per-email lines and the digest text. Only progress, counts and results are printed (`Sent to telegram: …`).
- This is what `serve` uses, so log files never contain email subjects or content.
- The digest itself is still written, saved and sent as normal.

### Only one run at a time
`run` holds a lock (`data/run.lock`) while it works. If another run is already going (a scheduled one, or another terminal), it prints `Another MailBrief run is in progress…` and exits with code 3. Nothing is touched.
- The lock is held by the operating system, so it disappears when the process ends, even after a crash. There's never a stale lock to delete.

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
| 1 | Cursor not advanced: the digest reached no destination |
| 2 | No saved session, or the session expired: run `mailbrief login` |
| 3 | Another run is in progress (nothing done) |
| 4 | Digest sent, but `--commit` refused because only list previews were available. The cursor is kept, so those emails are read again next time. `serve` does **not** retry this, because a retry would just send the same digest again |

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
| `--digest --send` | **Resends** the latest digest saved on `--day` (default today) to all destinations, split exactly as `run --send` would, followed by a freshly built UPCOMING EVENTS calendar. No Outlook and no AI involved, so it's instant. Use it when a send failed or you want a digest again. Exits 1 if there's no saved digest or no destination received it. `--send` without `--digest` is rejected (exit 2). |

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

### `mailbrief events`: the UPCOMING EVENTS calendar
```
uv run mailbrief events               # print the next 14 days (EVENTS_DAYS)
uv run mailbrief events --days 30     # look further ahead
uv run mailbrief events --send        # send it to all destinations now
uv run mailbrief events --past 30     # also the last 30 days (past days marked (PAST))
uv run mailbrief events --past 30 --days 0   # only the last 30 days
```
- **Built by code, not AI,** from the `events` the classifier saved for every email: no Outlook, no AI, instant.
- **Grouped by day** (`FRI 23 OCT`), soonest first. Within a day, ⭐ boosted events (your rules, section 5) come first, then by time.
- **Each event:** time · name · place, then its one-line detail, then the sign-up deadline ("sign-up closed" once passed) and link.
- **The same event in two emails** (same name and date) is shown once, with the details of both.
- **Past events are dropped.** Events with no date only show in the morning message on the day their email arrives (under DATE NOT GIVEN), so `mailbrief events` on its own lists dated events only.
- **🆕** marks events from the emails the current digest covers (only in the message `run --send` sends).
- **Older mail has no events** until it's re-classified: `labels retag --period this-month` (section 5).
- **Past events: `--past N`** adds the last N days, in calendar order, with past days headed like `MON 13 OCT (PAST)`. Past events skip the sign-up line (it would always say "closed") but keep their link. `--days 0` drops the days ahead, so `--past 30 --days 0` is a list of the last month's events; `--send` sends exactly what's printed. Only emails that have events saved show up: older mail needs `labels retag --period …` first.
- Exit codes: 0 done (or nothing found), 1 the archive can't be read or `--send` reached no destination, 2 `--days` or `--past` isn't 0–365, or `--days 0` without `--past`.

---

## 5. `mailbrief labels`

*(and `mailbrief rules`, for labels you define yourself: [below](#your-own-labels-mailbrief-rules))*

MailBrief puts its classification **on the emails in Outlook**, as Outlook *categories*:

```
Prof Tan   Submit form by Fri    [MB: Urgent] [MB: P1]
NUS News   Weekly roundup        [MB: Newsletter] [MB: P5]
Ana        Lunch tomorrow?       [MB: Needs Reply] [MB: P2]
```
Each inbox email gets **two labels**: its category and its priority.

| Category label | Colour | Priority label | Colour |
|---|---|---|---|
| `MB: Urgent` | red | `MB: P1` | dark red |
| `MB: Needs Reply` | orange | `MB: P2` | orange |
| `MB: Meetings` | purple | `MB: P3` | yellow |
| `MB: FYI` | blue | `MB: P4` | teal |
| `MB: Newsletter` | green | `MB: P5` | grey |
| `MB: Low Priority` | grey | | |

- **Where they show:** Outlook on the web, desktop and phone, because categories live on the server.
- **Filtering:** search `category:"MB: Urgent"`, or Filter → Categories.
- **Colours:** the 11 categories are created once in your category list (Settings → Mail → Categories). Recolour or rename them there if you like; MailBrief never changes an existing one.
- **Your own categories are never touched.** MailBrief reads each email's categories first and swaps only the `MB:` ones.
- **Your own labels** (courses, professors, topics) sit beside these two; see [Your own labels](#your-own-labels-mailbrief-rules).
- **Only these emails get labels:** inbox emails from other people with a real classification. Not your sent mail, other-folder copies, `Unclassified` emails, or list-preview-only records.
- **Nothing else changes:** read/unread state, folder and flags stay as they were. The sender isn't notified (categories are private to your mailbox).

### When labels are applied
**Automatically, in every `mailbrief run`** (and so in every scheduled run):
- It labels every archived email whose labels aren't what they should be, up to 400 per run. The first run did your whole archive (360 emails in about a minute).
- If an email is **reclassified**, its `MB:` labels are swapped, never added to.
- If you **remove a label by hand** in Outlook, MailBrief doesn't put it back. It remembers what it applied.
- Turn it off with `OUTLOOK_LABELS=off` in `.env`.

### `mailbrief labels status`
```
Outlook labels: on
              labelled  pending  cleared
this-week           60        0        0
this-month         152        0        0
last-month         205        0        0
older                3        0        0
all                360        0        0
```
- **labelled:** emails carrying MailBrief labels.
- **pending:** emails the next run will label.
- **cleared:** emails you removed labels from. These are left alone until you `apply` again.

### `mailbrief labels clear`: remove labels
```
uv run mailbrief labels clear --period last-month    # or this-week, this-month, older
uv run mailbrief labels clear --days 30              # emails from the last 30 days
uv run mailbrief labels clear --all                  # every email MailBrief labelled
uv run mailbrief labels clear --all --colours        # …and delete the 11 MB: categories from your category list
```
- **Confirmation:** it shows how many emails (and lists them when there are 5 or fewer), then asks `Go ahead? [y/N]`. Add `--yes` to skip the question.
- **What it removes:** only `MB:` labels. Your own categories stay.
- **`--colours`:** also deletes the MB: categories from your list, the same as deleting them in Settings. That strips them from **every** email, even ones MailBrief has lost track of. Use it for a complete reset.
- **Cleared emails stay cleared:** runs don't re-label them. New mail is still labelled while `OUTLOOK_LABELS=on`, and `clear --all` reminds you of that.
- **Other options:** `--dry-run` shows what would change without touching Outlook. `--limit N` handles at most N emails, newest first.
- Clearing 360 emails takes about a minute.

#### One of your own labels: `--label`
```
uv run mailbrief labels clear --label MA1521 --dry-run     # which emails carry MB: MA1521
uv run mailbrief labels clear --label MA1521               # remove it from every email MailBrief gave it to
uv run mailbrief labels clear --label MA1521 --everywhere  # …from EVERY email in the mailbox, and delete it from your category list
```
- **Why you need it:** when you remove a rule (`rules remove course MA1521`), emails already labelled **keep** the label as history. This is how you take it off.
- **Remove the rule first.** If a rule still gives the label, it's refused (exit 2): the next run would only put it back.
- **Default scope is all periods**; narrow it with `--period` / `--days` / `--limit`.
- **`--everywhere`** also catches emails MailBrief never tracked (e.g. ones you labelled by hand with the same name). It uses the same Outlook operation as deleting the category in Settings, so it ignores `--period` / `--days` / `--limit`: the label goes from every email.
- **Always asks first** (`Go ahead? [y/N]`, or `--yes`). The archive forgets the label, so runs never put it back.
- Only your own labels: built-in ones (`MB: FYI`, `MB: P2`…) are cleared with `--period` / `--days` / `--all` above.

### `mailbrief labels apply`: label now
```
uv run mailbrief labels apply                     # everything pending, plus anything you cleared
uv run mailbrief labels apply --period this-month
uv run mailbrief labels apply --limit 1 --dry-run # which email would be next, and with which labels
```
- Use it after a `clear` to bring labels back, or to label without waiting for a run.
- It also re-creates the coloured categories if you deleted them.
- After adding a course or sender rule, `labels apply --dry-run` shows exactly which emails will get it. No AI involved.

### `mailbrief labels retag`: ask the AI again
```
uv run mailbrief labels retag --period this-month --dry-run   # how many emails, how many AI calls
uv run mailbrief labels retag --period this-month             # re-classify them with your current profile and topics
uv run mailbrief labels retag --days 7 --yes
```
- **When:** after adding or changing a **topic** or your **profile**. Those are AI decisions, so older mail only gets them when the AI is asked again. Course and sender rules never need this.
- **Cost:** about one AI call per email, a few minutes for a month. It asks before starting (`--yes` skips the question).
- **Events too:** the re-classification also lists each email's events, so this is how older mail gets into the UPCOMING EVENTS calendar.
- **Images:** they're never saved, so they're fetched again: attached and inline ones from Outlook, and linked ones (`REMOTE_IMAGES=on`), which also opens Outlook to read the HTML. With `REMOTE_IMAGES=off` and no image attachments, no Outlook is needed.
- **Failed calls keep the old classification.** Outlook labels are updated straight after.
- Needs `--period` or `--days`. Never at the same time as a run (exit 3).

### Exit codes
| Code | Meaning |
|---|---|
| 0 | Done (or nothing to do, or a dry run) |
| 1 | You answered no (or there's no terminal and no `--yes`), or the archive or `data/rules.json` can't be read |
| 2 | `clear` without `--period` / `--days` / `--all` / `--label`; `--label` naming a built-in label or one a rule still gives; `--everywhere` without `--label`; `retag` without `--period` / `--days`; or Outlook needs `mailbrief login` |
| 3 | A run is in progress. Labels never change at the same time as a run |

### Safety, in code
Every request MailBrief sends to Outlook passes one check (`check_request` in `owa_network.py`) before it leaves your PC:
- **reads** (`GetItem`, `GetAttachment`) are allowed;
- **`UpdateItem`** is allowed only if every change sets or deletes the **Categories** field and nothing else, with "save only" (no sending);
- **the category list** may only gain or lose names starting with `MB: `;
- **anything else** (move, delete, send, mark read, rules…) is refused with an error before any network call.

Your own labels need no new permission: they're `MB: ` categories too.

### Your own labels: `mailbrief rules`
Labels you define, beside the category and priority. They live in **`data/rules.json`** (personal, git-ignored, plain JSON you can also edit by hand).

```
uv run mailbrief rules list                                           # your rules + how many saved emails each matches
uv run mailbrief rules profile "Year 2 CS student looking for internships, hackathons and networking"
uv run mailbrief rules add course CS1101S                             # → MB: CS1101S
uv run mailbrief rules add course CS2103T --priority 2                # …and at least P2
uv run mailbrief rules add sender tan@nus.edu.sg --label "Prof Tan" --direct --priority 1
uv run mailbrief rules add sender "Career Centre" --label Careers --boost
uv run mailbrief rules add topic Networking "career fairs, meetups, recruiter outreach, hackathons, tech talks" --priority 2
uv run mailbrief rules remove course MA1521                           # old emails keep MB: MA1521 (labels clear --label removes it)
```

| Kind | Matched by | Gives |
|---|---|---|
| **course** | **Code, no AI:** the code as a whole word in the subject, the sender's name or the first 1,000 characters of the body (so course-listing newsletters don't collect every code). Case doesn't matter. | `MB: CS1101S` |
| **sender** | **Code, no AI:** an exact address, or (without `@`) part of the sender's name. `--direct`: only when **you are the only To recipient**, i.e. private mail, not a class announcement. (Mail merges, such as individually sent grade emails, also count as "only you".) | `MB: Prof Tan` |
| **topic** | **AI:** the classifier gets your topic descriptions and says which fit. Only names from your list are accepted. | `MB: Networking` |
| **profile** | **AI:** who you are and what you want. The classifier uses it for priority and to judge boosts; the digest sees it too. | (no label) |

- **`--priority N`:** matching mail is at least P*N*. The more important of the AI's priority and the rule's wins, so `MB: P<n>` changes too.
- **Boosted ⭐:** listed under **OPPORTUNITIES & EVENTS** in the digest, and raised to at least P2 (unless a rule sets its own floor). An email is boosted when:
  - it gets one of your **topic** labels **and** the AI judges it fits your **profile** (without a profile, any topic label boosts), or
  - it matches a **course or sender** rule added with `--boost` (e.g. your career office).
- **Adding again replaces** the rule with the same code / address / topic name.
- **Courses and senders apply without AI:** the next run (or `labels apply`) relabels the whole archive. **Topics and profile** apply to new mail; `labels retag` does older mail.
- **Removing a rule keeps its labels** on emails that already have them, as history. `labels clear --label NAME` removes them.
- **Names** are up to 40 characters, without `,` or `;`, and can't be a built-in label (`Urgent`, `P2`…).
- **Colours:** courses dark blue, senders cranberry, topics dark green (recolour them in Outlook if you like).
- **A broken `rules.json`** (say, a typo while hand-editing) never breaks the morning digest: the run warns, classifies without rules, and **skips Outlook labelling** that run so your labels aren't stripped. `rules list` shows the exact error.
- **`emails --show N`** shows an email's own labels (`Yours: …`), whether it's boosted, and its `To:` line ("only you" for private mail).
- **Telegram commands** (`/label add …`) come with the Telegram chat in M7.

#### One-off after upgrading: recipients, image lists and events
`--direct` needs each email's To/Cc, and the newer image rule (inline posters) needs each email's refreshed image list. Older saved emails have neither. Fill them in once:
```
uv run mailbrief run --backfill                      # right after your morning run
uv run mailbrief labels retag --period this-month    # optional: events (and topic tags) for this month's mail
```
- `run --backfill` re-reads every inbox email with GetItem but **asks the AI only about emails it hasn't classified yet**. It also advances the cursor, so run it **right after your morning run**; otherwise mail that arrived in between is skipped by the next morning digest.
- `labels retag` then re-classifies with the AI (about one call per email), which adds events. Pick the period you care about; future events only come from recent mail anyway.
- New mail always has all of this.

---

## 6. `mailbrief add-destination`

```
uv run mailbrief add-destination telegram [--chat-id ID]
```

**What it does:** registers where digests are sent, and (from M7) who may chat with the bot. Destinations can **only** be added this way, from your own machine. The chat listener answers only these private chats, so nobody can sign themselves up.

**While `serve` is running:** its chat listener is also reading the bot's messages (`getUpdates`), so the interactive lookup can come back empty or clash (Telegram allows one reader at a time). Stop `serve` first (`mailbrief stop`), or use `--chat-id`.

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

## 7. Running automatically

Typing `mailbrief run --send --commit` every morning gets old. **`mailbrief serve`** runs forever and fires the runs itself, on a schedule you choose. The same command is used everywhere:

| Where | What starts `serve` | What keeps it running |
|---|---|---|
| Your PC, by hand | You, in a terminal | The terminal window (closing it stops it) |
| Your PC, automatically | Windows Task Scheduler, at logon (`mailbrief autostart on`) | Runs hidden (no window) until you `stop` it or log out |
| A server | Docker (`docker compose up -d`) | Docker restarts it after crashes and reboots |

### The schedule: `RUN_AT`
Put it in `.env` (or pass `serve --at "…"` to try one without editing `.env`). Entries are separated by `;`, and each is **`<days> <HH:MM> [scope]`**:

```
RUN_AT="daily 07:30"                                   # once a day (the default when RUN_AT is unset)
RUN_AT="daily 07:30; daily 18:00"                      # twice a day
RUN_AT="sun 20:00 this-week"                           # once a week: a summary of the week
RUN_AT="weekdays 08:00; weekends 10:00"                # later at the weekend
RUN_AT="mon,wed,fri 07:30"                             # chosen days
RUN_AT="daily 07:30; sun 20:00 this-week; day-1 09:00 last-month"   # daily + weekly + monthly
```

| Part | Allowed values |
|---|---|
| days | `daily`, `weekdays` (Mon–Fri), `weekends`, `mon` … `sun`, `day-N` (day of the month, 1–31). Comma lists mix freely: `mon,day-15` |
| time | 24-hour `HH:MM`, in `DEFAULT_TIMEZONE` |
| scope | `new` (default), `this-week`, `this-month`, `last-month`, `older`, `all`: the same scopes as `run --digest` |

What each entry runs:
- a **`new`** entry runs `mailbrief run --send --commit --quiet`: the normal "new mail since last time" digest; the cursor advances;
- **any other scope** runs `mailbrief run --send --quiet --digest <scope>` **without `--commit`**. It still reads and archives new mail, but a weekly summary doesn't mark mail processed, so the next daily digest still shows it.

A bad schedule is refused before anything starts: `Bad schedule: 'daily 7.30': time must look like 07:30` (exit 2).

`day-31` only fires in months that have a 31st.

### `mailbrief serve`
```
uv run mailbrief serve                       # schedule from RUN_AT (default "daily 07:30")
uv run mailbrief serve --at "daily 18:00"    # try a schedule without editing .env
```
It prints (and logs) lines like:
```
2026-10-17 16:09:35 MailBrief service started (pid 33696), schedule: daily 07:30
2026-10-17 16:09:35 next run: Sun 18 Oct 07:30
2026-10-18 07:30:05 run started (new, slot Sun 18 Oct 07:30)
    [00:00] Loading saved emails…
    …
    Sent to telegram: Tejas (private) (1 message)
2026-10-18 07:30:46 run finished: ok in 40s
2026-10-18 07:30:46 next run: Mon 19 Oct 07:30
```
How it behaves:
- **Checks the clock every 30 s** (rather than one long sleep), so it notices the time correctly after your laptop wakes up.
- **Catch-up:** if the PC was off or asleep at a scheduled time, that run happens as soon as `serve` is running again. Only the **latest** missed run of each scope is done: off for three days means one `new` digest, not three (it covers all three days anyway).
- **First start ever:** no catch-up; it waits for the next scheduled time.
- **Each run is a separate process** with a 45-minute limit. If Outlook or the AI hangs, that run is killed and `serve` carries on.
- **Retries:** a failed run (e.g. no network right after waking) is retried after 15 min, up to 3 attempts, then skipped until the next scheduled time.
- **Login expired:** not retried, since only you can log in. It sends **one Telegram message a day**: `⚠️ MailBrief: the Outlook login has expired…`. Send `/login` to the bot (with chat on), or run `mailbrief login`; the next scheduled run works again.
- **No email content in the log:** scheduled runs use `--quiet`, so only progress, counts and results are logged, never subjects or digest text (the digest is in Telegram and the encrypted archive).
- **Only one `serve` at a time:** a second one says `MailBrief is already running` (exit 3).

### Stopping it properly
| How it's running | How to stop |
|---|---|
| In a terminal | **Ctrl+C** |
| Hidden (autostart) or another terminal | `uv run mailbrief stop` |
| Docker | `docker compose down` (or `docker compose stop`) |

All three do the same thing:
- **idle:** it stops within a second;
- **in the middle of a run:** it **lets the run finish** (email saved, digest sent, cursor advanced) and then stops. `mailbrief stop` waits up to 10 s, then tells you it's finishing the current run.
- **Ctrl+C a second time** stops immediately, killing the run.
- **A `/sync` run counts too.** `serve` waits for it (*"waiting for the /sync run to finish"*) or kills it on a second Ctrl+C. Before this fix, a `/sync` run outlived `serve`, with no 45-minute limit, and later runs said *"Another MailBrief run is in progress"*.
- **To stop only a run and keep `serve` going:** `Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%mailbrief.main run%'" | ForEach-Object { Stop-Process -Id $_.ProcessId }`.

Even a hard kill (Task Manager → End task, a power cut, `kill -9`) is **safe**: every file is written atomically (to a `.tmp` file, then renamed), and the cursor only advances after delivery. The worst case is that the next run redoes that work, or very rarely the same digest arrives twice.

### `mailbrief status`
```
Service:   running (pid 34732, since Sat 17 Oct 16:12)
Schedule:  daily 07:30
Next run:  Sun 18 Oct 07:30
Last run:  Sat 17 Oct 16:12 (new): ok, 19s
Autostart: on (starts at logon)
Log:       data\logs\2026-10.log
```
- `Right now: a run is in progress` appears during a run; `stopping (finishing the current run)` after a `stop`.
- `Last run` results: `ok`, `login needed`, or `failed (exit N)`. The log has the details.

### `mailbrief autostart on|off` (Windows)
```
uv run mailbrief autostart on     # start serve hidden every time you log in to Windows
schtasks /Run /TN MailBrief       # …and start it right now, without logging out
uv run mailbrief autostart off    # remove it (a running serve keeps going until `mailbrief stop`)
```
- It creates a Task Scheduler task named **MailBrief**:
  - **trigger:** when you log in;
  - **runs:** `.venv\Scripts\pythonw.exe -m mailbrief.main serve` in this folder (`pythonw` means no window);
  - **settings:** runs on battery, with no time limit.
- It runs **as you**, so it sees your Windows environment variables (like `SOCLAAS_API_KEY`) and `.env`.
- You can see it in Task Scheduler (`taskschd.msc`) → Task Scheduler Library → MailBrief.
- No admin rights needed.

On Linux/macOS, `autostart` says to use Docker (or a systemd user service).

### Watching the log
```
Get-Content data\logs\2026-10.log -Wait -Tail 30      # PowerShell: follow live
tail -f data/logs/2026-10.log                         # Git Bash / Linux
```
There's one file per month, in `data/logs/` (git-ignored).

### Hosting: always on, on a server
A server runs the same `serve`, inside Docker. The files are in the repo:
- **`Dockerfile`:** Python 3.11 + uv + Chromium. It runs `mailbrief serve` as a non-root user.
- **`compose.yaml`:**
  - `restart: unless-stopped`: always on, and back after a crash or reboot;
  - `stop_grace_period: 10m`: `docker compose down` lets a run finish;
  - `.env` is passed in;
  - `./data` is a volume, so the archive, session and logs survive rebuilds.
- **`.dockerignore`:** keeps `.env`, `data/` and exports **out of the image**.

On the server:
```
git clone <repo> && cd mail-manager
# .env: same values as your PC, plus SOCLAAS_API_KEY=… and RUN_AT=… (on your PC the key is a Windows variable)
# copy data/session.enc and data/destinations.json from your PC into ./data/ (same SESSION_ENCRYPTION_KEY!)
docker compose up -d --build                     # start (always on from now)
docker compose logs -f                           # watch
docker compose exec mailbrief mailbrief status   # status
docker compose down                              # stop properly
git pull && docker compose up -d --build         # update to new code
```
**Logging in on a server:** there's no screen, so you sign in from your phone:
- **Normally:** send **`/login`** to your bot and open the link (section 2, `login --remote`).
- **Server shell:** run `mailbrief login --remote` there, which prints the link.
- **Without either:** log in on your PC and copy `data/session.enc` across. The `SESSION_ENCRYPTION_KEY` must be identical.

When the login expires, the Telegram alert says "send /login".

The image needs about 2 GB of disk. Microsoft logins from a datacenter IP may expire sooner than from your PC.

**Home server with Docker:** uncomment the `ports:` line in `compose.yaml` and set `PUBLIC_URL` to an `https://` address that reaches it. That means a reverse proxy or tunnel with TLS; the sign-in page itself speaks plain HTTP behind it.

> ⚠️ **Before either recipe below: a cloud host sees your mail.** Railway and Render hold `data/` (archive, search index, Outlook session) on their volume, and `SESSION_ENCRYPTION_KEY` as one of their environment variables — so the host has both the ciphertext and the key. That's third-party data processing, the same decision as Browserless cloud (README §8), so check your employer's acceptable-use policy first. Your own always-on PC or your own server keeps mail in-house; these are the convenient option, not the private one.
>
> Two practical notes: both build the `Dockerfile` **directly and ignore `compose.yaml`**, so its `shm_size: 1gb` does *not* apply — Chromium on Docker's default 64 MB `/dev/shm` is the first thing to suspect if the browser crashes there. And a datacenter IP means Microsoft logins expire sooner than from your PC, each one costing a `/login` tap.

### Deploy on Railway
1. **New project** → *Deploy from GitHub repo*. Railway builds the existing `Dockerfile`.
2. **Region:** Settings → choose **Singapore**, so Microsoft and NUS see a local address.
3. **Volume:** add one mounted at **`/app/data`** (session, archive, index, logs).
   - Railway volumes belong to root, so add the variable `RAILWAY_RUN_UID=0` if runs fail with "permission denied" in `data/`.
4. **Variables:**
   - `SESSION_ENCRYPTION_KEY`, `SOCLAAS_API_KEY`, `TELEGRAM_BOT_TOKEN`;
   - `TZ=Asia/Singapore`, `RUN_AT=daily 07:30`;
   - anything else from your `.env`.
5. **Networking** → *Generate Domain*. **Type the port in by hand:** `8080`, or whatever `PORT` is set to.
   - Railway can't detect it, because nothing listens until a sign-in starts.
   - **Don't set a healthcheck path,** for the same reason: the deploy would fail.
6. **First sign-in.** The bot only answers chats it knows, and the new volume knows none, so open the service's **shell** and run:
   ```
   mailbrief add-destination telegram --chat-id <your chat id>   # the id is in data/destinations.json on your PC
   mailbrief login --remote                                       # open the printed link on your phone
   ```
   From then on, sign in again with **`/login`** in Telegram.
7. **Optional: keep your history.** Copy your PC's `data/` (archive, index, rules, destinations) into the volume first; it needs the same key. Otherwise the server starts empty, and `mailbrief run --backfill` refills it from Outlook.

### Deploy on Render
Render differs from Railway in two ways that matter:
- **A web service must always have a port open,** or its deploy fails with *"no open ports detected"*. On Render (`RENDER=true` is set for you), `serve` therefore keeps the sign-in server running on `$PORT` the whole time. It answers **404 to everything** unless a `/login` sign-in is open, and then only to the browser holding that one-time link. The same one-time token, cookie, 10-minute and https rules apply.
- **The free plan can't run MailBrief.** Free web services sleep after 15 minutes without web traffic, which would stop the schedule and the bot. They also can't have a disk, so the session and archive would vanish on every restart. You need a paid instance (Starter or above) plus a disk.

1. **New → Web Service** from your GitHub repo. Render detects the `Dockerfile`.
2. **Region:** Singapore. **Instance:** Starter to begin with. Starter has 512 MB of RAM, and a run's Chromium can be tight in that; if the logs show the service being killed for memory, move up to Standard.
3. **Disk:** Advanced → *Add Disk*, mount path **`/app/data`**, 1 GB is plenty.
4. **Environment:** `SESSION_ENCRYPTION_KEY`, `SOCLAAS_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TZ=Asia/Singapore`, `RUN_AT=daily 07:30`.
   - You don't need `PORT` or `PUBLIC_URL`: Render sets `PORT` (10000) and `RENDER_EXTERNAL_URL`, the `https://….onrender.com` address used for the link.
   - **Leave the health check path empty.**
5. **First sign-in.** Deploy, then open **Shell** in the Render dashboard and run:
   ```
   mailbrief add-destination telegram --chat-id <your chat id>   # the id is in data/destinations.json on your PC
   ```
   Then send **`/login`** to your bot and open the link on your phone.
   - On Render, `login --remote` in the shell can't be used, because `serve` already holds the port. It says so.
6. **Optional:** to keep your history, copy your PC's `data/` onto the disk; it needs the same key. Otherwise `mailbrief run --backfill` refills it.

**If the logs show "Permission denied" under `/app/data`:** the disk is owned by root while the container runs as user 1000. Tell me; the fix is a small Dockerfile change.

Any other host that insists on an open port: set `LOGIN_PAGE=always`.

**If NUS blocks sign-ins from datacenter addresses,** the Microsoft page says so during sign-in. Then use the copy-`session.enc` route, or a home server.

### Exit codes
| Command | 0 | 2 | 3 |
|---|---|---|---|
| `serve` | stopped normally | bad schedule | already running |
| `stop` | stopped / wasn't running / finishing a run | (n/a) | (n/a) |
| `autostart` | done (1 = Task Scheduler refused, with its message) | not Windows | (n/a) |

`serve` stopped by a second Ctrl+C exits with 130.

---

## 8. Developer commands

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
uv run python tests/test_labels.py        # label names, keeping your categories, pending/cleared selection, request shapes, the write guard
uv run python tests/test_rules.py         # your own labels: rules.json checks, course/sender/direct matching, topics, floors, boosts
uv run python tests/test_events.py        # the calendar: 14-day window, undated only when new, merging, ⭐/🆕, layout, per-day splitting
uv run python tests/test_web_images.py    # linked images: https + public addresses only, no redirects, type/size/budget/tries limits
uv run python tests/test_links.py         # Outlook links: the URL format, [n] refs → ↗ links, escaping (no links from email text)
uv run python tests/test_index.py         # search index: chunking, incremental updates, pruning, hybrid search, filters, never raises
uv run python tests/test_answer.py        # chat answers: plan checks, citation clean-up, file requests checked, rendering, history cap
uv run python tests/test_bot.py           # Telegram chat: only your private chats, buttons, files, commands, /label parsing, errors
uv run python tests/test_ai_client.py     # AI client: gives up on no answer after 2 retries (120 s / 300 s thinking), waits out 429s, logs retries
uv run python tests/test_remote_login.py  # sign-in page: one-time token → cookie, 404s, expiry, input checks, headers, https-only
uv run python tests/test_service.py       # RUN_AT parsing (and rejecting bad ones), catch-up/due runs, next run, run flags, locks
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

## 9. Configuration (`.env`)

| Variable | Default | Affects |
|---|---|---|
| `SESSION_ENCRYPTION_KEY` | *(required)* | Encrypts `session.enc` and archive `.enc` files |
| `AI_BASE_URL` | `https://soclaas-api.comp.nus.edu.sg/v1` | Which OpenAI-compatible endpoint `run` calls |
| `AI_API_KEY` / `SOCLAAS_API_KEY` | system env var | AI key (`AI_API_KEY` wins if set) |
| `AI_CLASSIFIER_MODEL` | `qwen3.6:35b` | Classifies text-only emails |
| `AI_VISION_MODEL` | `qwen3.6:35b` | Classifies emails with image attachments |
| `AI_DIGEST_MODEL` | `qwen3.8:27b` | Writes the digest (thinking on) |
| `AI_FALLBACK_MODEL` | `qwen3.6:35b` | Used when another model gives no answer in time (one try, then this). Empty = never switch |
| `TELEGRAM_BOT_TOKEN` | *(none)* | Needed by `add-destination` and `run --send` |
| `DEFAULT_TIMEZONE` | `Asia/Singapore` | Displayed times, `--day`, periods, which month file an email goes in |
| `ARCHIVE_DAYS` | `0` (forever) | If > 0, `run` deletes month files that ended more than this many days ago |
| `BROWSER_WS_URL` | *(empty)* | Empty = local Chromium. Set it to connect to a Browserless/CDP browser instead |
| `OUTLOOK_LABELS` | `on` | `off` stops `run` from labelling emails in Outlook (section 5) |
| `REMOTE_IMAGES` | `on` | `off` stops downloading images linked from email bodies (the senders' image servers see your IP when they're fetched). Events then come from text and attached/inline images only |
| `EVENTS_DAYS` | `14` | How many days ahead the UPCOMING EVENTS calendar looks; `0` stops `run --send` from sending it |
| `CHAT` | `on` | `serve` answers questions from your registered private Telegram chats (section 13). `off` keeps the bot send-only |
| `AI_EMBED_MODEL` | `bge-m3` | The model that turns emails and questions into search vectors. Changing it rebuilds the index on the next update |
| `AI_ANSWER_MODEL` | `qwen3.8:27b` | The model that writes chat answers (thinking on) |
| `RUN_AT` | `daily 07:30` | When `serve` runs, and which digest each time (format in section 7) |
| `PUBLIC_URL` | `$RENDER_EXTERNAL_URL` or `https://$RAILWAY_PUBLIC_DOMAIN`, else `http://localhost:$PORT` | The address in the `/login` sign-in link. Must be `https://` unless it's localhost |
| `PORT` | `8080` (Railway and Render set it) | The port the sign-in page listens on, only while a sign-in is open (always on Render) |
| `LOGIN_PAGE` | *(empty)*; automatic on Render | `always`: `serve` keeps the port open, answering 404 to everything except an open sign-in. For hosts that require an open port |
| `LOGIN_TUNNEL` | *(empty)* | `cloudflared`: on your PC (no `PUBLIC_URL`), `/login` opens a temporary `https://….trycloudflare.com` tunnel so the link works on your phone. Cloudflare sees the traffic |

Listed in `.env.example` but **not used by the code yet** (planned for later milestones): `FALLBACK_AGENT`, `DATABASE_URL`, `RESTORE_UNREAD` (`SORT_MODE` is replaced by `OUTLOOK_LABELS`; a "move to folders" mode is M6).

---

## 10. Files the commands create

| File | Created by | Contents | Sensitive? |
|---|---|---|---|
| `data/session.enc` | `login`, refreshed by every `run` | Outlook cookies + browser identity, encrypted | **Yes**: full mailbox access |
| `data/index.enc` | every `run`, `index update/rebuild`, `labels retag` | Search vectors for chat (one set per email, plus a hash). No email text: it's recomputed from the archive | Yes (encrypted) |
| `data/rules.json` | `rules add/remove/profile` (or you, by hand) | Your own labels: profile, courses, senders, topics | No (rules only, no email content) |
| `data/cursor.json` | `run --commit`, `run --backfill` | Newest processed time + last 500 email IDs | No (IDs only) |
| `data/archive/YYYY-MM.enc` | every `run` | That month's emails, classifications, digests, encrypted | Yes (encrypted) |
| `data/archive/YYYY-MM.json` | `run --no-password` | Same, **plain text** | **Yes, unencrypted** |
| `data/destinations.json` | `add-destination` | Telegram chat IDs | Mildly |
| `data/archive/…` (fields) | `run`, `labels` | Per email: `outlook_labels` (what Outlook was given), `labels_cleared`, `outlook_gone` | (inside the archive) |
| `data/schedule.json` | `serve` | Schedule, last scheduled time done, last run result, next run | No |
| `data/logs/YYYY-MM.log` | `serve` | Timestamped service lines + run progress (no email content: `--quiet`) | No |
| `data/run.lock`, `data/serve.lock` | `run`, `serve` | Empty; the OS lock on them is what matters | No |
| `data/stop.request` | `stop` | Empty; `serve` deletes it when it stops | No |
| whatever `--export FILE` / `--json >` names | you | Plain email JSON | **Yes, unencrypted** |

All of `data/` and `.env` are git-ignored. Exported files elsewhere are **not**.

---

## 11. Recipes

**First-time setup**
```
uv sync
uv run playwright install chromium --no-shell
# create .env (see section 1)
uv run mailbrief login
uv run mailbrief run --backfill        # optional: archive the whole inbox once
uv run mailbrief add-destination telegram
```

**Every morning by hand**
```
uv run mailbrief run --send --commit
```

**Every morning automatically, on this PC**
```
uv run mailbrief autostart on          # once: start with Windows from now on
schtasks /Run /TN MailBrief            # start it now without logging out
uv run mailbrief status                # check: running, next run
```

**Stop it** (today only / for good)
```
uv run mailbrief stop                  # stops now; starts again at your next login
uv run mailbrief autostart off         # no longer starts at login (then `stop` if it's running)
```

**Try a schedule in a terminal first**
```
uv run mailbrief serve --at "daily 07:30; sun 20:00 this-week"   # Ctrl+C to stop
```

**"Is it running? Did this morning's run work?"**
```
uv run mailbrief status
Get-Content data\logs\2026-10.log -Tail 40
```

**Labels in Outlook: check, remove, bring back**
```
uv run mailbrief labels status
uv run mailbrief labels clear --period last-month      # one month's
uv run mailbrief labels clear --all --colours          # everything, including the coloured categories
uv run mailbrief labels apply                          # put them back
```

**Run it on a server** → section 7, "Hosting".

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

**A run is very slow, or the log says `AI: no answer from …`:** the AI service or your network isn't answering. Each AI call now gives up after 2 retries (at most about 6 min, or 15 for a long digest), so the run fails instead of hanging. A scheduled run retries by itself; after `/sync`, send it again later. `AI: busy (429)` lines just mean the shared service is rate-limiting, and they wait it out. `AI: qwen3.8:27b didn't answer…; using qwen3.6:35b instead` means the strong model was too slow, and the fast one wrote that part.

**Start "new mail" tracking from scratch**: delete `data/cursor.json`. The next run looks back 24 h. The archive is unaffected and still prevents repeat AI calls.

---

## 12. Exit codes at a glance

| Command | 0 | 1 | 2 |
|---|---|---|---|
| `login` | saved | (n/a) | (n/a) |
| `run` | success | cursor not advanced | no session / session expired (3 = another run in progress, 4 = sent but cursor kept: previews only) |
| `serve` | stopped normally | (n/a) | bad schedule (3 = already running, 130 = forced stop) |
| `labels` | done / dry run | answered no / archive unreadable | bad options / login needed (3 = run in progress) |
| `stop` / `status` | done | (n/a) | (n/a) |
| `autostart` | done | Task Scheduler refused | not Windows |
| `emails` | success | bad number / can't decrypt | bad `--day` |
| `events` | done / nothing found | archive unreadable / not delivered | bad `--days` / `--past` |
| `rules` | done | rule not found / rules.json unreadable | bad rule |
| `index` | done | archive unreadable / nothing indexed | (n/a) (3 = run in progress) |
| `chat` | done | no index yet / archive unreadable | (n/a) |
| `bot` | stopped | (n/a) | chat off / no bot token (3 = serve is running) |
| `add-destination` | added | no chats / bad choice | unknown type |

---

## 13. Ask your inbox

Ask questions about your email and get answers built only from your saved emails, with quotes, sources and ↗ links that open each email in Outlook. In Telegram (through `serve`) or in the terminal (`mailbrief chat`). Design: README §3.9.

### Setup, once
```
uv run mailbrief run --backfill        # right after a morning run: all older inbox mail, recipients, attachment ids
uv run mailbrief index rebuild         # the search index (about 30-60 s for ~400 emails)
uv run mailbrief chat "any hackathons this month?"    # try it in the terminal
uv run mailbrief serve                 # Telegram: now message your bot a question
```
- `CHAT=on` (the default) and a `TELEGRAM_BOT_TOKEN` are all the chat needs. Your chat must be a destination (section 6).
- In @BotFather, keep `/setjoingroups` → **Disable**.
- After this, every run keeps the index current by itself.

### `mailbrief index status|update|rebuild`
```
uv run mailbrief index status     # counts only: emails, chunks, model, size, last update
uv run mailbrief index update     # embed what's new or changed (runs do this themselves)
uv run mailbrief index rebuild    # embed everything again (e.g. after changing AI_EMBED_MODEL)
```
- **What's indexed:** every saved email with full text (inbox mail and your own replies). Per email, a header chunk (subject, sender, date, summary, labels, attachment names, events) plus the body without quoted history, cut into about 1,500-character chunks (at most 6).
- **Sends email text to `AI_BASE_URL`** (the NUS endpoint, `bge-m3`): the same in-house endpoint classification uses. About 30 chunks a second.
- **Stored encrypted** in `data/index.enc`: vectors and hashes only, no email text. Safe to delete; `rebuild` recreates it.
- **Incremental:** only new or changed emails are embedded; emails pruned from the archive are dropped.
- Takes the run lock, so it never runs alongside a run (exit 3).
- Exit codes: 0 done, 1 the archive can't be read (or nothing could be indexed), 3 a run is in progress.

### `mailbrief chat ["question"]`
```
uv run mailbrief chat "when is the CS1101S midterm?"    # one question
uv run mailbrief chat                                    # keep asking; an empty line (or Ctrl+C) stops
```
- Prints the answer with `[n]` refs, then the numbered **Sources** with each email's Outlook link. If nothing was cited, it shows the **Closest matches** instead.
- Follow-up questions work within one session ("and what can I bring?").
- If the answer would send a file in Telegram, it says which.
- Needs the index (exit 1 without it). No Outlook is opened.

### How a question is answered
1. **Plan:** the cheap model turns the question and today's date into a search plus filters (sender, date range, labels, "is this about events?").
2. **Find:** filters in code, then ranking by meaning and keywords. Event and deadline questions ("what's on this week?", "anything due soon?") take their date range from the events' and deadlines' dates; questions about the emails themselves ("what did X send last week?") use arrival dates.
3. **Answer:** the strong model gets the best ~12 emails (with thread context) as data. It must cite every fact, quote exact wording where it matters, and say so when the emails don't answer.
4. **Check:** code drops refs to emails it wasn't given, and only sends files that really are attachments of cited emails.

### The Telegram chat
Runs inside `mailbrief serve` (or alone with `mailbrief bot`, for testing). It long-polls Telegram, so no webhook and no open port.
- **Only your registered private chats** (active Telegram destinations) get answers. Everyone else, and every group, is ignored without a reply.
- **Each answer** has ↗ links on its claims, a **Sources** list where each line opens that email, and buttons for the sources' attachments.
- **Tap an attachment button** and the file is fetched from Outlook (read-only, 5-10 s) and sent to the chat, from memory, never saved. If a run is using Outlook right then, you're asked to tap again in a minute. Buttons expire when `serve` restarts.
- **Ask for a file** ("send me the seating plan") and it's sent after the answer, checked against the cited emails.
- **Memory:** the last 3 questions and answers per chat, in memory only. `/new` forgets them.
- **Logs** (`data/logs/`) record counts and timings, never questions or answers.

| Command | What it does |
|---|---|
| `/help` (or `/start`) | What the bot can do |
| `/new` | Forget this conversation |
| `/sync` | Check for new mail now: a normal run with `--send`, so the digest arrives as usual |
| `/digest` | Send the latest saved digest again (with links), then the events calendar |
| `/events [days]` | The upcoming-events calendar (default 14 days) |
| `/labels` | Your label rules (as `mailbrief rules list`) |
| `/label add course CS2040S [p2] [boost]` | Add a course rule |
| `/label add sender a@b.c "Prof X" [direct] [boost] [p1]` | Add a sender rule (`direct`: only mail where you're the only To recipient) |
| `/label add topic Networking "career fairs, meetups" [p2]` | Add an AI topic |
| `/label remove course\|sender\|topic KEY` | Remove a rule (old emails keep its label) |
| `/profile text` | Set your profile |
| `/login` | Sign in to Outlook again from your phone: a one-time link to a sign-in page (section 2, `login --remote`) |

### `mailbrief bot`
Runs just the Telegram listener in the foreground, without the scheduler, until Ctrl+C. Useful for testing the chat. It refuses to start while `serve` is running (exit 3), since `serve` already listens and Telegram allows one reader at a time. Exit 2 if `CHAT=off` or there's no bot token.

### Privacy and safety
- **More reaches Telegram than with the digest:** quotes from your emails, and files you ask for. Telegram bot chats aren't end-to-end encrypted. `CHAT=off` turns chat off entirely.
- **The answering model reads email bodies,** so a malicious email could try to steer an answer. It has no tools, can only reply in your chat, and never writes links: code builds every link from email ids and escapes the model's text.
- **The ↗ links** only work for someone signed in to your mailbox. Opening an email marks it read, as Outlook always does. Outlook usually gives a moved email a new id, so links to mail you've since moved or archived may stop working.
