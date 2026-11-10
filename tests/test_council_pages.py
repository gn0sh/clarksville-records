"""M4 slice 2: City Council pages beside the county (sitegen/council.py, config/localities/<loc>/council.yml).

The council fixture is a small, real subset of the city facts file (a few meetings, one with a held roll call, one
with an agenda only), marked FIXTURE so it builds beside the county fixture."""
import json
import re

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT, parse
from qa import site_checks
from sitegen import config, council, views
from sitegen.build import BuildError, build

CITY = ROOT / "data" / "localities" / "clarksville-tn"
MEETINGS = ("2016-01-04-executive", "2018-05-30-special", "2018-06-07-special", "2019-01-03-regular",
            "2022-02-15-special")
CFG = config.load_council("clarksville-tn")


def subset(facts: dict, meeting_ids) -> dict:
    keep = set(meeting_ids)
    meetings = [m for m in facts["meetings"] if m["id"] in keep]
    rcs = [r for r in facts["roll_calls"] if r["meeting_id"] in keep]
    mos = [m for m in facts["motions"] if m["meeting_id"] in keep]
    evs = [e for e in facts["item_events"] if e["meeting_id"] in keep]
    item_ids = {x["item_id"] for x in rcs + mos + evs}
    items = [i for i in facts["items"] if i["id"] in item_ids]
    src = {m["source_id"] for m in meetings} | {m.get("agenda_source_id") for m in meetings}
    src |= {x["source_id"] for x in rcs + mos + evs}
    src |= {f["source_id"] for i in items for f in (i.get("zoning") or {}).values() if f}
    return {**facts, "fixture": True, "meetings": meetings, "roll_calls": rcs, "motions": mos, "item_events": evs,
            "items": items, "sources": [s for s in facts["sources"] if s["id"] in src], "corrections": []}


@pytest.fixture(scope="module")
def city_facts():
    return subset(json.loads((CITY / "facts.json").read_text(encoding="utf-8")), MEETINGS)


@pytest.fixture(scope="module")
def city_wards():
    return [w for w in json.loads((CITY / "wards.json").read_text(encoding="utf-8")) if w["meeting_id"] in MEETINGS]


@pytest.fixture(scope="module")
def cfg(tmp_path_factory, city_facts, city_wards):
    d = tmp_path_factory.mktemp("city")
    (d / "facts.json").write_text(json.dumps(city_facts), encoding="utf-8")
    (d / "wards.json").write_text(json.dumps(city_wards), encoding="utf-8")
    return {**CFG, "facts_path": d / "facts.json", "wards_path": d / "wards.json"}


@pytest.fixture(scope="module")
def site(tmp_path_factory, cfg):
    out = tmp_path_factory.mktemp("site") / "build" / "site"
    result = build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, councils=[cfg])
    return out, result


@pytest.fixture(scope="module")
def cpages(site):
    out, _ = site
    return {p.relative_to(out).as_posix(): p.read_text(encoding="utf-8") for p in out.rglob("*.html")}


@pytest.fixture(scope="module")
def cix(cfg, city_facts, city_wards):
    return council.load(cfg, city_facts, city_wards)


# ---------------------------------------------------------------- holder records

def _w(date, oid, ward, n=0):
    return {"date": date, "meeting_id": f"{date}-regular", "official_id": oid, "page": 1, "pro_tem": False,
            "raw_name": oid, "source_id": "s1", "ward": ward}


FACTS_W = {"sources": [{"id": "s1", "url": "https://example.gov/m.pdf"}],
           "officials": [{"id": i, "title": "Member"} for i in ("a", "b", "c")], "meetings": [], "roll_calls": []}


