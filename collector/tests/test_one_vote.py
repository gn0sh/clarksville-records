"""Architecture "Invariant: one vote, one roll call" (problem family item-history, second hit).

Keys: item-history/consent-reprint-duplicates, item-history/reprint-double-event. Built from the real text layer of
the October 12, 2020 minutes (pp1, 47-52: the consent vote printed after resolutions 20-10-1, -2 and -3, with
"20-1 0-10" and "20-10-1 1" garbled) and the January 10, 2022 minutes (pp1, 12, 72: "22l-6" garbled). No network.
"""
import json
import random
import re
from pathlib import Path

import pytest

from collector import verify as V
from collector.facts import Builder, consent_groups
from collector.invariants import consent_item_ids, one_vote_violations
from collector.meetings import choose
from collector.minutes import agenda_numbers_in, number_line
from collector.names import NAMES, Resolver, load_roster
from collector.tests.test_meetings import HEADER_DEC, RC_CLEAN, ADJOURN, doc

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]
OCT = [(FIX / "header_oct2020.txt").read_text()] + [(FIX / f"oct2020_p{p}.txt").read_text() for p in range(47, 53)]
FEB = [(FIX / n).read_text() for n in ("header_feb2021.txt", "feb2021_p2.txt", "feb2021_p3.txt", "feb2021_p59.txt",
                                     "feb2021_p65.txt")]
JAN = [(FIX / n).read_text() for n in ("header_jan2022.txt", "consent_jan2022_p12.txt", "consent_jan2022_p72.txt")]
OCT_ITEMS = [f"20-10-{n}" for n in range(1, 14)]


def build(d):
    b = Builder(Resolver(load_roster(NAMES)), [])
    chosen, _, _ = choose([d])
    for pm in chosen:
        b.add(pm)
    return b, b.facts(load_roster(NAMES))


def failed(x):
    return {c["check"] for c in x["verification"]["checks"] if not c["ok"]}


def consent_rcs(facts):
    ids = consent_item_ids(facts)
    return [r for r in facts["roll_calls"] if r["item_id"] in ids]


def rc_events(facts, item):
    return [e for e in facts["item_events"] if e["item_id"] == item and e["type"] == "roll_call"]


# ------------------------------------------------------------------ the real October 2020 printings

def test_list_numbers_reads_ocr_split_numbers_inside_a_comma_list():
    assert number_line(" Resolutions 20-10-1, 20-10-2,") == ["20-10-1", "20-10-2"]
    assert number_line("  20-10-9, 20-1 0-10,") == ["20-10-9", "20-10-10"]
    assert number_line("20-10-1 1, 20-10-12") == ["20-10-11", "20-10-12"]
    assert number_line("22-1-4, 22-1-5, 22l-6") == ["22-1-4", "22-1-5"]   # "22l-6" is no number: never guessed
    assert number_line("Clerk's Report") is None and number_line("January 11,2021 Commission Minutes") is None


def test_oct2020_three_printings_are_one_roll_call(tmp_path):
    b, facts = build(doc(tmp_path, OCT, label="October 2020 Minutes"))
    (rc,) = consent_rcs(facts)
    assert rc["page"] == 3                                   # the first printing (minutes p48)
    assert len(b.consent_reprints) == 2 and set(b.consent_reprints.values()) == {rc["id"]}
    assert "reprints_agree" not in failed(rc)
    assert {"yes": 20, "no": 0, "abstain": 0} == rc["stated_tally"]
    assert V.gates(facts, set())["roll_calls"] == len(facts["roll_calls"])
    assert not one_vote_violations(facts)


def test_oct2020_every_listed_item_gets_the_vote_once(tmp_path):
    _, facts = build(doc(tmp_path, OCT, label="October 2020 Minutes"))
    (rc,) = consent_rcs(facts)
    for item in OCT_ITEMS:                                   # 20-10-10 and 20-10-11 are garbled in some printings
        evs = rc_events(facts, item)
        assert [e["ref"] for e in evs] == [rc["id"]], item
    assert len(rc_events(facts, rc["item_id"])) == 1         # the Consent Agenda item: one event, not one per printing


def test_oct2020_a_printing_that_reads_differently_holds_the_one_vote(tmp_path):
    pages = list(OCT)
    pages[4] = re.sub(r"(Rickey Ray\s+)Y", r"\1N", pages[4])                                    # p50
    _, facts = build(doc(tmp_path, pages, label="October 2020 Minutes"))
    (rc,) = consent_rcs(facts)                               # held, never split into two votes
    assert "reprints_agree" in failed(rc) and "Rickey Ray" in str(rc["verification"]["checks"])


def test_oct2020_a_printing_with_another_tally_holds_the_one_vote(tmp_path):
    pages = list(OCT)
    pages[6] = pages[6].replace("Yeses    —   20", "Yeses    —   19")                          # p52
    _, facts = build(doc(tmp_path, pages, label="October 2020 Minutes"))
    (rc,) = consent_rcs(facts)
    assert "reprints_agree" in failed(rc)


