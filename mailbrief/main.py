import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

AI_THREADS = 4
BACKFILL_SAVE_EVERY = 25


def _tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("DEFAULT_TIMEZONE", "Asia/Singapore"))


def _needs_ai(stored: dict | None) -> bool:
    """True unless the archive already holds a real classification of this email's full text."""
    if not stored or stored.get("body_source") != "getitem":
        return True
    return (stored.get("classification") or {}).get("category") in (None, "Unclassified")


def run(show_all=False, as_json=False, commit=False, send=False, plain=False, backfill=False) -> int:
    from playwright.sync_api import sync_playwright

    from mailbrief import archive, threads
    from mailbrief import cursor as cur
    from mailbrief.ai.classifier import classify
    from mailbrief.ai.digest import digest
    from mailbrief.browser.connect import get_browser
    from mailbrief.browser.outlook_reader import fetch_emails, fetch_images, read_inbox
    from mailbrief.session import manager

    show_all = show_all or backfill
    session = manager.load()
    if session is None:
        print("No saved session. Run `mailbrief login` first.")
        return 2
    tz = _tz()
    log = sys.stderr if as_json else sys.stdout  # in --json mode stdout is pure JSON
    try:
        archived = {e["id"]: e for e in archive.load()[0]}
    except archive.ArchiveError as e:
        print(f"warning: {e}; continuing without reusing saved classifications", file=log)
        archived = {}

    cursor = cur.load()
    start = None if show_all else cur.since(cursor)
    t0 = time.time()
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
            records, full_text = fetch_emails(page, result["auth"], convs, result["me"])
            inbox = [r for r in records if r["in_inbox"] and not r["from_me"]]
            targets = sorted(inbox if show_all else cur.select_new(inbox, cursor), key=lambda r: r["received_at"])
            todo = [e for e in targets if _needs_ai(archived.get(e["id"]))]
            images = {e["id"]: fetch_images(page, result["auth"], e) for e in todo}  # memory only
            manager.save(context, session["user_agent"])  # Microsoft rotates auth cookies
        finally:
            browser.close()
    t_read = time.time() - t0

    total = result["total"] if result["total"] is not None else "?"
    scope = "all" if show_all else f"since {start.astimezone(tz):%Y-%m-%d %H:%M}"
    print(f"{len(targets)} inbox emails ({scope}), {len(todo)} need the AI, {len(targets) - len(todo)} already saved; "
          f"inbox: {len(result['messages'])} of {total} conversations; {len(records) - len(inbox)} of your replies / other-folder messages.", file=log)
    if show_all and isinstance(result["total"], int) and len(result["messages"]) < result["total"]:
        print(f"warning: Outlook only loaded {len(result['messages'])} of {result['total']} conversations this time; "
              "run it again to pick up the rest (saved emails are skipped)", file=log)
    if not result["me"]:
        print("warning: couldn't find your address in Outlook's startup data, so your replies aren't recognised", file=log)
    if not full_text:
        print("Full text unavailable this run: emails show list previews only.", file=log)
    if not result["messages"]:
        print("Nothing parsed. Outlook JSON endpoints seen (share these to adjust the parser):", file=log)
        for url in result["urls"]:
            print(f"  {url}", file=log)
    if not targets:
        return 0

    # Threads: earlier messages from the archive plus everything fetched now (fresh copies win).
    conv_ids = {r["conversation_id"] for r in records}
    pool = {e["id"]: e for e in archived.values() if e.get("conversation_id") in conv_ids}
    pool.update({r["id"]: r for r in records})
    for r in records:
        stored = archived.get(r["id"])
        if not r["in_inbox"] or r["from_me"]:
            r["classification"] = {"category": "Sent" if r["from_me"] else "Elsewhere"}  # context only, no AI
        elif stored and not _needs_ai(stored):
            r["classification"] = stored["classification"]  # never classify the same email twice
        else:
            r["classification"] = None
    thread_map = threads.group(list(pool.values()))
    for r in records:
        thread = thread_map[r.get("conversation_id") or r["id"]]
        r["replied"] = threads.replied(r, thread)
        r["thread_size"] = len(thread)

    # One worker per conversation, its emails oldest first, so a reply sees its parent's fresh summary.
    by_conv: dict[str, list[dict]] = {}
    todo_ids = {e["id"] for e in todo}
    for cid, thread in thread_map.items():
        mine = [m for m in thread if m["id"] in todo_ids]
        if mine:
            by_conv[cid] = mine

    def work(cid: str) -> list[dict]:
        for e in by_conv[cid]:
            try:
                e["classification"] = classify(e, images[e["id"]], threads.context_lines(e, thread_map[cid]))
            except Exception as ex:  # noqa: BLE001 - one bad call must not sink the run; retried next run
                print(f"warning: AI failed for one email ({type(ex).__name__}: {ex}); it will be retried next run", file=log)
                e["classification"] = {"category": "Unclassified", "priority": 3, "one_line_summary": e["subject"],
                                       "action_items": [], "deadline": None, "model": None}
        return by_conv[cid]

    t1 = time.time()
    done, pending = 0, []
    ordered = sorted(by_conv, key=lambda cid: by_conv[cid][0]["received_at"])  # oldest conversations first
    with ThreadPoolExecutor(AI_THREADS) as ex:
        for future in as_completed([ex.submit(work, cid) for cid in ordered]):
            batch = future.result()
            done += len(batch)
            pending += batch
            if backfill and len(pending) >= BACKFILL_SAVE_EVERY:  # Ctrl+C keeps everything saved so far
                archive.save(pending, [e["classification"] for e in pending], None, plain, tz)
                print(f"  classified {done}/{len(todo)} (saved)", file=log)
                pending = []
    t_classify = time.time() - t1

    t2 = time.time()
    results = [e["classification"] for e in targets]
    text = None if backfill else digest(targets, results)
    t_digest = time.time() - t2

    if as_json:
        json.dump(targets, sys.stdout, default=lambda o: o.isoformat(), ensure_ascii=False, indent=2)
        print()
    elif not backfill:
        for e in targets:
            c = e["classification"]
            done_tag = "  ✓ replied" if e["replied"] else ""
            print(f"  [{c['category']}/p{c.get('priority')}] {e['received_at'].astimezone(tz):%d %b %H:%M}  "
                  f"{e['sender_name'] or e['sender_email']} — {e['subject']}{done_tag}")
    if text:
        print(f"\n{text}\n", file=log)
    unclassified = sum(r["category"] == "Unclassified" for r in results)
    with_images = sum(bool(i) for i in images.values())
    print(f"timing: read {t_read:.0f}s, classify {t_classify:.0f}s ({len(todo)} emails, {with_images} with images)"
          + ("" if backfill else f", digest {t_digest:.0f}s") + (f"; {unclassified} unclassified" if unclassified else ""), file=log)

    try:  # saving is a convenience: a failure here must not lose the digest or block delivery
        archive.prune(datetime.now(tz).date())
        paths = archive.save(records, [r["classification"] for r in records], text, plain, tz)
        kind = "plain JSON" if plain else "encrypted"
        print(f"Saved ({kind}): {', '.join(p.name for p in paths)} in {archive.ARCHIVE_DIR}  (view with `mailbrief emails`)", file=log)
    except Exception as e:  # noqa: BLE001
        print(f"warning: archive not saved ({type(e).__name__}: {e})", file=log)

    # Nothing to deliver (no --send, or a backfill without a digest) counts as delivered.
    delivered = deliver(text, log) if send and text else True
    if commit or backfill:
        if not delivered:
            print("Cursor not advanced: the digest wasn't delivered anywhere.", file=log)
            return 1
        try:
            cur.save(cur.advance(cursor, targets))
        except ValueError as e:
            print(f"Cursor not advanced: {e}", file=log)
            return 1
        print("Cursor advanced: these emails won't be processed again.", file=log)
    return 0


