"""Regional Planning Commission (RPC-1): config, the listing page, the polite fetch and the agenda case reader.
No network: the listing is a trimmed copy of the real page, the agenda texts are pdftotext output of real agendas."""
import json
from pathlib import Path

import pytest

from collector import rpc, rpc_agenda
from collector.fetch import ALLOWED_HOSTS, USER_AGENT, PoliteFetcher
from collector.store import Store
from collector.tests.test_fetch import Clock, FakeNet

FIX = Path(__file__).parent / "fixtures" / "rpc"
LISTING = rpc.load_config().listing_url


@pytest.fixture(scope="module")
def cfg():
    return rpc.load_config()


@pytest.fixture(scope="module")
def rows(cfg):
    out, problems = rpc.parse_listing((FIX / "listing.html").read_text(encoding="utf-8"), cfg)
    return rpc.assign_ids(out), problems


def agenda_pages(name: str) -> list[str]:
    pages = (FIX / name).read_text(encoding="utf-8").split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages


# ------------------------------------------------------------------ config
def test_config_and_allowlist(cfg):
    assert cfg.listing_url == "https://www.cmcrpc.com/documents/agenda-minutes/"
    assert "cmcrpc.com" in ALLOWED_HOSTS
    assert not any("google" in h or "youtube" in h for h in ALLOWED_HOSTS)
    assert cfg.fetchable("https://www.cmcrpc.com/wp-content/uploads/2022/04/X.docx")
    assert not cfg.fetchable("https://drive.google.com/file/d/X/view")
    assert not cfg.fetchable("http://www.cmcrpc.com/wp-content/uploads/a.pdf")      # https only
    assert not cfg.fetchable("https://www.cmcrpc.com/documents/agenda-minutes/")   # a page, not a document


def test_config_rejects_a_kind_without_a_label(tmp_path):
    raw = (rpc.CONFIG).read_text(encoding="utf-8").replace("  cdrb: Common Design Review Board\n", "")
    p = tmp_path / "rpc.yml"
    p.write_text(raw, encoding="utf-8")
    with pytest.raises(rpc.RpcConfigError, match="cdrb"):
        rpc.load_config(p)


# ------------------------------------------------------------------ listing
def test_listing_rows_as_printed(rows):
    rs, problems = rows
    by_id = {r["id"]: r for r in rs}
    assert list(by_id) == ["2026-10-27-regular", "2026-09-21-cdrb", "2026-05-12-executive", "2026-01-27-regular",
                           "2025-10-27-cdrb", "2025-07-29-regular", "2024-08-13-special", "2023-09-26-regular",
                           "2022-08-23-regular", "2022-08-23-special",
                           "2022-04-25-executive"]
    assert problems == ["listing row '13/45/2022': not a real date"]
    assert by_id["2026-09-21-cdrb"]["label"] == "CDRB" and by_id["2026-09-21-cdrb"]["printed"] == "9/21/2026 – CDRB"
    assert by_id["2026-01-27-regular"]["cancelled"] and by_id["2026-01-27-regular"]["label"] == ""
    # a cell that prints the word with no link is a document not posted; "N/A" is not
    assert by_id["2026-10-27-regular"]["no_doc"] == ["minutes"]
    assert by_id["2026-05-12-executive"]["no_doc"] == ["agenda"]
    assert by_id["2026-01-27-regular"]["no_doc"] == []


def test_links_are_taken_from_the_page_never_built(rows):
    rs, _ = rows
    urls = [d["url"] for r in rs for d in r["docs"]]
    page = (FIX / "listing.html").read_text(encoding="utf-8")
    for u in urls:   # every URL is printed on the page (a relative href is only resolved against the page URL)
        assert u in page or u.replace("https://www.cmcrpc.com", "") in page
    assert "https://www.cmcrpc.com/wp-content/uploads/2023/09/Agenda-9-26-2023-1.pdf" in urls
    assert not any("not-in-a-table" in u for u in urls)


