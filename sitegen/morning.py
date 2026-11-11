"""The morning note (Daylight M3, docs/architecture/morning-note.md): each day's "what's new", as static JSON.

Nothing is sent and nothing about a reader is stored: the build writes morning/YYYY-MM-DD.json for the last
`keep_days` days and morning/latest.json (today's), and a later sender (behind the CEO's provider pick) only mails
what select() returns for each group of subscribers. Every list key, label and connective word is config
(config/site.yml `morning_note:`); nothing here names a place.

Window rule: the note for day D holds every document whose `first_fetched_at` (the collectors' own manifests, by
source URL) falls in [D-1 at `cutoff`, D at `cutoff`) in site_timezone. first_fetched_at never changes on a re-fetch,
so a document is new on one day only. Every document the note reads must have a manifest row, else the build fails.

A document becomes entries:
- an agenda: one `agenda_item` per item or case printed on it (none read: one `document` entry for the agenda);
- minutes: one `vote` per roll call (or motion without one) recorded on it. Outcome and tally only for a confirmed
  one (a county or council roll call the verifier passed, an RPC motion with confirmed == true); any other says
  config text `vote_unconfirmed` and carries no outcome, tally or names. No entry ever carries a person's name:
  movers, seconders, nays and per-official votes are left out (the M2 decision; a claim about a named person);
- a budget book: one `document`; a solicitation: one `solicitation` the day its first document is first fetched, and
  one `document` per later new document.
Titles are the record's own words (with the item or case number, as the feeds print them).

Lists: `budget` (item type rule `budget`, and budget books), `contracts` (solicitations and their documents), `seats`
(county entries for a stored district, council entries for a stored ward: `seat_body`), `zoning` (RPC cases whose
prefix is in `zoning_prefixes`, and county items linked to such a case by exact case number as Rpc.link_county links
them, inheriting the case's printed district and ward). A zoning entry matches "near me" only by printed district or
printed ward; one with neither never matches and is counted in `unplaced_zoning`.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, unofficial, views

SCHEMA = "morning-note/1"
FOLDER = "morning"
LIST_KEYS = ("zoning", "seats", "budget", "contracts")
KINDS = ("agenda_item", "vote", "document", "solicitation")
TEXT_KEYS = ("agenda_item", "vote", "vote_unconfirmed", "agenda", "minutes", "budget_book", "solicitation",
             "contract_document", "unplaced_zoning", "unplaced_zoning_one")
# `morning_note.page`: every word the sign-up section and the preview page print (sitegen/morning_page.py), and the
# placeholders each one must keep.
PAGE_KEYS = {"heading": (), "about": (), "legend": (), "state_off": (), "feeds_heading": (), "no_feed": (),
             "seats_hint": (), "seats_link": (), "preview_link": (), "email_label": (), "submit": (),
             "sent_line": ("{provider}",), "privacy_label": (), "preview_title": (),
             "seats_include": (), "seats_sent": ("{provider}", "{box}"), "method_heading": (),
             "method_sent": ("{provider}", "{box}"), "method_unsubscribe": (), "method_signup_link": (),
             "preview_lede": ("{date}", "{from}", "{to}"), "preview_mine": (), "quiet": (), "backfill": (),
             "unplaced_link": (), "source_label": (), "page_label": (), "district_label": (), "ward_label": (),
             "vote_on_label": ()}
FORM_FIELD_KEYS = ("email", "lists", "district", "ward")
_HTTPS = re.compile(r"https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?(?:/[^\s\"'<>`\\]*)?")


class MorningError(Exception):
    pass


def settings(cfg: dict | None = None) -> dict | None:
    cfg = config.SITE if cfg is None else cfg
    return cfg.get("morning_note")


def manifest_paths(cfg: dict | None = None) -> list:
    """The collectors' manifests the note reads: config/site.yml `fetch_manifests`, the one list the pages' fetch days
    come from too (sitegen/localdates.py; dates/two-manifest-lists)."""
    return list((config.SITE if cfg is None else cfg).get("fetch_manifests") or [])


def problems(cfg: dict) -> list[str]:
    """config/site.yml `morning_note:` shape and the provider seam rules; the build refuses anything else."""
    mn = cfg.get("morning_note")
    if mn is None:
        return []
    if not isinstance(mn, dict):
        return ["morning_note must be a mapping"]
    out = []
    lists = mn.get("lists")
    if not isinstance(lists, list) or not lists:
        out.append("morning_note.lists must be a non-empty list of {key, label}")
    else:
        keys = [x.get("key") if isinstance(x, dict) else None for x in lists]
        out += [f"morning_note.lists key {k!r} is not one of {', '.join(LIST_KEYS)}" for k in keys
                if k not in LIST_KEYS]
        if len(set(keys)) != len(keys):
            out.append("morning_note.lists has a key twice")
        out += [f"morning_note.lists {x.get('key')!r} needs a label" for x in lists
                if isinstance(x, dict) and not (isinstance(x.get("label"), str) and x["label"].strip())]
    if not (isinstance(mn.get("cutoff"), str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", mn["cutoff"])):
        out.append(f"morning_note.cutoff must be HH:MM, got {mn.get('cutoff')!r}")
    kd = mn.get("keep_days")
    if not isinstance(kd, int) or isinstance(kd, bool) or not 1 <= kd <= 31:
        out.append(f"morning_note.keep_days must be a whole number from 1 to 31, got {kd!r}")
    zp = mn.get("zoning_prefixes")
    if not isinstance(zp, list) or not zp or not all(isinstance(p, str) and re.fullmatch(r"[A-Z]+", p) for p in zp):
        out.append(f"morning_note.zoning_prefixes must be a list of case prefixes like Z, CZ, got {zp!r}")
    bf = mn.get("backfill")
    if not isinstance(bf, dict) or not all(isinstance(bf.get(k), int) and not isinstance(bf.get(k), bool)
                                           and bf[k] >= 1 for k in ("initial_run_hours", "max_entries")):
        out.append("morning_note.backfill must set initial_run_hours and max_entries, each a whole number >= 1")
    if "manifests" in mn:
        out.append("morning_note.manifests is gone: the note reads fetch_manifests (dates/two-manifest-lists)")
    man = cfg.get("fetch_manifests")
    if not isinstance(man, list) or not man or not all(isinstance(p, str) and p for p in man):
        out.append("fetch_manifests must list the collectors' manifest files (the morning note reads them)")
    text = mn.get("text")
    if not isinstance(text, dict):
        out.append("morning_note.text must be a mapping")
    else:
        out += [f"morning_note.text.{k} must be set" for k in TEXT_KEYS
                if not (isinstance(text.get(k), str) and text[k].strip())]
        if isinstance(text.get("unplaced_zoning"), str) and "{n}" not in text["unplaced_zoning"]:
            out.append("morning_note.text.unplaced_zoning must contain {n}")
    page = mn.get("page")
    if not isinstance(page, dict):
        out.append("morning_note.page must be a mapping (the sign-up section's and preview page's text)")
    else:
        for k, marks in PAGE_KEYS.items():
            v = page.get(k)
            if not (isinstance(v, str) and v.strip()):
                out.append(f"morning_note.page.{k} must be set")
            else:
                out += [f"morning_note.page.{k} must contain {m}" for m in marks if m not in v]
    # cr-your-seats (static/seats.js) keeps a ward number but not which council it is a ward of; every council's
    # entries are seat_body "ward". With two councils a stored ward would match both councils' items.
    councils = cfg.get("councils") or []
    if len(councils) > 1:
        out.append(f"morning_note supports one council (got {len(councils)}): the stored seats name a ward but not "
                   f"its council; name the council in cr-your-seats before adding a second")
    # provider seam (architecture "Provider seam"): off by default; on only with an https endpoint and a privacy page
    enabled = mn.get("enabled")
    if not isinstance(enabled, bool):
        out.append(f"morning_note.enabled must be true or false, got {enabled!r}")
    action, privacy = mn.get("form_action") or "", mn.get("privacy_url") or ""
    if not isinstance(mn.get("provider", ""), str):
        out.append("morning_note.provider must be text")
    if enabled is True:
        if not (isinstance(mn.get("provider"), str) and mn["provider"].strip()):
            out.append("morning_note.enabled is true, so provider must name who receives the form")
        if not (isinstance(action, str) and _HTTPS.fullmatch(action)):
            out.append(f"morning_note.enabled is true, so form_action must be an https URL, got {action!r}")
        if not (isinstance(privacy, str) and _HTTPS.fullmatch(privacy)):
            out.append(f"morning_note.enabled is true, so privacy_url must be an https URL, got {privacy!r}")
    elif action:
        out.append("morning_note.form_action must be empty while morning_note.enabled is false")
    ff = mn.get("form_fields")
    if not isinstance(ff, dict) or sorted(ff) != sorted(FORM_FIELD_KEYS) or \
            not all(isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_-]+", v) for v in ff.values()):
        out.append(f"morning_note.form_fields must map {', '.join(FORM_FIELD_KEYS)} to plain field names")
    return out + sender_problems(cfg)


# `morning_note.sender` (ADR 0004; package sender/): every key, and the placeholders each text must keep.
SENDER_KEYS = ("enabled", "provider", "api_base", "mode", "send_at", "latest_send", "max_editions",
               "max_recipients", "canary_only", "link_hosts", "text")
SENDER_MODES = ("stamp", "ids")
SENDER_TEXT_KEYS = {"subject": ("{site_name}", "{date}"), "why": (), "open_site": ()}
_HHMM = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
_API_BASE = re.compile(r"https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~/-]*)?")


def reader_problems(path=None) -> list[str]:
    """settings-parity: the deliver job reads config/site.yml without PyYAML (sender/settings.py). Every value it
    reads must be what PyYAML reads from the same file, or the build fails. The file itself, not config.SITE: the
    environment may override alerts.site_url there, and the deliver job sees only the file."""
    import yaml

    from sender import settings as sender_settings
    text = Path(path or config.SITE_CONFIG_PATH).read_text(encoding="utf-8")
    return sender_settings.parity(text, yaml.safe_load(text))


def sender_problems(cfg: dict) -> list[str]:
    """The sender block's shape and its switch rules. Left out: no sender, nothing to check. `enabled: true` is
    refused unless the sign-up form is enabled too and the site URL is set (an email links only live pages)."""
    mn = cfg.get("morning_note")
    s = mn.get("sender") if isinstance(mn, dict) else None
    if s is None:
        return []
    if not isinstance(s, dict):
        return ["morning_note.sender must be a mapping"]
    at = "morning_note.sender"
    out = [f"{at}.{k} is not a known key" for k in s if k not in SENDER_KEYS]
    out += [f"{at}.{k} must be set" for k in SENDER_KEYS if k not in s]
    for k in ("enabled", "canary_only"):
        if k in s and not isinstance(s[k], bool):
            out.append(f"{at}.{k} must be true or false, got {s[k]!r}")
    if "provider" in s and not (isinstance(s["provider"], str) and s["provider"].strip()):
        out.append(f"{at}.provider must name the mail provider")
    if "api_base" in s and not (isinstance(s["api_base"], str) and _API_BASE.fullmatch(s["api_base"])):
        out.append(f"{at}.api_base must be an https URL, got {s['api_base']!r}")
    elif "provider" in s and "api_base" in s:
        from sender.settings import api_base_problem     # settings/api-base-host: one rule, the deliver stage's
        out += [p + f", got {s['api_base']!r}" for p in [api_base_problem(s["provider"], s["api_base"])] if p]
    if "mode" in s and s["mode"] not in SENDER_MODES:
        out.append(f"{at}.mode must be {' or '.join(SENDER_MODES)}, got {s['mode']!r}")
    times = {k: s[k] for k in ("send_at", "latest_send") if k in s}
    bad = [k for k, v in times.items() if not (isinstance(v, str) and _HHMM.fullmatch(v))]
    out += [f"{at}.{k} must be HH:MM, got {times[k]!r}" for k in bad]
    if len(times) == 2 and not bad and not times["send_at"] < times["latest_send"]:
        out.append(f"{at}.send_at must be before latest_send")
    for k in ("max_editions", "max_recipients"):
        if k in s and (not isinstance(s[k], int) or isinstance(s[k], bool) or s[k] < 1):
            out.append(f"{at}.{k} must be a whole number >= 1, got {s[k]!r}")
    text = s.get("text")
    if "text" in s and not isinstance(text, dict):
        out.append(f"{at}.text must be a mapping")
    elif isinstance(text, dict):
        out += [f"{at}.text.{k} is not a known key" for k in text if k not in SENDER_TEXT_KEYS]
        for k, marks in SENDER_TEXT_KEYS.items():
            v = text.get(k)
            if not (isinstance(v, str) and v.strip()):
                out.append(f"{at}.text.{k} must be set")
            else:
                out += [f"{at}.text.{k} must contain {m}" for m in marks if m not in v]
        from sender.render import AUTHORITY      # render/no-independence-line: never a government's name or "official"
        subj = text.get("subject")
        if isinstance(subj, str) and AUTHORITY.search(subj.replace("{site_name}", str(cfg.get("site_name") or ""))):
            out.append(f"{at}.text.subject must not name a government body or say official, got {subj!r}")
    from sender.common import exact_url_ok, parse_hosts     # plan-untrusted/body-unchecked: what an email links
    if cfg.get("support_url") not in (None, "") and not exact_url_ok(cfg["support_url"]):
        out.append(f"support_url must be one https URL on a lower-case host, with no user or port (the deliver "
                   f"stage allows the note's support link as exactly this URL), got {cfg['support_url']!r}")
    hosts: tuple = ()
    if "link_hosts" in s:
        try:
            hosts = parse_hosts(s["link_hosts"])
        except ValueError as exc:
            out.append(f"{at}.{exc}, got {s['link_hosts']!r}")
    if s.get("enabled") is True:
        site = str((cfg.get("alerts") or {}).get("site_url") or "")
        if site.startswith("https://") and site[len("https://"):].split("/")[0] not in hosts:
            out.append(f"{at}.enabled is true, so link_hosts must hold the site's host "
                       f"({site[len('https://'):].split('/')[0]}): an email links its pages")
        if mn.get("enabled") is not True:
            out.append(f"{at}.enabled is true, so morning_note.enabled must be true (the sign-up form)")
        if not (cfg.get("alerts") or {}).get("site_url"):
            out.append(f"{at}.enabled is true, so alerts.site_url must be set: an email links only live pages")
    return out


# ---------------------------------------------------------------------------------------------- manifests, window
def manifest_rows(path) -> list[tuple[str, datetime]]:
    """One collector manifest's rows as (url, first_fetched_at), each row checked: a URL and an aware timestamp."""
    p = Path(path)
    if not p.is_absolute():
        p = config.REPO_ROOT / p
    if not p.is_file():
        raise MorningError(f"morning note: no manifest {p}")
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MorningError(f"{p}: not valid JSON ({exc})") from None
    if not isinstance(rows, list):
        raise MorningError(f"{p}: a manifest is a list of rows")
    out = []
    for n, row in enumerate(rows, 1):
        url = row.get("url") if isinstance(row, dict) else None
        if not isinstance(url, str) or not url:
            raise MorningError(f"{p}: row {n} has no url")
        raw = row.get("first_fetched_at")
        try:
            when = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            raise MorningError(f"{p}: {url!r} has no usable first_fetched_at ({raw!r})") from None
        if when.tzinfo is None:
            raise MorningError(f"{p}: {url!r} first_fetched_at has no time zone ({raw!r})")
        out.append((url, when))
    return out


