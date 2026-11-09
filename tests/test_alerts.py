# ruff: noqa: E501
"""Alerts v1 (M5, sitegen/feeds.py): static Atom feeds per body and per topic, and the Alerts page."""
import copy
import shutil
import xml.etree.ElementTree as ET

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, parse
from qa import site_checks
from qa.common import load_facts
from sitegen import config, feeds, views
from sitegen.build import build, site_url_problems
from test_site_neutrality import BANNED

A = "{http://www.w3.org/2005/Atom}"
FACTS = load_facts(FIXTURE)


def feed_files(built):
    return sorted((built / "feeds").glob("*.xml"))


def parsed(path):
    return ET.parse(path).getroot()


def text(el, tag):
    x = el.find(A + tag)
    return None if x is None else x.text


def test_one_feed_per_body_and_per_topic(built):
    """The fixture builds the county only: its agendas-and-minutes feed plus one per configured topic. No district
    or ward feeds (the records place no item in a district or ward; file budget)."""
    names = [f.name for f in feed_files(built)]
    want = ["county-meetings.xml"] + [f"topic-{t}.xml" for t in config.SITE["alerts"]["topics"]]
    assert sorted(names) == sorted(want)
    assert not [n for n in names if "district" in n or "ward" in n]


def test_feeds_are_valid_atom(built):
    for f in feed_files(built):
        root = parsed(f)
        assert root.tag == A + "feed", f
        for tag in ("id", "title", "updated"):
            assert text(root, tag), (f, tag)
        assert root.find(f"{A}author/{A}name").text == config.SITE_NAME
        assert [x.get("href") for x in root.findall(A + "link") if x.get("rel") == "self"] == [f.name]
        for e in root.findall(A + "entry"):
            for tag in ("id", "title", "updated"):
                assert text(e, tag), (f, tag)
            assert site_checks.RFC3339.fullmatch(text(e, "updated"))
            assert [x for x in e.findall(A + "link") if x.get("rel") == "alternate"]


def test_county_feed_has_one_entry_per_meeting_document(built):
    root = parsed(built / "feeds" / "county-meetings.xml")
    ids = [text(e, "id") for e in root.findall(A + "entry")]
    prefix = config.SITE["alerts"]["feed_id"]
    assert sorted(ids) == sorted(f"{prefix}county/meeting/{m['id']}/minutes" for m in FACTS["meetings"])
    dates = [text(e, "updated") for e in root.findall(A + "entry")]
    assert dates == sorted(dates, reverse=True)
    pages = {s["id"]: s["pages"] for s in FACTS["sources"]}
    m = FACTS["meetings"][0]
    e = next(e for e in root.findall(A + "entry") if text(e, "id").endswith(f"/{m['id']}/minutes"))
    n = pages[m["source_id"]]
    assert f"Minutes ({n} page{'' if n == 1 else 's'}), fetched " in text(e, "summary")


def test_entry_links_resolve_to_built_pages(built, pages):
    for f in feed_files(built):
        for e in parsed(f).findall(A + "entry"):
            for x in e.findall(A + "link"):
                href = x.get("href")
                if x.get("rel") == "alternate":
                    assert href.startswith("../") and "officials/" not in href, href
                    path, _, frag = href[3:].partition("#")
                    assert path in pages, href
                    assert f'id="{frag}"' in pages[path] if frag else True, href
                else:
                    assert x.get("rel") == "related" and href.startswith("https://"), href


def test_topic_feed_entries_are_items_of_that_type_at_each_meeting(built):
    ix = views.Index(FACTS)
    prefix = config.SITE["alerts"]["feed_id"]
    for t in config.SITE["alerts"]["topics"]:
        want = {f"{prefix}county/item/{it['id']}/{e['meeting_id']}" for it in FACTS["items"]
                if t in views.item_types(it) for e in ix.events_by_item[it["id"]]}
        got = {text(e, "id") for e in parsed(built / "feeds" / f"topic-{t}.xml").findall(A + "entry")}
        assert got == want, t


