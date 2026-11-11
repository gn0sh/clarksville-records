"""The launch hold on Regional Planning Commission motions (config/localities/cmc-rpc/rpc.yml `hold_motions`,
sitegen/rpc.py shown_motions): while it is on, every motion is "Not confirmed" and under no case on every page, day
card and morning note, the export writes no motion row, and qa/site_checks.py fails a block shown confirmed or an
exported row. Off, the reader's rules apply as before (the other RPC tests run with it off: conftest.rpc_config_unheld).
FIXTURE facts: the motions of tests/test_export_rpc.py on the RPC agenda reader's own output on a real agenda."""
import csv
import io
import json
import re
import shutil
from datetime import date
from html import unescape
from pathlib import Path

import pytest

from collector import rpc_export as RE
from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT, rpc_config_unheld
from sitegen import config, days, morning, rpc
from sitegen.build import build
from test_export_rpc import MEETING, facts_with_motions

HELD_TEXT = ("Moved by", "seconded by", "Outcome, as printed", "Voted nay", "Abstained")
BLOCK = re.compile(r'<div class="rpc-motion(?P<nc> nc)?" id="(?P<id>[^"]+)">(?P<body>.*?)</div>', re.S)


def cfg(d: Path, hold: bool) -> dict:
    return {**rpc_config_unheld(), "hold_motions": hold, "facts_path": d / "rpc.json"}


def rec(d: Path, hold: bool) -> dict:
    """The record qa/site_checks.py reads (rpc_facts): rpc.json plus its rpc.yml as `_cfg`."""
    return {**json.loads((d / "rpc.json").read_text(encoding="utf-8")), "_cfg": cfg(d, hold)}


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    d = tmp_path_factory.mktemp("hold")
    facts = facts_with_motions(d)
    (d / "rpc.json").write_text(json.dumps(facts), encoding="utf-8")
    county = json.loads(FIXTURE.read_text(encoding="utf-8"))
    county["items"].append({"id": "CZ-12-2026", "link_basis": "number", "number": "CZ-12-2026",
                            "title": "FIXTURE: CZ-12-2026", "year": 2026})
    (d / "facts.json").write_text(json.dumps(county), encoding="utf-8")
    return d


def make(d: Path, hold: bool) -> Path:
    out = d / f"site-{'held' if hold else 'unheld'}" / "build" / "site"
    if not out.is_dir():
        build(d / "facts.json", out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, rpc=cfg(d, hold))
    return out


def blocks(site: Path) -> list[re.Match]:
    return [b for p in sorted((site / "rpc").rglob("*.html")) for b in BLOCK.finditer(p.read_text(encoding="utf-8"))]


def pages(site: Path) -> dict:
    from qa import site_checks as SC
    return {f.relative_to(site).as_posix(): SC.parse(f) for f in site.rglob("*.html")}


# ------------------------------------------------------------------ the switch
def test_the_shipped_config_holds_every_motion_and_site_checks_reads_it():
    from qa import site_checks as SC
    assert rpc.load_config("cmc-rpc")["hold_motions"] is True
    real = SC.rpc_facts({})         # a real build's record: rpc.json with rpc.yml as `_cfg`
    assert real is not None and SC.rpc_held(real)
    assert not SC.rpc_held({"_cfg": {}}) and not SC.rpc_held({"_cfg": {"hold_motions": False}})
    assert SC.rpc_held({"_cfg": {"hold_motions": "no"}})     # anything but false or absent: held (the safe side)


