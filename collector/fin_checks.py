"""Finance checks (architecture A4, A5): the scan guard, the awardee match, coverage and coverage parity.

Slice 1b: subtotal reconciliation (`reconcile`) and the edition compare (`edition_compare`). No sum over budget
lines exists outside this module (lint, budget-reconcile/*).

- scan-values/*: a value of any kind (amount, name, date) comes only from a source whose text_layer is `text`;
  a document whose URL more than one archive row links (shared_by) is never read (award-source/*). `unreadable` is
  the gate the adapters pass through; `scan_guard` re-checks a whole finance.json and the build fails on any problem.
- award-source/*: `awardee_match` compares names after one normalisation only.
- coverage-count/*: `coverage` is the one function every page and the report read.
"""
from __future__ import annotations

import re

from .config import FIN_PARITY_HIGH, FIN_PARITY_LOW, FIN_PARITY_MIN_ROWS

NOT_STATED = "not stated"
# bid_tab.not_read_reason (schema enum): not_fetched = a dead link or a link-only host (Bonfire, off the allowlist)
# unreadable = fetched, but the PDF could not be inspected (pdfinfo/pdftotext failed or timed out); not a scan
NOT_READ_REASONS = ("layout", "scan", "shared_url", "not_pdf", "not_fetched", "unreadable")
AWARD_LETTER_STAGES = ("award_letter", "partial_award")


# ------------------------------------------------------------------ scan guard
def unreadable(document: dict, source: dict | None) -> str | None:
    """Why no value may be read from this document ('shared_url' | 'scan' | 'not_fetched' | 'unreadable'), or None
    if it may."""
    if document.get("shared_by"):
        return "shared_url"
    if source is None or document.get("status") != "fetched":
        return "not_fetched"
    if source.get("text_layer") == "unreadable":
        return "unreadable"
    if source.get("text_layer") != "text":
        return "scan"
    return None


def value_sources(fin: dict):
    """Every value in finance.json with the source it cites: (where, source_id)."""
    docs = {d["id"]: d for d in fin["documents"]}
    for s in fin["solicitations"]:
        if s.get("department"):
            yield f"{s['id']}.department", s["department"]["source_id"]
        t = s.get("bid_tab")
        if not t:
            continue
        doc = docs.get(t["document_id"], {})
        has_value = (t["bidders"] or any(t.get(k) for k in ("project_text", "bid_date_text", "awardee_text",
                                                             "award_date_text")))
        if has_value:
            yield f"{s['id']}.bid_tab", doc.get("source_id")
    for b in fin.get("books", []):
        yield f"book {b['id']}", b["source_id"]


def scan_guard(fin: dict) -> list[str]:
    """Problems (empty = pass): a value citing a non-text source, a missing source, or a shared document."""
    src = {s["id"]: s for s in fin["sources"]}
    docs = {d["id"]: d for d in fin["documents"]}
    problems = []
    for where, sid in value_sources(fin):
        s = src.get(sid)
        if s is None:
            problems.append(f"{where}: cites no known source ({sid})")
        elif s["text_layer"] != "text":
            problems.append(f"{where}: value from a {s['text_layer']!r} source {sid} (scan-values)")
    for s in fin["solicitations"]:
        t = s.get("bid_tab")
        if t and t["tab_type"] == "lump_sum" and docs.get(t["document_id"], {}).get("shared_by"):
            problems.append(f"{s['id']}: values from a shared URL {t['document_id']} (award-source)")
        if t and t["document_id"] not in s["document_ids"]:
            problems.append(f"{s['id']}: bid tab {t['document_id']} is not one of its documents")
    return problems


# ------------------------------------------------------------------ awardee match
def norm_name(s: str) -> str:
    """The one normalisation: casefold, "_" removed, whitespace collapsed, no spaces around "&", end punctuation
    stripped."""
    s = s.replace("_", " ").casefold()
    s = " ".join(s.split())
    s = re.sub(r"\s*&\s*", "&", s)
    return s.strip(" .,;:")


def awardee_match(awardee_text: str | None, bidder_names: list[str]) -> str:
    if not awardee_text or not norm_name(awardee_text):
        return "none_named"
    key = norm_name(awardee_text)
    hits = [i for i, n in enumerate(bidder_names, start=1) if norm_name(n) == key]
    if len(hits) == 1:
        return f"bidder:{hits[0]}"
    return "ambiguous" if hits else "not_a_listed_bidder"


