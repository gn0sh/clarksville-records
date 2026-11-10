"""Regional Planning Commission (RPC) from www.cmcrpc.com: list its meetings, fetch their agendas and minutes, read the
agendas' case items (milestone RPC-1).

python -m collector rpc fetch [--limit N]    the listing page, then every listed PDF/DOCX on the RPC's own host
python -m collector rpc build                read the stored agendas -> data/localities/cmc-rpc/rpc.json
python -m collector rpc run                  fetch then build

Rules (docs/research/rpc-cmcss-sources.md, docs/platform-facts.md "Regional Planning Commission"):
- one GET of the listing page (https://www.cmcrpc.com/documents/agenda-minutes/) lists every document. Each document
  URL is taken from the page as printed (resolved against the page URL, nothing else); none is ever built;
- requests go through collector.fetch.PoliteFetcher: allowlist, robots.txt before every request, its crawl-delay
  (10 s), our honest User-Agent, a 403/429 stops the host for the run;
- a link on another host (Google Drive, YouTube) is kept in the listing with its URL and never requested;
- PDFs and DOCX go into the existing content-addressed Store with this locality's own manifest.

Files (per locality, so no other body's manifest or facts are touched):
- data/localities/cmc-rpc/listing.json    every listed meeting as printed (committed; a build reads it offline)
- data/localities/cmc-rpc/manifest.json   one entry per fetched file (committed), bytes in the gitignored store
- data/localities/cmc-rpc/rpc.json        meetings, their documents (sources) and the agendas' case items
- build/rpc-report.json                   counts, problems, the fetch log
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

from .fetch import FetchFailed, HostBlocked, HostRefused, PoliteFetcher, ProxyRefused, RobotsDisallowed
from .store import Store, fetch_into_store

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "localities" / "cmc-rpc" / "rpc.yml"
STOP = (HostBlocked, HostRefused, ProxyRefused, RobotsDisallowed)   # the host said no (or policy): stop, never retry
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

    def kind_of(self, label: str) -> str:
        for kind, rx in self.kind_rules:
            if rx.search(label or ""):
                return kind
        return "regular"

    def fetchable(self, url: str) -> bool:
        u = urllib.parse.urlsplit(url)
        return (u.scheme == "https" and u.netloc.lower() in self.fetch_hosts
                and u.path.lower().endswith(self.fetch_extensions))


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
                        "case_types": {str(k).upper(): str(v) for k, v in (raw["case_types"] or {}).items()}})


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


# ------------------------------------------------------------------ fetch
def write_json(p: Path, obj) -> bool:
    text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if p.exists() and p.read_text(encoding="utf-8") == text:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return True


def paths(cfg: RpcConfig, root: Path = ROOT) -> dict:
    d = root / "data" / "localities" / cfg.locality
    return {"dir": d, "listing": d / "listing.json", "manifest": d / "manifest.json", "facts": root / cfg.facts,
            "report": root / "build" / "rpc-report.json"}


def fetch_listing(f: PoliteFetcher, cfg: RpcConfig) -> str:
    status, body, headers = f.get(cfg.listing_url)
    if status != 200:
        raise ListingError(f"HTTP {status} for {cfg.listing_url}")
    return body.decode("utf-8", "replace")


def cmd_fetch(cfg: RpcConfig, store: Store, listing_path: Path, log: dict, fetcher=None,
              limit: int | None = None) -> list[dict]:
    f = fetcher or PoliteFetcher()
    try:
        rows, problems = parse_listing(fetch_listing(f, cfg), cfg)
    except (ListingError, FetchFailed) + STOP as e:
        log["failures"].append({"stage": "listing", "error": f"{type(e).__name__}: {e}"})
        log["fetch_log"] = f.log
        return []
    log["problems"] += problems
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
    if limit is not None:
        jobs = jobs[:limit]
    stopped = False
    for r, d in jobs:
        if stopped:
            log["fetched"]["not_tried"] = log["fetched"].get("not_tried", 0) + 1
            continue
        expect = "docx" if d["url"].lower().endswith(".docx") else "pdf"
        try:
            _, status = fetch_into_store(f, store, d["url"], {"kind": d["kind"], "meeting_date": r["date"],
                                                               "label": f"{r['printed']} {d['kind']}"}, expect=expect)
            log["fetched"][status] = log["fetched"].get(status, 0) + 1
            store.save()                      # saved as it goes, so a stopped run keeps what it fetched
        except STOP as e:
            log["failures"].append({"stage": "fetch", "url": d["url"], "error": f"{type(e).__name__}: {e}"})
            stopped = isinstance(e, (HostBlocked, HostRefused))
        except FetchFailed as e:              # one file is logged and skipped
            log["failures"].append({"stage": "fetch", "url": d["url"], "error": f"{type(e).__name__}: {e}"})
    store.save()
    log["fetch_log"] = f.log
    return rows


def new_log() -> dict:
    return {"failures": [], "fetched": {}, "problems": []}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m collector rpc")
    ap.add_argument("command", choices=("fetch", "build", "run"))
    ap.add_argument("--limit", type=int, default=None, help="fetch at most N files (testing)")
    a = ap.parse_args(argv)
    cfg = load_config()
    p = paths(cfg)
    store = Store(manifest_path=p["manifest"])
    log = new_log()
    if a.command in ("fetch", "run"):
        cmd_fetch(cfg, store, p["listing"], log, limit=a.limit)
    report = {"fetch": {k: v for k, v in log.items() if k != "fetch_log"}}
    if a.command in ("build", "run"):
        from .rpc_agenda import build
        rows = json.loads(p["listing"].read_text(encoding="utf-8")) if p["listing"].exists() else []
        facts, summary = build(cfg, rows, store)
        write_json(p["facts"], facts)
        report["build"] = summary
    write_json(p["report"], {**report, "fetch_log": log.get("fetch_log", [])})
    print(json.dumps(report, indent=1, default=str)[:4000])
    return 2 if any(f["stage"] == "listing" for f in log["failures"]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
