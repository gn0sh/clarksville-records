"""City committee pages (milestone C2, sitegen/committees.py): each committee's home and year pages from a FIXTURE
committees.json (made-up names) beside the fixture county facts. hold_motions shows every motion "Not confirmed" with
its words and minutes page only; with the hold off a confirmed voice vote is "Voice vote (not recorded by name):
passed." and never a vote per member; names on a vote only as printed; a motion whose words the record withholds shows
the fixed note (the words rule: docs/architecture/committee-words-invariant.md, restated by site_checks); agenda-only
meetings say the minutes are not posted; minutes printing another date attach nothing. The search index lists every
meeting."""
from html import escape
import json
import re
from datetime import date

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS
from qa import site_checks
from sitegen import committees as cm_mod
from sitegen.build import build

TODAY = date(2024, 12, 1)
PDF = "https://clarksvilletn.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId={},plainText=false)"


def doc(kind, n, stored=True, pages=None):
    d = {"kind": kind, "url": PDF.format(n), "name": kind.title(), "source_id": f"src-{n:012d}" if stored else None,
         "sha256": f"{n:064d}" if stored else None, "fetched_at": "2026-11-16" if stored else None}
    if pages:
        d["pages"] = pages
    return d


def motion(mid, n, page, words, vote, confirmed=True, **kw):
    return {"id": f"{mid}-motion-{n}", "meeting_id": mid, "committee": mid.split("-", 3)[3],
            "source_id": "src-000000000011" if "finance" in mid else "src-000000000021", "page": page,
            "section": "5. Action", "item": "A", "subject_printed": "RESOLUTION 1-2024-25 A Resolution as printed",
            "mover_printed": "Councilman Alpha", "mover": "Alpha", "seconder_printed": "Councilwoman Beta",
            "seconder": "Beta", "motion_printed": words, "vote": vote, "confirmed": confirmed,
            "reasons": [] if confirmed else ["outcome-not-read"], **kw}


def facts(hold=True):
    fin = "2024-11-04-finance"
    return {"fixture": True, "locality": "clarksville-tn", "hold_motions": hold,
            "bodies": [{"slug": "finance", "label": "Finance Committee", "category_name": "Finance Committee"},
                       {"slug": "audit", "label": "Audit Committee", "category_name": "Audit Committee"}],
            "meetings": [
                {"id": fin, "committee": "finance", "body": "Finance Committee", "date": "2024-11-04",
                 "title": "Finance Committee Meeting", "event_id": 1, "cancelled": False, "video_url": None,
                 "documents": [doc("agenda", 10), doc("minutes", 11, pages=3)], "minutes_read": True,
                 "minutes_printed_date": "2024-11-04",
                 "attendance": {"present": [{"name": "Alpha"}, {"name": "Beta"}, {"name": "Gamma", "note": "arrived late"}],
                                "absent": [], "page": 1, "source_id": "src-000000000011", "confirmed": True}},
                {"id": "2024-11-25-finance", "committee": "finance", "body": "Finance Committee", "date": "2024-11-25",
                 "title": "Finance Committee Meeting", "event_id": 2, "cancelled": False, "video_url": None,
                 "documents": [doc("agenda", 12)], "minutes_read": False, "minutes_printed_date": None,
                 "attendance": None},
                {"id": "2025-01-27-finance", "committee": "finance", "body": "Finance Committee", "date": "2025-01-27",
                 "title": "Finance Committee Meeting", "event_id": 4, "cancelled": False, "video_url": None,
                 "documents": [], "minutes_read": False, "minutes_printed_date": None, "attendance": None},
                {"id": "2024-10-30-audit", "committee": "audit", "body": "Audit Committee", "date": "2024-10-30",
                 "title": "Audit Committee Meeting", "event_id": 3, "cancelled": False, "video_url": None,
                 "documents": [doc("agenda", 20, stored=False), doc("minutes", 21, pages=2)], "minutes_read": True,
                 "minutes_printed_date": "2023-10-30", "attendance": None}],
            "motions": [
                motion(fin, 1, 2, "to adopt Resolution 1-2024-25",
                       {"method": "voice vote", "outcome": "passed", "outcome_printed": "A voice vote was taken."}),
                motion(fin, 2, 2, "to approve the minutes",
                       {"method": "voice vote", "outcome": "passed", "outcome_printed": "x",
                        "nays_printed": ["Councilman Gamma"]}),
                motion(fin, 3, 3, "to adopt the plan", {"method": "unanimous", "outcome": "passed",
                                                        "outcome_printed": "The motion was approved unanimously."}),
                motion(fin, 4, 3, "to postpone", None, confirmed=False),
                motion(fin, 5, 3, None, {"method": "voice vote", "outcome": "passed", "outcome_printed": None},
                       section=None, subject_printed=None, words_note=cm_mod.WORDS_NOTE,
                       words_withheld=["section", "subject_printed", "motion_printed", "outcome_printed"])]}


