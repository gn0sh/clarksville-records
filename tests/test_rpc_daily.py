"""The Regional Planning Commission step of the daily run (collector/rpc.py run_step, collector/__main__.py run_rpc).

Polite (robots.txt first, the crawl-delay between requests, our User-Agent), stopped by the first 403/429 with no
further request to the host, and all or nothing on the committed files: listing.json, manifest.json, changes.jsonl
and rpc.json change only on a complete run. No network: every request goes to a fake opener."""
import json
import re
from pathlib import Path

import pytest

import collector.__main__ as M
from collector import rpc, rpc_agenda
from collector.fetch import USER_AGENT, PoliteFetcher
from collector.store import Store
from collector.tests.test_fetch import Clock, FakeNet

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "collector" / "tests" / "fixtures" / "rpc"
CFG = rpc.load_config()
LISTING = CFG.listing_url
ROBOTS = "https://www.cmcrpc.com/robots.txt"
ROBOTS_TXT = b"User-agent: *\ncrawl-delay: 10\n"
PAGE = (FIX / "listing.html").read_text(encoding="utf-8")
NEW_URL = "https://www.cmcrpc.com/wp2025/wp-content/uploads/2026/11/Agenda-11.24.2026.pdf"
NEW_ROW = ('<tr class="kb-table-row">\n<td><p>11/24/2026</p></td>\n'
           f'<td><p><a href="{NEW_URL}">Agenda</a></p></td>\n<td><p>Minutes</p></td>\n</tr>\n')
FIRST_ROW = '<tr class="kb-table-row">\n<td class="kb-table-data"><p class="wp-block-paragraph">10/27/2026'
AGENDA_PAGES = (FIX / "agenda_2026-10-27.txt").read_text(encoding="utf-8").split("\f")    # every PDF reads as this one
PAGE_NEW = PAGE.replace(FIRST_ROW, NEW_ROW + FIRST_ROW)
assert PAGE_NEW != PAGE


def doc_urls(page: str = PAGE) -> list[str]:
    """Every document the listing asks the collector to fetch, in listing order, once each."""
    rows, _ = rpc.parse_listing(page, CFG)
    return list(dict.fromkeys(d["url"] for r in rows for d in r["docs"] if d["fetch"]))


def body_for(url: str) -> bytes:
    return (b"PK\x03\x04 " if url.lower().endswith(".docx") else b"%PDF-1.4 ") + url.encode()


def routes(page: str = PAGE, **override) -> dict:
    out = {ROBOTS: (200, ROBOTS_TXT), LISTING: (200, page.encode())}
    out.update({u: (200, body_for(u)) for u in doc_urls(page)})
    out.update(override)
    return out


def fake_build(cfg, rows, store, audit_path=None):
    """The real build with the PDF text and OCR readers replaced (no poppler, no tesseract in a unit test)."""
    def no_ocr(pdf, sha, pages):
        raise RuntimeError("no OCR in this test")
    return rpc_agenda.build(cfg, rows, store, extract=lambda p: AGENDA_PAGES, ocr=no_ocr, audit_path=audit_path)


