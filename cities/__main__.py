"""python -m cities [validate | list [--json] | check <slug> | new <slug> ... | plan --budget N]. Fetches nothing.

Exit codes: 0 fine / READY, 1 NOT READY, 2 an invalid city or brand file (the message names the file and key)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from . import plan as plan_mod
from .check import render
from .errors import CityError
from .registry import load_all
from .scaffold import new_city


def _list(as_json: bool) -> int:
    cities = load_all()
    rows = [{"slug": c["slug"], "name": c["name"], "state": c["state"], "status": c["status"],
             "domain": c["domain"], "url": f"https://{c['domain']}/"} for c in cities]
    if as_json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"{r['slug']:<20} {r['status']:<6} {r['name']}, {r['state']:<3} {r['domain']}")
    return 0


def _plan(budget: int, today: date) -> int:
    cities = load_all()
    states = {c["slug"]: plan_mod.load_state(c["slug"]) for c in cities if c["launch"]}
    p = plan_mod.plan_run(cities, states, today, budget)
    for j in p.jobs:
        w = f" {j.window.start}..{j.window.end}" if j.window else ""
        print(f"run   {j.slug:<20} {j.kind:<8} {j.minutes:>3} min{w}")
    for j in p.skipped:
        print(f"later {j.slug:<20} {j.kind:<8} {j.minutes:>3} min (over budget)")
    print(f"{p.left} of {budget} minutes left. Nothing was run: this only prints the plan.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m cities", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("validate", help="load every city and the brand file (the default)")
    ls = sub.add_parser("list", help="cities with status and domain")
    ls.add_argument("--json", action="store_true")
    ck = sub.add_parser("check", help="a city's launch checklist: READY or NOT READY")
    ck.add_argument("slug")
    nw = sub.add_parser("new", help="a draft city folder, every unchecked value marked UNVERIFIED")
    nw.add_argument("slug")
    nw.add_argument("--name", required=True)
    nw.add_argument("--state", required=True)
    nw.add_argument("--portal", required=True)
    nw.add_argument("--tz", required=True)
    pl = sub.add_parser("plan", help="print one run's plan for the live cities (writes nothing)")
    pl.add_argument("--budget", type=int, required=True, help="minutes shared by every city")
    pl.add_argument("--today", type=date.fromisoformat, default=date.today())
    a = ap.parse_args(argv)
    try:
        if a.cmd == "list":
            return _list(a.json)
        if a.cmd == "check":
            text, code = render(a.slug)
            print(text)
            return code
        if a.cmd == "new":
            for p in new_city(a.slug, a.name, a.state, a.portal, a.tz):
                print(f"wrote {p}")
            print(f"Next: python -m cities check {a.slug}")
            return 0
        if a.cmd == "plan":
            return _plan(a.budget, a.today)
        cities = load_all()
        print(f"{len(cities)} cities valid: {', '.join(c['slug'] for c in cities)}")
        return 0
    except CityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
