"""Day by day (Daylight M2, docs/design/daylight): the week strip and the day cards on today.html.

One page, built at build time, holds every day of a window around today (config/site.yml `days`): from the start of
the week `weeks_before` weeks before today to the end of the week `weeks_after` weeks after it, today taken in the
site's zone (`site_timezone`). Each day lists the records we hold that are dated that day, one card per meeting or
listing, from every body the site collects:

- the county commission (its minutes: the votes and roll calls, each linked to its minutes page; a meeting the
  minutes do not cover yet, from the agenda the county posted, as "Agenda" with its items, and once its date has passed,
  a line that the county has not posted the minutes, as of the build date: sitegen/county_agendas.py);
- each council (its meetings from the Agenda Center and CivicClerk: the votes and roll calls when the minutes were
  read, otherwise the agenda; a meeting the city's calendar schedules that is not in the facts yet, as scheduled);
- the Regional Planning Commission (each agenda's cases as printed, each linked to its agenda page);
- bids and awards (a solicitation on the date the purchasing archive prints for it).

Rules (the same as every record page): votes come only from the record, through the county's view functions, so a
held roll call shows "Not confirmed" and no value; every official's name links to their page; every item links its
source; each card says "Unofficial copy. Official record:" and links the body's record; no text is written about a
named person. static/days.js turns the page to one day at a time (no inline script); without it the page is a plain
list of the days that have records.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import bodies, config, localdates, views, watch

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# Minutes states of a council meeting (schema meeting.minutes_status) other than "read", in plain words.
MINUTES_WORDS = {
    "not_posted": "Minutes not posted when the city's listing was last read.",
    "scan_not_read": "The minutes are a scanned image; nothing was read from them.",
    "not_fetched": "Minutes listed, not fetched.",
    "parse_failed": "The minutes could not be read; open them yourself.",
    "other_meeting": ("The file listed as this meeting's minutes does not show that it records this meeting (it "
                      "names another meeting or date), so it is not used here."),
    "unreadable": "The minutes file was fetched but could not be read, so nothing was taken from it.",
}
# The dot each kind of card draws in the strip (decorative; the button's label says the count in words).
DOTS = {"county": "county", "council": "city", "rpc": "rpc", "bids": "bids"}


class DaysError(Exception):
    pass


def today_in_zone(tz: str | None = None) -> date:
    """Today in the site's zone. RECORDS_TODAY=YYYY-MM-DD fixes it (tests, a rebuild of a past day's page)."""
    fixed = os.environ.get("RECORDS_TODAY")
    if fixed:
        return date.fromisoformat(fixed)
    return datetime.now(ZoneInfo(tz or config.SITE["site_timezone"])).date()


def window(today: date, cfg: dict | None = None) -> tuple[date, date]:
    """(first day, last day): whole weeks from `weeks_before` weeks before today's week to `weeks_after` after it."""
    cfg = cfg if cfg is not None else (config.SITE.get("days") or {})
    start_word = str(cfg.get("week_start", "sunday")).lower()
    if start_word not in WEEKDAYS:
        raise DaysError(f"config/site.yml days.week_start {start_word!r} is not a weekday name")
    before, after = int(cfg.get("weeks_before", 4)), int(cfg.get("weeks_after", 4))
    if before < 0 or after < 0 or before + after > 26:
        raise DaysError("config/site.yml days: weeks_before and weeks_after must be 0 or more, 26 weeks at most")
    week_first = today - timedelta(days=(today.weekday() - WEEKDAYS.index(start_word)) % 7)
    return week_first - timedelta(weeks=before), week_first + timedelta(weeks=after, days=6)


def day_text(d: date) -> str:
    return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}"


def date_text(d: date) -> str:
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _in(iso: str | None, start: date, end: date) -> bool:
    return bool(iso) and start.isoformat() <= iso[:10] <= end.isoformat()


# ---------------------------------------------------------------------------------------------------------------
# cards


