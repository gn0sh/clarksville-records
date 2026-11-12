"""Rezoning case facts (items[].zoning, collector/zoning.py) reach search: a name or street search finds the case."""
import copy
import json
from pathlib import Path

import pytest

from sitegen import views
from sitegen.build import BuildError, check_references

ROOT = Path(__file__).resolve().parent.parent
ZONING = {"applicant": {"value": "Qqzoning Applicant LLC", "source_id": None, "page": 5},
          "location": {"value": "A parcel at the corner of Qqstreet Rd. & Wine Ln.", "source_id": None, "page": 5},
          "acreage": None, "from_zoning": {"value": ["AG"], "source_id": None, "page": 5},
          "to_zoning": None}


def with_zoning(facts):
    f = copy.deepcopy(facts)
    sid = f["sources"][0]["id"]
    it = next(i for i in f["items"] if i["id"] == "AB-91-2024")
    it["zoning"] = {k: (dict(v, source_id=sid) if v else None) for k, v in ZONING.items()}
    return f, it


def test_search_records_carry_the_zoning_fields(facts):
    f, it = with_zoning(facts)
    recs = [r for r in views.search_index(f)["records"] if r["k"] in ("item", "vote")]
    mine = [r for r in recs if r["n"] == it["number"]]
    assert mine and all("Qqzoning Applicant LLC" in r["z"] and "Qqstreet Rd." in r["z"] and "AG" in r["z"]
                        for r in mine)
    assert all(r["z"] == "" for r in recs if r["n"] != it["number"])


def test_items_without_zoning_values_add_no_search_text(facts):
    f, it = with_zoning(facts)
    it["zoning"] = {k: None for k in ZONING}
    assert views.zoning_search_text(it) == ""


def test_search_script_matches_and_shows_the_zoning_text():
    js = (ROOT / "site" / "static" / "search.js").read_text(encoding="utf-8")
    assert '(r.z || "")' in js.split("function hay")[1].split("}")[0]
    assert "mark(r.z, toks)" in js


def test_zoning_values_must_cite_a_known_source(facts):
    f, it = with_zoning(facts)
    check_references(f)
    it["zoning"]["applicant"]["source_id"] = "src-000000000000"
    with pytest.raises(BuildError, match="zoning applicant"):
        check_references(f)


def test_the_schema_accepts_zoning_and_rejects_raw_extras(facts):
    from sitegen.build import _schema_errors, _validator
    from sitegen.config import SCHEMA_PATH
    v = _validator(SCHEMA_PATH)
    f, it = with_zoning(facts)
    assert _schema_errors(v, f) == []
    it["zoning"]["applicant"]["raw"] = "ofJohnathan Buck"
    assert _schema_errors(v, f)
