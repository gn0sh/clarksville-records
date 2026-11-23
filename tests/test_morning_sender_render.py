# ruff: noqa: E501
"""The morning note sender's renderer (T4.2: sender/render.py; architecture "T4 sender", Body). FIXTURE notes only.
A record's title is untrusted text that goes through the provider's template and Markdown step, so the tests feed
it markup of each kind and read the body back as HTML."""
import json
import re
from pathlib import Path

import pytest

from conftest import parse
from sitegen import config, morning
from sender import common, plan as plan_mod, render
from test_morning import D, inputs  # noqa: F401
from test_morning_sender_plan import NEXT, SITE_URL, cfg_with, msite, read_note  # noqa: F401
from test_site_neutrality import BANNED

ROOT = Path(__file__).resolve().parent.parent
CTX = render.context(cfg_with())
HOSTILE = "---\n<script>alert(1)</script> {{ subscriber.email }} {% for x in y %} [click](https://evil.example.com/) " \
          "![i](https://evil.example.com/p.png) <a href=\"javascript:alert(1)\">x</a> *bold* _em_ `code` # head\n\n" \
          "    indented\n> quote | cell ~~s~~ $x$ \\ 50% @someone"


def entry(**kw) -> dict:
    e = {"id": "county/item/x", "lists": ["budget"], "kind": "agenda_item", "body": "county",
         "body_name": "Fixture Commission", "meeting_date": "2026-11-16", "title": "FIXTURE: a resolution",
         "title_ours": False, "recorded": "On the agenda", "district": None, "ward": None, "case": None,
         "seat_body": "district", "href": "items/2026.html#i-x",
         "source": {"url": "https://example.com/fixture/agenda.pdf#page=2", "page": 2}}
    e.update(kw)
    return e


def note_of(*entries, **kw) -> dict:
    n = {"schema": morning.SCHEMA, "date": D.isoformat(), "backfill": False, "entries": list(entries),
         "lists": [{"key": x["key"], "label": x["label"]} for x in config.SITE["morning_note"]["lists"]],
         "unplaced_zoning": 0, "unplaced_text": ""}
    n.update(kw)
    return n


def html_of(*entries, ctx=CTX, **kw) -> str:
    n = note_of(*entries, **kw)
    return render.body_html(ctx, n, n["entries"])


def links(html: str) -> list[str]:
    return [n.attrs.get("href") for n in parse(html).walk() if n.tag == "a"]


TODAY = [SITE_URL + "today.html"]          # note/sunrise: the "Take part" box's button, the last link but support's
ALL_TAGS = {"div", "table", "tr", "td", "h1", "h2", "h3", "p", "span", "a", "br", "strong", "img"}   # common.TAG's


def styled(html: str, name: str) -> list:
    """Every element whose opening tag is common.TAG[name]."""
    want = parse(common.TAG[name] + "</x>").children[0].attrs
    return [n for n in parse(html).walk() if n.tag != "root" and n.attrs == want]


def paras(html: str) -> list[str]:
    """The footer's paragraphs before the credit, which always closes it (note/credit-logo): why, the notice, the
    support line."""
    out = [n.all_text().strip() for n in styled(html, "foot")[0].walk() if n.tag == "p"]
    assert out[-1] == common.CREDIT_TEXT and html.endswith(common.CREDIT_LINE + "\n</div>\n</div>\n</div>\n")
    return out[:-1]


def tags(html: str) -> set:
    return {n.tag for n in parse(html).walk()} - {"root"}


def cards(html: str) -> list:
    return styled(html, "card")


def card_text(card) -> str:
    """A card's words without its date block (the headline says the day)."""
    td = [n for n in card.walk() if n.tag == "td" and "aria-hidden" not in n.attrs]
    return (td[0] if td else card).all_text().strip()


def meeting_lines(html: str) -> list[str]:
    """Each card's heading (note-titles round 3): its meeting line, or with no meeting its body's name."""
    return [n.all_text() for c in cards(html) for n in c.walk() if n.tag == "h3"]


def items_of(html: str) -> list:
    """Each item's compact line in the cards (note-titles round 3)."""
    return styled(html, "item")


def headline_of(line) -> str:
    """An item line's headline: its words without the topic label and the muted labels after it (a meeting's
    untitled votes: the count line)."""
    skip = {id(n) for n in line.children if n.tag == "span"}
    return "".join(x if isinstance(x, str) else ("" if id(x) in skip or x.tag == "br" else x.all_text())
                   for x in line.parts).strip()


def titles(html: str) -> list[str]:
    """Each item's headline (note-titles): the record's title, or a meeting's untitled votes' count line."""
    return [headline_of(x) for x in items_of(html)]


def head_raw(html: str) -> str:
    """The first item's headline words as render wrote them (inside the link to the site's page, when it has one)."""
    line = next(x for x in html.split("\n") if x.startswith(common.TAG["item"]))
    inner = line[len(common.TAG["item"]):].rsplit("</p>", 1)[0]
    if inner.startswith(common.TAG["item_kick"]):
        inner = inner.split("</span> ", 1)[1]
    inner = inner.split(" " + common.TAG["muted"], 1)[0]
    return inner.split(common.LINKS["ink"], 1)[1].rsplit("</a>", 1)[0] if inner.startswith("<a href=") else inner


def head_text(html: str) -> str:
    return titles(html)[0]


# ------------------------------------------------------------------ untrusted titles come out inert
def test_a_hostile_title_comes_out_inert():
    html = html_of(entry(title=HOSTILE))
    assert tags(html) <= ALL_TAGS                                                       # only the tags we write
    # note-titles round 3: the meeting's document once (no page), then the item's page on its headline
    assert links(html) == ["https://example.com/fixture/agenda.pdf", SITE_URL + "items/2026.html#i-x"] + TODAY
    title = head_raw(html)
    # nothing the provider's template step or a Markdown step could read as markup is left as a plain character
    assert not re.search(r"[<>{}\[\]()*_`#\\~|!$%@=]", re.sub(r"&#\d+;", "", title)), title
    assert not title.startswith("-") and "\n" not in title and "  " not in title
    assert "{{" not in html and "{%" not in html and "---" not in html and "](" not in html
    # and a reader still sees the record's own words, unchanged apart from the whitespace, cut at a word to the
    # headline's length (note-titles; the site's page carries all of it)
    shown = head_text(html).replace("\u200b", "")
    assert shown.endswith("…") and " ".join(HOSTILE.split()).startswith(shown[:-1])
    assert len(shown) <= render.HEADLINE_MAX + 1


