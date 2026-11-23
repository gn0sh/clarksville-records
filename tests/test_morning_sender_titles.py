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
from test_morning_sender_render import CTX, HOSTILE, entry, head_raw, links, note_of, styled, titles, vote
from test_site_neutrality import BANNED

TEXT = config.SITE["morning_note"]["sender"]["text"]
PLACE = config.SITE["today_place"]
LABEL = {t["key"]: t["label"] for t in config.SITE["morning_note"]["subject_topics"]}
TAIL = TEXT["subject_frame"].replace("{topics}", "").replace("{place}", PLACE)       # ": your <place> morning note"
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


# Real agenda captions (agenda_captions on the 2026-07-02, 08-06, 09-03 and 10-01 City Council agendas, branch
# claude/note-titles-captions; the text is the agenda's own, cut by its reader)
ZONE = ("(FIRST READING) [ZONING CASE Z-22-2025] An Ordinance amending the zoning code and map of the City of "
        "Clarksville, application of Youth Realty, LLC for a zone change on a parcel of land located on the eastern "
        "frontage of Professional Park Dr, 1,850 +/- feet south of the intersection of Dunlop Ln & Professional Park "
        "Dr from O-1 Office District to C-2 General Commercial District.")
WINE = ("A Resolution approving a Certificate of Compliance for sale of wine in a food store at Sudden Service #25, "
        "located at 601 Hornbuckle Rd, Clarksville TN.")
BOARDS = "A Resolution approving appointments to the Beer Board and Tree Board"
DONATE = ("(FIRST READING) An Ordinance authorizing the donation of real property from the City of Clarksville "
          "Tennessee to Montgomery County, Tennessee for the purpose of a new school.")
LEASE = ("A Resolution of the City Council of the City of Clarksville, Tennessee, requiring majority council approval "
         "prior to termination of the lease agreement with Ajax Turner Senior Citizen's Center at 953 Clark Street and "
         "rescinding the notice of termination by the Mayor on March 20, 2026.")
SKATE = ("A Resolution of the City Council of the City of Clarksville, Tennessee, approving a Memorandum of Understanding "
         "by and between the City of Clarksville and Bikers Who Care for the development of the All Wheels Skatepark at "
         "Bel Aire Park.")
BUDGET = ("(FIRST READING) An Ordinance amending the Operating Budgets for the Fiscal Year 2026-27 for the Clarksville "
          "Police Special Revenue Fund")
K9 = 'A Resolution authorizing retirement of a Patrol Service Dog, "Drako" from K-9 Unit and donatin to Police Officer'
ANNEX = "A Resolution annexing a parcel of land west of Little Hope Rd"


def city(n: int, caption: str, kind="RESOLUTION", **kw) -> dict:
    num = f"{kind} {n}-2026-27"
    return vote(n, n, title=f"{num}: {caption}", title_ours=False, untitled=False, item_number=num, **kw)


# ------------------------------------------------------------------ what each record is about
@pytest.mark.parametrize("e, want", [
    (city(1, ZONE, "ORDINANCE"), "zonechange"),        # the title says "zone change"
    (city(13, "FIXTURE [ZONING CASE Z-1-2026] text amendment to the Zoning Ordinance", "ORDINANCE"), "zoning"),
    (city(2, WINE), "alcohol"),
    (city(3, BOARDS), "appointments"),                  # the first topic it matches: not "beer", an alcohol item
    (city(4, DONATE, "ORDINANCE"), "property"),
    (city(5, BUDGET, "ORDINANCE"), "budget"),            # budget comes before police
    (city(6, K9), "safety"),
    (city(7, ANNEX), "annexation"),                      # an act "annexing"
    (city(14, "A Resolution adopting a Final Plan of Services for annexed territory"), "annexitem"),
    (city(8, SKATE), "parks"),
    (city(9, LEASE), "resolution"),                     # "953 Clark Street" is an address, not a streets item
    (city(10, "A Resolution for a sign at 100 Professional Park Dr"), "resolution"),   # nor "Park Dr" a park
    (city(11, "FIXTURE an ordinance on sidewalks", "ORDINANCE"), "streets"),
    (city(12, "FIXTURE nothing else", "ORDINANCE"), "ordinance"),                       # the kind, last
])
def test_each_record_takes_the_first_topic_its_own_words_match(e, want):
    assert render.topic(CTX, e) == want


