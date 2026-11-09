"""CivicPlus Agenda Center source: list one board's meetings and fetch their agendas and minutes (M4, slice 1).

Everything locality-specific (host, category, years, kind rules, vote labels) comes from
config/localities/<locality>/agenda-center.yml, loaded and checked by load_config(). The listing is the Agenda
Center's own search page, one GET per year limited to the configured category (the category page loads other years
with a POST, which the collector does not send). Requests go through collector.fetch.PoliteFetcher: allowlist,
robots.txt checked before every request, the robots Crawl-delay (10 s here), honest User-Agent, and a 403/429 stops
the host for the run with no retry by another route.

A listing row is shown as printed: its date (from the row's own aria-label), its title, and links to the agenda and,
when posted, the minutes. Rows whose title and date do not parse are reported, never guessed.
"""
from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
VOTE_VALUES = ("yes", "no", "abstain", "other")
# City meeting kinds (schema/facts.schema.json meeting.kind; the county uses formal, informal and special).
CITY_KINDS = ("regular", "special", "executive", "work-session", "public-hearing", "committee", "other")


class AgendaCenterConfigError(Exception):
    pass


class ListingError(Exception):
    """A listing page is not the Agenda Center page we know (moved or changed). Fails loudly; nothing is guessed."""


@dataclass(frozen=True)
class AgendaCenterConfig:
    locality: str
    body: str
    official_title: str
    host: str
    category_id: int
    category_name: str
    search_url: str
    years: tuple            # (first, last) inclusive
    kind_rules: tuple       # ((kind, compiled), ...)
    vote_labels: dict       # LABEL -> value
    absent_labels: tuple
    present_labels: tuple
    note_labels: tuple
    outcome_passed: re.Pattern
    outcome_failed: re.Pattern
    item_number: re.Pattern
    presiding: re.Pattern
    presiding_title: str
    aliases: dict

    def year_range(self) -> range:
        return range(self.years[0], self.years[1] + 1)

    def listing_url(self, year: int) -> str:
        return self.search_url.format(cid=self.category_id, year=year)

    def kind_of(self, title: str) -> str:
        for kind, rx in self.kind_rules:
            if rx.search(title):
                return kind
        return "other"


def config_path(locality: str = "clarksville-tn") -> Path:
    return ROOT / "config" / "localities" / locality / "agenda-center.yml"


def _need(cfg: dict, key: str, kind):
    if key not in cfg:
        raise AgendaCenterConfigError(f"agenda-center.yml: missing key {key}")
    v = cfg[key]
    if not isinstance(v, kind):
        raise AgendaCenterConfigError(f"agenda-center.yml: {key} must be {getattr(kind, '__name__', kind)}")
    return v


def _rx(p, key: str, flags=re.I) -> re.Pattern:
    if not isinstance(p, str):
        raise AgendaCenterConfigError(f"agenda-center.yml: {key} must be a regex string")
    try:
        return re.compile(p, flags)
    except re.error as e:
        raise AgendaCenterConfigError(f"agenda-center.yml: {key}: bad regex {p!r}: {e}") from None


def parse_config(cfg) -> AgendaCenterConfig:
    if not isinstance(cfg, dict):
        raise AgendaCenterConfigError("agenda-center.yml: not a mapping")
    url = _need(cfg, "search_url", str)
    host = _need(cfg, "host", str)
    parts = urllib.parse.urlsplit(url.format(cid=0, year=2000))
    if parts.scheme != "https" or parts.netloc != host:
        raise AgendaCenterConfigError("agenda-center.yml: search_url must be https on host")
    if "{year}" not in url or "{cid}" not in url:
        raise AgendaCenterConfigError("agenda-center.yml: search_url needs {cid} and {year}")
    years = _need(cfg, "years", list)
    if len(years) != 2 or not all(isinstance(y, int) for y in years) or years[0] > years[1]:
        raise AgendaCenterConfigError("agenda-center.yml: years must be [first, last]")
    rules = []
    for i, r in enumerate(_need(cfg, "kind_rules", list)):
        if not (isinstance(r, list) and len(r) == 2 and isinstance(r[0], str)):
            raise AgendaCenterConfigError(f"agenda-center.yml: kind_rules[{i}] must be [kind, regex]")
        if r[0] not in CITY_KINDS:
            raise AgendaCenterConfigError(f"agenda-center.yml: kind_rules[{i}]: kind must be one of {CITY_KINDS}")
        rules.append((r[0], _rx(r[1], f"kind_rules[{i}]")))
    labels = _need(cfg, "vote_labels", dict)
    if not labels or any(v not in VOTE_VALUES for v in labels.values()):
        raise AgendaCenterConfigError(f"agenda-center.yml: vote_labels values must be one of {VOTE_VALUES}")
    aliases = cfg.get("aliases") or {}
    if not isinstance(aliases, dict):
        raise AgendaCenterConfigError("agenda-center.yml: aliases must be a mapping")
    return AgendaCenterConfig(
        locality=_need(cfg, "locality", str), body=_need(cfg, "body", str),
        official_title=_need(cfg, "official_title", str), host=host,
        category_id=_need(cfg, "category_id", int), category_name=_need(cfg, "category_name", str),
        search_url=url, years=(years[0], years[1]), kind_rules=tuple(rules),
        vote_labels={k.upper(): v for k, v in labels.items()},
        absent_labels=tuple(s.upper() for s in _need(cfg, "absent_labels", list)),
        present_labels=tuple(s.upper() for s in _need(cfg, "present_labels", list)),
        note_labels=tuple(s.upper() for s in _need(cfg, "note_labels", list)),
        outcome_passed=_rx(_need(cfg, "outcome_passed", str), "outcome_passed"),
        outcome_failed=_rx(_need(cfg, "outcome_failed", str), "outcome_failed"),
        item_number=_rx(_need(cfg, "item_number", str), "item_number", 0),
        presiding=_rx(_need(cfg, "presiding", str), "presiding", 0),
        presiding_title=_need(cfg, "presiding_title", str), aliases=dict(aliases))


