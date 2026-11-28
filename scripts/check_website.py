"""Verify the MailBrief static site: links, contracts, docs coverage and the file:// demo.

Run after the pages exist:  python scripts/check_website.py [folder]
The default folder is website/. No HTTP server is started and nothing is sent.
"""

import argparse
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "website"
PAGES = ("index.html", "setup.html", "docs.html")
PALETTE = ("#111210", "#181a17", "#ebe6db", "#b5b3a8", "#e7c58a", "#a9c6ce", "#d3c5a4")
TELEGRAM = (
    "/start", "/help", "/new", "/sync", "/digest", "/events", "/login", "/profile",
    "/rules", "/labels", "/rule", "/label",
)
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "param", "source", "track", "wbr"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children = tag, attrs, parent, []

    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()


class Tree(HTMLParser):
    """A small tolerant element tree: enough for the static checks below."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {}, None)
        self.stack = [self.root]
        self.duplicates = []

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.stack[-1])
        self.stack[-1].children.append(node)
        ident = node.attrs.get("id")
        if ident:
            seen = [n for n in nodes(self.root) if n.attrs.get("id") == ident]
            if len(seen) > 1:
                self.duplicates.append(ident)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, dict(attrs), self.stack[-1]))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def nodes(root):
    yield root
    for child in root.children:
        if isinstance(child, Node):
            yield from nodes(child)


def text(node):
    if isinstance(node, str):
        return node
    parts = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag not in ("script", "style"):
            parts.extend((" ", text(child), " "))
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


class Page:
    def __init__(self, path):
        self.path, self.name = path, path.name
        self.raw = path.read_text(encoding="utf-8")
        parser = Tree()
        parser.feed(self.raw)
        parser.close()
        self.root, self.duplicates = parser.root, parser.duplicates
        self.items = list(nodes(self.root))
        self.by_id = {}
        for node in self.items:
            ident = node.attrs.get("id")
            if ident:
                self.by_id.setdefault(ident, node)


def find_all(page, tag=None, klass=None, ident=None):
    found = []
    for node in page.items:
        if tag and node.tag != tag:
            continue
        if klass and klass not in node.classes:
            continue
        if ident and node.attrs.get("id") != ident:
            continue
        found.append(node)
    return found


def phrase(command):
    return re.compile(r"(?<![\w-])" + r"\s+".join(map(re.escape, command.split())) + r"(?![\w-])", re.I)


def flag_pattern(flag):
    return re.compile(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])")


def parser_commands():
    """Every CLI command path and its public flags, straight from the real parser."""
    import argparse

    from mailbrief.main import build_parser

    private = set()
    commands = []

    def walk(parser, path):
        public = []
        for action in parser._actions:
            if isinstance(action, argparse._HelpAction):
                continue
            if isinstance(action, argparse._SubParsersAction):
                continue
            if not action.option_strings:
                continue
            if action.help is argparse.SUPPRESS:
                private.update(action.option_strings)
            else:
                public.extend(action.option_strings)
        commands.append((path, public))
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    walk(child, path + [name])

    walk(build_parser(), [])
    return commands, private


def command_text(node):
    """The docs for one command anchor: its section, or a heading and the blocks under it."""
    if "doc-section" in node.classes:
        return text(node)
    if not re.fullmatch(r"h[1-6]", node.tag):
        return text(node)
    level = int(node.tag[1])
    siblings = node.parent.children
    start = next(i for i, child in enumerate(siblings) if child is node)
    parts = [text(node)]
    for sibling in siblings[start + 1:]:
        if isinstance(sibling, Node):
            heading = re.fullmatch(r"h([1-6])", sibling.tag)
            if heading and int(heading.group(1)) <= level:
                break
            parts.append(text(sibling))
    return " ".join(parts)


def static_checks(root):
    docs = {}
    for name in PAGES:
        path = root / name
        assert path.is_file(), f"{name} is missing from {root}"
        docs[name] = Page(path)

    css_path, js_path = root / "style.css", root / "site.js"
    assert css_path.is_file(), "style.css is missing"
    assert js_path.is_file(), "site.js is missing"
    css, js = css_path.read_text(encoding="utf-8").lower(), js_path.read_text(encoding="utf-8")

    for name, page in docs.items():
        assert not page.duplicates, f"{name}: duplicate id(s) {page.duplicates}"
        assert len(find_all(page, tag="h1")) == 1, f"{name}: expected exactly one h1"
        assert find_all(page, tag="header"), f"{name}: no shared header"
        assert find_all(page, tag="footer"), f"{name}: no shared footer"

        header_links = " ".join(text(a).lower() for a in find_all(page, tag="a") if any(
            n.tag == "header" for n in anc(a)))
        for wanted in ("home", "setup", "docs"):
            assert wanted in header_links, f"{name}: header navigation is missing {wanted!r}"
        footer = find_all(page, tag="footer")[0]
        footer_links = " ".join(text(a).lower() for a in find_all(page, tag="a") if any(
            n is footer for n in anc(a)))
        if name == "index.html":
            assert not footer_links, "home footer is status only; navigation belongs in the header"
            assert any("github.com/KidCoderT/mail-manager" in a.attrs.get("href", "")
                       for a in find_all(page, tag="a")), "home: source link missing"
        else:
            assert "github" in footer_links, f"{name}: footer needs a GitHub link"

        styles = [n for n in find_all(page, tag="link") if "stylesheet" in (n.attrs.get("rel") or "")]
        scripts = [n for n in find_all(page, tag="script") if n.attrs.get("src")]
        assert any((n.attrs.get("href") or "").endswith("style.css") for n in styles), f"{name}: style.css not linked"
        assert any((n.attrs.get("src") or "").endswith("site.js") for n in scripts), f"{name}: site.js not linked"
        for n in styles + scripts:
            ref = n.attrs.get("href") or n.attrs.get("src")
            assert not urlsplit(ref).scheme and not urlsplit(ref).netloc, f"{name}: external asset {ref}"
        for n in find_all(page, tag="img"):
            ref = n.attrs.get("src") or ""
            assert ref and not urlsplit(ref).scheme and not urlsplit(ref).netloc, f"{name}: external image {ref!r}"
            assert (root / unquote(urlsplit(ref).path)).is_file(), f"{name}: missing image {ref}"

        selects = [n for n in find_all(page, tag="select") if n.attrs.get("id") == "theme-select"]
        assert selects, f"{name}: #theme-select is missing"
        options = {o.attrs.get("value") for o in find_all(page, tag="option") if any(
            n is selects[0] for n in anc(o))}
        assert {"dark", "light", "system"} <= options, f"{name}: theme options are {sorted(options)}"

        for link in find_all(page, tag="a"):
            href = link.attrs.get("href")
            if href is not None and href.strip().lower().startswith("javascript:"):
                raise AssertionError(f"{name}: javascript: link")
        for target in page.items:
            for key in ("href", "src"):
                ref = target.attrs.get(key)
                if not ref:
                    continue
                parts = urlsplit(ref)
                if parts.scheme.lower() in ("http", "https", "mailto", "tel"):
                    continue
                if parts.scheme:
                    raise AssertionError(f"{name}: unsupported link {ref}")
                local = root / unquote(parts.path or name)
                assert local.is_file(), f"{name}: missing {ref}"
                if parts.fragment:
                    assert parts.fragment in docs[local.name].by_id, f"{name}: missing anchor {ref}"

    for tag in ("table",):
        for name, page in docs.items():
            for table in find_all(page, tag=tag):
                assert any("table-wrap" in n.classes for n in anc(table)), f"{name}: table is not wrapped in .table-wrap"

    index, docs_page = docs["index.html"], docs["docs.html"]
    for ident in ("playground", "terminal-form", "terminal-input", "terminal-output", "theme-select"):
        assert ident in index.by_id, f"index.html: #{ident} is missing"
    assert index.by_id["terminal-form"].tag == "form", "index.html: #terminal-form must be a form"
    terminal_input = index.by_id.get("terminal-input")
    assert terminal_input is not None, "index.html: #terminal-input is missing"
    assert terminal_input.tag == "input", "index.html: #terminal-input must be an input"
    assert any(n is index.by_id["terminal-form"] for n in anc(terminal_input)), \
        "index.html: terminal input is not in the form"
    assert find_all(index, klass="hero") or find_all(index, tag="h1"), "index.html: no hero"
    assert text(find_all(index, klass="digest-preview")[0]), "index.html: the no-JS digest is empty"
    assert [n for n in find_all(index) if "data-command" in n.attrs], "index.html: no [data-command] buttons"

    layout = find_all(docs_page, klass="docs-layout")
    assert layout, "docs.html: .docs-layout is missing"
    assert [n for n in find_all(docs_page, tag="aside") if "docs-nav" in n.classes], "docs.html: .docs-nav is missing"
    assert [n for n in find_all(docs_page, tag="article") if "docs-content" in n.classes], \
        "docs.html: .docs-content is missing"
    search = [n for n in find_all(docs_page) if n.attrs.get("id") == "docs-search"]
    if search:
        assert search[0].tag == "input", "docs.html: #docs-search must be an input"
    anchors = {}
    for page in (docs_page, index, docs["setup.html"]):
        for node in page.items:
            ident = node.attrs.get("id") or ""
            if ident.startswith("cmd-") and ident not in anchors:
                anchors[ident] = node
    commands, _private = parser_commands()
    for path, flags in commands:
        ident = "cmd-global" if not path else "cmd-" + "-".join(path)
        label = "mailbrief" + (" " + " ".join(path) if path else "")
        assert ident in anchors, f"docs: #{ident} is missing (for {label})"
        node = anchors[ident]
        if node.tag in ("section", "article"):
            assert "doc-section" in node.classes, f"docs.html: #{ident} section is not a .doc-section"
        body = command_text(node)
        if path:
            assert phrase(label).search(body), f"docs: #{ident} does not show `{label}`"
        for flag in flags:
            assert flag_pattern(flag).search(body), f"docs: #{ident} does not mention {flag}"
        if path:  # the terminal's own man pages (the MAN list in site.js)
            assert f"['{' '.join(path)}'," in js, f"site.js: MAN has no entry for `{label}`"

    everything = " ".join(text(page.root) for page in docs.values())
    for command in TELEGRAM:
        assert re.search(r"(?<![\w/])" + re.escape(command) + r"(?![\w-])", everything), \
            f"docs: Telegram command {command} is missing"

    assert re.search(r"segoe\s+ui\s+variable|system-ui", css), "style.css: display font stack is missing"
    assert re.search(r"cascadia\s+code|consolas|ui-monospace", css), "style.css: monospace font stack is missing"
    for colour in PALETTE:
        assert colour in css, f"style.css: palette colour {colour} is missing"
    for selector in ("pre", "code", ".table-wrap", ".callout", ".steps", ".copy-button",
                     ".docs-layout", ".docs-nav", ".docs-content", ".doc-section"):
        assert selector in css, f"style.css: {selector} support is missing"
    assert "prefers-reduced-motion" in css, "style.css: reduced-motion rule is missing"
    assert not re.search(r"@import|url\(\s*['\"]?https?:", css), "style.css: external asset import"
    assert not re.search(r"\bfetch\s*\(|XMLHttpRequest|WebSocket|EventSource|sendBeacon", js), \
        "site.js: network API found"
    print(f"Static checks passed: {len(commands)} command section(s), links, anchors, contracts and docs.")


def anc(node):
    parent = node.parent
    while parent is not None:
        yield parent
        parent = parent.parent


THEME_JS = """() => {
  const root = document.documentElement, body = document.body;
  const bgOf = el => {
    for (let n = el; n; n = n.parentElement) {
      const c = getComputedStyle(n).backgroundColor || "";
      const m = c.match(/[\\d.]+/g);
      if (m && (m.length > 3 ? Number(m[3]) > 0.01 : true) && !/^rgba?\\(0, 0, 0, 0\\)$/.test(c)) return c;
    }
    return "rgb(255,255,255)";
  };
  return {
    bg: bgOf(body || root),
    attrs: [root.getAttribute("data-theme"), body && body.getAttribute("data-theme"),
            root.className, body && body.className].filter(Boolean).join(" "),
    select: (document.querySelector("#theme-select") || {}).value || null,
    scheme: getComputedStyle(root).colorScheme || ""
  };
}"""


def luminance(colour):
    numbers = [float(x) for x in re.findall(r"[\d.]+", colour or "")][:3]
    if len(numbers) < 3:
        return 0.5
    values = []
    for value in numbers:
        value /= 255
        values.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]


def effective_theme(page):
    state = page.evaluate(THEME_JS)
    attrs = state["attrs"].lower()
    found = re.findall(r"\b(dark|light)\b", attrs)
    if found:
        return found[-1], state
    return ("dark" if luminance(state["bg"]) < 0.35 else "light"), state


def wait_theme(page, wanted, timeout=3.0):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        last = effective_theme(page)
        if last[0] == wanted:
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"expected the {wanted} theme, got {last}")


def external_requests(page):
    seen = []
    page.on("request", lambda request: seen.append(request.url)
            if re.match(r"https?://", request.url) else None)
    return seen


def layout_budget(page):
    return page.evaluate("""() => {
      const pg = document.querySelector("#playground");
      const main = document.querySelector("main");
      if (!pg || !main || !main.contains(pg)) return null;
      let hero = document.querySelector(".hero, [data-hero], #hero");
      if (!hero) {
        const h1 = main.querySelector("h1") || document.querySelector("h1");
        hero = h1 ? h1.closest("section, article, div") : main.firstElementChild;
      }
      if (!hero || hero === pg) return null;
      const a = hero.getBoundingClientRect(), b = pg.getBoundingClientRect();
      return {height: Math.max(a.bottom, b.bottom) - Math.min(a.top, b.top), viewport: innerHeight};
    }""")


def motion_scan(page):
    return page.evaluate("""() => {
      const durations = value => (value || "").split(",").map(x => parseFloat(x) || 0);
      let animation = 0, transition = 0;
      for (const el of document.querySelectorAll("*")) {
        if (!el.getClientRects().length) continue;
        const style = getComputedStyle(el);
        if (style.animationName !== "none") animation = Math.max(animation, ...durations(style.animationDuration));
        transition = Math.max(transition, ...durations(style.transitionDuration));
      }
      return {animation, transition, reduce: matchMedia("(prefers-reduced-motion: reduce)").matches};
    }""")


def browser_checks(root):
    urls = {name: (root / name).as_uri() for name in PAGES}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chromium")
        try:
            contexts = []

            def context(**kwargs):
                created = browser.new_context(**kwargs)
                contexts.append(created)
                return created

            # Every page, narrow and wide, with JavaScript: no sideways scroll and no network.
            for width, height in ((320, 900), (390, 844), (1280, 800)):
                ctx = context(viewport={"width": width, "height": height}, color_scheme="light")
                for name in PAGES:
                    page = ctx.new_page()
                    requests = external_requests(page)
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(urls[name])
                    assert page.locator("body").evaluate("e => e.scrollWidth <= innerWidth + 1"), (name, width)
                    assert not requests, f"{name}: network requests {requests}"
                    assert not errors, f"{name}: JavaScript errors {errors}"
                    page.close()
                ctx.close()

            # First visit is dark, even with light OS preference and even without JavaScript.
            for javascript in (True, False):
                ctx = context(viewport={"width": 1280, "height": 800}, color_scheme="light",
                              java_script_enabled=javascript)
                page = ctx.new_page()
                requests = external_requests(page)
                page.goto(urls["index.html"])
                if javascript:
                    wait_theme(page, "dark")
                else:
                    assert effective_theme(page)[0] == "dark", "no-JS first visit must be dark"
                    output = page.locator(".digest-preview")
                    assert output.is_visible() and output.inner_text().strip(), "no-JS transcript is missing"
                    usable = page.locator("#terminal-input").evaluate(
                        "e => !e.disabled && !e.readOnly && e.type !== 'hidden' && e.getClientRects().length > 0")
                    assert not usable, "no-JS terminal input must not be usable"
                assert not requests, f"network requests without JavaScript: {requests}"
                page.close()
                ctx.close()

            # Theme select: dark default, light persistence, system preference.
            ctx = context(viewport={"width": 1280, "height": 800}, color_scheme="light")
            page = ctx.new_page()
            page.goto(urls["index.html"])
            wait_theme(page, "dark")
            select = page.locator("#theme-select")
            select.select_option("light")
            wait_theme(page, "light")
            page.reload()
            wait_theme(page, "light")
            assert select.input_value() == "light", "the persisted theme is not selected after reload"
            select.select_option("system")
            page.emulate_media(color_scheme="dark")
            wait_theme(page, "dark")
            page.emulate_media(color_scheme="light")
            wait_theme(page, "light")
            page.close()
            ctx.close()

            # Playground: known command, unknown hint, history, buttons, literal text only.
            ctx = context(viewport={"width": 1280, "height": 800}, color_scheme="dark")
            page = ctx.new_page()
            requests = external_requests(page)
            page.goto(urls["index.html"])
            input_ = page.locator("#terminal-input")
            output = page.locator("#terminal-output")
            page.wait_for_function("() => { const i = document.querySelector('#terminal-input'); return i && !i.disabled; }")
            buttons = page.locator("[data-command]")
            assert buttons.count() > 0, "the playground has no command buttons"
            command = (buttons.first.get_attribute("data-command") or buttons.first.inner_text()).strip()
            assert command, "the first command button is empty"
            before = output.inner_text()
            input_.fill(command)
            input_.press("Enter")
            page.wait_for_function("old => document.querySelector('#terminal-output').textContent !== old", arg=before)
            assert command in output.inner_text(), "a known command was not accepted"
            input_.press("ArrowUp")
            assert input_.input_value() == command, "ArrowUp did not recall the last command"

            before = output.inner_text()
            buttons.first.click()
            page.wait_for_function("old => document.querySelector('#terminal-output').textContent !== old", arg=before)

            before = output.inner_text()
            unknown = "zzz-not-a-command"
            input_.fill(unknown)
            input_.press("Enter")
            page.wait_for_function("old => document.querySelector('#terminal-output').textContent !== old", arg=before)
            after = output.inner_text()
            fresh = after[len(before):] if after.startswith(before) else after
            assert re.search(r"unknown|unrecogni[sz]|not a .*command|type help|help for the list|"
                             r"i know|help lists", fresh, re.I), f"unknown command hint is missing: {fresh[-200:]!r}"

            page.evaluate("window.__xss = 0")
            before = output.inner_text()
            marker = '<img src=x onerror="window.__xss=1">'
            input_.fill(marker)
            input_.press("Enter")
            page.wait_for_function("old => document.querySelector('#terminal-output').textContent !== old", arg=before)
            assert output.locator("img").count() == 0, "terminal output injected HTML"
            assert page.evaluate("window.__xss") == 0, "terminal output executed HTML"
            assert "<img" not in output.inner_html().lower(), "terminal output wrote markup"
            assert not requests, f"playground network requests: {requests}"
            page.close()
            ctx.close()

            # A user draft must win over every stage of the opt-in tour.
            ctx = context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            page.clock.install()
            page.goto(urls["index.html"])
            input_ = page.locator("#terminal-input")
            blocks = page.locator("#terminal-output .block")
            input_.fill("my draft")
            page.locator(".secondary-commands > summary").click()
            page.locator('[data-command="mailbrief labels status"]').click()
            expect(blocks).to_have_count(1)
            page.clock.run_for(1500)
            expect(input_).to_have_value("my draft")
            for elapsed in (450, 530):  # during typing, then in the delayed-submit gap
                page.locator(".secondary-commands").evaluate("e => e.open = true")
                page.locator('[data-command="tour"]').click()
                page.clock.run_for(elapsed)
                before = blocks.count()
                input_.fill("my interrupted draft")
                page.clock.run_for(8000)
                expect(input_).to_have_value("my interrupted draft")
                expect(blocks).to_have_count(before)
                expect(page.locator("#stop-tour")).to_be_hidden()
            page.locator(".secondary-commands").evaluate("e => e.open = true")
            page.locator('[data-command="tour"]').click()
            page.clock.run_for(800)
            before = blocks.count()
            page.locator("#stop-tour").click()
            page.clock.run_for(8000)
            expect(blocks).to_have_count(before)
            page.close()
            ctx.close()

            # Landing hierarchy: one navigation row, demo-only rail, and a readable chat preview.
            for width, height in ((1280, 800), (390, 844)):
                ctx = context(viewport={"width": width, "height": height})
                page = ctx.new_page()
                page.goto(urls["index.html"])
                assert page.locator(".tabs a").all_text_contents() == ["home", "setup", "docs"]
                assert page.locator(".rail a, .statusbar a").count() == 0
                expect(page.locator(".setup-link")).to_have_count(1)
                expect(page.locator("#terminal-results")).to_be_hidden()
                hero = page.locator(".hero").bounding_box()
                preview = page.locator(".telegram-preview").bounding_box()
                assert hero and preview
                if width >= 1180:
                    assert preview["x"] >= hero["x"] + hero["width"], "preview should be beside the introduction"
                else:
                    assert preview["y"] >= hero["y"] + hero["height"], "mobile preview should stack below introduction"
                    page.locator(".rail .contents > summary").click()
                submenu = page.locator(".secondary-commands")
                assert submenu.get_attribute("open") is None
                submenu.locator("summary").click()
                expect(submenu.locator('[data-command="tour"]')).to_be_visible()
                assert page.locator(".rail .hint").first.evaluate("e => parseFloat(getComputedStyle(e).fontSize)") >= 14
                assert page.locator(".digest-item p").first.evaluate("e => parseFloat(getComputedStyle(e).fontSize)") >= 16
                page.locator("#terminal-input").fill("mailbrief events")
                page.locator("#terminal-input").press("Enter")
                expect(page.locator("#terminal-results")).to_be_visible()
                expect(page.locator(".telegram-preview")).to_be_visible()
                page.locator("#terminal-input").fill("clear")
                page.locator("#terminal-input").press("Enter")
                expect(page.locator("#terminal-results")).to_be_hidden()
                expect(page.locator(".hero")).to_be_visible()
                page.close()
                ctx.close()

            # Commands keep their meaning across pages; only docs explicitly navigates to a manual.
            ctx = context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
            page = ctx.new_page()
            for origin in PAGES:
                for command, expected in (("mailbrief events", "UPCOMING EVENTS"), ("man run", "USAGE")):
                    page.goto(urls[origin])
                    page.locator("#terminal-input").fill(command)
                    page.locator("#terminal-input").press("Enter")
                    expect(page).to_have_url(urls["index.html"])
                    expect(page.locator("#terminal-output")).to_contain_text(expected)
                page.goto(urls[origin])
                page.locator("#terminal-input").fill("setup")
                page.locator("#terminal-input").press("Enter")
                expect(page).to_have_url(urls["setup.html"])
                page.locator("#terminal-input").fill("docs run")
                page.locator("#terminal-input").press("Enter")
                expect(page).to_have_url(urls["docs.html"] + "#cmd-run")
            page.close()
            ctx.close()

            # Mobile contents are discoverable without commands, including with JavaScript off.
            for javascript in (True, False):
                ctx = context(viewport={"width": 390, "height": 844}, java_script_enabled=javascript,
                              is_mobile=True, has_touch=True)
                page = ctx.new_page()
                for name, target in (("docs.html", "#cmd-run"), ("setup.html", "#first-digest")):
                    page.goto(urls[name])
                    contents = page.locator(".docs-nav .contents")
                    expect(contents.locator("summary")).to_be_visible()
                    if javascript:
                        assert contents.get_attribute("open") is None
                        contents.locator("summary").click()
                    link = contents.locator('a[href="' + target + '"]')
                    expect(link).to_be_visible()
                    link.click()
                    expect(page).to_have_url(urls[name] + target)
                    expect(page.locator(target)).to_be_visible()
                page.close()
                ctx.close()

            # Reduced motion is respected.
            ctx = context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
            page = ctx.new_page()
            page.goto(urls["index.html"])
            motion = motion_scan(page)
            assert motion["reduce"], "reduced-motion preference is not visible to the page"
            assert motion["animation"] <= 0.05, f"animation still runs under reduced motion: {motion}"
            assert motion["transition"] <= 0.25, f"transition is too long under reduced motion: {motion}"
            page.close()
            ctx.close()

            # Two-screen budget for the hero plus the playground.
            for width, height in ((390, 844), (1280, 800)):
                ctx = context(viewport={"width": width, "height": height})
                page = ctx.new_page()
                page.goto(urls["index.html"])
                budget = layout_budget(page)
                assert budget, "could not measure the hero and playground"
                assert budget["height"] <= budget["viewport"] * 2 + 1, \
                    f"hero+playground is {budget['height']:.0f}px at {width}x{height}"
                page.close()
                ctx.close()

            # Docs filter (when present) narrows the visible sections and clears back.
            ctx = context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            page.goto(urls["docs.html"])
            search = page.locator("#docs-search")
            if search.count():
                before_count = page.locator(".doc-section:visible").count()
                assert before_count > 0, "docs page has no visible .doc-section"
                query = page.evaluate("""() => {
                  const sections = [...document.querySelectorAll(".doc-section")];
                  const words = new Set();
                  for (const section of sections) {
                    for (const word of section.textContent.match(/[A-Za-z][A-Za-z0-9_-]{3,}/g) || []) {
                      words.add(word);
                    }
                  }
                  for (const word of words) {
                    const hits = sections.filter(s => s.textContent.toLowerCase().includes(word.toLowerCase())).length;
                    if (hits > 0 && hits < sections.length) return word;
                  }
                  return null;
                }""")
                assert query, "could not find a word that narrows the docs"
                search.fill(query)
                page.wait_for_timeout(100)
                after_count = page.locator(".doc-section:visible").count()
                assert after_count < before_count, "the docs filter did not narrow the sections"
                search.fill("")
                page.wait_for_timeout(100)
                assert page.locator(".doc-section:visible").count() == before_count, \
                    "clearing the docs filter did not restore the sections"
            page.close()
            ctx.close()

            # Copy buttons, when the page uses code blocks.
            ctx = context(viewport={"width": 1280, "height": 800}, permissions=["clipboard-read", "clipboard-write"])
            for name in ("docs.html", "setup.html"):
                page = ctx.new_page()
                page.goto(urls[name])
                if page.locator("pre").count():
                    copies = page.locator(".copy-button")
                    assert copies.count() > 0, f"{name}: code blocks have no .copy-button"
                    button = copies.first
                    before = button.inner_text()
                    button.click()
                    page.wait_for_timeout(120)
                    assert button.inner_text() != before or re.search(
                        r"copied|select", button.inner_text(), re.I), f"{name}: copy button did nothing"
                page.close()
            ctx.close()

            for created in contexts:
                try:
                    created.close()
                except Exception:
                    pass
        finally:
            browser.close()
    print("Browser checks passed: themes, no-JS, playground, history, XSS, motion, viewports, docs filter and copy.")


def check(root):
    if not root.is_dir():
        raise SystemExit(f"Website folder not found: {root}\nCreate website/ (or pass its path) first.")
    missing = [name for name in PAGES if not (root / name).is_file()]
    if missing:
        raise SystemExit(f"{root} is missing {', '.join(missing)}; nothing was started.")
    static_checks(root)
    browser_checks(root)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", nargs="?", help="site folder (default: website/)")
    args = ap.parse_args()
    check(Path(args.path).resolve() if args.path else ROOT)
