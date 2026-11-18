"""RPC-3: the Regional Planning Commission's 2019-2021 meetings from the city's CivicClerk API (rpc.yml `civicclerk`,
collector/rpc.py backfill_rows, discover_backfill, fetch_backfill), read like the RPC's own.

The events page is an excerpt of the real 2019-2021 listing (fetched 2026-11-18, fields the reader uses only); the
agenda texts are real pages read by the collector's own text-layer reader. No network: a fake opener answers."""
import dataclasses
import json
from pathlib import Path

import pytest

from collector import rpc, rpc_agenda
from collector.fetch import USER_AGENT, PoliteFetcher
from collector.store import Store
from collector.tests.test_fetch import Clock, FakeNet
from sitegen import rpc as site_rpc

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "collector" / "tests" / "fixtures" / "rpc"
CFG = rpc.load_config()
BF = CFG.backfill
EVENTS = json.loads((FIX / "civicclerk-events-2019-2021-excerpt.json").read_text(encoding="utf-8"))
API = f"https://{BF.cc.api_host}"
API_ROBOTS = f"{API}/robots.txt"
ROBOTS = "https://www.cmcrpc.com/robots.txt"
LISTING_PAGE = (FIX / "listing.html").read_text(encoding="utf-8")


def pages(name: str) -> list[str]:
    out = (FIX / name).read_text(encoding="utf-8").split("\f")
    return out[:-1] if out and not out[-1].strip() else out


AGENDA_2019 = pages("agenda_2019-04-24_p1-2.txt")
AGENDA_2026 = pages("agenda_2026-10-27.txt")


def events() -> list[dict]:
    from collector import civicclerk
    rows, _ = civicclerk.parse_events(EVENTS, BF.cc, CFG.kind_of)
    return rows


def file_url(file_id: int) -> str:
    return BF.cc.file(file_id)


# ------------------------------------------------------------------ config
def test_config_reads_the_backfill_and_bounds_it_before_cmcrpc_starts():
    assert BF is not None and BF.cc.category_name == "Regional Planning Commission"
    assert BF.cc.api_host == "clarksvilletn.api.civicclerk.com" and BF.to_date == "2022-01-01"
    url = BF.cc.first_url()
    assert url.startswith(API + "/v1/Events?") and "startDateTime%20lt%202022-01-01T00:00:00Z" in url
    assert BF.cc.from_date == "2019-01-01" and BF.listing_url.startswith("https://")


@pytest.mark.parametrize("change, message", [
    ({"to_date": "2023-01-01"}, "events_url must ask only for events before to_date"),
    ({"to_date": "2018-01-01"}, "to_date must be YYYY-MM-DD after from_date"),
    ({"skip_events": [{"event_name": "x"}]}, "each skip_events entry"),
    ({"listing_url": "http://example.com/"}, "listing_url must be https"),
    ({"also_list": [{"category_name": "General"}]}, "also_list is not used"),
    ({"file_url": "https://elsewhere.example/{file_id}"}, "file_url must be https on api_host"),
])
def test_config_refuses_a_backfill_it_cannot_trust(tmp_path, change, message):
    import yaml
    raw = yaml.safe_load((ROOT / "config" / "localities" / "cmc-rpc" / "rpc.yml").read_text(encoding="utf-8"))
    raw["civicclerk"].update(change)
    p = tmp_path / "rpc.yml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(rpc.RpcConfigError, match=message):
        rpc.load_config(p)


