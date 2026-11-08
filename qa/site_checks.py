# ruff: noqa: E501
"""Black-box checks of a BUILT site directory (reads only the files in it, plus the facts file it was built from).

    python -m qa.site_checks --site build/site --facts data/facts.json            # public build (default)
    python -m qa.site_checks --site build/site --facts data/facts.json --internal # build made with --internal
    python -m qa.site_checks --site build/site --facts site/fixtures/facts.sample.json --no-export   # fixture

Checks (each prints PASS/FAIL, exit code 1 if any FAIL):
  links       every internal href resolves to a file, every #fragment to an id on the target page, assets exist
  sources     every link to a minutes PDF carries #page=N with 1 <= N <= the source's page count (and, when the PDF
              is cached locally, <= the real page count from pdfinfo); no other external links, except https links
              marked data-ext whose exact URL is in config/site.yml, the map's source_url or a roster row
  unverified  no held fact (unverified attendance, held motion attribution, outcome text) appears anywhere in the
              build but review.html; a public build has no review.html and nothing links to it; every fact id on a
              page is a shown fact; every shown fact appears on its official's page; every fact row or block of an
              unconfirmed roll call carries the "Not confirmed" note, and one of a confirmed roll call has no note and
              no "*" (invariant: held-back counts)
  index       officials.html lists every official in the facts exactly once; "surname" sections alphabetical by
              surname, "seat" (Current) sections by district number, then other seats (AC1.1, design 6A.3)
  layout      every official page has the same headings and the same distinct column-header sets (AC1.5, N1)
  provenance  derived seat dates are worded as seen in roll calls; no term wording, no inferred cutover date;
              the cutover is immaterial (architecture, invariant `provenance`)
  totals      "Recorded absent at X of Y meetings" equals a recount from the meeting pages (AC2.2)
  name-links  every occurrence of an official's display name in the visible text of a page is inside an <a> to that
              official's page (standing rule), except in <title>, <option>, the footer operator line and on the
              official's own page
  footer      "Provided as a free service by Brian Zacharias." on every page
  external    no third-party scripts, styles, images or fonts (N6)
  files       fewer than 250 files
  row-height  no table row (or vote / result list item) taller than 60% of the viewport, with long text clamped and row
              details collapsed, at 375x667, 768x1024, 1000x800 and 1280x800; needs Playwright (node)
  hscroll     no horizontal scroll at 390 px for the page types (index, official, meeting, items, and when present
              officials, district, search, votes); needs Playwright (node)
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qa.common import OPERATOR, ROOT, find_pdf, load_facts, pdf_page_count  # noqa: E402

MAX_FILES = 250
VIEWPORT = 390


# External links that are not minutes PDFs but are allowed: a holder record's roster source, the map's boundary source,
# the county redistricting page / old-lines map, and the footer support link. Each must be marked data-ext and https.
EXT_KINDS = {"roster", "map", "county", "support"}


def _site_cfg() -> dict:
    import yaml
    return yaml.safe_load((ROOT / "config" / "site.yml").read_text(encoding="utf-8"))


def default_inputs(facts: dict) -> tuple[Path | None, Path | None]:
    """(roster, map) files the build read: the fixture's for a fixture facts file, else the locality's."""
    if facts.get("fixture"):
        fx = ROOT / "site" / "fixtures"
        return fx / "seats.sample.yml", fx / "districts.sample.json"
    loc = ROOT / "config" / "localities" / _site_cfg()["locality"]
    seats = loc / "seats.yml" if (loc / "seats.yml").is_file() else ROOT / "config" / "seats.yml"
    return seats, loc / "districts.json"


def read_roster(path: Path | None) -> list[dict]:
    import yaml
    if path is None or not Path(path).is_file():
        return []
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    return raw.get("seats", []) if isinstance(raw, dict) else raw


def allowed_external(cfg: dict, seats_path: Path | None, districts_path: Path | None) -> set[str]:
    """Exact URLs (qa-weakened/ext-link-any-host): config/site.yml links, the map's source_url, every roster row's
    source and last_source, and the support link only when it is switched on."""
    out = {cfg[k] for k in ("redistricting_page", "old_lines_map_url", "swap_source") if cfg.get(k)}
    if cfg.get("support_enabled") is True and cfg.get("support_url"):
        out.add(cfg["support_url"])
    if districts_path is not None and Path(districts_path).is_file():
        out.add(json.loads(Path(districts_path).read_text(encoding="utf-8"))["source_url"])
    for r in read_roster(seats_path):
        out |= {r[k] for k in ("source", "last_source") if r.get(k)}
    return out


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.hrefs, self.fact_ids, self.resources, self.text = set(), [], [], [], []
        self.fact_hrefs = []          # hrefs inside an element carrying data-fact-id
        self.ext_hrefs = []           # <a data-ext="roster|map|county|support">: a sourced link that is not a minutes PDF
        self.links: list[tuple[str, str | None]] = []   # every <a href>, one entry per element: (href, data-ext)
        self.fact_texts: list[tuple[str, str]] = []   # (fact id, text) of each outermost data-fact-id element
        self._stack, self._fact_depth, self._fact_buf = [], None, None

    def handle_endtag(self, tag):
        if tag in self.VOID or tag not in self._stack:
            return
        while self._stack:
            if self._stack.pop() == tag:
                break
        if self._fact_depth is not None and len(self._stack) < self._fact_depth:
            self._fact_depth = None
            self.fact_texts.append(self._fact_buf)
            self._fact_buf = None

    VOID = {"meta", "link", "br", "img", "input", "hr", "source", "area", "base", "col", "embed", "wbr"}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag not in self.VOID:
            self._stack.append(tag)
            if "data-fact-id" in a and self._fact_depth is None:
                self._fact_depth = len(self._stack)
                self._fact_buf = (a["data-fact-id"], "")
        if tag == "a" and "href" in a and self._fact_depth is not None:
            self.fact_hrefs.append(a["href"] or "")
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and a.get("name"):
            self.ids.add(a["name"])
        if tag == "a" and "href" in a:
            self.hrefs.append(a["href"] or "")
            self.links.append((a["href"] or "", a.get("data-ext")))
            if a.get("data-ext") in EXT_KINDS:
                self.ext_hrefs.append(a["href"] or "")
        if "data-fact-id" in a:
            self.fact_ids.append(a["data-fact-id"])
        if tag == "script" and a.get("src"):
            self.resources.append((tag, a["src"]))
        if tag == "link" and a.get("href"):
            self.resources.append((tag, a["href"]))
        if tag in ("img", "source", "iframe", "video", "audio") and a.get("src"):
            self.resources.append((tag, a["src"]))
        if tag == "form" and a.get("action"):
            self.resources.append((tag, a["action"]))

    def handle_data(self, d):
        self.text.append(d)
        if self._fact_buf is not None:
            self._fact_buf = (self._fact_buf[0], self._fact_buf[1] + d)


def parse(path: Path) -> Page:
    p = Page()
    p.feed(path.read_text(encoding="utf-8"))
    return p


class Report:
    def __init__(self):
        self.results: list[tuple[str, bool, list[str], str]] = []

    def add(self, name: str, problems: list[str], note: str = ""):
        self.results.append((name, not problems, problems, note))

    def skip(self, name: str, why: str):
        self.results.append((name, True, [], f"SKIPPED: {why}"))

    @property
    def ok(self) -> bool:
        return all(r[1] for r in self.results)

    def render(self, limit=15) -> str:
        out = []
        for name, ok, problems, note in self.results:
            out.append(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({note})" if note else ""))
            for p in problems[:limit]:
                out.append(f"      - {p}")
            if len(problems) > limit:
                out.append(f"      ... {len(problems) - limit} more")
        return "\n".join(out)


def resolve(page_rel: str, href: str) -> str | None:
    """Site-relative path an internal href points at, or None if it leaves the site."""
    u = urlsplit(href)
    path = unquote(u.path)
    if not path:
        return page_rel
    parts = [] if path.startswith("/") else list(Path(page_rel).parent.parts)
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(seg)
    rel = "/".join(parts)
    return rel + "index.html" if path.endswith("/") and not rel else (rel + "/index.html" if path.endswith("/") else rel)


# ---------------------------------------------------------------- the checks

def check_links(site: Path, pages: dict[str, Page], no_export: bool) -> list[str]:
    problems = []
    for rel, pg in pages.items():
        for href in pg.hrefs:
            u = urlsplit(href)
            if u.scheme in ("http", "https"):
                continue
            if u.scheme or href.startswith("//"):
                problems.append(f"{rel}: href with scheme {href!r}")
                continue
            target = resolve(rel, href)
            if target is None:
                problems.append(f"{rel}: href {href!r} leaves the site")
                continue
            if no_export and target.startswith("data/") and not (site / "data").exists():
                continue
            f = site / target
            if not f.is_file():
                problems.append(f"{rel}: {href!r} -> missing file {target}")
                continue
            if u.fragment and target.endswith(".html"):
                ids = pages[target].ids if target in pages else parse(f).ids
                if u.fragment not in ids:
                    problems.append(f"{rel}: {href!r} -> no #{u.fragment} on {target}")
        # static assets referenced by <link>/<script>
        for tag, src in pg.resources:
            if urlsplit(src).scheme or src.startswith("//"):
                continue
            target = resolve(rel, src)
            if target is None or not (site / target).is_file():
                problems.append(f"{rel}: <{tag}> {src!r} not found")
    return problems


def check_sources(site: Path, pages: dict[str, Page], facts: dict, store_extra,
                  allowed: set[str] | None = None) -> tuple[list[str], str]:
    """`allowed`: the exact external URLs a page may link that are not minutes PDFs (allowed_external)."""
    allowed = set() if allowed is None else allowed
    problems = []
    by_url = {}
    for s in facts["sources"]:
        by_url[s["url"]] = s
        by_url[unquote(s["url"])] = s
    real_pages: dict[str, int | None] = {}
    seen = doc_level = 0
    for rel, pg in pages.items():
        for href, ext in pg.links:   # each <a> on its own: one allowed link never excuses another
            if urlsplit(href).scheme not in ("http", "https"):
                continue
            base, _, frag = href.partition("#")
            src = by_url.get(base) or by_url.get(unquote(base))
            if src is None:
                if ext not in EXT_KINDS:
                    problems.append(f"{rel}: external link {href!r} is not a known source document")
                elif not href.startswith("https://"):
                    problems.append(f"{rel}: marked external link {href!r} is not https")
                elif href not in allowed:
                    problems.append(f"{rel}: marked external link {href!r} is not a URL from the config, map or roster")
                continue
            seen += 1
            m = re.fullmatch(r"page=(\d+)", frag)
            if not m:
                if href in pg.fact_hrefs:
                    problems.append(f"{rel}: fact-row source link {href!r} has no #page=N")
                else:
                    doc_level += 1      # e.g. the meeting page header "minutes PDF, 25 pages": names the document, not a fact
                continue
            n = int(m.group(1))
            if not 1 <= n <= src["pages"]:
                problems.append(f"{rel}: {href!r}: page {n} outside 1..{src['pages']}")
                continue
            if src["id"] not in real_pages:
                pdf = find_pdf(src["sha256"], store_extra)
                real_pages[src["id"]] = pdf_page_count(pdf) if pdf else None
                if real_pages[src["id"]] is not None and real_pages[src["id"]] != src["pages"]:
                    problems.append(f"source {src['id']}: facts say {src['pages']} pages, PDF has {real_pages[src['id']]}")
            rp = real_pages[src["id"]]
            if rp is not None and n > rp:
                problems.append(f"{rel}: {href!r}: page {n} beyond the real PDF ({rp} pages)")
    checked = sum(1 for v in real_pages.values() if v is not None)
    return problems, (f"{seen} source links ({doc_level} document-level links without #page, outside fact rows); "
                      f"{checked} of {len(real_pages)} PDFs cross-checked with pdfinfo")


def unverified_tokens(facts: dict) -> list[tuple[str, str]]:
    """(token, why) pairs that must not appear anywhere in a public build."""
    # Free text that a public page legitimately shows (item titles, and event labels other than motion and roll call
    # ones) cannot prove a leak. Outcome text, motion text and motion/roll call event labels are raw OCR that no public
    # page shows, so they are not benign (raw-ocr-leak/qa-outcome-benign).
    benign = [e["label"] for e in facts["item_events"] if e["type"] not in ("motion", "roll_call")]
    benign += [i["title"] for i in facts["items"]]
    # Unconfirmed roll calls are shown, marked (CEO, 2026-11-07); their raw outcome text never is.
    toks = []
    for r in facts["roll_calls"]:
        if r["verification"]["status"] == "unverified":
            if len(r["outcome_text"]) > 12 and not any(r["outcome_text"] in b for b in benign):
                toks.append((r["outcome_text"], f"unverified roll call {r['id']} outcome text"))
    for m in facts["meetings"]:
        if m["verification"]["status"] == "unverified":
            toks.append((f"{m['id']}/att", "unverified attendance"))
    for mo in facts["motions"]:
        if not attribution_shown(facts, mo):
            toks += [(f"{mo['id']}/moved", "held motion attribution"), (f"{mo['id']}/seconded", "held motion attribution")]
    return toks


def attribution_shown(facts: dict, mo: dict) -> bool:
    """Rule 6 of the invariant, restated here on purpose (an independent check, not a call into sitegen): a verified
    motion shows its resolved names; an unverified one never shows any name ("Attribution under review")."""
    return mo["verification"]["status"] == "verified"


def _contains(body: str, tok: str, why: str) -> bool:
    """Ids match on id boundaries (ev-x-p9-1 is not inside ev-x-p9-13); free text matches as a substring."""
    if " text" in why:
        return tok in body
    return re.search(r"(?<![A-Za-z0-9_/-])" + re.escape(tok) + r"(?![A-Za-z0-9_-])", body) is not None


def shown_fact_ids(facts: dict) -> tuple[set[str], set[str]]:
    """(votes+attendance+moved/seconded that must be shown, and those that must not be)."""
    shown, hidden = set(), set()
    for r in facts["roll_calls"]:
        for v in r["votes"]:
            if v.get("official_id"):
                shown.add(f"{r['id']}/{v['official_id']}")  # confirmed or not: unconfirmed rows are shown, marked
    for m in facts["meetings"]:
        ok = m["verification"]["status"] == "verified" and m["attendance_status"] == "extracted"
        for a in m["attendance"]:
            if a.get("official_id"):
                (shown if ok else hidden).add(f"{m['id']}/att/{a['official_id']}")
    for mo in facts["motions"]:
        for who, key in (("moved_by", "moved"), ("seconded_by", "seconded")):
            p = mo.get(who)
            if p and p.get("official_id"):
                (shown if attribution_shown(facts, mo) else hidden).add(f"{mo['id']}/{key}")
    return shown, hidden


def check_unverified(site: Path, pages: dict[str, Page], facts: dict, internal: bool,
                     show_values: bool | None = None) -> list[str]:
    if show_values is None:  # the build's switch; the rule itself is restated here, not called from sitegen
        from sitegen.config import SHOW_UNCONFIRMED_VALUES as show_values
    problems = []
    has_review = "review.html" in pages
    if not internal:
        if has_review:
            problems.append("review.html is in a public build")
        for rel, pg in pages.items():
            if any(urlsplit(h).path.endswith("review.html") for h in pg.hrefs):
                problems.append(f"{rel}: links to review.html in a public build")
    # token scan over every text file (html, csv, json, js, css) except the internal review page
    toks = unverified_tokens(facts)
    for f in sorted(site.rglob("*")):
        rel = f.relative_to(site).as_posix()
        if not f.is_file() or rel == "review.html" or f.suffix not in (".html", ".csv", ".json", ".js", ".css", ".txt", ".md"):
            continue
        body = f.read_text(encoding="utf-8", errors="replace")
        body = body + "\n" + html.unescape(body)
        for tok, why in toks:
            if internal and rel.startswith("data/") and " text" in why:
                continue    # an --internal export carries raw outcome text by design; its pages still must not
            if _contains(body, tok, why):
                problems.append(f"{rel}: contains {tok!r} ({why})")
    # every fact id on a page is a shown fact; every shown fact is on its official's page
    shown, hidden = shown_fact_ids(facts)
    on_official: set[str] = set()
    known = ({r["id"] for r in facts["roll_calls"]} | {m["id"] for m in facts["motions"]} | {e["id"] for e in facts["item_events"]}
             | {m["id"] for m in facts["meetings"]})
    for rel, pg in pages.items():
        for fid in pg.fact_ids:
            if fid in hidden:
                problems.append(f"{rel}: shows hidden fact {fid}")
            elif fid not in shown and fid not in known and not rel == "review.html":
                problems.append(f"{rel}: fact id {fid} is not in the facts file")
            if rel.startswith("officials/"):
                on_official.add(fid)
    for fid in sorted(shown - on_official):
        problems.append(f"shown fact {fid} is on no official page")
    # every fact row or block showing an unconfirmed roll call carries the fixed note inside that row or block, and a
    # row or block of a confirmed roll call carries neither the note nor a "*"
    unconfirmed = {r["id"] for r in facts["roll_calls"] if r["verification"]["status"] == "unverified"}
    confirmed = {r["id"] for r in facts["roll_calls"] if r["verification"]["status"] == "verified"}
    rc_event = {e["id"]: e["ref"] for e in facts["item_events"] if e["type"] == "roll_call"}
    note = "Not confirmed: this page was hard to read."
    for rel, pg in pages.items():
        if rel == "review.html":
            continue
        for fid, text in pg.fact_texts:
            rc = rc_event.get(fid, fid.split("/")[0])
            text = html.unescape(text)
            if rc in unconfirmed and note not in text:
                problems.append(f"{rel}: {fid} shows an unconfirmed roll call without the 'Not confirmed' note")
            elif rc in confirmed and (note in text or "*" in text):
                problems.append(f"{rel}: {fid} shows a confirmed roll call with a '*' or the 'Not confirmed' note")
            if rc in unconfirmed and not show_values and (m := PARSED_VALUE.search(text)):
                problems.append(f"{rel}: {fid} shows a parsed value {m.group(0)!r} of an unconfirmed roll call")
    # SHOW_UNCONFIRMED_VALUES off: the public export carries no value, outcome or tally of an unconfirmed roll call
    export = site / "data" / "facts.json"
    if not internal and not show_values and export.is_file():
        for r in json.loads(export.read_text(encoding="utf-8")).get("roll_calls", []):
            if r["id"] in unconfirmed and (r.get("outcome") is not None or r.get("stated_tally") is not None
                                           or any(v.get("value") is not None for v in r.get("votes", []))):
                problems.append(f"data/facts.json: unconfirmed roll call {r['id']} carries a parsed value")
    return problems


# A vote word or outcome followed by the "*" mark, or a tally: what an unconfirmed roll call must not show when
# SHOW_UNCONFIRMED_VALUES is off (the block reads "Not confirmed*" instead).
PARSED_VALUE = re.compile(r"\b(?:Yes|No|Abstain|Other(?:: [A-Za-z ]+)?|Passed|Failed)\s*\*|\b\d+ (?:yes|no|abstain)\b")


def check_index(site: Path, pages: dict[str, Page], facts: dict, roster_only: tuple = ()) -> tuple[list[str], str]:
    """AC1.1 / design 6A.3: officials.html lists each official once. Sections marked data-order="surname" are
    alphabetical by surname then given name; data-order="seat" lists districts by number, then other seats (N1)."""
    problems = []
    f = site / "officials.html"
    if not f.is_file():
        return ["no officials.html"], ""
    text = f.read_text(encoding="utf-8")
    order = {o["id"]: (o["surname"].casefold(), o["given"].casefold()) for o in facts["officials"]}
    linked: list[str] = []
    starts = [(m.start(), m.group(1)) for m in re.finditer(r'data-order="(seat|surname)"', text)]
    if not starts:
        problems.append("officials.html has no section marked data-order")
    for i, (pos, kind) in enumerate(starts):
        chunk = text[pos:starts[i + 1][0] if i + 1 < len(starts) else len(text)]
        cards = re.findall(r'<li class="card"[^>]*>(.*?)</li>', chunk, re.S)
        ids = []
        for c in cards:
            m = re.search(r'href="officials/([^/#?"]+)\.html"', c)
            if m:
                ids.append((m.group(1), c))
        linked += [x for x, _ in ids]
        if kind == "surname":
            keyed = [order[x] for x, _ in ids if x in order]
            if keyed != sorted(keyed):
                problems.append(f"officials.html section {i + 1} is not alphabetical by surname, then given name")
        else:
            seats = []
            word = re.escape(_site_cfg()["district_label"])   # the configured label form, "District N"
            for x, c in ids:
                m = re.search(r'class="seat">,\s*' + word + r' (\d+)', c)
                seats.append((0, int(m.group(1))) if m else (1, 0))
            if seats != sorted(seats):
                problems.append(f"officials.html section {i + 1} (Current) is not in seat order")
    ids = [o["id"] for o in facts["officials"]] + [i for i in roster_only if i not in order]  # roster-only: a page, no facts
    for i in sorted(set(ids) - set(linked)):
        problems.append(f"official {i} is not listed on officials.html")
    for i in sorted(set(linked) - set(ids)):
        problems.append(f"officials.html lists {i}, who is not in the facts")
    for i in sorted({x for x in linked if linked.count(x) > 1}):
        problems.append(f"officials.html lists {i} more than once")
    for i in ids:
        if f"officials/{i}.html" not in pages:
            problems.append(f"no page officials/{i}.html")
    return problems, f"{len(set(linked))} officials listed"


def _clean_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", fragment)).strip()


def _skeleton(html_text: str) -> tuple:
    """Headings and column headers of an official page, minus the name: the layout N1/AC1.5 says must be identical.
    Headings in order; column headers as the set of distinct header rows (one history table per year, so a count
    of tables would differ by how many years a person has, qa-tool/layout-counts-year-tables)."""
    body = html_text.split("<h1", 1)[-1]
    heads = [_clean_text(x) for _, x in re.findall(r"<(h2|h3)\b[^>]*>(.*?)</\1>", body, re.S)]
    tables = {tuple(_clean_text(th) for th in re.findall(r"<th\b[^>]*>(.*?)</th>", t, re.S))
              for t in re.findall(r"<thead\b.*?</thead>", body, re.S)}
    return (tuple(heads), frozenset(tables))


def check_layout(site: Path, facts: dict) -> tuple[list[str], str]:
    skel = {o["id"]: _skeleton((site / "officials" / f"{o['id']}.html").read_text(encoding="utf-8"))
            for o in facts["officials"] if (site / "officials" / f"{o['id']}.html").is_file()}
    if not skel:
        return ["no official pages"], ""
    ref_id, ref = next(iter(skel.items()))
    return [f"officials/{i}.html differs in headings/columns from officials/{ref_id}.html" for i, k in skel.items() if k != ref], \
        f"{len(skel)} official pages, same {len(ref[0])} headings and {len(ref[1])} column header set(s)"


# ---------------------------------------------------------------- provenance (derived vs stated)
# Restated from the architecture's invariant `provenance`, not imported from sitegen.
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DATE_PHRASES = ("seen in roll calls", "shown as vacant in roll calls", "roll calls")
SOURCE_TERM = "as the source prints it"
BANNED = ("Held this seat", "vacant since", "to present", "in use since")


class SeatTexts(HTMLParser):
    """Text of each element that shows a holder record: .seat, .seat-line, .holder-row, table.holders and
    section.holder h3 (outermost only)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []   # (tag, opened a collected element)
        self.depth = 0                             # > 0 while inside a collected element
        self.buf, self.out = "", []
        self.in_holder_section = 0

    def handle_starttag(self, tag, attrs):
        if tag in Page.VOID:
            return
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag == "section" and "holder" in cls:
            self.in_holder_section += 1
        hit = (bool({"seat", "seat-line", "holder-row"} & set(cls)) or (tag == "table" and "holders" in cls)
               or (tag == "h3" and self.in_holder_section > 0))
        opened = hit and self.depth == 0
        if opened:
            self.buf = ""
        if self.depth or opened:
            self.depth += 1
        self.stack.append((tag, opened, tag == "section" and "holder" in cls))

    def handle_endtag(self, tag):
        if tag in Page.VOID or not any(t == tag for t, _, _ in self.stack):
            return
        while self.stack:
            t, opened, sec = self.stack.pop()
            if self.depth:
                self.depth -= 1
            if opened:
                self.out.append(" ".join(self.buf.split()))
                self.depth = 0
            if sec:
                self.in_holder_section -= 1
            if t == tag:
                break

    def handle_data(self, d):
        if self.depth:
            self.buf += d