class Site:
    """A checkout in tmp_path: the committed files under data/, the store beside them, and a fake cmcrpc.com."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.p = rpc.paths(CFG, tmp_path)
        self.store_dir = tmp_path / "store"
        self.calls: list[str] = []
        self.slept: list[float] = []

    def run(self, net_routes: dict | None = None, offline: bool = False, build=fake_build, cap=rpc.DAILY_FETCH_CAP):
        log: dict = {}
        fetcher = None
        net = None
        if not offline:
            net, clock = FakeNet(net_routes if net_routes is not None else routes()), Clock()
            fetcher = PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: [])
        store = Store(manifest_path=self.p["manifest"], root=self.store_dir)
        code = rpc.run_step(log, offline, fetcher=fetcher, cfg=CFG, root=self.root, store=store, build=build,
                            max_requests=cap)
        if net is not None:
            self.calls = [u for u, _ in net.calls]
            self.agents = {ua for _, ua in net.calls}
            self.slept = clock.slept
        else:
            self.calls = []
        assert log["rpc"]["exit"] == code
        return code, log["rpc"]

    def committed(self) -> dict:
        """The bytes of every file the step may commit (None when absent)."""
        return {k: (self.p[k].read_bytes() if self.p[k].is_file() else None)
                for k in ("listing", "manifest", "changes", "facts")}

    def docs_requested(self) -> list[str]:
        return [u for u in self.calls if u not in (ROBOTS, LISTING)]

    def facts(self) -> dict:
        return json.loads(self.p["facts"].read_text(encoding="utf-8"))

    def empty_store(self, keep: int = 0) -> None:
        for f in sorted(self.store_dir.iterdir())[keep:]:
            f.unlink()


@pytest.fixture
def site(tmp_path):
    return Site(tmp_path)


@pytest.fixture
def seeded(site):
    """A checkout whose last run was complete: the committed files and a full store."""
    code, _ = site.run()
    assert code == rpc.STEP_OK
    return site


# ------------------------------------------------------------------ a complete run
def test_complete_run_is_polite_and_writes_every_file(site):
    code, out = site.run()
    assert code == rpc.STEP_OK and out["changed"] is True
    assert site.calls[:2] == [ROBOTS, LISTING]                       # robots.txt before anything else
    assert site.docs_requested() == doc_urls()                       # each listed document once, none built
    assert all(u.startswith("https://www.cmcrpc.com/") for u in site.calls)      # Drive and YouTube never requested
    assert site.agents == {USER_AGENT}
    assert len(site.slept) == len(site.calls) - 1 and min(site.slept) >= 9.99    # the crawl-delay, every request
    facts = site.facts()
    assert facts["motion_rules"] and len(facts["meetings"]) == 11
    assert sum(1 for m in facts["meetings"] for d in m["documents"] if d["source_id"]) >= len(doc_urls())
    assert all(v is not None for k, v in site.committed().items() if k != "changes")
    assert json.loads((site.root / "build" / "rpc-report.json").read_text())["exit"] == 0


def test_second_run_asks_for_the_listing_only_and_changes_nothing(seeded):
    before = seeded.committed()
    code, out = seeded.run()
    assert code == rpc.STEP_OK and out["changed"] is False
    assert seeded.calls == [ROBOTS, LISTING]
    assert seeded.committed() == before


def test_a_newly_listed_document_is_fetched_and_shown(seeded):
    code, _ = seeded.run(routes(PAGE_NEW))
    assert code == rpc.STEP_OK
    assert seeded.docs_requested() == [NEW_URL]
    m = {m["id"]: m for m in seeded.facts()["meetings"]}["2026-11-24-regular"]
    assert m["documents"][0]["url"] == NEW_URL and m["documents"][0]["source_id"]
    assert NEW_URL in {e["url"] for e in json.loads(seeded.p["manifest"].read_text())}


# ------------------------------------------------------------------ a block: stop, keep nothing
@pytest.mark.parametrize("status", [403, 429])
def test_block_on_a_new_document_stops_and_leaves_the_committed_files(seeded, status):
    before = seeded.committed()
    code, out = seeded.run(routes(PAGE_NEW, **{NEW_URL: (status, b"slow down")}))
    assert code == rpc.STEP_FETCH and "HostBlocked" in out["status"]
    assert seeded.calls == [ROBOTS, LISTING, NEW_URL]                # asked once, never again
    assert seeded.committed() == before                              # not even the new listing row is kept


@pytest.mark.parametrize("status", [403, 429])
def test_block_part_way_through_a_cold_store_makes_no_further_request(seeded, status):
    before = seeded.committed()
    seeded.empty_store()
    urls = doc_urls()
    code, out = seeded.run(routes(**{urls[3]: (status, b"")}))
    assert code == rpc.STEP_FETCH
    assert seeded.docs_requested() == urls[:4]                       # the fourth answered the block: nothing after it
    assert out["fetch"]["fetched"]["not_tried"] == len(urls) - 4
    assert seeded.committed() == before
    # the next run (the next day) goes on from the bytes already stored: no document is asked for twice
    code, _ = seeded.run()
    assert code == rpc.STEP_OK and seeded.docs_requested() == urls[3:]
    assert seeded.committed() == before


@pytest.mark.parametrize("blocked", [ROBOTS, LISTING])
@pytest.mark.parametrize("status", [403, 429])
def test_block_before_any_document_writes_nothing(site, blocked, status):
    code, out = site.run(routes(**{blocked: (status, b"")}))
    assert code == rpc.STEP_FETCH and "nothing changed" in out["status"]
    assert site.calls == ([ROBOTS] if blocked == ROBOTS else [ROBOTS, LISTING])
    assert site.committed() == {"listing": None, "manifest": None, "changes": None, "facts": None}


def test_robots_disallow_is_obeyed(seeded):
    before = seeded.committed()
    code, out = seeded.run(routes(**{ROBOTS: (200, b"User-agent: *\nDisallow: /\n")}))
    assert code == rpc.STEP_FETCH and "RobotsDisallowed" in out["status"]
    assert seeded.calls == [ROBOTS]
    assert seeded.committed() == before


def test_listing_page_that_changed_fails_and_keeps_the_record(seeded):
    before = seeded.committed()
    code, out = seeded.run(routes(**{LISTING: (200, b"<html><body>We moved</body></html>")}))
    assert code == rpc.STEP_FETCH and "ListingError" in out["status"]
    assert seeded.committed() == before


# ------------------------------------------------------------------ a cold store: a few documents per run
def test_cold_store_is_filled_a_few_documents_per_run(seeded):
    before = seeded.committed()
    seeded.empty_store()
    urls = doc_urls()
    asked: list[str] = []
    codes = []
    for _ in range(len(urls)):
        code, out = seeded.run(cap=4)
        codes.append(code)
        assert len(seeded.docs_requested()) <= 4
        asked += seeded.docs_requested()
        assert seeded.committed() == before                          # nothing is committed until the store is whole
        if code == rpc.STEP_OK:
            break
        assert code == rpc.STEP_FILLING and "filling the store" in out["status"]
    assert codes[-1] == rpc.STEP_OK and codes[:-1] == [rpc.STEP_FILLING] * (len(codes) - 1) and len(codes) > 1
    assert asked == urls                                             # every document once over all the runs


def test_more_new_documents_than_the_cap_requests_none(site):
    code, out = site.run(cap=3)
    assert code == rpc.STEP_FETCH and "TooManyNew" in out["status"]
    assert site.calls == [ROBOTS, LISTING]
    assert site.committed() == {"listing": None, "manifest": None, "changes": None, "facts": None}


def test_the_cap_counts_every_request_robots_and_listing_included(seeded):
    """The hard cap is on requests to the RPC's hosts, not documents: robots.txt, the listing, every document."""
    assert rpc.DAILY_FETCH_CAP == 40
    seeded.empty_store()
    code, out = seeded.run(cap=6)
    assert code == rpc.STEP_FILLING
    assert len(seeded.calls) == 6 and seeded.calls[:2] == [ROBOTS, LISTING] and len(seeded.docs_requested()) == 4
    assert "at most 6 requests per run" in out["status"]


