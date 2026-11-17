"""The agenda reader for the school board and county committee agendas (collector/committee_agenda_text.py), on the
text layers of real agendas (tests/fixtures/county-committees/*.txt, pdftotext -layout; the names of people in them
replaced by invented ones), and the build and shrink rules on a small store."""
import json
import re
from pathlib import Path

import pytest

from collector import committee_agenda_text as cat
from collector import county_committees as cc
from collector.store import Store

FX = Path(__file__).resolve().parent / "fixtures" / "county-committees"


def pages(name: str) -> list[str]:
    out = (FX / name).read_text(encoding="utf-8").split("\f")
    return out[:-1] if out and not out[-1].strip() else out


def test_budget_committee_resolutions_with_their_numbers_as_printed():
    got = cat.read_agenda(pages("budget-committee-2026-01-21.txt"))
    assert got["text_layer"] == "text" and got["date_printed"] == "2026-01-21"
    assert got["title"] == "AGENDA BUDGET COMMITTEE MEETING JANUARY 21, 2026"
    by_num = {e["number"]: e for e in got["entries"] if e["number"]}
    assert list(by_num) == ["CZ-22-2025"] + [f"26-2-{n}" for n in range(1, 9)]
    # a title broken over two lines is one entry, joined as printed; the asterisk stays in the text
    assert by_num["26-2-1"]["text"] == ("26-2-1* Resolution of the Montgomery County Board of Commissioners Approving "
                                        "Amendments to the 2025 – 2026 School Budget")
    heads = [e["text"] for e in got["entries"] if e["heading"]]
    assert heads[:3] == ["CALL BUDGET COMMITTEE MEETING TO ORDER", "ZONING RESOLUTIONS", "RESOLUTIONS"]
    assert [e["text"] for e in got["entries"]][-3:] == ["1. Parks Employee Needed for March Camp",
                                                        "2. Animal Care & Control – Reclassification PT to FT", "ADJOURN"]
    assert all(e["page"] == 1 for e in got["entries"])


def test_study_session_items_and_a_sentence_carried_below_a_blank_line():
    got = cat.read_agenda(pages("study-session-2026-01-13.txt"))
    assert got["title"] == "CMCSS School Board Study Session January 13, 2026"
    texts = [e["text"] for e in got["entries"]]
    assert texts[0] == "6:00 PM"
    assert ("8. Goal #3 Continue implementing innovative academic programming across the district (Policy Reference "
            "E-1; E-2)") in texts
    assert texts[-1] == "10. Other Business" and len(texts) == 11


def test_formal_board_agenda_lines_and_the_reference_column_dropped():
    """The reader itself (the school board's text is not stored: see test_school_board_stores_no_item_text)."""
    got = cat.read_agenda(pages("formal-2026-02-24.txt"))
    assert got["date_printed"] == "2026-02-24"
    texts = [e["text"] for e in got["entries"]]
    assert "6:00 Convene Call to Order, Pledge of Allegiance, Moment of Silence" in texts   # GP-5 cell dropped
    assert "6:16 Policy Monitoring" in texts and "1. EL-3 Personnel Administration" in texts
    assert not any(re.search(r"\b(GP-5|GP-3|B/SL-3)\b", t) for t in texts)


def test_budget_hearing_group_names_are_their_own_lines_and_an_ordinal_date_is_read():
    got = cat.read_agenda(pages("budget-hearing-2026-04-09.txt"))
    assert got["date_printed"] == "2026-04-09"
    texts = [e["text"] for e in got["entries"]]
    i = texts.index("Building & Codes")
    assert texts[i - 1] == "• Operating Budget" and texts[i + 1] == "• Capital Outlay Requests"
    assert "Judicial Commissioners" in texts


def test_purchasing_agenda_lines():
    got = cat.read_agenda(pages("purchasing-2026-07-23.txt"))
    assert got["title"].startswith("Purchasing Committee") and got["date_printed"] == "2026-07-23"
    assert "• Bid listing since last meeting" in [e["text"] for e in got["entries"]]


def test_a_scan_has_no_entries():
    assert cat.read_agenda(["\n\n  \n"]) == {"title": None, "date_printed": None, "entries": [], "text_layer": "none"}


@pytest.mark.parametrize("text,iso", [("January 21, 2026", "2026-01-21"), ("April 9th, 2026", "2026-04-09"),
                                      ("Tuesday, June 2, 2026", "2026-06-02"), ("on 11/17/26 at", "2026-11-17"),
                                      ("no date", None)])
def test_printed_date(text, iso):
    assert cat.printed_date(text) == iso


def _store_with(tmp_path, rows):
    store = Store(manifest_path=tmp_path / "manifest.json", root=tmp_path / "store")
    for r in rows:
        store.put(r["url"], b"%PDF-1.4 " + r["url"].encode(), {}, {"kind": "agenda", "meeting_date": r["date"]})
    return store


