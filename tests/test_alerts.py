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
    """The fixture builds the county only: its agendas-and-minutes feed plus one per configured topic. Per-seat
    zoning feeds exist on the pages target only, and only with RPC cases (see the zoning tests below)."""
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
    ({"contracts_title": ""}, "contracts_title"),
    ({"contracts_title": None}, "contracts_title"),
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
    for words in ("feed reader", "Feedly", "Inoreader", "NetNewsWire", "iPhone", "Copy link", "Email alerts are planned.", "Feeds for a single ward or district are not available yet.",
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


def test_site_checks_cap_the_rezoning_feed_per_body(site, monkeypatch):
    # feeds/rezoning-keeps-every-body: topic-rezoning.xml holds max_entries of each body, so the check counts per body
    f = site / "feeds" / "topic-rezoning.xml"
    root = parsed(f)
    es = root.findall(A + "entry")
    assert len(es) >= 2
    pre = config.SITE["alerts"]["feed_id"]
    for n, e in enumerate(es):          # one RPC entry beside each county entry, same date: still newest first
        twin = copy.deepcopy(e)
        twin.find(A + "id").text = f"{pre}rpc/item/case-{n}/rpc-meeting"
        root.insert(list(root).index(e) + 1, twin)
    ET.ElementTree(root).write(f, encoding="utf-8", xml_declaration=True)
    cfg = copy.deepcopy(config.SITE)
    cfg["alerts"]["max_entries"] = len(es)          # the feed holds 2x the cap, each body exactly the cap
    monkeypatch.setattr(config, "SITE", cfg)
    pages = {p.relative_to(site).as_posix(): site_checks.parse(p) for p in site.rglob("*.html")}
    check = lambda: [p for p in site_checks.check_feeds(site, pages, FACTS["sources"], cfg)[0] if "rezoning" in p]  # noqa: E731
    assert check() == []
    cfg["alerts"]["max_entries"] = len(es) - 1
    assert sorted(check()) == sorted(f"feeds/topic-rezoning.xml: {len(es)} {b} entries, more than alerts.max_entries "
                                     f"{len(es) - 1} per body" for b in ("county", "rpc"))


def test_site_checks_know_the_finance_sources_the_contracts_feed_links(site, monkeypatch):
    seen = {}

    def spy(site_dir, pages, sources, cfg, finance_sources=()):
        seen["urls"] = {s["url"] for s in sources}
        seen["fin"] = {s["url"] for s in finance_sources}
        return [], "spy"
    monkeypatch.setattr(site_checks, "check_feeds", spy)
    fin = {"sources": [{"url": "https://example.invalid/fin/rfp-1.pdf"}], "documents": [], "solicitations": []}
    site_checks.run_checks(site, FACTS, browser=False, no_export=True, finance=fin)
    assert seen["fin"] == {"https://example.invalid/fin/rfp-1.pdf"} and FACTS["sources"][0]["url"] in seen["urls"]
    assert "https://example.invalid/fin/rfp-1.pdf" not in seen["urls"]   # finance sources travel apart


def _relink(f, url):
    """Point the first entry's source link of one feed at `url`."""
    root = parsed(f)
    link = next(x for x in root.iter(A + "link") if x.get("rel") == "related")
    link.set("href", url)
    ET.ElementTree(root).write(f, encoding="utf-8", xml_declaration=True)


def test_site_checks_know_a_finance_source_in_the_contracts_feed_only(site):
    # a finance.json document is a known source in topic-contracts.xml and nowhere else
    fin_url = "https://example.invalid/fin/rfp-1.pdf"
    pages = {f.relative_to(site).as_posix(): site_checks.parse(f) for f in site.rglob("*.html")}
    check = lambda: site_checks.check_feeds(site, pages, FACTS["sources"], config.SITE,  # noqa: E731
                                            finance_sources=[{"url": fin_url}])[0]
    assert site_checks.CONTRACTS_FEED == f"{feeds.FOLDER}/topic-contracts.xml"
    shutil.copy(site / "feeds" / "county-meetings.xml", site / site_checks.CONTRACTS_FEED)
    _relink(site / site_checks.CONTRACTS_FEED, fin_url)
    assert [p for p in check() if "not a fetched source" in p] == []
    _relink(site / "feeds" / "county-meetings.xml", fin_url)
    assert [p for p in check() if "not a fetched source" in p] == \
        [p for p in check() if p.startswith("feeds/county-meetings.xml") and fin_url in p] != []


@pytest.mark.parametrize("url", ["javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,x", "file:///etc/passwd",
                                 "vbscript:x", " javascript:alert(1)", "java\tscript:alert(1)"])
def test_site_checks_fail_a_feed_link_with_another_scheme(site, url):
    # morning-security/href-scheme-defense: never skipped
    _relink(site / "feeds" / "county-meetings.xml", url)
    assert any("link with scheme" in p for p in feeds_check(site)), feeds_check(site)


def test_one_per_body_feed_list_for_the_build_and_the_check(county, zoning_rpc, monkeypatch):
    assert site_checks.PER_BODY_FEEDS is feeds.PER_BODY_FEEDS == ("feeds/topic-rezoning.xml",)
    cfg = copy.deepcopy(config.SITE)
    cfg["alerts"]["max_entries"] = 2
    both = ids_of(feeds.build_feeds(county, cfg=cfg, rpc=zoning_rpc)["feeds/topic-rezoning.xml"])
    assert len(both) > 2                                   # 2 of each body
    monkeypatch.setattr(feeds, "PER_BODY_FEEDS", ())       # the build reads the list: off it, one cap for the feed
    assert len(ids_of(feeds.build_feeds(county, cfg=cfg, rpc=zoning_rpc)["feeds/topic-rezoning.xml"])) == 2


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


# -- Daylight M3 T2: contracts feed, RPC zoning cases, per-seat zoning feeds

FIN = FIXTURE.parent / "finance.sample.json"
CFG = config.SITE


def zcase(n, prefix="Z", district=None, ward=None, meeting="rpc-2026-11-24", date="2026-11-24"):
    return {"id": f"{date}-{prefix.lower()}-{n}-2026", "meeting_id": meeting, "prefix": prefix,
            "number": f"{prefix}-{n}-2026", "number_printed": f"{prefix}-{n}-2026", "page": n,
            "source_id": "src-rpc", "district": district, "ward": ward, "case_type": "City zoning",
            "request": f"R-1 to R-{n}"}


@pytest.fixture(scope="module")
def zoning_rpc():
    class R:   # the parts of sitegen.rpc.Rpc the feeds read
        body, body_key, cfg = "Planning Commission", "rpc", {"kind_labels": {"regular": "Regular"}}
        sources = {"src-rpc": {"url": "https://example.invalid/agenda.pdf"}}
        facts = {"meetings": [{"id": "rpc-2026-11-24", "date": "2026-11-24", "kind": "regular"}],
                 "cases": [zcase(1, district=3), zcase(2, ward=3), zcase(3, "CZ", district=21),
                           zcase(4, "Z"), zcase(5, "S", district=3), zcase(6, "HZ", district=3, ward=12)]}

        def year_href(self, y):
            return f"rpc/meetings/{y}.html"

        def case_anchor(self, c):
            return f"case-{c['id']}"
    return R()


@pytest.fixture(scope="module")
def county():
    return views.Index(FACTS)


@pytest.fixture(scope="module")
def fin():
    import json
    return json.loads(FIN.read_text(encoding="utf-8"))


def ids_of(raw):
    return [text(e, "id") for e in ET.fromstring(raw).findall(A + "entry")]


def test_contracts_feed_has_one_entry_per_solicitation(county, fin):
    out = feeds.build_feeds(county, cfg=CFG, fin=fin)
    ids = ids_of(out["feeds/topic-contracts.xml"])
    assert sorted(i.split(":")[-1] for i in ids) == sorted(f"contracts/solicitation/{s['id']}" for s in fin["solicitations"]
                                                           if s["document_ids"])
    assert "feeds/topic-contracts.xml" not in feeds.build_feeds(county, cfg=CFG)
    root = ET.fromstring(out["feeds/topic-contracts.xml"])
    titles = {text(e, "title") for e in root.findall(A + "entry")}
    assert titles <= {s["title"] for s in fin["solicitations"]}
    assert text(root, "title") == f"{config.SITE_NAME}: {CFG['alerts']['contracts_title']}"   # config text, not code
    cfg = copy.deepcopy(CFG)
    cfg["alerts"]["contracts_title"] = "Contracts: test title"
    assert text(ET.fromstring(feeds.build_feeds(county, cfg=cfg, fin=fin)["feeds/topic-contracts.xml"]), "title") \
        .endswith(": Contracts: test title")


def test_rpc_zoning_cases_join_the_rezoning_feed_and_old_ids_stay(county, zoning_rpc):
    old = ids_of(feeds.build_feeds(county, cfg=CFG)["feeds/topic-rezoning.xml"])
    new = ids_of(feeds.build_feeds(county, cfg=CFG, rpc=zoning_rpc)["feeds/topic-rezoning.xml"])
    assert set(old) <= set(new)
    added = [i.removeprefix(CFG["alerts"]["feed_id"]) for i in new if i not in old]
    assert sorted(added) == sorted(f"rpc/item/{c['id']}/rpc-2026-11-24" for c in zoning_rpc.facts["cases"]
                                   if c["prefix"] != "S")


def test_rpc_cases_beyond_max_entries_never_push_county_rezoning_items_out(county, zoning_rpc):
    # feeds/rezoning-keeps-every-body: RPC agendas are dated ahead and come often, county minutes run months behind;
    # the rezoning feed keeps the newest max_entries of each body, so every county entry stays.
    cap = CFG["alerts"]["max_entries"]

    class Many(type(zoning_rpc)):
        facts = {"meetings": [{"id": f"rpc-2027-{n:03d}", "date": f"2027-{1 + n // 28:02d}-{1 + n % 28:02d}",
                               "kind": "regular"} for n in range(cap + 10)],
                 "cases": [zcase(n, meeting=f"rpc-2027-{n:03d}") for n in range(cap + 10)]}
    county_ids = ids_of(feeds.build_feeds(county, cfg=CFG)["feeds/topic-rezoning.xml"])
    assert county_ids                                                 # the fixture has county rezoning items
    got = ids_of(feeds.build_feeds(county, cfg=CFG, rpc=Many())["feeds/topic-rezoning.xml"])
    assert set(county_ids) <= set(got)
    rpc_ids = [i for i in got if i.removeprefix(CFG["alerts"]["feed_id"]).startswith("rpc/")]
    assert len(rpc_ids) == cap and len(got) == cap + len(county_ids)
    assert f"rpc-2027-{cap + 9:03d}" in rpc_ids[0] and not any("rpc-2027-009/" in i for i in rpc_ids)  # RPC: its newest
    root = ET.fromstring(feeds.build_feeds(county, cfg=CFG, rpc=Many())["feeds/topic-rezoning.xml"])
    dates = [text(e, "updated") for e in root.findall(A + "entry")]
    assert dates == sorted(dates, reverse=True)                       # one list, newest first
    # every other feed keeps one cap across bodies
    assert feeds.newest([{"body": b, "sort": (n,)} for b in "ab" for n in range(cap)], cap) == \
        sorted([{"body": b, "sort": (n,)} for b in "ab" for n in range(cap)], key=lambda e: e["sort"], reverse=True)[:cap]


def test_per_seat_feeds_are_pages_target_only(county, zoning_rpc, fin):
    for target in ("preview", None):
        out = feeds.build_feeds(county, cfg=CFG, rpc=zoning_rpc, fin=fin, target=target)
        assert not [f for f in out if "zoning-" in f]
        assert not [f for f in feeds.feed_list(cfg=CFG, rpc=zoning_rpc, target=target) if f["kind"] == "zoning-seat"]
    out = feeds.build_feeds(county, cfg=CFG, rpc=zoning_rpc, fin=fin, target="pages")
    assert len([f for f in out if "zoning-district-" in f]) == CFG["district_count"] == 21
    assert len([f for f in out if "zoning-ward-" in f]) == CFG["ward_count"] == 12
    listed = [f for f in feeds.feed_list(cfg=CFG, rpc=zoning_rpc, target="pages") if f["kind"] == "zoning-seat"]
    assert len(listed) == 33 and {"seat", "number", "file", "title", "about"} <= set(listed[0])
    assert (listed[0]["seat"], listed[0]["number"], listed[0]["file"]) == ("district", 1, "feeds/zoning-district-01.xml")


def test_a_per_seat_feed_holds_only_cases_printing_that_number(county, zoning_rpc):
    out = feeds.build_feeds(county, cfg=CFG, rpc=zoning_rpc, target="pages")
    pre = CFG["alerts"]["feed_id"] + "rpc/item/2026-11-24-"
    cid = {n: f"{pre}{p}-{n}-2026/rpc-2026-11-24" for n, p in ((1, "z"), (2, "z"), (3, "cz"), (4, "z"), (6, "hz"))}
    assert set(ids_of(out["feeds/zoning-district-03.xml"])) == {cid[1], cid[6]}   # the S- plat is not zoning
    assert set(ids_of(out["feeds/zoning-district-21.xml"])) == {cid[3]}
    assert set(ids_of(out["feeds/zoning-ward-03.xml"])) == {cid[2]}
    assert set(ids_of(out["feeds/zoning-ward-12.xml"])) == {cid[6]}
    assert ids_of(out["feeds/zoning-district-02.xml"]) == []   # printed nowhere: empty, never guessed
    assert cid[4] not in "".join(v.decode() for k, v in out.items() if "zoning-" in k)


def test_new_feeds_are_valid_atom_and_ids_are_stable(county, zoning_rpc, fin):
    one = feeds.build_feeds(county, cfg=CFG, rpc=zoning_rpc, fin=fin, target="pages")
    two = feeds.build_feeds(county, cfg=CFG, rpc=zoning_rpc, fin=fin, target="pages")
    assert one == two
    for rel in [f for f in one if "zoning-" in f or "contracts" in f or "rezoning" in f]:
        root = ET.fromstring(one[rel])
        assert root.tag == A + "feed"
        for tag in ("id", "title", "updated", "subtitle"):
            assert text(root, tag), (rel, tag)
        for e in root.findall(A + "entry"):
            assert site_checks.RFC3339.fullmatch(text(e, "updated"))
            assert text(e, "id").startswith(CFG["alerts"]["feed_id"])
            assert [x for x in e.findall(A + "link") if x.get("rel") == "alternate"]
        assert len(set(ids_of(one[rel]))) == len(ids_of(one[rel]))


# -- morning-security/href-scheme-defense: an RPC source URL is a link only when it passes build._is_https_uri

@pytest.mark.parametrize("url", ["javascript:alert(1)//.pdf", "http://example.invalid/agenda.pdf", "data:text/html,x",
                                 "https://example.invalid/a b.pdf", 'https://example.invalid/a".pdf', "//example.invalid/a",
                                 "https:///agenda.pdf", ""])
def test_an_rpc_source_url_that_is_not_an_https_link_is_dropped(county, zoning_rpc, url):
    class Bad(type(zoning_rpc)):
        sources = {"src-rpc": {"url": url}}
    entries = feeds._rpc_entries(Bad(), feeds._rpc_cases(Bad(), CFG))
    assert entries and all(e["source"] == "" for e in entries)
    out = feeds.build_feeds(county, cfg=CFG, rpc=Bad(), target="pages")
    for rel in ("feeds/topic-rezoning.xml", "feeds/zoning-district-03.xml"):
        root = ET.fromstring(out[rel])
        rpc_entries = [e for e in root.findall(A + "entry") if "rpc/item/" in text(e, "id")]
        assert rpc_entries
        for e in rpc_entries:   # the entry stays, linked to its page here, with no source link
            assert [x.get("rel") for x in e.findall(A + "link")] == ["alternate"]
        if url:
            assert url.encode() not in out[rel]


def test_a_good_rpc_source_url_is_still_linked(zoning_rpc):
    e = feeds._rpc_entries(zoning_rpc, feeds._rpc_cases(zoning_rpc, CFG))[0]
    assert e["source"] == "https://example.invalid/agenda.pdf#page=1"


# ------------------------------------------------------------------ feeds/entry-date-is-local-day, alerts/entry-date-is-meeting-date
@pytest.mark.parametrize("day, want", [
    ("2026-01-15", "2026-01-15T12:00:00-06:00"),   # winter: CST
    ("2026-07-15", "2026-07-15T12:00:00-05:00"),   # summer: CDT
    ("2026-03-08", "2026-03-08T12:00:00-05:00"),   # spring forward (02:00 CST -> 03:00 CDT that morning)
    ("2026-11-01", "2026-11-01T12:00:00-06:00"),   # fall back (02:00 CDT -> 01:00 CST that morning)
])
def test_a_bare_day_is_noon_in_the_site_zone(day, want):
    assert feeds._stamp(day) == want
    assert site_checks.RFC3339.fullmatch(want)


@pytest.mark.parametrize("fetched, want", [
    ("2026-01-16T03:30:00+00:00", "2026-01-15T21:30:00-06:00"),   # winter evening: the UTC date is the next day
    ("2026-07-16T03:30:00+00:00", "2026-07-15T22:30:00-05:00"),   # summer evening
    ("2026-03-08T07:30:00+00:00", "2026-03-08T01:30:00-06:00"),   # spring-forward day, before the change
    ("2026-03-08T08:30:00+00:00", "2026-03-08T03:30:00-05:00"),   # and after it
    ("2026-11-01T06:30:00+00:00", "2026-11-01T01:30:00-05:00"),   # fall-back day, the first 01:30
    ("2026-11-01T07:30:00+00:00", "2026-11-01T01:30:00-06:00"),   # the second 01:30
])
def test_a_first_fetched_at_keeps_its_instant_with_the_local_offset(fetched, want):
    from datetime import datetime
    assert feeds._stamp(datetime.fromisoformat(fetched)) == want


def test_entries_are_dated_when_their_document_was_added_and_ids_do_not_change(county):
    """With the manifests' first_fetched_at, updated and published are that instant in site_timezone (not the
    meeting's date at midnight UTC), the feed lists entries by it, and every id is what it was without it."""
    from datetime import datetime, timedelta, timezone
    srcs = sorted(FACTS["sources"], key=lambda s: s["id"])
    base = datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)         # 21:00 CST on November 9: UTC is a day ahead
    first = {s["url"]: base + timedelta(hours=k) for k, s in enumerate(srcs)}
    plain = feeds.build_feeds(county, cfg=CFG)
    dated = feeds.build_feeds(county, cfg=CFG, first=first)
    assert sorted(plain) == sorted(dated)
    for rel in dated:
        assert sorted(ids_of(plain[rel])) == sorted(ids_of(dated[rel])), rel
    root = ET.fromstring(dated["feeds/county-meetings.xml"])
    by_source = {s["id"]: s for s in FACTS["sources"]}
    for m in FACTS["meetings"]:
        e = next(e for e in root.findall(A + "entry") if text(e, "id").endswith(f"/{m['id']}/minutes"))
        want = first[by_source[m["source_id"]]["url"]].astimezone(feeds._zone()).isoformat(timespec="seconds")
        assert text(e, "updated") == text(e, "published") == want
        assert text(e, "updated")[19:] == "-06:00"
        # feeds/entry-date-is-local-day/summary-fetched-utc: the summary's day is the entry's own Chicago day
        assert text(e, "summary").endswith(f", fetched {want[:10]}."), text(e, "summary")
    assert all(text(e, "summary").endswith("fetched 2026-11-09.") for e in root.findall(A + "entry"))   # not 11-07 or 11-10
    dates = [text(e, "updated") for e in root.findall(A + "entry")]
    assert dates == sorted(dates, reverse=True) and text(root, "updated") == dates[0]


