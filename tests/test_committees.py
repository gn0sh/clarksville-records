"""The committees placeholder (Brian, 2026-11-11: committee records before done): a menu entry, a "coming" page and a
day-page line that say plainly the city Finance and Audit committees' and the county Budget Committee's records are
being added, with plain links to their official source pages (docs/research/committee-sources-2026-11-11.md). Every
word and URL comes from config/site.yml `committees:`; nothing is fetched, and the page holds no numbers, dates or
names. Modelled on tests/test_school_board.py."""
import re
from datetime import date

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT
from qa import site_checks
from sitegen import config, views
from sitegen.build import build

TODAY = date(2024, 12, 1)
OPENS = '<span class="sr-only"> (opens in a new tab)</span></a>'


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("committees") / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, today=TODAY)
    return out


def main_of(html: str) -> str:
    return html.split("<main", 1)[1].split("</main>")[0]


def test_config_names_the_three_committees_and_their_official_pages():
    cm = config.SITE["committees"]
    assert views.committees() is cm
    text = cm["page"]["lede"]
    assert all(w in text for w in ("Finance Committee", "Audit Committee", "Budget Committee", "being added"))
    urls = [x["url"] for x in cm["links"]]
    research = (ROOT / "docs" / "research" / "committee-sources-2026-11-11.md").read_text(encoding="utf-8")
    assert all(u.startswith("https://") and u.rstrip("/") in research for u in urls), urls


def test_coming_page_says_coming_and_has_the_links_from_config(site):
    cm = config.SITE["committees"]
    pg = cm["page"]
    main = main_of((site / f"{pg['slug']}.html").read_text(encoding="utf-8"))
    assert f'<h1>{pg["title"]} <span class="chip chip-coming">Coming</span></h1>' in main
    assert pg["lede"] in main and not pg["lede"].startswith("Coming")    # the h1's tag says it once
    assert all(f"<li>{p}</li>" in main for p in pg["planned"])
    assert pg["link_lede"] in main
    ext = re.findall(r'<a [^>]*href="(https?://[^"]+)"', main)
    assert ext == [x["url"] for x in cm["links"]]
    for x in cm["links"]:
        assert (f'<a data-ext="committee" href="{x["url"]}" target="_blank" rel="noopener noreferrer">{x["label"]}'
                f'{OPENS}') in main
        assert x["url"] in site_checks.allowed_external(config.SITE, None, None)
    assert "committee" in site_checks.EXT_KINDS


def test_coming_page_has_no_numbers_no_tables_and_no_script_of_its_own(site):
    pg = config.SITE["committees"]["page"]
    main = main_of((site / f"{pg['slug']}.html").read_text(encoding="utf-8"))
    text = re.sub(r"<[^>]+>", " ", main)
    assert not re.search(r"\d", text), text        # no dates promised, no counts, no sample values
    assert not re.search(r"<(table|svg|canvas|script|form)", main)


def test_the_urls_live_only_in_config_and_nothing_fetches_them(site):
    fetch = (ROOT / "collector" / "fetch.py").read_text(encoding="utf-8")
    for x in config.SITE["committees"]["links"]:
        for path in [*(ROOT / "sitegen").glob("*.py"), *(ROOT / "site" / "templates").glob("*.j2")]:
            assert x["url"] not in path.read_text(encoding="utf-8"), path
        assert x["url"] not in fetch


def test_day_page_line_says_coming_with_the_links(site):
    cm = config.SITE["committees"]
    html = (site / "today.html").read_text(encoding="utf-8")
    line = html[html.index(f"<strong>{cm['label']}.</strong>"):]
    line = line[:line.index("</li>")]
    assert '<span class="chip chip-coming">Coming</span> Their meetings are not collected yet' in line
    for x in cm["links"]:
        assert f'<a data-ext="committee" href="{x["url"]}"' in line and html.count(x["url"]) == 1


def test_menu_lists_the_committees_as_coming_on_every_page_and_marks_it_current(site):
    pg = config.SITE["committees"]["page"]
    entry = f'{pg["slug"]}.html">{pg["nav_label"]} <span class="chip chip-coming">Coming</span></a>'
    for rel in ("index.html", "today.html", "about.html", "districts/01.html"):
        html = (site / rel).read_text(encoding="utf-8")
        nav = html[html.index('<nav id="site-nav"'):]
        assert nav.count(entry) == 1, rel
    own = (site / f"{pg['slug']}.html").read_text(encoding="utf-8")
    nav = own[own.index('<nav id="site-nav"'):]
    assert f'<a href="{pg["slug"]}.html" aria-current="page">{pg["nav_label"]}' in nav
    assert nav.count('aria-current="page"') == 1


def test_without_the_block_or_with_a_bad_url_there_is_no_entry_page_or_line(tmp_path, monkeypatch):
    cm = config.SITE["committees"]
    bad_link = [{**cm["links"][0], "url": "http://example.org/"}, *cm["links"][1:]]
    for i, value in enumerate((None, {**cm, "links": bad_link}, {k: v for k, v in cm.items() if k != "page"},
                               {**cm, "links": []})):
        cfg = {k: v for k, v in config.SITE.items() if k != "committees"}
        if value is not None:
            cfg["committees"] = value
        monkeypatch.setattr(config, "SITE", cfg)
        out = tmp_path / str(i) / "site"
        build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, today=TODAY)
        assert not (out / "committees.html").exists()
        assert "committees.html" not in (out / "index.html").read_text(encoding="utf-8")
        assert cm["label"] not in (out / "today.html").read_text(encoding="utf-8")
