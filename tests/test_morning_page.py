# ruff: noqa: E501
"""Morning note, the visitor's side (Daylight M3 T3, docs/tasks/morning-note.md): the #note section on alerts.html,
the preview page morning/index.html and static/morning.js. Off (M3): no email field, no submit, no form action and no
success text; the CSP is unchanged; morning.js makes no network call and its select() matches sitegen/morning.py
select() on the fixture day (site/fixtures/morning.sample.json) for every list and seat combination. The enabled path
is built only from a test config here. The browser run (Playwright Chromium over a local server) checks the picker by
keyboard, the per-seat feed choice, the preview filter, no request leaving the site, and no sideways scroll at 360 px."""
import copy
import functools
import http.server
import itertools
import json
import os
import re
import shutil
import subprocess
import threading

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT, parse
from qa import site_checks
from sitegen import config, morning, morning_page, views
from sitegen.build import build
from test_site_neutrality import BANNED

DAY = json.loads((ROOT / "site" / "fixtures" / "morning.sample.json").read_text(encoding="utf-8"))
MORNING_JS = ROOT / "site" / "static" / "morning.js"
LISTS = [x["key"] for x in config.SITE["morning_note"]["lists"]]
SEATS = [None, {"district": 7, "ward": None}, {"district": None, "ward": 6}, {"district": 7, "ward": 6},
         {"district": 3, "ward": 2}, {"district": 12, "ward": None}, {"district": None, "ward": 2}]
# Per-seat zoning feeds as T2's feed_list() shows them on the pages target (the fixture build has none).
SEAT_FEEDS = [{"file": "feeds/zoning-district-07.xml", "kind": "zoning-seat", "seat": "district", "number": 7,
               "title": "Zoning cases: District 7", "about": "", "key": "zoning-district-07"},
              {"file": "feeds/zoning-ward-06.xml", "kind": "zoning-seat", "seat": "ward", "number": 6,
               "title": "Zoning cases: Ward 6", "about": "", "key": "zoning-ward-06"}]
SUCCESS = re.compile(r"\b(subscribed|thank you|thanks|you're on|you are on|signed up|check your (e-?mail|inbox)|"
                     r"success|confirmed your)\b", re.IGNORECASE)
CSP_META = re.compile(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">')


def _no_second_day(*a, **kw):
    raise AssertionError("the preview page renders the note write() returned; day() is never called again")


def _build(out, monkeypatch, cfg=None, seat_feeds=False, note=None, **kw):
    """A fixture build whose note (sitegen/morning.py write()) is `note` (the fixture day by default). A fixture
    build reads no manifests, so an empty manifest list stands in: write() still runs, as on the pages target."""
    note = DAY if note is None else note
    monkeypatch.setattr(morning, "write", lambda out, today, docs, first, **k: copy.deepcopy(note))
    monkeypatch.setattr(morning, "day", _no_second_day)
    if cfg is not None:
        monkeypatch.setattr(config, "SITE", cfg)
    if seat_feeds:
        orig = morning_page.alerts_context
        monkeypatch.setattr(morning_page, "alerts_context",
                            lambda feeds, cfg=None, preview=False: orig(feeds + SEAT_FEEDS, cfg, preview))
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS,
          **{"morning_manifests": [], "target": "pages", **kw})
    return {p.relative_to(out).as_posix(): p.read_text(encoding="utf-8") for p in out.rglob("*.html")}


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    out = tmp_path_factory.mktemp("morning") / "site"
    pages = _build(out, mp, seat_feeds=True)
    mp.undo()
    return out, pages


def _main(html):
    return html[html.index("<main"):html.index("</main>")]


def _note(html):
    start = html.index('id="note"')
    return html[html.rindex("<", 0, start):html.index('<h2>How to follow a feed</h2>')]


# -- off (M3): nothing to submit, nothing claimed

def test_disabled_note_has_no_email_field_submit_action_or_names(site):
    _, pages = site
    note = _note(pages["alerts.html"])
    assert "<form" not in note and "action=" not in note
    assert 'type="email"' not in note and "<button" not in note and 'type="submit"' not in note
    assert " name=" not in note                                   # nothing could ever be submitted
    assert config.SITE["morning_note"]["page"]["state_off"] in note
    for x in config.SITE["morning_note"]["lists"]:
        assert f'id="n-{x["key"]}"' in note and x["label"] in note
    assert "<legend>" in note
    for html in pages.values():
        assert 'type="email"' not in html


def test_no_success_text_anywhere_while_disabled(site):
    _, pages = site
    for rel, html in pages.items():
        m = SUCCESS.search(parse(_main(html)).all_text())
        assert m is None, (rel, m.group(0))
    assert SUCCESS.search(MORNING_JS.read_text(encoding="utf-8")) is None
    assert SUCCESS.search(json.dumps(config.SITE["morning_note"])) is None


