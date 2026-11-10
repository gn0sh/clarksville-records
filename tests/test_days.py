# ruff: noqa: E501
"""Daylight M2: the day page (sitegen/days.py, today.html, static/days.js): the window of weeks around today, one
section per day, the day cards from every body (county, council, RPC, bids), the school board placeholder, and the
rules every record page keeps (votes only from the record, names linked, sources linked, the record line, no inline
script, no sideways scroll)."""
import json
import os
import re
import shutil
import subprocess
from datetime import date
from types import SimpleNamespace

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT, parse
from qa import site_checks
from sitegen import config, days, rpc
from sitegen.build import BuildError, build

FIN = ROOT / "site" / "fixtures" / "finance.sample.json"
LINE = "Unofficial copy. Official record:"
TODAY = date(2024, 12, 1)    # a Sunday: the window is 2024-11-03 to 2025-01-04, holding two fixture meetings


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("days") / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, today=TODAY)
    return out


@pytest.fixture(scope="module")
def html(site):
    return (site / "today.html").read_text(encoding="utf-8")


def section(html: str, iso: str) -> str:
    start = html.index(f'id="d-{iso}"')
    end = html.find('<section class="day-sheet', start)
    return html[start:end if end > 0 else len(html)]


# ---------------------------------------------------------------- the window


def test_window_is_whole_weeks_around_today_in_the_configured_shape():
    assert days.window(date(2026, 11, 10)) == (date(2026, 10, 11), date(2026, 12, 12))   # Sun to Sat, 9 weeks
    assert days.window(date(2026, 11, 8)) == (date(2026, 10, 11), date(2026, 12, 12))    # the Sunday itself
    assert days.window(date(2026, 11, 14)) == (date(2026, 10, 11), date(2026, 12, 12))   # the Saturday
    assert days.window(date(2026, 11, 10), {"weeks_before": 0, "weeks_after": 0, "week_start": "monday"}) == \
        (date(2026, 11, 9), date(2026, 11, 15))
    for bad in ({"week_start": "someday"}, {"weeks_before": -1}, {"weeks_before": 20, "weeks_after": 20}):
        with pytest.raises(days.DaysError):
            days.window(date(2026, 11, 10), bad)


def test_today_is_taken_in_the_site_zone_or_fixed_by_the_environment(monkeypatch):
    monkeypatch.setenv("RECORDS_TODAY", "2026-03-08")
    assert days.today_in_zone() == date(2026, 3, 8)
    monkeypatch.delenv("RECORDS_TODAY")
    assert isinstance(days.today_in_zone("America/Chicago"), date)
    assert config.SITE["site_timezone"] and config.SITE["days"]["week_start"] == "sunday"


def test_every_day_of_the_window_is_a_section_and_a_strip_button(html):
    dates = re.findall(r'<section class="day-sheet[^"]*" id="d-(\d{4}-\d{2}-\d{2})"', html)
    assert dates[0] == "2024-11-03" and dates[-1] == "2025-01-04" and len(dates) == 63
    assert re.findall(r'<button type="button" class="day" data-date="([\d-]+)"', html) == dates
    assert 'data-start="2024-11-03" data-end="2025-01-04" data-built="2024-12-01"' in html
    assert f'data-tz="{config.SITE["site_timezone"]}"' in html
    # without the script: no strip, and the empty days are left out by CSS (the list holds the days with records)
    assert '<nav class="day-strip" id="day-strip" aria-label="Pick a day" hidden>' in html
    assert 'class="day-sheet is-empty" id="d-2024-11-05"' in html
    assert 'class="day-sheet" id="d-2024-11-04"' in html and 'class="day-sheet" id="d-2024-12-09"' in html


# ---------------------------------------------------------------- county cards: votes only from the record


