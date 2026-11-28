# Labels, rules, events, images and links

<!-- TOC -->
**Contents**

- [`labels.py` and `outlook_writer.py`](#labelspy-and-outlook_writerpy)
   - [What an Outlook category is](#what-an-outlook-category-is)
   - [Step 0: copy what Outlook does, don't guess](#step-0-copy-what-outlook-does-dont-guess)
   - [The labels](#the-labels)
   - [Writing one batch (read, merge, write)](#writing-one-batch-read-merge-write)
   - [Creating and removing colours](#creating-and-removing-colours)
   - [Remembering what was done](#remembering-what-was-done)
   - [The guard: `check_request`](#the-guard-check_request)
   - [When it runs](#when-it-runs)
   - [Clearing](#clearing)
   - [Verified on the real mailbox](#verified-on-the-real-mailbox)
   - [Rebuilding it](#rebuilding-it)
   - [Try it](#try-it)
- [`rules.py`](#rulespy)
   - [The file is the truth](#the-file-is-the-truth)
   - [Code where code can decide, AI where it takes judgement](#code-where-code-can-decide-ai-where-it-takes-judgement)
   - [Priority floors and boosts](#priority-floors-and-boosts)
   - [How a rule change reaches Outlook (no new machinery)](#how-a-rule-change-reaches-outlook-no-new-machinery)
   - [Recipients](#recipients)
   - [Rebuilding it](#rebuilding-it-1)
   - [Try it](#try-it-1)
- [`events.py`](#eventspy)
   - [Why code builds it, not the AI](#why-code-builds-it-not-the-ai)
   - [`upcoming(emails, today, window, new_ids, your_rules, past)`](#upcomingemails-today-window-new_ids-your_rules-past)
   - [`render(events, today, window, past, html)`](#renderevents-today-window-past-html)
   - [`build(today, new_ids, log, html)`](#buildtoday-new_ids-log-html)
   - [Rebuilding it](#rebuilding-it-2)
   - [Try it](#try-it-2)
- [`web_images.py`](#web_imagespy)
   - [Is this URL safe to fetch?](#is-this-url-safe-to-fetch)
   - [Downloading](#downloading)
   - [Rebuilding it](#rebuilding-it-3)
   - [Try it](#try-it-3)
- [`links.py`](#linkspy)
   - [Building the links](#building-the-links)
   - [Rebuilding it](#rebuilding-it-4)
   - [Try it](#try-it-4)
<!-- /TOC -->

## `labels.py` and `outlook_writer.py`
**Job:** show each email's classification **inside Outlook**, as two categories (`MB: Urgent` + `MB: P1`), plus labels from your own rules. This is the app's first and only write to your mailbox, so it is narrow, checked, recorded and reversible.

### What an Outlook category is
- A category is a **name stored on the email**, on Microsoft's server. That's why it appears on web, desktop and phone.
- An email can have several. Your mailbox also has a **master category list** (Settings → Categories) that maps each name to a colour.
- A name that isn't in the list still shows, just without a colour.
- Changing an email's categories changes nothing else: not the folder, not read/unread, and nobody is notified.

### Step 0: copy what Outlook does, don't guess
Outlook's internal API is undocumented, so before writing any code a **probe** opened a visible Outlook, and the user categorised an email and created and deleted a category by hand. The probe recorded only the *structure* of the requests Outlook sent (action names and keys, with values redacted). It found:
- **The colour list:** `UpdateMasterCategoryList`, with `{Name, Color (a number), Id, LastTimeUsed, KeyboardShortcut}` entries to add and names to remove.
- **Deleting a category:** also sends `ApplyCategoryOperation` (Action 1), which strips that name from **every** email in one call.
- **A surprise:** Outlook's right-click "Categorize" doesn't tag the email. It sends `ApplyConversationAction / UpdateAlwaysCategorizeRule`, creating a rule that categorises the **whole conversation, including future replies**. That's not "label this email", so MailBrief deliberately doesn't copy it. It uses the standard per-email `UpdateItem` on the `Categories` field, and a one-email trial (below) confirmed that works.

The lesson generalises: when you automate a web app through its private API, record what the app itself sends, then copy the smallest piece of it. Guessing request shapes against an undocumented server is how you change things you didn't mean to.

### The labels
```
labels_for(email, rules):
    not a classified inbox email from someone else, or only a list preview → []
    else → ["MB: " + category]
           + ["MB: P" + priority]          priority after your rules' floors and boosts
           + your rule labels              e.g. "MB: CS1101S"
           + kept labels                   your labels from rules you've since removed (history)
```

```python
# mailbrief/labels.py::CATEGORY_COLOURS,labels_for,is_custom,_colours
CATEGORY_COLOURS = {"Urgent": 0, "Needs Reply": 1, "Meetings": 8, "FYI": 7, "Newsletter": 4, "Low Priority": 12}
#                   red         orange            purple         blue      green            grey
PRIORITY_COLOURS = {1: 15, 2: 1, 3: 3, 4: 5, 5: 12}
#                   dark red, orange, yellow, teal, grey
ALL_LABELS = {**{f"MB: {c}": col for c, col in CATEGORY_COLOURS.items()},
              **{f"MB: P{p}": col for p, col in PRIORITY_COLOURS.items()}}
CUSTOM_COLOURS = {"courses": 22, "senders": 9, "topics": 19}  # your own labels: dark blue, cranberry, dark green
RUN_LIMIT = 400  # per run; the first run on a big archive finishes the rest next time
# ...
def labels_for(email: dict, r: dict | None = None) -> list[str]:
    """The MB: labels this email should carry: [] for anything that isn't a classified inbox email from someone else.
    Built-in category + priority (raised by your rules), your rule labels, and labels of rules you've since removed
    (kept as history until `labels clear --label`). `r` = rules (default: data/rules.json)."""
    c = email.get("classification") or {}
    if c.get("category") not in CATEGORY_COLOURS or email.get("from_me") or not email.get("in_inbox", True) \
            or email.get("body_source") != "getitem":  # preview records carry a conversation id, not an email id
        return []
    r = rules.load() if r is None else r
    eff = rules.effective(email, r)
    current = rules.rule_labels(r)
    kept = [n for n in email.get("outlook_labels") or [] if is_custom(n) and n not in current and n not in eff["labels"]]
    return [f"MB: {c['category']}"] + ([f"MB: P{eff['priority']}"] if eff["priority"] in PRIORITY_COLOURS else []) \
        + eff["labels"] + kept


def is_custom(name: str) -> bool:
    """A label from your own rules (not one of the built-in category / priority labels)."""
    return name.startswith("MB: ") and name not in ALL_LABELS


def _colours(names) -> dict[str, int]:
    """Colours for these labels: built-ins as above, your own by kind (CUSTOM_COLOURS)."""
    r = rules.load()
    kind_of = {rules.label_name(k, rule): k for k in rules.KINDS for rule in r[k]}
    return {n: ALL_LABELS.get(n, CUSTOM_COLOURS.get(kind_of.get(n, "topics"), CUSTOM_COLOURS["topics"])) for n in names}
```

**How it works and why it's written this way:**
- **Why a prefix?** The prefix is how code tells "ours" from "yours". Every write is checked for it, clearing touches only it, and you can see at a glance which labels came from MailBrief.
- **Why two labels, not one combined one like "Urgent P1"?** Six categories plus five priorities is 11 names, versus 30 combinations. Filtering works either way: by "all urgent" or by "all P1".
- **Colours** are Outlook's preset numbers (0 red, 1 orange, 3 yellow, 4 green, 5 teal, 7 blue, 8 purple, 12 grey, 15 dark red), and your own labels get one colour per kind (courses 22, senders 9, topics 19). They're created once and only when missing. If you recolour one in Outlook, MailBrief never overwrites it.
- **`body_source != "getitem"` → no labels.** A record built only from the inbox list carries a *conversation* id, not an email id. Labelling with it would fail, or hit the wrong item.
- **`{**a, **b}`** merges two dicts into a new one, with `b` winning on clashes. `ALL_LABELS` is built from two dict comprehensions this way.
- **`r = rules.load() if r is None else r`.** Callers that label hundreds of emails load the rules once and pass them in. `load()` is cached anyway, but passing them in also means one run sees one version of the rules throughout.

### Writing one batch (read, merge, write)
```
set_labels(wanted = {email id: ["MB: FYI", "MB: P3"]}):
    for each batch of 20:
        current ← GetItem(ids, only Categories)          fresh categories + ChangeKey; a missing item → "gone"
        for each email:
            new ← (current without any "MB: …") + wanted  your own categories kept, in order
            new == current → ok, no write                (re-running costs reads only)
        UpdateItem(those that changed: set Categories = new, or delete the field if new is empty)
        per email: ok / gone / failed
        a batch that errors (e.g. a 60 s timeout) → only that batch marked failed; 3 failed batches in a row → stop
```

```python
# mailbrief/browser/outlook_writer.py::set_labels
def set_labels(page, auth: dict, wanted: dict[str, list[str]], label: str = "Labelling in Outlook") -> dict[str, str]:
    """Give each email exactly these MB: labels (an empty list removes them). Returns {id: ok|gone|failed: …}."""
    ids, results, failures_in_a_row = list(wanted), {}, 0
    for n in range(0, len(ids), BATCH):
        batch = ids[n : n + BATCH]
        try:
            current = parse_categories(_json(_service_call(page, auth, "GetItem", lambda h: categories_getitem_body(h, batch)),
                                             "reading categories"), batch)
            changes = []
            for i in batch:
                item = current.get(i)
                if item is None:
                    results[i] = "gone"
                    continue
                change_key, cats = item
                new = merge_categories(cats, wanted[i])
                if new == cats:
                    results[i] = "ok"  # already right: no write
                else:
                    changes.append((i, change_key, new))
            if changes:
                data = _json(_service_call(page, auth, "UpdateItem", lambda h: update_categories_body(h, changes)), "labelling")
                results.update(parse_update(data, [c[0] for c in changes]))
            failures_in_a_row = 0
        except Exception as e:  # noqa: BLE001 - a slow batch (timeout) is retried next time; the others go ahead
            results.update({i: f"failed: {type(e).__name__}" for i in batch if i not in results})
            failures_in_a_row += 1
            if failures_in_a_row >= 3:  # Outlook is clearly unhappy: stop, keep what's done
                results.update({i: "failed: stopped after 3 failed batches" for i in ids if i not in results})
                break
        progress.count(label, min(n + BATCH, len(ids)), len(ids))
    return results
```

```python
# mailbrief/browser/owa_network.py::merge_categories,update_categories_body
def merge_categories(current: list[str], wanted: list[str]) -> list[str]:
    """Your own categories kept in their order; every MailBrief one replaced by `wanted`."""
    return [c for c in current if not c.startswith(PREFIX)] + list(wanted)


def update_categories_body(header: dict, changes: list[tuple[str, str, list[str]]]) -> dict:
    """UpdateItem that sets (or, when empty, deletes) ONLY the Categories field of each (id, change_key, categories)."""
    def update(categories):
        path = {"__type": "PropertyUri:#Exchange", "FieldURI": "Categories"}
        if not categories:
            return {"__type": "DeleteItemField:#Exchange", "Path": path}
        return {"__type": "SetItemField:#Exchange", "Path": path, "Item": {"__type": "Message:#Exchange", "Categories": categories}}

    return {
        "__type": "UpdateItemJsonRequest:#Exchange",
        "Header": header,
        "Body": {
            "__type": "UpdateItemRequest:#Exchange",
            "ConflictResolution": "AlwaysOverwrite",
            "MessageDisposition": "SaveOnly",
            "SuppressReadReceipts": True,
            "ItemChanges": [{
                "__type": "ItemChange:#Exchange",
                "ItemId": {"__type": "ItemId:#Exchange", "Id": i, **({"ChangeKey": ck} if ck else {})},
                "Updates": [update(cats)],
            } for i, ck, cats in changes],
        },
    }
```

**How it works and why it's written this way:**
- **Why read first?** You may have added your own categories. Writing `["MB: FYI", "MB: P3"]` blindly would wipe them. `merge_categories` keeps every non-`MB:` category in its order and replaces only ours.
- **The ChangeKey is not a lock here.** It's Exchange's version stamp for an email, and `UpdateItem` requires it. But the request says `ConflictResolution: AlwaysOverwrite`, so Exchange applies the write even if the email changed in between. If you add a category in the second between `GetItem` and `UpdateItem`, it's overwritten. A stricter `AutoResolve` would refuse such writes, and each refusal would then need its own retry path. For a window of about a second, overwrite was the simpler choice.
- **Why skip unchanged ones?** It makes every operation idempotent and cheap to repeat. After a timeout, re-running is safe and quick: the second restore of 360 emails took 24 s because most were already right.
- **`DeleteItemField` for an empty list.** Removing the field is the clean way to say "no categories", instead of storing an empty list on the email.
- **`MessageDisposition: SaveOnly` and `SuppressReadReceipts`.** `SaveOnly` means "just save the change", never send. Suppressing read receipts means touching an email can never tell its sender you opened it.
- **Batches of 20.** One request per email would be 400 round trips. One request for 400 emails would run into the 60 s timeout. 20 is a compromise: a timeout costs one small batch, retried next run.
- **`except Exception` per batch.** A slow batch shouldn't stop the others. `{… for i in batch if i not in results}` marks only that batch's unfinished emails failed, so ones already found "gone" keep that result. Three failures in a row means Outlook is unhappy, and carrying on would just make 400 slow requests.
- **`lambda h: categories_getitem_body(h, batch)`.** `_service_call` builds the body from the *current* auth header, which can change if it retries after a 401. Passing a function that builds the body (instead of the body itself) lets it rebuild.

### Creating and removing colours
```
ensure_categories(existing, wanted)  → add only names your list lacks, with their colours
remove_categories(names)             → ApplyCategoryOperation(Action 1) per name: off every email
                                       then UpdateMasterCategoryList(remove names): out of your list
```

```python
# mailbrief/browser/outlook_writer.py::ensure_categories,remove_categories
def ensure_categories(page, auth: dict, existing: dict[str, int] | None, wanted: dict[str, int]) -> list[str]:
    """Add the wanted MB: categories (with colours) that your category list lacks. Existing ones are left
    alone, so a colour you changed in Outlook sticks. Returns the names added."""
    missing = [(n, c) for n, c in wanted.items() if existing is None or n not in existing]
    if not missing:
        return []
    now = datetime.now(timezone.utc).isoformat()
    data = _json(_service_call(page, auth, "UpdateMasterCategoryList", lambda _h: master_list_body(add=missing, now=now)),
                 "adding categories")
    if data.get("WasSuccessful") is False:
        raise WriteError(f"adding categories: Outlook said {data.get('ResponseCode')}")
    return [n for n, _ in missing]
# ...
def remove_categories(page, auth: dict, names: list[str]) -> None:
    """Delete MB: categories from your category list AND from every email that has them (what Outlook does when
    you delete a category in Settings)."""
    for name in names:
        _json(_service_call(page, auth, "ApplyCategoryOperation", lambda _h: remove_everywhere_body(name)), f"removing {name}")
    data = _json(_service_call(page, auth, "UpdateMasterCategoryList", lambda _h: master_list_body(remove=names)),
                 "removing categories")
    if data.get("WasSuccessful") is False:
        raise WriteError(f"removing categories: Outlook said {data.get('ResponseCode')}")
```

**How it works and why it's written this way:**
- **`WasSuccessful is False`, not `not WasSuccessful`.** A missing key means "Outlook didn't say", which isn't treated as failure. Only an explicit `False` is.
- **`timezone.utc` for `LastTimeUsed`.** Outlook stores it as a UTC timestamp. Writing local time without an offset would be ambiguous.
- **Removing everywhere is two steps** because that's what Outlook itself sends when you delete a category in Settings. Doing only the list would leave the names, uncoloured, on every email.

### Remembering what was done
Each archived email records:
- `outlook_labels`: what Outlook was given;
- `labels_cleared`: you removed them;
- `outlook_gone`: the email no longer exists in the mailbox.

```
pending(emails) = classified inbox emails where labels_for(e) ≠ e.outlook_labels,
                  not cleared, not gone
apply(emails):  create missing colours, set_labels, then record ok → outlook_labels, gone → outlook_gone
```

```python
# mailbrief/labels.py::pending,apply
def pending(emails: list[dict], include_cleared: bool = False) -> list[dict]:
    """Emails whose MB: labels in Outlook aren't what they should be (newest first, as given)."""
    r = rules.load()
    return [e for e in emails if (want := labels_for(e, r)) and not e.get("outlook_gone")
            and (include_cleared or not e.get("labels_cleared"))
            and want != e.get("outlook_labels")]
# ...
def apply(emails: list[dict]) -> str:
    """Give these emails their MB: labels (creating the coloured categories first if needed). Returns a summary."""
    from mailbrief.browser.outlook_writer import ensure_categories, set_labels
    from mailbrief.browser.owa_network import master_categories

    r = rules.load()
    wanted = {e["id"]: labels_for(e, r) for e in emails}
    names = {**ALL_LABELS, **_colours(n for labels in wanted.values() for n in labels)}
    with outlook() as (page, auth, startup):
        added = ensure_categories(page, auth, master_categories(startup), names)
        results = set_labels(page, auth, wanted)
    archive.update_fields({i: {"outlook_labels": wanted[i], "labels_cleared": False} if r == "ok" else {"outlook_gone": True}
                           for i, r in results.items() if r in ("ok", "gone")})
    return f"Labelled in Outlook: {_tally(results)}" + (f"; created {len(added)} coloured MB: categories" if added else "")
```

**How it works and why it's written this way:**
- **A new email:** it has no `outlook_labels` yet, so it's pending.
- **A reclassified email:** its labels differ, so it's pending, and its `MB:` labels are **swapped**.
- **An email you cleared:** it stays cleared until you `apply`.
- **A label you removed by hand:** the archive still says it was applied, so it isn't re-added. MailBrief respects your edits. The cost: if Outlook loses a label some other way, MailBrief won't notice either.
- **`(want := labels_for(e, r)) and …`.** The walrus assigns inside the comprehension's condition, so `labels_for` runs once per email, not twice.
- **Only "ok" and "gone" are recorded.** A failed email keeps its old record, so it's still pending next run.
- **Why store this in the archive?** Because the archive already holds one record per email, encrypted. A second file would have to be kept in sync with it.

One subtle fix made this work: `archive._merge` used to **replace** an email's record wholesale on every run. That would have wiped `outlook_labels` each morning, and every email would have looked pending forever. The merge now carries the label fields across.

### The guard: `check_request`
Every request goes through `_service_call`, and `_service_call` calls `check_request(action, body)` **before** anything leaves the PC:
```
GetItem, GetAttachment             → allowed (reads)
UpdateItem                         → only if MessageDisposition = SaveOnly, there is at least one change,
                                     and every change is Set/DeleteItemField on "Categories"
                                     with an Item that carries nothing but Categories
UpdateMasterCategoryList           → only adding/removing names that start with "MB: ", at least one;
                                     no colour, last-used or shortcut edits
ApplyCategoryOperation             → only Action 1 (remove everywhere), only for an "MB: " name, no other fields
anything else                      → UnsafeRequest: refused
```

```python
# mailbrief/browser/owa_network.py::check_request
READ_ACTIONS = {"GetItem", "GetAttachment"}
WRITE_ACTIONS = {"UpdateItem", "UpdateMasterCategoryList", "ApplyCategoryOperation"}
# ...
def check_request(action: str, body: dict) -> None:
    """The guard: every service.svc call passes here first. Reads are free; writes may touch categories only."""
    if action in READ_ACTIONS:
        return
    if action not in WRITE_ACTIONS:
        raise UnsafeRequest(f"{action} is not an allowed Outlook action")
    if action == "UpdateItem":
        b = body.get("Body") or {}
        changes = b.get("ItemChanges") or []
        if b.get("MessageDisposition") != "SaveOnly" or not changes:
            raise UnsafeRequest("UpdateItem must be SaveOnly with at least one change")
        for ch in changes:
            for u in ch.get("Updates") or [None]:
                if not isinstance(u, dict) or u.get("__type") not in ("SetItemField:#Exchange", "DeleteItemField:#Exchange") \
                        or (u.get("Path") or {}).get("FieldURI") != "Categories" \
                        or set((u.get("Item") or {}).keys()) - {"__type", "Categories"}:
                    raise UnsafeRequest("UpdateItem may only set or delete the Categories field")
    elif action == "UpdateMasterCategoryList":
        r = body.get("request") or {}
        names = [c.get("Name", "") for c in r.get("AddCategoryList") or []] + list(r.get("RemoveCategoryList") or [])
        if any(r.get(k) for k in ("ChangeCategoryColorList", "UpdateCategoryLastTimeUsedList", "ChangeCategoryKeyboardShortcutList")) \
                or not names or not all(str(n).startswith(PREFIX) for n in names):
            raise UnsafeRequest("the category list may only gain or lose MailBrief (\"MB: \") categories")
    elif action == "ApplyCategoryOperation":
        op = (body.get("request") or {}).get("categoryOperation") or {}
        # Action 1 (remove from every email) is the only operation MailBrief ever sends; the others
        # aren't known to be harmless, so they don't pass just because the name is ours.
        if op.get("Action") != 1 or set(op) - {"Action", "CategoryName"} or not str(op.get("CategoryName", "")).startswith(PREFIX):
            raise UnsafeRequest("only MailBrief (\"MB: \") categories can be removed everywhere")
```

```python
# mailbrief/browser/outlook_reader.py::_service_call
def _service_call(page, auth: dict, action: str, make_body):
    """POST an action to Outlook's service.svc as the page itself would. None if no auth was captured.

    Every call passes check_request first: reads are free, writes may only touch MailBrief's categories.
    """
    resp = None
    for _ in range(2):  # retry once: a 401 usually means the token refreshed after we copied it
        if not auth:
            return None
        body = make_body(auth["header"])
        check_request(action, body)  # raises before anything leaves this machine
        url = urlparse(auth["url"])._replace(query=f"action={action}&app=Mail").geturl()
        resp = page.request.post(
            url,
            headers={**auth["headers"], "action": action, "content-type": "application/json; charset=utf-8"},
            data=json.dumps(body),
            timeout=60_000,  # a 20-email update can take Outlook a while
        )
        if resp.status != 401:
            break
        page.wait_for_timeout(2000)
    return resp
```

**How it works and why it's written this way:**
- **An allowlist, not a blocklist.** The guard names what may pass and refuses everything else. A blocklist ("refuse SendItem, MoveItem, …") fails open the day you meet an action you didn't know about.
- **Why check the body, not just the action name?** `UpdateItem` can change *any* field. It's the same call that marks mail as read, or moves a draft to send. The guard looks inside the request. The tests try sneaking `IsRead` in, both as the field and hidden inside the item, plus "SendAndSaveCopy", and expect a refusal every time.
- **`set(item.keys()) - {"__type", "Categories"}`** is set difference: any other key left over means the item tries to set something else.
- **`for u in ch.get("Updates") or [None]`.** An item change with no updates becomes `[None]`, which fails the `isinstance(u, dict)` test. An empty list would otherwise skip the check entirely and pass.
- **`ApplyCategoryOperation` is pinned to Action 1.** It used to be checked by name alone. Its other actions aren't documented, so "the name is ours" wasn't proof they were harmless.
- **Why in the shared `_service_call`?** Every caller passes through it, so no future code can forget the check. And it runs on the body *after* it's built, right before `page.request.post`, so nothing can change the request between the check and the send.
- **The 401 retry.** Outlook's token refreshes in the page every so often. A 401 usually means the copy we took went stale, so it waits 2 s and tries once more with `make_body` re-run against the newer header.

### When it runs
```
run_step(log):            (in every `mailbrief run`, after saving the archive and before the digest)
    OUTLOOK_LABELS=off → nothing
    rules file broken → warning, skip labelling this run
    pending → apply the first 400, say how many are left
    any error → a warning; the run carries on, and the next run retries
outlook():  a headless browser with your saved session → (page, auth, startup); expired → LoginNeeded
            on the way out, save the rotated cookies
```

```python
# mailbrief/labels.py::outlook,run_step
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
# ...
def run_step(log) -> None:
    """The labelling step of `mailbrief run`: label what's pending (capped), never failing the run."""
    from mailbrief import progress

    if not enabled():
        return
    try:
        rules.load()
    except rules.RulesError as e:  # never relabel from a broken file: it would strip your labels everywhere
        print(f"warning: Outlook labels skipped this run: {e}", file=log)
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
```

**How it works and why it's written this way:**
- **It opens Outlook a second time**, about 5 s (`open_outlook`, the sign-in half of `read_inbox`, split out for this). The first browser was closed during the AI work, and its token may have aged.
- **It runs even when there's no new mail**, so earlier pending labels still get done.
- **It can never fail the run:** any error is a warning, and the next run retries. Labels are a bonus. The digest, delivery and cursor must still happen.
- **`RUN_LIMIT = 400`.** The first run on a big archive would otherwise spend minutes labelling before the digest. The rest is done next time.
- **`manager.save(context, …)` after the `yield`.** Microsoft rotates session cookies. Saving them after each use keeps the saved session fresh. It's skipped if the block raised, so a half-broken session isn't saved over a good one.
- **`mailbrief labels apply / clear / status`** do the same on demand. They take the run lock, so they never overlap a run.

### Clearing
```
clear(emails, colours):
    set_labels(each email → [])                       MB: labels removed, yours kept
    colours → remove_categories(every MB: name in your list)   strips them from EVERY email (even untracked)
                                                               and the colours disappear from your list
    archive: outlook_labels = [], labels_cleared = true
remove_label(emails, name, everywhere):   one of your own labels; the archive forgets it
```

```python
# mailbrief/labels.py::clear,remove_label
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
            removed = [n for n in existing if n.startswith("MB: ")]  # built-in and your own
            if removed:
                remove_categories(page, auth, removed)
    archive.update_fields({i: {"outlook_labels": [], "labels_cleared": True}
                           for i, r in results.items() if r in ("ok", "gone")})
    return f"Cleared labels: {_tally(results)}" + (f"; deleted {len(removed)} MB: categories from your list" if removed else "")


def remove_label(emails: list[dict], name: str, everywhere: bool = False) -> str:
    """Take one of your own labels off: from these emails (MailBrief-tracked), or with everywhere=True from every
    email in the mailbox and from your category list. The archive forgets it, so it's never re-applied."""
    from mailbrief.browser.outlook_writer import remove_categories, set_labels

    if not is_custom(name):
        raise ValueError(f"{name!r} isn't one of your own labels (built-in ones: `labels clear`)")
    results = {}
    with outlook() as (page, auth, _startup):
        if everywhere:
            remove_categories(page, auth, [name])
            results = {e["id"]: "ok" for e in emails}
        elif emails:
            results = set_labels(page, auth, {e["id"]: [n for n in e["outlook_labels"] if n != name] for e in emails},
                                 label=f"Removing {name}")
    by_id = {e["id"]: e for e in emails}
    archive.update_fields({i: {"outlook_labels": [n for n in by_id[i]["outlook_labels"] if n != name]}
                           for i, r in results.items() if r in ("ok", "gone")})
    where = "everywhere in your mailbox and your category list" if everywhere else _tally(results)
    return f"Removed {name}: {where}"
```

- **Selection:** `--period`, `--days N` or `--all`. It refuses to guess when none is given.
- **It asks before acting:** `Go ahead? [y/N]`. With no keyboard it counts as **no**, never as yes.
- **`--dry-run`** shows the exact emails and labels without touching Outlook.
- **`--everywhere`** uses Outlook's own "delete this category everywhere". The CLI then passes *every* archived email that carries the label, not just a period, so the archive forgets it on all of them. Otherwise a later relabel of an untouched email would write it back as "history".

### Verified on the real mailbox
1. **One already-read email:** got `MB: FYI` + `MB: P3`, and the 11 coloured categories were created.
2. **One unread email:** labelled, and still **unread** afterwards (checked with `GetItem` before and after).
3. **`clear --all` on those two:** labels gone.
4. **A normal run:** labelled all 358 pending emails in about 60 s.
5. **Idempotency and selection:** `labels status` showed 0 pending, and `clear --days 2` then `apply` worked.
6. **Full reset:** `clear --all --colours` removed 360 emails' labels and all 11 categories. `apply` restored everything.

### Rebuilding it
- **Inputs:** archived, classified emails; your rules. **Outputs:** categories in Outlook, and `outlook_labels` / `labels_cleared` / `outlook_gone` in the archive. **Depends on:** a signed-in browser page and the captured auth (`outlook_reader`), the request builders and guard (`owa_network`), `rules`, `archive`.
- **Write the guard first**, with tests that try to sneak other fields through. Then the read-merge-write batch. Then the bookkeeping. Then the CLI.
- **Adapting it:**
  - **Gmail:** labels are real objects with ids. `users.labels.create` once, then `users.messages.batchModify` with `addLabelIds` / `removeLabelIds`. Gmail's add/remove model means no read-merge step: you never send the full list, so you can't wipe the user's labels.
  - **Microsoft Graph** (if your tenant allows an app registration): `PATCH /me/messages/{id}` with `{"categories": […]}`, and `/me/outlook/masterCategories` for colours. The same read-merge is needed, because `categories` is a whole list.
  - **IMAP:** custom keywords (`STORE +FLAGS (MB_Urgent)`) work on many servers, but few clients show them. Moving to folders is visible everywhere, but it changes where mail lives, which this design avoids on purpose.

### Try it
- `tests/test_labels.py`: `test_labels_for`, `test_merge_keeps_your_categories_and_swaps_ours`, `test_pending_labelled_and_cleared`, `test_select_by_period_days_all`, `test_parse_categories_and_update`, `test_built_requests_pass_the_guard`, `test_guard_refuses_everything_else`, `test_master_categories_from_startup`, `test_your_own_labels`.

---

## `rules.py`
**Job:** your own labels, beside the built-in category and priority: `MB: CS1101S`, `MB: Prof Tan`, `MB: Networking`.

### The file is the truth
`data/rules.json` holds a profile and three lists: courses, senders, topics. `mailbrief rules add/remove/profile` edits it, and so can you by hand.
```
load()      → the rules (empty if no file); re-read only when the file's modification time changes
validate(d) → a clean copy, or RulesError naming the exact problem ("senders #2: needs a label")
              bare course strings become objects, codes upper-cased, built-in names refused, duplicates refused
save(r)     → validate, then write a temp file and rename it (atomic, like the archive)
add / remove → a new rules dict; add replaces a rule with the same key (code / match / name)
```

```python
# mailbrief/rules.py::RESERVED,_priority,_name,validate
RULES_PATH = Path("data/rules.json")
KINDS = ("courses", "senders", "topics")
RESERVED = {"urgent", "needs reply", "fyi", "meetings", "newsletter", "low priority", "unclassified",
            "p1", "p2", "p3", "p4", "p5"}  # the built-in MB: labels
BODY_SCAN = 1000  # ponytail: course codes only from the start of the body, so course-listing newsletters don't
#                   collect every code; "subject only for bulk senders" if that's still noisy
BOOST_FLOOR = 2   # a boosted email is at least P2 unless a rule says otherwise
# ...
def _priority(value, where: str):
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
        raise RulesError(f"{where}: priority must be 1-5 or null, not {value!r}")
    return value


def _name(value, where: str) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 40 or any(c in name for c in ",;"):
        raise RulesError(f"{where}: a label name must be 1-40 characters without , or ; (got {value!r})")
    if name.lower() in RESERVED:
        raise RulesError(f"{where}: {name!r} is a built-in MailBrief label; pick another name")
    return name


def validate(data) -> dict:
    """A clean copy of the rules, or RulesError saying what's wrong (and where)."""
    if not isinstance(data, dict):
        raise RulesError("rules.json must hold a JSON object")
    out = empty()
    out["profile"] = str(data.get("profile") or "").strip()
    for kind in KINDS:
        if not isinstance(data.get(kind, []), list):
            raise RulesError(f"{kind} must be a list")
    for n, c in enumerate(data.get("courses", []), 1):
        c = {"code": c} if isinstance(c, str) else c
        where = f"courses #{n}"
        if not isinstance(c, dict):
            raise RulesError(f"{where}: expected a course code or an object")
        out["courses"].append({"code": _name(c.get("code"), where).upper(),
                               "priority": _priority(c.get("priority"), where), "boost": bool(c.get("boost"))})
    for n, s in enumerate(data.get("senders", []), 1):
        where = f"senders #{n}"
        if not isinstance(s, dict) or not str(s.get("match") or "").strip():
            raise RulesError(f"{where}: needs \"match\" (an address, or part of a sender's name)")
        out["senders"].append({"match": str(s["match"]).strip(), "label": _name(s.get("label"), where),
                               "direct_only": bool(s.get("direct_only")),
                               "priority": _priority(s.get("priority"), where), "boost": bool(s.get("boost"))})
    for n, t in enumerate(data.get("topics", []), 1):
        where = f"topics #{n}"
        if not isinstance(t, dict) or not str(t.get("description") or "").strip():
            raise RulesError(f"{where}: needs \"name\" and \"description\"")
        out["topics"].append({"name": _name(t.get("name"), where), "description": str(t["description"]).strip(),
                              "priority": _priority(t.get("priority"), where)})
    names = [label_name(k, r) for k in KINDS for r in out[k]]
    dupes = sorted({x for x in names if names.count(x) > 1})
    if dupes:
        raise RulesError(f"two rules give the same label: {', '.join(dupes)}")
    return out
```

```python
# mailbrief/rules.py::load,save,add,remove
_cache: tuple = (None, None)


def load(path: Path | None = None) -> dict:
    """The current rules (empty when there's no file). Re-read only when the file changes."""
    global _cache
    path = path or RULES_PATH
    if not path.exists():
        return empty()
    try:
        raw = path.read_bytes()
        stamp = (str(path), hashlib.sha256(raw).digest())
        if _cache[0] != stamp:
            data = json.loads(raw.decode("utf-8"))
            _cache = (stamp, validate(data))
    except (OSError, ValueError) as e:
        raise RulesError(f"can't read {path}: {e}") from None
    return _cache[1]


def save(r: dict, path: Path | None = None) -> None:
    r, path = validate(r), path or RULES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace(tmp, path)  # atomic, like the archive


def _key(kind: str, rule: dict) -> str:
    return rule[{"courses": "code", "senders": "match", "topics": "name"}[kind]].lower()


def add(r: dict, kind: str, rule: dict) -> dict:
    """Rules with this one added, or replacing the rule with the same key (code / match / name)."""
    if kind not in KINDS:
        raise RulesError(f"unknown kind {kind!r}; use course, sender or topic")
    new = validate({kind: [rule]})[kind][0]  # the rule on its own first, so a replacement isn't a "duplicate"
    return validate({**r, kind: [x for x in r[kind] if _key(kind, x) != _key(kind, new)] + [new]})


def remove(r: dict, kind: str, key: str) -> tuple[dict, dict | None]:
    """(rules without it, the removed rule or None)."""
    gone = next((x for x in r[kind] if _key(kind, x) == key.strip().lower()), None)
    return {**r, kind: [x for x in r[kind] if x is not gone]}, gone
```

**How it works and why it's written this way:**
- **One validator for every way in.** The CLI, the bot and a hand-edited file all pass through `validate`, so there's one set of rules about what a rule may look like. Everything downstream can assume clean data: `"priority"` is an int or `None`, `"boost"` is a bool, and every list exists.
- **`isinstance(value, bool)` alongside `isinstance(value, int)`.** In Python, `True` *is* an `int` (`True == 1`). Without the extra check, `"priority": true` would pass as P1.
- **Errors say where.** `f"senders #{n}"` with `enumerate(…, 1)` counts from 1, the way you'd count entries in the file.
- **Reserved names.** A rule called `Urgent` would make `MB: Urgent` mean two things, and clearing one would clear the other.
- **The cache.** `_cache` holds `((path, sha256 of the bytes), rules)`. The file is small, so reading and hashing it costs almost nothing; parsing and validating is what the cache skips. That makes "what are the rules?" free to ask hundreds of times per run, and any change to the file, even two saves within the same timestamp tick, is picked up at once. (An earlier version keyed on `st_mtime_ns` and missed rapid saves on Windows.)
- **`add` validates the new rule alone first.** Then it replaces the old rule with the same key. Validating the whole list with both in it would report a duplicate label.
- **`remove` returns the removed rule too**, so the caller can say "removed CS2040S" or "no such rule" without a second search.
- **`encoding="utf-8"` and `ensure_ascii=False`.** Course names and profile text may have accents or other scripts. Writing them as real characters keeps the file readable by hand.

### Code where code can decide, AI where it takes judgement
```
matches(email, rules) → [(label, priority floor, boosted)]
  course   whole-word code in subject, sender name, first 1,000 chars of body       code
  sender   exact address, or part of the name; direct_only also needs email.direct  code
  topic    the topic is in classification.tags (the AI said so)                     AI
```

```python
# mailbrief/rules.py::_sender_fits,matches
def _sender_fits(rule: dict, email: dict) -> bool:
    m = rule["match"].lower()
    hit = (email.get("sender_email") or "").lower() == m if "@" in m else m in (email.get("sender_name") or "").lower()
    return hit and (not rule["direct_only"] or bool(email.get("direct")))


def matches(email: dict, r: dict) -> list[tuple[str, int | None, bool]]:
    """(label, priority floor, boosted) for every rule this email fits."""
    found = []
    text = " ".join([email.get("subject") or "", email.get("sender_name") or "", (email.get("body_text") or "")[:BODY_SCAN]])
    for c in r["courses"]:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(c['code'])}(?![A-Za-z0-9])", text, re.I):
            found.append((label_name("courses", c), c["priority"], c["boost"]))
    for s in r["senders"]:
        if _sender_fits(s, email):
            found.append((label_name("senders", s), s["priority"], s["boost"]))
    c = email.get("classification") or {}
    tags = {t.lower() for t in c.get("tags") or []}
    fits_profile = bool(c.get("boost")) or not r["profile"]  # no profile: any topic tag boosts
    for t in r["topics"]:
        if t["name"].lower() in tags:
            found.append((label_name("topics", t), t["priority"], fits_profile))
    return found
```

**How it works and why it's written this way:**
- **Courses and senders are exact questions**, so code answers them: free, instant, and the same answer every time.
- **The course regex.** `(?<![A-Za-z0-9])` and `(?![A-Za-z0-9])` are a negative look-behind and look-ahead: "no letter or digit right before / after". That's a whole-word match that also works for codes like `CS1101S`. `\b` would mostly do the same, but it treats `_` as a word character. `re.escape` makes a code with `.` or `+` match literally.
- **`"@" in m` decides the sender match.** With an `@` it's an exact address. Without one it's a substring of the display name, so `Tan` matches "Prof Tan Wei Ming". The trade-off: a short name can match more people than you meant.
- **"Is this a networking opportunity?" needs judgement**, so the classifier answers it. It gets your topic descriptions in the prompt (the same "definitions" trick that made the categories score 12/12) and returns `tags`. `validate` drops any name not in your list, so the AI can't invent labels.
- **Only the start of the body** is scanned for course codes. A newsletter listing twenty courses would otherwise collect twenty labels. (`ponytail:` if that's still noisy, "subject only for bulk senders" is the upgrade.)
- **With no profile and no topics the prompt is byte-for-byte the old one**, so the benchmark still holds.

### Priority floors and boosts
```
effective(email, rules):
    found    = matches(email, rules)
    boosted  = any rule in found says boosted
    priority = the most important (lowest number) of: the AI's priority, every floor in found,
               and P2 if boosted and no BOOSTED rule has a floor of its own
```

```python
# mailbrief/rules.py::effective
def effective(email: dict, r: dict) -> dict:
    """{"labels": rule labels, "priority": AI priority lowered by floors and boosts, "boosted": bool}."""
    found = matches(email, r)
    boosted = any(b for _, _, b in found)
    priority = (email.get("classification") or {}).get("priority")
    floors = [f for _, f, _ in found if f] + ([BOOST_FLOOR] if boosted and not any(f for _, f, b in found if b) else [])
    if isinstance(priority, int) and floors:
        priority = min([priority] + floors)
    return {"labels": [label for label, _, _ in found], "priority": priority, "boosted": boosted}
```

**How it works and why it's written this way:**
- **`min()` because P1 is the most important.** A floor can only raise an email's importance, never lower it.
- **The P2 rule, exactly.** The boost adds P2 unless a *boosted* rule set its own floor. A floor from a non-boosted rule doesn't count: a boosted topic plus a P4 course still gets P2.
- **`isinstance(priority, int)`.** An unclassified email has no priority. Floors aren't applied to nothing.
- **A topic match is boosted** only when the AI also said `boost: true` ("fits your profile"). Without a profile, every topic match boosts.
- **Course and sender rules** boost when added with `--boost`.
- **Boosted emails** get ⭐ in a digest section of their own, OPPORTUNITIES & EVENTS.

### How a rule change reaches Outlook (no new machinery)
`labels.labels_for(email)` asks `rules.effective()` too. Everything downstream is unchanged:
```
labels_for(email) = [MB: category, MB: P<effective priority>] + rule labels + kept labels
pending()         = emails whose labels_for ≠ outlook_labels   (as before)
```

```python
# mailbrief/labels.py::labels_for
    r = rules.load() if r is None else r
    eff = rules.effective(email, r)
    current = rules.rule_labels(r)
    kept = [n for n in email.get("outlook_labels") or [] if is_custom(n) and n not in current and n not in eff["labels"]]
    return [f"MB: {c['category']}"] + ([f"MB: P{eff['priority']}"] if eff["priority"] in PRIORITY_COLOURS else []) \
        + eff["labels"] + kept
```

`kept` is the history rule: a custom label already on the email stays only if no current rule gives it (`n not in current`) and this email's matches don't already include it.
So adding a course needs no special "re-apply" step. The next run (or `labels apply`) sees every matching email as pending and labels it. This is why courses and senders apply to the whole archive at once with no AI.

- **Kept labels:** a custom label already in `outlook_labels` whose rule no longer exists stays, as history. When the semester ends and you remove MA1521, old emails keep `MB: MA1521`. To take it off, `labels clear --label MA1521` calls `remove_label`, which updates Outlook and the archive, so it's never put back. Clearing a label that an active rule still gives is refused, because the next run would simply re-apply it.
- **A rule that still exists but no longer matches** (say you edited the address) does take its label off. Outlook mirrors your *current* rules, plus history from removed ones.
- **A broken rules file skips labelling for that run.** If the file were read as "no rules", every custom label would look wrong and be stripped from hundreds of emails. A warning and a skipped step are much cheaper than that. The digest still goes out.
- **Topics on older mail** need the AI again: `labels retag` re-classifies a period with your current rules, keeping the old answer when a call fails.

### Recipients
`direct` needs To/Cc, so `GetItem` asks for `ToRecipients` and `CcRecipients`. `fetch_emails`, which already knows your address for `from_me`, sets `direct = (to == [you])`. Checked on the real mailbox (structure only): a one-to-one email was direct, while a newsletter to a student list and an email sent to two of your addresses were not. A known limit: **mail merges** (e.g. individually sent grade emails) are also "only you", so `direct_only` is paired with a sender match, never used alone. Old archive entries get recipients from a one-off `run --backfill`: it re-fetches records with GetItem, and since their classifications are reused, no AI is called.

### Rebuilding it
- **Inputs:** a JSON file; an email dict with `subject`, `sender_*`, `body_text`, `direct` and `classification`. **Outputs:** `(label, floor, boosted)` matches and an effective priority. **Depends on:** nothing but `storage.files.replace`. It's the easiest module here to test.
- **Write `validate` first.** Everything else trusts its output.
- **Adapting it:** the same split works for any sorter. Put rules that have a definite answer (an address, a code, a regex) in code, and rules that need judgement ("is this a sales pitch?") in the prompt as named, described tags, then check the AI's answer against your list. For a work inbox, "courses" become project codes or ticket prefixes (`JIRA-\d+`), and "senders" become your manager and key clients.

### Try it
`tests/test_rules.py`: `test_validate`, `test_courses`, `test_senders_and_direct`, `test_topics_boost_and_priority`, `test_add_remove_save_load`. `tests/test_labels.py::test_your_own_labels` shows rule labels reaching `labels_for`.

---

## `events.py`
**Job:** the UPCOMING EVENTS message: a rolling calendar of the next `EVENTS_DAYS` days (default 14; 0 turns it off), sent after each digest.

### Why code builds it, not the AI
The classifier already did the judgement: it listed each email's events with real dates (`validate_events` threw out bad ones). What's left is sorting, filtering and layout, which code does exactly and for free. An AI asked to "list upcoming events" could drop one, invent one or get a date wrong, and nobody would notice. Building it in code also keeps the digest's 2,500-character limit for everything else.

### `upcoming(emails, today, window, new_ids, your_rules, past)`
```
for each saved email with events (not Sent, not Elsewhere, classified):
    boosted ← rules.effective(email).boosted          (your rules decide ⭐)
    for each event:
        dated:   keep if today - past ≤ date ≤ today + window
        undated: keep only if the email is in new_ids  (this digest's emails)
        merge with an event of the same name (letters/digits only) and date:
            fill missing fields from the other copy; new/boosted if either is;
            keep the first email's id (for the ↗ link)
```

```python
# mailbrief/events.py::days,_key,upcoming
def days() -> int:
    try:
        return max(0, int(os.environ.get("EVENTS_DAYS", DEFAULT_DAYS)))
    except ValueError:
        return DEFAULT_DAYS


def _key(ev: dict) -> tuple:
    return re.sub(r"[^a-z0-9]", "", ev["name"].lower()), ev.get("date")


def upcoming(emails: list[dict], today: date, window: int, new_ids=(), your_rules: dict | None = None,
             past: int = 0) -> list[dict]:
    """Events dated today-past … today+window (undated ones only from new emails), merged across emails."""
    from mailbrief import rules

    your_rules = your_rules or rules.empty()
    new_ids, first, last = set(new_ids), today - timedelta(days=past), today + timedelta(days=window)
    merged: dict[tuple, dict] = {}
    for e in emails:
        c = e.get("classification") or {}
        if c.get("category") in (None, "Sent", "Elsewhere") or not c.get("events"):
            continue
        boosted = rules.effective(e, your_rules)["boosted"]
        for ev in c["events"]:
            d = date.fromisoformat(ev["date"]) if ev.get("date") else None
            if (d is None and e["id"] not in new_ids) or (d is not None and not first <= d <= last):
                continue
            item = {**ev, "new": e["id"] in new_ids, "boosted": boosted, "from": e.get("sender_name") or "",
                    "email_id": e["id"]}  # merged events keep the first email's id (for the ↗ link)
            old = merged.get(_key(ev))
            if old is None:
                merged[_key(ev)] = item
            else:  # the same event in two emails: keep one, fill its gaps from the other
                merged[_key(ev)] = {**{k: v for k, v in item.items() if v}, **{k: v for k, v in old.items() if v},
                                    "new": old["new"] or item["new"], "boosted": old["boosted"] or item["boosted"]}
    return list(merged.values())
```

**How it works and why it's written this way:**
- **The whole archive, not just today's mail.** An event announced last week is still on the calendar this week. That's the point of a rolling calendar.
- **Undated events only when new**, otherwise "Career fair volunteer call (no date)" would appear every morning forever.
- **Merging** handles a reminder email repeating the original announcement. The key is the name with everything but letters and digits removed, plus the date, so "Hack Night!" and "hack night" on the same day are one event.
- **`{**{k: v for … if v}, **{…old… if v}, …}`.** Each copy drops its empty fields, then the old copy's non-empty values win over the new copy's. The result is the first announcement, with gaps filled from the later one. A field both copies fill keeps the first value, even if the reminder corrected it. That's the cost of this simple rule.
- **`date.fromisoformat`** parses `"2026-10-23"`. The classifier's validation already made every date ISO, so this shouldn't fail on archived data. If it ever does, `build()` catches it.
- **`days()`** treats a bad `EVENTS_DAYS` as the default, and a negative one as 0. A typo in `.env` shouldn't break the morning message.

### `render(events, today, window, past, html)`
```
title: "UPCOMING EVENTS · next 14 days" (or the past / past + next forms) and the count
day headings in uppercase ("FRI 23 OCT", "(PAST)" for past days), soonest first, then DATE NOT GIVEN
within a day: ⭐ boosted first, then by time ("7pm", "10:30am", "14:00"), then by name
each event: "mark time · name · place [↗ open]", the detail, then "sign up by … · link" (or "sign-up closed")
```

```python
# mailbrief/events.py::_time_key,_line,render
def _time_key(t: str | None) -> int:
    """Minutes since midnight for sorting "7pm", "10:30am", "14:00"; unknown times go last."""
    m = re.match(r"\s*(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?", (t or "").lower())
    if not m:
        return 24 * 60
    h, mins = int(m.group(1)) % 24, int(m.group(2) or 0)
    if m.group(3) and m.group(3).startswith("p") and h < 12:
        h += 12
    if m.group(3) and m.group(3).startswith("a") and h == 12:
        h = 0
    return h * 60 + mins


def _line(ev: dict, today: date, html_mode: bool = False) -> list[str]:
    esc = (lambda t: _html.escape(t, quote=False)) if html_mode else (lambda t: t)
    mark = ("⭐" if ev["boosted"] else "") + ("🆕" if ev["new"] else "") or "•"
    head = esc(" · ".join(x for x in (ev.get("time"), ev["name"], ev.get("place")) if x))
    if html_mode and ev.get("email_id"):
        head += f" {links.anchor(ev['email_id'], links.OPEN)}"  # "↗ open": the email that announced it
    lines = [f"{mark} {head}"]
    if ev.get("detail"):
        lines.append(f"   {esc(ev['detail'])}")
    signup = ev.get("signup_deadline")
    is_past = bool(ev.get("date")) and date.fromisoformat(ev["date"]) < today
    tail = []
    if signup and not is_past:  # "sign-up closed" on every past event is just noise
        d = date.fromisoformat(signup)
        tail.append(f"sign up by {d:%a %d %b}" if d >= today else "sign-up closed")
    if ev.get("link"):
        tail.append(ev["link"])
    if tail:
        lines.append("   " + esc(" · ".join(tail)))
    return lines


def render(events: list[dict], today: date, window: int = DEFAULT_DAYS, past: int = 0, html: bool = False) -> str | None:
    """The message text, or None when there's nothing to show. Day headings are uppercase (past days get a
    "(PAST)" note), so long messages split per day in telegram.messages(). html=True: Telegram HTML, every event
    ending with a ↗ link to its email."""
    if not events:
        return None
    if not past:
        title = f"UPCOMING EVENTS · next {window} days"
    elif not window:
        title = f"PAST EVENTS · last {past} days"
    else:
        title = f"EVENTS · last {past} days + next {window} days"
    out = [f"📅 {title} ({len(events)})"]
    dated = sorted({e["date"] for e in events if e.get("date")})
    for day in dated + [None]:
        group = [e for e in events if e.get("date") == day]
        if not group:
            continue
        if day:
            d = date.fromisoformat(day)
            heading = f"{d:%a %d %b}".upper() + (" (PAST)" if d < today else "")
        else:
            heading = "DATE NOT GIVEN"
        out += ["", heading]
        for ev in sorted(group, key=lambda e: (not e["boosted"], _time_key(e.get("time")), e["name"].lower())):
            out += _line(ev, today, html)
    return "\n".join(out)
```

**How it works and why it's written this way:**
- **Why uppercase headings?** `telegram.messages()` already splits a long digest at uppercase section headings. Day headings look the same to it, so a long calendar splits per day with "(cont.)" and `k/n` tags for free.
- **`_time_key`** turns a free-text time into minutes since midnight. `% 24` keeps "25" from breaking, `12am` becomes 0 and `1pm` becomes 13:00. Anything unreadable sorts last (`24 * 60`). It reads only the start of the string, so "7pm-9pm" sorts by 7pm.
- **Sorting by a tuple:** `(not e["boosted"], time, name)`. `False` sorts before `True`, so `not boosted` puts boosted events first.
- **`("⭐" if … else "") + ("🆕" if … else "") or "•"`.** If both marks are empty, the `or` falls back to a bullet. Operator precedence matters here: `+` binds tighter than `or`.
- **HTML mode escapes every piece of event text.** Event names come from emails. Only the `↗ open` link, built by `links.anchor`, is real markup.
- **Past events: `--past N`.** `upcoming` takes a `past` window too, so the range is `today - past … today + window`. `render` then says `EVENTS · last 30 days + next 14 days` (or `PAST EVENTS · last 30 days` with nothing ahead) and adds `(PAST)` to past day headings. That stays a valid uppercase heading with a note, so Telegram splitting still works per day. Past events drop the sign-up line, which would only ever say "closed". The morning message never passes `past`: it stays a look ahead.

### `build(today, new_ids, log, html)`
```
EVENTS_DAYS = 0 → None
load the archive and rules (a broken rules file → no rules), then upcoming + render
any error → a warning in the log, and None
```

```python
# mailbrief/events.py::build
def build(today: date, new_ids=(), log=None, html: bool = False) -> str | None:
    """The events message from the saved archive and your rules (html=True: for Telegram, with ↗ links).
    Never raises: events are a bonus."""
    from mailbrief import archive, rules

    window = days()
    if not window:
        return None
    try:
        try:
            your_rules = rules.load()
        except rules.RulesError:
            your_rules = rules.empty()
        return render(upcoming(archive.load()[0], today, window, new_ids, your_rules), today, window, html=html)
    except Exception as e:  # noqa: BLE001
        if log:
            print(f"warning: events message not built ({type(e).__name__}: {e})", file=log)
        return None
```

**How it works and why it's written this way:** It **never raises** (it returns `None` and logs a warning), because a calendar problem must not cost you the digest or the cursor. `run --send` sends it only after the digest was delivered, `emails --digest --send` and the bot's `/digest` resend it, and `/events` and `mailbrief events` show it on demand.

### Rebuilding it
- **Inputs:** archived emails with `classification.events` (`name`, `date`, `time`, `place`, `detail`, `signup_deadline`, `link`); today's date; the window. **Output:** one text block, plain or Telegram-HTML. **Depends on:** `rules.effective` for ⭐, `links.anchor` for ↗, `archive.load`.
- **Adapting it:** to put events in a real calendar instead, keep `upcoming()` and replace `render()` with an `.ics` writer (`BEGIN:VEVENT … DTSTART;VALUE=DATE:20261023 … END:VEVENT`). Any calendar app can subscribe to that file. The merge key then doubles as a stable `UID`.

### Try it
`tests/test_events.py`: `test_window_undated_and_skipped`, `test_merge_new_and_boost`, `test_render`, `test_past_window_and_render`, `test_long_calendar_splits_per_day`, `test_html_links`.

---

## `web_images.py`
**Job:** download images that newsletters link to, for the vision model. The links come from email bodies, so they're **untrusted input**: an email could point at anything, including a device on your own network (a router page, `http://192.168.1.1/…`), or at a cloud metadata address. That's a classic attack called SSRF (server-side request forgery).

### Is this URL safe to fetch?
```
allowed(url):
    https only, with a host name
    resolve the host name → every address must be a public internet address
        refused: private 10/8, 192.168/16, 172.16/12, loopback, link-local 169.254/16, CGNAT, reserved,
                 multicast, the IPv6 equivalents, and IPv6 forms that carry one of those IPv4 addresses inside
                 (::ffff:a.b.c.d, 2002:…  6to4, 64:ff9b::  NAT64, ::a.b.c.d)
```

```python
# mailbrief/web_images.py::constants,_resolve,allowed,_public
TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
TRIES = 12      # URLs tried per email at most
TIMEOUT_S = 10  # per connect and per read: a server that goes quiet
TOTAL_S = 20    # per image, start to finish: a server that drips a few bytes just inside every read timeout
# ...
def _resolve(host: str) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]


def allowed(url: str, resolve=_resolve) -> bool:
    """True for an https URL whose host resolves only to public internet addresses.
    ponytail: the name is resolved again when connecting (DNS rebinding); connect to the checked IP if that matters."""
    parts = urlparse(url)
    if parts.scheme != "https" or not parts.hostname:
        return False
    try:
        addresses = resolve(parts.hostname)
    except (OSError, UnicodeError):
        return False
    return bool(addresses) and all(_public(a) for a in addresses)


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


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

**How it works and why it's written this way:**
- **`urlparse(url).hostname`** pulls the host out and lower-cases it, without the port or a `user@` part. Checking the raw string instead would be fooled by `https://example.com@10.0.0.1/`.
- **Resolve, then check every address.** `socket.getaddrinfo` returns all the addresses a name has (IPv4 and IPv6). A name with one public and one private address is refused, because the connection could use either.
- **`ipaddress.ip_address(...).is_global`** is the standard library's own table of which ranges are public. It already knows private, loopback, link-local, CGNAT (100.64/10) and the reserved blocks. Writing that list by hand is how ranges get forgotten.
- **Why the IPv6 unwrapping?** `is_global` judges an IPv6 address as IPv6. `64:ff9b::7f00:1` is NAT64's way of writing 127.0.0.1, and `is_global` says it's public. On a network with NAT64, fetching it reaches this machine. So the embedded IPv4 is pulled out and checked itself. `int(ip) >> 32 == 0` catches the old "IPv4-compatible" `::a.b.c.d` form, whose top 96 bits are zero. `int(ip) & 0xFFFFFFFF` takes the low 32 bits as the IPv4 address.
- **`address.split("%")[0]`** drops an IPv6 zone id (`fe80::1%eth0`), which `ip_address` won't parse.
- **`resolve=_resolve` as a parameter.** Tests pass a fake resolver, so they can check `10.0.0.1` and NAT64 addresses without a DNS server.
- **The known gap:** the name is resolved once for the check and again when connecting. A hostile DNS server could answer differently the second time ("DNS rebinding"). The fix would be connecting to the checked address directly (with the original name for TLS); it's noted as a `ponytail:` in the code. HTTPS narrows the gap: a device on your network would also need a valid certificate for the attacker's name, so the TLS handshake fails before any HTTP request is sent.

### Downloading
```
download(urls, room, budget):
    for at most 12 URLs, while there is room and budget:
        skip unless allowed(url)
        fetch: 10 s per read, 20 s in all, no cookies, NO redirects, reading at most 5 MB + 1 byte
        keep only image/png|jpeg|webp|gif of 15 KB to 5 MB that fits the budget, as a data: URL
        any error → skip (never an exception)
```

```python
# mailbrief/web_images.py::_NoRedirect,_read,_fetch,download
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a 3xx becomes an error: never follow it


_opener = urllib.request.build_opener(_NoRedirect)


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


def _fetch(url: str) -> tuple[str, bytes]:
    """(content type, up to IMAGE_MAX + 1 bytes). Raises on any HTTP or network problem."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"})
    with _opener.open(req, timeout=TIMEOUT_S) as r:
        return (r.headers.get("Content-Type") or "").split(";")[0].strip().lower(), _read(r, IMAGE_MAX + 1)


def download(urls: list[str], room: int, budget: int, fetch=_fetch, check=allowed) -> list[str]:
    """Up to `room` images (data URLs) totalling at most `budget` bytes. Anything odd is skipped, never raised."""
    out: list[str] = []
    for url in urls[:TRIES]:
        if len(out) >= room or budget < IMAGE_MIN:
            break
        try:
            if not check(url):
                continue
            ctype, data = fetch(url)
        except Exception:  # noqa: BLE001 - a broken image link must never cost the email its classification
            continue
        if ctype in TYPES and IMAGE_MIN <= len(data) <= min(IMAGE_MAX, budget):
            out.append(f"data:{ctype};base64,{base64.b64encode(data).decode()}")
            budget -= len(data)
    return out
```

**How it works and why it's written this way:**
- **Why no redirects?** The check runs on the URL you were given. A public server could reply "go to `http://10.0.0.1/`", and following it would skip the check. `urllib` follows redirects through `HTTPRedirectHandler`. A subclass whose `redirect_request` returns `None` makes a 3xx an `HTTPError` instead. `build_opener(_NoRedirect)` builds an opener with that handler in place of the default. CDN images rarely redirect, so little is lost.
- **No cookies** because `urllib`'s default opener has no cookie jar. The browser's Outlook cookies are never involved.
- **Two time limits.** `timeout=10` bounds each socket operation. A server sending one byte every 9 s would never trip it, and could hold a run (and the run lock) for days. `_read` adds a 20 s deadline for the whole download. `read1` returns whatever has arrived instead of waiting for a full 64 KB, so the deadline is checked often.
- **`IMAGE_MAX + 1` bytes.** Reading one byte past the limit is how you tell "exactly 5 MB" from "bigger": anything over the limit is then thrown away by the size check.
- **`IMAGE_MIN` (15 KB)** skips tracking pixels, logos and icons, which are noise to a vision model and waste its budget.
- **The `Content-Type` check** uses what the server *says*. A server could lie, but the worst case is the vision model receiving junk, which it ignores.
- **`except Exception: continue`.** A broken image link must never cost the email its classification.
- **Privacy, honestly:** fetching an image tells its server your IP address and the time. Newsletters can use that to see the mail was "opened" (by MailBrief, often before you). `REMOTE_IMAGES=off` turns downloads off; events then come from text and attached or inline images only.
- **Measured on a week of real mail** (counts only): 16 linked images, 8.4 MB, for 5 newsletters, adding about 12 s to the run. No URL was refused.

### Rebuilding it
- **Inputs:** URLs from email HTML, how many images are still wanted, the byte budget. **Output:** `data:` URLs ready for the vision model. **Depends on:** only the standard library, plus two size constants from `owa_network`.
- **Any code that fetches URLs it didn't choose needs these same four steps:** a scheme allowlist, resolve-and-check every address, no redirects (or re-check each hop), and limits on size and total time. They apply equally to link previews, webhooks and URL importers.
- **If you'd rather use a library:** `requests` with `allow_redirects=False` and `stream=True` does the fetch half. The address check is still yours to write.

### Try it
`tests/test_web_images.py`: `test_allowed_only_public_https`, `test_download_filters_and_limits`, `test_a_dripping_server_is_given_up_on`, `test_no_redirects_and_switch`.

---

## `links.py`
**Job:** link every message MailBrief sends back to the emails it's about: a `↗ open` at the end of each digest bullet and each event, and on each claim in a chat answer.

### Building the links
```
outlook_url(id)  = https://outlook.office.com/owa/?ItemID=<id, URL-encoded>&exvsurl=1&viewmodel=ReadMessageItem
anchor(id, label) = <a href="…">label</a>, both escaped
to_html(text, refs):
    escape the whole text for Telegram's HTML mode
    "[3]" → " ↗ open" linked to email 3;  "[3][7]" → " ↗ 1  ↗ 2";  an unknown ref vanishes
    section headings (judged on the visible text) → bold
plain(text):          drop the [n] refs (terminal, logs)
```

```python
# mailbrief/links.py::outlook_url,anchor,to_html,plain
# Microsoft's documented web link (Graph "webLink"); Outlook redirects it to its current host and opens that email.
OUTLOOK_READ = "https://outlook.office.com/owa/?ItemID={}&exvsurl=1&viewmodel=ReadMessageItem"
REFS = re.compile(r"(?:\s*\[\d+\])+")  # "[3]", " [3][7]", "[3] [7]"
# ...
OPEN = f"↗{NB}open"


def outlook_url(item_id: str) -> str:
    return OUTLOOK_READ.format(quote(item_id, safe=""))


def anchor(item_id: str, label: str = "↗") -> str:
    return f'<a href="{html.escape(outlook_url(item_id))}">{html.escape(label)}</a>'


def to_html(text: str, refs: dict) -> str:
    """Escape `text` for Telegram's HTML mode and turn [n] refs into ↗ links ({n: item id}); unknown refs vanish."""
    refs = {int(k): v for k, v in refs.items()}  # JSON (the saved digest) turns int keys into strings

    def links(m: re.Match) -> str:
        ids = list(dict.fromkeys(refs[n] for n in map(int, re.findall(r"\d+", m.group(0))) if n in refs))
        if len(ids) == 1:
            return f" {anchor(ids[0], OPEN)}"
        return "".join(f" {anchor(i, f'↗{NB}{k}')} " for k, i in enumerate(ids, 1)).rstrip()  # "↗ 1  ↗ 2": apart

    out, last = [], 0
    for m in REFS.finditer(text):
        out += [html.escape(text[last:m.start()], quote=False), links(m)]
        last = m.end()
    return _bold_headings("".join(out + [html.escape(text[last:], quote=False)]))


def _bold_headings(html_text: str) -> str:
    """Section headings (TOP PRIORITIES TODAY, FYI, …) in bold: on a phone, plain capitals blur into the bullets.
    Judged on the visible text, the same way telegram.messages() finds the headings it splits at."""
    from mailbrief.notify.telegram import is_heading, visible

    return "\n".join(f"<b>{line}</b>" if is_heading(visible(line)) else line for line in html_text.split("\n"))


def plain(text: str) -> str:
    """The text without [n] refs (terminal, logs)."""
    return REFS.sub("", text)
```

**How it works and why it's written this way:**
- **Why this URL?** It's Microsoft's documented "web link" format. Outlook redirects it to its current address and opens that exact email. That was checked by watching Outlook request the linked item. The newer-looking `/mail/inbox/id/…` URLs just opened the inbox.
- **`quote(item_id, safe="")`.** Outlook ids contain `+`, `/` and `=`. By default `quote` leaves `/` alone. `safe=""` encodes it too, so the id survives as one query value.
- **Why refs and not links from the model?** The model only writes `[3]`. Code decides where `[3]` points, from the list of emails it gave the model, and escapes everything else. A malicious email therefore can't get its own link into your digest or an answer, even if it talks the model into writing one: it would show as plain text.
- **Escaping, piece by piece.** `REFS.finditer` finds each run of refs. The text between them is escaped with `html.escape(…, quote=False)` (quotes are harmless outside attributes), and each run becomes links. The `href` itself is escaped *with* quotes, since it sits inside `"…"`.
- **`dict.fromkeys(...)`** removes duplicates while keeping order. `[3][3]` gives one link.
- **`refs = {int(k): v …}`.** The digest is saved as JSON, and JSON object keys are always strings. Converting back means a resent digest still finds its refs.
- **Wider tap targets.** A lone `↗` is a few pixels wide, hard to hit with a thumb. `↗ open` is several times wider. The space between them is a no-break space (`NB`), so the arrow and the word never wrap apart.
- **Bold headings.** On a phone, plain capitals blur into the bullets. `_bold_headings` uses `telegram.is_heading(visible(line))`, the same test the splitter uses, so what's bold is exactly what the splitter treats as a section.
- **Telegram's HTML mode** counts the limit on the *visible* text, so the splitter measures that (`telegram.html_size`). Section headings are found on what a line shows, and a part Telegram can't parse is resent as plain text rather than lost.
- **The digest:** each email gets a `ref` number in the digest input, and the prompt asks for refs at the end of every bullet. The numbering is shared across batches and the merge. `archive` saves `refs` with the digest, so resending keeps its links.

### Rebuilding it
- **Inputs:** model text with `[n]` refs, and `{n: item id}`. **Output:** Telegram HTML. **Depends on:** `telegram.is_heading` and `visible`.
- **The pattern to keep** whatever you deliver to: number the sources you give the model, let it cite numbers only, and turn numbers into links in code. For Slack, `anchor` becomes `<{url}|open>` and escaping means `&`, `<`, `>` → `&amp;`, `&lt;`, `&gt;`. For Markdown email, it becomes a Markdown link with Markdown escaping. For another mail system, only `outlook_url` changes: it needs that system's "open this message" URL.

### Try it
`tests/test_links.py`: `test_outlook_url`, `test_to_html_and_plain`, `test_section_headings_are_bold_and_still_split_on`. `tests/test_events.py::test_html_links` shows the same anchors on events.
