"""Council pages beside the county (M4 slice 2): a council's meetings, items, members and ward holder records.

Everything about the body comes from its config/localities/<locality>/council.yml (config.COUNCILS); nothing here
names a place. The pages use the county's view functions (sitegen/views.py) through `CouncilIndex`, which only
changes where pages live and how seats are read, so every rule of the county pages holds here too: a held roll call
shows "Not confirmed*" and no value, every name links to its member page, every fact links its source page (N1-N4).

File budget (config.MAX_FILES): one page per member plus their history by year (consecutive years share a page
while it stays under config.PAGE_TARGET: build.py pack_years), one page per year of meetings
(each meeting a section with its roll calls inline) and one page per year of items, plus the council's home page. A
year page over config.PAGE_BYTES is split into parts by date (build.py plan_parts). Never one page per meeting or item.
"""
from __future__ import annotations

from collections import defaultdict

from . import config, localdates, views
from .seats import Seats


# ---------------------------------------------------------------------------------------------------------------
# Holder records, derived (architecture, invariant `provenance`: observed dates, never term dates)


def _src(sources: dict, source_id: str, page: int) -> str:
    return f"{sources[source_id]['url']}#page={page}"


def ward_rows(wards: list[dict], facts: dict, cfg: dict) -> list[dict]:
    """Ward holder records from the attendance lists' printed wards (wards.json).

    1. A print with no ward, or for a name that did not resolve, is not used. A configured, cited member's seating
       (collector city_build, path N10: `"configured": True`, the cited record's page) counts as a print of its ward.
    2. Per member, consecutive prints of the same ward form a run; a run shorter than `min_ward_prints` is dropped,
       the shortest first and one at a time, so the member's runs either side of it join again (a lone print that
       disagrees with the member's own run either side; the meeting page still shows the source). A run that ends
       at the latest minutes read is kept however short: no later print can confirm it yet, and dropping it would
       hide a newly seated member (city-pages/ward-misprint). A run holding a configured seating is never dropped:
       the cited record of the seating is the evidence, not a misprint.
    3. Per ward, the kept prints in date order are split wherever the member printed changes: each piece is one
       record, from its first to its last meeting. So someone who held a ward twice, with another member between,
       has two records.
    Every record carries the first and last meeting's source page."""
    sources = {s["id"]: s for s in facts["sources"]}
    officials = {o["id"] for o in facts["officials"]}
    obs = sorted((w for w in wards if w.get("ward") is not None and w.get("official_id") in officials),
                 key=lambda w: (w["date"], w["meeting_id"] or ""))
    by_member: dict[str, list[dict]] = defaultdict(list)
    for w in obs:
        by_member[w["official_id"]].append(w)
    def runs_of(prints):
        runs: list[list[dict]] = []
        for w in prints:
            if runs and runs[-1][-1]["ward"] == w["ward"]:
                runs[-1].append(w)
            else:
                runs.append([w])
        return runs

    latest = obs[-1]["date"] if obs else None   # the latest minutes read that print a ward
    kept = []
    for prints in by_member.values():
        # drop one short run at a time, the shortest first, so the runs either side of a lone misprint join up
        # again (Ward 4, Ward 3, Ward 4: one run of Ward 4) before their own length is judged
        while True:
            short = [r for r in runs_of(prints) if len({x["meeting_id"] for x in r}) < cfg["min_ward_prints"]
                     and r[-1]["date"] != latest and not any(x.get("configured") for x in r)]
            if not short:
                break
            drop = min(short, key=lambda r: (len(r), r[0]["date"]))
            prints = [w for w in prints if not any(w is x for x in drop)]
        kept += prints
    by_ward: dict[int, list[dict]] = defaultdict(list)
    for w in sorted(kept, key=lambda w: (w["date"], w["meeting_id"] or "")):
        by_ward[int(w["ward"])].append(w)
    rows = []
    for ward, prints in sorted(by_ward.items()):
        pieces: list[list[dict]] = []
        for w in prints:
            if pieces and pieces[-1][-1]["official_id"] == w["official_id"]:
                pieces[-1].append(w)
            else:
                pieces.append([w])
        for p in pieces:
            first, last = p[0], p[-1]
            rows.append({"official_id": first["official_id"], "seat": f"{cfg['seat_word']}-{ward}",
                         "start": first["date"], "end": last["date"],
                         "source": _src(sources, first["source_id"], first["page"]),
                         "last_source": _src(sources, last["source_id"], last["page"]),
                         "dates": "observed", "printed": None, "lines": None, "note": None, "name": None,
                         "evidence": cfg["evidence"]["ward"], "printed_to": None})
    return rows


