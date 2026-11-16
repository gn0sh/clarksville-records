"""City of Clarksville committees (Finance, Audit) from the city's CivicClerk portal, each its own body (milestone C1).

python -m collector committees fetch [--limit N] [--ids ID,ID]   the events listing of every committee, then the
                                         agenda and minutes PDFs the store lacks (at most N; --ids: only those meetings)
python -m collector committees build     read the stored minutes -> data/localities/<loc>/committees/committees.json
python -m collector committees run       fetch then build

Shaped like the Regional Planning Commission (collector/rpc.py): its own config, listing, manifest and output, so the
City Council path (collector/city_run.py, city_build.py, civicclerk.yml, ADR 0006 guards) is untouched. The CivicClerk
parts are collector/civicclerk.py's, used as they are: one CivicClerkConfig per committee (its category_name), the
same URL templates and checks (parse_config), the same OData paging (discover: nextLink on the API host only, each page
cached as fetched), the same row shape (parse_events: date as printed, newest agenda and minutes file, the video rule:
a bare storage path is never guessed into a URL).

Rules (docs/research/committee-sources-2026-11-11.md, docs/adr/0003-civicclerk-collection.md):
- requests go through collector.fetch.PoliteFetcher: allowlist, robots.txt before every request, 10 s per host, our
  honest User-Agent, GET only, a 403/429 stops the host for the run (never retried, never worked around);
- a listing that fails or would drop an event the committed listing has is not written (the committed one stands);
- files go into the content-addressed Store with this body's own manifest;
- a listed file is kept as listed, even when it prints another date (the 2026-05-26 Finance event carries the
  2025-05-27 minutes): the mismatch is reported, never "fixed".

Files (data/localities/<loc>/committees/, so no other body's manifest or facts are touched):
- listing.json      every listed committee meeting as printed (committed; a build reads it offline)
- manifest.json     one entry per fetched file (committed), bytes in the gitignored store
- committees.json   meetings, documents (sources), attendance and motions as printed (collector/committee_minutes.py)
- build/committees-report.json   counts, problems (date mismatches, motions not confirmed, by reason), the fetch log
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path

import yaml

from . import civicclerk, limits
from .civicclerk import CivicClerkConfig, CivicClerkConfigError
from .fetch import (ALLOWED_HOSTS, FetchFailed, HostBlocked, HostRefused, PoliteFetcher, ProxyRefused,
                    RequestCapReached, RobotsDisallowed, host_matches)
from .rpc import write_json
from .store import Store, fetch_into_store, store_dir

ROOT = Path(__file__).resolve().parent.parent
STOP = (HostBlocked, HostRefused, ProxyRefused, RobotsDisallowed)   # the host said no (or policy): stop, never retry
# The keys every committee shares, passed to civicclerk.parse_config with each committee's category_name
SHARED = ("locality", "api_host", "from_date", "events_url", "file_url", "agenda_types", "minutes_types", "video_hosts")
SLUG = re.compile(r"^[a-z][a-z0-9-]*$")
CANCELLED = re.compile(r"\bcancel+ed\b", re.I)
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), 1)}
TITLE_NUMERIC = re.compile(r"(?<![\d/-])(\d{1,2})[-/](\d{1,2})[-/](\d{2}|\d{4})(?![\d/-])")
TITLE_WORDS = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
# A document of these kinds is fetched; the CivicClerk "Agenda Packet" and other types are not (civicclerk.yml types)
DOC_KINDS = ("agenda", "minutes")


class CommitteesConfigError(Exception):
    pass


@dataclass(frozen=True)
class Committee:
    category_name: str
    slug: str
    label: str
    cc: CivicClerkConfig        # civicclerk.yml's shape for this one category: URLs, file types, video rule

    def kind_of(self, title: str) -> str:   # civicclerk.parse_events names each row's kind: the committee's slug
        return self.slug

    def name_words(self) -> list[str]:      # "Finance Committee" -> ["finance"]: an event name should print one
        return [w for w in self.label.lower().split() if w not in ("committee", "board", "the", "of", "and", "&")]


@dataclass(frozen=True)
class CommitteesConfig:
    locality: str
    api_host: str
    from_date: str
    committees: tuple
    hold_motions: bool = True   # anything but false is on (as rpc.yml): the site shows no motion confirmed

    def by_slug(self, slug: str) -> Committee:
        return next(c for c in self.committees if c.slug == slug)


def config_path(locality: str = "clarksville-tn") -> Path:
    return ROOT / "config" / "localities" / locality / "committees.yml"


def parse_config(raw) -> CommitteesConfig:
    """committees.yml -> CommitteesConfig. Each committee's CivicClerk settings are checked by civicclerk.parse_config
    (https on api_host, the URL templates' fields, from_date), so the committees obey the council's rules exactly."""
    if not isinstance(raw, dict):
        raise CommitteesConfigError("committees.yml: not a mapping")
    missing = [k for k in SHARED + ("committees",) if k not in raw]
    if missing:
        raise CommitteesConfigError(f"committees.yml: missing {', '.join(missing)}")
    if not isinstance(raw["api_host"], str) or not host_matches(raw["api_host"], ALLOWED_HOSTS):
        raise CommitteesConfigError("committees.yml: api_host must be a host on "
                                    "collector/fetch.py ALLOWED_HOSTS")
    items = raw["committees"]
    if not isinstance(items, list) or not items:
        raise CommitteesConfigError("committees.yml: committees must be a non-empty list")
    out, slugs, cats = [], set(), set()
    for i, c in enumerate(items):
        where = f"committees.yml: committees[{i}]"
        if not (isinstance(c, dict) and set(c) == {"category_name", "slug", "label"}
                and all(isinstance(v, str) and v.strip() for v in c.values())):
            raise CommitteesConfigError(f"{where} must be {{category_name, slug, label}}, each a non-empty string")
        if not SLUG.match(c["slug"]):
            raise CommitteesConfigError(f"{where}: slug must be lowercase letters, digits and hyphens")
        if c["slug"] in slugs or c["category_name"] in cats:
            raise CommitteesConfigError(f"{where}: slug or category_name listed twice")
        slugs.add(c["slug"])
        cats.add(c["category_name"])
        try:
            cc = civicclerk.parse_config({**{k: raw[k] for k in SHARED}, "category_name": c["category_name"]})
        except CivicClerkConfigError as e:
            raise CommitteesConfigError(str(e).replace("civicclerk.yml", "committees.yml")) from None
        out.append(Committee(category_name=c["category_name"], slug=c["slug"], label=c["label"].strip(), cc=cc))
    return CommitteesConfig(locality=out[0].cc.locality, api_host=out[0].cc.api_host, from_date=out[0].cc.from_date,
                            committees=tuple(out), hold_motions=raw.get("hold_motions", True) is not False)


def load_config(path: Path | None = None) -> CommitteesConfig:
    p = Path(path) if path else config_path()
    return parse_config(yaml.safe_load(p.read_text(encoding="utf-8")))


# ------------------------------------------------------------------ listing
def title_dates(title: str) -> list[str]:
    """Every date the event's name prints ("Finance Committee Agenda 4-4-19", "Audit Committee Agenda - October 28,
    2020"), as YYYY-MM-DD; a date that is not a real date is left out."""
    found = []
    for m in TITLE_NUMERIC.finditer(title or ""):
        mo, d, y = (int(x) for x in m.groups())
        found.append((y + 2000 if y < 100 else y, mo, d))
    for m in TITLE_WORDS.finditer(title or ""):
        found.append((int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))))
    out = []
    for y, mo, d in found:
        try:
            out.append(_date(y, mo, d).isoformat())
        except ValueError:
            continue
    return out


