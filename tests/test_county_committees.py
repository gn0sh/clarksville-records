"""County "Committee Agendas" page: the listing parser (collector/county_committees.py) on a saved copy of the page
(tests/fixtures/county-committee-agendas-2026-11-16.html), the file-name dates, the rollover merge and the fetch."""
import json
from datetime import date
from pathlib import Path

import pytest

from collector import county_committees as cc
from collector.store import Store

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "tests" / "fixtures" / "county-committee-agendas-2026-11-16.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def cfg():
    return cc.load_config()


@pytest.fixture(scope="module")
def rows(cfg):
    rows, problems = cc.parse_listing(PAGE, cfg)
    assert problems == []
    return cc.assign_ids(rows)


@pytest.mark.parametrize("name,iso", [
    ("01-13-26 - Study Session Agenda", "2026-01-13"),           # MM-DD-YY
    ("08-04-2026 Study Session Agenda", "2026-08-04"),           # MM-DD-YYYY
    ("09-01-2026 Study Session Agenda.", "2026-09-01"),
    ("CMCRAA Agenda 1-28-2026", "2026-01-28"),                   # M-DD-YYYY
    ("2026-04-08 - Fire Agenda", "2026-04-08"),                  # YYYY-MM-DD
    ("031926 Agenda MPO", "2026-03-19"),                         # MMDDYY
    ("CVB BoD Mtg Agenda - 260212 FINAL", "2026-02-12"),         # YYMMDD (MMDDYY is no date)
    ("Agenda 01 08 2026", "2026-01-08"),                         # spaces
    ("5-19- 26 Health Council Agenda", "2026-05-19"),
    ("BZA AGENDA - November 12, 2026", "2026-11-12"),
    ("Budget Committee Agenda 07-23-2026 SPECIAL CALLED", "2026-07-23"),
    ("Budget Hearing 05-05-2026 1PM", "2026-05-05"),
    ("Purchasing Agenda 01-14-26 (rescheduled)", "2026-01-14"),
])
def test_file_name_dates_in_every_printed_format(name, iso):
    assert cc.name_date(name) == (iso, None)


@pytest.mark.parametrize("name", ["Sports Authority Liaison - September 2026", "Agenda", "Agenda 13-45-26",
                                  "010203 Agenda", "Agenda 01-02-26 and 01-03-26"])
def test_no_date_or_an_ambiguous_one_is_not_guessed(name):
    when, why = cc.name_date(name)
    assert when is None and why


def test_the_configured_folders_and_their_counts(rows):
    by = {}
    for r in rows:
        by.setdefault(r["body"], []).append(r)
    assert {k: len(v) for k, v in by.items()} == {
        "school-board": 21, "budget-committee": 12, "budget-hearings": 10, "audit-committee": 1,
        "investment-committee": 2, "purchasing-committee": 3, "delinquent-tax-committee": 1}
    sb = sorted(by["school-board"], key=lambda r: r["date"])
    assert sb[0]["date"] == "2026-01-13" and sb[-1]["date"] == "2026-11-17"
    assert {r["kind"] for r in sb} == {"study-session", "formal"}
    # other folders on the page (County Commission, Beer Board, the RPC's nested folders) are not read
    assert not any("County Commission" in r["url"] or "Regional Planning" in r["url"] for r in rows)


def test_urls_are_the_page_links_resolved_and_every_one_is_fetchable(rows):
    r = next(r for r in rows if r["printed"] == "05-19-26 - Formal Board Agenda")
    assert r["url"] == ("https://montgomerytn.gov/storage/departments/mayor/calendar-files/School%20System/"
                        "05-19-26%20-%20%20Formal%20Board%20Agenda.pdf")
    assert r["file"] == "05-19-26 - Formal Board Agenda.pdf"     # the link text, whitespace joined
    assert all(r["fetch"] and r["on_page"] for r in rows)
    assert all(" " not in r["url"] for r in rows)


def test_labels_kept_as_printed_and_ids(rows):
    by_id = {(r["body"], r["id"]): r for r in rows}
    sp = by_id[("budget-committee", "2026-07-23-special")]
    assert sp["notes"] == ["SPECIAL CALLED"] and not sp["cancelled"]
    rs = by_id[("purchasing-committee", "2026-01-14-regular")]
    assert rs["notes"] == ["rescheduled"] and not rs["cancelled"]
    am, pm = by_id[("budget-hearings", "2026-05-05-hearing-0900")], by_id[("budget-hearings", "2026-05-05-hearing-1300")]
    assert (am["time"], pm["time"]) == ("9AM", "1PM")


