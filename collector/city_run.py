"""City of Clarksville City Council from the Agenda Center (M4, slice 1): fetch and build.

python -m collector city fetch [--agendas] [--limit N] [--source S]   listings + minutes PDFs (+ agenda PDFs)
python -m collector city build                            read the stored minutes -> data/localities/<loc>/facts.json
python -m collector city run [--agendas]                  fetch then build
  --allow-shrink   let a listing that drops committed rows, or a build that drops committed meetings, through

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

Exit codes (the workflow's Collect step fails the run, and so opens the issue, on any non-zero code; spec AC4.4):
0 ok (a single file that is skipped, e.g. a .docx behind a PDF link, is logged and stays 0); 2 a listing could not be
read, or the shrink guard held a result back; 3 the G4 skew gate flagged an official (build/city-report.json
build.gates; the AC-P1 verified rate is reported there but sets no code); 5 a host or policy refused us at any stage
(HostBlocked 403/429, HostRefused, ProxyRefused, RobotsDisallowed: alerting/city-fetch-failures-exit-0). A refusal is
never retried and never worked around: the code only reports it. 7 (KEPT, a warning; precedence 5 > 2 > 3 > 7 > 0):
the shrink guard kept committed city rows or meetings; the workflow publishes everything and opens the city
meetings-kept issue (docs/adr/0006-daily-refresh-data-guards.md, I1 and I2).

Shrink guard (ADR 0006; the county's rule 3, docs/architecture/pipeline-limits-invariant.md, at the city's units): a
listing read without an error but missing rows the committed listing has (an empty page, a 200 with no heading and no
rows, an events page of `{"value": []}`) keeps the committed rows (`kept_listing_rows`, exit 7), except a row with no
minutes dated on or after the run's UTC day (a cancelled or rescheduled event): it is dropped and listed under
`dropped_unminuted`, no code. A build that would drop a committed meeting keeps the committed facts (exit 7).
The guard's findings are under `guard` in build/city-report.json; it is never a `failures` row.
--allow-shrink (a deliberate removal at the source, or a parser change that renames meeting ids) lets it through,
recorded under `allowed_shrink`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import civicclerk, limits
from .agenda_center import AgendaCenterConfig, ListingError, discover, load_config
from .fetch import FetchFailed, HostBlocked, HostRefused, PoliteFetcher, ProxyRefused, RobotsDisallowed
from .store import Store, fetch_into_store, store_dir

ROOT = Path(__file__).resolve().parent.parent
STOP = (HostBlocked, HostRefused, ProxyRefused, RobotsDisallowed)   # the host said no (or policy): stop, never retry
LISTING_FAILED = 2
GATE_FAILED = 3        # G4 flagged an official (spec G4: release blocked), as the county's gate failure code
BLOCKED = 5            # its own code, so the alert says "refused", not "failed" (4 is the county run's offline refusal)
KEPT = 7               # a warning: the shrink guard kept committed rows or meetings (the county's KEPT, ADR 0006)


def failure(stage: str, e: Exception, **extra) -> dict:
    """One log['failures'] row. `refused` marks a STOP error: exit_code turns any of them into BLOCKED."""
    row = {"stage": stage, **extra, "error": f"{type(e).__name__}: {e}"}
    if isinstance(e, STOP):
        row["refused"] = True
    return row


def exit_code(log: dict) -> int:
    """BLOCKED when any host or policy refused us (at the listing or at a file), else LISTING_FAILED when a listing
    could not be read, else 0. A lone FetchFailed on one file stays 0: it is logged and that file is skipped. The
    gate (3) and the guard's KEPT (7) are applied after the build, in that order (main)."""
    if any(f.get("refused") for f in log["failures"]):
        return BLOCKED
    return LISTING_FAILED if any(f["stage"] == "listing" for f in log["failures"]) else 0


def kept_anything(log: dict) -> bool:
    """Whether the shrink guard kept committed rows or meetings, or a correction lowered a verified count (KEPT)."""
    g = log.get("guard") or {}
    return bool(g.get("kept_listing_rows") or g.get("kept_meetings") or g.get("lowered"))


def _row_key(r: dict, key: str):
    return r.get(key) or (r.get("date"), r.get("title"), r.get("minutes_url"))


def _row_order(r: dict, key: str) -> tuple:
    v = _row_key(r, key)
    return (r.get("date") or "", (0, v, "") if isinstance(v, int) else (1, 0, str(v)))