def test_every_field_of_an_entry_is_escaped_not_only_the_title():
    html = html_of(entry(body_name="<b>{{ x }}</b>", recorded="{% y %} [z](https://evil.example.com)"))
    assert tags(html) == ALL_TAGS
    assert "{{" not in html and "{%" not in html and "evil.example.com" not in "".join(links(html))


def test_the_body_has_no_blank_or_indented_line():
    """One HTML block from first line to last: a Markdown step finds no paragraph break and no code block."""
    lines = html_of(entry(title=HOSTILE), entry(id="b", title="second")).split("\n")
    assert lines[-1] == "" and all(line and line[0] == "<" for line in lines[:-1])


def test_control_and_direction_characters_are_dropped_and_a_long_title_is_cut():
    assert render.clean("a‮b\x00c​d\te") == "abcd e"
    long = "x" * 5000
    assert render.clean(long) == "x" * render.MAX_TITLE + render.CUT
    assert len(html_of(entry(title=long))) - len(html_of(entry(title="x"))) < 2000


# ------------------------------------------------------------------ links: the site's pages and https sources only
@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://example.com/a.pdf", "//example.com/a.pdf", "",
                                 None, "https://example.com/a b.pdf", "https://example.com/\"onclick=\"x",
                                 "data:text/html,x", "ftp://example.com/a", 7])
def test_a_source_url_that_is_not_plain_https_gives_no_link(url):
    html = html_of(entry(source={"url": url, "page": 3}))
    assert links(html) == [SITE_URL + "items/2026.html#i-x"] + TODAY
    assert config.SITE["morning_note"]["page"]["source_label"] not in html         # no "Source" words without a link


def test_braces_in_a_source_url_cannot_reach_the_template_step():
    html = html_of(entry(source={"url": "https://example.com/a?b={{subscriber.email}}&c=1", "page": None}))
    assert "{{" not in html and "}}" not in html
    assert links(html) == [SITE_URL + "items/2026.html#i-x"] + TODAY                    # a brace in a URL: no link at all


@pytest.mark.parametrize("href", ["https://evil.example.com/", "//evil.example.com/x", "/abs.html", "../up.html",
                                  "a/../../b.html", "javascript:alert(1)", "a b.html", "x.html?next=//evil", None, ""])
def test_an_href_that_is_not_a_plain_site_path_gives_no_site_link(href):
    assert links(html_of(entry(href=href))) == ["https://example.com/fixture/agenda.pdf"] + TODAY


@pytest.mark.parametrize("site_url", ["", "http://records.example.com/", "https://records.example.com",
                                      "javascript:alert(1)//", "https://records.example.com/?x=", None])
def test_no_site_link_without_a_proper_site_url(site_url):
    ctx = {**CTX, "site_url": site_url}
    assert links(html_of(entry(), ctx=ctx)) == ["https://example.com/fixture/agenda.pdf"]


def test_site_links_are_site_url_plus_href_for_every_fixture_entry(msite):  # noqa: F811
    note = read_note(msite)
    html = render.body_html(CTX, note, note["entries"])
    got = links(html)
    with_href = [e for e in note["entries"] if e["href"]]
    assert with_href and all(SITE_URL + e["href"] in got for e in with_href)        # every real href is linkable
    # note-titles round 3: a meeting's documents once each, without their page (the site's page gives it); an
    # entry with no meeting links its own source
    docs = {e["source"]["url"] if not e.get("meeting_date") else e["source"]["url"].split("#")[0]
            for e in note["entries"]}
    assert all(u in got for u in docs)
    assert got[-1] == note["support_url"]                                        # and the support link, last
    assert all(u.startswith(SITE_URL) or u in docs for u in got[:-1])


# ------------------------------------------------------------------ our own words: config text, neutral
def test_own_text_passes_the_neutrality_scan(msite):  # noqa: F811
    note = read_note(msite)
    ours = render.own_text(CTX, note)
    assert ours and not [t for t in ours if BANNED.search(t)]
    # note-titles: each topic of morning_note.subject_topics adds its two subject phrases
    assert set(config.SITE["morning_note"]["sender"]["text"]) - set(morning.topic_text_keys(config.SITE)) == set(render.TEXT_KEYS) == \
        set(morning.SENDER_TEXT_KEYS)
    assert render.subject(CTX, "2026-11-11") == "Daylight morning note, November 11, 2026" == ours[0]


