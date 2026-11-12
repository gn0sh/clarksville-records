"""Vote-to-item link invariant (docs/architecture/city-council.md; problem family city-votes/item-link, second hit).

A roll call is linked to a numbered item only when the words that belong to the vote (its motion, its lead-in
sentence, its outcome sentence) identify that item, or it sits under that item's own number line and those words
name no other item, kind or several items. Otherwise it goes to its section, or is held. One test per code path that
sets the link, each asserting the invariant; then the reviewer's abstention case, the lead-in case and the page-number
case (city-votes/outcome-text)."""
import re

import pytest

from collector import agenda_center as ac
from collector.city_build import build
from collector.city_minutes import Line, _item_for_vote, _motion, parse_text, vote_words
from collector.tests.test_city_minutes import checks, rows_and_store

ASIDE = "Councilman Grubbs abstained from voting on ORDINANCE 99-2015-16."


@pytest.fixture(scope="module")
def cfg():
    return ac.load_config(ac.config_path("clarksville-tn"))


def under_item(kind, number, heading="SECTION"):
    return {"number": number, "kind": kind, "title": "Title", "heading": heading}


def under_section(heading="ZONING"):
    return {"number": None, "kind": None, "title": None, "heading": heading}


def link(cfg, item, window_text, sentence):
    window = [Line(1, s) for s in window_text.split("\n") if s]
    motion = _motion(window)
    out, how = _item_for_vote(item, window, {}, cfg, motion, sentence)
    assert_invariant(cfg, item, window, motion, sentence, out, how)
    return out, how


def assert_invariant(cfg, item, window, motion, sentence, out, how):
    """The invariant, checked on any one link decision."""
    words = " ".join(vote_words(window, cfg, motion, sentence))
    if how["ok"] is False:
        assert out["number"] is None                       # a held roll call is never linked to an item
    if out["number"] is None:
        assert out["heading"] == item["heading"]           # not linked: its section heading, as printed
        return
    assert not cfg.not_item_votes.search(words)            # never Consent Agenda, adjournment or appointments
    num = re.compile(rf"\b{out['kind']}\s+{re.escape(out['number'])}\b", re.I)
    other = [m for m in re.finditer(cfg.item_number.pattern, words, re.I) if not num.match(m.group(0))]
    assert not other                                       # the vote's words name no other item
    if num.search(words):
        assert how["basis"] == "named"
    elif item["number"] == out["number"]:
        assert how["basis"] == "heading"                   # its own number line, and nothing in its words against it
    else:                                                  # "this ordinance", the one ordinance named before the motion
        assert how["basis"] == "named" and re.search(rf"\bthis\s+{out['kind']}\b", words, re.I)
    # a sentence that is not the vote's (an abstention note) never changes the link
    w2 = window[:-1] + [Line(1, ASIDE)] + window[-1:] if len(window) > 1 else [Line(1, ASIDE)] + window
    assert _item_for_vote(item, w2, {}, cfg, _motion(w2), sentence) == (out, how)


# ---- code paths of _item_for_vote: each asserts the invariant through link() ----

MOVED = ("Councilman Erb made a motion to {}. The motion was seconded by Councilman Allen.\n"
         "The following vote was recorded:")


def test_path_not_an_item_vote_goes_to_the_section(cfg):
    out, how = link(cfg, under_item("ordinance", "63-2020-21"), MOVED.format("adjourn"), "The motion to adjourn failed.")
    assert out["number"] is None and how == {"basis": "not_an_item_vote", "ok": True, "detail": None}


def test_path_item_line_another_number_is_held(cfg):
    out, how = link(cfg, under_item("ordinance", "47-2019-20"), "The following vote on RESOLUTION 50-2019-20 was "
                    "recorded:", "The motion to adopt RESOLUTION 50-2019-20 passed.")
    assert out["number"] is None and how["basis"] == "contradiction" and how["ok"] is False