def test_county_card_shows_each_roll_call_with_names_linked_and_its_minutes_page(html, facts):
    sec = section(html, "2024-11-04")
    rcs = [r for r in facts["roll_calls"] if r["meeting_id"] == "2024-11-04-formal"]
    for rc in rcs:
        assert f'data-fact-id="{rc["id"]}"' in sec
        src = next(s for s in facts["sources"] if s["id"] == rc["source_id"])
        assert f'href="{src["url"]}#page={rc["page"]}"' in sec
        for v in rc["votes"]:
            name = next(o["name"] for o in facts["officials"] if o["id"] == v["official_id"])
            assert f'<a href="officials/{v["official_id"]}.html">{name}</a>' in sec
    assert 'href="meetings/2024-11-04-formal.html">Meeting page</a>' in sec
    assert LINE + ' <a href="' + src["url"] in sec          # the record line names the meeting's own minutes PDF
    assert "Votes from the minutes, in minutes order (2)" in sec


def test_a_held_roll_call_shows_not_confirmed_and_no_value(html, facts):
    sec = section(html, "2024-12-09")
    held = next(r for r in facts["roll_calls"] if r["verification"]["status"] == "unverified")
    i = sec.index(f'data-fact-id="{held["id"]}"')
    block = sec[i:sec.index("</li>\n", sec.index("</details>", i))]
    assert "Not confirmed: this page was hard to read." in block
    assert not re.search(r"\b\d+ (?:yes|no)\b", block) and "Passed" not in block
    assert held["outcome_text"] not in html


def test_site_checks_pass_on_the_day_page(site, facts):
    pages = {p.relative_to(site).as_posix(): site_checks.parse(p) for p in site.rglob("*.html")}
    assert site_checks.page_type("today.html") == "today" and "today" in site_checks.NARROW_TYPES
    assert not site_checks.check_links(site, pages, no_export=True)
    probs, _ = site_checks.check_sources(site, pages, facts, (), site_checks.allowed_external(
        site_checks._site_cfg(), FIXTURE_SEATS, FIXTURE_DISTRICTS))
    assert not [p for p in probs if p.startswith("today.html")], probs
    assert not [p for p in site_checks.check_unverified(site, pages, facts, internal=False, export=False)
                if p.startswith("today.html")]
    assert not [p for p in site_checks.check_external(pages, site, site_checks._site_cfg()) if "today.html" in p]
    probs, _ = site_checks.check_name_links(site, facts, site_checks.read_roster(FIXTURE_SEATS))
    assert not [p for p in probs if p.startswith("today.html")], probs


# ---------------------------------------------------------------- the page's own rules


def test_no_inline_script_the_nav_lists_today_and_the_page_links_report(site, html):
    tree = parse(html)
    scripts = [n for n in tree.walk() if n.tag == "script"]
    assert scripts and all(n.attrs.get("src") for n in scripts)
    assert {n.attrs["src"] for n in scripts} >= {"static/js-flag.js", "static/days.js"}
    assert not re.search(r"\son[a-z]+=", html)
    assert '<a href="today.html" aria-current="page">Today</a>' in html
    assert '<a href="report.html">Report an error on this page</a>' in html
    landing = (site / "index.html").read_text(encoding="utf-8")
    assert '<a class="sky-link" href="today.html"><time class="sky-date" id="sky-date"></time>' in landing
    assert (site / "static" / "days.js").is_file()


def test_school_board_is_a_coming_placeholder_with_one_plain_link(html):
    sb = config.SITE["school_board"]
    assert sb["url"].startswith("https://") and "cmcss" in sb["url"]
    assert f'<a data-ext="school" href="{sb["url"]}"' in html and html.count(sb["url"]) == 1
    assert sb["label"] in html and "not collected yet" in html
    assert sb["url"] in site_checks.allowed_external(config.SITE, None, None)
    assert "school" in site_checks.EXT_KINDS
    # nothing in the collector fetches it
    fetch = (ROOT / "collector" / "fetch.py").read_text(encoding="utf-8")
    assert "cmcss" not in fetch