def title_rows(facts: dict, cfg: dict) -> list[dict]:
    """Seats held by title (`title_seats`, e.g. the mayor): one record per such official, from the first to the last
    confirmed roll call that lists a vote for them."""
    sources = {s["id"]: s for s in facts["sources"]}
    dates = {m["id"]: m["date"] for m in facts["meetings"]}
    rows = []
    for o in sorted(facts["officials"], key=lambda o: o["id"]):
        seat = cfg["title_seats"].get(o["title"])
        if not seat:
            continue
        rcs = sorted((rc for rc in facts["roll_calls"] if views.is_verified(rc)
                      and any(v["official_id"] == o["id"] for v in rc["votes"])),
                     key=lambda rc: (dates[rc["meeting_id"]], rc["page"], rc["id"]))
        if not rcs:
            continue
        first, last = rcs[0], rcs[-1]
        rows.append({"official_id": o["id"], "seat": seat, "start": dates[first["meeting_id"]],
                     "end": dates[last["meeting_id"]],
                     "source": _src(sources, first["source_id"], first["page"]),
                     "last_source": _src(sources, last["source_id"], last["page"]),
                     "dates": "observed", "printed": None, "lines": None, "note": None, "name": None,
                     "evidence": cfg["evidence"]["title"], "printed_to": None})
    return rows


def extend_by_listings(rows: list[dict], wards: list[dict], facts: dict, cfg: dict) -> None:
    """Invariant `city-seats/current-holder-matches-latest-attendance`: a seat's holder record runs on through the
    later attendance lists that still list its holder by name, until the record shows a successor.

    The evidence that places a member in a seat stops before the record does: the city's CivicClerk minutes (from
    2025-04) print the attendance names without their wards, and a roll call is used only when confirmed. So a record
    whose last print P is followed by attendance lists that list its holder is extended to the last of them (its
    `last_source` that list's page), unless the record shows a successor first: another record of the same seat, or
    another seat for the same member, starting after P. Then the extension stops before that start. `printed_to`
    keeps P (and `seen_evidence` the evidence up to P), so the wording says which part was printed and which part
    only listed the name (Seats.dates_text). A name the attendance list prints but that resolves to no official is
    never placed in a seat."""
    sources = {s["id"]: s for s in facts["sources"]}
    officials = {o["id"] for o in facts["officials"]}
    listed: dict[str, list[dict]] = defaultdict(list)     # every attendance listing of a member, ward or not
    for w in sorted(wards, key=lambda w: (w["date"], w["meeting_id"] or "")):
        if w.get("official_id") in officials:
            listed[w["official_id"]].append(w)
    for r in rows:
        if r["official_id"] is None:
            continue
        printed = r["end"]
        cut = min((x["start"] for x in rows if x is not r and x["start"] > printed
                   and (x["seat"] == r["seat"] or x["official_id"] == r["official_id"])), default=None)
        later = [w for w in listed[r["official_id"]] if w["date"] > printed and (cut is None or w["date"] < cut)]
        if not later:
            continue
        last = later[-1]
        r.update({"printed_to": printed, "printed_source": r["last_source"], "seen_evidence": r["evidence"],
                  "evidence": cfg["evidence"]["ward"], "end": last["date"],
                  "last_source": _src(sources, last["source_id"], last["page"])})


def latest_list_incomplete(wards: list[dict], facts: dict, latest: str | None, prev: str | None) -> bool:
    """True when the latest attendance list cannot show that a member of the list before it has gone: it prints a
    name that resolves to no official (a misspelling such as ZAHARIAS, or a new name the record cannot place yet),
    or it resolves fewer members than the list before it (a list cut off, or a page not read)."""
    if latest is None or prev is None:
        return False
    officials = {o["id"] for o in facts["officials"]}
    resolved = {d: {w["official_id"] for w in wards if w["date"] == d and w.get("official_id") in officials}
                for d in (latest, prev)}
    unresolved = any(w["date"] == latest and w.get("official_id") not in officials for w in wards) or any(
        not a.get("official_id") for m in facts.get("meetings", []) if m.get("date") == latest
        for a in m.get("attendance") or [])
    return unresolved or len(resolved[latest]) < len(resolved[prev])


