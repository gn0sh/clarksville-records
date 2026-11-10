"""The deliver stage: guards, the day claim and the per-edition delivery (architecture "T4 sender", Deliver stage;
ADR 0004, decisions 2 to 4). Standard library only, and no `sitegen` import: this is what runs in the job that
holds the mail key.

This module never opens a connection. It talks to a `Provider`, and this package ships none: the real adapter
(buttondown.py) is a later task, and the tests use an in-memory fake. Without `live=True` and a provider, run()
prints what it would do and calls nothing.

Order of work, each check stopping before the first write:
 0. not live: say what would happen; no provider call.
 1. `morning_note.sender.enabled` is not true (read from the repository, not from the plan): nothing.
 2. `plan.send` is false (a quiet day, a backfill day, a disabled or rehearsal plan): nothing.
 3. the plan's date is not today in the site's zone, or now is past `latest_send` ("missed", exit 3): nothing.
 4. day claim, read from the provider's own emails (`metadata.note_date`, `note_sha256`): a day claimed by another
    plan sends nothing; the same plan continues with the editions not yet created; a listing that fails sends
    nothing and fails the run (fail closed).
 5. recipients: confirmed (`type == "regular"`) subscribers only, each reduced at once to Recipient; the address
    and every other field stop there. With `canary_only`, only the subscriber ids listed in the note job's
    environment (`MORNING_NOTE_CANARY_IDS`); with no list, nobody and no provider call. Never subscriber metadata:
    a subscriber writes their own through the public form.
 6. per edition, in key order, by `mode` (`stamp` or `ids`). The email the provider says it stored must echo the
    status, claim metadata and filter that were sent (`ids`: no filter), or it is taken back to a draft and the run
    fails before anything else is sent (audience/provider-echo).

Privacy: nothing here prints a subscriber id, an address, a signature, a per-edition count or any text that came
back from the provider. A provider error is reported by the name of the step only. The summary line has totals.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time as time_mod
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import unicodedata
from html import unescape

from .common import (ADDRESS, DATE_RE, KEY_RE, LIST_KEYS, MARKUP, PLAN_SCHEMA, REASONS, REFS, SIGNATURE_RE,
                     link_ok, signature)
from .settings import Settings

NAMESPACE = uuid.UUID("6f1d2c1e-8b0a-5d3e-9c47-2a1b7e5d4c30")     # fixed: the idempotency keys must not change
PUBLISH_MARGIN = timedelta(minutes=5)   # a stamp email is scheduled at least this far ahead of the run's clock
MISSED_EXIT = 3            # "missed" (past latest_send): its own non-zero code, so the job fails and opens the issue
TRIES = 3                  # a rate-limited call is tried this many times, then the run stops
MAX_WAIT = 120              # seconds: the longest Retry-After that is obeyed in one wait
MAX_LIST_VALUES = 16        # a subscriber's `lists` with more values than this is not a picker's output: ignored
MAX_BODY = 500_000
MAX_SUBJECT = 300
STAMP_FIELD = "subscriber.metadata.note_edition"
# "<day>.<edition key>.<mac>": the mac is HMAC-SHA256(secret, "<day>.<key>")[:16] with the provider's API key as the
# secret, so nobody can compute a stamp from the public note (audience/stamp-self-set-race)
STAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9a-f]{12}\.[0-9a-f]{16}")
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_NUMBER = re.compile(r"[1-9][0-9]{0,3}")
# audience/canary-self-set: the canary list lives in the note job's environment (a `morning-note` environment
# secret), never in the repository and never in subscriber metadata, which subscribers write themselves.
CANARY_ENV = "MORNING_NOTE_CANARY_IDS"
_CANARY_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class ProviderError(Exception):
    """A provider call failed. Its text is never printed: it may carry what the provider answered."""


class RateLimited(ProviderError):
    """HTTP 429. `retry_after`: the seconds the provider asked for."""

    def __init__(self, retry_after: float = 1.0):
        super().__init__("rate limited")
        self.retry_after = retry_after


class EchoMismatch(ProviderError):
    """The provider stored an email other than the one deliver sent. `email_id`: its id, when one came back."""

    def __init__(self, email_id: str | None):
        super().__init__("email check")
        self.email_id = email_id


class PlanInvalid(Exception):
    """The plan file is not what the plan stage writes. The text names a field, never its content."""


def canary_ids(text: str | None) -> frozenset | None:
    """The canary subscriber ids from the environment's text (comma or whitespace separated): None when unset.
    A malformed entry is an error, so a typo never widens or silently empties the canary list."""
    if text is None:
        return None
    parts = [p for p in re.split(r"[\s,]+", text.strip()) if p] if text.strip() else []
    if text.strip() and (re.search(r",\s*,", text) or not all(_CANARY_ID.fullmatch(p) for p in parts)):
        raise PlanInvalid(f"{CANARY_ENV} must be subscriber ids separated by commas")
    return frozenset(parts)


class Provider:
    """What the deliver stage needs from a mail provider. Implementations: the real adapter (a later task, the only
    module allowed to open a connection) and the tests' in-memory fake. Every method raises ProviderError when the
    call failed or its answer could not be read in full; a listing that is cut short must raise, never return less."""

    def emails(self) -> list[dict]:
        """Every recent email: [{"id", "status", "metadata": {...}}]."""
        raise NotImplementedError

    def subscribers(self) -> list[dict]:
        """Every subscriber as the provider returns it. deliver reduces each to Recipient at once."""
        raise NotImplementedError

    def subscriber(self, subscriber_id: str) -> dict | None:
        """One subscriber as the provider holds it now (None when there is no such subscriber)."""
        raise NotImplementedError

    def set_metadata(self, subscriber_id: str, metadata: dict, idempotency_key: str) -> None:
        """Replace one subscriber's metadata with `metadata` (the whole object). Nothing else may change."""
        raise NotImplementedError

    def create_email(self, payload: dict, idempotency_key: str) -> dict:
        """Create one email; returns it as the provider stored it: {"id", "status", "metadata", "filters" (when it
        has one)}, read back from the provider's answer, never copied from `payload`."""
        raise NotImplementedError

    def unschedule(self, email_id: str, idempotency_key: str) -> dict:
        """Take one email back to a draft (it then goes to nobody). Used when its stored form is not what was sent.
        Returns the email as the provider now stores it ({"id", "status", ...}); deliver checks it is a draft."""
        raise NotImplementedError

    def send_draft(self, email_id: str, subscriber_ids: list[str], idempotency_key: str) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class Recipient:
    """All that is kept of a subscriber. `metadata` is the provider's own object, kept only so `stamp` mode can
    write it back whole; the address is not in it and is never read."""
    id: str
    lists: tuple
    district: int | None
    ward: int | None
    metadata: dict

    def __repr__(self) -> str:      # never the id or the metadata, should one ever reach a traceback
        return "Recipient(...)"


