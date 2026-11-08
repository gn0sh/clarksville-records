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
    budget: dict
    capital_fund: object


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
    budget = _need(cfg, "budget", dict)
    for k in ("books", "page_titles", "kind_words", "rows", "tags", "fund_balance_labels"):
        _need(budget, k, None, "budget.")
    if "capital_fund" not in cfg:
        raise FinanceConfigError("finance.yml: missing key capital_fund")
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
        budget=budget, capital_fund=cfg["capital_fund"])


def load(path: Path | None = None) -> FinanceConfig:
    path = Path(path) if path else default_path()
    if not path.is_file():
        raise FinanceConfigError(f"{path}: no finance config for this locality")
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")))
