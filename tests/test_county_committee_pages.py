"""School board and county finance committee agenda pages (sitegen/county_committees.py): the school board's hub
replaces its "coming" page, each meeting is a section with a dashed COMING minutes note and, for the county
committees, its agenda lines as printed (the school board: the count of lines only), numbers link the County
Commission's item on an exact match, no vote is shown, the switch's cards follow, and the day page and the search
index carry the meetings. Built from the county fixture with a FIXTURE agendas file."""
import json
import re
from datetime import date
from html import unescape

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS
from qa import site_checks as SC
from sitegen import config
from sitegen.build import build

TODAY = date(2024, 12, 1)
URL = "https://montgomerytn.gov/storage/departments/mayor/calendar-files/{}/{}.pdf"


def _meeting(body, mid, d, kind, entries, sid, printed, lines=None):
    """A meeting as agendas.json holds it; `lines` alone (no entries, no title) for the school board (text: false)."""
    return {"id": mid, "body": body, "date": d, "time": None, "kind": kind, "printed": printed, "notes": [],
            "cancelled": False, "url": URL.format(body, mid), "on_page": True, "source_id": sid,
            "title": None if lines is not None else f"{printed} heading", "date_printed": d,
            "lines": lines if lines is not None else len(entries),
            "entries": [{**e, "id": f"{mid}-e{i}", "page": 1, "heading": False} for i, e in enumerate(entries, 1)]}


def agendas(tmp_path):
    srcs = [{"id": f"src-{n:012d}", "url": URL.format(b, m), "sha256": f"{n:064d}", "kind": "agenda", "label": None,
             "fetched_at": "2024-11-20", "pages": 1, "text_layer": "text", "format": "pdf"}
            for n, (b, m) in enumerate([("school-board", "2024-11-26-formal"), ("school-board", "2024-11-12-study"),
                                        ("budget-committee", "2024-11-20-regular")], 1)]
    data = {
        "schema": "county-committees-1", "fixture": True,
        "listing_url": "https://montgomerytn.gov/code/webshare/commission-committees-agendas.php",
        "record_label": "Montgomery County Committee Agendas page",
        "bodies": [{"key": "school-board", "group": "school", "name": "FIXTURE Board of Education",
                    "short": "School board", "folder": "School System", "text": False,
                    "kind_labels": {"formal": "Formal Board Meeting", "study": "Study Session"}},
                   {"key": "budget-committee", "group": "county-finance", "name": "FIXTURE Budget Committee",
                    "short": "Budget Committee", "folder": "Budget Committee",
                    "text": True, "kind_labels": {"regular": "Budget Committee"}}],
        "coverage": {"from": "2024-11-12", "to": "2024-11-26"},
        "meetings": [
            _meeting("school-board", "2024-11-12-study", "2024-11-12", "study", [],
                     srcs[1]["id"], "11-12-24 Study Session Agenda", lines=1),
            _meeting("school-board", "2024-11-26-formal", "2024-11-26", "formal", [],
                     srcs[0]["id"], "11-26-24 Formal Board Agenda", lines=3),
            _meeting("budget-committee", "2024-11-20-regular", "2024-11-20", "regular",
                     [{"text": "24-12-91* Resolution FIXTURE budget amendment", "number": "24-12-91"},
                      {"text": "24-12-99* Resolution with no county item", "number": "24-12-99"}],
                     srcs[2]["id"], "Budget Committee Agenda 11-20-2024")],
        "sources": srcs}
    p = tmp_path / "agendas.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p, data


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cmx")
    path, data = agendas(tmp)
    out = tmp / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, today=TODAY, county_committees=path)
    return out, data


def main_of(p) -> str:
    return p.read_text(encoding="utf-8").split("<main", 1)[1].split("</main>")[0]