def dates_worded(text: str) -> list[str]:
    """Dates in `text` that do not sit in a phrase starting one of DATE_PHRASES (same clause: no . ; ( ) between)."""
    if SOURCE_TERM in text:
        return []
    bad = []
    low = text.lower()
    for m in DATE.finditer(text):
        before = low[:m.start()]
        starts = [before.rfind(ph) for ph in DATE_PHRASES]
        k = max(starts)
        if k < 0 or re.search(r"[.;()]", before[k:]):
            bad.append(m.group(0))
    return bad


def _day_before(d: str) -> str:
    import datetime as _dt
    return (_dt.date.fromisoformat(d) - _dt.timedelta(days=1)).isoformat()


def cutover_problems(facts: dict, roster: list[dict], effective: str) -> list[str]:
    """Check 4: the inferred cutover is immaterial. No meeting lies between the last roll-call meeting before it and
    the first on or after it, and every observed row's `lines` agrees with its meeting dates."""
    by_id = {m["id"]: m["date"] for m in facts["meetings"]}
    rc_dates = sorted({by_id[r["meeting_id"]] for r in facts["roll_calls"]})
    before = [d for d in rc_dates if d < effective]
    after = [d for d in rc_dates if d >= effective]
    # with only one side collected there is no boundary to straddle: rows are judged against the split key itself
    lo = before[-1] if before else _day_before(effective)
    hi = after[0] if after else effective
    problems = [f"meeting on {d} lies between the cutover meetings {lo} and {hi}"
                for d in sorted(by_id.values()) if before and after and lo < d < hi]
    for r in roster:
        if r.get("dates") != "observed" or not str(r.get("seat", "")).startswith("district-"):
            continue
        start, end = str(r["start"]), (str(r["end"]) if r.get("end") else None)
        if r.get("lines") == "old" and (end is None or end > lo):
            problems.append(f"{r.get('official_id')} {r['seat']}: old-lines row ends {end}, after {lo}")
        if r.get("lines") == "current" and start < hi:
            problems.append(f"{r.get('official_id')} {r['seat']}: current-lines row starts {start}, before {hi}")
    return problems


