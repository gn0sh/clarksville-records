"""Site-wide constants. The operator name is read from here for the footer and the About page (spec G1)."""
import os
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "facts.schema.json"
CHANGES_SCHEMA_PATH = REPO_ROOT / "schema" / "changes.schema.json"
FINANCE_SCHEMA_PATH = REPO_ROOT / "schema" / "finance.schema.json"
TEMPLATE_DIR = REPO_ROOT / "site" / "templates"
STATIC_DIR = REPO_ROOT / "site" / "static"

# Locality and branding text (config/site.yml): body and place names, purpose line, footer support link, seat
# labels, item type rule and the "coming" pages. Templates take these from `site.cfg`, never as literals.
CONFIG_DIR = REPO_ROOT / "config"
SITE_CONFIG_PATH = CONFIG_DIR / "site.yml"
SITE = yaml.safe_load(SITE_CONFIG_PATH.read_text(encoding="utf-8"))
LOCALITY = SITE["locality"]
# Launch-time override (docs/ops/launch-runbook.md): the daily-update workflow sets RECORDS_SITE_URL so feeds carry
# absolute links to the public site without editing alerts.site_url in config/site.yml. Unset: the file's value.
if os.environ.get("RECORDS_SITE_URL"):
    SITE.setdefault("alerts", {})["site_url"] = os.environ["RECORDS_SITE_URL"]
# Holder records (design 4.1) and the landing map's geometry (design 3.2). Both optional: without them the site
# shows no seat labels, one officials list, and the district list without a map.
# The roster lives with its locality (config/localities/<locality>/seats.yml); the older top-level config/seats.yml
# is read only while that file does not exist.
_LOCALITY_SEATS = CONFIG_DIR / "localities" / LOCALITY / "seats.yml"
SEATS_PATH = _LOCALITY_SEATS if _LOCALITY_SEATS.is_file() else CONFIG_DIR / "seats.yml"
DISTRICTS_PATH = CONFIG_DIR / "localities" / LOCALITY / "districts.json"

SITE_NAME = SITE["site_name"]

# Councils shown beside the county (M4): each listed locality's config/localities/<locality>/council.yml names its
# facts and wards files, its page folder and its wording (sitegen/council.py). An empty list builds the county only.
COUNCIL_KEYS = ("body_key", "body_name", "nav_label", "slug", "facts", "wards", "seat_word", "min_ward_prints",
                "title_seats", "evidence", "latest_words", "kind_labels", "untitled_item")


def load_council(locality: str) -> dict:
    path = CONFIG_DIR / "localities" / locality / "council.yml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [k for k in COUNCIL_KEYS if k not in cfg]
    if missing:
        raise ValueError(f"{path}: missing {', '.join(missing)}")
    return {**cfg, "locality": locality, "facts_path": REPO_ROOT / cfg["facts"],
            "wards_path": REPO_ROOT / cfg["wards"]}


COUNCILS = [load_council(loc) for loc in SITE.get("councils") or []]

# Fixed wording for the finance and contracts pages (design finance-contracts 2-5); exact-string tested.
FIN_TEXT_PATH = CONFIG_DIR / "finance_text.yml"
FIN_TEXT = yaml.safe_load(FIN_TEXT_PATH.read_text(encoding="utf-8"))
# The capital projects page shows this fund (architecture finance-contracts 7: finance.yml `capital_fund`). The
# FIXTURE finance file has its own made-up capital fund.
FIN_LOCALITY_PATH = CONFIG_DIR / "localities" / LOCALITY / "finance.yml"
CAPITAL_FUND = str(yaml.safe_load(FIN_LOCALITY_PATH.read_text(encoding="utf-8"))["capital_fund"]) \
    if FIN_LOCALITY_PATH.is_file() else None
FIXTURE_CAPITAL_FUND = "951"

# CEO decision G1 (2026-11-07): every page names the operator. The CEO supplies the real text; a public build
# (M1.5) refuses to run while this is still the placeholder.
OPERATOR_PLACEHOLDER = "[OPERATOR NAME - CEO to confirm]"
OPERATOR_NAME = SITE["operator"]  # "Brian Zacharias", confirmed by the CEO, 2026-11-07

