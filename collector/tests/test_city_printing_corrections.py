"""city-seats/printed-misspelling-of-seated-member (code review SHOULD-FIX, 64b5c84; accepted by the manager): a
curated, per-meeting, attendance-only printing correction (agenda-center.yml printing_corrections). The build applies
it only when the meeting's own page proves it, and fails closed otherwise. The real case: the 2026-07-06 minutes
(fileId 3254) print CLAULNCH in the PRESENT list and CLAUNCH in the votes of the same page."""
import pytest
import yaml

from collector import agenda_center as ac
from collector.tests.test_city_names import API, CAPS, FULL, att, meeting, minutes, run

FIX = API.format(2)                                       # the second meeting's minutes file in run()
MISPRINT = CAPS.replace("REYNOLDS", "REYNLODS")            # the PRESENT list misprints one member
ENTRY = {"meeting": "2025-03-06", "minutes_url": FIX, "page": 1, "printed": "REYNLODS", "reads": "REYNOLDS"}


def with_corrections(cfg, *entries):
    return ac.AgendaCenterConfig(**{**cfg.__dict__, "printing_corrections": tuple(entries)})


def build(cfg, second: str, aye: str = CAPS, entries=(ENTRY,), third: str | None = None, absent: str = ""):
    """A full-name list (the roster book: Karen Reynolds, Ward 2), then the 2025-03-06 list `second`."""
    meetings = [("2025-01-02", minutes("2025-01-02", FULL, aye="Brown, Holleman, Pitts, Reynolds, Streetman, "
                                                                 "Zacharias")),
                ("2025-03-06", minutes("2025-03-06", second, absent=absent, aye=aye))]
    if third:
        meetings.append(("2025-04-03", minutes("2025-04-03", third, aye=CAPS)))
    return run(with_corrections(cfg, *entries), meetings)


def check(facts, date):
    return [c for c in meeting(facts, date)["verification"]["checks"] if c["check"] == "printing_correction"]


def votes(facts, date):
    mid = meeting(facts, date)["id"]
    return [v for r in facts["roll_calls"] if r["meeting_id"] == mid for v in r["votes"]]


@pytest.fixture(scope="module")
def cfg():
    return ac.load_config(ac.config_path("clarksville-tn"))


def test_a_proved_correction_reads_the_attendance_entry_and_keeps_the_token_as_printed(cfg):
    facts, summary = build(cfg, MISPRINT)
    a = att(facts, "2025-03-06")
    assert a["REYNLODS"] == "city-karen-reynolds"                        # raw_name stays as printed
    (c,) = check(facts, "2025-03-06")
    assert c["ok"] and c["detail"].startswith("REYNLODS (PRESENT, p. 1) read as REYNOLDS: p. 1 prints REYNOLDS in a "
                                              "vote line, and Karen Reynolds is the one member")
    assert meeting(facts, "2025-03-06")["verification"]["status"] == "verified"
    assert any(v["raw_name"] == "REYNOLDS" and v["official_id"] == "city-karen-reynolds"
               for v in votes(facts, "2025-03-06"))
    w = next(w for w in facts["_wards"] if w["date"] == "2025-03-06" and w["official_id"] == "city-karen-reynolds")
    assert w["raw_name"] == "REYNLODS" and w["reads"] == "REYNOLDS"
    (row,) = summary["printing_corrections"]
    assert row["ok"] and row["printed"] == "REYNLODS"


def test_without_the_entry_the_misprint_stays_held(cfg):
    facts, summary = build(cfg, MISPRINT, entries=())
    assert att(facts, "2025-03-06")["REYNLODS"] is None and check(facts, "2025-03-06") == []
    assert meeting(facts, "2025-03-06")["verification"]["status"] == "unverified"
    assert summary["printing_corrections"] == []


NO_REYNOLDS = CAPS.replace("REYNOLDS, ", "")


@pytest.mark.parametrize("second,aye,absent,why", [
    # the page prints the corrected surname in no vote line
    (MISPRINT, NO_REYNOLDS, "", "no vote line of p. 1 prints REYNOLDS"),
    # the attendance prints both: the member is not left out
    (MISPRINT + ", REYNOLDS", CAPS, "", "the attendance also prints REYNOLDS"),
    # ... or prints the member in full
    (MISPRINT + ", Karen Reynolds (Ward 2)", CAPS, "", "the list already names Karen Reynolds"),
    # the token is on the ABSENT line, not the PRESENT list
    (NO_REYNOLDS, NO_REYNOLDS + ", REYNOLDS", "REYNLODS", "does not print REYNLODS once in its PRESENT list"),
    # not printed at all
    (NO_REYNOLDS, CAPS, "", "does not print REYNLODS once in its PRESENT list"),
    # printed twice
    (MISPRINT + ", REYNLODS", CAPS, "", "does not print REYNLODS once in its PRESENT list"),
])
def test_a_correction_the_page_does_not_prove_is_not_applied(cfg, second, aye, absent, why):
    facts, summary = build(cfg, second, aye=aye, absent=absent)
    (c,) = check(facts, "2025-03-06")
    assert not c["ok"] and why in c["detail"] and "not applied" in c["detail"]
    assert att(facts, "2025-03-06").get("REYNLODS") is None
    assert meeting(facts, "2025-03-06")["verification"]["status"] == "unverified"
    assert not summary["printing_corrections"][0]["ok"]
    assert any(p.get("problem") == c["detail"] for p in summary["problems"])


