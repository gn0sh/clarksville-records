"""What the plan and deliver stages share. Standard library only: the deliver job installs nothing."""
from __future__ import annotations

import re

PLAN_SCHEMA = "morning-send/1"
NOTE_SCHEMA = "morning-note/1"                             # sitegen.morning.SCHEMA (a test keeps them equal)
LIST_KEYS = ("zoning", "seats", "budget", "contracts")     # sitegen.morning.LIST_KEYS (a test keeps them equal)
MODES = ("stamp", "ids")
KEY_RE = re.compile(r"[0-9a-f]{12}")
# [0-9], never \d: in Python \d matches the digits of every script (Arabic-Indic, Devanagari, ...)
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
TIME_RE = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
SIGNATURE_RE = re.compile(r"[a-z]+(?:,[a-z]+)*\|(?:-|[1-9][0-9]{0,3})\|(?:-|[1-9][0-9]{0,3})")
# The plan stage's ceiling on what it writes (plan.json plus the edition files), and the most the deliver stage
# reads. A real RPC agenda day is about 2.7 MB over 191 editions; this is about twelve such days at once, so
# hitting it means something is wrong with the data, not a busy morning.
MAX_PLAN_BYTES = 32_000_000
REASONS = ("ok", "quiet", "backfill", "disabled")          # plan.reason: "ok" exactly when send is true


# plan-untrusted/body-unchecked: the hosts an email may link to (`morning_note.sender.link_hosts`: the site's host,
# the collectors' source hosts and the support link's), one rule for the plan stage, the deliver check and the build
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+")
_URL_CHARS = re.compile(r"[!#-&(-;=?-\[\]-_a-z|~]+", re.IGNORECASE)     # printable ASCII but " ' < > \ ` { }


def parse_hosts(text) -> tuple:
    """"a.example,b.example" -> ("a.example", "b.example"). ValueError unless every entry is a lower-case host."""
    if not isinstance(text, str) or not text:
        raise ValueError("link_hosts must be host names separated by commas")
    hosts = tuple(text.split(","))
    if not all(_HOST.fullmatch(h) for h in hosts):
        raise ValueError("link_hosts must be lower-case host names separated by commas, nothing else")
    return hosts


def link_ok(url, hosts) -> bool:
    """True for an https URL on exactly one of `hosts`: no user, no port, no character that could leave an href."""
    if not (isinstance(url, str) and _URL_CHARS.fullmatch(url) and url.startswith("https://")):
        return False
    netloc = re.split(r"[/?#]", url[len("https://"):], maxsplit=1)[0]     # a user or port stays in it: no match
    return netloc in hosts


def signature(lists, district, ward) -> str:
    """One subscriber shape as the plan's `signatures` keys write it: "budget,zoning|7|-" (list keys in
    alphabetical order, then the district and the ward, "-" for none). Unknown list keys are left out."""
    picked = sorted(k for k in LIST_KEYS if k in set(lists))
    return f"{','.join(picked)}|{district if district is not None else '-'}|{ward if ward is not None else '-'}"
