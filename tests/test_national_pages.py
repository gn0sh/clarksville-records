"""Daylight Digest page builder (sitegen/national_pages.py; docs/architecture/daylight-national.md 1a, 3.4, 3.5, 4.0,
4.3, 6, 7a, 11; task B4). Problem keys: privacy-withhold/national-prefix (consumer 3: the coming-up page prints items
only from the JSON, a withheld government the fixed label), national/csp-jsonp-gadget (the Census in no CSP but the
frame's), national-switch/byte-identical (off: nothing changes; on: only the three fixed fragments and new files).

The switch tests build the fixture site (about a second) for the pages target; the real-data tests make the feeds
from data/ through the build's loaders and skip only as tests/test_national_clarksville.py does."""
import copy
import html as html_mod
import json
import os
import re
import shutil
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import markupsafe
import pytest
import yaml

from sitegen import build as build_mod, config, county_agendas
from sitegen import national as nat
from sitegen import national_clarksville as ncl
from sitegen import national_pages as npg

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "site" / "fixtures" / "facts.sample.json"
FIXTURE_SEATS = ROOT / "site" / "fixtures" / "seats.sample.yml"
FIXTURE_DISTRICTS = ROOT / "site" / "fixtures" / "districts.sample.json"
COUNCIL_ID, COUNTY_ID = "place-4715160", "county-47125"
CENSUS = "geocoding.geo.census.gov"
BUILT_AT = datetime(2026, 11, 19, 18, 0, tzinfo=timezone.utc)
DIGEST_HTML = {"digest/index.html", "digest/covered.html", "digest/requested.html", "digest/how.html",
               "digest/geo-frame.html",
               f"digest/tn/{COUNCIL_ID}.html", f"digest/tn/{COUNTY_ID}.html"}
DIGEST_JSON = {f"digest/tn/{COUNCIL_ID}.json", f"digest/tn/{COUNTY_ID}.json"}


def _build(out: Path, national) -> Path:
    saved = config.SITE.get("national", "absent")
    try:
        if national == "absent":
            config.SITE.pop("national", None)
        else:
            config.SITE["national"] = {"enabled": national}
        build_mod.build(FIXTURE, out, internal=True, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS,
                        target="pages", today=date(2026, 11, 19))
    finally:
        if saved == "absent":
            config.SITE.pop("national", None)
        else:
            config.SITE["national"] = saved
    return out


def _tree(out: Path) -> dict[str, bytes]:
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def sites(tmp_path_factory):
    base = tmp_path_factory.mktemp("national")
    return {k: _tree(_build(base / k / "site", v)) for k, v in (("absent", "absent"), ("off", False), ("on", True))}


@pytest.fixture(scope="module")
def page_labels():
    return npg.load_page_labels()


@pytest.fixture(scope="module")
def loaded():
    return nat.load_all()


# --- the switch ----------------------------------------------------------------------------------------------------

def test_shipped_switch_is_off():
    assert config.SITE["national"] == {"enabled": False}
    assert npg.enabled() is False


@pytest.mark.parametrize("block", [{"enabled": "yes"}, {"enabled": 1}, {"enable": True}, {"enabled": True, "x": 1},
                                   "on", []])
def test_switch_refuses_anything_but_true_or_false(block):
    with pytest.raises(npg.NationalBuildError):
        npg.enabled({"national": block})


def test_switch_off_writes_no_digest_file_and_changes_no_page(sites):
    """national-switch/byte-identical: off is byte for byte the build without the block, writes nothing under digest/,
    copies neither digest script, and leaves the Menu and the front page alone (B5 proves it against main)."""
    off = sites["off"]
    assert off == sites["absent"]
    assert not [p for p in off if p.startswith("digest/")]
    assert "static/national.js" not in off and "static/us-count.js" not in off and "static/digest.css" not in off
    assert not any(b"digest/" in body for p, body in off.items() if p.endswith(".html"))
    assert not any(b"digest.css" in body for body in off.values())
    assert b'class="digest-line"' not in off["index.html"]
    assert off["method.html"].count(npg.METHOD_SENTENCE.encode()) == 1


def test_digest_pages_carry_the_digest_notice_and_clarksville_pages_keep_theirs(sites):
    """unofficial/digest-notice: every digest page's footer and meta tags say Daylight Digest is not affiliated with any
    government it covers, never the Clarksville bodies list; pages outside digest/ keep the site notice."""
    u = config.SITE["unofficial"]
    digest = u["digest_notice"].format(site_name=config.SITE["site_name"], operator=config.SITE["operator"])
    assert "run by gnoshcodes LLC" in digest and "any government it covers" in digest
    clarksville = u["notice"].format(site_name=config.SITE["site_name"], operator=config.SITE["operator"],
                                     bodies="X")
    bodies = [b["name"] for b in u["bodies"]]
    on = sites["on"]
    pages = [p for p in on if p.startswith("digest/") and p.endswith(".html") and b"unofficial-notice" in on[p]]
    assert pages
    for p in pages:
        text = " ".join(html_mod.unescape(re.sub(r"<[^>]+>", " ", on[p].decode())).split())
        assert digest in text, p
        foot = re.search(r'<section class="unofficial-notice".*?</section>', on[p].decode(), re.S).group(0)
        foot = " ".join(html_mod.unescape(re.sub(r"<[^>]+>", " ", foot)).split())
        assert digest in foot and not any(b in foot for b in bodies), p      # not the Clarksville bodies list
        assert on[p].decode().count(html_mod.escape(digest)) >= 3, p      # footer, description, og:description
    for p, body in on.items():
        if p.endswith(".html") and not p.startswith("digest/"):
            assert digest.encode() not in body, p
    assert clarksville != digest
    for p in ("about.html", "index.html"):
        assert b"the City of Clarksville" in on[p] and digest.encode() not in on[p]


def test_a_switch_on_build_leaves_the_site_s_unofficial_block_unchanged(tmp_path):
    """Code review 9c82941a nit 3 (unofficial/no-mutation-test): the digest notice is swapped in on a copy, so the
    pages built after the digest (and the next build in this process) still read the Clarksville notice and `short`.
    Nit 2 (unofficial/short-overridden): the digest pages' context keeps `short` as it is."""
    before = copy.deepcopy(config.SITE["unofficial"])
    _build(tmp_path / "site", True)
    assert config.SITE["unofficial"] == before
    pages = npg.Pages(build_mod.make_env(), {"unofficial": dict(before)}, {}, {})
    assert pages.site["unofficial"]["notice"] == before["digest_notice"]
    assert pages.site["unofficial"]["short"] == before["short"] and pages.site["switch"] is None
    assert config.SITE["unofficial"] == before


def test_switch_on_writes_the_page_set_and_no_feeds(sites):
    on = sites["on"]
    digest = {p for p in on if p.startswith("digest/")}
    assert digest == DIGEST_HTML | DIGEST_JSON
    assert not [p for p in on if p.endswith((".ics", ".xml")) and p.startswith("digest/")]      # M4
    assert "static/national.js" in on and "static/us-count.js" in on and "static/digest.css" in on
    assert set(on) - set(sites["off"]) == digest | {f"static/{n}" for n in npg.STATIC_ONLY}


def test_digest_stylesheet_is_linked_by_digest_pages_only(sites):
    """Design 0a, architecture 7a (d): static/digest.css is the digest pages' own stylesheet. Each digest page links it
    once, after style.css; the Census frame and every page outside digest/ never name it; style.css is the same file
    with the switch on or off."""
    on = sites["on"]
    assert on["static/digest.css"] == (ROOT / "site" / "static" / "digest.css").read_bytes()
    assert on["static/style.css"] == sites["off"]["static/style.css"]
    for rel, body in on.items():
        if not rel.endswith(".html"):
            assert b"digest.css" not in body or rel == "static/digest.css", rel
            continue
        html = body.decode()
        if rel in DIGEST_HTML - {"digest/geo-frame.html"}:
            root = "../" * rel.count("/")
            link = f'<link rel="stylesheet" href="{root}static/digest.css">'
            assert html.count(link) == 1 and html.count("digest.css") == 1, rel
            assert html.index(f'href="{root}static/style.css"') < html.index(link) < html.index("</head>"), rel
        else:
            assert "digest.css" not in html, rel


# The digest stylesheet's own colours (docs/design/digest-warmth.md section 6): three dawn tokens, (light, dark).
DAWN = {"--dawn": ("#FFF3E4", "#231A22"), "--dawn-2": ("#FFE3C7", "#3A2420"), "--dawn-line": ("#F0C9A6", "#5A3A2C")}
DAWN_LIGHT = ":root"
DAWN_DARK = (':root:not([data-theme="light"])', ':root[data-theme="dark"]')     # by system setting, by the page's switch
# Where brand orange may be drawn: the small sun mark (its sun and rays) and the card's sunrise edge.
ORANGE_DECORATION = {".digest-sunmark-sun", ".digest-sunmark-rays", ".digest-card::before"}
ORANGE_PROPS = {"fill", "stroke", "background"}                 # never color, border, outline or text-decoration
DAWN_PROPS = {"background", "border", "border-bottom", "box-shadow", "fill"}    # surfaces and edges, never text


def _digest_css() -> str:
    css = (ROOT / "site" / "static" / "digest.css").read_text(encoding="utf-8")
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def css_rules(rules: str) -> list[tuple[str, str, str]]:
    """(selector, property, value) of every declaration of a stylesheet without comments; a rule inside @media is
    read like any other (the innermost block is the rule)."""
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", rules):
        selector = " ".join(m.group(1).split())
        for decl in m.group(2).split(";"):
            if decl.strip():
                prop, _, value = decl.partition(":")
                out.append((selector, prop.strip(), " ".join(value.split())))
    return out


def test_digest_stylesheet_names_only_the_dawn_colours_and_loads_nothing():
    """Design 0a as digest-warmth section 6 restates it: every colour is a style.css token or one of the three dawn
    tokens, which are the only hex colours the file names (light on :root, dark on the two dark selectors style.css
    uses); no rgb or hsl, no red or green; no URL and no @import, so the pages' style-src-elem 'self' is all it needs
    (architecture section 6)."""
    rules = _digest_css()
    decls = css_rules(rules)
    assert not re.search(r"\b(rgb|hsl)a?\(", rules)
    assert not re.search(r"\b(red|green)\b|@import|url\(|//", rules)
    hexes = [(sel, prop, value) for sel, prop, value in decls if re.search(r"#[0-9a-fA-F]{3,8}\b", value)]
    want = [(DAWN_LIGHT, t, light) for t, (light, _dark) in DAWN.items()]
    want += [(sel, t, dark) for sel in DAWN_DARK for t, (_light, dark) in DAWN.items()]
    assert sorted(hexes) == sorted(want)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"--dawn[a-z0-9-]*:\s*#[0-9A-Fa-f]{6};", "", rules))
    tokens = set(re.findall(r"var\((--[a-z0-9-]+)\)", rules))
    style = (ROOT / "site" / "static" / "style.css").read_text(encoding="utf-8")
    assert tokens and all(t in DAWN or re.search(rf"^\s*{t}:", style, re.M) for t in tokens), tokens
    assert not any(re.search(rf"^\s*{t}:", style, re.M) for t in DAWN)       # style.css is not changed for the digest
    for hook in (".digest-pill-covered", ".digest-pill-not-covered-yet", ".digest-pill-cant-cover",
                 ".digest-count-btn", ".digest-err", ".digest-msg", ".digest-pick", ".digest-req-form",
                 '[data-state="sent"]', '[data-state="counted"]', '[data-state="failed"]',
                 ".digest-sunmark", ".digest-hero", ".digest-warm", ".digest-steps", ".digest-next", ".digest-month",
                 ".digest-datechip", ".digest-primary", ".digest-greet", ".digest-folded", ".digest-bodyhead"):
        assert hook in rules, hook


