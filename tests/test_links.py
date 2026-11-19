from urllib.parse import parse_qs, urlparse

from mailbrief.links import OPEN, anchor, outlook_url, plain, to_html

ID = "AAMkAGI2/abc+def=="


def test_outlook_url():
    url = outlook_url(ID)
    u = urlparse(url)
    assert (u.scheme, u.netloc, u.path) == ("https", "outlook.office.com", "/owa/")
    q = parse_qs(u.query)
    assert q["ItemID"] == [ID] and q["viewmodel"] == ["ReadMessageItem"] and q["exvsurl"] == ["1"]
    assert "/" not in u.query.split("&")[0][7:] and "+" not in url  # the id is fully encoded
    assert anchor(ID) == f'<a href="{outlook_url(ID).replace("&", "&amp;")}">↗</a>'


def test_to_html_and_plain():
    refs = {1: "id-one", 2: "id-two"}
    out = to_html("• Pay fee <now> & reply [1]\n• Both [1][2]\n• Unknown [9]\n• Twice [2] [2]", refs)
    lines = out.split("\n")
    assert lines[0] == f"• Pay fee &lt;now&gt; &amp; reply {anchor('id-one', OPEN)}"  # one email: "↗ open", easy to tap
    one, two = anchor("id-one", "↗ 1"), anchor("id-two", "↗ 2")
    assert lines[1] == f"• Both {one}  {two}"  # several: numbered, apart
    assert lines[2] == "• Unknown"  # refs the digest didn't have just vanish
    assert lines[3] == f"• Twice {anchor('id-two', OPEN)}"
    assert to_html("[1] x", {"1": "id-one"}).startswith(" <a")  # saved digests have string keys
    assert to_html("<a href='https://evil'>x</a>", {}) == "&lt;a href='https://evil'&gt;x&lt;/a&gt;"  # no links from text
    assert plain("• Pay [1][2] now [3]\nok") == "• Pay now\nok"


def test_section_headings_are_bold_and_still_split_on():
    from mailbrief.notify.telegram import messages, visible

    out = to_html("📬 3 new emails — FYI 3\n\nTOP PRIORITIES TODAY\n• Pay the fee [1]\n\nDEADLINES & MEETINGS\n• Quiz on Friday", {1: "id-one"})
    assert "<b>TOP PRIORITIES TODAY</b>" in out and "<b>DEADLINES &amp; MEETINGS</b>" in out
    assert "<b>•" not in out and "<b>📬" not in out  # only headings
    long = to_html("\n\n".join(f"SECTION {chr(65 + n)}\n" + "\n".join(f"• line {i}" for i in range(250)) for n in range(4)), {})
    parts = messages(long, html_mode=True)
    assert len(parts) >= 4 and all(visible(p).startswith("SECTION") for p in parts)  # splitting still finds them
    assert all(p.count("<b>") == p.count("</b>") for p in parts)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
