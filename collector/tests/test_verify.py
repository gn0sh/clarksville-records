"""Verifier checks, consent-list expansion, item numbers, G4 gate, and the hand-labelled set (AC-P3)."""
import json
import re
from pathlib import Path

import jsonschema
import pytest

from collector import parse as P
from collector import verify as V
from collector.compare_labels import compare
from collector.facts import norm_title, subject_of
from collector.minutes import consent_lists
from collector.names import NAMES, Resolver, load_roster
from collector.store import Store

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).parent / "fixtures"


def rollcall(rc_fixture, header):
    att = P.parse_attendance([(FIX / header).read_text()])
    pages = [(FIX / rc_fixture).read_text()]
    rcs = P.find_rollcalls(pages, "t", att, {})
    return rcs[0], att


def failed(ver):
    return {c["check"] for c in ver["checks"] if not c["ok"]}


# ------------------------------------------------------------------ roll call checks

def test_clean_roll_call_is_verified_with_every_named_check():
    rc, _ = rollcall("rc_dec2024_p9_clean.txt", "header_dec2024.txt")
    ver = V.roll_call_verification(rc, [])
    assert ver["status"] == "verified", ver
    names = {c["check"] for c in ver["checks"]}
    assert set(V.RC_CHECKS) <= names


def test_unresolved_roster_name_holds_the_roll_call():
    rc, _ = rollcall("rc_dec2024_p9_clean.txt", "header_dec2024.txt")
    ver = V.roll_call_verification(rc, ["Jolm Gannon"])
    assert ver["status"] == "unverified" and failed(ver) == {"names_resolve"}


def test_dropped_mark_fails_one_vote_per_member_and_tally():
    rc, _ = rollcall("rc_dec2024_p64_dropped.txt", "header_dec2024.txt")
    ver = V.roll_call_verification(rc, [])
    assert ver["status"] == "unverified"
    assert "one_vote_per_present_member" in failed(ver)


def test_source_error_needs_two_agreeing_readings():
    rc, _ = rollcall("rc_dec2024_p90_source_error.txt", "header_dec2024.txt")
    assert rc.status == "Unverified"
    assert not V.source_inconsistent(rc)                 # one reading: cannot tell OCR noise from a source error
    second = P.Reading("tesseract", dict(rc.readings[0].votes), rc.readings[0].tally, list(rc.readings[0].absent),
                       list(rc.readings[0].reasons))
    rc.readings.append(second)
    P.decide(rc)
    assert V.source_inconsistent(rc)


def test_reason_mapping_covers_parser_reasons():
    assert V.reason_check("[text-layer] counted (3, 15, 0) != stated (4, 15, 0)") == "tally_matches_stated"
    assert V.reason_check("[tesseract] listed absent but has vote Yes: X") == "one_vote_per_present_member"
    assert V.reason_check("sources disagree for X: a=Yes b=No") == "readings_agree"
    assert V.reason_check("outcome Adopted disagrees with tally (3, 18, 0)") == "outcome_consistent"
    assert V.reason_check("meeting attendance header not verified") == "roster_available"


def test_motion_checks():
    a = {"official_id": "a", "raw_name": "A"}
    b = {"official_id": "b", "raw_name": "B"}
    none = {"official_id": None, "raw_name": "Ailbert"}
    assert V.motion_verification(a, b, {"a", "b"}, True)["status"] == "verified"
    assert failed(V.motion_verification(none, b, {"a", "b"}, True)) == {"mover_resolves"}
    assert failed(V.motion_verification(a, a, {"a"}, True)) == {"mover_differs_from_seconder"}
    assert failed(V.motion_verification(a, b, {"a"}, True)) == {"seconder_present"}


# ------------------------------------------------------------------ motion type and consent agenda

def test_motion_to_table_keeps_its_wording_in_outcome_text():
    ctx = ("On Motion by Commissioner J. Smith, seconded by Commissioner Leverett, to Defer to the April 13, 2020 "
           "Formal Meeting. The foregoing Motion to Defer was Approved by the following roll call vote:")
    om = None
    for om in P.OUTCOME_RE.finditer(ctx):
        pass
    mot = list(P.MOTION_RE.finditer(ctx))[-1]
    text, clause = P.motion_clauses(ctx, mot, om)
    assert text.startswith("On Motion by Commissioner J. Smith")
    assert "Motion to Defer was Approved" in clause
    assert subject_of(clause) == "Motion to Defer"


