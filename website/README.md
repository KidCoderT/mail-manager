# MailBrief showcase

Static HTML, CSS and JavaScript. Open `index.html` directly; no build, dependencies, analytics or backend. All illustrated mail and chat exchanges are invented. The browser demo plays canned responses and never connects to a mailbox or AI endpoint.

The design uses graphite/slate surfaces, warm-white text and a restrained cobalt accent. Body copy is sans-serif; commands, logs and small labels retain the terminal influence. The header theme button remembers a light/dark preference; without JavaScript the site follows the operating system. The hero shows one fictional digest preview, not live output.

The setup guide is `setup.html`: steps 1–7 lead to the first digest, followed by optional backfill, custom labels, scheduling and hosting. Keep its commands aligned with `.env.example` and `commands.md` when changing the CLI. Detailed workflow and command references remain available in expandable sections, including through direct links.

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

`assets/showcase.png` is a screenshot of the site's invented digest illustration, used in the repository README. It contains no real mail. The examples share a 10 November 2026 morning timeline; the payment-receipt chat follows on 11 November.
