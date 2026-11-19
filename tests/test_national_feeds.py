# ruff: noqa: E501
"""Task C4 (docs/tasks/daylight-national.md; finding 3, `national/feed-ics-injection`): the Daylight ICS writer and
the Atom feed through sitegen/feeds.py (docs/architecture/daylight-national.md 3.6). The parser here is the test's
own stdlib reader of RFC 5545: unfold, split on the first unescaped ':', unescape TEXT."""
import copy
import re
import xml.etree.ElementTree as ET

import pytest

from sitegen import national_feeds as nf
from sitegen import national_guards as guards

A = "{http://www.w3.org/2005/Atom}"
PAGE = "https://daylight.gnoshcodes.com/digest/tn/county-47125.html"
EVIL = "Budget\r\nBEGIN:VEVENT\r\nUID:evil@x\r\nSUMMARY:pwned; a, b \\ c\r\nEND:VEVENT"


def _feed(title=EVIL, item_text=EVIL, **meeting):
    m = {"id": "2026-12-14-formal", "date": "2026-12-14", "time": None, "title": title, "title_ours": False,
         "meeting_url": "https://example.gov/m", "agenda": {"state": "final", "url": "https://example.gov/a.pdf",
                                                            "status_as_posted": None},
         "may_be_incomplete": False, "items_withheld": False, "item_count": 1,
         "items": [{"seq": 1, "number": "CZ-1", "text": item_text,
                    "source": {"url": "https://example.gov/a.pdf#page=1", "page": 1}}]}
    m.update(meeting)
    return {"schema": "daylight-upcoming/1", "review": None,
            "body": {"id": "county-47125", "name": "Montgomery County Commission", "tz": "America/Chicago",
                     "official_url": "https://example.gov/", "platform": "daylight", "full_url": None},
            "checked_at": "2026-11-19T14:02:00Z", "last_ok_at": None, "meetings": [m]}


def _unescape(value: str) -> str:
    return re.sub(r"\\([\\;,nN])", lambda g: "\n" if g.group(1) in "nN" else g.group(1), value)


def parse_ics(raw: bytes) -> list[dict]:
    """The VEVENTs of an ICS file as {name: value} (TEXT unescaped). Fails on any line structure RFC 5545 forbids."""
    s = raw.decode("utf-8")
    assert s.endswith("\r\n") and "\n" not in s.replace("\r\n", "") and "\r" not in s.replace("\r\n", "")
    physical = s[:-2].split("\r\n")
    for line in physical:
        assert len(line.encode("utf-8")) <= 75, line
    logical = []
    for line in physical:
        if line.startswith((" ", "\t")):
            logical[-1] += line[1:]
        else:
            logical.append(line)
    assert logical[0] == "BEGIN:VCALENDAR" and logical[-1] == "END:VCALENDAR"
    events, cur = [], None
    for line in logical[1:-1]:
        m = re.match(r"([A-Z-]+)((?:;[^:]*)?):(.*)\Z", line, re.S)
        assert m, line
        name, params, value = m.groups()
        if (name, value) == ("BEGIN", "VEVENT"):
            assert cur is None
            cur = {}
        elif (name, value) == ("END", "VEVENT"):
            events.append(cur)
            cur = None
        elif cur is not None:
            assert name not in cur, f"repeated {name}"
            cur[name + params] = _unescape(value) if name in ("SUMMARY", "DESCRIPTION") else value
    assert cur is None
    return events


def test_injection_is_one_escaped_folded_line_in_one_event():
    raw = nf.render_ics(_feed(), PAGE)
    events = parse_ics(raw)
    assert len(events) == 1
    ev = events[0]
    assert ev["UID"] == "county-47125/2026-12-14-formal@daylight.gnoshcodes.com"
    assert ev["SUMMARY"] == "Montgomery County Commission: Budget BEGIN:VEVENT UID:evil@x SUMMARY:pwned; a, b \\ c END:VEVENT"
    s = raw.decode()
    # exactly one BEGIN:VEVENT at a line start; the payload sits inside the SUMMARY's folded line
    assert re.findall(r"(?m)^BEGIN:VEVENT\r?$", s) == ["BEGIN:VEVENT\r"]
    summary = re.search(r"SUMMARY:.*?\r\n(?! )", s, re.S).group(0)
    assert summary.count("\r\n") >= 2          # long enough to fold
    unfolded = summary.replace("\r\n ", "")
    assert unfolded.count("\r\n") == 1 and "\\;" in unfolded and "\\," in unfolded and "\\\\" in unfolded
    # no item text in a calendar (3.6)
    assert "CZ-1" not in s and s.count("pwned") == 1


