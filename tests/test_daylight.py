"""Daylight M1 (docs/design/daylight): the name plate on every page, the landing sky (static/sky.js: the sun by the
viewer's clock, today's date, hidden without the script), self-hosted brand fonts and Daylight tokens in both themes."""
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import FIXTURE, ROOT, build, parse
from sitegen import config

SKY_JS = ROOT / "site" / "static" / "sky.js"
CSS = ROOT / "site" / "static" / "style.css"
BRAND = ROOT / "site" / "static" / "brand"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("daylight") / "build" / "site"
    build(FIXTURE, out, seats_path=None, districts_path=config.DISTRICTS_PATH)
    return out


def _pages(site):
    return {str(p.relative_to(site)): p.read_text(encoding="utf-8") for p in site.rglob("*.html")}


def test_every_page_has_the_name_plate_and_keeps_the_footer_lines(site):
    plate = (f'<span class="plate-name">{config.SITE_NAME}</span> '
             f'<span class="plate-place">{config.SITE["site_place"]}</span>')
    assert config.SITE_NAME == "Daylight" and config.SITE["site_place"] == "Clarksville-Montgomery County"
    for name, html in _pages(site).items():
        assert plate in html, name
        assert "A gnoshcodes project." in html, name
        assert 'data-ext="support"' in html, name
        nav = html[html.index('<nav id="site-nav"'):]
        for page in ("who-runs-this.html", "our-rules.html", "method.html", "corrections.html"):
            assert page + '"' in nav, (name, page)


def test_only_the_landing_has_the_sky_and_its_date_waits_for_the_script(site):
    pages = _pages(site)
    html = pages["index.html"]
    hero = next(n for n in parse(html).walk() if n.attrs.get("id") == "sky-hero")
    assert "hidden" in hero.attrs                                   # no script, no (stale) date
    assert re.search(r'<div class="sky-sun-frame" aria-hidden="true"><div class="sky-sun" id="sky-sun"></div>', html)
    assert f'<span class="sky-in"> in {config.SITE["today_place"]}</span>' in html
    assert re.search(r'<time class="sky-date" id="sky-date"></time>', html)
    assert '<script src="static/sky.js" defer></script>' in html
    # the welcome h1 still leads the main content (front-page-v2); the sky lives in the header
    assert html.index('id="sky-hero"') < html.index('<main id="main">') < html.index('<h1 id="welcome-h"')
    for name, other in pages.items():
        if name != "index.html":
            assert "sky-hero" not in other and "sky.js" not in other, name


def test_no_inline_script_or_handlers_and_no_outside_fonts(site):
    for name, html in _pages(site).items():
        for m in re.finditer(r"<script\b([^>]*)>", html):
            attrs = m.group(1)
            assert "src=" in attrs or 'type="application/json"' in attrs, (name, attrs)
        assert not re.search(r"\son[a-z]+=", html), name
        assert "fonts.googleapis" not in html and "fonts.gstatic" not in html, name
    css = CSS.read_text(encoding="utf-8")
    urls = re.findall(r'url\("([^"]+)"\)', css)
    assert urls and all(u.startswith("brand/") and (BRAND / u[len("brand/"):]).is_file() for u in urls), urls
    for family in ('"Outfit"', '"Inter"', '"JetBrains Mono"'):
        assert f"font-family: {family}" in css, family
    ofl = (BRAND / "OFL.txt").read_text(encoding="utf-8")
    assert "The JetBrains Mono Project Authors" in ofl


