"""Load and check config/localities/<locality>/finance.yml (task F1, architecture A2).

Every finance adapter reads its URLs, labels and word lists from here, so the code holds no locality literal
(AC-F12). A missing key, a wrong type, an unknown stage or a regex that does not compile fails the load loudly
(FinanceConfigError); nothing falls back to a default.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
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
class BlockRules:
    header: tuple                # the header line's columns, name column first
    header_words: tuple          # the only words allowed on the lines just above and below the header
    first_label: str             # the label that starts a bidder's block
    total_labels: tuple
    marks: tuple


@dataclass(frozen=True)
class BidTabRules:
    fields: dict                 # key -> labels as printed (tuple)
    columns: dict                # name / total -> header labels (tuple)
    optional_columns: tuple
    table_end: tuple
    blocks: BlockRules | None = None


KINDS = ("actual", "amended", "adopted", "projected", "proposed")  # schema column.kind (proposed: the city FY2027 book)
STATEMENTS = ("revenue", "expenditure", "fund_balance")    # schema budget_line.statement
RUN_STATEMENTS = STATEMENTS[:2] + ("net",)               # run_totals; net = revenue and expense together
AMOUNT_UNITS = ("dollars", "cents")
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
    kind_overrides: tuple = ()   # ((header as printed, kind), ...): this book's own meaning of a header


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
    subtotal_labels: dict        # label -> compiled regex on the account codes it adds up
    total: re.Pattern
    fund_totals: tuple           # compiled
    scope_break_after: tuple     # compiled
    footer: re.Pattern
    tag_codes: dict              # tag -> frozenset of account codes
    tag_headings: dict           # tag -> frozenset of casefolded headings
    fund_balance_labels: tuple   # compiled
    # Optional, for layouts like the city's Munis report (config/localities/clarksville-tn/finance.yml); the defaults
    # keep a book that does not set them read exactly as before.
    amount_unit: str = "dollars"         # "cents": amounts print cents ("-1,404.28", ".00"); cells carry `cents`
    header_year_lines: bool = False      # a header line holding years only belongs to the header
    fund_from_header: bool = False       # the fund line is the header's left phrase, not a row
    header_split_before: tuple = ()      # header words that always start a new phrase (band)
    ignore_tokens: tuple = ()            # compiled: tokens a derived band may hold besides derived numbers
    split_glued_amounts: bool = False    # split monospace words of touching amounts back by character width
    org_code: re.Pattern | None = None   # leading org code of rows and headings
    statement_by_code: tuple = ()        # ((statement, compiled code regex), ...): a row's statement by its code
    fund_total_by_name: bool = False     # "TOTAL <fund name, cut>" right after a section total is the fund total
    run_totals: dict = field(default_factory=dict)   # exact label -> revenue | expenditure | net (report-run totals)
    run_end: re.Pattern | None = None    # the line that ends a report run (its totals' scope)
    report_date: re.Pattern | None = None   # the page foot's report date, group "date" (book.report_dates)
    books_not_read: tuple = ()           # ({id, title, fiscal_year, url, reason}, ...): fetched and linked only


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
        over = b.get("kind_overrides", {})
        if not isinstance(over, dict) or not all(isinstance(k, str) and k.strip() and v in KINDS for k, v in over.items()):
            raise FinanceConfigError(f"finance.yml: {where}kind_overrides must map headers as printed to one of {KINDS}")
        books.append(BookSpec(b["id"], b["title"], b["edition"], b["fiscal_year"], b["url"], pages[0], pages[1],
                              tuple(sorted(over.items()))))
    if len({b.id for b in books}) != len(books):
        raise FinanceConfigError("finance.yml: budget.books ids repeat")
    titles = _need(budget, "page_titles", dict, w)
    if not titles or not set(titles) <= set(STATEMENTS) or not all(isinstance(v, str) and v.strip()
                                                                   for v in titles.values()):
        raise FinanceConfigError(f"finance.yml: budget.page_titles must name some of {', '.join(STATEMENTS)}")
    if len(set(titles.values())) != len(titles):
        raise FinanceConfigError("finance.yml: budget.page_titles repeat a title")
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
    fund_from_header = _flag(budget, "fund_from_header")
    fund_line = _cs_regex(rows["fund_line"], "budget.rows.fund_line")
    if not ({"name"} if fund_from_header else {"name", "no"}) <= set(fund_line.groupindex):
        raise FinanceConfigError("finance.yml: budget.rows.fund_line needs groups (?P<name>) and (?P<no>) (no is "
                                 "optional with fund_from_header: the fund number is then null)")
    subs = _need(rows, "subtotal_labels", dict, "budget.rows.")
    if not all(isinstance(k, str) and k.strip() for k in subs):
        raise FinanceConfigError("finance.yml: budget.rows.subtotal_labels must map labels to account-code regexes")
    subtotal_labels = {k: _cs_regex(v, f"budget.rows.subtotal_labels.{k}") for k, v in subs.items()}
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
    unit = budget.get("amount_unit", "dollars")
    if unit not in AMOUNT_UNITS:
        raise FinanceConfigError(f"finance.yml: budget.amount_unit must be one of {AMOUNT_UNITS}")
    by_code = rows.get("statement_by_code", {})
    if not isinstance(by_code, dict) or not set(by_code) <= set(STATEMENTS[:2]):
        raise FinanceConfigError("finance.yml: budget.rows.statement_by_code maps revenue/expenditure to code regexes")
    run_totals = rows.get("run_totals", {})
    if not isinstance(run_totals, dict) or not all(isinstance(k, str) and k.strip() and v in RUN_STATEMENTS
                                                   for k, v in run_totals.items()):
        raise FinanceConfigError(f"finance.yml: budget.rows.run_totals maps labels to one of {RUN_STATEMENTS}")
    if run_totals and "run_end" not in rows:
        raise FinanceConfigError("finance.yml: budget.rows.run_totals needs budget.rows.run_end")
    not_read = []
    for i, b in enumerate(budget.get("books_not_read", [])):
        where = f"budget.books_not_read[{i}]."
        for k, t in (("id", str), ("title", str), ("fiscal_year", int), ("url", str), ("reason", str)):
            _need(b, k, t, where)
        if urllib.parse.urlsplit(b["url"]).scheme != "https":
            raise FinanceConfigError(f"finance.yml: {where}url must be https")
        not_read.append({k: b[k] for k in ("id", "title", "fiscal_year", "url", "reason")})
    if {b["id"] for b in not_read} & {b.id for b in books}:
        raise FinanceConfigError("finance.yml: a book is both read and not read")
    return BudgetRules(
        books=tuple(books), page_titles={v: k for k, v in titles.items()}, kind_words=tuple(kinds),
        ignore_words=_strings(_need(budget, "ignore_words", list, w), "budget.ignore_words"),
        header_words=_strings(_need(budget, "header_words", list, w), "budget.header_words", True),
        year=_cs_regex(_need(budget, "year", str, w), "budget.year"),
        fund_line=fund_line, account_code=_cs_regex(rows["account_code"], "budget.rows.account_code"),
        subtotal_labels=subtotal_labels,
        total=_cs_regex(rows["total"], "budget.rows.total"),
        fund_totals=tuple(_cs_regex(p, "budget.rows.fund_totals") for p in
                          _strings(rows["fund_totals"], "budget.rows.fund_totals", True)),
        scope_break_after=tuple(_cs_regex(p, "budget.rows.scope_break_after") for p in
                                _strings(rows["scope_break_after"], "budget.rows.scope_break_after", True)),
        footer=_cs_regex(rows["footer"], "budget.rows.footer"),
        tag_codes=tag_codes, tag_headings=tag_headings,
        fund_balance_labels=tuple(_cs_regex(p, "budget.fund_balance_labels") for p in
                                  _strings(_need(budget, "fund_balance_labels", list, w), "budget.fund_balance_labels",
                                           True)),
        amount_unit=unit, header_year_lines=_flag(budget, "header_year_lines"), fund_from_header=fund_from_header,
        header_split_before=_strings(budget.get("header_split_before", []), "budget.header_split_before", True),
        ignore_tokens=tuple(_cs_regex(p, "budget.ignore_tokens") for p in
                            _strings(budget.get("ignore_tokens", []), "budget.ignore_tokens", True)),
        split_glued_amounts=_flag(budget, "split_glued_amounts"),
        org_code=_cs_regex(rows["org_code"], "budget.rows.org_code") if "org_code" in rows else None,
        statement_by_code=tuple((k, _cs_regex(v, f"budget.rows.statement_by_code.{k}")) for k, v in by_code.items()),
        fund_total_by_name=_flag(rows, "fund_total_by_name"), run_totals=dict(run_totals),
        run_end=_cs_regex(rows["run_end"], "budget.rows.run_end") if "run_end" in rows else None,
        report_date=_report_date(rows),
        books_not_read=tuple(not_read))


def _report_date(rows: dict) -> re.Pattern | None:
    if "report_date" not in rows:
        return None
    rx = _cs_regex(rows["report_date"], "budget.rows.report_date")
    if "date" not in rx.groupindex:
        raise FinanceConfigError("finance.yml: budget.rows.report_date needs a (?P<date>...) group")
    return rx


def _flag(cfg: dict, key: str) -> bool:
    v = cfg.get(key, False)
    if not isinstance(v, bool):
        raise FinanceConfigError(f"finance.yml: {key} must be true or false")
    return v


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


def _labels(v, key: str) -> tuple:
    """A label, or a list of labels, as printed -> a non-empty tuple of non-empty strings."""
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list) or not v or not all(isinstance(x, str) and x.strip() for x in v):
        raise FinanceConfigError(f"finance.yml: missing key {key} (a label or a non-empty list of labels)")
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
    fields = {k: _labels(fields.get(k), f"bidtab.fields.{k}") for k in BIDTAB_FIELDS}
    cols = _need(bt, "columns", dict, "bidtab.")
    cols = {k: _labels(cols.get(k), f"bidtab.columns.{k}") for k in ("name", "total")}
    blocks = None
    if "blocks" in bt:
        b = _need(bt, "blocks", dict, "bidtab.")
        blocks = BlockRules(header=_strings(_need(b, "header", list, "bidtab.blocks."), "bidtab.blocks.header"),
                            header_words=_strings(_need(b, "header_words", list, "bidtab.blocks."),
                                                  "bidtab.blocks.header_words"),
                            first_label=_labels(_need(b, "first_label", str, "bidtab.blocks."),
                                                "bidtab.blocks.first_label")[0],
                            total_labels=_strings(_need(b, "total_labels", list, "bidtab.blocks."),
                                                  "bidtab.blocks.total_labels"),
                            marks=_strings(_need(b, "marks", list, "bidtab.blocks."), "bidtab.blocks.marks"))
        if len(blocks.header) < 2:
            raise FinanceConfigError("finance.yml: bidtab.blocks.header must name the name column and at least one more")
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
        bidtab=BidTabRules(fields=fields, columns=cols,
                           optional_columns=_strings(bt.get("optional_columns", []), "bidtab.optional_columns", True),
                           table_end=_strings(bt.get("table_end", []), "bidtab.table_end", True), blocks=blocks),
        budget=budget, capital_fund=capital)


@dataclass(frozen=True)
class BooksConfig:
    """A locality whose finance.yml holds budget books only (no purchasing archive, no bid tabs): the city's
    config/localities/clarksville-tn/finance.yml. fin_books reads it; fin_facts.build_budget needs only these keys."""
    budget: BudgetRules
    scan_producers: tuple        # compiled regexes
    bonfire_hosts: tuple = ()


def parse_books(cfg: dict) -> BooksConfig:
    """A books-only finance.yml: `scan_producers` and `budget`, checked by the same rules as the county's. Any other
    top-level key fails the load (a books-only file that grew an archive belongs in `parse`)."""
    if not isinstance(cfg, dict):
        raise FinanceConfigError("finance.yml: not a mapping")
    extra = set(cfg) - {"scan_producers", "budget"}
    if extra:
        raise FinanceConfigError(f"finance.yml (books only): unknown keys {sorted(extra)}")
    return BooksConfig(
        budget=parse_budget(_need(cfg, "budget", dict)),
        scan_producers=tuple(_regex(p, "scan_producers") for p in
                             _strings(_need(cfg, "scan_producers", list), "scan_producers")))


def load_books(path: Path) -> BooksConfig:
    path = Path(path)
    if not path.is_file():
        raise FinanceConfigError(f"{path}: no finance config for this locality")
    return parse_books(yaml.safe_load(path.read_text(encoding="utf-8")))


def load(path: Path | None = None) -> FinanceConfig:
    path = Path(path) if path else default_path()
    if not path.is_file():
        raise FinanceConfigError(f"{path}: no finance config for this locality")
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")))
