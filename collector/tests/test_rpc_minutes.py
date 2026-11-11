"""Regional Planning Commission milestone 2 (collector/rpc_minutes.py, rpc_agenda.build): motions read from the
minutes, case numbers, the confirmation rule, scanned agendas read by OCR and the completeness nit. The *_ocr.txt
fixtures are tesseract's reading (collector/ocr.py settings) of real pages of the RPC's own PDFs; no network, no OCR
run here."""
from pathlib import Path

import pytest

from collector import rpc, rpc_agenda, rpc_minutes as R
from collector.store import Store

FIX = Path(__file__).parent / "fixtures" / "rpc"
PREFIXES = set(rpc.load_config().case_types)


def pages(name: str) -> list[str]:
    return (FIX / name).read_text(encoding="utf-8").split("\f")[:-1]


@pytest.fixture(scope="module")
def may2022():
    """2022-05-24 minutes, pages 1-5, 18, 19 (fixture pages 1-7)."""
    return R.read_minutes(pages("minutes_2022-05-24_ocr.txt"), {"Z-16-2022", "Z-28-2022", "Z-31-2022"}, PREFIXES)


# ------------------------------------------------------------------ header, cases
def test_members_present_two_columns_left_column_only(may2022):
    assert may2022.members == ["Richard Swift", "Thom Spigner", "Bryce Powers", "Wade Hadley", "Stacey Streetman",
                               "Bill Kimbrough", "Maria Jiminez", "Larry Rocconi", "Michael Long"]
    assert may2022.printed_date["date"] == "2022-05-24"


def test_members_present_one_column_list_after_staff():
    r = R.read_minutes(pages("minutes_2026-08-24-cdrb_p1_ocr.txt"), {"DDR-14-2026"}, PREFIXES)
    assert r.members == ["Gary Shephard", "James Bagby", "Gail Longton", "John Gannon", "Kirk Zeaman", "Doug Jones"]
    assert r.sections == [("DDR-14-2026", "DDR-14-2026", 1)]       # a case number alone on its line is a heading


def test_case_headings_and_the_prefix_repair_only_onto_the_agenda(may2022):
    secs = {printed: case for case, printed, _ in may2022.sections}
    assert secs["2-16-2022"] == "Z-16-2022"     # OCR read Z as 2; Z-16-2022 is on the agenda
    assert secs["2-31-2022"] == "Z-31-2022"
    assert secs["Z-32-2022"] == "Z-32-2022"     # read cleanly: kept though this test's agenda does not list it
    r = R.read_minutes(pages("minutes_2022-05-24_ocr.txt"), set(), PREFIXES)
    assert {printed: case for case, printed, _ in r.sections}["2-16-2022"] is None   # never guessed
    assert (r.case_heads_printed, r.case_heads_read) == (9, 7)


@pytest.mark.parametrize("printed,key", [("CZ-01-2024", "CZ-1-2024"), ("CZ-l1-2022", "CZ-11-2022"),
                                         ("CZ - O7 - 2024", "CZ-7-2024"), ("CZO-1-2023", "CZO-1-2023"),
                                         ("ZO-2A-2026", "ZO-2A-2026"), ("CZ-1-20", None), ("not a case", None)])
def test_link_key_is_the_parse_py_glyph_rule_without_zero_padding(printed, key):
    assert R.link_key(printed) == key


def test_a_wrapped_list_of_deferrals_is_not_a_case_heading():
    r = R.read_minutes(pages("minutes_2024-10-29_p1_ocr.txt"), {"SR-44-2024"}, PREFIXES)
    assert r.sections == []
    approve = [m for m in r.motions if m.outcome == "deferrals were approved"][0]
    assert approve.case is None and approve.confirmed
    assert (approve.mover, approve.seconder) == ("Bill Kimbrough", "Charlie Patterson")


# ------------------------------------------------------------------ motions
def test_motions_as_printed_2022_layout(may2022):
    by_case = {}
    for m in may2022.motions:
        by_case.setdefault(m.case, []).append(m)
    # "Mrs. Streetman moved to recommend approval": the minutes are named only in the sentence before, so the
    # motion's own sentences do not read its subject (rule 1)
    minutes = by_case[None][0]
    assert (minutes.mover, minutes.seconder, minutes.outcome, minutes.confirmed) == \
        ("Mrs. Streetman", "Mr. Kimbrough", "carried unanimously", False)
    assert minutes.reasons == [R.WHY_SUBJECT]
    defer = by_case["Z-16-2022"][0]
    assert (defer.kind, defer.mover, defer.seconder, defer.abstained, defer.outcome, defer.confirmed) == \
        ("Motion to defer", "Mr. Hadley", "Mr. Powers", ["Mr. Rocconi"], "Motion passed", True)
    dis = by_case["Z-32-2022"][0]
    assert (dis.kind, dis.outcome, dis.confirmed) == ("Motion for disapproval", "Motion for disapproval passed", True)


def test_a_name_spelled_unlike_the_header_is_not_confirmed(may2022):
    # the minutes print "Mrs. Jimenez" in the motion and "Maria Jiminez" in the header: nothing is forgiven
    z30 = [m for m in may2022.motions if m.case == "Z-30-2022"][0]
    assert z30.nays == ["Mrs. Streetman"] and not z30.confirmed
    assert "seconder is not one member present" in z30.reasons


GARBLED_HEADER = ("MEMBERS PRESENT:\nCharlie Patterson\nStacey Streetman\nBill Kimb   h\nCindy Greene\n"
                  "STAFF PRESENT:\nJeff Tyndall\nMeeting was called to order.\nCASE NUMBER: S-1-2025\n")


