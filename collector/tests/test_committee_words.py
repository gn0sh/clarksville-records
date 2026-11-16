"""The committee words gate (docs/architecture/committee-words-invariant.md): collector/committee_words.py, and its
independent restatement in qa/site_checks.py (CmWords), must agree. Every name in these cases is made up, except
officials on the roster."""
import json
from pathlib import Path

import pytest
import yaml

from collector import committee_words as W
from qa import site_checks

ROOT = Path(__file__).resolve().parents[2]
QA = site_checks.CmWords(W.WORDS_PATH)
CM_JSON = ROOT / "data" / "localities" / "clarksville-tn" / "committees" / "committees.json"

# The security reviews' phrasings (2026-11-16, both rounds), with made-up names: none may be published.
REVIEWERS = [
    'to approve payment to Zelda Quarmby in the amount of $1,200',
    'to approve the payment to zelda quarmby',
    'to approve a check to Zelda Quarmby for damages',
    'to pay Zelda Quarmby $2,500 for sewer backup damage',
    'to approve the claim of Zelda Quarmby',
    'Claim — Zelda Quarmby',
    'Claim: zelda quarmby',
    'Sewer backup claim (Zelda Quarmby) $3,000',
    'to approve the sewer backup claim for Mr. Quarmby',
    "to deny Mr. Quarmby's claim",
    "to approve Mrs. Van Der Berg's request",
    'to settle the matter with Mary Smith-Jones',
    'to approve the settlement with Mary Smith-Jones',
    'to approve the refund to Smith-Jones Properties LLC',
    "to approve the refund for O'Brien",
    'to approve the settlement in Quarmby v. City of Clarksville',
    'to approve settling the case brought by Zelda Quarmby',
    'Zelda Quarmby, damages to vehicle, $800 - approve',
    "to approve damages to Zelda Quarmby's vehicle",
    'to approve compensation for Zelda Quarmby',
    'to approve the tort payment of $5,000 to the Estate of Zelda Quarmby',
    'Council Member Zelda Quarmby moved to approve the claim',
    'to approve the claim as recommended by Councilman Henley and Mr. Quarmby',
    'to approve the agreement with Zelda Quarmby for the easement',
    'to approve the purchase of property from Zelda Quarmby',
    'to accept the offer from Zelda Quarmby',
    'to approve the request from Zelda Quarmby for a payment plan',
    'to approve the payment plan for Zelda Quarmby',
    'to approve forgiveness of the utility debt of Zelda Quarmby',
    'to approve the utility bill adjustment for Zelda Quarmby',
    'to approve the adjustment to the account of 123 Elm St',
    'to approve the request by zelda quarmby',
    'regarding the claim made by de la Cruz',
    'settlement with the family of Zelda Quarmby',
    'settlement - ZELDA QUARMBY',
    'SETTLEMENT DEMAND – ZELDA QUARMBY',
    'to approve the workers comp settlement for employee Zelda Quarmby',
    "to approve the workers' compensation settlement for officer Quarmby",
    'Workers Compensation - Zelda Quarmby',
    'to approve the severance for Zelda Quarmby',
    'to approve the retirement of Zelda Quarmby',
    'to approve the step increase for Zelda Quarmby',
    'the minor child of Zelda Quarmby',
    'to approve the payment of medical bills for Zelda Quarmby',
    'to approve the settlement with Grant Parks',
    'to approve the refund to Grant Case',
    'to approve the settlement as recommended by Attorney Zelda Quarmby, counsel for the plaintiff',
    'to approve the claim, Councilman Henley abstaining, Zelda Quarmby $500',
    'to approve the claim per Director Smith for Zelda Quarmby',
    'to approve the refund to LEE',
    'settlement - JO LEE',
    'to approve the claim; payee: Zelda Quarmby',
    'Claim — Zelda Quarmby-Smith',
    'Claim — Mary Ann Van Buren',
    'Claim of Mary Ann Van Buren',
    'to approve the reimbursement to zelda for mileage',
    'to approve the settlement with the Quarmby family',
    'to approve the petition from the residents of Elm Street',
    'to approve the settlement (Quarmby)',
    'Settlement Demand (Zelda Quarmby v. City)',
    'Quarmby vs. City of Clarksville, et al - settlement',
    'QUARMBY, ET AL. V. CITY OF CLARKSVILLE',
    'Zelda Quarmby and John Doe v. City',
    'Claim made by Dr. Zelda Quarmby',
    'Claim made by the Quarmby-Smith Trust',
    'to approve the payment to McDonald for the claim',
    "to approve the settlement with McDonald's",
    'to approve the settlement with ACME Holdings, LLC',
    'to approve the refund to the store manager Zelda Quarmby',
    "to approve the settlement with the claimant's attorney Zelda Quarmby",
    'to approve the claim of the retired clerk, Zelda Quarmby',
    'to approve the payment to Judge Zelda Quarmby',
    'to approve the reimbursement for Director Zelda Quarmby',
    'refund to the treasurer Zelda Quarmby of the HOA',
    'to approve the claim - Chief Zelda Quarmby',
    'to approve the settlement for family member Zelda Quarmby',
    'to approve the settlement with Zelda Quarmby (Council Member Henley abstained)',
]
EXTRA = [
    "approve payment to Zelda Quarmby", "settle with Zelda Quarmby", "Zelda Quarmby's request",
    "the Quarmby settlement", "claim made by zelda quarmby", "appeal of Zelda Quarmby",
    "regarding the claim, Zelda Quarmby, $2,500", "to pay Zelda Quarmby $2,500", "to pay zelda quarmby $2,500",
    "Estate of Zelda Quarmby", "to approve the tort payment to the Estate of Zelda Quarmby",
    "compensation for Zelda Quarmby", "to approve compensation for zelda", "Grant Parks settlement",
    "to approve the settlement with Grant Parks", "to approve the settlement with grant parks",
    "to approve payment to Z. Q.", "to approve the refund to ZQ", "the Parks claim", "to approve payment to April",
    "to approve the settlement with May Quarmby", "to approve payment to June Quarmby", "to pay Justice Quarmby",
    "Council Member Zelda Quarmby moved to approve", "to approve the request of Mr. Henley",
    "ORDINANCE 12-2025-26 An Ordinance accepting the donation of real property from Zelda Quarmby",
    "ORDINANCE 12-2025-26 An Ordinance accepting the donation of real property from the Quarmby Family Trust",
    "ORDINANCE 12-2025-26 An Ordinance rezoning land on the application of Zelda Quarmby",
    "RESOLUTION 12-2025-26 A Resolution approving the settlement with Zelda Quarmby",
    "RESOLUTION 12-2025-26 A Resolution donating a retired dog to Police Officer, Zelda Quarmby",
    "RESOLUTION 12-2025-26 A Resolution for the grant: Zelda Quarmby",
    "Write-off Authorization: 12 Example Dr.", "Travel Waivers 1. Zelda Quarmby 2. Lee Example",
]
# The third security review (committees-privacy hit 3), made-up names: M1 legislation-free-words, L3 name-vocabulary,
# L4 ascii-tokens
HIT3 = [
    # M1: a capitalised word anywhere in legislation must be allow-listed
    "Resolution 5-2025-26 appointing John Doe and Jane Roe to the Housing Authority",
    "RESOLUTION 5-2025-26 A Resolution appointing Zelda Quarmby to the Board",
    "ORDINANCE 12-2025-26 An Ordinance naming the park in honor of Zelda Quarmby",
    "ORDINANCE 12-2025-26 An Ordinance, Zelda Quarmby, approve",
    "BID 1-2025-26 Quarmby Paving",
    "RESOLUTION 5-2025-26 appointing ZELDA QUARMBY",
    # L3: words that are also names
    "to approve payment to Al Quarmby", "Al Quarmby", "to approve the Court settlement", "Fine Quarmby",
    "Early Quarmby", "Minor Quarmby", "More Quarmby", "Main Quarmby", "Plant Quarmby", "Card Quarmby",
    "Sale Quarmby", "Back Quarmby", "Urban Quarmby", "to approve the claim of Al", "approve payment to Urban",
    "for Court", "Court Quarmby et al",
    # L4: Unicode, spelled-out letters, Roman numerals
    "José Núñez", "to approve the minutes, José Núñez", "Resolution 5-2025-26 appointing José Núñez",
    "to approve Ζέλδα", "to approve 李明", "Zelda\u200bQuarmby", "to approve Ze\u0301lda",
    "J O H N D O E", "to approve the minutes J O H N D O E", "J. Q.", "to approve the refund to J. Q. Doe",
    "approve the minutes, J.Q.", "Xi", "Vi", "to approve Xi", "the Vi plan", "Vi. Quarmby", "Ii",
]
# The fourth security review (2026-11-16, PASS WITH LOWS), made-up uses of real surnames that were in `words`
# (L1 name-vocabulary) and initials before a word (L2 lone-initial): withheld by the gate and by QA
HIT4 = [
    "A Resolution appointing J. Bonds to the Industrial Development Board", "Settlement J. Bonds",
    "approve claim (J. East)", "approve claim J-P Prior", "J/Q Bonds", "plaintiff J. Bonds",
    "approve contract with Block Construction", "Bonds v. City of Clarksville", "V. Q. Prior settlement",
    "Settlement J. Industrial", "approve claim J.-Q. Industrial", "approve claim J_Q", "settlement - BRIDGE",
    "to approve the claim of Holiday", "Reading settlement", "Hazard claim", "approve payment to Fort",
    "claim Ж. Industrial",   # committees-privacy/qa-initial-ascii: QA reads any script's capital initial
]
# Public words that must still be published (agreement, and the gate is not a blanket refusal)
ALLOWED = [
    "to approve the minutes", "to approve the claim", "to reject the settlement demand per the advice of the City Attorney",
    "to forward this ordinance to the City Council with a recommendation of approval",
    "to postpone to the August meeting", "to adopt the May 26, 2020 minutes", "for the grant application",
    "to approve the amendment as recommended by Councilman Henley", "Councilperson Karen Reynolds",
    "The following vote was recorded: AYE: Holleman, Knight, Redd, Reynolds, Streetman The motion passed.",
    "A voice vote was taken; Councilman Henley voted \u201cnay.\u201d The motion passed.",
    "ORDINANCE 31-2024-25 (First Reading) An ordinance to amend the Official Code of the City of Clarksville, Title 1",
    "RESOLUTION 22-2024-25 A Resolution authorizing an Interlocal Agreement between the City of Clarksville and "
    "Montgomery County", "Parks and Recreation", "FY25 Budget Review",
    # hit 3: the real uses kept by phrases and the Roman rule
    "RESOLUTION 35-2024-25 A City of Clarksville Resolution requesting the State of Tennessee Department of "
    "Transportation fully fund a pedestrian bridge crossing over State Route 374 at S. Jordan and Jordan Rd.",
    "Title VI", "Phase II", "IV. ADOPTION OF MINUTES", "VIII. COMMITTEE ACTION REQUIRED",
    "TODD COUNTY FISCAL COURT AGREEMENT",
    "SALE OF SURPLUS PROPERTY", "CTS CREDIT CARD FEES", "the sale of the property", "to the start of early voting",
    "the City of Clarksville et al",
    # L1/L2 (fourth review): the real capitalised uses kept by phrases, and letters next to digits
    "ORDINANCE 31-2024-25 (FIRST READING)", "ORDINANCE 30-2024-25 (First Reading) An Ordinance for the donation",
    "WATER, SEWER, GAS BONDS", "JUNETEENTH CITY HOLIDAY", "JUNETEENTH HOLIDAY FUNDING",
    "2025 Montgomery County Natural Hazard Mitigation Plan", "FORT CAMPBELL MOU", "RED RIVER PEDESTRIAN BRIDGE",
    "EAST MONTGOMERY UTILITY DISTRICT", "Community Development Block Grant Funds", "E911 INTERLOCAL AGREEMENT",
    "K-9 DONATION", "utility relocation at SR-237 (Rossview Rd) from east of International Blvd to east of Kirkwood Rd",
    "the bonds for the prior year", "on the holiday", "a hazard on the bridge", "before the second reading",
]


