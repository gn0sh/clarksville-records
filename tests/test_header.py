"""One header pane on every page (owner, 2026-11-18: "i really like the date at the top of the page, but it isn't on all
the pages. i think the header pane should be consistent across the whole site"). The header is one partial,
site/templates/_header.html.j2, included by base.html.j2: the sky (sun, and the moon's place), the Menu button, the
name plate, the unofficial tag and today's date. Nothing in it depends on the page but the way back to the site's top
folder. qa/site_checks.py `header/same-on-every-page` holds every real build to it; these tests hold the fixture
build, the templates and the check itself. What the sky draws is in tests/test_moon.py."""
import re

from conftest import ROOT, ROOT_ABSOLUTE_PAGES
from qa import site_checks as SC
from sitegen import config

TEMPLATES = ROOT / "site" / "templates"


def test_every_built_page_has_the_same_header_with_the_date_line(built, pages):
    assert len(pages) > 40 and "review.html" in pages and "today.html" in pages
    assert any(rel.count("/") == 1 for rel in pages) and any(rel.count("/") >= 2 for rel in pages)   # every depth
    headers = {}
    for rel, html in pages.items():
        header = SC.site_header(html, rel)
        assert header is not None, rel                        # exactly one site header on the page
        if rel in ROOT_ABSOLUTE_PAGES:  # served for any address, so its links start at "/"
            header = header.replace('="/', '="')
        headers.setdefault(header, []).append(rel)
        assert html.index('<a class="skip" href="#main">') < html.index('<header class="site-header') \
            < html.index("</header>") < html.index('<nav class="body-switch"') < html.index('<main id="main">'), rel
    assert len(headers) == 1, {rels[0]: len(rels) for rels in headers.values()}      # the same markup everywhere
    header = next(iter(headers))
    # the date line he likes: the weekday, the place, and the date linked to the day page; filled by static/sky.js
    assert '<div class="sky-hero" id="sky-hero" data-tz="America/Chicago" hidden>' in header
    assert ('<p class="sky-day"><span class="sky-dow"><span id="sky-weekday"></span><span class="sky-in"> in Clarksville'
            '</span></span> <a class="sky-link" href="today.html"><time class="sky-date" id="sky-date"></time>') in header
    assert '<span class="sr-only">: meetings day by day</span></a></p>' in header
    # and the rest of the pane, once each: the sky's sun and moon (decoration), Menu, the name plate, the tag
    for part in ('<header class="site-header has-sky">',
                 '<div class="sky-sun-frame" aria-hidden="true"><div class="sky-sun" id="sky-sun"></div></div>',
                 '<div class="sky-moon-frame" aria-hidden="true"><span class="sky-moon" id="sky-moon" data-lat="36.53"'
                 ' data-lon="-87.36"'
                 ' data-weather="https://api.weather.gov/stations/KCKV/observations/latest" hidden></span></div>',
                 '<a id="nav-open" class="menu-btn" href="#site-nav">',
                 f'<span class="plate-name">{config.SITE_NAME}</span>',
                 f'<p class="unofficial-tag">{config.SITE["unofficial"]["tag"]}</p>'):
        assert header.count(part) == 1, part
    assert header.index('id="sky-sun"') < header.index('id="sky-moon"') < header.index('class="masthead"') \
        < header.index('id="sky-hero"')
    # nothing of one page or one body in it: no heading, no kicker, no coverage line, no current-page mark
    for word in ("<h1", "<h2", "kicker", "aria-current", "body-cover", "coverage"):
        assert word not in header, word
    # each page reaches the same places from where it is
    for rel, html in pages.items():
        raw = SC.SITE_HEADER.search(html).group(0)
        links = re.findall(r'href="([^"#][^"]*)"', raw)
        assert [SC.resolve(rel, h) for h in links] == ["index.html", "today.html"], rel


