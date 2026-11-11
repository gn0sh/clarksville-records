"""Regional Planning Commission milestone 2 pages (sitegen/rpc.py): the minutes' motions on each meeting section, the
county "Not confirmed" note on a motion that failed the reader's checks, and the Planning Commission -> County
Commission link on both sides. FIXTURE facts: the RPC agenda reader's own output on a real agenda (as in
test_rpc_pages.py), plus two made-up motions and one made-up county item with a CZ number."""
import json
import re
from pathlib import Path

import pytest

from collector.rpc_minutes import link_key
from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, rpc_config_unheld
from sitegen import config, rpc
from sitegen.build import BuildError, build
from test_rpc_pages import rpc_facts

MINUTES = "https://www.cmcrpc.com/wp2025/wp-content/uploads/2026/11/10.27.2026-RPC-Minutes.pdf"
CASE = "2026-10-27-regular-cz-12-2026"
Z19 = "2026-10-27-regular-z-19-2026"


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
        # docs/architecture/rpc-motion-invariant.md: an off-agenda case the reader did not confirm
        motion(3, case="ZO-4-2024", moved_by="Off Mover", seconded_by="Off Seconder", outcome="Motion passed",
               confirmed=False, reasons=["case number not on this meeting's agenda"]),
        # a record written before the invariant: confirmed there, but the record itself shows the doubt
        motion(4, case="ZO-5-2024", moved_by="Stale Mover", outcome="Motion passed stale"),     # off this agenda
        motion(5, case="Z-19-2026", case_id=Z19, moved_by="Crowded Mover A"),                  # two approvals on
        motion(6, case="Z-19-2026", case_id=Z19, moved_by="Crowded Mover B"),                  # one case
        motion(7, moved_by="Caseless Mover"),                       # no case, not the meeting's own business
        motion(8, kind="Motion to adjourn", outcome="carried unanimously"),     # the minutes' own words
    ]
    (d / "rpc.json").write_text(json.dumps(facts), encoding="utf-8")
    county = json.loads(FIXTURE.read_text(encoding="utf-8"))
    county["items"].append({"id": "CZ-12-2026", "link_basis": "number", "number": "CZ-12-2026",
                            "title": "FIXTURE: CZ-12-2026", "year": 2026})
    (d / "facts.json").write_text(json.dumps(county), encoding="utf-8")
    out = d / "build" / "site"
    build(d / "facts.json", out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS,
          rpc={**rpc_config_unheld(), "facts_path": d / "rpc.json"})
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
              rpc={**rpc_config_unheld(), "facts_path": p})


def test_an_unconfirmed_off_agenda_motion_shows_no_case_number(site):
    sec = section(site)
    block = sec[sec.index('id="2026-10-27-regular-motion-3"'):]
    block = block[:block.index("</div>")]
    assert "<strong>Motion for approval.</strong>" in block and "Not confirmed" in block
    for hidden in ("ZO-4-2024", "Off Mover", "Off Seconder", "Motion passed"):
        assert hidden not in block


def test_a_stored_record_is_shown_under_the_invariant(site):
    """Checks the record alone allows (sitegen/rpc.py record_doubts): an off-agenda case, two disposing motions on
    one case, a caseless motion that is not the meeting's business. Each is shown not confirmed, with no values, in
    the meeting's own list (never under the case it doubts)."""
    sec = section(site)
    other = sec[sec.index('id="2026-10-27-regular-motions"'):]
    z19 = sec[sec.index(f'id="case-{Z19}"'):sec.index('id="2026-10-27-regular-motions"')]
    z19 = z19[:z19.index('<div class="item"')] if '<div class="item"' in z19 else z19
    for k in (4, 5, 6, 7):
        assert f'<div class="rpc-motion nc" id="2026-10-27-regular-motion-{k}">' in other
        assert f'id="2026-10-27-regular-motion-{k}"' not in z19
    for hidden in ("Stale Mover", "ZO-5-2024", "Motion passed stale", "Crowded Mover", "Caseless Mover"):
        assert hidden not in sec
    assert '<div class="rpc-motion" id="2026-10-27-regular-motion-8">' in other      # the meeting's own business
    home = (site / "rpc/index.html").read_text(encoding="utf-8")
    assert "8 motions are read from the minutes (2 confirmed)" in home


