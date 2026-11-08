"""python -m collector fin {fetch,build,census} (task F5c, architecture A1-A2, A5).

fetch:  the purchasing archive page (always re-requested; a new version is stored only when its table changed), then
        every document it links that is not yet in the store, through the polite fetcher (robots.txt, 10 s per host,
        User-Agent, allowlist). Bonfire hosts are never requested; a link to a host off the allowlist or to a non-PDF
        file (.docx) is recorded, not requested. A site 403/429 or a proxy refusal stops the whole fetch (never worked
        around). Unfetched links are recorded in data/fin_fetch_status.json (committed, deterministic: a status keeps
        its first date while it is unchanged).
build:  store -> data/finance.json (fin_facts) and the `finance` block of build/report.json (coverage, parity).
census: per bid-tab link its layout class (lump_sum / not_read / scan) and the award-letter scan count (F5b).
"""
from __future__ import annotations

import json
import posixpath
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from .fetch import (FetchFailed, HostBlocked, HostRefused, NotPdf, PoliteFetcher, ProxyRefused, RobotsDisallowed,
                    _host_matches)
from .fin_archive import parse_archive
from .fin_config import FinanceConfig
from .store import Store, _looks_html, fetch_into_store

ROOT = Path(__file__).resolve().parent.parent
FETCH_STATUS = ROOT / "data" / "fin_fetch_status.json"
# document.stage -> source.kind (both enums of schema/finance.schema.json)
STAGE_KIND = {"bid_tab": "bid_tab", "award_letter": "award_letter", "partial_award": "award_letter",
              "notice_of_intent": "notice", "notice_of_award": "notice", "bid": "bid", "advertisement": "bid",
              "rfp": "rfp", "rfq": "rfp"}
ARCHIVE_KIND = "archive_index"


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def source_kind(stage: str) -> str:
    return STAGE_KIND.get(stage, "other")


def load_status(path: Path = FETCH_STATUS) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).is_file() else {}


def save_status(status: dict, path: Path = FETCH_STATUS) -> None:
    text = json.dumps(dict(sorted(status.items())), indent=2, sort_keys=True) + "\n"
    path = Path(path)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _mark(status: dict, url: str, state: str, detail: str, today: str) -> None:
    old = status.get(url)
    if old and old["status"] == state:
        return                                   # unchanged status keeps its first date (no-op run, no diff)
    status[url] = {"status": state, "date": today, "detail": detail}


def precheck(url: str, cfg: FinanceConfig, allowed: tuple) -> tuple[str, str] | None:
    """(status, detail) for a link that is never requested, else None."""
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc.lower()
    if _host_matches(host, cfg.bonfire_hosts):
        return "link_only", "bid site (finance.yml bonfire_hosts): never requested"
    if parts.scheme != "https" or not _host_matches(host, allowed):
        return "link_only", "host not on the allowlist: not requested"
    ext = posixpath.splitext(urllib.parse.unquote(parts.path))[1].lower()
    if ext and ext != ".pdf":
        return "not_pdf", f"{ext} file: not requested (only PDFs are read)"
    return None


def archive_links(rows) -> list[tuple[str, str, str]]:
    """Unique (url, stage, label) in page order; the first link to a URL names its stage."""
    seen, out = set(), []
    for r in rows:
        for lk in r.links:
            if lk.url not in seen:
                seen.add(lk.url)
                out.append((lk.url, lk.stage, lk.label))
    return out


def fetch_archive(f, store: Store, cfg: FinanceConfig):
    """-> (entry, status, rows). The page is always requested. Its bytes change on every request (the site's
    e-mail obfuscation outside the table), so a new version is stored only when the table read from it differs from
    the stored version's; otherwise the stored version stays the source (status 'unchanged-table') and a no-op run
    leaves the manifest and finance.json as they were."""
    status, body, headers = f.get(cfg.archive_url)
    if status != 200:
        raise FetchFailed(f"HTTP {status} for {cfg.archive_url}")
    if not _looks_html(body, headers):
        raise FetchFailed(f"not an HTML page: {cfg.archive_url} ({headers.get('Content-Type')})")
    rows = parse_archive(body.decode("utf-8", "replace"), cfg)          # StructureChanged propagates: fail loudly
    known = store.latest(cfg.archive_url)
    if known and store.has_bytes(known["sha256"]):
        old = parse_archive(store.path_for(known["sha256"]).read_text(encoding="utf-8"), cfg)
        if old == rows:
            return known, "unchanged-table", old
    entry, st = store.put(cfg.archive_url, body, headers, {"kind": ARCHIVE_KIND, "label": "purchasing archive"})
    return entry, st, rows


