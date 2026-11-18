"""I-data'' (docs/architecture/v1-fail-2026-11-18.md section 2, ADR 0011): what a data tree may hold.

data/ holds collector output only. Its tree listing (`git ls-tree -r -z <commit> -- data`) passes only when
1. there is at least one entry, and every entry fits SHAPE'' as bytes: a regular file (mode 100644) under data/ with
   plain ASCII names, named *.json or exactly changes.jsonl. No .yml any more: the curated .yml inputs moved to config/;
   and
2. no entry's file name is one of the curated inputs (CURATED_NAMES), at any depth. Those are reviewed code under
   config/ (row CFG); a copy in data/ would be an unreviewed edit the collector never wrote.

This module is the one definition outside the workflow. The gate and push job's `SHAPE=$'...'` lines in
.github/workflows/daily-update.yml are narrowed to SHAPE'' and gain the refusal list in task B2, with a test that keeps
them equal to SHAPE_BASH and CURATED_NAMES here.

    python -m collector.data_shape <listing>    exit 0 when the listing passes, 1 with at most 20 refused entries
                                                (bytes outside 0x20-0x7E shown as ?, never a raw name), 2 on a bad call
"""
from __future__ import annotations

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
CURATED_NAMES = ("names.yml", "procedural-titles.yml", "corrections-log.json", "published-fact-changes.yml")
_CURATED = {n.encode("ascii") for n in CURATED_NAMES}
CONFIG = Path(__file__).resolve().parent.parent / "config"


def _shown(entry: bytes) -> str:
    return "".join(chr(b) if 0x20 <= b <= 0x7E else "?" for b in entry)


def problems(listing: bytes) -> list[str]:
    """Each refused entry of a NUL-separated `git ls-tree -r -z` listing of data/, shown safely; [] when it passes."""
    entries = [e for e in listing.split(b"\0") if e]
    if not entries:
        return ["data/ holds no file"]
    out = []
    for e in entries:
        if e.rsplit(b"/", 1)[-1] in _CURATED:
            out.append(f"curated input in data/ (it belongs in config/): {_shown(e)}")
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