def today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def guard_listing(rows: list[dict], previous: list[dict] | None, key: str, name: str, log: dict,
                  allow_shrink: bool = False, today: str | None = None) -> list[dict]:
    """The listing to write (ADR 0006 fix 1): `rows` as read, plus every committed row (`previous`) the read lacks,
    kept as committed and listed under guard.kept_listing_rows (exit 7), except a row with no minutes dated on or after
    `today` (UTC): a cancelled or moved future event, dropped and listed under guard.dropped_unminuted (no code). A row
    is one meeting by `key` (agenda_id, event_id). Gains are never guarded; --allow-shrink lets the smaller listing win
    and records it."""
    have = {_row_key(r, key) for r in rows}
    gone = [r for r in previous or [] if _row_key(r, key) not in have]
    if not gone:
        return rows
    g = log.setdefault("guard", {})
    day = today or today_utc()
    future = [r for r in gone if not r.get("minutes_url") and (r.get("date") or "") >= day]
    if future:
        g.setdefault("dropped_unminuted", []).append({"listing": name, "dropped": [_print(r, key) for r in future]})
    dropped = [r for r in gone if r not in future]
    if not dropped:
        return rows
    ids = [_print(r, key) for r in dropped]
    if allow_shrink:
        g.setdefault("allowed_shrink", []).append({"listing": name, "dropped": ids})
        print(f"collector city: ALLOWED (--allow-shrink) {name}: {len(dropped)} committed rows dropped", flush=True)
        return rows
    g.setdefault("kept_listing_rows", []).append({"listing": name, "kept": ids})
    print(f"collector city: KEPT {name}: the listing as read has {len(rows)} rows and lacks {len(dropped)} of the "
          f"{len(previous)} committed rows, e.g. {', '.join(i['key'] for i in ids[:5])}; kept as committed",
          file=sys.stderr, flush=True)
    return sorted(rows + dropped, key=lambda r: _row_order(r, key))


def _print(r: dict, key: str) -> dict:
    """A guarded row as the kept entries print it: its key and the meeting id the build gives it (date-kind)."""
    return {"key": str(_row_key(r, key)), "meeting": f"{r.get('date')}-{r.get('kind')}", "date": r.get("date"),
            "title": r.get("title"), "minutes_url": r.get("minutes_url")}


def facts_shrink(new: dict, old: dict | None) -> list[str]:
    """Meeting ids the committed city facts have and the new build lacks (sorted)."""
    if not old:
        return []
    return sorted({m["id"] for m in old.get("meetings", [])} - {m["id"] for m in new.get("meetings", [])})


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
              agendas: bool = False, limit: int | None = None, allow_shrink: bool = False,
              today: str | None = None) -> list[dict]:
    f = fetcher or PoliteFetcher()
    previous = json.loads(listing_path.read_text(encoding="utf-8")) if listing_path.exists() else None
    try:
        rows = discover(f, cfg, log, previous)
    except (ListingError, FetchFailed) + STOP as e:
        log["failures"].append(failure("listing", e))
        log["fetch_log"] = f.log
        return []
    write_json(listing_path, guard_listing(rows, previous, "agenda_id", listing_path.name, log, allow_shrink, today))
    return fetch_files(f, store, rows, log, agendas, limit)


def cmd_fetch_civicclerk(cc: civicclerk.CivicClerkConfig, kind_of, store: Store, listing_path: Path, log: dict,
                         fetcher=None, agendas: bool = False, limit: int | None = None,
                         cache_dir: Path | None = None, allow_shrink: bool = False,
                         today: str | None = None) -> list[dict]:
    """The CivicClerk listing (every events page, cached) then its minutes (and agendas). A listing that fails part
    way is not written, so the last full civicclerk-listing.json stays."""
    f = fetcher or PoliteFetcher()
    try:
        rows = civicclerk.discover(f, cc, kind_of, log, cache_dir or store_dir() / "civicclerk")
    except (civicclerk.EventsError, FetchFailed) + STOP as e:
        log["failures"].append(failure("listing", e, source=civicclerk.SOURCE))
        log["fetch_log"] = f.log
        return []
    previous = json.loads(listing_path.read_text(encoding="utf-8")) if listing_path.exists() else None
    write_json(listing_path, guard_listing(rows, previous, "event_id", listing_path.name, log, allow_shrink, today))
    return fetch_files(f, store, rows, log, agendas, limit)


def fetch_files(f, store: Store, rows: list[dict], log: dict, agendas: bool, limit: int | None) -> list[dict]:
    jobs = [(r, "minutes", r["minutes_url"]) for r in rows if r["minutes_url"]]
    # a D1 row (page1_required) is kept by the build only when page 1 of its agenda or minutes prints the body's
    # name, so its agenda is fetched too
    jobs += [(r, "agenda", r["agenda_url"]) for r in rows if r["agenda_url"] and (agendas or r.get("page1_required"))]
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
            log["failures"].append(failure("fetch", e, url=url))
            stopped = isinstance(e, (HostBlocked, HostRefused))
        except FetchFailed as e:              # one file (e.g. a .docx behind a PDF link) is logged and skipped
            log["failures"].append(failure("fetch", e, url=url))
    store.save()
    log["fetch_log"] = f.log
    return rows


