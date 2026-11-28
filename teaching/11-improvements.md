# Improvements: what the review found and how it was fixed

This chapter covers one piece of work: the review of MailBrief and the commits that came out of it. The review had four parts run side by side: a bug review of the core pipeline, a bug and security review of the input/output edges (browser, sign-in server, images, AI client, Telegram), a UI/UX review of the CLI, the bot and the sign-in page, and a release-readiness review for GitHub hosting and a website. A follow-up session then finished the open items: the offline demo, AI portability, the type checks and the website. Bugs found earlier, by running against live Outlook, are in [Lessons from real bugs](10-lessons-and-limits.md) and are not repeated here.

The work was done on the branch `review-fixes`, which has since been merged into `main` as a fast-forward. So `git log main..HEAD` is now empty. To list the commits, use the last commit before the review instead: `git log --oneline --reverse 78bbd1d..3a40e6d`. That range has 79 commits. Every one of them is accounted for below.

**How to read an entry.** Each heading names the change and its commit. Under it:

- **How it was found** says what went wrong, which review pass (or test) spotted it, and the evidence it gave. These come from the commit messages and the review thread. Where the record is thin, the entry says so.
- **How it was fixed** shows the real Python from the diff, explains how the new code works, and says why this fix and not another.
- **Lesson** is the general rule to take away.
- **Test** names the test that now guards it. That test is also the reproduction: run it against the old code and it fails.

To see any change in full, run `git show <sha>`, for example `git show 8341920`. Code blocks that start with `# before` or `# after` are excerpts from that commit's diff. Blocks that start with a file path, like `# mailbrief/storage/files.py::replace`, are copied from the current source, and `tests/test_teaching.py` fails if they drift.

<!-- TOC -->
**Contents**