def annotate(rows: list[dict], committee: Committee) -> tuple[list[dict], list[dict]]:
    """civicclerk rows of one committee -> (rows, problems). Each row gains the committee's slug and label, and
    `cancelled` when its name says so. A name that prints a date other than the event's is kept as listed and
    reported (title_date). A name that does not print the committee's name ("Public Safety Committee FY25 Budget
    Review" under Finance) is kept as listed, marked `other_name` and reported. Nothing is ever "fixed"."""
    out, problems = [], []
    for r in rows:
        r = {**r, "committee": committee.slug, "body": committee.label, "cancelled": bool(CANCELLED.search(r["title"]))}
        printed = title_dates(r["title"])
        if printed and r["date"] not in printed:
            # the event id and dates only: the report is printed to the public Actions log, and an event name is the
            # portal's free text (committees-privacy/log-snippet)
            problems.append({"event": r["event_id"], "date": r["date"], "problem": "event name prints another date",
                             "printed": printed[0]})
            r["title_date"] = printed[0]
        if not any(w in r["title"].lower() for w in committee.name_words()):
            # e.g. "Public Safety Committee FY25 Budget Review" filed under Finance Committee: kept as listed
            problems.append({"event": r["event_id"], "date": r["date"], "problem": "event name does not name the "
                             "committee"})
            r["other_name"] = True
        out.append(r)
    return out, problems


