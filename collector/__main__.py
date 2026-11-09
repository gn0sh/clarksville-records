"""python -m collector {fetch,build,run,export} [--offline] [--internal] [--allow-shrink] [--out build/site]
python -m collector fin {fetch,build,census}   (finance and contracts: collector/fin_run.py)
python -m collector city {fetch,build,run}     (City Council, Agenda Center: collector/city_run.py)
python -m collector transcripts import <dir>   (meeting video transcripts: collector/transcripts.py)

run: discover -> fetch new (polite) -> parse -> resolve names -> verify -> data/facts.json -> finance fetch and
build (fin_run.run_step: data/finance.json, build/report.json `finance`) -> sitegen -> export -> build/report.json,
build/run-log.json. Exit 0 ok, 2 on fetch/parse failures (votes or finance), 3 on a gate failure (votes gates, or
finance parity 'review needed'). On 2 or 3 it prints the `gh issue create` command it would run (task D1).
--offline skips discovery and fetching (votes and finance) and uses the store (data/store/, or RECORDS_STORE).
Offline guard (provenance/offline-run-overwrites-facts): an offline run (and `build`) refuses, exit 4, writing
nothing, when minutes PDFs the manifest lists are missing from the store, when no minutes parse, or when the result
would drop a meeting data/facts.json has. --allow-shrink lets a deliberate shrink through.
export: build/site/data/ from the committed files (county facts, each council's facts, finance), no parsing.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import YEARS
from .discover import DiscoveryError, classify, discover, fetch_index
from .facts import Builder, dumps, load_procedural, write_if_changed
from .meetings import choose
from .fetch import FetchFailed, HostBlocked, HostRefused, PoliteFetcher, ProxyRefused, RobotsDisallowed
from .names import NAMES, Resolver, load_roster
from .store import MANIFEST, Store, fetch_into_store
from .verify import gates

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "data" / "facts.json"
FINANCE = ROOT / "data" / "finance.json"
BUILD = ROOT / "build"
REPO = "gn0sh/clarksville-records"


def load_seat_rows() -> list[dict] | None:
    """The seat holder rows for the export's seats.csv (none when the locality has no seats file yet)."""
    import yaml
    from sitegen import config
    p = Path(config.SEATS_PATH)
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or []) if p.is_file() else None


def doc_date(e: dict) -> str:
    return e.get("meeting_date") or (classify(e.get("label") or "") or {}).get("meeting_date") or ""


def in_range(e: dict) -> bool:
    d = doc_date(e)
    return e.get("kind", "minutes") == "minutes" and d[:4].isdigit() and int(d[:4]) in YEARS


# ------------------------------------------------------------------ fetch
def cmd_fetch(store: Store, log: dict, fetcher: PoliteFetcher | None = None) -> None:
    f = fetcher or PoliteFetcher()
    try:
        page = fetch_index(f)
        found, skipped = discover(page)
    except (DiscoveryError, HostBlocked, HostRefused, ProxyRefused, RobotsDisallowed, FetchFailed) as e:
        log["failures"].append({"stage": "discover", "error": f"{type(e).__name__}: {e}"})
        log["fetch_log"] = f.log
        return
    log["found"] = len(found)
    log["skipped_links"] = skipped
    for d in found:
        try:
            entry, status = fetch_into_store(f, store, d["url"], {"kind": "minutes", "meeting_date": d["meeting_date"],
                                                                  "label": d["label"]})
            log["fetched"][status] = log["fetched"].get(status, 0) + 1
            if status in ("new", "changed"):
                log["new"].append(d["url"])
        except (HostBlocked, HostRefused, ProxyRefused, RobotsDisallowed, FetchFailed) as e:
            log["failures"].append({"stage": "fetch", "url": d["url"], "error": f"{type(e).__name__}: {e}"})
    store.save()
    log["fetch_log"] = f.log


def finance_fetcher() -> PoliteFetcher:
    """One polite fetcher for the votes and finance fetches of a run (robots cache and per-host clock shared), which
    also hard-denies finance.yml bonfire_hosts."""
    from . import fin_config
    return PoliteFetcher(extra_denied=fin_config.load().bonfire_hosts)


def run_finance(store: Store, log: dict, offline: bool, **kw) -> int:
    from .fin_run import run_step
    return run_step(store, log, offline, **kw)


