"""County Commission agendas (collector/county_agenda.py): the agenda page, the polite fetch with its placeholder rule,
and the reader for the meeting date, kind and items. No network: the page is a trimmed copy of the real one, the
agenda texts are pdftotext output of real agendas (Nov 9, 2026 formal; Sep 8, 2026 informal)."""
import json
from datetime import date
from pathlib import Path

import pytest

from collector import county_agenda as C
from collector.fetch import ALLOWED_HOSTS, USER_AGENT, PoliteFetcher
from collector.store import Store
from collector.tests.test_fetch import Clock, FakeResp

FIX = Path(__file__).parent / "fixtures" / "county_agenda"
BASE = "https://mcgtn.org/storage/departments/commission/agendas-and-resolutions/2026/"
REAL = b"%PDF-1.7\n" + b"x" * 200_000


def text_pages(name: str) -> list[str]:
    pages = (FIX / name).read_text(encoding="utf-8").split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages


class Net:
    """url -> (status, body, headers); every request recorded with its User-Agent and the clock time."""

    def __init__(self, routes, clock):
        self.routes, self.clock, self.calls = routes, clock, []

    def __call__(self, req, timeout):
        import io
        import urllib.error
        url = req.full_url
        self.calls.append((url, req.get_header("User-agent"), self.clock.t))
        status, body, headers = self.routes.get(url, (404, b"", {}))
        if status >= 300:
            raise urllib.error.HTTPError(url, status, "x", headers, io.BytesIO(body))
        r = FakeResp(body, status)
        r.headers = headers
        return r


def fetcher(routes):
    clock = Clock()
    net = Net(routes, clock)
    return PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: []), net


def page_routes(extra=None):
    r = {"https://montgomerytn.gov/robots.txt": (200, b"User-agent: *\nDisallow:\n", {}),
         "https://mcgtn.org/robots.txt": (200, b"User-agent: *\nDisallow:\n", {}),
         C.INDEX_URL: (200, (FIX / "index.html").read_bytes(), {"Content-Type": "text/html"})}
    r.update(extra or {})
    return r


# ------------------------------------------------------------------ the agenda page
def test_page_links_are_read_with_year_month_and_kind_from_the_page():
    links, unread = C.parse_index((FIX / "index.html").read_text(encoding="utf-8"))
    assert unread == []
    assert len(links) == 26                          # 24 for 2026 and 2 special called; no form or SharePoint link
    nov = [x for x in links if (x["year"], x["month"]) == (2026, 11)]
    assert [(x["kind"], x["url"], x["label"]) for x in nov] == [
        ("informal", BASE + "nov-informal.pdf", "2026 November Informal"),
        ("formal", BASE + "nov-formal.pdf", "2026 November Formal")]
    # a relative link is resolved against the page URL, as printed: no other host is tried
    apr = next(x for x in links if (x["year"], x["month"], x["kind"]) == (2026, 4, "informal"))
    assert apr["url"] == "https://montgomerytn.gov/storage/departments/commission/agendas-and-resolutions/2026/apr-informal.pdf"
    special = [x for x in links if x["kind"] == "special"]
    assert [(x["year"], x["month"]) for x in special] == [(2024, 4), (2024, 7)]
    assert all("sharepoint" not in x["url"] and "FILLABLE" not in x["url"] for x in links)
    assert {"montgomerytn.gov", "mcgtn.org"} <= set(ALLOWED_HOSTS)


def test_a_page_without_agenda_links_fails_loudly():
    with pytest.raises(C.AgendaPageError):
        C.parse_index("<html><h3>2026</h3><p>Moved.</p></html>")


def test_only_months_from_the_newest_minutes_to_next_month_are_wanted():
    links, _ = C.parse_index((FIX / "index.html").read_text(encoding="utf-8"))
    got = C.wanted(links, (2026, 5), date(2026, 11, 10))
    assert sorted({x["month"] for x in got}) == [5, 6, 7, 8, 9, 10, 11, 12] and all(x["year"] == 2026 for x in got)
    assert {x["month"] for x in C.wanted(links, None, date(2026, 11, 10))} == {11, 12}   # first run: no archive walk
    assert C.wanted(links, (2026, 5), date(2026, 3, 1)) == []


def test_placeholder_rule_size_and_last_modified():
    assert "6,097 bytes" in C.placeholder_reason(b"%PDF" + b"x" * 6093, {}, 2026, 12)
    old = {"Last-Modified": "Thu, 02 Apr 2026 15:00:00 GMT"}
    assert "last modified 2026-04-02" in C.placeholder_reason(REAL, old, 2026, 12)
    assert C.placeholder_reason(REAL, {"Last-Modified": "Mon, 09 Nov 2026 21:03:12 GMT"}, 2026, 11) is None
    assert C.placeholder_reason(REAL, {"Last-Modified": "Fri, 16 Oct 2026 20:50:58 GMT"}, 2026, 11) is None
    assert C.placeholder_reason(REAL, {"Last-Modified": "not a date"}, 2026, 11) is None