def parse_page(page: dict, committee: Committee) -> tuple[list[dict], list[dict]]:
    """One OData events page of one committee -> (rows, problems), as discover() reads each page."""
    rows, problems = civicclerk.parse_events(page, committee.cc, committee.kind_of)
    rows, more = annotate(rows, committee)
    return rows, problems + more


def assign_ids(rows: list[dict]) -> list[dict]:
    """Each row's meeting id: <date>-<committee>, with -2, -3 on a repeat of the same date and committee, in listing
    order (oldest first, then event id). Rows are sorted so the ids do not depend on the API's page order."""
    rows = sorted(rows, key=lambda r: (r["date"], r["committee"], r["event_id"]))
    seen: dict[str, int] = {}
    out = []
    for r in rows:
        base = f"{r['date']}-{r['committee']}"
        seen[base] = seen.get(base, 0) + 1
        out.append({**r, "id": base if seen[base] == 1 else f"{base}-{seen[base]}"})
    return out


def discover(fetcher, cfg: CommitteesConfig, log: dict, cache_dir: Path) -> list[dict]:
    """Every committee's events listing (civicclerk.discover, politely), annotated and with meeting ids. A refusal or
    a page that is not the OData page we know propagates: a partial listing is never returned."""
    rows = []
    for c in cfg.committees:
        got = civicclerk.discover(fetcher, c.cc, c.kind_of, log, cache_dir)
        got, problems = annotate(got, c)
        log.setdefault("listing_problems", []).extend(problems)
        rows += [gate_listing_row(r) for r in got]
    return assign_ids(rows)


LISTING_WORDS = ("title", "agenda_name", "minutes_name")


def gate_listing_row(r: dict, allow=None) -> dict:
    """The portal's printed title and document names, as committed in listing.json (and copied into the manifest's
    labels): each passes the committee words rule or is replaced, before anything is written
    (docs/architecture/committee-words-invariant.md): a title by "<committee label> meeting", a document name by its
    kind ("Agenda", "Minutes"). `cancelled`, `title_date` and `other_name` were read from the printed title first."""
    from .committee_words import publishable
    out = dict(r)
    for k in LISTING_WORDS:
        if out.get(k) and not publishable(out[k], allow):
            out[k] = {"title": f"{out['body']} meeting", "agenda_name": "Agenda", "minutes_name": "Minutes"}[k]
            out.setdefault("words_replaced", []).append(k)
    return out


def listing_shrinks(rows: list[dict], previous: list[dict] | None, today: str) -> list[int]:
    """Event ids the committed listing has that `rows` lacks (an empty or cut-short answer, a removed meeting): such a
    listing is not written, the committed one stands and a person looks. The one exception, as for the council
    (ADR 0006): a row with no minutes dated today or later (a cancelled or moved future event) may go. Sorted."""
    now = {r["event_id"] for r in rows}
    return sorted(r["event_id"] for r in previous or []
                  if r["event_id"] not in now and (r.get("minutes_url") or r["date"] < today))


# ------------------------------------------------------------------ fetch
def paths(cfg: CommitteesConfig, root: Path = ROOT) -> dict:
    d = root / "data" / "localities" / cfg.locality / "committees"
    return {"dir": d, "listing": d / "listing.json", "manifest": d / "manifest.json", "facts": d / "committees.json",
            "report": root / "build" / "committees-report.json"}