def test_consent_list_lists_items_and_excludes_pulled():
    lines = (FIX / "consent_dec2024_p10.txt").read_text().splitlines()
    cls = consent_lists(lines, [10] * len(lines), [])
    assert len(cls) == 1
    cl = cls[0]
    assert cl.pulled == ["24-12-2"]
    nums = [e.number for e in cl.entries if e.number]
    assert nums == ["24-12-1", "24-12-3", "24-12-4", "24-12-5", "24-12-6", "24-12-7", "24-12-8", "24-12-10",
                    "24-12-11"]
    others = [e.title for e in cl.entries if not e.number]
    assert others == ["Commission Minutes November 12, 2024", "County Clerk’s Report", "Mayor Nominations"]
    assert "Consent Agenda" in cl.label


# ------------------------------------------------------------------ item numbers

@pytest.mark.parametrize("line,want", [
    ("24-12-1        Resolution", ("24-12-1", "24-12-1")),
    ("23_1O_1*       Resolution", ("23_1O_1", "23-10-1")),
    ("AB-4-2024", ("AB-4-2024", "AB-4-2024")),
    ("Case:AB -4-2024", ("AB -4-2024", "AB-4-2024")),
])
def test_item_numbers_normalise(line, want):
    assert P.item_number_in(line, {}) == want


def test_split_number_is_joined_only_when_on_the_agenda_else_unnumbered():
    assert P.item_number_in("20-3-1 1   Resolution", {"20-3-11": "t"}) == ("20-3-1 1", "20-3-11")
    assert P.item_number_in("20-3-1 1   Resolution", {"20-3-1": "t"}) is None        # ambiguous: never guessed
    assert not P.valid_number("2O-3")
    assert P.item_number_in("No. 123-4 of the code", {}) is None                   # matches no pattern


def test_title_normalisation_is_conservative():
    assert norm_title("  Resolution  to Name   the Room. ") == "resolution to name the room"
    assert norm_title("Resolution to Name the Room (Hybrid)") != norm_title("Resolution to Name the Room")


# ------------------------------------------------------------------ G4

def _facts(held_ids, meetings, unshown=()):
    """meetings: [(id, [official ids], n roll calls)]; ids in `unshown` get attendance under review."""
    rcs, mts, people = [], [], set()
    for mid, members, n_rc in meetings:
        people |= set(members)
        mts.append({"id": mid, "attendance_status": "extracted",
                    "verification": {"status": "unverified" if mid in unshown else "verified", "checks": []},
                    "attendance": [{"official_id": m, "raw_name": m.upper(), "status": "present"} for m in members]})
        for k in range(n_rc):
            rid = f"{mid}-{k}"
            rcs.append({"id": rid, "meeting_id": mid,
                        "verification": {"status": "unverified" if rid in held_ids else "verified",
                                         "checks": [{"check": "tally_matches_stated", "ok": rid not in held_ids}]}})
    return {"roll_calls": rcs, "meetings": mts, "officials": [{"id": p} for p in sorted(people)]}


def test_g4_passes_when_holds_are_shared_by_everyone_present():
    facts = _facts({"m1-0", "m1-1"}, [("m1", ["a", "b", "c"], 30), ("m2", ["a", "b", "c"], 30)])
    g = V.gates(facts, set())["g4"]
    assert g["pass"] and g["flagged"] == [] and g["status"] == "pass"
    assert {o: s["held"] for o, s in g["per_official"].items()} == {"a": 2, "b": 2, "c": 2}


def test_g4_flags_an_official_whose_meetings_are_held_far_more_than_peers():
    # c sits in m3 (10 of 30 held, with d only) and m4 (clean, with a and b): over c's meetings the peers' median
    # rate is 0, so c's 10/60 is more than 2 x max(0, floor)
    facts = _facts({f"m3-{k}" for k in range(10)},
                   [("m3", ["c", "d"], 30), ("m4", ["a", "b", "c"], 30), ("m5", ["a", "b"], 30)])
    g = V.gates(facts, set())["g4"]
    assert g["per_official"]["c"]["eligible"] == 60
    assert g["flagged"] == ["c"] and not g["pass"] and g["status"] == "fail"


def test_g4_ignores_officials_under_the_minimum_and_source_errors_only_leave_the_rate():
    g = V.gates(_facts({"m1-0", "m1-1", "m1-2"}, [("m1", ["a", "b"], 10)]), set())["g4"]
    assert g["pass"] and g["per_official"]["a"]["peer_median"] is None
    g = V.gates(_facts({"m1-0"}, [("m1", ["a", "b"], 60)]), {"m1-0"})["g4"]
    a = g["per_official"]["a"]
    assert a["held"] == 1 and a["held_source_error"] == 1 and a["rate"] == 0.0   # still counted as shown


