"""The city registry: config/cities/<slug>/city.yml, one per city, loaded and checked here.

A city file holds who and where the city is, its sources (portal type + config file), the hosts its collection may
ask (each with its robots.txt and terms check), its launch plan and its site settings. Brand keys are locked
(cities/brand.py). Clarksville's file points at today's files (config/site.yml, config/localities/...) instead of
copying them, so its live build is unchanged. A new city keeps its site settings in its own `site_file`
(config/cities/<slug>/site.yml: the primary body, the place name; ADR 0012 decisions 1-2), laid over the place-free
keys of config/site.yml (SHARED_SITE_KEYS). Nothing here fetches anything.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlsplit
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from collector.hosts import DENIED_HOSTS, host_denied, host_matches

from . import brand as brand_mod
from .errors import CityError
from .readers import READERS

ROOT = Path(__file__).resolve().parent.parent
CITIES_DIR = ROOT / "config" / "cities"
UNVERIFIED = "UNVERIFIED"
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
LOCAL_READER_CITY = "clarksville-tn"     # the one city the Clarksville-only readers (shared=False) may serve
STATUSES = ("draft", "live")
# Every pattern below is used with fullmatch: `$` alone also matches before a final newline (city-file/regex-dollar-
# newline), so "Murfreesboro\n" would pass .match.
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*-([a-z]{2})")       # <place>-<state>, e.g. salem-or
STATE_RE = re.compile(r"[A-Z]{2}")
HOST_RE = re.compile(r"(?=.{1,253}\Z)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+")
DOMAIN_RE = re.compile(r"(?:[a-z0-9-]+\.)?daylight\.gnoshcodes\.com")
# Site settings a city sets (top level of city.yml) -> the config/site.yml key the site build reads.
SITE_FIELDS = {"sky_place": "sky_place", "geocoder_places": "geocoder_places"}
KEYS = {"slug", "name", "state", "timezone", "status", "domain", "settings", "platform_facts", "sources",
        "allowed_hosts", "denied_hosts", "launch", "sky_place", "district_lookup", "geocoder_places",
        "verification_notes", "site", "site_file", "go_ahead"}
REQUIRED = ("slug", "name", "state", "timezone", "status", "domain", "platform_facts", "sources", "allowed_hosts")
FROM_SETTINGS = ("sky_place", "district_lookup", "geocoder_places")   # read from a legacy settings file instead
# The place-free keys of config/site.yml, as dotted paths: a new city's settings start from them, so the shared
# wording has one copy (ADR 0012 decision 1). None may hold a place (SHARED_PLACE_WORDS) and no city file may set one.
# Mixed blocks are split by path: unofficial.bodies and item_types (the county's CZ- prefixes) are each city's own.
SHARED_SITE_KEYS = ("purpose", "purpose_plus", "welcome_lede", "welcome_lede_parts", "welcome_lede_phone", "days",
                    "video_link", "video_label", "video_recording", "unofficial.tag", "unofficial.notice",
                    "unofficial.correction_label", "unofficial.differ", "unofficial.not_advice",
                    "unofficial.email_line", "unofficial.short")
SHARED_PLACE_WORDS = re.compile(r"(?i:clarksville|montgomery|cmcss|regional planning)|\bRPC\b")
SHARED_SOURCE = "config/site.yml"
# Settings a new city's site file may not set: they come from city.yml (one place) or from the status.
FROM_CITY_FILE = ("site_timezone", "today_place", "sky_place", "geocoder_places", "district_lookup_url",
                  "district_lookup_label", "live")
# The only settings a new city's site file (or `site:` block) may set, as dotted paths: what a city owns (ADR 0012
# decision 2; city-file/unlocked-trust-keys). Anything else fails, naming the key, so a city file can't set a
# trust key such as corrections.github_repo, analytics.code, a geocoder URL or alerts.site_url (from the domain).
CITY_SITE_KEYS = ("place_name", "corrections_log", "primary", "unofficial.bodies", "item_types", "alerts.feed_id",
                  "alerts.max_entries", "alerts.topics")
# The `primary:` block (ADR 0012 decision 2): the body a city-only site is built around. (Not sitegen/config.py
# PRIMARY_KEYS, the normalised dict the build reads.)
PRIMARY_BLOCK_KEYS = ("key", "name", "label", "record", "kind_labels", "held_sentences", "seats", "titles",
                      "member_title", "seat_basis")
PRIMARY_REQUIRED = ("key", "name", "label", "seats")
SEATS = ("districts", "wards", "at_large")
BODY_KEY_RE = re.compile(r"[a-z][a-z0-9-]*")
PLACE_NAME_RE = re.compile(r"[A-Za-z](?:[A-Za-z .'-]*[A-Za-z.])?")   # letters, spaces, hyphens, periods, apostrophes
PLACE_NAME_MAX = 40
TITLE_RE = re.compile(r"[A-Za-z][A-Za-z -]*")


def title_slug(title: str) -> str:
    """The seat slug of a printed title: the rule of sitegen.seats.title_slug ('Vice Mayor' -> 'vice-mayor'), kept
    here because sitegen.config imports this module (a test holds the two equal)."""
    return re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")


def is_unverified(value) -> bool:
    return isinstance(value, str) and value.strip().upper().startswith(UNVERIFIED)


def check_recorded(value) -> bool:
    """A host's robots or terms line counts as recorded only when it names the date of the check (YYYY-MM-DD) and is
    not marked unverified (any case). "TODO", "not checked" or a note without a date is not a record."""
    if not isinstance(value, str):
        return False
    up = value.upper()
    return not any(w in up for w in (UNVERIFIED, "NOT CHECKED", "TODO")) and bool(ISO_DATE.search(value))


def city_dir(slug: str, root: Path = ROOT) -> Path:
    return root / "config" / "cities" / slug


def slugs(root: Path = ROOT) -> list[str]:
    d = root / "config" / "cities"
    return sorted(p.parent.name for p in d.glob("*/city.yml"))


def load_city(slug: str, root: Path = ROOT, brand: dict | None = None) -> dict:
    """Load and check one city. Raises CityError naming the file and the key on any structural problem.
    UNVERIFIED values are allowed here; `python -m cities check` lists them (and says NOT READY)."""
    path = city_dir(slug, root) / "city.yml"
    if not path.is_file():
        raise CityError(f"{path}: no such city file")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    where = str(path.relative_to(root))
    if not isinstance(raw, dict):
        raise CityError(f"{where}: must be a mapping")
    brand = brand if brand is not None else brand_mod.load_brand(root / "config" / "brand.yml")
    city = dict(raw)
    city["_path"] = path
    _check_identity(city, slug, where)
    clash = brand_mod.locked_keys_set(city) + brand_mod.locked_keys_set(city.get("site") or {})
    brand_mod.refuse(clash, where)
    unknown = sorted(set(raw) - KEYS)
    if unknown:
        raise CityError(f"{where}: unknown keys {', '.join(unknown)}")
    city["settings_data"] = _settings(city, root, brand, where)
    city["sources"] = _sources(city, root, where)
    city["allowed_hosts"] = _hosts(city, where)
    city["denied_hosts"] = _denied(city)
    city["launch"] = _launch(city.get("launch"), where)
    _check_go_ahead(city, where)
    _check_source_hosts(city, root, where)
    _check_platform_facts(city, root, where)
    return city


def load_all(root: Path = ROOT) -> list[dict]:
    brand = brand_mod.load_brand(root / "config" / "brand.yml")
    cities = [load_city(s, root, brand) for s in slugs(root)]
    seen: dict[str, str] = {}
    for c in cities:
        if c["domain"] in seen:
            raise CityError(f"{c['slug']}: domain {c['domain']} is already {seen[c['domain']]}'s")
        seen[c["domain"]] = c["slug"]
    return cities


def allowed_hosts(city: dict) -> tuple[str, ...]:
    """The hosts a city's collection may ask, in file order (a denied host never appears: load_city refuses it)."""
    return tuple(h["host"] for h in city["allowed_hosts"])


