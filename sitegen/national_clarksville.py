"""Daylight Digest, the Clarksville adapter (docs/architecture/daylight-national.md 3.5, 4.3, 7 and 11; task B3): the
City Council and County Commission feeds in `daylight-upcoming/1` (schema/daylight-upcoming.schema.json), made from
data this site already collects. Pure: the caller loads the inputs with the loaders the build already uses and passes
them in; nothing here opens a data/ path, so the data move of ADR 0011 does not touch it.

- County Commission (7): the agenda-only meetings of `county_agendas.load(config.COUNTY_AGENDAS)` from `today` on,
  each item's text the stored `title` as is (only the B14 guards apply: control and bidi characters stripped, 2,000
  characters, 150 items, 60 meetings). A meeting whose source has no page count is left out, as on the agendas page
  (every item cites a page).
- City Council (7): upcoming items are not stored, so every meeting is `agenda.state` `not-read` (an agenda is
  posted) or `not-posted`, with no items and `item_count` null. Meetings come from the council's facts file (a meeting
  from `today` on) and its CivicClerk listing (council.yml `calendar`, `load_listing`), read by the rules of the day
  page's scheduled cards (sitegen/days.py `scheduled_cards`): no moved, cancelled or postponed row, no row listed from
  another category (`page1_required`), one meeting per date and kind.
- Neither source stores a meeting time: `time` is null. Titles are the fixed kind labels (`title_ours: true`).

Invariant `privacy-withhold/national-prefix` (section 11): `items_withheld` is the directory entry's `items` field
(`gov["items"] != "shown"`, a missing field meaning withheld), never an id prefix. A withheld government's meetings
carry `items: []` and `item_count: null`, and its stored item text is never read. Which feed a directory entry gets
comes from its `daylight.body` key (config.yml `county_key`, council.yml `body_key`), also never from its id.
"""
from __future__ import annotations

import functools
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator, FormatChecker

from . import config
from .days import _CALLED_OFF
from .national import Directory
from .national_guards import GuardCounts, allowed_url, clean_feed

UPCOMING_SCHEMA = "daylight-upcoming/1"
UPCOMING_SCHEMA_PATH = config.REPO_ROOT / "schema" / "daylight-upcoming.schema.json"
PLATFORM = "daylight"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

NOT_READ = "not-read"          # posted, items not read by us (the City Council in M1)
NOT_POSTED = "not-posted"
FINAL = "final"                # an agenda as printed (the County Commission's agenda-only meetings)


class FeedError(ValueError):
    """A feed this adapter made does not match schema/daylight-upcoming.schema.json: the build stops."""


# --- inputs (loaded by the caller) --------------------------------------------------------------------------------

def council_cfg(body_key: str) -> dict | None:
    """The config.COUNCILS entry (council.yml) whose `body_key` is `body_key`, or None."""
    return next((c for c in config.COUNCILS if c.get("body_key") == body_key), None)


def load_listing(cfg: dict) -> list[dict]:
    """A council's CivicClerk listing, read the way the day page reads it (council.yml `calendar`, relative to the
    repository root; sitegen/days.py `scheduled_cards`). No `calendar` key or no file: []."""
    path = cfg.get("calendar")
    p = config.REPO_ROOT / path if path else None
    if p is None or not p.is_file():
        return []
    rows = json.loads(p.read_text(encoding="utf-8"))
    return rows if isinstance(rows, list) else []


# --- the feeds ----------------------------------------------------------------------------------------------------

def _instant(t: datetime) -> str:
    if not isinstance(t, datetime) or t.tzinfo is None:
        raise ValueError("checked_at must be a datetime with a time zone")
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _shown(gov: Mapping) -> bool:
    """The one place this adapter decides whether item text may be published: the directory's `items` field only
    (default withheld; privacy-withhold/national-prefix)."""
    return gov.get("items", "withheld") == "shown"


def _iso_day(value) -> bool:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _meeting(mid: str, day: str, title: str, state: str, agenda_url, withheld: bool) -> dict:
    return {"id": mid, "date": day, "time": None, "title": title, "title_ours": True, "meeting_url": None,
            "agenda": {"state": state, "url": agenda_url or None, "status_as_posted": None},
            "may_be_incomplete": False, "items_withheld": withheld, "item_count": None, "items": []}


def council_meetings(facts: dict, listing: list, today: date, kind_labels: Mapping[str, str],
                     withheld: bool) -> list[dict]:
    """The City Council's meetings from `today` on, soonest first: each `not-read` with its agenda link when an agenda
    is posted, else `not-posted`; never items (they are not stored, architecture 7)."""
    day0 = today.isoformat()
    sources = {s["id"]: s for s in facts.get("sources", []) if isinstance(s, dict) and "id" in s}
    out: dict[tuple[str, str], dict] = {}
    for m in facts.get("meetings", []):
        if not _iso_day(m.get("date")) or m["date"] < day0 or not m.get("kind"):
            continue
        agenda = sources.get(m.get("agenda_source_id") or "") or {}
        url = allowed_url(agenda.get("url"), PLATFORM)
        out.setdefault((m["date"], m["kind"]), _meeting(
            m.get("id") or f"{m['date']}-{m['kind']}", m["date"], kind_labels.get(m["kind"], m["kind"]),
            NOT_READ if url else NOT_POSTED, url, withheld))
    for row in sorted((r for r in listing if isinstance(r, dict)),
                      key=lambda r: (str(r.get("date") or ""), str(r.get("kind") or ""))):
        day, kind = row.get("date"), row.get("kind")
        if not _iso_day(day) or not isinstance(kind, str) or not kind or day < day0:
            continue
        if _CALLED_OFF.search(row.get("title") or "") or row.get("page1_required") or (day, kind) in out:
            continue
        url = allowed_url(row.get("agenda_url"), PLATFORM)
        out[(day, kind)] = _meeting(f"{day}-{kind}", day, kind_labels.get(kind, kind),
                                    NOT_READ if url else NOT_POSTED, url, withheld)
    return sorted(out.values(), key=lambda m: (m["date"], m["id"]))


