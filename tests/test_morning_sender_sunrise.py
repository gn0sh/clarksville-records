# ruff: noqa: E501
"""note/sunrise (2026-11-22): the morning note's HTML edition in design concept A "Sunrise" (the sky header, the
greeting, one card per entry, the navy "Take part" box), with concept C's plain-word definitions and its "You are
invited." line over the next meetings in the records; the exact opening tags deliver accepts (common.TAG, LINKS);
and the size rule that keeps an edition under Gmail's clip (common.BODY_BUDGET). FIXTURE notes only."""
import copy
import re
from datetime import date

import pytest

from conftest import parse
from sitegen import config, morning
from sender import common, deliver, plan as plan_mod, render
from test_morning import D, inputs  # noqa: F401
from test_morning_sender_plan import SITE_URL, cfg_with, msite, read_note, site_with  # noqa: F401
from test_morning_sender_render import CTX, HOSTILE, SEPT, entry, html_of, links, note_of, vote
from test_site_neutrality import BANNED

TEXT = config.SITE["morning_note"]["sender"]["text"]
COMING = [{"date": "2026-11-18", "body": "Fixture County Budget Committee", "meeting": None,
           "href": "today.html#d-2026-11-18"},
          {"date": "2026-12-01", "body": "Fixture Council", "meeting": "executive session",
           "href": "city/meetings/2026.html#2026-12-01-executive"},
          {"date": "2026-12-03", "body": "Fixture Council", "meeting": "regular session",
           "href": "city/meetings/2026.html#2026-12-03-regular"}]
CONTRACTS = [entry(id="contracts/document/a/1", kind="document", body="contracts", body_name="Fixture County",
                   lists=["contracts"], meeting_date=None, meeting=None, recorded="New document",
                   title="Paving: Award Letter", href="contracts/paving.html",
                   source={"url": "https://example.com/fixture/Award%20Letter.pdf", "page": None}),
             entry(id="contracts/document/a/2", kind="document", body="contracts", body_name="Fixture County",
                   lists=["contracts"], meeting_date=None, meeting=None, recorded="New document",
                   title="Paving: Bid Tab", href="contracts/paving.html",
                   source={"url": "https://example.com/fixture/Bid%20Tab.pdf", "page": None}),
             entry(id="contracts/solicitation/b", kind="solicitation", body="contracts", body_name="Fixture County",
                   lists=["contracts"], meeting_date=None, meeting=None, recorded="New on the purchasing archive",
                   title="LED Signage Replacement", href="contracts/led.html",
                   source={"url": "https://example.com/fixture/RFP%20Packet-%20LED.pdf", "page": None})]


def ok(html: str) -> bool:
    return deliver.body_ok(html, CTX["link_hosts"], CTX["link_urls"])


def node_texts(html: str, tag: str) -> list[str]:
    return [n.all_text() for n in parse(html).walk() if n.tag == tag]


def styled(html: str, name: str) -> list:
    """Every element whose opening tag is common.TAG[name]."""
    want = parse(common.TAG[name] + "</x>").children[0].attrs
    return [n for n in parse(html).walk() if n.tag != "root" and n.attrs == want]


# ------------------------------------------------------------------ A's layout, top to bottom
LABEL = {t["key"]: t["label"] for t in config.SITE["morning_note"]["subject_topics"]}

def test_the_edition_opens_with_the_sky_header_greeting_and_unofficial_line():
    n = note_of(*SEPT, date="2026-11-18")
    html = render.body_html(CTX, n, n["entries"])
    assert html.startswith(common.TAG["page"] + "\n" + common.TAG["sheet"] + "\n" + common.TAG["sky"] + "\n")
    assert ok(html)
    assert node_texts(html, "h1") == [config.SITE["site_name"]]
    ps = node_texts(html, "p")
    place = config.SITE["today_place"]
    assert ps[:7] == [config.SITE["site_place"], f"Wednesday in {place}", "November 18", CTX["email_line"],
                      f"Good morning, {place}.", TEXT["tagline"],
                      TEXT["intro"].replace("{site_name}", config.SITE["site_name"])]
    # the sun and the name's mark are shapes, hidden from screen readers, with no word in them
    assert [x.attrs.get("aria-hidden") for x in styled(html, "sun_td") + styled(html, "mark_ring")] == ["true", "true"]
    assert all(not x.all_text() for x in styled(html, "sun_box") + styled(html, "mark_ring"))


