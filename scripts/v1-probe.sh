#!/usr/bin/env bash
# V1 probe, one time (docs/architecture/main-protect-invariant.md "V1 probe"; runbook docs/ops/morning-note.md 2.0.4;
# task T4.10.1). The bash twin of scripts/v1-probe.ps1, which is the one Brian runs.
#
# Question (V1', ADR 0010 decision 5): with the code-owner rule R1' on, does GitHub refuse GITHUB_TOKEN merging a pull
# request that changes anything outside data/, even after the bot approved it? Signed in as the owner (gh auth login,
# with the workflow scope; asked for only after the guard below passed), the script:
#   1. checks R1' is on (guard) and a daily data PR was merged by GitHub Actions (so bot merges work);
#   2. pushes three throwaway branches and opens their pull requests into main (author: you): W probe/v1-target
#      (an inert .github/workflows/v1-canary.yml, two commits), N probe/v1-target-n (sitegen/v1-probe-canary.txt),
#      H1 probe/v1-target-h1 (only renames .github/CODEOWNERS to data/v1-probe-CODEOWNERS);
#   3. posts a COMMENT review on W pinned to the OLDER commit and checks GitHub keeps that commit_id (step 4);
#   4. pushes probe/v1-runner (main plus .github/workflows/v1-probe.yml), which starts a run that, for each target,
#      posts a GITHUB_TOKEN APPROVE review, then tries squash, merge, rebase (REST) and GraphQL mergePullRequest;
#   5. reads the run's answers, whether each probe PR merged, whether each probe file is on main, and main's sha
#      before and after; prints PASS, FAIL or INCONCLUSIVE, and cleans up (closes every probe PR, deletes every
#      probe branch).
# PASS: for every target, both squash tries refused naming code-owner review, merge and rebase refused. FAIL means a
# probe PR merged or a probe file is on main (v1-probe/verdict-from-main-sha): then it turns "Allow GitHub Actions to
# create and approve pull requests" off at once. main moving for another reason, or a read that failed, is
# INCONCLUSIVE and leaves that setting on.
# v1-probe/verdict-race (L-c): the run must read `completed` before its answers count (else INCONCLUSIVE), and a PASS
# or INCONCLUSIVE stands only if the probe PR, read again after cleanup closed it, is still unmerged.
# Writes the result to v1-probe-results-<time>.txt in RESULTS_DIR (default: the home folder). Nothing is sent.
set -euo pipefail
repo=gn0sh/clarksville-records
here="$(cd "$(dirname "$0")" && pwd)"
target=probe/v1-target
target_n=probe/v1-target-n
target_h=probe/v1-target-h1
file_w=.github/workflows/v1-canary.yml
file_n=sitegen/v1-probe-canary.txt
file_h=data/v1-probe-CODEOWNERS
runner=probe/v1-runner
out_dir="${RESULTS_DIR:-$HOME}"
results="$out_dir/v1-probe-results-$(date +%Y%m%d-%H%M).txt"
log() { echo "$1"; echo "$1" >> "$results"; }
api_quiet() { gh api "$@" --silent >/dev/null 2>&1 || true; }

gh auth status >/dev/null 2>&1 || { echo "Not signed in: run gh auth login (as the repository owner)."; exit 1; }
# v1-probe/rerun-after-fail (ADR 0010): the probe found FAIL on 2026-11-18 (GitHub let GITHUB_TOKEN merge a workflow
# change into main). Turning "Allow GitHub Actions to create and approve pull requests" off does not stop merging, so
# running the probe again would put the canary on main again. It runs only once main's ruleset requires a code
# owner's review (R1', scripts/protect-main.sh), which is what a new run tests. The rule is vacuous without an owner,
# so it also needs .github/CODEOWNERS on main whose rules are `* @gn0sh` first and nothing else but `/data/` (a later
# line overrides an earlier one: v1-probe/rerun-after-fail-codeowners-override), no CODEOWNERS errors, every ruleset
# that carries the rule active (not evaluate or disabled), and its bypass list empty or exactly the admin role in
# pull request mode (v1-probe/rerun-after-fail-bypass). Any failed read stops it (fail closed). It runs before
# `gh auth refresh`, so a refusal opens no browser.
refuse_rerun() {
  echo "Stopped: $1 (ADR 0010: run scripts/protect-main.sh first). The probe found FAIL on 2026-11-18; running it now would merge the canary into main again. Nothing was changed."
  exit 1
}
owner_rules=$(gh api "repos/$repo/rules/branches/main" \
  --jq '.[] | select(.parameters.require_code_owner_review == true) | .ruleset_id' 2>/dev/null) \
  || refuse_rerun "could not read main's rules"
