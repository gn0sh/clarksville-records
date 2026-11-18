"""The school board's official video links (collector/school_videos.py, Brian 2026-11-18): the channel's RSS feed is
the one URL read, robots.txt first, through a fetcher that allows www.youtube.com alone; only board-meeting titles
that fit the pattern whole are kept; the feed wins over the config's known list. A hand-written feed, no network."""
import json
from pathlib import Path

import pytest

from collector import school_videos as sv
from collector.fetch import ALLOWED_HOSTS, HostRefused
from collector.tests.test_fetch import Clock, FakeNet

FEED = (Path(__file__).parent / "fixtures" / "school_videos" / "feed.xml").read_bytes()
CFG = sv.load_config()
ROBOTS = "https://www.youtube.com/robots.txt"


def fetcher(routes):
    net, clock = FakeNet(routes), Clock()
    f = sv.feed_fetcher()
    f.opener, f.clock, f.sleep, f.proxy_failures = net, clock.now, clock.sleep, (lambda: [])
    return f, net


def test_config_pins_the_feed_the_channel_and_well_formed_known_ids():
    assert CFG["feed_url"] == "https://www.youtube.com/feeds/videos.xml?channel_id=UC7te1VFbkqSPY48oUiQB7mQ"
    assert CFG["channel_url"] == "https://www.youtube.com/@CMCSSFocus" and CFG["body"] == "school-board"
    assert len(CFG["known"]) == 31 and all(sv.VIDEO_ID.fullmatch(k["id"]) for k in CFG["known"])
    assert {k["what"] for k in CFG["known"]} == set(sv.WHATS)
    # YouTube never joins the shared allowlist: only this step's own fetcher may reach it
    assert not any("youtube" in h for h in ALLOWED_HOSTS)
    assert sv.feed_fetcher().allowed_hosts == ("www.youtube.com",)


@pytest.mark.parametrize("change, why", [
    ({"feed_url": "https://www.youtube.com/youtubei/v1/browse?channel_id=UC7te1VFbkqSPY48oUiQB7mQ"}, "feed_url"),
    ({"feed_url": "http://www.youtube.com/feeds/videos.xml?channel_id=UC7te1VFbkqSPY48oUiQB7mQ"}, "feed_url"),
    ({"feed_url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCxxxxxxxxxxxxxxxxxxxxxx"}, "feed_url"),
    ({"channel_url": "https://www.cmcss.net/"}, "channel_url"),
    ({"known": [{"date": "2026-13-01", "id": "bmfHTL6mAeE", "what": "meeting"}]}, "known"),
    ({"known": [{"date": "2026-01-13", "id": "short", "what": "meeting"}]}, "known"),
    ({"known": [{"date": "2026-01-13", "id": "bmfHTL6mAeE", "what": "meeting"}] * 2}, "twice"),
    ({"title_pattern": "^CMCSS (?P<what>Meeting)$"}, "groups"),
])
def test_a_bad_config_is_refused(tmp_path, change, why):
    import yaml
    raw = yaml.safe_load(sv.CONFIG.read_text(encoding="utf-8"))
    p = tmp_path / "v.yml"
    p.write_text(yaml.safe_dump({**raw, **change}), encoding="utf-8")
    with pytest.raises(sv.ConfigError, match=why):
        sv.load_config(p)


@pytest.mark.parametrize("title, want", [
    ("CMCSS School Board Meeting 11-17-2026", ("2026-11-17", "meeting")),
    ("CMCSS School Board Meeting 1-13-2026", ("2026-01-13", "meeting")),
    ("cmcss school board  study session 1-13-2026", ("2026-01-13", "meeting")),
    ("CMCSS School Board Public Hearing 9-1-2026", ("2026-09-01", "hearing")),
    ("CMCSS School Board Budget Hearing 4-22-2025", ("2025-04-22", "budget-hearing")),
    ("CMCSS School Board Meeting 11-17-2026 Part 2", None),     # whole title only, no fuzzy matching
    ("CMCSS Board Meeting 11-17-2026", None),                   # must name the school board
    ("School Board Meeting 11-17-2026", None),
    ("CMCSS School Board Meeting 11-17-26", None),              # four-digit year as the channel prints it
    ("CMCSS School Board Meeting 2-30-2026", None),             # not a real date
    ("Graduation 2026", None),
])
def test_title_must_fit_the_pattern_whole(title, want):
    assert sv.read_title(CFG, title) == want


