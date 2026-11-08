"""Load and check config/localities/<locality>/finance.yml (task F1, architecture A2).

Every finance adapter reads its URLs, labels and word lists from here, so the code holds no locality literal
(AC-F12). A missing key, a wrong type, an unknown stage or a regex that does not compile fails the load loudly
(FinanceConfigError); nothing falls back to a default.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
# The stage enum of schema/finance.schema.json (document.stage).
STAGES = ("bid_tab", "award_letter", "partial_award", "notice_of_intent", "notice_of_award", "bid", "rfp", "rfq",
          "addendum", "qa", "forms", "advertisement", "drawings", "other")
BIDTAB_FIELDS = ("project", "department", "bid_date", "awardee", "award_date")


class FinanceConfigError(Exception):
    pass


@dataclass(frozen=True)
class BidTabRules:
    fields: dict                 # key -> label as printed
    columns: dict                # name / total -> header words
    optional_columns: tuple
    table_end: tuple


KINDS = ("actual", "amended", "adopted", "projected")      # schema column.kind
STATEMENTS = ("revenue", "expenditure", "fund_balance")    # schema budget_line.statement
TAGS = ("transfer", "non_revenue")                         # tags set by rule; available_funds = fund_balance rows


@dataclass(frozen=True)
class BookSpec:
    id: str
    title: str
    edition: str
    fiscal_year: int
    url: str
    first_page: int
    last_page: int


@dataclass(frozen=True)
class BudgetRules:
    books: tuple                 # BookSpec, ...
    page_titles: dict            # exact title line -> statement
    kind_words: tuple            # ((word, kind), ...) first match wins
    ignore_words: tuple
    header_words: tuple
    year: re.Pattern
    fund_line: re.Pattern
    account_code: re.Pattern
    subtotal_labels: tuple
    total: re.Pattern
    fund_totals: tuple           # compiled
    scope_break_after: tuple     # compiled
    footer: re.Pattern
    tag_codes: dict              # tag -> frozenset of account codes
    tag_headings: dict           # tag -> frozenset of casefolded headings
    fund_balance_labels: tuple   # compiled


def _cs_regex(pattern, key: str) -> re.Pattern:
    """A case-sensitive regex (budget row labels: "Total " is a total, "TOTAL" on a summary page is not read)."""
    if not isinstance(pattern, str):
        raise FinanceConfigError(f"finance.yml: {key} must be a regex string")
    try:
        return re.compile(pattern)
    except re.error as e:
        raise FinanceConfigError(f"finance.yml: {key}: bad regex {pattern!r}: {e}") from None


def parse_budget(budget: dict) -> BudgetRules:
    w = "budget."
    books = []
    raw_books = _need(budget, "books", list, w)
    if not raw_books:
        raise FinanceConfigError("finance.yml: budget.books is empty")
    for i, b in enumerate(raw_books):
        where = f"budget.books[{i}]."
        for k, t in (("id", str), ("title", str), ("edition", str), ("fiscal_year", int), ("url", str),
                     ("pages", list)):
            _need(b, k, t, where)
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", b["id"]):
            raise FinanceConfigError(f"finance.yml: {where}id {b['id']!r} is not a book id")
        if urllib.parse.urlsplit(b["url"]).scheme != "https":
            raise FinanceConfigError(f"finance.yml: {where}url must be https")
        pages = b["pages"]
        if not (len(pages) == 2 and all(isinstance(p, int) and p >= 1 for p in pages) and pages[0] <= pages[1]):
            raise FinanceConfigError(f"finance.yml: {where}pages must be [first, last]")
        books.append(BookSpec(b["id"], b["title"], b["edition"], b["fiscal_year"], b["url"], pages[0], pages[1]))
    if len({b.id for b in books}) != len(books):
        raise FinanceConfigError("finance.yml: budget.books ids repeat")
    titles = _need(budget, "page_titles", dict, w)
    if set(titles) != set(STATEMENTS) or not all(isinstance(v, str) and v.strip() for v in titles.values()):
        raise FinanceConfigError(f"finance.yml: budget.page_titles must name {', '.join(STATEMENTS)}")
    kinds = []
    for i, kw in enumerate(_need(budget, "kind_words", list, w)):
        if not (isinstance(kw, list) and len(kw) == 2 and all(isinstance(x, str) for x in kw)) or kw[1] not in KINDS:
            raise FinanceConfigError(f"finance.yml: budget.kind_words[{i}] must be [word, one of {KINDS}]")
        kinds.append((kw[0], kw[1]))
    if not kinds:
        raise FinanceConfigError("finance.yml: budget.kind_words is empty")
    rows = _need(budget, "rows", dict, w)
    for k in ("fund_line", "account_code", "subtotal_labels", "total", "fund_totals", "scope_break_after", "footer"):
        _need(rows, k, None, "budget.rows.")
    fund_line = _cs_regex(rows["fund_line"], "budget.rows.fund_line")
    if not {"name", "no"} <= set(fund_line.groupindex):
        raise FinanceConfigError("finance.yml: budget.rows.fund_line needs groups (?P<name>) and (?P<no>)")
    tags = _need(budget, "tags", dict, w)
    if set(tags) != set(TAGS):
        raise FinanceConfigError(f"finance.yml: budget.tags must name {', '.join(TAGS)}")
    tag_codes, tag_headings = {}, {}
    for t in TAGS:
        _need(tags[t], "codes", list, f"budget.tags.{t}.")
        _need(tags[t], "headings", list, f"budget.tags.{t}.")
        tag_codes[t] = frozenset(_strings(tags[t]["codes"], f"budget.tags.{t}.codes", True))
        tag_headings[t] = frozenset(h.casefold() for h in _strings(tags[t]["headings"], f"budget.tags.{t}.headings",
                                                                     True))
    return BudgetRules(
        books=tuple(books), page_titles={v: k for k, v in titles.items()}, kind_words=tuple(kinds),
        ignore_words=_strings(_need(budget, "ignore_words", list, w), "budget.ignore_words"),
        header_words=_strings(_need(budget, "header_words", list, w), "budget.header_words", True),
        year=_cs_regex(_need(budget, "year", str, w), "budget.year"),
        fund_line=fund_line, account_code=_cs_regex(rows["account_code"], "budget.rows.account_code"),
        subtotal_labels=_strings(rows["subtotal_labels"], "budget.rows.subtotal_labels"),
        total=_cs_regex(rows["total"], "budget.rows.total"),
        fund_totals=tuple(_cs_regex(p, "budget.rows.fund_totals") for p in
                          _strings(rows["fund_totals"], "budget.rows.fund_totals")),
        scope_break_after=tuple(_cs_regex(p, "budget.rows.scope_break_after") for p in
                                _strings(rows["scope_break_after"], "budget.rows.scope_break_after", True)),
        footer=_cs_regex(rows["footer"], "budget.rows.footer"),
        tag_codes=tag_codes, tag_headings=tag_headings,
        fund_balance_labels=tuple(_cs_regex(p, "budget.fund_balance_labels") for p in
                                  _strings(_need(budget, "fund_balance_labels", list, w), "budget.fund_balance_labels")))


@dataclass(frozen=True)
class FinanceConfig:
    archive_url: str
    archive_host: str
    archive_header: tuple
    status_words: tuple
    date_formats: tuple
    stage_rules: tuple           # ((stage, compiled regex), ...)
    bonfire_hosts: tuple
    scan_producers: tuple        # compiled regexes
    bidtab: BidTabRules
    budget: BudgetRules
    capital_fund: str


def locality() -> str:
    return yaml.safe_load((ROOT / "config" / "site.yml").read_text(encoding="utf-8"))["locality"]


def default_path() -> Path:
    return ROOT / "config" / "localities" / locality() / "finance.yml"


def _need(cfg: dict, key: str, kind, where: str = ""):
    if not isinstance(cfg, dict) or key not in cfg:
        raise FinanceConfigError(f"finance.yml: missing key {where}{key}")
    v = cfg[key]
    if kind is not None and not isinstance(v, kind):
        raise FinanceConfigError(f"finance.yml: {where}{key} must be {getattr(kind, '__name__', kind)}, "
                                 f"not {type(v).__name__}")
    return v


def _strings(v, key: str, allow_empty: bool = False) -> tuple:
    if not isinstance(v, list) or (not v and not allow_empty) or not all(isinstance(x, str) and x.strip() for x in v):
        raise FinanceConfigError(f"finance.yml: {key} must be a non-empty list of non-empty strings")
    return tuple(v)


def _regex(pattern: str, key: str) -> re.Pattern:
    try:
        return re.compile(pattern, re.I)
    except re.error as e:
        raise FinanceConfigError(f"finance.yml: {key}: bad regex {pattern!r}: {e}") from None


def parse(cfg: dict) -> FinanceConfig:
    if not isinstance(cfg, dict):
        raise FinanceConfigError("finance.yml: not a mapping")
    url = _need(cfg, "archive_url", str)
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        raise FinanceConfigError(f"finance.yml: archive_url must be an https URL, not {url!r}")
    header = _strings(_need(cfg, "archive_header", list), "archive_header")
    if len(header) != 3:
        raise FinanceConfigError("finance.yml: archive_header must name the 3 header cells")
    rules = []
    for i, r in enumerate(_need(cfg, "stage_rules", list)):
        if not (isinstance(r, list) and len(r) == 2 and all(isinstance(x, str) for x in r)):
            raise FinanceConfigError(f"finance.yml: stage_rules[{i}] must be [stage, regex]")
        if r[0] not in STAGES:
            raise FinanceConfigError(f"finance.yml: stage_rules[{i}]: unknown stage {r[0]!r}")
        rules.append((r[0], _regex(r[1], f"stage_rules[{i}]")))
    if not rules:
        raise FinanceConfigError("finance.yml: stage_rules is empty")
    for f in _strings(_need(cfg, "date_formats", list), "date_formats"):
        if "%" not in f:
            raise FinanceConfigError(f"finance.yml: date_formats: {f!r} is not a strptime format")
    bt = _need(cfg, "bidtab", dict)
    fields = _need(bt, "fields", dict, "bidtab.")
    for k in BIDTAB_FIELDS:
        if not isinstance(fields.get(k), str) or not fields[k].strip():
            raise FinanceConfigError(f"finance.yml: missing key bidtab.fields.{k}")
    cols = _need(bt, "columns", dict, "bidtab.")
    for k in ("name", "total"):
        if not isinstance(cols.get(k), str) or not cols[k].strip():
            raise FinanceConfigError(f"finance.yml: missing key bidtab.columns.{k}")
    budget = parse_budget(_need(cfg, "budget", dict))
    capital = _need(cfg, "capital_fund", str)
    if not re.fullmatch(r"\d{3}", capital):
        raise FinanceConfigError(f"finance.yml: capital_fund must be a 3-digit fund number, not {capital!r}")
    return FinanceConfig(
        archive_url=url, archive_host=parts.netloc.lower(), archive_header=header,
        status_words=_strings(_need(cfg, "status_words", list), "status_words"),
        date_formats=tuple(cfg["date_formats"]), stage_rules=tuple(rules),
        bonfire_hosts=tuple(h.lower() for h in _strings(_need(cfg, "bonfire_hosts", list), "bonfire_hosts")),
        scan_producers=tuple(_regex(p, "scan_producers") for p in
                             _strings(_need(cfg, "scan_producers", list), "scan_producers")),
        bidtab=BidTabRules(fields={k: fields[k] for k in BIDTAB_FIELDS}, columns={k: cols[k] for k in ("name", "total")},
                           optional_columns=_strings(bt.get("optional_columns", []), "bidtab.optional_columns", True),
                           table_end=_strings(bt.get("table_end", []), "bidtab.table_end", True)),
        budget=budget, capital_fund=capital)


def load(path: Path | None = None) -> FinanceConfig:
    path = Path(path) if path else default_path()
    if not path.is_file():
        raise FinanceConfigError(f"{path}: no finance config for this locality")
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")))