def test_each_list_is_a_section_and_each_meeting_a_card_with_the_date_block():
    """note-titles round 3 (the owner: a busy reader will not scroll a 35,000-pixel email): one card per meeting,
    its line, the `recorded` words its items share and its documents once, then one compact line per item."""
    titled = vote(3, 4, untitled=False)
    n = note_of(*SEPT, entry(), date="2026-11-18")
    html = render.body_html(CTX, n, n["entries"])
    assert node_texts(html, "h2")[:2] == ["My two seats", "Budget"]
    assert [k.all_text() for k in styled(html, "kicker")] == [TEXT["new_on_list"]]
    cards = styled(html, "card")
    assert len(cards) == 2                                  # the council meeting, the commission meeting
    day = [c.all_text() for c in styled(html, "day_td")]
    assert day == ["Sep32026", "Nov162026"]
    heads = [h.all_text() for h in parse(html).walk() if h.tag == "h3"]
    assert heads == ["Fixture Council, September 3, 2026 regular session", "Fixture Commission"]
    # the meeting line links the meeting's page when the entries name it
    assert [a.attrs["href"] for h in parse(html).walk() if h.tag == "h3" for a in h.walk() if a.tag == "a"] == [
        SITE_URL + "city/meetings/2026.html#2026-09-03-regular"]
    # the council's votes are not confirmed: never the card's shared words, each line says so (below)
    assert [x.all_text() for x in styled(html, "said")] == ["On the agenda"]
    assert [x.all_text() for x in styled(html, "docs")] == [TEXT["source_document"]] * 2
    assert [a.attrs["href"] for d in styled(html, "docs") for a in d.walk() if a.tag == "a"] == [
        "https://example.com/fixture/minutes-2026-09-03.pdf", "https://example.com/fixture/agenda.pdf"]
    # each item: its topic label (a config label of morning_note.subject_topics; first match wins: the budget entry
    # is on the budget list), then its headline linking its page
    assert [k.all_text() for k in styled(html, "item_kick")] == [LABEL["ordinance"], LABEL["ordinance"], LABEL["budget"]]
    item_links = [[a.attrs["href"] for a in x.walk() if a.tag == "a"] for x in styled(html, "item")]
    assert item_links == [[SITE_URL + "city/meetings/2026.html#2026-09-03-regular"], [SITE_URL + titled["href"]],
                          [SITE_URL + "items/2026.html#i-x"]]
    assert TEXT["open_site"] not in html and not styled(html, "source")
    assert [x.all_text() for x in styled(html, "muted")] == [
        "ORDINANCE 1-2026-27, ORDINANCE 2-2026-27, ORDINANCE 4-2026-27 · Recorded in the minutes; not confirmed",
        "Recorded in the minutes; not confirmed"]
    assert ok(html)


def test_a_meetings_card_names_a_different_recorded_and_the_title_labels_muted_after_the_headline():
    first = vote(3, 4, untitled=False, title="ORDINANCE 3-2026-27: (FIRST READING) [ZONING CASE Z-1-2026] FIXTURE a title",
                 recorded="Recorded in the minutes", confirmed=True)
    sure = vote(5, 6, untitled=False, recorded="Recorded in the minutes", confirmed=True)
    n = note_of(first, vote(4, 5, untitled=False), sure, date="2026-11-18")
    html = render.body_html(CTX, n, n["entries"])
    assert [x.all_text() for x in styled(html, "said")] == ["Recorded in the minutes"]
    muted = [x.all_text() for x in styled(html, "muted")]
    # under "Recorded in the minutes" a vote not confirmed says only the rest, on its own line
    assert muted == ["(FIRST READING) [ZONING CASE Z-1-2026]", "not confirmed"]
    line = styled(html, "item")[0]
    head = [a.all_text() for a in line.walk() if a.tag == "a"]
    assert head == ["ORDINANCE 3-2026-27: FIXTURE a title"]
    assert ok(html)


def test_a_vote_not_confirmed_is_flagged_on_its_own_line_even_when_most_are():
    """note/unconfirmed-unflagged: the words of a vote not confirmed are never the card's shared words, so a
    confirmed vote never reads as one under them and each unconfirmed one says so itself."""
    sure = vote(5, 6, untitled=False, recorded="Recorded in the minutes", confirmed=True)
    n = note_of(sure, vote(3, 4, untitled=False), vote(4, 5, untitled=False), date="2026-11-18")
    html = render.body_html(CTX, n, n["entries"])
    assert [x.all_text() for x in styled(html, "said")] == ["Recorded in the minutes"]
    assert [x.all_text() for x in styled(html, "muted")] == ["not confirmed", "not confirmed"]
    alone = note_of(vote(3, 4, untitled=False), vote(4, 5, untitled=False), date="2026-11-18")
    html = render.body_html(CTX, alone, alone["entries"])
    assert not styled(html, "said")
    assert [x.all_text() for x in styled(html, "muted")] == ["Recorded in the minutes; not confirmed"] * 2
    assert ok(html)


def test_two_votes_on_one_item_at_one_meeting_are_one_line():
    a, b = vote(3, 4, untitled=False), vote(3, 5, untitled=False, id="city/vote/rc-2026-09-03-3b")
    n = note_of(a, b, date="2026-11-18")
    html = render.body_html(CTX, n, n["entries"])
    assert len(styled(html, "item")) == 1 and ok(html)
    assert render.body_text(CTX, n, n["entries"]).count(a["title"]) == 1


def test_an_entry_with_no_meeting_has_its_body_as_the_card_line_and_links_its_own_source():
    n = note_of(*CONTRACTS)
    html = render.body_html(CTX, n, n["entries"])
    assert not styled(html, "day_td")
    assert [h.all_text() for h in parse(html).walk() if h.tag == "h3"] == ["Fixture County"]
    # note-titles: the topic label (by what the title says first: the two "Paving" documents are street items,
    # the solicitation a contract), the headline, then its own source document, muted
    assert [x.all_text() for x in styled(html, "item_kick")] == [LABEL["streets"]] * 2 + [LABEL["contracts"]]
    assert [x.all_text() for x in styled(html, "said")] == ["New document"]
    assert [x.all_text() for x in styled(html, "muted")] == [TEXT["source_document"]] * 2 + \
        [f"New on the purchasing archive · {TEXT['source_document']}"]
    assert [[a.all_text() for a in x.walk() if a.tag == "a"][0] for x in styled(html, "item")] == [e["title"] for e in CONTRACTS]
    assert [[a.attrs["href"] for a in x.walk() if a.tag == "a"][1] for x in styled(html, "item")] == \
        [e["source"]["url"] for e in CONTRACTS]
    assert ok(html)


