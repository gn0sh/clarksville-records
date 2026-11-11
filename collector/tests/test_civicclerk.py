"""CivicClerk source (M4 slice 3, ADR 0003): config, events listing, paging, de-duplication with the Agenda Center."""
import json

import pytest
import yaml

from collector import agenda_center as ac
from collector import civicclerk as cc
from collector.city_run import cmd_fetch_civicclerk, new_log
from collector.fetch import ALLOWED_HOSTS, DENIED_HOSTS, FetchFailed, HostBlocked, PoliteFetcher
from collector.store import Store

API = "https://clarksvilletn.api.civicclerk.com"


@pytest.fixture(scope="module")
def cfg():
    return cc.load_config()


@pytest.fixture(scope="module")
def acfg():
    return ac.load_config()


def event(eid, start, name, files=(), mp4="", category="City Council", **kw):
    """An event in the API's own shape (fields as the live API printed them on 2026-11-09, trimmed)."""
    return {"id": eid, "eventName": name, "startDateTime": start, "eventDate": start, "categoryName": category,
            "agendaId": kw.get("agendaId", 0), "hasAgenda": bool(files), "hasMedia": bool(mp4),
            "isDeleted": kw.get("isDeleted", False), "mediaSourcePathMp4": mp4,
            "publishedFiles": [{"id": 0, "fileId": fid, "type": t, "name": n, "publishOn": pub,
                                "url": f"stream/CLARKSVILLETN/{fid}.pdf", "fileType": 1} for fid, t, n, pub in files]}


JAN4 = event(91, "2024-01-04T18:00:00Z", "Regular Session",
             [(1860, "Agenda", "January 4, 2024 Regular Session Agenda", "2024-01-02T12:50:31.25Z"),
              (1905, "Minutes", "1/4/24 Minutes", "2024-02-09T09:45:55.94Z")],
             "https://cpmedia.azureedge.net/clarksvilletn/d5c3649fe7.mp4")
WORK = event(1765, "2024-02-22T16:30:00Z", "City Council Special Work Session",
             [(1921, "Agenda", "2-22-24 Special Work Session Agenda", "2024-02-20T10:00:00Z")],
             "stream/CLARKSVILLETN/bbc37593-4bdb-4564-848e-a8de4e26d460.mp4")
NOFILES = event(1821, "2024-04-01T17:00:00Z", "Joint City/County Workshop (Comprehensive Plan)")
OLD = event(2044, "2013-01-03T18:00:00Z", "Regular Session", mp4="stream/CLARKSVILLETN/086e.mp4")
OTHER = event(5, "2024-01-09T17:00:00Z", "Regular Meeting", category="Planning Commission")


# ------------------------------------------------------------------ config
def test_config_loads_and_urls_stay_on_the_api_host(cfg):
    assert cfg.api_host == "clarksvilletn.api.civicclerk.com" and cfg.category_name == "City Council"
    assert cfg.first_url().startswith(API + "/v1/Events?$filter=categoryName%20eq%20%27City%20Council%27")
    assert "startDateTime%20ge%202024-01-01T00:00:00Z" in cfg.first_url()
    assert cfg.file(1905) == API + "/v1/Meetings/GetMeetingFileStream(fileId=1905,plainText=false)"


@pytest.mark.parametrize("key,value,match", [
    ("file_url", "https://evil.example/{file_id}", "api_host"),
    ("events_url", "http://{host}/v1/Events", "api_host"),
    ("from_date", "2024", "YYYY-MM-DD"),
    ("agenda_types", [], "list of strings"),
])
def test_config_rejects_bad_values(key, value, match):
    raw = yaml.safe_load(cc.config_path().read_text())
    raw[key] = value
    with pytest.raises(cc.CivicClerkConfigError, match=match):
        cc.parse_config(raw)


def test_only_the_api_host_is_allowed():
    assert "clarksvilletn.api.civicclerk.com" in ALLOWED_HOSTS
    assert "civicclerk.com" not in ALLOWED_HOSTS                 # not the portal or other tenants
    f = PoliteFetcher()
    with pytest.raises(Exception, match="allowlist"):
        f.check_host("clarksvilletn.portal.civicclerk.com")
    assert "cityofclarksville.com" in DENIED_HOSTS


