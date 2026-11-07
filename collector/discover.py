"""Minutes discovery: list County Commission minutes PDFs from the county clerk's production page.

The page (https://montgomerytn.gov/clerk/county-commission-minutes) lists minutes from January 2022 on; older
minutes are only in BIS Online's search, so 2020-2021 documents come from the store (fetched in M0). The dev host
that M0 used (dev2.montgomerytn.gov) now answers 403 from the site and is denied in collector/fetch.py.

A link's label is only a hint: "December 2025 Minutes" held the Dec 8, 2025 packet with the Nov 10, 2025 minutes
inside it. Meeting dates come from the document text (collector/facts.py), never from the label.

If the page moves, answers with no minutes links, or is blocked, discovery fails loudly (DiscoveryError, non-zero
exit). It never guesses other hosts or URL patterns (spec A4).
"""
from __future__ import annotations

import html
import re
import urllib.parse

from .config import YEARS

INDEX_URL = "https://montgomerytn.gov/clerk/county-commission-minutes"
VIEWER_HOST = "montgomeryminutes.bisonline.com"
MONTHS = ("january february march april may june july august september october "
          "november december").split()
LINK_RE = re.compile(r'<a[^>]+href="([^"]*bisonline\.com/viewpdf\.php\?id=[^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
LABEL_RE = re.compile(r"\b(" + "|".join(MONTHS) + r")\b\s*(\d{1,2})?\s*,?\s*(\d{4})", re.I)


class DiscoveryError(Exception):
    pass


def parse_index(page: str) -> list[dict]:
    """Every link to the minutes viewer: [{url, label}] in page order."""
    out = []
    for m in LINK_RE.finditer(page):
        label = re.sub(r"<[^>]+>", " ", m.group(2))
        label = re.sub(r"\s+", " ", html.unescape(label)).strip()
        out.append({"url": html.unescape(m.group(1)).strip(), "label": label})
    return out


def https_same_host(url: str) -> str:
    """The index lists 2020-2021 files as http://. They are requested as https:// on the same host (the
    sandbox proxy carries HTTPS only). Same host, same path: not another route."""
    p = urllib.parse.urlsplit(url)
    if p.scheme == "http" and p.netloc.lower() == VIEWER_HOST:
        return urllib.parse.urlunsplit(("https",) + tuple(p)[1:])
    return url


def classify(label: str) -> dict | None:
    """'April 1, 2024 Minutes (Special Called Meeting)' -> {year, month, day|None, kind}. None if no date."""
    m = LABEL_RE.search(label)
    if not m:
        return None
    month = MONTHS.index(m.group(1).lower()) + 1
    day = int(m.group(2)) if m.group(2) else None
    year = int(m.group(3))
    kind = "special" if re.search(r"special", label, re.I) else "formal"
    date = f"{year}-{month:02d}-{day:02d}" if day else f"{year}-{month:02d}"
    return {"year": year, "month": month, "day": day, "kind": kind, "meeting_date": date}


def discover(page: str, years=YEARS) -> tuple[list[dict], list[dict]]:
    """-> (minutes in range [{url, label, meeting_date, kind}], skipped [{url, label, reason}]).

    Raises DiscoveryError when the page has no minutes links at all, or none in range."""
    links = parse_index(page)
    if not links:
        raise DiscoveryError(f"no minutes links on {INDEX_URL}: the page may have moved (A4). Not guessing.")
    found, skipped, seen = [], [], set()
    for link in links:
        url = https_same_host(link["url"])
        c = classify(link["label"])
        if c is None:
            skipped.append({**link, "reason": "label has no recognisable date"})
            continue
        if c["year"] not in years:
            continue
        if "minute" not in link["label"].lower():
            skipped.append({**link, "reason": "not labelled as minutes"})
            continue
        if url in seen:
            continue
        seen.add(url)
        found.append({"url": url, "label": link["label"], "meeting_date": c["meeting_date"], "kind": c["kind"]})
    if not found:
        raise DiscoveryError(f"{INDEX_URL} lists no minutes for {years.start}-{years.stop - 1}. Not guessing.")
    found.sort(key=lambda d: (d["meeting_date"], d["url"]))
    return found, skipped


def fetch_index(fetcher) -> str:
    status, body, _ = fetcher.get(INDEX_URL)
    if status != 200:
        raise DiscoveryError(f"{INDEX_URL} answered HTTP {status}: the page may have moved (A4). Not guessing.")
    return body.decode("utf-8", "replace")
