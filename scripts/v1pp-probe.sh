#!/usr/bin/env bash
# V1'' probe, one time (ADR 0011 decision 7 and Amendment (c) item 6; docs/architecture/v1-fail-2026-11-18.md
# section 4; task V1 in docs/tasks/data-off-main.md; runbook docs/ops/morning-note.md section 4 item 6a). The bash twin
# of scripts/v1pp-probe.ps1, which is the one Brian runs. Brian's PC only: refused in a cloud session or CI.
#
# Question: after the cutover (R1'' on main: the ruleset maximum of approvals, squash only, bypass = the admin role in
# pull request mode; R-D; R-T; R2 off), can GITHUB_TOKEN get anything into main, and can a branch or tag other than
# main reach an environment? Signed in as gn0sh (the workflow scope is asked for only after the guard passed), it:
#   0. refuses unless scripts/protect-main.sh --check --apps <answer> prints OK (no writes), main and records-data read
#      as commits and no tag named main exists;
#   1. pushes three targets, twice, each one commit on main: W (an inert .github/workflows/v1pp-canary.yml), N
#      (sitegen/v1pp-probe-canary.txt), D0 (data/v1pp-probe-canary.txt, data/ now refused on main too). Set G
#      (probe/v1pp-w, probe/v1pp-n, probe/v1pp-d0): you open their pull requests into main. Set B (probe/v1pp-w-bot,
#      probe/v1pp-n-bot, probe/v1pp-d0-bot): the runner's GITHUB_TOKEN tries to open them, and must be refused;
#   2. tries to create a tag named main (R-T must refuse it: PR #54 finding 2), by the REST API and by git push;
#   3. pushes probe/v1pp-env (.github/workflows/v1pp-env.yml: one job per environment, github-pages and morning-note,
#      each only an echo, and a pages-api job with no environment that calls POST pages/deployments with a made-up
#      artifact), then the tag v1pp-probe at the same commit: GitHub must refuse both runs both environments, and the
#      Pages API on branch or environment grounds (v1pp-probe/pages-api-unreachable: GitHub's own "Unable to find
#      artifact" 400 is NOT-REACHABLE, not counted: the fake artifact is refused before the branch check, by design);
#   4. pushes probe/v1pp-runner (.github/workflows/v1pp-probe.yml): its GITHUB_TOKEN run tries steps 1-3 of section 4
#      (bot pull requests, then per pull request a bot APPROVE, REST squash, merge, rebase, GraphQL squash, then a
#      direct push to main by the REST ref update and by git push); a merge or push that goes through ends the run;
#   5. reads every answer, every probe pull request's merged flag, each probe file on main and on records-data, the
#      tag main and main's sha; then cancels any probe run not completed, cleans up (closes every probe pull request,
#      deletes every probe branch and tag, and the tag main) and reads each one again. A cleanup step is PASS only
#      when its write answered (a close: closed and unmerged; a delete: done, or "Reference does not exist") and the
#      read after it agrees; else INCONCLUSIVE with the command to run.
# Waits are bounded: 3 minutes for a run to start, 12 minutes for it to finish (then it is cancelled, INCONCLUSIVE).
# Run it again after an INCONCLUSIVE: it deletes the probe branches and tag of an earlier try first.
# Every step prints one line: PASS (the expected refusal), FAIL (it went through), NOT-TRIED (skipped because an
# earlier merge or push ended the run), NOT-REACHABLE (only the pages-api step, on GitHub's artifact 400: nothing was
# deployed, and the branch check behind it cannot be reached without a real artifact; not counted) or INCONCLUSIVE (a
# read failed, or a refusal for another reason). Verdict: FAIL
# if any line is FAIL (a probe pull request merged, a probe file on main or records-data, a push to main, a tag main,
# a bot pull request or approval, a job inside an environment): then "Allow GitHub Actions to create and approve pull
# requests" is turned off at once, before cleanup. Else INCONCLUSIVE if any line is not PASS or NOT-REACHABLE. Else PASS.
# Decisions after try 1 (2026-11-21): docs/architecture/main-protect-invariant.md "V1'' try 1 inconclusive".
# Exit 0 PASS, 1 INCONCLUSIVE or refused, 2 FAIL.
# A PASS gates MORNING_NOTE_SEND only (ADR 0011 Amendment (c) item 6). A FAIL that put a commit on main makes the gate
# refuse every later run until a person moves MAIN_PR_BASELINE past that commit.
# Not here (section 4): item 5, an unattested push to records-data, is a gate unit test on a fixture repo; item 7 is the
# first scheduled run after the cutover (D3 step 8).
# Expected refusal wordings (read from GitHub's docs and the U3 control, not yet seen live for every step; any other
# wording is INCONCLUSIVE, never PASS): bot open and approve "not permitted to ... pull requests", squash and GraphQL
# "approving review", or "Repository rule violations found" with "New changes require approval from someone other
# than the last pusher" (require_last_push_approval in R1'', seen live in try 1), merge and rebase "not allowed",
# "approving review" or "rule violation", direct push "rule violation", tag main (and its git push) "rule violation", or a 422 naming no
# rule that GitHub's rule suite for this try records as R-T's creation rule failing (active), environments "not
# allowed to deploy to <env>", the Pages API "not allowed to deploy" or "protection rule".
# Writes the result to v1pp-probe-results-<time>.txt in RESULTS_DIR (default: the home folder). Nothing is sent.
# Needs: gh signed in as gn0sh (gh auth login), git, GNU base64 and date. Takes about 5 minutes.
# Run: bash scripts/v1pp-probe.sh --apps claude|none   (the same answer protect-main takes)
#
# BEGIN-REFUSAL-LOCK (v1pp-probe/run-once, v1pp-probe/lock-window): the probe pushes workflows and tries merges, so it
# runs once, by a reviewed PR. To enable that run, the PR changes exactly one line in each twin to the last UTC day it
# may run (a few days after the merge), and the PR that records the result changes it back:
#   scripts/v1pp-probe.sh:   v1pp_unlocked_until=none   ->   v1pp_unlocked_until=YYYY-MM-DD
#   scripts/v1pp-probe.ps1:  $v1ppUnlockedUntil = 'none'   ->   $v1ppUnlockedUntil = 'YYYY-MM-DD'
# Nothing below runs while it is locked, or after that day (an unlock left in place expires by itself).
v1pp_unlocked_until=2026-11-24
if ! [[ "$v1pp_unlocked_until" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "REFUSED: the V1'' probe is locked (v1pp-probe/run-once). The team enables it for one run by a reviewed PR. Nothing was changed."
  exit 1
fi
if [[ "$(date -u +%F)" > "$v1pp_unlocked_until" ]]; then
  echo "REFUSED: the V1'' probe's unlock expired after $v1pp_unlocked_until (UTC) (v1pp-probe/lock-window). Ask the team for a new one. Nothing was changed."
  exit 1
fi
# END-REFUSAL-LOCK
set -uo pipefail
repo=gn0sh/clarksville-records
owner=gn0sh
here=$(cd "$(dirname "$0")" && pwd)
usage="Usage: bash scripts/v1pp-probe.sh --apps claude|none"
apps=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apps) [ "$#" -ge 2 ] || { echo "$usage. Nothing was changed."; exit 1; }; apps=$2; shift 2 ;;
    *) echo "$usage ('$1' is not an option). Nothing was changed."; exit 1 ;;
  esac
