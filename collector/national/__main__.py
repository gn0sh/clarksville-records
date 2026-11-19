"""python -m collector.national DATA_ROOT [--budget N] [--directory PATH]   (the D1 `national-update.yml` entry point)

One national collection run (`run.collect`): read the last outputs under DATA_ROOT, read every covered Legistar body
within the request budget, write `bodies/`, `health.json` and `proposals.json` back under DATA_ROOT
(docs/architecture/daylight-national.md 3.7, 4.5, 4.6; ADR 0013 decision 6).

- **Fetcher** (4.6 "D1 fetcher"): `PoliteFetcher(allowed_hosts=("webapi.legistar.com",),
  max_bytes=lu.MAX_RESPONSE_BYTES)`, never the Clarksville collector's ALLOWED_HOSTS or 200 MiB MAX_BYTES. Delay,
  robots.txt and the tenant rule are the fetcher's own.
- **Budget** (`national-budget/max-no-margin`): `--budget` requests on webapi.legistar.com for the run (default 300,
  ADR 0013 decision 6's NATIONAL_REQUEST_BUDGET: about 100 bodies at about 3 requests each), at most MAX_BUDGET = 360:
  RUN_SECONDS (the job's 75 minute timeout less a MARGIN_MINUTES = 15 minute margin) over the fetcher's 10 s floor.
  The margin is for the job's setup before this command, the requests of the body in flight at the deadline (each
  can take up to the fetcher's 120 s request timeout), the writes, and the commit and attest steps after it. A run
  killed by the job's timeout writes nothing, so the run must end well inside it.
- **Deadline** (`national-budget/no-wall-deadline`): the run stops reading at start + RUN_SECONDS by the wall clock,
  whatever the request count (a robots.txt Crawl-delay above 10 s stretches every wait): the bodies not read record
  `budget-skipped` and the outputs are still written (`run.run`'s `deadline`).
- **Data root** (4.6 "D1 data path"): a path the workflow creates itself (a fresh checkout of `national-data`); a
  symlinked root, `bodies/` or `cache/` is refused (`run.check_data_root`), as is a root that exists and is not a
  folder. Nothing else in the tree is checked here; the workflow owns the path.
- **Output** (4.6 "D1 logs", 11.1 row 23): stdout gets one line per body (its id and its 3.7 outcome kind) and one
  line of counts. Nothing else is printed: never `fetcher.log`, an exception's text or a traceback, because they can
  hold up to 200 characters of a 403 body and the Server and Location headers. A run that fails as a whole prints one
  line to stderr with the exception's type name (and the body id when the exception carries a well-formed one) and
  exits 1. KeyboardInterrupt prints one line and exits 130; argparse's own usage errors exit 2.

Exit codes: 0 the run completed and read at least one body (or the directory has none to read); 3 the run completed
and wrote its outputs, but some body ended `collector-error` or no body was read `ok` (`cli-exit/silent-all-failed`:
the workflow should still commit the outputs, and flag the run); 1 the run failed and wrote nothing past the
failure; 2 bad arguments; 130 interrupted.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from collector.fetch import MIN_DELAY, PoliteFetcher
from collector.national import legistar_upcoming as lu
from collector.national import run as nr
from sitegen import national as nat
from sitegen.national_guards import id_layer

PROG = "python -m collector.national"
DEFAULT_BUDGET = 300             # ADR 0013 decision 6: NATIONAL_REQUEST_BUDGET default
JOB_MINUTES = 75                 # ADR 0013 decision 6: the national-update job's timeout
MARGIN_MINUTES = 15              # setup before, the body in flight at the deadline, writes, commit and attest after
RUN_SECONDS = (JOB_MINUTES - MARGIN_MINUTES) * 60       # the run's wall-clock deadline, from its start
MAX_BUDGET = int(RUN_SECONDS // MIN_DELAY)              # 360: a full-spend run at the 10 s floor ends by the deadline
EXIT_OK, EXIT_FAILED, EXIT_FLAGGED, EXIT_INTERRUPTED = 0, 1, 3, 130
KINDS = (nr.OK, *nr.LAST_ERRORS)  # the only outcome words ever printed (3.7)


def _wall() -> datetime:
    return datetime.now(timezone.utc)


def _say(line: str, stream=None) -> None:
    """Print one line we built from ids, fixed words and numbers; a closed pipe is not the run's failure."""
    try:
        print(line, file=stream or sys.stdout, flush=True)
    except (OSError, ValueError):
        pass


