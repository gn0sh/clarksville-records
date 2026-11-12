"""Meeting video transcripts (spec AC6.3): import (collector/transcripts.py), call-on detection and name resolution
(sitegen/transcripts.py), the transcript and member pages, and the file cap per target.

Rules under test: every line verbatim, labelled Transcript, linked to <video_url>#t=<whole seconds>; a call-on is read
from the TEXT only and resolves only when exactly one entry of that meeting's attendance shown on the site has the
surname (name resolution invariant, docs/architecture/city-council.md); nothing is summarised or reworded; the import
and the pages are deterministic."""
import html
import json
import re
import shutil
from pathlib import Path

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT
from collector import transcripts as ctx
from qa import site_checks
from sitegen import config, council, transcripts as tx
from sitegen.build import build

CITY = ROOT / "data" / "localities" / "clarksville-tn"
CFG = config.load_council("clarksville-tn")
MEETING = "2026-02-05-regular"       # minutes read, attendance shown, video on CivicClerk
HOSTILE = '<script>alert(1)</script> "quoted" & <b>bold</b> <a href="javascript:x">x</a>'


LISTING = ctx.load_listing(CITY / "civicclerk-listing.json")
EVENT = 2618                          # MEETING's event in the city's listing


def kind_of(title: str) -> str:
    from collector.agenda_center import load_config
    return load_config().kind_of(title)


def city_facts() -> dict:
    return json.loads((CITY / "facts.json").read_text(encoding="utf-8"))


def raw_transcript(meeting: dict, segments, **over) -> dict:
    d = {"event_id": 2618, "event_name": "Regular Session", "start": meeting["date"], "video_url": meeting["video_url"],
         "model": "small.en", "model_version": "faster-whisper 1.2.1", "created_at": "2026-11-09T21:17:07Z",
         "segments": [{"start": a, "end": b, "text": t, "words": [{"start": a, "end": b, "word": t, "prob": 0.5}]}
                      for a, b, t in segments]}
    d.update(over)
    return d


SEGMENTS = [
    (0.0, 4.0, "Good evening, the meeting will come to order."),
    (4.0, 9.5, "councilman Smith you're recognized thank you mayor I have a question"),
    (9.5, 15.0, "about the paving contract on Main Street and the schedule"),
    (15.0, 21.0, HOSTILE),
    (21.0, 26.0, "and that is all I have.\x07 Thank you. Councilman"),
    (26.0, 30.0, "Brown, you're recognized. Thank you Mayor."),
    (30.0, 35.0, "I agree with Councilman Smith on this one."),          # a mention, not a call-on
    (35.0, 40.0, "councilman holloman you recognized thank you mayor"),  # near spelling of Holleman: never matched
    (40.0, 45.0, "councilman Chandler you're recognized thank you I yield"),       # Chandler: listed absent, so never linked
    (45.0, 50.0, "the chair recognizes Councilwoman Lovato on the item"),
]