if [ -z "$owner_rules" ]; then refuse_rerun "main's ruleset does not require a code owner's review yet"; fi
for id in $owner_rules; do
  if ! [[ "$id" =~ ^[0-9]+$ ]]; then refuse_rerun "could not read main's rules"; fi
  enforcement=$(gh api "repos/$repo/rulesets/$id" --jq '.enforcement' 2>/dev/null) \
    || refuse_rerun "could not read ruleset $id"
  if [ "$enforcement" != active ]; then
    refuse_rerun "ruleset $id requires a code owner's review but its enforcement is '$enforcement', not active"
  fi
  bypass=$(gh api "repos/$repo/rulesets/$id" --jq '.bypass_actors[] | [.actor_type, .actor_id, .bypass_mode] | @tsv' \
           2>/dev/null) || refuse_rerun "could not read ruleset $id's bypass list"
  bypass=$(printf '%s' "$bypass" | tr '\t' ':' | paste -sd, -)
  if [ -n "$bypass" ] && [ "$bypass" != "RepositoryRole:5:pull_request" ]; then
    refuse_rerun "ruleset $id lets '$bypass' bypass it (only the admin role in pull request mode, RepositoryRole:5:pull_request, may)"
  fi
done
codeowners=$(gh api -H 'Accept: application/vnd.github.raw' "repos/$repo/contents/.github/CODEOWNERS?ref=main" 2>/dev/null) \
  || refuse_rerun "could not read .github/CODEOWNERS on main"
# its rules: comments and blank lines dropped, runs of spaces or tabs made one space, ends trimmed
co_rules=$(printf '%s\n' "$codeowners" | tr -d '\r' | grep -Ev '^[[:space:]]*(#|$)' \
           | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//' | paste -sd'|' - || true)
case "$co_rules" in
  '* @gn0sh'|'* @gn0sh|/data/') ;;
  *) refuse_rerun ".github/CODEOWNERS on main is not '* @gn0sh' (then only '/data/'): its rules are '$co_rules'" ;;
esac
owner_errors=$(gh api "repos/$repo/codeowners/errors?ref=main" --jq '.errors | length' 2>/dev/null) \
  || refuse_rerun "could not read GitHub's CODEOWNERS errors"
if [ "$owner_errors" != 0 ]; then refuse_rerun "GitHub lists '$owner_errors' error(s) in .github/CODEOWNERS"; fi
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
for b in "$target" "$target_n" "$target_h" "$runner"; do api_quiet -X DELETE "repos/$repo/git/refs/heads/$b"; done   # leftovers
nums=()
cleanup() {   # every probe pull request closed, every probe branch deleted
  local n b
  for n in "${nums[@]}"; do api_quiet -X PATCH "repos/$repo/pulls/$n" -f state=closed; done
  for b in "$target" "$target_n" "$target_h" "$runner"; do api_quiet -X DELETE "repos/$repo/git/refs/heads/$b"; done
}
trap cleanup EXIT
setup_failed() { log "INCONCLUSIVE: could not set up the probe branches or pull requests (see the messages above). Send this output to the team."; exit 1; }
open_pr() {   # $1 branch, $2 target name: opens its pull request into main, prints the number
  gh api -X POST "repos/$repo/pulls" -f head="$1" -f base=main -f title="V1 probe $2 (do not merge)" \
    -f body="One-time V1' probe (runbook 2.0.4). Closed by the probe script; never merge it." --jq '.number'
}

canary=$(base64 -w0 < "$here/v1-probe/v1-canary.yml")
canary2=$( { cat "$here/v1-probe/v1-canary.yml"; echo "# second commit of the probe"; } | base64 -w0)
probe=$(base64 -w0 < "$here/v1-probe/v1-probe.yml")
# W: an inert workflow file, two commits (the older one carries the step 4 review)
gh api -X POST "repos/$repo/git/refs" -f ref="refs/heads/$target" -f sha="$main_before" --silent || setup_failed
read -r c1 blob <<< "$(gh api -X PUT "repos/$repo/contents/$file_w" -f message="V1 probe: inert canary workflow" \
  -f content="$canary" -f branch="$target" --jq '[.commit.sha, .content.sha] | @tsv')"
c2=$(gh api -X PUT "repos/$repo/contents/$file_w" -f message="V1 probe: second commit" \
  -f content="$canary2" -f sha="$blob" -f branch="$target" --jq '.commit.sha')
