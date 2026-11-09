"""Finance and contracts export (tasks F8, F15; architecture finance-contracts 6; spec AC-F13).

build/site/data/: solicitations.csv, bidders.csv, fin_documents.csv, budget_lines.csv (one row per line per cell),
budget_checks.csv (one row per checked cell of a subtotal or total line) and finance.json (the finance file as the
pages show it).

Rules, the same as the pages (sitegen/fin_views.py, budget_views.py):
- Every row carries `source_url`, `source_sha256`, `page` and `fetched_at` of the document that prints it (page empty
  for an HTML page such as the purchasing archive). finance.json rows carry `source_url` too.
- A held value (schema `held`, a bidder total the page shows as "Not confirmed*", a held budget line) is exported as
  null with the check that held it (`*_held_check`), never as a value; its printed text is null too.
- Values only from a text-layer source: a not-read bid tab exports no tab values, only its link and reason.
- Order by id, date or printed order only, never by an amount (neutrality, AC-F8). No computed column: the export
  carries no sum, share or difference of its own; budget_checks.csv reports the reconciliation fin_checks.py made.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from .export import _csv

SRC = ["source_url", "source_sha256", "page", "fetched_at"]
FIN_FILES = ("solicitations", "bidders", "fin_documents", "budget_lines", "budget_checks")

# Held solicitation fields (schema held.field) -> the solicitations.csv column they null. Any other held field fails
# the export (no held value may slip out under a column the export does not know).
SOL_HELD = {"department": "department", "department.text": "department", "bid_tab.awardee_text": "awardee_text",
            "bid_tab.bid_date_text": "bid_date_text", "bid_tab.award_date_text": "award_date_text",
            "bid_tab.project_text": "project_text"}
BIDDER_HELD = re.compile(r"bid_tab\.bidders\[(\d+)\]\.(?:total_cents|total_as_printed)")
TAB_VALUES = ("project_text", "bid_date_text", "bid_date_page", "awardee_text", "awardee_page", "award_date_text",
              "award_date_page")

_S = "stated"
_C = {"source_url": "derived: link to the source document the team fetched",
      "source_sha256": "derived: hash of the fetched file", "page": "derived: page of the source that prints it",
      "fetched_at": "derived: time the team fetched the file"}
_HELD = "derived: the check that held the value back (the value is then empty)"
# Provenance registry for the finance CSVs (architecture, "Invariant: derived vs stated"): every column says which it
# is; collector/tests/test_fin_export.py fails on an unregistered column.
FIN_PROVENANCE: dict[str, str] = {
    **{f"{f}.{k}": v for f in FIN_FILES for k, v in _C.items()},
    "solicitations.id": "derived: id", "solicitations.slug": "derived: from the title",
    "solicitations.title": _S, "solicitations.archive_date_text": _S,
    "solicitations.archive_date": "derived: archive_date_text read as a date",
    "solicitations.year": "derived: year of archive_date", "solicitations.number": _S,
    "solicitations.department": _S, "solicitations.department_held_check": _HELD,
    "solicitations.department_source_url": "derived: link to the document that prints the department",
    "solicitations.department_page": "derived: page of that document",
    "solicitations.document_ids": "derived: ids", "solicitations.bid_tab_document_id": "derived: id",
    "solicitations.bid_tab_source_url": "derived: link to the bid tab the values are read from",
    "solicitations.tab_type": "derived: whether the team read the bid tab",
    "solicitations.not_read_reason": "derived: why the bid tab was not read",
    "solicitations.project_text": _S, "solicitations.bid_date_text": _S, "solicitations.bid_date_page": _C["page"],
    "solicitations.awardee_text": _S, "solicitations.awardee_page": _C["page"],
    "solicitations.awardee_held_check": _HELD,
    "solicitations.awardee_match": "derived: awardee name compared with the listed bidders",
    "solicitations.award_date_text": _S, "solicitations.award_date_page": _C["page"],
    "solicitations.held_checks": "derived: every held field with the check that held it",
    "bidders.fact_id": "derived: id", "bidders.solicitation_id": "derived: id", "bidders.printed_order": _S,
    "bidders.name": _S, "bidders.total_as_printed": _S, "bidders.total_cents": "derived: total_as_printed in cents",
    "bidders.held_check": _HELD,
    "fin_documents.id": "derived: id", "fin_documents.solicitation_ids": "derived: archive rows that link it",
    "fin_documents.link_label": _S, "fin_documents.stage": "derived: fixed patterns on the link label",
    "fin_documents.status": "derived: what the fetch found", "fin_documents.scanned": "derived: no text layer, or a "
    "scanner's OCR", "fin_documents.shared": "derived: the same link listed by more than one solicitation",
    "fin_documents.doc_date_text": _S,
    "budget_lines.line_id": "derived: book, page and row", "budget_lines.book_id": "derived: id",
    "budget_lines.book_title": _S, "budget_lines.edition": "derived: from the book's title",
    "budget_lines.fund_no": _S, "budget_lines.fund_name": _S,
    "budget_lines.statement": "derived: page role (revenue, expenditure, fund balance)",
    "budget_lines.heading_as_printed": _S, "budget_lines.department": "derived: the expenditure heading",
    "budget_lines.account_code": _S, "budget_lines.label_as_printed": _S,
    "budget_lines.row_role": "derived: detail, subtotal or total from the row's place and label",
    "budget_lines.tags": "derived: fixed patterns on the label", "budget_lines.column": "derived: column position",
    "budget_lines.header_as_printed": _S, "budget_lines.fiscal_year": "derived: from the header",
    "budget_lines.kind": "derived: from the header (actual, amended, adopted, projected)",
    "budget_lines.as_printed": _S, "budget_lines.dollars": "derived: as_printed in whole dollars ('-' is 0)",
    "budget_lines.held_check": _HELD,
    "budget_lines.edition_differs": "derived: lines in the other book with the same key and different dollars",
    "budget_checks.line_id": "derived: book, page and row", "budget_checks.book_id": "derived: id",
    "budget_checks.fund_no": _S, "budget_checks.label_as_printed": _S,
    "budget_checks.row_role": "derived: subtotal or total", "budget_checks.state": "derived: the team's "
    "reconciliation (exact, within_rounding, does_not_add_up, not_checked)",
    "budget_checks.column": "derived: column position", "budget_checks.header_as_printed": _S,
    "budget_checks.fiscal_year": "derived: from the header", "budget_checks.kind": "derived: from the header",
    "budget_checks.printed": "derived: the printed total in whole dollars",
    "budget_checks.sum": "derived: sum of the scope lines' dollars in this column",
    "budget_checks.diff": "derived: printed minus sum",
    "budget_checks.scope_lines": "derived: number of detail lines checked against",
    "budget_checks.held_check": _HELD,
}

COLS = {
    "solicitations": ["id", "slug", "title", "archive_date_text", "archive_date", "year", "number", "department",
                      "department_held_check", "department_source_url", "department_page", "document_ids",
                      "bid_tab_document_id", "bid_tab_source_url", "tab_type", "not_read_reason", "project_text",
                      "bid_date_text", "bid_date_page", "awardee_text", "awardee_page", "awardee_held_check",
                      "awardee_match", "award_date_text", "award_date_page", "held_checks"] + SRC,
    "bidders": ["fact_id", "solicitation_id", "printed_order", "name", "total_as_printed", "total_cents",
                "held_check"] + SRC,
    "fin_documents": ["id", "solicitation_ids", "link_label", "stage", "status", "scanned", "shared",
                      "doc_date_text"] + SRC,
    "budget_lines": ["line_id", "book_id", "book_title", "edition", "fund_no", "fund_name", "statement",
                     "heading_as_printed", "department", "account_code", "label_as_printed", "row_role", "tags",
                     "column", "header_as_printed", "fiscal_year", "kind", "as_printed", "dollars", "held_check",
                     "edition_differs"] + SRC,
    "budget_checks": ["line_id", "book_id", "fund_no", "label_as_printed", "row_role", "state", "column",
                      "header_as_printed", "fiscal_year", "kind", "printed", "sum", "diff", "scope_lines",
                      "held_check"] + SRC,
}


class ExportError(Exception):
    pass


def _sol_held(sol: dict) -> tuple[dict[str, str], dict[int, str]]:
    """({solicitations.csv column: check}, {bidder index: check}) for one solicitation's held fields."""
    cols, bidders = {}, {}
    for h in sol["held"]:
        m = BIDDER_HELD.fullmatch(h["field"])
        if m:
            bidders[int(m.group(1))] = h["check"]
        elif h["field"] in SOL_HELD:
            cols[SOL_HELD[h["field"]]] = h["check"]
        else:
            raise ExportError(f"solicitation {sol['id']}: held field {h['field']!r} has no export rule")
    return cols, bidders


