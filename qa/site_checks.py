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
  official-numbers  each official page's numbers agree with themselves: one value per data-n key, parts add up to
              their whole, legends and Totals repeat the sentences (site-polish/official-totals-consistent)
  name-links  every occurrence of an official's display name in the visible text of a page is inside an <a> to that
              official's page (standing rule), except in <title>, <option>, item titles (data-item-title: text in
              the document, never linked), the operator lines (footer, About) and on the official's own page
  footer      "Provided as a free service by gnoshcodes LLC." on every page
  brand/no-old-gnoshcodes  no built file carries the old gnoshcodes logo (logo D: its path data or kit file names)
              and none is the old favicon; the footer credit is the hook (gnoshcodes.com)
  external    no third-party scripts, styles, images or fonts (N6); the landing address box's geocoder (called
              only on submit) is exactly config/site.yml geocoder_url; a page that loads static/address.js carries
              its settings block (addr-config); every page has one CSP meta whose script-src is 'self' only, plus
              (only beside the address box) one sha256 hash and exactly geocoder_url
  feeds       every feeds/*.xml is Atom (feed id, title, updated, author, self link; each entry id, title, updated,
              alternate link) with unique tag: ids, newest first, at most alerts.max_entries; each alternate link
              resolves to a built page and its #anchor, each related link is a fetched source document; alerts.html
              links every feed and no other (Alerts v1, sitegen/feeds.py)
  dates/no-raw-utc-day  every fetch day a page, the search index or a feed entry shows is the site_timezone day of
              its source's manifest instant (config/site.yml fetch_manifests), or is labelled "(UTC day)" when the
              source has none (docs/architecture/local-dates.md)
  rpc-cases   (a build with the Regional Planning Commission) every "CASE NUMBER:" and numbered case line an agenda prints was read as a case
              (the completeness check of collector/rpc_agenda.py: a missed case is never silent)
  rpc-motions (a build with the Regional Planning Commission) docs/architecture/rpc-motion-invariant.md, from rpc.json
              alone: a motion block not confirmed holds no names, outcome or case number; a block shown confirmed is
              confirmed in the record, the only disposing motion on its case, under its own agenda case (or the
              meeting's own business with no case), with no nay or abstainer who is its mover or seconder, and none
              is shown confirmed from a record without the reader's current motion_rules; no page with RPC content
              (RPC pages, index, today, any RPC card) says "unanimous" outside the minutes' own words; while
              rpc.yml hold_motions is on, no block is shown confirmed or sits under a case
  rpc-export  (a build with the RPC export) data/<slug>/motions.csv and facts.json hold only motions confirmed in
              rpc.json under the current motion_rules, each on its own meeting's case (or the meeting's own business),
              one disposing motion per case_id, with no confirmed/reasons/tally key or column; each row's values are
              the record's, both files hold the same motions once, no value of a motion left out is in any file, and
              data/<slug>/ holds exactly the export's five files; while rpc.yml hold_motions is on, no motion row
  rpc-morning (a build with the RPC) every morning/*.json RPC vote entry (<body_key>/vote/<motion id>) of a motion
              that is not confirmed in rpc.json, or of any motion while hold_motions is on or motion_rules is not
              current, carries confirmed false, no outcome or tally and none of the motion's names; no vote entry
              of the RPC's body_key has any other id; a pages build with config morning_note set has morning/*.json
  files       at most the target's file cap: --target preview (claude.ai artifact, 500) or pages (GitHub Pages, 3000)
  transcripts every line of a transcript page (<folder>/transcripts/*.html) has its time linked to its meeting's own
              video as <video_url>#t=<whole seconds>, the "Transcript" label and the notice; every call-on entry on a
              member page links a video time; video links (data-ext="video") go only to a meeting's video_url;
              transcript pages carry robots noindex and the privacy line linking report.html
  transcripts/private-addresses  no transcript text (data-transcript: transcript lines, call-on words and excerpts)
              on any page shows a street address or phone number; every committed transcript line passes the same
              rule (masked at rest); no file under data/ and not the search index carries any committed transcript
              line at all (privacy/transcript-private-addresses); problems name the place, never the text
  current-holders  no seat says "Current member not yet recorded" (nor lists its member under Served previously)
              while the latest list names the member last printed in it: a council's latest attendance list, the
              county's confirmed roll calls of the latest meeting (city-seats/current-holder-matches-latest-attendance)
  row-height  no table row (or vote / result list item) taller than 60% of the viewport, with long text clamped and row
              details collapsed, at 375x667, 768x1024, 1000x800 and 1280x800 (contracts pages also at 360x640); needs Playwright (node)
  hscroll     no horizontal scroll at 390 px (contracts pages also at 360 px) for the page types (index, official, meeting, items, and when present
              officials, district, search, votes); needs Playwright (node)

Councils (config/site.yml `councils`, each config/localities/<locality>/council.yml): a real build also has each
council's pages under its folder, built from the council's own facts file. links, sources, unverified, layout, totals,
provenance, name-links, footer, external, hscroll and row-height cover them too, each against the council's facts and
its member pages (<folder>/members/<id>.html); the council's pages are also checked at 360 px.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import json
from collections import defaultdict
import os
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qa.common import OPERATOR, ROOT, find_pdf, load_facts, pdf_page_count  # noqa: E402
# One rule for what QA takes from the build (qa-constants/mixed-sourcing): the NAMES of build outputs (which file is
# which feed) are imported, so a renamed file cannot leave a check looking at nothing; every RULE a page must meet
# (allowed URLs, the CSP, form actions, caps, schemes) is restated in this file and never computed by the code under
# test.
from sitegen.feeds import CONTRACTS_FEED, PER_BODY_FEEDS  # noqa: E402

# Per build target (sitegen.config.MAX_FILES_BY_TARGET says the same): preview 500, under the artifact limit of 511
# files per version; pages 3000 (GitHub Pages has no such limit). MAX_FILES is the preview's.
MAX_FILES_BY_TARGET = {"preview": 500, "pages": 3000}
MAX_FILES = MAX_FILES_BY_TARGET["preview"]
TRANSCRIPT_NOTICE = ("Automatic transcript made by speech-recognition software from the city's video. It may contain "
                     "errors. The video is the record.")
VIEWPORT = 390
NARROW = 360  # AC-F10: the Bids and awards pages are also checked at 360 px


# External links that are not minutes PDFs but are allowed: a holder record's roster source, the map's boundary source,
# the county redistricting page / old-lines map, and the footer support link. Each must be marked data-ext and https.
EXT_KINDS = {"roster", "map", "county", "support", "lookup", "geocoder", "corrections", "video", "operator", "record",
             "listed", "school", "committee", "watch", "provider", "body"}   # listed: an RPC document on a host we do not collect from (Google Drive), linked as listed
# body: About's link to each body's own official site (config/site.yml unofficial.bodies)
# provider: the morning note provider's privacy policy (config morning_note.privacy_url), only while it is enabled
# school: the day page's one plain link to the school board's site (config/site.yml school_board.url; never fetched)
# committee: the committees' "coming" links to their official source pages (config/site.yml committees.links)
# watch: a body's official meeting video page (config/site.yml video.<body>.url; never fetched)
# the data-transcript attribute itself, not data-transcript-foo
TRANSCRIPT_TEXT = re.compile(r"(<(span|p)\b[^>]*\sdata-transcript(?=[\s=/>])[^>]*>)[^<]*(</\2>)")
VIDEO_HREF = re.compile(r"(https://[^#\s]+)(?:#t=(\d+))?")
# Restated from sitegen/config.py VIDEO_HOSTS and sitegen/transcripts.py video_ok (an independent check): times link to
# a meeting's video only when its video_url is https on one of these hosts, a path ending .mp4, with no "#" in it.
VIDEO_HOSTS = ("cpmedia.azureedge.net",)


def video_ok(url) -> bool:
    if not isinstance(url, str) or "#" in url:
        return False
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        return False
    return (u.scheme == "https" and u.hostname in VIDEO_HOSTS and u.netloc == u.hostname and port is None
            and u.path.lower().endswith(".mp4"))


def corrections_links(cfg: dict) -> tuple[str, str]:
    """The report page's channel links as config/site.yml `corrections:` sets them: (GitHub issue form URL, mailto)."""
    c = cfg.get("corrections") or {}
    repo, email = str(c.get("github_repo") or "").strip(), str(c.get("email") or "").strip()
    return (f"https://github.com/{repo}/issues/new?template=correction.yml" if repo else "",
            f"mailto:{email}" if email else "")


REPORT_CHANNEL_TARGETS = ("pages",)   # the hosts real readers use (GitHub Pages); the preview may stay closed


def check_report_channel(pages: dict[str, "Page"], cfg: dict, target: str,
                         form: Path | None = None) -> tuple[list[str], str]:
    """corrections/channel-set-in-production-build: a pages build never ships report.html without a way to send a
    report. It must link the GitHub issue form or the mailto that config/site.yml `corrections:` sets, on the ids
    static/report.js fills (report-issue / report-mail), and must not say corrections are not open yet. With
    github_repo set, the issue form (`form`, default .github/ISSUE_TEMPLATE/correction.yml) must be in this repo
    (corrections/form-on-default-branch: GitHub shows it only from the default branch, which a file check cannot see)."""
    if target not in REPORT_CHANNEL_TARGETS:
        return [], f"{target} target: not checked"
    pg = pages.get("report.html")
    if pg is None:
        return ["report.html is not built"], ""
    issue, mail = corrections_links(cfg)
    if not (issue or mail):
        return ["config/site.yml corrections: sets no github_repo or email, so report.html offers no channel"], ""
    hrefs = set(pg.hrefs)
    problems = [f"report.html does not link {u}" for u in (issue, mail) if u and u not in hrefs]
    problems += [f"report.html has no id={i!r} link (static/report.js fills it)"
                 for u, i in ((issue, "report-issue"), (mail, "report-mail")) if u and i not in pg.ids]
    form = ROOT / ".github" / "ISSUE_TEMPLATE" / "correction.yml" if form is None else Path(form)
    if issue and not form.is_file():
        problems.append(f"corrections.github_repo is set but the issue form {form.name} is not in the repo ({form})")
    if "report-closed" in pg.ids:
        problems.append("report.html still says corrections are not open")
    return problems, "report.html links " + " and ".join(u for u in (issue, mail) if u)


def _site_cfg() -> dict:
    import yaml
    cfg = yaml.safe_load((ROOT / "config" / "site.yml").read_text(encoding="utf-8"))
    if os.environ.get("RECORDS_SITE_URL"):    # the same launch-time override sitegen/config.py applies
        cfg.setdefault("alerts", {})["site_url"] = os.environ["RECORDS_SITE_URL"]
    return cfg


def councils(facts: dict) -> list[dict]:
    """The councils a real build has beside the county: {slug, prefix, facts}. None for a fixture facts file."""
    import yaml
    if facts.get("fixture"):
        return []
    out = []
    for loc in _site_cfg().get("councils") or []:
        c = yaml.safe_load((ROOT / "config" / "localities" / loc / "council.yml").read_text(encoding="utf-8"))
        out.append({"slug": c["slug"], "prefix": c["slug"] + "/", "facts": load_facts(ROOT / c["facts"]),
                    "held_sentences": c.get("held_sentences"),
                    "transcripts_dir": (ROOT / c["facts"]).parent / "transcripts"})
    return out


def rpc_facts(facts: dict) -> dict | None:
    """The Regional Planning Commission facts a real build shows (config/site.yml `rpc:`), or None (a fixture build,
    no `rpc:`, or no facts file yet)."""
    import yaml
    loc = _site_cfg().get("rpc")
    if facts.get("fixture") or not loc:
        return None
    c = yaml.safe_load((ROOT / "config" / "localities" / loc / "rpc.yml").read_text(encoding="utf-8"))
    p = ROOT / c["facts"]
    return {**load_facts(p), "_cfg": c} if p.is_file() else None


def check_rpc_cases(rpc: dict | None) -> tuple[list[str], str]:
    """The completeness check: an agenda that prints "CASE NUMBER:" more times than the cases read from it."""
    if not rpc:
        return [], "no RPC facts"
    read = [m for m in rpc["meetings"] if m.get("case_numbers_printed") is not None]
    problems = [f"{m['id']}: the agenda prints {m['case_numbers_printed']} case numbers (CASE NUMBER: or a numbered case line), "
                f"{m['case_numbers_read']} of those cases read" for m in read
                if m["case_numbers_printed"] > (m.get("case_numbers_read") or 0)]
    return problems, f"{len(read)} agendas read, {sum(m['case_count'] for m in read)} cases"


# rpc-motions (docs/architecture/rpc-motion-invariant.md), restated here from rpc.json alone (no import from collector)
RPC_BUSINESS = {"Motion to elect", "Motion to adjourn", "Motion to approve the minutes",
                "Motion to approve the consent agenda", "Motion to approve the deferrals"}
# the reader's rules (collector/rpc_minutes.py MOTION_RULES): a record written without them shows no motion confirmed
RPC_MOTION_RULES = "rpc-motion-invariant-1"
# `nc`: " nc" (a motion shown not confirmed) or " held" (rpc.yml hold_motions: its type and minutes page only)
MOTION_BLOCK = re.compile(r'<div class="rpc-motion(?P<nc> nc| held)?" id="(?P<id>[^"]+)">(?P<body>.*?)</div>', re.S)
# words a held block never carries (Brian 2026-11-11: no vote content at all while held, not even a "not confirmed" row)
RPC_HELD_WORDS = ("Not confirmed", "Moved by", "seconded by", "Outcome", "Voted nay", "Abstained", "Passed", "Failed",
                  "carried", "unanimous")
RPC_PLACE = re.compile(r'id="(?:case-(?P<case>[^"]+)|(?P<meeting>[^"]+)-motions)"')
ITEM_TITLE_SPAN = re.compile(r"<span data-item-title>.*?</span>", re.S)
# RPC content outside the RPC's own pages: a motion block, or a day card (today.html); the front pages are always read
RPC_CARD = re.compile(r'class="(?:rpc-motion|day-card day-card-rpc)\b')
RPC_FRONT_PAGES = ("index.html", "today.html")


def rpc_held(rpc: dict) -> bool:
    """rpc.yml `hold_motions` (sitegen/rpc.py shown_motions, restated): on, no motion is shown confirmed, none sits
    under a case and none is exported. Anything but false or absent counts as on (the safe side)."""
    return rpc["_cfg"].get("hold_motions", False) is not False


def _rpc_surname(name: str) -> str:
    parts = (name or "").split()
    return re.sub(r"[^a-z]", "", parts[-1].casefold()) if parts else ""


def check_rpc_motions(site: Path, pages: dict[str, "Page"], rpc: dict | None) -> tuple[list[str], str]:
    """Every motion block on the built pages against rpc.json: (a) a block whose motion is not confirmed in the
    record, or that the page marks not confirmed, holds none of its names, outcome or case number, nor "Moved by" /
    "Outcome, as printed"; a block the page shows confirmed is confirmed in the record; (f) a record whose
    `motion_rules` is not the reader's current rules (written before them) has no block shown confirmed, and every
    block of it is held to (a); then for every block shown confirmed: (b) no case holds more than one disposing motion
    (counted by motion id, so a block shown on two pages counts once); (c) it sits under its record's case_id, a case
    on its meeting's agenda, or is the meeting's own business with no case; (d) no nay or abstainer is (by surname)
    its mover or seconder; (e) no page with RPC content (the RPC's own pages, index.html, today.html, any page with an
    RPC card or motion block) says "unanimous" outside the minutes' own words (data-item-title); (g) while rpc.yml
    `hold_motions` is on, no block is shown confirmed or sits under a case, and every block is held to (a); (h) while
    it is on every block is a held block (class "held": no "Not confirmed" row, no vote wording, a minutes link), and
    a held block while it is off is a problem."""
    if not rpc:
        return [], "no RPC facts"
    motions = {mv["id"]: mv for mv in rpc.get("motions", [])}
    cases = {c["id"]: c for c in rpc["cases"]}
    rules = rpc.get("motion_rules")
    on_hold = rpc_held(rpc)
    current = rules == RPC_MOTION_RULES and not on_hold
    problems: list[str] = []
    seen, shown_ok = 0, 0
    per_case: dict[str, set[str]] = defaultdict(set)     # case id -> ids of the disposing motions shown confirmed
    slug = rpc["_cfg"]["slug"]
    for rel in sorted(pages):
        raw = (site / rel).read_text(encoding="utf-8")
        if rel.startswith(slug + "/") or rel in RPC_FRONT_PAGES or RPC_CARD.search(raw):
            plain = html.unescape(re.sub(r"<[^>]+>", " ", ITEM_TITLE_SPAN.sub(" ", raw)))
            if re.search(r"unanimous", plain, re.I):
                problems.append(f"{rel}: says 'unanimous' outside the minutes' own words")
        if 'class="rpc-motion' not in raw:
            continue
        places = [(m.start(), m.group("case"), m.group("meeting")) for m in RPC_PLACE.finditer(raw)]
        for b in MOTION_BLOCK.finditer(raw):
            seen += 1
            mid, body = b.group("id"), html.unescape(b.group("body"))
            mv = motions.get(mid)
            if mv is None:
                problems.append(f"{rel}#{mid}: a motion block with no motion in the RPC facts")
                continue
            confirmed = bool(mv.get("confirmed") is True and not b.group("nc") and current)
            if not b.group("nc") and mv.get("confirmed") is not True:
                problems.append(f"{rel}#{mid}: shown confirmed, not confirmed in the RPC facts")
            if not b.group("nc") and on_hold:
                problems.append(f"{rel}#{mid}: shown confirmed while rpc.yml hold_motions is on")
            elif not b.group("nc") and not current:
                problems.append(f"{rel}#{mid}: shown confirmed, but rpc.json was not written under the reader's "
                                f"current motion rules (motion_rules {rules!r}, want {RPC_MOTION_RULES!r})")
            before = [p for p in places if p[0] < b.start()]
            under = before[-1][1] if before else None
            if on_hold and under:
                problems.append(f"{rel}#{mid}: under case {under} while rpc.yml hold_motions is on")
            if on_hold and b.group("nc") == " nc":
                problems.append(f"{rel}#{mid}: a not confirmed vote row while rpc.yml hold_motions is on "
                                "(a held motion shows its type and minutes page only)")
            if b.group("nc") == " held":
                if not on_hold:
                    problems.append(f"{rel}#{mid}: shown held while rpc.yml hold_motions is off")
                words = [w for w in RPC_HELD_WORDS if re.search(re.escape(w), body, re.I)]
                if words:
                    problems.append(f"{rel}#{mid}: a held motion shows vote wording: {', '.join(words)}")
                if "#page=" not in b.group("body"):
                    problems.append(f"{rel}#{mid}: a held motion without a link to its page of the minutes")
            if not confirmed:
                held = [mv.get("moved_by"), mv.get("seconded_by"), mv.get("outcome"), mv.get("case"),
                        *(mv.get("nays") or []), *(mv.get("abstained") or []), "Moved by", "Outcome, as printed"]
                leak = [h for h in held if h and h in body]
                if leak:
                    problems.append(f"{rel}#{mid}: a motion not confirmed shows {', '.join(sorted(set(leak)))}")
                continue
            shown_ok += 1
            if under and mv["kind"] not in RPC_BUSINESS:
                per_case[under].add(mid)
            if mv.get("case_id"):
                c = cases.get(mv["case_id"])
                if c is None or c["meeting_id"] != mv["meeting_id"] or under != mv["case_id"]:
                    problems.append(f"{rel}#{mid}: confirmed, but not under its own case on its meeting's agenda")
            elif mv["kind"] not in RPC_BUSINESS or under:
                problems.append(f"{rel}#{mid}: confirmed with no agenda case, and not the meeting's own business")
            movers = {_rpc_surname(x) for x in (mv.get("moved_by"), mv.get("seconded_by")) if x}
            if any(_rpc_surname(n) in movers for n in (mv.get("nays") or []) + (mv.get("abstained") or [])):
                problems.append(f"{rel}#{mid}: confirmed, with a nay or abstainer who is its mover or seconder")
    for case, ids in sorted(per_case.items()):
        if len(ids) > 1:
            problems.append(f"case-{case}: {len(ids)} confirmed disposing motions on one case "
                            f"({', '.join(sorted(ids)[:3])})")
    rec = sum(1 for mv in motions.values() if mv.get("confirmed") is True)
    return problems, (f"{seen} motion blocks, {shown_ok} shown confirmed ({rec} confirmed in rpc.json; "
                      + ("hold_motions on; " if on_hold else "") + "motion_rules "
                      + (rules if rules == RPC_MOTION_RULES else f"not current: {rules!r}") + ")")


RPC_EXPORT_HELD_KEYS = ("confirmed", "reasons", "tally")      # never in a site's data/<slug>/ (internal: build/)
RPC_EXPORT_FILES = {"facts.json", "meetings.csv", "cases.csv", "motions.csv", "sources.csv"}
RPC_HELD_FIELDS = ("moved_by", "seconded_by", "outcome", "nays", "abstained")    # what a motion not exported never shows
_RPC_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _rpc_cell(v):
    """A value as collector/export.py _csv writes it (lists joined by "; ", a formula-like text cell after a ')."""
    if isinstance(v, list):
        v = "; ".join(v) if v else None
    if v is None:
        return None
    if isinstance(v, str):
        return "'" + v if v.startswith(_RPC_FORMULA) else v
    return str(v)


def _rpc_held_keys(v, path: str = "") -> list[str]:
    out = []
    if isinstance(v, dict):
        for k, x in v.items():
            if k in RPC_EXPORT_HELD_KEYS:
                out.append(f"key {k} at {path or 'top level'}")
            out += _rpc_held_keys(x, f"{path}.{k}" if path else k)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            out += _rpc_held_keys(x, f"{path}[{i}]")
    return out


def check_rpc_export(site: Path, rpc: dict | None) -> tuple[list[str], str]:
    """The RPC's export (data/<slug>/, collector/rpc_export.py) against rpc.json, as the county guard on
    data/facts.json: every exported motion is `confirmed: true` in the record, which was written under the reader's
    current motion_rules; it sits on its record's case_id, a case on its own meeting's agenda, or is the meeting's own
    business with no case; no case_id holds more than one disposing motion; each row's values (kind, mover, seconder,
    nays, abstainers, outcome, case number, source, page) are the record's; motions.csv and facts.json hold the same
    motions, each once; no value of a motion left out is in any of the files; no file carries a confirmed, reasons or
    tally key (anywhere in facts.json) or column; and data/<slug>/ holds the export's files and nothing else (the
    internal export goes beside the site, in every build); while rpc.yml `hold_motions` is on, no motion row at all.
    An export written without data/<slug>/ fails."""
    if not rpc:
        return [], "no RPC facts"
    slug = rpc["_cfg"]["slug"]
    d = site / "data" / slug
    if not d.is_dir():
        if (site / "data").is_dir():
            return [f"data/{slug}/: missing, beside the rest of data/ (the RPC export)"], ""
        return [], f"no data/{slug}/ export"
    motions = {mv["id"]: mv for mv in rpc.get("motions", [])}
    cases = {c["id"]: c for c in rpc["cases"]}
    sources = {s["id"]: s for s in rpc["sources"]}
    dates = {m["id"]: m["date"] for m in rpc["meetings"]}
    rules = rpc.get("motion_rules")
    on_hold = rpc_held(rpc)
    problems: list[str] = []
    exported: dict[str, list[dict]] = {}
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.relative_to(d).as_posix() not in RPC_EXPORT_FILES:
            problems.append(f"data/{slug}/{p.relative_to(d).as_posix()}: not a file the RPC export writes (a "
                            f"leftover; internal files never go in the site)")
    problems += [f"data/{slug}/{n}: missing" for n in sorted(RPC_EXPORT_FILES) if not (d / n).is_file()]
    csv_name, json_name = f"data/{slug}/motions.csv", f"data/{slug}/facts.json"
    if (d / "motions.csv").is_file():
        with (d / "motions.csv").open(encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            problems += [f"{csv_name}: column {c}" for c in r.fieldnames or [] if c in RPC_EXPORT_HELD_KEYS]
            exported[csv_name] = [{k: (v or None) for k, v in row.items()} for row in r]
    if (d / "facts.json").is_file():
        data = json.loads((d / "facts.json").read_text(encoding="utf-8"))
        problems += [f"{json_name}: {k}" for k in _rpc_held_keys(data)]
        exported[json_name] = data.get("motions", [])
    for name, rows in exported.items():
        per_case: dict[str, set[str]] = defaultdict(set)
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            counts[row.get("id")] += 1
        problems += [f"{name}: motion {mid} is in the file {n} times" for mid, n in sorted(counts.items()) if n > 1]
        for row in rows:
            mid = row.get("id")
            mv = motions.get(mid)
            if on_hold:
                problems.append(f"{name}: motion {mid} exported while rpc.yml hold_motions is on")
                continue
            if mv is None or mv.get("confirmed") is not True or mv.get("reasons"):
                problems.append(f"{name}: motion {mid} is not confirmed in rpc.json")
                continue
            if rules != RPC_MOTION_RULES:
                problems.append(f"{name}: motion {mid} exported, but rpc.json was not written under the reader's "
                                f"current motion rules (motion_rules {rules!r}, want {RPC_MOTION_RULES!r})")
            if mv.get("case_id"):
                c = cases.get(mv["case_id"])
                if c is None or c["meeting_id"] != mv["meeting_id"] or row.get("case_id") != mv["case_id"]:
                    problems.append(f"{name}: motion {mid} is not under its own case on its meeting's agenda")
            elif row.get("case_id") or mv["kind"] not in RPC_BUSINESS:
                problems.append(f"{name}: motion {mid} has no case and is not the meeting's own business")
            if row.get("case_id") and mv["kind"] not in RPC_BUSINESS:
                per_case[row["case_id"]].add(mid)
            # every value as the record holds it (the case number only where the motion is placed on its case)
            want = {"meeting_id": mv["meeting_id"], "kind": mv["kind"], "moved_by": mv.get("moved_by"),
                    "seconded_by": mv.get("seconded_by"), "nays": list(mv.get("nays") or []),
                    "abstained": list(mv.get("abstained") or []), "outcome": mv.get("outcome"),
                    "case_number": mv.get("case") if mv.get("case_id") else None, "page": mv["page"]}
            if name == csv_name:
                s = sources.get(mv["source_id"]) or {}
                want.update(date=dates.get(mv["meeting_id"]), source_url=s.get("url"),
                            source_sha256=s.get("sha256"), fetched_at=s.get("fetched_at"))
                want = {k: _rpc_cell(v) for k, v in want.items()}
            else:
                want["source_id"] = mv["source_id"]
            problems += [f"{name}: motion {mid} {k} is not rpc.json's" for k, v in want.items() if row.get(k) != v]
        problems += [f"{name}: {len(ids)} disposing motions on case {case} ({', '.join(sorted(ids)[:3])})"
                     for case, ids in sorted(per_case.items()) if len(ids) > 1]
    if csv_name in exported and json_name in exported:
        in_csv = {r.get("id") for r in exported[csv_name]}
        in_json = {r.get("id") for r in exported[json_name]}
        if in_csv != in_json:
            parts = [f"only in {w}: {', '.join(sorted(str(x) for x in ids)[:3])}"
                     for w, ids in (("facts.json", in_json - in_csv), ("motions.csv", in_csv - in_json)) if ids]
            problems.append(f"{csv_name} and facts.json hold different motions ({'; '.join(parts)})")
    # no value of a motion left out of the files is in any of them; allowed: a value a shown motion also has, or one
    # the record's agendas, listing or sources print themselves (a member who is also a case's agent, say)
    out_ids = {r.get("id") for rows in exported.values() for r in rows}
    printed = json.dumps([rpc["cases"], rpc["meetings"], rpc["sources"]], ensure_ascii=False)
    shown_vals = [v for mid in out_ids if mid in motions for k in RPC_HELD_FIELDS
                  for v in (motions[mid].get(k) if isinstance(motions[mid].get(k), list) else [motions[mid].get(k)])
                  if v]
    held: dict[str, str] = {}
    for mid, mv in motions.items():
        if mid in out_ids:
            continue
        for k in RPC_HELD_FIELDS:
            for v in (mv.get(k) if isinstance(mv.get(k), list) else [mv.get(k)]):
                if v and v not in held and v not in printed and not any(v in s for s in shown_vals):
                    held[v] = mid
    for n in sorted(RPC_EXPORT_FILES):
        if (d / n).is_file():
            text = (d / n).read_text(encoding="utf-8")
            problems += [f"data/{slug}/{n}: holds {v!r}, a value of motion {mid}, which is not exported"
                         for v, mid in sorted(held.items()) if v in text]
    n = {len(rows) for rows in exported.values()}
    return problems, (f"{'/'.join(str(x) for x in sorted(n))} motions in data/{slug}/motions.csv and facts.json "
                      f"(motion_rules {rules!r}; {'hold_motions on; ' if on_hold else ''}{len(held)} values of "
                      f"motions left out checked)")


def check_rpc_morning(site: Path, rpc: dict | None, note_expected: bool = False) -> tuple[list[str], str]:
    """The morning note (morning/*.json, sitegen/morning.py) against rpc.json, restated: an RPC vote entry (id
    <body_key>/vote/<motion id>) may carry `confirmed: true`, an outcome or a tally only for a motion `confirmed: true`
    in rpc.json under the current motion_rules while rpc.yml `hold_motions` is off; any other carries none of those
    and none of its motion's mover, seconder, nays or abstainers (allowed: a value the record's agendas, listing or
    sources print themselves, as rpc-export). `note_expected` (config morning_note set, a pages build: build.py writes
    the note then): a build with no morning/*.json is a problem, not a pass (rpc-hold/morning-dir-absent). With no
    RPC record (`rpc` None) nothing is checked, a missing note included."""
    if not rpc:
        return [], "no RPC facts"
    notes = sorted((site / "morning").glob("*.json")) if (site / "morning").is_dir() else []
    if note_expected and not notes:
        return ["morning/: no morning note, though config morning_note is set and this is a pages build"], \
            "0 morning notes"
    motions = {mv["id"]: mv for mv in rpc.get("motions", [])}
    on_hold = rpc_held(rpc)
    current = rpc.get("motion_rules") == RPC_MOTION_RULES and not on_hold
    prefix = f"{rpc['_cfg']['body_key']}/vote/"
    printed = json.dumps([rpc["cases"], rpc["meetings"], rpc["sources"]], ensure_ascii=False)
    problems: list[str] = []
    seen = 0
    for f in notes:
        try:
            entries = json.loads(f.read_text(encoding="utf-8")).get("entries") or []
        except (ValueError, AttributeError):
            problems.append(f"morning/{f.name}: not a morning note")
            continue
        for e in entries:
            eid = str(e.get("id") or "")
            if not eid.startswith(prefix):
                # a vote entry of the RPC under any other id would skip every rule below (rpc-hold/morning-id-drift)
                if e.get("kind") == "vote" and e.get("body") == rpc["_cfg"]["body_key"]:
                    problems.append(f"morning/{f.name}: vote entry {eid or '(no id)'} of {e['body']} lacks the "
                                    f"{prefix}<motion id> id")
                continue
            seen += 1
            mid = eid[len(prefix):]
            if on_hold:     # no RPC vote entry at all while held, confirmed or not (Brian, 2026-11-11)
                problems.append(f"morning/{f.name}: {eid}: an RPC vote entry while rpc.yml hold_motions is on")
                continue
            mv = motions.get(mid)
            if current and mv is not None and mv.get("confirmed") is True:
                continue
            why = ("rpc.yml hold_motions is on" if on_hold else "rpc.json's motion_rules is not current"
                   if not current else "not in rpc.json" if mv is None else "not confirmed in rpc.json")
            shown = [k for k in ("outcome", "tally") if e.get(k) is not None]
            if e.get("confirmed") is True:
                shown.insert(0, "confirmed")
            names = [v for k in RPC_HELD_FIELDS if k not in ("outcome",)
                     for v in ((mv or {}).get(k) if isinstance((mv or {}).get(k), list) else [(mv or {}).get(k)])
                     if v and v not in printed and v in json.dumps(e, ensure_ascii=False)]
            if shown or names:
                problems.append(f"morning/{f.name}: {eid} shows {', '.join(shown + sorted(set(names)))} ({why})")
    return problems, (f"{seen} RPC vote entries in {len(notes)} morning notes"
                      + ("; hold_motions on" if on_hold else ""))


def rpc_allowed(rpc: dict | None) -> set[str]:
    """The RPC's record page and every listed link we did not collect (shown with data-ext="listed")."""
    if not rpc:
        return set()
    return {rpc["_cfg"]["record_url"]} | {d["url"] for m in rpc["meetings"] for d in m["documents"]
                                          if not d["fetched"] and d["url"].startswith("https://")}


def calendar_agenda_urls(facts: dict) -> tuple[set[str], list[str]]:
    """(urls, problems): the https agenda links on each council's calendar file whose host is one the locality's config
    names (the council's record_url host, or the api_host of its civicclerk.yml). The today page links a scheduled
    meeting's agenda (data-ext="listed") before the collector has it in the facts. A fixture facts file gives nothing;
    a missing or unreadable calendar or council file is a reported problem, not a crash."""
    out: set[str] = set()
    problems: list[str] = []
    if facts.get("fixture"):
        return out, problems
    for loc in _site_cfg().get("councils") or []:
        base = ROOT / "config" / "localities" / loc
        try:
            c = yaml.safe_load((base / "council.yml").read_text(encoding="utf-8"))
            if not c.get("calendar"):
                continue
            hosts = {urlsplit(c.get("record_url") or "").hostname}
            if (base / "civicclerk.yml").is_file():
                hosts.add((yaml.safe_load((base / "civicclerk.yml").read_text(encoding="utf-8")) or {}).get("api_host"))
            hosts.discard(None)
            rows = json.loads((ROOT / c["calendar"]).read_text(encoding="utf-8"))
        except (OSError, ValueError, AttributeError, KeyError, TypeError, yaml.YAMLError) as e:
            problems.append(f"calendar for {loc}: cannot read ({type(e).__name__}); its agenda links are not allowed")
            continue
        for r in rows if isinstance(rows, list) else []:
            u = r.get("agenda_url") if isinstance(r, dict) else None
            if isinstance(u, str) and u.startswith("https://") and urlsplit(u).hostname in hosts:
                out.add(u)
    return out, problems


def county_agendas(facts: dict) -> dict | None:
    """The county agendas a real build shows (data/county-agendas/agendas.json, collector/county_agenda.py), or None
    (a fixture build, or no agendas file yet). Their PDFs are sources like the minutes; their page is a record link."""
    p = ROOT / "data" / "county-agendas" / "agendas.json"
    if facts.get("fixture") or not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


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


def council_record_urls(cfg: dict) -> set[str]:
    import yaml
    out = set()
    for loc in cfg.get("councils") or []:
        c = yaml.safe_load((ROOT / "config" / "localities" / loc / "council.yml").read_text(encoding="utf-8"))
        if c.get("record_url"):
            out.add(c["record_url"])
    return out


def corrections_log_urls(path: Path | None = None) -> set[str]:
    """The https source_url of each row of the public corrections log (data/corrections-log.json). A malformed log
    adds nothing: the sitegen build rejects it first."""
    p = Path(path) if path else ROOT / "data" / "corrections-log.json"
    if not p.is_file():
        return set()
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return set()
    return {r["source_url"] for r in rows if isinstance(r, dict) and isinstance(r.get("source_url"), str)
            and r["source_url"].startswith("https://")} if isinstance(rows, list) else set()


def allowed_external(cfg: dict, seats_path: Path | None, districts_path: Path | None,
                     corrections_path: Path | None = None) -> set[str]:
    """Exact URLs (qa-weakened/ext-link-any-host): config/site.yml links, the map's source_url, every roster row's
    source and last_source, and the support link only when it is switched on."""
    out = {cfg[k] for k in ("redistricting_page", "old_lines_map_url", "swap_source", "district_lookup_url") if cfg.get(k)}
    if cfg.get("geocoder_url") and cfg.get("geocoder_privacy_url"):
        out.add(cfg["geocoder_privacy_url"])         # the address box's "<geocoder>'s privacy policy" link
    out |= {v["url"] for v in (cfg.get("official_records") or {}).values()}   # "Official record:" lines
    out |= council_record_urls(cfg)
    out |= {b["url"] for b in (cfg.get("unofficial") or {}).get("bodies") or []}   # About's "official sites" list
    if (cfg.get("school_board") or {}).get("url"):
        out.add(cfg["school_board"]["url"])          # the day page's "coming" school board link
    out |= {x["url"] for x in (cfg.get("committees") or {}).get("links") or []   # the committees' "coming" links
            if isinstance(x, dict) and x.get("url")}
    out |= {v["url"] for v in (cfg.get("video") or {}).values()   # the "Watch" links (sitegen/watch.py)
            if isinstance(v, dict) and isinstance(v.get("url"), str) and v["url"].startswith("https://")}
    out |= corrections_log_urls(corrections_path)    # the corrections page's "Source" links
    if cfg.get("operator_url"):
        out.add(cfg["operator_url"])                 # the footer's "gnoshcodes LLC" link
    if cfg.get("support_enabled") is True and cfg.get("support_url"):
        out.add(cfg["support_url"])
    mn = cfg.get("morning_note") or {}
    if mn.get("enabled") is True and mn.get("privacy_url"):
        out.add(mn["privacy_url"])                   # the sign-up form's and the Method page's privacy policy link
    out |= {u for u in corrections_links(cfg) if u.startswith("https://")}   # the report page's GitHub issue link
    if districts_path is not None and Path(districts_path).is_file():
        d = json.loads(Path(districts_path).read_text(encoding="utf-8"))
        out.add(d["source_url"])
        wards = d.get("wards") or {}
        if wards.get("status") == "available" and wards.get("source_url"):
            out.add(wards["source_url"])             # the ward lines' source, named under the address box
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
        self.json_blocks: dict[str, list[str]] = defaultdict(list)   # <script type="application/json" id=...> text
        self.csp: list[str] = []      # every <meta http-equiv="Content-Security-Policy"> content
        self._json_id = None

    def handle_endtag(self, tag):
        if tag == "script":
            self._json_id = None
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
        if tag == "script" and (a.get("type") or "").strip().lower() == "application/json" and a.get("id"):
            self._json_id = a["id"]
            self.json_blocks[a["id"]].append("")
        if tag == "meta" and (a.get("http-equiv") or "").strip().lower() == "content-security-policy":
            self.csp.append(a.get("content") or "")
        if tag == "link" and a.get("href"):
            self.resources.append((tag, a["href"]))
        if tag in ("img", "source", "iframe", "video", "audio") and a.get("src"):
            self.resources.append((tag, a["src"]))
        if tag == "form" and a.get("action"):
            self.resources.append((tag, a["action"]))
        if a.get("formaction"):
            # a button's or input's formaction overrides its form's action, so it meets the same rule
            # (morning-security/qa-formaction-gap); on any tag, since only this check would notice a stray one
            self.resources.append(("formaction", a["formaction"]))

    def handle_data(self, d):
        if self._json_id is not None:
            self.json_blocks[self._json_id][-1] += d
            return
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

LINK_SCHEMES = ("http", "https")


def bad_scheme(href: str) -> bool:
    """A link or resource address with a scheme other than http(s): `javascript:`, `data:`, `vbscript:`, `file:`,
    `mailto:`, `tel:` and the rest (morning-security/href-scheme-defense). A relative address has none. The site's
    one legitimate exception, report.html's mailto from config `corrections:`, is allowed by check_links alone.
    Browsers drop tabs, newlines and leading control characters before reading the scheme; so does this."""
    cleaned = re.sub(r"[\t\n\r]", "", href).lstrip("".join(map(chr, range(0x21))))
    return bool(re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", cleaned)) and urlsplit(cleaned).scheme not in LINK_SCHEMES

def _has_export(site: Path) -> bool:
    """data/ holds the collector's export, not only the README.txt sitegen writes beside it (sitegen/unofficial.py)."""
    d = site / "data"
    return d.is_dir() and any(p.name != "README.txt" for p in d.iterdir())


def check_links(site: Path, pages: dict[str, Page], no_export: bool) -> list[str]:
    problems = []
    mailto = corrections_links(_site_cfg())[1]   # the one mailto allowed: report.html's, from config `corrections:`
    for rel, pg in pages.items():
        for href in pg.hrefs:
            u = urlsplit(href)
            if u.scheme in ("http", "https"):
                continue
            if mailto and rel == "report.html" and href == mailto:
                continue
            if u.scheme or href.startswith("//") or bad_scheme(href):
                problems.append(f"{rel}: href with scheme {href!r}")
                continue
            target = resolve(rel, href)
            if target is None:
                problems.append(f"{rel}: href {href!r} leaves the site")
                continue
            if no_export and target.startswith("data/") and target != "data/README.txt" and not _has_export(site):
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
            if bad_scheme(src):     # never skipped: a javascript: form action or a data: script is a failure
                problems.append(f"{rel}: {'formaction' if tag == 'formaction' else f'<{tag}>'} with scheme {src!r}")
                continue
            if urlsplit(src).scheme or src.startswith("//"):
                continue
            target = resolve(rel, src)
            if target is None or not (site / target).is_file():
                problems.append(f"{rel}: <{tag}> {src!r} not found")
    return problems


def check_sources(site: Path, pages: dict[str, Page], facts: dict, store_extra,
                  allowed: set[str] | None = None, fin: dict | None = None,
                  videos: set[str] | None = None) -> tuple[list[str], str]:
    """`allowed`: the exact external URLs a page may link that are not minutes PDFs (allowed_external). `videos`: the
    meetings' video_url values; a data-ext="video" link is one of them, alone or with #t=<whole seconds>."""
    allowed = set() if allowed is None else allowed
    videos = set() if videos is None else videos
    problems = []
    # a finance document that was never fetched (a .docx, a dead or link-only URL) has no source row but is a listed link
    doc_urls = {d["url"] for d in (fin or {}).get("documents", []) if d.get("url")}
    by_url = {}
    for s in [*facts["sources"], *(fin or {}).get("sources", [])]:  # finance.json shares the source ids (ADR 0002)
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
            if src is None and rel.startswith("contracts/") and base in doc_urls:
                continue
            if src is None and ext == "video":
                m = VIDEO_HREF.fullmatch(href)
                if not m or m.group(1) not in videos:
                    problems.append(f"{rel}: video link {href!r} is not a meeting's video_url with an optional #t=<seconds>")
                continue
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
                if href in pg.fact_hrefs and not rel.startswith("contracts/"):
                    # contracts pages: a row's document link names a whole document and has no page by design; their
                    # page citations are held to #page by tests/test_fin_pages.py (provenance/*)
                    problems.append(f"{rel}: fact-row source link {href!r} has no #page=N")
                else:
                    doc_level += 1      # e.g. the meeting page header "minutes PDF, 25 pages": names the document, not a fact
                continue
            n = int(m.group(1))
            if not src.get("pages"):      # no page count (agenda-data/pages-none): a #page link cannot be checked
                problems.append(f"{rel}: {href!r}: source {src['id']} has no page count")
                continue
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


ID_RUN = re.compile(r"[A-Za-z0-9_/-]+")


def id_prefixes(body: str) -> set[str]:
    """Every string an id token can match in `body` under _contains' boundaries: each maximal run of id characters,
    cut at each '/'. One pass per file, so a big page is scanned once for all id tokens, not once per token."""
    out: set[str] = set()
    for m in ID_RUN.finditer(body):
        run = m.group(0)
        i = run.find("/")
        while i >= 0:
            out.add(run[:i])
            i = run.find("/", i + 1)
        out.add(run)
    return out


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


def finance_fact_ids(fin: dict | None) -> set[str]:
    """Fact ids the finance pages may carry (sitegen/fin_views.py, budget_views.py): solicitation, its documents, its
    bidders; each budget line by its line id, and each fund as fund/<fund_no>."""
    ids: set[str] = set()
    for s in (fin or {}).get("solicitations", []):
        ids.add(s["id"])
        ids |= {f"{s['id']}/{d}" for d in s["document_ids"]}
        if s["bid_tab"]:
            ids |= {f"{s['id']}/bidder/{b['printed_order']}" for b in s["bid_tab"]["bidders"]}
    for x in (fin or {}).get("budget_lines", []):
        ids |= {x["id"], f"fund/{x['fund_no']}"}
    return ids


def held_sentence(rc: dict, sentences: dict) -> str:
    """A held roll call's sentence (council.yml held_sentences): attendance_verified's whenever it failed; else its
    one failed check's, names_resolve and surnames_resolve counted as one; else `other`. outcome_consistent with no
    outcome read (outcome `other`) has no sentence of its own (its sentence speaks of a stated outcome)."""
    failed = {"names_resolve" if c["check"] == "surnames_resolve" else c["check"]
              for c in rc["verification"]["checks"] if not c["ok"]}
    if rc.get("outcome") not in ("passed", "failed"):
        failed = {"outcome_not_read" if f == "outcome_consistent" else f for f in failed}
    one = "attendance_verified" if "attendance_verified" in failed else next(iter(failed)) if len(failed) == 1 else None
    return (sentences.get(one) or sentences["other"]) if one else sentences["other"]


def check_unverified(site: Path, pages: dict[str, Page], facts: dict, internal: bool,
                     show_values: bool | None = None, fin: dict | None = None, official_prefix: str = "officials/",
                     export: bool = True, held_sentences: dict | None = None) -> list[str]:
    """`pages`: the pages built from `facts` (a council's pages are checked against the council's facts, with its
    member pages under `official_prefix`); the token scan always covers every file. `export`: data/facts.json is
    this facts file's export. `held_sentences`: the council's sentence per held check (council.yml), so each held
    roll call must show its own."""
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
        if not f.is_file() or rel == "review.html" or f.suffix not in (".html", ".csv", ".json", ".js", ".css", ".txt", ".md", ".xml"):
            continue
        body = f.read_text(encoding="utf-8", errors="replace")
        body = body + "\n" + html.unescape(body)
        ids = None
        for tok, why in toks:
            if internal and rel.startswith("data/") and " text" in why:
                continue    # an --internal export carries raw outcome text by design; its pages still must not
            if " text" in why:
                hit = tok in body
            else:   # the same boundaries as _contains, from one scan of the file
                if ids is None:
                    ids = id_prefixes(body)
                hit = tok in ids
            if hit:
                problems.append(f"{rel}: contains {tok!r} ({why})")
    # every fact id on a page is a shown fact; every shown fact is on its official's page
    shown, hidden = shown_fact_ids(facts)
    on_official: set[str] = set()
    known = ({r["id"] for r in facts["roll_calls"]} | {m["id"] for m in facts["motions"]} | {e["id"] for e in facts["item_events"]}
             | {m["id"] for m in facts["meetings"]}) | finance_fact_ids(fin)
    for rel, pg in pages.items():
        for fid in pg.fact_ids:
            if fid in hidden:
                problems.append(f"{rel}: shows hidden fact {fid}")
            elif fid not in shown and fid not in known and not rel == "review.html":
                problems.append(f"{rel}: fact id {fid} is not in the facts file")
            if rel.startswith(official_prefix):
                on_official.add(fid)
    for fid in sorted(shown - on_official):
        problems.append(f"shown fact {fid} is on no official page")
    # every fact row or block showing an unconfirmed roll call carries the fixed note inside that row or block, and a
    # row or block of a confirmed roll call carries neither the note nor a "*"
    unconfirmed = {r["id"] for r in facts["roll_calls"] if r["verification"]["status"] == "unverified"}
    confirmed = {r["id"] for r in facts["roll_calls"] if r["verification"]["status"] == "verified"}
    rc_event = {e["id"]: e["ref"] for e in facts["item_events"] if e["type"] == "roll_call"}
    note = "Not confirmed: this page was hard to read."
    # a council with held_sentences: each held roll call shows the sentence of the check that held it, never the
    # generic note (the rule restated from council.yml, not called from sitegen: city-verify V5)
    expected = {r["id"]: held_sentence(r, held_sentences) for r in facts["roll_calls"]
                if r["verification"]["status"] == "unverified"} if held_sentences else {}
    every_note = {note, *(held_sentences or {}).values()}
    for rel, pg in pages.items():
        if rel == "review.html":
            continue
        for fid, text in pg.fact_texts:
            rc = rc_event.get(fid, fid.split("/")[0])
            text = html.unescape(text)
            want = expected.get(rc, note)
            if rc in unconfirmed and want not in text:
                problems.append(f"{rel}: {fid} shows an unconfirmed roll call without the 'Not confirmed' note"
                                + (f" of its check ({want!r})" if rc in expected else ""))
            elif rc in unconfirmed and rc in expected and any(n in text for n in every_note - {want}):
                problems.append(f"{rel}: {fid} shows an unconfirmed roll call with another check's note")
            elif rc in confirmed and (any(n in text for n in every_note) or "*" in text):
                problems.append(f"{rel}: {fid} shows a confirmed roll call with a '*' or the 'Not confirmed' note")
            # a Moved or Seconded row (shown only for a verified motion) never carries a roll call's note as its own:
            # a held roll call's outcome is named as the roll call's (city-verify/moved-row-note-ambiguous)
            if fid.endswith(("/moved", "/seconded")) and any(n in text for n in every_note):
                problems.append(f"{rel}: {fid} carries a roll call's 'Not confirmed' note as if the motion were held")
            if rc in unconfirmed and not show_values and (m := PARSED_VALUE.search(text)):
                problems.append(f"{rel}: {fid} shows a parsed value {m.group(0)!r} of an unconfirmed roll call")
    # SHOW_UNCONFIRMED_VALUES off: the public export carries no value, outcome or tally of an unconfirmed roll call
    export_file = site / "data" / "facts.json"
    if export and not internal and not show_values and export_file.is_file():
        for r in json.loads(export_file.read_text(encoding="utf-8")).get("roll_calls", []):
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


def check_layout(site: Path, facts: dict, folder: str = "officials") -> tuple[list[str], str]:
    skel = {o["id"]: _skeleton((site / folder / f"{o['id']}.html").read_text(encoding="utf-8"))
            for o in facts["officials"] if (site / folder / f"{o['id']}.html").is_file()}
    if not skel:
        return [f"no official pages under {folder}/"], ""
    ref_id, ref = next(iter(skel.items()))
    return [f"{folder}/{i}.html differs in headings/columns from {folder}/{ref_id}.html" for i, k in skel.items() if k != ref], \
        f"{len(skel)} official pages under {folder}/, same {len(ref[0])} headings and {len(ref[1])} column header set(s)"


# ---------------------------------------------------------------- provenance (derived vs stated)
# Restated from the architecture's invariant `provenance`, not imported from sitegen.
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DATE_PHRASES = ("seen in roll calls", "shown as vacant in roll calls", "roll calls", "seen in attendance lists",
                "shown as vacant in attendance lists", "attendance lists",
                # a record that starts at a configured seating (council.yml evidence.configured, sitegen/council.py
                # CONFIGURED_EVIDENCE): the cited minutes that record it (site-checks/provenance-claunch-seat-text)
                "seen in the minutes that record the seating")
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
        # transcript text (data-transcript) is what the speech-recognition software wrote, shown verbatim: its words
        # are the speakers', not the site's seat wording
        plain = html.unescape(TRANSCRIPT_TEXT.sub(r"\1\3", body))
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


def check_totals(site: Path, pages: dict[str, Page], facts: dict, meetings: str = "meetings/",
                 folder: str = "officials") -> tuple[list[str], str]:
    """AC2.2: each 'Recorded absent at X of Y meetings' equals a recount from the built meeting pages (`meetings`:
    their folder; a council's are one page per year) on the official pages under `folder`."""
    counts: dict[str, list[int]] = {}
    for rel in pages:
        if not rel.startswith(meetings):
            continue
        t = (site / rel).read_text(encoding="utf-8")
        for m in re.finditer(r'data-fact-id="[^"]+/att/([^"]+)"[^>]*>\s*<th[^>]*>.*?</th>\s*<td[^>]*>(.*?)</td>', t, re.S):
            c = counts.setdefault(m.group(1), [0, 0])
            c[0] += 1
            c[1] += re.sub(r"<[^>]+>", "", m.group(2)).strip() == "Absent"
    problems = []
    for o in facts["officials"]:
        f = site / folder / f"{o['id']}.html"
        if not f.is_file():
            continue
        m = re.search(r"Recorded absent at (\d+) of (\d+) meetings", f.read_text(encoding="utf-8"))
        listed, absent = counts.get(o["id"], [0, 0])
        if not m:
            problems.append(f"{folder}/{o['id']}.html: no 'Recorded absent at X of Y meetings' sentence")
        elif (int(m.group(1)), int(m.group(2))) != (absent, listed):
            problems.append(f"{folder}/{o['id']}.html: page says {m.group(1)} of {m.group(2)}, meeting pages recount {absent} of {listed}")
    return problems, f"{len(facts['officials'])} officials under {folder}/ recounted"


DATA_N = re.compile(r'data-n="([a-z_-]+)"[^>]*>(\d+)<')
VOTE_KEYS = ("yes", "no", "abstain", "other")


def official_number_problems(text: str) -> list[str]:
    """site-polish/official-totals-consistent, restated here (no call into sitegen): on one official page every number
    marked data-n shows the same value wherever it appears, the parts add up to their whole (meetings present + absent
    = meetings listed; votes + roll calls while absent + no vote recorded = roll calls; Yes + No + Abstain + Other =
    votes; each bar's legend equals the sentence above it), and the Totals sentences repeat the same numbers."""
    seen: dict[str, set[int]] = defaultdict(set)
    for k, n in DATA_N.findall(text):
        seen[k].add(int(n))
    out = [f"{k} shows {sorted(v)}" for k, v in sorted(seen.items()) if len(v) > 1]
    n = {k: next(iter(v)) for k, v in seen.items()}
    need = ("meetings_listed", "present", "absent", "rc_total", "rc_voted", "rc_absent", "rc_novote", "rc_total_nc",
            "rc_voted_nc", "rc_absent_nc", "rc_novote_nc", "att-present", "att-absent",
            *(f"vote-{k}" for k in (*VOTE_KEYS, "absent", "novote")))
    missing = [k for k in need if k not in n]
    if missing:
        return out + [f"no data-n for {', '.join(missing)}"]

    def eq(label: str, a: int, b: int) -> None:
        if a != b:
            out.append(f"{label}: {a} != {b}")
    eq("present + absent = meetings listed", n["present"] + n["absent"], n["meetings_listed"])
    eq("attendance legend present", n["att-present"], n["present"])
    eq("attendance legend absent", n["att-absent"], n["absent"])
    for sfx, leg in (("", "vote-"), ("_nc", "vote-nc-")):
        eq(f"rc_voted{sfx} + rc_absent{sfx} + rc_novote{sfx} = rc_total{sfx}",
           n["rc_voted" + sfx] + n["rc_absent" + sfx] + n["rc_novote" + sfx], n["rc_total" + sfx])
        if all(f"{leg}{k}" in n for k in VOTE_KEYS):   # the not confirmed legend exists only with values shown
            eq(f"{leg}Yes+No+Abstain+Other = rc_voted{sfx}", sum(n[f"{leg}{k}"] for k in VOTE_KEYS), n["rc_voted" + sfx])
            eq(f"{leg}absent legend", n[f"{leg}absent"], n["rc_absent" + sfx])
            eq(f"{leg}novote legend", n[f"{leg}novote"], n["rc_novote" + sfx])
    plain = re.sub(r"<[^>]+>", "", html.unescape(text))
    m = re.search(r"Recorded absent at (\d+) of (\d+) meetings", plain)
    if not m:
        out.append("no 'Recorded absent at X of Y meetings' sentence")
    else:
        eq("Totals: absent", int(m.group(1)), n["absent"])
        eq("Totals: meetings", int(m.group(2)), n["meetings_listed"])
    m = re.search(r"Roll call votes, \S+ to \S+: (\d+) Yes, (\d+) No, (\d+) Abstain, (\d+) Other confirmed; "
                  r"(?:(\d+) votes? in not confirmed\* roll calls|(\d+) Yes\*, (\d+) No\*, (\d+) Abstain\*, (\d+) Other\*)",
                  plain)
    if not m:
        out.append("no 'Roll call votes' totals sentence")
    else:
        g = [int(x) if x is not None else None for x in m.groups()]
        for k, v in zip(VOTE_KEYS, g[:4]):
            eq(f"Totals: {k}", v, n[f"vote-{k}"])
        eq("Totals: not confirmed votes", g[4] if g[4] is not None else sum(g[5:]), n["rc_voted_nc"])
    return out


def check_official_numbers(site: Path, facts: dict, folder: str = "officials") -> tuple[list[str], str]:
    problems, n = [], 0
    for o in facts["officials"]:
        f = site / folder / f"{o['id']}.html"
        if not f.is_file():
            continue
        n += 1
        problems += [f"{folder}/{o['id']}.html: {p}" for p in official_number_problems(f.read_text(encoding="utf-8"))]
    return problems, f"{n} official pages under {folder}/ agree with themselves"


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
        # data-variants: the cell listing the spellings merged into an official (not a display of the name).
        # data-item-title: an item's title as the minutes print it; a name in it is text in the document (an
        # applicant or buyer may share an official's name), never linked (manager decision 2026-11-09).
        # data-transcript: speech-recognition text, shown verbatim; a name in it is never linked (AC6.3)
        self.stack.append((tag, a.get("href") if tag == "a" else None,
                           tag in self.SKIP or "data-variants" in a or "data-item-title" in a or "data-transcript" in a))

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


def check_name_links(site: Path, facts: dict, roster: list[dict], councils_=()) -> tuple[list[str], str]:
    """Standing rule: wherever an elected official's name is shown, it links to officials/<id>.html (a council
    member's: <folder>/members/<id>.html). A name two people share may link to either one's page."""
    names = {o["id"]: o["name"] for o in facts["officials"]}
    for r in roster:
        if r.get("official_id") and r["official_id"] not in names:
            names[r["official_id"]] = r.get("name") or " ".join(w.capitalize() for w in r["official_id"].split("-"))
    pages_of: dict[str, set[str]] = defaultdict(set)   # display name -> the official pages it may link to
    for oid, n in names.items():
        pages_of[n].add(f"officials/{oid}.html")
    for c in councils_:
        for o in c["facts"]["officials"]:
            pages_of[o["name"]].add(f"{c['prefix']}members/{o['id']}.html")
    pat = re.compile(r"(?<!\w)(" + "|".join(re.escape(n) for n in sorted(pages_of, key=len, reverse=True)) + r")(?!\w)")
    problems, checked = [], 0
    pages = sorted(site.rglob("*.html"))
    for f in pages:
        rel = f.relative_to(site).as_posix()
        p = NameLinks()
        p.feed(f.read_text(encoding="utf-8"))
        for text, href in p.nodes:
            if "Provided as a free service by" in text or "This site is run by" in text:   # the operator lines (footer, About)
                continue
            for m in pat.finditer(text):
                allowed = pages_of[m.group(1)]
                if rel in allowed:
                    continue   # a person's own page names them in its heading
                checked += 1
                target = resolve(rel, href) if href is not None else None
                if target not in allowed:
                    problems.append(f"{rel}: {m.group(1)!r} is not linked to {' or '.join(sorted(allowed))} (in {text.strip()[:60]!r})")
    return problems, f"{checked} name links checked on {len(pages)} pages"


# The old gnoshcodes logo ("logo D", brand kit v1: a pixel ring and a pixel-to-curve wordmark), replaced by the hook
# (gnoshcodes.com) before launch. Signatures: the mark's pixel ring and its arc (every mark, lockup, stacked and
# app-icon file of the kit), the wordmark's pixel "g" and its "s" curve (the wordmark files), the kit's file names,
# and the kit favicon's bytes (sha1).
OLD_BRAND_SIGNATURES = (b"M8 20h6v6h-6z", b"M32 11A21 21 0 0 1 32 53", b"M-2 24h4v4h-4z", b"L94 22L89.05 23.46")
OLD_BRAND_NAMES = re.compile(rb"gnoshcodes-(?:(?:wordmark|mark|lockup|stacked)-(?:color-light|color-dark|black|blue|white)|app-icon)\b")
OLD_BRAND_FAVICON_SHA1 = "b6d981bbbdab7d4fa9fd2d2234f3e2950ce9c488"


def check_old_brand(site: Path) -> tuple[list[str], str]:
    """brand/no-old-gnoshcodes: no built file (pages, styles, scripts, images, feeds, data) carries the old gnoshcodes
    logo's path data or file names, no file is named like the old kit, and no file is the old favicon."""
    problems, n = [], 0
    for f in sorted(p for p in site.rglob("*") if p.is_file()):
        rel, n = f.relative_to(site).as_posix(), n + 1
        if OLD_BRAND_NAMES.search(rel.encode()):
            problems.append(f"{rel}: named like the old gnoshcodes logo kit")
        body = f.read_bytes()
        if hashlib.sha1(body).hexdigest() == OLD_BRAND_FAVICON_SHA1:
            problems.append(f"{rel}: is the old gnoshcodes favicon")
        hits = sum(sig in body for sig in OLD_BRAND_SIGNATURES) + len(OLD_BRAND_NAMES.findall(body))
        if hits:
            problems.append(f"{rel}: {hits} old gnoshcodes logo signature(s) (path data or file name)")
    return problems, f"{n} files scanned for the old logo's path data, file names and favicon"


def check_footer(pages: dict[str, Page], operator: str) -> list[str]:
    needle = re.compile(r"Provided as a free service by\s+" + re.escape(operator) + r"\s*\.")
    return [f"{rel}: no 'Provided as a free service by {operator}.' footer" for rel, pg in pages.items()
            if not needle.search(" ".join(pg.text))]


ADDRESS_JS = re.compile(r"(^|/)static/address\.js$")
CSP_FIXED = {"default-src": ["'self'"], "connect-src": ["'none'"], "object-src": ["'none'"], "base-uri": ["'none'"],
             "frame-src": ["'self'"], "img-src": ["'self'", "data:"], "form-action": ["'self'"]}
HASH_SRC = re.compile(r"'sha256-[A-Za-z0-9+/]{43}='")


def parse_csp(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for part in text.split(";"):
        bits = part.split()
        if bits:
            out.setdefault(bits[0].lower(), bits[1:])
    return out


NOTE_PAGE = "alerts.html"   # the morning note's sign-up form (sitegen/morning_page.py)


def check_external(pages: dict[str, Page], site: Path | None = None, cfg: dict | None = None) -> list[str]:
    """No third-party resource in the HTML. The one runtime call out, the landing address box's geocoder (only on
    submit, from a sandboxed iframe), may go only to config/site.yml geocoder_url, exactly: the box's settings block
    and the page's CSP script-src both hold it. A page that loads address.js without its settings block fails
    (qa-guard/addr-config-silent-miss), as does a page without the CSP meta (third-party-script/no-csp)."""
    problems = []
    # The one form that may post off the site: the morning note's sign-up form on alerts.html, only while config
    # morning_note.enabled is true, and only to its form_action exactly; that page's CSP form-action then holds
    # 'self' and that one origin (restated here, not called from sitegen/morning_page.py).
    mn = (cfg or {}).get("morning_note") or {}
    note_action = mn.get("form_action") if mn.get("enabled") is True and isinstance(mn.get("form_action"), str) else None
    for rel, pg in pages.items():
        for tag, src in pg.resources:
            if tag in ("form", "formaction") and note_action and rel == NOTE_PAGE and src == note_action \
                    and src.startswith("https://"):
                continue
            if urlsplit(src).scheme or src.startswith("//"):
                what = "formaction on a button or input" if tag == "formaction" else f"<{tag}>"
                problems.append(f"{rel}: third-party {what} {src!r}")
    if site is None:
        return problems
    want = (cfg or {}).get("geocoder_url") or None
    for rel, pg in pages.items():
        blocks = pg.json_blocks.get("addr-config", [])
        loads = any(t == "script" and ADDRESS_JS.search(src) for t, src in pg.resources)
        if loads and not blocks:
            problems.append(f"{rel}: loads static/address.js without its addr-config settings block")
        if len(blocks) > 1:
            problems.append(f"{rel}: {len(blocks)} addr-config settings blocks")
        if blocks and not loads:
            problems.append(f"{rel}: addr-config settings block without static/address.js")
        for raw in blocks:
            try:
                got = json.loads(raw)
                geo = got.get("geocoder")
            except (ValueError, AttributeError):
                problems.append(f"{rel}: address box settings are not a JSON object")
                continue
            if not want or geo != want:
                problems.append(f"{rel}: address box geocoder {geo!r} is not config geocoder_url {want!r}")
            if not isinstance(got.get("frame"), str) or not got["frame"]:
                problems.append(f"{rel}: address box settings carry no frame script")
        if len(pg.csp) != 1:
            problems.append(f"{rel}: {len(pg.csp)} Content-Security-Policy metas (want 1)")
            continue
        pol = parse_csp(pg.csp[0])
        for k, v in CSP_FIXED.items():
            if k == "form-action" and note_action and rel == NOTE_PAGE:
                u = urlsplit(note_action)
                v = [*v, f"{u.scheme}://{u.netloc}"]
            if pol.get(k) != v:
                problems.append(f"{rel}: CSP {k} is {pol.get(k)!r}, want {v!r}")
        scripts = pol.get("script-src")
        if blocks:
            hashes = [x for x in scripts or [] if HASH_SRC.fullmatch(x)]
            ok = scripts is not None and "'self'" in scripts and len(hashes) == 1 and want in scripts and \
                len(scripts) == 3
        else:
            ok = scripts == ["'self'"]
        if not ok:
            problems.append(f"{rel}: CSP script-src {scripts!r} is not 'self'"
                            + (" + one sha256 + geocoder_url" if blocks else " only"))
        elif blocks:
            try:
                frame = json.loads(blocks[0]).get("frame") or ""
            except (ValueError, AttributeError):
                frame = ""
            digest = base64.b64encode(hashlib.sha256(frame.encode("utf-8")).digest()).decode("ascii")
            if f"'sha256-{digest}'" not in scripts:
                problems.append(f"{rel}: CSP script hash is not the address box's frame script")
    return problems


class UnofficialText(HTMLParser):
    """The text a visitor can see in a page's <footer> and in its `.unofficial-tag` element(s). Comments are not text;
    script, style, template and noscript content is not shown; an element with `hidden`, aria-hidden="true" or an
    inline display:none / visibility:hidden hides everything inside it."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track",
            "wbr"}
    SKIP = {"script", "style", "template", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []        # (tag, hidden, in_footer, in_tag)
        self.footer, self.tags = [], []   # tags: the text parts of each visible .unofficial-tag element

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        _, hid, foot, intag = self.stack[-1] if self.stack else ("", False, False, False)
        style = (a.get("style") or "").replace(" ", "").lower()
        hid = (hid or tag in self.SKIP or "hidden" in a or (a.get("aria-hidden") or "").lower() == "true"
               or "sr-only" in (a.get("class") or "").split() or bool(INLINE_HIDE.search(style)))
        is_tag = "unofficial-tag" in (a.get("class") or "").split()
        if is_tag and not hid and not intag:
            self.tags.append([])
        if tag not in self.VOID:
            self.stack.append((tag, hid, foot or tag == "footer", intag or (is_tag and not hid)))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self.stack and not self.stack[-1][1]:
            if self.stack[-1][2]:
                self.footer.append(data)
            if self.stack[-1][3]:
                self.tags[-1].append(data)


_ZERO = r"(?:0+(?:\.0*)?|\.0+)[a-z%]*(?=\s*(?:;|!|$))"   # 0, 0.0, .0, 0px, 0em, 0% (not 0.5)
INLINE_HIDE = re.compile(rf"display:none|visibility:hidden|opacity:{_ZERO}|font-size:{_ZERO}")
CSS_HIDE = re.compile(rf"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*{_ZERO}|font-size\s*:\s*{_ZERO}",
                      re.M)
FOOTER_SUBJECT = re.compile(r"^(?:footer|\.site-footer)(?![\w-])")


def _hides_notice(selector: str) -> bool:
    """A selector that can hide the notice: one naming an unofficial-* class, one whose subject is the footer, or one
    whose subject is a section inside the footer (`footer section`, `.site-footer > section`)."""
    if "unofficial" in selector:
        return True
    parts = [p for p in re.split(r"\s*[>+~]\s*|\s+", selector.strip()) if p]
    if not parts:
        return False
    return bool(FOOTER_SUBJECT.match(parts[-1])) or (
        parts[-1].startswith("section") and any(FOOTER_SUBJECT.match(p) for p in parts[:-1]))


def _hiding_rules(site: Path) -> list[str]:
    """Selectors in the built style.css that can hide the notice (_hides_notice) with display:none, visibility:hidden,
    opacity:0 or font-size:0."""
    css = site / "static" / "style.css"
    text = re.sub(r"/\*.*?\*/", "", css.read_text(encoding="utf-8"), flags=re.S) if css.is_file() else ""
    return [" ".join(sel.split()) for group, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text) if CSS_HIDE.search(body)
            for sel in group.split(",") if _hides_notice(sel)]