def deliver(text: str, log) -> bool:
    """Send to every active destination; True if at least one got it. One failure never blocks the others."""
    from mailbrief import destinations
    from mailbrief.notify import ADAPTERS

    targets = [d for d in destinations.load() if d["active"]]
    if not targets:
        print("No destinations yet: run `mailbrief add-destination telegram`.", file=log)
        return False
    sent = 0
    for d in targets:
        try:
            ADAPTERS[d["type"]](d["target"], text)
            sent += 1
            print(f"Sent to {d['type']}: {d['label']}", file=log)
        except Exception as e:  # noqa: BLE001 - report and continue with the next destination
            print(f"Failed to send to {d['type']}: {d['label']} ({type(e).__name__}: {e})", file=log)
    return sent > 0


def _who(e: dict) -> str:
    return "You" if e.get("from_me") else (e.get("sender_name") or e.get("sender_email") or "?")


def _tag(e: dict) -> str:
    c = e.get("classification") or {}
    if c.get("category") in ("Sent", "Elsewhere"):
        return f"[{c['category'].lower()}]"
    return f"[{c.get('category', '?')}/p{c.get('priority', '?')}]"


def show_emails(period, day, search, show, thread, digest, export) -> int:
    """Browse the saved archive: threaded list by period/day/search, open one, a whole thread, digests, export."""
    from mailbrief import archive, threads

    tz = _tz()
    today = datetime.now(tz).date()
    try:
        all_emails, all_digests = archive.load()
        on_day = date.fromisoformat(day) if day else None
    except archive.ArchiveError as e:
        print(e)
        return 1
    except ValueError:
        print(f"--day must look like {today.isoformat()}")
        return 2

    if digest:
        want = on_day or today
        found = [d for d in all_digests if datetime.fromisoformat(d["at"]).astimezone(tz).date() == want]
        for d in found:
            print(f"── digest from {datetime.fromisoformat(d['at']).astimezone(tz):%d %b %H:%M} ──\n{d['text']}\n")
        if not found:
            print(f"No digest saved for {want}.")
        return 0

    emails = all_emails
    if on_day:
        emails = [e for e in emails if e["received_at"].astimezone(tz).date() == on_day]
    if period or not (on_day or search):
        name = period or "this-week"
        emails = [e for e in emails if archive.in_period(e, name, today, tz)]
    if search:
        needle = search.lower()
        emails = [e for e in emails if needle in " ".join(
            [e["sender_name"], e["sender_email"], e["subject"], e["body_text"]]).lower()]

    # Threaded list: conversations by latest activity; inside, logical (ConversationIndex) order.
    grouped = sorted(threads.group(emails).values(), key=lambda t: max(m["received_at"] for m in t), reverse=True)
    listing = [m for t in grouped for m in t]

    if export:
        out = [{**e, "received_at": e["received_at"].isoformat()} for e in listing]
        Path(export).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Exported {len(out)} emails to {export} (plain, unencrypted).")
        return 0

    pick = show or thread
    if pick is not None:
        if not 1 <= pick <= len(listing):
            print(f"No email #{pick}; this list has {len(listing)}.")
            return 1
        e = listing[pick - 1]
        full_thread = threads.group(all_emails)[e.get("conversation_id") or e["id"]]
        if thread:
            for m in full_thread:
                print(f"{'═' * 70}\n{'  ' * threads.depth(m)}{m['received_at'].astimezone(tz):%a %d %b %H:%M}  "
                      f"{_who(m)} — {m['subject']}  {_tag(m)}\n{'═' * 70}\n{m['body_text']}\n")
            return 0
        c = e.get("classification") or {}
        print(f"From:     {e['sender_name']} <{e['sender_email']}>")
        print(f"Subject:  {e['subject']}")
        print(f"Received: {e['received_at'].astimezone(tz):%a %d %b %Y %H:%M}")
        if e["attachment_names"]:
            print(f"Attached: {', '.join(e['attachment_names'])}")
        print(f"AI:       {c.get('category')} / priority {c.get('priority')} ({c.get('model')})"
              + ("   ✓ you replied" if e.get("replied") else ""))
        if c.get("one_line_summary"):
            print(f"Summary:  {c['one_line_summary']}")
        for item in c.get("action_items") or []:
            print(f"  • {item}")
        if c.get("deadline"):
            print(f"Deadline: {c['deadline']}")
        if len(full_thread) > 1:
            print(f"\nThread ({len(full_thread)} messages; open all with --thread {pick}):")
            for m in full_thread:
                mark = "▶" if m["id"] == e["id"] else " "
                print(f"  {mark} {'  ' * threads.depth(m)}{m['received_at'].astimezone(tz):%d %b %H:%M}  {_who(m)} — {m['subject']}")
        print(f"\n{e['body_text']}")
        return 0

    if not listing:
        print("No saved emails here. Emails are saved by `mailbrief run` (whole inbox: `mailbrief run --backfill`).")
    for n, m in enumerate(listing, 1):
        depth = threads.depth(m)
        arrow = "   " * depth + ("↳ " if depth else "")
        done_tag = "   ✓ replied" if m.get("replied") else ""
        print(f"{n:4}  {m['received_at'].astimezone(tz):%d %b %H:%M}  {_tag(m):20} {arrow}{_who(m)} — {m['subject']}{done_tag}")
    inbox_emails = [e for e in all_emails if (e.get("classification") or {}).get("category") not in ("Sent", "Elsewhere")]
    counts = " · ".join(f"{p.replace('-', ' ')} {sum(archive.in_period(e, p, today, tz) for e in inbox_emails)}"
                        for p in archive.PERIODS)
    print(f"\n{len(listing)} shown. ── {counts} ──  (--period NAME, --show N, --thread N)")
    return 0


