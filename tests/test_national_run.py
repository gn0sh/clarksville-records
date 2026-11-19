"""Daylight Digest national collection run (collector/national/run.py; docs/architecture/daylight-national.md 3.7,
4.4.1, 4.5; ADR 0013 decision 6; task C3). Every request goes to the real PoliteFetcher with its network faked (no
real network; webapi.legistar.com is allowed only on the test fetcher, never in ALLOWED_HOSTS). Problem keys:
national-freshness/checked-at-is-first-fetch, national/tenant-caller-order, cache-confine/put-error-kind."""
import copy
import io
import json
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from collector import fetch
from collector.fetch import HostRefused, PoliteFetcher
from collector.national import legistar_upcoming as lu
from collector.national import run as nr
from sitegen import national as nat

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "national" / "legistar"
NOW = datetime(2026, 12, 1, 18, 0, tzinfo=timezone.utc)          # 10:00 in Oregon: today is 2026-12-01
HOST_OK = {"date": "2026-11-18", "link": "https://github.com/gn0sh/clarksville-records/pull/1"}


def body(n, client, items="withheld"):
    return {"gov": f"place-41{n:05d}", "also": [], "body_name": f"Example Council {n}", "state": "OR",
            "status": "covered", "official_url": f"https://{client}.legistar.com/Calendar.aspx",
            "checked": "2026-12-01", "checked_url": f"https://{client}.legistar.com/Calendar.aspx", "items": items,
            "platform": "legistar", "legistar": {"client": client, "body_id": 100 + n, "tz": "America/Los_Angeles"},
            "host_ok": HOST_OK}


SALEM = {"gov": "place-4164900", "also": [], "body_name": "Salem City Council", "state": "OR", "status": "covered",
         "official_url": "https://salem.legistar.com/Calendar.aspx", "checked": "2026-12-01",
         "checked_url": "https://salem.legistar.com/Calendar.aspx", "items": "shown", "platform": "legistar",
         "legistar": {"client": "salem", "body_id": 138, "tz": "America/Los_Angeles"}, "host_ok": HOST_OK}
CANT = {"gov": "place-4100001", "also": [], "body_name": "Example Cannot", "state": "OR", "status": "cant-cover",
        "official_url": "https://example.gov/", "checked": "2026-12-01", "reason": "blocks-readers",
        "reason_url": "https://example.gov/"}


def load(tmp_path, monkeypatch, *govs, reviewed=()):
    rows = tuple(nat.ShownReview(e["gov"], nat.norm_entry(e)) for e in reviewed)
    monkeypatch.setattr(nat, "SHOWN_REVIEWED", nat.SHOWN_REVIEWED + rows)
    p = tmp_path / "directory.yml"
    p.write_text(yaml.safe_dump({"schema": "daylight-directory/1", "govs": list(govs)}, sort_keys=False),
                 encoding="utf-8")
    return nat.load_directory(p, nat.load_labels()), p


def event(n, body_id, day, status="Draft"):
    return {"EventId": n, "EventBodyId": body_id, "EventDate": f"{day}T00:00:00", "EventTime": "6:00 PM",
            "EventAgendaStatusName": status, "EventAgendaFile": None, "EventInSiteURL": None,
            "EventAgendaLastPublishedUTC": None, "EventComment": None}


class Resp(io.BytesIO):
    status, headers = 200, {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(url, code, body=b""):
    return urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(body))


class Net:
    """The faked network under a real PoliteFetcher. `fail[client]` answers that client's events query with
    (code, body); `events[body_id]` is that body's events answer; `robots` the robots.txt answer."""

    def __init__(self, fail=None, events=None, robots=None, items=None):
        self.fail, self.events, self.robots, self.items = fail or {}, events or {}, robots, items or {}
        self.calls = []

    def __call__(self, req, timeout):
        url = req.full_url
        self.calls.append(url)
        u = urlsplit(url)
        if u.path == "/robots.txt":
            if self.robots is None:
                raise http_error(url, 404)
            if isinstance(self.robots, tuple):
                code, headers = self.robots
                raise urllib.error.HTTPError(url, code, "x", headers, io.BytesIO(b""))
            return Resp(self.robots.encode())
        parts = u.path.split("/")
        client = parts[2]
        if parts[3:] == ["events"]:
            if client in self.fail:
                code, payload = self.fail[client]
                raise http_error(url, code, payload)
            body_id = parse_qs(u.query)["$filter"][0].split()[2]
            return Resp(json.dumps(self.events.get(int(body_id), [])).encode())
        return Resp(json.dumps(self.items.get(parts[4], [])).encode())

    def event_calls(self):
        return [urlsplit(c).path.split("/")[2] for c in self.calls if urlsplit(c).path.endswith("/events")]


def fetcher(net, allowed=("webapi.legistar.com",)):
    return PoliteFetcher(opener=net, sleep=lambda s: None, proxy_failures=lambda: [], allowed_hosts=allowed)


def ticking(start=NOW, step=timedelta(minutes=1)):
    t = [start - step]

    def clock():
        t[0] += step
        return t[0]
    return clock


def test_webapi_stays_off_the_real_allowlist():
    assert not fetch.host_matches("webapi.legistar.com", fetch.ALLOWED_HOSTS)          # H1 adds it, not C3


# --- budget -------------------------------------------------------------------------------------------------------

def test_a_budget_of_10_reads_what_fits_and_records_budget_skipped_for_the_rest(tmp_path, monkeypatch):
    govs = [body(i, f"c{i:02d}") for i in range(1, 13)]                 # 12 bodies, 12 tenants, one request each
    d, _ = load(tmp_path, monkeypatch, *govs)
    net = Net()
    r = nr.run(d, fetcher(net), 10, NOW)
    assert len(net.calls) == 10                                        # robots.txt + 9 events queries, never more
    oks = [g for g, o in r.outcomes.items() if o == "ok"]
    skipped = [g for g, o in r.outcomes.items() if o == "budget-skipped"]
    assert (len(oks), len(skipped)) == (9, 3)
    for g in skipped:
        assert r.health[g] == {"last_attempt_at": None, "last_ok_at": None, "consecutive_failures": 0,
                               "last_error": "budget-skipped", "failure_streak": None}
        assert g not in r.feeds
    assert all(r.health[g]["last_error"] is None for g in oks)


def test_the_tenant_cap_skips_only_that_tenant(tmp_path, monkeypatch):
    govs = [body(1, "aa"), body(2, "aa"), body(3, "aa"), body(4, "bb")]
    d, _ = load(tmp_path, monkeypatch, *govs)
    net = Net()
    r = nr.run(d, fetcher(net), 100, NOW, tenant_budget=2)
    assert [r.outcomes[g["gov"]] for g in govs] == ["ok", "ok", "budget-skipped", "ok"]
    assert net.event_calls() == ["aa", "aa", "bb"]


def test_a_cap_hit_mid_read_is_budget_skipped_and_stops_the_host(tmp_path, monkeypatch):
    govs = [body(1, "aa"), body(2, "bb")]
    d, _ = load(tmp_path, monkeypatch, *govs)
    r = nr.run(d, fetcher(Net()), 1, NOW)                              # robots.txt uses the only request
    assert set(r.outcomes.values()) == {"budget-skipped"}


