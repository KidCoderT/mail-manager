import argparse
import functools
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
    return (stored.get("classification") or {}).get("category") in (
        None,
        "Unclassified",
    )


def run(
    show_all=False,
    as_json=False,
    commit=False,
    send=False,
    plain=False,
    backfill=False,
    digest_scope=None,
    quiet=False,
) -> int:
    from playwright.sync_api import sync_playwright

    from mailbrief import archive, progress, threads
    from mailbrief import cursor as cur
    from mailbrief.ai.classifier import classify
    from mailbrief import links
    from mailbrief.ai.digest import digest
    from mailbrief.ai.digest import refs as digest_refs
    from mailbrief.browser.connect import get_browser
    from mailbrief.browser.outlook_reader import collect_images, fetch_emails, read_inbox
    from mailbrief.session import manager

    show_all = show_all or backfill
    # The morning digest by default; a backfill writes none unless a scope is asked for explicitly.
    scope = digest_scope or (None if backfill else "new")
    session = manager.load()
    if session is None:
        print("No saved session. Run `mailbrief login` first.")
        return 2
    tz = _tz()
    log = sys.stderr if as_json else sys.stdout  # in --json mode stdout is pure JSON
    progress.step("Loading saved emails…")
    try:
        archived = {e["id"]: e for e in archive.load()[0]}
    except archive.ArchiveError as e:
        print(
            f"warning: {e}; continuing without reusing saved classifications", file=log
        )
        archived = {}

    from mailbrief import rules

    try:
        your_rules = rules.load()
    except rules.RulesError as e:  # a typo in rules.json must not stop the digest
        print(f"warning: {e}; using no rules this run (fix data/rules.json)", file=log)
        your_rules = rules.empty()

    cursor = cur.load()
    start = None if show_all else cur.since(cursor)
    t0 = time.time()
    with sync_playwright() as p:
        browser = get_browser(p, headless=True)
        try:
            context = browser.new_context(
                storage_state=session["state"], user_agent=session["user_agent"]
            )
            page = context.new_page()
            result = read_inbox(page)
            if result["expired"]:
                print("Outlook session expired. Run `mailbrief login` again.")
                return 2
            # A conversation whose latest email predates the cursor has nothing new in it.
            convs = [
                c
                for c in result["messages"]
                if start is None or c["received_at"] >= start
            ]
            records, full_text = fetch_emails(page, result["auth"], convs, result["me"])
            inbox = [r for r in records if r["in_inbox"] and not r["from_me"]]
            targets = sorted(
                inbox if show_all else cur.select_new(inbox, cursor),
                key=lambda r: r["received_at"],
            )
            todo = [e for e in targets if _needs_ai(archived.get(e["id"]))]
            images = collect_images(page, result["auth"], todo)  # memory only
            with_images = [e for e in todo if images[e["id"]]]
            manager.save(
                context, session["user_agent"]
            )  # Microsoft rotates auth cookies
        finally:
            browser.close()
    t_read = time.time() - t0

    total = result["total"] if result["total"] is not None else "?"
    window = "all" if show_all else f"since {start.astimezone(tz):%Y-%m-%d %H:%M}"
    print(
        f"{len(targets)} inbox emails ({window}), {len(todo)} need the AI, {len(targets) - len(todo)} already saved; "
        f"inbox: {len(result['messages'])} of {total} conversations; {len(records) - len(inbox)} of your replies / other-folder messages.",
        file=log,
    )
    if (
        show_all
        and isinstance(result["total"], int)
        and len(result["messages"]) < result["total"]
    ):
        print(
            f"warning: Outlook only loaded {len(result['messages'])} of {result['total']} conversations this time; "
            "run it again to pick up the rest (saved emails are skipped)",
            file=log,
        )
    if not result["me"]:
        print(
            "warning: couldn't find your address in Outlook's startup data, so your replies aren't recognised",
            file=log,
        )
    if not full_text:
        print(
            "Full text unavailable this run: emails show list previews only.", file=log
        )
    if not result["messages"]:
        print(
            "Nothing parsed. Outlook JSON endpoints seen (share these to adjust the parser):",
            file=log,
        )
        for url in result["urls"]:
            print(f"  {url}", file=log)
    if not targets and scope in (None, "new"):
        print("No new emails, so no digest.", file=log)
        from mailbrief import labels

        labels.run_step(log)  # labels still pending from earlier runs
        return 0

    # Threads: earlier messages from the archive plus everything fetched now (fresh copies win).
    conv_ids = {r["conversation_id"] for r in records}
    pool = {
        e["id"]: e for e in archived.values() if e.get("conversation_id") in conv_ids
    }
    pool.update({r["id"]: r for r in records})
    for r in records:
        stored = archived.get(r["id"])
        if not r["in_inbox"] or r["from_me"]:
            r["classification"] = {
                "category": "Sent" if r["from_me"] else "Elsewhere"
            }  # context only, no AI
        elif stored and not _needs_ai(stored):
            r["classification"] = stored[
                "classification"
            ]  # never classify the same email twice
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
                e["classification"] = classify(
                    e,
                    images[e["id"]],
                    threads.context_lines(e, thread_map[cid]),
                    your_rules,
                )
            except Exception as ex:  # noqa: BLE001 - one bad call must not sink the run; retried next run
                print(
                    f"warning: AI failed for one email ({type(ex).__name__}: {ex}); it will be retried next run",
                    file=log,
                )
                e["classification"] = {
                    "category": "Unclassified",
                    "priority": 3,
                    "one_line_summary": e["subject"],
                    "action_items": [],
                    "deadline": None,
                    "events": [],
                    "model": None,
                }
        return by_conv[cid]

    t1 = time.time()
    done, pending = 0, []
    ordered = sorted(
        by_conv, key=lambda cid: by_conv[cid][0]["received_at"]
    )  # oldest conversations first
    if todo:
        progress.step(f"Classifying {len(todo)} emails with the AI…")
    with ThreadPoolExecutor(AI_THREADS) as ex:
        for future in as_completed([ex.submit(work, cid) for cid in ordered]):
            batch = future.result()
            done += len(batch)
            pending += batch
            progress.count("Classifying", done, len(todo))
            if (
                backfill and len(pending) >= BACKFILL_SAVE_EVERY
            ):  # Ctrl+C keeps everything saved so far
                archive.save(
                    pending, [e["classification"] for e in pending], None, plain, tz
                )
                pending = []
    t_classify = time.time() - t1

    # Save before the digest: a period digest reads this run's emails back from the archive.
    try:  # saving is a convenience: a failure here must not lose the digest or block delivery
        progress.step("Saving to the archive…")
        archive.prune(datetime.now(tz).date())
        paths = archive.save(
            records, [r["classification"] for r in records], None, plain, tz
        )
        kind = "plain JSON" if plain else "encrypted"
        names = ", ".join(p.name for p in paths) or "nothing new"
        saved_msg = f"Saved ({kind}): {names} in {archive.ARCHIVE_DIR}  (view with `mailbrief emails`)"
    except Exception as e:  # noqa: BLE001
        saved_msg = f"warning: archive not saved ({type(e).__name__}: {e})"
    else:
        from mailbrief import labels

        labels.run_step(
            log
        )  # MB: labels in Outlook for whatever is pending; never fails the run
        from mailbrief import index

        progress.step("Updating the search index…")
        added, _ = index.update(archive.load()[0], log)  # new mail becomes searchable in chat; never fails the run
        if added:
            print(f"Search index: {added} email(s) added", file=log)

    text, t_digest, digest_emails = None, 0.0, []
    if scope:
        digest_emails = digest_set(scope, targets, cursor, tz, log)
        if digest_emails:
            t2 = time.time()
            parts = (len(digest_emails) + 24) // 25 if len(digest_emails) > 40 else 1
            label = f"Writing the {scope.replace('-', ' ')} digest of {len(digest_emails)} emails"
            with progress.working(
                label + (f" in {parts} parts" if parts > 1 else "")
            ) as w:
                text = digest(
                    digest_emails,
                    [e["classification"] for e in digest_emails],
                    scope,
                    on_part=w.note,
                    your_rules=your_rules,
                )
            t_digest = time.time() - t2
            try:
                archive.save([], [], text, plain, tz, digest_scope=scope, digest_refs=digest_refs(digest_emails))
            except Exception as e:  # noqa: BLE001
                saved_msg += f"; warning: digest not saved ({type(e).__name__}: {e})"

    results = [e["classification"] for e in targets]
    if as_json:
        json.dump(
            targets,
            sys.stdout,
            default=lambda o: o.isoformat(),
            ensure_ascii=False,
            indent=2,
        )
        print()
    elif (
        not backfill and not quiet
    ):  # quiet (scheduled runs): logs never hold mail content
        for e in targets:
            c = e["classification"]
            done_tag = "  ✓ replied" if e["replied"] else ""
            print(
                f"  [{c['category']}/p{c.get('priority')}] {e['received_at'].astimezone(tz):%d %b %H:%M}  "
                f"{e['sender_name'] or e['sender_email']} — {e['subject']}{done_tag}"
            )
    # The UPCOMING EVENTS calendar goes with every digest: built by code from the saved archive (no AI).
    from mailbrief import events

    new_ids = [e["id"] for e in digest_emails]
    events_text = events.build(datetime.now(tz).date(), new_ids, log) if text else None
    if text and not quiet:
        print(f"\n{links.plain(text)}\n", file=log)
        if events_text:
            print(f"{events_text}\n", file=log)
    unclassified = sum(r["category"] == "Unclassified" for r in results)
    print(
        f"timing: read {t_read:.0f}s, classify {t_classify:.0f}s ({len(todo)} emails, {len(with_images)} with images)"
        + (f", digest {t_digest:.0f}s" if text else "")
        + (f"; {unclassified} unclassified" if unclassified else ""),
        file=log,
    )
    print(saved_msg, file=log)

    # Nothing to deliver (no --send, or no digest this run) counts as delivered.
    if send and text:
        progress.step("Sending the digest…")
    # Telegram gets HTML: every bullet and event ends with ↗ links to its emails in Outlook.
    delivered = deliver(links.to_html(text, digest_refs(digest_emails)), log, html=True) if send and text else True
    if send and text and delivered and events_text:
        events_html = events.build(datetime.now(tz).date(), new_ids, log, html=True)
        deliver(events_html, log, html=True)  # a failure is reported, but never holds back the cursor
    if commit or backfill:
        if not delivered:
            print(
                "Cursor not advanced: the digest wasn't delivered anywhere.", file=log
            )
            return 1
        try:
            cur.save(cur.advance(cursor, targets))
        except ValueError as e:  # previews only: the digest went out, but these emails must be read again
            print(f"Cursor not advanced: {e}", file=log)
            return 4  # not 1: rerunning would send the same digest again (serve retries 1, not 4)
        print("Cursor advanced: these emails won't be processed again.", file=log)
    return 0


