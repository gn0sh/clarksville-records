"""Seats, holder records and the landing map's geometry (docs/design/landing-search-nav.md 3.2, 4.1, 6A).

Holder records come only from `config/seats.yml` rows, each with a source. Nothing here guesses a seat: an official
with no row has no seat label and is listed under "Seat not yet recorded". When the file is absent the whole site
falls back to no labels and one officials list. One rule for everyone (N1): current = no `end`, or `end` after the
latest meeting in the facts.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import yaml

from . import config


class SeatsError(Exception):
    pass


SEAT_RE = re.compile(r"^(district|ward)-(\d{1,2})$")


def _date(value, where: str) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    raise SeatsError(f"{where}: {value!r} is not a YYYY-MM-DD date")


def seat_label(seat: str) -> str:
    """'district-7' -> 'District 7', 'ward-3' -> 'Ward 3', other seats by their configured label."""
    m = SEAT_RE.match(seat)
    if m:
        word = config.SITE["district_label"] if m.group(1) == "district" else config.SITE["ward_label"]
        return f"{word} {int(m.group(2))}"
    for s in config.SITE["other_seats"]:
        if s["seat"] == seat:
            return s["label"]
    return seat.replace("-", " ").title()  # as the source names it; the row's seat id is the source's wording


def seat_order(seat: str) -> tuple:
    """Districts by number, then wards by number, then other seats in the configured order (design 6A.3)."""
    m = SEAT_RE.match(seat)
    if m:
        return (0 if m.group(1) == "district" else 1, int(m.group(2)), "")
    others = [s["seat"] for s in config.SITE["other_seats"]]
    return (2, others.index(seat) if seat in others else len(others), seat)


def district_number(seat: str) -> int | None:
    m = SEAT_RE.match(seat)
    return int(m.group(2)) if m and m.group(1) == "district" else None


def load_rows(path: Path | None) -> list[dict] | None:
    """The roster rows, or None when there is no roster file (the site then shows no seat labels)."""
    if path is None or not Path(path).is_file():
        return None
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    if isinstance(raw, dict):  # allow {seats: [...]} as well as a top-level list
        raw = raw.get("seats", [])
    if not isinstance(raw, list):
        raise SeatsError(f"{path}: expected a list of holder records")
    rows = []
    for n, r in enumerate(raw, 1):
        where = f"{path} row {n}"
        if not isinstance(r, dict) or "seat" not in r or "source" not in r:
            raise SeatsError(f"{where}: needs seat and source")
        src = r.get("source") or ""
        if not (isinstance(src, str) and src.startswith("https://")):
            raise SeatsError(f"{where}: every holder record needs an https source (N4)")
        start = _date(r.get("start"), where)
        if start is None:
            raise SeatsError(f"{where}: needs a start date")
        rows.append({"official_id": r.get("official_id") or None, "seat": str(r["seat"]), "start": start,
                     "end": _date(r.get("end"), where), "source": src, "note": r.get("note")})
    return rows


def load_districts(path: Path | None) -> dict | None:
    """The map file, or None when it has not been produced yet (the landing then shows the list only)."""
    if path is None or not Path(path).is_file():
        return None
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("source_url", "fetched", "viewBox", "districts"):
        if key not in d:
            raise SeatsError(f"{path}: missing {key!r}")
    if not str(d["source_url"]).startswith("https://"):
        raise SeatsError(f"{path}: source_url must be https (N4)")
    for x in d["districts"]:
        if not re.fullmatch(r"[MmLlHhVvCcSsQqTtAaZz0-9eE.,\s+-]+", x["path"]):
            raise SeatsError(f"{path}: district {x.get('number')} path has characters outside SVG path data")
    return d


def source_label(url: str) -> str:
    """'p. 3' when the source names a page, else 'source'. The link itself is the source (N4)."""
    m = re.search(r"#page=(\d+)", url)
    return f"p. {m.group(1)}" if m else "source"


class Seats:
    """Holder records over one facts index. `loaded` is False when there is no roster file."""

    def __init__(self, rows: list[dict] | None, officials: dict, latest: str):
        self.loaded = rows is not None
        self.latest = latest
        self.records: list[dict] = []
        unknown = set()
        for r in rows or []:
            oid = r["official_id"]
            if oid is not None and oid not in officials:
                unknown.add(oid)  # a roster person with no facts yet: no page to link, so no record here
                continue
            current = r["end"] is None or r["end"] > latest
            self.records.append({**r, "label": seat_label(r["seat"]), "current": current,
                                 "district": district_number(r["seat"]),
                                 "src_label": source_label(r["source"])})
        if unknown:
            print(f"WARNING: config/seats.yml names {len(unknown)} official id(s) not in the facts: "
                  f"{', '.join(sorted(unknown))}", file=sys.stderr)
        self.records.sort(key=lambda r: (seat_order(r["seat"]), r["start"]))
        self.by_official: dict[str, list[dict]] = {}
        for r in self.records:
            if r["official_id"]:
                self.by_official.setdefault(r["official_id"], []).append(r)

    def of(self, official_id: str) -> list[dict]:
        """An official's records, newest first by start date."""
        return sorted(self.by_official.get(official_id, []), key=lambda r: r["start"], reverse=True)

    def is_current(self, official_id: str) -> bool:
        return any(r["current"] for r in self.by_official.get(official_id, []))

    def on(self, official_id: str | None, date: str) -> str | None:
        """The seat label held on a date ('District 7', or 'District 7 (old lines)' before the 2022 lines)."""
        if not self.loaded or not official_id:
            return None
        for r in self.by_official.get(official_id, []):
            if r["start"] <= date and (r["end"] is None or date <= r["end"]):
                old = r["district"] is not None and date < config.SITE["lines_effective"]
                return r["label"] + (" (old lines)" if old else "")
        return None

    def seat_text(self, official_id: str) -> str | None:
        """6A.2: 'District 7' for a current holder; former: 'District 7, 2018-09-01 to 2022-08-31'; several seats
        newest first, joined by '; '. None when there is no roster or no record (never guessed)."""
        recs = self.of(official_id)
        if not self.loaded or not recs:
            return None
        parts = []
        for r in recs:
            if r["current"]:
                parts.append(r["label"])
            else:
                parts.append(f"{r['label']}, {r['start']} to {r['end']}")
        return "; ".join(parts)

    def header_text(self, official_id: str) -> str | None:
        """Official page header: 'District 7, from 2022-09-01' (current) or the former form."""
        recs = self.of(official_id)
        if not self.loaded:
            return None
        if not recs:
            return "Seat not yet recorded"
        return "; ".join(f"{r['label']}, from {r['start']}" if r["current"] else f"{r['label']}, {r['start']} to {r['end']}"
                         for r in recs)

    def for_seat(self, seat: str) -> list[dict]:
        return [r for r in self.records if r["seat"] == seat]

    def current_of_seat(self, seat: str) -> dict | None:
        """The current holder record (person or vacancy), latest start first."""
        cur = [r for r in self.for_seat(seat) if r["current"]]
        return max(cur, key=lambda r: r["start"]) if cur else None