def test_a_lone_ward_print_is_not_a_record_and_a_return_after_someone_else_is_a_second_record():
    wards = [_w("2020-01-01", "a", 2), _w("2020-02-01", "a", 2),
             _w("2020-03-01", "b", 2), _w("2020-03-01", "c", 3),   # b printed in ward 2 once: a misprint
             _w("2020-04-01", "c", 2), _w("2020-05-01", "c", 2),   # c holds ward 2 between a's two spells
             _w("2020-06-01", "a", 2), _w("2020-07-01", "a", 2),
             _w("2020-08-01", "b", None)]                           # no ward printed: not used
    rows = council.ward_rows(wards, FACTS_W, CFG)
    got = [(r["official_id"], r["seat"], r["start"], r["end"]) for r in rows]
    assert got == [("a", "ward-2", "2020-01-01", "2020-02-01"), ("c", "ward-2", "2020-04-01", "2020-05-01"),
                   ("a", "ward-2", "2020-06-01", "2020-07-01")]
    assert all(r["dates"] == "observed" and r["evidence"] == "attendance lists" for r in rows)
    assert rows[0]["source"] == "https://example.gov/m.pdf#page=1" and rows[0]["last_source"].endswith("#page=1")


def test_records_seen_at_the_latest_print_have_no_end_so_they_are_current():
    wards = [_w("2020-01-01", "a", 1), _w("2020-02-01", "a", 1), _w("2020-01-01", "b", 2), _w("2020-03-01", "b", 2)]
    rows, latest = council.holder_rows(wards, FACTS_W, CFG)
    assert latest == "2020-03-01"
    assert {r["official_id"]: r["end"] for r in rows} == {"a": "2020-02-01", "b": None}


def test_mayor_seat_comes_from_the_confirmed_roll_calls(cix, city_facts):
    mayors = [o["id"] for o in city_facts["officials"] if o["title"] == "Mayor"]
    recs = [r for r in cix.seats.records if r["seat"] == "city-mayor"]
    assert recs and {r["official_id"] for r in recs} <= set(mayors)
    assert all(r["evidence"] == "roll calls" for r in recs)


def test_seat_wording_names_attendance_lists_and_the_latest_minutes_read(cix):
    rec = next(r for r in cix.seats.records if r["seat"].startswith("ward-"))
    text = cix.seats.dates_text(rec)
    assert text.startswith("seen in attendance lists ")
    assert site_checks.dates_worded(text) == []
    cur = next(r for r in cix.seats.records if r["current"])
    assert cix.seats.basis(cur).startswith(f"Current: in the {cur['evidence']} of the latest minutes read, ")


# ---------------------------------------------------------------- where pages live

def test_council_hrefs_are_one_page_per_year_with_unique_anchors(cix, city_facts):
    rc = city_facts["roll_calls"][0]
    m = cix.meetings[rc["meeting_id"]]
    y = m["date"][:4]
    assert cix.meeting_href(m["id"]) == f"city/meetings/{y}.html#{m['id']}"
    assert cix.meeting_href(m["id"], rc["id"]) == f"city/meetings/{y}.html#{rc['id']}"
    assert cix.meeting_href(m["id"], views.ATTENDANCE) == f"city/meetings/{y}.html#{m['id']}-attendance"
    oid = city_facts["officials"][0]["id"]
    assert cix.official_href(oid) == f"city/members/{oid}.html"
    it = city_facts["items"][0]
    assert cix.item_href(it) == f"city/items/{it['year']}.html#{it['id']}"


def test_an_untitled_item_shows_the_fixed_words(cix):
    assert cix.item_title({"title": ""}) == CFG["untitled_item"]
    assert cix.item_title({"title": "CONSENT AGENDA"}) == "CONSENT AGENDA"


def _member_history_pages(out, facts: dict, cix) -> int:
    """Pages of member history: each member's years with a row, consecutive years sharing a page (council.py,
    history_by_year; build.py pack_years). Every year with a row is on exactly one page, named by its years."""
    n = 0
    for o in facts["officials"]:
        years = {y["year"] for y in views.official(o["id"], cix)["year_pages"]}
        pages = sorted(p.stem for p in (out / "city" / "members" / o["id"]).glob("*.html"))
        covered = []
        for name in pages:
            m = re.fullmatch(r"(\d{4})(?:-(\d{4}))?", name)
            assert m, name
            covered += [str(y) for y in range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1)
                        if str(y) in years]
        assert sorted(covered) == sorted(years)                  # each year once, on one page
        n += len(pages)
    return n


