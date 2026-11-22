# ruff: noqa: E501
"""note-titles (2026-11-22, the owner on the Sunrise sample: "nothing letting me know why I should care"): a subject
that says what is inside, counted from the edition's own entries by the site's topic rule and written only in config
phrases (common.compose; the deliver stage reads it back, deliver.subject_ok); a topic kicker over each card and the
record's title as its headline; a vote titled from its meeting's agenda cites that agenda. FIXTURE notes only."""
import copy
import dataclasses
import random
import re

import pytest

from sitegen import config, morning
from sender import common, deliver, plan as plan_mod, render
from sender import settings as settings_mod
from test_morning import D, inputs  # noqa: F401
from test_morning_sender_plan import SITE_URL, cfg_with, msite, read_note, site_with  # noqa: F401
from test_morning_sender_render import CTX, HOSTILE, cards, entry, head_raw, links, note_of, titles, vote
from test_site_neutrality import BANNED

TEXT = config.SITE["morning_note"]["sender"]["text"]
PLACE = config.SITE["today_place"]
TAIL = TEXT["subject_topics"].replace("{topics}", "").replace("{place}", PLACE)       # ": your <place> morning note"
DAY = D.isoformat()
AGENDA_URL = "https://example.com/fixture/agenda-2026-09-03.pdf"


def ok(html: str) -> bool:
    return deliver.body_ok(html, CTX["link_hosts"], CTX["link_urls"])


def subj(*entries, coming=None, ctx=CTX) -> str:
    return render.subject(ctx, DAY, list(entries), coming)


def rpc_case(n: int, kind="agenda_item", **kw) -> dict:
    return entry(**{"id": f"rpc/{kind}/{n}", "kind": kind, "body": "rpc", "body_name": "Fixture Planning",
                    "lists": ["zoning"], "title": f"CZ-{n}-2026: FIXTURE request", "case": f"CZ-{n}-2026", **kw})


def solicitation(n: int) -> dict:
    return entry(id=f"contracts/solicitation/{n}", kind="solicitation", body="contracts", lists=["contracts"],
                 meeting_date=None, meeting=None, title=f"FIXTURE bid {n}", recorded="New on the purchasing archive",
                 href=f"contracts/b{n}.html", source={"url": f"https://example.com/fixture/bid{n}.pdf", "page": None})


def agenda_vote(n: int, page: int, caption: str, url=AGENDA_URL, apage=3, **kw) -> dict:
    """A council vote whose minutes printed no title, titled from its meeting's agenda: the facts' item.title_source
    (claude/note-titles-captions, aca44d8d: {kind "agenda", source_id, page, meeting_id}) as the note carries it,
    with the agenda page's URL (sitegen.morning._title_source)."""
    return vote(n, page, title=f"ORDINANCE {n}-2026-27: {caption}", title_ours=False, untitled=False,
                title_source={"kind": "agenda", "source_id": "src-agenda-fixture", "page": apage,
                              "meeting_id": "2026-09-03-regular", "url": f"{url}#page={apage}" if url else url}, **kw)


def today_row(day=DAY) -> dict:
    return {"date": day, "body": "Fixture Council", "meeting": "regular session", "href": f"today.html#d-{day}"}


# ------------------------------------------------------------------ the topic rule
def test_topics_follow_the_sites_rules_and_never_a_title_we_made():
    assert render.topics(CTX, rpc_case(1)) == ("rezoning",)                                     # the zoning list
    assert render.topics(CTX, solicitation(1)) == ("contracts",)                                # the contracts list
    assert render.topics(CTX, entry(lists=["budget"], title="FIXTURE: paving")) == ("budget",)  # the budget list
    assert render.topics(CTX, vote(1, 2, untitled=False)) == ("ordinance",)                     # number prefix
    assert render.topics(CTX, entry(lists=["seats"], title="FIXTURE: appoint members")) == ("appointment",)
    # several at once, in the fixed order; "zoning" in the title is the item type rule's rezoning word
    e = entry(lists=["seats", "budget"], item_number="ORDINANCE 9-2026-27", title="FIXTURE amending the zoning code")
    assert render.topics(CTX, e) == ("rezoning", "budget", "ordinance")
    # our fallback words are never read for a topic, the item's own number still is
    assert render.topics(CTX, entry(lists=["seats"], title="Resolution of the budget", title_ours=True)) == ()
    assert render.topics(CTX, vote(1, 2)) == ("ordinance",)