def first_fetched(paths) -> dict[str, datetime]:
    """{source URL: first_fetched_at} over the collectors' manifests (the earliest, should a URL be in two)."""
    out: dict[str, datetime] = {}
    for p in paths:
        for url, when in manifest_rows(p):
            if url not in out or when < out[url]:
                out[url] = when
    return out


def bulk_urls(paths, hours: int) -> frozenset[str]:
    """Source URLs a collector first fetched in its initial (bulk) run: within `hours` of the earliest
    first_fetched_at in that collector's manifest. A new collector's first run counts the same way."""
    out = set()
    for p in paths:
        whens = manifest_rows(p)
        if not whens:
            continue
        start = min(w for _, w in whens)
        out |= {u for u, w in whens if w < start + timedelta(hours=hours)}
    return frozenset(out)


def window(day: date, cutoff: str, tz: str) -> tuple[datetime, datetime]:
    """[day before at cutoff, day at cutoff) in the site's zone."""
    zone = ZoneInfo(tz)
    hh, mm = (int(x) for x in cutoff.split(":"))
    end = datetime.combine(day, time(hh, mm), zone)
    start = datetime.combine(day - timedelta(days=1), time(hh, mm), zone)
    return start, end


def note_day(when: datetime, cutoff: str, tz: str) -> date:
    """The note a document first fetched at `when` belongs to: the day whose window() holds it (one rule)."""
    d = when.astimezone(ZoneInfo(tz)).date()
    start, end = (x.astimezone(timezone.utc) for x in window(d, cutoff, tz))   # compare instants, not wall clocks
    at = when.astimezone(timezone.utc)
    return d + timedelta(days=1) if at >= end else d - timedelta(days=1) if at < start else d


