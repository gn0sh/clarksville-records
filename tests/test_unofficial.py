"""Independent and unofficial (config/site.yml `unofficial:`): one wording, on every page, feed, note and export, and the
qa/site_checks.py check `unofficial/notice-on-every-page` that fails when any of them lacks it."""
import copy
import re
import shutil

import pytest

from qa import site_checks
from sitegen import config, unofficial

NOTICE = unofficial.load()["notice"]
BODIES = ("City of Clarksville", "Montgomery County", "CMCSS", "Regional Planning Commission")


def run(site, pages_):
    return site_checks.check_unofficial(site, dict.fromkeys(pages_))[0]


def test_notice_wording_is_one_config_block_and_names_the_four_bodies():
    assert NOTICE.startswith("Daylight is an independent, unofficial site run by gnoshcodes LLC.")
    assert "not affiliated with, endorsed by, or operated by" in NOTICE
    assert all(b in NOTICE for b in BODIES)
    assert NOTICE.endswith("The official record held by each body controls.")
    assert unofficial.problems() == []
    assert site_checks.unofficial_notice(config.SITE) == NOTICE   # the check restates it from the same block


def test_config_problems_are_refused():
    bad = copy.deepcopy(config.SITE)
    del bad["unofficial"]["bodies"][3]
    bad["unofficial"]["bodies"][0]["url"] = "http://x.example/"
    assert len(unofficial.problems(bad)) == 2
    assert unofficial.problems({}) == ["unofficial: block is missing"]


def test_every_built_page_carries_the_notice_tag_meta_and_title(built, pages):
    assert pages
    for rel, html in pages.items():
        assert NOTICE in " ".join(re.sub(r"<[^>]+>", " ", html.split("<body", 1)[1]).replace("&#39;", "'").split()), rel
        assert html.count(f'content="{NOTICE}"') == 2, rel          # description and og:description
        assert re.search(r"<title>Daylight \(independent, unofficial\) \| [^<]+</title>", html), rel
        assert re.search(r'<meta property="og:title" content="Daylight \(independent, unofficial\) \| [^"]+">', html), rel
        assert '<p class="unofficial-tag">Independent, unofficial</p>' in html, rel
        assert 'class="unofficial-notice"' in html and "report.html" in html, rel
    assert run(built, pages) == []


def test_home_and_about_carry_the_fuller_text(pages):
    assert 'class="unofficial-intro"' in pages["index.html"]
    assert ("Not affiliated with or endorsed by the City of Clarksville, Montgomery County, CMCSS, or the Regional "
            "Planning Commission.") == unofficial.load()["short"] and unofficial.load()["short"] in pages["index.html"]
    about = pages["about.html"]
    for want in ("Who runs it.", "Where the records come from.", "If this site and the official document differ, "
                 "the official document is right.", "Nothing on this site is legal advice.", 'id="unofficial"'):
        assert want in about
    for b in config.SITE["unofficial"]["bodies"]:
        assert f'href="{b["url"]}"' in about


def test_no_page_calls_itself_official_or_uses_a_government_image(pages):
    for rel, html in pages.items():
        assert not re.search(r"<img[^>]+(seal|crest|insignia)", html, re.I), rel
        assert not re.search(r"\bour official\b|\bthe official (site|website) of\b", html, re.I), rel


def test_feeds_and_export_readme(built, tmp_path):
    assert sorted(built.rglob("*.xml"))
    readme = built / "data" / "README.txt"
    assert readme.is_file() and NOTICE in " ".join(readme.read_text(encoding="utf-8").split())
    assert site_checks.check_unofficial(built, {})[0] == []
    site = tmp_path / "site"
    shutil.copytree(built, site)
    (site / "data" / "README.txt").unlink()   # an export without its README fails
    assert any("README" in p for p in site_checks.check_unofficial(site, {})[0])


