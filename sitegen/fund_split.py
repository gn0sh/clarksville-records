"""The city budget dollar, by fund (docs/architecture/city-funds-dollar.md; finance-contracts 13): on the city's Finance
index, above the general fund dollar, how the whole budget of one adopted column of one book splits across its funds,
in tenths of a cent of each dollar. CEO 2026-11-18: "just break them up the same way you did with the county stuff."

One column of one book, from config/localities/<locality>/fund-split.yml. No city fund prints a spending-only total
(its "TOTAL <fund>" line adds revenue and spending together), so each fund's amount is its printed spending section
totals added up, and checked the dollar bar's `total_net` way: those totals and the fund's printed revenue totals give
its printed "TOTAL <fund>" line to the cent. The bar's total is the book's own printed "TOTAL EXPENSE" lines of its
report runs, and the funds of each run add up to that run's TOTAL EXPENSE exactly. Money one fund pays another is shown
as printed, in both funds, never taken out; the revenue lines other funds print as received from the general fund are
listed in the sources block. Rows keep the book's order (no amount sort, neutrality/*); adding goes through
collector.fin_checks (budget-reconcile/*). Anything that does not hold fails the build (problem keys fund-split/*):
a wrong figure must never reach the page."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from collector.fin_checks import parts_add_up, tenths_of_dollar, total_of

from . import config
from .budget_views import Budget, cents_text, dollars, fund_key, usd
from .dollar_split import T_LABEL_MIN, T_PHONE_MIN, _cell, _exact_in_column, _newer_books_note, slug
from .fin_views import Finance, FinanceError
from .property_tax import tenths_text

T = config.FIN_TEXT["fund_split"]
FILE = "fund-split.yml"


def load(locality: str) -> dict | None:
    """config/localities/<locality>/fund-split.yml, or None when the locality has none. A file that is there but
    missing any part fails: a partial config never builds a partial bar."""
    path = config.CONFIG_DIR / "localities" / locality / FILE
    if not Path(path).is_file():
        return None
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for key in ("book", "column", "body", "dollar_fund"):
        if not isinstance(cfg.get(key), str) or not cfg[key].strip():
            raise FinanceError(f"{path}: `{key}` must be a non-empty string")
    fg = cfg.get("from_general_fund")
    if not isinstance(fg, dict):
        raise FinanceError(f"{path}: `from_general_fund` must be a mapping (accounts, label_token)")
    accounts = fg.get("accounts")
    if not isinstance(accounts, list) or not accounts or not all(isinstance(a, str) and a.strip() for a in accounts):
        raise FinanceError(f"{path}: `from_general_fund.accounts` must list account codes (non-empty strings)")
    if not isinstance(fg.get("label_token"), str) or not fg["label_token"].strip():
        raise FinanceError(f"{path}: `from_general_fund.label_token` must be a non-empty string")
    funds = cfg.get("funds")
    if not isinstance(funds, list) or len(funds) < 2:
        raise FinanceError(f"{path}: `funds` must list every fund the book prints (two or more)")
    for i, f in enumerate(funds):
        if not isinstance(f, dict):
            raise FinanceError(f"{path}: funds[{i}] must be a mapping")
        for key in ("printed", "name"):
            if not isinstance(f.get(key), str) or not f[key].strip():
                raise FinanceError(f"{path}: funds[{i}] needs `{key}` (a non-empty string)")
    for key in ("printed", "name"):
        seen = [f[key].casefold() for f in funds]
        if len(set(seen)) != len(seen):
            raise FinanceError(f"{path}: two funds share a `{key}`")
    return cfg


def _is_section(x: dict) -> bool:
    """A printed spending section total of a fund: the only kind of line a row's amount is built from
    (fund-split/no-double-count: never a revenue, net or run total line)."""
    return bool(x["fund_name"]) and x["statement"] == "expenditure" and x["row_role"] == "total" and bool(x["department"])


def _once_inside(parts: list[dict], wholes: list[dict], what: str) -> dict[str, list[dict]]:
    """Each part (a section total) lies inside exactly one whole's scope (a fund net total or a run TOTAL EXPENSE):
    {whole id: its parts}, in book order."""
    scopes = [(w, set(w["scope_line_ids"])) for w in wholes]
    out: dict[str, list[dict]] = {w["id"]: [] for w in wholes}
    for p in parts:
        inside = [w for w, s in scopes if set(p["scope_line_ids"]) <= s]
        if len(inside) != 1:
            raise FinanceError(f"fund split: total {p['id']} lies inside {len(inside)} {what} lines, not exactly one")
        out[inside[0]["id"]].append(p)
    return out


def split(bg: Budget, cfg: dict | None, dollar: dict | None = None) -> dict | None:
    """The view of the city budget dollar by fund, or None when there is no config (a body without one; a config whose
    book is missing raises, never None: fund-split/silent-hide). `dollar`: the general fund dollar on the same page
    (dollar_split.split): its fund's row links down to it, and must equal its total (fund-split/dollar-match). Call
    this after the fund pages are planned (Budget.line_pages), as the general fund dollar."""
    if cfg is None:
        return None
    book = bg.book.get(cfg["book"])
    if book is None:
        raise FinanceError(f"fund split: book {cfg['book']} is not in finance.json")
    column, cents = cfg["column"], bg.cents(book["id"])
    money = cents_text if cents else dollars

    def prose(n: int) -> str:
        return usd(n) if cents else "$" + dollars(n)

    lines = [x for x in bg.lines if x["book_id"] == book["id"]]
    href_of = bg.href_from(bg.index)

    # fund-split/fund-list: the config's funds are exactly the book's, in its order (first page, then row), each once.
    in_book = list(dict.fromkeys(x["fund_name"] for x in lines if x["fund_name"]))
    want = [f["printed"] for f in cfg["funds"]]
    if in_book != want:
        missing = [f for f in in_book if f not in want]
        extra = [f for f in want if f not in in_book]
        raise FinanceError(f"fund split: fund-split.yml funds are not the funds {book['id']} prints, in its order "
                           f"(not in the config: {missing}; not in the book: {extra})")

    # Every cell read: the adopted budget of one fiscal year (fund-split/exact).
    year: list[int] = []

    def read(line: dict) -> dict:
        c = _cell(line, column, cents)
        if c["kind"] != "adopted" or (year and c["fiscal_year"] != year[0]):
            raise FinanceError(f"fund split: {line['id']} column {column!r} is {c['kind']} FY{c['fiscal_year']}, not "
                               f"adopted{f' FY{year[0]}' if year else ''}")
        year[:] = year or [c["fiscal_year"]]
        return c

    sections = [x for x in lines if _is_section(x)]
    if not sections:
        raise FinanceError(f"fund split: {book['id']} prints no spending section totals")
    amount = {}
    for t in sections:
        amount[t["id"]] = read(t)["value"]
    note = _newer_books_note(bg, book, year[0])       # fund-split/stale-book: a newer adopted book fails here
    for t in sections:
        _exact_in_column(t, column)
        if amount[t["id"]] < 0:
            raise FinanceError(f"fund split: {book['id']} prints a negative spending total ({t['id']})")

    # fund-split/run-total and covered-once across the book: every spending detail line sits under exactly one run
    # TOTAL EXPENSE (fund_name None: a report-run total, never a row), and each run's section totals add up to it.
    runs = [x for x in lines if x["fund_name"] is None and x["statement"] == "expenditure" and x["row_role"] == "total"]
    if not runs:
        raise FinanceError(f"fund split: {book['id']} prints no report-run TOTAL EXPENSE line to check the total against")
    details = [x["id"] for x in lines if x["statement"] == "expenditure" and x["row_role"] == "detail"]
    in_runs = [i for e in runs for i in e["scope_line_ids"]]
    if len(in_runs) != len(details) or set(in_runs) != set(details):
        raise FinanceError(f"fund split: {book['id']}: the TOTAL EXPENSE lines do not cover every spending line "
                           "exactly once")
    run_amount = {}
    for e, parts in _once_inside(sections, runs, "TOTAL EXPENSE").items():
        line = bg.by_id[e]
        _exact_in_column(line, column)
        run_amount[e] = read(line)["value"]
        if not parts_add_up([amount[p["id"]] for p in parts], run_amount[e]):
            raise FinanceError(f"fund split: the spending totals of {e} do not add up to its printed TOTAL EXPENSE")
    total = total_of([run_amount[e["id"]] for e in runs])

    # Per fund: its section totals cover its spending lines once, and with its revenue totals give each printed
    # "TOTAL <fund>" line (fund-split/fund-net, per report run: a fund printed over several runs still checks).
    built = []
    for f in cfg["funds"]:
        fl = [x for x in lines if x["fund_name"] == f["printed"]]
        secs = [x for x in fl if _is_section(x)]
        if not secs:
            raise FinanceError(f"fund split: {book['id']} fund {f['printed']!r} prints no spending section totals")
        fdetails = {x["id"] for x in fl if x["statement"] == "expenditure" and x["row_role"] == "detail"}
        under = [i for t in secs for i in t["scope_line_ids"]]
        if len(under) != len(fdetails) or set(under) != fdetails:
            raise FinanceError(f"fund split: {book['id']} fund {f['printed']!r}: the spending totals do not cover every "
                               "spending line exactly once")
        nets = [x for x in fl if x["row_role"] == "total" and x["statement"] == "net"]
        if not nets:
            raise FinanceError(f"fund split: {book['id']} fund {f['printed']!r} prints no fund total to check against")
        revs = [x for x in fl if x["statement"] == "revenue" and x["row_role"] == "total"]
        for x in revs:
            _exact_in_column(x, column)
        for n, parts in _once_inside(revs + secs, nets, f"{f['printed']!r} fund total").items():
            line = bg.by_id[n]
            _exact_in_column(line, column)
            vals = [amount[p["id"]] if p["id"] in amount else read(p)["value"] for p in parts]
            if not parts_add_up(vals, read(line)["value"]):
                raise FinanceError(f"fund split: {book['id']} fund {f['printed']!r}: revenue and spending totals do not "
                                   f"add up to the printed {line['label_as_printed']!r} ({n})")
        built.append({"cfg": f, "key": fund_key(fl[0]), "secs": secs, "net": nets[0],
                      "value": total_of([amount[t["id"]] for t in secs])})
    if total_of([b["value"] for b in built]) != total:
        raise FinanceError(f"fund split: {book['id']}: the funds do not add up to the printed TOTAL EXPENSE lines")
    used = [t["id"] for b in built for t in b["secs"]]
    if len(used) != len(set(used)):                        # fund-split/no-double-count
        raise FinanceError(f"fund split: {book['id']}: a spending total feeds two funds")

    # fund-split/dollar-match: the general fund row is the general fund dollar's total, to the cent.
    dollar_rows = [b for b in built if b["key"] == cfg["dollar_fund"]]
    if len(dollar_rows) != 1:
        raise FinanceError(f"fund split: dollar_fund {cfg['dollar_fund']!r} names {len(dollar_rows)} of the book's "
                           "funds, not one")
    if dollar and dollar["book_id"] == book["id"] and dollar["col_amount"] == column \
            and dollar["fund"] == cfg["dollar_fund"] and dollar["value_total"] != dollar_rows[0]["value"]:
        raise FinanceError(f"fund split: the {dollar_rows[0]['cfg']['printed']!r} row is not the general fund "
                           "dollar's total")

    # fund-split/between-list: revenue lines other funds print as received from the general fund, checked both ways.
    fg = cfg["from_general_fund"]
    accounts = set(fg["accounts"])
    token = re.compile(r"(^|[^A-Za-z])" + re.escape(fg["label_token"]) + r"([^A-Za-z]|$)")
    plain = {f["printed"]: f["name"] for f in cfg["funds"]}
    between = []
    for x in lines:
        if x["statement"] != "revenue" or x["row_role"] != "detail" or not x["fund_name"] \
                or fund_key(x) == cfg["dollar_fund"]:
            continue
        by_account = x["account_code"] in accounts
        by_label = bool(token.search(x["label_as_printed"] or ""))
        if by_account != by_label:
            raise FinanceError(f"fund split: revenue line {x['id']} ({x['label_as_printed']!r}, account "
                               f"{x['account_code']}) is {'' if by_account else 'not '}under a from_general_fund "
                               f"account but has {'no ' if by_account else ''}{fg['label_token']!r} in its label")
        if not by_account:
            continue
        found = [c for c in x["cells"] if c["header_as_printed"] == column]
        if len(found) != 1:
            raise FinanceError(f"fund split: line {x['id']} prints column {column!r} {len(found)} times, not once")
        if not (found[0].get("cents") if cents else found[0].get("dollars")):
            continue
        between.append({"fund": plain[x["fund_name"]], "label": x["label_as_printed"], "amount": found[0]["as_printed"],
                        "href": href_of(x["id"]), "src": bg.src(x), "page": x["page"], "line_id": x["id"]})

    def member(t: dict) -> dict:
        """One printed spending section total: its amount exactly as printed, its row and its PDF page."""
        return {"heading": t["heading_as_printed"], "label": t["label_as_printed"],
                "amount": _cell(t, column, cents)["as_printed"], "page": t["page"], "href": href_of(t["id"]),
                "src": bg.src(t), "line_id": t["id"]}

    base = f"funds/{book['id']}"
    zero = [b for b in built if b["value"] == 0]
    live = [b for b in built if b["value"] > 0]
    shares, nearest_sum, moved = tenths_of_dollar([b["value"] for b in live], total)
    rows = []
    for i, (b, t) in enumerate(zip(live, shares)):
        f = b["cfg"]
        is_dollar = b["key"] == cfg["dollar_fund"]
        rows.append({
            "key": slug(f["printed"]), "name": f["name"], "printed": f["printed"], "printed_as": f["printed"] != f["name"],
            "value": b["value"], "amount": prose(b["value"]), "amount_printed": money(b["value"]),
            "tenths": t, "cents": tenths_text(t), "cents_words": T["cents_many"].format(n=tenths_text(t)),
            "moved": i in moved, "labelled": t >= 10 * T_LABEL_MIN, "narrow": t < 10 * T_PHONE_MIN, "short": f["name"],
            "href": href_of(b["net"]["id"]), "fund_src": bg.src(b["net"]),
            "members": [] if is_dollar else [member(x) for x in b["secs"]],
            "line_ids": [x["id"] for x in b["secs"]], "n_sections": len(b["secs"]),
            "to_dollar": is_dollar, "fact_id": f"{base}/{slug(f['printed'])}",
        })
    rounding = T["rounding_exact"] if not moved else T["rounding_moved" if len(moved) > 1 else "rounding_moved_one"].format(
        sum=tenths_text(nearest_sum), names="; ".join(rows[i]["name"] for i in moved),
        way=T["way_less"] if nearest_sum > 1000 else T["way_more"])
    n_funds = len(cfg["funds"])
    total_text = T["total"].format(amount=prose(total), runs=len(runs), cites="{cites}").split("{cites}")
    return {
        "heading": T["heading"],
        "lede": T["lede"].format(year=year[0], n=n_funds),
        "between": T["between"],
        "key": [r for r in rows if r["labelled"]],
        "key_note": T["key_note"].format(n=T_LABEL_MIN),
        "total_line": T["total_line"].format(amount=prose(total), n=n_funds),
        "source": T["source"].format(book=book["title"], header=column),
        "total_before": total_text[0], "total_after": total_text[1],
        "total_srcs": [{"label": e["label_as_printed"], "amount": _cell(e, column, cents)["as_printed"],
                        "page": e["page"], "href": href_of(e["id"]), "src": bg.src(e), "line_id": e["id"]}
                       for e in runs],
        "fund_check": T["fund_check"], "measures": T["measures"],
        "between_list": T["between_list"], "between_lines": between,
        "rounding": T["rounding"] + " " + rounding, "order": T["order"], "note": note,
        "zero": [{"name": b["cfg"]["name"], "printed": b["cfg"]["printed"], "members": [member(x) for x in b["secs"]]}
                 for b in zero],
        "zero_heading": T["zero"].format(header=column, n=len(zero)),
        "dollar_members": T["dollar_members"].format(n=len(dollar_rows[0]["secs"])),
        "rows": rows, "total": prose(total), "total_printed": money(total), "value_total": total,
        "total_cents": tenths_text(total_of(shares)),
        "col_amount": column, "kind": config.FIN_TEXT["budget"]["kinds"]["adopted"],
        "caption": T["caption"].format(year=year[0]), "t": T,
        "book_id": book["id"], "total_fact_id": f"{base}/total",
    }


def fact_ids(fin: dict | None, locality: str) -> set[str]:
    """Every data-fact-id the city budget dollar by fund puts on a body's Finance index (each fund and the total), from
    the same split the page renders: qa/site_checks.py reads this so the two never drift."""
    if not fin or not fin.get("budget_lines"):
        return set()
    cfg = load(locality)
    if cfg is None:
        return set()
    d = split(Budget(Finance(fin, []), None), cfg)
    return set() if d is None else {r["fact_id"] for r in d["rows"]} | {d["total_fact_id"]}
