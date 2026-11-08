"""F2: the finance hosts go through the same polite fetcher. Bonfire hosts are hard-denied (never requested, not even
robots.txt); the archive page is stored as HTML; a non-PDF document is recorded and not stored; a CONNECT refusal by
the sandbox proxy and a 403 from the site stay distinguished on the finance hosts (AC-F11). No network."""
import json
import urllib.parse

import pytest

from collector import fin_config
from collector.fetch import HostBlocked, HostRefused, NotPdf, PoliteFetcher, ProxyRefused
from collector.store import Store, fetch_into_store
from collector.tests.test_fetch import Clock, FakeNet

CFG = fin_config.load()
HOST = CFG.archive_host
ARCHIVE = CFG.archive_url
DOC = f"https://{HOST}/storage/departments/purchasing/BID/Bid%20Tab%20-%20Example.pdf"
BONFIRE = f"https://{CFG.bonfire_hosts[0]}/portal/"


def make(routes, proxy_failures=None):
    net, clock = FakeNet(routes), Clock()
    f = PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: proxy_failures or [],
                      extra_denied=CFG.bonfire_hosts)
    return f, net, clock


def test_bonfire_host_is_refused_without_any_request():
    f, net, _ = make({BONFIRE: (200, b"<html></html>")})
    for url in (BONFIRE, f"https://{CFG.bonfire_hosts[0]}/robots.txt", f"https://www.{CFG.bonfire_hosts[0]}/x"):
        with pytest.raises(HostRefused, match="denied by config"):
            f.get(url)
    assert net.calls == []


def test_bonfire_is_denied_even_if_put_on_the_allowlist():
    net, clock = FakeNet({}), Clock()
    f = PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: [],
                      allowed_hosts=CFG.bonfire_hosts + (HOST,), extra_denied=CFG.bonfire_hosts)
    with pytest.raises(HostRefused):
        f.get(BONFIRE)
    assert net.calls == []


def test_archive_host_is_on_the_allowlist_and_polite():
    f, net, clock = make({ARCHIVE: (200, b"<!DOCTYPE html><html></html>"), DOC: (200, b"%PDF-1.7 x")})
    f.get(ARCHIVE)
    f.get(DOC)
    assert [u for u, _ in net.calls] == [f"https://{HOST}/robots.txt", ARCHIVE, DOC]
    assert clock.slept == [10.0, 10.0]
    assert all("clarksville-records research collector" in ua for _, ua in net.calls)


def test_tunnel_refusal_is_the_proxy_not_the_site():
    f, net, _ = make({f"https://{HOST}/robots.txt": (404, b""), DOC: ("tunnel", b"")})
    with pytest.raises(ProxyRefused):
        f.get(DOC)
    assert HOST not in f._blocked


def test_site_403_blocks_the_host_for_the_run():
    f, net, _ = make({ARCHIVE: (403, b"Forbidden", {"Server": "x"})})
    with pytest.raises(HostBlocked):
        f.get(ARCHIVE)
    n = len(net.calls)
    with pytest.raises(HostBlocked):
        f.get(DOC)
    assert len(net.calls) == n and HOST in f._blocked


def test_proxy_recorded_403_is_not_a_site_block():
    when = "2999-01-01T00:00:00Z"
    f, net, _ = make({ARCHIVE: (403, b"")}, proxy_failures=[{"host": f"{HOST}:443", "ts": when, "detail": "403"}])
    with pytest.raises(ProxyRefused):
        f.get(ARCHIVE)
    assert HOST not in f._blocked


class FakeFetcher:
    def __init__(self, body, ctype):
        self.body, self.ctype, self.calls = body, ctype, 0

    def get(self, url):
        self.calls += 1
        return 200, self.body, {"Content-Type": self.ctype}


def store(tmp_path):
    return Store(tmp_path / "manifest.json", root=tmp_path / "store", now=lambda: "2026-11-08T00:00:00+00:00")


def test_archive_html_is_stored_with_expect_html(tmp_path):
    st = store(tmp_path)
    e, status = fetch_into_store(FakeFetcher(b"<!DOCTYPE html><html>t</html>", "text/html; charset=UTF-8"), st,
                                 ARCHIVE, {"kind": "archive_index"}, expect="html")
    assert status == "new" and e["kind"] == "archive_index" and st.has_bytes(e["sha256"])


def test_expect_html_refuses_a_pdf(tmp_path):
    with pytest.raises(Exception, match="not an HTML page"):
        fetch_into_store(FakeFetcher(b"%PDF-1.7", "application/pdf"), store(tmp_path), ARCHIVE, expect="html")


