"""Daylight Digest, the Legistar upcoming reader (docs/architecture/daylight-national.md 3.5, 3.7, 4.5 and section 11;
ADR 0013 decision 6; task C2): one covered Legistar body's meetings from today to four weeks on, as a
`daylight-upcoming/1` feed (schema/daylight-upcoming.schema.json, the shape the Clarksville adapter B3 writes).

What it asks for, and only through the fetcher's public `get(url) -> (status, body, headers)` (collector/fetch.py; the
tenant rule of task C1 lives inside the fetcher, not here):
- one events query per body: `$filter=EventBodyId eq <body_id>` (stable when a body is renamed) and the window today
  minus one day to today plus 28 days in the body's time zone (`events_url`);
- an event's agenda items (`items_url`) only when all hold: the entry is shown (`national_guards.is_shown`: `items:
  shown` and a review digest, which `load_directory` sets only after the whole entry matched its SHOWN_REVIEWED row),
  the agenda is final (`agenda_state`), the event's `EventBodyId` is the entry's `body_id`, and the cache has no copy
  read under this review for this `EventAgendaLastPublishedUTC`.
- Never anything else: agenda PDFs (`EventAgendaFile`) and the client's own pages (`EventInSiteURL`) are linked,
  never requested.

Agenda state (`agenda_state`): `final` only when `EventAgendaStatusName` is exactly one of the entry's
`final_statuses` (default: every name in `LEGISTAR_FINAL_STATUSES`); no status and no agenda file is `not-posted`;
anything else (Draft, an empty status with a file, a name we do not know) is `not-final`, with no items request. A
status name that is neither final nor `Draft` becomes an `agenda-status-name` proposal for a person (3.7).

Invariant `privacy-withhold/national-prefix` (section 11, rows 18-19): for an entry that is not shown no items request
is made at all, the feed carries no item text (`bind_feed` then also fixes the titles and nulls free text) and
`cache/<id>/` is deleted. A cache file is used only when its `review`, body, event id and `last_published` all match;
any other file is a miss and is deleted. Every field read passes the B14 guards (`clean_feed`: control and bidi
stripping, the 2,000-character, 150-item and 60-meeting caps, `allowed_url` with the Legistar host allowlist), then
`bind_feed`, then the schema, before a feed is returned or a cache file written. Errors and counts carry ids and
numbers only, never text from the source (11.1 row 23).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sitegen.national import LEGISTAR_FINAL_STATUSES, Directory
from sitegen.national_clarksville import UPCOMING_SCHEMA, feed_errors
from sitegen.national_guards import (LEGISTAR_API_HOST, MAX_TEXT, BindCounts, GuardCounts, allowed_url, bind_feed,
                                     checked_id, clean_feed, clean_text, cut_text, host_ok_valid, is_shown)

PLATFORM = "legistar"
API_ROOT = f"https://{LEGISTAR_API_HOST}/v1"
DAYS_BEFORE = 1                  # ADR 0013 decision 6: today minus one day ...
DAYS_AFTER = 28                  # ... to today plus 28 days, in the body's time zone
KNOWN_NOT_FINAL = frozenset({"Draft"})          # a status we know means "not final": no proposal
KNOWN_STATUSES = LEGISTAR_FINAL_STATUSES | KNOWN_NOT_FINAL
MAX_RESPONSE_BYTES = 5 * 1024 * 1024            # one events or items answer (finding 12, untrusted size)
MAX_ROWS = 1_000                                 # Legistar returns at most 1,000 rows per query (vendor docs)
MAX_OBSERVED = 60                                # characters of a status name a proposal may carry
STATUS_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()/&-]{0,59}$")
CACHE_SCHEMA = "daylight-legistar-cache/1"
FALLBACK_TITLE = "Meeting"       # the fixed title of a meeting with no posted comment (title_ours: true)

FINAL, NOT_FINAL, NOT_POSTED = "final", "not-final", "not-posted"


class ReadError(Exception):
    """The body could not be read this run. `kind` is a 3.7 health `last_error` value (C3 records it). The message
    holds ids and status codes only, never text from the answer."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class FeedError(ValueError):
    """The feed this reader made does not bind to its entry or match the schema: a bug, nothing is written."""