def bidder_held(sol: dict, i: int, b: dict, held_idx: dict[int, str]) -> str | None:
    """The check that holds bidder i's total, as the pages decide it (fin_views._tab_state): a held entry, or a total
    the reader left null (amount-format). None: the total is shown."""
    if i in held_idx:
        return held_idx[i]
    if b["total_cents"] is None or b["total_as_printed"] is None:
        return "amount-format"
    return None


def public_finance(fin: dict) -> dict:
    """finance.json as the pages show it: held values null (a held bidder total loses its printed text too), a
    not-read tab carries no values, and every solicitation, bidder, document, book and budget line its source_url."""
    out = copy.deepcopy(fin)
    out.pop("fixture", None)
    sources = {s["id"]: s for s in fin["sources"]}
    docs = {d["id"]: d for d in fin["documents"]}

    def url(source_id):
        return sources[source_id]["url"] if source_id in sources else None

    for sol in out["solicitations"]:
        cols, held_idx = _sol_held(sol)
        sol["source_url"] = url(sol["archive_source_id"])
        if "department" in cols:
            sol["department"] = None
        tab = sol["bid_tab"]
        if tab is None:
            continue
        doc = docs[tab["document_id"]]
        tab["source_url"] = doc["url"]
        if tab["tab_type"] != "lump_sum":
            for k in TAB_VALUES:
                tab[k] = None
            tab["bidders"] = []
            continue
        for col in ("awardee_text", "bid_date_text", "award_date_text", "project_text"):
            if col in cols:
                tab[col] = None
        for i, b in enumerate(tab["bidders"]):
            check = bidder_held(sol, i, b, held_idx)
            b["held_check"] = check
            b["source_url"] = doc["url"]
            if check is not None:
                b["total_as_printed"] = None
                b["total_cents"] = None
    for d in out["documents"]:
        d["source_url"] = d["url"]
    for b in out["books"]:
        b["source_url"] = url(b["source_id"])
    books = {b["id"]: b for b in fin["books"]}
    for x in out["budget_lines"]:
        x["source_url"] = url(books[x["book_id"]]["source_id"])
        if x["held"]:
            for c in x["cells"]:
                c["as_printed"] = None
                c["dollars"] = None
            if x["check"]:
                for pc in x["check"]["per_cell"]:
                    pc["printed"] = None
                    pc["diff"] = None
    return out


