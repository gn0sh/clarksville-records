"""Assemble data/finance.json from the store (task F5c, architecture A3, schema/finance.schema.json).

Deterministic: lists sorted by id, keys sorted, ids from content (src-<sha12>, doc-<sha1(url)[:10]>, sol-<slug>), so
a run with nothing new writes byte-identical output. Values come only through the scan guard
(fin_checks.unreadable) and the bid-tab adapter; a held value is null and listed with its check.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import fin_budget, fin_checks
from .extract import extract_pages, image_only_pages
from .fin_archive import parse_archive
from .fin_bidtab import read_bidtab
from .fin_config import FinanceConfig
from .fin_run import ARCHIVE_KIND, load_status
from .pdfwords import pdf_words

ROOT = Path(__file__).resolve().parent.parent
FINANCE = ROOT / "data" / "finance.json"
META_CACHE = ROOT / "data" / "text" / "fin"
SCHEMA_VERSION = "1.0"


# ------------------------------------------------------------------ per-file facts (cached by hash)
def pdf_meta(pdf: Path, cfg: FinanceConfig, cache_dir: Path | None = META_CACHE) -> dict:
    """{pages, text_layer, creator}. text_layer: 'none' when every page is image-only; 'ocr' when the text comes from
    a scanner (Creator/Producer matches finance.yml scan_producers); else 'text'."""
    cache = Path(cache_dir) / f"{pdf.stem}.json" if cache_dir else None
    if cache and cache.exists():
        info = json.loads(cache.read_text(encoding="utf-8"))
    else:
        out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True).stdout.decode("utf-8", "replace")
        tags = dict(re.findall(r"^(Creator|Producer|Pages):\s*(.*?)\s*$", out, re.M))
        pages = extract_pages(pdf)
        info = {"pages": int(tags["Pages"]) if tags.get("Pages", "").isdigit() else len(pages),
                "image_only": len(image_only_pages(pages)) == len(pages),
                "creator": tags.get("Creator") or None, "producer": tags.get("Producer") or None}
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(info, sort_keys=True), encoding="utf-8")
    made_by = " ".join(x for x in (info["creator"], info["producer"]) if x)
    if info["image_only"]:
        layer = "none"
    elif any(rx.search(made_by) for rx in cfg.scan_producers):
        layer = "ocr"
    else:
        layer = "text"
    return {"pages": max(info["pages"], 1), "text_layer": layer, "creator": info["creator"] or info["producer"]}


def source_record(entry: dict, meta: dict | None) -> dict:
    html = entry["kind"] == ARCHIVE_KIND
    return {"id": f"src-{entry['sha256'][:12]}", "url": entry["url"], "sha256": entry["sha256"], "kind": entry["kind"],
            "fetched_at": (entry["first_fetched_at"] or "")[:10],
            "pages": None if html else meta["pages"], "text_layer": "text" if html else meta["text_layer"],
            "content_type": "text/html" if html else "application/pdf",
            "creator": None if html else meta["creator"]}


def doc_id(url: str) -> str:
    return "doc-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-") or "untitled"


def solicitation_ids(rows) -> list[str]:
    """sol-<slug>; every row of a colliding slug gets -<sha1(first doc url)[:6]> (order-independent)."""
    slugs = [slugify(r.title) for r in rows]
    out = []
    for r, s in zip(rows, slugs):
        if slugs.count(s) > 1:
            first = r.links[0].url if r.links else f"row-{r.row}"
            s = f"{s}-{hashlib.sha1(first.encode('utf-8')).hexdigest()[:6]}"
        out.append(f"sol-{s}")
    if len(set(out)) != len(out):
        raise ValueError("solicitation ids collide after the hash suffix")
    return out


# ------------------------------------------------------------------ the build
@dataclass
class Census:
    """Per bid-tab document: its class for `fin census` (lump_sum / not_read / scan) and why."""
    url: str
    solicitation: str
    cls: str
    detail: str


def _tab_not_read(document_id: str, reason: str) -> dict:
    return {"document_id": document_id, "tab_type": "not_read", "not_read_reason": reason, "project_text": None,
            "bid_date_text": None, "bid_date_page": None, "awardee_text": None, "awardee_page": None,
            "award_date_text": None, "award_date_page": None, "awardee_match": None, "bidders": []}


def build_budget(store, cfg: FinanceConfig, sources: dict, problems: list, meta_cache: Path | None = META_CACHE,
                 book_words=pdf_words) -> tuple[list[dict], list[dict]]:
    """Budget books in the store -> (books, budget_lines with checks and edition marks) (tasks F10-F12). A book not
    in the store, or without a text layer, is reported in `problems` and not read; both are guard problems
    (fin_run.GUARD_KEYS), so the build writes nothing rather than drop a book's lines (provenance/book-missing)."""
    books, lines = [], []
    for spec in cfg.budget.books:
        e = store.latest(spec.url)
        if not e or not store.has_bytes(e["sha256"]):
            problems.append(f"book {spec.id}: not in the store, its lines would be dropped (provenance/book-missing): "
                            f"run `python -m collector fin fetch` ({spec.url})")
            continue
        pdf = store.path_for(e["sha256"])
        src = source_record(e, pdf_meta(pdf, cfg, meta_cache))
        src = sources.setdefault(src["id"], src)
        if src["text_layer"] != "text":
            problems.append(f"book {spec.id}: {src['text_layer']} source {src['id']}, not read (scan-values)")
            continue
        read = fin_budget.read_book(book_words(pdf, spec.first_page, spec.last_page), spec, cfg.budget)
        books.append({"id": spec.id, "title": spec.title, "edition": spec.edition, "fiscal_year": spec.fiscal_year,
                      "source_id": src["id"], "pages_read": read.pages_read, "columns": read.columns})
        lines += fin_budget.to_records(read, cfg.budget)
    fin_checks.reconcile(lines)
    fin_checks.edition_compare(lines)
    return sorted(books, key=lambda b: b["id"]), sorted(lines, key=lambda x: x["id"])