def test_topics_also_come_from_the_lists_and_kinds_but_never_from_a_title_we_made():
    assert render.topic(CTX, rpc_case(1)) == "zoning"                                   # the zoning list
    assert render.topic(CTX, solicitation(1)) == "contracts"                            # a solicitation
    assert render.topic(CTX, entry(id="contracts/document/7/1", kind="document", lists=["contracts"],
                                   title="FIXTURE: Bid Tab")) is None                    # a later document: not a new bid
    assert render.topic(CTX, entry(lists=["budget"], title="FIXTURE: a hearing")) == "budget"      # the budget list
    assert render.topic(CTX, entry(lists=["seats"], title="Beer and parks", title_ours=True)) is None
    assert render.topic(CTX, vote(1, 2)) == "ordinance"           # an untitled vote: its number, the kind fallback
    caption = city(13, WINE, title_source={"kind": "agenda", "url": "https://elsewhere.example.org/a.pdf"})
    assert render.topic(CTX, caption) == "resolution"             # a caption that cannot be cited is not read


def test_each_item_counts_once_under_the_topic_it_first_matches():
    two_readings = [city(1, ZONE, "ORDINANCE"), city(1, ZONE.replace("FIRST", "SECOND"), "ORDINANCE", id="city/vote/b")]
    on_both = [rpc_case(4), rpc_case(4, kind="vote", id="rpc/vote/4b")]            # agenda and minutes: one case
    got = render.topic_counts(CTX, two_readings + on_both + [city(2, WINE), solicitation(1), solicitation(2)])
    assert got == {"zonechange": 1, "zoning": 1, "alcohol": 1, "contracts": 2}
    docs = [entry(id=f"contracts/document/7/{d}", kind="document", lists=["contracts"], title="FIXTURE: Bid Tab")
            for d in (1, 2)]
    assert render.topic_counts(CTX, docs + [solicitation(1)]) == {"contracts": 1}


# ------------------------------------------------------------------ the subject
def test_the_subject_says_what_the_records_are_about_most_first_with_plurals():
    es = [city(n, ZONE, "ORDINANCE") for n in (1, 2)] + [city(5, DONATE, "ORDINANCE"), solicitation(1)]
    assert subj(*es) == f"2 zone changes, a property item and a new bid{TAIL}"
    assert subj(solicitation(1)) == f"A new bid{TAIL}"                      # one: the _one phrase, upper case first
    assert subj(city(1, K9), city(2, K9)) == f"2 public safety items{TAIL}"


def test_ordinance_and_resolution_are_named_only_when_nothing_else_is():
    kinds = [vote(n, n, untitled=False) for n in (1, 2, 3)] + [city(4, LEASE)]
    assert subj(*kinds) == f"3 ordinances and a resolution{TAIL}"
    assert subj(*kinds, city(5, WINE)) == f"An alcohol item{TAIL}"


def test_ties_go_in_the_configs_order_and_at_most_three_topics():
    es = [solicitation(1), city(2, K9), city(3, ANNEX), city(4, DONATE, "ORDINANCE")]
    # a 1-1-1-1 tie in the config's order: annexation, property, public safety (past the cap: left out), the bid
    assert subj(*es) == f"An annexation, a property item and a new bid{TAIL}"


def test_a_phrase_that_would_pass_the_cap_is_left_out_whole_and_a_shorter_one_may_follow():
    es = [city(n, ZONE, "ORDINANCE") for n in range(3)] + [city(20 + n, WINE) for n in range(2)] + \
        [city(40 + n, K9) for n in range(2)] + [solicitation(1)]
    s = subj(*es)           # "and 2 public safety items" would pass the cap: left out, the shorter bid fits
    assert s == f"3 zone changes, 2 alcohol items and a new bid{TAIL}" and len(s) <= common.SUBJECT_CAP
    ctx = {**CTX, "place": "Clarksville Area"}
    for n in range(1, 30):          # whatever the counts, never over the cap and never a cut word
        r = random.Random(n)
        many = [rpc_case(k) for k in range(r.randint(0, 999))] + [solicitation(k) for k in range(r.randint(0, 30))] + \
            [city(k, K9) for k in range(r.randint(0, 30))]
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
    assert s == f"A meeting today · 2 zoning items{TAIL}"
    assert subj(*es, coming=[today_row(), today_row()]).startswith("2 meetings today · ")
    assert common.claim_subject(s) == subj(*es)
    full = [city(n, ZONE, "ORDINANCE") for n in range(12)] + [city(20 + n, K9) for n in range(11)]
    assert subj(*full, coming=[today_row()]) == subj(*full)            # no room: the topics stay, the lead goes