def may_fetch(city: dict, host: str) -> bool:
    """The fetcher's rule for this city: never a denied host (global or the city's own), else on its allowlist."""
    host = host.lower()
    return not host_denied(host, city["denied_hosts"]) and host_matches(host, allowed_hosts(city))


def site_settings(city: dict, brand: dict) -> dict:
    """The city's site settings with the shared brand laid over them (brand keys locked). For a new city these are,
    in order: the SHARED_SITE_KEYS of config/site.yml, its site_file, its `site:` block, the fields of city.yml
    (time zone, today_place, sky_place, geocoder_places, district_lookup), `live` from its status, then the brand."""
    s = dict(city["settings_data"])
    if city.get("settings"):                       # legacy file: its brand duplicates already equal the brand
        s = {k: v for k, v in s.items() if k not in brand_mod.LOCKED}
        if isinstance(s.get("corrections"), dict):
            s["corrections"] = {k: v for k, v in s["corrections"].items() if k != "email"}
    return brand_mod.merge(brand, s, str(city["_path"]))


# ------------------------------------------------------------------ checks
def _check_identity(city: dict, slug: str, where: str) -> None:
    missing = [k for k in REQUIRED if k not in city or city[k] in (None, "")] + (
        ["sources"] if city.get("sources") == [] else [])
    if missing:
        raise CityError(f"{where}: missing {', '.join(missing)}")
    m = SLUG_RE.fullmatch(str(city["slug"]))
    if city["slug"] != slug or not m:
        raise CityError(f"{where}: slug must be the folder name, written <place>-<state> (e.g. salem-or)")
    if not STATE_RE.fullmatch(str(city["state"])) or m.group(1) != str(city["state"]).lower():
        raise CityError(f"{where}: state must be the two-letter code the slug ends with, in capitals")
    if city["status"] not in STATUSES:
        raise CityError(f"{where}: status must be one of {', '.join(STATUSES)}")
    if not is_unverified(city["timezone"]):
        try:
            ZoneInfo(str(city["timezone"]))
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise CityError(f"{where}: timezone {city['timezone']!r} is not an IANA zone (e.g. America/Chicago)") \
                from exc
    if not DOMAIN_RE.fullmatch(str(city["domain"])):
        raise CityError(f"{where}: domain must be daylight.gnoshcodes.com or <name>.daylight.gnoshcodes.com")


