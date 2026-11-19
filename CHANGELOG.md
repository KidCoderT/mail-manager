# Changelog

## 1.0.0 (unreleased)

Everything from the milestones below, plus a review pass. No release tag has been published yet.

**Review pass (bugs, security, usability)**
- Runs: the cursor no longer advances when the archive couldn't be saved; a run that can't read Outlook's
  inbox list fails (exit 5) instead of reporting "no new emails"; an email that leaves the inbox keeps its
  classification; list-preview records are no longer archived; Ctrl+C stops queued AI calls.
- Service: a caught-up weekly or monthly digest covers its own period; a slot that already succeeded isn't
  run twice; schedules survive a clock change; a Telegram alert when a run fails three times; file saves
  retry on a briefly locked file (Windows).
- AI: impossible dates are rejected; dropped connections are retried and waits are capped; no built-in
  endpoint (`AI_BASE_URL` is required; `AI_API_KEY` is optional for keyless local servers). The Qwen thinking
  extension is opt-in (`AI_CHAT_TEMPLATE_KWARGS=on`) for strict OpenAI-compatible servers. Retry diagnostics
  go to stderr so JSON output stays valid.
- Chat: a missing key no longer kills the listener; a damaged search index is rebuilt; `/sync` answers when
  there is nothing new; errors say what to do; `/rules` and `/rule` (the old `/labels`, `/label` still work).
- Security: the sign-in server times out silent connections, never serves plain http to the network, and
  doesn't identify itself; image downloads have a total time limit and refuse IPv6-wrapped private
  addresses; a remote sign-in is verified before it replaces the saved session.
- CLI: every `--help` has a description and examples; `--plain` (was `--no-password`); clear one-line
  errors for a bad key, no network, no browser, Telegram problems and Ctrl+C.
- Sign-in page: separate email, password and code fields, a loading state, dark mode, a message per ending.
- Offline demo: 15 invented emails in a disposable archive, with real thread/event views and prewritten
  digest/chat examples; no accounts or AI endpoint needed.
- Showcase: terminal-style website in `website/`, with a Telegram digest preview, complete setup and command docs, and an interactive simulated terminal;
  GitHub Pages workflow and local responsive/accessibility smoke checks.
- Validation: pipeline failure tests and schedule retry regression tests; mypy and Ruff enforced in CI.

**Milestones**
- M7: ask your inbox in Telegram, links to the email on every line, remote sign-in.
- M6b: images in newsletters and an UPCOMING EVENTS calendar.
- M6a: your own labels (courses, senders, topics) with priorities.
- M5: `serve`, `stop`, `status`, autostart, Docker.
- M4: `MB:` categories in Outlook.
- M1–M3: sign in once, read the inbox, classify and digest, Telegram delivery.