def test_named_nay_and_abstention_after_except():
    roster = ["Charlie Patterson", "Stacey Streetman", "Cindy Greene", "Bill Kimbrough"]
    p17 = pages("minutes_2025-06-24_p17_ocr.txt")
    r = R.read_minutes([GARBLED_HEADER + p17[0]], {"S-1-2025"}, PREFIXES, roster)
    assert r.header_garbled and "Bill Kimbrough" not in r.members
    m = r.motions[0]
    assert (m.mover, m.seconder, m.nays, m.abstained) == ("Charlie Patterson", "Stacey Streetman",
                                                          ["Bill Kimbrough"], ["Cindy Greene"])
    assert m.case == "S-1-2025"
    # rpc-votes/outcome-not-printed (2025-06-24 S-42-2025, QA 2026-11-11): "All members voted in favor, except Cindy
    # Greene who abstained and Bill Kimbrough who voted against." prints no outcome; its first words are not one
    assert m.outcome is None and m.tally is None and not m.confirmed
    assert m.reasons == [R.WHY_FAVOUR_NOT_OUTCOME]     # rule 2a matched Bill Kimbrough on the garbled header line


# rpc-votes/outcome-not-printed: the real sentence (2025-06-24 minutes p17, S-42-2025) and its shapes
S42 = ("Charlie Patterson made a motion for approval, seconded by Stacey Streetman. All members voted in\n"
       "favor, except Cindy Greene who abstained and Bill Kimbrough who voted against.")
S42_MEMBERS = ("Charlie Patterson", "Stacey Streetman", "Bill Kimbrough", "Cindy Greene", "Michael Long")


@pytest.mark.parametrize("text", [
    S42,
    S42 + "\nJeff Tyndall made a comment.",
    "Charlie Patterson made a motion for approval, seconded by Stacey Streetman. All members voted in favor, but Bill "
    "Kimbrough voted against.",
    "Charlie Patterson made a motion for approval, seconded by Stacey Streetman. All members voted in favor. Bill "
    "Kimbrough voted against.",
    "Charlie Patterson made a motion for approval, seconded by Stacey Streetman. Bill Kimbrough voted against. All "
    "others voted in favor.",
    "Charlie Patterson made a motion for approval, seconded by Stacey Streetman. All members voted in favor, except "
    "Cindy Greene who abstained.",
])
def test_an_in_favor_sentence_that_goes_on_or_has_nays_is_never_the_outcome(text):
    m = _one("CASE NUMBER: S-42-2025\n" + text, S42_MEMBERS)[0]
    assert m.outcome is None and not m.confirmed, (m.outcome, m.reasons)
    assert R.WHY_FAVOUR_NOT_OUTCOME in m.reasons


def test_an_outcome_sentence_after_the_except_sentence_is_the_outcome():
    """2025-11-25-style: the printed outcome sentence follows, so it is the outcome and the motion confirms."""
    m = _one("CASE NUMBER: S-42-2025\n" + S42 + " Motion passes for approval 4-1.", S42_MEMBERS)[0]
    assert m.outcome == "Motion passes for approval 4-1" and m.tally == "4-1"
    assert (m.nays, m.abstained, m.confirmed) == (["Bill Kimbrough"], ["Cindy Greene"], True), m.reasons


def test_a_whole_in_favor_sentence_with_no_nays_is_still_the_outcome():
    m = _one("CASE NUMBER: S-42-2025\nCharlie Patterson made a motion for approval, seconded by Stacey Streetman. "
             "All members voted in favor.", S42_MEMBERS)[0]
    assert m.outcome == "All members voted in favor" and m.confirmed, m.reasons


# rpc-votes/outcome-phrase-choice: the real sentences (2024-10-29 SR-58-2024 p15, 2024-09-24 S-41-2024 p5)
@pytest.mark.parametrize("votes,outcome", [
    ("All others voted in favor. Motion was approved on consent agenda.", "Motion was approved on consent agenda"),
    ("All others voted in favor. Motion was approved on the Consent Agenda.",
     "Motion was approved on the Consent Agenda"),
])
def test_the_printed_outcome_sentence_is_preferred_to_the_in_favor_sentence(votes, outcome):
    m = _one("CASE NUMBER: SR-58-2024\nJeff Henley made a motion for approval, seconded by Stacey Streetman. " + votes,
             ("Jeff Henley", "Stacey Streetman", "Charlie Patterson"))[0]
    assert m.outcome == outcome and m.confirmed, (m.outcome, m.reasons)


def _one(text: str, members=("Wade Hadley", "Bryce Powers", "Stacey Streetman", "Bill Kimbrough", "Michael Long")):
    page = "Members Present          Others Present\n" + "\n".join(members) + "\nMeeting was called to order.\n" + text
    return R.read_minutes([page], set(), PREFIXES).motions