@dataclass
class ReadCounts:
    """What one body's read did, for the run log (counts only)."""
    events: int = 0                 # event rows in the answer
    other_body_dropped: int = 0     # rows whose EventBodyId is not the entry's body_id (11.1 row 18)
    past_dropped: int = 0           # rows dated before today in the body's time zone
    future_dropped: int = 0         # rows dated after today plus DAYS_AFTER (the API ignored the window)
    bad_dropped: int = 0            # rows that are not objects or have no usable EventId or EventDate
    rows_over_cap: int = 0          # rows past MAX_ROWS
    items_requests: int = 0         # items requests made
    cache_hits: int = 0
    cache_deleted: int = 0          # cache files deleted (another review, unreadable, or the body is not shown)
    unknown_status: int = 0         # events whose status name is not one we know
    guard: GuardCounts = field(default_factory=GuardCounts)
    bind: BindCounts = field(default_factory=BindCounts)


@dataclass
class BodyRead:
    feed: dict                      # the bound, schema-checked `daylight-upcoming/1` feed
    proposals: list[dict]           # 3.7 proposals of kind `agenda-status-name` (C3 merges them into proposals.json)
    counts: ReadCounts


# --- URLs ---------------------------------------------------------------------------------------------------------

def _query(params: dict) -> str:
    return urllib.parse.urlencode(params, safe="$", quote_via=urllib.parse.quote)


def events_url(client: str, body_id: int, start: date, end: date) -> str:
    """The OData events query for one body (`EventBodyId`, never the name) and the days `start` <= day < `end`."""
    flt = (f"EventBodyId eq {int(body_id)} and EventDate ge datetime'{start.isoformat()}' "
           f"and EventDate lt datetime'{end.isoformat()}'")
    return f"{API_ROOT}/{client}/events?" + _query({"$filter": flt, "$orderby": "EventDate asc"})


def items_url(client: str, event_id: int) -> str:
    """One event's agenda items. No notes, attachments or votes are asked for: only the item title is read."""
    return f"{API_ROOT}/{client}/events/{int(event_id)}/eventitems"


# --- reading one event --------------------------------------------------------------------------------------------

def _whole(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _status(event: dict) -> str | None:
    raw = event.get("EventAgendaStatusName")
    return raw if isinstance(raw, str) and raw.strip() else None


def _has_file(event: dict) -> bool:
    f = event.get("EventAgendaFile")
    return isinstance(f, str) and bool(f.strip())


def agenda_state(event: dict, final_statuses=LEGISTAR_FINAL_STATUSES) -> str:
    """`final` when the posted status name is exactly one of `final_statuses`; `not-posted` when there is no status
    and no agenda file; else `not-final` (Draft, an empty status with a file, any other name)."""
    name = _status(event)
    if name is None and not _has_file(event):
        return NOT_POSTED
    return FINAL if name in frozenset(final_statuses) else NOT_FINAL


def _day(event: dict) -> date | None:
    raw = event.get("EventDate")
    if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}(T[0-9:.]+)?", raw):
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def meeting_id(day: date, event_id: int) -> str:
    """`<date>-e<EventId>`: stable for the event, a full match of MEETING_ID_RE."""
    return f"{day.isoformat()}-e{int(event_id)}"


def _text(value) -> str | None:
    text, _ = clean_text(value)
    text, _ = cut_text(text, MAX_TEXT)
    return text or None


def build_items(rows: list, agenda_url: str | None) -> list[dict]:
    """Legistar eventitems -> 3.5 items, agenda order. Read: `EventItemAgendaSequence`, `EventItemAgendaNumber` and
    `EventItemTitle` only (never mover, seconder, votes, notes or attachments). A row without a positive agenda
    sequence or a title is not an agenda item and is left out. Text is cleaned and capped later by clean_feed."""
    good = []
    for r in rows[:MAX_ROWS]:
        if not isinstance(r, dict):
            continue
        seq = _whole(r.get("EventItemAgendaSequence"))
        title = r.get("EventItemTitle")
        if seq is None or seq < 1 or not isinstance(title, str) or not clean_text(title)[0]:
            continue
        number = r.get("EventItemAgendaNumber")
        good.append((seq, _whole(r.get("EventItemId")) or 0, title, number if isinstance(number, str) else None))
    good.sort(key=lambda g: (g[0], g[1]))
    return [{"seq": n, "number": number, "text": title, "source": {"url": agenda_url, "page": None}}
            for n, (_, _, title, number) in enumerate(good, start=1)]


