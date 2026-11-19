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
HOST_OK = {"date": "2026-12-01", "link": "https://github.com/gn0sh/clarksville-records/pull/1"}


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
