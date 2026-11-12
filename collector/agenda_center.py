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
import string
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime
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
    item_kind_word: re.Pattern    # from item_kinds: group 1 the kind, group 2 a plural s
    not_item_votes: re.Pattern
    vote_lead_in: re.Pattern      # the sentence leading into a vote ("The following vote ... was recorded:")
    vote_asides: re.Pattern       # a sentence about a member's own vote (an abstention note), not about the item
    presiding: re.Pattern
    presiding_title: str
    aliases: dict
    seating: dict | None = None   # {month, every_years, from_year}: when the council is seated (name resolution window)
    # the city's mayor as configured, cited seating entries: ({name, from, to, cite}, ...), dates inclusive (path N3)
    mayors: tuple = ()
    # members seated between full-name attendance lists, each citing an official record of the seating (path N10):
    # ({name, ward, seated, kind, cite_url, cite_page, quote}, ...). The build checks each cite (city_build
    # cited_members) and leaves out any entry whose quote is not on that page of the stored file.
    members: tuple = ()

    def members_on(self, date: str) -> list[dict]:
        """The configured member entries seated on or before date (YYYY-MM-DD), oldest first. Whether one is still
        in its seat is RosterBook's to judge (a later list or entry may give the ward to someone else)."""
        return [m for m in self.members if m["seated"] <= date]

    def mayors_on(self, date: str) -> list[dict]:
        """The configured mayor entries whose term covers date (YYYY-MM-DD): at most one (parse_config refuses an
        overlap)."""
        return [m for m in self.mayors if m["from"] <= date <= m["to"]]

    def seated_on(self, date: str) -> str | None:
        """The latest seating on or before date (YYYY-MM-DD), or None without a seating rule."""
        if not self.seating:
            return None
        s = self.seating
        y0 = s["from_year"] + ((int(date[:4]) - s["from_year"]) // s["every_years"]) * s["every_years"]
        start = f"{y0:04d}-{s['month']:02d}-01"
        return start if start <= date else f"{y0 - s['every_years']:04d}-{s['month']:02d}-01"

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


def _presiding(rx: re.Pattern) -> re.Pattern:
    if not {"title", "name"} <= set(rx.groupindex):
        raise AgendaCenterConfigError("agenda-center.yml: presiding needs groups (?P<title>) and (?P<name>)")
    return rx


def _kinds(kinds: list) -> re.Pattern:
    if not kinds or not all(isinstance(k, str) and re.fullmatch(r"[a-z]+", k) for k in kinds):
        raise AgendaCenterConfigError("agenda-center.yml: item_kinds must be lower-case words")
    return re.compile(r"\b(" + "|".join(kinds) + r")(s)?\b", re.I)


def parse_config(cfg) -> AgendaCenterConfig:
    if not isinstance(cfg, dict):
        raise AgendaCenterConfigError("agenda-center.yml: not a mapping")
    url = _need(cfg, "search_url", str)
    host = _need(cfg, "host", str)
    _template("search_url", url, SEARCH_URL_FIELDS)    # before any .format (agenda-center-search-url-format)
    parts = urllib.parse.urlsplit(url.format(cid=0, year=2000))
    if parts.scheme != "https" or parts.netloc != host:
        raise AgendaCenterConfigError("agenda-center.yml: search_url must be https on host")
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
    # whole printed names only: resolve() reads vote, mover and seconder tokens through the aliases, so a bare surname
    # as a key would re-point every vote printed with that surname (city-votes/alias-in-votes)
    if any(not isinstance(x, str) or len(x.split()) < 2 for kv in aliases.items() for x in kv):
        raise AgendaCenterConfigError("agenda-center.yml: each alias and its target must be a full name")
    seating = cfg.get("seating")
    if seating is not None and not (isinstance(seating, dict) and set(seating) == {"month", "every_years", "from_year"}
                                    and all(type(v) is int for v in seating.values())
                                    and 1 <= seating["month"] <= 12 and seating["every_years"] >= 1):
        raise AgendaCenterConfigError("agenda-center.yml: seating must be {month: 1-12, every_years: 1+, from_year}")
    mayors = _mayors(cfg.get("mayors") or [])
    members = _members(cfg.get("members") or [])
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
        item_kind_word=_kinds(_need(cfg, "item_kinds", list)),
        not_item_votes=_rx(_need(cfg, "not_item_votes", str), "not_item_votes"),
        vote_lead_in=_rx(_need(cfg, "vote_lead_in", str), "vote_lead_in"),
        vote_asides=_rx(_need(cfg, "vote_asides", str), "vote_asides"),
        presiding=_presiding(_rx(_need(cfg, "presiding", str), "presiding", 0)),
        presiding_title=_need(cfg, "presiding_title", str), aliases=dict(aliases),
        seating=dict(seating) if seating else None, mayors=mayors, members=members)


# The listing URL template's fields, all required: a template without {year} would list one year for every year, and
# any other field ({0}, {cid.__class__}, {year!r}, a format spec) is refused before the URL is ever filled.
SEARCH_URL_FIELDS = {"cid", "year"}