def test_page_count_is_one_per_member_and_per_year_never_per_meeting(site, cix, city_facts):
    out, _ = site
    city = sorted(p.relative_to(out).as_posix() for p in (out / "city").rglob("*.html"))
    want = (1 + len(city_facts["officials"]) + len({m["date"][:4] for m in city_facts["meetings"]})
            + len({i["year"] for i in city_facts["items"]}) + _member_history_pages(out, city_facts, cix))
    assert len(city) == want
    assert "city/index.html" in city
    assert not any(re.search(r"meetings/\d{4}-\d{2}-\d{2}", p) for p in city)


def test_real_city_pages_fit_the_file_budget():
    """The real city facts make at most this many pages: one per member and per year of each member's history, per
    year of meetings and of items (more parts when a year is over config.PAGE_BYTES, about 20 more today), plus the
    home. With CivicClerk (2024 on) this upper bound is 205; pack_years puts consecutive years of a member's history
    on one page (about 60 fewer pages), and with the county's pages the built site stays under config.MAX_FILES
    (469 files on 2026-11-09; BuildError and qa/site_checks.py check the built site)."""
    facts = json.loads((CITY / "facts.json").read_text(encoding="utf-8"))
    years = {o["id"]: set() for o in facts["officials"]}
    dates = {m["id"]: m["date"][:4] for m in facts["meetings"]}
    for rc in facts["roll_calls"]:
        for v in rc["votes"]:
            if v["official_id"] in years:
                years[v["official_id"]].add(dates[rc["meeting_id"]])
    for m in facts["meetings"]:
        for a in m["attendance"]:
            if a["official_id"] in years:
                years[a["official_id"]].add(m["date"][:4])
    n = (1 + len(facts["officials"]) + len({m["date"][:4] for m in facts["meetings"]})
         + len({i["year"] for i in facts["items"]}) + sum(len(y) for y in years.values()))
    assert n <= 230


# ---------------------------------------------------------------- the pages

def test_nav_and_landing_carry_the_council(cpages):
    for rel in ("index.html", "officials.html", "city/index.html"):
        nav = parse(cpages[rel])
        hrefs = [n.attrs.get("href", "") for n in nav.walk() if n.tag == "a"]
        assert any(h.endswith("city/index.html") for h in hrefs), rel
    landing = cpages["index.html"]
    assert 'href="city/index.html">' + CFG["nav_label"] + '</a>: ' in landing   # short label: one line at 375 px
    assert CFG["nav_label"] + " seats" in landing
    assert "pages are coming" not in landing and "records are coming" not in landing


def test_member_pages_share_the_county_layout_and_carry_the_ward(cpages, cix, city_facts):
    rels = [f"city/members/{o['id']}.html" for o in city_facts["officials"]]
    skel = {site_checks._skeleton(cpages[r]) for r in rels}
    assert len(skel) == 1
    labelled = [o["id"] for o in city_facts["officials"] if cix.seats.of(o["id"])]
    assert labelled
    for oid in labelled:
        assert re.search(r'class="seat-line"><span class="seat">(Ward \d+|City Mayor)', cpages[f"city/members/{oid}.html"])


def test_held_roll_calls_show_not_confirmed_and_no_value(site, cpages, city_facts):
    out, _ = site
    held = [r for r in city_facts["roll_calls"] if r["verification"]["status"] != "verified"]
    assert held
    city_pages = {rel: site_checks.parse(out / rel) for rel in cpages if rel.startswith("city/")}
    problems = site_checks.check_unverified(out, city_pages, city_facts, internal=False,
                                            official_prefix="city/members/", export=False)
    assert problems == []
    year = {m["id"]: m["date"][:4] for m in city_facts["meetings"]}
    for r in held:
        html = cpages[f"city/meetings/{year[r['meeting_id']]}.html"]
        block = html.split(f'id="{r["id"]}"', 1)[1].split("</article>", 1)[0]
        assert "Not confirmed: this page was hard to read." in block
        assert not site_checks.PARSED_VALUE.search(block)


def test_every_name_links_to_its_member_page_and_every_fact_to_its_source(site, cpages, city_facts):
    out, _ = site
    cs = [{"slug": "city", "prefix": "city/", "facts": city_facts}]
    county = json.loads(FIXTURE.read_text(encoding="utf-8"))
    problems, _ = site_checks.check_name_links(out, county, site_checks.read_roster(FIXTURE_SEATS), cs)
    assert problems == []
    pages = {rel: site_checks.parse(out / rel) for rel in cpages}
    allowed = site_checks.allowed_external(config.SITE, FIXTURE_SEATS, FIXTURE_DISTRICTS)
    problems, _ = site_checks.check_sources(out, pages, {"sources": county["sources"] + city_facts["sources"]},
                                            (), allowed)
    assert problems == []
    assert site_checks.check_links(out, pages, no_export=True) == []