def _settings(city: dict, root: Path, brand: dict, where: str) -> dict:
    """Legacy (Clarksville): the settings file it points at, whose brand duplicates must equal config/brand.yml and
    whose time zone must equal the city's. New cities: the shared keys of config/site.yml, then the city's own
    site_file and `site:` block, then city.yml's own fields (ADR 0012 decision 1)."""
    if city.get("settings") and city.get("site_file"):
        raise CityError(f"{where}: settings (a legacy settings file) and site_file can't both be set")
    if city.get("settings"):
        doubled = [k for k in FROM_SETTINGS if k in city]
        if doubled:
            raise CityError(f"{where}: {', '.join(doubled)} come from {city['settings']}; set them in one place")
        p = root / city["settings"]
        if not p.is_file():
            raise CityError(f"{where}: settings file {city['settings']} not found")
        site = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        drift = brand_mod.drift(brand, site)
        if drift:
            raise CityError(f"{city['settings']}: brand keys differ from config/brand.yml: {', '.join(drift)}")
        if site.get("site_timezone") != city["timezone"]:
            raise CityError(f"{where}: timezone {city['timezone']} differs from {city['settings']} site_timezone")
        city["sky_place"] = site.get("sky_place")
        city["district_lookup"] = {"url": site.get("district_lookup_url") or "",
                                   "label": site.get("district_lookup_label") or ""}
        city["geocoder_places"] = site.get("geocoder_places") or []
        return site
    site = _shared(root)
    if city.get("site_file"):
        site = _deep_merge(site, _site_file(city, root))
    block = city.get("site") or {}
    if not isinstance(block, dict):
        raise CityError(f"{where}: site is a mapping of site settings")
    _refuse_owned(block, f"{where} site")
    _refuse_denied_links(block, _denied(city), f"{where} site")
    site = _deep_merge(site, block)
    _check_site(site, city, root, where)
    site.update({"site_timezone": city["timezone"], "today_place": city["name"], "live": city["status"] == "live"})
    for k, sk in SITE_FIELDS.items():
        if k in city and not is_unverified(city[k]):
            site[sk] = city[k]
    if isinstance(site.get("alerts"), dict):
        site["alerts"].setdefault("site_url", f"https://{city['domain']}/")
    lookup = city.get("district_lookup") or {}
    if is_unverified(lookup):
        lookup = {}
    elif lookup and not (isinstance(lookup, dict) and isinstance(lookup.get("url"), str)
                         and lookup["url"].startswith("https://") and isinstance(lookup.get("label"), str)):
        raise CityError(f"{where}: district_lookup is {{url: https://..., label: ...}}")
    _refuse_denied_links({"district_lookup": lookup}, _denied(city), where)
    if lookup:
        site["district_lookup_url"], site["district_lookup_label"] = lookup.get("url", ""), lookup.get("label", "")
    sky = city.get("sky_place")
    if sky is not None and not is_unverified(sky):
        if not (isinstance(sky, dict) and all(isinstance(sky.get(k), (int, float)) for k in ("lat", "lon"))
                and -90 <= sky["lat"] <= 90 and -180 <= sky["lon"] <= 180):
            raise CityError(f"{where}: sky_place is {{lat, lon}} in degrees")
    places = city.get("geocoder_places")
    if places is not None and not is_unverified(places) and not (
            isinstance(places, list) and len(places) <= 5 and all(isinstance(p, str) for p in places)):
        raise CityError(f"{where}: geocoder_places is a list of at most 5 mailing places")
    return site


