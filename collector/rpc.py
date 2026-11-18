"""Regional Planning Commission (RPC) from www.cmcrpc.com: list its meetings, fetch their agendas and minutes, read the
agendas' case items (milestone RPC-1).

python -m collector rpc fetch [--limit N]    the listing page, then the listed PDF/DOCX the store lacks (at most N
                                             of them; at most DAILY_FETCH_CAP requests, crawl-delay obeyed). The
                                             manifest keeps what it fetched: the capped recovery for a backlog
                                             (docs/ops/launch-runbook.md, "RPC backlog")
python -m collector rpc build                read the stored agendas -> data/localities/cmc-rpc/rpc.json
python -m collector rpc run                  fetch then build
python -m collector rpc daily [--offline]    the daily step on its own (run_step below; `collector run` calls it)

The daily step (run_step) is all or nothing on the committed files (listing.json, manifest.json, changes.jsonl,
rpc.json): they change only when the listing was read, the host refused nothing, every stored document is in the store
and the result drops nothing the committed rpc.json has. Otherwise they are left exactly as they were and the step
returns its own code: 2 the listing was not read or the host said no (the first 403/429 ends the host's requests for
the run; the next run is the next day's), 3 an agenda prints more case numbers than were read, 4 the result would
shrink the record or the store has gaps, 6 the store is still being filled (at most DAILY_FETCH_CAP requests go to
the RPC's hosts per run, robots.txt, the listing, redirects and retries included, so a cold store is filled over
several days, never in one burst), 1 an unexpected error. More newly listed documents than the requests left after
the listing is code 2 with none of them requested (a person looks first). While filling, only the manifest's gaps are
requested; new documents wait for a run that can finish, and new documents cut off by the cap are code 2.

Rules (docs/research/rpc-cmcss-sources.md, docs/platform-facts.md "Regional Planning Commission"):
- one GET of the listing page (https://www.cmcrpc.com/documents/agenda-minutes/) lists every document. Each document
  URL is taken from the page as printed (resolved against the page URL, nothing else); none is ever built;
- requests go through collector.fetch.PoliteFetcher: allowlist, robots.txt before every request, its crawl-delay
  (10 s), our honest User-Agent, a 403/429 stops the host for the run;
- a link on another host (Google Drive, YouTube) is kept in the listing with its URL and never requested;
- PDFs and DOCX go into the existing content-addressed Store with this locality's own manifest.

RPC-3, 2019-2021 (rpc.yml `civicclerk`; docs/platform-facts.md "RPC 2019-2021 on CivicClerk"): the city's CivicClerk
API lists the RPC's meetings before the listing page starts (2022-01-25). After the listing page, the step reads that
events listing (civicclerk.discover: robots.txt, OData paging on the API host only) and adds one listing row per
meeting (source "civicclerk", backfill_rows), and fetches their files under a cap of their own (BACKFILL_FETCH_CAP):
the files of a cold store come over a few runs, each run committing what it fetched, so the backfill never holds up
the RPC's own update. A CivicClerk listing that is not read (refused, down) leaves the committed backfill rows as they
are and asks for none of their files; the status line says so. Files are read by the same agenda and minutes readers.

Files (per locality, so no other body's manifest or facts are touched):
- data/localities/cmc-rpc/listing.json    every listed meeting as printed (committed; a build reads it offline)
- data/localities/cmc-rpc/manifest.json   one entry per fetched file (committed), bytes in the gitignored store
- data/localities/cmc-rpc/rpc.json        meetings, their documents (sources) and the agendas' case items
- build/rpc-report.json                   counts (motions not confirmed, by reason), problems, the fetch log
- build/rpc-motions-audit.jsonl           one line per motion: id, page, reasons and the sentences read (OCR text,
                                          internal, for QA sampling: never under build/site, never committed)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import yaml

from . import civicclerk, limits
from .fetch import (FetchFailed, HostBlocked, HostRefused, PoliteFetcher, ProxyRefused, RequestCapReached,
                    RobotsDisallowed)
from .store import Store, fetch_into_store

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "localities" / "cmc-rpc" / "rpc.yml"
STOP = (HostBlocked, HostRefused, ProxyRefused, RobotsDisallowed)   # the host said no (or policy): stop, never retry
# The daily step's own exit codes (run_step). `collector run` reports them as 5 (failed) or 6 (filling the store).
STEP_OK, STEP_ERROR, STEP_FETCH, STEP_GATE, STEP_REFUSED, STEP_FILLING = 0, 1, 2, 3, 4, 6
# Requests to the RPC's hosts (cfg.fetch_hosts and the listing's host, together) per daily run at most: robots.txt,
# the listing page, every document, redirect and retry. A normal day is robots.txt, the listing and 0 to 3 new
# documents. A cold store (168 documents) is filled over several runs: cmcrpc.com answered 429 after 51 documents in
# one run on 2026-11-10 (docs/status.md). Enforced by the fetcher (PoliteFetcher.limit_hosts): the 41st request is
# never made.
DAILY_FETCH_CAP = 40
# RPC-3: requests to the CivicClerk API host (rpc.yml `civicclerk`) per run at most, a cap group of its own: robots.txt,
# the events listing (3 pages for 2019-2021) and the 2019-2021 files. A cold store gets its files over two runs; after
# that a run asks for robots.txt and the listing only.
BACKFILL_FETCH_CAP = 40
BACKFILL = "civicclerk"                    # a listing row's `source` when it came from the CivicClerk backfill
# The capped by-hand recovery when the daily step cannot finish on its own (TooManyNew, a cut-off by the cap).
RECOVERY = "python -m collector rpc fetch --limit 30 (once a day until the backlog is in, then commit; " \
           "docs/ops/launch-runbook.md 'RPC backlog')"
# What the daily step puts back byte for byte unless it succeeds: what cmd_fetch may rewrite, and rpc.json, which
# only run_step writes, last (rpc-daily/restore-misses-rpc-json).
COMMITTED = ("listing", "manifest", "changes", "facts")
KEYS = ("locality", "body", "nav_label", "slug", "body_key", "listing_url", "record_url", "record_label", "facts",
        "fetch_hosts", "fetch_extensions", "kind_rules", "kind_labels", "case_types")
DATE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*(.*)$", re.S)
DOC_WORDS = (("agenda", re.compile(r"\bagenda\b", re.I)), ("minutes", re.compile(r"\bminutes?\b", re.I)),
             ("video", re.compile(r"\bvideo\b|youtube", re.I)))


class RpcConfigError(Exception):
    pass


class ListingError(Exception):
    """The listing page is not the page we know (moved or rebuilt). Fails loudly; nothing is guessed."""


@dataclass(frozen=True)
class RpcConfig:
    locality: str
    body: str
    nav_label: str
    slug: str
    body_key: str
    listing_url: str
    record_url: str
    record_label: str
    facts: str
    fetch_hosts: tuple
    fetch_extensions: tuple
    kind_rules: tuple          # ((kind, compiled), ...)
    kind_labels: dict
    case_types: dict           # case-number prefix -> case type label
    # rpc.yml hold_motions: on, no motion is published confirmed (sitegen/rpc.py), so the shrink guard does not
    # protect confirmed motions (a reader fix is expected to unconfirm some). Anything but false counts as on, as in
    # qa/site_checks.py
    hold_motions: bool = False
    # rpc.yml `civicclerk` (RPC-3): the meetings before the listing page starts, from the city's CivicClerk API, or None
    backfill: "Backfill | None" = None

    def kind_of(self, label: str) -> str:
        for kind, rx in self.kind_rules:
            if rx.search(label or ""):
                return kind
        return "regular"

    def fetchable(self, url: str) -> bool:
        u = urllib.parse.urlsplit(url)
        return (u.scheme == "https" and u.netloc.lower() in self.fetch_hosts
                and u.path.lower().endswith(self.fetch_extensions))


@dataclass(frozen=True)
class Backfill:
    """rpc.yml `civicclerk` (RPC-3): the CivicClerk events of one category dated before `to_date`."""
    cc: civicclerk.CivicClerkConfig
    to_date: str
    listing_url: str            # where these meetings are listed (the portal; never fetched)
    listing_label: str
    printed_names: re.Pattern   # an event name is shown as printed only when it matches in full
    skip: tuple                 # ((compiled event-name pattern, reason), ...)


BACKFILL_KEYS = ("to_date", "listing_url", "listing_label", "printed_names", "skip_events")


def parse_backfill(raw, locality: str, path) -> Backfill:
    """rpc.yml `civicclerk`: civicclerk.parse_config's keys and checks, plus BACKFILL_KEYS. Raises RpcConfigError."""
    if not isinstance(raw, dict):
        raise RpcConfigError(f"{path}: civicclerk must be a mapping")
    missing = [k for k in BACKFILL_KEYS if k not in raw]
    if missing:
        raise RpcConfigError(f"{path}: civicclerk: missing {', '.join(missing)}")
    if raw.get("also_list"):
        raise RpcConfigError(f"{path}: civicclerk: also_list is not used here")
    try:
        cc = civicclerk.parse_config({**{k: v for k, v in raw.items() if k not in BACKFILL_KEYS},
                                      "locality": locality})
    except civicclerk.CivicClerkConfigError as e:
        raise RpcConfigError(f"{path}: civicclerk: {e}") from None
    to = str(raw["to_date"])
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", to) or to <= cc.from_date:
        raise RpcConfigError(f"{path}: civicclerk: to_date must be YYYY-MM-DD after from_date")
    if f"startDateTime%20lt%20{to}T00:00:00Z" not in cc.events_url:
        raise RpcConfigError(f"{path}: civicclerk: events_url must ask only for events before to_date "
                             f"(startDateTime%20lt%20{to}T00:00:00Z)")
    if not str(raw["listing_url"]).startswith("https://") or not str(raw["listing_label"] or "").strip():
        raise RpcConfigError(f"{path}: civicclerk: listing_url must be https and listing_label set")
    skip = []
    try:
        names = re.compile(str(raw["printed_names"]), re.I)
        for s in raw["skip_events"] or []:
            if not (isinstance(s, dict) and set(s) == {"event_name", "reason"}
                    and all(isinstance(v, str) and v.strip() for v in s.values())):
                raise RpcConfigError(f"{path}: civicclerk: each skip_events entry is {{event_name, reason}}")
            skip.append((re.compile(s["event_name"], re.I), s["reason"].strip()))
    except re.error as e:
        raise RpcConfigError(f"{path}: civicclerk: {e}") from None
    return Backfill(cc=cc, to_date=to, listing_url=str(raw["listing_url"]), listing_label=str(raw["listing_label"]),
                    printed_names=names, skip=tuple(skip))


