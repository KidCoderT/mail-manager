# MailBrief — AI Morning Email Digest (Outlook)

> **Status:** Architecture plan / v1 design
> **Scope of v1:** Outlook on the web (Microsoft 365), Playwright driving a **local Chromium**, Telegram delivery (more channels pluggable). [Browserless](https://www.browserless.io) is an optional later runtime.

MailBrief reads a user's work inbox every morning with a headless browser on the user's own machine. It sorts the emails inside Outlook (categories/folders, **never deletes**) and sends a summary to one or more destinations, starting with Telegram.

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

### Non-Goals (v1)
- ❌ Deleting, archiving to trash, or permanently removing any email
- ❌ Sending or replying to emails
- ❌ Gmail / other providers (planned for later)
- ❌ Multi-tenant SaaS signup flow (v1 runs for one user or a small team)

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
                │  Storage (SQLite)         │  users, sessions, cursors,
                │  + encrypted session files│  destinations, run logs
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

**Primary: capture Outlook's own data.** Outlook's page fetches the message list and message bodies as JSON. `page.on("response")` captures those responses as the page loads and scrolls:
- real item and conversation IDs (stable dedupe keys),
- structured fields (sender, subject, received time, read state, importance, attachments),
- message bodies without opening each email, so **nothing gets marked as read**.

That format is internal and undocumented, so all parsing lives in **one file** (`browser/owa_network.py`). When it changes, only that file needs fixing.

**Fallback: DOM.** If the network parse fails, scroll the message list and open each email, using **stable selectors** (aria-labels, roles, visible text) from `selectors.py`. Opening an email marks it read, so this path restores the unread state afterwards (`RESTORE_UNREAD`).

**Both paths**
- Read until reaching emails older than `last_processed_at`, deduped against `last_processed_ids`.
- Per email: `id`, `sender_name`, `sender_email`, `subject`, `received_at`, `body_text` (plain text, trimmed), `has_attachments` + names, `is_read`, `importance`.
- Output: a list of `EmailRecord` JSON objects.

### 3.3 AI Processor
A two-pass pipeline behind **one function**, `complete(prompt) -> str` (`ai/client.py`). It calls any **OpenAI-compatible** chat endpoint set by `AI_BASE_URL`. **Your company's own AI model is the preferred choice**, so email content stays in-house. No provider-specific code lives anywhere else.

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

### 3.4 Sorter
Writes results back to Outlook **through the UI only**.

| Mode | Action | Risk |
|---|---|---|
| `categorize` (default) | Right-click → Categorize → `MB: Urgent`, etc. | Lowest; nothing moves |
| `move` | Right-click → Move → target folder | Medium; email leaves inbox |

- Categories and folders are prefixed (`MB: …`) so they're clearly the app's.
- Missing categories or folders are created on first run.
- **No delete action exists in the code.** There is no code path to the Delete button.

### 3.5 AI Fallback Agent (optional, off by default)
Enabled with `FALLBACK_AGENT=on`. When a scripted step fails (selector not found or timeout):
1. Capture a screenshot and the page's accessibility tree.
2. Hand the single failed step to an AI browser agent (e.g. `browser-use`) with a narrow instruction ("Apply category 'MB: Urgent' to the selected email").
3. Log the fallback event so the scripted selector can be fixed.

**Limits are enforced in code (`browser/guard.py`), not in the prompt:**
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

- **Multiple destinations per user.** Every digest goes to all active destinations.
- **Telegram's limit is ~4,096 chars/message.** Split long digests into parts, with the top priorities first.
- Delivery failures to one destination don't block the others. Each is retried and logged.

**Telegram bot lockdown** (nobody else can use or hijack the bot):
- **Send-only bot.** The app never polls for incoming messages, so `/start` from strangers does nothing. There is no self-registration and no invite codes.
- **Destinations are added only via the local CLI** (`mailbrief add-destination`). The CLI reads the chat ID once, during setup, from the message you send the bot.
- In BotFather, set **`/setjoingroups` → Disable**, so nobody can add the bot to their own group. Re-enable it briefly only to add it to your own group.
- **The bot token is a password.** Whoever has it controls the bot. Keep it in `.env` only and `/revoke` it in BotFather if it leaks.
- The app never accepts a user-supplied bot token.

**Policy note:** Telegram bot chats are **not end-to-end encrypted**, so digest text leaves the company. Keep the digest summary-level (no full email bodies), and switch to an Email/Teams adapter if policy requires.

### 3.7 Scheduler
- Windows **Task Scheduler** or cron (Linux/macOS) fires the job runner. APScheduler can be used if the app runs as a long-lived process.
- Per-user `run_time` and `timezone` (default `07:00 Asia/Singapore`).
- A lock per user prevents overlapping runs.
- A manual "run now" command is available for testing.

---

## 4. Data Model

```
users
  id, name, timezone, run_time, sort_mode (categorize|move),
  status (active|needs_relogin|paused), created_at

sessions
  user_id, encrypted_state_path, last_refreshed_at, last_valid_at

cursors
  user_id, last_processed_at, last_processed_ids (recent N, for dedupe)

destinations             (written only by the local CLI)
  id, user_id, type (telegram|whatsapp|slack|...), target (chat_id/number/...),
  label, active

runs
  id, user_id, started_at, finished_at, status (ok|failed|relogin),
  emails_processed, read_path (network|dom), fallback_count, error_message

email_results            (optional, short retention)
  run_id, email_hash, category, priority, one_line_summary
```

Raw email bodies are **not** persisted. They live in memory for the duration of a run only.

---

## 5. Project Structure

```
mailbrief/
├── README.md
├── pyproject.toml
├── .env.example
├── config/
│   └── categories.yaml         # category names, rules, prompts
├── mailbrief/
│   ├── main.py                 # CLI: login, run, run-now, add-destination
│   ├── scheduler.py
│   ├── session/
│   │   ├── login_once.py
│   │   └── manager.py          # load/validate/refresh/encrypt storage_state
│   ├── browser/
│   │   ├── connect.py          # local launch, or connect_over_cdp if BROWSER_WS_URL set
│   │   ├── owa_network.py      # capture + parse Outlook's own JSON responses
│   │   ├── outlook_reader.py   # network-first read, DOM fallback
│   │   ├── outlook_sorter.py   # categorize / move
│   │   ├── selectors.py        # all selectors in one place
│   │   ├── guard.py            # code-enforced action blocklist for the agent
│   │   └── fallback_agent.py   # optional AI self-healing step runner
│   ├── ai/
│   │   ├── client.py           # complete(prompt) -> str, OpenAI-compatible
│   │   ├── classifier.py
│   │   ├── digest.py
│   │   └── prompts/
│   ├── notify/
│   │   ├── __init__.py         # ADAPTERS registry
│   │   └── telegram.py
│   ├── storage/
│   │   ├── db.py
│   │   └── crypto.py
│   └── logging.py
├── data/                        # gitignored: sessions, db, screenshots
└── tests/
```

---

## 6. Configuration (`.env`)

```
# AI: any OpenAI-compatible endpoint (preferably your company's own model)
AI_BASE_URL=https://...
AI_API_KEY=...
AI_CLASSIFIER_MODEL=...
AI_DIGEST_MODEL=...

# Browser: empty = local Chromium (default); set to use Browserless later
BROWSER_WS_URL=
FALLBACK_AGENT=off

TELEGRAM_BOT_TOKEN=...
SESSION_ENCRYPTION_KEY=...
DATABASE_URL=sqlite:///data/mailbrief.db
DEFAULT_TIMEZONE=Asia/Singapore
DEFAULT_RUN_TIME=07:00
SORT_MODE=categorize
RESTORE_UNREAD=true             # DOM fallback only
```

---

## 7. Daily Run Flow

1. Scheduler fires for the user at their `run_time`.
2. Session Manager decrypts `storage_state` and gets a headless browser (local by default).
3. **Session check.** If expired, send a re-login alert and stop.
4. Inbox Reader collects emails newer than the cursor: network capture first, DOM fallback if that fails.
5. AI Processor runs Pass 1 (classify), then Pass 2 (digest).
6. Sorter applies categories or moves per `sort_mode`.
7. Session Manager re-saves the refreshed `storage_state`.
8. Cursor is updated.
9. Notifier sends the digest to all active destinations.
10. Run is logged (counts, read path, fallbacks, errors, screenshot on failure).

**Failure policy:** if reading succeeds but sorting fails, still send the digest and flag the sorting failure. A digest is never silently dropped.

---

## 8. Security

**Where data goes**

| Data | Goes to | Notes |
|---|---|---|
| Session cookies, email bodies | Local browser on your machine only | Unless Browserless is enabled (below) |
| Email text for classification/digest | `AI_BASE_URL` | Use your company's model to keep it in-house |
| Digest text (summaries only) | Telegram | Not end-to-end encrypted; summary-level only |
| Everything the browser sees | Browserless | **Only if** `BROWSER_WS_URL` is set. Self-hosted stays local; cloud is a third party |

**Rules**
- `storage_state` files act as **passwords** for the mailbox: encrypt them at rest (Fernet/AES), keep them out of git, and use file permissions of `600`.
- The Telegram bot token, AI key and `BROWSER_WS_URL` (it can contain a token) live in `.env` or a secrets manager only. Never log them.
- **Browserless cloud sends work data to a third party** (US servers). Get employer/IT approval and a data-processing agreement first. Logging in locally and then uploading the session does **not** avoid this, because the cookies still go to the cloud.
- **Email content is untrusted.** Models that read it have no tools. The fallback agent never runs with an email body open, and its actions pass through a code-enforced blocklist (§3.5).
- **Telegram bot is send-only and locked down** (§3.6). Only chat IDs added via the local CLI receive digests.
- Email content is held in memory per run, not stored long-term.
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

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Session expires / MFA re-prompt | Detect redirect → Telegram re-login alert → quick re-login command |
| Outlook UI changes break selectors | Network-first reading; centralized `selectors.py`; optional AI fallback; failure screenshots |
| Outlook's internal JSON format changes | DOM fallback; all parsing in `owa_network.py`; `read_path` logged per run |
| Prompt injection via email content | No tools for models that read email; agent only runs with no email open; code-enforced action blocklist |
| Work AI model refuses to summarize mail | Test before M3; endpoint is swappable via `AI_BASE_URL` |
| Long inbox → slow/expensive | Cursor-based incremental reads, batching, cheap classifier model |
| Accidental destructive action | No delete code path; `guard.py` blocklist; categorize mode by default |
| Strangers using the Telegram bot | Send-only bot; CLI-only destinations; group joins disabled |
| Digest content on Telegram vs company policy | Summary-level digests; pluggable adapters (Email/Teams) |
| Telegram message limits | Auto-split, priorities first |
| Opening emails marks them read | Network path doesn't open emails; `RESTORE_UNREAD` on the DOM path |

---

## 11. Tech Stack

- **Language:** Python 3.11+
- **Browser automation:** Playwright with local Chromium (`playwright install chromium`)
- **Optional browser runtime (later):** Browserless (`ghcr.io/browserless/chromium` in Docker, or browserless.io cloud)
- **AI models:** any OpenAI-compatible endpoint, preferably your company's own model (cheap model for classification, stronger model for the digest)
- **AI fallback agent (optional):** browser-use, behind `guard.py`
- **Storage:** SQLite
- **Scheduling:** Windows Task Scheduler / cron
- **Delivery:** Telegram Bot API over plain HTTPS (send-only, no SDK needed)
- **Encryption:** `cryptography` (Fernet)

---

## 12. Roadmap

| Milestone | Deliverable |
|---|---|
| **M1** | `login_once` + headless session reuse (local Chromium); print today's inbox subjects from network capture |
| **M2** | Full email extraction to JSON with cursor/dedupe; DOM fallback |
| **M3** | Test the work AI model on real emails; classification + digest via `AI_BASE_URL`; send to one Telegram chat |
| **M4** | Sorter (categorize mode) + re-login alert |
| **M5** | CLI-only destinations, bot lockdown, multiple destinations, scheduler, run logs |
| **M6** | Optional AI fallback agent behind `guard.py`, failure screenshots, move mode |
| **Later** | Browserless (Docker, then cloud), WhatsApp/Slack/Email/Teams adapters, Gmail support, web dashboard, multi-user |