def text(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def test_school_board_hub_replaces_the_coming_page(built):
    out, _ = built
    pg = config.SITE["school_board"]["page"]
    main = main_of(out / f"{pg['slug']}.html")
    assert f'<h1>{pg["title"]}</h1>' in main                      # no Coming tag on the h1
    assert 'data-card="meetings"' in main and 'href="school-board/meetings/2024.html"' in main
    assert "What is planned" not in main
    # the "What we can show" note says where the minutes are, so the hub carries no separate minutes note
    assert config.SITE["county_committees"]["minutes"]["school"] not in text(main) and 'data-limits="school"' in main
    assert config.SITE["school_board"]["url"] in main
    nav = (out / "index.html").read_text(encoding="utf-8")
    nav = nav[nav.index('<nav id="site-nav"'):]
    assert f'{pg["slug"]}.html">{pg["nav_label"]}</a>' in nav     # the menu entry drops its Coming chip


def test_school_board_hub_says_what_it_can_show_and_why_in_config_words(built):
    """Brian 2026-11-16: the hub says plainly what is here (agendas, from the county), what is not (minutes, votes,
    budget) and why (cmcss.net blocks automated visitors; this site respects that), with one plain link."""
    out, _ = built
    sb = config.SITE["school_board"]
    lim = config.SITE["switch"]["bodies"]["school"]["limits"]
    main = main_of(out / f"{sb['page']['slug']}.html")
    note = main.split('data-limits="school">', 1)[1].split("</section>", 1)[0]
    assert f'<h2 class="sec-h" id="limits-h">{lim["heading"]}</h2>' in note
    assert text(note).replace(" .", ".") == (f'{lim["heading"]} {lim["shown"]} {lim["not_shown"]} {lim["why"]} '
                                             f'{lim["link_lede"]} {sb["link_label"]} (opens in a new tab).')
    assert re.findall(r'href="([^"]+)"', note) == [sb["url"]] and 'data-ext="school"' in note
    # above the cards; each coming card agrees with it: the card names the school system's website, never "yet"
    assert main.index('data-limits="school"') < main.index('class="hub-cards"')
    cards = {c["key"]: c for c in config.SITE["switch"]["bodies"]["school"]["cards"]}
    for key in ("votes", "budget"):
        assert "school system website" in cards[key]["text"] and "yet" not in cards[key]["text"], key
        assert cards[key]["text"] in text(main), key
    assert "yet" not in config.SITE["county_committees"]["minutes"]["school"]
    for w in ("agendas", "county"):
        assert w in lim["shown"]
    for w in ("minutes", "votes", "budget"):
        assert w in lim["not_shown"]
    # neutral: the reason is the site's own rule, said without judging the school system
    assert "CMCSS" not in " ".join(lim[k] for k in ("shown", "not_shown", "why", "link_lede"))
    assert not re.search(r"\b(refuse|hide|hides|hidden|secret|unfortunately|sadly|only)\b",
                         " ".join(lim[k] for k in ("shown", "not_shown", "why")).lower())


def test_the_limits_note_is_left_out_without_its_heading_or_lines():
    from sitegen import bodies
    assert bodies.limits(None) is None and bodies.limits({"heading": "H"}) is None
    assert bodies.limits({"shown": "x"}) is None
    one = bodies.limits({"heading": "H", "why": "W", "link_lede": "L", "link": {"from": "nowhere", "kind": "school"}})
    assert one == {"heading": "H", "lines": ["W"], "link_lede": "", "link": None}


def test_year_page_sections_lines_minutes_note_and_no_votes(built):
    out, data = built
    main = main_of(out / "school-board" / "meetings" / "2024.html")
    secs = re.findall(r'<section class="council-meeting committee-meeting" id="([^"]+)"', main)
    assert secs == ["2024-11-12-study", "2024-11-26-formal"]
    assert main.count('class="coming-note"') == 2
    # the school board's minutes are not collected: their own tag, never "Coming" (Brian 2026-11-16); the county
    # finance committees' minutes line keeps "Coming"
    tag = config.SITE["switch"]["not_collected_tag"]
    assert main.count(f'<p class="coming-note"><span class="chip chip-uncollected">{tag}</span> Minutes:') == 2
    assert "chip-coming" not in main
    fin_main = main_of(out / "county-committees" / "budget-committee" / "2024.html")
    assert '<p class="coming-note"><span class="chip chip-coming">Coming</span> Minutes:' in fin_main
    assert "This agenda has 3 lines." in main and "This agenda has 1 line." in main
    assert config.SITE["county_committees"]["no_text"] in main       # says why the items are not shown
    assert "data-item-title" not in main and "agenda p." not in main and "heading" not in main
    assert data["sources"][0]["url"] in main                          # the official PDF link
    fin = main_of(out / "county-committees" / "budget-committee" / "2024.html")
    assert "agenda p. 1" in fin and f'{data["sources"][2]["url"]}#page=1' in fin
    assert not re.search(r"\b(moved by|seconded|voted|outcome|unanimous)\b", text(main), re.I)


def test_finance_pages_link_commission_items_on_an_exact_number_only(built):
    out, _ = built
    idx = main_of(out / "county-committees" / "index.html")
    assert 'id="budget-committee"' in idx and "county-committees/budget-committee/2024.html" in idx
    main = main_of(out / "county-committees" / "budget-committee" / "2024.html")
    assert "County Commission record of 24-12-91" in main
    assert "record of 24-12-99" not in main
    assert "the county does not post this committee" in text(main)


def test_switch_cards_and_day_page_and_search(built):
    out, _ = built
    county = main_of(out / "montgomery-county.html")
    card = county.split('id="card-budget-committee"', 1)[1].split("</li>", 1)[0]
    assert "is-coming" not in county.split('id="card-budget-committee"', 1)[0][-80:]
    assert 'href="county-committees/index.html#budget-committee"' in card
    assert 'id="card-finance-committees"' in county
    today = main_of(out / "today.html")
    assert 'id="school-board-2024-11-26-formal"' in today and 'data-body="school"' in today
    assert 'id="budget-committee-2024-11-20-regular"' in today
    assert "Its meetings are not collected yet" not in today
    # the school board's day card says its minutes are not collected, under that tag, never "Coming"
    # (notcollected/today-minutes-coming); the county finance committee's card keeps "Coming"
    tag = config.SITE["switch"]["not_collected_tag"]
    school_card = today.split('id="school-board-2024-11-26-formal"', 1)[1].split("</article>", 1)[0]
    assert f'<p class="coming-note"><span class="chip chip-uncollected">{tag}</span> Minutes:' in school_card
    assert "chip-coming" not in school_card
    fin_card = today.split('id="budget-committee-2024-11-20-regular"', 1)[1].split("</article>", 1)[0]
    assert '<span class="chip chip-coming">Coming</span> Minutes:' in fin_card
    from qa import site_checks
    pages = {p.relative_to(out).as_posix(): None for p in out.rglob("*.html")}
    problems, note = site_checks.check_not_collected(out, pages)
    assert problems == [] and not note.startswith("0 "), (problems, note)
    idx = (out / "static" / "search-index.js").read_text(encoding="utf-8")
    rec = json.loads(idx.split("=", 1)[1].rstrip().rstrip(";"))
    mine = [r for r in rec["records"] if r["id"].startswith(("school-board-", "budget-committee-"))]
    assert {r["b"] for r in mine} == {"school", config.SITE["county_key"]} and len(mine) == 3
    assert all((out / r["h"].split("#")[0]).is_file() for r in mine)


def test_site_check_passes_and_catches_a_vote_word(built, monkeypatch):
    out, data = built
    cmx = {**data, "_site": config.SITE["county_committees"]}
    problems, note = SC.check_county_committees(out, {}, cmx)
    assert problems == [], problems
    p = out / "county-committees" / "budget-committee" / "2024.html"
    raw = p.read_text(encoding="utf-8")
    p.write_text(raw.replace("agenda p. 1", "Moved by Example, passed, agenda p. 1"), encoding="utf-8")
    try:
        problems, _ = SC.check_county_committees(out, {}, cmx)
        assert any("moved by" in x for x in problems) and any("passed" in x for x in problems)
    finally:
        p.write_text(raw, encoding="utf-8")


def test_without_the_file_the_school_page_stays_coming(tmp_path):
    out = tmp_path / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, today=TODAY)
    pg = config.SITE["school_board"]["page"]
    assert 'chip-coming">Coming</span></h1>' in main_of(out / f"{pg['slug']}.html")
    assert not (out / "county-committees").exists()


