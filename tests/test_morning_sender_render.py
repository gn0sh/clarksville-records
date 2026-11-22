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


def paras(html: str) -> list[str]:
    """The paragraphs of a body before the footer credit, which always closes it (note/credit-logo)."""
    out = [n.all_text() for n in parse(html).walk() if n.tag == "p"]
    assert out[-1].strip() == common.CREDIT_TEXT and html.endswith(common.CREDIT_LINE + "\n")
    return out[:-1]


def tags(html: str) -> set:
    return {n.tag for n in parse(html).walk()} - {"root"}


# ------------------------------------------------------------------ untrusted titles come out inert
def test_a_hostile_title_comes_out_inert():
    html = html_of(entry(title=HOSTILE))
    assert tags(html) == {"h1", "p", "h2", "ul", "li", "br", "strong", "a", "img"}        # only the tags we write
    assert links(html) == [SITE_URL + "items/2026.html#i-x", "https://example.com/fixture/agenda.pdf#page=2"]
    title = html.split("<strong>")[1].split("</strong>")[0]
    # nothing the provider's template step or a Markdown step could read as markup is left as a plain character
    assert not re.search(r"[<>{}\[\]()*_`#\\~|!$%@=]", re.sub(r"&#\d+;", "", title)), title
    assert not title.startswith("-") and "\n" not in title and "  " not in title
    assert "{{" not in html and "{%" not in html and "---" not in html and "](" not in html
    # and a reader still sees the record's own words, unchanged apart from the whitespace
    shown = next(n for n in parse(html).walk() if n.tag == "strong").all_text()
    assert shown.replace("\u200b", "") == " ".join(HOSTILE.split())


def test_every_field_of_an_entry_is_escaped_not_only_the_title():
    html = html_of(entry(body_name="<b>{{ x }}</b>", recorded="{% y %} [z](https://evil.example.com)"))
    assert tags(html) == {"h1", "p", "h2", "ul", "li", "br", "strong", "a", "img"}
    assert "{{" not in html and "{%" not in html and "evil.example.com" not in "".join(links(html))


def test_the_body_has_no_blank_or_indented_line():
    """One HTML block from first line to last: a Markdown step finds no paragraph break and no code block."""
    lines = html_of(entry(title=HOSTILE), entry(id="b", title="second")).split("\n")
    assert lines[-1] == "" and all(line and line[0] == "<" for line in lines[:-1])


def test_control_and_direction_characters_are_dropped_and_a_long_title_is_cut():
    assert render.clean("a‮b\x00c​d\te") == "abcd e"
    long = "x" * 5000
    assert render.clean(long) == "x" * render.MAX_TITLE + render.CUT
    assert len(html_of(entry(title=long))) < 2000


# ------------------------------------------------------------------ links: the site's pages and https sources only
@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://example.com/a.pdf", "//example.com/a.pdf", "",
                                 None, "https://example.com/a b.pdf", "https://example.com/\"onclick=\"x",
                                 "data:text/html,x", "ftp://example.com/a", 7])
def test_a_source_url_that_is_not_plain_https_gives_no_link(url):
    html = html_of(entry(source={"url": url, "page": 3}))
    assert links(html) == [SITE_URL + "items/2026.html#i-x"]
    assert config.SITE["morning_note"]["page"]["source_label"] not in html         # no "Source" words without a link


def test_braces_in_a_source_url_cannot_reach_the_template_step():
    html = html_of(entry(source={"url": "https://example.com/a?b={{subscriber.email}}&c=1", "page": None}))
    assert "{{" not in html and "}}" not in html
    assert links(html) == [SITE_URL + "items/2026.html#i-x"]                    # a brace in a URL: no link at all


@pytest.mark.parametrize("href", ["https://evil.example.com/", "//evil.example.com/x", "/abs.html", "../up.html",
                                  "a/../../b.html", "javascript:alert(1)", "a b.html", "x.html?next=//evil", None, ""])
def test_an_href_that_is_not_a_plain_site_path_gives_no_site_link(href):
    assert links(html_of(entry(href=href))) == ["https://example.com/fixture/agenda.pdf#page=2"]


@pytest.mark.parametrize("site_url", ["", "http://records.example.com/", "https://records.example.com",
                                      "javascript:alert(1)//", "https://records.example.com/?x=", None])
def test_no_site_link_without_a_proper_site_url(site_url):
    ctx = {**CTX, "site_url": site_url}
    assert links(html_of(entry(), ctx=ctx)) == ["https://example.com/fixture/agenda.pdf#page=2"]


