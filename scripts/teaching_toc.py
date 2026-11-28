"""Rewrite the table of contents in every teaching/*.md file.

Each file has a line `<!-- TOC -->` (or a block `<!-- TOC -->` ... `<!-- /TOC -->`);
it is replaced by a list of the file's ## and ### headings, linked by GitHub's anchor rules.
Run: uv run python scripts/teaching_toc.py      (tests/test_teaching.py fails if it is out of date)
"""

import re
import sys
from pathlib import Path

TEACHING = Path(__file__).resolve().parent.parent / "teaching"
BLOCK = re.compile(r"<!-- TOC -->(?:.*?<!-- /TOC -->)?", re.S)


def anchor(heading: str) -> str:
    # GitHub: lowercase, drop everything but letters, digits, spaces, hyphens and underscores; spaces -> hyphens
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def toc(text: str) -> str:
    lines, seen, fenced = [], {}, False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        m = None if fenced else re.match(r"^(##|###) (.+)$", line)
        if not m:
            continue
        a = anchor(m.group(2))
        n = seen.get(a, 0)
        seen[a] = n + 1
        indent = "   " if m.group(1) == "###" else ""
        lines.append(f"{indent}- [{m.group(2).strip()}](#{a}{f'-{n}' if n else ''})")
    return "<!-- TOC -->\n**Contents**\n\n" + "\n".join(lines) + "\n<!-- /TOC -->"


def render(text: str) -> str:
    return BLOCK.sub(lambda _: toc(BLOCK.sub("", text)), text, count=1)


if __name__ == "__main__":
    for path in sorted(TEACHING.glob("*.md")):
        old = path.read_text(encoding="utf-8")
        new = render(old)
        if new != old:
            path.write_text(new, encoding="utf-8")
            print("updated", path.name)
    sys.exit(0)
