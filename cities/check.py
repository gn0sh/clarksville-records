"""`python -m cities check <slug>`: a plain checklist of what a city still needs before launch, then READY or NOT READY.

It reads files only. It never fetches robots.txt, terms or anything else: a person checks those and records them in
the city's files (docs/expansion/add-a-city.md)."""
from __future__ import annotations

import re
from pathlib import Path

from . import brand as brand_mod
from .errors import CityError
from .registry import ROOT, UNVERIFIED, is_unverified, load_city

HOST_LINE = re.compile(r"^\s*(robots|terms):")


def _marks(path: Path, root: Path, skip_host_lines: bool) -> tuple[list[str], list[str]]:
    """(missing, to verify) from a file's UNVERIFIED marks: a mark in the value is a missing value; a mark only in the
    comment is a value set but not yet checked against a real source."""
    missing, verify = [], []
    rel = path.relative_to(root)
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if UNVERIFIED not in line or (skip_host_lines and HOST_LINE.match(line)):
            continue
        value = "" if line.lstrip().startswith("#") else line.partition(" #")[0]
        text = f"{rel} line {n}: {line.strip()}"
        (missing if UNVERIFIED in value else verify).append(text)
    return missing, verify


def checklist(slug: str, root: Path = ROOT) -> tuple[list[tuple[bool, str]], bool]:
    """[(done, line)], ready. Raises CityError when the city file itself is invalid."""
    city = load_city(slug, root)
    items: list[tuple[bool, str]] = []
    brand = brand_mod.load_brand(root / "config" / "brand.yml")
    items.append((True, f"brand: {brand['site_name']} by {brand['operator']}; Buy Me a Coffee {brand['support_url']} "
                        "(shared, locked)"))
    items.append((True, f"platform facts: {city['platform_facts']}"))
    files = [(city["_path"], True)] + [(root / s["config"], False) for s in city["sources"] if s.get("config")]
    for path, is_city in files:
        missing, verify = _marks(path, root, skip_host_lines=is_city)
        items += [(False, f"missing: {t}") for t in missing] + [(False, f"UNVERIFIED: {t}") for t in verify]
    if not city["allowed_hosts"]:
        items.append((False, "hosts: none listed yet (add every host collection will ask to allowed_hosts)"))
    for h in city["allowed_hosts"]:
        for k, what in (("robots", "robots.txt"), ("terms", "terms of use")):
            ok = not is_unverified(h[k])
            items.append((ok, f"host {h['host']}: {what} {'checked: ' + h[k] if ok else 'not checked'}"))
    for s in city["sources"]:
        r, name = s["reader"], f"source {s['portal']}" + (f" ({s['config']})" if s.get("config") else "")
        if not r.built:
            items.append((False, f"{name}: the {r.label} reader is not built yet ({r.note})"))
            continue
        scope = "shared reader" if r.shared else "Clarksville-only reader"
        if s.get("config") and r.loader:
            try:
                r.load(root / s["config"])
                items.append((True, f"{name}: {scope} built; config loads"))
            except Exception as exc:                      # the reader's own message, shown as is
                items.append((False, f"{name}: {scope} built; config does not load yet: {exc}"))
        else:
            items.append((True, f"{name}: {scope} built ({r.note})" if r.note else f"{name}: {scope} built"))
    if city["launch"]:
        e = city["launch"]["earliest"]
        items.append((True, f"launch: last {city['launch']['launch_days']} days, then one older year per run back "
                            f"to {e.isoformat() if e else 'an earliest date not yet known (launch year only)'}"))
    else:
        items.append((True, "launch: no backfill plan (history collected by its own pipeline)"))
    return items, all(done for done, _ in items)


def render(slug: str, root: Path = ROOT) -> tuple[str, int]:
    try:
        items, ready = checklist(slug, root)
    except CityError as exc:
        return f"{slug}: city file is invalid: {exc}\nNOT READY", 2
    city = load_city(slug, root)
    todo = sum(1 for done, _ in items if not done)
    lines = [f"{city['name']}, {city['state']} ({slug}): {city['status']}, {city['domain']}"]
    lines += [f"  [{'x' if done else ' '}] {text}" for done, text in items]
    lines.append("READY" if ready else f"NOT READY: {todo} item{'s' if todo != 1 else ''} to do")
    return "\n".join(lines), 0 if ready else 1
