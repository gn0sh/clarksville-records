"""Polite HTTP fetcher.

Rules (CLAUDE.md, spec): obey robots.txt per host, at least MIN_DELAY seconds between
requests to the same host (robots.txt fetch included), a clear User-Agent, and stop for a
host on 403/429 without retrying by any other route.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

USER_AGENT = ("clarksville-records research collector "
              "(+https://github.com/gn0sh/clarksville-records; polite, 10s/host)")
MIN_DELAY = 10.0


class HostBlocked(Exception):
    """The host answered 403/429 (or is already marked blocked). Do not retry it."""


class RobotsDisallowed(Exception):
    pass


@dataclass
class PoliteFetcher:
    min_delay: float = MIN_DELAY
    user_agent: str = USER_AGENT
    timeout: float = 60.0
    sleep: object = time.sleep
    clock: object = time.monotonic
    opener: object = None                            # injectable for tests
    _last: dict = field(default_factory=dict)        # host -> clock() of last request
    _robots: dict = field(default_factory=dict)      # host -> RobotFileParser
    _blocked: dict = field(default_factory=dict)     # host -> reason
    _delay: dict = field(default_factory=dict)       # host -> delay (robots Crawl-delay may raise it)

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        delay = max(self.min_delay, self._delay.get(host, 0.0))
        if last is not None:
            gap = self.clock() - last
            if gap < delay:
                self.sleep(delay - gap)
        self._last[host] = self.clock()

    def _open(self, req):
        if self.opener is not None:
            return self.opener(req, self.timeout)
        return urllib.request.urlopen(req, timeout=self.timeout)

    def _raw_get(self, url: str) -> tuple[int, bytes, dict]:
        host = urllib.parse.urlsplit(url).netloc
        if host in self._blocked:
            raise HostBlocked(f"{host}: {self._blocked[host]}")
        self._wait(host)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with self._open(req) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                snippet = (e.read() or b"")[:200].decode("utf-8", "replace")
                self._blocked[host] = (f"HTTP {e.code} on {url} server={e.headers.get('Server')!r} "
                                       f"body={snippet!r}")
                raise HostBlocked(self._blocked[host]) from None
            return e.code, (e.read() or b""), dict(e.headers or {})

    def robots(self, host: str, scheme: str = "https") -> urllib.robotparser.RobotFileParser:
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            status, body, _ = self._raw_get(f"{scheme}://{host}/robots.txt")
            if status == 200:
                rp.parse(body.decode("utf-8", "replace").splitlines())
            elif 400 <= status < 500:
                rp.allow_all = True          # no robots.txt = no rules (RFC 9309)
            else:
                rp.disallow_all = True       # server error: be conservative
            self._robots[host] = rp
            delay = rp.crawl_delay(self.user_agent) or rp.crawl_delay("*")
            if delay:
                self._delay[host] = float(delay)
        return self._robots[host]

    def get(self, url: str) -> tuple[int, bytes, dict]:
        parts = urllib.parse.urlsplit(url)
        rp = self.robots(parts.netloc, parts.scheme)
        if not rp.can_fetch(self.user_agent, url):
            raise RobotsDisallowed(url)
        return self._raw_get(url)


def cache_download(fetcher: PoliteFetcher, url: str, raw_dir: Path, manifest_path: Path,
                   meta: dict | None = None) -> dict:
    """Download url into raw_dir (named by sha256) unless the manifest already has it."""
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    for entry in manifest:
        if entry["url"] == url and (raw_dir / entry["file"]).exists():
            return entry
    status, body, headers = fetcher.get(url)
    if status != 200:
        raise RuntimeError(f"HTTP {status} for {url}")
    digest = hashlib.sha256(body).hexdigest()
    ext = ".pdf" if body[:4] == b"%PDF" else ".bin"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{digest}{ext}").write_bytes(body)
    entry = {"url": url, "sha256": digest, "file": f"{digest}{ext}", "bytes": len(body),
             "content_type": headers.get("Content-Type", ""),
             "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             **(meta or {})}
    manifest = [e for e in manifest if e["url"] != url] + [entry]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return entry