def write_raw(folder: Path, d: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{d['start']}_{d['event_id']}.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------------------------------------- import

def test_import_compacts_and_matches_by_video_url(tmp_path):
    facts = city_facts()
    m = next(x for x in facts["meetings"] if x["id"] == MEETING)
    write_raw(tmp_path / "in", raw_transcript(m, SEGMENTS))
    out = tmp_path / "out"
    log = ctx.import_dir(tmp_path / "in", facts, out, kind_of, LISTING)
    assert [r["meeting_id"] for r in log["imported"]] == [MEETING] and log["imported"][0]["matched_by"] == "video_url"
    t = json.loads((out / f"{MEETING}.json").read_text(encoding="utf-8"))
    assert t["video_url"] == m["video_url"] and t["model"] == "small.en" and t["source_file"] == "2026-02-05_2618.json"
    assert all(len(s) == 3 for s in t["segments"]) and "words" not in json.dumps(t)
    # hostile text is data: kept as written (escaped only when rendered); control characters removed
    assert t["segments"][3][2] == HOSTILE
    assert t["segments"][4][2] == "and that is all I have. Thank you. Councilman"
    assert json.loads((out / "index.json").read_text())[MEETING]["segments"] == len(SEGMENTS)


def test_import_is_deterministic_and_idempotent(tmp_path):
    facts = city_facts()
    m = next(x for x in facts["meetings"] if x["id"] == MEETING)
    write_raw(tmp_path / "in", raw_transcript(m, SEGMENTS))
    ctx.import_dir(tmp_path / "in", facts, tmp_path / "a", kind_of, LISTING)
    first = {p.name: p.read_bytes() for p in (tmp_path / "a").iterdir()}
    log = ctx.import_dir(tmp_path / "in", facts, tmp_path / "a", kind_of, LISTING)
    assert log["imported"] == [] and len(log["unchanged"]) == 1
    assert {p.name: p.read_bytes() for p in (tmp_path / "a").iterdir()} == first
    # a separate run elsewhere gives the same bytes (no clock, sorted keys)
    ctx.import_dir(tmp_path / "in", facts, tmp_path / "b", kind_of, LISTING)
    assert {p.name: p.read_bytes() for p in (tmp_path / "b").iterdir()} == first


def test_import_matches_by_date_and_kind_only_without_a_video_url(tmp_path):
    facts = city_facts()
    m = next(x for x in facts["meetings"] if x["id"] == MEETING)
    write_raw(tmp_path / "in", raw_transcript(m, SEGMENTS, video_url=None))
    log = ctx.import_dir(tmp_path / "in", facts, tmp_path / "out", kind_of, LISTING)
    assert log["imported"][0]["matched_by"] == "date_kind"
    # the link always goes to the meeting's own video
    assert json.loads((tmp_path / "out" / f"{MEETING}.json").read_text())["video_url"] == m["video_url"]


def test_import_never_guesses(tmp_path):
    facts = city_facts()
    m = next(x for x in facts["meetings"] if x["id"] == MEETING)
    write_raw(tmp_path / "in", raw_transcript(m, SEGMENTS, video_url="https://evil.example/x.mp4"))
    write_raw(tmp_path / "in", raw_transcript({**m, "date": "2026-02-06"}, SEGMENTS, video_url=None, event_id=5))
    write_raw(tmp_path / "in", raw_transcript(m, [(5.0, 1.0, "ends before it starts")], event_id=6))
    (tmp_path / "in" / "notes.json").write_text("{}")
    log = ctx.import_dir(tmp_path / "in", facts, tmp_path / "out", kind_of, LISTING)
    assert log["imported"] == [] and len(log["skipped"]) == 4
    assert json.loads((tmp_path / "out" / "index.json").read_text()) == {}


def test_import_refuses_a_second_transcript_of_a_meeting_under_another_event(tmp_path):
    # facts meetings carry no event_id: the listing decides, so a later transcript under another event is refused
    facts = city_facts()
    m = next(x for x in facts["meetings"] if x["id"] == MEETING)
    assert "event_id" not in m
    write_raw(tmp_path / "in", raw_transcript(m, SEGMENTS, event_id=EVENT, created_at="2026-11-09T01:00:00Z"))
    write_raw(tmp_path / "in", raw_transcript(m, SEGMENTS[:2], event_id=778, created_at="2026-11-10T01:00:00Z"))
    log = ctx.import_dir(tmp_path / "in", facts, tmp_path / "out", kind_of, LISTING)
    assert json.loads((tmp_path / "out" / f"{MEETING}.json").read_text())["source_file"] == "2026-02-05_2618.json"
    assert [s["file"] for s in log["skipped"]] == ["2026-02-05_778.json"]
    assert "listing has" in log["skipped"][0]["why"] and "event 2618" in log["skipped"][0]["why"]


def test_import_checks_the_listing_when_the_meeting_has_no_event_id(tmp_path):
    facts = city_facts()
    m = next(x for x in facts["meetings"] if x["id"] == MEETING)
    assert "event_id" not in m
    # the wrong event, by video_url and by date + kind: refused
    write_raw(tmp_path / "a", raw_transcript(m, SEGMENTS, event_id=900))
    write_raw(tmp_path / "b", raw_transcript(m, SEGMENTS, event_id=900, video_url=None))
    for d in ("a", "b"):
        log = ctx.import_dir(tmp_path / d, facts, tmp_path / f"out-{d}", kind_of, LISTING)
        assert log["imported"] == [] and "event 2618, the transcript is event 900" in log["skipped"][0]["why"]
    # a video the listing does not name: refused, never imported on the facts match alone
    write_raw(tmp_path / "c", raw_transcript(m, SEGMENTS, event_id=EVENT))
    no_video = {u: e for u, e in LISTING.items() if u != m["video_url"]}
    log = ctx.import_dir(tmp_path / "c", facts, tmp_path / "out-c", kind_of, no_video)
    assert log["imported"] == [] and "names no event" in log["skipped"][0]["why"]
    # a video the listing names under two events is ambiguous: refused
    two = {**LISTING, m["video_url"]: {str(EVENT), "900"}}
    assert ctx.import_dir(tmp_path / "c", facts, tmp_path / "out-c", kind_of, two)["imported"] == []
    # the right event imports
    log = ctx.import_dir(tmp_path / "c", facts, tmp_path / "out-c", kind_of, LISTING)
    assert [r["meeting_id"] for r in log["imported"]] == [MEETING]
    # and a later listing that moves the video to another event removes the committed transcript
    log = ctx.import_dir(tmp_path / "empty", facts, tmp_path / "out-c", kind_of, {**LISTING, m["video_url"]: {"900"}})
    assert [r["file"] for r in log["removed"]] == [f"{MEETING}.json"]


def test_load_listing_refuses_a_missing_or_empty_listing(tmp_path):
    with pytest.raises(ctx.TranscriptError):
        ctx.load_listing(tmp_path / "nope.json")
    (tmp_path / "empty.json").write_text("[]")
    with pytest.raises(ctx.TranscriptError, match="names no video"):
        ctx.load_listing(tmp_path / "empty.json")


def test_import_compares_event_id_when_the_meeting_carries_one(tmp_path):
    facts = city_facts()
    m = next(x for x in facts["meetings"] if x["id"] == MEETING)
    write_raw(tmp_path / "in", raw_transcript(m, SEGMENTS, event_id=2618))
    other = {**facts, "meetings": [{**x, "event_id": 900} if x["id"] == MEETING else x for x in facts["meetings"]]}
    log = ctx.import_dir(tmp_path / "in", other, tmp_path / "out", kind_of, LISTING)
    assert log["imported"] == [] and "event 900" in log["skipped"][0]["why"]
    same = {**facts, "meetings": [{**x, "event_id": 2618} if x["id"] == MEETING else x for x in facts["meetings"]]}
    log = ctx.import_dir(tmp_path / "in", same, tmp_path / "out", kind_of, LISTING)
    assert [r["meeting_id"] for r in log["imported"]] == [MEETING]
    # without a video_url (date + kind) the event_id is compared too
    write_raw(tmp_path / "in2", raw_transcript(m, SEGMENTS, video_url=None, event_id=2618))
    assert ctx.import_dir(tmp_path / "in2", other, tmp_path / "out2", kind_of, LISTING)["imported"] == []


def test_import_removes_transcripts_that_no_longer_match(tmp_path):
    facts = city_facts()
    m = next(x for x in facts["meetings"] if x["id"] == MEETING)
    write_raw(tmp_path / "in", raw_transcript(m, SEGMENTS))
    out = tmp_path / "out"
    ctx.import_dir(tmp_path / "in", facts, out, kind_of, LISTING)
    assert (out / f"{MEETING}.json").is_file()
    # the next import from an empty folder keeps a transcript that still matches
    (tmp_path / "empty").mkdir()
    log = ctx.import_dir(tmp_path / "empty", facts, out, kind_of, LISTING)
    assert log["removed"] == [] and MEETING in json.loads((out / "index.json").read_text())
    # the meeting's video changed: the transcript no longer matches it, so it and its index entry go
    moved = {**facts, "meetings": [{**x, "video_url": "https://cpmedia.azureedge.net/clarksvilletn/new.mp4"}
                                   if x["id"] == MEETING else x for x in facts["meetings"]]}
    log = ctx.import_dir(tmp_path / "empty", moved, out, kind_of, LISTING)
    assert [r["file"] for r in log["removed"]] == [f"{MEETING}.json"]
    assert not (out / f"{MEETING}.json").exists() and json.loads((out / "index.json").read_text()) == {}
    # a meeting gone from the facts, or an event_id that differs, also removes it
    ctx.import_dir(tmp_path / "in", facts, out, kind_of, LISTING)
    gone = {**facts, "meetings": [x for x in facts["meetings"] if x["id"] != MEETING]}
    assert len(ctx.import_dir(tmp_path / "empty", gone, out, kind_of, LISTING)["removed"]) == 1
    ctx.import_dir(tmp_path / "in", facts, out, kind_of, LISTING)
    ev = {**facts, "meetings": [{**x, "event_id": 1} if x["id"] == MEETING else x for x in facts["meetings"]]}
    assert len(ctx.import_dir(tmp_path / "empty", ev, out, kind_of, LISTING)["removed"]) == 1


def test_committed_transcripts_match_their_meetings():
    facts = city_facts()
    loaded = tx.load(CITY / "facts.json", facts)
    assert loaded, "at least one transcript is committed"
    by_id = {m["id"]: m for m in facts["meetings"]}
    for mid, t in loaded.items():
        assert t["video_url"] == by_id[mid]["video_url"]
    # every committed file passes the importer's own check, the event listing included
    files = [p for p in (CITY / "transcripts").glob("*.json") if p.name != "index.json"]
    assert len(files) == len(loaded) == 17
    for p in files:
        assert ctx.stale(json.loads(p.read_text(encoding="utf-8")), by_id, LISTING) is None, p.name


# ---------------------------------------------------------------------------------------------- links and detection

def test_timestamp_link_format():
    url = "https://cpmedia.azureedge.net/clarksvilletn/abc.mp4"
    assert tx.video_href(url, 1184.98) == f"{url}#t=1184"     # whole seconds, rounded down: never after the words
    assert tx.video_href(url, 0) == f"{url}#t=0"
    assert tx.clock(3725.5) == "1:02:05" and tx.clock(59.9) == "0:00:59"


@pytest.mark.parametrize("url", [
    "http://cpmedia.azureedge.net/clarksvilletn/abc.mp4",          # not https
    "https://evil.example/clarksvilletn/abc.mp4",                  # another host
    "https://cpmedia.azureedge.net.evil.example/abc.mp4",          # a host that only starts like it
    "https://user@cpmedia.azureedge.net/abc.mp4",                  # userinfo
    "https://cpmedia.azureedge.net:8443/abc.mp4",                  # a port
    "https://cpmedia.azureedge.net/clarksvilletn/abc.mp4.html",    # not an .mp4 path
    "https://cpmedia.azureedge.net/clarksvilletn/abc.mp4#t=5",     # already has a fragment
    None,
])
def test_no_timestamp_link_to_a_video_the_rule_does_not_allow(url):
    assert tx.video_ok(url) is False and tx.video_href(url, 12.0) is None
    assert site_checks.video_ok(url) is False                       # the QA check restates the same rule
    assert config.VIDEO_HOSTS == site_checks.VIDEO_HOSTS


def test_a_disallowed_video_shows_times_as_text_only(tmp_path):
    facts = city_facts()
    wards = json.loads((CITY / "wards.json").read_text(encoding="utf-8"))
    bad = "https://evil.example/clarksvilletn/x.mp4"
    facts = {**facts, "meetings": [{**x, "video_url": bad} if x["id"] == MEETING else x for x in facts["meetings"]]}
    cix = council.load(CFG, facts, wards)
    cix.tx = tx.Transcripts(cix, {MEETING: {"meeting_id": MEETING, "video_url": bad, "segments": segs(),
                                            "model": "m", "model_version": "v", "created_at": "2026-11-09"}})
    assert all(line["href"] is None for line in cix.tx.lines(MEETING))
    assert cix.tx.page(MEETING)["video_ok"] is False
    rows = cix.tx.member_rows("city-wanda-smith")
    assert rows and all(r["video_href"] is None for r in rows)


def segs(rows=SEGMENTS):
    return [[a, b, ctx.clean_text(t)] for a, b, t in rows]


def test_detection_reads_call_ons_from_the_text_only():
    found = [(d["seg"], d["name"]) for d in tx.detect(segs())]
    # a title split across two lines is found; a mention ("I agree with Councilman Smith") is not a call-on
    assert found == [(1, "Smith"), (4, "Brown"), (7, "holloman"), (8, "Chandler"), (9, "Lovato")]


@pytest.mark.parametrize("text", ["councilman you're recognized", "Councilman Smith recognizes the effort",
                                  "thank you councilman Smith", "council members you're recognized",
                                  "Councilwoman Smith recognized the students",
                                  "Councilman Brown, you recognize this is a tough vote",
                                  "Chairman Pitts recognized the veterans",
                                  "Councilman Brown recognized",
                                  # call-on invariant: the recognition must be in the same clause as the name...
                                  "Thank you Councilman Smith. You are recognized, Councilwoman Jones.",
                                  "I yield to Councilman Smith. You recognized me earlier.",
                                  "Councilman Smith; you're recognized.", "Councilman Smith - you're recognized.",
                                  # ...and must end it
                                  "Councilman Smith, you recognized that the budget was short",
                                  "Councilman Smith, you are recognized for your service",
                                  "councilman Smith you're recognized on the consent agenda",
                                  "Councilman Smith you recognized thanks to the staff the problem",
                                  "Councilman Smith you recognized, I think, the problem"])
def test_detection_ignores_non_call_ons(text):
    assert tx.detect([[0.0, 3.0, text]]) == []


@pytest.mark.parametrize("text,name", [("Councilman Brown, you're recognized.", "Brown"),
                                       ("councilman brown you are recognized", "brown"),
                                       ("Councilwoman Smith you recognized thank you", "Smith"),
                                       ("Councilman Brown, you’re recognised", "Brown"),
                                       ("the chair recognizes Councilwoman Smith now", "Smith"),
                                       ("Councilman Smith, you're recognized.", "Smith"),
                                       ("Councilman Smith you're recognized", "Smith"),       # end of the line
                                       ("councilman Smith you recognized thanks mayor", "Smith"),
                                       ("Councilman Smith, you're recognized, go ahead", "Smith")])
def test_detection_finds_the_call_on_forms(text, name):
    found = tx.detect([[0.0, 3.0, text]])
    assert [d["name"] for d in found] == [name]
    assert found[0]["matched"] in text                               # the matched words, verbatim


def test_a_call_on_at_the_end_of_a_line_ends_its_clause_only_if_the_next_line_starts_a_new_one():
    found = tx.detect([[0.0, 2.0, "Councilman Smith you're recognized"], [2.0, 4.0, "thank you mayor I have a question"]])
    assert [d["name"] for d in found] == ["Smith"]
    assert tx.detect([[0.0, 2.0, "Councilman Smith, you recognized"], [2.0, 4.0, "that the budget was short"]]) == []
    assert tx.detect([[0.0, 2.0, "Councilman Smith you're recognized"], [2.0, 4.0, "on the item"]]) == []
    assert tx.detect([[0.0, 4.0, "Councilman Smith you're recognized on the item I have a question"]]) == []


def test_excerpt_is_verbatim_and_bounded():
    s = segs()
    joined = " ".join(x[2] for x in s)
    for d in tx.detect(s):
        assert d["excerpt"] in joined, "never reworded: the excerpt is a stretch of the transcript text"
        assert len(d["excerpt"]) > 0
    first = tx.detect(s)[0]
    # runs to the lines starting within 20 s of the call-on, and stops before the next call-on ("Councilman Brown")
    assert first["excerpt"].startswith("thank you mayor I have a question about the paving contract")
    assert first["excerpt"].endswith("Thank you") and "Brown" not in first["excerpt"]


# ------------------------------------------------------------------------------- name resolution invariant

def meeting_with(att, status="verified", extracted=True):
    return {"attendance_status": "extracted" if extracted else "not_extracted",
            "verification": {"status": status, "checks": []}, "attendance": att}


OFF = {"a": {"id": "a", "surname": "Smith"}, "b": {"id": "b", "surname": "Brown"}, "c": {"id": "c", "surname": "Smith"}}


def att(oid, raw, status="present"):
    return {"official_id": oid, "raw_name": raw, "status": status, "page": 1}


def test_resolves_only_on_exactly_one_roster_match():
    r = tx.roster(meeting_with([att("a", "SMITH"), att("b", "BROWN")]), OFF)
    assert tx.resolve("smith", r) == ("a", "")
    assert tx.resolve("Smyth", r)[0] is None                       # never a near spelling
    two = tx.roster(meeting_with([att("a", "SMITH"), att("c", "SMITH")]), OFF)
    assert tx.resolve("Smith", two)[0] is None                     # two members with the surname: held
    blocked = tx.roster(meeting_with([att("a", "SMITH"), att(None, "W. SMITH")]), OFF)
    assert tx.resolve("Smith", blocked)[0] is None                 # an unresolved entry still blocks
    alone = tx.roster(meeting_with([att(None, "CLAUNCH")]), OFF)
    assert tx.resolve("Claunch", alone)[0] is None                 # the one match did not resolve to a member


def test_an_absent_member_blocks_but_never_links():
    r = tx.roster(meeting_with([att("a", "SMITH", "absent"), att("b", "BROWN")]), OFF)
    oid, why = tx.resolve("Smith", r)
    assert oid is None and "absent" in why                          # listed absent: never linked
    assert tx.resolve("Brown", r) == ("b", "")
    shared = tx.roster(meeting_with([att("a", "SMITH"), att("c", "SMITH", "absent")]), OFF)
    assert tx.resolve("Smith", shared)[0] is None                   # still blocks the present member's shared surname


OFF2 = {"a": {"id": "a", "surname": "Smith"}, "b": {"id": "b", "surname": "Brown"},
        "l": {"id": "l", "surname": "Little"}, "s": {"id": "s", "surname": "Streetman"},
        "d": {"id": "d", "surname": "Arrived"}}


@pytest.mark.parametrize("raw,blocked", [
    ("DaJaun Little m", "Little"),          # the surname is not the last word
    ("DaJaun Little m", "DaJaun"),          # every word of the printed name blocks
    ("StaceyStreetman", "Streetman"),       # a registered surname inside the name with no space
    ("Stacey Street man", "Streetman"),     # ... with spaces removed
    ("arrived at 6:04)", "arrived"),
])
def test_an_unresolved_line_blocks_every_name_in_it(raw, blocked):
    members = {"l": att("l", "LITTLE"), "s": att("s", "STREETMAN"), "d": att("d", "ARRIVED")}
    present = [v for k, v in members.items() if OFF2[k]["surname"].casefold() == blocked.casefold()]
    r = tx.roster(meeting_with([*present, att(None, raw)]), OFF2)
    assert tx.resolve(blocked, r)[0] is None
    if present:   # without the unresolved line the member would have linked
        assert tx.resolve(blocked, tx.roster(meeting_with(present), OFF2))[0] is not None


def test_no_roster_no_link():
    assert tx.roster(meeting_with([att("a", "SMITH")], status="unverified"), OFF) is None   # attendance under review
    assert tx.roster(meeting_with([], extracted=False), OFF) is None                         # no minutes read
    assert tx.resolve("Smith", None)[0] is None


def test_every_resolved_call_on_is_on_the_meetings_own_shown_attendance():
    """The invariant over the real data: a call-on links a member only if that member is on the meeting's own
    attendance as shown, and no other entry there has the surname."""
    facts = city_facts()
    wards = json.loads((CITY / "wards.json").read_text(encoding="utf-8"))
    cix = council.load(CFG, facts, wards)
    m = cix.meetings[MEETING]
    t = {"meeting_id": MEETING, "video_url": m["video_url"], "segments": segs()}
    cix.tx = tx.Transcripts(cix, {**tx.load(CITY / "facts.json", facts), MEETING: t})
    for mid, calls in cix.tx.call_ons.items():
        meet = cix.meetings[mid]
        for d in calls:
            ids = [a["official_id"] for a in meet["attendance"]]
            assert d["official_id"] in ids
            sur = cix.officials[d["official_id"]]["surname"].casefold()
            same = [a for a in meet["attendance"] if (cix.officials.get(a["official_id"]) or {}).get("surname", a["raw_name"]
                    .split()[-1]).casefold() == sur]
            assert len(same) == 1
    got = {(d["name"], d["official_id"]) for d in cix.tx.call_ons[MEETING]}
    # not "holloman" (near spelling), not Chandler (listed absent in this meeting's minutes)
    assert got == {("Smith", "city-wanda-smith"), ("Brown", "city-jimmy-brown"), ("Lovato", "city-keri-lovato")}
    assert next(a["status"] for a in m["attendance"] if a["official_id"] == "city-tim-chandler") == "absent"
    for mid, calls in cix.tx.call_ons.items():   # no call-on ever links a member listed absent
        absent = {a["official_id"] for a in cix.meetings[mid]["attendance"] if a["status"] == "absent"}
        assert not {d["official_id"] for d in calls} & absent
    # the 2026-11-05 transcript: no minutes read yet, so nothing links
    assert all(not v for k, v in cix.tx.call_ons.items() if k != MEETING and not council.views.attendance_shown(cix.meetings[k]))


# ------------------------------------------------------------------------------------------------------ pages

@pytest.fixture(scope="module")
def city_dir(tmp_path_factory):
    from test_council_pages import subset
    facts = city_facts()
    sub = subset(facts, ("2019-01-03-regular", MEETING))
    d = tmp_path_factory.mktemp("city")
    (d / "facts.json").write_text(json.dumps(sub), encoding="utf-8")
    wards = [w for w in json.loads((CITY / "wards.json").read_text()) if w["meeting_id"] in ("2019-01-03-regular", MEETING)]
    (d / "wards.json").write_text(json.dumps(wards), encoding="utf-8")
    m = next(x for x in sub["meetings"] if x["id"] == MEETING)
    write_raw(d / "raw", raw_transcript(m, SEGMENTS))
    ctx.import_dir(d / "raw", sub, d / "transcripts", kind_of, LISTING)
    return d, sub


@pytest.fixture(scope="module")
def built(tmp_path_factory, city_dir):
    d, sub = city_dir
    cfg = {**CFG, "facts_path": d / "facts.json", "wards_path": d / "wards.json"}
    out = tmp_path_factory.mktemp("site") / "build" / "site"
    result = build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, councils=[cfg])
    return out, result, cfg, sub