@pytest.mark.parametrize("text", REVIEWERS + EXTRA + HIT3 + HIT4)
def test_reviewer_phrasings_are_never_published(text):
    assert not W.publishable(text) and not QA.words_ok(text)


@pytest.mark.parametrize("text", ALLOWED)
def test_public_words_are_published_by_both(text):
    assert W.publishable(text) and QA.words_ok(text)


@pytest.mark.parametrize("name, ok", [
    ("Councilman Henley", True), ("Henley", True), ("Councilperson Karen Reynolds", True), ("Jeff Henley", True),
    ("Dr. Jennifer Thayer", True), ("Mr. Quarmby", False), ("Dr. Zelda Quarmby", False), ("Zelda Quarmby", False),
    ("Councilman Quarmby", False), ("Ms. Smith", False), ("Mayor Quarmby", False)])
def test_printed_names_only_from_the_roster(name, ok):
    assert W.roster_name(name) is ok and QA.name_ok(name) is ok


def test_vocabulary_holds_no_name_words():
    y = yaml.safe_load(W.WORDS_PATH.read_text(encoding="utf-8"))
    words = {w.casefold() for w in y["words"]}
    assert all(isinstance(w, str) for k in ("words", "lowercase_only", "phrases", "titles") for w in y[k])
    # never words: given names and surnames that the minutes print (the vocabulary is curated by hand), the months
    # that are names, titles anyone can hold, and organisation suffixes
    never = {"march", "april", "may", "june", "august", "mr", "mrs", "ms", "dr", "llc", "inc", "grant", "park",
             "parks", "will", "chase", "field", "street", "river", "justice", "jeff", "lance", "stephanie", "rod",
             "montgomery", "davidson", "le", "look",
             # hit 3 (L3): words that are also names
             "al", "early", "fine", "court", "minor", "more", "main", "plant", "card", "sale", "back", "urban",
             "jordan",
             # fourth review (L1): surnames that were words
             "bonds", "block", "prior", "holiday", "east", "hazard", "reading", "fort", "bridge"}
    assert not words & never
    assert not words & {o["surname"].casefold() for o in y["officials"]}


