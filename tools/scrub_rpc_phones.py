"""Read-only check (security review L1, privacy/rpc-applicant-phone): no case `location` in
data/localities/cmc-rpc/rpc.json carries an applicant's phone number, by the rule `collector rpc build` applies when it
reads an agenda (collector/rpc_agenda.py strip_phones).

    python -m tools.scrub_rpc_phones --check [--path <rpc.json>]   # exit 1 if any case location carries a phone number

It never writes. Its one-off rewrite mode is gone (ADR 0011 decision 2a, row SC): no person-run tool writes data/ for
commit (I-in), and the daily `rpc build` already strips phones, so the data on records-data is fixed by the collector.
The cutover runs this check on the seed tree. It prints the ids of the cases that fail, never the location text.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from collector.rpc_agenda import strip_phones

RPC_JSON = Path(__file__).resolve().parent.parent / "data" / "localities" / "cmc-rpc" / "rpc.json"


def carrying_phones(rpc: dict) -> list[str]:
    """The ids of the cases whose location strip_phones would change (it carries a phone number). Reads only."""
    return [c["id"] for c in rpc.get("cases") or [] if strip_phones(c.get("location")) != c.get("location")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", required=True,
                    help="report only (the one mode); exit 1 if a location carries a phone number")
    ap.add_argument("--path", type=Path, default=RPC_JSON)
    a = ap.parse_args(argv)
    try:
        rpc = json.loads(a.path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"scrub_rpc_phones: cannot read {a.path} ({type(exc).__name__}); run scripts/fetch-data first",
              file=sys.stderr)
        return 2
    bad = carrying_phones(rpc)
    for cid in bad:
        print(f"carries a phone number: {cid}")
    print(f"{len(bad)} case locations carry a phone number in {a.path}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
