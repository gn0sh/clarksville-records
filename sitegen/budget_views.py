"""Budget book views: the Finance and Capital projects pages (docs/design/finance-contracts.md 6-7, slice 1b; tasks
F13, F14). finance.json budget lines -> plain dicts.

Each book keeps its own columns, as printed, in its own tables: no table puts two books' columns on one axis, and
nothing here adds, subtracts or compares amounts (no difference, percent, arrow, county-wide total or total across
lines or books). Rows keep the book's order, (book, page, row) parsed from the line id, never an amount. Every
fixed sentence comes from config/finance_text.yml (`budget`, `held`, `notes`, `edition_note`)."""
from __future__ import annotations

from . import config
from .fin_views import Finance, FinanceError, held_check, notes, _words

T = config.FIN_TEXT
B = T["budget"]
C = T["contracts"]
SECTIONS = ("revenue", "spending", "other")
INDEX = "finance/index.html"
CAPITAL = "capital/index.html"


def line_key(line_id: str) -> tuple[str, int, int]:
    """schema line_id `<book>/p<page>/r<row>` in book order (as text, p100 would sort before p28)."""
    book, page, row = line_id.split("/")
    return book, int(page[1:]), int(row[1:])


def anchor(line_id: str) -> str:
    return "l-" + line_id.replace("/", "-")


def section_of(line: dict) -> str:
    """Design 6 / Note E: transfers, other (non-revenue) sources and available funds have their own section; they are
    not revenue or spending."""
    if line["tags"] or line["statement"] == "fund_balance":
        return "other"
    return "revenue" if line["statement"] == "revenue" else "spending"


def aria_amount(text: str | None) -> str | None:
    """Screen readers say "minus 1,200" for a printed "(1,200)"; the text itself stays as printed."""
    if text and len(text) > 2 and text.startswith("(") and text.endswith(")"):
        return "minus " + text[1:-1]
    return None


def dollars(n: int) -> str:
    """Whole dollars with thousands separators; a negative in parentheses, as the book prints it."""
    return f"({-n:,})" if n < 0 else f"{n:,}"


def diff_notes(line: dict) -> list[str]:
    """One fixed-wording note per column whose printed total and summed lines differ (owner's decision 2026-11-08).
    The numbers are the check cells' printed, sum and diff, never recomputed."""
    check = line["check"]
    state = check["state"]
    if state not in ("does_not_add_up", "within_rounding"):
        return []
    out = []
    for c, pc in zip(line["cells"], check["per_cell"]):
        d = pc["diff"]
        if d in (0, None):
            continue
        h = c["header_as_printed"]
        if state == "within_rounding":
            out.append(B["diff_note_rounding"].format(header=h, abs=f"{abs(d):,}"))
        elif not line["scope_line_ids"]:
            out.append(B["diff_note_no_lines"].format(header=h, printed=dollars(pc["printed"])))
        else:
            out.append(B["diff_note"].format(
                header=h, printed=dollars(pc["printed"]), sum=dollars(pc["sum"]), diff=dollars(d), abs=f"{abs(d):,}",
                direction=B["diff_higher"] if d > 0 else B["diff_lower"]))
    return out


def coverage_sentence(cov: dict) -> str:
    """Design 2: the one budget coverage sentence, from finance.json's coverage block (never counted here)."""
    return T["coverage_budget"].format(n_lines=cov["n_lines"], n_books=cov["n_books"], n_flag=cov["n_flag"])


