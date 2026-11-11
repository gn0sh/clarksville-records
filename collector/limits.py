"""Limit trips, reported (docs/architecture/pipeline-limits-invariant.md rule 3).

Every time a safety limit refuses a fetch, a page or a document (a timeout, a byte, page or size cap), it is
recorded here as one line, `limit <NAME>: <file> [p<page>] <value> > <cap>`, and each run summary (county, city, RPC,
finance) prints `limits tripped: N` (0 included) followed by the lines. A trip in an OCR worker process cannot reach
this process's list, so the exception raised for it carries the line as its message and the parent records it with
note() when it collects the worker's error.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_TRIPS: list[str] = []
_floor = 0                           # where the current step's trips start (mark()); duplicates are dropped from there


def line(name: str, file, value, cap, page: int | None = None) -> str:
    where = Path(str(file)).name if "://" not in str(file) else str(file)
    if page is not None:
        where += f" p{page}"
    return f"limit {name}: {where} {value} > {cap}"


def trip(name: str, file, value, cap, page: int | None = None) -> str:
    """Record one trip; returns its line (use it as the exception message)."""
    ln = line(name, file, value, cap, page)
    _add(ln)
    return ln


def _add(ln: str) -> None:
    # one line per trip within a step: a page re-read in-process after its worker tripped is the same trip
    if ln not in _TRIPS[_floor:]:
        _TRIPS.append(ln)


def mark() -> int:
    """Start of a step (county, city, RPC, finance): returns the position to pass to tripped()/summary(), so each
    step reports only its own trips (steps run one after another in one process)."""
    global _floor
    _floor = len(_TRIPS)
    return _floor


def note(message) -> None:
    """Record a trip line that came back as an error message (from an OCR worker); other messages are ignored."""
    text = str(message or "")
    if text.startswith("limit "):
        _add(text)


def tripped(start: int = 0, end: int | None = None) -> list[str]:
    """The trips recorded from position `start` (a mark()) up to `end` (another mark(), or now)."""
    return _TRIPS[start:end]


def reset() -> None:
    global _floor
    _TRIPS.clear()
    _floor = 0


def summary(prefix: str, start: int = 0, end: int | None = None) -> str:
    """`<prefix>: limits tripped: N` and one indented line per trip of that step."""
    return render(prefix, tripped(start, end))


def render(prefix: str, lines: list[str]) -> str:
    return "\n".join([f"{prefix}: limits tripped: {len(lines)}"] + [f"  {x}" for x in lines])


class TimeoutTrip(subprocess.TimeoutExpired):
    """A tool timed out: a subprocess.TimeoutExpired (callers' handling is unchanged) whose message is the trip line."""

    def __init__(self, cmd, timeout, trip_line: str):
        super().__init__(cmd, timeout)
        self.line = trip_line

    def __str__(self) -> str:
        return self.line


def run(name: str, cmd: list, *, file, timeout: float, page: int | None = None, **kw):
    """subprocess.run(cmd, timeout=timeout, **kw); a timeout is recorded as `limit <name>` and raised as TimeoutTrip."""
    try:
        return subprocess.run(cmd, timeout=timeout, **kw)
    except subprocess.TimeoutExpired as e:
        # the value is the cap reached ("120s+"), not the measured time, so a repeat of the same trip is one line
        raise TimeoutTrip(e.cmd, timeout, trip(name, file, f"{timeout:g}s+", f"{timeout:g}s", page)) from None
