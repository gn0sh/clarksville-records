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


def tags(html: str) -> set:
    return {n.tag for n in parse(html).walk()} - {"root"}


# ------------------------------------------------------------------ untrusted titles come out inert
def test_a_hostile_title_comes_out_inert():
    html = html_of(entry(title=HOSTILE))
    assert tags(html) == {"h1", "p", "h2", "ul", "li", "br", "strong", "a"}        # only the tags we write
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
    assert tags(html) == {"h1", "p", "h2", "ul", "li", "br", "strong", "a"}
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
           "link_hosts": ("records.example.com", "example.com", "tips.example.com")}
    n = note_of(entry(body_name="BODY", recorded="REC", title="TITLE"), unplaced_text="UNPLACED",
                support_line="SUPPORT", support_url="https://tips.example.com/x")
    n["lists"] = [{"key": k, "label": f"L-{k}"} for k in morning.LIST_KEYS]
    text = " ".join(t for node in parse(render.body_html(ctx, n, n["entries"])).walk() for t in node.text)
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
    assert [n.all_text() for n in parse(body).walk() if n.tag == "strong"] == shown


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
    paras = [n.all_text() for n in parse(html).walk() if n.tag == "p"]
    assert paras[-3:] == ["2 zoning cases printed no district or ward", CTX["text"]["why"], CTX["notice"]]
    assert [n.all_text() for n in parse(html_of(entry())).walk() if n.tag == "p"][-2:] == [CTX["text"]["why"], CTX["notice"]]
    assert "unsubscribe" not in html.lower()                           # the provider's link, not ours


def test_the_text_version_reads_the_same_edition():
    n = note_of(entry(title="A  title\nover two lines"), unplaced_text="1 zoning case printed no district or ward")
    text = render.body_text(CTX, n, n["entries"])
    assert "A title over two lines" in text and SITE_URL + "items/2026.html#i-x" in text
    assert "https://example.com/fixture/agenda.pdf#page=2" in text and text.rstrip().endswith(CTX["notice"])
    assert CTX["text"]["why"] in text and CTX["email_line"] in text


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
    paras = [p.all_text() for p in parse(html).walk() if p.tag == "p"]
    assert paras[1] == u["email_line"] and paras[-1] == u["notice"]
    text = render.body_text(CTX, n, n["entries"])
    assert text.count(u["email_line"]) == 1 and text.count(u["notice"]) == 1


def test_the_support_line_closes_the_body_when_the_note_carries_it():
    n = note_of(entry(), **SUPPORT)
    html = render.body_html(CTX, n, n["entries"])
    last = [p for p in parse(html).walk() if p.tag == "p"][-1]
    assert last.all_text() == f"{SUPPORT['support_line']} {config.SITE['support_label']}"
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
    assert [p.all_text() for p in parse(html).walk() if p.tag == "p"][-1] == CTX["notice"]


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
    assert deliver.body_ok(html, CTX["link_hosts"])


def test_render_writes_only_bodies_the_deliver_check_accepts():
    """Every hostile field render is given still comes out as a body deliver sends (plan-untrusted/body-unchecked)."""
    from sender import deliver
    html = html_of(entry(title=HOSTILE, body_name=HOSTILE, recorded=HOSTILE), entry(id="b", title="second"),
                   unplaced_text=HOSTILE)
    assert deliver.body_ok(html, CTX["link_hosts"])


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


def test_no_support_link_off_the_link_hosts():
    n = note_of(entry(), support_line="Please help.", support_url="https://tips.elsewhere.example/")
    html = render.body_html(CTX, n, n["entries"])
    assert "tips.elsewhere.example" not in html and "Please help." not in html
