"""Name resolution invariant (docs/architecture/city-council.md, problem family city-votes, third hit
city-votes/surname-stale-book): one test per path N1-N8, each through assert_name_invariant, plus the reviewer's case
of a departed member's surname reused by a new member.

Invariant: a printed name resolves to a member only when exactly one member of that meeting's own roster matches it;
the roster is the meeting's attendance in full (through the aliases) plus its presiding mayor when the roster book has
that name as the Mayor seat, and a surname printed alone counts only against the roster book: full-name lists printed
since the latest seating, for members no later list in that window replaced, and the configured, cited mayor. Titled
prose in the minutes ("Councilman David Allen moved to Clarksville", "called to order by Mayor Wes Golden") is never
evidence. Anything else is held.
"""
import re

import jsonschema
import pytest
import yaml

from collector import agenda_center as ac
from collector.city_build import (Officials, RosterBook, break_free, build, name_parts, official_id, printed_full_names,
                                  resolve, resolve_with)
from collector.city_minutes import NAME_RE, parse_text
from collector.tests.test_city_minutes import SCHEMA, FakeStore, entry

API = "https://clarksvilletn.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId={},plainText=false)"
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


@pytest.fixture(scope="module")
def cfg():
    return ac.load_config(ac.config_path("clarksville-tn"))


def with_mayors(cfg, *mayors):
    """cfg with these configured mayors ({name, from, to, cite}) in place of the real ones (none: lists only)."""
    return ac.AgendaCenterConfig(**{**cfg.__dict__, "mayors": tuple(mayors)})


def minutes(date: str, present: str, absent: str = "", aye: str = "", mover: str = "Streetman",
            seconder: str = "Holleman", mayor: str = "Joe Pitts", extra: str = "") -> str:
    """A one-vote minutes text in the CivicClerk shape (test_civicclerk_minutes.py excerpts)."""
    y, m, d = date.split("-")
    words = f"{MONTHS[int(m) - 1]} {int(d)}, {y}"
    return (f"1.   Call to Order\n"
            f"      Regular Session of the Clarksville City Council was called to order by Mayor {mayor}\n"
            f"      on Thursday, {words}, at 6:00 p.m. {extra}\n\n"
            f"2.   Attendance\n"
            f"      PRESENT: {present}\n\n"
            + (f"      ABSENT: {absent}\n\n" if absent else "") +
            f"3.   Consent Agenda\n"
            f"          Councilman {mover} made a motion to adopt the Consent Agenda, seconded by Councilman\n"
            f"          {seconder}. The following vote was recorded:\n\n"
            f"             AYE: {aye}\n\n"
            f"             The motion to adopt the Consent Agenda passed.\n")


FULL = ("Brian Zacharias (Ward 1), Karen Reynolds (Ward 2), Stacey Streetman (Ward 3), Travis Holleman (Ward 4), "
        "Jimmy Brown (Ward 5)")
FULL_AYE = "Brown, Holleman, Pitts, Reynolds, Streetman, Zacharias"
CAPS = "BROWN, HOLLEMAN, PITTS, REYNOLDS, STREETMAN, ZACHARIAS"


def run(cfg, meetings: list[tuple[str, str]]):
    """Build facts from [(date, minutes text)], each a CivicClerk listing row with its own minutes file."""
    rows, entries, by_url = [], [], {}
    for n, (date, text) in enumerate(meetings, 1):
        url = API.format(n)
        rows.append({"date": date, "title": "City Council Regular Session", "kind": "regular",
                     "agenda_id": f"cc-{n}", "agenda_url": None, "minutes_url": url, "source": "civicclerk",
                     "video_url": None})
        entries.append(entry(url, "minutes", date, n))
        by_url[url] = text

    def parse(path, c):
        sha = str(path).rsplit("/", 1)[-1][:-4]
        return parse_text([by_url[next(e["url"] for e in entries if e["sha256"] == sha)]], c)
    facts, summary = build(cfg, rows, FakeStore(entries), parse=parse, inspect=lambda p: (3, "text"))
    jsonschema.validate({k: v for k, v in facts.items() if k != "_wards"}, SCHEMA)
    assert_name_invariant(cfg, facts, dict(meetings))
    return facts, summary


def assert_name_invariant(cfg, facts: dict, texts: dict) -> None:
    """Every resolved name of a meeting is on that meeting's roster (its attendance, or its presiding mayor when that
    resolved), matches exactly one member of it, and every surname read from earlier lists names lists dated inside
    the meeting's window (from the latest seating up to the meeting). A presiding mayor that did not resolve is not on
    the roster."""
    names = {o["id"]: o["name"] for o in facts["officials"]}
    off = Officials(cfg)
    for m in facts["meetings"]:
        pm = parse_text([texts[m["date"]]], cfg)
        roster = {a["official_id"] for a in m["attendance"] if a["official_id"]}
        presiding = next((c for c in m["verification"]["checks"] if c["check"] == "presiding_resolves"), None)
        if pm.presiding and pm.presiding_title == cfg.presiding_title:
            assert presiding is not None, m["id"]
            if presiding["ok"]:
                roster.add(official_id(off.canonical(pm.presiding)))
        pairs = [(oid, names[oid]) for oid in sorted(roster)]
        for a in m["attendance"]:
            if a["official_id"] and not NAME_RE.match(a["raw_name"]):          # read from a surname, or N9
                name = names[a["official_id"]]
                assert name.split()[-1].lower() == a["raw_name"].lower() or \
                    break_free(a["raw_name"]) in (break_free(name), break_free(name_parts(name)[1])), (m["id"], a)
        for c in m["verification"]["checks"]:
            if c["check"] == "surnames_resolve":
                for d in re.findall(r"by the attendance of (\d{4}-\d{2}-\d{2})", c.get("detail", "")):
                    assert cfg.seated_on(m["date"]) <= d <= m["date"], (m["id"], d)
        rcs = [r for r in facts["roll_calls"] if r["meeting_id"] == m["id"]]
        refs = [v for r in rcs for v in r["votes"]]
        for mo in (x for x in facts["motions"] if x["meeting_id"] == m["id"]):
            refs += [mo["moved_by"]] + ([mo["seconded_by"]] if mo["seconded_by"] else [])
        for v in refs:
            assert v["official_id"] is None or v["official_id"] in roster, (m["id"], v)
            assert v["official_id"] == resolve(v["raw_name"], pairs, cfg.aliases), (m["id"], v)
            oid, via_break = resolve_with(v["raw_name"], pairs, cfg.aliases)
            if via_break:                       # N9: every printed letter equals the member's name or surname
                name = names[oid]
                assert break_free(v["raw_name"]) in (break_free(name), break_free(name_parts(name)[1])), (m["id"], v)
        if not m["verification"]["status"] == "verified":
            assert all(r["verification"]["status"] == "unverified" for r in rcs)


def meeting(facts, date):
    return next(m for m in facts["meetings"] if m["date"] == date)


def att(facts, date):
    return {a["raw_name"]: a["official_id"] for a in meeting(facts, date)["attendance"]}


def surname_check(facts, date):
    return next(c for c in meeting(facts, date)["verification"]["checks"] if c["check"] == "surnames_resolve")


