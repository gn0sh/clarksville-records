"""Landing map, nav drawer, seat labels, seat pages, search and footer (docs/design/landing-search-nav.md).
The session `pages` fixture is built with the fixture roster (site/fixtures/seats.sample.yml) and map
(site/fixtures/districts.sample.json); `build_pages` builds without either."""
import copy
import json
import re
from pathlib import Path

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT, parse
from sitegen import build as sitegen_build, config, views
from sitegen.seats import load_rows
from test_site_neutrality import skeleton
from test_site_review_fixes import build_pages


def text(html):
    return " ".join(parse(html).all_text().split())


def main_text(html):
    return " ".join(next(n for n in parse(html).walk() if n.tag == "main").all_text().split())


def load_index(path):
    js = Path(path).read_text(encoding="utf-8")
    assert js.startswith("window.SEARCH_INDEX = ") and js.rstrip().endswith(";")
    return json.loads(js[len("window.SEARCH_INDEX = "):].rstrip().rstrip(";"))


# ---- 1. Nav drawer -----------------------------------------------------------------------------------------------

def test_menu_is_a_link_to_the_footer_list_without_js_and_the_dialog_is_built_by_nav_js(pages):
    for name, html in pages.items():
        tree = parse(html)
        menu = next(n for n in tree.walk() if n.attrs.get("id") == "nav-open")
        assert menu.tag == "a" and menu.attrs["href"] == "#site-nav", name
        assert "Menu" in menu.all_text()
        nav = next(n for n in tree.walk() if n.attrs.get("id") == "site-nav")
        assert nav.tag == "nav" and nav.attrs["aria-label"] == "All pages", name
        assert "<dialog" not in html and 'class="nav-wide"' not in html and 'class="nav-narrow"' not in html, name
        assert re.search(r'<script src="(\.\./)*static/nav\.js" defer>', html), name
    js = (ROOT / "site" / "static" / "nav.js").read_text(encoding="utf-8")
    for needle in ("showModal()", 'aria-expanded', 'aria-haspopup', 'aria-controls', '"site-nav-drawer"',
                   'aria-labelledby', "autofocus", "btn.focus()", "e.target === dlg", "cloneNode(true)"):
        assert needle in js, needle
    assert not re.search(r"fetch\(|XMLHttpRequest|https?://", js)


def test_current_page_is_marked_in_the_nav(pages):
    for name, label in (("officials.html", "Officials"), ("index.html", "Map (home)"), ("search.html", "Search"),
                        ("finance.html", "Finance")):
        nav = next(n for n in parse(pages[name]).walk() if n.attrs.get("id") == "site-nav")
        current = [a for a in nav.walk() if a.tag == "a" and a.attrs.get("aria-current") == "page"]
        assert len(current) == 1 and current[0].all_text().strip().startswith(label), name


def test_coming_pages_have_no_numbers_and_are_marked_coming_in_the_nav(pages):
    for slug in ("finance", "capital-projects"):
        body = main_text(pages[f"{slug}.html"])
        assert "Coming" in body
        assert not re.search(r"\d", body), (slug, body)
        assert not re.search(r"<(table|svg|canvas)", pages[f"{slug}.html"].split("<main", 1)[1].split("</main>")[0])
    nav = pages["about.html"][pages["about.html"].index('<nav id="site-nav"'):]
    assert re.search(r'finance\.html">Finance <span class="chip chip-coming">Coming</span>', nav)
    assert re.search(r'capital-projects\.html">Capital projects <span class="chip chip-coming">Coming</span>', nav)


# ---- 2. Landing ---------------------------------------------------------------------------------------------------

def test_landing_is_one_screen_of_purpose_search_map_and_district_list(pages):
    html = pages["index.html"]
    body = main_text(html)
    assert body.startswith(config.SITE["purpose"])
    assert re.search(r'<form class="landing-search" action="search\.html" method="get"', html)
    assert 'name="q"' in html and "Map shows" in body
    # the old home content moved away
    for gone in ('class="card"', 'class="glance"', 'class="timeline meetings"'):
        assert gone not in html, gone
    assert 'class="card"' in pages["officials.html"]
    assert 'class="timeline meetings"' in pages["meetings.html"]
    assert 'id="the-record"' in pages["about.html"] and 'class="glance"' in pages["about.html"]


