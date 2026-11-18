"""The county property tax dollar (docs/architecture/finance-contracts.md 12): on the county's Finance index, above the
general fund dollar, how each dollar of the county property tax splits across the funds the tax rate resolution levies
it for, schools included, in cents that add up to 100. Owner's request 2026-11-18.

One column of one tax rate resolution, from config/localities/<locality>/property-tax-split.yml: each fund's rate
exactly as printed (per $100 of assessed value), and its share is rate / total rate. The resolution is a page of a
budget book already in finance.json, so every row cites that page. The rates are checked against the page's own total
and against the book: every fund the book budgets current property tax for (the configured account, adopted column) is
one row, and each of those amounts is the same multiple of its rate. Anything that does not hold fails the build: a
wrong rate must never reach the page. Rows keep the resolution's order (no amount sort, neutrality/*); adding goes
through collector.fin_checks (budget-reconcile/*). Shares are in tenths of a cent (tenths_of_dollar, largest remainder,
a tie to the larger exact share), so near-equal rates are never told apart by a whole-cent tie break
(property-tax-split/tie-understates-schools)."""
from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path

import yaml

from collector.fin_checks import tenths_of_dollar, total_of

from . import config
from .budget_views import Budget, dollars, fund_key
from .dollar_split import T_LABEL_MIN, T_PHONE_MIN, slug
from .fin_views import Finance, FinanceError

T = config.FIN_TEXT["property_tax"]
RATE_RE = re.compile(r"\$?(\d+)\.(\d{3})")      # a rate as the resolution's table prints it: "$1.130", "0.140"
RATE2_RE = re.compile(r"\$(\d+)\.(\d{2})")      # Section 1's combined rate: "$2.10"
FILE = "property-tax-split.yml"


def tenths_text(t: int) -> str:
    """Tenths of a cent as the page prints them: 538 -> "53.8", 1000 -> "100.0"."""
    return f"{t // 10}.{t % 10}"