# ------------------------------------------------------------------ events
def test_parse_events_rows_as_printed(cfg, acfg):
    rows, problems = cc.parse_events({"value": [OLD, JAN4, WORK, NOFILES, OTHER]}, cfg, acfg.kind_of)
    assert [r["event_id"] for r in rows] == [91, 1765, 1821]      # before from_date and other boards left out
    r = rows[0]
    assert r["date"] == "2024-01-04" and r["kind"] == "regular" and r["source"] == "civicclerk"
    assert r["agenda_id"] == "cc-91"
    assert r["agenda_url"] == cfg.file(1860) and r["minutes_url"] == cfg.file(1905)
    assert r["video_url"] == "https://cpmedia.azureedge.net/clarksvilletn/d5c3649fe7.mp4"
    assert rows[1]["kind"] == "work-session" and rows[1]["minutes_url"] is None
    assert rows[2]["agenda_url"] is None and rows[2]["minutes_url"] is None


@pytest.mark.parametrize("title,kind", [
    ("Regular Session", "regular"), ("City Council Regular Session", "regular"), ("Executive Session", "executive"),
    ("City Council Special Work Session", "work-session"), ("City Council - Special Session", "special"),
    ("Special Session - 2nd Reading of the Budget", "special"), ("Budget Workshop", "work-session"),
    ("Ethics Code Review Special Called Meeting", "committee"),      # as the Agenda Center's Ethics Code Review
    ("Restoring Clarksville", "other"),
])
def test_civicclerk_titles_get_the_agenda_center_kinds(acfg, title, kind):
    assert acfg.kind_of(title) == kind


def test_date_is_taken_as_printed_not_converted(cfg, acfg):
    late = event(7, "2024-03-07T23:30:00Z", "Regular Session", [(1, "Agenda", "a", "")])
    rows, _ = cc.parse_events({"value": [late]}, cfg, acfg.kind_of)
    assert rows[0]["date"] == "2024-03-07"


def test_bare_storage_video_path_is_not_guessed(cfg, acfg):
    rows, problems = cc.parse_events({"value": [WORK]}, cfg, acfg.kind_of)
    assert rows[0]["video_url"] is None
    assert problems == [{"event": 1765, "date": "2024-02-22", "problem": "video path is not a public URL: not kept",
                         "snippet": WORK["mediaSourcePathMp4"]}]


@pytest.mark.parametrize("mp4", ["http://cpmedia.azureedge.net/clarksvilletn/a.mp4",
                                 "https://other.example/clarksvilletn/a.mp4",
                                 "https://cpmedia.azureedge.net/clarksvilletn/a.m3u8"])
def test_video_only_https_mp4_on_a_configured_host(cfg, mp4):
    assert cc.video_url({"mediaSourcePathMp4": mp4}, cfg) is None


def test_newest_minutes_file_is_used_and_reported(cfg, acfg):
    e = event(9, "2024-05-02T18:00:00Z", "Regular Session",
              [(10, "Minutes", "Minutes", "2024-05-20T00:00:00Z"), (12, "Minutes", "Amended", "2024-06-01T00:00:00Z"),
               (11, "Agenda Packet", "Packet", "2024-04-30T00:00:00Z")])
    rows, problems = cc.parse_events({"value": [e]}, cfg, acfg.kind_of)
    assert rows[0]["minutes_url"] == cfg.file(12) and rows[0]["agenda_url"] is None     # a packet is not the agenda
    assert problems[0]["problem"] == "2 minutes files published; the newest is used"


def test_deleted_events_and_events_without_a_date_are_left_out(cfg, acfg):
    gone = event(3, "2024-02-01T18:00:00Z", "Regular Session", isDeleted=True)
    bad = {**event(4, "", "Regular Session")}
    rows, problems = cc.parse_events({"value": [gone, bad]}, cfg, acfg.kind_of)
    assert rows == [] and problems[0]["problem"] == "event without a date, name or id"


