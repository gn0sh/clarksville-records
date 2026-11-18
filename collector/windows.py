"""Collection windows: "launch with a year, then backfill one older year per run" (docs/expansion/daylight-template.md).

A leaf module (ADR 0012 decision 7): it imports nothing from `cities` or `collector`. collector/legistar.py imports
it directly; cities/plan.py re-exports the names and turns WindowError into CityError.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

YEAR = timedelta(days=365)


class WindowError(ValueError):
    """The windows can't be planned (e.g. `earliest` is after today)."""


@dataclass(frozen=True)
class Window:
    start: date      # inclusive
    end: date        # exclusive


def launch_windows(today: date, launch_days: int, earliest: date) -> list[Window]:
    """The collection windows, newest first: [today - launch_days, today + 1 day), then one older year at a time back
    to `earliest`. Run 1 collects windows[0] (the launch year); each later run takes the next window it has not done."""
    end = today + timedelta(days=1)
    start = max(earliest, end - timedelta(days=launch_days))
    if start >= end:
        raise WindowError(f"earliest {earliest} is after {today}: no launch window")
    windows = [Window(start, end)]
    while start > earliest:
        end, start = start, max(earliest, start - YEAR)
        windows.append(Window(start, end))
    return windows