def test_council_attendance_totals_recount_from_the_year_pages(site, cpages, city_facts):
    out, _ = site
    pages = {rel: None for rel in cpages}
    problems, _ = site_checks.check_totals(out, pages, city_facts, "city/meetings/", "city/members")
    assert problems == []


def test_agenda_only_meeting_says_so_and_links_the_agenda(cpages):
    html = cpages["city/meetings/2016.html"]
    sec = html.split('id="2016-01-04-executive"', 1)[1].split("</section>", 1)[0]
    assert "Minutes not collected for this meeting." in sec and "agenda PDF" in sec


def test_council_home_lists_seats_and_current_then_former_members(cpages, cix):
    html = cpages["city/index.html"]
    for n in range(1, config.SITE["ward_count"] + 1):
        assert f'id="seat-ward-{n}"' in html
    assert 'id="seat-city-mayor"' in html
    assert re.search(r'<h3 class="section-h" id="current-h">Current</h3>', html)
    assert "Served previously" in html


def test_search_index_has_council_records_under_their_body(site, city_facts):
    out, _ = site
    raw = (out / "static" / "search-index.js").read_text(encoding="utf-8")
    ix = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    city = [r for r in ix["records"] if r["b"] == "city"]
    assert {r["k"] for r in city} == {"item", "vote", "meeting", "person"}
    assert all(r["h"].startswith("city/") for r in city)
    held = {r["id"] for r in city_facts["roll_calls"] if r["verification"]["status"] != "verified"}
    assert all(r["o"] is None and r["v"] is None for r in city if r["id"] in held)
    assert {"key": "city", "label": CFG["body_name"]} in ix["bodies"]
    oid = city_facts["officials"][0]["id"]
    assert ix["hrefs"][oid] == f"city/members/{oid}.html"


def test_search_page_has_a_body_filter_per_body(cpages):
    html = cpages["search.html"]
    assert 'name="body" value="county"' in html and 'name="body" value="city"' in html
    assert "(coming)" not in html.split("<legend>Body</legend>", 1)[1].split("</fieldset>", 1)[0]


def test_a_real_council_is_never_built_beside_fixture_county_facts(tmp_path, cfg, city_facts):
    real = {**city_facts}
    real.pop("fixture")
    (tmp_path / "facts.json").write_text(json.dumps(real), encoding="utf-8")
    with pytest.raises(BuildError, match="council facts"):
        build(FIXTURE, tmp_path / "site", seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS,
              councils=[{**cfg, "facts_path": tmp_path / "facts.json"}])


def test_a_fixture_build_has_no_council_by_default(pages):
    assert not any(rel.startswith("city/") for rel in pages)


@pytest.mark.parametrize("body", ["x mo-1/moved y", "mo-1/moved/z", "amo-1/moved", "mo-1/movedx", "mo-1/moved-2",
                                  "<td>mo-1/moved</td>", "2016-01-07-regular/att", "a/2016-01-07-regular/att"])
def test_one_scan_id_match_agrees_with_contains(body):
    """qa/site_checks.py scans each file once for id tokens (id_prefixes); it must match _contains exactly."""
    for tok in ("mo-1/moved", "2016-01-07-regular/att", "mo-1"):
        assert (tok in site_checks.id_prefixes(body)) == site_checks._contains(body, tok, "held motion attribution")


def test_a_lone_misprint_does_not_cut_the_members_own_run():
    """Ward 4, Ward 3 once, Ward 4 again at the latest meeting: one Ward 4 record to the end (the Ward 3 print is
    dropped first, so the last Ward 4 print joins the run instead of being judged alone)."""
    wards = [_w("2020-01-01", "a", 4), _w("2020-02-01", "a", 4), _w("2020-03-01", "a", 3), _w("2020-04-01", "a", 4)]
    rows, _ = council.holder_rows(wards, FACTS_W, CFG)
    assert [(r["seat"], r["start"], r["end"]) for r in rows] == [("ward-4", "2020-01-01", None)]


