"""County Commission agendas from the commission's agenda page (docs/research/county-recency.md, Fix 2).

The county posts a meeting's minutes months after the meeting (the clerk's page had nothing after May 2026 on
2026-11-10), but posts each agenda before the meeting on https://montgomerytn.gov/commission/agenda. This adapter
reads that page so the site can show the meetings the minutes do not cover yet, as agenda-only meetings.

Rules:
- one GET of the agenda page per run. Every PDF URL is taken from the page as printed, resolved against the page URL
  (some links are relative), nothing else; no URL is ever built or guessed, and no search form is ever sent (the BIS
  Online search is not used: decision recorded 2026-11-10);
- requests go through collector.fetch.PoliteFetcher: allowlist, robots.txt before every request, at least 10 s between
  requests per host, our honest User-Agent, a 403/429 stops the host for the run;
- only links for months on or after the month of the newest county minutes we hold, and no later than next month, are
  requested (the page lists every agenda back to 2006). A link to a host outside collector.fetch.ALLOWED_HOSTS (or on
  its denied list) is skipped with the reason and never requested;
- a stored agenda is requested again, once per run, until its meeting date has passed: the county may replace the PDF
  at the same URL (a revised agenda). New bytes are a new store version (the old one stays as its own source); the
  same bytes change nothing. The request is a plain GET through the same fetcher (PoliteFetcher sends no conditional
  headers). After the meeting date a stored agenda is never requested again;
- the county keeps placeholder files at the links of meetings it has not posted yet (dec-formal.pdf was a 6 KB file
  dated 2026-04-02). A file under PLACEHOLDER_BYTES, or last modified more than PLACEHOLDER_DAYS before the first day of
  the month it is listed under, is not stored: it is recorded in `skipped` with the reason and asked for again on a
  later run, when the real agenda may be there;
- the meeting date and kind (formal, informal, special) are read from the PDF's own first pages, never from the link
  or a weekday pattern. An agenda whose text gives no date is kept as a source and reported, and shows no meeting.

Files (the county's minutes manifest and facts are never touched):
- data/county-agendas/manifest.json   one entry per stored agenda (committed), bytes in the gitignored store
- data/county-agendas/agendas.json    the agenda-only meetings, their sources, items and the skipped links
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from .fetch import (ALLOWED_HOSTS, DENIED_HOSTS, FetchFailed, HostBlocked, HostRefused, PoliteFetcher, ProxyRefused,
                    RobotsDisallowed, _host_matches)
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
INDEX_URL = "https://montgomerytn.gov/commission/agenda"
DIR = ROOT / "data" / "county-agendas"
MANIFEST = DIR / "manifest.json"
AGENDAS = DIR / "agendas.json"
FACTS = ROOT / "data" / "facts.json"
STOP = (HostBlocked, HostRefused, ProxyRefused, RobotsDisallowed)   # the host said no (or policy): stop the run
PLACEHOLDER_BYTES = 100_000      # every real agenda seen was 6 to 19 MB; the placeholder was 6 KB
PLACEHOLDER_DAYS = 45            # real agendas were last modified in their month or the days before it
MONTHS = ("january february march april may june july august september october november december").split()
KINDS = {"informal": "informal", "formal": "formal", "special": "special", "view special agenda": "special"}


class AgendaPageError(Exception):
    """The agenda page is not the page we know (moved, rebuilt, or no agenda links). Nothing is guessed."""


# ------------------------------------------------------------------ the agenda page
class _Links(HTMLParser):
    """Each <a href> with the text of the last <h3> before it (the year section) and the text of its table cell up to
    the link (the month, or 'April 1 Special Called Agenda')."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[dict] = []
        self.h3 = ""
        self._in_h3 = False
        self._h3_buf: list[str] = []
        self._cell: list[str] = []
        self._a: dict | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "h3":
            self._in_h3, self._h3_buf = True, []
        elif tag in ("th", "td"):
            self._cell = []
        elif tag == "a":
            self._a = {"href": dict(attrs).get("href") or "", "text": [], "cell": " ".join(self._cell)}

    def handle_endtag(self, tag):
        if tag == "h3" and self._in_h3:
            self._in_h3 = False
            self.h3 = _clean(" ".join(self._h3_buf))
        elif tag == "a" and self._a is not None:
            self.links.append({"href": self._a["href"], "text": _clean(" ".join(self._a["text"])),
                               "cell": _clean(self._a["cell"]), "section": self.h3})
            self._a = None

    def handle_data(self, data):
        if self._in_h3:
            self._h3_buf.append(data)
        if self._a is not None:
            self._a["text"].append(data)
        else:
            self._cell.append(data)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


