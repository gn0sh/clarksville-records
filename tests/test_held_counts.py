"""Invariant: held-back counts (docs/architecture/clarksville-records.md). Problem family neutrality/held-count.

1. Same meeting, same count: two officials both listed in a meeting's verified attendance get the same held roll
   calls from that meeting (both or neither).
2. No name matching: no held roll call is attributed through a raw name or alias. Rewriting every raw name and alias
   changes no count.
3. Exactly once: every held roll call in the period is counted once, either in the per-official sentences (for every
   official the verified attendance lists) or in the one uniform clause, which reads the same on every page.
"""
import copy
import random
import re

from markupsafe import escape

from sitegen import views
from test_site_review_fixes import MEETING_DEC, MEETING_NOV, MEETING_OCT, RC_HELD, build_pages, by_id, unverify

UNIFORM = re.compile(r"A further (\d+) roll calls? under review")


def held_parts(facts):
    """{official_id: (per-official number, uniform number or 0, full held sentence)} as the pages show them."""
    ix = views.Index(facts)
    out = {}
    for o in facts["officials"]:
        s = views.totals_sentences(ix, o["id"])[1]
        u = UNIFORM.search(s)
        out[o["id"]] = (int(re.match(r"(\d+) roll call", s).group(1)), int(u.group(1)) if u else 0, s)
    return out


def uniform_clause(s):
    i = s.find(" A further ")
    return s[i:] if i >= 0 else ""


def put_under_review(f, meeting_id):
    unverify(by_id(f, "meetings", meeting_id), "absent_count_matches_stated")
    for rc in f["roll_calls"]:
        if rc["meeting_id"] == meeting_id:
            unverify(rc, "roster_available")


def mangle_everywhere(f, official_id, garbled):
    """The official's name OCRs badly in every raw form: attendance, votes, Moved/Seconded. Attendance keeps its
    resolved id only where the verifier resolved it; votes and motions lose theirs."""
    for m in f["meetings"]:
        for a in m["attendance"]:
            if a["official_id"] == official_id:
                a["raw_name"] = garbled
    for rc in f["roll_calls"]:
        for v in rc["votes"]:
            if v["official_id"] == official_id:
                v.update(official_id=None, raw_name=garbled)
    for mo in f["motions"]:
        for ref in (mo["moved_by"], mo["seconded_by"]):
            if ref is not None and ref["official_id"] == official_id:
                ref.update(official_id=None, raw_name=garbled)


# --- targeted cases -------------------------------------------------------------------------------------------------


def test_mangled_name_at_under_review_meeting_gives_everyone_the_same_count(facts):
    """neutrality/held-count: an official whose name OCRs badly everywhere at a meeting whose attendance is under
    review does not get 0 while colleagues get 1. Those roll calls go into the uniform clause for everyone."""
    f = copy.deepcopy(facts)
    put_under_review(f, MEETING_DEC)
    mangle_everywhere(f, "a-example", "A. Exarnple")
    parts = held_parts(f)
    assert {p[0] for p in parts.values()} == {0}
    assert {p[1] for p in parts.values()} == {2}  # both December roll calls are held
    assert len({p[2] for p in parts.values()}) == 1  # the whole sentence is identical on every page
    assert parts["a-example"][2] == ("0 roll calls in this period are not shown because they are under review. "
                                     "A further 2 roll calls under review are at meetings whose attendance is not "
                                     "shown, and are not counted for any one member.")


def test_mangled_vote_name_at_shown_meeting_still_counts_for_the_listed_official(facts):
    """neutrality/held-count: with verified attendance, the listed official counts whatever their vote OCR'd as."""
    f = copy.deepcopy(facts)
    mangle_everywhere(f, "a-example", "A. Exarnple")
    parts = held_parts(f)
    assert {oid: p[:2] for oid, p in parts.items()} == {o["id"]: (1, 0) for o in f["officials"]}