@dataclass(frozen=True)
class Outcome:
    code: int               # the process exit code
    status: str             # dry-run | disabled | no-send | wrong-date | missed | claimed | sent | failed | ...
    editions: int = 0       # emails created by this run
    recipients: int = 0     # recipients of those emails, in total


# ------------------------------------------------------------------------------------------------ the plan file
# plan-untrusted/body-unchecked (M3): the body is held to the exact lines render.body_html writes, not parsed as
# HTML. Text is any character but a markup one, a newline and "&", which stands only in a reference render writes.
_CHAR = "[^" + re.escape(MARKUP) + "\\n]"
_REF = "&(?:#[0-9]{1,7}|middot);"
_TEXT = f"(?:{_CHAR}|{_REF})*"
_LINK = f'<a href="[^"<>\\s]*">{_TEXT}</a>'
_INLINE = f"(?:{_CHAR}|{_REF}|<br>|<strong>{_TEXT}</strong>|{_LINK})*"
_LINE = re.compile(f"<h1>{_TEXT}</h1>|<h2>{_TEXT}</h2>|<p>{_INLINE}</p>|<ul>|</ul>|<li>{_INLINE}</li>")
_TAG = re.compile(r"<[^<>]*>")
_HREF_OF = re.compile(r'<a href="([^"]*)">')