def test_every_word_outside_the_record_is_config_text():
    """Change every config text and label: nothing of the old wording is left, so none of it is hard-coded."""
    text = {k: " ".join([f"W{k.replace('_', '').upper()}", *marks]) for k, marks in render.TEXT_KEYS.items()}
    text["subject"] = "{site_name} S {date}"
    text["define_minutes"] = "WTERM. WMEANS"
    # note-titles: the kicker is a topic's config label (morning_note.subject_topics)
    ctx = {"site_name": "SITE", "site_url": SITE_URL, "source_label": "SRC", "page_label": "PG", "text": text,
           "topics": [{"key": "budget", "label": "KBUDGET", "lists": ["budget"]}],
           "notice": "NOTICE", "email_line": "LINE", "support_label": "TIPS", "place": "PLACE", "site_place": "PLATE",
           "today_href": "today.html", "note_href": "morning/index.html",
           "link_hosts": ("records.example.com", "example.com"), "link_urls": ("https://tips.example.com/x",)}
    # and one compact group of untitled votes (note-compact/config-text-test): its count line is config text too
    group = [vote(k, k, body_name="BODY", recorded="REC", title="TITLE", item_number=num) for k, num in ((1, "NUMA"), (2, "NUMB"))]
    rows = [{"date": "2026-12-01", "body": "CBODY", "meeting": "CMEET", "href": "a.html"},
            {"date": "2026-12-02", "body": "CBODY", "meeting": None, "href": "b.html"}]
    # and a vote titled from its meeting's agenda (note-titles): the agenda link's words are config text too
    agenda = vote(9, 9, body_name="BODY", recorded="REC", title="TITLE", item_number="NUMC", lists=["budget"],
                  title_ours=False, untitled=False,
                  title_source={"kind": "agenda", "source_id": "src-a", "page": 3, "meeting_id": "m",
                                "url": "https://example.com/fixture/agenda.pdf#page=3"})
    # one titled from an earlier meeting's agenda: that agenda's day in the link's words (title_agenda_dated)
    earlier = vote(8, 8, body_name="BODY", recorded="REC", title="TITLE", item_number="NUMD", lists=["budget"],
                   title_ours=False, untitled=False,
                   title_source={"kind": "agenda", "source_id": "src-b", "page": 1, "meeting_id": "2026-11-16-formal",
                                 "url": "https://example.com/fixture/agenda-b.pdf#page=1"})
    n = note_of(entry(body_name="BODY", recorded="REC", title="TITLE"),
                entry(id="u", meeting_date=None, body_name="BODY", recorded="REC", title="TITLE"), *group, agenda,
                earlier,
                unplaced_text="UNPLACED", support_line="SUPPORT", support_url="https://tips.example.com/x", coming_up=rows)
    n["lists"] = [{"key": k, "label": f"L-{k}"} for k in morning.LIST_KEYS]
    html = render.body_html(ctx, n, n["entries"])
    paras(html)                 # the credit is the site footer's fixed wording (note/credit-logo), not config text
    shown = " ".join(t for node in parse(html.replace(common.CREDIT_LINE, "")).walk() for t in node.text)
    words = re.sub(r"November 1[16]|December [12], 2026|September 3, 2026|Wednesday|Nov|Sep|\d", "", shown)
    # note-titles round 3: a meeting's card names its documents "Source document" (its line says the day);
    # source_meeting stands in the size rule's rows
    used = ["header_day", "greeting", "tagline", "intro", "new_on_list", "source_document",
            "plain_words", "take_part", "take_part_heading", "take_part_line", "invited", "coming_up",
            "coming_meeting", "coming_body", "all_meetings", "why", "untitled_votes", "title_agenda",
            "title_agenda_dated", "title_agenda_page", "title_agenda_page_dated"]
    assert sorted(set(re.findall(r"[A-Za-z-]+", words))) == sorted(
        ["SITE", "PLATE", "PLACE", "L-budget", "L-seats", "BODY", "REC", "TITLE", "PG", "UNPLACED", "NOTICE",
         "LINE", "SUPPORT", "TIPS", "NUMA", "NUMB", "CBODY", "CMEET", "WTERM", "WMEANS", "KBUDGET"] +
        [f"W{k.replace('_', '').upper()}" for k in used])
    assert "WUNTITLEDVOTES 2" in html and "NUMA, NUMB" in html
    # the page link's words stand in the size rule's rows (note-titles round 3: the plain text gives each item's
    # page after it, the meeting's after its line)
    cut = render.body_html({**ctx, "budget": len(html) - 400}, n, n["entries"])
    assert "WOPENSITE" in cut and "WSOURCEMEETING" in cut and len(cut) <= len(html) - 400
    assert render.subject(ctx, "2026-11-11") == "SITE S November 11, 2026"


@pytest.mark.parametrize("path", sorted((ROOT / "sender").glob("*.py")), ids=lambda p: p.name)
def test_no_locality_name_is_hard_coded_in_the_sender(path):
    assert not re.search(r"Montgomery|Clarksville|Tennessee|\bTN\b", path.read_text(encoding="utf-8")), path.name


def test_no_person_is_named_and_no_outcome_or_tally_is_printed(msite, inputs):  # noqa: F811
    """The email adds nothing the preview page does not show: no mover, seconder or dissenter, no official's name
    or id, and no outcome or tally for any vote (so an unconfirmed one can never show either)."""
    note = read_note(msite)
    built = plan_mod.build(msite, D, cfg_with())
    raw = json.dumps(built["plan"]) + "".join(built["texts"].values())
    for name in ("Fixture Mover", "Fixture Seconder", "Fixture Nay"):
        assert name not in raw
    for o in inputs["county"]["officials"]:
        assert o["name"] not in raw and o["id"] not in raw
    votes = [e for e in note["entries"] if e["kind"] == "vote"]
    assert [e for e in votes if e.get("confirmed") is False] and [e for e in votes if e.get("outcome")]
    assert "Motion passes" not in raw and "5-1" not in raw
    for e in votes:
        for value in (e.get("outcome"), e.get("tally")):
            assert not value or value not in raw
    unconfirmed = config.SITE["morning_note"]["text"]["vote_unconfirmed"]
    assert unconfirmed in raw                                         # an unconfirmed vote says so, in config text


# ------------------------------------------------------------------ the same entries, in the preview page's order
def _preview_rows(html: str) -> list[dict]:
    rows = []
    for li in parse(html).walk():
        if li.tag == "li" and "mn-entry" in li.attrs.get("class", "") and "data-unplaced" not in li.attrs:
            title = next(n for n in li.walk() if n.tag == "p" and n.attrs.get("class") == "mn-title")
            rows.append({"lists": li.attrs["data-lists"].split(), "seat_body": li.attrs.get("data-seat-body"),
                         "district": int(li.attrs["data-district"]) if "data-district" in li.attrs else None,
                         "ward": int(li.attrs["data-ward"]) if "data-ward" in li.attrs else None,
                         "title": title.all_text()})
    return rows