# ------------------------------------------------------------------ listing rows
def test_backfill_rows_as_listed():
    rows, problems = rpc.backfill_rows(events(), CFG)
    by_date = {r["date"]: r for r in rows}
    assert [r["date"] for r in rows] == ["2020-12-14", "2020-03-25", "2019-09-25", "2019-04-24"]   # newest first
    first = by_date["2019-04-24"]
    assert first["printed"] == "Regional Planning Commission Agenda 4-24-19" and first["kind"] == "regular"
    assert [(d["kind"], d["url"], d["fetch"]) for d in first["docs"]] == [
        ("agenda", file_url(1619), True), ("minutes", file_url(1620), True)]
    assert first["source"] == rpc.BACKFILL and first["listing_url"] == BF.listing_url
    assert by_date["2020-03-25"]["cancelled"] is True
    assert by_date["2020-12-14"]["kind"] == "cdrb"
    # the 2019-09-25 minutes are a second event whose one file is typed "Agenda" and named "RPC Minutes": one meeting
    sept = by_date["2019-09-25"]
    assert [(d["kind"], d["url"]) for d in sept["docs"]] == [("agenda", file_url(1641)), ("minutes", file_url(1647))]
    assert sept["event_ids"] == [1160, 1164]
    text = json.dumps(problems)
    assert "another body" in text and "a notice, not a meeting" in text      # the MPO agenda and the RPC letter
    assert "named as minutes" in text and "one meeting" in text
    assert "2022" not in "".join(r["date"] for r in rows)                   # cmcrpc.com is the source from 2022
    # problems name event ids and dates, never the portal's free text
    assert all(set(p) == {"event", "date", "problem"} for p in problems)
    assert "Regional Planning" not in text.replace("Metropolitan Planning Organization", "")


def test_the_kind_is_read_from_the_event_name_and_its_agenda_files_name():
    """2020-04-06: the event is "Regional Planning Commission Agenda 4-6-20", its file "411a-Agenda Special Called RPC
    Meeteing April 6 2020 11AM revised" (as printed), and the agenda itself heads "Special Called Meeting"."""
    ev = [dict(events()[0], date="2020-04-06", title="Regional Planning Commission Agenda 4-6-20",
               agenda_name="411a-Agenda Special Called RPC Meeteing April 6 2020 11AM revised")]
    rows, _ = rpc.backfill_rows(ev, CFG)
    assert rows[0]["kind"] == "special" and rows[0]["printed"] == "Regional Planning Commission Agenda 4-6-20"


def test_an_event_name_of_an_unknown_shape_is_not_shown():
    ev = [dict(events()[0], title="Regional Planning Commission Agenda for Jane Doe rezoning")]
    rows, problems = rpc.backfill_rows(ev, CFG)
    assert rows[0]["printed"] == "Regional Planning Commission, 2019-04-24"
    assert "Jane" not in json.dumps(problems) and "not of a known shape" in json.dumps(problems)


def test_the_listing_pages_row_wins_over_a_backfill_row_of_the_same_meeting():
    page = [{"date": "2019-04-24", "kind": "regular", "docs": []}]
    bf, _ = rpc.backfill_rows(events(), CFG)
    rows, problems = rpc.merge_backfill(page, bf)
    assert [r for r in rows if r["date"] == "2019-04-24"] == page
    assert problems and problems[0]["date"] == "2019-04-24"


# ------------------------------------------------------------------ the 2019-2021 agendas
def test_a_2019_agenda_reads_like_the_2022_layout():
    res = rpc_agenda.parse_pages(AGENDA_2019)
    assert res["printed_date"]["date"] == "2019-04-24"
    assert [(c["item"], c["number"], c["page"]) for c in res["cases"]] == [
        (1, "Z-6-2019", 1), (2, "Z-7-2019", 1), (3, "Z-8-2019", 2), (4, "Z-9-2019", 2), (5, "Z-10-2019", 2)]
    assert res["case_numbers_printed"] == res["case_numbers_read"] == 5
    rec = rpc_agenda.case_record(res["cases"][1], "m", "s", CFG.case_types)
    assert rec["applicant"] == "Paramount Hospitality, Inc." and rec["ward"] == 12 and rec["district"] == 1
    assert rec["request"].startswith("R-1 Single-Family Residential District to C-5")
    # hearing dates as printed on one line (a date whose heading breaks across lines is not read: never guessed)
    assert [h["date"] for h in res["hearings"]] == ["2019-04-25", "2019-05-06", "2019-05-13"]