def _line_ok(line: str, hosts) -> bool:
    """One line of the body as render writes it: one of its forms, only its references, every link to one of
    `hosts`, and no text a mail client could link (common.ADDRESS) once the references are read."""
    if not _LINE.fullmatch(line) or "  " in line:
        return False
    if any(int(n) not in REFS for n in re.findall(r"&#([0-9]+);", line)):
        return False
    for href in _HREF_OF.findall(line):     # render writes "&" in a URL as "&amp;" and nothing else as a reference
        if re.search(r"&(?!amp;)", href) or not link_ok(href.replace("&amp;", "&"), hosts):
            return False
    raw = _TAG.sub("", line)
    if any(unicodedata.category(c) in ("Cc", "Cf") or (c.isspace() and c != " ") for c in raw):
        return False
    shown = unescape(_TAG.sub("", line.replace("<br>", "\n")))         # what a reader (and a mail client) sees
    return not ADDRESS.search(shown)


def body_ok(body: str, hosts) -> bool:
    """True when `body` could have come from render.body_html with these link hosts: the site name's <h1> first,
    every line one of render's forms, lists closed, and the body ending in a complete line and a newline. Anything
    else (an unclosed tag at the end, an attribute, a comment, a raw bracket, a bare address) is refused."""
    if not (isinstance(body, str) and body.startswith("<h1>") and body.endswith(">\n")):
        return False
    in_list = False
    for line in body[:-1].split("\n"):
        if not _line_ok(line, hosts):
            return False
        if line in ("<ul>", "</ul>"):
            if in_list == (line == "<ul>"):
                return False
            in_list = line == "<ul>"
        elif in_list != line.startswith("<li>"):
            return False
    return not in_list and body.count("<h1>") == 1


def check_plan(plan, link_hosts=()) -> dict:
    """The plan as the plan stage writes it, or PlanInvalid. The file crosses from the job that parses untrusted
    documents to the job that holds the key, so every field deliver reads is checked here first, each body
    against the tags render writes and `link_hosts` (from the repository's config, not the plan)."""
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise PlanInvalid("schema")
    if not (isinstance(plan.get("date"), str) and DATE_RE.fullmatch(plan["date"])):
        raise PlanInvalid("date")
    if not isinstance(plan.get("send"), bool) or not isinstance(plan.get("timezone"), str):
        raise PlanInvalid("send or timezone")
    # plan-untrusted/log-injection: the dry run prints the reason and each subject into a public Actions log, so
    # the reason is one of four words and a subject one printable line (no Cc, Cf, Zl, Zp: no newline, NEL,
    # U+2028, escape or bidi control that could start a log line such as "::error ...")
    if plan.get("reason") not in REASONS or (plan["reason"] == "ok") != plan["send"]:
        raise PlanInvalid("reason")
    editions, sigs = plan.get("editions"), plan.get("signatures")
    if not isinstance(editions, list) or not isinstance(sigs, dict):
        raise PlanInvalid("editions or signatures")
    keys = []
    for ed in editions:
        if not isinstance(ed, dict) or sorted(ed) != ["body", "entry_ids", "key", "subject"]:
            raise PlanInvalid("an edition's fields")
        if not (isinstance(ed["key"], str) and KEY_RE.fullmatch(ed["key"])):
            raise PlanInvalid("an edition's key")
        if not (isinstance(ed["subject"], str) and 0 < len(ed["subject"]) <= MAX_SUBJECT and ed["subject"].isprintable()
                and ed["subject"] == ed["subject"].strip()):
            raise PlanInvalid("an edition's subject")
        if not (isinstance(ed["body"], str) and 0 < len(ed["body"]) <= MAX_BODY and body_ok(ed["body"], link_hosts)):
            raise PlanInvalid("an edition's body")
        if not (isinstance(ed["entry_ids"], list) and ed["entry_ids"]
                and all(isinstance(i, str) for i in ed["entry_ids"])):
            raise PlanInvalid("an edition's entry_ids")
        keys.append(ed["key"])
    if len(set(keys)) != len(keys):
        raise PlanInvalid("an edition key is used twice")
    for sig, key in sigs.items():
        if not SIGNATURE_RE.fullmatch(sig) or key not in keys:
            raise PlanInvalid("a signature")
    if plan["send"]:
        if not (isinstance(plan.get("note_sha256"), str) and _SHA_RE.fullmatch(plan["note_sha256"])):
            raise PlanInvalid("note_sha256")
        if not editions or not sigs:
            raise PlanInvalid("send is true with no edition")
    return plan


