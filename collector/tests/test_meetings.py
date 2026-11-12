"""Meetings inside one document: dates from the text, attached and packet minutes, one copy per meeting. No network."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from collector import parse as P
from collector.facts import Builder
from collector.meetings import choose
from collector.minutes import parse_minutes
from collector.names import Resolver, load_roster, NAMES

FIX = Path(__file__).parent / "fixtures"
HEADER_DEC = (FIX / "header_dec2024.txt").read_text()
RC_CLEAN = (FIX / "rc_dec2024_p9_clean.txt").read_text()
ADJOURN = "\nThe Board was adjourned at 6:27 P.M.\n\n            Submitted by:\n            County Clerk\n"


def segs_of(pages):
    lines, page_of = P._lines_with_pages(pages)
    return P.minutes_segments(lines, page_of)


def header(date_words: str, weekday: str, banner: str = "") -> str:
    return banner + HEADER_DEC.replace("Monday, December 9, 2024", f"{weekday}, {date_words}")


def doc(tmp_path, pages, sha="ab" * 32, label="December 2025 Minutes"):
    """parse_minutes on synthetic page texts (the text cache stands in for the PDF)."""
    cache = tmp_path / "text"
    cache.mkdir(exist_ok=True)
    (cache / f"{sha}.pages.json").write_text(json.dumps(pages))
    src = {"sha256": sha, "url": f"https://example.invalid/{sha[:6]}", "label": label,
           "first_fetched_at": "2026-11-07T00:00:00+00:00", "kind": "minutes"}
    return parse_minutes(tmp_path / f"{sha}.pdf", src, use_ocr=False, text_cache=cache)


# ------------------------------------------------------------------ dates from the text

def test_header_date_comes_from_the_header_sentence():
    assert P.header_date("met in regular session, on Monday, December 9, 2024, at 6:00")[0] == "2024-12-09"


def test_ocr_garbled_day_needs_a_matching_weekday():
    text = (FIX / "header_dec2023_ocr_day.txt").read_text()
    s = segs_of([text])
    assert [(x.date, x.kind, x.role) for x in s] == [("2023-12-11", "formal", "own")]
    assert "weekday matches" in s[0].date_how
    assert P.header_date("on Tuesday, December Ii, 2023")[0] is None        # 2023-12-11 was a Monday
    assert P.header_date("on December Ii, 2023")[0] is None                 # no weekday: never guessed


def test_printed_digits_with_a_contradicting_weekday_give_no_date():
    assert P.header_date("on Tuesday, December 9, 2024")[0] is None


def test_garbled_remembered_is_a_header_but_be_it_resolved_is_not():
    s = segs_of([(FIX / "header_apr2022_garbled.txt").read_text()])     # "BE IT REM1EI~4BEREDthat the Board of"
    assert [(x.date, x.role) for x in s] == [("2022-04-11", "own")]
    assert segs_of([(FIX / "resolution_apr2026_p86.txt").read_text()]) == []
    assert not P.HEADER_RE.search("NOW, THEREFORE, BE IT RESOLVED that the Board of Montgomery County")


def test_special_called_session_is_special():
    s = segs_of([header("April 1, 2024", "Monday").replace("met in regular session,",
                                                           "met in a Special Called session")])
    assert s[0].kind == "special"


# ------------------------------------------------------------------ attached minutes

def test_attached_previous_minutes_nest_inside_the_meetings_own_minutes():
    """Dec 9, 2024 minutes carry the Nov 12 minutes (real page 54) as a consent item, then continue."""
    pages = [HEADER_DEC + RC_CLEAN, (FIX / "embedded_nov2024_p54.txt").read_text() + ADJOURN, RC_CLEAN + ADJOURN]
    s = segs_of(pages)
    assert [(x.date, x.role, x.page, x.end_page, x.closed, x.certain) for x in s] == [
        ("2024-12-09", "own", 1, 3, True, True), ("2024-11-12", "attached", 2, 2, True, True)]


def test_missed_adjournment_line_makes_the_nested_meeting_uncertain_and_holds_its_votes(tmp_path):
    nested = (FIX / "embedded_nov2024_p54.txt").read_text()          # its adjournment line is not read
    d = doc(tmp_path, [HEADER_DEC, nested, RC_CLEAN + ADJOURN])
    own, att = d.meetings
    assert own.segment.certain and not att.segment.certain
    assert [rc.page for rc in att.roll_calls] == [3] and own.roll_calls == []
    assert att.roll_calls[0].status == "Unverified"
    assert any("boundaries uncertain" in r for r in att.roll_calls[0].reasons)


def test_duplicate_of_the_open_header_is_not_a_second_meeting():
    s = segs_of([HEADER_DEC, HEADER_DEC + "\n AGENDA\n", RC_CLEAN + ADJOURN])
    assert [(x.date, x.role) for x in s] == [("2024-12-09", "own")]


# ------------------------------------------------------------------ agenda packets

def packet_pages():
    agenda = ("BOARD OF COMMISSIONERS          AGENDA          DECEMBER 8, 2025\n\n"
              "25-12-1        Resolution to Approve Something New\n\n" + RC_CLEAN)
    minutes = header("November 10, 2025", "Monday",
                     banner="COUNTY COMMISSION MINUTES FOR\n\n NOVEMBER 10, 2025\n\n"
                            " SUBMITTED FOR APPROVAL DECEMBER 8, 2025\n\n") + RC_CLEAN + ADJOURN
    resolution = ("25-12-1\n\nNOW, THEREFORE, BE IT RESOLVED that the Board of Montgomery County\n"
                  "Commissioners hereby approves.\n\n" + RC_CLEAN)
    return [agenda, minutes, resolution]


def test_packet_minutes_are_dated_from_their_own_text_not_the_label(tmp_path):
    d = doc(tmp_path, packet_pages(), label="December 2025 Minutes")
    assert [(m.meeting_date, m.kind, m.segment.role) for m in d.meetings] == [("2025-11-10", "formal",
                                                                                "for_approval")]
    m = d.meetings[0]
    assert [(rc.page, rc.status, rc.meeting_date) for rc in m.roll_calls] == [(2, "Verified", "2025-11-10")]


def test_packet_agenda_and_resolution_pages_are_never_votes_or_listings(tmp_path):
    d = doc(tmp_path, packet_pages())
    assert d.tables_outside_minutes == [1, 3]
    assert all(rc.page == 2 for m in d.meetings for rc in m.roll_calls)
    assert d.meetings[0].agenda == []                     # the Dec 8 agenda is not the Nov 10 meeting's


# ------------------------------------------------------------------ one copy per meeting

def fake(sha, date, role, n_rc=0, certain=True, page=1, end_page=3, verified=0, start=0):
    sg = SimpleNamespace(date=date, kind="formal", role=role, certain=certain, page=page, end_page=end_page,
                         start=start, date_how="digits")
    rcs = [SimpleNamespace(status="Verified" if i < verified else "Unverified") for i in range(n_rc)]
    return SimpleNamespace(source={"sha256": sha * 32, "label": sha}, segment=sg, roll_calls=rcs,
                           meeting_date=date, kind="formal")


def docs(*pms):
    return [SimpleNamespace(meetings=[pm]) for pm in pms]


def test_own_minutes_beat_a_copy_attached_to_the_next_meeting():
    own = fake("bb", "2024-11-12", "own", n_rc=0)
    attached = fake("aa", "2024-11-12", "attached", n_rc=5, page=54, end_page=56)
    chosen, copies, undated = choose(docs(attached, own))
    assert chosen == [own] and undated == []
    assert copies[0]["meeting_id"] == "2024-11-12-formal"
    assert copies[0]["chosen"]["source_id"] == "src-" + "bb" * 6
    assert [c["role"] for c in copies[0]["dropped"]] == ["attached"]


def test_packet_copy_beats_a_nested_copy_and_certain_beats_uncertain():
    packet = fake("aa", "2025-11-10", "for_approval", n_rc=3)
    nested = fake("bb", "2025-11-10", "attached", n_rc=3)
    assert choose(docs(nested, packet))[0] == [packet]
    sure = fake("cc", "2025-10-13", "attached", certain=True)
    unsure = fake("dd", "2025-10-13", "attached", certain=False, n_rc=9)
    assert choose(docs(unsure, sure))[0] == [sure]


def test_the_choice_never_depends_on_how_many_roll_calls_verify():
    a = fake("aa", "2025-11-10", "for_approval", n_rc=4, verified=0)
    b = fake("bb", "2025-11-10", "for_approval", n_rc=4, verified=4)
    first = choose(docs(a, b))[0]
    a2 = fake("aa", "2025-11-10", "for_approval", n_rc=4, verified=4)
    b2 = fake("bb", "2025-11-10", "for_approval", n_rc=4, verified=0)
    assert [p.source["sha256"] for p in first] == [p.source["sha256"] for p in choose(docs(a2, b2))[0]]


def test_undated_minutes_are_reported_never_emitted():
    chosen, _, undated = choose(docs(fake("aa", None, "attached")))
    assert chosen == [] and undated[0]["problem"].startswith("no readable meeting date")


def test_builder_refuses_the_same_meeting_twice(tmp_path):
    d1 = doc(tmp_path, [HEADER_DEC + RC_CLEAN + ADJOURN], sha="cd" * 32)
    d2 = doc(tmp_path, [HEADER_DEC + RC_CLEAN + ADJOURN], sha="ef" * 32)
    b = Builder(Resolver(load_roster(NAMES)), [])
    b.add(d1.meetings[0])
    with pytest.raises(ValueError):
        b.add(d2.meetings[0])
    chosen, copies, _ = choose([d1, d2])
    assert len(chosen) == 1 and len(copies) == 1