def test_orange_is_decoration_only_never_text_and_never_a_status():
    """digest-warmth section 6 ("Orange rule"): brand orange (--sun, with --halo) is drawn only as the sun, its rays
    and halo and the cards' sunrise edge, by fill, stroke or background; --focus only as an outline (the focus ring);
    --seal (orange for text) not at all. So no `color`, border or text decoration on a digest page is orange. The
    dawn tokens are surfaces and edges, never a text colour. The status pills use navy tokens only, and the card
    edge is one rule for every card: no selector that names a status or a pill touches an orange or dawn token."""
    decls = css_rules(_digest_css())
    assert not any("var(--seal)" in value for _s, _p, value in decls)
    for sel, prop, value in decls:
        if "var(--focus)" in value:
            assert prop == "outline", (sel, prop)
        if "var(--sun)" in value or "var(--halo)" in value:
            assert prop in ORANGE_PROPS, (sel, prop)
            assert set(x.strip() for x in sel.split(",")) <= ORANGE_DECORATION, sel
        if "var(--dawn" in value:
            assert prop in DAWN_PROPS, (sel, prop)
        if prop in ("color", "-webkit-text-fill-color", "text-decoration-color", "caret-color", "border-color"):
            assert not re.search(r"var\(--(sun|halo|seal|focus|dawn[a-z0-9-]*)\)", value), (sel, prop, value)
        if re.search(r"pill|status|data-status|digest-msg|digest-err", sel):
            assert not re.search(r"var\(--(sun|halo|seal|focus|dawn[a-z0-9-]*)\)", value), (sel, prop, value)
    # the orange is really used where the design draws it (the test above is not vacuous)
    used = {sel for sel, _p, value in decls if "var(--sun)" in value}
    assert used == {".digest-sunmark-sun", ".digest-sunmark-rays", ".digest-card::before"}
    # the pills: navy fill or outline, as before
    pills = {sel: (prop, value) for sel, prop, value in decls if sel.startswith(".digest-pill-") and prop == "color"}
    assert pills == {".digest-pill-covered": ("color", "var(--on-blue)"),
                     ".digest-pill-not-covered-yet": ("color", "var(--link)"),
                     ".digest-pill-cant-cover": ("color", "var(--link)")}
    # the sunrise edge is one rule for every card, whatever its status
    edge = [(sel, prop) for sel, prop, value in decls if "var(--sun)" in value and "card" in sel]
    assert edge == [(".digest-card::before", "background")]


def test_digest_pages_are_one_column_with_no_band_and_no_second_sun():
    """Owner, 2026-11-24 (docs/design/digest-warmth.md section 2a): every digest page is one 44rem column, left-aligned
    like the Clarksville front page's address card. Nothing bleeds into main's gutters or is pulled up over another
    part (no negative margin at all), nothing is positioned out of the flow, and the dawn band is gone: the header's
    sky draws the page's one sun."""
    rules = _digest_css()
    decls = css_rules(rules)
    assert (".digest", "max-width", "44rem") in decls
    style = (ROOT / "site" / "static" / "style.css").read_text(encoding="utf-8")
    assert re.search(r"^\.find \{[^}]*max-width: 44rem;", style, re.M)       # the Clarksville card the column matches
    for sel, prop, value in decls:
        if prop.startswith("margin") and not sel.endswith("::before"):       # the card edge fills its own card
            assert "-" not in re.sub(r"var\(--[a-z0-9-]+\)", "", value), (sel, prop, value)
        if prop == "max-width":
            assert value == "44rem", (sel, value)
        if prop == "position":
            assert value == "relative" or sel.endswith("::before"), (sel, value)
        assert "--gutter" not in value and "100vw" not in value, (sel, prop, value)
    assert "digest-dawn" not in rules
    for name in ("_dawn.html.j2", "index.html.j2", "body.html.j2", "covered.html.j2", "how.html.j2", "requested.html.j2"):
        text = (ROOT / "site" / "templates" / "digest" / name).read_text(encoding="utf-8")
        assert "digest-dawn" not in text and "dawn_band(" not in text, name
    assert "digest-dawn" not in (ROOT / "site" / "static" / "national.js").read_text(encoding="utf-8")


def test_nothing_on_a_digest_page_moves():
    """The sun does not rise: the stylesheet has no keyframes, and its only animation and transition declarations
    are the `none` of the reduced-motion rule; the drawings hold no SMIL animation."""
    rules = _digest_css()
    assert "@keyframes" not in rules
    moving = [(sel, prop, value) for sel, prop, value in css_rules(rules) if prop.startswith(("animation", "transition"))]
    assert moving and all(value == "none" for _s, _p, value in moving), moving
    assert "prefers-reduced-motion: reduce" in rules
    drawings = (ROOT / "site" / "templates" / "digest" / "_dawn.html.j2").read_text(encoding="utf-8")
    assert not re.search(r"<animate|<set\b|<text|<title|<a\b|style=|href|#[0-9a-fA-F]{3,8}\b", drawings)
    js = (ROOT / "site" / "static" / "national.js").read_text(encoding="utf-8")
    assert not re.search(r"\.animate\(|requestAnimationFrame|setInterval", js)


def _hex_tokens(css: str, selector: str) -> dict[str, str]:
    block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css).group(1)
    return dict(re.findall(r"(--[a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})\b", block))


def _contrast(a: str, b: str) -> float:
    def lum(h):
        chans = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b_ = (v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in chans)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_text_on_the_dawn_surfaces_meets_wcag_aa_in_light_and_dark():
    """WCAG 2.2 AA, recomputed from the two stylesheets: every text colour a digest page draws on a dawn surface
    (ink, muted, link, visited link) is 4.5:1 or better on --dawn, and ink, muted and link on --dawn-2 (the step
    numbers; the hero heading's wash); the focus ring is 3:1 or better on both. Brand orange would fail as text on
    --dawn in the light theme (under 4.5:1), which is one more reason it is never text."""
    style = (ROOT / "site" / "static" / "style.css").read_text(encoding="utf-8")
    digest = (ROOT / "site" / "static" / "digest.css").read_text(encoding="utf-8")
    light = {**_hex_tokens(style, ":root"), **_hex_tokens(digest, ":root")}
    dark = {**light, **_hex_tokens(style, ':root[data-theme="dark"]'), **_hex_tokens(digest, ':root[data-theme="dark"]')}
    by_system = {**light, **_hex_tokens(style, ':root:not([data-theme="light"])'),
                 **_hex_tokens(digest, ':root:not([data-theme="light"])')}
    assert {k: dark[k] for k in DAWN} == {k: by_system[k] for k in DAWN} == {k: v[1] for k, v in DAWN.items()}
    assert {k: light[k] for k in DAWN} == {k: v[0] for k, v in DAWN.items()}
    for theme in (light, dark, by_system):
        for text in ("--fg", "--muted", "--link", "--link-visited"):
            assert _contrast(theme[text], theme["--dawn"]) >= 4.5, (text, "--dawn")
        for text in ("--fg", "--muted", "--link"):
            assert _contrast(theme[text], theme["--dawn-2"]) >= 4.5, (text, "--dawn-2")
        for surface in ("--dawn", "--dawn-2"):
            assert _contrast(theme["--focus"], theme[surface]) >= 3, surface
    assert _contrast(light["--sun"], light["--dawn"]) < 4.5
    assert round(_contrast(light["--fg"], light["--dawn"]), 1) == 15.8
    assert round(_contrast(dark["--fg"], dark["--dawn"]), 1) == 15.0
    assert round(_contrast(light["--muted"], light["--dawn"]), 1) == 6.9
    assert round(_contrast(dark["--muted"], dark["--dawn"]), 1) == 7.5


def test_switch_on_changes_existing_pages_only_by_the_three_fragments(sites, page_labels):
    """7a: removing the Menu group (once per page) and the front-page line (once), and putting the Method page's
    off-build sentence back in place of its on-build one (once, design 9a), leaves every existing file equal;
    static/pages.js gains only the digest pages."""
    off, on = sites["off"], sites["on"]
    front = npg.front_fragment(page_labels)
    method = npg.method_fragment(page_labels)
    for rel, before in off.items():
        after = on[rel]
        if rel == "static/pages.js":
            listed = set(json.loads(after.decode()[len("window.BUILT_PAGES = "):-2]))
            assert listed - set(json.loads(before.decode()[len("window.BUILT_PAGES = "):-2])) == DIGEST_HTML - {
                "digest/geo-frame.html"}
            continue
        if not rel.endswith(".html") or after == before:
            assert after == before, rel
            continue
        text = after.decode()
        root = "../" * rel.count("/")
        menu = npg.menu_fragment(root, page_labels)
        assert text.count(menu) == 1, rel
        text = text.replace(menu, "", 1)
        if rel == "index.html":
            assert text.count(front) == 1
            text = text.replace(front, "", 1)
        if rel == "method.html":
            assert text.count(method) == 1 and npg.METHOD_SENTENCE not in text
            text = text.replace(method, npg.METHOD_SENTENCE, 1)
        assert text == before.decode(), rel
    changed = [r for r in off if r.endswith(".html") and on[r] != off[r]]
    assert "index.html" in changed and "about.html" in changed and "method.html" in changed


def test_method_page_names_the_digest_keys_and_links_how(sites, page_labels):
    """AC9.3, design 9a (QA national/method-page-claims): with the switch on the Method page no longer says its two
    keys are all the site keeps; it says the Clarksville pages keep two and the digest pages three more, linked to
    how.html, which lists those three keys by name."""
    on = sites["on"]["method.html"].decode()
    assert npg.METHOD_SENTENCE not in on
    assert ('These two keys are all the Clarksville pages keep in your browser. Daylight Digest pages keep three '
            'more, listed on <a href="digest/how.html">How Daylight Digest works</a>.') in on
    assert "digest/how.html" in sites["on"]
    how = sites["on"]["digest/how.html"].decode()
    for key in ("daylight.us.list", "daylight.us.requested", "daylight.us.counted"):
        assert key in how, key


def test_front_line_sits_right_after_the_address_card(sites, page_labels):
    html = sites["on"]["index.html"].decode()
    assert '</section>\n  <p class="digest-line"><a href="digest/index.html">' + page_labels["front.line"] in html


def test_fragment_insertion_fails_closed():
    labels = npg.load_page_labels()
    with pytest.raises(npg.NationalBuildError):
        npg.apply_site_fragments({"index.html": "<html>no card</html>"}, labels)
    page = '<nav id="site-nav" class="site-nav" aria-label="All pages" data-root="../">' + npg.MENU_ANCHOR * 2
    with pytest.raises(npg.NationalBuildError):
        npg.apply_site_fragments({"a/b.html": page}, labels)
    assert npg.apply_site_fragments({"x.html": "<p>no footer</p>"}, labels) == {"x.html": "<p>no footer</p>"}
    with pytest.raises(npg.NationalBuildError):
        npg.apply_site_fragments({"method.html": "<p>no sentence</p>"}, labels)
    with pytest.raises(npg.NationalBuildError):
        npg.apply_site_fragments({"method.html": npg.METHOD_SENTENCE * 2}, labels)
    with pytest.raises(npg.NationalBuildError):
        npg.menu_fragment("/", labels)


# --- CSP per file (section 6, 4.0) ---------------------------------------------------------------------------------