def digest_set(scope: str, targets: list[dict], cursor: dict, tz, log) -> list[dict]:
    """The emails a digest of `scope` covers: new since the cursor, or an archive period ("all" = everything)."""
    from mailbrief import archive
    from mailbrief import cursor as cur

    if scope == "new":
        emails = cur.select_new(
            targets, cursor
        )  # with --all, targets is the whole inbox; the digest stays on new mail
    else:
        today = datetime.now(tz).date()
        emails = [
            e
            for e in archive.load()[0]
            if scope == "all" or archive.in_period(e, scope, today, tz)
        ]
        emails.sort(key=lambda e: e["received_at"])
    # Only incoming mail with a real classification: not your sent replies or other-folder copies.
    emails = [
        e
        for e in emails
        if (e.get("classification") or {}).get("category")
        not in (None, "Sent", "Elsewhere")
    ]
    if not emails:
        print(f"No emails for a {scope!r} digest.", file=log)
    return emails


def deliver(text: str, log, html: bool = False) -> bool:
    """Send to every active destination; True if at least one got it. One failure never blocks the others.
    html=True: `text` is Telegram HTML (↗ links to the emails, see links.py)."""
    from mailbrief import destinations
    from mailbrief.notify import ADAPTERS

    targets = [d for d in destinations.load() if d["active"]]
    if not targets:
        print(
            "No destinations yet: run `mailbrief add-destination telegram`.", file=log
        )
        return False
    sent = 0
    for d in targets:
        try:
            n = ADAPTERS[d["type"]](d["target"], text, html=html)
            sent += 1
            print(
                f"Sent to {d['type']}: {d['label']} ({n} message{'s' if n != 1 else ''})",
                file=log,
            )
        except Exception as e:  # noqa: BLE001 - report and continue with the next destination
            print(
                f"Failed to send to {d['type']}: {d['label']} ({type(e).__name__}: {e})",
                file=log,
            )
    return sent > 0