def test_each_item_counts_once_under_its_first_topic():
    two_readings = [vote(1, 2, untitled=False), vote(1, 7, untitled=False, id="city/vote/rc-second", meeting_date="2026-10-01")]
    on_both = [rpc_case(4), rpc_case(4, kind="vote", id="rpc/vote/4b")]            # agenda and minutes: one case
    budget_ord = entry(id="b", lists=["budget"], item_number="ORDINANCE 8-2026-27", title="FIXTURE amending the budget")
    got = render.topic_counts(CTX, two_readings + on_both + [budget_ord, solicitation(1), solicitation(2)])
    assert got == {"ordinance": 1, "rezoning": 1, "budget": 1, "contracts": 2}
    # a solicitation's later documents are that one listing (real data, 2026-11-16: a bid tab and an award letter
    # of one solicitation, and a new solicitation, are two listings)
    docs = [entry(id=f"contracts/document/7/{d}", lists=["contracts"], title="FIXTURE: Bid Tab") for d in (1, 2)]
    assert render.topic_counts(CTX, docs + [solicitation(1)]) == {"contracts": 2}


# ------------------------------------------------------------------ the subject
def test_the_subject_names_the_top_topics_most_first_with_plurals():
    es = [rpc_case(n) for n in (1, 2, 3)] + [entry(id="b1", lists=["budget"])] + [solicitation(n) for n in (1, 2)]
    assert subj(*es) == f"3 zoning cases and 2 contract listings{TAIL}"         # a third would pass the cap
    three = [rpc_case(1), rpc_case(2), entry(id="b1", lists=["budget"]), vote(3, 4, untitled=False)]
    assert subj(*three) == f"2 zoning cases, a budget item and an ordinance{TAIL}"
    assert subj(solicitation(1)) == f"A contract listing{TAIL}"                     # one: the _one phrase, upper case first
    assert subj(rpc_case(1), entry(id="b1", lists=["budget"])) == f"A zoning case and a budget item{TAIL}"


def test_ties_go_in_the_fixed_order_and_at_most_three_topics():
    es = [vote(n, n, untitled=False) for n in (1, 2)] + [solicitation(n) for n in (1, 2)] + \
        [entry(id=f"a{n}", lists=["seats"], title=f"FIXTURE appoint {n}") for n in (1, 2)] + \
        [entry(id=f"r{n}", lists=["seats"], item_number=f"RESOLUTION {n}", title="FIXTURE") for n in (1, 2)]
    assert subj(*es) == f"2 contract listings and 2 ordinances{TAIL}"          # the third passes the cap
    short = [entry(id="b1", lists=["budget"]), entry(id="b2", lists=["budget"]), vote(3, 4, untitled=False),
             entry(id="a1", lists=["seats"], title="FIXTURE appoint"), entry(id="r1", lists=["seats"], item_number="RESOLUTION 1")]
    assert subj(*short) == f"2 budget items, an ordinance and a resolution{TAIL}"     # 1-1-1 tie: fixed order, three


def test_a_long_subject_drops_whole_phrases_within_the_cap():
    ctx = {**CTX, "place": "Clarksville Area"}
    es = [rpc_case(n) for n in range(12)] + [entry(id=f"b{n}", lists=["budget"]) for n in range(11)] + \
        [solicitation(n) for n in range(10)]
    s = subj(*es, ctx=ctx)       # the third phrase would pass the cap: it is left out whole
    assert s == "12 zoning cases and 11 budget items: your Clarksville Area morning note"
    assert len(s) <= common.SUBJECT_CAP
    for n in range(1, 30):          # whatever the counts, never over the cap and never a cut word
        r = random.Random(n)
        many = [rpc_case(k) for k in range(r.randint(0, 999))] + [solicitation(k) for k in range(r.randint(0, 30))] + \
            [entry(id=f"b{k}", lists=["budget"]) for k in range(r.randint(0, 30))]
        s = subj(*many, ctx=ctx) if many else ""
        assert len(s) <= common.SUBJECT_CAP and not s.endswith(common.CUT)


