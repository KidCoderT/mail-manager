# MailBrief — AI Morning Email Digest (Outlook)

> **Status:** v1 works end to end (M1–M5 ✅: reading, AI classification and digests, Outlook labels, scheduled service), plus **your own labels** (M6a ✅, §3.8) and **newsletter images & an UPCOMING EVENTS calendar** (M6b ✅, §3.10) and **chatting with your inbox in Telegram**, with a ↗ link to the Outlook email on every digest line, event and answer (M7 ✅, §3.9).
> **Scope:** one person's Outlook on the web (Microsoft 365), Playwright driving a **local Chromium**, Telegram delivery (more channels pluggable). [Browserless](https://www.browserless.io) is an optional later runtime. **Single-user only:** multi-user hosting is cancelled (§13).

> ⚠️ **Disclaimer:**
> - MailBrief is a personal project, not affiliated with or endorsed by Microsoft or NUS.
> - It uses Outlook on the web's **internal** API, not a public one, so it can break without warning.
> - Use it only on **your own** mailbox, and check your organisation's IT and acceptable-use policies first.
> - Email text is sent to whichever AI endpoint you configure.
> - It comes with no warranty ([MIT License](LICENSE)).

> 📘 **Docs:** [commands.md](commands.md) (every command in detail) · [teaching.md](teaching.md) (how and why the code works)

MailBrief reads your work inbox every morning with a headless browser on your own machine. It labels the emails inside Outlook (categories, **never deletes**) and sends a summary to one or more destinations, starting with Telegram. It also labels mail by your own rules (courses, professors, networking), keeps a calendar of the events your emails announce, and answers questions about your email in a Telegram chat. Every line it sends links to the email in Outlook.

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
- **Ask your inbox** (M7 ✅): ask in Telegram ("when is the CS1101S midterm?", "any hackathons this month?") and get an answer from your emails, with quotes, sources and attachments (§3.9).

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

**Images** (M6b, details in §3.10) go to the vision model, kept in memory only and never saved. Up to 5 per email and 8 MB in total:
- **attached images** of 15 KB–5 MB, and **inline** ones (in the body) of 30 KB–5 MB, through `GetAttachment`. Signature logos are smaller and skipped;
- **linked images** that newsletters load from the web (`REMOTE_IMAGES=on`): found in the HTML body and downloaded with safety checks.

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
- **Allowlisted listener (M7 ✅).** To answer your questions (§3.9) and take label commands (§3.8), `serve` reads the bot's incoming messages. It **acts only on private chats listed in `data/destinations.json`**. Every other chat, and every group, is ignored without a reply, so a stranger who finds the bot learns nothing. `CHAT=off` returns to send-only.
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
- `/label …` commands in your Telegram chat (below; M7 ✅).

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

**From Telegram (M7 ✅):**
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

### 3.9 Ask your inbox ✅ (M7: `index.py`, `ai/answer.py`, `notify/bot.py`, `links.py`)
Chat with your email in Telegram. You ask; MailBrief finds the relevant emails in your archive and answers from them. (Example from a made-up test mailbox.)

```
You:        and what can I bring?            (after "when is the CS1101S midterm?")
MailBrief:  • You may bring "ONE A4 double-sided cheat sheet, handwritten or printed" ↗
            • It can include "code snippets," but "no full past-year solutions," and font size
              must be "at least 8pt" ↗
            • "Calculators are not allowed" ↗
            Sources
            17 Oct · CS1101S Teaching Team · CS1101S Midterm logistics      ← tap: opens it in Outlook
            23 Oct · Prof Low Wei Ming · Re: cheat sheet question
            [📎 Midterm_seating.pdf]                                         ← tap: the file is sent here
```

