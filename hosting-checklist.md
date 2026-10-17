# Before hosting MailBrief for others: checklist

MailBrief today is **single-user and local**: your PC, your Outlook login, your `data/` folder. This file lists what has to be true, and what has to change, before other people can use it.

Work top to bottom. The first section can rule out the whole idea, so do it first.

---

## 1. Permission and policy (do these first)

### NUS IT policy
- [ ] **Ask NUS IT whether students may grant a third-party app read access to their mail** through Microsoft Graph (`Mail.Read`, delegated), and whether NUS's Microsoft account system needs admin approval for that. **This answer decides the design** (see §3).
- [ ] Confirm that NUS's IT acceptable-use rules allow **automated access** to student mailboxes, and processing their content with an AI service.
- [ ] Get the answer **in writing** (an email is enough) and keep it.

### Singapore's personal data law (PDPA)
Once you hold other people's emails, you're holding their personal data, and it often includes data about third parties too (the senders). The PDPA's main duties, in practice:

- [ ] **Consent:** users agree, clearly and before anything runs, that their mail is read, labelled by an AI, stored and summarised. "Your email is processed by the NUS AI service" must be stated explicitly.
- [ ] **Purpose limitation:** use the data only for digests. No analytics on content, and no reuse for anything else.
- [ ] **Notification:** a short privacy notice covering what is collected, why, where it's stored, how long it's kept, and who can see it.
- [ ] **Access and correction:** users can see what's stored about them (`emails --export` already does this per user).
- [ ] **Retention:** set a real limit for hosted users. Today the default is forever (`ARCHIVE_DAYS=0`). Delete data when it's no longer needed.
- [ ] **Withdrawal and deletion:** a "delete my account and all my data" action that really removes the archive, session, keys and destinations.
- [ ] **Protection:** reasonable security (§4). Encryption at rest is already in place per archive.
- [ ] **Breach notification:** a plan for who you tell and how fast. Significant breaches must be reported to the PDPC (Singapore's data regulator) and the affected users.
- [ ] **Data protection officer (DPO):** the PDPA expects someone to be responsible. For a student project that's you; write down that you are.
- [ ] **Transfer outside Singapore:** if the server or any service is overseas, check the PDPA rules for overseas transfer.

### AI resource (NUS SoC AI endpoint)
- Your position: the endpoint is an **NUS-run resource**. Requests go to NUS, and you have no access to what's sent through it; only NUS does. So using your key to serve other users doesn't expose their mail to you.
- [ ] Still confirm with NUS SoC that the key may be used for a service with **multiple users**: their quota and fair-use terms, and whether a per-user or project key is preferred. The question is about their usage terms, not who can see the data.
- [ ] Plan for **rate limits**: many users means many calls. The client already retries 429 errors, but a shared key needs a queue and per-user limits.

---

## 2. Already reusable as-is
These work for any user once they're handed "this user's emails":

- Parsing Outlook data (`browser/owa_network.py`)
- Threads (`threads.py`)
- Labelling and digests (`ai/`)
- Telegram splitting and sending (`notify/telegram.py`)
- Archive format and encryption (`archive.py`)

---

## 3. Getting into other people's mailboxes (the hard part)

| Option | How | Risk |
|---|---|---|
| **A. Microsoft Graph OAuth** (preferred) | Users click "Sign in with Microsoft" and grant read-only mail access. You get a token you can refresh; you never see their password or cookies. | Needs an app registered in Azure, and probably **NUS admin approval**. Rewrites the reading part: Graph replaces the headless browser. |
| B. Remote browser login | The user logs into Outlook (NUS single sign-on plus two-factor approval) through a browser streamed from your server; the cookies are saved encrypted. | You hold live login sessions to their mailboxes; a breach exposes them. Fiddly to build. |
| C. Upload a local session | Each user runs `mailbrief login` on their own machine and uploads the encrypted session. | Same cookie liability as B, and it needs re-uploading whenever the session expires. |

- [ ] Choose an option based on the §1 answer from NUS IT. If Graph isn't allowed, only B or C remain. Treat those as **trusted friends only**.

---

## 4. Code and infrastructure changes

| Area | Today | Needed |
|---|---|---|
| Accounts | None | User records; everything keyed by a user ID |
| Storage | Files in `data/` | One folder per user (small scale) or a database (e.g. Postgres) plus encrypted files |
| Encryption keys | One `SESSION_ENCRYPTION_KEY` in `.env` | **One key per user**, in a secrets manager, never on the same disk as the data |
| Telegram | Send-only; chat added by hand | One central bot (no one adds their own). It **listens** for `/start <link-code>` to tie a chat to an account, which proves the chat belongs to the user |
| Bot settings | `can_join_groups` on | `/setjoingroups` → Disable in @BotFather |
| Running | You type `run` | Scheduler plus job queue plus workers. Each run's Chromium needs about 300–500 MB of RAM (not needed with Graph); limit how many run at once |
| Login expiry | You notice | An automatic "please log in again" Telegram message (planned in M4) |
| Interface | Command line | Telegram commands (`/digest`, `/stop`, `/delete`) or a small signup website |
| Deployment | Your PC | Docker image, a server, HTTPS, backups (encrypted) |
| Logs | Your terminal | Structured logs with **no email content, addresses or secrets**, ever |
| Abuse limits | n/a | Caps on emails per run, digests per day and users per instance |

---

## 5. Security checks before launch
- [ ] No secret in the repo, image, logs or error messages (bot token, AI key, encryption keys, sessions).
- [ ] Each user's data is reachable **only** with their user ID and key; test that user A can never read user B's data.
- [ ] The server runs with least privilege, and its disk is encrypted.
- [ ] Dependencies are pinned, and you check them for known security holes.
- [ ] Deleting an account really deletes everything; test it.
- [ ] Encrypted backups, and a tested restore.

---

## 6. Easiest paths, ranked
1. **Each person runs their own copy** (Docker plus a guide). No hosting and no liability. But each needs their own bot token, which clashes with "no one adds their own bot".
2. **Hosted for a few trusted friends:** per-user folders and keys, central bot with `/start` linking, option C login.
3. **Proper hosted service:** Graph OAuth, database, workers, signup. The right design, but only if NUS IT approves.

**Next step:** the NUS IT question in §1.