def test_no_topic_gives_the_record_count_and_nothing_fitting_gives_the_days_template():
    plain = [entry(id=f"o{n}", lists=["seats"], title="FIXTURE: approval of the agenda") for n in range(4)]
    assert subj(*plain) == f"4 new records{TAIL}"
    assert subj(plain[0]) == f"A new record{TAIL}"
    long_place = {**CTX, "place": "P" * 70}
    assert subj(rpc_case(1), ctx=long_place) == render.subject(CTX, DAY) == f"{config.SITE['site_name']} morning note, November 11, 2026"
    assert render.subject(CTX, DAY, []) == render.subject(CTX, DAY)


def test_a_meeting_today_leads_when_it_fits_and_never_moves_a_topic_out():
    es = [rpc_case(1), rpc_case(2)]
    later = [today_row("2026-12-03")]
    assert subj(*es, coming=later) == subj(*es)
    s = subj(*es, coming=[today_row()])
    assert s == f"A meeting today · 2 zoning cases{TAIL}"
    assert subj(*es, coming=[today_row(), today_row()]).startswith("2 meetings today · ")
    assert common.claim_subject(s) == subj(*es)
    full = [rpc_case(n) for n in range(12)] + [entry(id=f"b{n}", lists=["budget"]) for n in range(11)] + \
        [solicitation(n) for n in range(10)]
    assert subj(*full, coming=[today_row()]) == subj(*full)            # no room: the topics stay, the lead goes


@pytest.mark.parametrize("seed", range(200))
def test_every_subject_reads_back_and_never_names_a_government(seed):
    r = random.Random(seed)
    counts = {k: r.choice([0, 0, 1, 2, 9, 17, 120]) for k in common.TOPICS}
    entries = r.randint(1, 400)
    meetings = r.randint(0, 3)
    s = common.compose(TEXT, config.SITE["site_name"], PLACE, DAY, counts, entries, meetings)
    assert not render.AUTHORITY.search(s) and BANNED.search(s) is None
    if s != render.subject(CTX, DAY):
        counted, today = common.subject_parse(s, TEXT, PLACE)
        assert today == (meetings if common.SUBJECT_SEP in s else 0)
        assert all(counts.get(k, entries if k == "records" else 0) == n for k, n in counted)
        assert len(s) <= common.SUBJECT_CAP


def test_a_phrase_naming_a_government_body_fails_the_plan_and_the_build(msite):  # noqa: F811
    cfg = cfg_with()
    cfg["morning_note"]["sender"]["text"]["subject_topics"] = "{topics}: your county morning note"
    with pytest.raises(plan_mod.PlanError, match="official"):
        plan_mod.build(msite, D, cfg)
    assert any("subject_topics must not name a government body" in p for p in morning.problems(cfg))


@pytest.mark.parametrize("key, value, problem", [
    ("subject_budget_one", "a budget item, or two", "must not hold"),
    ("subject_budget_many", "{n} budget and money items", "must not hold"),
    ("subject_today_one", "today · a meeting", "must not hold"),
    ("subject_budget_one", "an ordinance", "read as that phrase only"),
    ("subject_budget_many", "{n} ordinances", "read as that phrase only"),
    ("subject_records_many", "new records", "must contain {n}"),
    ("subject_topics", "your {place} morning note", "must contain {topics}"),
    ("subject_and", "and also", "must be one word"),
    ("subject_contracts_one", "a CMCSS listing", "must not name a government body"),
])
def test_the_build_refuses_phrases_the_deliver_stage_could_not_read_back(key, value, problem):
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"]["sender"]["text"][key] = value
    assert any(problem in p for p in morning.problems(cfg)), morning.problems(cfg)


def test_the_shipped_phrases_pass_and_every_one_is_read_by_the_deliver_stage():
    assert common.subject_problems(TEXT, PLACE) == []
    assert not [p for p in morning.problems(config.SITE) if "subject" in p]
    s = settings_mod.load(config.REPO_ROOT / "config" / "site.yml")
    assert dict(s.subject_text) == {k: TEXT[k] for k in common.SUBJECT_KEYS} and s.place == PLACE
    assert common.COMING_N == morning.COMING_N
    for k in common.SUBJECT_KEYS:
        assert BANNED.search(TEXT[k]) is None and not render.AUTHORITY.search(TEXT[k].replace("{place}", PLACE))


# ------------------------------------------------------------------ the deliver stage reads the subject back
SETTINGS = settings_mod.load(config.REPO_ROOT / "config" / "site.yml")