def test_map_paths_are_identical_links_hidden_from_assistive_tech(pages):
    tree = parse(pages["index.html"])
    svg = next(n for n in tree.walk() if n.tag == "svg")
    assert svg.attrs["aria-hidden"] == "true" and svg.attrs["focusable"] == "false"
    links = [n for n in svg.walk() if n.tag == "a"]
    assert [a.attrs["href"] for a in links] == ["districts/01.html", "districts/02.html", "districts/03.html"]
    assert all(a.attrs["tabindex"] == "-1" for a in links)
    paths = [n for n in svg.walk() if n.tag == "path" and "district" in n.attrs.get("class", "")]
    assert len(paths) == 3
    assert {p.attrs["class"] for p in paths} == {"district"}  # one value for all: the fill encodes nothing
    assert not any("fill" in p.attrs or "style" in p.attrs for p in paths)
    assert "The same districts are listed after the map." in text(pages["index.html"])
    assert 'data-ext="map" href="https://example.org/fixture/districts.pdf"' in pages["index.html"]


def test_district_list_rows_follow_the_roster_and_never_guess(pages):
    nav = next(n for n in parse(pages["index.html"]).walk() if n.attrs.get("aria-label") == "County commission districts")
    rows = [" ".join(li.all_text().split()) for li in nav.walk() if li.tag == "li"]
    assert len(rows) == config.SITE["district_count"]
    assert rows[:4] == ["District 1 A. Example", "District 2 D. Testperson", "District 3 Seat vacant",
                        "District 4 Current member not yet recorded"]
    assert all(r.endswith("Current member not yet recorded") for r in rows[3:])


def test_landing_without_map_or_roster_shows_the_list_and_the_placeholder(tmp_path, facts):
    pages = build_pages(tmp_path, facts)
    html = pages["index.html"]
    assert "<svg" not in html and "The map is not available yet. Districts are listed by number." in html
    assert re.search(r'<details class="district-list" open', html)
    nav = next(n for n in parse(html).walk() if n.attrs.get("aria-label") == "County commission districts")
    rows = [" ".join(li.all_text().split()) for li in nav.walk() if li.tag == "li"]
    assert rows == [f"District {n}" for n in range(1, config.SITE["district_count"] + 1)]
    assert "map.js" not in html


def test_fixture_facts_never_read_the_real_roster_or_map(tmp_path, facts):
    pages = build_pages(tmp_path, facts)
    assert 'class="seat"' not in "".join(pages.values())


# ---- 3. Seat labels and seat pages ----------------------------------------------------------------------------------

def test_seat_label_follows_the_name_on_meeting_pages_by_that_meetings_date(pages, facts):
    ix = views.Index(facts, load_rows(FIXTURE_SEATS))
    for m in facts["meetings"]:
        html = pages[f"meetings/{m['id']}.html"]
        for o in facts["officials"]:
            # the seat on that date, or the fixed words when no record covers it (manager decision; never guessed)
            want = ix.seats.on(o["id"], m["date"]) or "seat not recorded"
            link = f'officials/{o["id"]}.html">{o["name"]}</a>'
            if link not in html:
                continue
            assert f'{link}<span class="seat">, {want}</span>' in html, (m["id"], o["id"])
    # b-sample seen in District 2 on 2024-11-04 only, d-testperson from 2024-12-09: by date, never guessed
    assert ix.seats.on("b-sample", "2024-11-04") == "District 2"
    assert ix.seats.on("b-sample", "2024-12-09") is None
    assert ix.seats.on("d-testperson", "2024-11-04") is None
    assert ix.seats.on("d-testperson", "2024-12-09") == "District 2"
    assert ix.seats.on("a-example", "2021-01-01") is None
    assert ix.seats.on("e-fixture", "2024-12-09") is None


def test_official_page_header_carries_the_seat(pages):
    assert ("District 1, seen in roll calls from 2024-11-04 to 2024-12-09, the latest meeting collected"
            in text(pages["officials/a-example.html"]))
    assert "District 2, seen in roll calls 2024-11-04 to 2024-11-04" in text(pages["officials/b-sample.html"])
    assert "Seat not yet recorded" in text(pages["officials/e-fixture.html"])