def test_a_page_without_value_fails_loudly(cfg, acfg):
    with pytest.raises(cc.EventsError):
        cc.parse_events({"error": "x"}, cfg, acfg.kind_of)


# ------------------------------------------------------------------ paging
CFG = cc.load_config()
ALSO = CFG.also_url(CFG.also_list[0])        # D1: the "General" / "Special Session" listing, empty unless a test fills it


class Pages:
    def __init__(self, pages, fail=()):
        self.pages, self.fail, self.calls, self.log = {ALSO: {"value": []}, **pages}, set(fail), [], []

    def get(self, url):
        self.calls.append(url)
        if url in self.fail:
            raise FetchFailed(f"{url}: reset")
        if url not in self.pages:
            return 404, b"", {}
        b = self.pages[url]
        return 200, b if isinstance(b, bytes) else json.dumps(b).encode(), {}


def test_discover_follows_next_links_and_caches_each_page(cfg, acfg, tmp_path):
    nxt = cfg.first_url() + "&$skiptoken=startDateTime-2024-02-22T16%3A30%3A00Z,id-1765"
    f = Pages({cfg.first_url(): {"value": [JAN4, WORK], "@odata.nextLink": nxt},
               nxt: {"value": [WORK, NOFILES]}})
    log = {}
    rows = cc.discover(f, cfg, acfg.kind_of, log, tmp_path / "cache")
    assert f.calls == [cfg.first_url(), nxt, ALSO]
    assert [r["event_id"] for r in rows] == [91, 1765, 1821]        # an event on two pages is kept once
    assert len(list((tmp_path / "cache").glob("*.json"))) == 3
    assert [p["rows"] for p in log["listings"]] == [2, 2, 0]


def test_next_link_off_the_api_host_stops(cfg, acfg, tmp_path):
    f = Pages({cfg.first_url(): {"value": [], "@odata.nextLink": "https://elsewhere.example/v1/Events?x"}})
    with pytest.raises(cc.EventsError, match="leaves the API host"):
        cc.discover(f, cfg, acfg.kind_of, {}, tmp_path)


def test_non_200_and_non_json_fail_loudly(cfg, acfg, tmp_path):
    with pytest.raises(cc.EventsError, match="HTTP 404"):
        cc.discover(Pages({}), cfg, acfg.kind_of, {}, tmp_path)
    with pytest.raises(cc.EventsError, match="not JSON"):
        cc.discover(Pages({cfg.first_url(): b"<html>"}), cfg, acfg.kind_of, {}, tmp_path)


def test_fetch_step_writes_listing_then_minutes_and_agendas(cfg, acfg, tmp_path):
    f = Pages({cfg.first_url(): {"value": [JAN4, WORK, NOFILES]},
               cfg.file(1905): b"%PDF-1.7 minutes", cfg.file(1860): b"%PDF-1.7 agenda", cfg.file(1921): b"%PDF a"})
    store = Store(manifest_path=tmp_path / "m.json", root=tmp_path / "s")
    log = new_log()
    rows = cmd_fetch_civicclerk(cfg, acfg.kind_of, store, tmp_path / "l.json", log, fetcher=f, agendas=True,
                                cache_dir=tmp_path / "c")
    assert len(rows) == 3 and json.loads((tmp_path / "l.json").read_text())[0]["event_id"] == 91
    assert log["fetched"] == {"new": 3} and not log["failures"]
    assert store.latest(cfg.file(1905))["kind"] == "minutes"
    assert store.latest(cfg.file(1905))["meeting_date"] == "2024-01-04"


def test_a_failed_listing_keeps_the_last_listing(cfg, acfg, tmp_path):
    listing = tmp_path / "l.json"
    listing.write_text("[\"kept\"]")
    f = Pages({}, fail=[cfg.first_url()])
    log = new_log()
    assert cmd_fetch_civicclerk(cfg, acfg.kind_of, Store(manifest_path=tmp_path / "m.json", root=tmp_path / "s"),
                                listing, log, fetcher=f, cache_dir=tmp_path / "c") == []
    assert listing.read_text() == "[\"kept\"]" and log["failures"][0]["source"] == "civicclerk"


