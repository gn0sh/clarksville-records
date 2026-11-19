"""Fetcher tenant rule (architecture daylight-national 4.4, task C1): on a shared host (webapi.legistar.com) a 403 from
one tenant stops only that tenant; anything else stops the host. Delay, robots.txt and limit_hosts stay per host.
Fakes only: no network."""
import pytest

from collector.fetch import (HostBlocked, HostRefused, PoliteFetcher, RequestCapReached, TenantBlocked, site_key,
                             tenant_key)
from collector.tests.test_fetch import Clock, FakeNet

H = "https://webapi.legistar.com"
JSON_403 = b'{"Message":"Agency not found or access denied."}'


def make(routes):
    net, clock = FakeNet(routes), Clock()
    f = PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: [],
                      allowed_hosts=("webapi.legistar.com", "h.example"))
    return f, net, clock


def urls(net):
    return [u for u, _ in net.calls]


# ------------------------------------------------------------------ tenant_key (shared_path, architecture 4.4.1)
@pytest.mark.parametrize("url, key", [
    (f"{H}/v1/salem/events", "webapi.legistar.com/salem"),
    (f"{H}/v1/Salem/events", "webapi.legistar.com/salem"),
    (f"{H}/v1/SALEM/bodies?$top=1", "webapi.legistar.com/salem"),
    (f"{H}/V1/salem/events", "webapi.legistar.com/salem"),     # case is the one variation mapped
    ("https://WebAPI.Legistar.com:443/v1/salem/events", "webapi.legistar.com/salem"),
    ("https://www.webapi.legistar.com/v1/salem/events", "webapi.legistar.com/salem"),
    (f"{H}/v1/st-paul-2/events", "webapi.legistar.com/st-paul-2"),
    (f"{H}/v1/salem/", "webapi.legistar.com/salem"),
    (f"{H}/v1/salem", "webapi.legistar.com/salem"),             # no further path: still salem's
    (f"{H}/v1/salem/events.json", "webapi.legistar.com/salem"),
    (f"{H}/v1/salem/events?$filter=EventBodyId%20eq%201", "webapi.legistar.com/salem"),   # the query is not keyed
    (f"{H}/v1/{'a' * 40}/x", f"webapi.legistar.com/{'a' * 40}"),
    (f"{H}/robots.txt", None),
    (f"{H}/v1/", None),
    (f"{H}/v1", None),
    (f"{H}/", None),
    (H, None),
    (f"{H}/v2/salem/events", None),
    ("https://h.example/v1/salem/events", None),     # not a shared host
    ("https://h.example/v1/%73alem/../x", None),     # not a shared host: its paths are not parsed
    ("https://[x/v1/salem/", None),                 # malformed
])
def test_tenant_key(url, key):
    assert tenant_key(url) == key


REFUSED = ["//v1/salem/events", "/%2fv1/salem/events", "/%2Fv1/salem/events", "/v1/%73alem/events",
           "/v1/sa%6Cem/events", "/v1/salem%2fevents", "/v1/salem/../salem/events", "/v1/x/../salem/events",
           "/v1/x/%2e%2e/salem/events", "/v1/x/%2E%2E/salem/events", "/v1/x/%252e%252e/salem/events",
           "/v1/./salem/events", "/v1/x\\..\\salem/events", "/v1//salem/events", "/%761/salem/events",
           "/v1/salem./events", "/v1/.salem/events", "/./v1/salem/events", "/v1/salem;x/events", "/v1/sa+lem/events",
           "/v1/sal\u00e9m/events", "/v1/salem//events", "/v1/salem/events/..", "/v1/salem/events/.",
           "/v1/s/events", f"/v1/{'a' * 41}/events", "/v1/sa_lem/events", "/v1/sa.lem/events", "/v1/salem/x..y",
           "/robots.txt/..", "/v2//x"]


@pytest.mark.parametrize("path", REFUSED)
def test_a_non_canonical_shared_path_is_refused_by_tenant_key(path):
    from collector.fetch import TenantPathRefused, shared_path
    with pytest.raises(TenantPathRefused):
        tenant_key(f"{H}{path}")
    with pytest.raises(TenantPathRefused):
        shared_path(f"{H}{path}")


def test_a_tenant_key_never_equals_a_site_key():
    assert "/" in tenant_key(f"{H}/v1/salem/x") and "/" not in site_key("webapi.legistar.com")