def meeting(event: dict, items: list[dict] | None, tz: str, *, client: str, withheld: bool,
            final_statuses=LEGISTAR_FINAL_STATUSES, item_count: int | None = None) -> dict:
    """One event -> a 3.5 meeting. `items` is the list read for a shown body's final agenda, else None (no request
    was made: `items: []`, `item_count: null`). `time` and `status_as_posted` are as posted; `title` is the event's
    comment as posted, else FALLBACK_TITLE. URLs pass `allowed_url` for the client (else null). `tz` names the zone
    the date is read in (EventDate is the local meeting date). `may_be_incomplete` is always true: the API returns
    only items marked public (ADR 0013 decision 6)."""
    day = _day(event)           # EventDate is already the body's local date; `tz` stays in 4.5's signature
    state = agenda_state(event, final_statuses)
    agenda_url = allowed_url(event.get("EventAgendaFile"), PLATFORM, client) or None
    comment = _text(event.get("EventComment"))
    read = items is not None and state == FINAL and not withheld
    return {"id": meeting_id(day, event["EventId"]), "date": day.isoformat(), "time": _text(event.get("EventTime")),
            "title": comment or FALLBACK_TITLE, "title_ours": comment is None,
            "meeting_url": allowed_url(event.get("EventInSiteURL"), PLATFORM, client) or None,
            "agenda": {"state": state, "url": agenda_url, "status_as_posted": _text(_status(event))},
            "may_be_incomplete": True, "items_withheld": withheld,
            "item_count": (len(items) if item_count is None else item_count) if read else None,
            "items": list(items) if read else []}


# --- the cache (3.7; 11.1 row 19) ---------------------------------------------------------------------------------

def _cache_root(cache_root) -> Path | None:
    """`cache_root` resolved once (`cache-confine/root-symlink`): a root that is itself a symlink is refused, so no
    delete or write ever goes through a link to somewhere else."""
    if cache_root is None:
        return None
    root = Path(cache_root)
    if root.is_symlink():
        raise ValueError("the cache root is a symlink: refused (cache-confine/root-symlink)")
    return root.resolve()


def _inside(root: Path, path: Path) -> bool:
    """`path` is a real (not symlinked) folder directly in `root` (`cache-confine/symlinked-body-folder`)."""
    return not path.is_symlink() and path.is_dir() and path.resolve().parent == root


def _cache_dir(root: Path | None, gov: str, counts: "ReadCounts") -> Path | None:
    """`root/<gov>`, confined: a symlink there (or anything that resolves outside `root`, or a file) is unlinked,
    never followed, and the folder starts fresh."""
    if root is None:
        return None
    folder = root / checked_id(gov)
    if (folder.is_symlink() or folder.exists()) and not _inside(root, folder):
        counts.cache_deleted += _remove(folder)
    return folder


def _remove(path: Path) -> int:
    """Delete a cache file or folder (a link is unlinked, never followed). -> number of files removed."""
    if path.is_symlink() or path.is_file():
        path.unlink()
        return 1
    if path.is_dir():
        n = sum(1 for p in path.rglob("*") if p.is_file() or p.is_symlink())
        shutil.rmtree(path)
        return n
    return 0


def prune_cache(directory: Directory, cache_root: Path) -> list[str]:
    """Delete every `cache_root/<name>` that is not the folder of a covered, shown Legistar entry (11.1 row 19: run
    first, so a body that became withheld keeps no item text). -> the names removed, sorted."""
    root = _cache_root(cache_root)
    if not root.is_dir():
        return []
    keep = {g["gov"] for g in directory.govs
            if g.get("status") == "covered" and g.get("platform") == PLATFORM and is_shown(g)}
    removed = []
    for p in sorted(root.iterdir()):
        if p.name not in keep or p.is_symlink() or not p.is_dir():
            _remove(p)
            removed.append(p.name)
    return removed


def _sweep(folder: Path, entry: dict, counts: ReadCounts) -> None:
    """Delete every file in a shown body's cache folder that was not written under this review for this body
    (11.1 row 19), so text read under an old review never waits there for its event to come round again."""
    if not folder.is_dir():
        return
    for p in sorted(folder.iterdir()):
        doc = None
        if p.is_file() and not p.is_symlink() and re.fullmatch(r"[1-9][0-9]{0,11}\.json", p.name):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = None
        if not (isinstance(doc, dict) and doc.get("review") == entry["review"] and doc.get("body") == entry["gov"]):
            counts.cache_deleted += _remove(p)