def check_provenance(site: Path, pages: dict[str, Page], facts: dict, roster: list[dict], cfg: dict) -> tuple[list[str], str]:
    problems = []
    eff = cfg["lines_effective"]
    import datetime as _dt
    banned = BANNED + (eff, (_dt.date.fromisoformat(eff) - _dt.timedelta(days=1)).isoformat())
    texts = 0
    for rel in sorted(pages):
        body = (site / rel).read_text(encoding="utf-8")
        plain = html.unescape(body)
        for b in banned:
            if b in plain:
                problems.append(f"{rel}: contains banned {b!r}")
        p = SeatTexts()
        p.feed(body)
        for t in p.out:
            texts += 1
            for d in dates_worded(t):
                problems.append(f"{rel}: seat text dates {d} without 'seen in roll calls' wording: {t[:90]!r}")
    idx_file = site / "static" / "search-index.js"
    if idx_file.is_file():
        raw = idx_file.read_text(encoding="utf-8")
        for b in banned:
            if b in raw:
                problems.append(f"static/search-index.js: contains banned {b!r}")
        ix = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        seat_strings = ([r.get("st") or "" for r in ix.get("records", []) if r.get("k") == "person"]
                        + [o["label"] for o in ix.get("officials", [])] + list(ix.get("seat_labels", [])))
        for t in seat_strings:
            texts += 1
            for d in dates_worded(t):
                problems.append(f"static/search-index.js: seat text dates {d} without 'seen in roll calls' wording: {t[:90]!r}")
    problems += cutover_problems(facts, roster, eff)
    return problems, f"{texts} seat texts checked; lines split key {eff} immaterial"


