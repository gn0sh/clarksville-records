"""qa/site_checks.py with Daylight Digest on (task B13; docs/architecture/daylight-national.md 4.0, 6, 7a).

header/same-on-every-page: pages outside digest/ keep exactly the old rule; a digest page carries the usual header after
the three named substitutions (plate place, no moon, no sky-in span) and nothing else. switch/on-every-page: one switch
with unchanged options outside digest/, none on a digest page. digest/csp: the per-file policies (the Census in no CSP
but the frame's, exactly sitegen.national.geo_frame_csp; the parent's script-src 'self'). The scoped exemptions other
checks needed (each naming the digest/ prefix) are tested here too. Problem key: national/csp-jsonp-gadget.

Builds the fixture site (about a second each) with config national.enabled on, and once off."""
import json
import re
import shutil
from datetime import date

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS
from qa import site_checks as SC
from sitegen import build as build_mod, config
from sitegen import national as nat

# pages the build must have at least; the counts below come from the build itself (later tasks add digest pages)
KNOWN_DIGEST = ["digest/index.html", "digest/covered.html", "digest/requested.html",
                "digest/tn/place-4715160.html", "digest/tn/county-47125.html"]


def _digest(site) -> list[str]:
    """The built digest/ pages a visitor opens (all but the geo frame)."""
    return sorted(p.relative_to(site).as_posix() for p in (site / "digest").rglob("*.html")
                  if p.relative_to(site).as_posix() != "digest/geo-frame.html")


def _build(out, on: bool):
    saved = config.SITE.get("national", "absent")
    config.SITE["national"] = {"enabled": on}
    try:
        build_mod.build(FIXTURE, out, internal=False, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS,
                        target="pages", today=date(2026, 11, 19))
    finally:
        if saved == "absent":
            config.SITE.pop("national", None)
        else:
            config.SITE["national"] = saved
    return out


@pytest.fixture(scope="module")
def built_on(tmp_path_factory):
    return _build(tmp_path_factory.mktemp("digest-on") / "site", True)


@pytest.fixture(scope="module")
def built_off(tmp_path_factory):
    return _build(tmp_path_factory.mktemp("digest-off") / "site", False)


@pytest.fixture
def site(built_on, tmp_path):
    """A fresh copy of the switch-on build, to change one file at a time."""
    out = tmp_path / "site"
    shutil.copytree(built_on, out)
    return out


def _pages(site):
    return {p.relative_to(site).as_posix(): SC.parse(p) for p in site.rglob("*.html")}


def _edit(site, rel, fn):
    p = site / rel
    new = fn(p.read_text(encoding="utf-8"))
    assert new != p.read_text(encoding="utf-8"), f"the change to {rel} changed nothing"
    p.write_text(new, encoding="utf-8")


def _header(site, rel):
    return SC.SITE_HEADER.search((site / rel).read_text(encoding="utf-8")).group(0)


def _set_header(site, rel, header):
    _edit(site, rel, lambda h: SC.SITE_HEADER.sub(lambda m: header, h, count=1))


def _usual_at(site, rel):
    """about.html's (the usual) header as a page at `rel`'s depth would carry it."""
    return _header(site, "about.html").replace('href="', 'href="' + "../" * rel.count("/"))


def test_the_build_has_the_digest_pages(built_on, built_off):
    assert set(KNOWN_DIGEST) | {SC.DIGEST_FRAME} <= set(_pages(built_on))
    assert not (built_off / "digest").exists()


# --- header/same-on-every-page ----------------------------------------------------------------------------------------

def test_header_passes_the_build_with_the_digest_variant(built_on):
    pages = SC.site_pages(_pages(built_on))
    problems, note = SC.check_header(built_on, pages)
    assert problems == []
    n = len(_digest(built_on))
    assert note.endswith(f"its digest variant on {n} of {n} digest/ pages"), note
    # the variant is the three substitutions and nothing else
    usual, digest = _header(built_on, "about.html"), _header(built_on, "digest/covered.html").replace('href="../', 'href="')
    assert 'class="sky-moon"' in usual and 'class="sky-in"' in usual and "United States" not in usual
    assert 'class="sky-moon"' not in digest and 'class="sky-in"' not in digest
    assert '<span class="plate-place">United States</span>' in digest
    assert SC.digest_header(usual) == (digest, [])