def _csp(html: str) -> str:
    m = re.findall(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', html)
    assert len(m) == 1
    return html_mod.unescape(m[0])


def test_csp_per_file(sites):
    on = {k: v.decode() for k, v in sites["on"].items() if k in DIGEST_HTML}
    site_csp = _csp(sites["on"]["about.html"].decode())
    index = _csp(on["digest/index.html"])
    origin = "https://buttondown.com"       # the shipped morning note's form (morning_page.form_origin)
    assert index == npg.index_csp(None, origin)
    assert "script-src 'self';" in index and "frame-src 'self'" in index
    assert f"form-action 'self' {origin}" in index and f"connect-src {origin}" in index
    for rel in ("digest/covered.html", "digest/requested.html", f"digest/tn/{COUNCIL_ID}.html",
                f"digest/tn/{COUNTY_ID}.html"):
        # the site's policy less the header's weather origin: a digest header has no sky place and asks for none
        assert _csp(on[rel]) == site_csp.replace("connect-src https://api.weather.gov", "connect-src 'none'"), rel
        assert "data-weather" not in on[rel] and "connect-src https://api.weather.gov" in site_csp, rel
    frame = on["digest/geo-frame.html"]
    assert frame == nat.geo_frame_html()
    for rel, html in on.items():
        assert (CENSUS in _csp(html)) == (rel == "digest/geo-frame.html"), rel


def test_index_csp_names_the_counter_only_while_on():
    gc = "https://daylight-gnosh.goatcounter.com"
    assert "connect-src https://buttondown.com " + gc in npg.index_csp(gc, "https://buttondown.com")
    assert "connect-src 'none'" in npg.index_csp(None, None)
    assert "form-action 'self';" in npg.index_csp(None, None)


# --- the pages ------------------------------------------------------------------------------------------------------

def test_scripts_only_on_the_entry_page(sites):
    on = {k: v.decode() for k, v in sites["on"].items() if k in DIGEST_HTML}
    for rel, html in on.items():
        if rel == "digest/geo-frame.html":
            continue
        has = "static/national.js" in html
        assert has == (rel == "digest/index.html"), rel
        assert 'id="body-switch"' not in html, rel            # 7a: no "Show records from" on digest pages
    assert "static/us-count.js" not in on["digest/index.html"]   # fixture build: analytics off


def test_header_variant_on_digest_pages(sites, page_labels):
    clark = sites["on"]["about.html"].decode()
    assert 'id="sky-moon"' in clark and 'class="sky-in"' in clark
    for rel in DIGEST_HTML - {"digest/geo-frame.html"}:
        html = sites["on"][rel].decode()
        assert f'<span class="plate-place">{page_labels["digest.place"]}</span>' in html, rel
        assert 'id="sky-moon"' not in html and 'class="sky-in"' not in html, rel


def test_report_an_error_on_fact_pages(sites):
    for rel in ("digest/index.html", "digest/covered.html", f"digest/tn/{COUNCIL_ID}.html",
                f"digest/tn/{COUNTY_ID}.html"):
        assert "Report an error on this page" in sites["on"][rel].decode(), rel


def test_entry_page_embeds_the_page_directory_and_strings(sites, loaded, page_labels):
    html = sites["on"]["digest/index.html"].decode()
    blobs = dict(re.findall(r'<script type="application/json" id="(digest-[a-z]+)">(.*?)</script>', html, re.S))
    assert set(blobs) == {"digest-pagedir", "digest-strings", "digest-config"}
    pagedir = json.loads(blobs["digest-pagedir"])
    assert pagedir["schema"] == nat.PAGEDIR_SCHEMA and pagedir["root"] == "../"
    assert set(pagedir["govs"]) == {g["gov"] for g in loaded[0].govs}
    assert pagedir["govs"][COUNTY_ID]["page"] == f"digest/tn/{COUNTY_ID}.html"
    assert json.loads(blobs["digest-strings"]) == {k: v for k, v in page_labels.items()
                                                   if k.startswith(npg.SCRIPT_GROUPS)}
    cfg = json.loads(blobs["digest-config"])
    assert cfg["frame"] == "geo-frame.html" and cfg["form_action"].startswith("https://buttondown.com/")
    # the two outside links (design section 3, "Outside links"): settings from config/national/links.yml
    assert cfg["election_url"] == "https://www.usa.gov/state-election-office"
    assert cfg["census_url"] == "https://geocoding.geo.census.gov/geocoder/"
    assert {k: cfg[k] for k in npg.LINK_KEYS} == npg.load_links()
    form = re.search(r'<form class="addr-form" id="digest-form" hidden>(.*?)</form>', html, re.S).group(1)
    assert " name=" not in form and "action=" not in form


def test_links_file_keys_are_optional_and_checked(tmp_path):
    """links.yml: a key left out is None (the script then leaves that line out whole); an unknown key, a value that
    is not a plain https URL, a wrong schema or a missing file stops the build."""
    path = tmp_path / "links.yml"

    def write(links, schema=npg.LINKS_SCHEMA, **extra):
        path.write_text(json.dumps({"schema": schema, "links": links, **extra}), encoding="utf-8")
        return path
    assert npg.load_links(write({})) == {"election_url": None, "census_url": None}
    assert npg.load_links(write({"census_url": "https://example.gov/x"})) == {
        "election_url": None, "census_url": "https://example.gov/x"}
    for bad in ({"election_url": "http://www.usa.gov/"}, {"election_url": "javascript:alert(1)"},
                {"census_url": "https://user:pw@example.gov/"}, {"census_url": "https://example.gov:8443/"},
                {"census_url": ""}, {"census_url": 3}, {"other_url": "https://example.gov/"}, ["x"]):
        with pytest.raises(npg.NationalBuildError):
            npg.load_links(write(bad))
    with pytest.raises(npg.NationalBuildError):
        npg.load_links(write({}, schema="daylight-links/2"))
    with pytest.raises(npg.NationalBuildError):
        npg.load_links(write({}, more=1))
    with pytest.raises(npg.NationalBuildError):
        npg.load_links(tmp_path / "absent.yml")


def test_no_links_given_means_null_settings(tmp_path, loaded, page_labels):
    """build_national without `links` (or with a bad value) writes both settings as null, never a bad href."""
    directory, flags, labels = loaded
    feeds = npg.build_feeds(directory, npg.council_inputs([], True), None, date(2026, 11, 19))
    for links in (None, {"election_url": "http://x.example/", "census_url": None}):
        out = tmp_path / str(bool(links))
        npg.build_national(out, build_mod.make_env(), _SITE_CTX(), directory, flags, labels, page_labels, feeds,
                           built_at=BUILT_AT, counter=None, links=links)
        html = (out / "digest" / "index.html").read_text(encoding="utf-8")
        cfg = json.loads(re.search(r'id="digest-config">(.*?)</script>', html, re.S).group(1))
        assert cfg["election_url"] is None and cfg["census_url"] is None


def test_feed_json_validates_with_no_extra_key(sites):
    for rel in DIGEST_JSON:
        feed = json.loads(sites["on"][rel])
        assert ncl.feed_errors(feed) == [], rel
        assert feed["body"]["id"] == Path(rel).stem


# --- every visible string is a label or source text (AC4.5, AC4.8) ---------------------------------------------------

BLOCKS = {"p", "h1", "h2", "h3", "h4", "li", "ul", "ol", "section", "div", "nav", "summary", "details", "label",
          "form", "button", "dt", "dd", "main", "table", "tr", "td", "th"}


class _Main(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.skip, self.out = 0, 0, []

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.depth += 1
        if tag in ("script", "style"):
            self.skip += 1
        if tag in BLOCKS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag == "main":
            self.depth -= 1
        if tag in ("script", "style"):
            self.skip -= 1
        if tag in BLOCKS:
            self.out.append("\n")

    def handle_data(self, data):
        if self.depth and not self.skip:
            self.out.append(data)


def main_text(html: str) -> str:
    p = _Main()
    p.feed(html)
    return "\n".join(" ".join(line.split()) for line in "".join(p.out).split("\n") if line.strip())


# Words base.html.j2 prints in every page's <main> (the shared frame, UX section 0), not digest labels.
FRAME_WORDS = ("Report an error on this page", "daylight.us.list", "daylight.us.requested", "daylight.us.counted")


def leftover(text: str, labels, sources) -> str:
    for s in sorted({s for s in sources if s}, key=len, reverse=True):
        text = text.replace(s, "\x00")         # a placeholder may stand where a source value was
    for lab in sorted(labels, key=len, reverse=True):
        plain = npg.LINK_RE.sub(lambda m: m.group(1), lab)
        pattern = re.sub(r"\\\{[a-z]+\\\}", ".{0,160}?", re.escape(plain))
        text = re.sub(pattern, "\n", text)
    return text.replace("\x00", "\n")


def _sources(directory, feeds) -> set[str]:
    out = {g["body_name"] for g in directory.govs} | {npg._host(g.get("official_url")) for g in directory.govs}
    for f in feeds:
        out.add(f["body"]["name"])
        for m in f["meetings"]:
            day = date.fromisoformat(m["date"])
            # the heading's date in words, and the month heading and the date chip made from the same date
            out |= {m["title"], npg.long_day(m["date"]), f"{day:%B} {day.year}", f"{day:%a}", str(day.day)}
            for it in m["items"]:
                out |= {it["text"], it["number"] or "", str((it.get("source") or {}).get("page") or "")}
    return out


def test_every_visible_string_is_a_label_or_source_text(sites, loaded, page_labels):
    directory, _flags, labels = loaded
    feeds = [json.loads(sites["on"][r]) for r in DIGEST_JSON]
    allowed = [*page_labels.values(), *labels.values(), *FRAME_WORDS]
    for rel in DIGEST_HTML - {"digest/geo-frame.html"}:
        rest = leftover(main_text(sites["on"][rel].decode()), allowed, _sources(directory, feeds))
        assert re.fullmatch(r"[\s.,·:/]*", rest), (rel, rest.strip()[:300])


def test_the_strings_check_catches_an_unlabelled_word(loaded, page_labels):
    text = main_text("<main><p>Coming up</p><p>Breaking news</p></main>")
    assert "Breaking news" in leftover(text, list(page_labels.values()), set())


# --- How Daylight Digest works ---------------------------------------------------------------------------------------

def test_how_page_exists_only_with_the_switch_on_and_lists_the_three_keys(sites):
    """T1: the Daylight Digest method text is its own page (the Clarksville Method page is untouched). It names the
    three storage keys, the counter event and the rough-location disclosure; the entry page and What we cover link it."""
    assert "digest/how.html" not in sites["off"] and "digest/how.html" not in sites["absent"]
    html = sites["on"]["digest/how.html"].decode()
    for key in ("daylight.us.list", "daylight.us.requested", "daylight.us.counted"):
        assert f"<code>{key}</code>" in html
    assert "IP address" in html and "show roughly where you are" in html        # the request paragraph: always
    assert "GoatCounter" not in html and "count-" not in html       # fixture build: no counter, so no counting text
    assert "Visits to Daylight Digest pages" not in html
    for rel in ("digest/index.html", "digest/covered.html"):
        assert 'href="how.html"' in sites["on"][rel].decode(), rel


def test_how_page_describes_the_counter_only_while_it_is_on(loaded, page_labels, tmp_path):
    """national/privacy-claims: the "Just count me" and page-visit paragraphs print exactly when `counter` is set."""
    directory, flags, labels = loaded
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas("Item"), date(2026, 11, 19),
                                  checked_at=BUILT_AT)
    gc = "https://daylight-gnosh.goatcounter.com"
    text = {}
    for k, counter in (("off", None), ("on", {"origin": gc, "endpoint": gc + "/count"})):
        out = tmp_path / k
        npg.build_national(out, build_mod.make_env(), _SITE_CTX(), directory, flags, labels, page_labels, feeds,
                           built_at=BUILT_AT, counter=counter)
        text[k] = (out / npg.HOW).read_text(encoding="utf-8")
    assert "GoatCounter" not in text["off"] and "count-" not in text["off"]
    assert "Visits to Daylight Digest" not in text["off"] and "IP address" in text["off"]
    assert "GoatCounter" in text["on"] and "count-" in text["on"]
    assert "page address" in text["on"] and "screen size" in text["on"]


# --- labels and their links ---------------------------------------------------------------------------------------

def test_label_html_escapes_values_and_makes_one_link():
    out = npg.label_html("Checked {date}. [Source]", "https://e.gov/?a=1&b=<2>", ext=True, date="<b>x</b>")
    assert str(out) == ('Checked &lt;b&gt;x&lt;/b&gt;. <a href="https://e.gov/?a=1&amp;b=&lt;2&gt;" '
                        'rel="noopener noreferrer">Source</a>')
    assert str(npg.label_html("See [it]", None)) == "See it"
    assert npg.label_text("A [b] {n}", n=3) == "A b 3"
    with pytest.raises(npg.NationalBuildError):
        npg.label_text("{n} days")


def _labels_file(tmp_path, extra: str) -> Path:
    text = npg.PAGE_LABELS_PATH.read_text(encoding="utf-8") + extra
    p = tmp_path / "page-labels.yml"
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.parametrize("extra", ["  Bad.key: x\n", "  body.two: '[a] and [b]'\n", "  body.ctl: \"a\\u202eb\"\n",
                                   "  body.empty: ' '\n", "  body.open: 'a [b'\n"])
def test_page_labels_refuse_bad_entries(tmp_path, extra):
    with pytest.raises(npg.NationalBuildError):
        npg.load_page_labels(_labels_file(tmp_path, extra))


def test_page_labels_refuse_a_missing_key(tmp_path):
    text = npg.PAGE_LABELS_PATH.read_text(encoding="utf-8").replace("  body.withheld:", "  body.unused:")
    p = tmp_path / "page-labels.yml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(npg.NationalBuildError, match="body.withheld"):
        npg.load_page_labels(p)


# --- staleness and the collection instant ----------------------------------------------------------------------------

def test_newest_record_is_the_newest_fetch_never_invented():
    srcs = [{"fetched_at": "2026-11-08"}, {"fetched_at": "2026-11-10"}, {"fetched_at": None}, "x"]
    assert npg.newest_record_at(srcs) == datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
    assert npg.newest_record_at([]) == npg.EPOCH
    assert npg.newest_day("2026-11-10T12:00:00Z") == "2026-11-10"
    assert npg.newest_day("1970-01-01T00:00:00Z") is None and npg.newest_day(None) is None


def test_feeds_claim_no_check_time(loaded):
    """national-freshness/checked-at-is-first-fetch: M1 records no check run, so every feed has last_ok_at null and
    checked_at the newest record's first fetch; the pagedir marks no daylight government stale; the page says
    "We got our newest record on" (or "no records yet"), never "Last checked" or a stale line."""
    directory, _f, _l = loaded
    feeds = npg.build_feeds(directory, {"city": ({}, [])}, _agendas("x"), date(2026, 11, 19))
    assert {f["last_ok_at"] for f in feeds.values()} == {None}
    assert feeds[COUNTY_ID]["checked_at"] == "2026-11-18T12:00:00Z"
    assert feeds[COUNCIL_ID]["checked_at"] == "1970-01-01T00:00:00Z"


def test_pages_say_newest_record_and_mark_nothing_stale(sites, page_labels):
    on = sites["on"]
    pagedir = json.loads(re.search(r'id="digest-pagedir">(.*?)</script>', on["digest/index.html"].decode(),
                                   re.S).group(1))
    assert pagedir["govs"][COUNCIL_ID]["stale"] is False and pagedir["govs"][COUNTY_ID]["stale"] is False
    council = main_text(on[f"digest/tn/{COUNCIL_ID}.html"].decode())       # a fixture build: no council records
    assert page_labels["body.no-records"] in council
    county = json.loads(on[f"digest/tn/{COUNTY_ID}.json"])
    text = main_text(on[f"digest/tn/{COUNTY_ID}.html"].decode())
    assert page_labels["body.newest"] == "We got our newest record on {date}."      # Q11 decision
    if county["checked_at"] != "1970-01-01T00:00:00Z":
        assert "We got our newest record on " in text
    for rel in DIGEST_HTML:
        assert "Last checked" not in on[rel].decode() and "couldn't check" not in on[rel].decode(), rel


# --- consumer 3 of section 11: items only from the JSON; withheld shows the fixed label ------------------------------

SENTINEL = "Approve the contract SENTINEL-ITEM-TEXT"


def _agendas(*titles):
    return {"index_url": "https://montgomerytn.gov/commission/agenda",
            "sources": [{"id": "src-1", "url": "https://mcgtn.org/a.pdf", "pages": 3, "fetched_at": "2026-11-18"}],
            "meetings": [{"id": "2026-12-14-formal", "date": "2026-12-14", "kind": "formal", "source_id": "src-1",
                          "items": [{"number": f"26-12-{n}", "title": t, "page": 1}
                                    for n, t in enumerate(titles, 1)]}]}


def _entry(directory, gov_id, **changes):
    e = dict(directory.get(COUNTY_ID))
    e.update(gov=gov_id, also=[], review=None, **changes)
    return e


def test_shown_county_prints_its_items_from_the_json(tmp_path, loaded, page_labels, monkeypatch):
    directory, flags, labels = loaded
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas(SENTINEL, "Second item"),
                                  date(2026, 11, 19), checked_at=BUILT_AT)
    feeds[COUNTY_ID]["meetings"][0]["items"][1]["text"] = "Edited in the JSON only"
    html = _render_one(tmp_path, directory, flags, labels, page_labels, feeds, COUNTY_ID)
    assert SENTINEL in html and "Edited in the JSON only" in html and "Second item" not in html