def test_order_soon_not_final_first_then_not_read_longest(tmp_path, monkeypatch):
    a, b, c, e = body(1, "aa"), body(2, "bb"), body(3, "cc"), body(4, "dd")
    d, _ = load(tmp_path, monkeypatch, a, b, c, e)
    prev_health = {a["gov"]: {"last_ok_at": "2026-11-30T10:00:00Z"}, b["gov"]: {"last_ok_at": "2026-11-29T10:00:00Z"},
                   c["gov"]: {"last_ok_at": "2026-12-01T09:00:00Z"}}
    soon = {"meetings": [{"date": "2026-12-05", "agenda": {"state": "not-final"}}]}
    later = {"meetings": [{"date": "2026-12-20", "agenda": {"state": "not-final"}}]}
    order = nr.budget_order([a, b, c, e], {c["gov"]: soon, b["gov"]: later}, prev_health, NOW)
    assert [x["gov"] for x in order] == [c["gov"], e["gov"], b["gov"], a["gov"]]   # e never read: before b and a
    net = Net()
    nr.run(d, fetcher(net), 100, NOW, previous_feeds={c["gov"]: soon}, previous_health=prev_health)
    assert net.event_calls() == ["cc", "dd", "bb", "aa"]


# --- host and tenant stops ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("code, payload, first", [(429, b"", "rate-limited"), (403, b"<html>no</html>", "host-stopped")])
def test_a_host_stop_marks_the_remaining_bodies_stale_never_cant_cover(tmp_path, monkeypatch, code, payload, first):
    govs = [body(1, "aa"), body(2, "bb"), body(3, "cc"), body(4, "dd")]
    d, path = load(tmp_path, monkeypatch, *govs)
    before = path.read_bytes()
    good = nr.run(d, fetcher(Net()), 100, NOW)                        # an earlier good run: every body has a feed
    later = NOW + timedelta(hours=12)
    health = {g: dict(h) for g, h in good.health.items()}
    health[govs[0]["gov"]]["last_ok_at"] = "2026-11-01T00:00:00Z"     # read first next time
    health[govs[1]["gov"]]["last_ok_at"] = "2026-11-02T00:00:00Z"
    net = Net(fail={"bb": (code, payload)})
    r = nr.run(d, fetcher(net), 100, later, previous_feeds=good.feeds, previous_health=health)
    assert net.event_calls() == ["aa", "bb"]                          # nothing asked after the stop
    out = [r.outcomes[g["gov"]] for g in govs]
    assert out == ["ok", first, "host-stopped", "host-stopped"]
    for g in govs[2:]:
        gid = g["gov"]
        assert r.feeds[gid] == good.feeds[gid]                         # not read: the feed is unchanged
        assert r.health[gid]["last_ok_at"] == good.health[gid]["last_ok_at"]
        assert r.health[gid]["last_attempt_at"] == good.health[gid]["last_attempt_at"]
        assert r.health[gid]["consecutive_failures"] == 0             # a host stop is not the body's failure
        assert r.health[gid]["failure_streak"] is None
    stopped = r.feeds[govs[1]["gov"]]                                 # read and failed: new checked_at, old last_ok_at
    assert stopped["checked_at"] == nr._instant(later)
    assert stopped["last_ok_at"] == nr._instant(NOW)
    assert "cant-cover" not in json.dumps([r.health, r.proposals, r.feeds])
    assert path.read_bytes() == before                                 # no curated status written


def test_a_tenant_block_stops_only_that_tenant_and_the_citys_own_host(tmp_path, monkeypatch):
    """national/tenant-caller-order: TenantBlocked is caught before HostBlocked, so the host's other tenants go on."""
    govs = [body(1, "salem"), body(2, "salem"), body(3, "other")]
    d, _ = load(tmp_path, monkeypatch, *govs)
    net = Net(fail={"salem": (403, b'{"Message":"Agency not found"}')})
    pf = fetcher(net, allowed=("webapi.legistar.com", "salem.legistar.com", "other.legistar.com"))
    r = nr.run(d, pf, 100, NOW)
    assert [r.outcomes[g["gov"]] for g in govs] == ["tenant-blocked", "tenant-blocked", "ok"]
    assert net.event_calls() == ["salem", "other"]                    # the second salem body sent nothing
    assert r.health[govs[1]["gov"]]["last_attempt_at"] is None
    with pytest.raises(HostRefused):
        pf.check_host("salem.legistar.com")                           # the city's other Legistar host, for the run
    pf.check_host("other.legistar.com")


def test_two_tenants_blocked_is_a_host_stop(tmp_path, monkeypatch):
    govs = [body(1, "aa"), body(2, "bb"), body(3, "cc")]
    d, _ = load(tmp_path, monkeypatch, *govs)
    j = b'{"Message":"no"}'
    r = nr.run(d, fetcher(Net(fail={"aa": (403, j), "bb": (403, j)})), 100, NOW)
    assert [r.outcomes[g["gov"]] for g in govs] == ["tenant-blocked", "host-stopped", "host-stopped"]


def test_robots_unreadable_is_a_host_stop_not_robots(tmp_path, monkeypatch):
    govs = [body(1, "aa"), body(2, "bb")]
    d, _ = load(tmp_path, monkeypatch, *govs)
    net = Net(robots=(302, {"Location": "https://elsewhere.example/robots.txt"}))
    r = nr.run(d, fetcher(net), 100, NOW)
    assert set(r.outcomes.values()) == {"host-stopped"}
    assert net.event_calls() == []


def test_robots_disallowing_one_tenant_is_robots_for_it_only(tmp_path, monkeypatch):
    govs = [body(1, "aa"), body(2, "bb")]
    d, _ = load(tmp_path, monkeypatch, *govs)
    r = nr.run(d, fetcher(Net(robots="User-agent: *\nDisallow: /v1/aa/\n")), 100, NOW)
    assert [r.outcomes[g["gov"]] for g in govs] == ["robots", "ok"]


# --- one body never fails the run ---------------------------------------------------------------------------------

def test_a_cache_put_error_is_one_bodys_collector_error(tmp_path, monkeypatch):
    """cache-confine/put-error-kind: C2's bare ValueError from _cache_put stops that body only."""
    fx = json.loads((FIXTURES / "legistar-salem.json").read_text(encoding="utf-8"))
    other = body(2, "bb")
    d, _ = load(tmp_path, monkeypatch, SALEM, other, reviewed=(SALEM,))

    def refuse(*a, **k):
        raise ValueError("cache folder is not a real folder in the cache root (cache-confine)")
    monkeypatch.setattr(lu, "_cache_put", refuse)
    net = Net(events={138: fx["events"]["138"]}, items=fx["eventitems"])
    r = nr.run(d, fetcher(net), 100, NOW, cache_root=tmp_path / "cache",
               previous_health={other["gov"]: {"last_ok_at": "2026-12-01T00:00:00Z"}})
    assert r.outcomes == {SALEM["gov"]: "collector-error", other["gov"]: "ok"}
    assert SALEM["gov"] not in r.feeds and r.health[SALEM["gov"]]["last_error"] == "collector-error"


@pytest.mark.parametrize("code, kind", [(404, "not-enabled-suspected"), (401, "token-suspected"),
                                        (500, "server-error")])
