import os
import tempfile
from pathlib import Path

from mailbrief.storage import files


def test_replace_waits_out_a_file_another_process_has_open():
    real, calls = os.replace, []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) < 3:  # Windows, while a reader or a virus scanner holds the target open
            raise PermissionError(5, "Access is denied")
        real(src, dst)

    with tempfile.TemporaryDirectory() as d:
        tmp, path = Path(d) / "a.tmp", Path(d) / "a.json"
        tmp.write_text("new")
        path.write_text("old")
        os.replace = flaky
        try:
            files.replace(tmp, path, wait=0)
            assert path.read_text() == "new" and len(calls) == 3
            tmp.write_text("x")
            calls.clear()
            os.replace = lambda s, t: (_ for _ in ()).throw(PermissionError(5, "Access is denied"))
            try:
                files.replace(tmp, path, tries=2, wait=0)
            except PermissionError:
                pass  # still locked after every try: the error is real, so it is raised
            else:
                raise AssertionError("a file that stays locked must raise")
        finally:
            os.replace = real


if __name__ == "__main__":
    test_replace_waits_out_a_file_another_process_has_open()
    print("ok")