def _stamp(dt: datetime) -> str:
    s = dt.isoformat(timespec="minutes")
    return s


# ---------------------------------------------------------------------------------------------- documents
def _entry(**kw) -> dict:
    e = {"id": None, "lists": [], "kind": None, "body": None, "body_name": None, "meeting_date": None, "title": None,
         "title_ours": False, "recorded": None, "district": None, "ward": None, "case": None, "seat_body": None,
         "href": None, "source": {"url": None, "page": None}}
    e.update(kw)
    e["lists"] = [k for k in LIST_KEYS if k in e["lists"]]
    return e


def _number_title(number: str | None, title: str) -> str:
    return f"{number}: {title}" if number and title != number else title


def _case_title(c: dict) -> str:
    return _number_title(c["number_printed"] or c["number"], c.get("request") or c.get("case_type") or c["number"])


class _Zoning:
    """RPC zoning cases (prefix in zoning_prefixes) and the county items linked to them by exact case number."""

    def __init__(self, rpx, prefixes):
        self.prefixes = set(prefixes)
        self.by_key: dict[str, dict] = {}
        if rpx is None:
            return
        from collector.rpc_minutes import link_key
        from .rpc import COUNTY_PREFIXES
        self.link_key = link_key
        dates = {m["id"]: m["date"] for m in rpx.facts["meetings"]}
        # the newest printing of each county-zoning case number carries its district and ward
        for c in sorted(rpx.facts["cases"], key=lambda c: (dates[c["meeting_id"]], c["id"])):
            if c["prefix"] in COUNTY_PREFIXES and c["prefix"] in self.prefixes:
                k = link_key(c["number"])
                if k:
                    self.by_key[k] = c

    def is_zoning(self, c: dict) -> bool:
        return c["prefix"] in self.prefixes

    def county_case(self, number: str | None) -> dict | None:
        if not self.by_key or not number:
            return None
        return self.by_key.get(self.link_key(number) or "")


