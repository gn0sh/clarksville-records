"""Problem family `provenance` (architecture, "Invariant: derived vs stated"): the backend checks.

Check 5: every public CSV column and facts.json row key is registered in collector.export.PROVENANCE as stated or
derived; a derived column never starts stated_; a stated_ value is never filled from a derived one (the hit-1 end to
end test is collector/tests/test_parse_review_fixes.py::test_facts_and_export_carry_null_for_a_blank_count).
Check 4: the lines cutover is immaterial on the committed data. Plus the seat rows' shape as tools/derive_seats.py
writes it (observed rows carry last_source, sourced rows carry printed) and seats.csv.
"""
from __future__ import annotations

import copy
import csv
import io
import json
from pathlib import Path

import pytest
import yaml

from collector import parse as P
from collector.export import CSV_FILES, PROVENANCE, export, seats_csv

ROOT = Path(__file__).resolve().parents[2]
SITE = yaml.safe_load((ROOT / "config" / "site.yml").read_text(encoding="utf-8"))
LOC = ROOT / "config" / "localities" / SITE["locality"]
SEATS = yaml.safe_load((LOC / "seats.yml").read_text(encoding="utf-8"))
FACTS = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    out = {}
    for internal in (False, True):
        d = tmp_path_factory.mktemp("pub" if not internal else "int")
        out[internal] = {f.name: f for f in export(copy.deepcopy(FACTS), d, internal=internal, seats=SEATS)}
    return out


def test_every_registry_value_is_stated_or_says_how_it_is_derived():
    for k, v in PROVENANCE.items():
        assert v == "stated" or (v.startswith("derived: ") and len(v) > len("derived: ")), k
        if v != "stated":
            assert not k.rsplit(".", 1)[-1].startswith("stated_"), f"derived {k} uses a stated_ name"


@pytest.mark.parametrize("internal", [False, True])
def test_every_csv_column_is_registered(exported, internal):
    files = exported[internal]
    assert {f"{n}.csv" for n in CSV_FILES} <= set(files)
    for name in CSV_FILES:
        header = next(csv.reader(io.StringIO(files[f"{name}.csv"].read_text(encoding="utf-8"))))
        missing = [c for c in header if f"{name}.{c}" not in PROVENANCE]
        assert not missing, f"{name}.csv columns not in export.PROVENANCE: {missing}"


def unregistered_keys(pub: dict) -> set[str]:
    """Every key path in the public facts.json, at any depth, that is not in PROVENANCE: dict values and lists of dicts
    are walked (provenance/registry-walk-skips-dicts), so coverage.*, items.zoning.*, roll_calls.stated_tally.* and
    *.verification.* must each say which they are. A list's entries share the list's path."""
    missing: set[str] = set()

    def walk(path: str, v) -> None:
        if isinstance(v, list):
            for x in v:
                walk(path, x)
        elif isinstance(v, dict):
            for k, x in v.items():
                p = f"{path}.{k}" if path else k
                if f"facts.json:{p}" not in PROVENANCE:
                    missing.add(p)
                walk(p, x)

    for top, v in pub.items():
        if isinstance(v, (list, dict)):
            walk(top, v)
        elif f"facts.json:{top}" not in PROVENANCE:
            missing.add(top)
    return missing


@pytest.mark.parametrize("internal", [False, True])
def test_every_facts_json_row_key_is_registered(exported, internal):
    pub = json.loads(exported[internal]["facts.json"].read_text(encoding="utf-8"))
    missing = unregistered_keys(pub)
    assert not missing, f"facts.json keys not in export.PROVENANCE: {sorted(missing)}"


def test_the_registry_walk_reaches_keys_inside_dict_values():
    pub = {"coverage": {"body": "x", "new_key": 1}, "items": [{"id": "a", "zoning": {"acreage": {"value": 1.0,
                                                                                               "odd": 2}}}]}
    assert unregistered_keys(pub) == {"coverage.new_key", "items.zoning.acreage.odd"}


def test_roll_call_columns_are_the_stated_counts_only(exported):
    rows = list(csv.DictReader(io.StringIO(exported[False]["roll_calls.csv"].read_text(encoding="utf-8"))))
    assert not {"yes", "no", "abstain"} & set(rows[0])
    by_id = {r["id"]: r for r in FACTS["roll_calls"]}
    for row in rows:
        st = by_id[row["id"]]["stated_tally"]
        if st is None or row["confirmed"] != "True":
            continue
        for k in ("yes", "no", "abstain"):
            assert row[f"stated_{k}"] == ("" if st[k] is None else str(st[k])), row["id"]


