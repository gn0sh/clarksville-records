"""Daylight Digest Legistar upcoming reader (collector/national/legistar_upcoming.py; docs/architecture/daylight-national.md
3.5, 3.7, 4.5 and section 11 rows 18-19; task C2). Fixtures are hand-made in the Legistar Web API's documented shapes
(tests/fixtures/national/legistar/, see their `_comment`), never recorded and never fetched: every request goes to a
recorded fetcher that answers from them. Problem keys: privacy-withhold/national-prefix (a withheld `place-` youth
council and an `sd*` board make no items request and leave no item text), national/url-scheme-untrusted and
national/untrusted-size (B14 guards on every field read)."""
import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from collector.fetch import PoliteFetcher
from collector.national import legistar_upcoming as lu
from sitegen import national as nat
from sitegen.national_clarksville import feed_errors

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "national" / "legistar"
NOW = datetime(2026, 12, 1, 18, 0, tzinfo=timezone.utc)          # 10:00 in Salem: today is 2026-12-01
SENTINELS = ("SENTINEL-ITEM-TEXT", "SENTINEL-PERSON-NAME", "SENTINEL-NOTE-TEXT")
HOST_OK = {"date": "2026-12-01", "link": "https://github.com/gn0sh/clarksville-records/pull/1"}

SALEM = {"gov": "place-4164900", "also": [], "body_name": "Salem City Council", "state": "OR", "status": "covered",
         "official_url": "https://salem.legistar.com/Calendar.aspx", "checked": "2026-12-01",
         "checked_url": "https://salem.legistar.com/Calendar.aspx", "items": "shown", "platform": "legistar",
         "legistar": {"client": "salem", "body_id": 138, "tz": "America/Los_Angeles"}, "host_ok": HOST_OK}
YOUTH = {"gov": "place-4199999", "also": [], "body_name": "Example Youth Council", "state": "OR", "status": "covered",
         "official_url": "https://salem.legistar.com/Calendar.aspx", "checked": "2026-12-01",
         "checked_url": "https://salem.legistar.com/Calendar.aspx", "items": "withheld", "platform": "legistar",
         "legistar": {"client": "salem", "body_id": 250, "tz": "America/Los_Angeles"}, "host_ok": HOST_OK}
SCHOOL = {"gov": "sdu-4199998", "also": [], "body_name": "Example School District Board of Directors", "state": "OR",
          "status": "covered", "official_url": "https://exampleschools.legistar.com/Calendar.aspx",
          "checked": "2026-12-01", "checked_url": "https://exampleschools.legistar.com/Calendar.aspx",
          "platform": "legistar", "legistar": {"client": "exampleschools", "body_id": 12, "tz": "America/Los_Angeles"},
          "host_ok": HOST_OK}


def fixture(name):
    return json.loads((FIXTURES / f"legistar-{name}.json").read_text(encoding="utf-8"))


class Recorded:
    """A fetcher with the public `get(url) -> (status, body, headers)` of collector.fetch.PoliteFetcher, answering
    from the hand-made fixtures. `answers` overrides (status, body) per request kind ("events" or an event id)."""

    def __init__(self, *names, answers=None):
        self.fx = {f["client"]: f for f in map(fixture, names)}
        self.calls = []
        self.answers = answers or {}

    def get(self, url):
        self.calls.append(url)
        u = urlsplit(url)
        assert (u.scheme, u.hostname) == ("https", "webapi.legistar.com"), url
        parts = u.path.split("/")
        fx = self.fx[parts[2]]
        if parts[3:] == ["events"]:
            if "events" in self.answers:
                return self.answers["events"]
            flt = parse_qs(u.query)["$filter"][0]
            m = re.fullmatch(r"EventBodyId eq (\d+) and EventDate ge datetime'([\d-]+)' and EventDate lt "
                             r"datetime'([\d-]+)'", flt)
            assert m, flt
            return 200, json.dumps(fx["events"].get(m.group(1), [])).encode(), {}
        assert parts[3] == "events" and parts[5:] == ["eventitems"], url
        if parts[4] in self.answers:
            return self.answers[parts[4]]
        return 200, json.dumps(fx["eventitems"].get(parts[4], [])).encode(), {}

    def items_calls(self):
        return [c for c in self.calls if c.endswith("/eventitems")]