def test_cancelled_label_from_another_folder_is_read_the_same_way():
    page = ("<dl><dt>School System</dt><dd><ul><li><a href='/storage/departments/mayor/calendar-files/School System/"
            "CANCELED 09-14-26 Formal Board Agenda.pdf'>CANCELED 09-14-26 Formal Board Agenda.pdf</a></li>"
            "<li><a href='/storage/departments/mayor/calendar-files/School System/Agenda.pdf'>Agenda.pdf</a></li>"
            "<li><a href='https://example.com/x/09-15-26 Agenda.pdf'>09-15-26 Agenda.pdf</a></li>"
            "</ul></dd></dl>")
    rows, problems = cc.parse_listing(page, cc.load_config())
    assert rows[0]["cancelled"] and rows[0]["notes"] == ["CANCELED"] and rows[0]["kind"] == "formal"
    assert not rows[1]["fetch"]                                 # another host: kept, never requested
    assert any("Agenda.pdf" in p and "no date" in p for p in problems)
    assert any("Budget Committee" in p and "not on the page" in p for p in problems)


def test_a_page_with_no_folders_is_an_error(cfg):
    with pytest.raises(cc.ListingError):
        cc.parse_listing("<html><body>Not found</body></html>", cfg)


def test_rollover_keeps_rows_no_longer_on_the_page(rows):
    old = rows
    new = [r for r in rows if r["date"] >= "2026-11-01"]
    merged = cc.merge_rows(old, [{k: v for k, v in r.items() if k != "id"} for r in new])
    assert len(merged) == len(rows)
    gone = [r for r in merged if not r["on_page"]]
    assert len(gone) == len(rows) - len(new) and all(r["date"] < "2026-11-01" for r in gone)
    assert sorted(r["id"] for r in merged) == sorted(r["id"] for r in rows)


class FakeFetcher:
    """Answers the page and a PDF for every agenda; counts requests; a 304 for conditional GETs."""

    def __init__(self, page=PAGE, block_after=None):
        self.page, self.calls, self.log, self.block_after = page, [], [], block_after

    def limit_hosts(self, hosts, n):
        pass

    def get(self, url):
        self.calls.append(("get", url))
        if self.block_after is not None and len(self.calls) > self.block_after:
            raise cc.HostBlocked("403")
        if url.endswith(".php"):
            return 200, self.page.encode(), {"Content-Type": "text/html"}
        return 200, b"%PDF-1.4 " + url.encode(), {"ETag": '"x"'}

    def get_if_changed(self, url, etag=None, last_modified=None):
        self.calls.append(("cond", url))
        return 304, b"", {}


def test_fetch_stores_each_agenda_once_and_rechecks_only_future_meetings(tmp_path, cfg):
    store = Store(manifest_path=tmp_path / "manifest.json", root=tmp_path / "store")
    log = cc.new_log()
    rows = cc.cmd_fetch(cfg, store, tmp_path / "listing.json", log, fetcher=FakeFetcher(), today=date(2026, 11, 16))
    assert len(rows) == 50 and log["fetched"] == {"new": 50} and not log["failures"]
    assert json.loads((tmp_path / "listing.json").read_text()) == rows
    f2 = FakeFetcher()
    log2 = cc.new_log()
    cc.cmd_fetch(cfg, store, tmp_path / "listing.json", log2, fetcher=f2, today=date(2026, 11, 16))
    # the meetings on or after today (school board 11-17, Budget Committee 11-18) are asked again, conditionally
    assert [c for c in f2.calls if c[0] == "cond"] and all(c[0] == "cond" for c in f2.calls[1:])
    assert log2["fetched"] == {"cached": 48, "not_modified": 2}


def test_fetch_limit_and_a_block_stop_the_run(tmp_path, cfg):
    store = Store(manifest_path=tmp_path / "manifest.json", root=tmp_path / "store")
    log = cc.new_log()
    cc.cmd_fetch(cfg, store, tmp_path / "listing.json", log, fetcher=FakeFetcher(), limit=5, today=date(2026, 11, 16))
    assert log["fetched"] == {"new": 5, "over_limit": 45}
    log = cc.new_log()
    f = FakeFetcher(block_after=3)
    cc.cmd_fetch(cfg, store, tmp_path / "listing.json", log, fetcher=f, today=date(2026, 11, 16))
    assert len(f.calls) == 4 and log["failures"][-1]["stop"]


def test_a_page_not_read_leaves_the_listing_alone(tmp_path, cfg):
    lp = tmp_path / "listing.json"
    lp.write_text("[]\n")
    store = Store(manifest_path=tmp_path / "manifest.json", root=tmp_path / "store")
    log = cc.new_log()
    assert cc.cmd_fetch(cfg, store, lp, log, fetcher=FakeFetcher(page="<html></html>")) is None
    assert lp.read_text() == "[]\n" and log["failures"][0]["stage"] == "listing"


def _read(p):
    return ["Budget Committee\nJanuary 21, 2026\n\n26-2-1*   Resolution one\n\nADJOURN\n"]