# The fixture's allow-list (made-up roster): the words rule restated by site_checks reads it instead of the real one
WORDS_YML = """officials:
- {name: Ann Alpha, surname: Alpha, source: committee}
- {name: Bo Beta, surname: Beta, source: committee}
- {name: Cy Gamma, surname: Gamma, source: committee}
titles: [Councilman, Councilwoman]
words: [action, adopt, the, approve, minutes, plan, postpone, resolution, a, as, printed, voice, vote, was, taken,
  motion, approved, unanimously, x, arrived, late, to, finance, audit, committee, meeting, agenda]
lowercase_only: []
phrases: []
"""


def built(tmp_path_factory, hold):
    root = tmp_path_factory.mktemp(f"cm-{hold}")
    p = root / "committees.json"
    p.write_text(json.dumps(facts(hold)), encoding="utf-8")
    cfg = {**cm_mod.load_config(), "facts_path": p, "hold_motions": hold}
    out = root / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, today=TODAY, city_committees=cfg)
    return out


@pytest.fixture(scope="module")
def held(tmp_path_factory):
    return built(tmp_path_factory, True)


@pytest.fixture(scope="module")
def open_(tmp_path_factory):
    return built(tmp_path_factory, False)


def main_of(path) -> str:
    return path.read_text(encoding="utf-8").split("<main", 1)[1].split("</main>")[0]


def blocks(html):
    return {b["id"]: (bool(b["nc"]), b["body"]) for b in site_checks.CM_BLOCK.finditer(html)}


def test_pages_are_built_per_committee(held):
    for folder in ("city-finance-committee", "city-audit-committee"):
        assert (held / folder / "index.html").is_file()
    assert (held / "city-finance-committee" / "meetings" / "2024.html").is_file()
    home = main_of(held / "city-finance-committee" / "index.html")
    assert "<h1>Finance Committee</h1>" in home and "City of Clarksville" in home
    assert "1 meeting has no minutes posted." in home and "minutes read for 1 meeting." in home


def test_held_motions_show_words_not_confirmed_and_no_vote(held):
    html = (held / "city-finance-committee" / "meetings" / "2024.html").read_text(encoding="utf-8")
    bs = blocks(html)
    assert len(bs) == 5 and all(nc for nc, _ in bs.values())
    for nc, body in bs.values():
        assert "Not confirmed" in body and "#page=" in body
        assert escape(cm_mod.HELD_NOTE) in body and "hard to read" not in body
        assert not any(w in body for w in site_checks.CM_NC_WORDS)
    assert "to adopt Resolution 1-2024-25" in bs["2024-11-04-finance-motion-1"][1]