def _votes(ix: views.Index, meeting_id: str) -> list[dict]:
    """The meeting's roll calls in minutes order, each as the meeting page shows it (views._roll_call_block)."""
    rcs = [rc for rc in ix.facts["roll_calls"] if rc["meeting_id"] == meeting_id]
    return [views._roll_call_block(ix, rc) for rc in sorted(rcs, key=ix.position)]


def _doc(src: dict | None, word: str) -> dict | None:
    if not src:
        return None
    pages = src.get("pages")
    return {"word": word, "url": src["url"], "what": f"PDF, {pages} {'page' if pages == 1 else 'pages'}" if pages
            else "PDF", "fetched": localdates.fetched(src)}


def county_card(ix: views.Index, m: dict) -> dict:
    src = ix.sources[m["source_id"]]
    votes = _votes(ix, m["id"])
    return {"kind": "county", "dot": DOTS["county"], "id": f"county-{m['id']}", "body": ix.facts["coverage"]["body"],
            "title": ix.kind_labels[m["kind"]], "href": ix.meeting_href(m["id"]),
            "docs": [d for d in (_doc(src, "Minutes"),) if d], "minutes_note": None,
            "watch": watch.meeting(config.SITE["county_key"], m.get("video_url")),
            "votes": votes, "state": "votes" if votes else "none", "cases": [], "sols": [],
            "record": {"url": src["url"], "label": "the minutes PDF", "ext": False}}


def county_agenda_card(ix: views.Index, ax, m: dict) -> dict:
    """A county meeting the minutes do not cover yet: its agenda PDF and items, as the agenda prints them."""
    ctx = ax.meeting(m)
    doc = ctx["doc"]
    return {"kind": "county", "dot": DOTS["county"], "id": f"county-{m['id']}", "body": ix.facts["coverage"]["body"],
            "title": ctx["kind_label"], "href": ctx["href"],
            "docs": [{"word": "Agenda", "url": doc["url"], "fetched": doc["fetched"],
                      "what": f"PDF, {doc['pages']} {'page' if doc['pages'] == 1 else 'pages'}" if doc["pages"] else "PDF"}],
            "minutes_note": ctx["minutes_note"], "watch": watch.body(config.SITE["county_key"]),
            "votes": [], "state": "agenda", "cases": [],
            "sols": [], "agenda_items": ctx["entries"], "agenda_only": True,
            "record": {"url": doc["url"], "label": "the county's agenda PDF", "ext": False}}


def council_card(cix, m: dict) -> dict:
    src = cix.sources[m["source_id"]]
    agenda = cix.sources.get(m.get("agenda_source_id") or "")
    minutes = src if src["kind"] == "minutes" else None
    votes = _votes(cix, m["id"]) if minutes else []
    docs = [d for d in (_doc(agenda, "Agenda"), _doc(minutes, "Minutes")) if d]
    status = m.get("minutes_status") or ("read" if minutes else "not_posted")
    rec = ({"url": minutes["url"], "label": "the minutes PDF", "ext": False} if minutes
           else {"url": agenda["url"], "label": "the agenda PDF", "ext": False} if agenda
           else {"url": cix.cfg["record_url"], "label": cix.cfg["record_label"], "ext": True}
           if views.https_url(cix.cfg.get("record_url")) else None)
    return {"kind": "council", "dot": DOTS["council"], "id": f"{cix.slug}-{m['id']}", "body": cix.body_name,
            "bkey": getattr(cix, "body_key", None) or DOTS["council"],
            "title": cix.kind_labels.get(m["kind"], m["kind"]), "href": cix.meeting_href(m["id"]),
            "docs": docs, "minutes_note": None if status == "read" else MINUTES_WORDS.get(status),
            "watch": watch.meeting(getattr(cix, "body_key", None), m.get("video_url")),
            "votes": votes, "state": "votes" if votes else ("agenda" if agenda else "none"), "cases": [], "sols": [],
            "record": rec}


_CALLED_OFF = re.compile(r"moved|cancell?ed|postponed", re.I)