def _who(e: dict) -> str:
    return (
        "You"
        if e.get("from_me")
        else (e.get("sender_name") or e.get("sender_email") or "?")
    )


def _tag(e: dict) -> str:
    c = e.get("classification") or {}
    if c.get("category") in ("Sent", "Elsewhere"):
        return f"[{c['category'].lower()}]"
    return f"[{c.get('category', '?')}/p{c.get('priority', '?')}]"


def show_emails(period, day, search, show, thread, digest, export, send=False) -> int:
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
        from mailbrief import links

        want = on_day or today
        found = [
            d
            for d in all_digests
            if datetime.fromisoformat(d["at"]).astimezone(tz).date() == want
        ]
        for d in found:
            scope = d.get("scope", "new").replace("-", " ")
            print(
                f"── {scope} digest, written {datetime.fromisoformat(d['at']).astimezone(tz):%d %b %H:%M} ──\n"
                f"{links.plain(d['text'])}\n"
            )
        if not found:
            print(f"No digest saved for {want}.")
            return 1 if send else 0
        if send:  # resend the latest one, then today's events calendar: no Outlook, no AI
            from mailbrief import events, links

            last = found[-1]  # digests saved before M7 have no refs: they go out without links
            if not deliver(links.to_html(last["text"], last.get("refs") or {}), sys.stdout, html=True):
                return 1
            events_html = events.build(today, (), sys.stdout, html=True)
            if events_html:
                deliver(events_html, sys.stdout, html=True)
            return 0
        return 0

    emails = all_emails
    if on_day:
        emails = [e for e in emails if e["received_at"].astimezone(tz).date() == on_day]
    if period or not (on_day or search):
        name = period or "this-week"
        emails = [e for e in emails if archive.in_period(e, name, today, tz)]
    if search:
        needle = search.lower()
        emails = [
            e
            for e in emails
            if needle
            in " ".join(
                [e["sender_name"], e["sender_email"], e["subject"], e["body_text"]]
            ).lower()
        ]

    # Threaded list: conversations by latest activity; inside, logical (ConversationIndex) order.
    grouped = sorted(
        threads.group(emails).values(),
        key=lambda t: max(m["received_at"] for m in t),
        reverse=True,
    )
    listing = [m for t in grouped for m in t]

    if export:
        out = [{**e, "received_at": e["received_at"].isoformat()} for e in listing]
        Path(export).write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
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
                print(
                    f"{'═' * 70}\n{'  ' * threads.depth(m)}{m['received_at'].astimezone(tz):%a %d %b %H:%M}  "
                    f"{_who(m)} — {m['subject']}  {_tag(m)}\n{'═' * 70}\n{m['body_text']}\n"
                )
            return 0
        c = e.get("classification") or {}
        print(f"From:     {e['sender_name']} <{e['sender_email']}>")
        print(f"Subject:  {e['subject']}")
        print(f"Received: {e['received_at'].astimezone(tz):%a %d %b %Y %H:%M}")
        if e.get("to"):
            print(
                f"To:       {', '.join(e['to'])}"
                + ("   (only you)" if e.get("direct") else "")
            )
        if e["attachment_names"]:
            print(f"Attached: {', '.join(e['attachment_names'])}")
        print(
            f"AI:       {c.get('category')} / priority {c.get('priority')} ({c.get('model')})"
            + ("   ✓ you replied" if e.get("replied") else "")
        )
        try:
            from mailbrief import rules

            eff = rules.effective(e, rules.load())
            if eff["labels"]:
                print(
                    f"Yours:    {', '.join(n[4:] for n in eff['labels'])}"
                    + ("   ⭐ boosted" if eff["boosted"] else "")
                    + (
                        f"   (priority raised to {eff['priority']})"
                        if eff["priority"] != c.get("priority")
                        else ""
                    )
                )
        except rules.RulesError:
            pass
        if c.get("one_line_summary"):
            print(f"Summary:  {c['one_line_summary']}")
        for item in c.get("action_items") or []:
            print(f"  • {item}")
        if c.get("deadline"):
            print(f"Deadline: {c['deadline']}")
        for ev in c.get("events") or []:
            when = " ".join(x for x in (ev.get("date"), ev.get("time")) if x) or "date not given"
            print(f"Event:    {when} · {ev['name']}" + (f" · {ev['place']}" if ev.get("place") else ""))
            if ev.get("detail"):
                print(f"          {ev['detail']}")
        if len(full_thread) > 1:
            print(
                f"\nThread ({len(full_thread)} messages; open all with --thread {pick}):"
            )
            for m in full_thread:
                mark = "▶" if m["id"] == e["id"] else " "
                print(
                    f"  {mark} {'  ' * threads.depth(m)}{m['received_at'].astimezone(tz):%d %b %H:%M}  {_who(m)} — {m['subject']}"
                )
        print(f"\n{e['body_text']}")
        return 0

    if not listing:
        print(
            "No saved emails here. Emails are saved by `mailbrief run` (whole inbox: `mailbrief run --backfill`)."
        )
    for n, m in enumerate(listing, 1):
        depth = threads.depth(m)
        arrow = "   " * depth + ("↳ " if depth else "")
        done_tag = "   ✓ replied" if m.get("replied") else ""
        print(
            f"{n:4}  {m['received_at'].astimezone(tz):%d %b %H:%M}  {_tag(m):20} {arrow}{_who(m)} — {m['subject']}{done_tag}"
        )
    inbox_emails = [
        e
        for e in all_emails
        if (e.get("classification") or {}).get("category") not in ("Sent", "Elsewhere")
    ]
    counts = " · ".join(
        f"{p.replace('-', ' ')} {sum(archive.in_period(e, p, today, tz) for e in inbox_emails)}"
        for p in archive.PERIODS
    )
    print(
        f"\n{len(listing)} shown. ── {counts} ──  (--period NAME, --show N, --thread N)"
    )
    return 0


