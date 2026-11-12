"""The Buttondown adapter: the one module in `sender/` allowed to open a connection (architecture "T4 sender",
ADR 0004; T4.4). Standard library only (urllib.request over http.client), so the job that holds the key installs
nothing.

What it may do, and nothing else:
- GET    /v1/emails                       every page, reduced to {"id", "status", "metadata"} per row (the day claim)
- GET    /v1/subscribers                  every page, reduced to {"id", "type", "metadata"} per row: the address and
                                          every other field are dropped here, at the boundary
- GET    /v1/subscribers/{id}             one subscriber, reduced the same way (None when there is none)
- PATCH  /v1/subscribers/{id}             body exactly {"metadata": {...}}: never type, address, tags or anything else
- POST   /v1/emails                       one email from the deliver stage's payload (known fields only)
- PATCH  /v1/emails/{id}                  body exactly {"status": "draft"} (take a wrong email back)
- POST   /v1/emails/{id}/send-draft       body exactly {"subscribers": [ids]}

Rules (security checklist in docs/tasks/morning-note.md T4.5; threat points 1, 2 and 6):
- https only, to exactly the pinned host (`settings.PROVIDER_HOSTS`, `api_base` == https://<host>/v1); no proxy,
  no redirect followed (a 3xx is an error), a timeout on every request, TLS verified with the system store;
- a pagination `next` link is followed only when it is https on that same host under /v1/, and never twice;
- the key comes from the environment (KEY_ENV) and is only ever put in the Authorization header. It is not logged,
  not in any exception text and not in repr();
- an error says the method, the path template (`/subscribers/{id}`) and the status code, never a body, an id or an
  address; no exception is chained to urllib's (whose text holds the URL, and so an id);
- any answer whose shape is not the documented one raises ProviderError: the deliver stage then sends nothing more
  (fail closed);
- at most 5 requests a second, one at a time; a 429 raises deliver.RateLimited with its Retry-After, and the
  deliver stage obeys it three times, then stops.

Unverified against a real account (there is none yet): each "verify in T4.0 probe" item in
docs/tasks/morning-note.md T4.4. Until the probe, every doubt is resolved by failing closed.
"""
from __future__ import annotations

import http.client
import json
import re
import ssl
import time as time_mod
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit

from .deliver import Provider, ProviderError, RateLimited
from .settings import API_PATH, PROVIDER_HOSTS

KEY_ENV = "BUTTONDOWN_API_KEY"
HOST = PROVIDER_HOSTS["buttondown"]
API_BASE = f"https://{HOST}{API_PATH}"
TIMEOUT = 30                    # seconds, per request (connect and each read)
MIN_INTERVAL = 0.2              # seconds between two requests: at most 5 a second (the limit is 600 a minute)
MAX_RESPONSE = 16_000_000       # bytes in one answer; more is not a page we asked for
MAX_PAGES = 2_000               # pages in one listing; more fails the run (it would not be cut short silently)
DEFAULT_RETRY = 5.0             # seconds, when a 429 carries no Retry-After we can read
USER_AGENT = "daylight-morning-note"
# a key goes into one header line: printable ASCII, no space, so it cannot add a header or end the request
_KEY = re.compile(r"[!-~]{16,256}")
# ids go into a path: refuse anything that could leave its segment ("/", "..", "?", "%")
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
# sender/transport/parse-differential: urlsplit drops tab and newline and other parsers read a backslash as "/", so
# a URL holding any character outside printable ASCII, or a backslash, is refused before it is parsed at all
_UNSAFE_URL = re.compile(r"[^\x21-\x7e]|\\")
_EMAIL_FIELDS = frozenset({"subject", "body", "status", "publish_date", "filters", "metadata", "archival_mode"})


class _Response:
    """What _send returns: the status and the parsed JSON (None for an empty body)."""
    __slots__ = ("status", "data")

    def __init__(self, status: int, data):
        self.status, self.data = status, data


def make_opener() -> urllib.request.OpenerDirector:
    """An opener with an https handler only (and the one that refuses every other scheme): no http, file, ftp or
    data handler, no proxy handler (so no proxy from
    the environment), no redirect handler (a 3xx comes back as its status and is refused), and no error processor
    (every status comes back to _send, which decides). TLS is verified against the system store."""
    od = urllib.request.OpenerDirector()
    od.add_handler(urllib.request.HTTPSHandler(context=ssl.create_default_context(), debuglevel=0))
    od.add_handler(urllib.request.UnknownHandler())       # any other scheme: URLError, never a silent None
    return od


def _fail(method: str, template: str, what: str) -> ProviderError:
    return ProviderError(f"{method} {template}: {what}")


