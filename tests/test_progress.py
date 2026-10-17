import io

from mailbrief import progress


def fresh() -> io.StringIO:
    progress.OUT = io.StringIO()  # a StringIO is not a terminal: the "piped" behaviour
    progress._quarters.clear()
    progress._open_line = False
    return progress.OUT


def test_step_is_one_timestamped_line():
    out = fresh()
    progress.step("Opening Outlook…")
    assert out.getvalue().startswith("[00:") and out.getvalue().endswith("Opening Outlook…\n")


def test_count_when_piped_prints_quarters_only():
    out = fresh()
    for n in range(1, 101):
        progress.count("Fetching", n, 100)
    lines = out.getvalue().splitlines()
    assert [line.split()[-1] for line in lines] == ["25/100", "50/100", "75/100", "100/100"]
    assert "\r" not in out.getvalue()
    progress.count("Nothing", 0, 0)  # empty totals are ignored
    assert len(out.getvalue().splitlines()) == 4


def test_working_when_piped_prints_start_and_done():
    out = fresh()
    with progress.working("Writing digest") as w:
        w.note("(part 1/3)")  # live detail is terminal-only
    lines = out.getvalue().splitlines()
    assert len(lines) == 2 and lines[0].endswith("Writing digest…") and "✓ Writing digest (" in lines[1]
    assert "\r" not in out.getvalue() and "part" not in out.getvalue()


def test_working_marks_failure():
    out = fresh()
    try:
        with progress.working("Sending"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert "✗ Sending (" in out.getvalue()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