**Links to Outlook, everywhere.** Every digest bullet, every event in the calendar and every claim in an answer ends with a ↗ that opens that exact email in Outlook. Source lines are links too.
- **The format** is Microsoft's documented web link, `https://outlook.office.com/owa/?ItemID=…&viewmodel=ReadMessageItem`. Outlook redirects it to its current address by itself. Verified: it opens exactly the linked email. (`/mail/inbox/id/…` did not.) It only works for someone signed in to your mailbox.
- **Links are built by code from the email's id.** The model only writes `[3]` style refs, which code turns into links, and all model text is escaped. So an email can't plant a link of its own in your digest or an answer.
- **On a phone** it opens Outlook on the web, or the Outlook app if it claims the link. Opening an email marks it read, as Outlook always does.
- **Known limit:** Outlook usually gives an email a new id when it's moved to another folder, so links (and attachment buttons) for mail you've since moved or archived may stop working. The bot then says the file is no longer in Outlook.

**How emails are pulled and read (no Outlook at question time):**
- **Answers come from the local archive**, which every run already fills: full text, classification, labels, events and threads. Asking never opens a browser.
- **Keeping it complete:** scheduled runs add new mail; `run --backfill` (once) adds older inbox mail and refreshes records; `/sync` starts a run now.
- **Only the best ~12 emails** (about 2.5k characters each, with thread context) go to the answering model, never the whole inbox. A search index finds them in well under a second.

**How a question is answered:**
1. **Understand.** The cheap model (`qwen3.6:35b`) turns the question, plus today's date, into a search: some text, and optional sender, date range and labels. "Anything from Prof Tan last week?" becomes a date and sender filter, not just words.
2. **Find.** Filter the archive by those fields in code, then rank by meaning (vector similarity) plus keyword matches (BM25), with a small nudge for recent mail. Take the best ~12 emails and add their thread context.
   - **Event and deadline questions** ("what's on this week?", "anything due for CS1101S soon?") use the saved `events` lists (§3.10) and each email's `deadline`. The date range applies to the *events' and deadlines'* dates, not when the emails arrived, and those emails lead the results. "What did X send last week?" still filters by arrival date.
3. **Answer.** The strong model (`qwen3.8:27b`, thinking on) gets the question and those emails as data. It answers only from them, cites every fact as `[n]`, and quotes exact phrases where wording matters. If the emails don't say, it says so and shows the closest matches.
4. **Reply.** The answer with ↗ links, then the **Sources** (each line a link), then buttons for the sources' attachments.

**Checked on a made-up mailbox** (15 invented emails, real endpoint):
- Exam date and rules, a professor's reply in a thread, "did I pay my fee?" (connecting a reminder and a receipt), a deadline and who set it, "events this week", "what's in November", "any hackathons", follow-up questions, and "send me the seating plan" (the right file) were all answered correctly, with correct citations.
- An off-topic question was answered "the emails don't say".
- Answers take 3–30 s; broad questions over many emails ("what's due this week?") can take a minute or more while the model thinks.
- **Final test on real mail** (one-off, with permission): exam rules, this week's networking events, an assignment's requirements, "anything due for CS1101S", "what's due this week" and "what did X send last week" were answered correctly with exact quotes and sources. Two bugs found and fixed there: deadline questions searched by arrival date, and the endpoint allows at most 4 images per prompt.

