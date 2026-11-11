"""Official meeting video, "Watch" links (Brian, 2026-11-11; sitegen/watch.py): one link per body from config/site.yml
`video:`, https only, never fetched; a body without an entry shows none; day cards, body pages, county meeting pages
and every morning-note entry about a meeting carry it."""
import html
import json
import re

import pytest

from conftest import ROOT
from qa import site_checks
from sitegen import config, watch
from sitegen.build import site_url_problems
from test_council_pages import cfg as council_cfg, city_facts, city_wards  # noqa: F401  (module fixtures, reused)
from test_morning import D, inputs, make  # noqa: F401  (inputs: the module fixture, reused)
from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS
from sitegen.build import build

WATCH = re.compile(r'<a class="watch" data-ext="(watch|video)" href="([^"]+)"[^>]*>([^<]+)<span class="sr-only">'
                   r' \(opens in a new tab\)</span></a> <span class="watch-note">([^<]+)</span>')


@pytest.fixture(scope="module")
def site(inputs, tmp_path_factory):  # noqa: F811
    out = tmp_path_factory.mktemp("watch") / "build" / "site"
    make(inputs, out)
    return out


def links(page: str) -> list[tuple[str, ...]]:
    return [tuple(html.unescape(x) for x in m) for m in WATCH.findall(page)]


def test_config_entries_are_https_and_the_three_official_streams():
    v = config.SITE["video"]
    assert set(v) == {config.SITE["county_key"], "city", "rpc"}
    assert all(e["url"].startswith("https://") for e in v.values())
    assert v["city"]["url"] == "https://clarksvilletn.portal.civicclerk.com/"
    assert v["county"]["url"] == "https://www.youtube.com/channel/UColCy-INQM4uZSqrJCeHTGg"
    assert v["rpc"]["url"] == "https://www.youtube.com/@CMCRPC"
    assert watch.problems(config.SITE) == [] and not [p for p in site_url_problems(config.SITE) if "video" in p]
    w = watch.body("rpc")
    assert w == {"url": v["rpc"]["url"], "link": "Watch", "label": "Official video (opens YouTube)", "ext": "watch"}


@pytest.mark.parametrize("bad", [{"url": "http://www.youtube.com/@CMCRPC", "host": "YouTube"},
                                 {"url": "javascript:alert(1)", "host": "YouTube"},
                                 {"url": "https://www.youtube.com/@CMCRPC", "host": ""}, "https://x.example/"])
def test_a_bad_entry_is_refused_and_never_linked(bad):
    cfg = {**config.SITE, "video": {**config.SITE["video"], "rpc": bad}}
    assert any(p.startswith("video.rpc") for p in watch.problems(cfg))
    assert any(p.startswith("video.rpc") for p in site_url_problems(cfg))
    assert watch.body("rpc", cfg) is None


def test_a_body_without_an_entry_has_no_link():
    assert watch.body("no-such-body") is None and watch.meeting(None) is None
    cfg = {k: v for k, v in config.SITE.items() if k != "video"}
    assert watch.body("rpc", cfg) is None and watch.problems(cfg) == []


def test_a_meeting_recording_is_used_only_when_video_ok():
    rec = "https://cpmedia.azureedge.net/stream/CLARKSVILLETN/abc.mp4"
    assert watch.meeting("city", rec) == {**watch.body("city"), "url": rec, "ext": "video",
                                          "label": config.SITE["video_recording"]}
    for bad in ("https://elsewhere.example/a.mp4", "http://cpmedia.azureedge.net/a.mp4", "stream/CLARKSVILLETN/a.mp4"):
        assert watch.meeting("city", bad) == watch.body("city")


def test_body_pages_and_day_cards_show_watch_from_config(site):
    v = config.SITE["video"]
    for rel, key in (("meetings.html", "county"), ("rpc/index.html", "rpc")):
        got = links((site / rel).read_text(encoding="utf-8"))
        assert got == [("watch", v[key]["url"], "Watch", f"Official video (opens {v[key]['host']}).")], rel
    meeting = next((site / "meetings").glob("*.html")).read_text(encoding="utf-8")
    assert links(meeting) == [("watch", v["county"]["url"], "Watch", "Official video (opens YouTube).")]
    today = (site / "today.html").read_text(encoding="utf-8")
    cards = re.findall(r'<article class="day-card day-card-(\w+)".*?</article>', today, re.S)
    assert cards
    for kind, body in re.findall(r'<article class="day-card day-card-(\w+)"(.*?)</article>', today, re.S):
        got = links(body)
        if kind == "bids":
            assert got == []
        else:
            assert len(got) == 1 and got[0][1] in {x["url"] for x in v.values()} | _recordings(site), kind


