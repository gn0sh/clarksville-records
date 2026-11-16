"""The shared brand (config/brand.yml): every key is locked, so no city can change or switch it off.

The Buy Me a Coffee link and its switch are pinned here as well: the brand file may not change them either, so a
change takes a reviewed code change (docs/adr/0007-multi-city-template.md)."""
from __future__ import annotations

from pathlib import Path

import yaml

from .errors import CityError

ROOT = Path(__file__).resolve().parent.parent
BRAND_PATH = ROOT / "config" / "brand.yml"
BMAC_URL = "https://buymeacoffee.com/gnoshcodes"      # one link for every city (no www)
# Dotted paths of the locked keys, in the shape config/site.yml uses.
LOCKED = ("site_name", "operator", "operator_url", "support_url", "support_label", "support_line", "support_enabled",
          "corrections.email")


def get(d: dict, dotted: str, default=None):
    for part in dotted.split("."):
        if not isinstance(d, dict) or part not in d:
            return default
        d = d[part]
    return d


_MISSING = object()


def load_brand(path: str | Path = BRAND_PATH) -> dict:
    """Read and check config/brand.yml: every locked key set, the coffee link exactly BMAC_URL and switched on."""
    brand = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    missing = [k for k in LOCKED if get(brand, k, _MISSING) is _MISSING]
    if missing:
        raise CityError(f"{path}: missing brand keys {', '.join(missing)}")
    extra = sorted(set(brand) - {k.split(".")[0] for k in LOCKED})
    if extra:
        raise CityError(f"{path}: unknown brand keys {', '.join(extra)} (a city setting belongs in its city.yml)")
    if brand["support_url"] != BMAC_URL:
        raise CityError(f"{path}: support_url must be {BMAC_URL} (the one Buy Me a Coffee link for every city)")
    if brand["support_enabled"] is not True:
        raise CityError(f"{path}: support_enabled must be true (the coffee link is on in every city)")
    for k in LOCKED:
        if k != "support_enabled" and not (isinstance(get(brand, k), str) and get(brand, k).strip()):
            raise CityError(f"{path}: {k} must be non-empty text")
    return brand


def locked_keys_set(settings: dict) -> list[str]:
    """The locked brand keys a city's settings try to set (any value, even the same one)."""
    return [k for k in LOCKED if get(settings, k, _MISSING) is not _MISSING]


def refuse(clash: list[str], where: str) -> None:
    if clash:
        raise CityError(f"{where}: {', '.join(clash)} {'is a' if len(clash) == 1 else 'are'} shared brand "
                        f"setting{'s' if len(clash) > 1 else ''}, set once in config/brand.yml for every city. "
                        "Remove it from the city's file.")


def merge(brand: dict, settings: dict, where: str) -> dict:
    """A city's site settings with the brand laid over them. A city that sets a locked key fails, naming the key."""
    refuse(locked_keys_set(settings), where)
    out = {**settings, **{k: v for k, v in brand.items() if k != "corrections"}}
    out["corrections"] = {**(settings.get("corrections") or {}), **brand["corrections"]}
    return out


def drift(brand: dict, site: dict) -> list[str]:
    """Locked keys whose value in a legacy settings file (Clarksville's config/site.yml) differs from the brand."""
    return [k for k in LOCKED if get(site, k, _MISSING) != get(brand, k)]
