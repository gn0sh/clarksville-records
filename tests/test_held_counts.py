"""Invariant: held-back counts (docs/architecture/clarksville-records.md). Problem family neutrality/held-count.

CEO decision 2026-11-07: unverified roll calls are shown, marked "*", and counted apart from confirmed ones.
1. Confirmed only from confirmed: changing any unconfirmed roll call changes no confirmed count.
2. Unconfirmed only from the official's own resolved id; rewriting every raw name and alias changes no count.
3. Same meeting, same treatment: every official with a resolved vote in a roll call gets it, with the same mark.
4. Exactly once: every vote counts once, under its resolved official or in the one site-wide unmatched sentence;
   an unmatched vote is on no official's page and shows "Name not matched*" on the meeting page.
6. Unverified motions never name anyone: type label plus "Attribution under review" everywhere.
"""
import copy
import random
import re

from html import unescape

from markupsafe import escape

from sitegen import views
from test_site_review_fixes import (MEETING_DEC, MEETING_NOV, MO_SHOWN, RC_HELD, RC_SHOWN, build_pages, by_id,
                                    public, unverify)

MO_HELD = "mo-314626e6-p15-2"  # the motion of RC_HELD: moved e-fixture, seconded c-placeholder
VOTES = re.compile(r"Roll call votes, [0-9-]+ to [0-9-]+: (\d+) Yes, (\d+) No, (\d+) Abstain, (\d+) Other confirmed; "
                   r"(\d+) Yes\*, (\d+) No\*, (\d+) Abstain\*, (\d+) Other\* not confirmed\.")
UNMATCHED = re.compile(r"(\d+) votes? in this period (?:has|have) a name that could not be matched")
NOTE = "Not confirmed: this page was hard to read."


def parts(facts):
    """{official_id: ((confirmed y, n, a, o), (unconfirmed y, n, a, o), unmatched, unmatched sentence)}."""
    ix = views.Index(facts)
    out = {}
    for o in facts["officials"]:
        s = views.totals_sentences(ix, o["id"])
        m = VOTES.fullmatch(s[1])
        assert m, s[1]
        n = [int(x) for x in m.groups()]
        out[o["id"]] = (tuple(n[:4]), tuple(n[4:]), int(UNMATCHED.match(s[2]).group(1)), s[2])
    return out


def recount(facts, official_id, verified):
    c = {"yes": 0, "no": 0, "abstain": 0, "other": 0}
    for rc in facts["roll_calls"]:
        if views.is_verified(rc) != verified:
            continue
        for v in rc["votes"]:
            if v["official_id"] == official_id:
                c[v["value"]] += 1
    return tuple(c[k] for k in ("yes", "no", "abstain", "other"))


def text_of(html, fact_id, key="id"):
    """The text of the element carrying key="fact_id", in document order, tags removed."""
    at = html.index(f'{key}="{fact_id}"')
    start = html.rindex("<", 0, at)
    tag = re.match(r"<(\w+)", html[start:]).group(1)
    end = html.index(f"</{tag}>", at)
    return " ".join(unescape(re.sub(r"<[^>]+>", "", html[start:end])).split())


# --- targeted cases -------------------------------------------------------------------------------------------------


def test_fixture_counts_confirmed_and_unconfirmed_apart(facts):
    p = parts(facts)
    # a-example: Yes in the three verified roll calls; Yes in the unverified December one.
    assert p["a-example"][:2] == ((3, 0, 0, 0), (1, 0, 0, 0))
    assert views.totals_sentences(views.Index(facts), "a-example")[1] == (
        "Roll call votes, 2024-10-07 to 2024-12-09: 3 Yes, 0 No, 0 Abstain, 0 Other confirmed; "
        "1 Yes*, 0 No*, 0 Abstain*, 0 Other* not confirmed.")
    assert p["c-placeholder"][:2] == ((2, 0, 0, 1), (0, 1, 0, 0))
    assert {x[2] for x in p.values()} == {0}


def test_unconfirmed_roll_call_never_changes_a_confirmed_total(facts):
    """Rule 1: flipping, adding or dropping unconfirmed votes changes only the starred part."""
    before = parts(facts)
    f = copy.deepcopy(facts)
    rc = by_id(f, "roll_calls", RC_HELD)
    for v in rc["votes"]:
        v["value"] = "no"
    rc["votes"].append({"official_id": "b-sample", "raw_name": "B. Sample", "value": "yes", "raw_value": "Y"})
    after = parts(f)
    for oid in before:
        assert after[oid][0] == before[oid][0], oid
    assert after["a-example"][1] == (0, 1, 0, 0)
    assert after["b-sample"][1] == (1, 0, 0, 0)


