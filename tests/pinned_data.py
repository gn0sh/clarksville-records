"""The pinned real data (docs/architecture/real-data-tests-invariant.md, problem family real-data-tests/).

The daily update collects fresh data into data/ and then runs this suite on that checkout, so a test that reads data/
reads whatever today's collection wrote: a new council list, an EARLIER meeting whose minutes were posted late, a new
county meeting, a new budget book. Only a test of what holds for ANY valid growth may read data/ (live-invariant). A
test that asserts a specific date, name, count or wording of the real records reads this snapshot instead: the data
files exactly as committed at PINNED_COMMIT, in one byte-stable gzip committed under tests/fixtures/. It never
changes when data/ does, needs no git history (the update job's checkout is shallow) and no network.

Re-pin only by a deliberate pull request: check out a commit whose data/ the pinned tests should read, run
`python -c "import sys; sys.path.insert(0, 'tests'); import pinned_data; pinned_data.write()"`, change PINNED_COMMIT
and SNAPSHOT to that commit, and update the pinned tests' expected values with it. The snapshot holds published data
only (the same records data/ publishes); a privacy scrub of data/ must re-pin it too (qa/pii_scan.py cannot read
gzip)."""
import copy
import functools
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PINNED_COMMIT = "b35f129"   # data/ of main after PR #33; the facts and wards are as at b5a3638
SNAPSHOT = ROOT / "tests" / "fixtures" / f"real-data-{PINNED_COMMIT}.json.gz"
CITY_DATA = Path("data") / "localities" / "clarksville-tn"
# The budget funds of the city's books the pinned page tests read (the whole file is 13 MB): every line of them.
CITY_FUNDS = ("parking-commission", "vehicle-replacement-fund")
# The county budget lines the pinned tests read (data/finance.json is 5.6 MB): these lines only.
COUNTY_LINES = ("fy2027-approved/p47/r37",)
# repo-relative file -> the snapshot key it is stored under
FILES = {
    "city_facts": CITY_DATA / "facts.json",
    "city_wards": CITY_DATA / "wards.json",
    "city_finance": CITY_DATA / "finance.json",
    "county_facts": Path("data") / "facts.json",
    "county_finance": Path("data") / "finance.json",
}


def _project_city_finance(fin: dict) -> dict:
    """The city's finance.json with only the CITY_FUNDS budget lines (books, sources and the rest kept whole)."""
    from sitegen import budget_views
    return {**fin, "budget_lines": [x for x in fin["budget_lines"] if budget_views.fund_key(x) in CITY_FUNDS]}


def write(root: Path = ROOT, path: Path = SNAPSHOT) -> Path:
    """Rewrite the snapshot from `root`'s data/ (a deliberate re-pin only): byte-stable gzip, mtime 0."""
    snap = {key: json.loads((root / rel).read_text(encoding="utf-8")) for key, rel in FILES.items()}
    snap["city_finance"] = _project_city_finance(snap["city_finance"])
    snap["county_finance"] = {"budget_lines": [x for x in snap["county_finance"]["budget_lines"]
                                               if x["id"] in COUNTY_LINES]}
    raw = json.dumps(snap, sort_keys=True, separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))
    return path


@functools.cache
def _snapshot() -> dict:
    return json.loads(gzip.decompress(SNAPSHOT.read_bytes()))


def get(key: str):
    """A deep copy of one pinned file (FILES key), so no test can change what another reads."""
    return copy.deepcopy(_snapshot()[key])


def city() -> tuple[dict, list]:
    """(facts, wards) of the city council as committed at PINNED_COMMIT."""
    return get("city_facts"), get("city_wards")


def county_facts() -> dict:
    """The county's data/facts.json as committed at PINNED_COMMIT."""
    return get("county_facts")


def city_dir(tmp: Path) -> Path:
    """The pinned city files written to `tmp`/clarksville-tn/ (facts.json, wards.json, finance.json side by side, as
    data/localities/ holds them: the build finds the locality's finance.yml by the folder's name), for a build or a
    council config that takes paths. Returns that folder."""
    d = tmp / CITY_DATA.name
    d.mkdir(parents=True, exist_ok=True)
    for key, name in (("city_facts", "facts.json"), ("city_wards", "wards.json"), ("city_finance", "finance.json")):
        (d / name).write_text(json.dumps(_snapshot()[key]), encoding="utf-8")
    return d
