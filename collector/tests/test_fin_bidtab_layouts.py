"""Slice 1a-2: the bid-tab layouts found by the census on real data (collector/fin_bidtab.py).

Each layout has a regression test on a trimmed real `pdftotext -bbox` fixture (collector/tests/fixtures/finance/):
- table, "Bidder Name | Lump Sum Bid" with colon labels: FDR Ironhorse Way;
- table, colon labels with fill ("Department:___Sheriff's Office"), awardee named: MCSO fire panel;
- table, "Bidder Name | Total Bid": Sheriff's Office vehicle equipment;
- blocks, "Contractor | Bid Bond | Bid Amount", base bid only, a name wrapped below its amount: Courts Center generator;
- blocks with alternates and a printed "Total Bid:", label and amount on separate lines, no addendum column:
  generator electrical alteration;
- blocks with names wrapped around the tick line: 2174 Rossview Road demolition;
- blocks with a name that runs into its "Base Bid:" line and tick glyphs: interior renovations;
- blocks with a "NON RESPONSIVE" bidder: not read; the same tab without that block reads (four-line name join).
Problem keys: award-source/*, scan-values/*, bidtab-layout/*.
"""
import pytest

from collector import fin_checks
from collector.fin_bidtab import read_bidtab
from collector.fin_facts import doc_id
from collector.tests.fin_fake import CFG, FIX, FakeFin, url_ending, words

RULES = CFG.bidtab


def fixture(name: str) -> str:
    return (FIX / f"{name}.bbox.html").read_text(encoding="utf-8")


def read(name: str):
    return read_bidtab(words(fixture(name)), RULES)


def rows(r):
    return [(b.printed_order, b.name, b.total_as_printed, b.total_cents, b.page) for b in r.bidders]


def test_lump_sum_bid_header_and_colon_labels():
    r = read("fdr_ironhorse_bidtab")
    assert (r.tab_type, r.layout, r.held) == ("lump_sum", "table", [])
    assert rows(r) == [(1, "Byrne & Jones Construction", "$1,203,210.00", 120321000, 1),
                       (2, "Estes Bros. Const. Inc.", "$1,188,243.00", 118824300, 1),
                       (3, "Martin Paving Company, Inc", "$803,500.00", 80350000, 1),
                       (4, "Mt. Carmel Stabilization Group", "$839,460.50", 83946050, 1)]
    assert r.fields == {"project": ("Full Depth Reclamation for Ironhorse Way", 1),
                        "department": ("Highway Department", 1), "bid_date": ("10-1-26 at 10 a.m.", 1)}


def test_colon_labels_with_fill_name_department_awardee_and_dates():
    r = read("fire_panel_bidtab")
    assert (r.tab_type, r.layout) == ("lump_sum", "table")
    assert r.fields["department"] == ("Sheriﬀ’s Oﬃce", 1)                     # as printed, ligatures kept
    assert r.fields["project"] == ("Fire Panel Upgrade", 1)
    assert r.fields["bid_date"] == ("11-12-25 at 2 p.m.", 1)
    assert r.fields["awardee"] == ("Integrated Protection Services", 1)
    assert r.fields["award_date"] == ("11-17-25", 1)
    assert [b.name for b in r.bidders] == ["Convergint Technologies", "Integrated Protection Services",
                                           "Southeastern Sound, Inc/Eagle Fire, Inc"]
    assert fin_checks.awardee_match(r.fields["awardee"][0], [b.name for b in r.bidders]) == "bidder:2"


def test_total_bid_header():
    r = read("vehicle_equipment_bidtab")
    assert (r.tab_type, r.layout, r.held) == ("lump_sum", "table", [])
    assert rows(r) == [(1, "Columbia CDJR", "$89,230.00", 8923000, 1), (2, "On-Duty Depot", "$101,850.00", 10185000, 1),
                       (3, "Truckers Lighthouse", "$77,667.80", 7766780, 1)]
    assert fin_checks.awardee_match(r.fields["awardee"][0], [b.name for b in r.bidders]) == "bidder:3"


def test_blocks_base_bid_only():
    r = read("courts_generator_bidtab")
    assert (r.tab_type, r.layout, r.held) == ("lump_sum", "blocks", [])
    assert rows(r) == [(1, "John Bouchard & Sons (JBS)", "$324,600.00", 32460000, 1),
                       (2, "Rubicon Engineering", "$383,000.00", 38300000, 1),
                       (3, "Intech", "$399,500.00", 39950000, 1),
                       (4, "Knight Electric", "$495,720.00", 49572000, 1),
                       (5, "Active Energy Services, LLC", "$506,200.00", 50620000, 1),
                       (6, "Neely Engineering & Contracting", "$550,430.75", 55043075, 1)]   # wrapped below
    assert r.fields == {"project": ("Montgomery Courts Center Generator Replacement Project", 1),
                        "bid_date": ("9/1/2026", 1)}           # "Owner:" is not a department: none is read
    assert "awardee" not in r.fields


def test_blocks_total_bid_is_the_printed_total_and_its_parts_add_up():
    r = read("generator_alteration_bidtab")
    assert (r.tab_type, r.layout, r.held) == ("lump_sum", "blocks", [])
    assert rows(r) == [(1, "Optimal Electric Pro", "$39,915.00", 3991500, 1),
                       (2, "Knight Electric, Inc.", "$62,137.00", 6213700, 1),
                       (3, "Stansell Electric", "$65,811.00", 6581100, 1)]