def _thousandths(text: str, rx: re.Pattern, where: str) -> int:
    """A printed rate as an integer in thousandths of a dollar per $100 ("$1.130" -> 1130, "$2.10" -> 2100)."""
    m = rx.fullmatch(text or "")
    if not m:
        raise FinanceError(f"property tax split: {where} {text!r} is not a rate as printed")
    whole, frac = m.groups()
    return int(whole) * 1000 + int(frac) * (1000 // 10 ** len(frac))


def load(locality: str) -> dict | None:
    """config/localities/<locality>/property-tax-split.yml, or None when the locality has none. A file that is there
    but missing any part fails: a partial config never builds a partial bar."""
    path = config.CONFIG_DIR / "localities" / locality / FILE
    if not Path(path).is_file():
        return None
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for key in ("book", "resolution", "title", "rate_as_printed", "column", "total_as_printed", "check_account",
                "check_column"):
        if not isinstance(cfg.get(key), str) or not cfg[key].strip():
            raise FinanceError(f"{path}: `{key}` must be a non-empty string")
    for key in ("page", "fiscal_year"):
        if not isinstance(cfg.get(key), int) or isinstance(cfg.get(key), bool) or cfg[key] < 1:
            raise FinanceError(f"{path}: `{key}` must be a whole number")
    funds = cfg.get("funds")
    if not isinstance(funds, list) or len(funds) < 2:
        raise FinanceError(f"{path}: `funds` must list every fund the resolution prints (two or more)")
    for i, f in enumerate(funds):
        if not isinstance(f, dict):
            raise FinanceError(f"{path}: funds[{i}] must be a mapping")
        for key in ("printed", "rate", "name"):
            if not isinstance(f.get(key), str) or not f[key].strip():
                raise FinanceError(f"{path}: funds[{i}] needs `{key}` (a non-empty string)")
        if "fund" not in f or not (f["fund"] is None or isinstance(f["fund"], str) and f["fund"]):
            raise FinanceError(f"{path}: funds[{i}] needs `fund` (the book's fund number, or null)")
    for key in ("printed", "name"):
        seen = [f[key].casefold() for f in funds]
        if len(set(seen)) != len(seen):
            raise FinanceError(f"{path}: two funds share a `{key}`")
    nums = [f["fund"] for f in funds if f["fund"]]
    if len(set(nums)) != len(nums):
        raise FinanceError(f"{path}: two funds share a book fund number")
    return cfg


def _check_against_book(bg: Budget, book: dict, cfg: dict, rates: list[int]) -> dict:
    """Every fund the book budgets the configured account for, in the adopted column, is one row of the resolution,
    and each of those amounts is the same multiple of its rate (amount_i * rate_j == amount_j * rate_i, integers)."""
    lines = [x for x in bg.lines if x["book_id"] == book["id"] and x.get("account_code") == cfg["check_account"]
             and x["statement"] == "revenue" and x["row_role"] == "detail"]
    by_fund: dict[str, list] = {}
    for x in lines:
        by_fund.setdefault(fund_key(x), []).append(x)
    mapped = {f["fund"]: i for i, f in enumerate(cfg["funds"]) if f["fund"]}
    if not lines:
        raise FinanceError(f"property tax split: {book['id']} prints no account {cfg['check_account']} line to check "
                           "the rates against")
    unmapped = sorted(set(by_fund) - set(mapped))
    if unmapped:
        raise FinanceError(f"property tax split: {book['id']} budgets account {cfg['check_account']} in fund(s) "
                           f"{', '.join(unmapped)}, which no row of the resolution names")
    missing = sorted(set(mapped) - set(by_fund))
    if missing:
        raise FinanceError(f"property tax split: fund(s) {', '.join(missing)} have no account {cfg['check_account']} "
                           f"line in {book['id']}")
    checked = []
    for fund, i in mapped.items():   # the resolution's order
        if len(by_fund[fund]) != 1:
            raise FinanceError(f"property tax split: fund {fund} prints account {cfg['check_account']} "
                               f"{len(by_fund[fund])} times in {book['id']}, not once")
        x = by_fund[fund][0]
        if x["held"]:
            raise FinanceError(f"property tax split: line {x['id']} is held ({x['held']})")
        cells = [c for c in x["cells"] if c["header_as_printed"] == cfg["check_column"]]
        if len(cells) != 1 or cells[0].get("dollars") is None:
            raise FinanceError(f"property tax split: line {x['id']} prints no single amount in {cfg['check_column']!r}")
        c = cells[0]
        if c["kind"] != "adopted" or c["fiscal_year"] != cfg["fiscal_year"]:
            raise FinanceError(f"property tax split: column {cfg['check_column']!r} of {x['id']} is {c['kind']} "
                               f"FY{c['fiscal_year']}, not adopted FY{cfg['fiscal_year']}")
        checked.append({"fund": fund, "printed": cfg["funds"][i]["printed"], "rate": rates[i], "amount": c["dollars"],
                        "as_printed": c["as_printed"], "page": x["page"], "line": x})
    a0, r0 = checked[0]["amount"], checked[0]["rate"]
    for c in checked[1:]:
        if c["amount"] * r0 != a0 * c["rate"]:
            raise FinanceError(f"property tax split: fund {c['fund']}'s {cfg['check_account']} amount "
                               f"{c['as_printed']} is not the same multiple of its rate as fund {checked[0]['fund']}'s: "
                               "the rates and the book disagree")
    per = Fraction(a0 * 1000, r0)    # dollars of that revenue for each $1.000 of rate
    return {"lines": checked, "per_dollar": dollars(per.numerator) if per.denominator == 1 else None}


def split(bg: Budget, cfg: dict | None, dollar_fund: str | None = None) -> dict | None:
    """The view of the county property tax dollar, or None when there is no config (a body without one, or a FIXTURE
    build; a config whose book is missing raises, never None: property-tax-split/silent-hide). `dollar_fund`: the
    fund the general fund dollar on the same page splits; its row links down to that bar."""
    if cfg is None:
        return None
    book = bg.book.get(cfg["book"])
    if book is None:
        raise FinanceError(f"property tax split: book {cfg['book']} is not in finance.json")
    if book["source_id"] not in bg.fx.sources:
        raise FinanceError(f"property tax split: source {book['source_id']} of {book['id']} is not in finance.json")
    if book["fiscal_year"] != cfg["fiscal_year"]:
        raise FinanceError(f"property tax split: {book['id']} is FY{book['fiscal_year']}, the config says "
                           f"FY{cfg['fiscal_year']}")
    for b in bg.books:   # property-tax-split/stale-book: a newer adopted book means a newer levy to show
        if b["fiscal_year"] > cfg["fiscal_year"] and any(
                c["kind"] == "adopted" and c["fiscal_year"] == b["fiscal_year"] for c in b["columns"]):
            raise FinanceError(f"property tax split: {b['id']} prints an adopted FY{b['fiscal_year']} budget, newer "
                               f"than FY{cfg['fiscal_year']}: point property-tax-split.yml at its tax rate resolution")
    rates = [_thousandths(f["rate"], RATE_RE, f"rate of {f['printed']}") for f in cfg["funds"]]
    if any(r <= 0 for r in rates):
        raise FinanceError("property tax split: every rate must be above zero")
    total = _thousandths(cfg["total_as_printed"], RATE_RE, "Total Tax Rate")
    if total_of(rates) != total:
        raise FinanceError(f"property tax split: the fund rates do not add up to the printed Total Tax Rate "
                           f"{cfg['total_as_printed']}")
    if _thousandths(cfg["rate_as_printed"], RATE2_RE, "Section 1 rate") != total:
        raise FinanceError(f"property tax split: Section 1's rate {cfg['rate_as_printed']} is not the printed Total "
                           f"Tax Rate {cfg['total_as_printed']}")
    check = _check_against_book(bg, book, cfg, rates)
    src = bg.fx.src(book["source_id"], cfg["page"])
    href_of = bg.href_from(bg.index)
    shares, nearest_sum, moved = tenths_of_dollar(rates, total)
    base = f"proptax/{book['id']}"
    rows = []
    for i, (f, r, t) in enumerate(zip(cfg["funds"], rates, shares)):
        rows.append({
            "key": slug(f["printed"]), "name": f["name"], "printed": f["printed"], "rate": f["rate"], "value": r,
            "tenths": t, "cents": tenths_text(t), "moved": i in moved,
            "labelled": t >= 10 * T_LABEL_MIN, "narrow": t < 10 * T_PHONE_MIN, "short": f["name"],
            "cents_words": T["cents_many"].format(n=tenths_text(t)),
            "printed_as": f["printed"] != f["name"], "src": src, "fact_id": f"{base}/{slug(f['printed'])}",
            "fund": f["fund"], "to_dollar": bool(dollar_fund) and f["fund"] == dollar_fund,
        })
    rounding = T["rounding_exact"] if not moved else T["rounding_moved" if len(moved) > 1 else "rounding_moved_one"].format(
        sum=tenths_text(nearest_sum), names="; ".join(rows[i]["name"] for i in moved),
        way=T["way_less"] if nearest_sum > 1000 else T["way_more"])
    ck = check["lines"]
    return {
        "heading": T["heading"],
        "lede": T["lede"].format(year=cfg["fiscal_year"], rate=cfg["rate_as_printed"], n=len(rows), book=book["title"]),
        "rate_line": T["rate_line"].format(rate=cfg["rate_as_printed"]),
        "other_money": T["other_money"], "city": T["city"],
        "key": [r for r in rows if r["labelled"]],
        "key_note": T["key_note"].format(n=T_LABEL_MIN),
        "source": T["source"].format(number=cfg["resolution"], title=cfg["title"], book=book["title"],
                                     column=cfg["column"]),
        "src": src, "rows": rows, "total_cents": tenths_text(total_of(shares)), "total": cfg["total_as_printed"],
        "rate": cfg["rate_as_printed"], "column": cfg["column"],
        "rounding": T["rounding"] + " " + rounding, "order": T["order"],
        "check": T["check"].format(n=len(ck), account=cfg["check_account"], column=cfg["check_column"]),
        "check_cites": [{"label": c["printed"], "amount": c["as_printed"], "src": bg.src(c["line"]),
                         "href": href_of(c["line"]["id"])} for c in ck],
        "per_dollar": T["per_dollar"].format(amount=check["per_dollar"]) if check["per_dollar"] else None,
        "caption": T["caption"].format(year=cfg["fiscal_year"]), "t": T,
        "book_id": book["id"], "total_fact_id": f"{base}/total",
    }


def fact_ids(fin: dict | None, locality: str) -> set[str]:
    """Every data-fact-id the property tax dollar puts on a body's Finance index (each fund and the total), from the
    same split the page renders: qa/site_checks.py reads this so the two never drift."""
    if not fin or not fin.get("budget_lines"):
        return set()
    cfg = load(locality)
    if cfg is None:
        return set()
    d = split(Budget(Finance(fin, []), None), cfg)
    return {r["fact_id"] for r in d["rows"]} | {d["total_fact_id"]}
