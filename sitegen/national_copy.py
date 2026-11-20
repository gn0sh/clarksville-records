"""Daylight Digest, the D2 copy step (docs/architecture/daylight-national.md 4.6 "D2 copy step", 4.4.3 site 7,
11.1 row 16; task D2): the feeds of covered governments on a collected platform (Legistar), read from the newest
attested `national-data` (`data/national/bodies/<body id>.json`, 3.7) for the national builder.

The root is the `data/national` folder of that checkout, named by the environment variable RECORDS_NATIONAL_DATA
(`daily-update.yml`'s update job sets it to the folder it moved out of the attested checkout; unset: no national
data). The national builder (`national_pages.build_feeds`) is the only caller, and only while the switch is on, so
with `national.enabled: false` nothing here runs and the Clarksville build stays byte-identical (B5).

For each covered entry on a collected platform:
1. The entry itself must be one the collector may read: its platform's key mapping with a `client`, and a valid
   `host_ok` (R5, the loader's own check): else CopyError (the build stops; `national/r5-not-enforced`).
2. Read `bodies/<id>.json` (the id through `checked_id` first) and parse it per 4.4.3 (`collector.safe_json`): a
   missing file, a symlinked root, `bodies/` or file, a file over MAX_FILE_BYTES, or any error while reading or
   parsing, or a value that is not an object, is "file missing".
3. `clean_feed` with the entry's platform and client (the collector's files are not trusted as cleaned: S2a), then
   `bind_feed` against the current directory entry, then the `daylight-upcoming/1` schema. Any error there is "file
   missing" too.
4. `withheld_stripped > 0` (the file carried items for an entry that is not shown) is a collector bug (11.2): the
   build stops (CopyError) rather than publish quietly. `review_mismatch` (shown, read under another review) is only
   counted: expected for the runs between a reviewed change and the next collect.

A missing file gives `stale_feed(entry)`: no meetings, `checked_at` the epoch and `last_ok_at` null, so the page says
it has no records yet and the government is marked stale (never "can't cover": a curated status only). Only the
cleaned, bound, schema-checked feed (or that placeholder) reaches `digest/`; nothing else of the file is used. Errors
and the run log carry ids and counts only, never the file's text.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
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
UPCOMING_SCHEMA = "daylight-upcoming/1"


class CopyError(ValueError):
    """The copy step cannot go on for this entry (a directory entry the collector may not read, or a file that
    carried withheld items): the build stops."""


@dataclass
class CopyCounts:
    """What the copy step did for one government, for the run log (counts and fixed words only)."""
    state: str = "missing"                  # "copied" or "missing" (page stale)
    guards: GuardCounts = field(default_factory=GuardCounts)
    bind: BindCounts = field(default_factory=BindCounts)

    def summary(self) -> str:
        return f"{self.state}; {self.guards.summary()}; review_mismatch={self.bind.review_mismatch}"


def data_root(env: Mapping[str, str] | None = None) -> Path | None:
    """The national-data `data/national` folder named by RECORDS_NATIONAL_DATA, or None when it is unset or empty."""
    value = (os.environ if env is None else env).get(ENV)
    return Path(value) if value else None


def _platform_keys(entry: Mapping) -> tuple[str, str]:
    """(platform, client) of a covered entry on a collected platform; CopyError for anything else."""
    gov = entry.get("gov") if id_layer(entry.get("gov")) else "<bad id>"
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
    """The placeholder feed of a government whose file is missing: no meetings, no check recorded (page stale)."""
    platform = entry.get("platform")
    keys = entry.get(platform) if isinstance(entry.get(platform), dict) else {}
    return {"schema": UPCOMING_SCHEMA, "review": None,
            "body": {"id": entry.get("gov"), "name": entry.get("body_name"),
                     "tz": keys.get("tz") or config.SITE["site_timezone"], "official_url": entry.get("official_url"),
                     "platform": platform, "full_url": None},
            "checked_at": EPOCH_INSTANT, "last_ok_at": None, "meetings": []}


def copy_feed(root: Path | None, entry: dict, counts: CopyCounts | None = None) -> dict:
    """The feed published for one covered entry on a collected platform (module docstring): the file's feed after
    clean_feed, bind_feed and the schema, or `stale_feed(entry)` when the file is missing or fails any of them.
    Raises CopyError for an entry the collector may not read, or a file that carried items for a withheld entry."""
    platform, client = _platform_keys(entry)
    counts = counts if counts is not None else CopyCounts()
    doc = read_body_file(root, entry["gov"])
    feed = bound = None
    if isinstance(doc, dict):
        try:
            cleaned, guards = clean_feed(doc, platform, client)
            feed, bound = bind_feed(cleaned, entry)
            if feed_errors(feed):
                feed = None
            else:
                counts.guards = guards
        except Exception:                 # UnsafeIdError, BindError, RecursionError, anything: file missing
            feed = None
    if feed is not None and bound is not None:
        if bound.withheld_stripped:
            raise CopyError(f"{entry['gov']}: national-data carried items for a government that is not shown "
                            f"({bound.withheld_stripped} meeting(s)): a collector bug, the build stops (11.2)")
        counts.bind, counts.state = bound, "copied"
        return feed
    counts.state = "missing"
    return stale_feed(entry)