def load_config(path: Path = CONFIG) -> RpcConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    missing = [k for k in KEYS if k not in raw]
    if missing:
        raise RpcConfigError(f"{path}: missing {', '.join(missing)}")
    try:
        rules = tuple((str(k), re.compile(rx, re.I)) for k, rx in raw["kind_rules"])
    except (TypeError, ValueError, re.error) as e:
        raise RpcConfigError(f"{path}: kind_rules: {e}") from e
    unknown = sorted({k for k, _ in rules} - set(raw["kind_labels"]))
    if unknown:
        raise RpcConfigError(f"{path}: kind_rules name kinds with no kind_labels entry: {', '.join(unknown)}")
    if not str(raw["listing_url"]).startswith("https://"):
        raise RpcConfigError(f"{path}: listing_url must be https")
    return RpcConfig(**{**{k: raw[k] for k in KEYS}, "kind_rules": rules,
                        "fetch_hosts": tuple(h.lower() for h in raw["fetch_hosts"]),
                        "fetch_extensions": tuple(e.lower() for e in raw["fetch_extensions"]),
                        "case_types": {str(k).upper(): str(v) for k, v in (raw["case_types"] or {}).items()},
                        "hold_motions": raw.get("hold_motions", False) is not False,
                        "backfill": (parse_backfill(raw["civicclerk"], raw["locality"], path)
                                     if raw.get("civicclerk") is not None else None)})