# ------------------------------------------------------------------ build
def cmd_build(store: Store, log: dict, use_ocr: bool = True) -> tuple[dict, dict, Builder]:
    from .minutes import parse_minutes
    roster = load_roster(NAMES)
    b = Builder(Resolver(roster), load_procedural())
    # only the latest version of each URL is read; replaced versions stay in the manifest for citations only
    entries = sorted((e for e in store.current() if in_range(e)), key=lambda e: (doc_date(e), e["url"]))
    log["superseded"] = [{"url": e["url"], "sha256": e["sha256"], "superseded_by": e.get("superseded_by")}
                         for e in store.superseded()]
    seen_sha: set[str] = set()
    parsed_docs = []
    for e in entries:
        if e["sha256"] in seen_sha:
            continue                     # the same bytes listed under two URLs: one document
        seen_sha.add(e["sha256"])
        p = store.path_for(e["sha256"])
        if not p.exists():
            log["failures"].append({"stage": "parse", "url": e["url"], "error": "not in the store (run without --offline)"})
            continue
        t0 = time.time()
        try:
            pd = parse_minutes(p, e, use_ocr=use_ocr)
        except Exception as ex:          # one bad document must not stop the run; it is logged and alerted
            log["failures"].append({"stage": "parse", "url": e["url"], "error": f"{type(ex).__name__}: {ex}"})
            continue
        parsed_docs.append(pd)
        log["parsed"] += 1
        rcs = [r for m in pd.meetings for r in m.roll_calls]
        print(f"  parsed {e.get('label') or e['url']}: meetings "
              f"{', '.join(f'{m.meeting_date} ({m.segment.role})' for m in pd.meetings) or 'none'}; {len(rcs)} roll "
              f"calls, {sum(r.status == 'Verified' for r in rcs)} verified ({time.time() - t0:.0f} s)", flush=True)
    if not log["parsed"]:
        log["failures"].append({"stage": "parse", "error": "no minutes documents parsed"})
    chosen, copies, undated = choose(parsed_docs)
    for pm in chosen:
        b.add(pm)
    for pd in parsed_docs:
        b.add_zoning(pd)
    for u in undated:
        b.problems.append({"source": u["source_id"], "problem": f"minutes on pp{u['pages'][0]}-{u['pages'][1]}: "
                                                                f"{u['problem']} ({u['date_how']})"})
    for p in b.problems:
        log["failures"].append({"stage": "assemble", **p})
    facts = b.facts(roster)
    g = gates(facts, b.source_errors)
    log["held_back"] = g["held_back"]
    report = {
        "generated_for": {"coverage": facts["coverage"], "sources": len(facts["sources"])},
        "gates": g,
        "pass": g["verified_rate_gate"]["pass"] and g["g4"]["pass"],
        "held_back_roll_calls": [
            {"id": r["id"], "meeting_id": r["meeting_id"], "page": r["page"],
             "source_error": r["id"] in b.source_errors,
             "failed": [c["check"] for c in r["verification"]["checks"] if not c["ok"]]}
            for r in facts["roll_calls"] if r["verification"]["status"] != "verified"],
        "meetings_attendance_unverified": [m["id"] for m in facts["meetings"]
                                           if m["verification"]["status"] != "verified"],
        "consent_roll_calls_not_expanded": sorted(b.consent_unexpanded),
        "motions_held_back": sum(m["verification"]["status"] != "verified" for m in facts["motions"]),
        "documents": documents_report(parsed_docs, b),
        "meetings_by_year": meetings_by_year(facts),
        "meeting_copies": copies,
        "consent_reprints": dict(sorted(b.consent_reprints.items())),
        "superseded_sources": log.get("superseded", []),
        "problems": b.problems,
    }
    return facts, report, b


def documents_report(parsed_docs: list, b: Builder) -> list[dict]:
    """Per document: its index label (a hint only), the meetings found in its text and which of them it supplies."""
    used = {(d["source_id"], d["meeting_id"]): d for d in b.doc_summary}
    out = []
    for pd in parsed_docs:
        sid = f"src-{pd.source['sha256'][:12]}"
        label_hint = (classify(pd.source.get("label") or "") or {}).get("meeting_date")
        found = []
        for m in pd.meetings:
            mid = f"{m.meeting_date}-{m.kind}" if m.meeting_date else None
            found.append({"meeting_id": mid, "pages": [m.segment.page, m.segment.end_page], "role": m.segment.role,
                          "boundaries_certain": m.segment.certain, "date_read": m.segment.date_how,
                          "vote_tables": len(m.roll_calls),
                          # a used meeting counts its votes (consent reprints are one vote); an unused copy its tables
                          "roll_calls": used[(sid, mid)]["roll_calls"] if (sid, mid) in used else len(m.roll_calls),
                          "verified": (used[(sid, mid)]["verified"] if (sid, mid) in used else
                                       sum(r.status == "Verified" for r in m.roll_calls)),
                          "used": (sid, mid) in used})
        own = [f["meeting_id"] for f in found if f["role"] == "own"]
        out.append({"source_id": sid, "label": pd.source.get("label"), "label_month": label_hint,
                    "label_matches_text": bool(own and label_hint and own[0] and own[0].startswith(label_hint)),
                    "pages": pd.pages, "image_only_pages": len(pd.image_only_pages),
                    "vote_tables_outside_minutes": pd.tables_outside_minutes, "meetings_found": found})
    return sorted(out, key=lambda d: ((d["meetings_found"] or [{}])[0].get("meeting_id") or "", d["source_id"]))


