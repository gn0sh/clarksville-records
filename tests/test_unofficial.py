"""Independent and unofficial (config/site.yml `unofficial:`): one wording, on every page, feed, note and export, and the
qa/site_checks.py check `unofficial/notice-on-every-page` that fails when any of them lacks it."""
import copy
import re
import shutil


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
    assert ("not run by, paid by or approved by " + ", ".join(b["name"] for b in config.SITE["unofficial"]["bodies"])
            + ", or any candidate, party or campaign.") in who
    # no claim that can be false while an officeholder is involved (review unofficial/untrue-claim)
    assert "or any official" not in who and "office or official" not in pages["about.html"]
    assert "No government body or office runs, pays for, reviews or approves this site." in pages["about.html"]
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