def test_a_refusal_stops_the_file_fetches(cfg, acfg, tmp_path):
    class Refusing(Pages):
        def get(self, url):
            if "GetMeetingFileStream" in url:
                self.calls.append(url)
                raise HostBlocked("HTTP 429 from the site")
            return super().get(url)

    f = Refusing({cfg.first_url(): {"value": [JAN4, WORK]}})
    log = new_log()
    cmd_fetch_civicclerk(cfg, acfg.kind_of, Store(manifest_path=tmp_path / "m.json", root=tmp_path / "s"),
                         tmp_path / "l.json", log, fetcher=f, agendas=True, cache_dir=tmp_path / "c")
    assert len([u for u in f.calls if "GetMeetingFileStream" in u]) == 1     # never retried
    assert log["fetched"]["not_tried"] == 2


# ------------------------------------------------------------------ de-duplication
def ac_row(date, title, kind, minutes=True, aid="01042024-1"):
    base = "https://www.clarksvilletn.gov/AgendaCenter/ViewFile"
    return {"date": date, "title": title, "kind": kind, "agenda_id": aid, "agenda_url": f"{base}/Agenda/_{aid}",
            "minutes_url": f"{base}/Minutes/_{aid}" if minutes else None, "has_previous_versions": False}


def cc_row(cfg, acfg, e):
    return cc.parse_events({"value": [e]}, cfg, acfg.kind_of)[0][0]


def test_same_date_and_kind_is_one_meeting_from_the_agenda_center(cfg, acfg):
    a = ac_row("2024-01-04", "City Council Regular Session", "regular")
    rows, dups = cc.merge_sources([a], [cc_row(cfg, acfg, JAN4)])
    assert len(rows) == 1 and rows[0]["source"] == "agenda-center" and rows[0]["agenda_id"] == "01042024-1"
    assert rows[0]["video_url"] == JAN4["mediaSourcePathMp4"]                 # the video is carried over
    assert rows[0]["also_listed"][0]["source"] == "civicclerk"
    assert dups == [{"date": "2024-01-04", "kind": "regular", "kept": "agenda-center", "dropped": "civicclerk",
                     "kept_title": a["title"], "dropped_title": "Regular Session"}]


def test_the_listing_with_minutes_wins(cfg, acfg):
    a = ac_row("2024-01-04", "City Council Regular Session", "regular", minutes=False)
    rows, dups = cc.merge_sources([a], [cc_row(cfg, acfg, JAN4)])
    assert len(rows) == 1 and rows[0]["source"] == "civicclerk" and rows[0]["minutes_url"] == cfg.file(1905)
    assert rows[0]["also_listed"][0]["agenda_url"] == a["agenda_url"] and dups[0]["kept"] == "civicclerk"


def test_another_kind_on_the_same_day_is_not_a_duplicate(cfg, acfg):
    a = ac_row("2024-01-04", "Executive Session", "executive")
    rows, dups = cc.merge_sources([a], [cc_row(cfg, acfg, JAN4)])
    assert len(rows) == 2 and dups == [] and {r["source"] for r in rows} == {"agenda-center", "civicclerk"}


def test_one_source_never_merges_its_own_rows(cfg, acfg):
    a1 = ac_row("2024-01-04", "Special Session", "special", aid="01042024-1")
    a2 = ac_row("2024-01-04", "Special Session", "special", aid="01042024-2")
    s1 = event(1, "2024-01-04T16:00:00Z", "Special Session", [(1, "Agenda", "a", "")])
    s2 = event(2, "2024-01-04T17:00:00Z", "Special Session", [(2, "Agenda", "a", "")])
    s3 = event(3, "2024-01-04T18:00:00Z", "Special Session", [(3, "Agenda", "a", "")])
    rows, dups = cc.merge_sources([a1, a2], [cc_row(cfg, acfg, e) for e in (s1, s2, s3)])
    assert len(dups) == 2 and len(rows) == 3                      # two pairs, one CivicClerk meeting left over
    assert [r["source"] for r in rows] == ["agenda-center", "agenda-center", "civicclerk"]