def test_a_2021_variance_section_numbered_with_a_parenthesis():
    res = rpc_agenda.parse_pages(pages("agenda_2021-11-23_p5.txt"))
    assert [(c["item"], c["number"]) for c in res["cases"]] == [(1, "S-111-2021"), (2, "S-114-2021")]
    assert res["case_numbers_printed"] == res["case_numbers_read"] == 2


@pytest.mark.parametrize("name, want", [
    # "a.   CASE NUMBER: SR-32-2020" lettered site reviews (no item number recorded for a letter), and "CASE" printed at
    # the end of the rule above "NUMBER: S-88-2020" by the text layer
    ("agenda_2020-09-23_p9-p11-p12.txt", [(13, "S-87-2020", 1), (14, "S-88-2020", 1), (15, "S-89-2020", 1),
                                          (16, "S-90-2020", 1), (None, "SR-32-2020", 2), (None, "SR-33-2020", 2),
                                          (None, "SR-34-2020", 2), (None, "AB-2-2020", 3)]),
    # "8    CASE NUMBER: CZO-4-2020": an item number with no period
    ("agenda_2020-11-24_p3.txt", [(6, "CZ-23-2020", 1), (7, "CZO-3-2020", 1), (8, "CZO-4-2020", 1)]),
    # "*******  CASE" / "NUMBER: Z-38-2021 ..."
    ("agenda_2021-07-27_p2.txt", [(3, "Z-36-2021", 1), (4, "Z-37-2021", 1), (5, "Z-38-2021", 1)]),
])
def test_the_2020_2021_agenda_forms_read_every_printed_case(name, want):
    res = rpc_agenda.parse_pages(pages(name))
    assert [(c["item"], c["number"], c["page"]) for c in res["cases"]] == want
    assert res["case_numbers_printed"] == res["case_numbers_read"] == len(want)       # the completeness check holds


def test_the_split_label_keeps_the_rule_and_the_case_apart():
    res = rpc_agenda.parse_pages(pages("agenda_2021-07-27_p2.txt"))
    z37 = next(c for c in res["cases"] if c["number"] == "Z-37-2021")
    assert "CASE" not in z37["text"] and z37["fields"]["applicant"] == "Krueckberg LLC"
    z38 = next(c for c in res["cases"] if c["number"] == "Z-38-2021")
    assert z38["fields"]["applicant"] == "Bret And Patricia Logan"


def test_an_ocr_cdrb_agenda_whose_label_lost_its_colon():
    res = rpc_agenda.parse_pages(rpc_agenda.ocr_clean(pages("agenda_2021-01-25-cdrb_ocr_p1.txt")))
    assert [c["number"] for c in res["cases"]] == ["HZ-2-2020", "MSCD-3-2021"]


def test_a_parenthesis_number_without_case_number_is_not_a_case():
    res = rpc_agenda.parse_pages(["V. OTHER BUSINESS:\n  1) S-12-2021 was deferred\n"])
    assert res["cases"] == []


# ------------------------------------------------------------------ the daily step with the backfill on
def api_routes(excerpt: dict = EVENTS, status: int = 200) -> dict:
    out = {API_ROBOTS: (200, b"User-agent: *\nAllow: /\n"),
           BF.cc.first_url(): (status, json.dumps(excerpt).encode())}
    for e in excerpt["value"]:
        for f in e["publishedFiles"]:
            out[file_url(f["fileId"])] = (200, b"%PDF-1.4 civicclerk " + str(f["fileId"]).encode())
    return out


def page_routes() -> dict:
    out = {ROBOTS: (200, b"User-agent: *\ncrawl-delay: 10\n"), CFG.listing_url: (200, LISTING_PAGE.encode())}
    rows, _ = rpc.parse_listing(LISTING_PAGE, CFG)
    for r in rows:
        for d in r["docs"]:
            if d["fetch"]:
                body = (b"PK\x03\x04 " if d["url"].lower().endswith(".docx") else b"%PDF-1.4 ") + d["url"].encode()
                out[d["url"]] = (200, body)
    return out