@pytest.mark.parametrize("rules", [rpc.MOTION_RULES, None])
def test_shown_motions_holds_every_motion_whatever_the_record_says(inputs, rules):
    ms = json.loads((inputs / "rpc.json").read_text(encoding="utf-8"))["motions"]
    held = rpc.shown_motions(ms, rules, True)
    assert len(held) == len(ms) and not any(mv["confirmed"] for mv in held)
    assert all(mv["case_id"] is None and mv["reasons"][-1] == rpc.WHY_HELD for mv in held)
    # off: as before the switch (the reader's rules and the record's own doubts decide)
    off = rpc.shown_motions(ms, rules, False)
    if rules is None:
        assert off == [{**mv, "confirmed": False, "case_id": None, "reasons": mv["reasons"] + [rpc.WHY_STALE]}
                       for mv in ms]
    else:
        assert [mv["id"] for mv in off if mv["confirmed"]] == [f"{MEETING}-motion-1", f"{MEETING}-motion-8"]
        assert next(mv for mv in off if mv["id"] == f"{MEETING}-motion-1")["case_id"] is not None


def test_a_hold_that_is_not_true_or_false_fails_the_build(inputs):
    facts = json.loads((inputs / "rpc.json").read_text(encoding="utf-8"))
    with pytest.raises(rpc.RpcError, match="hold_motions"):
        rpc.Rpc({**cfg(inputs, True), "hold_motions": "yes"}, facts)


# ------------------------------------------------------------------ pages
def test_held_pages_show_no_motion_confirmed_and_none_under_a_case(inputs):
    site = make(inputs, True)
    bs = blocks(site)
    facts = json.loads((inputs / "rpc.json").read_text(encoding="utf-8"))
    assert len(bs) == len(facts["motions"]) == 8 and all(b.group("nc") for b in bs)
    values = {v for mv in facts["motions"] for k in ("moved_by", "seconded_by", "outcome", "case")
              for v in [mv.get(k)] if v} | {v for mv in facts["motions"] for v in mv["nays"] + mv["abstained"]}
    for b in bs:
        body = unescape(b.group("body"))
        assert "Not confirmed" in body and "#page=" in body          # its type, the note and its minutes page
        leak = [v for v in (*values, *HELD_TEXT) if v in body]
        assert not leak, (b.group("id"), leak)
    year = (site / "rpc/meetings/2026.html").read_text(encoding="utf-8")
    assert 'class="zoning rpc-motions"' not in year            # no motion under any case
    assert f'id="{MEETING}-motions"' in year
    home = (site / "rpc/index.html").read_text(encoding="utf-8")
    assert "being re-checked against the minutes" in home and "who moved and seconded each" not in home


def test_unheld_pages_are_unchanged(inputs):
    site = make(inputs, False)
    shown = [b.group("id") for b in blocks(site) if not b.group("nc")]
    assert sorted(set(shown)) == [f"{MEETING}-motion-1", f"{MEETING}-motion-8"]
    assert 'class="zoning rpc-motions"' in (site / "rpc/meetings/2026.html").read_text(encoding="utf-8")
    assert "being re-checked" not in (site / "rpc/index.html").read_text(encoding="utf-8")


def test_site_checks_passes_the_held_pages_and_flags_a_confirmed_block_under_hold(inputs):
    from qa import site_checks as SC
    held = make(inputs, True)
    problems, note = SC.check_rpc_motions(held, pages(held), rec(inputs, True))
    assert problems == [] and "8 motion blocks, 0 shown confirmed" in note and "hold_motions on" in note, problems
    # the pages built with the hold off, checked as if it were on: every confirmed block, and every block under a
    # case, is a problem
    unheld = make(inputs, False)
    problems, _ = SC.check_rpc_motions(unheld, pages(unheld), rec(inputs, True))
    text = "\n".join(problems)
    assert f"#{MEETING}-motion-1: shown confirmed while rpc.yml hold_motions is on" in text
    assert f"#{MEETING}-motion-1: under case" in text
    # a motion block marked not confirmed, but showing its values, still fails (a)
    bad = inputs / "tampered"
    shutil.copytree(held, bad)
    y = bad / "rpc/meetings/2026.html"
    y.write_text(y.read_text(encoding="utf-8").replace('<p class="nc-note">', "<p>Moved by Fixture Mover</p>"
                                                       '<p class="nc-note">', 1), encoding="utf-8")
    problems, _ = SC.check_rpc_motions(bad, pages(bad), rec(inputs, True))
    assert any("a motion not confirmed shows" in p for p in problems), problems


