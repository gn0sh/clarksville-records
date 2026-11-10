"""Daylight M1 (docs/design/daylight): the name plate on every page, the landing sky (static/sky.js: the sun by the
viewer's clock, today's date, hidden without the script), self-hosted brand fonts and Daylight tokens in both themes."""
import json
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
    # the purpose line still leads the main content; the sky lives in the header
    assert html.index('id="sky-hero"') < html.index('<main id="main">') < html.index('<h1 class="purpose"')
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
    for block, want in ((light, {"--bg": "#F7F8FC", "--sky": "#D6E2FB", "--fg": "#141A2E", "--sun": "#EF5E35"}),
                        (auto, {"--bg": "#0D1224", "--sky": "#18245A", "--fg": "#EEF1F8", "--link": "#9DB1F5"}),
                        (forced, {"--bg": "#0D1224", "--sky": "#18245A", "--fg": "#EEF1F8", "--link": "#9DB1F5"})):
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


@pytest.mark.parametrize("fg,bg", [
    ("#141A2E", "#D6E2FB"), ("#4A5470", "#D6E2FB"), ("#4A5470", "#F7F8FC"), ("#2B4BA5", "#F7F8FC"),   # light
    ("#FFFFFF", "#2B4BA5"), ("#2B4BA5", "#E8EDFA"),
    ("#EEF1F8", "#18245A"), ("#A3ACC4", "#18245A"), ("#A3ACC4", "#0D1224"), ("#9DB1F5", "#0D1224"),   # dark
    ("#9DB1F5", "#161C33"), ("#FFFFFF", "#3D5FC4"), ("#A3ACC4", "#1B2443"),
])
def test_text_pairs_meet_aa(fg, bg):
    assert _ratio(fg, bg) >= 4.5, (fg, bg, round(_ratio(fg, bg), 2))


@pytest.mark.parametrize("bg", ["#F7F8FC", "#FFFFFF", "#0D1224", "#161C33"])
def test_sun_focus_ring_is_visible_off_the_sky(bg):
    assert _ratio("#EF5E35", bg) >= 3, bg


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
