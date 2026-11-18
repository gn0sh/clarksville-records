#!/usr/bin/env bash
# U3 positive control: the bash twin of scripts/u3-toggle.ps1 (same steps, same lines, same verdicts). Design:
# docs/ops/u3-positive-control.md; ADR 0011 decision 5 (R1''); task U3-1 in docs/tasks/data-off-main.md.
#
# Question: under R1'' (2 required approvals, last-push approval, no code-owner review, squash only, admin bypass in
# pull_request mode) does the team's merge-reviewed merge of a docs-only PR go through as a bypass?
#
# Run:
#   bash scripts/u3-toggle.sh --pr <P>                       Brian's path: opens the window, waits for main to move
#   bash scripts/u3-toggle.sh --pr <P> --merge --report <R>  team path: runs scripts/merge-reviewed.sh <P> <head> <R>
#   bash scripts/u3-toggle.sh --pr <P> --rehearse            the whole preflight, then a one-minute window that PUTs
#                                                            R1' itself (no change) and restores: try Ctrl+C in it
#   bash scripts/u3-toggle.sh --restore [<backup json>]      PUTs scripts/main-ruleset-r1p.json (R1'), or that backup
#   bash scripts/u3-toggle.sh --noop                         U3-0: PUTs the live ruleset back unchanged, reads it back
#   bash scripts/u3-toggle.sh --show-body <json>             prints the PUT body built from a file; no GitHub call
#
# Steps (it stops at the first failure):
#   1. Preflight, read-only: refuses (nothing changed) from 07:30 to 10:30 UTC (a 30-minute run started then could
#      reach the daily run's 08:00-10:30), while a daily-update run is not completed, unless
#      scripts/main-ruleset.json is R1' with only the three ADR 0011 decision 5 changes, unless ruleset 27502319
#      equals R1' (scripts/main-ruleset-r1p.json) on every written field, unless PR P is open into main, authored by
#      gn0sh, from a branch of this repository, not a draft, mergeable and docs-only, and unless
#      current_user_can_bypass is pull_requests_only or always. Saves the live ruleset outside the repository and
#      prints "BACKUP <file>".
#   2. PUTs R1'' and reads it back; any difference closes the window at once. Prints
#      "U3 WINDOW OPEN <utc> BACKUP <file>". From here on every exit (error, Ctrl+C) restores R1'.
#   3. Team path: runs merge-reviewed. Brian's path: checks main every 15 s. If the team's merge is refused, the
#      manager comments "U3 merge refused: <gh's error line>" on PR P as gn0sh; that ends the wait. The window,
#      rule-suite reads included, ends 20 minutes after it opened.
#   4. Reads PR P (merged, merged_by, merge_commit_sha), the ruleset again (still R1''?) and the rule suite whose
#      after_sha is the merge commit.
#   5. Restores the backup held in memory (equal to scripts/main-ruleset-r1p.json; that file if the backup is unusable),
#      reads it back, prints "RESTORED <utc>", then one line:
#      "U3 VERDICT <PASS|FAIL-U3|FAIL-RULE|INCONCLUSIVE> rule-suite <id|none>: <detail>".
# PASS: the suite's result is bypass and its one pull_request evaluation (ruleset 27502319, enforcement active) is
# fail. FAIL-RULE: that evaluation is pass (suite bypass or pass): 2 approvals did not bind. FAIL-U3: the merge was
# refused with HTTP 405 naming reviews or approvals, P unmerged at the same head. Anything else: INCONCLUSIVE.
# Every PUT body comes from one function (wl below): only name, target, enforcement, conditions, bypass_actors
# (actor_id, actor_type, bypass_mode) and rules (type, parameters); never id, _links, source or
# current_user_can_bypass. Exit: 0 PASS (or a verified --rehearse / --restore / --noop), 1 refused before any write,
# 2 any other verdict (restored), 3 the restore (or --noop) did not read back as written.
# Needs: gh signed in as gn0sh (gh auth login) and jq.
set -uo pipefail
repo=gn0sh/clarksville-records
owner=gn0sh
rid=27502319
here=$(cd "$(dirname "$0")" && pwd)
r1p="$here/main-ruleset-r1p.json"
r1pp="$here/main-ruleset.json"
export U3_OWNER=$owner U3_RULE=pull_request U3_RID=$rid U3_REFUSED="U3 merge refused"
# The one whitelist: every PUT body and every comparison goes through it (order made canonical: rules by type).
wl='def wl: {name, target, enforcement, conditions,
  bypass_actors: ([.bypass_actors[]? | {actor_id, actor_type, bypass_mode}] | sort_by(.actor_type, .actor_id, .bypass_mode)),
  rules: ([.rules[]? | if .parameters == null then {type} else {type, parameters} end] | sort_by(.type))}; wl'
