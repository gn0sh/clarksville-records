"""What the plan and deliver stages share. Standard library only: the deliver job installs nothing."""
from __future__ import annotations

import re

PLAN_SCHEMA = "morning-send/1"
NOTE_SCHEMA = "morning-note/1"                             # sitegen.morning.SCHEMA (a test keeps them equal)
LIST_KEYS = ("zoning", "seats", "budget", "contracts")     # sitegen.morning.LIST_KEYS (a test keeps them equal)
MODES = ("stamp", "ids")
KEY_RE = re.compile(r"[0-9a-f]{12}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
TIME_RE = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
SIGNATURE_RE = re.compile(r"[a-z]+(?:,[a-z]+)*\|(?:-|[1-9]\d{0,3})\|(?:-|[1-9]\d{0,3})")


def signature(lists, district, ward) -> str:
    """One subscriber shape as the plan's `signatures` keys write it: "budget,zoning|7|-" (list keys in
    alphabetical order, then the district and the ward, "-" for none). Unknown list keys are left out."""
    picked = sorted(k for k in LIST_KEYS if k in set(lists))
    return f"{','.join(picked)}|{district if district is not None else '-'}|{ward if ward is not None else '-'}"