def retry_after(value, now: datetime | None = None) -> float:
    """Seconds from a Retry-After header: a whole number of seconds or an HTTP date. DEFAULT_RETRY when absent or
    unreadable; never negative (deliver also caps it at deliver.MAX_WAIT)."""
    if isinstance(value, str):
        value = value.strip()
        if re.fullmatch(r"[0-9]{1,7}", value):
            return float(int(value))
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return DEFAULT_RETRY
        if when.tzinfo is None:
            return DEFAULT_RETRY
        return max((when - (now or datetime.now(timezone.utc))).total_seconds(), 0.0)
    return DEFAULT_RETRY


def _reduce_subscriber(row, method: str, template: str) -> dict:
    """{"id", "type", "metadata"}: all deliver may know. The address, IP, notes and the rest stop here."""
    if not isinstance(row, dict):
        raise _fail(method, template, "a subscriber that is not an object")
    out = {k: row[k] for k in ("id", "type", "metadata") if k in row}
    if not (isinstance(out.get("id"), str) and _ID.fullmatch(out["id"])):
        raise _fail(method, template, "a subscriber without a usable id")
    if not isinstance(out.get("type"), str):
        raise _fail(method, template, "a subscriber without a type")
    if "metadata" in out and out["metadata"] is not None and not isinstance(out["metadata"], dict):
        raise _fail(method, template, "a subscriber whose metadata is not an object")
    return out


def _reduce_email(row, method: str, template: str) -> dict:
    """{"id", "status", "metadata"} (and "filters" when asked): what the day claim and the echo check read. A row
    without a `metadata` key stays without it, so deliver fails closed on it."""
    if not isinstance(row, dict):
        raise _fail(method, template, "an email that is not an object")
    return {k: row[k] for k in ("id", "status", "metadata") if k in row}