@pytest.mark.parametrize("seed", range(200))
def test_every_subject_reads_back_and_never_names_a_government(seed):
    r = random.Random(seed)
    counts = {k: r.choice([0, 0, 1, 2, 9, 17, 120]) for k in common.topic_keys(TEXT)}
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
    cfg["morning_note"]["sender"]["text"]["subject_frame"] = "{topics}: your county morning note"
    with pytest.raises(plan_mod.PlanError, match="official"):
        plan_mod.build(msite, D, cfg)
    assert any("subject_frame must not name a government body" in p for p in morning.problems(cfg))


@pytest.mark.parametrize("key, value, problem", [
    ("subject_budget_one", "a budget change, or two", "must not hold"),
    ("subject_budget_many", "{n} budget and money changes", "must not hold"),
    ("subject_today_one", "today · a meeting", "must not hold"),
    ("subject_budget_one", "an ordinance", "read as that phrase only"),
    ("subject_budget_many", "{n} ordinances", "read as that phrase only"),
    ("subject_records_many", "new records", "must contain {n}"),
    ("subject_frame", "your {place} morning note", "must contain {topics}"),
    ("subject_and", "and also", "must be one word"),
    ("subject_contracts_one", "a CMCSS bid", "must not name a government body"),
    ("subject_parks_one", None, "must be set"),
    ("subject_mystery_one", "a mystery", "is not a known key"),
])
def test_the_build_refuses_phrases_the_deliver_stage_could_not_read_back(key, value, problem):
    cfg = copy.deepcopy(config.SITE)
    if value is None:
        del cfg["morning_note"]["sender"]["text"][key]
    else:
        cfg["morning_note"]["sender"]["text"][key] = value
    assert any(problem in p for p in morning.problems(cfg)), morning.problems(cfg)


@pytest.mark.parametrize("change, problem", [
    (lambda ts: ts[0]["words"].append("(unclosed"), "is not a pattern"),
    (lambda ts: ts[0].update(lists=["zoning", "nearby"]), "is not one of"),
    (lambda ts: ts[0].update(kinds=["memo"]), "is not one of"),
    (lambda ts: ts[-1].update(item_types=["proclamation"]), "is not an item_types key"),
    (lambda ts: ts.append(dict(ts[0])), "used once"),
    (lambda ts: ts.append({"key": "records", "label": "X", "words": ["x"]}), "not records or today"),
    (lambda ts: ts.append({"key": "misc", "label": "Misc"}), "needs at least one rule"),
    (lambda ts: ts[0].update(fallback="yes"), "fallback (true or false)"),
    (lambda ts: ts.append({"key": "misc", "label": "Misc", "words": ["misc"]}), "subject_misc_one must be set"),
])
def test_the_build_refuses_a_topic_it_could_not_apply(change, problem):
    cfg = copy.deepcopy(config.SITE)
    change(cfg["morning_note"]["subject_topics"])
    assert any(problem in p for p in morning.problems(cfg)), morning.problems(cfg)


def test_the_shipped_phrases_pass_and_every_one_is_read_by_the_deliver_stage():
    assert common.subject_problems(TEXT, PLACE) == []
    assert not [p for p in morning.problems(config.SITE) if "subject" in p]
    s = settings_mod.load(config.REPO_ROOT / "config" / "site.yml")
    assert dict(s.subject_text) == {k: v for k, v in TEXT.items() if k.startswith("subject_")} and s.place == PLACE
    assert set(common.topic_keys(TEXT)) == {t["key"] for t in config.SITE["morning_note"]["subject_topics"]}
    assert common.COMING_N == morning.COMING_N
    for k in dict(s.subject_text):
        assert BANNED.search(TEXT[k]) is None and not render.AUTHORITY.search(TEXT[k].replace("{place}", PLACE))