def extract(path: Path) -> list[str]:
    """A backfill file reads as the 2019 agenda, any other as the 2026 one (no poppler in a unit test)."""
    return AGENDA_2019 if b"civicclerk" in path.read_bytes() else AGENDA_2026


def fake_build(cfg, rows, store, audit_path=None):
    def no_ocr(pdf, sha, n):
        raise RuntimeError("no OCR in this test")
    return rpc_agenda.build(cfg, rows, store, extract=extract, ocr=no_ocr, audit_path=audit_path)


class Site:
    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.p = rpc.paths(CFG, tmp_path)
        self.store_dir = tmp_path / "store"

    def run(self, routes: dict, cfg=CFG, build=None):
        net, clock = FakeNet(routes), Clock()
        f = PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: [])
        log: dict = {}
        store = Store(manifest_path=self.p["manifest"], root=self.store_dir)
        code = rpc.run_step(log, False, fetcher=f, cfg=cfg, root=self.root, store=store, build=build or fake_build)
        self.calls = [u for u, _ in net.calls]
        self.agents = {ua for _, ua in net.calls}
        self.clock = clock
        return code, log["rpc"]

    def api_calls(self) -> list[str]:
        return [u for u in self.calls if u.startswith(API)]

    def facts(self) -> dict:
        return json.loads(self.p["facts"].read_text(encoding="utf-8"))


@pytest.fixture
def site(tmp_path):
    return Site(tmp_path)


def test_a_run_lists_and_fetches_the_backfill_politely(site):
    code, out = site.run({**page_routes(), **api_routes()})
    assert code == rpc.STEP_OK, out["status"]
    api = site.api_calls()
    assert api[:2] == [API_ROBOTS, BF.cc.first_url()]                          # robots.txt first, one listing page
    files = [file_url(i) for i in (1619, 1620, 1641, 1647, 1575, 1569)]         # oldest first, agenda before minutes
    assert api[2:] == files                                                     # the MPO agenda and the letter: never
    assert site.agents == {USER_AGENT}
    facts = site.facts()
    bf = [m for m in facts["meetings"] if m["date"] < "2022-01-01"]
    assert [m["id"] for m in sorted(bf, key=lambda m: m["date"])] == [
        "2019-04-24-regular", "2019-09-25-regular", "2020-03-25-regular", "2020-12-14-cdrb"]
    assert all(m["listing_url"] == BF.listing_url for m in bf)
    assert all(m["listing_url"] == CFG.listing_url for m in facts["meetings"] if m["date"] >= "2022-01-01")
    first = next(m for m in bf if m["id"] == "2019-04-24-regular")
    assert first["agenda_read_by"] == "text layer" and first["case_count"] == 5
    assert {c["number"] for c in facts["cases"] if c["meeting_id"] == first["id"]} >= {"Z-6-2019", "Z-10-2019"}
    listing = json.loads(site.p["listing"].read_text(encoding="utf-8"))
    assert sum(1 for r in listing if r.get("source") == rpc.BACKFILL) == 4
    assert site.clock.slept and min(site.clock.slept) > 0         # the fetcher's per-host wait (test_fetch.py)


def test_the_next_run_asks_for_the_listings_only(site):
    routes = {**page_routes(), **api_routes()}
    assert site.run(routes)[0] == rpc.STEP_OK
    before = {k: site.p[k].read_bytes() for k in ("listing", "manifest", "facts")}
    code, out = site.run(routes)
    assert code == rpc.STEP_OK and out["changed"] is False
    assert site.api_calls() == [API_ROBOTS, BF.cc.first_url()]
    assert {k: site.p[k].read_bytes() for k in before} == before