done
case "$apps" in
  claude|none) ;;
  *) echo "$usage: --apps is the same answer protect-main takes (open https://github.com/settings/installations first). Nothing was changed."; exit 1 ;;
esac
for v in CLAUDE_CODE_REMOTE GITHUB_ACTIONS CI; do
  if [ -n "${!v:-}" ]; then
    echo "REFUSED: $v is set. The V1'' probe runs only from Brian's PC. Nothing was changed."
    exit 1
  fi
done
gh auth status >/dev/null 2>&1 || { echo "Not signed in: run gh auth login (as $owner). Nothing was changed."; exit 1; }

# ---------------------------------------------------------------------------------------------- guard (reads only)
echo "Guard: scripts/protect-main.sh --check --apps $apps (no writes) must print OK first."
pm_out=$(bash "$here/protect-main.sh" --check --apps "$apps" 2>&1); pm_rc=$?
printf '%s\n' "$pm_out"
pm_last=$(printf '%s\n' "$pm_out" | grep . | tail -n 1)
if [ "$pm_rc" != 0 ] || [ "${pm_last#OK: main is protected}" = "$pm_last" ]; then
  echo "REFUSED: protect-main --check did not print OK, so main is not as the probe assumes (R1'', R-D, R-T, R2 off). Nothing was changed. Send this output to the team."
  exit 1
fi
sha_of() {   # $1 a ref (heads/main, tags/main): prints its sha, or "absent" on a 404; returns 1 on any other answer
  local out
  if out=$(gh api "repos/$repo/git/ref/$1" --jq '.object.sha' 2>&1); then
    [[ "$out" =~ ^[0-9a-f]{40}$ ]] || return 1
    printf '%s' "$out"; return 0
  fi
  grep -q 'HTTP 404' <<< "$out" || return 1
  printf 'absent'
}
main_before=$(sha_of heads/main) || main_before=""
rd_before=$(sha_of heads/records-data) || rd_before=""
tag_before=$(sha_of tags/main) || tag_before=""
[[ "$main_before" =~ ^[0-9a-f]{40}$ ]] || { echo "REFUSED: could not read main. Nothing was changed."; exit 1; }
[[ "$rd_before" =~ ^[0-9a-f]{40}$ ]] || { echo "REFUSED: could not read records-data. Nothing was changed."; exit 1; }
[ "$tag_before" = absent ] || { echo "REFUSED: a tag named main exists or could not be read ('${tag_before:-unread}'): R-T should make that impossible. Nothing was changed. Send this output to the team."; exit 1; }

scope_added=""
give_back_scope() {   # the workflow scope this run added (a browser may open); runs last, after the verdict
  if [ -n "$scope_added" ]; then
    scope_added=""
    echo "Removing the workflow scope this probe added to your GitHub CLI sign-in (a browser may open)."
    gh auth refresh -h github.com --remove-scopes workflow || echo "Could not remove it: run gh auth refresh -h github.com --remove-scopes workflow"
  fi
}
if ! gh auth status 2>&1 | grep -q "workflow"; then
  echo "Your GitHub CLI sign-in needs the workflow scope to push the probe's workflow files: a browser opens."
  gh auth refresh -h github.com -s workflow || { echo "Could not add the workflow scope (see above). Nothing was changed."; exit 1; }
  scope_added=yes
fi
work=$(mktemp -d) || { give_back_scope; echo "Could not make a temporary folder. Nothing was changed."; exit 1; }
out_dir="${RESULTS_DIR:-$HOME}"
results="$out_dir/v1pp-probe-results-$(date +%Y%m%d-%H%M).txt"
if ! : > "$results"; then give_back_scope; rm -rf "$work"; echo "Could not write $results. Nothing was changed."; exit 1; fi

# ---------------------------------------------------------------------------------------------- the record
log() { printf '%s\n' "$1"; printf '%s\n' "$1" >> "$results"; }
fails=0; others=0; unreach=0
mark() {   # $1 PASS|FAIL|NOT-TRIED|NOT-REACHABLE|INCONCLUSIVE, $2 the step, $3 what was seen
  log "$1 $2: $3"
  case "$1" in
    PASS) ;;
    NOT-REACHABLE) unreach=$((unreach + 1)) ;;   # pages_refused only (v1pp-probe/pages-api-unreachable)
    FAIL) fails=$((fails + 1)); turn_r2_off ;;
    *) others=$((others + 1)) ;;
  esac
}
api_quiet() { gh api "$@" --silent >/dev/null 2>&1 || true; }
# read-after-write (docs/architecture/read-after-write-invariant.md): after a write to GitHub, its confirming read may
# lag. read_until <what> <expected> <cmd...> runs <cmd> up to 10 times, 3 s apart (never after the last), and returns 0
# on the first read that exits 0 and prints exactly <expected>; a failed read or any other value is "not yet". Else it
# says what it read last and returns 1. The write is never retried. Sets rlast (the last read) and rrc (its exit code).
# The same text in every script that uses it (tests pin that).
read_until() {
  local what=$1 want=$2 i
  shift 2
  rlast=""; rrc=1
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if rlast=$("$@"); then rrc=0; else rrc=$?; fi
    [ "$rrc" = 0 ] && [ "$rlast" = "$want" ] && return 0
    [ "$i" = 10 ] || sleep 3
  done
  if [ "$rrc" = 0 ]; then echo "$what reads '$rlast', not '$want', after 10 reads."
  else echo "$what: could not read the state, not '$want', after 10 reads."; fi
  return 1
}

