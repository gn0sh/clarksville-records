"""Exports F8/F15 (architecture finance-contracts 6, AC-F13), the council export per locality (M4), and the offline
guard (provenance/offline-run-overwrites-facts)."""
from __future__ import annotations

import copy
import csv
import io
import json
from pathlib import Path

import pytest

import collector.__main__ as M
from collector import fin_export as FE
from collector.export import CSV_FILES, PROVENANCE, export_council, export_site

ROOT = Path(__file__).resolve().parents[2]
FIN = json.loads((ROOT / "data" / "finance.json").read_text(encoding="utf-8"))
SAMPLE = json.loads((ROOT / "site" / "fixtures" / "finance.sample.json").read_text(encoding="utf-8"))


def rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


@pytest.fixture(scope="module")
def real():
    pub = FE.public_finance(FIN)
    return pub, {k: rows(v) for k, v in FE.tables(pub).items()}


# ---------------------------------------------------------------- F8 / F15 tables


def test_every_finance_row_carries_its_source(real):
    _, t = real
    for name in FE.FIN_FILES:
        assert t[name], name
        for r in t[name]:
            assert r["source_url"].startswith("https://"), (name, r)
            assert r["fetched_at"], (name, r)
            assert set(FE.SRC) <= set(r), name
    # every PDF-backed row names its page; the archive (HTML) row has none
    for name in ("bidders", "budget_lines", "budget_checks"):
        assert all(r["page"] for r in t[name]), name


def test_every_finance_column_is_registered():
    for name, cols in FE.COLS.items():
        missing = [c for c in cols if f"{name}.{c}" not in FE.FIN_PROVENANCE]
        assert not missing, f"{name}.csv columns not in FIN_PROVENANCE: {missing}"
    for k, v in FE.FIN_PROVENANCE.items():
        assert v == "stated" or v.startswith("derived: "), k


def test_budget_lines_one_row_per_cell_and_checks_per_checked_cell(real):
    _, t = real
    assert len(t["budget_lines"]) == sum(len(x["cells"]) for x in FIN["budget_lines"])
    assert len(t["budget_checks"]) == sum(len(x["cells"]) for x in FIN["budget_lines"] if x["check"])
    x = next(x for x in FIN["budget_lines"] if x["check"] and x["check"]["state"] == "does_not_add_up")
    got = [r for r in t["budget_checks"] if r["line_id"] == x["id"]]
    assert [int(r["diff"]) if r["diff"] else None for r in got] == [c["diff"] for c in x["check"]["per_cell"]]
    assert {r["state"] for r in got} == {"does_not_add_up"}


def test_held_bidder_totals_export_as_held_with_the_check_never_as_values(real):
    pub, t = real
    sol = next(s for s in FIN["solicitations"] if s["held"])
    held = {int(h["field"].split("[")[1].split("]")[0]): h["check"] for h in sol["held"]}
    printed = {b["printed_order"]: b for b in sol["bid_tab"]["bidders"]}
    got = {int(r["printed_order"]): r for r in t["bidders"] if r["solicitation_id"] == sol["id"]}
    for i, b in enumerate(sol["bid_tab"]["bidders"]):
        r = got[b["printed_order"]]
        if i in held:
            assert r["held_check"] == held[i] and r["total_as_printed"] == "" and r["total_cents"] == ""
            # the raw printed token stays out of every export file
            assert printed[b["printed_order"]]["total_as_printed"] not in FE.tables(pub)["bidders"]
        else:
            assert r["held_check"] == "" and r["total_as_printed"] == b["total_as_printed"]
    jb = next(s for s in pub["solicitations"] if s["id"] == sol["id"])["bid_tab"]["bidders"]
    assert all(b["total_as_printed"] is None and b["total_cents"] is None for i, b in enumerate(jb) if i in held)
    assert all(b["held_check"] == held[i] for i, b in enumerate(jb) if i in held)


def test_held_department_awardee_and_budget_line_are_null_with_check():
    fin = copy.deepcopy(FIN)
    sol = next(s for s in fin["solicitations"] if s["department"] and s["bid_tab"]
               and s["bid_tab"]["tab_type"] == "lump_sum" and s["bid_tab"]["awardee_text"])
    sol["held"] += [{"field": "department.text", "check": "scan-values"},
                    {"field": "bid_tab.awardee_text", "check": "award-source"}]
    line = next(x for x in fin["budget_lines"] if x["row_role"] == "total" and x["check"])
    line["held"] = "column-align"
    pub = FE.public_finance(fin)
    t = {k: rows(v) for k, v in FE.tables(pub).items()}
    r = next(r for r in t["solicitations"] if r["id"] == sol["id"])
    assert r["department"] == "" and r["department_held_check"] == "scan-values"
    assert r["awardee_text"] == "" and r["awardee_held_check"] == "award-source"
    assert r["awardee_match"] == ""
    assert next(s for s in pub["solicitations"] if s["id"] == sol["id"])["bid_tab"]["awardee_match"] is None
    cells = [r for r in t["budget_lines"] if r["line_id"] == line["id"]]
    assert cells and all(c["as_printed"] == "" and c["dollars"] == "" and c["held_check"] == "column-align"
                         for c in cells)
    checks = [r for r in t["budget_checks"] if r["line_id"] == line["id"]]
    assert all(c["printed"] == "" and c["diff"] == "" and c["held_check"] == "column-align" for c in checks)


