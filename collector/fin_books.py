"""python -m collector fin-books {fetch,build} --locality <id>: budget books of a locality with no purchasing archive
(the City of Clarksville, config/localities/clarksville-tn/finance.yml; architecture finance-contracts A2).

The county pipeline unchanged, pointed at the locality's own files so county output stays byte-identical:
fetch:  each book in finance.yml `budget.books` into the store (fin_run.fetch_books: polite fetcher, robots.txt,
        10 s per host, own User-Agent, allowlist; a stored book is not requested again). The locality's manifest is
        its own file, data/localities/<id>/fin-manifest.json (bytes in the shared, uncommitted store).
build:  store -> data/localities/<id>/finance.json through fin_facts.build_budget (fin_budget.read_book, then
        fin_checks.reconcile and edition_compare): no solicitations, no documents; validated against
        schema/finance.schema.json. A book missing from the store or without a text layer writes nothing
        (fin_run.GUARD_KEYS). The run report goes to build/fin-books-<id>.json.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import fin_checks, fin_config, limits
from .fetch import PoliteFetcher
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


def paths(locality: str, root: Path = ROOT) -> dict:
    d = root / "data" / "localities" / locality
    return {"config": root / "config" / "localities" / locality / "finance.yml",
            "manifest": d / "fin-manifest.json", "finance": d / "finance.json",
            "report": root / "build" / f"fin-books-{locality}.json"}


def cmd_fetch(store: Store, cfg: fin_config.BooksConfig, fetcher: PoliteFetcher | None = None,
              progress=print) -> dict:
    from .fin_run import fetch_books
    f = fetcher or PoliteFetcher(extra_denied=cfg.bonfire_hosts)
    log = {"failures": [], "stopped": None}
    if not fetch_books(f, store, cfg, log, progress):
        fetch_not_read(f, store, cfg, log, progress)
    log["fetch_log"] = f.log
    return log


def fetch_not_read(f, store: Store, cfg: fin_config.BooksConfig, log: dict, progress=print) -> None:
    """Books listed as not read are fetched the same way (kind budget_book), so their link cites a stored file."""
    from .fetch import FetchFailed, HostBlocked, HostRefused, ProxyRefused, RobotsDisallowed
    from .fin_run import BOOK_KIND
    from .store import fetch_into_store
    for b in cfg.budget.books_not_read:
        try:
            entry, st = fetch_into_store(f, store, b["url"], {"kind": BOOK_KIND, "label": b["title"]})
            log["books"][b["id"]] = st
            if st in ("new", "changed"):
                store.save()
                progress(f"  book {b['id']} (not read): {st} {b['url']}", flush=True)
        except (HostBlocked, ProxyRefused) as e:
            log["stopped"] = f"{type(e).__name__} at {b['url']}: {e}"
            return
        except (HostRefused, RobotsDisallowed, FetchFailed) as e:
            log["failures"].append({"stage": f"book {b['id']}", "error": f"{type(e).__name__}: {e}"})
    store.save()


def build(store: Store, cfg: fin_config.BooksConfig, meta_cache: Path | None = None, **kw) -> tuple[dict, list]:
    """-> (finance facts, problems). The county's finance.json shape with only books, budget lines and sources."""
    from . import fin_facts
    sources: dict = {}
    problems: list[str] = []
    mc = fin_facts.META_CACHE if meta_cache is None else meta_cache
    books, lines = fin_facts.build_budget(store, cfg, sources, problems, mc, **kw)
    fin = {"schema_version": fin_facts.SCHEMA_VERSION, "sources": sorted(sources.values(), key=lambda s: s["id"]),
           "solicitations": [], "documents": [], "books": books, "budget_lines": lines}
    fin["coverage"] = fin_checks.coverage(fin)
    problems += fin_checks.scan_guard(fin)
    return fin, problems


def book_summary(fin: dict) -> dict:
    """fin_facts.budget_summary, with the funds by printed name (the city books print no fund number) and the count
    of subtotal and total lines checked."""
    from . import fin_facts
    out = fin_facts.budget_summary(fin)
    for book_id, b in out.items():
        lines = [x for x in fin["budget_lines"] if x["book_id"] == book_id]
        b["funds"] = sorted({x["fund_name"] for x in lines if x["fund_name"]})
        b["totals"] = sum(1 for x in lines if x["check"])
    return out


KEPT = 3     # cmd_build(keep_committed=True): the new build reads worse than the committed file, which is kept