def tables(fin: dict) -> dict[str, str]:
    """The five finance CSVs from the PUBLIC finance dict (public_finance)."""
    sources = {s["id"]: s for s in fin["sources"]}
    docs = {d["id"]: d for d in fin["documents"]}
    books = {b["id"]: b for b in fin["books"]}

    def cite(source_id, page, url=None):
        s = sources.get(source_id) or {}
        return {"source_url": url or s.get("url"), "source_sha256": s.get("sha256"), "page": page,
                "fetched_at": s.get("fetched_at")}

    sols, bidders = [], []
    for sol in sorted(fin["solicitations"], key=lambda s: s["id"]):
        cols, _ = _sol_held(sol)
        tab = sol["bid_tab"] or {}
        dep = sol["department"] or {}
        tab_doc = docs.get(tab.get("document_id")) or {}
        row = {"id": sol["id"], "slug": sol["slug"], "title": sol["title"],
               "archive_date_text": sol["archive_date_text"], "archive_date": sol["archive_date"],
               "year": sol["year"], "number": sol["number"], "department": dep.get("text"),
               "department_held_check": cols.get("department"),
               "department_source_url": url_of(sources, dep.get("source_id")), "department_page": dep.get("page"),
               "document_ids": "; ".join(sol["document_ids"]), "bid_tab_document_id": tab.get("document_id"),
               "bid_tab_source_url": tab_doc.get("url"), "tab_type": tab.get("tab_type"),
               "not_read_reason": tab.get("not_read_reason"),
               **{k: tab.get(k) for k in TAB_VALUES}, "awardee_held_check": cols.get("awardee_text"),
               "awardee_match": tab.get("awardee_match"),
               "held_checks": "; ".join(f"{h['field']}: {h['check']}" for h in sol["held"]),
               **cite(sol["archive_source_id"], None)}
        sols.append(row)
        for b in sorted(tab.get("bidders") or [], key=lambda b: b["printed_order"]):   # printed order (AC-F8)
            bidders.append({"fact_id": f"{sol['id']}/bidder/{b['printed_order']}", "solicitation_id": sol["id"],
                            "printed_order": b["printed_order"], "name": b["name"],
                            "total_as_printed": b["total_as_printed"], "total_cents": b["total_cents"],
                            "held_check": b.get("held_check"), **cite(tab_doc.get("source_id"), b["page"])})
    shared_by = {}
    for sol in fin["solicitations"]:
        for did in sol["document_ids"]:
            shared_by.setdefault(did, []).append(sol["id"])
    documents = [{"id": d["id"], "solicitation_ids": "; ".join(sorted(shared_by.get(d["id"], []))),
                  "link_label": d["link_label"], "stage": d["stage"], "status": d["status"], "scanned": d["scanned"],
                  "shared": bool(d["shared_by"]), "doc_date_text": d["doc_date_text"],
                  **cite(d["source_id"], d["doc_date_page"], url=d["url"]),
                  # a document with no bytes (not a PDF, dead at fetch) keeps the fetch date the archive gave it
                  **({"fetched_at": d["fetched_at"]} if d["source_id"] is None else {})}
                 for d in sorted(fin["documents"], key=lambda d: d["id"])]
    lines, checks = [], []
    for x in sorted(fin["budget_lines"], key=lambda x: (x["book_id"], x["page"], _row_no(x["id"]))):
        book = books[x["book_id"]]
        c = cite(book["source_id"], x["page"])
        for n, cell in enumerate(x["cells"], 1):
            lines.append({"line_id": x["id"], "book_id": x["book_id"], "book_title": book["title"],
                          "edition": x["edition"], "fund_no": x["fund_no"], "fund_name": x["fund_name"],
                          "statement": x["statement"], "heading_as_printed": x["heading_as_printed"],
                          "department": x["department"], "account_code": x["account_code"],
                          "label_as_printed": x["label_as_printed"], "row_role": x["row_role"],
                          "tags": "; ".join(x["tags"]), "column": n, "header_as_printed": cell["header_as_printed"],
                          "fiscal_year": cell["fiscal_year"], "kind": cell["kind"],
                          "as_printed": cell["as_printed"], "dollars": cell["dollars"], "held_check": x["held"],
                          "edition_differs": "; ".join(x["edition_differs"]), **c})
        if x["check"]:
            for n, (cell, pc) in enumerate(zip(x["cells"], x["check"]["per_cell"]), 1):
                checks.append({"line_id": x["id"], "book_id": x["book_id"], "fund_no": x["fund_no"],
                               "label_as_printed": x["label_as_printed"], "row_role": x["row_role"],
                               "state": x["check"]["state"], "column": n,
                               "header_as_printed": cell["header_as_printed"], "fiscal_year": cell["fiscal_year"],
                               "kind": cell["kind"], "printed": pc["printed"], "sum": pc["sum"], "diff": pc["diff"],
                               "scope_lines": len(x["scope_line_ids"]), "held_check": x["held"], **c})
    return {"solicitations": _csv(sols, COLS["solicitations"]), "bidders": _csv(bidders, COLS["bidders"]),
            "fin_documents": _csv(documents, COLS["fin_documents"]),
            "budget_lines": _csv(lines, COLS["budget_lines"]), "budget_checks": _csv(checks, COLS["budget_checks"])}


def url_of(sources: dict, source_id: str | None) -> str | None:
    return sources[source_id]["url"] if source_id in sources else None


def _row_no(line_id: str) -> int:
    m = re.search(r"/r(\d+)$", line_id)
    return int(m.group(1)) if m else 0


def export_finance(fin: dict, data_dir: Path) -> list[Path]:
    """Write finance.json and the five CSVs into `data_dir` (build/site/data)."""
    if fin.get("fixture"):
        raise ExportError("a FIXTURE finance file is never exported")
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    pub = public_finance(fin)
    written = []
    p = data_dir / "finance.json"
    p.write_text(json.dumps(pub, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append(p)
    for name, text in tables(pub).items():
        p = data_dir / f"{name}.csv"
        p.write_text(text, encoding="utf-8")
        written.append(p)
    return written