def test_other_hosts_are_listed_not_fetched(rows):
    rs, _ = rows
    docs = {d["url"]: d for r in rs for d in r["docs"]}
    drive = docs["https://drive.google.com/file/d/EXAMPLE1/view?usp=drive_link"]
    assert drive["kind"] == "agenda" and drive["fetch"] is False and drive["host"] == "drive.google.com"
    assert docs["https://www.youtube.com/watch?v=EXAMPLE"]["kind"] == "video"
    assert docs["https://www.youtube.com/watch?v=EXAMPLE"]["fetch"] is False
    assert docs["https://www.cmcrpc.com/wp-content/uploads/2022/04/REGIONAL-PLANNING-COMMISSION-EXECUTIVE-COMMITTEE-"
                "AGENDA-1.docx"]["fetch"] is True


def test_listing_that_changed_fails_loudly(cfg):
    with pytest.raises(rpc.ListingError):
        rpc.parse_listing("<html><body><p>Moved</p></body></html>", cfg)


# ------------------------------------------------------------------ fetch
PDF = b"%PDF-1.4 fake"
DOCX = b"PK\x03\x04 fake"


def test_fetch_is_polite_and_stores_pdf_and_docx(cfg, tmp_path):
    listing = (FIX / "listing.html").read_bytes()
    routes = {"https://www.cmcrpc.com/robots.txt": (200, b"User-agent: *\ncrawl-delay: 10\n"), LISTING: (200, listing)}
    page = listing.decode()
    rs, _ = rpc.parse_listing(page, cfg)
    for r in rs:
        for d in r["docs"]:
            if d["fetch"]:
                routes[d["url"]] = (200, DOCX if d["url"].endswith(".docx") else PDF)
    net, clock = FakeNet(routes), Clock()
    f = PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: [])
    store = Store(manifest_path=tmp_path / "manifest.json", root=tmp_path / "store")
    log = rpc.new_log()
    rpc.cmd_fetch(cfg, store, tmp_path / "listing.json", log, fetcher=f)
    urls = [u for u, _ in net.calls]
    assert urls[0] == "https://www.cmcrpc.com/robots.txt" and urls[1] == LISTING
    assert not any("google" in u or "youtube" in u for u in urls)            # listed, never requested
    assert len(urls) == len(set(urls))                                         # a URL listed twice is fetched once
    assert {ua for _, ua in net.calls} == {USER_AGENT}
    assert clock.slept and min(clock.slept) >= 9.99                            # crawl-delay 10 between requests
    assert log["failures"] == [] and log["link_only"] == 2
    kinds = {e["url"].rsplit(".", 1)[1] for e in store.entries}
    assert kinds == {"pdf", "docx"}
    assert json.loads((tmp_path / "listing.json").read_text())[0]["id"] == "2026-10-27-regular"


def test_fetch_refuses_a_docx_that_is_not_one(cfg, tmp_path):
    from collector.store import fetch_into_store
    from collector.fetch import FetchFailed
    url = "https://www.cmcrpc.com/wp-content/uploads/2022/04/X.docx"
    routes = {"https://www.cmcrpc.com/robots.txt": (200, b"User-agent: *\ncrawl-delay: 10\n"), url: (200, b"<html>")}
    clock = Clock()
    f = PoliteFetcher(opener=FakeNet(routes), clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: [])
    store = Store(manifest_path=tmp_path / "m.json", root=tmp_path / "s")
    with pytest.raises(FetchFailed, match="not a DOCX"):
        fetch_into_store(f, store, url, expect="docx")
    assert store.entries == []


