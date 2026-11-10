"""Regional Planning Commission export (collector/rpc_export.py): data/<slug>/facts.json, meetings.csv, cases.csv,
motions.csv, sources.csv, and the Data page that lists them.

Invariant (docs/architecture/rpc-motion-invariant.md): a motion leaves in a file only when the pages show it
confirmed; nothing of a motion that is not confirmed (names, outcome, case number, the reader's reasons) is in any
public file. FIXTURE facts for the confirmed case (the RPC agenda reader's output on a real agenda plus made-up
motions, as tests/test_rpc_minutes_pages.py); the committed rpc.json for the state before its rebuild.
"""
import csv
import io
import re
from html import unescape
import json
from pathlib import Path

import pytest

from collector import rpc_export as RE
from collector.export import SRC_COLS, export_site
from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS
from sitegen import config, rpc, views
from sitegen.build import build, export_file_count
from test_rpc_minutes_pages import CASE, MINUTES, Z19, motion
from test_rpc_pages import rpc_facts

ROOT = Path(__file__).resolve().parent.parent
MEETING = "2026-10-27-regular"
# every made-up value of a motion that must not be exported (not confirmed by the reader, or doubted by the record)
HELD = ("Hidden Mover", "Hidden Seconder", "Off Mover", "Off Seconder", "ZO-4-2024", "Stale Mover", "ZO-5-2024",
        "Motion passed stale", "Crowded Mover", "Caseless Mover", "Held Nay", "Held Abstainer",
        "mover is not one member present", "not on this meeting's agenda", "subject not read",
        "more than one motion on one case section")


def facts_with_motions(d: Path) -> dict:
    facts = rpc_facts(d)
    facts["sources"].append({"id": "src-fixturemin", "url": MINUTES, "sha256": "0" * 64, "kind": "minutes",
                             "meeting_date": "2026-10-27", "fetched_at": "2026-11-10", "pages": 3,
                             "text_layer": "none", "format": "pdf", "read_by": "OCR"})
    m = next(m for m in facts["meetings"] if m["id"] == MEETING)
    m.update({"minutes_source_id": "src-fixturemin", "minutes_read_by": "OCR", "minutes_date": "2026-10-27"})
    facts["motions"] = [
        motion(1, case="CZ-12-2026", case_id=CASE, nays=["Fixture Nay", "Second Nay"], abstained=["Fixture Abstainer"],
               outcome="Motion passes for approval 5-1", tally="5-1"),
        motion(2, kind="Motion to approve the minutes", moved_by="Hidden Mover", seconded_by="Hidden Seconder",
               nays=["Held Nay"], abstained=["Held Abstainer"], outcome="minutes were approved", confirmed=False,
               reasons=["mover is not one member present"]),
        motion(3, case="ZO-4-2024", moved_by="Off Mover", seconded_by="Off Seconder", outcome="Motion passed",
               confirmed=False, reasons=["case number not on this meeting's agenda"]),
        # marked confirmed in the record, but the record itself shows the doubt (sitegen.rpc.record_doubts)
        motion(4, case="ZO-5-2024", moved_by="Stale Mover", outcome="Motion passed stale"),
        motion(5, case="Z-19-2026", case_id=Z19, moved_by="Crowded Mover A"),
        motion(6, case="Z-19-2026", case_id=Z19, moved_by="Crowded Mover B"),
        motion(7, moved_by="Caseless Mover"),
        motion(8, kind="Motion to adjourn", outcome="carried unanimously", page=3),     # the minutes' own words
    ]
    return facts


def load(d: Path, facts: dict) -> rpc.Rpc:
    (d / "rpc.json").write_text(json.dumps(facts), encoding="utf-8")
    return rpc.load({**rpc.load_config("cmc-rpc"), "facts_path": d / "rpc.json"}, True)


def rows(path: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))


@pytest.fixture(scope="module")
def rpx(tmp_path_factory):
    d = tmp_path_factory.mktemp("rpcx")
    return load(d, facts_with_motions(d))


@pytest.fixture(scope="module")
def files(tmp_path_factory, rpx):
    out = tmp_path_factory.mktemp("pub")
    return {p.name: p for p in RE.export_rpc(rpx, out)}


@pytest.fixture(scope="module")
def stale_files(tmp_path_factory):
    """A record written before the reader's motion rules (no `motion_rules`), as the committed rpc.json is until its
    rebuild: the same motions, the same stored `confirmed` flags."""
    d = tmp_path_factory.mktemp("rpcstalex")
    facts = facts_with_motions(d)
    assert facts.pop("motion_rules") == rpc.MOTION_RULES
    return {p.name: p for p in RE.export_rpc(load(d, facts), d / "out")}


