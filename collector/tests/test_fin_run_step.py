"""A1: the finance steps of `python -m collector run` (fin_run.run_step): fin fetch through the polite fetcher (fake
transport, no network), then fin build from the store; offline skips the fetch; a blocked fetch is logged and the
build still runs from the store. Problem keys: politeness/*, coverage-count/*."""
import json

from collector import fin_facts, fin_run
from collector.fetch import PoliteFetcher
from collector.tests.fin_fake import ARCHIVE_HTML, CFG, FakeFin
from collector.tests.test_fetch import Clock, FakeNet

HOST = CFG.archive_host


def fetcher(routes):
    net, clock = FakeNet(routes), Clock()
    return PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: [],
                         extra_denied=CFG.bonfire_hosts), net


def step(tmp_path, monkeypatch, offline, routes):
    ff = FakeFin(tmp_path)
    monkeypatch.setattr(fin_facts, "pdf_meta", ff.meta)
    f, net = fetcher(routes)
    log = {"failures": []}
    code = fin_run.run_step(ff.store, log, offline, fetcher=f, cfg=CFG, finance_path=tmp_path / "finance.json",
                            report_path=tmp_path / "report.json", status_path=ff.status_path,
                            progress=lambda *a, **k: None, meta_cache=None, words_for=ff.words_for)
    return code, log, net


def test_online_step_fetches_politely_then_builds(tmp_path, monkeypatch):
    routes = {CFG.archive_url: (200, ARCHIVE_HTML, {"Content-Type": "text/html"})}
    code, log, net = step(tmp_path, monkeypatch, False, routes)
    # every linked PDF is already in the store: only robots.txt and the archive page are requested, never Bonfire
    assert [u for u, _ in net.calls] == [f"https://{HOST}/robots.txt", CFG.archive_url]
    assert log["fin_fetch"]["archive"]["status"] == "unchanged-table" and log["fin_fetch"]["stopped"] is None
    assert code in (0, 3) and log["fin_build"] == code and log["failures"] == []
    fin = json.loads((tmp_path / "finance.json").read_text())
    assert fin["coverage"]["n_total"] == 15 and fin["coverage"]["n_tab_read"] == 1
    assert "finance" in json.loads((tmp_path / "report.json").read_text())


def test_offline_step_builds_without_any_request(tmp_path, monkeypatch):
    code, log, net = step(tmp_path, monkeypatch, True, {})
    assert net.calls == [] and "fin_fetch" not in log and log["failures"] == []
    assert (tmp_path / "finance.json").exists() and log["fin_build"] == code


def test_blocked_fetch_is_logged_not_retried_and_the_store_still_builds(tmp_path, monkeypatch):
    code, log, net = step(tmp_path, monkeypatch, False, {CFG.archive_url: (403, b"no")})
    assert [u for u, _ in net.calls] == [f"https://{HOST}/robots.txt", CFG.archive_url]
    assert log["failures"][0]["stage"] == "fin_fetch" and "HostBlocked" in log["failures"][0]["error"]
    assert (tmp_path / "finance.json").exists()


def test_no_archive_in_the_store_is_a_logged_failure(tmp_path):
    from collector.store import Store
    log = {"failures": []}
    code = fin_run.run_step(Store(tmp_path / "m.json", root=tmp_path / "s"), log, True, cfg=CFG,
                            finance_path=tmp_path / "finance.json", report_path=tmp_path / "report.json",
                            status_path=tmp_path / "status.json")
    assert code == 2 and log["failures"][0]["stage"] == "fin_build" and not (tmp_path / "finance.json").exists()
