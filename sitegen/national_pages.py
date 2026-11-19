"""Daylight Digest, the page builder (docs/architecture/daylight-national.md 1a, 3.4, 3.5, 4.0, 4.3, 6, 7a, 11; task
B4): with config/site.yml `national.enabled: true` the build writes, under `digest/`,

- `index.html`      the entry page: the address card, the embedded page directory (`#digest-pagedir`, 3.4), the
                    lookup's fixed words (`#digest-strings`) and settings (`#digest-config`, with the two outside
                    links of config/national/links.yml), and the empty mount points the page wiring (task F2)
                    draws into. Its own CSP (section 6): script-src 'self', frame-src 'self', the email service in
                    form-action and connect-src, the counter's origin while analytics is on.
- `covered.html`    What we cover: covered and can't-cover governments by state, then name. Static, no script.
- `requested.html`  the request-confirmed page. Static.
- `how.html`        How Daylight Digest works: what the page keeps on a device, what the request and the count send.
                    Static; its page-visits paragraph prints only while the visit counter is on.
- `geo-frame.html`  the Census frame, exactly `national.geo_frame_html()` (its own meta CSP, 4.0).
- `<st>/<body id>.html` and `.json` per covered government: the coming-up page, printed from the JSON only (consumer 3
                    of section 11), and its `daylight-upcoming/1` feed (3.5), checked against the schema again here.

and `apply_site_fragments` adds the two fixed fragments to the pages that already exist (7a): the Menu group
"Daylight Digest" in the footer list of every page, and the one front-page line under the address card. Nothing else
in an existing page changes; with the switch off this module is not called and the build is byte-identical.

Every digest page but the frame also links `static/digest.css` (design 0a), the digest pages' own stylesheet: no
other page links it, and like the two digest scripts it is copied into the build only while the switch is on.

Every fixed word on a digest page comes from config/national/page-labels.yml (or labels.yml's card labels); every
other word is source text from the directory or a feed (AC4.5, AC4.8). Labels mark their one link as `[text]` and
their data as `{name}`; `label_html` escapes both.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import yaml
from markupsafe import Markup, escape

from . import config, localdates, morning_page
from . import national as nat
from . import national_clarksville as ncl
from .national_guards import BAD_TEXT_RE, BindCounts, BindError, GuardCounts, allowed_url, bind_feed, link_or_official
from .views import CSP_BASE

FOLDER = "digest"
PAGE_LABELS_PATH = nat.NATIONAL_DIR / "page-labels.yml"
PAGE_LABELS_SCHEMA = "daylight-pagelabels/1"

INDEX = f"{FOLDER}/index.html"
COVERED = f"{FOLDER}/covered.html"
REQUESTED = f"{FOLDER}/requested.html"
HOW = f"{FOLDER}/how.html"
FRAME = nat.GEO_FRAME_PAGE                         # digest/geo-frame.html
# site/static files only the digest pages use: copied into the build only while the switch is on (7a (d))
STATIC_ONLY = ("national.js", "us-count.js", "digest.css")
# The outside links the lookup's script prints (design section 3, "Outside links"): settings, never label text.
LINKS_PATH = nat.NATIONAL_DIR / "links.yml"
LINKS_SCHEMA = "daylight-links/1"
LINK_KEYS = ("election_url", "census_url")


# Page label keys: a group and a name, or a state's USPS code, or a time zone name.
PAGE_LABEL_KEY_RE = re.compile(
    r"^((digest|menu|front|crumb|index|lookup|form|count|covered|requested|how|body)\.[a-z0-9][a-z0-9-]*"
    r"|state\.[A-Z]{2}|tz\.[A-Za-z_]+(/[A-Za-z_+-]+){0,2})$")
SCRIPT_GROUPS = ("lookup.", "form.", "count.")      # embedded in digest/index.html for national.js (F2)
# The keys the templates and this module read (the script groups are F2's and are checked by F2's tests).
REQUIRED_PAGE_LABELS = (
    "digest.place", "menu.group", "menu.find", "menu.covered", "front.line", "crumb.home", "crumb.covered",
    "index.title", "index.h1", "index.lede", "index.who", "index.cover-link", "index.input-label",
    "index.placeholder", "index.find", "index.privacy", "index.privacy-detail", "index.toggle-summary",
    "index.toggle-body", "index.census-notice", "index.noscript",
    "covered.title", "covered.h1", "covered.count", "covered.count-one", "covered.how", "covered.lookup",
    "covered.h-covered", "covered.h-cant", "covered.row-link", "covered.checked", "covered.official",
    "covered.empty-cant", "covered.closing",
    "requested.title", "requested.h1", "requested.body", "requested.cant", "requested.back",
    "index.how-link", "covered.how-link",
    "how.title", "how.h1", "how.address", "how.device-intro", "how.key-list", "how.key-requested",
    "how.key-counted", "how.device-after", "how.requests", "how.requests-2", "how.count", "how.count-2", "how.visits", "how.back",
    "body.title", "body.eyebrow", "body.coming-up", "body.official-record", "body.newest", "body.no-records",
    "body.no-time", "body.tz", "body.as-posted", "body.agenda", "body.agenda-for",
    "body.not-posted", "body.incomplete", "body.withheld", "body.cut", "body.item-page", "body.no-meetings",
    "body.full", "body.morning")

LINK_RE = re.compile(r"\[([^\[\]]+)\]")
FIELD_RE = re.compile(r"\{([a-z]+)\}")

# The two fragments added to existing pages (7a (b), (c)): fixed text but for the page's own `root` prefix.
MENU_ANCHOR = "    </ul>\n  </nav>\n</footer>"
MENU_ROOT_RE = re.compile(r'<nav id="site-nav" class="site-nav" aria-label="All pages" data-root="((?:\.\./)*)"')
FRONT_PAGE = "index.html"
FRONT_START = '<section class="find" aria-labelledby="find-h">'
SECTION_TAG_RE = re.compile(r"<section\b|</section>")


class NationalBuildError(ValueError):
    """The national pages cannot be built as the contract says: the build stops."""


# --- the switch -----------------------------------------------------------------------------------------------------

def enabled(cfg: Mapping | None = None) -> bool:
    """config/site.yml `national: {enabled: true|false}`. Absent: off. Anything but a true/false `enabled` (or another
    key) stops the build, so a typo never turns the pages on or off silently."""
    cfg = config.SITE if cfg is None else cfg
    block = cfg.get("national")
    if block is None:
        return False
    if not isinstance(block, dict) or set(block) != {"enabled"} or not isinstance(block["enabled"], bool):
        raise NationalBuildError("config/site.yml national: must be {enabled: true} or {enabled: false}")
    return block["enabled"]


def static_ignore(on: bool):
    """The `ignore` for the build's copy of site/static: the digest-only scripts and stylesheet stay out while the
    switch is off."""
    def ignore(_dir, names):
        return [] if on else [n for n in names if n in STATIC_ONLY]
    return ignore


# --- page labels ------------------------------------------------------------------------------------------------------

def load_page_labels(path: Path = PAGE_LABELS_PATH) -> dict[str, str]:
    """page-labels.yml -> {key: text}; refuses an unknown key form, empty text, control or bidi characters, more than
    one link mark, a field name the builder does not fill, or a missing required key."""
    path = Path(path)
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise NationalBuildError(f"{path}: cannot read: {e}") from e
    if not isinstance(doc, dict) or doc.get("schema") != PAGE_LABELS_SCHEMA or set(doc) - {"schema", "labels"}:
        raise NationalBuildError(f"{path}: must be {{schema: {PAGE_LABELS_SCHEMA}, labels: {{...}}}}")
    labels = doc.get("labels")
    if not isinstance(labels, dict) or not labels:
        raise NationalBuildError(f"{path}: labels: must be a mapping of label keys to text")
    out = {}
    for k, v in labels.items():
        if not isinstance(k, str) or not PAGE_LABEL_KEY_RE.fullmatch(k):
            raise NationalBuildError(f"{path}: labels: {k}: bad label key")
        if not isinstance(v, str) or not v.strip() or len(v) > 600 or BAD_TEXT_RE.search(v):
            raise NationalBuildError(f"{path}: labels: {k}: must be text of at most 600 characters with no control "
                                     "or bidi characters")
        if len(LINK_RE.findall(v)) > 1 or v.count("[") != v.count("]"):
            raise NationalBuildError(f"{path}: labels: {k}: at most one [link] mark")
        out[k] = v
    missing = [k for k in REQUIRED_PAGE_LABELS if k not in out]
    if missing:
        raise NationalBuildError(f"{path}: labels: {missing[0]}: missing")
    return out


# --- outside links ----------------------------------------------------------------------------------------------------

def load_links(path: Path = LINKS_PATH) -> dict[str, str | None]:
    """links.yml -> {election_url, census_url}, each an https URL or None. A key left out is None, and the script
    then leaves that line out whole; an unknown key, or a value that is not a plain https URL (national_guards.
    allowed_url: no user name, password or odd port), stops the build, so a typo never drops a line silently."""
    path = Path(path)
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise NationalBuildError(f"{path}: cannot read: {e}") from e
    if not isinstance(doc, dict) or doc.get("schema") != LINKS_SCHEMA or set(doc) - {"schema", "links"}:
        raise NationalBuildError(f"{path}: must be {{schema: {LINKS_SCHEMA}, links: {{...}}}}")
    links = doc.get("links")
    if not isinstance(links, dict) or set(links) - set(LINK_KEYS):
        raise NationalBuildError(f"{path}: links: must be a mapping with only the keys {', '.join(LINK_KEYS)}")
    out: dict[str, str | None] = {}
    for k in LINK_KEYS:
        v = links.get(k)
        if v is not None and not allowed_url(v):
            raise NationalBuildError(f"{path}: links: {k}: must be an https URL")
        out[k] = v
    return out


def _fill(text: str, values: Mapping[str, object]) -> str:
    def one(m):
        if m.group(1) not in values:
            raise NationalBuildError(f"label {text!r}: no value for {{{m.group(1)}}}")
        return str(values[m.group(1)])
    return FIELD_RE.sub(one, text)


def label_text(text: str, **values) -> str:
    """A label as plain text: its link mark dropped, its fields filled (for titles and for tests)."""
    return _fill(LINK_RE.sub(lambda m: m.group(1), text), values)


def label_html(text: str, href: str | None = None, *, ext: bool = False, sr: str = "", **values) -> Markup:
    """A label as HTML: fields filled with escaped values, the `[text]` mark a link to `href` (outbound links get
    rel="noopener noreferrer"), `sr` an escaped screen-reader-only tail inside the link. A label with a link mark and
    no `href` prints its text plain."""
    m = LINK_RE.search(text)
    if m is None:
        return escape(_fill(text, values))
    before, inner, after = text[:m.start()], m.group(1), text[m.end():]
    if not href:                    # no link to give: the words, never href=""
        return escape(_fill(before + inner + after, values))
    rel = ' rel="noopener noreferrer"' if ext else ""
    tail = Markup('<span class="sr-only">{}</span>').format(sr) if sr else ""
    link = Markup('<a href="{}"{}>{}{}</a>').format(href, Markup(rel), _fill(inner, values), tail)
    return escape(_fill(before, values)) + link + escape(_fill(after, values))


# --- the two fragments on existing pages (7a) --------------------------------------------------------------------------

def menu_fragment(root: str, labels: Mapping[str, str]) -> str:
    """The Menu group, inserted as the last entry of the footer list that static/nav.js copies into the drawer."""
    if not nat.ROOT_RE.fullmatch(root):
        raise NationalBuildError(f"root must be a run of '../', not {root!r}")
    g = escape(labels["menu.group"])
    return (f'      <li><span class="nav-group">{g}</span>\n'
            f'        <ul class="nav-years" aria-label="{g}">\n'
            f'          <li><a href="{root}{INDEX}">{escape(labels["menu.find"])}</a></li>\n'
            f'          <li><a href="{root}{COVERED}">{escape(labels["menu.covered"])}</a></li>\n'
            f'        </ul>\n'
            f'      </li>\n')


def front_fragment(labels: Mapping[str, str]) -> str:
    """The front page's one line, right after its address card (the `find` section)."""
    return f'\n  <p class="digest-line"><a href="{INDEX}">{escape(labels["front.line"])}</a></p>'


