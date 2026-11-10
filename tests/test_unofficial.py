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
    assert NOTICE.startswith("Daylight is an independent, unofficial site run by gnoshcodes.")
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
        assert re.search(r"<title>[^<]*\| Independent, unofficial</title>", html), rel
        assert '<p class="unofficial-tag">Independent, unofficial</p>' in html, rel
        assert 'class="unofficial-notice"' in html and "report.html" in html, rel
    assert run(built, pages) == []


def test_home_and_about_carry_the_fuller_text(pages):
    assert 'class="unofficial-intro"' in pages["index.html"]
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


@pytest.mark.parametrize("key", ["tag", "notice"])
def test_check_needs_the_config_block(built, key):
    cfg = copy.deepcopy(config.SITE)
    del cfg["unofficial"]
    assert site_checks.check_unofficial(built, {}, cfg)[0] == ["config/site.yml has no unofficial: block"]
