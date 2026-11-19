"""Daylight Digest, the national collection run (docs/architecture/daylight-national.md 3.7, 4.4.1, 4.5; ADR 0013
decision 6; task C3): every covered Legistar body in budget order, one `read_body` each (C2), never failing the run on
one body's failure, then the feeds, `health.json` and `proposals.json` of `data/national/`.

- **Host OK first** (Brian's rule R5, security finding 7, `national/r5-not-enforced`): before any fetcher call (even
  `limit_hosts`) or cache pruning, every entry on a platform other than daylight must hold a valid `host_ok: {date,
  link}` (`host_ok_valid`, the loader's own check). One without it refuses the whole run (`HostNotApproved`): a
  directory that got past the loader is a bug, not one body's failure, and no request goes to an unapproved host.
- **Budget** (ADR 0013 decision 6): the run's request budget on `webapi.legistar.com` goes to the fetcher's
  `limit_hosts`, and at most TENANT_BUDGET requests per tenant to `limit_tenant`. Order: bodies with a meeting in the
  next SOON_DAYS days whose agenda was not final at the last read, then bodies not read longest (never read first). A
  body the budget does not reach, or whose read runs into a cap, records `budget-skipped`.
- **Stops** (4.4.1): a `TenantBlocked` (caught before `HostBlocked`, `national/tenant-caller-order`) stops that body's
  tenant only; the host's other tenants go on. It also denies the city's own Legistar host (`<client>.legistar.com`)
  for the rest of the run (manager decision, C1 fresh review). A host stop (any other `HostBlocked`, or robots.txt
  that could not be read) marks every body not yet read on that host `host-stopped`: stale, never `cant-cover`.
- **No curated status is written**: the directory is only read. A suggested status change goes to `proposals.json`
  for a person (kind `status`, after STATUS_PROPOSAL_AFTER failures in a row of a kind that suggests one).
- **Freshness** (`national-freshness/checked-at-is-first-fetch`): each body read is stamped when it starts (`clock`);
  that stamp is the feed's `checked_at` and, on success, `last_ok_at`. A body whose read failed keeps its last good
  feed (rebound to its current entry) with the new `checked_at` and the old `last_ok_at`; a body not read this run
  keeps its feed unchanged.
- **Ids** (6, Security): every government id is matched against the id regex (`checked_id` / `id_layer`) before it
  becomes a path or a key; ids read back from files that do not match are dropped.
- Health and proposals carry ids, fixed kinds, instants and counts only, never text from an answer (11.1 row 23).
"""
from __future__ import annotations

import copy
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, NamedTuple
from zoneinfo import ZoneInfo

from collector.fetch import (FetchFailed, HostBlocked, HostRefused, ProxyRefused, RequestCapReached, RobotsDisallowed,
                             TenantBlocked, TenantCapReached, tenant_key)
from collector.national import legistar_upcoming as lu
from sitegen.national import Directory
from sitegen.national_clarksville import feed_errors
from sitegen.national_guards import allowed_url, bind_feed, checked_id, host_ok_problem, id_layer

HOST = lu.LEGISTAR_API_HOST
TENANT_BUDGET = 12               # ADR 0013 decision 6: at most 12 requests per tenant per run
SOON_DAYS = 7                    # ... bodies with a not-final agenda in the next 7 days are read first
STATUS_PROPOSAL_AFTER = 3        # failures in a row of one of STATUS_REASON's kinds before a status proposal

OK = "ok"
# 3.7 `last_error` values. `collector-error` (added by C3): the reader refused its own output or its cache (a bug or a
# tampered cache file, e.g. C2's _cache_put ValueError, `cache-confine/put-error-kind`); nothing of it was written.
LAST_ERRORS = ("tenant-blocked", "host-stopped", "rate-limited", "robots", "budget-skipped", "server-error",
               "not-enabled-suspected", "token-suspected", "collector-error")
# Not the body's failure (scheduling, or a stop about us or the shared host): consecutive_failures and the failure
# streak are left as they were (`national-proposal/streak-not-per-kind`).
NOT_A_FAILURE = frozenset({"budget-skipped", "host-stopped", "rate-limited"})
# A failure kind that, repeated, suggests the entry may belong in `cant-cover` with this reason (3.2 REASONS).
STATUS_REASON = {"not-enabled-suspected": "api-not-enabled", "token-suspected": "token-required",
                 "robots": "robots-disallow"}