class Budget:
    """Budget lines in book order, with their books, over one Finance. Refuses a file whose lines point at a book or
    line that is not there, or carry a held check or check state with no fixed words."""

    def __init__(self, fx: Finance, capital_fund: str | None):
        fin = fx.fin
        self.fx = fx
        self.lines = sorted(fin.get("budget_lines", []), key=lambda x: line_key(x["id"]))
        self.by_id = {x["id"]: x for x in self.lines}
        self.books = sorted(fin.get("books", []), key=lambda b: (-b["fiscal_year"], b["id"]))  # newest book first
        self.book = {b["id"]: b for b in self.books}
        for x in self.lines:
            if x["book_id"] not in self.book:
                raise FinanceError(f"budget line {x['id']} names book {x['book_id']!r}, which is not in the file")
            for other in [*x["scope_line_ids"], *x["edition_differs"]]:
                if other not in self.by_id:
                    raise FinanceError(f"budget line {x['id']} refers to line {other!r}, which is not in the file")
            held_check(x["held"], f"budget line {x['id']}")
            if x["check"] is not None and x["check"]["state"] not in B["check"]:
                raise FinanceError(f"budget line {x['id']} has check state {x['check']['state']!r}, which has no "
                                   "words in config/finance_text.yml (budget.check)")
        funds: dict[str, None] = {}
        for b in self.books:  # the newest book's order, then funds printed only in an older book
            for x in self.lines:
                if x["book_id"] == b["id"]:
                    funds.setdefault(x["fund_no"], None)
        self.funds = list(funds)
        self.capital_fund = capital_fund if capital_fund in funds else None

    def fund_lines(self, fund_no: str, book_id: str) -> list[dict]:
        return [x for x in self.lines if x["fund_no"] == fund_no and x["book_id"] == book_id]

    @staticmethod
    def fund_href(fund_no: str) -> str:
        return f"finance/{fund_no}.html"

    def src(self, line: dict) -> dict:
        return self.fx.src(self.book[line["book_id"]]["source_id"], line["page"])

    def href_from(self, page: str):
        """A link to a line's row from `page`: #anchor on the same page, else on the line's own fund page."""
        def href_of(line_id: str) -> str:
            target = self.fund_href(self.by_id[line_id]["fund_no"])
            return ("" if target == page else "../" + target) + "#" + anchor(line_id)
        return href_of


def _signature(line: dict) -> tuple:
    return tuple((c["header_as_printed"], c["kind"]) for c in line["cells"])


def _columns(line: dict, seen: set[str]) -> list[dict]:
    """Design 6: the book's header as printed plus its kind, in the book's column order. The first use of a kind
    word on a page links to its glossary entry."""
    out = []
    for c in line["cells"]:
        gid = B["kind_glossary"].get(c["kind"])
        out.append({"header": c["header_as_printed"], "kind": B["kinds"][c["kind"]],
                    "glossary": gid if gid and gid not in seen else None})
        if gid:
            seen.add(gid)
    return out


def _row(bg: Budget, line: dict, href_of) -> dict:
    held = line["held"]
    cells = []
    for c in line["cells"]:
        text = None if held else c["as_printed"]
        cells.append({"text": text, "aria": aria_amount(text), "held": bool(held),
                      "label": f"{c['header_as_printed']} {B['kinds'][c['kind']]}"})
    check = None
    if line["check"] is not None and not held:  # a held total says why it is held instead (not_confirmed)
        state = line["check"]["state"]
        check = {"state": state, "words": B["check"][state], "flag": state == "does_not_add_up",
                 "notes": diff_notes(line),
                 "href": "#chk-" + anchor(line["id"])[2:]}
    moved = []
    if line["row_role"] != "detail":  # tagged lines this total adds that are listed in another section
        here = section_of(line)
        moved = [{"href": href_of(i), "label": bg.by_id[i]["label_as_printed"]} for i in line["scope_line_ids"]
                 if section_of(bg.by_id[i]) != here]
    edition = None
    if line["edition_differs"]:
        edition = {"sentence": T["edition_note"],
                   "links": [{"href": href_of(i), "book": bg.book[bg.by_id[i]["book_id"]]["title"],
                              "page": bg.by_id[i]["page"]} for i in line["edition_differs"]]}
    return {"id": line["id"], "anchor": anchor(line["id"]), "account": line["account_code"],
            "label": line["label_as_printed"], "role": line["row_role"],
            "role_words": B["role_words"].get(line["row_role"]), "cells": cells, "held": held, "check": check,
            "moved": moved, "edition": edition, "src": bg.src(line)}


