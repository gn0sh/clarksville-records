"""Count "Request it" taps per government from Buttondown (architecture daylight-national section 6; task B12).

Run on Brian's PC, never in Actions: it needs his Buttondown key in the environment variable BUTTONDOWN_API_KEY.
Steps in Windows PowerShell 7 (`pwsh`), from the repository folder; the key is typed hidden and never on a command line,
so it is not in the shell history:
    python -m pip install -r requirements.txt          (once; into the Python itself, not --user: -I skips the user folder)
    $env:BUTTONDOWN_API_KEY = Read-Host -MaskInput "Buttondown key"
    python -I tools\\national\\request_report.py
    Remove-Item Env:BUTTONDOWN_API_KEY

Counts the `req-<gov id>` tags of confirmed (type "regular") subscribers only, one per subscriber per government; an
`also` id in config/national/directory.yml counts for its entry's id. Ids not in the directory are ignored and the
number ignored is printed (security finding 11, national/form-abuse). The counts are advisory: anyone can tag a known
email (finding 2). It never prints or writes an email address or the key, reads no GoatCounter, and writes no file.
The subscriber list is read through the sender's Buttondown adapter (sender/buttondown.py: https to api.buttondown.com
only, every page, rows checked against the listing's count, paced, addresses dropped at the boundary). Needs PyYAML
and Jinja2 (sitegen.national loads the directory), hence the pip step.
"""
from __future__ import annotations

import argparse
import http.client
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sender.buttondown import KEY_ENV, Buttondown  # noqa: E402
from sender.deliver import ProviderError, RateLimited  # noqa: E402

PREFIX = "req-"
HEADER = "advisory: anyone can tag a known email"
_KEY = re.compile(r"[!-~]{16,256}")
STEPS = ("Steps (PowerShell 7): python -m pip install -r requirements.txt (once); "
         f'$env:{KEY_ENV} = Read-Host -MaskInput "Buttondown key"; python -I tools\\national\\request_report.py; '
         f"Remove-Item Env:{KEY_ENV}")


def count_requests(rows, known: dict[str, str]) -> tuple[Counter, int, int]:
    """(counts per canonical id, number of req- tags ignored as unknown, confirmed subscribers read).
    `rows` are the adapter's reduced subscribers ({"id", "type", "tags", "metadata"}); `known` maps every directory
    id and `also` id to its entry's id. A subscriber counts once per government, whichever of its ids it tagged."""
    counts: Counter = Counter()
    ignored = subscribers = 0
    for row in rows:
        if not isinstance(row, dict) or row.get("type") != "regular":
            continue
        subscribers += 1
        tags = row.get("tags")
        govs = set()
        for t in ({t for t in tags if isinstance(t, str)} if isinstance(tags, list) else ()):
            if not t.startswith(PREFIX):
                continue
            gov = known.get(t[len(PREFIX):])
            if gov is None:
                ignored += 1
            else:
                govs.add(gov)
        counts.update(govs)
    return counts, ignored, subscribers


def render(counts: Counter, ignored: int, subscribers: int, names: dict[str, str]) -> str:
    lines = [f"Request report ({HEADER})", f"confirmed subscribers read: {subscribers}",
             f"ignored req- tags not in the directory: {ignored}"]
    if not counts:
        lines.append("no requests for any government in the directory")
    for gov, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"{n:5d}  {gov}  {names.get(gov, '')}".rstrip())
    return "\n".join(lines)


def _fail(text: str) -> int:
    print(f"error: {text}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None, env=None, opener=None) -> int:
    """`opener` is for tests (the adapter's HTTP layer); the default is the adapter's own https-only opener."""
    ap = argparse.ArgumentParser(
        prog="request_report.py",
        description=("Counts req-<government id> tags among confirmed Buttondown subscribers. Run on Brian's PC with his "
                     f"key in the environment variable {KEY_ENV}; never in Actions. Advisory only: anyone can tag a known "
                     "email. Ids not in config/national/directory.yml are ignored (the number is printed). Prints no email "
                     "address and writes no file."),
        epilog=STEPS)
    ap.parse_args(argv)
    env = os.environ if env is None else env
    key = env.get(KEY_ENV, "")
    if not _KEY.fullmatch(key):
        print(f"error: set {KEY_ENV} to your Buttondown API key", file=sys.stderr)
        return 2
    try:
        from sitegen.national import NationalConfigError, load_directory
    except ImportError:
        return _fail("PyYAML or Jinja2 is missing: run python -m pip install -r requirements.txt")
    try:
        directory = load_directory()
    except NationalConfigError as e:      # names the file, the entry and the key; never a subscriber or the key
        return _fail(str(e))
    names = {g["gov"]: g["body_name"] for g in directory.govs}
    known = {**{a: gov for a, gov in directory.alias.items()}, **{g: g for g in names}}
    try:
        rows = Buttondown(key, opener=opener).subscribers()
    except RateLimited:
        return _fail("Buttondown asked to slow down; try again in a minute")
    except ProviderError as e:
        # the adapter's text is method, path template and status; only the status class is echoed, as fixed text
        if str(e).endswith(("HTTP 401", "HTTP 403")):
            return _fail("Buttondown refused the key (check it)")
        return _fail("could not read the subscriber list from Buttondown")
    except (ValueError, OSError, http.client.HTTPException, RecursionError):
        return _fail("could not read the subscriber list from Buttondown")
    counts, ignored, subs = count_requests(rows, known)
    print(render(counts, ignored, subs, names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