@pytest.mark.parametrize("lists, district, ward", [
    (["zoning", "seats", "budget", "contracts"], 7, 3), (["seats"], 5, None), (["seats"], None, 2),
    (["budget"], None, None), (["zoning"], 7, None), (["contracts", "budget"], None, None)])
def test_an_editions_entries_and_order_equal_the_preview_pages(msite, lists, district, ward):  # noqa: F811
    """The preview page (morning/index.html) shows the day the site was built on; the plan for that day, for the
    same lists and seats, lists the same titles in the same order."""
    note = read_note(msite, NEXT)
    page = _preview_rows((msite / "morning" / "index.html").read_text(encoding="utf-8"))
    assert len(page) == len(note["entries"]) > 0
    seats = {"district": district, "ward": ward}
    shown = [r["title"] for r in page if any(k in r["lists"] and morning._seat_match(r, k, seats) for k in lists)]
    p = plan_mod.build(msite, NEXT, cfg_with())["plan"]
    key = p["signatures"].get(common.signature(lists, district, ward))
    if not shown:
        assert key is None
        return
    body = next(e["body"] for e in p["editions"] if e["key"] == key)
    got = titles(body)
    # the same entries as the page; the email groups them under the list that selected each (plan.placed), keeping
    # the page's order within a list
    assert sorted(got) == sorted(shown)
    by_id = {e["id"]: e for e in note["entries"]}
    assert got == [by_id[i]["title"] for i, _ in plan_mod.placed(note, lists, seats)]
    under = dict(plan_mod.placed(note, lists, seats))
    for k in morning.LIST_KEYS:
        assert [t for t in got if t in {by_id[i]["title"] for i, x in under.items() if x == k}] == \
            [t for t in shown if t in {by_id[i]["title"] for i, x in under.items() if x == k}]


def test_at_least_one_preview_comparison_has_entries(msite):  # noqa: F811
    p = plan_mod.build(msite, NEXT, cfg_with())["plan"]
    assert p["signatures"].get("seats|5|-") or p["signatures"].get("budget,contracts,seats,zoning|7|3")


def test_sections_follow_the_notes_order_under_config_labels(msite):  # noqa: F811
    note = read_note(msite)
    labels = {x["key"]: x["label"] for x in note["lists"]}
    secs = render.sections(note, note["entries"])
    assert [e["id"] for _, rows in secs for e in rows] == [e["id"] for e in note["entries"]]
    assert [label for label, _ in secs] == [labels[k] for k in morning.LIST_KEYS if any(e["lists"][0] == k for e in note["entries"])]
    html = render.body_html(CTX, note, note["entries"])
    assert [n.all_text() for n in styled(html, "h2")] == [label for label, _ in secs]


def test_unplaced_line_and_why_line_close_the_entries_then_the_notice():
    html = html_of(entry(), unplaced_text="2 zoning cases printed no district or ward")
    assert [n.all_text() for n in styled(html, "note")] == ["2 zoning cases printed no district or ward"]
    assert html.index("2 zoning cases") > html.rindex(common.TAG["card"]) and paras(html) == [CTX["text"]["why"], CTX["notice"]]
    assert paras(html_of(entry()))[-2:] == [CTX["text"]["why"], CTX["notice"]]
    assert "unsubscribe" not in html.lower()                           # the provider's link, not ours


def test_the_text_version_reads_the_same_edition():
    n = note_of(entry(title="A  title\nover two lines"), unplaced_text="1 zoning case printed no district or ward")
    text = render.body_text(CTX, n, n["entries"])
    assert "A title over two lines" in text and SITE_URL + "items/2026.html#i-x" in text
    assert "https://example.com/fixture/agenda.pdf" in text and text.rstrip().endswith(CTX["notice"])
    assert CTX["text"]["why"] in text and CTX["email_line"] in text


# ------------------------------------------------------------------ note/entry-meeting
TWO = (entry(id="county/item/26-11-4/2026-11-02-informal", meeting_date="2026-11-02", meeting="informal meeting"),
       entry(id="county/item/26-11-4/2026-11-09-formal", meeting_date="2026-11-09", meeting="formal meeting"))


def test_each_entry_names_its_meeting_day_and_kind_in_both_bodies():
    """Two agendas of one item (real data: 26-11-4, the Nov 2 informal and Nov 9 formal agendas) read as two
    meetings, not a duplicate. The line is config morning_note.text.meeting_line filled with the record's own body,
    day and the site's kind label."""
    line = config.SITE["morning_note"]["text"]["meeting_line"]
    want = [line.replace("{body}", "Fixture Commission").replace("{date}", d).replace("{meeting}", k)
            for d, k in (("November 2, 2026", "informal meeting"), ("November 9, 2026", "formal meeting"))]
    assert want == ["Fixture Commission, November 2, 2026 informal meeting",
                    "Fixture Commission, November 9, 2026 formal meeting"]
    n = note_of(*TWO)
    text, html = render.body_text(CTX, n, n["entries"]), render.body_html(CTX, n, n["entries"])
    assert [f"  {w}" in text.split("\n") for w in want] == [True, True]
    shown = [card_text(x) for x in cards(html)]
    assert [sum(w in s for s in shown) for w in want] == [1, 1]


@pytest.mark.parametrize("kw", [{"meeting": None}, {"meeting": "  "}, {"meeting_date": None},
                                {"meeting_date": "2026-13-40"}, {"meeting_date": "Nov 9"}, {"meeting": 3}])
def test_an_entry_without_a_meeting_is_its_body_alone(kw):
    e = entry(**{"meeting": "formal meeting", **kw})
    assert render.who_when(CTX, e) == "Fixture Commission"
    assert "None" not in render.body_text(CTX, note_of(e), [e])