# ------------------------------------------------------------------ build: both sources in one facts file
def test_build_records_each_meetings_source_and_video(cfg, acfg):
    import jsonschema

    from collector.city_build import build
    from collector.city_minutes import parse_text
    from collector.tests.test_city_minutes import PAGE1, PAGE2, SCHEMA, FakeStore, entry, rows_and_store

    rows, _, inspect = rows_and_store()
    c = cc_row(cfg, acfg, event(1408, "2024-02-01T18:00:00Z", "Regular Session",
                                [(1891, "Agenda", "2-1-24 Regular Session Agenda", ""), (2002, "Minutes", "Minutes", "")],
                                "https://cpmedia.azureedge.net/clarksvilletn/d6b27ab504.mp4"))
    merged, dups = cc.merge_sources(rows, [c])
    store = FakeStore([entry(rows[0]["agenda_url"], "agenda", "2019-12-05", 1),
                       entry(rows[0]["minutes_url"], "minutes", "2019-12-05", 2),
                       entry(c["agenda_url"], "agenda", "2024-02-01", 4),
                       entry(c["minutes_url"], "minutes", "2024-02-01", 5)])
    facts, summary = build(acfg, merged, store, parse=lambda p, k: parse_text([PAGE1, PAGE2], k), inspect=inspect)
    jsonschema.validate({k: v for k, v in facts.items() if k != "_wards"}, SCHEMA)
    ms = {m["id"]: m for m in facts["meetings"]}
    assert ms["2019-12-05-regular"]["listing_source"] == "agenda-center" and "video_url" not in ms["2019-12-05-regular"]
    new = ms["2024-02-01-regular"]
    assert new["listing_source"] == "civicclerk" and new["minutes_status"] == "read"
    assert new["video_url"] == "https://cpmedia.azureedge.net/clarksvilletn/d6b27ab504.mp4"
    assert new["minutes_url"] == cfg.file(2002) and new["agenda_url"] == cfg.file(1891)
    bs = summary["by_source"]
    assert bs["civicclerk"]["meetings"] == 1 and bs["civicclerk"]["with_video"] == 1
    assert bs["2024_on"]["roll_calls"] == bs["civicclerk"]["roll_calls"] > 0
    assert bs["agenda-center"]["roll_calls"] + bs["civicclerk"]["roll_calls"] == summary["roll_calls"]
    assert len({r["id"] for r in facts["roll_calls"]}) == len(facts["roll_calls"])


def test_minutes_but_no_agenda_builds_with_a_null_agenda_url(cfg, acfg):
    import jsonschema

    from collector.city_build import build
    from collector.city_minutes import parse_text
    from collector.tests.test_city_minutes import PAGE1, PAGE2, SCHEMA, FakeStore, entry

    c = cc_row(cfg, acfg, event(3, "2024-03-12T17:30:00Z", "City Council Special Session",
                                [(3075, "Minutes", "Minutes", "")]))
    store = FakeStore([entry(c["minutes_url"], "minutes", "2024-03-12", 6)])
    facts, _ = build(acfg, [c], store, parse=lambda p, k: parse_text([PAGE1, PAGE2], k), inspect=lambda p: (2, "text"))
    jsonschema.validate({k: v for k, v in facts.items() if k != "_wards"}, SCHEMA)
    m = facts["meetings"][0]
    assert m["agenda_url"] is None and m["minutes_status"] == "read" and "agenda_source_id" not in m


# ------------------------------------------------------------------ D1: City Council Special Sessions under "General"
# The 2026-02-11 City Council Special Session as CivicClerk lists it (category "General", event "Special Session",
# minutes fileId 3068, agenda 2887; one listing query, 2026-11-11), and another board's special session filed alike.
SPECIAL = event(2900, "2026-02-11T16:30:00Z", "Special Session",
                [(2887, "Agenda", "2-11-26 Special Session Agenda", ""), (3068, "Minutes", "Minutes", "")],
                category="General")
OTHER_SPECIAL = event(2901, "2025-06-10T09:00:00Z", "Special Session",
                      [(2500, "Minutes", "Minutes", "")], category="General")