def new_log() -> dict:
    return {"failures": [], "fetched": {}, "problems": []}


def _failure(stage: str, e: Exception, **extra) -> dict:
    return {"stage": stage, "error": f"{type(e).__name__}: {e}"[:400], "stop": isinstance(e, STOP), **extra}


def cmd_fetch(cfg: CommitteesConfig, store: Store, listing_path: Path, log: dict, fetcher=None,
              limit: int | None = None, ids: set | None = None, today: str | None = None,
              cache_dir: Path | None = None, kinds: tuple = DOC_KINDS) -> list[dict]:
    """Every committee's listing (written only when read in full and dropping no committed event), then each listed
    agenda and minutes PDF the store lacks, oldest meeting first, minutes before agenda. `ids`: only those meetings'
    files (a by-hand fetch of a few files). `limit`: at most that many files are requested (stored ones need no
    request and are not counted). `kinds`: only these document kinds. A 403/429 or a robots refusal stops every
    request for the rest of the run."""
    from datetime import datetime, timezone
    f = fetcher or PoliteFetcher()
    today = today or datetime.now(timezone.utc).date().isoformat()
    previous = json.loads(listing_path.read_text(encoding="utf-8")) if listing_path.exists() else None
    try:
        rows = discover(f, cfg, log, cache_dir or store_dir() / "civicclerk")
    except (civicclerk.EventsError, FetchFailed, RequestCapReached) + STOP as e:
        log["failures"].append(_failure("listing", e))
        log["fetch_log"] = f.log
        return []
    log["problems"] += log.pop("listing_problems", [])
    lost = listing_shrinks(rows, previous, today)
    if lost:
        log["failures"].append({"stage": "listing", "stop": False, "error": (
            f"the listing lacks {len(lost)} events the committed listing has (e.g. {lost[:5]}): not written, the "
            "committed listing stands; a person looks (removed at the source, or a short answer)")})
        log["fetch_log"] = f.log
        return previous or []
    write_json(listing_path, rows)
    unknown = sorted(set(ids or ()) - {r["id"] for r in rows})
    if unknown:
        log["problems"].append({"problem": "--ids names no listed meeting", "ids": unknown})
    jobs = [(r, kind, r[f"{kind}_url"]) for r in rows for kind in ("minutes", "agenda")
            if kind in kinds and r.get(f"{kind}_url") and (ids is None or r["id"] in ids)]
    if limit is not None:
        needs = [u for _, _, u in jobs if not ((e := store.latest(u)) and store.has_bytes(e["sha256"]))]
        keep = set(needs[:max(0, limit)])
        over = [u for u in needs if u not in keep]
        if over:
            log["fetched"]["over_limit"] = len(over)
        jobs = [j for j in jobs if j[2] in keep or j[2] not in needs]
    stopped = False
    for r, kind, url in jobs:
        if stopped:
            log["fetched"]["not_tried"] = log["fetched"].get("not_tried", 0) + 1
            continue
        try:
            _, status = fetch_into_store(f, store, url, {"kind": kind, "meeting_date": r["date"],
                                                          "label": f"{r['body']}: {r['title']} ({kind})"})
            log["fetched"][status] = log["fetched"].get(status, 0) + 1
            store.save()                      # saved as it goes, so a stopped run keeps what it fetched
        except RequestCapReached as e:
            log["failures"].append(_failure("fetch", e, url=url))
            stopped = True
        except STOP as e:
            log["failures"].append(_failure("fetch", e, url=url))
            stopped = isinstance(e, (HostBlocked, HostRefused, ProxyRefused))
        except FetchFailed as e:              # one file is logged and skipped
            log["failures"].append(_failure("fetch", e, url=url))
    store.save()
    log["fetch_log"] = f.log
    return rows


