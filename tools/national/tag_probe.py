"""Q2 tag probe: does a confirmed subscriber's re-submit of the public form ADD its `tag` values or REPLACE the
subscriber's tags? (architecture daylight-national, risk R-A: if it replaces, the morning-note `note-` tags are wiped.)

Run ONCE, on Brian's PC, against the LIVE `daylight` newsletter, with ONE team address that is already a confirmed
subscriber and holds at least one `note-` tag. It needs his Buttondown key in the environment variable
BUTTONDOWN_API_KEY. Steps in PowerShell, from the repository folder; the key and the address are typed hidden and
never on a command line, so neither is in the shell history:
    python -m pip install -r requirements.txt          (once; into the Python itself, not --user: -I skips the user folder)
    $env:BUTTONDOWN_API_KEY = [Net.NetworkCredential]::new('', (Read-Host -AsSecureString "Buttondown key")).Password
    python -I tools\\national\\tag_probe.py --dry-run      (finds the subscriber and reads its tags; changes nothing)
    python -I tools\\national\\tag_probe.py
    Remove-Item Env:BUTTONDOWN_API_KEY

What it changes: it posts the public form (https://buttondown.com/api/emails/embed-subscribe/daylight) once with the
address and one `tag=req-probe` field, exactly the fields the national page posts (site/static/national.js: `email`,
then `tag`). It then re-reads the subscriber's tags (a few reads, a few seconds apart), prints one verdict line
(ADDS, REPLACES, NO-CHANGE or UNCLEAR), and, if the tags differ from before, PATCHes them back to exactly the
original list and prints RESTORED or RESTORE FAILED (with the tags to re-add by hand).

It never prints, logs or writes the address or the key and writes no file. Tag names are printed only for `note-`
tags and `req-probe`; other tags are counted. The API is reached through the sender's Buttondown adapter
(sender/buttondown.py: https to api.buttondown.com only, no proxy, no redirect followed, paced, fixed error text);
the form post uses the adapter's opener with the host and path pinned. Assumed, not yet seen: that
GET /v1/subscribers/{id_or_email} finds a subscriber by address and returns its `email_address`, and that
PATCH /v1/subscribers/{id} with {"tags": [...]} sets the tags to exactly that list and echoes the subscriber.
"""
from __future__ import annotations

import argparse
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
PROBE_TAG = "req-probe"
NOTE_PREFIX = "note-"
READS = 8                  # re-reads after the post, at most
READ_GAP = 4.0             # seconds before each re-read (eventual consistency)
USER_AGENT = "daylight-tag-probe"
_KEY = re.compile(r"[!-~]{16,256}")
# one address: printable ASCII, no space, one "@", a dot in the domain; nothing that could leave a path segment
_EMAIL = re.compile(r"[A-Za-z0-9._+'-]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63}){1,8}")
KEY_STEP = f"$env:{KEY_ENV} = [Net.NetworkCredential]::new('', (Read-Host -AsSecureString \"Buttondown key\")).Password"
RUN_STEP = "python -I tools\\national\\tag_probe.py"
STEPS = (f"Steps (PowerShell): python -m pip install -r requirements.txt (once); {KEY_STEP}; {RUN_STEP} --dry-run; "
         f"{RUN_STEP}; Remove-Item Env:{KEY_ENV}")

VERDICTS = {
    "ADDS": "ADDS (old tags kept + req-probe)",
    "REPLACES": "REPLACES (old tags gone)",
    "NO-CHANGE": "NO-CHANGE (the tags are as before)",
    "UNCLEAR": "UNCLEAR (the tags changed in another way)",
}


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
        if row["id"] != subscriber_id or sorted(row.get("tags") or []) != sorted(tags):
            raise _fail("PATCH", t, "the stored tags are not what was sent")
        return row