# ------------------------------------------------------------------------------------------------ recipients
def _number(value, most: int) -> int | None:
    """A district or ward as a subscriber's metadata may hold it: a whole number from 1 to `most`, as a number or
    as its plain digits. Anything else (the public form takes any text) is treated as not set."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= most else None
    if isinstance(value, str) and _NUMBER.fullmatch(value) and 1 <= int(value) <= most:
        return int(value)
    return None


def _lists(value) -> tuple:
    if isinstance(value, str):
        value = value.split(",") if len(value) <= 200 else []
    if not isinstance(value, (list, tuple)) or len(value) > MAX_LIST_VALUES:
        return ()
    got = {v.strip() for v in value if isinstance(v, str)}
    return tuple(k for k in LIST_KEYS if k in got)


def recipient(raw, settings: Settings) -> Recipient | None:
    """One subscriber as the provider returned it, reduced to what the sender may know: None unless it is a
    confirmed (`type == "regular"`) subscriber with an id. The address and every field but the id and metadata are
    dropped here. Unknown list keys and out-of-range seats are ignored, never passed on."""
    if not isinstance(raw, dict) or raw.get("type") != "regular":
        return None
    sid = raw.get("id")
    if not isinstance(sid, str) or not sid:
        return None
    meta = raw.get("metadata")
    meta = dict(meta) if isinstance(meta, dict) else {}
    return Recipient(id=sid, lists=_lists(meta.get("lists")),
                     district=_number(meta.get("district"), settings.district_count),
                     ward=_number(meta.get("ward"), settings.ward_count), metadata=meta)


# ------------------------------------------------------------------------------------------------ provider calls
def idempotency_key(day: str, key: str, step: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"daylight-note/{day}/{key}/{step}"))


def stamp_value(day: str, key: str, secret: bytes) -> str:
    """"<day>.<key>.<mac>". Deterministic for one secret, so a re-run writes and filters the same value."""
    if not isinstance(secret, bytes) or not secret:
        raise PlanInvalid("the stamp secret")
    base = f"{day}.{key}"
    value = f"{base}.{hmac.new(secret, base.encode('utf-8'), hashlib.sha256).hexdigest()[:16]}"
    if not STAMP_RE.fullmatch(value):
        raise PlanInvalid("an edition's stamp")
    return value


def stamp_filter(day: str, key: str, secret: bytes) -> dict:
    """The one audience of a `stamp` email: subscribers whose `note_edition` is exactly its stamp. The value carries
    the day, so a stamp from an earlier day can never match, and the mac, so nobody can set it on themselves."""
    return {"filters": [{"field": STAMP_FIELD, "operator": "equals", "value": stamp_value(day, key, secret)}],
            "groups": [], "predicate": "and"}


def _check_audience(mode: str, payload: dict, day: str, key: str, secret: bytes | None) -> None:
    """The last check before an email is created. An empty or malformed filter means everyone, so a `stamp` email
    must carry exactly its edition's filter; an `ids` email is a draft with no audience of its own."""
    if mode == "stamp":
        f = payload.get("filters")
        rules = f.get("filters") if isinstance(f, dict) else None
        ok = isinstance(rules, list) and len(rules) == 1 and rules[0] == {
            "field": STAMP_FIELD, "operator": "equals", "value": stamp_value(day, key, secret)} \
            and f.get("groups") == [] and f.get("predicate") == "and" and payload.get("status") == "scheduled"
    else:
        ok = payload.get("status") == "draft" and "filters" not in payload
    if not ok:
        raise ProviderError("audience check")


def held_stamps(rows) -> list[tuple[str, object]]:
    """(id, metadata.note_edition) for every row of a subscriber listing, whatever its `type` (L3: the provider's
    filter may also reach paying, gifted or trial subscribers, who are never recipients here)."""
    out = []
    for raw in rows:
        meta = raw.get("metadata") if isinstance(raw, dict) else None
        if isinstance(meta, dict) and "note_edition" in meta:
            out.append((raw.get("id"), meta["note_edition"]))
    return out


