"""Adapter 3: budget-book PDF -> budget lines (task F10, architecture A2 "Adapter 3" and "Row roles and scopes").

Deterministic, on word positions from `pdftotext -bbox` (pdfwords). Every title, word list and row rule comes from
finance.yml `budget` (fin_config.BudgetRules); the code holds no locality literal.

- Page role by an exact title line (revenue, expenditure, fund_balance = the consolidated page); any other page is
  not read. On a fund_balance page only rows matching `fund_balance_labels` are read, and their fund is the fund of
  the next statement page.
- Column bands from the header block under the title: words of one header line closer than BAND_GAP form a phrase,
  phrases of the header lines that overlap in x form one band, read top to bottom ("FY 2026" / "Amended" / "Budget").
  A band's kind is its first kind word, its fiscal year from `year`; a band with an ignore word (derived columns) is
  only a position. Any other header band fails the book (BookLayoutError).
- A word is a cell token when its right edge is at or right of the first band's left edge; band j holds the tokens
  whose right edge lies in [band j left edge, band j+1 left edge). A value band with two tokens, a token that is not
  an amount, or a digit token off its column's right edge by more than ALIGN_TOL holds the line (check
  `column-align`): its dollars are null and it is still listed. "-" is 0 as printed; no token is a blank cell (null).
- Row roles and scopes as A2: a fund line opens a fund (carried across pages); a line with no amounts opens a section;
  account-coded and codeless rows are detail; a `subtotal_labels` row scopes the coded rows directly above it whose
  code matches its label's code class (budget-reconcile/subtotal-scope-class); a
  `total` row scopes the section's detail rows, or the whole fund's statement for `fund_totals`. A section with no
  heading takes its heading from its total (heading_from_total). Each detail row is in one scope per level.

No sum is computed here: reconciliation lives in fin_checks (budget-reconcile/*).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .fin_config import BookSpec, BudgetRules
from .pdfwords import Line, Word, lines as group_lines

BAND_GAP = 8.0           # points: words of one header phrase are closer than this ("FY" "2025")
ALIGN_TOL = 2.0          # points: digit amounts of one column share their right edge (pdfwords test: 1 pt)
AMOUNT = re.compile(r"^(\()?(\d{1,3}(?:,\d{3})*)(?(1)\))$")
DASH = "-"
HELD_ALIGN = "column-align"


class BookLayoutError(Exception):
    """The book does not match the configured layout (an unknown header word, no header on a statement page)."""


@dataclass(frozen=True)
class Band:
    x0: float
    x1: float
    header: str                  # header lines of the band joined with one space
    kind: str | None             # None: a derived column, position only
    fiscal_year: int | None


@dataclass
class Section:
    heading: str | None = None
    from_total: bool = False
    line_ids: list = field(default_factory=list)


@dataclass
class ParsedLine:
    id: str
    page: int
    statement: str
    fund_no: str | None
    fund_name: str | None
    section: Section | None
    account_code: str | None
    label: str
    row_role: str
    level: str | None            # subtotal | section | fund for subtotal/total rows
    cells: list                  # [{header_as_printed, fiscal_year, kind, as_printed, dollars}]
    scope_line_ids: list
    held: str | None


@dataclass
class BookRead:
    spec: BookSpec
    columns: list                # [{header_as_printed, fiscal_year, kind}] in first-seen order
    pages_read: list
    lines: list                  # ParsedLine in book order


def amount_dollars(tok: str) -> int | None:
    """Whole dollars of an amount token as printed: "-" is 0, "(1,234)" is -1234; None when it is not an amount."""
    if tok == DASH:
        return 0
    m = AMOUNT.match(tok)
    if not m:
        return None
    n = int(m.group(2).replace(",", ""))
    return -n if m.group(1) else n


def is_amount(tok: str) -> bool:
    return amount_dollars(tok) is not None


# ------------------------------------------------------------------ page role and header
def page_role(plines: list[Line], rules: BudgetRules) -> tuple[str | None, int]:
    """(statement, index of the title line) or (None, -1)."""
    for i, ln in enumerate(plines):
        if ln.text in rules.page_titles:
            return rules.page_titles[ln.text], i
    return None, -1


def _is_header_line(ln: Line, rules: BudgetRules) -> bool:
    """A line of the column header: it holds a header word and no amount. Its other words are checked per band
    (an unknown word fails the book there, it does not end the header)."""
    allowed = {w for w, _ in rules.kind_words} | set(rules.ignore_words) | set(rules.header_words)
    rest = rules.year.sub(" ", ln.text).split()                # "FY 23" is a year, not an amount
    return any(w.text in allowed for w in ln.words) and not any(is_amount(t) for t in rest)


def _phrases(ln: Line) -> list[list[Word]]:
    out: list[list[Word]] = []
    for w in ln.words:
        if out and w.x0 - out[-1][-1].x1 < BAND_GAP:
            out[-1].append(w)
        else:
            out.append([w])
    return out


def header_bands(plines: list[Line], title_at: int, rules: BudgetRules, where: str) -> tuple[list[Band], set]:
    """(bands left to right, indexes of the header lines). Raises BookLayoutError on an unknown header band."""
    idx = []
    for i in range(title_at + 1, len(plines)):
        if _is_header_line(plines[i], rules):
            idx.append(i)
        elif idx:
            break
    if not idx:
        raise BookLayoutError(f"{where}: no column header under the title")
    groups: list[dict] = []                     # {x0, x1, lines: [[words]]}
    for i in idx:
        for ph in _phrases(plines[i]):
            x0, x1 = ph[0].x0, ph[-1].x1
            hit = [g for g in groups if x0 < g["x1"] and x1 > g["x0"]]
            if len(hit) > 1:
                raise BookLayoutError(f"{where}: header phrase {' '.join(w.text for w in ph)!r} spans two bands")
            if hit:
                g = hit[0]
                g["x0"], g["x1"] = min(g["x0"], x0), max(g["x1"], x1)
                g["parts"].append(" ".join(w.text for w in ph))
            else:
                groups.append({"x0": x0, "x1": x1, "parts": [" ".join(w.text for w in ph)]})
    bands = []
    for g in sorted(groups, key=lambda g: g["x0"]):
        header = " ".join(g["parts"])
        words = header.split()
        if any(w in rules.ignore_words for w in words):
            bands.append(Band(g["x0"], g["x1"], header, None, None))
            continue
        kind = next((k for kw, k in rules.kind_words if kw in words), None)
        m = rules.year.search(header)
        if kind is None or m is None:
            raise BookLayoutError(f"{where}: header {header!r} has no known kind word and year")
        y = int(m.group(1))
        bands.append(Band(g["x0"], g["x1"], header, kind, y + 2000 if y < 100 else y))
    if not any(b.kind for b in bands):
        raise BookLayoutError(f"{where}: no value column in the header")
    return bands, set(idx)


def band_of(x1: float, bands: list[Band]) -> int | None:
    """Index of the band whose [left edge, next band's left edge) holds a right edge; None left of the first band."""
    j = None
    for i, b in enumerate(bands):
        if x1 >= b.x0:
            j = i
    return j


# ------------------------------------------------------------------ rows
@dataclass
class _Row:
    index: int                   # 1-based text-line index on the page (the line id's r)
    label_words: list
    tokens: dict                 # band index -> [Word]


def split_row(ln: Line, index: int, bands: list[Band]) -> _Row:
    label, tokens = [], {}
    for w in ln.words:
        j = band_of(w.x1, bands)
        if j is None:
            label.append(w)
        else:
            tokens.setdefault(j, []).append(w)
    return _Row(index, label, tokens)


def has_amount(row: _Row) -> bool:
    return any(is_amount(w.text) for ws in row.tokens.values() for w in ws)


def column_edges(rows: list[_Row], bands: list[Band]) -> dict:
    """Per value band, the most common right edge of its digit tokens on the page (amounts are right-aligned)."""
    edges: dict[int, Counter] = {}
    for r in rows:
        for j, ws in r.tokens.items():
            if bands[j].kind and len(ws) == 1 and ws[0].text != DASH and is_amount(ws[0].text):
                edges.setdefault(j, Counter())[round(ws[0].x1)] += 1
    return {j: c.most_common(1)[0][0] for j, c in edges.items()}


def read_cells(row: _Row, bands: list[Band], edges: dict) -> tuple[list[dict], str | None]:
    cells, held = [], None
    for j, b in enumerate(bands):
        if not b.kind:
            continue
        ws = row.tokens.get(j, [])
        text = " ".join(w.text for w in ws) or None
        dollars = amount_dollars(ws[0].text) if len(ws) == 1 else None
        if ws and (len(ws) > 1 or dollars is None):
            held = HELD_ALIGN
        elif ws and ws[0].text != DASH and j in edges and abs(ws[0].x1 - edges[j]) > ALIGN_TOL:
            held = HELD_ALIGN
        cells.append({"header_as_printed": b.header, "fiscal_year": b.fiscal_year, "kind": b.kind,
                      "as_printed": text, "dollars": dollars})
    if held:
        for c in cells:
            c["dollars"] = None
    return cells, held


# ------------------------------------------------------------------ the book
class _Scopes:
    """Scope state while reading one statement stream (A2 row roles and scopes)."""

    def __init__(self):
        self.reset_fund()

    def reset_fund(self):
        self.section = Section()
        self.coded: list[tuple[str, str]] = []      # (line id, account code) of the coded rows directly above
        self.fund: list[str] = []

    def open_section(self, heading: str | None):
        self.section = Section(heading=heading)
        self.coded = []


def read_book(words: list[Word], spec: BookSpec, rules: BudgetRules) -> BookRead:
    by_page: dict[int, list[Line]] = {}
    for ln in group_lines(words):
        by_page.setdefault(ln.page, []).append(ln)
    columns: list[dict] = []
    pages_read: list[int] = []
    out: list[ParsedLine] = []
    fund_no = fund_name = None
    statement = None
    sc = _Scopes()
    pending_fb: list[ParsedLine] = []          # fund_balance lines waiting for the next statement page's fund
    for page in range(spec.first_page, spec.last_page + 1):
        plines = by_page.get(page, [])
        role, title_at = page_role(plines, rules)
        if role is None:
            continue
        where = f"{spec.id} p. {page}"
        bands, header_idx = header_bands(plines, title_at, rules, where)
        pages_read.append(page)
        for b in bands:
            col = {"header_as_printed": b.header, "fiscal_year": b.fiscal_year, "kind": b.kind}
            if b.kind and col not in columns:
                columns.append(col)
        rows = []
        for i, ln in enumerate(plines):
            if i == title_at or i in header_idx or rules.footer.fullmatch(ln.text):
                continue
            r = split_row(ln, i + 1, bands)
            if i < min(header_idx) and not has_amount(r):
                continue                        # the page's title block (a row printed above it is still read)
            rows.append(r)
        edges = column_edges(rows, bands)
        if role == "fund_balance":
            local = _Scopes()
            for r in rows:
                label = " ".join(w.text for w in r.label_words)
                if not has_amount(r) or not any(p.search(label) for p in rules.fund_balance_labels):
                    continue
                pl = _line(spec, page, r, role, None, None, local, rules, bands, edges, label)
                out.append(pl)
                pending_fb.append(pl)
            continue
        if role != statement:
            statement = role
            sc.reset_fund()
        for r in rows:
            label = " ".join(w.text for w in r.label_words)
            if not has_amount(r):
                text = " ".join([label] + [w.text for _, ws in sorted(r.tokens.items()) for w in ws])
                m = rules.fund_line.match(text)
                if m:
                    fund_no, fund_name = m.group("no"), m.group("name")
                    sc.reset_fund()
                else:
                    sc.open_section(text)
                continue
            if fund_no is None:
                raise BookLayoutError(f"{where}: a row before any fund line: {label!r}")
            for pl in pending_fb:
                pl.fund_no, pl.fund_name = fund_no, fund_name
            pending_fb = []
            pl = _line(spec, page, r, role, fund_no, fund_name, sc, rules, bands, edges, label)
            out.append(pl)
    if pending_fb:
        raise BookLayoutError(f"{spec.id}: fund-balance rows with no statement page after them")
    return BookRead(spec, columns, pages_read, out)


def _line(spec, page, r: _Row, statement, fund_no, fund_name, sc: _Scopes, rules: BudgetRules, bands, edges,
          label) -> ParsedLine:
    code = None
    if r.label_words and rules.account_code.fullmatch(r.label_words[0].text):
        code = r.label_words[0].text
        label = " ".join(w.text for w in r.label_words[1:])
    cells, held = read_cells(r, bands, edges)
    lid = f"{spec.id}/p{page}/r{r.index}"
    if not label:                              # amounts with no label: kept verbatim, never shown as a value
        label = " ".join([code or ""] + [w.text for _, ws in sorted(r.tokens.items()) for w in ws]).strip()
        held = HELD_ALIGN
    role, level, scope = "detail", None, []
    if code is None and label in rules.subtotal_labels:
        cls = rules.subtotal_labels[label]
        role, level, scope = "subtotal", "subtotal", [i for i, c in sc.coded if cls.fullmatch(c)]
        sc.coded = []
    elif code is None and rules.total.match(label):
        role = "total"
        if any(p.match(label) for p in rules.fund_totals):
            level, scope = "fund", list(sc.fund)
            sc.open_section(None)
        else:
            level, scope = "section", list(sc.section.line_ids)
            sect = sc.section
            if sect.heading is None:
                sect.heading, sect.from_total = rules.total.sub("", label, count=1), True
            pl = ParsedLine(lid, page, statement, fund_no, fund_name, sect, code, label, role, level, cells, scope,
                            held)
            sc.open_section(None)
            return pl
    else:
        sc.section.line_ids.append(lid)
        sc.fund.append(lid)
        if code:
            sc.coded.append((lid, code))
        else:
            sc.coded = []
    pl = ParsedLine(lid, page, statement, fund_no, fund_name, sc.section if level != "fund" else None, code, label,
                    role, level, cells, scope, held)
    if role == "detail" and any(p.match(label) for p in rules.scope_break_after):
        sc.open_section(None)
    return pl


def tags_for(pl: ParsedLine, rules: BudgetRules) -> list[str]:
    heading = (pl.section.heading if pl.section else None) or ""
    tags = []
    for t in ("transfer", "non_revenue"):
        if (pl.account_code and pl.account_code in rules.tag_codes[t]) or heading.casefold() in rules.tag_headings[t]:
            tags.append(t)
    if pl.statement == "fund_balance":
        tags.append("available_funds")
    return tags


def to_records(read: BookRead, rules: BudgetRules) -> list[dict]:
    """budget_lines records (schema budget_line) without check and edition_differs (fin_checks fills them)."""
    out = []
    for pl in read.lines:
        heading = pl.section.heading if pl.section else None
        out.append({
            "id": pl.id, "book_id": read.spec.id, "edition": read.spec.edition, "fund_no": pl.fund_no,
            "fund_name": pl.fund_name, "statement": pl.statement, "heading_as_printed": heading,
            "heading_from_total": bool(pl.section and pl.section.from_total),
            "department": heading if pl.statement == "expenditure" else None,
            "account_code": pl.account_code, "label_as_printed": pl.label, "row_role": pl.row_role,
            "tags": tags_for(pl, rules), "cells": pl.cells, "page": pl.page,
            "scope_line_ids": pl.scope_line_ids, "check": None, "edition_differs": [], "held": pl.held})
    return out