@pytest.mark.parametrize("body", [None, "", "  ", "\u200b"])
def test_an_entry_with_no_body_name_reads_date_and_meeting_only(body):
    """CR6: no "None, " and no leading ", ": the meeting line's own tail, "<date> <meeting>"."""
    e = entry(body_name=body, meeting="formal meeting", meeting_date="2026-11-09")
    assert render.who_when(CTX, e) == "November 9, 2026 formal meeting"
    assert "  November 9, 2026 formal meeting" in render.body_text(CTX, note_of(e), [e]).split("\n")


def test_the_meeting_words_are_escaped_like_every_other_field():
    e = entry(meeting="<b>{{ x }}</b> [z](https://evil.example.com)")
    html = html_of(e)
    assert tags(html) == ALL_TAGS
    assert "{{" not in html and "evil.example.com" not in "".join(links(html))


def test_the_meeting_line_is_config_text_in_the_neutrality_scan():
    assert CTX["meeting_line"] in render.own_text(CTX, note_of())
    assert BANNED.search(CTX["meeting_line"]) is None


# ------------------------------------------------------------------ note/credit-logo
def test_the_html_edition_closes_with_the_site_footers_gnoshcodes_credit():
    """The site footer's credit (base.html.j2 `gc-credit`): the hook wordmark with the same alt text, the same
    wording, an absolute https URL on the site with width and height. The plain-text edition carries no image."""
    n = note_of(entry(), **{"support_line": config.SITE["support_line"], "support_url": config.SITE["support_url"]})
    html, text = render.body_html(CTX, n, n["entries"]), render.body_text(CTX, n, n["entries"])
    assert html.endswith(common.CREDIT_LINE + "\n</div>\n</div>\n</div>\n") and html.count("<img ") == 1
    img = next(x for x in parse(html).walk() if x.tag == "img")
    assert img.attrs == {"src": config.SITE["alerts"]["site_url"] + common.CREDIT_PATH, "alt": "gnoshcodes",
                         "width": "160", "height": "32"}
    assert common.CREDIT_IMAGE.startswith("https://daylight.gnoshcodes.com/static/brand/")
    footer = (ROOT / "site" / "templates" / "base.html.j2").read_text(encoding="utf-8")
    credit = re.search(r'<p class="gc-credit">(.*?)</p>', footer).group(1)
    assert 'alt="gnoshcodes" width="160" height="32"' in credit and f"<span>{common.CREDIT_TEXT}</span>" in credit
    assert "img" not in text and common.CREDIT_PATH not in text and common.CREDIT_TEXT not in text


def test_the_credit_png_ships_in_the_site_static_folder():
    """A PNG (Gmail shows no SVG): the 320x64 render of the light hook SVG, transparent, shown at 160x32. The build
    copies site/static/ whole, so it is served at CREDIT_IMAGE."""
    # The PNG header read directly: Pillow is not in requirements.lock, so the daily job's test step cannot import it.
    # The pixel check runs only where Pillow is installed (locally, not in the daily job).
    import struct
    path = ROOT / "site" / common.CREDIT_PATH
    head = path.read_bytes()[:29]
    assert head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR"
    width, height, depth, colour = struct.unpack(">IIBB", head[16:26])
    assert (width, height, depth, colour) == (320, 64, 8, 6)          # 8-bit RGBA (colour type 6)
    assert path.stat().st_size < 20_000
    try:
        from PIL import Image
    except ImportError:
        return
    with Image.open(path) as im:
        assert (im.format, im.size, im.mode) == ("PNG", (320, 64), "RGBA")
        assert im.getpixel((0, 0))[3] == 0 and im.getbbox()                 # a transparent ground, a visible mark


def test_the_built_site_serves_the_credit_png(msite):  # noqa: F811
    assert (msite / common.CREDIT_PATH).read_bytes() == (ROOT / "site" / common.CREDIT_PATH).read_bytes()


# ------------------------------------------------------------------ render/no-independence-line
UNOFF = config.SITE["unofficial"]
SUPPORT = {"support_line": config.SITE["support_line"], "support_url": config.SITE["support_url"]}


def test_both_bodies_say_the_site_is_independent_and_unofficial():
    """The short line under the date and the full notice at the foot, both from config/site.yml `unofficial:`."""
    from sitegen import unofficial
    u = unofficial.load(config.SITE)
    assert (CTX["email_line"], CTX["notice"]) == (u["email_line"], u["notice"]) and UNOFF["email_line"] == u["email_line"]
    n = note_of(entry())
    html = render.body_html(CTX, n, n["entries"])
    ps = paras(html)
    assert [n.all_text() for n in styled(html, "unofficial")] == [u["email_line"]] and ps[-1] == u["notice"]
    text = render.body_text(CTX, n, n["entries"])
    assert text.count(u["email_line"]) == 1 and text.count(u["notice"]) == 1


def test_the_support_line_closes_the_body_when_the_note_carries_it():
    n = note_of(entry(), **SUPPORT)
    html = render.body_html(CTX, n, n["entries"])
    assert paras(html)[-1] == f"{SUPPORT['support_line']} {config.SITE['support_label']}"
    assert links(html)[-1] == SUPPORT["support_url"]
    text = render.body_text(CTX, n, n["entries"])
    assert text.rstrip().endswith(f"{SUPPORT['support_line']} {config.SITE['support_label']}: {SUPPORT['support_url']}")


@pytest.mark.parametrize("extra", [{}, {"support_line": "", "support_url": ""},
                                   {"support_line": "Please help.", "support_url": "http://tips.example.com/"},
                                   {"support_line": "Please help.", "support_url": "javascript:alert(1)"},
                                   {"support_line": "", "support_url": "https://tips.example.com/"}])
def test_no_support_line_without_both_a_line_and_an_https_link(extra):
    n = note_of(entry(), **extra)
    html = render.body_html(CTX, n, n["entries"])
    assert "Please help." not in html and "tips.example.com" not in html
    assert paras(html)[-1] == CTX["notice"]