def _stray_stamp(held: list, by_key: dict, expected: dict) -> bool:
    """audience/stamp-self-set: in `stamp` mode the provider mails whoever holds an edition's stamp. True when any
    subscriber holds exactly one of today's stamps (`expected`: {stamp: edition key}) and is not in that edition's
    audience; a stamp written by an earlier run of this plan always is. Any other value is ignored: the filter does
    not match it, and it must not let one subscriber stop every send (audience/stamp-self-set-race)."""
    members = {key: {m.id for m in to} for key, to in by_key.items()}
    for sid, value in held:
        if isinstance(value, str) and value in expected and sid not in members.get(expected[value], ()):
            return True
    return False


def _check_echo(mode: str, payload: dict, stored) -> str:
    """audience/provider-echo: the email as the provider stored it decides who gets it, so it must carry exactly
    the status, claim metadata and (in `stamp` mode) filter deliver sent, and an `ids` draft no filter at all.
    Returns its id; raises EchoMismatch (with the id when one came back) otherwise."""
    sid = stored.get("id") if isinstance(stored, dict) else stored if isinstance(stored, str) else None
    sid = sid if isinstance(sid, str) and sid else None
    ok = isinstance(stored, dict) and sid is not None and stored.get("status") == payload["status"] \
        and stored.get("metadata") == payload["metadata"]
    if ok and mode == "stamp":
        ok = stored.get("filters") == payload["filters"]
    elif ok:
        ok = stored.get("filters") is None          # a draft for send-draft carries no audience of its own
    if not ok:
        raise EchoMismatch(sid)
    return sid


def _call(sleep, fn, *args):
    """One provider call, obeying Retry-After on a rate limit: TRIES tries, then the run stops."""
    for attempt in range(1, TRIES + 1):
        try:
            return fn(*args)
        except RateLimited as exc:
            if attempt == TRIES:
                raise ProviderError("rate limited") from None
            wait = exc.retry_after if isinstance(exc.retry_after, (int, float)) else 1
            sleep(min(max(float(wait), 0.0), MAX_WAIT))


def _claim(emails, plan: dict) -> tuple[str, set]:
    """("free" | "ours" | "other", the edition keys this plan has already created) from the provider's emails."""
    if not isinstance(emails, list):
        raise ProviderError("email listing")
    done, state = set(), "free"
    for em in emails:
        if not isinstance(em, dict) or "metadata" not in em:
            raise ProviderError("email listing")     # a row without metadata cannot say whether it claims the day
        meta = em["metadata"]
        if meta is None or meta == {}:
            continue
        if not isinstance(meta, dict):
            raise ProviderError("email listing")
        if meta.get("note_date") != plan["date"]:
            continue
        if meta.get("note_sha256") != plan["note_sha256"]:
            return "other", set()
        state = "ours"
        edition = meta.get("note_edition")
        if isinstance(edition, str) and edition.startswith(plan["date"] + "."):
            done.add(edition[len(plan["date"]) + 1:].split(".")[0])
    return state, done


# ------------------------------------------------------------------------------------------------ run
def describe(plan: dict, settings: Settings) -> list[str]:
    """What a live run would do, for the dry run. It names no subscriber: none has been read."""
    lines = [f"morning note {plan['date']}: dry run, no connection opened, nothing sent",
             f"sender enabled in config: {'yes' if settings.enabled else 'no'}; mode {settings.mode}; "
             f"canary only: {'yes' if settings.canary_only else 'no'}",
             f"plan: send {'true' if plan['send'] else 'false'} ({plan.get('reason', '')}); "
             f"{len(plan['editions'])} edition(s); {len(plan['signatures'])} subscriber shape(s) would get one"]
    lines += [f"edition {ed['key']}: {len(ed['entry_ids'])} entr{'y' if len(ed['entry_ids']) == 1 else 'ies'}; "
              f"subject: {ed['subject']}" for ed in plan["editions"]]
    return lines


