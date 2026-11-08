"""F4: `pdftotext -bbox` words and lines (collector/pdfwords.py) on real extracts: the wheel-loader bid tab and
FY2027 budget book p. 36. Line grouping keeps a tall header and the row under it apart; amount right edges in one
column are stable to 1 pt (the budget adapter's column bands rest on this)."""
import re
from pathlib import Path

from collector import pdfwords as P

FIX = Path(__file__).parent / "fixtures" / "finance"


def load(name):
    return P.parse_bbox((FIX / f"{name}.bbox.html").read_text(encoding="utf-8"))


def test_bid_tab_lines():
    words, pages = load("wheel_loader_bidtab")
    assert pages == 1 and len(words) == 37 and {w.page for w in words} == {1}
    texts = [ln.text for ln in P.lines(words)]
    assert texts[:8] == [
        "Bid Tab", "Bid Project___Wheel Loader____________", "Department___Bi-County SWM__________",
        "Bid Date___2-20-25 at 2p.m.________", "Bidder Name Total Notes", "McCoy Construction & $189,000.00",
        "Forestry", "Thompson Machinery $211,887.00"]
    assert texts[8] == "Bid Awarded to____McCoy Construction &Forestry___"
    assert texts[9] == "Date Bid Awarded___2-26-25_______"


def test_header_and_first_row_overlap_but_stay_two_lines():
    words, _ = load("wheel_loader_bidtab")
    total = next(w for w in words if w.text == "Total")
    first = next(w for w in words if w.text == "$189,000.00")
    assert total.y1 > first.y0                         # the boxes overlap in the real file
    ls = P.lines(words)
    assert next(ln for ln in ls if total in ln.words) is not next(ln for ln in ls if first in ln.words)


def test_budget_page_lines_and_words_in_order():
    words, _ = load("fy2027_p36")
    ls = P.lines(words)
    texts = [ln.text for ln in ls]
    assert "FY 2025 FY 2026 FY 2027 Budgeted Percent" in texts
    assert "Actuals Amended Budget Difference Change" in texts
    assert "53020 ADVERTISING 105 250 250 - -" in texts
    assert "Salaries & Benefits 8,612 10,770 10,765 (5) (.05)" in texts
    assert "Total COUNTY COMMISSION 376,605 449,008 466,993 17,985 4.01" in texts
    for ln in ls:
        assert [w.x0 for w in ln.words] == sorted(w.x0 for w in ln.words)
    assert [ln.yc for ln in ls] == sorted(ln.yc for ln in ls)


AMOUNT = re.compile(r"^\(?[\d,.]+\)?$|^-$")


def test_amount_right_edges_are_stable_to_one_point():
    words, _ = load("fy2027_p36")
    rows = [ln.words[-5:] for ln in P.lines(words) if len(ln.words) > 5 and all(AMOUNT.match(w.text)
                                                                               for w in ln.words[-5:])]
    assert len(rows) >= 25
    for col in range(5):
        edges = [r[col].x1 for r in rows]
        assert max(edges) - min(edges) <= 1.0, (col, min(edges), max(edges))


def test_scan_has_no_words():
    words, pages = load("scan_award_letter")
    assert pages == 1 and words == [] and P.lines(words) == []


def test_pdf_words_page_numbers_are_pdf_indexes(monkeypatch):
    """pdf_words on a page range gives the PDF page index (pdftotext numbers a range from 1)."""
    src = (FIX / "fy2027_p36.bbox.html").read_text(encoding="utf-8")
    seen = {}

    def fake(pdf, first=None, last=None):
        seen.update(first=first, last=last)
        return src
    monkeypatch.setattr(P, "bbox_text", fake)
    words = P.pdf_words(Path("book.pdf"), 36, 36)
    assert seen == {"first": 36, "last": 36} and {w.page for w in words} == {36}
    assert P.lines(words)[0].page == 36