# ------------------------------------------------------------------ the reviewer's case
def test_a_departed_members_surname_reused_by_a_new_member_is_held(cfg):
    """Karen Reynolds (Ward 2) is printed in full in 2024 only; after the 2025 seating a new REYNOLDS is printed as a
    surname only. Before the fix the unbounded book read REYNOLDS as Karen Reynolds, with verified votes."""
    after = FULL.replace("Karen Reynolds (Ward 2), ", "")
    facts, _ = run(cfg, [("2024-10-03", minutes("2024-10-03", FULL, aye=FULL_AYE)),
                         ("2025-02-06", minutes("2025-02-06", after, aye="Brown, Holleman, Pitts, Streetman, Zacharias")),
                         ("2025-08-07", minutes("2025-08-07", CAPS, aye=CAPS))])
    assert att(facts, "2025-08-07")["REYNOLDS"] is None
    c = surname_check(facts, "2025-08-07")
    assert not c["ok"] and ("REYNOLDS (no roster entry; Karen Reynolds: last printed 2024-10-03, before the seating "
                            "of 2025-01-01)") in c["detail"]
    rcs = [r for r in facts["roll_calls"] if r["meeting_id"] == meeting(facts, "2025-08-07")["id"]]
    assert rcs and all(r["verification"]["status"] == "unverified" for r in rcs)
    assert not any(v["official_id"] == "city-karen-reynolds" for r in rcs for v in r["votes"])
    assert att(facts, "2025-08-07")["BROWN"] == "city-jimmy-brown"            # members still seated still resolve


def test_a_member_replaced_in_their_ward_inside_the_window_is_held(cfg):
    """Same seating period: Karen Reynolds holds Ward 2 on 2025-01-02, Ward 2 is printed for Eric Claunch on
    2025-04-03. A later REYNOLDS is not Karen Reynolds."""
    after = FULL.replace("Karen Reynolds (Ward 2)", "Eric Claunch (Ward 2)")
    caps = CAPS.replace("REYNOLDS", "REYNOLDS, CLAUNCH")
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", FULL, aye=FULL_AYE)),
                         ("2025-04-03", minutes("2025-04-03", after, aye=FULL_AYE.replace("Reynolds", "Claunch"))),
                         ("2025-08-07", minutes("2025-08-07", caps, aye=CAPS))])
    a = att(facts, "2025-08-07")
    assert a["REYNOLDS"] is None and a["CLAUNCH"] == "city-eric-claunch"
    assert "Karen Reynolds: Ward 2 printed for Eric Claunch on 2025-04-03" in surname_check(facts, "2025-08-07")["detail"]


def test_a_full_name_reused_for_the_same_ward_resolves_to_the_later_printing(cfg):
    """A seat change printed in full (the later list names someone new with the same surname) resolves to the
    member now printed for the seat, never the one before."""
    after = FULL.replace("Karen Reynolds (Ward 2)", "Joe Reynolds (Ward 2)")
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", FULL, aye=FULL_AYE)),
                         ("2025-04-03", minutes("2025-04-03", after, aye=FULL_AYE)),
                         ("2025-08-07", minutes("2025-08-07", CAPS, aye=CAPS))])
    assert att(facts, "2025-08-07")["REYNOLDS"] == "city-joe-reynolds"
    assert surname_check(facts, "2025-08-07")["ok"]


# ------------------------------------------------------------------ one test per path
def test_n1_attendance_in_full_is_the_member_and_a_non_name_is_none(cfg):
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", FULL + ", 7:15 pm", aye=FULL_AYE))])
    a = att(facts, "2025-01-02")
    assert a["Karen Reynolds"] == "city-karen-reynolds" and a["7:15 pm"] is None
    assert meeting(facts, "2025-01-02")["verification"]["status"] == "unverified"         # names_well_formed holds


def test_n2_an_alias_is_one_member_on_the_roster(cfg):
    text = minutes("2025-01-02", FULL + ", Amber Marquis (Ward 6)", aye=FULL_AYE + ", Marquis")
    facts, _ = run(cfg, [("2025-01-02", text)])
    assert att(facts, "2025-01-02")["Amber Marquis"] == "city-ambar-marquis"
    rc = next(r for r in facts["roll_calls"])
    assert {v["raw_name"]: v["official_id"] for v in rc["votes"]}["Marquis"] == "city-ambar-marquis"


def test_n3_the_presiding_mayor_votes_and_an_earlier_mayor_is_not_read_for_a_surname(cfg):
    """The presiding mayor is on the meeting's roster when the book has the name as the Mayor seat: here the
    configured, cited mayor (Joe Pitts, 2019-2026), on the first meeting after a seating with no list in the window
    yet. Without configured mayors, a list that prints the mayor puts the seat in the book, and a mayor printed
    earlier in the window whose seat a later list gives to another mayor is held for a later PITTS."""
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", FULL, aye=FULL_AYE))])
    rc = facts["roll_calls"][0]
    assert {v["raw_name"]: v["official_id"] for v in rc["votes"]}["Pitts"] == "city-joe-pitts"
    assert rc["verification"]["status"] == "verified"
    c = next(c for c in meeting(facts, "2025-01-02")["verification"]["checks"] if c["check"] == "presiding_resolves")
    assert c == {"check": "presiding_resolves", "ok": True,
                 "detail": "Joe Pitts by the configured mayor seat from 2019-01-01"}
    lists = with_mayors(cfg)
    facts, _ = run(lists, [("2025-01-02", minutes("2025-01-02", FULL + ", Joe Pitts (Mayor)", aye=FULL_AYE)),
                           ("2025-02-06", minutes("2025-02-06", FULL + ", Kim McMillan (Mayor)",
                                                  aye=FULL_AYE.replace("Pitts", "McMillan"), mayor="Kim McMillan")),
                           ("2025-08-07", minutes("2025-08-07", CAPS, aye=CAPS, mayor="Kim McMillan"))])
    rc = next(r for r in facts["roll_calls"] if r["meeting_id"] == meeting(facts, "2025-01-02")["id"])
    assert {v["raw_name"]: v["official_id"] for v in rc["votes"]}["Pitts"] == "city-joe-pitts"
    assert rc["verification"]["status"] == "verified"
    assert att(facts, "2025-08-07")["PITTS"] is None
    assert "Joe Pitts: Mayor printed for Kim McMillan on 2025-02-06" in surname_check(facts, "2025-08-07")["detail"]
    c = next(c for c in meeting(facts, "2025-08-07")["verification"]["checks"] if c["check"] == "presiding_resolves")
    assert c["ok"] and c["detail"] == "Kim McMillan by the attendance of 2025-02-06"


def test_n4_a_titled_name_in_the_minutes_never_adds_a_candidate(cfg):
    """city-votes/titled-nonmember: a titled full name in the text is no evidence, in an action of the meeting or not.
    Before, "Councilman Eric Claunch led the Pledge" made CLAUNCH resolve "by these minutes"; now only the roster
    book can, and neither surname has an entry there."""
    caps = CAPS.replace("REYNOLDS", "CLAUNCH, ALLEN")
    extra = "Councilman Eric Claunch led the Pledge. A plaque honored former Councilman David Allen."
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", FULL, aye=FULL_AYE)),
                         ("2025-08-07", minutes("2025-08-07", caps, aye=caps, extra=extra))])
    a = att(facts, "2025-08-07")
    assert a["CLAUNCH"] is None and a["ALLEN"] is None
    c = surname_check(facts, "2025-08-07")
    assert not c["ok"] and "these minutes" not in c["detail"]
    assert "CLAUNCH (no roster entry), ALLEN (no roster entry)" in c["detail"]
    assert not {"city-eric-claunch", "city-david-allen"} & {o["id"] for o in facts["officials"]}