def test_an_entry_with_no_page_has_a_plain_headline_and_no_source_line_without_a_source():
    html = html_of(entry(href=None, source={"url": None, "page": None}))
    h3 = next(h for h in parse(html).walk() if h.tag == "h3")
    assert not [a for a in h3.walk() if a.tag == "a"] and not styled(html, "source")
    assert ok(html)


def test_the_navy_box_invites_and_lists_the_next_meetings_then_the_footer():
    n = note_of(entry(), coming_up=COMING, support_line="Please help.", support_url=config.SITE["support_url"])
    html = render.body_html(CTX, n, n["entries"])
    part = styled(html, "part")[0]
    texts = [x.all_text() for x in part.walk() if x.tag in ("p", "h2")]
    assert texts == [TEXT["take_part"], TEXT["take_part_heading"],
                     TEXT["take_part_line"].replace("{site_name}", config.SITE["site_name"]), TEXT["invited"],
                     TEXT["coming_up"], "November 18, 2026: Fixture County Budget Committee",
                     "December 1, 2026: Fixture Council, executive session",
                     "December 3, 2026: Fixture Council, regular session", TEXT["all_meetings"]]
    assert [a.attrs["href"] for a in part.walk() if a.tag == "a"] == [SITE_URL + c["href"] for c in COMING] + [SITE_URL + "today.html"]
    foot = [x.all_text().strip() for x in styled(html, "foot")[0].walk() if x.tag == "p"]
    assert foot == [CTX["text"]["why"], CTX["notice"], f"Please help. {config.SITE['support_label']}", common.CREDIT_TEXT]
    assert html.endswith(common.CREDIT_LINE + "\n</div>\n</div>\n</div>\n")
    assert ok(html)


def test_with_no_meeting_ahead_the_coming_up_list_is_left_out():
    for coming in (None, [], "x", [{"date": "nope", "body": "B"}, {"date": "2026-12-01", "body": 7}]):
        n = note_of(entry(), **({} if coming is None else {"coming_up": coming}))
        html = render.body_html(CTX, n, n["entries"])
        assert TEXT["coming_up"] not in html and TEXT["invited"] in html and TEXT["all_meetings"] in html
        assert ok(html)


def test_at_most_three_meetings_and_a_bad_link_leaves_the_words_without_a_link():
    rows = COMING + [{"date": "2026-12-09", "body": "Fourth", "meeting": None, "href": "x.html"}]
    rows[1] = {**rows[1], "href": "https://evil.example.com/x"}
    n = note_of(entry(), coming_up=rows)
    html = render.body_html(CTX, n, n["entries"])
    assert "Fourth" not in html and "evil" not in html
    assert len(styled(html, "coming")) == 3 and len([a for c in styled(html, "coming") for a in c.walk() if a.tag == "a"]) == 2


def test_the_text_twin_reads_the_same_content_in_the_same_order():
    n = note_of(*SEPT, *CONTRACTS, coming_up=COMING, date="2026-11-18",
                support_line="Please help.", support_url=config.SITE["support_url"])
    text = render.body_text(CTX, n, n["entries"])
    place = config.SITE["today_place"]
    order = [config.SITE["site_name"], config.SITE["site_place"], f"Wednesday in {place}", "November 18, 2026",
             CTX["email_line"], f"Good morning, {place}.", TEXT["tagline"], TEXT["new_on_list"], "My two seats",
             "Fixture Council, September 3, 2026 regular session", "Contracts", "Paving: Award Letter",
             TEXT["plain_words"], TEXT["define_ordinance"], TEXT["define_rfp"], TEXT["take_part"],
             TEXT["take_part_heading"], TEXT["invited"], TEXT["coming_up"],
             "December 3, 2026: Fixture Council, regular session", TEXT["all_meetings"], CTX["text"]["why"],
             CTX["notice"], "Please help."]
    at = [text.find(w) for w in order]
    assert -1 not in at and at == sorted(at), list(zip(order, at))
    assert f"{TEXT['all_meetings']}: {SITE_URL}today.html" in text and SITE_URL + COMING[2]["href"] in text


# ------------------------------------------------------------------ "Read it in plain words." (concept C)
def test_only_the_definitions_of_kinds_in_the_edition_are_listed():
    seats = render.body_html(CTX, note_of(*SEPT), SEPT)
    assert [x.all_text() for x in styled(seats, "define")] == [TEXT[k] for k in ("define_ordinance", "define_minutes")]
    res = [vote(1, 2, item_number="RESOLUTION 1-2026-27"), vote(2, 3, item_number="ORDINANCE 2-2026-27")]
    assert [x.all_text() for x in styled(html_of(*res), "define")] == \
        [TEXT[k] for k in ("define_ordinance", "define_resolution", "define_minutes")]
    contracts = html_of(*CONTRACTS)
    assert [x.all_text() for x in styled(contracts, "define")] == \
        [TEXT[k] for k in ("define_bid_tab", "define_award_letter", "define_rfp")]
    assert node_texts(contracts, "h2")[-2] == TEXT["plain_words"]
    # the term is bold, the definition plain, both config text word for word
    d = styled(contracts, "define")[0]
    assert [s.all_text() for s in d.walk() if s.tag == "strong"] == ["Bid tab."]
    none = html_of(entry(title="A budget amendment", source={"url": "https://example.com/a.pdf", "page": None}))
    assert not styled(none, "words") and TEXT["plain_words"] not in none