def _tables(bg: Budget, lines: list[dict], seen: set[str], href_of, anchors: bool = True) -> list[dict]:
    """Consecutive lines with the same printed columns share one table; a change of columns starts a new one."""
    out: list[dict] = []
    for x in lines:
        if not out or out[-1]["sig"] != _signature(x):
            out.append({"sig": _signature(x), "columns": _columns(x, seen), "rows": []})
        out[-1]["rows"].append(dict(_row(bg, x, href_of), with_anchor=anchors))
    return out


def _groups(bg: Budget, lines: list[dict], prefix: str, seen: set[str], href_of) -> list[dict]:
    """Runs of lines under one printed heading (a revenue source, a department, a project) in book order; each run
    is a `<details>` with its own anchor."""
    runs: list[list[dict]] = []
    for x in lines:
        if not runs or runs[-1][0]["heading_as_printed"] != x["heading_as_printed"]:
            runs.append([])
        runs[-1].append(x)
    out = []
    for n, run in enumerate(runs, 1):
        heading = run[0]["heading_as_printed"]
        out.append({"id": f"{prefix}-{n}", "heading": heading or B["no_heading"], "n": len(run),
                    "n_word": B["line_word"] if len(run) == 1 else B["lines_word"],
                    "search": " ".join([heading or "", *(x["label_as_printed"] for x in run)]).casefold(),
                    "tables": _tables(bg, run, seen, href_of)})
    return out


def _flagged(bg: Budget, lines: list[dict], seen: set[str], href_of) -> list[dict]:
    """Design 6 "does not add up": the total as printed, then every line it was checked against, wherever that line
    is listed (a transfer moved to its own section is still listed under its total). Shown, never collapsed."""
    out = []
    for x in lines:
        if x["check"] is None or x["held"] or x["check"]["state"] != "does_not_add_up":
            continue
        scope = [bg.by_id[i] for i in x["scope_line_ids"]]
        tables = _tables(bg, [x, *scope], seen, href_of, anchors=False)
        tables[0]["rows"][0]["check"]["href"] = "#" + anchor(x["id"])  # back to the total's own row
        out.append({"id": "chk-" + anchor(x["id"])[2:], "line_href": "#" + anchor(x["id"]),
                    "caption": B["flagged_caption"].format(label=x["label_as_printed"], page=x["page"]),
                    "no_lines": None if scope else B["flagged_no_lines"], "tables": tables})
    return out


def _common(bg: Budget) -> dict:
    return {"coverage_sentence": coverage_sentence(bg.fx.coverage), "notes": notes(), "b": B, "c": C,
            "disclosure": False}


def _actuals_missing(bg: Budget) -> list[str]:
    """Fiscal years between the first and the last Actual column that no book prints as Actual."""
    years = {c["fiscal_year"] for b in bg.books for c in b["columns"] if c["kind"] == "actual"}
    years |= {c["fiscal_year"] for x in bg.lines for c in x["cells"] if c["kind"] == "actual"}
    if not years:
        return []
    return [B["actuals_missing"].format(year=y) for y in range(min(years), max(years) + 1) if y not in years]


def _names(bg: Budget, fund_no: str) -> list[dict]:
    """The fund's name as each book prints it, cited to the book's first page of that fund."""
    out = []
    for b in bg.books:
        lines = bg.fund_lines(fund_no, b["id"])
        if lines:
            out.append({"name": lines[0]["fund_name"], "book": b["title"], "src": bg.src(lines[0])})
    return out


