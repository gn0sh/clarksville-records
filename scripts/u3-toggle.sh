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
#   bash scripts/u3-toggle.sh --restore [<backup json>]      PUTs scripts/main-ruleset.json (R1'), or that backup
#   bash scripts/u3-toggle.sh --noop                         U3-0: PUTs the live ruleset back unchanged, reads it back
#   bash scripts/u3-toggle.sh --show-body <json>             prints the PUT body built from a file; no GitHub call
#
# Steps (it stops at the first failure):
#   1. Preflight, read-only: refuses (nothing changed) at 08:00-10:30 UTC, while a daily-update run is not completed,
#      unless ruleset 27502319 equals R1' (scripts/main-ruleset.json) on every written field, unless PR P is open into
#      main, authored by gn0sh, from a branch of this repository, not a draft, mergeable and docs-only, and unless
#      current_user_can_bypass is pull_requests_only or always. Saves the live ruleset outside the repository.
#   2. PUTs R1'' (scripts/main-ruleset-r1pp.json) and reads it back; any difference closes the window at once.
#      Prints "U3 WINDOW OPEN <utc> backup <file>". From here on every exit (error, Ctrl+C) restores the backup.
#   3. Team path: runs merge-reviewed. Brian's path: checks main every 15 s for up to 20 minutes. If the team's merge
#      is refused, the manager comments "U3 merge refused: <gh's message>" on PR P; that ends the wait as FAIL-U3.
#   4. Reads PR P (merged, merged_by, merge_commit_sha), the ruleset again (still R1''?) and the rule suite whose
#      after_sha is the merge commit.
#   5. Restores the backup, reads it back, prints "RESTORED <utc>", then one line:
#      "U3 VERDICT <PASS|FAIL-U3|FAIL-RULE|INCONCLUSIVE> rule-suite <id|none>: <detail>".
# Every PUT body comes from one function (wl below): only name, target, enforcement, conditions, bypass_actors
# (actor_id, actor_type, bypass_mode) and rules (type, parameters); never id, _links, source or
# current_user_can_bypass. Exit: 0 PASS (or --restore / --noop verified), 1 refused before any write, 2 any other
# verdict (restored), 3 the restore (or --noop) did not read back as written.
# Needs: gh signed in as gn0sh (gh auth login) and jq.
set -uo pipefail
repo=gn0sh/clarksville-records
owner=gn0sh
rid=27502319
here=$(cd "$(dirname "$0")" && pwd)
r1p="$here/main-ruleset.json"
r1pp="$here/main-ruleset-r1pp.json"
export U3_OWNER=$owner U3_RULE=pull_request U3_RID=$rid
# The one whitelist: every PUT body and every comparison goes through it (order made canonical: rules by type).
wl='def wl: {name, target, enforcement, conditions,
  bypass_actors: ([.bypass_actors[]? | {actor_id, actor_type, bypass_mode}] | sort_by(.actor_type, .actor_id, .bypass_mode)),
  rules: ([.rules[]? | if .parameters == null then {type} else {type, parameters} end] | sort_by(.type))}; wl'
# read-only or unknown fields inside a rule or bypass actor (the whitelist would hide them in a comparison)
extras='[(.rules[]? | keys[] | select(. != "type" and . != "parameters") | "rules." + .),
  (.bypass_actors[]? | keys[] | select(. != "actor_id" and . != "actor_type" and . != "bypass_mode") | "bypass_actors." + .)] | join(",")'

usage="Usage: bash scripts/u3-toggle.sh --pr <P> [--merge --report <review report>] | --restore [<backup json>] | --noop | --show-body <json>"
mode=window; pr=""; merge=0; report=""; src=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --pr) pr="${2:-}"; shift 2 || { echo "$usage"; exit 1; } ;;
    --merge) merge=1; shift ;;
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
restore() {   # $1 source json, $2 its name; three tries
  local i
  for i in 1 2 3; do
    if put_verify "$1"; then echo "RESTORED $(utc) (ruleset $rid read back equal to $2)"; restored=1; return 0; fi
    [ "$i" = 3 ] || sleep 5
  done
  echo "RESTORE FAILED: ruleset $rid may still be R1''. Run: bash scripts/u3-toggle.sh --restore (or bash scripts/protect-main.sh). Send this output to the team."
  return 1
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
    *) echo "NOOP CHANGED $(utc): ruleset $rid did not read back as it was. Run: bash scripts/protect-main.sh. Send this output to the team."; exit 3 ;;
  esac
fi