def holder_rows(wards: list[dict], facts: dict, cfg: dict) -> tuple[list[dict], str | None]:
    """(records, L). L is the latest minutes read: the latest meeting with an attendance list (wards.json lists every
    member each list prints, ward or not); only without any list, the latest record end. A record seen at L (or
    later) has no end (current); every record keeps `seen_to`, the last meeting it was seen at.

    L is never the latest end of one kind of evidence: the wards printed in the attendance lists stop at 2025-03-06
    and the confirmed roll calls at another date, so taking L from the records closed every ward record that still
    ran on (city-seats/current-holder-matches-latest-attendance); a confirmed roll call at a meeting with no
    attendance list would do the same, so L comes from the lists alone. extend_by_listings carries each record on
    through the lists that still list its holder.

    One list is not enough to close a record (city-seats, one-list drop): a record last seen at the list before L,
    whose member L's list does not name, stays open (`held_over`) when that list is incomplete
    (latest_list_incomplete) and the record shows no successor. Seats words it as not named at L."""
    rows = ward_rows(wards, facts, cfg) + title_rows(facts, cfg)
    extend_by_listings(rows, wards, facts, cfg)
    lists = sorted({w["date"] for w in wards if not w.get("configured")})    # a configured seating is not a list
    latest = lists[-1] if lists else max((r["end"] for r in rows), default=None)
    prev = lists[-2] if len(lists) > 1 else None
    short = latest_list_incomplete(wards, facts, latest, prev)
    for r in rows:
        r["seen_to"], r["held_over"] = r["end"], False
        if r["end"] >= latest:
            r["end"] = None
        elif short and r["official_id"] and r["end"] == prev and not any(
                x is not r and x["start"] > prev and (x["seat"] == r["seat"] or x["official_id"] == r["official_id"])
                for x in rows):
            r["end"], r["held_over"] = None, True
    return rows, latest


# ---------------------------------------------------------------------------------------------------------------
# The council's index: the county's view functions with the council's page paths and seats


class CouncilIndex(views.Index):
    def __init__(self, cfg: dict, facts: dict, wards: list[dict]):
        self.cfg = cfg
        self.slug, self.body_key, self.body_name = cfg["slug"], cfg["body_key"], cfg["body_name"]
        self.nav_label = cfg["nav_label"]
        self.KIND_LABELS = {**config.KIND_LABELS, **cfg["kind_labels"]}
        self._rows, self._seen = holder_rows(wards, facts, cfg)
        self.year_pages = {}
        self.tx = None   # transcripts.Transcripts, set by build.py
        self.held_sentences = cfg.get("held_sentences")    # city-verify V5: one sentence per held check
        super().__init__(facts, self._rows)

    def make_seats(self, seat_rows):
        latest = self._seen or self.latest
        return Seats(seat_rows, self.officials, latest,
                     wording={"evidence": self.cfg["evidence"]["ward"], "latest": self.cfg["latest_words"]})

    history_by_year = True
    # official id -> {year: page key}: consecutive years share one history page while it stays under
    # config.PAGE_TARGET (build.py pack_years; city-pages/file-budget). A year not packed has its own page.
    year_pages: dict = {}

    def official_href(self, official_id: str) -> str:
        return f"{self.slug}/members/{official_id}.html"

    def year_page_key(self, official_id: str, year: str) -> str:
        return self.year_pages.get(official_id, {}).get(year, year)

    def official_year_href(self, official_id: str, year: str) -> str:
        key = self.year_page_key(official_id, year)
        page = f"{self.slug}/members/{official_id}/{key}.html"
        return page if key == year else f"{page}#year-{year}"

    def meeting_href(self, meeting_id: str, anchor: str = "") -> str:
        year = self.meetings[meeting_id]["date"][:4]
        if anchor == views.ATTENDANCE:
            anchor = f"{meeting_id}-{views.ATTENDANCE}"
        return f"{self.slug}/meetings/{year}{self.part_suffix('meeting', meeting_id)}.html#{anchor or meeting_id}"

    def item_href(self, item: dict) -> str:
        return f"{self.slug}/items/{item['year']}{self.part_suffix('item', item['id'])}.html#{item['id']}"

    def item_title(self, item: dict) -> str:
        return item["title"] or self.cfg["untitled_item"]

    def meeting_years(self) -> list[str]:
        return sorted({m["date"][:4] for m in self.facts["meetings"]})

    def home_href(self) -> str:
        return f"{self.slug}/index.html"

    def page_name(self, rest: str = "") -> str:
        return f"{self.nav_label}: {rest}" if rest else self.nav_label


def load(cfg: dict, facts: dict, wards: list[dict]) -> CouncilIndex:
    return CouncilIndex(cfg, facts, wards)


# ---------------------------------------------------------------------------------------------------------------
# Page views


def site_for(site: dict, cix: CouncilIndex) -> dict:
    """The site context for a council page: the header's coverage line and data date are the council's own."""
    rec = {"url": cix.cfg["record_url"], "label": cix.cfg["record_label"]} if cix.cfg.get("record_url") else None
    return {**site, "coverage": cix.coverage, "data_as_of": cix.data_as_of(), "record": rec}