class Buttondown(Provider):
    """deliver.Provider over Buttondown's REST API. `opener`, `sleep` and `monotonic` are for tests; the defaults are
    the real ones. `key` is never stored anywhere but the Authorization header value."""

    def __init__(self, key: str, api_base: str = API_BASE, opener=None, sleep=time_mod.sleep,
                 monotonic=time_mod.monotonic):
        if api_base != API_BASE:
            raise ValueError(f"the API base must be exactly {API_BASE}")
        if not (isinstance(key, str) and _KEY.fullmatch(key)):
            raise ValueError(f"{KEY_ENV} is not a usable key (printable characters, no space, 16 to 256 long)")
        self.__auth = f"Token {key}"
        self._open = (opener if opener is not None else make_opener()).open
        self._sleep, self._monotonic = sleep, monotonic
        self._last = None

    def __repr__(self) -> str:      # never the key
        return "Buttondown(...)"

    # ------------------------------------------------------------------------------------------ one request
    def _pace(self) -> None:
        if self._last is not None:
            wait = MIN_INTERVAL - (self._monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._monotonic()

    def _send(self, method: str, url: str, template: str, body=None, idempotency_key: str | None = None,
              ok=(200,), allow_404: bool = False) -> _Response | None:
        """One request. `template` is what an error may say about the path. None for an allowed 404."""
        if not isinstance(url, str) or _UNSAFE_URL.search(url):
            raise _fail(method, template, "a URL off the pinned host")
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != HOST or not parts.path.startswith(API_PATH + "/") \
                or parts.username or parts.password or ".." in parts.path or parts.fragment:
            raise _fail(method, template, "a URL off the pinned host")
        headers = {"Authorization": self.__auth, "Accept": "application/json", "User-Agent": USER_AGENT}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("ascii")
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers["X-Idempotency-Key"] = idempotency_key
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        # the second parse, by the library that sends it: it must agree on the scheme, the host and the path
        if req.type != "https" or req.host != HOST or not req.selector.startswith(API_PATH + "/"):
            raise _fail(method, template, "a URL off the pinned host")
        self._pace()
        try:
            resp = self._open(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as exc:        # only if an error processor were added; handled the same way
            resp = exc
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):   # adapter-errors: never unwrapped
            raise _fail(method, template, "the connection failed") from None
        if resp is None:
            raise _fail(method, template, "the connection failed")
        try:
            with resp:
                status = resp.status if isinstance(getattr(resp, "status", None), int) else resp.getcode()
                if status == 429:
                    raise RateLimited(retry_after(resp.headers.get("Retry-After")))
                if allow_404 and status == 404:
                    return None
                if status not in ok:
                    raise _fail(method, template, f"HTTP {status}")
                raw = resp.read(MAX_RESPONSE + 1)
                ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        except ProviderError:
            raise
        except Exception:       # noqa: BLE001  a broken read: say where, never what
            raise _fail(method, template, "the answer could not be read") from None
        if len(raw) > MAX_RESPONSE:
            raise _fail(method, template, "an answer over the size limit")
        if not raw:
            return _Response(status, None)
        if ctype != "application/json":
            raise _fail(method, template, "an answer that is not JSON")
        try:
            return _Response(status, json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, ValueError):
            raise _fail(method, template, "an answer that is not JSON") from None

    def _path(self, method: str, template: str, **ids) -> str:
        for v in ids.values():
            if not (isinstance(v, str) and _ID.fullmatch(v)):
                raise _fail(method, template, "an id that cannot go in a path")
        return API_BASE + template.format(**{k: quote(v, safe="") for k, v in ids.items()})

    def _listing(self, template: str) -> list:
        """Every row of a paged listing ({"results": [...], "next": url|null, "count": n}). Raises unless every
        page was read, every page gives the same `count`, and the rows add up to it: a listing is never cut short
        (or grown under us) silently."""
        url, seen, rows, count = API_BASE + template, set(), [], None
        for _ in range(MAX_PAGES):
            if url in seen:
                raise _fail("GET", template, "a page that links back")
            seen.add(url)
            got = self._send("GET", url, template)
            page = got.data if got else None
            if not (isinstance(page, dict) and isinstance(page.get("results"), list)):
                raise _fail("GET", template, "a page without results")
            nxt = page.get("next")
            if nxt is not None and not isinstance(nxt, str):
                raise _fail("GET", template, "a page whose next link is not a URL")
            c = page.get("count")
            if not isinstance(c, int) or isinstance(c, bool) or c < 0:
                raise _fail("GET", template, "a page without a count")
            if count is not None and c != count:
                raise _fail("GET", template, "a page whose count differs from the first page's")
            count = c
            rows.extend(page["results"])
            if not nxt:
                if len(rows) != count:
                    raise _fail("GET", template, "a listing whose rows do not add up to its count")
                return rows
            if _UNSAFE_URL.search(nxt):
                raise _fail("GET", template, "a next link off the pinned host")
            n = urlsplit(nxt)
            if n.scheme != "https" or n.netloc != HOST or not n.path.startswith(API_PATH + "/"):
                raise _fail("GET", template, "a next link off the pinned host")
            url = nxt
        raise _fail("GET", template, "more pages than MAX_PAGES")

    # ------------------------------------------------------------------------------------------ the interface
    def emails(self) -> list[dict]:
        return [_reduce_email(r, "GET", "/emails") for r in self._listing("/emails")]

    def subscribers(self) -> list[dict]:
        return [_reduce_subscriber(r, "GET", "/subscribers") for r in self._listing("/subscribers")]

    def subscriber(self, subscriber_id: str) -> dict | None:
        t = "/subscribers/{id}"
        got = self._send("GET", self._path("GET", t, id=subscriber_id), t, allow_404=True)
        if got is None:
            return None
        row = _reduce_subscriber(got.data, "GET", t)
        if row["id"] != subscriber_id:
            raise _fail("GET", t, "another subscriber than the one asked for")
        return row

    def set_metadata(self, subscriber_id: str, metadata: dict, idempotency_key: str) -> None:
        t = "/subscribers/{id}"
        if not isinstance(metadata, dict):
            raise _fail("PATCH", t, "metadata that is not an object")
        got = self._send("PATCH", self._path("PATCH", t, id=subscriber_id), t, body={"metadata": metadata},
                         idempotency_key=idempotency_key)
        row = _reduce_subscriber(got.data if got else None, "PATCH", t)
        # the write must have stored exactly the object sent: no merge, no change of other keys
        if row["id"] != subscriber_id or row.get("metadata") != metadata:
            raise _fail("PATCH", t, "the stored metadata is not what was sent")

    def create_email(self, payload: dict, idempotency_key: str) -> dict:
        t = "/emails"
        if not isinstance(payload, dict) or not set(payload) <= _EMAIL_FIELDS:
            raise _fail("POST", t, "a payload with a field the adapter does not send")
        got = self._send("POST", API_BASE + t, t, body=payload, idempotency_key=idempotency_key, ok=(200, 201))
        row = got.data if got else None
        if not isinstance(row, dict):
            raise _fail("POST", t, "an answer that is not an email")
        # read back from the answer, never copied from the payload: deliver's echo check compares the two
        out = _reduce_email(row, "POST", t)
        if "filters" in row:
            out["filters"] = row["filters"]
        return out

    def unschedule(self, email_id: str, idempotency_key: str) -> dict:
        t = "/emails/{id}"
        got = self._send("PATCH", self._path("PATCH", t, id=email_id), t, body={"status": "draft"},
                         idempotency_key=idempotency_key)
        return _reduce_email(got.data if got else None, "PATCH", t)

    def send_draft(self, email_id: str, subscriber_ids: list[str], idempotency_key: str) -> None:
        t = "/emails/{id}/send-draft"
        ids = list(subscriber_ids)
        if not ids or not all(isinstance(i, str) and _ID.fullmatch(i) for i in ids):
            raise _fail("POST", t, "subscriber ids that are empty or malformed")
        self._send("POST", self._path("POST", t, id=email_id), t, body={"subscribers": ids},
                   idempotency_key=idempotency_key, ok=(200, 201, 202, 204))