# ------------------------------------------------------------------ export
def test_held_export_has_no_motion_row_and_site_checks_flags_one(inputs, tmp_path):
    from qa import site_checks as SC
    facts = json.loads((inputs / "rpc.json").read_text(encoding="utf-8"))
    rpx = rpc.Rpc(cfg(inputs, True), facts)
    assert RE.exported_motions(rpx) == []
    out = tmp_path / "held"
    written = {p.name: p for p in RE.export_rpc(rpx, out)}
    assert written["motions.csv"].read_text(encoding="utf-8").strip().count("\n") == 0       # the header only
    assert json.loads(written["facts.json"].read_text(encoding="utf-8"))["motions"] == []
    ms = {r["id"]: r for r in csv.DictReader(io.StringIO(written["meetings.csv"].read_text(encoding="utf-8")))}
    assert (ms[MEETING]["motions_confirmed"], ms[MEETING]["motions_not_confirmed"]) == ("0", "8")
    problems, note = SC.check_rpc_export(out, rec(inputs, True))
    assert problems == [] and "0 motions in data/rpc/motions.csv" in note and "hold_motions on" in note, problems
    # an export written with the hold off, checked with it on: every row is a problem
    out2 = tmp_path / "unheld"
    RE.export_rpc(rpc.Rpc(cfg(inputs, False), facts), out2)
    problems, _ = SC.check_rpc_export(out2, rec(inputs, True))
    assert f"data/rpc/motions.csv: motion {MEETING}-motion-1 exported while rpc.yml hold_motions is on" in problems
    assert f"data/rpc/facts.json: motion {MEETING}-motion-1 exported while rpc.yml hold_motions is on" in problems


# ------------------------------------------------------------------ day cards and the morning note
def test_day_card_and_morning_note_follow_the_hold(inputs):
    facts = json.loads((inputs / "rpc.json").read_text(encoding="utf-8"))
    txt = morning.settings(config.SITE)["text"]
    prefixes = morning.settings(config.SITE)["zoning_prefixes"]
    votes = {}
    for hold in (True, False):
        rpx = rpc.Rpc(cfg(inputs, hold), facts)
        card = days.rpc_card(rpx, next(m for m in facts["meetings"] if m["id"] == MEETING))
        if hold:
            assert all(not c["motions"] for c in card["rpc"]["cases"])
            assert card["rpc"]["other_motions"] and not any(mv["confirmed"] or mv["moved_by"] or mv["outcome"]
                                                            for mv in card["rpc"]["other_motions"])
        docs = morning._rpc_documents(rpx, txt, morning._Zoning(rpx, prefixes))
        votes[hold] = [e for d in docs for e in d["entries"] if e["kind"] == "vote"]
    assert votes[True] == []
    # off: the confirmed motion on the CZ-12-2026 zoning case is a confirmed vote entry, as before
    assert [(e["id"], e["confirmed"]) for e in votes[False]] == [(f"rpc/vote/{MEETING}-motion-1", True)]


# ------------------------------------------------------------------ site_checks rpc-morning (morning/*.json)
def make_with_note(d: Path, hold: bool) -> Path:
    """A build that writes the morning note for 2026-11-11: the RPC's documents first fetched on Nov 10, the county
    fixture's long before (so the RPC rows are not a collector's initial run)."""
    out = d / f"note-{'held' if hold else 'unheld'}" / "build" / "site"
    if out.is_dir():
        return out
    county = json.loads((d / "facts.json").read_text(encoding="utf-8"))
    rpcf = json.loads((d / "rpc.json").read_text(encoding="utf-8"))
    rows = [{"url": s["url"], "first_fetched_at": "2026-01-05T09:00:00+00:00", "kind": s["kind"]}
            for s in county["sources"]]
    rows += [{"url": s["url"], "first_fetched_at": "2026-11-10T20:00:00+00:00"} for s in rpcf["sources"]]
    (d / "manifest.json").write_text(json.dumps(rows), encoding="utf-8")
    build(d / "facts.json", out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, rpc=cfg(d, hold),
          morning_manifests=[d / "manifest.json"], today=date(2026, 11, 12), target="pages")
    return out


