"""Reader-facing dates (docs/architecture/local-dates.md, problem family feeds/entry-date-is-local-day): every date the
site shows is the America/Chicago day of the instant; stored timestamps stay UTC; meeting dates are never shifted."""
import copy
import json
import re
from datetime import date, datetime, timezone

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS
from qa import site_checks
from sitegen import build as build_mod, localdates, views

TZ = "America/Chicago"


@pytest.fixture(autouse=True)
def _no_instants():
    """Every test starts and ends with no known instants (localdates keeps them per build)."""
    localdates.use({})
    yield
    localdates.use({})


@pytest.mark.parametrize("ts, want", [
    # winter (CST, UTC-6)
    ("2026-01-15T12:00:00+00:00", "2026-01-15"),
    ("2026-01-15T05:59:59+00:00", "2026-01-14"),
    ("2026-01-15T06:00:00+00:00", "2026-01-15"),
    # summer (CDT, UTC-5)
    ("2026-07-01T04:59:59+00:00", "2026-06-30"),
    ("2026-07-01T05:00:00+00:00", "2026-07-01"),
    # spring forward, Sunday 2026-03-08 (02:00 CST -> 03:00 CDT at 08:00Z): the day starts at CST, ends at CDT
    ("2026-03-08T05:59:59+00:00", "2026-03-07"),
    ("2026-03-08T06:00:00+00:00", "2026-03-08"),
    ("2026-03-08T08:30:00+00:00", "2026-03-08"),
    ("2026-03-09T04:59:59+00:00", "2026-03-08"),
    ("2026-03-09T05:00:00+00:00", "2026-03-09"),
    # fall back, Sunday 2026-11-01 (02:00 CDT -> 01:00 CST at 07:00Z): the day starts at CDT, ends at CST
    ("2026-11-01T04:59:59+00:00", "2026-10-31"),
    ("2026-11-01T05:00:00+00:00", "2026-11-01"),
    ("2026-11-01T06:30:00+00:00", "2026-11-01"),   # 01:30 CDT, the first of the two 01:30s
    ("2026-11-01T07:30:00+00:00", "2026-11-01"),   # 01:30 CST, the second
    ("2026-11-02T05:59:59+00:00", "2026-11-01"),
    ("2026-11-02T06:00:00+00:00", "2026-11-02"),
    # a late-evening fetch in Clarksville (22:38 CST) is stored as the next UTC day
    ("2026-11-10T04:38:00+00:00", "2026-11-09"),
    ("2026-11-09T22:38:00-06:00", "2026-11-09"),
])
def test_local_day_is_the_chicago_calendar_day_of_the_instant(ts, want):
    assert localdates.local_day(ts, TZ) == want
    assert localdates.local_day(datetime.fromisoformat(ts), TZ) == want


def test_local_day_reads_the_zone_from_config():
    assert localdates.local_day("2026-11-10T04:38:00+00:00") == "2026-11-09"   # config/site.yml site_timezone


@pytest.mark.parametrize("bad", ["2026-11-10", date(2026, 11, 10), datetime(2026, 11, 10, 4, 38), "", None])
def test_a_day_or_a_naive_time_is_never_converted(bad):
    with pytest.raises((ValueError, TypeError)):
        localdates.local_day(bad, TZ)


URL, SHA = "https://example.invalid/agenda.pdf", "a" * 64
LATE = datetime(2026, 11, 10, 4, 38, tzinfo=timezone.utc)


def test_a_source_with_its_instant_shows_the_local_day():
    localdates.use({(URL, SHA): LATE})
    assert localdates.fetched({"url": URL, "sha256": SHA, "fetched_at": "2026-11-10"}) == "2026-11-09"


def test_a_source_without_an_instant_shows_its_utc_day_labelled():
    assert localdates.fetched({"url": URL, "sha256": SHA, "fetched_at": "2026-11-10"}) == "2026-11-10 (UTC day)"
    localdates.use({(URL, "b" * 64): LATE})   # another copy of the same URL is not this fetch
    assert localdates.fetched({"url": URL, "sha256": SHA, "fetched_at": "2026-11-10"}) == "2026-11-10 (UTC day)"


def test_a_row_of_another_fetch_is_not_used():
    """The stored day must be the instant's UTC day; else the row is another fetch and the day is labelled."""
    localdates.use({(URL, SHA): LATE})
    assert localdates.fetched({"url": URL, "sha256": SHA, "fetched_at": "2026-11-09"}) == "2026-11-09 (UTC day)"


def test_no_stored_day_stays_empty():
    assert localdates.fetched({"url": URL, "sha256": SHA, "fetched_at": None}) is None
    assert localdates.fetched(None) is None


def test_span_compares_local_days_only_when_every_source_has_its_instant():
    a = {"url": URL, "sha256": SHA, "fetched_at": "2026-11-10"}
    b = {"url": URL + "?2", "sha256": SHA, "fetched_at": "2026-11-08"}
    localdates.use({(URL, SHA): LATE, (URL + "?2", SHA): datetime(2026, 11, 8, 15, tzinfo=timezone.utc)})
    assert localdates.span([a, b]) == ("2026-11-08", "2026-11-09")
    localdates.use({(URL, SHA): LATE})
    assert localdates.span([a, b]) == ("2026-11-08 (UTC day)", "2026-11-10 (UTC day)")
    assert localdates.span([]) is None