def test_header_off_build_is_checked_as_before(built_off):
    problems, note = SC.check_header(built_off, _pages(built_off))
    assert problems == [] and "digest" not in note


def test_header_a_digest_page_with_the_clarksville_header_fails(site):
    _set_header(site, "digest/covered.html", _usual_at(site, "digest/covered.html"))
    problems, _ = SC.check_header(site, SC.site_pages(_pages(site)))
    assert problems == ["digest/covered.html: a digest page with the usual header, not its digest variant"], problems


@pytest.mark.parametrize("change", [
    pytest.param(lambda h: h.replace("United States", "United  States"), id="plate-place-spacing"),
    pytest.param(lambda h: h.replace('<span class="plate-place">United States</span>',
                                     '<span class="plate-place">Clarksville-Montgomery County</span>'),
                 id="old-plate-place"),
    pytest.param(lambda h: h.replace('<span id="sky-weekday"></span>',
                                     '<span id="sky-weekday"></span><span class="sky-in"> in Clarksville</span>'),
                 id="sky-in-kept"),
    pytest.param(lambda h: h.replace('<div class="masthead">', '<div class="sky-moon-frame" aria-hidden="true"><span '
                                     'class="sky-moon" id="sky-moon" data-lat="36.53" data-lon="-87.36" hidden></span>'
                                     '</div>\n  <div class="masthead">'), id="moon-kept"),
    pytest.param(lambda h: h.replace('<header class="site-header has-sky">', '<header class="site-header has-sky x">'),
                 id="extra-class"),
    pytest.param(lambda h: h.replace("</header>", "<p>Digest</p></header>"), id="extra-element"),
])
def test_header_a_digest_page_with_any_other_difference_fails(site, change):
    _set_header(site, "digest/tn/county-47125.html", change(_header(site, "digest/tn/county-47125.html")))
    problems, _ = SC.check_header(site, SC.site_pages(_pages(site)))
    assert len(problems) == 1, problems
    assert problems[0].startswith("digest/tn/county-47125.html: its header is not the one on ")
    assert "three digest substitutions" in problems[0]


def test_header_a_page_outside_digest_with_the_digest_header_fails(site):
    digest = _header(site, "digest/covered.html").replace('href="../', 'href="')
    _set_header(site, "about.html", digest)
    problems, _ = SC.check_header(site, SC.site_pages(_pages(site)))
    assert any(p.startswith("about.html: its header differs from the one on ") for p in problems), problems


def test_header_scripts_and_date_link_still_hold_on_digest_pages(site):
    _edit(site, "digest/requested.html", lambda h: h.replace('<script src="../static/sky.js" defer></script>', ""))
    problems, _ = SC.check_header(site, SC.site_pages(_pages(site)))
    assert problems == ["digest/requested.html: static/sky.js is not loaded once (no date, no sun by the hour, no moon)"]


# --- switch/on-every-page ---------------------------------------------------------------------------------------------

def test_switch_passes_the_build_with_none_on_digest_pages(built_on):
    pages = SC.site_pages(_pages(built_on))
    problems, note = SC.check_switch(built_on, pages)
    assert problems == []
    n = len(_digest(built_on))
    assert note.startswith(f"the switch on {len(pages) - n} pages, options all, ")
    assert note.endswith(f"none on {n} digest/ pages"), note


