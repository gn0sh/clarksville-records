"""The plan stage, which is also the dry run (architecture "T4 sender", Plan stage, and "One edition for everyone";
ADR 0004, decisions 3 and 6).

A pure function of one day's note and config/site.yml: it reads `<site>/morning/<D>.json` and, on a day with
entries, writes **one edition** holding every entry of the note, in the note's order, each under its first list
(invariant one-edition: every confirmed subscriber gets the same note). It writes `<out>/<D>/plan.json` and, for a
person to read, `edition-<key>.html` and `.txt` beside it. Two runs on the same note give byte-identical files.

Nothing here opens a connection, reads a secret or knows a subscriber: the plan holds no personal data.

While `morning_note.sender.enabled` is false (the default) the plan is `send: false`, reason "disabled", with no
edition, and the note is not even read. `rehearse=True` (`--rehearse`) is the dry run for a disabled sender: the
edition is written for a person to read, and the plan still says `send: false`, which the deliver stage treats as
"open no connection".
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from sitegen import morning

from . import common, deliver, render
from .common import LIST_KEYS, NOTE_SCHEMA, PLAN_SCHEMA


class PlanError(Exception):
    """The run must fail (exit 2): the note is missing or wrong, or the plan is over MAX_PLAN_BYTES. While the
    sender is disabled (a rehearsal), `python -m sender plan` prints it and exits 0 instead."""


def sender_settings(cfg: dict) -> dict:
    return ((cfg.get("morning_note") or {}).get("sender")) or {}


def enabled(cfg: dict) -> bool:
    return sender_settings(cfg).get("enabled") is True


def read_note(site: Path, day: date) -> tuple[dict, bytes]:
    """The note file for `day` and its bytes, checked: the schema, the date, and the fields the plan reads."""
    path = Path(site) / morning.FOLDER / f"{day.isoformat()}.json"
    if not path.is_file():
        raise PlanError(f"no note file for {day.isoformat()}: {path}")
    raw = path.read_bytes()
    try:
        note = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanError(f"{path}: not valid JSON ({exc})") from None
    if not isinstance(note, dict) or note.get("schema") != NOTE_SCHEMA:
        raise PlanError(f"{path}: schema is not {NOTE_SCHEMA!r}")
    if note.get("date") != day.isoformat():
        raise PlanError(f"{path}: the note is for {note.get('date')!r}, not {day.isoformat()}")
    entries, lists = note.get("entries"), note.get("lists")
    if not isinstance(entries, list) or not isinstance(lists, list) or not isinstance(note.get("backfill"), bool):
        raise PlanError(f"{path}: entries, lists or backfill is missing")
    if not all(isinstance(x, dict) and x.get("key") in LIST_KEYS and isinstance(x.get("label"), str) for x in lists):
        raise PlanError(f"{path}: lists must be {{key, label}} with a known key")
    seen = set()
    for e in entries:
        ok = isinstance(e, dict) and isinstance(e.get("id"), str) and e["id"] and "\n" not in e["id"] \
            and isinstance(e.get("lists"), list) and e["lists"] and set(e["lists"]) <= set(LIST_KEYS) \
            and all(k in e for k in ("district", "ward", "seat_body"))
        if not ok or e["id"] in seen:
            raise PlanError(f"{path}: an entry is malformed or its id is used twice")
        seen.add(e["id"])
    return note, raw


def one_edition(note: dict) -> list[tuple[str, str]]:
    """[(entry id, the list key it stands under)] for the day's one edition: every entry of the note, none
    filtered, in the note's order, each under its first list (`e["lists"][0]`). The note is already sorted by first
    list in LIST_KEYS order (sitegen.morning.write), so email order = note order = the preview page's order."""
    return [(e["id"], e["lists"][0]) for e in note["entries"]]


def edition_key(day: str, rows: list[tuple[str, str]]) -> str:
    """The first 12 hex of sha256 over the day and each (entry id, list) row: the edition's name, which changes
    whenever its entries or their headings do."""
    return hashlib.sha256((day + "\n" + "\n".join(f"{i}\t{k}" for i, k in rows)).encode("utf-8")).hexdigest()[:12]


def _at(day: date, hhmm: str, tz: str) -> str:
    hh, mm = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(hh, mm), ZoneInfo(tz)).isoformat(timespec="seconds")