def _seat_fields(case: dict | None) -> dict:
    """A zoning entry's printed district and ward, and `case`: the case number in its one comparable form
    (rpc_minutes.link_key), so the unplaced count counts each case once however many entries name it."""
    if case is None:
        return {}
    from collector.rpc_minutes import link_key
    return {"district": case.get("district"), "ward": case.get("ward"),
            "case": link_key(case["number"]) or case["number"]}


def _index_documents(ix, body: str, body_name: str, seat_body: str, txt: dict, zoning: _Zoning | None) -> list[dict]:
    """A county or council facts file: each minutes (or agenda) source, with its entries. One source can be named by
    more than one meeting (minutes covering two meetings), so every entry takes its meeting, and with it the date,
    label and link, from the fact's own meeting_id; the source gives only the document's URL."""
    by_source: dict[str, list] = {}     # source id: every meeting naming it, in the facts' order
    for m in ix.facts["meetings"]:
        for sid in dict.fromkeys(x for x in (m["source_id"], m.get("agenda_source_id")) if x):
            if sid in ix.sources:
                by_source.setdefault(sid, []).append(m)
    rcs_by_source: dict[str, list] = {}
    for rc in ix.facts["roll_calls"]:
        rcs_by_source.setdefault(rc["source_id"], []).append(rc)
    with_rc = {rc["motion_id"] for rc in ix.facts["roll_calls"] if rc["motion_id"]}
    mos_by_source: dict[str, list] = {}
    for mo in ix.facts["motions"]:
        if mo["id"] not in with_rc:
            mos_by_source.setdefault(mo["source_id"], []).append(mo)
    docs = []
    for sid, named_by in by_source.items():
        s = ix.sources[sid]
        entries = []
        if s["kind"] == "minutes":
            for fact in sorted(rcs_by_source.get(sid, []) + mos_by_source.get(sid, []),
                               key=lambda f: (f["page"], f["id"])):
                m = ix.meetings[fact["meeting_id"]]
                is_rc = "votes" in fact
                it = ix.items.get(fact.get("item_id") or "")
                confirmed = bool(is_rc and views.is_verified(fact))
                case = zoning.county_case(it.get("number")) if (zoning and it) else None
                title = _number_title(it.get("number"), ix.item_title(it)) if it else ix.meeting_label(m)
                tally = fact.get("stated_tally") if confirmed else None
                # what the roll call voted on, as its own outcome clause states it ("Amendment", "Resolution, as
                # amended": views.outcome_kind_label, the site's "Vote on" rule), so two votes on one item read apart
                # (morning-digest/vote-entries-indistinct). Confirmed roll calls only, like the outcome; no name.
                vote_on = views.outcome_kind_label(fact.get("outcome_text")) if confirmed else None
                entries.append(_entry(
                    id=f"{body}/vote/{fact['id']}", kind="vote", body=body, body_name=body_name,
                    meeting_date=m["date"], title=title,
                    lists=["seats"] + (["budget"] if it and "budget" in views.item_types(it) else [])
                    + (["zoning"] if case else []),
                    recorded=txt["vote"] if confirmed else txt["vote_unconfirmed"], seat_body=seat_body,
                    confirmed=confirmed, vote_on=vote_on,
                    outcome=config.OUTCOME_LABELS[fact["outcome"]] if confirmed else None,
                    tally=(f"{tally['yes']}-{tally['no']}" + (f"-{tally['abstain']}" if tally.get("abstain") else "")
                           if tally else None),
                    href=ix.item_href(it) if it else ix.meeting_href(m["id"]),
                    source={"url": f"{s['url']}#page={fact['page']}", "page": fact["page"]},
                    title_ours=not (it and it.get("title")), **_seat_fields(case)))
        else:   # an agenda: the items printed on it, as the facts record them
            seen = {}
            for e in ix.facts["item_events"]:
                if e["source_id"] == sid and e["item_id"] in ix.items:
                    seen.setdefault((e["item_id"], e["meeting_id"]), e)
            for (item_id, _), e in sorted(seen.items(), key=lambda kv: (kv[1]["page"], kv[1]["order"], kv[0])):
                it = ix.items[item_id]
                m = ix.meetings[e["meeting_id"]]
                case = zoning.county_case(it.get("number")) if zoning else None
                entries.append(_entry(
                    id=f"{body}/item/{item_id}/{m['id']}", kind="agenda_item", body=body, body_name=body_name,
                    meeting_date=m["date"], title=_number_title(it.get("number"), ix.item_title(it)),
                    lists=["seats"] + (["budget"] if "budget" in views.item_types(it) else [])
                    + (["zoning"] if case else []), title_ours=not it.get("title"),
                    recorded=txt["agenda_item"], seat_body=seat_body, href=ix.item_href(it),
                    source={"url": f"{s['url']}#page={e['page']}", "page": e["page"]}, **_seat_fields(case)))
        if not entries:     # nothing itemised: the document itself, once for each meeting naming it
            entries += [_entry(
                id=f"{body}/meeting/{m['id']}/{s['kind']}", kind="document", body=body, body_name=body_name,
                meeting_date=m["date"], title=ix.meeting_label(m), title_ours=True, lists=["seats"],
                seat_body=seat_body, recorded=txt["minutes"] if s["kind"] == "minutes" else txt["agenda"],
                href=ix.meeting_href(m["id"]), source={"url": s["url"], "page": None}) for m in named_by]
        docs.append({"url": s["url"], "entries": entries})
    return docs