@pytest.mark.parametrize("text,reason", [
    ("Mr. Hadley made the motion for approval. Mr. Powers seconded. Mr. Hadley, Mr. Powers were in favor, "
     "Mrs. Streetman was in opposition. Mr. Long broke the tie. Motion passed.", "unmodelled wording: a tie"),
    ("Mr. Hadley made the motion for approval. Mr. Powers seconded. All voted in favor except Mrs. Streetman. "
     "Motion passed.", "'except'"),
    ("Mr. Hadley made the motion for disapproval. Mr. Powers seconded. All others were in favor. Motion for approval "
     "passed.", "the outcome names another kind of motion"),
    ("Mr. Hadley made the motion for approval. Mr. Powers seconded. All members voted in favor except Mr. Long who "
     "voted against. Motion passes for approval 4-2.", "the printed tally does not match"),
    ("Mr. Hadley made the motion for approval. Mr. Kinmbrough seconded. Motion passed.", "seconder is not one member"),
    ("Mr. Hadley made the motion for approval. Mr. Powers seconded. Mr. Long made a comment.", "no outcome read"),
    ("Mr. Hadley made a motion to amend the conditions. Mr. Powers seconded. Motion passed.", "amendment"),
])
def test_anything_uncertain_is_not_confirmed(text, reason):
    m = _one(text)[0]
    assert not m.confirmed and any(reason in r for r in m.reasons), m.reasons


def test_a_motion_that_dies_for_lack_of_a_second_needs_no_seconder():
    m = _one("CASE NUMBER: Z-5-2026\nStacey Streetman made a motion for disapproval. Motion falls for a lack of a "
             "second. Mr. Long asked.")[0]
    assert m.seconder is None and m.outcome == "Motion falls for a lack of a second" and m.confirmed


def test_motions_after_other_business_or_to_adjourn_belong_to_no_case():
    ms = _one("CASE NUMBER: Z-5-2026 APPLICANT: A\nMr. Hadley made the motion for approval. Mr. Powers seconded. "
              "Motion passed.\nOTHER BUSINESS:\nMr. Long made the motion to approve the P & L. Mr. Powers seconded. "
              "Motion passed.\nMr. Long made a motion to adjourn, seconded by Mr. Powers. All members voted in favor.")
    assert [(m.case, m.kind) for m in ms] == [("Z-5-2026", "Motion for approval"), (None, "Motion for approval"),
                                             (None, "Motion to adjourn")]
    # the P & L approval has no case and is not the meeting's own business in the reader's list: subject not read
    assert [m.confirmed for m in ms] == [True, False, True]
    assert ms[1].reasons == [R.WHY_SUBJECT]


# ------------------------------------------------------------------ build: OCR, attachment, date rule
@pytest.fixture()
def built(tmp_path):
    cfg = rpc.load_config()
    rows = rpc.assign_ids([
        {"date": "2025-09-22", "label": "CDRB", "printed": "9/22/2025 – CDRB", "kind": "cdrb", "cancelled": False,
         "docs": [{"kind": "agenda", "url": "https://www.cmcrpc.com/a-9-22-2025.pdf", "host": "www.cmcrpc.com",
                   "fetch": True}, {"kind": "minutes", "url": "https://www.cmcrpc.com/m-8-24-2026.pdf",
                                    "host": "www.cmcrpc.com", "fetch": True}], "no_doc": []},
        {"date": "2026-08-24", "label": "CDRB", "printed": "8/24/2026 – CDRB", "kind": "cdrb", "cancelled": False,
         "docs": [{"kind": "minutes", "url": "https://www.cmcrpc.com/m-8-24-2026.pdf", "host": "www.cmcrpc.com",
                   "fetch": True}], "no_doc": []}])
    store = Store(manifest_path=tmp_path / "manifest.json", root=tmp_path / "store")
    store.put("https://www.cmcrpc.com/a-9-22-2025.pdf", b"%PDF a", {}, {"kind": "agenda"})
    store.put("https://www.cmcrpc.com/m-8-24-2026.pdf", b"%PDF m", {}, {"kind": "minutes"})
    agenda_sha = store.latest("https://www.cmcrpc.com/a-9-22-2025.pdf")["sha256"]
    scans = {agenda_sha: pages("agenda_2025-09-22-cdrb_ocr.txt"),
             store.latest("https://www.cmcrpc.com/m-8-24-2026.pdf")["sha256"]: pages("minutes_2026-08-24-cdrb_p1_ocr.txt")}
    calls = []

    def ocr(pdf, sha, n):
        calls.append(sha)
        return scans[sha]

    facts, summary = rpc_agenda.build(cfg, rows, store, extract=lambda p: [""] * len(scans[p.stem]), ocr=ocr)
    return facts, summary, calls


def test_a_scanned_agenda_is_read_by_ocr_with_the_border_marks_dropped(built):
    facts, summary, calls = built
    m = {m["id"]: m for m in facts["meetings"]}["2025-09-22-cdrb"]
    # "1. | CASE NUMBER: DDR - 18 - 2025": the OCR'd table rule after the item number is not case text
    assert [c["number"] for c in facts["cases"]] == ["DDR-18-2025", "MSCD-27-2025"]
    assert all(c["read_by"] == "OCR" for c in facts["cases"]) and m["agenda_read_by"] == "OCR"
    assert facts["cases"][0]["applicant"] == "Planters Bank" and facts["cases"][0]["agent"] == "Bryce Powers"
    assert (m["case_numbers_printed"], m["case_numbers_read"], summary["case_shortfalls"]) == (2, 2, [])
    assert len(calls) == len(set(calls)) == 2       # each scan read once, though its minutes are listed twice