def directory(tmp_path, monkeypatch, *govs, reviewed=(SALEM,)):
    rows = tuple(nat.ShownReview(e["gov"], nat.norm_entry(e)) for e in reviewed)
    monkeypatch.setattr(nat, "SHOWN_REVIEWED", nat.SHOWN_REVIEWED + rows)
    p = tmp_path / "directory.yml"
    p.write_text(yaml.safe_dump({"schema": "daylight-directory/1", "govs": list(govs)}, sort_keys=False),
                 encoding="utf-8")
    return nat.load_directory(p, nat.load_labels())


@pytest.fixture
def loaded(tmp_path, monkeypatch):
    d = directory(tmp_path, monkeypatch, SALEM, YOUTH, SCHOOL)
    return {g["gov"]: g for g in d.govs}, d


def by_id(feed):
    return {m["id"]: m for m in feed["meetings"]}


def files_text(folder: Path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in folder.rglob("*") if p.is_file()) if folder.exists() else ""


# --- URLs ---------------------------------------------------------------------------------------------------------

def test_events_url_filters_by_body_id_and_window_and_passes_the_fetchers_url_check():
    url = lu.events_url("salem", 138, datetime(2026, 11, 30).date(), datetime(2026, 12, 30).date())
    u = urlsplit(url)
    assert (u.scheme, u.hostname, u.path) == ("https", "webapi.legistar.com", "/v1/salem/events")
    assert parse_qs(u.query) == {"$filter": ["EventBodyId eq 138 and EventDate ge datetime'2026-11-30' and EventDate "
                                             "lt datetime'2026-12-30'"], "$orderby": ["EventDate asc"]}
    PoliteFetcher().check_url(url)                       # no space, quote or control character goes on the wire
    assert lu.items_url("salem", 1001) == "https://webapi.legistar.com/v1/salem/events/1001/eventitems"


# --- agenda state -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("status, file, finals, state", [
    ("Final", "x.pdf", None, "final"),
    ("Final-Revised", "x.pdf", None, "final"),
    ("Final-Addendum", None, None, "final"),
    ("Draft", "x.pdf", None, "not-final"),
    ("Draft", None, None, "not-final"),
    ("Pending Clerk Review", "x.pdf", None, "not-final"),
    ("final", "x.pdf", None, "not-final"),             # exact names only: fail closed
    ("Final ", "x.pdf", None, "not-final"),
    ("Final‮", "x.pdf", None, "not-final"),
    ("", "x.pdf", None, "not-final"),
    (None, "x.pdf", None, "not-final"),
    (None, None, None, "not-posted"),
    ("", " ", None, "not-posted"),
    ("Final-Revised", "x.pdf", ["Final"], "not-final"),   # the entry's own final_statuses list
    ("Final", "x.pdf", ["Final"], "final"),
])
def test_agenda_state(status, file, finals, state):
    ev = {"EventAgendaStatusName": status, "EventAgendaFile": file}
    assert lu.agenda_state(ev, finals or nat.LEGISTAR_FINAL_STATUSES) == state


# --- a shown body -------------------------------------------------------------------------------------------------

