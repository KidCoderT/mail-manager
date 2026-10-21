# MailBrief — AI Morning Email Digest (Outlook)

> **Status:** v1 works end to end (M1–M5 ✅: reading, AI classification and digests, Outlook labels, scheduled service), plus **your own labels** (M6a ✅, §3.8). **Being designed:** reading newsletter images and events (M6b, §3.10) and chatting with your inbox in Telegram (M7, §3.9).
> **Scope:** one person's Outlook on the web (Microsoft 365), Playwright driving a **local Chromium**, Telegram delivery (more channels pluggable). [Browserless](https://www.browserless.io) is an optional later runtime. **Single-user only:** multi-user hosting is cancelled (§13).

> ⚠️ **Disclaimer:**
> - MailBrief is a personal project, not affiliated with or endorsed by Microsoft or NUS.
> - It uses Outlook on the web's **internal** API, not a public one, so it can break without warning.
> - Use it only on **your own** mailbox, and check your organisation's IT and acceptable-use policies first.
> - Email text is sent to whichever AI endpoint you configure.
> - It comes with no warranty ([MIT License](LICENSE)).

> 📘 **Docs:** [commands.md](commands.md) (every command in detail) · [teaching.md](teaching.md) (how and why the code works)

MailBrief reads your work inbox every morning with a headless browser on your own machine. It labels the emails inside Outlook (categories, **never deletes**) and sends a summary to one or more destinations, starting with Telegram. Planned next: labels you define yourself (courses, professors, networking), and a Telegram chat where you ask questions and it answers from your emails.

---

## 1. Goals & Non-Goals

### Goals
- **Log in once.** The user signs in a single time and the app reuses that session for daily headless runs.
- **No API / OAuth app registration.** All mailbox access goes through the Outlook web UI.
- **AI classification and summary** of every new email since the last run.
- **Sorting inside Outlook** by applying categories (default) or moving to folders.
- **Morning digest** delivered to one or many Telegram chats, with WhatsApp and other channels pluggable later.
- **Runs automatically** every morning on a schedule, in the user's timezone.
- **Keep mail data in-house where possible:** local browser, and your own or your company's AI model.
- **Your own labels** (M6a ✅): courses (`MB: CS1101S`), professors (`MB: Prof Tan`), topics you care about (`MB: Networking`) with their own priority. You define them and change them as time goes on (§3.8).
- **Ask your inbox** (M7): ask in Telegram ("when is the CS1101S midterm?", "any hackathons this month?") and get an answer from your emails, with quotes, sources and attachments (§3.9).

### Non-Goals
- ❌ Deleting, archiving to trash, or permanently removing any email
- ❌ Sending or replying to emails
- ❌ Gmail / other providers (planned for later)
- ❌ Multi-user hosting: **cancelled** for legal reasons (§13). MailBrief serves exactly one person: you.
- ❌ A public bot. From M7 the bot listens, but only to your own registered private chat (§3.6).

---

## 2. High-Level Architecture

```
                ┌──────────────────────────┐
                │ Scheduler (Task Sched./  │  e.g. 07:00 Asia/Singapore
                │ cron)                    │
                └────────────┬─────────────┘
                             │ triggers per-user job
                             ▼
┌───────────────────────────────────────────────────────────────┐
│                        Job Runner                             │
│                                                               │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐   │
│  │ 1. Session   │──▶│ 2. Inbox     │──▶│ 3. AI Processor  │   │
│  │   Manager    │   │   Reader     │   │  (any OpenAI-    │   │
│  │ (cookies)    │   │ (Playwright, │   │   compatible     │   │
│  │              │   │  local)      │   │   endpoint)      │   │
│  └──────┬───────┘   └──────────────┘   └────────┬─────────┘   │
│         │ expired?                               │            │
│         ▼                                        ▼            │
│  ┌──────────────┐                       ┌──────────────────┐  │
│  │ Re-login     │                       │ 4. Sorter        │  │
│  │ alert        │                       │ (categorize/move │  │
│  └──────┬───────┘                       │  via UI)         │  │
│         │                               └────────┬─────────┘  │
│         │                                        ▼            │
│         │                               ┌──────────────────┐  │
│         └──────────────────────────────▶│ 5. Notifier      │  │
│                                         │ (Telegram, ...)  │  │
│                                         └────────┬─────────┘  │
└──────────────────────────────────────────────────┼────────────┘
                                                   ▼
                                    Telegram chat A, chat B, group C …

                ┌───────────────────────────┐
                │  Storage: files in data/  │  session, archive, cursor,
                │  (encrypted where private)│  destinations, logs (§4)
                └───────────────────────────┘
```

**Browser runtime:** one setting, `BROWSER_WS_URL`, picks where the browser runs. The rest of the code is identical.

| Mode | `BROWSER_WS_URL` | How Playwright gets a browser | Mail data leaves the machine? |
|---|---|---|---|
| **Local** (default) | empty | `chromium.launch()` | No |
| Browserless self-hosted (later) | `ws://localhost:3000?token=...` | `chromium.connect_over_cdp()` to a Docker container | No |
| Browserless cloud (later, IT approval only) | `wss://production-sfo.browserless.io/...` | `chromium.connect_over_cdp()` | **Yes**, see §8 |

### Design decisions & trade-offs
- **Web UI instead of the Microsoft Graph API.** No admin-approved app registration is needed, and the app can only do what the user can do by hand. The cost is fragility: Outlook's UI changes often, so reading is network-first (§3.2) and all selectors live in one file.
- **Local first.** For one user, a local Chromium does everything a hosted browser would, with no Docker and no third party. Browserless becomes worthwhile for many users, cloud hosting, or human hand-off (`liveURL`).
- **Scripts navigate, AI only reads and decides.** Runs stay fast, cheap and predictable. The AI fallback agent is optional and boxed in by code (§3.5).
- **Never trust email content.** Emails are untrusted input. No component that reads email bodies can act on the mailbox (§3.3, §3.5).

---

## 3. Components

### 3.1 Session Manager (login once, reuse cookies)
Handles the "log in once, run headless forever" flow.

