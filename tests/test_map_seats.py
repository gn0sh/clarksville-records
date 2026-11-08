"""The traced district map (config/localities/<locality>/districts.json) and the seat holder records (config/seats.yml):
their shape, the 19/20 renumbering, the seat check, and the pure parts of the extraction and derivation tools."""
import json
import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

from tools import derive_seats, seat_check

ROOT = Path(__file__).resolve().parent.parent
LOCALITY = ROOT / "config" / "localities" / seat_check.locality()
DISTRICTS = LOCALITY / "districts.json"
SEATS = ROOT / "config" / "seats.yml"
SVG_PATH = re.compile(r"^[MLZ0-9. -]+$")


def rings(path: str):
    for sub in re.findall(r"M([^Z]+)Z", path):
        yield [tuple(float(v) for v in p.split()) for p in sub.split("L")]


def area(path: str) -> float:
    total = 0.0
    for r in rings(path):
        total += abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]))) / 2
    return total


def inside(path: str, x: float, y: float) -> bool:
    """Even-odd ray casting over every ring (holes included)."""
    hit = False
    for r in rings(path):
        for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                hit = not hit
    return hit


@pytest.fixture(scope="module")
def districts():
    return json.loads(DISTRICTS.read_text(encoding="utf-8"))


# --- map file ---------------------------------------------------------------------------------------------------

def test_map_has_21_districts_with_sourced_metadata(districts):
    assert [d["number"] for d in districts["districts"]] == list(range(1, 22))
    assert districts["source_url"].startswith("https://")
    assert re.fullmatch(r"[0-9a-f]{64}", districts["source_sha256"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", districts["fetched"])
    assert districts["effective"] == "2022-09-01"
    assert "19 and 20" in districts["note"]


def test_paths_are_plain_svg_path_data(districts):
    for d in districts["districts"]:
        assert SVG_PATH.match(d["path"]), d["number"]
    assert SVG_PATH.match(districts["outline_path"])
    assert districts["river_path"] is None or SVG_PATH.match(districts["river_path"])


def test_each_label_point_lies_inside_its_own_district_only(districts):
    for d in districts["districts"]:
        x, y = d["label_xy"]
        assert inside(d["path"], x, y), d["number"]
        others = [o["number"] for o in districts["districts"] if o is not d and inside(o["path"], x, y)]
        assert others == [], (d["number"], others)


def test_view_box_holds_every_district(districts):
    minx, miny, w, h = (float(v) for v in districts["viewBox"].split())
    for d in districts["districts"]:
        for r in rings(d["path"]):
            assert all(minx <= x <= minx + w and miny <= y <= miny + h for x, y in r), d["number"]


def test_district_areas_add_up_to_the_outline(districts):
    total = sum(area(d["path"]) for d in districts["districts"])
    assert abs(total - area(districts["outline_path"])) / total < 0.01


def test_19_and_20_carry_the_adopted_numbers(districts):
    """The PDF prints the 2021-10-18 proposal's numbers; the adopted map swapped 19 and 20. Billy Frye (District 19
    on the roster) lives in the large north-east district, Autumn Simmons (District 20) in the small one near the
    state line, so after the swap 19 is the large one."""
    by = {d["number"]: d for d in districts["districts"]}
    assert area(by[19]["path"]) > 10 * area(by[20]["path"])


def test_map_is_small_enough_to_inline():
    assert DISTRICTS.stat().st_size < 60_000


def test_wards_state_why_they_are_missing(districts):
    assert districts["wards"]["status"] in ("unavailable", "coming")
    assert districts["wards"]["note"]


# --- seats.yml --------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rows():
    return yaml.safe_load(SEATS.read_text(encoding="utf-8"))


def test_every_row_has_a_seat_start_and_https_source(rows):
    for r in rows:
        assert re.fullmatch(r"district-\d{1,2}|county-mayor", r["seat"])
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r["start"]))
        assert r["end"] is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r["end"]))
        assert r["source"].startswith("https://")
        assert r["note"]


def test_rows_never_span_the_2022_lines(rows):
    for r in rows:
        if r["seat"].startswith("district-"):
            old = str(r["start"]) < "2022-09-01"
            assert r["lines"] == ("old" if old else "current")
            assert r["end"] is None or (str(r["end"]) < "2022-09-01") == old


def test_committed_seats_pass_the_seat_check(rows):
    facts = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))
    roster = yaml.safe_load((LOCALITY / "roster-current.yml").read_text(encoding="utf-8"))
    assert seat_check.check(facts, rows, roster) == []


def test_roster_copy_holds_no_contact_details():
    text = (LOCALITY / "roster-current.yml").read_text(encoding="utf-8")
    assert not re.search(r"\b\d{3}-\d{4}\b|@|\b(Dr|Rd|Way|Ave|Pike|Cir)\b\.?\s*$", text, re.M)


# --- seat check catches problems ----------------------------------------------------------------------------------

