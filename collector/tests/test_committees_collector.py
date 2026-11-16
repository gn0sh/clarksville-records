"""City committees from CivicClerk (milestone C1, collector/committees.py): the config, the listing as printed, the
fetch into the body's own store, the minutes reader and the build. Fixtures under fixtures/committees/ are excerpts of
the live API pages and minutes files (fetched 2026-11-16, politely), trimmed to the fields the collector reads."""
import json
from pathlib import Path

import pytest
import yaml

from collector import committees as C

FIX = Path(__file__).parent / "fixtures" / "committees"


@pytest.fixture(scope="module")
def cfg():
    return C.load_config()


def page(name: str) -> dict:
    return json.loads((FIX / f"{name}-events-page-excerpt.json").read_text(encoding="utf-8"))


def raw_config() -> dict:
    return yaml.safe_load(C.config_path().read_text(encoding="utf-8"))


# ------------------------------------------------------------------ config
def test_config_lists_finance_and_audit_on_the_api_host(cfg):
    assert [(c.slug, c.category_name, c.label) for c in cfg.committees] == [
        ("finance", "Finance Committee", "Finance Committee"), ("audit", "Audit Committee", "Audit Committee")]
    assert cfg.api_host == "clarksvilletn.api.civicclerk.com" and cfg.from_date == "2019-01-01"
    fin = cfg.by_slug("finance").cc
    assert fin.first_url().startswith("https://clarksvilletn.api.civicclerk.com/v1/Events?$filter=categoryName%20eq"
                                      "%20%27Finance%20Committee%27%20and%20startDateTime%20ge%202019-01-01T00:00:00Z")
    assert fin.file(3197) == ("https://clarksvilletn.api.civicclerk.com/v1/Meetings/GetMeetingFileStream"
                              "(fileId=3197,plainText=false)")
    assert fin.also_list == ()          # the council's General-category rule (D1) is not the committees'


def test_council_config_is_untouched():
    from collector import civicclerk
    cc = civicclerk.load_config()
    assert cc.category_name == "City Council" and cc.from_date == "2024-01-01"


@pytest.mark.parametrize("change, match", [
    ({"committees": []}, "non-empty list"),
    ({"committees": [{"category_name": "Finance Committee", "slug": "finance"}]}, "category_name, slug, label"),
    ({"committees": [{"category_name": "Finance Committee", "slug": "Fin ance", "label": "F"}]}, "slug must"),
    ({"committees": [{"category_name": "A", "slug": "a", "label": "A"},
                     {"category_name": "A", "slug": "b", "label": "B"}]}, "listed twice"),
    ({"api_host": "evil.example.com"}, "ALLOWED_HOSTS"),
    ({"file_url": "https://{host}/v1/file"}, "must name"),
    ({"from_date": "2019"}, "YYYY-MM-DD"),
])
def test_config_rejects_bad_values(change, match):
    raw = {**raw_config(), **change}
    with pytest.raises(C.CommitteesConfigError, match=match):
        C.parse_config(raw)


def test_config_missing_key():
    raw = raw_config()
    del raw["events_url"]
    with pytest.raises(C.CommitteesConfigError, match="missing events_url"):
        C.parse_config(raw)


# ------------------------------------------------------------------ listing
def test_listing_rows_as_printed(cfg):
    rows, problems = C.parse_page(page("finance"), cfg.by_slug("finance"))
    assert [(r["date"], r["title"], r["committee"], r["event_id"]) for r in rows] == [
        ("2019-04-04", "Finance Committee Agenda 4-4-19", "finance", 734),
        ("2019-04-23", "Finance Committee Agenda 4-23-19", "finance", 730),
        ("2019-05-15", "Finance Committee Agenda 5-15-19", "finance", 735)]
    first = rows[0]
    assert first["agenda_url"].endswith("(fileId=996,plainText=false)")
    assert first["minutes_url"].endswith("(fileId=997,plainText=false)")
    assert first["minutes_name"] == "136m-Finance Minutes 4-4-19"
    assert first["body"] == "Finance Committee" and first["source"] == "civicclerk" and not first["cancelled"]
    assert rows[2]["minutes_url"] is None            # 2019-05-15: agenda only
    assert problems == []


