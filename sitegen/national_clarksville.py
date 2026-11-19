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
  from `today` on) and its CivicClerk listing (council.yml `calendar`, `load_listing`), read by the day page's one
  rule for listing rows (sitegen/days.py `calendar_rows`). One meeting per date and kind; the facts meeting wins over
  its listing row, except that a facts meeting whose only listing rows for its date and kind are called off (moved,
  cancelled, postponed) is left out (the day page is unchanged). A posted agenda whose link `allowed_url` refuses is
  still `not-read`, with a null `agenda.url` (the page falls back to `official_url`).
- Neither source stores a meeting time: `time` is null. Titles are fixed labels (`title_ours: true`): the body's kind
  label (council.yml `kind_labels`, config.KIND_LABELS), or FALLBACK_TITLE for a kind with no label, never the raw
  kind.
- Each council's inputs are passed keyed by its council.yml `body_key`; a covered daylight entry whose `daylight.body`
  is neither the county's key nor a key with inputs and a council.yml stops the build (FeedError), so no entry is
  ever given another council's meetings.

Invariant `privacy-withhold/national-prefix` (section 11 v3): stored item text is read only when
`national_guards.is_shown(gov)` (the entry says `items: shown` and its whole-entry review digest matched its
SHOWN_REVIEWED row), never by an id prefix. A withheld government's meetings carry `items: []` and `item_count:
null`, and its stored item text is never read. Each feed carries `review` (the digest when shown, else null) and goes
through `bind_feed` before the schema check. Items flow only by the county route: the code fixes COUNTY_BODY_KEY and
stops the build (FeedError) unless config.SITE `county_key` equals it and no council.yml `body_key` does (11.1 row
10); council feeds never carry items.
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
from .days import calendar_rows
from .national import Directory
from .national_guards import BindCounts, GuardCounts, allowed_url, bind_feed, clean_feed, is_shown

UPCOMING_SCHEMA = "daylight-upcoming/1"
UPCOMING_SCHEMA_PATH = config.REPO_ROOT / "schema" / "daylight-upcoming.schema.json"
PLATFORM = "daylight"
COUNTY_BODY_KEY = "county"     # the only daylight.body whose feed carries items (11.1 row 10), fixed in code
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

NOT_READ = "not-read"          # posted, items not read by us (the City Council in M1)
NOT_POSTED = "not-posted"
FINAL = "final"                # an agenda as printed (the County Commission's agenda-only meetings)
FALLBACK_TITLE = "Meeting"     # the fixed title of a meeting whose kind has no label


class FeedError(ValueError):
    """A feed this adapter made does not match schema/daylight-upcoming.schema.json: the build stops."""


# --- inputs (loaded by the caller) --------------------------------------------------------------------------------

def council_cfg(body_key) -> dict | None:
    """The config.COUNCILS entry (council.yml) whose `body_key` is `body_key`, or None (also for a missing key)."""
    if not isinstance(body_key, str) or not body_key:
        return None
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


def _iso_day(value) -> bool:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _title(kind_labels: Mapping[str, str], kind) -> str:
    label = kind_labels.get(kind) if isinstance(kind, str) else None
    return label if isinstance(label, str) and label else FALLBACK_TITLE


def _meeting(mid: str, day: str, title: str, state: str, agenda_url, withheld: bool) -> dict:
    return {"id": mid, "date": day, "time": None, "title": title, "title_ours": True, "meeting_url": None,
            "agenda": {"state": state, "url": agenda_url or None, "status_as_posted": None},
            "may_be_incomplete": False, "items_withheld": withheld, "item_count": None, "items": []}


def council_meetings(facts: dict, listing: list, today: date, kind_labels: Mapping[str, str],
                     withheld: bool) -> list[dict]:
    """The City Council's meetings from `today` on, soonest first: each `not-read` when an agenda is posted (its link
    when `allowed_url` keeps it, else null), else `not-posted`; never items (they are not stored, architecture 7)."""
    day0 = today.isoformat()
    sources = {s["id"]: s for s in facts.get("sources", []) if isinstance(s, dict) and "id" in s}
    rows = [r for r in listing if isinstance(r, dict) and _iso_day(r.get("date")) and isinstance(r.get("kind"), str)]
    called_off: set = set()
    listed = calendar_rows(rows, today, called_off)
    cancelled = called_off - {(r["date"], r["kind"]) for r in listed}    # every row for that date and kind called off
    out: dict[tuple[str, str], dict] = {}
    for m in facts.get("meetings", []):
        if not _iso_day(m.get("date")) or m["date"] < day0 or not m.get("kind") or (m["date"], m["kind"]) in cancelled:
            continue
        agenda = sources.get(m.get("agenda_source_id") or "")
        out.setdefault((m["date"], m["kind"]), _meeting(
            m.get("id") or f"{m['date']}-{m['kind']}", m["date"], _title(kind_labels, m["kind"]),
            NOT_READ if agenda else NOT_POSTED, allowed_url((agenda or {}).get("url"), PLATFORM), withheld))
    for row in listed:
        day, kind = row["date"], row["kind"]
        if (day, kind) in out:
            continue
        posted = bool(row.get("agenda_url"))
        out[(day, kind)] = _meeting(f"{day}-{kind}", day, _title(kind_labels, kind),
                                    NOT_READ if posted else NOT_POSTED, allowed_url(row.get("agenda_url"), PLATFORM),
                                    withheld)
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
        meeting = _meeting(m.get("id"), m["date"], _title(kind_labels, m.get("kind")), FINAL, url,
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
    return {"schema": UPCOMING_SCHEMA, "review": gov["review"] if is_shown(gov) else None,
            "body": {"id": gov["gov"], "name": gov["body_name"], "tz": tz, "official_url": gov["official_url"],
                     "platform": PLATFORM, "full_url": gov["daylight"]["full_url"]},
            "checked_at": stamp, "last_ok_at": stamp, "meetings": meetings}


def clarksville_feeds(directory: Directory, councils: Mapping[str, tuple[dict, list]], county_agendas: dict | None,
                      today: date, *, checked_at: datetime,
                      counts: dict[str, GuardCounts] | None = None,
                      bind_counts: dict[str, BindCounts] | None = None) -> dict[str, dict]:
    """{body id: `daylight-upcoming/1` feed} for every covered daylight entry of the directory. `councils` maps a
    council's council.yml `body_key` to its (facts, listing); an entry gets the county feed when its `daylight.body`
    is COUNTY_BODY_KEY (`county`), that council's feed when it is a key of `councils` with a council.yml, and any other
    key stops the build (FeedError). `today` is the build day in the body's zone; `checked_at` (aware) is when the
    inputs were collected, written as `checked_at` and `last_ok_at`. Each feed goes through
    `national_guards.clean_feed`, then `bind_feed` with its entry, and is then checked against the schema
    (FeedError). `counts` and `bind_counts`, if given, receive each feed's GuardCounts and BindCounts for the run log.
    Stops the build (FeedError) unless config.SITE `county_key` is COUNTY_BODY_KEY and no council's `body_key` is."""
    stamp = _instant(checked_at)
    tz = config.SITE["site_timezone"]
    if config.SITE.get("county_key") != COUNTY_BODY_KEY:
        raise FeedError(f"config.SITE county_key {config.SITE.get('county_key')!r} is not {COUNTY_BODY_KEY!r}: the "
                        "county route is the only one that carries items (privacy-withhold, 11.1 row 10)")
    if any(c.get("body_key") == COUNTY_BODY_KEY for c in config.COUNCILS):
        raise FeedError(f"a council.yml body_key is {COUNTY_BODY_KEY!r}, the county's key (11.1 row 10)")
    feeds: dict[str, dict] = {}
    for gov in directory.govs:
        if gov.get("status") != "covered" or gov.get("platform") != PLATFORM:
            continue
        key = (gov.get("daylight") or {}).get("body")
        withheld = not is_shown(gov)
        if key == COUNTY_BODY_KEY:
            meetings = county_meetings(county_agendas, today, config.KIND_LABELS, withheld)
        elif key in councils and (cfg := council_cfg(key)) is not None:
            facts, listing = councils[key]
            meetings = council_meetings(facts, listing, today, cfg.get("kind_labels") or {}, withheld)
        else:
            raise FeedError(f"{gov['gov']}: daylight.body {key!r} is neither the county's key nor a council with "
                            "inputs and a council.yml")
        feed, n = clean_feed(_feed(gov, tz, meetings, stamp), PLATFORM)
        try:
            feed, bound = bind_feed(feed, gov)
        except ValueError as e:              # BindError
            raise FeedError(f"{gov['gov']}: {e}") from e
        errors = feed_errors(feed)
        if errors:
            raise FeedError(f"{gov['gov']}: feed does not match {UPCOMING_SCHEMA}:\n" + "\n".join(errors))
        feeds[gov["gov"]] = feed
        if counts is not None:
            counts[gov["gov"]] = n
        if bind_counts is not None:
            bind_counts[gov["gov"]] = bound
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