def test_shown_body_reads_items_only_for_final_agendas(loaded):
    govs, _ = loaded
    f = Recorded("salem")
    r = lu.read_body(govs["place-4164900"], f, NOW)
    feed = r.feed
    assert feed_errors(feed) == []
    assert feed["review"] == govs["place-4164900"]["review"] and re.fullmatch(r"[0-9a-f]{64}", feed["review"])
    assert feed["checked_at"] == feed["last_ok_at"] == "2026-12-01T18:00:00Z"
    assert feed["body"] == {"id": "place-4164900", "name": "Salem City Council", "tz": "America/Los_Angeles",
                            "official_url": "https://salem.legistar.com/Calendar.aspx", "platform": "legistar",
                            "full_url": None}
    m = by_id(feed)
    # 1000 is yesterday (dropped), 1005 is another EventBodyId (dropped)
    assert list(m) == ["2026-12-03-e1001", "2026-12-08-e1002", "2026-12-10-e1003", "2026-12-15-e1004",
                       "2026-12-17-e1006", "2026-12-22-e1007"]
    assert (r.counts.past_dropped, r.counts.other_body_dropped, r.counts.events) == (1, 1, 8)
    # Final and Final-Revised: items read; Draft, unknown and not posted: no request
    assert sorted(c.split("/")[-2] for c in f.items_calls()) == ["1001", "1002", "1007"]
    assert r.counts.items_requests == 3
    final = m["2026-12-03-e1001"]
    assert final["agenda"] == {"state": "final", "status_as_posted": "Final",
                               "url": "https://salem.legistar.com/View.ashx?M=A&ID=1001&GUID=00000000-0000-0000-"
                                      "0000-000000001001"}
    assert (final["items_withheld"], final["item_count"], final["may_be_incomplete"]) == (False, 3, True)
    assert [(i["seq"], i["number"]) for i in final["items"]] == [(1, "1."), (2, "2."), (3, None)]
    assert final["items"][1]["text"] == "Ordinance 26-1001 amending chapter 5 SENTINEL-ITEM-TEXT (zoning)"
    assert final["items"][0]["source"] == {"url": final["agenda"]["url"], "page": None}
    assert (final["time"], final["title"], final["title_ours"]) == ("6:00 PM", "Meeting", True)
    assert m["2026-12-08-e1002"]["agenda"]["state"] == "final" and m["2026-12-08-e1002"]["item_count"] == 3
    for mid, state in (("2026-12-10-e1003", "not-final"), ("2026-12-15-e1004", "not-final"),
                       ("2026-12-17-e1006", "not-posted")):
        assert (m[mid]["agenda"]["state"], m[mid]["items"], m[mid]["item_count"]) == (state, [], None)
        assert m[mid]["items_withheld"] is False
    assert m["2026-12-17-e1006"]["time"] is None
    # nothing from the other body, nothing from fields we never read
    text = json.dumps(feed)
    assert "SENTINEL-PERSON-NAME" not in text and "SENTINEL-NOTE-TEXT" not in text and "1005" not in text
    assert "matter name" not in text and "minutes-only" not in text


def test_draft_agenda_makes_no_items_request_and_is_not_final(loaded):
    govs, _ = loaded
    draft = [e for e in fixture("salem")["events"]["138"] if e["EventId"] == 1003]
    f = Recorded("salem", answers={"events": (200, json.dumps(draft).encode(), {})})
    feed = lu.read_body(govs["place-4164900"], f, NOW).feed
    assert f.items_calls() == []
    (m,) = feed["meetings"]
    assert (m["agenda"]["state"], m["agenda"]["status_as_posted"], m["items"], m["item_count"]) == (
        "not-final", "Draft", [], None)


def test_unknown_status_is_not_final_with_one_proposal(loaded):
    govs, _ = loaded
    f = Recorded("salem")
    r = lu.read_body(govs["place-4164900"], f, NOW)
    assert by_id(r.feed)["2026-12-15-e1004"]["agenda"]["state"] == "not-final"
    assert not any("/1004/" in c for c in f.calls)
    assert r.proposals == [{"body": "place-4164900", "kind": "agenda-status-name", "observed": "Pending Clerk Review",
                            "evidence_url": "https://salem.legistar.com/MeetingDetail.aspx?ID=1004&GUID=00000000-"
                                            "0000-0000-0000-000000001004",
                            "first_seen": "2026-12-01T18:00:00Z", "count": 1}]
    assert r.counts.unknown_status == 1


def test_an_odd_status_name_is_counted_not_copied_into_the_proposal(loaded):
    govs, _ = loaded
    ev = copy.deepcopy(fixture("salem")["events"]["138"][4])
    ev["EventAgendaStatusName"] = "Final‮ SENTINEL" + "x" * 80
    r = lu.read_body(govs["place-4164900"], Recorded("salem", answers={"events": (200, json.dumps([ev]).encode(),
                                                                                  {})}), NOW)
    assert [(p["observed"], p["count"]) for p in r.proposals] == [(None, 1)]
    assert r.feed["meetings"][0]["agenda"]["state"] == "not-final"