def post_form(opener, address: str) -> int:
    """POST the public form once: `email`, then one `tag` (the national page's fields and order). Returns the HTTP
    status (a 302 is Buttondown's answer for an existing address; no redirect is followed). Raises ProviderError
    with fixed text on a connection failure."""
    body = urlencode([("email", address), ("tag", PROBE_TAG)]).encode("ascii")
    req = urllib.request.Request(FORM_URL, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "User-Agent": USER_AGENT})
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
            resp.read(MAX_RESPONSE)          # read and drop: the body may hold the address
    except Exception:       # noqa: BLE001
        raise ProviderError("POST form: the answer could not be read") from None
    return int(status)


def verdict(old: list[str], new: list[str]) -> str:
    o, n = set(old), set(new)
    if n == o:
        return "NO-CHANGE"
    if PROBE_TAG in n and o <= n and n - o == {PROBE_TAG}:
        return "ADDS"
    if PROBE_TAG in n and o - n:
        return "REPLACES"
    return "UNCLEAR"


def describe(tags: list[str]) -> str:
    """Tag count, the `note-` names, and whether req-probe is there. No other name."""
    notes = sorted({t for t in tags if t.startswith(NOTE_PREFIX)})
    others = len({t for t in tags if not t.startswith(NOTE_PREFIX) and t != PROBE_TAG})
    probe = "present" if PROBE_TAG in tags else "absent"
    return (f"{len(set(tags))} tags (note- tags: {', '.join(notes) or 'none'}; other tags: {others}; "
            f"req-probe: {probe})")


def manual_fix(original: list[str]) -> str:
    notes = sorted({t for t in original if t.startswith(NOTE_PREFIX)})
    others = len({t for t in original if not t.startswith(NOTE_PREFIX)})
    text = (f"manual fix: in Buttondown, open this subscriber and set its tags to the original {len(set(original))}: "
            f"{', '.join(notes) or 'no note- tags'}")
    if others:
        text += f", plus {others} other tag(s) not named here"
    return text + f"; remove {PROBE_TAG} if it is there"


def _err(text: str, code: int = 1) -> int:
    print(f"error: {text}", file=sys.stderr)
    return code


def _api_error(e: Exception, doing: str) -> str:
    if isinstance(e, RateLimited):
        return "Buttondown asked to slow down; try again in a minute"
    if isinstance(e, ProviderError) and str(e).endswith(("HTTP 401", "HTTP 403")):
        return "Buttondown refused the key (check it)"
    return f"could not {doing}"


def _read_tags(bd: ProbeButtondown, sub_id: str) -> tuple[list[str], str]:
    row = bd.subscriber(sub_id)
    if row is None:
        raise ProviderError("GET /subscribers/{id}: gone")
    return list(row.get("tags") or []), str(row.get("type"))