# read-only or unknown fields inside a rule or bypass actor (the whitelist would hide them in a comparison)
extras='[(.rules[]? | keys[] | select(. != "type" and . != "parameters") | "rules." + .),
  (.bypass_actors[]? | keys[] | select(. != "actor_id" and . != "actor_type" and . != "bypass_mode") | "bypass_actors." + .)] | join(",")'

usage="Usage: bash scripts/u3-toggle.sh --pr <P> [--merge --report <review report> | --rehearse] | --restore [<backup json>] | --noop | --show-body <json>"
mode=window; pr=""; merge=0; report=""; src=""; rehearse=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --pr) pr="${2:-}"; shift 2 || { echo "$usage"; exit 1; } ;;
    --merge) merge=1; shift ;;
    --rehearse) rehearse=1; shift ;;
    --report) report="${2:-}"; shift 2 || { echo "$usage"; exit 1; } ;;
    --restore) mode=restore; shift; if [ "$#" -gt 0 ] && [ "${1#--}" = "$1" ]; then src="$1"; shift; fi ;;
    --noop) mode=noop; shift ;;
    --show-body) mode=show; src="${2:-}"; shift 2 || { echo "$usage"; exit 1; } ;;
    *) echo "$usage"; exit 1 ;;
  esac
done

utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
command -v jq >/dev/null 2>&1 || { echo "jq not found: install it, then run this again. Nothing was changed."; exit 1; }
body_of() {   # $1 source json, $2 output body file: the whitelisted PUT body, re-read to prove it says the same
  jq -c "$wl" "$1" > "$2" 2>/dev/null || return 1
  [ "$(jq -S -c "$wl" "$2" 2>/dev/null)" = "$(jq -S -c "$wl" "$1" 2>/dev/null)" ] || return 1
  [ -n "$(jq -r '.name // empty' "$2")" ]
}
if [ "$mode" = show ]; then
  [ -f "$src" ] || { echo "$usage"; exit 1; }
  jq -c "$wl" "$src"; exit $?
fi
gh auth status >/dev/null 2>&1 || { echo "Not signed in: run gh auth login (as $owner). Nothing was changed."; exit 1; }

work=$(mktemp -d) || { echo "Could not make a temporary folder. Nothing was changed."; exit 1; }
read_live() {   # $1 output file: the live ruleset json
  gh api "repos/$repo/rulesets/$rid" > "$1" 2>/dev/null || return 1
  jq -e '.id' "$1" >/dev/null 2>&1
}
same_as() {   # $1 live json, $2 expected json: exact equality on every whitelisted field, no unknown nested fields
  local x
  x=$(jq -r "$extras" "$1" 2>/dev/null) || return 1
  if [ -n "$x" ]; then echo "The ruleset has fields this script does not write: $x"; return 1; fi
  [ "$(jq -S -c "$wl" "$1")" = "$(jq -S -c "$wl" "$2")" ] && return 0
  echo "The ruleset differs from $(basename "$2") (- expected, + live):"
  diff <(jq -S "$wl" "$2") <(jq -S "$wl" "$1") | grep '^[<>]' | sed 's/^</-/; s/^>/+/'
  return 1
}
put_verify() {   # $1 source json: PUT its whitelisted body, read back, compare. 0 ok, 1 body, 2 PUT, 3 read, 4 differs
  body_of "$1" "$work/body.json" || { echo "Could not build a ruleset body from $1."; return 1; }
  gh api -X PUT "repos/$repo/rulesets/$rid" --input "$work/body.json" --silent || return 2
  read_live "$work/after.json" || { echo "Could not read ruleset $rid back."; return 3; }
  same_as "$work/after.json" "$work/body.json" || return 4
}
restored=0
backup=""
restore() {   # $1 source json, $2 its name; three tries
  local i
  for i in 1 2 3; do
    if put_verify "$1"; then echo "RESTORED $(utc) (ruleset $rid read back equal to $2)"; restored=1; return 0; fi
    [ "$i" = 3 ] || sleep 5
  done
  if [ -n "$backup" ]; then
    echo "RESTORE FAILED: ruleset $rid may still be R1''. BACKUP $backup. Run: bash scripts/u3-toggle.sh --restore '$backup'. Send this output to the team."
  else
    echo "RESTORE FAILED: ruleset $rid may not be R1'. Run: bash scripts/u3-toggle.sh --restore. Send this output to the team."
  fi
  return 1
}
# ADR 0011 decision 5 pinned: R1'' is R1' except these three pull_request parameters, which take these values.
pin_ok() {
  local strip='del(.rules[] | select(.type == "pull_request") | .parameters | (.required_approving_review_count, .require_last_push_approval, .require_code_owner_review))'
  [ "$(jq -S -c "$wl | $strip" "$r1pp" 2>/dev/null)" = "$(jq -S -c "$wl | $strip" "$r1p" 2>/dev/null)" ] || return 1
  [ "$(jq -c '[.rules[] | select(.type == "pull_request") | .parameters | .required_approving_review_count, .require_last_push_approval, .require_code_owner_review]' "$r1pp" 2>/dev/null)" = '[2,true,false]' ]
}