def unofficial_notice(cfg: dict) -> str:
    """The notice text, restated from config/site.yml `unofficial:` (not called from sitegen's templates)."""
    names = [b["name"] for b in cfg["unofficial"]["bodies"]]
    joined = ", ".join(names[:-1]) + ", or " + names[-1] if len(names) > 2 else " or ".join(names)
    return " ".join(cfg["unofficial"]["notice"].format(site_name=cfg["site_name"], operator=cfg["operator"],
                                                       bodies=joined).split())


def check_unofficial(site: Path, pages: dict[str, Page], cfg: dict | None = None) -> tuple[list[str], str]:
    """unofficial/notice-on-every-page: the independent-and-unofficial notice (config/site.yml `unofficial:`) is in the
    text of every built HTML page, in its <meta name=description> and og:description, with the tag in its <title> and
    beside the site name; in every feed's subtitle; in every morning note's "notice" and "email_line"; and in
    data/README.txt when the build has an export. Each missing one is a problem."""
    import xml.etree.ElementTree as ET
    cfg = _site_cfg() if cfg is None else cfg
    u = cfg.get("unofficial")
    if not u:
        return ["config/site.yml has no unofficial: block"], ""
    notice = unofficial_notice(cfg)
    problems = [f"static/style.css: {sel!r} hides the unofficial notice" for sel in _hiding_rules(site)]
    for rel in sorted(pages):
        raw = (site / rel).read_text(encoding="utf-8")
        seen = UnofficialText()
        seen.feed(raw)
        seen.close()
        if notice not in " ".join("".join(seen.footer).split()):
            problems.append(f"{rel}: the unofficial notice is not in the page text (visible, in the footer)")
        if not seen.tags or any(" ".join("".join(t).split()) != u["tag"] for t in seen.tags):
            problems.append(f"{rel}: no visible '{u['tag']}' tag by the site name")
        meta = re.findall(r'<meta\s+(?:name="description"|property="og:description")\s+content="([^"]*)"', raw)
        if len(meta) != 2 or any(" ".join(html.unescape(m).split()) != notice for m in meta):
            problems.append(f"{rel}: description and og:description meta tags do not both carry the notice")
        lead = f"{cfg['site_name']} ({u['tag'].lower()}) | "   # the tag leads the title and the share card
        for what, m in (("<title>", re.search(r"<title>(.*?)</title>", raw, re.S)),
                        ("og:title", re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', raw))):
            if not m or not html.unescape(m.group(1)).strip().startswith(lead):
                problems.append(f"{rel}: {what} does not start with {lead!r}")
    feeds = []   # every Atom feed anywhere; any other .xml in feeds/ is a problem, other .xml files are not feeds
    for f in sorted(site.rglob("*.xml")):
        rel = f.relative_to(site).as_posix()
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            if rel.startswith("feeds/"):
                problems.append(f"{rel}: feed is not valid XML")
            continue
        if root.tag != ATOM + "feed":
            if rel.startswith("feeds/"):
                problems.append(f"{rel}: not an Atom feed")
            continue
        feeds.append(f)
        sub = root.find(ATOM + "subtitle")
        if sub is None or notice not in " ".join((sub.text or "").split()):
            problems.append(f"{rel}: the feed subtitle lacks the unofficial notice")
    notes = sorted((site / "morning").glob("*.json")) if (site / "morning").is_dir() else []
    for f in notes:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            problems.append(f"morning/{f.name}: not valid JSON")
            continue
        if d.get("notice") != notice or d.get("email_line") != u["email_line"]:
            problems.append(f"morning/{f.name}: the note lacks the unofficial notice or email line")
    readme = site / "data" / "README.txt"
    if (site / "data").is_dir() and not (readme.is_file() and notice in " ".join(readme.read_text(encoding="utf-8").split())):
        problems.append("data/README.txt is missing or lacks the unofficial notice")
    return problems, f"{len(pages)} pages, {len(feeds)} feeds, {len(notes)} morning notes"


ATOM = "{http://www.w3.org/2005/Atom}"
RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")


# dates/no-raw-utc-day (docs/architecture/local-dates.md), restated here on purpose (no call into sitegen): every fetch
# day a reader sees is the site_timezone day of the manifest instant (first_fetched_at), never the stored UTC day.
FETCH_DAY = re.compile(
    r'href="(?P<href>https?://[^"]+)"'
    r"|(?P<kind>[Ff]etched between|[Ff]etched on|latest fetched|Data as of|[Ff]etched|at fetch \(|"
    r"(?:[Cc]ollected|[Aa]dded|[Dd]ownloaded|[Rr]etrieved)(?: on)?,?)\s"
    # the footer prints its day in words inside <time class="data-as-of" datetime="ISO"> (sitegen/build.py as_of_day)
    r'(?:<time class="data-as-of" datetime=")?(?P<day>\d{4}-\d{2}-\d{2})(?:">[^<]*</time>)?'
    r"(?P<utc> \(UTC day\))?(?: and (?P<day2>\d{4}-\d{2}-\d{2})(?P<utc2> \(UTC day\))?)?")
FETCH_AGGREGATE = ("fetched between", "fetched on", "latest fetched", "data as of")
# other words a fetch day may follow; after "meeting " ("the latest meeting collected, D") the day is a meeting date
FETCH_OTHER_WORDS = ("collected", "added", "downloaded", "retrieved")
UTC_DAY_LABEL = " (UTC day)"


def fetch_rows(cfg: dict, fixture: bool) -> dict[tuple[str, str], tuple[str, str]]:
    """{(url, sha256): (UTC day, site_timezone day)} of every row of config/site.yml `fetch_manifests` (none for a
    fixture build: its made-up sources have no rows)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    out: dict[tuple[str, str], tuple[str, str]] = {}
    if fixture:
        return out
    zone = ZoneInfo(cfg["site_timezone"])
    for rel in cfg.get("fetch_manifests") or []:
        for row in json.loads((ROOT / rel).read_text(encoding="utf-8")):
            when = datetime.fromisoformat(row["first_fetched_at"])
            if when.tzinfo is None:
                raise ValueError(f"{rel}: {row['url']} first_fetched_at has no time zone")
            out[(row["url"], row.get("sha256"))] = (when.astimezone(ZoneInfo("UTC")).date().isoformat(),
                                                    when.astimezone(zone).date().isoformat())
    return out


def fetch_instants(cfg: dict, fixture: bool, rows: dict | None = None) -> dict[str, set[tuple[str, str]]]:
    """{url: {(UTC day, site_timezone day)}} of fetch_rows (a URL may have several copies)."""
    out: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for (url, _), days in (fetch_rows(cfg, fixture) if rows is None else rows).items():
        out[url].add(days)
    return out


def _fetch_span(sources, rows) -> tuple[str, str, bool] | None:
    """(earliest, latest, exact) fetch day of facts-file sources: site_timezone days when every source has its row
    (same url and sha256, the row's UTC day its stored fetched_at), else stored UTC days (exact False)."""
    srcs = [s for s in sources if s.get("fetched_at")]
    if not srcs:
        return None
    hits = [rows.get((s.get("url"), s.get("sha256"))) for s in srcs]
    if all(h is not None and h[0] == str(s["fetched_at"])[:10] for h, s in zip(hits, srcs)):
        days = sorted(h[1] for h in hits)
        return days[0], days[-1], True
    days = sorted(str(s["fetched_at"])[:10] for s in srcs)
    return days[0], days[-1], False


def _shown(day, utc) -> str:
    return f"{day}{UTC_DAY_LABEL if utc else ''}"


def _site_span(spans) -> tuple[str, str, bool] | None:
    """The footer's site-wide day (dates/footer-as-of-county-only), restated from sitegen/localdates.py latest on
    purpose: each file's own latest (its _fetch_span), then the newest by calendar day, on a tie the exact one."""
    best = max((sp for sp in spans if sp), key=lambda sp: (sp[1], sp[2]), default=None)
    return (best[1], best[1], best[2]) if best else None


def _aggregate_ok(m, span, rpc_span, site_span=None) -> str | None:
    """Why an aggregate fetch day on a page breaks the rule: it must be its own sources' latest ("latest fetched":
    the RPC's), or earliest and latest ("fetched between"), or the one day ("fetched on"), each labelled (UTC day)
    exactly when a source has no recorded instant (dates/check-aggregate-loose); the footer's "Data as of" is the
    site-wide latest (`site_span`, dates/footer-as-of-county-only)."""
    kind = m["kind"].lower()
    sp = rpc_span if kind == "latest fetched" else site_span if kind == "data as of" else span
    shown = f"'{m['kind']} {_shown(m['day'], m['utc'])}" + (f" and {_shown(m['day2'], m['utc2'])}'" if m["day2"] else "'")
    if sp is None:
        return f"{shown}: the page's body has no fetched sources to check it against"
    lo, hi, exact = sp
    want = {"data as of": [hi], "latest fetched": [hi], "fetched on": [lo, hi] if lo == hi else None,
            "fetched between": [lo, hi]}[kind]
    got = [d for d in (m["day"], m["day2"]) if d]
    labels = [bool(u) for u, d in ((m["utc"], m["day"]), (m["utc2"], m["day2"])) if d]
    if kind == "fetched on":
        got, labels = got * 2, labels * 2
    if want != got or any(lab == exact for lab in labels):
        return (f"{shown}, but its sources' fetch days are {_shown(lo, not exact)} to {_shown(hi, not exact)}")
    return None


def _fetch_day_ok(day: str, labelled: bool, urls, instants) -> str | None:
    """Why a fetch day shown next to the source links `urls` breaks the rule, or None."""
    rows = {r for u in urls for r in instants.get(u, ())}
    if labelled:
        # an honest UTC day only when no linked source has a recorded instant on that UTC day (else the lookup
        # failed and labelled a day it could have converted: dates/check-labelled-passes)
        hit = sorted(u for u in urls if any(utc == day for utc, _ in instants.get(u, ())))
        return (f"fetched {day} (UTC day), but {hit} has a recorded instant on that UTC day: show its site_timezone "
                f"day") if hit else None
    if not rows:
        return f"fetched {day} next to {sorted(urls) or 'no source link'}, which has no recorded instant: label it (UTC day)"
    if day not in {local for _, local in rows}:
        utc = " (the stored UTC day)" if day in {u for u, _ in rows} else ""
        return f"fetched {day}{utc}, but the site_timezone day of {sorted(urls)} is {sorted({lo for _, lo in rows})}"
    return None


FRESH_BLOCK = re.compile(r'<(section|details) class="freshness".*?</\1>', re.S)
FRESH_DATE = re.compile(r'<a href="(?P<href>[^"]+)"[^>]*>(?:<time class="nowrap" datetime="(?P<iso>[^"]+)">|'
                        r'<span class="nowrap">)(?P<text>[^<]+)<')
FRESH_FY = re.compile(r"fiscal year (\d{4})")


def check_freshness_dates(site: Path, pages: dict[str, Page]) -> tuple[list[str], str]:
    """dates/freshness-linked (site-polish/freshness-no-source-link), restated here on purpose (no call into sitegen):
    every "through <date>" in a freshness block (the landing, the RPC home) links to a page of this site that exists,
    holds the linked fragment id and prints that date (ISO or worded, as the site words it; a fiscal year as "FY<n>"
    or "fiscal year <n>"), or to an https source document. A date with no link fails."""
    import datetime as _dt
    problems: list[str] = []
    n = 0
    for rel in sorted(pages):
        raw = (site / rel).read_text(encoding="utf-8")
        for blk in FRESH_BLOCK.finditer(raw):
            body = blk.group(0)
            unlinked = len(re.findall(r'class="nowrap"', body)) - len(FRESH_DATE.findall(body))
            if unlinked:
                problems.append(f"{rel}: {unlinked} freshness date(s) with no link to the page that set them")
            for m in FRESH_DATE.finditer(body):
                n += 1
                href, iso, label = html.unescape(m["href"]), m["iso"], html.unescape(m["text"])
                if href.startswith("https://"):
                    continue
                path, _, frag = href.partition("#")
                target = (site / rel).parent / unquote(path)
                try:
                    target = target.resolve()
                    target.relative_to(site.resolve())
                except (OSError, ValueError):
                    problems.append(f"{rel}: freshness link {href!r} leaves the site")
                    continue
                if not target.is_file():
                    problems.append(f"{rel}: freshness link {href!r} has no page")
                    continue
                page = target.read_text(encoding="utf-8")
                if frag and f'id="{frag}"' not in page:
                    problems.append(f"{rel}: freshness link {href!r}: no id {frag!r} on that page")
                if iso:
                    d = _dt.date.fromisoformat(iso)
                    forms = {iso, f"{d.strftime('%B')} {d.day}, {d.year}", f"{d.strftime('%b')} {d.day}, {d.year}"}
                else:
                    fy = FRESH_FY.fullmatch(label)
                    forms = {f"FY{fy[1]}", label} if fy else {label}
                if not any(f in page for f in forms):
                    problems.append(f"{rel}: freshness date {label!r} not printed on the page it links ({href})")
    return problems, f"{n} freshness dates, each linked to a page printing it"


def check_local_dates(site: Path, pages: dict[str, Page], cfg: dict, fixture: bool, county: dict | None = None,
                      councils_: list[dict] | tuple = (), rpc: dict | None = None,
                      other_sources=()) -> tuple[list[str], str]:
    """dates/no-raw-utc-day: (1) each per-document fetch day on a page ("fetched D", "Fetched D.", "at fetch (D)")
    is the site_timezone day of a manifest instant of a source linked just before it (the links since the previous
    fetch day, else the previous fetch day's links: a Details list after its links), or is labelled "(UTC day)"
    when no linked source has an instant; (2) an aggregate ("fetched between A and B", "fetched on", "latest
    fetched") is its own page's sources' day (_aggregate_ok: a council's pages, `councils_` {prefix, facts}, by the
    council's sources; the RPC's pages (its slug) by `rpc`'s; every other page by `county`'s; "latest fetched" by
    `rpc`'s), and the footer's "Data as of" on every page the latest of every file's (county, councils, RPC and
    `other_sources`: a list of source lists, the county agendas and finance); a day after
    "collected", "added", "downloaded" or "retrieved" is a fetch day as in (1), or after "meeting " a meeting date of
    the page's facts; (3) the same for the search index's s.f beside s.u and (4) each feed entry's summary "fetched D"
    beside its related link."""
    import xml.etree.ElementTree as ET
    county = county or {}
    rows = fetch_rows(cfg, fixture)
    instants = fetch_instants(cfg, fixture, rows)
    rpc_span = _fetch_span((rpc or {}).get("sources") or [], rows)
    scopes = [(c["prefix"], c["facts"]) for c in councils_]
    rpc_slug = ((rpc or {}).get("_cfg") or {}).get("slug")
    if rpc_slug:   # the RPC's own pages date their footer by its sources (site-polish/rpc-subtitle: Rpc.site_for)
        scopes.append((rpc_slug + "/", rpc))
    spans = {id(f): _fetch_span(f.get("sources") or [], rows) for _, f in scopes + [("", county)]}
    site_span = _site_span([*spans.values(), rpc_span, *(_fetch_span(list(s), rows) for s in other_sources)])
    problems: list[str] = []
    n = labelled_n = 0
    for rel in sorted(pages):
        text = (site / rel).read_text(encoding="utf-8")
        own = next((f for pre, f in scopes if rel.startswith(pre)), county)
        cands: list[str] = []
        prev: list[str] = []
        for m in FETCH_DAY.finditer(text):
            if m["href"]:
                cands.append(html.unescape(m["href"]).split("#", 1)[0])
                continue
            n += 1
            labelled_n += bool(m["utc"])
            if m["kind"].lower() in FETCH_AGGREGATE:
                why = _aggregate_ok(m, spans[id(own)], rpc_span, site_span)
                if why:
                    problems.append(f"{rel}: {why}")
                continue
            if m["kind"].lower().rstrip(",").removesuffix(" on") in FETCH_OTHER_WORDS and \
                    text[max(0, m.start() - 8):m.start()] == "meeting ":
                n -= 1   # a meeting date ("the latest meeting collected, D"): civil, never shifted
                if m["day"] not in {x.get("date") for x in own.get("meetings") or []}:
                    problems.append(f"{rel}: 'meeting {m['kind']} {m['day']}' is no meeting date of its facts")
                continue
            urls = cands or prev
            why = _fetch_day_ok(m["day"], bool(m["utc"]), set(urls), instants)
            if why:
                problems.append(f"{rel}: {why}")
            prev, cands = urls, []
    idx = site / "static" / "search-index.js"
    n_search = 0
    if idx.is_file():
        body = idx.read_text(encoding="utf-8")
        data = json.loads(body[body.index("=") + 1:].strip().rstrip(";"))

        def walk(v):
            if isinstance(v, dict):
                if isinstance(v.get("u"), str) and isinstance(v.get("f"), str):
                    yield v
                for x in v.values():
                    yield from walk(x)
            elif isinstance(v, list):
                for x in v:
                    yield from walk(x)
        for s in walk(data):
            n_search += 1
            day, lab = (s["f"][:-len(UTC_DAY_LABEL)], True) if s["f"].endswith(UTC_DAY_LABEL) else (s["f"], False)
            why = _fetch_day_ok(day, lab, {s["u"].split("#", 1)[0]}, instants)
            if why:
                problems.append(f"static/search-index.js: {why}")
    A = "{http://www.w3.org/2005/Atom}"
    n_feed = 0
    for f in sorted((site / "feeds").glob("*.xml")) if (site / "feeds").is_dir() else []:
        for e in ET.parse(f).getroot().iter(A + "entry"):
            m = re.search(r"fetched (\d{4}-\d{2}-\d{2})( \(UTC day\))?", e.findtext(A + "summary") or "")
            rel_links = [x.get("href") for x in e.findall(A + "link") if x.get("rel") == "related"]
            if not m or not rel_links:
                continue
            n_feed += 1
            why = _fetch_day_ok(m[1], bool(m[2]), {u.split("#", 1)[0] for u in rel_links}, instants)
            if why:
                problems.append(f"feeds/{f.name} {e.findtext(A + 'id')}: {why}")
    return problems, (f"{n} fetch days on {len(pages)} pages ({labelled_n} labelled UTC day), {n_search} search "
                      f"records, {n_feed} feed entries against {sum(len(v) for v in instants.values())} manifest "
                      f"instants in {cfg['site_timezone']}")


def check_feeds(site: Path, pages: dict[str, Page], sources: list[dict], cfg: dict,
                finance_sources: list[dict] | tuple = ()) -> tuple[list[str], str]:
    """Alerts v1 (sitegen/feeds.py): each feeds/*.xml is valid Atom (RFC 4287 required elements), its entry ids are
    unique tag: URIs, newest first, capped (sitegen.feeds.PER_BODY_FEEDS: per body, the entry id's first part); its
    links go to a built page (and #anchor) or a fetched source document (`sources`: every facts file's;
    `finance_sources`: finance.json's, known to CONTRACTS_FEED only), and every entry has a source link. No link
    carries a scheme other than http(s)."""
    import xml.etree.ElementTree as ET
    problems: list[str] = []
    feeds = sorted((site / "feeds").glob("*.xml")) if (site / "feeds").is_dir() else []
    alerts = cfg.get("alerts") or {}
    if not feeds:
        return (["config/site.yml has alerts: but the build has no feeds/*.xml"] if alerts.get("feed_id") else []), "no feeds"
    cap = alerts.get("max_entries") or 0
    records = {s["url"] for s in sources}
    with_finance = records | {s["url"] for s in finance_sources}
    entries_n = 0
    for f in feeds:
        rel = f.relative_to(site).as_posix()
        known = with_finance if rel == CONTRACTS_FEED else records
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError as exc:
            problems.append(f"{rel}: not well-formed XML ({exc})")
            continue
        if root.tag != ATOM + "feed":
            problems.append(f"{rel}: root is {root.tag!r}, not an Atom feed")
            continue

        def text(el, tag):
            x = el.find(ATOM + tag)
            return (x.text or "").strip() if x is not None else ""

        for tag in ("id", "title", "updated"):
            if not text(root, tag):
                problems.append(f"{rel}: feed has no {tag}")
        if text(root, "updated") and not RFC3339.fullmatch(text(root, "updated")):
            problems.append(f"{rel}: feed updated {text(root, 'updated')!r} is not an RFC 3339 date-time")
        entries = root.findall(ATOM + "entry")
        entries_n += len(entries)
        problems += [f"{rel}: link with scheme {x.get('href')!r}" for x in root.iter(ATOM + "link")
                     if bad_scheme(x.get("href") or "")]
        if root.find(f"{ATOM}author/{ATOM}name") is None and any(e.find(ATOM + "author") is None for e in entries):
            problems.append(f"{rel}: no feed author and an entry without one")
        if not any(link.get("rel") == "self" for link in root.findall(ATOM + "link")):
            problems.append(f"{rel}: no rel=self link")
        if cap and rel in PER_BODY_FEEDS:
            per: dict[str, int] = {}
            for e in entries:
                body = text(e, "id").removeprefix(alerts.get("feed_id") or "").split("/")[0]
                per[body] = per.get(body, 0) + 1
            problems += [f"{rel}: {n} {body} entries, more than alerts.max_entries {cap} per body"
                         for body, n in sorted(per.items()) if n > cap]
        elif cap and len(entries) > cap:
            problems.append(f"{rel}: {len(entries)} entries, more than alerts.max_entries {cap}")
        ids, dates = set(), []
        for e in entries:
            eid = text(e, "id")
            for tag in ("id", "title", "updated"):
                if not text(e, tag):
                    problems.append(f"{rel}: entry {eid or '?'} has no {tag}")
            if eid and not eid.startswith("tag:"):
                problems.append(f"{rel}: entry id {eid!r} is not a tag: URI")
            if eid in ids:
                problems.append(f"{rel}: entry id {eid!r} twice")
            ids.add(eid)
            up = text(e, "updated")
            if up and not RFC3339.fullmatch(up):
                problems.append(f"{rel}: entry {eid} updated {up!r} is not an RFC 3339 date-time")
            elif up:   # as an instant: text order breaks in the fall-back hour (01:30-05:00 is before 01:15-06:00)
                from datetime import datetime
                dates.append(datetime.fromisoformat(up))
            links = e.findall(ATOM + "link")
            alt = [x.get("href") or "" for x in links if (x.get("rel") or "alternate") == "alternate"]
            if not alt:
                problems.append(f"{rel}: entry {eid} has no alternate link")
            for href in alt:
                u = urlsplit(href)
                if u.scheme:
                    base = (alerts.get("site_url") or "")
                    if not base or not href.startswith(base):
                        problems.append(f"{rel}: entry {eid} links {href!r} outside alerts.site_url")
                        continue
                    href = href[len(base):]
                    target = resolve("index.html", href)
                else:
                    target = resolve(rel, href)
                if target is None or not (site / target).is_file():
                    problems.append(f"{rel}: entry {eid} links {href!r}, no such page")
                elif u.fragment and target in pages and u.fragment not in pages[target].ids:
                    problems.append(f"{rel}: entry {eid} links {href!r}, no #{u.fragment} on {target}")
            # every entry links its source document (source-link-always/feed-drop-silent): the build drops a
            # source URL that is not an https link, so an entry without the link is a data error, never a pass
            related = [x for x in links if x.get("rel") == "related"]
            if not related:
                problems.append(f"{rel}: entry {eid} has no source link (rel=\"related\")")
            for x in related:
                src = (x.get("href") or "").split("#")[0]
                if src not in known:
                    problems.append(f"{rel}: entry {eid} source {src!r} is not a fetched source document")
        if dates != sorted(dates, reverse=True):
            problems.append(f"{rel}: entries are not newest first")
    linked = set()
    if "alerts.html" in pages:
        linked = {resolve("alerts.html", h) for h in pages["alerts.html"].hrefs if h.endswith(".xml")}
    else:
        problems.append("feeds are built but alerts.html is not")
    built = {f.relative_to(site).as_posix() for f in feeds}
    problems += [f"alerts.html does not link {r}" for r in sorted(built - linked)]
    problems += [f"alerts.html links {r}, which is not built" for r in sorted(linked - built)]
    return problems, f"{len(feeds)} feeds, {entries_n} entries"


def page_type(rel: str) -> str | None:
    if rel == "index.html":
        return "index"
    if rel in ("officials.html", "search.html", "alerts.html", "today.html"):
        return rel[:-5]
    head = rel.split("/")[0]
    if head == "contracts":
        return "contracts_index" if rel == "contracts/index.html" else "contract"
    if head == "finance":
        return "finance_index" if rel == "finance/index.html" else "fund"
    if head == "capital":
        return "capital"
    if head == _rpc_slug():
        return "rpc_home" if rel.count("/") == 1 else "rpc_meetings"
    for c in _council_slugs():
        if head == c:
            parts = rel.split("/")
            return "council_home" if len(parts) == 2 else {"members": "council_member", "meetings": "council_meetings",
                                                            "items": "council_items", "transcripts": "council_transcript"}.get(parts[1])
    return {"officials": "official", "meetings": "meeting", "items": "items", "districts": "district",
            "votes": "votes"}.get(head)


NARROW_TYPES = ("contracts_index", "contract", "finance_index", "fund", "capital",  # AC-F10: also at 360 px
                "council_home", "council_member", "council_meetings", "council_items",  # M4: compact at 360 px
                "council_transcript",
                "rpc_home", "rpc_meetings",  # RPC-1: phone widths, no sideways scroll
                "alerts", "today")  # today: the day page (Daylight M2)


def _rpc_slug() -> str | None:
    import yaml
    loc = _site_cfg().get("rpc")
    return yaml.safe_load((ROOT / "config" / "localities" / loc / "rpc.yml").read_text(encoding="utf-8"))["slug"] if loc else None


def _council_slugs() -> list[str]:
    import yaml
    return [yaml.safe_load((ROOT / "config" / "localities" / loc / "council.yml").read_text(encoding="utf-8"))["slug"]
            for loc in _site_cfg().get("councils") or []]


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
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        try:
            env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    problems, n = [], 0
    # every chosen page at 390 px; the Bids and awards pages again at 360 px (AC-F10)
    for width, rels in ((VIEWPORT, chosen), (NARROW, [c for c in chosen if page_type(c) in NARROW_TYPES])):
        if not rels:
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            json.dump([{"name": r, "path": str((site / r).resolve())} for r in rels], tf)
        try:
            r = subprocess.run(["node", str(Path(__file__).with_name("hscroll.js")), tf.name, str(width)],
                               capture_output=True, text=True, timeout=600, env=env)
        finally:
            os.unlink(tf.name)
        if r.returncode != 0:
            raise RuntimeError("browser check could not run: " + (r.stderr.strip().splitlines() or ["?"])[-1])
        results = json.loads(r.stdout)
        n += len(results)
        problems += [f"{x['name']} at {width}px: scrollWidth {x['scrollWidth']} > {x['width']}; offenders: "
                     f"{', '.join(x['offenders']) or 'none found'}" for x in results if x["overflow"]]
    return problems, f"{n} page checks at {VIEWPORT}px (contracts also {NARROW}px): " + ", ".join(
        f"{t} x{sum(1 for c in chosen if page_type(c) == t)}" for t in by_type)


ROW_VIEWPORTS = ((375, 667), (768, 1024), (1000, 800), (1280, 800))
NARROW_ROW = (NARROW, 640)  # AC-F10: 360 px, judged on the Bids and awards pages only


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
        for w, h in ROW_VIEWPORTS + (NARROW_ROW,):
            r = subprocess.run(["node", str(Path(__file__).with_name("rowheight.js")), tf.name, str(w), str(h), "0.6"],
                               capture_output=True, text=True, timeout=900, env=env)
            if r.returncode != 0:
                raise RuntimeError("row-height check could not run: " + (r.stderr.strip().splitlines() or ["?"])[-1])
            for x in json.loads(r.stdout):
                if w == NARROW and page_type(x["name"]) not in NARROW_TYPES:
                    continue
                rows += x["rows"]
                for o in x["offenders"]:
                    problems.append(f"{x['name']} at {w}x{h}: {o['tag']} is {o['h']}px (limit {int(h * 0.6)}): {o['text']!r}")
    finally:
        os.unlink(tf.name)
    return problems, f"{rows} rows on {len(chosen)} pages at " + ", ".join(f"{w}x{h}" for w, h in ROW_VIEWPORTS + (NARROW_ROW,))


# ---------------------------------------------------------------- driver

class TranscriptLines(HTMLParser):
    """Each <li> of ol.transcript: (id, the first a.tx-time href, the label chip text, has a data-transcript span);
    and each li of ul.call-ons: (its data-meeting, its data-ext="video" hrefs)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[dict] = []
        self.call_ons: list[tuple[str | None, list[str]]] = []
        self.text: list[str] = []
        self._in_ol = self._in_ul = 0
        self._li: dict | None = None
        self._chip = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag == "ol" and "transcript" in cls:
            self._in_ol += 1
        elif tag == "ul" and "call-ons" in cls:
            self._in_ul += 1
        elif tag == "li" and self._in_ol:
            self._li = {"id": a.get("id"), "time": None, "label": "", "text": False}
            self.lines.append(self._li)
        elif tag == "li" and self._in_ul:
            self.call_ons.append((a.get("data-meeting"), []))
        elif tag == "a" and self._li is not None and "tx-time" in cls and self._li["time"] is None:
            self._li["time"] = (a.get("href") or "", a.get("data-ext"))
        elif tag == "a" and self._in_ul and a.get("data-ext") == "video" and self.call_ons:
            self.call_ons[-1][1].append(a.get("href") or "")
        elif tag == "span" and self._li is not None and "chip-type" in cls:
            self._chip = True
        elif tag == "span" and self._li is not None and "data-transcript" in a:
            self._li["text"] = True

    def handle_endtag(self, tag):
        if tag == "ol" and self._in_ol:
            self._in_ol -= 1
            self._li = None
        elif tag == "ul" and self._in_ul:
            self._in_ul -= 1
        elif tag == "span":
            self._chip = False

    def handle_data(self, d):
        self.text.append(d)
        if self._chip and self._li is not None:
            self._li["label"] += d


# privacy/transcript-private-addresses, restated here (not imported from collector/privacy.py): a house number (digits,
# not part of a dollar amount, decimal, comma number or hyphenated number, and not after a word that names something
# else), one to three street-name words that are not function words or units, and a street suffix; or a phone number
# (3-3-4 or 3-4 digit groups, or seven or more single digits apart).
# It restates one house number, not the masker's bounded join of up to four (privacy/mask-regex-redos), so it
# has no join to bound: each start tries at most three words, linear in the text.
_PRIV_NOT_NAME = set("""a an the and or but so of to in on at by for from with into off over up down out about than
then that this these those there here it it's its is are was were be i we you he she they my your his her their
what when where if as also known like just only not no yes do did have has had will would can could each every
other another more less many some any all both same whole foot feet mile miles acre acres percent per square year
years month months day days hour hours minute minutes time times car cars home homes house houses unit units lot
lots people lane lanes way wheel wide k thousand ordinance resolution fails council councilman councilwoman
councilmember mayor clerk zero oh one two three four five six seven eight nine ten twenty thirty forty fifty
hundred""".split())
_PRIV_NOT_AFTER = {"ordinance", "resolution", "highway", "route", "us", "sr", "ward", "district", "number", "no",
                   "item", "phase", "the", "approximately", "about", "year", "years", "since"}
PRIVATE_ADDRESS = re.compile(r"(?<![\w$#/.,'’-])(\d{1,5})(?![.,]\d)((?:\s+(?:[A-Za-z]\.){1,3}|\s+\d{1,3}(?:st|nd|rd|th)"
                             r"|\s+[A-Za-z][A-Za-z'’-]*){1,3})\s+(?:street|avenue|road|drive|court|lane|boulevard|blvd|"
                             r"pike|place|way|circle|trail|parkway|alley|cove)\b", re.I)
PRIVATE_PHONE = re.compile(r"(?<![\w$.,-])(?:\(\d{3}\)\s*|\d{3}[\s.-]{1,2})\d{3}[\s.-]{1,2}\d{4}(?![\w-])(?!\s*[.,]?\s*\d)"
                           r"|(?<![\w$.,-])\d{3}[.-]\d{4}(?![\w-])(?![.,]\d)"
                           r"|(?<![\w$.,-])(?:\d\s+){6,}\d(?![\w-])(?![.,]\d)")


def private_details(text: str) -> list[str]:
    """Street addresses and phone numbers in a piece of transcript text (the restated rule above)."""
    out = [m.group(0) for m in PRIVATE_PHONE.finditer(text)]
    for m in PRIVATE_ADDRESS.finditer(text):
        before = re.findall(r"[A-Za-z]+", text[max(0, m.start() - 30):m.start()])
        words = [w.strip(".").lower() for w in m.group(2).split()]
        if (before and before[-1].lower() in _PRIV_NOT_AFTER) or any(w in _PRIV_NOT_NAME for w in words):
            continue
        out.append(m.group(0))
    return out


# Restated from collector/privacy.py ADDRESS_MASK / PHONE_MASK: only transcript text carries them
PLACEHOLDERS = ("[address omitted; hear it in the video at this time]",
                "[phone number omitted; hear it in the video at this time]")
NEEDLE_MIN = 20       # committed transcript lines at least this long are looked for in data/ and the search index
_JS_ESCAPE = re.compile(r'\\(u[0-9a-fA-F]{4}|["\\/bfnrt])')


def _unescape_js(body: str) -> str:
    """JSON / JS string escapes undone (\\u2019, \\", \\n ...), so a line written as a JSON string is found as text."""
    def one(m):
        e = m.group(1)
        return chr(int(e[1:], 16)) if e[0] == "u" else {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}.get(e, e)
    return _JS_ESCAPE.sub(one, body)


def _source_text(transcript_dirs: list[Path]) -> str:
    """Every string in the committed data outside the transcript folders (data/**/*.json), whitespace folded, one per
    line: text the site has from a source document, so a transcript line equal to it (an item title read aloud) is not
    transcript-only text."""
    skip = {Path(d).resolve() for d in transcript_dirs if d}
    out: list[str] = []

    def walk(v):
        if isinstance(v, str):
            out.append(" ".join(v.split()))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    for f in sorted((ROOT / "data").rglob("*.json")):
        if f.resolve().parent in skip:
            continue
        try:
            walk(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return "\n".join(out)


def _lines_in(flat: str, by_head: dict[str, list[tuple[str, str]]]) -> list[str]:
    """The ids of the needles (by their first NEEDLE_MIN characters) found in flat text, each starting at a word start."""
    found = []
    for i in range(len(flat) - NEEDLE_MIN + 1):
        if i and flat[i - 1].isalnum():
            continue
        for needle, where in by_head.get(flat[i:i + NEEDLE_MIN], ()):
            if flat.startswith(needle, i):
                found.append(where)
    return found


def check_private_details(site: Path, cs: list[dict]) -> tuple[list[str], str]:
    """privacy/transcript-private-addresses (docs/architecture/city-council.md, "Private details in transcript text"):
    (a) every data-transcript text on every page (transcript lines and the call-on words and excerpts on member pages)
    passes the restated rule: no street address or phone number; (b) every committed transcript segment
    (data/localities/<locality>/transcripts/*.json) passes it, line by line and joined (masked at rest); (c) no file
    under data/ and not static/search-index.js carries any committed transcript line (at least NEEDLE_MIN characters)
    at all, and no placeholder: transcript text is shown only on transcript and member pages. The needles are the
    committed, masked lines (safe to hold), less any line that is also a string of the committed source data (an item
    title the clerk reads aloud is the item's own text, shown from the agenda). Problems name the file and line, never
    the matched text."""
    problems, texts, segs_checked = [], 0, 0
    by_head: dict[str, list[tuple[str, str]]] = {}
    for c in cs:
        folder = c.get("transcripts_dir")
        for f in sorted(Path(folder).glob("*.json")) if folder else ():
            if f.name == "index.json":
                continue
            rel = f"{c.get('slug', '?')}/transcripts/{f.name}"
            segs = json.loads(f.read_text(encoding="utf-8")).get("segments") or []
            lines = [" ".join(str(seg[2]).split()) if isinstance(seg, list) and len(seg) == 3 else "" for seg in segs]
            for i, t in enumerate(lines):
                segs_checked += 1
                if private_details(t):
                    problems.append(f"{rel}#s{i}: committed transcript line holds {len(private_details(t))} address or "
                                    "phone number matches (not masked at rest)")
                if len(t) >= NEEDLE_MIN:
                    by_head.setdefault(t[:NEEDLE_MIN], []).append((t, f"{rel}#s{i}"))
            if lines and not any(private_details(t) for t in lines) and private_details(" ".join(lines)):
                problems.append(f"{rel}: an address or phone number split over two committed lines (not masked at rest)")
    shared = 0
    if by_head:
        also = set(_lines_in(_source_text([c.get("transcripts_dir") for c in cs]), by_head))
        shared = len(also)
        by_head = {h: kept for h, v in by_head.items() if (kept := [x for x in v if x[1] not in also])}
    files = 0
    for f in sorted(site.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in (".html", ".js", ".json", ".csv", ".xml", ".txt", ".ics"):
            continue
        files += 1
        rel = f.relative_to(site).as_posix()
        body = f.read_text(encoding="utf-8", errors="replace")
        if f.suffix.lower() == ".html":
            for k, m in enumerate(TRANSCRIPT_TEXT.finditer(body)):
                texts += 1
                seg = html.unescape(re.sub(r"^<[^>]*>|</[^>]*>$", "", m.group(0)))
                if (n := len(private_details(seg))):
                    problems.append(f"{rel}: transcript text #{k} shows {n} address or phone number matches")
        if rel.startswith("data/") or rel == "static/search-index.js":
            flat = " ".join(html.unescape(_unescape_js(body)).split())
            if (n := sum(flat.count(m) for m in PLACEHOLDERS)):
                problems.append(f"{rel}: carries {n} transcript placeholders (transcript text outside the pages)")
            hits = _lines_in(flat, by_head)
            if hits:
                problems.append(f"{rel}: carries {len(hits)} committed transcript lines ({', '.join(sorted(set(hits))[:5])})")
    n_needles = sum(len(v) for v in by_head.values())
    return problems, (f"{texts} transcript texts on pages; {segs_checked} committed transcript lines checked at rest; "
                      f"{files} files, of them data/ and the search index checked for {n_needles} committed lines "
                      f"({shared} more are also source text) and the placeholders")


def check_transcripts(site: Path, cs: list[dict]) -> tuple[list[str], str]:
    """Transcript pages and member call-ons (sitegen/transcripts.py, spec AC6.3)."""
    problems, n_pages, n_lines, n_calls = [], 0, 0, 0
    for c in cs:
        videos = {m["id"]: m.get("video_url") for m in c["facts"]["meetings"]}
        for f in sorted((site / c["slug"] / "transcripts").glob("*.html")):
            rel = f.relative_to(site).as_posix()
            mid = re.sub(r"-\d+$", "", f.stem) if f.stem not in videos else f.stem
            if mid not in videos or not videos[mid]:
                problems.append(f"{rel}: names no meeting with a video")
                continue
            p = TranscriptLines()
            p.feed(f.read_text(encoding="utf-8"))
            n_pages += 1
            if TRANSCRIPT_NOTICE not in " ".join("".join(p.text).split()):
                problems.append(f"{rel}: the transcript notice is missing")
            raw = f.read_text(encoding="utf-8")
            if not re.search(r'<meta name="robots" content="noindex">', raw.split("</head>")[0]):
                problems.append(f"{rel}: no robots noindex in its head")
            if not re.search(r'<p class="privacy-note">[^<]*addresses and phone numbers[^<]*<a href="[./]*report\.html">',
                             raw):
                problems.append(f"{rel}: the privacy line (addresses left out, report link) is missing")
            if not p.lines:
                problems.append(f"{rel}: no transcript lines")
            linked = video_ok(videos[mid])
            for li in p.lines:
                n_lines += 1
                href, ext = li["time"] or ("", None)
                m = VIDEO_HREF.fullmatch(href)
                if not linked:
                    if li["time"] is not None:
                        problems.append(f"{rel}#{li['id']}: line links a time in a video not on the allowed hosts")
                elif ext != "video" or not m or m.group(1) != videos[mid] or m.group(2) is None:
                    problems.append(f"{rel}#{li['id']}: line does not link a time in the meeting's video ({href!r})")
                if li["label"].strip() != "Transcript":
                    problems.append(f"{rel}#{li['id']}: line is not labelled Transcript")
                if not li["text"]:
                    problems.append(f"{rel}#{li['id']}: line has no data-transcript text")
        for f in sorted((site / c["slug"] / "members").glob("*.html")):
            p = TranscriptLines()
            p.feed(f.read_text(encoding="utf-8"))
            for mid, hrefs in p.call_ons:
                n_calls += 1
                rel = f.relative_to(site).as_posix()
                video = videos.get(mid)
                if not video:
                    problems.append(f"{rel}: a call-on entry names no meeting with a video ({mid!r})")
                    continue
                ok = [h for h in hrefs if (m := VIDEO_HREF.fullmatch(h)) and m.group(2) is not None and m.group(1) == video]
                if video_ok(video) and (not ok or len(ok) != len(hrefs)):
                    problems.append(f"{rel}: a call-on entry of {mid} does not link a time in that meeting's video")
                elif not video_ok(video) and hrefs:
                    problems.append(f"{rel}: a call-on entry of {mid} links a video not on the allowed hosts")
    return problems, f"{n_pages} transcript pages, {n_lines} lines; {n_calls} call-on entries on member pages"


# ---------------------------------------------------------------- current holders
# Restated from the invariant `city-seats/current-holder-matches-latest-attendance`, not imported from sitegen: a
# seat's current holder is the member recorded in that seat who is still listed at the latest meeting read, unless
# the record shows a successor. So no seat says "Current member not yet recorded", and its member is not under
# "Served previously", while the latest list (council: attendance; county: confirmed roll calls) lists that member
# and nobody has been printed in the seat since the member's own latest print.
NOT_RECORDED = "Current member not yet recorded"


def _council_cfg(slug: str) -> dict:
    for loc in _site_cfg().get("councils") or []:
        c = yaml.safe_load((ROOT / "config" / "localities" / loc / "council.yml").read_text(encoding="utf-8"))
        if c["slug"] == slug:
            return c
    return {}


ABOUT_RATE = re.compile(r'<p class="glance-note" data-confirmed-rate="(?P<body>[^"]+)">(?P<text>.*?)</p>', re.S)
OPERATOR_PERSON = re.compile(r'<p id="operator-person">(?P<text>.*?)</p>', re.S)


def _rate_problems(text: str | None, body: str, rcs: list[dict], href: str) -> tuple[list[str], str]:
    n = sum(1 for rc in rcs if rc["verification"]["status"] == "verified")
    want = f"{n:,} of {len(rcs):,}"
    pct = f"({100 * n / len(rcs):.1f}%)" if rcs else "(0.0%)"
    plain = html.unescape(re.sub(r"<[^>]+>", "", text or ""))
    if text is None:
        return [f"about.html: no confirmed rate for {body}"], f"{body} {want} {pct}"
    if not plain.startswith(f"{want} {body} roll calls {pct} are confirmed"):
        return [f"about.html: {body} rate reads {plain[:80]!r}, the facts give {want} {pct}"], f"{body} {want} {pct}"
    if f'href="{href}"' not in text:
        return [f"about.html: {body} rate does not link the body's pages"], f"{body} {want} {pct}"
    return [], f"{body} {want} {pct}"


OPERATOR_PAGES = ("about.html", "who-runs-this.html")


def check_about(site: Path, cs: list[dict], cfg: dict, county: dict | None = None) -> tuple[list[str], str]:
    """about.html and who-runs-this.html against the facts (Brian 2026-11-11): (a) every body's confirmed rate, the
    county's (`county`: its facts) and each built council's, reads "<n> of <total> <body> roll calls (<pct>%) are
    confirmed" and links the body's pages, restated here from the facts (verification status "verified"), so the page
    can never drift from the record and every body's line is labelled the same way; (b) with config operator_person set
    and that official in a built council, one operator line on each of About and Who runs this, the same on both, that
    names them, links their own vote history page (<slug>/members/<id>.html), prints no date the data does not hold,
    names the council's body, and says "is on" with their ward exactly when the council's latest attendance list
    places them there (latest_listed, expected_ward_holders: the seat records' rule), else "has served on"."""
    page = site / "about.html"
    if not page.is_file():
        return ["about.html: missing"], "no About page"
    raw = page.read_text(encoding="utf-8")
    problems: list[str] = []
    shown = {html.unescape(m.group("body")): m.group("text") for m in ABOUT_RATE.finditer(raw)}
    notes = []
    bodies = [(county["coverage"]["body"], county["roll_calls"], "meetings.html")] if county else []
    bodies += [(_council_cfg(c["slug"]).get("body_name") or c["facts"]["coverage"]["body"], c["facts"]["roll_calls"],
                f'{c["slug"]}/index.html') for c in cs]
    for body, rcs, href in bodies:
        p, note = _rate_problems(shown.pop(body, None), body, rcs, href)
        problems += p
        notes.append(note)
    problems += [f"about.html: a confirmed rate for {b}, which this build has no facts for" for b in shown]
    pid = cfg.get("operator_person")
    owner = next((c for c in cs if any(o["id"] == pid for o in c["facts"]["officials"])), None) if pid else None
    texts = {}
    for rel in OPERATOR_PAGES:
        f = site / rel
        lines = OPERATOR_PERSON.findall(f.read_text(encoding="utf-8")) if f.is_file() else []
        if owner is None:
            if lines:
                problems.append(f"{rel}: an operator line with no operator_person in a built council")
            continue
        if len(lines) != 1:
            problems.append(f"{rel}: {len(lines)} operator lines, want 1")
            continue
        texts[rel] = lines[0]
    if owner is not None and texts:
        if len(set(texts.values())) > 1:
            problems.append("who-runs-this.html: the operator line differs from About's")
        o = next(o for o in owner["facts"]["officials"] if o["id"] == pid)
        body = _council_cfg(owner["slug"]).get("body_name") or owner["facts"]["coverage"]["body"]
        wards = owner["wards"] if "wards" in owner else _council_wards(owner["slug"])
        _, named, _ = latest_listed(owner["facts"], wards)
        ward = next((w for w, oid in expected_ward_holders(wards, owner["facts"]).items() if oid == pid), None)
        ends = sorted({r["end"] for r in _council_seat_rows(owner, wards)
                       if r.get("official_id") == pid and r.get("dates") == "sourced" and r.get("end")})
        for rel, line in texts.items():
            text = html.unescape(re.sub(r"<[^>]+>", "", line))
            want = f'<a href="{owner["slug"]}/members/{pid}.html">{html.escape(o["name"])}</a>'
            if want not in line:
                problems.append(f"{rel}: the operator line does not link {o['name']} to their vote history page")
            # a year only inside the line's term end, and only a seat record's sourced end (the city's have none)
            rest = text
            for e in ends:
                rest = rest.replace(f", in a term that ends on {e}", "")
            if re.search(r"\b(19|20)\d\d\b", rest):
                problems.append(f"{rel}: the operator line prints a year that is not a seat record's sourced term end")
            if pid in named:
                seat = f"is on the {body}" + (f" (Ward {ward})" if ward is not None else "")
                if seat not in text:
                    problems.append(f"{rel}: the operator line does not say {seat!r}, as the latest attendance "
                                    "list places them")
            elif f"has served on the {body}" not in text or " is on the " in text:
                problems.append(f"{rel}: the operator line does not say 'has served on the {body}'; the latest "
                                "attendance list does not name them")
        notes.append(f"operator line links {owner['slug']}/members/{pid}.html on {', '.join(texts)}")
    return problems, "; ".join(notes) or "no councils"


def _council_wards(slug: str) -> list[dict]:
    c = _council_cfg(slug)
    if c and (ROOT / c["wards"]).is_file():
        return json.loads((ROOT / c["wards"]).read_text(encoding="utf-8"))
    return []


def _council_seat_rows(owner: dict, wards: list[dict]) -> list[dict]:
    """The council's holder records (sitegen/council.py holder_rows), or owner["seat_rows"] when given (tests).
    Records that cannot be derived (wards that name a source the facts lack) give none: no term end is then allowed,
    so a failure here only makes the year check stricter."""
    if "seat_rows" in owner:
        return owner["seat_rows"]
    from sitegen import config as site_config, council as site_council
    for loc in _site_cfg().get("councils") or []:
        c = site_config.load_council(loc)
        if c["slug"] == owner["slug"]:
            try:
                return site_council.holder_rows(wards, owner["facts"], c)[0]
            except (KeyError, ValueError):
                return []
    return []


def latest_listed(facts: dict | None, wards: list[dict]) -> tuple[str | None, set[str], set[str]]:
    """(L, named, may_hold): L the latest attendance list; `named` the officials it names; `may_hold` those plus,
    when L's list is incomplete (it prints a name that resolves to no official, or names fewer officials than the
    list before it), the officials the list before it names: L cannot show that they have gone. Read from the facts
    file's own attendance lists (meetings[].attendance), not from wards.json, when the facts have any."""
    lists = defaultdict(list)            # date -> [official_id or None]
    for m in (facts or {}).get("meetings", []):
        for x in m.get("attendance") or []:
            lists[m["date"]].append(x.get("official_id"))
    if not lists:
        for w in wards:
            lists[w["date"]].append(w.get("official_id"))
    if not lists:
        return None, set(), set()
    dates = sorted(lists)
    latest = dates[-1]
    named = {o for o in lists[latest] if o}
    may_hold = set(named)
    if len(dates) > 1:
        before = {o for o in lists[dates[-2]] if o}
        if None in lists[latest] or len(named) < len(before):
            may_hold |= before
    return latest, named, may_hold


def last_wards(wards: list[dict], members) -> dict[str, int]:
    """{member: ward} for each of `members` whose own last two ward prints agree on a ward that nobody else has been
    printed in since, or whose last print is a configured, cited seating (city path N10, `configured`)."""
    prints = defaultdict(list)          # member -> [(date, ward, configured)]
    last_in = {}                         # ward -> (date, member) of its latest print
    for w in sorted(wards, key=lambda w: (w["date"], w["meeting_id"] or "")):
        if w.get("ward") is None or not w.get("official_id"):
            continue
        prints[w["official_id"]].append((w["date"], int(w["ward"]), bool(w.get("configured"))))
        last_in[int(w["ward"])] = (w["date"], w["official_id"])
    out = {}
    for oid in sorted(members):
        p = prints.get(oid, [])
        if p and (p[-1][2] or len(p) >= 2 and p[-1][1] == p[-2][1]) and last_in[p[-1][1]][1] == oid:
            out[oid] = p[-1][1]
    return out


def expected_ward_holders(wards: list[dict], facts: dict | None = None) -> dict[int, str]:
    """{ward: member} for each member the latest list names (latest_listed `named`; a may-hold member is allowed in
    their seat but not required) whose own last two ward prints agree on a ward nobody has been printed in since."""
    if not wards:
        return {}
    _, named, _ = latest_listed(facts, wards)
    return {ward: oid for oid, ward in last_wards(wards, named).items()}


def expected_district_holders(facts: dict, roster: list[dict]) -> dict[int, str]:
    """{district: official} for each official with a vote in a confirmed roll call of the latest meeting collected
    whose own latest district record is a seat no other record starts in after it."""
    dates = {m["id"]: m["date"] for m in facts["meetings"]}
    if not dates:
        return {}
    latest = max(dates.values())
    voters = {v["official_id"] for rc in facts["roll_calls"] if dates.get(rc["meeting_id"]) == latest
              and (rc.get("verification") or {}).get("status") == "verified" for v in rc["votes"] if v.get("official_id")}
    out = {}
    for oid in sorted(voters):
        mine = sorted((r for r in roster if r.get("official_id") == oid and str(r.get("seat", "")).startswith("district-")),
                      key=lambda r: str(r["start"]))
        if not mine:
            continue
        last = mine[-1]
        if any(r["seat"] == last["seat"] and str(r["start"]) > str(last["start"]) for r in roster):
            continue
        out[int(last["seat"].split("-")[1])] = oid
    return out


def check_current_holders(site: Path, facts: dict, roster: list[dict], cs: list[dict]) -> tuple[list[str], str]:
    """Both ways, per council (city-seats/current-holder-matches-latest-attendance):
    - every member the latest list names, and last printed in a ward, is shown in that ward; no member the latest
      list may still hold (latest_listed `may_hold`) is under Served previously;
    - every shown holder is that ward's expected member, or a may-hold member with no other seat; nobody is shown in
      two seats; a title seat (the mayor) shows an official of that title who may hold a seat at the latest list,
      and the one such official the latest list names, if there is one.
    County: every official voting in a confirmed roll call of the latest meeting is current in their latest
    district. A council entry may carry its own `wards` and `cfg` (tests); otherwise its council.yml is read."""
    problems, n = [], 0
    for c in cs:
        home = site / c["slug"] / "index.html"
        if not home.is_file():
            continue
        body = home.read_text(encoding="utf-8")
        at = body.find('<details class="officials-section" id="previous"')
        prev = body[at:body.find("</details>", at)] if at >= 0 else ""
        wards = c["wards"] if "wards" in c else _council_wards(c["slug"])
        cfg = c["cfg"] if "cfg" in c else _council_cfg(c["slug"])
        latest, named, may_hold = latest_listed(c["facts"], wards)
        expected = expected_ward_holders(wards, c["facts"])
        placed = last_wards(wards, may_hold)              # where each may-hold member was last printed
        shown, noted = {}, {}                              # seat -> the member its holder / held-over note links
        for m in re.finditer(r'<li id="seat-([^"]+)"[^>]*>(.*?)</li>', body, re.S):
            for cls, into in (("d-holder", shown), ("d-note", noted)):
                h = re.search(r'<span class="' + cls + r'[^"]*">(.*?)</span>', m.group(2), re.S)
                ids = re.findall(r'members/([^"/]+)\.html', h.group(1) if h else "")
                into[m.group(1)] = ids[0] if ids else None
        for ward, oid in sorted(expected.items()):
            n += 1
            if shown.get(f"ward-{ward}") != oid:
                problems.append(f"{c['slug']}/index.html: ward {ward} does not show {oid}, listed in the latest "
                                f"attendance list and last printed in that ward")
        for oid in sorted(may_hold):
            if f"members/{oid}.html" in prev:
                problems.append(f"{c['slug']}/index.html: {oid} is under Served previously")
        titles = {o["id"]: o.get("title") for o in c["facts"]["officials"]}
        title_of_seat = {seat: title for title, seat in ((cfg or {}).get("title_seats") or {}).items()}
        for title, seat in ((cfg or {}).get("title_seats") or {}).items():
            n += 1
            want = sorted(o for o in named if titles.get(o) == title)
            if len(want) == 1 and shown.get(seat) != want[0]:
                problems.append(f"{c['slug']}/index.html: {seat} does not show {want[0]}, the {title} named in the "
                                f"latest attendance list ({latest})")
        seats_of = defaultdict(list)
        for seat, oid in sorted(shown.items()):
            if oid is None:
                continue
            seats_of[oid].append(seat)
            # a holder is always named in the latest list: a may-hold member it does not name is held over, shown
            # only as "not yet recorded" with a note (second re-review of bfee967)
            if seat in title_of_seat:
                ok = oid in named and titles.get(oid) == title_of_seat[seat]
            else:
                ward = int(seat.rsplit("-", 1)[1])
                ok = expected.get(ward) == oid or (ward not in expected and oid in named
                                                   and oid not in expected.values() and placed.get(oid) == ward)
            if not ok:
                problems.append(f"{c['slug']}/index.html: {seat} shows {oid}, whom the latest attendance list "
                                f"({latest}) does not place there")
        for seat, oid in sorted(noted.items()):
            if oid is None:
                continue
            here = (titles.get(oid) == title_of_seat[seat] if seat in title_of_seat
                    else placed.get(oid) == int(seat.rsplit("-", 1)[1]))
            if shown.get(seat) is not None or oid not in may_hold - named or not here:
                problems.append(f"{c['slug']}/index.html: {seat} notes {oid}, who is not held over in that seat "
                                f"(named at {latest}, or not last placed there)")
        for oid, seats in sorted(seats_of.items()):
            if len(seats) > 1:
                problems.append(f"{c['slug']}/index.html: {oid} is shown in {len(seats)} seats ({', '.join(seats)})")
    if roster:
        for d, oid in sorted(expected_district_holders(facts, roster).items()):
            page = site / "districts" / f"{d:02d}.html"
            if not page.is_file():
                continue
            n += 1
            text = page.read_text(encoding="utf-8")
            cur = text[text.find('id="current-h"'):text.find('id="previous-h"')]
            if NOT_RECORDED in cur or f"officials/{oid}.html" not in cur:
                problems.append(f"districts/{d:02d}.html: does not show {oid} as current, who votes in a confirmed "
                                f"roll call of the latest meeting")
    return problems, f"{n} seats checked against the latest list, both ways"


def seats_fresh_note(facts: dict, roster: list[dict]) -> str:
    """M1 pipeline/seats-stale-on-new-county-meeting: a WARNING when the seat rows were read to an earlier meeting
    than the facts hold (the site then words them to that meeting; re-run tools/derive_seats.py). Not a failure:
    the pages stay true, they are only behind."""
    urls = {x["id"]: x.get("url") for x in facts.get("sources", [])}
    dates = {m["id"]: m["date"] for m in facts.get("meetings", [])}
    at = defaultdict(set)
    for rc in facts.get("roll_calls", []):
        if rc.get("source_id") in urls and rc.get("page") and rc.get("meeting_id") in dates:
            at[f"{urls[rc['source_id']]}#page={rc['page']}"].add(dates[rc["meeting_id"]])
    seen = [str(r["end"]) if r.get("end") else max(at.get(r.get("last_source"), {""}))
            for r in roster if r.get("dates") == "observed"]
    seen = [x for x in seen if x]
    newest = max(dates.values()) if dates else None
    if seen and newest and max(seen) < newest:
        return (f"WARNING: seats.yml is read to {max(seen)}, the facts to {newest}; the site words the seats to "
                f"{max(seen)}. Re-run tools/derive_seats.py")
    return f"seats read to {max(seen) if seen else 'n/a'}, the latest meeting collected"


def run_checks(site: Path, facts: dict, internal=False, no_export=False, operator=OPERATOR, browser=True,
               all_pages=False, sample=3, store_extra=(), seats_path=None, districts_path=None, finance=None,
               target="preview") -> Report:
    rep = Report()
    d_seats, d_map = default_inputs(facts)
    seats_path, districts_path = seats_path or d_seats, districts_path or d_map
    cfg = _site_cfg()
    files = [f for f in site.rglob("*") if f.is_file()]
    pages = {f.relative_to(site).as_posix(): parse(f) for f in files if f.suffix == ".html"}
    if not pages:
        rep.add("site", [f"no HTML files under {site}"])
        return rep
    cap = MAX_FILES_BY_TARGET[target]
    # one rule everywhere (sitegen/config.py max_files): a build is within its cap at most at the cap (<= cap)
    rep.add("files", [f"{len(files)} files, over the limit of {cap} for the {target} target"] if len(files) > cap else [],
            f"{len(files)} files, {len(pages)} pages, {target} target (cap {cap})")
    rep.add("links", check_links(site, pages, no_export), "internal links, #anchors and assets" + ("; data/ skipped" if no_export and not _has_export(site) else ""))
    cs = [c for c in councils(facts) if any(rel.startswith(c["prefix"]) for rel in pages)]
    missing = [c["slug"] for c in councils(facts) if c not in cs]
    rpc = rpc_facts(facts)
    agendas = county_agendas(facts)
    all_sources = {"sources": [*facts["sources"], *(s for c in cs for s in c["facts"]["sources"]),
                               *(rpc or {}).get("sources", []),   # an RPC DOCX has no page count: linked whole only
                               *(agendas or {}).get("sources", [])]}
    videos = {m["video_url"] for c in cs for m in c["facts"]["meetings"] if m.get("video_url")}
    cal_urls, cal_problems = calendar_agenda_urls(facts)
    problems, note = check_sources(site, pages, all_sources, store_extra,
                                   allowed_external(cfg, seats_path, districts_path) | rpc_allowed(rpc) | cal_urls
                                   | ({agendas["index_url"]} if agendas else set()), finance, videos)
    if rpc is not None and not any(rel.startswith(rpc["_cfg"]["slug"] + "/") for rel in pages):
        problems.append(f"no pages under {rpc['_cfg']['slug']}/ for the configured RPC")
    problems += cal_problems
    rep.add("sources", problems + [f"no pages under {m}/ for the configured council" for m in missing], note)
    if rpc is not None:
        problems, note = check_rpc_cases(rpc)
        rep.add("rpc-cases", problems, note)
        problems, note = check_rpc_motions(site, pages, rpc)
        rep.add("rpc-motions", problems, note)
        problems, note = check_rpc_export(site, rpc)
        rep.add("rpc-export", problems, note)
        # build.py writes the note on every target but preview while config morning_note is set (a real build).
        # The missing-note check rides on rpc-morning, so it runs only when the RPC is configured (rpc_facts not
        # None); a build without the RPC is not checked for morning/ here.
        problems, note = check_rpc_morning(site, rpc, cfg.get("morning_note") is not None and target != "preview")
        rep.add("rpc-morning", problems, note)
    county_pages = {rel: pg for rel, pg in pages.items() if not any(rel.startswith(c["prefix"]) for c in cs)}
    problems = check_unverified(site, county_pages, facts, internal, fin=finance)
    for c in cs:
        mine = {rel: pg for rel, pg in pages.items() if rel.startswith(c["prefix"])}
        problems += check_unverified(site, mine, c["facts"], internal, official_prefix=c["prefix"] + "members/",
                                     export=False, held_sentences=c.get("held_sentences"))
    rep.add("unverified", problems, ("internal build" if internal else "public build") + "".join(f"; {c['slug']}/ against its own facts" for c in cs))
    fact_ids = {o["id"] for o in facts["officials"]}
    roster_only = tuple(sorted({r["official_id"] for r in read_roster(seats_path) if r.get("official_id")} - fact_ids))
    problems, note = check_index(site, pages, facts, roster_only)
    rep.add("index", problems, "AC1.1: " + note)
    problems, note = check_layout(site, facts)
    for c in cs:
        p2, n2 = check_layout(site, c["facts"], c["prefix"] + "members")
        problems, note = problems + p2, f"{note}; {n2}"
    rep.add("layout", problems, "AC1.5/N1: " + note)
    problems, note = check_totals(site, pages, facts)
    for c in cs:
        p2, n2 = check_totals(site, pages, c["facts"], c["prefix"] + "meetings/", c["prefix"] + "members")
        problems, note = problems + p2, f"{note}; {n2}"
    rep.add("totals", problems, "AC2.2: " + note)
    problems, note = check_official_numbers(site, facts)
    for c in cs:
        p2, n2 = check_official_numbers(site, c["facts"], c["prefix"] + "members")
        problems, note = problems + p2, f"{note}; {n2}"
    rep.add("official-numbers", problems, note)
    problems, note = check_provenance(site, pages, facts, read_roster(seats_path), cfg)
    rep.add("provenance", problems, note)
    problems, note = check_name_links(site, facts, read_roster(seats_path), cs)
    rep.add("name-links", problems, note)
    rep.add("footer", check_footer(pages, operator), f"'Provided as a free service by {operator}.' on {len(pages)} pages")
    problems, note = check_old_brand(site)
    rep.add("brand/no-old-gnoshcodes", problems, note)
    rep.add("external", check_external(pages, site, cfg))
    problems, note = check_report_channel(pages, cfg, target)
    rep.add("report-channel", problems, note)
    # the contracts feed links each solicitation's first document, a finance.json source
    problems, note = check_feeds(site, pages, all_sources["sources"], cfg,
                                 finance_sources=list((finance or {}).get("sources") or []))
    rep.add("feeds", problems, note)
    problems, note = check_local_dates(site, pages, cfg, bool(facts.get("fixture")), county=facts, councils_=cs, rpc=rpc,
                                       # the agendas a build shows: those with a page count (sitegen/county_agendas.py)
                                       other_sources=[[s for s in (agendas or {}).get("sources") or [] if s.get("pages")],
                                                      (finance or {}).get("sources") or []])
    rep.add("dates/no-raw-utc-day", problems, note)
    problems, note = check_freshness_dates(site, pages)
    rep.add("dates/freshness-linked", problems, note)
    problems, note = check_transcripts(site, cs)
    rep.add("transcripts", problems, note)
    problems, note = check_private_details(site, cs)
    rep.add("transcripts/private-addresses", problems, note)
    problems, note = check_unofficial(site, pages, cfg)
    rep.add("unofficial/notice-on-every-page", problems, note)
    problems, note = check_about(site, cs, cfg, county=facts)
    rep.add("about", problems, note)
    problems, note = check_current_holders(site, facts, read_roster(seats_path), cs)
    rep.add("current-holders", problems, note)
    note = seats_fresh_note(facts, read_roster(seats_path))
    if note.startswith("WARNING"):
        print(note, file=sys.stderr)
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::warning title=seats.yml is stale::{note}")   # an annotation on the workflow run
    rep.add("seats-fresh", [], note)
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
    ap.add_argument("--finance", help="finance.json the build read (default: data/finance.json when it exists)")
    ap.add_argument("--target", choices=sorted(MAX_FILES_BY_TARGET), default=os.environ.get("RECORDS_BUILD_TARGET") or "preview",
                    help="the host the build is for: its file cap applies (preview 500, pages 3000)")
    ap.add_argument("--out", default=str(ROOT / "build" / "qa" / "site_checks.txt"))
    a = ap.parse_args(argv)
    fin_path = Path(a.finance) if a.finance else Path(a.facts).with_name("finance.json")
    fin = load_facts(fin_path) if fin_path.exists() else None
    rep = run_checks(Path(a.site), load_facts(a.facts), a.internal, a.no_export, a.operator, not a.no_browser, a.all_pages,
                     store_extra=a.store, seats_path=a.seats, districts_path=a.districts, finance=fin, target=a.target)
    text = rep.render()
    print(text)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print("RESULT: " + ("PASS" if rep.ok else "FAIL"))
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
