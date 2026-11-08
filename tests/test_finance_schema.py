"""F0: site/fixtures/finance.sample.json matches schema/finance.schema.json, and covers the cases F6-F8 build on."""
import copy
import json

import pytest
from jsonschema import Draft202012Validator

from sitegen import build as sitegen_build, config

FIXTURE = config.REPO_ROOT / "site" / "fixtures" / "finance.sample.json"


@pytest.fixture(scope="module")
def validator():
    Draft202012Validator.check_schema(json.loads(config.FINANCE_SCHEMA_PATH.read_text(encoding="utf-8")))
    return sitegen_build._validator(config.FINANCE_SCHEMA_PATH)


@pytest.fixture(scope="module")
def fin():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_validates_against_the_schema(validator, fin):
    assert sitegen_build._schema_errors(validator, fin) == []
    assert fin["fixture"] is True


def test_fixture_urls_are_made_up(fin):
    urls = [s["url"] for s in fin["sources"]] + [d["url"] for d in fin["documents"]]
    assert urls and all(u.startswith("https://example.invalid/") for u in urls)


def test_fixture_references_resolve(fin):
    src = {s["id"]: s for s in fin["sources"]}
    docs = {d["id"]: d for d in fin["documents"]}
    sols = {s["id"] for s in fin["solicitations"]}
    lines = {x["id"] for x in fin["budget_lines"]}
    for s in fin["solicitations"]:
        assert s["archive_source_id"] in src
        assert all(d in docs for d in s["document_ids"])
        if s["bid_tab"]:
            assert s["bid_tab"]["document_id"] in s["document_ids"]
    for d in docs.values():
        assert d["source_id"] is None or d["source_id"] in src
        assert set(d["shared_by"]) <= sols
    for x in fin["budget_lines"]:
        assert set(x["scope_line_ids"]) <= lines
    assert all(b["source_id"] in src for b in fin["books"])


def test_no_value_from_a_scan_or_shared_url(fin):
    src = {s["id"]: s for s in fin["sources"]}
    docs = {d["id"]: d for d in fin["documents"]}
    for d in docs.values():
        if d["source_id"]:
            assert d["scanned"] == (src[d["source_id"]]["text_layer"] == "none")
    for s in fin["solicitations"]:
        t = s["bid_tab"]
        if t and t["tab_type"] == "lump_sum":
            d = docs[t["document_id"]]
            assert src[d["source_id"]]["text_layer"] == "text" and not d["shared_by"]


def test_fixture_covers_every_case(fin):
    sols = {s["id"]: s for s in fin["solicitations"]}
    tabs = [s["bid_tab"] for s in sols.values() if s["bid_tab"]]
    docs = fin["documents"]
    lines = fin["budget_lines"]
    assert any(t["tab_type"] == "lump_sum" for t in tabs)
    assert any(t["tab_type"] == "not_read" for t in tabs)
    assert any(t["awardee_match"] == "not_a_listed_bidder" for t in tabs)
    assert any(d["stage"] == "award_letter" and d["scanned"] for d in docs)
    assert any(len(d["shared_by"]) >= 2 for d in docs)
    assert {d["status"] for d in docs} == {"fetched", "not_pdf", "link_only", "dead_at_fetch"}
    assert any(s["held"] for s in sols.values())
    assert any(s["documents_differ"] for s in sols.values())
    assert any(s["bid_tab"] is None for s in sols.values())
    assert {x["check"]["state"] for x in lines if x["check"]} == {"exact", "within_rounding", "does_not_add_up"}
    assert any(x["heading_from_total"] and x["fund_no"] != lines[0]["fund_no"] for x in lines)  # capital fund line
    assert any("transfer" in x["tags"] for x in lines)
    assert any(c["as_printed"] is None for x in lines for c in x["cells"])  # blank cell stays null


def test_held_values_are_null(fin):
    for s in fin["solicitations"]:
        for h in s["held"]:
            assert h["field"].startswith("bid_tab.bidders[")
            n = int(h["field"].split("[")[1].split("]")[0])
            b = s["bid_tab"]["bidders"][n]  # a path: 0-based index into the list (collector writes n - 1)
            assert b["total_cents"] is None


def test_checks_match_their_scope(fin):
    by = {x["id"]: x for x in fin["budget_lines"]}
    for x in by.values():
        if not x["check"]:
            continue
        for i, pc in enumerate(x["check"]["per_cell"]):
            s = sum(by[i_d]["cells"][i]["dollars"] or 0 for i_d in x["scope_line_ids"])
            assert pc["sum"] == s and pc["printed"] == x["cells"][i]["dollars"]


@pytest.mark.parametrize("mutate", [
    lambda f: f["documents"][0].update(stage="invoice"),
    lambda f: f["sources"][0].update(url="http://example.invalid/x.pdf"),
    lambda f: next(x for x in f["budget_lines"] if x["row_role"] == "detail")
    .update(check={"state": "exact", "per_cell": []}),
    lambda f: next(s for s in f["solicitations"] if s["bid_tab"] and s["bid_tab"]["tab_type"] == "not_read")["bid_tab"]
    .update(awardee_text="Someone"),
    lambda f: f["budget_lines"][0]["cells"][0].update(kind="estimate"),
    lambda f: next(d for d in f["documents"] if d["status"] == "link_only").update(source_id=f["sources"][0]["id"]),
])
def test_schema_rejects_contract_breaks(validator, fin, mutate):
    bad = copy.deepcopy(fin)
    mutate(bad)
    assert sitegen_build._schema_errors(validator, bad)


def _tab(fin, kind):
    return next(s for s in fin["solicitations"] if s["bid_tab"] and s["bid_tab"]["tab_type"] == kind)


def test_not_pdf_reason_and_date_pages(validator, fin):
    f = copy.deepcopy(fin)
    _tab(f, "not_read")["bid_tab"]["not_read_reason"] = "not_pdf"
    assert sitegen_build._schema_errors(validator, f) == []
    lump = _tab(fin, "lump_sum")["bid_tab"]
    assert lump["bid_date_text"] and lump["bid_date_page"] >= 1 and lump["award_date_page"] >= 1
    assert set(fin["coverage"]["n_tab_not_read"]) == {"layout", "scan", "shared_url", "not_pdf"}


@pytest.mark.parametrize("edit", [
    lambda t: t.update(bid_date_page=None),                    # a date with no page cannot be cited
    lambda t: t.update(award_date_page=None),
    lambda t: t.update(bid_date_text=None),                    # a page with no date
    lambda t: t.pop("bid_date_page"),
    lambda t: t.update(not_read_reason="docx"),
])
def test_date_pages_and_reasons_are_checked(validator, fin, edit):
    f = copy.deepcopy(fin)
    edit(_tab(f, "lump_sum")["bid_tab"])
    assert sitegen_build._schema_errors(validator, f) != []


def test_not_read_tab_carries_no_dates(validator, fin):
    f = copy.deepcopy(fin)
    t = _tab(f, "not_read")["bid_tab"]
    t.update(bid_date_text="1-1-26", bid_date_page=1)
    assert sitegen_build._schema_errors(validator, f) != []