def test_the_files_and_where_they_live(files, rpx):
    assert sorted(files) == sorted(["facts.json"] + [f"{n}.csv" for n in RE.RPC_FILES])
    assert all(p.parent.name == rpx.slug == "rpc" and p.parent.parent.name == "data" for p in files.values())


# ------------------------------------------------------------------ motions: confirmed only
def test_only_the_motions_the_pages_show_confirmed_are_exported(files, rpx):
    ms = rows(files["motions.csv"])
    shown = {mv["id"] for mv in rpx.motions if mv["confirmed"]}
    assert {r["id"] for r in ms} == shown == {f"{MEETING}-motion-1", f"{MEETING}-motion-8"}
    data = json.loads(files["facts.json"].read_text(encoding="utf-8"))
    assert {mv["id"] for mv in data["motions"]} == shown
    assert data["motion_rules"] == rpc.MOTION_RULES


def test_a_confirmed_motion_carries_its_values_as_printed_and_its_source(files):
    ms = {r["id"]: r for r in rows(files["motions.csv"])}
    r = ms[f"{MEETING}-motion-1"]
    assert r == {"id": f"{MEETING}-motion-1", "meeting_id": MEETING, "date": "2026-10-27", "case_id": CASE,
                 "case_number": "CZ-12-2026", "kind": "Motion for approval", "moved_by": "Fixture Mover",
                 "seconded_by": "Fixture Seconder", "nays": "Fixture Nay; Second Nay",
                 "abstained": "Fixture Abstainer", "outcome": "Motion passes for approval 5-1",
                 "source_url": MINUTES, "source_sha256": "0" * 64, "page": "2", "fetched_at": "2026-11-10"}
    adjourn = ms[f"{MEETING}-motion-8"]
    # meeting business has no case; no nay named is an empty cell, never a word of ours
    assert (adjourn["case_id"], adjourn["case_number"], adjourn["nays"], adjourn["abstained"]) == ("", "", "", "")
    assert adjourn["outcome"] == "carried unanimously" and adjourn["page"] == "3"
    data = json.loads(files["facts.json"].read_text(encoding="utf-8"))
    j = next(mv for mv in data["motions"] if mv["id"] == f"{MEETING}-motion-1")
    assert j["nays"] == ["Fixture Nay", "Second Nay"] and j["abstained"] == ["Fixture Abstainer"]
    assert "tally" not in j and "confirmed" not in j and "reasons" not in j


def test_nothing_of_an_unconfirmed_motion_is_in_any_public_file(files):
    for name, p in files.items():
        text = p.read_text(encoding="utf-8")
        for token in HELD:
            assert token not in text, (name, token)
        for k in range(2, 8):
            assert f"{MEETING}-motion-{k}" not in text, (name, k)
        assert "reasons" not in text and "tally" not in text, name


def test_no_word_of_ours_says_unanimous(files):
    """Unanimity is never inferred: the word is in a file only inside an outcome the minutes print."""
    for name, p in files.items():
        if name == "motions.csv":
            hits = [r for r in rows(p) if any("unanim" in (v or "").casefold() for k, v in r.items() if k != "outcome")]
            assert not hits
            assert "unanim" not in p.read_text(encoding="utf-8").splitlines()[0].casefold()
        elif name == "facts.json":
            data = json.loads(p.read_text(encoding="utf-8"))
            for mv in data["motions"]:
                mv.pop("outcome")
            assert "unanim" not in json.dumps(data).casefold()
        else:
            assert "unanim" not in p.read_text(encoding="utf-8").casefold(), name


def test_meetings_count_the_motions_held_back(files):
    m = next(r for r in rows(files["meetings.csv"]) if r["id"] == MEETING)
    assert (m["motions_confirmed"], m["motions_not_confirmed"]) == ("2", "6")
    assert sum(int(r["motions_confirmed"]) for r in rows(files["meetings.csv"])) == len(rows(files["motions.csv"]))


@pytest.mark.parametrize("rules", [None, "rpc-motion-invariant-0"])
def test_a_record_without_the_current_motion_rules_exports_no_motion(tmp_path, rules):
    facts = facts_with_motions(tmp_path)
    facts["motion_rules"] = rules
    if rules is None:
        del facts["motion_rules"]
    written = {p.name: p for p in RE.export_rpc(load(tmp_path, facts), tmp_path / "out")}
    assert rows(written["motions.csv"]) == []
    data = json.loads(written["facts.json"].read_text(encoding="utf-8"))
    assert data["motions"] == [] and data["motion_rules"] == rules
    m = next(r for r in rows(written["meetings.csv"]) if r["id"] == MEETING)
    assert (m["motions_confirmed"], m["motions_not_confirmed"]) == ("0", "8")


