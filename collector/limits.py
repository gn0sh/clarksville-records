"""Limit trips, reported (docs/architecture/pipeline-limits-invariant.md rule 3).

Every time a safety limit refuses a fetch, a page or a document (a timeout, a byte, page or size cap), it is
recorded here as one line, `limit <NAME>: <file> [p<page>] <value> > <cap>`, and each run summary (county, city, RPC,
finance) prints `limits tripped: N` (0 included) followed by the lines. A trip in an OCR worker process cannot reach
this process's list, so the exception raised for it carries the line as its message and the parent records it with
note() when it collects the worker's error.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

_TRIPS: dict[str, None] = {}        # ordered, de-duplicated (a page re-read in-process after a worker trip)


def line(name: str, file, value, cap, page: int | None = None) -> str:
    where = Path(str(file)).name if "://" not in str(file) else str(file)
    if page is not None:
        where += f" p{page}"
    return f"limit {name}: {where} {value} > {cap}"


def trip(name: str, file, value, cap, page: int | None = None) -> str:
    """Record one trip; returns its line (use it as the exception message)."""
    ln = line(name, file, value, cap, page)
    _TRIPS.setdefault(ln)
    return ln


def note(message) -> None:
    """Record a trip line that came back as an error message (from an OCR worker); other messages are ignored."""
    text = str(message or "")
    if text.startswith("limit "):
        _TRIPS.setdefault(text)


def tripped() -> list[str]:
    return list(_TRIPS)


def reset() -> None:
    _TRIPS.clear()


def summary(prefix: str) -> str:
    """`<prefix>: limits tripped: N` and one indented line per trip."""
    lines = tripped()
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
    started = time.monotonic()
    try:
        return subprocess.run(cmd, timeout=timeout, **kw)
    except subprocess.TimeoutExpired as e:
        took = max(time.monotonic() - started, float(timeout))
        raise TimeoutTrip(e.cmd, timeout, trip(name, file, f"{took:g}s", f"{timeout:g}s", page)) from None
