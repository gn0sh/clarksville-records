"""Compare parser output (data/out/rollcalls.json) with the hand labels.

Usage: python3 -m collector.compare_labels
A "wrong vote" is a member whose parsed vote differs from the label in a Verified roll call.
"""
from __future__ import annotations

import json
from pathlib import Path

from .parse import name_similarity

ROOT = Path(__file__).resolve().parent.parent
CODE = {"Y": "Yes", "N": "No", "A": "Abstain"}


def main() -> int:
    labels = json.loads((ROOT / "collector" / "hand_labels.json").read_text())
    rcs = json.loads((ROOT / "data" / "out" / "rollcalls.json").read_text())
    total = wrong_verified = checked_votes = 0
    held = 0
    for lab in labels["labels"]:
        roster = labels["rosters"][lab["roster"]]
        codes = lab["votes"].replace(" ", "")
        rc = next((r for r in rcs if r["source"] == lab["source"] and r["page"] == lab["page"]
                   and r["ordinal_on_page"] == lab["ordinal"]), None)
        total += 1
        if rc is None:
            print(f"MISSING  {lab['source']} p{lab['page']}#{lab['ordinal']}")
            continue
        diffs = []
        for name, code in zip(roster, codes):
            if code == "V":
                continue
            key = max(rc["votes"], key=lambda k: name_similarity(k, name), default=None)
            got = rc["votes"].get(key) if key and name_similarity(key, name) >= 0.7 else None
            want = CODE.get(code, "absent")
            have = "absent" if got in ("none", "---", "-") and key in rc["absent"] else got
            if have != want:
                diffs.append(f"{name}: label {want}, parsed {have}")
        tally_ok = tuple(rc["tally"] or ()) == tuple(lab["tally"])
        if rc["status"] == "Verified":
            wrong_verified += len(diffs)
            checked_votes += sum(c in CODE for c in codes)
        else:
            held += 1
        print(f"{rc['status']:<10} {lab['source'][:28]:<28} p{lab['page']:<3}#{lab['ordinal']} "
              f"by={rc['verified_by'] or '-':<10} tally {'ok' if tally_ok else 'DIFF'}  diffs={len(diffs)}"
              + (f"  {diffs[:3]}" if diffs else ""))
    print(f"\nlabelled roll calls {total}; Verified {total - held}; held back {held}")
    print(f"votes checked in Verified roll calls: {checked_votes}; wrong votes among Verified: {wrong_verified}")
    return 1 if wrong_verified else 0


if __name__ == "__main__":
    raise SystemExit(main())