# File cap per build target. preview: the claude.ai artifact preview holds at most 511 files per version, so 500;
# finance adds one page per fund, not per department. pages: GitHub Pages has no such cap; 3000 keeps the site small.
MAX_FILES_BY_TARGET = {"preview": 500, "pages": 3000}
MAX_FILES = MAX_FILES_BY_TARGET["preview"]
# The daily-update workflow sets RECORDS_BUILD_TARGET=pages; local and preview builds default to "preview".
DEFAULT_TARGET = os.environ.get("RECORDS_BUILD_TARGET") or "preview"


def max_files(target: str | None = None) -> int:
    """The file cap of a build target (sitegen --target, qa.site_checks --target). One rule everywhere: a build is
    within its cap when it has at most this many files (<= cap)."""
    return MAX_FILES_BY_TARGET[target or DEFAULT_TARGET]
PAGE_BYTES = 1_000_000  # a year page over this is split in parts (build.py plan_parts; city-pages/page-weight)
PAGE_TARGET = 850_000  # the size each part aims at, under PAGE_BYTES

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

# What a roll call voted on, from the minutes' own outcome clause ("The foregoing Amendment was Adopted by the
# following roll call vote:"). Derived by fixed patterns, like the motion type: each pattern must match the WHOLE
# clause (after trimming stray quotes, a leading name and spacing); anything else gets no label. Never shows any part
# of the clause itself. The first match wins.
_VERB = r"(?:(?:was|were) )?(?:adopted|approved|failed)(?: and approved)?"
_TAIL = r" by (?:the|th~) following roll call vote:?\W*"
OUTCOME_SUBJECTS = [
    (r"(?:the )?foregoing resolution,? as amended,? " + _VERB, "Resolution, as amended"),
    (r"(?:the )?foregoing resolution " + _VERB + r", as amended,", "Resolution, as amended"),
    (r"(?:the )?foregoing amended resolution " + _VERB, "Resolution, as amended"),
    (r"(?:the )?foregoing zoning resolution " + _VERB, "Zoning resolution"),
    (r"(?:the )?foregoing resolution " + _VERB, "Resolution"),
    (r"(?:the )?foregoing amendment " + _VERB, "Amendment"),
    (r"(?:the )?amendment " + _VERB, "Amendment"),
    (r"(?:the )?foregoing motion to defer " + _VERB, "Motion to defer"),
    (r"(?:the )?motion to defer " + _VERB, "Motion to defer"),
    (r"(?:the )?(?:foregoing )?motion to table " + _VERB, "Motion to table"),
    (r"(?:the )?motion to reconsider " + _VERB, "Motion to reconsider"),
    (r"(?:the )?(?:foregoing )?motion " + _VERB, "Motion"),
    (r"(?:the )?foregoing consent agenda items " + _VERB, "Consent agenda"),
]
# Before the clause there may be one stray word (a name) or earlier text that ends in sentence punctuation (an
# amendment's own wording); that text is never shown.
OUTCOME_KINDS = [(r"(?:[a-z]+ |.*?[.:;\u201c\u201d\"] )?" + subj + _TAIL, label) for subj, label in OUTCOME_SUBJECTS]
# The same patterns in plain words for the About page (views.vote_on_rule, about.html#vote-on): _VERB and _TAIL as
# written below, "(?:x )?" as "[x]", ",?" as "[,]". tests/test_provenance.py checks no pattern syntax is left.
OUTCOME_VERB_WORDS = "[was or were] adopted, approved or failed [and approved]"
OUTCOME_TAIL_WORDS = "by the following roll call vote"

# Source URLs must use this scheme; anything else fails the build.
ALLOWED_URL_SCHEMES = ("https",)
# Hosts whose meeting videos get timestamp links (sitegen/transcripts.py video_ok): the city's CivicClerk media host.
# A transcript of a video anywhere else shows its times as text only.
VIDEO_HOSTS = ("cpmedia.azureedge.net",)