# ---------------------------------------------------------------------------------------------- 1. preflight
refuse() { echo "REFUSED: $1. Nothing was changed."; exit 1; }
[[ "$pr" =~ ^[0-9]+$ ]] || { echo "$usage"; exit 1; }
if [ "$merge" = 1 ] && [ -z "$report" ]; then echo "--merge needs --report <review report of PR $pr>. $usage"; exit 1; fi
hm=$(date -u +%H%M)
[[ "$hm" =~ ^[0-9]{4}$ ]] || refuse "could not read the UTC time"
if [ $((10#$hm)) -ge 800 ] && [ $((10#$hm)) -le 1030 ]; then
  refuse "it is ${hm:0:2}:${hm:2:2} UTC, inside 08:00-10:30 (the daily run's window); run it later"
fi
runs=$(gh api "repos/$repo/actions/workflows/daily-update.yml/runs?per_page=30" --jq '.workflow_runs[].status') \
  || refuse "could not read the daily-update runs"
busy=$(printf '%s\n' "$runs" | grep -cv -e '^completed$' -e '^$')
[ "$busy" = 0 ] || refuse "a daily-update run is queued or in progress; run it after that run completes"
read_live "$work/live.json" || refuse "could not read ruleset $rid"
bypass=$(jq -r '.current_user_can_bypass // "missing"' "$work/live.json")
case "$bypass" in pull_requests_only|always) ;; *) refuse "current_user_can_bypass is '$bypass', not pull_requests_only or always" ;; esac
same_as "$work/live.json" "$r1p" || refuse "ruleset $rid is not R1' (scripts/main-ruleset.json)"
prline=""
for i in 1 2 3 4; do
  prline=$(gh api "repos/$repo/pulls/$pr" --jq '[.state, .base.ref, .user.login, .head.repo.full_name, .head.sha, (.draft|tostring), (.mergeable|tostring), (.changed_files|tostring), (.merged|tostring)] | @tsv') \
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
files=$(gh api --paginate "repos/$repo/pulls/$pr/files?per_page=100" --jq '.[] | [.filename, .previous_filename] | @tsv') \
  || refuse "could not read pull request #$pr's files"
n=0
while IFS=$'\t' read -r f prev; do
  [ -n "$f" ] || continue
  n=$((n + 1))
  for name in "$f" ${prev:+"$prev"}; do
    case "$name" in docs/*) ;; *) refuse "pull request #$pr changes $name, outside docs/ (P must be docs-only)" ;; esac
  done
done <<< "$files"
[ "$n" -ge 1 ] && [ "$n" = "${p_count:-}" ] || refuse "pull request #$pr lists $n file(s), GitHub counts '${p_count:-}'"
main_before=$(gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha') || main_before=""
[[ "$main_before" =~ ^[0-9a-f]{40}$ ]] || refuse "could not read main"
stamp=$(date -u +%Y%m%d-%H%M%S)
backup="$HOME/u3-ruleset-backup-$stamp.json"
cp "$work/live.json" "$HOME/u3-ruleset-live-$stamp.json" && body_of "$work/live.json" "$backup" \
  || refuse "could not save the ruleset backup in $HOME"
echo "Preflight passed. PR #$pr head $head, main $main_before. Live ruleset saved to $HOME/u3-ruleset-live-$stamp.json."

# ---------------------------------------------------------------------------------------------- 2. apply R1''
armed=0; verdict=""; detail=""; why=""; suite_id=""
finish() {
  local rc=$?
  trap '' INT TERM HUP   # a second Ctrl+C must not stop the restore (gh inherits the ignore)
  trap - EXIT
  if [ "$armed" != 1 ]; then rm -rf "$work"; exit "$rc"; fi
  echo "Closing the window: restoring R1' from $backup."
  restore "$backup" "the backup" || true
  if [ -z "$verdict" ]; then verdict=INCONCLUSIVE; detail="${why:-the run stopped before a verdict (exit $rc)}"; fi
  if [ "$verdict" = PASS ] && [ "$restored" != 1 ]; then verdict=INCONCLUSIVE; detail="the restore was not verified; $detail"; fi
  echo "U3 VERDICT $verdict rule-suite ${suite_id:-none}: $detail"
  rm -rf "$work"
  if [ "$restored" != 1 ]; then exit 3; fi
  if [ "$verdict" = PASS ]; then exit 0; fi
  exit 2
}
trap finish EXIT
trap 'why="interrupted (Ctrl+C or a stop signal)"; exit 130' INT TERM HUP
armed=1   # from here on, every exit restores (a PUT that failed half-way is restored too)
if ! put_verify "$r1pp"; then why="R1'' did not read back as written; the window closed at once"; exit 2; fi
opened=$(utc)
export U3_OPENED=$opened
echo "U3 WINDOW OPEN $opened backup $backup"
echo "If this window ever closes without a RESTORED line: gh api -X PUT repos/$repo/rulesets/$rid --input '$backup'"

# ---------------------------------------------------------------------------------------------- 3. merge
pr_state() {   # merged, merged_by, merge commit
  gh api "repos/$repo/pulls/$pr" --jq '[(.merged|tostring), .merged_by.login, .merge_commit_sha] | @tsv'
}
if [ "$merge" = 1 ]; then
  out=$(bash "$here/merge-reviewed.sh" "$pr" "$head" "$report" 2>&1); mrc=$?
  printf '%s\n' "$out"
  if [ "$mrc" != 0 ]; then
    st=$(pr_state) || { why="merge-reviewed failed and PR #$pr could not be read"; exit 2; }
    if [ "${st%%$'\t'*}" != true ]; then
      if printf '%s' "$out" | grep -q 'HTTP 405' && printf '%s' "$out" | grep -qiE 'review|approv'; then
        verdict=FAIL-U3; detail="merge-reviewed's merge of PR #$pr was refused: $(printf '%s\n' "$out" | grep -m1 'HTTP 405')"
      else
        why="merge-reviewed failed without a ruleset refusal: $(printf '%s\n' "$out" | tail -n1)"
      fi
      exit 2
    fi
  fi
else
  echo "Waiting for main to move (checked every 15 s, up to 20 minutes). Now type U3 go in the team thread."
  moved=0; fails=0; refused=""
  for i in $(seq 1 80); do
    sleep 15
    now=$(gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha' 2>/dev/null) || now=""
    if ! [[ "$now" =~ ^[0-9a-f]{40}$ ]]; then
      fails=$((fails + 1)); [ "$fails" -lt 4 ] || { why="main could not be read four times running"; exit 2; }
      continue
    fi
    fails=0
    if [ "$now" != "$main_before" ]; then moved=1; break; fi
    refused=$(gh api --paginate "repos/$repo/issues/$pr/comments?per_page=100" \
              --jq '.[] | select(.user.login == $ENV.U3_OWNER and .created_at >= $ENV.U3_OPENED) | .body' 2>/dev/null \
              | grep -m1 '^U3 merge refused') || refused=""
    [ -z "$refused" ] || break
  done
  if [ -n "$refused" ]; then
    st=$(pr_state) || { why="the team reported a refused merge but PR #$pr could not be read"; exit 2; }
    [ "${st%%$'\t'*}" = false ] || { why="the team reported a refused merge but PR #$pr reads merged=${st%%$'\t'*}"; exit 2; }
    verdict=FAIL-U3; detail="the team's merge of PR #$pr was refused (PR comment: $refused)"; exit 2
  fi
  [ "$moved" = 1 ] || { why="no merge in the 20-minute window"; exit 2; }
fi

# ---------------------------------------------------------------------------------------------- 4. verdict
st=$(pr_state) || { why="PR #$pr could not be read after the merge"; exit 2; }
IFS=$'\t' read -r merged merged_by merge_sha <<< "$st" || true
now=$(gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha') || now=""
[ "$merged" = true ] || { why="main moved to ${now:-?} but PR #$pr is not merged (another actor)"; exit 2; }
[ "$merged_by" = "$owner" ] || { why="PR #$pr was merged by '$merged_by', not $owner"; exit 2; }
[[ "$merge_sha" =~ ^[0-9a-f]{40}$ ]] || { why="PR #$pr's merge commit could not be read"; exit 2; }
[ "$now" = "$merge_sha" ] || { why="main is at ${now:-?}, not PR #$pr's merge commit $merge_sha (another actor)"; exit 2; }
read_live "$work/window.json" || { why="ruleset $rid could not be read at the end of the window"; exit 2; }
same_as "$work/window.json" "$r1pp" || { why="ruleset $rid did not read R1'' at the end of the window"; exit 2; }
export U3_AFTER=$merge_sha
for i in 1 2 3 4 5 6 7 8; do
  suite_id=$(gh api "repos/$repo/rulesets/rule-suites?ref=main&time_period=hour&per_page=100" \
             --jq '.[] | select(.after_sha == $ENV.U3_AFTER) | .id' 2>/dev/null | head -n1) || suite_id=""
  [[ "$suite_id" =~ ^[0-9]+$ ]] && break
  suite_id=""
  [ "$i" = 8 ] || sleep 15
done
[ -n "$suite_id" ] || { why="PR #$pr merged by $owner as $merge_sha, but no rule suite lists it"; exit 2; }
ev=$(gh api "repos/$repo/rulesets/rule-suites/$suite_id" \
     --jq '.result, (.rule_evaluations[]? | select(.rule_type == $ENV.U3_RULE and .rule_source.id == ($ENV.U3_RID | tonumber)) | .result)') \
  || { why="rule suite $suite_id could not be read"; exit 2; }
suite_result=$(printf '%s\n' "$ev" | head -n1)
pr_eval=$(printf '%s\n' "$ev" | tail -n +2 | paste -sd, -)
detail="PR #$pr merged by $owner as $merge_sha; rule suite $suite_id result=$suite_result pull_request=${pr_eval:-none}"
if [ -z "$pr_eval" ] || [[ "$pr_eval" == *,* ]]; then
  why="$detail (expected one pull_request evaluation from ruleset $rid)"
elif [ "$suite_result" = bypass ] || [ "$pr_eval" = bypass ]; then
  verdict=PASS
elif [ "$suite_result" = pass ] && [ "$pr_eval" = pass ]; then
  verdict=FAIL-RULE
else
  why="$detail (neither bypass nor pass)"
fi
exit 0