def good(n=3) -> str:
    return common.compose(TEXT, config.SITE["site_name"], PLACE, DAY, {"rezoning": 2, "budget": 1}, n, 1)


def test_deliver_accepts_what_render_writes():
    assert deliver.subject_ok(SETTINGS, DAY, good(), 3)
    assert deliver.subject_ok(SETTINGS, DAY, common.claim_subject(good()), 3)
    assert deliver.subject_ok(SETTINGS, DAY, render.subject(CTX, DAY), 1)
    assert deliver.subject_ok(SETTINGS, DAY, f"12 new records{TAIL}", 12)


@pytest.mark.parametrize("subject, entries", [
    (f"2 zoning cases and a budget item{TAIL}", 2),                         # more items than the edition's entries
    (f"12 new records{TAIL}", 11),                                          # a record count that is not its entries
    (f"2 zoning cases and 2 zoning cases{TAIL}", 9),                        # a topic twice
    (f"A zoning case and 3 new records{TAIL}", 9),                          # records with a topic
    (f"2 zoning cases, a budget item, an ordinance and a resolution{TAIL}", 9),     # four topics
    ("2 zoning cases and a budget item: your Elsewhere morning note", 9),  # not the repository's place
    (f"2 zoning cases and a budget item{TAIL} - URGENT: reply with your password", 9),
    (f"2 Zoning cases and a budget item{TAIL}", 9),                         # not exactly as render writes it
    (f"2 zoning cases and a budget item {TAIL}", 9),
    (f"02 zoning cases{TAIL}", 9),
    (f"2 lawsuits{TAIL}", 9),                                               # a phrase that is not config
    (f"4 public meetings today · a budget item{TAIL}", 9),                  # more meetings than coming_up holds
    (f"Official notice · a budget item{TAIL}", 9),
    ("Official notice from the City", 9),
    (f"{'2 zoning cases, ' * 6}a budget item{TAIL}", 99),
])
def test_deliver_refuses_a_subject_that_is_not_made_of_config_phrases(subject, entries):
    assert not deliver.subject_ok(SETTINGS, DAY, subject, entries)


def test_deliver_refuses_topic_subjects_without_the_configs_phrases():
    assert not deliver.subject_ok(dataclasses.replace(SETTINGS, subject_text=()), DAY, good(), 3)
    assert not deliver.subject_ok(dataclasses.replace(SETTINGS, place=""), DAY, good(), 3)
    other = tuple((k, "{n} lawsuits" if k == "subject_rezoning_many" else v) for k, v in SETTINGS.subject_text)
    assert not deliver.subject_ok(dataclasses.replace(SETTINGS, subject_text=other), DAY, good(), 3)
    # the day's template still passes whatever the phrases
    assert deliver.subject_ok(dataclasses.replace(SETTINGS, subject_text=()), DAY, render.subject(CTX, DAY), 3)


def test_the_plans_subjects_are_per_edition_and_pass_the_deliver_check(msite):  # noqa: F811
    from test_morning_sender_deliver import Fake, go, people
    p = plan_mod.build(msite, D, cfg_with())["plan"]
    note = read_note(msite)
    by_id = {e["id"]: e for e in note["entries"]}
    for ed in p["editions"]:
        assert ed["subject"] == render.subject(render.context(cfg_with()), DAY, [by_id[i] for i in ed["entry_ids"]],
                                               note.get("coming_up"))
    assert len({ed["subject"] for ed in p["editions"]}) > 1             # editions of other lists say other things
    res, _ = go(copy.deepcopy(p), Fake(people(p)))
    assert (res.code, res.status) == (0, "sent")
    bad = copy.deepcopy(p)
    bad["editions"][0]["subject"] = bad["editions"][-1]["subject"].replace("a ", "an urgent ", 1) or "x"
    assert go(bad, Fake(people(p)))[0].status == "bad-plan"


def _two_plans_today(msite, tmp_path):  # noqa: F811
    base = read_note(msite)
    one = {**base, "coming_up": []}
    two = {**base, "coming_up": [today_row()]}
    return (plan_mod.build(site_with(tmp_path / "a", one), D, cfg_with())["plan"],
            plan_mod.build(site_with(tmp_path / "b", two), D, cfg_with())["plan"])


