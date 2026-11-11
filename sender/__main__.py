"""`python -m sender plan` and `python -m sender deliver` (architecture "T4 sender").

    python -m sender plan [--date D] [--site build/site] [--out build/morning-send] [--rehearse]
    python -m sender deliver --plan build/morning-send/<D>/plan.json [--config config/site.yml]

`plan` is the dry run: no connection, no secret. `deliver` here only describes what a live run would do: this
build has no provider adapter, so `--live` is refused and nothing can be sent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _plan(args) -> int:
    from datetime import date

    from sitegen import config, morning

    from . import plan as plan_mod
    from . import settings
    cfg = config.SITE
    # settings-parity: what this job loaded with PyYAML must be what the deliver job reads without it
    problems = morning.problems(cfg) + settings.parity(config.SITE_CONFIG_PATH.read_text(encoding="utf-8"), cfg)
    if problems or not plan_mod.sender_settings(cfg):
        for p in problems or ["config/site.yml has no morning_note.sender block"]:
            print(f"sender plan: {p}", file=sys.stderr)
        return 2
    try:
        day = date.fromisoformat(args.date) if args.date else plan_mod.today(cfg)
    except ValueError:
        print(f"sender plan: --date must be YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
        return 2
    try:
        built = plan_mod.build(Path(args.site), day, cfg, rehearse=args.rehearse)
    except plan_mod.PlanError as exc:
        print(f"sender plan: {exc}", file=sys.stderr)
        if not plan_mod.enabled(cfg):
            # the sender is off, so this was the rehearsal: it must never fail the daily site job
            print("sender plan: the sender is disabled, so this was a rehearsal; nothing written, not failing the run",
                  file=sys.stderr)
            # an Actions annotation so it is seen; fixed text only, never the error's (it may quote the note)
            print("::warning title=Morning note rehearsal::the sender plan failed while the sender is disabled; "
                  "see the step log", file=sys.stderr)
            return 0
        return 2
    path = plan_mod.write(Path(args.out), built)
    p = built["plan"]
    print(f"morning note plan {p['date']}: send {'true' if p['send'] else 'false'} ({p['reason']}); "
          f"{len(p['editions'])} edition(s); {len(p['signatures'])} subscriber shape(s); wrote {path}")
    return 0


def _canary_from_env():
    """The canary subscriber ids, from the note job's environment only (deliver.CANARY_ENV); None when unset."""
    import os

    from . import deliver
    return deliver.canary_ids(os.environ.get(deliver.CANARY_ENV))


def _deliver(args) -> int:
    from . import deliver, settings
    if args.live:
        print("sender deliver: this build has no provider adapter, so --live is refused; nothing sent",
              file=sys.stderr)
        return 2
    try:
        cfg = settings.load(args.config)
    except settings.SettingsError as exc:
        print(f"sender deliver: {exc}; nothing sent", file=sys.stderr)
        return 2
    from . import common
    try:
        if Path(args.plan).stat().st_size > common.MAX_PLAN_BYTES:
            print(f"sender deliver: the plan file is over MAX_PLAN_BYTES ({common.MAX_PLAN_BYTES}); nothing sent",
                  file=sys.stderr)
            return 2
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        print("sender deliver: the plan file cannot be read; nothing sent", file=sys.stderr)
        return 2
    try:
        canary = _canary_from_env()
    except deliver.PlanInvalid as exc:
        print(f"sender deliver: {exc}; nothing sent", file=sys.stderr)
        return 2
    return deliver.run(plan, cfg, provider=None, live=False, canary_ids=canary).code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sender", description="The morning note's sender (dry run only).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="write the would-send payloads for one day (no connection, no secret)")
    p.add_argument("--date", help="the note's day, YYYY-MM-DD (default: today in site_timezone)")
    p.add_argument("--site", default="build/site", help="the built site (holds morning/<date>.json)")
    p.add_argument("--out", default="build/morning-send", help="where <date>/plan.json is written")
    p.add_argument("--rehearse", action="store_true",
                   help="write the editions even while the sender is disabled; the plan still says send false")
    p.set_defaults(fn=_plan)
    d = sub.add_parser("deliver", help="describe what a live run would do with a plan (opens no connection)")
    d.add_argument("--plan", required=True, help="plan.json from the plan stage")
    d.add_argument("--config", default="config/site.yml")
    d.add_argument("--live", action="store_true", help="refused in this build: there is no provider adapter")
    d.set_defaults(fn=_deliver)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
