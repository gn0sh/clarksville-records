"""Count "Request it" taps per government from Buttondown (architecture daylight-national section 6; task B12).

Run on Brian's PC, never in Actions: it needs his Buttondown key in the environment variable BUTTONDOWN_API_KEY.
    BUTTONDOWN_API_KEY=... python -I tools/national/request_report.py

Counts the `req-<gov id>` tags of confirmed (type "regular") subscribers only, one per subscriber per id. Ids not in
config/national/directory.yml are ignored and the number ignored is printed (security finding 11, national/form-abuse).
The counts are advisory: anyone can tag a known email (finding 2). It never prints or writes an email address or the
key, reads no GoatCounter, and writes no file. Standard library only; HTTPS to api.buttondown.com only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

KEY_ENV = "BUTTONDOWN_API_KEY"
HOST = "api.buttondown.com"
FIRST_URL = f"https://{HOST}/v1/subscribers?type=regular"
TIMEOUT = 30
MAX_PAGES = 2_000
MAX_RESPONSE = 16_000_000
PREFIX = "req-"
HEADER = "advisory: anyone can tag a known email"
_KEY = re.compile(r"[!-~]{16,256}")


class ReportError(Exception):
    """A message that never holds the key, a URL query, a body or an address."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _fetch(url: str, key: str) -> dict:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != HOST or parts.port not in (None, 443) \
            or not parts.path.startswith("/v1/") or parts.username or parts.password:
        raise ReportError(f"refusing a link that is not https://{HOST}/v1/")
    req = urllib.request.Request(url, headers={"Authorization": f"Token {key}", "Accept": "application/json",
                                               "User-Agent": "daylight-request-report"})
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            raw = r.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as e:
        hint = " (check the key)" if e.code in (401, 403) else ""
        raise ReportError(f"Buttondown answered HTTP {e.code}{hint}") from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ReportError("could not reach Buttondown") from None
    if len(raw) > MAX_RESPONSE:
        raise ReportError("Buttondown answer too large")
    try:
        doc = json.loads(raw)
    except ValueError:
        raise ReportError("Buttondown answer is not JSON") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("results"), list):
        raise ReportError("Buttondown answer has an unexpected shape")
    return doc


def count_requests(fetch, known_ids: set[str]) -> tuple[Counter, int, int]:
    """(counts per known id, number of req- tags ignored as unknown, confirmed subscribers read).
    `fetch(url) -> page dict`. Only tags are read from a row; the address is never touched."""
    counts: Counter = Counter()
    ignored = subscribers = 0
    url, seen = FIRST_URL, set()
    for _ in range(MAX_PAGES):
        page = fetch(url)
        for row in page["results"]:
            if not isinstance(row, dict) or row.get("type") != "regular":
                continue
            subscribers += 1
            tags = row.get("tags")
            for t in ({t for t in tags if isinstance(t, str)} if isinstance(tags, list) else ()):
                if not t.startswith(PREFIX):
                    continue
                if t[len(PREFIX):] in known_ids:
                    counts[t[len(PREFIX):]] += 1
                else:
                    ignored += 1
        nxt = page.get("next")
        if not nxt:
            return counts, ignored, subscribers
        seen.add(url)
        if not isinstance(nxt, str) or nxt in seen:
            raise ReportError("Buttondown pagination did not advance")
        url = nxt
    raise ReportError("too many pages")


def render(counts: Counter, ignored: int, subscribers: int, names: dict[str, str]) -> str:
    lines = [f"Request report ({HEADER})", f"confirmed subscribers read: {subscribers}",
             f"ignored req- tags not in the directory: {ignored}"]
    if not counts:
        lines.append("no requests for any government in the directory")
    for gov, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"{n:5d}  {gov}  {names.get(gov, '')}".rstrip())
    return "\n".join(lines)


def main(argv: list[str] | None = None, env=None, fetch=None) -> int:
    ap = argparse.ArgumentParser(
        prog="request_report.py",
        description=("Counts req-<government id> tags among confirmed Buttondown subscribers. Run on Brian's PC with his "
                     f"key in the environment variable {KEY_ENV}; never in Actions. Advisory only: anyone can tag a known "
                     "email. Ids not in config/national/directory.yml are ignored (the number is printed). Prints no email "
                     "address and writes no file."))
    ap.parse_args(argv)
    env = os.environ if env is None else env
    key = env.get(KEY_ENV, "")
    if not _KEY.fullmatch(key):
        print(f"error: set {KEY_ENV} to your Buttondown API key", file=sys.stderr)
        return 2
    try:
        from sitegen.national import load_directory
        directory = load_directory()
        names = {g["gov"]: g["body_name"] for g in directory.govs}
        counts, ignored, subs = count_requests(fetch or (lambda u: _fetch(u, key)), set(names))
    except ReportError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(render(counts, ignored, subs, names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
