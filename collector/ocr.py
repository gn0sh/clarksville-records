"""Second reading of a vote table: re-OCR the scanned page with tesseract.

The PDF's own text layer often drops faint vote marks. Rendering the page at 300 dpi and running
tesseract (free, open source; `apt-get install tesseract-ocr`) gives an independent reading. A
roll call is Verified only if some reading passes every P2 check and no two readings disagree on a
vote (parse.decide). Only pages of roll calls that fail on the text layer are OCRed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .parse import RollCall, decide, read_table, table_heads, _lines_with_pages

ROOT = Path(__file__).resolve().parent.parent
OCR_CACHE = Path(os.environ.get("RECORDS_OCR_CACHE", ROOT / "data" / "ocr"))
DPI = 300


def cache_path(sha: str, page: int) -> Path:
    return OCR_CACHE / f"{sha[:16]}-p{page}.txt"


def ocr_page(pdf: Path, page: int, sha: str) -> str:
    OCR_CACHE.mkdir(parents=True, exist_ok=True)
    cache = cache_path(sha, page)
    if cache.exists():
        return cache.read_text()
    if shutil.which("tesseract") is None:
        raise RuntimeError("tesseract not installed")
    env = dict(os.environ, OMP_THREAD_LIMIT="1")      # one core per page; pages run in parallel
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "pg"
        subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(DPI), "-gray", "-png",
                        str(pdf), str(base)], check=True, capture_output=True)
        png = next(Path(td).glob("pg*.png"))
        text = subprocess.run(["tesseract", str(png), "-", "--psm", "6", "-c", "preserve_interword_spaces=1"],
                              check=True, capture_output=True, env=env).stdout.decode("utf-8", "replace")
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
    reading, _ = read_table(lines, h, nxt, roster, "tesseract")
    rc.readings = rc.readings + [reading]
    decide(rc)
    return rc