# ------------------------------------------------------------------ budget reconciliation (budget-reconcile/*)
RECONCILE_STATES = ("exact", "within_rounding", "does_not_add_up", "not_checked")
NOT_CHECKED = "not_checked"      # a held total or a total over a held line: we could not read it, not a book error


def rounding_bound(n: int) -> int:
    """Largest |printed - sum| that rounding alone explains for n detail lines each printed to the dollar
    (ADR 0002 point 4): floor((n + 1) / 2)."""
    return (n + 1) // 2


def rounded_cells(scope: list[dict], i: int) -> int:
    """n for column i's rounding bound: the scope lines with a printed amount there. A "-" is an exact 0 and a blank
    cell is not printed: neither can carry a rounding slip (budget-reconcile/rounding-n-counts-dashes)."""
    return sum(1 for x in scope if x["cells"][i]["dollars"] is not None and x["cells"][i]["as_printed"] != "-")


def check_total(line: dict, scope: list[dict]) -> dict:
    """The check of one subtotal or total over exactly its scope lines. Printed values are never altered. Per cell:
    printed = the total's dollars, sum = the scope lines' dollars in that column (blank or held = not added),
    diff = printed - sum (null when printed is null). State: not_checked when the total or a scope line is held (the
    line is then held too and shown as Not confirmed*, see reconcile; counted apart, never as a book error,
    budget-reconcile/held-counted-as-book-error); does_not_add_up when the scope is empty, a blank total has lines
    with dollars, or some |diff| exceeds its column's rounding bound (n = rounded_cells); within_rounding when every
    |diff| is within it and one is not 0; else exact."""
    per_cell, bounds = [], []
    for i, c in enumerate(line["cells"]):
        s = sum(x["cells"][i]["dollars"] or 0 for x in scope)
        p = c["dollars"]
        per_cell.append({"printed": p, "sum": s, "diff": None if p is None else p - s})
        bounds.append(rounding_bound(rounded_cells(scope, i)))
    if line["held"] or any(x["held"] for x in scope):
        state = NOT_CHECKED
    elif not scope or any(pc["printed"] is None and pc["sum"] != 0 for pc in per_cell):
        state = "does_not_add_up"
    elif all(pc["diff"] in (0, None) for pc in per_cell):
        state = "exact"
    elif all(pc["diff"] is None or abs(pc["diff"]) <= b for pc, b in zip(per_cell, bounds)):
        state = "within_rounding"
    else:
        state = "does_not_add_up"
    return {"state": state, "per_cell": per_cell}


SCOPE_HELD = "scope-held"


def reconcile(lines: list[dict]) -> dict:
    """Set `check` on every subtotal and total line (in place); returns the counts per state for the run report.
    A total whose scope holds a held line cannot be checked: it is held as well (check `scope-held`), so the page
    shows Not confirmed* instead of a state that would blame the book for a line we could not read."""
    by_id = {x["id"]: x for x in lines}
    counts = dict.fromkeys(RECONCILE_STATES, 0)
    for x in lines:
        if x["row_role"] == "detail":
            x["check"] = None
            continue
        scope = [by_id[i] for i in x["scope_line_ids"]]
        if not x["held"] and any(s["held"] for s in scope):
            x["held"] = SCOPE_HELD
        x["check"] = check_total(x, scope)
        counts[x["check"]["state"]] += 1
    return counts


def reconcile_counts(lines: list[dict]) -> dict:
    counts = dict.fromkeys(RECONCILE_STATES, 0)
    for x in lines:
        if x.get("check"):
            counts[x["check"]["state"]] += 1
    return counts


# ------------------------------------------------------------------ edition compare (budget-edition/*)
def edition_key(line: dict, cell: dict) -> tuple | None:
    """(fund_no, account code or label, heading, fiscal_year, kind); None for a line that is never compared: held,
    or with a heading taken from a total label (truncated and repeated, never a key)."""
    if line["held"] or line["heading_from_total"]:
        return None
    return (line["fund_no"], line["account_code"] or line["label_as_printed"], line["heading_as_printed"],
            cell["fiscal_year"], cell["kind"])