def test_retries_use_the_cap_and_the_request_past_it_is_never_made(seeded):
    seeded.empty_store()
    urls = doc_urls()
    code, out = seeded.run(routes(**{urls[0]: (503, b"busy"), urls[1]: (503, b"busy")}), cap=6)
    assert code == rpc.STEP_FILLING
    assert len(seeded.calls) == 6                                   # robots, listing, 2 x (document + its retry)
    assert seeded.docs_requested() == [urls[0], urls[0], urls[1], urls[1]]
    assert len(seeded.slept) == 5 and min(seeded.slept) >= 9.99     # the crawl-delay before every one


def test_a_persistent_503_on_a_cold_record_never_loops_as_filling(site):
    """rpc-daily/filling-livelock: cap = documents + 2 (robots, listing) with one document always 503. Its retry takes
    the last document's request; before the fix every run was exit 6 forever, fetching the same new documents."""
    urls = doc_urls()
    net = routes(**{urls[3]: (503, b"busy")})
    for _ in range(3):
        code, out = site.run(net, cap=len(urls) + 2)
        assert code == rpc.STEP_FETCH and "cap of" in out["status"]          # hard: an issue opens, a person looks
        assert len(site.calls) == len(urls) + 2
        assert site.committed() == {"listing": None, "manifest": None, "changes": None, "facts": None}