def test_site_links_are_site_url_plus_href_for_every_fixture_entry(msite):  # noqa: F811
    note = read_note(msite)
    html = render.body_html(CTX, note, note["entries"])
    got = links(html)
    with_href = [e for e in note["entries"] if e["href"]]
    assert with_href and all(SITE_URL + e["href"] in got for e in with_href)        # every real href is linkable
    assert all(e["source"]["url"] in got for e in note["entries"])
    assert got[-1] == note["support_url"]                                        # and the support link, last
    assert all(u.startswith(SITE_URL) or u in {e["source"]["url"] for e in note["entries"]} for u in got[:-1])


# ------------------------------------------------------------------ our own words: config text, neutral
def test_own_text_passes_the_neutrality_scan(msite):  # noqa: F811
    note = read_note(msite)
    ours = render.own_text(CTX, note)
    assert ours and not [t for t in ours if BANNED.search(t)]
    assert set(config.SITE["morning_note"]["sender"]["text"]) == set(render.TEXT_KEYS) == set(morning.SENDER_TEXT_KEYS)
    assert render.subject(CTX, "2026-11-11") == "Daylight morning note, November 11, 2026" == ours[0]


def test_every_word_outside_the_record_is_config_text():
    """Change every config text and label: nothing of the old wording is left, so none of it is hard-coded."""
    ctx = {"site_name": "SITE", "site_url": SITE_URL, "source_label": "SRC", "page_label": "PG",
           "text": {"subject": "{site_name} S {date}", "why": "WHY", "open_site": "OPEN"},
           "notice": "NOTICE", "email_line": "LINE", "support_label": "TIPS",
           "link_hosts": ("records.example.com", "example.com"), "link_urls": ("https://tips.example.com/x",)}
    n = note_of(entry(body_name="BODY", recorded="REC", title="TITLE"), unplaced_text="UNPLACED",
                support_line="SUPPORT", support_url="https://tips.example.com/x")
    n["lists"] = [{"key": k, "label": f"L-{k}"} for k in morning.LIST_KEYS]
    html = render.body_html(ctx, n, n["entries"])
    paras(html)                 # the credit is the site footer's fixed wording (note/credit-logo), not config text
    text = " ".join(t for node in parse(html[:-len(common.CREDIT_LINE) - 1]).walk() for t in node.text)
    words = re.sub(r"November 11, 2026|\d", "", text)
    assert sorted(set(re.findall(r"[A-Za-z-]+", words))) == sorted(
        ["SITE", "L-budget", "BODY", "REC", "TITLE", "OPEN", "SRC", "PG", "UNPLACED", "WHY", "NOTICE", "LINE",
         "SUPPORT", "TIPS"])
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
    got = [n.all_text() for n in parse(body).walk() if n.tag == "strong"]
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
    assert [n.all_text() for n in parse(html).walk() if n.tag == "h2"] == [label for label, _ in secs]


def test_unplaced_line_and_why_line_close_the_entries_then_the_notice():
    html = html_of(entry(), unplaced_text="2 zoning cases printed no district or ward")
    assert paras(html)[-3:] == ["2 zoning cases printed no district or ward", CTX["text"]["why"], CTX["notice"]]
    assert paras(html_of(entry()))[-2:] == [CTX["text"]["why"], CTX["notice"]]
    assert "unsubscribe" not in html.lower()                           # the provider's link, not ours


def test_the_text_version_reads_the_same_edition():
    n = note_of(entry(title="A  title\nover two lines"), unplaced_text="1 zoning case printed no district or ward")
    text = render.body_text(CTX, n, n["entries"])
    assert "A title over two lines" in text and SITE_URL + "items/2026.html#i-x" in text
    assert "https://example.com/fixture/agenda.pdf#page=2" in text and text.rstrip().endswith(CTX["notice"])
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
    shown = [x.all_text() for x in parse(html).walk() if x.tag == "li"]
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
    assert tags(html) == {"h1", "p", "h2", "ul", "li", "br", "strong", "a", "img"}
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
    assert html.endswith(common.CREDIT_LINE + "\n") and html.count("<img ") == 1
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
    assert ps[1] == u["email_line"] and ps[-1] == u["notice"]
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
    strong = html.split("<strong>")[1].split("</strong>")[0]
    shown = next(n for n in parse(html).walk() if n.tag == "strong").all_text()
    assert not re.search(r"(?i)www\.|[a-z]+://", shown)
    assert shown.replace("\u200b", "") == title and "&#8203;" in strong
    assert links(html) == [SITE_URL + "items/2026.html#i-x", "https://example.com/fixture/agenda.pdf#page=2"]


