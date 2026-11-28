"""Render the README's Telegram digest images (website/assets/showcase-{dark,light}.png).

The digest has the shape of a real MailBrief digest, but every name, course, place and date in it is invented.
It goes through the real links.to_html, so the ↗ links and bold headings look exactly as in Telegram.
Run: uv run python scripts/render_showcase.py
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

from mailbrief import links

DIGEST = """📬 17 new emails — Meetings 6 · Low Priority 4 · Newsletter 3 · FYI 2 · Urgent 1 · Needs Reply 1

TOP PRIORITIES TODAY
• Register for the compulsory writing-test briefing by today, 11 Mar [1]
• Go to the Year 2 project showcase today at 2:00 PM, Hall B [14][15]
• Join the Quant Club Discord for the briefing before tomorrow's trading workshop [17]
• Check your MATH1920 quiz 3 marks and try the past-year questions before Friday's lecture [13]

NEEDS A REPLY
• COMP1840: check your PA2 grade; email the course team only if the marks look wrong [7]

DEADLINES & MEETINGS
• 11 Mar: writing-test briefing registration closes [1]
• 11 Mar: Year 2 project showcase, 2:00 PM [14][15]
• 12 Mar: trading workshop; join the Discord first [17]
• 13 Mar: MATH1920 past-year questions [13]
• 15 Mar: study trip to Lisbon and Porto, applications close [5]
• 17 Mar: course feedback closes [2]
• 31 Mar: student research conference abstracts due [9]

OPPORTUNITIES & EVENTS
⭐ Deep-tech job list: AI, robotics and biotech internships for students [10]
⭐ Year 2 project showcase today at 2:00 PM: a good place to meet the teams [14][15]
⭐ Trading workshop tomorrow: you're registered; the briefing is on Discord [17]
⭐ Three seminars this week on robotics, AI and data; the AI talk is on Zoom [6]
⭐ Study trip to Lisbon and Porto in June; needs a 250-word application [5]
⭐ Research conference deadline moved to 31 Mar; check if your project fits the theme [9]

FYI
• The COMP1840 forum has new threads on grading, marks and past papers [8]
• The health centre is closed on 18 Mar [12]
• The dining hall closes after 7 PM on Friday [11]
• The co-op newsletter features this year's student founders [3]"""

THEMES = {
    "dark": {"page": "#0e1621", "bar": "#17212b", "bubble": "#182533", "text": "#f5f5f5", "muted": "#7f91a4", "link": "#6ab3f3"},
    "light": {"page": "#d5e3c6", "bar": "#ffffff", "bubble": "#ffffff", "text": "#000000", "muted": "#8b9aa8", "link": "#168acd"},
}

PAGE = """<!doctype html><meta charset="utf-8"><style>
body {{ margin: 0; width: 560px; background: {page}; font: 15px/1.45 "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: {text}; }}
header {{ display: flex; align-items: center; gap: 12px; padding: 10px 16px; background: {bar}; }}
.avatar {{ width: 42px; height: 42px; border-radius: 50%; background: #e0a33a; color: #1b1408; display: grid; place-items: center; font-weight: 700; font-size: 19px; }}
header b {{ display: block; font-size: 16px; }} header span {{ color: {muted}; font-size: 13px; }}
.day {{ text-align: center; margin: 14px 0 10px; }}
.day span {{ background: rgba(0,0,0,.25); color: #fff; padding: 3px 10px; border-radius: 12px; font-size: 13px; }}
.msg {{ background: {bubble}; margin: 0 56px 16px 12px; padding: 8px 12px 6px; border-radius: 14px 14px 14px 4px; white-space: pre-wrap; }}
a {{ color: {link}; text-decoration: none; }}
time {{ display: block; text-align: right; color: {muted}; font-size: 12px; margin-top: 2px; }}
</style>
<header><div class="avatar">M</div><div><b>MailBrief</b><span>bot</span></div></header>
<div class="day"><span>Wednesday, 11 March</span></div>
<div class="msg">{body}<time>07:30</time></div>"""


def main() -> None:
    body = links.to_html(DIGEST, {n: f"invented-{n}" for n in range(1, 18)})
    out = Path(__file__).resolve().parent.parent / "website" / "assets"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chromium")  # the full build `playwright install chromium --no-shell` gives
        page = browser.new_page(viewport={"width": 560, "height": 400}, device_scale_factor=2)
        for name, colours in THEMES.items():
            page.set_content(PAGE.format(body=body, **colours))
            page.screenshot(path=out / f"showcase-{name}.png", full_page=True)
        browser.close()


if __name__ == "__main__":
    main()
