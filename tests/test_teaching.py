"""The teaching/ guide quotes real code. These checks fail when a quote drifts from the source,
when a relative link breaks, or when a table of contents is out of date."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEACHING = ROOT / "teaching"
sys.path.insert(0, str(ROOT / "scripts"))
from teaching_toc import render, toc  # noqa: E402

# A quoted block starts with a comment naming its file:  # mailbrief/cursor.py::select_new
FENCE = re.compile(r"```python\n# ((?:mailbrief|tests|scripts|demo)/[\w/]+\.py)[^\n]*\n(.*?)```", re.S)
ELIDE = re.compile(r"^\s*# \.\.\.\s*$", re.M)  # a line "# ..." marks code left out of the quote


def _docs():
    return sorted(TEACHING.glob("*.md"))


def test_quoted_code_matches_the_source():
    stale = []
    for doc in _docs():
        for path, body in FENCE.findall(doc.read_text(encoding="utf-8")):
            source = (ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n")
            at = 0
            for piece in ELIDE.split(body):
                piece = piece.strip("\n")
                if not piece:
                    continue
                found = source.find(piece, at)
                if found < 0:
                    stale.append(f"{doc.name}: {path}: {piece.splitlines()[0][:70]!r}")
                    break
                at = found + len(piece)
    assert not stale, "quotes no longer match the code:\n" + "\n".join(stale)


def test_relative_links_resolve():
    broken = []
    for doc in _docs():
        prose = re.sub(r"```.*?```", "", doc.read_text(encoding="utf-8"), flags=re.S)  # code may contain "]("
        for target, frag in re.findall(r"\]\(([^)#\s]*)(?:#([^)\s]*))?\)", prose):
            if target.startswith(("http:", "https:", "mailto:")):
                continue
            path = doc.parent / target if target else doc
            if not path.exists():
                broken.append(f"{doc.name}: {target}")
            elif frag and path.suffix == ".md" and f"(#{frag})" not in toc(path.read_text(encoding="utf-8")):
                broken.append(f"{doc.name}: {target}#{frag}")
    assert not broken, broken


def test_tables_of_contents_are_current():
    stale = [d.name for d in _docs() if render(d.read_text(encoding="utf-8")) != d.read_text(encoding="utf-8")]
    assert not stale, f"run: uv run python scripts/teaching_toc.py  (stale: {stale})"