def test_site_check_fails_school_board_text_in_the_file(built):
    """privacy-withhold: a school board meeting holding a title or an entry in agendas.json is a failure."""
    import copy
    out, data = built
    for change in ({"title": "CMCSS Board of Education Formal Session"},
                   {"entries": [{"text": "6:02 Point of Pride Awards", "number": None, "page": 1, "heading": False,
                                 "id": "x-e1"}]},
                   {"summary": "words"}):
        cmx = {**copy.deepcopy(data), "_site": config.SITE["county_committees"]}
        next(m for m in cmx["meetings"] if m["id"] == "2024-11-26-formal").update(change)
        problems, _ = SC.check_county_committees(out, {}, cmx)
        assert any("agendas.json holds school board agenda text" in x for x in problems), (change, problems)


def test_site_check_fails_school_board_text_on_a_page(built):
    """privacy-withhold: a school board page showing an agenda line (or any data-item-title) is a failure."""
    out, data = built
    cmx = {**data, "_site": config.SITE["county_committees"]}
    p = out / "school-board" / "meetings" / "2024.html"
    raw = p.read_text(encoding="utf-8")
    p.write_text(raw.replace("<p class=\"muted\" data-no-text>",
                             "<p><span data-item-title>Avery Madeup, Sample High School</span></p><p class=\"muted\" "
                             "data-no-text>", 1), encoding="utf-8")
    try:
        problems, _ = SC.check_county_committees(out, {}, cmx)
        assert any("the page shows school board agenda text" in x for x in problems), problems
        assert any("shows school board agenda text" in x and x.startswith("school-board/meetings") for x in problems)
    finally:
        p.write_text(raw, encoding="utf-8")


