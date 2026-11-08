"""Derive county commission seat holder records from the district numbers printed in the minutes' roll-call tables.

Each "District / Commissioner / Vote" table prints the district number before each name ("4  Rickey Ray  Y"). For
every roll call in data/facts.json this reads the page text the parser read (text layer and OCR, whichever exist),
finds each voter's printed name and the number just before it, and counts one observation per (page, reading, table
position). Per meeting, an official's district is the number most observations agree on; OCR misreads ("71" for
21, "l" for 1) are outvoted by the other tables and readings of the same meeting. Nothing is guessed: a meeting
where an official has no readable number, or two numbers tie, is listed under `unknown`; two people in one district
at one meeting are listed under `conflicts`.

Holder records are runs of meetings where one official holds one district number, split at `lines_effective`
(config/site.yml), so old-lines and current-lines periods are separate rows. Every row is `dates: observed`
(architecture, "Invariant: derived vs stated"): `start`/`end` are the first and last meeting whose roll-call table
prints that holder in that slot, never term dates; `source` cites the first meeting's roll-call page and
`last_source` the last one's. The latest run of a seat that reaches the latest meeting in the facts (the site's
"L, the latest meeting collected": the latest meeting date in data/facts.json, not the latest one read here) has
no end, and its `last_source` is a roll-call page of that meeting; a run that stops before it keeps its end, so it
is never shown as seen at L. The district count and cutover default to config/site.yml.

  python -I tools/derive_seats.py --text-dir PATH/data/text --ocr-dir PATH/data/ocr
      (writes config/localities/<locality>/seats.yml and seat-evidence.json there)

`--extra` (default config/localities/<locality>/seats-extra.yml) names a YAML file of rows from other sources (e.g.
the county mayor from the Elected Officials List, `dates: sourced` with the source's own `printed` wording),
appended unchanged after the derived rows.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def site_config() -> dict:
    import yaml
    return yaml.safe_load((ROOT / "config" / "site.yml").read_text(encoding="utf-8"))
NUM = r"(?<![\w.$,])(\d{1,2})[ \t]+(?:[—–-][ \t]*)?"      # a district number, then the name on the same line
VACANT = re.compile(NUM + r"Vacan\w*", re.I)


def _pages(sha: str, page: int, text_dir: Path, ocr_dir: Path) -> list[tuple[str, str]]:
    """(reading, text) for the roll call's page, from every reading on disk."""
    out = []
    tp = text_dir / f"{sha}.pages.json"
    if tp.is_file():
        pages = json.loads(tp.read_text(encoding="utf-8"))
        if 0 < page <= len(pages) and pages[page - 1]:
            out.append(("text-layer", pages[page - 1]))
    op = ocr_dir / f"{sha[:16]}-p{page}.txt"
    if op.is_file():
        out.append(("ocr", op.read_text(encoding="utf-8")))
    return out


def _name_re(names: set[str]) -> re.Pattern:
    alts = sorted({n for n in names if n}, key=len, reverse=True)
    return re.compile(NUM + "(" + "|".join(re.escape(a) for a in alts) + r")(?![A-Za-z])")


def observe(facts: dict, text_dir: Path, ocr_dir: Path, only_verified: bool = True):
    """-> obs[(meeting_date, official_id)] = Counter(district), vac[meeting_date] = Counter(district),
    cite[(meeting_date, official_id, district)] = (source_id, page)."""
    sources = {s["id"]: s for s in facts["sources"]}
    meetings = {m["id"]: m for m in facts["meetings"]}
    obs: dict = defaultdict(Counter)
    vac: dict = defaultdict(Counter)
    cite: dict = {}
    seen = set()
    # every spelling that names exactly one official anywhere in the facts (names, aliases, raw table and attendance
    # names), so members marked absent, who sit in the table with no vote, are found too
    names = defaultdict(set)
    for o in facts["officials"]:
        for n in [o["name"], *o.get("aliases", [])]:
            names[n].add(o["id"])
    for m in facts["meetings"]:
        for a in m.get("attendance", []):
            if a.get("official_id"):
                names[a["raw_name"]].add(a["official_id"])
    for rc in facts["roll_calls"]:
        for v in rc["votes"]:
            if v.get("official_id"):
                names[v["raw_name"]].add(v["official_id"])
    spellings = {n: next(iter(ids)) for n, ids in names.items() if len(ids) == 1 and len(n) >= 6}
    pat = _name_re(set(spellings))
    for rc in facts["roll_calls"]:
        if only_verified and rc["verification"]["status"] != "verified":
            continue          # e.g. an earlier year's roll call reprinted as an exhibit (2024-09-09 p. 50, item 20-9-14)
        src = sources[rc["source_id"]]
        date = meetings[rc["meeting_id"]]["date"] if "date" in meetings[rc["meeting_id"]] else rc["meeting_id"][:10]
        by_name = spellings
        for reading, text in _pages(src["sha256"], rc["page"], text_dir, ocr_dir):
            for m in pat.finditer(text):
                key = (src["id"], rc["page"], reading, m.start(2), m.group(2))
                if key in seen:
                    continue
                seen.add(key)
                oid, d = by_name[m.group(2)], int(m.group(1))
                obs[(date, oid)][d] += 1
                cite.setdefault((date, oid, d), (src["id"], rc["page"]))
            for m in VACANT.finditer(text):
                key = (src["id"], rc["page"], reading, m.start(), "vacant")
                if key not in seen:
                    seen.add(key)
                    vac[date][int(m.group(1))] += 1
                    cite.setdefault((date, None, int(m.group(1))), (src["id"], rc["page"]))
    return obs, vac, cite