num=$(open_pr "$target" W) || setup_failed
nums+=("$num")
# N (M2): one non-workflow file outside data/
gh api -X POST "repos/$repo/git/refs" -f ref="refs/heads/$target_n" -f sha="$main_before" --silent || setup_failed
gh api -X PUT "repos/$repo/contents/$file_n" -f message="V1 probe: inert non-workflow file" \
  -f content="$(printf 'V1 probe: inert, never merge.\n' | base64 -w0)" -f branch="$target_n" --silent || setup_failed
num_n=$(open_pr "$target_n" N) || setup_failed
nums+=("$num_n")
# H1 (main-protect/codeowners-rename-vacuous): only renames .github/CODEOWNERS into data/ (same blob, new path)
co_blob=$(gh api "repos/$repo/contents/.github/CODEOWNERS?ref=$main_before" --jq '.sha') || setup_failed
base_tree=$(gh api "repos/$repo/git/commits/$main_before" --jq '.tree.sha') || setup_failed
tree=$(printf '{"base_tree":"%s","tree":[{"path":".github/CODEOWNERS","mode":"100644","type":"blob","sha":null},{"path":"%s","mode":"100644","type":"blob","sha":"%s"}]}' \
         "$base_tree" "$file_h" "$co_blob" | gh api -X POST "repos/$repo/git/trees" --input - --jq '.sha') || setup_failed
commit_h=$(gh api -X POST "repos/$repo/git/commits" -f message="V1 probe: rename CODEOWNERS into data/" -f tree="$tree" \
             -f "parents[]=$main_before" --jq '.sha') || setup_failed
gh api -X POST "repos/$repo/git/refs" -f ref="refs/heads/$target_h" -f sha="$commit_h" --silent || setup_failed
num_h=$(open_pr "$target_h" H1) || setup_failed
nums+=("$num_h")
for n in "${nums[@]}"; do [[ "$n" =~ ^[0-9]+$ ]] || setup_failed; done
[[ "$c1" =~ ^[0-9a-f]{40}$ && "$c2" =~ ^[0-9a-f]{40}$ ]] || setup_failed
log "Probe pull requests: W #$num (commits $c1 older, $c2 head), N #$num_n, H1 #$num_h"
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
  log "FAIL (V1' false): GITHUB_TOKEN merged a probe pull request into main. Turning off 'Allow GitHub Actions to create and approve pull requests' now."
  gh api -X PUT "repos/$repo/actions/permissions/workflow" -F can_approve_pull_request_reviews=false --silent \
    && log "Turned off: workflows can no longer open pull requests, so the daily update stops saving data." \
    || log "Could NOT turn it off: Settings > Actions > General > Workflow permissions > untick Allow GitHub Actions to create and approve pull requests > Save. Now."
  log "Leave GitHub Actions on and open pull requests open: only someone with write access can start a workflow that merges (ADR 0010, invariant T1-T8)."
  log "The canary is removed by a person's pull request (scripts/merge-reviewed.sh); the team opens it."
  log "Leave MAIN_PR_BASELINE and MORNING_NOTE_SEND unset. Send this output to the team: the fallback, data off main, goes to a Brain Trust (ADR 0010)."
}
# v1-probe/verdict-race (L-c): a PASS or INCONCLUSIVE is final only after cleanup closed every probe pull request and
# a fresh read still shows each unmerged; a merge that landed meanwhile turns it into FAIL.
finish() {   # $1: 0 (PASS) or 1 (INCONCLUSIVE); $2: the verdict line
  trap - EXIT
  cleanup
  local again n unread=""
  for n in "${nums[@]}"; do
    again=$(gh api "repos/$repo/pulls/$n" --jq '.merged' 2>/dev/null || true)
    log "Probe pull request #$n merged, read again after cleanup: ${again:-unread}"
    if [ "$again" = true ]; then turn_r2_off; exit 2; fi
    [ "$again" = false ] || unread=yes
  done
  if [ "$1" = 0 ] && [ -n "$unread" ]; then
    log "INCONCLUSIVE: a probe pull request could not be read again after cleanup. Send this output to the team."; exit 1
  fi
  log "$2"
  exit "$1"
}
if [ -z "$run" ]; then finish 1 "INCONCLUSIVE: the probe run did not start within 3 minutes. Send this output to the team."; fi
log "Probe run: https://github.com/$repo/actions/runs/$run"
gh run watch "$run" --repo "$repo" >/dev/null 2>&1 || true
status=$(gh run view "$run" --repo "$repo" --json status --jq '.status' 2>/dev/null || true)
log "Probe run status: ${status:-unread}"
# v1-probe/log-raw-to-console: the run's log is untrusted text; drop ANSI colour codes, then control characters,
# before any of it is matched or printed.
log_text=$(gh run view "$run" --repo "$repo" --log 2>/dev/null | sed -E $'s|\x1b\\[[0-9;?]*[ -/]*[@-~]||g' \
           | tr -d '\000-\010\013-\037\177' || true)