def test_switch_a_digest_page_with_a_switch_fails(site):
    nav = SC.SWITCH_NAV.search((site / "about.html").read_text(encoding="utf-8")).group(0)
    _edit(site, "digest/covered.html", lambda h: h.replace('<main id="main">', nav.replace('href="', 'href="../')
                                                           + '<main id="main">', 1))
    problems, _ = SC.check_switch(site, SC.site_pages(_pages(site)))
    assert problems == ["digest/covered.html: 1 body switches on a digest page (want 0)"], problems


def test_switch_a_page_outside_digest_without_a_switch_fails(site):
    _edit(site, "about.html", lambda h: SC.SWITCH_NAV.sub("", h, count=1))
    problems, _ = SC.check_switch(site, SC.site_pages(_pages(site)))
    assert problems == ["about.html: 0 body switches (want 1)"], problems


def test_switch_an_option_to_a_digest_page_fails(site):
    _edit(site, "about.html", lambda h: re.sub(r'<a href="[^"]*" data-switch="school"',
                                               '<a href="digest/index.html" data-switch="school"', h, count=1))
    problems, _ = SC.check_switch(site, SC.site_pages(_pages(site)))
    assert "about.html: body switch option 'school' links the digest page digest/index.html" in problems, problems


# --- digest/csp -------------------------------------------------------------------------------------------------------

def _cfg(on: bool) -> dict:
    """config/site.yml as committed, with national.enabled set as the build under test had it."""
    return {**SC._site_cfg(), "national": {"enabled": on}}


def _csp(site, on: bool = True):
    return SC.check_digest_csp(site, _pages(site), _cfg(on))


def test_digest_csp_passes_the_build(built_on):
    problems, note = _csp(built_on)
    assert problems == [], problems
    assert note.startswith(f"digest/geo-frame.html holds the frame CSP of 4.0; {len(_digest(built_on))} other digest/ pages")
    frame = SC.parse(built_on / SC.DIGEST_FRAME).csp[0]
    js = SC.INLINE_SCRIPT.search((built_on / SC.DIGEST_FRAME).read_text(encoding="utf-8")).group(1)
    assert frame == nat.geo_frame_csp(js) == SC.frame_csp(js)
    index = SC.parse_csp(SC.parse(built_on / SC.DIGEST_INDEX).csp[0])
    assert index["script-src"] == ["'self'"] and index["frame-src"] == ["'self'"]
    assert "https://buttondown.com" in index["form-action"] and "https://buttondown.com" in index["connect-src"]


def test_digest_csp_is_silent_without_digest_pages(built_off):
    assert _csp(built_off, on=False) == ([], "no digest/ pages (national.enabled off)")
    # config/site.yml as committed (off): the Clarksville build passes unchanged
    assert SC.check_digest_csp(built_off, _pages(built_off)) == ([], "no digest/ pages (national.enabled off)")


def test_digest_csp_flag_on_without_digest_pages_fails(built_off):
    assert _csp(built_off, on=True) == (["digest/: national.enabled but no digest/ pages built"], "")


def test_digest_csp_flag_off_with_digest_pages_fails(built_on):
    problems, _ = _csp(built_on, on=False)
    assert len(problems) == 1 and problems[0].startswith("digest/: national.enabled is off but "), problems


def test_digest_csp_flag_absent_with_digest_pages_fails(built_on):
    cfg = {k: v for k, v in SC._site_cfg().items() if k != "national"}
    problems, _ = SC.check_digest_csp(built_on, _pages(built_on), cfg)
    assert len(problems) == 1 and problems[0].startswith("digest/: national.enabled is off but "), problems


def test_digest_csp_only_the_lookup_page_fails(site):
    for p in sorted((site / "digest").rglob("*.html")):
        if p.relative_to(site).as_posix() != SC.DIGEST_INDEX:
            p.unlink()
    problems, _ = _csp(site)
    assert "digest/geo-frame.html: not built (national.enabled on)" in problems, problems


def test_digest_csp_only_the_frame_fails(site):
    for p in sorted((site / "digest").rglob("*.html")):
        if p.relative_to(site).as_posix() != SC.DIGEST_FRAME:
            p.unlink()
    problems, _ = _csp(site)
    assert "digest/index.html: not built (national.enabled on)" in problems, problems


