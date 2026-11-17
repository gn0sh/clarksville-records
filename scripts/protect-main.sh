#!/usr/bin/env bash
# Protect main: the bash twin of scripts/protect-main.ps1 (docs/ops/morning-note.md, step 2.0.1). Creates the
# "main: pull request required" ruleset (no bypass), or updates it if it already exists; never makes a second one.
# First it turns on "Allow GitHub Actions to create and approve pull requests" (the push job's data PR), and it
# stops before changing anything if main's workflow does not open data pull requests yet.
# Needs: gh, signed in as the repository owner (gh auth login). Run: bash scripts/protect-main.sh
set -euo pipefail
repo=gn0sh/clarksville-records
body="$(dirname "$0")/main-ruleset.json"
export RULESET_NAME='main: pull request required'
find='.[] | select(.name == $ENV.RULESET_NAME) | .id'

gh auth status >/dev/null 2>&1 || { echo "Not signed in: run gh auth login (as the repository owner)."; exit 1; }
wf=$(gh api "repos/$repo/contents/.github/workflows/daily-update.yml?ref=main" -H 'Accept: application/vnd.github.raw') \
  || wf=""
case "$wf" in
  *"Open and merge the data pull request"*) ;;
  *) echo "Main does not have the data pull request change yet. Nothing was changed. Merge that pull request first, then run this again."; exit 1 ;;
esac
gh api -X PUT "repos/$repo/actions/permissions/workflow" -F can_approve_pull_request_reviews=true --silent \
  || { echo "Turning on 'Allow GitHub Actions to create and approve pull requests' failed (see above). Nothing else was changed. Send this output to the team."; exit 1; }
ids=$(gh api "repos/$repo/rulesets" --jq "$find")
if [ -z "$ids" ]; then
  echo "No ruleset yet: creating it."
  gh api -X POST "repos/$repo/rulesets" --input "$body" --silent \
    || { echo "Creating the ruleset failed (see the message above). Nothing was changed. Send this output to the team."; exit 1; }
else
  for id in $ids; do
    echo "Ruleset $id already exists: updating it."
    gh api -X PUT "repos/$repo/rulesets/$id" --input "$body" --silent \
      || { echo "Updating ruleset $id failed (see the message above). The ruleset may be unchanged. Send this output to the team."; exit 1; }
  done
fi

ok=1
found=0
rules=$(gh api "repos/$repo/rules/branches/main" --jq '.[].type' | sort -u | paste -sd, -)
echo "Rules on main: $rules"
[ "$rules" = "deletion,non_fast_forward,pull_request" ] || ok=0
prs=$(gh api "repos/$repo/actions/permissions/workflow" --jq '.can_approve_pull_request_reviews')
echo "GitHub Actions may create pull requests: $prs"
[ "$prs" = true ] || ok=0
# main-protect L-D: auto-merge merges whatever head a branch has later, unreviewed; it stays off.
auto=$(gh api "repos/$repo" --jq '.allow_auto_merge')
echo "Auto-merge allowed: $auto"
[ "$auto" = false ] || { echo "Auto-merge must be off: Settings > General > Pull Requests > untick Allow auto-merge."; ok=0; }
for id in $(gh api "repos/$repo/rulesets" --jq "$find"); do
  enf=$(gh api "repos/$repo/rulesets/$id" --jq '.enforcement')
  actors=$(gh api "repos/$repo/rulesets/$id" --jq '.bypass_actors[] | [.actor_type, .actor_id] | @tsv' \
           | tr '\t' ':' | paste -sd, -)
  # main-protect L-E: approvals stay 0. With GitHub Actions allowed to approve pull requests, a workflow's approval
  # would count toward any number above 0; the gate counts a person's merge and review instead (ADR 0009).
  appr=$(gh api "repos/$repo/rulesets/$id" --jq '.rules[].parameters.required_approving_review_count // empty' \
         | paste -sd, -)
  found=1
  echo "Ruleset $id: $enf, bypass ${actors:-none}, required approvals ${appr:-none}"
  [ "$enf" = active ] && [ -z "$actors" ] || ok=0
  [ "$appr" = 0 ] || { echo "Required approvals must be 0 (raising them needs ADR 0009 changed first: a workflow's approval would count)."; ok=0; }
done
[ "$found" = 1 ] || { echo "No ruleset named 'main: pull request required' found after writing it."; ok=0; }
if [ "$ok" = 1 ]; then
  echo "OK: main is protected. Next: Actions > Daily update > Run workflow (the check run of step 2.0)."
else
  echo "NOT OK: expected rules deletion,non_fast_forward,pull_request, active, no bypass, required approvals 0, auto-merge off, and Actions may create pull requests."
  exit 1
fi