def _render_one(tmp_path, directory, flags, labels, page_labels, feeds, gov_id):
    out = tmp_path / "site"
    _build_pages_into(out, directory, flags, labels, page_labels, feeds)
    st = directory.get(gov_id)["state"].lower()
    return (out / "digest" / st / f"{gov_id}.html").read_text(encoding="utf-8")


def _noon(day: date) -> datetime:
    """A build instant on `day` (the real-data tests build their feeds from a day other than BUILT_AT's)."""
    return npg.build_instant(day, now=BUILT_AT)


def _build_pages_into(out, directory, flags, labels, page_labels, feeds, built_at=BUILT_AT):
    env = build_mod.make_env()
    npg.build_national(out, env, _SITE_CTX(), directory, flags, labels, page_labels, feeds, built_at=built_at,
                       counter=None)


def _SITE_CTX():  # noqa: N802
    """A site context from the fixture facts, as build() makes it (views.site_context)."""
    from sitegen import views
    facts = build_mod.load_facts(FIXTURE)
    ix = views.Index(facts, [])
    site = views.site_context(ix)
    site.update(internal=False, analytics=None, morning_note=None, data_as_of="2026-11-18")
    return site


@pytest.mark.parametrize("gov_id,name", [("place-4799999", "Clarksville Youth Council"),
                                          ("sdu-4799999", "Example County School Board")])
def test_withheld_government_prints_the_label_and_no_item_text(tmp_path, loaded, page_labels, gov_id, name):
    directory, flags, labels = loaded
    withheld = _entry(directory, gov_id, body_name=name, items="withheld")
    d = nat.Directory(govs=(*directory.govs, withheld), alias={})
    feeds = ncl.clarksville_feeds(d, {"city": ({}, [])}, _agendas(SENTINEL), date(2026, 11, 19),
                                  checked_at=BUILT_AT)
    assert feeds[gov_id]["meetings"][0]["items_withheld"] is True
    html = _render_one(tmp_path, d, flags, labels, page_labels, feeds, gov_id)
    assert SENTINEL not in html
    assert npg.label_text(page_labels["body.withheld"]) in " ".join(main_text(html).split())
    assert npg.label_text(page_labels["body.withheld"]) not in _render_one(
        tmp_path / "c", d, flags, labels, page_labels, feeds, COUNTY_ID)


def test_page_prints_no_items_the_json_marks_withheld_or_not_final(loaded, page_labels):
    body = {"gov": COUNTY_ID, "official_url": "https://montgomerytn.gov/commission/agenda", "platform": "daylight"}
    m = {"id": "2026-12-14-formal", "date": "2026-12-14", "time": None, "title": "Formal", "title_ours": True,
         "agenda": {"state": "final", "url": None, "status_as_posted": None}, "may_be_incomplete": False,
         "items_withheld": True, "item_count": None,
         "items": [{"seq": 1, "number": None, "text": SENTINEL, "source": {"url": None, "page": None}}]}
    assert npg.meeting_view(m, body, "America/Chicago", page_labels)["entries"] == []
    assert npg.meeting_view(m, body, "America/Chicago", page_labels)["withheld"] is True
    m2 = dict(m, items_withheld=False, agenda=dict(m["agenda"], state="not-final"))
    assert npg.meeting_view(m2, body, "America/Chicago", page_labels)["entries"] == []
    m3 = dict(m, items_withheld=False)
    v = npg.meeting_view(m3, body, "America/Chicago", page_labels)
    assert [e["text"] for e in v["entries"]] == [SENTINEL] and v["agenda_url"] == body["official_url"]


def test_links_come_from_the_entry_and_are_rechecked(loaded, page_labels):
    """national-pages/body-from-feed-not-directory: a meeting link is kept only on the entry's platform hosts, else
    the entry's official link; with no usable link at all the words print with no link (never href="")."""
    m = {"id": "2026-12-14-formal", "date": "2026-12-14", "time": None, "title": "Formal", "title_ours": True,
         "agenda": {"state": "final", "url": "https://evil.example/a.pdf", "status_as_posted": None},
         "may_be_incomplete": False, "items_withheld": False, "item_count": 1,
         "items": [{"seq": 1, "number": None, "text": "t", "source": {"url": "https://evil.example/a.pdf#page=1",
                                                                      "page": 1}}]}
    legistar = {"gov": "place-4799999", "platform": "legistar", "legistar": {"client": "salem"},
                "official_url": "https://salem.legistar.com/Calendar.aspx"}
    v = npg.meeting_view(m, legistar, "America/Chicago", page_labels)
    assert v["agenda_url"] == legistar["official_url"] and v["entries"][0]["url"] == legistar["official_url"]
    bad = dict(legistar, official_url="https://evil.example/")
    assert npg.official_of(bad) is None
    v = npg.meeting_view(m, bad, "America/Chicago", page_labels)
    assert v["agenda_url"] is None and v["entries"][0]["url"] is None
    assert str(npg.label_html("[Official agenda]", v["agenda_url"])) == "Official agenda"
    assert str(npg.label_html("[Official agenda]", "")) == "Official agenda"


def test_morning_note_and_full_pages_only_on_clarksville_bodies(tmp_path, loaded, page_labels):
    """national-pages/morning-gate: "Get the morning note" and the full Daylight link are per entry (daylight only)."""
    directory, flags, labels = loaded
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas("x"), date(2026, 11, 19),
                                  checked_at=BUILT_AT)
    site = _SITE_CTX()
    site["morning_note"] = {"signup_href": "alerts.html#note"}
    out = tmp_path / "site"
    npg.build_national(out, build_mod.make_env(), site, directory, flags, labels, page_labels, feeds,
                       built_at=BUILT_AT, counter=None)
    html = (out / "digest" / "tn" / f"{COUNTY_ID}.html").read_text(encoding="utf-8")
    assert 'href="../../alerts.html#note"' in html and 'href="../../meetings/agendas.html"' in html
    # a covered Legistar government (M2's shape) in the same build: neither link
    other = {"gov": "place-4799999", "also": [], "body_name": "Example City Council", "state": "TN",
             "status": "covered", "official_url": "https://example.legistar.com/Calendar.aspx",
             "checked": date(2026, 11, 19), "items": "withheld", "review": None, "platform": "legistar",
             "legistar": {"client": "example", "body_id": 1, "tz": "America/Chicago"},
             "host_ok": {"date": date(2026, 11, 18), "link": "https://github.com/gn0sh/clarksville-records/pull/1"}}
    feed = json.loads(json.dumps(feeds[COUNTY_ID]))
    feed["body"].update(id=other["gov"], platform="legistar", full_url=None)
    d = nat.Directory(govs=(*directory.govs, other), alias={})
    out2 = tmp_path / "site2"
    npg.build_national(out2, build_mod.make_env(), site, d, flags, labels, page_labels,
                       {**feeds, other["gov"]: feed}, built_at=BUILT_AT, counter=None)
    html = (out2 / "digest" / "tn" / f"{other['gov']}.html").read_text(encoding="utf-8")
    assert "alerts.html#note" not in html.split("<main", 1)[1].split("</main>")[0]
    assert "meetings/agendas.html" not in html and 'href=""' not in html


# --- real data ------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real():
    cfg = ncl.council_cfg("city")
    if cfg is None or not cfg["facts_path"].is_file() or not config.COUNTY_AGENDAS.is_file():
        why = "the Clarksville data is not in this checkout; set CR_ALLOW_NO_DATA=1 to skip locally"
        if os.environ.get("CR_ALLOW_NO_DATA") == "1" and not os.environ.get("CI"):
            pytest.skip(why)
        pytest.fail(why)
    agendas = county_agendas.load(config.COUNTY_AGENDAS)
    paged = {s["id"] for s in agendas["sources"] if s.get("pages")}
    today = min(date.fromisoformat(m["date"]) for m in agendas["meetings"] if m["source_id"] in paged)
    councils = {"city": (build_mod.load_facts(cfg["facts_path"]), ncl.load_listing(cfg))}
    return {"councils": councils, "agendas": agendas, "today": today}


def item_headings(html: str) -> list[str]:
    """The agenda item headings of a coming-up page, in page order: a bare <h3> in the "Next meeting" card, a bare
    <h5> in a later row (one level under their meeting's h2 or h4; digest-warmth section 6)."""
    return [main_text("<main>" + h + "</main>") for _level, h in re.findall(r"<h([35])>(.*?)</h\1>", html, re.S)]


def test_real_coming_up_pages_print_exactly_the_json_items(tmp_path, loaded, page_labels, real):
    directory, flags, labels = loaded
    feeds = npg.build_feeds(directory, real["councils"], real["agendas"], real["today"])
    assert set(feeds) == {COUNCIL_ID, COUNTY_ID}
    assert feeds[COUNTY_ID]["checked_at"] == npg.newest_record_at(real["agendas"]["sources"]).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    out = tmp_path / "site"
    _build_pages_into(out, directory, flags, labels, page_labels, feeds, built_at=_noon(real["today"]))
    for gid, feed in feeds.items():
        html = (out / "digest" / "tn" / f"{gid}.html").read_text(encoding="utf-8")
        printed = item_headings(html)
        want = [" ".join(f"{it['number'] or ''} {it['text']}".split())
                for m in feed["meetings"] for it in m["items"]]
        assert printed == want, gid
        rest = leftover(main_text(html), [*page_labels.values(), *labels.values(), *FRAME_WORDS],
                        _sources(directory, [feed]))
        assert re.fullmatch(r"[\s.,·:/]*", rest), (gid, rest.strip()[:300])
    assert any(m["items"] for m in feeds[COUNTY_ID]["meetings"])          # the county page has items to check
    assert not any(m["items"] for m in feeds[COUNCIL_ID]["meetings"])     # the council's are not stored (7)


