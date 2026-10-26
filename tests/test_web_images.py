import urllib.request

from mailbrief import web_images
from mailbrief.web_images import TRIES, allowed, download

PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731


def test_allowed_only_public_https():
    assert allowed("https://cdn.example.com/a.png", PUBLIC)
    assert not allowed("http://cdn.example.com/a.png", PUBLIC)  # https only
    assert not allowed("ftp://cdn.example.com/a.png", PUBLIC)
    assert not allowed("https:///a.png", PUBLIC)
    for private in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254", "100.64.0.1",
                    "::1", "fe80::1%eth0", "fc00::1", "0.0.0.0", "224.0.0.1"):
        assert not allowed("https://evil.example.com/a.png", lambda h, ip=private: [ip]), private
    assert not allowed("https://mixed.example.com/a.png", lambda h: ["93.184.216.34", "10.0.0.1"])  # any private → no

    def broken(host):
        raise OSError("no such host")
    assert not allowed("https://nowhere.example.com/a.png", broken)
    assert not allowed("https://empty.example.com/a.png", lambda h: [])


def test_download_filters_and_limits():
    big = b"\x89PNG" + b"x" * 40_000
    files = {
        "https://a/1.png": ("image/png", big),
        "https://a/icon.png": ("image/png", b"x" * 500),            # too small: an icon
        "https://a/page.html": ("text/html", big),                  # not an image
        "https://a/huge.jpg": ("image/jpeg", b"x" * 5_000_001),     # over IMAGE_MAX
        "https://a/2.webp": ("image/webp", big),
        "https://a/3.jpg": ("image/jpeg", big),
    }

    def fetch(url):
        if url not in files:
            raise OSError("404")
        return files[url]

    ok = lambda url: True  # noqa: E731
    urls = list(files) + ["https://a/missing.png"]
    got = download(urls, room=5, budget=8_000_000, fetch=fetch, check=ok)
    assert [g.split(";")[0] for g in got] == ["data:image/png", "data:image/webp", "data:image/jpeg"]
    assert download(urls, room=1, budget=8_000_000, fetch=fetch, check=ok)[0].startswith("data:image/png")
    assert len(download(urls, room=5, budget=90_000, fetch=fetch, check=ok)) == 2  # budget: 2 × ~40 KB fit
    assert download(urls, room=5, budget=8_000_000, fetch=fetch, check=lambda u: False) == []  # unsafe URLs skipped
    assert download(urls, room=0, budget=8_000_000, fetch=fetch, check=ok) == []
    tried = []
    download([f"https://a/{i}.png" for i in range(30)], 5, 8_000_000, fetch=lambda u: tried.append(u) or ("image/png", b""),
             check=ok)
    assert len(tried) == TRIES  # never more than TRIES URLs per email


def test_no_redirects_and_switch():
    handler = next(h for h in web_images._opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://10.0.0.1/") is None
    import os
    old = os.environ.get("REMOTE_IMAGES")
    try:
        os.environ["REMOTE_IMAGES"] = "off"
        assert not web_images.enabled()
        os.environ.pop("REMOTE_IMAGES")
        assert web_images.enabled()  # on by default
    finally:
        if old is not None:
            os.environ["REMOTE_IMAGES"] = old


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