def cmd_fetch(store: Store, cfg: FinanceConfig, fetcher: PoliteFetcher | None = None,
              status_path: Path = FETCH_STATUS, today: str | None = None, progress=print) -> dict:
    f = fetcher or PoliteFetcher(extra_denied=cfg.bonfire_hosts)
    if not set(cfg.bonfire_hosts) <= set(f.extra_denied):
        raise ValueError("the finance fetcher must deny finance.yml bonfire_hosts")
    today = today or _today()
    log = {"archive": None, "links": 0, "fetched": {}, "not_requested": {}, "failures": [], "stopped": None}
    status = load_status(status_path)
    try:
        entry, st, rows = fetch_archive(f, store, cfg)
        store.save()
        log["archive"] = {"sha256": entry["sha256"], "status": st}
    except (HostBlocked, ProxyRefused) as e:
        log["stopped"] = f"{type(e).__name__}: {e}"
        log["fetch_log"] = f.log
        return log
    except (HostRefused, RobotsDisallowed, FetchFailed) as e:
        log["failures"].append({"stage": "archive", "error": f"{type(e).__name__}: {e}"})
        log["fetch_log"] = f.log
        return log
    links = archive_links(rows)
    log["links"] = len(links)
    for n, (url, stage, label) in enumerate(links, start=1):
        pre = precheck(url, cfg, f.allowed_hosts)
        if pre:
            _mark(status, url, pre[0], pre[1], today)
            log["not_requested"][pre[0]] = log["not_requested"].get(pre[0], 0) + 1
            continue
        try:
            entry, st = fetch_into_store(f, store, url, {"kind": source_kind(stage), "label": label})
            status.pop(url, None)
            log["fetched"][st] = log["fetched"].get(st, 0) + 1
            if st in ("new", "changed"):
                store.save()                         # a long first run keeps its progress if it is interrupted
                progress(f"  [{n}/{len(links)}] {st}: {label} {url}", flush=True)
        except NotPdf as e:
            _mark(status, url, "not_pdf", str(e), today)
        except (HostBlocked, ProxyRefused) as e:
            log["stopped"] = f"{type(e).__name__} at {url}: {e}"
            break
        except (HostRefused, RobotsDisallowed) as e:
            _mark(status, url, "link_only", f"{type(e).__name__}: {e}", today)
        except FetchFailed as e:
            _mark(status, url, "dead_at_fetch", str(e), today)       # a fact about the source, not a run failure
            log.setdefault("dead", []).append({"url": url, "error": str(e)})
    store.save()
    save_status(status, status_path)
    log["fetch_log"] = f.log
    return log


def validate(fin: dict) -> list[str]:
    from sitegen import build as sitegen_build, config as site_config
    return sitegen_build._schema_errors(sitegen_build._validator(site_config.FINANCE_SCHEMA_PATH), fin)