_MISSING = object()


def _get(d: dict, dotted: str):
    for part in dotted.split("."):
        if not isinstance(d, dict) or part not in d:
            return _MISSING
        d = d[part]
    return d


def _deep_merge(base: dict, over: dict) -> dict:
    """`over` laid on `base`; a mapping in both is merged key by key, anything else is replaced."""
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else v
    return out


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _shared(root: Path) -> dict:
    """The SHARED_SITE_KEYS of config/site.yml, nested as there. Each must exist and name no place."""
    p = root / SHARED_SOURCE
    if not p.is_file():
        raise CityError(f"{SHARED_SOURCE} not found: a new city's shared site settings come from it")
    src = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: dict = {}
    for dotted in SHARED_SITE_KEYS:
        value = _get(src, dotted)
        if value is _MISSING:
            raise CityError(f"{SHARED_SOURCE}: shared key {dotted} (registry.SHARED_SITE_KEYS) is missing")
        named = [w for t in _strings(value) for w in SHARED_PLACE_WORDS.findall(t)]
        if named:
            raise CityError(f"{SHARED_SOURCE}: shared key {dotted} names a place ({', '.join(sorted(set(named)))}); "
                            "a shared key is the same for every city, so move it to each city's site file")
        node = out
        *parents, leaf = dotted.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    return out


def _refuse_owned(data: dict, where: str) -> None:
    """A city's own settings may not set a brand key, a shared key, or a key that comes from city.yml."""
    brand_mod.refuse(brand_mod.locked_keys_set(data), where)
    shared = [k for k in SHARED_SITE_KEYS if _get(data, k) is not _MISSING]
    if shared:
        raise CityError(f"{where}: {', '.join(shared)} {'is a' if len(shared) == 1 else 'are'} shared setting"
                        f"{'s' if len(shared) > 1 else ''} of every city, set once in {SHARED_SOURCE}. "
                        "Remove it from the city's file.")
    owned = [k for k in FROM_CITY_FILE if k in data]
    if owned:
        raise CityError(f"{where}: {', '.join(owned)} come{'s' if len(owned) == 1 else ''} from city.yml (live from "
                        "its status); set them in one place")
    other = _outside(data, CITY_SITE_KEYS)
    if other:
        raise CityError(f"{where}: {', '.join(other)} can't be set in a city's file: a city sets only "
                        f"{', '.join(CITY_SITE_KEYS)} (cities/registry.py CITY_SITE_KEYS). Remove it.")


def _outside(data: dict, allowed: tuple[str, ...], prefix: str = "") -> list[str]:
    """The dotted keys of `data` that are not one of `allowed` and not inside one (city-file/unlocked-trust-keys)."""
    out = []
    for k, v in data.items():
        path = f"{prefix}{k}"
        if path in allowed:
            continue
        if isinstance(v, dict) and v:                    # name the leaf: corrections.github_repo, not corrections
            out += _outside(v, allowed, path + ".")
        else:
            out.append(path)
    return out