def test_n5_the_book_keeps_a_cut_list_and_holds_what_is_outside_the_window(cfg):
    """2025-02-06 printed a list cut short (no Ward 2): Karen Reynolds from 2025-01-02 is still on the roster. A
    member printed without a ward and not on the latest list is held; so is a list from before the seating."""
    off = Officials(cfg)
    rb = RosterBook(cfg)
    rb.add(printed_full_names(cfg, off, parse_text([minutes("2024-12-05", "Wanda Allen (Ward 7)")], cfg),
                              "2024-12-05"))
    rb.add(printed_full_names(cfg, off, parse_text([minutes("2025-01-02", FULL + ", Ted Nobody")], cfg),
                              "2025-01-02"))
    rb.add(printed_full_names(cfg, off, parse_text([minutes("2025-02-06", FULL.replace(
        "Karen Reynolds (Ward 2), ", ""))], cfg), "2025-02-06"))
    book = rb.for_meeting("2025-08-07")
    assert book["reynolds"]["people"] == [{"name": "Karen Reynolds", "ward": 2, "mayor": False, "date": "2025-01-02"}]
    assert book["nobody"] == {"people": [], "held": ["Ted Nobody: printed without a ward on 2025-01-02, not on the "
                                                     "list of 2025-02-06"]}
    assert book["allen"]["people"] == [] and "before the seating of 2025-01-01" in book["allen"]["held"][0]
    assert rb.for_meeting("2024-12-31")["allen"]["people"][0]["name"] == "Wanda Allen"      # the earlier term
    assert all(p["date"] >= "2025-01-01" for e in book.values() for p in e["people"] if not p.get("configured"))
    # the configured, cited mayor is the one entry not read from a list (its date is its term's start)
    assert book["pitts"]["people"] == [{"name": "Joe Pitts", "ward": None, "mayor": True, "date": "2019-01-01",
                                        "configured": True}]
    no_rule = RosterBook(ac.AgendaCenterConfig(**{**cfg.__dict__, "seating": None}))
    no_rule.lists = rb.lists
    assert all(p.get("configured") for e in no_rule.for_meeting("2025-08-07").values()
               for p in e["people"])                                                       # no rule: nothing earlier


def test_n6_two_full_names_or_a_disagreeing_ward_hold_the_surname(cfg):
    two = FULL + ", Jim Brown (Ward 6)"
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", two, aye=FULL_AYE)),
                         ("2025-08-07", minutes("2025-08-07", CAPS, aye=CAPS))])
    assert att(facts, "2025-08-07")["BROWN"] is None
    assert "BROWN (2 full names)" in surname_check(facts, "2025-08-07")["detail"]
    wards = "Zacharias (Ward 1), Reynolds (Ward 2), Streetman (Ward 3), Holleman (Ward 4), Brown (Ward 9)"
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", FULL, aye=FULL_AYE)),
                         ("2025-03-06", minutes("2025-03-06", wards, aye=FULL_AYE))])
    assert att(facts, "2025-03-06")["Brown"] is None and att(facts, "2025-03-06")["Reynolds"] == "city-karen-reynolds"


def test_n7_a_vote_name_resolves_only_against_this_meetings_roster(cfg):
    """Karen Reynolds is an official from the first meeting; the second meeting's attendance does not list her, so
    its vote 'Reynolds' is not hers: held (names_resolve)."""
    after = FULL.replace("Karen Reynolds (Ward 2), ", "")
    facts, summary = run(cfg, [("2025-01-02", minutes("2025-01-02", FULL, aye=FULL_AYE)),
                               ("2025-02-06", minutes("2025-02-06", after, aye=FULL_AYE))])
    rc = next(r for r in facts["roll_calls"] if r["meeting_id"] == meeting(facts, "2025-02-06")["id"])
    assert {v["raw_name"]: v["official_id"] for v in rc["votes"]}["Reynolds"] is None
    assert any(c["check"] == "names_resolve" and not c["ok"] for c in rc["verification"]["checks"])
    assert rc["verification"]["status"] == "unverified"


def test_n8_a_mover_or_seconder_off_the_roster_is_not_resolved(cfg):
    after = FULL.replace("Karen Reynolds (Ward 2), ", "")
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", FULL, aye=FULL_AYE)),
                         ("2025-02-06", minutes("2025-02-06", after, aye=FULL_AYE.replace("Reynolds, ", ""),
                                                mover="Reynolds", seconder="Brown"))])
    mo = next(x for x in facts["motions"] if x["meeting_id"] == meeting(facts, "2025-02-06")["id"])
    assert mo["moved_by"]["official_id"] is None and mo["seconded_by"]["official_id"] == "city-jimmy-brown"
    assert mo["verification"]["status"] == "unverified"


def test_the_window_starts_at_the_latest_seating_and_a_bad_rule_is_refused(cfg):
    assert [cfg.seated_on(d) for d in ("2024-12-31", "2025-01-01", "2026-06-04", "2027-01-07", "2016-05-05")] == [
        "2023-01-01", "2025-01-01", "2025-01-01", "2027-01-01", "2015-01-01"]
    raw = yaml.safe_load(ac.config_path("clarksville-tn").read_text(encoding="utf-8"))
    for bad in ({"month": 13, "every_years": 2, "from_year": 2017}, {"month": 1, "every_years": 0, "from_year": 2017},
                {"month": 1, "every_years": 2}, "odd years"):
        with pytest.raises(ac.AgendaCenterConfigError):
            ac.parse_config({**raw, "seating": bad})


# ------------------------------------------------------------------ city-votes/titled-nonmember: prose is never evidence
BOOK_IDS = {official_id(n) for n in ("Brian Zacharias", "Karen Reynolds", "Stacey Streetman", "Travis Holleman",
                                     "Jimmy Brown", "Joe Pitts")}       # the 2025-01-02 list and the configured mayor


def held_after(cfg, extra: str, surnames: str = "ALLEN, CLAUNCH", mayor: str = "Joe Pitts"):
    """2025-01-02 prints the full-name list; 2025-08-07 prints `surnames` in place of REYNOLDS (none of them on any
    list) and `extra` in its call-to-order paragraph. Returns (facts, the 2025-08-07 surnames_resolve check)."""
    caps = CAPS.replace("REYNOLDS", surnames)
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", FULL, aye=FULL_AYE)),
                         ("2025-08-07", minutes("2025-08-07", caps, aye=caps, extra=extra, mayor=mayor))])
    return facts, surname_check(facts, "2025-08-07")


def assert_held(facts, check, *surnames):
    """Each surname is held with no roster entry, no official is made beyond the book's, and every roll call and
    motion of the meeting is held."""
    a = att(facts, "2025-08-07")
    for s in surnames:
        assert a[s] is None, s
        assert f"{s} (no roster entry)" in check["detail"], (s, check["detail"])
    assert not check["ok"] and "these minutes" not in check["detail"]
    assert {o["id"] for o in facts["officials"]} <= BOOK_IDS
    mid = meeting(facts, "2025-08-07")["id"]
    assert all(x["verification"]["status"] == "unverified"
               for x in facts["roll_calls"] + facts["motions"] if x["meeting_id"] == mid)


