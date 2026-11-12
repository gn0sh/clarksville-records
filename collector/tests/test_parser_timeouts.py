"""pipeline/parser-dos: every poppler/tesseract call has a timeout; a timeout fails that document, not the run."""
import subprocess
from pathlib import Path

import pytest

from collector import city_minutes, extract, ocr, pdfwords


def _record(monkeypatch, module, seen):
    def fake(cmd, **kw):
        seen.append((cmd[0], kw.get("timeout")))
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    monkeypatch.setattr(module.subprocess, "run", fake)


def test_extract_and_pdfwords_have_120s_timeouts(monkeypatch):
    seen = []
    _record(monkeypatch, extract, seen)
    with pytest.raises(subprocess.TimeoutExpired):
        extract.extract_pages(Path("x.pdf"))
    _record(monkeypatch, pdfwords, seen)
    with pytest.raises(subprocess.TimeoutExpired):
        pdfwords.bbox_text(Path("x.pdf"))
    assert seen == [("pdftotext", 120), ("pdftotext", 120)]


def test_city_pdf_layer_calls_have_timeouts(monkeypatch):
    seen = []
    _record(monkeypatch, city_minutes, seen)
    with pytest.raises(subprocess.TimeoutExpired):
        city_minutes.pdf_layer(Path("x.pdf"), ["a long enough page of text " * 5])
    assert seen == [("pdfinfo", 120)]


def test_ocr_timeout_is_600s_and_reverify_records_a_failure(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(ocr, "OCR_CACHE", tmp_path)
    monkeypatch.setattr(ocr.shutil, "which", lambda n: "/usr/bin/" + n)
    _record(monkeypatch, ocr, seen)
    with pytest.raises(subprocess.TimeoutExpired):              # the page-size check's pdfinfo has its own timeout
        ocr.ocr_page(Path("x.pdf"), 1, "a" * 64)
    monkeypatch.setattr(ocr, "check_page", lambda pdf, page: None)
    with pytest.raises(subprocess.TimeoutExpired):
        ocr.ocr_page(Path("x.pdf"), 1, "a" * 64)
    assert seen == [("pdfinfo", 60), ("pdftoppm", 600)]

    class RC:
        page, end_page, reasons = 1, 1, []
    rc = ocr.reverify(RC(), Path("x.pdf"), "a" * 64, None)
    assert any("OCR failed" in r for r in rc.reasons)       # the document fails, the run continues