GENERAL_OTHER = event(2902, "2025-06-11T09:00:00Z", "Budget Retreat", [(2501, "Minutes", "Minutes", "")],
                      category="General")
PAGE1_CITY = ("                                         City of Clarksville\n"
              "                                  City Council - Special Session\n\n"
              "                                         February 11, 2026 at 4:30 PM\n")
PAGE1_OTHER = ("                                         City of Clarksville\n"
               "                           Board of Zoning Appeals - Special Session\n\n"
               "                                         June 10, 2025 at 9:00 AM\n")


def test_config_also_lists_general_special_sessions_on_the_api_host(cfg):
    assert cfg.also_list == ({"category_name": "General", "event_name": "Special Session",
                              "page1": "City Council - Special Session"},)
    assert ALSO.startswith(API + "/v1/Events?$filter=categoryName%20eq%20%27General%27%20and%20eventName%20eq%20"
                                 "%27Special%20Session%27%20and%20startDateTime%20ge%202024-01-01T00:00:00Z")


@pytest.mark.parametrize("also,match", [
    ([{"category_name": "General", "event_name": "Special Session"}], "also_list"),
    ([{"category_name": "General", "event_name": "", "page1": "x"}], "also_list"),
    ("General", "also_list must be a list"),
])
def test_config_rejects_a_bad_also_list(also, match):
    raw = yaml.safe_load(cc.config_path().read_text())
    with pytest.raises(cc.CivicClerkConfigError, match=match):
        cc.parse_config({**raw, "also_list": also})
    with pytest.raises(cc.CivicClerkConfigError, match="also_events_url"):
        cc.parse_config({**raw, "also_events_url": ""})
    with pytest.raises(cc.CivicClerkConfigError, match="api_host"):
        cc.parse_config({**raw, "also_events_url": "https://evil.example/{category}{event}"})


def test_the_also_listing_keeps_only_its_category_and_event_name_and_marks_each_row(cfg, acfg):
    page = {"value": [SPECIAL, OTHER_SPECIAL, GENERAL_OTHER, JAN4]}
    rows, _ = cc.parse_events(page, cfg, acfg.kind_of, cfg.also_list[0])
    assert [r["event_id"] for r in rows] == [2900, 2901]                      # not the retreat, not a council event
    assert all(r["page1_required"] == "City Council - Special Session" for r in rows)
    assert rows[0]["listed_as"] == "General / Special Session" and rows[0]["kind"] == "special"
    assert rows[0]["minutes_url"] == cfg.file(3068) and rows[0]["agenda_url"] == cfg.file(2887)
    main, _ = cc.parse_events(page, cfg, acfg.kind_of)
    assert [r["event_id"] for r in main] == [91] and "page1_required" not in main[0]


def test_discover_asks_the_also_listing_after_the_council_listing(cfg, acfg, tmp_path):
    f = Pages({cfg.first_url(): {"value": [JAN4]}, ALSO: {"value": [SPECIAL, OTHER_SPECIAL]}})
    log = {}
    rows = cc.discover(f, cfg, acfg.kind_of, log, tmp_path / "c")
    assert f.calls == [cfg.first_url(), ALSO]
    assert [r["event_id"] for r in rows] == [91, 2901, 2900]                  # oldest first
    assert [p["url"] for p in log["listings"]] == [cfg.first_url(), ALSO]


def test_a_failed_also_listing_fails_the_listing_and_keeps_the_last_one(cfg, acfg, tmp_path):
    listing = tmp_path / "l.json"
    listing.write_text("[\"kept\"]")
    f = Pages({cfg.first_url(): {"value": [JAN4]}}, fail=[ALSO])
    log = new_log()
    assert cmd_fetch_civicclerk(cfg, acfg.kind_of, Store(manifest_path=tmp_path / "m.json", root=tmp_path / "s"),
                                listing, log, fetcher=f, cache_dir=tmp_path / "c") == []
    assert listing.read_text() == "[\"kept\"]" and log["failures"][0]["stage"] == "listing"