def test_morning_js_makes_no_network_call_and_stores_nothing():
    js = MORNING_JS.read_text(encoding="utf-8")
    for bad in ("fetch", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource", "import(", "new Image",
                "localStorage", "sessionStorage", "cookie", "submit(", ".src =", "open("):
        assert bad not in js, bad


def test_csp_unchanged_when_disabled(site):
    _, pages = site
    for rel, html in pages.items():
        assert CSP_META.findall(html) == [views.csp().replace("'", "&#39;")], rel
    assert morning_page.form_origin() is None


def test_nav_morning_note_links_the_section_on_every_page(site):
    _, pages = site
    for rel, html in pages.items():
        nav = html[html.index('<nav id="site-nav"'):]
        nav = nav[:nav.index("</nav>")]
        assert re.search(r'href="(\.\./)*alerts\.html#note"[^>]*>Morning note<', nav), rel
    assert 'id="note"' in pages["alerts.html"]
    assert 'aria-current="page">Morning note' not in pages["morning/index.html"]


def test_no_js_shows_every_list_and_its_feeds(site):
    _, pages = site
    tree = parse(_note(pages["alerts.html"]))
    lists = [n for n in tree.walk() if n.tag == "li" and "data-list" in n.attrs]
    assert [n.attrs["data-list"] for n in lists] == LISTS
    for n in lists:
        assert "hidden" not in n.attrs
    shown = [n.attrs["href"] for n in tree.walk() if n.tag == "a" and n.attrs.get("type") == "application/atom+xml"
             and not any("hidden" in p.attrs for p in _parents(n))]
    assert "feeds/topic-rezoning.xml" in shown and "feeds/topic-budget.xml" in shown
    assert "feeds/county-meetings.xml" in shown
    assert "feeds/zoning-district-07.xml" not in shown              # a per-seat feed waits for the stored seat
    assert 'href="feeds/zoning-district-07.xml"' in pages["alerts.html"]


def _parents(n):
    while n is not None:
        yield n
        n = n.parent


def test_list_feed_mapping():
    feeds = [{"file": "feeds/county-meetings.xml", "kind": "body", "key": "county", "title": "c"},
             {"file": "feeds/council-a-meetings.xml", "kind": "body", "key": "council-a", "title": "w"},
             {"file": "feeds/topic-rezoning.xml", "kind": "topic", "key": "rezoning", "title": "z"},
             {"file": "feeds/topic-budget.xml", "kind": "topic", "key": "budget", "title": "b"},
             {"file": "feeds/topic-contracts.xml", "kind": "topic", "key": "contracts", "title": "k"}] + SEAT_FEEDS
    by = {x["key"]: x["feeds"] for x in morning_page._lists(feeds, config.SITE)}
    assert [f["file"] for f in by["zoning"]] == ["feeds/topic-rezoning.xml", "feeds/zoning-district-07.xml",
                                                 "feeds/zoning-ward-06.xml"]
    assert [(f["file"], f["seat"]) for f in by["seats"]] == [("feeds/county-meetings.xml", "district"),
                                                             ("feeds/council-a-meetings.xml", "ward")]
    assert [f["file"] for f in by["budget"]] == ["feeds/topic-budget.xml"]
    assert [f["file"] for f in by["contracts"]] == ["feeds/topic-contracts.xml"]


# -- the preview page

def test_preview_page_renders_every_entry_with_its_filter_data(site):
    _, pages = site
    html = pages["morning/index.html"]
    tree = parse(_main(html))
    lis = [n for n in tree.walk() if n.tag == "li" and "mn-entry" in n.attrs.get("class", "")
           and "data-unplaced" not in n.attrs]
    assert len(lis) == len(DAY["entries"])
    for n, e in zip(lis, DAY["entries"]):
        assert n.attrs["data-lists"] == " ".join(e["lists"]) and n.attrs["data-body"] == e["body"]
        assert n.attrs.get("data-district") == (None if e["district"] is None else str(e["district"]))
        assert n.attrs.get("data-ward") == (None if e["ward"] is None else str(e["ward"]))
        assert e["title"] in n.all_text() and e["recorded"] in n.all_text()
    assert "1 zoning case printed no district or ward" in html
    assert "December 10, 2024: what was added to this site from December 9, 7:00 AM to December 10, 7:00 AM" in html
    assert BANNED.search(parse(_main(html)).all_text()) is None
    assert BANNED.search(json.dumps(DAY)) is None
    assert 'href="../meetings/2024-12-09-formal.html"' in html     # site links from one folder down


def test_quiet_day_says_so_and_sends_nothing(tmp_path, monkeypatch):
    quiet = {**copy.deepcopy(DAY), "entries": [], "unplaced_zoning": 0, "unplaced_text": ""}
    html = _build(tmp_path / "site", monkeypatch, note=quiet)["morning/index.html"]
    q = re.search(r'<p class="mn-quiet"[^>]*>([^<]*)<', html)
    assert "hidden" not in q.group(0) and q.group(1) == config.SITE["morning_note"]["page"]["quiet"]
    assert config.SITE["morning_note"]["page"]["backfill"] not in html


def test_backfill_day_says_the_first_collection_is_not_sent(tmp_path, monkeypatch):
    # morning-preview/backfill-day: a first-collection day has many new records and no note; "Nothing new" is false
    t = config.SITE["morning_note"]["page"]
    bf = {**copy.deepcopy(DAY), "backfill": True, "entries": [], "unplaced_zoning": 0, "unplaced_text": "",
          "counts": {"entries": 412, "lists": {"zoning": 40, "seats": 300, "budget": 60, "contracts": 12},
                     "unplaced_zoning": 9}}
    html = _build(tmp_path / "site", monkeypatch, note=bf)["morning/index.html"]
    q = re.search(r'<p class="mn-quiet"[^>]*>([^<]*)<', html)
    assert "hidden" not in q.group(0) and q.group(1) == t["backfill"]
    assert t["quiet"] not in html
    assert BANNED.search(t["backfill"]) is None and SUCCESS.search(t["backfill"]) is None


def test_entries_without_a_meeting_date_print_no_none(site):
    # morning-preview/no-None-text: budget books, solicitations and contract documents carry meeting_date None
    _, pages = site
    assert [e for e in DAY["entries"] if e["meeting_date"] is None]
    tree = parse(_main(pages["morning/index.html"]))
    metas = [n.all_text() for n in tree.walk() if n.tag == "p" and n.attrs.get("class") == "mn-meta"]
    assert len(metas) == len(DAY["entries"])
    assert not [m for m in metas if "None" in m]
    for m, e in zip(metas, DAY["entries"]):
        assert (e["meeting_date"] or "") in m and (", " + e["meeting_date"] if e["meeting_date"] else "") in m
        if e["meeting_date"] is None:
            assert not m.rstrip().endswith(",")


def test_unplaced_line_is_the_notes_own_text(site):
    # morning-text/one-source: the page prints the note's unplaced_text, not a second copy in the page block
    _, pages = site
    li = re.search(r'<li class="mn-entry mn-unplaced"[^>]*>(.*?)</li>', pages["morning/index.html"], re.S).group(1)
    assert li.startswith(DAY["unplaced_text"] + ": ")
    assert morning.unplaced_text(DAY["unplaced_zoning"]) == DAY["unplaced_text"]


def test_every_entry_carries_its_seat_body(site):
    # morning-signup/seats-match-by-seat_body: the page emits T1's seat_body; the JS matches on it, not on the body
    _, pages = site
    tree = parse(_main(pages["morning/index.html"]))
    lis = [n for n in tree.walk() if n.tag == "li" and "mn-entry" in n.attrs.get("class", "")
           and "data-unplaced" not in n.attrs]
    assert all("seat_body" in e for e in DAY["entries"])
    assert [n.attrs.get("data-seat-body") for n in lis] == [e["seat_body"] for e in DAY["entries"]]
    assert "data-county" not in pages["morning/index.html"] and "countyKey" not in MORNING_JS.read_text()


@pytest.mark.parametrize("why", ["fixture build", "preview target"])
def test_no_note_means_no_preview_page_and_no_link_to_it(tmp_path, monkeypatch, why):
    # morning-preview/pages-only: the page is built only from the note write() returned (pages target, manifests)
    monkeypatch.setattr(morning, "day", _no_second_day)
    out = tmp_path / "site"
    kw = {"target": "preview", "morning_manifests": []} if why == "preview target" else {"target": "pages"}
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, **kw)
    assert not (out / "morning").exists()
    html = (out / "alerts.html").read_text(encoding="utf-8")
    assert 'id="note"' in html                                         # the sign-up section and its feeds stay
    assert 'id="mn-preview"' not in html and "data-preview" not in html and "morning/index.html" not in html
    assert config.SITE["morning_note"]["page"]["preview_link"] not in html
    pages = {f.relative_to(out).as_posix(): site_checks.parse(f) for f in out.rglob("*.html")}
    assert [m for m in site_checks.check_links(out, pages, no_export=True) if "morning" in m] == []