def meetings_by_year(facts: dict) -> dict:
    """Actual meeting dates covered, per year, with roll-call counts (coverage is these dates, not a range)."""
    out: dict[str, dict] = {}
    by_m: dict[str, list] = {}
    for r in facts["roll_calls"]:
        by_m.setdefault(r["meeting_id"], []).append(r)
    for m in sorted(facts["meetings"], key=lambda m: m["id"]):
        y = out.setdefault(m["date"][:4], {"meetings": [], "roll_calls": 0, "verified": 0})
        rs = by_m.get(m["id"], [])
        y["meetings"].append(m["id"])
        y["roll_calls"] += len(rs)
        y["verified"] += sum(r["verification"]["status"] == "verified" for r in rs)
    for y in out.values():
        y["verified_rate"] = round(y["verified"] / y["roll_calls"], 4) if y["roll_calls"] else None
    return out


def name_candidates(b: Builder, roster: list[dict]) -> dict:
    r = Resolver(roster)
    return {
        "rules": "names.yml merge rules 1-4 (collector/names.py). Suggestions are never applied automatically.",
        "unmatched": [{"raw_name": k, "count": v["count"], "examples": v["examples"], "suggestions": r.suggestions(k)}
                      for k, v in sorted(b.unresolved.items(), key=lambda kv: (-kv[1]["count"], kv[0]))],
        "merges": [{"official_id": o["id"], "name": o["name"], "alias": a["alias"], "reason": a.get("reason"),
                    "example": a.get("example")} for o in roster for a in o["aliases"]],
    }


def issue_command(code: int, log: dict, report: dict | None) -> str:
    title = "Collector run failed" if code == 2 else "Collector gates failed"
    body = {"exit": code, "failures": log["failures"][:20],
            "gates": (report or {}).get("gates", {}).get("verified_rate_gate"),
            "g4_flagged": (report or {}).get("gates", {}).get("g4", {}).get("flagged"),
            "finance_build_exit": log.get("fin_build")}          # 3: parity 'review needed' (A5)
    return (f"gh issue create --repo {REPO} --title {shlex.quote(title)} "
            f"--body {shlex.quote(json.dumps(body, indent=1))}")


# ------------------------------------------------------------------ offline guard
REFUSED = 4


def missing_inputs(store: Store) -> list[dict]:
    """Minutes entries the build would read (current, in range) whose bytes are not in the store."""
    return [e for e in store.current() if in_range(e) and not store.path_for(e["sha256"]).exists()]


def shrink_reason(facts: dict, log: dict, facts_path: Path) -> str | None:
    """Why an offline result must not replace facts_path, or None. Refused: no minutes parsed, a document not in the
    store, or a meeting the current file has that the new result lacks (provenance/offline-run-overwrites-facts)."""
    gone = [f for f in log["failures"] if f.get("stage") == "parse" and "not in the store" in f.get("error", "")]
    if gone:
        return f"{len(gone)} minutes documents are not in the store, e.g. {gone[0].get('url')}"
    if not log.get("parsed") or not facts.get("meetings"):
        return "no minutes documents parsed"
    if not Path(facts_path).is_file():
        return None
    old = json.loads(Path(facts_path).read_text(encoding="utf-8"))
    dropped = sorted({m["id"] for m in old.get("meetings", [])} - {m["id"] for m in facts["meetings"]})
    if dropped:
        return (f"the result has {len(facts['meetings'])} meetings and would drop {len(dropped)} of the "
                f"{len(old.get('meetings', []))} in {Path(facts_path).name}, e.g. {', '.join(dropped[:3])}. "
                f"A parser change that renames meeting ids also causes this; pass --allow-shrink to override")
    return None


def refuse(why: str) -> int:
    print(f"collector: REFUSED (offline run): {why}. {FACTS.name} and the build were left unchanged. Restore the "
          "store (data/store/ or RECORDS_STORE), run without --offline, or pass --allow-shrink if the smaller result "
          "is meant.", file=sys.stderr, flush=True)
    return REFUSED