def test_entry_final_statuses_narrow_what_is_final(tmp_path, monkeypatch):
    e = copy.deepcopy(SALEM)
    e["legistar"]["final_statuses"] = ["Final"]
    (g,) = directory(tmp_path, monkeypatch, e, reviewed=(e,)).govs
    f = Recorded("salem")
    r = lu.read_body(g, f, NOW)
    assert by_id(r.feed)["2026-12-08-e1002"]["agenda"]["state"] == "not-final"     # Final-Revised is not on its list
    assert sorted(c.split("/")[-2] for c in f.items_calls()) == ["1001", "1007"]
    assert [p["observed"] for p in r.proposals] == ["Pending Clerk Review"]         # a known name is no proposal


def test_shown_without_a_review_digest_reads_no_items(loaded):
    """is_shown needs the digest load_directory sets after the whole-entry SHOWN_REVIEWED match: an entry that says
    `shown` but was not bound by the loader (review None) is withheld."""
    govs, _ = loaded
    g = dict(govs["place-4164900"], review=None)
    f = Recorded("salem")
    feed = lu.read_body(g, f, NOW).feed
    assert f.items_calls() == [] and feed["review"] is None
    assert all(m["items"] == [] and m["items_withheld"] for m in feed["meetings"])


def test_a_changed_shown_entry_does_not_load(tmp_path, monkeypatch):
    """The SHOWN_REVIEWED row pins the whole entry: another body_id under the same row is refused at load, so the
    reader never sees it as shown."""
    e = copy.deepcopy(SALEM)
    e["legistar"]["body_id"] = 250
    with pytest.raises(nat.NationalConfigError, match="SHOWN_REVIEWED"):
        directory(tmp_path, monkeypatch, e, reviewed=(SALEM,))


# --- withheld bodies: a place- youth council and an sd* board (privacy-withhold/national-prefix) --------------------

@pytest.mark.parametrize("gov, client", [("place-4199999", "salem"), ("sdu-4199998", "exampleschools")])
def test_withheld_body_makes_no_items_request_and_keeps_no_item_text(loaded, tmp_path, gov, client):
    govs, _ = loaded
    cache = tmp_path / "cache"
    stale = cache / gov
    stale.mkdir(parents=True)
    (stale / "2501.json").write_text('{"items": [{"text": "SENTINEL-ITEM-TEXT"}]}', encoding="utf-8")
    f = Recorded("salem", "exampleschools")
    r = lu.read_body(govs[gov], f, NOW, cache_root=cache)
    assert f.calls and f.items_calls() == []                 # one events query, no items request at all
    assert len(f.calls) == 1 and f.calls[0].startswith(f"https://webapi.legistar.com/v1/{client}/events?")
    feed = r.feed
    assert feed_errors(feed) == [] and feed["review"] is None and feed["meetings"]
    text = json.dumps(feed)
    assert not any(s in text for s in SENTINELS)
    for m in feed["meetings"]:
        assert (m["items"], m["item_count"], m["items_withheld"]) == ([], None, True)
        assert (m["title"], m["title_ours"], m["time"], m["agenda"]["status_as_posted"]) == ("Meeting", True, None,
                                                                                              None)
    assert {m["agenda"]["state"] for m in feed["meetings"]} >= {"final"}
    assert r.counts.bind.withheld_stripped == 0             # the reader never put item content in to be stripped
    assert r.counts.items_requests == 0 and r.counts.cache_deleted == 1
    assert not stale.exists() and files_text(cache) == ""


def test_prune_cache_keeps_only_shown_legistar_bodies(loaded, tmp_path):
    _, d = loaded
    cache = tmp_path / "cache"
    for name in ("place-4164900", "place-4199999", "sdu-4199998", "place-4100000", "junk"):
        (cache / name).mkdir(parents=True)
        (cache / name / "1.json").write_text("{}", encoding="utf-8")
    (cache / "stray.json").write_text("{}", encoding="utf-8")
    assert lu.prune_cache(d, cache) == ["junk", "place-4100000", "place-4199999", "sdu-4199998", "stray.json"]
    assert [p.name for p in cache.iterdir()] == ["place-4164900"]


# --- agenda PDFs are linked, never requested ----------------------------------------------------------------------

