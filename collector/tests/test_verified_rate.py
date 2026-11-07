"""Parse-accuracy fixes that raise the verified rate without loosening a check (problem key
parse-accuracy/verified-rate). Each fix either reads a page more correctly or adds an agreeing reading."""
from pathlib import Path

from collector import parse as P

FIX = Path(__file__).parent / "fixtures"

# the 2022-08-08 minutes header (p1): 18 present, 3 absent
ROSTER_AUG2022 = ["Jerry Ailbert", "David Harper", "Rickey Ray", "Randy Ailbert", "Garland Johnson", "Larry Rocconi",
                  "Joshua Beal", "Charles Keene", "Robert Sigler", "Loretta J. Bryant", "Rashidah A. Leverett",
                  "Walker R. Woodruff", "Brandon Bulls", "James R. Lewis", "Carmelle Chandler", "Lisa L. Prichard",
                  "Joe L. Creek", "Chris Rasnic", "John M. Gannon", "Joe Smith", "Tangi C. Smith"]


def reading(fixture: str, source: str, roster=ROSTER_AUG2022) -> P.Reading:
    lines = (FIX / fixture).read_text().splitlines()
    r, _ = P.read_table(lines, P.table_heads(lines)[0], len(lines), roster, source)
    return r


def _rc(readings, roster=ROSTER_AUG2022, outcome="Adopted"):
    rc = P.RollCall(source="t", meeting_date=None, page=1, end_page=1, line=0, item=None, item_title=None,
                    kind="resolution", outcome_text=outcome, motion=None, mover=None, seconder=None,
                    votes={}, tally=None, absent=[])
    rc.roster = list(roster)
    rc.readings = readings
    P.decide(rc)
    return rc


# ------------------------------------------------------------------ combined reading

def test_combined_reading_aug2022_p24():
    """Text layer drops the third column's marks; tesseract reads the absent "---" of Gannon as "ue". Neither
    reading passes alone. Cell by cell they agree, and the result (hand-checked against the page image: 18 Y,
    Gannon, J. Smith, T. Smith absent) passes every P2 check."""
    t = reading("rc_aug2022_p24_textlayer.txt", "text-layer")
    o = reading("ocr_aug2022_p24.txt", "tesseract")
    assert any("no vote read for present member: Chris Rasnic" in x for x in t.reasons)
    assert any("unrecognised token" in x and "John M. Gannon" in x for x in o.reasons)
    assert t.clean["Chris Rasnic"] is True                  # a blank cell is clean (nothing read), not junk
    assert o.clean["John M. Gannon"] is False
    rc = _rc([t, o])
    assert rc.status == "Verified", rc.reasons
    assert rc.verified_by == "text-layer+tesseract"
    assert rc.tally == (18, 0, 0)
    assert sorted(rc.absent) == ["Joe Smith", "John M. Gannon", "Tangi C. Smith"]
    yes = sorted(m for m, v in rc.votes.items() if v == "Yes")
    assert len(yes) == 18 and "Chris Rasnic" in yes and "Larry Rocconi" in yes
    assert rc.votes["John M. Gannon"] in ("none", "---")


def _r(source, votes, tally=(2, 1, 0), absent=(), reasons=("x",), clean=None):
    return P.Reading(source, dict(votes), tally, list(absent), list(reasons), {},
                     clean if clean is not None else {m: True for m in votes})


ROSTER4 = ["A", "B", "C", "D"]


def test_combine_fills_blank_cells_from_a_clean_reading():
    a = _r("text-layer", {"A": "Yes", "B": "none", "C": "No", "D": "---"}, absent=["D"])
    b = _r("tesseract", {"A": "Yes", "B": "Yes", "C": "No", "D": "---"}, absent=["D"],
           clean={"A": True, "B": True, "C": True, "D": False})
    c = P.combine([a, b], ROSTER4)
    assert c.reasons == [] and c.votes == {"A": "Yes", "B": "Yes", "C": "No", "D": "---"}