def _cache_get(folder: Path | None, entry: dict, event_id: int, published: str | None,
               counts: ReadCounts) -> tuple[list[dict], int] | None:
    """(items, item_count) cached for this event under this review and this LastPublished, else None (a file that
    does not match is deleted). `item_count` is the uncapped count read with them (`legistar-cache/item-count-drift`),
    so a hit gives the same meeting as a fresh read."""
    if folder is None or published is None:
        return None
    path = folder / f"{int(event_id)}.json"
    if not path.is_file() or path.is_symlink():
        if path.is_symlink():
            counts.cache_deleted += _remove(path)
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = None
    ok = (isinstance(doc, dict) and doc.get("schema") == CACHE_SCHEMA and doc.get("review") == entry["review"]
          and doc.get("body") == entry["gov"] and doc.get("event_id") == int(event_id)
          and isinstance(doc.get("items"), list) and all(isinstance(i, dict) for i in doc["items"])
          and _whole(doc.get("item_count")) is not None and doc["item_count"] >= len(doc["items"]))
    if not ok:
        counts.cache_deleted += _remove(path)
        return None
    if doc.get("last_published") != published:
        return None             # the agenda was published again: re-read, the new copy replaces this file
    counts.cache_hits += 1
    return doc["items"], doc["item_count"]


