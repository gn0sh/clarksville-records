#!/usr/bin/env python3
"""The morning clock report (ADR 0015 decision 8 and "Success signal"): how GitHub's schedule lines and the morning
note did, per site day. Read-only: it lists daily-update.yml's runs on main, their jobs and the arm and note jobs'
logs through `gh api` (your own gh sign-in; this script handles no token itself) and prints what it found.

    python scripts/clock-report.py                  # the last 3 site days, one block each
    python scripts/clock-report.py --days 14        # the last 14
    python scripts/clock-report.py --summary 14     # the S1, S2 and S3 counts over the last 14 site days
    python scripts/clock-report.py --from-json f.json --now "2026-11-28 12:00"    # offline, from saved answers

For each site day (America/Chicago, config/site.yml site_timezone) and each run that started that day:
- a scheduled run's line (from its run name, "Daily update (schedule 37 2 * * *)"), its created time and its lateness
  (created minus the line's last UTC time at or before it; GitHub creates scheduled runs late, never early);
- armed yes or no: the arm job's "send=..." log line, or, when the log can't be read (older runs have no arm job,
  logs expire), derived from the run's start in site time against [cut(D), ARM_UNTIL), where cut(D) is the cut in
  force for the run's site day D (CUTOFF from CUTOFF_FROM on, the legacy 07:00 before it);
- each note job that ran: its route (schedule or dispatch), conclusion, completed time and the deliver status from
  its log ("sent", "claimed", ...);
- on time (a real send whose Deliver step ended by 06:55 site time, emails at 07:00), late, none, or no-send;
- how many runs collected (the update job's "Collect (polite fetch, parse, verify)" step ran).

A delivery is a send only when its deliver line says "sent" with "emails created N" and N > 0 ("sent; emails created
0" on a second run of the same plan is not one).

--summary N (ADR 0015 "Success signal"): S1 days with a real send whose Deliver step ended by 06:55 (days whose only
outcome is "no-send" leave the count and are reported on their own line; disabled, no-canary and wrong-date days
never count as on time); S2 days with an armed schedule run created by 05:00 site time; S3 days with a safety problem
the report can see (two real sends, a delivery "claimed" by a different plan = possible lost records, a note job or
Deliver step finishing after 10:00, a note failed by the route or arm check). S3's other
parts (the alarm fired exactly on days with no note, no record lost or doubled at the cutoff switch) are checked by
hand: the report says so.

--from-json FILE reads {"runs": [run, ...], "jobs": {"<run id>": [job, ...]}, "logs": {"<job id>": "text"}}, the same
objects GitHub's API returns, so a saved day can be read again and the tests run without GitHub.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
REPO = "gn0sh/clarksville-records"
WORKFLOW = "daily-update.yml"
# The arm window, the promise and the send bound. tests/test_clock_report.py keeps these equal to config/site.yml
# (morning_note.cutoff, cutoff_from, sender.latest_send), sitegen.morning.LEGACY_CUTOFF and the arm job's ARM_UNTIL.
CUTOFF = time(0, 0)
CUTOFF_FROM = date(2026, 11, 30)    # T, the switch day
LEGACY_CUTOFF = time(7, 0)
ARM_UNTIL = time(8, 0)
ON_TIME_BY = time(6, 55)        # emails are scheduled for max(send_at 07:00, now + 5 min)
S2_CREATED_BY = time(5, 0)      # a send run that starts by 05:00 ends by about 07:00
LATEST_SEND = time(10, 0)
SCHEDULE_TITLE = re.compile(r"^Daily update \(schedule ([0-9]{1,2}) ([0-9]{1,2}) \* \* \*\)$")
ARM_LOG = re.compile(r"arm window \[[0-9:]+, [0-9:]+\): send=(true|false)\b")
DELIVER_LOG = re.compile(r"morning note ([0-9]{4}-[0-9]{2}-[0-9]{2}): ([a-z-]+)([^\n]*)")
EMAILS_CREATED = re.compile(r"emails created ([0-9]+)")
ROUTE_REFUSAL = "only an armed run may send"
DELIVER_STEP = "Deliver the morning note"
COLLECT_STEP = "Collect (polite fetch, parse, verify)"


def site_zone() -> ZoneInfo:
    """config/site.yml's site_timezone (one plain line; read without PyYAML), else America/Chicago."""
    try:
        text = (ROOT / "config" / "site.yml").read_text(encoding="utf-8")
    except OSError:
        return ZoneInfo("America/Chicago")
    m = re.search(r"^site_timezone:\s*([A-Za-z_/+-]+)", text, re.M)
    return ZoneInfo(m.group(1) if m else "America/Chicago")