# The delta re-review's six prose forms (each matched ACTING_BEFORE_RE / ACTING_AFTER_RE and resolved the surname)
@pytest.mark.parametrize("extra, surname", [
    ("WHEREAS, Councilman David Allen moved to Clarksville in 1985 and served on many boards;", "ALLEN"),
    ("Councilman David Allen presided over the Finance Committee for many years.", "ALLEN"),
    ("A presentation was made by Councilman David Allen on the history of the Council.", "ALLEN"),
    ("The Council adopted a resolution honoring Councilman David Allen, seconded by the Council as a whole.", "ALLEN"),
    ("the Pledge was led by Councilman David Allen, who served Ward 2 until 2021.", "ALLEN"),
    ("the Pledge was led by Mayor Wes Golden of Montgomery County.", "GOLDEN"),
])
def test_n4_the_reviewers_prose_never_resolves_a_surname(cfg, extra, surname):
    facts, check = held_after(cfg, extra, surnames=surname)
    assert_held(facts, check, surname)


@pytest.mark.parametrize("extra", [
    # a qualifier before the title, or another body's title (the fresh review's not-sitting forms)
    "The Council honored former City Councilman David Allen.",
    "A plaque for then-Councilman David Allen was shown.",
    "Former Ward 7 Councilwoman David Allen was recognized.",
    "the late Mayor David Allen was remembered.",
    "outgoing Councilman David Allen received a key.",
    "County Mayor David Allen and Mayor Pitts proclaimed the day.",
    "with Montgomery Council Mayor David Allen, we agreed.",
    "Montgomery County Mayor David Allen was present.",
    "Vice Mayor David Allen of the sister city attended.",
    "The Council adopted a resolution honoring Councilman David Allen.",
    # an action of the meeting (these corroborated a titled name before; now nothing does)
    "A prayer was offered by Councilman Eric Claunch; the Pledge",
    "the Pledge of Allegiance was led by Councilman Eric Claunch.",
    "the Pledge of Allegiance as led by Councilman Eric Claunch (Ward 2).",
    "Councilman Eric Claunch made a motion to adopt the agenda.",
    "Councilman Eric Claunch (Ward 2) made a motion to adopt the agenda.",
    "Councilman Eric Claunch moved to adopt the agenda.",
    "seconded by Councilman Eric Claunch.",
    "Councilman Eric Claunch seconded the motion.",
    "Councilman Eric Claunch called the meeting to order at 4:00 PM.",
    "Councilman Eric Claunch offered a prayer and led the Pledge.",
    "the Pledge was led by former Councilman Eric Claunch.",
    # words a titled pair can pick up that are no name
    "Valerie Guzman, Mayor Pro Tem (Ward 5) was present.",
    "Councilperson Allen Seconded the motion.",
    "Councilperson Smith With no objection, this item was moved.",
    "Councilperson Holleman Finance: Approval",
    "Mayor and Council Member Comments Stacey Streetman invited everyone.",
])
def test_n4_a_titled_name_never_adds_a_candidate(cfg, extra):
    """Every form the titled-name scan once read (not-sitting, action, junk): ALLEN and CLAUNCH, on no list, stay held,
    and no official is made from the text."""
    facts, check = held_after(cfg, extra)
    assert_held(facts, check, "ALLEN", "CLAUNCH")


def test_n4_reviewers_repro_former_city_councilman_does_not_verify_allen(cfg):
    """The review's repro: 2025-01-02 prints the full-name list; 2025-08-07 prints ALLEN in place of REYNOLDS and
    'honored former City Councilman David Allen'. Before the fix ALLEN resolved to city-david-allen and the roll call
    was verified."""
    facts, check = held_after(cfg, "A plaque honored former City Councilman David Allen.", surnames="ALLEN")
    assert_held(facts, check, "ALLEN")
    rcs = [r for r in facts["roll_calls"] if r["meeting_id"] == meeting(facts, "2025-08-07")["id"]]
    assert rcs and not any(v["official_id"] == "city-david-allen" for r in rcs for v in r["votes"])


def test_n4_a_member_on_the_book_resolves_whatever_the_text_says(cfg):
    """REYNOLDS resolves from the book (2025-01-02), not from the plaque sentence; CLAUNCH seconded the motion at this
    meeting, which is no roster entry, so it stays held (before, the second corroborated it)."""
    caps = CAPS.replace("REYNOLDS", "REYNOLDS, CLAUNCH")
    text = minutes("2025-08-07", caps, aye=caps, seconder="Eric Claunch",
                   extra="A plaque honored Councilwoman Karen Reynolds.")
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", FULL, aye=FULL_AYE)), ("2025-08-07", text)])
    a = att(facts, "2025-08-07")
    assert a["REYNOLDS"] == "city-karen-reynolds" and a["CLAUNCH"] is None
    c = surname_check(facts, "2025-08-07")
    assert not c["ok"] and "CLAUNCH (no roster entry)" in c["detail"] and "by the attendance of 2025-01-02" in c["detail"]
    assert "city-eric-claunch" not in {o["id"] for o in facts["officials"]}


# ------------------------------------------------------------------ city-votes/presiding-guest
def test_n3_a_presiding_mayor_not_on_the_book_is_held_and_made_no_official(cfg):
    """A joint session 'called to order by Mayor Wes Golden' (the County Mayor), with GOLDEN on the attendance and in
    the votes: no Golden on any list and no configured mayor of that name, so no official is made, no GOLDEN vote
    resolves, and the meeting is held (presiding_resolves). The next meeting's configured mayor still resolves."""
    caps = CAPS + ", GOLDEN"
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", FULL, aye=FULL_AYE)),
                         ("2025-08-07", minutes("2025-08-07", caps, aye=caps, mayor="Wes Golden of Montgomery County")),
                         ("2025-09-04", minutes("2025-09-04", CAPS, aye=CAPS))])
    m = meeting(facts, "2025-08-07")
    assert att(facts, "2025-08-07")["GOLDEN"] is None
    assert "city-wes-golden" not in {o["id"] for o in facts["officials"]}
    c = next(c for c in m["verification"]["checks"] if c["check"] == "presiding_resolves")
    assert not c["ok"] and c["detail"].startswith("Wes Golden: no roster entry for the Mayor seat")
    assert m["verification"]["status"] == "unverified"
    rcs = [r for r in facts["roll_calls"] if r["meeting_id"] == m["id"]]
    assert rcs and all(r["verification"]["status"] == "unverified" for r in rcs)
    assert all(v["official_id"] is None for r in rcs for v in r["votes"] if v["raw_name"] == "GOLDEN")
    assert att(facts, "2025-09-04")["PITTS"] == "city-joe-pitts"
    assert meeting(facts, "2025-09-04")["verification"]["status"] == "verified"