def test_minutes_attach_only_to_the_meeting_whose_date_they_print(built):
    facts, summary, _ = built
    ms = {m["id"]: m for m in facts["meetings"]}
    assert ms["2026-08-24-cdrb"]["minutes_source_id"] and ms["2025-09-22-cdrb"]["minutes_source_id"] is None
    assert any("2025-09-22-cdrb: the listed minutes print" in p for p in summary["problems"])
    assert {mv["meeting_id"] for mv in facts["motions"]} == {"2026-08-24-cdrb"}
    mv = facts["motions"][0]
    assert (mv["kind"], mv["moved_by"], mv["seconded_by"], mv["outcome"], mv["confirmed"]) == \
        ("Motion to approve the minutes", "Gail Longton", "James Bagby", "minutes were approved", True)
    assert summary["motions"] == 1 and summary["motions_confirmed"] == 1


def test_ocr_failure_leaves_the_document_unread_and_reported(tmp_path):
    cfg = rpc.load_config()
    rows = rpc.assign_ids([{"date": "2025-09-22", "label": "CDRB", "printed": "9/22/2025", "kind": "cdrb",
                            "cancelled": False, "no_doc": [], "docs": [{"kind": "agenda", "host": "www.cmcrpc.com",
                                                                        "url": "https://www.cmcrpc.com/a.pdf",
                                                                        "fetch": True}]}])
    store = Store(manifest_path=tmp_path / "manifest.json", root=tmp_path / "store")
    store.put("https://www.cmcrpc.com/a.pdf", b"%PDF a", {}, {"kind": "agenda"})

    def ocr(pdf, sha, n):
        raise RuntimeError("OCR failed on page 2 (timeout)")

    facts, summary = rpc_agenda.build(cfg, rows, store, extract=lambda p: ["", ""], ocr=ocr)
    assert facts["cases"] == [] and facts["meetings"][0]["agenda_read_by"] is None
    assert any("OCR failed on page 2" in p for p in summary["problems"])
    assert any("agenda has no text layer and was not read by OCR" in p for p in summary["problems"])


# ------------------------------------------------------------------ completeness nit, watermark
def test_numbered_case_lines_count_in_the_completeness_check():
    res = rpc_agenda.parse_pages(["1. Z - 1 - 2026 OWNER(S): A\n2. Z - 2 - 2O26 OWNER(S): B\n"])
    # "2. Z - 2 - 2O26" (a misread year) is a numbered case line the reader cannot read: reported, never silent
    assert (res["numbered_printed"], res["numbered_read"], len(res["cases"])) == (2, 1, 1)
    assert res["case_numbers_printed"] > res["case_numbers_read"]


def test_the_watermark_skip_never_drops_a_zoning_code():
    assert rpc_agenda.ZONING_CODES, "the county's zoning codes list is read"
    assert not [c for c in rpc_agenda.ZONING_CODES if rpc_agenda.is_watermark(c)]
    for letters in ("D", "R", "A", "F", "T", "AF", "DR", "FT"):
        assert rpc_agenda.is_watermark(f"   {letters}  ")
    res = rpc_agenda.parse_pages(["1. CZ - 3 - 2024 OWNER(S): A REQUEST: R-1 to\nAG\nLOCATION: B\nR\n"])
    assert res["cases"][0]["fields"]["request"] == "R-1 to AG"


# ------------------------------------------------------------------ docs/architecture/rpc-motion-invariant.md
def _read(text: str, members=("Wade Hadley", "Bryce Powers", "Stacey Streetman", "Bill Kimbrough", "Michael Long"),
          roster=()):
    page = "Members Present          Others Present\n" + "\n".join(members) + "\nMeeting was called to order.\n" + text
    return R.read_minutes([page], set(), PREFIXES, roster)


def _case(text: str):
    return _one("CASE NUMBER: Z-5-2026\n" + text)


MOVED = "Mr. Hadley made the motion for approval. Mr. Powers seconded. "


@pytest.mark.parametrize("votes", [
    "Mr. Long opposed. Motion passed.",
    "Voting nay were Mr. Long and Mrs. Streetman. Motion passed.",
    "Mr. Long voted nav. Motion passed.",                   # OCR's "nay"
    "Mr. Long recused himself. Motion passed.",
    "Mr. Long dissenting. Motion passed.",
    "Nays: Mr. Long. Motion passed.",
    "Mr. Long did not vote. Motion passed.",
    "Motion passed. Mr. Long voted nay.",                   # the one sentence after the outcome
])
def test_a_vote_word_the_reader_does_not_read_is_not_confirmed(votes):
    m = _case(MOVED + votes)[0]
    assert not m.confirmed and R.WHY_VOTE_WORD in m.reasons, m.reasons


# code review 5769870 finding 2 (rpc-motion/c3-vote-words): each phrasing came back confirmed with nays=[]
@pytest.mark.parametrize("votes", [
    'Mr. Long voted "no". Motion passed.',
    "Mr. Long voted “no”. Motion passed.",                  # curly quotes
    "Mr. Long voted ‘no’. Motion passed.",
    "Mr. Long was not in favor. Motion passed.",
    "Motion passed. Mr. Long was not in favor.",
    "Mr. Long cast the only no vote. Motion passed.",
    "Motion passed with one no vote.",
    "Motion passed with Mr. Long voting in the negative.",
    "Motion passed, Mr. Long objecting.",
    "Motion passed. Mrs. Streetman thanked staff. Mr. Long voted nay.",     # two sentences after the outcome
    # the same family, wider than the review's list (the list is a denylist: wide on purpose)
    "Motion passed. Mrs. Streetman thanked staff for the report on the traffic study and the drainage plan, and the "
    "chairman thanked the applicant for coming. Staff noted the next step. Mr. Long voted nay.",   # to section end
    "The vote was 5 to 1. Motion passed.",
    "By a vote of 5-1, the motion passed.",
    "Ayes: Mr. Hadley, Mr. Powers. Noes: Mr. Long. Motion passed.",
    "Mr. Long declared a conflict of interest. Motion passed.",
    "Mr. Long refrained. Motion passed.",
    "Mr. Long did not support the motion. Motion passed.",
    "Mr. Long disagreed. Motion passed.",
    "Motion passed. Mr. Long asked that his vote be recorded.",
])
def test_a_vote_word_anywhere_up_to_the_next_motion_is_not_confirmed(votes):
    m = _case(MOVED + votes)[0]
    assert not m.confirmed and R.WHY_VOTE_WORD in m.reasons, m.reasons
    assert m.nays == [] or not m.confirmed