def test_a_meeting_today_in_a_later_build_still_claims_the_day_and_sends_the_rest(msite, tmp_path):  # noqa: F811
    """The lead comes from coming_up, which a later build the same day may change: the claim reads the subject
    without it (common.claim_subject), so a re-run continues the same plan."""
    from test_morning_sender_deliver import Fake, go, people
    p1, p2 = _two_plans_today(msite, tmp_path)
    assert any(common.SUBJECT_SEP in e["subject"] for e in p2["editions"])
    assert not any(common.SUBJECT_SEP in e["subject"] for e in p1["editions"])
    assert deliver.plan_digest(p1) == deliver.plan_digest(p2)
    fake = Fake(people(p1), fail={"create_email": [None] + [deliver.ProviderError("email create")]})
    assert go(p1, fake)[0].status == "failed"
    res, _ = go(p2, fake)
    assert (res.code, res.status, res.editions, len(fake.created)) == (0, "sent", 2, 3)


# ------------------------------------------------------------------ the card: kicker and headline
def test_each_card_leads_with_its_topic_kicker_then_the_title_as_headline():
    n = note_of(vote(3, 4, untitled=False), solicitation(1), entry(id="o", lists=["budget"]), date=DAY)
    html = render.body_html(CTX, n, n["entries"])
    assert ok(html)
    kick = [[p.all_text() for p in c.walk() if p.tag == "p"][0] for c in cards(html)]
    # the fixture entry's title says "resolution": the item type rule's word, so both labels, in the fixed order
    assert kick == [TEXT["topic_ordinance"], TEXT["topic_contracts"], f"{TEXT['topic_budget']} · {TEXT['topic_resolution']}"]
    assert titles(html) == ["ORDINANCE 3-2026-27: FIXTURE a real title", "FIXTURE bid 1", "FIXTURE: a resolution"]
    assert links(html)[0] == SITE_URL + "city/items/2026.html#ordinance-3"          # the headline links the site page
    text = render.body_text(CTX, n, n["entries"])
    assert f"  {TEXT['topic_ordinance']}\n  ORDINANCE 3-2026-27: FIXTURE a real title\n  Fixture Council, September 3, 2026 regular session\n" in text


def test_an_entry_with_no_topic_leads_with_its_recorded_words():
    e = entry(lists=["seats"], title="FIXTURE: approval of the agenda", recorded="On the agenda")
    html = render.body_html(CTX, note_of(e), [e])
    c = cards(html)[0]
    assert [p.all_text() for p in c.walk() if p.tag == "p"][0] == "On the agenda"
    assert html.count("On the agenda") == 1


def test_a_long_title_is_cut_at_a_word_with_an_ellipsis():
    words = " ".join(["word"] * 200)                    # 999 characters
    e = entry(title=words)
    head = titles(render.body_html(CTX, note_of(e), [e]))[0]
    assert head.endswith(" word" + common.CUT) and len(head) <= common.MAX_TITLE + len(common.CUT)
    assert common.cut("a" * 700) == "a" * common.MAX_TITLE + common.CUT          # no break at all: cut mid-run
    assert common.cut("short title") == "short title"


def test_record_text_in_the_kicker_slot_and_headline_stays_inert():
    e = entry(lists=["seats"], recorded=HOSTILE, title=HOSTILE)
    html = render.body_html(CTX, note_of(e), [e])
    assert ok(html) and "{{" not in html and "<script" not in html
    assert not re.search(r"[<>{}\[\]()*_`#\\~|!$%@=]", re.sub(r"&#\d+;", "", head_raw(html)))


# ------------------------------------------------------------------ a title from the meeting's agenda
def test_a_vote_titled_from_its_agenda_stands_as_itself_and_cites_the_agenda():
    from test_morning_sender_render import SEPT, MINUTES_URL
    titled = agenda_vote(6, 7, "FIXTURE an ordinance on parking")
    n = note_of(*SEPT, titled, date=DAY)
    html = render.body_html(CTX, n, n["entries"])
    assert ok(html)
    assert titles(html) == ["Fixture Council, September 3, 2026 regular session", SEPT[2]["title"], titled["title"]]
    assert render.untitled_words(CTX, 4) in html              # the group keeps only the votes still untitled
    assert links(html)[-4:-1] == [SITE_URL + "city/items/2026.html#ordinance-6", f"{MINUTES_URL}#page=7",
                                  f"{AGENDA_URL}#page=3"]
    words = f"{TEXT['title_agenda']}, {config.SITE['morning_note']['page']['page_label']} 3"
    assert words in cards(html)[-1].all_text()
    text = render.body_text(CTX, n, n["entries"])
    assert f"  {words}: {AGENDA_URL}#page=3" in text and f"  {titled['title']}" in text
    assert render.topic_counts(CTX, n["entries"]) == {"ordinance": 5}