def test_a_stale_record_leaks_no_motion_value(stale_files):
    for name, p in stale_files.items():
        text = p.read_text(encoding="utf-8")
        for token in HELD + ("Fixture Mover", "Fixture Seconder", "Fixture Nay", "Fixture Abstainer",
                             "Motion passes for approval", "carried unanimously", "-motion-"):
            assert token not in text, (name, token)
    # the header is still written, so the file's shape does not change at the rebuild
    assert stale_files["motions.csv"].read_text(encoding="utf-8").splitlines() == [",".join(RE.MOTION_COLS + SRC_COLS)]


def test_the_stored_confirmed_flag_alone_never_exports_a_motion(tmp_path):
    """`confirmed` must be true on the pages' view (shown_motions): a truthy value that is not True, or a motion the
    record itself doubts, is not exported."""
    facts = facts_with_motions(tmp_path)
    facts["motions"] = [motion(1, case="CZ-12-2026", case_id=CASE, confirmed="yes"),
                        motion(2, kind="Motion to adjourn", moved_by="Same Person", nays=["Mr. Person"]),
                        motion(3, kind="Motion to adjourn")]
    written = {p.name: p for p in RE.export_rpc(load(tmp_path, facts), tmp_path / "out")}
    assert [r["id"] for r in rows(written["motions.csv"])] == [f"{MEETING}-motion-3"]


def test_a_motion_stored_confirmed_with_a_reason_is_not_exported(tmp_path):
    """`confirmed` is `not reasons` in the reader: a record that says both (true, with a reason) is in doubt."""
    from qa import site_checks as SC
    facts = facts_with_motions(tmp_path)
    facts["motions"] = [motion(1, kind="Motion to adjourn", moved_by="Reasoned Mover", reasons=["subject not read"]),
                        motion(2, kind="Motion to adjourn")]
    written = {p.name: p for p in RE.export_rpc(load(tmp_path, facts), tmp_path / "site")}
    assert [r["id"] for r in rows(written["motions.csv"])] == [f"{MEETING}-motion-2"]
    assert all("Reasoned Mover" not in p.read_text(encoding="utf-8") for p in written.values())
    # the guard reads it the same way
    rec = {**facts, "_cfg": rpc.load_config("cmc-rpc")}
    data = json.loads(written["facts.json"].read_text(encoding="utf-8"))
    data["motions"].append(dict(data["motions"][0], id=f"{MEETING}-motion-1"))
    written["facts.json"].write_text(json.dumps(data), encoding="utf-8")
    assert SC.check_rpc_export(tmp_path / "site", rec)[0] == [
        f"data/rpc/facts.json: motion {MEETING}-motion-1 is not confirmed in rpc.json"]


def test_a_motion_the_pages_place_nowhere_is_not_exported(tmp_path):
    """The export carries what the pages place: a confirmed motion whose case_id is no case on its own meeting's agenda
    (a case of another meeting, or none at all), or whose meeting is not listed, is on no page and in no file."""
    facts = facts_with_motions(tmp_path)
    other = "2026-01-27-regular"
    facts["motions"] = [
        motion(1, case="CZ-12-2026", case_id=CASE),
        {**motion(2, case="CZ-12-2026", case_id=CASE, moved_by="Elsewhere Mover"),
         "id": f"{other}-motion-1", "meeting_id": other},
        motion(3, case="Z-77-2026", case_id=f"{MEETING}-z-77-2026", moved_by="Nowhere Mover"),
        {**motion(4, kind="Motion to adjourn", moved_by="Unlisted Mover"), "id": "2026-12-01-regular-motion-1",
         "meeting_id": "2026-12-01-regular"},
        motion(5, kind="Motion to adjourn"),
    ]
    rx = load(tmp_path, facts)
    assert {mv["id"] for mv in rx.motions if mv["confirmed"]} == {mv["id"] for mv in facts["motions"]}
    written = {p.name: p for p in RE.export_rpc(rx, tmp_path / "out")}
    assert [r["id"] for r in rows(written["motions.csv"])] == [f"{MEETING}-motion-1", f"{MEETING}-motion-5"]
    for p in written.values():
        text = p.read_text(encoding="utf-8")
        assert not any(t in text for t in ("Elsewhere Mover", "Nowhere Mover", "Unlisted Mover", "z-77")), p.name
    ms = {r["id"]: r for r in rows(written["meetings.csv"])}
    assert (ms[MEETING]["motions_confirmed"], ms[MEETING]["motions_not_confirmed"]) == ("2", "1")
    assert (ms[other]["motions_confirmed"], ms[other]["motions_not_confirmed"]) == ("0", "1")


