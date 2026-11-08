"""Review of efbf38f..345d497 (2026-11-08): combine counts dissent from every reading, the outcome word never crosses a
clause, a count printed blank is never published as stated, and a two-thirds table is checked against two-thirds."""
import csv
import io
import json

from collector import parse as P
from collector.tests.test_verified_rate import ROSTER4, _r, _rc


# ------------------------------------------------------------------ parse-accuracy/combine-ignores-unclean-dissent

def test_combine_holds_a_clean_vote_against_another_readings_conflicting_marks():
    # B: clean Yes in the text layer; tesseract read two marks there ("?", a row read out of line), not clean
    a = _r("text-layer", {"A": "Yes", "B": "Yes", "C": "No", "D": "---"}, absent=["D"], tally=(2, 1, 0))
    b = _r("tesseract", {"A": "Yes", "B": "?", "C": "No", "D": "---"}, absent=["D"], tally=(2, 1, 0),
           clean={"A": True, "B": False, "C": True, "D": True})
    c = P.combine([a, b], ROSTER4)
    assert c.votes["B"] == "?" and any("conflicting marks for B" in x for x in c.reasons)
    rc = _rc([a, b], roster=ROSTER4, outcome="Adopted")
    assert rc.status == "Unverified" and rc.combined is None


def test_combine_holds_a_clean_vote_against_an_unclean_absent_mark():
    # B: clean Yes in one reading, "---" with junk beside it (not clean) in the other: no vote is taken
    a = _r("text-layer", {"A": "Yes", "B": "Yes", "C": "No", "D": "---"}, absent=["D"], tally=(2, 1, 0))
    b = _r("tesseract", {"A": "Yes", "B": "---", "C": "No", "D": "---"}, absent=["D"], tally=(2, 1, 0),
           clean={"A": True, "B": False, "C": True, "D": True})
    c = P.combine([a, b], ROSTER4)
    assert c.votes["B"] == "?" and c.reasons
    assert _rc([a, b], roster=ROSTER4).status == "Unverified"


def test_combine_holds_a_blank_cell_against_another_readings_marks():
    # D: clean blank in one reading, "?" in the other: unreadable, not "no vote"
    a = _r("text-layer", {"A": "Yes", "B": "Yes", "C": "No", "D": "none"}, absent=["D"], tally=(2, 1, 0))
    b = _r("tesseract", {"A": "Yes", "B": "Yes", "C": "No", "D": "?"}, absent=["D"], tally=(2, 1, 0),
           clean={"A": True, "B": True, "C": True, "D": False})
    assert P.combine([a, b], ROSTER4).votes["D"] == "?"


def test_combine_still_fills_a_blank_cell_when_no_reading_dissents():
    a = _r("text-layer", {"A": "Yes", "B": "none", "C": "No", "D": "---"}, absent=["D"], tally=(2, 1, 0))
    b = _r("tesseract", {"A": "Yes", "B": "Yes", "C": "No", "D": "---"}, absent=["D"], tally=(2, 1, 0),
           clean={"A": True, "B": True, "C": True, "D": False})
    c = P.combine([a, b], ROSTER4)
    assert c.reasons == [] and c.votes["B"] == "Yes"


# ------------------------------------------------------------------ parse-accuracy/outcome-crosses-clause

def _word(ctx):
    found = list(P.OUTCOME_RE.finditer(ctx))
    return found[-1].group(1) if found else None


def test_outcome_comma_phrase_never_crosses_a_clause():
    # the reviewer's probes: the comma group must not carry "Approved" across "and the main motion"
    assert _word("The foregoing Motion to Amend was Approved, and the main motion, failed by the following roll "
                 "call vote:") == "failed"
    assert _word("The foregoing Motion to Amend was Approved, and the main motion, Failed by the following roll "
                 "call vote:") == "Failed"
    # any other comma phrase ends the match: no outcome is read rather than a wrong one
    assert _word("The Motion to Amend was Approved, and the Resolution, by the following roll call vote:") is None
    assert _word("was Approved, the vote being taken, by the following roll call vote:") is None


def test_outcome_comma_phrases_on_the_list_still_read():
    assert _word("The foregoing Resolution was Adopted, as Amended, by the following roll call vote:") == "Adopted"
    assert _word("The foregoing Resolution was Adopted, As  Amended, by the following roll call vote:") == "Adopted"
    assert _word("was Adopted, in its original state, by the following roll call vote:") == "Adopted"


# ------------------------------------------------------------------ neutrality/derived-count-shown-as-stated

def _table(tally_line, absent_line="ABSENT: Cy Charlie (1)"):
    return ["District Commissioner Vote", "1  Ann Alpha   Y", "2  Bob Bravo   N", "3  Cy Charlie  ---",
            tally_line, absent_line]


ROSTER3 = ["Ann Alpha", "Bob Bravo", "Cy Charlie"]


def _rd(lines):
    return P.read_table(lines, 0, len(lines), ROSTER3, "text-layer")[0]


def test_blank_count_is_derived_for_the_check_but_not_printed():
    r = _rd(_table("Yeses - 1 Noes - Abstentions - 0"))
    assert r.reasons == [] and r.tally == (1, 1, 0)
    assert P.printed_counts(r) == (1, None, 0)
    rc = _rc([r], roster=ROSTER3, outcome="Failed")
    assert rc.tally == (1, 1, 0) and rc.printed_tally == (1, None, 0)
    # a fully printed tally is printed as read
    r = _rd(_table("Yeses - 1 Noes - 1 Abstentions - 0"))
    assert P.printed_counts(r) == (1, 1, 0) == r.tally