def test_g4_never_places_a_person_by_name_and_unshown_meetings_are_unattributed():
    facts = _facts({"m1-0", "m2-0", "m2-1"}, [("m1", ["a", "b"], 5), ("m2", ["a", "b"], 5)], unshown={"m2"})
    g = V.gates(facts, set())["g4"]
    assert g["per_official"]["a"] == g["per_official"]["b"] | {}
    assert g["per_official"]["a"]["held"] == 1 and g["per_official"]["a"]["eligible"] == 5
    assert g["held_unattributed"] == 2 and g["eligible_unattributed"] == 5 and g["held_total"] == 3
    for m in facts["meetings"]:                  # rewriting every raw name changes nothing
        for x in m["attendance"]:
            x["raw_name"] = "garbled"
    assert V.gates(facts, set())["g4"]["per_official"] == g["per_official"]


def test_g4_official_with_no_shown_meeting_has_no_rate():
    facts = _facts({"m1-0"}, [("m1", ["a"], 5), ("m2", ["z"], 5)], unshown={"m2"})
    g = V.gates(facts, set())["g4"]
    assert g["per_official"]["z"] == {"eligible": 0, "held": 0, "held_source_error": 0, "rate": None,
                                      "peer_median": None}


def test_g4_review_needed_when_the_uniform_share_is_large():
    facts = _facts({"m1-0", "m2-0", "m2-1"}, [("m1", ["a", "b"], 10), ("m2", ["a", "b"], 10)], unshown={"m2"})
    g = V.gates(facts, set())["g4"]
    assert g["uniform_share"] == round(2 / 3, 4) and g["review_needed"] and g["status"] == "review needed"
    assert g["pass"]                             # not a hard fail
    assert g["meetings_attendance_not_shown"] == [
        {"meeting_id": "m2", "attendance": "under_review", "held_roll_calls": ["m2-0", "m2-1"]}]
    g = V.gates(_facts({"m1-0"}, [("m1", ["a"], 10)]), set())["g4"]
    assert g["uniform_share"] == 0.0 and g["status"] == "pass"


def test_held_total_equals_unverified_count_on_committed_facts():
    facts = json.loads((ROOT / "data" / "facts.json").read_text())
    g = V.gates(facts, set())
    unverified = sum(r["verification"]["status"] != "verified" for r in facts["roll_calls"])
    assert g["g4"]["held_total"] == g["held_back"] == unverified


def test_verified_rate_gate():
    g = V.gates(_facts({"m1-0"}, [("m1", ["a"], 10)]), set())
    assert g["verified_rate"] == 0.9 and g["verified_rate_gate"]["pass"]
    g = V.gates(_facts({"m1-0", "m1-1"}, [("m1", ["a"], 10)]), set())
    assert not g["verified_rate_gate"]["pass"]


# ------------------------------------------------------------------ committed facts

def test_committed_facts_validate_against_the_schema():
    facts = json.loads((ROOT / "data" / "facts.json").read_text())
    jsonschema.validate(facts, json.loads((ROOT / "schema" / "facts.schema.json").read_text()))
    for key in ("sources", "officials", "meetings", "items", "item_events", "motions", "roll_calls"):
        ids = [x["id"] for x in facts[key]]
        assert ids == sorted(ids) and len(ids) == len(set(ids)), key


def test_hand_labelled_set_gives_zero_wrong_votes():
    facts = json.loads((ROOT / "data" / "facts.json").read_text())
    labels = json.loads((ROOT / "collector" / "hand_labels.json").read_text())
    res = compare(facts, labels, Store(), Resolver(load_roster(NAMES)))
    assert res["labelled"] >= 15 and not res["missing"]
    assert res["wrong"] == []
    assert res["verified"] >= 15


def test_every_consent_roll_call_reaches_the_items_it_covered():
    facts = json.loads((ROOT / "data" / "facts.json").read_text())
    items = {i["id"]: i for i in facts["items"]}
    consent = [r for r in facts["roll_calls"] if items[r["item_id"]]["title"] == "Consent Agenda"]
    assert consent
    expanded = 0
    for r in consent:
        covered = [e for e in facts["item_events"] if e["type"] == "roll_call" and e["ref"] == r["id"]
                   and e["item_id"] != r["item_id"]]
        expanded += bool(covered)
        assert all(re.search(r"Consent\W{0,3}Agenda", e["label"]) for e in covered)
    # a list whose heading OCRs as garbage is not expanded (listed in build/report.json), never guessed
    assert expanded >= 0.8 * len(consent)


def test_site_held_numbers_equal_the_g4_report():
    """Cross-module (Invariant: held-back counts): the site's per-official N equals g4.per_official[id].held and its
    uniform U equals g4.held_unattributed, on the real facts and on the fixture."""
    from sitegen import views
    for path in (ROOT / "data" / "facts.json", ROOT / "site" / "fixtures" / "facts.sample.json"):
        facts = json.loads(path.read_text())
        g = V.gates(facts, set())["g4"]
        held, uniform = views.held_counts(views.Index(facts))
        assert uniform == g["held_unattributed"], path
        for o in facts["officials"]:
            assert held.get(o["id"], 0) == g["per_official"][o["id"]]["held"], (path, o["id"])