# ------------------------------------------------------------------ command line
def main(argv: list[str]) -> int:
    """Exit 0 ok; 2 a listing not read or kept back, or the host or policy said no (403/429, robots: never retried);
    4 the build wrote nothing (store gaps, or the result would shrink the committed record); 1 a file could not be
    fetched (logged, the others still fetched)."""
    ap = argparse.ArgumentParser(prog="python -m collector committees")
    ap.add_argument("command", choices=("fetch", "build", "run"))
    ap.add_argument("--limit", type=int, default=None, help="request at most N files the store lacks")
    ap.add_argument("--ids", default=None, help="fetch only these meetings' files (meeting ids, comma separated)")
    ap.add_argument("--kinds", default=",".join(DOC_KINDS), help="fetch only these kinds (agenda, minutes)")
    ap.add_argument("--allow-shrink", action="store_true", help="build: let a smaller result replace committees.json")
    a = ap.parse_args(argv)
    cfg = load_config()
    p = paths(cfg)
    store = Store(manifest_path=p["manifest"])
    log = new_log()
    since = limits.mark()
    if a.command in ("fetch", "run"):
        ids = {x.strip() for x in a.ids.split(",") if x.strip()} if a.ids else None
        kinds = tuple(k for k in DOC_KINDS if k in a.kinds.split(","))
        cmd_fetch(cfg, store, p["listing"], log, limit=a.limit, ids=ids, kinds=kinds)
    report = {"fetch": {k: v for k, v in log.items() if k != "fetch_log"}}
    if a.command in ("build", "run"):
        report["build"] = cmd_build(cfg, p, store, allow_shrink=a.allow_shrink, hold=cfg.hold_motions)
    report["limits"] = limits.tripped(since)
    write_json(p["report"], {**report, "fetch_log": log.get("fetch_log", [])})
    print(json.dumps(report, indent=1, default=str)[:4000])
    print(limits.summary("collector committees", since), flush=True)
    if any(f["stage"] == "listing" or f.get("stop") for f in log["failures"]):
        return 2
    if "build" in report and not report["build"].get("written"):
        print(f"collector committees: {report['build']['status']}", file=sys.stderr)
        return 4
    return 1 if log["failures"] else 0


# ------------------------------------------------------------------ build
def source_of(row: dict, kind: str, store: Store) -> dict | None:
    """The listed document of this kind with its stored copy: {kind, url, name, source_id, sha256, fetched_at}.
    source_id is None while the file is not fetched (the listing still names it)."""
    url = row.get(f"{kind}_url")
    if not url:
        return None
    e = store.latest(url)
    stored = bool(e and store.has_bytes(e["sha256"]))
    return {"kind": kind, "url": url, "name": row.get(f"{kind}_name"),
            "source_id": f"src-{e['sha256'][:12]}" if stored else None, "sha256": e["sha256"] if stored else None,
            "fetched_at": (e.get("first_fetched_at") or "")[:10] if stored else None}


def store_gaps(rows: list[dict], store: Store) -> list[str]:
    """Listed files the manifest holds whose bytes are not in the store (a fresh checkout): a build then would read
    less than the committed record, so it writes nothing."""
    by_url = {e["url"]: e for e in store.current()}
    return sorted({r[f"{k}_url"] for r in rows for k in DOC_KINDS
                   if r.get(f"{k}_url") in by_url and not store.has_bytes(by_url[r[f"{k}_url"]]["sha256"])})


def read_pages(path: Path) -> tuple[list[str] | None, str | None]:
    """The PDF's text pages, or (None, why not). No OCR in C1: a scan is reported, never guessed."""
    from .extract import extract_pages, image_only_pages
    try:
        pages = extract_pages(path)
    except Exception as e:                    # a broken or hung file is reported, the build goes on
        return None, f"text not extracted ({type(e).__name__})"
    blank = image_only_pages(pages)
    if not pages or len(blank) == len(pages):
        return None, "no text layer (a scan): not read"
    return pages, None


