"""Compare data/facts.json with the hand labels (AC-P3).

Usage: python3 -m collector.compare_labels [facts.json]
A "wrong vote" is a member whose vote in a verified roll call differs from the label (an absent member must have no
vote). Exit 1 if any wrong vote, or if a labelled roll call is missing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .names import NAMES, Resolver, load_roster
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
CODE = {"Y": "yes", "N": "no", "A": "abstain", "-": None}


def compare(facts: dict, labels: dict, store: Store, resolver: Resolver) -> dict:
    by_label = {e.get("label"): e["sha256"] for e in store.entries}
    rcs = {r["id"]: r for r in facts["roll_calls"]}
    out = {"labelled": 0, "verified": 0, "held": 0, "missing": [], "votes_checked": 0, "wrong": [], "rows": []}
    for lab in labels["labels"]:
        out["labelled"] += 1
        sha = by_label.get(lab["source"])
        rid = f"rc-{sha[:8]}-p{lab['page']}-{lab['ordinal']}" if sha else None
        rc = rcs.get(rid)
        if rc is None and sha:
            # a reprinted consent vote is one roll call; its printing on this page is an event pointing at it
            refs = {e["ref"] for e in facts["item_events"] if e["type"] == "roll_call" and e["ref"] in rcs
                    and e["id"].startswith(f"ev-{sha[:8]}-p{lab['page']}-")
                    and rcs[e["ref"]]["page"] != lab["page"]}
            if len(refs) == 1:
                rid = refs.pop()
                rc = rcs[rid]
        if rc is None:
            out["missing"].append(f"{lab['source']} p{lab['page']}#{lab['ordinal']}")
            continue
        roster = labels["rosters"][lab["roster"]]
        codes = lab["votes"].replace(" ", "")
        got = {v["official_id"]: v["value"] for v in rc["votes"]}
        diffs = []
        for name, code in zip(roster, codes):
            if code == "V" or name == "VACANT":
                continue
            oid = resolver.exact_match(name)
            want = CODE[code]
            have = got.get(oid)
            if oid is None or have != want:
                diffs.append(f"{name}: label {want}, facts {have}")
        ok = rc["verification"]["status"] == "verified"
        if ok:
            out["verified"] += 1
            out["votes_checked"] += sum(c in "YNA" for c in codes)
            out["wrong"] += [f"{rid} {d}" for d in diffs]
        else:
            out["held"] += 1
        out["rows"].append(f"{'verified' if ok else 'held':<9} {rid:<28} diffs={len(diffs)}")
    return out


def main(argv: list[str]) -> int:
    facts = json.loads(Path(argv[1] if len(argv) > 1 else ROOT / "data" / "facts.json").read_text())
    labels = json.loads((ROOT / "collector" / "hand_labels.json").read_text())
    res = compare(facts, labels, Store(), Resolver(load_roster(NAMES)))
    print("\n".join(res["rows"]))
    print(f"\nlabelled {res['labelled']}; verified {res['verified']}; held back {res['held']}; "
          f"missing {len(res['missing'])}")
    print(f"votes checked in verified roll calls: {res['votes_checked']}; wrong votes: {len(res['wrong'])}")
    for w in res["wrong"]:
        print("  WRONG", w)
    return 1 if res["wrong"] or res["missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
