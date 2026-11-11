"""docs/architecture/pipeline-limits-invariant.md: every limit sits above the largest real input with margin, and a
limit trip is reported."""
import json
import re
import subprocess
from pathlib import Path

import pytest

from collector import extract, fetch, fin_facts, limits, minutes, ocr
from collector.store import Store
from collector.tests.test_fetch import make


@pytest.fixture(autouse=True)
def _fresh_trips():
    limits.reset()
    yield
    limits.reset()


# ------------------------------------------------------------------ meta: no limit skips the margin table

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "architecture" / "pipeline-limits-invariant.md"
# a module-level constant whose name has MAX, CAP or TIMEOUT as a word (MAX_BYTES, DAILY_FETCH_CAP, PARA_MAX; not
# CAPS_NAMES_RE)
LIMIT_NAME = re.compile(r"^((?:[A-Z0-9]+_)*(?:MAX|CAP|TIMEOUT)(?:_[A-Z0-9]+)*)\s*(?::[^=]*)?=", re.M)
LITERAL_TIMEOUT = re.compile(r"\btimeout=(\d+(?:\.\d+)?)\b")


def test_every_limit_is_in_the_invariant_table():
    """Every module-level MAX/CAP/TIMEOUT constant and every literal `timeout=N` in collector/ is a row of the
    table (by `module.NAME`, or NAME in a row that names module.py), so a new limit cannot skip the margin check."""
    rows = [ln for ln in DOC.read_text(encoding="utf-8").splitlines() if ln.startswith("| L")]
    missing = []
    for path in sorted((ROOT / "collector").glob("*.py")):
        src, mod = path.read_text(encoding="utf-8"), path.stem
        for name in LIMIT_NAME.findall(src):
            if not any(name in r and (f"{mod}.{name}" in r or f"{mod}.py" in r) for r in rows):
                missing.append(f"{mod}.{name}")
        for n in LITERAL_TIMEOUT.findall(src):
            if not any(f"timeout={n}" in r and f"{mod}.py" in r for r in rows):
                missing.append(f"{mod}.py timeout={n}")
    assert missing == [], f"limits not in {DOC.name}: {missing}"


def test_the_meta_check_sees_the_limits_it_must():
    found = {(p.stem, n) for p in (ROOT / "collector").glob("*.py") for n in LIMIT_NAME.findall(p.read_text())}
    assert {("ocr", "OCR_TIMEOUT"), ("fetch", "MAX_BYTES"), ("rpc", "DAILY_FETCH_CAP"), ("minutes", "MAX_PAGES"),
            ("rpc_agenda", "RPC_MAX_OCR_PAGES"), ("rpc_minutes", "PARA_MAX")} <= found


# ------------------------------------------------------------------ margins (L7, L16)

def test_fetch_stores_the_largest_real_file_and_refuses_one_over_the_cap(tmp_path):
    """L16: the 2021-10-28 city agenda is 52,041,095 B (the old 50 MiB cap refused it)."""
    big = b"%PDF-1.7\n" + b"x" * (52_041_095 - 9)
    f, _, _ = make({"https://h.example/a.pdf": (200, big)})
    status, body, headers = f.get("https://h.example/a.pdf")
    assert status == 200 and len(body) == 52_041_095
    store = Store(tmp_path / "manifest.json", root=tmp_path / "store", now=lambda: "2026-11-11T00:00:00+00:00")
    e, _ = store.put("https://h.example/a.pdf", body, headers, {"kind": "agenda"})
    assert store.path_for(e["sha256"]).stat().st_size == 52_041_095
    assert fetch.MAX_BYTES == 200 * 1024 * 1024 >= 2 * 52_041_095
    f, _, _ = make({"https://h.example/b.pdf": (200, b"x" * 1001)})
    f.max_bytes = 1000                       # cap + 1, scaled down so the test holds no 200 MiB body
    with pytest.raises(fetch.FetchFailed, match="larger than 1000 bytes"):
        f.get("https://h.example/b.pdf")


def test_county_minutes_page_cap_has_margin_over_621_pages(monkeypatch, tmp_path):
    """L7: a 621-page document is read; 1501 pages is a parse failure."""
    monkeypatch.setattr(minutes, "cached_pages", lambda pdf, cache: [""] * 621)
    assert minutes.parse_minutes(tmp_path / "m.pdf", {"sha256": "a" * 64}, use_ocr=False, text_cache=tmp_path)
    monkeypatch.setattr(minutes, "cached_pages", lambda pdf, cache: [""] * 1501)
    with pytest.raises(ValueError, match="over the 1500-page cap"):
        minutes.parse_minutes(tmp_path / "m.pdf", {"sha256": "a" * 64}, use_ocr=False, text_cache=tmp_path)


