"""Adapter 3: budget-book PDF -> budget lines (task F10, architecture A2 "Adapter 3" and "Row roles and scopes").

Deterministic, on word positions from `pdftotext -bbox` (pdfwords). Every title, word list and row rule comes from
finance.yml `budget` (fin_config.BudgetRules); the code holds no locality literal.

- Page role by an exact title line (revenue, expenditure, fund_balance = the consolidated page); any other page is
  not read. On a fund_balance page only rows matching `fund_balance_labels` are read, and their fund is the fund of
  the next statement page.
- Column bands from the header block under the title: words of one header line closer than BAND_GAP form a phrase,
  phrases of the header lines that overlap in x form one band, read top to bottom ("FY 2026" / "Amended" / "Budget").
  A band's kind is its first kind word, its fiscal year from `year`; a book's `kind_overrides` set the kind of a whole
  header as printed (the FY2025 approved book's "FY 25 Projection" is its adopted budget year, column-kind/
  budget-year-kind), and an override that matches no header fails the book. A band with an ignore word (derived
  columns) is only a position. Any other header band fails the book (BookLayoutError).
- A word is a cell token when its right edge is at or right of the first band's left edge; band j holds the tokens
  whose right edge lies in [band j left edge, band j+1 left edge). A value band with two tokens, a token that is not
  an amount, or a digit token off its column's right edge by more than ALIGN_TOL holds the line (check
  `column-align`): its dollars are null and it is still listed. "-" is 0 as printed; no token is a blank cell (null).
  Derived bands are never stored, but their tokens are checked too: two tokens, a token that is not a number of the
  derived forms ("(1,234)", "12.50", "-3.10%", "-"), or one off its column's right edge (per trailing character: digit,
  ")", "%", "-") holds the line (check `derived-spill`, column-kind/derived-band-spill): a value that spilled
  into a derived column would otherwise leave its own cell blank unnoticed.
- Row roles and scopes as A2: a fund line opens a fund (carried across pages); a line with no amounts opens a section;
  account-coded and codeless rows are detail; a `subtotal_labels` row scopes the coded rows directly above it whose
  code matches its label's code class (budget-reconcile/subtotal-scope-class); a
  `total` row scopes the section's detail rows, or the whole fund's statement for `fund_totals`. A section with no
  heading takes its heading from its total (heading_from_total). Each detail row is in one scope per level.

No sum is computed here: reconciliation lives in fin_checks (budget-reconcile/*).

City layout (Munis "NEXT YEAR / CURRENT YEAR BUDGET ANALYSIS", config/localities/clarksville-tn/finance.yml; every
rule below is off unless its optional key is set, so a book without them is read exactly as before):
- `amount_unit: cents`: amounts print cents ("-1,404.28", ".00"); a cell's exact value is `cents` and `dollars` is
  null (no rounding is ever made). `split_glued_amounts`: a monospace word of touching amounts that reaches into the
  value bands ("REVENUE-183,187,308.58-197,098,013.00") is split back by character width; each piece is still checked
  against its column's right edge (column-align), so a wrong split holds the line instead of moving a value.
- `header_year_lines`: a line of years only is part of the header; `header_split_before`: words that start their own
  band ("COMMENT" 4.8 pt after "2nd Readin"); `ignore_tokens`: what a derived band may hold (the "________" rule).
- `fund_from_header`: the header's left phrase is the fund line (no fund number: fund_no null); a change of fund
  resets the fund scope. `rows.org_code`: a row's leading org code is dropped from its label when it repeats its
  section heading's org (another org stays in the label; the code is still read); a line with no amounts and no
  org right under an org heading continues that heading (a project name, "PD090 Mental Health Wellness Counselor").
  `rows.statement_by_code`: a coded row's statement by its account code (an unknown code class fails the book); a
  codeless row and a section total take their section's (a codeless row in a section with none: the page's).
- Org layout: a "TOTAL <name>" whose name does not start its org heading's name is a project subtotal
  ("TOTAL UNDEFINED PROJECT", "TOTAL AUTO LIABILITY CLAIMS"): scope its rows since the project opened; a project
  heading line ("AUTO AUTO LIABILITY CLAIMS", no org, no amounts) opens no section.
- `rows.fund_total_by_name`: "TOTAL <fund name, cut>" right after a section total is the fund total (statement net,
  scope the fund's rows in this report run). `rows.run_totals` (label -> revenue | expenditure | net) scope the run's
  rows of that statement; `rows.run_end` ends a run (scopes restart).
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
DERIVED = re.compile(r"^(\()?-?(?=[\d.])(?:\d{1,3}(?:,\d{3})*)?(?:\.\d+)?%?(?(1)\))$")  # "(1,234)" "(.50)" "-3.10%"
DASH = "-"
HELD_ALIGN = "column-align"
HELD_DERIVED = "derived-spill"
CENTS = re.compile(r"^(-)?(\d{1,3}(?:,\d{3})*)?\.(\d{2})$")             # "-1,404.28" ".00"
GLUED = re.compile(r"-?(?:\d{1,3}(?:,\d{3})*)?\.\d{2}")
NET = "net"


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
    statement: str | None = None   # of its detail rows (statement_by_code); a section total takes it


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
    report_dates: list = field(default_factory=list)   # [{as_printed, page}]: rules.report_date on the pages read


def amount_dollars(tok: str) -> int | None:
    """Whole dollars of an amount token as printed: "-" is 0, "(1,234)" is -1234; None when it is not an amount."""
    if tok == DASH:
        return 0
    m = AMOUNT.match(tok)
    if not m:
        return None
    n = int(m.group(2).replace(",", ""))
    return -n if m.group(1) else n


def amount_cents(tok: str) -> int | None:
    """Cents of an amount printed with cents ("-1,404.28" is -140428, ".00" is 0); None when it is not one."""
    m = CENTS.match(tok)
    if not m:
        return None
    n = int((m.group(2) or "0").replace(",", "")) * 100 + int(m.group(3))
    return -n if m.group(1) else n


def amount_value(tok: str, unit: str = "dollars") -> int | None:
    return amount_cents(tok) if unit == "cents" else amount_dollars(tok)


def is_amount(tok: str, unit: str = "dollars") -> bool:
    return amount_value(tok, unit) is not None


def split_glued(w: Word, unit: str, value_x0: float | None = None) -> list[Word]:
    """A word of touching amounts, maybe after a label ("REVENUE-1.00-2.00"), as one word per piece; positions by
    character width (the city books print in a monospace font). Any other word is returned as it is. The split starts
    where the value bands start: a piece whose right edge falls left of `value_x0` (the first value band's left edge;
    split_row places a word by its right edge) stays in the label, so a label ending in digits is never cut."""
    if unit != "cents" or is_amount(w.text, unit):
        return [w]
    cw = (w.x1 - w.x0) / len(w.text)
    pieces, end = [], len(w.text)
    for m in reversed(list(GLUED.finditer(w.text))):
        if m.end() != end or (value_x0 is not None and w.x0 + m.end() * cw < value_x0):
            break
        pieces.insert(0, (m.start(), m.end()))
        end = m.start()
    if not pieces or (end == 0 and len(pieces) < 2):
        return [w]
    if end:
        pieces.insert(0, (0, end))
    return [Word(w.page, w.x0 + a * cw, w.x0 + b * cw, w.y0, w.y1, w.text[a:b]) for a, b in pieces]


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
    if rules.header_year_lines and ln.words and not rest:
        return True                                            # "2024 2025 2025 2025 2025 2026" above the kinds
    return any(w.text in allowed for w in ln.words) and not any(is_amount(t, rules.amount_unit) for t in rest)


def _phrases(ln: Line, split_before: tuple = ()) -> list[list[Word]]:
    out: list[list[Word]] = []
    for w in ln.words:
        if out and w.x0 - out[-1][-1].x1 < BAND_GAP and w.text not in split_before:
            out[-1].append(w)
        else:
            out.append([w])
    return out


def _is_label_phrase(ph: list[Word], rules: BudgetRules) -> bool:
    """fund_from_header: a header phrase with no header word and no year is the fund name printed in the header."""
    allowed = {w for w, _ in rules.kind_words} | set(rules.ignore_words) | set(rules.header_words)
    text = " ".join(w.text for w in ph)
    return not any(w.text in allowed for w in ph) and not rules.year.search(text)


def header_bands(plines: list[Line], title_at: int, rules: BudgetRules, where: str,
                 kind_overrides: dict | None = None, labels: list | None = None) -> tuple[list[Band], set]:
    """(bands left to right, indexes of the header lines). Raises BookLayoutError on an unknown header band.
    `kind_overrides`: header as printed -> kind, for this book (the header is still stored as printed).
    `labels` (fund_from_header): receives the text of each line's leading label phrase (the fund name)."""
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
        for n, ph in enumerate(_phrases(plines[i], rules.header_split_before)):
            if rules.fund_from_header and n == 0 and _is_label_phrase(ph, rules):
                if labels is not None:
                    labels.append(" ".join(w.text for w in ph))
                continue
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
        if kind is not None and kind_overrides and header in kind_overrides:
            kind = kind_overrides[header]
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