def test_motions_on_one_page_keep_the_minutes_order(tmp_path):
    """Same meeting and page: by the motion's number (its content position), so motion-10 follows motion-9."""
    facts = facts_with_motions(tmp_path)
    facts["motions"] = [motion(k, kind="Motion to adjourn") for k in (10, 2, 9, 1)]
    written = {p.name: p for p in RE.export_rpc(load(tmp_path, facts), tmp_path / "out")}
    want = [f"{MEETING}-motion-{k}" for k in (1, 2, 9, 10)]
    assert [r["id"] for r in rows(written["motions.csv"])] == want
    assert [mv["id"] for mv in json.loads(written["facts.json"].read_text(encoding="utf-8"))["motions"]] == want


def _export_site_dir(tmp_path: Path, facts: dict) -> tuple[Path, dict]:
    """A built site's data/rpc/ as the export writes it, and the rpc.json record site_checks reads."""
    site = tmp_path / "site"
    RE.export_rpc(load(tmp_path, facts), site)
    return site, {**json.loads((tmp_path / "rpc.json").read_text(encoding="utf-8")), "_cfg": rpc.load_config("cmc-rpc")}


def test_site_checks_rpc_export_passes_on_the_export(tmp_path):
    from qa import site_checks as SC
    site, rec = _export_site_dir(tmp_path, facts_with_motions(tmp_path))
    problems, note = SC.check_rpc_export(site, rec)
    assert problems == [] and "2 motions in data/rpc/motions.csv and facts.json" in note, problems
    # no export written (a --no-export build): nothing to check
    assert SC.check_rpc_export(tmp_path / "none", rec) == ([], "no data/rpc/ export")


def test_site_checks_rpc_export_catches_an_unconfirmed_a_crowded_and_an_internal_motion(tmp_path):
    """Restated from rpc.json: every exported motion is `confirmed: true` under the current motion_rules and placed on
    its own meeting's case, one disposing motion per case_id, and no confirmed/reasons/tally key or column."""
    from qa import site_checks as SC
    site, rec = _export_site_dir(tmp_path, facts_with_motions(tmp_path))
    d = site / "data" / "rpc"
    data = json.loads((d / "facts.json").read_text(encoding="utf-8"))
    held = next(mv for mv in rec["motions"] if mv["id"] == f"{MEETING}-motion-2")
    crowd = next(mv for mv in rec["motions"] if mv["id"] == f"{MEETING}-motion-5")
    data["motions"] += [{k: held.get(k) for k in data["motions"][0]}, {k: crowd.get(k) for k in data["motions"][0]}]
    data["motions"][0]["reasons"] = []
    data["motions"][0]["tally"] = "5-1"
    (d / "facts.json").write_text(json.dumps(data), encoding="utf-8")
    text = (d / "motions.csv").read_text(encoding="utf-8")
    head, *body = text.splitlines()
    (d / "motions.csv").write_text("\n".join([head + ",confirmed", *(b + ",True" for b in body),
                                              held["id"] + "," + MEETING + ",,,,,,,,,,,,,,True"]) + "\n",
                                   encoding="utf-8")
    text = "\n".join(SC.check_rpc_export(site, rec)[0])
    assert f"data/rpc/facts.json: motion {MEETING}-motion-2 is not confirmed in rpc.json" in text
    assert f"data/rpc/motions.csv: motion {MEETING}-motion-2 is not confirmed in rpc.json" in text
    assert "data/rpc/motions.csv: column confirmed" in text
    assert f"data/rpc/facts.json: motion {MEETING}-motion-1 carries reasons, tally" in text
    # two disposing motions on one case_id (stored confirmed; the pages hold both back as crowded), a motion moved
    # off its own case, and a caseless approval that is not the meeting's own business
    by_id = {mv["id"]: mv for mv in rec["motions"]}
    keys = [k for k in data["motions"][0] if k not in ("reasons", "tally")]

    def row(k, **kw):
        return {**{key: by_id[f"{MEETING}-motion-{k}"].get(key) for key in keys}, **kw}
    data["motions"] = [row(5), row(6), row(1, case_id=None), row(7)]
    (d / "facts.json").write_text(json.dumps(data), encoding="utf-8")
    text = "\n".join(SC.check_rpc_export(site, rec)[0])
    assert f"data/rpc/facts.json: 2 disposing motions on case {Z19}" in text
    assert f"data/rpc/facts.json: motion {MEETING}-motion-1 is not under its own case" in text
    assert f"data/rpc/facts.json: motion {MEETING}-motion-7 has no case and is not the meeting's own business" in text


def test_site_checks_rpc_export_a_stale_record_exports_no_motion(tmp_path):
    from qa import site_checks as SC
    facts = facts_with_motions(tmp_path)
    site, rec = _export_site_dir(tmp_path, facts)       # written under the current rules: two motions
    rec.pop("motion_rules")
    text = "\n".join(SC.check_rpc_export(site, rec)[0])
    assert "rpc.json was not written under the reader's current motion rules" in text and "motion-1" in text