def _agenda_only_documents(ax, ix, body: str, body_name: str, txt: dict, zoning: _Zoning | None) -> list[dict]:
    """County agendas posted before their minutes (data/county-agendas/agendas.json): every agenda in the file, so a
    meeting the minutes now cover still has its agenda's day."""
    from . import county_agendas
    listed = {m["id"] for m in ax.meetings}
    docs = []
    for m in ax.data.get("meetings", []):
        s = ax.sources.get(m["source_id"])
        if s is None:
            continue
        entries, used = [], set()
        for it in m["items"]:
            known = ix.items.get(it["number"])
            iid = it["number"] or it["id"]
            eid = f"{body}/item/{iid}/{m['id']}"
            n = 1
            while eid in used:     # a number printed twice on one agenda
                n += 1
                eid = f"{body}/item/{iid}/{m['id']}/{n}"
            used.add(eid)
            case = zoning.county_case(it["number"]) if zoning else None
            title = _number_title(it["number"], it.get("title") or it["number"] or "")
            href = ix.item_href(known) if known else (ax.href(m["id"]) if m["id"] in listed else county_agendas.PAGE)
            entries.append(_entry(
                id=eid, kind="agenda_item", body=body, body_name=body_name, meeting_date=m["date"], title=title,
                lists=["seats"] + (["budget"] if "budget" in views.item_types(it) else []) + (["zoning"] if case else []),
                recorded=txt["agenda_item"], seat_body="district", href=href,
                source={"url": f"{s['url']}#page={it['page']}", "page": it["page"]}, **_seat_fields(case)))
        if not entries:
            entries.append(_entry(
                id=f"{body}/meeting/{m['id']}/agenda", kind="document", body=body, body_name=body_name,
                meeting_date=m["date"], title=f"{m['date']}, {ix.kind_labels.get(m['kind'], m['kind']).lower()}",
                title_ours=True, lists=["seats"], seat_body="district", recorded=txt["agenda"],
                href=ax.href(m["id"]) if m["id"] in listed else county_agendas.PAGE,
                source={"url": s["url"], "page": None}))
        docs.append({"url": s["url"], "entries": entries})
    return docs


