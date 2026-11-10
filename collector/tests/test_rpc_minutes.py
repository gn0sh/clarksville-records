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
    minutes = by_case[None][0]
    assert (minutes.mover, minutes.seconder, minutes.outcome, minutes.confirmed) == \
        ("Mrs. Streetman", "Mr. Kimbrough", "carried unanimously", True)
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


def test_named_nay_and_abstention_after_except():
    roster = ["Charlie Patterson", "Stacey Streetman", "Cindy Greene", "Bill Kimbrough"]
    r = R.read_minutes(pages("minutes_2025-06-24_p17_ocr.txt"), set(), PREFIXES, roster)
    m = r.motions[0]
    assert (m.mover, m.seconder, m.nays, m.abstained) == ("Charlie Patterson", "Stacey Streetman",
                                                          ["Bill Kimbrough"], ["Cindy Greene"])
    assert m.outcome == "All members voted in favor" and m.confirmed      # rule 2a: names from the roster


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
    m = _one("Stacey Streetman made a motion for disapproval. Motion falls for a lack of a second. Mr. Long asked.")[0]
    assert m.seconder is None and m.outcome == "Motion falls for a lack of a second" and m.confirmed


def test_motions_after_other_business_or_to_adjourn_belong_to_no_case():
    ms = _one("CASE NUMBER: Z-5-2026 APPLICANT: A\nMr. Hadley made the motion for approval. Mr. Powers seconded. "
              "Motion passed.\nOTHER BUSINESS:\nMr. Long made the motion to approve the P & L. Mr. Powers seconded. "
              "Motion passed.\nMr. Long made a motion to adjourn, seconded by Mr. Powers. All members voted in favor.")
    assert [(m.case, m.kind) for m in ms] == [("Z-5-2026", "Motion for approval"), (None, "Motion for approval"),
                                             (None, "Motion to adjourn")]
    assert all(m.confirmed for m in ms)


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