def labels_command(args) -> int:
    """`mailbrief labels status|apply|clear`: MailBrief's MB: categories in Outlook."""
    from mailbrief import archive, labels, rules

    tz = _tz()
    today = datetime.now(tz).date()
    try:
        emails = archive.load()[0]
        rules.load()
    except (archive.ArchiveError, rules.RulesError) as e:
        print(e)
        return 1

    if args.action == "clear" and args.label:
        return _clear_label(args, emails, today, tz)
    if args.action == "retag":
        return _retag(args, emails, today, tz)

    if args.action == "status":
        print(
            f"Outlook labels: {'on' if labels.enabled() else 'off (OUTLOOK_LABELS=off)'}"
        )
        print(f"{'':12} {'labelled':>9} {'pending':>8} {'cleared':>8}")
        for name in archive.PERIODS:
            group = [e for e in emails if archive.in_period(e, name, today, tz)]
            print(
                f"{name:12} {len(labels.labelled(group)):9} {len(labels.pending(group)):8} "
                f"{sum(bool(e.get('labels_cleared')) for e in group):8}"
            )
        print(
            f"{'all':12} {len(labels.labelled(emails)):9} {len(labels.pending(emails)):8} "
            f"{sum(bool(e.get('labels_cleared')) for e in emails):8}"
        )
        return 0

    if args.action == "clear" and args.everywhere:
        print("--everywhere works with --label NAME.")
        return 2
    if args.action == "clear" and not (args.period or args.days or args.all):
        print("Say what to clear: --period this-month | --days 30 | --all")
        return 2
    chosen = labels.select(emails, args.period, args.days, today, tz)
    if args.action == "apply":
        targets = labels.pending(chosen, include_cleared=True)[: args.limit or None]
        verb = "Label"
    else:
        targets = labels.labelled(chosen)[: args.limit or None]
        verb = "Remove MailBrief labels from"
    print(
        f"{verb} {len(targets)} email(s)"
        + (
            " and delete the MB: categories from your list"
            if getattr(args, "colours", False)
            else ""
        )
        + "."
    )
    if args.dry_run or len(targets) <= 5:
        for e in targets[:20]:
            shown = (
                labels.labels_for(e)
                if args.action == "apply"
                else e.get("outlook_labels")
            )
            print(
                f"  {e['received_at'].astimezone(tz):%d %b %H:%M}  {', '.join(shown)}  {e['subject'][:60]}"
            )
    if args.dry_run:
        print("Dry run: Outlook not touched.")
        return 0
    if not targets and not getattr(args, "colours", False):
        print("Nothing to do.")
        return 0
    if args.action == "clear" and not _confirm(args.yes):
        return 1
    code = _locked(
        lambda: (
            labels.apply(targets)
            if args.action == "apply"
            else labels.clear(targets, args.colours)
        )
    )
    if code:
        return code
    if args.action == "clear" and args.all and labels.enabled():
        print(
            "New emails will still be labelled. To stop that too, put OUTLOOK_LABELS=off in .env."
        )
    return 0


def _confirm(yes: bool, question: str = "Go ahead?") -> bool:
    if yes:
        return True
    try:
        answer = input(f"{question} [y/N] ") if sys.stdin.isatty() else ""
    except EOFError:  # no keyboard (piped, scheduled): never assume yes
        answer = ""
    if answer.strip().lower() != "y":
        print("\nNothing changed (answer y, or add --yes).")
        return False
    return True


