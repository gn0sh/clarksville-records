"""`python -m sender plan` and `python -m sender deliver` (architecture "T4 sender").

    python -m sender plan [--date D] [--site build/site] [--out build/morning-send] [--rehearse]
    python -m sender deliver --plan build/morning-send/<D>/plan.json [--config config/site.yml] [--live]

`plan` is the dry run: no connection, no secret. `deliver` describes what a live run would do and opens no
connection, unless `--live` is passed and `morning_note.sender.enabled` is true in the config. Then the provider key
must be in the environment (`BUTTONDOWN_API_KEY`): missing or malformed, the command exits 2 with a fixed message
(never the value). Only a live run imports the provider adapter (sender/buttondown.py, the one module that opens a
connection).
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


KEY_ENV = "BUTTONDOWN_API_KEY"     # buttondown.KEY_ENV (a test keeps them equal); named here so a dry run never
                                    # imports the adapter


class MissingKey(Exception):
    """--live with the sender enabled but no key in the environment."""


def _live_provider(args, cfg):
    """(provider, stamp_secret) when this run is live; (None, None) for a dry run (no --live, or --live with the
    sender disabled in the repository's config, which says so on stderr). With --live and the sender enabled, a
    missing key raises MissingKey and a malformed one ValueError: the command then fails, it never dry-runs."""
    import os
    if not args.live:
        return None, None
    if cfg.enabled:
        key = os.environ.get(KEY_ENV)
        if not key:
            # a forgotten secret at go-live must fail the job, never pass as a dry run
            raise MissingKey()
        from . import buttondown
        # the key is the stamps' HMAC secret too (architecture "As built": the stamp is unguessable)
        return buttondown.Buttondown(key, api_base=cfg.api_base), key.encode("utf-8")
    print("sender deliver: --live was passed but morning_note.sender.enabled is false in the config, so this is a "
          "dry run; nothing sent", file=sys.stderr)
    # fixed text: the key, an id or an address is never in it
    print("::warning title=Morning note::--live was given but the run was a dry run; see the step log",
          file=sys.stderr)
    return None, None


def _deliver(args) -> int:
    from . import deliver, settings
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
    try:
        provider, secret = _live_provider(args, cfg)
    except MissingKey:
        print(f"sender deliver: --live with the sender enabled, but {KEY_ENV} is not set; nothing sent",
              file=sys.stderr)
        return 2
    except Exception:       # noqa: BLE001  a bad key or base: the text could quote the key, so it is never printed
        print(f"sender deliver: --live with the sender enabled, but {KEY_ENV} is not a usable key (or api_base is "
              "wrong); nothing sent", file=sys.stderr)
        return 2
    return deliver.run(plan, cfg, provider=provider, live=provider is not None, canary_ids=canary,
                       stamp_secret=secret).code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sender", description="The morning note's sender.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="write the would-send payloads for one day (no connection, no secret)")
    p.add_argument("--date", help="the note's day, YYYY-MM-DD (default: today in site_timezone)")
    p.add_argument("--site", default="build/site", help="the built site (holds morning/<date>.json)")
    p.add_argument("--out", default="build/morning-send", help="where <date>/plan.json is written")
    p.add_argument("--rehearse", action="store_true",
                   help="write the editions even while the sender is disabled; the plan still says send false")
    p.set_defaults(fn=_plan)
    d = sub.add_parser("deliver", help="send a plan's editions (only with --live, sender.enabled and the key); "
                                       "otherwise describe what a live run would do and open no connection")
    d.add_argument("--plan", required=True, help="plan.json from the plan stage")
    d.add_argument("--config", default="config/site.yml")
    d.add_argument("--live", action="store_true",
                   help=f"send for real (needs {KEY_ENV}); a dry run while sender.enabled is false")
    d.set_defaults(fn=_deliver)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