# v1pp-probe/tag-main-unnamed-422 (try 1: POST git/refs answered a bare 422 "Reference update failed"). Right after
# the REST try, tag_suite reads GitHub's own record of it, its rule suite (GET rulesets/rule-suites, fields per GitHub's
# OpenAPI description): exactly one suite on refs/tags/main with after_sha = main, actor_name = owner and pushed_at at
# or after tag_t0 (checked to be YYYY-MM-DDTHH:MM:SSZ first: v1pp-probe/tag-main-t0-unchecked), suite result fail, and
# exactly one evaluation from R-T (ruleset id rt_id) of rule_type creation, with result fail and enforcement active.
# It is read before the git push try, whose own suite would otherwise be a second match. Then tag_git tries the same
# tag by git push (GH013 names the rule). How the lines combine (main-protect-invariant.md "V1'' try 1 inconclusive"
# item 2): a bare 422 is PASS on its rule suite; or, only when no suite could be seen or read (tag_soft), when the git
# push line is PASS; a suite that contradicts R-T, or two suites, stays INCONCLUSIVE whatever git says.
rt_id=27685093   # R-T "tag main: blocked" (docs/platform-facts.md "Main protection"); a recreated R-T = INCONCLUSIVE
tag_t0=""; tag_proof=""; tag_why=""; tag_soft=""; tag_git_kind=""
tag_suite() {   # sets tag_proof (it proves R-T), else tag_why (why not) and tag_soft (yes: no suite seen or read)
  local i ids n sid="" ev evl detail
  tag_proof=""; tag_why=""; tag_soft=""
  if ! [[ "$tag_t0" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]]; then
    tag_why="the rule suite was not read: the start time could not be computed ('$tag_t0')"; tag_soft=yes; return 0
  fi
  export V1PP_SHA=$main_before V1PP_T0=$tag_t0 V1PP_RT=$rt_id V1PP_RULE=creation V1PP_ACTOR=$owner
  for i in 1 2 3 4 5 6; do
    ids=$(gh api "repos/$repo/rulesets/rule-suites?ref=refs/tags/main&time_period=day&per_page=100" \
          --jq '.[] | select(.after_sha == $ENV.V1PP_SHA and .actor_name == $ENV.V1PP_ACTOR and .pushed_at >= $ENV.V1PP_T0) | .id' 2>/dev/null) || ids=""
    n=$(grep -cE '^[0-9]+$' <<< "$ids")
    if [ "$n" = 1 ]; then sid=$(grep -E '^[0-9]+$' <<< "$ids"); break; fi
    if [ "$n" -gt 1 ]; then tag_why="$n rule suites match this try, not one"; return 0; fi
    [ "$i" = 6 ] || sleep 10
  done
  if [ -z "$sid" ]; then tag_why="no rule suite recorded this try"; tag_soft=yes; return 0; fi
  # line 1: the suite's result; then result and enforcement of each creation evaluation from R-T
  if ! ev=$(gh api "repos/$repo/rulesets/rule-suites/$sid" \
       --jq '.result, (.rule_evaluations[]? | select(.rule_source.id == ($ENV.V1PP_RT | tonumber) and .rule_type == $ENV.V1PP_RULE) | .result, .enforcement)' 2>/dev/null); then
    tag_why="rule suite $sid could not be read"; tag_soft=yes; return 0
  fi
  mapfile -t evl <<< "$ev"
  detail="rule suite $sid: result=${evl[0]:-none}, R-T $rt_id creation=${evl[1]:-none} enforcement=${evl[2]:-none}"
  if [ "${#evl[@]}" = 3 ] && [ "${evl[0]}" = fail ] && [ "${evl[1]}" = fail ] && [ "${evl[2]}" = active ]; then
    tag_proof=$detail
  else tag_why="not shown to be R-T: $detail"; fi
}
tag_git() {   # the same tag by git push from a scratch clone (no hooks, no stored credentials; gh signs it in)
  local g="$work/tagpush" out gc=(-c credential.helper= -c 'credential.helper=!gh auth git-credential')
  tag_git_kind=INCONCLUSIVE
  if ! out=$(git init -q "$g" 2>&1 && GIT_TERMINAL_PROMPT=0 git -C "$g" "${gc[@]}" fetch -q --depth=1 \
       "https://github.com/$repo.git" "$main_before" 2>&1); then
    mark INCONCLUSIVE "tag main git" "could not fetch main to push from: $(flat "$out")"; return 0
  fi
  if out=$(GIT_TERMINAL_PROMPT=0 git -C "$g" "${gc[@]}" push "https://github.com/$repo.git" \
           "$main_before:refs/tags/main" 2>&1); then
    tag_git_kind=FAIL; mark FAIL "tag main git" "git push created it: $(flat "$out")"
  elif grep -qiE 'GH013|rule violation' <<< "$out"; then
    tag_git_kind=PASS; mark PASS "tag main git" "refused: $(flat "$out")"
  else mark INCONCLUSIVE "tag main git" "refused, but not naming 'rule violation': $(flat "$out")"; fi
}

