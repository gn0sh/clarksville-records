"""Site-wide constants. The operator name is read from here for the footer and the About page (spec G1)."""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "facts.schema.json"
CHANGES_SCHEMA_PATH = REPO_ROOT / "schema" / "changes.schema.json"
TEMPLATE_DIR = REPO_ROOT / "site" / "templates"
STATIC_DIR = REPO_ROOT / "site" / "static"

# Locality and branding text (config/site.yml): body and place names, purpose line, footer support link, seat
# labels, item type rule and the "coming" pages. Templates take these from `site.cfg`, never as literals.
CONFIG_DIR = REPO_ROOT / "config"
SITE_CONFIG_PATH = CONFIG_DIR / "site.yml"
SITE = yaml.safe_load(SITE_CONFIG_PATH.read_text(encoding="utf-8"))
LOCALITY = SITE["locality"]
# Holder records (design 4.1) and the landing map's geometry (design 3.2). Both optional: without them the site
# shows no seat labels, one officials list, and the district list without a map.
# The roster lives with its locality (config/localities/<locality>/seats.yml); the older top-level config/seats.yml
# is read only while that file does not exist.
_LOCALITY_SEATS = CONFIG_DIR / "localities" / LOCALITY / "seats.yml"
SEATS_PATH = _LOCALITY_SEATS if _LOCALITY_SEATS.is_file() else CONFIG_DIR / "seats.yml"
DISTRICTS_PATH = CONFIG_DIR / "localities" / LOCALITY / "districts.json"

SITE_NAME = SITE["site_name"]

# CEO decision G1 (2026-11-07): every page names the operator. The CEO supplies the real text; a public build
# (M1.5) refuses to run while this is still the placeholder.
OPERATOR_PLACEHOLDER = "[OPERATOR NAME - CEO to confirm]"
OPERATOR_NAME = SITE["operator"]  # "Brian Zacharias", confirmed by the CEO, 2026-11-07

MAX_FILES = 250

# Fixed lists, the same for every official (neutrality N1/N2).
HISTORY_TYPES = ("vote", "attendance", "moved", "seconded")
TYPE_LABELS = {"vote": "Vote", "attendance": "Attendance", "moved": "Moved", "seconded": "Seconded"}
KIND_LABELS = {"formal": "Formal meeting", "informal": "Informal meeting", "special": "Special meeting"}
EVENT_TYPE_LABELS = {
    "listed": "Listed", "referral": "Referral", "reading": "Reading", "amendment": "Amendment",
    "motion": "Motion", "roll_call": "Roll call", "postponed": "Postponed", "withdrawn": "Withdrawn",
    "other": "Other",
}
OUTCOME_LABELS = {"passed": "Passed", "failed": "Failed", "other": "Other"}

# Brain Trust round 2 (docs/reviews/brain-trust-round2.md); False confirmed by the CEO, 2026-11-07 (link only).
# False: an unconfirmed roll call
# shows no parsed value on any public page or in the public export: every vote and the outcome read "Not confirmed*"
# with the source-page link, there is no bar and no tally, and official pages count unconfirmed roll calls without a
# Yes/No breakdown. True: unconfirmed values are shown, marked "*" (the CEO decision of 2026-11-07). review.html and
# --internal exports show everything either way.
SHOW_UNCONFIRMED_VALUES = False
NOT_CONFIRMED_LABEL = "Not confirmed"

# raw-ocr-leak/vote-raw-value: an `other` vote shows the minutes' wording only when it normalises (lower case,
# letters and spaces only) to one of these keys; the value on the right is what is printed. Anything else is "Other".
OTHER_VOTE_WORDS = {
    "recused": "Recused", "recuse": "Recused",
    "absent": "Absent",
    "not voting": "Not voting", "notvoting": "Not voting", "nv": "Not voting",
    "present": "Present",
}

# Plain-words motion type for a motion whose attribution is under review. The facts file has no motion-type field,
# so the type is read from the motion text by this fixed, ordered list; only the label on the right is ever printed,
# never any of the sentence. Anything not matched is plain "Motion".
UNVERIFIED_MOTION_TYPES = [
    (r"\bmotion to amend|\bto amend\b|\bamendment\b", "Motion to amend"),
    (r"\bmotion to defer|\bto defer\b", "Motion to defer"),
    (r"\bmotion to table|\bto table\b", "Motion to table"),
    (r"\bmotion to postpone|\bto postpone\b", "Motion to postpone"),
    (r"\bmotion to approve|\bto approve\b", "Motion to approve"),
    (r"\bmotion to adopt|\bforegoing\b.*\bwas adopted\b", "Motion to adopt"),
    (r"\brules were suspended|\bsuspend the rules", "Motion to suspend the rules"),
]
UNVERIFIED_MOTION_DEFAULT = "Motion"

# Source URLs must use this scheme; anything else fails the build.
ALLOWED_URL_SCHEMES = ("https",)
