"""City of Clarksville City Council from the Agenda Center (M4, slice 1): fetch and build.

python -m collector city fetch [--agendas] [--limit N] [--source S]   listings + minutes PDFs (+ agenda PDFs)
python -m collector city build                            read the stored minutes -> data/localities/<loc>/facts.json
python -m collector city run [--agendas]                  fetch then build

Two listings (M4 slice 3): the Agenda Center (2016 to January 2024, one GET per year) and CivicClerk (2024 on, the
API's events pages; collector/civicclerk.py, ADR 0003). The build joins them with civicclerk.merge_sources: one
meeting per date and kind, each naming its listing source.

Files (per locality, so the county's data/manifest.json and data/facts.json are never touched):
- data/localities/<loc>/listing.json   every listed meeting as printed (committed; a build reads it offline)
- data/localities/<loc>/civicclerk-listing.json   the same for the CivicClerk events (committed)
- data/localities/<loc>/manifest.json  one entry per fetched file (committed), bytes in the gitignored data/store
- data/localities/<loc>/facts.json     the facts (schema/facts.schema.json shape, city meeting kinds)
- data/localities/<loc>/wards.json     each member's ward as printed in each meeting's attendance, with its source
- build/city-report.json               counts, problems, the fetch log
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import civicclerk
from .agenda_center import AgendaCenterConfig, ListingError, discover, load_config
from .fetch import FetchFailed, HostBlocked, HostRefused, PoliteFetcher, ProxyRefused, RobotsDisallowed
from .store import Store, fetch_into_store, store_dir

ROOT = Path(__file__).resolve().parent.parent
STOP = (HostBlocked, HostRefused, ProxyRefused, RobotsDisallowed)   # the host said no (or policy): stop, never retry


def paths(cfg: AgendaCenterConfig, root: Path = ROOT) -> dict:
    d = root / "data" / "localities" / cfg.locality
    return {"dir": d, "listing": d / "listing.json", "manifest": d / "manifest.json", "facts": d / "facts.json", "wards": d / "wards.json",
            "cc_listing": d / "civicclerk-listing.json", "report": root / "build" / "city-report.json"}


def write_json(p: Path, obj) -> bool:
    text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if p.exists() and p.read_text(encoding="utf-8") == text:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return True


def cmd_fetch(cfg: AgendaCenterConfig, store: Store, listing_path: Path, log: dict, fetcher=None,
              agendas: bool = False, limit: int | None = None) -> list[dict]:
    f = fetcher or PoliteFetcher()
    previous = json.loads(listing_path.read_text(encoding="utf-8")) if listing_path.exists() else None
    try:
        rows = discover(f, cfg, log, previous)
    except (ListingError, FetchFailed) + STOP as e:
        log["failures"].append({"stage": "listing", "error": f"{type(e).__name__}: {e}"})
        log["fetch_log"] = f.log
        return []
    write_json(listing_path, rows)
    return fetch_files(f, store, rows, log, agendas, limit)


def cmd_fetch_civicclerk(cc: civicclerk.CivicClerkConfig, kind_of, store: Store, listing_path: Path, log: dict,
                         fetcher=None, agendas: bool = False, limit: int | None = None,
                         cache_dir: Path | None = None) -> list[dict]:
    """The CivicClerk listing (every events page, cached) then its minutes (and agendas). A listing that fails part
    way is not written, so the last full civicclerk-listing.json stays."""
    f = fetcher or PoliteFetcher()
    try:
        rows = civicclerk.discover(f, cc, kind_of, log, cache_dir or store_dir() / "civicclerk")
    except (civicclerk.EventsError, FetchFailed) + STOP as e:
        log["failures"].append({"stage": "listing", "source": civicclerk.SOURCE, "error": f"{type(e).__name__}: {e}"})
        log["fetch_log"] = f.log
        return []
    write_json(listing_path, rows)
    return fetch_files(f, store, rows, log, agendas, limit)


def fetch_files(f, store: Store, rows: list[dict], log: dict, agendas: bool, limit: int | None) -> list[dict]:
    jobs = [(r, "minutes", r["minutes_url"]) for r in rows if r["minutes_url"]]
    if agendas:
        jobs += [(r, "agenda", r["agenda_url"]) for r in rows if r["agenda_url"]]
    if limit is not None:
        jobs = jobs[:limit]
    stopped = False
    for r, kind, url in jobs:
        if stopped:
            log["fetched"]["not_tried"] = log["fetched"].get("not_tried", 0) + 1
            continue
        try:
            _, status = fetch_into_store(f, store, url, {"kind": kind, "meeting_date": r["date"], "label": r["title"]})
            log["fetched"][status] = log["fetched"].get(status, 0) + 1
            store.save()                      # saved as it goes, so a stopped run keeps what it fetched
        except STOP as e:
            log["failures"].append({"stage": "fetch", "url": url, "error": f"{type(e).__name__}: {e}"})
            stopped = isinstance(e, (HostBlocked, HostRefused))
        except FetchFailed as e:              # one file (e.g. a .docx behind a PDF link) is logged and skipped
            log["failures"].append({"stage": "fetch", "url": url, "error": f"{type(e).__name__}: {e}"})
    store.save()
    log["fetch_log"] = f.log
    return rows


def listing_rows(p: dict, cfg: AgendaCenterConfig) -> tuple[list[dict], list[dict]]:
    """Both committed listings joined (civicclerk.merge_sources). The meeting kind is re-read from each title with
    the current config, as the build does, so the de-duplication and the meeting ids agree."""
    ac = json.loads(p["listing"].read_text(encoding="utf-8")) if p["listing"].exists() else []
    cc = json.loads(p["cc_listing"].read_text(encoding="utf-8")) if p["cc_listing"].exists() else []
    ac = [{**r, "kind": cfg.kind_of(r["title"])} for r in ac]
    cc = [{**r, "kind": cfg.kind_of(r["title"])} for r in cc]
    return civicclerk.merge_sources(ac, cc)


def new_log() -> dict:
    return {"failures": [], "fetched": {}}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m collector city")
    ap.add_argument("command", choices=("fetch", "build", "run"))
    ap.add_argument("--agendas", action="store_true", help="also fetch agenda PDFs (minutes are always fetched)")
    ap.add_argument("--limit", type=int, default=None, help="fetch at most N files (testing)")
    ap.add_argument("--locality", default="clarksville-tn")
    ap.add_argument("--source", choices=("all", "agenda-center", "civicclerk"), default="all",
                    help="which listing to fetch (the build always reads both)")
    a = ap.parse_args(argv)
    cfg = load_config(Path(ROOT / "config" / "localities" / a.locality / "agenda-center.yml"))
    cc_path = civicclerk.config_path(a.locality)
    cc = civicclerk.load_config(cc_path) if cc_path.exists() else None
    p = paths(cfg)
    store = Store(manifest_path=p["manifest"])
    log = new_log()
    if a.command in ("fetch", "run"):
        fetcher = PoliteFetcher()
        if a.source in ("all", "agenda-center"):
            cmd_fetch(cfg, store, p["listing"], log, fetcher=fetcher, agendas=a.agendas, limit=a.limit)
        if cc and a.source in ("all", "civicclerk"):
            cmd_fetch_civicclerk(cc, cfg.kind_of, store, p["cc_listing"], log, fetcher=fetcher, agendas=a.agendas,
                                 limit=a.limit)
    report = {"fetch": {k: v for k, v in log.items() if k != "fetch_log"}}
    if a.command in ("build", "run"):
        from .city_build import build
        rows, dups = listing_rows(p, cfg)
        facts, summary = build(cfg, rows, store)
        summary["duplicates"] = dups
        write_json(p["wards"], facts.pop("_wards"))
        write_json(p["facts"], facts)
        report["build"] = summary
    write_json(p["report"], {**report, "fetch_log": log.get("fetch_log", [])})
    print(json.dumps({k: v for k, v in report.items()}, indent=1, default=str)[:4000])
    return 2 if log["failures"] and any(f["stage"] == "listing" for f in log["failures"]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