def book_stats(fin: dict) -> dict:
    """Per book: its source's sha256, its line count and its held and does-not-add-up counts."""
    sha = {s["id"]: s["sha256"] for s in fin.get("sources", [])}
    out = {b["id"]: {"sha256": sha.get(b["source_id"]), "lines": 0, "held": 0, "does_not_add_up": 0}
           for b in fin.get("books", [])}
    for x in fin.get("budget_lines", []):
        st = out.get(x["book_id"])
        if st is None:
            continue
        st["lines"] += 1
        st["held"] += bool(x["held"])
        st["does_not_add_up"] += bool(x["check"] and x["check"]["state"] == "does_not_add_up")
    return out


def worse_than_committed(new: dict, old: dict) -> list[str]:
    """Why the daily build must not replace the committed finance.json (city-books/daily-overwrite-unguarded): a
    committed book dropped or read from a file whose sha256 differs from the committed source (the city replaced the
    file: a person reviews the new reading first), fewer lines, or more held or does-not-add-up lines (a book new to
    the file counts from 0). [] = the new build may be written."""
    a, b = book_stats(old), book_stats(new)
    why = []
    for book_id, o in a.items():
        n = b.get(book_id)
        if n is None:
            why.append(f"book {book_id}: in the committed file, not in the new build")
            continue
        if n["sha256"] != o["sha256"]:
            why.append(f"book {book_id}: source sha256 {str(n['sha256'])[:12]} differs from the committed "
                       f"{str(o['sha256'])[:12]}")
        if n["lines"] < o["lines"]:
            why.append(f"book {book_id}: {n['lines']} lines, committed {o['lines']}")
    for book_id, n in b.items():
        o = a.get(book_id, {"held": 0, "does_not_add_up": 0})
        for k in ("held", "does_not_add_up"):
            if n[k] > o[k]:
                why.append(f"book {book_id}: {n[k]} {k.replace('_', ' ')} lines, committed {o[k]}")
    return why


def cmd_build(store: Store, cfg: fin_config.BooksConfig, finance_path: Path, report_path: Path,
              keep_committed: bool = False, **kw) -> int:
    """Exit 0 ok, 2 on schema or guard problems (finance.json not written; the report says why under `stopped`).
    With keep_committed (the daily run), KEPT when the
    new build reads worse than the committed finance.json (worse_than_committed): the committed file is kept and the
    reasons go to the report (`kept`) and the output."""
    from .facts import dumps, write_if_changed
    from .fin_run import GUARD_KEYS, validate
    since = limits.mark()
    fin, problems = build(store, cfg, **kw)
    errors = validate(fin)
    guard = [p for p in problems if any(k in p for k in GUARD_KEYS)]
    if errors or guard:
        # the report says why, so it never shows an earlier build's outcome (budget/exit2-stale-report)
        write_if_changed(Path(report_path), dumps({"stopped": {"schema_errors": errors[:50], "guard": guard},
                                                   "problems": problems}))
        for p in (errors + guard)[:20]:
            print("  problem:", p)
        print(f"collector fin-books: {len(errors)} schema errors, {len(guard)} guard problems; nothing written")
        print(limits.summary("collector fin-books", since))
        return 2
    kept = []
    if keep_committed and Path(finance_path).is_file():
        kept = worse_than_committed(fin, json.loads(Path(finance_path).read_text(encoding="utf-8")))
    changed = False if kept else write_if_changed(Path(finance_path), dumps(fin))
    summary = book_summary(fin)
    report = {"reconcile": fin_checks.reconcile_counts(fin["budget_lines"]), "budget": summary,
              "held": [{"id": x["id"], "check": x["held"]} for x in fin["budget_lines"] if x["held"]],
              "books_not_read": list(cfg.budget.books_not_read), "problems": problems}
    if kept:
        report["kept"] = kept
    write_if_changed(Path(report_path), dumps(report))
    if kept:
        for k in kept:
            print("  kept:", k)
        print(f"collector fin-books: KEPT the committed {Path(finance_path).name}: the new build reads worse "
              f"({len(kept)} reasons); nothing written")
        print(limits.summary("collector fin-books", since))
        return KEPT
    print(f"collector fin-books: {len(fin['books'])} books, {len(fin['budget_lines'])} lines; "
          f"{Path(finance_path).name} {'changed' if changed else 'unchanged'}")
    for book_id, b in summary.items():
        print(f"  budget {book_id}: {b['lines']} lines, {len(b['funds'])} funds, {b['totals']} totals, reconcile "
              f"{json.dumps(b['reconcile'], sort_keys=True)}, held {b['held']}, edition differs {b['edition_differs']}")
    for b in cfg.budget.books_not_read:
        print(f"  not read: {b['id']} ({b['reason']}) {b['url']}")
    for p in problems:
        print("  note:", p)
    print(limits.summary("collector fin-books", since))
    return 0


