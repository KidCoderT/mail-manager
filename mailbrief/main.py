import argparse
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


def run(show_all: bool = False) -> int:
    from playwright.sync_api import sync_playwright

    from mailbrief.browser.connect import get_browser
    from mailbrief.browser.outlook_reader import read_inbox
    from mailbrief.browser.owa_network import received_on
    from mailbrief.session import manager

    session = manager.load()
    if session is None:
        print("No saved session. Run `mailbrief login` first.")
        return 2

    tz = ZoneInfo(os.environ.get("DEFAULT_TIMEZONE", "Asia/Singapore"))
    with sync_playwright() as p:
        browser = get_browser(p, headless=True)
        try:
            context = browser.new_context(storage_state=session["state"], user_agent=session["user_agent"])
            result = read_inbox(context.new_page())
            if result["expired"]:
                print("Outlook session expired. Run `mailbrief login` again.")
                return 2
            manager.save(context, session["user_agent"])  # Microsoft rotates auth cookies
        finally:
            browser.close()

    messages = result["messages"]
    shown = messages if show_all else received_on(messages, datetime.now(tz).date(), tz)
    fmt = "%Y-%m-%d %H:%M" if show_all else "%H:%M"
    for m in shown:
        sender = f"{m['sender']} — " if m["sender"] else ""
        print(f"{m['received_at'].astimezone(tz):{fmt}}  {sender}{m['subject']}")
    total = result["total"] if result["total"] is not None else "?"
    label = "inbox" if show_all else "from today"
    print(f"\n{len(shown)} shown ({label}); captured {len(messages)} of {total} inbox conversations.")
    if not result["messages"]:
        print("Nothing parsed. Outlook JSON endpoints seen (share these to adjust the parser):")
        for url in result["urls"]:
            print(f"  {url}")
    return 0


def main() -> None:
    load_dotenv()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # emoji subjects crash Windows' cp1252 when piped
    parser = argparse.ArgumentParser(prog="mailbrief", description="AI morning email digest for Outlook")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="sign in to Outlook once in a visible browser")
    run_p = sub.add_parser("run", help="headless: print today's inbox subjects")
    run_p.add_argument("--all", action="store_true", help="print every inbox conversation, not just today's")
    args = parser.parse_args()

    if args.command == "login":
        from mailbrief.session.login_once import login_once

        login_once()
        sys.exit(0)
    sys.exit(run(show_all=args.all))
