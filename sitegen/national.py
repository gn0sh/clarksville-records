"""Daylight Digest, the national address lookup (docs/architecture/daylight-national.md; ADR 0013): the build side.

M1 task B1: the three curated files under config/national/ and their loaders, which refuse to build on any entry that
breaks a rule of architecture 3.2 and 3.3 (raising NationalConfigError naming the file, the entry and the key), and
`page_directory`, the pure function that makes the page directory the browser's lookup reads (3.4), embedded with
`embed_json` (the same escaping as Jinja's |tojson; finding 9). Task B2: MAX_ANSWER and the Census facts in
docs/platform-facts.md "Census TIGER/Line codes".

Not wired into sitegen.build yet (B4 does that behind `national.enabled`), so nothing here changes a Clarksville page.

Invariant `privacy-withhold/national-prefix` (architecture section 11): item text is published only for a government
whose entry says `items: shown` and whose whole entry is the readable row in SHOWN_REVIEWED (section 11 v3). A
missing `items` is `withheld`; `shown` is refused unless the entry's `norm_entry` equals its row's `entry` and the
fail-closed guard (`shown_refusal`) passes. The loaded entry carries `review` (the digest when shown, else None);
consumers decide with `national_guards.is_shown(entry)` and write through `national_guards.bind_feed`, never an id
prefix.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import zoneinfo
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Mapping, NamedTuple

import yaml
from jinja2.utils import htmlsafe_json_dumps

from . import config
from .national_guards import BAD_TEXT_RE, GEOID_DIGITS, allowed_url, id_layer

NATIONAL_DIR = config.CONFIG_DIR / "national"
DIRECTORY_PATH = NATIONAL_DIR / "directory.yml"
FLAGS_PATH = NATIONAL_DIR / "gov-flags.yml"
LABELS_PATH = NATIONAL_DIR / "labels.yml"

DIRECTORY_SCHEMA = "daylight-directory/1"
FLAGS_SCHEMA = "daylight-govflags/1"
LABELS_SCHEMA = "daylight-labels/1"
PAGEDIR_SCHEMA = "daylight-pagedir/1"

# Ids (3.1): `<layer>-<GEOID>`. GEOID_DIGITS, ID_RE, id_layer and allowed_url live in sitegen/national_guards.py,
# shared with the collector (task B14), and are imported above.
LAYERS = tuple(GEOID_DIGITS)       # the six Census layers (3.1); card order is national.js ORDER (4.1, step 7)
SCHOOL_LAYERS = ("sdu", "sds", "sde")

# USPS code -> state FIPS code (the GEOID's first two digits): the 50 states, DC and the territories the Census
# geocoder covers. `state` must be one of these and must match the id's GEOID.
USPS_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10", "DC": "11",
    "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30",
    "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49",
    "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55", "WY": "56",
    "AS": "60", "GU": "66", "MP": "69", "PR": "72", "VI": "78",
}
FIPS_STATES = frozenset(USPS_FIPS.values())

STATUSES = ("covered", "cant-cover")
REASONS = ("blocks-readers", "robots-disallow", "scanned-only", "not-posted", "token-required", "api-not-enabled",
           "terms")
ITEMS = ("shown", "withheld")
ITEMS_DEFAULT = "withheld"

# Platform keys (3.2). `daylight` is this site's own data, so it needs no host OK; every other platform needs
# `host_ok` (finding 7) and its URLs on the platform's hosts (finding 4). boarddocs, escribe and civicclerk join here,
# each with its key checks, when a task adds them; until then they are unknown platforms and refused.
PLATFORM_KEYS = {"daylight": {"body", "full_url"}, "legistar": {"client", "body_id", "tz", "final_statuses"}}
PLATFORM_REQUIRED = {"daylight": {"body", "full_url"}, "legistar": {"client", "body_id", "tz"}}
# Legistar EventAgendaStatusName values that mean a final agenda (`final_statuses` must be a list drawn from these).
LEGISTAR_FINAL_STATUSES = frozenset({"Final", "Final-Revised", "Final-Addendum"})

ENTRY_KEYS = frozenset({"gov", "also", "body_name", "state", "status", "official_url", "checked", "checked_url",
                        "checked_doc", "items", "platform", "host_ok", "reason", "reason_url"} | set(PLATFORM_KEYS))
ENTRY_REQUIRED = ("gov", "body_name", "state", "status", "official_url", "checked")
CANT_COVER_REQUIRED = ("reason", "reason_url", "checked")
HOST_OK_KEYS = frozenset({"date", "link"})

PATH_RE = re.compile(r"^[a-z0-9][a-z0-9/_.-]*$")            # daylight.full_url and the pagedir `page`
CLIENT_RE = re.compile(r"^[a-z0-9-]{2,40}$")                 # legistar.client
BODY_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")         # daylight.body (the search index body key)
CHECKED_DOC_RE = re.compile(r"^docs/[A-Za-z0-9_][A-Za-z0-9_/.-]*\.md$")
LABEL_KEY_RE = re.compile(r"^(slot|reason|note)\.[a-z0-9][a-z0-9-]*$")
ROOT_RE = re.compile(r"^(\.\./)*$")
# Controls and bidi overrides never belong in a curated name or label: national_guards.BAD_TEXT_RE.
MAX_NAME = 160
MAX_LABEL = 300

# `items: shown` (invariant `privacy-withhold/national-prefix`, architecture 3.2 and section 11 v3; finding 5).
# The rule is the reviewed entry: an entry may say `shown` only when SHOWN_REVIEWED has a row for its `gov` whose
# `entry` equals the entry in canonical form (`norm_entry`: every key, `also` sorted, `items` defaulted, dates as ISO
# text). The row holds the readable entry, not a hash, so the reviewer of the PR that adds or changes a row sees every
# field it vouches for (platform, source keys `daylight.body` / `legistar.client` and `body_id`, `also`, URLs, dates)
# in that one diff, whatever earlier PRs did to the YAML (security `privacy-withhold/review-row-opaque`). A build
# refused for a changed shown entry prints the whole canonical entry to paste. The `review` digest stamped on feeds is
# `review_digest` of that same canonical entry. Adding or changing a row is a code change, so it goes through code
# review; its comment names the source showing the body is the government's own council or commission, the source
# for each `also` id, and the review date. A second, fail-closed guard still runs on every shown entry: no school
# district id, a place, county or county subdivision id, ASCII only (a Cyrillic "о" in "Yоuth" hides the word), and
# no stem of SHOWN_DENYLIST_RE unless the row says `denylist_ok=True` (a place name such as College Station or
# Childress County). `withheld` needs no row: an edit to the YAML alone can narrow what is published, never widen it.


class ShownReview(NamedTuple):
    gov: str
    entry: dict                    # the reviewed entry in canonical form (norm_entry), every key, readable
    denylist_ok: bool = False      # True only for a place-name hit on SHOWN_DENYLIST_RE, said in the comment

    @property
    def digest(self) -> str:
        """review_digest of the reviewed entry: the `review` stamped on this government's feeds."""
        return review_digest(self.entry)


