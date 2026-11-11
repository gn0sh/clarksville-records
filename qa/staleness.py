"""Data-age check (launch Brain Trust, "No freshness line or data-age check"; config/staleness.yml).

Two commands, both run by the daily workflow after a green run (never blocking publishing):

    python -m qa.staleness check  --data data --out build/staleness.json
    python -m qa.staleness issues --report build/staleness.json

`check` reads the committed data files (no network), finds each source's newest date with the same rules as the site's
"How recent the records are" line (sitegen/freshness.py), and writes one row per source: newest date, age in days,
threshold, stale or not. `issues` keeps one open GitHub issue per stale source (label from the config, title
"<prefix> <name> [<key>]"): it creates the issue once, then only edits its body; it closes the issue with a comment
when the source is fresh again, and reopens the latest closed one if it goes stale again. It calls `gh` with
argument lists (no shell) and fixed text built from our own data.

Exit codes: 0 for a finished check or issue pass (staleness is a signal, not a gate); 1 when any gh call failed (the
label included); 2 for a bad config, an unreadable report or issues that could not be listed. A non-zero exit fails
the (continue-on-error) step, and the workflow then opens one 'Daily update: data-age check broken' issue.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "staleness.yml"
SITE = ROOT / "config" / "site.yml"

FILES = {
    "county": "facts.json",
    "county_agendas": "county-agendas/agendas.json",
    "city": "localities/clarksville-tn/facts.json",
    "rpc": "localities/cmc-rpc/rpc.json",
    "finance": "finance.json",
}
KEYS = ("county-agendas", "county-minutes", "city-agendas", "city-minutes", "rpc-agendas", "rpc-minutes",
        "finance-bids", "finance-budget")


class ConfigError(ValueError):
    pass


# ---- newest dates (mirrors sitegen/freshness.py) --------------------------------------------------------------------

def _max_date(values) -> str | None:
    ds = [v for v in values if isinstance(v, str) and len(v) >= 10]
    return max(v[:10] for v in ds) if ds else None


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def newest_dates(data_dir: Path) -> dict:
    """{key: newest ISO date or None}; finance-budget is the newest approved fiscal year (int) or None. A missing or
    unreadable file gives None for its sources (counted as stale: no dated record)."""
    out: dict = {k: None for k in KEYS}
    county = _load(data_dir / FILES["county"])
    if county:
        out["county-minutes"] = _max_date(m.get("date") for m in county.get("meetings") or [])
    ag = _load(data_dir / FILES["county_agendas"])
    if ag:
        paged = {s.get("id") for s in ag.get("sources") or [] if s.get("pages")}   # as the agenda pages show them
        out["county-agendas"] = _max_date(m.get("date") for m in ag.get("meetings") or [] if m.get("source_id") in paged)
    city = _load(data_dir / FILES["city"])
    if city:
        kinds = {s.get("id"): s.get("kind") for s in city.get("sources") or []}
        ms = city.get("meetings") or []
        out["city-minutes"] = _max_date(m.get("date") for m in ms if kinds.get(m.get("source_id")) == "minutes")
        out["city-agendas"] = _max_date(m.get("date") for m in ms
                                        if m.get("agenda_source_id") or kinds.get(m.get("source_id")) == "agenda")
    rpc = _load(data_dir / FILES["rpc"])
    if rpc:
        ms = rpc.get("meetings") or []
        out["rpc-minutes"] = _max_date(m.get("date") for m in ms if m.get("minutes_source_id"))
        out["rpc-agendas"] = _max_date(m.get("date") for m in ms if m.get("agenda_source_id"))
    fin = _load(data_dir / FILES["finance"])
    if fin:
        out["finance-bids"] = _max_date(s.get("archive_date") for s in fin.get("solicitations") or [])
        fys = [b["fiscal_year"] for b in fin.get("books") or []
               if isinstance(b.get("fiscal_year"), int) and b.get("edition") == "approved"]
        out["finance-budget"] = max(fys) if fys else None
    return out


# ---- the check ----------------------------------------------------------------------------------------------------

def load_config(path: Path = CONFIG) -> dict:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(cfg.get("label"), str) or not cfg["label"] or not isinstance(cfg.get("title_prefix"), str):
        raise ConfigError("staleness config needs a label and a title_prefix")
    srcs = cfg.get("sources")
    if not isinstance(srcs, dict) or set(srcs) - set(KEYS):
        raise ConfigError(f"staleness sources must be among {KEYS}")
    for key, s in srcs.items():
        if not isinstance(s, dict) or not isinstance(s.get("name"), str) or "[" in s["name"]:
            raise ConfigError(f"{key}: a name without '[' is required")
        field = "grace_days" if key == "finance-budget" else "max_age_days"
        n = s.get(field)
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise ConfigError(f"{key}: {field} must be a positive whole number of days")
    return cfg


def fiscal_year(day: date) -> int:
    """The county fiscal year runs July 1 to June 30 and is named for the year it ends."""
    return day.year + 1 if day.month >= 7 else day.year


def check(newest: dict, cfg: dict, today: date) -> list[dict]:
    rows = []
    for key, s in cfg["sources"].items():
        n = newest.get(key)
        row = {"key": key, "name": s["name"], "newest": n}
        if key == "finance-budget":
            fy = fiscal_year(today)
            began = date(fy - 1, 7, 1)
            due = (today - began).days >= s["grace_days"]
            row.update(threshold_days=s["grace_days"], current_fiscal_year=fy, age_days=None,
                       stale=n is None or (n < fy and due))
        else:
            age = (today - date.fromisoformat(n)).days if n else None
            row.update(threshold_days=s["max_age_days"], age_days=age, stale=age is None or age > s["max_age_days"])
        rows.append(row)
    return rows


def today_local() -> date:
    tz = (yaml.safe_load(SITE.read_text(encoding="utf-8")) or {}).get("site_timezone") or "UTC"
    return datetime.now(ZoneInfo(tz)).date()


# ---- issues ---------------------------------------------------------------------------------------------------------

def title(cfg: dict, row: dict) -> str:
    return f"{cfg['title_prefix']} {row['name']} [{row['key']}]"


def body(row: dict, today: date, run_url: str) -> str:
    if row["key"] == "finance-budget":
        have = f"fiscal year {row['newest']}" if row["newest"] else "none"
        what = (f"The newest approved budget book is {have}; fiscal year {row['current_fiscal_year']} began July 1 and "
                f"its book is still missing {row['threshold_days']} or more days later.")
    elif row["newest"]:
        what = (f"Newest record: {row['newest']}, {row['age_days']} days old on {today.isoformat()} "
                f"(threshold {row['threshold_days']} days).")
    else:
        what = "No dated record was found for this source."
    return "\n".join([
        f"**{row['name']}** (`{row['key']}`) is stale. {what}",
        "",
        "The site keeps publishing; its \"How recent the records are\" line shows the date above as it is.",
        "What to do: docs/ops/launch-runbook.md, \"Paused sources\". Thresholds: config/staleness.yml.",
        "",
        f"Updated by the daily run: {run_url}" if run_url else "Updated by the daily run.",
        "This issue is edited each day, never duplicated, and closed by the first run that finds the source fresh.",
    ])


def _key(cfg: dict, t: str) -> str | None:
    """The source key of an issue title "<prefix> ... [<key>]", else None."""
    if t.startswith(cfg["title_prefix"]) and t.endswith("]") and "[" in t:
        return t[t.rindex("[") + 1:-1]
    return None


def plan(rows: list[dict], open_issues: list[dict], cfg: dict, today: date, run_url: str = "",
         closed_issues: list[dict] = ()) -> list[tuple]:
    """Actions, in order: ("create", title, body), ("reopen", number, body), ("edit", number, body),
    ("close", number, comment).
    An issue belongs to a source when its title starts with the prefix and ends with "[<key>]"; extra open issues for
    the same key (made by hand) are edited too, never closed for that reason alone. A source stale again reopens its
    most recently closed issue instead of opening a new one (ci/stale-issue-flap-noise)."""
    by_key: dict[str, list[int]] = {}
    for i in open_issues:
        k = _key(cfg, i.get("title") or "")
        if k:
            by_key.setdefault(k, []).append(int(i["number"]))
    last_closed: dict[str, tuple] = {}
    for i in closed_issues:
        k = _key(cfg, i.get("title") or "")
        if k:
            rank = (i.get("closedAt") or "", int(i["number"]))
            if k not in last_closed or rank > last_closed[k]:
                last_closed[k] = rank
    actions: list[tuple] = []
    for row in rows:
        nums = sorted(by_key.get(row["key"], []))
        if row["stale"]:
            if nums:
                actions += [("edit", n, body(row, today, run_url)) for n in nums]
            elif row["key"] in last_closed:
                actions.append(("reopen", last_closed[row["key"]][1], body(row, today, run_url)))
            else:
                actions.append(("create", title(cfg, row), body(row, today, run_url)))
        else:
            fresh = (f"fiscal year {row['newest']}" if row["key"] == "finance-budget" else row["newest"])
            note = f"Fresh again: newest record {fresh} on {today.isoformat()}. Closed by the daily run."
            if run_url:
                note += f" {run_url}"
            actions += [("close", n, note) for n in nums]
    return actions


def gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def _why(e: Exception) -> str:
    """The error with gh's own stderr (pipeline/stale-check-silent-failure), on one line, capped."""
    err = getattr(e, "stderr", None) or ""
    if isinstance(e, subprocess.CalledProcessError):   # the command's first words only, never the issue body
        cmd = e.cmd if isinstance(e.cmd, list) else [str(e.cmd)]
        head = f"{' '.join(str(c) for c in cmd[:3])} exited {e.returncode}"
    else:
        head = str(e)
    return " ".join(f"{head}: {err}".split())[:500]