def test_filling_requests_gaps_only_and_the_new_documents_after(seeded):
    """With more to fetch than one run allows, a run asks only for the manifest's gaps (kept across runs); the newly
    listed document is asked for by the first run that can finish, and every document is asked for once."""
    seeded.empty_store()
    runs, codes = [], []
    for _ in range(10):
        code, _ = seeded.run(routes(PAGE_NEW), cap=8)
        codes.append(code)
        runs.append(seeded.docs_requested())
        if code != rpc.STEP_FILLING:
            break
    assert codes[-1] == rpc.STEP_OK and len(codes) > 1
    assert all(NEW_URL not in r for r in runs[:-1]) and runs[-1].count(NEW_URL) == 1   # only in the run that finishes
    assert sorted(u for r in runs for u in r) == sorted(doc_urls(PAGE_NEW))           # each document once
    assert NEW_URL in {e["url"] for e in json.loads(seeded.p["manifest"].read_text())}


PAGE_NEW_LAST = PAGE.replace("<tr><td><p>13/45/2022", NEW_ROW + "<tr><td><p>13/45/2022", 1)   # new one asked for last


def test_a_cut_off_after_gaps_were_filled_is_filling_and_heals_next_run(seeded):
    """rpc-daily/cut-off-self-heals: the cap ran out on the new document only because a gap's retry took a request,
    but the run filled gaps, so the next run has room: exit 6 (not a failure), then 0."""
    assert PAGE_NEW_LAST != PAGE and doc_urls(PAGE_NEW_LAST)[-1] == NEW_URL
    seeded.empty_store()
    urls = doc_urls()
    cap = len(urls) + 1 + 2                                        # every gap and the new one, robots and listing
    code, out = seeded.run(routes(PAGE_NEW_LAST, **{urls[0]: (503, b"busy")}), cap=cap)
    assert code == rpc.STEP_FILLING and out["fetch"]["fetched"]["new_cut_off"] == 1
    assert NEW_URL not in seeded.docs_requested()
    code, _ = seeded.run(routes(PAGE_NEW_LAST), cap=cap)
    assert code == rpc.STEP_OK and seeded.docs_requested() == [urls[0], NEW_URL]


def test_stall_messages_name_the_capped_recovery(site):
    code, out = site.run(cap=3)                                    # TooManyNew
    assert code == rpc.STEP_FETCH and "repeats every day until someone acts" in out["status"]
    assert "python -m collector rpc fetch --limit 30" in rpc.RECOVERY
    assert "python -m collector rpc fetch --limit" in out["status"]


def test_the_by_hand_fetch_is_capped_and_keeps_what_it_fetched(site):
    """The recovery: `rpc fetch --limit N` asks for at most N documents the store lacks, never more than the cap
    (robots.txt and the listing included), waits the crawl-delay, and keeps them in the manifest, so the next day's
    call goes on where it stopped."""
    urls = doc_urls()
    asked = []
    for _ in range(4):
        net, clock = FakeNet(routes()), Clock()
        f = PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: [])
        store = Store(manifest_path=site.p["manifest"], root=site.store_dir)
        log = rpc.new_log()
        rpc.cmd_fetch(CFG, store, site.p["listing"], log, fetcher=f, limit=5, max_requests=rpc.DAILY_FETCH_CAP,
                      keeps_manifest=True)
        calls = [u for u, _ in net.calls]
        docs = [u for u in calls if u not in (ROBOTS, LISTING)]
        assert len(docs) <= 5 and len(calls) <= rpc.DAILY_FETCH_CAP and min(clock.slept) >= 9.99
        asked += docs
    assert asked == urls                                           # 5 + 5 + 5 + 1, in listing order, once each
    assert {e["url"] for e in json.loads(site.p["manifest"].read_text())} == set(urls)


def test_the_by_hand_fetch_command_uses_the_cap(monkeypatch):
    seen = {}
    monkeypatch.setattr(rpc, "cmd_fetch", lambda *a, **k: seen.update(k) or [])
    monkeypatch.setattr(rpc, "write_json", lambda path, obj: False)      # no report into the real build/
    assert rpc.main(["fetch", "--limit", "30"]) == 0
    assert seen["limit"] == 30 and seen["max_requests"] == rpc.DAILY_FETCH_CAP == 40 and seen["keeps_manifest"]