SHOWN_REVIEWED: tuple[ShownReview, ...] = (
    # source https://clarksvilletn.portal.civicclerk.com/ (the council's own agenda portal; docs/platform-facts.md
    # "CivicClerk, City Council 2024 on"); daylight.body `city` = config/localities/clarksville-tn/council.yml
    # body_key; no `also` ids; reviewed 2026-11-19 (B1 code review; readable row for security finding 1)
    ShownReview("place-4715160", {
        "gov": "place-4715160", "also": [], "body_name": "Clarksville City Council", "state": "TN",
        "status": "covered", "official_url": "https://www.clarksvilletn.gov/", "checked": "2026-11-19",
        "checked_url": "https://clarksvilletn.portal.civicclerk.com/", "items": "shown", "platform": "daylight",
        "daylight": {"body": "city", "full_url": "city/"}}),
    # source https://montgomerytn.gov/commission/agenda (the commission's own agenda page; docs/platform-facts.md
    # "Montgomery County, TN"); daylight.body `county` = national_clarksville.COUNTY_BODY_KEY; no `also` ids;
    # reviewed 2026-11-19 (B1 code review; readable row for security finding 1)
    ShownReview("county-47125", {
        "gov": "county-47125", "also": [], "body_name": "Montgomery County Commission", "state": "TN",
        "status": "covered", "official_url": "https://montgomerytn.gov/commission/agenda", "checked": "2026-11-19",
        "checked_url": "https://montgomerytn.gov/commission/agenda", "items": "shown", "platform": "daylight",
        "daylight": {"body": "county", "full_url": "meetings/agendas.html"}}),
)

# Stems of bodies whose items may name children, students or pretend officials. Child-specific stems match anywhere
# ("Preschool", "Schoolboard", "Childcare"); the shorter ones need a word start ("Kidder" still hits \bkid: a
# reviewed pair with denylist_ok=True is the way through).
SHOWN_DENYLIST_RE = re.compile(
    r"(school|educat|youth|student|child|pupil|juvenil|infant|toddler|scholar|foster|adolescen|cadet|young"
    r"|\b(kid|teen|minor|junior|mock|model|shadow|pre[\s-]?k(\b|inder)|head\s+start|early\s+learning|college"
    r"|universit|librar|hospital|pension|retire|civil\s+service))", re.IGNORECASE)
GENERAL_LAYERS = ("place", "county", "cousub")