def test_transcript_page_lines(built):
    out, result, cfg, sub = built
    assert result["transcripts"] and result["transcript_pages"] == 1
    page = (out / "city" / "transcripts" / f"{MEETING}.html").read_text(encoding="utf-8")
    assert tx.NOTICE in html.unescape(page)
    video = next(m for m in sub["meetings"] if m["id"] == MEETING)["video_url"]
    lines = re.findall(r'<li id="s(\d+)"[^>]*>(.*?)</li>', page, re.S)
    assert len(lines) == len(SEGMENTS)
    for i, body in lines:
        assert f'href="{video}#t={int(SEGMENTS[int(i)][0])}"' in body
        assert '<span class="chip chip-type">Transcript</span>' in body
    # hostile text is escaped, never markup
    assert "<script>alert" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert 'href="javascript' not in page
    # the call-on lines are marked with the member, linked
    assert re.search(r'<li id="s1" class="call-on">.*Called on: <a href="../../city/members/city-wanda-smith.html">Wanda Smith</a>', page)
    assert 'id="s7" class="call-on"' not in page        # "holloman": not matched


def test_member_pages_list_call_ons_verbatim_and_alike(built):
    out, result, cfg, sub = built
    smith = (out / "city" / "members" / "city-wanda-smith.html").read_text(encoding="utf-8")
    assert "Called on in meetings (transcript)" in smith
    assert "Transcript text after the chair called on Wanda Smith:" in smith
    video = next(m for m in sub["meetings"] if m["id"] == MEETING)["video_url"]
    assert f'href="{video}#t=4"' in smith
    assert "thank you mayor I have a question about the paving contract" in smith
    assert f"transcripts/{MEETING}.html#s1" in smith
    # the matched call-on words are shown verbatim with the entry
    assert ('Matched words: &ldquo;<span class="tx-matched" data-transcript>councilman Smith you&#39;re recognized'
            '</span>&rdquo;') in smith
    chandler = out / "city" / "members" / "city-tim-chandler.html"
    if chandler.is_file():
        assert "Chandler you" not in chandler.read_text(encoding="utf-8")      # listed absent: no call-on entry
    other = (out / "city" / "members" / "city-geno-grubbs.html")
    if other.is_file():
        text = other.read_text(encoding="utf-8")
        assert "Called on in meetings (transcript)" in text and "No call-ons found in the 1 meeting transcript" in text
    # the same headings on every member page (layout N1)
    problems, _ = site_checks.check_layout(out, json.loads(Path(cfg["facts_path"]).read_text()), "city/members")
    assert problems == []


