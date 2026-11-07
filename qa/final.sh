#!/usr/bin/env bash
# Final M1 QA pass, scripted parts only (the manual parts are in docs/qa/m1-test-plan.md).
# Run from the repo root on the commit under test, after `python -m collector run --offline` has produced
# data/facts.json, build/report.json and build/site/ (with the open-data export in build/site/data/).
# Needs the cached minutes PDFs in data/store/ (or RECORDS_STORE); add --download to spot_check if they are missing.
set -u
cd "$(dirname "$0")/.."
STORE_ARGS=()
[ -n "${RECORDS_STORE:-}" ] && STORE_ARGS=(--store "$RECORDS_STORE")
rc=0
step() { printf '\n== %s ==\n' "$1"; }

step "1. git SHA under test"
git rev-parse HEAD

step "2. full test suite (collector, sitegen, QA tools)"
python -m pytest -q || rc=1

step "3. AC-P1 / G4 gates from build/report.json"
python - <<'PY' || rc=1
import json, sys
try:
    r = json.load(open("build/report.json"))
except FileNotFoundError:
    print("MISSING build/report.json: run `python -m collector run --offline` first"); sys.exit(1)
g = r["gates"]
print(f"roll calls {g['roll_calls']}, verified {g['verified']} ({100 * g['verified_rate']:.1f}%), held back {g['held_back']}"
      f" (source errors {g['held_back_source_error']})")
print(f"AC-P1 verified >= 90%: {'PASS' if g['verified_rate_gate']['pass'] else 'FAIL'}")
print(f"G4 skew: {g['g4']['status']} (uniform share {g['g4']['uniform_share']}), overall pass={r['pass']}")
sys.exit(0 if r["pass"] else 1)
PY

step "4. AC-P3 hand-labelled set (zero wrong votes)"
python -m collector.compare_labels data/facts.json || rc=1

step "5. site checks on build/site (links, #page=, unverified leak, footer, N1, totals, 390 px)"
python -m qa.site_checks --site build/site --facts data/facts.json "${STORE_ARGS[@]}" || rc=1

step "6. AC-P2 spot check: build the sheet (a person fills it in, then run --score)"
python -m qa.spot_check --facts data/facts.json "${STORE_ARGS[@]}" || rc=1
echo "Fill in build/qa/spot/sheet.md, then: python -m qa.spot_check --score build/qa/spot/sheet.md"

printf '\nSCRIPTED PARTS: %s\n' "$([ $rc -eq 0 ] && echo PASS || echo FAIL)"
exit $rc