def _denied(city: dict) -> tuple[str, ...]:
    """The hosts this city may never ask or link: collector DENIED_HOSTS plus the city's own denied_hosts."""
    return tuple(DENIED_HOSTS) + tuple(str(h).lower() for h in city.get("denied_hosts") or ())


URL_IN_TEXT = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s\"'<>`]+")


def _refuse_denied_links(data, denied: tuple[str, ...], where: str, path: str = "") -> None:
    """No URL a city's file sets (primary.record.url, primary.seat_basis.url, unofficial.bodies[].url, a URL inside
    any text) may point at a denied host: a host we never collect from is never linked either
    (city-only/denied-host-never-linked)."""
    if isinstance(data, dict):
        for k, v in data.items():
            _refuse_denied_links(v, denied, where, f"{path}.{k}" if path else str(k))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            _refuse_denied_links(v, denied, where, f"{path}[{i}]")
    elif isinstance(data, str):
        for m in URL_IN_TEXT.finditer(data):
            try:
                host = urlsplit(m.group(0)).hostname or ""
            except ValueError as exc:
                raise CityError(f"{where}: {path} holds {m.group(0)!r}, which is not a valid URL") from exc
            if host and host_denied(host, denied):
                raise CityError(f"{where}: {path} links {host}, a denied host; it can never be asked or linked")


def _city_path(rel, city: dict, root: Path, what: str, where: str) -> Path:
    """`rel` (a repository path) when it lies inside config/cities/<slug>/ once resolved; no absolute path, no `..`
    (city-file/path-outside-city-dir)."""
    home = f"config/cities/{city['slug']}/"
    if not (isinstance(rel, str) and rel.strip()):
        raise CityError(f"{where}: {what} must be a path inside {home}")
    p = Path(rel)
    full = (root / p).resolve()
    inside = full.is_relative_to(city_dir(city["slug"], root).resolve())
    if p.is_absolute() or ".." in p.parts or "\\" in rel or not inside:
        raise CityError(f"{where}: {what} {rel} must be a path inside {home} (no absolute path, no ..)")
    return full


