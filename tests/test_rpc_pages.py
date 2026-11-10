"""Regional Planning Commission pages (RPC-1, sitegen/rpc.py): the RPC home, one page per year of meetings, the nav
entry and the search records. The RPC facts here are FIXTURE facts built by the collector's own reader from real
agenda text (collector/tests/fixtures/rpc), so they build beside the county fixture."""
import json
import re
from pathlib import Path

import pytest

from collector import rpc as rpc_collector, rpc_agenda
from collector.store import Store
from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS
from qa import site_checks
from sitegen import config, rpc, views
from sitegen.build import BuildError, build

FIX = Path(__file__).resolve().parent.parent / "collector" / "tests" / "fixtures" / "rpc"
AGENDA = "https://www.cmcrpc.com/wp2025/wp-content/uploads/2026/10/Agenda-10.27.2026.pdf"


def rpc_facts(tmp: Path) -> dict:
    cfg = rpc_collector.load_config()
    rows, _ = rpc_collector.parse_listing((FIX / "listing.html").read_text(encoding="utf-8"), cfg)
    store = Store(manifest_path=tmp / "manifest.json", root=tmp / "store")
    store.put(AGENDA, b"%PDF agenda", {}, {"kind": "agenda", "meeting_date": "2026-10-27"})
    pages = (FIX / "agenda_2026-10-27.txt").read_text(encoding="utf-8").split("\f")[:-1]
    facts, _ = rpc_agenda.build(cfg, rpc_collector.assign_ids(rows), store, extract=lambda p: pages)
    return {**facts, "fixture": True}


@pytest.fixture(scope="module")
def rpc_cfg(tmp_path_factory):
    d = tmp_path_factory.mktemp("rpc")
    (d / "rpc.json").write_text(json.dumps(rpc_facts(d)), encoding="utf-8")
    return {**rpc.load_config("cmc-rpc"), "facts_path": d / "rpc.json"}


@pytest.fixture(scope="module")
def site(tmp_path_factory, rpc_cfg):
    out = tmp_path_factory.mktemp("site") / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, rpc=rpc_cfg)
    return out


def read(site: Path, rel: str) -> str:
    return (site / rel).read_text(encoding="utf-8")


def test_pages_and_file_budget(site):
    rels = sorted(p.relative_to(site).as_posix() for p in (site / "rpc").rglob("*.html"))
    # one home and one page per year of meetings, never one page per meeting (the preview file cap)
    assert rels == ["rpc/index.html", "rpc/meetings/2022.html", "rpc/meetings/2023.html", "rpc/meetings/2024.html",
                    "rpc/meetings/2025.html", "rpc/meetings/2026.html"]


def test_nav_lists_the_rpc_on_every_page(site):
    for rel in ("index.html", "search.html", "rpc/index.html"):
        assert 'href="' + "../" * rel.count("/") + 'rpc/index.html">Planning Commission</a>' in read(site, rel) or \
            'rpc/index.html" aria-current="page">Planning Commission</a>' in read(site, rel)


def test_meeting_section_shows_cases_as_printed_with_page_links(site):
    html = read(site, "rpc/meetings/2026.html")
    sec = html[html.index('id="2026-10-27-regular"'):]
    sec = sec[:sec.index("</section>")]
    assert f'Unofficial copy. Official record: <a href="{AGENDA}"' in sec
    assert 'id="case-2026-10-27-regular-z-19-2026"' in sec
    assert f'<a href="{AGENDA}#page=1"' in sec and f'<a href="{AGENDA}#page=3"' in sec
    assert "<dd data-item-title>Estate of Jason Feltner, Bob Yates Executor</dd>" in sec
    assert "<dt>City council ward</dt><dd data-item-title>11</dd>" in sec
    assert sec.count('class="item"') == 27
    assert "CITY COUNCIL INFORMAL October 29, 2026 @ 4:30 P.M." in sec
    assert "Minutes: <span class=\"doc-note\">not linked on the RPC page</span>" in sec


def test_page_level_record_line_and_listed_links(site):
    for rel in ("rpc/index.html", "rpc/meetings/2024.html"):
        assert ('Unofficial copy. Official record: <a data-ext="record" '
                'href="https://www.cmcrpc.com/documents/agenda-minutes/"') in read(site, rel)
    html = read(site, "rpc/meetings/2024.html")
    assert '<a data-ext="listed" href="https://drive.google.com/file/d/EXAMPLE1/view?usp=drive_link"' in html
    assert "not collected or read" in html
    assert "youtube" not in html.lower()


def test_no_inline_script_and_no_ai_wording(site):
    for p in (site / "rpc").rglob("*.html"):
        html = p.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", html), p   # every script is an external file
        assert not re.search(r"\bstyle=", html), p
        # the pages carry no judgement words about cases or the people named in them
        assert not re.search(r"\b(controversial|notable|important|likely|probably)\b",
                             re.sub(r"<dd data-item-title>.*?</dd>", "", html, flags=re.S), re.I), p