def test_read_errors_are_recorded_per_body(tmp_path, monkeypatch, code, kind):
    govs = [body(1, "aa"), body(2, "bb")]
    d, _ = load(tmp_path, monkeypatch, *govs)
    r = nr.run(d, fetcher(Net(fail={"aa": (code, b"")})), 100, NOW)
    assert [r.outcomes[g["gov"]] for g in govs] == [kind, "ok"]
    assert r.health[govs[0]["gov"]]["last_error"] == kind


def test_an_unforeseen_exception_is_collector_error_and_the_run_goes_on(tmp_path, monkeypatch):
    govs = [body(1, "aa"), body(2, "bb")]
    d, _ = load(tmp_path, monkeypatch, *govs)
    real = lu.read_body

    def flaky(entry, *a, **k):
        if entry["gov"] == govs[0]["gov"]:
            raise RuntimeError("SENTINEL-ITEM-TEXT")
        return real(entry, *a, **k)
    monkeypatch.setattr(lu, "read_body", flaky)
    r = nr.run(d, fetcher(Net()), 100, NOW)
    assert [r.outcomes[g["gov"]] for g in govs] == ["collector-error", "ok"]
    assert "SENTINEL" not in json.dumps([r.health, r.proposals])       # never text from an error


def test_health_values_are_fixed_kinds_only():
    assert set(nr.STATUS_REASON) <= set(nr.LAST_ERRORS)
    assert set(nr.STATUS_REASON.values()) <= set(nat.REASONS)


# --- freshness: the run's stamp, not a document's first fetch -----------------------------------------------------

def test_each_body_is_stamped_when_it_is_checked(tmp_path, monkeypatch):
    """national-freshness/checked-at-is-first-fetch."""
    govs = [body(1, "aa"), body(2, "bb")]
    d, _ = load(tmp_path, monkeypatch, *govs)
    r = nr.run(d, fetcher(Net()), 100, NOW, clock=ticking())
    stamps = [nr._instant(NOW), nr._instant(NOW + timedelta(minutes=1))]
    for g, s in zip(govs, stamps):
        f, h = r.feeds[g["gov"]], r.health[g["gov"]]
        assert f["checked_at"] == f["last_ok_at"] == h["last_attempt_at"] == h["last_ok_at"] == s
    later = NOW + timedelta(hours=12)
    r2 = nr.run(d, fetcher(Net(fail={"aa": (500, b"")})), 100, later, previous_feeds=r.feeds,
                previous_health=r.health, clock=ticking(later))
    f = r2.feeds[govs[0]["gov"]]
    assert (f["checked_at"], f["last_ok_at"]) == (nr._instant(later), stamps[0])
    assert r2.health[govs[0]["gov"]] == {"last_attempt_at": nr._instant(later), "last_ok_at": stamps[0],
                                         "consecutive_failures": 1, "last_error": "server-error",
                                         "failure_streak": {"kind": "server-error", "count": 1}}


def test_a_kept_feed_is_rebound_to_its_entry_as_it_is_now(tmp_path, monkeypatch):
    """A body that was shown and is now withheld keeps no item text in its kept feed (11.1 row 16)."""
    fx = json.loads((FIXTURES / "legistar-salem.json").read_text(encoding="utf-8"))
    d, _ = load(tmp_path, monkeypatch, SALEM, reviewed=(SALEM,))
    net = Net(events={138: fx["events"]["138"]}, items=fx["eventitems"])
    good = nr.run(d, fetcher(net), 100, NOW)
    assert "SENTINEL-ITEM-TEXT" in json.dumps(good.feeds)
    withheld = dict(copy.deepcopy(SALEM), items="withheld")
    d2, _ = load(tmp_path, monkeypatch, withheld)
    r = nr.run(d2, fetcher(Net(fail={"salem": (500, b"")})), 100, NOW, previous_feeds=good.feeds)
    assert r.outcomes[SALEM["gov"]] == "server-error"
    assert "SENTINEL" not in json.dumps(r.feeds) and r.feeds[SALEM["gov"]]["review"] is None


# --- ids, proposals, files ----------------------------------------------------------------------------------------

def test_ids_are_checked_before_they_become_paths(tmp_path, monkeypatch):
    good = body(1, "aa")
    bad = dict(body(2, "bb"), gov="../../etc")
    d = nat.Directory(govs=(good, bad, CANT))
    r = nr.run(d, fetcher(Net()), 100, NOW)
    assert list(r.outcomes) == [good["gov"]]                           # the bad id and the cant-cover entry: no read
    root = tmp_path / "national"
    (root / "bodies").mkdir(parents=True)
    (root / "bodies" / "evil.json").write_text("{}", encoding="utf-8")
    (root / "health.json").write_text(json.dumps({"../x": {}, good["gov"]: {"last_ok_at": "2026-11-01T00:00:00Z"}}),
                                      encoding="utf-8")
    feeds, health, _ = nr.read_previous(root)
    assert feeds == {} and list(health) == [good["gov"]]
    nr.write_outputs(root, r)
    assert sorted(p.name for p in (root / "bodies").iterdir()) == [f"{good['gov']}.json"]


def test_status_proposal_after_repeated_failures_merged_and_cleared_on_success(tmp_path, monkeypatch):
    g = body(1, "aa")
    d, path = load(tmp_path, monkeypatch, g)
    before = path.read_bytes()
    feeds, health, proposals = {}, {}, []
    for i in range(4):
        t = NOW + timedelta(hours=12 * i)
        r = nr.run(d, fetcher(Net(fail={"aa": (404, b"")})), 100, t, previous_feeds=feeds, previous_health=health,
                   previous_proposals=proposals)
        feeds, health, proposals = r.feeds, r.health, r.proposals
        assert len(proposals) == (1 if i >= 2 else 0)
    p = proposals[0]
    assert (p["body"], p["kind"], p["observed"], p["count"]) == (g["gov"], "status", "api-not-enabled", 2)
    assert p["first_seen"] == nr._instant(NOW + timedelta(hours=24))
    assert urlsplit(p["evidence_url"]).hostname == "webapi.legistar.com"
    assert health[g["gov"]]["consecutive_failures"] == 4
    r = nr.run(d, fetcher(Net()), 100, NOW + timedelta(days=3), previous_feeds=feeds, previous_health=health,
               previous_proposals=proposals)
    assert r.proposals == [] and r.health[g["gov"]]["consecutive_failures"] == 0
    assert path.read_bytes() == before


def test_agenda_status_proposals_merge_across_runs(tmp_path, monkeypatch):
    g = body(1, "aa")
    d, _ = load(tmp_path, monkeypatch, g)
    ev = {101: [event(5001, 101, "2026-12-03", "Pending Clerk Review")]}
    r1 = nr.run(d, fetcher(Net(events=ev)), 100, NOW)
    r2 = nr.run(d, fetcher(Net(events=ev)), 100, NOW + timedelta(hours=12), previous_proposals=r1.proposals)
    assert [(p["kind"], p["observed"], p["count"], p["first_seen"]) for p in r2.proposals] == [
        ("agenda-status-name", "Pending Clerk Review", 2, nr._instant(NOW))]
    keep = nr.merge_proposals(r2.proposals + [{"body": "../x", "kind": "status"}], [], set(), {})
    assert keep == []                                                   # a body no longer covered keeps none


