"""Check config/seats.yml against the facts and the current roster (docs/design/landing-search-nav.md 4.1).

Checks, the same for everyone:
  1. every official with a vote in any roll call holds exactly one seat on that meeting's date;
  2. no seat has two holder records on one date, and no official holds two seats on one date;
  3. every seat in the current roster has an open record (no end) for the roster's person, and nobody else holds an
     open record for it.
Prints the problems and exits 1 when there are any. `python -I tools/seat_check.py`
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _covers(row: dict, date: str) -> bool:
    return str(row["start"]) <= date and (row.get("end") is None or date <= str(row["end"]))


def check(facts: dict, rows: list[dict], roster: dict | None = None) -> list[str]:
    problems = []
    dates = {m["id"]: m["date"] for m in facts["meetings"]}
    by_official = defaultdict(list)
    by_seat = defaultdict(list)
    for r in rows:
        by_seat[r["seat"]].append(r)
        if r.get("official_id"):
            by_official[r["official_id"]].append(r)

    voters = set()
    for rc in facts["roll_calls"]:
        date = dates[rc["meeting_id"]]
        for v in rc["votes"]:
            if v.get("official_id"):
                voters.add((date, v["official_id"], rc["id"]))
    reported = set()
    for date, oid, rc_id in sorted(voters):
        held = {r["seat"] for r in by_official.get(oid, []) if _covers(r, date)}
        if len(held) != 1 and (date, oid) not in reported:
            reported.add((date, oid))
            problems.append(f"{date} {oid}: votes in {rc_id} but holds {len(held)} seats then ({sorted(held)})")

    for seat, rs in by_seat.items():
        rs = sorted(rs, key=lambda r: str(r["start"]))
        for a, b in zip(rs, rs[1:]):
            if a.get("end") is None or str(b["start"]) <= str(a["end"]):
                problems.append(f"{seat}: records overlap ({a.get('official_id')} from {a['start']}, "
                                f"{b.get('official_id')} from {b['start']})")
    for oid, rs in by_official.items():
        rs = sorted(rs, key=lambda r: str(r["start"]))
        for a, b in zip(rs, rs[1:]):
            if a["seat"] != b["seat"] and (a.get("end") is None or str(b["start"]) <= str(a["end"])):
                problems.append(f"{oid}: holds {a['seat']} and {b['seat']} at once")

    if roster:
        for seat, who in roster["seats"].items():
            open_ = [r.get("official_id") for r in by_seat.get(seat, []) if r.get("end") is None]
            if open_ != [who["official_id"]]:
                problems.append(f"{seat}: roster lists {who['official_id']}, open records name {open_}")
    return problems


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--facts", default=str(ROOT / "data" / "facts.json"))
    ap.add_argument("--seats", default=str(ROOT / "config" / "seats.yml"))
    ap.add_argument("--roster", default=None, help="default: config/localities/<locality>/roster-current.yml")
    a = ap.parse_args(argv)
    roster_path = Path(a.roster) if a.roster else ROOT / "config" / "localities" / locality() / "roster-current.yml"
    facts = json.loads(Path(a.facts).read_text(encoding="utf-8"))
    rows = yaml.safe_load(Path(a.seats).read_text(encoding="utf-8")) or []
    roster = yaml.safe_load(roster_path.read_text(encoding="utf-8")) if roster_path.is_file() else None
    problems = check(facts, rows, roster)
    for p in problems:
        print(p)
    print(f"{len(rows)} holder records, {len(problems)} problems")
    return 1 if problems else 0


def locality() -> str:
    site = ROOT / "config" / "site.yml"
    if site.is_file():
        return (yaml.safe_load(site.read_text(encoding="utf-8")) or {}).get("locality", "montgomery-tn")
    return "montgomery-tn"


if __name__ == "__main__":
    sys.exit(main())