def _budget(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a whole number") from None
    if not 1 <= n <= MAX_BUDGET:
        raise argparse.ArgumentTypeError(f"must be from 1 to {MAX_BUDGET}")
    return n


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=PROG, description="One Daylight Digest national collection run.",
                                 allow_abbrev=False)
    ap.add_argument("data_root", type=Path, help="the data/national folder of a fresh national-data checkout")
    ap.add_argument("--budget", type=_budget, default=DEFAULT_BUDGET,
                    help=f"requests on {nr.HOST} this run (default {DEFAULT_BUDGET}, at most {MAX_BUDGET})")
    ap.add_argument("--directory", type=Path, default=None,     # None: load_directory's own default (11.3 test 10)
                    help="directory.yml (labels.yml beside it); default the repo's config/national/directory.yml")
    return ap


def build_fetcher() -> PoliteFetcher:
    """The national fetcher (4.6): webapi.legistar.com only, one answer at most MAX_RESPONSE_BYTES."""
    return PoliteFetcher(allowed_hosts=(nr.HOST,), max_bytes=lu.MAX_RESPONSE_BYTES)


def checked_root(data_root: Path) -> Path:
    """`run.check_data_root` (a symlinked root, bodies/ or cache/ is refused), plus: a root that exists must be a
    folder. Raises ValueError."""
    root = nr.check_data_root(data_root)
    if root.exists() and not root.is_dir():
        raise ValueError("the data root is not a folder: refused")
    return root


def report(result: nr.RunResult, requests: int, budget: int) -> list[str]:
    """The lines printed for a completed run: `body <id> <kind>` per body, then the counts. Only ids that pass the id
    check and only 3.7 kinds are printed; anything else is counted, never echoed."""
    lines, counts, odd = [], dict.fromkeys(KINDS, 0), 0
    for gov in sorted(k for k in result.outcomes if isinstance(k, str)):
        kind = result.outcomes[gov]
        if id_layer(gov) is None or kind not in counts:
            odd += 1
            continue
        counts[kind] += 1
        lines.append(f"body {gov} {kind}")
    odd += sum(1 for k in result.outcomes if not isinstance(k, str))
    parts = [f"{k}={n}" for k, n in counts.items() if n]
    if odd:
        parts.append(f"unprintable={odd}")
    parts += [f"bodies={len(result.outcomes)}", f"feeds={len(result.feeds)}", f"proposals={len(result.proposals)}",
              f"requests={requests}/{budget}"]
    lines.append("counts " + " ".join(parts))
    return lines


def _failure(err: BaseException) -> str:
    """The one line a failed run prints: the type name and, when the exception carries a well-formed id, that id.
    Never str(err) or repr(err)."""
    try:
        gov = getattr(err, "gov", None)
        where = f" body {gov}" if isinstance(gov, str) and id_layer(gov) else ""
    except Exception:
        where = ""
    return f"{PROG}: failed: {type(err).__name__}{where}"


def _main(argv) -> int:
    args = _parser().parse_args(argv)
    root = checked_root(args.data_root)
    directory = nat.load_directory() if args.directory is None else nat.load_directory(args.directory)
    fetcher = build_fetcher()
    start = _wall()
    result = nr.collect(root, directory, fetcher, args.budget, start, clock=_wall,
                        deadline=start + timedelta(seconds=RUN_SECONDS))
    for line in report(result, fetcher.sent(nr.HOST), args.budget):
        _say(line)
    return exit_code(result)


def exit_code(result: nr.RunResult) -> int:
    """EXIT_FLAGGED when some body ended `collector-error` or, with at least one body, none ended `ok`; the outputs
    are written either way (this runs after collect)."""
    kinds = list(result.outcomes.values())
    if "collector-error" in kinds or (kinds and nr.OK not in kinds):
        return EXIT_FLAGGED
    return EXIT_OK


def main(argv=None) -> int:
    """Every exception is caught here and reported by type name only (4.6 "D1 logs")."""
    try:
        return _main(argv)
    except SystemExit:
        raise                                          # argparse: usage errors (2) and --help (0)
    except KeyboardInterrupt:
        _say(f"{PROG}: interrupted", sys.stderr)
        return EXIT_INTERRUPTED
    except Exception as err:                           # HostNotApproved, HostBlocked, OSError, anything unforeseen
        _say(_failure(err), sys.stderr)
        return EXIT_FAILED


def _last_resort(exc_type, exc, tb) -> None:
    """sys.excepthook / sys.unraisablehook: should anything still escape, print its type name only."""
    name = getattr(exc_type, "__name__", "Exception")
    try:
        sys.stderr.write(f"{PROG}: failed: {name}\n")
    except Exception:
        pass


def _last_resort_unraisable(unraisable) -> None:
    _last_resort(unraisable.exc_type, None, None)


if __name__ == "__main__":
    sys.excepthook = _last_resort
    sys.unraisablehook = _last_resort_unraisable
    sys.exit(main())