g_branches=(probe/v1pp-w probe/v1pp-n probe/v1pp-d0)
b_branches=(probe/v1pp-w-bot probe/v1pp-n-bot probe/v1pp-d0-bot)
runner=probe/v1pp-runner
envb=probe/v1pp-env
ptag=v1pp-probe
file_w=.github/workflows/v1pp-canary.yml
file_n=sitegen/v1pp-probe-canary.txt
file_d=data/v1pp-probe-canary.txt
file_push=sitegen/v1pp-push.txt
file_runner=.github/workflows/v1pp-probe.yml
file_env=.github/workflows/v1pp-env.yml
probe_refs=()
for b in "${g_branches[@]}" "${b_branches[@]}" "$runner" "$envb"; do probe_refs+=("heads/$b"); done
probe_refs+=("tags/$ptag")
clean_refs=("${probe_refs[@]}" tags/main)   # v1pp-probe/tag-main-cleanup: the guard read tags/main absent, so always
nums=()            # every probe pull request into main: yours, and any the bot opened
merged_read=()     # the pull requests whose merged flag has been read (and marked)
r2_done=""; finished=""; started=""
# the three probe runs: name, pushed head, run id, looked up (v1pp-probe/inflight-run-at-cleanup)
r_names=("$runner" "$envb" "$ptag"); r_heads=("" "" ""); r_ids=("" "" ""); r_looked=("" "" "")
flat() { printf '%s' "$1" | tr '\r\n' '  '; }

