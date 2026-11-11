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
from html import unescape
from pathlib import Path

import pytest

from collector import rpc_export as RE
from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, rpc_config_unheld
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