def _cache_put(root: Path, folder: Path, entry: dict, event_id: int, published: str, items: list[dict],
               item_count: int) -> None:
    """Write one cache file inside `root/<gov>` only: a symlinked or outside folder is refused, the temporary file is
    created new with O_NOFOLLOW, and the rename replaces a link at the target, never what it points to."""
    root.mkdir(parents=True, exist_ok=True)
    folder.mkdir(exist_ok=True)
    if not _inside(root, folder):
        raise ValueError(f"{entry['gov']}: cache folder is not a real folder in the cache root (cache-confine)")
    path = folder / f"{int(event_id)}.json"
    tmp = folder / f".{int(event_id)}.json.tmp"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    text = json.dumps({"schema": CACHE_SCHEMA, "review": entry["review"], "body": entry["gov"],
                       "event_id": int(event_id), "last_published": published, "item_count": int(item_count),
                       "items": items}, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# --- one body -----------------------------------------------------------------------------------------------------

def _instant(t: datetime) -> str:
    if not isinstance(t, datetime) or t.tzinfo is None:
        raise ValueError("now must be a datetime with a time zone")
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _error_kind(status: int) -> str:
    if status in (401, 407):
        return "token-suspected"
    if status in (400, 404, 410):
        return "not-enabled-suspected"
    return "server-error"


def _get_json(fetcher, url: str, gov: str, what: str) -> list:
    """GET a Legistar answer that must be a JSON list. Fetcher exceptions (HostBlocked, TenantBlocked,
    RobotsDisallowed, RequestCapReached, FetchFailed, ...) pass through to the run (C3)."""
    status, body, _headers = fetcher.get(url)
    if status != 200:
        raise ReadError(_error_kind(status), f"{gov}: {what} answered HTTP {int(status)}")
    if not isinstance(body, (bytes, bytearray)) or len(body) > MAX_RESPONSE_BYTES:
        raise ReadError("server-error", f"{gov}: {what} answer is larger than {MAX_RESPONSE_BYTES} bytes")
    try:
        rows = json.loads(bytes(body).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ReadError("not-enabled-suspected", f"{gov}: {what} answer is not JSON") from None
    if not isinstance(rows, list):
        raise ReadError("not-enabled-suspected", f"{gov}: {what} answer is not a JSON list")
    return rows


def _published(event: dict) -> str | None:
    """EventAgendaLastPublishedUTC as the cache key: kept only when it is a plain timestamp."""
    raw = event.get("EventAgendaLastPublishedUTC")
    return raw if isinstance(raw, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T[0-9:.]{1,20}Z?", raw) else None


def _proposal(gov: str, name: str, evidence_url: str, stamp: str) -> dict:
    observed = name if STATUS_NAME_RE.fullmatch(name) else None     # odd characters or length: counted, not copied
    return {"body": gov, "kind": "agenda-status-name", "observed": observed, "evidence_url": evidence_url,
            "first_seen": stamp, "count": 0}


def read_body(entry: dict, fetcher, now: datetime, cache_root: Path | None = None) -> BodyRead:
    """Read one covered Legistar entry (loaded by `load_directory`) into a bound `daylight-upcoming/1` feed.

    `now` (aware) is the run's check stamp: it picks today in the body's zone and is written as `checked_at` and
    `last_ok_at`. `cache_root` is `data/national/cache` (None: no cache, every final agenda of a shown body is read).
    Raises ReadError when the events answer is unusable, FeedError on a feed that fails bind or the schema, and lets
    fetcher exceptions through (C3 records health and moves on)."""
    if not isinstance(entry, dict) or entry.get("status") != "covered" or entry.get("platform") != PLATFORM:
        raise ValueError("read_body takes a covered Legistar directory entry")
    gov = checked_id(entry.get("gov"))
    if not host_ok_valid(entry.get("host_ok")):          # R5 (finding 7): no request without Brian's OK for the host
        raise ValueError(f"{gov}: no valid host_ok (Brian's OK, R5): nothing is sent")
    keys = entry[PLATFORM]
    client, body_id, tz = keys["client"], _whole(keys["body_id"]), keys["tz"]
    if body_id is None:
        raise ValueError(f"{gov}: legistar.body_id must be a whole number")
    finals = frozenset(keys.get("final_statuses") or LEGISTAR_FINAL_STATUSES)
    shown = is_shown(entry)
    stamp = _instant(now)
    counts = ReadCounts()
    root = _cache_root(cache_root)
    folder = _cache_dir(root, gov, counts)
    if not shown and folder is not None and (folder.exists() or folder.is_symlink()):
        counts.cache_deleted += _remove(folder)         # 11.1 row 19: a withheld body keeps no cache
        folder = None
    elif not shown:
        folder = None
    elif folder is not None:
        _sweep(folder, entry, counts)

    today = now.astimezone(ZoneInfo(tz)).date()
    url = events_url(client, body_id, today - timedelta(days=DAYS_BEFORE), today + timedelta(days=DAYS_AFTER + 1))
    rows = _get_json(fetcher, url, gov, "events")
    counts.events = len(rows)
    if len(rows) > MAX_ROWS:
        counts.rows_over_cap = len(rows) - MAX_ROWS
        rows = rows[:MAX_ROWS]

    events = []
    for ev in rows:
        if not isinstance(ev, dict):
            counts.bad_dropped += 1
            continue
        if _whole(ev.get("EventBodyId")) != body_id:
            counts.other_body_dropped += 1
            continue
        event_id, day = _whole(ev.get("EventId")), _day(ev)
        if event_id is None or event_id < 1 or day is None:
            counts.bad_dropped += 1
            continue
        if day < today:
            counts.past_dropped += 1
            continue
        if day > today + timedelta(days=DAYS_AFTER):     # the query's upper bound, checked, never trusted
            counts.future_dropped += 1
            continue
        events.append((day, event_id, ev))
    events.sort(key=lambda e: (e[0], e[1]))

    proposals: dict[str, dict] = {}
    meetings, published_of = [], {}
    for day, event_id, ev in events:
        name = _status(ev)
        if name is not None and name not in KNOWN_STATUSES:
            counts.unknown_status += 1
            evidence = allowed_url(ev.get("EventInSiteURL"), PLATFORM, client) or url
            p = proposals.setdefault(name, _proposal(gov, name, evidence, stamp))
            p["count"] += 1
        items, item_count = None, None
        if shown and agenda_state(ev, finals) == FINAL:
            published = _published(ev)
            hit = _cache_get(folder, entry, event_id, published, counts)
            if hit is not None:
                items, item_count = hit
            else:
                agenda_url = allowed_url(ev.get("EventAgendaFile"), PLATFORM, client) or None
                counts.items_requests += 1
                items = build_items(_get_json(fetcher, items_url(client, event_id), gov, f"event {event_id} items"),
                                    agenda_url)
                if published is not None:
                    published_of[meeting_id(day, event_id)] = (event_id, published)
        meetings.append(meeting(ev, items, tz, client=client, withheld=not shown, final_statuses=finals,
                                item_count=item_count))

    feed = {"schema": UPCOMING_SCHEMA, "review": entry["review"] if shown else None,
            "body": {"id": gov, "name": entry["body_name"], "tz": tz, "official_url": entry.get("official_url"),
                     "platform": PLATFORM, "full_url": None},
            "checked_at": stamp, "last_ok_at": stamp, "meetings": meetings}
    feed, counts.guard = clean_feed(feed, PLATFORM, client)
    try:
        feed, counts.bind = bind_feed(feed, entry)
    except ValueError as e:                  # BindError
        raise FeedError(f"{gov}: {e}") from e
    errors = feed_errors(feed)
    if errors:
        raise FeedError(f"{gov}: feed does not match {UPCOMING_SCHEMA}:\n" + "\n".join(errors))

    if folder is not None and feed["review"] is not None:      # only items that passed the guards, bind and schema
        for m in feed["meetings"]:
            if m["id"] in published_of:
                event_id, published = published_of[m["id"]]
                _cache_put(root, folder, entry, event_id, published, m["items"], m["item_count"])
    return BodyRead(feed=feed, proposals=sorted(proposals.values(), key=lambda p: str(p["observed"])),
                    counts=counts)