def test_only_the_api_is_requested_never_an_agenda_pdf_or_client_page(loaded):
    govs, _ = loaded
    f = Recorded("salem", "exampleschools")
    for g in govs.values():
        lu.read_body(g, f, NOW)
    assert f.calls and all(c.startswith("https://webapi.legistar.com/v1/") for c in f.calls)
    linked = {e["EventAgendaFile"] for fx in ("salem", "exampleschools") for evs in fixture(fx)["events"].values()
              for e in evs} | {e["EventInSiteURL"] for evs in fixture("salem")["events"].values() for e in evs}
    assert not linked & set(f.calls)


def test_through_the_polite_fetcher_only_robots_and_the_api_are_asked():
    """The same reader on the real PoliteFetcher (public API only), its network faked: robots.txt once, the events
    query, one items request per final agenda; every URL passes the fetcher's own checks."""
    import io
    import urllib.error

    fx = fixture("salem")
    net = []

    class Resp(io.BytesIO):
        status, headers = 200, {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout):
        url = req.full_url
        net.append(url)
        u = urlsplit(url)
        if u.path == "/robots.txt":
            raise urllib.error.HTTPError(url, 404, "x", {}, io.BytesIO(b""))
        if u.path == "/v1/salem/events":
            return Resp(json.dumps(fx["events"]["138"]).encode())
        return Resp(json.dumps(fx["eventitems"][u.path.split("/")[4]]).encode())

    pf = PoliteFetcher(opener=opener, sleep=lambda s: None, proxy_failures=lambda: [],
                       allowed_hosts=("webapi.legistar.com",))
    entry = dict(copy.deepcopy(SALEM), review="0" * 64)
    feed = lu.read_body(entry, pf, NOW).feed
    assert [urlsplit(u).path for u in net] == ["/robots.txt", "/v1/salem/events", "/v1/salem/events/1001/eventitems",
                                               "/v1/salem/events/1002/eventitems", "/v1/salem/events/1007/eventitems"]
    assert by_id(feed)["2026-12-03-e1001"]["item_count"] == 3


# --- B14 guards on every field read -------------------------------------------------------------------------------

def test_b14_urls_and_text_from_the_answer_are_guarded(loaded):
    govs, _ = loaded
    r = lu.read_body(govs["place-4164900"], Recorded("salem"), NOW)
    m = by_id(r.feed)
    revised = m["2026-12-08-e1002"]          # agenda PDF on a host off the Legistar allowlist: linked as null
    assert revised["agenda"]["url"] is None and all(i["source"]["url"] is None for i in revised["items"])
    assert (revised["title"], revised["title_ours"], revised["time"]) == ("Work Session", False, "5:30 PM")
    bad = m["2026-12-22-e1007"]              # javascript: page link and an http agenda: both null
    assert (bad["meeting_url"], bad["agenda"]["url"]) == (None, None)
    assert m["2026-12-03-e1001"]["meeting_url"].startswith("https://salem.legistar.com/MeetingDetail.aspx?ID=1001")
    assert "‮" not in json.dumps(r.feed, ensure_ascii=False)
    assert r.counts.guard.chars_stripped >= 3


def test_b14_caps_on_items_text_and_meetings(loaded):
    govs, _ = loaded
    fx = fixture("salem")
    base = next(e for e in fx["events"]["138"] if e["EventId"] == 1001)
    events = []
    for n in range(70):
        e = copy.deepcopy(base)
        e["EventId"], e["EventDate"] = 3000 + n, f"2026-12-{2 + n % 27:02d}T00:00:00"
        events.append(e)
    item = fx["eventitems"]["1001"][0]
    long_items = [dict(item, EventItemId=9000 + n, EventItemAgendaSequence=n + 1,
                       EventItemTitle=("SENTINEL-ITEM-TEXT " + "w" * 2500) if n == 0 else f"Item {n}")
                  for n in range(160)]
    answers = {"events": (200, json.dumps(events).encode(), {})}
    answers.update({str(3000 + n): (200, json.dumps(long_items).encode(), {}) for n in range(70)})
    r = lu.read_body(govs["place-4164900"], Recorded("salem", answers=answers), NOW)
    feed = r.feed
    assert feed_errors(feed) == []
    assert len(feed["meetings"]) == 60 and r.counts.guard.meetings_dropped == 10
    first = feed["meetings"][0]
    assert len(first["items"]) == 150 and first["item_count"] == 160
    assert first["items"][0]["cut"] is True and len(first["items"][0]["text"]) <= 2000