def _with_menu(rel: str, html: str, labels) -> str:
    m = MENU_ROOT_RE.search(html)
    if m is None:
        return html                         # not a page of base.html.j2 (the geo frame): no footer list
    if html.count(MENU_ANCHOR) != 1 or len(MENU_ROOT_RE.findall(html)) != 1:
        raise NationalBuildError(f"{rel}: the footer list's end is not where base.html.j2 puts it")
    return html.replace(MENU_ANCHOR, menu_fragment(m.group(1), labels) + MENU_ANCHOR, 1)


def _with_front_line(html: str, labels) -> str:
    start = html.find(FRONT_START)
    if start < 0 or html.count(FRONT_START) != 1:
        raise NationalBuildError(f"{FRONT_PAGE}: no single address card ({FRONT_START})")
    depth = 0
    for m in SECTION_TAG_RE.finditer(html, start):
        depth += 1 if m.group(0) == "<section" else -1
        if depth == 0:
            return html[:m.end()] + front_fragment(labels) + html[m.end():]
    raise NationalBuildError(f"{FRONT_PAGE}: the address card is not closed")


def apply_site_fragments(pages: Mapping[str, str], labels: Mapping[str, str]) -> dict[str, str]:
    """{site path: html} -> the same pages with the Menu group in every page's footer list and, on the front page,
    the one line under the address card. Pure; each fragment is fixed text and is added exactly once."""
    out = {}
    for rel, html in pages.items():
        html = _with_menu(rel, html, labels)
        if rel == FRONT_PAGE:
            html = _with_front_line(html, labels)
        out[rel] = html
    return out