def build(site: Path, day: date, cfg: dict, rehearse: bool = False) -> dict:
    """The plan for `day` plus `texts` ({edition key: plain text}, not part of plan.json). Raises PlanError for
    the cases that must fail the run."""
    s = sender_settings(cfg)
    tz = cfg["site_timezone"]
    plan = {"schema": PLAN_SCHEMA, "date": day.isoformat(), "note_sha256": "", "timezone": tz, "send": False,
            "reason": "disabled", "send_at": "", "latest_send": "", "editions": []}
    on = enabled(cfg)
    if not on and not rehearse:
        return {"plan": plan, "texts": {}}
    plan["send_at"], plan["latest_send"] = _at(day, s["send_at"], tz), _at(day, s["latest_send"], tz)
    note, raw = read_note(site, day)
    plan["note_sha256"] = hashlib.sha256(raw).hexdigest()
    if note["backfill"]:
        plan["reason"] = "backfill"
        return {"plan": plan, "texts": {}}
    if not note["entries"]:
        plan["reason"] = "quiet"
        return {"plan": plan, "texts": {}}
    by_id = {e["id"]: e for e in note["entries"]}
    rows = one_edition(note)
    key = edition_key(plan["date"], rows)
    ctx = render.context(cfg)
    try:
        subject = render.subject(ctx, plan["date"])
    except ValueError as exc:
        raise PlanError(str(exc)) from None
    entries, under = [by_id[i] for i, _ in rows], dict(rows)
    body = render.body_html(ctx, note, entries, under)
    # render/clean-order: the deliver stage's own body check, here too, so any render/deliver gap fails the plan
    # (the rehearsal's ::warning while the sender is off; a failed run once it is on), never a day lost at 7:00
    if not deliver.body_ok(body, ctx["link_hosts"], ctx["link_urls"]):
        raise PlanError(f"edition {key}: render wrote a body the deliver stage's body check refuses")
    plan["editions"].append({"key": key, "subject": subject, "body": body, "entry_ids": [i for i, _ in rows]})
    texts = {key: render.body_text(ctx, note, entries, under)}
    plan["send"], plan["reason"] = (True, "ok") if on else (False, "disabled")
    built = {"plan": plan, "texts": texts}
    # A size ceiling: a day over backfill.max_entries is a backfill day (never mailed), so the one body holds at
    # most that many entries; a plan over the ceiling means the data is wrong.
    size = size_of(built)
    if size > common.MAX_PLAN_BYTES:
        raise PlanError(f"the plan's files would be {size} bytes, over the MAX_PLAN_BYTES ceiling "
                        f"({common.MAX_PLAN_BYTES}): something is wrong with the data")
    return built


def size_of(built: dict) -> int:
    """The bytes write() puts on disk for `built`: plan.json and every edition's .html and .txt."""
    plan = built["plan"]
    return len(dumps(plan).encode("utf-8")) + sum(
        len(ed["body"].encode("utf-8")) + len(_text_file(ed, built["texts"]).encode("utf-8")) for ed in plan["editions"])


def _text_file(ed: dict, texts: dict) -> str:
    return ed["subject"] + "\n\n" + texts[ed["key"]]


def dumps(plan: dict) -> str:
    return json.dumps(plan, ensure_ascii=False, indent=1) + "\n"


def write(out: Path, built: dict) -> Path:
    """`<out>/<date>/plan.json` and the edition's `edition-<key>.html` / `.txt` (none on a day with no edition).
    Edition files left by an earlier run for the same day are removed first, so the folder always matches its plan."""
    plan = built["plan"]
    folder = Path(out) / plan["date"]
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("edition-*"):
        if old.is_file():
            old.unlink()
    for ed in plan["editions"]:
        (folder / f"edition-{ed['key']}.html").write_text(ed["body"], encoding="utf-8")
        (folder / f"edition-{ed['key']}.txt").write_text(_text_file(ed, built["texts"]), encoding="utf-8")
    (folder / "plan.json").write_text(dumps(plan), encoding="utf-8")
    return folder / "plan.json"


def today(cfg: dict, now: datetime | None = None) -> date:
    """Today in site_timezone: the day the plan is for when --date is left out."""
    zone = ZoneInfo(cfg["site_timezone"])
    return (now.astimezone(zone) if now else datetime.now(zone)).date()