def test_n3_a_presiding_guest_at_a_full_name_meeting_is_held_and_never_enters_the_book(cfg):
    """The full-name shape: 'called to order by Mayor Wes Golden' with a 'Golden' vote. Before, the sentence made
    city-wes-golden (title Mayor), resolved the vote, and put Golden in the book for the next surname list."""
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", FULL, aye=FULL_AYE + ", Golden",
                                                mayor="Wes Golden")),
                         ("2025-08-07", minutes("2025-08-07", CAPS + ", GOLDEN", aye=CAPS))])
    assert "city-wes-golden" not in {o["id"] for o in facts["officials"]}
    rc = facts["roll_calls"][0]
    votes = {v["raw_name"]: v["official_id"] for v in rc["votes"]}
    assert votes["Golden"] is None and votes["Pitts"] is None              # Joe Pitts did not preside here
    assert rc["verification"]["status"] == "unverified"
    assert att(facts, "2025-08-07")["GOLDEN"] is None
    assert "GOLDEN (no roster entry)" in surname_check(facts, "2025-08-07")["detail"]


def test_n3_a_configured_mayor_counts_only_inside_its_term(cfg):
    """Joe Pitts's configured term ends 2026-12-31: a meeting of 2027 'called to order by Mayor Joe Pitts' has no
    configured mayor and no list in its window, so the presiding mayor is held (the 2027 empty book)."""
    facts, _ = run(cfg, [("2027-01-07", minutes("2027-01-07", FULL, aye=FULL_AYE))])
    c = next(c for c in meeting(facts, "2027-01-07")["verification"]["checks"] if c["check"] == "presiding_resolves")
    assert not c["ok"] and "city-joe-pitts" not in {o["id"] for o in facts["officials"]}
    assert [cfg.mayors_on(d)[0]["name"] for d in ("2016-01-07", "2018-12-31", "2019-01-01", "2026-12-31")] == [
        "Kim McMillan", "Kim McMillan", "Joe Pitts", "Joe Pitts"]
    assert cfg.mayors_on("2027-01-01") == [] and all(m["cite"] for m in cfg.mayors)


@pytest.mark.parametrize("bad", [
    [{"name": "Pitts", "from": "2019-01-01", "to": "2026-12-31", "cite": "x"}],              # not a full name
    [{"name": "Joe Pitts", "from": "2019-01-01", "to": "2026-12-31", "cite": " "}],          # no citation
    [{"name": "Joe Pitts", "from": "2019-01-01", "to": "2026-12-31"}],                       # no citation key
    [{"name": "Joe Pitts", "from": "2027-01-01", "to": "2026-12-31", "cite": "x"}],          # from after to
    [{"name": "Joe Pitts", "from": "January 2019", "to": "2026-12-31", "cite": "x"}],        # not a date
    [{"name": "Joe Pitts", "from": "2019-01-01", "to": "2026-12-31", "cite": "x"},
     {"name": "Wes Golden", "from": "2026-06-01", "to": "2030-12-31", "cite": "x"}],         # two mayors on one date
    {"Joe Pitts": "2019"},
])
def test_n3_a_bad_mayors_entry_is_refused(bad):
    raw = yaml.safe_load(ac.config_path("clarksville-tn").read_text(encoding="utf-8"))
    with pytest.raises(ac.AgendaCenterConfigError):
        ac.parse_config({**raw, "mayors": bad})


def test_n5_a_member_printed_without_a_ward_on_the_latest_list_is_kept(cfg):
    """`d == last` in RosterBook.for_meeting: a ward-less entry has no seat, so only being on the latest list keeps
    it. Without that clause Ted Nobody would be held and NOBODY would not resolve."""
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", FULL + ", Ted Nobody", aye=FULL_AYE + ", Nobody")),
                         ("2025-08-07", minutes("2025-08-07", CAPS + ", NOBODY", aye=CAPS + ", NOBODY"))])
    assert att(facts, "2025-08-07")["NOBODY"] == "city-ted-nobody"
    assert surname_check(facts, "2025-08-07")["ok"]
    rb = RosterBook(cfg)
    rb.add(printed_full_names(cfg, Officials(cfg), parse_text([minutes("2025-01-02", FULL + ", Ted Nobody")], cfg),
                              "2025-01-02"))
    assert rb.for_meeting("2025-08-07")["nobody"] == {
        "people": [{"name": "Ted Nobody", "ward": None, "mayor": False, "date": "2025-01-02"}], "held": []}


# ------------------------------------------------------------------ city-votes/alias-in-votes
def test_n2_n7_n8_a_vote_mover_or_seconder_printed_as_an_alias_resolves(cfg):
    """Path N2 is applied in N7 and N8: a vote, mover or seconder printed 'Amber Marquis' is read through the alias
    list as Ambar Marquis, the member on this meeting's roster. (The motion parser reads a mover or seconder as one
    word after the title, so a full-name mover reaches resolve() only through the same call checked below.)"""
    text = minutes("2025-01-02", FULL + ", Ambar Marquis (Ward 6)", aye=FULL_AYE + ", Amber Marquis")
    facts, _ = run(cfg, [("2025-01-02", text)])
    rc = facts["roll_calls"][0]
    assert {v["raw_name"]: v["official_id"] for v in rc["votes"]}["Amber Marquis"] == "city-ambar-marquis"
    assert rc["verification"]["status"] == "verified"
    roster = [("city-ambar-marquis", "Ambar Marquis")]
    assert resolve("Amber Marquis", roster, cfg.aliases) == "city-ambar-marquis"
    assert resolve("Amber Marquis", roster) is None
    raw = yaml.safe_load(ac.config_path("clarksville-tn").read_text(encoding="utf-8"))
    for bad in ({"Marquis": "Ambar Marquis"}, {"Amber Marquis": "Marquis"}, {"Amber Marquis": None}):
        with pytest.raises(ac.AgendaCenterConfigError):          # a surname alias would re-point every such vote
            ac.parse_config({**raw, "aliases": bad})


# ------------------------------------------------------------------ city-verify W1: format characters in the text layer
def _w(x0, x1, text, y0=696.556641, y1=709.845703, page=1):
    from collector.pdfwords import Word
    return Word(page, x0, x1, y0, y1, text)


# 2020-10-01 page 1 as its text layer has it (pdftotext -bbox and -layout, AgendaCenter Minutes/_10012020-608)
HENLEY_LINE = "    Holleman (Ward 7), David Allen, Mayor Pro Tem (Ward 8)​, J​ eff Henley (Ward 9),"
HENLEY_WORDS = [_w(413.990234, 425.990234, "8)​,"), _w(427.740233, 432.410154, "J"),
                _w(427.740233, 427.740233, "​", 695.822877, 717.300070),
                _w(432.410154, 445.728514, "eff"), _w(450.978518, 485.630861, "Henley"),
                _w(490.880858, 521.525389, "(Ward"), _w(526.775392, 539.771486, "9),")]


def _henley_minutes(page1: str) -> str:
    present = "Travis " + page1.strip().rstrip(",")
    return minutes("2020-10-01", present, aye="Allen, Henley, Holleman", mover="Holleman", seconder="Allen")


def test_w1_the_real_2020_10_01_boxes_read_jeff_henley_and_resolve(cfg):
    from collector.city_minutes import join_format_breaks
    page = join_format_breaks([HENLEY_LINE], HENLEY_WORDS)[0]
    assert "Jeff Henley (Ward 9)" in page and "J eff" not in page
    facts, _ = run(cfg, [("2020-10-01", _henley_minutes(page))])
    assert att(facts, "2020-10-01")["Jeff Henley"] == "city-jeff-henley"                       # N1
    assert meeting(facts, "2020-10-01")["verification"]["status"] == "verified"
    rc = facts["roll_calls"][0]
    assert {v["raw_name"]: v["official_id"] for v in rc["votes"]}["Henley"] == "city-jeff-henley"