def test_unknown_held_field_fails_the_export():
    fin = copy.deepcopy(FIN)
    fin["solicitations"][0]["held"].append({"field": "bid_tab.something_new", "check": "amount-format"})
    with pytest.raises(FE.ExportError):
        FE.public_finance(fin)


def test_not_read_tab_exports_no_values(real):
    pub, t = real
    nr = {s["id"] for s in FIN["solicitations"] if s["bid_tab"] and s["bid_tab"]["tab_type"] != "lump_sum"}
    assert nr
    assert not [r for r in t["bidders"] if r["solicitation_id"] in nr]
    for r in t["solicitations"]:
        if r["id"] in nr:
            assert r["awardee_text"] == r["bid_date_text"] == r["project_text"] == "" and r["not_read_reason"]


def test_bidders_in_printed_order_never_by_amount(real):
    _, t = real
    by: dict[str, list[int]] = {}
    for r in t["bidders"]:
        by.setdefault(r["solicitation_id"], []).append(int(r["printed_order"]))
    assert by and all(v == sorted(v) for v in by.values())


def test_export_finance_writes_files_and_refuses_a_fixture(tmp_path):
    out = FE.export_finance(FIN, tmp_path)
    assert sorted(p.name for p in out) == sorted(["finance.json"] + [f"{n}.csv" for n in FE.FIN_FILES])
    with pytest.raises(FE.ExportError):
        FE.export_finance(SAMPLE, tmp_path / "x")
    # the sample shape works through the same table code
    assert FE.tables(FE.public_finance(SAMPLE))["solicitations"].startswith("id,")


# ---------------------------------------------------------------- councils, per locality (config-driven)


@pytest.fixture(scope="module")
def council_export(tmp_path_factory):
    from sitegen import config
    assert config.COUNCILS, "config/site.yml lists no council"
    d = tmp_path_factory.mktemp("council")
    cfg = config.COUNCILS[0]
    return cfg, {p.name: p for p in export_council(cfg, d)}, d


def test_council_export_matches_the_county_files(council_export):
    cfg, files, d = council_export
    assert set(files) == {"facts.json"} | {f"{n}.csv" for n in CSV_FILES}
    assert all(p.parent == d / "data" / cfg["slug"] for p in files.values())
    for name in CSV_FILES:
        header = next(csv.reader(io.StringIO(files[f"{name}.csv"].read_text(encoding="utf-8"))))
        assert not [c for c in header if f"{name}.{c}" not in PROVENANCE], name
        body = rows(files[f"{name}.csv"].read_text(encoding="utf-8"))
        if name not in ("officials",):
            assert body and all(r["source_url"].startswith("https://") for r in body), name


def test_council_export_holds_unconfirmed_values_and_raw_text(council_export):
    _, files, _ = council_export
    pub = json.loads(files["facts.json"].read_text(encoding="utf-8"))
    un = [r for r in pub["roll_calls"] if not r["confirmed"]]
    assert un and all(r["outcome"] is None and r["stated_tally"] is None and all(v["value"] is None
                                                                               for v in r["votes"]) for r in un)
    assert all("raw_name" not in v for r in pub["roll_calls"] for v in r["votes"])
    assert all("text" not in m for m in pub["motions"])
    seats = rows(files["seats.csv"].read_text(encoding="utf-8"))
    assert seats and {r["dates"] for r in seats} == {"observed"} and all(r["printed_term"] == "" for r in seats)


def test_export_site_writes_county_councils_and_finance(tmp_path):
    facts = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))
    written = export_site(facts, tmp_path, finance_path=ROOT / "data" / "finance.json")
    names = {p.relative_to(tmp_path / "data").as_posix() for p in written}
    assert {"facts.json", "finance.json", "solicitations.csv", "budget_lines.csv", "city/facts.json",
            "city/votes.csv"} <= names
    fixture = json.loads((ROOT / "site" / "fixtures" / "facts.sample.json").read_text(encoding="utf-8"))
    written = export_site(fixture, tmp_path / "fx", finance_path=ROOT / "data" / "finance.json")
    assert {p.relative_to(tmp_path / "fx" / "data").as_posix() for p in written} == \
        {"facts.json"} | {f"{n}.csv" for n in CSV_FILES}       # a fixture county exports no real council or finance


# ---------------------------------------------------------------- offline guard


def _facts(ids):
    """One source document per meeting (the shrink guard's unit: collector/__main__.py check_unit)."""
    return {"sources": [{"id": f"src-{i}", "sha256": i * 64} for i in ids],
            "meetings": [{"id": i, "source_id": f"src-{i}"} for i in ids]}