**Search index: a vector search, without a database server.**
- After each run saves the archive, new or changed emails are **embedded** with `bge-m3` on the NUS endpoint. Embedding turns text into numbers, so that texts with similar meaning get similar numbers. Measured: about 30 texts a second in batches of 64.
- **Per email:** a header chunk (subject, sender, date, summary, labels, attachment names, events) plus the body without quoted history, in chunks of about 1,500 characters (at most 6).
- **Stored** in `data/index.enc`, **encrypted** like the archive. It holds only vectors and hashes; chunk text is recomputed from the archive. It's a derived copy: `mailbrief index rebuild` recreates it at any time.
- **Size:** about 870 chunks for ~400 emails, around 3.5 MB.
- **Search is a flat scan:** compare the question against every stored chunk, in plain Python. At about 1,500 emails a year this is exact and fast, so no vector database (Chroma, Qdrant…) and no new dependency is needed. `ponytail:` past roughly 20,000 chunks, move to numpy, then `sqlite-vec`.

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
- Each source's attachments appear as **buttons** (up to 8; inline images like logos are left out). Tap one and MailBrief fetches it through Outlook's read-only `GetAttachment` (already allowed by the write guard) and sends it to you with `sendDocument` or `sendPhoto`. The file goes from memory to Telegram and is never written to disk.
- **The answer may ask to send** up to 3 files when they *are* the answer ("send me the timetable"). Code checks that each is a real attachment of an email the answer cited before anything is sent.
- **Fetching opens headless Outlook**, which takes 5–10 s. If a run is using Outlook at that moment, you're asked to tap again in a minute.
- Saved emails record each attachment's id, name, size and type (never the content). Older mail gets them from `run --backfill`.

**Conversation:**
- **Follow-ups work.** The last few turns are remembered per chat, so "and the final?" works. They're kept **in memory only**, never written to disk. `/new` starts fresh.
- **Fresh mail:** answers come from the archive, which is as current as the last run. `/sync` starts a run now (the digest arrives as usual). `/digest` resends the latest digest, `/events` the calendar.
- **Labels from the chat:** `/labels`, `/label add …`, `/label remove …` and `/profile …` edit `rules.json`, exactly like `mailbrief rules` (§3.8).
- **In a terminal:** `mailbrief chat` works the same way without Telegram. `mailbrief bot` runs only the listener, for testing.

**Where it runs:** inside `mailbrief serve`. A listener thread long-polls Telegram (`getUpdates`), so there's no webhook and no open port, and it works behind home Wi-Fi. It acts only on your allowlisted chat (§3.6). Logs record counts and timings only, never questions or answers.

**Why plain Python and not a Telegram bot library:**
- **Async clashes with Playwright.** The popular libraries (python-telegram-bot v20+, aiogram) are asyncio-based, and Playwright's sync API (used for attachments) refuses to run inside an asyncio loop.
- **They want to own the process.** `run_polling()` wants the main thread and installs its own signal handlers, but `serve` already owns stopping (Ctrl+C, `mailbrief stop`, autostart).
- **A new dependency** with a history of breaking rewrites.
- **We need little:** about 7 Bot API methods, on top of the existing tested sender (429 back-off, UTF-16 sizing, splitting).
- `ponytail:` switch to pyTelegramBotAPI (sync, threaded) if conversation flows, inline mode or webhooks are ever needed.

**Safety:**
- Unlike the digest model, **the answer model reads email bodies**, so a malicious email could try to steer an answer. The model has **no tools**, can only reply in your chat, and every file it suggests is checked in code.
- **More content goes to Telegram** than the summary-only digest: quotes, and attachments you ask for. Telegram bot chats aren't end-to-end encrypted. `CHAT=off` disables chat entirely (§8).

**Later, not M7:**
- Reading the text of PDF and Office attachments, so questions can be answered from them. Needs a parsing dependency.
- Voice questions, through `whisper-large-v3`, which the endpoint also serves.

---

### 3.10 Newsletter images & events ✅ (M6b: `events.py`, `web_images.py`)
Before M6b, a newsletter announcing five events became "newsletter with upcoming events", with one date at most. Now every event is kept, and a daily calendar message lists them.

**What a structure-only check of real mail showed** (counts and flags only, no content read):
- **Mass newsletters** (sent with mailing tools such as Mailchimp) usually have **no attachments**. They load their images, often a dozen or more, from web links.
- **Emails written by people** often paste posters in **inline**, hundreds of KB to several MB each. Inline signature images are much smaller, under about 20 KB.
- So both kinds have to be read: linked images for the first, inline ones for the second.