def test_a_covered_entry_without_a_feed_source_is_refused_at_load(loaded, page_labels):
    """national-isolation (architecture 12): a covered entry the build has no feed source for is a reviewed-config
    fault, refused in the load phase; reached at data time anyway, it only degrades that entry (tier 1)."""
    directory, flags, labels = loaded
    odd = nat.Directory(govs=tuple(g for g in directory.govs if g["gov"] != COUNTY_ID)
                        + (dict(directory.get(COUNTY_ID), platform="legistar"),), alias={})
    with pytest.raises(npg.ncopy.CopyError, match="no legistar client"):
        npg.check_load(odd, flags, labels, page_labels)
    with pytest.raises(npg.NationalBuildError, match="no feed is built for platform 'boarddocs'"):
        npg.check_load(nat.Directory(govs=(dict(directory.get(COUNTY_ID), platform="boarddocs"),), alias={}),
                       flags, labels, page_labels)
    states = {}
    feeds = npg.build_feeds(odd, {"city": ({}, [])}, None, date(2026, 11, 19), states=states)
    assert states == {COUNCIL_ID: npg.BUILT, COUNTY_ID: npg.ADAPTER_ERROR}
    assert feeds[COUNTY_ID] == npg.ncopy.stale_feed(odd.get(COUNTY_ID))
    npg.check_load(directory, flags, labels, page_labels)          # the shipped directory passes


SALEM_LEGISTAR = {"gov": "place-4164900", "body_name": "Salem City Council", "state": "OR", "status": "covered",
                  "official_url": "https://salem.legistar.com/Calendar.aspx", "checked": "2026-12-01",
                  "items": "withheld", "platform": "legistar",
                  "legistar": {"client": "salem", "body_id": 138, "tz": "America/Los_Angeles"},
                  "host_ok": {"date": "2026-11-18", "link": "https://github.com/gn0sh/clarksville-records/pull/1"}}


def _folder_with(tmp_path, entry) -> Path:
    """A copy of config/national/ whose directory.yml also lists `entry` (YAML appended, the file's comments kept)."""
    folder = tmp_path / "national"
    shutil.copytree(nat.NATIONAL_DIR, folder)
    p = folder / "directory.yml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    doc["govs"].append(entry)
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return folder


@pytest.mark.parametrize("host_ok", [..., {"date": "2026-11-18"},
                                     {"date": "soon", "link": "https://github.com/gn0sh/clarksville-records/pull/1"},
                                     {"date": "2026-11-18", "link": "http://github.com/gn0sh/clarksville-records/pull/1"}],
                         ids=["missing", "no-link", "bad-date", "http-link"])
def test_the_build_refuses_a_legistar_entry_without_host_ok_and_writes_nothing(tmp_path, host_ok):
    """national/r5-not-enforced (finding 7, task D3): the build's one call stops on a non-daylight entry with no valid
    `host_ok: {date, link}`, before any digest file is written."""
    entry = dict(SALEM_LEGISTAR)
    if host_ok is ...:
        del entry["host_ok"]
    else:
        entry["host_ok"] = host_ok
    folder = _folder_with(tmp_path, entry)
    out = tmp_path / "site"
    out.mkdir()
    with pytest.raises(npg.NationalBuildError, match="host_ok"):
        npg.run(out, build_mod.make_env(), _SITE_CTX(), councils={"city": ({}, [])}, county_agendas=None,
                built_day=date(2026, 11, 19), counter=None, fixture=True, folder=folder)
    assert list(out.rglob("*")) == []


def test_the_same_legistar_entry_with_host_ok_passes_the_builds_loader(tmp_path):
    directory, _f, _l = nat.load_all(_folder_with(tmp_path, SALEM_LEGISTAR))     # the control for the test above
    assert directory.get("place-4164900")["host_ok"]["link"].startswith("https://")


@pytest.mark.parametrize("moved,slot", [(True, "CITY OR TOWN"), (False, "TOWNSHIP OR TOWN")])
def test_page_slot_follows_the_gov_flags_slot_rule(tmp_path, loaded, page_labels, moved, slot):
    """national/new-england-town-slot (AC2.11): the coming-up page's eyebrow and its What we cover row print the slot
    nat.slot_of gives (a gov-flags `slots` rule for the id's state moves a cousub to the city-or-town slot)."""
    import dataclasses
    directory, flags, labels = loaded
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas("x"), date(2026, 11, 19),
                                  checked_at=BUILT_AT)
    town = {"gov": "cousub-4712590887", "also": [], "body_name": "Example Town Board", "state": "TN",
            "status": "covered", "official_url": "https://example.legistar.com/Calendar.aspx",
            "checked": date(2026, 11, 19), "items": "withheld", "review": None, "platform": "legistar",
            "legistar": {"client": "example", "body_id": 1, "tz": "America/Chicago"},
            "host_ok": {"date": date(2026, 11, 18), "link": "https://github.com/gn0sh/clarksville-records/pull/1"}}
    feed = json.loads(json.dumps(feeds[COUNTY_ID]))
    feed["body"].update(id=town["gov"], name=town["body_name"], platform="legistar", full_url=None)
    rule = ({"state": "47", "layer": "cousub", "slot": "place"},) if moved else ()
    f2 = dataclasses.replace(flags, slots=rule)
    d = nat.Directory(govs=(*directory.govs, town), alias={})
    out = tmp_path / "site"
    npg.build_national(out, build_mod.make_env(), _SITE_CTX(), d, f2, labels, page_labels,
                       {**feeds, town["gov"]: feed}, built_at=BUILT_AT, counter=None)
    body = main_text((out / "digest" / "tn" / f"{town['gov']}.html").read_text(encoding="utf-8"))
    assert f"Tennessee · {slot}" in body
    covered = main_text((out / "digest" / "covered.html").read_text(encoding="utf-8"))
    row = covered[covered.index("Example Town Board"):][:200]
    assert slot in row and ("TOWNSHIP OR TOWN" in row) is not moved


# --- topic labels (AC4.7, AC4.8): the morning note's lists by the published item type word list ----------------------

ITEM_LI_RE = re.compile(r"<li>\s*<h([35])>(.*?)</h\1>\s*(?:<p class=\"digest-topics\">(.*?)</p>)?", re.S)
CHIP_RE = re.compile(r'<span class="chip digest-topic"><span class="sr-only">[^<]*</span>([^<]*)</span>')


def _printed_topics(html: str) -> list[tuple[str, list[str]]]:
    """(item heading text, [topic label text]) for each item on a coming-up page, in page order."""
    return [(main_text("<main>" + h + "</main>"), [html_mod.unescape(c) for c in CHIP_RE.findall(chips or "")])
            for _level, h, chips in ITEM_LI_RE.findall(html)]


def _word_list_topics(number: str | None, text: str, page_labels) -> list[str]:
    """The expected labels, read straight from config/site.yml item_types (independent of views.item_types): a
    number prefix, or a word at the start of a word of the text, any case."""
    types = {t["key"]: t for t in config.SITE["item_types"]}
    out = []
    for key, item_type in npg.TOPICS:
        t = types[item_type]
        if any((number or "").upper().startswith(p.upper()) for p in t["prefixes"]) or \
                any(re.search(r"(?<!\w)" + re.escape(w.casefold()), text.casefold()) for w in t["words"]):
            out.append(page_labels[f"body.topic-{key}"])
    return out


def test_topics_are_the_morning_note_lists_with_a_word_rule(page_labels):
    from sitegen import morning
    types = {t["key"]: t for t in config.SITE["item_types"]}
    item_types = set(types)
    assert [k for k, _ in npg.TOPICS] == ["zoning", "budget"]
    for key, item_type in npg.TOPICS:
        assert key in morning.LIST_KEYS and item_type in item_types
        # the chip is the About page's name for the item type it links to (about.html#item-types), word for word
        assert page_labels[f"body.topic-{key}"] == types[item_type]["label"]
    assert (page_labels["body.topic-zoning"], page_labels["body.topic-budget"]) == ("Rezoning", "Budget and finance")
    assert npg.item_topics(None, "Rezone 5 acres on Main St") == ["body.topic-zoning"]
    assert npg.item_topics("CZ-12-2026", "Application of A. Owner") == ["body.topic-zoning"]
    assert npg.item_topics(None, "FY27 Budget amendment") == ["body.topic-budget"]
    assert npg.item_topics(None, "A resolution appropriating funds") == ["body.topic-budget"]
    assert npg.item_topics(None, "Budget for a rezoning study") == ["body.topic-zoning", "body.topic-budget"]
    assert npg.item_topics(None, "Appoint a member") == []            # appointments are not a morning note list
    assert npg.item_topics(None, "Disbudgeted and prezoned") == []    # a word must start a word
    assert npg.item_topics(None, SENTINEL) == []


def test_topic_labels_follow_shown_items_and_never_a_withheld_meeting(tmp_path, loaded, page_labels):
    directory, flags, labels = loaded
    withheld = _entry(directory, "place-4799999", body_name="Clarksville Youth Council", items="withheld")
    d = nat.Directory(govs=(*directory.govs, withheld), alias={})
    titles = ("Resolution amending the FY27 budget", "Rezoning request for 5 acres", "Approve the minutes")
    feeds = ncl.clarksville_feeds(d, {"city": ({}, [])}, _agendas(*titles), date(2026, 11, 19), checked_at=BUILT_AT)
    out = tmp_path / "site"
    _build_pages_into(out, d, flags, labels, page_labels, feeds)
    html = (out / "digest" / "tn" / f"{COUNTY_ID}.html").read_text(encoding="utf-8")
    assert [t for _h, t in _printed_topics(html)] == [["Budget and finance"], ["Rezoning"], []]
    assert html.count('class="digest-topic-note"') == 1
    assert 'href="../../about.html#item-types"' in html
    assert '<span class="sr-only">Topic: </span>Rezoning' in html       # accessible name "Topic: ..."
    rest = leftover(main_text(html), [*page_labels.values(), *labels.values(), *FRAME_WORDS],
                    _sources(d, [feeds[COUNTY_ID]]))
    assert re.fullmatch(r"[\s.,·:/]*", rest), rest.strip()[:300]
    other = (out / "digest" / "tn" / "place-4799999.html").read_text(encoding="utf-8")
    assert "digest-topic" not in other and "Budget and finance" not in other
    # a page with no matching item prints no note
    feeds2 = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas("Approve the minutes"), date(2026, 11, 19),
                                   checked_at=BUILT_AT)
    html2 = _render_one(tmp_path / "n", directory, flags, labels, page_labels, feeds2, COUNTY_ID)
    assert "digest-topic" not in html2


# --- digest titles, Proposal A: the page summary and each meeting's "On this agenda" line -----------------------------

def _e(*topics):
    return {"topics": [f"body.topic-{t}" for t in topics]}


def test_agenda_counts_count_each_topic_in_topics_order_and_the_rest_once():
    """An item counts once under every topic it shows a chip for; `more` is the items with no chip, so an item is in
    `more` or in a topic, never both (no double count in "N more items")."""
    c = npg.agenda_counts([_e("budget"), _e("zoning"), _e(), _e("zoning", "budget"), _e("zoning"), _e()])
    assert c == {"topics": [("body.topic-zoning", 3), ("body.topic-budget", 2)], "more": 2, "total": 6}
    assert npg.agenda_counts([_e(), _e()]) == {"topics": [], "more": 2, "total": 2}
    assert npg.agenda_counts([]) == {"topics": [], "more": 0, "total": 0}


def test_agenda_line_topics_then_more_items_and_its_zero_cases(page_labels):
    L = page_labels
    assert npg.agenda_line([_e("budget"), *[_e("zoning")] * 3, *[_e()] * 14], L) == [
        "Rezoning (3)", "Budget and finance (1)", "14 more items"]
    assert npg.agenda_line([_e("zoning"), _e()], L) == ["Rezoning (1)", "1 more item"]
    assert npg.agenda_line([_e("zoning"), _e("zoning", "budget")], L) == ["Rezoning (2)", "Budget and finance (1)"]
    assert npg.agenda_line([_e()] * 18, L) == ["18 items"]           # no topic match: no invented hook
    assert npg.agenda_line([_e()], L) == ["1 item"]
    assert npg.agenda_line([], L) is None                            # no items shown: the card keeps its lines


def test_page_summary_counts_meetings_and_topics_over_the_whole_page(page_labels):
    L = page_labels
    ms = [{"entries": [_e("zoning"), _e("zoning"), _e()]}, {"entries": []}, {"entries": [_e("zoning", "budget")]}]
    assert npg.page_summary(ms, L) == ["3 meetings", "Rezoning (3)", "Budget and finance (1)"]
    assert npg.page_summary([{"entries": [_e(), _e()]}], L) == ["1 meeting", "2 items"]
    assert npg.page_summary([{"entries": [_e()]}, {"entries": []}], L) == ["2 meetings", "1 item"]
    assert npg.page_summary([{"entries": []}], L) == ["1 meeting"]
    assert npg.page_summary([], L) is None