def test_a_cap_too_small_for_the_listing_is_a_fetch_failure_with_no_request_past_it(site):
    code, out = site.run(cap=1)
    assert code == rpc.STEP_FETCH and "RequestCapReached" in out["status"]
    assert site.calls == [ROBOTS]
    assert site.committed() == {"listing": None, "manifest": None, "changes": None, "facts": None}


def test_the_daily_step_defaults_to_the_cap():
    import inspect
    assert inspect.signature(rpc.run_step).parameters["max_requests"].default == rpc.DAILY_FETCH_CAP


# ------------------------------------------------------------------ never a smaller or half-read record
def test_one_failed_new_document_is_listed_with_no_source(seeded):
    code, _ = seeded.run(routes(PAGE_NEW, **{NEW_URL: (404, b"")}))
    assert code == rpc.STEP_OK
    m = {m["id"]: m for m in seeded.facts()["meetings"]}["2026-11-24-regular"]
    assert m["documents"][0]["fetched"] is False and m["documents"][0]["source_id"] is None
    assert len(seeded.facts()["meetings"]) == 12


def test_a_stored_document_that_cannot_be_fetched_again_refuses_the_result(seeded):
    before = seeded.committed()
    seeded.empty_store()
    urls = doc_urls()
    code, out = seeded.run(routes(**{urls[0]: (404, b"")}))
    assert code == rpc.STEP_REFUSED and "not in the store" in out["status"]
    assert seeded.committed() == before


def test_a_result_that_drops_a_meeting_is_refused(seeded):
    before = seeded.committed()
    code, out = seeded.run(routes(PAGE.replace("10/27/2026", "10/28/2026")))     # the id of a meeting changes
    assert code == rpc.STEP_REFUSED and "would drop 1 of the 11" in out["status"]
    assert seeded.committed() == before


def test_a_document_that_is_no_longer_read_is_refused(seeded):
    old = seeded.facts()
    read = next(m for m in old["meetings"] if m["agenda_read_by"])
    new = json.loads(json.dumps(old))
    next(m for m in new["meetings"] if m["id"] == read["id"])["agenda_read_by"] = None
    assert "the agenda was read" in rpc.shrink_reason(old, new)
    lost = json.loads(json.dumps(old))
    for d in next(m for m in lost["meetings"] if m["id"] == read["id"])["documents"]:
        d["source_id"] = None
    assert "had a source" in rpc.shrink_reason(old, lost)
    moved = json.loads(json.dumps(old))                 # the same agenda posted again under another link: no loss
    next(m for m in moved["meetings"] if m["id"] == read["id"])["documents"][0]["url"] += "?v=2"
    assert rpc.shrink_reason(old, moved) is None and rpc.shrink_reason(old, old) is None


def test_case_shortfall_is_a_gate_and_keeps_the_record(seeded):
    before = seeded.committed()

    def short(cfg, rows, store, audit_path=None):
        facts, summary = fake_build(cfg, rows, store)
        return facts, {**summary, "case_shortfalls": ["2026-11-24-regular"]}
    code, out = seeded.run(routes(PAGE_NEW), build=short)
    assert code == rpc.STEP_GATE and "2026-11-24-regular" in out["status"]
    assert seeded.committed() == before


def test_an_unexpected_error_never_raises_and_keeps_the_record(seeded):
    before = seeded.committed()

    def boom(cfg, rows, store, audit_path=None):
        raise ValueError("parser bug")
    code, out = seeded.run(routes(PAGE_NEW), build=boom)
    assert code == rpc.STEP_ERROR and "ValueError: parser bug" in out["status"]
    assert seeded.committed() == before


