"""Launch Brain Trust copy and freshness fixes (docs/reviews/brain-trust-launch.md, problem keys site-polish/*)."""
import copy
import re

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS
from sitegen import config, freshness, views
from sitegen.build import BuildError, build
from test_rpc_pages import read, rpc_cfg, site as rpc_site  # noqa: F401  (module fixtures: the fixture RPC build)


FRESH = re.compile(r'<(section|details) class="freshness".*?</\1>', re.S)


def text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# ---- site-polish/freshness-line ------------------------------------------------------------------------------------

def test_county_line_is_computed_from_the_facts(pages, facts):
    latest = max(m["date"] for m in facts["meetings"])
    mid = max((m["date"], m["id"]) for m in facts["meetings"])[1]
    assert freshness.county(views.Index(facts)) == {
        "body": config.SITE["county_body"], "lagged": False,
        "parts": [{"what": "minutes and votes", "iso": latest, "text": freshness.date_text(latest),
                   "href": f"meetings/{mid}.html"}]}
    sec = FRESH.search(pages["index.html"]).group(0)
    # site-polish/freshness-no-source-link: the date links to the meeting page that set it (which links its source)
    assert (f'<a href="meetings/{mid}.html"><time class="nowrap" datetime="{latest}">{freshness.date_text(latest)}'
            '</time></a>') in sec
    # site-polish/freshness-a11y: the fixture build has no agendas line, so no note about minutes behind agendas;
    # the collapsed block's summary is plain text, like the landing's other details (front-page-v2)
    assert freshness.NOTE not in sec
    assert '<summary id="fresh-h">How recent the records are</summary>' in sec


def test_a_newer_meeting_moves_the_line(facts):
    f = copy.deepcopy(facts)
    m = copy.deepcopy(f["meetings"][0])
    m.update(id="2099-01-05-x", date="2099-01-05")
    f["meetings"].append(m)
    assert freshness.county(views.Index(f))["parts"][0]["text"] == "January 5, 2099"


class _Council:
    body_name = "Test Council"

    def __init__(self, meetings, sources):
        self.facts = {"meetings": meetings}
        self.sources = {s["id"]: s for s in sources}

    def meeting_href(self, mid):
        return f"council/meetings/x.html#{mid}"


def test_council_minutes_skip_agenda_only_meetings():
    cix = _Council([{"id": "m-0604", "date": "2026-06-04", "source_id": "m1", "agenda_source_id": "a1"},
                    {"id": "m-1105", "date": "2026-11-05", "source_id": "a2", "agenda_source_id": "a2"}],
                   [{"id": "m1", "kind": "minutes"}, {"id": "a1", "kind": "agenda"}, {"id": "a2", "kind": "agenda"}])
    line = freshness.council(cix)
    assert [(p["what"], p["iso"], p["href"]) for p in line["parts"]] == [
        ("minutes and votes", "2026-06-04", "council/meetings/x.html#m-0604"),
        ("agendas", "2026-11-05", "council/meetings/x.html#m-1105")]
    assert line["lagged"] is True


def test_finance_line():
    fin = {"books": [{"fiscal_year": 2025, "edition": "approved", "source_id": "s1"},
                     {"fiscal_year": 2027, "edition": "approved", "source_id": "s2"}],
           "sources": [{"id": "s1", "url": "https://example.gov/fy25.pdf"},
                       {"id": "s2", "url": "https://example.gov/fy27.pdf"}],
           "solicitations": [{"archive_date": "2026-10-19", "slug": "b-19"}, {"archive_date": None, "slug": "b-x"},
                             {"archive_date": "2026-09-02", "slug": "b-02"}]}
    line = freshness.finance(fin, "finance/index.html")
    assert [(p["text"], p["href"]) for p in line["parts"]] == [("fiscal year 2027", "finance/index.html#books-h"),
                                                               ("October 19, 2026", "contracts/b-19.html")]
    assert line["lagged"] is False      # no minutes-behind note for finance (site-polish/freshness-a11y)
    assert freshness.finance(fin)["parts"][0]["href"] == "https://example.gov/fy27.pdf"   # no budget page: the book
    assert freshness.finance(None) is None


def test_finance_line_names_only_approved_books():
    """site-polish/freshness-finance-edition: a newer book of another edition is never called approved."""
    fin = {"books": [{"fiscal_year": 2026, "edition": "approved"}, {"fiscal_year": 2027, "edition": "proposed"}],
           "solicitations": []}
    assert [p["text"] for p in freshness.finance(fin)["parts"]] == ["fiscal year 2026"]
    fin["books"] = [{"fiscal_year": 2027, "edition": "proposed"}]
    assert freshness.finance(fin) is None