def test_count_labels_pick_the_singular_key_for_one(page_labels):
    for key in ("body.summary-meetings", "body.on-more", "body.on-items"):
        assert key in npg.REQUIRED_PAGE_LABELS and f"{key}-one" in npg.REQUIRED_PAGE_LABELS
        assert npg.count_label(page_labels, key, 1) == npg.label_text(page_labels[f"{key}-one"], n=1)
        assert npg.count_label(page_labels, key, 0) == npg.label_text(page_labels[key], n=0)
        assert npg.count_label(page_labels, key, 7) == npg.label_text(page_labels[key], n=7)
    assert page_labels["body.summary"] == "Listed below:"          # claims no period (Legistar: today to +28 days)


def test_coming_up_page_leads_with_the_summary_and_what_is_on_each_agenda(tmp_path, loaded, page_labels):
    directory, flags, labels = loaded
    titles = ("Resolution amending the FY27 budget", "Rezoning request for 5 acres", "Rezone 2 acres on Main St",
              "Approve the minutes", "Budget for a rezoning study")
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas(*titles), date(2026, 11, 19),
                                  checked_at=BUILT_AT)
    html = _render_one(tmp_path, directory, flags, labels, page_labels, feeds, COUNTY_ID)
    text = main_text(html)
    assert "Listed below: 1 meeting · Rezoning (3) · Budget and finance (2)" in _seen(text)
    section = re.search(r'<section class="digest-meeting".*?</section>', html, re.S).group(0)
    # titles-a11y/lead-before-heading: the heading is first in the DOM (the region's name, then what is on it);
    # digest.css draws the lead line first in the card
    lines = main_text("<main>" + section + "</main>").split("\n")
    assert lines[0] == "Monday, December 14, 2026"
    assert _seen(lines[1]) == "On this agenda: Rezoning (3) · Budget and finance (2) · 1 more item"
    assert section.index("<h2") < section.index('class="digest-on"') < section.index("digest-meeting-title")
    # titles-copy/separator-sr: the dot is hidden from screen readers, which hear a comma instead
    assert section.count('<span aria-hidden="true"> · </span><span class="sr-only">, </span>') == 2
    assert " · " not in section.replace('<span aria-hidden="true"> · </span>', "")
    assert html.index('class="digest-summary"') < html.index('class="digest-next')     # the summary tops the page
    rest = leftover(text, [*page_labels.values(), *labels.values(), *FRAME_WORDS],
                    _sources(directory, [feeds[COUNTY_ID]]))
    assert re.fullmatch(r"[\s.,·:/]*", rest), rest.strip()[:300]
    assert section.count('class="digest-on"') == 1
    # no topic match: the plain item count
    feeds2 = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas("Approve the minutes", "Call to order"),
                                   date(2026, 11, 19), checked_at=BUILT_AT)
    text2 = _seen(main_text(_render_one(tmp_path / "n", directory, flags, labels, page_labels, feeds2, COUNTY_ID)))
    assert "Listed below: 1 meeting · 2 items" in text2 and "On this agenda: 2 items" in text2


def _seen(text: str) -> str:
    """Page text as the eye reads it: the screen-reader-only comma after each " · " dropped."""
    return text.replace(" · , ", " · ")


def test_page_drops_meetings_before_the_build_day(tmp_path, loaded, page_labels):
    """titles-summary/period-claim: a stale feed's past meetings never print under "Next meeting" or in the summary
    count; the build day itself still counts (in the site's zone), and the JSON stays the bound feed."""
    directory, flags, labels = loaded
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas("Rezone 2 acres"), date(2026, 11, 19),
                                  checked_at=BUILT_AT)
    county = feeds[COUNTY_ID]
    past, same_day = copy.deepcopy(county["meetings"][0]), copy.deepcopy(county["meetings"][0])
    past.update(id="2026-11-18-formal", date="2026-11-18")
    same_day.update(id="2026-11-19-formal", date="2026-11-19")
    county["meetings"] = [past, same_day, *county["meetings"]]
    out = tmp_path / "site"
    _build_pages_into(out, directory, flags, labels, page_labels, feeds)          # BUILT_AT: 2026-11-19 18:00 UTC
    html = (out / "digest" / "tn" / f"{COUNTY_ID}.html").read_text(encoding="utf-8")
    assert 'id="m-2026-11-18-formal"' not in html and "November 18, 2026" not in main_text(html)
    nxt = re.search(r'<div class="digest-next">.*?</section>', html, re.S).group(0)
    assert 'id="m-2026-11-19-formal"' in nxt
    assert "Listed below: 2 meetings" in _seen(main_text(html))
    js = json.loads((out / "digest" / "tn" / f"{COUNTY_ID}.json").read_text(encoding="utf-8"))
    assert [m["id"] for m in js["meetings"]][:2] == ["2026-11-18-formal", "2026-11-19-formal"]
    # 03:00 UTC on the 20th is still the 19th in Clarksville: the 19th's meeting stays
    late = datetime(2026, 11, 20, 3, 0, tzinfo=timezone.utc)
    _build_pages_into(tmp_path / "late", directory, flags, labels, page_labels, feeds, built_at=late)
    html2 = (tmp_path / "late" / "digest" / "tn" / f"{COUNTY_ID}.html").read_text(encoding="utf-8")
    assert 'id="m-2026-11-19-formal"' in html2 and 'id="m-2026-11-18-formal"' not in html2


def test_a_meeting_with_no_items_shown_keeps_its_current_lines(tmp_path, loaded, page_labels):
    """The city meetings (agenda not read, no items) and a withheld government's meetings get no "On this agenda"
    line; their not-posted or withheld text is unchanged."""
    directory, flags, labels = loaded
    withheld = _entry(directory, "place-4799999", body_name="Clarksville Youth Council", items="withheld")
    d = nat.Directory(govs=(*directory.govs, withheld), alias={})
    facts = {"meetings": [{"id": "2026-12-03-regular", "date": "2026-12-03", "kind": "regular", "title": "Regular"}],
             "sources": []}
    feeds = ncl.clarksville_feeds(d, {"city": (facts, [])}, _agendas("Rezone 2 acres"), date(2026, 11, 19),
                                  checked_at=BUILT_AT)
    out = tmp_path / "site"
    _build_pages_into(out, d, flags, labels, page_labels, feeds)
    for gid in ("place-4799999", COUNCIL_ID):
        html = (out / "digest" / "tn" / f"{gid}.html").read_text(encoding="utf-8")
        assert feeds[gid]["meetings"], gid
        assert 'class="digest-on"' not in html and "On this agenda" not in html, gid
        n = len(feeds[gid]["meetings"])
        assert npg.count_label(page_labels, "body.summary-meetings", n) in main_text(html), gid
    youth = (out / "digest" / "tn" / "place-4799999.html").read_text(encoding="utf-8")
    assert npg.label_text(page_labels["body.withheld"]) in " ".join(main_text(youth).split())


def test_real_county_page_20_sampled_items_match_the_word_list(tmp_path, loaded, page_labels, real):
    """AC3.3 / AC4.7 QA sample: 20 items spread over the real county page, each item's printed labels equal the
    labels the word list gives its verbatim number and text, and at least one sampled or printed item has a label."""
    directory, flags, labels = loaded
    feeds = npg.build_feeds(directory, real["councils"], real["agendas"], real["today"])
    out = tmp_path / "site"
    _build_pages_into(out, directory, flags, labels, page_labels, feeds, built_at=_noon(real["today"]))
    html = (out / "digest" / "tn" / f"{COUNTY_ID}.html").read_text(encoding="utf-8")
    items = [it for m in feeds[COUNTY_ID]["meetings"] for it in m["items"]]
    printed = _printed_topics(html)
    assert len(printed) == len(items) >= 20
    step = len(items) / 20
    for i in sorted({int(n * step) for n in range(20)}):
        it, (heading, chips) = items[i], printed[i]
        assert heading == " ".join(f"{it['number'] or ''} {it['text']}".split())
        assert chips == _word_list_topics(it["number"], it["text"], page_labels), heading
    assert any(chips for _h, chips in printed)
    assert html.count('class="digest-topic-note"') == 1


# --- 11.3 item 7: the builder sweep ------------------------------------------------------------------------------------

def _sweep(out: Path) -> set[str]:
    return {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()
            and SENTINEL in p.read_text(encoding="utf-8")}


def test_builder_sweep_sentinel_only_in_the_bound_shown_government(tmp_path, loaded, page_labels):
    """privacy-withhold/national-prefix 11.3 item 7: from fixtures holding SENTINEL-ITEM-TEXT in every source, the text
    reaches only the shown county's .json and .html. A withheld "Youth Council" under a place id and a school district
    get the county's own items handed to them as copied M2 files (the shown review stamped on): bind_feed strips them.
    The page's items equal its JSON's."""
    directory, flags, labels = loaded
    youth = _entry(directory, "place-4799999", body_name="Clarksville Youth Council", items="withheld")
    school = _entry(directory, "sdu-4799999", body_name="Example County School Board", items="withheld")
    d = nat.Directory(govs=(*directory.govs, youth, school), alias={})
    agendas = _agendas(SENTINEL)
    facts = {"meetings": [{"id": "2026-12-03-regular", "date": "2026-12-03", "kind": "regular",
                           "title": SENTINEL}], "sources": []}
    feeds = ncl.clarksville_feeds(directory, {"city": (facts, [])}, agendas, date(2026, 11, 19), checked_at=BUILT_AT)
    county = feeds[COUNTY_ID]
    assert county["review"] and any(SENTINEL in it["text"] for m in county["meetings"] for it in m["items"])
    for e in (youth, school):                       # a copied M2 file for a withheld entry, carrying items
        copied = json.loads(json.dumps(county))
        copied["body"].update(id=e["gov"], name=e["body_name"])
        feeds[e["gov"]] = copied
    out = tmp_path / "site"
    binds = {}
    npg.build_national(out, build_mod.make_env(), _SITE_CTX(), d, flags, labels, page_labels, feeds,
                       built_at=BUILT_AT, counter=None, bind_counts=binds)
    assert _sweep(out) == {f"digest/tn/{COUNTY_ID}.json", f"digest/tn/{COUNTY_ID}.html"}
    assert binds["place-4799999"].withheld_stripped == 1 and binds["sdu-4799999"].withheld_stripped == 1
    for e in (youth, school):
        written = json.loads((out / "digest" / "tn" / f"{e['gov']}.json").read_text(encoding="utf-8"))
        assert written["review"] is None and all(m["items"] == [] and m["items_withheld"] for m in
                                                 written["meetings"])
    html = (out / "digest" / "tn" / f"{COUNTY_ID}.html").read_text(encoding="utf-8")
    printed = item_headings(html)
    data = json.loads((out / "digest" / "tn" / f"{COUNTY_ID}.json").read_text(encoding="utf-8"))
    assert printed == [" ".join(f"{it['number'] or ''} {it['text']}".split())
                       for m in data["meetings"] for it in m["items"]]


def test_builder_sweep_a_stale_review_publishes_no_item(tmp_path, loaded, page_labels):
    """A copied M2 file for the shown county read under another review: stripped, counted, no sentinel anywhere."""
    directory, flags, labels = loaded
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas(SENTINEL), date(2026, 11, 19),
                                  checked_at=BUILT_AT)
    feeds[COUNTY_ID]["review"] = "0" * 64
    out = tmp_path / "site"
    binds = {}
    npg.build_national(out, build_mod.make_env(), _SITE_CTX(), directory, flags, labels, page_labels, feeds,
                       built_at=BUILT_AT, counter=None, bind_counts=binds)
    assert _sweep(out) == set()
    assert binds[COUNTY_ID].review_mismatch == 1


def test_a_feed_for_another_body_is_never_written_and_that_page_is_stale(tmp_path, loaded, page_labels, capsys):
    """11.1 row 15 and architecture 12 (tier 1): bind_feed refuses the county's feed for the council; nothing of it is
    written, the council's page and JSON are its stale feed (render-error), the county is built as usual."""
    directory, flags, labels = loaded
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas(SENTINEL), date(2026, 11, 19),
                                  checked_at=BUILT_AT)
    feeds[COUNCIL_ID] = feeds[COUNTY_ID]
    states = {}
    npg.build_national(tmp_path, build_mod.make_env(), _SITE_CTX(), directory, flags, labels, page_labels,
                       feeds, built_at=BUILT_AT, counter=None, states=states)
    assert states == {COUNCIL_ID: npg.RENDER_ERROR}
    council = json.loads((tmp_path / "digest" / "tn" / f"{COUNCIL_ID}.json").read_text(encoding="utf-8"))
    stale, _n = npg.bind_feed(npg.ncopy.stale_feed(directory.get(COUNCIL_ID)), directory.get(COUNCIL_ID))
    assert council == stale and council["meetings"] == []
    assert SENTINEL in (tmp_path / "digest" / "tn" / f"{COUNTY_ID}.json").read_text(encoding="utf-8")
    assert _sweep(tmp_path) == {f"digest/tn/{COUNTY_ID}.html", f"digest/tn/{COUNTY_ID}.json"}
    assert capsys.readouterr().out == f"::warning::National pages: {COUNCIL_ID}: render-error (BindError)\n"