def test_daylight_tokens_are_set_for_light_dark_and_the_theme_attribute():
    css = CSS.read_text(encoding="utf-8")
    light = css[css.index(":root {"):css.index("@media (prefers-color-scheme: dark)")]
    auto = css[css.index(':root:not([data-theme="light"]) {'):]
    forced = css[css.index(':root[data-theme="dark"] {'):]
    navy, orange = "#0F1F3D", "#D2561B"                # the gnoshcodes brand pair (Brian, 2026-11-12)
    dark = {"--bg": "#0D1224", "--sky": "#15294F", "--fg": "#EEF1F8", "--link": "#A9BDE6", "--blue": "#4F6FB0",
            "--band-bg": "#1A2F5A", "--sun": orange, "--focus": orange}
    for block, want in ((light, {"--bg": "#F7F8FC", "--sky": "#D5DFF0", "--fg": "#141A2E", "--link": navy,
                                 "--blue": navy, "--band-bg": navy, "--sun": orange, "--focus": orange}),
                        (auto, dark), (forced, dark)):
        block = block[:block.index("}")]
        for k, v in want.items():
            assert re.search(rf"{k}:\s*{v}\b", block), (k, v)


def _luminance(hex_):
    def ch(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(hex_[i:i + 2]) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _tokens(block_start):
    css = CSS.read_text(encoding="utf-8")
    block = css[css.index(block_start):]
    block = block[:block.index("}")]
    return dict(re.findall(r"(--[a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", block))


LIGHT = _tokens(":root {")
DARK = _tokens(':root[data-theme="dark"] {')
# (theme, text token, background token), read from the CSS so a palette change is checked, not a copy of it
PAIRS = [
    (LIGHT, "--fg", "--sky"), (LIGHT, "--muted", "--sky"), (LIGHT, "--muted", "--bg"), (LIGHT, "--link", "--bg"),
    (LIGHT, "--on-blue", "--blue"), (LIGHT, "--link", "--surface-2"), (LIGHT, "--fg", "--surface-2"),
    (DARK, "--fg", "--sky"), (DARK, "--muted", "--sky"), (DARK, "--muted", "--bg"), (DARK, "--link", "--bg"),
    (DARK, "--link", "--surface"), (DARK, "--on-blue", "--blue"), (DARK, "--muted", "--surface-2"),
    (DARK, "--fg", "--surface-2"),
    # the navy recolor: the band, links on every surface and on the sky, and the orange-for-text seal
    (LIGHT, "--band-fg", "--band-bg"), (LIGHT, "--band-muted", "--band-bg"), (LIGHT, "--link", "--surface"),
    (LIGHT, "--link", "--sky"), (LIGHT, "--link-visited", "--bg"), (LIGHT, "--link-visited", "--surface-2"),
    (LIGHT, "--seal", "--bg"), (LIGHT, "--seal", "--surface"),
    (DARK, "--band-fg", "--band-bg"), (DARK, "--band-muted", "--band-bg"), (DARK, "--link", "--surface-2"),
    (DARK, "--link", "--sky"), (DARK, "--link-visited", "--bg"), (DARK, "--link-visited", "--surface-2"),
    (DARK, "--seal", "--bg"), (DARK, "--seal", "--surface"),
]
# (theme, UI token, the background it must stand 3:1 off): buttons and pills, the county dot, the initials ring,
# and the orange button on the morning-note card
UI_PAIRS = [
    (LIGHT, "--blue", "--bg"), (LIGHT, "--blue", "--surface"), (LIGHT, "--blue", "--surface-2"),
    (LIGHT, "--sun", "--surface-2"), (LIGHT, "--seal", "--surface-2"), (LIGHT, "--sun", "--band-bg"),
    (DARK, "--blue", "--bg"), (DARK, "--blue", "--surface"), (DARK, "--blue", "--surface-2"),
    (DARK, "--sun", "--surface-2"), (DARK, "--seal", "--surface-2"), (DARK, "--sun", "--band-bg"),
    (DARK, "--sun", "--sky"),
]


@pytest.mark.parametrize("theme,fg,bg", PAIRS)
def test_text_pairs_meet_aa(theme, fg, bg):
    assert _ratio(theme[fg], theme[bg]) >= 4.5, (fg, bg, round(_ratio(theme[fg], theme[bg]), 2))


@pytest.mark.parametrize("theme,fg,bg", UI_PAIRS)
def test_ui_pairs_meet_three_to_one(theme, fg, bg):
    assert _ratio(theme[fg], theme[bg]) >= 3, (fg, bg, round(_ratio(theme[fg], theme[bg]), 2))


def test_no_old_daylight_color_is_left_in_the_stylesheet_and_the_morning_card_is_the_band():
    css = CSS.read_text(encoding="utf-8")
    assert not re.search(r"#(?:2B4BA5|EF5E35)", css, re.I)
    assert re.search(r"\.mn-card \{ background: var\(--band-bg\); color: var\(--on-blue\)", css)
    assert re.search(r"\.mn-card \.btn \{[^}]*background: var\(--sun\); color: #1A0B05", css)
    for theme in (LIGHT, DARK):                       # the card's white text, and the dark words on its orange button
        assert _ratio(theme["--on-blue"], theme["--band-bg"]) >= 4.5
        assert _ratio("#1A0B05", theme["--sun"]) >= 4.5


def test_button_hover_is_a_navy_step_with_an_underline_and_list_links_are_underlined_at_rest():
    css = CSS.read_text(encoding="utf-8")
    assert "brightness(" not in css
    assert re.search(r"\.search-row button:hover, #more:hover, \.apply:hover \{ background: var\(--blue-hover\); "
                     r"text-decoration: underline", css)
    for theme in (LIGHT, DARK):
        assert _ratio(theme["--on-blue"], theme["--blue-hover"]) >= 4.5
        assert _ratio(theme["--blue-hover"], theme["--blue"]) >= 1.3        # a step you can see
    assert re.search(r"\.door a span:first-child \{ text-decoration: underline", css)
    assert re.search(r"ol\.districts a \.d-label \{ text-decoration: underline", css)
    assert re.search(r"ol\.districts \.d-holder a \{ text-decoration: underline", css)


@pytest.mark.parametrize("theme", [LIGHT, DARK])
@pytest.mark.parametrize("bg", ["--bg", "--surface"])
def test_sun_focus_ring_is_visible_off_the_sky(theme, bg):
    assert _ratio(theme["--sun"], theme[bg]) >= 3, bg


def test_focus_ring_on_the_wash_is_ink():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"\.your-seats \{[^}]*--focus: var\(--fg\)", css)
    assert re.search(r"\.menu-list a:hover:focus-visible \{ --focus: var\(--fg\)", css)
    for theme in (LIGHT, DARK):                       # ink on the #E9EDF5 wash (and its dark twin) is 3:1 or better
        assert _ratio(theme["--fg"], theme["--surface-2"]) >= 3