def has_amount(row: _Row, unit: str = "dollars") -> bool:
    return any(is_amount(w.text, unit) for ws in row.tokens.values() for w in ws)


def _edge_class(tok: str) -> str:
    """A derived token's right-edge class: its last character unless a digit ("(1,234)" ends 3 pt right of "1,234")."""
    return "d" if tok[-1].isdigit() else tok[-1]


def _ignored(tok: str, ignore_tokens: tuple) -> bool:
    return any(p.fullmatch(tok) for p in ignore_tokens)


def column_edges(rows: list[_Row], bands: list[Band], unit: str = "dollars", ignore_tokens: tuple = ()) -> dict:
    """Per value band j, the most common right edge of its digit tokens on the page (amounts are right-aligned); per
    derived band, (j, edge class) -> the most common right edge of its tokens of that class."""
    edges: dict = {}
    for r in rows:
        for j, ws in r.tokens.items():
            if len(ws) != 1:
                continue
            t = ws[0].text
            if bands[j].kind and t != DASH and is_amount(t, unit):
                edges.setdefault(j, Counter())[round(ws[0].x1)] += 1
            elif not bands[j].kind and not _ignored(t, ignore_tokens) and (t == DASH or DERIVED.match(t)):
                edges.setdefault((j, _edge_class(t)), Counter())[round(ws[0].x1)] += 1
    return {k: c.most_common(1)[0][0] for k, c in edges.items()}