def test_shared_alias_counts_no_one_who_was_not_listed(facts):
    """neutrality/held-count: an alias two officials share never places either of them at a meeting."""
    f = copy.deepcopy(facts)
    f["officials"].append({"id": "f-other", "name": "F. Other", "surname": "Other", "given": "F.",
                           "title": "Commissioner", "aliases": ["A Example"]})
    by_id(f, "officials", "b-sample")["aliases"].append("A Example")
    for v in by_id(f, "roll_calls", RC_HELD)["votes"]:
        if v["official_id"] == "a-example":
            v.update(official_id=None, raw_name="A Example")
    # Shown attendance: the five listed officials count, f-other (not listed, shares the alias) does not.
    parts = held_parts(f)
    assert parts["f-other"][:2] == (0, 0)
    assert {parts[a["official_id"]][:2] for a in by_id(f, "meetings", MEETING_DEC)["attendance"]} == {(1, 0)}
    # Attendance under review: nobody is placed by the alias; every page shows the same uniform clause.
    put_under_review(f, MEETING_DEC)
    parts = held_parts(f)
    assert {p[:2] for p in parts.values()} == {(0, 2)}


def test_attendance_not_extracted_goes_to_the_uniform_clause(tmp_path, facts):
    """neutrality/held-count: no attendance section, so nobody is placed; one clause, same number on every page, and
    the meeting page states the same held roll calls."""
    f = copy.deepcopy(facts)
    m = by_id(f, "meetings", MEETING_DEC)
    m.update(attendance_status="not_extracted", attendance=[], stated_absent_count=None)
    unverify(m, "roster_available")
    for rc in f["roll_calls"]:
        if rc["meeting_id"] == MEETING_DEC:
            unverify(rc, "roster_available")
    parts = held_parts(f)
    assert {p[:2] for p in parts.values()} == {(0, 2)}
    clause = ("A further 2 roll calls under review are at meetings whose attendance is not shown, "
              "and are not counted for any one member.")
    pages = build_pages(tmp_path, f)
    for o in f["officials"]:
        assert str(escape(clause)) in pages[f"officials/{o['id']}.html"]
    assert "2 roll calls at this meeting are under review and not shown." in pages[f"meetings/{MEETING_DEC}.html"]


def test_about_page_explains_the_held_count_rule(pages):
    """copy/about-corrupted: the held-back paragraph reads as intended, with nothing spliced into it."""
    para = next(p for p in re.findall(r"<p>(.*?)</p>", pages["about.html"], re.S) if "held back" in p)
    expected = (
        "A computer program can misread a page, so each extracted fact is checked automatically before it is shown. "
        "For a roll call the checks are: every member present has exactly one recorded vote; the Yes, No and Abstain "
        "totals equal the totals the minutes state; the recorded outcome agrees with the votes; and every name matches "
        "the roster for that meeting. A fact that passes every check is <em>verified</em> and is shown. A fact that "
        "fails any check is <em>held back</em>: it is not shown, and nothing is guessed in its place. For a motion the "
        "checks are that the people named as moving and seconding it match the roster, were present, and are two "
        "different people; if any of these fails, the two names are held back and the motion is marked "
        "&ldquo;Attribution under review&rdquo;. The minutes' own sentence for a motion, and the names exactly as the "
        "program read them, are never shown on these pages or included in the data files below, because the program "
        "can misread names in them. Each motion is shown as its kind, such as "
        "&ldquo;Motion to adopt&rdquo;, and, when verified, &ldquo;Moved by&rdquo; and &ldquo;seconded by&rdquo; "
        "the officials named on this site. A roll call shows "
        "its outcome as Passed, Failed or Other with a tally counted from the votes shown on the page, never the "
        "minutes' own outcome sentence. Each official's page states how many held-back roll "
        "calls are at meetings whose verified attendance lists that person, present or absent. Held-back roll calls "
        "at meetings whose attendance is not shown are counted once, in one sentence that is the same on every "
        "official's page. Scanned minutes with no readable text are shown as &ldquo;Attendance not extracted for "
        "this meeting.&rdquo;")
    assert para == expected


# --- property tests over random variations of the fixture -----------------------------------------------------------