def test_unconfirmed_vote_shows_starred_with_the_page_link(tmp_path, facts):
    pages = build_pages(tmp_path, copy.deepcopy(facts))
    rc = by_id(facts, "roll_calls", RC_HELD)
    link = f'href="https://example.invalid/fixture/minutes-2024-12.pdf#page={rc["page"]}"'
    for v in rc["votes"]:
        html = pages[f"officials/{v['official_id']}.html"]
        row = text_of(html, f"{RC_HELD}/{v['official_id']}", "data-fact-id")
        assert views.vote_label(v["value"], v["raw_value"]) + "*" in row and NOTE in row and "Read it yourself" in row
        assert link in html
    block = text_of(pages[f"meetings/{MEETING_DEC}.html"], RC_HELD)
    assert NOTE in block and "Read it yourself" in block and "Outcome*:" in block
    assert link in pages[f"meetings/{MEETING_DEC}.html"]
    assert "1 roll call at this meeting is not confirmed and marked *." in pages[f"meetings/{MEETING_DEC}.html"]
    # A confirmed roll call carries no star.
    assert NOTE not in text_of(pages[f"meetings/{MEETING_DEC}.html"], RC_SHOWN)


def test_unmatched_vote_is_on_no_official_page_and_unnamed_on_the_meeting_page(tmp_path, facts):
    """Rule 4: never guess a name."""
    f = copy.deepcopy(facts)
    for v in by_id(f, "roll_calls", RC_HELD)["votes"]:
        if v["official_id"] == "a-example":
            v.update(official_id=None, raw_name="Qq A. Exarnple")
    p = parts(f)
    assert p["a-example"][1] == (0, 0, 0, 0) and p["a-example"][0] == (3, 0, 0, 0)
    assert {x[2] for x in p.values()} == {1} and len({x[3] for x in p.values()}) == 1
    pages = build_pages(tmp_path, f)
    assert f"{RC_HELD}/a-example" not in pages["officials/a-example.html"]
    block = text_of(pages[f"meetings/{MEETING_DEC}.html"], RC_HELD)
    assert "Name not matched*" in block
    sentence = "1 vote in this period has a name that could not be matched to an official and is not counted for any member."
    for o in f["officials"]:
        assert str(escape(sentence)) in pages[f"officials/{o['id']}.html"]
    for name, html in public(pages).items():
        assert "Qq A. Exarnple" not in html and "Exarnple" not in html, name


def test_unverified_motion_never_names_anyone_even_with_an_unconfirmed_roll_call(tmp_path, facts):
    """Rule 6 (manager decision 2026-11-07): both names resolve and the roll call is unconfirmed, still no names."""
    f = copy.deepcopy(facts)
    unverify(by_id(f, "motions", MO_HELD), "mover_present")
    pages = build_pages(tmp_path, f)
    names = {o["id"]: o["name"] for o in f["officials"]}
    meeting = pages[f"meetings/{MEETING_DEC}.html"]
    for fid in (RC_HELD, MO_HELD):
        text = text_of(meeting, fid)
        assert "Attribution under review" in text and "Moved by" not in text and "Seconded by" not in text, fid
    ev = next(e["id"] for e in f["item_events"] if e["ref"] == MO_HELD)
    assert "Attribution under review" in text_of(pages["items/2024.html"], ev, "data-fact-id")
    for v in by_id(f, "roll_calls", RC_HELD)["votes"]:
        row = text_of(pages[f"officials/{v['official_id']}.html"], f"{RC_HELD}/{v['official_id']}", "data-fact-id")
        assert "Attribution under review" in row and "Moved by" not in row, v["official_id"]
    for name, html in public(pages).items():
        assert f"{MO_HELD}/moved" not in html and f"{MO_HELD}/seconded" not in html, name
        assert f"seconded by {names['c-placeholder']}*" not in html, name


