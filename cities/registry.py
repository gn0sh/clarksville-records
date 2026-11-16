"""The city registry: config/cities/<slug>/city.yml, one per city, loaded and checked here.

A city file holds who and where the city is, its sources (portal type + config file), the hosts its collection may
ask (each with its robots.txt and terms check), its launch plan and its site settings. Brand keys are locked
(cities/brand.py). Clarksville's file points at today's files (config/site.yml, config/localities/...) instead of
copying them, so its live build is unchanged. Nothing here fetches anything.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from collector.fetch import ALLOWED_HOSTS as _GLOBAL_ALLOWED  # noqa: F401  (tests compare Clarksville to it)
from collector.fetch import DENIED_HOSTS, host_matches

from . import brand as brand_mod
from .errors import CityError
from .readers import READERS

ROOT = Path(__file__).resolve().parent.parent
CITIES_DIR = ROOT / "config" / "cities"
UNVERIFIED = "UNVERIFIED"
STATUSES = ("draft", "live")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-([a-z]{2})$")       # <place>-<state>, e.g. salem-or
STATE_RE = re.compile(r"^[A-Z]{2}$")
HOST_RE = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$")
DOMAIN_RE = re.compile(r"^(?:[a-z0-9-]+\.)?daylight\.gnoshcodes\.com$")
# Site settings a city sets (top level of city.yml) -> the config/site.yml key the site build reads.
SITE_FIELDS = {"sky_place": "sky_place", "geocoder_places": "geocoder_places"}
KEYS = {"slug", "name", "state", "timezone", "status", "domain", "settings", "platform_facts", "sources",
        "allowed_hosts", "denied_hosts", "launch", "sky_place", "district_lookup", "geocoder_places",
        "verification_notes", "site"}
REQUIRED = ("slug", "name", "state", "timezone", "status", "domain", "platform_facts", "sources", "allowed_hosts")
FROM_SETTINGS = ("sky_place", "district_lookup", "geocoder_places")   # read from a legacy settings file instead


def is_unverified(value) -> bool:
    return isinstance(value, str) and value.strip().startswith(UNVERIFIED)


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
    city["denied_hosts"] = tuple(DENIED_HOSTS) + tuple(str(h).lower() for h in city.get("denied_hosts") or ())
    city["launch"] = _launch(city.get("launch"), where)
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
    return not host_matches(host, city["denied_hosts"]) and host_matches(host, allowed_hosts(city))


def site_settings(city: dict, brand: dict) -> dict:
    """The city's site settings with the shared brand laid over them (brand keys locked)."""
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
    m = SLUG_RE.match(str(city["slug"]))
    if city["slug"] != slug or not m:
        raise CityError(f"{where}: slug must be the folder name, written <place>-<state> (e.g. salem-or)")
    if not STATE_RE.match(str(city["state"])) or m.group(1) != str(city["state"]).lower():
        raise CityError(f"{where}: state must be the two-letter code the slug ends with, in capitals")
    if city["status"] not in STATUSES:
        raise CityError(f"{where}: status must be one of {', '.join(STATUSES)}")
    if not is_unverified(city["timezone"]):
        try:
            ZoneInfo(str(city["timezone"]))
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise CityError(f"{where}: timezone {city['timezone']!r} is not an IANA zone (e.g. America/Chicago)") \
                from exc
    if not DOMAIN_RE.match(str(city["domain"])):
        raise CityError(f"{where}: domain must be daylight.gnoshcodes.com or <name>.daylight.gnoshcodes.com")


def _settings(city: dict, root: Path, brand: dict, where: str) -> dict:
    """Legacy (Clarksville): the settings file it points at, whose brand duplicates must equal config/brand.yml and
    whose time zone must equal the city's. New cities: built from city.yml's own fields and `site:` block."""
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
    site = dict(city.get("site") or {})
    site.update({"site_timezone": city["timezone"], "today_place": city["name"]})
    for k, sk in SITE_FIELDS.items():
        if k in city:
            site[sk] = city[k]
    lookup = city.get("district_lookup") or {}
    if is_unverified(lookup):
        lookup = {}
    elif lookup and not (isinstance(lookup, dict) and isinstance(lookup.get("url"), str)
                         and lookup["url"].startswith("https://") and isinstance(lookup.get("label"), str)):
        raise CityError(f"{where}: district_lookup is {{url: https://..., label: ...}}")
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
        if not HOST_RE.match(host):
            raise CityError(f"{where}: allowed_hosts[{i}] {host!r} is not a host name")
        denied = tuple(DENIED_HOSTS) + tuple(str(d).lower() for d in city.get("denied_hosts") or ())
        if host_matches(host, denied):
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
        off = [h for h in hosts if not host_matches(h, allowed_hosts(city))]
        if off:
            raise CityError(f"{where}: {s['config']} asks {', '.join(off)}, not in allowed_hosts")
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        theirs = None if is_unverified(data.get("earliest")) else str(data.get("earliest"))
        ours = city["launch"]["earliest"].isoformat() if city["launch"] and city["launch"]["earliest"] else None
        if city["launch"] and "launch_days" in data and (data["launch_days"] != city["launch"]["launch_days"]
                                                         or theirs != ours):
            raise CityError(f"{s['config']}: launch_days/earliest differ from {where} launch")


def _check_platform_facts(city: dict, root: Path, where: str) -> None:
    if not (root / city["platform_facts"]).is_file():
        raise CityError(f"{where}: platform_facts {city['platform_facts']} not found")