def derived_spill(row: _Row, bands: list[Band], edges: dict, ignore_tokens: tuple = ()) -> bool:
    """True when a derived band of the row holds what cannot be its own value (column-kind/derived-band-spill)."""
    for j, ws in row.tokens.items():
        if bands[j].kind:
            continue
        if len(ws) == 1 and _ignored(ws[0].text, ignore_tokens):
            continue
        if len(ws) > 1 or not (ws[0].text == DASH or DERIVED.match(ws[0].text)):
            return True
        e = edges.get((j, _edge_class(ws[0].text)))
        if e is not None and abs(ws[0].x1 - e) > ALIGN_TOL:
            return True
    return False


def null_amounts(cells: list[dict]) -> None:
    """A held line carries no amount (budget-reconcile/held-labelless-dollars): dollars, and cents in a cents book."""
    for c in cells:
        c["dollars"] = None
        if "cents" in c:
            c["cents"] = None


def read_cells(row: _Row, bands: list[Band], edges: dict, unit: str = "dollars",
               ignore_tokens: tuple = ()) -> tuple[list[dict], str | None]:
    cells, held = [], None
    for j, b in enumerate(bands):
        if not b.kind:
            continue
        ws = row.tokens.get(j, [])
        text = " ".join(w.text for w in ws) or None
        value = amount_value(ws[0].text, unit) if len(ws) == 1 else None
        if ws and (len(ws) > 1 or value is None):
            held = HELD_ALIGN
        elif ws and ws[0].text != DASH and j in edges and abs(ws[0].x1 - edges[j]) > ALIGN_TOL:
            held = HELD_ALIGN
        cell = {"header_as_printed": b.header, "fiscal_year": b.fiscal_year, "kind": b.kind, "as_printed": text,
                "dollars": value}
        if unit == "cents":                    # exact as printed; no whole-dollar value is made up
            cell["dollars"], cell["cents"] = None, value
        cells.append(cell)
    if not held and derived_spill(row, bands, edges, ignore_tokens):
        held = HELD_DERIVED
    if held:
        null_amounts(cells)
    return cells, held