def test_daily_step_writes_then_an_empty_store_keeps_the_committed_file(tmp_path, cfg):
    store = Store(manifest_path=cc.paths(cfg, tmp_path)["manifest"], root=tmp_path / "store")
    log = {}
    code = cc.run_step(log, offline=False, fetcher=FakeFetcher(), cfg=cfg, root=tmp_path, store=store,
                       today=date(2026, 11, 16), read=_read, count=lambda p: 1)
    p = cc.paths(cfg, tmp_path)
    assert code == 0 and log["county_committees"]["exit"] == 0, log
    facts = json.loads(p["facts"].read_text())
    assert len(facts["meetings"]) == 50 and len(facts["sources"]) == 50
    before = {k: p[k].read_bytes() for k in ("facts", "listing", "manifest")}
    empty = Store(manifest_path=p["manifest"], root=tmp_path / "empty-store")     # a fresh checkout: no PDFs
    log = {}
    assert cc.run_step(log, offline=True, cfg=cfg, root=tmp_path, store=empty, read=_read, count=lambda p: 1) == 0
    assert log["county_committees"]["kept"] and "nothing changed" in log["county_committees"]["status"]
    assert {k: p[k].read_bytes() for k in before} == before


def test_daily_step_blocked_page_changes_nothing(tmp_path, cfg):
    log = {}
    code = cc.run_step(log, offline=False, fetcher=FakeFetcher(block_after=0), cfg=cfg, root=tmp_path,
                       store=Store(manifest_path=tmp_path / "m.json", root=tmp_path / "s"), read=_read)
    assert code == 2 and "stopped" in log["county_committees"]["status"]
    assert not cc.paths(cfg, tmp_path)["facts"].exists()


@pytest.mark.parametrize("href", ["/storage/departments/mayor/calendar-files/School System/../../secret/x.pdf",
                                  "/storage/departments/mayor/calendar-files/School System/%2e%2e/%2e%2e/x.pdf",
                                  "/storage/departments/mayor/calendar-files/./School System/x.pdf",
                                  "/storage/departments/mayor/calendar-files/School System/x.pdf?y=1",
                                  "/storage/other/x.pdf"])
def test_fetchable_refuses_a_path_out_of_the_calendar_files(cfg, href):
    assert not cfg.fetchable("https://montgomerytn.gov" + href.replace(" ", "%20"))


def test_a_non_https_link_is_a_problem_not_a_row(cfg):
    page = ("<dl><dt>School System</dt><dd><ul>"
            "<li><a href='http://montgomerytn.gov/storage/departments/mayor/calendar-files/School System/"
            "09-14-26 Formal Board Agenda.pdf'>09-14-26 Formal Board Agenda.pdf</a></li>"
            "<li><a href='javascript:alert(1)'>09-15-26 Agenda.pdf</a></li>"
            "<li><a href='mailto:x@example.org'>09-16-26 Agenda.pdf</a></li></ul></dd></dl>")
    rows, problems = cc.parse_listing(page, cfg)
    assert rows == [] and sum("not an https link" in p for p in problems) == 3


def test_an_agenda_over_the_size_cap_is_not_stored(tmp_path, cfg, monkeypatch):
    monkeypatch.setattr(cc, "MAX_AGENDA_BYTES", 10)
    store = Store(manifest_path=tmp_path / "manifest.json", root=tmp_path / "store")
    log = cc.new_log()
    cc.cmd_fetch(cfg, store, tmp_path / "listing.json", log, fetcher=FakeFetcher(), limit=2, today=date(2026, 11, 16))
    assert store.current() == [] and all("MAX_AGENDA_BYTES" in f["error"] for f in log["failures"])


class CappedFetcher(FakeFetcher):
    """A fetcher with its own byte cap (like PoliteFetcher.max_bytes): records the cap each agenda is read under."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.max_bytes, self.caps = 200 * 1024 * 1024, []

    def get(self, url):
        self.caps.append((url.endswith(".php"), self.max_bytes))
        return super().get(url)


def test_agendas_are_read_under_the_20_mb_cap_and_the_fetcher_gets_its_cap_back(tmp_path, cfg):
    store = Store(manifest_path=tmp_path / "manifest.json", root=tmp_path / "store")
    f = CappedFetcher()
    cc.cmd_fetch(cfg, store, tmp_path / "listing.json", cc.new_log(), fetcher=f, limit=3, today=date(2026, 11, 16))
    agendas = [cap for page, cap in f.caps if not page]
    assert agendas and set(agendas) == {cc.MAX_AGENDA_BYTES}
    assert f.max_bytes == 200 * 1024 * 1024       # a shared fetcher (collector run) is left as it was


def test_the_fetcher_gets_its_cap_back_when_a_fetch_raises(tmp_path, cfg):
    store = Store(manifest_path=tmp_path / "manifest.json", root=tmp_path / "store")
    f = CappedFetcher()
    f.get_if_changed = None                        # not called: a cold store
    real = f.get
    def boom(url):
        if not url.endswith(".php"):
            raise RuntimeError("x")
        return real(url)
    f.get = boom
    with pytest.raises(RuntimeError):
        cc.cmd_fetch(cfg, store, tmp_path / "listing.json", cc.new_log(), fetcher=f, today=date(2026, 11, 16))
    assert f.max_bytes == 200 * 1024 * 1024
