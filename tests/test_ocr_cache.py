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


def test_a_truncated_text_cache_is_deleted_and_read_again(tmp_path, monkeypatch):
    """ci/derived-cache-truncated: a short .pages.json (a run stopped mid-write, a bad cache) is never trusted."""
    from collector import extract
    calls = []
    monkeypatch.setattr(extract, "extract_pages", lambda pdf: calls.append(pdf) or ["page one", "page two"])
    pdf = tmp_path / f"{SHA}.pdf"
    c = tmp_path / "text" / f"{SHA}.pages.json"
    c.parent.mkdir()
    c.write_text('["page one", "pa')                                       # truncated JSON
    assert extract.cached_pages(pdf, c.parent) == ["page one", "page two"] and len(calls) == 1
    assert extract.cached_pages(pdf, c.parent) == ["page one", "page two"] and len(calls) == 1   # now cached
    c.write_text('{"not": "pages"}')
    assert extract.cached_pages(pdf, c.parent) == ["page one", "page two"] and len(calls) == 2
    assert not list(c.parent.glob("*.part"))


def test_the_text_cache_is_written_through_a_part_file(tmp_path, monkeypatch):
    from collector import extract
    seen = []
    real_replace = Path.replace

    def spy(self, target):
        seen.append((self.name, Path(target).name))
        return real_replace(self, target)
    monkeypatch.setattr(Path, "replace", spy)
    monkeypatch.setattr(extract, "extract_pages", lambda pdf: ["x"])
    extract.cached_pages(tmp_path / f"{SHA}.pdf", tmp_path)
    assert seen == [(f"{SHA}.pages.json.part", f"{SHA}.pages.json")]


def _steps():
    return {s.get("name"): s for s in WF["jobs"]["update"]["steps"]}


def test_the_workflow_restores_the_text_and_ocr_caches_before_collecting():
    names = [s.get("name") for s in WF["jobs"]["update"]["steps"]]
    restore = _steps()["Restore text and OCR caches"]
    assert "actions/cache/restore@" in restore["uses"]
    assert restore["with"]["path"].split() == ["data/text", "data/ocr"]
    code = ("${{ steps.tools.outputs.versions }}-"
            "${{ hashFiles('collector/extract.py', 'collector/ocr.py', 'requirements.lock') }}")
    names = [s.get("name") for s in WF["jobs"]["update"]["steps"]]
    assert names.index("Record OCR tool versions") < names.index("Restore text and OCR caches")
    assert restore["with"]["restore-keys"] == f"records-derived-v1-{code}-"         # ci/derived-cache-integrity
    assert restore["with"]["key"] == f"records-derived-v1-{code}-${{{{ github.run_id }}}}"
    assert "requirements.txt" not in restore["with"]["key"]    # deps/derived-cache-key: the lock holds every pin
    assert names.index("Restore text and OCR caches") < names.index("Collect (polite fetch, parse, verify)")
    assert names.index("Restore document store") < names.index("Collect (polite fetch, parse, verify)")
    # the document store keeps its own key and path, so the cache that exists today still restores
    assert _steps()["Restore document store"]["with"]["path"] == "data/store"


def test_the_workflow_saves_the_caches_even_after_a_failed_step():
    save = _steps()["Save text and OCR caches"]
    assert "actions/cache/save@" in save["uses"]
    # only the scheduled run on main writes the cache main restores (ci/derived-cache-integrity)
    assert save["if"] == ("always() && env.DERIVED_GREW == 'yes' && github.event_name == 'schedule' "
                          "&& github.ref == 'refs/heads/main'")
    assert save["with"]["key"] == _steps()["Restore text and OCR caches"]["with"]["key"]
    assert save["with"]["path"].split() == ["data/text", "data/ocr"]
    assert _steps()["Save document store"]["if"] == "always() && env.STORE_GREW == 'yes'"


def test_the_runbook_names_the_cache_rules_and_the_pages_branch_check():
    text = (ROOT / "docs" / "ops" / "launch-runbook.md").read_text(encoding="utf-8")
    assert "by the scheduled run on `main` only" in text
    assert "environments/github-pages/deployment-branch-policies" in text and "ci/pages-env-branch" in text
    assert "tesseract and pdftotext versions" in text


def test_the_tool_version_step_prints_one_short_hex_output(tmp_path):
    """The step's own script, run here: the output is 16 hex characters and changes with a tool's version line."""
    import os
    import shutil
    import subprocess
    script = _steps()["Record OCR tool versions"]["run"]
    assert "secrets." not in script and "${{" not in script        # nothing interpolated into the shell

    def run(tess_line):
        bindir = tmp_path / "bin"
        bindir.mkdir(exist_ok=True)
        for name, line in (("tesseract", tess_line), ("pdftotext", "pdftotext version 24.02.0")):
            f = bindir / name
            f.write_text(f"#!/bin/sh\necho '{line}'\n")
            f.chmod(0o755)
        out = tmp_path / "out"
        out.write_text("")
        env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(out)}
        subprocess.run([shutil.which("bash"), "-c", script], env=env, check=True)
        line = out.read_text().strip()
        assert line.startswith("versions=") and len(line) == len("versions=") + 16
        return line
    assert run("tesseract 5.3.4") != run("tesseract 5.5.0")