def test_path_item_line_several_numbers_goes_to_the_section(cfg):
    out, how = link(cfg, under_item("ordinance", "47-2019-20"),
                    MOVED.format("adopt ORDINANCE 47-2019-20 and ORDINANCE 48-2019-20"), "The motion passed.")
    assert out["number"] is None and how == {"basis": "several_items", "ok": True, "detail": None}


def test_path_item_line_another_kind_is_held(cfg):
    out, how = link(cfg, under_item("ordinance", "47-2019-20"), MOVED.format("adopt this resolution"),
                    "The motion to adopt this resolution passed.")
    assert out["number"] is None and how["basis"] == "contradiction" and how["ok"] is False


def test_path_item_line_plural_kind_goes_to_the_section(cfg):
    out, how = link(cfg, under_item("ordinance", "48-2019-20"), "The following vote was recorded:",
                    "The motion to adopt these ordinances on first reading passed.")
    assert out["number"] is None and how == {"basis": "several_items", "ok": True, "detail": None}


@pytest.mark.parametrize("sentence, basis", [
    ("The motion to adopt this ordinance on second reading passed.", "heading"),
    ("The motion to adopt ORDINANCE 63-2020-21 on second reading passed.", "named"),
])
def test_path_item_line_links_its_own_item(cfg, sentence, basis):
    out, how = link(cfg, under_item("ordinance", "63-2020-21"),
                    MOVED.format("adopt this ordinance on second reading"), sentence)
    assert out["number"] == "63-2020-21" and how == {"basis": basis, "ok": True, "detail": None}


@pytest.mark.parametrize("window, sentence", [
    (MOVED.format("adopt ORDINANCE 16-2017-18 on first reading"), "The motion passed."),          # motion
    ("The following vote on ORDINANCE 16-2017-18 was recorded:", "The motion passed."),          # lead-in
    (MOVED.format("approve the request"), "The motion to adopt Ordinance 16-2017-18 passed."),   # outcome
])
def test_path_section_one_number_in_the_vote_words_links(cfg, window, sentence):
    out, how = link(cfg, under_section(), window, sentence)
    assert out["number"] == "16-2017-18" and how == {"basis": "named", "ok": True, "detail": None}


def test_path_section_this_ordinance_links_the_one_named_before_the_motion(cfg):
    window = ("The recommendation of the Regional Planning Staff was for disapproval of ORDINANCE 14-2017-18.\n"
              + MOVED.format("adopt this ordinance on first reading"))
    out, how = link(cfg, under_section(), window, "The motion to adopt this ordinance on first reading passed.")
    assert out["number"] == "14-2017-18" and how["basis"] == "named"


@pytest.mark.parametrize("window, sentence", [
    # no item word in the vote's words
    ("The recommendation was for approval of ORDINANCE 14-2017-18.\n" + MOVED.format("refer this request back"),
     "The motion passed."),
    # two numbers in the vote's words
    (MOVED.format("approve the requests"), "The motion to adopt ORDINANCE 15-2017-18 and ORDINANCE 16-2017-18 "
     "passed."),
    # "this ordinance", but two ordinances named before the motion
    ("The recommendations were for approval of ORDINANCE 15-2017-18 and ORDINANCE 16-2017-18.\n"
     + MOVED.format("adopt this ordinance"), "The motion passed."),
    # plural
    ("The recommendation was for approval of ORDINANCE 15-2017-18.\n" + MOVED.format("adopt these ordinances"),
     "The motion passed."),
    # another kind
    ("The recommendation was for approval of ORDINANCE 15-2017-18.\n" + MOVED.format("adopt this resolution"),
     "The motion passed."),
])
def test_path_section_otherwise_goes_to_the_section(cfg, window, sentence):
    out, how = link(cfg, under_section(), window, sentence)
    assert out["number"] is None and how == {"basis": "section", "ok": True, "detail": None}


# ---- the reviewer's case: a number named in passing just before the vote lines ----

