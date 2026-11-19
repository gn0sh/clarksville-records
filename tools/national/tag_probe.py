"""Q2 tag probe: does a confirmed subscriber's re-submit of the public form ADD its `tag` values or REPLACE the
subscriber's tags? (architecture daylight-national, risk R-A: if it replaces, the morning-note `note-` tags are wiped.)

Run ONCE, on Brian's PC, against the LIVE `daylight` newsletter, with ONE team address that is already a confirmed
subscriber and holds at least one `note-` tag. It needs his Buttondown key in the environment variable
BUTTONDOWN_API_KEY. Steps in PowerShell, from the repository folder; the key and the address are typed hidden
(the address twice) and never on a command line, so neither is in the shell history:
    python -m pip install -r requirements.txt          (once; into the Python itself, not --user: -I skips the user folder)
    $env:BUTTONDOWN_API_KEY = [Net.NetworkCredential]::new('', (Read-Host -AsSecureString "Buttondown key")).Password
    python -I tools\\national\\tag_probe.py --dry-run      (finds the subscriber and reads its tags; changes nothing)
    python -I tools\\national\\tag_probe.py
    Remove-Item Env:BUTTONDOWN_API_KEY

What it changes: it posts the public form (https://buttondown.com/api/emails/embed-subscribe/daylight) once with the
address and one `tag=req-probe` field, exactly the fields the national page posts (site/static/national.js: `email`,
then `tag`), with the page's Origin. This is a server-side post: it is not the browser's no-cors post, so a
NO-CHANGE here is inconclusive until R-B's post from the live page. It then re-reads the subscriber (a few reads, a
few seconds apart; on NO-CHANGE it offers one more check two minutes later), prints one verdict line (ADDS,
REPLACES, NO-CHANGE or UNCLEAR) and whether the metadata (the morning note's stamp) changed, and, if the tags differ
from before, PATCHes them back to exactly the original list. It reads the subscriber once more and prints RESTORED
only when tags, metadata and type all equal the snapshot taken before the post; else RESTORE FAILED or RESTORE
INCOMPLETE with the exact fix, and exits 3. `--restore-tags "a,b,c"` sets the tags to that list (the fix line prints it).

It never prints, logs or writes the address or the key and writes no file. It prints the subscriber's tag names
(a team address: note- and req- names) and metadata key counts, never metadata values. The API is reached through
the sender's Buttondown adapter (sender/buttondown.py: https to api.buttondown.com only, no proxy, no redirect
followed, paced, fixed error text); the form post uses the adapter's opener with the host and path pinned.
Assumed, not yet seen: that GET /v1/subscribers/{id_or_email} finds a subscriber by address and returns its
`email_address`, and that PATCH /v1/subscribers/{id} with {"tags": [...]} sets the tags to exactly that list and
echoes the subscriber.
"""
from __future__ import annotations

import argparse
import functools
import getpass
import http.client
import os
import re
import secrets
import sys
import time as time_mod
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sender.buttondown import (  # noqa: E402
    API_BASE, KEY_ENV, MAX_RESPONSE, TIMEOUT, Buttondown, _fail, _reduce_subscriber, make_opener,
)
from sender.deliver import ProviderError, RateLimited  # noqa: E402