# ------------------------------------------------------------------ rule 3: every trip is reported

def test_a_timeout_is_a_timeout_expired_whose_message_is_the_trip_line(monkeypatch):
    def hung(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    monkeypatch.setattr(subprocess, "run", hung)
    with pytest.raises(subprocess.TimeoutExpired) as e:
        extract.extract_pages(Path("/x/big.pdf"))
    assert str(e.value) == "limit extract.PARSE_TIMEOUT: big.pdf 120s+ > 120s"
    assert limits.tripped() == ["limit extract.PARSE_TIMEOUT: big.pdf 120s+ > 120s"]
    assert limits.summary("collector") == ("collector: limits tripped: 1\n"
                                           "  limit extract.PARSE_TIMEOUT: big.pdf 120s+ > 120s")


def test_no_trip_prints_zero():
    assert limits.summary("collector city") == "collector city: limits tripped: 0"


def test_fetch_cap_and_page_cap_trips_are_reported(monkeypatch, tmp_path):
    f, _, _ = make({"https://h.example/b.pdf": (200, b"x" * 1001)})
    f.max_bytes = 1000
    with pytest.raises(fetch.FetchFailed):
        f.get("https://h.example/b.pdf")
    monkeypatch.setattr(minutes, "cached_pages", lambda pdf, cache: [""] * 1501)
    with pytest.raises(ValueError):
        minutes.parse_minutes(tmp_path / "m.pdf", {"sha256": "a" * 64}, use_ocr=False, text_cache=tmp_path)
    assert limits.tripped() == ["limit fetch.MAX_BYTES: https://h.example/b.pdf 1001+ B > 1000 B",
                                "limit minutes.MAX_PAGES: m.pdf 1501 pp > 1500 pp"]


def test_a_trip_in_an_ocr_worker_reaches_the_parent_summary(monkeypatch, tmp_path):
    """ocr_pages_parallel runs ocr_page in worker processes: the trip comes back as the error text and is noted."""
    monkeypatch.setattr(ocr, "OCR_CACHE", tmp_path)
    monkeypatch.setattr(minutes, "_ocr_job", lambda job: (job[1], "limit ocr.OCR_TIMEOUT: m.pdf p7 600s > 600s"))

    class Pool:
        def __init__(self, max_workers):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def map(self, fn, jobs, chunksize=1):
            return [fn(j) for j in jobs]
    monkeypatch.setattr(minutes, "ProcessPoolExecutor", Pool)
    errors = minutes.ocr_pages_parallel([("m.pdf", 7, "b" * 64)])
    assert errors == {("b" * 64, 7): "limit ocr.OCR_TIMEOUT: m.pdf p7 600s > 600s"}
    assert limits.tripped() == ["limit ocr.OCR_TIMEOUT: m.pdf p7 600s > 600s"]


def test_a_county_refusal_prints_the_limits_line(capsys):
    from collector import __main__ as county
    limits.trip("minutes.MAX_PAGES", "m.pdf", "1501 pp", "1500 pp")
    assert county.refuse("x") == county.REFUSED
    assert "collector: limits tripped: 1\n  limit minutes.MAX_PAGES: m.pdf 1501 pp > 1500 pp" in capsys.readouterr().out


def test_fin_and_rpc_steps_in_one_process_report_only_their_own_trips(monkeypatch, capsys, tmp_path):
    """pipeline/limits-reported-misattributed: county, then finance, then RPC in one process (collector run)."""
    from collector import fin_run, rpc
    from collector.tests.fin_fake import CFG, FakeFin
    limits.mark()
    limits.trip("minutes.MAX_PAGES", "county.pdf", "1501 pp", "1500 pp")            # the county step's
    ff = FakeFin(tmp_path / "fin")

    def meta(pdf, cfg, cache_dir=None):
        limits.trip("fin_facts.PDFINFO_TIMEOUT", pdf, "120s+", "120s")
        return ff.meta(pdf, cfg, cache_dir)
    monkeypatch.setattr(fin_facts, "pdf_meta", meta)
    fin_run.cmd_build(ff.store, CFG, finance_path=tmp_path / "f.json", report_path=tmp_path / "r.json",
                      status_path=ff.status_path, meta_cache=None, words_for=ff.words_for, book_words=ff.book_words)
    fin_out = capsys.readouterr().out
    assert "collector fin: limits tripped: " in fin_out and "county.pdf" not in fin_out
    assert "limit fin_facts.PDFINFO_TIMEOUT: " in fin_out

    def daily(cfg, p, out, offline, fetcher, store, build, max_requests, allow_shrink=False):
        limits.trip("rpc_agenda.RPC_MAX_OCR_PAGES", "rpc.pdf", "201 pp", "200 pp")
        out["status"] = "ok"
        return rpc.STEP_OK
    monkeypatch.setattr(rpc, "_daily", daily)
    root = tmp_path / "rpc"
    rpc.run_step({}, offline=True, root=root, cfg=rpc.load_config())
    rpc_out = capsys.readouterr().out
    assert "collector: rpc: limits tripped: 1\n  limit rpc_agenda.RPC_MAX_OCR_PAGES: rpc.pdf 201 pp > 200 pp" in rpc_out
    report = json.loads((root / "build" / "rpc-report.json").read_text())
    assert report["limits"] == ["limit rpc_agenda.RPC_MAX_OCR_PAGES: rpc.pdf 201 pp > 200 pp"]


def test_the_same_trip_twice_in_one_step_is_one_line_and_timeouts_show_the_cap(monkeypatch):
    def hung(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    monkeypatch.setattr(subprocess, "run", hung)
    limits.mark()
    for _ in range(2):
        with pytest.raises(subprocess.TimeoutExpired):
            extract.extract_pages(Path("/x/big.pdf"))
    assert limits.tripped() == ["limit extract.PARSE_TIMEOUT: big.pdf 120s+ > 120s"]
    limits.mark()                                       # a later step: the same trip is its own again
    with pytest.raises(subprocess.TimeoutExpired):
        extract.extract_pages(Path("/x/big.pdf"))
    assert len(limits.tripped()) == 2


@pytest.mark.parametrize("which", ["city", "rpc", "fin"])
def test_each_run_summary_prints_the_limits_line(which, monkeypatch, capsys, tmp_path):
    limits.trip("ocr.MAX_PAGE_PTS", "before.pdf", "9000 pt", "2592 pt", page=1)     # before the step: not its own

    def trip():
        limits.trip("ocr.MAX_PAGE_PTS", "big.pdf", "9000 pt", "2592 pt", page=3)
    if which == "fin":
        from collector import fin_run
        from collector.tests.fin_fake import CFG, FakeFin
        ff = FakeFin(tmp_path)
        monkeypatch.setattr(fin_facts, "pdf_meta", lambda pdf, cfg, cache_dir=None: trip() or ff.meta(pdf, cfg))
        fin_run.cmd_build(ff.store, CFG, finance_path=tmp_path / "f.json", report_path=tmp_path / "r.json",
                          status_path=ff.status_path, meta_cache=None, words_for=ff.words_for,
                          book_words=ff.book_words)
        prefix = "collector fin"
    elif which == "rpc":
        from collector import rpc

        def daily(cfg, p, out, *a, **k):
            trip()
            out["status"] = "ok"
            return rpc.STEP_OK
        monkeypatch.setattr(rpc, "_daily", daily)
        rpc.run_step({}, offline=True, root=tmp_path, cfg=rpc.load_config())
        prefix = "collector: rpc"
    else:
        from collector import city_run
        monkeypatch.setattr(city_run, "write_json", lambda path, obj: None)
        monkeypatch.setattr(city_run, "listing_rows", lambda p, cfg: ([], []))
        monkeypatch.setattr("collector.city_build.build", lambda cfg, rows, store: trip() or ({"_wards": {}}, {}))
        city_run.main(["build"])
        prefix = "collector city"
    out = capsys.readouterr().out
    assert f"{prefix}: limits tripped: 1\n  limit ocr.MAX_PAGE_PTS: big.pdf p3 9000 pt > 2592 pt" in out
    assert "before.pdf" not in out


# ------------------------------------------------------------------ rule 3: the shrink guard

def _rc(rid, status, sid="src-30a9df8f0000", mid="m1"):
    return {"id": rid, "meeting_id": mid, "source_id": sid, "verification": {"status": status, "checks": []}}


def _doc(rcs, sha="30a9df8f" + "0" * 56, mid="m1"):
    sid = f"src-{sha[:12]}"
    return {"sources": [{"id": sid, "sha256": sha}], "meetings": [{"id": mid, "source_id": sid}],
            "roll_calls": [dict(r, source_id=sid) for r in rcs]}


def test_county_guard_refuses_a_committed_verified_roll_call_that_is_no_longer_verified(tmp_path):
    from collector import __main__ as M
    old = _doc([_rc("rc-30a9df8f-p519-0", "verified"), _rc("rc-b", "verified"), _rc("rc-c", "unverified")])
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    log = {"parsed": 1, "failures": []}
    assert M.shrink_reason(_doc(old["roll_calls"]), log, path) is None
    lost = _doc([_rc("rc-30a9df8f-p519-0", "unverified"), _rc("rc-b", "verified")])
    why = M.shrink_reason(lost, log, path)
    assert "1 source documents in facts.json would lose verified roll calls or meetings" in why
    assert "rc-30a9df8f-p519-0" in why and "--allow-shrink" in why and "rc-b" not in why
    gone = _doc([_rc("rc-b", "verified")])                                              # dropped: also lost
    assert "rc-30a9df8f-p519-0" in M.shrink_reason(gone, log, path)
    better = _doc(old["roll_calls"][:2] + [_rc("rc-c", "verified")])
    assert M.shrink_reason(better, log, path) is None                                 # gaining one is fine
    # G2.7: new bytes for the same meeting are a correction, not refused offline either
    corrected = _doc([_rc("rc-11111111-p519-0", "unverified")], sha="1" * 64)
    assert M.shrink_reason(corrected, log, path) is None


def test_county_allow_shrink_skips_the_guard():
    """cmd_run calls shrink_reason only when the run is offline and --allow-shrink is not given; online and offline
    the guard's kept documents are applied unless --allow-shrink is given."""
    import inspect

    from collector import __main__ as M
    src = inspect.getsource(M.cmd_run)
    assert "if args.offline and not allow:\n        why = shrink_reason(facts, log, FACTS)" in src
    assert 'kept = [] if allow else guard["kept"]' in src
    assert "facts = keep_documents(facts, old, kept)" in src


def _motion(mid, confirmed):
    return {"id": mid, "confirmed": confirmed}


def test_rpc_guard_refuses_a_committed_confirmed_motion_that_is_no_longer_confirmed():
    from collector import rpc
    old = {"meetings": [], "motions": [_motion("2026-05-26-regular-motion-1", True), _motion("m2", False)]}
    new = {"meetings": [], "motions": [_motion("2026-05-26-regular-motion-1", False), _motion("m2", False)]}
    why = rpc.shrink_reason(old, new)
    assert "1 motions confirmed in the committed record would not be confirmed" in why
    assert "2026-05-26-regular-motion-1" in why
    assert rpc.shrink_reason(old, {"meetings": [], "motions": []}) is not None      # dropped
    assert rpc.shrink_reason(old, new, allow_shrink=True) is None
    assert rpc.shrink_reason(old, old) is None
    # rpc.yml hold_motions on: nothing is published confirmed and a reader fix is expected to unconfirm motions
    assert rpc.shrink_reason(old, new, hold_motions=True) is None


def test_rpc_hold_is_read_from_rpc_yml_and_reaches_the_guard(monkeypatch, tmp_path):
    import dataclasses

    from collector import rpc
    cfg = rpc.load_config()
    assert cfg.hold_motions is True                      # rpc.yml today: 0 confirmed shown is expected
    seen = {}

    def guard(old, new, hold_motions=False, allow_shrink=False):
        seen.update(hold=hold_motions, allow=allow_shrink)
        return None
    monkeypatch.setattr(rpc, "shrink_reason", guard)
    p = rpc.paths(cfg, tmp_path)
    p["facts"].parent.mkdir(parents=True, exist_ok=True)
    p["facts"].write_text(json.dumps({"meetings": [], "motions": []}), encoding="utf-8")
    p["listing"].parent.mkdir(parents=True, exist_ok=True)
    p["listing"].write_text(json.dumps([{"docs": []}]), encoding="utf-8")
    store = Store(tmp_path / "manifest.json", root=tmp_path / "store")
    build = lambda cfg, rows, store, audit_path=None: ({"meetings": [], "motions": []}, {})   # noqa: E731
    for hold, allow in ((True, False), (False, True)):
        out: dict = {}
        code = rpc._daily(dataclasses.replace(cfg, hold_motions=hold), p, out, True, None, store, build, None,
                          allow_shrink=allow)
        assert code == rpc.STEP_OK and seen == {"hold": hold, "allow": allow}
