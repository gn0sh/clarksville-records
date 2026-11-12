# ruff: noqa: E501
"""Front page v2 (docs/design/front-page-v2.md): the welcome, the address card, the "Start here" doors, the meetings
list (a selection of today.html's own cards: sitegen/days.py landing_meetings), the search and the details, with
their empty states; static/landing.js moving a row whose day has passed. Rules kept: nothing new collected, no
official named outside the wards and districts list, no Planning Commission vote, works without script."""
import json
import os
import re
import shutil
import subprocess
from datetime import date

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT, parse
from sitegen import config, days, views
from sitegen.build import build

FIN = ROOT / "site" / "fixtures" / "finance.sample.json"
LANDING_JS = ROOT / "site" / "static" / "landing.js"
TODAY = date(2024, 12, 1)    # tests/test_days.py: the window 2024-11-03 to 2025-01-04 holds two fixture meetings


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("fp2") / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, today=TODAY)
    return out


@pytest.fixture(scope="module")
def html(site):
    return (site / "index.html").read_text(encoding="utf-8")


def main_of(html):
    return html[html.index('<main id="main">'):html.index("</main>")]


def card(kind="county", state="none", body="Body", title="Formal meeting", cancelled=False):
    return {"kind": kind, "state": state, "body": body, "title": title, "dot": days.DOTS[kind],
            "cancelled": cancelled, "sols": []}


def ctx(by_day, built="2026-11-11"):
    weeks, ds = [], []
    for iso in sorted(by_day):
        d = date.fromisoformat(iso)
        ds.append({"iso": iso, "anchor": f"d-{iso}", "text": days.day_text(d), "dow": d.strftime("%a"), "n": d.day,
                   "month": d.strftime("%b"), "cards": by_day[iso]})
    weeks.append({"days": ds})
    return {"weeks": weeks, "built": built}


# ---- the selection -------------------------------------------------------------------------------------------

def test_landing_meetings_takes_the_next_and_the_last_three_bids_left_out_cancelled_kept():
    c = ctx({"2026-10-20": [card()], "2026-10-27": [card()], "2026-11-02": [card("council", "agenda")],
             "2026-11-09": [card(state="votes"), card("bids", "bids")], "2026-11-11": [card("rpc", "agenda", title=None)],
             "2026-11-20": [card("rpc", "none", cancelled=True, title=None)], "2026-12-01": [card("council", "scheduled")],
             "2026-12-03": [card("council", "scheduled")]})
    m = days.landing_meetings(c, date(2026, 11, 11))
    assert [r["iso"] for r in m["upcoming"]] == ["2026-11-11", "2026-11-20", "2026-12-01"]   # today counts as coming
    assert [r["iso"] for r in m["spare"]] == ["2026-12-03"]          # built hidden, shown by landing.js in turn
    assert [r["iso"] for r in m["recent"]] == ["2026-11-09", "2026-11-02", "2026-10-27"]      # newest first
    assert [r["chip"] for r in m["upcoming"]] == ["Agenda", "Cancelled", "Scheduled"]
    assert [r["chip"] for r in m["recent"]] == ["Votes", "Agenda", None]
    assert all(r["href"] == f"today.html#d-{r['iso']}" for r in m["upcoming"] + m["recent"])
    assert m["upcoming"][0]["title"] is None and m["built_text"] == "November 11, 2026"


def test_an_rpc_card_never_shows_votes():
    assert days.chip(card("rpc", "agenda")) == "Agenda"
    assert days.chip(card("rpc", "none")) is None
    assert days.chip({"kind": "rpc", "state": "agenda", "cancelled": True}) == "Cancelled"


def test_landing_meetings_is_empty_when_the_window_is():
    m = days.landing_meetings(ctx({}), date(2026, 11, 11))
    assert m["upcoming"] == [] and m["recent"] == [] and m["spare"] == []


# ---- the page --------------------------------------------------------------------------------------------------

def test_order_headings_and_the_address_box_ids_are_kept(html):
    main = main_of(html)
    # the fixture build has no geocoder, so no address form (its ids: tests/test_address_box.py, test_your_seats.py)
    order = ['class="welcome-h"', 'id="unofficial-short"', 'id="find-h"', 'id="your-seats"', 'href="#wards-districts"',
             'id="doors-h"', 'id="meet-h"', 'id="search-h"', 'id="landing-q"', 'id="freshness"', 'id="wards-districts"']
    at = [main.index(s) for s in order]
    assert at == sorted(at)
    assert f'<h1 id="welcome-h" class="welcome-h">{config.SITE["welcome_h1"]}</h1>' in main
    heads = re.findall(r"<(h[1-3])\b[^>]*>(.*?)</h[1-3]>", main)
    assert [h for h in heads if h[0] == "h1"] == [("h1", config.SITE["welcome_h1"])]
    # "Public bodies on this site": the body switch's overview (tests/test_body_switch.py), 2026-11-12
    assert [t for h, t in heads if h == "h2"][:5] == ["Find who represents you", "Start here",
                                                      "Public bodies on this site", "Meetings",
                                                      "Looking for something specific?"]


