import os


def get_browser(p, headless: bool = True):
    """Local Chromium by default; a Browserless (or any CDP) browser if BROWSER_WS_URL is set."""
    ws_url = os.environ.get("BROWSER_WS_URL")
    if ws_url:
        return p.chromium.connect_over_cdp(ws_url)
    # Full Chromium build for both login and runs, so the session sees the same browser.
    return p.chromium.launch(channel="chromium", headless=headless)