# Reasons are stored as codes, never as the minutes' words (docs/architecture/committee-words-invariant.md): the reader's
# reasons quote what it could not read, which may be a name. The first pattern that matches gives the code.
REASON_CODES = (
    (r"^words not read", "words-not-read"), (r"^outcome not read", "outcome-not-read"),
    (r"^seconder not read", "seconder-not-read"), (r"^mover \S", "mover-not-one-member"),
    (r"^seconder \S", "seconder-not-one-member"), (r"^(?:aye|nay) \S", "vote-name-not-one-member"),
    (r"^vote list", "vote-list-not-read"), (r"^a member is named twice", "vote-name-twice"),
    (r"^mover and seconder are the same", "mover-is-seconder"),
    (r"^the minutes print no date", "minutes-date-not-printed"), (r"^the minutes print ", "minutes-date-differs"),
    (r"^members present not read", "attendance-not-read"), (r"^attendance: ", "attendance-name-not-read"),
)
WORD_FIELDS = ("section", "subject_printed", "motion_printed")


def reason_code(reason: str) -> str:
    return next((code for pat, code in REASON_CODES if re.search(pat, reason)), "other")


def _words_ok(text: str | None, known, allow) -> bool:
    """The allow-list gate (committee_words.publishable), with the masking as belt and braces: a name the masking
    finds, or a claim private_doubt still doubts, withholds the text whatever the allow-list says."""
    from .committee_minutes import mask_private, private_doubt
    from .committee_words import publishable
    if not text:
        return True
    _, hit = mask_private(text, known)
    return not hit and not private_doubt(text) and publishable(text, allow)


def publish(mv: dict, count: dict, problems: list, known, allow) -> None:
    """Keep only what may be published of one motion, in place, before anything is written
    (docs/architecture/committee-words-invariant.md): words that pass the allow-list, names on the roster, reason
    codes. A withheld words field is None and listed in `words_withheld`, with `words_note`; a printed name not on
    the roster is None and the motion is not confirmed."""
    from .committee_minutes import WITHHOLD
    from .committee_words import WORDS_NOTE, roster_name
    withheld = []
    every = any(WITHHOLD.search(mv.get(k) or "") for k in WORD_FIELDS)    # a write-off or travel-waiver item (F5)
    for k in WORD_FIELDS:
        if mv.get(k) and (every or not _words_ok(mv[k], known, allow)):
            mv[k] = None
            withheld.append(k)
    v = mv.get("vote")
    if v and v.get("outcome_printed") and (every or not _words_ok(v["outcome_printed"], known, allow)):
        v["outcome_printed"] = None
        withheld.append("outcome_printed")
    codes = [reason_code(r) for r in mv.get("reasons") or []]
    names_out = 0
    for k in ("mover_printed", "seconder_printed"):
        if mv.get(k) and not roster_name(mv[k], allow):
            mv[k] = None
            mv[k.replace("_printed", "")] = None
            names_out += 1
    for k in ("ayes_printed", "nays_printed"):
        if v and v.get(k) and not all(roster_name(n, allow) for n in v[k]):
            v[k] = None
            names_out += 1
    if names_out:
        codes.append("name-not-on-roster")
        count["names_withheld"] += names_out
    mv["reasons"] = list(dict.fromkeys(codes))
    mv["confirmed"] = not mv["reasons"]
    if withheld:
        mv["words_withheld"] = withheld
        mv["words_note"] = WORDS_NOTE
        for k in withheld:
            count["words_withheld"][k] += 1
        problems.append({"motion_id": mv["id"], "problem": f"words not shown ({', '.join(withheld)}): not on the "
                         "allow-list (config/localities/clarksville-tn/committee-words.yml)"})


def publish_meeting(m: dict, label: str, count: dict, allow) -> None:
    """A meeting's text fields: the portal's title and document names pass the word rule or are replaced by the
    committee's label and the document's kind; attendance names must all be on the roster (otherwise no attendance
    is kept); an attendance note that fails the word rule is dropped."""
    from .committee_words import publishable, roster_name
    if not publishable(m["title"], allow):
        m["title"] = f"{label} meeting"
        count["titles_replaced"] += 1
    for d in m["documents"]:
        if not publishable(d.get("name"), allow):
            d["name"] = DOC_KINDS.get(d["kind"], "Document")
    att = m.get("attendance")
    if not att:
        return
    people = (att.get("present") or []) + (att.get("absent") or [])
    if not all(roster_name(p["name"], allow) for p in people):
        m["attendance"] = None
        m["attendance_withheld"] = "name-not-on-roster"
        count["attendance_withheld"] += 1
        return
    for p in people:
        if p.get("note") and not publishable(p["note"], allow):
            del p["note"]