def test_a_failed_rpc_json_write_leaves_the_committed_record(seeded, monkeypatch):
    """rpc-daily/restore-misses-rpc-json: a write that dies part way (disk full, a kill) leaves rpc.json whole, and
    the snapshot puts every committed file back, rpc.json included."""
    assert "facts" in rpc.COMMITTED
    before = seeded.committed()
    real = Path.write_text

    def dies_on_rpc_json(self, text, *a, **k):
        if self.name.startswith("rpc.json"):
            real(self, text[:20], *a, **k)                 # a short write, then the failure
            raise OSError("No space left on device")
        return real(self, text, *a, **k)
    monkeypatch.setattr(Path, "write_text", dies_on_rpc_json)
    code, out = seeded.run(routes(PAGE_NEW))
    monkeypatch.undo()
    assert code == rpc.STEP_ERROR and "No space left" in out["status"]
    assert seeded.committed() == before
    assert not list(seeded.p["facts"].parent.glob("*.part"))                  # nothing half written is left


def test_committed_files_are_written_through_a_part_file(tmp_path, monkeypatch):
    seen = []
    real = Path.replace
    monkeypatch.setattr(Path, "replace", lambda self, t: seen.append((self.name, Path(t).name)) or real(self, t))
    assert rpc.write_json(tmp_path / "rpc.json", {"a": 1}) is True
    assert seen == [("rpc.json.part", "rpc.json")] and json.loads((tmp_path / "rpc.json").read_text()) == {"a": 1}


# ------------------------------------------------------------------ offline
def test_offline_with_a_partial_store_keeps_the_record_and_is_not_a_failure(seeded):
    before = seeded.committed()
    seeded.empty_store(keep=2)
    code, out = seeded.run(offline=True)
    assert code == rpc.STEP_OK and out["kept"] is True and "not in the store" in out["status"]
    assert seeded.calls == [] and seeded.committed() == before


def test_offline_with_the_whole_store_rebuilds_without_a_request(seeded):
    before = seeded.committed()
    seeded.p["facts"].write_text(json.dumps({**seeded.facts(), "motion_rules": None}), encoding="utf-8")
    code, out = seeded.run(offline=True)
    assert code == rpc.STEP_OK and out["changed"] is True
    assert seeded.calls == [] and seeded.committed() == before


def test_offline_in_a_fresh_checkout_does_nothing(site):
    code, out = site.run(offline=True)
    assert code == rpc.STEP_OK and out["kept"] is True
    assert site.committed() == {"listing": None, "manifest": None, "changes": None, "facts": None}


def test_the_real_checkout_step_is_offline_safe(tmp_path, monkeypatch):
    """`collector run --offline` in a checkout with no RPC store bytes: the committed RPC files are not touched."""
    monkeypatch.setenv("RECORDS_STORE", str(tmp_path / "empty-store"))
    p = rpc.paths(CFG)
    before = {k: p[k].read_bytes() for k in ("listing", "manifest", "facts")}
    monkeypatch.setattr(rpc, "write_json", lambda path, obj: False)      # no report into the real build/
    log: dict = {}
    assert rpc.run_step(log, True) == rpc.STEP_OK and log["rpc"]["kept"] is True
    assert {k: p[k].read_bytes() for k in before} == before


# ------------------------------------------------------------------ `collector run`: the step's own exit code
@pytest.fixture
def county_run(tmp_path, monkeypatch):
    """`collector run --offline` with every other step replaced, so only the exit-code rule is under test."""
    import collector.export
    import sitegen.build
    report = {"gates": {"roll_calls": 1, "verified": 1, "verified_rate": 1.0, "held_back": 0,
                        "held_back_source_error": 0, "verified_rate_gate": {"min": 0.9, "pass": True},
                        "g4": {"status": "pass", "uniform_share": 0.0, "flagged": []}}, "pass": True}
    state = {"fail": False, "rpc": 0, "order": [], "rpc_args": None}

    class B:
        unresolved = {}

    def build(store, log, use_ocr=True):
        log["parsed"] = 1
        if state["fail"]:
            log["failures"].append({"stage": "parse", "error": "boom"})
        return {"meetings": [{"id": "m"}]}, report, B()

    def run_rpc(log, offline, fetcher=None, allow_shrink=False):
        state["order"].append("rpc")
        state["rpc_args"] = (offline, fetcher)
        log["rpc"] = {"exit": state["rpc"], "status": "stopped, nothing changed: HostBlocked: HTTP 429"}
        return state["rpc"]
    for name, value in (("FACTS", tmp_path / "facts.json"), ("BUILD", tmp_path / "build"),
                        ("MANIFEST", tmp_path / "manifest.json"), ("FINANCE", tmp_path / "finance.json"),
                        ("cmd_build", build), ("run_finance", lambda store, log, offline, **kw: 0),
                        ("run_agendas", lambda log, offline, fetcher=None: state["order"].append("agendas")),
                        ("run_rpc", run_rpc), ("shrink_reason", lambda facts, log, path: None),
                        ("name_candidates", lambda b, roster: {}), ("load_seat_rows", lambda: None)):
        monkeypatch.setattr(M, name, value)
    monkeypatch.setattr(sitegen.build, "build", lambda *a, **k: state["order"].append("site"))
    monkeypatch.setattr(sitegen.build, "write_publish_manifest", lambda *a, **k: None)
    monkeypatch.setattr(collector.export, "export_site", lambda *a, **k: [])
    return state