def test_a_title_over_the_cap_is_cut_and_controls_are_word_breaks(loaded):
    govs, _ = loaded
    ev = copy.deepcopy(fixture("salem")["events"]["138"][1])
    ev["EventComment"], ev["EventTime"] = "Special\r\nMeeting " + "z" * 3000, "6:00\u0007 PM"
    r = lu.read_body(govs["place-4164900"], Recorded("salem", answers={"events": (200, json.dumps([ev]).encode(),
                                                                                  {})}), NOW)
    m = r.feed["meetings"][0]
    assert m["title"].startswith("Special Meeting zzz") and len(m["title"]) == 2000
    assert m["time"] == "6:00 PM"


@pytest.mark.parametrize("ev, why", [
    ({"EventId": True, "EventBodyId": 138, "EventDate": "2026-12-03T00:00:00"}, "bad"),
    ({"EventId": 5, "EventBodyId": 138, "EventDate": "2026-13-03T00:00:00"}, "bad"),
    ({"EventId": 5, "EventBodyId": 138, "EventDate": "../../x"}, "bad"),
    ({"EventId": -5, "EventBodyId": 138, "EventDate": "2026-12-03T00:00:00"}, "bad"),
    ({"EventId": 5, "EventBodyId": "138", "EventDate": "2026-12-03T00:00:00"}, "other"),
    ({"EventId": 5, "EventBodyId": True, "EventDate": "2026-12-03T00:00:00"}, "other"),
    ("not an object", "bad"),
])
def test_malformed_event_rows_are_dropped_and_counted(loaded, ev, why):
    govs, _ = loaded
    f = Recorded("salem", answers={"events": (200, json.dumps([ev]).encode(), {})})
    r = lu.read_body(govs["place-4164900"], f, NOW)
    assert r.feed["meetings"] == [] and f.items_calls() == []
    assert (r.counts.bad_dropped, r.counts.other_body_dropped) == ((1, 0) if why == "bad" else (0, 1))


@pytest.mark.parametrize("answer, kind", [
    ((500, b"", {}), "server-error"),
    ((404, b"{}", {}), "not-enabled-suspected"),
    ((401, b"", {}), "token-suspected"),
    ((200, b"<html>SENTINEL-ITEM-TEXT</html>", {}), "not-enabled-suspected"),
    ((200, b'{"Message": "x"}', {}), "not-enabled-suspected"),
    ((200, b"[" + b" " * (lu.MAX_RESPONSE_BYTES + 1) + b"]", {}), "server-error"),
])
def test_an_unusable_events_answer_is_a_read_error_without_its_text(loaded, answer, kind):
    govs, _ = loaded
    with pytest.raises(lu.ReadError) as e:
        lu.read_body(govs["place-4164900"], Recorded("salem", answers={"events": answer}), NOW)
    assert e.value.kind == kind and "SENTINEL" not in str(e.value) and "place-4164900" in str(e.value)


def test_an_unusable_items_answer_is_a_read_error(loaded):
    govs, _ = loaded
    with pytest.raises(lu.ReadError, match="event 1001 items answered HTTP 500"):
        lu.read_body(govs["place-4164900"], Recorded("salem", answers={"1001": (500, b"", {})}), NOW)


def test_read_body_refuses_an_entry_that_is_not_covered_legistar(loaded):
    govs, _ = loaded
    with pytest.raises(ValueError):
        lu.read_body(dict(govs["place-4164900"], platform="daylight"), Recorded("salem"), NOW)


# --- the cache, keyed by EventAgendaLastPublishedUTC and the review (11.1 row 19) ----------------------------------