- [Summary](#summary)
- [Correctness fixes](#correctness-fixes)
   - [The cursor stays put when the archive save fails (`8341920`)](#the-cursor-stays-put-when-the-archive-save-fails-8341920)
   - [A run that parses nothing from Outlook exits 5, not 0 (`df67c90`)](#a-run-that-parses-nothing-from-outlook-exits-5-not-0-df67c90)
   - [An email that leaves the inbox keeps its classification (`8a784c8`)](#an-email-that-leaves-the-inbox-keeps-its-classification-8a784c8)
   - [A caught-up weekly or monthly digest covers its own period (`ae7c427`)](#a-caught-up-weekly-or-monthly-digest-covers-its-own-period-ae7c427)
   - [A slot that succeeded before a retry is not run twice (`fb85d32`)](#a-slot-that-succeeded-before-a-retry-is-not-run-twice-fb85d32)
   - [Scheduled runs stay on local time across a DST change (`53dfa47`)](#scheduled-runs-stay-on-local-time-across-a-dst-change-53dfa47)
   - [An impossible deadline no longer breaks "what's coming up" questions (`f9efd88`)](#an-impossible-deadline-no-longer-breaks-whats-coming-up-questions-f9efd88)
   - [A missing key no longer kills the chat listener silently (`0f0ac8b`)](#a-missing-key-no-longer-kills-the-chat-listener-silently-0f0ac8b)
   - [`serve` tells you on Telegram when it gives up on a run (`12ea8cf`)](#serve-tells-you-on-telegram-when-it-gives-up-on-a-run-12ea8cf)
   - [A damaged search index is rebuilt instead of breaking chat (`5a52977`)](#a-damaged-search-index-is-rebuilt-instead-of-breaking-chat-5a52977)
   - [File saves survive a briefly locked file on Windows (`50e47e5`)](#file-saves-survive-a-briefly-locked-file-on-windows-50e47e5)
   - [Ctrl+C during classification stops the queued AI calls (`9ccda8b`)](#ctrlc-during-classification-stops-the-queued-ai-calls-9ccda8b)
   - [List-preview records are no longer saved to the archive (`e824841`)](#list-preview-records-are-no-longer-saved-to-the-archive-e824841)
   - [`labels retag` reports AI failures instead of hiding them (`226ba3a`)](#labels-retag-reports-ai-failures-instead-of-hiding-them-226ba3a)
   - [Long HTML lines are cut between links, not inside them (`67ce2dc`)](#long-html-lines-are-cut-between-links-not-inside-them-67ce2dc)
   - [A string `action_items` is one item, not a list of letters (`e4b2a7f`)](#a-string-action_items-is-one-item-not-a-list-of-letters-e4b2a7f)
   - [Digest batches are ordered by time, not by weekday name (`8832c83`)](#digest-batches-are-ordered-by-time-not-by-weekday-name-8832c83)
   - [`/events` with a non-ASCII digit no longer fails (`fdd9ae4`)](#events-with-a-non-ascii-digit-no-longer-fails-fdd9ae4)
   - [The AI client retries dropped connections and caps waits (`2fcf11f`)](#the-ai-client-retries-dropped-connections-and-caps-waits-2fcf11f)
   - [A sign-in page on another host counts as an expired session (`0fbb017`)](#a-sign-in-page-on-another-host-counts-as-an-expired-session-0fbb017)
   - [Telegram updates are confirmed before they are acted on (`d44e871`)](#telegram-updates-are-confirmed-before-they-are-acted-on-d44e871)
   - [A caught-up digest stops at its scheduled day (`0031b03`)](#a-caught-up-digest-stops-at-its-scheduled-day-0031b03)
   - [AI retry messages go to stderr, so `--json` stays valid (`fdcbab9`)](#ai-retry-messages-go-to-stderr-so---json-stays-valid-fdcbab9)
- [Security](#security)
   - [The sign-in server drops silent connections after 10 s (`b8c8f41`)](#the-sign-in-server-drops-silent-connections-after-10-s-b8c8f41)
   - [`LOGIN_PAGE=always` never serves plain http to the network (`0f90473`)](#login_pagealways-never-serves-plain-http-to-the-network-0f90473)
   - [A linked-image download has a total time limit (`981bbf1`)](#a-linked-image-download-has-a-total-time-limit-981bbf1)
   - [IPv6 addresses that wrap a private IPv4 are refused (`170dc4b`)](#ipv6-addresses-that-wrap-a-private-ipv4-are-refused-170dc4b)
   - [A remote sign-in is checked before it replaces the saved one (`ae2d7a1`)](#a-remote-sign-in-is-checked-before-it-replaces-the-saved-one-ae2d7a1)
   - [The write guard only allows the one category operation used (`bee2872`)](#the-write-guard-only-allows-the-one-category-operation-used-bee2872)
   - [The sign-in server no longer identifies itself (`186274c`)](#the-sign-in-server-no-longer-identifies-itself-186274c)
- [User experience](#user-experience)
   - [A missing or placeholder encryption key is explained before login (`94e1eef`)](#a-missing-or-placeholder-encryption-key-is-explained-before-login-94e1eef)
   - [The first-time recipe sends a digest before the backfill (`f423d59`)](#the-first-time-recipe-sends-a-digest-before-the-backfill-f423d59)
   - [`/sync` says so when there is no new mail (`e126843`)](#sync-says-so-when-there-is-no-new-mail-e126843)
   - [The bot answers a photo, voice note or file (`6991c64`)](#the-bot-answers-a-photo-voice-note-or-file-6991c64)
   - [Bot error replies say what went wrong and what to do (`52dfa0e`)](#bot-error-replies-say-what-went-wrong-and-what-to-do-52dfa0e)
   - [`/label` and `/profile` replies use chat commands, not CLI flags (`fa00e88`)](#label-and-profile-replies-use-chat-commands-not-cli-flags-fa00e88)
   - [The bot calls your rules `/rules`, as the CLI does (`7c15ff2`)](#the-bot-calls-your-rules-rules-as-the-cli-does-7c15ff2)
   - [Ctrl+C prints "Stopped." instead of a traceback (`db1a640`)](#ctrlc-prints-stopped-instead-of-a-traceback-db1a640)
   - [A wrong key, no network or no browser gives one line (`b94680a`)](#a-wrong-key-no-network-or-no-browser-gives-one-line-b94680a)
   - [`add-destination` explains Telegram errors (`3158506`)](#add-destination-explains-telegram-errors-3158506)
   - [Every `--help` screen has a description and examples (`a82bcc2`)](#every---help-screen-has-a-description-and-examples-a82bcc2)
   - [`run --no-password` is now `--plain` (`af3837e`)](#run---no-password-is-now---plain-af3837e)
   - [`--limit`, `--days`, `--show` and `--thread` refuse zero and negatives (`d309338`)](#--limit---days---show-and---thread-refuse-zero-and-negatives-d309338)
   - [`run --json` always prints valid JSON on stdout (`8cb732e`)](#run---json-always-prints-valid-json-on-stdout-8cb732e)
   - [The sign-in page tells a timeout from a failed sign-in (`f4dc27e`)](#the-sign-in-page-tells-a-timeout-from-a-failed-sign-in-f4dc27e)
   - [The sign-in page's Start button can only be tapped once (`61425cc`)](#the-sign-in-pages-start-button-can-only-be-tapped-once-61425cc)
   - [The sign-in page shows "Loading…" until the first picture arrives (`501e2f9`)](#the-sign-in-page-shows-loading-until-the-first-picture-arrives-501e2f9)
   - [The sign-in page follows the phone's dark mode (`d037394`)](#the-sign-in-page-follows-the-phones-dark-mode-d037394)
   - [The sign-in page explains itself and is easier to tap and read (`9526614`)](#the-sign-in-page-explains-itself-and-is-easier-to-tap-and-read-9526614)
   - [The sign-in page has separate email, password and code fields (`2a63d62`)](#the-sign-in-page-has-separate-email-password-and-code-fields-2a63d62)
   - [Digest section headings are bold in Telegram (`3b45145`)](#digest-section-headings-are-bold-in-telegram-3b45145)
   - [Links to emails are wider tap targets (`b370d48`)](#links-to-emails-are-wider-tap-targets-b370d48)
- [Tests, types and CI](#tests-types-and-ci)
   - [Tests stop writing `tests/no-such-rules.json` into the repo (`e832ce9`)](#tests-stop-writing-testsno-such-rulesjson-into-the-repo-e832ce9)
   - [Remove an unused variable and an unused import (`1fcceb3`)](#remove-an-unused-variable-and-an-unused-import-1fcceb3)
   - [Cover archive, delivery and parser failures in the run pipeline (`22ad05c`)](#cover-archive-delivery-and-parser-failures-in-the-run-pipeline-22ad05c)
   - [Resolve nullable values and inference errors across the code (`b5f4c11`)](#resolve-nullable-values-and-inference-errors-across-the-code-b5f4c11)
   - [Enforce type checks and lint the demo and scripts in CI (`561164c`)](#enforce-type-checks-and-lint-the-demo-and-scripts-in-ci-561164c)
   - [Verify successful schedule slots are not repeated during retries (`ed5fc81`)](#verify-successful-schedule-slots-are-not-repeated-during-retries-ed5fc81)
- [Configuration and AI portability](#configuration-and-ai-portability)
   - [Drop three settings the code never reads (`4b77566`)](#drop-three-settings-the-code-never-reads-4b77566)
   - [No built-in AI endpoint, checked before Outlook opens (`6a60c9d`)](#no-built-in-ai-endpoint-checked-before-outlook-opens-6a60c9d)
   - [The vendor thinking extension is opt-in (`e734e62`)](#the-vendor-thinking-extension-is-opt-in-e734e62)
   - [Local AI endpoints work without a dummy API key (`412b612`)](#local-ai-endpoints-work-without-a-dummy-api-key-412b612)
- [Demo](#demo)
   - [An isolated offline tour with fifteen invented emails (`e24c655`)](#an-isolated-offline-tour-with-fifteen-invented-emails-e24c655)
- [Documentation and project hosting](#documentation-and-project-hosting)
   - [Documentation accuracy (seven commits)](#documentation-accuracy-seven-commits)
   - [GitHub and CI: workflows, metadata, security policy, changelog (`4693e87`)](#github-and-ci-workflows-metadata-security-policy-changelog-4693e87)
   - [README: a landing page first, the design document after (`0b4259e`)](#readme-a-landing-page-first-the-design-document-after-0b4259e)
- [Website](#website)
   - [The first static showcase and setup guide (`02c13d4`)](#the-first-static-showcase-and-setup-guide-02c13d4)
   - [Website redesigns and the shared CLI parser (`a3f1de1`, `f74caa2`, `efd2012`, `62a7bf6`, `d1f20b5`, `3a40e6d`)](#website-redesigns-and-the-shared-cli-parser-a3f1de1-f74caa2-efd2012-62a7bf6-d1f20b5-3a40e6d)
- [Patterns across the review](#patterns-across-the-review)
<!-- /TOC -->

## Summary

| Category | Entries | Commits |
|---|---|---|
| Correctness fixes (`Fix:`) | 23 | 23 |
| Security | 7 | 7 |
| User experience (`UX:`) | 22 | 22 |
| Tests, types and CI | 6 | 6 |
| Configuration and AI portability | 4 | 4 |
| Demo | 1 | 1 |
| Documentation and project hosting | 3 | 9 |
| Website | 2 | 7 |
| **Total** | **68** | **79** |

Two `Fix:` commits (`e734e62`, `412b612`) are about AI portability, so they sit under Configuration and AI portability. Each still has its own entry. The seven docs-only commits share one entry, with a bullet each. The seven website commits, including the two `WIP` commits and the final `3a40e6d`, share two entries.

---

## Correctness fixes

### The cursor stays put when the archive save fails (`8341920`)

**How it was found.** The core pipeline review traced `run` in `mailbrief/main.py` and reported two linked bugs. First, `archive.prune()` ran `int(os.environ["ARCHIVE_DAYS"])` inside the same `try` as `archive.save()`. A typo such as `ARCHIVE_DAYS=30d` raised `ValueError`, so the whole save was skipped with only a warning. Second, and worse, `--commit` still advanced the cursor after any failed save: a full disk, a locked file, or one month file that wouldn't decrypt. Those emails were then never archived. Emails the AI had failed on were never retried either, because `failed_ids` looks for them in the archive.

**How it was fixed.** Pruning got its own `try`, so a bad `ARCHIVE_DAYS` only skips pruning. The save records whether it worked, and the commit step refuses to move the cursor if it didn't.

```python
# after
    saved = True
    try:  # an old month not deleted (a typo in ARCHIVE_DAYS) must not stop this run's emails being saved
        archive.prune(datetime.now(tz).date())
    except Exception as e:  # noqa: BLE001
        print(f"warning: old archive months not pruned ({type(e).__name__}: {e}); check ARCHIVE_DAYS", file=log)
    try:  # a failure here must not lose the digest or block delivery (but the cursor stays: see below)
        progress.step("Saving to the archive…")
        # ...
    except Exception as e:  # noqa: BLE001
        saved = False
        saved_msg = f"warning: archive not saved ({type(e).__name__}: {e})"
    # ...
        if not saved:  # unsaved emails must be read again: the archive is where failed AI calls are retried from
            print("Cursor not advanced: these emails weren't saved to the archive.", file=log)
            return 4
```

How it works: `saved` starts true and only the save's `except` sets it false. The digest is still built and delivered, because losing the morning message over a disk problem would be worse. But just before `cur.save(cur.advance(...))` the run checks `saved` and returns exit code 4. Code 4 already meant "sent, but not marked processed", so `serve` needed only its wording changed. The next run reads the same emails again.

Why this fix: the cursor is the promise "everything before this point is safely stored". Only advance it when that is true. An alternative was to make the save itself raise and abort the run, but then a full disk would also cost you the digest. Splitting prune from save keeps an unimportant step (deleting old months) from blocking an important one.

**Lesson.** Only record progress after the work it stands for has really been saved.

**Test:** `tests/test_pipeline.py::test_failed_archive_does_not_advance_cursor` and `::test_invalid_pruning_setting_does_not_prevent_saving` (added later in `22ad05c`).

### A run that parses nothing from Outlook exits 5, not 0 (`df67c90`)

**How it was found.** Core pipeline review, item 3. If Outlook changed its internal JSON, `result["messages"]` came back empty. The run printed "Nothing parsed…", then "No new emails, so no digest", and exited 0. `serve` would log "run finished: ok" every day and no digest would ever come. Under `pythonw`, nobody sees the warning.

**How it was fixed.** Outlook reports its own inbox total. If that total is anything but 0 and nothing was parsed, the run fails.

```python
# after
        if result["total"] != 0:  # an empty inbox says 0; anything else means the list couldn't be read
            print("Outlook's inbox list couldn't be read (its format may have changed), so this run failed.", file=log)
            return 5  # not 0: `serve` must retry and then alert, not log "ok" on a run that saw nothing
```

Why this fix: the code can't tell "no mail" from "couldn't read the mail" by looking at an empty list. It can by comparing with a second source, here Outlook's own count. `None` (no count at all) also counts as a failure, which is the safe side. A new exit code, rather than reusing 1, lets `serve` and the bot say exactly what happened.

**Lesson.** An empty result is not proof of "nothing there". Check it against a second source before reporting success.

**Test:** `tests/test_pipeline.py::test_broken_inbox_format_fails_instead_of_reporting_success`.

### An email that leaves the inbox keeps its classification (`8a784c8`)

**How it was found.** Core pipeline review, item 2, traced through `run` and `archive._merge`. When a thread was fetched again (a new reply, or `--all`), any email no longer in the inbox was re-saved as `{"category": "Elsewhere"}`. The merge replaces the whole record, so an email you had filed lost its summary and events. It dropped out of the calendar and the period digests.

**How it was fixed.** A small helper decides whether the saved classification is real AI work worth keeping.

```python
# mailbrief/main.py::_kept
def _kept(stored: dict | None) -> dict | None:
    """The saved classification of an email that has left the inbox, if the AI really classified it."""
    c = (stored or {}).get("classification") or {}
    return c if c.get("category") not in (None, "Sent", "Elsewhere", "Unclassified") else None
```

```diff
-        if not r["in_inbox"] or r["from_me"]:
-            r["classification"] = {
-                "category": "Sent" if r["from_me"] else "Elsewhere"
-            }  # context only, no AI
+        if r["from_me"]:
+            r["classification"] = {"category": "Sent"}  # context only, no AI
+        elif not r["in_inbox"]:
+            # Filed or deleted since it was classified: keep that work (summary, events), don't blank it.
+            r["classification"] = _kept(stored) or {"category": "Elsewhere"}
```

How it works: `(stored or {})` and `.get(...) or {}` make the helper safe for a missing record or a `None` classification. The placeholder categories (`Sent`, `Elsewhere`, `Unclassified`) are not real work, so they return `None` and the `or` falls back to `Elsewhere`.

Why this fix: the bug was one `if` doing two jobs. Splitting "sent by me" from "left the inbox" made the second case free to look at the saved record. Changing `_merge` to keep old fields was the other option, but the merge is meant to replace records, and other callers depend on that.

**Lesson.** When you overwrite a record, ask what earlier work you are throwing away.

**Test:** `tests/test_main.py::test_kept_keeps_only_real_classifications`.

### A caught-up weekly or monthly digest covers its own period (`ae7c427`)

**How it was found.** Core pipeline review, item 1, marked confirmed. With `sun 20:00 this-week` in `RUN_AT` and the PC off on Sunday night, `serve` correctly caught up the slot on Monday morning. But it passed only the scope to the child run, and `digest_set` counted "this week" from today. On Monday that week had barely started, so the run printed "No emails for a 'this-week' digest", exited 0, and the slot was marked done. The reviewer reproduced it with `archive.in_period(...)` on a Saturday email and a Monday date: `False`.

**How it was fixed.** The slot's own date now travels to the child as `run --as-of YYYY-MM-DD`.

```python
# after
def run_args(scope: str, at: datetime | None = None) -> list[str]:
    """'new' advances the cursor; a period summary doesn't, so it never swallows emails the next daily digest needs.
    A period summary gets its slot's date: caught up a day late, 'this-week' must still mean the slot's week."""
    if scope == "new":
        return ["run", "--send", "--quiet", "--commit"]
    return ["run", "--send", "--quiet", "--digest", scope] + (["--as-of", at.date().isoformat()] if at else [])
```

And in `digest_set`: `today = as_of or datetime.now(tz).date()`. The new flag uses `type=date.fromisoformat`, so argparse rejects a bad date for you.

Why this fix: the child process can't know when its slot was. Passing the fact explicitly is simpler and more testable than having the child guess from the schedule. The `new` scope doesn't get `--as-of`, because "new" means "since the cursor", not a calendar period.

**Lesson.** A job that runs late must be told when it was meant to run. "Now" is the wrong default for catch-up work.

**Test:** `tests/test_service.py::test_run_args_commit_only_for_new`. The follow-up fix is `0031b03` below.

### A slot that succeeded before a retry is not run twice (`fb85d32`)

**How it was found.** Core pipeline review, item 6, reproduced by running the real `_serve` loop with a patched clock and fake child runs. With two slots due (`new` and `this-week`), `new` failed and `this-week` succeeded. On the retry, only `new` was left, so `last_done` was set to the `new` slot's time, which was earlier. On the next tick, `this-week` was due again and the weekly digest was sent twice. The recorded runs were `new, this-week, new, this-week`.

**How it was fixed.** One line: include the slots that already succeeded when computing `last_done`.

```diff
-                    state["last_done"] = max(at for at, _ in due).isoformat()
+                    # done_now too: `due` holds only what was left for this attempt, and a slot that already
+                    # succeeded on an earlier attempt may be the latest one (else it would fire again)
+                    state["last_done"] = max(at for at, _ in [*due, *done_now]).isoformat()
```

Why this fix: `last_done` means "every slot up to here is handled". It has to be the maximum over everything handled in this round, not only what the last attempt touched. The smallest correct change was to widen the set the `max` looks at.

**Lesson.** When a loop shrinks its work list on each retry, any summary computed from that list must include what was already done.

**Test:** `tests/test_service_retry.py::test_retry_does_not_repeat_a_successful_later_slot` (added in `ed5fc81`).

### Scheduled runs stay on local time across a DST change (`53dfa47`)

**How it was found.** Core pipeline review, item 7, reproduced with Europe/London dates. `last_done` is stored as ISO text, so when it is read back it carries a fixed offset like `+01:00`, not the time zone. `_slots` built the day's slot times with `start.tzinfo`, so after the clocks went back every run fired an hour early, forever. The reviewer noted the author's own zone has no DST, so it didn't show up in daily use.

**How it was fixed.**

```diff
-    start = max(last_done, now - timedelta(days=LOOKBACK_DAYS))
+    # In now's zone: last_done comes from ISO text with a fixed offset, which is an hour out after a clock change.
+    start = max(last_done, now - timedelta(days=LOOKBACK_DAYS)).astimezone(now.tzinfo)
```

How it works: `now` carries a real `ZoneInfo`. `.astimezone(now.tzinfo)` turns the fixed-offset time into the same instant in that zone, so every slot built from `start` uses the right offset for its own date.

Why this fix: storing the zone name next to `last_done` would also work, but it changes the state file. Converting at the one place where slots are built fixes old state files too.

**Lesson.** A fixed UTC offset is not a time zone. Do date arithmetic in a real zone (`ZoneInfo`).

**Test:** `tests/test_service.py::test_due_slots_survive_a_clock_change`.

### An impossible deadline no longer breaks "what's coming up" questions (`f9efd88`)

**How it was found.** Security and I/O review, bug 1, reproduced. The classifier accepted any `YYYY-MM-DD` shape as a deadline, so `2026-02-30` was archived. Later, `answer._day()` called `date.fromisoformat` without a `try` and raised `ValueError: day is out of range for month`. Every chat question that looked at events then failed until that email aged out. A model slip or a crafted email could cause it.

**How it was fixed.** Two layers. The classifier now runs the deadline through the existing `_date` helper, which already parsed real dates for events:

```python
# mailbrief/ai/classifier.py::_date
def _date(value, received: date | None) -> str | None:
    """A YYYY-MM-DD within a year of the email (catches a wrong year), else None."""
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return None
    try:
        d = date.fromisoformat(value)
    except ValueError:
        return None
    return value if received is None or abs((d - received).days) <= 366 else None
```

And the reader got the same guard, because old archives may already hold bad values:

```python
# after
def _day(value) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) and _DATE.fullmatch(value) else None
    except ValueError:  # the right shape but not a day ("2026-02-30"), from the model or an older archive
        return None
```

Why this fix: a regex checks shape, not meaning. Reuse of `_date` meant one definition of "a valid date" for both events and deadlines. Fixing only the writer would leave existing bad data crashing the reader; fixing only the reader would keep storing junk. Both were cheap.

**Lesson.** Validate at the boundary where data comes in, and still read defensively, because old data was written by old code.

**Test:** `tests/test_ai.py::test_deadline_must_be_a_real_day` and `tests/test_answer.py::test_impossible_dates_never_raise`.

### A missing key no longer kills the chat listener silently (`0f0ac8b`)

**How it was found.** Flagged by two passes. The security and I/O review (bug 2) and the UI/UX review (broken item 9) both traced it: `crypto._fernet()` and the AI client raised `SystemExit` when a key was missing. In the CLI that is fine. But the bot runs in a thread, its handlers catch only `Exception`, and `SystemExit` is not an `Exception`. Python's `threading` ends a thread on `SystemExit` without logging anything. So the first chat question with a missing key killed the listener: no reply, no log line.

**How it was fixed.** A new exception class for configuration problems, raised by library code instead of `SystemExit`.

```python
# mailbrief/__init__.py::ConfigError
class ConfigError(Exception):
    """A setting is missing or wrong (.env). Library code raises this, never SystemExit: a SystemExit in the chat
    listener's thread would end that thread silently. `main()` turns it into a one-line message."""
```

Each caller decides what to do with it. `main()` prints it as one line (`sys.exit(str(e))`). The bot replies with it. The classification loop re-raises it, because with no key every call would fail the same way and marking all emails Unclassified would be wrong:

```python
# after
            except ConfigError:  # no AI key: every call would fail the same way, so stop the run
                raise
            except Exception as ex:  # noqa: BLE001 - one bad call must not sink the run; retried next run
```

```python
# after
        except ConfigError as e:  # a missing key in .env: only you can fix it, so say which
            _log("failed (setup)")
            self.say(chat_id, f"MailBrief isn't set up for that: {e}")
```

Why this fix: `SystemExit` means "stop the whole program", which is a decision only the program's entry point should make. Catching `BaseException` in the bot was the other option, but it would also swallow Ctrl+C. A named exception keeps the message and lets each layer choose.

**Lesson.** Library code raises exceptions; only `main()` decides to exit.

**Test:** `tests/test_bot.py::test_commands_and_errors` (the "a question with no key" part).

### `serve` tells you on Telegram when it gives up on a run (`12ea8cf`)

**How it was found.** UI/UX review, broken item 2. After three failed attempts `serve` only wrote "giving up" to its log. It sent a Telegram alert only for an expired login. On the phone, a broken install, a failed run and a quiet day all looked the same: silence.

**How it was fixed.** The once-a-day login alert was generalised into `_alert(state, key, text)`, and a second kind was added.

```python
# after
def _alert(state: dict, key: str, text: str) -> None:
    """Tell the destinations something only you can fix, at most once a day per kind (`key` in schedule.json)."""
    today = datetime.now(_tz()).date().isoformat()
    if state.get(key) == today:
        return
    from mailbrief.main import deliver

    out = io.StringIO()
    try:
        if deliver(text, out):
            state[key] = today
    except Exception as e:  # noqa: BLE001 - an alert that can't be sent must never stop the service
        log(f"alert not sent ({type(e).__name__})")
    # ...


def _alert_failed(state: dict, result: str) -> None:
    """A slot was given up on: without this, a broken install looks exactly like a day with no mail."""
    _alert(state, "fail_alert_day", f"⚠️ MailBrief: the scheduled run failed {MAX_ATTEMPTS} times ({result}), so there's "
           "no digest this time. On the machine it runs on: `mailbrief status`, then the log file it names.")
```

How it works: each alert kind has its own key in `schedule.json` holding the last day it was sent, so a login alert doesn't block a failure alert. The day is only recorded if delivery worked, so a failed alert tries again next time. Any error inside is logged and swallowed: the alert is a side channel and must not take down the service.

Why this fix: one helper with a key per kind avoids copying the rate-limit logic. Once a day is enough to be noticed without spamming the phone on every retry.

**Lesson.** An unattended service must report failure on the same channel it reports success, or failure looks like silence.

**Test:** none added. `_alert_failed` is called from the `_serve` loop; the retry loop itself is covered by `tests/test_service_retry.py`.

### A damaged search index is rebuilt instead of breaking chat (`5a52977`)

**How it was found.** Security and I/O review, bug 3, reproduced with a temp file. `index.update()` called `load()` before it looked at `rebuild`, so `index rebuild` failed on the very file it was meant to replace. And `search()` raised `InvalidToken` on a damaged or wrong-key file, so every chat question failed until someone deleted `data/index.enc` by hand.

**How it was fixed.** The index is derived data (it can be rebuilt from the archive), so an unreadable one is treated as empty.

```python
# after
        fresh = {"model": _model(), "updated": None, "items": {}}
        try:  # derived data: an index that won't open (key changed, file damaged) is rebuilt, not fatal
            data = fresh if rebuild else load(path)
        except Exception as e:  # noqa: BLE001
            if log:
                print(f"warning: the search index couldn't be read ({type(e).__name__}); rebuilding it", file=log)
            data = fresh
```

And in `search()`, an unreadable index gives `items = {}`, so the keyword half of the hybrid search still answers.

Why this fix: `fresh if rebuild else load(path)` skips the load entirely when you ask for a rebuild, which is the actual bug. Swallowing errors broadly is usually bad, but here the data can be recreated and the warning is printed. The archive, which can't be recreated, keeps its strict error handling.

**Lesson.** Be strict with source data and forgiving with derived data you can rebuild.

**Test:** `tests/test_index.py::test_damaged_index_is_rebuilt_and_search_still_answers`.

### File saves survive a briefly locked file on Windows (`50e47e5`)

**How it was found.** Core pipeline review, item 8. The reviewer reproduced the mechanism on Windows: open a file for reading, then `os.replace` onto it, and you get `PermissionError [WinError 5]`. Readers include `mailbrief emails`, the chat, Defender and the search indexer. For the archive this hit the cursor bug above. For `schedule.json` inside the `serve` loop there was no guard, so it crashed the service.

**How it was fixed.** One shared helper, used by every atomic write (archive, cursor, index, rules, session, schedule).

```python
# mailbrief/storage/files.py::replace
def replace(tmp: Path, path: Path, tries: int = 15, wait: float = 0.2) -> None:
    """os.replace, retried: on Windows it fails with PermissionError while another process has `path` open
    (`mailbrief emails` or the chat reading a month, a virus scanner, the search indexer). Those reads last
    milliseconds, so a short wait gets through; after ~3 s the error is real and is raised."""
    for n in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if n == tries - 1:
                raise
            time.sleep(wait)
```

How it works: try up to 15 times, 0.2 s apart. Only `PermissionError` is retried; anything else (a missing folder, a full disk) fails at once. On the last try the error is re-raised, so a file that stays locked is still reported. `save_state` in `service.py` also wraps its write in `try/except OSError` and logs, because `schedule.json` is bookkeeping and must never stop `serve`.

Why this fix: the readers hold the file for milliseconds, so a short retry is enough. File locking across processes would be heavier and still wouldn't cover the virus scanner. Putting it in one helper fixed all six writers at once.

**Lesson.** On Windows, "atomic replace" can fail while anyone has the file open. Retry briefly, and fix it once in a shared helper.

**Test:** `tests/test_files.py::test_replace_waits_out_a_file_another_process_has_open`.

### Ctrl+C during classification stops the queued AI calls (`9ccda8b`)

**How it was found.** Core pipeline review, item 9, reproduced: 40 of 40 queued jobs still ran after the interrupt. Leaving a `with ThreadPoolExecutor(...)` block calls `shutdown(wait=True)`, which waits for every queued job. So Ctrl+C on a 1000-email backfill still made every AI call and then threw the results away.

**How it was fixed.**

```python
# after
        except BaseException:  # Ctrl+C, or no AI key: don't let the queued conversations call the AI anyway
            ex.shutdown(wait=False, cancel_futures=True)
            if backfill and pending:  # keep what was classified since the last save
                archive.save(pending, [e["classification"] for e in pending], None, plain, tz)
            raise
```

How it works: `cancel_futures=True` (Python 3.9+) drops every job that hasn't started. Jobs already running finish on their own. A backfill saves what it has, then the exception carries on up, so Ctrl+C still stops the program.

Why this fix: catching `BaseException` here is right because the handler always re-raises. It is cleanup, not swallowing. The standard library already had the needed switch.

**Lesson.** A `with` block's exit can do a lot of work. Know what your context manager does on the way out when an exception passes through.

**Test:** none added.

### List-preview records are no longer saved to the archive (`e824841`)

**How it was found.** Core pipeline review, item 10. When Outlook's `GetItem` call failed, the run fell back to list previews, keyed by conversation id and holding only preview text. Those were archived for good. The real emails have different ids, so they never replaced the previews, and digests, events and listings showed the conversation twice. The reviewer pointed out that `labels_for` already special-cased previews, a sign the problem was known but patched in one place only.

**How it was fixed.** Only full-text records are saved, both in the final save and in the backfill's periodic saves (`full_text` guards those).

```python
# after
        # List previews (GetItem failed) are not saved: they're keyed by conversation, so the real emails
        # would never replace them and every later view would show the conversation twice.
        keep = [r for r in records if r.get("body_source") == "getitem"]
        paths = archive.save(keep, [r["classification"] for r in keep], None, plain, tz)
```

Why this fix: previews are a fallback for one digest, not data worth keeping. Not saving them is simpler than saving them and cleaning them up later. The cursor already refuses to advance on a preview run (exit 4), so the emails are read again properly next time.

**Lesson.** Don't store a stand-in record under a different key from the real one; nothing will ever replace it.

**Test:** `tests/test_pipeline.py::test_previews_are_not_archived_and_cannot_advance_cursor`.

### `labels retag` reports AI failures instead of hiding them (`226ba3a`)

**How it was found.** Core pipeline review, item 11, traced. The retag loop used `as_completed` but never called `future.result()`. A future that raised kept its exception to itself, so with the endpoint down retag printed "Re-tagged 0 of 40 email(s)." and nothing else.

**How it was fixed.**

```python
# after
            for future in as_completed([ex.submit(one, e) for e in targets]):
                try:
                    future.result()
                except ConfigError:  # no AI key: nothing will work, say so once
                    ex.shutdown(wait=False, cancel_futures=True)
                    raise
                except Exception as e:  # noqa: BLE001 - one failed call keeps that email's old classification
                    failed, why = failed + 1, f"{type(e).__name__}: {e}"
                done += 1
                progress.count("Re-tagging", done, len(targets))
        if failed:
            print(f"warning: the AI failed for {failed} email(s), which keep their old classification (last error: {why})")
```

Why this fix: `future.result()` is the only way to see a worker's exception. Counting failures and showing the last error gives one useful line instead of 40 repeated ones. A missing key stops everything, as in the run.

**Lesson.** An exception in a thread pool is invisible until you call `.result()`. Always read your futures.

**Test:** none added.

### Long HTML lines are cut between links, not inside them (`67ce2dc`)

**How it was found.** Security and I/O review, bug 4, reproduced: a 199-reference one-line answer became three messages, two with an unbalanced `<a>`. The hard cut for an overlong line counted raw characters, so it could split an `<a href…>` tag or an `&amp;` entity. Telegram rejected the HTML, and the plain-text fallback showed the broken tag.

**How it was fixed.** In HTML mode the line is cut into "atoms" first, and cuts only fall between atoms.

```python
# after
# What an HTML line may be cut between: a whole link, any other tag, an entity (&amp;), or one character.
_HTML_ATOM = re.compile(r"<a\b[^>]*>.*?</a>|<[^>]+>|&[#\w]{1,10};|.", re.S)


def _hard_cut(line: str, limit: int, measure=size) -> list[str]:
    # ...
    pieces, current = [], ""
    for atom in _HTML_ATOM.findall(line) if measure is html_size else line:
        if current and measure(current + atom) > limit:
            pieces.append(current)
            current = ""
        current += atom
    return pieces + ([current] if current else [])
```

How it works: the regex tries a whole link first, then any tag, then an entity, then falls back to one character (`.`). `findall` returns those pieces in order, so a link is never in two pieces. The `measure` argument is passed through, so HTML is measured by its visible size (`html_size`), plain text by `size`. The `if current and` guard stops an empty first piece when a single atom is already over the limit.

Why this fix: a full HTML parser would be overkill for the three tag shapes the app itself writes. The regex covers exactly what `links.to_html` produces.

**Lesson.** When you split structured text, split on the structure's boundaries, not on raw characters.

**Test:** `tests/test_telegram.py::test_html_hard_cut_never_splits_a_link_or_an_entity`.

### A string `action_items` is one item, not a list of letters (`e4b2a7f`)

**How it was found.** Security and I/O review, bug 5. When the model returned `"action_items": "Reply to Bob"` instead of a list, `[str(a) for a in ...]` iterated over the string and stored `['R', 'e', 'p', ...]`.

**How it was fixed.**

```python
# after
def _strings(value) -> list[str]:
    """A list of strings from what should be one: a bare string is one item, not a list of its letters."""
    items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return [str(a).strip() for a in items if a and str(a).strip()]
```

Why this fix: in Python a `str` is iterable, so any code that expects "a list" will quietly accept a string and loop over its characters. The fix checks the type first and drops empty or blank items. A dict or number becomes `[]`.

**Lesson.** Model output is untrusted input. Check its type, and remember that strings are iterable.

**Test:** `tests/test_ai.py::test_action_items_as_a_bare_string`.

### Digest batches are ordered by time, not by weekday name (`8832c83`)

**How it was found.** Security and I/O review, bug 6, reproduced. Large digests sort emails before splitting them into batches. The key was `(i["thread"], i["received"])`, both strings. `received` is formatted like `"Fri 06 Mar 09:00"`, so Friday sorted before Monday, and thread labels sorted as `t1, t10, t2`.

**How it was fixed.**

```diff
-        # Time order keeps a thread's emails (and related ones) in the same batch.
-        items.sort(key=lambda i: (i["thread"], i["received"]))
+        # Threads in the order they started, each thread's emails in time order, so a conversation stays in
+        # one batch. By number, not by text: "t10" sorts before "t2", and "Fri 06 Mar" before "Mon 02 Mar".
+        # (ref order is time order: callers pass the emails oldest first.)
+        items.sort(key=lambda i: (int(i["thread"][1:]), i["ref"]))
```

How it works: `int(i["thread"][1:])` turns `"t10"` into `10`. `ref` is the email's number in the digest, and callers pass emails oldest first, so sorting by `ref` is sorting by time.

Why this fix: the right values were already on each item, just not as the sort key. No new field was needed.

**Lesson.** Never sort by a display string. Sort by the number or the datetime it was made from.

**Test:** `tests/test_ai.py::test_digest_batches_keep_threads_together_in_time_order`.

### `/events` with a non-ASCII digit no longer fails (`fdd9ae4`)

**How it was found.** Security and I/O review, bug 11. `"²".isdigit()` is `True`, but `int("²")` raises, so `/events ²` answered "Sorry, that failed".

**How it was fixed.** `rest.isascii() and rest.isdigit()` before calling `int`. (`d27f1cd` later replaced the silent fallback with a usage reply; see the documentation entry.)

**Lesson.** `str.isdigit()` accepts more than 0 to 9. Pair it with `isascii()`, or just `try: int(...)`.

**Test:** `tests/test_bot.py::test_commands_and_errors` (the `/events ²` message).

### The AI client retries dropped connections and caps waits (`2fcf11f`)

**How it was found.** Security and I/O review, bugs 9 and 10, from reading `mailbrief/ai/client.py`. Three problems: a reset or closed connection (`ConnectionResetError`, `RemoteDisconnected`) is not a `URLError`, so it failed the call at once instead of being retried. A `Retry-After` header was obeyed with no limit, so one header could make the run sleep for an hour while holding the run lock. And a 200 reply without `choices` raised a bare `KeyError`.

**How it was fixed.**

```python
# after
MAX_WAIT_S = 120  # the longest a Retry-After is obeyed: a run holds the run lock while it waits
# No answer: a timeout, a refused or reset connection, or a reply cut off half way.
NO_ANSWER = (TimeoutError, urllib.error.URLError, ConnectionError, http.client.HTTPException)
```

```diff
-            wait = int(retry_after) if retry_after.isdigit() else min(60, 3 * 2**busy)
+            wait = min(MAX_WAIT_S, int(retry_after)) if retry_after.isdigit() else min(60, 3 * 2**busy)
```

```python
# after
    try:
        text = data["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError, AttributeError):  # a 200 that isn't a completion ({"error": …})
        text = ""  # an empty reply: callers already retry or fall back on those
```

Why this fix: naming the tuple `NO_ANSWER` once means both retry sites (the fallback path and `_post`) agree on what "no answer" is. `ConnectionError` is the base class of reset, refused and aborted connections; `http.client.HTTPException` covers replies cut off halfway. A malformed reply becomes an empty one because callers already handle empty answers.

**Lesson.** List the failures you retry in one named place, and put a ceiling on any wait a server can ask for.

**Test:** `tests/test_ai_client.py::test_dropped_connections_are_retried_and_waits_are_capped`.

### A sign-in page on another host counts as an expired session (`0fbb017`)

**How it was found.** Flagged by the security and I/O review (bug 7, "likely") and the UI/UX review (CLI item 8). `open_outlook` only recognised two Microsoft login hosts. If Outlook sent the browser to an organisation's own sign-in page or a "stay signed in?" screen, the loop waited 60 s, found no message list, and printed "Signed in" anyway. The run then saw an empty inbox instead of asking for a new login.

**How it was fixed.**

```python
# after
    host = urlparse(page.url).hostname or ""
    if not loaded and not host.startswith("outlook."):
        # Parked somewhere that isn't Outlook: an organisation's own sign-in page, a consent or "stay signed in?"
        # screen. That is a sign-in to finish, not an empty inbox.
        progress.step("Session expired (Outlook sent the browser to a sign-in page)")
        return {"expired": True, "auth": auth, "startup": []}
    progress.step("Signed in" if loaded else f"Outlook opened, but no message list after {timeout_s}s (slow network, or an empty inbox)")
```

Why this fix: you can't list every sign-in host in the world, but you can tell whether you are still on Outlook. An allow-list of the place you want to be is more robust than a block-list of places you don't. The message also stops claiming "Signed in" when the list never appeared.

**Lesson.** Check for the state you expect, not for a list of known bad states.

**Test:** none added (`outlook_reader.py` drives a real browser and has no unit tests).

### Telegram updates are confirmed before they are acted on (`d44e871`)

**How it was found.** Security and I/O review, bug 8, from Telegram's documented behaviour. The bot kept the update offset in memory, and Telegram only forgets a batch when the next `getUpdates` names a higher offset. So restarting `serve` right after a `/sync`, `/login` or `/rule add` ran it again on the next start.

**How it was fixed.**

```python
# after
        if updates:
            # Tell Telegram these are taken BEFORE acting on them. It only forgets a batch when the next call
            # names a higher offset, so a restart right after /sync or /login would otherwise run them again.
            self.offset = updates[-1]["update_id"] + 1
            try:
                self.api("getUpdates", {"offset": self.offset, "timeout": 0, "limit": 1,
                                        "allowed_updates": payload["allowed_updates"]})
            except Exception:  # noqa: BLE001 - the next poll confirms them anyway
                pass
```

How it works: a quick `getUpdates` with `timeout: 0` and the new offset tells Telegram the batch is consumed. If that call fails, nothing is lost: the next long poll confirms them anyway.

Why this fix: this is "at most once" delivery. For commands with side effects (start a run, send a sign-in link), losing one message on a crash is better than running it twice. Saving the offset to disk was the alternative, but it adds a file and still has a crash window.

**Lesson.** Decide whether a message may be handled twice or not at all, and acknowledge it at the matching moment.

**Test:** `tests/test_bot.py::test_only_your_private_chats` (asserts the batch is confirmed with offset 5).

### A caught-up digest stops at its scheduled day (`0031b03`)

**How it was found.** In the follow-up session, while re-checking the `ae7c427` fix. The thread records: "I also found a gap in the weekly catch-up fix: it could include mail received after the missed slot's day." Counting the week from the slot's date was right, but the period ran to the end of that week, so a Sunday slot caught up on Wednesday would include Monday-to-Wednesday mail.

**How it was fixed.** When `as_of` is given, mail received after that day is excluded.

```diff
-            if scope == "all" or archive.in_period(e, scope, today, tz)
+            if (scope == "all" or archive.in_period(e, scope, today, tz))
+            and (as_of is None or e["received_at"].astimezone(tz).date() <= today)
```

Why this fix: `as_of` means "pretend today is this day", and on that day later mail didn't exist yet. The extra condition makes that true. `.astimezone(tz).date()` compares local days, not UTC days.

**Lesson.** When you fix a bug, check the edges of the fix too. "Count from this day" usually also means "nothing after this day".

**Test:** `tests/test_main.py::test_caught_up_digest_excludes_mail_after_the_slot_day`.

### AI retry messages go to stderr, so `--json` stays valid (`fdcbab9`)

**How it was found.** In the follow-up session, after `8cb732e` made `run --json` print valid JSON. The thread shows the edit, not a separate write-up. The AI client printed its retry and fallback notes ("AI: busy (429), retrying in 6s") with a plain `print`, which goes to stdout. In `--json` mode that text landed in the middle of the JSON.

**How it was fixed.** The three diagnostic `print` calls in `mailbrief/ai/client.py` now pass `file=sys.stderr`.

```diff
-            print(f"AI: busy ({e.code}), retrying in {wait}s ({busy}/{RETRIES})", flush=True)
+            print(f"AI: busy ({e.code}), retrying in {wait}s ({busy}/{RETRIES})", file=sys.stderr, flush=True)
```

Why this fix: stdout is for the program's result; stderr is for messages about how it is going. Pipes only carry stdout, so diagnostics on stderr still show on screen but never break `run --json | python -m json.tool`.

**Lesson.** Results to stdout, everything else to stderr, in every module, not just the one that writes JSON.

**Test:** `tests/test_ai_client.py::test_retry_messages_leave_json_stdout_clean`.

---

## Security

### The sign-in server drops silent connections after 10 s (`b8c8f41`)

**How it was found.** Security and I/O review, security finding 1, confirmed on loopback. `BaseHTTPRequestHandler.timeout` defaults to `None`, so a connection that sends half a request waits forever, and `ThreadingHTTPServer` starts one thread per connection with no cap. 50 idle connections held 50 threads, and they outlived `server.shutdown()`. On a host where the port stays open (`LOGIN_PAGE=always`), any scanner could exhaust the `serve` process.

**How it was fixed.**

```python
# after
    class Handler(BaseHTTPRequestHandler):
        # Seconds a connection may sit silent (stdlib default: forever). Without it anyone could open idle
        # connections, or send half a request, and pin a thread and a socket each until `serve` ran out.
        timeout = 10
```

How it works: the stdlib applies `timeout` to the socket before reading, so both the request line and `rfile.read` of the body give up after 10 s of silence.

Why this fix: one class attribute, from the standard library, closes the hole. A connection cap would also help but needs more code; the timeout alone stops connections from piling up.

**Lesson.** Check the defaults of any server you expose. "Wait forever" is a common default and a denial-of-service hole.

**Test:** `tests/test_remote_login.py::test_a_silent_connection_is_dropped`.

### `LOGIN_PAGE=always` never serves plain http to the network (`0f90473`)

**How it was found.** Security and I/O review, security finding 3, from reading `start_always`. With `LOGIN_PAGE=always` and no https `PUBLIC_URL`, the page's address was `http://localhost`, which passed the "https unless local" check, yet the server bound `0.0.0.0`. So the Microsoft password typed into the page could cross the network in cleartext.

**How it was fixed.**

```python
# after
def always_bind() -> str:
    """Where the always-on server listens: every interface only when the page's address is https (a proxy or
    the host's own TLS in front). With no PUBLIC_URL the page is plain http://localhost, so this machine only:
    on 0.0.0.0 your password would cross the network unencrypted. Refuses a plain-http public address."""
    return "127.0.0.1" if is_local(public_url()) else "0.0.0.0"
```

How it works: `is_local` returns true for a localhost address and raises `ValueError` for a plain-http public address, so the same call both chooses the bind address and refuses the unsafe setup.

Why this fix: the bind address now follows from the same fact as the URL check. Before, the two were decided separately and could disagree.

**Lesson.** Derive "where do I listen" and "what address do I advertise" from one setting, so they can't contradict each other.

**Test:** `tests/test_remote_login.py::test_render_address_and_switch`.

### A linked-image download has a total time limit (`981bbf1`)

**How it was found.** Security and I/O review, security finding 2, from urllib's documented behaviour (not reproduced over a network). `timeout=10` applies to each socket read, not the whole download. An image host sending a few bytes every 9 s could hold a run, and the run lock, for days.

**How it was fixed.** A chunked read with a deadline on the whole download.

```python
# mailbrief/web_images.py::_read
def _read(stream, limit: int, total_s: float = TOTAL_S, clock=time.monotonic) -> bytes:
    """Up to `limit` bytes, giving up (TimeoutError) once the whole download has taken total_s. The socket
    timeout alone only bounds each read, so a slow drip could hold a run, and the run lock, for days."""
    deadline, data = clock() + total_s, b""
    read = getattr(stream, "read1", None) or stream.read  # read1: whatever has arrived, not "block until 64 KB have"
    while len(data) < limit:
        if clock() > deadline:
            raise TimeoutError("image download took too long")
        chunk = read(min(65536, limit - len(data)))
        if not chunk:
            break
        data += chunk
    return data
```

How it works: `time.monotonic()` is used because it never jumps when the system clock changes. `read1` returns whatever bytes have arrived, so the deadline is checked often; plain `read(65536)` would block until 64 KB came. The size cap (`limit`) still holds. `clock` is a parameter so the test can fake time instead of waiting 20 s.

Why this fix: the socket timeout handles a server that goes quiet; the total deadline handles one that drips. You need both.

**Lesson.** A per-read timeout is not a per-operation timeout. Bound the whole operation by a monotonic deadline.

**Test:** `tests/test_web_images.py::test_a_dripping_server_is_given_up_on`.

### IPv6 addresses that wrap a private IPv4 are refused (`170dc4b`)

**How it was found.** Security and I/O review, security finding 4, confirmed on Python 3.11. The image downloader refused private addresses with `ip.is_global`. But `is_global` is `True` for `64:ff9b::7f00:1` (NAT64 for 127.0.0.1) and for `::127.0.0.1`. On an IPv6 network with NAT64, a linked image could reach this machine or the local network. The reviewer rated it low, since https and certificate checks limit it further.

**How it was fixed.** IPv6 forms that carry an IPv4 address are judged by that inner address.

```python
# mailbrief/web_images.py::_public
def _public(address: str) -> bool:
    """A public internet address: not private, loopback, link-local, reserved, CGNAT or multicast, and not an
    IPv6 form that carries one of those IPv4 addresses inside it (which is_global alone lets through)."""
    ip = ipaddress.ip_address(address.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address):
        inner = ip.ipv4_mapped or ip.sixtofour  # ::ffff:a.b.c.d, 2002:AABB:CCDD::
        if inner is None and (ip in _NAT64 or int(ip) >> 32 == 0):  # 64:ff9b::a.b.c.d (NAT64), ::a.b.c.d
            inner = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if inner is not None:
            return inner.is_global and not inner.is_multicast
    return ip.is_global and not ip.is_multicast
```

How it works: `split("%")[0]` drops a zone id like `%eth0`. The standard library already extracts two embedded forms (`ipv4_mapped`, `sixtofour`). For NAT64 and the old "IPv4-compatible" form, the last 32 bits are the IPv4 address, so `int(ip) & 0xFFFFFFFF` pulls them out. `int(ip) >> 32 == 0` means the top 96 bits are zero. The `isinstance` check (from the later types commit) lets mypy know `ipv4_mapped` exists.

Why this fix: it keeps the existing rule ("only public addresses") and applies it to the address that would really be reached. The reviewer's other option, connecting over IPv4 only, would break IPv6-only image hosts.

**Lesson.** Address checks must look through encodings. An IP can hide inside another IP.

**Test:** `tests/test_web_images.py::test_allowed_only_public_https`.

### A remote sign-in is checked before it replaces the saved one (`ae2d7a1`)

**How it was found.** Security and I/O review, security finding 7 ("likely, low"). The remote sign-in wrote the new session to `data/session.enc` and only then tested it. A sign-in that didn't work destroyed a session that did. Nothing compared the signed-in account with the previous one, so signing in as a different account would silently switch which mailbox MailBrief read and labelled.

**How it was fixed.** The check now uses the in-memory session, and the save happens only if it passes. Runs also record which address the session belongs to.

```python
# after
                        # Checked from memory first: a sign-in that doesn't work must not replace a saved one that does.
                        check = browser.new_context(storage_state=context.storage_state(), user_agent=ua)
                        cp = check.new_page()  # open_outlook alone can't tell "stuck on a sign-in page" from "slow"
                        opened = open_outlook(cp)
                        ok = not opened["expired"] and cp.locator(MESSAGE_ROW).count() > 0
                        check.close()
                        if ok:
                            me, before = find_user_email(opened["startup"]), manager.account()
                            manager.save(context, ua, me)
                            other = me if before and me and before.lower() != me.lower() else None
```

How it works: Playwright's `context.storage_state()` returns the cookies as a dict, so a second browser context can be opened from it without touching the disk. Only when Outlook really shows the message list is the session saved. If the saved account and the new one differ (compared case-insensitively), the user gets a warning in Telegram.

Why this fix: "verify, then commit" is the standard pattern for replacing anything you can't easily get back. Warning on a different account, rather than refusing, keeps a deliberate switch possible.

**Lesson.** Test a replacement before it overwrites the working original.

**Test:** none added. `manager.account()` and the remote-login flow need a real browser.

### The write guard only allows the one category operation used (`bee2872`)

**How it was found.** Security and I/O review, security finding 8, from reading `check_request` in `mailbrief/browser/owa_network.py`. `ApplyCategoryOperation` was checked by category name alone. MailBrief only ever sends `Action: 1` (remove a category from every email), but any other action on an `MB:` category would have passed.

**How it was fixed.**

```python
# after
        op = (body.get("request") or {}).get("categoryOperation") or {}
        # Action 1 (remove from every email) is the only operation MailBrief ever sends; the others
        # aren't known to be harmless, so they don't pass just because the name is ours.
        if op.get("Action") != 1 or set(op) - {"Action", "CategoryName"} or not str(op.get("CategoryName", "")).startswith(PREFIX):
            raise UnsafeRequest("only MailBrief (\"MB: \") categories can be removed everywhere")
```

How it works: three conditions, any of which refuses. The action must be exactly 1. `set(op) - {"Action", "CategoryName"}` is non-empty if any extra field is present. The name must start with `MB: `.

Why this fix: a guard should describe exactly what the app does and refuse everything else. Allowing "anything with our name on it" trusts operations nobody has tested.

**Lesson.** Write security checks as allow-lists of the exact requests you send.

**Test:** `tests/test_labels.py::test_guard_refuses_everything_else`.

### The sign-in server no longer identifies itself (`186274c`)

**How it was found.** Security and I/O review, security finding 11, confirmed. Every reply carried `Server: BaseHTTP/0.6 Python/3.11.x`, and PUT, OPTIONS or a malformed request got the stdlib's HTML error page. That contradicted the teaching notes, which said the server says nothing about itself.

**How it was fixed.**

```python
# after
        def version_string(self) -> str:  # the Server header: don't name the software or the Python version
            return "web"

        def send_error(self, code, message=None, explain=None):  # the stdlib's HTML error pages name it too
            try:
                self._nope()
            except OSError:  # the client already hung up
                pass
            self.close_connection = True

        do_HEAD = do_PUT = do_DELETE = do_OPTIONS = do_PATCH = lambda self: self._nope()
```

How it works: `BaseHTTPRequestHandler` builds the `Server` header from `version_string()` and calls `send_error()` for bad requests and unknown methods. Overriding both routes everything to the same bare 404 the server already used. The stdlib looks up `do_<METHOD>`, so defining those methods gives the same 404 instead of a 501.

Why this fix: hiding the version doesn't make the server safe, but it stops a scanner from matching it to known bugs, and it makes the docs true.

**Lesson.** Override the framework's defaults that leak details, and make every refusal look the same.

**Test:** `tests/test_remote_login.py::test_the_server_says_nothing_about_itself`.

---

## User experience

### A missing or placeholder encryption key is explained before login (`94e1eef`)

**How it was found.** UI/UX review, broken item 1. `.env.example` shipped `SESSION_ENCRYPTION_KEY=...`. Copied as is, `Fernet("...")` raised `ValueError` with a traceback, and only after the user had typed their password, done MFA and pressed Enter. The sign-in was lost.

**How it was fixed.** The key is checked before the browser opens, and both error cases say how to make a key.

```python
# after
def _fernet() -> Fernet:
    key = (os.environ.get("SESSION_ENCRYPTION_KEY") or "").strip()
    if not key:
        raise ConfigError(f"SESSION_ENCRYPTION_KEY is not set. Make one and put it in .env:\n  {MAKE_KEY}")
    try:
        return Fernet(key)
    except ValueError:  # not 32 url-safe base64 bytes: a placeholder ("...") or a mangled paste
        raise ConfigError(f"SESSION_ENCRYPTION_KEY in .env isn't a valid key. Make one and paste it in whole:\n  {MAKE_KEY}") from None


def check_key() -> None:
    """Raise ConfigError now if the key is missing or malformed (before a sign-in is spent on it)."""
    _fernet()
```

`login_once()` calls `check_key()` first. `.env.example` now leaves the line empty. `from None` hides the inner `ValueError`, because the message already says everything.

**Lesson.** Check configuration before the expensive or human step, not after it.

**Test:** `tests/test_files.py::test_a_missing_or_placeholder_key_is_explained`.

### The first-time recipe sends a digest before the backfill (`f423d59`)

**How it was found.** UI/UX review, broken item 3. The documented first-time order in `commands.md` ran `--backfill` first. Backfill advances the cursor, so the first `run --send --commit` found nothing new and Telegram stayed silent.

**How it was fixed.** Docs only: the recipe is now `login`, `add-destination`, `run --send --commit` (first digest), then the optional `--backfill` and `index rebuild`, with one line explaining why the order matters.

**Lesson.** Walk through your own setup steps as a new user, in the documented order.

**Test:** none (documentation).

### `/sync` says so when there is no new mail (`e126843`)

**How it was found.** UI/UX review, broken item 4. `/sync` promised "The digest arrives here if there's anything new" and then, on a quiet inbox, sent nothing. Exit 0 meant both "digest sent" and "nothing new", so the bot couldn't tell which.

**How it was fixed.** The bot notes the time of the newest saved digest before the run and compares after it.

```python
# after
                before = _last_digest()
                code = (self.run_sync or run_sync)()
                # Exit 0 covers "digest sent" and "nothing new": only the second needs a word from here.
                quiet = "✅ No new mail since the last check." if _last_digest() == before else None
```

`_last_digest()` returns `None` if it can't tell, and then the bot says nothing rather than something wrong.

**Lesson.** If one exit code means two things, look for another signal before you speak.

**Test:** `tests/test_bot.py::test_commands_and_errors` (the `/sync` part).

### The bot answers a photo, voice note or file (`6991c64`)

**How it was found.** UI/UX review, Telegram item 1: non-text messages from the owner got no reply.

**How it was fixed.** An empty `text` now gets "I can only read text for now: type your question, or /help for what I can do." The check moved below `chat_id` so the bot knows where to reply.

**Lesson.** Every input from a real user deserves some answer, even "I can't do that".

**Test:** `tests/test_bot.py::test_commands_and_errors` (the photo update).

### Bot error replies say what went wrong and what to do (`52dfa0e`)

**How it was found.** UI/UX review, Telegram item 8. "Sorry, that failed (it's in the log)" and "The check failed (exit 1)" pointed a phone user at a log file on another machine.

**How it was fixed.** A `why(e)` function turns an exception into plain words with a next step, and each `/sync` exit code got its own sentence.

```python
# after
def why(e: Exception) -> str:
    # ...
    if isinstance(e, labels.LoginNeeded):
        return "Outlook needs you to sign in again. Send /login."
    if isinstance(e, archive.ArchiveError):
        return f"the saved emails couldn't be read ({e})."
    if isinstance(e, urllib.error.HTTPError):
        return f"the AI endpoint refused the request (HTTP {e.code}). Check the AI settings in .env."
    if isinstance(e, (TimeoutError, urllib.error.URLError, ConnectionError)):
        return "the AI didn't answer (it may be busy or unreachable). Try again in a minute."
    # ...
```

`HTTPError` is tested before `URLError` because it is a subclass. The function never includes email content, only the kind of failure.

**Lesson.** An error message should name the kind of problem and the next step, in the user's own context.

**Test:** `tests/test_bot.py::test_commands_and_errors`.

### `/label` and `/profile` replies use chat commands, not CLI flags (`fa00e88`)

**How it was found.** UI/UX review, broken item 5. The bot reused the CLI's messages word for word, so a phone user was told to add `--label` or run `mailbrief rules list`.

**How it was fixed.** `rules_command` already took an `out` buffer when called from the bot, so `chat = out is not None` tells it where it is. Each message picks the chat wording (`/rule add sender …`, `/sync does one now`), and steps that need the PC say "on the machine MailBrief runs on".

**Lesson.** When one function serves two interfaces, let it know which one it is talking to.

**Test:** `tests/test_bot.py::test_chat_replies_never_tell_you_to_type_cli_flags`.

### The bot calls your rules `/rules`, as the CLI does (`7c15ff2`)

**How it was found.** UI/UX review, broken item 6. In the bot, `/labels` listed your rules, while `mailbrief labels` on the CLI meant the `MB:` categories in Outlook. One word, two things.

**How it was fixed.** `/rules` and `/rule` became the names in the menu and help. `/labels` and `/label` still work: `elif name in ("/rules", "/labels"):`.

**Lesson.** One name per concept across every interface. Keep old names as aliases so nothing breaks.

**Test:** `tests/test_bot.py::test_commands_and_errors` (asserts `/rules` and `/labels` give the same reply).

### Ctrl+C prints "Stopped." instead of a traceback (`db1a640`)

**How it was found.** UI/UX review, broken item 7. Interrupting a backfill, a confirmation prompt, `login` or `add-destination` printed a Python traceback, even though the help promised "Ctrl+C keeps everything saved so far".

**How it was fixed.** `main()` catches `KeyboardInterrupt`, prints `Stopped.` to stderr and exits 130 (the shell convention for "killed by SIGINT"). `_confirm` treats Ctrl+C at "Go ahead? [y/N]" as no: `except (EOFError, KeyboardInterrupt):`.

**Lesson.** Handle Ctrl+C once at the top, and make it mean "no" at a prompt.

**Test:** none added.

### A wrong key, no network or no browser gives one line (`b94680a`)

**How it was found.** UI/UX review, broken item 2. A changed `SESSION_ENCRYPTION_KEY` raised `InvalidToken` out of `run`, and a missing Chromium or a dead network raised raw Playwright errors.

**How it was fixed.** `_explain(e)` recognises those setup failures and returns a message; anything else returns `None` and keeps its traceback.

```python
# after
    except Exception as e:  # noqa: BLE001
        if (msg := _explain(e)) is None:
            raise  # a real bug: keep the traceback
        sys.exit(msg)
```

It matches Playwright errors by `type(e).__module__.startswith("playwright")` and their text (`"Executable doesn't exist"`, `"net::"`), so `main.py` doesn't import Playwright just to name the class.

Why this fix: a traceback is right for a bug and wrong for a setup mistake. Returning `None` for the unknown case keeps real bugs visible.

**Lesson.** Translate the errors you understand, and let the ones you don't keep their traceback.

**Test:** `tests/test_main.py::test_setup_failures_get_one_line_and_bugs_keep_their_traceback`.

### `add-destination` explains Telegram errors (`3158506`)

**How it was found.** UI/UX review, broken item 8. With no token, a wrong token, or `serve` already polling the bot (HTTP 409), `add-destination` died with a `TelegramError` traceback. If the test message failed, the chat had been saved but the user didn't know.

**How it was fixed.** `find_chats()` errors are matched by code: 409 says "stop MailBrief first or use --chat-id", 401 says "copy the token again", anything else is shown in one line. A failed test message now says the chat was added anyway.

**Lesson.** Tell the user what state you left things in, especially after a partial failure.

**Test:** none added.

### Every `--help` screen has a description and examples (`a82bcc2`)

**How it was found.** UI/UX review, CLI items 1, 2, 4 and Telegram item 4. Subcommand help showed only a usage line and flags. `--period` had no help text. The top level gave no starting point. `run` sounded like a preview but wrote to Outlook. `--priority 1-5` didn't say which end was urgent.

**How it was fixed.** An `EXAMPLES` table and a small wrapper around `add_parser`:

```python
# after
def _described(add_parser, prefix: str, name: str, **kw):
    """add_parser, plus what argparse leaves out of `mailbrief <command> --help`: the command's description
    (its one-line help) and its examples."""
    text = kw.get("help") or ""
    kw.setdefault("description", text[:1].upper() + text[1:] + ("" if text.endswith((".", ")")) else "."))
    if prefix + name in EXAMPLES:
        kw.setdefault("epilog", "examples:\n" + "\n".join("  " + line for line in EXAMPLES[prefix + name].splitlines()))
    kw.setdefault("formatter_class", argparse.RawDescriptionHelpFormatter)
    return add_parser(name, **kw)
```

It is installed with `sub.add_parser = functools.partial(_described, sub.add_parser, "")`, so the many existing `add_parser` calls didn't change. argparse shows `help=` only in the parent's list; `description=` is what the subcommand's own screen shows, so the wrapper copies one into the other. `RawDescriptionHelpFormatter` keeps the example lines as written. A `--version` flag and a "first time" epilog were added too.

**Lesson.** Wrap the library call once instead of editing every call site.

**Test:** `tests/test_cli_parser.py::test_version_comes_from_package_metadata` and `::test_parses_command_values_and_defaults` (added in `62a7bf6`).

### `run --no-password` is now `--plain` (`af3837e`)

**How it was found.** UI/UX review, CLI item 3. There is no password anywhere: the flag meant "save the archive unencrypted".

**How it was fixed.** `--plain` is the flag. The old name stays as a hidden alias writing to the same place: `run_p.add_argument("--no-password", dest="plain", action="store_true", help=argparse.SUPPRESS)`.

**Lesson.** Name a flag for what it does. Keep the old name hidden so scripts keep working.

**Test:** `tests/test_cli_parser.py::test_hidden_flag_parses_but_stays_out_of_help`.

### `--limit`, `--days`, `--show` and `--thread` refuse zero and negatives (`d309338`)

**How it was found.** UI/UX review, CLI items 6 and 7. `labels apply --limit -1` became the slice `[:-1]` and silently dropped one email. `--days -5` matched nothing. `emails --show N --thread M` used N and ignored the mode clash.

**How it was fixed.**

```python
# after
def _positive(text: str) -> int:
    """argparse type for counts: 1 or more. (A negative --limit used to slice one email off the end silently.)"""
    try:
        n = int(text)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"{text!r} isn't a whole number of 1 or more")
    return n
```

`--show` and `--thread` went into `add_mutually_exclusive_group()`. argparse turns `ArgumentTypeError` into a normal usage error with exit code 2.

**Lesson.** Validate numbers where they are parsed. Python's negative indexes turn a bad count into a silent wrong answer.

**Test:** `tests/test_cli_parser.py::test_required_and_mutually_exclusive_arguments_still_fail`.

### `run --json` always prints valid JSON on stdout (`8cb732e`)

**How it was found.** UI/UX review, CLI item 5, and a docs mismatch it listed. On a day with no new mail, stdout was empty, which breaks `run --json | python -m json.tool`. "No saved session" and "Outlook session expired" went to stdout too.

**How it was fixed.** `log = sys.stderr if as_json else sys.stdout` moved above the first message, both messages use `file=log`, and the quiet-day return prints `[]` first.

**Lesson.** A machine-readable mode must be machine-readable on every path, including the empty one.

**Test:** none added for the empty case. `fdcbab9` above extends the same rule to the AI client.

### The sign-in page tells a timeout from a failed sign-in (`f4dc27e`)

**How it was found.** UI/UX review, sign-in page item 1, and security and I/O review, bug 13. `/status` returned only `done` or `closed`, so running out of time, a sign-in Outlook didn't keep, and a crash all showed "This sign-in window has closed. Send /login again", which is also wrong advice after `login --remote`. The Telegram note was chosen from the clock, so a check that failed just after 10 minutes was reported as a timeout.

**How it was fixed.** The window has more end states, and the final one is set from what happened.

```python
# after
    def status(self) -> str:
        """What the page shows: open | hidden (on Outlook itself: no picture) | done | failed | expired."""
        if self.state != "open":
            return self.state
        return ("hidden" if self.hidden else "open") if self.live() else "expired"
```

```python
# after
            # From what happened, not from the clock: a check that fails just after the 10 minutes is still "failed".
            win.state = "done" if ok else "failed" if signed_in else "expired"
```

`signed_in` is set when the message list appeared in the sign-in browser. The page has a message per state, each ending with how to start again from Telegram or the CLI. `status()` replaced a long inline expression in the handler.

**Lesson.** Record the outcome when it happens; don't reconstruct it later from the clock.

**Test:** `tests/test_remote_login.py::test_done_state_is_shown_then_frames_stop`.

### The sign-in page's Start button can only be tapped once (`61425cc`)

**How it was found.** UI/UX review, sign-in page item 2. A second tap got a 404 whose "already been used" message replaced "Sign in as usual" on a session that was working.

**How it was fixed.** JavaScript in the `PAGE` string: the button is disabled and shows "Starting…" on the first tap, and a network error becomes `{ok: false}` instead of an unhandled promise.

**Lesson.** A one-time action needs a one-time button.

**Test:** none added (browser-side script).

### The sign-in page shows "Loading…" until the first picture arrives (`501e2f9`)

**How it was found.** UI/UX review, sign-in page item 3. After Start, the page showed a broken-image icon for the seconds before the first screenshot existed.

**How it was fixed.** The image stays hidden and the message says "Loading the Microsoft sign-in page…" until the first `onload`. `onerror` keeps retrying without showing the icon.

**Lesson.** Show a loading state instead of a broken one.

**Test:** none added (browser-side script).

### The sign-in page follows the phone's dark mode (`d037394`)

**How it was found.** UI/UX review, sign-in page item 10. It was hard-coded white: a bright flash at night when a sign-in expires.

**How it was fixed.** `<meta name="color-scheme" content="light dark">` and one `@media (prefers-color-scheme:dark)` rule. The doubled braces `{{ }}` are because `PAGE` is a Python `str.format` template.

**Lesson.** Respect the system theme; it costs two lines.

**Test:** none added.

### The sign-in page explains itself and is easier to tap and read (`9526614`)

**How it was found.** UI/UX review, sign-in page items 6, 8 and 9. The page didn't say what it was (a random tunnel address asking for a Microsoft password looks like phishing), showed nothing without JavaScript, had 40 px buttons 2 px apart, and an unlabelled input and backspace button.

**How it was fixed.** One line saying it is a live picture of a browser on your MailBrief machine and when it closes; 44 px tap targets with 8 px gaps; `aria-label`s; a `role="status"` message region; a `<noscript>` line; and a note that screen-reader users should sign in on the machine itself.

**Lesson.** A page that asks for a password must explain who is asking and why.

**Test:** none added.

### The sign-in page has separate email, password and code fields (`2a63d62`)

**How it was found.** UI/UX review, sign-in page items 4 and 5. One `type="password"` box masked the email as it was typed, and with `autocomplete="off"` password managers couldn't help. Typing also took two steps: Send, then find the Enter button.

**How it was fixed.** Three labelled inputs with the right `autocomplete` hints (`username`, `current-password`, `one-time-code`), and a "press Enter after typing" box, on by default, so the phone keyboard's Go key moves the Microsoft page on.

**Lesson.** Use the field types and autocomplete hints the platform already understands.

**Test:** none added.

### Digest section headings are bold in Telegram (`3b45145`)

**How it was found.** UI/UX review, Telegram item 5. Headings like TOP PRIORITIES TODAY were plain capitals and blurred into the bullets on a phone.

**How it was fixed.**

```python
# after
def _bold_headings(html_text: str) -> str:
    # ...
    from mailbrief.notify.telegram import is_heading, visible

    return "\n".join(f"<b>{line}</b>" if is_heading(visible(line)) else line for line in html_text.split("\n"))
```

It reuses the splitter's own `is_heading`, judged on the visible text, so the splitter still finds headings after they gain `<b>` tags.

**Lesson.** Reuse the existing definition of a thing (here "a heading") instead of writing a second one.

**Test:** `tests/test_links.py::test_section_headings_are_bold_and_still_split_on`.

### Links to emails are wider tap targets (`b370d48`)

**How it was found.** UI/UX review, Telegram item 6. A digest line ended in a lone `↗`, or several in a row, each a few pixels wide.

**How it was fixed.** One email gets `↗ open`; several get `↗ 1  ↗ 2`, spaced apart. A no-break space keeps arrow and word together. The events calendar uses the same `links.OPEN`.

```python
# after
        ids = list(dict.fromkeys(refs[n] for n in map(int, re.findall(r"\d+", m.group(0))) if n in refs))
        if len(ids) == 1:
            return f" {anchor(ids[0], OPEN)}"
        return "".join(f" {anchor(i, f'↗{NB}{k}')} " for k, i in enumerate(ids, 1)).rstrip()  # "↗ 1  ↗ 2": apart
```

`dict.fromkeys` removes duplicates while keeping order, which a `set` wouldn't.

**Lesson.** A link's text is its tap target. Make it wide enough for a thumb.

**Test:** `tests/test_links.py::test_to_html_and_plain`.

---

## Tests, types and CI

### Tests stop writing `tests/no-such-rules.json` into the repo (`e832ce9`)

**How it was found.** Flagged by the core pipeline review (test gaps) and the release-readiness review (blocker 5). `test_labels.py` set `rules.RULES_PATH` to a file next to the tests, at import time. pytest imports every test module before running any, so `test_bot.py`'s rule commands wrote that file on every run. It was untracked and not ignored, so a `git add .` would commit it. During the fixes it then made a test fail: the thread notes "a leftover file from the known test-isolation problem tripped a test".

**How it was fixed.** `rules.RULES_PATH = Path(tempfile.mkdtemp()) / "no-such-rules.json"`: a fresh empty folder per run.

**Lesson.** Tests must never write into the source tree, and module-level setup leaks into every other test module.

**Test:** the whole suite: run it twice and `git status` stays clean.

### Remove an unused variable and an unused import (`1fcceb3`)

**How it was found.** Release-readiness review: with ruff's default rules the repo had one F401 (unused import) and one F841 (unused variable).

**How it was fixed.** Removed both, in `tests/test_rules.py` and `tests/test_answer.py`, so `ruff check` passes before CI enforces it.

**Lesson.** Get to zero lint findings before you turn the linter on in CI.

**Test:** `uv run ruff check`.

### Cover archive, delivery and parser failures in the run pipeline (`22ad05c`)

**How it was found.** The core pipeline review listed as a test gap: "`main.run`: no tests at all", including the save-failure, empty-parse and preview paths. The follow-up session wrote these after checking the earlier fixes.

**How it was fixed.** `tests/test_pipeline.py` with one fixture that replaces the browser, Outlook reader, archive, cursor, AI and delivery with fakes, using pytest's `monkeypatch`. Each test changes one fake and checks one outcome.

```python
# tests/test_pipeline.py::test_failed_archive_does_not_advance_cursor
def test_failed_archive_does_not_advance_cursor(pipeline):
    pipeline.save.side_effect = OSError("disk full")
    assert main.run(commit=True, send=True, quiet=True) == 4
    pipeline.cursor_save.assert_not_called()
    pipeline.deliver.assert_called_once()
    pipeline.browser.close.assert_called_once()
```

How it works: `Mock(side_effect=...)` makes the fake raise when called. `assert_not_called()` proves the cursor never moved; `assert_called_once()` proves the digest still went out and the browser was closed. `monkeypatch` undoes every replacement after each test.

Why this approach: the run touches a browser, the network and the disk, so testing it end to end needs fakes at those edges. One fixture keeps each test to a few lines.

**Lesson.** Your biggest function needs tests most. Fake the outside world at its edges and test the decisions in the middle.

**Test:** the five tests in `tests/test_pipeline.py`.

### Resolve nullable values and inference errors across the code (`b5f4c11`)

**How it was found.** Release-readiness review: `mypy mailbrief --ignore-missing-imports` reported 49 errors in 14 files, mostly missing annotations, `None` not handled, and wrong types. The follow-up session cleaned them up before adding mypy to CI.

**How it was fixed.** Small changes across 14 files. Three kinds are typical:

```diff
-    chunks, current = [], []
+    chunks: list[list[str]] = []
+    current: list[str] = []
```

```diff
-    if os.name == "nt":
+    if sys.platform == "win32":
```

```diff
-    if ip.version == 6:
+    if isinstance(ip, ipaddress.IPv6Address):
```

Why these: mypy can't guess the type of an empty list, so it needs an annotation. mypy understands `sys.platform` checks and skips Windows-only code on Linux, but not `os.name`. An `isinstance` check narrows the type so `ip.ipv4_mapped` is known to exist; `ip.version == 6` means the same at run time but tells mypy nothing.

**Lesson.** Write checks the type checker understands; they document your intent to humans too.

**Test:** `uv run mypy mailbrief`.

### Enforce type checks and lint the demo and scripts in CI (`561164c`)

**How it was found.** Release-readiness review: "Fix the defaults set first, then add CI."

**How it was fixed.** `mypy` joined the dev dependency group, and the CI workflow runs `uv run ruff check mailbrief tests demo scripts` and `uv run mypy mailbrief` before `pytest`, on Linux and Windows.

**Lesson.** A check that isn't in CI decays. Add it once the code passes it.

**Test:** the CI workflow itself.

### Verify successful schedule slots are not repeated during retries (`ed5fc81`)

**How it was found.** The core pipeline review reproduced the double-send (`fb85d32`) by running the real `_serve` loop, but that fix landed without a test.

**How it was fixed.** `tests/test_service_retry.py` drives the real `_serve` loop with a fake clock: `time.sleep` advances the fake time by 30 s, the first child run fails and the rest succeed, and saving the expected `last_done` creates the stop file to end the loop.

```python
# tests/test_service_retry.py::test_retry_does_not_repeat_a_successful_later_slot
    spec = "daily 07:30; daily 07:45 this-week"
    assert service._serve(spec, service.parse_schedule(spec)) == 0
    assert calls == ["new", "this-week", "new"]
    assert saved[-1]["last_done"] == "2026-11-19T07:45:00+00:00"
```

Why this approach: the bug lived in how the loop combines retries and slots, so only running the loop could catch it. A fake clock makes minutes of schedule run in milliseconds.

**Lesson.** Inject the clock, and a scheduler becomes testable.

**Test:** this test.

---

## Configuration and AI portability

### Drop three settings the code never reads (`4b77566`)

**How it was found.** Core pipeline review ("dead config") and UI/UX review (onboarding item 5): `.env.example` and the README listed `FALLBACK_AGENT`, `DATABASE_URL` and `RESTORE_UNREAD`. Nothing reads them.

**How it was fixed.** Removed from `.env.example`, the README and `commands.md`.

**Lesson.** A setting in the example file is a promise. Remove the ones you don't keep.

**Test:** none (configuration files).

### No built-in AI endpoint, checked before Outlook opens (`6a60c9d`)

**How it was found.** Release-readiness review, blocker 2, and UI/UX review, CLI item 9. The code defaulted `AI_BASE_URL` to one university's internal endpoint and read the key from that endpoint's own variable name. A stranger who cloned the repo would have sent their email text there. Separately, a missing key was only reported after the whole Outlook read, about a minute in.

**How it was fixed.** One function reads the settings and refuses a missing endpoint. `run` and `labels retag` call it first.

```python
# before (the URL is elided here)
DEFAULT_BASE_URL = "https://<a university's internal endpoint>/v1"
# ...
    url = os.environ.get("AI_BASE_URL", DEFAULT_BASE_URL).rstrip("/") + path
```

```python
# after (as first committed; 412b612 below makes the key optional)
def settings() -> tuple[str, str]:
    """(endpoint, key) from .env, or ConfigError saying what's missing. Commands call this before they open
    Outlook, so a missing setting shows in a second, not after a minute of reading the inbox."""
    base = (os.environ.get("AI_BASE_URL") or "").strip()
    if not base:  # no built-in default: where your email text goes is your decision, never an assumption
        raise ConfigError("AI_BASE_URL is not set: put your OpenAI-compatible endpoint in .env, "
                          "e.g. AI_BASE_URL=http://localhost:11434/v1 (see .env.example)")
    # ...
```

The key is `AI_API_KEY`; the old variable name is still read as `LEGACY_KEY` so the author's existing install keeps working. The fallback model now defaults to your own `AI_CLASSIFIER_MODEL` instead of a hard-coded model name your endpoint may not serve.

Why this fix: where private data goes must be an explicit choice. A default that points somewhere real is a privacy bug for everyone but the author. Checking early turns a one-minute wait into a one-second error.

**Lesson.** Never default a destination for user data. Fail fast on missing configuration.

**Test:** `tests/test_ai_client.py::test_no_endpoint_is_a_clear_error_and_local_key_is_optional`.

### The vendor thinking extension is opt-in (`e734e62`)

**How it was found.** Release-readiness review, portability notes: every request sent `chat_template_kwargs`, and the code comment claimed unknown fields are ignored. The reviewer marked that "unverified for OpenAI and likely rejected". The follow-up session confirmed it was still there: "AI requests still include a Qwen-specific field that strict OpenAI-compatible servers may reject."

**How it was fixed.**

```python
# after
    # This extension is rejected by strict OpenAI-compatible servers; opt in for Qwen/Ollama.
    if os.environ.get("AI_CHAT_TEMPLATE_KWARGS", "off").lower() in ("on", "1", "true"):
        body["chat_template_kwargs"] = {"enable_thinking": thinking}
```

Why this fix: the standard request works everywhere; the extension helps some servers. So the standard is the default and the extension is a switch. The old setup turns it on in `.env`.

**Lesson.** Send only the standard fields by default; make vendor extras opt-in.

**Test:** `tests/test_ai_client.py::test_vendor_thinking_extension_is_opt_in`.

### Local AI endpoints work without a dummy API key (`412b612`)

**How it was found.** Release-readiness review, portability notes: "`_post` exits with 'No AI key' when no key is set, so Ollama users need a dummy key." Fixed in the follow-up session.

**How it was fixed.** `settings()` returns `key or ""`, and the `Authorization` header is only sent when there is a key.

```python
# after
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})},
```

How it works: `**({...} if key else {})` unpacks either one header or nothing into the dict. A local server gets no `Bearer ` header at all, rather than an empty one.

**Lesson.** Optional means optional: leave the header out instead of sending a fake value.

**Test:** `tests/test_ai_client.py::test_keyless_endpoint_sends_no_authorization_header`.

---

## Demo

### An isolated offline tour with fifteen invented emails (`e24c655`)

**How it was found.** Release-readiness review, showcase plan: "a demo mode doesn't exist", and a `demo/` folder with about 15 invented emails would be "the single biggest win for the showcase". The follow-up session confirmed "the offline demo was never created".

**How it was fixed.** `demo/run.py` builds 15 invented emails (all `@example.edu`), saves them to a temporary archive, and runs the real `emails` and `events` views on them. Digest and chat are prewritten and labelled as such, because they would need an AI.

```python
# demo/run.py::tour
    old_cwd, old_archive = Path.cwd(), archive.ARCHIVE_DIR
    with tempfile.TemporaryDirectory(prefix="mailbrief-demo-") as folder:
        try:
            os.chdir(folder)  # rules and all other relative paths also stay away from the real data/
            archive.ARCHIVE_DIR = Path(folder) / "archive"
```

How it works: `data/` paths are relative to the working directory, so changing into a temp folder keeps every file (rules, cursor) away from your real data. `ARCHIVE_DIR` is also pointed there. A `finally` block restores both, and the temp folder deletes itself.

Why this approach: it runs the real code on fake data, so the demo can't drift from the app. No Outlook, Telegram or AI is touched.

**Lesson.** A demo should run the real code on invented data, in a sandbox it cleans up.

**Test:** `tests/test_demo.py::test_offline_tour_restores_paths_and_never_uses_real_archive` and `::test_demo_has_threads_and_upcoming_events`.

---

## Documentation and project hosting

### Documentation accuracy (seven commits)

**How it was found.** The UI/UX review had a section "Docs vs behaviour mismatches". The release-readiness review flagged wording and data on a repo that was already public: `gh repo view` reported it as public, so everything on `origin/main` was visible. Its scans found no credentials in the tree or history.

**How it was fixed.** One commit per finding:

- `d27f1cd` Docs: brought `commands.md` and the README back in line with the code: `run --json` prints `[]` on a quiet day, the `emails` synopsis lists `--send`, past events are optional (`--past`), the rule commands exist in Telegram, the "cursor kept" result, everything that needs `TELEGRAM_BOT_TOKEN`, and `login --remote`'s exit codes. It also changed code: `/events` used a fixed 14 days and silently replaced bad input. It now reads `EVENTS_DAYS` like the CLI and replies with usage:

  ```python
  # after
          if rest and not (rest.isascii() and rest.isdigit() and 1 <= int(rest) <= 365):
              self.say(chat_id, "Usage: /events, or /events 30 for the next 30 days (1 to 365).")
              return
          # the same default as the morning message and `mailbrief events`: EVENTS_DAYS (0 there means 14 here)
          days = int(rest) if rest else events.days() or events.DEFAULT_DAYS
  ```

- `01e4e31` Docs: the teaching notes had framed the tool as a way to get mailbox access when an admin won't approve an app, and described copying the page's token. They now say plainly that it works in the Outlook web session you signed in to yourself, and that whether that is allowed is your organisation's decision.
- `5d25725` Docs: no university endpoint or key name in the README, `commands.md` or teaching notes. `AI_BASE_URL` is yours to set.
- `428b46e` Docs: dropped the claim "the AI provider is configured for zero retention", which can't be guaranteed for an endpoint this project doesn't run.
- `bd5b7cc` Docs and tests: examples used real-looking names and a real university's domain. They now use invented names and `example.edu`.
- `91466cb` Docs: removed the multi-user hosting checklist. Hosting for others is cancelled and the file was a public plan built around one institution's policies.
- `3e5e48d` Docs: recorded the finished review work and the AI portability settings in `CHANGELOG.md`, `commands.md` and the teaching notes.

**Lesson.** Docs are part of the product. Check every claim against the code, and treat a public repo's text as published.

**Test:** `tests/test_bot.py::test_commands_and_errors` asserts the `/events` usage reply. The rest is documentation.

### GitHub and CI: workflows, metadata, security policy, changelog (`4693e87`)

**How it was found.** Release-readiness review, "should fix before showcasing": no `.github/` folder, no CI, no `SECURITY.md`, no changelog, no dev dependency group (so `uv run pytest` failed with "Failed to spawn: pytest"), and gaps in `.gitignore`.

**How it was fixed.** One commit, as the user asked for CI and GitHub work to be kept together:

- `.github/workflows/ci.yml`: ruff and pytest on Linux and Windows for every push and pull request.
- `.github/workflows/pages.yml`: publishes `website/` to GitHub Pages.
- `pyproject.toml`: version 1.0.0, readme, licence, URLs, keywords, classifiers, a `dev` dependency group, and ruff and pytest settings.
- `SECURITY.md` (private reporting, scope), `CHANGELOG.md`, a bug-report template.
- `.gitignore`: `*.enc` anywhere, tool caches, coverage files.

**Lesson.** One command to run the tests (`uv run pytest`) should work right after cloning.

**Test:** CI.

### README: a landing page first, the design document after (`0b4259e`)

**How it was found.** UI/UX review (onboarding item 1) and release-readiness review (proposed README outline). The README opened with milestone status and about 700 lines of design, and had no install steps.

**How it was fixed.** It now starts with what MailBrief is, what it never does, where data goes, the caveats, an example digest and answer (made-up mail), requirements, a quick start in the right order, everyday use, honest limits and how to run the tests. The design sections follow unchanged under "Design notes".

**Lesson.** The first screen of a README answers: what is it, is it safe, how do I start.

**Test:** none (documentation).

---

## Website

### The first static showcase and setup guide (`02c13d4`)

**How it was found.** Not a bug. The user asked for a simple HTML, CSS and JS site in `website/` for GitHub Pages, explaining setup, use and example output. The release-readiness review had planned it: plain static pages, no framework, invented mail only, no analytics, no page that accepts credentials. The planned website agent hit a rate limit, so the follow-up session finished the existing files after the user agreed.

**How it was fixed.** `website/index.html`, `setup.html`, a stylesheet, a small script and a screenshot built from invented mail. `scripts/check_website.py` checks the pages in headless Chromium; the thread reports it passing "in all 16 combinations of screen width, light/dark mode, and JavaScript enabled/disabled".

**Lesson.** Even a static site deserves an automated check.

**Test:** `uv run python scripts/check_website.py`.

### Website redesigns and the shared CLI parser (`a3f1de1`, `f74caa2`, `efd2012`, `62a7bf6`, `d1f20b5`, `3a40e6d`)

**How it was found.** Design iterations by the user, not review findings. `a3f1de1` has a message (a terminal-style look with a light/dark toggle that remembers your choice). `f74caa2` and `efd2012` are later layout and theme passes. `62a7bf6` and `d1f20b5` are WIP commits that built a new version in `webpage-redesign/`. `3a40e6d` moved it into `website/`, removed the old folder, and pointed the Pages workflow at it.

**How it was fixed.** The site is now one terminal-style window per page (`index.html`, `setup.html`, `docs.html`) with a simulated prompt that only matches known inputs to prewritten responses. One change inside the WIP commit `62a7bf6` is real Python worth knowing: the CLI parser was pulled out of `_main()` into its own function, so other code can build it without side effects.

```python
# after
def build_parser() -> argparse.ArgumentParser:
    """The CLI parser, without reading .env, touching streams, or running a command."""
    # ...
    return parser


def _main() -> None:
    load_dotenv()
    # ...
    parser = build_parser()
    args = parser.parse_args()
```

`scripts/check_website.py` uses it to walk every real command and flag and fail if the site's command reference is missing one:

```python
# scripts/check_website.py::parser_commands
def parser_commands():
    """Every CLI command path and its public flags, straight from the real parser."""
    import argparse

    from mailbrief.main import build_parser
```

Why this approach: before, the parser only existed inside `_main()`, which also loads `.env` and changes the console encoding. Splitting "build" from "run" made it testable, and it let the website check compare the docs against the real CLI instead of a hand-kept list. `3a40e6d` also made the Pages workflow run when `mailbrief/**` changes, since the site check now depends on the code.

**Lesson.** Separate building an object from using it, and docs can be checked against the code automatically.

**Test:** `tests/test_cli_parser.py` (six tests, including `::test_build_parser_has_no_setup_side_effects`), and `uv run python scripts/check_website.py`.

---

## Patterns across the review

- **Progress recorded before the work was safe.** The cursor advancing after a failed save, `last_done` taken from a partial list, Telegram offsets confirmed late or early. Decide what each marker promises, and move it only when that is true.
- **"Nothing" that was really "couldn't tell".** An empty parse reported as no mail, exit 0 meaning both "sent" and "nothing new", a missing alert making failure look like a quiet day. When a result is empty, check a second source before calling it success.
- **Defaults that were wrong outside the author's setup.** A university endpoint, a vendor-only request field, a required dummy key, a time zone with no DST, a server that waits forever. Test with the settings a stranger would have.
- **Errors that vanished.** `SystemExit` in a thread, futures never read, exceptions inside a `with` block's exit. Raise ordinary exceptions from library code, always call `.result()`, and know what your context managers do on the way out.
- **Strings standing in for structure.** Sorting by `"Fri 06 Mar"`, cutting HTML by characters, iterating a string as a list, `isdigit()` accepting `²`. Keep the real type (datetime, int, list, parsed HTML atom) until the last moment.
- **Checks that described bad states instead of good ones.** A list of known login hosts, a write guard that only checked the name, `is_global` missing embedded IPv4. Allow-list what you expect.
- **Messages for the wrong audience.** CLI flags in chat replies, "it's in the log" on a phone, tracebacks for setup mistakes. Write each message for where it will be read.
- **Untested code where the risk was highest.** `main.run` and the `serve` loop had no tests until the review. Fake the edges (browser, network, clock) and test the decisions in between.