def _recordings(site) -> set[str]:
    return set()   # the fixture council meetings carry no video_url


def test_every_watch_link_on_the_site_is_https_and_from_config(site):
    urls = {x["url"] for x in config.SITE["video"].values()}
    allowed = site_checks.allowed_external(config.SITE, None, None)
    assert urls <= allowed and "watch" in site_checks.EXT_KINDS
    n = 0
    for p in site.rglob("*.html"):
        for ext, href, *_ in links(p.read_text(encoding="utf-8")):
            n += 1
            assert href.startswith("https://") and (href in urls if ext == "watch" else True), (p, href)
    assert n > 5


def test_without_an_entry_a_body_shows_no_watch(inputs, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setitem(config.SITE, "video", {k: v for k, v in config.SITE["video"].items() if k != "rpc"})
    out = tmp_path / "site"
    make(inputs, out)
    rpc_url = "https://www.youtube.com/@CMCRPC"
    assert links((out / "rpc" / "index.html").read_text(encoding="utf-8")) == []
    assert not [p for p in out.rglob("*.html") if rpc_url in p.read_text(encoding="utf-8")]
    note = json.loads((out / "morning" / f"{D.isoformat()}.json").read_text(encoding="utf-8"))
    assert all(e["watch"] is None for e in note["entries"] if e["body"] == "rpc")
    assert links((out / "meetings.html").read_text(encoding="utf-8"))   # the others keep theirs


def test_morning_note_entries_carry_the_watch_link(site):
    v = config.SITE["video"]
    note = json.loads((site / "morning" / f"{D.isoformat()}.json").read_text(encoding="utf-8"))
    assert note["entries"]
    for e in note["entries"]:
        if e["meeting_date"] is None:
            assert e["watch"] is None, e["id"]
        else:
            assert e["watch"] == watch.body(e["body"]), e["id"]
            assert e["watch"] is None or e["watch"]["url"] == v[e["body"]]["url"]
    assert {e["body"] for e in note["entries"] if e["watch"]} >= {"county", "rpc"}
    preview = (site / "morning" / "index.html").read_text(encoding="utf-8")
    shown = re.findall(r'<p class="mn-watch">(.*?)</p>', preview)
    assert shown and all(links(x) for x in shown)


def test_no_video_url_or_host_is_hard_coded_outside_config():
    for e in config.SITE["video"].values():
        host = re.sub(r"^https://", "", e["url"]).split("/")[0]
        for path in [*(ROOT / "sitegen").glob("*.py"), *(ROOT / "site" / "templates").glob("*.j2"),
                     ROOT / "collector" / "fetch.py"]:
            assert e["url"] not in path.read_text(encoding="utf-8"), path
        assert host not in (ROOT / "collector" / "fetch.py").read_text(encoding="utf-8")   # nothing fetches it
    assert "youtube" not in " ".join(p.read_text(encoding="utf-8").lower()
                                     for p in (ROOT / "site" / "templates").glob("*.j2"))


@pytest.fixture(scope="module")
def csite(tmp_path_factory, council_cfg):  # noqa: F811
    out = tmp_path_factory.mktemp("watch-city") / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, councils=[council_cfg])
    return out


def test_council_home_and_a_card_with_its_own_recording(csite, council_cfg, city_facts):  # noqa: F811
    v = config.SITE["video"]["city"]
    home = links((csite / "city" / "index.html").read_text(encoding="utf-8"))
    assert home == [("watch", v["url"], "Watch", f"Official video (opens {v['host']}).")]
    # a day card: a meeting whose facts carry a video_url video_ok allows links that recording, else the portal
    from sitegen import council, days
    cix = council.load(council_cfg, city_facts, [])
    m = city_facts["meetings"][0]
    rec = "https://cpmedia.azureedge.net/clarksvilletn/d5c3649fe7.mp4"
    assert days.council_card(cix, {**m, "video_url": rec})["watch"]["url"] == rec
    assert days.council_card(cix, {**m, "video_url": None})["watch"] == watch.body("city")
    assert days.council_card(cix, {**m, "video_url": "https://elsewhere.example/a.mp4"})["watch"] == watch.body("city")