r2_read() { gh api "repos/$repo/actions/permissions/workflow" --jq '.can_approve_pull_request_reviews' 2>/dev/null; }
turn_r2_off() {   # at once on the first FAIL (mark calls it), so always before cleanup (as V1')
  [ -z "$r2_done" ] || return 0
  r2_done=yes
  log "A FAIL was found: turning off 'Allow GitHub Actions to create and approve pull requests' now (R2 should already be off)."
  if gh api -X PUT "repos/$repo/actions/permissions/workflow" -F can_approve_pull_request_reviews=false --silent \
     && read_until R2 false r2_read; then
    log "R2 reads off."
  else
    log "Could NOT confirm it is off: Settings > Actions > General > Workflow permissions > untick Allow GitHub Actions to create and approve pull requests > Save. Now."
  fi
}
pr_state() { gh api "repos/$repo/pulls/$1" --jq '[.state, (.merged|tostring)] | @tsv' 2>/dev/null; }
ref_state() { local s; s=$(sha_of "$1") || return 1; if [ "$s" = absent ]; then printf absent; else printf present; fi; }
cleanup_quiet() {   # an early stop: cancel known runs, close, delete; nothing recorded
  local n r id
  for id in "${r_ids[@]}"; do [ -z "$id" ] || api_quiet -X POST "repos/$repo/actions/runs/$id/cancel"; done
  for n in "${nums[@]}"; do api_quiet -X PATCH "repos/$repo/pulls/$n" -f state=closed; done
  for r in "${clean_refs[@]}"; do api_quiet -X DELETE "repos/$repo/git/refs/$r"; done
}
close_res=(); del_res=()
cleanup() {   # v1pp-probe/cleanup-absence-read: each write's own answer is kept (read-after-write rule 6)
  local n r out
  close_res=(); del_res=()
  for n in "${nums[@]}"; do   # a merged one stays merged: its answer says so
    if out=$(gh api -X PATCH "repos/$repo/pulls/$n" -f state=closed --jq '[.state, (.merged|tostring)] | @tsv' 2>&1); then
      close_res+=("$out")
    else close_res+=("failed: $(flat "$out")"); fi
  done
  for r in "${clean_refs[@]}"; do
    if out=$(gh api -X DELETE "repos/$repo/git/refs/$r" 2>&1); then del_res+=(done)
    elif grep -q 'Reference does not exist' <<< "$out"; then del_res+=(done)
    elif [ "$r" = tags/main ] && grep -qi 'rule violation' <<< "$out"; then del_res+=(done)   # R-T refusing it
    else del_res+=("failed: $(flat "$out")"); fi
  done
}
add_num() { local n x; for n in "$@"; do for x in "${nums[@]}"; do [ "$x" = "$n" ] && continue 2; done; nums+=("$n"); done; }
list_prs() {   # $1 branch: the numbers of every pull request from it into main, one per line
  gh api "repos/$repo/pulls?state=all&base=main&head=$owner:$1" --jq '.[].number' 2>/dev/null
}
read_merged() {   # $1 pull request: its merged flag, read and marked once
  local m x
  for x in "${merged_read[@]}"; do [ "$x" = "$1" ] && return 0; done
  merged_read+=("$1")
  m=$(gh api "repos/$repo/pulls/$1" --jq '.merged' 2>/dev/null) || m=""
  case "$m" in
    false) mark PASS "pull request #$1" "unmerged" ;;
    true) mark FAIL "pull request #$1" "merged into main" ;;
    *) mark INCONCLUSIVE "pull request #$1" "could not read whether it merged" ;;
  esac
}
run_once() {   # $1 branch or tag, $2 its head: one read of the push run's id (empty: none yet; 1: unread)
  local id
  id=$(H="$2" gh run list --repo "$repo" --branch "$1" --event push --json databaseId,headSha \
       --jq '[.[] | select(.headSha == $ENV.H)][0].databaseId // empty' 2>/dev/null) || return 1
  if [[ "$id" =~ ^[0-9]+$ ]]; then printf '%s' "$id"; fi
}
run_state() { gh run view "$1" --repo "$repo" --json status --jq '.status' 2>/dev/null; }
settle_runs() {   # v1pp-probe/inflight-run-at-cleanup: no probe run may still be running when cleanup starts
  local i id s out
  for i in 0 1 2; do
    if [ -z "${r_ids[$i]}" ] && [ -n "${r_heads[$i]}" ] && [ -z "${r_looked[$i]}" ]; then
      id=$(run_once "${r_names[$i]}" "${r_heads[$i]}") || id=""
      r_ids[$i]=$id; r_looked[$i]=yes
      if [ -z "$id" ]; then
        mark INCONCLUSIVE "run ${r_names[$i]}" "pushed, but no run seen yet: if one starts, cancel it at https://github.com/$repo/actions"
      fi
    fi
    id=${r_ids[$i]}
    [ -n "$id" ] || continue
    s=$(run_state "$id") || s=""
    [ "$s" = completed ] && continue
    log "Run $id (${r_names[$i]}) reads '${s:-unread}': cancelling it before cleanup."
    out=$(gh api -X POST "repos/$repo/actions/runs/$id/cancel" 2>&1) || log "  The cancel answered: $(flat "$out")"
    if ! read_until "Run $id" completed run_state "$id"; then
      mark INCONCLUSIVE "run $id" "still '${rlast:-unread}' after the cancel: cancel it at https://github.com/$repo/actions/runs/$id"
    fi
  done
}
finish() {   # cancel, cleanup, the reads after it, the verdict; never returns
  local n r tab=$'\t' x i c d ok
  started=""; finished=yes
  for r in "${g_branches[@]}" "${b_branches[@]}"; do   # pull requests whose number this run did not learn
    if x=$(list_prs "$r"); then add_num $x; else mark INCONCLUSIVE "cleanup $r" "could not list its pull requests"; fi
  done
  settle_runs   # first: a late run's merge is then seen by the reads below, and R2 goes off before cleanup
  for n in "${nums[@]}"; do read_merged "$n"; done   # before cleanup closes them (v1pp-probe/r2-after-cleanup)
  log "Cleanup: closing ${#nums[@]} probe pull request(s), deleting ${#clean_refs[@]} ref(s)."
  cleanup
  i=0
  for n in "${nums[@]}"; do
    c=${close_res[$i]}; i=$((i + 1))
    if read_until "Pull request #$n" "closed${tab}false" pr_state "$n"; then ok=yes; else ok=""; fi
    if [ "${c#*"$tab"}" = true ] || [ "${rlast#*"$tab"}" = true ]; then
      mark FAIL "after cleanup #$n" "merged into main"
    elif [ "$c" = "closed${tab}false" ] && [ -n "$ok" ]; then
      mark PASS "after cleanup #$n" "closed, unmerged"
    else
      mark INCONCLUSIVE "after cleanup #$n" "the close answered '$c', it reads '${rlast:-unread}': close it with gh pr close $n --repo $repo"
    fi
  done
  i=0
  for r in "${clean_refs[@]}"; do
    d=${del_res[$i]}; i=$((i + 1))
    if read_until "$r" absent ref_state "$r"; then ok=yes; else ok=""; fi
    if [ "$d" = done ] && [ -n "$ok" ]; then mark PASS "after cleanup $r" "deleted"
    elif [ "$r" = tags/main ]; then
      mark INCONCLUSIVE "after cleanup $r" "the delete answered '$d', it reads '${rlast:-unread}': R-T refuses a plain DELETE, so a person removes it by editing the R-T ruleset (tag main: blocked) to allow deletion, deleting the tag, then running protect-main again"
    else mark INCONCLUSIVE "after cleanup $r" "the delete answered '$d', it reads '${rlast:-unread}': delete it with gh api -X DELETE repos/$repo/git/refs/$r"; fi
  done
  rm -rf "$work"
  if [ "$fails" != 0 ]; then
    log "FAIL (V1''): $fails step(s) above went through. 'Allow GitHub Actions to create and approve pull requests' is off (see above)."
    log "If a probe commit is on main, the gate now refuses every daily run until a person moves MAIN_PR_BASELINE past it (ADR 0011 Amendment (c) item 6); the team removes the probe file by a person's pull request (scripts/merge-reviewed.sh)."
    log "Leave MORNING_NOTE_SEND unset, and do not run anything else. Send this output to the team. Saved to $results"
    give_back_scope; exit 2
  fi
  if [ "$others" != 0 ]; then
    log "INCONCLUSIVE (V1''): $others step(s) above are not PASS (a read failed, a refusal for another reason, or a step not tried); nothing was seen to go through. MORNING_NOTE_SEND stays unset. Send this output to the team. Saved to $results"
    give_back_scope; exit 1
  fi
  log "PASS (V1''): every step above was refused as expected: no pull request or push from GITHUB_TOKEN reached main, the bot could not open or approve a pull request, no tag main, no environment job and no Pages deployment for a branch or tag other than main, main unchanged, no probe file on main or records-data, and every probe pull request, branch and tag is gone. $unreach pages-api line(s) NOT-REACHABLE by design: the Pages API's own branch check is not covered (U-pages in the invariant note). Send this output to the team. Saved to $results"
  give_back_scope; exit 0
}
on_exit() {   # an exit before finish (Ctrl+C, an unexpected stop): clean up quietly
  if [ -n "$started" ]; then started=""; cleanup_quiet; fi
  rm -rf "$work"
  give_back_scope
}
trap on_exit EXIT
trap 'exit 130' INT TERM

log "V1'' probe $(date -u +%FT%TZ). main before: $main_before. records-data before: $rd_before."
for r in "${probe_refs[@]}"; do api_quiet -X DELETE "repos/$repo/git/refs/$r"; done   # leftovers of an earlier try
started=yes