def test_no_wording_about_people_on_the_day_page(html):
    text = re.sub(r"<[^>]+>", " ", html).lower()
    for word in ("controversial", "slams", "failed to", "refused", "should", "unfortunately", "praised"):
        assert word not in text, word


# ---------------------------------------------------------------- the other bodies


def test_council_cards_show_votes_when_read_and_the_agenda_when_not(tmp_path):
    from test_council_pages import CFG, CITY, subset
    facts = json.loads((CITY / "facts.json").read_text(encoding="utf-8"))
    read = "2019-01-03-regular"
    agenda_only = next(m for m in facts["meetings"] if m.get("minutes_status") == "not_posted" and m.get("agenda_source_id"))
    sub = subset(facts, [read, agenda_only["id"]])
    wards = [w for w in json.loads((CITY / "wards.json").read_text(encoding="utf-8")) if w["meeting_id"] == read]
    (tmp_path / "facts.json").write_text(json.dumps(sub), encoding="utf-8")
    (tmp_path / "wards.json").write_text(json.dumps(wards), encoding="utf-8")
    cfg = {**CFG, "facts_path": tmp_path / "facts.json", "wards_path": tmp_path / "wards.json"}
    for when, mid in ((date(2019, 1, 3), read), (date.fromisoformat(agenda_only["date"]), agenda_only["id"])):
        out = tmp_path / f"site-{mid}"
        build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, councils=[cfg], today=when)
        sec = section((out / "today.html").read_text(encoding="utf-8"), when.isoformat())
        assert CFG["body_name"] in sec and LINE in sec
        if mid == read:
            rc = next(r for r in sub["roll_calls"] if r["meeting_id"] == read)
            assert f'data-fact-id="{rc["id"]}"' in sec
            oid = next(v["official_id"] for v in rc["votes"] if v["official_id"])
            assert f'href="city/members/{oid}.html"' in sec
            assert f'href="city/meetings/2019.html#{read}">Meeting page</a>' in sec
        else:
            ag = next(s for s in sub["sources"] if s["id"] == agenda_only["agenda_source_id"])
            assert f'Agenda: <a href="{ag["url"]}"' in sec and "Minutes not posted" in sec
            assert "data-fact-id" not in sec
            assert f'{LINE} <a href="{ag["url"]}"' in sec


def test_scheduled_meetings_come_from_the_city_calendar_once_per_date_and_kind(tmp_path):
    cal = tmp_path / "calendar.json"
    cal.write_text(json.dumps([
        {"date": "2026-12-03", "kind": "regular", "title": "Regular Session"},
        {"date": "2026-12-03", "kind": "regular", "title": "Regular Session"},     # the calendar lists it twice
        {"date": "2026-11-05", "kind": "regular", "title": "Regular Session"},     # held in the facts already
        {"date": "2027-03-04", "kind": "regular", "title": "Regular Session"},     # outside the window
    ]), encoding="utf-8")
    cix = SimpleNamespace(cfg={"calendar": str(cal), "record_url": "https://example.gov/portal", "record_label": "portal"},
                          fixture=False, slug="city", body_name="A council", kind_labels={"regular": "Regular session"},
                          facts={"meetings": [{"date": "2026-11-05", "kind": "regular"}]})
    got = days.scheduled_cards(cix, date(2026, 10, 11), date(2026, 12, 12), date(2026, 11, 10))
    assert [(d, c["state"], c["title"]) for d, c in got] == [("2026-12-03", "scheduled", "Regular session")]
    assert got[0][1]["record"]["url"] == "https://example.gov/portal"
    assert days.scheduled_cards(SimpleNamespace(**{**vars(cix), "fixture": True}), date(2026, 10, 11),
                                date(2026, 12, 12), date(2026, 11, 10)) == []