def check_totals(site: Path, pages: dict[str, Page], facts: dict) -> tuple[list[str], str]:
    """AC2.2: each 'Recorded absent at X of Y meetings' equals a recount from the built meeting pages."""
    counts: dict[str, list[int]] = {}
    for rel in pages:
        if not rel.startswith("meetings/"):
            continue
        t = (site / rel).read_text(encoding="utf-8")
        for m in re.finditer(r'data-fact-id="[^"]+/att/([^"]+)"[^>]*>\s*<th[^>]*>.*?</th>\s*<td[^>]*>(.*?)</td>', t, re.S):
            c = counts.setdefault(m.group(1), [0, 0])
            c[0] += 1
            c[1] += re.sub(r"<[^>]+>", "", m.group(2)).strip() == "Absent"
    problems = []
    for o in facts["officials"]:
        f = site / "officials" / f"{o['id']}.html"
        if not f.is_file():
            continue
        m = re.search(r"Recorded absent at (\d+) of (\d+) meetings", f.read_text(encoding="utf-8"))
        listed, absent = counts.get(o["id"], [0, 0])
        if not m:
            problems.append(f"officials/{o['id']}.html: no 'Recorded absent at X of Y meetings' sentence")
        elif (int(m.group(1)), int(m.group(2))) != (absent, listed):
            problems.append(f"officials/{o['id']}.html: page says {m.group(1)} of {m.group(2)}, meeting pages recount {absent} of {listed}")
    return problems, f"{len(facts['officials'])} officials recounted"


