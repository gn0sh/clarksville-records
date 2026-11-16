"""Montgomery County's "Committee Agendas" page: the CMCSS school board's agendas (mirrored by the county) and the
county finance committees' agendas (Budget Committee, budget hearings, Audit, Investment, Purchasing, Delinquent Tax).

python -m collector county-committees fetch [--limit N]   the page, then the listed agendas the store lacks
python -m collector county-committees build                read the stored agendas -> agendas.json (offline)
python -m collector county-committees run                  fetch then build
python -m collector county-committees daily [--offline]    the daily step on its own (`collector run` calls run_step)

Rules (config/localities/montgomery-tn/committee-agendas.yml; docs/research/committee-sources-2026-11-11.md):
- one GET of the page lists every agenda, one folder (<dt>) per body. Each URL is taken from the page as printed,
  resolved against the page URL; none is ever built. Only the folders the config names are read;
- requests go through collector.fetch.PoliteFetcher: allowlist, robots.txt before every request, 10 s per host, our
  honest User-Agent, GET only; a 403/429 stops the host for the run (never retried, never worked around);
- the meeting date is read from the file name as printed (MM-DD-YY, MM-DD-YYYY, M-D-YYYY, YYYY-MM-DD, MMDDYY/YYMMDD
  when only one reading is a real date, "Month D, YYYY"); a name with no readable date is reported, never guessed.
  CANCELED, RESCHEDULED, SPECIAL CALLED and a printed time are kept as printed;
- the page shows the current year only: a row no longer on the page stays in listing.json (`on_page: false`) and its
  stored file stays a source, so a January rollover drops nothing;
- an agenda whose meeting day has not passed is asked for again once per run with a conditional GET (a revised
  agenda becomes a new store version; an unchanged one answers 304);
- these agendas carry no votes and no minutes: nothing here reads or invents either.

Files (data/localities/montgomery-tn/committee-agendas/, so no other body's manifest or facts are touched):
- listing.json    every listed agenda of the configured folders as printed (committed; a build reads it offline)
- manifest.json   one entry per fetched file (committed), bytes in the gitignored store
- agendas.json    bodies, meetings, their agenda source and the agenda's items as printed (collector/committee_agenda
                  _text below), resolution numbers linked to County Commission items by exact number
- build/county-committees-report.json   counts, problems, the fetch log
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import yaml

from . import limits
from .fetch import (FetchFailed, HostBlocked, HostRefused, PoliteFetcher, ProxyRefused, RequestCapReached,
                    RobotsDisallowed)
from .rpc import write_json
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "localities" / "montgomery-tn" / "committee-agendas.yml"
STOP = (HostBlocked, HostRefused, ProxyRefused, RobotsDisallowed)   # the host said no (or policy): stop, never retry
# Requests to montgomerytn.gov per run at most (robots.txt, the page, every agenda, rechecks, redirects). The page
# listed 30 agendas of the configured folders on 2026-11-16; a normal day is robots.txt, the page and 0 to 4 more.
DAILY_FETCH_CAP = 60
# The largest agenda this step stores (bytes). The 50 agendas of 2026 were 56,951 to 237,626 B (one or two pages);
# a file over this is not read past this size (the fetcher's max_bytes is lowered to it while agendas are fetched:
# a `fetch.MAX_BYTES` trip at this cap), not stored, and a failure in the report.
MAX_AGENDA_BYTES = 20_000_000
KEYS = ("locality", "listing_url", "record_label", "facts", "fetch_hosts", "fetch_path", "fetch_extensions", "bodies")
BODY_KEYS = ("folder", "key", "group", "name", "short", "kind_rules", "kind_labels")
GROUPS = ("school", "county-finance")
SLUG = re.compile(r"^[a-z][a-z0-9-]*$")
MONTHS = ("january february march april may june july august september october november december").split()


class ConfigError(Exception):
    pass


class ListingError(Exception):
    """The page is not the page we know (moved or rebuilt). Fails loudly; nothing is guessed."""


@dataclass(frozen=True)
class Body:
    folder: str
    key: str
    group: str
    name: str
    short: str
    kind_rules: tuple          # ((kind, compiled), ...)
    kind_labels: dict
    text: bool = True          # false: no agenda item text or heading is stored for this body, only the count of lines

    def kind_of(self, label: str) -> str:
        for kind, rx in self.kind_rules:
            if rx.search(label or ""):
                return kind
        return self.kind_rules[-1][0]


@dataclass(frozen=True)
class Config:
    locality: str
    listing_url: str
    record_label: str
    facts: str
    fetch_hosts: tuple
    fetch_path: str
    fetch_extensions: tuple
    bodies: tuple              # (Body, ...)

    def body_for(self, folder: str) -> Body | None:
        return next((b for b in self.bodies if b.folder == folder), None)

    def fetchable(self, url: str) -> bool:
        """An https URL on a fetch host whose path, unquoted and normalised, is under fetch_path with no ".." or "."
        segment and no backslash (a "../" or "%2e%2e/" never leads out of the calendar files), ending in a fetched
        extension."""
        u = urllib.parse.urlsplit(url)
        path = urllib.parse.unquote(u.path)
        segs = path.split("/")
        return (u.scheme == "https" and u.netloc.lower() in self.fetch_hosts and not u.query
                and "\\" not in path and ".." not in segs and "." not in segs
                and posixpath.normpath(path) == path and path.startswith(self.fetch_path)
                and path.lower().endswith(self.fetch_extensions))


def load_config(path: Path = CONFIG) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    missing = [k for k in KEYS if k not in raw]
    if missing:
        raise ConfigError(f"{path}: missing {', '.join(missing)}")
    if not str(raw["listing_url"]).startswith("https://"):
        raise ConfigError(f"{path}: listing_url must be https")
    bodies, seen = [], set()
    for b in raw["bodies"] or []:
        miss = [k for k in BODY_KEYS if k not in b]
        if miss:
            raise ConfigError(f"{path}: body {b.get('key')!r}: missing {', '.join(miss)}")
        if not SLUG.match(str(b["key"])) or b["key"] in seen:
            raise ConfigError(f"{path}: body key {b['key']!r}: lowercase letters, digits and '-', once each")
        if b["group"] not in GROUPS:
            raise ConfigError(f"{path}: body {b['key']}: group must be one of {', '.join(GROUPS)}")
        seen.add(b["key"])
        try:
            rules = tuple((str(k), re.compile(rx, re.I)) for k, rx in b["kind_rules"])
        except (TypeError, ValueError, re.error) as e:
            raise ConfigError(f"{path}: body {b['key']}: kind_rules: {e}") from e
        if not rules or any(k not in b["kind_labels"] or not SLUG.match(k) for k, _ in rules):
            raise ConfigError(f"{path}: body {b['key']}: every kind needs a kind_labels entry and a slug name")
        if "withhold" in b:
            raise ConfigError(f"{path}: body {b['key']}: withhold rules are retired; use text: false "
                              "(docs/architecture/agenda-withhold-invariant.md)")
        if not isinstance(b.get("text", True), bool):
            raise ConfigError(f"{path}: body {b['key']}: text must be true or false")
        bodies.append(Body(**{**{k: b[k] for k in BODY_KEYS}, "kind_rules": rules, "text": b.get("text", True)}))
    if not bodies:
        raise ConfigError(f"{path}: no bodies")
    return Config(**{**{k: raw[k] for k in KEYS if k != "bodies"},
                     "fetch_hosts": tuple(h.lower() for h in raw["fetch_hosts"]),
                     "fetch_extensions": tuple(e.lower() for e in raw["fetch_extensions"]),
                     "bodies": tuple(bodies)})


# ------------------------------------------------------------------ the page
class _Folders(HTMLParser):
    """Each <a href> with the folder it is listed under: the text of the <dt> whose <dd> holds it (folders nest: the
    page puts sub-folders inside the Regional Planning Commission's <dd>; a link belongs to the innermost open one)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[dict] = []
        self.folders: list[str] = []
        self._stack: list[str] = []
        self._dt: list[str] | None = None
        self._last_dt = ""
        self._a: dict | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "dt":
            self._dt = []
        elif tag == "dd":
            self._stack.append(self._last_dt)
        elif tag == "a":
            href = dict(attrs).get("href")
            if href and self._stack:
                self._a = {"href": href.strip(), "text": "", "folder": self._stack[-1]}

    def handle_endtag(self, tag):
        if tag == "dt" and self._dt is not None:
            self._last_dt = _clean("".join(self._dt))
            self.folders.append(self._last_dt)
            self._dt = None
        elif tag == "dd" and self._stack:
            self._stack.pop()
        elif tag == "a" and self._a is not None:
            self.links.append(self._a)
            self._a = None

    def handle_data(self, d):
        if self._dt is not None:
            self._dt.append(d)
        if self._a is not None:
            self._a["text"] += d


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _iso(y: int, m: int, d: int) -> str | None:
    if y < 100:
        y += 2000
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


ISO_RX = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
MDY_RX = re.compile(r"(?<!\d)(\d{1,2})(?:\s*[-.]\s*|\s+)(\d{1,2})(?:\s*[-.]\s*|\s+)(\d{4}|\d{2})(?!\d)")
SIX_RX = re.compile(r"(?<!\d)(\d{6})(?!\d)")
WORDS_RX = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
TIME_RX = re.compile(r"(?<![\w:])(\d{1,2}(?::\d{2})?\s*[AP]\.?M\.?)(?!\w)", re.I)
# Labels kept as printed: a cancelled meeting, a rescheduled one, a special called one
NOTE_RX = re.compile(r"\b(cancel+ed|rescheduled|special[\s-]+called)\b", re.I)


def name_date(text: str) -> tuple[str | None, str | None]:
    """(ISO date, None) read from a file name as printed, or (None, why). Formats seen on the page (2026-11-16):
    "01-13-26", "08-04-2026", "1-28-2026", "2026-04-08", "Agenda 01 08 2026", "5-19- 26", "260212" (YYMMDD),
    "031926" (MMDDYY), "November 12, 2026". A six-digit run is read only when exactly one of MMDDYY and YYMMDD is a
    real date. More than one different date in a name is not guessed between."""
    found: list[str] = []
    rest = text
    for m in ISO_RX.finditer(rest):
        d = _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            found.append(d)
    rest = ISO_RX.sub(" ", rest)
    for m in WORDS_RX.finditer(rest):
        d = _iso(int(m.group(3)), MONTHS.index(m.group(1).lower()) + 1, int(m.group(2)))
        if d:
            found.append(d)
    rest = WORDS_RX.sub(" ", rest)
    for m in MDY_RX.finditer(rest):
        d = _iso(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if d:
            found.append(d)
    rest = MDY_RX.sub(" ", rest)
    for m in SIX_RX.finditer(rest):
        s = m.group(1)
        readings = {x for x in (_iso(int(s[4:]), int(s[:2]), int(s[2:4])), _iso(int(s[:2]), int(s[2:4]), int(s[4:])))
                    if x}
        if len(readings) == 1:
            found.append(readings.pop())
        elif readings:
            return None, f"{s!r} reads as more than one date"
    found = sorted(set(found))
    if not found:
        return None, "no date in the file name"
    if len(found) > 1:
        return None, f"more than one date in the file name: {', '.join(found)}"
    return found[0], None


def parse_listing(page: str, cfg: Config) -> tuple[list[dict], list[str]]:
    """(rows, problems). One row per listed file of a configured folder, in page order:
    {body, folder, file, printed, url, date, time, notes, cancelled, kind, fetch}. A file whose name gives no date is
    a problem, not a row. A configured folder missing from the page is a problem (the page changed?); no folder at
    all is a ListingError."""
    p = _Folders()
    p.feed(page)
    if not p.folders:
        raise ListingError(f"{cfg.listing_url}: no folders found (the page changed?)")
    problems = [f"folder {b.folder!r} is not on the page" for b in cfg.bodies if b.folder not in p.folders]
    rows = []
    for a in p.links:
        body = cfg.body_for(a["folder"])
        if body is None:
            continue
        url = urllib.parse.urljoin(cfg.listing_url, urllib.parse.quote(a["href"], safe="/:%?&=#~"))
        if urllib.parse.urlsplit(url).scheme != "https":      # http:, mailto:, javascript: ... never a row
            problems.append(f"{body.folder}: {a['href'][:200]!r}: not an https link; not listed")
            continue
        file = _clean(a["text"]) or urllib.parse.unquote(url.rsplit("/", 1)[-1])
        printed = re.sub(r"\.+pdf$", "", file, flags=re.I).strip()
        when, why = name_date(printed)
        if when is None:
            problems.append(f"{body.folder}: {file!r}: {why}")
            continue
        notes = [_clean(m.group(1)) for m in NOTE_RX.finditer(printed)]
        tm = TIME_RX.search(printed)
        rows.append({"body": body.key, "folder": body.folder, "file": file, "printed": printed, "url": url,
                     "date": when, "time": _clean(tm.group(1)) if tm else None, "notes": notes,
                     "cancelled": any(re.match(r"cancel", n, re.I) for n in notes),
                     "kind": body.kind_of(printed), "fetch": cfg.fetchable(url), "on_page": True})
    return rows, problems


def _time_key(t: str | None) -> str:
    """"9AM" -> "0900", "1PM" -> "1300", for an id and ordering only (the page shows the time as printed)."""
    if not t:
        return ""
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*([AP])", t, re.I)
    if not m:
        return ""
    h = int(m.group(1)) % 12 + (12 if m.group(3).upper() == "P" else 0)
    return f"{h:02d}{m.group(2) or '00'}"


def assign_ids(rows: list[dict]) -> list[dict]:
    """Each row's meeting id within its body: <date>-<kind>[-<hhmm> when a time is printed], with -2, -3 on a repeat,
    in (date, time, url) order so the ids do not depend on the page's order."""
    seen: dict[tuple, int] = {}
    out = []
    for r in sorted(rows, key=lambda r: (r["body"], r["date"], _time_key(r.get("time")), r["url"])):
        base = f"{r['date']}-{r['kind']}" + (f"-{_time_key(r.get('time'))}" if _time_key(r.get("time")) else "")
        k = (r["body"], base)
        seen[k] = seen.get(k, 0) + 1
        out.append({**r, "id": base if seen[k] == 1 else f"{base}-{seen[k]}"})
    return out


def merge_rows(old: list[dict], new: list[dict]) -> list[dict]:
    """The page's rows plus every committed row no longer on the page (`on_page: false`), so the January rollover
    (the page lists the current year only) drops nothing. Keyed by URL."""
    urls = {r["url"] for r in new}
    kept = [{**r, "on_page": False} for r in old if r["url"] not in urls]
    return assign_ids([{k: v for k, v in r.items() if k != "id"} for r in new + kept])


# ------------------------------------------------------------------ fetch
def paths(cfg: Config, root: Path = ROOT) -> dict:
    d = root / "data" / "localities" / cfg.locality / "committee-agendas"
    return {"dir": d, "listing": d / "listing.json", "manifest": d / "manifest.json", "facts": root / cfg.facts,
            "changes": d / "changes.jsonl", "report": root / "build" / "county-committees-report.json"}


def new_log() -> dict:
    return {"failures": [], "fetched": {}, "problems": []}


def _count(log: dict, k: str) -> None:
    log["fetched"][k] = log["fetched"].get(k, 0) + 1


def cmd_fetch(cfg: Config, store: Store, listing_path: Path, log: dict, fetcher=None, limit: int | None = None,
              max_requests: int | None = DAILY_FETCH_CAP, today: date | None = None) -> list[dict] | None:
    """The page, then each listed agenda the store lacks (at most `limit` of them), and once each stored agenda whose
    meeting day has not passed (a conditional GET). Returns the merged rows written to listing.json, or None when the
    page was not read (listing.json is then left as it is). A failure where the host or policy said no carries
    `stop: True` and ends the run's requests."""
    f = fetcher or PoliteFetcher()
    today = today or datetime.now(timezone.utc).date()
    hosts = {urllib.parse.urlsplit(cfg.listing_url).netloc.lower(), *cfg.fetch_hosts}
    if max_requests is not None:
        f.limit_hosts(hosts, max_requests)
    try:
        status, body, _ = f.get(cfg.listing_url)
        if status != 200:
            raise ListingError(f"HTTP {status} for {cfg.listing_url}")
        rows, problems = parse_listing(body.decode("utf-8", "replace"), cfg)
    except (ListingError, FetchFailed, RequestCapReached) + STOP as e:
        log["failures"].append({"stage": "listing", "error": f"{type(e).__name__}: {e}", "stop": isinstance(e, STOP)})
        log["fetch_log"] = f.log
        return None
    log["problems"] += problems
    old = json.loads(listing_path.read_text(encoding="utf-8")) if listing_path.is_file() else []
    rows = merge_rows(old, rows)
    write_json(listing_path, rows)
    # the agendas are read at most MAX_AGENDA_BYTES (+1) into memory: the fetcher's own cap is lowered for this loop
    # (a shared fetcher from `collector run` gets its cap back after), and the check below backs a fetcher without one
    cap = getattr(f, "max_bytes", None)
    if cap is not None:
        f.max_bytes = min(cap, MAX_AGENDA_BYTES)
    try:
        _fetch_agendas(f, store, rows, log, limit, today)
    finally:
        if cap is not None:
            f.max_bytes = cap
    store.save()
    log["fetch_log"] = f.log
    return rows


def _fetch_agendas(f, store: Store, rows: list[dict], log: dict, limit: int | None, today: date) -> None:
    asked = 0
    for r in rows:
        if not r["fetch"] or not r["on_page"]:
            continue
        known = store.latest(r["url"])
        have = bool(known and store.has_bytes(known["sha256"]))
        if have and r["date"] < today.isoformat():
            _count(log, "cached")
            continue
        if not have and limit is not None and asked >= limit:
            _count(log, "over_limit")
            continue
        meta = {"kind": f"agenda_{r['body']}", "meeting_date": r["date"], "label": f"{r['folder']}: {r['printed']}"}
        try:
            if have and (known.get("etag") or known.get("last_modified")):
                st, data, headers = f.get_if_changed(r["url"], etag=known.get("etag"),
                                                     last_modified=known.get("last_modified"))
            else:
                st, data, headers = f.get(r["url"])
            asked += 0 if have else 1
        except RequestCapReached:
            _count(log, "over_cap")
            continue
        except STOP as e:
            log["failures"].append({"stage": "fetch", "url": r["url"], "error": f"{type(e).__name__}: {e}",
                                    "stop": True})
            break
        except FetchFailed as e:              # one file is logged and skipped
            log["failures"].append({"stage": "fetch", "url": r["url"], "error": f"{type(e).__name__}: {e}"})
            continue
        if have and st == 304:
            _count(log, "not_modified")
            continue
        if st != 200 or data[:4] != b"%PDF":
            log["failures"].append({"stage": "fetch", "url": r["url"],
                                    "error": f"HTTP {st}" if st != 200 else "not a PDF"})
            continue
        if len(data) > MAX_AGENDA_BYTES:      # limit trip: reported, never stored
            log["failures"].append({"stage": "fetch", "url": r["url"], "error": limits.trip(
                "county_committees.MAX_AGENDA_BYTES", r["url"], f"{len(data)} B", f"{MAX_AGENDA_BYTES} B")})
            continue
        _, how = store.put(r["url"], data, headers, meta)
        _count(log, how)
        store.save()                          # saved as it goes, so a stopped run keeps what it fetched


# ------------------------------------------------------------------ the daily step
def run_step(log: dict, offline: bool, fetcher=None, cfg: Config | None = None, root: Path = ROOT,
             store: Store | None = None, today: date | None = None, read=None, count=None) -> int:
    """The daily step (collector run): read the page and fetch what is new (unless offline), then rebuild
    agendas.json from the stored agendas. All or nothing: a page not read or a host that said no (2), or a result that
    would drop a meeting or a read agenda the committed file has (a store with gaps: 0 offline, 4 online), leaves
    listing.json, manifest.json, changes.jsonl and agendas.json exactly as they were. Never raises; the summary
    goes to log['county_committees'] and build/county-committees-report.json. Returns 0 ok, 2 the page was not read
    or the host said no, 4 the result would shrink the record, 1 an unexpected error."""
    from .committee_agenda_text import build, shrink_reason
    out: dict = {"offline": offline, "status": None}
    since = limits.mark()                      # this step's own trips only (limits invariant rule 3)
    code = 0
    p = snap = None
    try:
        cfg = cfg or load_config()
        p = paths(cfg, root)
        snap = {k: (p[k].read_bytes() if p[k].is_file() else None) for k in ("listing", "manifest", "changes", "facts")}
        store = store or Store(manifest_path=p["manifest"])
        if offline:
            rows = json.loads(p["listing"].read_text(encoding="utf-8")) if p["listing"].is_file() else []
        else:
            flog = new_log()
            rows = cmd_fetch(cfg, store, p["listing"], flog, fetcher=fetcher, today=today)
            out["fetch"] = {k: v for k, v in flog.items() if k != "fetch_log"}
            out["fetch_log"] = flog.get("fetch_log", [])
            if rows is None or any(x.get("stop") for x in flog["failures"]):
                out["status"] = f"stopped, nothing changed: {(flog['failures'] or [{}])[0].get('error')}"[:400]
                out["kept"] = True
                code = 2
        if not code:
            facts, summary = build(cfg, rows, store, root=root, read=read, count=count)
            out["build"] = summary
            old = json.loads(p["facts"].read_text(encoding="utf-8")) if p["facts"].is_file() else None
            why = shrink_reason(old, facts) if old else None
            if why:
                out["status"] = f"nothing changed: {why}"
                out["kept"] = True
                code = 0 if offline else 4      # offline (a fresh checkout): the committed record stands
            else:
                out["changed"] = write_json(p["facts"], facts)
                out["status"] = (f"{summary['meetings']} meetings, {summary['sources']} agendas read, "
                                 f"{summary['items']} items; {p['facts'].name} "
                                 f"{'rewritten' if out['changed'] else 'unchanged'}")
    except Exception as e:      # this step never takes the county run down; nothing of its own is left half written
        out["status"] = f"error, nothing changed: {type(e).__name__}: {e}"[:400]
        out["kept"] = True
        code = 1
    if snap is not None and out.get("kept"):
        for k, body in snap.items():
            if body is None:
                p[k].unlink(missing_ok=True)
            elif not p[k].is_file() or p[k].read_bytes() != body:
                p[k].write_bytes(body)
    out["exit"] = code
    out["limits"] = limits.tripped(since)
    fetch_log = out.pop("fetch_log", [])
    if p is not None:
        try:
            write_json(p["report"], {**out, "fetch_log": fetch_log})
        except OSError as e:
            out["report_error"] = str(e)
    problems = (out.get("build") or {}).pop("problems", None)
    if problems is not None:
        out["build"]["problems"] = len(problems)          # the full list is in the report file
    log["county_committees"] = out
    print(f"collector: county committees: exit {code}: {out['status']}", flush=True)
    print(limits.summary("collector: county committees", since), flush=True)
    return code


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m collector county-committees")
    ap.add_argument("command", choices=("fetch", "build", "run", "daily"))
    ap.add_argument("--limit", type=int, default=None, help="request at most N agendas the store lacks")
    ap.add_argument("--offline", action="store_true", help="daily: no fetching, build from the store")
    a = ap.parse_args(argv)
    if a.command == "daily":
        return run_step({}, a.offline)
    cfg = load_config()
    p = paths(cfg)
    store = Store(manifest_path=p["manifest"])
    log = new_log()
    rows = None
    if a.command in ("fetch", "run"):
        rows = cmd_fetch(cfg, store, p["listing"], log, limit=a.limit)
    report = {"fetch": {k: v for k, v in log.items() if k != "fetch_log"}}
    if a.command in ("build", "run"):
        from .committee_agenda_text import build
        rows = json.loads(p["listing"].read_text(encoding="utf-8")) if p["listing"].is_file() else []
        facts, summary = build(cfg, rows, store)
        write_json(p["facts"], facts)
        report["build"] = summary
    write_json(p["report"], {**report, "fetch_log": log.get("fetch_log", [])})
    print(json.dumps(report, indent=1, default=str)[:4000])
    return 2 if any(f["stage"] == "listing" or f.get("stop") for f in log["failures"]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