def test_site_checks_rpc_morning_fails_a_vote_entry_shown_under_hold(inputs):
    from qa import site_checks as SC
    unheld = make_with_note(inputs, False)
    note = json.loads((unheld / "morning/2026-11-11.json").read_text(encoding="utf-8"))
    assert not note["backfill"]
    votes = [e for e in note["entries"] if e["id"].startswith("rpc/vote/")]
    assert [(e["id"], e["confirmed"]) for e in votes] == [(f"rpc/vote/{MEETING}-motion-1", True)]
    assert SC.check_rpc_morning(unheld, rec(inputs, False))[0] == []
    # the same note checked with the hold on: the confirmed vote entry, with its outcome and tally, fails
    problems, _ = SC.check_rpc_morning(unheld, rec(inputs, True))
    assert any(p.startswith("morning/2026-11-11.json: rpc/vote/") and "confirmed, outcome, tally" in p
               and "hold_motions is on" in p for p in problems), problems
    # built with the hold on: no RPC vote entry at all, and the check passes
    held = make_with_note(inputs, True)
    problems, msg = SC.check_rpc_morning(held, rec(inputs, True))
    assert problems == [] and msg.startswith("0 RPC vote entries") and "hold_motions on" in msg, problems


def test_site_checks_rpc_morning_fails_a_name_or_a_stale_record(inputs, tmp_path):
    from qa import site_checks as SC
    site = tmp_path / "site"
    shutil.copytree(make_with_note(inputs, False), site)
    f = site / "morning/2026-11-11.json"
    note = json.loads(f.read_text(encoding="utf-8"))
    first = next(e for e in note["entries"] if e["id"] == f"rpc/vote/{MEETING}-motion-1")
    note["entries"].append({**first, "id": f"rpc/vote/{MEETING}-motion-2", "confirmed": False, "outcome": None,
                            "tally": None, "title": "Hidden Mover"})
    f.write_text(json.dumps(note), encoding="utf-8")
    problems, _ = SC.check_rpc_morning(site, rec(inputs, False))
    assert problems == [f"morning/2026-11-11.json: rpc/vote/{MEETING}-motion-2 shows Hidden Mover "
                        "(not confirmed in rpc.json)"], problems
    stale = {**rec(inputs, False), "motion_rules": None}
    problems, _ = SC.check_rpc_morning(site, stale)
    assert any(f"rpc/vote/{MEETING}-motion-1 shows confirmed" in p and "motion_rules is not current" in p
               for p in problems), problems


def test_site_checks_rpc_morning_fails_an_rpc_vote_entry_under_another_id(inputs, tmp_path):
    """rpc-hold/morning-id-drift: a vote entry of the RPC body whose id lacks rpc/vote/ would skip every rule."""
    from qa import site_checks as SC
    site = tmp_path / "site"
    shutil.copytree(make_with_note(inputs, False), site)
    f = site / "morning/2026-11-11.json"
    note = json.loads(f.read_text(encoding="utf-8"))
    first = next(e for e in note["entries"] if e["id"] == f"rpc/vote/{MEETING}-motion-1")
    assert (first["kind"], first["body"]) == ("vote", "rpc")
    note["entries"] += [{**first, "id": f"rpc/votes/{MEETING}-motion-1"}, {**first, "id": None},
                        {**first, "id": "other/vote/x", "body": "other"},                  # another body: not the RPC's
                        {**first, "id": f"rpc/item/{MEETING}-motion-1", "kind": "agenda_item"}]   # not a vote
    f.write_text(json.dumps(note), encoding="utf-8")
    problems, _ = SC.check_rpc_morning(site, rec(inputs, False))
    assert problems == [f"morning/2026-11-11.json: vote entry rpc/votes/{MEETING}-motion-1 of rpc lacks the "
                        "rpc/vote/<motion id> id",
                        "morning/2026-11-11.json: vote entry (no id) of rpc lacks the rpc/vote/<motion id> id"], problems