# ---------------------------------------------------------------- review fixes (docs/reviews/code-review-city-pages.md)

def test_each_council_list_on_the_landing_has_its_own_basis_line(cpages, cix):
    """city-pages/current-basis: the council's seats are not under the county's "Current" line; they carry the
    council's own, dated at the council's latest minutes read."""
    landing = cpages["index.html"]
    county = re.search(r'<details class="district-list".*?<p class="basis muted">(.*?)</p>', landing, re.S).group(1)
    council_part = landing[landing.index('<h2 class="list-h">'):]
    own = re.search(r'<p class="basis muted">(.*?)</p>\s*<nav aria-label="' + CFG["nav_label"] + ' seats">',
                    council_part, re.S).group(1)
    assert own != county
    # the fixture's latest list (a special session) names fewer members than the one before, so the line goes on to
    # name the seats whose member it does not name (city-seats, one-list drop)
    assert f"{CFG['latest_words']}, {cix.seats.latest}" in own and own.endswith(".")
    assert views.observed_basis(cix) + "." == own


def test_the_basis_names_each_kind_of_evidence_with_its_seats(cix):
    """city-pages/current-basis (low): wards come from the attendance lists, the mayor from the roll calls; one line
    names both, so the mayor is never described as seen in the attendance lists."""
    def rec(seat, label, ev):
        return {"seat": seat, "label": label, "evidence": ev, "current": True, "dates": "observed"}
    ward, mayor = CFG["evidence"]["ward"], CFG["evidence"]["title"]
    both = views.observed_basis(cix, [rec("ward-2", "Ward 2", ward), rec("ward-1", "Ward 1", ward),
                                      rec("city-mayor", "City Mayor", mayor)])
    assert both == (f"Current: in the {ward} (wards) and the {mayor} (City Mayor) of {CFG['latest_words']}, "
                    f"{cix.seats.latest}")
    one = views.observed_basis(cix, [rec("ward-1", "Ward 1", ward)])
    assert one == f"Current: in the {ward} of {CFG['latest_words']}, {cix.seats.latest}"


def test_the_council_home_basis_matches_its_seats(cpages, cix):
    html = cpages["city/index.html"]
    seats_sec = html[html.index('id="seats-h"'):html.index('id="meetings-h"')]
    line = re.search(r'<p class="basis muted">(.*?)</p>', seats_sec).group(1)
    evs = {r["evidence"] for r in cix.seats.records if r["current"] and r["dates"] == "observed"}
    assert evs
    for ev in evs:
        assert f"the {ev}" in line


def test_names_inside_item_titles_never_link_to_an_official(tmp_path, cfg, city_facts):
    """city-pages/cross-body-name-link: an item title is text in the document; a buyer or applicant may share an
    official's name. No name inside a title links, in the council's pages or the county's."""
    county = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cname = county["officials"][0]["name"]
    member = city_facts["officials"][0]
    facts = json.loads(json.dumps(city_facts))
    it = next(i for i in facts["items"] if i["title"])
    it["title"] = f"Sale of property to {cname} and {member['name']}"
    d = tmp_path / "c"
    d.mkdir()
    (d / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    out = tmp_path / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS,
          councils=[{**cfg, "facts_path": d / "facts.json"}])
    year = (out / "city" / "items" / f"{it['year']}.html").read_text(encoding="utf-8")
    assert f'<span data-item-title>Sale of property to {cname} and {member["name"]}</span>' in year
    n = 0
    for f in out.rglob("*.html"):
        for m in re.finditer(r"<span data-item-title>(.*?)</span>", f.read_text(encoding="utf-8"), re.S):
            n += 1
            assert "<a " not in m.group(1), f
    assert n
    cs = [{"slug": "city", "prefix": "city/", "facts": facts}]
    problems, _ = site_checks.check_name_links(out, county, site_checks.read_roster(FIXTURE_SEATS), cs)
    assert problems == []