LINE_LABEL = "note.{}"                # a gov-flags `line` is drawn from this label (labels.yml)
REQUIRED_LABELS = tuple(f"slot.{layer}" for layer in LAYERS) + ("note.no-city", "note.no-county")

STALE_AFTER = timedelta(days=3)       # 3.4: a covered government's data older than this at build time is `stale`

# Largest Census answer (JSON text) the lookup page accepts from the geo frame (architecture 4.0; security "needs
# verification"). Sized for MAX_MATCHES matches, each carrying one unit in each of the six layers, from the fields one
# recorded answer carries (docs/platform-facts.md "Census geocoder"): a layer unit is about 600-800 characters
# (OBJECTID, OID, GEOID, NAME, BASENAME, STATE, the layer's own code, FUNCSTAT, LSADC, the class code, MTFCC,
# AREALAND, AREAWATER, CENTLAT/CENTLON, INTPTLAT/INTPTLON, school grades), a match's own fields (matchedAddress,
# coordinates, tigerLine, addressComponents) about 600, and the envelope (input, benchmark, vintage) about 1,000.
# Each bound below is about twice that, so an answer of 20 matches x 6 layers fits with room for fields the Census
# adds; tests/test_national_directory.py builds that answer and checks it. More than 20 matches is "add the city and
# ZIP" (4.1); an answer longer than MAX_ANSWER has more matches than that, so the page shows the same tips.
# national.js copies this number (task F1; its test reads it from here).
MAX_MATCHES = 20
ANSWER_LAYERS = len(LAYERS)
UNIT_CHARS = 1_600
MATCH_CHARS = 1_200
ENVELOPE_CHARS = 4_000
MAX_ANSWER = MAX_MATCHES * (ANSWER_LAYERS * UNIT_CHARS + MATCH_CHARS) + ENVELOPE_CHARS     # 220,000 characters


class NationalConfigError(ValueError):
    """A curated national file breaks a rule: the build stops. The message names the file, the entry and the key."""


@dataclass(frozen=True)
class Directory:
    """The loaded directory (3.2): entries in file order, each with `items` and `also` filled in, `checked` a date."""
    govs: tuple[dict, ...]
    alias: dict[str, str] = field(default_factory=dict)        # an `also` id -> the entry's `gov` id

    def get(self, gov_id: str) -> dict | None:
        return next((g for g in self.govs if g["gov"] == gov_id), None)


@dataclass(frozen=True)
class GovFlags:
    """The loaded gov-flags (3.3)."""
    hide: tuple[str, ...] = ()
    show: tuple[str, ...] = ()
    rules: tuple[dict, ...] = ()          # {state: "<FIPS>", layer, show}
    lines: dict[str, str] = field(default_factory=dict)        # id -> line key (labels note.<line>)


# --- shared checks ---------------------------------------------------------------------------------------------

def _fail(path: Path, where: str, key: str, problem: str):
    raise NationalConfigError(f"{path}: {where}: {key}: {problem}")


def _read_yaml(path: Path, schema: str) -> dict:
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise NationalConfigError(f"{path}: cannot read: {e}") from e
    if not isinstance(doc, dict):
        _fail(path, "file", "schema", "not a mapping")
    if doc.get("schema") != schema:
        _fail(path, "file", "schema", f"must be {schema!r}")
    return doc


def _unknown(path: Path, where: str, obj: dict, allowed) -> None:
    extra = sorted(str(k) for k in obj if k not in allowed)
    if extra:
        _fail(path, where, extra[0], "unknown key")


def _id_fips(gov_id: str) -> str:
    return gov_id.split("-", 1)[1][:2]


def _text(path: Path, where: str, key: str, value, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(path, where, key, "must be non-empty text")
    if len(value) > limit or BAD_TEXT_RE.search(value):
        _fail(path, where, key, f"longer than {limit} characters or holds control or bidi characters")
    return value


def _date(path: Path, where: str, key: str, value) -> date:
    if isinstance(value, datetime) or not isinstance(value, (date, str)):
        _fail(path, where, key, "must be a date (YYYY-MM-DD)")
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value)
        except ValueError:
            _fail(path, where, key, "must be a date (YYYY-MM-DD)")
    return value


def _safe_path(value) -> bool:
    return isinstance(value, str) and bool(PATH_RE.fullmatch(value)) and ".." not in value and "//" not in value


# --- labels.yml ---------------------------------------------------------------------------------------------------

