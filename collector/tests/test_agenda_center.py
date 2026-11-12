"""City Agenda Center source (M4 slice 1): config checks, listing parse, discovery and the polite fetch. No network."""
import io
import json
import urllib.error
from pathlib import Path

import pytest
import yaml

from collector import agenda_center as ac
from collector.city_run import cmd_fetch, new_log
from collector.fetch import FetchFailed, HostRefused, PoliteFetcher
from collector.store import Store

FIX = Path(__file__).parent / "fixtures" / "city"
CFG_PATH = ac.config_path("clarksville-tn")


@pytest.fixture(scope="module")
def cfg():
    return ac.load_config(CFG_PATH)


def raw_cfg() -> dict:
    return yaml.safe_load(CFG_PATH.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ config
def test_config_loads_and_is_locality_data(cfg):
    assert cfg.body == "Clarksville City Council"
    assert cfg.host == "www.clarksvilletn.gov"
    assert cfg.year_range() == range(2016, 2025)
    assert cfg.listing_url(2019).startswith("https://www.clarksvilletn.gov/AgendaCenter/Search/?term=&CIDs=3&")
    assert "startDate=01/01/2019&endDate=12/31/2019" in cfg.listing_url(2019)
    from collector.fetch import DENIED_HOSTS
    assert "cityofclarksville.com" in DENIED_HOSTS


def test_vote_labels_are_strings_not_yaml_booleans(cfg):
    # YAML reads a bare yes/no as true/false; the config quotes them and the loader rejects anything else
    assert cfg.vote_labels["YES"] == "yes" and cfg.vote_labels["NO"] == "no" and cfg.vote_labels["NAY"] == "no"
    bad = raw_cfg()
    bad["vote_labels"] = {"AYE": True}
    with pytest.raises(ac.AgendaCenterConfigError, match="vote_labels"):
        ac.parse_config(bad)


@pytest.mark.parametrize("key,value,match", [
    ("search_url", "http://www.clarksvilletn.gov/x?{cid}{year}", "https"),
    ("search_url", "https://cityofclarksville.com/x?{cid}{year}", "https on host"),
    ("search_url", "https://www.clarksvilletn.gov/AgendaCenter/Search/?CIDs={cid}", "{year}"),
    ("search_url", "https://www.clarksvilletn.gov/AgendaCenter/Search/?startDate={year}", "{cid}"),
    # config-validation/agenda-center-search-url-format: only {cid} and {year}, each bare; refused before any .format
    ("search_url", "https://www.clarksvilletn.gov/x?{cid}{year}{0}", "may name only"),
    ("search_url", "https://www.clarksvilletn.gov/x?{cid}{year}{host}", "may name only"),
    ("search_url", "https://www.clarksvilletn.gov/x?{cid.__class__}{year}", "may name only"),
    ("search_url", "https://www.clarksvilletn.gov/x?{cid}{year!r}", "may name only"),
    ("search_url", "https://www.clarksvilletn.gov/x?{cid:>99999}{year}", "may name only"),
    ("search_url", "https://www.clarksvilletn.gov/x?{cid}{year}{", "not a template"),
    ("years", [2024, 2016], "years"),
    ("kind_rules", [["formal", "x"]], "kind must be one of"),
    ("kind_rules", [["regular", "("]], "bad regex"),
    ("item_kinds", ["ORDINANCE (x)"], "item_kinds"),
    ("item_kinds", [], "item_kinds"),
    ("not_item_votes", "(", "bad regex"),
])
def test_config_rejects_bad_values(key, value, match):
    bad = raw_cfg()
    bad[key] = value
    with pytest.raises(ac.AgendaCenterConfigError, match=match):
        ac.parse_config(bad)


def test_search_url_literal_braces_are_text():
    good = raw_cfg()
    good["search_url"] = "https://www.clarksvilletn.gov/AgendaCenter/Search/?q={{x}}&CIDs={cid}&y={year}"
    assert ac.parse_config(good).listing_url(2019).endswith("?q={x}&CIDs=3&y=2019")


def test_config_missing_key_fails_loudly():
    bad = raw_cfg()
    del bad["body"]
    with pytest.raises(ac.AgendaCenterConfigError, match="missing key body"):
        ac.parse_config(bad)


@pytest.mark.parametrize("title,kind", [
    ("City Council Regular Session Agenda 12-5-19", "regular"),
    ("City Council Executive Session Agenda 12-30-19", "executive"),
    ("City Council Special Session Agenda 10-31-19", "special"),
    ("City Council Special Work Session Agenda - October 2, 2023", "work-session"),
    ("Oath of Office Special Session", "special"),
    ("Ethics Code Review Agenda - February 9, 2023", "committee"),
    ("Finance Committee Budget Review Mtg Notice", "committee"),
    ("Growth Plan Public Hearing", "public-hearing"),
    ("Legislative Agenda Reception - September 21, 2021", "other"),
])
def test_kind_from_title(cfg, title, kind):
    assert cfg.kind_of(title) == kind


# ------------------------------------------------------------------ listing
def test_parse_listing_rows_as_printed(cfg):
    rows, problems = ac.parse_listing((FIX / "search_2019_excerpt.html").read_text(encoding="utf-8"), cfg, 2019)
    assert problems == []
    assert [r["date"] for r in rows] == ["2019-12-30", "2019-12-05", "2019-10-31"]
    ex, reg, spe = rows
    assert ex == {"date": "2019-12-30", "title": "City Council Executive Session Agenda 12-30-19", "kind": "executive",
                  "agenda_id": "12302019-340",
                  "agenda_url": "https://www.clarksvilletn.gov/AgendaCenter/ViewFile/Agenda/_12302019-340",
                  "minutes_url": None, "has_previous_versions": False}
    assert reg["minutes_url"] == "https://www.clarksvilletn.gov/AgendaCenter/ViewFile/Minutes/_12052019-325"
    assert reg["has_previous_versions"] is True
    assert spe["title"] == "City Council Special Session Agenda 10-31-19 & Notice"     # entities unescaped


def test_listing_without_heading_but_with_rows_fails_loudly(cfg):
    page = (FIX / "search_2019_excerpt.html").read_text(encoding="utf-8").replace(">City Council</h2>", ">Other</h2>")
    with pytest.raises(ac.ListingError, match="heading"):
        ac.parse_listing(page, cfg, 2019)


def test_empty_year_has_no_rows(cfg):
    assert ac.parse_listing("<html><body>No agendas</body></html>", cfg, 2016) == ([], [])


def test_row_dated_outside_its_year_is_reported(cfg):
    rows, problems = ac.parse_listing((FIX / "search_2019_excerpt.html").read_text(encoding="utf-8"), cfg, 2020)
    assert len(rows) == 3 and len(problems) == 3 and "on the 2020 listing" in problems[0]["problem"]


class FakeFetcher:
    def __init__(self, pages, fail=()):
        self.pages, self.fail, self.calls, self.log = pages, set(fail), [], []

    def get(self, url):
        self.calls.append(url)
        if url in self.fail:
            raise FetchFailed(f"{url}: reset")
        if url not in self.pages:
            return 404, b"", {}
        body = self.pages[url]
        return 200, body, {"Content-Type": "application/pdf" if body.startswith(b"%PDF") else "text/html"}


def small_cfg(cfg, years=(2019, 2020)):
    return ac.AgendaCenterConfig(**{**cfg.__dict__, "years": years})


def test_discover_one_get_per_year_and_keeps_previous_rows_on_a_network_failure(cfg):
    c = small_cfg(cfg)
    page = (FIX / "search_2019_excerpt.html").read_bytes()
    f = FakeFetcher({c.listing_url(2019): page}, fail=[c.listing_url(2020)])
    prev = [{"date": "2020-01-02", "agenda_id": "01022020-1", "title": "kept"}]
    log = {}
    rows = ac.discover(f, c, log, previous=prev)
    assert f.calls == [c.listing_url(2019), c.listing_url(2020)]
    assert [r["date"] for r in rows] == ["2019-10-31", "2019-12-05", "2019-12-30", "2020-01-02"]
    assert log["listing_failures"][0]["year"] == 2020 and log["listing_failures"][0]["kept_previous_rows"] == 1


def test_discover_non_200_fails_loudly(cfg):
    c = small_cfg(cfg, (2019, 2019))
    with pytest.raises(ac.ListingError, match="HTTP 404"):
        ac.discover(FakeFetcher({}), c, {})


# ------------------------------------------------------------------ fetch step
def test_cmd_fetch_stores_minutes_and_keeps_going_past_a_bad_file(cfg, tmp_path):
    c = small_cfg(cfg, (2019, 2019))
    page = (FIX / "search_2019_excerpt.html").read_bytes()
    m1 = "https://www.clarksvilletn.gov/AgendaCenter/ViewFile/Minutes/_12052019-325"
    m2 = "https://www.clarksvilletn.gov/AgendaCenter/ViewFile/Minutes/_10312019-303"
    f = FakeFetcher({c.listing_url(2019): page, m1: b"%PDF-1.4 minutes", m2: b"<html>not a pdf</html>"})
    store = Store(manifest_path=tmp_path / "manifest.json", root=tmp_path / "store")
    log = new_log()
    rows = cmd_fetch(c, store, tmp_path / "listing.json", log, fetcher=f)
    assert len(rows) == 3
    assert json.loads((tmp_path / "listing.json").read_text())[0]["date"] == "2019-10-31"
    assert log["fetched"] == {"new": 1}
    assert [x["url"] for x in log["failures"]] == [m2]          # NotPdf logged, not stored
    entry = store.latest(m1)
    assert entry["kind"] == "minutes" and entry["meeting_date"] == "2019-12-05"
    assert not any(u.endswith("Agenda/_12052019-325") for u in f.calls)       # agendas only with --agendas


def test_cmd_fetch_stops_the_host_after_a_refusal(cfg, tmp_path):
    c = small_cfg(cfg, (2019, 2019))
    page = (FIX / "search_2019_excerpt.html").read_bytes()

    class Refusing(FakeFetcher):
        def get(self, url):
            if "ViewFile" in url:
                self.calls.append(url)
                raise HostRefused("www.clarksvilletn.gov: denied")
            return super().get(url)

    f = Refusing({c.listing_url(2019): page})
    log = new_log()
    cmd_fetch(c, Store(manifest_path=tmp_path / "m.json", root=tmp_path / "s"), tmp_path / "l.json", log,
              fetcher=f, agendas=True)
    assert len([u for u in f.calls if "ViewFile" in u]) == 1            # no second try after the refusal
    assert log["fetched"]["not_tried"] == 4


# ------------------------------------------------------------------ polite fetcher on the city host
class FakeResp(io.BytesIO):
    status = 200
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fetcher_with(responses):
    calls = []

    def opener(req, timeout):
        calls.append(req.full_url)
        r = responses[req.full_url].pop(0)
        if isinstance(r, Exception):
            raise r
        return FakeResp(r)

    f = PoliteFetcher(opener=opener, sleep=lambda s: None, clock=lambda: 0.0, proxy_failures=lambda: [])
    return f, calls


ROBOTS = b"User-agent: *\nDisallow: /Search\nCrawl-delay: 10\n"


def test_robots_crawl_delay_and_agenda_center_allowed():
    url = "https://www.clarksvilletn.gov/AgendaCenter/ViewFile/Minutes/_12052019-325"
    f, calls = fetcher_with({"https://www.clarksvilletn.gov/robots.txt": [ROBOTS], url: [b"%PDF"]})
    assert f.get(url)[0] == 200
    assert f.delay_for("www.clarksvilletn.gov") == 10.0
    assert calls[0].endswith("/robots.txt")


def test_connection_reset_is_retried_once_then_fails():
    url = "https://www.clarksvilletn.gov/AgendaCenter/Search/?CIDs=3"
    reset = urllib.error.URLError(ConnectionResetError(104, "Connection reset by peer"))
    f, calls = fetcher_with({"https://www.clarksvilletn.gov/robots.txt": [ROBOTS], url: [reset, b"<html>"]})
    assert f.get(url) == (200, b"<html>", {})
    assert [e["event"] for e in f.log].count("retry") == 1
    f2, _ = fetcher_with({"https://www.clarksvilletn.gov/robots.txt": [ROBOTS], url: [reset, reset]})
    with pytest.raises(FetchFailed, match="reset"):
        f2.get(url)


def test_reset_retry_waits_the_host_delay_first():
    # fetch/reset-retry: the retry is a new request on the host, so it waits the full crawl delay
    url = "https://www.clarksvilletn.gov/AgendaCenter/Search/?CIDs=3"
    reset = urllib.error.URLError(ConnectionResetError(104, "Connection reset by peer"))
    now, timeline = [0.0], []
    responses = {"https://www.clarksvilletn.gov/robots.txt": [ROBOTS], url: [reset, b"<html>"]}

    def opener(req, timeout):
        timeline.append(("get", req.full_url, now[0]))
        r = responses[req.full_url].pop(0)
        if isinstance(r, Exception):
            raise r
        return FakeResp(r)

    def sleep(s):
        timeline.append(("sleep", s, now[0]))
        now[0] += s

    f = PoliteFetcher(opener=opener, sleep=sleep, clock=lambda: now[0], proxy_failures=lambda: [])
    assert f.get(url)[0] == 200
    gets = [(u, t) for kind, u, t in timeline if kind == "get"]
    assert [u for u, _ in gets] == ["https://www.clarksvilletn.gov/robots.txt", url, url]
    assert gets[2][1] - gets[1][1] >= 10.0                      # the retry waited the Crawl-delay
    assert timeline[-2] == ("sleep", 10.0, gets[1][1])


def test_reset_retries_are_capped_per_host_per_run():
    urls = [f"https://www.clarksvilletn.gov/AgendaCenter/ViewFile/Minutes/_{n}" for n in range(5)]
    reset = urllib.error.URLError(ConnectionResetError(104, "Connection reset by peer"))
    f, calls = fetcher_with({"https://www.clarksvilletn.gov/robots.txt": [ROBOTS],
                             **{u: [reset, b"%PDF"] for u in urls}})
    from collector.fetch import RESET_RETRIES_PER_HOST
    assert RESET_RETRIES_PER_HOST == 3
    for u in urls[:3]:
        assert f.get(u)[0] == 200                               # retried once each
    for u in urls[3:]:
        with pytest.raises(FetchFailed, match="not retried: 3 resets"):
            f.get(u)
    assert [e["event"] for e in f.log].count("retry") == 3
    assert calls.count(urls[3]) == 1 and calls.count(urls[4]) == 1      # no second request after the cap


def test_cityofclarksville_com_is_never_requested():
    f, calls = fetcher_with({})
    with pytest.raises(HostRefused):
        f.get("https://www.cityofclarksville.com/AgendaCenter")
    assert calls == []