def test_the_shipped_note_carries_the_support_line_into_every_edition(msite):  # noqa: F811
    built = plan_mod.build(msite, D, cfg_with())
    note = read_note(msite)
    assert note["support_line"] and note["support_url"]
    for ed in built["plan"]["editions"]:
        assert note["notice"] in ed["body"] or render.inert(note["notice"]) in ed["body"]
        assert render.inert(note["support_line"]) in ed["body"] and note["support_url"] in ed["body"]


def test_the_notice_is_in_the_neutrality_scan(msite):  # noqa: F811
    note = read_note(msite)
    ours = render.own_text(CTX, {**note, **SUPPORT})
    for t in (CTX["notice"], CTX["email_line"], SUPPORT["support_line"], config.SITE["support_label"]):
        assert t in ours
    assert not [t for t in ours if BANNED.search(t)]


@pytest.mark.parametrize("subject", ["{site_name} official note, {date}", "{site_name} County note, {date}",
                                     "City of {site_name}, {date}", "{site_name} CMCSS {date}", "{site_name} rpc {date}",
                                     "{site_name} unofficial note {date}"])
def test_the_subject_never_borrows_a_governments_name(subject):
    """Nobody may read the note as coming from a government body: no "City of", "County", "CMCSS", "RPC" or
    "official" in the subject (the provider account's From name is the site name, set at go-live)."""
    cfg = cfg_with()
    cfg["morning_note"]["sender"]["text"]["subject"] = subject
    assert any("text.subject" in p for p in morning.sender_problems(cfg))
    with pytest.raises(ValueError):
        render.subject({**CTX, "text": {**CTX["text"], "subject": subject}}, "2026-11-11")
    assert not render.AUTHORITY.search(render.subject(CTX, "2026-11-11"))


@pytest.mark.parametrize("title", ["See www.evil.example now", "WWW.EVIL.EXAMPLE", "go to http://evil.example/x",
                                   "HTTPS://evil.example", "ftp://evil.example/f", "(www.a.example)"])
def test_a_bare_address_in_a_title_is_not_left_for_the_mail_client_to_link(title):
    """A mail client turns a bare www. or scheme:// into a link; a zero-width space after it keeps the record's words
    on screen and leaves nothing to link."""
    html = html_of(entry(title=title))
    strong = head_raw(html)
    shown = head_text(html)
    assert not re.search(r"(?i)www\.|[a-z]+://", shown)
    assert shown.replace("\u200b", "") == title and "&#8203;" in strong
    assert links(html) == ["https://example.com/fixture/agenda.pdf", SITE_URL + "items/2026.html#i-x"] + TODAY


@pytest.mark.parametrize("title", ["Sign in at evil.example/login", "x@evil.example", "x_https://evil.example",
                                   "a.b.c.d", "3.5 million", "evil\uff0eexample", "evil\u3002example", "-a.b",
                                   "U.S. Route 41A", "wwww.evil.example", "https:///x", "Ord. 2026-12"])
def test_a_bare_domain_in_a_title_is_broken_and_the_body_passes_the_deliver_check(title):
    """M3: a mail client links "evil.example/login" too. Render puts a zero-width space after every dot between
    two word characters (and after the colon of "://"), and deliver refuses a body that still has one."""
    from sender import deliver
    html = html_of(entry(title=title))
    shown = head_text(html)
    assert shown.replace("\u200b", "") == title
    assert not re.search(r"(?i)www\.|://|[\w-][.\u3002\uff0e\uff61]\w", shown), shown
    assert deliver.body_ok(html, CTX["link_hosts"], CTX["link_urls"])


@pytest.mark.parametrize("title", ["Budget \xad amendment", "Budget \ufeff amendment", "Budget \u202e amendment",
                                   "\ufeff Budget", "Budget \u200b", "a \x00 b", "a\t\xad\tb", "\xad", " \u2066 \u2069 x"])
def test_a_format_character_between_spaces_leaves_no_double_space(title):
    """render/clean-order: pdftotext output carries soft hyphens, BOMs and bidi controls. clean() drops them before
    it collapses whitespace, so none leaves the double space deliver refuses (which would lose the whole day)."""
    from sender import deliver
    assert "  " not in render.clean(title) and render.clean(title) == render.clean(title).strip()
    html = html_of(entry(title=title, body_name=title, recorded=title), unplaced_text=title)
    assert deliver.body_ok(html, CTX["link_hosts"], CTX["link_urls"]), html


_PIECES = ["a", "Z", "7", " ", "  ", "\t", "\n", "\r\n", "\x85", "\u2028", "\xa0", "\u3000", "\xad", "\ufeff",
           "\u202e", "\u2066", "\u200b", "\u200d", "\x00", "\x1b", "\x7f", ".", "\u3002", "\uff0e", "\uff61", "..",
           "-", "+", "_", "@", ":", "//", "://", "https://", "HTTP://", "www.", "WWW.", "evil.example", "x.y/z",
           "[", "]", "(", ")", "![", "](", "<", ">", "</p>", "<a href=", "&", "&amp;", "&#58;", "&#x3a;", "{{", "}}",
           "{%", "*", "`", "#", "~", "|", "!", "$", "%", "=", "\"", "'", "\\", "e\u0301", "\U0001f600", "\u0645",
           "3.5", "U.S.", "Ord.", "---", "> "]


def test_render_writes_a_body_deliver_accepts_for_any_text():
    """render/clean-order, as a property: thousands of random titles and names, made of format characters, markup
    characters, dots, brackets and addresses, all come out as bodies deliver accepts (seeded, so a failure repeats)."""
    import random
    from sender import deliver
    rnd = random.Random(20261110)
    for n in range(3000):
        text = ["".join(rnd.choice(_PIECES) for _ in range(rnd.randint(0, 25))) for _ in range(4)]
        html = html_of(entry(title=text[0], body_name=text[1], recorded=text[2]), unplaced_text=text[3])
        assert deliver.body_ok(html, CTX["link_hosts"], CTX["link_urls"]), (n, text)


