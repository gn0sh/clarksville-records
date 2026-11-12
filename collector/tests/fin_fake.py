"""A finance store built from the test fixtures, no network and no PDFs: the trimmed real archive page, fake PDF bytes
per link, and per-file words and text-layer facts injected into fin_facts.build (shared by the F5 and F5c tests)."""
from __future__ import annotations

import json
from pathlib import Path

from collector import fin_config, fin_facts, fin_run
from collector import pdfwords as P
from collector.fin_archive import parse_archive
from collector.store import Store

FIX = Path(__file__).parent / "fixtures" / "finance"
CFG = fin_config.load()
ARCHIVE_HTML = (FIX / "archive_trimmed.html").read_bytes()
WHEEL = (FIX / "wheel_loader_bidtab.bbox.html").read_text(encoding="utf-8")


def words(bbox: str):
    return P.parse_bbox(bbox)[0]


def page_words(name: str, page: int) -> list:
    """Words of a one-page budget-book bbox fixture (`fy2027_p36`), numbered as PDF page `page`."""
    return [P.Word(page, w.x0, w.x1, w.y0, w.y1, w.text)
            for w in words((FIX / f"{name}.bbox.html").read_text(encoding="utf-8"))]


# budget book id -> fixture pages the fake store serves for it (a statement page with a fund line first)
BOOK_PAGES = {"fy2027-approved": ("fy2027", (28, 30, 36, 37)), "fy2025-approved": ("fy2025", (31, 33, 36))}


def book_words(book_id: str) -> list:
    prefix, pages = BOOK_PAGES[book_id]
    return [w for p in pages for w in page_words(f"{prefix}_p{p}", p)]


def itemised(bbox: str = WHEEL) -> str:
    """The wheel-loader tab with a unit-price header: another layout."""
    return bbox.replace(">Notes</word>", ">Qty</word>")


def links():
    return fin_run.archive_links(parse_archive(ARCHIVE_HTML.decode(), CFG))


def url_ending(tail: str) -> str:
    return next(u for u, _, _ in links() if u.endswith(tail))


# per-URL overrides: tail of URL -> (text_layer, bbox text)
DEFAULT_CASES = {
    "Bid%20Tab%20-%20Wheel%20Loader.pdf": ("text", WHEEL),
    "Bid%20Tab%20-%20Sinkhole%20Repair.pdf": ("none", (FIX / "scan_award_letter.bbox.html").read_text("utf-8")),
    "Bid%20Tab%20-%20Hwy%20Dept%20Rock%20FY27.pdf": ("text", itemised()),
    "Bid%20Tab%20Sheet.pdf": ("text", WHEEL),                # shared by two rows: must yield nothing
    "Bid%20Tab%20-%20Traffic%20Paint%20FY27.pdf": ("ocr", WHEEL),   # a scanner's OCR text: must yield nothing
    "Award%20Letter%20-%20Wheel%20Loader.pdf": ("none", ""),
}


class FakeFin:
    def __init__(self, tmp_path: Path, cases: dict | None = None, stamp: str = "2026-11-08T00:00:00+00:00"):
        self.tmp = Path(tmp_path)
        self.cases = dict(DEFAULT_CASES if cases is None else cases)
        self.store = Store(self.tmp / "manifest.json", root=self.tmp / "store", now=lambda: stamp)
        self.store.put(CFG.archive_url, ARCHIVE_HTML, {"Content-Type": "text/html"}, {"kind": "archive_index"})
        self.by_sha: dict[str, tuple[str, str]] = {}
        status = {}
        for url, stage, label in links():
            if url.endswith(".docx"):
                status[url] = {"status": "not_pdf", "date": "2026-11-08", "detail": "docx"}
                continue
            e, _ = self.store.put(url, b"%PDF-1.7 " + url.encode(), {}, {"kind": fin_run.source_kind(stage),
                                                                         "label": label})
            layer, bbox = next((v for k, v in self.cases.items() if url.endswith(k)), ("text", ""))
            self.by_sha[e["sha256"]] = (layer, bbox)
        self.books: dict[str, list] = {}
        for spec in CFG.budget.books:
            e, _ = self.store.put(spec.url, b"%PDF-1.7 book " + spec.id.encode(), {}, {"kind": fin_run.BOOK_KIND,
                                                                                      "label": spec.title})
            self.by_sha[e["sha256"]] = ("text", "")
            self.books[e["sha256"]] = book_words(spec.id)
        self.store.save()
        self.status_path = self.tmp / "fin_fetch_status.json"
        self.status_path.write_text(json.dumps(status), encoding="utf-8")

    @staticmethod
    def default_cases() -> dict:
        return dict(DEFAULT_CASES)

    def meta(self, pdf: Path, cfg, cache_dir=None) -> dict:
        layer, _ = self.by_sha[pdf.stem]
        return {"pages": 1, "text_layer": layer, "creator": "Fixture Writer"}

    def words_for(self, pdf: Path):
        return words(self.by_sha[pdf.stem][1]) if self.by_sha[pdf.stem][1] else []

    def book_words(self, pdf: Path, first=None, last=None):
        return self.books[pdf.stem]

    def build(self, monkeypatch):
        monkeypatch.setattr(fin_facts, "pdf_meta", self.meta)
        return fin_facts.build(self.store, CFG, status_path=self.status_path, meta_cache=None,
                               words_for=self.words_for, book_words=self.book_words)