def test_a_garbled_mark_in_a_count_is_not_a_printed_blank():
    for line in ("Yeses - 1 Noes - | Abstentions - 0", "Yeses - 1 Noes - ] Abstentions - 0",
                 "Yeses - 1 Noes - 1 Abstentions — |", "Yeses - 1 Noes - ! Abstentions - 0",
                 "Yeses - 1 Noes - |1 Abstentions - 0"):
        r = _rd(_table(line))
        assert r.tally is None and any("tally unreadable" in x for x in r.reasons), line
    # dashes and spaces only: printed blank, as before
    r = _rd(_table("Yeses—1 Noes—   Abstentions — 0"))
    assert r.tally == (1, 1, 0) and P.printed_counts(r) == (1, None, 0)
    # a stray quote or full stop before a printed number still reads (as before)
    assert _rd(_table("Yeses —. 1 Noes - 1 Abstentions —'0")).tally == (1, 1, 0)


def test_combine_publishes_a_count_only_when_a_reading_printed_it():
    a = _r("text-layer", {"A": "Yes", "B": "none", "C": "No", "D": "---"}, absent=["D"], tally=(2, 1, 0))
    a.printed = (2, 1, None)
    b = _r("tesseract", {"A": "Yes", "B": "Yes", "C": "No", "D": "---"}, absent=["D"], tally=(2, 1, 0),
           clean={"A": True, "B": True, "C": True, "D": False})
    b.printed = (2, None, None)
    c = P.combine([a, b], ROSTER4)
    assert c.reasons == [] and c.tally == (2, 1, 0) and c.printed == (2, 1, None)


def test_facts_and_export_carry_null_for_a_blank_count(tmp_path):
    """End to end on the real 2024-12-09 p9 table with its Noes count printed blank: the roll call verifies on the
    derived count, but facts.json and the export publish null for it (every consumer of stated_tally)."""
    from collector.export import export
    from collector.tests.test_meetings import ADJOURN, HEADER_DEC, RC_CLEAN, doc
    from collector.tests.test_one_vote import build
    blank = RC_CLEAN.replace("Noes   —   0 Abstentions", "Noes   —   Abstentions")
    assert blank != RC_CLEAN
    _, facts = build(doc(tmp_path, [HEADER_DEC + blank + ADJOURN]))
    (rc,) = facts["roll_calls"]
    assert rc["verification"]["status"] == "verified"
    assert rc["stated_tally"] == {"yes": 19, "no": None, "abstain": 0}
    _, plain = build(doc(tmp_path, [HEADER_DEC + RC_CLEAN + ADJOURN], sha="cd" * 32))
    assert plain["roll_calls"][0]["stated_tally"] == {"yes": 19, "no": 0, "abstain": 0}
    files = {f.name: f for f in export(facts, tmp_path / "site")}
    pub = json.loads(files["facts.json"].read_text())
    assert pub["roll_calls"][0]["stated_tally"] == {"yes": 19, "no": None, "abstain": 0}
    (row,) = csv.DictReader(io.StringIO(files["roll_calls.csv"].read_text()))
    assert (row["yes"], row["no"], row["abstain"]) == ("19", "", "0")


# ------------------------------------------------------------------ parse-accuracy/two-thirds-majority

def test_two_thirds_table_passes_only_when_every_base_agrees():
    # rc-b325a18d-p109-1: 15 Yes, 1 No, 1 Abstain, Approved: two-thirds of votes cast, of present, of the body
    assert P.check_outcome("Approved", (15, 1, 1), two_thirds=True) == []
    # 12-8 on a two-thirds table: under two-thirds of every base, so Approved disagrees and Failed agrees
    assert P.check_outcome("Approved", (12, 8, 0), two_thirds=True)
    assert P.check_outcome("Failed", (12, 8, 0), two_thirds=True) == []
    # 13-5-2 (20 present): 13/18 cast >= 2/3, 13/20 present < 2/3: the base decides, so it is held either way
    for word in ("Approved", "Failed"):
        rs = P.check_outcome(word, (13, 5, 2), two_thirds=True)
        assert rs and "do not say two-thirds of what" in rs[0]
    # a simple-majority table is unchanged
    assert P.check_outcome("Approved", (12, 8, 0)) == []


def test_two_thirds_heading_sets_the_flag():
    lines = ["The foregoing Motion was Approved by the following two-thirds (2/3) vote:",
             "District Commissioner Vote", "1  Ann Alpha   Y", "2  Bob Bravo   N", "3  Cy Charlie  ---",
             "Yeses - 1 Noes - 1 Abstentions - 0", "ABSENT: Cy Charlie (1)"]
    att = P.Attendance("2023-06-12", 1, ROSTER3[:2], ["Cy Charlie"], 2, 1, [], True, [])
    rcs = P.find_rollcalls(["\n".join(lines)], "t", att)
    assert rcs and rcs[0].two_thirds is True
    lines[0] = "The foregoing Motion was Approved by the following roll call vote:"
    assert P.find_rollcalls(["\n".join(lines)], "t", att)[0].two_thirds is False
