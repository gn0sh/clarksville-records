"""Fetch one source map PDF politely into the document store, listed in config/maps/manifest.json.

Map PDFs (the county district map, the city ward poster) are inputs to tools/extract_pdf_map.py, not minutes, so they
get their own manifest: the collector's manifests list only documents it parses. The fetch goes through the
collector's PoliteFetcher (robots.txt, its Crawl-delay, our User-Agent, no redirect tricks) with the one map host
added to the allowlist for this run; bytes already in the store are never fetched again.

  python -I tools/fetch_map.py https://www.cmcrpc.com/wp2025/wp-content/uploads/2026/02/ClarksvilleCityWardsPoster.pdf \
      --label "City Council Wards poster, RPC, updated 2026-02-25"

Prints the stored path and sha256. Dev tool; nothing at build time runs it, but the build reads its manifest through
config/site.yml `fetch_manifests`. The manifest is a person-made input, so it lives under config/maps/ and reaches the
build only by a reviewed pull request (I-in, ADR 0011 decision 2a, row MP); the tool writes only under config/maps/
(the PDF bytes go to the uncommitted document store) and refuses any other --manifest.
"""
from __future__ import annotations

import argparse
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.fetch import ALLOWED_HOSTS, PoliteFetcher  # noqa: E402
from collector.store import ROOT, Store, fetch_into_store  # noqa: E402

MAPS_DIR = ROOT / "config" / "maps"
MAPS_MANIFEST = MAPS_DIR / "manifest.json"
MAP_HOSTS = ("www.cmcrpc.com",)      # Clarksville-Montgomery County Regional Planning Commission (robots crawl-delay 10)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("url")
    ap.add_argument("--label", required=True)
    ap.add_argument("--manifest", default=str(MAPS_MANIFEST), help="a manifest under config/maps/ (default: %(default)s)")
    a = ap.parse_args(argv)
    if not Path(a.manifest).resolve().is_relative_to(MAPS_DIR.resolve()):
        print(f"--manifest must be under {MAPS_DIR} (I-in: no person-run tool writes data/)", file=sys.stderr)
        return 2
    parts = urllib.parse.urlsplit(a.url)
    host = parts.netloc
    if parts.scheme != "https":
        print("only https URLs are fetched", file=sys.stderr)
        return 2
    if host not in MAP_HOSTS and host not in ALLOWED_HOSTS:
        print(f"{host} is not a known map host", file=sys.stderr)
        return 2
    store = Store(manifest_path=Path(a.manifest))
    fetcher = PoliteFetcher(allowed_hosts=ALLOWED_HOSTS + MAP_HOSTS)
    entry, status = fetch_into_store(fetcher, store, a.url, {"kind": "map", "label": a.label})
    store.save()
    print(status, entry["sha256"], store.path_for(entry["sha256"]))
    for ev in fetcher.log:
        print(" ", ev["event"], ev.get("url") or ev["host"], ev.get("detail", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