def load_config(path: Path | None = None) -> AgendaCenterConfig:
    p = Path(path) if path else config_path()
    return parse_config(yaml.safe_load(p.read_text(encoding="utf-8")))


# ------------------------------------------------------------------ listing
ROW_RE = re.compile(r'<tr[^>]*class="catAgendaRow"[^>]*>(.*?)</tr>', re.S)
DATE_RE = re.compile(r'aria-label="Agenda for ([A-Z][a-z]+ \d{1,2}, \d{4})"')
TITLE_RE = re.compile(r"<p>(.*?)</p>", re.S)
FILE_RE = re.compile(r'href="(/AgendaCenter/ViewFile/(Agenda|Minutes)/(_\d{8}-\d+))"')
PREV_RE = re.compile(r'href="(/AgendaCenter/PreviousVersions/_\d{8}-\d+)"')
CATEGORY_RE = re.compile(r'<h2[^>]*>\s*([^<]+?)\s*</h2>')


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_listing(page: str, cfg: AgendaCenterConfig, year: int) -> tuple[list[dict], list[dict]]:
    """-> (rows [{date, title, kind, agenda_id, agenda_url, minutes_url, has_previous_versions}], problems).

    Raises ListingError when the page does not carry the configured category heading (the page changed)."""
    heads = [html.unescape(h) for h in CATEGORY_RE.findall(page)]
    rows, problems = [], []
    if cfg.category_name not in heads:
        if ROW_RE.search(page):
            raise ListingError(f"{year}: listing has rows but no '{cfg.category_name}' heading: the page changed")
        return rows, problems                      # a year with no meetings has no table at all
    base = f"https://{cfg.host}"
    for raw in ROW_RE.findall(page):
        dm, tm = DATE_RE.search(raw), TITLE_RE.search(raw)
        files = {kind: (path, aid) for path, kind, aid in FILE_RE.findall(raw)}
        if not dm or not tm or "Agenda" not in files:
            problems.append({"year": year, "problem": "row without a date, title or agenda link",
                             "snippet": _text(raw)[:160]})
            continue
        date = datetime.strptime(dm.group(1), "%B %d, %Y").date().isoformat()
        title = _text(tm.group(1))
        agenda_path, agenda_id = files["Agenda"]
        minutes = files.get("Minutes")
        rows.append({
            "date": date, "title": title, "kind": cfg.kind_of(title), "agenda_id": agenda_id.lstrip("_"),
            "agenda_url": base + agenda_path, "minutes_url": base + minutes[0] if minutes else None,
            "has_previous_versions": bool(PREV_RE.search(raw)),
        })
        if not date.startswith(str(year)):
            problems.append({"year": year, "problem": f"row dated {date} on the {year} listing",
                             "snippet": title})
    return rows, problems


def discover(fetcher, cfg: AgendaCenterConfig, log: dict, previous: list[dict] | None = None) -> list[dict]:
    """GET each year's listing (politely), return every row once, oldest first. Listing pages are not stored as
    sources: the facts cite each agenda or minutes file, and the listing's URL is kept in the run log.

    A year whose listing fails with a network error (FetchFailed) keeps that year's rows from `previous` (the last
    listing.json) and is logged under listing_failures; a refusal (403/429, robots, denied host) propagates and
    stops the run. A page that changed shape raises ListingError."""
    from .fetch import FetchFailed
    seen, out = set(), []
    for year in cfg.year_range():
        url = cfg.listing_url(year)
        try:
            status, body, _ = fetcher.get(url)
        except FetchFailed as e:
            kept = [r for r in previous or [] if r["date"].startswith(str(year))]
            log.setdefault("listing_failures", []).append({"year": year, "url": url, "error": str(e),
                                                           "kept_previous_rows": len(kept)})
            rows = kept
        else:
            if status != 200:
                raise ListingError(f"{url} answered HTTP {status}: the page may have moved. Not guessing.")
            rows, problems = parse_listing(body.decode("utf-8", "replace"), cfg, year)
            log.setdefault("listing_problems", []).extend(problems)
        log.setdefault("listings", []).append({"year": year, "url": url, "rows": len(rows)})
        for r in rows:
            if r["agenda_id"] in seen:
                continue
            seen.add(r["agenda_id"])
            out.append(r)
    out.sort(key=lambda r: (r["date"], r["agenda_id"]))
    return out