def test_listing_keeps_a_cancelled_meeting_and_flags_a_name_with_another_date(cfg):
    rows, problems = C.parse_page(page("audit"), cfg.by_slug("audit"))
    by_id = {r["event_id"]: r for r in rows}
    assert by_id[158]["cancelled"] and by_id[158]["minutes_url"] is None
    # "Audit Committee Agenda 4-24-20" is listed on 2020-04-27: kept as listed, the name's date reported
    assert by_id[161]["date"] == "2020-04-27" and by_id[161]["title_date"] == "2020-04-24"
    assert [(p["event"], p["printed"]) for p in problems if p["problem"] == "event name prints another date"] == [
        (161, "2020-04-24")]
    # the "Agenda Packet" is not an agenda; the bare storage video path is never made a URL
    assert by_id[144]["agenda_url"].endswith("(fileId=118,plainText=false)")
    assert by_id[159]["video_url"] is None
    assert any(p["event"] == 159 and "not a public URL" in p["problem"] for p in problems)


def test_an_event_named_for_another_body_is_kept_and_flagged(cfg):
    pg = page("finance")
    pg["value"][0] = {**pg["value"][0], "eventName": "Public Safety Committee FY25 Budget Review"}
    rows, problems = C.parse_page(pg, cfg.by_slug("finance"))
    assert rows[0]["other_name"] and "other_name" not in rows[1]
    assert [p["event"] for p in problems if p["problem"] == "event name does not name the committee"] == [734]


@pytest.mark.parametrize("title, dates", [
    ("Finance Committee Agenda 4-4-19", ["2019-04-04"]),
    ("Audit Committee Agenda - October 28, 2020", ["2020-10-28"]),
    ("Audit Committee ", []),
    ("Finance Committee Agenda 13-45-19", []),
])
def test_title_dates(title, dates):
    assert C.title_dates(title) == dates


def test_meeting_ids_are_date_and_committee_with_repeats_numbered(cfg):
    fin, _ = C.parse_page(page("finance"), cfg.by_slug("finance"))
    aud, _ = C.parse_page(page("audit"), cfg.by_slug("audit"))
    twin = {**fin[0], "event_id": 999}
    ids = [r["id"] for r in C.assign_ids(aud + fin + [twin])]
    assert ids[:3] == ["2019-01-17-audit", "2019-04-04-finance", "2019-04-04-finance-2"]
    assert len(set(ids)) == len(ids)


class Pages:
    """A fetcher answering each URL from a dict."""

    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url):
        self.urls.append(url)
        return 200, json.dumps(self.pages[url]).encode(), {}


def test_discover_reads_every_committee_and_caches_pages(cfg, tmp_path):
    fin, aud = cfg.by_slug("finance").cc, cfg.by_slug("audit").cc
    nxt = fin.first_url() + "&$skiptoken=x"
    p1 = page("finance")
    p2 = {"value": p1["value"][2:]}
    p1 = {"value": p1["value"][:2], "@odata.nextLink": nxt}
    f = Pages({fin.first_url(): p1, nxt: p2, aud.first_url(): page("audit")})
    log = {}
    rows = C.discover(f, cfg, log, tmp_path / "cache")
    assert len(rows) == 7 and rows[0]["id"] == "2019-01-17-audit"
    assert f.urls == [fin.first_url(), nxt, aud.first_url()]
    assert len(list((tmp_path / "cache").glob("*.json"))) == 3
    assert any(p["problem"] == "event name prints another date" for p in log["listing_problems"])


def test_listing_shrinks_names_the_lost_events_but_lets_a_future_unminuted_one_go():
    old = [{"event_id": 1, "date": "2019-04-04", "minutes_url": None},
           {"event_id": 2, "date": "2026-12-28", "minutes_url": None},
           {"event_id": 3, "date": "2026-12-28", "minutes_url": "https://x/m"},
           {"event_id": 4, "date": "2020-01-01", "minutes_url": None}]
    assert C.listing_shrinks([{"event_id": 4}], old, today="2026-11-16") == [1, 3]
    assert C.listing_shrinks([{"event_id": 2}], None, today="2026-11-16") == []


# ------------------------------------------------------------------ fetch
PDF = b"%PDF-1.4 test"


class Files(Pages):
    """Listing pages from a dict; any file URL answers a small PDF, or the given status."""

    def __init__(self, pages, status=None):
        super().__init__(pages)
        self.status = status or {}
        self.log = []

    def get(self, url):
        if url in self.pages:
            return super().get(url)
        self.urls.append(url)
        code = self.status.get(url, 200)
        if code in (403, 429):
            from collector.fetch import HostBlocked
            raise HostBlocked(f"HTTP {code}")
        return code, PDF + url.encode(), {"Content-Type": "application/pdf"}