def test_open_confirmed_voice_vote_is_never_per_member(open_):
    html = (open_ / "city-finance-committee" / "meetings" / "2024.html").read_text(encoding="utf-8")
    bs = blocks(html)
    nc, body = bs["2024-11-04-finance-motion-1"]
    assert not nc and "Moved by <span data-item-title>Councilman Alpha</span>, seconded by" in body
    assert '<strong class="label">Voice vote (not recorded by name):</strong> passed.' in body
    assert cm_mod.VOICE_VOTE == "Voice vote (not recorded by name)" and "Outcome" not in body
    assert "Voted aye" not in body and "Voted nay" not in body
    # a printed dissent is shown as printed, and only that name
    assert "Voted nay (as printed): <span data-item-title>Councilman Gamma</span>." in bs["2024-11-04-finance-motion-2"][1]
    # "unanimous" only in the minutes' own words
    body3 = bs["2024-11-04-finance-motion-3"][1]
    assert "<span data-item-title>The motion was approved unanimously.</span>" in body3
    assert re.sub(r"<span data-item-title>.*?</span>", "", body3).count("unanimous") == 0
    # not confirmed by the reader: no vote content
    nc4, body4 = bs["2024-11-04-finance-motion-4"]
    assert nc4 and "Moved by" not in body4 and "Outcome" not in body4 and escape(cm_mod.NOT_READ_NOTE) in body4
    # attendance as printed with the note, linked to its minutes page
    assert "Present: <span data-item-title>Alpha, Beta, Gamma (arrived late)</span>." in html
    assert "Absent: <span data-item-title>none</span>." in html


def test_withheld_words_show_the_note_and_the_minutes_link(held, open_):
    from collector.committee_words import WORDS_NOTE
    assert cm_mod.WORDS_NOTE == WORDS_NOTE
    for site in (held, open_):
        body = blocks((site / "city-finance-committee" / "meetings" / "2024.html").read_text(encoding="utf-8"))[
            "2024-11-04-finance-motion-5"][1]
        assert cm_mod.WORDS_NOTE in body and "#page=" in body
        assert 'class="motion-item"' not in body and "as printed:" not in body
    # with the hold off it is a confirmed voice vote: the outcome is still shown, in our words
    body = blocks((open_ / "city-finance-committee" / "meetings" / "2024.html").read_text(encoding="utf-8"))[
        "2024-11-04-finance-motion-5"][1]
    assert '<strong class="label">Voice vote (not recorded by name):</strong> passed.' in body


def test_agenda_only_and_other_date_meetings(held):
    fin = main_of(held / "city-finance-committee" / "meetings" / "2024.html")
    sec = fin.split('id="2024-11-25-finance"', 1)[1]
    assert "Minutes: <span class=\"doc-note\">not posted on the city's portal</span>" in sec
    assert "Minutes not posted on the city's portal; the agenda is linked above." in sec
    aud = main_of(held / "city-audit-committee" / "meetings" / "2024.html")
    assert "print the date October 30, 2023" in aud and "nothing read from them is shown here" in aud
    assert "listed by the city; not collected yet" in aud
    assert "cm-motion" not in aud and "Present:" not in aud


def test_official_record_and_committees_page(held):
    page = (held / "city-finance-committee" / "index.html").read_text(encoding="utf-8")
    assert 'data-ext="record" href="https://clarksvilletn.portal.civicclerk.com/"' in page
    cp = main_of(held / "committees.html")
    assert '<a href="city-finance-committee/index.html">City of Clarksville Finance Committee</a>' in cp
    assert '<a href="city-audit-committee/index.html">City of Clarksville Audit Committee</a>' in cp


def test_search_index_lists_committee_meetings(held):
    js = (held / "static" / "search-index.js").read_text(encoding="utf-8")
    idx = json.loads(js.split("=", 1)[1].rstrip().rstrip(";"))
    recs = [r for r in idx["records"] if r["b"] in ("city-finance-committee", "city-audit-committee")]
    assert len(recs) == 4 and {r["k"] for r in recs} == {"meeting"}
    assert any(r["h"] == "city-finance-committee/meetings/2024.html#2024-11-04-finance" for r in recs)
    assert {"key": "city-finance-committee", "label": "City of Clarksville Finance Committee"} in idx["bodies"]


def qa_cm(tmp_path, hold=True, **over):
    words = tmp_path / "committee-words.yml"
    words.write_text(WORDS_YML, encoding="utf-8")
    return {**facts(hold), "_held": hold, "_words": words,
            "_cfg": {"pages": [{"folder": "city-finance-committee", "committee": "finance"}]}, **over}