def test_filter_submit_button_uses_the_button_tokens():
    assert re.search(r'\.sol-filters button\[type="submit"\] \{ background: var\(--blue\);[^}]*color: var\(--on-blue\)',
                     CSS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def node():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    return shutil.which("node")


def test_sun_altitude_follows_the_clock(node):
    probe = ("const s = require(process.argv[1]);"
             "console.log(JSON.stringify([0, 3, 6, 9, 12.5, 16, 19, 22, NaN, '12'].map(s.altitude)));")
    res = subprocess.run([node, "-e", probe, str(SKY_JS)], capture_output=True, text=True, check=True)
    night, early, rise, morning, noon, afternoon, set_, late, bad, text = json.loads(res.stdout)
    assert night == early == rise == set_ == late == bad == text < 0     # below the horizon at night, and on junk
    assert noon == 1 and 0 < morning < noon and 0 < afternoon < noon


def test_hero_date_is_clarksvilles_not_the_viewers(node):
    probe = r"""
const RealDate = Date, fixed = RealDate.UTC(2026, 10, 10, 16, 0, 0);   // Wed 02:00 in Brisbane, Tue 10:00 in Chicago
global.Date = class extends RealDate { constructor(...a) { a.length ? super(...a) : super(fixed); } };
const els = {};
const mk = id => (els[id] = { hidden: true, textContent: "", attrs: {}, style: { setProperty() {} },
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }, setAttribute(k, v) { this.attrs[k] = v; } });
mk("sky-hero").attrs["data-tz"] = "America/Chicago"; mk("sky-weekday"); mk("sky-date"); mk("sky-sun");
global.window = global;
global.document = { getElementById: id => els[id] || null };
global.addEventListener = () => {};
require(process.argv[1]).render();
console.log(JSON.stringify([els["sky-weekday"].textContent, els["sky-date"].textContent,
  els["sky-date"].attrs.datetime, els["sky-hero"].hidden, new RealDate(fixed).toLocaleDateString("en-US", {weekday: "long"})]));
"""
    res = subprocess.run([node, "-e", probe, str(SKY_JS)], capture_output=True, text=True, check=True,
                         env={**os.environ, "TZ": "Australia/Brisbane"})
    weekday, date, iso, hidden, viewer_weekday = json.loads(res.stdout)
    assert viewer_weekday == "Wednesday"             # the viewer's own zone is already on the next day
    assert (weekday, date, iso, hidden) == ("Tuesday", "November 10", "2026-11-10", False)


def test_council_seat_note_and_cite_links_stay_inline_and_underlined():
    """a11y/link-affordance/council-seats-note-cite: ol.districts a (flex, padding, no underline) styles the home page's
    row links; the member-name and "(source: p. N)" links in a council seat's note must stay inline and underlined
    (SC 1.4.1), while the home rows and the holder-name underline are unchanged."""
    css = CSS.read_text(encoding="utf-8")
    reset = re.search(r"^ol\.council-seats \.d-note a, ol\.council-seats \.d-printed a \{([^}]*)\}", css, re.M)
    assert reset, "no reset rule for the seat note/cite links"
    body = reset.group(1)
    assert re.search(r"display: inline;", body)
    assert re.search(r"padding: 0;", body) and re.search(r"min-height: 0;", body)
    assert re.search(r"text-decoration: underline;", body)
    # The reset outranks ol.districts a (0,1,2) and the 900px rule, and no later rule takes the underline away.
    assert css.index(reset.group(0)) > css.index("ol.districts a { display: flex;")
    assert not re.search(r"ol\.council-seats \.d-(note|printed) a[^{]*\{[^}]*text-decoration: none", css)
    # The home rows and holder names keep their styling.
    assert "ol.districts a { display: flex; gap: 10px; padding: 7px 4px; min-height: 40px; align-items: baseline; " \
           "text-decoration: none; }" in css
    assert re.search(r"ol\.districts \.d-holder a \{ text-decoration: underline", css)
    # The template still puts every note and cite link inside .d-note / .d-printed.
    tpl = (ROOT / "site" / "templates" / "council_home.html.j2").read_text(encoding="utf-8")
    li = re.search(r'<ol class="districts council-seats">(.*?)</ol>', tpl, re.S).group(1)
    for part in re.split(r'(?=<span class="d-(?:label|holder|printed|note))', li):
        if "<a " in part:
            assert part.startswith(('<span class="d-holder', '<span class="d-printed', '<span class="d-note')), part[:60]


def test_council_seat_printed_line_and_note_sit_on_their_own_line_without_a_leading_colon():
    """layout/council-seat-note-wrap: the printed-name line and the note always take their own line under the
    holder's name (flex-basis 100%, indented to the name), and neither starts with ": ", which wrapped on phones to an
    orphan colon."""
    css = CSS.read_text(encoding="utf-8")
    rule = re.search(r"^ol\.council-seats \.d-printed, ol\.council-seats \.d-note \{([^}]*)\}", css, re.M)
    assert rule, "no own-line rule for the seat printed line and note"
    assert "flex-basis: 100%;" in rule.group(1)
    assert "padding-left: calc(5.5em + 14px);" in rule.group(1)
    assert re.search(r"ol\.council-seats li \{ display: flex; flex-wrap: wrap; gap: 4px 10px;", css)
    assert re.search(r"ol\.council-seats \.d-label \{ min-width: 5\.5em;", css)
    tpl = (ROOT / "site" / "templates" / "council_home.html.j2").read_text(encoding="utf-8")
    for cls in ("d-printed", "d-note"):
        m = re.search(r'<span class="' + cls + r' muted">(.{0,12})', tpl)
        assert m and not re.match(r"\s*:", m.group(1)), (cls, m and m.group(1))