def test_the_shipped_definitions_are_concept_cs_words():
    assert [TEXT[f"define_{k}"] for k, _ in render.KINDS] == [
        "Ordinance. A local law.", "Resolution. A formal decision or statement that is not a law.",
        "Minutes. The official written record of a meeting.", "Bid tab. A table of the bids received and their prices.",
        "Award letter. The letter that names the bidder chosen.",
        "RFP. A request for proposals: a government asking for offers to provide a service or product."]


def test_the_shipped_intro_and_invitation_promise_only_what_holds():
    """note-sunrise/intro-every-item-links: some sources are not public; note-sunrise/executive-session-reads-closed:
    an executive session is not open to anyone, so the heading says the meetings are open to the public."""
    assert TEXT["intro"] == ("Here is what is new on {site_name} for the lists you picked. Each item links to its "
                             "official source where the source is public.")
    assert TEXT["take_part_heading"] == "This is your government. Its meetings are open to the public."
    assert TEXT["invited"] == "You are invited."


# ------------------------------------------------------------------ every new slot: hostile text stays inert
def test_hostile_text_in_every_new_slot_comes_out_inert_and_passes_the_deliver_check():
    ctx = {**CTX, "place": HOSTILE, "site_place": HOSTILE, "site_name": HOSTILE,
           "text": {**CTX["text"], **{k: HOSTILE + " {n} {date} {body} {meeting} {place} {weekday} {site_name}"
                                      for k in render.TEXT_KEYS if k != "subject"}}}
    ctx["text"]["define_ordinance"] = "Ordinance. " + HOSTILE
    hostile_row = {"date": "2026-12-01", "body": HOSTILE, "meeting": HOSTILE, "href": "a.html"}
    bad_rows = [{"date": HOSTILE, "body": "x", "meeting": None, "href": "b.html"},
                {"date": "2026-12-02", "body": "y", "meeting": None, "href": HOSTILE}]
    es = [entry(title=HOSTILE, body_name=HOSTILE, recorded=HOSTILE, meeting=HOSTILE),
          entry(id="c", meeting_date=None, title=HOSTILE, body_name=HOSTILE, recorded=HOSTILE),
          *[vote(k, k, body_name=HOSTILE, item_number="ORDINANCE " + HOSTILE) for k in (1, 2)]]
    n = note_of(*es, coming_up=[hostile_row, *bad_rows], unplaced_text=HOSTILE)
    for c in (ctx, {**ctx, "budget": 3000}):
        html = render.body_html(c, n, n["entries"])
        assert ok(html), html
        assert "{{" not in html and "{%" not in html and "<script" not in html and "evil.example.com" not in "".join(links(html))
        assert set(links(html)) <= {SITE_URL + x for x in ("a.html", "today.html", "morning/index.html", "items/2026.html#i-x",
                                                           "city/meetings/2026.html#2026-09-03-regular")} | \
            {"https://example.com/fixture/agenda.pdf#page=2", "https://example.com/fixture/agenda.pdf",
             "https://example.com/fixture/minutes-2026-09-03.pdf"}
        tags = {x.tag for x in parse(html).walk()} - {"root"}
        assert tags <= {"div", "table", "tr", "td", "h1", "h2", "h3", "p", "span", "a", "br", "strong", "img"}


@pytest.mark.parametrize("n", range(300))
def test_random_text_in_the_new_slots_always_gives_a_body_deliver_accepts(n):
    import random

    from test_morning_sender_render import _PIECES
    rnd = random.Random(20261122 + n)
    t = ["".join(rnd.choice(_PIECES) for _ in range(rnd.randint(0, 20))) for _ in range(6)]
    ctx = {**CTX, "place": t[0], "site_place": t[1]}
    rows = [{"date": "2026-12-01", "body": t[2], "meeting": t[3], "href": "a.html"}]
    es = [entry(title=t[4]), entry(id="u", meeting_date=None, body_name=t[5]), *[vote(k, k, item_number=t[k]) for k in (1, 2)]]
    nn = note_of(*es, coming_up=rows)
    assert ok(render.body_html(ctx, nn, nn["entries"])), t


# ------------------------------------------------------------------ deliver.body_ok: exact tags only
def _good() -> str:
    n = note_of(*SEPT, *CONTRACTS, coming_up=COMING, support_line="Please help.", support_url=config.SITE["support_url"])
    return render.body_html(CTX, n, n["entries"])