def test_record_doubts_restates_the_record_checks():
    ms = [motion(1, case="Z-1-2026", case_id="c1", nays=["Mr. Mover"], moved_by="Fixture Mover"),
          motion(2, case="Z-2-2026", case_id="c2", abstained=["Fixture Seconder"]),
          motion(3, case="Z-3-2026", case_id="c3", kind="Motion to approve the consent agenda"),
          motion(4, case="Z-3-2026", case_id="c3"),
          motion(5, kind="Motion to elect")]
    d = rpc.record_doubts(ms)
    assert d == {"2026-10-27-regular-motion-1": (["a member named as voting nay is the mover or seconder"], False),
                 "2026-10-27-regular-motion-2": (["a member named as voting nay is the mover or seconder"], False)}
    shown = {mv["id"]: mv for mv in rpc.shown_motions(ms, rpc.MOTION_RULES, False)}
    assert shown["2026-10-27-regular-motion-1"]["case_id"] == "c1"      # the doubt is not about the case
    assert not shown["2026-10-27-regular-motion-1"]["confirmed"] and shown["2026-10-27-regular-motion-4"]["confirmed"]


def test_no_page_says_unanimous_outside_the_minutes_own_words(site):
    for p in (site / "rpc").rglob("*.html"):
        text = re.sub(r"<span data-item-title>.*?</span>", "", p.read_text(encoding="utf-8"), flags=re.S)
        assert "unanimous" not in re.sub(r"<[^>]+>", " ", text).lower(), p
    assert "<span data-item-title>carried unanimously</span>" in section(site)


def test_search_records_carry_no_motion_fields(site):
    facts = json.loads((site.parent.parent / "rpc.json").read_text(encoding="utf-8"))
    recs = rpc.Rpc({**rpc_config_unheld(), "facts_path": site.parent.parent / "rpc.json"}, facts).search_records()
    blob = json.dumps(recs)
    for value in ("Fixture Mover", "Hidden Mover", "Stale Mover", "Motion passes for approval", "Fixture Nay"):
        assert value not in blob


def _site_rpc(site: Path) -> dict:
    facts = json.loads((site.parent.parent / "rpc.json").read_text(encoding="utf-8"))
    return {**facts, "_cfg": rpc_config_unheld()}


def test_site_checks_rpc_motions_passes_on_the_built_pages(site):
    from qa import site_checks as SC
    pages = {f.relative_to(site).as_posix(): SC.parse(f) for f in site.rglob("*.html")}
    problems, note = SC.check_rpc_motions(site, pages, _site_rpc(site))
    assert problems == [] and ("8 motion blocks, 2 shown confirmed (6 confirmed in rpc.json; motion_rules "
                               "rpc-motion-invariant-1)") in note, problems


def test_site_checks_rpc_motions_catches_a_leak_a_misplaced_motion_and_unanimous(site, tmp_path):
    import shutil
    from qa import site_checks as SC
    bad = tmp_path / "site"
    shutil.copytree(site, bad)
    page = bad / "rpc/meetings/2026.html"
    html = page.read_text(encoding="utf-8")
    # a not-confirmed block that shows its mover; a stale-confirmed block shown as confirmed; our own "unanimous"
    html = html.replace('<div class="rpc-motion nc" id="2026-10-27-regular-motion-3">',
                        '<div class="rpc-motion nc" id="2026-10-27-regular-motion-3">Off Mover')
    html = html.replace('<div class="rpc-motion nc" id="2026-10-27-regular-motion-5">',
                        '<div class="rpc-motion" id="2026-10-27-regular-motion-5">')
    html = html.replace("</h1>", " All votes were unanimous.</h1>", 1)
    page.write_text(html, encoding="utf-8")
    pages = {f.relative_to(bad).as_posix(): SC.parse(f) for f in bad.rglob("*.html")}
    problems, _ = SC.check_rpc_motions(bad, pages, _site_rpc(site))
    text = "\n".join(problems)
    assert "motion-3: a motion not confirmed shows Off Mover" in text
    assert "motion-5: confirmed, but not under its own case on its meeting's agenda" in text
    assert "says 'unanimous' outside the minutes' own words" in text


