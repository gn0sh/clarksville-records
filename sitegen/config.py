"""Site-wide constants. The operator name is read from here for the footer and the About page (spec G1)."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "facts.schema.json"
CHANGES_SCHEMA_PATH = REPO_ROOT / "schema" / "changes.schema.json"
TEMPLATE_DIR = REPO_ROOT / "site" / "templates"
STATIC_DIR = REPO_ROOT / "site" / "static"

SITE_NAME = "Clarksville Records"

# CEO decision G1 (2026-11-07): every page names the operator. The CEO supplies the real text; a public build
# (M1.5) refuses to run while this is still the placeholder.
OPERATOR_PLACEHOLDER = "[OPERATOR NAME - CEO to confirm]"
OPERATOR_NAME = "Brian Zacharias"  # confirmed by the CEO, 2026-11-07

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

# Source URLs must use this scheme; anything else fails the build.
ALLOWED_URL_SCHEMES = ("https",)