**One-time login (`login_once.py`)**
1. Launch Chromium **headed** (visible).
2. Open `https://outlook.office.com/mail/`.
3. The user signs in manually, including MFA, and ticks **"Stay signed in"**.
4. Save the session with `context.storage_state(path=...)`, which captures cookies and local storage.
5. Encrypt the file and store it per user.

**Each run**
1. Get a browser via `browser/connect.py` (local launch by default) and create `new_context(storage_state=...)`.
2. Navigate to the inbox.
3. If redirected to `login.microsoftonline.com`, the session has **expired**:
   - abort the run,
   - send a "Please re-login" alert to the user's destinations,
   - mark the user `needs_relogin`.
4. On success, **re-save `storage_state`** at the end of the run, because Microsoft rotates auth cookies.

**Rules**
- Do the one-time login **on the same machine** that runs the headless jobs. Copying cookies between machines or IPs often forces a re-login or is blocked by device-bound sessions.
- Use the same Chromium build and user agent for the login and the headless runs.
- Expect periodic re-logins. Their frequency is set by the organization's Microsoft security settings.

**Later, Browserless cloud:** the session would instead be a Browserless *profile* (created via dashboard → Profiles → "Sign in via remote browser"). Each run connects with `&profile=<name>` and uses `browser.contexts[0]`. Re-saving rotated cookies via `Browserless.saveProfile` is unverified. Cloud mode needs IT approval (§8).

### 3.2 Inbox Reader (network-first)
Extracts new emails from Outlook on the web **without scraping the page where possible**.

**1. List: capture Outlook's own data.** `page.on("response")` captures the `FindConversation` JSON that Outlook's page fetches as the list loads. The list is virtualized and pages in about 50 at a time, so the reader scrolls it with the mouse wheel until it has the count Outlook reports (`TotalConversationsInView`). With **Focused Inbox** on, it loads the **Focused** and **Other** tabs separately and tells their responses apart by `FocusedViewFilter`.

**2. Full text: read-only `GetItem`.** For conversations newer than the cursor, the reader calls Outlook's own `service.svc?action=GetItem` with each conversation's `ItemIds` (20 per call, plain-text bodies). It reuses the auth headers from Outlook's latest request; these stay in memory only. Nothing is clicked or opened, so **read state is untouched** (verified: unread emails stay unread).

**3. Cursor and dedupe** (`cursor.py`, `data/cursor.json`): new = `received_at >= last_processed_at` and ID not among the last 500 processed. The first run looks back 24 h. The cursor only advances on `--commit` and only when every email has full text.

These formats are internal and undocumented, so all parsing lives in **one file** (`browser/owa_network.py`). When they change, only that file needs fixing.

**Fallback: list previews.** If `GetItem` fails, the run still produces one record per conversation, with Outlook's list preview as the body (`body_source: "preview"`). The cursor never advances on a preview run.

**Deferred: DOM fallback.** Opening each email via a selectors file (not built) and restoring its unread state (`RESTORE_UNREAD`) would only be needed if both the list capture and `GetItem` break.

**Both paths**
- Read until reaching emails older than `last_processed_at`, deduped against `last_processed_ids`.
- Per email: `id`, `sender_name`, `sender_email`, `subject`, `received_at`, `body_text` (plain text, trimmed), `has_attachments` + names, `is_read`, `importance`.
- Output: a list of `EmailRecord` JSON objects.

### 3.3 AI Processor
A two-pass pipeline behind **one function**, `complete(model, messages, thinking)` (`ai/client.py`, stdlib `urllib`). It calls any **OpenAI-compatible** chat endpoint set by `AI_BASE_URL`. **Your company's own AI model is the preferred choice**, so email content stays in-house. No provider-specific code lives anywhere else.

**Current setup:** the NUS SoC endpoint (`https://soclaas-api.comp.nus.edu.sg/v1`), with the key taken from `AI_API_KEY` or the `SOCLAAS_API_KEY` system env var.

| Role | Model | Why |
|---|---|---|
| Classify text emails | `qwen3.6:35b` | MoE (~3B active): light on a shared server; short JSON with no thinking; 262k context |
| Classify emails with images | `qwen3.8:27b` (thinking off) | Newest (Aug 2026) dense native-vision model; 1.7 s per email |
| Write the digest | `qwen3.8:27b` (thinking on) | Strongest reasoning in the list; connects related emails ("fee looks paid") |

These were picked by testing every candidate on the endpoint with made-up emails (12 with known categories, plus a timetable screenshot):
- qwen3.6:35b, qwen3.8:27b, qwen3-vl:32b and gemma4:26b all scored 12/12 and 5/5 on the screenshot. **Category definitions in the prompt were what got them there.**
- gemma4 was 3–5× slower.
- qwen3.5:9b ran out of tokens while thinking.
- llama3.1:8b can't take images (HTTP 400) and got about half the categories right.

**Images:** non-inline image attachments between 15 KB and 5 MB (up to 3 per email) are fetched through `GetAttachment` and sent to the vision model. They're kept in memory only. Signature logos are inline and skipped.
- **Today's limit:** images embedded in the body (inline) are skipped too. Images loaded from links aren't fetched at all, because the body is read as plain text.
- So a newsletter's event poster rarely reaches the model. When one does, only one summary line and one deadline survive.
- M6b fixes this (§3.10).

**Untrusted input:** the email goes inside `<email>` delimiters, marked as data rather than instructions. The digest only sees Pass 1 results, never email bodies.

**Requirements for the model**
- It is reachable via an API (not just a chat window).
- It doesn't refuse to summarize the user's own email. Models with strict "no private information" guardrails may refuse, so **test with a few real emails first**.
- It returns usable JSON. Output is validated against the schema below, with **one retry** on failure, after which the email is listed as "unclassified".

**Pass 1: Classification (cheap model), per email**
```json
{
  "id": "...",
  "category": "Urgent | Needs Reply | FYI | Meetings | Newsletter | Low Priority",
  "priority": 1,
  "action_items": ["Send Q3 numbers to Ana"],
  "deadline": "2026-10-17",
  "one_line_summary": "Ana needs Q3 figures before Friday's review."
}
```