def test_latest_is_a_plain_day_and_says_whether_it_is_a_utc_day():
    a = {"url": URL, "sha256": SHA, "fetched_at": "2026-11-10"}
    assert localdates.latest([a]) == ("2026-11-10", False)
    localdates.use({(URL, SHA): LATE})
    assert localdates.latest([a]) == ("2026-11-09", True)
    assert localdates.latest([]) is None


def test_load_reads_url_and_sha_from_the_manifests(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps([{"url": URL, "sha256": SHA, "first_fetched_at": "2026-11-10T04:38:00+00:00"}]))
    assert localdates.load([p]) == 1
    assert localdates.fetched({"url": URL, "sha256": SHA, "fetched_at": "2026-11-10"}) == "2026-11-09"
    p.write_text(json.dumps([{"url": URL, "sha256": SHA, "first_fetched_at": "2026-11-10T04:38:00"}]))
    with pytest.raises(localdates.LocalDatesError, match="no time zone"):
        localdates.load([p])
    with pytest.raises(localdates.LocalDatesError, match="no manifest"):
        localdates.load([tmp_path / "missing.json"])
    assert localdates.load(None) == 0


def test_a_meeting_date_is_a_civil_date_and_is_never_shifted():
    """A meeting on 2026-11-09 stays 2026-11-09, whatever the fetch instant; only the fetch day is converted."""
    facts = copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))
    m = facts["meetings"][0]
    m["date"] = "2026-11-09"
    src = next(s for s in facts["sources"] if s["id"] == m["source_id"])
    src["fetched_at"] = "2026-11-10"
    localdates.use({(src["url"], src["sha256"]): LATE})
    ctx = views.meeting(m["id"], facts)
    assert ctx["meeting"]["date"] == "2026-11-09" and ctx["label"].startswith("2026-11-09, ")
    assert ctx["doc"]["fetched"] == "2026-11-09"
    # and one at the start of a day in UTC stays that day too (no shift either way)
    m["date"] = "2026-11-10"
    assert views.meeting(m["id"], facts)["meeting"]["date"] == "2026-11-10"


@pytest.fixture(scope="module")
def late_site(tmp_path_factory):
    """The fixture site built with one manifest row: the first fixture source fetched at 22:38 CST, stored UTC."""
    tmp = tmp_path_factory.mktemp("local-dates")
    facts = json.loads(FIXTURE.read_text(encoding="utf-8"))
    src = facts["sources"][0]
    man = tmp / "manifest.json"
    man.write_text(json.dumps([{"url": src["url"], "sha256": src["sha256"],
                                "first_fetched_at": f"{src['fetched_at']}T04:38:00+00:00"}]))
    out = tmp / "site"
    build_mod.build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, fetch_manifests=[man])
    yield out, man, src, facts
    localdates.use({})


def test_the_built_meeting_page_shows_the_local_fetch_day_and_the_meeting_date_as_is(late_site):
    out, _, src, facts = late_site
    m = next(m for m in facts["meetings"] if m["source_id"] == src["id"])
    page = (out / "meetings" / f"{m['id']}.html").read_text(encoding="utf-8")
    local = localdates.local_day(f"{src['fetched_at']}T04:38:00+00:00")
    assert local != src["fetched_at"]
    assert f", fetched {local}." in page and not re.search(rf"fetched {src['fetched_at']}(?! \(UTC day\))", page)
    assert m["date"] in page
    # a fixture source with no manifest row still shows its stored day, labelled
    m2 = next(x for x in facts["meetings"] if x["source_id"] != src["id"])
    other = next(s for s in facts["sources"] if s["id"] == m2["source_id"])
    page2 = (out / "meetings" / f"{m2['id']}.html").read_text(encoding="utf-8")
    assert f", fetched {other['fetched_at']} (UTC day)." in page2


def test_site_check_passes_the_converted_build_and_fails_a_raw_utc_day(late_site, tmp_path):
    out, man, src, facts = late_site
    cfg = {**site_checks._site_cfg(), "fetch_manifests": [str(man)]}
    pages = {p.relative_to(out).as_posix(): None for p in out.rglob("*.html")}
    problems, note = site_checks.check_local_dates(out, pages, cfg, False, county=facts)
    assert problems == [], problems[:5]
    # the same page with the stored UTC day put back fails
    bad = tmp_path / "bad"
    bad.mkdir()
    local = localdates.local_day(f"{src['fetched_at']}T04:38:00+00:00")
    page = next(p for p in out.rglob("meetings/*.html") if f"fetched {local}." in p.read_text(encoding="utf-8"))
    (bad / "m.html").write_text(page.read_text(encoding="utf-8").replace(f"fetched {local}.",
                                                                       f"fetched {src['fetched_at']}."))
    problems, _ = site_checks.check_local_dates(bad, {"m.html": None}, cfg, False)
    assert problems and "the stored UTC day" in problems[0], problems