# ------------------------------------------------------------------ 403 classification
def test_a_json_403_on_one_tenant_blocks_only_that_tenant():
    """C1: a 403 on /v1/ta/ (task wording: /v1/a/; the 4.4 pattern needs 2-40 characters) stops only tenant ta."""
    f, net, _ = make({f"{H}/v1/ta/events": (403, JSON_403), f"{H}/v1/tb/events": (200, b"[]")})
    with pytest.raises(TenantBlocked):
        f.get(f"{H}/v1/ta/events")
    n = len(net.calls)
    with pytest.raises(TenantBlocked):          # tenant ta: no request again this run, any path
        f.get(f"{H}/v1/ta/bodies")
    with pytest.raises(TenantBlocked):          # the case-folded spelling is the same tenant
        f.get(f"{H}/v1/TA/events")
    assert len(net.calls) == n
    assert f.get(f"{H}/v1/tb/events")[1] == b"[]"    # tenant tb and the host carry on
    assert urls(net)[-1] == f"{H}/v1/tb/events"
    blocked = [e for e in f.log if e["event"] == "blocked"]
    assert len(blocked) == 1 and blocked[0]["tenant"] == "webapi.legistar.com/ta"


def test_tenant_blocked_is_a_host_blocked_for_existing_callers():
    assert issubclass(TenantBlocked, HostBlocked)
    f, _, _ = make({f"{H}/v1/ta/events": (403, JSON_403)})
    with pytest.raises(HostBlocked):
        f.get(f"{H}/v1/ta/events")


def test_salem_and_Salem_are_one_tenant_for_a_block():
    """national/tenant-key-normalize (finding 10)."""
    f, net, _ = make({f"{H}/v1/Salem/events": (403, JSON_403), f"{H}/v1/salem/events": (200, b"[]")})
    with pytest.raises(TenantBlocked):
        f.get(f"{H}/v1/Salem/events")
    n = len(net.calls)
    with pytest.raises(TenantBlocked):
        f.get(f"{H}/v1/salem/events")
    assert len(net.calls) == n


def test_a_403_from_a_second_distinct_tenant_blocks_the_host():
    f, net, _ = make({f"{H}/v1/ta/events": (403, JSON_403), f"{H}/v1/tb/events": (403, JSON_403),
                      f"{H}/v1/tc/events": (200, b"[]"), f"{H}/v1/tb/bodies": (200, b"[]")})
    with pytest.raises(TenantBlocked):
        f.get(f"{H}/v1/ta/events")
    with pytest.raises(HostBlocked) as e:
        f.get(f"{H}/v1/tb/events")
    assert not isinstance(e.value, TenantBlocked)
    n = len(net.calls)
    for u in (f"{H}/v1/tc/events", f"{H}/v1/tb/bodies", f"{H}/v1/ta/events"):
        with pytest.raises(HostBlocked):
            f.get(u)
    assert len(net.calls) == n                  # no request to any tenant of the host after that


def test_a_429_on_a_tenant_path_blocks_the_host():
    f, net, _ = make({f"{H}/v1/ta/events": (429, b'{"Message":"Too many"}', {"Retry-After": "1"}),
                      f"{H}/v1/tb/events": (200, b"[]")})
    with pytest.raises(HostBlocked) as e:
        f.get(f"{H}/v1/ta/events")
    assert not isinstance(e.value, TenantBlocked)
    n = len(net.calls)
    with pytest.raises(HostBlocked):
        f.get(f"{H}/v1/tb/events")
    assert len(net.calls) == n
    assert urls(net).count(f"{H}/v1/ta/events") == 1    # never retried


def test_a_403_on_robots_txt_blocks_the_host():
    f, net, _ = make({f"{H}/robots.txt": (403, JSON_403), f"{H}/v1/tb/events": (200, b"[]")})
    with pytest.raises(HostBlocked) as e:
        f.get(f"{H}/v1/ta/events")
    assert not isinstance(e.value, TenantBlocked)
    assert urls(net) == [f"{H}/robots.txt"]
    with pytest.raises(HostBlocked):
        f.get(f"{H}/v1/tb/events")
    assert urls(net) == [f"{H}/robots.txt"]


def test_a_403_on_a_non_tenant_path_blocks_the_host():
    f, net, _ = make({f"{H}/v1/": (403, JSON_403), f"{H}/v1/tb/events": (200, b"[]")})
    with pytest.raises(HostBlocked) as e:
        f.get(f"{H}/v1/")
    assert not isinstance(e.value, TenantBlocked)
    n = len(net.calls)
    with pytest.raises(HostBlocked):
        f.get(f"{H}/v1/tb/events")
    assert len(net.calls) == n


