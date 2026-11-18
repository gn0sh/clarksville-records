"""T0 golden digests (docs/tasks/city-only-site.md, problem family city-only/clarksville-identical).

The Clarksville site must stay byte-identical while sitegen learns `--city` (ADR 0012). Two builds with a fixed
`today` and target `pages`: (a) the pinned snapshot (tests/pinned_data.py, the county and city as at PINNED_COMMIT) and
(b) the fixture facts the page tests use (tests/conftest.py). Each output tree is reduced to one sha256 over the sorted
(relpath, sha256) list; the expected values and the commit they were taken at are in
tests/fixtures/clarksville-digests.json. A change to a template, static file or the build that touches Clarksville
output fails here: either undo it, or (deliberately, in its own reviewed PR) regenerate the JSON with
`python tests/test_clarksville_identical.py <commit> > tests/fixtures/clarksville-digests.json`."""
import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import pinned_data  # noqa: E402
from sitegen import config  # noqa: E402
from sitegen.build import build  # noqa: E402

DIGESTS = ROOT / "tests" / "fixtures" / "clarksville-digests.json"
TODAY = "2026-06-15"          # fixed: the day page and every "today" reading are built around it
FIXTURE = ROOT / "site" / "fixtures" / "facts.sample.json"
FIXTURE_SEATS = ROOT / "site" / "fixtures" / "seats.sample.yml"
FIXTURE_DISTRICTS = ROOT / "site" / "fixtures" / "districts.sample.json"
# What the pinned build leaves out (as tests/test_city_budget_pages.py's pinned_pages does): parts the snapshot lacks.
PINNED_OFF = dict(finance_path=None, rpc=None, county_agendas=None, county_committees=None, city_committees=None,
                  transcripts=False, export=False, morning_manifests=None, fetch_manifests=None, vote_lists=False,
                  general_fund_dollar=False)


def tree_digest(out: Path) -> str:
    rows = sorted((p.relative_to(out).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest())
                  for p in out.rglob("*") if p.is_file())
    assert rows, "empty output tree"
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def build_pinned(tmp: Path) -> Path:
    city = pinned_data.city_dir(tmp)
    (tmp / "county").mkdir()
    (tmp / "county" / "facts.json").write_text(json.dumps(pinned_data.county_facts()), encoding="utf-8")
    cfg = {**config.load_council("clarksville-tn"), "facts_path": city / "facts.json", "wards_path": city / "wards.json"}
    out = tmp / "site"
    build(tmp / "county" / "facts.json", out, target="pages", councils=[cfg], today=date.fromisoformat(TODAY),
          **PINNED_OFF)
    return out


def build_fixture(tmp: Path) -> Path:
    out = tmp / "site"
    build(FIXTURE, out, target="pages", seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS,
          today=date.fromisoformat(TODAY))
    return out


def _expected() -> dict:
    return json.loads(DIGESTS.read_text(encoding="utf-8"))


def test_digest_file_records_its_commit():
    exp = _expected()
    assert exp["taken_at_commit"] and exp["today"] == TODAY and exp["target"] == "pages"
    assert exp["pinned_commit"] == pinned_data.PINNED_COMMIT, "the snapshot was re-pinned: regenerate the digests"


def test_pinned_snapshot_build_is_byte_identical(tmp_path):
    assert tree_digest(build_pinned(tmp_path)) == _expected()["pinned"]


def test_fixture_build_is_byte_identical(tmp_path):
    assert tree_digest(build_fixture(tmp_path)) == _expected()["fixture"]


def _cli_supports_city() -> bool:
    r = subprocess.run([sys.executable, "-m", "sitegen", "--help"], cwd=ROOT, capture_output=True, text=True)
    return "--city" in r.stdout


@pytest.mark.skipif(not _cli_supports_city(), reason="sitegen has no --city yet (T3)")
def test_city_flag_build_is_byte_identical(tmp_path):
    out = tmp_path / "site"
    cmd = [sys.executable, "-m", "sitegen", "--city", "clarksville-tn", "--facts", str(FIXTURE), "--out", str(out),
           "--target", "pages", "--seats", str(FIXTURE_SEATS), "--districts", str(FIXTURE_DISTRICTS)]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env={**os.environ, "RECORDS_TODAY": TODAY})
    assert r.returncode == 0, r.stderr
    assert tree_digest(out) == _expected()["fixture"]


if __name__ == "__main__":   # regenerate: prints the JSON; argv[1] is the commit the digests are taken at
    import tempfile
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        print(json.dumps({"taken_at_commit": sys.argv[1] if len(sys.argv) > 1 else "",
                          "pinned_commit": pinned_data.PINNED_COMMIT, "today": TODAY, "target": "pages",
                          "pinned": tree_digest(build_pinned(Path(a))),
                          "fixture": tree_digest(build_fixture(Path(b)))}, indent=2))