def test_w1_a_visible_gap_after_the_zero_width_word_stays_a_gap_and_is_held(cfg):
    from collector.city_minutes import join_format_breaks
    gap = [w if w.text != "eff" else _w(435.410154, 448.728514, "eff") for w in HENLEY_WORDS]      # a 3 pt gap
    page = join_format_breaks([HENLEY_LINE], gap)[0]
    assert page == HENLEY_LINE                                         # unchanged; lines_of deletes the U+200B only
    facts, _ = run(cfg, [("2020-10-01", _henley_minutes(page))])        # no Jeff Henley on the book: W2 cannot match
    assert att(facts, "2020-10-01")["J eff Henley"] is None
    assert meeting(facts, "2020-10-01")["verification"]["status"] == "unverified"
    assert all(r["verification"]["status"] == "unverified" for r in facts["roll_calls"])


def test_w1_a_pair_also_seen_with_a_gap_on_the_page_is_never_joined():
    from collector.city_minutes import format_breaks
    words = HENLEY_WORDS + [_w(100, 105, "J", 720, 733), _w(100, 100, "​", 720, 733), _w(108, 120, "eff", 720, 733)]
    assert format_breaks(HENLEY_WORDS) == {1: {("J", "eff")}}
    assert format_breaks(words) == {}
    other_line = HENLEY_WORDS[:3] + [_w(432.410154, 445.728514, "eff", 720, 733)]
    assert format_breaks(other_line) == {}                                    # not one line


def test_w1_format_characters_inside_a_word_are_removed():
    from collector.city_minutes import lines_of, page_has
    assert lines_of(["PRESENT: Travis Holle­man (Ward 7), Da‍vid Allen﻿"])[0].text == \
        "PRESENT: Travis Holleman (Ward 7), David Allen"
    assert page_has("City Council -​ Special\n  Session", "City Council - Special Session")


# ------------------------------------------------------------------ city-verify W2: the break-free key (path N9)
WIDE = FULL + ", Jerry Haywood (Ward 6), Richard Lovato (Ward 7)"
WIDE_AYE = FULL_AYE + ", Haywood, Lovato"


def votes_of(facts, date, k=0):
    rcs = [r for r in facts["roll_calls"] if r["meeting_id"] == meeting(facts, date)["id"]]
    return rcs[k], {v["raw_name"]: v["official_id"] for v in rcs[k]["votes"]}


def check(r, name):
    return next(c for c in r["verification"]["checks"] if c["check"] == name)


def test_n9_an_attendance_name_printed_without_its_space_resolves_against_the_book(cfg):
    """2022-04-07 page 1 prints "StaceyStreetman (Ward 10)" (one glyph box, no space); the book has Stacey Streetman,
    Ward 10, from the list of 2022-03-03."""
    before = "Stacey Streetman (Ward 10), Travis Holleman (Ward 7), Jimmy Brown (Ward 5)"
    after = "StaceyStreetman (Ward 10), Travis Holleman (Ward 7), Jimmy Brown (Ward 5)"
    aye = "Brown, Holleman, Pitts, Streetman"
    facts, summary = run(cfg, [("2022-03-03", minutes("2022-03-03", before, aye=aye)),
                               ("2022-04-07", minutes("2022-04-07", after, aye=aye))])
    assert att(facts, "2022-04-07")["StaceyStreetman"] == "city-stacey-streetman"
    c = surname_check(facts, "2022-04-07")
    assert c["ok"] and "StaceyStreetman read as StaceyStreetman (Stacey Streetman), word break ignored" in c["detail"]
    rc, votes = votes_of(facts, "2022-04-07")
    assert votes["Streetman"] == "city-stacey-streetman" and rc["verification"]["status"] == "verified"
    assert summary["word_break_matches"] == [{"meeting": "2022-04-07-regular", "page": 1, "where": "attendance",
                                              "printed": "StaceyStreetman", "official_id": "city-stacey-streetman",
                                              "name": "Stacey Streetman"}]


def test_n9_a_printed_ward_that_disagrees_holds_the_attendance_name(cfg):
    before = "Stacey Streetman (Ward 10), Travis Holleman (Ward 7)"
    facts, summary = run(cfg, [("2022-03-03", minutes("2022-03-03", before, aye="Holleman, Streetman")),
                               ("2022-04-07", minutes("2022-04-07", before.replace("Stacey Streetman (Ward 10)",
                                                                                   "StaceyStreetman (Ward 9)"),
                                                      aye="Holleman, Streetman"))])
    assert att(facts, "2022-04-07")["StaceyStreetman"] is None
    assert not surname_check(facts, "2022-04-07")["ok"] and summary["word_break_matches"] == []
    assert meeting(facts, "2022-04-07")["verification"]["status"] == "unverified"


@pytest.mark.parametrize("token,member", [("H AYWOOD", "city-jerry-haywood"), ("H olleman", "city-travis-holleman"),
                                          ("LOV ATO", "city-richard-lovato"), ("Jerry Hay wood", "city-jerry-haywood")])
def test_n9_a_vote_name_with_a_printed_break_resolves_against_the_meetings_roster(cfg, token, member):
    surname = {"city-jerry-haywood": "Haywood", "city-travis-holleman": "Holleman", "city-richard-lovato": "Lovato"}
    aye = ", ".join(x if x != surname[member] else token for x in WIDE_AYE.split(", "))
    facts, summary = run(cfg, [("2025-01-02", minutes("2025-01-02", WIDE, aye=aye))])
    rc, votes = votes_of(facts, "2025-01-02")
    assert votes[token] == member and rc["verification"]["status"] == "verified"
    assert "word break ignored" in check(rc, "names_resolve")["detail"]
    assert [(u["where"], u["printed"], u["official_id"]) for u in summary["word_break_matches"]] == \
        [("vote", token, member)]


@pytest.mark.parametrize("token", ["STRETMAN", "AYWOOD", "HOLLEMNA", "PITT", "R reynolds", "Burkhart Erb",
                                   "Alexander. Allen", "H"])
def test_n9_never_a_near_spelling_a_split_or_a_lone_letter(cfg, token):
    facts, summary = run(cfg, [("2025-01-02", minutes("2025-01-02", WIDE, aye=WIDE_AYE + ", " + token))])
    rc, votes = votes_of(facts, "2025-01-02")
    assert votes[token] is None and rc["verification"]["status"] == "unverified"
    assert not check(rc, "names_resolve")["ok"] and summary["word_break_matches"] == []


def test_n9_two_roster_people_whose_keys_collide_hold_the_token(cfg):
    present = FULL + ", Mary Ann Lee (Ward 8), Maryann Lee (Ward 9)"
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", present, aye=FULL_AYE + ", MaryAnnLee, Mary Ann Lee"))])
    rc, votes = votes_of(facts, "2025-01-02")
    assert votes["MaryAnnLee"] is None and votes["Mary Ann Lee"] == "city-mary-ann-lee"
    assert rc["verification"]["status"] == "unverified"


