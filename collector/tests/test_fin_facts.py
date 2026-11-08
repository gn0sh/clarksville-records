"""F5c: fin_facts (data/finance.json), coverage and parity (fin_checks), the report block and the fin CLI.

On the fixture store (collector/tests/fin_fake.py). Keys: coverage-count/*, doc-completeness/*, determinism/*.
"""
import json

import pytest

from collector import fin_checks, fin_run
from collector.facts import dumps
from collector.fin_archive import parse_archive
from collector.fin_facts import report_block, solicitation_ids
from collector.tests.fin_fake import ARCHIVE_HTML, CFG, FakeFin


@pytest.fixture
def fake(tmp_path):
    return FakeFin(tmp_path)


@pytest.fixture
def built(fake, monkeypatch):
    return fake.build(monkeypatch)


def test_output_validates_against_the_schema(built):
    fin, extras = built
    assert fin_run.validate(fin) == []
    assert "fixture" not in fin and fin["schema_version"] == "1.0"
    assert extras["problems"] == []


def test_two_runs_are_byte_identical(fake, monkeypatch):
    a, _ = fake.build(monkeypatch)
    b, _ = fake.build(monkeypatch)
    assert dumps(a) == dumps(b)
    assert [s["id"] for s in a["solicitations"]] == sorted(s["id"] for s in a["solicitations"])
    assert [d["id"] for d in a["documents"]] == sorted(d["id"] for d in a["documents"])


def test_ids_are_stable_content_ids(built):
    fin, _ = built
    s = next(x for x in fin["solicitations"] if x["title"] == "BID - WHEEL LOADER")
    assert s["id"] == "sol-bid-wheel-loader" and s["slug"] == "bid-wheel-loader" and s["row"] == 14
    assert all(d["id"].startswith("doc-") and len(d["id"]) == 14 for d in fin["documents"])
    assert {x["archive_source_id"] for x in fin["solicitations"]} == {
        next(src["id"] for src in fin["sources"] if src["kind"] == "archive_index")}


def test_slug_collision_gets_a_hash_on_every_row():
    html = ARCHIVE_HTML.decode().replace("BID - INMATE UNIFORMS", "BID - WHEEL LOADER")
    ids = solicitation_ids(parse_archive(html, CFG))
    loaders = [i for i in ids if i.startswith("sol-bid-wheel-loader")]
    assert len(loaders) == 2 and len(set(loaders)) == 2 and all(len(i) == len("sol-bid-wheel-loader-") + 6
                                                                 for i in loaders)


def test_documents_shown_equal_archive_links(built):
    """doc-completeness/*: per row, document_ids has one entry per archive link (AC-F7)."""
    fin, _ = built
    rows = {r.title: r for r in parse_archive(ARCHIVE_HTML.decode(), CFG)}
    for s in fin["solicitations"]:
        assert len(s["document_ids"]) == len(rows[s["title"]].links), s["title"]
    assert sum(len(s["document_ids"]) for s in fin["solicitations"]) == sum(len(r.links) for r in rows.values())


def test_document_states(built):
    fin, _ = built
    by_url = {d["url"]: d for d in fin["documents"]}
    docx = next(d for u, d in by_url.items() if u.endswith(".docx"))
    assert (docx["status"], docx["source_id"], docx["fetched_at"]) == ("not_pdf", None, "2026-11-08")
    forms = next(d for u, d in by_url.items() if u.endswith("Required%20forms%20and%20information.pdf"))
    assert len(forms["shared_by"]) == 3
    scanned = [d for d in fin["documents"] if d["scanned"]]
    assert {d["stage"] for d in scanned} == {"bid_tab", "award_letter"}


def test_coverage_is_the_one_function(built):
    fin, _ = built
    assert fin["coverage"] == fin_checks.coverage(fin)
    c = fin["coverage"]
    assert c["n_total"] == 15
    assert c["n_bid_tab_links"] == c["n_tab_read"] + sum(c["n_tab_not_read"].values())
    assert c["n_tab_read"] == 1
    assert c["n_tab_not_read"] == {"layout": 2, "scan": 2, "shared_url": 2}
    assert c["n_award_scanned"] == 1 and c["n_award_letters"] == 10
    assert c["by_department_year"]["Bi-County SWM"] == {"2025": {"rows": 1, "with_tab": 1, "tab_read": 1}}
    ns = c["by_department_year"][fin_checks.NOT_STATED]
    assert ns[fin_checks.NOT_STATED]["rows"] == 5                    # 4 status words and 1 empty date: no year
    assert sum(v["rows"] for ys in c["by_department_year"].values() for v in ys.values()) == 15