def test_old_lines_label_before_the_2022_lines():
    from sitegen.seats import Seats
    base = {"official_id": "x", "seat": "district-2", "dates": "observed", "source": "https://e/a#page=1",
            "last_source": "https://e/b#page=2", "printed": None, "note": None, "name": None}
    s = Seats([{**base, "start": "2020-03-09", "end": "2022-08-08", "lines": "old"},
               {**base, "start": "2022-09-12", "end": None, "lines": "current"}], {"x": {}}, "2024-12-09")
    assert s.on("x", "2021-05-01") == "District 2 (old lines)"
    assert s.on("x", "2023-05-01") == "District 2"
    assert s.on("x", "2022-08-20") is None   # between the two runs: no record covers it


def test_district_pages_exist_for_every_seat_with_one_skeleton(pages):
    names = sorted(p for p in pages if p.startswith("districts/"))
    assert names == [f"districts/{n:02d}.html" for n in range(1, config.SITE["district_count"] + 1)]
    # two seats with no records render the same skeleton (N1); every seat page has the same h2 headings
    assert skeleton(pages["districts/04.html"]) == skeleton(pages["districts/05.html"])
    h2 = {n: [x.all_text().strip() for x in parse(pages[n]).walk() if x.tag == "h2" and x.attrs.get("id")]
          for n in names}
    assert len({tuple(v) for v in h2.values()}) == 1
    assert h2["districts/01.html"] == ["Current", "Served previously",
                                       "Current district lines: roll calls from 2024-11-04", "Old district lines"]


def test_district_page_current_previous_and_periods(pages):
    t = text(pages["districts/02.html"])
    assert "District 2 covered a different area before the change." in t
    assert "redrawn" not in t and config.SITE["lines_effective"] not in t
    assert ("Current D. Testperson District 2, seen in roll calls from 2024-12-09 to 2024-12-09, the latest meeting "
            "collected.") in t
    prev = next(n for n in parse(pages["districts/02.html"]).walk() if n.tag == "table")
    assert ("B. Sample seen in roll calls 2024-11-04 to 2024-11-04 Current district lines Source: first, p. 1 (opens in a new tab); "
            "last, p. 2 (opens in a new tab)") in " ".join(prev.all_text().split())
    # each block names its own first and last roll-call meetings, never a clip date
    assert "B. Sample, District 2: roll calls 2024-11-04 to 2024-11-04" in t
    assert "D. Testperson, District 2: roll calls 2024-12-09 to 2024-12-09" in t
    assert re.search(r"Roll call votes, 2024-12-09 to 2024-12-09: \d+ Yes", t)
    t3 = text(pages["districts/03.html"])
    assert "Seat vacant, shown as vacant in roll calls from 2024-11-04 to 2024-12-09" in t3
    assert "No votes are recorded for District 3 in the minutes collected so far." in t3
    assert "No earlier holders are recorded for this seat." in t3
    t4 = text(pages["districts/04.html"])
    assert "Current member not yet recorded" in t4
    assert "The map of the old district lines has not been found yet." in t4


def test_district_scoped_totals_never_mix_confirmed_and_unconfirmed(pages, facts):
    ix = views.Index(facts, load_rows(FIXTURE_SEATS))
    whole = views.official_counts(ix, "d-testperson")
    part = views.official_counts(ix, "d-testperson", "2024-11-01", None)
    early = views.official_counts(ix, "d-testperson", None, "2024-10-31")
    for k in ("yes", "no", "abstain", "other", "rc_voted", "rc_voted_nc", "yes_nc"):
        assert part[k] + early[k] == whole[k], k


def test_swapped_district_line_on_19_and_20_only(pages):
    for n in range(1, config.SITE["district_count"] + 1):
        has = ("The map PDF prints Districts 19 and 20 the other way round; this site uses the numbers printed in the "
               "roll-call tables" in pages[f"districts/{n:02d}.html"])
        assert has == (n in (19, 20)), n