class NameLinks(HTMLParser):
    """Visible text nodes of one page with whether each sits inside an <a> and where that <a> points."""
    SKIP = {"script", "style", "title", "option", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None, bool]] = []   # (tag, href for <a>, skip this subtree)
        self.nodes: list[tuple[str, str | None]] = []          # (text, enclosing <a> href or None)

    def handle_starttag(self, tag, attrs):
        if tag in Page.VOID:
            return
        a = dict(attrs)
        # data-variants: the cell listing the spellings merged into an official (not a display of the name)
        self.stack.append((tag, a.get("href") if tag == "a" else None, tag in self.SKIP or "data-variants" in a))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, d):
        if not d.strip() or any(skip for _, _, skip in self.stack):
            return
        href = next((h for t, h, _ in reversed(self.stack) if t == "a" and h is not None), None)
        self.nodes.append((d, href))


def check_name_links(site: Path, facts: dict, roster: list[dict]) -> tuple[list[str], str]:
    """Standing rule: wherever an elected official's name is shown, it links to officials/<id>.html."""
    names = {o["id"]: o["name"] for o in facts["officials"]}
    for r in roster:
        if r.get("official_id") and r["official_id"] not in names:
            names[r["official_id"]] = r.get("name") or " ".join(w.capitalize() for w in r["official_id"].split("-"))
    by_name = {n: oid for oid, n in names.items()}
    pat = re.compile(r"(?<!\w)(" + "|".join(re.escape(n) for n in sorted(by_name, key=len, reverse=True)) + r")(?!\w)")
    problems, checked = [], 0
    pages = sorted(site.rglob("*.html"))
    for f in pages:
        rel = f.relative_to(site).as_posix()
        p = NameLinks()
        p.feed(f.read_text(encoding="utf-8"))
        for text, href in p.nodes:
            if "Provided as a free service by" in text:
                continue
            for m in pat.finditer(text):
                oid = by_name[m.group(1)]
                if rel == f"officials/{oid}.html":
                    continue   # a person's own page names them in its heading
                checked += 1
                target = resolve(rel, href) if href is not None else None
                if target != f"officials/{oid}.html":
                    problems.append(f"{rel}: {names[oid]!r} is not linked to officials/{oid}.html (in {text.strip()[:60]!r})")
    return problems, f"{checked} name links checked on {len(pages)} pages"