@pytest.mark.parametrize("body", [b"<html><body>Access denied</body></html>", b"", b"not json", b'"denied"',
                                  b"[1, 2]", b"null", b"\xff\xfe{}"])
def test_a_403_whose_body_is_not_a_json_object_blocks_the_host(body):
    f, net, _ = make({f"{H}/v1/ta/events": (403, body), f"{H}/v1/tb/events": (200, b"[]")})
    with pytest.raises(HostBlocked) as e:
        f.get(f"{H}/v1/ta/events")
    assert not isinstance(e.value, TenantBlocked)
    n = len(net.calls)
    with pytest.raises(HostBlocked):
        f.get(f"{H}/v1/tb/events")
    assert len(net.calls) == n


def test_a_json_403_on_a_host_that_is_not_shared_still_blocks_the_host():
    f, net, _ = make({"https://h.example/v1/ta/events": (403, JSON_403), "https://h.example/v1/tb/events": (200, b"x")})
    with pytest.raises(HostBlocked) as e:
        f.get("https://h.example/v1/ta/events")
    assert not isinstance(e.value, TenantBlocked)
    n = len(net.calls)
    with pytest.raises(HostBlocked):
        f.get("https://h.example/v1/tb/events")
    assert len(net.calls) == n


def test_a_proxy_recorded_403_on_a_tenant_path_blocks_nothing():
    from collector.fetch import ProxyRefused
    rec = [{"ts": "2999-01-01T00:00:00.000Z", "host": "webapi.legistar.com:443", "detail": "gateway answered 403"}]
    net, clock = FakeNet({f"{H}/v1/ta/events": (403, JSON_403)}), Clock()
    f = PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: rec,
                      allowed_hosts=("webapi.legistar.com",))
    with pytest.raises(ProxyRefused):
        f.get(f"{H}/v1/ta/events")
    assert not f._blocked and not f._tenant_blocked


def test_a_redirect_into_a_blocked_tenant_is_not_requested():
    f, net, _ = make({f"{H}/v1/ta/events": (403, JSON_403),
                      f"{H}/v1/tb/events": (302, b"", {"Location": f"{H}/v1/ta/other"})})
    with pytest.raises(TenantBlocked):
        f.get(f"{H}/v1/ta/events")
    with pytest.raises(TenantBlocked):
        f.get(f"{H}/v1/tb/events")
    assert f"{H}/v1/ta/other" not in urls(net)


# ------------------------------------------------------------------ delay and caps stay per host
def test_the_delay_is_per_host_across_tenants():
    robots = b"User-agent: *\nCrawl-delay: 12\n"
    f, net, clock = make({f"{H}/robots.txt": (200, robots), f"{H}/v1/ta/e": (200, b"[]"), f"{H}/v1/tb/e": (200, b"[]"),
                          f"{H}/v1/ta/f": (403, JSON_403), f"{H}/v1/tc/e": (200, b"[]")})
    f.get(f"{H}/v1/ta/e")
    f.get(f"{H}/v1/tb/e")                         # another tenant: same host, same gap
    with pytest.raises(TenantBlocked):
        f.get(f"{H}/v1/ta/f")
    f.get(f"{H}/v1/tc/e")                         # a tenant block never shortens the host gap
    assert clock.slept == [12.0, 12.0, 12.0, 12.0]
    assert urls(net).count(f"{H}/robots.txt") == 1    # robots.txt once per host, not per tenant


def test_the_host_cap_counts_every_tenant():
    f, net, _ = make({f"{H}/v1/ta/e": (200, b"[]"), f"{H}/v1/tb/e": (200, b"[]"), f"{H}/v1/tc/e": (200, b"[]")})
    f.limit_hosts(("webapi.legistar.com",), 3)
    f.get(f"{H}/v1/ta/e")                         # robots + a: 2
    f.get(f"{H}/v1/tb/e")                         # 3
    with pytest.raises(RequestCapReached):
        f.get(f"{H}/v1/tc/e")
    assert len(net.calls) == 3


