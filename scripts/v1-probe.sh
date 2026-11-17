#!/usr/bin/env bash
# V1 probe, one time (docs/architecture/main-protect-invariant.md "V1 probe"; runbook docs/ops/morning-note.md 2.0.4;
# task T4.10.1). The bash twin of scripts/v1-probe.ps1, which is the one Brian runs.
#
# Question: does GitHub refuse GITHUB_TOKEN merging a pull request that adds a workflow file? The gate job's design
# rests on it. The script, signed in as the owner (gh auth login, with the `workflow` scope):
#   1. checks a daily data PR was merged by GitHub Actions (so bot merges work: a refusal below is about workflows);
#   2. pushes the throwaway branch probe/v1-target (main plus an inert .github/workflows/v1-canary.yml, two commits)
#      and opens its pull request into main (author: you);
#   3. posts a COMMENT review on it pinned to the OLDER commit and checks GitHub keeps that commit_id (step 4);
#   4. pushes probe/v1-runner (main plus .github/workflows/v1-probe.yml), which starts a run that tries to merge the
#      pull request with GITHUB_TOKEN: squash, then merge, then rebase (REST), then GraphQL mergePullRequest;
#   5. reads the run's answers, whether the probe PR merged, whether v1-canary.yml is on main, and main's sha before
#      and after; prints PASS, FAIL or INCONCLUSIVE, and cleans up (closes the PR, deletes both probe branches).
# FAIL means the probe PR merged (the run's own merge answer, or the PR reads merged) or v1-canary.yml is on main
# (v1-probe/verdict-from-main-sha): then it turns "Allow GitHub Actions to create and approve pull requests" off at
# once. main moving for another reason, or a read that failed, is INCONCLUSIVE and leaves that setting on.
# v1-probe/verdict-race (L-c): the run must read `completed` before its answers count (else INCONCLUSIVE), and a PASS
# or INCONCLUSIVE stands only if the probe PR, read again after cleanup closed it, is still unmerged.
# Writes the result to v1-probe-results-<time>.txt in RESULTS_DIR (default: the home folder). Nothing is sent.
set -euo pipefail
repo=gn0sh/clarksville-records
here="$(cd "$(dirname "$0")" && pwd)"
target=probe/v1-target
runner=probe/v1-runner
out_dir="${RESULTS_DIR:-$HOME}"
results="$out_dir/v1-probe-results-$(date +%Y%m%d-%H%M).txt"
log() { echo "$1"; echo "$1" >> "$results"; }
api_quiet() { gh api "$@" --silent >/dev/null 2>&1 || true; }

gh auth status >/dev/null 2>&1 || { echo "Not signed in: run gh auth login (as the repository owner)."; exit 1; }
if ! gh auth status 2>&1 | grep -q "workflow"; then
  echo "Your GitHub CLI sign-in needs the workflow scope to push the probe's workflow files: a browser opens."
  gh auth refresh -h github.com -s workflow
fi
data_prs=$(gh pr list --repo "$repo" --state merged --app github-actions --search "head:data/" --json number --jq 'length')
if ! [[ "$data_prs" =~ ^[0-9]+$ ]] || [ "$data_prs" -lt 1 ]; then
  echo "No daily data pull request merged by GitHub Actions yet: do the check run of runbook step 2.0 first. Nothing was changed."
  exit 1
fi