# ------------------------------------------------------------------ the deliver stage reads the subject back
SETTINGS = settings_mod.load(config.REPO_ROOT / "config" / "site.yml")


def good(n=3) -> str:
    return common.compose(TEXT, config.SITE["site_name"], PLACE, DAY, {"zoning": 2, "budget": 1}, n, 1)


def test_deliver_accepts_what_render_writes():
    assert deliver.subject_ok(SETTINGS, DAY, good(), 3)
    assert deliver.subject_ok(SETTINGS, DAY, common.claim_subject(good()), 3)
    assert deliver.subject_ok(SETTINGS, DAY, render.subject(CTX, DAY), 1)
    assert deliver.subject_ok(SETTINGS, DAY, f"12 new records{TAIL}", 12)


@pytest.mark.parametrize("subject, entries", [
    (f"2 zone changes and a budget item{TAIL}", 2),                         # more items than the edition's entries
    (f"12 new records{TAIL}", 11),                                          # a record count that is not its entries
    (f"2 zone changes and 2 zone changes{TAIL}", 9),                        # a topic twice
    (f"A zone change and 3 new records{TAIL}", 9),                          # records with a topic
    (f"2 zone changes, a budget item, an ordinance and a resolution{TAIL}", 9),     # four topics
    ("2 zone changes and a budget item: your Elsewhere morning note", 9),  # not the repository's place
    (f"2 zone changes and a budget item{TAIL} - URGENT: reply with your password", 9),
    (f"2 Zoning cases and a budget item{TAIL}", 9),                         # not exactly as render writes it
    (f"2 zone changes and a budget item {TAIL}", 9),
    (f"02 zone changes{TAIL}", 9),
    (f"2 lawsuits{TAIL}", 9),                                               # a phrase that is not config
    (f"4 public meetings today · a budget item{TAIL}", 9),                  # more meetings than coming_up holds
    (f"Official notice · a budget item{TAIL}", 9),
    ("Official notice from the City", 9),
    (f"{'2 zone changes, ' * 6}a budget item{TAIL}", 99),
])
def test_deliver_refuses_a_subject_that_is_not_made_of_config_phrases(subject, entries):
    assert not deliver.subject_ok(SETTINGS, DAY, subject, entries)


def test_deliver_refuses_topic_subjects_without_the_configs_phrases():
    assert not deliver.subject_ok(dataclasses.replace(SETTINGS, subject_text=()), DAY, good(), 3)
    assert not deliver.subject_ok(dataclasses.replace(SETTINGS, place=""), DAY, good(), 3)
    other = tuple((k, "{n} lawsuits" if k == "subject_zoning_many" else v) for k, v in SETTINGS.subject_text)
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
    kick = [k.all_text() for k in styled(html, "item_kick")]
    assert kick == [LABEL["ordinance"], LABEL["contracts"], LABEL["budget"]]       # one each: the first it matches
    assert titles(html) == ["ORDINANCE 3-2026-27: FIXTURE a real title", "FIXTURE bid 1", "FIXTURE: a resolution"]
    first = [a.attrs["href"] for a in styled(html, "item")[0].walk() if a.tag == "a"]
    assert first == [SITE_URL + "city/items/2026.html#ordinance-3"]               # the headline links the site page
    text = render.body_text(CTX, n, n["entries"])
    assert "  Fixture Council, September 3, 2026 regular session: " in text
    # the vote is not confirmed: its own line says so (note/unconfirmed-unflagged)
    assert f"  - {LABEL['ordinance']}: ORDINANCE 3-2026-27: FIXTURE a real title · Recorded in the minutes; not confirmed " \
           f"<{SITE_URL}city/items/2026.html#ordinance-3>\n" in text


def test_an_entry_with_no_topic_leads_with_its_recorded_words():
    e = entry(lists=["seats"], title="FIXTURE: approval of the agenda", recorded="On the agenda")
    html = render.body_html(CTX, note_of(e), [e])
    # note-titles round 3: no topic label; the `recorded` words stand once, under the meeting line
    assert not styled(html, "item_kick") and [x.all_text() for x in styled(html, "said")] == ["On the agenda"]
    assert html.count("On the agenda") == 1