def _with_csp(site, rel, fn):
    _edit(site, rel, lambda h: re.sub(r'(http-equiv="Content-Security-Policy" content=")([^"]*)"',
                                      lambda m: m.group(1) + fn(m.group(2)) + '"', h, count=1))


def test_digest_csp_the_census_in_a_static_digest_page_fails(site):
    _with_csp(site, "digest/covered.html", lambda c: c.replace("script-src &#39;self&#39;",
                                                               "script-src &#39;self&#39; https://geocoding.geo.census.gov"))
    problems, _ = _csp(site)
    assert "digest/covered.html: names the Census in its CSP (only digest/geo-frame.html may)" in problems, problems


def test_digest_csp_the_census_in_the_parent_fails(site):
    _with_csp(site, SC.DIGEST_INDEX, lambda c: c.replace("script-src &#39;self&#39;",
                                                        f"script-src &#39;self&#39; {SC.CENSUS_GEOGRAPHIES}"))
    problems, _ = _csp(site)
    assert "digest/index.html: names the Census in its CSP (only digest/geo-frame.html may)" in problems
    assert any(p.startswith("digest/index.html: CSP script-src is ") for p in problems), problems


def test_digest_csp_the_geographies_path_outside_digest_fails(site):
    # the landing's address box may name the Census locations path (task F7 moves it); never the frame's path
    _with_csp(site, "about.html", lambda c: c.replace("script-src &#39;self&#39;",
                                                     f"script-src &#39;self&#39; {SC.CENSUS_GEOGRAPHIES}"))
    problems, _ = _csp(site)
    assert problems == ["about.html: names the Census geographies path in its CSP (only digest/geo-frame.html may)"]


def test_digest_csp_the_census_on_a_page_without_the_address_box_fails(site):
    _with_csp(site, "about.html", lambda c: c.replace("script-src &#39;self&#39;",
                                                     "script-src &#39;self&#39; https://www.census.gov"))
    problems, _ = _csp(site)
    assert problems == ["about.html: names the Census in its CSP without the landing address box"]


@pytest.mark.parametrize("change", [
    pytest.param(lambda c: c.replace("onelineaddress;", "onelineaddress https://example.com;"), id="extra-source"),
    pytest.param(lambda c: c.replace("default-src 'none'", "default-src 'self'"), id="default-self"),
    pytest.param(lambda c: c.replace("; form-action 'none'", ""), id="no-form-action"),
    pytest.param(lambda c: c.replace("/geographies/onelineaddress", "/"), id="whole-host"),
])
def test_digest_csp_any_other_frame_policy_fails(site, change):
    _with_csp(site, SC.DIGEST_FRAME, change)
    problems, _ = _csp(site)
    assert any(p.startswith("digest/geo-frame.html: CSP ") and " is not " in p for p in problems), problems
    assert "digest/geo-frame.html: CSP is not sitegen.national.geo_frame_csp of its script" in problems


def test_digest_csp_a_frame_script_its_hash_does_not_name_fails(site):
    _edit(site, SC.DIGEST_FRAME, lambda h: h.replace("<script>", "<script> ", 1))
    problems, _ = _csp(site)
    assert "digest/geo-frame.html: CSP is not sitegen.national.geo_frame_csp of its script" in problems, problems


def test_digest_csp_a_frame_that_loads_anything_fails(site):
    _edit(site, SC.DIGEST_FRAME, lambda h: h.replace("</body>", '<img src="x.png"></body>'))
    problems, _ = _csp(site)
    assert any(p.startswith("digest/geo-frame.html: loads or links ") for p in problems), problems


@pytest.mark.parametrize("tag", ['<form action="https://example.com">', "<IFRAME src=x>", "<Object data=x>",
                                 "<embed src=x>"])
