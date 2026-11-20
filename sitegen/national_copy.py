"""Daylight Digest, the D2 copy step (docs/architecture/daylight-national.md 4.6 "D2 copy step", 4.4.3 site 7,
11.1 row 16, 11.2, 12; task D2): the feeds of covered governments on a collected platform (Legistar), read from the
newest attested `national-data` (`data/national/bodies/<body id>.json`, 3.7) for the national builder.

The root is the `data/national` folder of that checkout, named by the environment variable RECORDS_NATIONAL_DATA
(`daily-update.yml`'s update job sets it to the folder it moved out of the attested checkout; unset: no national
data). The national builder (`national_pages.build_feeds`) is the only caller, and only while the switch is on, so
with `national.enabled: false` nothing here runs and the Clarksville build stays byte-identical (B5).

For each covered entry on a collected platform:
1. The entry itself must be one the collector may read: its platform's key mapping with a `client`, and a valid
   `host_ok` (R5, the loader's own check): else CopyError. `check_entry` runs this in the builder's load phase
   (section 12), before any national input is read, so a reviewed entry that fails it stops the PR's own checks;
   `copy_feed` repeats it (`national/r5-not-enforced`).
2. Read `bodies/<id>.json` (the id through `checked_id` first) and parse it per 4.4.3 (`collector.safe_json`): a
   missing file, a symlinked root, `bodies/` or file, a file over MAX_FILE_BYTES, or any error while reading or
   parsing, or a value that is not an object, is "file missing".
3. `clean_feed` with the entry's platform and client (the collector's files are not trusted as cleaned: S2a), then
   `bind_feed` against the current directory entry, then the date and instant checks, then the `daylight-upcoming/1`
   schema. A clean, bind or schema error is "file missing" too.
4. Nothing here raises on a national input (section 12; security S2b findings 1 and 2). Each case below gives
   `stale_feed(entry)`, sets `CopyCounts.state` to its fixed word and prints one `::warning::` line with the id and
   that word (and a count), never the file's text:
   - `withheld-items`: `withheld_stripped > 0`, the file carried items for an entry that is not shown (a collector
     bug, or a file collected while the entry was shown and read after a PR narrowed it to `items: withheld`).
     Raising would un-publish nothing (`national-data` is public) and would hold the narrowing PR's own deploy.
   - `bad-date`: a `meetings[].date` that is not ASCII `YYYY-MM-DD` or not a calendar day (`2026-02-30`).
   - `bad-instant`: a `checked_at` or `last_ok_at` that is not ASCII `YYYY-MM-DDTHH:MM:SSZ`, or lies before the
     epoch or more than a day after the build's instant.
   `review_mismatch` (shown, read under another review) is only counted: expected for the runs between a reviewed
   change and the next collect.

A missing file gives `stale_feed(entry)`: no meetings, `checked_at` the epoch and `last_ok_at` null, so the page says
it has no records yet and the government is marked stale (never "can't cover": a curated status only). Only the
cleaned, bound, checked feed (or that placeholder) reaches `digest/`; nothing else of the file is used. Errors and the
run log carry ids and counts only, never the file's text.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from collector.safe_json import parse_json

from . import config
from .national_clarksville import feed_errors     # the one schema check
from .national_guards import BindCounts, GuardCounts, bind_feed, checked_id, clean_feed, host_ok_valid, id_layer

ENV = "RECORDS_NATIONAL_DATA"
COLLECTED = ("legistar",)              # platforms whose feeds come from national-data (ADR 0013 decision 6)
MAX_FILE_BYTES = 8 * 1024 * 1024       # one body file: 60 meetings x 150 items x 2,000 characters fit with room
EPOCH_INSTANT = "1970-01-01T00:00:00Z"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
INSTANT_SLACK = timedelta(days=1)      # an instant may lie at most this far after the build's (12.1 row 12)
UPCOMING_SCHEMA = "daylight-upcoming/1"
# ASCII digits only: `\d` takes any Unicode digit (security S2b finding 2, national-isolation/date-crashes-build)
DAY_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
INSTANT_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")

# CopyCounts.state words (fixed: the run log and the annotations print only these)
COPIED, MISSING = "copied", "missing"
WITHHELD_ITEMS, BAD_DATE, BAD_INSTANT = "withheld-items", "bad-date", "bad-instant"
ANNOTATION = "::warning::National pages: "


class CopyError(ValueError):
    """A directory entry the collector may not read (a reviewed-config problem, decided in the load phase): the
    build stops. Never raised for anything a national-data file holds."""


@dataclass
class CopyCounts:
    """What the copy step did for one government, for the run log (counts and fixed words only)."""
    state: str = MISSING                    # COPIED, MISSING (page stale), WITHHELD_ITEMS, BAD_DATE or BAD_INSTANT
    guards: GuardCounts = field(default_factory=GuardCounts)
    bind: BindCounts = field(default_factory=BindCounts)

    def summary(self) -> str:
        return f"{self.state}; {self.guards.summary()}; review_mismatch={self.bind.review_mismatch}"


def data_root(env: Mapping[str, str] | None = None) -> Path | None:
    """The national-data `data/national` folder named by RECORDS_NATIONAL_DATA, or None when it is unset or empty."""
    value = (os.environ if env is None else env).get(ENV)
    return Path(value) if value else None


def safe_gov(entry: Mapping) -> str:
    """The entry's id for a log line or an error: the id when id_layer accepts it, else `<bad id>`."""
    return entry.get("gov") if id_layer(entry.get("gov")) else "<bad id>"