def seat_list(cix: CouncilIndex) -> list[dict]:
    """The council's seats in order (wards by number, then title seats), each with its current holder: the same row
    for every seat (N1), the holder's name linked, or the fixed words when no current record is read."""
    seats = [f"{cix.cfg['seat_word']}-{n}" for n in range(1, config.SITE["ward_count"] + 1)]
    seats += [s for s in dict.fromkeys(cix.cfg["title_seats"].values())]
    out = []
    from .seats import seat_label
    for seat in seats:
        rec = cix.seats.current_of_seat(seat)
        holder = None
        if rec is not None and rec["official_id"] in cix.officials:
            holder = {"name": cix.officials[rec["official_id"]]["name"], "href": cix.official_href(rec["official_id"])}
        # a held-over record (holder_rows): the seat reads "not yet recorded", with one neutral line naming who the
        # record last placed there and that the latest list does not name them; never shown as the current member
        held = cix.seats.held_over_of_seat(seat) if holder is None else None
        note = None
        if held is not None and held["official_id"] in cix.officials:
            note = {"name": cix.officials[held["official_id"]]["name"], "href": cix.official_href(held["official_id"]),
                    "text": cix.seats.held_over_text(held)}
        out.append({"seat": seat, "label": seat_label(seat), "holder": holder, "note": note})
    return out


def home(cix: CouncilIndex) -> dict:
    """<slug>/index.html: the seats, the members (Current by seat, then Served previously, by surname, as the
    Officials page), and the meetings and items by year."""
    meetings_by_year: dict[str, int] = defaultdict(int)
    for m in cix.facts["meetings"]:
        meetings_by_year[m["date"][:4]] += 1
    items_by_year: dict[int, int] = defaultdict(int)
    for it in cix.facts["items"]:
        items_by_year[it["year"]] += 1
    return {**views.officials_page(cix), "seat_rows": seat_list(cix),
            "basis": views.observed_basis(cix) if cix.seats.loaded else None,
            "body": cix.body_name, "coverage": cix.coverage, "fetched": cix.fetched_sentence(),
            "meeting_years": [{"year": y, "n": meetings_by_year[y], "href": f"meetings/{y}.html"}
                              for y in sorted(meetings_by_year, reverse=True)],
            "item_years": [{"year": y, "n": items_by_year[y], "href": f"items/{y}.html"}
                           for y in sorted(items_by_year, reverse=True)],
            "glance": views.record_glance(cix)}


def meetings_year(year: str, cix: CouncilIndex) -> dict:
    """<slug>/meetings/<yyyy>.html: every meeting that year, oldest first, each with its attendance, motions and roll
    calls as on a county meeting page (views.meeting), under ids unique on the page."""
    out = []
    for m in sorted((m for m in cix.facts["meetings"] if m["date"][:4] == year), key=lambda m: (m["date"], m["id"])):
        ctx = views.meeting(m["id"], cix)
        src = cix.sources[m["source_id"]]
        agenda = cix.sources.get(m.get("agenda_source_id") or "")
        out.append({**ctx, "id": m["id"], "has_minutes": src["kind"] == "minutes",
                    "video_url": m.get("video_url"),
                    "transcript": cix.tx.meeting_entry(m["id"]) if cix.tx is not None else None,
                    "agenda": ({"url": agenda["url"], "pages": agenda["pages"], "fetched": localdates.fetched(agenda)}
                               if agenda and agenda["id"] != src["id"] else None)})
    return {"year": year, "meetings": out, "years": cix.meeting_years(), "body": cix.body_name, "parts": []}


def items_year(year: int, cix: CouncilIndex) -> dict:
    return {**views.items_year(year, cix), "years": cix.item_years(), "body": cix.body_name}


def member(official_id: str, cix: CouncilIndex) -> dict:
    """A member's page: the county's official view plus the call-ons found in the transcripts (the same section on
    every member's page, sitegen/transcripts.py)."""
    return {**views.official(official_id, cix),
            "called_on": cix.tx.member_rows(official_id) if cix.tx is not None else [],
            "transcripts_read": len(cix.tx.by_meeting) if cix.tx is not None else 0}


def landing_entry(cix: CouncilIndex) -> dict:
    """What the county landing shows of the council: a link, its coverage and its seats with current holders."""
    return {"label": cix.nav_label, "body": cix.body_name, "href": cix.home_href(),
            "from": cix.coverage["from"][:4], "to": cix.coverage["to"][:4],
            # the council's own basis line: its "current" is its latest minutes read, not the county's meeting
            "basis": views.observed_basis(cix) if cix.seats.loaded else None,
            "seats": [{**s, "href": f"{cix.home_href()}#seat-{s['seat']}",
                       "holder": ({**s["holder"], "href": s["holder"]["href"]} if s["holder"] else None)}
                      for s in seat_list(cix)]}