def test_confirmed_roll_call_shows_no_star_anywhere(tmp_path, facts):
    """Rule 3/6: a confirmed roll call's block, item event and official rows carry no "*" and no note, even when its
    motion is unverified or one vote's name is unmatched."""
    f = copy.deepcopy(facts)
    unverify(by_id(f, "motions", MO_SHOWN), "mover_present")
    rc = by_id(f, "roll_calls", RC_SHOWN)
    rc["votes"][0].update(official_id=None, raw_name="Qq Unmatched")
    pages = build_pages(tmp_path, f)
    block = text_of(pages[f"meetings/{MEETING_DEC}.html"], RC_SHOWN)
    assert "*" not in block and NOTE not in block and "Outcome:" in block and "Name not matched" in block
    ev = next(e["id"] for e in f["item_events"] if e["ref"] == RC_SHOWN)
    event = text_of(pages["items/2024.html"], ev, "data-fact-id")
    assert "*" not in event and NOTE not in event
    for v in rc["votes"][1:]:
        row = text_of(pages[f"officials/{v['official_id']}.html"], f"{RC_SHOWN}/{v['official_id']}", "data-fact-id")
        assert "*" not in row and NOTE not in row, v["official_id"]


def test_unverified_motion_keeps_attribution_under_review_otherwise(tmp_path, facts):
    """Rule 6: one name unresolved, or the roll call confirmed, or the same person twice: under review."""
    cases = []
    f = copy.deepcopy(facts)  # one name unresolved
    mo = by_id(f, "motions", MO_HELD)
    unverify(mo, "seconder_resolves")
    mo["seconded_by"] = {"official_id": None, "raw_name": "Qq Raw Seconder"}
    cases.append((f, MO_HELD, RC_HELD))
    f = copy.deepcopy(facts)  # the motion's roll call is confirmed
    unverify(by_id(f, "motions", MO_SHOWN), "mover_present")
    cases.append((f, MO_SHOWN, RC_SHOWN))
    f = copy.deepcopy(facts)  # same person twice
    mo = by_id(f, "motions", MO_HELD)
    unverify(mo, "mover_differs_from_seconder")
    mo["seconded_by"] = dict(mo["moved_by"])
    cases.append((f, MO_HELD, RC_HELD))
    for n, (f, mo_id, rc_id) in enumerate(cases):
        (tmp_path / str(n)).mkdir()
        pages = build_pages(tmp_path / str(n), f)
        for fid in (mo_id, rc_id):
            text = text_of(pages[f"meetings/{MEETING_DEC}.html"], fid)
            assert "Attribution under review" in text and "Moved by" not in text and "Seconded by" not in text, (n, fid)
        for name, html in public(pages).items():
            assert f"{mo_id}/moved" not in html and f"{mo_id}/seconded" not in html, (n, name)
            assert "Qq Raw" not in html, (n, name)


def test_about_page_explains_the_rule(pages):
    """copy/about-corrupted: the paragraph reads as intended, with nothing spliced into it."""
    para = next(p for p in re.findall(r"<p>(.*?)</p>", pages["about.html"], re.S) if "not confirmed" in p)
    expected = (
        "A computer program can misread a page, so each extracted fact is checked automatically before it is shown. "
        "For a roll call the checks are: every member present has exactly one recorded vote; the Yes, No and Abstain "
        "totals equal the totals the minutes state; the recorded outcome agrees with the votes; and every name matches "
        "the roster for that meeting. A roll call that passes every check is <em>confirmed</em>. A roll call that "
        "fails any check is still shown, marked with an asterisk (*) and &ldquo;Not confirmed: this page was hard to "
        "read. Read it yourself&rdquo;, with a link to that page of the minutes. Confirmed and not confirmed votes are "
        "always counted separately, for example &ldquo;12 Yes, 3 No confirmed; 2 Yes* not confirmed&rdquo;, and a not "
        "confirmed vote never changes a confirmed total. A vote whose name could not be matched to an official is "
        "never placed under anyone: it appears only on the meeting and item pages, as &ldquo;Name not matched*&rdquo;, "
        "and is "
        "counted once, in one sentence that is the same on every official's page. For a motion the checks are that "
        "the people named as moving and seconding it match the roster, were present, and are two different people; "
        "if any of these fails, the motion is marked &ldquo;Attribution under review&rdquo; and no one is named as "
        "moving or seconding it, even when its roll call is shown. The minutes' own sentence for a "
        "motion, and the names exactly as the program read them, are never shown on these pages or included in the "
        "data files below, because the program can misread names in them. Each motion is shown as its kind, such as "
        "&ldquo;Motion to adopt&rdquo;. A roll call shows its outcome as Passed, Failed or Other with a tally counted "
        "from the votes shown on the page, never the minutes' own outcome sentence. Attendance that fails its checks "
        "is not shown. Scanned minutes with no readable text are shown as &ldquo;Attendance not extracted for this "
        "meeting.&rdquo;")
    assert para == expected


