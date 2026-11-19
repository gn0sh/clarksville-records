"""The one host rule, shared by the fetcher (collector/fetch.py) and the city registry (cities/registry.py).

A leaf module (ADR 0012 decision 7): it imports nothing from `cities` or `collector`, so the registry can import it
without pulling in the fetcher, and the fetcher never imports `cities`. collector/fetch.py re-exports these names.
"""
from __future__ import annotations

import re
import urllib.parse

# cityofclarksville.com blocks automated tools: never collect from it. dev2.montgomerytn.gov (the M0 index host)
# answered 403 from the site on 2026-11-07: stopped for good, never retried by another route.
DENIED_HOSTS = ("cityofclarksville.com", "dev2.montgomerytn.gov")


def host_matches(host: str, names) -> bool:
    """True when `host` (a port is ignored) is one of `names` or a subdomain of one. The one host rule for every
    ALLOW check: the fetcher's allowlist, the city registry and any adapter that filters links before asking the
    fetcher. Exact: a trailing dot ("montgomerytn.gov.") is not a listed name, so it never matches an allowlist
    (fetch-host/trailing-dot-denied). Denied lists use host_denied."""
    host = host.lower().split(":")[0]
    return any(host == n or host.endswith("." + n) for n in names)


def host_denied(host: str, names) -> bool:
    """host_matches for a DENIED list: one trailing dot (the DNS root, "cityofclarksville.com.") is the same host, so
    it can't dodge the list. Only this side widens; an allow check never does (fetch-host/trailing-dot-denied)."""
    return host_matches(_no_root_dot(host.lower().split(":")[0]), map(_no_root_dot, names))


def _no_root_dot(name: str) -> str:
    return name[:-1] if name.endswith(".") else name


PLAIN_HOST = re.compile(r"[a-z0-9.-]+")


def plain_hostname(host: str) -> str | None:
    """The lowercase host name of a netloc (no port, no user info) when it is a plain DNS name: letters, digits, dots
    and hyphens only. None otherwise (collector-input/host-percent-encoded): urllib decodes %23, %40, %2f in a host
    before it connects, so a raw netloc like evil.com%23.clarksvilletn.gov must never be matched against the
    allowlist."""
    try:
        name = urllib.parse.urlsplit("//" + host).hostname
    except ValueError:
        return None
    return name if name and PLAIN_HOST.fullmatch(name) else None