# ------------------------------------------------------------------ the polite fetch
def test_fetch_is_polite_stores_real_agendas_and_skips_placeholders(tmp_path):
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"meetings": [{"date": "2026-10-19"}]}), encoding="utf-8")
    lm = {"Last-Modified": "Mon, 09 Nov 2026 21:03:12 GMT", "Content-Type": "application/pdf"}
    f, net = fetcher(page_routes({
        BASE + "oct-informal.pdf": (200, REAL + b"1", lm), BASE + "oct-formal.pdf": (200, REAL + b"2", lm),
        BASE + "nov-informal.pdf": (200, REAL + b"3", lm), BASE + "nov-formal.pdf": (200, b"<html>moved</html>", {}),
        BASE + "dec-informal.pdf": (200, b"%PDF" + b"x" * 6000, {}),
        BASE + "dec-formal.pdf": (200, REAL + b"4", {"Last-Modified": "Thu, 02 Apr 2026 15:00:00 GMT"})}))
    store = Store(tmp_path / "manifest.json", root=tmp_path / "store")
    log = {}
    skipped = C.cmd_fetch(store, log, fetcher=f, today=date(2026, 11, 10), facts_path=facts)
    urls = [u for u, _, _ in net.calls]
    assert urls.count(C.INDEX_URL) == 1 and urls[0] == "https://montgomerytn.gov/robots.txt"
    assert "https://mcgtn.org/robots.txt" in urls
    assert all(ua == USER_AGENT for _, ua, _ in net.calls)
    times = [t for u, _, t in net.calls if u.startswith("https://mcgtn.org/")]
    assert all(b - a >= 10.0 for a, b in zip(times, times[1:]))          # at least 10 s between requests per host
    assert log["fetched"] == {"new": 3} and log["failures"] == []
    assert sorted(e["kind"] for e in store.entries) == ["agenda_formal", "agenda_informal", "agenda_informal"]
    assert {s["url"].rsplit("/", 1)[1]: s["reason"].split(":")[0] for s in skipped} == {
        "nov-formal.pdf": "not a PDF", "dec-informal.pdf": "placeholder", "dec-formal.pdf": "placeholder"}
    # placeholders are not stored, so a later run asks again; a stored agenda is never requested again
    f2, net2 = fetcher(page_routes({BASE + "dec-formal.pdf": (200, REAL + b"5", lm)}))
    C.cmd_fetch(store, {}, fetcher=f2, today=date(2026, 11, 11), facts_path=facts)
    asked = [u for u, _, _ in net2.calls if u.endswith(".pdf")]
    assert BASE + "oct-formal.pdf" not in asked and BASE + "dec-formal.pdf" in asked
    assert any(e["url"] == BASE + "dec-formal.pdf" for e in store.entries)


def test_a_blocked_host_stops_the_fetch_and_a_moved_page_is_a_failure(tmp_path):
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"meetings": [{"date": "2026-10-19"}]}), encoding="utf-8")
    f, net = fetcher(page_routes({BASE + "oct-informal.pdf": (403, b"no", {})}))
    log = {}
    C.cmd_fetch(Store(tmp_path / "m.json", root=tmp_path / "s"), log, fetcher=f, today=date(2026, 11, 10),
                facts_path=facts)
    assert [x["stage"] for x in log["failures"]] == ["agenda_fetch"] and "HostBlocked" in log["failures"][0]["error"]
    assert not [u for u, _, _ in net.calls if u.endswith(".pdf") and "oct-informal" not in u]   # nothing after it
    f, _ = fetcher(page_routes({C.INDEX_URL: (404, b"", {})}))
    log = {}
    assert C.cmd_fetch(Store(tmp_path / "m.json", root=tmp_path / "s"), log, fetcher=f, facts_path=facts) == []
    assert log["failures"][0]["stage"] == "agenda_page"


# ------------------------------------------------------------------ reading an agenda
def test_header_reads_date_and_kind_from_the_first_page():
    h = C.header(text_pages("2026-11-formal.txt"))
    assert (h["date"], h["kind"]) == ("2026-11-09", "formal")
    h = C.header(text_pages("2026-09-informal.txt"))
    assert (h["date"], h["kind"]) == ("2026-09-08", "informal")          # a Tuesday: never a weekday pattern
    assert C.header(["SPECIAL CALLED MEETING AGENDA   APRIL 1, 2024\nCALL TO ORDER"])["kind"] == "special"
    assert C.header(["AGENDA\nCALL TO ORDER"]) == {"date": None, "kind": None, "line": "AGENDA"}