def _locked(action) -> int:
    """Run an Outlook action under the run lock, turning the usual failures into exit codes."""
    from mailbrief import labels
    from mailbrief.service import Busy, lock

    try:
        with lock("run"):  # never at the same time as a run
            print(action())
    except Busy:
        print("A MailBrief run is in progress; try again when it finishes.")
        return 3
    except labels.LoginNeeded as e:
        print(f"Can't open Outlook: {e}")
        return 2
    return 0


def _clear_label(args, emails: list[dict], today, tz) -> int:
    """`labels clear --label NAME [--everywhere]`: take one of your own labels off, after asking."""
    from mailbrief import labels, rules

    name = args.label if args.label.startswith("MB: ") else f"MB: {args.label}"
    if not labels.is_custom(name):
        print(
            f"{name} is a built-in label; use `labels clear --period/--days/--all` for those."
        )
        return 2
    if name in rules.rule_labels(rules.load()):
        print(
            f"Your rules still give {name}, so the next run would put it back. "
            f"Remove the rule first (`mailbrief rules remove …`), then clear the label."
        )
        return 2
    # --everywhere strips it from the whole mailbox, so the archive must forget it on every email, not a slice.
    chosen = (
        emails
        if args.everywhere
        else labels.select(emails, args.period, args.days, today, tz)
    )
    targets = [e for e in chosen if name in (e.get("outlook_labels") or [])][
        : None if args.everywhere else args.limit or None
    ]
    if args.everywhere:
        print(
            f"Remove {name} from EVERY email in your mailbox (also ones MailBrief never labelled) "
            f"and delete it from your category list. MailBrief had put it on {len(targets)} email(s)."
        )
    else:
        print(f"Remove {name} from {len(targets)} email(s) MailBrief labelled.")
    for e in targets[:20]:
        print(f"  {e['received_at'].astimezone(tz):%d %b %H:%M}  {e['subject'][:70]}")
    if args.dry_run:
        print("Dry run: Outlook not touched.")
        return 0
    if not targets and not args.everywhere:
        print("Nothing to do.")
        return 0
    if not _confirm(args.yes):
        return 1
    return _locked(lambda: labels.remove_label(targets, name, args.everywhere))


def _retag(args, emails: list[dict], today, tz) -> int:
    """`labels retag`: ask the AI again about saved emails with your current profile and topics."""
    from mailbrief import archive, labels, progress, rules, threads
    from mailbrief.ai.classifier import classify

    if not (args.period or args.days):
        print("Say which emails: --period this-month | --days 30")
        return 2
    your_rules = rules.load()
    targets = [
        e
        for e in labels.select(emails, args.period, args.days, today, tz)
        if (e.get("classification") or {}).get("category")
        not in (None, "Sent", "Elsewhere")
        and e.get("body_source") == "getitem"
    ][: args.limit or None]
    print(
        f"Ask the AI again about {len(targets)} email(s) (about one call each) with your current profile and "
        f"{len(your_rules['topics'])} topic(s)."
    )
    if args.dry_run or not targets:
        print("Dry run: nothing changed." if args.dry_run else "Nothing to do.")
        return 0
    if not _confirm(args.yes):
        return 1

    def work() -> str:
        from mailbrief import web_images

        images = {e["id"]: [] for e in targets}
        # Images are never saved, so they're fetched again; linked ones need the HTML from Outlook too.
        if web_images.enabled() or any(e.get("image_attachments") for e in targets):
            from mailbrief.browser.outlook_reader import collect_images

            with labels.outlook() as (page, auth, _startup):
                images = collect_images(page, auth, targets)
        thread_map = threads.group(emails)
        changes, done = {}, 0

        def one(e: dict) -> None:
            c = classify(
                e,
                images[e["id"]],
                threads.context_lines(
                    e, thread_map[e.get("conversation_id") or e["id"]]
                ),
                your_rules,
            )
            if (
                c["category"] != "Unclassified"
            ):  # a failed call keeps the old classification
                changes[e["id"]] = {"classification": c}

        with ThreadPoolExecutor(AI_THREADS) as ex:
            for _ in as_completed([ex.submit(one, e) for e in targets]):
                done += 1
                progress.count("Re-tagging", done, len(targets))
        archive.update_fields(changes)
        labels.run_step(sys.stdout)  # Outlook catches up straight away
        from mailbrief import index

        index.update(archive.load()[0], sys.stdout)  # new events / summaries become searchable
        return f"Re-tagged {len(changes)} of {len(targets)} email(s)."

    return _locked(work)