def test_a_long_title_is_cut_at_a_word_with_an_ellipsis():
    words = " ".join(["word"] * 200)                    # 999 characters
    e = entry(title=words)
    head = titles(render.body_html(CTX, note_of(e), [e]))[0]
    assert head.endswith(" word…") and len(head) <= render.HEADLINE_MAX + 1
    assert words in render.body_text(CTX, note_of(e), [e]) or head in render.body_text(CTX, note_of(e), [e])
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
    titled = agenda_vote(6, 7, "FIXTURE an ordinance on noise")
    n = note_of(*SEPT, titled, date=DAY)
    html = render.body_html(CTX, n, n["entries"])
    assert ok(html)
    assert titles(html) == [render.untitled_words(CTX, 4), SEPT[2]["title"], titled["title"]]
    assert render.untitled_words(CTX, 4) in html              # the group keeps only the votes still untitled
    # note-titles round 3: the meeting's card links the minutes and the agenda its title comes from, once each
    docs = styled(html, "docs")[0]
    assert [(a.all_text(), a.attrs["href"]) for a in docs.walk() if a.tag == "a"] == [
        (TEXT["source_document"], MINUTES_URL), (TEXT["title_agenda"], AGENDA_URL)]
    # and its own line cites the agenda page next to the caption's words (captions/uncited-title/card-level-only)
    line = styled(html, "item")[-1]
    assert [(a.all_text(), a.attrs["href"]) for a in line.walk() if a.tag == "a"] == [
        (titled["title"], SITE_URL + "city/items/2026.html#ordinance-6"),
        (TEXT["title_agenda_page"].replace("{page}", "3"), f"{AGENDA_URL}#page=3")]
    text = render.body_text(CTX, n, n["entries"])
    assert f"  {TEXT['title_agenda']}: {AGENDA_URL}\n" in text and titled["title"] in text
    assert f"{TEXT['title_agenda_page'].replace('{page}', '3')}: {AGENDA_URL}#page=3" in text
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
    assert links(html).count(AGENDA_URL) == 1 and TEXT["title_agenda"] not in html


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


# ------------------------------------------------------------------ the headline: labels, lead drop, 200 characters
def test_a_zoning_caption_reads_from_the_zone_change_with_its_districts_and_no_applicant():
    """note-titles round 3: the labels move after the headline; the zoning boilerplate and the applicant (often a
    person's name) are left out through "for"; the middle is cut so the "from ... to ..." districts stay."""
    e = city(1, ZONE, "ORDINANCE")
    head, labels = render.headline_parts(CTX, e, e["title"])
    assert labels == "(FIRST READING) [ZONING CASE Z-22-2025]"
    assert head.startswith("ORDINANCE 1-2026-27: …a zone change on a parcel of land located on the eastern frontage")
    assert head.endswith("… from O-1 Office District to C-2 General Commercial District.")
    assert "Youth Realty" not in head and len(head) <= render.HEADLINE_MAX
    # each run of words shown is the record's own, in its order: the headline is the title with words left out
    runs = [x.strip() for x in head.split("…") if x.strip()]
    assert all(r in e["title"] for r in runs)
    assert [e["title"].index(r) for r in runs] == sorted(e["title"].index(r) for r in runs)
    lease = city(2, LEASE)
    assert render.headline(CTX, lease, lease["title"]).startswith("RESOLUTION 2-2026-27: …requiring majority council")
    assert render.headline(CTX, city(3, BOARDS), city(3, BOARDS)["title"]) == \
        "RESOLUTION 3-2026-27: …appointments to the Beer Board and Tree Board"


def test_without_an_application_clause_only_the_boilerplate_goes():
    e = city(5, "An Ordinance amending the zoning code and map of the City of Clarksville, FIXTURE parcel rezoned "
                "from R-1 to R-2", "ORDINANCE")
    assert render.headline(CTX, e, e["title"]) == "ORDINANCE 5-2026-27: …FIXTURE parcel rezoned from R-1 to R-2"


def test_an_applicant_whose_name_holds_for_is_still_left_out():
    e = city(6, "An Ordinance amending the zoning code and map of the City of Clarksville, application of Friends "
                "for Parks, LLC for a zone change on FIXTURE land", "ORDINANCE")
    assert render.headline(CTX, e, e["title"]) == "ORDINANCE 6-2026-27: …a zone change on FIXTURE land"


