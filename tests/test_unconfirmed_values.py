"""SHOW_UNCONFIRMED_VALUES (sitegen/config.py; Brain Trust round 2, CEO confirmed False on 2026-11-07, link only).

False (default): an unconfirmed roll call shows no parsed value on any public page or in the public export. Each vote
and the outcome read "Not confirmed*" with the note and the source-page link; no bar, no tally; official pages count
unconfirmed roll calls without a Yes/No breakdown. review.html and --internal exports keep everything.
True: values are shown, starred (the rest of this behaviour is tested in test_held_counts.py).
"""
import copy
import csv
import io
import json
import re
from html import unescape

import pytest

from collector.export import export
from qa import site_checks
from sitegen import config, views
from test_held_counts import NOTE, text_of
from test_site_review_fixes import MEETING_DEC, RC_HELD, RC_SHOWN, build_pages, by_id, public

VALUE = site_checks.PARSED_VALUE  # "Yes*", "Passed*", "2 yes" ...


@pytest.fixture(params=[False, True], ids=["values-hidden", "values-shown"])
def switch(request, monkeypatch):
    monkeypatch.setattr(config, "SHOW_UNCONFIRMED_VALUES", request.param)
    return request.param


def _texts(pages, facts):
    """Text of every block and row that shows RC_HELD: meeting block, item event, each voter's history row."""
    out = {"meeting": text_of(pages[f"meetings/{MEETING_DEC}.html"], RC_HELD)}
    ev = next(e["id"] for e in facts["item_events"] if e["ref"] == RC_HELD)
    out["item"] = text_of(pages["items/2024.html"], ev, "data-fact-id")
    for v in by_id(facts, "roll_calls", RC_HELD)["votes"]:
        out[v["official_id"]] = text_of(pages[f"officials/{v['official_id']}.html"], f"{RC_HELD}/{v['official_id']}",
                                        "data-fact-id")
    return out


def test_default_is_link_only():
    assert config.SHOW_UNCONFIRMED_VALUES is False


def test_unconfirmed_roll_call_shows_values_only_when_switched_on(tmp_path, facts, switch):
    pages = build_pages(tmp_path, copy.deepcopy(facts))
    rc = by_id(facts, "roll_calls", RC_HELD)
    link = f'https://example.invalid/fixture/minutes-2024-12.pdf#page={rc["page"]}'
    for where, text in _texts(pages, facts).items():
        assert NOTE in text and "Read it yourself" in text, where
        if switch:
            assert VALUE.search(text), where
        else:
            assert not VALUE.search(text), (where, VALUE.search(text).group(0))
            assert "Not confirmed*" in text, where
    assert link in pages[f"meetings/{MEETING_DEC}.html"]
    block = pages[f"meetings/{MEETING_DEC}.html"]
    block = block[block.index(f'id="{RC_HELD}"'):]
    block = block[:block.index("</article>")]
    assert ('class="bar"' in block) == switch
    if not switch:
        assert block.count("Not confirmed") >= len(rc["votes"]) + 1  # every vote, plus the outcome
        assert "Outcome:" in unescape(re.sub(r"<[^>]+>", "", block))


def test_confirmed_roll_call_is_unchanged_by_the_switch(tmp_path, facts, switch):
    pages = build_pages(tmp_path, copy.deepcopy(facts))
    text = text_of(pages[f"meetings/{MEETING_DEC}.html"], RC_SHOWN)
    assert "*" not in text and NOTE not in text and re.search(r"\d+ yes", text)
    out = views.Index(facts).outcome(by_id(facts, "roll_calls", RC_SHOWN))
    assert out["label"] in config.OUTCOME_LABELS.values() and out["tally"]


def test_official_page_counts_unconfirmed_roll_calls_without_a_breakdown(tmp_path, facts, switch):
    pages = build_pages(tmp_path, copy.deepcopy(facts))
    sentence = views.totals_sentences(views.Index(facts), "a-example")[1]
    page = unescape(pages["officials/a-example.html"])
    if switch:
        assert "1 Yes*, 0 No*" in sentence and "Yes*: 1" in re.sub(r"<[^>]+>", "", page)   # legend numbers carry data-n
    else:
        assert sentence == ("Roll call votes, 2024-10-07 to 2024-12-09: 3 Yes, 0 No, 0 Abstain, 0 Other confirmed; "
                            "1 vote in not confirmed* roll calls, see each page.")
        assert "Yes*" not in page and "No*" not in page


def test_no_public_page_shows_an_unconfirmed_value_when_off(tmp_path, facts, switch):
    """The QA check that guards it passes on a clean build under either setting (it reads the same switch)."""
    pages = build_pages(tmp_path, copy.deepcopy(facts))
    site = tmp_path / "build" / "site"
    assert not site_checks.check_unverified(site, {k: site_checks.parse(site / k) for k in pages}, facts, True)
    if not switch:
        for name, html in public(pages).items():
            if name != "about.html":
                assert "Yes*" not in unescape(re.sub(r"<[^>]+>", "", html)), name


