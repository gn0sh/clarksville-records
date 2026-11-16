"""`python -m cities new`: a draft city folder from cities/templates, every unchecked value marked UNVERIFIED.

Writes config/cities/<slug>/city.yml, the portal's source file (when the portal has one) and platform-facts.md, then
loads the result with the registry's own checks. Fetches nothing."""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path
from string import Template
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import CityError
from .readers import READERS
from .registry import ROOT, SLUG_RE, STATE_RE, city_dir, load_city

TEMPLATES = Path(__file__).resolve().parent / "templates"
PORTAL_HOSTS = {"legistar": ("webapi.legistar.com",)}     # hosts known from the portal type alone (no city part)


def _render(template: str, **values) -> str:
    return Template((TEMPLATES / template).read_text(encoding="utf-8")).substitute(**values)


def new_city(slug: str, name: str, state: str, portal: str, tz: str, root: Path = ROOT,
             today: date | None = None) -> list[Path]:
    m = SLUG_RE.match(slug)
    if not m:
        raise CityError(f"slug {slug!r}: write it <place>-<state> in lowercase, e.g. salem-or")
    if not STATE_RE.match(state) or m.group(1) != state.lower():
        raise CityError(f"state {state!r}: the two-letter code in capitals, matching the slug's ending")
    if portal not in READERS:
        raise CityError(f"portal {portal!r} is unknown (known: {', '.join(sorted(READERS))})")
    if not READERS[portal].shared and READERS[portal].built:
        raise CityError(f"portal {portal!r} is a Clarksville-only reader; it can't serve another city yet")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CityError(f"--tz {tz!r} is not an IANA time zone (e.g. America/Los_Angeles)") from exc
    if not name.strip():
        raise CityError("--name is empty")
    folder = city_dir(slug, root)
    if folder.exists():
        raise CityError(f"{folder.relative_to(root)} already exists; nothing written")
    today = today or date.today()
    reader = READERS[portal]
    src_tmpl = f"{portal}.yml.tmpl"
    has_src = (TEMPLATES / src_tmpl).is_file()
    src_rel = f"config/cities/{slug}/{portal}.yml"
    hosts = PORTAL_HOSTS.get(portal, ())
    values = dict(slug=slug, name=name.strip(), state=state, tz=tz, portal=portal, today=today.isoformat(),
                  domain=f"{slug[:-3]}.daylight.gnoshcodes.com", reader_label=reader.label)
    values["source_line"] = f"{{portal: {portal}, config: {src_rel}}}" if has_src else f"{{portal: {portal}}}"
    values["hosts"] = "\n".join(f"  - host: {h}\n    robots: UNVERIFIED\n    terms: UNVERIFIED" for h in hosts) \
        or "  []                             # none known yet"
    values["host_rows"] = "\n".join(f"| {h} | not checked | not checked | |" for h in hosts) \
        or "| (none listed yet) | | | |"
    folder.mkdir(parents=True)
    written = []
    try:
        for fname, tmpl in [("city.yml", "city.yml.tmpl"), ("platform-facts.md", "platform-facts.md.tmpl")] + (
                [(f"{portal}.yml", src_tmpl)] if has_src else []):
            p = folder / fname
            p.write_text(_render(tmpl, **values), encoding="utf-8")
            written.append(p)
        load_city(slug, root)
    except Exception:
        shutil.rmtree(folder)                      # only the folder this call just made
        raise
    return written