**Pass 2: Digest (stronger model), over all Pass 1 results**
- Top priorities for today
- Emails needing a reply (with who and why)
- Deadlines and meetings
- FYI highlights
- Counts per category

**Long inboxes:** process in batches (e.g. 25 emails), summarize each batch, then summarize the summaries.

**Untrusted input:** email text can contain instructions aimed at the AI ("ignore previous instructions…"). The classifier and digest models get **no tools**. They only return text, and only the validated JSON fields are used.

**Privacy:** the AI provider must not retain or train on data. Send only the fields needed and strip signatures and long quoted threads.

### 3.4 Sorter: Outlook labels ✅ (`labels.py`, `browser/outlook_writer.py`)
Each inbox email gets **two Outlook categories**: `MB: <category>` + `MB: P<priority>` (e.g. `MB: Urgent` + `MB: P1`). They're coloured, and visible and filterable on web, desktop and phone.
- **How it writes:** through Outlook's own JSON calls, not by clicking. The formats were captured from Outlook itself (a probe recorded the request structure while categorising by hand).
  - Per email: `UpdateItem`, setting **only** `Categories`, after reading the current categories. The email's own non-MB categories are kept.
  - Colours: `UpdateMasterCategoryList`, once.
  - Full reset: `ApplyCategoryOperation`.