# ------------------------------------------------------------------ agenda cases
def test_agenda_cases_as_printed():
    res = rpc_agenda.parse_pages(agenda_pages("agenda_2026-10-27.txt"))
    assert res["printed_date"]["date"] == "2026-10-27"
    nums = [c["number"] for c in res["cases"]]
    assert nums[:3] == ["Z-19-2026", "Z-30-2026", "Z-31-2026"]
    assert "CZ-12-2026" in nums and "SR-86-2026" in nums and "ZO-2A-2026" in nums
    assert len(nums) == 27 and len(set(nums)) == 27
    types = {"Z": "City zoning", "CZ": "County zoning", "SR": "Site review"}
    recs = {c["number"]: rpc_agenda.case_record(c, "m", "src-x", types) for c in res["cases"]}
    z = recs["Z-19-2026"]
    assert z["applicant_label"] == "Owner(s)" and z["applicant"] == "Estate of Jason Feltner, Bob Yates Executor"
    assert z["request"].startswith("AG - Agricultural District to R-2A - Single-Family Residential District")
    assert z["location"].startswith("A large tract of land consisting of two parcels")
    assert z["ward"] == 11 and z["district"] == 1 and z["acres"] == "134.02 +/-" and z["page"] == 1
    assert z["note"] == "RECOMMENDED FOR DEFERRAL" and z["case_type"] == "City zoning"
    assert z["agenda_part"] == "Regular agenda" and z["number_printed"] == "Z - 19 - 2026"
    cz = recs["CZ-12-2026"]
    assert cz["applicant"] == "Chris Blackwell" and cz["ward"] is None and cz["district"] == 6 and cz["page"] == 3
    sr = recs["SR-76-2026"]
    assert sr["applicant_label"] == "Applicant" and sr["request_label"] == "Development"
    assert sr["request"] == "Ferrari Stampi" and sr["proposed_use"] == "Warehouse"
    assert sr["agenda_part"] == "Consent agenda" and sr["case_type"] == "Site review"
    v = recs["V-7-2026"]
    assert v["request_label"] == "Variance request" and v["case_type"] == rpc_agenda.OTHER_CASE
    # OTHER BUSINESS ("A. Profit and Loss Statement") is not a case and does not run into the last case's text
    assert "Profit and Loss" not in recs["SR-86-2026"]["request"] + (recs["SR-86-2026"]["location"] or "")


def test_agenda_hearing_dates_as_printed():
    res = rpc_agenda.parse_pages(agenda_pages("agenda_2026-10-27.txt"))
    assert [(h["printed"], h["date"], h["page"]) for h in res["hearings"]] == [
        ("CITY COUNCIL INFORMAL October 29, 2026 @ 4:30 P.M.", "2026-10-29", 1),
        ("CITY COUNCIL PUBLIC HEARING & FIRST READING November 5, 2026 @ 6:00 P.M.", "2026-11-05", 1),
        ("COUNTY COMMISSION PUBLIC HEARING November 2, 2026 @ 6:00 P.M.", "2026-11-02", 1),
        ("COUNTY COMMISSION FORMAL MEETING November 9, 2026 @ 6:00 P.M.", "2026-11-09", 1)]
    # the 2026-07-28 agenda numbers its hearing lines V. to VIII.
    res = rpc_agenda.parse_pages(agenda_pages("agenda_2026-07-28_p1.txt"))
    assert [h["date"] for h in res["hearings"]] == ["2026-07-30", "2026-08-06", "2026-08-03", "2026-08-10"]
    assert res["cases"][0]["number"] == "Z-18-2026" and res["cases"][0]["agenda_part"] == "Regular agenda"


def test_agenda_2025_layout():
    # "1.   CASE NUMBER: Z - 29 - 2025 APPLICANT Name" (no colon), "UPCOMING MEETINGS DATES/TIMES", and
    # "REGULAR AGENDA ITEM(S):" with no numeral
    res = rpc_agenda.parse_pages(agenda_pages("agenda_2025-07-29_p1-2.txt"))
    assert len(res["hearings"]) == 4 and res["hearings"][0]["date"] == "2025-07-31"
    recs = [rpc_agenda.case_record(c, "m", "s", {"Z": "City zoning"}) for c in res["cases"]]
    assert [(r["number"], r["page"]) for r in recs] == [("Z-29-2025", 1), ("Z-30-2025", 2), ("ZO-4-2024", 2)]
    assert recs[0]["applicant"] == "Charles Thomas Jerles" and recs[0]["applicant_label"] == "Applicant"
    assert recs[0]["request"] == "C-2 - General Commercial District to C-5 - Highway & Arterial Commercial District"
    assert recs[0]["ward"] == 11 and recs[0]["agenda_part"] == "Regular agenda" and recs[0]["case_type"] == "City zoning"
    assert recs[2]["location"] is None and recs[2]["applicant"] == "Regional Planning Commission"


