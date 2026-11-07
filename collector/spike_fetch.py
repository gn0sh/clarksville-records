"""M0: fetch the minutes index and a spread of minutes PDFs, politely.

Usage:
  python3 -m collector.spike_fetch index            # fetch index, list links found
  python3 -m collector.spike_fetch pick             # choose ~10 PDFs across 2020-2024 and download
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

from .fetch import PoliteFetcher, cache_download

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "data" / "manifest.json"
INDEX_URL = "https://dev2.montgomerytn.gov/clerk/county-commission-minutes"
INDEX_CACHE = RAW / "index.html"


def parse_index(page: str) -> list[dict]:
    """Return [{url, label}] for every link to the minutes viewer."""
    out = []
    for m in re.finditer(r'<a[^>]+href="([^"]*bisonline\.com/viewpdf\.php\?id=[^"]+)"[^>]*>(.*?)</a>',
                         page, re.S | re.I):
        label = re.sub(r"<[^>]+>", " ", m.group(2))
        label = re.sub(r"\s+", " ", html.unescape(label)).strip()
        out.append({"url": html.unescape(m.group(1)), "label": label})
    return out


def main(argv: list[str]) -> int:
    f = PoliteFetcher()
    cmd = argv[1] if len(argv) > 1 else "index"
    if cmd == "index" or not INDEX_CACHE.exists():
        status, body, _ = f.get(INDEX_URL)
        print("index status", status, len(body))
        RAW.mkdir(parents=True, exist_ok=True)
        INDEX_CACHE.write_bytes(body)
    links = parse_index(INDEX_CACHE.read_text("utf-8", "replace"))
    if cmd == "index":
        for l in links:
            print(l["label"], "|", l["url"])
        print(len(links), "links")
        return 0
    if cmd == "pick":
        picks = json.loads((ROOT / "collector" / "spike_picks.json").read_text())
        for p in picks:
            e = cache_download(f, p["url"], RAW, MANIFEST, {"label": p["label"]})
            print(e["label"], e["sha256"][:12], e["bytes"])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