def test_check_fails_when_a_page_feed_or_note_lacks_the_notice(built, tmp_path, pages):
    site = tmp_path / "site"
    shutil.copytree(built, site)
    assert run(site, pages) == []
    p = site / "about.html"
    p.write_text(p.read_text(encoding="utf-8").replace("independent, unofficial site", "site"), encoding="utf-8")
    got = run(site, pages)
    assert any(x.startswith("about.html: the unofficial notice is not in the page text") for x in got)
    assert any(x.startswith("about.html: description and og:description") for x in got)
    # a page with no footer notice and no meta at all
    q = site / "officials.html"
    q.write_text(re.sub(r"<section class=\"unofficial-notice\".*?</section>", "", q.read_text(encoding="utf-8"), flags=re.S),
                 encoding="utf-8")
    assert any(x.startswith("officials.html: the unofficial notice") for x in run(site, pages))
    # a feed without it
    feed = sorted(site.rglob("*.xml"))[0]
    feed.write_text(feed.read_text(encoding="utf-8").replace(NOTICE, "x"), encoding="utf-8")
    assert any("feed subtitle" in x for x in site_checks.check_unofficial(site, {})[0])
    # a morning note without it
    (site / "morning").mkdir()
    (site / "morning" / "latest.json").write_text('{"date": "2026-11-10"}', encoding="utf-8")
    assert any("morning/latest.json" in x for x in site_checks.check_unofficial(site, {})[0])


NOTICE_SECTION = re.compile(r'<section class="unofficial-notice".*?</section>', re.S)


@pytest.mark.parametrize("how", ["comment", "hidden", "aria-hidden", "inline-style", "template", "out-of-footer",
                                 "sr-only", "opacity", "font-size"])
def test_check_fails_for_a_notice_nobody_can_see(built, tmp_path, pages, how):
    site = tmp_path / "site"
    shutil.copytree(built, site)
    p = site / "officials.html"
    raw = p.read_text(encoding="utf-8")
    sec = NOTICE_SECTION.search(raw).group(0)
    hidden = {"comment": f"<!-- {sec} -->",
              "hidden": sec.replace("<section ", "<section hidden ", 1),
              "aria-hidden": sec.replace("<section ", '<section aria-hidden="true" ', 1),
              "inline-style": sec.replace("<section ", '<section style="display: none" ', 1),
              "template": f"<template>{sec}</template>",
              "sr-only": f'<div class="sr-only">{sec}</div>',
              "opacity": sec.replace("<section ", '<section style="opacity: 0" ', 1),
              "font-size": sec.replace("<p>", '<p style="font-size:0px">', 1)}.get(how)
    if how == "out-of-footer":   # in the page, but not in the footer of every page
        raw = raw.replace(sec, "").replace("</main>", sec + "</main>", 1)
    else:
        raw = raw.replace(sec, hidden)
    p.write_text(raw, encoding="utf-8")
    assert [x for x in run(site, pages) if x.startswith("officials.html:")] == [
        "officials.html: the unofficial notice is not in the page text (visible, in the footer)"]


@pytest.mark.parametrize("how", ["hidden", "text", "gone"])
def test_check_reads_the_tag_text_not_only_its_class(built, tmp_path, pages, how):
    site = tmp_path / "site"
    shutil.copytree(built, site)
    p = site / "officials.html"
    tag = '<p class="unofficial-tag">Independent, unofficial</p>'
    new = {"hidden": '<p class="unofficial-tag" hidden>Independent, unofficial</p>',
           "text": '<p class="unofficial-tag">Official</p>', "gone": ""}[how]
    p.write_text(p.read_text(encoding="utf-8").replace(tag, new), encoding="utf-8")
    assert [x for x in run(site, pages) if x.startswith("officials.html:")] == [
        "officials.html: no visible 'Independent, unofficial' tag by the site name"]


def test_check_fails_when_css_hides_the_notice(built, tmp_path):
    site = tmp_path / "site"
    shutil.copytree(built, site)
    css = site / "static" / "style.css"
    rule = "\n@media (max-width: 600px) { .unofficial-intro-full { display:none } }\n"
    css.write_text(css.read_text(encoding="utf-8") + rule, encoding="utf-8")
    assert site_checks.check_unofficial(site, {})[0] == [
        "static/style.css: '.unofficial-intro-full' hides the unofficial notice"]