PROPOSAL_KINDS = ("status", "agenda-status-name")

INSTANT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
MAX_URL = 2_000                  # characters of an evidence_url read back
BODY_FILE_RE = re.compile(r"[a-z]+-[0-9]{5,10}\.json")


class HostNotApproved(ValueError):
    """An entry on a platform other than daylight has no valid `host_ok` (Brian's OK, R5): the run sends nothing."""


class RunResult(NamedTuple):
    feeds: dict          # body id -> bound, schema-checked `daylight-upcoming/1` feed (a body with none has no key)
    health: dict         # body id -> 3.7 health record
    proposals: list      # 3.7 proposals, merged with the previous run's
    outcomes: dict       # body id -> "ok" or its `last_error` this run (the run log; counts only)


# --- small helpers ------------------------------------------------------------------------------------------------

def _instant(t: datetime) -> str:
    if not isinstance(t, datetime) or t.tzinfo is None:
        raise ValueError("a run stamp must be a datetime with a time zone")
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _old_instant(value) -> str | None:
    return value if isinstance(value, str) and INSTANT_RE.fullmatch(value) else None


def _count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _tenant_url(entry: dict) -> str:
    """The tenant root of an entry's client; only ever used for the fetcher's tenant key and cap."""
    return f"{lu.API_ROOT}/{entry[lu.PLATFORM]['client']}/"


def _today(entry: dict, now: datetime) -> date:
    return now.astimezone(ZoneInfo(entry[lu.PLATFORM]["tz"])).date()


def _evidence_url(entry: dict, now: datetime) -> str:
    """The events query a run makes for this body (what a person opens to check a suggested status)."""
    keys, today = entry[lu.PLATFORM], _today(entry, now)
    return lu.events_url(keys["client"], int(keys["body_id"]), today - timedelta(days=lu.DAYS_BEFORE),
                         today + timedelta(days=lu.DAYS_AFTER + 1))


def _last_block_was_429(fetcher, host: str) -> bool:
    for e in reversed(getattr(fetcher, "log", None) or []):
        if isinstance(e, dict) and e.get("event") == "blocked" and e.get("host") == host and "tenant" not in e:
            return str(e.get("detail", "")).startswith("HTTP 429")
    return False


def _robots_unreadable(fetcher, host: str) -> bool:
    """robots.txt could not be read this run (refused, a server error, too many redirects), as opposed to read and
    disallowing (`national-stop/robots-5xx-not-host-stop`; the fetcher's public `robots_unreadable`)."""
    return fetcher.robots_unreadable(host) is not None


def _deny_city_hosts(fetcher, entry: dict) -> None:
    """A webapi tenant block for a city stops that city's other Legistar hosts for the run (e.g. salem.legistar.com;
    manager decision on the C1 fresh review). Today they are linked, never fetched; this keeps it so for the run."""
    host = f"{entry[lu.PLATFORM]['client']}.legistar.com"
    denied = tuple(getattr(fetcher, "extra_denied", ()) or ())
    if host not in denied:
        fetcher.extra_denied = denied + (host,)


# --- order --------------------------------------------------------------------------------------------------------

def _soon_not_final(entry: dict, feed: dict | None, now: datetime) -> bool:
    if not isinstance(feed, dict) or not isinstance(feed.get("meetings"), list):
        return False
    today = _today(entry, now)
    for m in feed["meetings"]:
        try:
            day = date.fromisoformat(m["date"])
            state = m["agenda"]["state"]
        except (KeyError, TypeError, ValueError):
            continue
        if today <= day <= today + timedelta(days=SOON_DAYS) and state != lu.FINAL:
            return True
    return False