def test_collect_prunes_the_cache_first_and_writes_only_data(tmp_path, monkeypatch):
    g = body(1, "aa")
    d, path = load(tmp_path, monkeypatch, g)
    before = path.read_bytes()
    root = tmp_path / "data" / "national"
    stale = root / "cache" / g["gov"]                                  # a withheld body's old cache
    stale.mkdir(parents=True)
    (stale / "1.json").write_text("SENTINEL-ITEM-TEXT", encoding="utf-8")
    r = nr.collect(root, d, fetcher(Net()), 0, NOW)                    # budget 0: nothing is read, still pruned
    assert r.outcomes == {g["gov"]: "budget-skipped"}
    assert not stale.exists()
    assert json.loads((root / "health.json").read_text())[g["gov"]]["last_error"] == "budget-skipped"
    assert json.loads((root / "proposals.json").read_text()) == []
    r = nr.collect(root, d, fetcher(Net()), 100, NOW)
    written = json.loads((root / "bodies" / f"{g['gov']}.json").read_text())
    assert "full_url" not in written["body"]                           # 3.7: "3.5 minus full_url"
    assert written == nr.body_file(r.feeds[g["gov"]]) and written["checked_at"] == nr._instant(NOW)
    r = nr.collect(root, d, fetcher(Net(fail={"aa": (500, b"")})), 100, NOW + timedelta(hours=1))
    assert r.feeds[g["gov"]]["body"]["full_url"] is None              # the kept feed binds again without it
    assert sorted(p.name for p in root.iterdir()) == ["bodies", "cache", "health.json", "proposals.json"]
    assert path.read_bytes() == before


def test_a_symlinked_data_root_is_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(ValueError):
        nr.write_outputs(link, nr.RunResult({}, {}, [], {}))
    assert list(real.iterdir()) == []


# --- C3 review fixes ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("link", ["root", "bodies", "cache"])
def test_collect_refuses_a_symlinked_data_tree_before_reading_anything(tmp_path, monkeypatch, link):
    """national-confine/data-root-symlink-late: refused before read_previous, prune or any request."""
    g = body(1, "aa")
    d, _ = load(tmp_path, monkeypatch, g)
    real = tmp_path / "real"
    (real / "cache" / "place-4199999").mkdir(parents=True)
    (real / "cache" / "place-4199999" / "1.json").write_text("x", encoding="utf-8")
    (real / "health.json").write_text("{}", encoding="utf-8")
    snapshot = sorted((p.relative_to(real), p.read_bytes() if p.is_file() else None) for p in real.rglob("*"))
    root = tmp_path / "data" / "national"
    if link == "root":
        root.parent.mkdir(parents=True)
        root.symlink_to(real)
    else:
        root.mkdir(parents=True)
        (root / link).symlink_to(real)
    net = Net()
    with pytest.raises(ValueError):
        nr.collect(root, d, fetcher(net), 100, NOW)
    assert net.calls == []
    assert sorted((p.relative_to(real), p.read_bytes() if p.is_file() else None) for p in real.rglob("*")) == snapshot


def test_a_status_proposal_needs_three_failures_of_the_same_kind(tmp_path, monkeypatch):
    """national-proposal/streak-not-per-kind: mixed kinds never add up; host stops and budget skips neither count
    nor break the streak."""
    g, h = body(1, "aa"), body(2, "bb")
    d, _ = load(tmp_path, monkeypatch, g, h)
    feeds, health, proposals = {}, {}, []
    history = [{"aa": (500, b"")}, {"aa": (404, b"")}, {"aa": (401, b"")}, {"aa": (404, b"")},
               {"aa": (404, b"")}, "host-stop", {"aa": (404, b"")}]
    seen = []
    for i, fail in enumerate(history):
        t = NOW + timedelta(hours=12 * i)
        health = {k: dict(v, last_ok_at=None) if k == g["gov"] else dict(v, last_ok_at="2026-12-09T00:00:00Z")
                  for k, v in health.items()}                         # aa read first every run
        net = Net(fail={"aa": (429, b"")}) if fail == "host-stop" else Net(fail=fail)
        r = nr.run(d, fetcher(net), 100, t, previous_feeds=feeds, previous_health=health,
                   previous_proposals=proposals)
        feeds, health, proposals = r.feeds, r.health, r.proposals
        seen.append((r.outcomes[g["gov"]], health[g["gov"]]["failure_streak"], len(proposals)))
    assert [s[2] for s in seen] == [0, 0, 0, 0, 0, 0, 1]
    assert seen[5][0] == "rate-limited" and seen[5][1] == {"kind": "not-enabled-suspected", "count": 2}
    assert seen[6][1] == {"kind": "not-enabled-suspected", "count": 3}
    assert health[g["gov"]]["consecutive_failures"] == 6               # the rate-limited run is not counted
    assert health[h["gov"]]["consecutive_failures"] == 0


@pytest.mark.parametrize("robots", [(503, {}), (500, {})])
def test_robots_server_error_is_a_host_stop_and_never_proposes_cant_cover(tmp_path, monkeypatch, robots):
    """national-stop/robots-5xx-not-host-stop."""
    govs = [body(1, "aa"), body(2, "bb")]
    d, _ = load(tmp_path, monkeypatch, *govs)
    feeds, health, proposals = {}, {}, []
    for i in range(4):
        net = Net(robots=robots)
        pf = fetcher(net)
        r = nr.run(d, pf, 100, NOW + timedelta(hours=12 * i), previous_feeds=feeds, previous_health=health,
                   previous_proposals=proposals)
        feeds, health, proposals = r.feeds, r.health, r.proposals
        assert set(r.outcomes.values()) == {"host-stopped"} and net.event_calls() == []
        assert pf.robots_unreadable("webapi.legistar.com") == f"HTTP {robots[0]}"
    assert proposals == []


def test_robots_unreadable_is_none_for_a_robots_file_that_was_read():
    pf = fetcher(Net(robots="User-agent: *\nDisallow: /v1/aa/\n"))
    pf.robots("webapi.legistar.com")
    assert pf.robots_unreadable("webapi.legistar.com") is None
    assert fetcher(Net()).robots_unreadable("webapi.legistar.com") is None   # not asked yet


def test_an_exception_in_a_bodys_bookkeeping_is_its_collector_error(tmp_path, monkeypatch):
    """national-run/raise-outside-try."""
    govs = [body(1, "aa"), body(2, "bb")]
    d, _ = load(tmp_path, monkeypatch, *govs)
    real = nr._kept_feed

    def broken(previous, entry, stamp):
        if entry["gov"] == govs[0]["gov"]:
            raise KeyError("boom")
        return real(previous, entry, stamp)
    monkeypatch.setattr(nr, "_kept_feed", broken)
    r = nr.run(d, fetcher(Net(fail={"aa": (500, b"")})), 100, NOW, previous_health={govs[0]["gov"]: {"x": 1}})
    assert [r.outcomes[g["gov"]] for g in govs] == ["collector-error", "ok"]
    assert r.health[govs[0]["gov"]]["last_error"] == "collector-error"

    monkeypatch.setattr(nr, "budget_order", lambda *a: 1 / 0)          # the order itself failing: id order
    r = nr.run(d, fetcher(Net()), 100, NOW)
    assert set(r.outcomes.values()) == {"ok"}


