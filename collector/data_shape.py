"""I-data'' (docs/architecture/v1-fail-2026-11-18.md section 2, ADR 0011): what a data tree may hold.

data/ holds collector output only. Its tree listing (`git ls-tree -r -z <commit> -- data`) passes only when
1. there is at least one entry, and every entry fits SHAPE'' as bytes: a regular file (mode 100644) under data/ with
   plain ASCII names, named *.json or exactly changes.jsonl. No .yml any more: the curated .yml inputs moved to config/;
   and
2. no entry's file name is one of the curated inputs (CURATED_NAMES), at any depth. Those are reviewed code under
   config/ (row CFG); a copy in data/ would be an unreviewed edit the collector never wrote; and
3. no entry is under data/maps/ or inside a transcripts/ folder at any depth (I-in, ADR 0011 decision 2a, rows TR and
   MP): the map manifest and the transcripts are person-made inputs that live under config/ (config/maps/,
   config/localities/<locality>/transcripts/), and no reader falls back to data/.

This module is the one definition outside the workflow. The gate and push job's `SHAPE=$'...'` lines in
.github/workflows/daily-update.yml are narrowed to SHAPE'' and gain the refusal list in task B2, with a test that keeps
them equal to SHAPE_BASH and CURATED_NAMES here.

    python -m collector.data_shape <listing>    exit 0 when the listing passes, 1 with at most 20 refused entries
                                                (bytes outside 0x20-0x7E shown as ?, never a raw name), 2 on a bad call

disk_listing() makes the same listing from a data/ folder on disk (filled by scripts/fetch-data, or the update job's
checkout of records-data), the uncommitted caches DATA_CACHES left out, for checks that must not read git's index of
main: data/ leaves main at the cutover (ADR 0011 row LS).
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

# The bash form, exactly as the workflow writes it inside $'...' (B2 copies this line); SHAPE is its bytes regex.
SHAPE_BASH = (r"^100644 blob [0-9a-f]{40}\tdata/([A-Za-z0-9_][A-Za-z0-9._-]*/)*"
              r"([A-Za-z0-9_][A-Za-z0-9._-]*\\.json|changes\\.jsonl)$")
# SHAPE_ERE: what bash makes of $'SHAPE_BASH' (\\ -> \, \t -> TAB), the bytes `grep -zE` gets. SHAPE compiles it.
SHAPE_ERE = SHAPE_BASH.replace("\\\\", "\\").replace("\\t", "\t").encode("ascii")
SHAPE = re.compile(SHAPE_ERE)

# Curated inputs: reviewed code under config/, never in data/ (I-data''). Their file names are refused at any depth.
CURATED_NAMES = ("names.yml", "procedural-titles.yml", "corrections-log.json", "published-fact-changes.yml",
                 "fin-books-accepted.yml")
_CURATED = {n.encode("ascii") for n in CURATED_NAMES}
CONFIG = Path(__file__).resolve().parent.parent / "config"
# The uncommitted collector caches under data/ (.gitignore: downloads and derived text), never part of a data tree.
DATA_CACHES = ("raw", "text", "ocr", "out", "store")


def _shown(entry: bytes) -> str:
    return "".join(chr(b) if 0x20 <= b <= 0x7E else "?" for b in entry)


def disk_listing(folder: Path) -> bytes:
    """A `git ls-tree -r -z`-shaped listing of the folder on disk (normally <checkout>/data), sorted by path, its
    top-level DATA_CACHES left out: per file its mode as git would record it (100755 when executable, 120000 for a
    symbolic link, else 100644), the blob id git would give it, and its path from the folder's parent. A missing or
    empty folder gives b"", which problems() refuses."""
    folder = Path(folder)
    rows = []
    if not folder.is_dir():
        return b""
    for dirpath, dirnames, filenames in os.walk(folder):
        rel = Path(dirpath).relative_to(folder)
        if rel == Path("."):
            dirnames[:] = [d for d in dirnames if d not in DATA_CACHES]
        for d in [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:   # a link to a folder: one entry
            filenames.append(d)
            dirnames.remove(d)
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                mode, body = b"120000", os.fsencode(os.readlink(full))
            else:
                mode = b"100755" if os.access(full, os.X_OK) else b"100644"
                body = Path(full).read_bytes()
            blob = hashlib.sha1(b"blob %d\0" % len(body) + body).hexdigest().encode("ascii")
            path = os.fsencode(Path(folder.name) / rel / name).replace(b"\\", b"/").replace(b"/./", b"/")
            rows.append((path, mode + b" blob " + blob + b"\t" + path))
    return b"".join(row + b"\0" for _, row in sorted(rows))


def problems(listing: bytes) -> list[str]:
    """Each refused entry of a NUL-separated `git ls-tree -r -z` listing of data/, shown safely; [] when it passes."""
    entries = [e for e in listing.split(b"\0") if e]
    if not entries:
        return ["data/ holds no file"]
    out = []
    for e in entries:
        path = e.split(b"\t", 1)[-1]
        if e.rsplit(b"/", 1)[-1] in _CURATED:
            out.append(f"curated input in data/ (it belongs in config/): {_shown(e)}")
        elif path.startswith(b"data/maps/"):
            out.append(f"map manifest in data/ (it belongs in config/maps/): {_shown(e)}")
        elif b"transcripts" in path.split(b"/")[:-1]:
            out.append(f"transcript in data/ (it belongs in config/localities/<locality>/transcripts/): {_shown(e)}")
        elif not SHAPE.fullmatch(e):
            out.append(f"not allowed in data/: {_shown(e)}")
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m collector.data_shape <git ls-tree -r -z listing of data/>", file=sys.stderr)
        return 2
    try:
        listing = Path(argv[0]).read_bytes()
    except OSError as exc:
        print(f"could not read the listing: {exc.strerror}", file=sys.stderr)
        return 2
    found = problems(listing)
    for p in found[:20]:
        print(p)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