@pytest.mark.parametrize("rpc_code,county_fails,code", [
    (0, False, 0),
    (rpc.STEP_FETCH, False, M.RPC_FAILED), (rpc.STEP_GATE, False, M.RPC_FAILED),
    (rpc.STEP_REFUSED, False, M.RPC_FAILED), (rpc.STEP_ERROR, False, M.RPC_FAILED),
    (rpc.STEP_FILLING, False, M.RPC_FILLING),
    (rpc.STEP_FETCH, True, 2), (rpc.STEP_FILLING, True, 2),          # the county's own failure keeps its code
])
def test_run_reports_the_rpc_step_with_its_own_code(county_run, capsys, tmp_path, rpc_code, county_fails, code):
    county_run["rpc"], county_run["fail"] = rpc_code, county_fails
    assert M.main(["run", "--offline"]) == code
    out = capsys.readouterr().out
    assert ("gh issue create" in out) == (code not in (0, M.RPC_FILLING))
    if code == M.RPC_FAILED:
        assert "Collector RPC step failed" in out and "HostBlocked" in out
    assert county_run["order"] == ["agendas", "rpc", "site"]         # before the site build, which reads rpc.json
    assert county_run["rpc_args"] == (True, None)                    # offline: no fetcher, no request
    assert json.loads((tmp_path / "build" / "run-log.json").read_text())["rpc"]["exit"] == rpc_code
    assert (M.RPC_FAILED, M.RPC_FILLING, M.KEPT) == (5, 6, 7) and not {5, 6, 7} & {0, 2, 3, M.REFUSED}
    assert M.KEPT not in {rpc.STEP_OK, rpc.STEP_ERROR, rpc.STEP_FETCH, rpc.STEP_GATE, rpc.STEP_REFUSED,
                          rpc.STEP_FILLING}                  # rpc.py's step codes never collide with 7


def test_run_rpc_shares_the_runs_fetcher(monkeypatch):
    seen = {}
    monkeypatch.setattr(rpc, "run_step",
                        lambda log, offline, fetcher=None, allow_shrink=False: seen.update(a=(offline, fetcher)) or 0)
    f = object()
    assert M.run_rpc({}, False, fetcher=f) == 0 and seen["a"] == (False, f)