def test_previous_proposals_are_rechecked_on_read_back(tmp_path, monkeypatch):
    """national-proposal/previous-text-unchecked."""
    g = body(1, "aa")
    d, _ = load(tmp_path, monkeypatch, g)
    base = {"body": g["gov"], "kind": "agenda-status-name", "first_seen": "2026-11-01T00:00:00Z", "count": 1}
    ok_url = "https://aa.legistar.com/MeetingDetail.aspx?ID=1"
    previous = [
        dict(base, observed="Pending Clerk Review", evidence_url=ok_url),                       # kept
        dict(base, observed="<script>x</script>", evidence_url=ok_url),                         # odd text
        dict(base, observed="Pending Two", evidence_url="https://evil.example/x"),              # other host
        dict(base, observed="Pending Three", evidence_url="https://bb.legistar.com/x"),         # another client
        dict(base, observed="Pending Four", evidence_url="javascript:alert(1)"),
        dict(base, kind="status", observed="SENTINEL", evidence_url=ok_url),                    # not a reason we make
        dict(base, kind="status", observed="api-not-enabled",
             evidence_url="https://webapi.legistar.com/v1/aa/events"),                          # kept
    ]
    r = nr.run(d, fetcher(Net(fail={"aa": (500, b"")})), 100, NOW, previous_proposals=previous)
    assert [(p["kind"], p["observed"]) for p in r.proposals] == [("agenda-status-name", "Pending Clerk Review"),
                                                                ("status", "api-not-enabled")]


# --- D3: no request without Brian's OK for the host (R5, finding 7, national/r5-not-enforced) ----------------------

class Spy:
    """A fetcher that records every attribute read or set (any `get`, `limit_hosts`, `extra_denied`, ...)."""

    def __init__(self):
        object.__setattr__(self, "touched", [])

    def __getattr__(self, name):
        self.touched.append(name)
        return lambda *a, **k: None

    def __setattr__(self, name, value):
        self.touched.append(name)


def without_host_ok(entry, **host_ok):
    e = copy.deepcopy(entry)
    if host_ok:
        e["host_ok"] = host_ok
    else:
        e.pop("host_ok")
    return e


BAD_HOST_OK = [
    ("missing", without_host_ok(SALEM)),
    ("no-date", without_host_ok(SALEM, link=HOST_OK["link"])),
    ("bad-date", without_host_ok(SALEM, date="soon", link=HOST_OK["link"])),
    ("http-link", without_host_ok(SALEM, date=HOST_OK["date"], link="http://github.com/x")),
    ("extra-key", without_host_ok(SALEM, date=HOST_OK["date"], link=HOST_OK["link"], who="Brian")),
    ("not-a-mapping", dict(SALEM, host_ok="yes")),
    ("cant-cover-platform", dict(CANT, platform="legistar")),       # not read by run(), still refused
]


@pytest.mark.parametrize("name,bad", BAD_HOST_OK, ids=[b[0] for b in BAD_HOST_OK])
def test_run_refuses_a_hand_built_directory_without_host_ok_before_any_request(tmp_path, name, bad):
    """A Directory built without the loader: one entry lacking a valid host_ok refuses the whole run, and the
    fetcher is never touched (no get, no limit_hosts) and the cache is not pruned."""
    cache = tmp_path / "cache"
    (cache / "place-4199999").mkdir(parents=True)                       # a folder prune_cache would delete
    d = nat.Directory(govs=(body(1, "aa"), bad), alias={})
    spy = Spy()
    with pytest.raises(nr.HostNotApproved, match=r"host_ok \(Brian's OK, R5\)") as exc:
        nr.run(d, spy, 100, NOW, cache_root=cache)
    assert bad["gov"] in str(exc.value)
    assert spy.touched == []
    assert (cache / "place-4199999").is_dir()


def test_run_refusal_sends_nothing_on_a_real_fetcher():
    net = Net()
    with pytest.raises(nr.HostNotApproved):
        nr.run(nat.Directory(govs=(without_host_ok(SALEM),), alias={}), fetcher(net), 100, NOW)
    assert net.calls == []


def test_collect_refuses_without_host_ok_and_writes_nothing(tmp_path):
    root = tmp_path / "national"
    spy = Spy()
    with pytest.raises(nr.HostNotApproved):
        nr.collect(root, nat.Directory(govs=(body(1, "aa"), without_host_ok(SALEM)), alias={}), spy, 100, NOW)
    assert spy.touched == [] and not root.exists()
    root.mkdir()
    (root / "health.json").write_text("{}\n", encoding="utf-8")         # a previous run's outputs stay as they were
    with pytest.raises(nr.HostNotApproved):
        nr.collect(root, nat.Directory(govs=(without_host_ok(SALEM),), alias={}), spy, 100, NOW)
    assert sorted(p.name for p in root.rglob("*")) == ["health.json"]
    assert (root / "health.json").read_text(encoding="utf-8") == "{}\n"


def test_daylight_and_no_platform_entries_need_no_host_ok(tmp_path):
    """The check is for third-party hosts only: a directory of daylight and cant-cover entries runs (and reads
    nothing, there being no Legistar entry)."""
    daylight = {"gov": "place-4715160", "also": [], "status": "covered", "platform": "daylight",
                "daylight": {"body": "city", "full_url": "city/"}}
    net = Net()
    r = nr.run(nat.Directory(govs=(daylight, CANT), alias={}), fetcher(net), 100, NOW)
    assert r.outcomes == {}
    assert net.calls == []


def test_read_body_refuses_an_entry_without_host_ok():
    net = Net()
    with pytest.raises(ValueError, match="host_ok"):
        lu.read_body(without_host_ok(SALEM), fetcher(net), NOW)
    assert net.calls == []


# --- collector-input/json-depth-recursion (security S2a finding 2; architecture 4.4.3 sites 5 and 6) ---------------

NESTED = [b"[" * 60000, b'{"a":' * 500 + b"1" + b"}" * 500]


@pytest.mark.parametrize("raw", NESTED, ids=["list", "object"])
def test_nested_previous_files_are_left_out_and_collect_completes(tmp_path, monkeypatch, raw):
    """collector-input/json-depth-recursion (4.4.3 site 5): a nested health.json used to abort collect(); nested
    health, proposals and body files are unreadable (left out), and the run writes its outputs."""
    g = body(1, "aa")
    d, _ = load(tmp_path, monkeypatch, g)
    root = tmp_path / "data" / "national"
    (root / "bodies").mkdir(parents=True)
    for p in (root / "health.json", root / "proposals.json", root / "bodies" / f"{g['gov']}.json"):
        p.write_bytes(raw)
    assert nr.read_previous(root) == ({}, {}, [])
    r = nr.collect(root, d, fetcher(Net()), 100, NOW)
    assert r.outcomes == {g["gov"]: "ok"}
    assert json.loads((root / "health.json").read_text())[g["gov"]]["last_error"] is None
    assert json.loads((root / "proposals.json").read_text()) == []
    assert json.loads((root / "bodies" / f"{g['gov']}.json").read_text())["body"]["id"] == g["gov"]


def _deep(levels):
    x = []
    for _ in range(levels):
        x = [x]
    return x