def _cov(depts):
    """by_department_year from {dept: (rows, tab_read)} in one year."""
    return {"by_department_year": {d: {"2026": {"rows": r, "with_tab": r, "tab_read": t}} for d, (r, t) in
                                   depts.items()}}


def test_parity_flags_a_five_row_department_at_0_4x():
    # overall share = 30/60 = 0.5; Parks 1/5 = 0.2 = 0.4x -> flagged
    p = fin_checks.parity(_cov({"Highway": (25, 14), "Parks": (5, 1), "EMS": (10, 5), "Library": (20, 10)}))
    assert p["overall_share"] == 0.5 and p["flagged"] == ["Parks"] and p["status"] == "review needed"
    assert {e["dept"]: e["tab_read_share"] for e in p["departments"]}["Parks"] == 0.2


def test_parity_ignores_small_departments_and_passes_within_bounds():
    p = fin_checks.parity(_cov({"Highway": (20, 10), "Parks": (4, 0), "EMS": (10, 3)}))
    assert p["flagged"] == [] and p["status"] == "ok"                     # 4 rows: too few; EMS 0.3 = 0.65x


def test_parity_flags_high_share_too():
    p = fin_checks.parity(_cov({"Highway": (40, 4), "Parks": (5, 5)}))     # overall 9/45 = 0.2; Parks 1.0 = 5x
    assert p["flagged"] == ["Parks"]


def test_not_stated_bucket_is_reported_not_flagged():
    p = fin_checks.parity(_cov({"Highway": (10, 5), fin_checks.NOT_STATED: (30, 0)}))
    assert p["not_stated"] == {"dept": fin_checks.NOT_STATED, "rows": 30, "tab_read_share": 0.0}
    assert fin_checks.NOT_STATED not in p["flagged"]
    assert any(e["dept"] == fin_checks.NOT_STATED for e in p["departments"])


def test_report_block(built):
    fin, extras = built
    b = report_block(fin, extras)
    assert set(b) == {"coverage", "parity", "reconcile", "budget", "held", "docs_by_status", "problems"}
    assert b["coverage"] is fin["coverage"] and b["docs_by_status"]["not_pdf"] == 1
    assert b["reconcile"] == fin_checks.reconcile_counts(fin["budget_lines"]) and sum(b["reconcile"].values()) > 0
    assert set(b["budget"]) == {x.id for x in CFG.budget.books}


def test_cmd_build_writes_finance_and_report_block(fake, monkeypatch, tmp_path, capsys):
    from collector import fin_facts
    monkeypatch.setattr(fin_facts, "pdf_meta", fake.meta)
    out, rep = tmp_path / "finance.json", tmp_path / "build" / "report.json"
    rep.parent.mkdir()
    rep.write_text(json.dumps({"gates": {"kept": True}}))
    kw = dict(finance_path=out, report_path=rep, status_path=fake.status_path, meta_cache=None,
              words_for=fake.words_for, book_words=fake.book_words)
    code = fin_run.cmd_build(fake.store, CFG, **kw)
    assert code in (0, 3)
    first = out.read_text()
    report = json.loads(rep.read_text())
    assert report["gates"] == {"kept": True} and report["finance"]["coverage"]["n_total"] == 15
    assert fin_run.cmd_build(fake.store, CFG, **kw) == code and out.read_text() == first
    assert "15 solicitations" in capsys.readouterr().out


def test_census_lists_every_bid_tab_link_with_its_class(built):
    fin, extras = built
    text = fin_run.census_text(fin, extras)
    classes = [c.cls for c in extras["census"]]
    assert len(classes) == fin["coverage"]["n_bid_tab_links"] == 7
    assert sorted(classes) == ["lump_sum", "not_read", "not_read", "not_read", "not_read", "scan", "scan"]
    assert "award letters: 10, scanned: 1" in text and "lump_sum" in text


def test_cli_dispatches_fin(monkeypatch):
    from collector import __main__ as M
    seen = {}
    monkeypatch.setattr(fin_run, "main", lambda argv: seen.setdefault("argv", argv) and 0)
    M.main(["fin", "census"])
    assert seen["argv"] == ["census"]