def apply(actions: list[tuple], cfg: dict, repo: str, run=None) -> list[str]:
    """Runs each action; one failed call is reported and the rest still run. Returns the failures."""
    run = run or gh
    failed = []
    for kind, ref, text in actions:
        if kind == "create":
            calls = [["issue", "create", "--repo", repo, "--title", ref, "--label", cfg["label"], "--body", text]]
        elif kind == "edit":
            calls = [["issue", "edit", str(ref), "--repo", repo, "--body", text]]
        elif kind == "reopen":
            calls = [["issue", "reopen", str(ref), "--repo", repo, "--comment", "Stale again; reopened by the daily run."],
                     ["issue", "edit", str(ref), "--repo", repo, "--body", text]]
        else:
            calls = [["issue", "close", str(ref), "--repo", repo, "--reason", "completed", "--comment", text]]
        for args in calls:
            try:
                run(args)
            except (subprocess.CalledProcessError, OSError) as e:
                failed.append(f"{kind} {ref}: {_why(e)}")
                break
    return failed


def list_issues(cfg: dict, repo: str, state: str, run=None) -> list[dict]:
    out = (run or gh)(["issue", "list", "--repo", repo, "--state", state, "--label", cfg["label"], "--limit", "200",
               "--json", "number,title" + (",closedAt" if state == "closed" else "")])
    return json.loads(out or "[]")