def test_n9_a_key_matching_only_someone_off_the_meetings_roster_is_held(cfg):
    """Jerry Haywood is on the earlier list (so on the book), not on this meeting's attendance: H AYWOOD is held."""
    facts, summary = run(cfg, [("2025-01-02", minutes("2025-01-02", WIDE, aye=WIDE_AYE)),
                               ("2025-02-06", minutes("2025-02-06", FULL, aye=FULL_AYE + ", H AYWOOD"))])
    rc, votes = votes_of(facts, "2025-02-06")
    assert votes["H AYWOOD"] is None and rc["verification"]["status"] == "unverified"
    assert summary["word_break_matches"] == []


def test_n9_a_join_that_gives_a_member_a_second_vote_holds_the_roll_call(cfg):
    facts, summary = run(cfg, [("2025-01-02", minutes("2025-01-02", WIDE, aye=WIDE_AYE + ", H olleman"))])
    rc, votes = votes_of(facts, "2025-01-02")
    assert votes["H olleman"] == "city-travis-holleman"
    assert not check(rc, "one_entry_per_official")["ok"] and rc["verification"]["status"] == "unverified"


def test_n9_mover_and_seconder_tokens_use_the_same_last_step():
    """N8 reads the mover and seconder through resolve_with, as N7 (the parser reads them as one titled word, so a
    printed break cannot reach them today; the step is the same if it ever does)."""
    roster = [("city-stacey-streetman", "Stacey Streetman"), ("city-travis-holleman", "Travis Holleman")]
    assert resolve_with("Stree tman", roster) == ("city-stacey-streetman", True)
    assert resolve_with("Streetman", roster) == ("city-stacey-streetman", False)
    assert resolve_with("Stretman", roster) == (None, False)


def test_n9_an_attendance_entry_with_a_break_inside_a_name_resolves_against_the_book(cfg):
    """An entry neither a full name nor one surname ("J eff Henley", if W1 could not join it) is read against the
    book by its break-free key, the ward agreeing."""
    first = "Jeff Henley (Ward 9), Travis Holleman (Ward 7)"
    facts, summary = run(cfg, [("2020-09-03", minutes("2020-09-03", first, aye="Henley, Holleman")),
                               ("2020-10-01", minutes("2020-10-01", first.replace("Jeff", "J eff"),
                                                      aye="Henley, Holleman"))])
    assert att(facts, "2020-10-01")["J eff Henley"] == "city-jeff-henley"
    assert meeting(facts, "2020-10-01")["verification"]["status"] == "verified"
    assert [u["printed"] for u in summary["word_break_matches"]] == ["J eff Henley"]


# ------------------------------------------------------------------ city-verify M1: configured, cited members (N10)
CITE = API.format(3068)
# page 3 of the 2026-02-11 City Council Special Session minutes (resumed 2026-02-19), CivicClerk fileId 3068, as the
# city reader reads it (sha256 df53b5ec7368...)
CLAUNCH_P3 = ("           i.      Oath of Office\n                Because the vote was recessed to February 19, there "
              "was no Oath of Office.\n6.   Public Comment\n     (allows 3 persons; 5 minutes each)\n      There was no "
              "public comment.\n7.   Recess: The meeting was recessed to February 19, 2026 at 4:30 pm.\n      The "
              "meeting was recessed to February 19, 2026 at 4:30 pm.\n\n8.   Special Session Resumed on February 19, "
              "2026 at 4:30 pm. All councilmembers\n     were present.\n\n\n9.   Unfinished Business\n\n\n     A.   "
              "City Council Vacancy\n\n                 • Review of Procedure: City Attorney\n                 • Vote "
              "and Appointment of Ward 2 City Councilman\n                 • Oath of Office\n\n                City "
              "Attorney, Eric Bittner, reviewed the procedure with the Council. The\n                following votes "
              "were then taken: Round 33. Eric Claunch was selected as the\n                Ward 2 replacement and was "
              "sworn in by Mayor Pitts.\n\n\n10. Adjournment\n      The meeting was adjourned at 4:39 pm\n")
# page 1: the applicants (never a record of a seating)
APPLICANTS_P1 = ("     B.   Vote and Appointment of Ward 2 City Council Member\n          Applicants:\n\n             "
                 "1. Eric Claunch\n             2. AC Lopez\n             3. Jeff Loyd\n")
CLAUNCH = {"name": "Eric Claunch", "ward": 2, "seated": "2026-02-19", "kind": "minutes", "cite_url": CITE,
           "cite_page": 3, "quote": "Eric Claunch was selected as the Ward 2 replacement and was sworn in by Mayor Pitts."}
SEATED = ("Brian Zacharias (Ward 1), Deanna McLaughlin (Ward 2), Stacey Streetman (Ward 3), Travis Holleman (Ward 4), "
          "Jimmy Brown (Ward 5)")
SEATED_AYE = "Brown, Holleman, McLaughlin, Pitts, Streetman, Zacharias"
AFTER = "BROWN, CLAUNCH, HOLLEMAN, PITTS, STREETMAN, ZACHARIAS"


def with_members(cfg, *members):
    return ac.AgendaCenterConfig(**{**cfg.__dict__, "members": ac._members(list(members))})


def run_cited(cfg, meetings, cite_pages=(APPLICANTS_P1, "page 2", CLAUNCH_P3), cite_meeting="2026-02-11",
              stored=True):
    """run() with the cited file (fileId 3068) in the store, read as `cite_pages`."""
    rows, entries, by_url = [], [], {}
    for n, (date, text) in enumerate(meetings, 1):
        url = API.format(n)
        rows.append({"date": date, "title": "City Council Regular Session", "kind": "regular",
                     "agenda_id": f"cc-{n}", "agenda_url": None, "minutes_url": url, "source": "civicclerk",
                     "video_url": None})
        entries.append(entry(url, "minutes", date, n))
        by_url[url] = text
    if stored:
        entries.append(entry(CITE, "minutes", cite_meeting, 99))

    def parse(path, c):
        sha = str(path).rsplit("/", 1)[-1][:-4]
        return parse_text([by_url[next(e["url"] for e in entries if e["sha256"] == sha)]], c)

    def pages(path):
        assert path.stem == entry(CITE, "minutes", cite_meeting, 99)["sha256"]
        return list(cite_pages)
    facts, summary = build(cfg, rows, FakeStore(entries), parse=parse, inspect=lambda p: (3, "text"), pages=pages)
    jsonschema.validate({k: v for k, v in facts.items() if k != "_wards"}, SCHEMA)
    assert_name_invariant(cfg, facts, dict(meetings))
    return facts, summary


CLAUNCH_MEETINGS = [("2025-01-02", minutes("2025-01-02", SEATED, aye=SEATED_AYE)),
                    ("2026-02-05", minutes("2026-02-05", AFTER.replace("CLAUNCH", "MCLAUGHLIN"),
                                           aye=AFTER.replace("CLAUNCH", "MCLAUGHLIN"))),
                    ("2026-03-05", minutes("2026-03-05", AFTER, aye=AFTER))]


