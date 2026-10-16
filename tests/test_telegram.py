from mailbrief.notify.telegram import split


def test_short_message_is_one_part():
    assert split("hello\nworld") == ["hello\nworld"]


def test_splits_on_lines_within_limit():
    text = "\n".join(f"line {i:03d} " + "x" * 40 for i in range(300))
    parts = split(text, limit=1000)
    assert all(len(p) <= 1000 for p in parts) and len(parts) > 1
    assert "\n".join(parts) == text  # nothing lost, lines never cut


def test_overlong_line_is_hard_split():
    parts = split("a" * 2500 + "\nend", limit=1000)
    assert [len(p) for p in parts] == [1000, 1000, 504]  # 500-char tail + "\nend" share the last part


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
