"""The general fund dollar (docs/architecture/finance-contracts.md 11): on each body's Finance index, how each dollar
of the general fund budget splits across departments, in cents that add up to 100. Owner's request 2026-11-11.

One adopted column of one book, from config/localities/<locality>/dollar-split.yml. Every amount is a printed total:
a department is one or more printed department totals (grouped as the config says, each listed with its page), and
the fund total is either the fund's own printed spending total (the county) or, where the book prints none (the city
books print only a total of revenue and spending together), the department totals added up and checked against that
printed total with the fund's printed revenue totals. Any adding goes through collector.fin_checks (the one module
that adds amounts, lint budget-reconcile/*). Departments keep the book's order (no amount sort, neutrality/*); a
department under half a cent goes to one "Other" row that lists them; one printed with no amount in the column is
listed apart. Anything that does not add up exactly, a held line, a negative department or a heading the config
cannot name fails the build: a wrong figure must never reach the page."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from collector.fin_checks import cents_of_dollar, parts_add_up, total_of

from . import config
from .budget_views import Budget, cents_text, dollars, fund_key
from .fin_views import Finance, FinanceError

T = config.FIN_TEXT["dollar"]
GROUP_RULES = ("heading_prefix", "org_code")
OTHER_BELOW = 200   # a department under 1/200 of the fund (half a cent of each dollar) goes to Other
T_LABEL_MIN = 5     # a bar segment of this many cents or more carries its cents, and the key under the bar names it
T_PHONE_MIN = 10    # on a phone a segment under this many cents is too narrow for its label (the key still names it)


def slug(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", key.casefold()).strip("-")


def load(locality: str) -> dict | None:
    """config/localities/<locality>/dollar-split.yml, or None when the locality has none."""
    path = config.CONFIG_DIR / "localities" / locality / "dollar-split.yml"
    if not Path(path).is_file():
        return None
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for key in ("book", "column", "fund", "group_by", "body"):
        if not isinstance(cfg.get(key), str) or not cfg[key]:
            raise FinanceError(f"{path}: `{key}` must be a non-empty string")
    if cfg["group_by"] not in GROUP_RULES:
        raise FinanceError(f"{path}: group_by must be one of {GROUP_RULES}, not {cfg['group_by']!r}")
    if cfg["group_by"] == "org_code" and not (isinstance(cfg.get("org_digits"), int) and isinstance(cfg.get("names"), dict)):
        raise FinanceError(f"{path}: group_by org_code needs org_digits (a number) and names (org prefix: name)")
    if cfg["group_by"] == "heading_prefix" and not isinstance(cfg.get("heading_separator"), str):
        raise FinanceError(f"{path}: group_by heading_prefix needs heading_separator")
    return cfg


def _cell(line: dict, column: str, cents: bool) -> dict:
    found = [c for c in line["cells"] if c["header_as_printed"] == column]
    if len(found) != 1:
        raise FinanceError(f"dollar split: line {line['id']} prints column {column!r} {len(found)} times, not once")
    c = found[0]
    value = c.get("cents") if cents else c.get("dollars")
    if value is None:
        raise FinanceError(f"dollar split: line {line['id']} prints no amount in {column!r}")
    return {"value": value, "as_printed": c["as_printed"], "kind": c["kind"], "fiscal_year": c["fiscal_year"]}


def _exact_in_column(line: dict, column: str) -> None:
    """A total the bar uses must add up to its lines in this column exactly (diff 0) and not be held."""
    if line["held"]:
        raise FinanceError(f"dollar split: total {line['id']} is held ({line['held']})")
    chk = line["check"]
    i = next((i for i, c in enumerate(line["cells"]) if c["header_as_printed"] == column), None)
    if i is None:
        raise FinanceError(f"dollar split: total {line['id']} prints no column {column!r}")
    if chk is None or chk["state"] == "not_checked" or chk["per_cell"][i]["diff"] != 0:
        raise FinanceError(f"dollar split: total {line['id']} does not add up to its lines in {column!r} exactly")


def _group_key(line: dict, cfg: dict) -> tuple[str, str]:
    """(key, name) of the department a printed department total belongs to."""
    heading = line["heading_as_printed"]
    if cfg["group_by"] == "heading_prefix":
        name = heading.split(cfg["heading_separator"])[0].strip()
        return name, name
    org = heading.split()[0]
    if not re.fullmatch(r"\d{6,}", org):
        raise FinanceError(f"dollar split: heading {heading!r} ({line['id']}) starts with no org code")
    key = org[:cfg["org_digits"]]
    name = (cfg["names"] or {}).get(key)
    if not name:
        raise FinanceError(f"dollar split: org code {key} ({heading!r}, {line['id']}) has no name in dollar-split.yml")
    return key, name


def _own_kinds(book: dict) -> set[str]:
    """The kinds of a book's own budget-year columns (fiscal year = the book's): {"adopted"}, {"proposed"}, ..."""
    return {c["kind"] for c in book["columns"] if c["fiscal_year"] == book["fiscal_year"]}


def _newer_books_note(bg: Budget, book: dict, year: int) -> str | None:
    """Why the bar uses this book when the file has a newer one (dollar-split/stale-book-note): built from the data,
    so it cannot go stale. A newer book that prints an adopted budget for its own year fails the build: the config
    must move to it (a bar of an older year beside a newer adopted book would mislead)."""
    newer = [b for b in bg.books if b["fiscal_year"] > year]
    for b in newer:
        if "adopted" in _own_kinds(b):
            raise FinanceError(f"dollar split: {b['id']} prints an adopted FY{b['fiscal_year']} budget, newer than "
                               f"{book['id']} (FY{year}): point dollar-split.yml at it")
    if not newer:
        return None
    b = max(newer, key=lambda b: (b["fiscal_year"], b["id"]))
    kinds = config.FIN_TEXT["budget"]["kinds"]
    what = " and ".join(kinds[k].lower() for k in sorted(_own_kinds(b))) or T["newer_no_budget"]
    return T["newer_note"].format(year=b["fiscal_year"], edition=b["edition"], what=what, used=year)


def caption_amount(text: str) -> str:
    """The amount for the bar's caption: ".00" is dropped when the cents are zero; any other cents stay."""
    return text[:-3] if text.endswith(".00") else text