# ------------------------------------------------------------------ the book
class _Scopes:
    """Scope state while reading one statement stream (A2 row roles and scopes)."""

    def __init__(self):
        self.run: list[tuple[str, str]] = []        # (line id, statement) of the detail rows of this report run
        self.reset_fund()

    def reset_run(self):
        self.run = []
        self.reset_fund()

    def reset_fund(self):
        self.section = Section()
        self.coded: list[tuple[str, str]] = []      # (line id, account code) of the coded rows directly above
        self.fund: list[str] = []
        self.project: list[str] = []                # rows since the section or project opened (org layout)

    def open_section(self, heading: str | None):
        self.section = Section(heading=heading)
        self.coded = []
        self.project = []


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
    overrides = dict(spec.kind_overrides)
    unit = rules.amount_unit
    report_dates: list[dict] = []
    seen_dates: set[str] = set()
    for page in range(spec.first_page, spec.last_page + 1):
        plines = by_page.get(page, [])
        role, title_at = page_role(plines, rules)
        if role is None:
            continue
        where = f"{spec.id} p. {page}"
        labels: list[str] = []
        bands, header_idx = header_bands(plines, title_at, rules, where, overrides, labels)
        if rules.fund_from_header:
            m = rules.fund_line.match(labels[0]) if len(labels) == 1 else None
            if m is None:
                raise BookLayoutError(f"{where}: the header names no one fund ({labels!r})")
            new = (m.groupdict().get("no"), m.group("name"))
            if new != (fund_no, fund_name):
                fund_no, fund_name = new
                sc.reset_fund()
        pages_read.append(page)
        for b in bands:
            col = {"header_as_printed": b.header, "fiscal_year": b.fiscal_year, "kind": b.kind}
            if b.kind and col not in columns:
                columns.append(col)
        if rules.report_date is not None:
            for ln in plines:
                m = rules.report_date.search(ln.text)
                if m and m.group("date") not in seen_dates:
                    seen_dates.add(m.group("date"))
                    report_dates.append({"as_printed": m.group("date"), "page": page})
        rows = []
        for i, ln in enumerate(plines):
            if i == title_at or i in header_idx or rules.footer.fullmatch(ln.text):
                continue
            if rules.split_glued_amounts:           # only words that reach into the value bands
                ln = Line(ln.page, [p for w in ln.words
                                    for p in (split_glued(w, unit, bands[0].x0) if w.x1 >= bands[0].x0 else [w])])
            r = split_row(ln, i + 1, bands)
            if i < min(header_idx) and not has_amount(r, unit):
                continue                        # the page's title block (a row printed above it is still read)
            rows.append(r)
        edges = column_edges(rows, bands, unit, rules.ignore_tokens)
        if role == "fund_balance":
            local = _Scopes()
            for r in rows:
                label = " ".join(w.text for w in r.label_words)
                if not has_amount(r, unit) or not any(p.search(label) for p in rules.fund_balance_labels):
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
            if not has_amount(r, unit):
                text = " ".join([label] + [w.text for _, ws in sorted(r.tokens.items()) for w in ws])
                if rules.run_end and rules.run_end.match(text.strip()):
                    sc.reset_run()                  # never stored (it names the staff member who ran the report)
                    continue
                m = None if rules.fund_from_header else rules.fund_line.match(text)
                if m:
                    fund_no, fund_name = m.group("no"), m.group("name")
                    sc.reset_fund()
                elif rules.org_code and sc.section.heading and not rules.org_code.fullmatch(text.split()[0]):
                    if not sc.section.line_ids:         # a project line right under the org heading
                        sc.section.heading += " " + text
                    sc.project = []                     # a project heading: its rows end at "TOTAL <project>"
                else:
                    sc.open_section(text)
                continue
            if fund_name is None:
                raise BookLayoutError(f"{where}: a row before any fund line: {label!r}")
            for pl in pending_fb:
                pl.fund_no, pl.fund_name = fund_no, fund_name
            pending_fb = []
            pl = _line(spec, page, r, role, fund_no, fund_name, sc, rules, bands, edges, label)
            out.append(pl)
    if pending_fb:
        raise BookLayoutError(f"{spec.id}: fund-balance rows with no statement page after them")
    unused = set(overrides) - {c["header_as_printed"] for c in columns}
    if unused:
        raise BookLayoutError(f"{spec.id}: kind_overrides name no header of the book: {sorted(unused)}")
    return BookRead(spec, columns, pages_read, out, report_dates)