# ---------------------------------------------------------------------------------------------- setup (writes)
setup_failed() { mark INCONCLUSIVE setup "$1 (see the messages above)"; finish; }
b64() { base64 -w0; }
pushed=""
push_file() {   # $1 branch, $2 path, $3 base64 content, $4 message: the branch at main_before plus one commit (sets pushed)
  pushed=""
  gh api -X POST "repos/$repo/git/refs" -f ref="refs/heads/$1" -f sha="$main_before" --silent || return 1
  pushed=$(gh api -X PUT "repos/$repo/contents/$2" -f message="$4" -f content="$3" -f branch="$1" --jq '.commit.sha') \
    || return 1
  [[ "$pushed" =~ ^[0-9a-f]{40}$ ]]
}
pr_num=""
open_pr() {   # $1 branch, $2 name, $3 the pushed head: its pull request into main (read-after-write rule 6; sets pr_num)
  local i=0 out n h
  pr_num=""
  while :; do
    i=$((i + 1))
    if out=$(gh api -X POST "repos/$repo/pulls" -f head="$1" -f base=main -f title="V1pp probe $2 (do not merge)" \
        -f body="One-time V1'' probe (ADR 0011; runbook section 4 item 6a). Closed by the probe script; never merge it." \
        --jq '[(.number|tostring), (.head.sha|tostring)] | @tsv' 2>"$work/pr.err"); then
      IFS=$'\t' read -r n h <<< "$out" || true
      [[ "${n:-}" =~ ^[0-9]+$ ]] || return 1
      add_num "$n"
      [ "${h:-}" = "$3" ] || { echo "Pull request #$n has head '${h:-}', not the pushed $3."; return 1; }
      pr_num=$n; return 0
    fi
    cat "$work/pr.err" 2>/dev/null
    grep -q '(HTTP 422)' "$work/pr.err" 2>/dev/null || return 1   # anything else: a pull request may exist (cleanup lists them)
    [ "$i" != 10 ] || return 1
    sleep 3
  done
}
canary=$(b64 < "$here/v1pp-probe/v1pp-canary.yml") || setup_failed "could not read scripts/v1pp-probe/v1pp-canary.yml"
envwf=$(b64 < "$here/v1pp-probe/v1pp-env.yml") || setup_failed "could not read scripts/v1pp-probe/v1pp-env.yml"
runwf=$(b64 < "$here/v1pp-probe/v1pp-probe.yml") || setup_failed "could not read scripts/v1pp-probe/v1pp-probe.yml"
text_n=$(printf 'V1pp probe: inert, never merge.\n' | b64)
text_d=$(printf 'V1pp probe: a data/ file, never on main.\n' | b64)
heads=()
i=0
for b in "${g_branches[@]}" "${b_branches[@]}"; do
  case $((i % 3)) in 0) f=$file_w; c=$canary ;; 1) f=$file_n; c=$text_n ;; *) f=$file_d; c=$text_d ;; esac
  push_file "$b" "$f" "$c" "V1pp probe: $f" || setup_failed "could not push $b"
  heads+=("$pushed"); i=$((i + 1))
done
g_nums=(); g_names=(W N D0)
for i in 0 1 2; do
  open_pr "${g_branches[$i]}" "${g_names[$i]}" "${heads[$i]}" || setup_failed "could not open the pull request for ${g_branches[$i]}"
  g_nums+=("$pr_num")
done
log "Probe pull requests (yours): W #${g_nums[0]}, N #${g_nums[1]}, D0 #${g_nums[2]}. Bot branches: ${b_branches[*]}."
# F2 (R-T): a tag named main must not be creatable, by anyone: by the REST API, then by git push
tag_t0=$(date -u -d '-60 seconds' +%FT%TZ 2>/dev/null)   # rule suites of this try are pushed at or after it (skew margin)
tag_bare=""
if out=$(gh api -X POST "repos/$repo/git/refs" -f ref=refs/tags/main -f sha="$main_before" --jq '.ref' 2>&1); then
  mark FAIL "tag main" "GitHub created it: $(printf '%s' "$out" | tr '\r\n' '  ')"
elif grep -qi 'rule violation' <<< "$out"; then
  mark PASS "tag main" "refused ($(printf '%s' "$out" | tr '\r\n' '  '))"
elif grep -q 'HTTP 422' <<< "$out"; then
  tag_bare=$(flat "$out"); tag_suite   # its rule suite, read now: before the git push adds a second one
else
  mark INCONCLUSIVE "tag main" "failed without naming a rule: $(printf '%s' "$out" | tr '\r\n' '  ')"
fi
tag_git
if [ -n "$tag_bare" ]; then
  if [ -n "$tag_proof" ]; then mark PASS "tag main" "refused ($tag_bare); $tag_proof"
  elif [ -n "$tag_soft" ] && [ "$tag_git_kind" = PASS ]; then
    mark PASS "tag main" "refused ($tag_bare), naming no rule, and $tag_why; R-T, which has no bypass actor, is shown refusing the same tag on the git line above, and 'tag main after' reads that it is absent"
  elif [ "$tag_why" = "no rule suite recorded this try" ]; then
    mark INCONCLUSIVE "tag main" "failed without naming a rule, and no rule suite recorded this try, and the git line is not PASS: $tag_bare (see https://github.com/$repo/rules/insights)"
  else mark INCONCLUSIVE "tag main" "refused ($tag_bare), but $tag_why"; fi
fi
push_file "$envb" "$file_env" "$envwf" "V1pp probe: environment refusal" || setup_failed "could not push $envb"
env_head=$pushed; r_heads[1]=$env_head
gh api -X POST "repos/$repo/git/refs" -f ref="refs/tags/$ptag" -f sha="$env_head" --silent \
  || setup_failed "could not create the tag $ptag"
r_heads[2]=$env_head
push_file "$runner" "$file_runner" "$runwf" "V1pp probe: runner workflow" || setup_failed "could not push $runner"
run_head=$pushed; r_heads[0]=$run_head