def test_site_checks_rpc_morning_fails_a_missing_note_when_one_is_expected(inputs, tmp_path):
    """rpc-hold/morning-dir-absent: a pages build with config morning_note set writes morning/; without it (or with
    no note in it) the check fails instead of passing on zero entries. Not expected (preview, no morning_note): pass."""
    from qa import site_checks as SC
    site = tmp_path / "site"
    shutil.copytree(make_with_note(inputs, True), site)
    assert SC.check_rpc_morning(site, rec(inputs, True), True)[0] == []
    for f in (site / "morning").glob("*.json"):
        f.unlink()
    for _ in range(2):      # an empty morning/, then none at all
        problems, msg = SC.check_rpc_morning(site, rec(inputs, True), True)
        assert problems == ["morning/: no morning note, though config morning_note is set and this is a pages build"]
        assert msg == "0 morning notes"
        assert SC.check_rpc_morning(site, rec(inputs, True))[0] == []
        shutil.rmtree(site / "morning", ignore_errors=True)
    assert not (site / "morning").exists()


def test_run_checks_fails_a_real_pages_build_without_its_morning_note(tmp_path):
    """run_checks wires note_expected from config morning_note and the target: the committed data built for pages
    (which writes morning/), checked with morning/ and then without it, as pages (FAIL) and as preview (pass). The
    checks run on the build's top-level pages and morning/ only: rpc-morning reads morning/*.json and rpc.json, and a
    whole real site takes minutes to check."""
    from qa import site_checks as SC
    built = tmp_path / "real" / "build" / "site"
    build(ROOT / "data" / "facts.json", built, target="pages")
    assert config.SITE.get("morning_note") is not None and (built / "morning").is_dir()
    site = tmp_path / "site"
    site.mkdir()
    for f in built.glob("*.html"):
        shutil.copy(f, site / f.name)
    shutil.copytree(built / "morning", site / "morning")
    facts = SC.load_facts(ROOT / "data" / "facts.json")
    assert SC.rpc_facts(facts) is not None and SC.rpc_held(SC.rpc_facts(facts))   # a real record, the hold on

    def rpc_morning(target):
        rep = SC.run_checks(site, facts, browser=False, target=target)
        return next(r for r in rep.results if r[0] == "rpc-morning")

    name, ok, problems, note = rpc_morning("pages")
    assert ok and problems == [] and "hold_motions on" in note and "0 morning notes" not in note, problems
    shutil.rmtree(site / "morning")
    name, ok, problems, note = rpc_morning("pages")
    assert not ok and problems == [
        "morning/: no morning note, though config morning_note is set and this is a pages build"], problems
    name, ok, problems, note = rpc_morning("preview")      # the preview writes no note: nothing expected
    assert ok and problems == [] and note.startswith("0 RPC vote entries in 0 morning notes"), problems


def test_show_unconfirmed_values_never_overrides_the_hold(inputs, monkeypatch):
    """config.SHOW_UNCONFIRMED_VALUES on shows a not-confirmed motion's values, but never while the hold is on."""
    facts = json.loads((inputs / "rpc.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(config, "SHOW_UNCONFIRMED_VALUES", True)
    hx = rpc.Rpc(cfg(inputs, True), facts)
    held = [hx.motion(mv) for mv in hx.motions]
    assert len(held) == 8
    assert all(m["moved_by"] is None and m["seconded_by"] is None and m["outcome"] is None and m["case"] is None
               and m["nays"] == [] and m["abstained"] == [] for m in held)
    rx = rpc.Rpc(cfg(inputs, False), facts)
    shown = rx.motion(next(mv for mv in rx.motions if mv["id"] == f"{MEETING}-motion-2"))      # not confirmed
    assert shown["confirmed"] is False and shown["moved_by"] == "Hidden Mover"