def _template(key: str, template: str, fields: set) -> None:
    """A URL template names only `fields`, each bare, and every one of them; literal braces ({{ }}) are text. The same
    whitelist as civicclerk._template (config-validation family). Raises AgendaCenterConfigError."""
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as ex:                                    # an unmatched brace
        raise AgendaCenterConfigError(f"agenda-center.yml: {key} is not a template ({ex})") from None
    seen = set()
    for _, field, spec, conversion in parsed:
        if field is None:
            continue
        if field not in fields or spec or conversion is not None:
            raise AgendaCenterConfigError(f"agenda-center.yml: {key} may name only "
                                          f"{', '.join('{' + f + '}' for f in sorted(fields))}, each bare")
        seen.add(field)
    if fields - seen:
        raise AgendaCenterConfigError(f"agenda-center.yml: {key} needs "
                                      f"{' and '.join('{' + f + '}' for f in sorted(fields - seen))}")


def _iso(v, key: str) -> str:
    """A YAML date (unquoted 2019-01-01 loads as a date) or a quoted ISO date -> 'YYYY-MM-DD'."""
    s = v.isoformat() if isinstance(v, date) and not isinstance(v, datetime) else v
    if not (isinstance(s, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s)):
        raise AgendaCenterConfigError(f"agenda-center.yml: {key} must be a date YYYY-MM-DD")
    return s


def _mayors(raw) -> tuple:
    """mayors: [{name, from, to, cite}]: each a full name, an inclusive term, and the minutes that print the person as
    the city's mayor. Terms may not overlap: two mayors on one date would make the seat a guess."""
    if not isinstance(raw, list):
        raise AgendaCenterConfigError("agenda-center.yml: mayors must be a list")
    out = []
    for i, m in enumerate(raw):
        if not (isinstance(m, dict) and set(m) == {"name", "from", "to", "cite"}):
            raise AgendaCenterConfigError(f"agenda-center.yml: mayors[{i}] must be {{name, from, to, cite}}")
        if not (isinstance(m["name"], str) and len(m["name"].split()) >= 2):
            raise AgendaCenterConfigError(f"agenda-center.yml: mayors[{i}].name must be a full name")
        if not (isinstance(m["cite"], str) and m["cite"].strip()):
            raise AgendaCenterConfigError(f"agenda-center.yml: mayors[{i}].cite must name the minutes it is read from")
        e = {"name": " ".join(m["name"].split()), "from": _iso(m["from"], f"mayors[{i}].from"),
             "to": _iso(m["to"], f"mayors[{i}].to"), "cite": m["cite"].strip()}
        if e["from"] > e["to"]:
            raise AgendaCenterConfigError(f"agenda-center.yml: mayors[{i}]: from is after to")
        out.append(e)
    out.sort(key=lambda e: e["from"])
    for a, b in zip(out, out[1:]):
        if b["from"] <= a["to"]:
            raise AgendaCenterConfigError(f"agenda-center.yml: mayors: {a['name']} and {b['name']} overlap")
    return tuple(out)


MEMBER_KINDS = ("minutes", "resolution", "oath", "roster_page", "certified_results")
MEMBER_KEYS = {"name", "ward", "seated", "kind", "cite_url", "cite_page", "quote"}


def _members(raw) -> tuple:
    """members: [{name, ward, seated, kind, cite_url, cite_page, quote}] (docs/architecture/city-council.md, M1).
    Refused at load: a name that is not a full name as the attendance prints one, a ward outside 1-12, an unknown
    kind, a seated date that is not a date, a cite that is not an https URL with a page and a quote, and two entries
    seating someone in one ward on one date. What needs the stored file (the URL stored, the quote on that page, the
    seated date not before the cited meeting) is the build's check (city_build.cited_members)."""
    from .city_minutes import NAME_RE
    if not isinstance(raw, list):
        raise AgendaCenterConfigError("agenda-center.yml: members must be a list")
    out = []
    for i, m in enumerate(raw):
        where = f"agenda-center.yml: members[{i}]"
        if not (isinstance(m, dict) and set(m) == MEMBER_KEYS):
            raise AgendaCenterConfigError(f"{where} must be {{{', '.join(sorted(MEMBER_KEYS))}}}")
        name = " ".join(str(m["name"]).split()) if isinstance(m["name"], str) else ""
        if not NAME_RE.match(name):
            raise AgendaCenterConfigError(f"{where}.name must be a full name as the attendance prints one")
        if type(m["ward"]) is not int or not 1 <= m["ward"] <= 12:
            raise AgendaCenterConfigError(f"{where}.ward must be 1-12")
        if m["kind"] not in MEMBER_KINDS:
            raise AgendaCenterConfigError(f"{where}.kind must be one of {MEMBER_KINDS}")
        url = m["cite_url"] if isinstance(m["cite_url"], str) else ""
        if urllib.parse.urlsplit(url).scheme != "https" or not urllib.parse.urlsplit(url).netloc:
            raise AgendaCenterConfigError(f"{where}.cite_url must be an https URL")
        if type(m["cite_page"]) is not int or m["cite_page"] < 1:
            raise AgendaCenterConfigError(f"{where}.cite_page must be a page number")
        if not (isinstance(m["quote"], str) and m["quote"].strip()):
            raise AgendaCenterConfigError(f"{where}.quote must be the record's words")
        out.append({"name": name, "ward": m["ward"], "seated": _iso(m["seated"], f"members[{i}].seated"),
                    "kind": m["kind"], "cite_url": url, "cite_page": m["cite_page"],
                    "quote": " ".join(m["quote"].split())})
    out.sort(key=lambda e: (e["seated"], e["ward"]))
    seen = set()
    for e in out:
        if (e["ward"], e["seated"]) in seen:
            raise AgendaCenterConfigError(f"agenda-center.yml: members: two entries seat Ward {e['ward']} on "
                                          f"{e['seated']}")
        seen.add((e["ward"], e["seated"]))
    return tuple(out)


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
