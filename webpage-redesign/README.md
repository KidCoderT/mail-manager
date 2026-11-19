# MailBrief website

Open `index.html` directly. Three static pages, one stylesheet and one script; no build, external assets, analytics or backend.

Every page is one terminal window: a tab bar, the content, a prompt you can type into and a status bar.

- `index.html`: the terminal. A short banner, a command rail, and a session that answers typed commands with invented mail.
- `setup.html`: installation through the first digest, then optional archive and scheduling.
- `docs.html`: CLI and Telegram reference, configuration, hosting and privacy. `commands.md` remains the canonical detailed reference.

## What the prompt understands

On the home page: `help`, `about`, `commands`, `man <command>`, `setup`, `docs [command]`, `github`, `tour`, `theme dark|light|system`, `clear`, and the simulated `mailbrief run`, `events`, `chat`, `status` and `labels status`. Any other real command prints its manual entry. Tab completes, Up and Down recall history, and typing anywhere on the page lands in the prompt. Command clicks respond immediately; only the optional tour types commands, and typing, Escape, or Stop tour cancels all pending tour work.

On every page, `setup` opens the complete setup guide and `docs [command]` opens the reference. Other commands, including `man <command>` and simulations, run in the home terminal; setup/docs hand them over without changing their meaning. On docs, `/text` additionally filters the page. The mobile command menu and contents lists can be expanded without typing.

The session only matches known inputs to prewritten responses. It cannot execute commands or connect to a mailbox, and the CSP disallows network connections. The `MAN` list in `site.js` holds one usage line per real command; the checker fails if the parser gains a command that the list lacks.

Dark is the first-visit and no-JavaScript default. Without JavaScript the pages and the sample digest remain readable, and the prompt and command buttons are hidden. Motion (brief output fade, opening wordmark scramble, the subtle glyph backdrop) is off under reduced motion.

## Verification and deployment

From the repository root:

```sh
uv sync --frozen
uv run playwright install chromium --no-shell
uv run python scripts/check_website.py
```

The checker verifies local links, parser and Telegram command coverage, themes, keyboard interactions, narrow layouts, no-JavaScript content and the terminal. GitHub Pages runs it before uploading this directory on pushes to main. Opening any page with `#selftest` in the URL runs the script's own assertions in the console.

The opening example shows a concise Telegram digest, with processing logs in an expandable detail. The setup guide is the only installation walkthrough; the terminal links to it instead of offering an incomplete shortcut. Common questions in docs cover cost, app registration, platform support, removal and lost keys.