def test_the_scan_after_the_outcome_stops_at_the_next_motion():
    ms = _one("Mr. Hadley made a motion to approve the minutes. Mr. Powers seconded. Motion passed. "
              "Mr. Long made a motion to adjourn, seconded by Mr. Powers. Mrs. Streetman voted nay. All others were "
              "in favor. Motion passed.\nCASE NUMBER: Z-5-2026\n")
    assert [(m.kind, m.confirmed) for m in ms] == [("Motion to approve the minutes", True), ("Motion to adjourn", True)]
    assert ms[1].nays == ["Mrs. Streetman"] and ms[0].nays == []


def test_words_after_the_outcome_with_no_vote_word_stay_confirmed():
    m = _case(MOVED + "Motion passed. Mrs. Streetman thanked staff.")[0]
    assert m.confirmed, m.reasons


@pytest.mark.parametrize("votes", ["Mrs. Streetman voted nay. All others were in favor. Motion passed.",
                                   "Mrs. Streetman voted nay. Motion passed."])
def test_a_modelled_nay_stays_confirmed(votes):
    m = _case(MOVED + votes)[0]
    assert m.confirmed and m.nays == ["Mrs. Streetman"] and m.outcome == "Motion passed", m.reasons


def test_a_nay_with_only_an_in_favor_sentence_has_no_outcome():
    # rpc-votes/outcome-not-printed: with a member named as voting nay, "All others were in favor." is not an outcome
    m = _case(MOVED + "Mrs. Streetman voted nay. All others were in favor.")[0]
    assert m.nays == ["Mrs. Streetman"] and m.outcome is None and not m.confirmed
    assert m.reasons == [R.WHY_FAVOUR_NOT_OUTCOME]


@pytest.mark.parametrize("mangled", ["CASE NUMBFR: Z-6-2026", "C ASE NUMRER"])
def test_a_mangled_case_heading_starts_its_own_section(mangled):
    r = _read(f"CASE NUMBER: Z-5-2026\n{MOVED}Motion passed.\n{mangled}\n"
              "Mrs. Streetman made the motion for approval. Mr. Long seconded. Motion passed.\n"
              f"CASE NUMBER: Z-7-2026\n{MOVED}Motion passed.\n")
    first, second, third = r.motions
    assert first.case == "Z-5-2026" and first.confirmed
    assert second.case is None and not second.confirmed and R.WHY_HEAD in second.reasons
    assert third.case == "Z-7-2026" and third.confirmed
    assert (r.case_heads_printed, r.case_heads_read) == (3, 2)


def _read_on(text: str, agenda: set[str]):
    page = ("Members Present          Others Present\n" + "\n".join(
        ("Wade Hadley", "Bryce Powers", "Stacey Streetman", "Bill Kimbrough", "Michael Long"))
        + "\nMeeting was called to order.\n" + text)
    return R.read_minutes([page], agenda, PREFIXES)


NEXT = "Mrs. Streetman made the motion for approval. Mr. Long seconded. Motion passed.\n"


# code review 5769870 finding 3 (rpc-motion/c1-case-heading): under Z-5-2026, with Z-6-2026 on the agenda, a section
# with no motion of its own, then a heading with a mangled CASE word: the next motion was confirmed under Z-5-2026
@pytest.mark.parametrize("mangled", ["GASE NUMBER: Z-6-2026", "CASF NUMBER: Z-6-2026", "Case Numbr: Z-6-2026",
                                     "CASE NO. Z-6-2026", "CASE #: Z-6-2026", "2. GASE NUMBER: Z-6-2026"])
def test_a_mangled_case_word_starts_its_own_section(mangled):
    r = _read_on(f"CASE NUMBER: Z-5-2026\nStaff presented the request. No one spoke.\n{mangled}\n{NEXT}",
                 {"Z-5-2026", "Z-6-2026"})
    (m,) = r.motions
    assert m.case is None and not m.confirmed and R.WHY_HEAD in m.reasons, (m.case, m.reasons)
    assert (r.case_heads_printed, r.case_heads_read) == (2, 1)


def test_another_agenda_case_printed_in_a_case_section_unconfirms_its_motions():
    """The robust guard: a heading no pattern reads ("The next item, Z-6-2026, ..."), so the section of Z-5-2026
    runs on; the other agenda case printed in it, outside the motion's own sentences, unconfirms the section."""
    for printed in ("Z-6-2026", "Z - 06 - 2026", "2-6-2026"):         # as printed, zero padded, Z read as 2
        r = _read_on(f"CASE NUMBER: Z-5-2026\nStaff presented the request.\nThe next item, {printed}, was "
                     f"presented by staff.\n{NEXT}", {"Z-5-2026", "Z-6-2026"})
        (m,) = r.motions
        assert m.case == "Z-5-2026" and not m.confirmed and R.WHY_SECTION_OTHER_CASE in m.reasons, (printed, m.reasons)
        assert R.WHY_SECTION_OTHER_CASE in R.CASE_REASONS     # rpc_agenda places it under no case