def test_a_cold_store_is_filled_over_several_runs_without_stopping_the_rpc(site, monkeypatch):
    monkeypatch.setattr(rpc, "BACKFILL_FETCH_CAP", 4)          # robots.txt, the listing and two files a run
    routes = {**page_routes(), **api_routes()}
    code, out = site.run(routes)
    assert code == rpc.STEP_OK and "4 files left for later runs" in out["status"]
    assert len(site.api_calls()) == 4
    facts = site.facts()
    sept = next(m for m in facts["meetings"] if m["id"] == "2019-09-25-regular")
    assert [d["source_id"] for d in sept["documents"]] == [None, None]          # listed, its files not yet fetched
    assert next(m for m in facts["meetings"] if m["id"] == "2019-04-24-regular")["agenda_read_by"] == "text layer"
    code, out = site.run(routes)
    assert code == rpc.STEP_OK and "2 files left" in out["status"]
    code, out = site.run(routes)
    assert code == rpc.STEP_OK and "left for later" not in out["status"]
    assert all(d["source_id"] for m in site.facts()["meetings"] if m["date"] < "2022" for d in m["documents"])


def test_a_refused_civicclerk_listing_keeps_the_committed_backfill_and_updates_the_rpc(site):
    assert site.run({**page_routes(), **api_routes()})[0] == rpc.STEP_OK
    before = json.loads(site.p["listing"].read_text(encoding="utf-8"))
    code, out = site.run({**page_routes(), **api_routes(status=403)})
    assert code == rpc.STEP_OK and "CivicClerk 2019-2021: listing not read" in out["status"]
    assert site.api_calls() == [API_ROBOTS, BF.cc.first_url()]                  # no file asked for after the 403
    after = json.loads(site.p["listing"].read_text(encoding="utf-8"))
    assert [r for r in after if r.get("source") == rpc.BACKFILL] == [r for r in before if r.get("source") == rpc.BACKFILL]
    assert {m["id"] for m in site.facts()["meetings"]} >= {"2019-04-24-regular", "2020-12-14-cdrb"}


def test_a_backfill_meeting_gone_from_the_api_is_kept_as_committed(site):
    """rpc-backfill/blocks-rpc-update: a shorter CivicClerk answer never drops a meeting nor stops the RPC update."""
    assert site.run({**page_routes(), **api_routes()})[0] == rpc.STEP_OK
    before = site.facts()
    fewer = {**EVENTS, "value": [e for e in EVENTS["value"] if e["id"] not in (1149, 1164)]}
    code, out = site.run({**page_routes(), **api_routes(fewer)})
    assert code == rpc.STEP_OK, out["status"]
    problems = out["fetch"]["problems"]
    assert "civicclerk event 1149 (2019-04-24): gone from the API: kept as committed" in problems
    assert "civicclerk event 1164 (2019-09-25): gone from the API: kept as committed" in problems
    listing = json.loads(site.p["listing"].read_text(encoding="utf-8"))
    sept = [r for r in listing if r["date"] == "2019-09-25"]
    assert len(sept) == 1 and sept[0]["event_ids"] == [1160, 1164]          # the joined row, as committed
    assert site.facts()["meetings"] == before["meetings"]


def test_an_empty_civicclerk_answer_is_a_listing_not_read(site):
    assert site.run({**page_routes(), **api_routes()})[0] == rpc.STEP_OK
    before = site.facts()
    code, out = site.run({**page_routes(), **api_routes({**EVENTS, "value": []})})
    assert code == rpc.STEP_OK and "listing not read (EventsError: the events listing answered with no events)" \
        in out["status"]
    assert site.facts()["meetings"] == before["meetings"]