def test_a_run_of_one_at_the_latest_minutes_read_is_kept():
    """city-pages/ward-misprint: a member first printed at the latest minutes read is a current record, not a
    misprint; a lone print before the latest is still dropped."""
    wards = [_w("2020-01-01", "a", 1), _w("2020-02-01", "a", 1), _w("2020-03-01", "a", 1),
             _w("2020-02-01", "b", 4),                                # lone print, not at the latest: dropped
             _w("2020-01-01", "c", 2), _w("2020-02-01", "c", 2), _w("2020-03-01", "c", 3)]  # c moves at the latest
    rows, latest = council.holder_rows(wards + [_w("2020-03-01", "b", 5)], FACTS_W, CFG)
    got = sorted((r["official_id"], r["seat"], r["start"], r["end"]) for r in rows)
    assert latest == "2020-03-01"
    assert got == [("a", "ward-1", "2020-01-01", None), ("b", "ward-5", "2020-03-01", None),
                   ("c", "ward-2", "2020-01-01", "2020-02-01"), ("c", "ward-3", "2020-03-01", None)]


# ---------------------------------------------------------------- page weight (city-pages/page-weight)

def test_member_page_links_each_year_to_the_page_that_holds_that_years_rows(cpages, cix, city_facts):
    for o in city_facts["officials"]:
        ctx = views.official(o["id"], cix)
        page = cpages[f"city/members/{o['id']}.html"]
        assert 'id="history"' not in page   # no rows on the member page itself
        links = {y: h for h, y in re.findall(r'<a href="\.\./\.\./([^"]+)">(\d{4})</a> <span class="muted">', page)}
        assert sorted(links) == sorted(y["year"] for y in ctx["year_pages"])
        for y in ctx["year_pages"]:
            rel, _, anchor = links[y["year"]].partition("#")
            yp = cpages[rel]
            label = rel.rsplit("/", 1)[1][:-5].replace("-", " to ")
            assert f'<a href="../../../city/members/{o["id"]}.html">{o["name"]}</a>: {label}</h1>' in yp
            assert anchor in ("", f"year-{y['year']}") and f'id="year-{y["year"]}"' in yp
            rows = re.findall(r'<tr role="row" class="fact[^"]*" data-type="[^"]+" data-year="(\d{4})"', yp)
            assert rows.count(y["year"]) == y["n"]
        assert sum(y["n"] for y in ctx["year_pages"]) == len(ctx["rows"])


def test_county_official_pages_keep_their_history_inline(pages):
    off = [r for r in pages if r.startswith("officials/") and r.count("/") == 1]
    assert off and all('id="history"' in pages[r] for r in off if "No votes or attendance" not in pages[r])
    assert not any(r.count("/") == 2 and r.startswith("officials/") for r in pages)


def test_balanced_chunks_are_contiguous_and_cover_everything():
    from sitegen.build import balanced_chunks
    w = [5, 1, 1, 1, 5, 1, 1, 1, 5, 1]
    for k in range(1, 12):
        runs = balanced_chunks(w, k)
        assert [i for r in runs for i in r] == list(range(len(w)))
        assert all(len(r) for r in runs) and len(runs) <= min(k, len(w))
    assert [list(r) for r in balanced_chunks([1, 1, 1, 1], 2)] == [[0, 1], [2, 3]]


def test_a_year_page_over_the_limit_is_split_in_parts_and_links_follow(tmp_path, cfg, monkeypatch):
    monkeypatch.setattr(config, "PAGE_BYTES", 60_000)
    monkeypatch.setattr(config, "PAGE_TARGET", 40_000)
    out = tmp_path / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, councils=[cfg])
    pages = {p.relative_to(out).as_posix(): p.read_text(encoding="utf-8") for p in out.rglob("*.html")}
    parts = [r for r in pages if re.fullmatch(r"(city/)?(meetings|items)/\d{4}-\d+\.html", r)]
    assert parts, sorted(pages)
    for r in parts:
        first = re.sub(r"-\d+\.html$", ".html", r)
        assert 'class="year-nav parts-nav"' in pages[r] and 'class="year-nav parts-nav"' in pages[first]
    for rel, html in pages.items():
        if rel.startswith(("city/meetings/", "city/items/", "items/")):
            n = html.count('<section class="council-meeting"') + html.count('<section class="item"')
            assert len(html.encode("utf-8")) <= 60_000 or n == 1, rel   # one entry alone may be bigger
    county = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pg = {rel: site_checks.parse(out / rel) for rel in pages}
    assert site_checks.check_links(out, pg, no_export=True) == []
    cs = [{"slug": "city", "prefix": "city/", "facts": json.loads(cfg["facts_path"].read_text(encoding="utf-8"))}]
    problems, _ = site_checks.check_name_links(out, county, site_checks.read_roster(FIXTURE_SEATS), cs)
    assert problems == []
    problems, _ = site_checks.check_totals(out, {r: None for r in pages}, cs[0]["facts"], "city/meetings/",
                                           "city/members")
    assert problems == []