FORM_HOST = "buttondown.com"
FORM_PATH = "/api/emails/embed-subscribe/daylight"
FORM_URL = f"https://{FORM_HOST}{FORM_PATH}"
# the national page's origin (config/site.yml alerts.site_url): a browser's no-cors POST sends it; no Referer
# (national.js posts with referrerPolicy no-referrer)
PAGE_ORIGIN = "https://daylight.gnoshcodes.com"
PROBE_TAG = "req-probe"
NOTE_PREFIX = "note-"
READS = 8                  # re-reads after the post, at most
READ_GAP = 4.0             # seconds before each re-read (eventual consistency)
RECHECK_WAIT = 120.0       # seconds before the one extra check offered on NO-CHANGE
MAX_WAIT = 120.0           # the longest Retry-After obeyed
RATE_TRIES = 3             # tries of one call when Buttondown answers 429
USER_AGENT = "daylight-tag-probe"
_KEY = re.compile(r"[!-~]{16,256}")
# one address: printable ASCII, no space, one "@", a dot in the domain; nothing that could leave a path segment
_EMAIL = re.compile(r"[A-Za-z0-9._+'-]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63}){1,8}")
_NAME = re.compile(r"[a-z0-9-]{1,100}")            # a tag name printed as is (and usable in --restore-tags)
_SAFE_PATH = re.compile(r"/[A-Za-z0-9/._-]{0,200}")
_SEGMENT = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,39}")
KEY_STEP = f"$env:{KEY_ENV} = [Net.NetworkCredential]::new('', (Read-Host -AsSecureString \"Buttondown key\")).Password"
RUN_STEP = "python -I tools\\national\\tag_probe.py"
STEPS = (f"Steps (PowerShell): python -m pip install -r requirements.txt (once); {KEY_STEP}; {RUN_STEP} --dry-run; "
         f"{RUN_STEP}; Remove-Item Env:{KEY_ENV}")

VERDICTS = {
    "ADDS": "ADDS (old tags kept + req-probe)",
    "REPLACES": "REPLACES (old tags gone)",
    "NO-CHANGE": "NO-CHANGE (the tags are as before; inconclusive until R-B's live-page post)",
    "UNCLEAR": "UNCLEAR (the tags changed in another way)",
}
METADATA_FIX = ("metadata fix: nothing to type; the next morning-note run stamps note_edition again before it sends "
                "(sender/deliver.py, stamp mode); the sender reads no other metadata key. Run this probe only when no "
                "morning note is scheduled: a note already scheduled reaches only subscribers that still hold its stamp")
TYPE_FIX = ("type fix: in Buttondown > Subscribers, open this subscriber and change its type back to Regular (or "
            "confirm again from Buttondown's confirmation email); until then it gets no morning note")


class ProbeButtondown(Buttondown):
    """The adapter plus the two calls this probe needs. Both go through the adapter's own `_send` (pinned host, no
    redirect, paced, fixed error text); `sender/` itself is not changed."""

    def find_by_email(self, address: str) -> dict | None:
        """The subscriber with this address, reduced to {"id", "type", "tags", "metadata"}, or None (404).
        Assumed: GET /v1/subscribers/{id_or_email} accepts an address. The answer must carry the same address
        (`email_address`, or `email`), else it is refused: a lookup that ignored the path cannot pick another row."""
        t = "/subscribers/{email}"           # what an error may say: never the address
        if not (isinstance(address, str) and _EMAIL.fullmatch(address)) or ".." in address:
            raise _fail("GET", t, "an address that cannot go in a path")
        got = self._send("GET", f"{API_BASE}/subscribers/{quote(address, safe='')}", t, allow_404=True)
        if got is None:
            return None
        raw = got.data
        if not isinstance(raw, dict):
            raise _fail("GET", t, "a subscriber that is not an object")
        said = raw.get("email_address", raw.get("email"))
        if not (isinstance(said, str) and said.strip().lower() == address.lower()):
            raise _fail("GET", t, "another subscriber than the one asked for")
        return _reduce_subscriber(raw, "GET", t)

    def set_tags(self, subscriber_id: str, tags: list[str], idempotency_key: str) -> dict:
        """PATCH exactly {"tags": [...]} (the PATCH replaces what it is sent, T4.0 probe: so nothing else is sent)
        and return the reduced echo. Raises unless the echo holds exactly these tags."""
        t = "/subscribers/{id}"
        if not (isinstance(tags, list) and all(isinstance(x, str) for x in tags)):
            raise _fail("PATCH", t, "tags that are not a list of names")
        got = self._send("PATCH", self._path("PATCH", t, id=subscriber_id), t, body={"tags": list(tags)},
                         idempotency_key=idempotency_key)
        row = _reduce_subscriber(got.data if got else None, "PATCH", t)
        if row["id"] != subscriber_id or set(row.get("tags") or []) != set(tags):
            raise _fail("PATCH", t, "the stored tags are not what was sent")
        return row