def main(argv: list[str] | None = None, env=None, opener=None, ask=None, confirm=None, sleep=time_mod.sleep,
         monotonic=time_mod.monotonic) -> int:
    """`opener`, `ask` (the hidden address prompt), `confirm`, `sleep` and `monotonic` are for tests."""
    ap = argparse.ArgumentParser(
        prog="tag_probe.py",
        description=("Q2 probe (risk R-A). Run ONCE on Brian's PC, against the LIVE daylight newsletter, with ONE team "
                     "address that is already a confirmed subscriber with at least one note- tag; never in Actions. "
                     f"Needs the key in the environment variable {KEY_ENV}. It posts the public form once with that "
                     f"address and tag={PROBE_TAG}, re-reads the tags, prints ADDS, REPLACES, NO-CHANGE or UNCLEAR, "
                     "and restores the original tags if they changed (prints RESTORED or RESTORE FAILED with the "
                     "manual fix). The address is typed hidden; it and the key are never printed or written to a file."),
        epilog=STEPS)
    ap.add_argument("--dry-run", action="store_true",
                    help="find the subscriber and read its tags only: no form post, no change")
    args = ap.parse_args(argv)
    env = os.environ if env is None else env
    key = env.get(KEY_ENV, "")
    if not _KEY.fullmatch(key):
        return _err(f"set {KEY_ENV} to your Buttondown API key", 2)
    ask = ask or (lambda: getpass.getpass("Team test address (typed hidden): "))
    confirm = confirm or (lambda text: input(text))
    try:
        address = (ask() or "").strip()
    except (EOFError, KeyboardInterrupt):
        return _err("no address typed", 2)
    if not _EMAIL.fullmatch(address) or ".." in address:
        return _err("that is not a usable email address (nothing was sent)", 2)
    opener = opener if opener is not None else make_opener()
    bd = ProbeButtondown(key, opener=opener, sleep=sleep, monotonic=monotonic)

    # 1. find it; refuse unless it is a confirmed subscriber with tags we can tell apart
    try:
        sub = bd.find_by_email(address)
    except (ProviderError, ValueError, OSError, http.client.HTTPException, RecursionError) as e:
        return _err(_api_error(e, "look the address up in Buttondown"))
    if sub is None:
        return _err("no subscriber has that address on the daylight newsletter (nothing was changed)")
    if sub.get("type") != "regular":
        return _err("that subscriber is not confirmed (type is not regular); use a confirmed team address "
                    "(nothing was changed)")
    sub_id = sub["id"]
    original = list(sub.get("tags") or [])

    if args.dry_run:
        print(f"subscriber found: confirmed, {describe(original)}")
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
    try:
        answer = confirm(f"Found a confirmed subscriber with {len(set(original))} tags. Post the live form once with "
                         f"tag={PROBE_TAG}, then restore its tags? Type yes to go on: ")
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if (answer or "").strip().lower() != "yes":
        print("stopped: nothing was posted or changed")
        return 0

    # 2. post the form; whatever happens from here, the tags are checked and restored
    final = original
    code = 0
    try:
        try:
            status = post_form(opener, address)
            print(f"form post: HTTP {status}" + ("" if 200 <= status < 400 else " (Buttondown refused it)"))
            posted = 200 <= status < 400
        except ProviderError:
            print("form post: the connection failed (it may or may not have reached Buttondown)")
            posted = False
        del address
        # 3. re-read until two reads agree on a change, or the reads run out
        print(f"reading the tags again (up to {READS} reads, {READ_GAP:g} s apart)")
        last, warned = None, False
        for _ in range(READS):
            sleep(READ_GAP)
            final, kind = _read_tags(bd, sub_id)
            if kind != "regular" and not warned:
                warned = True
                print(f"note: the subscriber's type is now {kind!r}, not regular (not restored by this tool)")
            if set(final) != set(original) and last is not None and set(final) == set(last):
                break
            last = final
        v = verdict(original, final)
        print(f"VERDICT: {VERDICTS[v]}")
        print(f"before: {describe(original)}")
        print(f"after:  {describe(final)}")
        if v == "NO-CHANGE" and not posted:
            print("the post was refused or failed, so NO-CHANGE here does not answer R-A")
        if v == "NO-CHANGE":
            print("(a slow change would not show here: run with --dry-run in a few minutes; if the tags differ, "
                  "use the manual fix below)")
            print(manual_fix(original))
    except KeyboardInterrupt:
        print("interrupted: restoring the original tags")
        final = None
    except (ProviderError, ValueError, OSError, http.client.HTTPException, RecursionError) as e:
        print(f"could not read the tags after the post ({_api_error(e, 'read the subscriber')}): restoring")
        final = None

    # 4. restore when the tags differ (or are unknown)
    if final is not None and set(final) == set(original):
        print("no restore needed: the tags are the original ones")
        return code
    try:
        bd.set_tags(sub_id, original, secrets.token_hex(16))
    except (ProviderError, ValueError, OSError, http.client.HTTPException, RecursionError, KeyboardInterrupt) as e:
        why = _api_error(e, "write the tags") if not isinstance(e, KeyboardInterrupt) else "interrupted"
        print(f"RESTORE FAILED ({why})")
        print(manual_fix(original))
        return 3
    print(f"RESTORED (tags back to the original {len(set(original))})")
    return code


if __name__ == "__main__":
    sys.exit(main())
