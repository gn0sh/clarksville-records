"""Checks of architecture "Invariant: one vote, one roll call" on a facts file (problem family item-history).

python -m collector.invariants [data/facts.json]  -> prints the counts and each violation; exit 1 on any violation.
Used by collector/tests/test_one_vote.py on synthetic and real facts.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def consent_item_ids(facts: dict) -> set:
    return {i["id"] for i in facts["items"] if i["link_basis"] == "title" and i["title"] == "Consent Agenda"}


def one_vote_violations(facts: dict) -> list[str]:
    """Every breach of the one-vote invariant that the facts file itself can show:
    1. no meeting has two verified consent roll calls with the same per-member votes and the same mover and seconder
       (a name the facts could not resolve fits any): two printings of one vote published as two votes;
    2. no official has two vote rows in one roll call;
    3. no (item, roll call) pair has two roll_call item events;
    4. every roll_call item event points at a roll call that exists."""
    out = []
    motions = {m["id"]: m for m in facts["motions"]}
    consent = consent_item_ids(facts)
    seen: dict[tuple, list] = {}
    for rc in sorted(facts["roll_calls"], key=lambda r: r["id"]):
        if rc["item_id"] not in consent or rc["verification"]["status"] != "verified":
            continue
        mo = motions.get(rc["motion_id"]) or {}
        names = ((mo.get("moved_by") or {}).get("official_id"), (mo.get("seconded_by") or {}).get("official_id"))
        key = (rc["meeting_id"], tuple(sorted((v["official_id"] or "?" + v["raw_name"], v["value"])
                                              for v in rc["votes"])))
        for other, onames in seen.get(key, []):
            # the same mover and seconder, where both motions name them (an unresolved or unread name fits any)
            if all(a is None or b is None or a == b for a, b in zip(names, onames)):
                out.append(f"{rc['meeting_id']}: verified consent roll calls {other} and {rc['id']} are one vote")
                break
        seen.setdefault(key, []).append((rc["id"], names))
    for rc in facts["roll_calls"]:
        dup = [o for o, n in Counter(v["official_id"] for v in rc["votes"] if v["official_id"]).items() if n > 1]
        if dup:
            out.append(f"{rc['id']}: two vote rows for {', '.join(sorted(dup))}")
    rc_ids = {r["id"] for r in facts["roll_calls"]}
    pairs = Counter((e["item_id"], e["ref"]) for e in facts["item_events"] if e["type"] == "roll_call")
    out += [f"item {i}: {n} roll_call events for {r}" for (i, r), n in sorted(pairs.items()) if n > 1]
    out += [f"item {i}: roll_call event points at missing {r}" for (i, r) in sorted(pairs) if r not in rc_ids]
    return out


def main(argv=None) -> int:
    path = Path((argv or sys.argv[1:] or [str(ROOT / "data" / "facts.json")])[0])
    facts = json.loads(path.read_text(encoding="utf-8"))
    bad = one_vote_violations(facts)
    rcs = facts["roll_calls"]
    print(f"{path}: {len(rcs)} roll calls, {sum(r['verification']['status'] == 'verified' for r in rcs)} verified, "
          f"{sum(r['item_id'] in consent_item_ids(facts) for r in rcs)} consent; one-vote violations: {len(bad)}")
    for b in bad:
        print("  " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