# ------------------------------------------------------------------ listing page
class _Rows(HTMLParser):
    """Every table row of the page as cells of {text, links: [{href, text}]}."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict]] = []
        self._cell = None
        self._link = None
        self._in_row = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self.rows.append([])
            self._in_row = True
        elif tag in ("td", "th") and self._in_row:
            self._cell = {"text": "", "links": []}
            self.rows[-1].append(self._cell)
        elif tag == "a" and self._cell is not None and a.get("href"):
            self._link = {"href": a["href"].strip(), "text": ""}
            self._cell["links"].append(self._link)

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._cell = None
        elif tag == "a":
            self._link = None
        elif tag == "tr":
            self._in_row = False
            self._cell = None

    def handle_data(self, d):
        if self._cell is not None:
            self._cell["text"] += d
        if self._link is not None:
            self._link["text"] += d


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _label(rest: str) -> str:
    """The row's words after the date, as printed less the leading dash ("– CDRB" -> "CDRB")."""
    return _clean(re.sub(r"^[\s\-–—]+", "", rest))


def doc_kind(link_text: str, column: int) -> str:
    for kind, rx in DOC_WORDS:
        if rx.search(link_text or ""):
            return kind
    return {1: "agenda", 2: "minutes"}.get(column, "other")


def parse_listing(page: str, cfg: RpcConfig) -> tuple[list[dict], list[str]]:
    """(rows, problems). One row per listed meeting, newest first as printed:
    {date, label, kind, cancelled, docs: [{kind, url, host, fetch}], no_doc: [kinds printed with no link]}.
    A row whose first cell does not start with a date is not a meeting row (year headings); a row with a date that
    is not a real date is reported as a problem."""
    from datetime import date as _date
    p = _Rows()
    p.feed(page)
    rows, problems = [], []
    for cells in p.rows:
        if not cells:
            continue
        m = DATE.match(cells[0]["text"].strip())
        if not m:
            continue
        mo, d, y, rest = m.groups()
        try:
            iso = _date(int(y), int(mo), int(d)).isoformat()
        except ValueError:
            problems.append(f"listing row {cells[0]['text'].strip()!r}: not a real date")
            continue
        label = _label(rest)
        cancelled = bool(re.search(r"\bcancel+ed\b", label, re.I))
        label_clean = _clean(re.sub(r"\*?\s*cancel+ed\s*\*?", "", label, flags=re.I))
        docs, no_doc = [], []
        for col, c in enumerate(cells[1:], 1):
            if not c["links"]:
                t = _clean(c["text"])
                if t and t.upper() != "N/A":
                    no_doc.append(doc_kind(t, col))
                continue
            for link in c["links"]:
                url = urllib.parse.urljoin(cfg.listing_url, link["href"])
                host = urllib.parse.urlsplit(url).netloc.lower()
                docs.append({"kind": doc_kind(link["text"], col), "url": url, "host": host,
                             "fetch": cfg.fetchable(url), "link_text": _clean(link["text"])})
        rows.append({"date": iso, "label": label_clean, "printed": _clean(cells[0]["text"]),
                     "kind": cfg.kind_of(label_clean), "cancelled": cancelled, "docs": docs, "no_doc": no_doc})
    if not rows:
        raise ListingError(f"{cfg.listing_url}: no meeting rows found (the page changed?)")
    return rows, problems


def meeting_id(row: dict) -> str:
    return f"{row['date']}-{row['kind']}"


def assign_ids(rows: list[dict]) -> list[dict]:
    """Each row's meeting id: <date>-<kind>, with -2, -3 on a repeat of the same date and kind in listing order."""
    seen: dict[str, int] = {}
    out = []
    for r in rows:
        base = meeting_id(r)
        seen[base] = seen.get(base, 0) + 1
        out.append({**r, "id": base if seen[base] == 1 else f"{base}-{seen[base]}"})
    return out