def jinja_card(c: dict) -> str:
    from sitegen.build import make_env
    src = (config.TEMPLATE_DIR / "today.html.j2").read_text(encoding="utf-8")      # the card macro, without the page shell
    head = "".join(ln + "\n" for ln in src.splitlines()[:3] if ln.startswith("{% from"))
    macro = src[src.index("{% macro card"):src.index("{% endmacro %}") + len("{% endmacro %}")]
    return make_env().from_string(head + macro + "{{ card(c) }}").render(c={"cancelled": False, **c}, root="")


def _sched(tmp_path, rows):
    cal = tmp_path / "calendar.json"
    cal.write_text(json.dumps(rows), encoding="utf-8")
    return SimpleNamespace(cfg={"calendar": str(cal), "record_url": "https://example.gov/portal", "record_label": "portal"},
                           fixture=False, slug="city", body_name="A council", kind_labels={"regular": "Regular session"},
                           facts={"meetings": []})


def test_scheduled_drops_rows_before_the_build_day_and_called_off_titles(tmp_path):
    rows = [{"date": "2026-11-09", "kind": "regular", "title": "Regular Session"},                  # before build day
            {"date": "2026-11-12", "kind": "regular", "title": "(Meeting moved to June 20th)"},
            {"date": "2026-11-13", "kind": "regular", "title": "CANCELLED - Regular Session"},
            {"date": "2026-11-14", "kind": "regular", "title": "Canceled Session"},
            {"date": "2026-11-15", "kind": "regular", "title": "Postponed: Regular Session"},
            {"date": "2026-11-10", "kind": "regular", "title": "Regular Session"}]
    got = days.scheduled_cards(_sched(tmp_path, rows), date(2026, 11, 1), date(2026, 12, 12), date(2026, 11, 10))
    assert [d for d, _ in got] == ["2026-11-10"]


def test_scheduled_card_shows_the_printed_title_the_built_date_and_the_agenda_or_none(tmp_path):
    rows = [{"date": "2026-11-12", "kind": "regular", "title": "Regular Session & Work Sess.", "agenda_url": ""},
            {"date": "2026-11-13", "kind": "regular", "title": "Regular Session",
             "agenda_url": "https://example.gov/a.pdf"},
            {"date": "2026-11-14", "kind": "regular", "title": "Regular Session", "agenda_url": None}]
    got = days.scheduled_cards(_sched(tmp_path, rows), date(2026, 11, 1), date(2026, 12, 12), date(2026, 11, 10))
    html = [jinja_card(c) for _, c in got]
    assert 'data-item-title>Regular Session &amp; Work Sess.</span>' in html[0]
    assert all("On the city's calendar as of " + days.date_text(date(2026, 11, 10)) in h for h in html)
    assert "No agenda posted" in html[0] and "No agenda posted" in html[2]
    assert 'href="https://example.gov/a.pdf"' in html[1] and "No agenda posted" not in html[1]


def test_scheduled_skips_rows_without_a_date_or_kind(tmp_path):
    rows = [{"kind": "regular", "title": "x"}, {"date": "2026-11-12", "title": "x"},
            {"date": None, "kind": None}, {"date": "2026-11-12", "kind": "regular", "title": "ok"}]
    got = days.scheduled_cards(_sched(tmp_path, rows), date(2026, 11, 1), date(2026, 12, 12), date(2026, 11, 10))
    assert [d for d, _ in got] == ["2026-11-12"]


def test_rpc_cards_list_each_case_as_printed_with_its_agenda_page(tmp_path):
    from test_rpc_pages import AGENDA, rpc_facts
    (tmp_path / "rpc.json").write_text(json.dumps(rpc_facts(tmp_path)), encoding="utf-8")
    cfg = {**rpc.load_config("cmc-rpc"), "facts_path": tmp_path / "rpc.json"}
    out = tmp_path / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, rpc=cfg, today=date(2026, 10, 27))
    sec = section((out / "today.html").read_text(encoding="utf-8"), "2026-10-27")
    assert "Cases on the agenda, as printed" in sec
    assert re.search(re.escape(AGENDA) + r"#page=\d+", sec)
    assert f'{LINE} <a href="{AGENDA}"' in sec
    assert 'href="rpc/meetings/2026.html#case-' in sec and "data-item-title" in sec