def test_digest_csp_a_frame_with_a_form_or_embedded_content_fails(site, tag):
    _edit(site, SC.DIGEST_FRAME, lambda h: h.replace("</body>", tag + "</body>"))
    problems, _ = _csp(site)
    word = tag[1:].split()[0].split(">")[0].lower()
    assert any(p.startswith("digest/geo-frame.html: has ") and "<" + word in p for p in problems), problems


def test_digest_csp_a_missing_frame_fails(site):
    (site / SC.DIGEST_FRAME).unlink()
    problems, _ = _csp(site)
    assert "digest/geo-frame.html: not built (national.enabled on)" in problems


def test_digest_csp_the_frame_on_another_page_fails(site):
    _edit(site, "digest/tn/county-47125.html", lambda h: h.replace(
        "</main>", '<iframe sandbox="allow-scripts" src="../geo-frame.html"></iframe></main>'))
    problems, _ = _csp(site)
    assert problems == ["digest/tn/county-47125.html: names the geo frame (only digest/index.html may)"], problems


@pytest.mark.parametrize("change, key", [
    (lambda c: c.replace("connect-src https://buttondown.com", "connect-src &#39;none&#39;"), "connect-src"),
    (lambda c: c.replace("form-action &#39;self&#39; https://buttondown.com", "form-action &#39;self&#39;"), "form-action"),
    (lambda c: c.replace("frame-src &#39;self&#39;", "frame-src *"), "frame-src"),
    (lambda c: c + "; worker-src *", "worker-src"),
])
def test_digest_csp_the_parent_policy_is_exact(site, change, key):
    _with_csp(site, SC.DIGEST_INDEX, change)
    problems, _ = _csp(site)
    assert [p for p in problems if p.startswith("digest/index.html: CSP ")] and \
        all(p.startswith(f"digest/index.html: CSP {key} is ") for p in problems), problems


def test_digest_csp_a_static_page_with_the_form_origin_fails(site):
    _with_csp(site, "digest/requested.html", lambda c: c.replace(
        "form-action &#39;self&#39;", "form-action &#39;self&#39; https://buttondown.com"))
    problems, _ = _csp(site)
    assert problems == ["digest/requested.html: CSP form-action is [\"'self'\", 'https://buttondown.com'], want "
                        "[\"'self'\"]"], problems


# --- the other checks' scoped exemptions (each on digest/ only) -------------------------------------------------------

def test_external_holds_the_digest_pages(built_on):
    assert SC.check_external(SC.site_pages(_pages(built_on)), built_on, SC._site_cfg()) == []


def test_external_us_count_only_on_the_lookup_page(site):
    # (the fixture build counts nothing; the real-data build, which does, runs in the B13 handoff)
    tag = '<script src="../static/us-count.js" defer></script>'
    _edit(site, "digest/covered.html", lambda h: h.replace("</body>", tag + "</body>"))
    problems = SC.check_external(SC.site_pages(_pages(site)), site, SC._site_cfg())
    assert "digest/covered.html: loads static/us-count.js (only digest/index.html may)" in problems, problems


def test_external_a_page_outside_digest_still_meets_the_old_csp_rule(site):
    _with_csp(site, "about.html", lambda c: c.replace("form-action &#39;self&#39;",
                                                     "form-action &#39;self&#39; https://buttondown.com"))
    problems = SC.check_external(SC.site_pages(_pages(site)), site, SC._site_cfg())
    assert problems == ["about.html: CSP form-action is [\"'self'\", 'https://buttondown.com'], want [\"'self'\"]"]


def test_the_frame_is_only_left_out_of_page_checks_by_its_exact_name(built_on):
    pages = _pages(built_on)
    assert set(pages) - set(SC.site_pages(pages)) == {"digest/geo-frame.html"}


def _sources(site, pages):
    cfg = SC._site_cfg()
    return SC.check_sources(site, pages, {"sources": []}, (), SC.allowed_external(cfg, FIXTURE_SEATS, FIXTURE_DISTRICTS),
                            None, set(), SC.digest_link_urls(site, pages, cfg))[0]