def test_a_docx_body_is_not_pdf_and_not_stored(tmp_path):
    st = store(tmp_path)
    url = f"https://{HOST}/storage/x.pdf"
    with pytest.raises(NotPdf):
        fetch_into_store(FakeFetcher(b"PK\x03\x04docx", "application/vnd.openxmlformats"), st, url, {"kind": "bid_tab"})
    st.save()
    assert st.latest(url) is None and not (tmp_path / "store").exists()
    assert (tmp_path / "manifest.json").read_text() == "[]\n"


def test_bad_expect_value_is_an_error(tmp_path):
    with pytest.raises(ValueError):
        fetch_into_store(FakeFetcher(b"", ""), store(tmp_path), ARCHIVE, expect="docx")


def test_finance_hosts_carry_no_literal_in_the_fetcher():
    src = (fin_config.ROOT / "collector" / "fetch.py").read_text(encoding="utf-8")
    assert all(h not in src for h in CFG.bonfire_hosts)
    assert urllib.parse.urlsplit(ARCHIVE).path not in src


# ------------------------------------------------------------------ fin fetch (collector/fin_run.cmd_fetch)
FIXTURE_HTML = (fin_config.ROOT / "collector" / "tests" / "fixtures" / "finance" / "archive_trimmed.html").read_bytes()


def _links():
    from collector import fin_run
    from collector.fin_archive import parse_archive
    return fin_run.archive_links(parse_archive(FIXTURE_HTML.decode(), CFG))


def _fin_fetch(tmp_path, routes):
    from collector import fin_run
    net, clock = FakeNet(routes), Clock()
    f = PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: [],
                      extra_denied=CFG.bonfire_hosts)
    st = store(tmp_path)
    sp = tmp_path / "fin_fetch_status.json"
    log = fin_run.cmd_fetch(st, CFG, fetcher=f, status_path=sp, today="2026-11-08", progress=lambda *a, **k: None)
    return log, net, st, sp


def test_fin_fetch_requests_pdfs_only_and_never_bonfire(tmp_path):
    links = _links()
    pdfs = [u for u, _, _ in links if not u.endswith(".docx")]
    routes = {ARCHIVE: (200, FIXTURE_HTML, {"Content-Type": "text/html"})}
    routes.update({u: (200, b"%PDF-1.7 " + u.encode()) for u in pdfs[1:]})       # the first PDF link is dead (404)
    log, net, st, sp = _fin_fetch(tmp_path, routes)
    called = [u for u, _ in net.calls]
    assert called[:2] == [f"https://{HOST}/robots.txt", ARCHIVE]
    assert not any("bonfire" in u or u.endswith(".docx") for u in called)
    assert set(called[2:]) == set(pdfs) and len(called) == len(set(called))
    assert log["stopped"] is None and log["fetched"] == {"new": len(pdfs) - 1}
    status = json.loads(sp.read_text())
    assert {u: v["status"] for u, v in status.items()} == {
        pdfs[0]: "dead_at_fetch", **{u: "not_pdf" for u, _, _ in links if u.endswith(".docx")}}
    assert st.latest(ARCHIVE)["kind"] == "archive_index"
    # a second run: the archive is re-requested, the dead link retried, nothing else; status file unchanged
    before = sp.read_text()
    _, net2, _, _ = _fin_fetch(tmp_path, routes)
    assert [u for u, _ in net2.calls] == [f"https://{HOST}/robots.txt", ARCHIVE, pdfs[0]]
    assert sp.read_text() == before


def test_fin_fetch_stops_on_a_site_403(tmp_path):
    first = _links()[0][0]
    routes = {ARCHIVE: (200, FIXTURE_HTML, {"Content-Type": "text/html"}), first: (403, b"no")}
    log, net, _, _ = _fin_fetch(tmp_path, routes)
    assert log["stopped"].startswith("HostBlocked")
    assert [u for u, _ in net.calls][-1] == first             # nothing after the block, no other route


def test_fin_fetch_stops_on_a_blocked_archive(tmp_path):
    log, net, st, _ = _fin_fetch(tmp_path, {ARCHIVE: (403, b"no")})
    assert log["stopped"].startswith("HostBlocked") and log["links"] == 0
    assert st.latest(ARCHIVE) is None


def test_fin_fetch_refuses_a_fetcher_that_allows_bonfire(tmp_path):
    from collector import fin_run
    with pytest.raises(ValueError):
        fin_run.cmd_fetch(store(tmp_path), CFG, fetcher=PoliteFetcher(), status_path=tmp_path / "s.json")