def test_the_short_unofficial_line_is_the_email_line_with_an_about_link(html, site):
    from sitegen import unofficial
    u = unofficial.load()
    main = main_of(html)
    assert f'id="unofficial-short">{u["email_line"]} <a href="about.html#unofficial">About this site</a>' in main
    assert u["short"] not in main                         # once on the first screen, not twice
    assert u["notice"] in html                            # the full notice stays in the footer
    assert 'id="unofficial"' in (site / "about.html").read_text(encoding="utf-8")


def test_fixture_doors_link_only_built_pages(html, site):
    main = main_of(html)
    hrefs = re.findall(r'<li class="door[^"]*">.*?</li>\s*</ul>\s*</li>', main, re.S)
    joined = " ".join(hrefs)
    links = re.findall(r'<a href="([^"#]+)', joined)
    assert links and all((site / h).is_file() for h in links)
    assert "County money" not in main and "Planning Commission" not in main     # not built in the fixture
    assert "city ward" not in joined                                           # no council in the fixture


def test_doors_follow_the_built_pages_city_first_and_rpc_only_under_meetings():
    nav = [{"label": "Today", "href": "today.html", "coming": False},
           {"label": "Votes", "href": "votes/2026.html", "coming": False},
           {"label": "Officials", "href": "officials.html", "coming": False},
           {"label": "Finance", "href": "finance.html", "coming": True},
           {"label": "Bids and awards", "href": "contracts/index.html", "coming": False}]
    site = {"nav": nav, "councils": [{"label": "City Council", "href": "city/index.html"}], "vote_years_desc": ["2026"]}
    d = {x["key"]: x for x in views.landing_doors(site, ("Planning Commission", "rpc/index.html"))}
    assert [lk["href"] for lk in d["office"]["links"]] == ["city/index.html#seats-h", "officials.html"]
    assert [lk["href"] for lk in d["votes"]["links"]] == ["city/index.html#meetings-h", "votes/2026.html"]
    assert [lk["label"] for lk in d["meetings"]["links"]] == ["Day by day", "Planning Commission"]
    assert [lk["label"] for lk in d["money"]["links"]] == ["Bids and awards"]     # the budget is still "coming"
    assert not any("rpc" in lk["href"] for lk in d["votes"]["links"])
    site["nav"] = [e for e in nav if e["label"] != "Bids and awards"]
    assert "money" not in {x["key"] for x in views.landing_doors(site)}            # a door with no links goes
    for x in views.landing_doors(site):
        assert not re.search(r"\b(?!12\b|21\b)\d+\b", x["text"])                   # no counts but wards and districts


def test_lede_names_money_only_with_finance():
    assert "spends money" in views.welcome_lede(finance=True)
    assert "spends money" not in views.welcome_lede(finance=False)
    assert views.welcome_lede(False).startswith("See who represents you, how they voted and when they meet.")


def test_meetings_say_their_build_date_and_link_each_day(html):
    main = main_of(html)
    assert 'As of <time datetime="2024-12-01">December 1, 2024</time>.' in main
    rows = re.findall(r'<a class="meet-row" href="(today\.html#d-[0-9-]+)"', main)
    assert rows and "data-built-text" not in main
    page = parse(html)
    ids = {n.attrs.get("id") for n in page.walk()}
    assert "meet-stale" in ids and 'href="today.html#day-bodies-h"' in main


def test_meetings_empty_states(tmp_path):
    out = tmp_path / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, today=date(2031, 6, 1))
    main = main_of((out / "index.html").read_text(encoding="utf-8"))
    assert "No meetings from the last four weeks or the next four are in these records." in main
    assert 'class="meet-row"' not in main and 'href="today.html">All meetings, day by day' in main


def test_bid_listings_are_not_meetings_on_the_landing(tmp_path):
    out = tmp_path / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, finance_path=FIN,
          today=date(2026, 10, 14))
    main = main_of((out / "index.html").read_text(encoding="utf-8"))
    assert config.FIN_TEXT["contracts"]["title"] not in re.sub(r'<ul class="doors".*?</ul>\s*</li>\s*</ul>', "", main, flags=re.S).split('id="meet-h"')[1].split('id="search-h"')[0]
    assert "County money" in main and 'href="contracts/index.html"' in main


def test_no_official_is_named_outside_the_seat_list(html):
    main = main_of(html)
    outside = re.sub(r'<details class="district-list".*?</details>', "", main, flags=re.S)
    names = [o["name"] for o in json.loads(FIXTURE.read_text(encoding="utf-8"))["officials"]]
    assert names and not [n for n in names if n in outside]


def test_no_script_fallback_offers_the_list(html):
    main = main_of(html)
    assert '<a href="#wards-districts"><span class="addr-on">Or pick</span><span class="addr-off">Pick</span>' in main
    css = (ROOT / "site" / "static" / "style.css").read_text(encoding="utf-8")
    assert ".landing.has-addr .addr-off { display: none; }" in css and ".addr-on { display: none; }" in css
    assert '<script src="static/landing.js" defer></script>' in html
    assert "<script>" not in html                                           # no inline script (CSP)