@pytest.mark.parametrize("title", ["Sign in at evil.example/login", "x@evil.example", "x_https://evil.example",
                                   "a.b.c.d", "3.5 million", "evil\uff0eexample", "evil\u3002example", "-a.b",
                                   "U.S. Route 41A", "wwww.evil.example", "https:///x", "Ord. 2026-12"])
def test_a_bare_domain_in_a_title_is_broken_and_the_body_passes_the_deliver_check(title):
    """M3: a mail client links "evil.example/login" too. Render puts a zero-width space after every dot between
    two word characters (and after the colon of "://"), and deliver refuses a body that still has one."""
    from sender import deliver
    html = html_of(entry(title=title))
    shown = next(n for n in parse(html).walk() if n.tag == "strong").all_text()
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
    assert links(html) == [SITE_URL + "items/2026.html#i-x"]
    assert "elsewhere.example.org" not in html


def test_no_site_link_when_the_site_host_is_not_a_link_host():
    ctx = {**CTX, "link_hosts": ("example.com",)}
    assert links(html_of(entry(), ctx=ctx)) == ["https://example.com/fixture/agenda.pdf#page=2"]


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
              href=f"city/items/2026.html#ordinance-{n}", meeting_href=f"city/meetings/2026.html#{meeting}-regular",
              source={"url": f"{MINUTES_URL}#page={page}", "page": page}, confirmed=False, outcome=None, tally=None)
    e.update(kw)
    return e


SEPT = [vote(1, 2), vote(2, 3), vote(3, 4, untitled=False), vote(4, 5), vote(5, 6, title="MINUTES", title_ours=False)]


def lis(html: str) -> list[str]:
    return [n.all_text() for n in parse(html).walk() if n.tag == "li"]


def test_a_meetings_untitled_votes_stand_as_one_line_with_a_count_and_two_links():
    """2026-11-18: four past council meetings' minutes at once gave a seats reader 51 entries, nearly all titled
    "Title not read from the minutes" or "MINUTES". The email gives a meeting's untitled votes one line: the meeting,
    a count (config text), its page on the site and the minutes document, once each; a titled vote stays itself."""
    html = html_of(*SEPT)
    rows = lis(html)
    assert len(rows) == 2
    words = render.untitled_words(CTX, 4)
    assert words == CTX["text"]["untitled_votes"].replace("{n}", "4") and "4" in words
    assert rows[0].startswith("Fixture Council, September 3, 2026 regular session") and words in rows[0]
    assert "Title not read" not in html and "MINUTES" not in html and "not confirmed" not in rows[0]
    assert "FIXTURE a real title" in rows[1]
    assert links(html)[:4] == [SITE_URL + "city/meetings/2026.html#2026-09-03-regular", MINUTES_URL,
                               SITE_URL + "city/items/2026.html#ordinance-3", f"{MINUTES_URL}#page=4"]
    assert [n.all_text() for n in parse(html).walk() if n.tag == "strong"] == [SEPT[2]["title"]]


def test_the_text_body_reads_the_same_compact_edition():
    n = note_of(*SEPT)
    text = render.body_text(CTX, n, n["entries"])
    block = text.split("\n\n")[2].split("\n")
    assert block == ["  Fixture Council, September 3, 2026 regular session", f"  {render.untitled_words(CTX, 4)}",
                     f"  {CTX['text']['open_site']}: {SITE_URL}city/meetings/2026.html#2026-09-03-regular",
                     f"  {CTX['source_label']}: {MINUTES_URL}"]
    assert "Title not read" not in text and "MINUTES" not in text and SEPT[2]["title"] in text


def test_one_line_per_meeting_and_a_lone_untitled_vote_stays_itself():
    oct_ = [vote(n, n, meeting="2026-10-01") for n in (7, 8, 9)]
    lone = vote(10, 2, meeting="2026-08-06")
    rows = lis(html_of(lone, *SEPT, *oct_))
    assert len(rows) == 4
    assert lone["title"] in rows[0]                                    # one untitled vote: as it reads today
    assert render.untitled_words(CTX, 4) in rows[1] and render.untitled_words(CTX, 3) in rows[3]
    assert "October 1, 2026" in rows[3]


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
    assert len(lis(html)) == 1 and links(html) == []
    assert "elsewhere.example.org" not in html and "evil" not in html


def test_the_count_line_is_config_text_and_in_the_neutrality_scan(msite):  # noqa: F811
    ctx = {**CTX, "text": {**CTX["text"], "untitled_votes": "UNTITLED {n} COUNT"}}
    assert "UNTITLED 4 COUNT" in html_of(*SEPT, ctx=ctx)
    assert CTX["text"]["untitled_votes"] in render.own_text(CTX, read_note(msite))
    assert "{n}" in config.SITE["morning_note"]["sender"]["text"]["untitled_votes"]