def listing_pages(cfg):
    return {cfg.by_slug("finance").cc.first_url(): page("finance"), cfg.by_slug("audit").cc.first_url(): page("audit")}


def test_fetch_writes_listing_and_files_into_the_bodys_own_manifest(cfg, tmp_path):
    from collector.store import Store
    p = C.paths(cfg, tmp_path)
    store = Store(manifest_path=p["manifest"], root=tmp_path / "store")
    log = C.new_log()
    f = Files(listing_pages(cfg))
    rows = C.cmd_fetch(cfg, store, p["listing"], log, fetcher=f, today="2026-11-16", cache_dir=tmp_path / "cache")
    assert p["listing"].exists() and p["manifest"].exists()
    assert str(p["manifest"]).endswith("data/localities/clarksville-tn/committees/manifest.json")
    listed = json.loads(p["listing"].read_text())
    assert [r["id"] for r in listed] == [r["id"] for r in rows] and len(rows) == 7
    files = sum(bool(r["minutes_url"]) + bool(r["agenda_url"]) for r in rows)
    assert log["fetched"] == {"new": files} and not log["failures"]
    man = json.loads(p["manifest"].read_text())
    assert {e["kind"] for e in man} == {"agenda", "minutes"}
    m = next(e for e in man if e["url"].endswith("(fileId=997,plainText=false)"))
    assert m["meeting_date"] == "2019-04-04" and m["label"] == (
        "Finance Committee: Finance Committee Agenda 4-4-19 (minutes)")
    assert any(pr.get("problem") == "event name prints another date" for pr in log["problems"])
    # a second run asks only for the listing: every file is in the store
    f2 = Files(listing_pages(cfg))
    C.cmd_fetch(cfg, store, p["listing"], C.new_log(), fetcher=f2, today="2026-11-16", cache_dir=tmp_path / "cache")
    assert f2.urls == list(listing_pages(cfg))


def test_fetch_ids_and_limit_pick_the_files(cfg, tmp_path):
    from collector.store import Store
    p = C.paths(cfg, tmp_path)
    store = Store(manifest_path=p["manifest"], root=tmp_path / "store")
    log = C.new_log()
    f = Files(listing_pages(cfg))
    C.cmd_fetch(cfg, store, p["listing"], log, fetcher=f, ids={"2019-04-04-finance", "2030-01-01-finance"},
                limit=1, today="2026-11-16", cache_dir=tmp_path / "cache")
    files = f.urls[2:]
    assert files == [cfg.by_slug("finance").cc.file(997)]          # its minutes first; the agenda over the limit
    assert log["fetched"] == {"new": 1, "over_limit": 1}
    assert {"problem": "--ids names no listed meeting", "ids": ["2030-01-01-finance"]} in log["problems"]
    f = Files(listing_pages(cfg))
    C.cmd_fetch(cfg, store, p["listing"], C.new_log(), fetcher=f, kinds=("minutes",), today="2026-11-16",
                cache_dir=tmp_path / "cache")
    assert f.urls[2:] and all(u in {r["minutes_url"] for r in json.loads(p["listing"].read_text())} for u in f.urls[2:])


def test_a_refusal_stops_every_later_request(cfg, tmp_path):
    from collector.store import Store
    p = C.paths(cfg, tmp_path)
    store = Store(manifest_path=p["manifest"], root=tmp_path / "store")
    log = C.new_log()
    first = cfg.by_slug("audit").cc.file(120)                       # the oldest meeting's minutes, asked first
    f = Files(listing_pages(cfg), status={first: 429})
    C.cmd_fetch(cfg, store, p["listing"], log, fetcher=f, today="2026-11-16", cache_dir=tmp_path / "cache")
    assert f.urls[2:] == [first]
    assert log["failures"][0]["stop"] and log["fetched"]["not_tried"] > 0