def test_a_deeply_nested_previous_feed_is_no_kept_feed_and_the_body_keeps_its_outcome(tmp_path, monkeypatch):
    """collector-input/json-depth-recursion (4.4.3 site 6): a previous feed passed in (not read through parse_json)
    whose deepcopy raises RecursionError gives no kept feed; the body's outcome stays server-error, not
    collector-error."""
    g = body(1, "aa")
    d, _ = load(tmp_path, monkeypatch, g)
    deep = {"schema": "daylight-upcoming/1", "body": {"id": g["gov"]}, "meetings": _deep(5000)}
    assert nr._kept_feed(deep, g, nr._instant(NOW)) is None
    r = nr.run(d, fetcher(Net(fail={"aa": (500, b"")})), 100, NOW, previous_feeds={g["gov"]: deep})
    assert r.outcomes[g["gov"]] == "server-error" and g["gov"] not in r.feeds


# --- cache-confine/prune-fail-open (security S2a finding 5) --------------------------------------------------------

@pytest.mark.parametrize("exc", [OSError("disk"), ValueError("symlinked root"), PermissionError("no")])
def test_a_prune_failure_fails_the_run_before_any_request_or_write(tmp_path, monkeypatch, exc):
    """cache-confine/prune-fail-open: a prune that fails used to leave the run going uncached, so a now-withheld
    body's cached item text stayed on disk and was pushed. Now the run raises: no request, nothing written."""
    g = body(1, "aa")
    d, _ = load(tmp_path, monkeypatch, g)

    def broken(directory, cache_root):
        raise exc
    monkeypatch.setattr(lu, "prune_cache", broken)
    net = Net()
    root = tmp_path / "data" / "national"
    with pytest.raises(type(exc)):
        nr.collect(root, d, fetcher(net), 100, NOW)
    assert net.calls == [] and not (root / "health.json").exists() and not (root / "bodies").exists()
    with pytest.raises(type(exc)):
        nr.run(d, fetcher(net), 100, NOW, cache_root=tmp_path / "cache")
    assert net.calls == []


def test_a_symlinked_cache_root_fails_the_run(tmp_path, monkeypatch):
    """cache-confine/prune-fail-open: prune_cache refuses a symlinked root (cache-confine/root-symlink); the run no
    longer goes on uncached."""
    g = body(1, "aa")
    d, _ = load(tmp_path, monkeypatch, g)
    real = tmp_path / "elsewhere"
    real.mkdir()
    link = tmp_path / "cache"
    link.symlink_to(real)
    net = Net()
    with pytest.raises(ValueError):
        nr.run(d, fetcher(net), 100, NOW, cache_root=link)
    assert net.calls == []


# --- the run deadline (4.4.4, national-budget/*) and freshness stamps (4.4.5, national-freshness/*) -------------

class Wall:
    """A fake wall clock moved only by the fetcher's sleeps and the faked answers: the fetcher's monotonic clock and
    the run's clock read the same seconds."""

    def __init__(self, s=0.0):
        self.s, self.slept = s, []

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.s += seconds

    def mono(self):
        return self.s

    def now(self):
        return NOW + timedelta(seconds=self.s)


def walled(net, wall, **kw):
    return PoliteFetcher(opener=net, sleep=wall.sleep, clock=wall.mono, proxy_failures=lambda: [],
                         allowed_hosts=("webapi.legistar.com",), **kw)


class SlowNet(Net):
    """Net whose every answer takes `cost` seconds of the fake wall; `at` records each request's start."""

    def __init__(self, wall, *a, cost=15, **k):
        super().__init__(*a, **k)
        self.wall, self.cost, self.at = wall, cost, []

    def __call__(self, req, timeout):
        self.at.append(self.wall.s)
        self.wall.s += self.cost
        return super().__call__(req, timeout)


def test_probe2_slow_answers_send_nothing_at_or_after_the_deadline(tmp_path, monkeypatch):
    """The reviewer's probe (national-budget/post-deadline-request): answers of 15 s each, so no wait is ever slept
    and the old sleep guard never ran; 5 requests went out at 30-90 s against a 20 s deadline."""
    later = body(99999, "zz")                                          # read after Salem (id order)
    d, _ = load(tmp_path, monkeypatch, SALEM, later, reviewed=(SALEM,))
    evs = [event(n, 138, "2026-12-0%d" % (n + 1), "Final") for n in range(1, 6)]
    wall = Wall()
    net = SlowNet(wall, events={138: evs})
    root = tmp_path / "data" / "national"
    deadline = NOW + timedelta(seconds=20)
    r = nr.collect(root, d, walled(net, wall), 100, NOW, clock=wall.now, deadline=deadline)
    assert net.at and all(t < 20 for t in net.at)                      # every request starts before D
    assert sum(1 for t in net.at if t + net.cost > 20) <= 1            # at most one ends after it
    assert net.at == [0, 15]                                           # robots.txt, Salem's events; no item request
    assert r.outcomes == {SALEM["gov"]: "budget-skipped", later["gov"]: "budget-skipped"}
    assert wall.slept == []
    assert set(json.loads((root / "health.json").read_text())) == {SALEM["gov"], later["gov"]}


class Answer(Resp):
    def __init__(self, status, payload=b"", headers=None):
        super().__init__(payload)
        self.status, self.headers = status, headers or {}


@pytest.mark.parametrize("where", ["robots", "5xx", "reset", "3xx"])
def test_the_deadline_refuses_robots_a_retry_and_a_redirect_hop(where):
    """4.4.6 test 1, parametrised at the fetcher: the hook turns true after `k` requests; the next request, whatever
    sends it (robots.txt, a 5xx retry, a reset retry, a redirect hop), is never sent."""
    url = "https://webapi.legistar.com/v1/aa/events"
    calls = []

    def opener(req, timeout):
        calls.append(req.full_url)
        if req.full_url.endswith("/robots.txt"):
            raise urllib.error.HTTPError(req.full_url, 404, "x", {}, io.BytesIO(b""))
        if where == "5xx":
            raise urllib.error.HTTPError(req.full_url, 503, "x", {}, io.BytesIO(b""))
        if where == "reset":
            raise ConnectionResetError("reset")
        if where == "3xx":
            raise urllib.error.HTTPError(req.full_url, 302, "x", {"Location": url + "?hop=1"}, io.BytesIO(b""))
        return Answer(200, b"[]")
    k = 0 if where == "robots" else 2                                   # robots.txt, then the first events request
    f = PoliteFetcher(opener=opener, sleep=lambda s: None, proxy_failures=lambda: [],
                      allowed_hosts=("webapi.legistar.com",), past_deadline=lambda pause: len(calls) >= k)
    with pytest.raises(fetch.RequestCapReached):
        f.get(url)
    assert len(calls) == k
    assert any(e["event"] == "deadline" for e in f.log)
    assert f.sent("webapi.legistar.com") == k


@pytest.mark.parametrize("seconds, sent", [(30, False), (25, False), (31, True)])
def test_a_wait_ending_at_or_past_the_deadline_is_never_slept_or_sent(tmp_path, monkeypatch, seconds, sent):
    """4.4.6 test 2: a Crawl-delay of 30 s; a deadline at exactly the wait's end (>=) or before it refuses the wait."""
    d, _ = load(tmp_path, monkeypatch, body(1, "aa"))
    wall = Wall()
    net = Net(robots="User-agent: *\nCrawl-delay: 30\n")
    f = walled(net, wall)
    r = nr.run(d, f, 100, NOW, clock=wall.now, deadline=NOW + timedelta(seconds=seconds))
    if sent:
        assert len(net.calls) == 2 and wall.slept == [30.0] and r.outcomes == {"place-4100001": "ok"}
        return
    assert len(net.calls) == 1 and wall.slept == []                    # robots.txt only
    assert f._sent == {"webapi.legistar.com": 1} and f._tenant_sent == {}
    assert r.outcomes == {"place-4100001": "budget-skipped"}