def _rpc_documents(rpx, txt: dict, zoning: _Zoning) -> list[dict]:
    """RPC agendas (one entry per zoning case printed) and minutes (one per motion on a zoning case). Other case
    types belong to no list, so they make no entry."""
    meetings = {m["id"]: m for m in rpx.facts["meetings"]}
    cases = {c["id"]: c for c in rpx.facts["cases"]}
    by_source: dict[str, list] = {}
    for c in rpx.facts["cases"]:
        by_source.setdefault(c["source_id"], []).append(("case", c))
    for mv in rpx.facts.get("motions", []):
        by_source.setdefault(mv["source_id"], []).append(("motion", mv))
    docs = []
    body, name = rpx.body_key, rpx.body
    for s in rpx.facts["sources"]:
        entries = []
        for what, f in sorted(by_source.get(s["id"], []), key=lambda x: (x[1]["page"], x[1]["id"])):
            c = f if what == "case" else cases.get(f["case_id"] or "")
            if c is None or not zoning.is_zoning(c):
                continue
            m = meetings[f["meeting_id"]]
            href = f"{rpx.year_href(m['date'][:4])}#{rpx.case_anchor(c)}" if c["meeting_id"] in meetings else None
            common = dict(body=body, body_name=name, meeting_date=m["date"], title=_case_title(c), lists=["zoning"],
                          **_seat_fields(c), href=href,
                          source={"url": f"{s['url']}#page={f['page']}", "page": f["page"]})
            if what == "case":
                entries.append(_entry(id=f"{body}/item/{c['id']}/{m['id']}", kind="agenda_item",
                                      recorded=txt["agenda_item"], **common))
            else:
                ok = f.get("confirmed") is True     # anything else: no outcome, tally or names
                entries.append(_entry(id=f"{body}/vote/{f['id']}", kind="vote", confirmed=ok,
                                      recorded=txt["vote"] if ok else txt["vote_unconfirmed"],
                                      outcome=f.get("outcome") if ok else None, tally=f.get("tally") if ok else None,
                                      **common))
        docs.append({"url": s["url"], "entries": entries})
    return docs


def _finance_documents(fx, bg, cfg: dict, txt: dict, first: dict[str, datetime], cutoff: str, tz: str) -> list[dict]:
    """Budget books, and each solicitation: its entry on the day its first document is first fetched, then one
    `document` entry per document first fetched on a later day."""
    fin = fx.fin
    sources = {s["id"]: s for s in fin["sources"]}
    name = cfg["county_name"]
    docs = []
    for b in fin.get("books", []):
        s = sources.get(b.get("source_id") or "")
        if s is None:
            continue
        docs.append({"url": s["url"], "entries": [_entry(
            id=f"finance/book/{b['id']}", kind="document", body="finance", body_name=name, title=b["title"],
            lists=["budget"], recorded=txt["budget_book"], href="finance/index.html" if bg is not None else None,
            source={"url": s["url"], "page": None})]})
    fdocs = {d["id"]: d for d in fin.get("documents", [])}
    for sol in fin.get("solicitations", []):
        ds = [fdocs[i] for i in sol.get("document_ids", []) if i in fdocs and fdocs[i].get("source_id") in sources]
        if not ds:
            continue
        urls = [sources[d["source_id"]]["url"] for d in ds]
        known = [first[u] for u in urls if u in first]
        if len(known) != len(urls):     # resolve() reports the missing rows; nothing is guessed here
            docs += [{"url": u, "entries": []} for u in urls]
            continue
        first_day = note_day(min(known), cutoff, tz)
        href = f"contracts/{sol['slug']}.html"
        common = dict(body="contracts", body_name=name, meeting_date=None, lists=["contracts"], href=href)
        opened = False
        for d, u in sorted(zip(ds, urls), key=lambda x: (first[x[1]], x[0]["id"])):
            if note_day(first[u], cutoff, tz) == first_day:
                entries = [] if opened else [_entry(
                    id=f"contracts/solicitation/{sol['id']}", kind="solicitation", title=sol["title"],
                    recorded=txt["solicitation"], source={"url": u, "page": None}, **common)]
                opened = True
            else:
                entries = [_entry(id=f"contracts/document/{sol['id']}/{d['id']}", kind="document",
                                  title=f"{sol['title']}: {d['link_label']}", recorded=txt["contract_document"],
                                  source={"url": u, "page": None}, **common)]
            docs.append({"url": u, "entries": entries})
    return docs