def post_form(opener, address: str) -> tuple[int, str]:
    """POST the public form once: `email`, then one `tag` (the national page's fields and order), with the page's
    Origin and no Referer. Returns (HTTP status, the Location path or a placeholder): a 302 is Buttondown's answer for
    an existing address; no redirect is followed. The Location is shown as its path only, and not at all when it
    holds an "@", a query or any other character. Raises ProviderError with fixed text on a connection failure."""
    body = urlencode([("email", address), ("tag", PROBE_TAG)]).encode("ascii")
    req = urllib.request.Request(FORM_URL, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "User-Agent": USER_AGENT,
        "Origin": PAGE_ORIGIN})
    u = urlsplit(req.full_url)
    if u.scheme != "https" or u.netloc != FORM_HOST or u.path != FORM_PATH or req.host != FORM_HOST:
        raise ProviderError("POST form: a URL off the pinned host")
    try:
        resp = opener.open(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as exc:
        resp = exc
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        raise ProviderError("POST form: the connection failed") from None
    if resp is None:
        raise ProviderError("POST form: the connection failed")
    try:
        with resp:
            status = resp.status if isinstance(getattr(resp, "status", None), int) else resp.getcode()
            loc = resp.headers.get("Location") if getattr(resp, "headers", None) is not None else None
            resp.read(MAX_RESPONSE)          # read and drop: the body may hold the address
    except Exception:       # noqa: BLE001
        raise ProviderError("POST form: the answer could not be read") from None
    return int(status), location_path(loc)


def location_path(loc) -> str:
    """The first path segment of a clean Location ("/daylight"), else "(other path)"; "(none)" without one
    (national/tag-probe-location-token: a later segment could be a per-subscriber token)."""
    if not loc:
        return "(none)"
    if not isinstance(loc, str) or "@" in loc or "%40" in loc.lower() or "?" in loc or "#" in loc:
        return "(other path)"
    try:
        path = urlsplit(loc).path
    except ValueError:
        return "(other path)"
    if not _SAFE_PATH.fullmatch(path):
        return "(other path)"
    first = path.split("/")[1]
    return f"/{first}" if _SEGMENT.fullmatch(first) else "(other path)"


def verdict(old: list[str], new: list[str]) -> str:
    o, n = set(old), set(new)
    if n == o:
        return "NO-CHANGE"
    if PROBE_TAG in n and o <= n and n - o == {PROBE_TAG}:
        return "ADDS"
    if PROBE_TAG in n and o - n:
        return "REPLACES"
    return "UNCLEAR"


def name(t: str) -> str:
    """A tag name as printed: as is when it is plain lowercase, digits and "-", else its ascii() form."""
    return t if _NAME.fullmatch(t) else ascii(t)


def describe(tags: list[str]) -> str:
    names = sorted(set(tags))
    probe = "present" if PROBE_TAG in names else "absent"
    return f"{len(names)} tags ({', '.join(name(t) for t in names) or 'none'}; req-probe: {probe})"


def metadata_line(before, after) -> str:
    """`metadata: unchanged` or `metadata: CHANGED (n keys before, m after; note_edition kept/lost)`. No value."""
    b = before if isinstance(before, dict) else {}
    a = after if isinstance(after, dict) else {}
    if before == after or (not b and not a):
        return "metadata: unchanged"
    if "note_edition" not in b:
        ne = "none before"
    else:
        ne = "kept" if a.get("note_edition") == b["note_edition"] else "lost"
    return f"metadata: CHANGED ({len(b)} keys before, {len(a)} after; note_edition {ne})"


def _same_meta(before, after) -> bool:
    return metadata_line(before, after) == "metadata: unchanged"


def manual_fix(original: list[str], when: str = "") -> list[str]:
    """The exact fix: one copy-paste command (key still set) and the same list for the dashboard."""
    names = sorted(set(original))
    lines = []
    if all(_NAME.fullmatch(t) for t in names):
        lines.append(f"manual fix{when} (PowerShell, key still set; type the address twice when asked): "
                     f"{RUN_STEP} --restore-tags \"{','.join(names)}\"")
    lines.append(f"or in Buttondown, open this subscriber and set its tags to exactly these {len(names)}: "
                 f"{', '.join(name(t) for t in names)} (remove {PROBE_TAG} if it is there)")
    return lines


def _err(text: str, code: int = 1) -> int:
    print(f"error: {text}", file=sys.stderr)
    return code


def _api_error(e: BaseException, doing: str) -> str:
    if isinstance(e, KeyboardInterrupt):
        return "interrupted"
    if isinstance(e, RateLimited):
        return "Buttondown asked to slow down; try again in a minute"
    if isinstance(e, ProviderError) and str(e).endswith(("HTTP 401", "HTTP 403")):
        return "Buttondown refused the key (check it)"
    if not isinstance(e, (ProviderError, ValueError, OSError, http.client.HTTPException)):
        return f"could not {doing}: an unexpected error"
    return f"could not {doing}"


def _patient(call, sleep):
    """`call()`, waiting out a 429's Retry-After (at most MAX_WAIT) up to RATE_TRIES times."""
    for i in range(RATE_TRIES):
        try:
            return call()
        except RateLimited as e:
            if i == RATE_TRIES - 1:
                raise
            sleep(min(max(float(e.retry_after), 0.0), MAX_WAIT))


def _read(bd: ProbeButtondown, sub_id: str, sleep) -> dict:
    row = _patient(lambda: bd.subscriber(sub_id), sleep)
    if row is None:
        raise ProviderError("GET /subscribers/{id}: gone")
    return row


def _tags(row: dict) -> list[str]:
    return list(row.get("tags") or [])


def _ask_address(ask) -> str | None:
    """The address, typed twice (hidden); None when the two differ or nothing was typed."""
    first = (ask("Team test address (typed hidden): ") or "").strip()
    second = (ask("Same address again (typed hidden): ") or "").strip()
    return first if first and first == second else None


def _confirm(confirm, text: str) -> bool:
    try:
        return (confirm(text) or "").strip().lower() == "yes"
    except (EOFError, KeyboardInterrupt):
        return False


def _restore_only(bd: ProbeButtondown, sub: dict, raw: str, confirm, sleep) -> int:
    """--restore-tags: set the tags to exactly the given list, check the echo and a fresh read."""
    wanted = [t.strip() for t in raw.split(",")]
    if not wanted or not all(_NAME.fullmatch(t) for t in wanted):
        return _err("--restore-tags takes tag names (a-z, 0-9, -) separated by commas (nothing was changed)", 2)
    wanted = sorted(set(wanted))
    if not _confirm(confirm, f"Found the subscriber ({len(set(_tags(sub)))} tags now). Set its tags to exactly the "
                             f"{len(wanted)} given? Type yes to go on: "):
        print("stopped: nothing was changed")
        return 0
    try:
        key = secrets.token_hex(16)
        _patient(lambda: bd.set_tags(sub["id"], wanted, key), sleep)
        check = _read(bd, sub["id"], sleep)
    except (Exception, KeyboardInterrupt) as e:      # noqa: BLE001  fixed text only
        print(f"RESTORE FAILED ({_api_error(e, 'write the tags')})")
        for line in manual_fix(wanted):
            print(line)
        return 3
    if set(_tags(check)) != set(wanted):
        print("RESTORE FAILED (a fresh read shows other tags)")
        for line in manual_fix(wanted):
            print(line)
        return 3
    print(f"RESTORED (tags set to the {len(wanted)} given: {', '.join(wanted)})")
    if check.get("type") != "regular":
        print(f"type: {name(str(check.get('type')))}, not regular")
        print(TYPE_FIX)
        return 3
    return 0


def _settle(bd, sub_id, original, reads, sleep, gap):
    """Re-read up to `reads` times, `gap` seconds apart, until two reads agree on a change. The last row read."""
    last = row = None
    for _ in range(reads):
        sleep(gap)
        row = _read(bd, sub_id, sleep)
        if set(_tags(row)) != set(original) and last is not None and set(_tags(row)) == set(_tags(last)):
            break
        last = row
    return row


def main(argv: list[str] | None = None, env=None, opener=None, ask=None, confirm=None, sleep=time_mod.sleep,
         monotonic=time_mod.monotonic) -> int:
    """`opener`, `ask(prompt)` (the hidden address prompt), `confirm(prompt)`, `sleep` and `monotonic` are for
    tests."""
    ap = argparse.ArgumentParser(
        prog="tag_probe.py",
        description=("Q2 probe (risk R-A). Run ONCE on Brian's PC, against the LIVE daylight newsletter, with ONE team "
                     "address that is already a confirmed subscriber with at least one note- tag; never in Actions. "
                     f"Needs the key in the environment variable {KEY_ENV}. It posts the public form once, server-side, "
                     f"with that address and tag={PROBE_TAG}, re-reads the subscriber, prints ADDS, REPLACES, NO-CHANGE "
                     "or UNCLEAR and whether the metadata changed, and restores the original tags if they changed "
                     "(prints RESTORED, or RESTORE FAILED with the exact fix). A NO-CHANGE is inconclusive until R-B's "
                     "live-page post. The address is typed hidden, twice; it and the key are never printed or written "
                     "to a file."),
        epilog=STEPS)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="find the subscriber and read its tags only: no form post, no change")
    mode.add_argument("--restore-tags", metavar="TAGS",
                      help="set the subscriber's tags to exactly this comma-separated list (the manual fix); no post")
    args = ap.parse_args(argv)
    env = os.environ if env is None else env
    key = env.get(KEY_ENV, "")
    if not _KEY.fullmatch(key):
        return _err(f"set {KEY_ENV} to your Buttondown API key", 2)
    ask = ask or getpass.getpass
    confirm = confirm or input
    try:
        address = _ask_address(ask)
    except (EOFError, KeyboardInterrupt):
        return _err("no address typed", 2)
    if address is None:
        return _err("the two addresses typed differ, or none was typed (nothing was sent)", 2)
    if not _EMAIL.fullmatch(address) or ".." in address:
        return _err("that is not a usable email address (nothing was sent)", 2)
    opener = opener if opener is not None else make_opener()
    bd = ProbeButtondown(key, opener=opener, sleep=sleep, monotonic=monotonic)

    # 1. find it; refuse unless it is a confirmed subscriber with tags we can tell apart
    try:
        sub = _patient(functools.partial(bd.find_by_email, address), sleep)
    except (Exception, KeyboardInterrupt) as e:      # noqa: BLE001  fixed text only
        return _err(_api_error(e, "look the address up in Buttondown"))
    if sub is None:
        return _err("Buttondown answered 404: no subscriber has that address on the daylight newsletter, or "
                    "Buttondown does not look subscribers up by address (nothing was changed)")
    if args.restore_tags is not None:
        return _restore_only(bd, sub, args.restore_tags, confirm, sleep)
    if sub.get("type") != "regular":
        return _err("that subscriber is not confirmed (type is not regular); use a confirmed team address "
                    "(nothing was changed)")
    sub_id = sub["id"]
    original = _tags(sub)
    meta0 = sub.get("metadata")

    if args.dry_run:
        print(f"subscriber found: confirmed, {describe(original)}")
        print(f"metadata keys: {len(meta0) if isinstance(meta0, dict) else 0}")
        print("dry run: nothing was posted or changed")
        return 0
    if not original:
        return _err("that subscriber has no tags, so adding and replacing look the same; give the team address a "
                    "note- tag on the Alerts form first (nothing was changed)")
    if not any(t.startswith(NOTE_PREFIX) for t in original):
        return _err("that subscriber has no note- tag, so the probe cannot show what happens to them; sign the team "
                    "address up for one topic on the Alerts form first (nothing was changed)")
    if PROBE_TAG in original:
        return _err(f"that subscriber already has {PROBE_TAG} (an earlier run?); remove it in Buttondown first "
                    "(nothing was changed)")
    if not _confirm(confirm, f"Found a confirmed subscriber with {len(set(original))} tags. Post the live form once "
                             f"with tag={PROBE_TAG}, then restore its tags? Type yes to go on: "):
        print("stopped: nothing was posted or changed")
        return 0
    print(f"before: {describe(original)}")

    # 2. post the form; whatever happens from here (any exception, Ctrl-C), the subscriber is checked and restored
    final = None
    try:
        try:
            status, where = post_form(opener, address)
            posted = 200 <= status < 400
            print(f"form post (server-side): HTTP {status}, Location {where}"
                  + ("" if posted else " (Buttondown refused it)"))
        except ProviderError:
            print("form post (server-side): the connection failed (it may or may not have reached Buttondown)")
            posted = False
        del address
        # 3. re-read until two reads agree on a change, or the reads run out
        print(f"reading the subscriber again (up to {READS} reads, {READ_GAP:g} s apart)")
        row = _settle(bd, sub_id, original, READS, sleep, READ_GAP)
        if set(_tags(row)) == set(original) and _same_meta(meta0, row.get("metadata")):
            print("no change seen yet")
            if _confirm(confirm, f"Check once more in {RECHECK_WAIT / 60:g} minutes (and restore if the tags changed "
                                 "by then)? Type yes to wait: "):
                print(f"waiting {RECHECK_WAIT / 60:g} minutes")
                row = _settle(bd, sub_id, original, 2, sleep, RECHECK_WAIT / 2)
        final = row
        v = verdict(original, _tags(final))
        print(f"VERDICT (server-side post): {VERDICTS[v]}")
        print(f"after:  {describe(_tags(final))}")
        print(metadata_line(meta0, final.get("metadata")))
        if v == "NO-CHANGE" and not posted:
            print("the post was refused or failed, so this NO-CHANGE does not answer R-A at all")
        if v == "NO-CHANGE":
            for line in manual_fix(original, " (only if a later --dry-run shows req-probe)"):
                print(line)
    except KeyboardInterrupt:
        print("interrupted: restoring the original tags")
    except Exception as e:      # noqa: BLE001  code 6: the restore below must run whatever went wrong
        print(f"could not read the subscriber after the post ({_api_error(e, 'read the subscriber')}): restoring")

    # 4. restore when the tags differ (or are unknown), then read once more and compare with the snapshot; a change
    # that lands only by that read (late) is restored too, once
    failed, patched = None, False
    need = final is None or set(_tags(final)) != set(original)
    for _ in range(2):
        if need:
            patched = True
            try:
                idem = secrets.token_hex(16)
                echo = _patient(lambda: bd.set_tags(sub_id, original, idem), sleep)
                if not _same_meta(meta0, echo.get("metadata", meta0)):
                    print(f"{metadata_line(meta0, echo.get('metadata'))} (in the restore's echo)")
            except (Exception, KeyboardInterrupt) as e:      # noqa: BLE001  fixed text only
                failed = _api_error(e, "write the tags")
            sleep(READ_GAP)          # let the write settle before the fresh read that judges it
        try:
            check = _read(bd, sub_id, sleep)
        except (Exception, KeyboardInterrupt) as e:      # noqa: BLE001
            print(f"RESTORE FAILED ({failed or _api_error(e, 'read the subscriber after the restore')})")
            for line in manual_fix(original):
                print(line)
            return 3
        if patched or set(_tags(check)) == set(original):
            break
        print("a late change showed in the last read: restoring")
        need = True
    tags_ok = set(_tags(check)) == set(original)
    meta_ok = _same_meta(meta0, check.get("metadata"))
    type_ok = check.get("type") == "regular"
    if not tags_ok:
        print(f"RESTORE FAILED ({failed or 'a fresh read shows other tags'}): now {describe(_tags(check))}")
        for line in manual_fix(original):
            print(line)
    elif failed:
        print(f"note: the restore call failed ({failed}), but a fresh read shows the original tags")
    if tags_ok and meta_ok and type_ok:
        if patched:
            print(f"RESTORED (tags, metadata and type equal the snapshot; {len(set(original))} tags)")
        else:
            print("UNCHANGED (tags, metadata and type equal the snapshot; nothing to restore)")
        return 0
    if tags_ok:
        print("RESTORE INCOMPLETE (the tags are the original ones; see below)")
    if not meta_ok:
        print(f"{metadata_line(meta0, check.get('metadata'))} (fresh read)")
        print(METADATA_FIX)
    if not type_ok:
        print(f"type: CHANGED to {name(str(check.get('type')))}, not regular")
        print(TYPE_FIX)
    return 3


if __name__ == "__main__":
    sys.exit(main())