def test_county_agenda_only_meetings_join_the_county_feed(county):
    """alerts/county-agendas-not-in-feed: each agenda-only county meeting (no minutes yet) is one entry of the
    county's agendas-and-minutes feed, id county/meeting/<id>/agenda, linked to meetings/agendas.html; a meeting the
    minutes cover is not; the other feeds and every earlier id are unchanged."""
    from datetime import date, datetime
    from sitegen import county_agendas
    covered = FACTS["meetings"][0]
    src = {"id": "src-agenda1", "url": "https://example.invalid/nov-formal.pdf", "kind": "agenda", "pages": 9,
           "fetched_at": "2026-11-10", "label": "2026 November Formal", "sha256": "a" * 64}
    data = {"body": "Montgomery County Commission", "index_url": "https://example.invalid/agendas", "skipped": [],
            "problems": [], "sources": [src],
            "meetings": [{"id": "2026-11-16-formal", "date": "2026-11-16", "kind": "formal", "source_id": src["id"],
                          "date_page": 1, "items": []},
                         {"id": covered["id"], "date": covered["date"], "kind": covered["kind"],
                          "source_id": src["id"], "date_page": 1, "items": []}]}
    ax = county_agendas.Agendas(data, county, date(2026, 11, 10))
    plain = feeds.build_feeds(county, cfg=CFG)
    first = {src["url"]: datetime.fromisoformat("2026-11-10T04:33:47+00:00")}   # the evening of November 9 here
    out = feeds.build_feeds(county, cfg=CFG, agendas=ax, first=first)
    prefix = CFG["alerts"]["feed_id"]
    added = sorted(set(ids_of(out["feeds/county-meetings.xml"])) - set(ids_of(plain["feeds/county-meetings.xml"])))
    assert added == [f"{prefix}county/meeting/2026-11-16-formal/agenda"]
    assert set(ids_of(plain["feeds/county-meetings.xml"])) <= set(ids_of(out["feeds/county-meetings.xml"]))
    assert {k: v for k, v in out.items() if k != "feeds/county-meetings.xml"} == \
        {k: v for k, v in plain.items() if k != "feeds/county-meetings.xml"}
    e = next(e for e in ET.fromstring(out["feeds/county-meetings.xml"]).findall(A + "entry")
             if text(e, "id") == added[0])
    assert text(e, "title") == "Agenda: 2026-11-16, formal meeting"   # as a minutes entry labels it
    assert text(e, "updated") == text(e, "published") == "2026-11-09T22:33:47-06:00"
    links = {x.get("rel"): x.get("href") for x in e.findall(A + "link")}
    assert links == {"alternate": "../meetings/agendas.html#2026-11-16-formal", "related": src["url"]}
    assert "Agenda (9 pages), fetched 2026-11-09." in text(e, "summary")   # the Chicago day, not the UTC 11-10