# ------------------------------------------------------------------ RPC-3: 2019-2021 from CivicClerk
def backfill_rows(events: list[dict], cfg: RpcConfig) -> tuple[list[dict], list[dict]]:
    """civicclerk.discover rows (one per event, oldest first) -> (listing rows, problems), newest first like the
    listing page's. Each row has the listing row's shape plus source "civicclerk", its event ids and listing_url.
    - an event on or after to_date is left out (cmcrpc.com is the source from 2022); one matching skip_events (another
      body, a notice) is left out and reported;
    - a file's kind is read from its name first, as a listing link's from its text (2019-09-25: the minutes are filed
      as a separate event's "Agenda" file named "RPC Minutes 9-25-19"), else its published type; a name that says
      another kind than its type is reported;
    - two events of one date and kind whose files are of different kinds are one meeting (that same 2019-09-25 pair);
    - the event name is `printed` only when it matches printed_names (the portal's free text), else
      "<kind label>, <date>" and reported. Problems carry event ids and dates only, never an event or file name."""
    bf = cfg.backfill
    rows, problems = [], []
    for e in events:
        if e["date"] >= bf.to_date or e["date"] < bf.cc.from_date:
            continue
        title = " ".join((e.get("title") or "").split())
        why = next((reason for rx, reason in bf.skip if rx.fullmatch(title)), None)
        if why:
            problems.append({"event": e["event_id"], "date": e["date"], "problem": f"left out: {why}"})
            continue
        docs = []
        for typ, col in (("agenda", 1), ("minutes", 2)):
            if not e.get(f"{typ}_url"):
                continue
            kind = doc_kind(e.get(f"{typ}_name") or "", col)
            if kind not in ("agenda", "minutes"):
                kind = typ
            if kind != typ:
                problems.append({"event": e["event_id"], "date": e["date"],
                                 "problem": f"a file published as {typ} is named as {kind}: listed as {kind}"})
            docs.append({"kind": kind, "url": e[f"{typ}_url"], "host": bf.cc.api_host, "fetch": True,
                         "link_text": kind.capitalize()})
        # the kind rules read the event name and its agenda file's name (2020-04-06 is named as a regular agenda; its
        # file "Agenda Special Called RPC Meeting ..." and the agenda's own heading say special called)
        kind = cfg.kind_of(f"{title} {e.get('agenda_name') or ''}")
        printed = title
        if not bf.printed_names.fullmatch(title):
            printed = f"{cfg.kind_labels.get(kind, kind)}, {e['date']}"
            problems.append({"event": e["event_id"], "date": e["date"],
                             "problem": "event name not of a known shape: shown as kind and date"})
        rows.append({"date": e["date"], "label": "", "printed": printed, "kind": kind,
                     "cancelled": bool(re.search(r"\bcancel+ed\b", title, re.I)), "docs": docs, "no_doc": [],
                     "source": BACKFILL, "event_ids": [e["event_id"]], "listing_url": bf.listing_url})
    merged: list[dict] = []
    for r in rows:
        kinds = {d["kind"] for d in r["docs"]}
        prev = next((x for x in merged if (x["date"], x["kind"], x["cancelled"]) == (r["date"], r["kind"], r["cancelled"])
                     and not kinds & {d["kind"] for d in x["docs"]}), None)
        if prev is None:
            merged.append(r)
            continue
        prev["docs"] = sorted(prev["docs"] + r["docs"], key=lambda d: d["kind"] != "agenda")
        prev["printed"] = f"{prev['printed']}; {r['printed']}"
        prev["event_ids"] = prev["event_ids"] + r["event_ids"]
        problems.append({"event": r["event_ids"][0], "date": r["date"],
                         "problem": f"listed as two events ({', '.join(map(str, prev['event_ids']))}): one meeting"})
    merged.sort(key=lambda r: (r["date"], r["event_ids"][0]), reverse=True)
    return merged, problems


def merge_backfill(rows: list[dict], extra: list[dict]) -> tuple[list[dict], list[dict]]:
    """The listing page's rows, then the backfill's. A backfill meeting whose date and kind the listing page also
    lists is left out (the RPC's own page wins) and reported."""
    have = {(r["date"], r["kind"]) for r in rows}
    out, problems = list(rows), []
    for r in extra:
        if (r["date"], r["kind"]) in have:
            problems.append({"event": r["event_ids"][0], "date": r["date"],
                             "problem": "also on the RPC's listing page: the page's row is kept"})
            continue
        out.append(r)
    return out, problems


def discover_backfill(f, cfg: RpcConfig, log: dict, cache_dir: Path) -> list[dict]:
    """The CivicClerk events listing (civicclerk.discover: robots, paging on the API host only, each page cached
    under cache_dir), as listing rows. Raises on a refusal or a page that is not the API's (a partial listing is
    never used)."""
    sub: dict = {}
    events = civicclerk.discover(f, cfg.backfill.cc, cfg.kind_of, sub, cache_dir)
    rows, problems = backfill_rows(events, cfg)
    log.setdefault("backfill", {})["listing_pages"] = len(sub.get("listings", []))
    log["problems"] += [problem_line(p) for p in sub.get("listing_problems", []) + problems]
    return rows


def problem_line(p: dict) -> str:
    """A CivicClerk problem as the RPC report's one-line form: event id, date and the problem, nothing printed by
    the portal (an event or file name is its free text; the video path snippet is left out too)."""
    return f"civicclerk event {p.get('event')} ({p.get('date') or 'no date'}): {p.get('problem')}"


# ------------------------------------------------------------------ fetch
def write_json(p: Path, obj) -> bool:
    text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if p.exists() and p.read_text(encoding="utf-8") == text:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".part")     # a stopped write leaves a .part, never a short committed file
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return True


def paths(cfg: RpcConfig, root: Path = ROOT) -> dict:
    d = root / "data" / "localities" / cfg.locality
    return {"dir": d, "listing": d / "listing.json", "manifest": d / "manifest.json", "facts": root / cfg.facts,
            "changes": d / "changes.jsonl",
            "report": root / "build" / "rpc-report.json", "audit": root / "build" / "rpc-motions-audit.jsonl"}


def fetch_listing(f: PoliteFetcher, cfg: RpcConfig) -> str:
    status, body, headers = f.get(cfg.listing_url)
    if status != 200:
        raise ListingError(f"HTTP {status} for {cfg.listing_url}")
    return body.decode("utf-8", "replace")


