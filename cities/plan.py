"""Launch with a year, then backfill (docs/expansion/daylight-template.md): pure planning plus the one state file.

- A city launches with its last `launch_days` days (365).
- After launch, each run takes ONE older year per city, newest first, down to the city's `earliest` date.
- Every city shares one run budget (minutes). Daily updates of live cities come first; launch years next; backfill
  only from what is left, so a big backfill can never crowd out a daily update.

State per city is data/cities/<slug>/backfill.json, written only by save_state() here. A city with no `launch` block
(Clarksville: its own pipeline holds its history) never gets one. Nothing here fetches anything.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from collector import windows as _windows
from collector.windows import YEAR, Window, WindowError  # noqa: F401  (re-exported: public names)

from .errors import CityError

ROOT = Path(__file__).resolve().parent.parent
DAILY_MINUTES = 5          # provisional run-cost estimates; recalibrate from the first real runs
YEAR_MINUTES = 30


def launch_windows(today: date, launch_days: int, earliest: date) -> list[Window]:
    """collector.windows.launch_windows, with its WindowError as CityError (the one error type of `cities`)."""
    try:
        return _windows.launch_windows(today, launch_days, earliest)
    except WindowError as exc:
        raise CityError(str(exc)) from exc


# ------------------------------------------------------------------ state (data/cities/<slug>/backfill.json)
def new_state(slug: str, launch_date: date, launch_days: int, earliest: date) -> dict:
    """The state after a city's launch year is collected: windows are fixed from the launch date from then on."""
    first = launch_windows(launch_date, launch_days, earliest)[0]
    return {"slug": slug, "launch_date": launch_date.isoformat(), "launch_days": launch_days,
            "done": [first.start.isoformat()]}


def windows_for(state: dict, earliest: date) -> list[Window]:
    """The city's windows from its stored launch date and launch_days (so they never shift day to day). `earliest`
    is the city file's current value: moving it only adds or drops older windows."""
    return launch_windows(date.fromisoformat(state["launch_date"]), state["launch_days"], earliest)


def next_window(state: dict, earliest: date) -> Window | None:
    done = set(state["done"])
    for w in windows_for(state, earliest):
        if w.start.isoformat() not in done:
            return w
    return None


def mark_done(state: dict, window: Window, earliest: date) -> dict:
    """A new state with `window` done. Only the next window may be marked: newest first, never skipping a year."""
    if window != next_window(state, earliest):
        raise CityError(f"{state['slug']}: {window.start}..{window.end} is not the next backfill window")
    return {**state, "done": state["done"] + [window.start.isoformat()]}


def state_path(slug: str, root: Path = ROOT) -> Path:
    return root / "data" / "cities" / slug / "backfill.json"


def load_state(slug: str, root: Path = ROOT) -> dict | None:
    p = state_path(slug, root)
    if not p.is_file():
        return None
    state = json.loads(p.read_text(encoding="utf-8"))
    _check_state(state, slug)
    return state


def save_state(city: dict, state: dict, root: Path = ROOT) -> Path:
    """Write a city's backfill state. Refused for a city without a launch block (Clarksville) or a mismatched slug."""
    if not city.get("launch"):
        raise CityError(f"{city['slug']}: no launch block, so no backfill state (its own pipeline holds its history)")
    _check_state(state, city["slug"])
    p = state_path(city["slug"], root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return p


def _check_state(state: dict, slug: str) -> None:
    ok = (isinstance(state, dict) and state.get("slug") == slug and isinstance(state.get("launch_days"), int)
          and isinstance(state.get("done"), list) and state["done"])
    try:
        date.fromisoformat(state["launch_date"])
        [date.fromisoformat(d) for d in state["done"]]
    except (KeyError, TypeError, ValueError):
        ok = False
    if not ok:
        raise CityError(f"{slug}: backfill state is malformed (slug, launch_date, launch_days, done)")


# ------------------------------------------------------------------ one run's plan
@dataclass(frozen=True)
class Job:
    slug: str
    kind: str                 # daily | launch | backfill
    minutes: int
    window: Window | None = None


@dataclass
class Plan:
    jobs: list[Job] = field(default_factory=list)
    skipped: list[Job] = field(default_factory=list)     # did not fit this run's budget
    errors: list[str] = field(default_factory=list)      # cities left out of this run, with the reason
    left: int = 0


def plan_run(cities: list[dict], states: dict[str, dict | None], today: date, budget_minutes: int,
             daily_minutes: int = DAILY_MINUTES, year_minutes: int = YEAR_MINUTES) -> Plan:
    """One run's jobs for every live city, within one shared budget. Draft cities get nothing (no collection before
    the owner's go-ahead for that city). Order: daily updates, then launch years, then one backfill year per city
    (the cities with the fewest years done first, then by slug)."""
    def earliest(c: dict) -> date:          # an UNVERIFIED earliest: the launch year only, no backfill yet
        e = c["launch"]["earliest"]
        return e if e is not None else today + timedelta(days=1) - timedelta(days=c["launch"]["launch_days"])

    live = sorted((c for c in cities if c.get("status") == "live"), key=lambda c: c["slug"])
    daily, launch, back, broken = [], [], [], []
    for c in live:
        try:
            _plan_city(c, states.get(c["slug"]), today, earliest, daily_minutes, year_minutes, daily, launch, back)
        except CityError as exc:             # one bad city never stops the others' plan
            broken.append(f"{c['slug']}: {exc}")
    plan, left = Plan(errors=broken), budget_minutes
    for job in daily + launch + [j for _, j in sorted(back, key=lambda t: (t[0], t[1].slug))]:
        if job.minutes <= left:
            plan.jobs.append(job)
            left -= job.minutes
        else:
            plan.skipped.append(job)
    plan.left = left
    return plan


def _plan_city(c, state, today, earliest, daily_minutes, year_minutes, daily, launch, back) -> None:
    """One city's jobs, appended to the three lists. Raises CityError when its windows can't be planned."""
    if not c.get("launch"):
        daily.append(Job(c["slug"], "daily", daily_minutes))
    elif state is None:
        w = launch_windows(today, c["launch"]["launch_days"], earliest(c))[0]
        launch.append(Job(c["slug"], "launch", year_minutes, w))
    else:
        daily.append(Job(c["slug"], "daily", daily_minutes))
        w = next_window(state, c["launch"]["earliest"] or date.fromisoformat(state["done"][0]))
        if w is not None:
            back.append((len(state["done"]), Job(c["slug"], "backfill", year_minutes, w)))