def test_preview_link_when_the_page_is_built(site):
    _, pages = site
    html = pages["alerts.html"]
    assert 'id="mn-preview" href="morning/index.html"' in html and 'data-preview="morning/index.html"' in html


def test_site_link_check_passes_on_the_note_pages(site):
    out, _ = site
    pages = {f.relative_to(out).as_posix(): site_checks.parse(f) for f in out.rglob("*.html")}
    bad = [m for m in site_checks.check_links(out, pages, no_export=True)
           if ("alerts.html" in m or "morning/" in m) and "zoning-district-07" not in m and "zoning-ward-06" not in m]
    assert bad == []


# -- morning-security/href-scheme-defense

BAD_URLS = ["javascript:alert(1)", "JAVASCRIPT:alert(1)//.pdf", "http://example.org/a.pdf", "data:text/html,x",
            "https://example.org/a b.pdf", "//example.org/a.pdf", "vbscript:x", "https://example.org/a\"onclick=\"x"]


def _day_with_source(url):
    day = copy.deepcopy(DAY)
    day["entries"][0]["source"] = {"url": url, "page": 3}
    return day


@pytest.mark.parametrize("url", BAD_URLS)
def test_preview_drops_a_source_url_that_is_not_an_https_link(url):
    ctx = morning_page.preview(_day_with_source(url), [])
    assert ctx["entries"][0]["source"] == {"url": "", "page": None}
    assert ctx["entries"][0]["title"] == DAY["entries"][0]["title"]          # the entry itself stays
    assert [e["source"]["url"] for e in ctx["entries"][1:]] == \
        [(e.get("source") or {}).get("url") or "" for e in DAY["entries"][1:]]   # good links untouched


def test_preview_page_renders_no_link_for_a_bad_source_url(tmp_path, monkeypatch):
    pages = _build(tmp_path / "site", monkeypatch, note=_day_with_source("javascript:alert(1)"))
    html = pages["morning/index.html"]
    assert "javascript:" not in html
    first = html.split('class="mn-entry"')[1]
    assert DAY["entries"][0]["title"] in first and 'class="mn-src"' not in first
    assert html.count('class="mn-src"') == sum(1 for e in DAY["entries"] if (e.get("source") or {}).get("url")) - 1


@pytest.mark.parametrize("href", ["javascript:alert(1)", "JaVaScRiPt:alert(1)", " javascript:alert(1)",
                                  "java&#9;script:alert(1)", "&#106;avascript:alert(1)", "data:text/html,x",
                                  "vbscript:x", "file:///etc/passwd", "tel:+19315550100", "mailto:someone@example.org",
                                  "//example.org/x"])
def test_site_checks_fail_a_link_with_another_scheme(site, tmp_path, href):
    # site_checks never skips a non-http(s) href: the only one allowed is report.html's own mailto from the config
    out, _ = site
    dst = tmp_path / "site"
    shutil.copytree(out, dst)
    f = dst / "morning" / "index.html"
    f.write_text(f.read_text(encoding="utf-8").replace("</main>", f'<a href="{href}">x</a></main>'), encoding="utf-8")
    pages = {p.relative_to(dst).as_posix(): site_checks.parse(p) for p in dst.rglob("*.html")}
    bad = [m for m in site_checks.check_links(dst, pages, no_export=True) if "href with scheme" in m]
    assert len(bad) == 1 and bad[0].startswith("morning/index.html"), bad


