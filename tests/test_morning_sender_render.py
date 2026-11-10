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
    assert shown == " ".join(HOSTILE.split())


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
    assert links(html)[1] == "https://example.com/a?b=%7B%7Bsubscriber.email%7D%7D&c=1"


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
    assert all(u.startswith(SITE_URL) or u in {e["source"]["url"] for e in note["entries"]} for u in got)


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
           "text": {"subject": "{site_name} S {date}", "why": "WHY", "open_site": "OPEN"}}
    n = note_of(entry(body_name="BODY", recorded="REC", title="TITLE"), unplaced_text="UNPLACED")
    n["lists"] = [{"key": k, "label": f"L-{k}"} for k in morning.LIST_KEYS]
    text = " ".join(t for node in parse(render.body_html(ctx, n, n["entries"])).walk() for t in node.text)
    words = re.sub(r"November 11, 2026|\d", "", text)
    assert sorted(set(re.findall(r"[A-Za-z-]+", words))) == sorted(
        ["SITE", "L-budget", "BODY", "REC", "TITLE", "OPEN", "SRC", "PG", "UNPLACED", "WHY"])
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


def test_unplaced_line_and_why_line_close_the_body():
    html = html_of(entry(), unplaced_text="2 zoning cases printed no district or ward")
    paras = [n.all_text() for n in parse(html).walk() if n.tag == "p"]
    assert paras[-2:] == ["2 zoning cases printed no district or ward", CTX["text"]["why"]]
    assert [n.all_text() for n in parse(html_of(entry())).walk() if n.tag == "p"][-1] == CTX["text"]["why"]
    assert "unsubscribe" not in html.lower()                           # the provider's link, not ours


def test_the_text_version_reads_the_same_edition():
    n = note_of(entry(title="A  title\nover two lines"), unplaced_text="1 zoning case printed no district or ward")
    text = render.body_text(CTX, n, n["entries"])
    assert "A title over two lines" in text and SITE_URL + "items/2026.html#i-x" in text
    assert "https://example.com/fixture/agenda.pdf#page=2" in text and text.rstrip().endswith(CTX["text"]["why"])