def check_footer(pages: dict[str, Page], operator: str) -> list[str]:
    needle = re.compile(r"Provided as a free service by\s+" + re.escape(operator) + r"\.")
    return [f"{rel}: no 'Provided as a free service by {operator}.' footer" for rel, pg in pages.items()
            if not needle.search(" ".join(pg.text))]


def check_external(pages: dict[str, Page]) -> list[str]:
    problems = []
    for rel, pg in pages.items():
        for tag, src in pg.resources:
            if urlsplit(src).scheme or src.startswith("//"):
                problems.append(f"{rel}: third-party <{tag}> {src!r}")
    return problems


def page_type(rel: str) -> str | None:
    if rel == "index.html":
        return "index"
    if rel in ("officials.html", "search.html"):
        return rel[:-5]
    head = rel.split("/")[0]
    return {"officials": "official", "meetings": "meeting", "items": "items", "districts": "district",
            "votes": "votes"}.get(head)


def check_hscroll(site: Path, pages: dict[str, Page], all_pages: bool, sample: int) -> tuple[list[str], str]:
    by_type: dict[str, list[str]] = {}
    for rel in sorted(pages):
        t = page_type(rel)
        if t:
            by_type.setdefault(t, []).append(rel)
    chosen = []
    for t, rels in by_type.items():
        rels = sorted(rels, key=lambda r: (site / r).stat().st_size)
        pick = rels if all_pages or len(rels) <= sample else [rels[-1], rels[len(rels) // 2], rels[0]][:sample]
        chosen += pick
    missing = {"index", "official", "meeting", "items"} - set(by_type)
    if missing:
        return [f"no page of type {sorted(missing)} in the site"], ""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump([{"name": r, "path": str((site / r).resolve())} for r in chosen], tf)
    try:
        env = dict(os.environ)
        if "NODE_PATH" not in env:
            try:
                env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=30).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass
        r = subprocess.run(["node", str(Path(__file__).with_name("hscroll.js")), tf.name, str(VIEWPORT)],
                           capture_output=True, text=True, timeout=600, env=env)
    finally:
        os.unlink(tf.name)
    if r.returncode != 0:
        raise RuntimeError("browser check could not run: " + (r.stderr.strip().splitlines() or ["?"])[-1])
    results = json.loads(r.stdout)
    problems = [f"{x['name']}: scrollWidth {x['scrollWidth']} > {x['width']}; offenders: {', '.join(x['offenders']) or 'none found'}"
                for x in results if x["overflow"]]
    return problems, f"{len(results)} pages at {VIEWPORT}px: " + ", ".join(f"{t} x{sum(1 for c in chosen if page_type(c) == t)}" for t in by_type)


ROW_VIEWPORTS = ((375, 667), (768, 1024), (1000, 800), (1280, 800))


def check_row_height(site: Path, pages: dict[str, Page], sample: int, all_pages: bool) -> tuple[list[str], str]:
    """Owner feedback: no single table entry may run past the screen. Measures every table row at four viewports."""
    by_type: dict[str, list[str]] = {}
    for rel in sorted(pages):
        t = page_type(rel)
        if t:
            by_type.setdefault(t, []).append(rel)
    chosen = []
    for t, rels in by_type.items():
        rels = sorted(rels, key=lambda r: (site / r).stat().st_size)
        chosen += rels if all_pages or len(rels) <= sample else [rels[-1], rels[len(rels) // 2], rels[0]][:sample]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump([{"name": r, "path": str((site / r).resolve())} for r in chosen], tf)
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        try:
            env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    problems, rows = [], 0
    try:
        for w, h in ROW_VIEWPORTS:
            r = subprocess.run(["node", str(Path(__file__).with_name("rowheight.js")), tf.name, str(w), str(h), "0.6"],
                               capture_output=True, text=True, timeout=900, env=env)
            if r.returncode != 0:
                raise RuntimeError("row-height check could not run: " + (r.stderr.strip().splitlines() or ["?"])[-1])
            for x in json.loads(r.stdout):
                rows += x["rows"]
                for o in x["offenders"]:
                    problems.append(f"{x['name']} at {w}x{h}: {o['tag']} is {o['h']}px (limit {int(h * 0.6)}): {o['text']!r}")
    finally:
        os.unlink(tf.name)
    return problems, f"{rows} rows on {len(chosen)} pages at " + ", ".join(f"{w}x{h}" for w, h in ROW_VIEWPORTS)


# ---------------------------------------------------------------- driver

def run_checks(site: Path, facts: dict, internal=False, no_export=False, operator=OPERATOR, browser=True,
               all_pages=False, sample=3, store_extra=(), seats_path=None, districts_path=None) -> Report:
    rep = Report()
    d_seats, d_map = default_inputs(facts)
    seats_path, districts_path = seats_path or d_seats, districts_path or d_map
    cfg = _site_cfg()
    files = [f for f in site.rglob("*") if f.is_file()]
    pages = {f.relative_to(site).as_posix(): parse(f) for f in files if f.suffix == ".html"}
    if not pages:
        rep.add("site", [f"no HTML files under {site}"])
        return rep
    rep.add("files", [f"{len(files)} files, limit {MAX_FILES - 1}"] if len(files) >= MAX_FILES else [], f"{len(files)} files, {len(pages)} pages")
    rep.add("links", check_links(site, pages, no_export), "internal links, #anchors and assets" + ("; data/ skipped" if no_export and not (site / "data").exists() else ""))
    problems, note = check_sources(site, pages, facts, store_extra, allowed_external(cfg, seats_path, districts_path))
    rep.add("sources", problems, note)
    rep.add("unverified", check_unverified(site, pages, facts, internal), "internal build" if internal else "public build")
    fact_ids = {o["id"] for o in facts["officials"]}
    roster_only = tuple(sorted({r["official_id"] for r in read_roster(seats_path) if r.get("official_id")} - fact_ids))
    problems, note = check_index(site, pages, facts, roster_only)
    rep.add("index", problems, "AC1.1: " + note)
    problems, note = check_layout(site, facts)
    rep.add("layout", problems, "AC1.5/N1: " + note)
    problems, note = check_totals(site, pages, facts)
    rep.add("totals", problems, "AC2.2: " + note)
    problems, note = check_provenance(site, pages, facts, read_roster(seats_path), cfg)
    rep.add("provenance", problems, note)
    problems, note = check_name_links(site, facts, read_roster(seats_path))
    rep.add("name-links", problems, note)
    rep.add("footer", check_footer(pages, operator), f"'Provided as a free service by {operator}.' on {len(pages)} pages")
    rep.add("external", check_external(pages))
    if browser:
        try:
            problems, note = check_hscroll(site, pages, all_pages, sample)
            rep.add("hscroll", problems, note)
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            rep.add("hscroll", [str(exc)])
        try:
            problems, note = check_row_height(site, pages, sample, all_pages)
            rep.add("row-height", problems, note)
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            rep.add("row-height", [str(exc)])
    else:
        rep.skip("hscroll", "--no-browser")
        rep.skip("row-height", "--no-browser")
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m qa.site_checks", description=__doc__.split("\n\n")[0])
    ap.add_argument("--site", default=str(ROOT / "build" / "site"))
    ap.add_argument("--facts", default=str(ROOT / "data" / "facts.json"))
    ap.add_argument("--internal", action="store_true", help="the build was made with --internal (review.html allowed)")
    ap.add_argument("--no-export", action="store_true", help="the build has no data/ export (sitegen only, e.g. the fixture)")
    ap.add_argument("--operator", default=OPERATOR)
    ap.add_argument("--no-browser", action="store_true", help="skip the 390 px check")
    ap.add_argument("--all-pages", action="store_true", help="390 px check on every page, not a sample of 3 per type")
    ap.add_argument("--store", action="append", default=[], help="extra directory holding <sha256>.pdf (repeatable)")
    ap.add_argument("--seats", help="the roster the build read (default: the locality's, or the fixture's)")
    ap.add_argument("--districts", help="the map file the build read (default: the locality's, or the fixture's)")
    ap.add_argument("--out", default=str(ROOT / "build" / "qa" / "site_checks.txt"))
    a = ap.parse_args(argv)
    rep = run_checks(Path(a.site), load_facts(a.facts), a.internal, a.no_export, a.operator, not a.no_browser, a.all_pages,
                     store_extra=a.store, seats_path=a.seats, districts_path=a.districts)
    text = rep.render()
    print(text)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print("RESULT: " + ("PASS" if rep.ok else "FAIL"))
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