def _platform_keys(entry: Mapping) -> tuple[str, str]:
    """(platform, client) of a covered entry on a collected platform; CopyError for anything else."""
    gov = safe_gov(entry)
    platform = entry.get("platform")
    if platform not in COLLECTED:
        raise CopyError(f"{gov}: platform {str(platform)[:40]!r} is not collected into national-data")
    keys = entry.get(platform)
    client = keys.get("client") if isinstance(keys, dict) else None
    if not isinstance(client, str) or not client:
        raise CopyError(f"{gov}: no {platform} client in the directory entry")
    if not host_ok_valid(entry.get("host_ok")):
        raise CopyError(f"{gov}: platform {platform} has no valid host_ok (Brian's OK, R5): refused")
    return platform, client


def check_entry(entry: Mapping) -> None:
    """The load-phase check of one covered entry on a collected platform (point 1; architecture 12, B-ISO-1): a
    function of the reviewed directory entry alone. CopyError when the collector may not read it."""
    _platform_keys(entry)


def _real_dir(path: Path) -> bool:
    return not path.is_symlink() and path.is_dir()


def read_body_file(root: Path | None, gov: str):
    """The parsed `bodies/<gov>.json` under `root`, or None for "file missing" (4.4.3: any error is unreadable)."""
    if root is None:
        return None
    try:
        root = Path(root)
        bodies = root / "bodies"
        if not _real_dir(root) or not _real_dir(bodies):
            return None
        path = bodies / f"{checked_id(gov)}.json"
        if path.is_symlink() or not path.is_file():
            return None
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as f:
            raw = f.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            return None
        return parse_json(raw)
    except Exception:
        return None


def stale_feed(entry: Mapping) -> dict:
    """The placeholder feed of a government whose file is missing or refused: no meetings, no check recorded (page
    stale). Built from the directory entry alone."""
    platform = entry.get("platform")
    keys = entry.get(platform) if isinstance(entry.get(platform), dict) else {}
    return {"schema": UPCOMING_SCHEMA, "review": None,
            "body": {"id": entry.get("gov"), "name": entry.get("body_name"),
                     "tz": keys.get("tz") or config.SITE["site_timezone"], "official_url": entry.get("official_url"),
                     "platform": platform, "full_url": None},
            "checked_at": EPOCH_INSTANT, "last_ok_at": None, "meetings": []}


def civil_day(value) -> bool:
    """A meeting `date` the pages can print: ASCII `YYYY-MM-DD` (full match) that is a calendar day."""
    if not isinstance(value, str) or not DAY_RE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def instant_ok(value, built_at: datetime) -> bool:
    """A `checked_at` or `last_ok_at`: ASCII `YYYY-MM-DDTHH:MM:SSZ` (full match), a real instant, from the epoch to
    one day after the build's instant (a future `last_ok_at` would never go stale; 12.1 row 12)."""
    if not isinstance(value, str) or not INSTANT_RE.fullmatch(value):
        return False
    try:
        t = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return EPOCH <= t <= built_at + INSTANT_SLACK


def date_problem(feed: Mapping, built_at: datetime) -> str | None:
    """BAD_DATE or BAD_INSTANT for a text date or instant of a bound feed that the pages could not print, else None.
    A value of another type is left to the schema (file missing)."""
    for m in feed.get("meetings") or ():
        if isinstance(m, dict) and isinstance(m.get("date"), str) and not civil_day(m["date"]):
            return BAD_DATE
    for key in ("checked_at", "last_ok_at"):
        if isinstance(feed.get(key), str) and not instant_ok(feed[key], built_at):
            return BAD_INSTANT
    return None


def _refused(entry: Mapping, counts: CopyCounts, state: str, tail: str = "") -> dict:
    """stale_feed(entry) for a file the copy step refuses, its fixed word in `counts`, and one annotation line: the
    id, the word and counts only (architecture 12.3 #13)."""
    counts.state = state
    print(f"{ANNOTATION}{safe_gov(entry)}: {state}{tail}", flush=True)
    return stale_feed(entry)


def copy_feed(root: Path | None, entry: dict, counts: CopyCounts | None = None, *,
              built_at: datetime | None = None) -> dict:
    """The feed published for one covered entry on a collected platform (module docstring): the file's feed after
    clean_feed, bind_feed, the date and instant checks and the schema, or `stale_feed(entry)` when the file is missing
    or fails any of them. `built_at` (aware) is the build's instant (default now). Raises CopyError only for an entry
    the collector may not read (point 1, a reviewed-config problem); never for anything the file holds."""
    platform, client = _platform_keys(entry)
    counts = counts if counts is not None else CopyCounts()
    built_at = built_at or datetime.now(timezone.utc)
    counts.state = MISSING
    doc = read_body_file(root, entry["gov"])
    if not isinstance(doc, dict):
        return stale_feed(entry)
    try:
        cleaned, guards = clean_feed(doc, platform, client)
        feed, bound = bind_feed(cleaned, entry)
    except Exception:                     # UnsafeIdError, BindError, RecursionError, anything: file missing
        return stale_feed(entry)
    if bound.withheld_stripped:           # security S2b finding 1: degrade, never stop the build
        counts.bind = bound
        return _refused(entry, counts, WITHHELD_ITEMS, f", withheld_stripped={bound.withheld_stripped}")
    problem = date_problem(feed, built_at)
    if problem:                           # security S2b finding 2
        return _refused(entry, counts, problem)
    try:
        if feed_errors(feed):
            return stale_feed(entry)
    except Exception:                     # a value the validator cannot take (RecursionError): file missing
        return stale_feed(entry)
    counts.guards, counts.bind, counts.state = guards, bound, COPIED
    return feed
