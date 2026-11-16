"""City budget books (config/localities/clarksville-tn/finance.yml, collector/fin_books.py): config checks."""
import copy

import pytest
import yaml

from collector import fin_books, fin_config
from collector.fin_config import FinanceConfigError

CITY = fin_books.paths("clarksville-tn")["config"]


@pytest.fixture(scope="module")
def raw():
    return yaml.safe_load(CITY.read_text(encoding="utf-8"))


def test_city_config_loads(raw):
    cfg = fin_config.load_books(CITY)
    b = cfg.budget
    assert [x.id for x in b.books] == ["fy2024-adopted", "fy2026-final", "fy2027-presented"]
    assert [x["id"] for x in b.books_not_read] == ["fy2025-adopted"]
    assert all(x.url.startswith("https://www.clarksvilletn.gov/DocumentCenter/View/") for x in b.books)
    assert b.amount_unit == "cents" and b.fund_from_header and b.header_year_lines
    assert dict(b.kind_words)["Mayor"] == "proposed"
    assert b.run_totals == {"TOTAL REVENUE": "revenue", "TOTAL EXPENSE": "expenditure", "GRAND TOTAL": "net"}


def test_county_config_keeps_the_defaults():
    b = fin_config.load().budget
    assert (b.amount_unit, b.header_year_lines, b.fund_from_header, b.split_glued_amounts, b.fund_total_by_name) == \
        ("dollars", False, False, False, False)
    assert b.org_code is None and b.run_end is None and not b.statement_by_code and not b.run_totals
    assert not b.header_split_before and not b.ignore_tokens and not b.books_not_read


def test_books_only_file_rejects_other_keys(raw):
    cfg = copy.deepcopy(raw)
    cfg["archive_url"] = "https://example.org/"
    with pytest.raises(FinanceConfigError, match="unknown keys"):
        fin_config.parse_books(cfg)


@pytest.mark.parametrize("key,value,match", [
    ("amount_unit", "pennies", "amount_unit"),
    ("fund_from_header", "yes", "fund_from_header"),
    ("page_titles", {"summary": "X"}, "page_titles"),
])
def test_bad_budget_keys_fail_loudly(raw, key, value, match):
    cfg = copy.deepcopy(raw)
    cfg["budget"][key] = value
    with pytest.raises(FinanceConfigError, match=match):
        fin_config.parse_books(cfg)


def test_run_totals_need_a_run_end_and_known_statements(raw):
    cfg = copy.deepcopy(raw)
    del cfg["budget"]["rows"]["run_end"]
    with pytest.raises(FinanceConfigError, match="run_end"):
        fin_config.parse_books(cfg)
    cfg = copy.deepcopy(raw)
    cfg["budget"]["rows"]["run_totals"]["GRAND TOTAL"] = "everything"
    with pytest.raises(FinanceConfigError, match="run_totals"):
        fin_config.parse_books(cfg)


def test_fund_number_group_optional_only_with_fund_from_header(raw):
    cfg = copy.deepcopy(raw)
    cfg["budget"]["fund_from_header"] = False
    with pytest.raises(FinanceConfigError, match="fund_line"):
        fin_config.parse_books(cfg)


def test_not_read_book_cannot_also_be_read(raw):
    cfg = copy.deepcopy(raw)
    cfg["budget"]["books_not_read"][0]["id"] = "fy2024-adopted"
    with pytest.raises(FinanceConfigError, match="both read and not read"):
        fin_config.parse_books(cfg)
