"""Parser tests on short text-layer excerpts of Montgomery County Commission minutes."""
from pathlib import Path

import pytest

from collector import parse as P

FIX = Path(__file__).parent / "fixtures"


def fx(name: str) -> str:
    return (FIX / name).read_text()


def att_for(header: str) -> P.Attendance:
    a = P.parse_attendance([fx(header)])
    assert a is not None
    return a


def read(rc_fixture: str, header: str, source="text-layer"):
    att = att_for(header)
    lines = fx(rc_fixture).splitlines()
    heads = P.table_heads(lines)
    assert heads, "fixture has a vote table"
    reading, _ = P.read_table(lines, heads[0], len(lines), att.present + att.absent, source)
    return reading, att


# ------------------------------------------------------------------ attendance

def test_attendance_header_dec2024():
    a = att_for("header_dec2024.txt")
    assert a.verified, a.reasons
    assert a.date == "2024-12-09"
    assert len(a.present) == 19 and a.present_count == 19
    assert a.absent == ["Jason Knight", "Jeremiah Walker"]


def test_attendance_header_ocr_spelling_and_webex_marks():
    a = att_for("header_feb2021.txt")          # "Cormnissioners:", "Brandon Butts*"
    assert a.verified, a.reasons
    assert "Brandon Butts" in a.present and "Arnold Hodges" in a.present
    assert a.absent == [] and a.absent_count == 0


def test_attendance_header_vacancy():
    a = att_for("header_aug2021.txt")
    assert a.verified, a.reasons
    assert len(a.present) == 18 and len(a.absent) == 2
    assert a.vacant == ["District 18"]


# ------------------------------------------------------------------ vote tables

def test_clean_table_passes_p2_despite_ocr_name_errors():
    r, _ = read("rc_dec2024_p9_clean.txt", "header_dec2024.txt")   # "Jolm Gannon", "ii", "Autunrn"
    assert r.reasons == []
    assert r.tally == (19, 0, 0)
    assert r.votes["John Gannon"] == "Yes"
    assert r.votes["David Harper"] == "Yes"                       # lowercase "y"
    assert r.votes["Jason Knight"] == "---" and "Jason Knight" in r.absent


def test_dropped_vote_marks_are_unverified_not_guessed():
    r, _ = read("rc_dec2024_p64_dropped.txt", "header_dec2024.txt")
    assert any(x.startswith("no vote read for present member") for x in r.reasons)
    assert any(x.startswith("counted") for x in r.reasons)
    assert "Yes" not in {r.votes["David Harper"]}                 # blank stays blank


def test_source_inconsistency_is_held_back():
    # The scan itself marks Knight "Y" while the ABSENT line names him (clerical error).
    r, _ = read("rc_dec2024_p90_source_error.txt", "header_dec2024.txt")
    assert r.reasons
    ocr_lines = fx("ocr_dec2024_p90.txt").splitlines()
    att = att_for("header_dec2024.txt")
    o, _ = P.read_table(ocr_lines, P.table_heads(ocr_lines)[0], len(ocr_lines), att.present + att.absent, "tesseract")
    assert any("listed absent but has vote Yes: Jason Knight" in x for x in o.reasons)


def test_abstentions_and_merged_ocr_names():
    r, _ = read("rc_feb2021_p176_abstain.txt", "header_feb2021.txt")  # "R,ickeyRay", "JoeLCreek"
    assert r.reasons == []
    assert r.tally == (18, 1, 2)
    assert r.votes["Garland Johnson"] == "Abstain"
    assert r.votes["Arnold Hodges"] == "No"
    assert r.votes["Rickey Ray"] == "Yes"


def test_vacant_seat_and_allbert_brothers_kept_apart():
    r, att = read("rc_aug2021_p9_vacant.txt", "header_aug2021.txt")
    # "Randy Ailbert" and "Jeny Alibert" must map to the two different Allberts
    roster = att.present + att.absent
    randy = next(n for n in roster if n.startswith("Randy"))
    jerry = next(n for n in roster if n.startswith("Jer"))
    assert r.votes[randy] == "Yes" and r.votes[jerry] == "Yes"
    assert not any("VACANT" in x for x in r.reasons)
    # Joe L. Creek's mark is missing from the text layer: must fail, not pass
    assert any("Joe L. Creek" in x for x in r.reasons)


# ------------------------------------------------------------------ token rules