def _good_run(tmp_path, monkeypatch, *govs, at=NOW - timedelta(days=1)):
    """An earlier good run: every body has a feed and health stamped `at`."""
    d, _ = load(tmp_path, monkeypatch, *govs)
    return d, nr.run(d, fetcher(Net()), 100, at, clock=lambda: at)


def _unchanged(r, good, gid, failures=0):
    h, g = r.health[gid], good.health[gid]
    assert (h["last_attempt_at"], h["last_ok_at"]) == (g["last_attempt_at"], g["last_ok_at"])
    assert h["consecutive_failures"] == failures
    assert r.feeds[gid] == good.feeds[gid]                             # checked_at included


def test_a_first_wait_refused_by_the_deadline_keeps_every_stamp(tmp_path, monkeypatch):
    """4.4.6 test 3 (national-freshness/deadline-stamp-without-request)."""
    g = body(1, "aa")
    d, good = _good_run(tmp_path, monkeypatch, g)
    wall = Wall()
    r = nr.run(d, walled(Net(robots="User-agent: *\nCrawl-delay: 30\n"), wall), 100, NOW, clock=wall.now,
               deadline=NOW + timedelta(seconds=20), previous_feeds=good.feeds, previous_health=good.health)
    assert r.outcomes[g["gov"]] == "budget-skipped"
    _unchanged(r, good, g["gov"])
    assert r.health[g["gov"]]["failure_streak"] is None


def test_the_cap_pre_check_and_a_cap_mid_read_keep_every_stamp(tmp_path, monkeypatch):
    a, b = body(1, "aa"), body(2, "bb")
    d, good = _good_run(tmp_path, monkeypatch, a, b)
    r = nr.run(d, fetcher(Net()), 1, NOW, clock=lambda: NOW, previous_feeds=good.feeds,
               previous_health=good.health)                            # robots.txt takes the only request
    assert set(r.outcomes.values()) == {"budget-skipped"}
    for g in (a, b):
        _unchanged(r, good, g["gov"])


def test_robots_counts_a_failure_but_moves_no_stamp(tmp_path, monkeypatch):
    g = body(1, "aa")
    d, good = _good_run(tmp_path, monkeypatch, g)
    r = nr.run(d, fetcher(Net(robots="User-agent: *\nDisallow: /\n")), 100, NOW, clock=lambda: NOW,
               previous_feeds=good.feeds, previous_health=good.health)
    assert r.outcomes[g["gov"]] == "robots"
    _unchanged(r, good, g["gov"], failures=1)
    assert r.health[g["gov"]]["failure_streak"] == {"kind": "robots", "count": 1}


def test_a_collector_error_before_any_get_moves_no_stamp(tmp_path, monkeypatch):
    g = body(1, "aa")
    d, good = _good_run(tmp_path, monkeypatch, g)

    def refuse(entry, fetcher, now, cache_root):
        raise ValueError("refused before any request")
    monkeypatch.setattr(lu, "read_body", refuse)
    r = nr.run(d, fetcher(Net()), 100, NOW, clock=lambda: NOW, previous_feeds=good.feeds,
               previous_health=good.health)
    assert r.outcomes[g["gov"]] == "collector-error"
    _unchanged(r, good, g["gov"], failures=1)


def test_an_ok_with_no_tenant_request_is_a_collector_error(tmp_path, monkeypatch):
    g = body(1, "aa")
    d, good = _good_run(tmp_path, monkeypatch, g)
    real = lu.read_body
    monkeypatch.setattr(lu, "read_body", lambda entry, f, now, cache_root: real(entry, fetcher(Net()), now, cache_root))
    r = nr.run(d, fetcher(Net()), 100, NOW, clock=lambda: NOW, previous_feeds=good.feeds,
               previous_health=good.health)
    assert r.outcomes[g["gov"]] == "collector-error"
    _unchanged(r, good, g["gov"], failures=1)


def test_a_retry_refused_by_the_deadline_stamps_the_attempt_only(tmp_path, monkeypatch):
    """4.4.6 test 4: robots.txt 0-5 s, the events request sent at 10 s (a 503 by 15 s); its retry would be sent at
    20 s, after the 18 s deadline: refused."""
    g = body(1, "aa")
    d, good = _good_run(tmp_path, monkeypatch, g)
    wall = Wall()
    net = SlowNet(wall, fail={"aa": (503, b"")}, cost=5)
    r = nr.run(d, walled(net, wall), 100, NOW, clock=wall.now, deadline=NOW + timedelta(seconds=18),
               previous_feeds=good.feeds, previous_health=good.health)
    assert net.at == [0, 10]                                           # robots.txt, events; no retry
    gid = g["gov"]
    assert r.outcomes[gid] == "budget-skipped"
    start = nr._instant(NOW + timedelta(seconds=0))
    assert r.health[gid]["last_attempt_at"] == r.feeds[gid]["checked_at"] == start
    assert r.health[gid]["last_ok_at"] == r.feeds[gid]["last_ok_at"] == good.health[gid]["last_ok_at"]


def test_an_ok_read_is_stamped_with_its_own_start_not_the_run_now(tmp_path, monkeypatch):
    """4.4.6 test 5."""
    a, b = body(1, "aa"), body(2, "bb")
    d, _ = load(tmp_path, monkeypatch, a, b)
    wall = Wall(s=100)
    net = SlowNet(wall, cost=3)
    r = nr.run(d, walled(net, wall), 100, NOW, clock=wall.now)
    for g, s in ((a, 100), (b, 113)):          # a: robots.txt 100-103, wait to 110, events 110-113; b starts at 113
        start = nr._instant(NOW + timedelta(seconds=s))
        h, f = r.health[g["gov"]], r.feeds[g["gov"]]
        assert h["last_attempt_at"] == h["last_ok_at"] == f["checked_at"] == f["last_ok_at"] == start
        assert start != nr._instant(NOW)


def test_the_fallback_record_keeps_the_previous_valid_stamps(tmp_path, monkeypatch):
    """4.4.6 test 6: `_record` raising (consumer 5): the bare collector-error record keeps the last run's stamps."""
    a, b = body(1, "aa"), body(2, "bb")
    d, good = _good_run(tmp_path, monkeypatch, a, b)
    health = copy.deepcopy(good.health)
    health[b["gov"]]["last_attempt_at"] = "not an instant"

    def broken(*args, **kw):
        raise RuntimeError("record")
    monkeypatch.setattr(nr, "_record", broken)
    monkeypatch.setattr(lu, "read_body", lambda *a, **k: (_ for _ in ()).throw(ValueError("no request")))
    r = nr.run(d, fetcher(Net()), 100, NOW, clock=lambda: NOW, previous_feeds=good.feeds, previous_health=health)
    ha, hb = r.health[a["gov"]], r.health[b["gov"]]
    assert ha["last_error"] == "collector-error"
    assert (ha["last_attempt_at"], ha["last_ok_at"]) == (good.health[a["gov"]]["last_attempt_at"],
                                                         good.health[a["gov"]]["last_ok_at"])
    assert (hb["last_attempt_at"], hb["last_ok_at"]) == (None, good.health[b["gov"]]["last_ok_at"])


