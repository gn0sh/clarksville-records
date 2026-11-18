"""The deliver stage: guards, the day claim and the delivery of the day's one edition (architecture "T4 sender",
Deliver stage, and "One edition for everyone"; ADR 0004, decisions 3, 4 and 6). Standard library only, and no
`sitegen` import: this is what runs in the job that holds the mail key.

This module never opens a connection. It talks to a `Provider`: the real adapter is `buttondown.py` (the one module
that opens a connection; `python -m sender deliver --live` builds it only when the config enables the sender and the
key is set), and the tests also use an in-memory fake. Without `live=True` and a provider, run() prints what it
would do and calls nothing.

Order of work, each check stopping before the first write:
 0. not live: say what would happen; no provider call.
 1. `morning_note.sender.enabled` is not true (read from the repository, not from the plan): nothing.
 2. `plan.send` is false (a quiet day, a backfill day, a disabled or rehearsal plan): nothing.
 3. `canary_only` with a mode other than `stamp` ("bad-config", exit 2: an `all` email has no filter to narrow);
    the plan's date is not today in the site's zone, or now is past `latest_send` ("missed", exit 3): nothing.
 4. day claim, read from the provider's own emails since yesterday (`metadata.note_date`, `note_sha256`,
    `note_plan`: the note's digest and the plan's, sender/claim-plan-identity): a day claimed by another plan, even
    one from the same note, sends nothing; the same plan creates nothing it has already created; a listing that
    fails sends nothing and fails the run (fail closed).
 5. by `mode`:
    - `all` (the daily mode): no subscriber call at all. One scheduled email with no filter, which the provider
      sends to every confirmed subscriber (invariant one-edition). Nothing a subscriber or the form wrote (tags,
      metadata) is read, so nothing of theirs can change who gets it or what it says.
    - `stamp` (canary trials): confirmed (`type == "regular"`) subscribers only, each reduced at once to Recipient
      (its id); the address, the tags and the metadata stop there. With `canary_only`, only the subscriber ids
      listed in the note job's environment (`MORNING_NOTE_CANARY_IDS`); with no list, nobody and no provider call.
      Never subscriber metadata or tags for that: a subscriber writes both through the public form. Each recipient
      is stamped with the edition's HMAC stamp, then one scheduled email filtered on that stamp is created.
    - `ids`: a draft sent to the recipients' ids (unusable on Buttondown: send-draft only previews).
    The email the provider says it stored must echo the status, claim metadata and filter that were sent (`all`: no
    filter or the empty one; `ids`: none), or it is taken back to a draft and the run fails (audience/provider-echo).

Privacy: nothing here prints a subscriber id, an address, a per-edition count or any text that came back from the
provider. A provider error is reported by the name of the step only. The summary line has totals.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time as time_mod
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import unicodedata
from html import unescape

from .common import (ADDRESS, CREDIT_LINE, DATE_RE, KEY_RE, MARKUP, PLAN_SCHEMA, REASONS, REFS, exact_url_ok,
                     link_ok, subject_line)
from .settings import Settings

NAMESPACE = uuid.UUID("6f1d2c1e-8b0a-5d3e-9c47-2a1b7e5d4c30")     # fixed: the idempotency keys must not change
PUBLISH_MARGIN = timedelta(minutes=5)   # a scheduled email leaves at least this far ahead of the run's clock
MISSED_EXIT = 3            # "missed" (past latest_send): its own non-zero code, so the job fails and opens the issue
TRIES = 3                  # a rate-limited call is tried this many times, then the run stops
MAX_WAIT = 120              # seconds: the longest Retry-After that is obeyed in one wait
MAX_BODY = 500_000
MAX_SUBJECT = 300
STAMP_FIELD = "subscriber.metadata.note_edition"
# the one stored filter an `all` email may come back with: the empty shape a Buttondown email holds when none was
# sent (T4.0 probe, 2026-11-16). Any rule in it would narrow, or widen, who the provider mails.
EMPTY_FILTER = {"filters": [], "groups": [], "predicate": "and"}
# "<day>.<edition key>.<mac>": the mac is HMAC-SHA256(secret, "<day>.<key>")[:16] with the provider's API key as the
# secret, so nobody can compute a stamp from the public note (audience/stamp-self-set-race)
STAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9a-f]{12}\.[0-9a-f]{16}")
_SHA_RE = re.compile(r"[0-9a-f]{64}")
# audience/canary-self-set: the canary list lives in the note job's environment (a `morning-note` environment
# secret), never in the repository and never in subscriber metadata, which subscribers write themselves.
CANARY_ENV = "MORNING_NOTE_CANARY_IDS"
_CANARY_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
# note-job/mask-unicode-ws: the ids are split on exactly the characters the workflow's mask step splits on (its IFS:
# the comma and ASCII whitespace, \x1c to \x1f included), never on Unicode whitespace such as NBSP, which bash does
# not split on. An id holding one then fails _CANARY_ID, so nothing is sent with an id the mask step did not mask.
_CANARY_WS = " \t\n\r\v\f\x1c\x1d\x1e\x1f"
_CANARY_SPLIT = re.compile(f"[,{re.escape(_CANARY_WS)}]+", re.ASCII)
_CANARY_EMPTY = re.compile(f",[{re.escape(_CANARY_WS)}]*,", re.ASCII)


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


# the fields of a morning-send/2 plan, exactly (plan.build writes them; any other is refused)
PLAN_FIELDS = frozenset({"schema", "date", "note_sha256", "timezone", "send", "reason", "send_at", "latest_send",
                         "editions"})


class PlanInvalid(Exception):
    """The plan file is not what the plan stage writes. The text names a field, never its content."""


def canary_ids(text: str | None) -> frozenset | None:
    """The canary subscriber ids from the environment's text (comma or whitespace separated): None when unset.
    A malformed entry is an error, so a typo never widens or silently empties the canary list."""
    if text is None:
        return None
    body = text.strip(_CANARY_WS)
    parts = [p for p in _CANARY_SPLIT.split(body) if p] if body else []
    if body and (_CANARY_EMPTY.search(text) or not all(_CANARY_ID.fullmatch(p) for p in parts)):
        raise PlanInvalid(f"{CANARY_ENV} must be subscriber ids separated by commas")
    return frozenset(parts)


class Provider:
    """What the deliver stage needs from a mail provider. Implementations: the real adapter (buttondown.Buttondown,
    the only module allowed to open a connection) and the tests' in-memory fake. Every method raises ProviderError when the
    call failed or its answer could not be read in full; a listing that is cut short must raise, never return less."""

    def emails(self, since: str) -> list[dict]:
        """Every email created on or after day `since` (YYYY-MM-DD; deliver asks for yesterday, so every email of
        today is in it): [{"id", "status", "metadata": {...}, "archival_mode"}]. A provider that cannot filter
        returns more, never less (sender/claim-listing-unbounded)."""
        raise NotImplementedError

    def subscribers(self) -> list[dict]:
        """Every subscriber as the provider returns it. deliver reduces each to Recipient at once. Never called in
        `all` mode (nor are subscriber() and set_metadata())."""
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
    """All that is kept of a subscriber: the id. The address, the tags and the metadata are not kept (a `stamp`
    write replaces the metadata with the stamp alone, so it never needs them)."""
    id: str

    def __repr__(self) -> str:      # never the id, should one ever reach a traceback
        return "Recipient(...)"


@dataclass(frozen=True)
class Outcome:
    code: int               # the process exit code
    status: str             # dry-run | disabled | no-send | bad-config | wrong-date | missed | claimed | sent | failed | ...
    editions: int = 0       # emails created by this run
    recipients: int = 0     # recipients of those emails, in total (`all` mode: 0, the run does not know them)


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


def _line_ok(line: str, hosts, urls=()) -> bool:
    """One line of the body as render writes it: one of its forms, only its references, every link to one of
    `hosts` or exactly one of `urls`, and no text a mail client could link (common.ADDRESS) once the references
    are read. The footer credit (common.CREDIT_LINE, note/credit-logo) is the one line with an image, accepted
    exactly as render writes it: any other <img>, or that image with another URL, size or alt, is refused."""
    if line == CREDIT_LINE:
        return True
    if not _LINE.fullmatch(line) or "  " in line:
        return False
    if any(int(n) not in REFS for n in re.findall(r"&#([0-9]+);", line)):
        return False
    for href in _HREF_OF.findall(line):     # render writes "&" in a URL as "&amp;" and nothing else as a reference
        url = href.replace("&amp;", "&")
        if re.search(r"&(?!amp;)", href) or not (link_ok(url, hosts) or (url in urls and exact_url_ok(url))):
            return False
    raw = _TAG.sub("", line)
    if any(unicodedata.category(c) in ("Cc", "Cf") or (c.isspace() and c != " ") for c in raw):
        return False
    shown = unescape(_TAG.sub("", line.replace("<br>", "\n")))         # what a reader (and a mail client) sees
    return not ADDRESS.search(shown)


def body_ok(body: str, hosts, urls=()) -> bool:
    """True when `body` could have come from render.body_html with these link hosts: the site name's <h1> first,
    every line one of render's forms, lists closed, and the body ending in a complete line and a newline. Anything
    else (an unclosed tag at the end, an attribute, a comment, a raw bracket, a bare address) is refused."""
    if not (isinstance(body, str) and body.startswith("<h1>") and body.endswith(">\n")):
        return False
    in_list = False
    for line in body[:-1].split("\n"):
        if not _line_ok(line, hosts, urls):
            return False
        if line in ("<ul>", "</ul>"):
            if in_list == (line == "<ul>"):
                return False
            in_list = line == "<ul>"
        elif in_list != line.startswith("<li>"):
            return False
    return not in_list and body.count("<h1>") == 1


def expected_subject(settings: Settings, day: str) -> str | None:
    """The subject every edition of `day` must carry, rebuilt from the repository's config (site_name and
    text.subject) the way render writes it; None when the settings or the day cannot give one."""
    if not (settings.site_name and settings.subject_template):
        return None
    try:
        return subject_line(settings.subject_template, settings.site_name, day)
    except (TypeError, ValueError):
        return None


def check_plan(plan, link_hosts=(), link_urls=(), subject=None) -> dict:
    """The plan as the plan stage writes it, or PlanInvalid. The file crosses from the job that parses untrusted
    documents to the job that holds the key, so every field deliver reads is checked here first, each body
    against the tags render writes and `link_hosts` (from the repository's config, not the plan), and, when
    `subject` is given, each subject against exactly that text (sender/plan-untrusted/subject-unchecked).
    Invariant one-edition: at most one edition, exactly one when `send` is true (a rehearsal plan, send false,
    carries its edition for a person to read), and no field but PLAN_FIELDS (schema /1's per-shape map is refused)."""
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
    if set(plan) != PLAN_FIELDS:
        raise PlanInvalid("the plan's fields")
    editions = plan.get("editions")
    if not isinstance(editions, list):
        raise PlanInvalid("editions")
    if len(editions) > 1 or (plan["send"] and len(editions) != 1):
        raise PlanInvalid("not one edition (send true needs exactly one; never more)")
    for ed in editions:
        if not isinstance(ed, dict) or sorted(ed) != ["body", "entry_ids", "key", "subject"]:
            raise PlanInvalid("an edition's fields")
        if not (isinstance(ed["key"], str) and KEY_RE.fullmatch(ed["key"])):
            raise PlanInvalid("an edition's key")
        if not (isinstance(ed["subject"], str) and 0 < len(ed["subject"]) <= MAX_SUBJECT and ed["subject"].isprintable()
                and ed["subject"] == ed["subject"].strip()):
            raise PlanInvalid("an edition's subject")
        if subject is not None and ed["subject"] != subject:
            raise PlanInvalid("an edition's subject is not the one the config gives")
        if not (isinstance(ed["body"], str) and 0 < len(ed["body"]) <= MAX_BODY
                and body_ok(ed["body"], link_hosts, link_urls)):
            raise PlanInvalid("an edition's body")
        if not (isinstance(ed["entry_ids"], list) and ed["entry_ids"]
                and all(isinstance(i, str) for i in ed["entry_ids"])):
            raise PlanInvalid("an edition's entry_ids")
    if plan["send"] and not (isinstance(plan.get("note_sha256"), str) and _SHA_RE.fullmatch(plan["note_sha256"])):
        raise PlanInvalid("note_sha256")
    return plan


# ------------------------------------------------------------------------------------------------ recipients
def recipient(raw) -> Recipient | None:
    """One subscriber as the provider returned it, reduced to what the sender may know: None unless it is a
    confirmed (`type == "regular"`) subscriber with an id. Everything but the id is dropped here: the tags and the
    metadata are never read for an audience (the public form can write both; only held_stamps reads note_edition)."""
    if not isinstance(raw, dict) or raw.get("type") != "regular":
        return None
    sid = raw.get("id")
    if not isinstance(sid, str) or not sid:
        return None
    return Recipient(id=sid)


# ------------------------------------------------------------------------------------------------ provider calls
def idempotency_key(day: str, key: str, step: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"daylight-note/{day}/{key}/{step}"))


MIN_SECRET = 32         # bytes (security Low (b)): a shorter HMAC key could make a stamp guessable


def secret_ok(secret) -> bool:
    """True for a stamp secret deliver may use: bytes, at least MIN_SECRET of them. Nothing else stands in."""
    return isinstance(secret, bytes) and len(secret) >= MIN_SECRET


def stamp_value(day: str, key: str, secret: bytes) -> str:
    """"<day>.<key>.<mac>". Deterministic for one secret, so a re-run writes and filters the same value."""
    if not secret_ok(secret):
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
    must carry exactly its edition's filter; an `all` email is scheduled and carries no `filters` key at all
    (everyone confirmed is its audience, and no filter is sent that a mistake could get wrong); an `ids` email is a
    draft with no audience of its own."""
    if mode == "stamp":
        f = payload.get("filters")
        rules = f.get("filters") if isinstance(f, dict) else None
        ok = isinstance(rules, list) and len(rules) == 1 and rules[0] == {
            "field": STAMP_FIELD, "operator": "equals", "value": stamp_value(day, key, secret)} \
            and f.get("groups") == [] and f.get("predicate") == "and" and payload.get("status") == "scheduled"
    elif mode == "all":
        ok = payload.get("status") == "scheduled" and "filters" not in payload
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


def _strays(held: list, by_key: dict, expected: dict, done: set) -> list[tuple[str, str]] | None:
    """audience/stamp-self-set: in `stamp` mode the provider mails whoever holds an edition's stamp. A stray holds
    exactly one of today's stamps (`expected`: {stamp: edition key}) and is not in that edition's audience now.
    - its edition is in `done` (an earlier run of this plan created that email, and stamped them while they were in
      its audience; they changed lists since): nothing this run does changes who that email reaches, so it is
      skipped (audience/stamp-rerun-false-stray);
    - its edition has nobody to mail this run: its email is not created, so the stamp reaches nothing;
    - otherwise its email is still to be created. When the stray is in another edition's audience this run that is
      not created yet, it is returned as (id, that edition's key): run() writes that stamp over the stray one before
      any email is created. Else None: the run stops before any write.
    Any other value is ignored: the filter does not match it, and it must not let one subscriber stop every send
    (audience/stamp-self-set-race)."""
    members = {key: {m.id for m in to} for key, to in by_key.items()}
    now_in = {m.id: key for key, to in by_key.items() for m in to}
    out = []
    for sid, value in held:
        if not (isinstance(value, str) and value in expected):
            continue
        key = expected[value]
        if sid in members.get(key, ()) or key in done or key not in by_key:
            continue
        new = now_in.get(sid)
        if new is None or new in done:
            return None
        out.append((sid, new))
    return out


def _check_echo(mode: str, payload: dict, stored) -> str:
    """audience/provider-echo: the email as the provider stored it decides who gets it, so it must carry exactly
    the status, claim metadata and (in `stamp` mode) filter deliver sent; an `all` email no filter, or exactly the
    empty one (EMPTY_FILTER: absent, null or that shape, never a rule); an `ids` draft no filter at all. Its
    archival mode, when it carries one, must be the one sent ("disabled": off the public archive); that the create
    answer carries it at all is unverified (render/archival-not-echoed, platform-facts).
    Returns its id; raises EchoMismatch (with the id when one came back) otherwise."""
    sid = stored.get("id") if isinstance(stored, dict) else stored if isinstance(stored, str) else None
    sid = sid if isinstance(sid, str) and sid else None
    ok = isinstance(stored, dict) and sid is not None and stored.get("status") == payload["status"] \
        and stored.get("metadata") == payload["metadata"] \
        and ("archival_mode" not in stored or stored["archival_mode"] == payload["archival_mode"])
    if ok and mode == "stamp":
        ok = stored.get("filters") == payload["filters"]
    elif ok and mode == "all":
        ok = stored.get("filters") is None or stored["filters"] == EMPTY_FILTER
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


def plan_digest(plan: dict) -> str:
    """sha256 over what decides what the email says: the note's digest and the edition (key, subject, body, entry
    ids). Two plans of one note made by different code or config differ here, so a re-run of
    another plan can never take this plan's created editions as its own (sender/claim-plan-identity)."""
    canon = {"note_sha256": plan["note_sha256"],
             "editions": sorted(([e["key"], e["subject"], e["body"], e["entry_ids"]] for e in plan["editions"]))}
    return hashlib.sha256(json.dumps(canon, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                          .encode("ascii")).hexdigest()


def _claim(emails, plan: dict, digest: str) -> tuple[str, set]:
    """("free" | "ours" | "other", the edition keys this plan has already created) from the provider's emails. An
    email of the day is ours only when it carries this plan's note digest and plan digest (`digest`)."""
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
        if meta.get("note_sha256") != plan["note_sha256"] or meta.get("note_plan") != digest:
            return "other", set()
        state = "ours"
        edition = meta.get("note_edition")
        if isinstance(edition, str) and edition.startswith(plan["date"] + "."):
            done.add(edition[len(plan["date"]) + 1:].split(".")[0])
    return state, done


# ------------------------------------------------------------------------------------------------ run
AUDIENCE = {"all": "every confirmed subscriber (no subscriber is read)",
            "stamp": "the confirmed subscribers it stamps", "ids": "the confirmed subscribers' ids"}


def describe(plan: dict, settings: Settings) -> list[str]:
    """What a live run would do, for the dry run. It names no subscriber: none has been read."""
    emails = len(plan["editions"]) if plan["send"] else 0
    lines = [f"morning note {plan['date']}: dry run, no connection opened, nothing sent",
             f"sender enabled in config: {'yes' if settings.enabled else 'no'}; mode {settings.mode}; "
             f"canary only: {'yes' if settings.canary_only else 'no'}",
             f"plan: send {'true' if plan['send'] else 'false'} ({plan.get('reason', '')}); "
             f"{len(plan['editions'])} edition(s); a live run would create {emails} email(s), "
             f"to {AUDIENCE.get(settings.mode, settings.mode)}"]
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
        day = plan.get("date") if isinstance(plan, dict) else None
        subject = expected_subject(settings, day) if isinstance(day, str) and DATE_RE.fullmatch(day) else None
        if subject is None:
            raise PlanInvalid("date, or the config's site_name and text.subject")
        plan = check_plan(plan, settings.link_hosts, settings.link_urls, subject=subject)
    except PlanInvalid as exc:
        out(f"morning note: the plan file is not valid ({exc}); nothing sent")
        return Outcome(2, "bad-plan")
    day = plan["date"]

    def end(code: int, status: str, editions: int = 0, recipients: int = 0, why: str = "") -> Outcome:
        # `all` mode reads no subscriber, so it cannot count them (the provider's dashboard does)
        who = (("recipients: every confirmed subscriber" if editions else "recipients: none from this run")
               if settings.mode == "all" else f"recipients in total {recipients}")
        out(f"morning note {day}: {status}{' (' + why + ')' if why else ''}; emails created {editions}; {who}")
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
        return end(2, "no-provider", why="no provider adapter was given")
    if settings.canary_only and settings.mode != "stamp":
        return end(2, "bad-config", why="canary_only needs mode stamp: an all-mode email has no filter to narrow")
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
    if settings.mode == "stamp" and not secret_ok(stamp_secret):
        return end(2, "no-secret", why=f"stamp mode needs the stamp secret (the provider key), at least {MIN_SECRET} bytes")
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
        digest = plan_digest(plan)
        state, done = _claim(_call(sleep, provider.emails, (the_day - timedelta(days=1)).isoformat()), plan, digest)
        if state == "other":
            return end(0, "claimed", why="the day belongs to an earlier, different plan")
        send_at, latest = at(settings.send_at), at(settings.latest_send)
        if settings.mode == "all":
            # invariant one-edition: one scheduled email with no filter; no subscriber listing, re-read or write
            ed = plan["editions"][0]
            if ed["key"] in done:
                return end(0, "sent", why="an earlier run of this plan created the email")
            meta = {"note_date": day, "note_edition": f"{day}.{ed['key']}", "note_sha256": plan["note_sha256"],
                    "note_plan": digest}
            publish = max(send_at, clock() + PUBLISH_MARGIN)       # never "now": the echo is checked first
            if publish > latest:
                return end(2, "late", why="the email could not be scheduled a margin ahead before latest_send")
            payload = {"subject": ed["subject"], "body": ed["body"], "archival_mode": "disabled", "metadata": meta,
                       "status": "scheduled",
                       "publish_date": publish.astimezone(zone).isoformat(timespec="seconds")}
            step = "email create"
            _check_audience("all", payload, day, ed["key"], None)
            stored = _call(sleep, provider.create_email, payload, idempotency_key(day, ed["key"], "email"))
            step = "email check"
            checked(payload, stored, ed["key"])
            return end(0, "sent", 1)
        step = "subscriber listing"
        raw = _call(sleep, provider.subscribers)
        if not isinstance(raw, (list, tuple)):
            raise ProviderError("subscriber listing")
        held = held_stamps(raw)          # every row, before the type, dedupe and canary filters
        audience, seen = [], set()
        for r in (recipient(x) for x in raw):
            if r is not None and r.id not in seen:      # a listing that repeats a row (paging overlap): once each
                seen.add(r.id)
                audience.append(r)
        del seen
        del raw
        if settings.canary_only:
            audience = [r for r in audience if r.id in canary_ids]
        if len(audience) > settings.max_recipients:
            return end(2, "over-limit", why="more recipients than max_recipients")
        # The invariant "one stamp, one email a day" (architecture; audience/stamp-rerun-false-stray): whoever holds
        # the stamp of an edition already created today is in no audience this run, so is never re-stamped into
        # another edition; they get the email they hold, or nothing.
        expected = {stamp_value(day, ed["key"], stamp_secret): ed["key"] for ed in plan["editions"]} \
            if settings.mode == "stamp" else {}
        holds_created = {sid for sid, value in held if isinstance(value, str) and expected.get(value) in done}
        # invariant one-edition: every recipient gets the day's one edition (check_plan: exactly one)
        to_all = [r for r in audience if r.id not in holds_created]
        by_key: dict[str, list[Recipient]] = {plan["editions"][0]["key"]: to_all} if to_all else {}

        def stamp(r: Recipient, key: str, value: str) -> bool:
            """Re-read one subscriber just before the write (L2), then stamp them; False (no write) when they are
            gone or no longer confirmed (`type` other than "regular") since the listing: they get nothing today."""
            nonlocal step
            step = "subscriber re-read"
            raw = _call(sleep, provider.subscriber, r.id)
            fresh = recipient(raw)
            if fresh is None or fresh.id != r.id:
                return False
            # sender/stamp-idem-replay: the key carries the stamp held now, so a replay after someone changed it (the
            # form can write metadata) is a new write, not the provider's remembered answer to an old one
            meta_now = raw.get("metadata") if isinstance(raw, dict) else None
            held_now = meta_now.get("note_edition") if isinstance(meta_now, dict) else None
            if isinstance(held_now, str) and expected.get(held_now) in done:
                return False        # took a created edition's stamp since the listing: keep it (the invariant)
            was = hashlib.sha256(repr(held_now).encode("utf-8")).hexdigest()[:16]
            step = "subscriber stamp"
            _call(sleep, provider.set_metadata, r.id, {"note_edition": value},
                  idempotency_key(day, key, f"stamp/{r.id}/{was}"))
            return True

        stamped_early = set()
        if settings.mode == "stamp":
            strays = _strays(held, by_key, expected, done)
            if strays is None:
                return end(2, "stray-stamp", why="a subscriber holds a stamp for today outside that edition's audience, "
                                                 "and no stamp of theirs is written over it; the provider's filter "
                                                 "would mail them")
            who = {m.id: m for to in by_key.values() for m in to}
            for sid, key in strays:     # their stamp of today is written over before any email is created
                if not stamp(who[sid], key, stamp_value(day, key, stamp_secret)):
                    return end(2, "stray-stamp", why="a subscriber holding a stamp for today outside that edition's "
                                                     "audience changed again before it could be written over")
                stamped_early.add(sid)
        del held
        for ed in sorted(plan["editions"], key=lambda e: e["key"]):
            key, to = ed["key"], by_key.get(ed["key"], [])
            if key in done or not to:
                continue        # already created by an earlier run of this plan, or nobody to mail: no email
            edition_id = stamp_value(day, key, stamp_secret) if settings.mode == "stamp" else f"{day}.{key}"
            meta = {"note_date": day, "note_edition": edition_id, "note_sha256": plan["note_sha256"], "note_plan": digest}
            payload = {"subject": ed["subject"], "body": ed["body"], "archival_mode": "disabled", "metadata": meta}
            if settings.mode == "stamp":
                # The T4.0 probe (2026-11-16) showed a metadata PATCH replaces the whole object, and the sender
                # keeps nothing else there, so the write is exactly {"note_edition": <stamp>}: any other key (one the
                # public form wrote, a forged note_edition, an old stamp) is dropped by it (sender/stamp-write-
                # replaces). Each subscriber is read again just before the write (L2): someone whose type changed
                # since the listing is not stamped and gets nothing today.
                stamped = [r for r in to if r.id in stamped_early or stamp(r, key, meta["note_edition"])]
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
                # sender/ids-no-invariant: this branch relies on two provider facts: a draft has no audience of its
                # own (stored with no filter), and send_draft delivers it to exactly the listed subscriber ids. On
                # Buttondown neither holds (T4.0 probe 2026-11-16, docs/platform-facts.md: send-draft mails only a
                # "[PREVIEW]" to the account owner and the draft stays a draft; a draft comes back with an empty
                # filters object). So `mode: ids` is not usable with Buttondown: config/site.yml keeps `stamp`, and
                # ids may be switched on only for a provider whose probe shows both facts.
                # Never twice before never missed: a run that dies between the draft and its send leaves the
                # edition claimed (the draft carries the metadata), so a re-run does not send it again. That
                # edition is then not mailed today; its records are on the site and the feeds.
                # sender/never-late/ids-no-recheck: `ids` sends at once, so the clock is read again before each
                # write; past latest_send the rest of the day is not sent (a draft already made stays a draft).
                if clock() > latest:
                    return end(2, "late", sent, people, why="past latest_send before this edition's draft; it and "
                                                            "the rest are not sent")
                payload.update(status="draft")
                step = "email create"
                _check_audience("ids", payload, day, key, None)
                stored = _call(sleep, provider.create_email, payload, idempotency_key(day, key, "email"))
                step = "email check"
                email_id = checked(payload, stored, key)
                if clock() > latest:
                    return end(2, "late", sent, people, why="past latest_send before this edition's send; its draft "
                                                            "is not sent, nor the rest")
                step = "draft send"
                _call(sleep, provider.send_draft, email_id, [r.id for r in to], idempotency_key(day, key, "send"))
            sent += 1
            people += len(to)
    except PlanInvalid:
        return end(2, "bad-plan", sent, people, why="an edition's stamp")
    except Exception:       # noqa: BLE001  a provider's error text may carry personal data: only the step is named
        return end(1, "failed", sent, people, why=f"the provider call failed at: {step}")
    return end(0, "sent", sent, people)