def test_meeting_section_links_the_transcript(built):
    out, *_ = built
    year = (out / "city" / "meetings" / "2026.html").read_text(encoding="utf-8")
    assert f'href="../../city/transcripts/{MEETING}.html">Automatic transcript</a>' in year


def test_site_checks_pass_on_transcripts_and_catch_a_line_without_time(built, tmp_path):
    out, result, cfg, sub = built
    cs = [{"slug": "city", "prefix": "city/", "facts": sub}]
    problems, note = site_checks.check_transcripts(out, cs)
    assert problems == [] and f"{len(SEGMENTS)} lines" in note
    videos = {m["video_url"] for m in sub["meetings"] if m.get("video_url")}
    pages = {f.relative_to(out).as_posix(): site_checks.parse(f) for f in out.rglob("*.html")}
    probs, _ = site_checks.check_sources(out, pages, {"sources": [*json.loads(FIXTURE.read_text())["sources"],
                                                                  *sub["sources"]]}, (), set(), None, videos)
    assert [p for p in probs if "video" in p] == []
    copy = tmp_path / "site"
    shutil.copytree(out, copy)
    p = copy / "city" / "transcripts" / f"{MEETING}.html"
    p.write_text(re.sub(r'(<li id="s3">)<a class="tx-time"[^>]*>.*?</a>', r"\1", p.read_text(encoding="utf-8"),
                        flags=re.S), encoding="utf-8")
    problems, _ = site_checks.check_transcripts(copy, cs)
    assert any("#s3" in x for x in problems)
    # a video link to another host is caught by the sources check
    p2 = copy / "city" / "members" / "city-wanda-smith.html"
    p2.write_text(p2.read_text(encoding="utf-8").replace(next(iter(videos)), "https://evil.example/v.mp4"), encoding="utf-8")
    pages = {"city/members/city-wanda-smith.html": site_checks.parse(p2)}
    probs, _ = site_checks.check_sources(copy, pages, {"sources": []}, (), set(), None, videos)
    assert any("video link" in x for x in probs)
    problems, _ = site_checks.check_transcripts(copy, cs)
    assert any("call-on entry of" in x for x in problems)            # the entry no longer links its meeting's video