def test_missing_backfill_files_hold_their_meetings_not_the_rpc_update(site):
    """A fresh store (an evicted cache) without the 2019-2021 bytes: the RPC page's meetings update, each 2019-2021
    meeting with a missing file stays as committed, and the files are fetched again under the cap."""
    assert site.run({**page_routes(), **api_routes()})[0] == rpc.STEP_OK
    before = site.facts()
    for f in site.store_dir.glob("*.pdf"):
        if b"civicclerk" in f.read_bytes():
            f.unlink()
    # the CivicClerk API refuses this run, so no file comes back: the meetings are held, the step still commits
    code, out = site.run({**page_routes(), **api_routes(status=403)})
    assert code == rpc.STEP_OK, out["status"]
    assert out["held"] == ["2019-04-24-regular", "2019-09-25-regular", "2020-03-25-regular", "2020-12-14-cdrb"]
    assert "4 meetings held" in out["status"]
    after = site.facts()
    assert after["meetings"] == before["meetings"] and after["cases"] == before["cases"]
    assert after["sources"] == before["sources"]
    # the next run with the API back fetches them again (gaps first) and reads them
    code, out = site.run({**page_routes(), **api_routes()})
    assert code == rpc.STEP_OK and not out.get("held")
    assert len([u for u in site.api_calls() if "GetMeetingFileStream" in u]) == 6


def short_build(cfg, rows, store, audit_path=None):
    """Every backfill agenda prints one case number more than can be read."""
    def short(path):
        pages = extract(path)
        return pages + ["CASE NUMBER: (not legible)"] if b"civicclerk" in path.read_bytes() else pages
    return rpc_agenda.build(cfg, rows, store, extract=short, ocr=lambda *a: None, audit_path=audit_path)


def test_a_short_2019_2021_agenda_holds_that_meeting_only(site):
    """Decision (L28): shown without cases on a first run, as committed afterwards; the RPC page's update goes on."""
    code, out = site.run({**page_routes(), **api_routes()}, build=short_build)
    assert code == rpc.STEP_OK, out["status"]
    facts = site.facts()
    first = next(m for m in facts["meetings"] if m["id"] == "2019-04-24-regular")
    assert first["case_count"] == 0 and first["case_numbers_printed"] is None and first["agenda_read_by"] is None
    assert not [c for c in facts["cases"] if c["meeting_id"] == first["id"]]
    assert [c for c in facts["cases"] if c["meeting_id"].startswith("2026-")]           # the RPC page's, as read
    report = json.loads((site.root / "build" / "rpc-report.json").read_text())
    assert ("2019-04-24-regular: held (its agenda prints more case numbers than were read)"
            in report["build"]["problems"])
    from qa import site_checks
    assert site_checks.check_rpc_cases(facts)[0] == []
    # read in full once, then short again: kept as committed
    assert site.run({**page_routes(), **api_routes()})[0] == rpc.STEP_OK
    good = site.facts()
    assert site.run({**page_routes(), **api_routes()}, build=short_build)[0] == rpc.STEP_OK
    assert site.facts() == good


def test_a_listing_page_agenda_short_of_its_count_still_stops_the_step(site):
    def page_short(cfg, rows, store, audit_path=None):
        def short(path):
            pages = extract(path)
            return pages if b"civicclerk" in path.read_bytes() else pages + ["CASE NUMBER: (not legible)"]
        return rpc_agenda.build(cfg, rows, store, extract=short, ocr=lambda *a: None, audit_path=audit_path)
    code, _ = site.run({**page_routes(), **api_routes()}, build=page_short)
    assert code == rpc.STEP_GATE


def test_an_event_without_a_real_date_is_left_out_and_reported():
    ev = events()
    bad = [dict(ev[0], date="2019-02-30", event_id=1), dict(ev[0], date="2019-04-2", event_id=2),
           dict(ev[0], date=None, event_id=3)]
    rows, problems = rpc.backfill_rows(bad + ev, CFG)
    assert len(rows) == 4
    assert [p["event"] for p in problems if p["problem"] == "event date is not a date: left out"] == [1, 2, 3]


def test_without_the_backfill_the_step_never_asks_the_api(site):
    code, _ = site.run(page_routes(), cfg=dataclasses.replace(CFG, backfill=None))
    assert code == rpc.STEP_OK and site.api_calls() == []