if [ "$mode" = restore ]; then
  trap 'rm -rf "$work"' EXIT
  src="${src:-$r1p}"
  [ -f "$src" ] || { echo "No such file: $src. Nothing was changed."; exit 1; }
  restore "$src" "$(basename "$src")" && exit 0
  exit 3
fi
if [ "$mode" = noop ]; then
  trap 'rm -rf "$work"' EXIT
  read_live "$work/live.json" || { echo "Could not read ruleset $rid. Nothing was changed."; exit 1; }
  x=$(jq -r "$extras" "$work/live.json")
  [ -z "$x" ] || { echo "The ruleset has fields this script does not write ($x). Nothing was changed. Send this output to the team."; exit 1; }
  cp "$work/live.json" "$work/before.json"
  put_verify "$work/before.json"; r=$?
  case "$r" in
    0) echo "NOOP OK $(utc): ruleset $rid written with its own body and read back unchanged."; exit 0 ;;
    1) echo "NOOP REFUSED: could not build the body. Nothing was changed."; exit 1 ;;
    2) echo "NOOP REFUSED $(utc): GitHub did not accept the PUT (see gh's message and HTTP status above). Nothing was changed."; exit 1 ;;
    *) echo "NOOP CHANGED $(utc): ruleset $rid did not read back as it was. Run: bash scripts/u3-toggle.sh --restore. Send this output to the team."; exit 3 ;;
  esac
fi