def ensure_label(cfg: dict, repo: str, run=None) -> str | None:
    """Creates the label once and leaves an existing one as it is. Returns an error text when the label can be neither
    created nor found (every later create would then fail), else None."""
    try:
        (run or gh)(["label", "create", cfg["label"], "--repo", repo, "--color", "d4c5f9",
             "--description", "A source's newest record is older than its threshold (config/staleness.yml)"])
        return None
    except (subprocess.CalledProcessError, OSError) as e:
        if "already exists" in (getattr(e, "stderr", None) or ""):
            return None
        return f"label {cfg['label']}: {_why(e)}"


# ---- CLI ----------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import os
    p = argparse.ArgumentParser(prog="python -m qa.staleness")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--data", type=Path, default=ROOT / "data")
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--today", type=date.fromisoformat, default=None)
    c.add_argument("--config", type=Path, default=CONFIG)
    i = sub.add_parser("issues")
    i.add_argument("--report", type=Path, required=True)
    i.add_argument("--config", type=Path, default=CONFIG)
    a = p.parse_args(argv)
    try:
        cfg = load_config(a.config)
    except (OSError, ValueError, ConfigError) as e:
        print(f"staleness: bad config: {e}", file=sys.stderr)
        return 2
    if a.cmd == "check":
        today = a.today or today_local()
        rows = check(newest_dates(a.data), cfg, today)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps({"today": today.isoformat(), "sources": rows}, indent=1) + "\n", encoding="utf-8")
        for r in rows:
            mark = "STALE" if r["stale"] else "ok   "
            print(f"{mark} {r['key']:15} newest={r['newest']} age={r['age_days']} threshold={r['threshold_days']}")
            if r["stale"]:
                print(f"::warning::Stale source {r['key']}: newest record {r['newest']} (config/staleness.yml)")
        return 0
    try:
        rep = json.loads(a.report.read_text(encoding="utf-8"))
        today, rows = date.fromisoformat(rep["today"]), rep["sources"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"staleness: unreadable report: {e}", file=sys.stderr)
        return 2
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        print("staleness: GITHUB_REPOSITORY is not set", file=sys.stderr)
        return 2
    server = os.environ.get("GITHUB_SERVER_URL", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if server and run_id else ""
    failed = []
    label_err = ensure_label(cfg, repo)
    if label_err:
        failed.append(label_err)
    try:
        current = list_issues(cfg, repo, "open")
        closed = list_issues(cfg, repo, "closed")
    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        print(f"::warning::staleness: could not list issues, nothing changed: {_why(e)}")
        return 2       # never create without knowing what is open (stale-check/no-duplicate-issue)
    actions = plan(rows, current, cfg, today, run_url, closed)
    failed += apply(actions, cfg, repo)
    for kind, ref, _ in actions:
        print(f"{kind} {ref}")
    for f in failed:
        print(f"::warning::staleness issue call failed: {f}")
    return 1 if failed else 0    # a failed call fails the (continue-on-error) step, which opens its own issue


if __name__ == "__main__":
    sys.exit(main())