def test_a_long_title_with_no_closing_districts_is_cut_at_its_end():
    words = "FIXTURE " + " ".join(["word"] * 80)
    head = render.headline(CTX, entry(), words)
    assert head.endswith(" word…") and len(head) <= render.HEADLINE_MAX + 1


def test_a_title_of_labels_only_keeps_them_as_the_headline():
    e = entry(title="(FIRST READING) [FIXTURE]")
    assert render.headline_parts(CTX, e, e["title"]) == ("(FIRST READING) [FIXTURE]", "")


@pytest.mark.parametrize("title", [
    "RESOLUTION 4-2026-27: A Resolution approving",                       # nothing would be left: kept whole
    "RESOLUTION 4-2026-27: FIXTURE. A Resolution approving a lease",      # not at the start: kept
    "FIXTURE: An Ordinance amending the zoning code and map of the City of Clarksville, a parcel",   # another number
])
def test_a_lead_phrase_is_dropped_only_at_the_start_and_never_to_nothing(title):
    assert render.headline(CTX, city(4, WINE), title) == title


def test_the_lead_phrases_come_from_config():
    e = city(2, LEASE)
    assert render.headline({**CTX, "lead_drop": []}, e, e["title"]).startswith("RESOLUTION 2-2026-27: A Resolution of")
    assert config.SITE["morning_note"]["title_lead_drop"]
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"]["title_lead_drop"] = ["ok", 3]
    assert "morning_note.title_lead_drop must be a list of patterns" in morning.problems(cfg)
    for bad in ("(unclosed", "x*"):                       # not a pattern; matches the empty start of any title
        cfg["morning_note"]["title_lead_drop"] = [bad]
        assert any("title_lead_drop" in p for p in morning.problems(cfg)), bad


def test_a_real_caption_card_reads_kicker_headline_meeting_and_both_sources():
    from test_morning_sender_render import MINUTES_URL
    e = city(1, ZONE, "ORDINANCE", title_source={"kind": "agenda", "source_id": "s", "page": 1, "meeting_id": "m",
                                                  "url": f"{AGENDA_URL}#page=1"})
    html = render.body_html(CTX, note_of(e), [e])
    assert ok(html)
    assert [k.all_text() for k in styled(html, "item_kick")] == [LABEL["zonechange"]]
    assert titles(html)[0] == render.headline(CTX, e, e["title"])
    # muted after it: its labels, that it is not confirmed (never only in the card's shared words), its agenda page
    cite = TEXT["title_agenda_page"].replace("{page}", "1")
    assert [x.all_text() for x in styled(html, "muted")] == [
        f"(FIRST READING) [ZONING CASE Z-22-2025] · Recorded in the minutes; not confirmed · {cite}"]
    assert not styled(html, "said")
    assert links(html)[1:3] == [MINUTES_URL, AGENDA_URL] and links(html)[4] == f"{AGENDA_URL}#page=1"


# ------------------------------------------------------------------ PR #90 review: cite, wording, privacy, subject
def test_a_row_names_the_agenda_of_the_meeting_that_printed_the_title_with_its_page():
    """captions/uncited-title/row-wrong-agenda: the size rule's row says which meeting's agenda, and its page."""
    other = agenda_vote(6, 7, "FIXTURE an ordinance on parking")
    other["title_source"]["meeting_id"] = "2026-08-06-regular"           # titled from an earlier meeting's agenda
    row = render._row(CTX, render._item(CTX, other))[0]
    dated = TEXT["title_agenda_dated"].replace("{date}", "August 6, 2026")
    assert render.inert(f"{dated}, {config.SITE['morning_note']['page']['page_label']} 3") in row
    assert render.inert(TEXT["title_agenda"]) not in row
    line = render._line_of(CTX, render._item(CTX, other), [])
    assert render.inert(TEXT["title_agenda_page_dated"].replace("{date}", "August 6, 2026").replace("{page}", "3")) in line
    own = render._row(CTX, render._item(CTX, agenda_vote(6, 7, "FIXTURE an ordinance on parking")))[0]
    assert render.inert(f"{TEXT['title_agenda']}, {config.SITE['morning_note']['page']['page_label']} 3") in own