def scheduled_cards(cix, start: date, end: date, today: date | None = None) -> list[tuple[str, dict]]:
    """Meetings on the city's calendar (council.yml `calendar`) in the window that the facts file does not hold yet:
    the calendar's own title and date only, linked to the agenda when the calendar has one, else to the council's
    record page. One card per date and kind. Rows before the build day, or whose title says moved, cancelled or
    postponed, are not shown, and rows without a date or kind are skipped. A row listed from another category (D1,
    `page1_required`: kept only when page 1 of its stored file prints the council's heading) is never shown here,
    since nothing has checked yet that it is this body's meeting (a "One Time Event" may be any board's)."""
    today = today or today_in_zone()
    path = cix.cfg.get("calendar")
    if not path or cix.fixture or not views.https_url(cix.cfg.get("record_url")):
        return []
    p = config.REPO_ROOT / path
    if not p.is_file():
        return []
    held = {(m["date"], m["kind"]) for m in cix.facts["meetings"]}
    seen, out = set(), []
    for row in sorted(json.loads(p.read_text(encoding="utf-8")), key=lambda r: (r.get("date") or "", r.get("kind") or "")):
        key = (row.get("date"), row.get("kind"))
        if not all(key) or row["date"] < today.isoformat() or _CALLED_OFF.search(row.get("title") or ""):
            continue
        if row.get("page1_required"):
            continue
        if not _in(row["date"], start, end) or key in held or key in seen:
            continue
        seen.add(key)
        out.append((row["date"], {
            "kind": "council", "dot": DOTS["council"], "id": f"{cix.slug}-{row['date']}-{row['kind']}-scheduled",
            "bkey": getattr(cix, "body_key", None) or DOTS["council"],
            "body": cix.body_name, "title": cix.kind_labels.get(row["kind"], row["kind"]), "href": None,
            "docs": [], "watch": watch.body(getattr(cix, "body_key", None)), "votes": [],
            "state": "scheduled",
            "cases": [], "sols": [],
            "minutes_note": None, "cal_title": row.get("title") or "",
            "agenda_url": row["agenda_url"] if views.https_url(row.get("agenda_url")) else "",
            "built_text": date_text(today),
            "record": {"url": cix.cfg["record_url"], "label": cix.cfg["record_label"], "ext": True}}))
    return out


def rpc_card(rpx, m: dict) -> dict:
    ctx = rpx.meeting(m)
    agenda = ctx["agenda"]
    rec = ({"url": agenda["url"], "label": "the RPC's agenda PDF", "ext": False} if agenda
           else {"url": rpx.cfg["record_url"], "label": rpx.cfg["record_label"], "ext": True})
    return {"kind": "rpc", "dot": DOTS["rpc"], "id": f"{rpx.slug}-{m['id']}", "body": ctx["kind_label"],
            "bkey": rpx.body_key,
            "title": None, "href": ctx["href"], "rpc": ctx, "docs": [], "minutes_note": None,
            "watch": watch.body(rpx.body_key),
            "votes": [], "state": "agenda" if ctx["cases"] else "none", "cases": ctx["cases"], "sols": [],
            "cancelled": ctx["cancelled"], "record": rec}


def bids_card(fx, sols: list[dict]) -> dict:
    rows = []
    for s in sorted(sols, key=lambda s: s["row"]):
        rows.append({"id": s["id"], "title": s["title"], "href": f"contracts/{s['slug']}.html",
                     "date_text": s["archive_date_text"], "src": fx.src(s["archive_source_id"], None)})
    rec = (config.SITE.get("official_records") or {}).get("contracts")
    return {"kind": "bids", "dot": DOTS["bids"], "id": f"bids-{sols[0]['archive_date']}",
            "body": config.FIN_TEXT["contracts"]["title"], "title": None, "href": "contracts/index.html",
            "docs": [], "minutes_note": None, "watch": None, "votes": [], "state": "bids", "cases": [],
            "sols": rows,
            "record": {**rec, "ext": True} if rec and views.https_url(rec.get("url")) else None}