# ------------------------------------------------------------------ the morning note
def test_the_backfills_documents_are_never_news(tmp_path):
    """A 2019 agenda first fetched today is no entry in today's note, and does not hold the day back either."""
    import copy
    from sitegen import config, morning
    rows = [{"url": file_url(1619), "first_fetched_at": "2026-11-19T09:00:00+00:00", "meeting_date": "2019-04-24"},
            {"url": CFG.listing_url + "a.pdf", "first_fetched_at": "2026-11-19T09:00:00+00:00",
             "meeting_date": "2026-11-24"},
            {"url": CFG.listing_url + "b.pdf", "first_fetched_at": "2026-11-10T09:00:00+00:00"}]
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps(rows), encoding="utf-8")
    cfg = copy.deepcopy(config.SITE)
    cfg["fetch_manifests"] = [str(m)]
    cfg["morning_note"]["backfill"]["past_records"] = [{"manifest": str(m), "before": "2022-01-01"}]
    assert not any("past_records" in p for p in morning.problems(cfg))
    assert morning.past_record_urls(cfg) == {file_url(1619)}
    shipped = config.SITE["morning_note"]["backfill"]["past_records"]
    assert shipped == [{"manifest": "data/localities/cmc-rpc/manifest.json", "before": BF.to_date}]
    for bad in ([{"manifest": "data/elsewhere.json", "before": "2022-01-01"}],
                [{"manifest": str(m), "before": "1/1/2022"}], "data/x.json"):
        cfg["morning_note"]["backfill"]["past_records"] = bad
        assert any("past_records" in p for p in morning.problems(cfg))


def test_the_backfills_cases_are_no_feed_entries(site, tmp_path):
    """Decision (manager, PR #36): a 2019-2021 case is no Atom feed entry either; the RPC page's cases still are."""
    import copy
    from sitegen import config, feeds
    assert site.run({**page_routes(), **api_routes()})[0] == rpc.STEP_OK
    view = site_rpc.Rpc({**site_rpc.load_config("cmc-rpc"), "hold_motions": True}, site.facts())
    cfg = copy.deepcopy(config.SITE)
    cfg["fetch_manifests"] = [str(site.p["manifest"])]
    cfg["morning_note"]["backfill"]["past_records"] = [{"manifest": str(site.p["manifest"]), "before": BF.to_date}]
    dates = {m["date"][:4] for _, m in feeds._rpc_cases(view, cfg)}
    assert dates and all(d >= "2022" for d in dates)
    cfg["morning_note"]["backfill"]["past_records"] = []
    assert "2019" in {m["date"][:4] for _, m in feeds._rpc_cases(view, cfg)}


def test_the_portal_link_is_allowed_from_rpc_yml_not_from_the_facts():
    from qa import site_checks
    cfg = site_rpc.load_config("cmc-rpc")
    facts = {"meetings": [{"id": "x", "listing_url": "https://elsewhere.example/", "documents": []}]}
    allowed = site_checks.rpc_allowed({**facts, "_cfg": cfg})
    assert BF.listing_url in allowed and "https://elsewhere.example/" not in allowed
    assert BF.listing_url not in site_checks.rpc_allowed({**facts, "_cfg": {**cfg, "civicclerk": None}})


# ------------------------------------------------------------------ the pages and the export
def test_a_backfill_meeting_says_where_it_is_listed(site):
    assert site.run({**page_routes(), **api_routes()})[0] == rpc.STEP_OK
    facts = site.facts()
    view = site_rpc.Rpc({**site_rpc.load_config("cmc-rpc"), "hold_motions": True}, facts)
    old = next(m for m in facts["meetings"] if m["id"] == "2020-12-14-cdrb")
    new = next(m for m in facts["meetings"] if m["date"] >= "2022-01-01")
    assert view.meeting(old)["listed_on"] == {"url": BF.listing_url, "label": BF.listing_label}
    assert view.meeting(new)["listed_on"] is None
    from qa import site_checks
    assert BF.listing_url in site_checks.rpc_allowed({**facts, "_cfg": site_rpc.load_config("cmc-rpc")})
    # the export: each meeting's listing page, in facts.json and as meetings.csv source_url
    import csv
    import io
    from collector import rpc_export
    pub = rpc_export.public_facts(view)
    by_id = {m["id"]: m for m in pub["meetings"]}
    assert by_id["2020-12-14-cdrb"]["listing_url"] == BF.listing_url
    assert by_id[new["id"]]["listing_url"] == CFG.listing_url
    rows = {r["id"]: r for r in csv.DictReader(io.StringIO(rpc_export.tables(pub)["meetings"]))}
    assert rows["2020-12-14-cdrb"]["source_url"] == BF.listing_url
    assert rows[new["id"]]["source_url"] == CFG.listing_url