def test_an_also_listed_events_agenda_is_fetched_without_agendas(cfg, acfg, tmp_path):
    f = Pages({cfg.first_url(): {"value": [JAN4]}, ALSO: {"value": [SPECIAL]},
               cfg.file(1905): b"%PDF-1.7 m", cfg.file(3068): b"%PDF-1.7 m2", cfg.file(2887): b"%PDF-1.7 a"})
    store = Store(manifest_path=tmp_path / "m.json", root=tmp_path / "s")
    log = new_log()
    cmd_fetch_civicclerk(cfg, acfg.kind_of, store, tmp_path / "l.json", log, fetcher=f, cache_dir=tmp_path / "c")
    assert store.latest(cfg.file(2887))["kind"] == "agenda"                  # needed for the page-1 check
    assert store.latest(cfg.file(1860)) is None                              # a council agenda still needs --agendas
    assert log["fetched"] == {"new": 3}


def _d1_build(cfg, acfg, events, page1_of):
    from collector.city_build import build
    from collector.city_minutes import parse_text
    from collector.tests.test_city_minutes import PAGE1, PAGE2, FakeStore, entry

    rows = [cc.parse_events({"value": [e]}, cfg, acfg.kind_of, cfg.also_list[0])[0][0] for e in events]
    entries, n = [], 10
    for r in rows:
        for kind in ("agenda", "minutes"):
            if r[f"{kind}_url"]:
                n += 1
                entries.append(entry(r[f"{kind}_url"], kind, r["date"], n))
    sha_page1 = {e["sha256"]: page1_of(e["url"]) for e in entries}
    return build(acfg, rows, FakeStore(entries), parse=lambda p, k: parse_text([PAGE1, PAGE2], k),
                 inspect=lambda p: (3, "text"), pages=lambda p: [sha_page1[p.stem]])


def test_build_keeps_an_also_listed_event_only_when_page_1_prints_the_council(cfg, acfg):
    pages = {cfg.file(3068): PAGE1_CITY, cfg.file(2887): PAGE1_CITY, cfg.file(2500): PAGE1_OTHER}
    facts, summary = _d1_build(cfg, acfg, [SPECIAL, OTHER_SPECIAL], pages.get)
    assert [m["id"] for m in facts["meetings"]] == ["2026-02-11-special"]
    assert facts["meetings"][0]["minutes_url"] == cfg.file(3068)
    assert summary["skipped_events"] == [{
        "date": "2025-06-10", "title": "Special Session", "event_id": 2901, "listed_as": "General / Special Session",
        "reason": "listed as General / Special Session; page 1 of its minutes does not print "
                  "'City Council - Special Session': skipped, not this body's meeting"}]
    assert any(p["problem"] == summary["skipped_events"][0]["reason"] for p in summary["problems"])
    assert not any(s["url"] == cfg.file(2500) for s in facts["sources"])      # nothing of the skipped event is cited


def test_build_reads_the_agenda_when_the_minutes_page_1_does_not_print_it(cfg, acfg):
    pages = {cfg.file(3068): "MINUTES\n", cfg.file(2887): PAGE1_CITY}
    facts, summary = _d1_build(cfg, acfg, [SPECIAL], pages.get)
    assert [m["id"] for m in facts["meetings"]] == ["2026-02-11-special"] and not summary["skipped_events"]
    pages = {cfg.file(3068): "MINUTES\n", cfg.file(2887): PAGE1_OTHER}
    facts, summary = _d1_build(cfg, acfg, [SPECIAL], pages.get)
    assert facts["meetings"] == [] and "page 1 of its minutes or agenda does not print" in \
        summary["skipped_events"][0]["reason"]


def test_build_skips_an_also_listed_event_with_no_stored_file(cfg, acfg):
    from collector.city_build import build

    class Empty:
        def latest(self, url):
            return None

    row = cc.parse_events({"value": [SPECIAL]}, cfg, acfg.kind_of, cfg.also_list[0])[0][0]
    facts, summary = build(acfg, [row], Empty(), inspect=lambda p: (3, "text"), pages=lambda p: [""])
    assert facts["meetings"] == []
    assert "no stored agenda or minutes does not print" in summary["skipped_events"][0]["reason"]
