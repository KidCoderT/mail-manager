"""Offline tour using invented mail in a disposable archive; never opens Outlook or calls an AI."""

import argparse
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mailbrief import archive
from mailbrief.main import events_command, show_emails


def sample_emails(now: datetime) -> list[dict]:
    specs = [
        ("Housing Office", "housing", "Housing fee due", "Urgent", "Pay the housing acceptance fee by Friday.", 1),
        ("Dr Ada Reed", "ada", "Lab demo helpers", "Needs Reply", "Can you help set up Thursday's lab demo?", None),
        ("Algorithms Team", "algorithms", "Problem set 4", "FYI", "Submit problem set 4 by Sunday 23:59.", 3),
        ("Hack Club", "hack", "Campus HackDay", "FYI", "Bring a laptop to Campus HackDay in Innovation Hall.", 5),
        ("Library", "library", "Book ready to collect", "FYI", "Your reserved book is ready at the main desk.", None),
        ("Careers Team", "careers", "CV clinic", "FYI", "Join the CV clinic in Workshop Room 2 at 14:00.", 2),
        ("Sam Patel", "sam", "Project review", "Needs Reply", "Does Tuesday at 10:00 work for the project review?", 5),
        ("Systems Team", "systems", "Maintenance notice", "FYI", "The teaching portal will be unavailable overnight.", None),
        ("Science Club", "science", "Science weekly", "Newsletter", "This week's talks and student projects.", None),
        ("Robotics Club", "robotics", "Robot building night", "FYI", "Build a line-following robot in Lab 3 at 18:00.", 4),
        ("Sports Centre", "sports", "Pool opening hours", "FYI", "The pool opens at 07:00 during term time.", None),
        ("Accounts Office", "accounts", "Printing receipt", "FYI", "Your printing balance top-up is complete.", None),
        ("Tech Society", "tech", "Tech weekly", "Newsletter", "Student technology news and event round-up.", None),
        ("You", "demo", "Re: Lab demo helpers", "Sent", "Yes, I can help set up the demo at 09:00.", None),
        ("Dr Ada Reed", "ada", "Re: Lab demo helpers", "FYI", "Thanks! See you in Lab 2 at 09:00.", 7),
    ]
    emails = []
    for i, (sender, address, subject, category, body, offset) in enumerate(specs):
        day = (now + timedelta(days=offset)).date().isoformat() if offset is not None else None
        if i == 0:
            body = f"Pay the housing acceptance fee by {day}."
        elif i == 2:
            body = f"Submit problem set 4 by {day} 23:59."
        emails.append({
            "id": f"demo-{i + 1}", "conversation_id": "lab-demo" if i in (1, 13, 14) else f"thread-{i}",
            "sender_name": sender, "sender_email": f"{address}@example.edu", "subject": subject,
            "body_text": body, "received_at": now - timedelta(hours=len(specs) - i),
            "body_source": "getitem", "in_inbox": category != "Sent", "from_me": category == "Sent",
            "attachment_names": [], "to": ["demo@example.edu"], "replied": i == 1,
            "classification": {
                "category": category, "priority": 1 if category == "Urgent" else 3,
                "one_line_summary": body, "action_items": [body] if i in (0, 2) else [],
                "deadline": day if i in (0, 2) else None,
                "model": "offline-example", "events": [{"name": subject, "date": day, "time": None,
                                                           "place": None, "detail": body}] if day else [],
            },
        })
    return emails


def tour(view: str) -> int:
    now = datetime.now(timezone.utc)
    emails = sample_emails(now)
    digest = ("EXAMPLE DIGEST (prewritten, not a live AI response)\n\n"
              "TOP PRIORITIES TODAY\n• Housing acceptance fee needs attention. [1]\n\n"
              "NEEDS A REPLY\n• Sam asks about a project review. [7]\n\n"
              "DEADLINES & MEETINGS\n• Problem set 4 is due in three days at 23:59. [3]\n\n"
              "FYI\n• You already replied to the lab demo request. [2][14][15]")
    old_cwd, old_archive = Path.cwd(), archive.ARCHIVE_DIR
    with tempfile.TemporaryDirectory(prefix="mailbrief-demo-") as folder:
        try:
            os.chdir(folder)  # rules and all other relative paths also stay away from the real data/
            archive.ARCHIVE_DIR = Path(folder) / "archive"
            archive.save(emails, [e["classification"] for e in emails], digest, True, timezone.utc, now)
            print("OFFLINE DEMO — invented mail; no Outlook, Telegram, AI, or real data used.\n")
            if view == "events":
                return events_command(14, False)
            if view == "digest":
                print(digest)
                return 0
            if view == "chat":
                print('EXAMPLE CHAT (prewritten)\nYou: Did I reply to the lab demo request?\n'
                      'MailBrief: Yes. You wrote: "Yes, I can help set up the demo at 09:00."\n'
                      'Source: You <demo@example.edu> — Re: Lab demo helpers (demo-14).')
                return 0
            return show_emails(None, None, "lab demo" if view == "thread" else "example.edu",
                               1 if view == "email" else None, 1 if view == "thread" else None,
                               False, None)
        finally:
            os.chdir(old_cwd)
            archive.ARCHIVE_DIR = old_archive


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("view", nargs="?", default="emails", choices=("emails", "email", "thread", "events", "digest", "chat"))
    raise SystemExit(tour(parser.parse_args().view))