DOC_KINDS = {"agenda": "Agenda", "minutes": "Minutes"}


def build(cfg: CommitteesConfig, rows: list[dict], store: Store, hold: bool = True) -> tuple[dict, dict]:
    """listing rows + stored files -> (committees.json, summary). Each meeting as listed, its documents, and when its
    minutes are stored and have text: the minutes' printed date, the members present and absent as printed, and
    each motion as read (collector/committee_minutes.py), with `confirmed` and its `reasons`. `hold` (committees.yml
    hold_motions) is written into the record so the site shows no motion confirmed while it is on."""
    from .committee_minutes import private_names, read_minutes
    from .committee_words import load_allow
    allow = load_allow()
    by_sha: dict[str, list[str]] = {}
    meetings, motions, problems = [], [], []
    count = {"meetings": 0, "minutes_listed": 0, "minutes_stored": 0, "minutes_read": 0, "motions": 0,
             "confirmed": 0, "date_mismatches": [], "shared_minutes": [], "not_read": [], "names_withheld": 0,
             "words_withheld": {k: 0 for k in (*WORD_FIELDS, "outcome_printed")}, "attendance_withheld": 0,
             "titles_replaced": 0}
    for r in rows:
        docs = [d for d in (source_of(r, "agenda", store), source_of(r, "minutes", store)) if d]
        m = {"id": r["id"], "committee": r["committee"], "body": r["body"], "date": r["date"], "title": r["title"],
             "event_id": r["event_id"], "cancelled": r["cancelled"], "video_url": r.get("video_url"),
             "documents": docs, "minutes_read": False, "minutes_printed_date": None, "attendance": None}
        for k in ("title_date", "other_name"):
            if r.get(k):
                m[k] = r[k]
        count["meetings"] += 1
        mins = next((d for d in docs if d["kind"] == "minutes"), None)
        count["minutes_listed"] += bool(mins)
        if mins and mins["source_id"]:
            count["minutes_stored"] += 1
            by_sha.setdefault(mins["sha256"], []).append(r["id"])
            pages, why = read_pages(store.path_for(mins["sha256"]))
            if pages is None:
                count["not_read"].append({"meeting_id": r["id"], "why": why})
            else:
                mins["pages"] = len(pages)    # the site links each motion's page (#page=N), checked against this
                rd = read_minutes(pages, r["date"])
                count["minutes_read"] += 1
                m.update(minutes_read=True, minutes_printed_date=rd["printed_date"])
                if rd["date_mismatch"]:
                    # the file is kept on this meeting as listed, but what it records is another meeting's: no
                    # attendance and no motion is attached here (they would be shown under the wrong date)
                    count["date_mismatches"].append({"meeting_id": r["id"], "printed": rd["printed_date"],
                                                     "motions_not_attached": len(rd["motions"])})
                    problems.append({"meeting_id": r["id"], "problem": f"minutes print {rd['printed_date']}: kept "
                                     "as listed; their attendance and motions are not attached to this meeting"})
                    meetings.append(m)
                    continue
                m["attendance"] = {**rd["attendance"], "source_id": mins["source_id"], "confirmed": not rd["problems"]}
                for x in rd["motions"]:     # masked below, once every minutes file's party names are known
                    motions.append({"id": f"{r['id']}-motion-{x['n']}", "meeting_id": r["id"],
                                    "committee": r["committee"], "source_id": mins["source_id"],
                                    **{k: v for k, v in x.items() if k != "n"}})
        meetings.append(m)
    # every party name any minutes print in a claim or a case caption (the same party comes back at later meetings:
    # "Jeff Doe, et al" in April, "the Does" in May), masked wherever any motion prints it, plurals too
    known = private_names(t for x in motions for t in (x.get("section"), x.get("subject_printed"),
                                                       x.get("motion_printed"), *x["reasons"]))
    for mv in motions:
        publish(mv, count, problems, known, allow)
    labels = {c.slug: c.label for c in cfg.committees}
    for m in meetings:
        publish_meeting(m, labels.get(m["committee"], "Committee"), count, allow)
    for sha, ids in sorted(by_sha.items()):
        if len(ids) > 1:            # one file listed on two meetings: kept on both, reported
            count["shared_minutes"].append({"source_id": f"src-{sha[:12]}", "meetings": ids})
            problems.append({"meetings": ids, "problem": "the same minutes file is listed on these meetings"})
    count["motions"] = len(motions)
    count["confirmed"] = sum(x["confirmed"] for x in motions)
    held: dict[str, int] = {}
    for x in motions:
        for code in x["reasons"]:
            held[code] = held.get(code, 0) + 1
    count["motions_with_all_words"] = sum(1 for x in motions if not x.get("words_withheld"))
    count["motions_with_motion_words"] = sum(1 for x in motions if x.get("motion_printed"))
    count["held_by_reason"] = dict(sorted(held.items(), key=lambda kv: (-kv[1], kv[0])))
    facts = {"locality": cfg.locality, "hold_motions": hold,
             "bodies": [{"slug": c.slug, "label": c.label, "category_name": c.category_name} for c in cfg.committees],
             "meetings": meetings, "motions": motions}
    return facts, {**count, "problems": problems}