@pytest.mark.parametrize("tok,kind,val", [
    ("Y", "vote", "y"), ("y", "vote", "y"), ("¥", "vote", "y"), ("YY", "vote", "y"), ("Y¥", "vote", "y"),
    ("Y-", "vote", "y"), ("_Y", "vote", "y"), ("N,", "vote", "n"), ("A", "vote", "a"),
    ("---", "absent", "---"), ("—", "absent", "-"), ("=", "skip", ""),
    ("ii", "skip", "ii"), ("1]", "skip", "1"), ("io", "unknown", "io"),
    ("g", "unknown", "g"), ("WN", "unknown", "WN"), ("yN", "unknown", "yN"),
])
def test_classify_token(tok, kind, val):
    assert P.classify_token(tok) == (kind, val)


def test_chunk_row_keeps_short_surnames():
    assert P.chunk_row("4       Rickey Ray            Y        ii       Joe Creek   -   Y") == \
        ["4", "Rickey Ray", "Y", "ii", "Joe Creek", "-", "Y"]


def test_name_similarity_separates_first_names():
    assert P.name_similarity("Jerry Allbert", "Jerry Ailbert") > 0.85
    assert P.name_similarity("Jerry Allbert", "Randy Allbert") < P.ASSIGN_MIN
    assert P.name_similarity("JoeLCreek", "Joe L. Creek") > 0.9


# ------------------------------------------------------------------ outcome, items, decision

def test_outcome_regex_takes_word_next_to_roll_call():
    ctx = "The foregoing Amended Resolution was Adopted by the following roll call vote:"
    assert list(P.OUTCOME_RE.finditer(ctx))[-1].group(1) == "Adopted"
    ctx = "the Rules were Suspended for 24-4-6 by the follo*ing roll Call vote:"
    assert list(P.OUTCOME_RE.finditer(ctx))[-1].group(1) == "Suspended"


def test_outcome_must_agree_with_tally():
    assert P.check_outcome("Adopted", (19, 0, 0)) == []
    assert P.check_outcome("Failed", (4, 17, 0)) == []
    assert P.check_outcome("Adopted", (4, 17, 0))
    assert P.check_outcome(None, (19, 0, 0))


def test_item_numbers_and_titles():
    assert P.norm_item("24~12~1") == "24-12-1"
    assert P.norm_item("24_I2_2") == "24-12-2"
    assert P.norm_item("AB-4-2024") == "AB-4-2024"
    titles = P.item_titles([fx("agenda_dec2024_p2.txt")])
    assert titles["AB-4-2024"].startswith("Resolution Approving a Partial Public Right of Way")
    assert "24-12-1" in titles


def _rc(readings):
    rc = P.RollCall(source="t", meeting_date=None, page=1, end_page=1, line=0, item=None, item_title=None,
                    kind="resolution", outcome_text="Adopted", motion=None, mover=None, seconder=None,
                    votes={}, tally=None, absent=[])
    rc.readings = readings
    P.decide(rc)
    return rc


def test_decide_needs_a_clean_reading_and_no_disagreement():
    good = P.Reading("tesseract", {"A": "Yes", "B": "No"}, (12, 1, 0), [], [])   # decide() trusts the
    # reading's own checks; the tally only feeds the outcome check here
    bad = P.Reading("text-layer", {"A": "Yes", "B": "none"}, (12, 1, 0), [], ["no vote read for present member: B"])
    rc = _rc([bad, good])
    assert rc.status == "Verified" and rc.votes == good.votes and rc.verified_by == "tesseract"
    clash = P.Reading("text-layer", {"A": "No", "B": "No"}, (12, 1, 0), [], ["counted"])
    rc = _rc([clash, good])
    assert rc.status == "Unverified" and any("sources disagree for A" in x for x in rc.reasons)


def test_canonical_officials_merges_ocr_spellings_only():
    canon = P.canonical_officials(["Jerry Allbert"] * 5 + ["Jerry Ailbert", "Randy Allbert", "Randy Alibert",
                                                          "John M. Gannon", "John Gannon", "Joe Smith", "Tangi Smith"])
    assert canon["Jerry Ailbert"] == canon["Jerry Allbert"] == "Jerry Allbert"
    assert canon["Randy Alibert"] == canon["Randy Allbert"] != canon["Jerry Allbert"]
    assert canon["John M. Gannon"] == canon["John Gannon"]
    assert canon["Joe Smith"] != canon["Tangi Smith"]