# ---------------------------------------------------------------- history pages (city-pages/file-budget)

def test_pack_years_joins_consecutive_years_while_the_page_fits():
    from sitegen.build import pack_years, years_key
    size = {"2026": 200_000, "2025": 300_000, "2024": 300_000, "2023": 900_000, "2022": 100_000, "2021": 100_000}
    groups = [{"year": y} for y in size]                       # newest first, as the member page lists them
    runs = pack_years(groups, lambda run: 20_000 + sum(size[g["year"]] for g in run))
    assert [years_key(r) for r in runs] == ["2024-2026", "2023", "2021-2022"]
    assert [g["year"] for r in runs for g in r] == list(size)    # order kept, every year once
    assert pack_years([], lambda run: 0) == []


def test_pack_years_never_joins_years_with_a_gap():
    """city-pages/year-run-label: a member seen in 2018 and 2023 only gets two pages, never one labelled 2018-2023."""
    from sitegen.build import pack_years, years_key
    groups = [{"year": y} for y in ("2026", "2025", "2023", "2018", "2017")]
    runs = pack_years(groups, lambda run: 1)
    assert [years_key(r) for r in runs] == ["2025-2026", "2023", "2017-2018"]
    assert all(int(a["year"]) - int(b["year"]) == 1 for r in runs for a, b in zip(r, r[1:]))


# ---------------------------------------------------------------- alerts feeds beside a council

ATOM = "{http://www.w3.org/2005/Atom}"


def _feed(out, name):
    from xml.etree import ElementTree as ET
    return ET.parse(out / "feeds" / name).getroot()


def _alt(entry):
    return next(x.get("href") for x in entry.findall(ATOM + "link") if x.get("rel") == "alternate")


def test_council_feed_hrefs_resolve_to_council_pages(site):
    out, _ = site
    entries = _feed(out, "city-meetings.xml").findall(ATOM + "entry")
    assert entries
    for e in entries:
        href = _alt(e)
        assert href.startswith("../city/meetings/"), href
        page, _, anchor = href[3:].partition("#")
        assert (out / page).is_file(), href
        assert f'id="{anchor}"' in (out / page).read_text(encoding="utf-8"), href


def test_multi_body_feed_ids_carry_the_body_key(site, cix):
    out, _ = site
    prefix = config.SITE["alerts"]["feed_id"]
    county, city = config.SITE["county_key"], cix.body_key
    bodies, item_ids = set(), []
    for f in sorted((out / "feeds").glob("*.xml")):
        ids = [e.find(ATOM + "id").text for e in _feed(out, f.name).findall(ATOM + "entry")]
        assert len(ids) == len(set(ids)), f.name
        for i in ids:
            assert i.startswith(prefix), i
            bodies.add(i[len(prefix):].split("/")[0])
        if f.name.startswith("topic-"):
            item_ids += ids
    assert bodies == {county, city}
    assert any(i.startswith(f"{prefix}{city}/item/") for i in item_ids)
    assert any(i.startswith(f"{prefix}{county}/item/") for i in item_ids)


def test_council_item_entries_link_to_council_item_pages(site, cix):
    out, _ = site
    prefix = config.SITE["alerts"]["feed_id"] + cix.body_key + "/item/"
    hrefs = [_alt(e) for f in (out / "feeds").glob("topic-*.xml") for e in _feed(out, f.name).findall(ATOM + "entry")
             if e.find(ATOM + "id").text.startswith(prefix)]
    assert hrefs and all(h.startswith("../city/items/") for h in hrefs)