def cmd_build(store: Store, cfg: FinanceConfig, finance_path: Path | None = None, report_path: Path | None = None,
              status_path: Path = FETCH_STATUS, **kw) -> int:
    """Store -> data/finance.json and build/report.json `finance`. Exit 0 ok, 2 on schema or scan-guard problems
    (nothing written), 3 when parity says 'review needed' (written; release waits for the reason, A5)."""
    from . import fin_facts
    from .facts import dumps, write_if_changed
    finance_path = Path(finance_path) if finance_path else fin_facts.FINANCE
    report_path = Path(report_path) if report_path else ROOT / "build" / "report.json"
    fin, extras = fin_facts.build(store, cfg, status_path=status_path, **kw)
    errors = validate(fin)
    guard = [p for p in extras["problems"] if "scan-values" in p or "award-source" in p or "cites no" in p]
    if errors or guard:
        for p in (errors + guard)[:20]:
            print("  problem:", p)
        print(f"collector fin: {len(errors)} schema errors, {len(guard)} scan-guard problems; nothing written")
        return 2
    changed = write_if_changed(finance_path, dumps(fin))
    block = fin_facts.report_block(fin, extras)
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    report["finance"] = block
    write_if_changed(report_path, dumps(report))
    c = fin["coverage"]
    print(f"collector fin: {c['n_total']} solicitations, {c['n_docs']} documents ({c['n_docs_scanned']} scanned), "
          f"bid tabs read {c['n_tab_read']} of {c['n_bid_tab_links']}; parity {block['parity']['status']}; "
          f"finance.json {'changed' if changed else 'unchanged'}")
    for p in extras["problems"]:
        print("  note:", p)
    return 3 if block["parity"]["status"] != "ok" else 0


def reason_class(detail: str) -> str:
    """A census detail without its page and quoted text: "layout: words, not one amount, in the Total column"."""
    head, _, rest = detail.partition(": ")
    if head != "layout":
        return head
    return head + ": " + re.split(r" on page|: '|: \"| for '", rest)[0]


def census_text(fin: dict, extras: dict) -> str:
    """F5b: each bid tab's layout class and the award-letter scan count."""
    out = ["bid tabs (archive order): class | detail | solicitation | url"]
    counts: dict[str, int] = {}
    for c in extras["census"]:
        counts[c.cls] = counts.get(c.cls, 0) + 1
        out.append(f"  {c.cls:<9} | {c.detail} | {c.solicitation} | {c.url}")
    cov = fin["coverage"]
    shared = {c.url for c in extras["census"] if c.detail.startswith("shared_url")}
    out.append(f"bid-tab links (per row): {sum(counts.values())}, unique URLs: {len({c.url for c in extras['census']})}"
               f" (shared URLs: {len(shared)})")
    out.append("layout classes (per row link): " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    why: dict[str, int] = {}
    for c in extras["census"]:
        if c.cls != "lump_sum":
            why[reason_class(c.detail)] = why.get(reason_class(c.detail), 0) + 1
    out.append("not read, by detail: " + "; ".join(f"{k} {v}" for k, v in sorted(why.items(), key=lambda kv: -kv[1])))
    out.append(f"solicitations: {cov['n_total']}; with a bid tab: {cov['n_bid_tab_links']}; tab read (lump_sum): "
               f"{cov['n_tab_read']}; not read: {json.dumps(cov['n_tab_not_read'], sort_keys=True)}")
    out.append(f"award letters: {cov['n_award_letters']}, scanned: {cov['n_award_scanned']}; documents: "
               f"{cov['n_docs']}, scanned: {cov['n_docs_scanned']}; by status: "
               f"{json.dumps(extras['docs_by_status'], sort_keys=True)}")
    return "\n".join(out)


def cmd_census(store: Store, cfg: FinanceConfig, status_path: Path = FETCH_STATUS, **kw) -> int:
    from . import fin_facts
    fin, extras = fin_facts.build(store, cfg, status_path=status_path, **kw)
    print(census_text(fin, extras))
    return 0


def main(argv=None) -> int:
    import argparse
    import sys

    from . import fin_config
    from .store import MANIFEST
    ap = argparse.ArgumentParser(prog="python -m collector fin")
    ap.add_argument("command", choices=["fetch", "build", "census"])
    args = ap.parse_args(argv)
    cfg = fin_config.load()
    store = Store(MANIFEST)
    if args.command == "fetch":
        print(f"collector fin: fetch {cfg.archive_url} and its documents (10 s between requests per host)", flush=True)
        log = cmd_fetch(store, cfg)
        print(json.dumps({k: v for k, v in log.items() if k != "fetch_log"}, indent=1))
        if log["stopped"]:
            print(f"collector fin: STOPPED, not retried: {log['stopped']}", file=sys.stderr)
            return 2
        return 2 if log["failures"] else 0
    if args.command == "census":
        return cmd_census(store, cfg)
    return cmd_build(store, cfg)