def add_destination(type_: str, chat_id: str | None) -> int:
    from mailbrief import destinations
    from mailbrief.notify import telegram

    if type_ != "telegram":
        print(f"Unknown destination type: {type_}")
        return 2
    if chat_id:
        destinations.add("telegram", chat_id, chat_id)
        print(f"Added Telegram chat {chat_id}.")
        return 0
    chats = telegram.find_chats()
    if not chats:
        print("No chats found. Send your bot a message in Telegram first, then run this again.")
        return 1
    for n, c in enumerate(chats, 1):
        print(f"  {n}. {c['label']}  (chat id {c['id']})")
    choice = input("Add which chat? number: ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(chats):
        print("Nothing added.")
        return 1
    chat = chats[int(choice) - 1]
    destinations.add("telegram", chat["id"], chat["label"])
    telegram.send(chat["id"], "✅ MailBrief will send your morning digest here.")
    print(f"Added {chat['label']} and sent a test message.")
    return 0


def main() -> None:
    load_dotenv()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # emoji subjects crash Windows' cp1252 when piped
    parser = argparse.ArgumentParser(prog="mailbrief", description="AI morning email digest for Outlook")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="sign in to Outlook once in a visible browser")
    run_p = sub.add_parser("run", help="headless: classify new emails and print the digest")
    run_p.add_argument("--all", action="store_true", help="every inbox email, ignoring the cursor")
    run_p.add_argument("--backfill", action="store_true",
                       help="save the whole inbox to the archive: no digest, skips saved emails, resumable")
    run_p.add_argument("--json", action="store_true", help="print email records with classifications as JSON")
    run_p.add_argument("--send", action="store_true", help="send the digest to all destinations")
    run_p.add_argument("--commit", action="store_true", help="mark these emails processed (advance the cursor)")
    run_p.add_argument("--no-password", action="store_true", help="save the archive as plain JSON instead of encrypted")
    em_p = sub.add_parser("emails", help="browse saved emails (this week by default), grouped by thread")
    em_p.add_argument("--period", choices=["this-week", "this-month", "last-month", "older"])
    em_p.add_argument("--day", help="one day, e.g. 2026-10-16")
    em_p.add_argument("--search", help="text to find in sender, subject or body (all periods)")
    em_p.add_argument("--show", type=int, metavar="N", help="open email #N from the list, with its thread outline")
    em_p.add_argument("--thread", type=int, metavar="N", help="print the whole conversation of email #N")
    em_p.add_argument("--digest", action="store_true", help="show the saved digest(s) for --day (default today)")
    em_p.add_argument("--export", metavar="FILE", help="write the listed emails to FILE as plain JSON")
    dest_p = sub.add_parser("add-destination", help="add where digests are sent (local setup only)")
    dest_p.add_argument("type", choices=["telegram"])
    dest_p.add_argument("--chat-id", help="skip the lookup and add this chat id directly")
    args = parser.parse_args()

    if args.command == "login":
        from mailbrief.session.login_once import login_once

        login_once()
        sys.exit(0)
    if args.command == "add-destination":
        sys.exit(add_destination(args.type, args.chat_id))
    if args.command == "emails":
        sys.exit(show_emails(args.period, args.day, args.search, args.show, args.thread, args.digest, args.export))
    sys.exit(run(show_all=args.all, as_json=args.json, commit=args.commit, send=args.send,
                 plain=args.no_password, backfill=args.backfill))
