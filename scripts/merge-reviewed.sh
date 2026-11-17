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
# commit on main only with a person's merge and a person's review at the PR's head. Needs gh, signed in as a person
# with write access (gh auth login).
set -euo pipefail
repo=gn0sh/clarksville-records
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

got=$(gh api "repos/$repo/pulls/$pr" --jq '[.state, .base.ref, .head.sha, .head.ref, .head.repo.full_name] | join(" ")')
read -r state base head ref head_repo <<< "$got" || true
if [ "${state:-}" != open ] || [ "${base:-}" != main ]; then
  echo "Pull request #$pr is not open into main ($got). Nothing done."; exit 1
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
if [ "$head_repo" = "$repo" ]; then
  gh api -X DELETE "repos/$repo/git/refs/heads/$ref" --silent \
    || echo "Could not delete the branch $ref: delete it on the pull request's page."
fi
echo "Merged pull request #$pr (reviewed at $sha) as $merged."