def test_the_committed_record_exports_only_what_its_pages_show(tmp_path):
    """The committed rpc.json in whichever state it is: before its rebuild (no `motion_rules`) no motion is exported;
    after, exactly the motions the pages show confirmed, and the reader's reasons never."""
    rx = rpc.load(rpc.load_config(config.SITE.get("rpc")), False)
    if rx is None:
        pytest.skip("no committed RPC facts")
    written = {p.name: p for p in RE.export_rpc(rx, tmp_path)}
    ms = rows(written["motions.csv"])
    shown = [mv for mv in rx.motions if mv["confirmed"]]
    assert {r["id"] for r in ms} == {mv["id"] for mv in shown} and len(ms) == len(shown)
    if rx.facts.get("motion_rules") != rpc.MOTION_RULES:
        assert ms == []
    assert len(rows(written["meetings.csv"])) == len(rx.facts["meetings"])
    assert len(rows(written["cases.csv"])) == len(rx.facts["cases"])
    assert len(rows(written["sources.csv"])) == len(rx.facts["sources"])
    held = sum(int(r["motions_not_confirmed"]) for r in rows(written["meetings.csv"]))
    assert held + len(ms) == len(rx.facts.get("motions", []))
    assert "reasons" not in written["facts.json"].read_text(encoding="utf-8")


def test_internal_export_keeps_every_motion_with_its_reasons_outside_the_site(tmp_path, rpx):
    site = tmp_path / "build" / "site"
    paths = RE.export_rpc(rpx, site, internal=True)
    idir = RE.internal_dir(rpx, site)
    assert idir == tmp_path / "build" / "internal-data" / "rpc" and not idir.is_relative_to(site)
    written = {p.name: p for p in paths if p.parent == idir}
    assert sorted(written) == sorted(["facts.json"] + [f"{n}.csv" for n in RE.RPC_FILES])
    # the site itself gets the public files only, the same as a public build
    public = {p.name: p for p in paths if p.parent == site / "data" / "rpc"}
    assert sorted(public) == sorted(written) and len(paths) == 2 * len(written)
    for name, p in public.items():
        assert p.read_bytes() == (RE.export_rpc(rpx, tmp_path / "pub")[0].parent / name).read_bytes(), name
    ms = {r["id"]: r for r in rows(written["motions.csv"])}
    assert len(ms) == 8
    assert ms[f"{MEETING}-motion-2"]["confirmed"] == "False" and ms[f"{MEETING}-motion-1"]["confirmed"] == "True"
    assert ms[f"{MEETING}-motion-2"]["reasons"] == "mover is not one member present"
    assert ms[f"{MEETING}-motion-4"]["confirmed"] == "False"       # the record's own doubt, as the pages


def test_a_public_export_removes_stale_files_it_did_not_write(tmp_path, rpx):
    """An earlier export's leftovers under data/rpc/ (an old internal export at the public names, a renamed file) are
    removed; files of other bodies are left alone. site_checks rpc-export fails a leftover the export did not write."""
    from qa import site_checks as SC
    site = tmp_path / "site"
    d = site / "data" / "rpc"
    (d / "old").mkdir(parents=True)
    (d / "motions.csv").write_text("id,confirmed,reasons\nx,False,mover is not one member present\n", encoding="utf-8")
    (d / "motions-internal.csv").write_text("leftover", encoding="utf-8")
    (d / "old" / "facts.json").write_text("{}", encoding="utf-8")
    (site / "data" / "facts.json").write_text("{}", encoding="utf-8")
    written = RE.export_rpc(rpx, site)
    assert sorted(p.relative_to(d).as_posix() for p in d.rglob("*")) == sorted(p.name for p in written)
    assert "reasons" not in (d / "motions.csv").read_text(encoding="utf-8")
    assert (site / "data" / "facts.json").read_text(encoding="utf-8") == "{}"
    rec = {**rpx.facts, "_cfg": rpc.load_config("cmc-rpc")}
    assert SC.check_rpc_export(site, rec)[0] == []
    (d / "motions-internal.csv").write_text("leftover", encoding="utf-8")
    assert SC.check_rpc_export(site, rec)[0] == [
        "data/rpc/motions-internal.csv: not a file the RPC export writes (a leftover; internal files never go in the "
        "site)"]