def test_an_agenda_title_with_no_page_is_not_shown():
    e = agenda_vote(6, 7, "FIXTURE CAPTION WORDS")
    e["title_source"]["page"] = None
    assert render.agenda_cite(e) is None
    html = render.body_html(CTX, note_of(e), [e])
    assert "CAPTION WORDS" not in html and "CAPTION WORDS" not in render.body_text(CTX, note_of(e), [e])


def _application_titles() -> list[str]:
    """Every caption the fixture agendas give (collector/tests/fixtures/city/agenda_*.txt, read by the captions
    reader) and every facts title (data/facts.json, when fetched) that holds "application of"."""
    from pathlib import Path
    import json
    from collector import agenda_center as ac
    from collector.city_minutes import agenda_captions
    root = config.REPO_ROOT
    cfg = ac.load_config(ac.config_path("clarksville-tn"))
    out = []
    for f in sorted((root / "collector" / "tests" / "fixtures" / "city").glob("agenda_*.txt")):
        for (kind, num), found in agenda_captions(f.read_text(encoding="utf-8").split("\f"), cfg).items():
            if found[0][0]:
                out.append(f"{kind.upper()} {num}: {found[0][0]}")
    facts = Path(root / "data" / "facts.json")
    if facts.exists():
        out += [f"{i['number']}: {i['title']}" if i.get("number") else i["title"]
                for i in json.loads(facts.read_text(encoding="utf-8"))["items"] if i.get("title")]
    return [t for t in out if "application of" in t.lower()]


# A title where "application of" is no applicant: the county's beer law resolution (facts item 20-3-7).
NO_APPLICANT = ("Distance Rules for Application of",)


def test_no_applicant_survives_into_a_headline():
    """note-privacy/lead-drop-misses-wording (best effort): every agenda caption and facts title of a zoning case or
    an application leaves out "application of <applicant>" in the email's headline."""
    titles_ = _application_titles()
    assert len(titles_) >= 60                       # the 2021 and 2026 agendas alone hold more than 60
    left = []
    for t in titles_:
        num = t.split(": ", 1)[0]
        head, _ = render.headline_parts(CTX, {"item_number": num}, t)
        if "application of" in head.lower() and not any(x in t for x in NO_APPLICANT):
            left.append(t)
    assert left == []


@pytest.mark.parametrize("title, want", [
    ("ORDINANCE 47-2021-22: (First Reading) Amending the Zoning Ordinance and Map of the City of Clarksville, "
     "application of Sandra Sims, Brian Bryant - Agent for Zone Change on FIXTURE property from R-1 to C-5",
     "ORDINANCE 47-2021-22: …Zone Change on FIXTURE property from R-1 to C-5"),
    ("ORDINANCE 1-2025-26: An Ordinance amending the zoning ordinance and map of the City of Clarksville, "
     "application of FIXTURE Person for a zone change on FIXTURE land", "ORDINANCE 1-2025-26: …a zone change on FIXTURE land"),
    ("CZ-7-2025: Application of FIXTURE Person from AG to M-2", "CZ-7-2025: …from AG to M-2"),
    ("AB-2-2025: Application of FIXTURE Dept. for the Abandonment of FIXTURE Road", "AB-2-2025: …the Abandonment of FIXTURE Road"),
])
def test_each_application_wording_reads_from_the_act(title, want):
    assert render.headline(CTX, {"item_number": title.split(": ", 1)[0]}, title) == want


def test_deliver_refuses_a_subject_naming_authority_even_from_config():
    """sender/subject-config-trust: a subject the repository's own config would make (its template, its place) is
    still refused when AUTHORITY matches it; the build refuses such config first."""
    s = dataclasses.replace(SETTINGS, subject_template="{site_name} county note, {date}")
    bad = deliver.expected_subject(s, DAY)
    assert bad == "Daylight county note, November 11, 2026" and not deliver.subject_ok(s, DAY, bad, 1)
    s = dataclasses.replace(SETTINGS, place="Montgomery County")
    subject = common.compose(TEXT, config.SITE["site_name"], "Montgomery County", DAY, {"zoning": 1}, 3, 0)
    assert common.subject_parse(subject, dict(s.subject_text), s.place) is not None
    assert not deliver.subject_ok(s, DAY, subject, 3)
    assert deliver.subject_ok(SETTINGS, DAY, common.compose(TEXT, config.SITE["site_name"], PLACE, DAY, {"zoning": 1}, 3, 0), 3)