def test_search_index_has_rpc_meetings_and_cases(site, rpc_cfg):
    js = read(site, "static/search-index.js")
    idx = json.loads(js[js.index("=") + 1:].rstrip().rstrip(";"))
    assert {"key": "rpc", "label": rpc_cfg["body"]} in idx["bodies"]
    recs = [r for r in idx["records"] if r["b"] == "rpc"]
    meetings = [r for r in recs if r["k"] == "meeting"]
    cases = {r["n"]: r for r in recs if r["k"] == "item"}
    assert len(meetings) == 11 and len(cases) == 27
    z = cases["Z-19-2026"]
    assert z["h"] == "rpc/meetings/2026.html#case-2026-10-27-regular-z-19-2026" and z["ty"] == ["rezoning"]
    assert "Estate of Jason Feltner" in z["z"]
    assert all(len(r["t"]) <= rpc.TITLE_MAX + 1 for r in cases.values())


def test_site_checks_pass_on_rpc_pages(site, rpc_cfg):
    facts = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rfacts = json.loads(Path(rpc_cfg["facts_path"]).read_text(encoding="utf-8"))
    pages = {p.relative_to(site).as_posix(): site_checks.parse(p) for p in site.rglob("*.html")}
    allowed = site_checks.allowed_external(config.SITE, FIXTURE_SEATS, FIXTURE_DISTRICTS) | \
        site_checks.rpc_allowed({**rfacts, "_cfg": rpc_cfg})
    problems, _ = site_checks.check_sources(site, pages, {"sources": facts["sources"] + rfacts["sources"]}, (), allowed)
    assert problems == []
    assert site_checks.check_links(site, pages, no_export=True) == []
    assert site_checks.check_external(pages, site, site_checks._site_cfg()) == []
    assert site_checks.page_type("rpc/index.html") == "rpc_home"
    assert site_checks.page_type("rpc/meetings/2026.html") == "rpc_meetings"


def test_real_and_fixture_rpc_facts_never_mix(tmp_path, rpc_cfg):
    real = {**json.loads(Path(rpc_cfg["facts_path"]).read_text(encoding="utf-8")), "fixture": False}
    p = tmp_path / "rpc.json"
    p.write_text(json.dumps(real), encoding="utf-8")
    with pytest.raises(BuildError, match="real RPC facts file"):
        build(FIXTURE, tmp_path / "site", seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS,
              rpc={**rpc_cfg, "facts_path": p})


def test_a_fixture_build_reads_no_real_rpc(tmp_path):
    out = tmp_path / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS)
    assert not (out / "rpc").exists()
    home = re.sub(r"<meta[^>]*>|<(section|p)[^>]*unofficial[^>]*>.*?</\1>", "", (out / "index.html").read_text(encoding="utf-8"), flags=re.S)   # the unofficial notice names the RPC on every page
    assert "Planning Commission" not in home
    assert views.RECORD_RPC == {"rpc_home.html.j2", "rpc_meetings_year.html.j2"}


def test_rpc_cases_check_fails_on_a_case_number_not_read(rpc_cfg):
    # the completeness check (rpc/case-dropped-silently): every "CASE NUMBER:" an agenda prints is read as a case
    rfacts = json.loads(Path(rpc_cfg["facts_path"]).read_text(encoding="utf-8"))
    assert site_checks.check_rpc_cases(rfacts)[0] == []
    m = {**rfacts["meetings"][0], "case_numbers_printed": 3, "case_numbers_read": 2}
    problems, _ = site_checks.check_rpc_cases({**rfacts, "meetings": [m]})
    assert problems == [f"{m['id']}: the agenda prints 3 case numbers (CASE NUMBER: or a numbered case line), "
                        "2 of those cases read"]
    assert site_checks.check_rpc_cases(None) == ([], "no RPC facts")


def test_sitegen_reports_the_file_headroom(tmp_path, capsys):
    # rpc/file-cap-headroom: one line, the target's cap minus the files the site has with the export
    from sitegen.__main__ import headroom_line, main
    assert headroom_line({"target": "preview", "files_with_export": 488}) == \
        "sitegen: file headroom 12 (preview cap 500 minus 488 files with the export)"
    assert main(["--facts", str(FIXTURE), "--out", str(tmp_path / "site"), "--seats", str(FIXTURE_SEATS),
                 "--districts", str(FIXTURE_DISTRICTS)]) == 0
    out = capsys.readouterr().out
    assert re.search(r"^sitegen: file headroom -?\d+ \(preview cap 500 minus \d+ files with the export\)$", out, re.M)