def shrink_reason(old: dict | None, new: dict) -> str | None:
    """Why `new` must not replace the committed committees.json: a meeting gone, minutes that were read and are not,
    or fewer confirmed motions for a meeting whose minutes file did not change."""
    if not old:
        return None
    now = {m["id"]: m for m in new["meetings"]}
    gone = [m["id"] for m in old["meetings"] if m["id"] not in now]
    if gone:
        return f"{len(gone)} meetings in the committed record would be dropped, e.g. {', '.join(gone[:3])}"
    unread = [m["id"] for m in old["meetings"] if m.get("minutes_read") and not now[m["id"]].get("minutes_read")]
    if unread:
        return f"{len(unread)} meetings' minutes were read in the committed record and would not be: {unread[:3]}"

    def confirmed(f: dict) -> dict:
        out: dict = {}
        for x in f["motions"]:
            if x["confirmed"]:
                out[(x["meeting_id"], x["source_id"])] = out.get((x["meeting_id"], x["source_id"]), 0) + 1
        return out
    was, is_ = confirmed(old), confirmed(new)
    still = {(m["id"], d.get("source_id")) for m in new["meetings"] for d in m.get("documents", [])
             if d.get("kind") == "minutes"}        # a meeting whose minutes file changed is a correction, not a loss
    lost = sorted(k[0] for k, n in was.items() if k in still and is_.get(k, 0) < n)
    if lost:
        return f"confirmed motions would be lost for {', '.join(lost[:3])} (a reader change?)"
    return None


def cmd_build(cfg: CommitteesConfig, p: dict, store: Store, allow_shrink: bool = False, hold: bool = True) -> dict:
    """Build committees.json from the committed listing and the store. Writes nothing when the store lacks a file the
    manifest lists, or (unless allow_shrink) when the result would shrink the committed record."""
    rows = json.loads(p["listing"].read_text(encoding="utf-8")) if p["listing"].exists() else []
    if not rows:
        return {"status": "nothing written: no listing (run fetch first)", "written": False}
    gaps = store_gaps(rows, store)
    if gaps:
        return {"status": f"nothing written: {len(gaps)} files the manifest lists are not in the store, e.g. "
                          f"{gaps[0]}", "written": False}
    facts, summary = build(cfg, rows, store, hold=hold)
    old = json.loads(p["facts"].read_text(encoding="utf-8")) if p["facts"].exists() else None
    why = None if allow_shrink else shrink_reason(old, facts)
    if why:
        return {**summary, "status": f"nothing written: {why}", "written": False}
    changed = write_json(p["facts"], facts)
    return {**summary, "written": True, "status": f"{summary['meetings']} meetings, {summary['minutes_read']} minutes "
            f"read, {summary['motions']} motions ({summary['confirmed']} read as confirmed); {p['facts'].name} "
            f"{'rewritten' if changed else 'unchanged'}"}


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
