"""Links from MailBrief's messages to the emails in Outlook: a ↗ per email, built by code from item ids.

Model text is never trusted as markup: it's HTML-escaped, and only code turns "[3]" refs into links, so an email
can't slip a link of its own into a digest or an answer.
"""

import html
import re
from urllib.parse import quote

# Microsoft's documented web link (Graph "webLink"); Outlook redirects it to its current host and opens that email.
OUTLOOK_READ = "https://outlook.office.com/owa/?ItemID={}&exvsurl=1&viewmodel=ReadMessageItem"
REFS = re.compile(r"(?:\s*\[\d+\])+")  # "[3]", " [3][7]", "[3] [7]"
# A lone "↗" is a few pixels wide: hard to hit with a thumb. The word makes the target several times wider,
# and the no-break space keeps arrow and word on one line.
NB = " "
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