def test_n10_the_cited_minutes_resolve_claunch_from_the_seating_on(cfg):
    c = with_members(cfg, CLAUNCH)
    facts, summary = run_cited(c, CLAUNCH_MEETINGS)
    assert att(facts, "2026-03-05")["CLAUNCH"] == "city-eric-claunch"
    sc = surname_check(facts, "2026-03-05")
    assert sc["ok"] and ("CLAUNCH: by the configured member Eric Claunch (seated 2026-02-19, minutes p. 3)"
                         in sc["detail"])
    rc, votes = votes_of(facts, "2026-03-05")
    assert votes["CLAUNCH"] == "city-eric-claunch" and rc["verification"]["status"] == "verified"
    assert att(facts, "2026-02-05")["MCLAUGHLIN"] == "city-deanna-mclaughlin"         # before the seating: as before
    off = next(o for o in facts["officials"] if o["id"] == "city-eric-claunch")
    src = next(s for s in facts["sources"] if s["url"] == CITE)
    assert off["name_source"] == {"source_id": src["id"], "page": 3, "quote": CLAUNCH["quote"]}
    assert [w for w in facts["_wards"] if w.get("configured")] == [{
        "official_id": "city-eric-claunch", "raw_name": "Eric Claunch", "ward": 2, "pro_tem": False,
        "meeting_id": None, "date": "2026-02-19", "source_id": src["id"], "page": 3, "configured": True}]
    assert summary["members"] == [{"check": "member_cited", "ok": True, "name": "Eric Claunch", "ward": 2,
                                   "seated": "2026-02-19", "cite_url": CITE, "cite_page": 3,
                                   "detail": "quote found on page 3"}]


def test_n10_the_entry_replaces_the_wards_earlier_holder_from_the_seating(cfg):
    later = minutes("2026-03-05", AFTER + ", MCLAUGHLIN", aye=AFTER)
    facts, _ = run_cited(with_members(cfg, CLAUNCH), CLAUNCH_MEETINGS[:2] + [("2026-03-05", later)])
    assert att(facts, "2026-03-05")["MCLAUGHLIN"] is None
    assert ("Deanna McLaughlin: Ward 2 given to Eric Claunch by the configured member Eric Claunch (seated "
            "2026-02-19, minutes p. 3)") in surname_check(facts, "2026-03-05")["detail"]


def test_n10_no_meeting_before_the_seated_date_resolves_the_member(cfg):
    early = minutes("2026-02-11", AFTER, aye=AFTER)                    # the day of the applicants, before the seating
    facts, _ = run_cited(with_members(cfg, CLAUNCH), CLAUNCH_MEETINGS[:2] + [("2026-02-11", early)])
    assert att(facts, "2026-02-11")["CLAUNCH"] is None
    assert "CLAUNCH (no roster entry)" in surname_check(facts, "2026-02-11")["detail"]


def test_n10_the_applicants_page_alone_resolves_nothing(cfg):
    """Without the members entry, the applicant list (2026-02-05, 2026-02-11 p.1) is never evidence."""
    facts, summary = run_cited(cfg.__class__(**{**cfg.__dict__, "members": ()}), CLAUNCH_MEETINGS,
                               cite_pages=(APPLICANTS_P1,))
    assert att(facts, "2026-03-05")["CLAUNCH"] is None and summary["members"] == []
    rc, votes = votes_of(facts, "2026-03-05")
    assert votes["CLAUNCH"] is None and rc["verification"]["status"] == "unverified"


@pytest.mark.parametrize("change,kw,reason", [
    ({"quote": "Eric Claunch was sworn in as the Ward 2 member."}, {}, "the quote is not on page 3 of the cited file"),
    ({"cite_page": 1}, {}, "the quote is not on page 1 of the cited file"),
    ({}, {"stored": False}, "the cited file is not stored"),
    ({"seated": "2026-02-10"}, {}, "seated 2026-02-10 is before the cited record's meeting of 2026-02-11"),
    ({"name": "Eric Clanch"}, {}, "the quote does not name the person"),
    ({}, {"cite_pages": (APPLICANTS_P1,)}, "the quote is not on page 3 of the cited file"),
])
def test_n10_an_entry_whose_cite_does_not_check_out_is_left_out_with_the_reason(cfg, change, kw, reason):
    facts, summary = run_cited(with_members(cfg, {**CLAUNCH, **change}), CLAUNCH_MEETINGS, **kw)
    assert att(facts, "2026-03-05")["CLAUNCH"] is None
    assert summary["members"][0]["ok"] is False and summary["members"][0]["detail"] == reason
    assert {"member": summary["members"][0]["name"], "problem": f"configured member left out: {reason}"} in \
        summary["problems"]
    assert not any(o.get("name_source") for o in facts["officials"])
    assert not any(w.get("configured") for w in facts["_wards"])


@pytest.mark.parametrize("bad,match", [
    ({"name": "Claunch"}, "full name"),
    ({"name": "eric claunch"}, "full name"),
    ({"ward": 13}, "1-12"),
    ({"kind": "agenda"}, "kind"),
    ({"kind": "news"}, "kind"),
    ({"seated": "Feb 19"}, "date"),
    ({"cite_url": "http://example.com/x"}, "https"),
    ({"cite_page": 0}, "page"),
    ({"quote": " "}, "quote"),
])
def test_n10_a_bad_members_entry_is_refused(bad, match):
    raw = yaml.safe_load(ac.config_path("clarksville-tn").read_text())
    with pytest.raises(ac.AgendaCenterConfigError, match=match):
        ac.parse_config({**raw, "members": [{**CLAUNCH, **bad}]})


def test_n10_two_entries_seating_one_ward_on_one_date_are_refused():
    raw = yaml.safe_load(ac.config_path("clarksville-tn").read_text())
    with pytest.raises(ac.AgendaCenterConfigError, match="two entries seat Ward 2 on 2026-02-19"):
        ac.parse_config({**raw, "members": [CLAUNCH, {**CLAUNCH, "name": "Jeff Loyd",
                                                      "quote": "Jeff Loyd was selected"}]})


def test_n10_a_full_name_list_after_the_seating_that_gives_the_ward_to_someone_else_drops_the_entry(cfg):
    other = SEATED.replace("Deanna McLaughlin (Ward 2)", "Jeff Loyd (Ward 2)")
    meetings = CLAUNCH_MEETINGS[:2] + [("2026-03-05", minutes("2026-03-05", other, aye=SEATED_AYE.replace(
        "McLaughlin", "Loyd"))), ("2026-04-02", minutes("2026-04-02", AFTER, aye=AFTER))]
    facts, _ = run_cited(with_members(cfg, CLAUNCH), meetings)
    assert att(facts, "2026-04-02")["CLAUNCH"] is None
    assert "Eric Claunch: Ward 2 printed for Jeff Loyd on 2026-03-05" in surname_check(facts, "2026-04-02")["detail"]


def test_n10_the_entry_is_not_carried_past_the_next_seating(cfg):
    meetings = CLAUNCH_MEETINGS + [("2027-01-07", minutes("2027-01-07", AFTER, aye=AFTER))]
    facts, _ = run_cited(with_members(cfg, CLAUNCH), meetings)
    assert att(facts, "2026-03-05")["CLAUNCH"] == "city-eric-claunch"
    assert att(facts, "2027-01-07")["CLAUNCH"] is None


def test_n10_the_real_config_entry_is_eric_claunch_ward_2_from_the_special_session_minutes(cfg):
    assert cfg.members == (CLAUNCH,)
    assert cfg.members_on("2026-02-18") == [] and cfg.members_on("2026-02-19") == [CLAUNCH]