@pytest.mark.parametrize("window, sentence", [
    # the delta re-review's synthetic case: the abstention note is the last sentence before the AYE lines
    ("Councilman Erb made a motion to approve the request. The motion was seconded by Councilman Allen.\n"
     "Councilman Grubbs abstained from voting on ORDINANCE 46-2015-16.", "The motion passed."),
    # ... with "this ordinance" in the motion: the note comes after the motion, so it is not what it refers to
    ("Councilman Erb made a motion to adopt this ordinance. The motion was seconded by Councilman Allen.\n"
     "Councilman Grubbs abstained from voting on ORDINANCE 46-2015-16.", "The motion to adopt this ordinance passed."),
    # ... the note before the motion: an abstention note is never what "this ordinance" refers to
    ("Councilman Grubbs abstained from voting on ORDINANCE 46-2015-16.\n" + MOVED.format("adopt this ordinance"),
     "The motion to adopt this ordinance passed."),
    # ... the note in the lead-in sentence itself: only the words from "the following" on are the lead-in
    ("Councilman Erb made a motion to approve the request. The motion was seconded by Councilman Allen.\n"
     "Councilman Grubbs abstained from voting on ORDINANCE 46-2015-16; the following vote was recorded:",
     "The motion passed."),
])
def test_a_number_named_in_passing_before_the_vote_links_nothing(cfg, window, sentence):
    out, how = link(cfg, under_section(), window, sentence)
    assert out["number"] is None and out["heading"] == "ZONING" and how["basis"] == "section"


ABSTAIN = """ATTENDANCE

    PRESENT: Geno Grubbs (Ward 7), Ron Erb (Ward 3), David Allen (Ward 8)

    The regular session was called to order by Mayor Kim McMillan.

ZONING

    Councilman Erb made a motion to approve the request. The motion was seconded by Councilman
    Allen. Councilman Grubbs abstained from voting on ORDINANCE 46-2015-16.

             AYE: Allen, Erb, Grubbs, McMillan

             The motion passed.
"""


def test_abstention_note_before_the_vote_lines_is_not_linked_in_the_facts(cfg):
    rc = parse_text([ABSTAIN], cfg).roll_calls[0]
    assert rc.item["number"] is None and rc.link["basis"] == "section"
    rows, store, inspect = rows_and_store()
    rows = [{**rows[0], "date": "2016-06-02"}]           # inside Mayor Kim McMillan's configured term (path N3)
    facts, _ = build(cfg, rows, store, parse=lambda p, c: parse_text([ABSTAIN], c), inspect=inspect)
    assert facts["roll_calls"][0]["item_id"].startswith("t-")
    assert not any(i["number"] for i in facts["items"])                      # no ORDINANCE 46-2015-16 item
    assert facts["roll_calls"][0]["verification"]["status"] == "verified"


# ---- the lead-in case: the sentence that leads into the vote is the vote's own words ----

@pytest.mark.parametrize("window, sentence, number", [
    # 2016-06-02, as printed: the heading runs into the lead-in, no motion
    ("ADOPTION OF BUDGET The following vote on the motion to adopt ORDINANCE 104-2015-16 on second reading as "
     "amended was recorded:", "The motion to adopt the FY17 General Government budget on second reading as amended "
     "passed.", "104-2015-16"),
    ("The motion to adopt the amendment passed. With no objections, the following vote on RESOLUTION 65-2021-22 "
     "as amended was recorded:", "The motion passed.", "65-2021-22"),
])
def test_a_vote_lead_in_that_names_the_item_links_it(cfg, window, sentence, number):
    out, how = link(cfg, under_section("ADOPTION OF BUDGET"), window, sentence)
    assert out["number"] == number and how["basis"] == "named"