# ---- static/landing.js ------------------------------------------------------------------------------------------

def _node():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    return shutil.which("node")


def test_landing_js_moves_passed_rows_to_most_recent():
    probe = ("const L = require(process.argv[1]);"
             "console.log(JSON.stringify([L.split(['2026-11-12','2026-11-20','2026-12-01'], ['2026-11-09','2026-11-05','2026-11-02'], '2026-11-21', 3),"
             " L.split(['2026-12-01'], [], '2026-11-21', 3), L.daysBetween('2026-11-11', '2026-11-14'), L.daysBetween('2026-02-27', '2026-03-02')]))")
    res = subprocess.run([_node(), "-e", probe, str(LANDING_JS)], capture_output=True, text=True, check=True)
    moved, none, three, leap = json.loads(res.stdout)
    assert moved["upcoming"] == [2]
    assert moved["recent"] == [{"from": "up", "i": 1}, {"from": "up", "i": 0}, {"from": "recent", "i": 0}]
    assert none == {"upcoming": [0], "recent": []}
    assert three == 3 and leap == 3


def test_landing_js_reads_today_from_date_parts_in_the_site_zone():
    probe = ("const L = require(process.argv[1]);"
             "console.log(JSON.stringify([L.todayIn('America/Chicago', new Date('2026-11-12T05:30:00Z')),"
             " L.todayIn('America/Chicago', new Date('2026-11-12T06:30:00Z'))]))")
    res = subprocess.run([_node(), "-e", probe, str(LANDING_JS)], capture_output=True, text=True, check=True)
    assert json.loads(res.stdout) == ["2026-11-11", "2026-11-12"]


def _browser_ok():
    return bool(shutil.which("node")) and (os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright")))


ROW = ('<li data-iso="{iso}"{hidden}><a class="meet-row" href="today.html#d-{iso}"><span class="meet-what">Body</span>'
       '{chip}</a></li>')


def _row(iso, chip=None, hidden=False):
    return ROW.format(iso=iso, hidden=" hidden" if hidden else "",
                      chip=f'<span class="chip chip-status" data-chip="{chip}">{chip}</span>' if chip else "")


def _render(tmp_path, up, recent, now):
    """The landing's meetings section as index.html.j2 builds it (built 2026-11-11, n 3), landing.js run at `now`."""
    html = (f'<!doctype html><section class="meetings" id="meetings" data-built="2026-11-11" data-tz="America/Chicago" '
            f'data-n="3"><p id="meet-stale" hidden>stale</p><ul id="meet-up"{"" if up else " hidden"}>{"".join(up)}</ul>'
            f'<p id="meet-up-empty"{" hidden" if up else ""}>none</p><ul id="meet-recent"{"" if recent else " hidden"}>'
            f'{"".join(recent)}</ul><p id="meet-recent-empty"{" hidden" if recent else ""}>none</p></section>'
            f'<script src="{LANDING_JS.as_uri()}"></script>')
    f = tmp_path / "p.html"
    f.write_text(html, encoding="utf-8")
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    res = subprocess.run(["node", str(ROOT / "tests" / "landing_render_browser.js"), str(f), now],
                         capture_output=True, text=True, timeout=120, env=env)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_render_moves_passed_rows_refills_from_spares_and_drops_scheduled(tmp_path):
    up = [_row("2026-11-12", "Scheduled"), _row("2026-11-16", "Agenda"), _row("2026-11-19", "Scheduled"),
          _row("2026-12-01", "Scheduled", hidden=True), _row("2026-12-03", hidden=True)]
    recent = [_row("2026-11-09", "Agenda"), _row("2026-11-05", "Votes"), _row("2026-11-02")]
    # read on Nov 11 (the build day): nothing moves, spares stay hidden
    same = _render(tmp_path, up, recent, "2026-11-11T20:00:00Z")
    assert same["up"] == ["2026-11-12 Scheduled", "2026-11-16 Agenda", "2026-11-19 Scheduled"] and not same["stale"]
    # Nov 17 in Clarksville: two rows moved (Scheduled dropped, Agenda kept), two spares shown, the build 6 days old
    late = _render(tmp_path, up, recent, "2026-11-17T18:00:00Z")
    assert late["up"] == ["2026-11-19 Scheduled", "2026-12-01 Scheduled", "2026-12-03"]
    assert late["recent"] == ["2026-11-16 Agenda", "2026-11-12", "2026-11-09 Agenda"]
    assert late["stale"] and late["upList"] and not late["upEmpty"]
    # after every upcoming day: the list is hidden and the empty line shows
    gone = _render(tmp_path, up, recent, "2026-12-10T18:00:00Z")
    assert gone["up"] == [] and not gone["upList"] and gone["upEmpty"]
    assert gone["recent"] == ["2026-12-03", "2026-12-01", "2026-11-19"]
    # nothing recent at build time: the moved row fills it and the empty line goes
    only = _render(tmp_path, up[:1], [], "2026-11-13T18:00:00Z")
    assert only["recent"] == ["2026-11-12"] and not only["recEmpty"] and only["upEmpty"]