@pytest.mark.parametrize("url", ["http://example.com/a.pdf", "https://elsewhere.example.org/a.pdf", None, ""])
def test_a_caption_whose_agenda_cannot_be_linked_is_never_shown(url):
    from test_morning_sender_render import SEPT
    titled = agenda_vote(6, 7, "FIXTURE CAPTION WORDS", url=url)
    n = note_of(*SEPT, titled, date=DAY)
    html = render.body_html(CTX, n, n["entries"])
    assert ok(html) and "CAPTION WORDS" not in html and "CAPTION WORDS" not in render.body_text(CTX, n, n["entries"])
    assert render.untitled_words(CTX, 5) in html                # it joins its meeting's untitled votes


def test_a_lone_vote_whose_agenda_cannot_be_linked_shows_its_number_only():
    titled = agenda_vote(6, 7, "FIXTURE CAPTION WORDS", url="https://elsewhere.example.org/a.pdf")
    html = render.body_html(CTX, note_of(titled), [titled])
    assert "CAPTION WORDS" not in html and titles(html) == ["ORDINANCE 6-2026-27"]


def test_the_agenda_link_stays_in_a_row_when_the_size_rule_applies():
    titled = agenda_vote(6, 7, "FIXTURE an ordinance on parking")
    it = render._item(CTX, titled)
    row = render._row(CTX, it)[0]
    assert f"{AGENDA_URL}#page=3" in row and render.inert(TEXT["title_agenda"]) in row
    html = render._compose(CTX, note_of(titled), [titled], render._flat(CTX, note_of(titled), [titled], None), 0, 1)
    assert ok(html) and f"{AGENDA_URL}#page=3" in links(html)


def test_an_agenda_entry_whose_own_source_is_the_cited_page_gets_no_second_link():
    e = entry(lists=["seats"], title="ORDINANCE 6-2026-27: FIXTURE", source={"url": f"{AGENDA_URL}#page=3", "page": 3},
              title_source={"kind": "agenda", "source_id": "s", "page": 3, "meeting_id": "m", "url": f"{AGENDA_URL}#page=3"})
    html = render.body_html(CTX, note_of(e), [e])
    assert links(html).count(f"{AGENDA_URL}#page=3") == 1 and TEXT["title_agenda"] not in html


def test_the_note_carries_the_facts_title_source_with_the_agenda_pages_url():
    """sitegen.morning: an item the city build titled from its meeting's agenda (facts item.title_source) gives
    every entry of it `title_source` with that agenda page's URL; any other entry carries null."""
    import json
    from sitegen import views
    from conftest import FIXTURE
    f = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ix0 = views.Index(f)
    item_id = next(r["item_id"] for r in f["roll_calls"] if ix0.items.get(r.get("item_id") or ""))
    agenda = next(s for s in f["sources"] if s["id"] != next(r["source_id"] for r in f["roll_calls"]))
    it = next(i for i in f["items"] if i["id"] == item_id)
    it["title"] = "FIXTURE caption from the agenda"
    it["title_source"] = {"kind": "agenda", "source_id": agenda["id"], "page": 4, "meeting_id": "m-fixture"}
    entries = [e for d in morning.documents(views.Index(f)) for e in d["entries"]]
    mine = [e for e in entries if e["kind"] == "vote" and e["href"] and item_id in e["href"]]
    others = [e for e in entries if e not in mine]
    assert mine and all(e["title_source"] == {"kind": "agenda", "source_id": agenda["id"], "page": 4,
                                              "meeting_id": "m-fixture", "url": f"{agenda['url']}#page=4"}
                        and e["title"].endswith("FIXTURE caption from the agenda") and not e["untitled"] for e in mine)
    assert others and all(e["title_source"] is None for e in others)
    it["title_source"]["source_id"] = "src-not-in-the-facts"
    assert all(e["title_source"] is None for d in morning.documents(views.Index(f)) for e in d["entries"])
