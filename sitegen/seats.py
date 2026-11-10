"""Seats, holder records and the landing map's geometry (docs/design/landing-search-nav.md 3.2, 4.1, 6A).

Holder records come only from the roster rows (config.SEATS_PATH), each with a source. Nothing here guesses a seat: an official
with no row has no seat label and is listed under "Seat not yet recorded". When the file is absent the whole site
falls back to no labels and one officials list. One rule for everyone (N1): current = no `end` and seen at L, the
latest meeting the rows were read to (stamp_seen; the latest meeting in the facts unless seats.yml is older), or an
`end` after it. Current is derived and is shown only with its basis line.
"""
from __future__ import annotations

import datetime as dt
import json
import re
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


def _https(value, where: str, key: str) -> str:
    if not (isinstance(value, str) and value.startswith("https://")):
        raise SeatsError(f"{where}: {key} must be an https link (N4)")
    return value


def load_rows(path: Path | None) -> list[dict] | None:
    """The roster rows, or None when there is no roster file (the site then shows no seat labels).

    Shape (architecture, invariant `provenance`): every row says `dates: observed | sourced`. An observed row's
    start/end are the first and last meetings whose roll-call tables print the holder in that slot, and it needs
    `last_source` (the last meeting's page). A sourced row needs `printed`, the source's own term wording; its
    start/end are sort keys only and are never shown. A row that breaks this is a SeatsError."""
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
        src = _https(r.get("source"), where, "source")
        start = _date(r.get("start"), where)
        if start is None:
            raise SeatsError(f"{where}: needs a start date")
        kind = r.get("dates")
        if kind not in ("observed", "sourced"):
            raise SeatsError(f"{where}: needs dates: observed or dates: sourced")
        last_src = printed = None
        if kind == "observed":
            last_src = _https(r.get("last_source"), where, "last_source")
        else:
            printed = r.get("printed")
            if not (isinstance(printed, str) and printed.strip()):
                raise SeatsError(f"{where}: a sourced row needs printed (the source's own term wording)")
            printed = printed.strip()
        lines = r.get("lines")
        if lines not in (None, "old", "current"):
            raise SeatsError(f"{where}: lines must be old or current")
        rows.append({"official_id": r.get("official_id") or None, "seat": str(r["seat"]), "start": start,
                     "end": _date(r.get("end"), where), "source": src, "last_source": last_src,
                     "dates": kind, "printed": printed, "lines": lines, "note": r.get("note"),
                     "name": r.get("name")})
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
    wards = d.get("wards") or {}
    if wards.get("status") == "available":
        if not str(wards.get("source_url", "")).startswith("https://") or not wards.get("fetched"):
            raise SeatsError(f"{path}: wards need an https source_url and a fetch date (N4)")
        if sorted(w["number"] for w in wards.get("wards") or []) != list(range(1, config.SITE["ward_count"] + 1)):
            raise SeatsError(f"{path}: wards must be numbered 1 to {config.SITE['ward_count']}, once each")
        for x in wards["wards"]:
            if not re.fullmatch(r"[MLZ0-9. -]+", x["path"]):
                raise SeatsError(f"{path}: ward {x.get('number')} path has characters outside M/L/Z path data")
    return d


def source_label(url: str) -> str:
    """'p. 3' when the source names a page, else 'source'. The link itself is the source (N4)."""
    m = re.search(r"#page=(\d+)", url)
    return f"p. {m.group(1)}" if m else "source"


# The fixed wording of observed holder records (architecture, invariant `provenance`). `evidence` names what printed
# the holder in the seat ("roll calls" for the county; a council's attendance lists print each member's ward);
# `latest` names what the latest date L is. The county's wording is the default; a council passes its own.
COUNTY_WORDING = {"evidence": "roll calls", "latest": "the latest meeting collected",
                  "read_latest": "the latest meeting read for seats"}
# A record carried on by name only (council.extend_by_listings): the clause after its printed dates.
LISTED_WORDS = "listed by name in"