def test_the_full_layout_passes_and_every_tag_render_wrote_is_a_shared_constant():
    html = _good()
    assert ok(html)
    known = set(common.TAG.values()) | {"<br>", common.CREDIT_LINE}
    assert html.count(common.CREDIT_LINE) == 1
    for tag in re.findall(r"<(?!/)[^<>]*>", html.replace(common.CREDIT_LINE, "")):
        if tag.startswith("<a href="):
            assert any(tag.endswith(end) for end in common.LINKS.values()), tag
        else:
            assert tag in known, tag
    assert html.count("<img ") == 1 and "url(" not in html and "background-image" not in html


CARD = common.TAG["card"]
TAMPERED = [
    CARD.replace('">', 'position:fixed;">'), CARD.replace("#FFFFFF", "#FFFFFE"), CARD.replace("<div ", '<div onclick="x" '),
    CARD.replace('">', '" class="x">'), CARD.replace("<div", "<DIV"), CARD.replace(";", "; ", 1),
    CARD.replace('style="', "style='").replace('">', "'>"), CARD.replace('">', '" >'),
]


@pytest.mark.parametrize("bad", TAMPERED)
def test_an_unknown_attribute_or_style_is_refused(bad):
    html = _good()
    assert CARD in html
    assert not ok(html.replace(CARD, bad, 1))


@pytest.mark.parametrize("swap", [
    lambda h: h.replace(common.LINKS["ink"], '" style="color:#0F1F3D;">', 1),                  # another link style
    lambda h: h.replace(common.LINKS["ink"], '" onclick="x' + common.LINKS["ink"], 1),
    lambda h: h.replace(f'<a href="{SITE_URL}', '<a href="https://evil.example.com/', 1),        # a host not allowed
    lambda h: h.replace(common.TAG["sun"] + "</span>", common.TAG["sun"] + "Click here</span>", 1),  # words in the sun
    lambda h: h.replace(common.TAG["mark"] + "</span>", common.TAG["mark"] + "x</span>", 1),
    lambda h: h.replace(common.TAG["card"] + "\n", common.TAG["card"], 1),                     # two tags on a line
    lambda h: h.replace("</h3>\n", "</h3>" + common.TAG["line"] + "x</p>\n", 1),                # two blocks on a line
    lambda h: h.replace("</table>\n", "", 1),                                                   # a container left open
    lambda h: h.replace("</div>\n", "</div>\n</div>\n", 1),                                     # one closed twice
    lambda h: h.replace(common.TAG["h3"], common.TAG["h1"], 1).replace("</h3>", "</h1>", 1),     # a second h1
    lambda h: h.replace("</strong>", "", 1),                                                    # an inline tag left open
    lambda h: h.replace("<strong>", "<strong>" + common.TAG["line"], 1),                         # a block inside a line
    lambda h: h.replace(common.TAG["page"], common.TAG["sheet"], 1),                             # not the first line
    lambda h: h[:-7],                                                                            # cut short
    lambda h: h.replace("\n", "\n\n", 1), lambda h: h.replace("\n" + common.TAG["sky"], "\n  " + common.TAG["sky"], 1),
    lambda h: h.replace("</td>\n", "</td>\nloose text\n", 1),                                   # text on its own line
    lambda h: h.replace(common.TAG["intro"], common.TAG["intro"] + "evil.example/login ", 1),
    lambda h: h.replace(common.TAG["intro"], common.TAG["intro"] + "{{ x }} ", 1),
    lambda h: h.replace(common.CREDIT_LINE, common.CREDIT_LINE.replace("160", "1"), 1),
])
def test_a_tampered_body_is_refused(swap):
    html = _good()
    bad = swap(html)
    assert bad != html and not ok(bad)


def test_a_tampered_constant_in_render_fails_the_plan_not_the_morning(msite, monkeypatch):  # noqa: F811
    """If render's tags drift from the ones deliver holds (an edit to one copy only), the plan stage refuses the
    edition it wrote (PlanError), so the gap shows in the rehearsal, never as a day lost at 7:00."""
    built = plan_mod.build(msite, D, cfg_with())
    assert built["plan"]["editions"]
    tampered = {**common.TAG, "card": common.TAG["card"].replace('">', 'position:fixed;">')}
    monkeypatch.setattr(render, "TAG", tampered)
    with pytest.raises(plan_mod.PlanError, match="body check refuses"):
        plan_mod.build(msite, D, cfg_with())


def test_deliver_holds_its_own_copy_of_the_tags():
    """A change to common.TAG at run time (after import) widens nothing: deliver's sets were made at import."""
    html = _good()
    saved = copy.deepcopy(common.TAG)
    try:
        common.TAG["card"] = common.TAG["card"].replace('">', 'position:fixed;">')
        assert not ok(html.replace(saved["card"], common.TAG["card"]))
    finally:
        common.TAG.clear()
        common.TAG.update(saved)


def test_the_tag_constants_hold_nothing_a_template_or_markdown_step_could_read():
    for name, tag in {**common.TAG, **{f"link-{k}": '<a href="x' + v for k, v in common.LINKS.items()}}.items():
        assert not re.search(r"[{}\n\\`]|  |url\(|expression|position|!important|javascript", tag, re.I), name
        assert tag.startswith("<") and tag.endswith(">") and tag.count("<") == tag.count(">") == 1, name