def edition_compare(lines: list[dict]) -> list[tuple[str, str]]:
    """Mark lines of different books that match on edition_key with different dollars: each lists the other in
    `edition_differs` (in place). A key that occurs more than once in one book is ambiguous and not compared. Lines are
    never merged and no value is changed. Returns the marked pairs, sorted."""
    keyed: dict[tuple, dict[str, list]] = {}
    for x in lines:
        for c in x["cells"]:
            k = edition_key(x, c)
            if k is not None:
                keyed.setdefault(k, {}).setdefault(x["book_id"], []).append((x, c))
    pairs = set()
    for per_book in keyed.values():
        if len(per_book) < 2 or any(len(v) > 1 for v in per_book.values()):
            continue
        items = [v[0] for v in per_book.values()]
        for a, ca in items:
            for b, cb in items:
                if a["book_id"] < b["book_id"] and ca["dollars"] != cb["dollars"]:
                    pairs.add((a["id"], b["id"]))
    by = {x["id"]: x for x in lines}
    for a, b in pairs:
        for x, other in ((by[a], b), (by[b], a)):
            if other not in x["edition_differs"]:
                x["edition_differs"] = sorted(x["edition_differs"] + [other])
    return sorted(pairs)


def parts_add_up(parts: list[int | None], total: int) -> bool:
    """Bid-tab blocks (total-parts): a bidder's printed base bid and alternates add up to its printed total, to the
    cent. A part that is not a well-formed amount (None) means it cannot be checked: False, the total is held."""
    return bool(parts) and None not in parts and sum(parts) == total


# ------------------------------------------------------------------ coverage and parity
def coverage(fin: dict) -> dict:
    """Live counts for every page and the report (schema coverage)."""
    sols, docs = fin["solicitations"], fin["documents"]
    tabs = [s["bid_tab"] for s in sols if s["bid_tab"]]
    not_read = dict.fromkeys(NOT_READ_REASONS, 0)
    for t in tabs:
        if t["tab_type"] == "not_read":
            not_read[t["not_read_reason"]] += 1
    awards = [d for d in docs if d["stage"] in AWARD_LETTER_STAGES]
    lines = fin.get("budget_lines", [])
    by: dict = {}
    for s in sols:
        dept = s["department"]["text"] if s["department"] else NOT_STATED
        year = str(s["year"]) if s["year"] else NOT_STATED
        c = by.setdefault(dept, {}).setdefault(year, {"rows": 0, "with_tab": 0, "tab_read": 0})
        c["rows"] += 1
        c["with_tab"] += s["bid_tab"] is not None
        c["tab_read"] += bool(s["bid_tab"] and s["bid_tab"]["tab_type"] == "lump_sum")
    return {
        "n_total": len(sols),
        "n_bid_tab_links": len(tabs),
        "n_tab_read": sum(t["tab_type"] == "lump_sum" for t in tabs),
        "n_tab_not_read": not_read,
        "n_award_letters": len(awards),
        "n_award_scanned": sum(d["scanned"] for d in awards),
        "n_docs": len(docs),
        "n_docs_scanned": sum(d["scanned"] for d in docs),
        "n_lines": len(lines),
        "n_books": len(fin.get("books", [])),
        "n_flag": sum(1 for x in lines if (x.get("check") or {}).get("state") == "does_not_add_up"),
        "by_department_year": {d: dict(sorted(y.items())) for d, y in sorted(by.items())},
    }


def parity(cov: dict, min_rows: int = FIN_PARITY_MIN_ROWS, low: float = FIN_PARITY_LOW,
           high: float = FIN_PARITY_HIGH) -> dict:
    """AC-F16 (A5): a department with at least `min_rows` rows whose tab_read share is below low x or above high x the
    overall share is flagged; any flag sets status 'review needed'. "not stated" is reported in its own entry and
    is not flagged: a department is known only from a read bid tab, so its share is 0 by construction."""
    rows = {d: sum(c["rows"] for c in ys.values()) for d, ys in cov["by_department_year"].items()}
    read = {d: sum(c["tab_read"] for c in ys.values()) for d, ys in cov["by_department_year"].items()}
    total = sum(rows.values())
    overall = (sum(read.values()) / total) if total else 0.0
    depts, flagged = [], []
    for d in sorted(rows):
        share = read[d] / rows[d] if rows[d] else 0.0
        entry = {"dept": d, "rows": rows[d], "tab_read_share": round(share, 4)}
        depts.append(entry)
        if d != NOT_STATED and rows[d] >= min_rows and overall and not (low * overall <= share <= high * overall):
            flagged.append(d)
    return {"rule": f"departments with at least {min_rows} rows whose bid-tab read share is outside "
                    f"{low}x-{high}x the overall share",
            "overall_share": round(overall, 4), "departments": depts, "flagged": flagged,
            "not_stated": next((e for e in depts if e["dept"] == NOT_STATED), None),
            "status": "review needed" if flagged else "ok"}