def split(bg: Budget, cfg: dict | None) -> dict | None:
    """The view of the general fund dollar for one body's Finance index, or None when the config names a book or
    fund that is not in this file (a FIXTURE build). `href_of` links each printed total to its row on the fund page,
    so call this after the fund pages are planned (Budget.line_pages)."""
    if cfg is None or cfg["book"] not in bg.book:
        return None
    book = bg.book[cfg["book"]]
    column, cents = cfg["column"], bg.cents(book["id"])
    money = cents_text if cents else dollars
    lines = [x for x in bg.lines if x["book_id"] == book["id"] and fund_key(x) == cfg["fund"]]
    if not lines:
        return None
    href_of = bg.href_from(bg.index)
    spend = [x for x in lines if x["statement"] == "expenditure"]
    dept_totals = [x for x in spend if x["row_role"] == "total" and x["department"]]
    if not dept_totals:
        raise FinanceError(f"dollar split: {book['id']} fund {cfg['fund']} prints no department totals")
    # Every spending detail line of the fund sits under exactly one department total (no line left out or counted twice).
    details = {x["id"] for x in spend if x["row_role"] == "detail"}
    under = [i for t in dept_totals for i in t["scope_line_ids"]]
    if len(under) != len(details) or set(under) != details:
        raise FinanceError(f"dollar split: {book['id']} fund {cfg['fund']}: the department totals do not cover every "
                           "spending line exactly once")
    first = _cell(dept_totals[0], column, cents)
    for t in dept_totals:   # every total the bar reads: the adopted budget of one fiscal year
        c = _cell(t, column, cents)
        if c["kind"] != "adopted" or c["fiscal_year"] != first["fiscal_year"]:
            raise FinanceError(f"dollar split: {t['id']} column {column!r} is {c['kind']} FY{c['fiscal_year']}, not "
                               f"adopted FY{first['fiscal_year']}")
    note = _newer_books_note(bg, book, first["fiscal_year"])
    for t in dept_totals:
        _exact_in_column(t, column)
    amounts = [_cell(t, column, cents)["value"] for t in dept_totals]
    if any(a < 0 for a in amounts):
        raise FinanceError(f"dollar split: {book['id']} fund {cfg['fund']} prints a negative department total")
    total = total_of(amounts)

    # The fund total: its own printed spending total, else the printed total of revenue and spending together.
    fund_spend = [x for x in spend if x["row_role"] == "total" and not x["department"]]
    fund_net = [x for x in lines if x["row_role"] == "total" and x["statement"] == "net"]
    if fund_spend:
        if len(fund_spend) != 1:
            raise FinanceError(f"dollar split: {book['id']} fund {cfg['fund']} prints {len(fund_spend)} spending totals")
        ft = fund_spend[0]
        _exact_in_column(ft, column)
        if _cell(ft, column, cents)["value"] != total:
            raise FinanceError(f"dollar split: {book['id']} fund {cfg['fund']}: the department totals do not add up "
                               f"to the printed {ft['label_as_printed']!r}")
        basis = {"kind": "printed", "line": ft}
    elif len(fund_net) == 1:
        ft = fund_net[0]
        _exact_in_column(ft, column)
        rev = [x for x in lines if x["statement"] == "revenue" and x["row_role"] == "total"]
        parts = [_cell(x, column, cents)["value"] for x in rev] + [total]
        if not parts_add_up(parts, _cell(ft, column, cents)["value"]):
            raise FinanceError(f"dollar split: {book['id']} fund {cfg['fund']}: revenue and department totals do not "
                               f"add up to the printed {ft['label_as_printed']!r}")
        basis = {"kind": "net", "line": ft}
    else:
        raise FinanceError(f"dollar split: {book['id']} fund {cfg['fund']} prints no fund total to check against")

    # Departments in book order (the first printed total of each), each with its printed totals.
    groups: dict[str, dict] = {}
    for t, a in zip(dept_totals, amounts):
        key, name = _group_key(t, cfg)
        g = groups.setdefault(key, {"key": key, "name": name, "members": [], "amounts": []})
        g["members"].append(t)
        g["amounts"].append(a)
    for g in groups.values():
        g["amount"] = total_of(g["amounts"])

    def member(t: dict, a: int) -> dict:
        """One printed department total: its amount exactly as printed ("-", ".00"), its row and its PDF page."""
        return {"heading": t["heading_as_printed"], "label": t["label_as_printed"],
                "amount": _cell(t, column, cents)["as_printed"], "value": a,
                "page": t["page"], "href": href_of(t["id"]), "src": bg.src(t), "line_id": t["id"]}

    def row(key: str, name: str, members: list[tuple[dict, int]], amount: int) -> dict:
        ms = [member(t, a) for t, a in members]
        srcs = list({m["src"]["url"]: m["src"] for m in ms}.values())
        return {"key": key, "name": name, "amount": money(amount), "value": amount, "members": ms, "srcs": srcs,
                "href": ms[0]["href"], "fact_id": f"dollar/{book['id']}/{slug(key)}",
                "printed_as": len(ms) > 1 or ms[0]["heading"] != name}

    zero = [g for g in groups.values() if g["amount"] == 0]
    live = [g for g in groups.values() if g["amount"] > 0]
    small = [g for g in live if g["amount"] * OTHER_BELOW < total]
    shown = [g for g in live if g not in small]
    rows = [row(g["key"], g["name"], list(zip(g["members"], g["amounts"])), g["amount"]) for g in shown]
    other = None
    if small:
        amount = total_of([g["amount"] for g in small])
        other = row("other", T["other_name"].format(n=len(small)),
                    [(t, a) for g in small for t, a in zip(g["members"], g["amounts"])], amount)
        other["departments"] = [{"name": g["name"], "amount": money(g["amount"]),
                                 "members": [member(t, a) for t, a in zip(g["members"], g["amounts"])]} for g in small]
        other["printed_as"] = False
        other["srcs"] = []   # every page is in the row's own list
        rows.append(other)
    shares, nearest_sum, moved = cents_of_dollar([r["value"] for r in rows], total)
    for i, (r, c) in enumerate(zip(rows, shares)):
        r["cents"] = c
        r["moved"] = i in moved
        r["cents_words"] = T["cent_one"] if c == 1 else T["cents_many"].format(n=c)
        r["labelled"] = c >= T_LABEL_MIN
        r["narrow"] = c < T_PHONE_MIN
        r["short"] = T["other_short"] if r is other else r["name"]
    ft = basis["line"]
    fsrc = bg.src(ft)
    total_text = (T["total_printed"] if basis["kind"] == "printed" else T["total_net"]).format(
        amount=money(total), label=ft["label_as_printed"], n=len(dept_totals), cite="{cite}").split("{cite}")
    year = first["fiscal_year"]
    rounding = T["rounding_exact"] if not moved else T["rounding_moved" if len(moved) > 1 else "rounding_moved_one"].format(
        sum=nearest_sum, n=len(moved), names="; ".join(rows[i]["name"] for i in moved),
        way=T["way_less"] if nearest_sum > 100 else T["way_more"],
        most=T["most_up"] if nearest_sum > 100 else T["most_down"])
    rev_pages = sorted({x["page"] for x in lines if x["statement"] == "revenue" and x["row_role"] == "detail"})
    out = {
        "heading": T["heading"],
        "lede": T["lede"].format(year=year, body=cfg["body"]),
        # the key under the bar: the rows whose segment carries its cents, in the bar's (the book's) order
        "key": [r for r in rows if r["labelled"]],
        "key_note": T["key_note"].format(n=T_LABEL_MIN),
        "total_line": T["total_line"].format(body=cfg["body"], amount=caption_amount(money(total))),
        "total_amount": T["total_amount"].format(amount=money(total)),
        "source": T["source"].format(book=book["title"], header=column, fund=ft["fund_name"] or cfg["fund"]),
        "rows": rows, "other": other, "total": money(total), "total_cents": total_of(shares),
        "total_src": fsrc, "total_href": href_of(ft["id"]),
        "total_before": total_text[0], "total_after": total_text[1],
        "measures": T["measures"].format(body=cfg["body"]),
        "tax": T["tax"] if rev_pages else None,
        "tax_src": bg.fx.src(book["source_id"], rev_pages[0]) if rev_pages else None,
        "tax_pages": (f"pp. {rev_pages[0]}-{rev_pages[-1]}" if len(rev_pages) > 1 else f"p. {rev_pages[0]}")
        if rev_pages else None,
        "rounding": T["rounding"] + " " + rounding,
        "order": T["order"],
        "transfers": T["transfers"] if any("transfer" in t["tags"] for t in dept_totals) else None,
        "note": note,
        "zero": [{"name": g["name"], "members": [member(t, a) for t, a in zip(g["members"], g["amounts"])]}
                 for g in zero],
        "zero_heading": T["zero"].format(header=column, n=len(zero)),
        "col_amount": column, "kind": config.FIN_TEXT["budget"]["kinds"][first["kind"]],
        "caption": T["caption"].format(year=year), "t": T,
        "book_id": book["id"], "fund": cfg["fund"], "value_total": total, "total_fact_id": f"dollar/{book['id']}/total",
    }
    return out


def fact_ids(fin: dict | None, locality: str) -> set[str]:
    """Every data-fact-id the general fund dollar puts on a body's Finance index (each row, Other and the total), from
    the same split the page renders: qa/site_checks.py reads this so the two never drift."""
    if not fin or not fin.get("budget_lines"):
        return set()
    d = split(Budget(Finance(fin, []), None), load(locality))
    return set() if d is None else {r["fact_id"] for r in d["rows"]} | {d["total_fact_id"]}