# ---------------------------------------------------------------------------------------------------------------
# the page


def _coverage(ix, cixs, rpx, fx, start: date, end: date, counts: dict, ax=None) -> list[dict]:
    """What the page holds, body by body: the newest dated record, and how many cards fall in these weeks."""
    out = [{"body": ix.facts["coverage"]["body"], "n": counts["county"],
            "what": f"Minutes from {localdates.words(ix.coverage['from'])} to {localdates.words(ix.coverage['to'])}"
                    + (", and the agendas the county posted for meetings after that." if ax and ax.meetings else ".")}]
    for c in cixs:
        out.append({"body": c.body_name, "n": counts[c.slug],
                    "what": f"Meetings from {localdates.words(c.coverage['from'])} to "
                            f"{localdates.words(c.coverage['to'])}"
                            + (", and the meetings the city's calendar lists after that." if c.cfg.get("calendar")
                               and not c.fixture else ".")})
    if rpx is not None:
        cov = rpx.facts["coverage"]
        out.append({"body": rpx.body, "n": counts["rpc"],
                    "what": f"Meetings listed from {localdates.words(cov.get('from'))} to "
                            f"{localdates.words(cov.get('to'))}."})
    if fx is not None:
        dated = sorted(s["archive_date"] for s in fx.fin["solicitations"] if s.get("archive_date"))
        if dated:
            out.append({"body": config.FIN_TEXT["contracts"]["title"], "n": counts["bids"], "unit": "bid listing",
                        "what": f"Solicitations on the dates the purchasing archive prints, {localdates.words(dated[0])} to "
                                f"{localdates.words(dated[-1])}. Budget books are by fiscal year, not by day, so "
                                f"they are on the Finance page."})
    return out