def decide(obs, vac, n_seats: int):
    """Per meeting: official -> district by majority, plus the lists of what could not be decided."""
    held: dict = defaultdict(dict)        # date -> {district: official_id or None (vacant)}
    unknown, conflicts = [], []
    claims: dict = defaultdict(list)
    for (date, oid), cnt in sorted(obs.items()):
        top = cnt.most_common()
        valid = [(d, c) for d, c in top if 1 <= d <= n_seats]
        if not valid or (len(valid) > 1 and valid[0][1] == valid[1][1]):
            unknown.append({"date": date, "official_id": oid, "readings": dict(cnt)})
            continue
        claims[(date, valid[0][0])].append(oid)
    for (date, d), oids in sorted(claims.items()):
        if len(oids) > 1:          # two people read into one slot: neither is placed
            conflicts.append({"date": date, "district": d, "officials": sorted(oids)})
            continue
        held[date][d] = oids[0]
    for date, cnt in sorted(vac.items()):
        for d, _c in cnt.items():
            if 1 <= d <= n_seats and d not in held[date]:
                held[date][d] = None
    return held, unknown, conflicts


def latest_meeting(facts: dict) -> str | None:
    """The latest meeting collected, as the site computes it (sitegen.views: max of the meetings' dates)."""
    dates = [m["date"] for m in facts["meetings"]]
    return max(dates) if dates else None


def runs(held: dict, cite: dict, sources: dict, lines_effective: str, n_seats: int, prefix: str = "district",
         latest: str | None = None):
    """Holder runs per seat. `latest` is the latest meeting in the facts (latest_meeting); a run is left open only
    when it reaches that meeting. Without it, the latest meeting read here."""
    dates = sorted(held)
    latest = latest or (dates[-1] if dates else None)
    rows = []
    for d in range(1, n_seats + 1):
        seq = [(date, held[date][d]) for date in dates if d in held[date]]
        cur = None
        for date, oid in seq:
            period = "old" if date < lines_effective else "current"
            sid, page = cite[(date, oid, d)]
            here = f"{sources[sid]['url']}#page={page}"
            if cur and cur["official_id"] == oid and cur["lines"] == period:
                cur["end"], cur["last_source"] = date, here
                continue
            cur = {"official_id": oid, "seat": f"{prefix}-{d}", "dates": "observed", "start": date, "end": date,
                   "lines": period, "source": here, "last_source": here}
            rows.append(cur)
        if cur and cur["end"] == latest:
            cur["end"] = None
    for r in rows:
        r["note"] = ("Dates are the first and last meetings whose roll-call tables print this name in this district "
                     "slot; the term's own start and end are not yet sourced.") if r["official_id"] else \
                    "The roll-call table prints this district slot as vacant."
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--facts", default=str(ROOT / "data" / "facts.json"))
    ap.add_argument("--text-dir", default=str(ROOT / "data" / "text"))
    ap.add_argument("--ocr-dir", default=str(ROOT / "data" / "ocr"))
    cfg = site_config()
    loc = ROOT / "config" / "localities" / cfg["locality"]
    ap.add_argument("--seats", type=int, default=int(cfg["district_count"]))
    ap.add_argument("--lines-effective", default=str(cfg["lines_effective"]))
    ap.add_argument("--extra", default=str(loc / "seats-extra.yml"))
    ap.add_argument("--out", default=str(loc / "seats.yml"))
    ap.add_argument("--evidence", default=str(loc / "seat-evidence.json"))
    a = ap.parse_args(argv)
    facts = json.loads(Path(a.facts).read_text(encoding="utf-8"))
    obs, vac, cite = observe(facts, Path(a.text_dir), Path(a.ocr_dir))
    held, unknown, conflicts = decide(obs, vac, a.seats)
    sources = {s["id"]: s for s in facts["sources"]}
    rows = runs(held, cite, sources, a.lines_effective, a.seats, latest=latest_meeting(facts))
    import yaml
    if a.extra and Path(a.extra).is_file():
        rows += yaml.safe_load(Path(a.extra).read_text(encoding="utf-8")) or []
    header = ("# Seat holder records (docs/design/landing-search-nav.md 4.1). GENERATED by tools/derive_seats.py from the\n"
              "# district numbers printed in the minutes' roll-call tables, plus the rows in seats-extra.yml.\n"
              "# dates: observed = first/last meeting whose roll-call table prints the holder (never term dates);\n"
              "# dates: sourced = the source's own term wording in `printed` (architecture, derived vs stated).\n"
              "# Do not hand-edit derived rows: fix the source reading or add a row to the extra file and re-run.\n")
    Path(a.out).write_text(header + yaml.safe_dump(rows, sort_keys=False, allow_unicode=True, width=200),
                           encoding="utf-8")
    disagree = [{"date": dt, "official_id": oid, "readings": dict(c)} for (dt, oid), c in sorted(obs.items())
                if len(c) > 1]
    ev = {"generated_by": "tools/derive_seats.py", "meetings": len(held),
          "observations": sum(sum(c.values()) for c in obs.values()),
          "unknown": unknown, "conflicts": conflicts, "outvoted_readings": disagree,
          "held": {dt: {str(d): o for d, o in sorted(v.items())} for dt, v in sorted(held.items())}}
    Path(a.evidence).write_text(json.dumps(ev, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "meetings": len(held), "unknown": len(unknown), "conflicts": conflicts,
                      "outvoted": len(disagree)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