def test_cache_by_last_published_and_review(loaded, tmp_path):
    govs, _ = loaded
    g = govs["place-4164900"]
    cache = tmp_path / "cache"
    first = Recorded("salem")
    feed1 = lu.read_body(g, first, NOW, cache_root=cache).feed
    folder = cache / "place-4164900"
    # 1007 has no LastPublished: read every run, never cached
    assert sorted(p.name for p in folder.iterdir()) == ["1001.json", "1002.json"]
    doc = json.loads((folder / "1001.json").read_text(encoding="utf-8"))
    assert (doc["review"], doc["body"], doc["event_id"], doc["last_published"]) == (
        g["review"], "place-4164900", 1001, "2026-11-26T19:04:12.4")
    assert doc["items"] == by_id(feed1)["2026-12-03-e1001"]["items"]          # cleaned items, as published

    again = Recorded("salem")
    r2 = lu.read_body(g, again, NOW, cache_root=cache)
    assert [c.split("/")[-2] for c in again.items_calls()] == ["1007"] and r2.counts.cache_hits == 2
    assert r2.feed == feed1

    # the agenda was published again: re-read
    fx = Recorded("salem")
    next(e for e in fx.fx["salem"]["events"]["138"] if e["EventId"] == 1001)["EventAgendaLastPublishedUTC"] = \
        "2026-11-30T09:00:00"
    lu.read_body(g, fx, NOW, cache_root=cache)
    assert sorted(c.split("/")[-2] for c in fx.items_calls()) == ["1001", "1007"]
    assert json.loads((folder / "1001.json").read_text(encoding="utf-8"))["last_published"] == "2026-11-30T09:00:00"


def test_a_cache_file_under_another_review_is_a_miss_and_deleted(loaded, tmp_path):
    govs, _ = loaded
    g = govs["place-4164900"]
    cache = tmp_path / "cache"
    folder = cache / "place-4164900"
    folder.mkdir(parents=True)
    old = {"schema": lu.CACHE_SCHEMA, "review": "f" * 64, "body": "place-4164900", "event_id": 1001,
           "last_published": "2026-11-26T19:04:12.4", "items": [{"seq": 1, "number": None, "text": "OLD-REVIEW-TEXT",
                                                                 "source": {"url": None, "page": None}}]}
    (folder / "1001.json").write_text(json.dumps(old), encoding="utf-8")
    (folder / "4444.json").write_text(json.dumps(dict(old, event_id=4444)), encoding="utf-8")   # not in this run
    (folder / "notes.txt").write_text("x", encoding="utf-8")
    f = Recorded("salem")
    r = lu.read_body(g, f, NOW, cache_root=cache)
    assert "1001" in [c.split("/")[-2] for c in f.items_calls()]
    assert "OLD-REVIEW-TEXT" not in json.dumps(r.feed) and "OLD-REVIEW-TEXT" not in files_text(cache)
    assert sorted(p.name for p in folder.iterdir()) == ["1001.json", "1002.json"]
    assert r.counts.cache_deleted == 3


def test_a_tampered_cache_file_is_a_miss(loaded, tmp_path):
    govs, _ = loaded
    g = govs["place-4164900"]
    cache = tmp_path / "cache"
    lu.read_body(g, Recorded("salem"), NOW, cache_root=cache)
    path = cache / "place-4164900" / "1001.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(dict(doc, items="not a list")), encoding="utf-8")
    f = Recorded("salem")
    lu.read_body(g, f, NOW, cache_root=cache)
    assert "1001" in [c.split("/")[-2] for c in f.items_calls()]
    assert isinstance(json.loads(path.read_text(encoding="utf-8"))["items"], list)


def test_fixtures_are_marked_hand_made():
    for p in FIXTURES.glob("*.json"):
        assert json.loads(p.read_text(encoding="utf-8"))["_comment"].startswith("HAND-MADE, NOT RECORDED"), p.name


# --- cache confinement (code review C2: cache-confine/symlinked-body-folder, cache-confine/root-symlink) ------------

def outside_state(folder: Path) -> dict:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(folder.iterdir())}


def test_a_symlinked_shown_body_folder_is_unlinked_never_followed(loaded, tmp_path):
    govs, _ = loaded
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep me", encoding="utf-8")
    (outside / "1001.json").write_text("{}", encoding="utf-8")
    before = outside_state(outside)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "place-4164900").symlink_to(outside, target_is_directory=True)
    r = lu.read_body(govs["place-4164900"], Recorded("salem"), NOW, cache_root=cache)
    assert outside_state(outside) == before                       # nothing deleted or written outside
    folder = cache / "place-4164900"
    assert not folder.is_symlink() and folder.is_dir()
    assert sorted(p.name for p in folder.iterdir()) == ["1001.json", "1002.json"]
    assert r.counts.cache_deleted == 1