def test_bids_appear_on_the_date_the_archive_prints(tmp_path):
    fin = json.loads(FIN.read_text(encoding="utf-8"))
    sol = next(s for s in fin["solicitations"] if s["archive_date"] == "2026-10-14")
    out = tmp_path / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, finance_path=FIN,
          today=date(2026, 10, 14))
    html = (out / "today.html").read_text(encoding="utf-8")
    sec = section(html, "2026-10-14")
    assert f'href="contracts/{sol["slug"]}.html"' in sec and "Date printed on the" in sec
    assert LINE in sec and config.SITE["official_records"]["contracts"]["url"] in sec
    assert "Budget books are by fiscal year" in html


def test_a_bad_window_setting_stops_the_build(tmp_path, monkeypatch):
    monkeypatch.setitem(config.SITE, "days", {"week_start": "never"})
    with pytest.raises(BuildError):
        build(FIXTURE, tmp_path / "s", seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, today=TODAY)


# ---------------------------------------------------------------- county agendas without minutes (county-recency Fix 1)
AGENDA_URL = "https://mcgtn.org/storage/departments/commission/agendas-and-resolutions/2024/dec-formal.pdf"


def county_agendas(tmp_path):
    src = {"id": "src-aaaaaaaaaaaa", "url": AGENDA_URL, "sha256": "a" * 64, "kind": "agenda", "label": "2024 December Formal",
           "fetched_at": "2024-12-02", "pages": 12}
    item = {"id": "x/24-12-1", "number": "24-12-1", "printed": "24-12-1*", "title": "Resolution to Accept a Donation",
            "section": "RESOLUTIONS", "page": 2, "year": 2024, "link_basis": "number"}
    meetings = [{"id": "2024-12-09-formal", "date": "2024-12-09", "kind": "formal", "source_id": src["id"], "date_page": 1,
                 "items": [item]},                                      # the minutes cover it: not shown
                {"id": "2024-12-16-formal", "date": "2024-12-16", "kind": "formal", "source_id": src["id"], "date_page": 1,
                 "items": [item]},
                {"id": "2024-12-23-informal", "date": "2024-12-23", "kind": "informal", "source_id": src["id"],
                 "date_page": 1, "items": []}]
    p = tmp_path / "agendas.json"
    p.write_text(json.dumps({"body": "Montgomery County Commission", "index_url": "https://montgomerytn.gov/commission/agenda",
                             "meetings": meetings, "sources": [src], "skipped": [], "problems": []}), encoding="utf-8")
    return p


