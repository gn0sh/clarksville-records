"""Regional Planning Commission milestone 2 pages (sitegen/rpc.py): the minutes' motions on each meeting section, the
county "Not confirmed" note on a motion that failed the reader's checks, and the Planning Commission -> County
Commission link on both sides. FIXTURE facts: the RPC agenda reader's own output on a real agenda (as in
test_rpc_pages.py), plus two made-up motions and one made-up county item with a CZ number."""
import json
import re
from pathlib import Path

import pytest

from collector.rpc_minutes import link_key
from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS
from sitegen import config, rpc
from sitegen.build import BuildError, build
from test_rpc_pages import rpc_facts

MINUTES = "https://www.cmcrpc.com/wp2025/wp-content/uploads/2026/11/10.27.2026-RPC-Minutes.pdf"
CASE = "2026-10-27-regular-cz-12-2026"


def motion(k: int, **kw) -> dict:
    base = {"id": f"2026-10-27-regular-motion-{k}", "meeting_id": "2026-10-27-regular", "source_id": "src-fixturemin",
            "page": 2, "case": None, "case_id": None, "kind": "Motion for approval", "moved_by": "Fixture Mover",
            "seconded_by": "Fixture Seconder", "nays": [], "abstained": [], "outcome": "Motion passes for approval",
            "tally": None, "confirmed": True, "reasons": []}
    return {**base, **kw}


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    d = tmp_path_factory.mktemp("rpc2")
    facts = rpc_facts(d)
    facts["sources"].append({"id": "src-fixturemin", "url": MINUTES, "sha256": "0" * 64, "kind": "minutes",
                             "meeting_date": "2026-10-27", "fetched_at": "2026-11-10", "pages": 3,
                             "text_layer": "none", "format": "pdf", "read_by": "OCR"})
    m = next(m for m in facts["meetings"] if m["id"] == "2026-10-27-regular")
    m.update({"minutes_source_id": "src-fixturemin", "minutes_read_by": "OCR", "minutes_date": "2026-10-27"})
    facts["motions"] = [
        motion(1, case="CZ-12-2026", case_id=CASE, nays=["Fixture Nay"], abstained=["Fixture Abstainer"],
               outcome="Motion passes for approval 5-1", tally="5-1"),
        motion(2, kind="Motion to approve the minutes", moved_by="Hidden Mover", seconded_by="Hidden Seconder",
               outcome="minutes were approved", confirmed=False, reasons=["mover is not one member present"]),
    ]
    (d / "rpc.json").write_text(json.dumps(facts), encoding="utf-8")
    county = json.loads(FIXTURE.read_text(encoding="utf-8"))
    county["items"].append({"id": "CZ-12-2026", "link_basis": "number", "number": "CZ-12-2026",
                            "title": "FIXTURE: CZ-12-2026", "year": 2026})
    (d / "facts.json").write_text(json.dumps(county), encoding="utf-8")
    out = d / "build" / "site"
    build(d / "facts.json", out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS,
          rpc={**rpc.load_config("cmc-rpc"), "facts_path": d / "rpc.json"})
    return out


def section(site: Path) -> str:
    html = (site / "rpc/meetings/2026.html").read_text(encoding="utf-8")
    sec = html[html.index('id="2026-10-27-regular"'):]
    return sec[:sec.index("</section>")]


def test_a_confirmed_motion_shows_its_values_as_printed_on_its_case(site):
    sec = section(site)
    case = sec[sec.index(f'id="case-{CASE}"'):]
    case = case[:case.index('<div class="item"')] if '<div class="item"' in case else case
    assert "In the minutes (read by OCR)" in case
    assert "<strong>Motion for approval.</strong>" in case
    assert "Moved by <span data-item-title>Fixture Mover</span>, seconded by <span data-item-title>Fixture Seconder" \
        in case
    assert "Voted nay, as printed: <span data-item-title>Fixture Nay</span>" in case
    assert "Abstained, as printed: <span data-item-title>Fixture Abstainer</span>" in case
    assert "<span data-item-title>Motion passes for approval 5-1</span>" in case
    assert f'<a href="{MINUTES}#page=2"' in case


def test_an_unconfirmed_motion_shows_its_type_and_the_county_note_only(site):
    sec = section(site)
    other = sec[sec.index('id="2026-10-27-regular-motions"'):]
    assert "<strong>Motion to approve the minutes.</strong>" in other
    assert "Not confirmed" in other and "Read it yourself" in other
    assert not config.SHOW_UNCONFIRMED_VALUES
    for hidden in ("Hidden Mover", "Hidden Seconder", "minutes were approved"):
        assert hidden not in sec


def test_planning_commission_to_county_commission_both_ways(site):
    sec = section(site)
    case = sec[sec.index(f'id="case-{CASE}"'):]
    m = re.search(r'Planning Commission → County Commission:</strong> <a href="([^"]+)">County Commission item '
                  r'CZ-12-2026</a>', case)
    assert m and m.group(1) == "../../items/2026.html#CZ-12-2026"
    items = (site / "items/2026.html").read_text(encoding="utf-8")
    block = items[items.index('id="CZ-12-2026"'):]
    assert "Planning Commission → County Commission:" in block
    assert f'href="../rpc/meetings/2026.html#case-{CASE}">Regional Planning Commission agenda, October 27, 2026: ' \
           f'CZ - 12 - 2026</a>' in block
    # only county zoning cases link (exact number); a Z- (city) case never does
    z = sec[sec.index('id="case-2026-10-27-regular-z-19-2026"'):]
    z = z[:z.index('<div class="item"')]
    assert "County Commission" not in z


def test_link_key_matches_the_county_number_form():
    assert link_key("CZ-12-2026") == link_key("CZ - 12 - 2026".replace(" ", "")) == "CZ-12-2026"
    assert link_key("CZ-01-2024") == "CZ-1-2024"


def test_a_motion_citing_a_page_outside_its_source_fails_the_build(tmp_path):
    facts = rpc_facts(tmp_path)
    facts["motions"] = [motion(1, source_id=facts["sources"][0]["id"], page=99)]
    p = tmp_path / "rpc.json"
    p.write_text(json.dumps(facts), encoding="utf-8")
    with pytest.raises(BuildError, match="cases or motions cite"):
        build(FIXTURE, tmp_path / "site", seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS,
              rpc={**rpc.load_config("cmc-rpc"), "facts_path": p})