def apply_to_tree(out: Path, labels: Mapping[str, str]) -> int:
    """apply_site_fragments on every .html file under `out` (data/ excluded); returns how many files changed."""
    out = Path(out)
    changed = 0
    for p in sorted(out.rglob("*.html")):
        rel = p.relative_to(out).as_posix()
        if rel.split("/", 1)[0] == "data":
            continue
        html = p.read_text(encoding="utf-8")
        new = apply_site_fragments({rel: html}, labels)[rel]
        if new != html:
            p.write_text(new, encoding="utf-8")
            changed += 1
    return changed


# --- CSP (section 6) --------------------------------------------------------------------------------------------------

def index_csp(counter: str | None, form_origin: str | None) -> str:
    """digest/index.html: script-src 'self' (the Census only in the frame's own CSP), frame-src 'self', the email
    service in form-action (beside 'self', which the Menu's search form needs) and connect-src, and the counter's
    origin in connect-src while analytics is on. The rest is the site's base policy."""
    connect = " ".join(o for o in (form_origin, counter) if o) or "'none'"
    rest = []
    for d in CSP_BASE[1:]:
        if d == "connect-src 'none'":
            d = f"connect-src {connect}"
        elif d == "form-action 'self'" and form_origin:
            d = f"form-action 'self' {form_origin}"
        rest.append(d)
    return "; ".join([CSP_BASE[0], "script-src 'self'", *rest])