def test_qa_catches_a_value_on_an_unconfirmed_roll_call(tmp_path, facts):
    pages = build_pages(tmp_path, copy.deepcopy(facts))
    site = tmp_path / "build" / "site"
    p = site / "meetings" / f"{MEETING_DEC}.html"
    t = p.read_text(encoding="utf-8")
    at = t.index(f'id="{RC_HELD}"')
    i = t.index("Not confirmed<span", at)
    p.write_text(t[:i] + "Yes<span" + t[i + len("Not confirmed<span"):], encoding="utf-8")
    problems = site_checks.check_unverified(site, {k: site_checks.parse(site / k) for k in pages}, facts, True,
                                            show_values=False)
    assert any("parsed value" in x for x in problems), problems


def test_review_page_keeps_everything(tmp_path, facts):
    pages = build_pages(tmp_path, copy.deepcopy(facts))
    rc = by_id(facts, "roll_calls", RC_HELD)
    assert rc["outcome_text"] in unescape(pages["review.html"])


def test_export_follows_the_switch(tmp_path, facts, switch):
    export(copy.deepcopy(facts), tmp_path / "pub")
    export(copy.deepcopy(facts), tmp_path / "int", internal=True)
    for kind in ("pub", "int"):
        data = json.loads((tmp_path / kind / "data" / "facts.json").read_text(encoding="utf-8"))
        rc = by_id(data, "roll_calls", RC_HELD)
        hidden = kind == "pub" and not switch
        assert rc["confirmed"] is False and all(v["confirmed"] is False for v in rc["votes"])
        assert all((v["value"] is None) == hidden for v in rc["votes"]), kind
        assert (rc["outcome"] is None) == hidden and (rc["stated_tally"] is None) == (hidden or rc["stated_tally"] is None)
        rows = [r for r in csv.DictReader(io.StringIO((tmp_path / kind / "data" / "votes.csv").read_text(encoding="utf-8")))
                if r["roll_call_id"] == RC_HELD]
        assert rows and all((r["value"] == "") == hidden for r in rows), kind
        ok = by_id(data, "roll_calls", RC_SHOWN)
        assert ok["outcome"] and all(v["value"] for v in ok["votes"])


def test_about_text_follows_the_switch(tmp_path, facts, switch):
    pages = build_pages(tmp_path, copy.deepcopy(facts))
    para = next(p for p in re.findall(r"<p>(.*?)</p>", pages["about.html"], re.S) if "not confirmed" in p)
    hidden = ("but no vote, outcome or tally the program read from it is shown: each vote and the outcome read "
              "&ldquo;Not confirmed*&rdquo;, here and in the data files below.")
    assert (hidden in para) != switch
    assert ("2 Yes* not confirmed" in para) == switch


CLAUSE = "The foregoing Resolution was Adopted by the following roll call vote:"


def test_an_unconfirmed_roll_call_has_no_vote_on(tmp_path, facts, switch):
    """neutrality/unconfirmed-vote-on-untested: "Vote on" is derived from the outcome clause, which is a value the
    program read, so a roll call that is not confirmed never shows one, on any page or in the public or internal
    export, whatever SHOW_UNCONFIRMED_VALUES says. The same clause on a confirmed roll call does show it."""
    f = copy.deepcopy(facts)
    for rc in f["roll_calls"]:
        rc["outcome_text"] = CLAUSE
    assert views.outcome_kind_label(CLAUSE) == "Resolution"
    pages = build_pages(tmp_path, f)
    for where, text in _texts(pages, f).items():
        assert "Vote on" not in text, where
    held = by_id(f, "roll_calls", RC_HELD)
    year = held["meeting_id"][:4]
    assert "Vote on" not in text_of(pages[f"votes/{year}.html"], RC_HELD, "data-fact-id")
    assert "Vote on: Resolution." in text_of(pages[f"meetings/{MEETING_DEC}.html"], RC_SHOWN)
    assert "Vote on: Resolution." in text_of(pages[f"votes/{year}.html"], RC_SHOWN, "data-fact-id")
    for kind, internal in (("pub", False), ("int", True)):
        export(copy.deepcopy(f), tmp_path / kind, internal=internal)
        data = json.loads((tmp_path / kind / "data" / "facts.json").read_text(encoding="utf-8"))
        assert by_id(data, "roll_calls", RC_HELD)["vote_on"] is None, kind
        assert by_id(data, "roll_calls", RC_SHOWN)["vote_on"] == "Resolution", kind
        rows = {r["id"]: r for r in csv.DictReader(io.StringIO(
            (tmp_path / kind / "data" / "roll_calls.csv").read_text(encoding="utf-8")))}
        assert rows[RC_HELD]["vote_on"] == "" and rows[RC_SHOWN]["vote_on"] == "Resolution", kind