def test_ids_are_stable_across_builds(built, tmp_path):
    """The same records build byte-identical feeds, so a reader never alerts twice."""
    out = tmp_path / "again" / "site"
    build(FIXTURE, out, internal=True, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS)
    for f in feed_files(built):
        assert (out / "feeds" / f.name).read_bytes() == f.read_bytes(), f.name


def entry(n, title="t"):
    d = f"2026-{1 + n // 28:02d}-{1 + n % 28:02d}"
    return {"id": f"county/x/{n}", "title": title, "updated": d, "href": "items/2026.html#x", "source": "https://example.invalid/a.pdf",
            "summary": "s", "sort": (d, n)}


def test_capped_and_newest_first():
    feed = {"file": "feeds/t.xml", "title": "T", "about": "A"}
    root = ET.fromstring(feeds.render(feed, [entry(n) for n in range(80)]))
    es = root.findall(A + "entry")
    assert len(es) == config.SITE["alerts"]["max_entries"] == 50
    dates = [text(e, "updated") for e in es]
    assert dates == sorted(dates, reverse=True) and dates[0].startswith("2026-03-")
    assert text(root, "updated") == dates[0]


def test_text_is_escaped():
    nasty = 'A <b>bold</b> & "quoted" ]]> <script>x</script>'
    feed = {"file": "feeds/t.xml", "title": nasty, "about": nasty}
    raw = feeds.render(feed, [entry(1, nasty)])
    assert b"<script>" not in raw and b"<b>" not in raw
    root = ET.fromstring(raw)
    assert text(root.find(A + "entry"), "title") == nasty
    assert text(root, "subtitle") == nasty


def test_absolute_links_with_site_url():
    cfg = copy.deepcopy(config.SITE)
    cfg["alerts"]["site_url"] = "https://records.example.org/"
    root = ET.fromstring(feeds.render({"file": "feeds/t.xml", "title": "T", "about": "A"}, [entry(1)], cfg))
    links = [x.get("href") for x in root.iter(A + "link")]
    assert "https://records.example.org/feeds/t.xml" in links
    assert "https://records.example.org/items/2026.html#x" in links


@pytest.mark.parametrize("change, bad", [
    ({"feed_id": "https://records.example.org/"}, "feed_id"),
    ({"feed_id": ""}, "feed_id"),
    ({"site_url": "http://records.example.org/"}, "site_url"),
    ({"site_url": "https://records.example.org"}, "site_url"),
    ({"max_entries": 0}, "max_entries"),
    ({"max_entries": "50"}, "max_entries"),
    ({"topics": ["rezoning", "parking"]}, "parking"),
])
def test_config_problems(change, bad):
    cfg = copy.deepcopy(config.SITE)
    cfg["alerts"].update(change)
    assert any(bad in p for p in site_url_problems(cfg))


def test_real_config_is_clean():
    assert feeds.problems(config.SITE) == []


def test_alerts_page_links_every_feed_and_explains_how(built, pages):
    html = pages["alerts.html"]
    for f in feed_files(built):
        assert f'href="feeds/{f.name}"' in html
        assert 'rel="alternate" type="application/atom+xml"' in html
    main = html[html.index("<main"):html.index("</main>")]
    for words in ("feed reader", "Feedly", "Inoreader", "NetNewsWire", "iPhone", "Copy link", "Email alerts are planned.",
                  "We keep no list of followers and run no sign-up."):
        assert words in main, words
    assert BANNED.search(parse(main).all_text()) is None
    assert "officials/" not in main


def test_alerts_is_in_the_nav_on_every_page(pages):
    for name, html in pages.items():
        nav = html[html.index('<nav id="site-nav"'):]
        assert 'alerts.html"' in nav[:nav.index("</nav>")], name