@pytest.mark.parametrize("tag", ['<form action="javascript:alert(1)"></form>', '<script src="data:text/javascript,x"></script>',
                                 '<img src="javascript:x" alt="">', '<iframe src="data:text/html,x"></iframe>'])
def test_site_checks_fail_a_resource_with_another_scheme(site, tmp_path, tag):
    out, _ = site
    dst = tmp_path / "site"
    shutil.copytree(out, dst)
    f = dst / "morning" / "index.html"
    f.write_text(f.read_text(encoding="utf-8").replace("</main>", tag + "</main>"), encoding="utf-8")
    pages = {p.relative_to(dst).as_posix(): site_checks.parse(p) for p in dst.rglob("*.html")}
    assert [m for m in site_checks.check_links(dst, pages, no_export=True) if "with scheme" in m]


@pytest.mark.parametrize("href, bad", [
    ("meetings.html", False), ("../a/b.html#x", False), ("#top", False), ("https://example.org/a.pdf#page=2", False),
    ("http://example.org/", False), ("?q=a:b", False), ("a/b:c.html", False), ("", False),
    ("javascript:x", True), ("\x01javascript:x", True), ("jav\nascript:x", True), ("mailto:a@example.org", True),
    ("tel:1", True), ("data:,x", True), ("blob:https://example.org/1", True), ("ftp://example.org/a", True)])
def test_bad_scheme(href, bad):
    assert site_checks.bad_scheme(href) is bad


# -- JS select() == Python select()

def _node():
    return shutil.which("node")


@pytest.mark.skipif(not _node(), reason="node not available")
def test_js_select_matches_python_select_for_every_list_and_seat_combination():
    combos = [list(c) for r in range(len(LISTS) + 1) for c in itertools.combinations(LISTS, r)]
    cases = [{"lists": c, "seats": s} for c in combos for s in SEATS]
    # seat_body decides "seats", not the body key: one entry of a body other than the county's tied to a district,
    # and one with no seat at all, which the old body === county rule would have read differently
    day = copy.deepcopy(DAY)
    day["entries"] += [
        {**DAY["entries"][5], "id": "rpc/vote/x-1", "body": "rpc", "seat_body": "district", "lists": ["seats"]},
        {**DAY["entries"][5], "id": "rpc/vote/x-2", "body": "rpc", "seat_body": None, "lists": ["seats"]}]
    prog = ("const m = require(process.argv[1]); const inp = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
            "console.log(JSON.stringify(inp.cases.map(c => m.select(inp.day, c.lists, c.seats)"
            ".map(e => e.id))));")
    r = subprocess.run(["node", "-e", prog, str(MORNING_JS)], capture_output=True, text=True, timeout=60,
                       input=json.dumps({"day": day, "cases": cases}))
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    py = [[e["id"] for e in morning.select(day, c["lists"], c["seats"])] for c in cases]
    assert js == py
    seats_d7 = [e["id"] for e in morning.select(day, ["seats"], {"district": 7, "ward": None})]
    assert "rpc/vote/x-1" in seats_d7 and "rpc/vote/x-2" not in seats_d7
    # and the rule itself, as the architecture states it
    sel = lambda lists, seats: [e["id"].split("/")[2] for e in morning.select(DAY, lists, seats)]  # noqa: E731
    assert sel(["zoning"], {"district": 7, "ward": None}) == ["Z-1-2024", "CZ-5-2024"]
    assert sel(["zoning"], {"district": None, "ward": 2}) == ["Z-3-2024"]
    assert sel(["zoning"], None) == []
    assert "CZO-4-2024" not in sel(["zoning"], {"district": 7, "ward": 6})
    assert sel(["seats"], {"district": None, "ward": 6}) == ["rc-1"]