# --- feeds -----------------------------------------------------------------------------------------------------------

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def newest_record_at(sources) -> datetime:
    """The newest record we hold for a feed (national-freshness/checked-at-is-first-fetch): the latest first fetch
    among its source records, the recorded instant when the manifests have it (localdates.instant), else noon UTC of
    the stored UTC day (so the site_timezone day printed is the stored day, as other pages print it). This is when the
    newest document was first collected, not when the source was last checked: M1 records no check run, so nothing
    here or on the page claims one (a true check time comes from the M2 collector's run stamp, task C3). No fetch day
    at all: EPOCH, which the page reads as "no records yet" (never a made-up date)."""
    best = EPOCH
    for s in sources or ():
        day = s.get("fetched_at") if isinstance(s, dict) else None
        if not isinstance(day, str) or len(day) < 10:
            continue
        when = localdates.instant(s.get("url"), s.get("sha256"), day)
        if when is None:
            try:
                when = datetime.combine(date.fromisoformat(day[:10]), time(12), tzinfo=timezone.utc)
            except ValueError:
                continue
        best = max(best, when)
    return best


def council_inputs(councils, fixture: bool) -> dict[str, tuple[dict, list]]:
    """{council.yml body_key: (facts, listing)} for the adapter, from the build's CouncilIndex list. A fixture build
    builds no council and reads no real council data: each configured council then has no facts and no listing (its
    page says no meetings are posted and that it could not check), never the real files beside fixture facts."""
    out = {c.cfg["body_key"]: (c.facts, ncl.load_listing(c.cfg)) for c in councils if c.cfg.get("body_key")}
    if fixture:
        for cfg in config.COUNCILS:
            if cfg.get("body_key"):
                out.setdefault(cfg["body_key"], ({}, []))
    return out