def stamp_seen(rows: list[dict] | None, facts: dict) -> list[dict] | None:
    """Each observed row's `seen_to`, the last meeting it was seen at, and on every row `read_to`, the latest meeting
    the rows were read to (invariant `city-seats/current-holder-matches-latest-attendance`, M1
    `pipeline/seats-stale-on-new-county-meeting`).

    A closed row was seen to its end. An open row (no end) was seen at the meeting of its `last_source` page: the
    meeting of the confirmed or unconfirmed roll calls printed on that page. seats.yml is derived by hand
    (tools/derive_seats.py); when a newer meeting has been collected since, the rows are read to an earlier meeting
    than the facts hold, and Seats words its dates to that meeting, never to one the cited page does not show. A row
    whose last page holds no roll call in the facts (a roster, the fixture) gets no `seen_to`, and while any open row
    has none, no `read_to` is set (the rows are then read to the latest meeting collected, as before)."""
    if rows is None:
        return None
    urls = {s["id"]: s.get("url") for s in facts.get("sources", [])}
    dates = {m["id"]: m["date"] for m in facts.get("meetings", [])}
    at: dict[str, set] = {}
    for rc in facts.get("roll_calls", []):
        if rc.get("source_id") in urls and rc.get("page") and rc.get("meeting_id") in dates:
            at.setdefault(f"{urls[rc['source_id']]}#page={rc['page']}", set()).add(dates[rc["meeting_id"]])
    out = []
    for r in rows:
        seen = None
        if r.get("dates") == "observed":
            seen = r["end"] if r.get("end") else max(at.get(r.get("last_source") or "", ()), default=None)
        out.append({**r, "seen_to": seen})
    if any(r.get("dates") == "observed" and not r.get("end") and not r["seen_to"] for r in out):
        return out
    read = max((r["seen_to"] for r in out if r["seen_to"]), default=None)
    return [{**r, "read_to": read} for r in out] if read else out


def basis_text(rec: dict, latest: str, wording: dict | None = None) -> str:
    """The basis of a derived "Current" status, shown wherever "Current" is (architecture, invariant `provenance`)."""
    if rec["dates"] == "sourced":
        return "Current: the source prints no end to this term"
    w = wording or COUNTY_WORDING
    return f"Current: in the {rec.get('evidence') or w['evidence']} of {w['latest']}, {latest}"