def test_js_parse_lists_keeps_known_keys_only():
    if not _node():
        pytest.skip("node not available")
    prog = ("const m = require(process.argv[1]); const k = ['zoning','seats','budget','contracts'];"
            "console.log(JSON.stringify([m.parseLists('#lists=budget,zoning', k), m.parseLists('#note', k),"
            "m.parseLists('#lists=', k), m.parseLists('#lists=evil,budget', k), m.parseLists('', k)]));")
    r = subprocess.run(["node", "-e", prog, str(MORNING_JS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [["zoning", "budget"], None, [], ["budget"], None]


# -- the enabled path, from a test config only

ENABLED = {"enabled": True, "provider": "Example Mail", "form_action": "https://forms.example.net/subscribe/x",
           "privacy_url": "https://example.net/privacy"}


def test_enabled_path_in_a_test_config(tmp_path, monkeypatch):
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"].update(ENABLED)
    pages = _build(tmp_path / "site", monkeypatch, cfg)
    html = pages["alerts.html"]
    note = _note(html)
    fields = cfg["morning_note"]["form_fields"]
    assert re.search(r'<form class="mn-card" id="note" action="https://forms\.example\.net/subscribe/x" method="post"',
                     note)
    assert f'type="email" id="note-email" name="{fields["email"]}"' in note and 'type="submit"' in note
    assert f'name="{fields["lists"]}"' in note and f'name="{fields["district"]}"' in note
    assert 'href="https://example.net/privacy"' in note and "Example Mail" in note
    pol = site_checks.parse_csp(CSP_META.findall(html)[0].replace("&#39;", "'"))
    assert pol["form-action"] == ["'self'", "https://forms.example.net"]
    assert {k: v for k, v in pol.items() if k != "form-action"} == \
        {k: v for k, v in site_checks.parse_csp(views.csp()).items() if k != "form-action"}
    for rel, page in pages.items():   # only the Alerts page gains the origin
        if rel != "alerts.html":
            assert CSP_META.findall(page) == [views.csp().replace("'", "&#39;")], rel
    assert "We keep no list of followers" not in _main(html)
    assert SUCCESS.search(parse(_main(html)).all_text()) is None
    # the preview page's picker never submits
    assert " name=" not in _main(pages["morning/index.html"]).split('class="mn-picker"')[1].split("</fieldset>")[0]


@pytest.mark.parametrize("on", [True, False])
def test_support_line_beside_the_sign_up_only_with_support_on(tmp_path, monkeypatch, on):
    """Brian 2026-11-10: the sign-up says the service is free and always will be and links the tip jar, only when
    the footer support link is switched on (tests/support-line-alerts-untested)."""
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"].update(ENABLED)
    cfg.update(support_enabled=on, support_url="https://buymeacoffee.com/gnoshcodes")
    note = _note(_build(tmp_path / "site", monkeypatch, cfg)["alerts.html"])
    assert (cfg["support_line"] in note) is on
    assert ('data-ext="support" href="https://buymeacoffee.com/gnoshcodes"' in note) is on


def test_enabled_without_privacy_or_action_renders_the_off_state(tmp_path, monkeypatch):
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"].update({**ENABLED, "privacy_url": ""})
    assert not morning_page.enabled(cfg) and morning_page.form_origin(cfg) is None
    assert morning_page.privacy(cfg) is None


# -- morning-security/privacy-text-matches-data-flow and seat-consent (the enabled state, a test config only)

NEVER_SENT = re.compile(r"never\s+sent\s+anywhere|nothing\s+is\s+sent\s+anywhere|is\s+never\s+sent", re.IGNORECASE)


@pytest.fixture(scope="module")
def enabled_site(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    out = tmp_path_factory.mktemp("morning-on") / "site"
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"].update(ENABLED)
    pages = _build(out, mp, cfg)
    mp.undo()
    return out, pages, cfg


def _words(html):
    return " ".join(parse(_main(html)).all_text().split())


def test_committed_config_keeps_email_off():
    mn = config.SITE["morning_note"]
    assert mn["enabled"] is False and not mn["form_action"] and not mn["provider"] and not mn["privacy_url"]
    assert morning_page.privacy() is None


def test_disabled_build_keeps_the_never_sent_sentences_and_has_no_note_paragraph(site):
    _, pages = site
    assert "It stays on your device and is never sent anywhere." in _words(pages["method.html"])
    assert "Nothing is sent anywhere and no cookies are used." in " ".join(pages["index.html"].split())
    assert 'id="note-sent-h"' not in pages["method.html"]
    for rel, html in pages.items():   # none of the enabled-state text is printed while off
        assert "Include my saved seats" not in html and 'id="note-seats"' not in html, rel


def test_enabled_build_never_says_the_seats_are_never_sent(enabled_site):
    _, pages, _ = enabled_site
    for rel, html in pages.items():
        m = NEVER_SENT.search(" ".join(html.split()))
        assert m is None, (rel, m.group(0))
    for name in ("seats.js", "address.js", "morning.js"):   # nor does a script print it
        js = (ROOT / "site" / "static" / name).read_text(encoding="utf-8")
        assert not re.search(r"""["'][^"'\n]*(never sent|sent anywhere)[^"'\n]*["']""", js, re.IGNORECASE), name


def test_enabled_build_says_what_is_sent_on_the_landing_and_method_pages(enabled_site):
    _, pages, cfg = enabled_site
    t = cfg["morning_note"]["page"]
    seats_sent = t["seats_sent"].format(provider="Example Mail")
    assert "Example Mail" in seats_sent and "Include my saved seats" in seats_sent
    landing = " ".join(parse(pages["index.html"]).all_text().split())
    assert f"Saved only in this browser, on this device. {seats_sent} No cookies are used." in landing
    method = _words(pages["method.html"])
    assert f'so the home page can show "Your seats" next time. {seats_sent} The Forget button' in method
    # the Method page's Morning note paragraph: what is sent, to whom, how to stop, the provider's privacy policy
    sec = pages["method.html"].split('<section aria-labelledby="note-sent-h">')[1].split("</section>")[0]
    text = " ".join(parse(sec).all_text().split())
    assert f"<h2 id=\"note-sent-h\">{t['method_heading']}</h2>" in sec
    assert t["method_sent"].format(provider="Example Mail") in text and t["method_unsubscribe"] in text
    for word in ("email address", "lists", "district and ward", "Example Mail", "unsubscribe"):
        assert word in text, word
    assert '<a data-ext="provider" href="https://example.net/privacy" rel="noopener noreferrer">Example Mail: ' \
        f'{t["privacy_label"]}</a>' in sec
    assert f'<a href="alerts.html#note">{t["method_signup_link"]}</a>' in sec


def test_privacy_text_is_config_text(tmp_path, monkeypatch):
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"].update(ENABLED)
    cfg["morning_note"]["page"].update({
        "seats_sent": "SEATS-SENT to {provider}.", "method_heading": "METHOD-HEADING",
        "method_sent": "METHOD-SENT to {provider}.", "method_unsubscribe": "METHOD-STOP.",
        "method_signup_link": "METHOD-LINK", "seats_include": "SEATS-INCLUDE"})
    pages = _build(tmp_path / "site", monkeypatch, cfg)
    for want in ("SEATS-SENT to Example Mail.", "METHOD-HEADING", "METHOD-SENT to Example Mail.", "METHOD-STOP.",
                 "METHOD-LINK"):
        assert want in pages["method.html"], want
    assert "SEATS-SENT to Example Mail." in pages["index.html"] and "SEATS-INCLUDE" in pages["alerts.html"]


@pytest.mark.parametrize("key, value, why", [
    ("seats_sent", "", "must be set"), ("seats_sent", "They go to the provider.", "must contain {provider}"),
    ("method_sent", "It is sent.", "must contain {provider}"), ("method_heading", " ", "must be set"),
    ("method_unsubscribe", None, "must be set"), ("seats_include", "", "must be set"),
    ("method_signup_link", "", "must be set")])
def test_config_refuses_missing_privacy_text(key, value, why):
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"]["page"][key] = value
    assert any(f"morning_note.page.{key}" in p and why in p for p in morning.problems(cfg)), morning.problems(cfg)


def test_site_checks_accept_the_enabled_form_and_privacy_link_only_while_enabled(enabled_site):
    out, _, cfg = enabled_site
    pages = {f.relative_to(out).as_posix(): site_checks.parse(f) for f in out.rglob("*.html")}
    assert site_checks.check_external(pages, out, cfg) == []
    assert "https://example.net/privacy" in site_checks.allowed_external(cfg, None, None)
    assert [m for m in site_checks.check_links(out, pages, no_export=True) if "alerts.html" in m or "method" in m] == []
    off = site_checks.check_external(pages, out, config.SITE)       # the same pages against the committed config
    assert any("third-party <form>" in p for p in off) and any("CSP form-action" in p for p in off)
    assert "https://example.net/privacy" not in site_checks.allowed_external(config.SITE, None, None)
    other = copy.deepcopy(cfg)                                       # only that exact action, on that one page
    other["morning_note"]["form_action"] = "https://forms.example.net/subscribe/y"
    assert any("third-party <form>" in p for p in site_checks.check_external(pages, out, other))
    moved = {("index.html" if k == "alerts.html" else "x.html" if k == "index.html" else k): v for k, v in pages.items()}
    assert any("third-party <form>" in p for p in site_checks.check_external(moved, None, cfg))


def test_enabled_form_shows_a_visible_seats_box_and_keeps_the_seat_fields_off_without_the_script(enabled_site):
    _, pages, cfg = enabled_site
    note = _note(pages["alerts.html"])
    ff = cfg["morning_note"]["form_fields"]
    nodes = list(parse(note).walk())
    for k in ("district", "ward"):       # without the script the two fields stay disabled and empty: never posted
        inp = next(n for n in nodes if n.attrs.get("name") == ff[k])
        assert inp.attrs["type"] == "hidden" and inp.attrs["value"] == "" and "disabled" in inp.attrs
    box = next(n for n in nodes if n.attrs.get("id") == "note-seats")
    assert box.attrs["type"] == "checkbox" and "checked" in box.attrs
    assert "name" not in box.attrs and "hidden" not in box.attrs      # a real, visible box that is never posted itself
    row = next(n for n in nodes if n.attrs.get("id") == "mn-seats")
    assert "hidden" in row.attrs                                       # shown by the script only when seats are stored
    assert cfg["morning_note"]["page"]["seats_include"] in row.all_text()
    values = next(n for n in nodes if n.attrs.get("id") == "mn-seats-values")
    assert (values.attrs["data-district-label"], values.attrs["data-ward-label"]) == ("District", "Ward")
    assert note.index('id="note-seats"') < note.index('type="submit"')   # before the button


@pytest.mark.skipif(not _node(), reason="node not available")
def test_js_seat_post_sends_nothing_unless_the_box_is_ticked():
    script = (
        "const m = require(process.argv[1]); const L = {district: 'District', ward: 'Ward'}; const out = [];"
        "const seats = [null, {district: 5, ward: 3}, {district: 5, ward: null}, {district: null, ward: 3},"
        " {district: '5', ward: 3.5}, {}];"
        "for (const s of seats) for (const inc of [true, false, undefined, 'yes', 1])"
        " out.push([m.seatPost(s, inc), m.seatWords(s, L)]);"
        "console.log(JSON.stringify(out));")
    r = subprocess.run(["node", "-e", script, str(MORNING_JS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    none = {"district": None, "ward": None}
    want_on = [none, {"district": "5", "ward": "3"}, {"district": "5", "ward": None}, {"district": None, "ward": "3"},
               none, none]
    words = ["", "District 5, Ward 3", "District 5", "Ward 3", "", ""]
    it = iter(got)
    for on, w in zip(want_on, words):
        for inc in (True, False, None, "yes", 1):
            post, said = next(it)
            assert post == (on if inc is True else none), (on, inc, post)   # only a real tick sends anything
            assert said == w


@pytest.mark.parametrize("action", [
    "https://evil.example;script-src *", "https://evil.example; script-src *", "https://user@evil.example/x",
    "https://evil.example *", "http://forms.example.net/x", "https://evil.example\nscript-src *",
    "https://evil.example\u2028x", "//forms.example.net/x", "javascript:alert(1)", ["https://forms.example.net/x"]])
def test_form_origin_checks_the_action_itself(action):
    # morning-security/csp-origin-self-validating: called without morning.problems(), a bad action adds no CSP origin
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"].update({**ENABLED, "form_action": action})
    assert morning_page.form_origin(cfg) is None
    assert "csp" not in morning_page.alerts_context([], cfg)


def test_form_origin_of_a_good_action():
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"].update({**ENABLED, "form_action": "https://forms.example.net:8443/subscribe/x?a=1"})
    assert morning_page.form_origin(cfg) == "https://forms.example.net:8443"


# -- in a browser

def _browser_ok():
    return bool(_node()) and (os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright")))


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def served(site):
    out, _ = site
    handler = functools.partial(_Quiet, directory=str(out))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


BROWSER_JS = r"""
const path = require('path');
let pw; for (const r of [process.env.NODE_PATH, '/opt/node22/lib/node_modules'].filter(Boolean)) { try { pw = require(path.join(r, 'playwright')); break; } catch (e) {} }
const base = process.argv[1];
(async () => {
  const b = await pw.chromium.launch(); const out = {};
  const visible = (p, sel) => p.evaluate(s => [...document.querySelectorAll(s)].filter(e => e.offsetParent !== null || e.getClientRects().length).map(e => e.getAttribute('href') || e.textContent.trim()), sel);
  for (const w of [360, 1280]) {
    const ctx = await b.newContext({ viewport: { width: w, height: 760 } }); const p = await ctx.newPage();
    const errs = [], reqs = []; p.on('pageerror', e => errs.push(String(e))); p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
    p.on('request', r => reqs.push(r.url()));
    const r = {};
    // no seats stored: the hint shows, both body feeds and the all-zoning feed show
    await p.goto(base + 'alerts.html#note');
    r.legend = await p.evaluate(() => { const l = document.querySelector('#note legend'); const b = l.getBoundingClientRect(); return b.width > 0 && b.height > 0 && getComputedStyle(l).visibility === 'visible'; });
    r.noSeats = await visible(p, '#note .mn-lists > li:not([hidden]) li:not([hidden]) > a');
    r.lists0 = await p.evaluate(() => [...document.querySelectorAll('#note .mn-lists > li')].filter(l => !l.hidden).map(l => l.dataset.list));
    r.hint = await p.evaluate(() => [...document.querySelectorAll('#note [data-hint]')].filter(h => !h.hidden).length);
    // keyboard: focus the first pill and toggle it with Space
    await p.focus('#n-zoning'); r.focusRing = await p.evaluate(() => getComputedStyle(document.querySelector('#n-zoning + span')).outlineStyle);
    await p.keyboard.press('Space'); r.afterSpace = await p.evaluate(() => [document.getElementById('n-zoning').checked, document.querySelector('li[data-list=zoning]').hidden]);
    await p.keyboard.press('Tab'); r.tabTo = await p.evaluate(() => document.activeElement.id);
    await p.keyboard.press('Tab'); await p.keyboard.press('Space');
    r.preview = await p.evaluate(() => document.getElementById('mn-preview').getAttribute('href'));
    r.sw1 = await p.evaluate(() => document.documentElement.scrollWidth);
    // seats stored (as seats.js keeps them): the per-seat feeds replace the all-zoning one, the council feed hides
    await p.evaluate(() => localStorage.setItem('cr-your-seats', JSON.stringify({ district: 7, ward: null })));
    await p.goto(base + 'alerts.html'); await p.reload(); await p.check('#n-zoning');
    r.withSeats = await visible(p, '#note .mn-lists > li:not([hidden]) li:not([hidden]) > a');
    // preview page, filtered by the fragment and the stored seat
    await p.goto(base + 'morning/index.html#lists=zoning');
    r.pz = await visible(p, '.mn-entry .mn-title');
    r.unplaced = await p.evaluate(() => !document.querySelector('[data-unplaced]').hidden);
    await p.goto(base + 'morning/index.html#lists=contracts'); r.pc = await visible(p, '.mn-entry .mn-title');
    await p.uncheck('#n-contracts'); r.quiet = await p.evaluate(() => [!document.querySelector('.mn-quiet').hidden, location.hash]);
    await p.goto(base + 'morning/index.html'); r.pall = (await visible(p, '.mn-entry .mn-title')).length;
    r.sw2 = await p.evaluate(() => document.documentElement.scrollWidth); r.iw = w;
    r.errs = errs; r.foreign = reqs.filter(u => !u.startsWith(base)); out[w] = r; await ctx.close();
  }
  const ctx = await b.newContext({ viewport: { width: 360, height: 760 }, javaScriptEnabled: false }); const p = await ctx.newPage();
  await p.goto(base + 'morning/index.html');
  out.nojs = [(await visible(p, '.mn-entry .mn-title')).length, await p.evaluate(() => getComputedStyle(document.querySelector('.mn-picker')).display), await p.evaluate(() => document.documentElement.scrollWidth)];
  await p.goto(base + 'alerts.html');
  out.nojsAlerts = [(await visible(p, '#note .mn-lists > li')).length, await p.evaluate(() => document.documentElement.scrollWidth)];
  console.log(JSON.stringify(out)); await b.close();
})();
"""


CONSENT_JS = r"""
const path = require('path');
let pw; for (const r of [process.env.NODE_PATH, '/opt/node22/lib/node_modules'].filter(Boolean)) { try { pw = require(path.join(r, 'playwright')); break; } catch (e) {} }
const base = process.argv[1];
(async () => {
  const b = await pw.chromium.launch(); const out = {};
  // what a submit would post: the form's own entry list (names and values), as the browser builds it
  const state = p => p.evaluate(() => {
    const f = document.getElementById('note');
    return { posted: [...new FormData(f).entries()].map(e => [e[0], String(e[1])]),
             row: !document.getElementById('mn-seats').hidden && document.getElementById('mn-seats').getClientRects().length > 0,
             words: document.getElementById('mn-seats-values').textContent,
             label: document.querySelector('#mn-seats label').textContent.replace(/\s+/g, ' ').trim(),
             fields: [...f.querySelectorAll('input[data-seat-field]')].map(i => [i.name, i.value, i.disabled]),
             ticked: document.getElementById('note-seats').checked };
  });
  const ctx = await b.newContext({ viewport: { width: 360, height: 760 } }); const p = await ctx.newPage();
  const reqs = []; p.on('request', r => reqs.push(r.url()));
  await p.goto(base + 'alerts.html#note');
  out.noSeats = await state(p);                               // nothing stored: no row, nothing seat-related
  await p.evaluate(() => localStorage.setItem('cr-your-seats', JSON.stringify({ district: 5, ward: 3 })));
  await p.reload();
  out.both = await state(p);                                  // stored: the row shows the numbers, ticked
  out.box = await p.evaluate(() => { const r = document.getElementById('note-seats').getBoundingClientRect(); return [r.width, r.height]; });
  await p.focus('#note-seats'); await p.keyboard.press('Space');
  out.unticked = await state(p);                              // unticked by keyboard: nothing seat-related
  await p.uncheck('#n-zoning');                               // another change must not bring the seats back
  out.stillOff = await state(p);
  await p.click('#mn-seats label');
  out.reticked = await state(p);
  await p.evaluate(() => localStorage.setItem('cr-your-seats', JSON.stringify({ district: 7, ward: null })));
  await p.reload();
  out.districtOnly = await state(p);
  out.sw = await p.evaluate(() => document.documentElement.scrollWidth);
  out.foreign = reqs.filter(u => !u.startsWith(base));
  await ctx.close();
  const c2 = await b.newContext({ viewport: { width: 360, height: 760 }, javaScriptEnabled: false }); const q = await c2.newPage();
  await q.goto(base + 'alerts.html');
  await q.addInitScript(() => {});
  out.nojs = await q.evaluate(() => ({ row: document.getElementById('mn-seats').getClientRects().length > 0,
    fields: [...document.querySelectorAll('input[data-seat-field]')].map(i => [i.name, i.value, i.disabled]) })).catch(e => String(e));
  console.log(JSON.stringify(out)); await b.close();
})();
"""


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_seat_consent_in_a_browser(enabled_site):
    out_dir, _, cfg = enabled_site
    handler = functools.partial(_Quiet, directory=str(out_dir))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    try:
        r = subprocess.run(["node", "-e", CONSENT_JS, f"http://127.0.0.1:{srv.server_address[1]}/"],
                           capture_output=True, text=True, timeout=300, env=env)
    finally:
        srv.shutdown()
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    ff = cfg["morning_note"]["form_fields"]
    seat_names = {ff["district"], ff["ward"]}

    def seat_posts(x):
        return sorted(e for e in x["posted"] if e[0] in seat_names or e[0] not in (ff["email"], ff["lists"]))

    off = [[ff["district"], "", True], [ff["ward"], "", True]]
    assert out["noSeats"]["row"] is False and seat_posts(out["noSeats"]) == [] and out["noSeats"]["fields"] == off
    both = out["both"]
    assert both["row"] is True and both["ticked"] is True and both["words"] == "District 5, Ward 3"
    assert both["label"] == f"{cfg['morning_note']['page']['seats_include']} District 5, Ward 3"
    assert seat_posts(both) == sorted([[ff["district"], "5"], [ff["ward"], "3"]])
    assert out["box"][0] >= 16 and out["box"][1] >= 16                     # a visible box, not a hidden one
    for k in ("unticked", "stillOff"):                                     # unticked: nothing seat-related is posted
        assert out[k]["ticked"] is False and seat_posts(out[k]) == [] and out[k]["fields"] == off, (k, out[k])
        assert out[k]["row"] is True and out[k]["words"] == "District 5, Ward 3"   # still shown, so it can be re-ticked
    assert seat_posts(out["reticked"]) == sorted([[ff["district"], "5"], [ff["ward"], "3"]])
    d = out["districtOnly"]
    assert d["words"] == "District 7" and seat_posts(d) == [[ff["district"], "7"]]
    assert d["fields"] == [[ff["district"], "7", False], [ff["ward"], "", True]]
    assert out["sw"] <= 360 and not out["foreign"]
    assert out["nojs"] == {"row": False, "fields": off}                    # no script: never enabled, never posted


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_note_and_preview_in_a_browser(served):
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    r = subprocess.run(["node", "-e", BROWSER_JS, served], capture_output=True, text=True, timeout=300, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    titles = {e["id"].split("/")[2]: e["title"] for e in DAY["entries"]}
    for w in ("360", "1280"):
        x = out[w]
        assert x["legend"], (w, x)
        assert x["lists0"] == ["zoning", "seats"], (w, x)                       # the two default picks
        assert x["noSeats"] == ["feeds/topic-rezoning.xml", "feeds/county-meetings.xml"], (w, x)
        assert x["hint"] == 2, (w, x)
        assert x["focusRing"] == "solid", (w, x)
        assert x["afterSpace"] == [False, True], (w, x)                         # Space unpicks, the list hides
        assert x["tabTo"] == "n-seats", (w, x)
        assert x["preview"] == "morning/index.html#lists=seats,budget", (w, x)   # Space on Budget picked it
        assert "feeds/zoning-district-07.xml" in x["withSeats"], (w, x)
        assert "feeds/topic-rezoning.xml" not in x["withSeats"], (w, x)
        assert "feeds/zoning-ward-06.xml" not in x["withSeats"], (w, x)
        assert x["pz"] == [titles["Z-1-2024"], titles["CZ-5-2024"]], (w, x)
        assert x["unplaced"], (w, x)
        assert x["pc"] == [titles["rfp-1"]], (w, x)
        assert x["quiet"] == [True, "#lists="], (w, x)
        assert x["pall"] == 5, (w, x)          # all lists, district 7 stored: no ward-only or council entries
        assert x["sw1"] <= x["iw"] and x["sw2"] <= x["iw"], (w, x)              # no sideways scroll
        assert not x["errs"], (w, x)
        assert not x["foreign"], (w, x)                                         # nothing leaves the site
    assert out["nojs"] == [len(DAY["entries"]), "none", 360]
    assert out["nojsAlerts"] == [len(LISTS), 360]