def test_the_site_check_passes_the_build_and_names_a_page_that_strays(built, pages, tmp_path):
    parsed = {rel: SC.parse(built / rel) for rel in pages}
    problems, note = SC.check_header(built, parsed)
    assert problems == [] and note == f"one header on {len(pages)} of {len(pages)} pages, with the sky and the date line"
    # a small copy of the site, then one page changed at a time
    deep = next(rel for rel in sorted(pages) if rel.count("/") >= 1)
    keep = ["index.html", "today.html", "about.html", deep]

    def site_with(change=None, drop=None):
        out = tmp_path / f"s{len(list(tmp_path.iterdir()))}"
        for rel in keep:
            if rel == drop:
                continue
            html = pages[rel]
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / rel).write_text(change(html) if change and rel == "about.html" else html, encoding="utf-8")
        rels = [r for r in keep if r != drop]
        return SC.check_header(out, {rel: SC.parse(out / rel) for rel in rels})[0]

    assert site_with() == []
    hero = re.compile(r'\s*<div class="sky-hero".*?</div>\n', re.S)
    assert hero.search(pages["about.html"])
    no_date = site_with(lambda h: hero.sub("\n", h, count=1))
    assert any(p.startswith("about.html: its header differs from the one on ") for p in no_date), no_date
    assert any("the header's date does not link the day page" in p for p in no_date), no_date
    opening, tag = '<header class="site-header has-sky">', '<p class="unofficial-tag">'
    small = site_with(lambda h: h.replace(opening, '<header class="site-header has-sky sky-small">'))
    first = min(deep, "index.html")                           # the first page that carries the usual header
    assert small == [f"about.html: its header differs from the one on {first}"], small
    kicker = site_with(lambda h: h.replace(tag, '<p class="kicker">County</p>' + tag))
    assert len(kicker) == 1 and kicker[0].startswith("about.html: its header differs"), kicker
    none = site_with(lambda h: h.replace('<header class="site-header', '<div class="site-header')
                     .replace("</header>", "</div>", 1))
    assert none == ["about.html: 0 site headers (want 1)"], none
    no_flag = site_with(lambda h: h.replace('<script src="static/js-flag.js"></script>\n', ""))
    assert no_flag == ["about.html: static/js-flag.js is not in the page's head (the date line would jump in)"], no_flag
    no_sky = site_with(lambda h: h.replace('<script src="static/sky.js" defer></script>\n', ""))
    assert no_sky == ["about.html: static/sky.js is not loaded once (no date, no sun by the hour, no moon)"], no_sky
    assert site_with(drop="today.html") == ["today.html: the day page the header's date links is not built"]


def test_the_header_is_one_partial_that_no_page_template_can_change():
    """Every page template extends base.html.j2 (directly or through another), base includes the partial once, and
    no other template writes a site header, fills a block inside it or carries a piece of the sky."""
    base = (TEMPLATES / "base.html.j2").read_text(encoding="utf-8")
    partial = (TEMPLATES / "_header.html.j2").read_text(encoding="utf-8")
    assert base.count('{% include "_header.html.j2" %}') == 1 and "<header" not in base
    include = base.index('{% include "_header.html.j2" %}')
    assert base.index('<a class="skip"') < include < base.index('<nav class="body-switch"')
    assert partial.count('<header class="site-header has-sky">') == 1 and partial.count("</header>") == 1
    # the partial has no blocks to override and reads nothing of the page: only the site's settings and `root`, plus
    # the one digest variant (docs/architecture/daylight-national.md 7a: `digest_header`, set only by
    # sitegen/national_pages.py, and its plate place `digest_place`)
    rest = partial
    # and one more site setting: the address the sky asks for the weather (config sky_weather; tests/test_weather.py)
    for v in ("{% if sp and not digest_header | default(false) %}", "{% if not digest_header | default(false) %}",
              "{% if site.sky_weather | default(none) %}"):
        assert rest.count(v) == 1, v
        rest = rest.replace(v, "")
    assert "{% block" not in partial and "{% if" not in rest
    assert rest.count("default(false)") == 1 and "if digest_header | default(false) else site.cfg.site_place }}" in rest
    # every name read inside {{ ... }} (not only the first), the filter and the keywords left out
    words = {"if", "else", "not", "and", "or", "default", "false", "true", "none"}
    used = {n for expr in re.findall(r"\{\{(.*?)\}\}", partial, re.S)
            for n in re.findall(r"[a-z_][a-z_.]*", expr) if n not in words}
    assert used == {"root", "site.site_name", "digest_place", "digest_header", "site.cfg.site_place",
                    "site.unofficial.tag", "site.cfg.site_timezone", "site.cfg.today_place", "sp.lat", "sp.lon",
                    "site.sky_weather.url"}, used
    for word in ("page_name", "body_current", "crumbs", "sky_full"):
        assert word not in partial, word
    assert "sky_full" not in base and "{% block sky %}" not in base
    assert base.count('<script src="{{ root }}static/js-flag.js"></script>') == 1
    assert base.index("static/js-flag.js") < base.index("</head>")
    parents = {}
    for tpl in sorted(TEMPLATES.glob("*.html.j2")):
        text = tpl.read_text(encoding="utf-8")
        if tpl.name not in ("base.html.j2", "_header.html.j2"):
            for word in ("site-header", "sky-hero", "sky-sun", "sky-moon", "block sky", "masthead", "js-flag.js",
                         "_header.html.j2"):
                assert word not in text, (tpl.name, word)
        m = re.search(r'\{% extends "([^"]+)" %\}', text)
        if m:
            parents[tpl.name] = m.group(1)
    pages = [name for name in parents if not name.startswith("_")]
    assert len(pages) > 35
    for name in pages:                                        # each chain of extends ends at base.html.j2
        seen = name
        while seen in parents:
            seen = parents[seen]
        assert seen == "base.html.j2", name
    # every template that is not a partial is a page that extends something
    assert {t.name for t in TEMPLATES.glob("*.html.j2") if not t.name.startswith("_")} - {"base.html.j2"} == set(pages)
