"""What the plan and deliver stages share. Standard library only: the deliver job installs nothing."""
from __future__ import annotations

import re
import unicodedata
from datetime import date

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


# plan-untrusted/body-unchecked (M3): one rule for what render writes and what deliver accepts. MARKUP is every
# character HTML, Markdown or a template language ({{ x }}, {% y %}) could read as markup; render writes each as a
# character reference and deliver refuses it raw. ADDRESS is what a mail client could turn into a link in plain
# text (a "www.", a "scheme://", a dot between two word characters as in "evil.example/login", the CJK and
# full-width dots included); render breaks each with a zero-width space and deliver refuses a body that has one.
MARKUP = "&<>\"'{}[]()*_`#\\~|!$%@="
DOTS = ".\u3002\uff0e\uff61"
ADDRESS = re.compile(rf"(?i)www\.|://|[\w-][{DOTS}]\w")
ZWSP = "\u200b"
# the only numeric references render writes: a markup character, a leading "-", "+" or space, the zero-width space
REFS = frozenset({ord(c) for c in MARKUP} | {ord("-"), ord("+"), ord(" "), ord(ZWSP)})

# plan-untrusted/body-unchecked: the hosts an email may link to (`morning_note.sender.link_hosts`: the site's host
# and the collectors' source hosts), one rule for the plan stage, the deliver check and the build. The support link
# is allowed as its one exact URL (top-level `support_url`), never its host: anyone can host a page there.
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+")
_URL_CHARS = re.compile(r"[!#-&(-;=?-\[\]-_a-z|~]+", re.IGNORECASE)     # printable ASCII but " ' < > \ ` { }


def exact_url_ok(url) -> bool:
    """True for an https URL that may be allowed exactly (the support link, Low (a)): link_ok's characters and a
    lower-case host with no user and no port."""
    if not (isinstance(url, str) and _URL_CHARS.fullmatch(url) and url.startswith("https://")):
        return False
    return bool(_HOST.fullmatch(re.split(r"[/?#]", url[len("https://"):], maxsplit=1)[0]))


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


# sender/plan-untrusted/subject-unchecked: one rule for the subject, so the deliver stage can rebuild it from the
# repository's config and refuse a plan whose subject is anything else.
MAX_TITLE = 600         # a longer title is cut here and marked with CUT; the site's page carries all of it
CUT = "..."


def clean(text) -> str:
    """One line of plain text: control and format characters are dropped (whitespace ones stay, as word breaks),
    then runs of whitespace become one space, and anything past MAX_TITLE characters is cut. In that order
    (render/clean-order): collapsing first left "a \\xad b" as "a  b", a double space the deliver check refuses."""
    s = "".join(c for c in str(text if text is not None else "")
                if c.isspace() or unicodedata.category(c) not in ("Cc", "Cf"))
    s = " ".join(s.split())
    return s if len(s) <= MAX_TITLE else s[:MAX_TITLE].rstrip() + CUT


def day_words(iso: str) -> str:
    """"2026-11-11" -> "November 11, 2026" (as the preview page writes a day). ValueError for a day that is not one."""
    d = date.fromisoformat(iso)
    return f"{d:%B} {d.day}, {d.year}"


def subject_line(template: str, site_name: str, iso: str) -> str:
    """The subject for day `iso`: the config's `morning_note.sender.text.subject` with `{site_name}` and `{date}`
    filled in, cleaned. render.subject writes it (and adds the AUTHORITY check); deliver rebuilds it to compare."""
    return clean(template.replace("{site_name}", site_name).replace("{date}", day_words(iso)))