def test_qa_checks_each_freshness_date_against_the_page_it_links(rpc_site, tmp_path):  # noqa: F811
    """site-polish/freshness-no-source-link: qa dates/freshness-linked passes the build and catches a wrong date, a
    dead link and an unlinked date."""
    import shutil

    from qa.site_checks import check_freshness_dates
    rels = {"index.html": None, "rpc/index.html": None}
    problems, note = check_freshness_dates(rpc_site, rels)
    assert problems == [] and note.startswith("3 freshness dates"), (problems, note)
    bad = tmp_path / "bad"
    shutil.copytree(rpc_site, bad)
    home = (bad / "rpc/index.html").read_text(encoding="utf-8")
    m = re.search(r'datetime="(\d{4}-\d{2}-\d{2})">([^<]+)<', FRESH.search(home).group(0))
    (bad / "rpc/index.html").write_text(home.replace(f'datetime="{m[1]}">{m[2]}<', 'datetime="2099-01-05">January 5, '
                                                     '2099<'), encoding="utf-8")
    landing = (bad / "index.html").read_text(encoding="utf-8")
    sec = FRESH.search(landing).group(0)
    first = re.search(r'<a href="([^"]+)">', sec)
    (bad / "index.html").write_text(landing.replace(sec, sec.replace(first.group(0), '<a href="meetings/nope.html">', 1)),
                                    encoding="utf-8")
    problems, _ = check_freshness_dates(bad, rels)
    assert any("rpc/index.html: freshness date 'January 5, 2099' not printed" in p for p in problems), problems
    assert any("index.html: freshness link 'meetings/nope.html' has no page" in p for p in problems), problems
    sec = FRESH.search((bad / "index.html").read_text(encoding="utf-8")).group(0)
    unlinked = re.sub(r'<a href="[^"]+">(<time[^>]*>[^<]*</time>)</a>', r"\1", sec, count=1)
    (bad / "index.html").write_text(landing.replace(FRESH.search(landing).group(0), unlinked), encoding="utf-8")
    assert any("with no link" in p for p in check_freshness_dates(bad, rels)[0])


def test_rpc_home_has_its_own_line(rpc_site):  # noqa: F811
    home = read(rpc_site, "rpc/index.html")
    sec = text(FRESH.search(home).group(0))
    assert "Regional Planning Commission: " in sec and "agendas through" in sec
    landing = text(FRESH.search(read(rpc_site, "index.html")).group(0))
    assert "Montgomery County Commission: minutes and votes through" in landing
    assert "Regional Planning Commission: " in landing


# ---- site-polish/rpc-subtitle -------------------------------------------------------------------------------------

def test_rpc_pages_header_describes_the_rpc(rpc_site):  # noqa: F811
    # No page's masthead carries a coverage line (onceover/header/county-kicker-everywhere: it used to print one
    # body's dates over every page). An RPC page names the RPC in its own lede, never the County Commission.
    for rel in ("rpc/meetings/2026.html",):
        page = read(rpc_site, rel)
        assert 'class="kicker"' not in page[page.index("<header"):page.index("</header>")], rel
        lede = text(re.search(r'<p class="lede">(.*?)</p>', page, re.S).group(1)).strip()
        assert lede.startswith("Clarksville-Montgomery County Regional Planning Commission. "), (rel, lede)
        assert "County Commission minutes" not in text(page[:page.index("</header>")])
    # the RPC's home is a "Show records from" target: its masthead is the one every body shares (no coverage line),
    # and its own header states its coverage (tests/test_body_switch.py: the one header)
    home = read(rpc_site, "rpc/index.html")
    assert '<p class="kicker">' not in home and "County Commission minutes" not in text(home[:home.index("</header>")])
    assert re.search(r'<p class="body-cover">Meetings, <span class="nowrap">[A-Z][a-z]+ \d{1,2}, \d{4}</span> to ', home)


# ---- site-polish/home-heading -------------------------------------------------------------------------------------

def test_home_heading_names_every_body_built(pages, rpc_site):  # noqa: F811
    class C:
        body_name = "Clarksville City Council"
    # site-polish/home-heading-overclaims: votes only for bodies whose votes are shown; the RPC's are held
    assert views.purpose_line([C()], rpc=True, finance=True) == (
        "Votes and records of the Montgomery County Commission and Clarksville City Council, plus records of the "
        "Regional Planning Commission and county finance, each linked to its source.")
    assert views.purpose_line([C()], rpc=True, finance=True, rpc_votes=True) == (
        "Votes and records of the Montgomery County Commission, Clarksville City Council and Regional Planning "
        "Commission, plus records of county finance, each linked to its source.")
    # front-page-v2: the landing's h1 is the welcome (config/site.yml welcome_h1), so purpose_line no longer prints
    # there; the lede names money only when finance is built, so it never names a page the build lacks
    assert f'<h1 id="welcome-h" class="welcome-h">{config.SITE["welcome_h1"]}</h1>' in pages["index.html"]
    assert "spends money" not in pages["index.html"] and "Votes and records of" not in pages["index.html"]


# ---- site-polish/about-preview ------------------------------------------------------------------------------------

@pytest.mark.parametrize("live", [False, True])
def test_about_says_preview_until_live(tmp_path, monkeypatch, live):
    monkeypatch.setitem(config.SITE, "live", live)
    out = tmp_path / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS)
    about = (out / "about.html").read_text(encoding="utf-8")
    assert "private preview" not in about and "no public address" not in about
    assert ("has not launched yet" in about) is (not live)


def test_live_must_be_a_boolean(tmp_path, monkeypatch):
    monkeypatch.setitem(config.SITE, "live", "yes")
    with pytest.raises(BuildError, match="live must be true or false"):
        build(FIXTURE, tmp_path / "site", seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS)


def test_shipped_config_live_is_a_boolean():
    # site-polish/live-flag-test-blocks-golive: true or false, so the launch runbook's flip to true still passes
    assert isinstance(config.SITE["live"], bool)
