"""One-off data migration (security review L1, privacy/rpc-applicant-phone): take applicants' phone numbers out of the
case `location` values already in data/localities/cmc-rpc/rpc.json, by the rule `collector rpc build` now applies when
it reads an agenda (collector/rpc_agenda.py strip_phones). The rebuild itself needs the document store, which is not
in a fresh checkout; this gives the same value without it, and the next `rpc build` writes the same again.

    python -m tools.scrub_rpc_phones            # rewrite rpc.json (idempotent; prints the cases changed)
    python -m tools.scrub_rpc_phones --check    # exit 1 if any case location still carries a phone number

Only `location` changes; every other field and the file's format (collector/rpc.py write_json) stay as they were.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from collector.rpc import write_json
from collector.rpc_agenda import strip_phones

RPC_JSON = Path(__file__).resolve().parent.parent / "data" / "localities" / "cmc-rpc" / "rpc.json"


def scrub(rpc: dict) -> list[str]:
    """Strip phone numbers from every case location in place; the ids of the cases changed."""
    changed = []
    for c in rpc.get("cases") or []:
        loc = c.get("location")
        new = strip_phones(loc)
        if new != loc:
            c["location"] = new
            changed.append(c["id"])
    return changed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="report only; exit 1 if a location carries a phone number")
    ap.add_argument("--path", type=Path, default=RPC_JSON)
    a = ap.parse_args(argv)
    rpc = json.loads(a.path.read_text(encoding="utf-8"))
    changed = scrub(rpc)
    for cid in changed:
        print(f"{'carries a phone number' if a.check else 'stripped'}: {cid}")
    if a.check:
        return 1 if changed else 0
    if changed:
        write_json(a.path, rpc)
    print(f"{len(changed)} case locations changed in {a.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
