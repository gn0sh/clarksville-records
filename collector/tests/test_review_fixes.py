"""Tests for the code-review findings on the M1 collector (problem keys in each test's docstring). No network."""
import copy
from pathlib import Path

from collector import parse as P
from collector import verify as V
from collector.facts import Builder
from collector.meetings import choose
from collector.names import NAMES, Resolver, load_roster
from collector.tests.test_meetings import ADJOURN, HEADER_DEC, RC_CLEAN, doc

TABLE = RC_CLEAN[RC_CLEAN.index("District"):]
MOTION = ("       On Motion to Adopt by Commissioner J. Smith, seconded by Commissioner Woodruff, the\n\n")


def build(d, resolver=None):
    b = Builder(resolver or Resolver(load_roster(NAMES)), [])
    chosen, _, _ = choose([d])
    for pm in chosen:
        b.add(pm)
    return b, b.facts(load_roster(NAMES))


def failed(x):
    return {c["check"] for c in x["verification"]["checks"] if not c["ok"]}


# ------------------------------------------------------------------ attribution/motion-ignores-context

def test_motion_linked_only_when_its_sentence_leads_into_the_outcome():
    ctx = ("On Motion to Adopt by Commissioner Creek, seconded by Commissioner Woodruff, the foregoing Resolution "
           "was Adopted by the following roll call vote:")
    om = list(P.OUTCOME_RE.finditer(ctx))[-1]
    assert P.motion_linked(ctx, list(P.MOTION_RE.finditer(ctx))[-1], om)
    voice = ("On Motion by Commissioner Creek, seconded by Commissioner Woodruff, the Minutes were Approved by voice "
             "vote. The Rules were Suspended by the following roll call vote:")
    om = list(P.OUTCOME_RE.finditer(voice))[-1]
    assert not P.motion_linked(voice, list(P.MOTION_RE.finditer(voice))[-1], om)


def test_voice_vote_motion_is_not_filed_as_this_votes_motion(tmp_path):
    page = (HEADER_DEC + "\n       On Motion by Commissioner Creek, seconded by Commissioner Woodruff, the Minutes were\n"
            "Approved by voice vote. The Rules were Suspended by the following roll call vote:\n\n" + TABLE + ADJOURN)
    _, facts = build(doc(tmp_path, [page]))
    (mo,) = facts["motions"]
    assert "motion_precedes_vote" in failed(mo)
    assert facts["roll_calls"][0]["verification"]["status"] == "verified"     # the vote itself is fine


def test_motion_held_when_attendance_is_held_and_rule_3_off_with_an_unresolved_header_name(tmp_path):
    header = HEADER_DEC.replace("Joe Smith\n", "Joe Smyth\n")           # an unresolved header name ("Smyth")
    _, facts = build(doc(tmp_path, [header + RC_CLEAN + ADJOURN]))
    (mo,) = facts["motions"]
    assert {"attendance_verified", "mover_resolves"} <= failed(mo)
    assert mo["moved_by"]["official_id"] is None                       # "J. Smith" not placed by surname
    clean = build(doc(tmp_path, [HEADER_DEC + RC_CLEAN + ADJOURN], sha="cd" * 32))[1]["motions"][0]
    assert clean["moved_by"]["official_id"] == "joe-smith" and clean["verification"]["status"] == "verified"


def test_motion_in_uncertain_minutes_is_held(tmp_path):
    nested = (Path(__file__).parent / "fixtures" / "embedded_nov2024_p54.txt").read_text()   # adjournment not read
    _, facts = build(doc(tmp_path, [HEADER_DEC, nested, RC_CLEAN + ADJOURN]))
    mo = next(m for m in facts["motions"] if m["meeting_id"] == "2024-11-12-formal")
    assert "in_meeting_record" in failed(mo)


# ------------------------------------------------------------------ item-history/consent-reprint-duplicates

def consent_print(heading: str | None, table: str = TABLE) -> str:
    head = f"                                                     {heading}\n\n RESOLUTION TEXT\n\n" if heading else ""
    return (head + " Consent Agenda\n      24-12-1, 24-12-2\n\n" + MOTION +
            " foregoing Consent Agenda items were Adopted and Approved by the following roll call vote:\n\n" + table)