def listing_rows(p: dict, cfg: AgendaCenterConfig, store: Store | None = None) -> tuple[list[dict], list[dict]]:
    """Both committed listings joined (civicclerk.merge_sources). The meeting kind is re-read from each title with
    the current config, as the build does, so the de-duplication and the meeting ids agree. A D1 row is paired only
    after its page 1 check passes on the stored files (city-verify/d1-merge-before-page1); with no store, never."""
    ac = json.loads(p["listing"].read_text(encoding="utf-8")) if p["listing"].exists() else []
    cc = json.loads(p["cc_listing"].read_text(encoding="utf-8")) if p["cc_listing"].exists() else []
    ac = [{**r, "kind": cfg.kind_of(r["title"])} for r in ac]
    cc = [{**r, "kind": cfg.kind_of(r["title"])} for r in cc]
    if store is None:
        return civicclerk.merge_sources(ac, cc)
    from .city_build import page1_check
    return civicclerk.merge_sources(ac, cc, page1_ok=lambda r: page1_check(r, store) is None)


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
    ap.add_argument("--allow-shrink", action="store_true",
                    help="let a listing that drops committed rows, or a build that drops committed meetings, replace "
                         "the committed files (the shrink guard)")
    a = ap.parse_args(argv)
    cfg = load_config(Path(ROOT / "config" / "localities" / a.locality / "agenda-center.yml"))
    cc_path = civicclerk.config_path(a.locality)
    cc = civicclerk.load_config(cc_path) if cc_path.exists() else None
    p = paths(cfg)
    store = Store(manifest_path=p["manifest"])
    log = new_log()
    since = limits.mark()                      # this step's own trips only (limits invariant rule 3)
    if a.command in ("fetch", "run"):
        fetcher = PoliteFetcher()
        if a.source in ("all", "agenda-center"):
            cmd_fetch(cfg, store, p["listing"], log, fetcher=fetcher, agendas=a.agendas, limit=a.limit,
                      allow_shrink=a.allow_shrink)
        if cc and a.source in ("all", "civicclerk"):
            cmd_fetch_civicclerk(cc, cfg.kind_of, store, p["cc_listing"], log, fetcher=fetcher, agendas=a.agendas,
                                 limit=a.limit, allow_shrink=a.allow_shrink)
    report = {"fetch": {k: v for k, v in log.items() if k != "fetch_log"}}
    if a.command in ("build", "run"):
        from .city_build import build
        rows, dups = listing_rows(p, cfg, store)
        facts, summary = build(cfg, rows, store)
        summary["duplicates"] = dups
        wards = facts.pop("_wards")
        old = json.loads(p["facts"].read_text(encoding="utf-8")) if p["facts"].exists() else None
        dropped = facts_shrink(facts, old)
        guard = log.setdefault("guard", {})
        if dropped and not a.allow_shrink:
            n_new, n_old = len(facts.get("meetings") or []), len(old.get("meetings") or [])
            guard.setdefault("kept_meetings", []).append({"meeting_ids": dropped, "reason": "meetings gone from the result"})
            print(f"collector city: KEPT the build has {n_new} meetings and would drop {len(dropped)} of the {n_old} "
                  f"in {p['facts'].name}, e.g. {', '.join(dropped[:3])}; {p['facts'].name} and {p['wards'].name} are "
                  f"kept as committed", file=sys.stderr, flush=True)
        else:
            if dropped:
                guard.setdefault("allowed_shrink", []).append({"facts": p["facts"].name, "dropped": dropped})
            write_json(p["wards"], wards)
            write_json(p["facts"], facts)
        report["build"] = summary
        report["fetch"] = {k: v for k, v in log.items() if k != "fetch_log"}
    report["guard"] = log.get("guard") or {}
    report["limits"] = limits.tripped(since)
    write_json(p["report"], {**report, "fetch_log": log.get("fetch_log", [])})
    print(json.dumps({k: v for k, v in report.items()}, indent=1, default=str)[:4000])
    print(limits.summary("collector city", since), flush=True)
    code = exit_code(log)
    if "build" in report:              # the gates (AC-P1, G4) with the county's code: see GATE_FAILED
        g = report["build"]["gates"]
        print(f"collector city: {g['roll_calls']} roll calls, {g['verified']} verified "
              f"({100 * g['verified_rate']:.1f}%, AC-P1 {'pass' if g['verified_rate_gate']['pass'] else 'FAIL'}); "
              f"G4 {g['g4']['status']}, flagged {g['g4']['flagged'] or 'none'} "
              f"(uniform share {g['g4']['uniform_share']})", flush=True)
        if code == 0 and not g["g4"]["pass"]:
            print(f"collector city: G4 skew gate FAILED (exit {GATE_FAILED}): {', '.join(g['g4']['flagged'])}",
                  file=sys.stderr, flush=True)
            code = GATE_FAILED
    if code == 0 and kept_anything(log):       # precedence 5 > 2 > 3 > 7 > 0 (ADR 0006)
        print(f"collector city: KEPT (exit {KEPT}): committed rows or meetings kept, see guard in "
              f"{p['report'].name}; everything else is published", file=sys.stderr, flush=True)
        code = KEPT
    if code == BLOCKED:
        print(f"collector city: REFUSED by a host or by policy (exit {BLOCKED}); not retried. See the failures above.",
              file=sys.stderr, flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