def parse_time(value) -> datetime | None:
    """GitHub's "2026-11-28T08:40:12Z" as an aware UTC datetime, or None."""
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def schedule_line(title: str) -> tuple[int, int] | None:
    """(hour, minute) of the cron line a scheduled run's name carries, or None (an older run's plain name)."""
    m = SCHEDULE_TITLE.match(title or "")
    if not m:
        return None
    minute, hour = int(m.group(1)), int(m.group(2))
    return (hour, minute) if hour < 24 and minute < 60 else None


def lateness(created: datetime, line: tuple[int, int]) -> timedelta:
    """created minus the line's last UTC firing at or before it (a daily line, so 0 to 24 h)."""
    fire = created.replace(hour=line[0], minute=line[1], second=0, microsecond=0)
    if fire > created:
        fire -= timedelta(days=1)
    return created - fire


@dataclass
class Note:
    route: str
    conclusion: str
    completed: datetime | None
    deliver_done: datetime | None
    status: str | None          # the deliver line's status (sent, claimed, ...), None when the log can't be read
    refused: bool               # the Deliver step's route or arm check stopped it
    emails: int | None = None   # "emails created N" on the deliver line, None when absent

    @property
    def sent(self) -> bool:
        """A real send: the line says sent and N > 0 emails were created."""
        return self.status == "sent" and bool(self.emails)


@dataclass
class Run:
    id: int
    event: str
    title: str
    created: datetime
    started: datetime
    line: tuple[int, int] | None
    armed: bool
    armed_from: str             # "log" or "derived"
    collected: bool | None      # None: the jobs could not be read
    notes: list[Note] = field(default_factory=list)


class BadData(Exception):
    """A run or job answer that is not shaped as GitHub's API shapes it."""


class Source:
    """GitHub's answers, from `gh api` (read-only GETs) or from a saved JSON file."""

    def __init__(self, repo: str, saved: dict | None = None):
        self.repo, self.saved = repo, saved

    def _gh(self, path: str, raw: bool = False):
        r = subprocess.run(["gh", "api", "-X", "GET", path], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"gh api {path}: {r.stderr.strip() or r.returncode}")
        return r.stdout if raw else json.loads(r.stdout)

    def runs(self, since: datetime) -> list[dict]:
        if self.saved is not None:
            return list(self.saved.get("runs", []))
        out, page = [], 1
        stamp = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        while True:
            doc = self._gh(f"repos/{self.repo}/actions/workflows/{WORKFLOW}/runs?branch=main"
                           f"&created=%3E%3D{stamp}&per_page=100&page={page}")
            batch = doc.get("workflow_runs", [])
            out += batch
            if len(batch) < 100:
                return out
            page += 1

    def jobs(self, run_id: int) -> list[dict] | None:
        if self.saved is not None:
            return self.saved.get("jobs", {}).get(str(run_id))
        try:
            return self._gh(f"repos/{self.repo}/actions/runs/{run_id}/jobs?filter=all&per_page=100").get("jobs", [])
        except (RuntimeError, ValueError):
            return None

    def log(self, job_id: int) -> str | None:
        if self.saved is not None:
            return self.saved.get("logs", {}).get(str(job_id))
        try:
            return self._gh(f"repos/{self.repo}/actions/jobs/{job_id}/logs", raw=True)
        except RuntimeError:
            return None


def cut_for(day: date) -> time:
    """cut(D): the cut in force for site day D (ADR 0015 invariant)."""
    return CUTOFF if day >= CUTOFF_FROM else LEGACY_CUTOFF


def in_arm_window(local: datetime) -> bool:
    return cut_for(local.date()) <= local.time().replace(second=0, microsecond=0) < ARM_UNTIL