def test_reprinted_consent_vote_is_one_roll_call_with_one_event_per_printing(tmp_path):
    pages = [HEADER_DEC + consent_print(None), consent_print("24-12-1"), consent_print("24-12-2") + ADJOURN]
    b, facts = build(doc(tmp_path, pages))
    (rc,) = facts["roll_calls"]
    assert rc["page"] == 1 and "reprints_agree" not in failed(rc)
    assert set(b.consent_reprints) == {f"rc-{'ab' * 4}-p2-0", f"rc-{'ab' * 4}-p3-0"}
    for item in ("24-12-1", "24-12-2"):
        evs = [e for e in facts["item_events"] if e["item_id"] == item and e["type"] == "roll_call"]
        assert all(e["ref"] == rc["id"] for e in evs)
        assert len(evs) == 2                     # the list on p1, and the printing after its own resolution
    g = V.gates(facts, set())
    assert g["roll_calls"] == 1 and g["held_back"] == 0


def test_a_reprint_that_reads_differently_holds_the_one_roll_call(tmp_path):
    bad = TABLE.replace("Joe Smith             Y", "Joe Smith             N")
    pages = [HEADER_DEC + consent_print(None), consent_print("24-12-1", bad) + ADJOURN]
    _, facts = build(doc(tmp_path, pages))
    (rc,) = facts["roll_calls"]
    assert "reprints_agree" in failed(rc)


# ------------------------------------------------------------------ item-history/consent-pulled

def test_item_with_its_own_roll_call_never_gets_the_consent_vote(tmp_path):
    pages = [HEADER_DEC + consent_print(None),
             "                                                     24-12-1\n\n RESOLUTION TEXT\n\n" + RC_CLEAN + ADJOURN]
    _, facts = build(doc(tmp_path, pages))
    consent = next(r for r in facts["roll_calls"] if r["page"] == 1)
    own = next(r for r in facts["roll_calls"] if r["page"] == 2)
    assert own["item_id"] == "24-12-1"
    refs = {e["ref"] for e in facts["item_events"] if e["item_id"] == "24-12-1" and e["type"] == "roll_call"}
    assert refs == {own["id"]} and consent["id"] not in refs


# ------------------------------------------------------------------ attribution/item-link-unchecked

def test_item_number_links_only_from_the_agenda_or_the_resolutions_own_heading():
    assert P.item_link_ok("                         22-7-2", ("22-7-2", "22-7-2"), {})
    assert P.item_link_ok("AB-5-2024        A Resolution Approving", ("AB-5-2024", "AB-5-2024"), {})
    assert P.item_link_ok("as amended by Resolution 22-3-4 in March", ("22-3-4", "22-3-4"), {"22-3-4": "t"})
    assert not P.item_link_ok("as amended by Resolution 22-3-4 in March", ("22-3-4", "22-3-4"), {})


# ------------------------------------------------------------------ attribution/name-pairing-no-margin

def test_a_cell_that_ties_two_roster_names_is_not_paired():
    cells = [P.Cell("R. Allbert", None, 0.0)]
    P.assign_names(cells, ["Randy Allbert", "Jerry Allbert", "Joe Smith"])
    assert cells[0].member is None
    cells = [P.Cell("Randy Ailbert", None, 0.0), P.Cell("R. Allbert", None, 0.0)]
    P.assign_names(cells, ["Randy Allbert", "Jerry Allbert"])
    assert cells[0].member == "Randy Allbert"
    assert cells[1].member is None or cells[1].member == "Jerry Allbert"   # only by elimination, never a tie


# ------------------------------------------------------------------ attribution/one-entry-per-official

def test_two_table_entries_for_one_official_hold_the_roll_call(tmp_path):
    roster = copy.deepcopy(load_roster(NAMES))
    roster = [o for o in roster if o["id"] != "joe-creek"]
    next(o for o in roster if o["id"] == "tangi-smith")["aliases"].append({"alias": "Joe Creek"})
    _, facts = build(doc(tmp_path, [HEADER_DEC + RC_CLEAN + ADJOURN]), Resolver(roster))
    (rc,) = facts["roll_calls"]
    assert "one_entry_per_official" in failed(rc)


# ------------------------------------------------------------------ nit: held count cross-check

def test_held_count_cross_check_catches_a_status_that_disagrees_with_its_checks(tmp_path):
    _, facts = build(doc(tmp_path, [HEADER_DEC + RC_CLEAN + ADJOURN]))
    facts["roll_calls"][0]["verification"]["checks"][0]["ok"] = False      # status still says verified
    try:
        V.gates(facts, set())
    except V.HeldCountError:
        return
    raise AssertionError("a status that disagrees with its checks must fail the cross-check")