# ------------------------------------------------------------------ cases, meetings, sources
def test_cases_are_the_agendas_words_with_the_page_that_prints_them(files, rpx):
    cs = rows(files["cases.csv"])
    assert len(cs) == len(rpx.facts["cases"]) and len({r["id"] for r in cs}) == len(cs)
    src = {s["id"]: s for s in rpx.facts["sources"]}
    for r, c in zip(sorted(cs, key=lambda r: r["id"]), sorted(rpx.facts["cases"], key=lambda c: c["id"])):
        s = src[c["source_id"]]
        assert (r["id"], r["number_printed"], r["page"]) == (c["id"], c["number_printed"], str(c["page"]))
        assert (r["source_url"], r["source_sha256"], r["fetched_at"]) == (s["url"], s["sha256"], s["fetched_at"])
        assert r["applicant"].lstrip("'") == (c["applicant"] or "") and r["date"] == "2026-10-27"
    one = next(r for r in cs if r["id"] == CASE)
    assert one["number"] == "CZ-12-2026" and one["case_type"] == "County zoning" and one["meeting_id"] == MEETING


def test_meetings_name_the_listing_and_their_files(files, rpx):
    ms = rows(files["meetings.csv"])
    assert [r["id"] for r in ms] == [m["id"] for m in sorted(rpx.facts["meetings"], key=lambda m: (m["date"], m["id"]))]
    assert all(r["source_url"] == rpx.cfg["listing_url"] for r in ms)
    m = next(r for r in ms if r["id"] == MEETING)
    assert m["agenda_collected"] == "True" and m["agenda_source_sha256"] and m["agenda_fetched_at"]
    assert m["minutes_url"] == MINUTES and m["minutes_source_sha256"] == "0" * 64
    assert int(m["cases"]) == len(rpx.cases_by_meeting[MEETING]) > 0
    # a listed file the team did not fetch: its link as listed, no hash, no fetch date
    link_only = [r for r in ms if r["agenda_url"] and r["agenda_collected"] == "False"]
    assert link_only and all(not r["agenda_source_sha256"] and not r["agenda_fetched_at"] for r in link_only)
    data = json.loads(files["facts.json"].read_text(encoding="utf-8"))
    jm = next(x for x in data["meetings"] if x["id"] == MEETING)
    assert {d["kind"] for d in jm["documents"]} >= {"agenda"} and all("fetched" not in d for d in jm["documents"])


def test_a_fetched_file_not_read_as_the_meetings_own_is_still_collected(tmp_path):
    """`<kind>_collected`, hash and fetch date are the listed file's own (its source_id), as facts.json's documents and
    sources.csv say: a file the team holds but the reader did not take as this meeting's minutes (another date
    printed, as real 2025-04-11-executive) is collected, with `minutes_read_as_meeting` False."""
    facts = facts_with_motions(tmp_path)
    m = next(m for m in facts["meetings"] if m["id"] == "2025-07-29-regular")
    d = next(d for d in m["documents"] if d["kind"] == "minutes")
    d.update(fetched=True, source_id="src-unattached")
    facts["sources"].append({"id": "src-unattached", "url": d["url"], "sha256": "a" * 64, "kind": "minutes",
                             "meeting_date": "2025-07-29", "fetched_at": "2026-11-09", "pages": 4,
                             "text_layer": "text", "format": "pdf", "read_by": "text layer"})
    assert not m.get("minutes_source_id")
    written = {p.name: p for p in RE.export_rpc(load(tmp_path, facts), tmp_path / "out")}
    ms = {r["id"]: r for r in rows(written["meetings.csv"])}
    r = ms["2025-07-29-regular"]
    assert (r["minutes_url"], r["minutes_collected"], r["minutes_source_sha256"], r["minutes_fetched_at"]) == \
        (d["url"], "True", "a" * 64, "2026-11-09")
    assert r["minutes_read_as_meeting"] == "False"
    # the meeting's own files: collected and read as its own; a file listed but not fetched: neither
    own = ms[MEETING]
    assert (own["agenda_collected"], own["agenda_read_as_meeting"]) == ("True", "True")
    assert (own["minutes_collected"], own["minutes_read_as_meeting"]) == ("True", "True")
    assert (r["agenda_collected"], r["agenda_read_as_meeting"], r["agenda_source_sha256"]) == ("False", "False", "")
    # no file of that kind listed: empty
    assert ms["2026-01-27-regular"]["minutes_collected"] == ms["2026-01-27-regular"]["minutes_read_as_meeting"] == ""
    # every meeting row agrees with facts.json's documents and with sources.csv
    data = json.loads(written["facts.json"].read_text(encoding="utf-8"))
    hashes = {s["source_url"]: s["source_sha256"] for s in rows(written["sources.csv"])}
    for jm in data["meetings"]:
        for doc in jm["documents"]:
            if doc["kind"] in ("agenda", "minutes"):
                row = ms[jm["id"]]
                assert row[f"{doc['kind']}_collected"] == str(doc["collected"]), (jm["id"], doc["kind"])
                assert row[f"{doc['kind']}_source_sha256"] == (hashes[doc["url"]] if doc["collected"] else "")