def test_only_a_lead_in_counts_from_the_last_sentence(cfg):
    window = [Line(1, "The motion to amend passed. The following vote on ORDINANCE 80-2021-22 was recorded:")]
    assert vote_words(window, cfg, None, "The motion passed.") == [
        "The following vote on ORDINANCE 80-2021-22 was recorded:", "The motion passed."]
    window = [Line(1, "The motion to amend passed. Councilman Grubbs abstained on ORDINANCE 80-2021-22.")]
    assert vote_words(window, cfg, None, "The motion passed.") == ["The motion passed."]


def test_path_a_roll_call_made_without_the_link_check_is_held():
    from collector.city_minutes import RollCall
    rc = RollCall(1, [], [], "The motion passed.", "passed", under_item("ordinance", "1-2019-20"), None, 0)
    assert rc.link["ok"] is False and rc.link["basis"] == "unset"


# ---- consumers: the build writes the link to the roll call, its motion and its item events alike ----

def test_build_uses_the_link_for_roll_call_motion_and_events(cfg):
    from collector.tests.test_city_minutes import LINKS
    parsed = parse_text([LINKS], cfg).roll_calls
    rows, store, inspect = rows_and_store()
    facts, _ = build(cfg, rows[:1], store, parse=lambda p, c: parse_text([LINKS], c), inspect=inspect)
    items = {i["id"]: i for i in facts["items"]}
    motions = {m["id"]: m for m in facts["motions"]}
    for rc, built_rc in zip(parsed, facts["roll_calls"]):
        it = items[built_rc["item_id"]]
        if rc.item["number"]:
            assert built_rc["item_id"] == f"{rc.item['kind']}-{rc.item['number']}" and it["link_basis"] == "number"
        else:
            assert built_rc["item_id"].startswith("t-") and it["link_basis"] == "title"
            assert it["title"] == rc.item["heading"]
        assert checks(built_rc)["vote_matches_item"]["ok"] is rc.link["ok"]
        if built_rc["motion_id"]:
            assert motions[built_rc["motion_id"]]["item_id"] == built_rc["item_id"]
        evs = [e for e in facts["item_events"] if e["ref"] in (built_rc["id"], built_rc["motion_id"])]
        assert evs and all(e["item_id"] == built_rc["item_id"] for e in evs)


# ---- city-votes/outcome-text: a page number between the vote lines and what follows ----

PAGE_BREAK_1 = """ATTENDANCE

    PRESENT: Ron Erb (Ward 3), David Allen (Ward 8), Jeff Burkhart (Ward 12)

    The regular session was called to order by Mayor Joe Pitts.

15. ORDINANCE 136-2021-22 (First Reading) Amending the Zoning Ordinance

   Councilperson Erb made a motion to adopt ORDINANCE 136-2021-22 (First
   Reading). Councilperson Allen seconded the motion.

   The following vote was recorded:

            AYE: Allen, Erb, Pitts



                                          10"""
PAGE_BREAK_2 = """            NAY: Burkhart

   The motion to adopt ORDINANCE 136-2021-22 (First Reading) passed

16. ORDINANCE 137-2021-22 (First Reading) Amending the Zoning Ordinance

   The following vote was recorded:

            AYE: Allen, Burkhart, Erb, Pitts



                                          11"""
PAGE_BREAK_3 = """   The motion to adopt ORDINANCE 137-2021-22 (First Reading) passed
"""


def test_a_page_number_does_not_break_a_vote_block_or_its_outcome(cfg):
    a, b = parse_text([PAGE_BREAK_1, PAGE_BREAK_2, PAGE_BREAK_3], cfg).roll_calls
    assert [(v.raw_name, v.value) for v in a.votes] == [("Allen", "yes"), ("Erb", "yes"), ("Pitts", "yes"),
                                                          ("Burkhart", "no")]
    assert a.outcome == "passed" and a.outcome_text.startswith("The motion to adopt ORDINANCE 136-2021-22")
    assert a.item["number"] == "136-2021-22"
    assert b.outcome_text == "The motion to adopt ORDINANCE 137-2021-22 (First Reading) passed"
    assert b.item["number"] == "137-2021-22" and b.outcome == "passed"