def _line(spec, page, r: _Row, statement, fund_no, fund_name, sc: _Scopes, rules: BudgetRules, bands, edges,
          label) -> ParsedLine:
    code = None
    words, org = r.label_words, []
    if rules.org_code and words and rules.org_code.fullmatch(words[0].text):
        head = (sc.section.heading or "").split()
        # the section heading prints the same org: not part of the label; another org (a book that starts mid-section)
        # stays in the label, before the name
        org = [] if head and head[0] == words[0].text else [words[0]]
        words = words[1:]
        label = " ".join(w.text for w in org + words)
    if words and rules.account_code.fullmatch(words[0].text):
        code = words[0].text
        label = " ".join(w.text for w in org + words[1:])
    cells, held = read_cells(r, bands, edges, rules.amount_unit, rules.ignore_tokens)
    lid = f"{spec.id}/p{page}/r{r.index}"
    if not label:                              # amounts with no label: kept verbatim, never shown as a value
        label = " ".join([code or ""] + [w.text for _, ws in sorted(r.tokens.items()) for w in ws]).strip()
        held = HELD_ALIGN
        null_amounts(cells)                    # held means no amounts (budget-reconcile/held-labelless-dollars)
    role, level, scope = "detail", None, []
    if code is None and label in rules.run_totals:
        want = rules.run_totals[label]         # a report-run total: every fund of the run, one statement or net
        scope = [i for i, st in sc.run if want == NET or st == want]
        sc.open_section(None)
        return ParsedLine(lid, page, want, None, None, None, code, label, "total", "run", cells, scope, held)
    if code is None and label in rules.subtotal_labels:
        cls = rules.subtotal_labels[label]
        role, level, scope = "subtotal", "subtotal", [i for i, c in sc.coded if cls.fullmatch(c)]
        sc.coded = []
    elif code is None and rules.total.match(label):
        role = "total"
        rest = rules.total.sub("", label, count=1)
        by_name = (rules.fund_total_by_name and fund_name and rest and not sc.section.line_ids
                   and fund_name.startswith(rest))
        if (not by_name and rules.org_code and sc.section.heading and sc.section.line_ids
                and not _names_section(rest, sc.section.heading, rules)):
            # a project's total inside an org section ("TOTAL AUTO LIABILITY CLAIMS"): its rows since the project
            # opened; they stay in the section, whose own total follows
            scope = list(sc.project)
            sc.project = []
            return ParsedLine(lid, page, sc.section.statement or statement, fund_no, fund_name, sc.section, code,
                              label, "subtotal", "subtotal", cells, scope, held)
        if by_name or any(p.match(label) for p in rules.fund_totals):
            level, scope = "fund", list(sc.fund)
            if by_name:
                statement = NET                # the fund's revenue (printed negative) and expense together
            sc.open_section(None)
        else:
            level, scope = "section", list(sc.section.line_ids)
            sect = sc.section
            if sect.heading is None:
                sect.heading, sect.from_total = rest, True
            pl = ParsedLine(lid, page, sect.statement or statement, fund_no, fund_name, sect, code, label, role,
                            level, cells, scope, held)
            sc.open_section(None)
            return pl
    else:
        if rules.statement_by_code:
            if code:
                own = next((st for st, rx in rules.statement_by_code if rx.fullmatch(code)), None)
                if own is None:
                    raise BookLayoutError(f"{lid}: account code {code} is in no statement_by_code class")
            else:
                own = sc.section.statement or statement
            sect = sc.section
            sect.statement = own if sect.statement in (None, own) else NET
            statement = own
        sc.section.line_ids.append(lid)
        sc.project.append(lid)
        sc.fund.append(lid)
        sc.run.append((lid, statement))
        if code:
            sc.coded.append((lid, code))
        else:
            sc.coded = []
    pl = ParsedLine(lid, page, statement, fund_no, fund_name, sc.section if level != "fund" else None, code, label,
                    role, level, cells, scope, held)
    if role == "detail" and any(p.match(label) for p in rules.scope_break_after):
        sc.open_section(None)
    return pl


def _names_section(rest: str, heading: str, rules: BudgetRules) -> bool:
    """Org layout: a total's label names its section when it is the start of the heading's name (labels are cut to
    22 characters: "TOTAL Self-Insurance Fund Re" for "2341000 Self-Insurance Fund Revenues")."""
    words = heading.split()
    if words and rules.org_code.fullmatch(words[0]):
        words = words[1:]
    return bool(rest) and " ".join(words).startswith(rest)


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
