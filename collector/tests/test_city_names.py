"""Name resolution invariant (docs/architecture/city-council.md, problem family city-votes, third hit
city-votes/surname-stale-book): one test per path N1-N8, each through assert_name_invariant, plus the reviewer's case
of a departed member's surname reused by a new member.

Invariant: a printed name resolves to a member only when exactly one member of that meeting's own roster matches it;
the roster is the meeting's attendance in full (through the aliases) plus its presiding mayor, and a surname printed
alone counts only against titled full names in the same minutes or full-name lists printed since the latest seating,
for members no later list in that window replaced. Anything else is held.
"""
import re

import jsonschema
import pytest
import yaml

from collector import agenda_center as ac
from collector.city_build import Officials, RosterBook, build, official_id, printed_full_names, resolve
from collector.city_minutes import NAME_RE, parse_text, titled_names
from collector.tests.test_city_minutes import SCHEMA, FakeStore, entry

API = "https://clarksvilletn.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId={},plainText=false)"
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


@pytest.fixture(scope="module")
def cfg():
    return ac.load_config(ac.config_path("clarksville-tn"))


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
    """Every resolved name of a meeting is on that meeting's roster (its attendance, or its presiding mayor), matches
    exactly one member of it, and every surname read from earlier lists names lists dated inside the meeting's window
    (from the latest seating up to the meeting)."""
    names = {o["id"]: o["name"] for o in facts["officials"]}
    off = Officials(cfg)
    for m in facts["meetings"]:
        pm = parse_text([texts[m["date"]]], cfg)
        roster = {a["official_id"] for a in m["attendance"] if a["official_id"]}
        if pm.presiding and pm.presiding_title == cfg.presiding_title:
            roster.add(official_id(off.canonical(pm.presiding)))
        pairs = [(oid, names[oid]) for oid in sorted(roster)]
        for a in m["attendance"]:
            if a["official_id"] and not NAME_RE.match(a["raw_name"]):          # read from a surname
                assert names[a["official_id"]].split()[-1].lower() == a["raw_name"].lower()
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
            assert v["official_id"] == resolve(v["raw_name"], pairs), (m["id"], v)
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
    assert not c["ok"] and "REYNOLDS (Karen Reynolds: last printed 2024-10-03, before the seating of 2025-01-01)" \
        in c["detail"]
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
    """The presiding mayor is on the meeting's roster. A mayor printed earlier in the window whose seat a later list
    gives to another mayor is held for a later PITTS."""
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", FULL, aye=FULL_AYE)),
                         ("2025-02-06", minutes("2025-02-06", FULL, aye=FULL_AYE.replace("Pitts", "McMillan"),
                                                mayor="Kim McMillan")),
                         ("2025-08-07", minutes("2025-08-07", CAPS, aye=CAPS, mayor="Kim McMillan"))])
    rc = next(r for r in facts["roll_calls"] if r["meeting_id"] == meeting(facts, "2025-01-02")["id"])
    assert {v["raw_name"]: v["official_id"] for v in rc["votes"]}["Pitts"] == "city-joe-pitts"
    assert rc["verification"]["status"] == "verified"
    assert att(facts, "2025-08-07")["PITTS"] is None
    assert "Joe Pitts: Mayor printed for Kim McMillan on 2025-02-06" in surname_check(facts, "2025-08-07")["detail"]


def test_n4_a_titled_name_in_these_minutes_resolves_but_a_former_member_does_not(cfg):
    assert titled_names("honoring former Councilman David Allen and the late Mayor Ted Crozier. Councilman "
                        "Eric Claunch spoke.") == ["Eric Claunch"]
    caps = CAPS.replace("REYNOLDS", "CLAUNCH, ALLEN")
    extra = "Councilman Eric Claunch led the Pledge. A plaque honored former Councilman David Allen."
    facts, _ = run(cfg, [("2025-01-02", minutes("2025-01-02", FULL, aye=FULL_AYE)),
                         ("2025-08-07", minutes("2025-08-07", caps, aye=caps, extra=extra))])
    a = att(facts, "2025-08-07")
    assert a["CLAUNCH"] == "city-eric-claunch" and a["ALLEN"] is None
    assert "by these minutes" in surname_check(facts, "2025-08-07")["detail"]


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
    assert all(p["date"] >= "2025-01-01" for e in book.values() for p in e["people"])
    no_rule = RosterBook(ac.AgendaCenterConfig(**{**cfg.__dict__, "seating": None}))
    no_rule.lists = rb.lists
    assert all(not e["people"] for e in no_rule.for_meeting("2025-08-07").values())       # no rule: nothing earlier


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
