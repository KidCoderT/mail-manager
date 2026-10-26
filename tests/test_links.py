from urllib.parse import parse_qs, urlparse

from mailbrief.links import anchor, outlook_url, plain, to_html

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
    assert lines[0] == f"• Pay fee &lt;now&gt; &amp; reply {anchor('id-one')}"
    assert lines[1] == f"• Both {anchor('id-one')} {anchor('id-two')}"
    assert lines[2] == "• Unknown"  # refs the digest didn't have just vanish
    assert lines[3] == f"• Twice {anchor('id-two')}"
    assert to_html("[1] x", {"1": "id-one"}).startswith(" <a")  # saved digests have string keys
    assert to_html("<a href='https://evil'>x</a>", {}) == "&lt;a href='https://evil'&gt;x&lt;/a&gt;"  # no links from text
    assert plain("• Pay [1][2] now [3]\nok") == "• Pay now\nok"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