def _one_page(tmp_path, body):
    (tmp_path / "p.html").write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    return {"p.html": None}


URL2, URL3 = "https://example.invalid/older.pdf", "https://example.invalid/rpc.pdf"


def _cfg(tmp_path):
    man = tmp_path / "m.json"
    man.write_text(json.dumps([{"url": URL, "sha256": SHA, "first_fetched_at": "2026-11-10T04:38:00+00:00"},
                               # in a manifest, but not a source of the page's body: its day is no aggregate's
                               {"url": URL2, "sha256": SHA, "first_fetched_at": "2026-11-08T15:00:00+00:00"},
                               {"url": URL3, "sha256": SHA, "first_fetched_at": "2026-11-08T03:00:00+00:00"}]))
    return {"site_timezone": TZ, "fetch_manifests": [str(man)]}


# the page's body: one source fetched at 22:38 CST on 11-09 (stored 11-10), one meeting; the RPC: one source
COUNTY = {"sources": [{"url": URL, "sha256": SHA, "fetched_at": "2026-11-10"}], "meetings": [{"date": "2026-05-11"}]}
RPC = {"sources": [{"url": URL3, "sha256": SHA, "fetched_at": "2026-11-08"}]}   # 21:00 CST on 11-07


@pytest.mark.parametrize("body, ok", [
    (f'<a href="{URL}#page=2">p. 2, fetched 2026-11-09</a>', True),
    (f'<a href="{URL}#page=2">p. 2, fetched 2026-11-10</a>', False),           # the raw UTC day
    # labelled although the linked source has its instant for that UTC day: a lost conversion (dates/check-labelled-passes)
    (f'<a href="{URL}">PDF</a>, fetched 2026-11-10 (UTC day).', False),
    (f'<a href="{URL}">PDF</a>, fetched 2026-11-08 (UTC day).', True),          # labelled, not this row's UTC day
    ('<a href="https://example.invalid/other.pdf">PDF</a>, fetched 2026-11-08.', False),   # no instant, unlabelled
    ('<a href="https://example.invalid/other.pdf">PDF</a>, fetched 2026-11-08 (UTC day).', True),
    (f'<a href="{URL}">A</a> <details><p>Fetched 2026-11-09.</p></details>', True),
    ("<p>Minutes fetched on 2026-11-09.</p>", True),
    ("<p>Minutes fetched between 2026-11-09 and 2026-11-10.</p>", False),      # 11-10 is the stored UTC day
    # aggregates are tied to the page's own sources (dates/check-aggregate-loose)
    ("<p>Data as of 2026-11-09</p>", True),
    ("<p>Data as of 2026-11-08</p>", False),     # a manifest row's local day, but not this body's latest
    ("<p>Data as of 2026-11-10 (UTC day)</p>", False),   # the source has its instant: no label
    ("<p>Minutes fetched between 2026-11-08 and 2026-11-09.</p>", False),
    ("<p>3 documents collected (latest fetched 2026-11-07)</p>", True),     # the RPC's own latest, local
    ("<p>3 documents collected (latest fetched 2026-11-08)</p>", False),    # its stored UTC day
    ("<p>3 documents collected (latest fetched 2026-11-09)</p>", False),    # the county's day, not the RPC's
    # other words before a fetch day
    (f'<a href="{URL}">PDF</a>, collected 2026-11-10.', False),
    (f'<a href="{URL}">PDF</a>, added on 2026-11-09.', True),
    ("<p>Current: in the roll calls of the latest meeting collected, 2026-05-11.</p>", True),   # a meeting date
    ("<p>Current: in the roll calls of the latest meeting collected, 2026-05-10.</p>", False),
])
def test_site_check_rule(tmp_path, body, ok):
    problems, _ = site_checks.check_local_dates(tmp_path, _one_page(tmp_path, body), _cfg(tmp_path), False,
                                                county=COUNTY, rpc=RPC)
    assert (problems == []) is ok, problems


def test_site_check_ties_a_council_page_to_the_councils_sources(tmp_path):
    council = {"sources": [{"url": URL2, "sha256": SHA, "fetched_at": "2026-11-08"}], "meetings": []}
    (tmp_path / "city").mkdir()
    (tmp_path / "city" / "p.html").write_text("<p>Data as of 2026-11-08</p>", encoding="utf-8")
    (tmp_path / "p.html").write_text("<p>Data as of 2026-11-08</p>", encoding="utf-8")
    problems, _ = site_checks.check_local_dates(tmp_path, {"city/p.html": None, "p.html": None}, _cfg(tmp_path),
                                                False, county=COUNTY, councils_=[{"prefix": "city/", "facts": council}])
    assert len(problems) == 1 and problems[0].startswith("p.html: "), problems   # the county's latest is 11-09


def test_site_check_in_a_fixture_build_wants_every_day_labelled(tmp_path):
    cfg = _cfg(tmp_path)
    problems, _ = site_checks.check_local_dates(
        tmp_path, _one_page(tmp_path, f'<a href="{URL}">p. 1, fetched 2026-11-09</a>'), cfg, True)
    assert problems   # a fixture build reads no manifests: an unlabelled day has no instant behind it