def cmd_fetch(cfg: RpcConfig, store: Store, listing_path: Path, log: dict, fetcher=None,
              limit: int | None = None, max_requests: int | None = None, keeps_manifest: bool = False) -> list[dict]:
    """The listing page, then each listed document the store lacks. `max_requests`: at most that many requests go to
    the RPC's hosts this run, robots.txt and the listing included (a hard cap in the fetcher); the documents left
    over are counted in log['fetched']['over_cap'] and left for a later run. `limit`: at most that many documents
    are requested (the stored ones need no request and are not counted). `keeps_manifest` (the by-hand fetch,
    whose manifest is kept): new documents are fetched in listing order up to the cap, since what it fetches stays
    known; the daily step (False) restores the manifest on any shortfall, so it asks for new ones only when all
    fit. A failure where the host or policy said no carries `stop: True`."""
    f = fetcher or PoliteFetcher()
    hosts = {urllib.parse.urlsplit(cfg.listing_url).netloc.lower(), *cfg.fetch_hosts}
    bf_host = cfg.backfill.cc.api_host.lower() if cfg.backfill is not None else None
    if max_requests is not None:
        f.limit_hosts(hosts, max_requests)
        if bf_host:
            f.limit_hosts({bf_host}, BACKFILL_FETCH_CAP)      # its own cap: never takes the listing page's requests
    try:
        rows, problems = parse_listing(fetch_listing(f, cfg), cfg)
    except (ListingError, FetchFailed, RequestCapReached) + STOP as e:
        log["failures"].append({"stage": "listing", "error": f"{type(e).__name__}: {e}", "stop": isinstance(e, STOP)})
        log["fetch_log"] = f.log
        return []
    log["problems"] += problems
    bf_read = False
    if cfg.backfill is not None:
        # RPC-3: a CivicClerk listing that is not read (refused, down, not the API we know) does not stop the RPC's own
        # update: the committed backfill rows stand as they are, none of their files is requested this run, and the
        # reason is in the report (rpc.backfill.not_read). The API host is never asked again this run after a 403/429.
        try:
            bf_rows = discover_backfill(f, cfg, log, store.root / "civicclerk")
            bf_read = True
        except (civicclerk.EventsError, FetchFailed, RequestCapReached) + STOP as e:
            log.setdefault("backfill", {})["not_read"] = f"{type(e).__name__}: {e}"[:400]
            bf_rows = committed_backfill(listing_path)
        rows, more = merge_backfill(rows, bf_rows)
        log["problems"] += [problem_line(p) for p in more]
    rows = assign_ids(rows)
    write_json(listing_path, rows)
    jobs, seen = [], set()
    for r in rows:
        for d in r["docs"]:
            if d["fetch"] and d["url"] not in seen:          # one URL listed under two meetings is fetched once
                seen.add(d["url"])
                jobs.append((r, d))
            elif not d["fetch"]:
                log["link_only"] = log.get("link_only", 0) + 1
    bf_jobs = [(r, d) for r, d in jobs if r.get("source") == BACKFILL]
    jobs = [(r, d) for r, d in jobs if r.get("source") != BACKFILL]
    if limit is not None:
        needs = [d["url"] for _, d in jobs if not ((e := store.latest(d["url"])) and store.has_bytes(e["sha256"]))]
        keep = set(needs[:max(0, limit)])
        jobs = [(r, d) for r, d in jobs if d["url"] in keep or d["url"] not in needs]
    over_cap: set[str] = set()
    new_urls: set[str] = set()
    gap_urls: set[str] = set()
    if max_requests is not None:
        # Requests this run: the documents the manifest lists whose bytes the store lacks (their bytes stay in the
        # store, so a capped run still gets closer), and the newly listed ones only when everything fits in this run.
        # A run that stops short restores manifest.json, which forgets every new document it fetched, so asking for
        # new ones in a run that cannot finish would repeat the same requests every day (rpc-daily/filling-livelock).
        known = {d["url"]: store.latest(d["url"]) for _, d in jobs}
        gaps = [u for u, e in known.items() if e and not store.has_bytes(e["sha256"])]
        new = [u for u, e in known.items() if not e]
        budget = min((f.remaining(h) for h in hosts if f.remaining(h) is not None), default=max_requests)
        if keeps_manifest:
            over_cap = set((gaps + new)[budget:])
        elif len(new) > budget:
            # More new documents than one run may request (the site moved its files?). A run that cannot finish
            # keeps no manifest entry, so asking for part of them would ask again every day: ask for none.
            log["failures"].append({"stage": "fetch", "stop": True, "error": (
                f"TooManyNew: {len(new)} newly listed documents, more than the {budget} requests this run has left "
                f"(cap {max_requests}); none requested. It repeats every day until someone acts: after a look at "
                f"the listing, run {RECOVERY}")})
            store.save()
            log["fetch_log"] = f.log
            return rows
        elif len(gaps) + len(new) > budget:
            over_cap = set(gaps[budget:]) | set(new)       # gaps only; the new ones wait for a run that can finish
        new_urls = set(new)
        gap_urls = set(gaps)
    stopped = False
    for r, d in jobs:
        if stopped:
            log["fetched"]["not_tried"] = log["fetched"].get("not_tried", 0) + 1
            continue
        if d["url"] in over_cap:
            log["fetched"]["over_cap"] = log["fetched"].get("over_cap", 0) + 1
            continue
        expect = "docx" if d["url"].lower().endswith(".docx") else "pdf"
        try:
            _, status = fetch_into_store(f, store, d["url"], {"kind": d["kind"], "meeting_date": r["date"],
                                                               "label": f"{r['printed']} {d['kind']}"}, expect=expect)
            log["fetched"][status] = log["fetched"].get(status, 0) + 1
            if d["url"] in gap_urls and status not in ("cached", "cached-meta"):
                log["fetched"]["gaps_filled"] = log["fetched"].get("gaps_filled", 0) + 1   # kept across runs
            store.save()                      # saved as it goes, so a stopped run keeps what it fetched
        except RequestCapReached:             # retries or redirects used the cap up: no request was made
            log["fetched"]["over_cap"] = log["fetched"].get("over_cap", 0) + 1
            if d["url"] in new_urls and not keeps_manifest:   # a new document cut off by the cap: this run cannot
                log["fetched"]["new_cut_off"] = log["fetched"].get("new_cut_off", 0) + 1   # finish, nor may the next
        except STOP as e:
            log["failures"].append({"stage": "fetch", "url": d["url"], "error": f"{type(e).__name__}: {e}",
                                    "stop": True})
            stopped = isinstance(e, (HostBlocked, HostRefused))
        except FetchFailed as e:              # one file is logged and skipped
            log["failures"].append({"stage": "fetch", "url": d["url"], "error": f"{type(e).__name__}: {e}"})
    if bf_read and bf_jobs:
        fetch_backfill(f, cfg, store, bf_jobs, log, limit=limit, capped=max_requests is not None)
    store.save()
    log["fetch_log"] = f.log
    return rows