def check_host_ok(directory: Directory) -> None:
    """HostNotApproved unless every entry whose `platform` is set and is not daylight (any status) holds a valid
    `host_ok` (R5, finding 7). Called before the run touches the fetcher, the cache or any file."""
    govs = getattr(directory, "govs", None)
    if not isinstance(govs, (tuple, list)):
        raise HostNotApproved("the directory has no entry list: refused before any request (host_ok, R5)")
    for e in govs:
        if not isinstance(e, dict) or e.get("platform") in (None, "daylight"):
            continue
        problem = host_ok_problem(e.get("host_ok"))
        if problem:
            gov = e.get("gov") if id_layer(e.get("gov")) else "(a bad id)"
            raise HostNotApproved(f"{gov}: platform {str(e.get('platform'))[:40]!r} has no valid host_ok (Brian's OK, "
                                  f"R5): {problem[0]}: {problem[1]}; the run is refused and sends no request")


def budget_order(entries: list[dict], previous_feeds: dict, previous_health: dict, now: datetime) -> list[dict]:
    """ADR 0013 decision 6: a not-final agenda in the next SOON_DAYS days first, then not read longest (never read
    first), then id, so the order is stable."""
    def key(e):
        h = previous_health.get(e["gov"])
        last_ok = _old_instant(h.get("last_ok_at")) if isinstance(h, dict) else None
        return (not _soon_not_final(e, previous_feeds.get(e["gov"]), now), last_ok or "", e["gov"])
    return sorted(entries, key=key)


# --- feeds kept from an earlier run -------------------------------------------------------------------------------

def _kept_feed(previous: dict | None, entry: dict, stamp: str | None) -> dict | None:
    """The last good feed, rebound to the entry as it is now (it may have become withheld or been re-reviewed since:
    11.1 row 16), with `checked_at` set to this run's stamp when the body was read and failed. None when there is none
    or it no longer binds or matches the schema (the page then shows the government as stale)."""
    if not isinstance(previous, dict):
        return None
    feed = copy.deepcopy(previous)
    if stamp is not None:
        feed["checked_at"] = stamp
    try:
        feed, _counts = bind_feed(feed, entry)
    except ValueError:
        return None
    return None if feed_errors(feed) else feed


# --- proposals ----------------------------------------------------------------------------------------------------

def _valid_proposal(p, clients: dict[str, str]) -> bool:
    """A proposal read back from the last run's file, re-checked as if it came from outside
    (`national-proposal/previous-text-unchecked`): a covered Legistar body, a known kind, `observed` a status name
    STATUS_NAME_RE accepts (or null) or, for `status`, one of the reasons we suggest, and `evidence_url` a Legistar
    URL `allowed_url` keeps for that body's client."""
    if not (isinstance(p, dict) and p.get("body") in clients and p.get("kind") in PROPOSAL_KINDS
            and _old_instant(p.get("first_seen")) is not None):
        return False
    observed, url = p.get("observed"), p.get("evidence_url")
    if p["kind"] == "status":
        ok_observed = observed in STATUS_REASON.values()
    else:
        ok_observed = observed is None or (isinstance(observed, str) and bool(lu.STATUS_NAME_RE.fullmatch(observed)))
    return ok_observed and isinstance(url, str) and len(url) <= MAX_URL \
        and allowed_url(url, lu.PLATFORM, clients[p["body"]]) == url


def merge_proposals(previous: list, new: list[dict], read_ok: set[str], clients: dict[str, str]) -> list[dict]:
    """Earlier proposals plus this run's, one per (body, kind, observed): `first_seen` is the earliest, `count` the
    sum, `evidence_url` the newest. A body's `status` proposals go once it reads OK; a body no longer covered on
    Legistar keeps none. `clients`: covered Legistar body id -> its client."""
    merged: dict[tuple, dict] = {}
    for p in previous if isinstance(previous, list) else []:
        if not _valid_proposal(p, clients) or (p["kind"] == "status" and p["body"] in read_ok):
            continue
        k = (p["body"], p["kind"], p["observed"])
        merged[k] = {"body": p["body"], "kind": p["kind"], "observed": p["observed"],
                     "evidence_url": p["evidence_url"], "first_seen": p["first_seen"], "count": _count(p.get("count"))}
    for p in new:
        k = (p["body"], p["kind"], p["observed"])
        if k in merged:
            old = merged[k]
            old["count"] += _count(p["count"])
            old["evidence_url"] = p["evidence_url"]
            old["first_seen"] = min(old["first_seen"], p["first_seen"])
        else:
            merged[k] = dict(p, count=_count(p["count"]))
    return sorted(merged.values(), key=lambda p: (p["body"], p["kind"], str(p["observed"])))