# ------------------------------------------------------------------ the workflow's Collect step
def test_workflow_collect_step_treats_only_the_rpc_codes_as_warnings():
    """One source must not freeze the daily refresh: the RPC step's own codes (5 failed, 6 filling) and the city's
    KEPT (7, ADR 0006) are warnings; every other county code and every other city code still fails the step."""
    text = (ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8")
    step = text.split("- name: Collect (polite fetch, parse, verify)")[1].split("\n      - name:")[0]
    lines = [ln.strip() for ln in step.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert 'python -m collector run "${shrink[@]}"; county=$?' in lines
    assert 'if [ "$county" = 6 ]; then' in lines and 'elif [ "$county" = 5 ]; then' in lines
    assert lines.count("rpc=failed; county=0") == 1 and lines.count("rpc=filling; county=0") == 1
    assert 'if [ "$city" = 7 ]; then' in lines and lines.count("city_kept=yes; city=0") == 1
    assert lines[-1] == '[ "$city" = 0 ] && [ "$county" = 0 ]'       # city 2/5 and county 2/3/4 still fail
    assert not re.search(r"city\"? = [56]", step) and "cmcrpc.com" not in " ".join(lines)  # no fetch outside the collector
    assert f"at most {rpc.DAILY_FETCH_CAP} requests per run" in step


def test_an_rpc_failure_with_a_good_county_run_still_commits_the_county_data(county_run, tmp_path):
    """The collector writes the county facts and builds the site when only the RPC step failed (exit 5); the
    workflow's Collect step then passes, so the data artifact is uploaded and the push job commits it."""
    import os
    import subprocess

    import yaml
    county_run["rpc"] = rpc.STEP_FETCH
    assert M.main(["run", "--offline"]) == M.RPC_FAILED
    assert json.loads((tmp_path / "facts.json").read_text())["meetings"] == [{"id": "m"}]     # county data written
    assert county_run["order"] == ["agendas", "rpc", "site"]
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8"))
    steps = {s.get("name"): s for s in wf["jobs"]["update"]["steps"]}
    script = steps["Collect (polite fetch, parse, verify)"]["run"].replace(
        "python -m collector city run --agendas; city=$?", "city=0").replace(
        'python -m collector run "${shrink[@]}"; county=$?', f"county={M.RPC_FAILED}")
    out = tmp_path / "gh-output"
    r = subprocess.run(["bash", "-c", script], env={**os.environ, "GITHUB_OUTPUT": str(out)}, capture_output=True,
                       text=True)
    assert r.returncode == 0 and "::warning::The RPC step failed" in r.stdout
    assert "rpc=failed" in out.read_text().split()
    assert steps["Upload refreshed data"]["if"].startswith("success() && ")      # so the artifact is uploaded
    assert wf["jobs"]["push"]["needs"] == "update"                                # and the push job commits it
    issue = steps["Open or update the RPC issue"]
    assert issue["if"] == "always() && steps.collect.outputs.rpc == 'failed'"
    assert "--body-file" in issue["run"] and "${{" not in issue["run"]            # nothing interpolated into bash
    assert "gh issue comment" in issue["run"] and "select(.title == $ENV.RPC_TITLE)" in issue["run"]   # one issue


@pytest.mark.parametrize("open_issue", ["", "17"])
def test_the_rpc_issue_step_opens_one_issue_then_comments(tmp_path, open_issue):
    """The step's own script with a stub `gh`: no open RPC issue -> create, one open -> comment on it; the reason
    from build/run-log.json goes in the body file."""
    import os
    import shutil
    import subprocess

    import yaml
    if not shutil.which("jq"):
        pytest.skip("jq not installed")
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8"))
    step = {s.get("name"): s for s in wf["jobs"]["update"]["steps"]}["Open or update the RPC issue"]
    work, bindir = tmp_path / "work", tmp_path / "bin"
    (work / "build").mkdir(parents=True)
    bindir.mkdir()
    (work / "build" / "run-log.json").write_text(json.dumps({"rpc": {"status": "stopped, nothing changed: TooManyNew"}}))
    calls = tmp_path / "gh-calls"
    gh = bindir / "gh"
    gh.write_text("#!/bin/bash\n"
                  f'echo "$@" >> "{calls}"\n'
                  f'if [ "$2" = list ]; then echo "{open_issue}"; fi\n'
                  'for ((i=1; i<=$#; i++)); do if [ "${!i}" = --body-file ]; then j=$((i+1)); '
                  f'cat "${{!j}}" >> "{tmp_path / "bodies"}"; fi; done\n')
    gh.chmod(0o755)
    env = {**os.environ, **step["env"], "PATH": f"{bindir}:{os.environ['PATH']}", "RUNNER_TEMP": str(tmp_path),
           "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "1"}
    env.pop("GH_TOKEN")
    subprocess.run(["bash", "-c", step["run"]], cwd=work, env=env, check=True)
    lines = calls.read_text().splitlines()
    assert lines[0].startswith("issue list")
    assert lines[1].startswith("issue comment 17" if open_issue else "issue create")
    assert len(lines) == 2 and "TooManyNew" in (tmp_path / "bodies").read_text()