def test_only_sitegen_national_reads_the_directory_file():
    """11.3 item 10, for this module: the page builder reads the directory only through sitegen.national."""
    src = (ROOT / "sitegen" / "national_pages.py").read_text(encoding="utf-8")
    assert "directory.yml" not in src and "DIRECTORY_PATH" not in src


def test_covered_page_cmcss_official_label_names_the_county_site(sites):
    # national/official-link-label-wrong-site: the entry's own `official_label`, else the generic page label
    page = sites["on"]["digest/covered.html"].decode()
    row = page[page.index("Clarksville-Montgomery County School System Board of Education"):]
    row = row[:row.index("</li>")]
    assert "Official agenda page (opens the county&#39;s site, which posts the school board&#39;s agendas)" in row
    assert "opens the government&#39;s own site" not in row


# --- digest-warmth (docs/design/digest-warmth.md): the warm layout, the same for every government --------------------

# The fixed copy the design adds or changes, word for word (sections 3 to 5). Every one is a page label; none names
# or describes a place, a government or an official.
WARM_COPY = {
    "index.eyebrow": "Daylight Digest",
    "index.h1": "Your local government,",
    "index.h1-2": "in broad daylight.",
    "index.lede": "Local governments like city councils, county commissions and school boards meet in public and decide "
                  "things like roads, zoning, schools and local taxes. Type your address to see which ones govern you "
                  "and what they take up next.",
    "index.find": "Find my local governments",
    "index.steps-h": "How it works",
    "index.step-1-h": "Type your address.",
    "index.step-1": "It goes to the Census Bureau, not to us.",
    "index.step-2-h": "Meet your local governments.",
    "index.step-2": "City or town, county, township and school district, each marked covered, not covered yet or "
                    "can't cover.",
    "index.step-3-h": "See what's coming up.",
    "index.step-3": "Their next meetings and agendas, in their own words, linked to the official document where we cover them.",
    "index.why-h": "Why look?",
    "index.why-1": "Meetings like these are where streets, schools and local taxes get decided. The "
                   "agendas are public records, and most meetings are open to anyone who walks in.",
    "index.why-2": "You don't have to speak. Knowing what's on the agenda is a good place to start.",
    "lookup.greet": "{place}, here's who governs you.",
    "lookup.greet-none": "Here's who governs this address.",
    "lookup.looked-up": "Address looked up. It was not sent to us.",
    "lookup.summary-none": "We don't read any of these yet. Each card links to the government's own agenda page, so "
                           "you can still see what's coming up there. Request the ones you want and we'll email you "
                           "if one opens.",
    "lookup.summary-none-one": "We don't read this one yet. Its card links to the government's own agenda page where "
                               "we have the link. Request it and we'll email you if it opens.",
    "body.next": "Next meeting",
    "body.later-h": "Later meetings",
    "body.more": "Show {n} later meetings, {from} to {to}",
    "body.no-time-all": "We don't have start times for this government's meetings.",
    "body.going-h": "Thinking of going?",
    "body.going": "Most local government meetings are open to the public, and you can sit in without speaking. Where "
                  "it meets and how to speak are set by the government. Start at its [official meetings page].",
    "body.no-meetings": "No upcoming meetings are posted. New ones show here after the government posts them and we "
                        "read them. [Official meetings page]",
}
# Lines the design keeps word for word (privacy, the Census line and notice, the task and its title).
KEPT_COPY = {
    "index.title": "Daylight Digest: Find your local governments",
    "index.input-label": "Your street address",
    "index.placeholder": "100 Main St, City, State",
    "index.privacy": "We never get your address and never sell anything.",
    "index.privacy-detail": "Your address goes from your browser straight to the US Census Bureau, which finds your "
                            "area. Daylight Digest never sees or keeps it. [Census privacy policy]",
    "index.census-notice": "This product uses the Census Bureau Data API but is not endorsed or certified by the "
                           "Census Bureau.",
    "index.cover-link": "See what we cover first, without typing anything",
    "index.who": "Daylight Digest is run and paid for by gnoshcodes LLC, a small software company in Clarksville, "
                 "Tennessee. It takes no ads and no political money. [Who runs this]",
    "lookup.matched": "Census matched: {line}",
    "lookup.another": "Look up another address",
    "lookup.coming-up": "See what's coming up",
    "lookup.nothing-listable": "The Census found this address, but we can't list a local government for it yet.",
    "body.no-time": "We don't have a start time for this meeting.",
    "body.not-posted": "Agenda not posted yet. [Official meetings page]",
    "body.no-records": "We have no records for this government yet.",
}


def test_warm_labels_are_the_designs_words_and_the_kept_lines_are_unchanged(page_labels):
    for key, text in {**WARM_COPY, **KEPT_COPY}.items():
        assert page_labels[key] == text, key
    script_only = {"lookup.greet", "lookup.greet-none", "lookup.summary-none", "lookup.summary-none-one"}
    assert set(WARM_COPY) - script_only <= set(npg.REQUIRED_PAGE_LABELS)
    # the greeting is one fixed sentence with one name slot, and no other label takes a place name
    assert [k for k, v in page_labels.items() if "{place}" in v] == ["lookup.greet"]
    assert npg.FIELD_RE.findall(page_labels["lookup.greet"]) == ["place"]
    assert "{" not in page_labels["lookup.greet-none"]
    # no time-of-day greeting and no countdown: the page can't know the reader's hour, and it is built once a day
    for key in WARM_COPY:
        assert not re.search(r"good (morning|afternoon|evening)|\bin \{n\} days\b|\btomorrow\b|\btonight\b",
                             page_labels[key], re.I), key


def test_warm_copy_praises_or_rates_no_one(page_labels):
    """Neutrality (spec R1 to R3; digest-warmth section 2): the warm words are about the reader and about local
    government in general. No label added or changed here holds a superlative or a word of praise or blame, and
    none says a named meeting is open: "most", never "all" and never "this meeting is open"."""
    banned = re.compile(r"\b(great|proud|pride|best|finest|hard-working|dedicated|trusted|excellent|amazing|wonderful|"
                        r"corrupt|failing|worst|bad|transparent|secretive|honest|dishonest)\b", re.I)
    for key in WARM_COPY:
        assert not banned.search(page_labels[key]), key
    for key in ("index.why-1", "body.going"):
        assert re.search(r"\bmost\b", page_labels[key], re.I), key
        assert not re.search(r"\ball (local government )?meetings\b", page_labels[key], re.I), key
    assert "this meeting is open" not in " ".join(page_labels.values()).lower()


def _views(*days, time=None):
    return [{"date": d, "time": time} for d in days]


def _laid(layout):
    return [(g["label"], [m["date"] for m in g["meetings"]]) for g in layout]


def test_meeting_layout_next_card_three_open_months_then_the_fold():
    days = ("2026-12-01", "2026-12-03", "2027-01-05", "2027-01-07", "2027-02-04", "2027-03-04", "2027-04-01",
            "2027-04-15")
    lay = npg.meeting_layout(_views(*days))
    assert lay["next"]["date"] == "2026-12-01"
    # the first three calendar months that have a meeting (the next meeting's month counts) print open
    assert _laid(lay["months"]) == [("December 2026", ["2026-12-03"]), ("January 2027", ["2027-01-05", "2027-01-07"]),
                                    ("February 2027", ["2027-02-04"])]
    assert (lay["more"]["n"], lay["more"]["from"], lay["more"]["to"]) == (3, "March 2027", "April 2027")
    assert _laid(lay["more"]["months"]) == [("March 2027", ["2027-03-04"]), ("April 2027", ["2027-04-01", "2027-04-15"])]
    # every meeting is laid out exactly once, in the order given (AC4.1; B-ISO-14)
    order = [lay["next"]["date"]] + [d for _l, ds in _laid(lay["months"]) + _laid(lay["more"]["months"]) for d in ds]
    assert order == list(days)
    # the date chip is made from the meeting's own date
    assert [(m["dow"], m["dom"]) for m in lay["months"][0]["meetings"]] == [("Thu", "3")]
    assert lay["no_time_all"] is True


def test_meeting_layout_edges():
    assert npg.meeting_layout([]) == {"next": None, "months": [], "more": None, "no_time_all": False}
    one = npg.meeting_layout(_views("2026-12-01"))
    assert one["next"]["date"] == "2026-12-01" and one["months"] == [] and one["more"] is None
    # three months or fewer: no fold
    lay = npg.meeting_layout(_views("2026-12-01", "2027-01-05", "2027-02-04"))
    assert lay["more"] is None and [label for label, _d in _laid(lay["months"])] == ["January 2027", "February 2027"]
    # the fold's one label needs more than one meeting over two months: otherwise the rest prints open
    for rest in (("2027-03-04",), ("2027-03-04", "2027-03-18")):
        lay = npg.meeting_layout(_views("2026-12-01", "2027-01-05", "2027-02-04", *rest))
        assert lay["more"] is None
        assert [d for _l, ds in _laid(lay["months"]) for d in ds] == ["2027-01-05", "2027-02-04", *rest]
    # months with no meeting don't count: December, March and June are the first three that have one
    lay = npg.meeting_layout(_views("2026-12-01", "2027-03-04", "2027-06-03", "2027-09-02", "2028-01-06"))
    assert [label for label, _d in _laid(lay["months"])] == ["March 2027", "June 2027"]
    assert (lay["more"]["n"], lay["more"]["from"], lay["more"]["to"]) == (2, "September 2027", "January 2028")
    # a time on any meeting: the page does not say "no start times" once (each meeting keeps its own line)
    some = _views("2026-12-01", "2026-12-03")
    some[1]["time"] = "6:00 PM"
    assert npg.meeting_layout(some)["no_time_all"] is False
    # a feed that is not in date order is laid out as it is, never re-sorted
    days = ["2027-05-01", "2026-12-01", "2027-01-05", "2027-02-04", "2027-03-04", "2026-12-09"]
    odd = npg.meeting_layout(_views(*days))
    flat = [odd["next"]["date"]] + [d for _l, ds in _laid(odd["months"]) + _laid((odd["more"] or {}).get("months", []))
                                    for d in ds]
    assert flat == days


WARM_DAYS = ("2026-12-14", "2026-12-21", "2027-01-11", "2027-02-08", "2027-03-08", "2027-04-12", "2027-04-26")


def _many(feeds, days=WARM_DAYS, gov=COUNTY_ID):
    """`feeds` with `gov`'s one meeting repeated on each of `days` (its own id and date; items and links kept)."""
    feed = json.loads(json.dumps(feeds[gov]))
    first = feed["meetings"][0]
    feed["meetings"] = [dict(json.loads(json.dumps(first)), id=f"{d}-formal", date=d) for d in days]
    return {**feeds, gov: feed}


@pytest.fixture(scope="module")
def warm_page(tmp_path_factory, loaded, page_labels):
    directory, flags, labels = loaded
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas("First item", "Second item"),
                                  date(2026, 11, 19), checked_at=BUILT_AT)
    out = tmp_path_factory.mktemp("warm") / "site"
    _build_pages_into(out, directory, flags, labels, page_labels, _many(feeds))
    return {"html": (out / "digest" / "tn" / f"{COUNTY_ID}.html").read_text(encoding="utf-8"),
            "feed": json.loads((out / "digest" / "tn" / f"{COUNTY_ID}.json").read_text(encoding="utf-8")),
            "council": (out / "digest" / "tn" / f"{COUNCIL_ID}.html").read_text(encoding="utf-8"),
            "index": (out / "digest" / "index.html").read_text(encoding="utf-8")}


def _main(html: str) -> str:
    return html.split('<main id="main">', 1)[1].split("</main>", 1)[0]


def _headings(html: str) -> list[tuple[int, str]]:
    return [(int(level), main_text("<main>" + inner + "</main>"))
            for level, inner in re.findall(r"<h([1-6])\b[^>]*>(.*?)</h\1>", _main(html), re.S)]