- **Code-enforced guard** (`check_request`): every Outlook request is checked before it leaves. Reads are allowed. Writes may only set or delete Categories, or add or remove `MB: ` categories. Move, delete, send, mark-read and rules are refused.
- **Not copied:** Outlook's own right-click "Categorize" creates an *always categorise this conversation* rule. MailBrief deliberately doesn't use that.
- **Every run labels what's pending:** new or reclassified emails, up to 400 per run. The archive remembers what each email was given (`outlook_labels`).
- **Easy to undo:** `mailbrief labels clear --period … | --days N | --all [--colours]`, and `labels apply` to bring them back. See [commands.md §5](commands.md#5-mailbrief-labels).
- **Verified on the real mailbox:** an unread email stayed unread. 360 emails were labelled, cleared (including the categories) and re-labelled.
- A "move to folders" mode is left for M8. **No delete action exists in the code.**
- **Your own labels** (courses, professors, topics) (M6a ✅) use this same mechanism: see §3.8.

### 3.5 AI Fallback Agent (optional, off by default; M8, not built)
Enabled with `FALLBACK_AGENT=on`. When a scripted step fails (selector not found or timeout):
1. Capture a screenshot and the page's accessibility tree.
2. Hand the single failed step to an AI browser agent (e.g. `browser-use`) with a narrow instruction ("Apply category 'MB: Urgent' to the selected email").
3. Log the fallback event so the scripted selector can be fixed.

**Limits are enforced in code (a planned `browser/guard.py`), not in the prompt:**
- Before **every** agent action, the guard resolves the target element's accessible name and **refuses** anything matching `delete | send | forward | reply | junk | block | report | unsubscribe | empty | sweep | ignore`.
- The agent runs only while **no email body is open**, so email text can't steer it.
- At most N actions per failed step, after which it gives up.

The agent needs a model with tool calling (ideally vision too). If the configured model lacks these, the agent stays off. A failed step then saves a screenshot and sends an alert instead.

### 3.6 Notifier
Adapters are plain functions in a registry (`notify/__init__.py`):

```python
ADAPTERS = {"telegram": send_telegram}   # later: "whatsapp": send_whatsapp, ...
```

Adding a channel means writing one `send_<channel>(target, digest)` function and one dict entry.

| Adapter | v1 | Notes |
|---|---|---|
| Telegram | ✅ | Bot API over plain HTTPS; send-only |
| WhatsApp | later | Business API |
| Slack | later | Incoming webhook |
| Email / Teams | later | Policy-friendlier options (data stays in Microsoft 365) |

- **Multiple destinations.** Every digest goes to all active destinations.
- **Telegram's limit is ~4,096 chars/message.** Split long digests into parts, with the top priorities first.
- Delivery failures to one destination don't block the others. Each is retried and logged.

**Telegram bot lockdown** (nobody else can use or hijack the bot):
- **Today (M1–M5): send-only.** The app never polls for incoming messages, so `/start` from strangers does nothing. There is no self-registration and no invite codes.
- **From M7: allowlisted.** To answer your questions (§3.9) and take label commands (§3.8), `serve` reads the bot's incoming messages. It **acts only on private chats listed in `data/destinations.json`**. Every other chat, and every group, is ignored without a reply, so a stranger who finds the bot learns nothing. `CHAT=off` returns to send-only.
- **Destinations are added only via the local CLI** (`mailbrief add-destination`). The CLI reads the chat ID once, during setup, from the message you send the bot. The bot can never add a chat itself.
- In BotFather, set **`/setjoingroups` → Disable**, so nobody can add the bot to their own group. Re-enable it briefly only to add it to your own group.
- **The bot token is a password.** Whoever has it controls the bot. Keep it in `.env` only and `/revoke` it in BotFather if it leaks.
- The app never accepts a user-supplied bot token.

**Policy note:** Telegram bot chats are **not end-to-end encrypted**, so digest text leaves the company. Keep the digest summary-level (no full email bodies), and switch to an Email/Teams adapter if policy requires.

### 3.7 Scheduler ✅ (`mailbrief/service.py`)
- **`mailbrief serve`** is one long-running process that fires runs on the `RUN_AT` schedule:
  - **format:** `daily 07:30; sun 20:00 this-week; day-1 09:00 last-month`, i.e. any days, any times, any digest scope;
  - **where it runs:** on your PC (started hidden at logon by Windows Task Scheduler: `mailbrief autostart on`) and on a server (Docker `CMD`). The same code runs in both.
- **Each run is a child process** with a timeout, so a hung browser or AI call can't take the service down. Failed runs are retried (15 min, 3 attempts).
- **Catch-up after sleep or shutdown:** the latest missed run of each scope runs once.
- **No overlaps:** OS file locks prevent overlapping runs (`run.lock`) and a second service (`serve.lock`). They are released by the OS even after a crash.
- **Graceful stop:** Ctrl+C, `mailbrief stop`, or `docker stop` let a run in progress finish first.
- **Logs and status:** monthly logs in `data/logs/` (no email content: `run --quiet`); `mailbrief status`.
- **Expired login:** a Telegram alert, once a day.

Commands and the full schedule format: [commands.md §7](commands.md#7-running-automatically).

### 3.8 Your own labels ✅ (M6a: `rules.py`; commands in [commands.md §5](commands.md#your-own-labels-mailbrief-rules))
Every email gets one of six fixed categories plus a priority. M6a adds **labels you define**: they sit beside the category, they're personal to you, and you change them as time goes on (new semester, new professor, new interest).

```
Prof Tan     Re: your project proposal        [MB: Needs Reply] [MB: P1] [MB: Prof Tan] [MB: CS2103T]
NUS Hackers  Hack&Roll 2027 sign-ups open     [MB: FYI] [MB: P2] [MB: Networking]
Canvas       CS1101S: Mission 7 released      [MB: FYI] [MB: P3] [MB: CS1101S]
```

**Where the rules live:** `data/rules.json`, on your PC (git-ignored, because it's personal). All of these edit the same file:
- by hand, in an editor (a typo never breaks the digest: that run warns and skips Outlook labelling);
- `mailbrief rules list | add | remove | profile` in the terminal;
- `/label …` commands in your Telegram chat (below; they arrive with the M7 listener).

**Four kinds of rule:**

| Kind | Example | Decided by | Result |
|---|---|---|---|
| `profile` | "Year 2 CS student. Looking for internships, hackathons, tech talks and people to network with." | AI | Shapes priorities and the digest. Mail matching your interests ranks higher. |
| `courses` | `CS1101S`, `MA1521`, `CS2040S` | **Code**: the code appears in the subject, body or sender (Canvas, Ed, course mailing lists) | `MB: CS1101S` |
| `senders` | `tan@nus.edu.sg` → "Prof Tan", direct only, priority at least 2 | **Code**: address or name match. *Direct only* means you're the only To recipient: private mail, not a class announcement. | `MB: Prof Tan`, and its priority raised to at least P2 |
| `topics` | **Networking:** "career fairs, meetups, recruiter outreach, hackathons, tech talks, alumni events", priority at least 2 | AI: the classifier gets your topic descriptions and tags each email with the ones that fit | `MB: Networking` |

- **Code where code can decide.** Course codes and senders are exact, so no AI is involved: they're free, instant and never wrong about a match.
- **AI where it takes judgement.** "Is this a networking opportunity?" is the kind of question the AI answers well when given definitions. It's the same technique that made the built-in categories score 12/12 (§3.3).
- **Tags are checked.** The classifier may only return topics from your list; anything else is dropped. Each email's tags are saved in the archive beside its classification.
- **Priority floors:** a rule can say "at least P2". The more important of the AI's priority and the floor wins, so `MB: P<n>` changes too.
- **Boosted ⭐** emails get their own digest section, **OPPORTUNITIES & EVENTS**, so networking mail isn't buried under FYI, and are raised to at least P2. An email is boosted when:
  - it gets one of your **topic** labels **and** the AI judges it fits your **profile** (the classifier returns `boost`; without a profile, any topic label boosts), or
  - it matches a **course or sender** rule marked `--boost` (e.g. the career office).

**When you change a rule:**
- **Course and sender rules** are re-applied to the whole archive straight away. They need no AI, so this is instant.
- **Topic and profile rules** apply to new mail from the next run. To apply them to older mail, `mailbrief labels retag --period this-month` asks the AI again for that period only. That costs about one AI call per email, a few minutes for a month.
- **Outlook catches up by itself.** The labels each email should carry change, so the next run (or `labels apply`) swaps them using the existing pending mechanism (§3.4).
- **Removing a rule keeps its labels as history** on emails that already have them; only new mail stops getting it. To take one off: `mailbrief labels clear --label MA1521` (emails MailBrief labelled) or `--everywhere` (every email in the mailbox, plus your category list). Both ask first.

**From Telegram (M7):**
```
/labels                                              list your rules
/label add course CS2040S
/label add sender tan@nus.edu.sg "Prof Tan" direct
/label add topic Networking "career fairs, meetups, hackathons, tech talks"
/label remove course MA1521                          (semester's over)
/profile Year 2 CS student looking for internships and hackathons
```
Each change is echoed back ("✅ Added course CS2040S. 14 saved emails match; they'll be labelled on the next run.").

**How it's built:**
- **Recipients.** GetItem now fetches `ToRecipients` and `CcRecipients`; *direct only* means you're the only To recipient. Older saved emails get them from a one-off `mailbrief run --backfill` (GetItem only; no AI for emails already classified).
- **No new Outlook permissions.** Every label is an `MB: ` category, which the write guard already allows.
- **Colours:** courses dark blue, senders cranberry, topics dark green.

### 3.9 Ask your inbox (M7, planned)
Chat with your email in Telegram. You ask; MailBrief finds the relevant emails in your archive and answers from them.

```
You:        when is the CS1101S midterm and what can I bring?
MailBrief:  Saturday 7 Nov, 10:00–11:30, in MPSH 2 [1]. You may bring one
            double-sided A4 cheat sheet; calculators aren't allowed [1][2].
            Sources:
            [1] 12 Oct · CS1101S Teaching Team · "Midterm logistics"   Open in Outlook
            [2] 20 Oct · Prof Low · "Re: midterm cheat sheet question"  Open in Outlook
            [📎 Midterm_venue.pdf]
```

**How a question is answered:**
1. **Understand.** The cheap model (`qwen3.6:35b`) turns the question, plus today's date, into a search: some text, and optional sender, date range and labels. "Anything from Prof Tan last week?" becomes a date and sender filter, not just words.
2. **Find.** Filter the archive by those fields, then rank by meaning (vector similarity) plus keyword matches. Take the best ~12 emails and add their thread context. Questions about events ("what's on this week?") also use the saved `events` lists (§3.10), filtered by date in code.
3. **Answer.** The strong model (`qwen3.8:27b`, thinking on) gets the question and those emails, and writes an answer that cites its sources as [1], [2]. If the emails don't contain the answer, it says so rather than guessing.
4. **Reply.** The answer, then the numbered sources, each with an **Open in Outlook** link (deep-link format still to verify), and buttons for their attachments.

**Search index: a vector search, without a database server.**
- After each run saves the archive, new emails are **embedded** with `bge-m3` on the NUS endpoint. Embedding turns text into numbers, so that texts with similar meaning get similar numbers. Checked: the endpoint serves `bge-m3`, 1024 numbers per text, under a second per call.
- What's embedded per email: subject, sender, AI summary, labels, and the body in chunks of about 1,500 characters.
- Stored in `data/index.enc`, **encrypted** like the archive. It's only a derived copy, so `mailbrief index rebuild` recreates it from the archive at any time.
- **Search is a flat scan:** compare the question against every stored chunk. At about 1,500 emails a year this is exact and takes well under a second, so no vector database (Chroma, Qdrant…) is needed. `ponytail:` the ceiling is roughly 50,000 chunks; past that, move to `sqlite-vec`.

**Attachments, images and links:**
- Each source's attachments appear as **buttons**. Tap one and MailBrief fetches it through Outlook's read-only `GetAttachment` (already allowed by the write guard) and sends it to you with `sendDocument` or `sendPhoto`.
- **The answer may suggest** up to 3 images or files when they *are* the answer ("here's the timetable"). Code checks that each belongs to an email the answer cited before anything is sent.
- **Fetching opens headless Outlook**, which takes 5–10 s. It waits if a run is in progress.

**Conversation:**
- **Follow-ups work.** The last few turns are remembered per chat, so "and the final?" works. They're kept **in memory only**, never written to disk. `/new` starts fresh.
- **Fresh mail:** answers come from the archive, which is as current as the last run. `/sync` starts a run now. `/digest` resends today's digest.
- **In a terminal:** `mailbrief chat` works the same way without Telegram, for testing.

**Where it runs:** inside `mailbrief serve`. A listener thread long-polls Telegram (`getUpdates`), so there's no webhook and no open port, and it works behind home Wi-Fi. It acts only on your allowlisted chat (§3.6).

**Safety:**
- Unlike the digest model, **the answer model reads email bodies**, so a malicious email could try to steer an answer. The model has **no tools**, can only reply in your chat, and every file it suggests is checked in code.
- **More content goes to Telegram** than the summary-only digest: quotes, and attachments you ask for. Telegram bot chats aren't end-to-end encrypted. `CHAT=off` disables chat entirely (§8).

**Later, not M7:**
- Reading the text of PDF and Office attachments, so questions can be answered from them. Needs a parsing dependency.
- Voice questions, through `whisper-large-v3`, which the endpoint also serves.

---

### 3.10 Newsletter images & events (M6b, planned)
A newsletter announcing five events becomes "newsletter with upcoming events" today, with one date at most (§3.3). M6b keeps every event. It doesn't depend on the label rules (M6a); only the ⭐ for boosted topics uses them once they exist.

- **An `events` list per email.** The classifier also returns
  `[{name, detail, date "YYYY-MM-DD" or null, time, place, link, signup_deadline}]`, and it is empty for most mail.
  - `detail` is **one line** on what the event is and why you'd go, e.g. "Google SWE talk + resume review, free pizza".
  - Events are checked in code like the other fields: bad dates become null, events without a name are dropped, and there are at most about 10 per email.
  - `one_line_summary` and `deadline` (the single most urgent date) stay as they are.
- **Why a list and not a longer summary.** A longer summary for every email costs tokens on mail with nothing to say. It also hits the digest's 2,500-character limit anyway, and dates written as sentences can't be sorted or filtered. A list can. A second "short version" summary can come later, only for P1–P2 mail, if the digest still feels thin.
- **Inline images are read.**
  - Inline image attachments of **15 KB or more** go to the vision model too, up to about 5 per email (today it's 3, non-inline only).
  - Logos and signature icons are smaller and stay skipped. `ponytail:` the size threshold is a heuristic; a per-sender skip list is the upgrade if logos still slip through.
  - To verify first: that OWA lists inline images in `Attachments` with `IsInline` set, on a real newsletter.
- **Linked images: opt-in, off by default** (`REMOTE_IMAGES=off`).
  - Loading them tells the sender you opened the mail, the same as a tracking pixel.
  - It would also need the HTML body, not just plain text.
  - When on: image URLs are taken from the HTML body and size-checked (at most about 5), then downloaded over plain HTTP, never through the Outlook session.
- **An UPCOMING EVENTS message.**
  - **Code, not AI, builds it,** and it goes out as a second Telegram message after the digest. Nothing is rewritten or made up, and the digest's 2,500-character limit isn't touched.
  - **Sorted** by date. Past events are dropped, and duplicates (the same name and date in two emails) are merged.
  - **Boosted topics** (your M6a rules, once built) are marked ⭐ and listed first.
  - The AI digest still mentions upcoming sign-up deadlines under DEADLINES & MEETINGS.

  ```
  📅 UPCOMING EVENTS
  ⭐ Thu 23 Oct 7pm · Google SWE talk · COM3 LT19
     Talk + resume review for interns, free pizza
     sign up by Wed 22 Oct · https://…
  • Sat 25 Oct 10am · Hack&Roll info session · Zoom
     Team formation and prize tracks for Hack&Roll 2027
  ```
- **Saved.** Each email's `events` go in the archive beside its classification, as text only (images are never stored). M7 chat answers "what's on this week?" from them (§3.9).
- **Cost.** More emails go through the vision model, at about 1.7 s each. A newsletter-heavy day takes longer, but still minutes.

## 4. Data Model

There is no database: one user's data fits in a few small files in `data/` (git-ignored). Each is written atomically, so a crash never leaves a half-written file.

| File | Holds | Encrypted |
|---|---|---|
| `session.enc` | Outlook cookies + browser identity | Yes |
| `archive/YYYY-MM.enc` | That month's emails, classifications, digests, Outlook-label bookkeeping (below) | Yes (plain `.json` with `--no-password`) |
| `cursor.json` | Newest processed time + last 500 email IDs | No (IDs only) |
| `destinations.json` | Telegram chat IDs (written only by the CLI) | No |
| `schedule.json`, `logs/YYYY-MM.log` | The service's state and log (no email content) | No |
| `rules.json` | Your own labels: profile, courses, senders, topics (§3.8) | No (rules only, no email content) |
| `index.enc` *(M7)* | Search vectors for chat (§3.9); rebuildable from the archive | Yes |

Per email, the archive stores the `EmailRecord` plus `classification`, `replied`, `thread_size`, and `outlook_labels` / `labels_cleared` / `outlook_gone` (§3.4). M6a added `tags` and `boost` (inside `classification`), and `to` / `cc` / `direct` (recipients); M6b adds `events` (inside `classification`, §3.10).

`ponytail:` JSON files are right for one person. A database would only be needed for many users, which is cancelled (§13).

**Email archive** (`archive.py`): each run saves its emails, with their classifications and the digest, to `data/archive/YYYY-MM.enc`, one file per received month.
- **Encrypted by default** with `SESSION_ENCRYPTION_KEY`, so there's no password to type: `mailbrief emails` decrypts in memory.
- `run --no-password` writes plain `YYYY-MM.json` instead. A month only ever has one of the two files.
- Emails merge by ID, so re-runs never duplicate them.
- **Already-saved emails are never sent to the AI again**: their stored classification is reused.
- Image contents are never stored, only attachment names.
- **Kept forever by default.** Set `ARCHIVE_DAYS` to drop months that ended more than that many days ago.
- Old per-day files (`YYYY-MM-DD.*`) are folded into month files automatically.

Files never move. **This week / this month / last month / older** are computed when you view:
- this week starts on Monday;
- this month starts on the 1st;
- older means before last month.

**Backfill:** `mailbrief run --backfill` saves the whole inbox once.
- It goes oldest conversation first, with no digest.
- It saves every 25 emails, so Ctrl+C keeps progress and a rerun continues where it stopped, skipping saved emails.
- Afterwards the cursor sits at the newest email, so daily runs only see new mail.

**Threads.** A reply or forward is always a **new email** with the same `ConversationId`; the original is never edited.
- For each new conversation the app fetches *every* message, using `GlobalItemIds`, so your own replies in Sent Items are included.
- It orders them by Exchange's `ConversationIndex`: a 22-byte root plus 5 bytes per reply level, so parents come before replies.
- It recognises your messages by your address from Outlook's `StartupData`.
- The classifier sees up to 6 earlier thread messages as context.
- An email you answered is marked **✓ replied** and never listed under NEEDS A REPLY.
- Your sent and other-folder messages are saved for context only, with no AI call.

```
mailbrief emails                       # this week, grouped by thread (↳ = reply, "You →" = you)
mailbrief emails --period last-month   # this-week | this-month | last-month | older
mailbrief emails --day 2026-10-16      # one day
mailbrief emails --search fee          # sender / subject / body, all periods
mailbrief emails --show 3              # full email + AI classification + thread outline
mailbrief emails --thread 3            # the whole conversation in order, with bodies
mailbrief emails --digest              # digests saved today (or for --day)
mailbrief emails --export out.json     # plain JSON copy, on request only
```

---

## 5. Project Structure

Files marked *(M7)* are planned and don't exist yet.

```
mail-manager/
├── README.md, commands.md, teaching.md
├── pyproject.toml, uv.lock, .env.example
├── Dockerfile, compose.yaml, .dockerignore   # always-on `serve` on your own server
├── mailbrief/
│   ├── main.py                 # CLI: login, run, emails, labels, add-destination, serve/stop/status/autostart
│   ├── service.py              # the schedule, locks, child runs, autostart
│   ├── archive.py              # encrypted monthly email archive, periods
│   ├── cursor.py               # which emails are new
│   ├── threads.py              # conversation order, "you replied", context
│   ├── labels.py               # which MB: labels each email needs; apply / clear / status
│   ├── destinations.py         # Telegram chats to deliver to
│   ├── progress.py             # live progress lines (stderr)
│   ├── rules.py                # your own labels: load/check rules.json, course/sender matching, floors, boosts
│   ├── index.py                # (M7) embeddings + flat vector search over the archive
│   ├── session/
│   │   ├── login_once.py       # the one-time visible login
│   │   └── manager.py          # save/load the encrypted session
│   ├── browser/
│   │   ├── connect.py          # local launch, or connect_over_cdp if BROWSER_WS_URL set
│   │   ├── outlook_reader.py   # drive Outlook: open, listen, scroll, GetItem / GetAttachment
│   │   ├── owa_network.py      # parse Outlook's JSON, build requests, the write guard (check_request)
│   │   └── outlook_writer.py   # the only code that changes Outlook: MB: categories
│   ├── ai/
│   │   ├── client.py           # complete(): any OpenAI-compatible endpoint (stdlib urllib)
│   │   ├── classifier.py       # Pass 1: one email → category, priority, summary, your topic tags + boost (+ M6b events)
│   │   ├── digest.py           # Pass 2: the digest
│   │   └── answer.py           # (M7) question → search → cited answer
│   ├── notify/
│   │   ├── __init__.py         # ADAPTERS registry
│   │   ├── telegram.py         # sending, splitting, flood control
│   │   └── bot.py              # (M7) the allowlisted listener: questions, /label commands, buttons
│   └── storage/
│       └── crypto.py           # Fernet encrypt/decrypt
├── data/                       # gitignored: session, archive, cursor, rules, index, logs
└── tests/                      # one plain-assert script per module (test_*.py)
```

---

## 6. Configuration (`.env`)

```
# AI: any OpenAI-compatible endpoint (preferably your company's own model)
AI_BASE_URL=https://soclaas-api.comp.nus.edu.sg/v1
# AI_API_KEY=...                  # optional; falls back to the SOCLAAS_API_KEY system env var
AI_CLASSIFIER_MODEL=qwen3.6:35b
AI_VISION_MODEL=qwen3.8:27b
AI_DIGEST_MODEL=qwen3.8:27b

# Browser: empty = local Chromium (default); set to use Browserless later
BROWSER_WS_URL=
FALLBACK_AGENT=off

TELEGRAM_BOT_TOKEN=...
SESSION_ENCRYPTION_KEY=...
DATABASE_URL=sqlite:///data/mailbrief.db   # unused: there is no database (§4)
DEFAULT_TIMEZONE=Asia/Singapore
# When `mailbrief serve` runs: "<days> <HH:MM> [scope]; …" e.g. "daily 07:30; sun 20:00 this-week" (see commands.md §7)
RUN_AT=daily 07:30
# MB: labels (categories) on your emails in Outlook: on | off (commands.md §5)
OUTLOOK_LABELS=on
RESTORE_UNREAD=true             # DOM fallback only
ARCHIVE_DAYS=0                  # 0 = keep saved emails forever; N = drop months older than N days

# Planned (M6b): download images linked from email bodies (tells senders you opened the mail; §3.10)
REMOTE_IMAGES=off

# Planned (M7): chat with your inbox (§3.9)
CHAT=on                         # off = the bot stays send-only
AI_EMBED_MODEL=bge-m3           # turns emails and questions into vectors for search
AI_ANSWER_MODEL=qwen3.8:27b     # writes the cited answers
```

---

## 7. Daily Run Flow

1. `serve` fires a run at a `RUN_AT` time (or you type `mailbrief run`).
2. Session Manager decrypts the session and gets a headless browser (local by default).
3. **Session check.** If expired, send a re-login alert (once a day) and stop.
4. Inbox Reader collects emails newer than the cursor through Outlook's own network calls, with list previews as the fallback. The refreshed session is re-saved.
5. AI Processor runs Pass 1: classify each new email, with your profile, tagging your topics (M6b: also list events). Your course and sender rules are applied in code.
6. The emails are saved to the archive. From M7 the new ones are added to the search index.
7. Sorter applies the `MB:` labels in Outlook.
8. Pass 2 writes the digest.
9. Notifier sends the digest to all active destinations.
10. The cursor advances, only if the digest was delivered.
11. The run is logged: progress, counts and results, never email content.

**Failure policy:** if reading succeeds but sorting fails, still send the digest and flag the sorting failure. A digest is never silently dropped.

---

## 8. Security

**Where data goes**

| Data | Goes to | Notes |
|---|---|---|
| Session cookies, email bodies | Local browser on your machine only | Unless Browserless is enabled (below) |
| Saved emails (archive) | `data/archive/` on your machine | Encrypted by default; plain only with `--no-password` |
| Email text for classification/digest | `AI_BASE_URL` | Use your company's model to keep it in-house |
| Digest text (summaries only) | Telegram | Not end-to-end encrypted; summary-level only |
| Chat answers with quotes, and attachments you ask for *(M7)* | Telegram | Not end-to-end encrypted; more than summary level. `CHAT=off` turns it off |
| Text for search vectors *(M7)* | `AI_BASE_URL` (`bge-m3`) | Same in-house endpoint as classification |
| Everything the browser sees | Browserless | **Only if** `BROWSER_WS_URL` is set. Self-hosted stays local; cloud is a third party |

**Rules**
- `storage_state` files act as **passwords** for the mailbox: encrypt them at rest (Fernet/AES), keep them out of git, and use file permissions of `600`.
- The Telegram bot token, AI key and `BROWSER_WS_URL` (it can contain a token) live in `.env` or a secrets manager only. Never log them.
- **Browserless cloud sends work data to a third party** (US servers). Get employer/IT approval and a data-processing agreement first. Logging in locally and then uploading the session does **not** avoid this, because the cookies still go to the cloud.
- **Email content is untrusted.** Models that read it have no tools. The fallback agent never runs with an email body open, and its actions pass through a code-enforced blocklist (§3.5).
- **Telegram bot is send-only and locked down** (§3.6). Only chat IDs added via the local CLI receive digests. From M7 it also listens, but acts only on those chats.
- **The chat answer model reads email bodies** (M7, §3.9), so an injected email could try to mislead an answer. It has no tools, can only reply in your chat, and any file it suggests is checked in code against the emails it cited.
- **The only change MailBrief makes in Outlook is its own `MB:` categories** (§3.4), enforced by `check_request` before any request leaves the machine.
- Email content is saved only in the local archive: encrypted by default and kept until you set `ARCHIVE_DAYS`. The encryption protects copies of `data/` (sync, backups, indexers, an accidental commit). It doesn't protect against someone logged into your Windows account, who also has `.env`.
- The AI provider is configured for zero retention.
- Check your employer's acceptable-use policy before automating a work account.

---

## 9. Hosting

| Option | Pros | Cons |
|---|---|---|
| **Always-on local machine** (Windows/Linux PC, mini PC) with local Chromium | Trusted device, stable IP, longest sessions, data stays local, no Docker | Must stay powered and online |
| Same machine + Browserless in Docker (later) | Browser isolated from the host, resource limits, debugger UI | Docker (WSL2 on Windows Home) and disk space for little gain with one user |
| Browserless cloud (later, IT approval only) | No browser to run or maintain | Third-party data processing (§8), datacenter IP, more re-logins, plan limits on session length |

**Recommendation for v1:** run locally on a machine the user already signs in from, and do the one-time login **on that machine**.

**Always on, locally:** `mailbrief autostart on` (Task Scheduler starts `serve` at logon).

**Always on, on a server:** `docker compose up -d --build` with the repo's `Dockerfile` and `compose.yaml`.
- The container runs `mailbrief serve` as a non-root user, with `restart: unless-stopped`.
- `.env` is passed in at runtime, and `data/` is a volume. Neither is baked into the image.
- Log in on your PC, then copy `data/session.enc` across (with the same `SESSION_ENCRYPTION_KEY`).

Steps: [commands.md §7 "Hosting"](commands.md#7-running-automatically). This is hosting **for yourself** only; hosting for other people is cancelled (§13).

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Session expires / MFA re-prompt | Detect redirect → Telegram re-login alert → quick re-login command |
| Outlook UI changes break selectors | Network-first reading (no selectors except the message list and tabs); optional AI fallback and failure screenshots (M8) |
| Outlook's internal JSON format changes | DOM fallback; all parsing in `owa_network.py`; `read_path` logged per run |
| Prompt injection via email content | No tools for models that read email; agent only runs with no email open; code-enforced action blocklist |
| Work AI model refuses to summarize mail | Test before M3; endpoint is swappable via `AI_BASE_URL` |
| Long inbox → slow/expensive | Cursor-based incremental reads, batching, cheap classifier model |
| Accidental destructive action | No delete code path; `check_request` refuses every write except `MB:` categories |
| Strangers using the Telegram bot | Send-only bot; CLI-only destinations; group joins disabled |
| Digest content on Telegram vs company policy | Summary-level digests; pluggable adapters (Email/Teams) |
| Telegram message limits | Auto-split, priorities first |
| Opening emails marks them read | Network path doesn't open emails; `RESTORE_UNREAD` on the DOM path |
| An email steers a chat answer (M7) | Answer model has no tools; replies only to you; suggested files checked against cited emails; sources always shown so you can check |
| Chat answers from stale data (M7) | Index updated every run; `/sync` runs now; sources show each email's date |
| Too many custom labels clutter Outlook (M6a) | Labels only from your own rules; old courses removable with `labels clear --label` (or `--everywhere`); all share the `MB: ` prefix for filtering |
| Logos read as event posters, or an event missed (M6b) | 15 KB size threshold (per-sender skip list later); the email's text is still read; events checked in code |
| AI tags a topic wrongly (M6a) | Tags validated against your list; topic descriptions in the prompt; `labels retag` after editing a description |

---

## 11. Tech Stack

- **Language:** Python 3.11+
- **Browser automation:** Playwright with local Chromium (`playwright install chromium`)
- **Optional browser runtime (later):** Browserless (`ghcr.io/browserless/chromium` in Docker, or browserless.io cloud)
- **AI models:** any OpenAI-compatible endpoint, preferably your company's own model (cheap model for classification, stronger model for the digest)
- **AI fallback agent (optional, M8):** browser-use, behind a code-enforced blocklist
- **Storage:** JSON files in `data/`, encrypted with Fernet where private; search vectors in an encrypted file (M7)
- **Scheduling:** built-in `mailbrief serve` (stdlib), started by Windows Task Scheduler at logon or by Docker on a server
- **Delivery:** Telegram Bot API over plain HTTPS (send-only, no SDK needed)
- **Encryption:** `cryptography` (Fernet)

---

## 12. Roadmap

| Milestone | Deliverable |
|---|---|
| **M1** ✅ | `login_once` + headless session reuse (local Chromium); print today's inbox subjects from network capture |
| **M2** ✅ | Full email extraction to JSON with cursor/dedupe; list-preview fallback (DOM fallback deferred) |
| **M3** ✅ | Test the work AI model on real emails; classification (text + images) + digest via `AI_BASE_URL`; send to one Telegram chat |
| **M4** ✅ | Outlook labels: `MB: <category>` + `MB: P<priority>`, coloured, applied every run, `labels status/apply/clear`, code-enforced write guard. (Re-login alert done in M5.) |
| **M5** ✅ | Scheduler (`serve`, extensible `RUN_AT`, catch-up, retries), `stop` / `status`, Windows autostart, run lock, run logs, login-expired Telegram alert, Docker hosting files. (CLI-only destinations, multiple destinations already done; bot lockdown = `/setjoingroups` in @BotFather) |
| **M6a** ✅ | Your own labels (§3.8): `rules.json`; profile, courses, senders (direct-only), AI topics with priority floors; To/Cc recipients + archive re-fetch; boosts + OPPORTUNITIES & EVENTS digest section; `mailbrief rules`, `labels retag`, `labels clear --label [--everywhere]`. (Telegram `/label` commands: M7) |
| **M6b** | Newsletter images & events (§3.10): inline images to the vision model (≥15 KB, up to ~5); `events` list with one-line `detail`; code-built UPCOMING EVENTS message; linked images opt-in (`REMOTE_IMAGES`) |
| **M7** | Ask your inbox (§3.9): `bge-m3` index, allowlisted Telegram listener in `serve`, cited answers, attachment buttons, `/label` and `/profile` commands, `/sync`, `mailbrief chat` |
| **M8** | Optional AI fallback agent behind a code-enforced blocklist, failure screenshots, move mode |
| **Later** | Attachment text (PDF/Office) in the index, voice questions (`whisper-large-v3`), Browserless (Docker, then cloud), WhatsApp/Slack/Email/Teams adapters, Gmail support, web dashboard |
| ~~Multi-user~~ | **Cancelled** for legal reasons (§13) |

---

## 13. Multi-user hosting (deprecated)

> ⚠️ **Cancelled.** Plans to host MailBrief for other people are cancelled for legal reasons. MailBrief is, and stays, a **single-user** tool.

- **Why.** Hosting for others means holding their live mailbox sessions and their email content, which includes personal data about every sender. That brings personal-data duties under Singapore's PDPA (consent, retention, deletion, breach reporting) and university IT-policy approval. A personal project can't responsibly carry those.
- **What still works.** Everything for **you**: on your PC, or always-on on **your own** server with Docker (§9).
- **What changes in the design.** Nothing is built for several users: no accounts, no per-user keys, no signup, no database. JSON files in `data/` stay the right choice (§4).
- **[hosting-checklist.md](hosting-checklist.md)** is kept only as a record of what was considered. It no longer applies.