# ---------------------------------------------------------------------------------------------- the runs (reads)
run_of() {   # $1 branch or tag, $2 its head: the push run's id, or nothing after 3 minutes
  local id i
  for i in $(seq 1 18); do
    id=$(run_once "$1" "$2") || id=""
    if [ -n "$id" ]; then printf '%s' "$id"; return 0; fi
    [ "$i" = 18 ] || sleep 10
  done
  return 1
}
wait_run() {   # $1 run id: v1pp-probe/unbounded-watch: up to 12 minutes (72 reads, 10 s apart); prints the last status
  local s="" i
  for i in $(seq 1 72); do
    s=$(run_state "$1") || s=""
    [ "$s" = completed ] && break
    [ "$i" = 72 ] || sleep 10
  done
  printf '%s' "$s"
}
clean_log() {   # untrusted text: ANSI colour codes, then control characters, are dropped
  sed -E $'s|\x1b\\[[0-9;?]*[ -/]*[@-~]||g' | tr -d '\000-\010\013-\037\177'
}
run_jobs() {   # $1 run id: one line per job, name TAB id TAB status TAB conclusion; returns 1 when unread
  gh api "repos/$repo/actions/runs/$1/jobs" \
    --jq '.jobs[] | [.name, (.id|tostring), .status, (.conclusion|tostring)] | @tsv' 2>/dev/null
}
# v1pp-probe/run-log-missing (try 1: gh run view --log gave nothing for a finished run whose job log held the line):
# each job's own log (GET actions/jobs/<id>/logs), read up to 6 times, 10 s apart (never after the last), until a read
# succeeds and holds $2 (an ERE); prints the last log read, cleaned; returns 1 if no read succeeded.
job_log() {
  local i t text="" got=""
  for i in 1 2 3 4 5 6; do
    if t=$(gh api "repos/$repo/actions/jobs/$1/logs" 2>/dev/null); then
      got=yes; text=$(printf '%s\n' "$t" | clean_log)
      grep -qE "$2" <<< "$text" && break
    fi
    [ "$i" = 6 ] || sleep 10
  done
  [ -n "$got" ] || return 1
  printf '%s\n' "$text"
}
run_id=$(run_of "$runner" "$run_head") || run_id=""
r_ids[0]=$run_id; r_looked[0]=yes
lines=""
if [ -z "$run_id" ]; then
  mark INCONCLUSIVE "runner" "the probe run did not start within 3 minutes"
else
  log "Probe run: https://github.com/$repo/actions/runs/$run_id"
  st=$(wait_run "$run_id")
  if [ "$st" = completed ]; then mark PASS "runner" "the run completed"
  else mark INCONCLUSIVE "runner" "the run reads '${st:-unread}', not completed after 12 minutes, so its answers are not final (it is cancelled before cleanup)"; fi
  log_text=""
  jobs=$(run_jobs "$run_id") || jobs=""
  jids=$(awk -F'\t' '$2 ~ /^[0-9]+$/ {print $2}' <<< "$jobs")
  [ -n "$jids" ] || mark INCONCLUSIVE "runner log" "could not read the run's jobs"
  for jid in $jids; do
    if t=$(job_log "$jid" 'V1PP-(RESULT|MERGED|NOPR) (W|N|D0|WB|NB|D0B|PUSH) '); then log_text+="$t"$'\n'
    else mark INCONCLUSIVE "runner log" "could not read job $jid's log"; fi
  done
  lines=$(grep -oE "V1PP-(RESULT|MERGED|NOPR) (W|N|D0|WB|NB|D0B|PUSH)( .*)?$" <<< "$log_text" || true)
  while IFS= read -r l; do [ -n "$l" ] && log "  $l"; done <<< "$lines"
  errs=$(grep -v 'echo "V1PP-ERROR' <<< "$log_text" | grep -oE "V1PP-ERROR: .*" || true)
  while IFS= read -r l; do [ -n "$l" ] && log "  $l"; done <<< "$errs"