# ---------------------------------------------------------------------------------------------- 1. preflight
refuse() { echo "REFUSED: $1. Nothing was changed."; exit 1; }
[[ "$pr" =~ ^[0-9]+$ ]] || { echo "$usage"; exit 1; }
if [ "$merge" = 1 ] && [ -z "$report" ]; then echo "--merge needs --report <review report of PR $pr>. $usage"; exit 1; fi
if [ "$merge" = 1 ] && [ "$rehearse" = 1 ]; then echo "--rehearse merges nothing: drop --merge. $usage"; exit 1; fi
hm=$(date -u +%H%M)
[[ "$hm" =~ ^[0-9]{4}$ ]] || refuse "could not read the UTC time"
# main-protect/window-over-20-min: a run lasts at most 30 minutes, so it must end before 08:00 or start after 10:30
if [ $((10#$hm)) -ge 730 ] && [ $((10#$hm)) -le 1030 ]; then
  refuse "it is ${hm:0:2}:${hm:2:2} UTC: a run started from 07:30 to 10:30 could reach the daily run's window (08:00-10:30); run it later"
fi
pin_ok || refuse "scripts/main-ruleset.json is not R1' with only ADR 0011 decision 5's three changes (2 approvals, last-push approval, no code-owner review)"
runs=$(gh api "repos/$repo/actions/workflows/daily-update.yml/runs?per_page=30" --jq '.workflow_runs[].status') \
  || refuse "could not read the daily-update runs"
busy=$(printf '%s\n' "$runs" | grep -cv -e '^completed$' -e '^$')
[ "$busy" = 0 ] || refuse "a daily-update run is queued or in progress; run it after that run completes"
read_live "$work/live.json" || refuse "could not read ruleset $rid"
bypass=$(jq -r '.current_user_can_bypass // "missing"' "$work/live.json")
case "$bypass" in pull_requests_only|always) ;; *) refuse "current_user_can_bypass is '$bypass', not pull_requests_only or always" ;; esac
same_as "$work/live.json" "$r1p" || refuse "ruleset $rid is not R1' (scripts/main-ruleset-r1p.json)"
# every field goes through tostring, so none is empty and a tab-split never shifts the fields
prline=""
for i in 1 2 3 4; do
  prline=$(gh api "repos/$repo/pulls/$pr" --jq '[(.state|tostring), (.base.ref|tostring), (.user.login|tostring), (.head.repo.full_name|tostring), (.head.sha|tostring), (.draft|tostring), (.mergeable|tostring), (.changed_files|tostring), (.merged|tostring)] | @tsv') \
    || refuse "could not read pull request #$pr"
  IFS=$'\t' read -r p_state p_base p_user p_repo head p_draft p_mergeable p_count p_merged <<< "$prline" || true
  [ "${p_mergeable:-}" = null ] || break   # GitHub still computing: read again
  [ "$i" = 4 ] || sleep 5
done
[ "${p_state:-}" = open ] && [ "${p_base:-}" = main ] && [ "${p_merged:-}" = false ] \
  || refuse "pull request #$pr is not open into main ($prline)"
[ "${p_user:-}" = "$owner" ] || refuse "pull request #$pr is authored by '${p_user:-}', not $owner"
[ "${p_repo:-}" = "$repo" ] || refuse "pull request #$pr's branch is in '${p_repo:-}', not $repo"
[[ "${head:-}" =~ ^[0-9a-f]{40}$ ]] || refuse "pull request #$pr's head could not be read"
[ "${p_draft:-}" = false ] || refuse "pull request #$pr is a draft"
[ "${p_mergeable:-}" = true ] || refuse "pull request #$pr is not mergeable ($p_mergeable)"
files=$(gh api --paginate "repos/$repo/pulls/$pr/files?per_page=100" --jq '.[] | [(.filename|tostring), (.previous_filename|tostring)] | @tsv') \
  || refuse "could not read pull request #$pr's files"
n=0
while IFS=$'\t' read -r f prev; do
  [ -n "$f" ] || continue
  n=$((n + 1))
  [ "$prev" != null ] || prev=""
  for name in "$f" ${prev:+"$prev"}; do
    case "$name" in docs/*) ;; *) refuse "pull request #$pr changes $name, outside docs/ (P must be docs-only)" ;; esac
  done
done <<< "$files"
[ "$n" -ge 1 ] && [ "$n" = "${p_count:-}" ] || refuse "pull request #$pr lists $n file(s), GitHub counts '${p_count:-}'"
main_before=$(gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha') || main_before=""
[[ "$main_before" =~ ^[0-9a-f]{40}$ ]] || refuse "could not read main"
stamp=$(date -u +%Y%m%d-%H%M%S)
# main-protect/u3-restore-source: the restore uses this whitelisted body, held in memory and proved equal to R1'
backup_json=$(jq -c "$wl" "$work/live.json")
[ "$(jq -S -c "$wl" <<< "$backup_json")" = "$(jq -S -c "$wl" "$r1p")" ] || refuse "the backup body is not R1'"
backup="$HOME/u3-ruleset-backup-$stamp.json"
cp "$work/live.json" "$HOME/u3-ruleset-live-$stamp.json" && body_of "$work/live.json" "$backup" \
  || { backup=""; refuse "could not save the ruleset backup in $HOME"; }
echo "Preflight passed. PR #$pr head $head, main $main_before. Live ruleset saved to $HOME/u3-ruleset-live-$stamp.json."
echo "BACKUP $backup"

# ---------------------------------------------------------------------------------------------- 2. apply R1''
armed=0; verdict=""; detail=""; why=""; suite_id=""
finish() {
  local rc=$? src
  trap '' INT TERM HUP   # a second Ctrl+C must not stop the restore (gh inherits the ignore)
  trap - EXIT
  if [ "$armed" != 1 ]; then rm -rf "$work"; exit "$rc"; fi
  src="$work/restore.json"
  if ! { [ -n "$backup_json" ] && printf '%s\n' "$backup_json" > "$src" && jq -e '.name' "$src" >/dev/null 2>&1; }; then
    src="$r1p"
  fi
  echo "Closing the window: restoring R1' ($( [ "$src" = "$r1p" ] && echo "scripts/main-ruleset-r1p.json" || echo "the backup")). BACKUP $backup"
  restore "$src" "$( [ "$src" = "$r1p" ] && echo "scripts/main-ruleset-r1p.json" || echo "the backup")" || true
  rm -rf "$work"
  if [ "$rehearse" = 1 ]; then
    if [ "$restored" = 1 ]; then echo "U3 REHEARSAL DONE: the window opened and R1' was restored and verified${why:+ ($why)}."; exit 0; fi
    echo "U3 REHEARSAL FAILED: the restore was not verified."; exit 3
  fi
  if [ -z "$verdict" ]; then verdict=INCONCLUSIVE; detail="${why:-the run stopped before a verdict (exit $rc)}"; fi
  if [ "$verdict" = PASS ] && [ "$restored" != 1 ]; then verdict=INCONCLUSIVE; detail="the restore was not verified; $detail"; fi
  echo "U3 VERDICT $verdict rule-suite ${suite_id:-none}: $detail"
  if [ "$restored" != 1 ]; then exit 3; fi
  if [ "$verdict" = PASS ]; then exit 0; fi
  exit 2
}
trap finish EXIT
trap 'why="interrupted (Ctrl+C or a stop signal)"; exit 130' INT TERM HUP
armed=1   # from here on, every exit restores (a PUT that failed half-way is restored too)
if [ "$rehearse" = 1 ]; then
  put_verify "$r1p" || { why="R1' did not read back as written"; exit 2; }
  echo "U3 REHEARSAL WINDOW OPEN $(utc) BACKUP $backup"
  echo "Nothing changed: the ruleset is R1' as before. Press Ctrl+C now to try the restore, or wait one minute."
  for i in 1 2 3 4; do
    sleep 15
    gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha' >/dev/null 2>&1 || true
  done
  exit 0
fi
if ! put_verify "$r1pp"; then why="R1'' did not read back as written; the window closed at once"; exit 2; fi
opened=$(utc)
deadline=$(( $(date +%s) + 1200 ))   # main-protect/u3-window-bound: 20 minutes, rule-suite reads included
export U3_OPENED=$opened
echo "U3 WINDOW OPEN $opened BACKUP $backup"
echo "If this window ever closes without a RESTORED line: gh api -X PUT repos/$repo/rulesets/$rid --input '$backup'"

# ---------------------------------------------------------------------------------------------- 3. merge
pr_state() {   # merged, merged_by, merge commit, head (each through tostring: never empty)
  gh api "repos/$repo/pulls/$pr" --jq '[(.merged|tostring), (.merged_by.login|tostring), (.merge_commit_sha|tostring), (.head.sha|tostring)] | @tsv'
}
refusal() {   # $1 text: FAIL-U3 only for HTTP 405 naming "approving review", P unmerged at the same head, main unmoved
  local st merged by msha h m
  # v1-probe/u3-405-wording: "Base branch was modified. Review and try the merge again." is a 405 too
  grep -q 'HTTP 405' <<< "$1" && grep -qi 'approving review' <<< "$1" \
    || { why="the merge failed without a ruleset refusal: $2"; return; }
  m=$(gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha') || m=""
  [ "$m" = "$main_before" ] || { why="the merge was refused but main is at ${m:-unread}, not $main_before"; return; }
  st=$(pr_state) || { why="the merge was refused but PR #$pr could not be read"; return; }
  IFS=$'\t' read -r merged by msha h <<< "$st" || true
  [ "$merged" = false ] || { why="the merge was refused but PR #$pr reads merged=$merged"; return; }
  [ "$h" = "$head" ] || { why="the merge was refused but PR #$pr's head is now $h, not $head"; return; }
  verdict=FAIL-U3; detail="the merge of PR #$pr at $head was refused: $2"
}
if [ "$merge" = 1 ]; then
  out=$(bash "$here/merge-reviewed.sh" "$pr" "$head" "$report" 2>&1); mrc=$?
  printf '%s\n' "$out"
  if [ "$mrc" != 0 ]; then
    st=$(pr_state) || { why="merge-reviewed failed and PR #$pr could not be read"; exit 2; }
    if [ "${st%%$'\t'*}" != true ]; then
      line=$(grep -m1 'HTTP 405' <<< "$out") || line=$(tail -n1 <<< "$out")
      refusal "$out" "$line"
      exit 2
    fi
  fi
else
  echo "Waiting for main to move (checked every 15 s, up to 20 minutes). Now type U3 go in the team thread."
  moved=0; fails=0; refused=""
  for i in $(seq 1 80); do
    [ "$(date +%s)" -lt "$deadline" ] || break
    sleep 15
    now=$(gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha' 2>/dev/null) || now=""
    if ! [[ "$now" =~ ^[0-9a-f]{40}$ ]]; then
      fails=$((fails + 1)); [ "$fails" -lt 4 ] || { why="main could not be read four times running"; exit 2; }
      continue
    fi
    fails=0
    if [ "$now" != "$main_before" ]; then moved=1; break; fi
    # a gn0sh comment made in this window whose body starts with "U3 merge refused", as one JSON-quoted line
    bodies=$(gh api --paginate "repos/$repo/issues/$pr/comments?per_page=100" \
             --jq '.[] | select(.user.login == $ENV.U3_OWNER and .created_at >= $ENV.U3_OPENED and (.body | startswith($ENV.U3_REFUSED))) | .body | @json' 2>/dev/null) || bodies=""
    refused=${bodies%%$'\n'*}
    [ -z "$refused" ] || break
  done
  if [ -n "$refused" ]; then refusal "$refused" "PR comment $refused"; exit 2; fi
  [ "$moved" = 1 ] || { why="no merge in the 20-minute window"; exit 2; }
fi

# ---------------------------------------------------------------------------------------------- 4. verdict
st=$(pr_state) || { why="PR #$pr could not be read after the merge"; exit 2; }
IFS=$'\t' read -r merged merged_by merge_sha _ <<< "$st" || true
now=$(gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha') || now=""
[ "$merged" = true ] || { why="main moved to ${now:-?} but PR #$pr is not merged (another actor)"; exit 2; }
[ "$merged_by" = "$owner" ] || { why="PR #$pr was merged by '$merged_by', not $owner"; exit 2; }
[[ "$merge_sha" =~ ^[0-9a-f]{40}$ ]] || { why="PR #$pr's merge commit could not be read"; exit 2; }
[ "$now" = "$merge_sha" ] || { why="main is at ${now:-?}, not PR #$pr's merge commit $merge_sha (another actor)"; exit 2; }
read_live "$work/window.json" || { why="ruleset $rid could not be read at the end of the window"; exit 2; }
same_as "$work/window.json" "$r1pp" || { why="ruleset $rid did not read R1'' at the end of the window"; exit 2; }
export U3_AFTER=$merge_sha
for i in 1 2 3 4 5 6 7 8; do
  ids=$(gh api "repos/$repo/rulesets/rule-suites?ref=main&time_period=hour&per_page=100" \
        --jq '.[] | select(.after_sha == $ENV.U3_AFTER) | .id' 2>/dev/null) || ids=""
  suite_id=${ids%%$'\n'*}
  [[ "$suite_id" =~ ^[0-9]+$ ]] && break
  suite_id=""
  [ "$(date +%s)" -lt "$deadline" ] || break
  [ "$i" = 8 ] || sleep 15
done
[ -n "$suite_id" ] || { why="PR #$pr merged by $owner as $merge_sha, but no rule suite listed it within the window"; exit 2; }
# line 1: the suite's result; then result and enforcement of each pull_request evaluation of ruleset 27502319
ev=$(gh api "repos/$repo/rulesets/rule-suites/$suite_id" \
     --jq '.result, (.rule_evaluations[]? | select(.rule_type == $ENV.U3_RULE and .rule_source.id == ($ENV.U3_RID | tonumber)) | .result, .enforcement)') \
  || { why="rule suite $suite_id could not be read"; exit 2; }
mapfile -t evl <<< "$ev"
suite_result=${evl[0]:-}; pr_eval=${evl[1]:-}; pr_enf=${evl[2]:-}
detail="PR #$pr merged by $owner as $merge_sha; rule suite $suite_id result=$suite_result pull_request=${pr_eval:-none} enforcement=${pr_enf:-none}"
if [ "${#evl[@]}" != 3 ]; then
  why="$detail (expected exactly one pull_request evaluation from ruleset $rid, got $(( (${#evl[@]} - 1) / 2 )))"
elif [ "$pr_enf" != active ]; then
  why="$detail (the pull_request rule was not enforced)"
elif [ "$suite_result" = bypass ] && [ "$pr_eval" = fail ]; then
  verdict=PASS
elif [ "$pr_eval" = pass ] && { [ "$suite_result" = bypass ] || [ "$suite_result" = pass ]; }; then
  verdict=FAIL-RULE
else
  why="$detail (not bypass+fail and not a pull_request pass)"
fi
exit 0