def cmd_export(args) -> int:
    """build/site/data/ from the committed files only: the county facts, each council's, finance (no parsing)."""
    from .export import export_site
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    out = Path(args.out)
    written = export_site(facts, out, internal=args.internal, seats=load_seat_rows(), finance_path=FINANCE)
    try:
        from sitegen.build import write_publish_manifest
    except ImportError:
        write_publish_manifest = None
    if write_publish_manifest is not None:
        write_publish_manifest(out)
    print(f"collector export: {len(written)} files, {sum(p.stat().st_size for p in written):,} bytes, to {out}/data")
    return 0


def cmd_run(args) -> int:
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log = {"started_at": started, "offline": args.offline, "found": None, "new": [], "fetched": {}, "failures": [],
           "parsed": 0, "held_back": None}
    store = Store(MANIFEST)
    allow = getattr(args, "allow_shrink", False)
    if args.offline and not allow:
        missing = missing_inputs(store)
        if missing:
            return refuse(f"{len(missing)} minutes PDFs listed in the manifest are not in the store "
                          f"({store.root}), e.g. {missing[0]['url']}")
    fetcher = None
    if not args.offline:
        fetcher = finance_fetcher()
        print("collector: discover and fetch (10 s between requests per host)", flush=True)
        cmd_fetch(store, log, fetcher=fetcher)
    print("collector: parse, verify, assemble", flush=True)
    facts, report, b = cmd_build(store, log, use_ocr=not args.no_ocr)
    if args.offline and not allow:
        why = shrink_reason(facts, log, FACTS)
        if why:
            return refuse(why)
    changed = write_if_changed(FACTS, dumps(facts))
    BUILD.mkdir(parents=True, exist_ok=True)
    write_if_changed(BUILD / "report.json", dumps(report))
    write_if_changed(BUILD / "name-candidates.json", dumps(name_candidates(b, load_roster(NAMES))))
    fin_code = run_finance(store, log, args.offline, fetcher=fetcher, finance_path=FINANCE,
                           report_path=BUILD / "report.json")
    site = BUILD / "site"
    try:
        from sitegen.build import build as site_build, write_publish_manifest
    except ImportError:
        print("collector: sitegen is not installed in this checkout; skipping the site step", flush=True)
        site_build = None
    from .export import export_site
    if site_build:
        site_build(FACTS, site, internal=args.internal, report_path=BUILD / "report.json")
    export_site(facts, site, internal=args.internal, seats=load_seat_rows(), finance_path=FINANCE)
    if site_build:
        write_publish_manifest(site)
    log["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log["facts_changed"] = changed
    (BUILD / "run-log.json").write_text(dumps(log))
    g = report["gates"]
    print(f"collector: {log['parsed']} documents parsed, {g['roll_calls']} roll calls, {g['verified']} verified "
          f"({100 * g['verified_rate']:.1f}%), {g['held_back']} held back "
          f"({g['held_back_source_error']} by source errors); G4 {g['g4']['status']} "
          f"(uniform share {g['g4']['uniform_share']}); "
          f"failures {len(log['failures'])}", flush=True)
    code = 2 if log["failures"] else (0 if report["pass"] and fin_code == 0 else 3)
    if code:
        for fl in log["failures"][:10]:
            print("  failure:", json.dumps(fl)[:300])
        print("collector: would open an internal issue (D1 wires this):")
        print("  " + issue_command(code, log, report))
    return code


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["city"]:
        from .city_run import main as city_main
        return city_main(argv[1:])
    if argv[:1] == ["transcripts"]:
        from .transcripts import main as tx_main
        return tx_main(argv[1:])
    if argv[:1] == ["fin"]:
        from .fin_run import main as fin_main
        return fin_main(argv[1:])
    ap = argparse.ArgumentParser(prog="python -m collector")
    ap.add_argument("command", choices=["run", "fetch", "build", "export"])
    ap.add_argument("--offline", action="store_true", help="skip discovery and fetching; use the store")
    ap.add_argument("--internal", action="store_true", help="build the internal review page too")
    ap.add_argument("--no-ocr", action="store_true", help="text layer only (no tesseract second reading)")
    ap.add_argument("--allow-shrink", action="store_true",
                    help="offline: let a result with fewer meetings, or missing store files, replace data/facts.json")
    ap.add_argument("--out", default=str(BUILD / "site"), help="export: the site folder (default build/site)")
    args = ap.parse_args(argv)
    if args.command == "export":
        return cmd_export(args)
    if args.command == "fetch":
        log = {"found": None, "new": [], "fetched": {}, "failures": []}
        store = Store(MANIFEST)
        cmd_fetch(store, log)
        print(json.dumps({k: v for k, v in log.items() if k != "fetch_log"}, indent=1))
        return 2 if log["failures"] else 0
    if args.command == "build":
        args.offline = True
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