COMMON_NAMES = site_checks.CM_NAMES_PATH


def _common_names() -> set[str]:
    return {n.casefold() for line in COMMON_NAMES.read_text(encoding="utf-8").splitlines() if not line.startswith("#")
            for n in line.split()}


def test_vocabulary_holds_no_common_us_name():
    """L1 (fourth review): no word of `words` (published in any case) is a common US surname or given name. The list
    (qa/common-us-names.txt, from public-domain Census surname and SSA given-name counts) is the one QA denies."""
    names = _common_names()
    assert len(names) >= 1000
    assert {"smith", "johnson", "bonds", "prior", "east", "holiday", "block", "grant", "may", "will"} <= names
    y = yaml.safe_load(W.WORDS_PATH.read_text(encoding="utf-8"))
    assert sorted({w.casefold() for w in y["words"]} & names) == []


def test_initials_and_names_fail_even_if_a_name_were_a_word(tmp_path):
    """L2/L4: the gate's initial rule and QA's initial rule and names deny-list do not depend on `words`: with the
    surnames put back in `words`, the attack strings are still withheld by both."""
    y = yaml.safe_load(W.WORDS_PATH.read_text(encoding="utf-8"))
    back = {"bonds", "prior", "east", "industrial"}
    y["words"] = sorted(set(y["words"]) | back)
    y["lowercase_only"] = [w for w in y["lowercase_only"] if w not in back]
    p = tmp_path / "words.yml"
    p.write_text(yaml.safe_dump(y), encoding="utf-8")
    allow, qa = W.parse_allow(y), site_checks.CmWords(p)
    initials = ["A Resolution appointing J. Bonds to the Industrial Development Board", "Settlement J. Bonds",
                "approve claim (J. East)", "plaintiff J. Bonds", "Settlement J. Industrial", "V. Q. Prior settlement",
                "approve claim J-P Prior", "J/Q Bonds"]
    for t in initials:
        assert not W.publishable(t, allow) and not qa.words_ok(t), t
    for t in ["Bonds settlement", "the claim of Prior", "EAST"]:   # QA's deny-list alone
        assert W.publishable(t, allow) and not qa.words_ok(t), t


