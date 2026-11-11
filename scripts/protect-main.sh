#!/usr/bin/env bash
# Protect main: the bash twin of scripts/protect-main.ps1 (docs/ops/morning-note.md, step 2.0.6). Creates the
# "main: pull request required" ruleset, or updates it if it already exists; never makes a second one.
# Needs: gh, signed in as the repository owner (gh auth login). Run: bash scripts/protect-main.sh
set -euo pipefail
repo=gn0sh/clarksville-records
body="$(dirname "$0")/main-ruleset.json"
export RULESET_NAME='main: pull request required'
find='.[] | select(.name == $ENV.RULESET_NAME) | .id'

gh auth status >/dev/null 2>&1 || { echo "Not signed in: run gh auth login (as the repository owner)."; exit 1; }
ids=$(gh api "repos/$repo/rulesets" --jq "$find")
if [ -z "$ids" ]; then
  echo "No ruleset yet: creating it."
  gh api -X POST "repos/$repo/rulesets" --input "$body" --silent
else
  for id in $ids; do
    echo "Ruleset $id already exists: updating it."
    gh api -X PUT "repos/$repo/rulesets/$id" --input "$body" --silent
  done
fi

ok=1
rules=$(gh api "repos/$repo/rules/branches/main" --jq '.[].type' | sort -u | paste -sd, -)
echo "Rules on main: $rules"
[ "$rules" = "deletion,non_fast_forward,pull_request" ] || ok=0
for id in $(gh api "repos/$repo/rulesets" --jq "$find"); do
  enf=$(gh api "repos/$repo/rulesets/$id" --jq '.enforcement')
  actors=$(gh api "repos/$repo/rulesets/$id" --jq '.bypass_actors[] | [.actor_type, .actor_id] | @tsv' \
           | tr '\t' ':' | paste -sd, -)
  echo "Ruleset $id: $enf, bypass $actors"
  [ "$enf" = active ] && [ "$actors" = "Integration:15368" ] || ok=0
done
if [ "$ok" = 1 ]; then
  echo "OK: main is protected. Next: Actions > Daily update > Run workflow (the check run of step 2.0)."
else
  echo "NOT OK: expected rules deletion,non_fast_forward,pull_request and active, bypass Integration:15368."
  exit 1
fi