def run(plan, settings: Settings, provider: Provider | None = None, live: bool = False,
        now: datetime | None = None, sleep=time_mod.sleep, out=print, canary_ids: frozenset | None = None,
        stamp_secret: bytes | None = None, clock=None) -> Outcome:
    """Deliver one plan. Returns the outcome; prints the dry run's description or one summary line of totals.
    `stamp_secret`: the HMAC key of the stamps (the provider's API key, passed by the adapter), needed in `stamp`
    mode. `clock`: a callable giving the current time (default: `now` when given, else the system clock)."""
    try:
        plan = check_plan(plan, settings.link_hosts)
    except PlanInvalid as exc:
        out(f"morning note: the plan file is not valid ({exc}); nothing sent")
        return Outcome(2, "bad-plan")
    day = plan["date"]

    def end(code: int, status: str, editions: int = 0, recipients: int = 0, why: str = "") -> Outcome:
        out(f"morning note {day}: {status}{' (' + why + ')' if why else ''}; "
            f"emails created {editions}; recipients in total {recipients}")
        return Outcome(code, status, editions, recipients)

    if not live:
        for line in describe(plan, settings):
            out(line)
        return Outcome(0, "dry-run")
    if not settings.enabled:
        return end(0, "disabled", why="morning_note.sender.enabled is false")
    if not plan["send"]:
        return end(0, "no-send", why="the plan says send false")
    if provider is None:
        return end(2, "no-provider", why="this build has no provider adapter")
    if plan["timezone"] != settings.timezone:
        return end(2, "bad-plan", why="the plan's time zone is not the site's")
    try:
        zone = ZoneInfo(settings.timezone)
    except (ZoneInfoNotFoundError, ValueError):     # an unknown name, or one that is not a plain zone key
        return end(2, "failed", why="site_timezone is not a known time zone")
    if clock is None:
        clock = (lambda: now) if now is not None else (lambda: datetime.now(timezone.utc))
    now = clock()
    if now.tzinfo is None:
        return end(2, "failed", why="the clock has no time zone")
    local = now.astimezone(zone)
    if local.date().isoformat() != day:
        return end(0, "wrong-date", why="the plan is not for today")
    the_day = local.date()

    def at(hhmm: str) -> datetime:
        return datetime.combine(the_day, time(int(hhmm[:2]), int(hhmm[3:])), zone)

    if now > at(settings.latest_send):
        return end(MISSED_EXIT, "missed", why="now is past latest_send; a note is never sent late")
    if settings.canary_only and not canary_ids:
        return end(0, "no-canary", why=f"canary_only is true and {CANARY_ENV} names nobody")
    if settings.mode == "stamp" and not (isinstance(stamp_secret, bytes) and stamp_secret):
        return end(2, "no-secret", why="stamp mode needs the stamp secret (the provider key)")
    sent = people = 0
    step = "email listing"

    def checked(payload: dict, stored, key: str) -> str:
        """The stored email's id once its echo matches; otherwise it is taken back to a draft (when an id came
        back) and the run fails at "email check" before the next edition. A failed take-back is named as such:
        that email may still be scheduled, so a person must look at it."""
        nonlocal step
        try:
            return _check_echo(settings.mode, payload, stored)
        except EchoMismatch as exc:
            stuck = "email check failed and an email may still be scheduled"
            if exc.email_id is None:
                step = f"{stuck}: no email id came back, so it could not be taken back"
                raise
            step = f"{stuck}: taking it back to a draft failed"
            back = _call(sleep, provider.unschedule, exc.email_id, idempotency_key(day, key, "unschedule"))
            if not (isinstance(back, dict) and back.get("id") == exc.email_id and back.get("status") == "draft"):
                step = f"{stuck}: the provider did not confirm it is a draft"
                raise
            step = "email check (the email was taken back to a draft)"
            raise

    try:
        state, done = _claim(_call(sleep, provider.emails), plan)
        if state == "other":
            return end(0, "claimed", why="the day belongs to an earlier, different plan")
        step = "subscriber listing"
        raw = _call(sleep, provider.subscribers)
        if not isinstance(raw, (list, tuple)):
            raise ProviderError("subscriber listing")
        held = held_stamps(raw)          # every row, before the type, dedupe and canary filters
        audience, seen = [], set()
        for r in (recipient(x, settings) for x in raw):
            if r is not None and r.id not in seen:      # a listing that repeats a row (paging overlap): once each
                seen.add(r.id)
                audience.append(r)
        del seen
        del raw
        if settings.canary_only:
            audience = [r for r in audience if r.id in canary_ids]
        if len(audience) > settings.max_recipients:
            return end(2, "over-limit", why="more recipients than max_recipients")
        by_key: dict[str, list[Recipient]] = {}
        for r in audience:
            key = plan["signatures"].get(signature(r.lists, r.district, r.ward)) if r.lists else None
            if key is not None:
                by_key.setdefault(key, []).append(r)
        # max_editions bounds the emails a run creates: the editions that have a recipient (the plan holds every
        # edition any shape could get), counted before the first write
        if len(by_key) > settings.max_editions:
            return end(2, "over-limit", why="more editions with a recipient than max_editions")
        expected = {stamp_value(day, ed["key"], stamp_secret): ed["key"] for ed in plan["editions"]} \
            if settings.mode == "stamp" else {}
        if settings.mode == "stamp" and _stray_stamp(held, by_key, expected):
            return end(2, "stray-stamp", why="a subscriber holds a stamp for today outside that edition's audience; "
                                             "the provider's filter would mail them")
        del held
        send_at, latest = at(settings.send_at), at(settings.latest_send)
        for ed in sorted(plan["editions"], key=lambda e: e["key"]):
            key, to = ed["key"], by_key.get(ed["key"], [])
            if key in done or not to:
                continue        # already created by an earlier run of this plan, or nobody to mail: no email
            edition_id = stamp_value(day, key, stamp_secret) if settings.mode == "stamp" else f"{day}.{key}"
            meta = {"note_date": day, "note_edition": edition_id, "note_sha256": plan["note_sha256"]}
            payload = {"subject": ed["subject"], "body": ed["body"], "archival_mode": "disabled", "metadata": meta}
            if settings.mode == "stamp":
                # L2: the write replaces the whole metadata object (until the T4.0 probe shows the provider merges
                # it, then only note_edition is sent), so it is built from a fresh read of that one subscriber just
                # before the write: a change made since the listing survives. Someone whose type or shape changed
                # since is not stamped and gets nothing today.
                stamped = []
                for r in to:
                    step = "subscriber re-read"
                    fresh = recipient(_call(sleep, provider.subscriber, r.id), settings)
                    if fresh is None or fresh.id != r.id or not fresh.lists or \
                            signature(fresh.lists, fresh.district, fresh.ward) != signature(r.lists, r.district, r.ward):
                        continue
                    step = "subscriber stamp"
                    _call(sleep, provider.set_metadata, r.id, {**fresh.metadata, "note_edition": meta["note_edition"]},
                          idempotency_key(day, key, f"stamp/{r.id}"))
                    stamped.append(r)
                if not stamped:
                    continue
                to = stamped
                # never "now": the stored email is checked (and taken back if wrong) before it can leave. Worked
                # out from the clock per edition, after the stamps, which can take minutes (L1).
                publish = max(send_at, clock() + PUBLISH_MARGIN)
                if publish > latest:
                    return end(2, "late", sent, people, why="this edition could not be scheduled a margin ahead "
                                                            "before latest_send; it and the rest are not sent")
                payload.update(status="scheduled", publish_date=publish.astimezone(zone).isoformat(timespec="seconds"),
                               filters=stamp_filter(day, key, stamp_secret))
                step = "email create"
                _check_audience("stamp", payload, day, key, stamp_secret)
                stored = _call(sleep, provider.create_email, payload, idempotency_key(day, key, "email"))
                step = "email check"
                checked(payload, stored, key)
            else:
                # Never twice before never missed: a run that dies between the draft and its send leaves the
                # edition claimed (the draft carries the metadata), so a re-run does not send it again. That
                # edition is then not mailed today; its records are on the site and the feeds.
                payload.update(status="draft")
                step = "email create"
                _check_audience("ids", payload, day, key, None)
                stored = _call(sleep, provider.create_email, payload, idempotency_key(day, key, "email"))
                step = "email check"
                email_id = checked(payload, stored, key)
                step = "draft send"
                _call(sleep, provider.send_draft, email_id, [r.id for r in to], idempotency_key(day, key, "send"))
            sent += 1
            people += len(to)
    except PlanInvalid:
        return end(2, "bad-plan", sent, people, why="an edition's stamp")
    except Exception:       # noqa: BLE001  a provider's error text may carry personal data: only the step is named
        return end(1, "failed", sent, people, why=f"the provider call failed at: {step}")
    return end(0, "sent", sent, people)