def test_escape_and_controls():
    assert nf.text("a\\b;c,d\ne") == "a\\\\b\\;c\\,d e"
    assert nf.text("x\x00\x07\x7f\x9f‮​y\tz\r\n") == "xy z"
    assert nf.text("a\x85b\u2028c") == "a b c"          # NEL and line separator are line breaks: word breaks
    assert nf.text(None) == ""


@pytest.mark.parametrize("ch", ["é", "€", "😀", "中"])
def test_fold_never_splits_a_character(ch):
    line = "SUMMARY:" + ch * 200
    folded = nf.fold(line)
    parts = folded.split("\r\n")
    assert all(len(p.encode()) <= 75 for p in parts)
    assert all(p.startswith(" ") for p in parts[1:])
    assert parts[0] + "".join(p[1:] for p in parts[1:]) == line
    for p in parts:
        p.encode().decode("utf-8")


def test_fold_short_and_exact():
    assert nf.fold("A" * 75) == "A" * 75
    assert nf.fold("A" * 76) == "A" * 75 + "\r\n A"


def test_uids_stable_and_bytes_stable_across_runs():
    f = _feed()
    assert nf.render_ics(f, PAGE) == nf.render_ics(copy.deepcopy(f), PAGE)
    changed = _feed(title="Other")
    assert parse_ics(nf.render_ics(changed, PAGE))[0]["UID"] == parse_ics(nf.render_ics(f, PAGE))[0]["UID"]


def test_parser_reads_back_exactly_the_expected_events():
    f = _feed(title="Formal Session")
    f["meetings"].append({**f["meetings"][0], "id": "2026-12-15-work", "date": "2026-12-15", "time": "6:00 PM",
                          "title": "Work Session", "agenda": {"state": "not-posted", "url": None}})
    f["meetings"].append({**f["meetings"][0], "id": "2026-12-16-x", "date": "2026-12-16", "time": "after the 5 pm meeting",
                          "title": "Special", "agenda": {"state": "not-final", "url": "javascript:alert(1)"}})
    f["meetings"].append({**f["meetings"][0], "id": "Bad\nId"})          # dropped: bad meeting id
    f["meetings"].append({**f["meetings"][0], "id": "2026-12-17", "date": "soon"})   # dropped: bad date
    stamp = "20261119T140200Z"
    assert parse_ics(nf.render_ics(f, PAGE)) == [
        {"UID": "county-47125/2026-12-14-formal@daylight.gnoshcodes.com", "DTSTAMP": stamp,
         "DTSTART;VALUE=DATE": "20261214", "SEQUENCE": "0",
         "SUMMARY": "Montgomery County Commission: Formal Session",
         "DESCRIPTION": "Agenda posted: https://example.gov/a.pdf", "URL": PAGE},
        {"UID": "county-47125/2026-12-15-work@daylight.gnoshcodes.com", "DTSTAMP": stamp,
         "DTSTART": "20261216T000000Z", "DURATION": "PT1H", "SEQUENCE": "0",       # 6 PM CST = 00:00 UTC next day
         "SUMMARY": "Montgomery County Commission: Work Session",
         "DESCRIPTION": "Agenda not posted yet.", "URL": PAGE},
        {"UID": "county-47125/2026-12-16-x@daylight.gnoshcodes.com", "DTSTAMP": stamp,
         "DTSTART;VALUE=DATE": "20261216", "SEQUENCE": "0",
         "SUMMARY": "Montgomery County Commission: Special, after the 5 pm meeting",
         "DESCRIPTION": "Agenda posted, not final yet.", "URL": PAGE},
    ]