def test_parse_feed_keeps_only_this_channels_board_titles():
    got = sv.parse_feed(FEED, CFG)
    assert [(v["id"], v["date"], v["what"]) for v in got] == [("FIXTUREvid1", "2024-11-26", "meeting"),
                                                             ("FIXTUREhrg2", "2024-11-26", "hearing")]
    assert got[0] == {"id": "FIXTUREvid1", "title": "CMCSS School Board Meeting 11-26-2024", "date": "2024-11-26",
                      "what": "meeting", "published": "2024-11-27T02:10:00+00:00"}
    # a title that does not fit is never kept (it can name a person)
    assert "Person Name" not in json.dumps(got) and "FIXTUREnot3" not in json.dumps(got)


@pytest.mark.parametrize("body, why", [
    (b'<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY x "y">]><feed xmlns="http://www.w3.org/2005/Atom"/>', "DTD"),
    (b"<html><body>consent</body></html>", "Atom"),
    (b"not xml", "XML"),
    (FEED.replace(b"<yt:channelId>UC7te1VFbkqSPY48oUiQB7mQ</yt:channelId>\n <title>CMCSS Focus",
                  b"<yt:channelId>UCxxxxxxxxxxxxxxxxxxxxxx</yt:channelId>\n <title>CMCSS Focus"), "channel"),
])
def test_a_body_that_is_not_the_feed_is_refused(body, why):
    with pytest.raises(sv.FeedError, match=why):
        sv.parse_feed(body, CFG)


def test_merge_keeps_what_left_the_feed_and_the_feed_wins_by_id():
    old = [{"id": "OLDvideo001", "title": "CMCSS School Board Meeting 1-2-2024", "date": "2024-01-02", "what": "meeting",
            "published": ""}, {"id": "FIXTUREvid1", "title": "x", "date": "2024-11-25", "what": "meeting"}]
    got = sv.merge(old, sv.parse_feed(FEED, CFG))
    assert [v["id"] for v in got] == ["OLDvideo001", "FIXTUREhrg2", "FIXTUREvid1"]
    assert next(v for v in got if v["id"] == "FIXTUREvid1")["date"] == "2024-11-26"


def test_by_date_feed_wins_over_known_and_says_so():
    cfg = {**CFG, "known": [{"date": "2024-11-26", "id": "KNOWNvid001", "what": "meeting"},   # another id that day
                            {"date": "2024-11-20", "id": "FIXTUREhrg2", "what": "hearing"},   # the feed has another date
                            {"date": "2024-11-26", "id": "KNOWNhrg002", "what": "budget-hearing"},
                            {"date": "2024-08-06", "id": "KNOWNvid003", "what": "meeting"}]}
    data = {"videos": sv.parse_feed(FEED, CFG) + [{"id": "HANDedit001", "title": "Student Spotlight 1-1-2024",
                                                   "date": "2024-01-01", "what": "meeting"}]}
    links, problems = sv.by_date(cfg, data)
    assert {d: [(v["id"], v["what"], v["source"]) for v in vs] for d, vs in links.items()} == {
        "2024-08-06": [("KNOWNvid003", "meeting", "known")],
        "2024-11-26": [("FIXTUREvid1", "meeting", "feed"), ("FIXTUREhrg2", "hearing", "feed"),
                       ("KNOWNhrg002", "budget-hearing", "known")]}
    assert links["2024-08-06"][0]["url"] == "https://www.youtube.com/watch?v=KNOWNvid003"
    assert len(problems) == 3
    assert any("KNOWNvid001" in p and "FIXTUREvid1" in p for p in problems)
    assert any("FIXTUREhrg2" in p and "2024-11-26" in p for p in problems)
    assert any("HANDedit001" in p for p in problems)        # a hand-edited entry that does not fit links nothing