# --- property tests over random variations of the fixture -----------------------------------------------------------


def random_facts(facts, rnd):
    """A random but contract-shaped variation: which roll calls are verified, extra roll calls at any meeting, vote
    values, and votes whose name did not resolve."""
    f = copy.deepcopy(facts)
    template = f["roll_calls"][0]
    for n in range(rnd.randint(0, 6)):
        rc = copy.deepcopy(template)
        rc.update(id=f"rc-random-{n}", meeting_id=rnd.choice(f["meetings"])["id"], motion_id=None)
        f["roll_calls"].append(rc)
    for rc in f["roll_calls"]:
        if rnd.random() < 0.5:
            unverify(rc, rnd.choice(["names_resolve", "tally_matches_stated", "roster_available"]))
        else:
            rc["verification"] = {"status": "verified", "checks": [{"check": "names_resolve", "ok": True}]}
        for v in rc["votes"]:
            v["value"] = rnd.choice(["yes", "no", "abstain", "other"])
            if rnd.random() < 0.3:
                v.update(official_id=None, raw_name=rnd.choice(["A Example", "Comm. B. Sample", "X. Garbled", "?"]))
    return f


def rewrite_names(f, rnd):
    """Every raw name and alias replaced by noise, plus aliases shared across officials."""
    g = copy.deepcopy(f)
    noise = lambda: "".join(rnd.choice("abcxyz .,") for _ in range(8))  # noqa: E731
    for m in g["meetings"]:
        for a in m["attendance"]:
            a["raw_name"] = noise()
    for rc in g["roll_calls"]:
        for v in rc["votes"]:
            v["raw_name"] = noise()
    for mo in g["motions"]:
        for ref in (mo["moved_by"], mo["seconded_by"]):
            if ref is not None:
                ref["raw_name"] = noise()
    shared = noise()
    for o in g["officials"]:
        o["aliases"] = [noise(), shared]
    return g


def test_count_invariant_holds_for_random_variations(facts):
    for seed in range(300):
        rnd = random.Random(seed)
        f = random_facts(facts, rnd)
        p = parts(f)
        ix = views.Index(f)
        for oid, (conf, unconf, _, _) in p.items():
            assert conf == recount(f, oid, True), seed     # 1: confirmed only from verified roll calls
            assert unconf == recount(f, oid, False), seed  # 2: unconfirmed only from their own resolved id
        # 4: every vote exactly once; one unmatched sentence, the same everywhere.
        total = sum(len(rc["votes"]) for rc in f["roll_calls"])
        unmatched = {x[2] for x in p.values()}
        assert len(unmatched) == 1 and len({x[3] for x in p.values()}) == 1, seed
        assert sum(sum(c) + sum(u) for c, u, _, _ in p.values()) + unmatched.pop() == total, seed
        # 3: same roll call, same treatment: each resolved vote has a row on its official's page, marked as its
        # roll call is, and no official has a row for a vote that is not theirs.
        for o in f["officials"]:
            rows = {r["fact_id"]: r["confirmed"] for r in views.official(o["id"], ix)["rows"] if r["type"] == "vote"}
            want = {f"{rc['id']}/{o['id']}": views.is_verified(rc) for rc in f["roll_calls"]
                    for v in rc["votes"] if v["official_id"] == o["id"]}
            assert rows == want, seed
        # 2: no name matching. Noise in every raw name and alias, and a shared alias, change no count.
        assert parts(rewrite_names(f, rnd)) == p, seed


def test_official_with_no_votes_sees_zeros_and_the_same_unmatched_sentence(facts):
    f = copy.deepcopy(facts)
    f["officials"].append({"id": "z-nobody", "name": "Z. Nobody", "surname": "Nobody", "given": "Z.",
                           "title": "Commissioner", "aliases": []})
    unverify(by_id(f, "roll_calls", "rc-99d3ff29-p8-1"))
    p = parts(f)
    assert p["z-nobody"][:2] == ((0, 0, 0, 0), (0, 0, 0, 0))
    assert {x[3] for x in p.values()} == {p["z-nobody"][3]}
    assert by_id(f, "meetings", MEETING_NOV)["attendance_status"] == "extracted"