def test_the_committed_record_meeting_rows_agree_with_their_documents(tmp_path):
    """The real rows the review found (2022-04-25-executive agenda, 2025-04-11-executive and 2025-10-27-cdrb minutes:
    fetched, not read as the meeting's own) say collected, with the hash sources.csv gives."""
    rx = rpc.load(rpc.load_config(config.SITE.get("rpc")), False)
    if rx is None:
        pytest.skip("no committed RPC facts")
    written = {p.name: p for p in RE.export_rpc(rx, tmp_path)}
    ms = {r["id"]: r for r in rows(written["meetings.csv"])}
    hashes = {s["source_url"]: s["source_sha256"] for s in rows(written["sources.csv"])}
    for m in rx.facts["meetings"]:
        for d in m["documents"]:
            if d["kind"] not in ("agenda", "minutes"):
                continue
            r = ms[m["id"]]
            assert r[f"{d['kind']}_collected"] == str(bool(d["fetched"])), (m["id"], d["kind"])
            assert r[f"{d['kind']}_source_sha256"] == (hashes[d["url"]] if d["fetched"] else ""), (m["id"], d["kind"])
            assert r[f"{d['kind']}_read_as_meeting"] == str(bool(m.get(f"{d['kind']}_source_id")))


def test_sources_list_every_collected_file(files, rpx):
    ss = rows(files["sources.csv"])
    assert {r["source_url"] for r in ss} == {s["url"] for s in rpx.facts["sources"]}
    assert all(len(r["source_sha256"]) >= 12 and r["fetched_at"] for r in ss)


def test_a_cell_that_starts_like_a_formula_is_text(tmp_path):
    facts = facts_with_motions(tmp_path)
    facts["cases"][0]["applicant"] = "=HYPERLINK(1)"
    facts["motions"] = [motion(1, kind="Motion to adjourn", moved_by="@Mover", outcome="+passed")]
    written = {p.name: p for p in RE.export_rpc(load(tmp_path, facts), tmp_path / "out")}
    assert any(r["applicant"] == "'=HYPERLINK(1)" for r in rows(written["cases.csv"]))
    r = rows(written["motions.csv"])[0]
    assert (r["moved_by"], r["outcome"]) == ("'@Mover", "'+passed")


# ------------------------------------------------------------------ provenance registry
def unregistered_keys(pub: dict) -> set[str]:
    missing: set[str] = set()

    def walk(path: str, v) -> None:
        if isinstance(v, list):
            for x in v:
                walk(path, x)
        elif isinstance(v, dict):
            for k, x in v.items():
                p = f"{path}.{k}"
                if f"rpc/facts.json:{p}" not in RE.RPC_PROVENANCE:
                    missing.add(p)
                walk(p, x)

    for top, v in pub.items():
        if isinstance(v, (list, dict)):
            walk(top, v)
        elif f"rpc/facts.json:{top}" not in RE.RPC_PROVENANCE:
            missing.add(top)
    return missing


def test_every_registry_value_is_stated_or_says_how_it_is_derived():
    for k, v in RE.RPC_PROVENANCE.items():
        assert v == "stated" or (v.startswith("derived: ") and len(v) > len("derived: ")), k
        if v != "stated":
            assert not k.rsplit(".", 1)[-1].startswith("stated_"), k


@pytest.mark.parametrize("internal", [False, True])
def test_every_column_and_key_is_registered(tmp_path, rpx, internal):
    paths = RE.export_rpc(rpx, tmp_path / "site", internal=internal)
    where = RE.internal_dir(rpx, tmp_path / "site") if internal else tmp_path / "site" / "data" / "rpc"
    written = {p.name: p for p in paths if p.parent == where}
    for name in RE.RPC_FILES:
        header = next(csv.reader(io.StringIO(written[f"{name}.csv"].read_text(encoding="utf-8"))))
        missing = [c for c in header if f"rpc/{name}.{c}" not in RE.RPC_PROVENANCE]
        assert not missing, f"rpc/{name}.csv columns not in RPC_PROVENANCE: {missing}"
        if name in ("cases", "motions"):
            assert header[-4:] == SRC_COLS
    assert unregistered_keys(json.loads(written["facts.json"].read_text(encoding="utf-8"))) == set()


def test_a_field_the_reader_adds_later_is_not_exported_unregistered(tmp_path):
    facts = facts_with_motions(tmp_path)
    for lst in ("meetings", "cases", "motions", "sources"):
        for r in facts[lst]:
            r["qq_new_field"] = "Qqnew"
    facts["qq_top"] = "Qqnew"
    facts["coverage"]["qq_later"] = "Qqnew"
    for d in facts["meetings"][0]["documents"]:
        d["qq_doc"] = "Qqnew"
    for p in RE.export_rpc(load(tmp_path, facts), tmp_path / "out"):
        assert "qq" not in p.read_text(encoding="utf-8").casefold(), p.name