def test_build_reports_a_date_mismatch_keeps_the_listed_date_and_reads_every_body(tmp_path):
    cfg = cc.load_config()
    page = (Path(__file__).resolve().parent / "fixtures" / "county-committee-agendas-2026-11-16.html").read_text()
    rows = cc.assign_ids(cc.parse_listing(page, cfg)[0])
    rows = [r for r in rows if r["body"] in ("budget-committee", "school-board")][:3] + rows[-2:]
    store = _store_with(tmp_path, rows[:-1])                 # the last row's file is not fetched yet
    text = pages("budget-committee-2026-01-21.txt")
    out, summary = cat.build(cfg, rows, store, read=lambda p: text, count=lambda p: 1)
    assert out["schema"] == cat.SCHEMA and summary["meetings"] == len(rows) and summary["sources"] == len(rows) - 1
    m = out["meetings"][0]
    assert m["source_id"] and m["entries"][0]["id"] == f"{m['id']}-e1"
    probs = [p["problem"] for p in summary["problems"]]
    assert any("the agenda prints 2026-01-21; the listed date is kept" in p for p in probs)
    assert "listed, not fetched yet" in probs
    unread = next(m for m in out["meetings"] if m["url"] == rows[-1]["url"])
    assert unread["source_id"] is None and unread["entries"] == []


def test_shrink_reason():
    old = {"meetings": [{"body": "b", "id": "1", "source_id": "s", "entries": [{"text": "x"}]},
                        {"body": "b", "id": "2", "source_id": None, "entries": []}]}
    assert cat.shrink_reason(old, old) is None
    assert "drop 1 meetings" in cat.shrink_reason(old, {"meetings": old["meetings"][:1]})
    lost = {"meetings": [{**old["meetings"][0], "source_id": None}, old["meetings"][1]]}
    assert "would have none" in cat.shrink_reason(old, lost)
    unread = {"meetings": [{**old["meetings"][0], "entries": []}, old["meetings"][1]]}
    assert "would not be" in cat.shrink_reason(old, unread)
    revised = {"meetings": [{**old["meetings"][0], "source_id": "s2"}, old["meetings"][1]]}
    assert cat.shrink_reason(old, revised) is None


# privacy-withhold hit 3 (manager decision 2026-11-16): the school board stores no item text at all, whatever the
# agenda prints (docs/architecture/agenda-withhold-invariant.md). Made-up names only.
SHOWCASE = """                     CMCSS Board of Education
                       Formal Session
                     November 17, 2026

6:00    Convene
        Call to Order

6:02    Point of Pride Awards
        STATE WRESTLING CHAMPIONS
        Avery Madeup, Sample High School
        Jordan Notreal, Sample High School

6:05    Student Spotlight
        Third grader Riley Fictional, Example Elementary

6:08    Recognitions
        Teacher of the Year: Morgan Invented, Example Middle

        NATIONAL MERIT SCHOLARS
        Casey Pretend

6:20    Approval of Consent Agenda
          1. 10/20/2026 Regular Session Minutes
6:30    Adjourn
"""
NAMES = ("Avery Madeup", "Jordan Notreal", "Riley Fictional", "Morgan Invented", "Casey Pretend")


def test_school_board_stores_no_item_text_only_the_count(tmp_path):
    cfg = cc.load_config()
    assert next(b for b in cfg.bodies if b.key == "school-board").text is False
    assert all(b.text for b in cfg.bodies if b.group == "county-finance")
    page = (Path(__file__).resolve().parent / "fixtures" / "county-committee-agendas-2026-11-16.html").read_text()
    rows = cc.assign_ids(cc.parse_listing(page, cfg)[0])
    rows = [r for r in rows if r["body"] == "school-board"][:2] + [r for r in rows if r["body"] == "budget-committee"][:1]
    store = _store_with(tmp_path, rows)
    out, summary = cat.build(cfg, rows, store, read=lambda p: [SHOWCASE], count=lambda p: 1)
    school = [m for m in out["meetings"] if m["body"] == "school-board"]
    n = len(cat.read_agenda([SHOWCASE])["entries"])
    assert school and all(m["entries"] == [] and m["title"] is None and m["lines"] == n and m["source_id"]
                          for m in school)
    blob = json.dumps(school)
    assert not any(x in blob for x in NAMES + ("Point of Pride", "Spotlight", "Approval", "Board of Education"))
    county = next(m for m in out["meetings"] if m["body"] == "budget-committee")
    assert county["lines"] == n and len(county["entries"]) == n          # county finance: item text as printed
    assert {b["key"]: b["text"] for b in out["bodies"]}["school-board"] is False


def test_withhold_rules_are_retired_in_the_config(tmp_path):
    raw = (cc.CONFIG).read_text(encoding="utf-8").replace("    text: false\n", "    withhold: ['x']\n", 1)
    (tmp_path / "c.yml").write_text(raw, encoding="utf-8")
    with pytest.raises(cc.ConfigError, match="withhold rules are retired"):
        cc.load_config(tmp_path / "c.yml")


def test_a_shrink_keeps_a_counted_school_agenda():
    old = {"meetings": [{"body": "school-board", "id": "1", "source_id": "s", "entries": [], "lines": 12}]}
    assert cat.shrink_reason(old, old) is None
    assert "would not be" in cat.shrink_reason(old, {"meetings": [{**old["meetings"][0], "lines": 0}]})