def test_a_case_section_naming_only_its_own_case_or_an_old_case_stays_confirmed():
    r = _read_on(f"CASE NUMBER: Z-5-2026\nStaff said Z-05-2026 follows an earlier rezoning, Z-3-2015.\n{NEXT}",
                 {"Z-5-2026", "Z-6-2026"})
    (m,) = r.motions
    assert m.case == "Z-5-2026" and m.confirmed, m.reasons


@pytest.mark.parametrize("line,loose", [("Mr. Long asked about the case number of the request.", False),
                                        ("asked for the Case No. of the request.", False),
                                        # near a line's start it counts (any doubt): the section after it is unread
                                        ("Case not heard by the board tonight, said staff.", True)])
def test_the_loose_case_word_reads_near_a_line_start_only(line, loose):
    assert bool(R.LOOSE_HEAD.search(R._clean(line))) is loose


def test_two_disposing_motions_on_one_case_section_are_both_unconfirmed():
    ms = _case(f"{MOVED}Motion passed. Mrs. Streetman made the motion for approval. Mr. Long seconded. Motion passed.")
    assert len(ms) == 2 and all(not m.confirmed and R.WHY_TWO in m.reasons for m in ms)


def test_a_seconder_joined_to_a_nay_is_never_read_as_voting_nay():
    m = _case("Mr. Hadley made the motion for approval, seconded by Mr. Powers and Mrs. Streetman voted nay. "
              "Motion passed.")[0]
    assert "Mr. Powers" not in m.nays
    assert m.nays == ["Mrs. Streetman"] or not m.confirmed


def test_the_mover_named_as_voting_nay_is_not_confirmed():
    m = _case(MOVED + "Mr. Hadley voted nay. Motion passed.")[0]
    assert not m.confirmed and R.WHY_NAY_IS_MOVER in m.reasons


def test_a_motion_naming_another_case_is_not_confirmed():
    m = _case("Mr. Hadley made the motion for approval of Z-6-2026. Mr. Powers seconded. Motion passed.")[0]
    assert not m.confirmed and R.WHY_OTHER_CASE in m.reasons
    own = _case("Mr. Hadley made the motion for approval of Z-05-2026. Mr. Powers seconded. Motion passed.")[0]
    assert own.confirmed, own.reasons        # its own case, as printed with zero padding


CASELESS = [
    ("Mr. Hadley made the motion for approval. Mr. Powers seconded. Motion passed.", "Motion for approval", False),
    ("Mr. Hadley made a motion to defer. Mr. Powers seconded. Motion passed.", "Motion to defer", False),
    ("Mr. Hadley made the motion. Mr. Powers seconded. Motion passed.", "Motion", False),
    ("Mr. Hadley made a motion to approve the minutes. Mr. Powers seconded. Motion passed.",
     "Motion to approve the minutes", True),
    ("Mr. Hadley made a motion to adjourn, seconded by Mr. Powers. All members voted in favor.",
     "Motion to adjourn", True),
    ("Mr. Hadley made a motion to elect Mrs. Streetman as chair. Mr. Powers seconded. Motion passed.",
     "Motion to elect", True),
    ("Mr. Hadley made a motion to approve the consent agenda. Mr. Powers seconded. Motion passed.",
     "Motion to approve the consent agenda", True),
    ("Mr. Hadley made a motion of approval, Mr. Powers seconded. All others voted in favor, and deferrals were "
     "approved.", "Motion to approve the deferrals", True),
]


@pytest.mark.parametrize("where", ["before the first case", "under other business"])
@pytest.mark.parametrize("text,kind,confirmed", CASELESS)
def test_a_caseless_motion_is_confirmed_only_as_the_meetings_own_business(where, text, kind, confirmed):
    body = (f"{text}\nCASE NUMBER: Z-5-2026\n" if where == "before the first case"
            else f"CASE NUMBER: Z-5-2026\nOTHER BUSINESS:\n{text}\n")
    m = [m for m in _one(body) if m.case is None][0]
    assert m.kind == kind and m.confirmed is confirmed, m.reasons
    if not confirmed:
        assert m.reasons == [R.WHY_SUBJECT]


def test_the_roster_is_asked_only_when_the_header_shows_a_garbled_member_line():
    roster = ["Wade Hadley", "Bryce Powers", "Michael Long"]
    text = "CASE NUMBER: Z-5-2026\nMr. Long made the motion for approval. Mr. Powers seconded. Motion passed.\n"
    clean = _read(text, members=("Wade Hadley", "Bryce Powers"), roster=roster)
    assert not clean.header_garbled
    assert not clean.motions[0].confirmed and "mover is not one member present" in clean.motions[0].reasons
    garbled = _read(text, members=("Wade Hadley", "Bryce Powers", "Mich@el L0ng"), roster=roster)
    assert garbled.header_garbled and garbled.motions[0].confirmed, garbled.motions[0].reasons


# code review 5769870 finding 5 (rpc-motion/c2-roster): only a line that looks like a member's name with a defect
# marks the header garbled; a heading or a line of marks never opens the roster fallback
@pytest.mark.parametrize("line,garbled", [("CALL TO ORDER", False), ("I. CALL TO ORDER", False),
                                          ("PLEDGE OF ALLEGIANCE", False), ("|  ~ —", False), ("1.", False),
                                          ("Mich@el L0ng", True), ("Bill Kimb   h", True)])