def test_the_home_page_lets_a_reader_discover_the_feeds(built, pages):
    """feeds/autodiscovery-on-index (plan F6): index.html carries a rel=alternate Atom link per body feed, each to
    a built feed."""
    import re
    links = re.findall(r'<link rel="alternate" type="application/atom\+xml" title="([^"]+)" href="([^"]+)">',
                       pages["index.html"].split("</head>")[0])
    want = [f for f in feeds.feed_list() if f["kind"] == "body"]
    assert [h for _, h in links] == [f["file"] for f in want] and want
    assert [t for t, _ in links] == [f["title"] for f in want]
    assert all((built / h).is_file() for _, h in links)


def test_without_a_manifest_row_an_entry_is_its_fetched_day_at_local_noon(built):
    """A fixture build has no manifests: each entry is its source's fetched day (never the meeting's) at noon."""
    fetched = {s["fetched_at"] for s in FACTS["sources"]}
    root = parsed(built / "feeds" / "county-meetings.xml")
    for e in root.findall(A + "entry"):
        up = text(e, "updated")
        assert up == text(e, "published") and up[:10] in fetched and up[10:19] == "T12:00:00", up
        assert text(e, "summary").endswith(f", fetched {up[:10]}."), text(e, "summary")   # one day, both places


# ------------------------------------------------------------------ the fall-back hour: newest first by instant, not text
FOLD_EARLY, FOLD_LATE = "2026-11-01T01:30:00-05:00", "2026-11-01T01:15:00-06:00"   # 06:30Z, then 07:15Z