def test_limit_tenant_caps_one_tenant_inside_the_host_cap():
    f, net, _ = make({f"{H}/v1/ta/{i}": (200, b"[]") for i in range(5)} | {f"{H}/v1/tb/{i}": (200, b"[]") for i in range(5)}
                     | {f"{H}/v1/ta/r": (503, b"busy")})
    f.limit_hosts(("webapi.legistar.com",), 6)
    f.limit_tenant(f"{H}/v1/TA/x", 3)              # case-folded: tenant ta
    assert f.remaining_tenant(f"{H}/v1/ta/0") == 3 and f.remaining_tenant(f"{H}/v1/tb/0") is None
    f.get(f"{H}/v1/ta/r")                         # robots (host only) + r + its retry: tenant ta 2, host 3
    assert f.remaining_tenant(f"{H}/v1/ta/0") == 1 and f.remaining("webapi.legistar.com") == 3
    f.get(f"{H}/v1/ta/0")                         # tenant ta 3, host 4
    with pytest.raises(RequestCapReached):
        f.get(f"{H}/v1/ta/1")                     # tenant cap: not made
    assert f"{H}/v1/ta/1" not in urls(net)
    f.get(f"{H}/v1/tb/0")                         # host 5
    f.get(f"{H}/v1/tb/1")                         # host 6
    with pytest.raises(RequestCapReached):       # the host cap still holds over an uncapped tenant
        f.get(f"{H}/v1/tb/2")
    assert len(net.calls) == 6


def test_a_later_tenant_cap_never_raises_an_earlier_one():
    f, _, _ = make({})
    f.limit_tenant(f"{H}/v1/ta/x", 1)
    f.limit_tenant(f"{H}/v1/ta/y", 10)
    assert f.remaining_tenant(f"{H}/v1/ta/z") == 1


def test_limit_tenant_refuses_a_url_that_is_no_tenant():
    f, _, _ = make({})
    with pytest.raises(ValueError):
        f.limit_tenant(f"{H}/robots.txt", 3)
    with pytest.raises(ValueError):
        f.limit_tenant("https://h.example/v1/ta/x", 3)


@pytest.mark.parametrize("target", [f"{H}/v1/tb/events", "https://h.example/x"])
def test_a_redirect_from_a_capped_tenant_cannot_leave_it(target):
    f, net, _ = make({f"{H}/v1/ta/r": (302, b"", {"Location": target}), target: (200, b"x")})
    f.limit_tenant(f"{H}/v1/ta/r", 5)
    with pytest.raises(HostRefused):
        f.get(f"{H}/v1/ta/r")
    assert target not in urls(net)


def test_a_redirect_inside_a_capped_tenant_counts_against_its_cap():
    f, net, _ = make({f"{H}/v1/ta/r": (302, b"", {"Location": f"{H}/v1/TA/x"}), f"{H}/v1/ta/x": (200, b"[]"),
                      f"{H}/v1/TA/x": (200, b"[]")})
    f.limit_tenant(f"{H}/v1/ta/r", 2)
    assert f.get(f"{H}/v1/ta/r")[1] == b"[]"
    assert f.remaining_tenant(f"{H}/v1/ta/r") == 0


# ------------------------------------------------------------------ national/tenant-block-escape (4.4.1)
MAPPED = ["/V1/salem/events", "/v1/SALEM/events", "/V1/Salem/other", "/v1/salem", "/v1/Salem/", "/v1/salem/events?x=1"]


@pytest.mark.parametrize("path", REFUSED + MAPPED)
def test_no_spelling_reaches_a_blocked_salem(path):
    from collector.fetch import TenantPathRefused
    alt = f"{H}{path}"
    f, net, _ = make({f"{H}/v1/salem/events": (403, JSON_403), alt: (200, b"[]")})
    with pytest.raises(TenantBlocked):
        f.get(f"{H}/v1/salem/events")
    n = len(net.calls)
    with pytest.raises(TenantPathRefused if path in REFUSED else TenantBlocked):
        f.get(alt)
    assert len(net.calls) == n                     # zero requests
    if path in REFUSED:
        assert f.log[-1]["event"] == "refused" and f.log[-1]["url"] == alt


@pytest.mark.parametrize("path", REFUSED + MAPPED)
def test_no_spelling_steps_around_a_capped_salem(path):
    from collector.fetch import TenantPathRefused
    alt = f"{H}{path}"
    f, net, _ = make({f"{H}/v1/salem/events": (200, b"[]"), alt: (200, b"[]")})
    f.limit_tenant(f"{H}/v1/salem/events", 1)
    f.get(f"{H}/v1/salem/events")
    n = len(net.calls)
    with pytest.raises(TenantPathRefused if path in REFUSED else RequestCapReached):
        f.get(alt)
    assert len(net.calls) == n                     # zero requests
    cap = [e for e in f.log if e["event"] == "cap"]
    assert all(e["tenant"] == "webapi.legistar.com/salem" for e in cap)    # logged under the canonical key