def test_agenda_2022_layout():
    # numeric hearing dates two to a line, "APPLICANT(S): ... AGENT: ...", "APPLIC ANT/OWNER:" split by the text layer,
    # a status printed at the right of a line ("DEFERRED"), rules of asterisks, footers "ZONING - 1"
    res = rpc_agenda.parse_pages(agenda_pages("agenda_2022-10-25.txt"))
    assert res["printed_date"]["date"] == "2022-10-25"
    assert [(h["printed"], h["date"]) for h in res["hearings"]][::3] == [
        ("CITY COUNCIL INFORMAL: 10/27/2022 - 4:30 P.M.", "2022-10-27"),
        ("COUNTY COMMISSION FORMAL MEETING: 11/14/2022 - 6:00 P.M.", "2022-11-14")]
    recs = {c["number"]: rpc_agenda.case_record(c, "m", "s", {}) for c in res["cases"]}
    assert len(recs) == 22 and len(res["cases"]) == 22
    z = recs["Z-75-2022"]
    assert (z["applicant"], z["agent"], z["ward"], z["page"]) == ("Bill Pollard", "Wade Hadley", 4, 1)
    assert recs["Z-76-2022"]["note"] == "DEFERRED" and "DEFERRED" not in recs["Z-76-2022"]["request"]
    s = recs["S-87-2022"]
    assert s["applicant_label"] == "Applicant/owner" and s["note"] == "WITHDRAWN"
    assert s["applicant"] == "DERRICK STEVENS (ASCENSION PROPERTIES LLC)"
    assert s["location"] == "East of and adjacent to the current terminus of West Thompkins Lane."   # "LOC ATION:"
    v = recs["V-4-2022"]
    assert v["request_label"] == "Variance request" and v["applicant"] == "Delton Teeter"
    assert "*" not in v["location"] and "SUBDIVISION VARIANCE" not in v["location"]   # the rule ends the case


def test_case_number_is_normalised():
    assert rpc_agenda.case_number("Z", "05", "2024") == "Z-5-2024"
    assert rpc_agenda.case_number("ZO", "2A", "2026") == "ZO-2A-2026"


def test_build_cites_pages_and_lists_what_was_not_read(cfg, rows, tmp_path):
    rs, _ = rows
    store = Store(manifest_path=tmp_path / "manifest.json", root=tmp_path / "store")
    agenda_url = "https://www.cmcrpc.com/wp2025/wp-content/uploads/2026/10/Agenda-10.27.2026.pdf"
    store.put(agenda_url, b"%PDF agenda", {}, {"kind": "agenda", "meeting_date": "2026-10-27"})
    scan_url = "https://www.cmcrpc.com/wp2025/wp-content/uploads/2026/10/Agenda-9-21-2026-Common-Design-Review-1.pdf"
    store.put(scan_url, b"%PDF scan", {}, {"kind": "agenda", "meeting_date": "2026-09-21"})
    texts = {store.latest(agenda_url)["sha256"]: agenda_pages("agenda_2026-10-27.txt"),
             store.latest(scan_url)["sha256"]: ["", ""]}

    def extract(p):
        return texts[p.stem]

    facts, summary = rpc_agenda.build(cfg, rs, store, extract=extract)
    by_id = {m["id"]: m for m in facts["meetings"]}
    m = by_id["2026-10-27-regular"]
    assert m["case_count"] == 27 and m["agenda_date"] == "2026-10-27" and len(m["hearings"]) == 4
    src = {s["id"]: s for s in facts["sources"]}[m["agenda_source_id"]]
    assert src["url"] == agenda_url and src["text_layer"] == "text"
    assert all(1 <= c["page"] <= src["pages"] and c["source_id"] == src["id"] for c in facts["cases"])
    assert by_id["2026-09-21-cdrb"]["case_count"] == 0
    assert any("2026-09-21-cdrb: agenda has no text layer" in p for p in summary["problems"])
    drive = [d for d in by_id["2024-08-13-special"]["documents"] if d["host"] == "drive.google.com"][0]
    assert drive["fetched"] is False and drive["source_id"] is None
    assert summary["cases"] == 27 and summary["meetings"] == 11