def documents(ix, councils=(), rpx=None, ax=None, fx=None, bg=None, first=None, cfg: dict | None = None) -> list[dict]:
    """Every document the note reads, [{url, entries}], from the county, each council, the county agendas, the RPC
    and finance. `first`: first_fetched (finance needs it to tell a new solicitation from a new document)."""
    cfg = config.SITE if cfg is None else cfg
    mn = settings(cfg)
    txt = mn["text"]
    zoning = _Zoning(rpx, mn["zoning_prefixes"])
    docs = _index_documents(ix, cfg["county_key"], cfg["county_body"], "district", txt, zoning)
    if ax is not None:
        docs += _agenda_only_documents(ax, ix, cfg["county_key"], cfg["county_body"], txt, zoning)
    for c in councils:
        docs += _index_documents(c, c.body_key, c.body_name, "ward", txt, None)
    if rpx is not None:
        docs += _rpc_documents(rpx, txt, zoning)
    if fx is not None:
        docs += _finance_documents(fx, bg, cfg, txt, first or {}, mn["cutoff"], cfg["site_timezone"])
    _add_watch(docs, ix, councils, cfg)
    return docs


def _add_watch(docs: list[dict], ix, councils, cfg: dict) -> None:
    """Each entry about a meeting carries `watch` (sitegen/watch.py): {url, link, label, ext} or null. A council
    meeting's own recording when exactly one meeting of that body on that date carries one, else the body's page;
    null for a body with no `video:` entry and for an entry with no meeting (a solicitation)."""
    from . import watch
    recordings: dict[tuple, set] = {}
    for b, facts in [(cfg["county_key"], ix.facts), *((c.body_key, c.facts) for c in councils)]:
        for m in facts["meetings"]:
            recordings.setdefault((b, m["date"]), set()).add(m.get("video_url") or "")
    for d in docs:
        for e in d["entries"]:
            if not e.get("meeting_date"):
                e["watch"] = None
                continue
            vids = recordings.get((e["body"], e["meeting_date"]), set())
            e["watch"] = watch.meeting(e["body"], next(iter(vids)) if len(vids) == 1 else None, cfg)


def resolve(docs: list[dict], first: dict[str, datetime]) -> None:
    """Every document must have a manifest row (architecture, Risks): a document without one would never alert."""
    missing = sorted({d["url"] for d in docs if d["url"] not in first})
    if missing:
        raise MorningError(f"morning note: {len(missing)} document(s) have no row in any collector manifest, "
                           f"e.g. {', '.join(missing[:5])}")


# ---------------------------------------------------------------------------------------------- the day, select
def as_of(d: date, fetch_dates) -> str:
    """A note's `data_as_of`: the newest fetch date on or before the note's day `d`, "" when there is none
    (morning-digest/data-as-of). `fetch_dates` is every source's fetch day (YYYY-MM-DD, as localdates.days gives
    it) from every data file the note reads, so each day's note states its own date, not the build's. A plain
    string is one date for every day, as given.
    Fallback (data_as_of_utc true: some source has no recorded instant, so these are stored UTC days): the `<= d`
    comparison is kept on purpose. A UTC day is the local day or the day after it, so a fetch on the evening of `d`
    (UTC day d+1) is left out of d's note: the note may state an older day, never one after its own."""
    if isinstance(fetch_dates, str):
        return fetch_dates
    dates = [x[:10] for x in fetch_dates or () if isinstance(x, str) and x[:10] <= d.isoformat()
             and re.fullmatch(r"\d{4}-\d\d-\d\d", x[:10])]
    return max(dates, default="")