def test_only_a_name_with_a_defect_marks_the_header_garbled(line, garbled):
    lines = ["MEMBERS PRESENT:", "Wade Hadley", line, "Bryce Powers", "STAFF PRESENT:", "Jeff Tyndall"]
    members, got = R.members_header(lines)
    assert got is garbled
    if "CALL TO ORDER" in line:
        assert members == ["Wade Hadley"]          # the header's list stops at the call to order
    else:
        assert members == ["Wade Hadley", "Bryce Powers"]


def _agenda_page(numbers):
    return "October 27, 2026\n" + "".join(f"{k}. {n.replace('-', ' - ')} OWNER(S): Owner {k}\n"
                                          for k, n in enumerate(numbers, 1))


MINUTES_TEXT = ("REGIONAL PLANNING COMMISSION MINUTES\nOctober 27, 2026\nMEMBERS PRESENT:\nWade Hadley\nBryce Powers\n"
                "Stacey Streetman\nSTAFF PRESENT:\nJeff Tyndall\nThe meeting was called to order.\n"
                "Mr. Hadley made a motion to approve the minutes. Mr. Powers seconded. Motion passed.\n"
                "CASE NUMBER: Z-1-2026\n" + MOVED + "Motion passed.\n"
                "CASE NUMBER: ZO-4-2024\n" + MOVED + "Motion passed.\n"
                "CASE NUMBER: Z-2-2026\n" + MOVED + "Motion passed.\n"
                "CASE NUMBER: Z-2-2026\nMrs. Streetman made a motion to defer. Mr. Powers seconded. Motion passed.\n"
                "CASE NUMBER: Z-3-2026\n" + MOVED + "Motion passed. Mrs. Streetman made the motion for approval. "
                "Mr. Hadley seconded. Motion passed.\n")


@pytest.fixture()
def attached(tmp_path, monkeypatch):
    # rule 11: these minutes (2026-10-27) count as checked, so the attach rules are what is tested
    monkeypatch.setattr(R, "CHECKED_THROUGH", "2026-10-27")
    return _attach(tmp_path)


def _attach(tmp_path):
    cfg = rpc.load_config()
    a_url, m_url = "https://www.cmcrpc.com/a-10-27-2026.pdf", "https://www.cmcrpc.com/m-10-27-2026.pdf"
    rows = rpc.assign_ids([{"date": "2026-10-27", "label": "RPC", "printed": "10/27/2026", "kind": "regular",
                            "cancelled": False, "no_doc": [],
                            "docs": [{"kind": "agenda", "url": a_url, "host": "www.cmcrpc.com", "fetch": True},
                                     {"kind": "minutes", "url": m_url, "host": "www.cmcrpc.com", "fetch": True}]}])
    store = Store(manifest_path=tmp_path / "manifest.json", root=tmp_path / "store")
    store.put(a_url, b"%PDF a", {}, {"kind": "agenda"})
    store.put(m_url, b"%PDF m", {}, {"kind": "minutes"})
    texts = {store.latest(a_url)["sha256"]: [_agenda_page(["Z-1-2026", "Z-2-2026", "Z-3-2026", "Z-7-2026",
                                                            "Z-8-2026", "Z-9-2026"])],
             store.latest(m_url)["sha256"]: [MINUTES_TEXT]}
    audit = tmp_path / "build" / "rpc-motions-audit.jsonl"
    facts, summary = rpc_agenda.build(cfg, rows, store, extract=lambda p: texts[p.stem], audit_path=audit)
    return facts, summary, audit


def test_attach_places_a_motion_under_its_case_only_while_nothing_doubts_the_case(attached):
    facts, summary, _ = attached
    by_case = {}
    for mv in facts["motions"]:
        by_case.setdefault(mv["case"], []).append(mv)
    assert [(mv["kind"], mv["confirmed"], mv["case_id"]) for mv in by_case[None]] == \
        [("Motion to approve the minutes", True, None)]
    z1 = by_case["Z-1-2026"][0]
    assert z1["confirmed"] and z1["case_id"] == "2026-10-27-regular-z-1-2026"
    off = by_case["ZO-4-2024"][0]      # read cleanly, but not on this meeting's agenda
    assert not off["confirmed"] and off["case_id"] is None and R.WHY_OFF_AGENDA in off["reasons"]
    assert len(by_case["Z-2-2026"]) == 2 and all(not mv["confirmed"] and mv["case_id"] is None
                                                 and R.WHY_REPEATED in mv["reasons"] for mv in by_case["Z-2-2026"])
    assert len(by_case["Z-3-2026"]) == 2 and all(not mv["confirmed"] and mv["case_id"] is None
                                                 and R.WHY_TWO in mv["reasons"] for mv in by_case["Z-3-2026"])
    assert summary["motions_confirmed"] == 2 and summary["motions_on_agenda_cases"] == 1
    assert summary["motions_not_confirmed_by_reason"] == {R.WHY_REPEATED: 2, R.WHY_TWO: 2, R.WHY_OFF_AGENDA: 1}
    assert any("the minutes read 5 case headings, the agenda lists 6 cases" in p for p in summary["problems"])


def test_the_build_writes_the_readers_motion_rules_into_the_record(attached):
    facts, summary, _ = attached
    assert facts["motion_rules"] == R.MOTION_RULES == "rpc-motion-invariant-6"
    assert facts["schema"] == "rpc-1"          # the record's layout is unchanged; only the rules it was read by
    assert facts["checked_through"] == R.CHECKED_THROUGH