- **An `events` list per email.** The classifier also returns
  `[{name, detail, date "YYYY-MM-DD" or null, time, place, link, signup_deadline}]`, and it is empty for most mail.
  - `detail` is **one line** on what the event is and why you'd go, e.g. "Google SWE talk + resume review, free pizza".
  - Events are checked in code like the other fields: bad dates become null, events without a name are dropped, and there are at most about 10 per email.
  - `one_line_summary` and `deadline` (the single most urgent date) stay as they are.
- **Why a list and not a longer summary.** A longer summary for every email costs tokens on mail with nothing to say. It also hits the digest's 2,500-character limit anyway, and dates written as sentences can't be sorted or filtered. A list can. A second "short version" summary can come later, only for P1–P2 mail, if the digest still feels thin.
- **Inline images are read.** Inline attachments of **30 KB or more** go to the vision model (attached ones from 15 KB, as before). Signature logos are smaller. Confirmed: Outlook lists inline images in `Attachments` with `IsInline` set.
- **Limits per email:** at most **4 images** (the NUS endpoint refuses more: "At most 4 image(s) may be provided in one prompt") and **8 MB** in total, each at most 5 MB. If the endpoint ever refuses an email's images anyway, it's classified from its text instead. Checked on the endpoint with synthetic images: 7.9 MB in one request is accepted. `ponytail:` bigger posters are skipped, not resized (that needs Pillow).
- **Linked images: on by default** (`REMOTE_IMAGES=on`), with safeguards:
  - A read-only GetItem fetches the **HTML** body of the emails being classified. Image URLs are taken from it and the HTML is dropped.
  - **Skipped by URL:** anything that isn't `https`, URLs with a query string (tracking images usually carry one), and names that look like icons or logos (facebook, logo, avatar, spacer, pixel…).
  - **Downloads are guarded:** the host is resolved first, and refused if any address is on a private, loopback or link-local network. Redirects aren't followed. There's a 10 s timeout, no cookies and no Outlook session, and at most 12 tries per email.
  - **Kept only if** it's a real image type (png/jpeg/webp/gif) and at least 15 KB, which drops leftover icons and pixels.
  - **The privacy trade-off:** the senders' image servers see your IP address and when MailBrief read the mail, often before you open it. `REMOTE_IMAGES=off` stops this; events then come from the text and inline images only.
  - Measured on one week of real mail: 16 images (8.4 MB) for 5 newsletters, about 12 s added to the run.
- **An UPCOMING EVENTS message: a rolling 14-day calendar.**
  - **Code, not AI, builds it,** and it goes out as a second Telegram message after every digest. Nothing is rewritten or made up, and the digest's 2,500-character limit isn't touched. The digest model doesn't see events at all; `deadline` still feeds DEADLINES & MEETINGS.
  - **From all saved mail**, not just today's: every event in the next `EVENTS_DAYS` days (default 14; `0` turns it off). 🆕 marks events from this digest's emails.
  - **Grouped by day**, with ⭐ boosted events (your rules, §3.8) first within each day, then by time. Past events are dropped, and the same event in two emails (same name and date) is merged into one.
  - **Undated events** appear only on the day their email arrives, under DATE NOT GIVEN, so they don't repeat forever.
  - A passed sign-up deadline shows as "sign-up closed".
  - Long calendars split per day in Telegram (day headings work like digest sections).
  - **Any time:** `mailbrief events [--days N] [--send]` prints or sends it, with no Outlook and no AI. `--past 30` adds the last 30 days (`--days 0` for past only). `emails --digest --send` resends it with the digest.

  ```
  📅 UPCOMING EVENTS · next 14 days (3)

  FRI 23 OCT
  ⭐🆕 7pm · Google SWE talk · COM3 LT19
     Talk + resume review for interns, free pizza
     sign up by Thu 22 Oct · https://…

  SUN 25 OCT
  • 10am · Hack&Roll info session · Zoom
     Team formation and prize tracks

  DATE NOT GIVEN
  🆕 CS Career Fair volunteer call
  ```