def test_a_failed_or_shorter_listing_keeps_the_committed_one(cfg, tmp_path):
    from collector.store import Store
    p = C.paths(cfg, tmp_path)
    store = Store(manifest_path=p["manifest"], root=tmp_path / "store")
    C.cmd_fetch(cfg, store, p["listing"], C.new_log(), fetcher=Files(listing_pages(cfg)), limit=0,
                today="2026-11-16", cache_dir=tmp_path / "cache")
    before = p["listing"].read_bytes()
    short = listing_pages(cfg)
    short[cfg.by_slug("audit").cc.first_url()] = {"value": []}
    log = C.new_log()
    f = Files(short)
    C.cmd_fetch(cfg, store, p["listing"], log, fetcher=f, today="2026-11-16", cache_dir=tmp_path / "cache")
    assert p["listing"].read_bytes() == before and log["failures"][0]["stage"] == "listing"
    assert f.urls == list(short)                                     # no file asked for
    bad = listing_pages(cfg)
    bad[cfg.by_slug("audit").cc.first_url()] = {"not": "odata"}
    log = C.new_log()
    assert C.cmd_fetch(cfg, store, p["listing"], log, fetcher=Files(bad), today="2026-11-16",
                       cache_dir=tmp_path / "cache") == []
    assert p["listing"].read_bytes() == before and "EventsError" in log["failures"][0]["error"]


def test_main_registers_the_committees_command(monkeypatch):
    from collector import __main__ as M
    seen = []
    monkeypatch.setattr(C, "main", lambda argv: seen.append(argv) or 0)
    assert M.main(["committees", "build"]) == 0 and seen == [["build"]]


# ------------------------------------------------------------------ minutes reader
def minutes(name: str, date: str) -> dict:
    from collector.committee_minutes import read_minutes
    return read_minutes((FIX / f"{name}.txt").read_text(encoding="utf-8").split("\f"), date)


def test_voice_votes_are_an_outcome_never_per_member_votes():
    r = minutes("finance-minutes-2025-05-27", "2025-05-27")
    assert r["printed_date"] == "2025-05-27" and not r["date_mismatch"]
    m = r["motions"][0]
    assert (m["section"], m["item"], m["subject_printed"]) == ("3. Approval of Minutes", "A", "April 21, 2025")
    assert (m["mover_printed"], m["mover"], m["seconder_printed"], m["seconder"]) == (
        "Councilman McLaughlin", "McLaughlin", "Councilman Shakeenab", "Shakeenab")
    assert m["motion_printed"] == "to adopt the April 21, 2025 minutes"
    assert m["vote"] == {"method": "voice vote", "outcome": "passed",
                         "outcome_printed": "A voice vote was taken and the motion passed."}
    assert m["confirmed"] and m["page"] == 1
    for m in r["motions"]:                       # no motion carries a list of yes votes it did not print
        assert "ayes_printed" not in (m["vote"] or {})


def test_attendance_as_printed_with_arrived_at_note():
    r = minutes("finance-minutes-2025-05-27", "2025-05-27")
    assert r["attendance"] == {"present": [{"name": "Streetman"}, {"name": "Lovato"}, {"name": "McLaughlin"},
                                           {"name": "Shakeenab"}, {"name": "Zacharias", "note": "arrived at 5:10 pm"}],
                               "absent": [], "page": 1}
    r = minutes("finance-minutes-2026-04-27", "2026-04-27")
    assert r["attendance"]["present"][0] == {"name": "Streetman", "note": "arrived at 4:43 pm"}
    assert [p["name"] for p in r["attendance"]["present"]] == ["Streetman", "Lovato", "Shakeenab", "Zacharias"]
    assert r["attendance"]["absent"] == [{"name": "Peters"}]          # "Also Present: Mayor Pitts" is not a member


def test_attendance_runs_onto_the_next_line_and_stops_at_other_lines():
    r = minutes("finance-minutes-2019-04-04", "2019-04-04")
    assert [p["name"] for p in r["attendance"]["present"]] == [
        "Jeff Burkhart", "Tim Chandler", "Valerie Guzman", "Jeff Henley", "Stacey Streetman"]
    r = minutes("audit-minutes-2024-10-30", "2024-10-30")
    assert [p["name"] for p in r["attendance"]["absent"]] == ["Karen Reynolds", "Elizabeth Rankin"]
    assert not r["problems"]


