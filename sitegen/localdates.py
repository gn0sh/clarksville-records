"""Reader-facing dates (docs/architecture/local-dates.md; problem family feeds/entry-date-is-local-day).

Invariant: every date the site shows to a reader is the site_timezone (America/Chicago) calendar day of the instant;
stored timestamps stay UTC; meeting dates are civil dates and are never shifted.

A source record's `fetched_at` is the UTC day of its manifest row's first_fetched_at (the collectors write
first_fetched_at[:10]). A UTC day alone cannot be turned into a local day: a fetch at 22:38 in Clarksville is the next
UTC day. So the day shown comes from the instant: the manifest row with the same url and sha256 (load(), at the start
of every build), used only when the stored day is that instant's UTC day (the same fetch). A source with no such row
shows its stored day labelled UTC_LABEL. Nothing here guesses a day.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config

UTC_LABEL = " (UTC day)"

# (url, sha256) -> first_fetched_at, from the manifests the current build read (load). Empty: no instants known.
_INSTANTS: dict[tuple[str, str], datetime] = {}


class LocalDatesError(ValueError):
    pass


def zone(tz: str | None = None) -> ZoneInfo:
    return ZoneInfo(tz or config.SITE["site_timezone"])


def local_day(ts, tz: str | None = None) -> str:
    """The site_timezone calendar day (YYYY-MM-DD) of an instant: an aware datetime, or an ISO 8601 timestamp with
    an offset. A bare day, a date or a naive timestamp names no instant and raises ValueError: it is never shifted."""
    if isinstance(ts, str):
        if "T" not in ts and " " not in ts.strip():
            raise ValueError(f"{ts!r} is a day, not an instant: it cannot be converted")
        ts = datetime.fromisoformat(ts)
    if not isinstance(ts, datetime):
        raise ValueError(f"{ts!r} is not an instant")
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(f"{ts!r} has no time zone")
    return ts.astimezone(zone(tz)).date().isoformat()


def read_manifest(path) -> dict[tuple[str, str], datetime]:
    """{(url, sha256): first_fetched_at} of one collector manifest. Every row must have both and an aware instant."""
    p = Path(path)
    if not p.is_absolute():
        p = config.REPO_ROOT / p
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise LocalDatesError(f"fetch_manifests: no manifest {p}") from None
    except json.JSONDecodeError as exc:
        raise LocalDatesError(f"{p}: not valid JSON ({exc})") from None
    if not isinstance(rows, list):
        raise LocalDatesError(f"{p}: a manifest is a list of rows")
    out = {}
    for n, row in enumerate(rows, 1):
        url, sha, raw = (row.get(k) if isinstance(row, dict) else None for k in ("url", "sha256", "first_fetched_at"))
        if not (isinstance(url, str) and url and isinstance(sha, str) and sha):
            raise LocalDatesError(f"{p}: row {n} has no url or sha256")
        try:
            when = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            raise LocalDatesError(f"{p}: {url!r} has no usable first_fetched_at ({raw!r})") from None
        if when.tzinfo is None:
            raise LocalDatesError(f"{p}: {url!r} first_fetched_at has no time zone ({raw!r})")
        out[(url, sha)] = when
    return out


def load(paths) -> int:
    """Replace the known instants with the rows of `paths` (None or empty: none known). Returns the row count."""
    rows: dict[tuple[str, str], datetime] = {}
    for p in paths or ():
        rows.update(read_manifest(p))
    use(rows)
    return len(rows)


def use(rows: dict[tuple[str, str], datetime]) -> None:
    _INSTANTS.clear()
    _INSTANTS.update(rows)


def instant(url: str | None, sha256: str | None, day: str | None) -> datetime | None:
    """The recorded instant of the fetch stored as `day` (a UTC day) for (url, sha256), or None when there is no
    such row or the row is another fetch (its UTC day is not `day`)."""
    if not (url and sha256 and day):
        return None
    when = _INSTANTS.get((url, sha256))
    if when is None or when.astimezone(timezone.utc).date().isoformat() != str(day)[:10]:
        return None
    return when


def day_of(url: str | None, sha256: str | None, day: str | None) -> str | None:
    """The fetch day a page prints: the local day of the recorded instant, else the stored UTC day, labelled.
    No stored day: returned as is (None or "")."""
    if not day:
        return day
    when = instant(url, sha256, day)
    return local_day(when) if when is not None else f"{str(day)[:10]}{UTC_LABEL}"


def fetched(src: dict | None) -> str | None:
    """day_of for a facts file's source record (url, sha256, fetched_at)."""
    if not src:
        return None
    return day_of(src.get("url"), src.get("sha256"), src.get("fetched_at"))


def _days(srcs) -> tuple[list[str], bool] | None:
    """(sorted plain days, exact) of source records: local days when every source has its recorded instant, else
    every stored UTC day (exact False: a local and a UTC day are never compared). None: no fetch day."""
    rows = [s for s in srcs if s and s.get("fetched_at")]
    if not rows:
        return None
    whens = [instant(s.get("url"), s.get("sha256"), s["fetched_at"]) for s in rows]
    if all(w is not None for w in whens):
        return sorted(local_day(w) for w in whens), True
    return sorted(str(s["fetched_at"])[:10] for s in rows), False


def span(srcs) -> tuple[str, str] | None:
    """(earliest, latest) fetch day of source records, as pages print them (_days; a UTC day labelled)."""
    d = _days(srcs)
    if d is None:
        return None
    label = "" if d[1] else UTC_LABEL
    return d[0][0] + label, d[0][-1] + label


def days(srcs) -> tuple[list[str], bool] | None:
    """(sorted plain fetch days, exact) of source records, as pages print them: site_timezone days when every source
    has its recorded instant, else stored UTC days (exact False). None: no fetch day."""
    return _days(srcs)


def latest(srcs) -> tuple[str, bool] | None:
    """(latest fetch day as a plain YYYY-MM-DD, exact): exact False means it is a stored UTC day (a machine field
    such as the morning note's data_as_of carries the flag beside the day, never a label in it)."""
    d = _days(srcs)
    return (d[0][-1], d[1]) if d else None