def test_render_writes_only_bodies_the_deliver_check_accepts():
    """Every hostile field render is given still comes out as a body deliver sends (plan-untrusted/body-unchecked)."""
    from sender import deliver
    html = html_of(entry(title=HOSTILE, body_name=HOSTILE, recorded=HOSTILE), entry(id="b", title="second"),
                   unplaced_text=HOSTILE)
    assert deliver.body_ok(html, CTX["link_hosts"], CTX["link_urls"])


@pytest.mark.parametrize("on, url, want", [(True, "https://tips.example.com/", True),
                                           (False, "https://tips.example.com/", False), (True, "", False)])
def test_the_note_carries_the_support_link_only_while_support_is_on(on, url, want):
    """The note's support line and link follow support_enabled and need a URL (kept through the E501 rewrite)."""
    cfg = {**config.SITE, "support_enabled": on, "support_url": url}
    n = morning.day(D, [], {}, cfg)
    assert (bool(n["support_line"]), n["support_url"]) == (want, url if want else "")



# ------------------------------------------------------------------ L5: links only to the configured hosts
def test_a_source_on_a_host_that_is_not_a_link_host_gives_no_link():
    html = html_of(entry(source={"url": "https://elsewhere.example.org/a.pdf", "page": 1}))
    assert links(html) == [SITE_URL + "items/2026.html#i-x"] + TODAY
    assert "elsewhere.example.org" not in html


def test_no_site_link_when_the_site_host_is_not_a_link_host():
    ctx = {**CTX, "link_hosts": ("example.com",)}
    assert links(html_of(entry(), ctx=ctx)) == ["https://example.com/fixture/agenda.pdf"]


def test_the_support_link_is_the_configured_url_exactly():
    """Low (a): another page on the support link's host gives no support link; the configured URL does."""
    assert CTX["link_urls"] == (config.SITE["support_url"],)
    host = config.SITE["support_url"].split("/")[2]
    assert host not in CTX["link_hosts"]
    n = note_of(entry(), support_line="Please help.", support_url=f"https://{host}/someone-else")
    assert "someone-else" not in render.body_html(CTX, n, n["entries"])
    n = note_of(entry(), support_line="Please help.", support_url=config.SITE["support_url"])
    assert links(render.body_html(CTX, n, n["entries"]))[-1] == config.SITE["support_url"]


def test_no_support_link_off_the_link_hosts():
    n = note_of(entry(), support_line="Please help.", support_url="https://tips.elsewhere.example/")
    html = render.body_html(CTX, n, n["entries"])
    assert "tips.elsewhere.example" not in html and "Please help." not in html


# ------------------------------------------------------------------ note/compact-untitled
MINUTES_URL = "https://example.com/fixture/minutes-2026-09-03.pdf"


def vote(n: int, page: int, untitled=True, meeting="2026-09-03", **kw) -> dict:
    """A council vote of the made-up meeting `meeting`; untitled: the record printed no title (our fallback words)."""
    e = entry(id=f"city/vote/rc-{meeting}-{n}", kind="vote", body="city", body_name="Fixture Council",
              lists=["seats"], seat_body="ward", meeting_date=meeting, meeting="regular session",
              title=f"ORDINANCE {n}-2026-27: Title not read from the minutes" if untitled else f"ORDINANCE {n}-2026-27: FIXTURE a real title",
              title_ours=untitled, untitled=untitled, recorded="Recorded in the minutes; not confirmed",
              item_number=f"ORDINANCE {n}-2026-27",
              href=f"city/items/2026.html#ordinance-{n}", meeting_href=f"city/meetings/2026.html#{meeting}-regular",
              source={"url": f"{MINUTES_URL}#page={page}", "page": page}, confirmed=False, outcome=None, tally=None)
    e.update(kw)
    return e


SEPT = [vote(1, 2), vote(2, 3), vote(3, 4, untitled=False), vote(4, 5),
        vote(5, 6, title="MINUTES", title_ours=False, item_number=None)]
SEPT_NUMBERS = "ORDINANCE 1-2026-27, ORDINANCE 2-2026-27, ORDINANCE 4-2026-27"


def lis(html: str) -> list[str]:
    """Each item's words (note-titles round 3: one compact line per item in its meeting's card; was one card,
    before that one <li>)."""
    return [x.all_text() for x in items_of(html)]


def test_a_meetings_untitled_votes_stand_as_one_line_with_a_count_and_two_links():
    """2026-11-18: four past council meetings' minutes at once gave a seats reader 51 entries, nearly all titled
    "Title not read from the minutes" or "MINUTES". The email gives a meeting's untitled votes one line: the meeting,
    a count (config text), its page on the site and the minutes document, once each; a titled vote stays itself."""
    html = html_of(*SEPT)
    rows = lis(html)
    assert len(rows) == 2
    words = render.untitled_words(CTX, 4)
    assert words == CTX["text"]["untitled_votes"].replace("{n}", "4") and "4" in words
    # note-titles round 3: one card for the meeting (its line, the `recorded` words its items share, the minutes
    # once), then a line per item: the group's topic label, count line and numbers; the titled vote
    assert meeting_lines(html) == ["Fixture Council, September 3, 2026 regular session"]
    # none of the votes is confirmed: no shared words; each line says so itself (note/unconfirmed-unflagged)
    assert not styled(html, "said")
    assert rows[0].startswith("Ordinance ") and words in rows[0]
    assert SEPT_NUMBERS in rows[0]                      # the record's item numbers, once each, in record order
    assert "Title not read" not in html and "MINUTES" not in html
    assert all(x.endswith("Recorded in the minutes; not confirmed") for x in rows)
    assert "FIXTURE a real title" in rows[1]
    assert links(html)[:4] == [SITE_URL + "city/meetings/2026.html#2026-09-03-regular", MINUTES_URL,
                               SITE_URL + "city/meetings/2026.html#2026-09-03-regular",
                               SITE_URL + "city/items/2026.html#ordinance-3"]
    # note-titles: the group's headline is its count line; a titled vote's is its own title
    assert titles(html) == [words, SEPT[2]["title"]]


