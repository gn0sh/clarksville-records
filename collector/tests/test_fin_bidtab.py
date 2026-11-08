"""F5: the bid-tab adapter (collector/fin_bidtab.py) and the scan guard (collector/fin_checks.py).

Regression on the real wheel-loader tab; synthetic variants of it for other layouts and a bad amount token; the scan
guard through fin_facts.build on a fixture store. Keys: award-source/*, scan-values/*.
"""
import copy
import random

import pytest

from collector import fin_checks
from collector.fin_bidtab import cents, read_bidtab
from collector.tests.fin_fake import CFG, WHEEL, FakeFin, itemised, url_ending, words
from collector.fin_facts import doc_id

RULES = CFG.bidtab


def test_wheel_loader_regression():
    r = read_bidtab(words(WHEEL), RULES)
    assert r.tab_type == "lump_sum" and r.reason is None and r.held == []
    assert [(b.printed_order, b.name, b.total_as_printed, b.total_cents, b.page) for b in r.bidders] == [
        (1, "McCoy Construction & Forestry", "$189,000.00", 18900000, 1),
        (2, "Thompson Machinery", "$211,887.00", 21188700, 1)]
    assert r.fields == {"project": ("Wheel Loader", 1), "department": ("Bi-County SWM", 1),
                        "bid_date": ("2-20-25 at 2p.m.", 1), "awardee": ("McCoy Construction &Forestry", 1),
                        "award_date": ("2-26-25", 1)}
    assert fin_checks.awardee_match(r.fields["awardee"][0], [b.name for b in r.bidders]) == "bidder:1"


def test_bidders_keep_printed_order_not_amount_order():
    swapped = WHEEL.replace("$189,000.00", "$299,000.00")
    r = read_bidtab(words(swapped), RULES)
    assert [b.name for b in r.bidders] == ["McCoy Construction & Forestry", "Thompson Machinery"]


@pytest.mark.parametrize("bbox, why", [
    (itemised(), "other columns"),
    (WHEEL.replace(">Notes</word>", ">Unit</word>").replace(">Total</word>", ">Price</word>"), "no bidder table"),
    (WHEEL.replace(">McCoy</word>", "></word>").replace(">Construction</word>", "></word>", 1)
     .replace(">&amp;</word>", "></word>", 1), "total with no bidder name"),
    (WHEEL.replace(">$211,887.00</word>", ">see</word>"), "words, not one amount"),
    (WHEEL.replace(">$211,887.00</word>", '>$211,887.00</word><word xMin="308.0" yMin="318.83" xMax="330.0" '
                   'yMax="337.62">per</word>'), "words, not one amount"),             # "$330.00 per load"
    (WHEEL.replace(">Bidder</word>", ">Vendor</word>"), "no bidder table"),
])
def test_other_layouts_are_not_read(bbox, why):
    r = read_bidtab(words(bbox), RULES)
    assert r.tab_type == "not_read" and why in r.reason and r.bidders == []


def test_dollar_sign_apart_from_the_number_is_held():
    r = read_bidtab(words(WHEEL.replace(">$211,887.00</word>", ">$ 211,887.00</word>")), RULES)
    assert r.tab_type == "lump_sum" and r.bidders[1].total_as_printed == "$ 211,887.00"
    assert r.bidders[1].total_cents is None and r.held == [("bid_tab.bidders[1].total_cents", "amount-format")]


def test_a_bad_amount_token_holds_the_value():
    r = read_bidtab(words(WHEEL.replace(">$211,887.00</word>", ">$211,887.0O</word>")), RULES)
    assert r.tab_type == "lump_sum"
    b = r.bidders[1]
    assert (b.name, b.total_as_printed, b.total_cents) == ("Thompson Machinery", "$211,887.0O", None)
    assert r.held == [("bid_tab.bidders[1].total_cents", "amount-format")]
    assert r.bidders[0].total_cents == 18900000


@pytest.mark.parametrize("token, value", [
    ("$189,000.00", 18900000), ("189,000.00", 18900000), ("$5", 500), ("$1,234", 123400), ("$0.99", 99),
    ("$189,000.0", None), ("$1890,00.00", None), ("$189 000.00", None), ("($5.00)", None), ("$-5.00", None),
    ("$189,000.00.", None), ("", None), ("$1,23", None),
])
def test_amount_format(token, value):
    assert cents(token) == value


@pytest.mark.parametrize("awardee, names, want", [
    ("McCoy Construction &Forestry", ["McCoy Construction & Forestry", "Thompson Machinery"], "bidder:1"),
    ("THOMPSON  MACHINERY.", ["McCoy Construction & Forestry", "Thompson Machinery"], "bidder:2"),
    ("Thompson_Machinery", ["Thompson Machinery"], "bidder:1"),
    ("Gamma Minerals LLC", ["Alpha", "Beta"], "not_a_listed_bidder"),
    ("Alpha", ["Alpha", "alpha."], "ambiguous"),
    ("", ["Alpha"], "none_named"), (None, ["Alpha"], "none_named"), ("___", ["Alpha"], "none_named"),
    ("Thompson Machinery Inc", ["Thompson Machinery"], "not_a_listed_bidder"),     # one normalisation only
])
def test_awardee_match(awardee, names, want):
    assert fin_checks.awardee_match(awardee, names) == want


# ------------------------------------------------------------------ scan guard, through the build
@pytest.fixture
def built(tmp_path, monkeypatch):
    return FakeFin(tmp_path).build(monkeypatch)


def _sol_with_doc(fin, tail):
    did = doc_id(url_ending(tail))
    return [s for s in fin["solicitations"] if did in s["document_ids"]], did