# ------------------------------------------------------------------ export_site, the file count and the Data page
def test_export_site_writes_the_rpc_files_beside_the_others(tmp_path):
    county = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cfg = {**rpc.load_config("cmc-rpc"), "facts_path": tmp_path / "rpc.json"}
    (tmp_path / "rpc.json").write_text(json.dumps(facts_with_motions(tmp_path)), encoding="utf-8")
    written = export_site(county, tmp_path / "a", rpc=cfg)
    names = {p.relative_to(tmp_path / "a" / "data").as_posix() for p in written}
    assert {"facts.json", "rpc/facts.json", "rpc/meetings.csv", "rpc/cases.csv", "rpc/motions.csv",
            "rpc/sources.csv"} <= names
    assert len(names) == export_file_count(True, (), False, rpc=True)
    # a fixture county reads no real RPC facts; no RPC config, no RPC files
    for kw in ({}, {"rpc": None}):
        written = export_site(county, tmp_path / "b", **kw)
        assert not any(p.parent.name == "rpc" for p in written)
        assert len(written) == export_file_count(True, (), False)


def test_export_site_refuses_fixture_rpc_facts_beside_real_county_facts(tmp_path):
    (tmp_path / "rpc.json").write_text(json.dumps(facts_with_motions(tmp_path)), encoding="utf-8")
    cfg = {**rpc.load_config("cmc-rpc"), "facts_path": tmp_path / "rpc.json"}
    real = {k: v for k, v in json.loads(FIXTURE.read_text(encoding="utf-8")).items() if k != "fixture"}
    with pytest.raises(rpc.RpcError):
        export_site(real, tmp_path / "out", councils=(), rpc=cfg)


def test_export_site_exports_the_committed_rpc_by_default(tmp_path):
    if rpc.load(rpc.load_config(config.SITE.get("rpc")), False) is None:
        pytest.skip("no committed RPC facts")
    facts = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))
    written = export_site(facts, tmp_path, councils=())
    assert {"rpc/facts.json"} | {f"rpc/{n}.csv" for n in RE.RPC_FILES} <= \
        {p.relative_to(tmp_path / "data").as_posix() for p in written}


def test_data_page_lists_the_rpc_files(rpx):
    ctx = views.data_page(rpc=rpx)
    g = ctx["groups"][-1]
    assert g["heading"] == rpx.body
    assert [f["name"] for f in g["files"]] == ["rpc/facts.json"] + [f"rpc/{n}.csv" for n in RE.RPC_FILES]
    assert "only when it is confirmed" in g["note"]
    assert len(views.data_page()["groups"]) == 1 and ctx["files"] == ctx["groups"][0]["files"]


def test_the_built_data_page_links_every_exported_rpc_file(tmp_path):
    (tmp_path / "rpc.json").write_text(json.dumps(facts_with_motions(tmp_path)), encoding="utf-8")
    cfg = {**rpc.load_config("cmc-rpc"), "facts_path": tmp_path / "rpc.json"}
    out = tmp_path / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, rpc=cfg)
    export_site(json.loads(FIXTURE.read_text(encoding="utf-8")), out, rpc=cfg)
    html = (out / "data.html").read_text(encoding="utf-8")
    for n in ["facts.json"] + [f"{n}.csv" for n in RE.RPC_FILES]:
        assert f'href="data/rpc/{n}"' in html and (out / "data" / "rpc" / n).is_file(), n
    assert "A motion appears in these files only when it is confirmed" in html
    # the Data page names no person and never says "unanimous"
    assert "unanim" not in html.casefold() and "Fixture Mover" not in html
    # the closing copy is true of the RPC's rows: a meeting row cites its listing and files, a sources row is the file,
    # and a motion not confirmed is left out (not an empty cell with its check)
    body = rpc.load(cfg, True).body
    plain_text = " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())
    assert (f"In the {body}'s files, a meeting row names the listing page it was taken from and its agenda and "
            "minutes files, and a sources row is the fetched file itself.") in plain_text
    assert (f"A {body} motion that is not confirmed is not in its files at all; its meeting row counts it "
            "(motions_not_confirmed).") in plain_text
    plain = tmp_path / "plain" / "site"
    build(FIXTURE, plain, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, rpc=None)
    text = (plain / "data.html").read_text(encoding="utf-8")
    assert "data/rpc/" not in text and "meeting row names the listing page" not in text
    assert "is not in its files at all" not in text