def _facts(*votes):
    meetings = [{"id": f"{d}-formal", "date": d} for d in sorted({d for d, _ in votes})]
    return {"meetings": meetings, "roll_calls": [{"id": f"rc{i}", "meeting_id": f"{d}-formal",
                                                  "votes": [{"official_id": o}]} for i, (d, o) in enumerate(votes)]}


def _row(oid, seat, start, end=None):
    return {"official_id": oid, "seat": seat, "start": start, "end": end}


def test_check_flags_a_voter_with_no_seat_and_one_with_two():
    rows = [_row("a", "district-1", "2022-09-12"), _row("b", "district-2", "2022-09-12"),
            _row("b", "district-3", "2023-01-01")]
    p = seat_check.check(_facts(("2022-08-08", "a"), ("2023-02-01", "b")), rows)
    assert any("2022-08-08 a" in x and "holds 0 seats" in x for x in p)
    assert any("2023-02-01 b" in x and "holds 2 seats" in x for x in p)
    assert any("b: holds district-2 and district-3 at once" in x for x in p)


def test_check_flags_overlapping_records_and_roster_mismatch():
    rows = [_row("a", "district-1", "2022-09-12"), _row("c", "district-1", "2024-01-01")]
    roster = {"seats": {"district-1": {"official_id": "c"}}}
    p = seat_check.check(_facts(("2024-02-01", "c")), rows, roster)
    assert any("district-1: records overlap" in x for x in p)
    assert any("roster lists c" in x for x in p)


# --- derivation ----------------------------------------------------------------------------------------------------

def test_decide_takes_the_majority_and_lists_ties_and_out_of_range():
    obs = {("2024-01-08", "a"): Counter({21: 5, 71: 1}), ("2024-01-08", "b"): Counter({3: 1, 8: 1}),
           ("2024-01-08", "c"): Counter({91: 2, 21: 1})}
    held, unknown, conflicts = derive_seats.decide(obs, {}, 21)
    assert 21 not in held["2024-01-08"]
    assert [u["official_id"] for u in unknown] == ["b"]
    assert conflicts and conflicts[0]["district"] == 21          # a and c both read as 21: listed, not guessed


def test_runs_split_at_the_lines_date_and_leave_the_latest_open():
    held = {"2022-08-08": {1: "a"}, "2022-09-12": {1: "a"}, "2023-01-09": {1: "b"}, "2023-02-13": {1: "b"}}
    cite = {(d, o, 1): ("s", 3) for d, v in held.items() for o in v.values()}
    rows = derive_seats.runs(held, cite, {"s": {"url": "https://x.test/m.pdf"}}, "2022-09-01", 1)
    assert [(r["official_id"], r["start"], r["end"], r["lines"]) for r in rows] == [
        ("a", "2022-08-08", "2022-08-08", "old"), ("a", "2022-09-12", "2022-09-12", "current"),
        ("b", "2023-01-09", None, "current")]
    assert rows[0]["source"] == "https://x.test/m.pdf#page=3"


def test_name_pattern_reads_the_number_before_a_name():
    pat = derive_seats._name_re({"Rickey Ray", "Joe Creek"})
    text = "   4       Rickey Ray           Y       Ii       Joe Creek     Y\n$1,000 Joe Creek"
    assert [(m.group(1), m.group(2)) for m in pat.finditer(text)] == [("4", "Rickey Ray")]


# --- extraction tool (needs shapely; skipped where it is not installed) ---------------------------------------------

def test_extractor_assigns_parts_by_printed_label():
    pytest.importorskip("shapely")
    from shapely.geometry import box
    from tools import extract_pdf_map as ex
    red, blue = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    by_colour = {red: [box(0, 0, 10, 10), box(10, 0, 20, 10), box(40, 0, 50, 10), box(60, 0, 63, 3)],
                 blue: [box(20, 0, 40, 10)]}
    labels = [(1, 5, 5, 15.6), (2, 45, 5, 15.6), (3, 30, 5, 15.6)]
    out, summary = ex._assemble(by_colour, labels, 0.1, 100, 100, lambda clip: None)
    nums = {d["number"]: d for d in out["districts"]}
    assert sorted(nums) == [1, 2, 3]
    assert abs(area(nums[1]["path"]) - 200) < 1          # two touching red boxes, one part
    assert abs(area(nums[3]["path"]) - 200) < 1
    # the 3x3 red speck touches no red part and red holds two districts: reported, never guessed
    assert summary["problems"] and "unlabelled part" in summary["problems"][0]


def test_extractor_groups_digits_into_numbers():
    from tools import extract_pdf_map as ex

    def ch(t, x0, top=100.0, size=15.6):
        return {"text": t, "x0": x0, "x1": x0 + 8.7, "top": top, "bottom": top + 15.6, "size": size}

    class Page:
        chars = [ch("1", 312), ch("0", 321), ch("1", 400), ch("7", 409), ch("2", 430), ch("0", 439), ch("9", 600, 50)]
    assert [n for n, *_ in ex._numbers(Page(), r"[1-9]\d?")] == [9, 10, 17, 20]
