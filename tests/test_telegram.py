import re

from mailbrief.notify.telegram import LIMIT, is_heading, messages, size

TAG = re.compile(r" · \d+/\d+$")


def bullets(prefix: str, n: int, width: int = 100) -> list[str]:
    return [f"• {prefix} {i:03d} " + "x" * width for i in range(n)]


def digest(*sections: tuple[str, int]) -> str:
    lines = ["📬 357 emails · all — Newsletter 114 · FYI 80", ""]
    for heading, n in sections:
        lines += [heading] + bullets(heading.split()[0], n) + [""]
    return "\n".join(lines)


def untag(line: str) -> str:
    return TAG.sub("", line)


def test_short_text_is_one_unchanged_message():
    text = "📬 3 new emails — FYI 3\n\nFYI\n• a\n• b"
    assert messages(text) == [text]
    assert messages("  ") == []


def test_long_digest_goes_one_message_per_section():
    text = digest(("STILL OPEN", 20), ("KEY EVENTS", 20), ("NOISE", 3))
    assert size(text) > LIMIT
    out = messages(text)
    assert len(out) == 3
    assert out[0].startswith("📬 357 emails") and out[0].splitlines()[0].endswith(" · 1/3")  # header joins section 1
    assert "STILL OPEN" in out[0]
    assert out[1].startswith("KEY EVENTS · 2/3") and out[2].startswith("NOISE · 3/3")
    assert all(size(m) <= 4096 for m in out)


def test_oversize_section_splits_on_lines_with_cont():
    text = digest(("STILL OPEN", 3), ("KEY EVENTS", 150), ("NOISE", 2))
    out = messages(text)
    key = [m for m in out if "KEY EVENTS" in m.splitlines()[0]]
    assert len(key) >= 2 and key[1].splitlines()[0].startswith("KEY EVENTS (cont.)")
    assert all(size(m) <= 4096 for m in out)
    # Nothing lost, nothing cut mid-line, order kept (ignoring the k/n tags and "(cont.)" lines).
    sent = [untag(l) for m in out for l in m.splitlines() if l.strip() and "(cont.)" not in l]
    original = [l for l in text.splitlines() if l.strip()]
    assert sent == original


def test_utf16_sizing_with_emoji():
    assert size("📬") == 2 and size("abc") == 3
    text = "\n".join(["HEADING"] + ["• " + "📬" * 50] * 120)  # 6000 chars, ~12000 UTF-16 units
    out = messages(text)
    assert len(out) > 2 and all(size(m) <= 4096 for m in out)


def test_overlong_single_line_is_hard_cut():
    out = messages("NOISE\n" + "y" * 9000)
    assert all(size(m) <= 4096 for m in out) and sum(m.count("y") for m in out) == 9000


def test_heading_detection():
    for h in ("NOISE", "KEY EVENTS", "DEADLINES & MEETINGS (with dates; say \"passed\")", "FYI (one line each, only the useful ones)",
              "TOP PRIORITIES TODAY:", "STILL OPEN"):
        assert is_heading(h), h
    for not_h in ("• NOISE item", "NUS AI Institute", "Dear students,", "OK", "📬 3 new emails — FYI 3", "- KEY EVENTS", ""):
        assert not is_heading(not_h), not_h


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