# ------------------------------------------------------------------ the size rule (Gmail clips at about 102 KB)
def _many(k: int, title_len: int = 200) -> list[dict]:
    return [entry(id=f"county/item/{i}", title=f"FIXTURE item {i} " + "word " * (title_len // 5),
                  meeting_date=f"2026-{1 + i % 12:02d}-{1 + i % 28:02d}") for i in range(k)]


def test_a_small_edition_has_every_entry_as_a_card():
    html = html_of(*_many(10))
    assert len(styled(html, "card")) == 10 and not styled(html, "row") and TEXT["more"].split(" ", 1)[1] not in html


def test_a_large_edition_stays_under_the_budget_with_its_footer_and_rest_as_rows():
    es = _many(100)
    n = note_of(*es, support_line="Please help.", support_url=config.SITE["support_url"], coming_up=COMING)
    html = render.body_html(CTX, n, n["entries"])
    size = len(html.encode("utf-8"))
    assert size <= common.BODY_BUDGET, size
    items, rows = styled(html, "item"), styled(html, "row")
    assert items and rows and len(items) + len(rows) == 100
    # the cards come first, in the edition's order with each meeting's items together (note-titles round 3), then
    # one row each for the rest
    order: dict = {}
    for i, e in enumerate(es):
        order.setdefault(e["meeting_date"], []).append(i)
    shown = [c.all_text() for c in items + rows]
    assert [next(i for i, e in enumerate(es) if f"item {i} " in s) for s in shown] == [i for g in order.values() for i in g]
    assert CTX["notice"] in parse(html).all_text() and common.CREDIT_LINE in html and "Please help." in html
    assert TEXT["all_meetings"] in html and ok(html)
    # the row keeps the entry's words and both links
    r = rows[0]
    assert {a.attrs["href"] for a in r.walk() if a.tag == "a"} == {SITE_URL + "items/2026.html#i-x",
                                                                   "https://example.com/fixture/agenda.pdf#page=2"}


def test_a_huge_edition_ends_its_list_with_n_more_on_the_site():
    es = _many(400, title_len=590)
    n = note_of(*es, support_line="Please help.", support_url=config.SITE["support_url"])
    html = render.body_html(CTX, n, n["entries"])
    assert len(html.encode("utf-8")) <= common.BODY_BUDGET and ok(html)
    rows = styled(html, "row")
    more = rows[-1]
    hidden = 400 - len(styled(html, "card")) - (len(rows) - 1)
    assert hidden > 0 and more.all_text() == TEXT["more"].replace("{n}", str(hidden))
    assert [a.attrs["href"] for a in more.walk() if a.tag == "a"] == [SITE_URL + "morning/index.html"]
    assert CTX["notice"] in parse(html).all_text() and html.rstrip().endswith("</div>")
    text = render.body_text(CTX, n, n["entries"])
    assert f"{TEXT['more'].replace('{n}', str(hidden))}: {SITE_URL}morning/index.html" in text
    assert text.count("FIXTURE item ") == 400 - hidden


@pytest.mark.parametrize("budget", [20_000, 40_000, 60_000])
def test_any_budget_is_kept(budget):
    n = note_of(*_many(150, 300))
    html = render.body_html({**CTX, "budget": budget}, n, n["entries"])
    assert len(html.encode("utf-8")) <= budget and ok(html)


def test_the_shipped_budget_leaves_room_under_gmails_clip():
    assert 60_000 <= common.BODY_BUDGET <= 90_000


# ------------------------------------------------------------------ config: every new word, checked
def test_every_new_word_is_config_text_and_passes_the_neutrality_scan(msite):  # noqa: F811
    assert set(TEXT) - set(morning.topic_text_keys(config.SITE)) == set(render.TEXT_KEYS) == set(morning.SENDER_TEXT_KEYS)
    ours = render.own_text(CTX, {**read_note(msite), "coming_up": COMING})
    for k in [*render.TEXT_KEYS, *morning.topic_text_keys(config.SITE)]:
        assert TEXT[k] in ours or render.subject(CTX, D.isoformat()) in ours, k
    assert "Fixture County Budget Committee" in ours and "executive session" in ours
    assert not [t for t in ours if BANNED.search(t)]


@pytest.mark.parametrize("key, value, problem", [
    ("greeting", "Good morning.", "must contain {place}"), ("header_day", "{weekday}", "must contain {place}"),
    ("coming_meeting", "{date}: {body}", "must contain {meeting}"), ("more", "More on the site", "must contain {n}"),
    ("source_meeting", "Source", "must contain {date}"), ("define_rfp", "RFP: proposals", "Term. Definition"),
    ("invited", "", "must be set")])
def test_the_build_refuses_a_new_text_without_its_placeholders(key, value, problem):
    cfg = copy.deepcopy(config.SITE)
    assert morning.problems(cfg) == []
    cfg["morning_note"]["sender"]["text"][key] = value
    assert any(key in p and problem in p for p in morning.problems(cfg)), morning.problems(cfg)


def test_the_deliver_jobs_reader_still_matches_pyyaml():
    assert morning.reader_problems() == []


# ------------------------------------------------------------------ the note's coming_up (build time, from the records)
def _rows():
    """days.meeting_rows() shape: the day page's meeting cards, soonest first."""
    return [
        {"iso": "2026-11-17", "body": "School Board", "title": "Formal board meeting", "href": "school/a.html", "cancelled": False},
        {"iso": "2026-11-18", "body": "Montgomery Budget Committee", "title": "Budget Committee", "href": None, "cancelled": False},
        {"iso": "2026-11-20", "body": "Council", "title": "Special session", "href": "c/x.html", "cancelled": True},
        {"iso": "2026-12-01", "body": "Council", "title": "Executive session", "href": None, "cancelled": False},
        {"iso": "2026-12-03", "body": "Council", "title": None, "href": "c/z.html", "cancelled": False},
        {"iso": "2026-12-09", "body": "Council", "title": "Council, regular session", "href": "c/w.html", "cancelled": False}]


def test_coming_up_is_the_next_three_meetings_on_or_after_the_notes_day():
    got = morning.coming_up(date(2026, 11, 18), _rows())
    # always the day page's anchor (a meeting page's part number may move)
    assert got == [{"date": "2026-11-18", "body": "Montgomery Budget Committee", "meeting": None,
                    "href": "today.html#d-2026-11-18"},
                   {"date": "2026-12-01", "body": "Council", "meeting": "executive session", "href": "today.html#d-2026-12-01"},
                   {"date": "2026-12-03", "body": "Council", "meeting": None, "href": "today.html#d-2026-12-03"}]
    assert morning.coming_up(date(2027, 1, 1), _rows()) == [] and morning.coming_up(date(2026, 11, 1), None) == []
    # a called-off meeting (11-20) is never listed
    assert [r["date"] for r in morning.coming_up(date(2026, 11, 19), _rows())] == ["2026-12-01", "2026-12-03", "2026-12-09"]


def test_a_kind_label_that_starts_with_the_body_name_drops_it():
    """coming-kind-repeats-body: "Council, regular session" under the body "Council" reads "regular session"."""
    got = morning.coming_up(date(2026, 12, 4), _rows())
    assert got[0] == {"date": "2026-12-09", "body": "Council", "meeting": "regular session", "href": "today.html#d-2026-12-09"}


def test_a_kind_label_that_starts_with_the_end_of_the_body_name_drops_it():
    """coming-kind-repeats-body: "Budget Committee, special called meeting" under "Montgomery County Budget Committee"
    reads "special called meeting"; a label whose head the body name does not end with stays whole."""
    rows = [{"iso": "2026-12-02", "body": "Montgomery County Budget Committee", "title": "Budget Committee, special called meeting",
             "href": None, "cancelled": False},
            {"iso": "2026-12-03", "body": "Montgomery County Budget Committee", "title": "Audit Committee, joint meeting",
             "href": None, "cancelled": False}]
    assert [r["meeting"] for r in morning.coming_up(date(2026, 12, 1), rows)] == \
        ["special called meeting", "audit committee, joint meeting"]


def test_a_calendar_only_meeting_is_listed_and_a_called_off_one_is_not(tmp_path):
    """The owner's goal is the invitation: a council meeting the city calendar lists, with no agenda yet and not in
    the facts (a scheduled card), is in coming_up; one the calendar calls off is not."""
    import json as json_mod
    from types import SimpleNamespace

    from sitegen import days
    cal = tmp_path / "calendar.json"
    cal.write_text(json_mod.dumps([{"date": "2026-12-01", "kind": "executive", "title": "Executive Session"},
                                   {"date": "2026-12-03", "kind": "regular", "title": "Regular Session"},
                                   {"date": "2026-12-17", "kind": "regular", "title": "CANCELLED - Regular Session"}]),
                   encoding="utf-8")
    cix = SimpleNamespace(cfg={"calendar": str(cal), "record_url": "https://example.gov/portal", "record_label": "portal"},
                          fixture=False, slug="city", body_name="Fixture Council",
                          kind_labels={"regular": "Regular session", "executive": "Executive session"},
                          facts={"meetings": []})
    cards = days.council_cards(cix, date(2026, 11, 1), date(2026, 12, 31), date(2026, 11, 22))
    ctx = {"weeks": [{"days": [{"iso": d, "cards": [c]} for d, c in cards]}]}
    got = morning.coming_up(date(2026, 11, 22), days.meeting_rows(ctx))
    assert got == [{"date": "2026-12-01", "body": "Fixture Council", "meeting": "executive session", "href": "today.html#d-2026-12-01"},
                   {"date": "2026-12-03", "body": "Fixture Council", "meeting": "regular session", "href": "today.html#d-2026-12-03"}]


def test_the_note_writer_passes_its_meetings_to_coming_up(monkeypatch):
    seen = {}
    monkeypatch.setattr(morning, "coming_up", lambda d, rows: seen.update(d=d, rows=rows) or [])
    note = morning.day(date(2026, 11, 18), [], {}, meetings=_rows())
    assert note["coming_up"] == [] and seen == {"d": date(2026, 11, 18), "rows": _rows()}


# ------------------------------------------------------------------ the day claim leaves coming_up out
def _two_plans(msite, tmp_path):  # noqa: F811
    """Two plans of one day whose notes differ only in coming_up (a calendar change between the morning's builds)."""
    base = read_note(msite)
    one = {**base, "coming_up": []}
    two = {**base, "coming_up": [{"date": "2026-12-03", "body": "Fixture Council", "meeting": "regular session",
                                  "href": "today.html#d-2026-12-03"}]}
    p1 = plan_mod.build(site_with(tmp_path / "a", one), D, cfg_with())["plan"]
    p2 = plan_mod.build(site_with(tmp_path / "b", two), D, cfg_with())["plan"]
    return p1, p2


def test_coming_up_is_the_one_part_of_a_note_the_claim_does_not_read(msite, tmp_path):  # noqa: F811
    p1, p2 = _two_plans(msite, tmp_path)
    assert [e["body"] for e in p1["editions"]] != [e["body"] for e in p2["editions"]]
    assert TEXT["coming_up"] in p2["editions"][0]["body"] and TEXT["coming_up"] not in p1["editions"][0]["body"]
    assert p1["note_sha256"] == p2["note_sha256"] and deliver.plan_digest(p1) == deliver.plan_digest(p2)
    assert [e["key"] for e in p1["editions"]] == [e["key"] for e in p2["editions"]]          # keys: rows only
    # anything else in the note still changes both digests
    note = read_note(msite)
    assert common.note_digest(note) != common.note_digest({**note, "notice": note["notice"] + " x"})
    other = copy.deepcopy(p2)
    other["editions"][0]["body"] = other["editions"][0]["body"].replace(TEXT["why"], TEXT["why"] + " x")
    assert deliver.plan_digest(other) != deliver.plan_digest(p2)


def test_a_rerun_with_a_changed_coming_up_still_claims_the_day_and_sends_the_rest(msite, tmp_path):  # noqa: F811
    """A run stopped after its first email; the re-run's build lists another coming meeting. The re-run's plan is the
    same plan for the claim, so it creates the other editions and none twice."""
    from test_morning_sender_deliver import Fake, go, people
    p1, p2 = _two_plans(msite, tmp_path)
    fake = Fake(people(p1), fail={"create_email": [None] + [deliver.ProviderError("email create")]})
    res, _ = go(p1, fake)
    assert (res.status, res.editions, len(fake.created)) == ("failed", 1, 1)
    res, _ = go(p2, fake)
    assert (res.code, res.status, res.editions, len(fake.created)) == (0, "sent", 2, 3)
    editions = [x["metadata"]["note_edition"] for x in fake.created]
    assert len(editions) == len(set(editions)) == 3


# ------------------------------------------------------------------ definitions only of what is shown
def test_definitions_come_only_from_items_the_email_shows():
    """defs-of-hidden-items: past the size cut, a kind only the hidden items have gets no definition."""
    es = [entry(id=f"county/item/{i}", title=f"FIXTURE item {i} " + "word " * 100) for i in range(300)]
    es.append(entry(id="county/item/last", title="RESOLUTION 9: the last item"))
    n = note_of(*es)
    html = render.body_html(CTX, n, n["entries"])
    assert "RESOLUTION 9" not in html and TEXT["define_resolution"].split(". ", 1)[1] not in html
    small = html_of(entry(title="RESOLUTION 9: shown"))
    assert TEXT["define_resolution"].split(". ", 1)[1] in small


# ------------------------------------------------------------------ note-sunrise/budget-unenforced
def test_the_deliver_check_refuses_a_body_over_the_budget(msite):  # noqa: F811
    from test_morning_sender_deliver import settings
    plan = plan_mod.build(msite, D, cfg_with())["plan"]
    s = settings()
    deliver.check_plan(copy.deepcopy(plan), s.link_hosts, s.link_urls)
    body = plan["editions"][0]["body"]
    pad = common.TAG["intro"] + "x" * 200 + "</p>"
    big = body.replace(common.TAG["foot"], (pad + "\n") * (common.BODY_BUDGET // 200) + common.TAG["foot"], 1)
    assert deliver.body_ok(big, s.link_hosts, s.link_urls) and len(big.encode("utf-8")) > common.BODY_BUDGET
    bad = copy.deepcopy(plan)
    bad["editions"][0]["body"] = big
    with pytest.raises(deliver.PlanInvalid, match="body"):
        deliver.check_plan(bad, s.link_hosts, s.link_urls)


def test_the_plan_refuses_a_body_render_wrote_over_the_budget(msite, monkeypatch):  # noqa: F811
    monkeypatch.setattr(common, "BODY_BUDGET", 1000)
    monkeypatch.setattr(plan_mod.common, "BODY_BUDGET", 1000)
    with pytest.raises(plan_mod.PlanError, match="budget"):
        plan_mod.build(msite, D, cfg_with())


def test_every_note_carries_coming_up_the_same_for_every_reader(msite):  # noqa: F811
    note = read_note(msite)
    assert isinstance(note["coming_up"], list) and len(note["coming_up"]) <= 3
    assert all(r["date"] >= note["date"] for r in note["coming_up"])
    built = plan_mod.build(msite, D, cfg_with())
    if note["coming_up"]:
        first = render.coming(CTX, note)[0][0]
        assert all(render.inert(first) in ed["body"] for ed in built["plan"]["editions"])


def test_a_note_without_coming_up_still_plans(tmp_path):
    n = note_of(entry(lists=["budget"]))
    n.update(window={"from": "x", "to": "y"}, data_as_of="", counts={}, notice=CTX["notice"],
             email_line=CTX["email_line"], support_line="", support_url="")
    built = plan_mod.build(site_with(tmp_path, n), D, cfg_with())
    assert built["plan"]["editions"] and TEXT["coming_up"] not in built["plan"]["editions"][0]["body"]