def test_no_reading_falls_back_to_the_derived_tally():
    # a reading with a tally but no printed counts states nothing (parse.printed_counts, facts.py stated_tally)
    r = P.Reading("text-layer", {"A": "Yes"}, (1, 0, 0), [], [])
    assert P.printed_counts(r) is None
    r.printed = (1, None, 0)
    assert P.printed_counts(r) == (1, None, 0)


# ------------------------------------------------------------------ seats (tools/derive_seats.py output)

def test_seat_rows_say_which_kind_of_dates_they_carry():
    assert SEATS
    for r in SEATS:
        assert r["dates"] in ("observed", "sourced"), r
        assert str(r["source"]).startswith("https://"), r
        if r["dates"] == "observed":
            assert str(r.get("last_source", "")).startswith("https://"), r
            assert "printed" not in r, r
        else:
            assert isinstance(r.get("printed"), str) and r["printed"], r
    mayor = next(r for r in SEATS if r["seat"] == "county-mayor")
    assert mayor["dates"] == "sourced" and mayor["printed"] == "2022-2026"


def test_derive_seats_writes_observed_rows_with_first_and_last_source():
    from tools import derive_seats
    held = {"2022-01-10": {1: "a"}, "2022-02-14": {1: "a"}, "2022-03-14": {1: "b"}}
    cite = {("2022-01-10", "a", 1): ("s", 3), ("2022-02-14", "a", 1): ("s", 9), ("2022-03-14", "b", 1): ("s", 12)}
    rows = derive_seats.runs(held, cite, {"s": {"url": "https://x.test/m.pdf"}}, "2022-08-30", 1)
    assert [(r["dates"], r["start"], r["end"], r["source"][-7:], r["last_source"][-7:]) for r in rows] == [
        ("observed", "2022-01-10", "2022-02-14", "#page=3", "#page=9"),
        ("observed", "2022-03-14", None, "page=12", "page=12")]


def test_derive_seats_defaults_come_from_site_config():
    from tools import derive_seats
    import argparse
    seen = {}
    real = argparse.ArgumentParser.parse_args

    def grab(self, argv=None, ns=None):
        a = real(self, ["--facts", "/nonexistent"])
        seen.update(vars(a))
        raise SystemExit(0)
    argparse.ArgumentParser.parse_args = grab
    try:
        with pytest.raises(SystemExit):
            derive_seats.main([])
    finally:
        argparse.ArgumentParser.parse_args = real
    assert seen["seats"] == SITE["district_count"] and seen["lines_effective"] == SITE["lines_effective"]
    assert Path(seen["out"]) == LOC / "seats.yml" and Path(seen["extra"]) == LOC / "seats-extra.yml"


def test_seats_csv_names_observed_dates_as_seen_and_sourced_terms_as_printed(exported):
    rows = list(csv.DictReader(io.StringIO(exported[False]["seats.csv"].read_text(encoding="utf-8"))))
    assert len(rows) == len(SEATS)
    assert not {"start", "end", "from", "to", "term"} & set(rows[0])
    for row, r in zip(rows, SEATS):
        assert row["dates"] == r["dates"]
        if r["dates"] == "observed":
            assert row["seen_first"] == str(r["start"]) and row["printed_term"] == ""
            assert row["last_source_url"] == r["last_source"] and "not term dates" in row["dates_basis"]
        else:
            assert row["seen_first"] == row["seen_last"] == "" and row["printed_term"] == r["printed"]
            assert row["dates_basis"] == "the term as the source prints it"
    with pytest.raises(ValueError):
        seats_csv([{"seat": "district-1", "source": "https://x.test/a.pdf"}], FACTS, {})


# ------------------------------------------------------------------ check 4: cutover immaterial

def test_lines_cutover_is_stated_and_immaterial():
    eff = SITE["lines_effective"]
    src = SITE["lines_effective_source"]
    assert src.startswith("https://") and "#page=" in src
    assert src.split("#")[0] in {s["url"] for s in FACTS["sources"]}, "cutover source is a collected document"
    dates = sorted({m["date"] for m in FACTS["meetings"]})
    before = [d for d in dates if d < eff]
    after = [d for d in dates if d >= eff]
    assert before and after
    # no meeting between the last one before the cutover and the first one on or after it could move
    for r in SEATS:
        if r["dates"] != "observed" or not r["seat"].startswith("district-"):
            continue
        start, end = str(r["start"]), (str(r["end"]) if r["end"] else None)
        assert r["lines"] == ("old" if start < eff else "current"), r
        assert end is None or (end < eff) == (start < eff), r
    # the day the commissioners were sworn (the stated cutover) sits strictly between the two boundary meetings
    assert before[-1] < eff <= after[0]