def build_feeds(directory: nat.Directory, councils: Mapping[str, tuple[dict, list]], county_agendas: dict | None,
                today: date, counts: dict[str, GuardCounts] | None = None) -> dict[str, dict]:
    """{body id: feed} for every covered entry, each with its own `checked_at` (the newest record, see
    newest_record_at) and `last_ok_at` null (M1 records no successful check run): the council's from its facts file's
    sources, the county's from the agendas file's sources (newest_record_at). `councils`: council_inputs(). The adapter
    (national_clarksville.clarksville_feeds) is called once per entry so each gets its own instant; a covered entry
    with no feed stops the build (its page would link nowhere)."""
    feeds: dict[str, dict] = {}
    for gov in directory.govs:
        if gov["status"] != "covered":
            continue
        key = (gov.get("daylight") or {}).get("body")
        if key == ncl.COUNTY_BODY_KEY:
            at = newest_record_at((county_agendas or {}).get("sources"))
        else:
            at = newest_record_at((councils.get(key, ({}, []))[0] or {}).get("sources"))
        one = nat.Directory(govs=(gov,), alias={})
        feeds.update(ncl.clarksville_feeds(one, councils, county_agendas, today, checked_at=at, counts=counts))
        if gov["gov"] in feeds:
            feeds[gov["gov"]]["last_ok_at"] = None      # schema: instant or null; no check time is recorded in M1
        if gov["gov"] not in feeds:
            raise NationalBuildError(f"{gov['gov']}: covered, but no feed is built for it (platform "
                                     f"{gov.get('platform')!r})")
    return feeds