@pytest.mark.parametrize("path", REFUSED)
def test_limit_tenant_refuses_a_non_canonical_url(path):
    from collector.fetch import TenantPathRefused
    f, _, _ = make({})
    with pytest.raises(TenantPathRefused):
        f.limit_tenant(f"{H}{path}", 3)
    with pytest.raises(TenantPathRefused):
        f.remaining_tenant(f"{H}{path}")


@pytest.mark.parametrize("path", ["", "/", "/robots.txt", "/v1", "/v1/", "/v2/x", "/v1/salem", "/v1/salem/",
                                  "/v1/Salem/Events/12/EventItems?AgendaNote=1&$filter=a%20eq%201",
                                  "/v1/salem/events.json", "/v1/st-paul-2/bodies"])
def test_canonical_shared_paths_are_fetched(path):
    url = f"{H}{path}"
    f, net, _ = make({url: (200, b"[]")})
    assert f.get(url)[1] == b"[]"
    assert urls(net)[-1] == url                    # sent exactly as asked, never rewritten


@pytest.mark.parametrize("loc, exc", [
    (f"{H}/v1/ta/../salem/y", "TenantPathRefused"),            # absolute: urljoin keeps the dot segments
    (f"{H}/v1/ta/%2e%2e/salem/y", "TenantPathRefused"),
    ("/%2fv1/salem/y", "TenantPathRefused"),
    (f"{H}//v1/salem/y", "TenantPathRefused"),
    ("../salem/y", "HostRefused"),                             # resolves to /v1/salem/y: leaves capped ta
    ("/V1/SALEM/y", "HostRefused"),
    ("//webapi.legistar.com/v1/salem/y", "HostRefused"),
    ("//v1/salem/y", "HostRefused"),                           # a network-path reference: host "v1", not allowed
])
def test_redirect_forms_from_a_capped_tenant_never_reach_salem(loc, exc):
    from collector import fetch as F
    f, net, _ = make({f"{H}/v1/ta/x": (302, b"", {"Location": loc})})
    f.limit_tenant(f"{H}/v1/ta/x", 5)
    with pytest.raises(getattr(F, exc)):
        f.get(f"{H}/v1/ta/x")
    assert urls(net) == [f"{H}/robots.txt", f"{H}/v1/ta/x"]


@pytest.mark.parametrize("loc, exc", [("/V1/Salem/y", TenantBlocked), ("../salem/y", TenantBlocked),
                                      ("/v1/salem/../salem/y", TenantBlocked),   # urljoin resolves it
                                      (f"{H}/v1/salem/../salem/y", HostRefused), ("/%2fv1/salem/y", HostRefused)])
def test_redirect_forms_from_an_uncapped_tenant_never_reach_a_blocked_salem(loc, exc):
    f, net, _ = make({f"{H}/v1/salem/e": (403, JSON_403), f"{H}/v1/ta/x": (302, b"", {"Location": loc})})
    with pytest.raises(TenantBlocked):
        f.get(f"{H}/v1/salem/e")
    with pytest.raises(exc):
        f.get(f"{H}/v1/ta/x")
    assert urls(net)[-1] == f"{H}/v1/ta/x"         # the redirect target was never requested


def test_the_refusal_is_a_scheme_refused_logged_with_no_request():
    from collector.fetch import SchemeRefused, TenantPathRefused
    f, net, _ = make({})
    with pytest.raises(TenantPathRefused) as e:
        f.get(f"{H}/v1/%73alem/events")
    assert isinstance(e.value, SchemeRefused) and net.calls == []
    assert f.log[-1] == {"event": "refused", "host": "webapi.legistar.com", "url": f"{H}/v1/%73alem/events",
                         "detail": "not a canonical shared-host path"}


@pytest.mark.parametrize("url", ["https://h.example/v1/%73alem/x", "https://h.example/a/../b", "https://h.example/V1/x"])
def test_other_hosts_keep_their_paths(url):
    f, net, _ = make({url: (200, b"x")})
    assert f.get(url)[1] == b"x"