def read_run(raw: dict, source: Source, tz: ZoneInfo) -> Run:
    created = parse_time(raw.get("created_at"))
    started = parse_time(raw.get("run_started_at")) or created
    title = raw.get("display_title") or raw.get("name") or ""
    jobs = source.jobs(raw["id"])
    armed, armed_from = in_arm_window(started.astimezone(tz)), "derived"
    collected, notes = None, []
    if jobs is not None:
        collected = False
        # the first attempt's arm job: only a first attempt can send on the schedule route
        arm = sorted((j for j in jobs if j.get("name") == "arm"), key=lambda j: j.get("run_attempt") or 1)
        if arm:
            m = ARM_LOG.search(source.log(arm[0]["id"]) or "")
            if m:
                armed, armed_from = m.group(1) == "true", "log"
        for job in jobs:
            steps = {s.get("name"): s for s in job.get("steps") or []}
            if job.get("name") == "update" and steps.get(COLLECT_STEP, {}).get("conclusion") not in (None, "skipped"):
                collected = True
            if job.get("name") == "note" and job.get("conclusion") not in (None, "skipped"):
                text = source.log(job["id"])
                found = DELIVER_LOG.findall(text or "")
                made = EMAILS_CREATED.search(found[-1][2]) if found else None
                notes.append(Note(route="schedule" if raw.get("event") == "schedule" else "dispatch",
                                  conclusion=job.get("conclusion") or "?",
                                  completed=parse_time(job.get("completed_at")),
                                  deliver_done=parse_time(steps.get(DELIVER_STEP, {}).get("completed_at")),
                                  status=found[-1][1] if found else None,
                                  refused=ROUTE_REFUSAL in (text or ""),
                                  emails=int(made.group(1)) if made else None))
    return Run(id=raw["id"], event=raw.get("event") or "?", title=title, created=created, started=started,
               line=schedule_line(title) if raw.get("event") == "schedule" else None, armed=armed,
               armed_from=armed_from, collected=collected, notes=notes)


@dataclass
class Day:
    day: date
    runs: list[Run]
    verdict: str                 # on time | late | none | no-send
    no_send: bool                # the only outcome is "no-send": out of S1's count
    s1: bool
    s2: bool
    problems: list[str]


def judge(day: date, runs: list[Run], tz: ZoneInfo) -> Day:
    def local(t: datetime | None) -> datetime | None:
        return t.astimezone(tz) if t else None

    on_time_by = datetime.combine(day, ON_TIME_BY, tz)
    latest = datetime.combine(day, LATEST_SEND, tz)
    good = [n for r in runs for n in r.notes if n.conclusion == "success"]
    sends = [n for n in good if n.sent]
    s1 = any((n.deliver_done or n.completed) and local(n.deliver_done or n.completed) <= on_time_by for n in sends)
    no_send = {n.status for r in runs for n in r.notes} == {"no-send"}
    verdict = "on time" if s1 else ("late" if sends else ("no-send" if no_send else "none"))
    s2 = any(r.event == "schedule" and r.armed and local(r.created) <= datetime.combine(day, S2_CREATED_BY, tz)
             for r in runs)
    problems = []
    sent = sum(n.sent for r in runs for n in r.notes)
    if sent > 1:
        problems.append(f"{sent} deliveries say sent (two plans' emails?)")
    for r in runs:
        for n in r.notes:
            end = n.deliver_done or n.completed
            if n.conclusion == "success" and end and local(end) > latest + timedelta(minutes=15):
                problems.append(f"run {r.id}: a note job succeeded after {LATEST_SEND:%H:%M}")
            if n.status == "claimed":
                problems.append(f"run {r.id}: the day was claimed by a different plan: possible lost records")
            if n.refused:
                problems.append(f"run {r.id}: the note job was stopped by the route or arm check")
    return Day(day=day, runs=runs, verdict=verdict, no_send=no_send, s1=s1, s2=s2, problems=problems)


def collect(source: Source, tz: ZoneInfo, now: datetime, days: int) -> list[Day]:
    today = now.astimezone(tz).date()
    first = today - timedelta(days=days - 1)
    since = datetime.combine(first - timedelta(days=1), time(0, 0), tz).astimezone(timezone.utc)
    by_day: dict[date, list[Run]] = {first + timedelta(days=i): [] for i in range(days)}
    for raw in source.runs(since):
        if raw.get("head_branch", "main") != "main" or not raw.get("created_at"):
            continue
        try:
            run = read_run(raw, source, tz)
        except (ValueError, KeyError, TypeError) as exc:
            raise BadData(f"run {raw.get('id', '?')}: unreadable run or job data ({type(exc).__name__}: {exc})")
        d = run.started.astimezone(tz).date()
        if d in by_day:
            by_day[d].append(run)
    return [judge(d, sorted(rs, key=lambda r: r.started), tz) for d, rs in sorted(by_day.items())]