def test_combine_never_takes_a_vote_against_an_explicit_absent_mark():
    a = _r("text-layer", {"A": "Yes", "B": "---", "C": "No", "D": "---"}, absent=["D"])
    b = _r("tesseract", {"A": "Yes", "B": "Yes", "C": "No", "D": "---"}, absent=["D"])
    c = P.combine([a, b], ROSTER4)
    assert c.votes["B"] == "?" and any("no clean reading of the vote for B" in x for x in c.reasons)


def test_combine_ignores_junk_cells_and_needs_a_clean_one():
    # B is junk in both readings: unreadable, never guessed
    a = _r("text-layer", {"A": "Yes", "B": "Yes", "C": "No", "D": "---"}, absent=["D"],
           clean={"A": True, "B": False, "C": True, "D": True})
    b = _r("tesseract", {"A": "Yes", "B": "none", "C": "No", "D": "---"}, absent=["D"],
           clean={"A": True, "B": False, "C": True, "D": True})
    c = P.combine([a, b], ROSTER4)
    assert c.votes["B"] == "?" and c.reasons


def test_combine_holds_on_disagreeing_votes_tallies_or_absent_lines():
    a = _r("text-layer", {"A": "Yes", "B": "No", "C": "No", "D": "---"}, absent=["D"])
    b = _r("tesseract", {"A": "Yes", "B": "Yes", "C": "No", "D": "---"}, absent=["D"])
    assert P.combine([a, b], ROSTER4).votes["B"] == "?"
    a = _r("text-layer", {"A": "Yes", "B": "none", "C": "No", "D": "---"}, absent=["D"], tally=(2, 1, 0))
    b = _r("tesseract", {"A": "Yes", "B": "Yes", "C": "No", "D": "---"}, absent=["D"], tally=(3, 0, 0))
    assert any("disagree on stated tally" in x for x in P.combine([a, b], ROSTER4).reasons)
    a = _r("text-layer", {"A": "Yes", "B": "none", "C": "No", "D": "---"}, absent=["D"])
    b = _r("tesseract", {"A": "Yes", "B": "Yes", "C": "No", "D": "---"}, absent=["C"])
    assert any("ABSENT line" in x for x in P.combine([a, b], ROSTER4).reasons)


def test_combine_checks_the_result_against_the_stated_tally():
    # each cell has a clean reading, but the counts do not match the stated tally: held
    a = _r("text-layer", {"A": "Yes", "B": "none", "C": "Yes", "D": "---"}, absent=["D"])
    b = _r("tesseract", {"A": "Yes", "B": "Yes", "C": "none", "D": "---"}, absent=["D"])
    c = P.combine([a, b], ROSTER4)
    assert any(x.startswith("counted") for x in c.reasons)
    rc = _rc([a, b], roster=ROSTER4)
    assert rc.status == "Unverified" and rc.combined is None


def test_combine_needs_two_readings_and_an_absent_member_stays_without_a_vote():
    a = _r("text-layer", {"A": "Yes", "B": "Yes", "C": "No", "D": "none"}, absent=["D"])
    assert P.combine([a], ROSTER4) is None
    b = _r("tesseract", {"A": "Yes", "B": "Yes", "C": "No", "D": "Yes"}, absent=["D"])
    c = P.combine([a, b], ROSTER4)
    assert any("listed absent but has vote" in x for x in c.reasons)


# ------------------------------------------------------------------ outcome wording

def test_outcome_regex_reads_a_comma_phrase_before_by():
    ctx = ("On Motion by Commissioner Chandler, seconded by Commissioner Rasnic. The foregoing Resolution was "
           "Adopted, in its original state, by the following roll call vote:")
    assert list(P.OUTCOME_RE.finditer(ctx))[-1].group(1) == "Adopted"
    # still never a capitalised sentence in between
    assert not list(P.OUTCOME_RE.finditer("was Adopted. The Board then voted by the following roll call vote"))


