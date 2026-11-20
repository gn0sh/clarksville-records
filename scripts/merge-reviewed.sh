#!/usr/bin/env bash
# Merge a reviewed pull request: the only way a person merges a PR that changes anything outside data/ (runbook
# docs/ops/morning-note.md 2.0.3; docs/architecture/main-protect-invariant.md S2; ADR 0009). The bash twin of
# scripts/merge-reviewed.ps1.
#
# Run: bash scripts/merge-reviewed.sh <pr number> <reviewed head sha> <review report> [<review report> ...]
#   <reviewed head sha>  the full 40-character commit the team's review and QA passed (the PR's head)
#   <review report>      a link or path to each review report (code review, security, QA)
# It refuses unless that sha is the PR's head now (L-D: a push after the review is never merged unreviewed), posts a
# COMMENT review pinned to that sha (commit_id) naming the reports, squash-merges pinned to the same sha, deletes the
# head branch (so nothing can push it later) and prints the merge commit. The daily update's gate accepts a code
# commit on main only with a person's merge and a person's review at the PR's head.
# ADR 0011 (R1'', consumer row S2): every merge into main is a bypass merge, so it also refuses a PR whose author is
# not gn0sh or whose head is in another repository, and after the merge it prints the rule suite GitHub recorded for
# the merge commit; its last line is "Rule suite <id> for <merge sha>: <result>", and the result must be bypass.
# Exit 0 merged with a bypass rule suite, 1 refused (nothing done), 2 merged but the rule suite is not bypass or was
# not found (tell the team). Needs gh, signed in as gn0sh (gh auth login).
set -euo pipefail
repo=gn0sh/clarksville-records
owner=gn0sh
usage="Usage: bash scripts/merge-reviewed.sh <pr number> <reviewed head sha> <review report> [<review report> ...]"
pr="${1:-}"
sha="${2:-}"
if ! [[ "$pr" =~ ^[0-9]+$ ]]; then echo "$usage"; exit 1; fi
if ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "The sha must be the full 40-character commit you reviewed (git rev-parse <branch>). Nothing done."; exit 1
fi
shift 2
if [ "$#" -lt 1 ]; then echo "Name at least one review report. Nothing done. $usage"; exit 1; fi
gh auth status >/dev/null 2>&1 || { echo "Not signed in: run gh auth login. Nothing done."; exit 1; }

got=$(gh api "repos/$repo/pulls/$pr" --jq '[(.state|tostring), (.base.ref|tostring), (.head.sha|tostring), (.head.ref|tostring), (.head.repo.full_name|tostring), (.user.login|tostring)] | @tsv') \
  || { echo "Could not read pull request #$pr. Nothing done."; exit 1; }
IFS=$'\t' read -r state base head ref head_repo author <<< "$got" || true
if [ "${state:-}" != open ] || [ "${base:-}" != main ]; then
  echo "Pull request #$pr is not open into main ($(tr '\t' ' ' <<< "$got")). Nothing done."; exit 1
fi
if [ "${author:-}" != "$owner" ]; then
  echo "Pull request #$pr is authored by '${author:-}', not $owner: never bypass-merged (ADR 0011). Nothing done."; exit 1
fi
if [ "${head_repo:-}" != "$repo" ]; then
  echo "Pull request #$pr's head is in '${head_repo:-}', not $repo: never bypass-merged (ADR 0011). Nothing done."; exit 1
fi
if [ "${head:-}" != "$sha" ]; then
  echo "Pull request #$pr's head is ${head:-unknown}, not $sha: it changed after the review. Review the new head, then run this again with its sha. Nothing done."
  exit 1
fi

body="Reviewed at $sha. Review reports: $*"
review=$(gh api -X POST "repos/$repo/pulls/$pr/reviews" -f commit_id="$sha" -f event=COMMENT -f body="$body" --jq '.commit_id')
if [ "$review" != "$sha" ]; then
  echo "The review was posted at '$review', not $sha. Not merged: tell the team."; exit 1
fi
merged=$(gh api -X PUT "repos/$repo/pulls/$pr/merge" -f merge_method=squash -f sha="$sha" --jq '.sha')
if ! [[ "$merged" =~ ^[0-9a-f]{40}$ ]]; then echo "The merge did not report a commit ('$merged'). Check pull request #$pr."; exit 1; fi
gh api -X DELETE "repos/$repo/git/refs/heads/$ref" --silent \
  || echo "Could not delete the branch $ref: delete it on the pull request's page."
echo "Merged pull request #$pr (reviewed at $sha) as $merged."
# ADR 0011: under R1'' this merge must be a bypass; GitHub lists the rule suite a few seconds after the merge.
export MR_AFTER=$merged
suite=""
for i in 1 2 3 4 5; do
  suite=$(gh api "repos/$repo/rulesets/rule-suites?ref=main&time_period=hour&per_page=100" \
          --jq '.[] | select(.after_sha == $ENV.MR_AFTER) | [(.id|tostring), (.result|tostring)] | @tsv' 2>/dev/null) || suite=""
  suite=${suite%%$'\n'*}
  [ -z "$suite" ] || break
  [ "$i" = 5 ] || sleep 10
done
if [ -z "$suite" ]; then
  echo "Rule suite for $merged: not found (Insights > Rule suites shows it). Tell the team."; exit 2
fi
IFS=$'\t' read -r suite_id suite_result <<< "$suite" || true
echo "Rule suite $suite_id for $merged: $suite_result"
[ "$suite_result" = bypass ] || { echo "The merge was not a bypass ($suite_result): tell the team."; exit 2; }