@pytest.mark.parametrize("gov", ["place-4199999", "sdu-4199998"])
def test_a_symlinked_withheld_body_folder_is_unlinked_never_followed(loaded, tmp_path, gov):
    govs, _ = loaded
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep me", encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / gov).symlink_to(outside, target_is_directory=True)
    lu.read_body(govs[gov], Recorded("salem", "exampleschools"), NOW, cache_root=cache)
    assert outside_state(outside) == {"precious.txt": "keep me"} and list(cache.iterdir()) == []


def test_a_symlinked_cache_file_is_unlinked_and_its_target_untouched(loaded, tmp_path):
    govs, _ = loaded
    cache = tmp_path / "cache"
    (cache / "place-4164900").mkdir(parents=True)
    secret = tmp_path / "secret.json"
    secret.write_text("{}", encoding="utf-8")
    (cache / "place-4164900" / "1001.json").symlink_to(secret)
    (cache / "place-4164900" / ".1002.json.tmp").symlink_to(secret)       # a planted temporary-file link
    lu.read_body(govs["place-4164900"], Recorded("salem"), NOW, cache_root=cache)
    assert secret.read_text(encoding="utf-8") == "{}"
    assert not any(p.is_symlink() for p in (cache / "place-4164900").iterdir())


def test_cache_put_refuses_a_folder_that_is_not_a_real_folder_in_the_root(loaded, tmp_path):
    govs, _ = loaded
    root = (tmp_path / "cache").resolve()
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    (root / "place-4164900").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="cache-confine"):
        lu._cache_put(root, root / "place-4164900", govs["place-4164900"], 1001, "2026-11-26T19:04:12.4", [], 0)
    assert list(outside.iterdir()) == []


def test_a_symlinked_cache_root_is_refused(loaded, tmp_path):
    govs, d = loaded
    real = tmp_path / "real"
    (real / "junk").mkdir(parents=True)
    link = tmp_path / "cache"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="root-symlink"):
        lu.prune_cache(d, link)
    with pytest.raises(ValueError, match="root-symlink"):
        lu.read_body(govs["place-4164900"], Recorded("salem"), NOW, cache_root=link)
    assert [p.name for p in real.iterdir()] == ["junk"]


# --- code review C2: legistar-cache/item-count-drift, legistar-window/no-upper-bound --------------------------------

def test_a_cache_hit_gives_the_same_item_count_as_a_fresh_read(loaded, tmp_path):
    govs, _ = loaded
    fx = fixture("salem")
    ev = next(e for e in fx["events"]["138"] if e["EventId"] == 1001)
    item = fx["eventitems"]["1001"][0]
    rows = [dict(item, EventItemId=9000 + n, EventItemAgendaSequence=n + 1, EventItemTitle=f"Item {n}")
            for n in range(160)]
    answers = {"events": (200, json.dumps([ev]).encode(), {}), "1001": (200, json.dumps(rows).encode(), {})}
    cache = tmp_path / "cache"
    fresh = lu.read_body(govs["place-4164900"], Recorded("salem", answers=answers), NOW, cache_root=cache)
    f = Recorded("salem", answers=answers)
    hit = lu.read_body(govs["place-4164900"], f, NOW, cache_root=cache)
    assert f.items_calls() == [] and hit.counts.cache_hits == 1
    assert hit.feed == fresh.feed and hit.feed["meetings"][0]["item_count"] == 160
    assert len(hit.feed["meetings"][0]["items"]) == 150


def test_an_event_past_the_window_is_dropped_and_counted(loaded):
    govs, _ = loaded
    base = fixture("salem")["events"]["138"][3]                  # Draft: no items request either way
    last, over = copy.deepcopy(base), copy.deepcopy(base)
    last["EventId"], last["EventDate"] = 4001, "2026-12-29T00:00:00"     # today + 28: kept
    over["EventId"], over["EventDate"] = 4002, "2026-12-30T00:00:00"     # today + 29: the API ignored the filter
    r = lu.read_body(govs["place-4164900"], Recorded("salem", answers={
        "events": (200, json.dumps([last, over]).encode(), {})}), NOW)
    assert [m["id"] for m in r.feed["meetings"]] == ["2026-12-29-e4001"] and r.counts.future_dropped == 1