def test_site_checks_rpc_motions_on_a_record_the_reader_never_wrote(tmp_path):
    """(b) two confirmed disposing motions on one case, (c) a confirmed caseless approval, (d) a nay who is the
    mover: each fails, whatever wrote the record."""
    from qa import site_checks as SC
    page = tmp_path / "rpc" / "meetings" / "2026.html"
    page.parent.mkdir(parents=True)
    blocks = "".join(f'<div class="rpc-motion" id="m-{k}"><p>x</p></div>' for k in (1, 2))
    page.write_text(f'<section id="mt"><div id="case-c1">{blocks}</div><h3 id="mt-motions"></h3>'
                    '<div class="rpc-motion" id="m-3"><p>x</p></div></section>', encoding="utf-8")
    rec = _guard_record(motion(1, id="m-1", meeting_id="mt", case="Z-1-2026", case_id="c1"),
                        motion(2, id="m-2", meeting_id="mt", case="Z-1-2026", case_id="c1", nays=["Mr. Mover"]),
                        motion(3, id="m-3", meeting_id="mt"))
    pages = {"rpc/meetings/2026.html": SC.parse(page)}
    text = "\n".join(SC.check_rpc_motions(tmp_path, pages, rec)[0])
    assert "case-c1: 2 confirmed disposing motions on one case" in text
    assert "m-3: confirmed with no agenda case, and not the meeting's own business" in text
    assert "m-2: confirmed, with a nay or abstainer who is its mover or seconder" in text


# ------------------------------------------------------------------ rpc-motion/c3-stale-record: the motion_rules marker
def test_the_motion_rules_marker_is_one_value_in_the_reader_the_pages_and_the_site_check():
    from collector import rpc_minutes
    from qa import site_checks as SC
    assert rpc_minutes.MOTION_RULES == rpc.MOTION_RULES == SC.RPC_MOTION_RULES == "rpc-motion-invariant-1"


@pytest.mark.parametrize("rules", [None, "rpc-motion-invariant-0"])
def test_a_record_without_the_current_motion_rules_confirms_nothing_and_places_nothing(rules):
    ms = [motion(1, case="Z-1-2026", case_id="c1"), motion(2, kind="Motion to adjourn")]
    shown = rpc.shown_motions(ms, rules, False)
    assert [(mv["confirmed"], mv["case_id"]) for mv in shown] == [(False, None), (False, None)]
    assert all(rpc.WHY_STALE in mv["reasons"] for mv in shown)
    assert [mv["confirmed"] for mv in rpc.shown_motions(ms, rpc.MOTION_RULES, False)] == [True, True]


@pytest.fixture(scope="module")
def stale_site(tmp_path_factory):
    """The site built from a record written before the reader's motion rules (no `motion_rules`), as the committed
    data/localities/cmc-rpc/rpc.json is until its rebuild: two motions it marks confirmed, one on its agenda case."""
    d = tmp_path_factory.mktemp("rpcstale")
    facts = rpc_facts(d)
    assert facts.pop("motion_rules") == rpc.MOTION_RULES       # rpc_agenda.build writes it
    facts["sources"].append({"id": "src-fixturemin", "url": MINUTES, "sha256": "0" * 64, "kind": "minutes",
                             "meeting_date": "2026-10-27", "fetched_at": "2026-11-10", "pages": 3,
                             "text_layer": "none", "format": "pdf", "read_by": "OCR"})
    facts["motions"] = [motion(1, case="CZ-12-2026", case_id=CASE, moved_by="Stale Case Mover",
                               outcome="Motion passes for approval 6-0", tally="6-0"),
                        motion(2, kind="Motion to adjourn", moved_by="Stale Adjourn Mover",
                               outcome="carried unanimously")]
    (d / "rpc.json").write_text(json.dumps(facts), encoding="utf-8")
    out = d / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS,
          rpc={**rpc_config_unheld(), "facts_path": d / "rpc.json"})
    return out


def test_a_stale_record_shows_every_motion_not_confirmed_in_the_meetings_own_list(stale_site):
    sec = section(stale_site)
    case = sec[sec.index(f'id="case-{CASE}"'):sec.index('id="2026-10-27-regular-motions"')]
    assert "rpc-motion" not in case             # C1 is in doubt too: placed under no case
    other = sec[sec.index('id="2026-10-27-regular-motions"'):]
    for k in (1, 2):
        assert f'<div class="rpc-motion nc" id="2026-10-27-regular-motion-{k}">' in other
    for hidden in ("Stale Case Mover", "Stale Adjourn Mover", "Fixture Seconder", "6-0", "carried unanimously",
                   "(CZ-12-2026)", "Moved by", "Outcome, as printed"):
        assert hidden not in sec
    home = (stale_site / "rpc/index.html").read_text(encoding="utf-8")
    assert "2 motions are read from the minutes (0 confirmed)" in home


