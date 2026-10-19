"""The only code that changes anything in Outlook, and all it can change is categories (labels).

Every request still goes through _service_call → check_request, which refuses anything but a Categories update
or adding/removing "MB: " categories. Read first, then write: an email's own (non-MB) categories are always kept.
"""

from datetime import datetime, timezone

from mailbrief import progress
from mailbrief.browser.outlook_reader import _service_call
from mailbrief.browser.owa_network import (
    categories_getitem_body,
    master_list_body,
    merge_categories,
    parse_categories,
    parse_update,
    remove_everywhere_body,
    update_categories_body,
)

BATCH = 20


class WriteError(Exception):
    pass


def _json(resp, what: str) -> dict:
    if resp is None:
        raise WriteError(f"{what}: no Outlook auth captured")
    if not resp.ok:
        raise WriteError(f"{what}: HTTP {resp.status}")
    return resp.json()


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
                if current.get(i) is None:
                    results[i] = "gone"
                    continue
                change_key, cats = current[i]
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


def remove_categories(page, auth: dict, names: list[str]) -> None:
    """Delete MB: categories from your category list AND from every email that has them (what Outlook does when
    you delete a category in Settings)."""
    for name in names:
        _json(_service_call(page, auth, "ApplyCategoryOperation", lambda _h: remove_everywhere_body(name)), f"removing {name}")
    data = _json(_service_call(page, auth, "UpdateMasterCategoryList", lambda _h: master_list_body(remove=names)),
                 "removing categories")
    if data.get("WasSuccessful") is False:
        raise WriteError(f"removing categories: Outlook said {data.get('ResponseCode')}")