def test_feed_lists_the_fall_back_hour_by_instant():
    from datetime import datetime
    es = [dict(entry(1), updated=datetime.fromisoformat(FOLD_EARLY), sort=("2026-11-01", 2)),
          dict(entry(2), updated=datetime.fromisoformat(FOLD_LATE), sort=("2026-11-01", 1))]
    root = ET.fromstring(feeds.render({"file": "feeds/t.xml", "title": "T", "about": "A"}, es))
    assert [text(e, "updated") for e in root.findall(A + "entry")] == [FOLD_LATE, FOLD_EARLY]
    assert text(root, "updated") == FOLD_LATE


@pytest.mark.parametrize("order, ok", [((FOLD_LATE, FOLD_EARLY), True), ((FOLD_EARLY, FOLD_LATE), False)])
def test_site_checks_compare_entry_dates_as_instants(site, order, ok):
    import re
    f = site / "feeds" / "county-meetings.xml"
    head, _, rest = f.read_text(encoding="utf-8").partition("<entry>")
    dates = iter(order + ("2026-10-01T12:00:00-05:00",) * 10)
    rest = re.sub(r"<updated>[^<]+</updated>", lambda m: f"<updated>{next(dates)}</updated>", rest)
    f.write_text(head + "<entry>" + rest, encoding="utf-8")
    newest = [p for p in feeds_check(site) if "newest first" in p]
    assert (newest == []) if ok else newest, newest


def test_render_writes_the_configured_zone():
    """site_timezone comes from the cfg render is given, not only from config.SITE."""
    cfg = {**CFG, "site_timezone": "America/New_York"}
    root = ET.fromstring(feeds.render({"file": "feeds/t.xml", "title": "T", "about": "A"}, [entry(200)], cfg))
    assert text(root.find(A + "entry"), "updated") == "2026-08-05T12:00:00-04:00"   # EDT
    assert text(root, "updated") == "2026-08-05T12:00:00-04:00"