def test_officials_card_seat_text_does_not_repeat_the_same_seat():
    from sitegen.seats import Seats
    base = {"official_id": "x", "dates": "observed", "source": "https://e/x", "last_source": "https://e/y",
            "printed": None, "note": None, "name": None}
    rows = [{**base, "seat": "district-1", "start": "2020-01-01", "end": "2022-08-08"},
            {**base, "seat": "district-1", "start": "2022-09-12", "end": None},
            {**base, "seat": "district-9", "start": "2018-01-01", "end": "2019-12-31"}]
    s = Seats(rows, {"x": {}}, "2024-12-09")
    assert s.seat_text("x") == "District 1; District 9 (seen in roll calls 2018-01-01 to 2019-12-31)"


def test_seats_rows_need_an_https_source(tmp_path):
    bad = tmp_path / "seats.yml"
    bad.write_text("- {official_id: a-example, seat: district-1, start: '2022-09-01', end: null, source: ''}\n")
    with pytest.raises(sitegen_build.BuildError, match="source"):
        sitegen_build.build(FIXTURE, tmp_path / "site", seats_path=bad)


# ---- 4. Search -----------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def index(built):
    return load_index(built / "static" / "search-index.js")


def test_unconfirmed_roll_calls_carry_no_vote_or_outcome_in_the_index(index, facts):
    status = {r["id"]: r["verification"]["status"] for r in facts["roll_calls"]}
    rcs = [r for r in index["records"] if r["k"] == "vote"]
    assert len(rcs) == len(facts["roll_calls"])
    assert any(not r["c"] for r in rcs) and any(r["c"] for r in rcs)
    for r in rcs:
        assert r["c"] == (status[r["id"]] == "verified")
        if not r["c"]:
            assert r["o"] is None and r["v"] is None and r["s"] is None, r
        else:
            assert r["o"] in ("passed", "failed", "other") and r["v"] and r["s"]["u"].startswith("https://")


def test_vote_filter_simulation_never_matches_an_unconfirmed_roll_call(index):
    """search.js matches a vote filter only on r.v[official] == value; unconfirmed records have v null."""
    for r in index["records"]:
        if r["k"] == "vote" and not r["c"]:
            for oid in index["names"]:
                for value in ("yes", "no", "abstain", "other"):
                    assert not (r["v"] and r["v"].get(oid) == value)


def test_official_filter_is_alphabetical_by_surname_with_no_counts(index, facts):
    want = [o["id"] for o in sorted(facts["officials"], key=views.name_key)]
    assert [o["id"] for o in index["officials"]] == want
    labels = {o["id"]: o["label"] for o in index["officials"]}
    assert labels["a-example"] == "Example, A. (District 1)"
    # served previously: the former seat with its roll-call dates (design 6A.2)
    assert labels["b-sample"] == "Sample, B. (District 2 (seen in roll calls 2024-11-04 to 2024-11-04))"
    assert labels["e-fixture"] == "Fixture, E."   # no record: no seat, never guessed
    for label in labels.values():   # no counts: any digit is inside the seat part
        assert not re.search(r"\d", re.sub(r" \(.*\)$", "", label)), label


def test_search_page_controls_and_no_js_state(pages):
    html = pages["search.html"]
    for ctl in ('name="q"', 'name="kind"', 'name="from"', 'name="to"', 'name="type"', 'name="official"',
                'name="vote"', 'name="outcome"', 'name="order"', 'id="copy"', 'id="clear"', 'aria-live="polite"',
                'aria-describedby="vote-hint"'):
        assert ctl in html, ctl
    assert "<noscript>" in html and "Search needs JavaScript. Browse instead:" in html
    assert re.search(r'<script src="static/search-index\.js" defer></script>\s*<script src="static/search\.js" defer>', html)
    js = (ROOT / "site" / "static" / "search.js").read_text(encoding="utf-8")
    assert "history.replaceState" in js and "Filtering by official, vote or outcome uses confirmed roll calls only." in js
    assert not re.search(r"fetch\(|XMLHttpRequest|localStorage|document\.cookie", js)


def test_item_type_rule_is_mechanical_and_on_the_about_page(pages):
    assert views.item_types({"number": "CZ-18-2020", "title": "x"}) == ["rezoning"]
    assert views.item_types({"number": "24-7-4", "title": "Resolution making appropriations"}) == ["budget", "resolution"]
    assert views.item_types({"number": "", "title": "Minutes"}) == ["other"]
    about = text(pages["about.html"])
    assert "How item types are decided" in about and "CZ-" in about


