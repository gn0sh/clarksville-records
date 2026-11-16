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


def cmd_build(store: Store, cfg: fin_config.BooksConfig, finance_path: Path, report_path: Path, **kw) -> int:
    """Exit 0 ok, 2 on schema or guard problems (nothing written)."""
    from . import fin_facts
    from .facts import dumps, write_if_changed
    from .fin_run import GUARD_KEYS, validate
    since = limits.mark()
    fin, problems = build(store, cfg, **kw)
    errors = validate(fin)
    guard = [p for p in problems if any(k in p for k in GUARD_KEYS)]
    if errors or guard:
        for p in (errors + guard)[:20]:
            print("  problem:", p)
        print(f"collector fin-books: {len(errors)} schema errors, {len(guard)} guard problems; nothing written")
        print(limits.summary("collector fin-books", since))
        return 2
    changed = write_if_changed(Path(finance_path), dumps(fin))
    summary = fin_facts.budget_summary(fin)
    report = {"reconcile": fin_checks.reconcile_counts(fin["budget_lines"]), "budget": summary,
              "held": [{"id": x["id"], "check": x["held"]} for x in fin["budget_lines"] if x["held"]],
              "problems": problems}
    write_if_changed(Path(report_path), dumps(report))
    print(f"collector fin-books: {len(fin['books'])} books, {len(fin['budget_lines'])} lines; "
          f"{Path(finance_path).name} {'changed' if changed else 'unchanged'}")
    for book_id, b in summary.items():
        print(f"  budget {book_id}: {b['lines']} lines, {len(b['funds'])} funds, reconcile "
              f"{json.dumps(b['reconcile'], sort_keys=True)}, held {b['held']}, edition differs {b['edition_differs']}")
    for p in problems:
        print("  note:", p)
    print(limits.summary("collector fin-books", since))
    return 0


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