def test_county_agenda_meetings_show_as_agenda_with_the_pdf_and_the_minutes_note(tmp_path):
    out = tmp_path / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, today=date(2024, 12, 20),
          county_agendas=county_agendas(tmp_path))
    html = (out / "today.html").read_text(encoding="utf-8")
    past = section(html, "2024-12-16")
    assert 'id="county-2024-12-16-formal"' in past
    assert f'Agenda: <a href="{AGENDA_URL}" target="_blank" rel="noopener noreferrer">PDF, 12 pages' in past
    assert "Minutes not yet posted by the county, as of December 20, 2024." in past
    assert f'{LINE} <a href="{AGENDA_URL}"' in past
    assert "Items on the agenda, as printed (1)" in past and f'href="{AGENDA_URL}#page=2"' in past
    assert '<span data-item-title>Resolution to Accept a Donation</span>' in past
    assert 'href="meetings/agendas.html#2024-12-16-formal">Meeting page</a>' in past
    upcoming = section(html, "2024-12-23")
    assert 'id="county-2024-12-23-informal"' in upcoming and "not yet posted" not in upcoming
    assert "No numbered items were read from it" in upcoming                      # no items read: said so
    # the minutes cover Dec 9: its card is the minutes card only
    assert section(html, "2024-12-09").count('id="county-2024-12-09-formal"') == 1
    assert "and the agendas the county posted for meetings after that." in html

    page = (out / "meetings" / "agendas.html").read_text(encoding="utf-8")
    assert 'id="2024-12-16-formal"' in page and 'id="2024-12-09-formal"' not in page
    assert "Minutes not yet posted by the county, as of December 20, 2024." in page
    assert f'Official record: <a href="{AGENDA_URL}"' in page                       # each meeting's own agenda
    assert 'data-ext="record" href="https://montgomerytn.gov/commission/agenda"' in page   # the page's record line
    assert page.count(LINE) == 3 and 'id="2024-12-16-formal-24-12-1"' in page
    meetings = (out / "meetings.html").read_text(encoding="utf-8")
    assert 'href="meetings/agendas.html#2024-12-16-formal">2024-12-16</a>' in meetings
    assert "Agendas without minutes yet" in meetings and "Agenda: 1 item <span" in meetings