def _site_file(city: dict, root: Path) -> dict:
    rel, where = city["site_file"], str(city["_path"].relative_to(root))
    full = _city_path(rel, city, root, "site_file", where)
    if not full.is_file():
        raise CityError(f"{where}: site_file {rel} not found")
    data = yaml.safe_load(full.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise CityError(f"{rel}: must be a mapping")
    _refuse_owned(data, rel)
    _refuse_denied_links(data, _denied(city), rel)
    return data


def _https_or_unverified(value) -> bool:
    if is_unverified(value):
        return True
    if not isinstance(value, str) or any(c.isspace() or c in "\"'<>`\\" for c in value):
        return False
    return value.startswith("https://") and bool(urlsplit(value).netloc)


def _plain(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not any(c in value for c in "<>&{}")


def _check_site(site: dict, city: dict, root: Path, where: str) -> None:
    """The keys of ADR 0012 a new city's settings may carry: place_name, corrections_log and the primary block."""
    if "place_name" in site:
        name = site["place_name"]
        if not (isinstance(name, str) and len(name) <= PLACE_NAME_MAX and PLACE_NAME_RE.fullmatch(name)):
            raise CityError(f"{where}: place_name must be a plain name (letters, spaces, hyphens, periods, "
                            f"apostrophes), at most {PLACE_NAME_MAX} characters")
    if "corrections_log" in site:
        log = site["corrections_log"]
        full = _city_path(log, city, root, "corrections_log", where)
        if not (log.endswith(".json") and full.is_file()):
            raise CityError(f"{where}: corrections_log {log} is not a JSON file in the repository")
    if "primary" in site:
        _check_primary(site["primary"], where)


def _check_primary(p, where: str) -> None:
    w = f"{where}: primary"
    if not isinstance(p, dict):
        raise CityError(f"{w} is a mapping ({', '.join(PRIMARY_BLOCK_KEYS)})")
    unknown = sorted(set(p) - set(PRIMARY_BLOCK_KEYS))
    if unknown:
        raise CityError(f"{w}: unknown keys {', '.join(unknown)} (known: {', '.join(PRIMARY_BLOCK_KEYS)})")
    missing = [k for k in PRIMARY_REQUIRED if k not in p]
    if missing:
        raise CityError(f"{w}: missing {', '.join(missing)}")
    if not (isinstance(p["key"], str) and BODY_KEY_RE.fullmatch(p["key"])):
        raise CityError(f"{w}.key must be a lowercase word (the search body key), e.g. council")
    for k in ("name", "label", "member_title"):
        if k in p and not _plain(p[k]):
            raise CityError(f"{w}.{k} must be plain text (no markup or braces)")
    if not (p["seats"] in SEATS or is_unverified(p["seats"])):
        raise CityError(f"{w}.seats must be one of {', '.join(SEATS)} (or UNVERIFIED), got {p['seats']!r}")
    for k in ("record", "seat_basis"):
        if k not in p:
            continue
        v = p[k]
        need = ("url", "label") + (("sentence",) if k == "seat_basis" else ())
        if not (isinstance(v, dict) and set(v) == set(need) and all(_plain(v[x]) for x in need)):
            raise CityError(f"{w}.{k} is {{{', '.join(need)}}}, each plain text")
        if not _https_or_unverified(v["url"]):
            raise CityError(f"{w}.{k}.url must be an https URL or UNVERIFIED")
    if "kind_labels" in p:
        kl = p["kind_labels"]
        if not (isinstance(kl, dict) and kl and "other" in kl
                and all(isinstance(k, str) and _plain(v) for k, v in kl.items())):
            raise CityError(f"{w}.kind_labels maps each meeting kind (and `other`) to plain words")
    if "held_sentences" in p:        # the rule of sitegen/config.py load_council, for council.yml
        held = p["held_sentences"]
        if not (isinstance(held, dict) and "other" in held and all(
                isinstance(v, str) and v.startswith("Not confirmed: ") and v.endswith(".") for v in held.values())):
            raise CityError(f"{w}.held_sentences must map checks (and `other`) to 'Not confirmed: ...' sentences")
    if "titles" in p:
        t = p["titles"]
        if not (isinstance(t, list) and all(isinstance(x, str) and TITLE_RE.fullmatch(x) for x in t)):
            raise CityError(f"{w}.titles is a list of plain words (the printed titles, e.g. Mayor), never who holds "
                            "them")
        seen: dict[str, str] = {}
        for x in t:     # two titles with one slug would share seat title-<slug> (review nit 4)
            if title_slug(x) in seen:
                raise CityError(f"{w}.titles {seen[title_slug(x)]!r} and {x!r} are one seat "
                                f"(title-{title_slug(x)}); list each printed title once")
            seen[title_slug(x)] = x


def _sources(city: dict, root: Path, where: str) -> list[dict]:
    out = []
    if not isinstance(city["sources"], list):
        raise CityError(f"{where}: sources is a list of {{portal, config}}")
    for i, s in enumerate(city["sources"]):
        if not isinstance(s, dict) or "portal" not in s:
            raise CityError(f"{where}: sources[{i}] needs a portal")
        r = READERS.get(s["portal"])
        if r is None:
            raise CityError(f"{where}: sources[{i}] portal {s['portal']!r} is unknown "
                            f"(known: {', '.join(sorted(READERS))})")
        if not r.shared and city["slug"] != LOCAL_READER_CITY:
            raise CityError(f"{where}: sources[{i}] portal {s['portal']!r} is a Clarksville-only reader; it can't "
                            "serve another city")
        cfg = s.get("config")
        if r.loader and not cfg:
            raise CityError(f"{where}: sources[{i}] ({s['portal']}) needs its config file")
        if cfg and not (root / cfg).is_file():
            raise CityError(f"{where}: sources[{i}] config {cfg} not found")
        if cfg and r.required:
            data = yaml.safe_load((root / cfg).read_text(encoding="utf-8")) or {}
            missing = [k for k in r.required if k not in data]
            if missing:
                raise CityError(f"{cfg}: the {r.label} reader needs {', '.join(missing)}")
        out.append({**s, "reader": r})
    return out


def _hosts(city: dict, where: str) -> list[dict]:
    out, seen = [], set()
    if not isinstance(city["allowed_hosts"], list):
        raise CityError(f"{where}: allowed_hosts is a list of {{host, robots, terms}}")
    for i, h in enumerate(city["allowed_hosts"]):
        if not isinstance(h, dict) or not isinstance(h.get("host"), str):
            raise CityError(f"{where}: allowed_hosts[{i}] is {{host, robots, terms}}")
        host = h["host"].strip().lower()
        if not HOST_RE.fullmatch(host):
            raise CityError(f"{where}: allowed_hosts[{i}] {host!r} is not a host name")
        if host_denied(host, _denied(city)):
            raise CityError(f"{where}: {host} is a denied host and can never be allowed")
        for k in ("robots", "terms"):
            if not (isinstance(h.get(k), str) and h[k].strip()):
                raise CityError(f"{where}: {host} needs {k}: when and where it was checked, or UNVERIFIED")
        if host in seen:
            raise CityError(f"{where}: {host} listed twice")
        seen.add(host)
        out.append({**h, "host": host})
    return out


def _launch(launch, where: str) -> dict | None:
    if launch is None:
        return None
    if not isinstance(launch, dict):
        raise CityError(f"{where}: launch is {{launch_days, earliest}}")
    days = launch.get("launch_days")
    if not isinstance(days, int) or not 30 <= days <= 400:
        raise CityError(f"{where}: launch.launch_days must be a whole number of days, 30 to 400")
    earliest = None                                  # UNVERIFIED: launch year only, no backfill until it is known
    if not is_unverified(launch.get("earliest")):
        try:
            earliest = date.fromisoformat(str(launch.get("earliest")))
        except ValueError as exc:
            raise CityError(f"{where}: launch.earliest must be YYYY-MM-DD or UNVERIFIED") from exc
        if earliest > date.today():
            raise CityError(f"{where}: launch.earliest {earliest} is in the future")
    return {**launch, "launch_days": days, "earliest": earliest}


def _check_source_hosts(city: dict, root: Path, where: str) -> None:
    """Every host a reader says it will ask is on the city's allowlist, and a source file's own launch settings
    (legistar.yml launch_days, earliest) equal the city's launch block."""
    for s in city["sources"]:
        if not s.get("config"):
            continue
        p = root / s["config"]
        try:
            hosts = s["reader"].hosts(p)
        except ValueError:
            hosts = ()                                        # a draft config that doesn't load yet: `check` says so
        denied = [h for h in hosts + s["reader"].link_hosts(p) if host_denied(h, city["denied_hosts"])]
        if denied:
            raise CityError(f"{s['config']}: {', '.join(denied)} is a denied host and can never be asked or linked")
        off = [h for h in hosts if not host_matches(h, allowed_hosts(city))]
        if off:
            raise CityError(f"{where}: {s['config']} asks {', '.join(off)}, not in allowed_hosts")
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        theirs = None if is_unverified(data.get("earliest")) else str(data.get("earliest"))
        ours = city["launch"]["earliest"].isoformat() if city["launch"] and city["launch"]["earliest"] else None
        if city["launch"] and "launch_days" in data and (data["launch_days"] != city["launch"]["launch_days"]
                                                         or theirs != ours):
            raise CityError(f"{s['config']}: launch_days/earliest differ from {where} launch")


def _check_go_ahead(city: dict, where: str) -> None:
    """The owner's go-ahead to go live, recorded as go_ahead: {date, by}. Required for every live city, launch
    block or not; only Clarksville, live before the template, has none."""
    g = city.get("go_ahead")
    if g is None:
        if city["status"] == "live" and city["slug"] != LOCAL_READER_CITY:
            raise CityError(f"{where}: status live needs go_ahead: {{date: YYYY-MM-DD, by: ...}}, the owner's "
                            "go-ahead to go live")
        return
    try:
        ok = (isinstance(g, dict) and isinstance(g.get("by"), str) and g["by"].strip()
              and date.fromisoformat(str(g.get("date"))) <= date.today())
    except ValueError:
        ok = False
    if not ok:
        raise CityError(f"{where}: go_ahead is {{date: YYYY-MM-DD (not in the future), by: who gave it}}")


def _check_platform_facts(city: dict, root: Path, where: str) -> None:
    if not (root / city["platform_facts"]).is_file():
        raise CityError(f"{where}: platform_facts {city['platform_facts']} not found")