def allowed_url(url: str) -> bool:
    """An https URL on a host the fetcher may ask (ALLOWED_HOSTS, not DENIED_HOSTS). Only such a URL is ever kept in a
    skipped entry, so agendas.json (committed, and possibly shown later) never carries a javascript:, http: or
    off-allowlist link as printed on the county's page (agenda-data/unvalidated-skipped-urls)."""
    parts = urllib.parse.urlsplit(url or "")
    host = parts.hostname or ""
    return (parts.scheme == "https" and bool(host) and _host_matches(host, ALLOWED_HOSTS)
            and not _host_matches(host, DENIED_HOSTS))


def _skip(url: str, label: str, reason: str) -> dict:
    """A skipped link; its URL is kept only when allowed_url says so, otherwise None (the reason says why)."""
    return {"url": url if allowed_url(url) else None, "label": label, "reason": reason}


def parse_index(page: str, base: str = INDEX_URL) -> tuple[list[dict], list[dict]]:
    """-> (agenda links [{url, label, year, month, kind}], skipped [{url, label, reason}]) in page order.

    A link counts as an agenda when its text is Informal, Formal, Special or View Special Agenda and it sits under a
    year heading. Its year comes from that heading and its month from the cell's own words ('January', 'April 1
    Special Called Agenda'); a link whose month or year the page does not print is skipped with the reason."""
    p = _Links()
    p.feed(page)
    found, skipped, seen = [], [], set()
    for a in p.links:
        kind = KINDS.get(a["text"].lower())
        if kind is None:
            continue                                     # a form, a calendar, a Comprehensive Plan link: not agendas
        url = urllib.parse.urljoin(base, html.unescape(a["href"]).strip())
        label = f"{a['cell'].split('(')[0].strip()} {a['text']}".strip()
        y = re.match(r"((?:19|20)\d\d)\b", a["section"])
        mo = re.match(r"(" + "|".join(MONTHS) + r")\b", a["cell"], re.I)
        if not y or not mo:
            skipped.append(_skip(url, label, "the page prints no year or month for this link"))
            continue
        if urllib.parse.urlsplit(url).scheme != "https" or not urllib.parse.urlsplit(url).path.lower().endswith(".pdf"):
            skipped.append(_skip(url, label, "not an https PDF link"))
            continue
        if not allowed_url(url):
            # one off-allowlist link must not reach the fetcher (agenda-fetch/hostrefused-stops-run)
            skipped.append(_skip(url, label, "a host this site does not collect from"))
            continue
        if url in seen:
            continue
        seen.add(url)
        found.append({"url": url, "label": f"{y.group(1)} {label}", "year": int(y.group(1)),
                      "month": MONTHS.index(mo.group(1).lower()) + 1, "kind": kind})
    if not found:
        raise AgendaPageError(f"no agenda links on {INDEX_URL}: the page may have moved. Not guessing.")
    return found, skipped


def fetch_index(f: PoliteFetcher) -> str:
    status, body, _ = f.get(INDEX_URL)
    if status != 200:
        raise AgendaPageError(f"{INDEX_URL} answered HTTP {status}: the page may have moved. Not guessing.")
    return body.decode("utf-8", "replace")


def _month_index(y: int, m: int) -> int:
    return y * 12 + m - 1


def minutes_month(facts_path: Path = FACTS) -> tuple[int, int] | None:
    """(year, month) of the newest county meeting the minutes cover, or None when there are no facts."""
    p = Path(facts_path)
    if not p.is_file():
        return None
    dates = [m["date"] for m in json.loads(p.read_text(encoding="utf-8")).get("meetings", []) if m.get("date")]
    if not dates:
        return None
    d = max(dates)
    return int(d[:4]), int(d[5:7])