lines=$(grep -oE "V1-(RESULT|MERGED|APPROVE) (W|N|H1) .*" <<< "$log_text" || true)
# v1-probe/node-read-under-e: the run's own V1-ERROR lines reach Brian too (not the step's echo text the log shows).
errors=$(grep -v 'echo "V1-ERROR' <<< "$log_text" | grep -oE "V1-ERROR: .*" || true)
main_after=$(gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha' || true)
while IFS= read -r line; do [ -n "$line" ] && log "$line"; done <<< "$lines"
while IFS= read -r line; do [ -n "$line" ] && log "$line"; done <<< "$errors"
log "main after: $main_after"
# The verdict comes from the probe PRs and the probe files, not from main's sha (any other merge moves main).
any_merged=""; all_unmerged=yes; not_merged=()
for n in "${nums[@]}"; do
  m=$(gh api "repos/$repo/pulls/$n" --jq '.merged' 2>/dev/null || true)
  log "Probe pull request #$n merged: ${m:-unread}"
  if [ "$m" = true ]; then any_merged=yes; else not_merged+=("$n"); fi
  [ "$m" = false ] || all_unmerged=""
done
on_main=""; all_absent=yes
for f in "$file_w" "$file_n" "$file_h"; do
  state=unread
  if out=$(gh api "repos/$repo/contents/$f?ref=main" --jq '.sha' 2>&1); then
    if [[ "$out" =~ ^[0-9a-f]{40}$ ]]; then state=on-main; fi
  elif grep -q "HTTP 404" <<< "$out"; then
    state=absent
  fi
  log "$f on main: $state"
  if [ "$state" = on-main ]; then on_main=yes; fi
  [ "$state" = absent ] || all_absent=""
done

if grep -qE "^V1-MERGED (W|N|H1) " <<< "$lines" || [ -n "$any_merged" ] || [ -n "$on_main" ]; then
  turn_r2_off
  nums=("${not_merged[@]}")   # a merged pull request is not closed again
  exit 2
fi
if [ "$status" != completed ]; then
  finish 1 "INCONCLUSIVE: the probe run had not finished ('${status:-unread}'), so its answers are not final. 'Allow GitHub Actions to create and approve pull requests' is left on. Send this output to the team."
fi
if [ -z "$all_unmerged" ] || [ -z "$all_absent" ] || ! [[ "$main_after" =~ ^[0-9a-f]{40}$ ]] \
   || [ "$main_after" != "$main_before" ]; then
  finish 1 "INCONCLUSIVE: no probe pull request is shown merged, but main moved during the probe or a read failed (see above). 'Allow GitHub Actions to create and approve pull requests' is left on. Send this output to the team."
fi
# V1' (ADR 0010 decision 5; M1 v1-probe/pass-not-proving-u1): for every target, the bot's approval was posted,
# REST squash and GraphQL squash were both refused naming code-owner review, and merge and rebase were refused
# (method refused: squash only). Anything else is INCONCLUSIVE.
proven=0; summary=""
for t in W N H1; do
  ok=yes
  grep -qE "^V1-APPROVE $t exit=0( |$)" <<< "$lines" || ok=""
  for m in squash graphql; do
    grep -E "^V1-RESULT $t $m exit=[1-9]" <<< "$lines" | grep -qi "code owner" || ok=""
  done
  for m in merge rebase; do
    grep -qE "^V1-RESULT $t $m exit=[1-9]" <<< "$lines" || ok=""
  done
  if [ -n "$ok" ]; then proven=$((proven + 1)); summary="$summary $t:proven"; else summary="$summary $t:not-proven"; fi
done
if [ "$proven" = 3 ] && [ "$review_ok" = yes ]; then
  finish 0 "PASS (V1'): for W, N and H1, the bot's approval did not count: REST squash and GraphQL squash refused for code-owner review, merge and rebase refused (method refused); main unchanged, every probe pull request unmerged, no probe file on main, review commit_id kept. Send this output to the team."
fi
finish 1 "INCONCLUSIVE:$summary (each needs the bot approval posted, both squash tries refused naming code-owner review, merge and rebase refused); review commit_id kept: $review_ok. Send this output to the team."