# --- the run ------------------------------------------------------------------------------------------------------

def _classify(err: BaseException, fetcher) -> str:
    """One body's failure -> its 3.7 `last_error`. Order matters: TenantBlocked is a HostBlocked and TenantCapReached
    a RequestCapReached, so each subclass is tested first (`national/tenant-caller-order`)."""
    if isinstance(err, TenantBlocked):
        return "tenant-blocked"
    if isinstance(err, HostBlocked):
        return "rate-limited" if _last_block_was_429(fetcher, HOST) else "host-stopped"
    if isinstance(err, RequestCapReached):            # TenantCapReached included
        return "budget-skipped"
    if isinstance(err, RobotsDisallowed):
        return "host-stopped" if _robots_unreadable(fetcher, HOST) else "robots"
    if isinstance(err, (HostRefused, ProxyRefused)):  # no request reached the site
        return "host-stopped"
    if isinstance(err, FetchFailed):
        return "server-error"
    if isinstance(err, lu.ReadError):
        return err.kind if err.kind in LAST_ERRORS else "server-error"
    return "collector-error"     # FeedError, _cache_put's ValueError, UnsafeIdError, OSError, anything unforeseen


class _Stops:
    """What this run has stopped so far: the host, tenants, and the tenants already given their cap."""

    def __init__(self):
        self.host: str | None = None                   # what every later body on the host records
        self.tenants: dict[str, str] = {}              # tenant key -> what every later body of it records
        self.capped: set[str] = set()


def _read_one(entry: dict, fetcher, stamp_of, cache_root, stops: _Stops, tenant_budget: int):
    """One body: -> (outcome, stamp or None when it was not read, BodyRead or None)."""
    url = _tenant_url(entry)
    tenant = tenant_key(url)                           # TenantPathRefused: the caller records collector-error
    if tenant is None:
        return "collector-error", None, None
    if tenant not in stops.capped:
        fetcher.limit_tenant(url, tenant_budget)
        stops.capped.add(tenant)
    if stops.host is not None:
        return stops.host, None, None
    if tenant in stops.tenants:
        return stops.tenants[tenant], None, None
    if fetcher.remaining(HOST) == 0 or fetcher.remaining_tenant(url) == 0:
        return "budget-skipped", None, None
    when = stamp_of()
    stamp = _instant(when)
    try:
        return OK, stamp, lu.read_body(entry, fetcher, when, cache_root)
    except Exception as err:          # never the run for one body: every kind is recorded and the next body read
        outcome = _classify(err, fetcher)
        if isinstance(err, TenantBlocked):             # national/tenant-caller-order: before HostBlocked
            stops.tenants[tenant] = "tenant-blocked"
            _deny_city_hosts(fetcher, entry)
        elif isinstance(err, TenantCapReached):        # before RequestCapReached
            stops.tenants[tenant] = "budget-skipped"
        elif isinstance(err, HostBlocked):
            stops.host = "host-stopped"
        elif isinstance(err, RequestCapReached):
            stops.host = "budget-skipped"
        elif isinstance(err, RobotsDisallowed) and outcome == "host-stopped":
            stops.host = "host-stopped"                # robots.txt unreadable: disallow-all is cached for the run
        return outcome, stamp, None


def _streak(prev) -> dict | None:
    s = prev.get("failure_streak")
    if isinstance(s, dict) and s.get("kind") in LAST_ERRORS and _count(s.get("count")) > 0:
        return {"kind": s["kind"], "count": _count(s["count"])}
    return None


