# Teaching MailBrief: how it works, why, and how to build it yourself

This guide walks through the whole project: the idea, every module, the data that flows between them, and **why** each piece is built the way it is. Each function is shown twice: first as **pseudocode** (the logic), then as the **real Python** from the repository. After the code comes how it works, why it's written that way, which alternatives were rejected, and what would break if you changed it.

It is written so that you can **rebuild the app from scratch**, or **adapt it** to another mail source, destination or purpose.

Every quoted block of real code starts with a comment naming its source, such as `# mailbrief/cursor.py::select_new`. `tests/test_teaching.py` fails if a quote no longer matches the code, so the quotes stay true. A line that is only `# ...` marks code left out of a quote.

<!-- TOC -->
**Contents**

- [Reading order](#reading-order)
- [Keeping it current](#keeping-it-current)
<!-- /TOC -->

## Reading order

| # | File | What it covers |
|---|---|---|
| 1 | [Overview](01-overview.md) | The problem, how Outlook on the web works, the guiding principles, the file map, the lifecycles, the data shapes |
| 2 | [Storage, sessions and reading Outlook](02-storage-session-browser.md) | `browser/connect.py`, `storage/`, `session/` (including phone sign-in), `outlook_reader.py`, `owa_network.py` |
| 3 | [The mail pipeline](03-ai-pipeline.md) | `cursor.py`, `threads.py`, `ai/client.py`, `ai/classifier.py`, `ai/digest.py`, `archive.py`, `index.py`, `ai/answer.py` |
| 4 | [Delivery and the service](04-delivery-and-service.md) | `notify/`, `destinations.py`, `progress.py`, `service.py`, `notify/bot.py` |
| 5 | [Labels, rules and extras](05-labels-rules-extras.md) | `labels.py`, `outlook_writer.py`, `rules.py`, `events.py`, `web_images.py`, `links.py` |
| 6 | [`main.py` and the full run](06-main-and-full-run.md) | The CLI, the run pipeline end to end, failure handling, the security model |
| 7 | [Testing and the website](07-testing-and-website.md) | How the code is tested and why that way; the static site, the demo and the doc checks |
| 8 | [Rebuild from scratch](08-rebuild-from-scratch.md) | A step-by-step build order, with what to test before moving on |
| 9 | [Adapting it](09-adapting.md) | The points where you can swap parts: another mail source, destination, AI endpoint, categories or feed |
| 10 | [Lessons and limits](10-lessons-and-limits.md) | Bugs hit against real Outlook and what each taught; known limits |
| 11 | [Improvements](11-improvements.md) | Every change from the full review: how each was found and how it was fixed |
| 12 | [Glossary](12-glossary.md) | Terms used throughout |

**To understand the app:** read 1, then 6, then 2–5 as needed.
**To rebuild it:** read 1, then follow 8, opening the module files it links to.
**To repurpose it:** read 1 and 9.
**To learn from its mistakes:** read 10 and 11.

## Keeping it current

After changing code, run `uv run pytest -q tests/test_teaching.py`. If a quote fails, update that quote and its explanation. After adding or renaming headings, run `uv run python scripts/teaching_toc.py`.
