"""What the plan and deliver stages share. Standard library only: the deliver job installs nothing."""
from __future__ import annotations

import re
import unicodedata
from datetime import date

PLAN_SCHEMA = "morning-send/1"
NOTE_SCHEMA = "morning-note/1"                             # sitegen.morning.SCHEMA (a test keeps them equal)
LIST_KEYS = ("zoning", "seats", "budget", "contracts")     # sitegen.morning.LIST_KEYS (a test keeps them equal)
MODES = ("stamp", "ids")
# The sign-up form's Buttondown tags (platform-facts "Morning note provider", 2026-11-16: on the free plan a new
# sign-up carrying metadata__ fields was refused, so the form posts tags; metadata holds only the sender's stamp).
# One fixed name per list and per seat, all under "note-", so the sender can tell its own tags from any other:
# "note-zoning", "note-district-5", "note-ward-3". The form writes them (sitegen/morning_page.py), the deliver stage
# reads them (deliver.recipient); every other tag is ignored.
TAG_PREFIX = "note-"
TAG_FIELD = "tag"                                          # the embed form's field name for a tag
_SEAT_TAG = re.compile(r"note-(district|ward)-([1-9][0-9]{0,3})")


def list_tag(key: str) -> str:
    """"zoning" -> "note-zoning". ValueError for a key that is not one of LIST_KEYS."""
    if key not in LIST_KEYS:
        raise ValueError(f"not a list key: {key!r}")
    return TAG_PREFIX + key


def seat_tag_prefix(seat: str) -> str:
    """"district" -> "note-district-" (the form's script appends the stored number)."""
    if seat not in ("district", "ward"):
        raise ValueError(f"not a seat: {seat!r}")
    return f"{TAG_PREFIX}{seat}-"


def read_tags(tags) -> tuple[tuple, list, list]:
    """A subscriber's tag names -> (list keys in LIST_KEYS order, district numbers, ward numbers). Only the names
    list_tag and seat_tag_prefix write count; every other tag, and every value that is not text, is ignored."""
    got = {t for t in tags if isinstance(t, str)} if isinstance(tags, (list, tuple)) else set()
    lists = tuple(k for k in LIST_KEYS if TAG_PREFIX + k in got)
    seats = {"district": [], "ward": []}
    for t in sorted(got):
        m = _SEAT_TAG.fullmatch(t)
        if m:
            seats[m.group(1)].append(int(m.group(2)))
    return lists, seats["district"], seats["ward"]
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

# note/credit-logo (Brian, 2026-11-17): the email's footer credit, as the site footer has it (base.html.j2
# `gc-credit`): the gnoshcodes hook wordmark, the same alt text and wording. A PNG, because Gmail does not show SVG;
# the 320x64 render of static/brand/gnoshcodes-hook-light.svg, shown at 160x32. The only image an email may carry:
# render writes CREDIT_LINE exactly, and deliver.body_ok accepts it as a whole line and refuses any other <img>.
# The URL is the site's own (alerts.site_url + CREDIT_PATH; a test keeps them equal).
CREDIT_PATH = "static/brand/gnoshcodes-hook-light.png"
CREDIT_IMAGE = "https://daylight.gnoshcodes.com/" + CREDIT_PATH
CREDIT_ALT = "gnoshcodes"
CREDIT_TEXT = "A gnoshcodes project."
CREDIT_LINE = f'<p><img src="{CREDIT_IMAGE}" alt="{CREDIT_ALT}" width="160" height="32"> {CREDIT_TEXT}</p>'

# note/sunrise (2026-11-22, design concept A "Sunrise"; docs/architecture/morning-note.md "Email body forms"): the
# exact opening tags the HTML edition is made of, each with its fixed inline style. render writes only these strings
# (by name) and deliver.body_ok accepts an opening tag only when it is one of them, character for character, the way
# CREDIT_LINE is held: no attribute or style is ever parsed or built from record text. The only variable part of a
# tag is a link's checked href (LINKS: `<a href="` + URL + one of these endings). Colors are the site's tokens
# (site/static/style.css); fonts are the site's stacks with system fallbacks (nothing is downloaded). No style holds
# a brace, a "<", a ">", a double quote or a double space.
_HEAD = "font-family:Outfit,'Avenir Next','Segoe UI',Arial,sans-serif;"
_MONO = "font-family:'JetBrains Mono',Menlo,Consolas,monospace;"
_KICK = _MONO + "font-size:12px;line-height:1.5;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;"
_TABLE = '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" ' \
         'style="width:100%;border-collapse:collapse;">'
