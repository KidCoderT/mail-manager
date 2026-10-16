from playwright.sync_api import sync_playwright

from mailbrief.browser.connect import get_browser
from mailbrief.browser.outlook_reader import INBOX_URL
from mailbrief.session import manager


def login_once() -> None:
    with sync_playwright() as p:
        browser = get_browser(p, headless=False)
        context = browser.new_context()
        page = context.new_page()
        # Read before navigating: Outlook keeps redirecting, which destroys the page's JS context.
        user_agent = page.evaluate("navigator.userAgent")
        page.goto(INBOX_URL)
        print("Sign in to Outlook in the browser window (MFA, tick 'Stay signed in').")
        input("When your inbox is visible, press Enter here... ")
        manager.save(context, user_agent)
        browser.close()
    print(f"Session saved (encrypted) to {manager.SESSION_PATH}")
