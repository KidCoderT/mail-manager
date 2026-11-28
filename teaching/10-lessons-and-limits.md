# Lessons from real bugs, known limits

<!-- TOC -->
**Contents**

- [12. Lessons from real bugs](#12-lessons-from-real-bugs)
- [13. Known limits and next steps](#13-known-limits-and-next-steps)
<!-- /TOC -->

## 12. Lessons from real bugs

Each of these was found by running against real Outlook, and each shaped the code.

1. **"Execution context was destroyed" at login.** Reading from the page while Outlook redirected. *Lesson:* never talk to a page mid-navigation. Read stable things before navigating.
2. **Only the pinned/flagged emails showed up.** The list loads about 50 at a time and needs real mouse-wheel scrolling. *Lesson:* virtualized lists only load what a human would scroll to.
3. **286 conversations "of 572".** After clicking *Other*, Outlook refreshed *Focused* in the background, and its responses were counted in the wrong view. *Lesson:* tag data by where it came from (`FocusedViewFilter`), not by when it arrived.
4. **The *Other* tab was invisible at first.** M1 only ever read *Focused*; 56 conversations were silently missed. *Lesson:* check the totals the system reports against what you captured.
5. **Emoji crashed printing on Windows.** The Windows console encoding can't encode 🙋 when output is piped. *Lesson:* force UTF-8 at the entry point.
6. **Receipts marked priority 1.** The model read "1" as lowest. *Lesson:* spell out scales and give anchors.
7. **"Pay the fee", already paid.** Emails were summarised in isolation. *Lesson:* tell the summariser to connect related items.
8. **Backfill crashed with HTTP 429.** A shared AI server has rate limits. *Lesson:* back off and retry, and never let one failure sink a batch job.
9. **"Couldn't find your address."** StartupData is JSON served with a JavaScript content type, so the JSON filter dropped it. *Lesson:* don't trust content-type labels; match on what you actually need.
10. **Only 180 of 344 loaded.** Outlook paused between pages longer than the 5 s stall rule. *Lesson:* timeouts against real services need slack, plus a warning when results are incomplete.
11. **Wrong order across time zones.** Times with `+05:30` and `Z` sorted as text. *Lesson:* compare real datetimes, never formatted strings.
12. **The silent 15-minute digest.** `run --all --send` widened the digest to all 357 emails: 15 sequential thinking calls, no output, then two months of mail headed for your phone. *Lessons:* one flag, one job (`--all` processes, `--digest` summarises); anything that can take minutes must show progress; and parallelise independent AI calls.
13. **The blank month digest.** The merge call, with thinking on, used its entire token budget reasoning and returned nothing, so the digest printed only its header line. *Lessons:* thinking models can "think out" their budget; check for empty answers, retry differently, and fail loudly rather than show a blank.
14. **`--backfill --send` refused to advance the cursor.** With no digest to send, "delivered" stayed false. *Lesson:* "nothing to deliver" and "delivery failed" are different states; don't let one boolean stand for both.
15. **The digest that never arrived.** A long digest silently failed to reach Telegram. The splitter counted Python characters with no margin (Telegram counts UTF-16), cut sections wherever the limit fell, didn't handle flood control, and reported only "HTTP Error 400". *Lessons:* measure limits the way the receiving system measures them, leave a margin, split on meaningful boundaries (sections, then lines), respect `retry_after`, and keep the remote system's error message: it usually tells you the fix.
16. **The categorize button is a rule.** The probe showed that Outlook's own "Categorize" doesn't label the email: it creates an *always categorise this conversation* rule. Copying the UI blindly would have left server-side rules on hundreds of threads. *Lesson:* record what the system actually does before copying it, and copy the intent ("label this email"), not the button.
17. **One slow batch lost a whole restore.** Re-labelling 360 emails right after deleting their categories hit a 30 s request timeout. Results were only saved at the very end, so the whole pass counted as failed. *Lessons:* keep partial progress per batch, allow slack on timeouts, and make operations idempotent: the retry finished in 24 s because done emails cost only a read.
18. **The 40-minute classify.** During a short AI or network outage, a `/sync` sat on "Classifying 9/12" for 40 minutes, then hung writing the digest until the 45-minute watchdog killed it. The client waited 300 s per attempt and retried 5 times, silently, so each unanswered call could hold the run about 32 minutes. *Lessons:* size timeouts to the job, retry hangs only a couple of times (unlike rate limits), and log every retry so a stall is visible.
19. **The orphaned `/sync`.** Stopping `serve` waited only for *scheduled* runs. A `/sync` run, started from the bot's thread, kept running on its own, with no 45-minute watchdog since that lived in `serve`, and held the run lock. Your next `run --send` said *"Another MailBrief run is in progress"*. The fix: `_run_child` records every child in `_children`; `serve` waits for them when stopping, and kills them on a second Ctrl+C. *Lesson:* every process you start needs an owner that outlives it, or kills it.
20. **The slow strong model.** The stalls kept landing on the same image email and on the digest. Tests with made-up prompts ruled out prompt size, image size, thinking and concurrency. The real cause was the shared endpoint's `qwen3.8:27b` dropping to 11 tokens/s, against 145 for `qwen3.6:35b`. *Lessons:* measure tokens per second before blaming the input; give each job the fastest model that passes its benchmark; and when a slower, stronger model is worth having, give it a fallback rather than a longer timeout.
21. **The retry that never came.** A failed email was saved as Unclassified with the promise "it will be retried next run". But the cursor advanced past it, the next run only read conversations newer than the cursor, and `select_new` never picked it again. Only `--all` would have. The fix: `failed_ids` lists recent Unclassified inbox emails, their conversations are fetched anyway, and `select_new(..., retry)` lets them through, so they're classified and land in that run's digest. *Lesson:* a promise like "retried later" needs a test that follows the email through the *next* run, cursor included.

---

## 13. Known limits and next steps

**Limits today** (most are marked `ponytail:` in the code):
- Every run scrolls the **whole** inbox, about 20–30 s here. Very large inboxes would want an early stop at the cursor.
- **Wide digests take minutes** (about 5 for a month of ~150 emails). Parts run in parallel, but the final thinking merge is one long call. Fine on demand, not for every morning.
- Mail moved into the inbox late can fall behind the cursor and be skipped.
- Only the **Inbox** is read for new mail, though thread context includes other folders.
- A **forward** you sent counts as "replied".
- JSON files instead of a database: fine for one user.
- The AI can't see PDFs or Office attachments, only their names.
- Images over 5 MB are skipped, not resized. Linked images are chosen by name and size, so an odd banner can take a slot from a poster.
- Events from older mail need `labels retag`; dates the AI can't work out stay undated.
- **Service logs are never pruned** (one small file per month); delete old ones by hand if you like.
- The **Docker image hasn't been built yet** (to save disk); expect small fixes on the first build.
- On a server you sign in through `/login` (section 7.24). Microsoft may expire logins from datacenter IPs sooner, and an organisation can block them outright.

**Roadmap** ([design notes §12](../docs/design.md)):
- **M4 ✅:** `MB: <category>` + `MB: P<priority>` labels in Outlook, coloured, applied every run, easy to clear (section 7.16). The session-expired alert came with M5.
- **M5 ✅:** `serve` with an extensible schedule, `stop` / `status`, autostart at logon, run locks, logs, the login alert, Docker files (section 7.15).
- **M6a ✅:** your own labels: courses, professors (direct-only), AI topics, a profile, priority floors, boosts and the OPPORTUNITIES & EVENTS section (section 7.17). Telegram `/label` commands come with M7.
- **M6b ✅:** newsletter images and events: inline posters and guarded linked-image downloads, an `events` list per email, a rolling 14-day UPCOMING EVENTS calendar built by code (sections 7.18 and 7.19).
- **M7 ✅:** ask your inbox: ↗ links to Outlook on every digest line, event and answer; the search index; cited answers; the Telegram chat with attachment buttons and commands (sections 7.20–7.23).
- **M8:** optional self-healing browser agent behind a code-enforced blocklist, failure screenshots, and a "move to folders" mode.
- **Later:** WhatsApp/Slack/email delivery, Gmail, Browserless (Docker/cloud), a dashboard. Multi-user hosting is cancelled ([design notes §13](../docs/design.md)).