def test_every_roster_name_has_its_source():
    y = yaml.safe_load(W.WORDS_PATH.read_text(encoding="utf-8"))
    council = json.loads((ROOT / "data" / "localities" / "clarksville-tn" / "facts.json").read_text(encoding="utf-8"))
    council_names = {o["name"] for o in council["officials"]}
    att = {p["name"] for m in json.loads(CM_JSON.read_text(encoding="utf-8"))["meetings"] if m.get("attendance")
           for p in (m["attendance"]["present"] or []) + (m["attendance"]["absent"] or [])}
    for o in y["officials"]:
        assert o["source"] in ("council", "committee"), o
        if o["source"] == "council":
            assert o["name"] in council_names, o
        else:
            assert {o["name"], *(o.get("aliases") or [])} & att, o


def test_committed_record_holds_only_allow_listed_text():
    """The invariant on the committed committees.json, checked with the QA restatement (not the collector's code):
    every words field passes the words rule, every printed name is on the roster, reasons are codes."""
    from collector.committees import REASON_CODES
    d = json.loads(CM_JSON.read_text(encoding="utf-8"))
    codes = {c for _, c in REASON_CODES} | {"other", "name-not-on-roster"}
    for x in d["motions"]:
        for k in ("section", "subject_printed", "motion_printed"):
            assert not x.get(k) or QA.words_ok(x[k]), (x["id"], k)
        v = x.get("vote") or {}
        assert not v.get("outcome_printed") or QA.words_ok(v["outcome_printed"]), x["id"]
        for k in ("mover_printed", "seconder_printed"):
            assert not x.get(k) or QA.name_ok(x[k]), (x["id"], k)
        assert all(QA.name_ok(n) for k in ("ayes_printed", "nays_printed") for n in v.get(k) or []), x["id"]
        assert set(x["reasons"]) <= codes, x["id"]
        if x.get("words_withheld"):
            assert x["words_note"] == W.WORDS_NOTE and all(x.get(k) is None or k == "outcome_printed"
                                                           for k in x["words_withheld"])
    for m in d["meetings"]:
        assert QA.words_ok(m["title"]) and all(QA.words_ok(doc["name"]) for doc in m["documents"]), m["id"]
        for p in ((m.get("attendance") or {}).get("present") or []) + ((m.get("attendance") or {}).get("absent") or []):
            assert QA.name_ok(p["name"]) and QA.words_ok(p.get("note") or ""), m["id"]