def wanted(links: list[dict], since: tuple[int, int] | None, today: date) -> list[dict]:
    """The links to look at this run: months from `since` (the newest minutes) to next month. Without minutes, the
    current and next month only, so a first run never walks the archive back to 2006."""
    hi = _month_index(today.year, today.month) + 1
    lo = _month_index(*since) if since else hi - 1
    return [x for x in links if lo <= _month_index(x["year"], x["month"]) <= hi]


def placeholder_reason(body: bytes, headers: dict, year: int, month: int) -> str | None:
    """Why a downloaded file is not a real agenda yet, or None."""
    if len(body) < PLACEHOLDER_BYTES:
        return f"placeholder: {len(body):,} bytes (a real agenda is over {PLACEHOLDER_BYTES:,})"
    lm = next((v for k, v in (headers or {}).items() if k.lower() == "last-modified"), None)
    if lm:
        try:
            when = parsedate_to_datetime(lm).date()
        except (TypeError, ValueError):
            when = None
        if when and when < date(year, month, 1) - timedelta(days=PLACEHOLDER_DAYS):
            return f"placeholder: last modified {when.isoformat()}, long before {MONTHS[month - 1].title()} {year}"
    return None


def _last_day(y: int, m: int) -> date:
    return date(y + m // 12, m % 12 + 1, 1) - timedelta(days=1)


def meeting_dates(agendas_path: Path | None) -> dict[str, str]:
    """url -> the latest meeting date its stored agenda printed (the last agendas.json), for the re-request rule."""
    p = Path(agendas_path or AGENDAS)
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    url_of = {s["id"]: s["url"] for s in data.get("sources", [])}
    out: dict[str, str] = {}
    for m in data.get("meetings", []):
        u = url_of.get(m.get("source_id"))
        if u and m.get("date"):
            out[u] = max(out.get(u, ""), m["date"])
    return out


def recheck_due(x: dict, dates: dict[str, str], today: date) -> bool:
    """A stored agenda is asked for again while its meeting date has not passed (provenance/agenda-revised-in-place):
    the date the agenda printed when known, else the last day of the month the page lists it under."""
    when = dates.get(x["url"]) or _last_day(x["year"], x["month"]).isoformat()
    return today.isoformat() <= when


def cmd_fetch(store: Store, log: dict, fetcher: PoliteFetcher | None = None, today: date | None = None,
              facts_path: Path = FACTS, agendas_path: Path | None = None) -> list[dict]:
    """One GET of the agenda page, then each wanted agenda not in the store yet, and once each stored agenda whose
    meeting date has not passed (a revision). Returns the skipped links."""
    f = fetcher or PoliteFetcher()
    today = today or datetime.now(timezone.utc).date()
    log.setdefault("failures", [])
    log.setdefault("fetched", {})
    try:
        links, unread = parse_index(fetch_index(f))
    except (AgendaPageError, FetchFailed) + STOP as e:
        log["failures"].append({"stage": "agenda_page", "error": f"{type(e).__name__}: {e}"})
        return []
    todo = wanted(links, minutes_month(facts_path), today)
    # an agenda stored earlier whose bytes this store lacks (an evicted cache) is fetched again even after its month
    # left the window, so the committed file can be rebuilt; still only a URL the page lists
    lacking = {e["url"] for e in store.current() if not store.has_bytes(e["sha256"])}
    todo += [x for x in links if x["url"] in lacking and x not in todo]
    log["listed"], log["unread_links"], log["wanted"] = len(links), len(unread), len(todo)
    skipped: list[dict] = []
    dates = meeting_dates(agendas_path)
    asked: set[str] = set()                              # each URL at most once per run
    for x in todo:
        if x["url"] in asked:
            continue
        known = store.latest(x["url"])
        recheck = bool(known and store.has_bytes(known["sha256"]))
        if recheck and not recheck_due(x, dates, today):
            log["fetched"]["cached"] = log["fetched"].get("cached", 0) + 1
            continue
        asked.add(x["url"])
        try:
            status, body, headers = f.get(x["url"])
        except STOP as e:
            log["failures"].append({"stage": "agenda_fetch", "url": x["url"], "error": f"{type(e).__name__}: {e}"})
            if isinstance(e, HostBlocked):
                break                                    # the site said 403/429: stop asking it for this run
            if isinstance(e, HostRefused):
                # our own policy refused this one link (off the allowlist, e.g. after a redirect): skip it and go on
                skipped.append(_skip(x["url"], x["label"], f"refused by the fetcher's host policy: {e}"))
            continue
        except FetchFailed as e:
            log["failures"].append({"stage": "agenda_fetch", "url": x["url"], "error": f"{type(e).__name__}: {e}"})
            continue
        if recheck and (status != 200 or body[:4] != b"%PDF"
                        or placeholder_reason(body, headers, x["year"], x["month"])):
            # the stored agenda stays as it is; a server error is still a failure the run reports
            if status not in (200, 404):
                log["failures"].append({"stage": "agenda_fetch", "url": x["url"], "error": f"HTTP {status}"})
            log["fetched"]["kept"] = log["fetched"].get("kept", 0) + 1
            continue
        if status == 404:
            skipped.append({"url": x["url"], "label": x["label"], "reason": "not found (HTTP 404)"})
            continue
        if status != 200:
            log["failures"].append({"stage": "agenda_fetch", "url": x["url"], "error": f"HTTP {status}"})
            continue
        if body[:4] != b"%PDF":
            skipped.append({"url": x["url"], "label": x["label"], "reason": "not a PDF"})
            continue
        why = placeholder_reason(body, headers, x["year"], x["month"])
        if why:
            skipped.append({"url": x["url"], "label": x["label"], "reason": why})
            continue
        _, st = store.put(x["url"], body, headers, {"kind": f"agenda_{x['kind']}",
                                                    "meeting_date": f"{x['year']}-{x['month']:02d}",
                                                    "label": x["label"]})
        log["fetched"][st] = log["fetched"].get(st, 0) + 1
        store.save()                                     # saved as it goes, so a stopped run keeps what it fetched
    store.save()
    log["skipped"] = skipped
    return skipped


# ------------------------------------------------------------------ reading an agenda
LIST_PAGES = 6                   # the agenda list is on its first pages; the rest of the PDF is the resolutions' text
DATE_RX = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})\s*,\s*((?:19|20)\d\d)\b", re.I)
# An item as the agenda prints it: a resolution number "26-11-1*" or a case number "CZ-12-2026", "CZO-1-2026",
# "AB-1-2026", then its title (the patterns of collector.parse.NUMBER_PATTERNS). "*" is kept as printed.
ITEM_RX = re.compile(r"^(\s*)(\d{2}-\d{1,2}-\d{1,3}|[A-Z]{1,4}-\d{1,3}-(?:19|20)\d\d)(\*?)\s+(\S.*?)\s*$")
# A section heading ("RESOLUTIONS REMOVED FROM CONSENT", "RESOLUTIONS ADDED AFTER BUDGET COMMITTEE ( Must Suspend the
# Rules)"): capitals from the left margin, with an optional bracketed note.
HEADING_RX = re.compile(r"^\s{0,3}([A-Z][A-Z0-9&/,'’\- ]*[A-Z])\s*(\([^)]*\))?\s*:?\s*$")
END_RX = re.compile(r"^\s*ADJOURN\b")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def first_pages(pdf: Path, n: int = LIST_PAGES) -> list[str]:
    import subprocess
    from .extract import PARSE_TIMEOUT
    out = subprocess.run(["pdftotext", "-f", "1", "-l", str(n), "-layout", "-enc", "UTF-8", str(pdf), "-"],
                         check=True, capture_output=True, timeout=PARSE_TIMEOUT).stdout.decode("utf-8", "replace")
    pages = out.split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages


def header(pages: list[str]) -> dict:
    """The meeting date and kind as the agenda's first page prints them: the lines before CALL TO ORDER (at most 8).
    {date, kind, line}; date or kind None when the page does not print it."""
    lines = [ln.strip() for ln in (pages[0] if pages else "").splitlines() if ln.strip()]
    head = []
    for ln in lines[:8]:
        if re.match(r"CALL TO ORDER\b", ln, re.I):
            break
        head.append(ln)
    text = " ".join(head)
    when = None
    m = DATE_RX.search(text)
    if m:
        try:
            when = date(int(m.group(3)), MONTHS.index(m.group(1).lower()) + 1, int(m.group(2))).isoformat()
        except ValueError:
            when = None
    up = text.upper()
    kind = ("special" if "SPECIAL" in up else "informal" if "INFORMAL" in up
            else "formal" if "BOARD OF COMMISSIONERS" in up or "FORMAL" in up else None)
    return {"date": when, "kind": kind, "line": re.sub(r"\s+", " ", text)[:200]}


def items(pages: list[str]) -> tuple[list[dict], bool]:
    """(items in agenda order, end_found). Each item: {number, printed, title, section, page}, every value the
    agenda's own words with whitespace joined. Reading stops at ADJOURN; without it (end_found False) nothing is read,
    since the list's end is not known."""
    out: list[dict] = []
    section = None
    cur = None
    for pno, page in enumerate(pages, 1):
        for raw in page.splitlines():
            ln = CONTROL.sub("", raw).rstrip()
            if END_RX.match(ln):
                return out, True
            m = ITEM_RX.match(ln)
            if m:
                cur = {"number": m.group(2), "printed": m.group(2) + m.group(3), "title": m.group(4),
                       "section": section, "page": pno, "_col": m.start(4)}
                out.append(cur)
                continue
            if not ln.strip():
                cur = None
                continue
            h = HEADING_RX.match(ln)
            if h:
                section = re.sub(r"\s+", " ", ln.strip().rstrip(":")).strip()
                cur = None
                continue
            indent = len(ln) - len(ln.lstrip())
            if cur is not None and indent >= cur["_col"] - 4:
                # a word broken at a line end ("Full-" / "Time") is joined as printed, without the line break
                sep = "" if re.search(r"[A-Za-z]-$", cur["title"]) else " "
                cur["title"] = f"{cur['title']}{sep}{ln.strip()}"
            else:
                cur = None
    return [], False