def committed_backfill(listing_path: Path) -> list[dict]:
    """The committed listing's backfill rows, as they are (the CivicClerk listing was not read this run)."""
    if not listing_path.is_file():
        return []
    return [r for r in json.loads(listing_path.read_text(encoding="utf-8")) if r.get("source") == BACKFILL]


def fetch_backfill(f, cfg: RpcConfig, store: Store, jobs: list, log: dict, limit: int | None = None,
                   capped: bool = True) -> None:
    """The backfill's files the store lacks, oldest meeting first, agenda before minutes: first the ones the manifest
    lists whose bytes the store lacks (gaps), then new ones, as many as the CivicClerk cap (BACKFILL_FETCH_CAP, after
    robots.txt and the listing) and `limit` allow. What does not fit waits for a later run: a gap is counted
    `over_cap` (the daily step then fills the store and changes nothing, as for the listing page's gaps); a new file
    is counted in backfill `later`, and its meeting is listed without that file's source until a run fetches it, so a
    cold store is filled over a few days and never stops the RPC's own update. A 403/429 or a robots refusal ends the
    backfill's requests for the run (backfill `stopped`); a failed file is logged and skipped."""
    bl = log.setdefault("backfill", {})
    host = cfg.backfill.cc.api_host
    by_url = {d["url"]: (r, d) for r, d in sorted(jobs, key=lambda j: (j[0]["date"], j[1]["kind"] != "agenda"))}
    known = {u: store.latest(u) for u in by_url}
    gaps = [u for u, e in known.items() if e and not store.has_bytes(e["sha256"])]
    new = [u for u, e in known.items() if not e]
    wanted = gaps + new
    if limit is not None:
        wanted = wanted[:max(0, limit)]
    if capped:
        left = f.remaining(host)
        wanted = wanted[:left] if left is not None else wanted
    stopped = None

    def wait(u: str) -> None:
        if u in gaps:
            log["fetched"]["over_cap"] = log["fetched"].get("over_cap", 0) + 1
        else:
            bl["later"] = bl.get("later", 0) + 1
    for u in gaps + new:
        if u not in wanted or stopped:
            wait(u)
            continue
        r, d = by_url[u]
        try:
            _, status = fetch_into_store(f, store, u, {"kind": d["kind"], "meeting_date": r["date"],
                                                       "label": f"{r['printed']} {d['kind']}"}, expect="pdf")
            bl.setdefault("fetched", {})[status] = bl.setdefault("fetched", {}).get(status, 0) + 1
            if u in gaps and status not in ("cached", "cached-meta"):
                log["fetched"]["gaps_filled"] = log["fetched"].get("gaps_filled", 0) + 1
            store.save()
        except RequestCapReached:             # retries or redirects used the cap up: no request was made
            wait(u)
        except STOP as e:
            stopped = f"{type(e).__name__}: {e}"[:400]
            bl["stopped"] = stopped
            wait(u)
        except FetchFailed as e:              # one file is logged and skipped
            log["failures"].append({"stage": "fetch", "url": u, "error": f"{type(e).__name__}: {e}"})


def new_log() -> dict:
    return {"failures": [], "fetched": {}, "problems": []}


# ------------------------------------------------------------------ the daily step
def _snapshot(p: dict) -> dict:
    return {k: (p[k].read_bytes() if p[k].is_file() else None) for k in COMMITTED}


def _restore(p: dict, snap: dict) -> None:
    """Put the committed files back byte for byte (a file the run created is removed)."""
    for k, body in snap.items():
        if body is None:
            p[k].unlink(missing_ok=True)
        elif not p[k].is_file() or p[k].read_bytes() != body:
            p[k].write_bytes(body)


def store_gaps(rows: list[dict], store: Store) -> list[str]:
    """Listed documents the manifest holds whose bytes are not in the store (a fresh checkout, an evicted cache)."""
    by_url = {e["url"]: e for e in store.current()}
    return sorted({d["url"] for r in rows for d in r["docs"]
                   if d["fetch"] and d["url"] in by_url and not store.has_bytes(by_url[d["url"]]["sha256"])})