def test_blocks_total_whose_parts_do_not_add_up_is_held():
    r = read_bidtab(words(fixture("generator_alteration_bidtab").replace(">$3,931.00<", ">$3,932.00<")), RULES)
    assert r.tab_type == "lump_sum"
    assert (r.bidders[0].total_as_printed, r.bidders[0].total_cents) == ("$39,915.00", None)
    assert r.held == [("bid_tab.bidders[0].total_cents", "total-parts")]
    assert r.bidders[1].total_cents == 6213700


def test_blocks_bad_total_token_is_held():
    r = read_bidtab(words(fixture("generator_alteration_bidtab").replace(">$62,137.00<", ">$62,137.0O<")), RULES)
    assert r.tab_type == "lump_sum" and r.bidders[1].total_as_printed == "$62,137.0O"
    assert r.bidders[1].total_cents is None and r.held == [("bid_tab.bidders[1].total_cents", "amount-format")]


def test_blocks_names_wrapped_around_the_tick_line():
    r = read("rossview_demo_bidtab")
    assert (r.tab_type, r.layout, r.held) == ("lump_sum", "blocks", [])
    assert [(b.name, b.total_cents) for b in r.bidders] == [
        ("Providence Builders", 1950000), ("Modern Day Wrecking", 2348000), ("Justice Farms LLC", 6110000),
        ("Workman General Contractors LLC", 6866500), ("Magnum Opus Construction", 7487300)]


def test_blocks_name_on_the_base_bid_line_and_glyph_ticks():
    r = read("interior_renovations_bidtab")
    assert (r.tab_type, r.layout, r.held) == ("lump_sum", "blocks", [])
    assert [(b.name, b.total_cents) for b in r.bidders] == [
        ("MDI Construction", 32404320), ("Providence Builders", 38535000),
        ("Bulley Andrews/Rock City Construction", 61900000), ("Rubicon Construction", 68001031)]


def test_blocks_non_responsive_bidder_is_not_read():
    r = read("vets_hvac_bidtab")
    assert r.tab_type == "not_read" and r.bidders == []
    assert r.reason == "words, not one amount, in the Bid Amount column on page 1: 'NON'"


def test_blocks_without_the_non_responsive_block_reads():
    ws = words(fixture("vets_hvac_bidtab"))
    cut = sorted(w.yc for w in ws if w.text == "Base")[2]            # the third block: Air Temp, NON RESPONSIVE
    r = read_bidtab([w for w in ws if w.yc < cut - 2], RULES)
    assert (r.tab_type, r.layout, r.held) == ("lump_sum", "blocks", [])
    assert [(b.name, b.total_as_printed, b.total_cents) for b in r.bidders] == [
        ("Freeman Mechanical, LLC", "$149,362.00", 14936200), ("Four Seasons Heating & Air", "$176,500.00", 17650000)]


@pytest.mark.parametrize("edit, why", [
    (lambda s: s.replace(">Total</word>", ">Subtotal</word>", 1), "no one printed total"),       # base + alternate
    (lambda s: s.replace(">Amount</word>", '>Amount</word><word xMin="500" yMin="118.62" xMax="520" yMax="131.92">'
                         'Qty</word>', 1), "header has other columns: 'Qty'"),
    (lambda s: s.replace(">Base</word>", ">Basic</word>", 1), "a line before the first 'Base Bid:'"),
])
def test_blocks_other_layouts_are_not_read(edit, why):
    r = read_bidtab(words(edit(fixture("generator_alteration_bidtab"))), RULES)
    assert r.tab_type == "not_read" and why in r.reason and r.bidders == []


def test_blocks_name_lines_far_apart_are_not_joined():
    """A name fragment far below its block's name (a layout these rules do not know) fails loudly, never joins."""
    ws = words(fixture("courts_generator_bidtab"))
    moved = [type(w)(w.page, w.x0, w.x1, w.y0 + 20, w.y1 + 20, w.text) if w.text == "Contracting" else w for w in ws]
    r = read_bidtab(moved, RULES)
    assert r.tab_type == "not_read" and "not adjacent" in r.reason


def test_unit_price_reason_names_the_header():
    """"Bidder Name | Price per Ton" (the salt tabs): a bidder table with no total column is a unit-price layout."""
    bbox = fixture("fdr_ironhorse_bidtab").replace(">Lump</word>", ">Price</word>").replace(">Sum</word>", ">per</word>")
    bbox = bbox.replace('xMin="462.252600" yMin="346.098000" xMax="486.437400" yMax="371.082000">Bid<',
                        'xMin="462.252600" yMin="346.098000" xMax="486.437400" yMax="371.082000">Ton<')
    r = read_bidtab(words(bbox), RULES)
    assert r.tab_type == "not_read" and r.reason == ("no bidder table header with a total column (unit-price "
                                                     "layout): 'Bidder Name Price per Ton'")


def test_block_tab_through_the_build_cites_its_pages(tmp_path, monkeypatch):
    tail = "Bid%20Tab%20-%20Hwy%20Dept%20Rock%20FY27.pdf"
    cases = FakeFin.default_cases()
    cases[tail] = ("text", fixture("courts_generator_bidtab"))
    fin, extras = FakeFin(tmp_path, cases).build(monkeypatch)
    did = doc_id(url_ending(tail))
    (s,) = [s for s in fin["solicitations"] if did in s["document_ids"]]
    t = s["bid_tab"]
    assert t["tab_type"] == "lump_sum" and t["document_id"] == did and len(t["bidders"]) == 6
    assert (t["bid_date_text"], t["bid_date_page"], t["award_date_text"], t["award_date_page"]) == ("9/1/2026", 1,
                                                                                                    None, None)
    assert t["awardee_match"] == "none_named" and s["department"] is None
    assert fin_checks.scan_guard(fin) == []
    assert any(c.cls == "lump_sum" and c.detail == "blocks: 6 bidders" for c in extras["census"])