def test_the_site_shows_the_backfill_and_passes_its_checks(tmp_path):
    """A fixture site build with the listing page's meetings and the backfill's: the 2019 year page says where each
    meeting is listed, a file not yet fetched says it is listed on the portal, and the source and link checks pass."""
    from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, rpc_config_unheld
    from qa import site_checks
    from sitegen import config
    from sitegen.build import build
    page_rows, _ = rpc.parse_listing(LISTING_PAGE, CFG)
    bf_rows, _ = rpc.backfill_rows(events(), CFG)
    rows = rpc.assign_ids(rpc.merge_backfill(page_rows, bf_rows)[0])
    store = Store(manifest_path=tmp_path / "manifest.json", root=tmp_path / "store")
    store.put(file_url(1619), b"%PDF-1.4 civicclerk 1619", {}, {"kind": "agenda", "meeting_date": "2019-04-24"})
    facts, _ = rpc_agenda.build(CFG, rows, store, extract=extract)
    (tmp_path / "rpc.json").write_text(json.dumps({**facts, "fixture": True}), encoding="utf-8")
    rcfg = {**rpc_config_unheld(), "facts_path": tmp_path / "rpc.json"}
    site = tmp_path / "build" / "site"
    build(FIXTURE, site, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, rpc=rcfg)
    import markupsafe
    label = str(markupsafe.escape(BF.listing_label))
    html = (site / "rpc" / "meetings" / "2019.html").read_text(encoding="utf-8")
    sec = html[html.index('id="2019-04-24-regular"'):]
    sec = sec[:sec.index("</section>")]
    assert ("Listed as: Regional Planning Commission Agenda 4-24-19, on the "
            f'<a data-ext="record" href="{BF.listing_url}" target="_blank" rel="noopener noreferrer">{label}') in sec
    assert f'Unofficial copy. Official record: <a href="{file_url(1619)}"' in sec
    assert 'id="case-2019-04-24-regular-z-6-2019"' in sec
    assert f'<a data-ext="listed" href="{file_url(1620)}"' in sec        # the minutes: listed, not yet fetched
    assert f"listed on the {label}; not collected or read" in sec
    y2020 = (site / "rpc" / "meetings" / "2020.html").read_text(encoding="utf-8")
    cdrb = y2020[y2020.index('id="2020-12-14-cdrb"'):]
    assert f"Minutes: <span class=\"doc-note\">not posted on the {label}</span>" in cdrb[:cdrb.index("</section>")]
    # the listing page's meetings read as before
    y2026 = (site / "rpc" / "meetings" / "2026.html").read_text(encoding="utf-8")
    assert "CivicClerk" not in y2026 and "not linked on the RPC page" in y2026
    county = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pages_ = {p.relative_to(site).as_posix(): site_checks.parse(p) for p in site.rglob("*.html")}
    allowed = site_checks.allowed_external(config.SITE, FIXTURE_SEATS, FIXTURE_DISTRICTS) | \
        site_checks.rpc_allowed({**facts, "_cfg": rcfg})
    problems, _ = site_checks.check_sources(site, pages_, {"sources": county["sources"] + facts["sources"]}, (),
                                            allowed)
    assert problems == []
    assert site_checks.check_links(site, pages_, no_export=True) == []
    assert site_checks.check_external(pages_, site, site_checks._site_cfg()) == []
