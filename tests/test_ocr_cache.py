"""Re-OCR cost (pipeline/re-ocr-every-run): a page is OCR'd once per document hash. The OCR cache is keyed by the
document's sha256 and the page, so an unchanged document is never OCR'd again, and the daily workflow restores that
cache (data/text, data/ocr) before the collector runs and saves it when it grew."""
from pathlib import Path

import yaml

from collector import minutes, ocr

ROOT = Path(__file__).resolve().parent.parent
WF = yaml.safe_load((ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8"))
SHA = "ab" * 32


def test_a_cached_page_is_never_ocrd_again(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "OCR_CACHE", tmp_path)
    ocr.cache_path(SHA, 3).write_text("cached reading")

    def no_run(*a, **k):
        raise AssertionError("tesseract or pdftoppm was called for a cached page")
    monkeypatch.setattr(ocr.subprocess, "run", no_run)
    assert ocr.ocr_page(tmp_path / "missing.pdf", 3, SHA) == "cached reading"


def test_the_parallel_ocr_skips_every_cached_page(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "OCR_CACHE", tmp_path)
    for p in (1, 2):
        ocr.cache_path(SHA, p).write_text("x")

    class NoPool:
        def __init__(self, *a, **k):
            raise AssertionError("a pool was started although every page is cached")
    monkeypatch.setattr(minutes, "ProcessPoolExecutor", NoPool)
    assert minutes.ocr_pages_parallel([("d.pdf", 1, SHA), ("d.pdf", 2, SHA)]) == {}


def test_a_changed_document_has_a_new_cache_key():
    assert ocr.cache_path(SHA, 1) != ocr.cache_path("cd" * 32, 1)      # new bytes, new hash: read afresh


def _steps():
    return {s.get("name"): s for s in WF["jobs"]["update"]["steps"]}


def test_the_workflow_restores_the_text_and_ocr_caches_before_collecting():
    names = [s.get("name") for s in WF["jobs"]["update"]["steps"]]
    restore = _steps()["Restore text and OCR caches"]
    assert "actions/cache/restore@" in restore["uses"]
    assert restore["with"]["path"].split() == ["data/text", "data/ocr"]
    assert restore["with"]["restore-keys"] == "records-derived-v1-"
    assert names.index("Restore text and OCR caches") < names.index("Collect (polite fetch, parse, verify)")
    assert names.index("Restore document store") < names.index("Collect (polite fetch, parse, verify)")
    # the document store keeps its own key and path, so the cache that exists today still restores
    assert _steps()["Restore document store"]["with"]["path"] == "data/store"


def test_the_workflow_saves_the_caches_even_after_a_failed_step():
    save = _steps()["Save text and OCR caches"]
    assert "actions/cache/save@" in save["uses"] and save["if"] == "always() && env.DERIVED_GREW == 'yes'"
    assert save["with"]["key"] == "records-derived-v1-${{ github.run_id }}"
    assert _steps()["Save document store"]["if"] == "always() && env.STORE_GREW == 'yes'"