def rules_command(args, out=None) -> int:
    """`mailbrief rules list|add|remove|profile`: your own labels in data/rules.json."""
    say = functools.partial(print, file=out or sys.stdout)  # out: the chat bot's reply buffer
    from mailbrief import archive, rules

    try:
        current = rules.load()
    except rules.RulesError as e:
        say(f"{e}\nFix {rules.RULES_PATH} by hand (it's plain JSON).")
        return 1
    try:
        emails = archive.load()[0]
    except archive.ArchiveError:
        emails = []

    def count(label: str) -> int:
        return sum(
            any(m[0] == label for m in rules.matches(e, current)) for e in emails
        )

    if args.action == "list":
        say(
            f"Rules in {rules.RULES_PATH}"
            + ("" if rules.RULES_PATH.exists() else " (none yet)")
        )
        say(f"Profile: {current['profile'] or '(none)'}")
        for kind in rules.KINDS:
            say(f"\n{kind.capitalize()}:")
            for r in current[kind]:
                label = rules.label_name(kind, r)
                extra = [
                    f"priority ≥ P{r['priority']}" if r.get("priority") else "",
                    "direct only" if r.get("direct_only") else "",
                    "boost" if r.get("boost") else "",
                    f"match {r['match']!r}" if kind == "senders" else "",
                    f"“{r['description']}”" if kind == "topics" else "",
                ]
                say(
                    f"  {label:24} {count(label):4} saved emails   {' · '.join(x for x in extra if x)}"
                )
            if not current[kind]:
                say("  (none)")
        return 0

    if args.action == "profile":
        new = {**current, "profile": args.text}
        msg = f"Profile set: {args.text}" if args.text.strip() else "Profile cleared."
        tail = "It shapes priorities for new mail; `labels retag --period this-month` re-asks for older mail."
    elif args.action == "add":
        kind = {"course": "courses", "sender": "senders", "topic": "topics"}[args.kind]
        rule = {
            "courses": {
                "code": args.key,
                "priority": args.priority,
                "boost": args.boost,
            },
            "senders": {
                "match": args.key,
                "label": args.label,
                "direct_only": args.direct,
                "priority": args.priority,
                "boost": args.boost,
            },
            "topics": {
                "name": args.key,
                "description": args.description,
                "priority": args.priority,
            },
        }[kind]
        if kind == "senders" and not args.label:
            say('A sender needs --label, e.g. --label "Prof Tan".')
            return 2
        if kind == "topics" and not args.description:
            say(
                'A topic needs a description, e.g. rules add topic Networking "career fairs, meetups, hackathons".'
            )
            return 2
        try:
            new = rules.add(current, kind, rule)
        except rules.RulesError as e:
            say(e)
            return 2
        label = rules.label_name(kind, new[kind][-1])
        msg = f"✅ Added {label}."
        if kind == "topics":
            tail = "The AI tags new mail with it; `labels retag --period this-month` does older mail."
        else:
            n = sum(any(m[0] == label for m in rules.matches(e, new)) for e in emails)
            tail = f"{n} saved emails match; Outlook gets the label on the next run (or `labels apply`)."
    else:  # remove
        kind = {"course": "courses", "sender": "senders", "topic": "topics"}[args.kind]
        new, gone = rules.remove(current, kind, args.key)
        if gone is None:
            say(
                f"No {args.kind} {args.key!r} in your rules (see `mailbrief rules list`)."
            )
            return 1
        label = rules.label_name(kind, gone)
        msg = f"Removed {label}."
        tail = f'Emails already labelled keep it; remove it with `mailbrief labels clear --label "{label[4:]}"`.'
    try:
        rules.save(new)
    except rules.RulesError as e:
        say(e)
        return 2
    say(f"{msg}\n{tail}")
    return 0


def index_command(action: str) -> int:
    """`mailbrief index status|update|rebuild`: the search index chat uses. Prints counts only."""
    from mailbrief import archive, index

    if action == "status":
        s = index.status()
        if not s["emails"]:
            print("No search index yet: run `mailbrief index rebuild` (or wait for the next run).")
            return 0
        print(f"Search index: {s['emails']} emails, {s['chunks']} chunks, model {s['model']}, "
              f"{s['bytes'] / 1e6:.1f} MB, updated {s['updated']}")
        return 0
    try:
        emails = archive.load()[0]
    except archive.ArchiveError as e:
        print(e)
        return 1
    from mailbrief.service import Busy, lock

    t0 = time.time()
    try:
        with lock("run"):  # one writer at a time: never alongside a run's own index update
            added, removed = index.update(emails, sys.stdout, rebuild=action == "rebuild")
    except Busy:
        print("A MailBrief run is in progress; try again when it finishes.")
        return 3
    s = index.status()
    print(f"Embedded {added} email(s), removed {removed}, in {time.time() - t0:.0f}s. "
          f"Index: {s['emails']} emails, {s['chunks']} chunks, {s['bytes'] / 1e6:.1f} MB.")
    return 0 if s["emails"] or not emails else 1