def tampered(site, tmp_path, mid, old, new):
    import shutil
    bad = tmp_path / f"bad-{abs(hash((mid, old, new)))}"
    shutil.copytree(site, bad, dirs_exist_ok=True)
    page = bad / "city-finance-committee" / "meetings" / "2024.html"
    text = page.read_text(encoding="utf-8")
    i = text.index(f'id="{mid}"')
    assert old in text[i:]
    page.write_text(text[:i] + text[i:].replace(old, new, 1), encoding="utf-8")
    return bad


def test_qa_check_catches_a_confirmed_block_while_held(held, open_, tmp_path):
    pages = {"city-finance-committee/meetings/2024.html": None}
    problems, note = site_checks.check_committee_motions(held, pages, qa_cm(tmp_path))
    assert problems == [] and "pass the committee words rule" in note
    problems, _ = site_checks.check_committee_motions(open_, pages, qa_cm(tmp_path))
    assert any("while hold_motions is on" in p for p in problems)
    # one block per motion in the record
    cm = qa_cm(tmp_path)
    extra = {**cm, "motions": cm["motions"] + [{**cm["motions"][0], "id": "2024-11-04-finance-motion-9"}]}
    problems, _ = site_checks.check_committee_motions(held, pages, extra)
    assert any("5 committee motion blocks on the pages, 6 motions" in p for p in problems)


@pytest.mark.parametrize("mid, old, new, want", [
    # a withheld motion that shows an item or words "as printed", or loses its note
    ("2024-11-04-finance-motion-5", "<strong>Motion</strong>",
     '<p class="motion-item">x</p><strong>Motion</strong>, as printed: <span data-item-title>x</span>', "withholds"),
    ("2024-11-04-finance-motion-5", cm_mod.WORDS_NOTE, "", "no note on the page"),
    # words not on the allow-list (made-up names), in any block, in any case
    ("2024-11-04-finance-motion-1", "to adopt Resolution 1-2024-25", "to approve payment to Zelda Quarmby",
     "words rule does not allow"),
    ("2024-11-04-finance-motion-1", "to adopt Resolution 1-2024-25", "to approve payment to zelda quarmby",
     "words rule does not allow"),
    ("2024-11-04-finance-motion-1", "RESOLUTION 1-2024-25 A Resolution as printed",
     "RESOLUTION 1-2024-25 A Resolution accepting land from Zelda Quarmby", "words rule does not allow"),
    # a voice vote in other words than the fixed ones, or with another outcome
    ("2024-11-04-finance-motion-1", "Voice vote (not recorded by name):</strong> passed.",
     "Voice vote:</strong> passed.", "not shown once as"),
    ("2024-11-04-finance-motion-1", "Voice vote (not recorded by name):</strong> passed.",
     "Voice vote (not recorded by name):</strong> failed.", "not shown once as"),
    # a name not on the roster as mover, and in the attendance
    ("2024-11-04-finance-motion-2", "Councilman Alpha", "Mr. Quarmby", "name that the committee words rule"),
    ("2024-11-04-finance-attendance", "Alpha, Beta", "Alpha, Zelda Quarmby", "attendance shows name"),
    ("2024-11-04-finance-attendance", "(arrived late)", "(with Zelda Quarmby)", "attendance shows words"),
])
def test_qa_words_rule_fails_tampered_pages(held, open_, tmp_path, mid, old, new, want):
    site = open_ if mid.endswith(("motion-2",)) or "Voice vote" in old else held
    pages = {"city-finance-committee/meetings/2024.html": None}
    bad = tampered(site, tmp_path, mid, old, new)
    problems, _ = site_checks.check_committee_motions(bad, pages, qa_cm(tmp_path, hold=site is held))
    assert any(want in p for p in problems), problems


