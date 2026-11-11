"""Second reading of a vote table: re-OCR the scanned page with tesseract.

The PDF's own text layer often drops faint vote marks. Rendering the page at 300 dpi and running
tesseract (free, open source; `apt-get install tesseract-ocr`) gives an independent reading. A
roll call is Verified only if some reading passes every P2 check and no two readings disagree on a
vote (parse.decide). Only pages of roll calls that fail on the text layer are OCRed.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .parse import RollCall, decide, read_table, table_heads, _lines_with_pages

ROOT = Path(__file__).resolve().parent.parent
OCR_CACHE = Path(os.environ.get("RECORDS_OCR_CACHE", ROOT / "data" / "ocr"))
DPI = 300
OCR_TIMEOUT = 600        # seconds per poppler/tesseract call; a timeout is an OCR failure for that roll call
# pipeline/parser-dos-untimed: a hostile PDF must not make one render exhaust memory or run forever. The caps bound
# what one page costs, never where in a document we may read (docs/architecture/pipeline-limits-invariant.md rule 4).
# Real stored pages: letter/legal, largest side 804 pt; largest documents 621 pp county minutes, 90 pp RPC
# (2026-11-11). A page larger than 36 in (2592 pt, 3.2x) on a side is not rendered: an OCR failure for that page (fail
# closed: the reading is missing, never guessed), reported as a limit trip like a timeout.
PAGE_INFO_TIMEOUT = 60   # seconds for the pdfinfo call that reads the page's boxes
MAX_PAGE_PTS = 2592.0
MAX_PAGE_PX = int(MAX_PAGE_PTS / 72 * DPI)     # the render's hard pixel bound (pdftoppm -W/-H), whatever pdfinfo said
_BOX = re.compile(r"^Page\s+\d+\s+(?:size:\s+([\d.]+)\s+x\s+([\d.]+)|(?:Media|Crop)Box:\s+([-\d.]+)\s+([-\d.]+)\s+"
                  r"([-\d.]+)\s+([-\d.]+))", re.M)


class PageRefused(RuntimeError):
    """The page is not rendered for OCR: too large, or its size could not be read."""


def check_page(pdf: Path, page: int) -> None:
    """Raise PageRefused unless `page` exists within the caps: its size, MediaBox and CropBox (pdfinfo -box, with a
    timeout) all at most MAX_PAGE_PTS on each side."""
    if page < 1:
        raise PageRefused(f"page {page} not rendered: no such page")
    out = subprocess.run(["pdfinfo", "-f", str(page), "-l", str(page), "-box", str(pdf)], capture_output=True,
                         timeout=PAGE_INFO_TIMEOUT).stdout.decode("utf-8", "replace")
    sides = []
    for m in _BOX.finditer(out):
        if m.group(1):
            sides += [float(m.group(1)), float(m.group(2))]
        else:
            x0, y0, x1, y1 = (float(m.group(k)) for k in range(3, 7))
            sides += [abs(x1 - x0), abs(y1 - y0)]
    if not sides:
        raise PageRefused(f"page {page} not rendered: pdfinfo gave no page size")
    if max(sides) > MAX_PAGE_PTS:
        raise PageRefused(f"page {page} not rendered: {max(sides):.0f} pt side, larger than {MAX_PAGE_PTS:.0f} pt")


def cache_path(sha: str, page: int) -> Path:
    return OCR_CACHE / f"{sha[:16]}-p{page}.txt"


def ocr_page(pdf: Path, page: int, sha: str) -> str:
    OCR_CACHE.mkdir(parents=True, exist_ok=True)
    cache = cache_path(sha, page)
    if cache.exists():
        return cache.read_text()
    if shutil.which("tesseract") is None:
        raise RuntimeError("tesseract not installed")
    check_page(pdf, page)
    env = dict(os.environ, OMP_THREAD_LIMIT="1")      # one core per page; pages run in parallel
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "pg"
        # -x/-y/-W/-H: a crop no larger than MAX_PAGE_PX, so the bitmap is bounded even if the boxes lied; a page
        # within the cap renders byte-identical to the uncropped call
        subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(DPI), "-gray", "-png",
                        "-x", "0", "-y", "0", "-W", str(MAX_PAGE_PX), "-H", str(MAX_PAGE_PX),
                        str(pdf), str(base)], check=True, capture_output=True, timeout=OCR_TIMEOUT)
        png = next(Path(td).glob("pg*.png"))
        text = subprocess.run(["tesseract", str(png), "-", "--psm", "6", "-c", "preserve_interword_spaces=1"],
                              check=True, capture_output=True, env=env, timeout=OCR_TIMEOUT).stdout.decode("utf-8", "replace")
    tmp = cache.with_suffix(".part")
    tmp.write_text(text)
    tmp.replace(cache)
    return text


def reverify(rc: RollCall, pdf: Path, sha: str, att) -> RollCall:
    try:
        pages = [ocr_page(pdf, p, sha) for p in range(rc.page, rc.end_page + 1)]
    except Exception as e:
        rc.reasons = rc.reasons + [f"[tesseract] OCR failed: {e}"]
        return rc
    lines, page_of = _lines_with_pages(pages)
    heads = table_heads(lines)
    on_first = [h for h in heads if page_of[h] == 1]
    if rc.ordinal_on_page >= len(on_first):
        rc.reasons = rc.reasons + ["[tesseract] matching table not found on page"]
        return rc
    roster = (att.present + att.absent) if att else []
    idx = heads.index(on_first[rc.ordinal_on_page])
    h = heads[idx]
    nxt = heads[idx + 1] if idx + 1 < len(heads) else len(lines)
    reading, _ = read_table(lines, h, nxt, roster, "tesseract", att.spellings if att else None)
    rc.readings = rc.readings + [reading]
    decide(rc)
    return rc