def chat_command(question: str | None) -> int:
    """`mailbrief chat ["question"]`: ask your saved emails, in the terminal. Memory lasts for this session only."""
    from mailbrief import archive, index
    from mailbrief.ai import answer

    if not index.status()["emails"]:
        print("No search index yet: run `mailbrief index rebuild` first.")
        return 1
    history: list[tuple[str, str]] = []
    today = datetime.now(_tz()).date()
    while True:
        q = question
        if q is None:
            try:
                q = input("\nAsk (empty line to stop): ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not q:
                return 0
        try:
            emails = archive.load()[0]
        except archive.ArchiveError as e:
            print(e)
            return 1
        t0 = time.time()
        result = answer.ask(q, history, today, emails)
        print(f"\n{answer.render(result)}\n\n({time.time() - t0:.0f}s)")
        if result["send"]:
            print("Files it would send in Telegram: " + ", ".join(a["name"] for _, a in result["send"]))
        history.append((q, result["text"]))
        if question is not None:
            return 0


def events_command(days: int | None, send: bool, past: int = 0) -> int:
    """`mailbrief events [--days N] [--past N] [--send]`: the events calendar, from the saved archive."""
    from mailbrief import archive, events, rules

    if not 0 <= past <= 365 or (days is not None and not 0 <= days <= 365):
        print("--days and --past must be 0-365")
        return 2
    if days == 0 and not past:
        print("--days 0 shows nothing ahead; add --past N to see past events")
        return 2
    window = days if days is not None else (events.days() or events.DEFAULT_DAYS)
    today = datetime.now(_tz()).date()
    try:
        try:
            your_rules = rules.load()
        except rules.RulesError:
            your_rules = rules.empty()
        found = events.upcoming(archive.load()[0], today, window, (), your_rules, past)
        text = events.render(found, today, window, past)
    except archive.ArchiveError as e:
        print(e)
        return 1
    if not text:
        span = " or ".join(x for x in (f"the last {past} days" if past else "", f"the next {window} days" if window else "") if x)
        print(f"No events in {span}.")
        return 0
    if send:
        return 0 if deliver(events.render(found, today, window, past, html=True), sys.stdout, html=True) else 1
    print(text)
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
        print(
            "No chats found. Send your bot a message in Telegram first, then run this again."
        )
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
    # Emoji subjects and progress marks (✓) crash Windows' cp1252 encoding when output is piped.
    for stream in (sys.stdout, sys.stderr):
        if stream:  # None under pythonw (autostart runs `serve` without a window)
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="mailbrief", description="AI morning email digest for Outlook"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    login_p = sub.add_parser("login", help="sign in to Outlook once in a visible browser")
    login_p.add_argument("--remote", action="store_true",
                         help="no screen (a server): print a one-time link to sign in from any browser")
    run_p = sub.add_parser(
        "run", help="headless: classify new emails and print the digest"
    )
    run_p.add_argument(
        "--all", action="store_true", help="every inbox email, ignoring the cursor"
    )
    run_p.add_argument(
        "--backfill",
        action="store_true",
        help="save the whole inbox to the archive: no digest, skips saved emails, resumable",
    )
    run_p.add_argument(
        "--json",
        action="store_true",
        help="print email records with classifications as JSON",
    )
    run_p.add_argument(
        "--send", action="store_true", help="send the digest to all destinations"
    )
    run_p.add_argument(
        "--commit",
        action="store_true",
        help="mark these emails processed (advance the cursor)",
    )
    run_p.add_argument(
        "--no-password",
        action="store_true",
        help="save the archive as plain JSON instead of encrypted",
    )
    run_p.add_argument(
        "--quiet",
        action="store_true",
        help="don't print email subjects or the digest text (for logs)",
    )
    run_p.add_argument(
        "--digest",
        dest="digest_scope",
        metavar="SCOPE",
        choices=["new", "this-week", "this-month", "last-month", "older", "all"],
        help="what the digest covers: new (default: since the last commit), this-week, this-month, "
        "last-month, older, all (read from the saved archive)",
    )
    em_p = sub.add_parser(
        "emails", help="browse saved emails (this week by default), grouped by thread"
    )
    em_p.add_argument(
        "--period", choices=["this-week", "this-month", "last-month", "older"]
    )
    em_p.add_argument("--day", help="one day, e.g. 2026-10-16")
    em_p.add_argument(
        "--search", help="text to find in sender, subject or body (all periods)"
    )
    em_p.add_argument(
        "--show",
        type=int,
        metavar="N",
        help="open email #N from the list, with its thread outline",
    )
    em_p.add_argument(
        "--thread",
        type=int,
        metavar="N",
        help="print the whole conversation of email #N",
    )
    em_p.add_argument(
        "--digest",
        action="store_true",
        help="show the saved digest(s) for --day (default today)",
    )
    em_p.add_argument(
        "--export", metavar="FILE", help="write the listed emails to FILE as plain JSON"
    )
    em_p.add_argument(
        "--send",
        action="store_true",
        help="with --digest: resend the latest saved digest to all destinations",
    )
    dest_p = sub.add_parser(
        "add-destination", help="add where digests are sent (local setup only)"
    )
    dest_p.add_argument("type", choices=["telegram"])
    dest_p.add_argument(
        "--chat-id", help="skip the lookup and add this chat id directly"
    )
    lab_p = sub.add_parser(
        "labels",
        help="MailBrief's MB: labels (categories) in Outlook: status, apply, clear",
    )
    lab_sub = lab_p.add_subparsers(dest="action", required=True)
    lab_sub.add_parser("status", help="labelled / pending / cleared emails per period")
    for name, text in (
        ("apply", "label now (pending emails; also re-labels cleared ones)"),
        ("clear", "remove MB: labels (your own categories stay)"),
        (
            "retag",
            "ask the AI again about saved emails, with your current profile and topics",
        ),
    ):
        a = lab_sub.add_parser(name, help=text)
        a.add_argument(
            "--period", choices=["this-week", "this-month", "last-month", "older"]
        )
        a.add_argument(
            "--days", type=int, metavar="N", help="emails from the last N days"
        )
        a.add_argument(
            "--limit", type=int, metavar="N", help="at most N emails (newest first)"
        )
        a.add_argument(
            "--dry-run",
            action="store_true",
            help="show what would change; don't touch Outlook",
        )
        if name != "apply":
            a.add_argument(
                "--yes", action="store_true", help="don't ask for confirmation"
            )
        if name == "clear":
            a.add_argument(
                "--all", action="store_true", help="every email MailBrief labelled"
            )
            a.add_argument(
                "--colours",
                action="store_true",
                help="also delete the MB: categories from your category list (removes them from every email)",
            )
            a.add_argument(
                "--label",
                metavar="NAME",
                help='only this one of your own labels, e.g. "MA1521" (all periods by default)',
            )
            a.add_argument(
                "--everywhere",
                action="store_true",
                help="with --label: from every email in the mailbox and your category list",
            )
    rules_p = sub.add_parser(
        "rules",
        help="your own labels: courses, senders, topics, profile (data/rules.json)",
    )
    rules_sub = rules_p.add_subparsers(dest="action", required=True)
    rules_sub.add_parser(
        "list", help="your rules and how many saved emails each matches"
    )
    add_p = rules_sub.add_parser(
        "add",
        help='add or replace a rule: course CS2040S | sender ADDRESS --label "Prof Tan" | topic NAME "description"',
    )
    add_p.add_argument("kind", choices=["course", "sender", "topic"])
    add_p.add_argument(
        "key", help="course code, sender address (or part of a name), or topic name"
    )
    add_p.add_argument(
        "description", nargs="?", help="topic only: what counts, in plain words"
    )
    add_p.add_argument(
        "--label", help='sender only: the label to give, e.g. "Prof Tan"'
    )
    add_p.add_argument(
        "--direct",
        action="store_true",
        help="sender only: only mail where you're the only To recipient",
    )
    add_p.add_argument(
        "--priority",
        type=int,
        choices=range(1, 6),
        metavar="1-5",
        help="raise matching mail to at least this priority",
    )
    add_p.add_argument(
        "--boost",
        action="store_true",
        help="course/sender: always list under OPPORTUNITIES & EVENTS with ⭐",
    )
    rm_p = rules_sub.add_parser(
        "remove", help="remove a rule (emails already labelled keep the label)"
    )
    rm_p.add_argument("kind", choices=["course", "sender", "topic"])
    rm_p.add_argument("key", help="course code, sender match, or topic name")
    prof_p = rules_sub.add_parser(
        "profile",
        help='set who you are and what you want, e.g. "Year 2 CS student looking for internships"',
    )
    prof_p.add_argument("text", help='your profile ("" clears it)')
    idx_p = sub.add_parser("index", help="the search index chat uses (data/index.enc): status, rebuild")
    idx_p.add_argument("action", choices=["status", "update", "rebuild"])
    chat_p = sub.add_parser("chat", help="ask your saved emails a question in the terminal (as the Telegram chat does)")
    chat_p.add_argument("question", nargs="?", help="one question; leave out to keep asking (empty line or Ctrl+C ends)")
    sub.add_parser("bot", help="run only the Telegram chat listener in the foreground (serve runs it too)")
    ev_p = sub.add_parser("events", help="upcoming events found in your saved emails (no Outlook, no AI)")
    ev_p.add_argument("--days", type=int, metavar="N", help="how far ahead (default EVENTS_DAYS, 14; 0 = none, with --past)")
    ev_p.add_argument("--past", type=int, default=0, metavar="N", help="also show events from the last N days")
    ev_p.add_argument("--send", action="store_true", help="send it to all destinations instead of just printing")
    serve_p = sub.add_parser(
        "serve",
        help="run forever, firing runs on the RUN_AT schedule (Ctrl+C or `stop` to end)",
    )
    serve_p.add_argument(
        "--at",
        metavar="SCHEDULE",
        help='e.g. "daily 07:30; sun 20:00 this-week" (default: RUN_AT)',
    )
    sub.add_parser(
        "stop",
        help="ask a running `serve` to stop (it finishes a run in progress first)",
    )
    sub.add_parser(
        "status", help="is `serve` running? schedule, next and last run, log file"
    )
    auto_p = sub.add_parser(
        "autostart", help="Windows: start `serve` hidden at logon (Task Scheduler)"
    )
    auto_p.add_argument("state", choices=["on", "off"])
    args = parser.parse_args()

    if args.command == "login":
        if args.remote:
            from mailbrief.session.remote_login import run_cli

            sys.exit(run_cli())
        from mailbrief.session.login_once import login_once

        login_once()
        sys.exit(0)
    if args.command == "add-destination":
        sys.exit(add_destination(args.type, args.chat_id))
    if args.command == "emails":
        if args.send and not args.digest:
            print("--send works with --digest (it resends the latest saved digest).")
            sys.exit(2)
        sys.exit(
            show_emails(
                args.period,
                args.day,
                args.search,
                args.show,
                args.thread,
                args.digest,
                args.export,
                args.send,
            )
        )
    if args.command == "labels":
        sys.exit(labels_command(args))
    if args.command == "rules":
        sys.exit(rules_command(args))
    if args.command == "events":
        sys.exit(events_command(args.days, args.send, args.past))
    if args.command == "index":
        sys.exit(index_command(args.action))
    if args.command == "chat":
        sys.exit(chat_command(args.question))
    if args.command == "bot":
        from mailbrief.notify import bot

        sys.exit(bot.run_foreground())
    if args.command in ("serve", "stop", "status", "autostart"):
        from mailbrief import service

        spec = (
            getattr(args, "at", None)
            or os.environ.get("RUN_AT")
            or service.DEFAULT_SCHEDULE
        )
        if args.command == "serve":
            try:
                sys.exit(service.serve(spec))
            except ValueError as e:
                print(f"Bad schedule: {e}")
                sys.exit(2)
        if args.command == "stop":
            sys.exit(service.stop())
        if args.command == "status":
            sys.exit(service.status(spec))
        sys.exit(service.autostart(args.state == "on"))
    from mailbrief.service import Busy, lock

    try:
        with lock("run"):  # a manual run and a scheduled one never overlap
            code = run(
                show_all=args.all,
                as_json=args.json,
                commit=args.commit,
                send=args.send,
                plain=args.no_password,
                backfill=args.backfill,
                digest_scope=args.digest_scope,
                quiet=args.quiet,
            )
    except Busy:
        print(
            "Another MailBrief run is in progress; try again when it finishes (`mailbrief status`)."
        )
        code = 3
    sys.exit(code)


if __name__ == "__main__":
    main()