def day(d: date, docs: list[dict], first: dict[str, datetime], cfg: dict | None = None,
        data_as_of="", bulk: frozenset[str] = frozenset(), data_as_of_utc: bool = False) -> dict:
    """The note for day `d` (the output contract): every entry of every document first fetched in d's window.
    `data_as_of`: every source's fetch date (as_of picks the day's), or one string for every day.
    Backfill guard: a day holding any document from a collector's initial run (`bulk`, bulk_urls) or more than
    morning_note.backfill.max_entries entries is a backfill day: `"backfill": true` and `entries: []` (nothing to
    send), its counts kept in `counts`."""
    cfg = config.SITE if cfg is None else cfg
    mn = settings(cfg)
    resolve(docs, first)
    start, end = window(d, mn["cutoff"], cfg["site_timezone"])
    entries, ids, from_bulk = [], set(), False
    for doc in docs:
        if start <= first[doc["url"]] < end:
            from_bulk = from_bulk or doc["url"] in bulk
            for e in doc["entries"]:
                if e["lists"] and e["id"] not in ids:
                    ids.add(e["id"])
                    entries.append(e)
    entries.sort(key=lambda e: (LIST_KEYS.index(e["lists"][0]), e["body"], e["meeting_date"] or "",
                                e["source"]["page"] or 0, e["id"]))
    # distinct cases, not entries: one case on an agenda and in the minutes is one case that printed no seat
    unplaced = len({e["case"] or e["id"] for e in entries
                    if "zoning" in e["lists"] and e["district"] is None and e["ward"] is None})
    backfill = from_bulk or len(entries) > mn["backfill"]["max_entries"]
    counts = {"entries": len(entries), "lists": {k: sum(1 for e in entries if k in e["lists"]) for k in LIST_KEYS},
              "unplaced_zoning": unplaced}
    if backfill:
        entries, unplaced = [], 0
    u = unofficial.load(cfg if "unofficial" in cfg else None)
    support_on = cfg.get("support_enabled") is True and bool(cfg.get("support_url"))
    return {"schema": SCHEMA, "date": d.isoformat(),
            "window": {"from": _stamp(start), "to": _stamp(end)}, "data_as_of": as_of(d, data_as_of),
            "data_as_of_utc": data_as_of_utc,
            "lists": [{"key": x["key"], "label": x["label"]} for x in mn["lists"]],
            "backfill": backfill, "counts": counts,
            "entries": entries, "unplaced_zoning": unplaced,
            "unplaced_text": unplaced_text(unplaced, cfg),
            # the mail sender prints these in every note's text and footer (unofficial/notice-on-every-page)
            "notice": u["notice"], "email_line": u["email_line"],
            # the ask for support, printed in the footer when the support link is on (Brian, 2026-11-10)
            "support_line": (cfg.get("support_line") or "") if support_on else "",
            "support_url": (cfg.get("support_url") or "") if support_on else ""}


def unplaced_text(n: int, cfg: dict | None = None) -> str:
    """The one line for `n` zoning cases that printed no district or ward (config text, singular for one)."""
    if not n:
        return ""
    text = settings(cfg)["text"]
    return text["unplaced_zoning_one"] if n == 1 else text["unplaced_zoning"].format(n=n)


def own_text(note: dict) -> list[str]:
    """Every string of the note that is ours, not the record's: list labels, connective text, body names (all
    config) and the titles we make (`title_ours`: a meeting's label, an agenda's date and kind). Verbatim titles and
    source URLs are the record's own words and are left out of the neutrality scan."""
    out = [x["label"] for x in note["lists"]] + ([note["unplaced_text"]] if note["unplaced_text"] else [])
    for e in note["entries"]:
        out += [e["recorded"], e["body_name"]] + ([e["title"]] if e.get("title_ours") else [])
        out += [e["vote_on"]] if e.get("vote_on") else []       # a fixed config label, never the record's text
        out += [e["watch"]["link"], e["watch"]["label"]] if e.get("watch") else []   # config text
    return out


def _seat_match(e: dict, key: str, seats: dict) -> bool:
    district, ward = seats.get("district"), seats.get("ward")
    if key == "zoning":
        return (district is not None and e["district"] == district) or (ward is not None and e["ward"] == ward)
    if key == "seats":
        return (e["seat_body"] == "district" and district is not None) or \
            (e["seat_body"] == "ward" and ward is not None)
    return True


def select(note: dict, lists, seats: dict | None = None) -> list[dict]:
    """The one filter: the note's entries for a set of list keys and stored seats ({district, ward}, each a number
    or None). budget/contracts by list membership; zoning and seats also need the seat match. morning.js mirrors it."""
    seats = seats or {}
    want = [k for k in LIST_KEYS if k in set(lists)]
    return [e for e in note["entries"] if any(k in e["lists"] and _seat_match(e, k, seats) for k in want)]


# ---------------------------------------------------------------------------------------------- files
def write(out: Path, today: date, docs: list[dict], first: dict[str, datetime], cfg: dict | None = None,
          data_as_of="", bulk: frozenset[str] = frozenset(), data_as_of_utc: bool = False) -> dict:
    """morning/YYYY-MM-DD.json for the last keep_days days and morning/latest.json; returns today's note. Written
    on the pages target only (build.py): the preview may leave sections out (docs/status.md, 2026-11-09)."""
    cfg = config.SITE if cfg is None else cfg
    folder = Path(out) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    today_note = None
    for back in range(settings(cfg)["keep_days"]):
        d = today - timedelta(days=back)
        note = day(d, docs, first, cfg, data_as_of, bulk, data_as_of_utc)
        text = json.dumps(note, ensure_ascii=False, indent=1, sort_keys=False) + "\n"
        (folder / f"{d.isoformat()}.json").write_text(text, encoding="utf-8")
        if back == 0:
            today_note = note
            (folder / "latest.json").write_text(text, encoding="utf-8")
    return today_note