def test_items_are_read_as_printed_with_section_and_page():
    got, end = C.items(text_pages("2026-11-formal.txt"))
    assert end and [x["printed"] for x in got] == [
        "CZO-1-2026", "CZ-12-2026", "CZ-13-2026", "26-11-1*", "26-11-2*", "26-11-3*", "26-11-4*", "26-11-5*",
        "26-11-6*", "26-11-7", "26-11-8"]
    two = got[4]
    assert two["title"] == ("Resolution to Accept Funds From the United States Department of Justice Office of Victims "
                            "of Crime FY2026 Services for Victims of Crime Program and Approve New Positions for the "
                            "Montgomery County Child Advocacy Center")
    assert two["section"] == "RESOLUTIONS" and two["page"] == 1
    assert got[3]["number"] == "26-11-1" and got[6]["title"].endswith("Add a Full-Time Position to the Register of Deeds")
    assert got[0]["section"] == "ZONING RESOLUTIONS"
    assert (got[9]["section"], got[9]["page"]) == ("RESOLUTIONS REMOVED FROM CONSENT", 2)
    assert got[10]["section"] == "RESOLUTIONS ADDED AFTER BUDGET COMMITTEE MET"
    # numbered report lines ("1. * Commission Minutes ...") are not items; neither is anything after ADJOURN
    assert not any("Minutes dated" in x["title"] or "Quarterly" in x["title"] for x in got)
    inf, end = C.items(text_pages("2026-09-informal.txt"))
    assert end and inf[0]["printed"] == "CZ-6-2026" and inf[0]["section"] == "PUBLIC HEARING ZONING RESOLUTIONS"
    assert C.items(["RESOLUTIONS\n 26-1-1   A title\n"]) == ([], False)      # no ADJOURN: the list's end is unknown


def test_build_writes_meetings_keyed_like_the_minutes_and_keeps_the_file_when_bytes_are_missing(tmp_path):
    store = Store(tmp_path / "manifest.json", root=tmp_path / "store", now=lambda: "2026-11-10T00:00:00+00:00")
    store.put(BASE + "nov-formal.pdf", REAL + b"a", {}, {"kind": "agenda_formal", "meeting_date": "2026-11",
                                                         "label": "2026 November Formal"})
    store.put(BASE + "sep-informal.pdf", REAL + b"b", {}, {"kind": "agenda_formal", "meeting_date": "2026-09",
                                                           "label": "2026 September Formal"})
    store.save()
    texts = {store.latest(BASE + "nov-formal.pdf")["sha256"]: text_pages("2026-11-formal.txt"),
             store.latest(BASE + "sep-informal.pdf")["sha256"]: text_pages("2026-09-informal.txt")}
    read = lambda p: texts[p.stem]                                           # noqa: E731
    out, summary = C.build(store, [{"url": BASE + "dec-formal.pdf", "reason": "placeholder"}], read=read,
                           page_count=lambda p: 143, agendas_path=tmp_path / "agendas.json")
    assert [m["id"] for m in out["meetings"]] == ["2026-09-08-informal", "2026-11-09-formal"]
    nov = out["meetings"][1]
    assert nov["source_id"] == f"src-{store.latest(BASE + 'nov-formal.pdf')['sha256'][:12]}"
    assert nov["items"][3] == {"id": "2026-11-09-formal/26-11-1", "number": "26-11-1", "printed": "26-11-1*",
                               "title": "Resolution to Accept a Monetary Donation from the Friends of Fredonia Park",
                               "section": "RESOLUTIONS", "page": 1, "year": 2026, "link_basis": "number"}
    assert out["sources"][0]["pages"] == 143 and out["skipped"][0]["reason"] == "placeholder"
    # the page listed this as formal; the agenda prints informal: the text wins and the mismatch is reported
    assert summary["problems"] == [{"url": BASE + "sep-informal.pdf",
                                    "problem": "listed as formal, the agenda prints informal"}]
    # run_step offline with an empty store keeps the committed file
    path = tmp_path / "agendas.json"
    path.write_text("{\"kept\": true}\n", encoding="utf-8")
    log = {"failures": []}
    import shutil
    shutil.rmtree(tmp_path / "store")
    C.run_step(log, offline=True, agendas_path=path, manifest_path=tmp_path / "manifest.json")
    assert path.read_text(encoding="utf-8") == "{\"kept\": true}\n" and "left unchanged" in log["county_agendas"]["kept"]
