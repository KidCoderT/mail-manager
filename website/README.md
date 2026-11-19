# MailBrief showcase

Static HTML, CSS and JavaScript. Open `index.html` directly; no build, dependencies, analytics or backend. All illustrated mail and chat exchanges are invented. The browser demo plays canned responses and never connects to a mailbox or AI endpoint.

The setup guide is `setup.html`. Keep its commands aligned with `.env.example` and `commands.md` when changing the CLI.

## GitHub Pages

The repository's `.github/workflows/pages.yml` publishes this folder on pushes to `main`. In repository **Settings → Pages → Build and deployment**, select **GitHub Actions** as the source. After merging the branch into `main`, the workflow publishes to `https://kidcodert.github.io/mail-manager/`. It also supports a manual workflow dispatch.

## Verification

From the repository root:

```sh
uv sync
uv run playwright install chromium --no-shell
uv run python scripts/check_website.py
```

Checks local files and anchors, JavaScript errors, example tabs and keyboard navigation, canned chat, copy controls, narrow layouts, dark mode, the light/dark toggle, and the page without JavaScript. It opens the files directly in headless Chromium; no server or accounts are needed.

`assets/showcase.png` is a screenshot of the site's invented inbox/chat illustration, used in the repository README. It contains no real mail.
