import argparse
import json
import os
import sys
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


def run(show_all: bool = False, as_json: bool = False, commit: bool = False) -> int:
    from playwright.sync_api import sync_playwright

    from mailbrief import cursor as cur
    from mailbrief.browser.connect import get_browser
    from mailbrief.browser.outlook_reader import fetch_emails, read_inbox
    from mailbrief.session import manager

    session = manager.load()
    if session is None:
        print("No saved session. Run `mailbrief login` first.")
        return 2

    cursor = cur.load()
    start = None if show_all else cur.since(cursor)
    with sync_playwright() as p:
        browser = get_browser(p, headless=True)
        try:
            context = browser.new_context(storage_state=session["state"], user_agent=session["user_agent"])
            page = context.new_page()
            result = read_inbox(page)
            if result["expired"]:
                print("Outlook session expired. Run `mailbrief login` again.")
                return 2
            # A conversation whose latest email predates the cursor has nothing new in it.
            convs = [c for c in result["messages"] if start is None or c["received_at"] >= start]
            records, full_text = fetch_emails(page, result["auth"], convs)
            manager.save(context, session["user_agent"])  # Microsoft rotates auth cookies
        finally:
            browser.close()

    emails = sorted(records if show_all else cur.select_new(records, cursor), key=lambda r: r["received_at"])
    tz = ZoneInfo(os.environ.get("DEFAULT_TIMEZONE", "Asia/Singapore"))
    # In --json mode stdout is pure JSON; everything else goes to stderr.
    log = sys.stderr if as_json else sys.stdout
    if as_json:
        json.dump(emails, sys.stdout, default=lambda o: o.isoformat(), ensure_ascii=False, indent=2)
        print()
    else:
        for e in emails:
            sender = e["sender_name"] or e["sender_email"]
            print(f"{e['received_at'].astimezone(tz):%Y-%m-%d %H:%M}  {sender} — {e['subject']}  ({len(e['body_text'])} chars)")

    total = result["total"] if result["total"] is not None else "?"
    scope = "all" if show_all else f"since {start.astimezone(tz):%Y-%m-%d %H:%M}"
    print(f"\n{len(emails)} emails ({scope}); inbox: captured {len(result['messages'])} of {total} conversations (Focused + Other).", file=log)
    if not full_text:
        print("Full text unavailable this run: emails show list previews only.", file=log)
    if not result["messages"]:
        print("Nothing parsed. Outlook JSON endpoints seen (share these to adjust the parser):", file=log)
        for url in result["urls"]:
            print(f"  {url}", file=log)

    if commit:
        try:
            cur.save(cur.advance(cursor, emails))
        except ValueError as e:
            print(f"Cursor not advanced: {e}", file=log)
            return 1
        print("Cursor advanced: these emails won't be listed again.", file=log)
    return 0


def main() -> None:
    load_dotenv()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # emoji subjects crash Windows' cp1252 when piped
    parser = argparse.ArgumentParser(prog="mailbrief", description="AI morning email digest for Outlook")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="sign in to Outlook once in a visible browser")
    run_p = sub.add_parser("run", help="headless: list emails received since the last committed run")
    run_p.add_argument("--all", action="store_true", help="every inbox email, ignoring the cursor")
    run_p.add_argument("--json", action="store_true", help="print full email records (with bodies) as JSON")
    run_p.add_argument("--commit", action="store_true", help="mark these emails processed (advance the cursor)")
    args = parser.parse_args()

    if args.command == "login":
        from mailbrief.session.login_once import login_once

        login_once()
        sys.exit(0)
    sys.exit(run(show_all=args.all, as_json=args.json, commit=args.commit))