@pytest.mark.parametrize("rule, flagged", [
    ("footer { display: none }", "footer"),
    (".page-landing .site-footer { visibility: hidden; }", ".page-landing .site-footer"),
    ("footer section { opacity: 0 }", "footer section"),
    (".site-footer > section { font-size: 0 }", ".site-footer > section"),
    ("main p, .unofficial-notice p { font-size: 0px !important }", ".unofficial-notice p"),
])
def test_check_fails_when_css_hides_the_footer(built, tmp_path, rule, flagged):
    site = tmp_path / "site"
    shutil.copytree(built, site)
    css = site / "static" / "style.css"
    css.write_text(css.read_text(encoding="utf-8") + "\n" + rule + "\n", encoding="utf-8")
    assert site_checks.check_unofficial(site, {})[0] == [f"static/style.css: {flagged!r} hides the unofficial notice"]


@pytest.mark.parametrize("rule", [".site-footer .nav-list { display: none }", ".site-footer { opacity: 0.9 }",
                                  "main section { display: none }", ".site-footer p { font-size: 0.9rem }"])
def test_css_that_leaves_the_notice_alone_passes(built, tmp_path, rule):
    site = tmp_path / "site"
    shutil.copytree(built, site)
    css = site / "static" / "style.css"
    css.write_text(css.read_text(encoding="utf-8") + "\n" + rule + "\n", encoding="utf-8")
    assert site_checks.check_unofficial(site, {})[0] == []


def test_only_real_feeds_are_checked_as_feeds(built, tmp_path):
    site = tmp_path / "site"
    shutil.copytree(built, site)
    n = len(sorted((site / "feeds").glob("*.xml")))
    (site / "static" / "map.xml").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    probs, note = site_checks.check_unofficial(site, {})
    assert probs == [] and f"{n} feeds" in note
    (site / "feeds" / "broken.xml").write_text("<rss/>", encoding="utf-8")
    assert site_checks.check_unofficial(site, {})[0] == ["feeds/broken.xml: not an Atom feed"]


def test_check_needs_the_config_block(built):
    cfg = copy.deepcopy(config.SITE)
    del cfg["unofficial"]
    assert site_checks.check_unofficial(built, {}, cfg)[0] == ["config/site.yml has no unofficial: block"]


def test_export_readme_names_the_correction_route_and_every_official_site():
    cfg = copy.deepcopy(config.SITE)
    cfg.setdefault("alerts", {})["site_url"] = "https://daylight.example/"
    text = unofficial.export_readme(cfg)
    assert text.startswith("Independent, unofficial.\n\n" + NOTICE)
    assert "How to report a correction: https://daylight.example/report.html" in text
    assert all(b["url"] in text for b in cfg["unofficial"]["bodies"])
    cfg["alerts"]["site_url"] = ""
    assert "How to report a correction: the Report an error page (report.html)" in unofficial.export_readme(cfg)


def test_who_runs_this_data_and_morning_preview_name_it(pages):
    who = " ".join(re.sub(r"<[^>]+>", " ", pages["who-runs-this.html"]).split())
    assert ("It is not run by, paid by or approved by the City of Clarksville, Montgomery County, CMCSS or the Regional "
            "Planning Commission. It is not run or approved by any candidate, party or campaign, and does not work for "
            "one.") in who
    assert "No one pays for what this site covers; tips do not buy anything." in who
    # no claim that can turn false (review unofficial/untrue-claim): officials, offices, tippers nobody checks
    for false_soon in ("or any official", "paid by or approved by any candidate",
                       "No person, company, office or group pays"):
        assert false_soon not in who, false_soon
    about = " ".join(re.sub(r"<[^>]+>", " ", pages["about.html"]).split())
    assert "office or official" not in about and "body or office" not in about
    assert "No government body or agency runs, pays for, reviews or approves this site." in about
    assert 'href="about.html#unofficial"' in pages["who-runs-this.html"]
    assert NOTICE in pages["data.html"] and 'href="data/README.txt"' in pages["data.html"]
    assert "beside these files" in pages["data.html"] and "Every download carries" not in pages["data.html"]


def test_morning_preview_and_sign_up_carry_the_email_line(tmp_path, monkeypatch):
    from test_morning_page import _build   # a fixture build with the morning note's preview page
    pages = _build(tmp_path / "site", monkeypatch)
    line = config.SITE["unofficial"]["email_line"]
    assert "morning/index.html" in pages
    for rel in ("morning/index.html", "alerts.html"):
        assert f'<p class="small mn-unofficial">{line}</p>' in pages[rel], rel
    assert site_checks.check_unofficial(tmp_path / "site", pages)[0] == []