def source_record(e: dict, pages: int | None) -> dict:
    return {"id": f"src-{e['sha256'][:12]}", "url": e["url"], "sha256": e["sha256"], "kind": "agenda",
            "label": e.get("label"), "fetched_at": (e.get("first_fetched_at") or "")[:10], "pages": pages}


def build(store: Store, skipped: list[dict] | None, read=first_pages, page_count=None,
          agendas_path: Path | None = None) -> tuple[dict, dict]:
    """(agendas, summary) from the stored agendas. Meetings are keyed <date>-<kind> like the minutes' meetings, so a
    page can tell which ones the minutes already cover. `skipped` None keeps the skipped links of the last file."""
    from .rpc_agenda import pdf_page_count
    page_count = page_count or pdf_page_count
    agendas_path = Path(agendas_path or AGENDAS)
    sources, meetings, problems = [], {}, []
    seen: set[str] = set()
    for e in sorted(store.current(), key=lambda e: (e.get("meeting_date") or "", e["url"])):
        if e["sha256"] in seen:
            continue
        seen.add(e["sha256"])
        if not store.has_bytes(e["sha256"]):
            problems.append({"url": e["url"], "problem": "not in the store (run without --offline)"})
            continue
        p = store.path_for(e["sha256"])
        try:
            pages = read(p)
        except Exception as ex:          # one bad document must not stop the run; it is reported
            problems.append({"url": e["url"], "problem": f"text not read: {type(ex).__name__}: {ex}"})
            continue
        n_pages = page_count(p)
        if not n_pages:
            # no page count (pdfinfo failed): every item link cites a page, so the meeting is left out and reported
            # (agenda-data/pages-none)
            problems.append({"url": e["url"], "problem": "no page count (pdfinfo); meeting left out"})
            continue
        src = source_record(e, n_pages)
        sources.append(src)
        h = header(pages)
        if not h["date"] or not h["kind"]:
            problems.append({"url": e["url"], "problem": f"no meeting date or kind on the first page: {h['line']!r}"})
            continue
        listed_kind = (e.get("kind") or "").removeprefix("agenda_")
        if listed_kind and listed_kind != h["kind"]:
            problems.append({"url": e["url"], "problem": f"listed as {listed_kind}, the agenda prints {h['kind']}"})
        found, end = items(pages)
        if not end:
            problems.append({"url": e["url"], "problem": f"the agenda list's end (ADJOURN) is not in the first "
                                                         f"{LIST_PAGES} pages; items not read"})
        mid = f"{h['date']}-{h['kind']}"
        if mid in meetings:
            problems.append({"url": e["url"], "problem": f"a second agenda for {mid}; the later one is kept"})
        meetings[mid] = {
            "id": mid, "date": h["date"], "kind": h["kind"], "source_id": src["id"], "date_page": 1,
            "items": [{"id": f"{mid}/{x['number']}", "number": x["number"], "printed": x["printed"],
                       "title": re.sub(r"\s+", " ", x["title"]).strip(), "section": x["section"], "page": x["page"],
                       "year": int(h["date"][:4]), "link_basis": "number"} for x in found],
        }
    if skipped is None:
        skipped = (json.loads(agendas_path.read_text(encoding="utf-8")).get("skipped", [])
                   if agendas_path.is_file() else [])
    # skipped URLs are https on allowlisted hosts only (allowed_url), also for a file written before that rule
    skipped = [{**s, "url": s.get("url") if allowed_url(s.get("url") or "") else None} for s in skipped]
    out = {"body": "Montgomery County Commission", "index_url": INDEX_URL,
           "meetings": sorted(meetings.values(), key=lambda m: (m["date"], m["id"])),
           "sources": sorted(sources, key=lambda s: s["id"]), "skipped": skipped, "problems": problems}
    summary = {"agendas": len(sources), "meetings": len(meetings),
               "items": sum(len(m["items"]) for m in meetings.values()), "skipped": len(skipped),
               "problems": problems}
    return out, summary