def load_labels(path: Path = LABELS_PATH) -> dict[str, str]:
    """labels.yml -> {key: text}. Keys `slot.<layer>`, `reason.<reason>`, `note.<key>`; every slot label and the two
    computed notes (no-city, no-county) must be there."""
    path = Path(path)
    doc = _read_yaml(path, LABELS_SCHEMA)
    _unknown(path, "file", doc, {"schema", "labels"})
    labels = doc.get("labels")
    if not isinstance(labels, dict) or not labels:
        _fail(path, "file", "labels", "must be a mapping of label keys to text")
    out = {}
    for k, v in labels.items():
        if not isinstance(k, str) or not LABEL_KEY_RE.fullmatch(k):
            _fail(path, "labels", str(k), "bad label key (slot.<layer>, reason.<reason> or note.<key>)")
        out[k] = _text(path, "labels", k, v, MAX_LABEL)
    missing = [k for k in REQUIRED_LABELS if k not in out]
    if missing:
        _fail(path, "labels", missing[0], "missing")
    return out


# --- directory.yml ------------------------------------------------------------------------------------------------

def _plain(path: Path, where: str, value, key: str = "") -> None:
    """Refuse any value a curated entry never needs (security `national/host-ok-unchecked`): only text, whole numbers,
    true/false, null, dates (as values), lists and mappings with text keys. Binary, sets, timestamps, floats and
    non-text keys stop the build here, never as a TypeError later."""
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                _fail(path, where, key or "entry", "every key must be text (a date or number key is refused)")
            _plain(path, where, v, f"{key}.{k}" if key else k)
    elif isinstance(value, list):
        for v in value:
            _plain(path, where, v, key)
    elif isinstance(value, datetime) or not (value is None or isinstance(value, (str, int, date))):
        _fail(path, where, key or "entry", f"a {type(value).__name__} value is not allowed (plain YAML only)")


def _iso_dates(value):
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _iso_dates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_iso_dates(v) for v in value]
    return value


def norm_entry(e: Mapping) -> dict:
    """The raw `safe_load` mapping of one directory entry in canonical form (section 11.2): every key kept, `also`
    defaulted to [] and sorted, `items` defaulted, every date written as ISO text (so YAML key order, `also` order and
    a quoted or plain date never change it). A loaded entry gives the same result: its `review` (set by the loader,
    never a YAML key) is left out."""
    out = _iso_dates({k: v for k, v in dict(e).items() if k != "review"})
    out["also"] = sorted(out.get("also") or [])
    out.setdefault("items", ITEMS_DEFAULT)
    return out