def test_transcript_text_regex_is_anchored():
    rx = site_checks.TRANSCRIPT_TEXT
    assert rx.search('<span class="x" data-transcript>words</span>')
    assert rx.search('<p data-transcript="1">words</p>')
    assert not rx.search('<span data-transcript-foo>words</span>')
    assert not rx.search('<span xdata-transcript>words</span>')


def test_pages_are_deterministic(built, tmp_path_factory):
    out, result, cfg, sub = built
    out2 = tmp_path_factory.mktemp("again") / "build" / "site"
    build(FIXTURE, out2, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, councils=[cfg])
    for rel in (f"city/transcripts/{MEETING}.html", "city/members/city-wanda-smith.html"):
        assert (out / rel).read_bytes() == (out2 / rel).read_bytes()


def test_preview_over_its_cap_leaves_transcript_pages_out(built, tmp_path_factory, monkeypatch):
    out, result, cfg, sub = built
    n = result["files"]
    from sitegen.build import export_file_count
    monkeypatch.setitem(config.MAX_FILES_BY_TARGET, "preview", n + export_file_count(True, [cfg], False) - 1)
    out2 = tmp_path_factory.mktemp("small") / "build" / "site"
    r2 = build(FIXTURE, out2, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, councils=[cfg])
    assert r2["transcripts"] is False and not (out2 / "city" / "transcripts").exists()
    year = (out2 / "city" / "meetings" / "2026.html").read_text(encoding="utf-8")
    assert "this preview copy leaves transcript pages out" in year
    smith = (out2 / "city" / "members" / "city-wanda-smith.html").read_text(encoding="utf-8")
    assert "#t=4" in smith and "line in the transcript" not in smith      # the video links stay
    # the pages target has room
    r3 = build(FIXTURE, tmp_path_factory.mktemp("pages") / "site", seats_path=FIXTURE_SEATS,
               districts_path=FIXTURE_DISTRICTS, councils=[cfg], target="pages")
    assert r3["transcripts"] is True


def test_file_caps_per_target():
    assert config.MAX_FILES_BY_TARGET == site_checks.MAX_FILES_BY_TARGET == {"preview": 500, "pages": 3000}
    assert config.max_files("pages") == 3000 and config.max_files("preview") == 500


def test_one_cap_rule_a_build_at_the_cap_is_ok(tmp_path, monkeypatch):
    """At most the cap (<= cap) is OK in sitegen's manifest and in qa/site_checks alike; one over fails both."""
    from sitegen.build import BuildError, write_publish_manifest
    site = tmp_path / "build" / "site"
    site.mkdir(parents=True)
    for i in range(3):
        (site / f"f{i}.txt").write_text("x")
    monkeypatch.setitem(config.MAX_FILES_BY_TARGET, "preview", 3)
    write_publish_manifest(site, "preview")                          # exactly at the cap: OK
    (site / "f3.txt").write_text("x")
    with pytest.raises(BuildError):
        write_publish_manifest(site, "preview")

