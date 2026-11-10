"""STUB (T3, frontend) for the morning-note digest generator. T1 (backend) owns this file: at merge, take T1's
sitegen/morning.py. T3 uses only `select(day, lists, seats)` and `day(date, ...)` with the contract's signatures and
output shape (docs/architecture/morning-note.md, "Output contract"); this stub implements `select()` to the contract's
rule so the JS parity test (tests/test_morning_page.py) can run before T1 lands, and `day()` returns a quiet day.
"""
from __future__ import annotations

from . import config

SCHEMA = "morning-note/1"


def _num(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _seat_match(entry: dict, list_key: str, seats: dict | None) -> bool:
    seats = seats or {}
    d, w = _num(seats.get("district")), _num(seats.get("ward"))
    if list_key == "zoning":
        return (d is not None and _num(entry.get("district")) == d) or \
               (w is not None and _num(entry.get("ward")) == w)
    if list_key == "seats":   # the county's documents for a district, a council's for a ward
        return d is not None if entry.get("body") == config.SITE["county_key"] else w is not None
    return True


def select(day: dict, lists, seats: dict | None) -> list[dict]:
    """The entries of `day` one subscriber gets: on one of `lists`, and for zoning and seats also matching `seats`
    ({district, ward}, each a number or None). Day order kept."""
    keys = list(lists or [])
    return [e for e in day.get("entries") or []
            if any(k in keys and _seat_match(e, k, seats) for k in e.get("lists") or [])]


def day(date: str, **_ignored) -> dict:
    """STUB: a quiet day (T1 computes the real entries from the collectors' manifests)."""
    cfg = config.SITE.get("morning_note") or {}
    return {"schema": SCHEMA, "date": date, "window": {"from": "", "to": ""}, "data_as_of": date,
            "lists": [{"key": x["key"], "label": x["label"]} for x in cfg.get("lists") or []],
            "entries": [], "unplaced_zoning": 0}