# ------------------------------------------------------------------ blank tally count

ROSTER_SEP2022 = ["Joshua Beal", "David Harper", "Rickey Ray", "Nathan Burkholder", "Jason Knight", "David Shelton",
                  "Carmelle Chandler", "Michael Lankford", "Autumn Simmons", "Joe Creek", "RashidahLeverett",
                  "Joe Smith", "Billy Frye", "Jorge Padro", "Tangi Smith", "Ryan Gallant", "Lisa Prichard",
                  "Jeremiah Walker", "John Gannon", "Chris Rasnic", "Walker Woodruff"]


def test_blank_noes_count_is_derived_from_the_roster():
    """2022-09-12 p12: "Yeses -21 Noes - Abstentions -0" (no number printed for Noes; checked on the page image).
    Every present member votes once, so the blank count is the roster minus the absent minus the other two."""
    r = reading("rc_sep2022_p12_blank_noes.txt", "text-layer", ROSTER_SEP2022)
    assert r.reasons == [], r.reasons
    assert r.tally == (21, 0, 0) and r.absent == []
    assert all(v == "Yes" for v in r.votes.values()) and len(r.votes) == 21


def _table(tally_line: str, absent_line: str = "ABSENT: None") -> list[str]:
    return ["District Commissioner Vote", "1  Ann Alpha   Y", "2  Bob Bravo   N", "3  Cy Charlie  ---",
            tally_line, absent_line]


def test_blank_count_rules():
    roster = ["Ann Alpha", "Bob Bravo", "Cy Charlie"]

    def rd(lines):
        return P.read_table(lines, 0, len(lines), roster, "text-layer")[0]
    r = rd(_table("Yeses - 1 Noes - Abstentions - 0", "ABSENT: Cy Charlie (1)"))
    assert r.tally == (1, 1, 0) and r.reasons == []
    # two blanks: never derived
    r = rd(_table("Yeses - 1 Noes - Abstentions -", "ABSENT: Cy Charlie (1)"))
    assert r.tally is None and any("tally unreadable" in x for x in r.reasons)
    # a garbled count is not a blank one
    r = rd(_table("Yeses - S Noes - 1 Abstentions - 0", "ABSENT: Cy Charlie (1)"))
    assert r.tally is None and any("tally unreadable" in x for x in r.reasons)
    # an ABSENT line that does not resolve gives nothing to derive from
    r = rd(_table("Yeses - 1 Noes - Abstentions - 0", "ABSENT: Zed Zulu (1)"))
    assert r.tally is None
    # the derived count is still checked: Cy Charlie is absent per the table but the ABSENT line says None
    r = rd(_table("Yeses - 1 Noes - Abstentions - 0"))
    assert r.tally == (1, 2, 0) and any(x.startswith("counted") for x in r.reasons)


def test_outcome_regex_reads_minutes_variants():
    cases = {
        "The foregoing Resolution was Adopted, as Amended, by the following roll call vote:": "Adopted",
        "the Rules were Suspended for Resolution 25-1-7 by the following roll call vote:": "Suspended",
        "the Rules were Suspended for Resolutions 25-4-9 and 25-4-10 by the following roll call vote:": "Suspended",
        "The Motion Failed by th~ following roll call vote:": "Failed",
        "the foregoing Consent Agenda items were Adopted and Approved by the following rail call vote:": "Approved",
        "The foregoing Resotution was Adopted by the following roll catl vote:": "Adopted",
    }
    for ctx, word in cases.items():
        assert list(P.OUTCOME_RE.finditer(ctx))[-1].group(1) == word, ctx
    # a capitalised word that is not an item list still ends the match
    assert not list(P.OUTCOME_RE.finditer("was Deferred to the July 10, 2023 Formal Meeting by the following roll call"))