def finance_index(bg: Budget) -> dict:
    """finance/index.html (design 6): books, then funds in the book's order, the same row for every fund and no
    amounts. No committee roster: finance.json names no one (AC-F9 has nothing to link here yet)."""
    books = []
    for b in bg.books:
        s = bg.fx.sources[b["source_id"]]
        books.append({"title": b["title"], "edition": b["edition"], "fiscal_year": b["fiscal_year"],
                      "url": s["url"], "fetched": s["fetched_at"]})
    funds = [{"no": no, "href": bg.fund_href(no), "names": _names(bg, no), "fact_id": f"fund/{no}"}
             for no in bg.funds]
    from .fin_views import EXPORTS_READY
    return dict(_common(bg), books=books, funds=funds, missing=_actuals_missing(bg), words=_words(B["words"]),
                capital_href=CAPITAL if bg.capital_fund else None, exports=EXPORTS_READY and not bg.fx.fixture)


def fund(fund_no: str, bg: Budget) -> dict:
    """finance/<fund_no>.html (design 6): for each book, the same three sections in the same order, then the totals
    that do not add up with their lines. A book without the fund says so; an empty section says so."""
    href_of = bg.href_from(bg.fund_href(fund_no))
    seen: set[str] = set()
    books = []
    for b in bg.books:
        lines = bg.fund_lines(fund_no, b["id"])
        entry = {"id": b["id"], "title": b["title"], "caption": B["caption"].format(title=b["title"],
                                                                                    edition=b["edition"]),
                 "absent": not lines, "absent_sentence": B["not_in_book"].format(book=b["title"]),
                 "sections": [], "flagged": []}
        for key in SECTIONS if lines else ():
            part = [x for x in lines if section_of(x) == key]
            sid = f"{b['id']}-{key}"
            entry["sections"].append({"key": key, "id": sid, "title": B["sections"][key], "n": len(part),
                                      "n_word": B["line_word"] if len(part) == 1 else B["lines_word"],
                                      "groups": _groups(bg, part, sid, seen, href_of)})
        if lines:
            entry["flagged"] = _flagged(bg, lines, seen, href_of)
        books.append(entry)
    names = _names(bg, fund_no)
    printed: dict[str, list[dict]] = {}  # one entry per name as printed, with every book that prints it
    for n in names:
        printed.setdefault(n["name"], []).append(n["src"])
    return dict(_common(bg), fund_no=fund_no, names=names, books=books, words=_words(B["words"]),
                printed=[{"name": k, "srcs": v} for k, v in printed.items()],
                title=names[0]["name"], capital_href="../" + CAPITAL if fund_no == bg.capital_fund else None)


def capital(bg: Budget) -> dict:
    """capital/index.html (design 7, Note D): the capital fund's spending lines, project by project, per book, as
    printed. No total across lines and no cost column: the printed lines and their checks only."""
    no = bg.capital_fund
    href_of = bg.href_from(CAPITAL)
    seen: set[str] = set()
    books = []
    for b in bg.books:
        part = [x for x in bg.fund_lines(no, b["id"]) if section_of(x) == "spending"]
        entry = {"id": b["id"], "title": b["title"], "caption": B["caption"].format(title=b["title"],
                                                                                    edition=b["edition"]),
                 "absent": not part, "absent_sentence": B["not_in_book"].format(book=b["title"]),
                 "groups": [], "flagged": [], "source_line": None, "src": None}
        if part:
            pages = [x["page"] for x in part]
            entry["source_line"] = B["capital_source"].format(fund_name=part[0]["fund_name"], fund_no=no,
                                                              book=b["title"], first=min(pages), last=max(pages))
            entry["src"] = bg.src(part[0])
            entry["groups"] = _groups(bg, part, f"cap-{b['id']}", seen, href_of)
            entry["flagged"] = _flagged(bg, part, seen, href_of)
        books.append(entry)
    return dict(_common(bg), books=books, fund_no=no, fund_href="../" + bg.fund_href(no),
                words=_words(B["capital_words"]))