def review_digest(e: Mapping) -> str:
    """sha256 hex of the canonical JSON of the whole entry (section 11.2): what a SHOWN_REVIEWED row pins."""
    text = json.dumps({"schema": DIRECTORY_SCHEMA, "entry": norm_entry(e)}, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def source_key(e: Mapping) -> str | None:
    """The source a covered entry reads (11.1 row 4): `daylight:<body>` or `legistar:<client>:<body_id>`; else None."""
    if e.get("platform") == "daylight":
        return f"daylight:{e['daylight']['body']}"
    if e.get("platform") == "legistar":
        return f"legistar:{e['legistar']['client']}:{e['legistar']['body_id']}"
    return None


def _row_text(gov_id: str, entry: dict) -> str:
    """A SHOWN_REVIEWED row to paste: the whole canonical entry, readable."""
    lines = [f"    ShownReview({gov_id!r}, {{"]
    lines += [f"        {k!r}: {entry[k]!r}," for k in entry]
    return "\n".join(lines + ["    }),"])


def shown_refusal(gov_id: str, body_name: str, canonical: dict) -> str | None:
    """Why `items: shown` is refused for this entry, or None when it is allowed (the reviewed entry, then the
    fail-closed guard; see SHOWN_REVIEWED). `canonical` is the entry's norm_entry."""
    layer = id_layer(gov_id)
    if layer in SCHOOL_LAYERS:
        return "`shown` is never allowed for a school district (privacy-withhold)"
    if layer not in GENERAL_LAYERS:
        return "`shown` needs a place, county or county subdivision id (privacy-withhold)"
    if not body_name.isascii():
        return "`shown` needs a body_name in ASCII letters only (privacy-withhold/body-name-word-check)"
    review = next((r for r in SHOWN_REVIEWED if r.gov == gov_id), None)
    if review is None:
        return ("`shown` needs a SHOWN_REVIEWED row in sitegen/national.py, added through code review with its source "
                "(privacy-withhold); leave it withheld. The row to review and paste:\n" + _row_text(gov_id, canonical))
    if review.entry != canonical:
        changed = sorted(k for k in set(review.entry) | set(canonical) if review.entry.get(k) != canonical.get(k))
        return (f"`shown` entry differs from its SHOWN_REVIEWED row in {', '.join(changed)}: the entry changed since "
                "it was reviewed; re-review it (privacy-withhold/review-row-opaque) or leave it withheld. The row to "
                "review and paste:\n" + _row_text(gov_id, canonical))
    if SHOWN_DENYLIST_RE.search(body_name) and not review.denylist_ok:   # body_name is part of the entry
        return ("`shown` body_name holds a school, youth or special-purpose word; only a reviewed pair with "
                "denylist_ok=True passes (privacy-withhold/body-name-word-check)")
    return None


def _check_platform(path: Path, where: str, e: dict) -> None:
    present = [p for p in PLATFORM_KEYS if p in e]
    platform = e.get("platform")
    if platform is not None and not isinstance(platform, str):
        _fail(path, where, "platform", "must be a platform name")
    if platform is None:
        if "host_ok" in e:
            _fail(path, where, "host_ok", "host_ok without a platform that needs it")
        if present:
            _fail(path, where, present[0], "platform keys without `platform`")
        if e["status"] == "covered":
            _fail(path, where, "platform", "a covered entry needs `platform` and its keys")
        return
    if platform not in PLATFORM_KEYS:
        _fail(path, where, "platform", f"unknown platform {platform!r}")
    others = [p for p in present if p != platform]
    if others:
        _fail(path, where, others[0], f"keys for another platform than {platform!r}")
    keys = e.get(platform)
    if not isinstance(keys, dict):
        _fail(path, where, platform, "missing platform keys")
    _unknown(path, f"{where}.{platform}", keys, PLATFORM_KEYS[platform])
    missing = sorted(PLATFORM_REQUIRED[platform] - set(keys))
    if missing:
        _fail(path, f"{where}.{platform}", missing[0], "missing")
    if platform == "daylight":
        if "host_ok" in e:
            _fail(path, where, "host_ok", "only a platform other than daylight takes host_ok")
        if not isinstance(keys["body"], str) or not BODY_KEY_RE.fullmatch(keys["body"]):
            _fail(path, f"{where}.daylight", "body", "must match " + BODY_KEY_RE.pattern)
        if not _safe_path(keys["full_url"]):
            _fail(path, f"{where}.daylight", "full_url", "must be a site path matching " + PATH_RE.pattern +
                  " with no '..'")
        return
    # every platform but daylight: Brian's OK for the host (R5, finding 7)
    host_ok = e.get("host_ok")
    if not isinstance(host_ok, dict):
        _fail(path, where, "host_ok", f"platform {platform!r} needs host_ok: {{date, link}} (Brian's OK, R5)")
    _unknown(path, f"{where}.host_ok", host_ok, HOST_OK_KEYS)
    for k in sorted(HOST_OK_KEYS):
        if k not in host_ok:
            _fail(path, f"{where}.host_ok", k, "missing")
    _date(path, f"{where}.host_ok", "date", host_ok["date"])
    if not allowed_url(host_ok["link"]):
        _fail(path, f"{where}.host_ok", "link", "must be an https link")
    if platform == "legistar":
        client = keys["client"]
        if not isinstance(client, str) or not CLIENT_RE.fullmatch(client):
            _fail(path, f"{where}.legistar", "client", "must match " + CLIENT_RE.pattern)
        if isinstance(keys["body_id"], bool) or not isinstance(keys["body_id"], int) or keys["body_id"] <= 0:
            _fail(path, f"{where}.legistar", "body_id", "must be a positive whole number")
        if not isinstance(keys["tz"], str) or keys["tz"] not in zoneinfo.available_timezones():
            _fail(path, f"{where}.legistar", "tz", "must be a time zone name (zoneinfo)")
        fs = keys.get("final_statuses")
        if fs is not None and (not isinstance(fs, list) or not fs or len(set(map(str, fs))) != len(fs)
                               or any(not isinstance(s, str) or s not in LEGISTAR_FINAL_STATUSES for s in fs)):
            _fail(path, f"{where}.legistar", "final_statuses",
                  "must be a list of distinct values from " + ", ".join(sorted(LEGISTAR_FINAL_STATUSES)))
        for k in ("official_url", "checked_url", "reason_url"):
            if k in e and not allowed_url(e[k], "legistar", client):
                _fail(path, where, k, f"host is not a Legistar host for client {client!r}")


def load_directory(path: Path = DIRECTORY_PATH, labels: Mapping[str, str] | None = None,
                   repo_root: Path = config.REPO_ROOT) -> Directory:
    """directory.yml -> Directory, refusing every bad case of architecture 3.2 (NationalConfigError names the entry and
    the key). `labels` defaults to labels.yml beside the file (a can't-cover `reason` must have its label)."""
    path = Path(path)
    if labels is None:
        labels = load_labels(path.parent / "labels.yml")
    doc = _read_yaml(path, DIRECTORY_SCHEMA)
    _unknown(path, "file", doc, {"schema", "govs"})
    govs = doc.get("govs")
    if not isinstance(govs, list):
        _fail(path, "file", "govs", "must be a list")
    seen: set[str] = set()
    out, alias = [], {}
    for n, e in enumerate(govs):
        where = f"govs[{n}]"
        if not isinstance(e, dict):
            _fail(path, where, "gov", "entry must be a mapping")
        if isinstance(e.get("gov"), str) and id_layer(e["gov"]):
            where = f"govs[{n}] {e['gov']}"
        _plain(path, where, e)
        _unknown(path, where, e, ENTRY_KEYS)
        for k in ENTRY_REQUIRED:
            if k not in e:
                _fail(path, where, k, "missing")
        gov = e["gov"]
        if id_layer(gov) is None:
            _fail(path, where, "gov", "bad id (<layer>-<GEOID>, layers " + ", ".join(LAYERS) + ")")
        state = e["state"]
        if not isinstance(state, str) or state not in USPS_FIPS:
            _fail(path, where, "state", "must be a USPS state code")
        also = e.get("also", [])
        if not isinstance(also, list):
            _fail(path, where, "also", "must be a list of ids")
        for i in [gov, *also]:
            if id_layer(i) is None:
                _fail(path, where, "also", f"bad id {i!r}")
            if i in seen:
                _fail(path, where, "gov" if i == gov else "also", f"duplicate id {i}")
            if _id_fips(i) != USPS_FIPS[state]:
                _fail(path, where, "state", f"{state} does not match the state code of {i}")
            if id_layer(i) != id_layer(gov):
                # an alias names the same government in the same layer (a re-coded GEOID, 3.1); a cross-layer alias
                # would let a school district or a sub-body ride on a general government's `items: shown`
                _fail(path, where, "also", f"{i} is not in the layer of {gov} (privacy-withhold/also-cross-layer)")
            seen.add(i)
        body_name = _text(path, where, "body_name", e["body_name"], MAX_NAME)
        status = e["status"]
        if not isinstance(status, str) or status not in STATUSES:
            _fail(path, where, "status", "must be covered or cant-cover")
        checked = _date(path, where, "checked", e["checked"])
        for k in ("official_url", "checked_url", "reason_url"):
            if k in e and not allowed_url(e[k]):
                _fail(path, where, k, "must be an https URL (no user name, password or other port)")
        if "checked_url" in e and "checked_doc" in e:
            _fail(path, where, "checked_doc", "give checked_url or checked_doc, not both")
        if "checked_doc" in e:
            doc_path = e["checked_doc"]
            if not isinstance(doc_path, str) or not CHECKED_DOC_RE.fullmatch(doc_path) or ".." in doc_path \
                    or not (Path(repo_root) / doc_path).is_file():
                _fail(path, where, "checked_doc", "must be an existing docs/...md file in the repo")
        if status == "cant-cover":
            for k in CANT_COVER_REQUIRED:
                if k not in e:
                    _fail(path, where, k, "a cant-cover entry needs reason, reason_url and checked")
            if not isinstance(e["reason"], str) or e["reason"] not in REASONS:
                _fail(path, where, "reason", "unknown reason (" + ", ".join(REASONS) + ")")
            if f"reason.{e['reason']}" not in labels:
                _fail(path, where, "reason", f"no label reason.{e['reason']} in labels.yml")
        else:
            for k in ("reason", "reason_url"):
                if k in e:
                    _fail(path, where, k, "only a cant-cover entry has a reason")
        items = e.get("items", ITEMS_DEFAULT)
        if not isinstance(items, str) or items not in ITEMS:
            _fail(path, where, "items", "must be shown or withheld")
        if status == "cant-cover":
            # security `privacy-withhold/source-unique-covered-only`: a can't-cover entry names no source at all, so
            # source uniqueness (covered entries) and the host OK rule have nothing to miss
            for k in ("platform", "host_ok", *PLATFORM_KEYS):
                if k in e:
                    _fail(path, where, k, "a cant-cover entry has no platform, source keys or host_ok")
        _check_platform(path, where, e)
        canonical = norm_entry(e)            # after every other per-entry check (11.2)
        digest = review_digest(canonical)
        if items == "shown":
            why = shown_refusal(gov, body_name, canonical)
            if why:
                _fail(path, where, "items", why)
        g = dict(e, also=list(also), items=items, checked=checked, review=digest if items == "shown" else None)
        out.append(g)
        alias.update({a: gov for a in also})
    sources: dict[str, str] = {}
    for g in out:
        key = source_key(g) if g["status"] == "covered" else None
        if key is None:
            continue
        if key in sources:
            _fail(path, f"govs {g['gov']}", g["platform"],
                  f"source {key} is already {sources[key]}'s: one covered entry per source (11.1 row 4)")
        sources[key] = g["gov"]
    return Directory(govs=tuple(out), alias=alias)


# --- gov-flags.yml ------------------------------------------------------------------------------------------------

def load_gov_flags(path: Path = FLAGS_PATH, labels: Mapping[str, str] | None = None) -> GovFlags:
    """gov-flags.yml -> GovFlags (3.3). Every entry needs `why` and an https `source`; ids must be well formed; an id
    is never both hidden and shown; a `line` needs its `note.<line>` label."""
    path = Path(path)
    if labels is None:
        labels = load_labels(path.parent / "labels.yml")
    doc = _read_yaml(path, FLAGS_SCHEMA)
    _unknown(path, "file", doc, {"schema", "hide", "show", "rules", "lines"})
    shapes = {"hide": {"id", "why", "source"}, "show": {"id", "why", "source"},
              "rules": {"state", "layer", "show", "why", "source"}, "lines": {"id", "line", "why", "source"}}
    lists = {}
    for part, keys in shapes.items():
        entries = doc.get(part, []) or []
        if not isinstance(entries, list):
            _fail(path, "file", part, "must be a list")
        for n, e in enumerate(entries):
            where = f"{part}[{n}]"
            if not isinstance(e, dict):
                _fail(path, where, "id", "entry must be a mapping")
            _unknown(path, where, e, keys)
            for k in sorted(keys):
                if k not in e:
                    _fail(path, where, k, "missing")
            _text(path, where, "why", e["why"], MAX_LABEL)
            if not allowed_url(e["source"]):
                _fail(path, where, "source", "must be an https URL")
            if "id" in e and id_layer(e["id"]) is None:
                _fail(path, where, "id", f"bad id {e['id']!r}")
        lists[part] = entries
    hide = [e["id"] for e in lists["hide"]]
    show = [e["id"] for e in lists["show"]]
    for part, ids in (("hide", hide), ("show", show), ("lines", [e["id"] for e in lists["lines"]])):
        dup = next((i for n, i in enumerate(ids) if i in ids[:n]), None)
        if dup:
            _fail(path, part, "id", f"duplicate id {dup}")
    both = next((i for i in hide if i in show), None)
    if both:
        _fail(path, "show", "id", f"{both} is both hidden and shown")
    rules, seen_rules = [], set()
    for n, r in enumerate(lists["rules"]):
        where = f"rules[{n}]"
        if not isinstance(r["state"], str) or r["state"] not in FIPS_STATES:
            _fail(path, where, "state", "must be a two-digit state FIPS code in quotes")
        if not isinstance(r["layer"], str) or r["layer"] not in LAYERS:
            _fail(path, where, "layer", "unknown layer")
        if not isinstance(r["show"], bool):
            _fail(path, where, "show", "must be true or false")
        if r["show"]:
            _fail(path, where, "show", "state rules only hide; use id-level show")
        if (r["state"], r["layer"]) in seen_rules:
            _fail(path, where, "layer", "duplicate rule for this state and layer")
        seen_rules.add((r["state"], r["layer"]))
        rules.append({"state": r["state"], "layer": r["layer"], "show": r["show"]})
    lines = {}
    for n, e in enumerate(lists["lines"]):
        if not isinstance(e["line"], str) or LINE_LABEL.format(e["line"]) not in labels:
            _fail(path, f"lines[{n}]", "line", f"no label {LINE_LABEL.format(e['line'])} in labels.yml")
        lines[e["id"]] = e["line"]
    return GovFlags(hide=tuple(hide), show=tuple(show), rules=tuple(rules), lines=lines)


# --- the embedded page directory (3.4) ----------------------------------------------------------------------------

def _parse_instant(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def gov_page(gov: dict) -> str:
    """A covered government's coming-up page, relative to the site root (1a): `digest/<st>/<body id>.html`."""
    page = f"digest/{gov['state'].lower()}/{gov['gov']}.html"
    if not _safe_path(page):
        raise NationalConfigError(f"{gov['gov']}: page: {page!r} is not a safe site path")
    return page


def page_directory(directory: Directory, flags: GovFlags, labels: Mapping[str, str], *, built_at: datetime,
                   last_ok_at: Mapping[str, str | None], root: str = "../") -> dict:
    """The page directory (3.4) the lookup page embeds: pure, from the loaded files. `built_at` is the build's instant
    (aware); `last_ok_at` maps a covered government's id to its JSON's `last_ok_at` (missing or None: stale). `page`
    and `full` are relative to `root`, the page's own data-root."""
    if built_at.tzinfo is None:
        raise ValueError("built_at must carry a time zone")
    if not isinstance(root, str) or not ROOT_RE.fullmatch(root):
        raise ValueError(f"root must be a run of '../', not {root!r}")
    built = built_at.astimezone(zoneinfo.ZoneInfo(config.SITE["site_timezone"])).date()
    govs = {}
    for g in directory.govs:
        entry = {"board": g["body_name"], "status": g["status"]}
        if g["status"] == "covered":
            last = _parse_instant(last_ok_at.get(g["gov"]))
            entry["page"] = gov_page(g)
            if g.get("platform") == "daylight":
                entry["full"] = g["daylight"]["full_url"]
            entry["stale"] = last is None or built_at - last > STALE_AFTER
        else:
            entry.update(reason=g["reason"], checked=g["checked"].isoformat(), reason_url=g["reason_url"],
                         official_url=g["official_url"])
        govs[g["gov"]] = entry
    return {"schema": PAGEDIR_SCHEMA, "built": built.isoformat(), "root": root, "govs": govs,
            "alias": dict(directory.alias), "hide": list(flags.hide), "show": list(flags.show),
            "rules": [dict(r) for r in flags.rules], "lines": dict(flags.lines), "labels": dict(labels)}


def embed_json(obj) -> str:
    """JSON text safe inside a <script type="application/json"> element: Jinja's |tojson escaping (<, >, & and '
    as \\u escapes, non-ASCII escaped), keys sorted so a build is stable. Never build the pagedir by string."""
    return str(htmlsafe_json_dumps(obj, sort_keys=True, separators=(",", ":")))


def load_all(folder: Path = NATIONAL_DIR) -> tuple[Directory, GovFlags, dict[str, str]]:
    """The three curated files, checked together (the builder's entry point)."""
    folder = Path(folder)
    labels = load_labels(folder / "labels.yml")
    directory = load_directory(folder / "directory.yml", labels)
    flags = load_gov_flags(folder / "gov-flags.yml", labels)
    hidden = set(flags.hide)
    for g in directory.govs:
        for i in [g["gov"], *g["also"]]:
            if i in hidden:
                raise NationalConfigError(f"{folder / 'gov-flags.yml'}: hide: id: {i} is in directory.yml "
                                          f"({g['gov']}); a listed government is never hidden")
    return directory, flags, labels


# --- the geo frame, digest/geo-frame.html (architecture 4.0; security finding 1, national/csp-jsonp-gadget) ---------

GEO_FRAME_SCRIPT_PATH = config.TEMPLATE_DIR / "_geo_frame.js"
GEO_FRAME_PAGE = "digest/geo-frame.html"          # relative to the site root; the lookup page loads "geo-frame.html"
# The one source the frame's CSP adds: the geographies path, exact (a CSP source with a path and no trailing slash
# matches that path only). No other page names the Census in its CSP (the parent's script-src stays 'self').
CENSUS_GEOGRAPHIES = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"


def script_hash(js: str) -> str:
    """The CSP source for one inline script: sha256-<base64> of its exact UTF-8 text (as sitegen.views.script_hash)."""
    return "sha256-" + base64.b64encode(hashlib.sha256(js.encode("utf-8")).digest()).decode("ascii")


def geo_frame_script(path: Path = GEO_FRAME_SCRIPT_PATH) -> str:
    """The frame's one inline script (site/templates/_geo_frame.js), fixed text. Refused if it could end the script
    element or open a comment, or if it names any host but the Census geographies path."""
    js = Path(path).read_text(encoding="utf-8").strip()
    if "</" in js or "<!--" in js:
        raise ValueError(f"{path} must not contain '</' or '<!--' (it is inlined in geo-frame.html)")
    hosts = set(re.findall(r"[a-z][a-z0-9+.-]*://[^\s\"'/]+", js, re.IGNORECASE))
    if hosts != {"https://geocoding.geo.census.gov"} or CENSUS_GEOGRAPHIES not in js:
        raise ValueError(f"{path} must name the Census geographies path and no other host, not {sorted(hosts)}")
    return js


def geo_frame_csp(js: str) -> str:
    """The frame's meta CSP (4.0): nothing by default; scripts only this inline one, by hash, and the Census
    geographies path. base-uri and form-action, which default-src does not cover, are closed too."""
    return (f"default-src 'none'; script-src '{script_hash(js)}' {CENSUS_GEOGRAPHIES}; base-uri 'none'; "
            "form-action 'none'")


def geo_frame_html(path: Path = GEO_FRAME_SCRIPT_PATH) -> str:
    """digest/geo-frame.html, the whole file; pure (the builder, task B4, writes it once per build). The lookup page
    loads it in <iframe sandbox="allow-scripts" src="geo-frame.html" referrerpolicy="no-referrer"> (no
    allow-same-origin: an opaque origin), and the address reaches it only by postMessage after it posts "ready"."""
    js = geo_frame_script(path)
    return ("<!doctype html>\n"
            '<html lang="en"><head><meta charset="utf-8">\n'
            f'<meta http-equiv="Content-Security-Policy" content="{geo_frame_csp(js)}">\n'
            '<meta name="referrer" content="no-referrer">\n'
            "<title>Census address lookup</title></head>\n"
            f"<body><script>{js}</script></body></html>\n")