def test_oct2020_a_consent_vote_moved_by_someone_else_is_another_vote(tmp_path):
    pages = list(OCT)
    pages[6] = pages[6].replace("seconded by Commissioner~Ailbert", "seconded by Commissioner Creek")
    pages[6] = pages[6].replace("On Motion to Adopt by Commissioner Prichard", "On Motion to Adopt by Commissioner Rasnic")
    _, facts = build(doc(tmp_path, pages, label="October 2020 Minutes"))
    assert len(consent_rcs(facts)) == 2


def test_an_unread_motion_that_fits_two_votes_is_held_not_merged(tmp_path):
    pages = list(OCT)
    pages[4] = pages[4].replace("Commissioner Prichard, seconded by Commissioner Ailbert",
                                "Commissioner Rasnic, seconded by Commissioner Creek")                   # p50
    pages[6] = pages[6].replace("On Motion to Adopt", "On M0tion t0 Adopt")                            # p52 unread
    _, facts = build(doc(tmp_path, pages, label="October 2020 Minutes"))
    rcs = consent_rcs(facts)
    assert len(rcs) == 3
    (odd,) = [r for r in rcs if "consent_printing_placed" in failed(r)]
    assert odd["page"] == 7 and odd["verification"]["status"] == "unverified"


# ------------------------------------------------------------------ a 2022 case

def test_jan2022_printing_with_a_garbled_number_is_the_same_vote(tmp_path):
    b, facts = build(doc(tmp_path, JAN, sha="cd" * 32, label="January 2022 Minutes"))
    (rc,) = consent_rcs(facts)
    assert rc["page"] == 2 and "reprints_agree" not in failed(rc)    # (its text layer misses 3 marks; OCR reads them)
    assert list(b.consent_reprints.values()) == [rc["id"]]
    for n in range(1, 9):
        assert [e["ref"] for e in rc_events(facts, f"22-1-{n}")] == [rc["id"]]
    assert not one_vote_violations(facts)


# ------------------------------------------------------------------ property: random printings of one vote

GARBLE = [("20-10-6", "20-1 0-6"), ("20-10-8", "2O-10-8"), ("20-10-13", "20-l0-13"), ("Ailbert", "Allbert"),
          ("Allbert", "Alibert"), ("On Motion to Adopt", "On Moti0n to Adopt"), ("20-10-12", "20-10-l2")]


@pytest.mark.parametrize("seed", range(8))
def test_any_set_of_garbled_printings_is_one_verified_vote_at_most(tmp_path, seed):
    """However the printings are ordered and garbled (numbers, name spellings, an unread motion), a meeting never
    has two verified consent roll calls with the same per-member votes and the same mover and seconder, no item gets
    the vote twice, and no official has two vote rows in one roll call."""
    rnd = random.Random(seed)
    prints = [OCT[2], OCT[4], OCT[6]]                      # pp48, 50, 52
    resolutions = [OCT[1], OCT[3], OCT[5]]
    body = []
    for _ in range(rnd.randint(2, 6)):
        p = rnd.choice(prints)
        for a, z in rnd.sample(GARBLE, rnd.randint(0, 3)):
            p = p.replace(a, z)
        body += [rnd.choice(resolutions), p]
    _, facts = build(doc(tmp_path, [OCT[0]] + body, sha=f"{seed:02d}" * 32, label="October 2020 Minutes"))
    assert not one_vote_violations(facts)
    rcs = consent_rcs(facts)
    assert sum(r["verification"]["status"] == "verified" for r in rcs) <= 1
    assert len(rcs) - sum("consent_printing_placed" in failed(r) for r in rcs) == 1


def test_consent_groups_never_join_two_named_votes_through_an_unread_one():
    from types import SimpleNamespace as NS
    rc = lambda mv, sc, st="Verified": NS(kind="consent", mover=mv, seconder=sc, status=st, context_reasons=[])
    rcs = [rc("A", "B"), rc(None, None), rc("C", "D"), rc("A", None), rc("A", "B", "Unverified")]
    reprints, unplaced = consent_groups(rcs)
    assert reprints == {3: 0, 4: 0} and unplaced == {1}


# ------------------------------------------------------------------ the committed real data

def test_committed_facts_hold_the_invariant():
    facts = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))
    assert one_vote_violations(facts) == []


# ------------------------------------------------------------------ items/consent-ocr-number (QA)

def test_garbled_consent_numbers_match_only_agenda_numbers():
    agenda = {"21-2-4": "", "21-2-5": "", "21-2-6": ""}
    assert agenda_numbers_in("2 l-2-5j 21-2-6", agenda) == ["21-2-5", "21-2-6"]
    assert agenda_numbers_in("2 l-2-7j", agenda) == []                     # not on the agenda: never guessed
    assert agenda_numbers_in("21-2-54 2 1-2-6", agenda) == []              # digits touch both: ambiguous
    assert number_line("Resolutions 21-2-1, 21-2-2, 2 l-2-5j 21-2-6", agenda) == ["21-2-1", "21-2-2", "21-2-5",
                                                                                 "21-2-6"]