def test_a_reading_that_is_no_one_or_someone_already_listed_is_not_applied(cfg):
    # REYNARD is on no list of the window: no roster member
    facts, _ = build(cfg, CAPS.replace("REYNOLDS", "REYNRAD"), aye=CAPS.replace("REYNOLDS", "REYNARD"),
                     entries=({**ENTRY, "printed": "REYNRAD", "reads": "REYNARD"},))
    (c,) = check(facts, "2025-03-06")
    assert not c["ok"] and "REYNARD is 0 full names on the meeting's roster book" in c["detail"]
    assert att(facts, "2025-03-06")["REYNRAD"] is None
    # BROWN is listed already: correcting ZACHRIAS to BROWN would list him twice
    facts, _ = build(cfg, CAPS.replace("ZACHARIAS", "ZACHRIAS"),
                     entries=({**ENTRY, "printed": "ZACHRIAS", "reads": "BROWN"},))
    (c,) = check(facts, "2025-03-06")
    assert not c["ok"] and "the attendance also prints BROWN" in c["detail"]
    assert att(facts, "2025-03-06")["ZACHRIAS"] is None


def test_the_correction_never_touches_a_vote_token_or_another_meeting(cfg):
    # a vote line printing the misspelling stays unresolved (the roll call is held), while the attendance is read
    facts, _ = build(cfg, MISPRINT, aye=CAPS + ", REYNLODS", third=MISPRINT)
    assert att(facts, "2025-03-06")["REYNLODS"] == "city-karen-reynolds"
    v = [v for v in votes(facts, "2025-03-06") if v["raw_name"] == "REYNLODS"]
    assert v and all(x["official_id"] is None for x in v)
    # the same misprint at another meeting is not corrected: the entry names one meeting
    assert att(facts, "2025-04-03")["REYNLODS"] is None and check(facts, "2025-04-03") == []


def test_an_entry_for_another_minutes_file_or_page_is_not_applied(cfg):
    facts, summary = build(cfg, MISPRINT, entries=({**ENTRY, "minutes_url": API.format(9)},))
    assert att(facts, "2025-03-06")["REYNLODS"] is None and check(facts, "2025-03-06") == []
    assert summary["printing_corrections"][0] == {**ENTRY, "minutes_url": API.format(9), "ok": False,
                                                  "detail": "not applied: no meeting read from these minutes"}
    facts, _ = build(cfg, MISPRINT, entries=({**ENTRY, "page": 2},))
    (c,) = check(facts, "2025-03-06")
    assert not c["ok"] and att(facts, "2025-03-06")["REYNLODS"] is None


def test_the_real_entry_is_the_2026_07_06_claulnch_printing(cfg):
    (e,) = cfg.printing_corrections
    assert e == {"meeting": "2026-07-06", "page": 1, "printed": "CLAULNCH", "reads": "CLAUNCH",
                 "minutes_url": "https://clarksvilletn.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3254,"
                                "plainText=false)"}


@pytest.mark.parametrize("bad,match", [
    ({"note": "x"}, "must be"),
    ({"minutes_url": "http://x.gov/m.pdf"}, "minutes_url must be an https URL"),
    ({"page": 0}, "page must be a page number"),
    ({"printed": "Eric Claunch"}, "printed must be one surname"),
    ({"reads": "CLAUNCH (Ward 2)"}, "reads must be one surname"),
    ({"reads": "claulnch"}, "reads must differ from printed"),
    ({"meeting": "July 6"}, "meeting must be a date"),
])
def test_a_bad_entry_is_refused_at_load(bad, match):
    raw = yaml.safe_load(ac.config_path("clarksville-tn").read_text())
    (real,) = raw["printing_corrections"]
    with pytest.raises(ac.AgendaCenterConfigError, match=match):
        ac.parse_config({**raw, "printing_corrections": [{**real, **bad}]})


def test_two_entries_for_one_printing_are_refused():
    raw = yaml.safe_load(ac.config_path("clarksville-tn").read_text())
    (real,) = raw["printing_corrections"]
    with pytest.raises(ac.AgendaCenterConfigError, match="a second entry for CLAULNCH"):
        ac.parse_config({**raw, "printing_corrections": [real, {**real, "reads": "CLAUNCHE"}]})