def localities(root: Path = ROOT) -> list[str]:
    """The councils' localities (config/site.yml `councils`) with a books-only finance.yml, in config order. The
    county's own finance.yml (the purchasing archive and its books) runs through fin_run, not here."""
    import yaml
    site = root / "config" / "site.yml"
    if site.is_file():
        locs = (yaml.safe_load(site.read_text(encoding="utf-8")) or {}).get("councils") or []
    else:       # a test root with only locality configs
        locs = sorted(p.parent.name for p in (root / "config" / "localities").glob("*/finance.yml"))
    return [loc for loc in locs if (root / "config" / "localities" / loc / "finance.yml").is_file()]


def run_step(log: dict, offline: bool, fetcher: PoliteFetcher | None = None, root: Path = ROOT,
             progress=print) -> dict:
    """The daily run's step (collector run, before the site build): per locality, fetch only books not in the store
    yet (online runs; a stored book is never requested again), then build offline from the store. Never raises and
    never fails the run: a refusal, a missing book, a guard problem (build 2) or a build that reads worse than the
    committed file (build KEPT, worse_than_committed) writes nothing and leaves the committed finance.json as it is;
    the outcome goes to log['city_books'] {locality: {fetch, build, warning?}}; warnings(log) lists the warnings."""
    out = log.setdefault("city_books", {})
    for loc in localities(root):
        p = paths(loc, root)
        res: dict = {"fetch": None, "build": None}
        out[loc] = res
        try:
            cfg = fin_config.load_books(p["config"])
            store = Store(manifest_path=p["manifest"])
            if not offline:
                flog = cmd_fetch(store, cfg, fetcher, progress)
                res["fetch"] = {"stopped": flog["stopped"], "failures": flog["failures"],
                                "new": sorted(k for k, v in flog.get("books", {}).items() if v in ("new", "changed"))}
                if flog["stopped"]:
                    progress(f"collector: city books {loc}: fetch stopped ({flog['stopped']}); building from the store",
                             flush=True)
            res["build"] = cmd_build(store, cfg, p["finance"], p["report"], keep_committed=True)
            if res["build"] == 2:
                res["warning"] = (f"city books {loc}: build stopped on schema or guard problems (exit 2); the "
                                  f"committed finance.json is kept, see {p['report'].name} and the run output")
            elif res["build"] == KEPT:
                rep = json.loads(p["report"].read_text(encoding="utf-8"))
                res["warning"] = (f"city books {loc}: the new build reads worse than the committed finance.json, "
                                  f"which is kept: " + "; ".join(rep.get("kept", [])))
        except Exception as e:   # noqa: BLE001 - one locality's books must never stop the daily run
            res["error"] = f"{type(e).__name__}: {e}"
            res["warning"] = f"city books {loc}: {res['error']}; the committed finance.json is kept"
        if res.get("warning"):
            progress(f"collector: WARNING {res['warning']}", flush=True)
    return out


def warnings(log: dict) -> list[str]:
    """The city books step's warnings for the run log (log['warnings'])."""
    return [r["warning"] for r in (log.get("city_books") or {}).values() if r.get("warning")]


def main(argv=None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog="python -m collector fin-books")
    ap.add_argument("command", choices=["fetch", "build"])
    ap.add_argument("--locality", required=True, help="e.g. clarksville-tn (config/localities/<id>/finance.yml)")
    args = ap.parse_args(argv)
    p = paths(args.locality)
    cfg = fin_config.load_books(p["config"])
    store = Store(manifest_path=p["manifest"])
    if args.command == "fetch":
        print(f"collector fin-books: fetch {len(cfg.budget.books)} books (10 s between requests per host)", flush=True)
        log = cmd_fetch(store, cfg)
        print(json.dumps({k: v for k, v in log.items() if k != "fetch_log"}, indent=1))
        if log["stopped"]:
            print(f"collector fin-books: STOPPED, not retried: {log['stopped']}", file=sys.stderr)
            return 2
        return 2 if log["failures"] else 0
    return cmd_build(store, cfg, p["finance"], p["report"])