def feed_json(feed: dict) -> str:
    """The published JSON text of a feed, checked against the schema once more (no extra key, section 11)."""
    errors = ncl.feed_errors(feed)
    if errors:
        raise NationalBuildError(f"{feed.get('body', {}).get('id')}: feed does not match {ncl.UPCOMING_SCHEMA}:\n"
                                 + "\n".join(errors))
    return json.dumps(feed, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


# --- dates ------------------------------------------------------------------------------------------------------------

def build_instant(built_day: date, now: datetime | None = None) -> datetime:
    """The build's instant: now, unless the build is fixed to another day (RECORDS_TODAY, a test): then noon of that
    day in the site's zone, so a rebuild of a past day reads the same."""
    tz = ZoneInfo(config.SITE["site_timezone"])
    now = now or datetime.now(timezone.utc)
    if now.astimezone(tz).date() == built_day:
        return now
    return datetime.combine(built_day, time(12), tzinfo=tz)


def _local_date(t: datetime) -> date:
    return t.astimezone(ZoneInfo(config.SITE["site_timezone"])).date()


def newest_day(checked_at: str | None) -> str | None:
    """The site_timezone day of a feed's newest record (`checked_at`, see newest_record_at), or None for no record."""
    when = nat._parse_instant(checked_at)
    if when is None or when <= EPOCH:
        return None
    return _local_date(when).isoformat()


def long_day(iso: str) -> str:
    """"2026-12-14" -> "Monday, December 14, 2026" (the meeting heading: weekday first, design section 5)."""
    d = date.fromisoformat(iso)
    return f"{d.strftime('%A')}, {localdates.words(iso)}"


# --- the pages --------------------------------------------------------------------------------------------------------

def _host(url: str | None) -> str:
    return urlsplit(url).hostname or "" if url else ""


def _state_label(page_labels, st: str) -> str:
    key = f"state.{st}"
    if key not in page_labels:
        raise NationalBuildError(f"config/national/page-labels.yml: no label {key} (a directory entry is in {st})")
    return page_labels[key]


def _tz_label(page_labels, tz: str) -> str:
    key = f"tz.{tz}"
    if key not in page_labels:
        raise NationalBuildError(f"config/national/page-labels.yml: no label {key}")
    return page_labels[key]


def official_of(gov: Mapping) -> str | None:
    """The directory entry's official link, checked again at build against its platform's host allowlist
    (national_guards.allowed_url); None when it fails (no link is printed, never href="")."""
    return allowed_url(gov.get("official_url"), gov.get("platform") or "daylight",
                       (gov.get("legistar") or {}).get("client")) or None


def meeting_view(m: dict, gov: Mapping, tz: str, page_labels) -> dict:
    """What the coming-up template prints for one meeting of the bound feed (section 11 consumer 3): items only when
    the agenda is final and the feed says they are not withheld. Links come from the meeting through the directory
    entry `gov`'s platform and client (re-checked here), falling back to the entry's official link; an empty link
    becomes None, so the page prints the words without a link."""
    platform, client = gov.get("platform") or "daylight", (gov.get("legistar") or {}).get("client")
    official = official_of(gov) or ""
    agenda_url = link_or_official(m["agenda"].get("url"), official, platform, client) or None
    state = m["agenda"]["state"]
    withheld = m["items_withheld"] is not False
    items = m["items"] if state == ncl.FINAL and not withheld else []
    return {"id": m["id"], "date": m["date"], "day": long_day(m["date"]), "time": m["time"],
            "tz": _tz_label(page_labels, tz) if m["time"] else None,
            "title": m["title"], "title_ours": m["title_ours"], "state": state,
            "posted": state in (ncl.FINAL, ncl.NOT_READ), "agenda_url": agenda_url,
            "withheld": state == ncl.FINAL and withheld,
            "incomplete": state == ncl.FINAL and not withheld and m["may_be_incomplete"],
            "entries": [{"number": it.get("number"), "text": it["text"], "cut": it.get("cut", False),
                         "page": (it.get("source") or {}).get("page"),
                         "url": link_or_official((it.get("source") or {}).get("url"), agenda_url or "", platform,
                                                 client) or None}
                        for it in items]}


class Pages:
    """Renders the digest pages with the build's Jinja environment and the site context (switch off: no "Show records
    from" on digest pages, 7a)."""

    def __init__(self, env, site: dict, labels: Mapping[str, str], page_labels: Mapping[str, str]):
        self.env = env
        self.site = dict(site, switch=None)
        self.labels = labels
        self.L = page_labels

    def html(self, template: str, rel: str, page_name: str, *, csp: str | None = None, crumbs=(),
             report: bool = True, **ctx) -> str:
        root = "../" * rel.count("/")
        return self.env.get_template(template).render(
            site=self.site, root=root, page_name=page_name, body_current="", report_page=report,
            crumbs=list(crumbs), official_record=None, csp=csp or self.site["csp"], digest_header=True,
            digest_place=self.L["digest.place"], L=self.L, card=self.labels, lh=label_html, lt=label_text, **ctx)

    def crumbs(self, *keys: str) -> list[dict]:
        hrefs = {"crumb.home": INDEX, "crumb.covered": COVERED}
        return [{"href": hrefs[k], "label": self.L[k]} for k in keys]


def build_national(out_dir: Path, env, site: dict, directory: nat.Directory, flags: nat.GovFlags,
                   labels: Mapping[str, str], page_labels: Mapping[str, str], feeds: Mapping[str, dict], *,
                   built_at: datetime, counter: dict | None,
                   bind_counts: dict[str, BindCounts] | None = None,
                   links: Mapping[str, str | None] | None = None) -> list[str]:
    """Writes the digest pages (module docstring) and returns their site paths, the HTML pages first. `counter`: the
    build's analytics settings (analytics.settings()) or None; `site`: the build's site context. `links`: load_links()
    (None: no outside link, both settings null).

    Architecture 11.1 row 15: every feed passes `national_guards.bind_feed(feed, entry)` with its covered directory
    entry first, and the .json and .html are written only from that bound object (a feed for no covered entry is not
    written). `bind_counts`, if given, receives what each bind stripped (counts only)."""
    out = Path(out_dir)
    pages = Pages(env, site, labels, page_labels)
    L = page_labels
    morning = (site.get("morning_note") or {}).get("signup_href") if site.get("morning_note") else None
    written: dict[str, str] = {}
    files: dict[str, str] = {}

    covered = [g for g in directory.govs if g["status"] == "covered"]
    bound: dict[str, dict] = {}
    for g in covered:
        if g["gov"] not in feeds:
            raise NationalBuildError(f"{g['gov']}: covered, but no feed was given")
        try:
            bound[g["gov"]], n = bind_feed(feeds[g["gov"]], g)
        except BindError as exc:
            raise NationalBuildError(str(exc)) from exc
        if bind_counts is not None:
            bind_counts[g["gov"]] = n
    feeds = bound
    last_ok = {gid: f.get("last_ok_at") for gid, f in feeds.items()}

    # the entry page: the page directory relative to digest/ (its own data-root), the script strings and settings
    pagedir = nat.page_directory(directory, flags, labels, built_at=built_at, last_ok_at=last_ok, root="../")
    # M1 records no check run (national-freshness/checked-at-is-first-fetch): a daylight-platform government is never
    # marked stale, because nothing says when its source was last checked. The M2 collector's run stamp (task C3)
    # brings `last_ok_at`, and with it the stale flag, for the Legistar governments.
    for g in covered:
        if g.get("platform") == ncl.PLATFORM:
            pagedir["govs"][g["gov"]]["stale"] = False
    form_origin = morning_page.form_origin()
    note = morning_page.settings() or {}
    settings = {"schema": "daylight-digest-config/1", "frame": "geo-frame.html", "covered": "covered.html",
                "requested": "requested.html",
                "form_action": note.get("form_action") if form_origin else None,
                "privacy_url": note.get("privacy_url") if form_origin else None,
                "morning": morning,
                **{k: allowed_url((links or {}).get(k)) or None for k in LINK_KEYS}}
    strings = {k: v for k, v in L.items() if k.startswith(SCRIPT_GROUPS)}
    written[INDEX] = pages.html(
        "digest/index.html.j2", INDEX, label_text(L["index.title"]),
        csp=index_csp(counter["origin"] if counter else None, form_origin), report=True,
        pagedir_json=Markup(nat.embed_json(pagedir)), strings_json=Markup(nat.embed_json(strings)),
        config_json=Markup(nat.embed_json(settings)), counter=counter)

    # What we cover: by state (its name), then board name
    def by_state(status):
        rows = sorted((g for g in directory.govs if g["status"] == status),
                      key=lambda g: (_state_label(L, g["state"]), g["body_name"].casefold()))
        groups: list[dict] = []
        for g in rows:
            st = _state_label(L, g["state"])
            if not groups or groups[-1]["state"] != st:
                groups.append({"state": st, "rows": []})
            groups[-1]["rows"].append({
                "board": g["body_name"], "slot": labels[f"slot.{nat.id_layer(g['gov'])}"],
                "page": nat.gov_page(g) if status == "covered" else None,
                "reason": labels.get(f"reason.{g.get('reason')}"), "checked": g["checked"].isoformat(),
                "source": allowed_url(g.get("reason_url") or g.get("checked_url")) or None,
                "official": official_of(g)})
        return groups
    n_cov = len(covered)
    written[COVERED] = pages.html(
        "digest/covered.html.j2", COVERED, label_text(L["covered.title"]), crumbs=pages.crumbs("crumb.home"),
        covered=by_state("covered"), cant=by_state("cant-cover"), n_covered=n_cov, share=None)

    written[REQUESTED] = pages.html("digest/requested.html.j2", REQUESTED, label_text(L["requested.title"]),
                                    crumbs=pages.crumbs("crumb.home"), report=False)

    # How Daylight Digest works: the method text for the digest pages (the Clarksville Method page is not touched)
    written[HOW] = pages.html("digest/how.html.j2", HOW, label_text(L["how.title"]), crumbs=pages.crumbs("crumb.home"),
                              buttondown_privacy=settings["privacy_url"])

    # one coming-up page and its JSON per covered government
    for g in covered:
        feed = feeds[g["gov"]]               # bound above: body.id and platform are this entry's
        rel = nat.gov_page(g)
        daylight = g.get("platform") == ncl.PLATFORM          # Clarksville's own bodies (AC4.5, AC8.3)
        official = official_of(g)
        written[rel] = pages.html(
            "digest/body.html.j2", rel, label_text(L["body.title"], name=g["body_name"]),
            crumbs=pages.crumbs("crumb.home", "crumb.covered"),
            name=g["body_name"], official=official, state_name=_state_label(L, g["state"]),
            slot=labels[f"slot.{nat.id_layer(g['gov'])}"], host=_host(official),
            newest=newest_day(feed.get("checked_at")),
            meetings=[meeting_view(m, g, feed["body"]["tz"], L) for m in feed["meetings"]],
            full_href=g["daylight"]["full_url"] if daylight else None, morning=morning if daylight else None)
        files[rel[:-len(".html")] + ".json"] = feed_json(feed)

    files[FRAME] = nat.geo_frame_html()
    for rel, text in [*written.items(), *files.items()]:
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return [*written, *files]


def run(out_dir: Path, env, site: dict, *, councils, county_agendas: dict | None, built_day: date,
        counter: dict | None, fixture: bool, folder: Path = nat.NATIONAL_DIR) -> list[str]:
    """The build's one call (sitegen/build.py, only when `enabled()`): load and check the curated files, make the
    feeds, write the digest/ files. Returns the HTML pages written (for static/pages.js); the guards' counts go to
    the run log as one line per government that had any."""
    try:
        directory, flags, labels = nat.load_all(folder)
        page_labels = load_page_labels(Path(folder) / "page-labels.yml")
        links = load_links(Path(folder) / "links.yml")
        counts: dict[str, GuardCounts] = {}
        feeds = build_feeds(directory, council_inputs(councils, fixture), county_agendas, built_day, counts)
    except (nat.NationalConfigError, ncl.FeedError, ValueError) as exc:
        raise NationalBuildError(str(exc)) from exc
    for gid, n in sorted(counts.items()):
        if n.any():
            print(f"sitegen: national: {gid}: guards changed the feed: {n.summary()}", flush=True)
    binds: dict[str, BindCounts] = {}
    written = build_national(out_dir, env, site, directory, flags, labels, page_labels, feeds,
                             built_at=build_instant(built_day), counter=counter, bind_counts=binds, links=links)
    for gid, n in sorted(binds.items()):
        if n.withheld_stripped or n.review_mismatch:
            print(f"sitegen: national: {gid}: bind_feed stripped items: {n.summary()}", flush=True)
    return [r for r in written if r.endswith(".html") and r != FRAME]


def fragment_labels(folder: Path = nat.NATIONAL_DIR) -> dict[str, str]:
    """The page labels apply_site_fragments reads (for the build and for B5's golden test)."""
    return load_page_labels(Path(folder) / "page-labels.yml")
