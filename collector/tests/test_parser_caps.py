"""pipeline/parser-dos-untimed (security review tip c6cf774, finding 5): pdfinfo calls have a timeout and a hung one
fails that file closed, reported, never the run; OCR renders no oversized page, whatever its position in the document
(pipeline-limits-invariant rule 4)."""
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from collector import agenda_center as ac
from collector import city_build, fin_facts, minutes, ocr, rpc_agenda
from collector.city_minutes import parse_text
from collector.tests.test_city_minutes import PAGE1, PAGE2, rows_and_store

needs_poppler = pytest.mark.skipif(shutil.which("pdfinfo") is None, reason="poppler-utils not installed")


def _record(monkeypatch, module, seen):
    def fake(cmd, **kw):
        seen.append((cmd[0], kw.get("timeout")))
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    monkeypatch.setattr(module.subprocess, "run", fake)


def _hung_pdfinfo(tmp_path: Path, monkeypatch) -> None:
    """A `pdfinfo` first on PATH that never finishes, as on a hostile PDF."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    tool = bin_dir / "pdfinfo"
    tool.write_text("#!/bin/sh\nsleep 30\n")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def _pdf(path: Path, media: str, crop: str | None = None, pages: int = 1) -> Path:
    """A minimal valid PDF of `pages` empty pages with the given MediaBox (and CropBox)."""
    box = f"/MediaBox [{media}]" + (f" /CropBox [{crop}]" if crop else "")
    kids = " ".join(f"{3 + i} 0 R" for i in range(pages))
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>"]
    objs += [f"<< /Type /Page /Parent 2 0 R {box} >>"] * pages
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)
    return path


# ------------------------------------------------------------------ pdfinfo timeouts

def test_city_build_pdfinfo_has_a_120s_timeout(monkeypatch):
    seen = []
    _record(monkeypatch, city_build, seen)
    with pytest.raises(subprocess.TimeoutExpired):
        city_build.pdf_pages(Path("x.pdf"))
    assert seen == [("pdfinfo", 120)]


def test_city_build_a_hung_pdfinfo_times_out(monkeypatch, tmp_path):
    _hung_pdfinfo(tmp_path, monkeypatch)
    monkeypatch.setattr(city_build, "PDFINFO_TIMEOUT", 0.5)
    t = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        city_build.pdf_pages(Path("x.pdf"))
    assert time.monotonic() - t < 10


def test_city_build_leaves_out_a_file_it_cannot_inspect_and_goes_on(capsys):
    """Every file hangs pdfinfo: each is reported once, none is cited or read, and the build still finishes."""
    cfg = ac.load_config(ac.config_path("clarksville-tn"))
    rows, store, _ = rows_and_store()

    def hung(path):
        raise subprocess.TimeoutExpired(["pdfinfo", str(path)], 120)
    facts, summary = city_build.build(cfg, rows, store, parse=lambda p, c: parse_text([PAGE1, PAGE2], c),
                                      inspect=hung)
    bad = [p for p in summary["problems"] if "pdf inspection failed" in p["problem"]]
    assert len(bad) == 3 and len({p["sha256"] for p in bad}) == 3       # three stored files, each reported once
    assert not facts.get("sources")
    assert capsys.readouterr().err.count("city build: skipped") == 3


def test_fin_pdf_meta_has_a_120s_timeout_and_fails_closed_without_caching(monkeypatch, tmp_path):
    seen = []
    _record(monkeypatch, fin_facts, seen)
    meta = fin_facts.pdf_meta(Path("x.pdf"), None, tmp_path / "cache")
    assert seen == [("pdfinfo", 120)]
    assert meta == {"pages": None, "text_layer": "unreadable", "creator": None}   # carries no value, not a scan
    assert not (tmp_path / "cache").exists()                                 # tried again next build


def test_fin_pdf_meta_a_hung_pdfinfo_times_out(monkeypatch, tmp_path, capsys):
    _hung_pdfinfo(tmp_path, monkeypatch)
    monkeypatch.setattr(fin_facts, "PDFINFO_TIMEOUT", 0.5)
    t = time.monotonic()
    assert fin_facts.pdf_meta(Path("x.pdf"), None, None)["text_layer"] == "unreadable"
    assert time.monotonic() - t < 10
    assert "pdf inspection failed (TimeoutExpired)" in capsys.readouterr().err


# ------------------------------------------------------------------ OCR page caps

@needs_poppler
@pytest.mark.parametrize("media,crop", [("0 0 14400 14400", None), ("0 0 612 9000", None),
                                        ("0 0 9000 792", "0 0 612 792")])
def test_an_oversized_page_is_skipped_and_never_rendered(monkeypatch, tmp_path, media, crop):
    pdf = _pdf(tmp_path / "big.pdf", media, crop)
    monkeypatch.setattr(ocr, "OCR_CACHE", tmp_path / "ocr")
    monkeypatch.setattr(ocr.shutil, "which", lambda n: "/usr/bin/" + n)
    real, rendered = subprocess.run, []

    def run(cmd, **kw):
        if cmd[0] != "pdfinfo":
            rendered.append(cmd[0])
        return real(["true"]) if cmd[0] != "pdfinfo" else real(cmd, **kw)
    monkeypatch.setattr(ocr.subprocess, "run", run)
    with pytest.raises(ocr.PageRefused, match="larger than 2592 pt"):
        ocr.ocr_page(pdf, 1, "b" * 64)
    assert rendered == [] and not ocr.cache_path("b" * 64, 1).exists()

    class RC:
        page, end_page, reasons = 1, 1, []
    rc = ocr.reverify(RC(), pdf, "b" * 64, None)
    assert any("OCR failed" in r and "not rendered" in r for r in rc.reasons)   # that reading fails, the run goes on
    assert rendered == []


@needs_poppler
def test_page_checks_allow_letter_and_refuse_a_missing_page(tmp_path):
    pdf = _pdf(tmp_path / "letter.pdf", "0 0 612 792")
    ocr.check_page(pdf, 1)
    with pytest.raises(ocr.PageRefused, match="no page size"):
        ocr.check_page(pdf, 2)
    with pytest.raises(ocr.PageRefused, match="no such page"):
        ocr.check_page(pdf, 0)


@needs_poppler
def test_page_519_of_a_621_page_document_is_read(monkeypatch, tmp_path):
    """pipeline/ocr-page-cap-drops-real-readings: county minutes run to 621 pages and verified roll calls rely on
    tesseract re-reads past page 200 (rc-30a9df8f-p519-0). Position is not cost: no page index is refused."""
    pdf = _pdf(tmp_path / "minutes.pdf", "0 0 612 792", pages=621)
    ocr.check_page(pdf, 519)
    ocr.check_page(pdf, 621)
    monkeypatch.setattr(ocr, "OCR_CACHE", tmp_path / "ocr")
    monkeypatch.setattr(ocr.shutil, "which", lambda n: "/usr/bin/" + n)
    real, rendered = subprocess.run, []

    def run(cmd, **kw):
        if cmd[0] == "pdfinfo":
            return real(cmd, **kw)
        rendered.append((cmd[0], cmd[cmd.index("-f") + 1] if cmd[0] == "pdftoppm" else None))
        raise subprocess.CalledProcessError(1, cmd)        # stop before tesseract; the render was asked for
    monkeypatch.setattr(ocr.subprocess, "run", run)

    class RC:
        page, end_page, reasons = 519, 519, []
    rc = ocr.reverify(RC(), pdf, "e" * 64, None)
    assert rendered == [("pdftoppm", "519")]
    assert not any("not rendered" in r for r in rc.reasons)


def test_the_render_itself_is_pixel_bounded(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(ocr, "OCR_CACHE", tmp_path / "ocr")
    monkeypatch.setattr(ocr.shutil, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(ocr, "check_page", lambda p, n: None)

    def run(cmd, **kw):
        seen.append(cmd)
        raise subprocess.CalledProcessError(1, cmd)
    monkeypatch.setattr(ocr.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        ocr.ocr_page(Path("x.pdf"), 1, "c" * 64)
    cmd = seen[0]
    assert cmd[0] == "pdftoppm" and cmd[cmd.index("-W") + 1] == cmd[cmd.index("-H") + 1] == str(ocr.MAX_PAGE_PX)
    assert ocr.MAX_PAGE_PX == 10800


def test_rpc_ocr_document_refuses_too_many_pages_before_rendering(monkeypatch):
    monkeypatch.setattr(minutes, "ocr_pages_parallel", lambda jobs: pytest.fail("no page may be rendered"))
    with pytest.raises(ocr.PageRefused, match="at most 200 pages"):
        rpc_agenda.ocr_document(Path("x.pdf"), "d" * 64, rpc_agenda.RPC_MAX_OCR_PAGES + 1)


def test_rpc_ocr_document_reads_the_largest_real_rpc_document_whole(monkeypatch, tmp_path):
    asked = []
    monkeypatch.setattr(ocr, "OCR_CACHE", tmp_path)

    def parallel(jobs):
        asked.extend(p for _, p, _ in jobs)
        for _, p, sha in jobs:
            ocr.cache_path(sha, p).write_text(f"page {p}")
        return {(sha, p): None for _, p, sha in jobs}
    monkeypatch.setattr(minutes, "ocr_pages_parallel", parallel)
    assert len(rpc_agenda.ocr_document(Path("x.pdf"), "f" * 64, 90)) == 90 and asked == list(range(1, 91))