def test_sources_digest_links_are_the_directorys(built_on):
    pages = {rel: pg for rel, pg in _pages(built_on).items() if rel.startswith("digest/")}
    assert _sources(built_on, pages) == []
    urls = SC.digest_link_urls(built_on, pages, SC._site_cfg())
    assert {"https://www.cmcss.net/", "https://clarksvilletn.portal.civicclerk.com/",
            "https://montgomerytn.gov/code/webshare/commission-committees-agendas.php",
            "https://www.census.gov/about/policies/privacy.html"} <= urls["digest/covered.html"]
    # a coming-up page also takes the URLs of its own JSON
    data = json.loads((built_on / "digest/tn/county-47125.json").read_text(encoding="utf-8"))
    assert data["body"]["official_url"] in urls["digest/tn/county-47125.html"]


def test_sources_the_form_services_privacy_page_only_while_the_form_is_on(built_on):
    """how.html links config morning_note.privacy_url (the form service's policy); allowed only while the form is on."""
    cfg = SC._site_cfg()
    privacy = cfg["morning_note"]["privacy_url"]
    pages = {rel: pg for rel, pg in _pages(built_on).items() if rel.startswith("digest/")}
    assert SC.note_form_origin(cfg) and privacy in SC.digest_link_urls(built_on, pages, cfg)["digest/how.html"]
    assert any(href == privacy for href, _ in pages["digest/how.html"].links)
    off = {**cfg, "morning_note": {**cfg["morning_note"], "enabled": False}}
    assert privacy not in SC.digest_link_urls(built_on, pages, off)["digest/how.html"]


@pytest.mark.parametrize("link, want", [
    ('<a href="https://example.com/" rel="noopener noreferrer">x</a>',
     "digest/covered.html: digest link 'https://example.com/' is not a URL of the directory, a privacy page the "
     "config names or the page's own JSON"),
    ('<a href="https://www.cmcss.net/">x</a>',
     "digest/covered.html: outbound link 'https://www.cmcss.net/' has rel None, not \"noopener noreferrer\""),
    ('<a href="http://www.cmcss.net/" rel="noopener noreferrer">x</a>',
     "digest/covered.html: digest link 'http://www.cmcss.net/' is not https"),
])
def test_sources_a_stray_digest_link_fails(site, link, want):
    _edit(site, "digest/covered.html", lambda h: h.replace("</main>", link + "</main>"))
    pages = {rel: pg for rel, pg in _pages(site).items() if rel.startswith("digest/")}
    assert _sources(site, pages) == [want]


def test_sources_a_directory_link_outside_digest_is_still_unknown(site):
    _edit(site, "about.html", lambda h: h.replace("</main>", '<a href="https://www.cmcss.net/" '
                                                  'rel="noopener noreferrer">x</a></main>'))
    pages = {"about.html": SC.parse(site / "about.html")}
    assert "about.html: external link 'https://www.cmcss.net/' is not a known source document" in _sources(site, pages)


def test_run_checks_wires_digest_csp_and_the_exemptions(built_on, built_off, monkeypatch):
    facts = json.loads(FIXTURE.read_text(encoding="utf-8"))
    names = ("sources", "footer", "external", "digest/csp", "unofficial/notice-on-every-page", "switch/on-every-page",
             "header/same-on-every-page")
    site_cfg = SC._site_cfg
    for site, on in ((built_on, True), (built_off, False)):
        # run_checks reads config/site.yml; each build is checked with the national.enabled it was built with
        monkeypatch.setattr(SC, "_site_cfg", lambda on=on: {**site_cfg(), "national": {"enabled": on}})
        rep = SC.run_checks(site, facts, browser=False, no_export=True, target="pages")
        got = {name: (ok, problems) for name, ok, problems, _ in rep.results}
        assert {n: got[n] for n in names} == {n: (True, []) for n in names}, site