def test_the_text_body_reads_the_same_compact_edition():
    n = note_of(*SEPT)
    text = render.body_text(CTX, n, n["entries"])
    block = text.split("\n\n")[4].split("\n")       # after the header, the greeting, the kicker and the label
    meeting = f"{SITE_URL}city/meetings/2026.html#2026-09-03-regular"
    flag = "Recorded in the minutes; not confirmed"
    assert block == [f"  Fixture Council, September 3, 2026 regular session: {meeting}",
                     f"  Source document: {MINUTES_URL}",
                     f"  - Ordinance: {render.untitled_words(CTX, 4)} {SEPT_NUMBERS} · {flag} <{meeting}>",
                     f"  - Ordinance: {SEPT[2]['title']} · {flag} <{SITE_URL}city/items/2026.html#ordinance-3>"]
    assert "Title not read" not in text and "MINUTES" not in text and SEPT[2]["title"] in text


def test_one_line_per_meeting_and_a_lone_untitled_vote_stays_itself():
    oct_ = [vote(n, n, meeting="2026-10-01") for n in (7, 8, 9)]
    lone = vote(10, 2, meeting="2026-08-06")
    html = html_of(lone, *SEPT, *oct_)
    rows = lis(html)
    assert len(rows) == 4 and len(cards(html)) == 3                   # one card per meeting
    assert lone["title"] in rows[0]                                    # one untitled vote: as it reads today
    assert render.untitled_words(CTX, 4) in rows[1] and render.untitled_words(CTX, 3) in rows[3]
    assert "October 1, 2026" in meeting_lines(html)[2]


def test_untitled_votes_from_two_documents_of_one_meeting_are_two_lines():
    other = [vote(n, 1, source={"url": f"https://example.com/fixture/other.pdf#page={n}", "page": n}) for n in (11, 12)]
    rows = lis(html_of(*SEPT[:2], *other))
    assert len(rows) == 2 and all(render.untitled_words(CTX, 2) in x for x in rows)


@pytest.mark.parametrize("gone", ["untitled", "meeting_href"])
def test_a_note_without_the_untitled_fields_renders_every_entry_as_before(gone):
    rows = [{k: v for k, v in e.items() if k != gone} for e in SEPT]
    assert len(lis(html_of(*rows))) == len(SEPT)


def test_only_votes_are_compacted():
    rows = [{**e, "kind": "agenda_item", "recorded": "On the agenda"} for e in SEPT]
    assert len(lis(html_of(*rows))) == len(SEPT)


def test_a_compact_line_passes_the_deliver_check_and_its_links_obey_the_hosts():
    from sender import deliver
    assert deliver.body_ok(html_of(*SEPT), CTX["link_hosts"], CTX["link_urls"])
    off = [{**e, "source": {"url": "https://elsewhere.example.org/m.pdf#page=2", "page": 2},
            "meeting_href": "../evil.html"} for e in SEPT if e["untitled"]]
    html = html_of(*off)
    assert len(lis(html)) == 1 and links(html) == TODAY
    assert "elsewhere.example.org" not in html and "evil" not in html


def test_the_count_line_is_config_text_and_in_the_neutrality_scan(msite):  # noqa: F811
    ctx = {**CTX, "text": {**CTX["text"], "untitled_votes": "UNTITLED {n} COUNT"}}
    assert "UNTITLED 4 COUNT" in html_of(*SEPT, ctx=ctx)
    assert CTX["text"]["untitled_votes"] in render.own_text(CTX, read_note(msite))
    assert "{n}" in config.SITE["morning_note"]["sender"]["text"]["untitled_votes"]


def test_the_shipped_count_line_says_what_it_counts_and_the_numbers_follow():
    assert config.SITE["morning_note"]["sender"]["text"]["untitled_votes"] == \
        "{n} votes in these minutes with no item title:"


def test_item_numbers_are_deduped_kept_in_record_order_and_inert():
    """note-compact/hides-item-numbers: the group keeps the record's item numbers (one line, ", ", each once, in the
    record's order), escaped like a title; an entry with no number (a kind-only "MINUTES") adds none."""
    again = vote(1, 7)
    hostile = vote(6, 8, item_number="<b>{{ x }}</b> [l](https://evil.example.com)")
    html = html_of(vote(4, 1), *SEPT[:2], again, hostile)
    rows = lis(html)
    assert len(rows) == 1
    assert "ORDINANCE 4-2026-27, ORDINANCE 1-2026-27, ORDINANCE 2-2026-27, <b>" in rows[0]
    assert rows[0].count("ORDINANCE 1-2026-27") == 1 and render.untitled_words(CTX, 5) in rows[0]
    assert "{{" not in html and "<b>" not in html and "evil.example.com" not in "".join(links(html))
    from sender import deliver
    assert deliver.body_ok(html, CTX["link_hosts"], CTX["link_urls"])


def test_a_group_with_no_item_number_has_no_numbers_line():
    kind_only = [vote(n, n, title="MINUTES", title_ours=False, item_number=None) for n in (1, 2)]
    n = note_of(*kind_only)
    block = render.body_text(CTX, n, n["entries"]).split("\n\n")[4].split("\n")
    assert len(block) == 3 and block[2].startswith("  - " + render.untitled_words(CTX, 2).rstrip(":") + " · ")


def test_a_zoning_case_is_never_compacted_and_only_the_seats_section_is():
    """note-compact/zoning-case-hidden: an entry with a `case` is a zoning case a reader may look for by number, and
    a section other than the seats list holds what the reader picked by topic: both stay one entry each."""
    cases = [vote(n, n, case=f"Z-{n}-2026", lists=["zoning", "seats"], district=7) for n in (1, 2, 3)]
    assert len(lis(html_of(*cases))) == 3
    budget = [vote(n, n, lists=["budget"]) for n in (1, 2, 3)]
    assert len(lis(html_of(*budget))) == 3
    assert len(lis(html_of(*[vote(n, n) for n in (1, 2, 3)]))) == 1