def build(store, cfg: FinanceConfig, status_path: Path | None = None, meta_cache: Path | None = META_CACHE,
          words_for=pdf_words, book_words=pdf_words) -> tuple[dict, dict]:
    """-> (finance facts, report extras {census, problems, docs_by_status})."""
    arch = store.latest(cfg.archive_url)
    if not arch or not store.has_bytes(arch["sha256"]):
        raise FileNotFoundError(f"{cfg.archive_url} is not in the store: run `python -m collector fin fetch` first")
    rows = parse_archive(store.path_for(arch["sha256"]).read_text(encoding="utf-8"), cfg)
    status = load_status(status_path) if status_path else load_status()
    sources = {}
    arch_src = source_record(arch, None)
    sources[arch_src["id"]] = arch_src
    sol_ids = solicitation_ids(rows)
    linked_by: dict[str, list[str]] = {}
    for sid, r in zip(sol_ids, rows):
        for lk in r.links:
            if sid not in linked_by.setdefault(lk.url, []):
                linked_by[lk.url].append(sid)
    problems: list[str] = []
    documents: dict[str, dict] = {}
    for r in rows:
        for lk in r.links:
            did = doc_id(lk.url)
            if did in documents:
                continue
            e = store.latest(lk.url)
            st = status.get(lk.url)
            src = None
            if e and e["kind"] != ARCHIVE_KIND and store.has_bytes(e["sha256"]):
                src = source_record(e, pdf_meta(store.path_for(e["sha256"]), cfg, meta_cache))
                sources.setdefault(src["id"], src)
                src = sources[src["id"]]
                state, when = "fetched", src["fetched_at"]
            elif st:
                state, when = st["status"], (st["date"] if st["status"] != "link_only" else None)
            else:
                state, when = "link_only", None
                problems.append(f"{lk.url}: not fetched yet (run `python -m collector fin fetch`)")
            shared = sorted(linked_by[lk.url]) if len(linked_by[lk.url]) > 1 else []
            documents[did] = {"id": did, "url": lk.url, "link_label": lk.label, "stage": lk.stage,
                              "source_id": src["id"] if src else None, "status": state,
                              # a scanner's OCR text is scanned too: no value is read from it (scan-values/*)
                              "scanned": bool(src and src["text_layer"] != "text"),
                              "doc_date_text": None, "doc_date_page": None, "shared_by": shared, "fetched_at": when}
    census: list[Census] = []
    solicitations = []
    for sid, r in zip(sol_ids, rows):
        held = [{"field": "archive_date", "check": "date-unparsed"}] if r.date_held else []
        reads = []                                     # (document id, BidTabRead) for lump-sum tabs, archive order
        first_not_read = None
        for lk in r.links:
            if lk.stage != "bid_tab":
                continue
            d = documents[doc_id(lk.url)]
            why = fin_checks.unreadable(d, sources.get(d["source_id"]))
            if why is None:
                res = read_bidtab(words_for(store.path_for(sources[d["source_id"]]["sha256"])), cfg.bidtab)
                if res.tab_type == "lump_sum":
                    reads.append((d["id"], res))
                    census.append(Census(lk.url, sid, "lump_sum", f"{res.layout}: {len(res.bidders)} bidders"))
                    continue
                why, detail = "layout", res.reason
            else:
                detail = {"shared_url": f"URL linked from {len(d['shared_by'])} rows",
                          "scan": f"text layer {sources[d['source_id']]['text_layer']}" if d["source_id"] else "",
                          "not_fetched": f"document {d['status']}"}[why]
            if why == "not_fetched" and d["status"] == "not_pdf":
                why, detail = "not_pdf", "a .docx link or non-PDF bytes: not read"
            # a dead or link-only tab is not_fetched, never "layout": we have no bytes to judge a layout by
            # (award-source/not-read-reason-misstated)
            census.append(Census(lk.url, sid, "scan" if why == "scan" else "not_read", f"{why}: {detail}"))
            first_not_read = first_not_read or (d["id"], why)
        bid_tab = department = differ = None
        if reads:
            did, res = reads[0]
            names = [b.name for b in res.bidders]
            f = res.fields
            bid_tab = {"document_id": did, "tab_type": "lump_sum", "not_read_reason": None,
                       "project_text": f.get("project", (None,))[0], "bid_date_text": f.get("bid_date", (None,))[0],
                       "bid_date_page": f["bid_date"][1] if "bid_date" in f else None,
                       "awardee_text": f.get("awardee", (None,))[0],
                       "awardee_page": f["awardee"][1] if "awardee" in f else None,
                       "award_date_text": f.get("award_date", (None,))[0],
                       "award_date_page": f["award_date"][1] if "award_date" in f else None,
                       "awardee_match": fin_checks.awardee_match(f.get("awardee", (None,))[0], names),
                       "bidders": [{"printed_order": b.printed_order, "name": b.name,
                                    "total_as_printed": b.total_as_printed, "total_cents": b.total_cents,
                                    "page": b.page} for b in res.bidders]}
            held += [{"field": p, "check": c} for p, c in res.held]
            if "department" in f:
                department = {"text": f["department"][0], "source_id": documents[did]["source_id"],
                              "page": f["department"][1]}
            if len(reads) > 1:
                fields = []
                aw = {fin_checks.norm_name(x.fields.get("awardee", ("",))[0]) for _, x in reads}
                if len(aw) > 1:
                    fields.append("awardee")
                if len({len(x.bidders) for _, x in reads}) > 1:
                    fields.append("n_bidders")
                if fields:
                    differ = {"fields": fields, "document_ids": [d for d, _ in reads]}
        elif first_not_read:
            bid_tab = _tab_not_read(*first_not_read)
        solicitations.append({
            "id": sid, "slug": sid[4:], "title": r.title, "archive_date_text": r.date_text,
            "archive_date": r.date, "archive_status": r.status, "year": int(r.date[:4]) if r.date else None,
            "department": department, "number": None, "document_ids": [doc_id(lk.url) for lk in r.links],
            # this row's own link text: a URL linked from several rows has one document but a label per row
            "document_labels": [lk.label for lk in r.links],                 # doc-completeness/label-not-verbatim
            "bid_tab": bid_tab, "documents_differ": differ, "held": held, "row": r.row,
            "archive_source_id": arch_src["id"]})
    books, budget_lines = build_budget(store, cfg, sources, problems, meta_cache, book_words)
    fin = {"schema_version": SCHEMA_VERSION,
           "sources": sorted(sources.values(), key=lambda s: s["id"]),
           "solicitations": sorted(solicitations, key=lambda s: s["id"]),
           "documents": sorted(documents.values(), key=lambda d: d["id"]),
           "books": books, "budget_lines": budget_lines}
    fin["coverage"] = fin_checks.coverage(fin)
    problems += fin_checks.scan_guard(fin)
    by_status: dict[str, int] = {}
    for d in fin["documents"]:
        by_status[d["status"]] = by_status.get(d["status"], 0) + 1
    return fin, {"census": census, "problems": problems, "docs_by_status": dict(sorted(by_status.items()))}


def report_block(fin: dict, extras: dict) -> dict:
    """build/report.json `finance` (A5)."""
    held = [{"id": s["id"], **h} for s in fin["solicitations"] for h in s["held"]]
    held += [{"id": x["id"], "field": "cells", "check": x["held"]} for x in fin["budget_lines"] if x["held"]]
    return {"coverage": fin["coverage"], "parity": fin_checks.parity(fin["coverage"]),
            "reconcile": fin_checks.reconcile_counts(fin["budget_lines"]), "budget": budget_summary(fin),
            "held": held, "docs_by_status": extras["docs_by_status"], "problems": extras["problems"]}


def budget_summary(fin: dict) -> dict:
    """Per book: lines, funds, reconcile counts, held lines, lines marked edition_differs (run report, F11-F12)."""
    out = {}
    for b in fin["books"]:
        lines = [x for x in fin["budget_lines"] if x["book_id"] == b["id"]]
        out[b["id"]] = {"lines": len(lines), "funds": sorted({x["fund_no"] for x in lines}),
                        "reconcile": fin_checks.reconcile_counts(lines),
                        "held": sum(1 for x in lines if x["held"]),
                        "edition_differs": sum(1 for x in lines if x["edition_differs"])}
    return out