def _record(entry: dict, outcome: str, stamp: str | None, read, now: datetime, previous_feeds: dict,
            previous_health: dict) -> tuple[dict | None, dict, list[dict]]:
    """-> (feed or None, health record, new proposals) for one body's outcome."""
    gov = entry["gov"]
    if outcome == OK:
        return read.feed, {"last_attempt_at": stamp, "last_ok_at": stamp, "consecutive_failures": 0,
                           "last_error": None, "failure_streak": None}, list(read.proposals)
    prev = previous_health.get(gov) if isinstance(previous_health.get(gov), dict) else {}
    prev_ok = _old_instant(prev.get("last_ok_at"))
    if prev_ok is None and isinstance(previous_feeds.get(gov), dict):
        prev_ok = _old_instant(previous_feeds[gov].get("last_ok_at"))
    failures, streak = _count(prev.get("consecutive_failures")), _streak(prev)
    if outcome not in NOT_A_FAILURE:
        failures += 1
        streak = {"kind": outcome, "count": streak["count"] + 1 if streak and streak["kind"] == outcome else 1}
    health = {"last_attempt_at": stamp or _old_instant(prev.get("last_attempt_at")), "last_ok_at": prev_ok,
              "consecutive_failures": failures, "last_error": outcome, "failure_streak": streak}
    proposals = []
    if (outcome in STATUS_REASON and streak and streak["kind"] == outcome
            and streak["count"] >= STATUS_PROPOSAL_AFTER):
        proposals.append({"body": gov, "kind": "status", "observed": STATUS_REASON[outcome],
                          "evidence_url": _evidence_url(entry, now), "first_seen": stamp or _instant(now),
                          "count": 1})
    return _kept_feed(previous_feeds.get(gov), entry, stamp), health, proposals


def run(directory: Directory, fetcher, budget: int, now: datetime, *, previous_feeds: dict | None = None,
        previous_health: dict | None = None, previous_proposals: list | None = None, cache_root: Path | None = None,
        clock: Callable[[], datetime] | None = None, tenant_budget: int = TENANT_BUDGET) -> RunResult:
    """One national collection run over every covered Legistar entry of `directory`. Never raises for one body: any
    exception in a body's read or its bookkeeping is that body's `collector-error` (`national-run/raise-outside-try`).
    Raises HostNotApproved, before any fetcher call, for an entry with no valid `host_ok` (`check_host_ok`).

    `fetcher` is a collector.fetch.PoliteFetcher (public API: get, limit_hosts, limit_tenant, remaining,
    remaining_tenant, robots_unreadable, log, extra_denied). `budget` is the run's request budget on
    webapi.legistar.com. `now` (aware) orders the run; `clock()` stamps each body as its read starts (default: `now`
    for every body). `previous_*` are the last run's outputs (`read_previous`). `cache_root` is
    `data/national/cache`: pruned first (11.1 row 19)."""
    check_host_ok(directory)                           # R5: before the fetcher, the cache or any file is touched
    stamp_of = clock or (lambda: now)
    _instant(now)
    previous_feeds = previous_feeds if isinstance(previous_feeds, dict) else {}
    previous_health = previous_health if isinstance(previous_health, dict) else {}

    entries = [e for e in directory.govs if isinstance(e, dict) and e.get("status") == "covered"
               and e.get("platform") == lu.PLATFORM and id_layer(e.get("gov")) is not None]
    clients = {e["gov"]: e[lu.PLATFORM]["client"] for e in entries}

    if cache_root is not None:
        try:
            lu.prune_cache(directory, cache_root)      # before any read, so a body now withheld keeps no item text
        except (OSError, ValueError):
            cache_root = None                          # e.g. a symlinked root: refused, the run reads uncached

    fetcher.limit_hosts([HOST], budget)
    try:
        ordered = budget_order(entries, previous_feeds, previous_health, now)
    except Exception:
        ordered = sorted(entries, key=lambda e: e["gov"])
    stops = _Stops()
    feeds, health, new_proposals, read_ok, outcomes = {}, {}, [], set(), {}

    for entry in ordered:
        gov = checked_id(entry["gov"])
        stamp = None
        try:
            outcome, stamp, read = _read_one(entry, fetcher, stamp_of, cache_root, stops, tenant_budget)
            feed, record, props = _record(entry, outcome, stamp, read, now, previous_feeds, previous_health)
        except Exception:
            outcome, feed, props = "collector-error", None, []
            record = {"last_attempt_at": stamp if isinstance(stamp, str) else None, "last_ok_at": None,
                      "consecutive_failures": 1, "last_error": outcome, "failure_streak": None}
            try:
                _f, record, _p = _record(entry, outcome, stamp, None, now, previous_feeds, previous_health)
            except Exception:
                pass                                   # the bare record above: nothing of the last run is trusted
        outcomes[gov] = outcome
        health[gov] = record
        new_proposals.extend(props)
        if feed is not None:
            feeds[gov] = feed
        if outcome == OK:
            read_ok.add(gov)

    proposals = merge_proposals(previous_proposals or [], new_proposals, read_ok, clients)
    return RunResult(feeds=feeds, health=health, proposals=proposals, outcomes=outcomes)