def test_unsure_motions_are_held_with_reasons():
    ms = minutes("finance-minutes-2025-05-27", "2025-05-27")["motions"]
    first, postpone = ms[1], ms[2]          # a motion, then a motion to postpone it, one voice vote on the postponing
    assert not first["confirmed"] and "outcome not read" in first["reasons"]
    assert any("Coiuncilman Zacharias" in x for x in first["reasons"])           # a misprinted title is not guessed
    assert not postpone["confirmed"] and any("motion to postpone passed" in x for x in postpone["reasons"])
    assert [m["confirmed"] for m in ms[3:]] == [True, True]
    last = minutes("finance-minutes-2026-04-27", "2026-04-27")["motions"][-1]
    assert not last["confirmed"] and "seconder not read" in last["reasons"]       # "seconded the meeting"
    assert last["subject_printed"].startswith("Motion to defend and indemnify Chief")
    assert last["mover_printed"] == "Councilman Lovato"                            # not the heading's words


def test_a_printed_dissent_in_a_voice_vote_is_kept_as_printed():
    ms = minutes("finance-minutes-2026-04-27", "2026-04-27")["motions"]
    m = ms[1]
    assert m["item"] == "A" and m["subject_printed"].startswith("New Positions")    # the section's only item
    assert m["vote"]["nays_printed"] == ["Councilman Lovato"] and m["vote"]["method"] == "voice vote"
    assert m["confirmed"] and "ayes_printed" not in m["vote"]
    m = minutes("finance-minutes-2019-04-04", "2019-04-04")["motions"][2]
    assert m["vote"] == {"method": "voice vote", "outcome": "passed", "nays_printed": ["Councilman Henley"],
                         "outcome_printed": "A voice vote was taken; Councilman Henley voted “nay.” The motion passed."}
    assert m["seconder"] == "Stacey Streetman" and m["confirmed"]


def test_unanimous_is_an_outcome_and_full_names_resolve():
    ms = minutes("audit-minutes-2024-10-30", "2024-10-30")["motions"]
    assert ms[0]["subject_printed"] == "III. ADOPTION OF MINUTES: July 31, 2024 Audit Committee Meeting"
    assert ms[0]["vote"]["method"] == "unanimous" and ms[0]["confirmed"]
    assert (ms[1]["mover"], ms[1]["seconder"]) == ("Trey Judd", "Jennifer Thayer")
    assert [m["confirmed"] for m in ms] == [True, True, True, True, False]       # adjourning: no outcome printed


def test_divided_vote_names_only_as_printed():
    ms = minutes("finance-minutes-divided-constructed", "2023-10-23")["motions"]
    assert ms[0]["vote"] == {"method": "roll call", "outcome": "passed", "ayes_printed": ["Ashby", "Birch", "Dunn", "Ellis"],
                             "nays_printed": ["Cole"],
                             "outcome_printed": "AYE: Ashby, Birch, Dunn, Ellis NAY: Cole The motion passed."}
    assert ms[0]["confirmed"]
    assert ms[1]["vote"]["outcome"] == "failed" and not ms[1]["confirmed"]
    assert ms[1]["reasons"] == ["aye 'Jones' is not exactly one member present"]


def test_minutes_printing_another_date_hold_everything():
    # the 2026-05-26 Finance event carries the 2025-05-27 minutes (the same bytes as that meeting's): kept as listed,
    # flagged, nothing confirmed for the 2026 meeting
    r = minutes("finance-minutes-2025-05-27", "2026-05-26")
    assert r["printed_date"] == "2025-05-27" and r["date_mismatch"]
    assert r["problems"] == ["the minutes print 2025-05-27, the meeting is 2026-05-26"]
    assert not any(m["confirmed"] for m in r["motions"])


@pytest.mark.parametrize("printed, member", [
    ("Councilman Henley", "Jeff Henley"), ("Councilwoman Valerie Guzman", "Valerie Guzman"),
    ("Jeff Henley", "Jeff Henley"), ("Henley", None), ("Coiuncilman Henley", None), ("Councilman Jones", None)])
def test_resolve(printed, member):
    from collector.committee_minutes import resolve
    assert resolve(printed, ["Jeff Henley", "Valerie Guzman"]) == member


def test_resolve_surname_only_attendance_and_shared_surnames():
    from collector.committee_minutes import resolve
    assert resolve("Councilman Lovato", ["Streetman", "Lovato"]) == "Lovato"
    assert resolve("Councilwoman Kaye Lovato", ["Streetman", "Lovato"]) == "Lovato"
    assert resolve("Councilman Smith", ["Ann Smith", "Bo Smith"]) is None