@pytest.mark.parametrize("path", ["/", "/v1/", "/v1", "/v2/x"])
def test_a_403_on_a_plain_non_tenant_path_still_blocks_the_host(path):
    f, net, _ = make({f"{H}{path}": (403, JSON_403), f"{H}/v1/tb/e": (200, b"[]")})
    with pytest.raises(HostBlocked) as e:
        f.get(f"{H}{path}")
    assert not isinstance(e.value, TenantBlocked)
    n = len(net.calls)
    with pytest.raises(HostBlocked):
        f.get(f"{H}/v1/tb/e")
    assert len(net.calls) == n


# ------------------------------------------------------------------ national/tenant-robots-host-block
def test_robots_txt_redirecting_to_a_tenant_json_403_blocks_the_host_once():
    f, net, _ = make({f"{H}/robots.txt": (302, b"", {"Location": f"{H}/v1/zz/robots"}),
                      f"{H}/v1/zz/robots": (403, JSON_403), f"{H}/v1/ta/e": (200, b"[]"), f"{H}/v1/tb/e": (200, b"[]")})
    with pytest.raises(HostBlocked) as e:
        f.get(f"{H}/v1/ta/e")
    assert not isinstance(e.value, TenantBlocked)
    for u in (f"{H}/v1/ta/e", f"{H}/v1/tb/e", f"{H}/v1/tb/e"):
        with pytest.raises(HostBlocked):
            f.get(u)
    assert urls(net) == [f"{H}/robots.txt", f"{H}/v1/zz/robots"]     # robots.txt asked once
    assert "webapi.legistar.com" in f._blocked and not f._tenant_blocked


def test_robots_txt_redirecting_into_an_already_blocked_tenant_blocks_the_host():
    """robots.txt is read per exact host: www. has its own, which redirects into the blocked tenant."""
    W = "https://www.webapi.legistar.com"
    f, net, _ = make({f"{H}/v1/zz/e": (403, JSON_403),
                      f"{W}/robots.txt": (302, b"", {"Location": f"{H}/v1/zz/robots"})})
    with pytest.raises(TenantBlocked):
        f.get(f"{H}/v1/zz/e")
    n = len(net.calls)
    with pytest.raises(HostBlocked) as e:
        f.get(f"{W}/v1/ta/e")
    assert not isinstance(e.value, TenantBlocked)
    assert len(net.calls) == n + 1                # www robots.txt only; the blocked tenant is not asked
    with pytest.raises(HostBlocked):
        f.get(f"{W}/v1/tb/e")
    assert len(net.calls) == n + 1


def test_robots_txt_hop_into_a_capped_tenant_caches_disallow_and_still_reports_the_cap():
    """4.4.1 consumer 6 (reviewer nit 6): robots.txt redirects into a tenant whose cap is used up."""
    f, net, _ = make({f"{H}/robots.txt": (302, b"", {"Location": f"{H}/v1/zz/robots"}),
                      f"{H}/v1/zz/robots": (200, b""), f"{H}/v1/ta/e": (200, b"[]")})
    f.limit_tenant(f"{H}/v1/zz/robots", 0)
    for _ in range(3):
        with pytest.raises(RequestCapReached):
            f.get(f"{H}/v1/ta/e")
    assert urls(net) == [f"{H}/robots.txt"]       # robots.txt asked once; never re-asked, the tenant never asked
    assert f._robots["webapi.legistar.com"].disallow_all
    assert [e["event"] for e in f.log].count("robots_refused") == 1


def test_robots_txt_hop_to_a_non_canonical_shared_path_caches_disallow_all():
    from collector.fetch import RobotsDisallowed
    f, net, _ = make({f"{H}/robots.txt": (302, b"", {"Location": f"{H}//v1/zz/robots"}),
                      f"{H}/v1/ta/e": (200, b"[]")})
    for _ in range(3):
        with pytest.raises(RobotsDisallowed):
            f.get(f"{H}/v1/ta/e")
    assert urls(net) == [f"{H}/robots.txt"]
    assert f._robots["webapi.legistar.com"].disallow_all
    assert [e["event"] for e in f.log].count("robots_refused") == 1


def test_a_403_body_with_a_utf8_bom_is_still_json():
    f, _, _ = make({f"{H}/v1/ta/e": (403, b'\xef\xbb\xbf{"Message":"no"}')})
    with pytest.raises(TenantBlocked):
        f.get(f"{H}/v1/ta/e")