- **Saved.** Each email's `events` go in the archive beside its classification, as text only (images are never stored). M7 chat answers "what's on this week?" from them (§3.9).
- **Cost.** More emails go through the vision model, at about 1.7 s each, plus the image downloads. A newsletter-heavy day takes longer, but still minutes.
- **Checked on made-up emails** (no real mail): the 12 benchmark categories still score 12/12 with the events field in the prompt, and 6 of 6 events in two made-up newsletters came back with the right dates, times, places and links.
- **Older mail:** `mailbrief run --backfill` (right after a morning run) refreshes each email's image list with the new inline rule, with no AI. Then `mailbrief labels retag --period this-month` re-classifies, which fills in events.

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
| `index.enc` | Search vectors for chat (§3.9); rebuildable from the archive | Yes |

Per email, the archive stores the `EmailRecord` plus `classification`, `replied`, `thread_size`, and `outlook_labels` / `labels_cleared` / `outlook_gone` (§3.4). M6a added `tags` and `boost` (inside `classification`), and `to` / `cc` / `direct` (recipients); M6b added `events` (inside `classification`, §3.10).

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


```
mail-manager/
├── README.md, commands.md, teaching.md
├── pyproject.toml, uv.lock, .env.example
├── Dockerfile, compose.yaml, .dockerignore   # always-on `serve` on your own server
├── mailbrief/
│   ├── main.py                 # CLI: login, run, emails, labels, rules, events, add-destination, serve/stop/status/autostart
│   ├── service.py              # the schedule, locks, child runs, autostart
│   ├── archive.py              # encrypted monthly email archive, periods
│   ├── cursor.py               # which emails are new
│   ├── threads.py              # conversation order, "you replied", context
│   ├── labels.py               # which MB: labels each email needs; apply / clear / status
│   ├── destinations.py         # Telegram chats to deliver to
│   ├── progress.py             # live progress lines (stderr)
│   ├── rules.py                # your own labels: load/check rules.json, course/sender matching, floors, boosts
│   ├── events.py               # the UPCOMING EVENTS calendar, built by code from saved events
│   ├── web_images.py           # linked images in emails: guarded downloads for the vision model
│   ├── index.py                # search index: chunks, bge-m3 embeddings, flat vector + keyword search
│   ├── links.py                # ↗ links to the emails in Outlook, built by code
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
│   │   ├── classifier.py       # Pass 1: one email → category, priority, summary, your topic tags + boost, events
│   │   ├── digest.py           # Pass 2: the digest
│   │   └── answer.py           # ask your inbox: question → plan → search → cited answer
│   ├── notify/
│   │   ├── __init__.py         # ADAPTERS registry
│   │   ├── telegram.py         # sending, splitting, flood control
│   │   └── bot.py              # the allowlisted Telegram listener: questions, commands, attachment buttons
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

# Images linked from email bodies (newsletters): downloaded for the AI, with safety checks.
# The senders' image servers see your IP and when the mail was read; off = text + attached/inline images only (§3.10)
REMOTE_IMAGES=on
# UPCOMING EVENTS message after each digest: how many days ahead (0 = don't send it)
EVENTS_DAYS=14

# Chat with your inbox in Telegram (§3.9)
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
5. AI Processor runs Pass 1: classify each new email, with your profile, tagging your topics and listing its events (from text and images). Your course and sender rules are applied in code.
6. The emails are saved to the archive, and new or changed ones are added to the search index.
7. Sorter applies the `MB:` labels in Outlook.
8. Pass 2 writes the digest.
9. Notifier sends the digest to all active destinations, then the UPCOMING EVENTS calendar (built by code from the archive).
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
| Chat answers with quotes, and attachments you ask for | Telegram | Not end-to-end encrypted; more than summary level. `CHAT=off` turns it off |
| Image downloads (linked images in emails) | The senders' image servers | They see your IP address and when MailBrief read the mail. `REMOTE_IMAGES=off` stops it |
| Text for search vectors | `AI_BASE_URL` (`bge-m3`) | Same in-house endpoint as classification |
| Everything the browser sees | Browserless | **Only if** `BROWSER_WS_URL` is set. Self-hosted stays local; cloud is a third party |

**Rules**
- `storage_state` files act as **passwords** for the mailbox: encrypt them at rest (Fernet/AES), keep them out of git, and use file permissions of `600`.
- The Telegram bot token, AI key and `BROWSER_WS_URL` (it can contain a token) live in `.env` or a secrets manager only. Never log them.
- **Browserless cloud sends work data to a third party** (US servers). Get employer/IT approval and a data-processing agreement first. Logging in locally and then uploading the session does **not** avoid this, because the cookies still go to the cloud.
- **Email content is untrusted.** Models that read it have no tools. The fallback agent never runs with an email body open, and its actions pass through a code-enforced blocklist (§3.5).
- **Telegram bot is send-only and locked down** (§3.6). Only chat IDs added via the local CLI receive digests. It also listens (M7), but acts only on those chats.
- **The chat answer model reads email bodies** (§3.9), so an injected email could try to mislead an answer. It has no tools, can only reply in your chat, never writes links (code builds them from email ids), and any file it suggests is checked in code against the emails it cited.
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
| An email steers a chat answer | Answer model has no tools; replies only to you; suggested files checked against cited emails; sources always shown so you can check |
| Chat answers from stale data | Index updated every run; `/sync` runs now; sources show each email's date |
| Too many custom labels clutter Outlook (M6a) | Labels only from your own rules; old courses removable with `labels clear --label` (or `--everywhere`); all share the `MB: ` prefix for filtering |
| Logos read as event posters, or an event missed (M6b) | 30 KB inline / 15 KB attached thresholds; icon-like URLs skipped; the email's text is still read; events checked in code |
| A malicious image link in an email (M6b) | https only; private/loopback/link-local addresses refused after resolving; no redirects; size, type and time limits; images never saved |
| Image-heavy days are slow (M6b) | 4 images / 8 MB per email; 12 URL tries per email; `REMOTE_IMAGES=off` |
| AI tags a topic wrongly (M6a) | Tags validated against your list; topic descriptions in the prompt; `labels retag` after editing a description |

---

## 11. Tech Stack

- **Language:** Python 3.11+
- **Browser automation:** Playwright with local Chromium (`playwright install chromium`)
- **Optional browser runtime (later):** Browserless (`ghcr.io/browserless/chromium` in Docker, or browserless.io cloud)
- **AI models:** any OpenAI-compatible endpoint, preferably your company's own model (cheap model for classification, stronger model for the digest)
- **AI fallback agent (optional, M8):** browser-use, behind a code-enforced blocklist
- **Storage:** JSON files in `data/`, encrypted with Fernet where private; search vectors in an encrypted file
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
| **M6a** ✅ | Your own labels (§3.8): `rules.json`; profile, courses, senders (direct-only), AI topics with priority floors; To/Cc recipients + archive re-fetch; boosts + OPPORTUNITIES & EVENTS digest section; `mailbrief rules`, `labels retag`, `labels clear --label [--everywhere]`. (Telegram `/label` commands came with M7) |
| **M6b** ✅ | Newsletter images & events (§3.10): inline images (≥30 KB) and guarded linked-image downloads (`REMOTE_IMAGES=on`), 4 images / 8 MB per email; `events` list with one-line `detail`; code-built rolling 14-day UPCOMING EVENTS calendar (`EVENTS_DAYS`), `mailbrief events` |
| **M7** ✅ | Ask your inbox (§3.9): ↗ links to Outlook on every digest line, event and answer; encrypted `bge-m3` index with hybrid search; cited answers with quotes and sources; allowlisted Telegram listener in `serve`; attachment buttons and requested files; `/sync`, `/digest`, `/events`, `/label`, `/profile`; `mailbrief index`, `chat`, `bot` |
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
