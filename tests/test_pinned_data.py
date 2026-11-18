"""The pinned real data (tests/pinned_data.py, docs/architecture/real-data-tests-invariant.md): what it holds, so a
re-pin that changes what the pinned tests read is seen in review, and that no test can change it for another."""
import pinned_data
from sitegen import budget_views


def test_the_snapshot_holds_the_named_files_as_projected():
    snap = pinned_data._snapshot()
    assert sorted(snap) == sorted(pinned_data.FILES)
    assert {budget_views.fund_key(x) for x in snap["city_finance"]["budget_lines"]} == set(pinned_data.CITY_FUNDS)
    assert [x["id"] for x in snap["county_finance"]["budget_lines"]] == list(pinned_data.COUNTY_LINES)
    assert sorted(snap["county_finance"]) == ["budget_lines"]


def test_the_pinned_city_is_the_data_the_seat_tests_were_written_against():
    """At the pin (city facts as at b5a3638) the latest city list is 2026-07-06 and the 2026-07-02 minutes are not read
    (hit 2 read them)."""
    facts, wards = pinned_data.city()
    read = sorted(m["date"] for m in facts["meetings"] if m["minutes_status"] == "read" and m.get("attendance"))
    assert read[-1] == max(w["date"] for w in wards) == "2026-07-06"
    assert "2026-07-02" not in read
    assert max(m["date"] for m in pinned_data.county_facts()["meetings"]) == "2026-05-11"


def test_each_read_is_a_copy():
    facts, _ = pinned_data.city()
    facts["meetings"].clear()
    assert pinned_data.city()[0]["meetings"]