class Seats:
    """Holder records over one facts index. `loaded` is False when there is no roster file.

    `dates_text` is the only place a holder record's dates become words. Records keep `start`/`end` for sorting and
    the on-date lookup, but nothing that leaves this class for a page carries them."""

    def __init__(self, rows: list[dict] | None, officials: dict, latest: str, wording: dict | None = None):
        self.loaded = rows is not None
        self.latest = latest
        self.wording = {**COUNTY_WORDING, **(wording or {})}
        # Rows read to an earlier meeting than the facts hold (stamp_seen `read_to`; seats.yml not yet re-derived
        # after a new meeting): L is that meeting, worded as such, so no open row is dated past what its page shows
        read_to = next((r["read_to"] for r in rows or [] if r.get("read_to")), None)
        if read_to and latest and read_to < latest:
            self.latest = read_to
            self.wording = {**self.wording, "latest": self.wording["read_latest"]}
        self.records: list[dict] = []
        # A roster person with no facts yet (e.g. a mayor, who has no roll call votes): kept, shown by name with their
        # seat and no history, never linked to a page that does not exist.
        self.roster_only: dict[str, dict] = {}
        for r in rows or []:
            oid = r["official_id"]
            if oid is not None and oid not in officials:
                name = r.get("name") or " ".join(w.capitalize() for w in oid.split("-"))
                parts = name.split()
                self.roster_only.setdefault(oid, {"id": oid, "name": name, "surname": parts[-1],
                                                  "given": " ".join(parts[:-1]), "title": "",
                                                  "aliases": []})
            # Current is derived: observed = seen at L, the latest meeting read (no end); sourced = no end printed.
            # An open observed row last seen before L is not current: it ends where it was last seen.
            end = r["end"]
            if r.get("dates") == "observed" and end is None and r.get("seen_to") and r["seen_to"] < self.latest:
                end = r["seen_to"]
            current = end is None or end > (self.latest if r.get("dates") == "observed" else latest)
            self.records.append({**r, "end": end, "label": seat_label(r["seat"]), "current": current,
                                 "district": district_number(r["seat"]),
                                 "src_label": source_label(r["source"]),
                                 "last_src_label": source_label(r["last_source"]) if r.get("last_source") else None})
        self.records.sort(key=lambda r: (seat_order(r["seat"]), r["start"]))
        self.by_official: dict[str, list[dict]] = {}
        for r in self.records:
            if r["official_id"]:
                self.by_official.setdefault(r["official_id"], []).append(r)

    # -- the one wording of a record's dates -----------------------------------------------------------------
    def dates_text(self, rec: dict) -> str:
        """Fixed wording (architecture, invariant `provenance`); L = the latest meeting collected."""
        if rec["dates"] == "sourced":
            return f"term {rec['printed']}, as the source prints it"
        ev = rec.get("evidence") or self.wording["evidence"]
        if rec["official_id"] is None:
            return f"shown as vacant in {ev} from {rec['start']} to {rec['end'] or self.latest}"
        to = f"{self.latest}, {self.wording['latest']}" if rec["end"] is None else rec["end"]
        if rec.get("printed_to"):
            # carried on by name only (council.extend_by_listings): what printed the seat, then the name-only lists
            seen = rec.get("seen_evidence") or ev
            return f"seen in {seen} from {rec['start']} to {rec['printed_to']}; {LISTED_WORDS} {ev} to {to}"
        if rec["end"] is None:
            return f"seen in {ev} from {rec['start']} to {to}"
        return f"seen in {ev} {rec['start']} to {rec['end']}"

    def basis(self, rec: dict) -> str:
        return basis_text(rec, self.latest, self.wording)

    def view(self, rec: dict) -> dict:
        """What a page may know about a record: label, wording and sources, never a bare start/end."""
        return {"label": rec["label"], "seat": rec["seat"], "dates_text": self.dates_text(rec),
                "src": rec["source"], "src_label": rec["src_label"],
                "last_src": rec.get("last_source"), "last_src_label": rec.get("last_src_label"),
                "current": rec["current"], "basis": self.basis(rec) if rec["current"] else None,
                "official_id": rec["official_id"], "lines": rec.get("lines")}

    def of(self, official_id: str) -> list[dict]:
        """An official's records, newest first by start date."""
        return sorted(self.by_official.get(official_id, []), key=lambda r: r["start"], reverse=True)

    def is_current(self, official_id: str) -> bool:
        return any(r["current"] for r in self.by_official.get(official_id, []))

    def on(self, official_id: str | None, date: str) -> str | None:
        """The seat label held on a date ('District 7', or 'District 7 (old lines)' for a record under the old
        lines). None when no record covers the date (the page then says the seat is not recorded; never guessed)."""
        if not self.loaded or not official_id:
            return None
        for r in self.by_official.get(official_id, []):
            # an open observed row covers no meeting after the one it was last seen at (a meeting collected since
            # seats.yml was derived is not read for seats yet: M1 pipeline/seats-stale-on-new-county-meeting)
            end = r["end"] if r["end"] is not None or r.get("dates") != "observed" else r.get("seen_to")
            if r["start"] <= date and (end is None or date <= end):
                if r.get("lines") is not None:
                    old = r["district"] is not None and r["lines"] == "old"
                else:
                    old = r["district"] is not None and date < config.SITE["lines_effective"]
                return r["label"] + (" (old lines)" if old else "")
        return None

    def seat_text(self, official_id: str) -> str | None:
        """6A.2: 'District 7' for a current holder (the label only; its basis is shown where "Current" is); former:
        'District 7 (seen in roll calls 2020-03-09 to 2022-08-08)'; several seats newest first, joined by '; '.
        None when there is no roster or no record (never guessed)."""
        recs = self.of(official_id)
        if not self.loaded or not recs:
            return None
        current = {r["label"] for r in recs if r["current"]}
        parts = []
        for r in recs:
            if r["current"]:
                if r["label"] not in parts:
                    parts.append(r["label"])
            elif r["label"] not in current:
                parts.append(f"{r['label']} ({self.dates_text(r)})")
        return "; ".join(parts)

    def header_text(self, official_id: str) -> str | None:
        """Official page header: 'District 7, seen in roll calls from X to L, the latest meeting collected'."""
        recs = self.of(official_id)
        if not self.loaded:
            return None
        if not recs:
            return "Seat not yet recorded"
        return "; ".join(f"{r['label']}, {self.dates_text(r)}" for r in recs)

    def for_seat(self, seat: str) -> list[dict]:
        return [r for r in self.records if r["seat"] == seat]

    def current_of_seat(self, seat: str) -> dict | None:
        """The current holder record (person or vacancy), latest start first."""
        cur = [r for r in self.for_seat(seat) if r["current"]]
        return max(cur, key=lambda r: r["start"]) if cur else None