def test_qa_is_stricter_than_the_gate():
    """QA never passes a text the gate withholds; a "," is a strict mark in QA only."""
    for t in REVIEWERS + EXTRA + HIT3 + HIT4 + ALLOWED + ["the plan, grant parks", "the plan, Grant"]:
        assert not QA.words_ok(t) or W.publishable(t), t
    assert W.publishable("the plan, grant parks") and not QA.words_ok("the plan, grant parks")


def test_qa_reason_codes_are_the_collectors():
    from collector.committees import REASON_CODES
    assert site_checks.CM_REASON_CODES == {c for _, c in REASON_CODES} | {"other", "name-not-on-roster"}


def test_every_committed_committee_string_passes_qa():
    """L5: every string field of committees.json, listing.json and the manifest labels, by class (QA's walk), not
    only what the pages render today."""
    d = json.loads(CM_JSON.read_text(encoding="utf-8"))
    assert site_checks.cm_string_problems(d, QA, "committees.json") == []
    listing = json.loads((CM_JSON.parent / "listing.json").read_text(encoding="utf-8"))
    assert site_checks.cm_string_problems(listing, QA, "listing.json", {"kind": r"[a-z]+"}) == []
    manifest = json.loads((CM_JSON.parent / "manifest.json").read_text(encoding="utf-8"))
    assert site_checks.cm_string_problems([{"label": e["label"]} for e in manifest], QA, "manifest.json") == []


@pytest.mark.parametrize("path, value", [
    (("motions", 0, "item"), "Zelda Quarmby"), (("motions", 0, "reasons"), ["zelda-quarmby"]),
    (("motions", 0, "words_note"), "Withheld: Zelda Quarmby"), (("motions", 0, "vote"), {"method": "Quarmby"}),
    (("motions", 0, "mover"), "Quarmby"), (("motions", 0, "remark"), "Zelda Quarmby"),
    (("motions", 0, "section"), "Resolution 5-2025-26 appointing John Doe and Jane Roe to the Housing Authority"),
    (("meetings", 0, "title"), "Finance Committee: Zelda Quarmby"),
    (("meetings", 0, "documents"), [{"name": "Quarmby claim", "kind": "minutes"}]),
    (("meetings", 0, "attendance"), {"present": [{"name": "Zelda Quarmby"}]}),
    (("meetings", 0, "id"), "2024-01-01-finance Quarmby"),
])
def test_qa_walk_rejects_a_bad_string_in_any_field(path, value):
    rec = {"motions": [{"id": "2024-01-01-finance-motion-1", "reasons": []}],
           "meetings": [{"id": "2024-01-01-finance", "title": "Finance Committee"}]}
    *head, last = path
    o = rec
    for k in head:
        o = o[k]
    o[last] = value
    assert site_checks.cm_string_problems(rec, QA, "x") != []
    assert not any("Quarmby" in p or "Doe" in p for p in site_checks.cm_string_problems(rec, QA, "x"))


def test_listing_titles_are_gated_before_they_are_written():
    from collector.committees import gate_listing_row
    row = {"title": "Finance Committee: settlement with Zelda Quarmby", "agenda_name": "12a-Finance Agenda 4-4-19",
           "minutes_name": "Zelda Q. minutes", "body": "Finance Committee", "kind": "finance"}
    out = gate_listing_row(row)
    assert out["title"] == "Finance Committee meeting" and out["minutes_name"] == "Minutes"
    assert out["agenda_name"] == row["agenda_name"] and out["words_replaced"] == ["title", "minutes_name"]
    assert site_checks.cm_string_problems([out], QA, "listing.json", {"kind": r"[a-z]+"}) == []
    assert gate_listing_row({**row, "title": "Finance Committee", "minutes_name": None}) == \
        {**row, "title": "Finance Committee", "minutes_name": None}