def test_coming_up_page_next_meeting_card_month_rows_and_the_fold(warm_page, page_labels):
    html, feed = _main(warm_page["html"]), warm_page["feed"]
    assert [m["date"] for m in feed["meetings"]] == list(WARM_DAYS)
    # every meeting is page text, once, in the JSON's order, each the same bare section (AC4.1, AC4.9, B-ISO-14)
    ids = re.findall(r'<section class="digest-meeting" id="m-([^"]+)" aria-labelledby="m-[^"]+-h">', html)
    assert ids == [m["id"] for m in feed["meetings"]]
    assert html.count("<section") == len(ids) + 1 and html.count('class="digest-meeting"') == len(ids)
    # the "Next meeting" card holds the first meeting and only it
    card = re.search(r'<div class="digest-next">(.*?)</div>\s*<section class="digest-warm', html, re.S).group(1)
    assert card.count("<section") == 1 and f'id="m-{ids[0]}"' in card
    assert main_text("<main>" + card + "</main>").splitlines()[0] == page_labels["body.next"]
    assert "<h2 id=" in card and "<h3>" in card and "<h4" not in card and "<h5" not in card
    # the fixed card, once, linked to the government's own official page
    going = re.findall(r'<section class="digest-warm digest-going".*?</section>', html, re.S)
    assert len(going) == 1
    assert page_labels["body.going-h"] in going[0]
    assert ('href="https://montgomerytn.gov/commission/agenda" rel="noopener noreferrer">official meetings page</a>'
            in going[0])
    # headings: h1 the government; h2 the next meeting, the card's title, "Later meetings"; h3 a month; h4 a meeting
    heads = _headings(warm_page["html"])
    assert [h for h in heads if h[0] == 1] == [(1, "Montgomery County Commission")]
    assert [text for level, text in heads if level == 2] == [
        npg.long_day(WARM_DAYS[0]), page_labels["body.going-h"], page_labels["body.later-h"]]
    months = ["December 2026", "January 2027", "February 2027", "March 2027", "April 2027"]
    assert [text for level, text in heads if level == 3 and text in months] == months
    assert [text for level, text in heads if level == 4] == [npg.long_day(d) for d in WARM_DAYS[1:]]
    assert [level for level, text in heads if text.endswith("First item")] == [3] + [5] * (len(WARM_DAYS) - 1)
    assert '<h2 class="sr-only">Later meetings</h2>' in html
    # the fold: a native toggle, closed, holding the meetings past the first three months, still page text
    assert html.count("<details") == 1 and "<details open" not in html and '<details class="digest-later">' in html
    fold = re.search(r'<details class="digest-later">(.*?)</details>', html, re.S).group(1)
    assert "<summary>Show 3 later meetings, March 2027 to April 2027</summary>" in fold
    assert re.findall(r'id="m-([^"]+)" aria', fold) == ids[4:]
    assert re.findall(r'id="m-([^"]+)" aria', html.split('<details class="digest-later">')[0]) == ids[:4]
    # a date chip per row, for the eye only
    chips = re.findall(r'<div class="digest-datechip" aria-hidden="true"><small>([A-Z][a-z]{2})</small>'
                       r'<b>(\d{1,2})</b></div>', html)
    assert chips == [(f"{date.fromisoformat(d):%a}", str(date.fromisoformat(d).day)) for d in WARM_DAYS[1:]]
    # no countdown anywhere
    assert not re.search(r"\bin \d+ days?\b|\bdays? (away|left)\b", main_text(warm_page["html"]))


def test_coming_up_page_says_no_start_time_once_for_the_rows(warm_page, page_labels, tmp_path, loaded):
    text = main_text(warm_page["html"])
    assert text.count(page_labels["body.no-time-all"]) == 1
    assert text.count(page_labels["body.no-time"]) == 1                    # the "Next meeting" card keeps its own line
    assert text.index(page_labels["body.no-time"]) < text.index(page_labels["body.going-h"]) < text.index(
        page_labels["body.no-time-all"])
    # one meeting only: its own line in the card, and no page-wide line under an empty list
    directory, flags, labels = loaded
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas("x"), date(2026, 11, 19), checked_at=BUILT_AT)
    one = main_text(_render_one(tmp_path, directory, flags, labels, page_labels, feeds, COUNTY_ID))
    assert one.count(page_labels["body.no-time"]) == 1 and page_labels["body.no-time-all"] not in one
    assert page_labels["body.later-h"] not in one


def test_coming_up_page_empty_state_is_the_same_card_and_keeps_the_going_card(warm_page, page_labels):
    """The council has no meetings in this build: the "Next meeting" card's place holds the no-meetings line with the
    sun mark, "Thinking of going?" still shows, and nothing about later meetings is printed."""
    html = _main(warm_page["council"])
    assert '<div class="digest-next digest-next-empty">' in html and '<div class="digest-next">' not in html
    empty = re.search(r'<div class="digest-next digest-next-empty">(.*?)</div>', html, re.S).group(1)
    assert 'class="digest-sunmark"' in empty
    assert npg.label_text(page_labels["body.no-meetings"]) in main_text("<main>" + empty + "</main>")
    assert html.count('class="digest-warm digest-going"') == 1
    assert "digest-meeting" not in html and "<details" not in html and page_labels["body.later-h"] not in html
    assert page_labels["body.no-time-all"] not in html


def test_two_governments_pages_have_the_same_parts(warm_page, tmp_path, loaded, page_labels):
    """AC4.9 (QA compares two bodies' pages): every coming-up page carries the same parts in the same order, whatever
    the government: the head, the "Next meeting" card (or its empty state), "Thinking of going?"."""
    def parts(html):
        found = re.findall(r'class="(digest-bodyhead|digest-next|digest-next digest-next-empty|'
                           r'digest-warm digest-going)"', _main(html))
        return [p.replace(" digest-next-empty", "") for p in found]
    assert parts(warm_page["html"]) == parts(warm_page["council"]) == [
        "digest-bodyhead", "digest-next", "digest-warm digest-going"]
    # and the words of the fixed card are the same on both
    going = [re.search(r'<section class="digest-warm digest-going".*?</section>', _main(warm_page[k]), re.S).group(0)
             for k in ("html", "council")]
    assert [re.sub(r'href="[^"]*"', "", g) for g in going][0] == [re.sub(r'href="[^"]*"', "", g) for g in going][1]


def test_no_official_link_means_no_going_card_and_no_empty_href(loaded, page_labels, tmp_path):
    directory, flags, labels = loaded
    bad = dict(directory.get(COUNTY_ID), official_url="https://montgomerytn.gov:8443/commission/agenda")
    d = nat.Directory(govs=tuple(bad if g["gov"] == COUNTY_ID else g for g in directory.govs), alias={})
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas("x"), date(2026, 11, 19), checked_at=BUILT_AT)
    html = _render_one(tmp_path, d, flags, labels, page_labels, feeds, COUNTY_ID)
    assert npg.official_of(bad) is None
    assert "digest-going" not in html and page_labels["body.going-h"] not in html
    assert 'href=""' not in html and '<div class="digest-next">' in html


def test_coming_up_page_keeps_its_one_crumb_above_the_h1_first_in_the_head(warm_page):
    html = _main(warm_page["html"])
    assert html.count('<nav class="crumb" aria-label="You are in">') == 1
    assert html.index('class="digest-bodyhead"') < html.index('<nav class="crumb"') < html.index("<h1")
    crumb = re.search(r'<nav class="crumb" aria-label="You are in">(.*?)</nav>', html, re.S).group(1)
    assert re.findall(r'href="([^"]+)"', crumb) == ["../../digest/index.html", "../../digest/covered.html"]
    # the same markup base.html.j2 writes on every other page
    base = (ROOT / "site" / "templates" / "base.html.j2").read_text(encoding="utf-8")
    line = re.search(r'<nav class="crumb" aria-label="You are in">.*?</nav>', base, re.S).group(0)
    body = (ROOT / "site" / "templates" / "digest" / "body.html.j2").read_text(encoding="utf-8")
    assert line.replace("crumbs", "head_crumbs") in body


def test_entry_page_order_one_h1_and_the_lines_kept_word_for_word(warm_page, page_labels):
    html = _main(warm_page["index"])
    text = main_text(warm_page["index"])
    heads = _headings(warm_page["index"])
    assert heads[0] == (1, "Your local government, in broad daylight.") and [lv for lv, _t in heads].count(1) == 1
    assert "| Daylight Digest: Find your local governments</title>" in warm_page["index"]
    order = ['class="digest-hero"', 'class="eyebrow"', "<h1", 'class="lede"', 'class="find digest-find"',
             'id="digest-form"', 'id="digest-privacy"',
             'class="digest-privacy-detail"', 'class="digest-cover-link"', 'class="digest-who"', 'id="digest-folded"',
             'id="digest-list"', 'id="digest-saved"', 'class="digest-steps"', 'id="digest-why-h"',
             'class="digest-how"', 'class="digest-census-notice"']
    at = [html.index(part) for part in order]
    assert at == sorted(at), sorted(zip(at, order))
    # AC1.9 and AC1.10 as amended: who runs it and "What we cover" are in view, right after the address card and its
    # privacy lines, not inside the toggle
    toggle = re.search(r'<details class="digest-how">.*?</details>', html, re.S).group(0)
    assert "gnoshcodes LLC" not in toggle and 'href="covered.html"' not in toggle
    between = html[html.index('class="digest-privacy-detail"'):html.index('id="digest-folded"')]
    assert not re.search(r"<h[1-6]|<details|<ol|<section", between)
    for key in ("index.privacy", "index.census-notice", "index.cover-link", "index.input-label"):
        assert text.count(page_labels[key]) == 1, key
    for key in ("index.privacy-detail", "index.who"):
        assert npg.label_text(page_labels[key]) in " ".join(text.split()), key
    assert f'placeholder="{page_labels["index.placeholder"]}"' in html
    assert f'<button type="submit">{page_labels["index.find"]}</button>' in html
    # three steps, each a lead and a sentence; the "Why look?" card
    steps = re.search(r'<ol class="digest-steps" role="list">(.*?)</ol>', html, re.S).group(1)
    assert re.findall(r"<li><b>(.*?)</b> (.*?)</li>", steps) == [
        (str(markupsafe.escape(page_labels[f"index.step-{n}-h"])), str(markupsafe.escape(page_labels[f"index.step-{n}"])))
        for n in (1, 2, 3)]
    why = re.search(r'<section class="digest-warm" aria-labelledby="digest-why-h">(.*?)</section>', html, re.S).group(1)
    assert [main_text("<main>" + para + "</main>") for para in re.findall(r"<p>(.*?)</p>", why, re.S)] == [
        page_labels["index.why-1"], page_labels["index.why-2"]]
    # the folded row is there, hidden until the script shows a result; the greeting's words are in the script's strings
    assert re.search(r'<div id="digest-folded" class="digest-folded" hidden>\s*<div class="digest-folded-row">\s*'
                     r'<p>Address looked up\. It was not sent to us\.</p>\s*'
                     r'<button type="button" class="more-btn" id="digest-another">Look up another address</button>', html)
    strings = json.loads(re.search(r'id="digest-strings">(.*?)</script>', html, re.S).group(1))
    assert strings["lookup.greet"] == "{place}, here's who governs you." and "lookup.greet-none" in strings
    # the builder prints no place name on the look-up page: it is the same page for every address
    assert "{place}" not in html.split('id="digest-strings"')[0]


def test_drawings_are_decoration_and_no_page_carries_inline_style(warm_page):
    """Every drawing in a digest page's <main> is aria-hidden and not focusable, holds no text, title, link or
    animation, and no element carries a style attribute or an inline colour (the pages' CSP allows none)."""
    for name in ("index", "html", "council"):
        html = _main(warm_page[name])
        svgs = re.findall(r"<svg\b[^>]*>.*?</svg>", html, re.S)
        assert svgs, name
        for svg in svgs:
            head = svg.split(">", 1)[0]
            assert 'aria-hidden="true"' in head and 'focusable="false"' in head, (name, head)
            assert not re.search(r"<(text|title|desc|a|animate\w*|set|image|use|script|style)\b", svg), (name, head)
            assert not re.search(r'\s(fill|stroke|style|href|on\w+)="', svg), (name, head)
        assert not re.search(r'\sstyle="', html), name
        bare = re.sub(r"<script.*?</script>|href=\"[^\"]*\"", "", html, flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{6}\b", bare), name
    # no band and no second sun: a page's own content starts with its head, right under the header, and its only
    # drawings are the small sun mark and the address card's lock
    for name in ("html", "council"):
        assert re.match(r'\s*<div class="digest digest-body">\s*<div class="digest-bodyhead">', _main(warm_page[name])), name
    assert re.match(r'\s*<div class="digest digest-entry" id="digest-entry" data-root="\.\./">\s*'
                    r'<div class="digest-fold digest-top">\s*<div class="digest-hero">', _main(warm_page["index"]))
    for name in ("index", "html", "council"):
        html = _main(warm_page[name])
        assert "digest-dawn" not in html, name
        assert set(re.findall(r'<svg class="([^"]+)"', html)) <= {"digest-sunmark", "digest-lock"}, name