# --- files (3.7: data/national/) ----------------------------------------------------------------------------------

def _real_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink()


def _load_json(path: Path):
    if not path.is_file() or path.is_symlink():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_previous(data_root: Path) -> tuple[dict, dict, list]:
    """(feeds, health, proposals) of the last run under `data_root` (`data/national`). Files or keys whose id does not
    match the id regex, symlinks and unreadable JSON are left out."""
    root = Path(data_root)
    feeds = {}
    bodies = root / "bodies"
    if _real_dir(bodies):
        for p in sorted(bodies.iterdir()):
            if BODY_FILE_RE.fullmatch(p.name) and id_layer(p.name[:-5]) is not None:
                doc = _load_json(p)
                if isinstance(doc, dict):
                    feeds[p.name[:-5]] = doc
    health = _load_json(root / "health.json")
    health = {k: v for k, v in health.items() if id_layer(k) is not None and isinstance(v, dict)} \
        if isinstance(health, dict) else {}
    proposals = _load_json(root / "proposals.json")
    return feeds, health, proposals if isinstance(proposals, list) else []


def _write(folder: Path, name: str, doc) -> None:
    """Write `folder/name` through a new temporary file (O_EXCL, O_NOFOLLOW); the rename replaces a link at the
    target, never what it points to."""
    tmp = folder / f".{name}.tmp"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    text = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, folder / name)


def check_data_root(data_root: Path) -> Path:
    """Refuse a data root, or a `bodies/` or `cache/` in it, that is a symlink (`national-confine/data-root-symlink-
    late`): called before anything is read, pruned or written, so nothing goes through a link. -> the root."""
    root = Path(data_root)
    for p in (root, root / "bodies", root / "cache"):
        if p.is_symlink():
            raise ValueError(f"{p}: a symlink in the national data tree: refused")
    return root


def body_file(feed: dict) -> dict:
    """What `bodies/<id>.json` holds: the feed minus `body.full_url` (3.7: "3.5 minus full_url"; the copy step's
    bind_feed sets it again from the directory)."""
    out = copy.deepcopy(feed)
    if isinstance(out.get("body"), dict):
        out["body"].pop("full_url", None)
    return out


def write_outputs(data_root: Path, result: RunResult) -> None:
    """`bodies/<id>.json` for every feed (and no other file there), `health.json`, `proposals.json`. A data root or
    bodies folder that is a symlink is refused (the run stops: that is not one body's failure)."""
    root = check_data_root(data_root)
    root.mkdir(parents=True, exist_ok=True)
    bodies = root / "bodies"
    bodies.mkdir(exist_ok=True)
    for gov, feed in sorted(result.feeds.items()):
        if feed.get("body", {}).get("id") != checked_id(gov):
            raise ValueError(f"{gov}: feed body id does not match its file")
        _write(bodies, f"{gov}.json", body_file(feed))
    keep = {f"{gov}.json" for gov in result.feeds}
    for p in sorted(bodies.iterdir()):
        if p.name not in keep:
            lu._remove(p)                  # a body no longer covered, or whose last feed no longer binds
    _write(root, "health.json", result.health)
    _write(root, "proposals.json", result.proposals)


def collect(data_root: Path, directory: Directory, fetcher, budget: int, now: datetime, *,
            clock: Callable[[], datetime] | None = None, tenant_budget: int = TENANT_BUDGET) -> RunResult:
    """check_data_root -> read_previous -> run (cache `data_root/cache`, pruned first) -> write_outputs. The directory
    is never written. A directory `check_host_ok` refuses raises before anything is read or written."""
    check_host_ok(directory)                           # on purpose: run() checks again, but this one runs before data_root is read
    root = check_data_root(data_root)
    feeds, health, proposals = read_previous(root)
    result = run(directory, fetcher, budget, now, previous_feeds=feeds, previous_health=health,
                 previous_proposals=proposals, cache_root=root / "cache", clock=clock, tenant_budget=tenant_budget)
    write_outputs(root, result)
    return result