def write_if_changed(p: Path, obj) -> bool:
    text = json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    if p.is_file() and p.read_text(encoding="utf-8") == text:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return True


def run_step(log: dict, offline: bool, fetcher: PoliteFetcher | None = None, agendas_path: Path | None = None,
             manifest_path: Path | None = None, today: date | None = None) -> dict:
    """The daily step (collector run): fetch (unless offline) then build data/county-agendas/agendas.json.
    Fetch failures go to log['failures'] (stage agenda_*), so the run exits 2 like any fetch failure."""
    agendas_path = Path(agendas_path or AGENDAS)
    store = Store(manifest_path or MANIFEST)
    alog: dict = {"failures": [], "fetched": {}}
    skipped = None
    if not offline:
        skipped = cmd_fetch(store, alog, fetcher=fetcher, today=today, agendas_path=agendas_path)
        if any(f["stage"] == "agenda_page" for f in alog["failures"]):
            skipped = None                               # the page was not read: keep the last known skips
    out, summary = build(store, skipped, agendas_path=agendas_path)
    gone = [p for p in summary["problems"] if "not in the store" in p["problem"]]
    if gone and agendas_path.is_file():
        # an empty or partial store (a fresh checkout, an evicted cache) must not shrink the committed file
        # (provenance/offline-run-overwrites-facts); the agendas are fetched again on the next online run
        alog["kept"] = f"{agendas_path.name} left unchanged: {len(gone)} stored agendas are not in the store"
        print(f"collector: county agendas: {alog['kept']}", flush=True)
    else:
        write_if_changed(agendas_path, out)
    log.setdefault("failures", []).extend(alog.pop("failures"))
    log["county_agendas"] = {**alog, "build": summary}
    print(f"collector: county agendas: {summary['agendas']} stored, {summary['meetings']} meetings, "
          f"{summary['items']} items, {summary['skipped']} links skipped, {len(summary['problems'])} problems",
          flush=True)
    return summary