def test_real_tab_is_read_through_the_build(built):
    fin, _ = built
    (s,), did = _sol_with_doc(fin, "Bid%20Tab%20-%20Wheel%20Loader.pdf")
    t = s["bid_tab"]
    assert t["document_id"] == did and t["tab_type"] == "lump_sum" and t["awardee_match"] == "bidder:1"
    assert t["awardee_text"] == "McCoy Construction &Forestry" and t["award_date_text"] == "2-26-25"
    assert (t["bid_date_text"], t["bid_date_page"], t["award_date_page"]) == ("2-20-25 at 2p.m.", 1, 1)
    assert [b["total_cents"] for b in t["bidders"]] == [18900000, 21188700]
    assert s["department"]["text"] == "Bi-County SWM" and s["department"]["page"] == 1


@pytest.mark.parametrize("tail, reason", [
    ("Bid%20Tab%20-%20Sinkhole%20Repair.pdf", "scan"),
    ("Bid%20Tab%20-%20Traffic%20Paint%20FY27.pdf", "scan"),          # OCR text from a scanner
    ("Bid%20Tab%20Sheet.pdf", "shared_url"),
    ("Bid%20Tab%20-%20Hwy%20Dept%20Rock%20FY27.pdf", "layout"),
    ("Bid%20Tab%20-%20Metal%20Pipe%20%26%20Bands%20FY27.docx", "not_pdf"),     # a .docx: not_pdf
])
def test_unreadable_tabs_yield_no_value(built, tail, reason):
    fin, _ = built
    sols, did = _sol_with_doc(fin, tail)
    assert sols
    for s in sols:
        t = s["bid_tab"]
        assert t["tab_type"] == "not_read" and t["not_read_reason"] == reason and t["document_id"] == did
        assert t["bidders"] == [] and t["awardee_text"] is None and t["awardee_match"] is None
        assert t["bid_date_text"] is None and t["bid_date_page"] is None and t["award_date_page"] is None
        assert s["department"] is None and s["held"] == []
    if reason == "shared_url":
        doc = next(d for d in fin["documents"] if d["id"] == did)
        assert len(sols) == 2 and doc["shared_by"] == sorted(s["id"] for s in sols)


def test_scan_guard_passes_and_catches_a_planted_value(built):
    fin, _ = built
    assert fin_checks.scan_guard(fin) == []
    bad = copy.deepcopy(fin)
    scanned = next(d for d in bad["documents"] if d["scanned"])
    good = next(s for s in bad["solicitations"] if s["bid_tab"] and s["bid_tab"]["tab_type"] == "lump_sum")
    good["bid_tab"]["document_id"] = scanned["id"]
    good["document_ids"].append(scanned["id"])
    assert any("scan-values" in p for p in fin_checks.scan_guard(bad))
    shared = copy.deepcopy(fin)
    s = next(x for x in shared["solicitations"] if x["bid_tab"] and x["bid_tab"]["tab_type"] == "lump_sum")
    next(d for d in shared["documents"] if d["id"] == s["bid_tab"]["document_id"])["shared_by"] = ["sol-a", "sol-b"]
    assert any("award-source" in p for p in fin_checks.scan_guard(shared))


@pytest.mark.parametrize("seed", range(12))
def test_property_no_value_cites_a_non_text_source(tmp_path, monkeypatch, seed):
    """scan-values/*: whatever text layer each bid tab has, every value cites a text source."""
    rng = random.Random(seed)
    cases = {tail: (rng.choice(["text", "ocr", "none"]), bbox) for tail, (_, bbox) in FakeFin.default_cases().items()}
    fin, _ = FakeFin(tmp_path, cases).build(monkeypatch)
    src = {s["id"]: s for s in fin["sources"]}
    docs = {d["id"]: d for d in fin["documents"]}
    assert fin_checks.scan_guard(fin) == []
    for where, sid in fin_checks.value_sources(fin):
        assert src[sid]["text_layer"] == "text", where
    for s in fin["solicitations"]:
        t = s["bid_tab"]
        if t and t["tab_type"] == "lump_sum":
            d = docs[t["document_id"]]
            assert src[d["source_id"]]["text_layer"] == "text" and not d["shared_by"]
        elif t:
            assert t["bidders"] == [] and s["department"] is None


def test_words_in_the_notes_column_mean_not_read():
    """A word in an optional column (Notes) was dropped unseen; now the tab is not read (1a nit 7)."""
    note = WHEEL.replace(">$211,887.00</word>", '>$211,887.00</word><word xMin="440.0" yMin="318.83" xMax="470.0" '
                         'yMax="337.62">late</word>')
    r = read_bidtab(words(note), RULES)
    assert r.tab_type == "not_read" and "optional column" in r.reason and r.bidders == []
    assert read_bidtab(words(WHEEL), RULES).tab_type == "lump_sum"        # an empty Notes column is fine


def test_a_name_line_far_below_its_bidder_means_not_read():
    """award-source/name-gap-table: in the table layout a name continuation line must be adjacent (NAME_GAP word
    heights, same page) to the line above it, so a stray line is never joined to a bidder's name (1a nit 8)."""
    far = WHEEL.replace('yMin="301.194960" xMax="124.192428" yMax="319.980480">Forestry',
                        'yMin="401.194960" xMax="124.192428" yMax="419.980480">Forestry')
    r = read_bidtab(words(far), RULES)
    assert r.tab_type == "not_read" and "not adjacent" in r.reason
    assert read_bidtab(words(WHEEL), RULES).bidders[0].name == "McCoy Construction & Forestry"   # 17 pt apart: joined
