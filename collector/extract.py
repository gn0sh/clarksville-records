"""Text extraction with page numbers.

Uses the PDF's existing OCR text layer via poppler's `pdftotext -layout`; pages are split on
form feeds, so page numbers are 1-based PDF page indexes. A page with (almost) no text is
reported as image-only (spec AC-P4: "not extracted"); OCR would need tesseract.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

MIN_CHARS_PER_PAGE = 40
PARSE_TIMEOUT = 120     # seconds; a hung poppler tool is a parse failure for that document (pipeline/parser-dos)


def extract_pages(pdf: Path) -> list[str]:
    out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"],
                         check=True, capture_output=True, timeout=PARSE_TIMEOUT).stdout.decode("utf-8", "replace")
    pages = out.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return pages


def image_only_pages(pages: list[str]) -> list[int]:
    return [i + 1 for i, p in enumerate(pages) if len(p.strip()) < MIN_CHARS_PER_PAGE]


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def cached_pages(pdf: Path, cache_dir: Path) -> list[str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    c = cache_dir / (pdf.stem + ".pages.json")
    if c.exists():
        return json.loads(c.read_text())
    pages = extract_pages(pdf)
    c.write_text(json.dumps(pages))
    return pages