def shrink_reason(old: dict, new: dict, hold_motions: bool = False, allow_shrink: bool = False) -> str | None:
    """Why `new` must not replace the committed record `old`, or None: a meeting gone, a meeting's agenda or minutes
    that had a source and now has none, or an agenda or minutes that was read and now is not (OCR not available).
    Compared per meeting and document kind, so a document the RPC posts again under a new link is not a loss.
    Also (limits invariant rule 3): a motion confirmed in the committed record that is not confirmed in `new`, unless
    hold_motions is on (nothing is published confirmed, and a reader fix is expected to unconfirm motions) or
    allow_shrink accepts it deliberately. A motion whose meeting's minutes source_id changed (the RPC posted
    different bytes) is a correction, not a loss (shrink guard G4 (i): motion ids `<meeting>-motion-<n>` do not
    depend on the bytes, so the source_id tells)."""
    now = {m["id"]: m for m in new.get("meetings", [])}
    gone = sorted(m["id"] for m in old.get("meetings", []) if m["id"] not in now)
    if gone:
        return (f"the result has {len(now)} meetings and would drop {len(gone)} of the {len(old['meetings'])} in the "
                f"committed record, e.g. {', '.join(gone[:3])}")
    for m in old.get("meetings", []):
        n = now[m["id"]]
        have = {d["kind"] for d in n["documents"] if d.get("source_id")}
        lost = sorted({d["kind"] for d in m["documents"] if d.get("source_id")} - have)
        if lost:
            return f"{m['id']}: the {' and '.join(lost)} had a source in the committed record and would have none"
        for k, what in (("agenda_read_by", "agenda"), ("minutes_read_by", "minutes")):
            if m.get(k) and not n.get(k):
                return f"{m['id']}: the {what} was read in the committed record and would not be"
    if not hold_motions and not allow_shrink:
        confirmed = {x["id"] for x in new.get("motions", []) if x.get("confirmed")}
        corrected = {c["meeting_id"]: set(c["new_source_ids"]) for c in minutes_corrections(old, new)}

        def correction(x: dict) -> bool:
            return x.get("meeting_id") in corrected and x.get("source_id") not in corrected[x["meeting_id"]]
        lost = sorted(x["id"] for x in old.get("motions", []) if x.get("confirmed") and x["id"] not in confirmed
                      and not correction(x))
        if lost:
            return (f"{len(lost)} motions confirmed in the committed record would not be confirmed, e.g. "
                    f"{', '.join(lost[:3])} (a limit trip or a reader change); pass --allow-shrink to accept it")
    return None


def minutes_corrections(old: dict, new: dict) -> list[dict]:
    """Shrink guard G4 (i), G1 (b): meetings whose minutes had a source in the committed record and have a different one
    in `new` (the RPC posted different bytes), with their confirmed motion counts:
    [{meeting_id, source_ids, new_source_ids, confirmed: [old, new]}]."""
    def minutes(m: dict) -> set:
        return {d["source_id"] for d in m.get("documents", []) if d.get("kind") == "minutes" and d.get("source_id")}
    now = {m["id"]: minutes(m) for m in new.get("meetings", [])}
    out = []
    for m in old.get("meetings", []):
        was, to = minutes(m), now.get(m["id"], set())
        if was and to and not was & to:
            def n(f):
                return sum(1 for x in f.get("motions", []) if x.get("meeting_id") == m["id"] and x.get("confirmed"))
            out.append({"meeting_id": m["id"], "source_ids": sorted(was), "new_source_ids": sorted(to),
                        "confirmed": [n(old), n(new)]})
    return out


def _daily(cfg: RpcConfig, p: dict, out: dict, offline: bool, fetcher, store: Store, build, max_requests,
           allow_shrink: bool = False) -> int:
    if offline:
        rows = json.loads(p["listing"].read_text(encoding="utf-8")) if p["listing"].is_file() else []
    else:
        flog = new_log()
        rows = cmd_fetch(cfg, store, p["listing"], flog, fetcher=fetcher, max_requests=max_requests)
        out["fetch"] = {k: v for k, v in flog.items() if k != "fetch_log"}
        out["fetch_log"] = flog.get("fetch_log", [])
        stops = [f for f in flog["failures"] if f.get("stop") or f["stage"] == "listing"]
        if stops:
            out["status"] = f"stopped, nothing changed: {stops[0]['error']}"[:400]
            return STEP_FETCH
        cut = flog["fetched"].get("new_cut_off", 0)
        if cut and not flog["fetched"].get("gaps_filled"):
            # rpc-daily/filling-livelock: the cap ran out on newly listed documents (retries or redirects took the
            # requests) and no stored gap was filled, so the next run would make the same requests and stop at the
            # same place: a failure for a person to look at, never "filling". When gaps were filled this run, the
            # next one has more room, so it is filling (rpc-daily/cut-off-self-heals).
            out["status"] = (f"stopped, nothing changed: {cut} newly listed documents not requested, the cap of "
                             f"{max_requests} requests ran out (retries or redirects). It repeats every day until "
                             f"someone acts: run {RECOVERY}")
            return STEP_FETCH
        left = flog["fetched"].get("over_cap", 0)
        if left:
            out["status"] = (f"filling the store, nothing changed: {left} documents left for later runs "
                             f"(at most {max_requests} requests per run)")
            return STEP_FILLING
    gaps = store_gaps(rows, store)
    if gaps or not rows:
        out["status"] = (f"nothing changed: {len(gaps)} stored documents are not in the store, e.g. {gaps[0]}"
                         if gaps else "nothing changed: no listing")
        out["kept"] = True
        return STEP_OK if offline else STEP_REFUSED    # offline (a fresh checkout): the committed record stands
    if build is None:
        from .rpc_agenda import build
    facts, summary = build(cfg, rows, store, audit_path=p["audit"])
    out["build"] = summary
    short = summary.get("case_shortfalls") or []
    if short:
        out["status"] = f"nothing changed: {len(short)} agendas with cases not read: {', '.join(short)}"
        return STEP_GATE
    old = json.loads(p["facts"].read_text(encoding="utf-8")) if p["facts"].is_file() else None
    if old:
        out["corrections"] = minutes_corrections(old, facts)     # reported in the run summary (G1 (b), G4 (i))
    why = shrink_reason(old, facts, hold_motions=cfg.hold_motions, allow_shrink=allow_shrink) if old else None
    if why:
        out["status"] = f"nothing changed: {why}"
        return STEP_REFUSED
    out["changed"] = write_json(p["facts"], facts)
    out["status"] = (f"{summary.get('meetings')} meetings, {summary.get('sources')} sources, {summary.get('cases')} "
                     f"cases; {p['facts'].name} {'rewritten' if out['changed'] else 'unchanged'}")
    bf = (out.get("fetch") or {}).get("backfill") or {}
    notes = [f"{bf['later']} files left for later runs" if bf.get("later") else None,
             f"listing not read ({bf['not_read']})" if bf.get("not_read") else None,
             f"stopped ({bf['stopped']})" if bf.get("stopped") else None]
    if any(notes):
        out["status"] = (out["status"] + "; CivicClerk 2019-2021: " + ", ".join(n for n in notes if n))[:600]
    return STEP_OK