def test_render_takes_text_from_the_config_not_the_data(tmp_path):
    """privacy-withhold/render-trusts-data: a school board meeting whose data file holds a title, items and
    text: true still renders no title and no items, because which bodies show text comes from the collector config."""
    path, data = agendas(tmp_path)
    data["bodies"][0]["text"] = True
    m = next(m for m in data["meetings"] if m["id"] == "2024-11-26-formal")
    m["title"] = "FIXTURE heading Avery Madeup"
    m["entries"] = [{"text": "6:02 Point of Pride Awards: Avery Madeup", "number": "24-12-91", "page": 1,
                     "heading": False, "id": "2024-11-26-formal-e1"}]
    path.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, today=TODAY, county_committees=path)
    main = main_of(out / "school-board" / "meetings" / "2024.html")
    assert "Avery Madeup" not in main and "data-item-title" not in main and "This agenda has 3 lines." in main
    idx = (out / "static" / "search-index.js").read_text(encoding="utf-8")
    assert "Avery Madeup" not in idx
    assert not any("Avery Madeup" in f.read_text(encoding="utf-8", errors="replace")
                   for f in out.rglob("*") if f.is_file() and f.suffix in (".html", ".js", ".json", ".xml"))


def test_year_pages_carry_the_one_crumb_line(built):
    """Round 2 wayfinding: the crumb above the h1 leads to the school board's page, or the county's then the index."""
    out, _ = built
    def crumb(rel):
        main = main_of(out / rel)
        nav = re.search(r'<nav class="crumb"[^>]*>(.*?)</nav>', main, re.S)
        assert nav and main.index('<nav class="crumb"') < main.index("<h1"), rel
        return [h.lstrip("./") for h in re.findall(r'href="([^"]+)"', nav.group(1))]
    pg = config.SITE["school_board"]["page"]["slug"]
    assert crumb("school-board/meetings/2024.html") == [f"{pg}.html"]
    assert crumb("county-committees/budget-committee/2024.html") == ["montgomery-county.html",
                                                                     "county-committees/index.html"]
    assert crumb("county-committees/index.html") == ["montgomery-county.html"]
    assert "kicker-line" not in main_of(out / "school-board" / "meetings" / "2024.html")


def test_the_not_collected_check_fails_a_line_that_also_says_coming(tmp_path):
    """notcollected/check-gap: the QA check fails a coming note, hub card or door line holding both tags."""
    from qa import site_checks
    tag = config.SITE["switch"]["not_collected_tag"]
    both = (f'<p class="coming-note"><span class="chip chip-uncollected">{tag}</span> '
            '<span class="chip chip-coming">Coming</span> Minutes.</p>')
    (tmp_path / "bad.html").write_text(f"<main>{both}</main>", encoding="utf-8")
    (tmp_path / "ok.html").write_text(f'<main><p class="door-coming door-uncollected"><span class="chip '
                                      f'chip-uncollected">{tag}</span> School board: Budget.</p></main>',
                                      encoding="utf-8")
    problems, _ = site_checks.check_not_collected(tmp_path, {"bad.html": None, "ok.html": None})
    assert problems == [f"bad.html: a line tagged {tag!r} also carries the Coming tag"]
