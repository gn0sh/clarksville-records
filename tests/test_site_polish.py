"""Launch Brain Trust copy and freshness fixes (docs/reviews/brain-trust-launch.md, problem keys site-polish/*)."""
import copy
import re

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS
from sitegen import config, freshness, views
from sitegen.build import BuildError, build
from test_rpc_pages import read, rpc_cfg, site as rpc_site  # noqa: F401  (module fixtures: the fixture RPC build)


def text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# ---- site-polish/freshness-line ------------------------------------------------------------------------------------

def test_county_line_is_computed_from_the_facts(pages, facts):
    latest = max(m["date"] for m in facts["meetings"])
    assert freshness.county(views.Index(facts)) == {
        "body": config.SITE["county_body"],
        "parts": [{"what": "minutes and votes", "iso": latest, "text": freshness.date_text(latest)}]}
    sec = re.search(r'<section class="freshness".*?</section>', pages["index.html"], re.S).group(0)
    assert f'<time class="nowrap" datetime="{latest}">{freshness.date_text(latest)}</time>' in sec
    assert freshness.NOTE in sec


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


def test_council_minutes_skip_agenda_only_meetings():
    cix = _Council([{"date": "2026-06-04", "source_id": "m1", "agenda_source_id": "a1"},
                    {"date": "2026-11-05", "source_id": "a2", "agenda_source_id": "a2"}],
                   [{"id": "m1", "kind": "minutes"}, {"id": "a1", "kind": "agenda"}, {"id": "a2", "kind": "agenda"}])
    line = freshness.council(cix)
    assert [(p["what"], p["iso"]) for p in line["parts"]] == [("minutes and votes", "2026-06-04"),
                                                                ("agendas", "2026-11-05")]


def test_finance_line():
    fin = {"books": [{"fiscal_year": 2025}, {"fiscal_year": 2027}],
           "solicitations": [{"archive_date": "2026-10-19"}, {"archive_date": None}, {"archive_date": "2026-09-02"}]}
    line = freshness.finance(fin)
    assert [p["text"] for p in line["parts"]] == ["fiscal year 2027", "October 19, 2026"]
    assert freshness.finance(None) is None


def test_rpc_home_has_its_own_line(rpc_site):  # noqa: F811
    home = read(rpc_site, "rpc/index.html")
    sec = text(re.search(r'<section class="freshness".*?</section>', home, re.S).group(0))
    assert "Regional Planning Commission: " in sec and "agendas through" in sec
    landing = text(re.search(r'<section class="freshness".*?</section>', read(rpc_site, "index.html"), re.S).group(0))
    assert "Montgomery County Commission: minutes and votes through" in landing
    assert "Regional Planning Commission: " in landing


# ---- site-polish/rpc-subtitle -------------------------------------------------------------------------------------

def test_rpc_pages_header_describes_the_rpc(rpc_site):  # noqa: F811
    for rel in ("rpc/index.html", "rpc/meetings/2026.html"):
        k = text(re.search(r'<p class="kicker">(.*?)</p>', read(rpc_site, rel), re.S).group(1)).strip()
        assert k.startswith("Clarksville-Montgomery County Regional Planning Commission meetings, "), (rel, k)
        assert "County Commission minutes" not in k


# ---- site-polish/home-heading -------------------------------------------------------------------------------------

def test_home_heading_names_every_body_built(pages, rpc_site):  # noqa: F811
    class C:
        body_name = "Clarksville City Council"
    assert views.purpose_line([C()], rpc=True, finance=True) == (
        "Votes and records of the Montgomery County Commission, Clarksville City Council, Regional Planning "
        "Commission and county finance, each linked to its source.")
    # the fixture build has no council, RPC or finance: the heading names only what it holds
    assert '<h1 class="purpose">Votes and records of the Montgomery County Commission, each linked to its source.</h1>' \
        in pages["index.html"]
    assert "Montgomery County Commission and Regional Planning Commission, each" in read(rpc_site, "index.html")


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


def test_shipped_config_is_not_live():
    assert config.SITE["live"] is False