def _hm(t: datetime | None, tz: ZoneInfo) -> str:
    return t.astimezone(tz).strftime("%m-%d %H:%M") if t else "-"


def _hours(td: timedelta) -> str:
    return f"{td.total_seconds() / 3600:.1f} h"


def report(days: list[Day], tz: ZoneInfo) -> str:
    out = []
    for d in days:
        collecting = sum(bool(r.collected) for r in d.runs)
        unknown = sum(r.collected is None for r in d.runs)
        out.append(f"{d.day} ({tz.key}): note {d.verdict}; collecting runs {collecting}"
                   + (f" (+{unknown} unread)" if unknown else ""))
        for r in d.runs:
            if r.event == "schedule":
                what = (f"schedule {r.line[1]} {r.line[0]} * * *, late {_hours(lateness(r.created, r.line))}"
                        if r.line else "schedule (line not in the run name)")
            else:
                what = f"{r.event} \"{r.title}\""
            out.append(f"  run {r.id}: {what}; created {_hm(r.created, tz)}, started {_hm(r.started, tz)}; "
                       f"armed {'yes' if r.armed else 'no'} ({r.armed_from})")
            for n in r.notes:
                out.append(f"    note ({n.route}): {n.conclusion}, completed {_hm(n.completed, tz)}, deliver "
                           f"{n.status or '?'}" + (" (0 emails)" if n.emails == 0 else "")
                           + (f" at {_hm(n.deliver_done, tz)}" if n.deliver_done else ""))
        if not d.runs:
            out.append("  no runs")
        for p in d.problems:
            out.append(f"  PROBLEM: {p}")
    return "\n".join(out)


def summary(days: list[Day]) -> str:
    n = len(days)
    counted = [d for d in days if not d.no_send]
    skipped = [d for d in days if d.no_send]
    s1 = sum(d.s1 for d in days)
    s2 = sum(d.s2 for d in days)
    s3 = [d for d in days if d.problems]
    lines = [f"Over {n} site days ({days[0].day} to {days[-1].day}):" if days else "No days.",
             f"S1 (note done by {ON_TIME_BY:%H:%M}): {s1} of {len(counted)} (target: at least {len(counted) - 1})",
             f"No-send days (left out of S1): {len(skipped)}"
             + (f" ({', '.join(str(d.day) for d in skipped)})" if skipped else ""),
             f"S2 (armed schedule run created by {S2_CREATED_BY:%H:%M}): {s2} of {n}",
             f"S3 (safety problems seen): {len(s3)} day(s)"
             + ("".join(f"\n  {d.day}: {'; '.join(d.problems)}" for d in s3)),
             "S3 by hand: the alarm issue fired exactly on the days with no note; no record lost or doubled across "
             "the cutoff switch day (QA)."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--days", type=int, default=3, help="site days to print, ending today (default 3)")
    ap.add_argument("--summary", type=int, metavar="N", help="print the S1, S2 and S3 counts over the last N days")
    ap.add_argument("--from-json", type=Path, help="read saved runs, jobs and logs instead of calling gh")
    ap.add_argument("--now", help="the site time to report from, 'YYYY-MM-DD HH:MM' (default: now)")
    args = ap.parse_args(argv)
    tz = site_zone()
    now = (datetime.strptime(args.now, "%Y-%m-%d %H:%M").replace(tzinfo=tz) if args.now
           else datetime.now(timezone.utc))
    n = args.summary or args.days
    if n < 1:
        ap.error("the number of days must be at least 1")
    try:
        saved = json.loads(args.from_json.read_text(encoding="utf-8")) if args.from_json else None
    except ValueError as exc:
        print(f"clock-report: {args.from_json} is not readable JSON ({' '.join(str(exc).split())})", file=sys.stderr)
        return 2
    try:
        days = collect(Source(args.repo, saved), tz, now, n)
    except (BadData, ValueError, KeyError, TypeError) as exc:
        print(f"clock-report: {' '.join(str(exc).split()) or type(exc).__name__}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"clock-report: could not read the runs: {exc}", file=sys.stderr)
        return 1
    print(summary(days) if args.summary else report(days, tz))
    return 0


if __name__ == "__main__":
    sys.exit(main())