fi
ended=""
if grep -qE '^V1PP-MERGED ' <<< "$lines"; then ended=yes; fi
judge() {   # $1 target, $2 step, $3 what the refusal must name (an ERE, any case; empty: any refusal)
  local l code rest
  l=$(grep -E "^V1PP-RESULT $1 $2 exit=[0-9]+( |$)" <<< "$lines" | head -n 1)
  if [ -z "$l" ]; then
    if [ -n "$ended" ]; then mark NOT-TRIED "$1 $2" "skipped: an earlier merge or push ended the run"
    else mark INCONCLUSIVE "$1 $2" "no answer in the run's log"; fi
    return 0
  fi
  rest=${l#*exit=}; code=${rest%% *}
  if [ "$code" = 0 ]; then mark FAIL "$1 $2" "GitHub accepted it: $rest"
  elif [ -z "$3" ] || grep -qiE "$3" <<< "$rest"; then mark PASS "$1 $2" "refused: $rest"
  else mark INCONCLUSIVE "$1 $2" "refused, but not naming '$3': $rest"; fi
}
# v1pp-probe/squash-last-pusher: the pull_request rule of R1'' may name its require_last_push_approval condition, not
# the approval count; both are that one rule, so both count, the last-pusher one only with the ruleset header
pr_rule='approving review|Repository rule violations found.*New changes require approval from someone other than the last pusher'
judge_pr() {   # $1 target: the bot approval and every merge try on its pull request
  judge "$1" approve 'not permitted to (create or )?approve pull requests'
  judge "$1" squash "$pr_rule"
  judge "$1" merge 'not allowed|approving review|rule violation'    # v1pp-probe/unobserved-refusal-pass
  judge "$1" rebase 'not allowed|approving review|rule violation'
  judge "$1" graphql "$pr_rule"
}
i=0
for t in WB NB D0B; do
  judge "$t" open 'not permitted to create'
  if grep -qE "^V1PP-RESULT $t open exit=0( |$)" <<< "$lines"; then judge_pr "$t"; fi
  if x=$(list_prs "${b_branches[$i]}"); then
    if [ -n "$x" ]; then add_num $x; mark FAIL "$t pull request" "a pull request from ${b_branches[$i]} exists: #$(printf '%s' "$x" | paste -sd, -)"
    else mark PASS "$t pull request" "none from ${b_branches[$i]}"; fi
  else
    mark INCONCLUSIVE "$t pull request" "could not list the pull requests from ${b_branches[$i]}"
  fi
  i=$((i + 1))
done
for t in W N D0; do judge_pr "$t"; done
judge PUSH rest 'rule violation'
judge PUSH git 'rule violation'

env_refused() {   # $1 run label, $2 run id: each environment's job refused before it started
  local jobs e row id st concl ann tab=$'\t'
  if [ -z "$2" ]; then
    for e in github-pages morning-note; do mark INCONCLUSIVE "$1 $e" "the run did not start within 3 minutes"; done
    return 0
  fi
  log "Environment run ($1): https://github.com/$repo/actions/runs/$2"
  wait_run "$2" >/dev/null
  jobs=$(run_jobs "$2") || jobs=""
  for e in github-pages morning-note; do
    row=$(awk -F'\t' -v n="$e" '$1 == n' <<< "$jobs" | head -n 1)
    if [ -z "$row" ]; then mark INCONCLUSIVE "$1 $e" "could not read the job"; continue; fi
    IFS="$tab" read -r _ id st concl <<< "$row"
    if [ "$concl" = success ]; then mark FAIL "$1 $e" "the job ran inside environment $e"; continue; fi
    if [ "$st" != completed ] || [ "$concl" != failure ]; then
      mark INCONCLUSIVE "$1 $e" "the job reads '$st' '$concl', not refused"; continue
    fi
    if ! [[ "$id" =~ ^[0-9]+$ ]] || ! ann=$(gh api "repos/$repo/check-runs/$id/annotations" --jq '.[].message' 2>/dev/null); then
      mark INCONCLUSIVE "$1 $e" "could not read the job's annotations"; continue
    fi
    if grep -qiF "not allowed to deploy to $e" <<< "$ann"; then
      mark PASS "$1 $e" "refused: $(grep -iF "not allowed to deploy to $e" <<< "$ann" | head -n 1)"
    else
      mark INCONCLUSIVE "$1 $e" "the job failed without the environment refusal: $(printf '%s' "$ann" | tr '\r\n' '  ')"
    fi
  done
}
pages_refused() {   # $1 run label, $2 run id: v1pp-probe/pages-api-coverage, the pages-api job's answer
  local l code rest jid t jobs
  if [ -z "$2" ]; then mark INCONCLUSIVE "$1 pages-api" "the run did not start within 3 minutes"; return 0; fi
  jobs=$(run_jobs "$2") || jobs=""   # v1pp-probe/pages-jid-pipefail: read first, then pick the row
  jid=$(awk -F'\t' '$1 == "pages-api" {print $2; exit}' <<< "$jobs")
  if ! [[ "$jid" =~ ^[0-9]+$ ]]; then mark INCONCLUSIVE "$1 pages-api" "could not read the job"; return 0; fi
  if ! t=$(job_log "$jid" 'V1PP-RESULT PAGES api exit=[0-9]'); then
    mark INCONCLUSIVE "$1 pages-api" "could not read the job's log (job $jid)"; return 0
  fi
  l=$(grep -oE "V1PP-RESULT PAGES api exit=[0-9]+( .*)?$" <<< "$t" | head -n 1) || l=""
  if [ -z "$l" ]; then mark INCONCLUSIVE "$1 pages-api" "no answer in the job's log"; return 0; fi
  rest=${l#*exit=}; code=${rest%% *}
  if [ "$code" = 0 ]; then mark FAIL "$1 pages-api" "GitHub accepted a Pages deployment: $rest"
  elif grep -qiE 'not allowed to deploy|protection rule' <<< "$rest"; then mark PASS "$1 pages-api" "refused: $rest"
  elif grep -qF 'Unable to find artifact' <<< "$rest" && grep -qE '\(HTTP 400\)|"status":"400"' <<< "$rest"; then
    # v1pp-probe/pages-api-unreachable: GitHub's own answer to the made-up artifact (try 1); the fake artifact stays,
    # since a real one could replace the live site, so the branch check behind it is never reached: not counted
    mark NOT-REACHABLE "$1 pages-api" "by design, not counted: the made-up artifact was refused (HTTP 400) before any branch check, so nothing was deployed and the Pages API's own branch check is not covered: $rest"
  elif grep -qi 'artifact' <<< "$rest"; then
    mark INCONCLUSIVE "$1 pages-api" "artifact refused first; branch check not reached: $rest"
  else mark INCONCLUSIVE "$1 pages-api" "refused, but not on branch or environment grounds: $rest"; fi
}
env_run=$(run_of "$envb" "$env_head") || env_run=""
r_ids[1]=$env_run; r_looked[1]=yes
env_refused "branch $envb" "$env_run"
pages_refused "branch $envb" "$env_run"
tag_run=$(run_of "$ptag" "$env_head") || tag_run=""
r_ids[2]=$tag_run; r_looked[2]=yes
env_refused "tag $ptag" "$tag_run"
pages_refused "tag $ptag" "$tag_run"

# every probe pull request's merged flag (yours and any the bot opened)
for r in "${g_branches[@]}"; do x=$(list_prs "$r") && add_num $x; done
for n in "${nums[@]}"; do read_merged "$n"; done
for f in "$file_w" "$file_n" "$file_d" "$file_push" "$file_runner" "$file_env"; do
  for ref in main records-data; do
    if out=$(gh api "repos/$repo/contents/$f?ref=$ref" --jq '.sha' 2>&1); then
      if [[ "$out" =~ ^[0-9a-f]{40}$ ]]; then mark FAIL "$f on $ref" "it is there"
      else mark INCONCLUSIVE "$f on $ref" "unreadable answer"; fi
    elif grep -q 'HTTP 404' <<< "$out"; then mark PASS "$f on $ref" "absent"
    else mark INCONCLUSIVE "$f on $ref" "could not read it"; fi
  done
done
tag_after=$(sha_of tags/main) || tag_after=""
case "$tag_after" in
  absent) mark PASS "tag main after" "absent" ;;
  "") mark INCONCLUSIVE "tag main after" "could not read it" ;;
  *) mark FAIL "tag main after" "a tag named main exists at $tag_after" ;;
esac
main_after=$(sha_of heads/main) || main_after=""
if [ "$main_after" = "$main_before" ]; then mark PASS "main" "unchanged at $main_before"
elif [[ "$main_after" =~ ^[0-9a-f]{40}$ ]]; then mark INCONCLUSIVE "main" "moved during the probe: $main_before -> $main_after (the lines above say whether a probe change went in)"
else mark INCONCLUSIVE "main" "could not read it after the probe"; fi
rd_after=$(sha_of heads/records-data) || rd_after=""
log "records-data after: ${rd_after:-unread} (the daily run may move it; only the probe files above count)."
finish
