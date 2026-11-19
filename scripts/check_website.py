"""Check the static site locally, including narrow layouts and keyboard tabs. No HTTP server needed."""

from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "website"


class Links(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.ids, self.targets = set(), []
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            assert attrs["id"] not in self.ids, f"duplicate id: {attrs['id']}"
            self.ids.add(attrs["id"])
        for key in ("href", "src"):
            if attrs.get(key):
                self.targets.append(attrs[key])


def check():
    docs = {p.name: Links(p) for p in ROOT.glob("*.html")}
    for name, doc in docs.items():
        for target in doc.targets:
            parts = urlsplit(target)
            if parts.scheme or parts.netloc:
                continue
            path = ROOT / unquote(parts.path or name)
            assert path.is_file(), f"{name}: missing {target}"
            if parts.fragment:
                assert parts.fragment in docs[path.name].ids, f"{name}: missing anchor {target}"
    with sync_playwright() as p:
        with p.chromium.launch(channel="chromium") as browser:
            for javascript in (True, False):
                for theme in ("light", "dark"):
                    for width in (320, 375, 768, 1280):
                        context = browser.new_context(viewport={"width": width, "height": 900},
                                                      color_scheme=theme, reduced_motion="reduce",
                                                      permissions=["clipboard-read", "clipboard-write"],
                                                      java_script_enabled=javascript)
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        for name in docs:
                            page.goto((ROOT / name).as_uri())
                            assert page.locator("h1").count() == 1
                            assert page.locator("body").evaluate("e => e.scrollWidth <= innerWidth"), (name, theme, width)
                            if javascript:
                                assert page.evaluate("document.documentElement.dataset.theme") == theme
                                page.locator(".theme").click()
                                flipped = {"light": "dark", "dark": "light"}[theme]
                                assert page.evaluate("[document.documentElement.dataset.theme, localStorage.theme]") == [flipped, flipped]
                                page.evaluate("localStorage.clear()")
                                for tab in page.get_by_role("tab").all():
                                    tab.click()
                                    panel = page.locator("#" + tab.get_attribute("aria-controls"))
                                    assert panel.is_visible()
                                if page.get_by_role("tab").count():
                                    page.get_by_role("tab").first.focus()
                                    page.keyboard.press("End")
                                    assert page.get_by_role("tab").last.get_attribute("aria-selected") == "true"
                                    page.get_by_role("tab", name="Inbox chat", exact=True).click()
                                    buttons = page.locator(".ask-row button")
                                    for button in buttons.all():
                                        if button.is_enabled():
                                            button.click()
                                    page.wait_for_timeout(30)
                                    assert page.locator(".typing").count() == 0
                                if page.locator(".code button").count():
                                    page.locator(".code button").first.click()
                                    expect(page.locator(".code button").first).to_have_text(re.compile("Copied|Select and copy"))
                            else:
                                assert page.locator("[role=tabpanel][hidden]").count() == 0
                            assert not errors, errors
                        context.close()
    print("Website checks passed: links, anchors, JavaScript, tabs, chat, copy controls, and 16 viewport/theme/JS combinations.")


if __name__ == "__main__":
    check()