def random_facts(facts, rnd):
    """A random but contract-shaped variation: each meeting's attendance state, who is listed, which roll calls are
    held, extra roll calls at any meeting, and garbled raw names."""
    f = copy.deepcopy(facts)
    ids = [o["id"] for o in f["officials"]]
    for m in f["meetings"]:
        state = rnd.choice(["shown", "under_review", "not_extracted"])
        if state == "not_extracted":
            m.update(attendance_status="not_extracted", attendance=[], stated_absent_count=None)
            unverify(m, "roster_available")
            continue
        listed = rnd.sample(ids, rnd.randint(0, len(ids)))
        m.update(attendance_status="extracted", attendance=[
            {"official_id": oid, "raw_name": by_id(f, "officials", oid)["name"], "page": 1,
             "status": rnd.choice(["present", "absent"])} for oid in listed])
        if state == "shown":
            m["verification"] = {"status": "verified", "checks": [{"check": "names_resolve", "ok": True}]}
        else:
            unverify(m, "absent_count_matches_stated")
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


def test_held_count_invariant_holds_for_random_variations(facts):
    for seed in range(300):
        rnd = random.Random(seed)
        f = random_facts(facts, rnd)
        ix = views.Index(f)
        attribution = views.held_attribution(ix)
        held_ids = {rc["id"] for rc in f["roll_calls"] if not views.is_verified(rc)}
        parts = held_parts(f)

        # Exactly once: every held roll call has one entry; nothing verified is in it.
        assert set(attribution) == held_ids, seed
        for rc_id, people in attribution.items():
            m = ix.meetings[ix.roll_calls[rc_id]["meeting_id"]]
            listed = {a["official_id"] for a in m["attendance"]}
            if views.attendance_shown(m) and listed:
                assert people == listed, seed  # 1: everyone listed, present or absent, and no one else
            else:
                assert people is None, seed  # goes to the uniform clause

        # Per-official sentences and the uniform clause match the attribution.
        uniform = sum(1 for p in attribution.values() if p is None)
        for oid, (n, u, _) in parts.items():
            assert n == sum(1 for p in attribution.values() if p and oid in p), seed
            assert u == uniform, seed
        assert len({uniform_clause(s) for _, _, s in parts.values()}) == 1, seed

        # 1: two officials listed in the same verified attendance get identical counts from that meeting.
        for m in f["meetings"]:
            if not views.attendance_shown(m):
                continue
            at_m = [p for rc_id, p in attribution.items() if ix.roll_calls[rc_id]["meeting_id"] == m["id"]]
            for a in m["attendance"]:
                for b in m["attendance"]:
                    assert all((a["official_id"] in p) == (b["official_id"] in p) for p in at_m), seed

        # 3: the parts add up to the meeting pages' held sentences and to the period's held total.
        by_meeting = {m["id"]: views.meeting(m["id"], ix)["held_roll_calls"] for m in f["meetings"]}
        attributed = sum(by_meeting[m["id"]] for m in f["meetings"]
                         if views.attendance_shown(m) and m["attendance"])
        assert attributed + uniform == sum(by_meeting.values()) == len(held_ids), seed

        # 2: no name matching. Noise in every raw name and alias, and a shared alias, change no count.
        g = rewrite_names(f, rnd)
        assert held_parts(g) == parts, seed


def test_unlisted_official_sees_the_same_uniform_clause(facts):
    """An official listed nowhere gets 0 and the same uniform clause as everyone else."""
    f = copy.deepcopy(facts)
    put_under_review(f, MEETING_NOV)
    f["officials"].append({"id": "z-nobody", "name": "Z. Nobody", "surname": "Nobody", "given": "Z.",
                           "title": "Commissioner", "aliases": []})
    parts = held_parts(f)
    assert parts["z-nobody"][:2] == (0, 2)  # both November roll calls
    assert {uniform_clause(p[2]) for p in parts.values()} == {uniform_clause(parts["z-nobody"][2])}
    assert by_id(f, "meetings", MEETING_OCT)["attendance_status"] == "not_extracted"  # no roll calls there