def test_a_fixture_build_reads_no_county_agendas_unless_named(site):
    assert not (site / "meetings" / "agendas.html").exists()
    assert "Agendas without minutes yet" not in (site / "meetings.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------- the script


def _node():
    return shutil.which("node")


@pytest.mark.skipif(not _node(), reason="node not available")
def test_days_js_picks_the_day_in_the_site_zone():
    js = ROOT / "site" / "static" / "days.js"
    prog = (f"const d=require({json.dumps(str(js))});"
            "console.log(JSON.stringify([d.isoInZone(new Date('2026-11-10T03:00:00Z'),'America/Chicago'),"
            "d.isoInZone(new Date('2026-11-10T07:00:00Z'),'America/Chicago'),"
            "d.pick('#d-2026-11-05','2026-11-10','2026-10-11','2026-12-12',()=>true),"
            "d.pick('#d-2030-01-01','2026-11-10','2026-10-11','2026-12-12',()=>false),"
            "d.pick('','2027-01-20','2026-10-11','2026-12-12',()=>true),"
            "d.addDays('2026-10-31',7),"
            "d.isoInZone(new Date('2026-03-08T05:30:00Z'),'America/Chicago'),"   # before the spring jump: still 03-07 (CST)
            "d.isoInZone(new Date('2026-03-08T06:30:00Z'),'America/Chicago'),"   # 00:30 CST on 03-08
            "d.isoInZone(new Date('2026-11-01T05:30:00Z'),'America/Chicago'),"   # 00:30 CDT on 11-01
            "d.isoInZone(new Date('2026-11-01T06:30:00Z'),'America/Chicago'),"   # 01:30 CDT on 11-01
            "d.isoInZone(new Date('2027-01-01T05:30:00Z'),'America/Chicago')]))")
    r = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["2026-11-09", "2026-11-10", "2026-11-05", "2026-11-10", "2026-12-12",
                                    "2026-11-07", "2026-03-07", "2026-03-08", "2026-11-01", "2026-11-01",
                                    "2026-12-31"]


def _browser_ok():
    return bool(_node()) and (os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright")))


BROWSER_JS = r"""
const path = require('path');
let pw; for (const r of [process.env.NODE_PATH, '/opt/node22/lib/node_modules'].filter(Boolean)) { try { pw = require(path.join(r, 'playwright')); break; } catch (e) {} }
(async () => {
  const b = await pw.chromium.launch(); const out = {};
  for (const w of [360, 375, 1280]) {
    const ctx = await b.newContext({ viewport: { width: w, height: 700 } }); const p = await ctx.newPage();
    const errs = []; p.on('pageerror', e => errs.push(String(e)));
    await p.goto('file://' + process.argv[1] + '#d-2024-11-04');
    const shown = () => p.evaluate(() => [...document.querySelectorAll('.day-sheet')].filter(s => !s.hidden).map(s => s.dataset.date));
    const r = { first: await shown(), strip: await p.evaluate(() => !document.getElementById('day-strip').hidden) };
    await p.click('#wk-next'); r.step = [await shown(), await p.evaluate(() => location.hash)];
    await p.keyboard.press('ArrowLeft'); r.key = await shown();
    await p.click('.strip-week:not([hidden]) button[data-date="2024-12-09"]').catch(() => {});
    await p.goto('file://' + process.argv[1] + '#d-2024-12-09'); r.hash = await shown();
    await p.evaluate(() => document.querySelector('details.roll').open = true);
    r.sw = await p.evaluate(() => document.documentElement.scrollWidth); r.iw = w;
    await p.evaluate(() => window.scrollTo(0, 600)); r.stripTop = await p.evaluate(() => document.getElementById('day-strip').getBoundingClientRect().top);
    r.errs = errs; out[w] = r; await ctx.close();
  }
  const ctx = await b.newContext({ viewport: { width: 375, height: 700 }, javaScriptEnabled: false }); const p = await ctx.newPage();
  await p.goto('file://' + process.argv[1]);
  out.nojs = await p.evaluate(() => [getComputedStyle(document.getElementById('day-strip')).display,
    [...document.querySelectorAll('.day-sheet')].filter(s => getComputedStyle(s).display !== 'none').map(s => s.dataset.date),
    document.documentElement.scrollWidth]);
  console.log(JSON.stringify(out)); await b.close();
})();
"""


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_the_strip_turns_the_page_in_a_browser_and_nothing_scrolls_sideways(site):
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    r = subprocess.run(["node", "-e", BROWSER_JS, str(site / "today.html")], capture_output=True, text=True,
                       timeout=300, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    for w in ("360", "375", "1280"):
        x = out[w]
        assert x["first"] == ["2024-11-04"] and x["strip"], (w, x)
        assert x["step"] == [["2024-11-11"], "#d-2024-11-11"], (w, x)
        assert x["key"] == ["2024-11-10"], (w, x)
        assert x["hash"] == ["2024-12-09"], (w, x)
        assert x["sw"] <= x["iw"], (w, x)                  # no sideways scroll, roll call open
        assert x["stripTop"] == 0, (w, x)                  # the strip stays at the top
        assert not x["errs"], (w, x)
    assert out["nojs"] == ["none", ["2024-11-04", "2024-12-09"], 375]


def test_site_checks_hold_a_scheduled_agenda_link_not_in_the_facts(tmp_path):
    rows = [{"date": "2026-11-13", "kind": "regular", "title": "Regular Session", "agenda_url": "https://example.gov/a.pdf"},
            {"date": "2026-11-14", "kind": "regular", "title": "Regular Session", "agenda_url": "http://example.gov/b.pdf"}]
    got = days.scheduled_cards(_sched(tmp_path, rows), date(2026, 11, 1), date(2026, 12, 12), date(2026, 11, 10))
    assert "http://example.gov/b.pdf" not in jinja_card(got[1][1]) and "No agenda posted" in jinja_card(got[1][1])
    site = tmp_path / "site"
    site.mkdir()
    (site / "today.html").write_text("<html><body>" + jinja_card(got[0][1]) + "</body></html>", encoding="utf-8")
    pages = {"today.html": site_checks.parse(site / "today.html")}
    assert 'data-ext="listed"' in (site / "today.html").read_text(encoding="utf-8")
    probs, _ = site_checks.check_sources(site, pages, {"sources": []}, (), set())
    assert any("https://example.gov/a.pdf" in p and "not a URL from the config" in p for p in probs), probs
    probs, _ = site_checks.check_sources(site, pages, {"sources": []}, (),
                                       {"https://example.gov/a.pdf", "https://example.gov/portal"})
    assert not probs, probs