def county_meetings(agendas: dict | None, today: date, kind_labels: Mapping[str, str], withheld: bool) -> list[dict]:
    """The County Commission's agenda-only meetings from `today` on, soonest first. Shown: each item's `text` is the
    stored `title` as is, `number` the stored number, its source the agenda PDF page. Withheld: no item is read."""
    if not agendas:
        return []
    day0 = today.isoformat()
    sources = {s["id"]: s for s in agendas.get("sources", []) if isinstance(s, dict) and s.get("pages")}
    out = []
    for m in agendas.get("meetings", []):
        if not _iso_day(m.get("date")) or m["date"] < day0 or m.get("source_id") not in sources:
            continue
        src = sources[m["source_id"]]
        url = allowed_url(src.get("url"), PLATFORM)
        meeting = _meeting(m.get("id"), m["date"], kind_labels.get(m.get("kind"), m.get("kind") or ""), FINAL, url,
                           withheld)
        if not withheld:
            stored = [it for it in m.get("items", []) if isinstance(it, dict)]
            meeting["item_count"] = len(stored)
            meeting["items"] = [
                {"seq": n, "number": it.get("number"), "text": it.get("title"),
                 "source": {"url": f"{url}#page={it['page']}" if url and isinstance(it.get("page"), int) else None,
                            "page": it.get("page") if isinstance(it.get("page"), int) else None}}
                for n, it in enumerate(stored, start=1)]
        out.append(meeting)
    return sorted(out, key=lambda m: (m["date"], str(m["id"])))


def _feed(gov: Mapping, tz: str, meetings: list[dict], stamp: str) -> dict:
    return {"schema": UPCOMING_SCHEMA,
            "body": {"id": gov["gov"], "name": gov["body_name"], "tz": tz, "official_url": gov["official_url"],
                     "platform": PLATFORM, "full_url": gov["daylight"]["full_url"]},
            "checked_at": stamp, "last_ok_at": stamp, "meetings": meetings}


def clarksville_feeds(directory: Directory, facts_city: dict, listing_city: list, county_agendas: dict | None,
                      today: date, *, checked_at: datetime, council_kinds: Mapping[str, str] | None = None,
                      county_kinds: Mapping[str, str] | None = None,
                      counts: dict[str, GuardCounts] | None = None) -> dict[str, dict]:
    """{body id: `daylight-upcoming/1` feed} for every covered daylight entry of the directory whose `daylight.body`
    is the county's key (config.SITE `county_key`) or the council's (council.yml `body_key`). `today` is the build day
    in the body's zone; `checked_at` (aware) is when the inputs were collected, written as `checked_at` and
    `last_ok_at`. Each feed goes through `national_guards.clean_feed` and is then checked against the schema
    (FeedError). `counts`, if given, receives each feed's GuardCounts for the run log."""
    stamp = _instant(checked_at)
    tz = config.SITE["site_timezone"]
    county_key = config.SITE["county_key"]
    county_kinds = config.KIND_LABELS if county_kinds is None else county_kinds
    feeds: dict[str, dict] = {}
    for gov in directory.govs:
        if gov.get("status") != "covered" or gov.get("platform") != PLATFORM:
            continue
        key = (gov.get("daylight") or {}).get("body")
        withheld = not _shown(gov)
        if key == county_key:
            meetings = county_meetings(county_agendas, today, county_kinds, withheld)
        elif (cfg := council_cfg(key)) is not None:
            kinds = (cfg.get("kind_labels") or {}) if council_kinds is None else council_kinds
            meetings = council_meetings(facts_city, listing_city, today, kinds, withheld)
        else:
            continue
        feed, n = clean_feed(_feed(gov, tz, meetings, stamp), PLATFORM)
        errors = feed_errors(feed)
        if errors:
            raise FeedError(f"{gov['gov']}: feed does not match {UPCOMING_SCHEMA}:\n" + "\n".join(errors))
        feeds[gov["gov"]] = feed
        if counts is not None:
            counts[gov["gov"]] = n
    return feeds


# --- the schema check ---------------------------------------------------------------------------------------------

_FORMATS = FormatChecker()
_FORMATS.checks("uri")(config.is_https_uri)      # the site's one link rule, as build.FORMAT_CHECKER


@functools.lru_cache(maxsize=None)
def validator(path: Path = UPCOMING_SCHEMA_PATH) -> Draft202012Validator:
    return Draft202012Validator(json.loads(Path(path).read_text(encoding="utf-8")), format_checker=_FORMATS)


def feed_errors(feed: dict, path: Path = UPCOMING_SCHEMA_PATH) -> list[str]:
    """Schema errors of a feed, one line each (path, then message; never the field's text), [] when it validates."""
    errs = sorted(validator(path).iter_errors(feed), key=lambda e: list(map(str, e.absolute_path)))
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.validator} {e.validator_value!r}"
            for e in errs]