def test_site_checks_passes_a_stale_record_shown_with_nothing_confirmed(stale_site):
    from qa import site_checks as SC
    pages = {f.relative_to(stale_site).as_posix(): SC.parse(f) for f in stale_site.rglob("*.html")}
    problems, note = SC.check_rpc_motions(stale_site, pages, _site_rpc(stale_site))
    assert problems == [], problems
    assert "2 motion blocks, 0 shown confirmed (2 confirmed in rpc.json; motion_rules not current: None)" in note


def test_site_checks_fails_a_stale_record_shown_confirmed(stale_site, tmp_path):
    """(f): the record marks the motion confirmed, but it was not read under the current rules, so the page may not
    show it confirmed, and its values count as a leak."""
    import shutil
    from qa import site_checks as SC
    bad = tmp_path / "site"
    shutil.copytree(stale_site, bad)
    page = bad / "rpc/meetings/2026.html"
    html = page.read_text(encoding="utf-8")
    html = html.replace('<div class="rpc-motion nc" id="2026-10-27-regular-motion-2">',
                        '<div class="rpc-motion" id="2026-10-27-regular-motion-2">Stale Adjourn Mover')
    page.write_text(html, encoding="utf-8")
    pages = {f.relative_to(bad).as_posix(): SC.parse(f) for f in bad.rglob("*.html")}
    problems, note = SC.check_rpc_motions(bad, pages, _site_rpc(stale_site))
    text = "\n".join(problems)
    assert "motion-2: shown confirmed, but rpc.json was not written under the reader's current motion rules" in text
    assert "motion-2: a motion not confirmed shows Stale Adjourn Mover" in text
    assert "0 shown confirmed" in note


# ------------------------------------------------------------------ rpc-motion/qa-guard nits
def _guard_page(tmp_path: Path, rel: str, body: str) -> Path:
    page = tmp_path / rel
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(body, encoding="utf-8")
    return page


def _guard_record(*motions) -> dict:
    return {"_cfg": {"slug": "rpc"}, "motion_rules": rpc.MOTION_RULES,
            "cases": [{"id": "c1", "meeting_id": "mt"}], "motions": list(motions)}


def test_site_checks_counts_a_motion_shown_on_two_pages_once(tmp_path):
    from qa import site_checks as SC
    block = '<section id="mt"><div id="case-c1"><div class="rpc-motion" id="m-1"><p>x</p></div></div></section>'
    pages = {rel: SC.parse(_guard_page(tmp_path, rel, block))
             for rel in ("rpc/meetings/2026.html", "rpc/meetings/copy.html")}
    rec = _guard_record(motion(1, id="m-1", meeting_id="mt", case="Z-1-2026", case_id="c1"))
    problems, note = SC.check_rpc_motions(tmp_path, pages, rec)
    assert problems == [] and "2 motion blocks, 2 shown confirmed" in note, problems


@pytest.mark.parametrize("rel,body", [
    ("today.html", '<article class="day-card day-card-rpc" id="rpc-x"><p>The vote was unanimous.</p></article>'),
    ("index.html", "<p>Every Planning Commission vote was unanimous.</p>"),
    ("meetings.html", '<article class="day-card day-card-rpc" id="rpc-x"><p>Unanimous.</p></article>'),
])
def test_site_checks_reads_every_page_with_rpc_content_for_unanimous(tmp_path, rel, body):
    from qa import site_checks as SC
    pages = {rel: SC.parse(_guard_page(tmp_path, rel, body))}
    problems, _ = SC.check_rpc_motions(tmp_path, pages, _guard_record())
    assert problems == [f"{rel}: says 'unanimous' outside the minutes' own words"]
    words = re.sub(r"<p>(.*?)</p>", r"<p><span data-item-title>\1</span></p>", body)    # the document's own words
    pages = {rel: SC.parse(_guard_page(tmp_path, rel, words))}
    assert SC.check_rpc_motions(tmp_path, pages, _guard_record())[0] == []


def test_site_checks_leaves_a_county_page_without_rpc_content_to_its_own_checks(tmp_path):
    from qa import site_checks as SC
    pages = {"items/2026.html": SC.parse(_guard_page(tmp_path, "items/2026.html", "<p>unanimous</p>"))}
    assert SC.check_rpc_motions(tmp_path, pages, _guard_record())[0] == []