def test_no_alerts_config_builds_no_feeds(tmp_path, monkeypatch):
    site = {k: v for k, v in config.SITE.items() if k != "alerts"}
    monkeypatch.setattr(config, "SITE", site)
    out = tmp_path / "b" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS)
    assert not (out / "feeds").exists() and not (out / "alerts.html").exists()
    assert "alerts.html" not in (out / "index.html").read_text(encoding="utf-8")


# -- qa.site_checks `feeds`


@pytest.fixture()
def site(tmp_path, built):
    dst = tmp_path / "site"
    shutil.copytree(built, dst)
    return dst


def feeds_check(site_dir):
    pages = {f.relative_to(site_dir).as_posix(): site_checks.parse(f) for f in site_dir.rglob("*.html")}
    return site_checks.check_feeds(site_dir, pages, FACTS["sources"], config.SITE)[0]


def test_site_checks_pass_on_the_fixture(site):
    assert feeds_check(site) == []


@pytest.mark.parametrize("old, new, why", [
    ("<updated>", "<updated>x", "RFC 3339"),
    ("</feed>", "", "not well-formed"),
    ('href="../items/', 'href="../itemz/', "no such page"),
    ("https://example.invalid/", "https://elsewhere.invalid/", "not a fetched source"),
])
def test_site_checks_catch_a_broken_feed(site, old, new, why):
    f = site / "feeds" / "county-meetings.xml" if "items" not in old else site / "feeds" / f"topic-{config.SITE['alerts']['topics'][0]}.xml"
    t = f.read_text(encoding="utf-8")
    if old not in t:  # the fixture's rezoning feed may be empty: use any feed with an item link
        f = next(x for x in (site / "feeds").glob("topic-*.xml") if old in x.read_text(encoding="utf-8"))
        t = f.read_text(encoding="utf-8")
    f.write_text(t.replace(old, new, 1), encoding="utf-8")
    assert any(why in p for p in feeds_check(site)), feeds_check(site)


def test_site_checks_catch_a_duplicate_id_and_an_unlinked_feed(site):
    f = site / "feeds" / "county-meetings.xml"
    root = parsed(f)
    es = root.findall(A + "entry")
    assert len(es) >= 2
    es[1].find(A + "id").text = es[0].find(A + "id").text
    ET.ElementTree(root).write(f, encoding="utf-8", xml_declaration=True)
    shutil.copy(f, site / "feeds" / "extra.xml")
    problems = feeds_check(site)
    assert any("twice" in p for p in problems)
    assert any("does not link feeds/extra.xml" in p for p in problems)


def test_illegal_xml_characters_are_stripped_and_whitespace_collapsed():
    """PDF text carries NUL, form feed and U+FFFE: none is legal in XML 1.0, so the feed must still parse."""
    nasty = "Zoning\x00 of  the\x0c lot\ufffe\n at  5\ufffa"
    feed = {"file": "feeds/t.xml", "title": nasty, "about": nasty}
    raw = feeds.render(feed, [entry(1, nasty)])
    root = ET.fromstring(raw)
    assert text(root.find(A + "entry"), "title") == "Zoning of the lot at 5\ufffa"
    assert text(root, "subtitle") == "Zoning of the lot at 5\ufffa"
    assert b"\x0c" not in raw and b"\x00" not in raw


@pytest.mark.parametrize("title,topic,hit", [
    ("Resolution to appoint a member", "appointment", True),
    ("Appointments to the board", "appointment", True),
    ("Report on disappointment with the schedule", "appointment", False),
    ("Reappointment of a member", "appointment", False),
    ("Budget amendment", "budget", True),
    ("Supplemental appropriations", "budget", True),
    ("A rezoning request", "rezoning", True),
    ("Resolution", "resolution", True),
    ("Irresolution on the matter", "resolution", False),
])
def test_topic_words_match_at_the_start_of_a_word(title, topic, hit):
    assert (topic in views.item_types({"number": "", "title": title})) is hit
