"""Outlook labels (categories): each inbox email gets "MB: <category>" + "MB: P<priority>", coloured.

The archive remembers what each email was given (outlook_labels), so runs only touch what changed, clearing knows
exactly what to undo, and a cleared email (labels_cleared) isn't labelled again unless you ask.
"""

import os
from contextlib import contextmanager
from datetime import datetime, timedelta

from mailbrief import archive

# Outlook's colour numbers (the same presets as Settings → Categories).
CATEGORY_COLOURS = {"Urgent": 0, "Needs Reply": 1, "Meetings": 8, "FYI": 7, "Newsletter": 4, "Low Priority": 12}
#                   red         orange            purple         blue      green            grey
PRIORITY_COLOURS = {1: 15, 2: 1, 3: 3, 4: 5, 5: 12}
#                   dark red, orange, yellow, teal, grey
ALL_LABELS = {**{f"MB: {c}": col for c, col in CATEGORY_COLOURS.items()},
              **{f"MB: P{p}": col for p, col in PRIORITY_COLOURS.items()}}
RUN_LIMIT = 400  # per run; the first run on a big archive finishes the rest next time


class LoginNeeded(Exception):
    pass


def enabled() -> bool:
    return os.environ.get("OUTLOOK_LABELS", "on").strip().lower() not in ("off", "0", "false", "no")


def labels_for(email: dict) -> list[str]:
    """The MB: labels this email should carry: [] for anything that isn't a classified inbox email from someone else."""
    c = email.get("classification") or {}
    if c.get("category") not in CATEGORY_COLOURS or email.get("from_me") or not email.get("in_inbox", True) \
            or email.get("body_source") != "getitem":  # preview records carry a conversation id, not an email id
        return []
    return [f"MB: {c['category']}"] + ([f"MB: P{c['priority']}"] if c.get("priority") in PRIORITY_COLOURS else [])


def select(emails: list[dict], period: str | None, days: int | None, today, tz) -> list[dict]:
    """Emails in a period ("this-month", …) or the last N days; everything when neither is given."""
    if period:
        return [e for e in emails if archive.in_period(e, period, today, tz)]
    if days:
        since = datetime.combine(today - timedelta(days=days - 1), datetime.min.time(), tzinfo=tz)
        return [e for e in emails if e["received_at"] >= since]
    return list(emails)


def pending(emails: list[dict], include_cleared: bool = False) -> list[dict]:
    """Emails whose MB: labels in Outlook aren't what they should be (newest first, as given)."""
    return [e for e in emails if labels_for(e) and not e.get("outlook_gone")
            and (include_cleared or not e.get("labels_cleared"))
            and labels_for(e) != e.get("outlook_labels")]


def labelled(emails: list[dict]) -> list[dict]:
    return [e for e in emails if e.get("outlook_labels")]


@contextmanager
def outlook():
    """A headless Outlook page with your saved session: yields (page, auth, startup). Saves rotated cookies after."""
    from playwright.sync_api import sync_playwright

    from mailbrief.browser.connect import get_browser
    from mailbrief.browser.outlook_reader import open_outlook
    from mailbrief.session import manager

    session = manager.load()
    if session is None:
        raise LoginNeeded("no saved session: run `mailbrief login`")
    with sync_playwright() as p:
        browser = get_browser(p, headless=True)
        try:
            context = browser.new_context(storage_state=session["state"], user_agent=session["user_agent"])
            page = context.new_page()
            opened = open_outlook(page)
            if opened["expired"]:
                raise LoginNeeded("the Outlook session expired: run `mailbrief login`")
            yield page, opened["auth"], opened["startup"]
            manager.save(context, session["user_agent"])
        finally:
            browser.close()


def _tally(results: dict[str, str]) -> str:
    ok = sum(r == "ok" for r in results.values())
    gone = sum(r == "gone" for r in results.values())
    failed = [r for r in results.values() if r.startswith("failed")]
    return f"{ok} done" + (f", {gone} no longer in the mailbox" if gone else "") + \
        (f", {len(failed)} failed ({failed[0]})" if failed else "")


def apply(emails: list[dict]) -> str:
    """Give these emails their MB: labels (creating the coloured categories first if needed). Returns a summary."""
    from mailbrief.browser.outlook_writer import ensure_categories, set_labels
    from mailbrief.browser.owa_network import master_categories

    wanted = {e["id"]: labels_for(e) for e in emails}
    with outlook() as (page, auth, startup):
        added = ensure_categories(page, auth, master_categories(startup), ALL_LABELS)
        results = set_labels(page, auth, wanted)
    archive.update_fields({i: {"outlook_labels": wanted[i], "labels_cleared": False} if r == "ok" else {"outlook_gone": True}
                           for i, r in results.items() if r in ("ok", "gone")})
    return f"Labelled in Outlook: {_tally(results)}" + (f"; created {len(added)} coloured MB: categories" if added else "")


def clear(emails: list[dict], colours: bool = False) -> str:
    """Remove MB: labels from these emails (your own categories stay). colours: also delete the MB: categories from
    your category list, which strips them from every email, tracked or not."""
    from mailbrief.browser.outlook_writer import remove_categories, set_labels
    from mailbrief.browser.owa_network import master_categories

    results = {}
    with outlook() as (page, auth, startup):
        if emails:
            results = set_labels(page, auth, {e["id"]: [] for e in emails}, label="Clearing labels")
        removed = []
        if colours:
            existing = master_categories(startup) or {}
            removed = [n for n in existing if n in ALL_LABELS]
            if removed:
                remove_categories(page, auth, removed)
    archive.update_fields({i: {"outlook_labels": [], "labels_cleared": True}
                           for i, r in results.items() if r in ("ok", "gone")})
    return f"Cleared labels: {_tally(results)}" + (f"; deleted {len(removed)} MB: categories from your list" if removed else "")


def run_step(log) -> None:
    """The labelling step of `mailbrief run`: label what's pending (capped), never failing the run."""
    from mailbrief import progress

    if not enabled():
        return
    try:
        todo = pending(archive.load()[0])
        if not todo:
            return
        progress.step(f"Labelling {min(len(todo), RUN_LIMIT)} emails in Outlook…")
        print(apply(todo[:RUN_LIMIT]) + (f" ({len(todo) - RUN_LIMIT} more next run)" if len(todo) > RUN_LIMIT else ""),
              file=log)
    except Exception as e:  # noqa: BLE001 - labels are a bonus: the digest, delivery and cursor must still happen
        print(f"warning: Outlook labels not applied ({type(e).__name__}: {e}); retried next run", file=log)