@pytest.mark.parametrize("day,want", [("2026-07-14", "20260714T230000Z"),     # CDT, UTC-5
                                      ("2026-10-31", "20261031T230000Z"),     # the day before the Nov 1 change
                                      ("2026-11-02", "20261103T000000Z"),     # just after it: CST, UTC-6
                                      ("2027-03-15", "20270315T230000Z")])    # after the March change
def test_timed_start_follows_dst(day, want):
    ev = parse_ics(nf.render_ics(_feed(title="T", date=day, time="6:00 PM"), PAGE))[0]
    assert ev["DTSTART"] == want and ev["DURATION"] == "PT1H"


@pytest.mark.parametrize("tz", ["Mars/Olympus", "../etc/passwd", ""])
def test_bad_tz_gives_all_day_event(tz):
    f = _feed(title="T", time="6:00 PM")
    f["body"]["tz"] = tz
    if not tz:
        f["body"]["tz"] = "America/Chicago\x00"
    ev = parse_ics(nf.render_ics(f, PAGE))[0]
    assert ev["DTSTART;VALUE=DATE"] == "20261214" and "DURATION" not in ev and "DTSTART" not in ev
    assert ev["SUMMARY"] == "Montgomery County Commission: T, 6:00 PM"


def test_atom_unknown_state_uses_fixed_label():
    root = ET.fromstring(nf.render_atom(_feed(agenda={"state": "odd", "url": "https://example.gov/a.pdf"}), "tn"))
    assert root.find(f"{A}entry/{A}summary").text.endswith("Agenda not posted yet.")


def test_page_url_must_be_https():
    assert "URL" not in parse_ics(nf.render_ics(_feed(), "javascript:alert(1)"))[0]


def test_bad_body_id_refused():
    f = _feed()
    f["body"]["id"] = "county-47125\r\nX"
    with pytest.raises(guards.UnsafeIdError):
        nf.render_ics(f, PAGE)


@pytest.mark.parametrize("posted,want", [("6:00 PM", (18, 0)), ("9 a.m.", (9, 0)), ("12:30 pm", (12, 30)),
                                         ("12 AM", (0, 0)), ("18:30", (18, 30)), ("13 PM", None), ("noon", None),
                                         (None, None)])
def test_parse_time(posted, want):
    t = nf.parse_time(posted)
    assert (None if t is None else (t.hour, t.minute)) == want


def test_sequence_bumps_only_on_agenda_change():
    f = _feed()
    s1 = nf.sequences(f)
    u = "county-47125/2026-12-14-formal@daylight.gnoshcodes.com"
    assert s1[u]["sequence"] == 0
    assert nf.sequences(_feed(title="Renamed"), s1)[u]["sequence"] == 0
    s2 = nf.sequences(_feed(agenda={"state": "final", "url": "https://example.gov/b.pdf"}), s1)
    assert s2[u]["sequence"] == 1
    s3 = nf.sequences(_feed(agenda={"state": "not-final", "url": "https://example.gov/b.pdf"}), s2)
    assert s3[u]["sequence"] == 2
    assert parse_ics(nf.render_ics(f, PAGE, s3))[0]["SEQUENCE"] == "2"


def test_atom_through_feeds_render():
    f = _feed()
    f["meetings"].append({**f["meetings"][0], "id": "2026-12-15-work", "date": "2026-12-15",
                          "agenda": {"state": "not-posted", "url": None}})
    raw = nf.render_atom(f, "tn")
    root = ET.fromstring(raw)
    entries = root.findall(f"{A}entry")
    assert len(entries) == 1                                   # the not-posted meeting has no entry
    e = entries[0]
    assert e.find(f"{A}id").text.endswith("county-47125/meeting/2026-12-14-formal/agenda")
    title = e.find(f"{A}title").text
    assert "\r" not in title and "\n" not in title and title.count("BEGIN:VEVENT") == 1
    assert "CZ-1" not in raw.decode()
    assert nf.render_atom(copy.deepcopy(f), "tn") == raw
    with pytest.raises(guards.UnsafeIdError):
        nf.render_atom(f, "../x")