# rule 11, the safety gate: minutes of a meeting after CHECKED_THROUGH (added by the daily collector after launch) are
# never confirmed, whatever the reader makes of them; the date sits in one place and the build writes it
def test_the_committed_record_confirms_nothing_after_the_gate_date():
    import json
    from pathlib import Path
    facts = json.loads((Path(__file__).resolve().parents[2] / "data/localities/cmc-rpc/rpc.json")
                       .read_text(encoding="utf-8"))
    assert facts["checked_through"] == R.CHECKED_THROUGH
    dates = {m["id"]: m["date"] for m in facts["meetings"]}
    late = [mv for mv in facts["motions"] if dates[mv["meeting_id"]] > R.CHECKED_THROUGH]
    assert all(not mv["confirmed"] and R.WHY_UNCHECKED in mv["reasons"] for mv in late)


def test_motions_of_minutes_after_the_gate_date_are_never_confirmed(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "CHECKED_THROUGH", "2026-10-26")      # the day before these minutes' meeting
    facts, summary, _ = _attach(tmp_path)
    assert facts["checked_through"] == "2026-10-26"
    assert facts["motions"] and not any(mv["confirmed"] for mv in facts["motions"])
    assert all(R.WHY_UNCHECKED in mv["reasons"] for mv in facts["motions"])
    assert summary["motions_confirmed"] == 0 and summary["motions_not_confirmed_by_reason"][R.WHY_UNCHECKED] == 7
    z1 = next(mv for mv in facts["motions"] if mv["case"] == "Z-1-2026")
    # not a doubt about the case: placed under it, shown as not confirmed with the page link like any withheld vote
    assert z1["case_id"] == "2026-10-27-regular-z-1-2026" and z1["reasons"] == [R.WHY_UNCHECKED]
    assert R.WHY_UNCHECKED not in R.CASE_REASONS


def test_motions_of_minutes_on_the_gate_date_are_read_as_before(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "CHECKED_THROUGH", "2026-10-27")
    facts, summary, _ = _attach(tmp_path)
    assert summary["motions_confirmed"] == 2 and R.WHY_UNCHECKED not in summary["motions_not_confirmed_by_reason"]


def test_the_motions_audit_is_internal_one_line_per_motion(attached, tmp_path):
    import json
    facts, _, audit = attached
    rows = [json.loads(x) for x in audit.read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in rows] == [mv["id"] for mv in facts["motions"]]
    assert all(set(r) == {"id", "source_id", "page", "confirmed", "reasons", "para", "lead"} and r["para"] for r in rows)
    assert not any("lead" in mv for mv in facts["motions"])       # nor the text before them (rule 10c)
    assert not any("para" in mv for mv in facts["motions"])       # the sentences never go into rpc.json
    with pytest.raises(ValueError, match="never written into a built site"):
        rpc_agenda.write_audit(tmp_path / "build" / "site" / "audit.jsonl", rows)


# rpc-votes/recall-miss (QA 2026-11-11): "All others voted in favor and the motion passed ..." and a count of days in
# the outcome's words, from the real sentences (2024-09-24 minutes p3; 2024-02-27 minutes p7)
@pytest.mark.parametrize("text,kind,outcome", [
    ("Bill Kimbrough made a motion for a 30 day deferral, seconded by Jeff Henley. All others voted\n\n"
     "in favor and the motion passed for a 30 day deferral.", "Motion to defer",
     "the motion passed for a 30 day deferral"),
    ("Bill Kimbrough made the motion for approval based on the staff’s recommendation. Jeff Henley\n"
     "seconded. All others were in favor and motion for approval passed.", "Motion for approval",
     "motion for approval passed"),
])
def test_in_favor_and_the_motion_passed_is_read(text, kind, outcome):
    m = _one("CASE NUMBER: Z-5-2026\n" + text, ("Bill Kimbrough", "Jeff Henley", "Stacey Streetman"))[0]
    assert (m.kind, m.outcome, m.confirmed) == (kind, outcome, True), m.reasons


@pytest.mark.parametrize("votes", ["All others voted in favor and the motion passed for a 30 day deferral 5-1.",
                                   "All others voted in favor and the motion passed for approval 5-1-0.",
                                   "All others voted in favor and the motion was discussed further."])
def test_a_tally_is_never_swallowed_into_the_outcome_words(votes):
    m = _case(MOVED + votes)[0]
    assert not m.confirmed, (m.outcome, m.tally, m.reasons)
    assert m.outcome is None or "5-1" not in m.outcome or m.tally == "5-1"


# rpc-votes/outcome-not-printed controls: the rest of an "in favor" sentence with no exception, member or vote word
# keeps it the outcome as printed (real sentences, 2025-04-22 minutes p33 and 2025-06-24 minutes p1)
@pytest.mark.parametrize("text", [
    "Valerie Guzman made a motion to adjourn, seconded by Bill Kimbrough. All others voted in favor, meeting was "
    "adjourned at 4:48 p.m.",
    "Bill Kimbrough made a motion to approve the deferrals, seconded by Charlie Patterson. All members voted in favor, "
    "cases were approved for deferrals.",
])
def test_an_in_favor_sentence_that_goes_on_with_no_exception_stays_the_outcome(text):
    m = _one(text, ("Valerie Guzman", "Bill Kimbrough", "Charlie Patterson"))[0]
    assert m.outcome is not None and m.outcome.lower().startswith("all ") and m.confirmed, (m.outcome, m.reasons)