@pytest.mark.parametrize("where", ["motion", "meeting", "listing", "manifest"])
def test_qa_checks_every_string_of_the_committee_data_not_only_the_pages(held, tmp_path, where):
    """A name in a field no page renders (a new key in committees.json, a listing title, a manifest label) still
    fails QA (committees-privacy hit 3, L5), and the problem names the field, never the text."""
    pages = {"city-finance-committee/meetings/2024.html": None}
    cm = qa_cm(tmp_path)
    listing, manifest = tmp_path / "listing.json", tmp_path / "manifest.json"
    rows = [{"id": "2024-11-04-finance", "title": "Finance Committee Meeting", "body": "Finance Committee",
             "kind": "finance", "agenda_name": "Agenda", "minutes_name": "Minutes"}]
    labels = [{"label": "Finance Committee: Finance Committee Meeting (agenda)", "kind": "agenda"}]
    if where == "motion":
        cm["motions"][0] = {**cm["motions"][0], "remark": "Zelda Quarmby"}
    elif where == "meeting":
        cm["meetings"][1] = {**cm["meetings"][1], "title": "Finance Committee: Zelda Quarmby claim"}
    elif where == "listing":
        rows[0]["title"] = "Finance Committee Meeting re Zelda Quarmby"
    else:
        labels[0]["label"] = "Finance Committee: Zelda Quarmby (agenda)"
    listing.write_text(json.dumps(rows), encoding="utf-8")
    manifest.write_text(json.dumps(labels), encoding="utf-8")
    problems, _ = site_checks.check_committee_motions(held, pages, {**cm, "_listing": listing, "_manifest": manifest})
    assert len(problems) == 1 and "Quarmby" not in problems[0], problems
    assert ("listing.json" if where == "listing" else "manifest.json" if where == "manifest" else "committees.json") \
        in problems[0]


def test_a_real_committees_file_is_never_built_beside_fixture_facts_and_vice_versa(tmp_path):
    p = tmp_path / "committees.json"
    p.write_text(json.dumps({**facts(), "fixture": False}), encoding="utf-8")
    cfg = {**cm_mod.load_config(), "facts_path": p}
    assert cm_mod.load(cfg, fixture=True) == []
    p.write_text(json.dumps(facts()), encoding="utf-8")
    with pytest.raises(cm_mod.CommitteesError):
        cm_mod.load(cfg, fixture=False)


def test_hold_from_either_switch(tmp_path):
    p = tmp_path / "committees.json"
    p.write_text(json.dumps(facts(hold=True)), encoding="utf-8")
    cs = cm_mod.load({**cm_mod.load_config(), "facts_path": p, "hold_motions": False}, fixture=True)
    assert all(c.held for c in cs)


def test_city_hub_cards_turn_present_when_the_pages_are_built(tmp_path):
    from sitegen import bodies, config, views

    class Council:
        slug, tx = "city", None

        def home_href(self):
            return "city/index.html"

        def meeting_years(self):
            return ["2024"]

    p = tmp_path / "committees.json"
    p.write_text(json.dumps(facts()), encoding="utf-8")
    cms = cm_mod.load({**cm_mod.load_config(), "facts_path": p}, fixture=True)
    for built_, want in ((cms, False), ((), True)):
        sw = bodies.build({"nav": []}, [Council()], None, committees=built_)
        cards = {c["key"]: c for c in sw["hubs"]["city"]["cards"]}
        for key, folder in (("finance-committee", "city-finance-committee"), ("audit-committee", "city-audit-committee")):
            assert cards[key]["coming"] is want
            if not want:
                assert cards[key]["href"] == f"{folder}/index.html" and cards[key]["go"] == "Meetings by year"
                assert "not collected" not in cards[key]["text"]
        # the landing's "Public money" door names a committee as coming only while its card is coming
        names = [x["label"] for g in views.door_coming({"switch": sw}, "money") for x in g["links"]]
        assert ("Finance Committee" in names) is want
    assert config.SITE["city_committees"]["url"] in site_checks.allowed_external(config.SITE, None, None)



def test_an_upcoming_meeting_says_so_and_claims_nothing_is_missing(held):
    sec = main_of(held / "city-finance-committee" / "meetings" / "2025.html").split('id="2025-01-27-finance"', 1)[1]
    assert '<span class="chip chip-status">Upcoming</span>' in sec and "not posted" not in sec
    assert "An upcoming meeting: its minutes are posted after it is held." in sec
    home = main_of(held / "city-finance-committee" / "index.html")
    assert "2 meetings and 1 upcoming" in home and "November 25, 2024</span>:" in home