def test_resolve_mover():
    roster = ["Joe Smith", "Tangi Smith", "Walker Woodruff"]
    assert P.resolve_commissioner("J. Smith", roster) == "Joe Smith"
    assert P.resolve_commissioner("Smith", roster) is None          # ambiguous: not guessed
    assert P.resolve_commissioner("Woodruff", roster) == "Walker Woodruff"


# ------------------------------------------------------------------ reading more correctly (headroom, 2026-11-08)
# Each rule below was hand-checked on the page images of the roll calls it newly verifies.

def _one_table(rows: list[str], tally: str, absent: str = "ABSENT: None"):
    from collector import parse as P
    lines = ["District Commissioner Vote District Commissioner Vote District Commissioner Vote"] + rows + [tally, absent]
    return P.read_table(lines, 0, len(lines), ROSTER6, "text-layer")[0]


ROSTER6 = ["John Gannon", "Jason Knight", "Joe Smith", "LaTonia Brown", "Jorge Padro", "Jeremiah Walker"]
ROWS6 = ["1   John Gannon      Y      8    LaTonia Brown     Y",
         "2   Jason Knight     Y      9    Jorge Padro       Y",
         "3   Joe Smith        Y     10    Jeremiah Walker   Y"]


def test_text_layer_u_for_a_printed_zero_is_zero_but_s_stays_garbled():
    """"Noes—U" is the text layer's reading of "Noes – 0" (March 2024 p56, May 2025 p44, November 2025 p47, February
    2022 p15 and p74, checked on the images); "S" stands for 5 in some places and 8 in others, so it stays garbled."""
    from collector import parse as P
    assert P._int("U", tally=True) == 0 and P._int("S", tally=True) is None
    r = _one_table(ROWS6, "Yeses —6         Noes—U Abstentions          —   0")
    assert r.tally == (6, 0, 0) and r.printed == (6, 0, 0) and not r.reasons
    r = _one_table(ROWS6, "Yeses —6 Noes —S Abstentions —0")
    assert r.tally is None and any(x.startswith("tally unreadable") for x in r.reasons)


def test_u_for_zero_is_mapped_only_in_tally_counts():
    """"U" for 0 was checked on tally counts only, so an attendance count, an ABSENT count or a date's day with "U"
    stays garbled (parse-accuracy/glyph-scope); the other glyphs still map everywhere."""
    from collector import parse as P
    assert P._int("U") is None and P._int("1U") is None and P._int("1O") == 10
    assert P.header_date("on Sunday, December 1O, 2023")[0] == "2023-12-10"     # the O rule is unchanged
    assert P.header_date("on Sunday, December 1U, 2023")[0] is None


def test_a_misread_s_in_the_abstentions_label_is_still_the_tally_line():
    """tesseract reads "Abstentions" as "Abitentions" or "Abétentions" (April 2026 p28, p92): the label, never a
    count, is read through it."""
    for label in ("Abitentions", "Abétentions", "Ab~tentions", "Abstentions"):
        r = _one_table(ROWS6, f"Yeses—6 Noes—0 {label} — 0")
        assert r.tally == (6, 0, 0) and not r.reasons, label
    assert _one_table(ROWS6, "Yeses—6 Noes—0 Absent — 0").tally is None       # not the label


def test_a_noisy_vote_letter_in_the_mid_row_district_column_is_the_district():
    """tesseract reads district 9 as "a)" between Jason Knight's "Y" and Jorge Padro (December 2025 p70)."""
    rows = list(ROWS6)
    rows[1] = "2   Jason Knight     Y      a)    Jorge Padro       Y"
    r = _one_table(rows, "Yeses—6 Noes—0 Abstentions—0")
    assert r.votes["Jason Knight"] == "Yes" and r.clean["Jason Knight"] and not r.reasons
    # a plain second letter is not skipped: it still counts against the cell
    rows[1] = "2   Jason Knight     Y      A    Jorge Padro       Y"
    r = _one_table(rows, "Yeses—6 Noes—0 Abstentions—0")
    assert r.votes["Jason Knight"] == "?"
    # with the district number dropped, the vote letter just before the next name is still the vote
    rows[1] = "2   Jason Knight     Y            Jorge Padro       Y"
    rows[0] = "1   John Gannon             LaTonia Brown     Y"
    r = _one_table(rows, "Yeses—5 Noes—0 Abstentions—0")
    assert r.votes["John Gannon"] == "none"
    rows[0] = "1   John Gannon      Y      LaTonia Brown     Y"
    assert _one_table(rows, "Yeses—6 Noes—0 Abstentions—0").votes["John Gannon"] == "Yes"