def test_feb2021_consent_vote_reaches_21_2_5_and_not_the_pulled_21_2_6(tmp_path):
    """Real pp1-3, 59, 65 of the February 8, 2021 minutes: p59's heading has a stray "I" at the margin, p65 prints
    "2 l-2-5j 21-2-6", both print "Resolution 2 1-2-6 was pulled from the Consent Agenda"."""
    _, facts = build(doc(tmp_path, FEB, sha="fe" * 32, label="February 2021 Minutes"))
    (rc,) = consent_rcs(facts)
    assert rc["page"] == 4
    for item in ("21-2-1", "21-2-2", "21-2-5"):
        assert [e["ref"] for e in rc_events(facts, item)] == [rc["id"]], item
    assert rc_events(facts, "21-2-6") == []                                # pulled: voted on at a later date
    assert not one_vote_violations(facts)


# ------------------------------------------------------------------ items/unnumbered-resolution (QA)

def test_case_numbers_in_a_resolution_heading_are_read():
    from collector import parse as P
    assert P.item_number_in(" CZ-l1-2022", {}) == ("CZ-l1-2022", "CZ-11-2022")          # 2022-06-13 p14
    assert P.item_number_in("AB-7-2 023", {}) == ("AB-7-2 023", "AB-7-2023")            # 2023-11-13 p33
    assert P.item_number_in("AB-4-2024", {}) == ("AB-4-2024", "AB-4-2024")


def test_a_vote_under_a_garbled_case_number_heading_is_filed_under_that_case(tmp_path):
    pages = [HEADER_DEC + "AB-7-2 023\n\n" + RC_CLEAN + ADJOURN]
    _, facts = build(doc(tmp_path, pages, sha="ca" * 32))
    (rc,) = facts["roll_calls"]
    assert rc["item_id"] == "AB-7-2023"


# ------------------------------------------------------------------ items/title-is-motion (QA)

def test_motion_and_outcome_sentences_are_never_item_titles():
    from collector.facts import is_sentence
    assert is_sentence("Motion by Commissioner Harper, seconded by Commissioner Woodruff,")
    assert is_sentence("On Motion by Commissioner Beal, seconded by Commissioner Gannon, the Rules were Suspended")
    assert is_sentence("The Motion was Approved by the following roll call vote:")
    assert not is_sentence("Resolution Approving a Motion Picture Grant")
    assert not is_sentence("County Clerk's Report")
    b = Builder(Resolver(load_roster(NAMES)), [])
    iid = b.item_for("CZ-2-2023", "Motion by Commissioner Harper, seconded by Commissioner Woodruff,",
                     ("2023-02-13", 5, 0), "x")
    assert b.items[iid]["title"] == "CZ-2-2023"
    b.item_for("CZ-2-2023", "Rezone 4 acres on Rossview Road", ("2023-03-13", 2, 0), "y")
    assert b.items[iid]["title"] == "Rezone 4 acres on Rossview Road"     # a later real title replaces the number
    b.item_for("CZ-2-2023", None, ("2023-01-09", 2, 0), "z")              # an earlier bare number keeps it
    assert b.items[iid]["title"] == "Rezone 4 acres on Rossview Road"
    a = b.item_for(None, "Motion by Commissioner Gannon, seconded by Commissioner Ray,", ("2024-09-09", 6, 0), "s1")
    c = b.item_for(None, "Motion by Commissioner Gannon, seconded by Commissioner Ray,", ("2024-10-14", 6, 0), "s2")
    assert a != c and b.items[a]["title"] == "(untitled)"                   # never title-linked by a motion sentence


def test_a_numbered_vote_without_an_agenda_title_is_titled_by_its_number(tmp_path):
    pages = [HEADER_DEC + "CZ-2-2023\n\n" + RC_CLEAN.replace("Motion to Adopt by", "Motion by") + ADJOURN]
    _, facts = build(doc(tmp_path, pages, sha="cb" * 32))
    (rc,) = facts["roll_calls"]
    assert rc["item_id"] == "CZ-2-2023"
    assert next(i for i in facts["items"] if i["id"] == "CZ-2-2023")["title"] == "CZ-2-2023"


def test_feb2026_amendment_and_resolution_as_amended_are_two_roll_calls():
    """February 9, 2026 p138 (item 26-2-6) prints two tables: the amendment's vote and the vote on the resolution as
    amended. Both are real roll calls, not one table read twice; the stated outcome clause tells them apart."""
    facts = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))
    a, b = (next(r for r in facts["roll_calls"] if r["id"] == f"rc-90320418-p138-{n}") for n in (0, 1))
    assert a["item_id"] == b["item_id"] == "26-2-6"
    assert "The foregoing Amendment was Adopted" in a["outcome_text"]
    assert b["outcome_text"].startswith("The foregoing Resolution, As Amended, was Adopted")