def test_a_failing_read_keeps_the_last_good_feed(tmp_path, monkeypatch):
    """national-freshness/fallback-drops-kept-feed: `_read_one` raising before any request is collector-error with
    the fallback record (consecutive_failures 1), and the last good feed is kept as it was, so its body file stays."""
    g = body(1, "aa")
    d, _ = load(tmp_path, monkeypatch, g)
    at = NOW - timedelta(days=1)
    good = nr.run(d, fetcher(Net()), 100, at, clock=lambda: at)
    assert g["gov"] in good.feeds

    def boom(*a, **k):
        raise RuntimeError("before any request")
    monkeypatch.setattr(nr, "_read_one", boom)
    net = Net()
    r = nr.run(d, fetcher(net), 100, NOW, clock=lambda: NOW, previous_feeds=good.feeds, previous_health=good.health)
    assert net.calls == [] and r.outcomes == {g["gov"]: "collector-error"}
    assert r.feeds[g["gov"]]["checked_at"] == good.feeds[g["gov"]]["checked_at"]
    assert r.feeds[g["gov"]]["last_ok_at"] == good.feeds[g["gov"]]["last_ok_at"]
    assert r.health[g["gov"]]["last_error"] == "collector-error"


def test_a_huge_crawl_delay_with_a_deadline_is_budget_skipped(tmp_path, monkeypatch):
    """national-budget/hook-overflow: a robots Crawl-delay too large for timedelta is a wait past the deadline
    (budget-skipped, nothing slept), not an OverflowError turned collector-error."""
    a, b = body(1, "aa"), body(2, "bb")
    d, _ = load(tmp_path, monkeypatch, a, b)
    wall = Wall()
    net = Net(robots="User-agent: *\nCrawl-delay: 100000000000000000\n")
    r = nr.run(d, walled(net, wall), 100, NOW, clock=wall.now, deadline=NOW + timedelta(minutes=60))
    assert r.outcomes == {a["gov"]: "budget-skipped", b["gov"]: "budget-skipped"}
    assert wall.slept == [] and len(net.calls) == 1                    # robots.txt only


class Untouched:
    """A fetcher stand-in that fails on any use: proves nothing was called."""

    def __getattr__(self, name):
        raise AssertionError(f"fetcher.{name} used")


def test_a_deadline_without_a_clock_is_refused_before_anything(tmp_path, monkeypatch):
    """4.4.6 test 7 (frozen-clock-deadline)."""
    d, _ = load(tmp_path, monkeypatch, body(1, "aa"))
    monkeypatch.setattr(nr, "read_previous", lambda root: pytest.fail("a file was read"))
    monkeypatch.setattr(lu, "prune_cache", lambda *a: pytest.fail("the cache was touched"))
    root = tmp_path / "data" / "national"
    for call in (lambda: nr.run(d, Untouched(), 100, NOW, deadline=NOW + timedelta(hours=1), cache_root=root / "cache"),
                 lambda: nr.collect(root, d, Untouched(), 100, NOW, deadline=NOW + timedelta(hours=1)),
                 lambda: nr.run(d, Untouched(), 100, NOW, clock=lambda: NOW, deadline=datetime(2026, 12, 1, 19, 0))):
        with pytest.raises(ValueError):
            call()
    assert not root.exists()


def test_the_hook_is_restored_after_run_returns_and_after_it_raises(tmp_path, monkeypatch):
    d, _ = load(tmp_path, monkeypatch, body(1, "aa"))
    f = fetcher(Net())
    mine = object()
    f.past_deadline = mine
    nr.run(d, f, 100, NOW, clock=lambda: NOW, deadline=NOW + timedelta(hours=1))
    assert f.past_deadline is mine
    monkeypatch.setattr(nr, "merge_proposals", lambda *a: (_ for _ in ()).throw(RuntimeError("late")))
    with pytest.raises(RuntimeError):
        nr.run(d, f, 100, NOW, clock=lambda: NOW, deadline=NOW + timedelta(hours=1))
    assert f.past_deadline is mine


def test_no_deadline_leaves_the_fetcher_hook_alone_and_waits_as_today(tmp_path, monkeypatch):
    govs = [body(1, "aa"), body(2, "bb")]
    d, _ = load(tmp_path, monkeypatch, *govs)
    net, wall = Net(robots="User-agent: *\nCrawl-delay: 3600\n"), Wall()
    f = walled(net, wall)
    r = nr.run(d, f, 100, NOW, clock=wall.now)
    assert set(r.outcomes.values()) == {"ok"} and wall.slept == [3600.0, 3600.0]   # an hour a request
    assert f.past_deadline is None


# --- slow answers (4.4.4 total-answer cap) ------------------------------------------------------------------------

class Drip(Resp):
    """An answer whose every chunk read takes `cost` seconds of the fake wall."""

    def __init__(self, wall, payload, cost=50):
        super().__init__(payload)
        self.wall, self.cost = wall, cost

    def read1(self, n=-1):
        self.wall.s += self.cost
        return super().read1(n)

    def read(self, n=-1):
        self.wall.s += self.cost
        return super().read(n)


@pytest.mark.parametrize("cap, outcome", [(120.0, "server-error"), (None, "ok")])
def test_a_slow_answer_is_cut_at_max_answer_seconds(tmp_path, monkeypatch, cap, outcome):
    """4.4.6 test 8: 200 KiB in 64 KiB chunks at 50 s each: past 120 s the fetch fails; with no cap it is read whole."""
    g = body(1, "aa")
    d, _ = load(tmp_path, monkeypatch, g)
    wall = Wall()
    payload = b"[" + b" " * (200 * 1024) + b"]"

    def opener(req, timeout):
        if req.full_url.endswith("/robots.txt"):
            raise urllib.error.HTTPError(req.full_url, 404, "x", {}, io.BytesIO(b""))
        return Drip(wall, payload)
    f = walled(opener, wall, max_answer_seconds=cap)
    r = nr.run(d, f, 100, NOW, clock=wall.now)
    assert r.outcomes[g["gov"]] == outcome
    if cap:
        assert wall.s == 10 + 150                                      # the floor wait, then 3 chunks: no 4th read


def test_a_slow_403_body_is_a_host_block():
    """4.4.2 holds with the cap: a 403 body cut short by max_answer_seconds is unreadable, so the host stops."""
    wall = Wall()

    def opener(req, timeout):
        if req.full_url.endswith("/robots.txt"):
            raise urllib.error.HTTPError(req.full_url, 404, "x", {}, io.BytesIO(b""))
        raise urllib.error.HTTPError(req.full_url, 403, "x", {}, Drip(wall, b'{"x": 1}' * 30000, cost=200))
    f = walled(opener, wall, max_answer_seconds=120.0)
    with pytest.raises(fetch.HostBlocked) as e:
        f.get("https://webapi.legistar.com/v1/aa/events")
    assert not isinstance(e.value, fetch.TenantBlocked)