TAG = {
    # the frame: the page ground, the 600px sheet (body font and ink set once, inherited below)
    "page": '<div style="margin:0;padding:16px 12px 28px;background-color:#E9EDF5;">',
    "sheet": '<div style="max-width:600px;margin:0 auto;background-color:#F7F8FC;border-radius:20px;'
             "font-family:Inter,-apple-system,'Segoe UI',Roboto,Arial,sans-serif;font-size:16px;line-height:1.5;"
             'color:#141A2E;">',
    # the sky header: name, plate, "Wednesday in <place>" over the date, the sun half-risen on the ink horizon
    "sky": '<div style="background-color:#D5DFF0;border-radius:20px 20px 0 0;border-bottom:2px solid #141A2E;">',
    "table": _TABLE,
    "tr": "<tr>",
    "sky_td": f'<td style="padding:20px 8px 14px 20px;vertical-align:bottom;{_HEAD}color:#141A2E;">',
    "h1": '<h1 style="margin:0;font-size:22px;line-height:1.1;font-weight:800;letter-spacing:-0.02em;color:#141A2E;">',
    "mark_ring": '<span aria-hidden="true" style="display:inline-block;margin:0 8px 0 0;padding:3px;'
                 'background-color:#EFC4AF;border-radius:50%;vertical-align:middle;">',
    "mark": '<span style="display:block;width:14px;height:14px;background-color:#D2561B;border-radius:50%;">',
    "plate": f'<p style="margin:3px 0 0;{_KICK}color:#4A5470;">',
    "weekday": '<p style="margin:20px 0 0;font-size:17px;line-height:1.2;font-weight:500;color:#141A2E;">',
    "date": '<p style="margin:0;font-size:32px;line-height:1.05;font-weight:800;letter-spacing:-0.035em;'
            'color:#141A2E;">',
    "sun_td": '<td width="80" aria-hidden="true" style="width:80px;padding:0 18px 0 0;vertical-align:bottom;">',
    "sun_box": '<div style="height:40px;overflow:hidden;font-size:0;line-height:0;">',
    "sun_ring": '<span style="display:inline-block;padding:10px;background-color:#EFC4AF;border-radius:50%;">',
    "sun": '<span style="display:block;width:60px;height:60px;background-color:#D2561B;border-radius:50%;">',
    "unofficial": '<p style="margin:0;padding:10px 20px;background-color:#E9EDF5;font-size:14px;line-height:1.45;'
                  'color:#141A2E;">',
    # the greeting
    "intro_box": '<div style="padding:24px 20px 4px;">',
    "greeting": f'<p style="margin:0;{_HEAD}font-size:28px;line-height:1.12;font-weight:800;'
                'letter-spacing:-0.025em;color:#141A2E;">',
    "tagline": f'<p style="margin:6px 0 0;{_HEAD}font-size:19px;line-height:1.3;font-weight:500;color:#141A2E;">',
    "intro": '<p style="margin:12px 0 0;">',
    # one section per list, one white card per entry (a meeting's carries the site's date block)
    "section": '<div style="padding:18px 20px 0;">',
    "kicker": f'<p style="margin:0;{_KICK}color:#4A5470;">',
    "h2": f'<h2 style="margin:2px 0 12px;{_HEAD}font-size:22px;line-height:1.2;font-weight:800;color:#141A2E;">',
    "card": '<div style="margin:0 0 12px;padding:16px;background-color:#FFFFFF;border:1px solid #D5DAE8;'
            'border-radius:12px;">',
    "day_td": f'<td width="52" aria-hidden="true" style="width:52px;padding:2px 14px 0 0;vertical-align:top;'
              f'text-align:center;{_MONO}font-size:12px;line-height:1.3;text-transform:uppercase;color:#4A5470;">',
    "day_n": f'<span style="{_HEAD}font-size:26px;line-height:1.1;font-weight:800;color:#141A2E;">',
    "card_td": '<td style="vertical-align:top;">',
    "h3": f'<h3 style="margin:0;{_HEAD}font-size:18px;line-height:1.25;font-weight:800;color:#141A2E;">',
    "h3_after": f'<h3 style="margin:4px 0 0;{_HEAD}font-size:18px;line-height:1.25;font-weight:800;'
                'color:#141A2E;">',
    "line": '<p style="margin:8px 0 0;">',
    "numbers": f'<p style="margin:4px 0 0;{_MONO}font-size:13px;line-height:1.6;color:#4A5470;">',
    "source": '<p style="margin:10px 0 0;font-size:15px;">',
    # the size rule's compact row (render.BUDGET), the "N more" line, and the unplaced zoning line
    "row": '<p style="margin:0 0 10px;font-size:15px;">',
    "note": '<p style="margin:0 0 12px;">',
    # "Read it in plain words."
    "words": '<div style="margin:6px 20px 0;padding:16px;background-color:#E9EDF5;border-radius:12px;">',
    "words_h2": f'<h2 style="margin:0 0 6px;{_HEAD}font-size:18px;line-height:1.25;font-weight:800;'
                'color:#141A2E;">',
    "define": '<p style="margin:6px 0 0;">',
    # the navy "Take part" box
    "part_box": '<div style="padding:18px 12px 0;">',
    "part": '<div style="padding:22px 20px 24px;background-color:#0F1F3D;border-radius:20px;color:#FFFFFF;">',
    "part_kicker": f'<p style="margin:0;{_KICK}color:#D5DCEA;">',
    "part_h2": f'<h2 style="margin:6px 0 0;{_HEAD}font-size:22px;line-height:1.2;font-weight:800;color:#FFFFFF;">',
    "part_line": '<p style="margin:10px 0 0;color:#FFFFFF;">',
    "invited": f'<p style="margin:16px 0 0;{_HEAD}font-size:19px;line-height:1.3;font-weight:500;color:#FFFFFF;">',
    "coming_kicker": f'<p style="margin:14px 0 0;{_KICK}color:#D5DCEA;">',
    "coming": '<p style="margin:6px 0 0;color:#FFFFFF;">',
    "button_p": '<p style="margin:20px 0 0;">',
    # the footer: why, the notice, the support line (then CREDIT_LINE, unstyled, exactly as before)
    "foot": '<div style="padding:22px 20px 24px;font-size:14px;color:#4A5470;">',
    "foot_first": '<p style="margin:0;">',
    "foot_p": '<p style="margin:10px 0 0;">',
    "strong": "<strong>",
}
# A link is `<a href="` + the checked URL + one of these endings: ink on a light ground, white on navy, the button.
LINKS = {
    "ink": '" style="color:#0F1F3D;text-decoration:underline;">',
    "white": '" style="color:#FFFFFF;text-decoration:underline;">',
    "button": '" style="display:inline-block;padding:13px 20px;background-color:#FFFFFF;border-radius:999px;'
              'font-size:16px;line-height:1.2;font-weight:600;color:#0F1F3D;text-decoration:none;">',
}
# Which of TAG stand alone on their line (a container opened here and closed on a later line by its own "</x>" line),
# which hold no text at all (the sun and the name's mark: shapes, never words), and which stand inside a line.
CONTAINERS = ("page", "sheet", "sky", "table", "tr", "sky_td", "sun_td", "intro_box", "section", "card", "card_td",
              "words", "part_box", "part", "foot")