def test_shrink_reason(tmp_path):
    p = tmp_path / "facts.json"
    p.write_text(json.dumps(_facts(["a", "b", "c"])))
    ok = {"parsed": 3, "failures": []}
    assert M.shrink_reason(_facts(["a", "b", "c", "d"]), ok, p) is None
    assert "drop 2 of the 3" in M.shrink_reason(_facts(["a"]), ok, p)
    assert M.shrink_reason(_facts([]), {"parsed": 0, "failures": []}, p) == "no minutes documents parsed"
    gone = {"parsed": 3, "failures": [{"stage": "parse", "url": "u", "error": "not in the store (run without "
                                                                              "--offline)"}]}
    assert "not in the store" in M.shrink_reason(_facts(["a", "b", "c"]), gone, p)
    assert M.shrink_reason(_facts(["a"]), ok, tmp_path / "none.json") is None


@pytest.fixture
def guarded(tmp_path, monkeypatch):
    facts_path = tmp_path / "facts.json"
    old = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))
    facts_path.write_text(json.dumps(old))
    monkeypatch.setattr(M, "FACTS", facts_path)
    monkeypatch.setattr(M, "BUILD", tmp_path / "build")
    calls = []
    small = dict(old, meetings=old["meetings"][:2])

    def fake_build(store, log, use_ocr=True):
        calls.append("build")
        log["parsed"] = 1
        return small, {}, None
    monkeypatch.setattr(M, "cmd_build", fake_build)
    monkeypatch.setattr(M, "run_finance", lambda *a, **k: calls.append("finance") or 0)
    monkeypatch.setattr(M, "missing_inputs", lambda store: [])   # the guard after the build is under test here
    return facts_path, calls


def test_offline_run_refuses_to_drop_meetings(guarded, capsys):
    facts_path, calls = guarded
    before = facts_path.read_bytes()
    assert M.main(["run", "--offline"]) == M.REFUSED
    assert facts_path.read_bytes() == before and calls == ["build"]
    assert not (facts_path.parent / "build").exists()
    assert "REFUSED" in capsys.readouterr().err
    assert M.main(["build"]) == M.REFUSED and facts_path.read_bytes() == before


def test_offline_run_refuses_when_store_files_are_missing(tmp_path, monkeypatch, capsys):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"url": "https://example.test/m.pdf", "sha256": "0" * 64, "kind": "minutes",
                                     "meeting_date": "2024-01-08", "label": "January 8, 2024"}]))
    monkeypatch.setattr(M, "MANIFEST", manifest)
    monkeypatch.setenv("RECORDS_STORE", str(tmp_path / "empty-store"))
    monkeypatch.setattr(M, "FACTS", tmp_path / "facts.json")
    monkeypatch.setattr(M, "cmd_build", lambda *a, **k: pytest.fail("parsed despite missing inputs"))
    assert M.main(["run", "--offline"]) == M.REFUSED
    assert "not in the store" in capsys.readouterr().err
    assert not (tmp_path / "facts.json").exists()


# -- csv-export/formula-injection: text cells are neutralised per column; number columns are not touched

def test_csv_text_cells_starting_with_a_formula_character_get_an_apostrophe():
    import csv
    import io
    from collector.export import _csv
    lead = ("=", "+", "-", "@", "\t", "\r")
    rows = [{"name": c + "x", "n": c + "1"} for c in lead] + [{"name": "Plain Co", "n": None}]
    out = list(csv.DictReader(io.StringIO(_csv(rows, ["name", "n"], {"n"}), newline="")))
    assert [r["name"] for r in out[:6]] == ["'" + c + "x" for c in lead]
    assert [r["n"] for r in out[:6]] == [c + "1" for c in lead]
    assert out[6] == {"name": "Plain Co", "n": ""}


def test_finance_csv_leaves_numbers_and_placeholder_alone_but_guards_bidder_names():
    import csv
    import io
    from collector.export import _csv
    from collector.fin_export import COLS, NUMERIC_COLS
    assert NUMERIC_COLS <= {c for cols in COLS.values() for c in cols}
    bidder = {"name": '=HYPERLINK("http://x")', "total_as_printed": "-", "total_cents": -500, "printed_order": 1}
    r = next(csv.DictReader(io.StringIO(_csv([bidder], COLS["bidders"], NUMERIC_COLS))))
    assert r["name"].startswith("'=") and r["total_as_printed"] == "-" and r["total_cents"] == "-500"
    line = {"as_printed": "-1,234", "dollars": -1234, "label_as_printed": "-Transfers"}
    r = next(csv.DictReader(io.StringIO(_csv([line], COLS["budget_lines"], NUMERIC_COLS))))
    assert r["as_printed"] == "-1,234" and r["dollars"] == "-1234" and r["label_as_printed"] == "'-Transfers"
