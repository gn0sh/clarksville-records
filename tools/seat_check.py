"""Check config/localities/<locality>/seats.yml against the facts and the current roster (docs/design/landing-search-nav.md 4.1).

Checks, the same for everyone:
  1. every official with a vote in any roll call holds exactly one seat on that meeting's date;
  2. no seat has two holder records on one date, and no official holds two seats on one date;
  3. every seat in the current roster has an open record (no end) for the roster's person, and nobody else holds an
     open record for it;
  4. every open observed record was seen at L, the latest meeting the records were read to (read_to; the site's
     wording "from X to L"): its `last_source` is a roll-call page of that meeting (provenance/open-run-latest). L is
     the latest meeting in the facts until a newer one is collected; the rows are then stale, not wrong, and the site
     says "the latest meeting read for seats" (M1 pipeline/seats-stale-on-new-county-meeting); main() prints a note.
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


def _pages_at(facts: dict) -> dict:
    """"<url>#page=N" -> the meeting dates of the roll calls printed on that page."""
    dates = {m["id"]: m["date"] for m in facts["meetings"]}
    urls = {s["id"]: s.get("url") for s in facts.get("sources", [])}
    at = defaultdict(set)
    for rc in facts["roll_calls"]:
        if rc.get("source_id") in urls and rc.get("page"):
            at[f"{urls[rc['source_id']]}#page={rc['page']}"].add(dates[rc["meeting_id"]])
    return at


def read_to(facts: dict, rows: list[dict]) -> str | None:
    """L, the latest meeting the records were read to: the latest end, or meeting of an open record's last page,
    over the observed records (the site words open records to it: sitegen/seats.py stamp_seen). Without observed
    records, the latest meeting in the facts. It is earlier than the latest meeting collected only when a meeting
    has been collected since tools/derive_seats.py last ran (M1 pipeline/seats-stale-on-new-county-meeting)."""
    at = _pages_at(facts)
    seen = []
    for r in rows:
        if r.get("dates") == "observed":
            seen += [str(r["end"])] if r.get("end") else list(at.get(r.get("last_source"), ()))
    if seen:
        return max(seen)
    dates_all = [m["date"] for m in facts["meetings"]]
    return max(dates_all) if dates_all else None


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

    latest = read_to(facts, rows)
    at = _pages_at(facts)
    for r in rows:
        if r.get("dates") == "observed" and r.get("end") is None and latest not in at.get(r.get("last_source"), ()):
            problems.append(f"{r['seat']}: open record for {r.get('official_id')} was last seen at "
                            f"{sorted(at.get(r.get('last_source'), ())) or r.get('last_source')}, not at the latest "
                            f"meeting the records were read to ({latest})")

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
    ap.add_argument("--seats", default=None, help="default: config/localities/<locality>/seats.yml")
    ap.add_argument("--roster", default=None, help="default: config/localities/<locality>/roster-current.yml")
    a = ap.parse_args(argv)
    roster_path = Path(a.roster) if a.roster else ROOT / "config" / "localities" / locality() / "roster-current.yml"
    facts = json.loads(Path(a.facts).read_text(encoding="utf-8"))
    seats_path = Path(a.seats) if a.seats else ROOT / "config" / "localities" / locality() / "seats.yml"
    rows = yaml.safe_load(seats_path.read_text(encoding="utf-8")) or []
    roster = yaml.safe_load(roster_path.read_text(encoding="utf-8")) if roster_path.is_file() else None
    problems = check(facts, rows, roster)
    for p in problems:
        print(p)
    dates_all = [m["date"] for m in facts["meetings"]]
    seen, newest = read_to(facts, rows), (max(dates_all) if dates_all else None)
    if seen and newest and seen < newest:
        print(f"WARNING: the records are read to {seen}; the facts hold meetings to {newest}. "
              f"Re-run tools/derive_seats.py to read the newer roll calls.")
    print(f"{len(rows)} holder records, {len(problems)} problems")
    return 1 if problems else 0


def locality() -> str:
    site = ROOT / "config" / "site.yml"
    if site.is_file():
        return (yaml.safe_load(site.read_text(encoding="utf-8")) or {}).get("locality", "montgomery-tn")
    return "montgomery-tn"


if __name__ == "__main__":
    sys.exit(main())