def _cfg_in(tmp_path):
    return {**CFG, "facts": str(tmp_path / "videos.json")}


def test_robots_disallow_means_the_feed_is_never_requested_and_nothing_is_written(tmp_path):
    f, net = fetcher({ROBOTS: (200, b"User-agent: *\nDisallow: /feeds/videos.xml\n")})
    log = {}
    assert sv.run_step(log, False, fetcher=f, cfg=_cfg_in(tmp_path), root=tmp_path) == 2
    assert [u for u, _ in net.calls] == [ROBOTS]
    assert "robots.txt disallows" in log["school_videos"]["status"]
    assert not (tmp_path / "videos.json").exists()


def test_the_feed_is_read_once_with_our_user_agent_and_written_sorted(tmp_path):
    f, net = fetcher({ROBOTS: (200, b"User-agent: *\nDisallow: /youtubei/\n"), CFG["feed_url"]: (200, FEED)})
    log = {}
    assert sv.run_step(log, False, fetcher=f, cfg=_cfg_in(tmp_path), root=tmp_path) == 0
    assert [u for u, _ in net.calls] == [ROBOTS, CFG["feed_url"]]
    assert all("clarksville-records" in (ua or "") for _, ua in net.calls)
    data = json.loads((tmp_path / "videos.json").read_text(encoding="utf-8"))
    assert data["schema"] == sv.SCHEMA and [v["id"] for v in data["videos"]] == ["FIXTUREhrg2", "FIXTUREvid1"]
    assert "rewritten" in log["school_videos"]["status"]
    f2, _ = fetcher({ROBOTS: (200, b""), CFG["feed_url"]: (200, FEED)})
    sv.run_step(log, False, fetcher=f2, cfg=_cfg_in(tmp_path), root=tmp_path)
    assert "unchanged" in log["school_videos"]["status"]


@pytest.mark.parametrize("routes, code", [
    ({CFG["feed_url"]: (403, b"")}, 2),                       # the site said no: stopped, never retried
    ({CFG["feed_url"]: (404, b"")}, 2),
    ({CFG["feed_url"]: (200, b"<html>consent</html>")}, 3),
    ({CFG["feed_url"]: (302, b"", {"Location": "https://consent.youtube.com/m?continue=x"})}, 2),   # off the host
])
def test_a_failure_leaves_the_committed_file_exactly_as_it_was(tmp_path, routes, code):
    p = tmp_path / "videos.json"
    p.write_text('{"schema": "school-board-videos-1", "videos": []}\n', encoding="utf-8")
    before = p.read_bytes()
    f, net = fetcher({ROBOTS: (404, b""), **routes})
    log = {}
    assert sv.run_step(log, False, fetcher=f, cfg=_cfg_in(tmp_path), root=tmp_path) == code
    assert p.read_bytes() == before
    assert not any("consent.youtube.com" in u for u, _ in net.calls)


def test_only_youtube_is_allowed_and_the_cap_holds():
    f, net = fetcher({ROBOTS: (404, b""), CFG["feed_url"]: (200, FEED)})
    with pytest.raises(HostRefused):
        f.get("https://www.cmcss.net/")
    for _ in range(3):
        f.get(CFG["feed_url"])
    from collector.fetch import RequestCapReached
    with pytest.raises(RequestCapReached):
        f.get(CFG["feed_url"])
    assert len(net.calls) == sv.FEED_FETCH_CAP


def test_offline_reads_nothing(tmp_path):
    log = {}
    assert sv.run_step(log, True, cfg=_cfg_in(tmp_path), root=tmp_path) == 0
    assert "offline" in log["school_videos"]["status"] and not (tmp_path / "videos.json").exists()
