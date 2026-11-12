# ruff: noqa: E501
"""The school board placeholder (scope gap 2026-11-10, task E): a menu entry and a "coming" page that say plainly the
board's records are coming and carry one plain link to the school system's own site. Every word and the URL come
from config/site.yml `school_board:`; nothing is fetched, and the page holds no numbers, dates or names."""
import re
from datetime import date

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT
from qa import site_checks
from sitegen import config
from sitegen.build import build

TODAY = date(2024, 12, 1)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("school") / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, today=TODAY)
    return out


def main_of(html: str) -> str:
    return html.split("<main", 1)[1].split("</main>")[0]


def test_coming_page_says_coming_and_has_the_one_link_from_config(site):
    sb = config.SITE["school_board"]
    pg = sb["page"]
    html = (site / f"{pg['slug']}.html").read_text(encoding="utf-8")
    main = main_of(html)
    assert f'<h1>{pg["title"]} <span class="chip chip-coming">Coming</span></h1>' in main
    assert pg["lede"] in main and pg["lede"].startswith("Coming.")
    assert all(f"<li>{p}</li>" in main for p in pg["planned"])
    # one external link, the configured URL, marked and opened the way the day page's link is
    ext = re.findall(r'<a [^>]*href="(https?://[^"]+)"', main)
    assert ext == [sb["url"]]
    assert (f'<a data-ext="school" href="{sb["url"]}" target="_blank" rel="noopener noreferrer">{sb["link_label"]}'
            '<span class="sr-only"> (opens in a new tab)</span></a>') in main
    assert sb["url"] in site_checks.allowed_external(config.SITE, None, None)


def test_coming_page_has_no_numbers_no_tables_and_no_script_of_its_own(site):
    pg = config.SITE["school_board"]["page"]
    main = main_of((site / f"{pg['slug']}.html").read_text(encoding="utf-8"))
    text = re.sub(r"<[^>]+>", " ", main)
    assert not re.search(r"\d", text), text        # no dates promised, no counts, no sample values
    assert not re.search(r"<(table|svg|canvas|script|form)", main)


def test_the_url_lives_only_in_config(site):
    url = config.SITE["school_board"]["url"]
    host = re.sub(r"^https://", "", url).strip("/")
    for path in [*(ROOT / "sitegen").glob("*.py"), *(ROOT / "site" / "templates").glob("*.j2")]:
        assert host not in path.read_text(encoding="utf-8"), path
    assert host not in (ROOT / "collector" / "fetch.py").read_text(encoding="utf-8")   # nothing fetches it


def test_menu_lists_the_school_board_as_coming_on_every_page_and_marks_it_current(site):
    pg = config.SITE["school_board"]["page"]
    entry = f'{pg["slug"]}.html">{pg["nav_label"]} <span class="chip chip-coming">Coming</span></a>'
    for rel in ("index.html", "today.html", "about.html", "districts/01.html"):
        html = (site / rel).read_text(encoding="utf-8")
        nav = html[html.index('<nav id="site-nav"'):]
        assert nav.count(entry) == 1, rel
    own = (site / f"{pg['slug']}.html").read_text(encoding="utf-8")
    nav = own[own.index('<nav id="site-nav"'):]
    assert f'<a href="{pg["slug"]}.html" aria-current="page">{pg["nav_label"]}' in nav
    assert nav.count('aria-current="page"') == 1


def test_without_the_block_or_with_a_bad_url_there_is_no_entry_and_no_page(tmp_path, monkeypatch):
    sb = config.SITE["school_board"]
    for i, value in enumerate((None, {**sb, "url": "http://example.org/"}, {k: v for k, v in sb.items() if k != "page"})):
        cfg = {k: v for k, v in config.SITE.items() if k != "school_board"}
        if value is not None:
            cfg["school_board"] = value
        monkeypatch.setattr(config, "SITE", cfg)
        out = tmp_path / str(i) / "site"
        build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, today=TODAY)
        assert not (out / "school-board.html").exists()
        assert "school-board.html" not in (out / "index.html").read_text(encoding="utf-8")