def page(ix: views.Index, cixs=(), rpx=None, fx=None, today: date | None = None, ax=None) -> dict:
    today = today or today_in_zone()
    start, end = window(today)
    by_day: dict[str, list[dict]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    for m in sorted(ix.facts["meetings"], key=lambda m: (m["date"], m["id"])):
        if _in(m["date"], start, end):
            by_day[m["date"]].append(county_card(ix, m))
            counts["county"] += 1
    for m in sorted(ax.meetings if ax else [], key=lambda m: (m["date"], m["id"])):
        if _in(m["date"], start, end):
            by_day[m["date"]].append(county_agenda_card(ix, ax, m))
            counts["county"] += 1
    for c in cixs:
        for m in sorted(c.facts["meetings"], key=lambda m: (m["date"], m["id"])):
            if _in(m["date"], start, end):
                by_day[m["date"]].append(council_card(c, m))
                counts[c.slug] += 1
        for d, card in scheduled_cards(c, start, end, today):
            by_day[d].append(card)
            counts[c.slug] += 1
    if rpx is not None:
        for m in sorted(rpx.facts["meetings"], key=lambda m: (m["date"], m["id"])):
            if _in(m["date"], start, end):
                by_day[m["date"]].append(rpc_card(rpx, m))
                counts["rpc"] += 1
    if fx is not None:
        sols: dict[str, list[dict]] = defaultdict(list)
        for s in fx.fin["solicitations"]:
            if _in(s.get("archive_date"), start, end):
                sols[s["archive_date"]].append(s)
        for d, ss in sols.items():
            by_day[d].append(bids_card(fx, ss))
            counts["bids"] += len(ss)
    for cards in by_day.values():   # the keys every card carries (the templates are strict)
        for c in cards:
            c.setdefault("cancelled", False)
            c.setdefault("rpc", None)
            c.setdefault("agenda_items", [])
            # whose record the card is, for the "Show records from" switch (data-body): county meetings and the
            # county's bid listings carry the county's key
            c.setdefault("bkey", config.SITE["county_key"])
    weeks, d = [], start
    while d <= end:
        days = []
        for _ in range(7):
            iso = d.isoformat()
            cards = by_day.get(iso, [])
            # the day button's aria-label counts every card; static/switch.js swaps in the count of the chosen
            # body's cards (data-label-<body>), the same cards whose dots stay visible
            days.append({"iso": iso, "anchor": f"d-{iso}", "text": day_text(d), "dow": d.strftime("%a"),
                         "n": d.day, "month": d.strftime("%b"), "cards": cards,
                         "dots": [c["dot"] for c in cards], "label": day_label(d, cards),
                         "labels": {k: day_label(d, [c for c in cards if c["bkey"] == k]) for k in bodies.ORDER}})
            d += timedelta(days=1)
        weeks.append({"first": days[0], "days": days})
    sb = config.SITE.get("school_board") or {}
    school = sb if sb.get("label") and views.https_url(sb.get("url")) else None
    return {"weeks": weeks, "start": start.isoformat(), "end": end.isoformat(), "built": today.isoformat(),
            "start_text": date_text(start), "end_text": date_text(end), "built_text": date_text(today),
            "tz": config.SITE["site_timezone"], "school": school, "committees": views.committees(),
            "n_cards": sum(len(v) for v in by_day.values()),
            "coverage": _coverage(ix, cixs, rpx, fx, start, end, counts, ax)}


PAGE = "today.html"


def day_label(d: date, cards: list[dict]) -> str:
    """A day button's spoken name: the day, then how many meetings and bid listings `cards` hold."""
    n_meet = sum(1 for c in cards if c["kind"] != "bids")
    n_bids = sum(len(c["sols"]) for c in cards)
    label = [f"{n_meet} {'meeting' if n_meet == 1 else 'meetings'}" if n_meet else "no meetings"]
    if n_bids:
        label.append(f"{n_bids} {'bid listing' if n_bids == 1 else 'bid listings'}")
    return f"{day_text(d)}: {', '.join(label)}"


# ---------------------------------------------------------------------------------------------------------------
# the landing's short list (docs/design/front-page-v2.md section 4)

CHIPS = (("cancelled", "Cancelled"), ("scheduled", "Scheduled"), ("votes", "Votes"), ("agenda", "Agenda"))


def chip(card: dict) -> str | None:
    """The status word today.html's cards carry, from fields the card already has: Cancelled, Scheduled, Votes,
    Agenda, or none. An RPC card never has state "votes" (rpc_card), so no RPC row says Votes."""
    if card.get("cancelled"):
        return "Cancelled"
    return dict(CHIPS[1:]).get(card.get("state"))


def landing_meetings(page_ctx: dict, today: date | None = None, n: int = 3) -> dict:
    """A selection of the day page's own cards (page()), nothing new: the next `n` meetings on or after the build day,
    soonest first, and the last `n` before it, newest first. Bid listings are not meetings and are left out; a
    cancelled meeting stays, marked. Each row links its day on today.html, where the card links its source."""
    today = today or date.fromisoformat(page_ctx["built"])
    rows = []
    for w in page_ctx["weeks"]:
        for d in w["days"]:
            for c in d["cards"]:
                if c["kind"] == "bids":
                    continue
                rows.append({"iso": d["iso"], "dow": d["dow"], "n": d["n"], "month": d["month"], "text": d["text"],
                             "body": c["body"], "title": c.get("title"), "dot": c["dot"], "chip": chip(c),
                             "bkey": c.get("bkey") or config.SITE["county_key"],
                             "href": f"{PAGE}#{d['anchor']}"})
    t = today.isoformat()
    ahead = [r for r in rows if r["iso"] >= t]
    recent = [r for r in rows if r["iso"] < t][-n:][::-1]
    # `spare`: the next upcoming rows after the first n, built hidden; static/landing.js shows them in turn when the
    # page is read after a shown row's day has passed, so "Coming up" stays full (front-page/stale-upcoming-not-refilled)
    return {"upcoming": ahead[:n], "spare": ahead[n:n + 2 * n], "recent": recent, "built": t,
            "built_text": date_text(today), "n": n}