: > "$results"
main_before=$(gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha' || true)
log "V1 probe $(date -u +%FT%TZ). main before: $main_before"
if ! [[ "$main_before" =~ ^[0-9a-f]{40}$ ]]; then log "INCONCLUSIVE: could not read main. Nothing was changed."; exit 1; fi
api_quiet -X DELETE "repos/$repo/git/refs/heads/$target"          # leftovers of an earlier try
api_quiet -X DELETE "repos/$repo/git/refs/heads/$runner"
cleanup() {
  if [ -n "${num:-}" ]; then api_quiet -X PATCH "repos/$repo/pulls/$num" -f state=closed; fi
  api_quiet -X DELETE "repos/$repo/git/refs/heads/$target"
  api_quiet -X DELETE "repos/$repo/git/refs/heads/$runner"
}
trap cleanup EXIT

canary=$(base64 -w0 < "$here/v1-probe/v1-canary.yml")
canary2=$( { cat "$here/v1-probe/v1-canary.yml"; echo "# second commit of the probe"; } | base64 -w0)
probe=$(base64 -w0 < "$here/v1-probe/v1-probe.yml")
gh api -X POST "repos/$repo/git/refs" -f ref="refs/heads/$target" -f sha="$main_before" --silent
read -r c1 blob <<< "$(gh api -X PUT "repos/$repo/contents/.github/workflows/v1-canary.yml" -f message="V1 probe: inert canary workflow" \
  -f content="$canary" -f branch="$target" --jq '[.commit.sha, .content.sha] | @tsv')"
c2=$(gh api -X PUT "repos/$repo/contents/.github/workflows/v1-canary.yml" -f message="V1 probe: second commit" \
  -f content="$canary2" -f sha="$blob" -f branch="$target" --jq '.commit.sha')
num=$(gh api -X POST "repos/$repo/pulls" -f head="$target" -f base=main -f title="V1 probe (do not merge)" \
  -f body="One-time V1 probe (runbook 2.0.4). Closed by the probe script; never merge it." --jq '.number')
log "Probe pull request #$num: commits $c1 (older) and $c2 (head)"
kept=$(gh api -X POST "repos/$repo/pulls/$num/reviews" -f commit_id="$c1" -f event=COMMENT \
  -f body="V1 probe step 4: a review pinned to the older commit." --jq '.commit_id')
if [ "$kept" = "$c1" ]; then review_ok=yes; else review_ok=no; fi
log "Step 4, review commit_id: asked $c1, GitHub kept $kept ($review_ok)"

gh api -X POST "repos/$repo/git/refs" -f ref="refs/heads/$runner" -f sha="$main_before" --silent
r=$(gh api -X PUT "repos/$repo/contents/.github/workflows/v1-probe.yml" -f message="V1 probe: runner workflow" \
  -f content="$probe" -f branch="$runner" --jq '.commit.sha')
run=""
for _ in $(seq 1 18); do
  run=$(R="$r" gh run list --repo "$repo" --branch "$runner" --event push --json databaseId,headSha \
        --jq '[.[] | select(.headSha == $ENV.R)][0].databaseId // empty')
  if [ -n "$run" ]; then break; fi
  sleep 10
done
turn_r2_off() {
  log "FAIL (V1 false): GITHUB_TOKEN merged a workflow change into main. Turning off 'Allow GitHub Actions to create and approve pull requests' now."
  gh api -X PUT "repos/$repo/actions/permissions/workflow" -F can_approve_pull_request_reviews=false --silent \
    && log "Turned off. The daily update now stops saving data (the safe state)." \
    || log "Could NOT turn it off: Settings > Actions > General > Workflow permissions > untick Allow GitHub Actions to create and approve pull requests > Save. Now."
  log "Leave MAIN_PR_BASELINE and MORNING_NOTE_SEND unset. Send this output to the team."
}
# v1-probe/verdict-race (L-c): a PASS or INCONCLUSIVE is final only after cleanup closed the probe pull request and
# a fresh read still shows it unmerged; a merge that landed meanwhile turns it into FAIL.
finish() {   # $1: 0 (PASS) or 1 (INCONCLUSIVE); $2: the verdict line
  trap - EXIT
  cleanup
  local again
  again=$(gh api "repos/$repo/pulls/$num" --jq '.merged' 2>/dev/null || true)
  log "Probe pull request merged, read again after cleanup: ${again:-unread}"
  if [ "$again" = true ]; then turn_r2_off; exit 2; fi
  if [ "$1" = 0 ] && [ "$again" != false ]; then
    log "INCONCLUSIVE: the probe pull request could not be read again after cleanup. Send this output to the team."; exit 1
  fi
  log "$2"
  exit "$1"
}
if [ -z "$run" ]; then finish 1 "INCONCLUSIVE: the probe run did not start within 3 minutes. Send this output to the team."; fi
log "Probe run: https://github.com/$repo/actions/runs/$run"
gh run watch "$run" --repo "$repo" >/dev/null 2>&1 || true
status=$(gh run view "$run" --repo "$repo" --json status --jq '.status' 2>/dev/null || true)
log "Probe run status: ${status:-unread}"
lines=$(gh run view "$run" --repo "$repo" --log 2>/dev/null | grep -oE "V1-(RESULT|MERGED) (squash|merge|rebase|graphql).*" || true)
main_after=$(gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha' || true)
while IFS= read -r line; do [ -n "$line" ] && log "$line"; done <<< "$lines"
log "main after: $main_after"
# The verdict comes from the probe PR and the canary file, not from main's sha (any other merge moves main).
pr_merged=$(gh api "repos/$repo/pulls/$num" --jq '.merged' 2>/dev/null || true)
canary=unread
if canary_out=$(gh api "repos/$repo/contents/.github/workflows/v1-canary.yml?ref=main" --jq '.sha' 2>&1); then
  if [[ "$canary_out" =~ ^[0-9a-f]{40}$ ]]; then canary=on-main; fi
elif grep -q "HTTP 404" <<< "$canary_out"; then
  canary=absent
fi
log "Probe pull request merged: ${pr_merged:-unread}. v1-canary.yml on main: $canary"

refused=$(grep -cE "^V1-RESULT (squash|merge|rebase|graphql) exit=[1-9]" <<< "$lines" || true)
named=$(grep -E "^V1-RESULT (squash|merge|rebase|graphql) exit=[1-9]" <<< "$lines" | grep -ci "without .workflows. permission" || true)
if grep -qE "^V1-MERGED (squash|merge|rebase|graphql)" <<< "$lines" || [ "$pr_merged" = true ] || [ "$canary" = on-main ]; then
  turn_r2_off
  if [ "$pr_merged" = true ]; then num=""; fi   # the pull request is merged: nothing to close
  exit 2
fi
if [ "$status" != completed ]; then
  finish 1 "INCONCLUSIVE: the probe run had not finished ('${status:-unread}'), so its answers are not final. 'Allow GitHub Actions to create and approve pull requests' is left on. Send this output to the team."
fi
if [ "$pr_merged" != false ] || [ "$canary" != absent ] || ! [[ "$main_after" =~ ^[0-9a-f]{40}$ ]] \
   || [ "$main_after" != "$main_before" ]; then
  finish 1 "INCONCLUSIVE: the probe pull request is not shown merged, but main moved during the probe or a read failed (see above). 'Allow GitHub Actions to create and approve pull requests' is left on. Send this output to the team."
fi
if [ "$refused" = 4 ] && [ "$named" = 4 ] && [ "$review_ok" = yes ]; then
  finish 0 "PASS: all four merges (squash, merge, rebase, GraphQL) refused for the workflows permission, main unchanged, review commit_id kept. Send this output to the team."
fi
finish 1 "INCONCLUSIVE: refused $refused of 4, $named naming the workflows permission, review commit_id kept: $review_ok. Send this output to the team."