EMPTY = ("mark_ring", "mark", "sun_box", "sun_ring", "sun")
INLINE = ("mark_ring", "mark", "sun_ring", "sun", "day_n", "strong")     # inside a line; every other TAG opens one
# Gmail clips a message at about 102 KB and hides the rest (the notice, the support line and the provider's
# unsubscribe link) behind "View entire message". An edition's HTML stays under this many bytes (render.layout).
BODY_BUDGET = 80_000

# plan-untrusted/body-unchecked: the hosts an email may link to (`morning_note.sender.link_hosts`: the site's host
# and the collectors' source hosts), one rule for the plan stage, the deliver check and the build. The support link
# is allowed as its one exact URL (top-level `support_url`), never its host: anyone can host a page there.
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+")
_URL_CHARS = re.compile(r"[!#-&(-;=?-\[\]-_a-z|~]+", re.IGNORECASE)     # printable ASCII but " ' < > \ ` { }


# note/sunrise, the day claim: the note's digest (plan.note_sha256) leaves out `coming_up`, the next meetings, which a
# later build the same day may list differently (a calendar change). Everything else in the note is read.
CLAIM_FREE = ("coming_up",)


def note_digest(note: dict) -> str:
    """sha256 over the note as canonical JSON without CLAIM_FREE, so two builds of one day whose notes differ only in
    their coming meetings give one digest, and a re-run still claims the day (deliver._claim)."""
    import hashlib
    import json
    rest = {k: v for k, v in note.items() if k not in CLAIM_FREE}
    return hashlib.sha256(json.dumps(rest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


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