def run_step(log: dict, offline: bool, fetcher=None, cfg: RpcConfig | None = None, root: Path = ROOT,
             store: Store | None = None, build=None, max_requests: int | None = DAILY_FETCH_CAP,
             allow_shrink: bool = False) -> int:
    """The daily step (collector run): read the listing, fetch what is new (unless offline), rebuild rpc.json.
    All or nothing: on any code but 0 (and on an offline run whose store has gaps) listing.json, manifest.json,
    changes.jsonl and rpc.json are left exactly as they were. Fetched bytes stay in the gitignored store, so a later
    run does not ask again for a document the manifest already lists. Never raises; the summary goes to log['rpc']
    (with `exit`) and build/rpc-report.json."""
    out: dict = {"offline": offline, "status": None}
    since = limits.mark()                      # this step's own trips only (limits invariant rule 3)
    p = snap = None
    try:
        cfg = cfg or load_config()
        p = paths(cfg, root)
        snap = _snapshot(p)
        code = _daily(cfg, p, out, offline, fetcher, store or Store(manifest_path=p["manifest"]), build, max_requests,
                      allow_shrink)
    except Exception as e:      # this step never takes the county run down; nothing of its own is left half written
        out["status"] = f"error, nothing changed: {type(e).__name__}: {e}"[:400]
        code = STEP_ERROR
    if snap is not None and (code != STEP_OK or out.get("kept")):
        _restore(p, snap)
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
        out["build"]["problems"] = len(problems)          # the full list is in build/rpc-report.json
    log["rpc"] = out
    print(f"collector: rpc: exit {code}: {out['status']}", flush=True)
    for c in out.get("corrections") or []:
        print(f"collector: rpc: correction: {c['meeting_id']} minutes "
              f"{'+'.join(x.removeprefix('src-')[:8] for x in c['source_ids'])} -> "
              f"{'+'.join(x.removeprefix('src-')[:8] for x in c['new_source_ids'])}, "
              f"confirmed {c['confirmed'][0]} -> {c['confirmed'][1]}", flush=True)
    print(limits.summary("collector: rpc", since), flush=True)
    return code


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m collector rpc")
    ap.add_argument("command", choices=("fetch", "build", "run", "daily"))
    ap.add_argument("--limit", type=int, default=None,
                    help="request at most N documents the store lacks (never more than the 40-request cap allows)")
    ap.add_argument("--offline", action="store_true", help="daily: no fetching, build from the store")
    ap.add_argument("--allow-shrink", action="store_true",
                    help="daily: accept a result in which a committed confirmed motion is no longer confirmed")
    a = ap.parse_args(argv)
    if a.command == "daily":
        return run_step({}, a.offline, allow_shrink=a.allow_shrink)
    cfg = load_config()
    p = paths(cfg)
    store = Store(manifest_path=p["manifest"])
    log = new_log()
    since = limits.mark()
    if a.command in ("fetch", "run"):
        # by hand too: the same cap and crawl-delay as the daily step; what it fetches stays in the manifest
        cmd_fetch(cfg, store, p["listing"], log, limit=a.limit, max_requests=DAILY_FETCH_CAP, keeps_manifest=True)
        left = (log["fetched"].get("over_cap", 0) + log["fetched"].get("not_tried", 0)
                + (log.get("backfill") or {}).get("later", 0))
        if left:
            print(f"collector rpc: {left} documents still to fetch; run this again tomorrow (cap "
                  f"{DAILY_FETCH_CAP} requests per run), then commit data/localities/{cfg.locality}/", flush=True)
    report = {"fetch": {k: v for k, v in log.items() if k != "fetch_log"}}
    if a.command in ("build", "run"):
        from .rpc_agenda import build
        rows = json.loads(p["listing"].read_text(encoding="utf-8")) if p["listing"].exists() else []
        facts, summary = build(cfg, rows, store, audit_path=p["audit"])
        write_json(p["facts"], facts)
        report["build"] = summary
    report["limits"] = limits.tripped(since)
    write_json(p["report"], {**report, "fetch_log": log.get("fetch_log", [])})
    print(json.dumps(report, indent=1, default=str)[:4000])
    print(limits.summary("collector rpc", since), flush=True)
    if any(f["stage"] == "listing" or f.get("stop") for f in log["failures"]):   # not read, or the host said no
        return 2
    short = report.get("build", {}).get("case_shortfalls") or []
    if short:   # the completeness check: an agenda prints more "CASE NUMBER:" than the cases read
        print(f"FAIL  rpc case completeness: {len(short)} agendas with cases not read: {', '.join(short)}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