def test_landing_district_lookup_line_is_a_plain_config_link_and_vanishes_when_empty(pages, monkeypatch, tmp_path):
    url = config.SITE["district_lookup_url"]
    assert url == "https://web.go-vote-tn.elections.tn.gov/"
    html = pages["index.html"]
    assert f'<a data-ext="lookup" href="{url}" rel="noopener">Look it up on GoVoteTN</a>' in html
    assert "Not sure of your district? Look it up on GoVoteTN." in main_text(html)
    assert url not in "".join(h for k, h in pages.items() if k != "index.html")
    assert sitegen_build.site_url_problems({**config.SITE, "district_lookup_url": "http://x.example"})
    assert config.SITE["district_lookup_label"] == "GoVoteTN"
    monkeypatch.setitem(config.SITE, "district_lookup_label", "the state lookup")
    (tmp_path / "relabel").mkdir()
    relabelled = build_pages(tmp_path / "relabel", json.loads(FIXTURE.read_text(encoding="utf-8")))["index.html"]
    assert f'<a data-ext="lookup" href="{url}" rel="noopener">Look it up on the state lookup</a>' in relabelled
    empty = {**config.SITE, "district_lookup_url": ""}
    monkeypatch.setattr(config, "SITE", empty)
    assert "district-lookup" not in build_pages(tmp_path, json.loads(FIXTURE.read_text(encoding="utf-8")))["index.html"]


# ---- 5. Footer -----------------------------------------------------------------------------------------------------

def test_footer_has_no_support_link_while_switched_off(tmp_path, facts, monkeypatch):
    monkeypatch.setitem(config.SITE, "support_enabled", False)
    pages = build_pages(tmp_path, facts)
    for name, html in pages.items():
        assert 'data-ext="support"' not in html and "buymeacoffee" not in html, name


def test_support_link_is_on_in_config():
    # Brian 2026-11-09: council seat not a factor; the footer support link is on.
    assert config.SITE["support_enabled"] is True


def test_footer_support_link_renders_when_switched_on(tmp_path, facts, monkeypatch):
    monkeypatch.setitem(config.SITE, "support_enabled", True)
    pages = build_pages(tmp_path, facts)
    for name, html in pages.items():
        assert re.search(r'Provided as a free service by <a data-ext="operator" href="https://gnoshcodes\.com/" rel="noopener noreferrer">gnoshcodes</a>\. '
                         r'<a data-ext="support" '
                         r'href="https://buymeacoffee\.com/gnoshcodes" rel="noopener noreferrer">Buy Me a Coffee</a>',
                         html), name
    monkeypatch.setitem(config.SITE, "support_url", "")
    (tmp_path / "b").mkdir()
    pages = build_pages(tmp_path / "b", facts)
    assert not any('data-ext="support"' in h for h in pages.values())


# ---- 6. Locality text lives in config ------------------------------------------------------------------------------

@pytest.mark.parametrize("path", sorted((ROOT / "site" / "templates").glob("*.j2")) +
                         sorted((ROOT / "site" / "static").glob("*.js")), ids=lambda p: p.name)
def test_no_locality_names_in_templates_or_scripts(path):
    assert not re.search(r"Montgomery|Clarksville|Tennessee|\bTN\b", path.read_text(encoding="utf-8")), path.name


def test_a_county_item_with_no_title_gets_a_fallback_title():
    ix = views.Index.__new__(views.Index)
    assert ix.item_title({"number": "24-7-4", "title": ""}) == "Untitled item 24-7-4"
    assert ix.item_title({"number": None, "title": ""}) == "Untitled item"
    assert ix.item_title({"number": "24-7-4", "title": None}) == "Untitled item 24-7-4"
    assert ix.item_title({"number": "24-7-4", "title": "Real title"}) == "Real title"


def test_item_types_match_word_starts_only():
    assert "appointment" in views.item_types({"number": "", "title": "Appointment of a member"})
    assert views.item_types({"number": "", "title": "On disappointment"}) == ["other"]
