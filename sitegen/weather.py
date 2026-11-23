"""The weather in the header's sky (static/sky.js): config/site.yml `sky_weather`.

On while the config names both `sky_place` and `sky_weather`: every page with the sky place then carries the one
address its script may ask (data-weather on #sky-moon), and views.csp names that address's origin in connect-src.
The script asks from the visitor's browser, once per page view, for the latest observation of one weather station,
and draws a scene only from a fresh answer. Off (either block absent): no attribute, no origin, no request.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from . import config

KEYS = {"station", "url", "disclosure"}
STATION = re.compile(r"[A-Z][A-Z0-9]{3}")             # an ICAO station id, as the National Weather Service lists it
HOST = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")


def _url(w: dict) -> str | None:
    """The observation address: `url` with {station} filled in, or None when it is not a plain https address."""
    url, station = w.get("url"), w.get("station")
    if not isinstance(url, str) or not isinstance(station, str) or "{station}" not in url:
        return None
    full = url.replace("{station}", station)
    try:
        u = urlsplit(full)
        port = u.port
    except ValueError:
        return None
    if u.scheme != "https" or not HOST.fullmatch(u.netloc) or port or u.query or u.fragment:
        return None
    if not u.path.startswith("/") or re.search(r"[^A-Za-z0-9/._~-]", u.path):   # nothing to escape in the page
        return None
    return full


def problems(cfg: dict | None = None) -> list[str]:
    """What is wrong with config/site.yml `sky_weather` (the build refuses to run on any)."""
    cfg = config.SITE if cfg is None else cfg
    w = cfg.get("sky_weather")
    if w is None:
        return []
    if not isinstance(w, dict):
        return ["sky_weather must be a mapping {station, url, disclosure}"]
    out = []
    if set(w) - KEYS:
        out.append(f"sky_weather: unknown keys {sorted(set(w) - KEYS)}")
    if not isinstance(w.get("station"), str) or not STATION.fullmatch(w["station"]):
        out.append(f"sky_weather.station must be a four-character station id such as KCKV, got {w.get('station')!r}")
    elif _url(w) is None:
        out.append("sky_weather.url must be a plain https address with {station} in its path, got "
                   f"{w.get('url')!r}")
    d = w.get("disclosure")
    if not isinstance(d, str) or not d.strip():
        out.append("sky_weather.disclosure must say what is asked, in a sentence for the About and Method pages")
    return out


def settings(cfg: dict | None = None) -> dict | None:
    """The header's weather for this build, or None (no sky_place, no sky_weather, or a bad block). Call problems()
    first. `origin` is what the CSP's connect-src names; `url` is the one address the script asks."""
    cfg = config.SITE if cfg is None else cfg
    w = cfg.get("sky_weather")
    if not cfg.get("sky_place") or not isinstance(w, dict) or problems(cfg):
        return None
    url = _url(w)
    u = urlsplit(url)
    return {"station": w["station"], "url": url, "origin": f"{u.scheme}://{u.netloc}",
            "disclosure": " ".join(w["disclosure"].split())}


def origin(cfg: dict | None = None) -> str | None:
    """The one origin connect-src gains on pages with the sky place, or None while the weather is off."""
    s = settings(cfg)
    return s["origin"] if s else None
