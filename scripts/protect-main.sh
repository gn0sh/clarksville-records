#!/usr/bin/env bash
# Protect main (ADR 0011 decisions 5-6; docs/tasks/data-off-main.md D1; consumer rows R1, R-D, R2, S1): the bash twin
# of scripts/protect-main.ps1, which is the one Brian runs. Brian's PC only: every ruleset and settings write is his
# (U3-0 = no), and the team proxy refuses several of the reads below, so it refuses to run in a cloud session or CI.
#
# Writes (each ruleset is created, or updated if one of that name exists; never a second one):
#   R1''  scripts/main-ruleset.json         main: 10 approvals (API max), last-push approval, no code-owner review, squash only,
#                                           bypass = the admin role in pull_request mode
#   R-D   scripts/records-data-ruleset.json records-data: no deletion, no force push, no bypass
#   R-T   scripts/main-tag-ruleset.json     a tag named main: no creating, updating or deleting it (finding F2)
#   R2    "Allow GitHub Actions to create and approve pull requests" turned OFF (load-bearing for R1'')
# Then it reads everything back. OK only if: each ruleset reads back equal to its file, main's rules are deletion,
# non_fast_forward and one pull_request rule with 10 approvals and no code-owner review, R2 is off, auto-merge is off,
# gn0sh is the only writer (no other collaborator or pending invitation with write or more, no App installed on
# gn0sh's account with contents or administration write that reaches this repository, no deploy key with write:
# finding F1), and both environments (github-pages, morning-note) allow exactly one custom policy, main, of type
# branch (F2). Any refused or failed read is NOT OK, never skipped (the review's "settings drift").
# Run it after any settings change and right before MAIN_PR_BASELINE is set; it must print OK.
# Prints "Main before the rulesets: <sha>" first (main read before any write). Exit 0 OK, 1 refused or NOT OK.
# --check: no writes, only the checks (for a settings-drift re-check, or a dry look before the cutover).
# Main's .github/workflows/daily-update.yml is read too (ADR 0011 row J2, I-prov): after the cutover it must run the
#   gate step ("Check main's history and the records-data head") in job gate and only there, push must need gate,
#   push must be the only job with attestations: write (only J2 stores attestations) and with contents: write, no job
#   may hold pull-requests: write or set its permissions inline, and the workflow's own permissions are {}.
#   --pre-cutover: cutover step 4 only, before the cutover merge. Main must then still hold the old step
#   "Open and merge the data pull request", and the post-cutover checks wait for the next run without it.
# Main's .github/workflows/national-update.yml is read too (ADR 0013 decision 6; main-protect-invariant.md note
#   2026-11-20), in both modes: the gate step ("Check the national-data head") in job gate and only there, push must
#   need gate, push must be the only job with attestations: write, contents: write and id-token: write, the only other
#   write is issues: write in job report, no job may hold pull-requests: write, set its permissions inline, name an
#   environment or call a reusable workflow, no line may read a secret, and the workflow's own permissions are {}.
# --apps: no token Brian holds can list installed GitHub Apps (user/installations needs a GitHub App token: HTTP 403
#   for gh's OAuth token, 2026-11-18), so Brian reads https://github.com/settings/installations and passes the Apps
#   that can write this repository (or none). Without --apps that check is NOT OK, never a silent pass. Only the Claude
#   App ($allowed_app, through which the team pushes branches) may be listed. With R2 off it is then the only approver
#   besides gn0sh, so R1'''s required approvals (the ruleset maximum, 10, S1-1) can't be met without gn0sh
#   (invariant I-person, ADR 0011 Amendment 2026-11-18 (b): at most one non-gn0sh approver counts; two Apps, or R2 on
#   plus one, would make 2 without gn0sh). No App may hold Administration write (it could edit the rulesets) or bypass, and only J2 on main stores attestations. Nor may it
#   hold Variables, Secrets or Environments write (S1-2: it could set MORNING_NOTE_SEND or RECORDS_DEPLOY_ENABLED,
#   or change an environment's policy); --apps claude is Brian's answer that all four are not Read and write, and
#   any other answer is NOT OK. That no App can bypass R1'', R-D or R-T is read, not confirmed: the bypass lists must
#   equal the files. R1'' asks for 10 approvals, the ruleset API maximum (S1-1), so gn0sh plus one App can't reach it
#   either: every merge is a gn0sh bypass, and rule 1 no longer rests on the COMMENT-only rule.
# Also read (S1-6, S1-7): GitHub Pages must build from a workflow (build_type workflow, so nothing publishes outside
#   daily-update's gate), and .github/workflows/ on main must hold exactly daily-update.yml and national-update.yml.
# Needs: gh signed in as gn0sh (gh auth login) and jq.
# --main <sha>: main's commit as the caller just merged it (cutover step 5): main's ref is read until it is <sha>
#   (read-after-write row 10), and main's .github/workflows/ files are read at <sha>, never at a lagging ?ref=main (a
#   failed read there is "not yet": up to 10 reads, 3 s apart; a sha never changes, so the first read that works holds).
# After this run's own writes, each read that confirms one (the rulesets, main's rules, R2 if this run turned it off)
#   is read until it shows what was written (up to 10 reads, 3 s apart: docs/architecture/read-after-write-invariant.md);
#   with --check every read is read once.
# Run: bash scripts/protect-main.sh [--check] [--pre-cutover] [--apps <names>|none] [--main <sha>]
set -uo pipefail
check=0; pre=0; r2_put=0
apps=""; apps_given=0; main_pin=""
usage="Usage: bash scripts/protect-main.sh [--check] [--pre-cutover] [--apps <App names>|none] [--main <sha>]"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --check) check=1; shift ;;
    --pre-cutover) pre=1; shift ;;
    --apps) [ "$#" -ge 2 ] || { echo "$usage"; exit 1; }; apps=$2; apps_given=1; shift 2 ;;
    --main) [ "$#" -ge 2 ] || { echo "$usage"; exit 1; }; main_pin=$2; shift 2
      [[ "$main_pin" =~ ^[0-9a-f]{40}$ ]] || { echo "--main takes main's full 40-hex commit sha ('$main_pin' is not one). Nothing was changed."; exit 1; } ;;
    *) echo "$usage"; exit 1 ;;
  esac
done
repo=gn0sh/clarksville-records
owner=gn0sh
allowed_app=claude
here=$(cd "$(dirname "$0")" && pwd)
export PM_OWNER=$owner PM_REPO=$repo PM_PR=pull_request PM_WRITE=write PM_READ=read PM_TRIAGE=triage
for v in CLAUDE_CODE_REMOTE GITHUB_ACTIONS CI; do
  if [ -n "${!v:-}" ]; then
    echo "REFUSED: $v is set. protect-main runs only from Brian's PC (ruleset and settings writes are his). Nothing was changed."
    exit 1
  fi
done
command -v jq >/dev/null 2>&1 || { echo "jq not found: install it, then run this again. Nothing was changed."; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Not signed in: run gh auth login (as $owner). Nothing was changed."; exit 1; }

# The one whitelist (the same text as scripts/u3-toggle.sh): every comparison goes through it.
wl='def wl: {name, target, enforcement, conditions,
  bypass_actors: ([.bypass_actors[]? | {actor_id, actor_type, bypass_mode}] | sort_by(.actor_type, .actor_id, .bypass_mode)),
  rules: ([.rules[]? | if .parameters == null then {type} else {type, parameters} end] | sort_by(.type))}; wl'
# read-only or unknown fields inside a rule or bypass actor (the whitelist would hide them in a comparison)
extras='[(.rules[]? | keys[] | select(. != "type" and . != "parameters") | "rules." + .),
  (.bypass_actors[]? | keys[] | select(. != "actor_id" and . != "actor_type" and . != "bypass_mode") | "bypass_actors." + .)] | join(",")'
sets="R1''|main-ruleset.json R-D|records-data-ruleset.json R-T|main-tag-ruleset.json"
for s in $sets; do
  f="$here/${s#*|}"
  [ -n "$(jq -r '.name // empty' "$f" 2>/dev/null)" ] || { echo "Could not read scripts/${s#*|}. Nothing was changed."; exit 1; }
done
work=$(mktemp -d) || { echo "Could not make a temporary folder. Nothing was changed."; exit 1; }
trap 'rm -rf "$work"' EXIT
stop() { echo "$1"; echo "NOT OK: stopped before the checks. Run this again; send this output to the team if it repeats."; exit 1; }
ids_of() {   # $1 ruleset file: the ids of the rulesets with its name (any target)
  PM_NAME=$(jq -r '.name' "$1") gh api --paginate "repos/$repo/rulesets?per_page=100" \
    --jq '.[] | select(.name == $ENV.PM_NAME) | .id'
}
ids_line() { local x; x=$(ids_of "$1") || return 1; printf '%s\n' "$x" | { grep . || true; } | sort | paste -sd, -; }   # one string (rule 5)
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

# ---------------------------------------------------------------------------------------------- writes
if [ "$check" = 1 ]; then
  echo "CHECK ONLY: nothing is written; the checks below read the live settings."
else
  # main is read before anything is written, so the printed sha is where main stood when protection began.
  main_sha=$(gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha') || main_sha=""
  [[ "$main_sha" =~ ^[0-9a-f]{40}$ ]] || { echo "Could not read main's commit. Nothing was changed. Run this again; send this output to the team if it repeats."; exit 1; }
  echo "Main before the rulesets: $main_sha"
  wrote=()   # per ruleset, in the order of $sets: the ids this run wrote, as ids_line prints them
  for s in $sets; do
    label=${s%%|*}; file=${s#*|}
    ids=$(ids_of "$here/$file") || stop "Could not list the rulesets (signed in as $owner?). $label was not written."
    if [ -z "$ids" ]; then
      echo "$label: no ruleset yet, creating it from scripts/$file."
      # a 2xx write is its own read (read-after-write rule 6): the new id comes from the answer, not from a list
      id=$(gh api -X POST "repos/$repo/rulesets" --input "$here/$file" --jq '.id') \
        || stop "Creating $label failed (see the message above)."
      [[ "$id" =~ ^[0-9]+$ ]] || stop "Creating $label: GitHub's answer names no ruleset id ('$id'); check Settings > Rules > Rulesets."
      wrote+=("$id")
    else
      for id in $ids; do
        echo "$label: ruleset $id exists, updating it from scripts/$file."
        gh api -X PUT "repos/$repo/rulesets/$id" --input "$here/$file" --silent \
          || stop "Updating $label (ruleset $id) failed (see the message above); it may be unchanged."
      done
      wrote+=("$(printf '%s\n' "$ids" | grep . | sort | paste -sd, -)")
    fi
  done
  r2=$(gh api "repos/$repo/actions/permissions/workflow" --jq '.can_approve_pull_request_reviews') || r2=""
  if [ "$r2" = false ]; then
    echo "R2 already off"
  elif [ "$r2" = true ]; then
    gh api -X PUT "repos/$repo/actions/permissions/workflow" -F can_approve_pull_request_reviews=false --silent \
      || stop "Turning off 'Allow GitHub Actions to create and approve pull requests' (R2) failed (see above); the rulesets are written."
    r2_put=1
    echo "R2 was on: turned off"
  else
    stop "Could not read 'Allow GitHub Actions to create and approve pull requests' (R2) ('$r2'); it was not changed (the rulesets are written)."
  fi
fi

# ---------------------------------------------------------------------------------------------- checks
problems=0
problem() { echo "  NOT OK: $1"; problems=$((problems + 1)); }
unread() { problem "could not read $1 (a refused or failed read counts as NOT OK)"; }
once() { if rlast=$("$@"); then rrc=0; else rrc=$?; fi; }   # one read; sets rlast and rrc as read_until does
settled() {   # <what> <expected> <cmd...>: a read that confirms this run's writes waits for them; --check reads once
  if [ "$check" = 1 ]; then once "${@:3}"; else read_until "$@" || true; fi
}

same_as() {   # $1 live json, $2 expected json: exact equality on every whitelisted field, no unknown nested fields
  local x
  x=$(jq -r "$extras" "$1" 2>/dev/null) || return 1
  if [ -n "$x" ]; then echo "  The ruleset has fields this script does not write: $x"; return 1; fi
  [ "$(jq -S -c "$wl" "$1")" = "$(jq -S -c "$wl" "$2")" ] && return 0
  echo "  It differs from $(basename "$2") (- expected, + live):"
  diff <(jq -S "$wl" "$2") <(jq -S "$wl" "$1") | grep '^[<>]' | sed 's/^</    -/; s/^>/    +/'
  return 1
}
live_wl() {   # $1 id: the live ruleset into $work/live.json, printed whitelisted
  gh api "repos/$repo/rulesets/$1" > "$work/live.json" 2>/dev/null && jq -e '.id' "$work/live.json" >/dev/null 2>&1 \
    && jq -S -c "$wl" "$work/live.json"
}
k=0
for s in $sets; do
  label=${s%%|*}; file=${s#*|}
  want=${wrote[$k]:-}; k=$((k + 1))
  name=$(jq -r .name "$here/$file")
  # read-after-write row 4: after a POST a lagging list shows no id, after a PUT a lagging GET the old body
  settled "$label: the rulesets named '$name'" "$want" ids_line "$here/$file"
  if [ "$rrc" != 0 ]; then unread "the rulesets"; continue; fi
  ids=$rlast
  if [ "$check" = 0 ] && [ "$ids" != "$want" ]; then
    problem "$label: the rulesets named '$name' read '$ids', not the ruleset this run wrote ($want)"; continue
  fi
  n=$(printf '%s' "$ids" | tr , '\n' | grep -c . || true)
  if [ "$n" != 1 ]; then problem "$label: $n rulesets named '$name', expected exactly 1"; continue; fi
  settled "$label: ruleset $ids" "$(jq -S -c "$wl" "$here/$file")" live_wl "$ids"
  if [ "$rrc" != 0 ]; then unread "ruleset $ids ($label)"; continue; fi
  if same_as "$work/live.json" "$here/$file"; then echo "$label: ruleset $ids matches scripts/$file"
  else problem "$label: ruleset $ids does not match scripts/$file"; fi
done

main_types() { local t; t=$(gh api "repos/$repo/rules/branches/main" --jq '.[].type') || return 1; printf '%s\n' "$t" | sort -u | paste -sd, -; }
main_prr() {
  gh api "repos/$repo/rules/branches/main" \
    --jq '.[] | select(.type == $ENV.PM_PR) | [(.parameters.required_approving_review_count|tostring), (.parameters.require_code_owner_review|tostring)] | @tsv'
}
# read-after-write row 5: main's rules come from every active ruleset, so each listing must equal the whole expected
# string (a view while the rulesets propagate never matches)
settled "Rules on main" "deletion,non_fast_forward,pull_request" main_types
if [ "$rrc" = 0 ]; then
  rules=$rlast
  echo "Rules on main: $rules"
  [ "$rules" = "deletion,non_fast_forward,pull_request" ] || problem "main's rules must be deletion,non_fast_forward,pull_request"
else unread "the rules on main"; fi
# every pull_request rule on main, from any ruleset: exactly one, 10 approvals (the ruleset API maximum,
# S1-1 main-protect/approval-margin: GitHub's schema repository-rule-pull-request caps it at 10), no code-owner review
# (CODEOWNERS is gone)
settled "Pull request rules on main" $'10\tfalse' main_prr
if [ "$rrc" = 0 ]; then
  prr=$rlast
  echo "Pull request rules on main (approvals, code-owner review): $(printf '%s' "$prr" | tr '\t\n' ' ;')"
  [ "$prr" = $'10\tfalse' ] || problem "main needs exactly one pull_request rule, with 10 approvals (the ruleset API maximum) and no code-owner review"
else unread "main's pull_request rules"; fi

r2_read() { gh api "repos/$repo/actions/permissions/workflow" --jq '.can_approve_pull_request_reviews'; }
# read-after-write row 2: the PUT ran only after a read of true, so a lagging read says true and is never accepted
if [ "${r2_put:-0}" = 1 ]; then read_until R2 false r2_read || true; else once r2_read; fi
r2=$rlast; [ "$rrc" = 0 ] || r2="unread"
echo "GitHub Actions may create and approve pull requests (R2): $r2"
case "$r2" in
  false) ;;
  true) problem "R2 is on: with R2 on, gn0sh plus the bot can approve a pull request (ADR 0011 decision 6)" ;;
  *) unread "R2 (actions/permissions/workflow)" ;;
esac
auto=$(gh api "repos/$repo" --jq '.allow_auto_merge') || auto="unread"
echo "Auto-merge allowed: $auto"
case "$auto" in
  false) ;;
  true) problem "auto-merge must be off: Settings > General > Pull Requests > untick Allow auto-merge" ;;
  *) unread "the repository settings (allow_auto_merge)" ;;
esac

# finding F1: gn0sh the only writer
if w=$(gh api --paginate "repos/$repo/collaborators?affiliation=all&per_page=100" \
       --jq '.[] | select(.permissions.admin or .permissions.maintain or .permissions.push) | .login'); then
  w=$(printf '%s\n' "$w" | grep . | sort -u | paste -sd, -)
  echo "Collaborators with write or more: ${w:-none}"
  [ "$w" = "$owner" ] || problem "the collaborators with write or more must be exactly $owner"
else unread "the collaborators"; fi
if inv=$(gh api --paginate "repos/$repo/invitations?per_page=100" \
         --jq '.[] | select(.permissions != $ENV.PM_READ and .permissions != $ENV.PM_TRIAGE) | [(.invitee.login // (.id|tostring)), .permissions] | @tsv'); then
  inv=$(printf '%s\n' "$inv" | grep . | tr '\t' ':' | paste -sd, -)
  echo "Pending invitations with write or more: ${inv:-none}"
  [ -z "$inv" ] || problem "a pending invitation with write or more: $inv"
else unread "the pending invitations"; fi
# installed Apps: confirmed by hand (--apps), never read (no read an OAuth token can make lists them)
if [ "$apps_given" = 0 ]; then
  echo "Installed Apps with write on this repository: not confirmed"
  problem "installed Apps can't be read with this token (GitHub's user/installations needs a GitHub App token), so confirm them by hand: open https://github.com/settings/installations, click Configure on each App, and note each one that reaches clarksville-records (All repositories, or listed) with any Read and write permission. Then run this again with --apps claude or --apps none (one value; any other App must first lose its access to clarksville-records, or the team amends ADR 0011). Only $allowed_app may be listed, and only if none of its Administration, Variables, Secrets and Environments permissions is Read and write (any other answer is NOT OK)"
elif ! [[ "$apps" =~ ^(none|[a-z0-9][a-z0-9-]*(,[a-z0-9][a-z0-9-]*)*)$ ]]; then
  echo "Installed Apps with write on this repository: '$apps' (not claude or none)"
  problem "--apps takes one value, claude or none ('$apps' is not one)"
else
  echo "Installed Apps with write on this repository: $apps (confirmed by hand by $owner on $(date -u +%Y-%m-%d), not read by this script; none with Administration, Variables, Secrets or Environments write)"
  if [ "$apps" != none ] && [ "$apps" != "$allowed_app" ]; then
    problem "an installed App other than $allowed_app alone can write this repository ($apps): remove its access to clarksville-records, or the team amends ADR 0011 first"
  fi
fi
if keys=$(gh api --paginate "repos/$repo/keys?per_page=100" --jq '.[] | select(.read_only != true) | [(.id|tostring), .title] | @tsv'); then
  keys=$(printf '%s\n' "$keys" | grep . | tr '\t' ':' | paste -sd, -)
  echo "Deploy keys with write: ${keys:-none}"
  [ -z "$keys" ] || problem "a deploy key with write: $keys"
else unread "the deploy keys"; fi

# finding F2: each environment deploys from main only, by a branch-type policy (a tag named main is not main)
for env in github-pages morning-note; do
  if pol=$(gh api "repos/$repo/environments/$env" \
           --jq '.deployment_branch_policy | [(.protected_branches|tostring), (.custom_branch_policies|tostring)] | @tsv'); then
    echo "Environment $env (protected branches, custom policies): $(tr '\t' ' ' <<< "$pol")"
    [ "$pol" = $'false\ttrue' ] || problem "environment $env must use custom deployment policies only (not protected branches, not all)"
  else unread "environment $env"; fi
  if bp=$(gh api --paginate "repos/$repo/environments/$env/deployment-branch-policies?per_page=100" \
          --jq '.branch_policies[] | [.name, (.type|tostring)] | @tsv'); then
    shown=$(printf '%s\n' "$bp" | grep . | tr '\t' ':' | paste -sd, -)
    echo "Environment $env policies: ${shown:-none}"
    [ "$bp" = $'main\tbranch' ] || problem "environment $env must allow exactly main, of type branch"
  else unread "environment $env's deployment policies"; fi
done

# S1-6 main-protect/pages-source-unchecked: Pages builds only from a workflow (a branch source would publish outside
# every gate); a refused read, or Pages off, is NOT OK
if pages=$(gh api "repos/$repo/pages" --jq '.build_type // empty'); then
  echo "GitHub Pages build type: ${pages:-none}"
  [ "$pages" = workflow ] || problem "GitHub Pages must build from a workflow (build_type workflow, Settings > Pages > Source: GitHub Actions), not '${pages:-none}'"
else unread "the GitHub Pages settings (repos/$repo/pages)"; fi
# read-after-write row 10 (--main <sha>, cutover step 5): main's ref read until it is <sha>, and main's workflow files
# read at <sha>, never at a lagging ?ref=main
wref=main; tries=1
if [ -n "$main_pin" ]; then
  main_ref() { gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha'; }
  if read_until main "$main_pin" main_ref; then echo "Main: $main_pin (--main); its workflow files are read at that commit."
  elif [ "$rrc" = 0 ]; then problem "main is at '$rlast', not $main_pin (--main)"
  else unread "main's commit (git/ref/heads/main)"; fi
  wref=$main_pin; tries=10
fi
read_at() {   # <cmd...>: one read, or with --main up to 10, 3 s apart, until one works (a sha never changes)
  local i o
  for i in $(seq 1 "$tries"); do
    if o=$("$@"); then printf '%s' "$o"; return 0; fi
    [ "$i" = "$tries" ] || sleep 3
  done
  return 1
}
# S1-7 main-protect/wf-shape-heuristic: daily-update.yml and national-update.yml are the only workflows on main (any
# other file there could run with the environments and never meets daily-update's gate). national-update.yml is
# allowed since 2026-11-20 (main-protect-invariant.md note): it names no environment and reads no secret, and its
# push job writes national-data only, attested as national-update.yml, which daily-update's gate never accepts for
# records-data (checked below). The contents API lists a folder in name order; any other order is NOT OK.
if wfs=$(read_at gh api "repos/$repo/contents/.github/workflows?ref=$wref" --jq '.[] | [.name, .type] | @tsv'); then
  echo "Main's .github/workflows/: $(printf '%s\n' "$wfs" | grep . | tr '\t' ':' | paste -sd, -)"
  [ "$wfs" = $'daily-update.yml\tfile\nnational-update.yml\tfile' ] \
    || problem "main's .github/workflows/ must hold exactly daily-update.yml and national-update.yml"
else unread "main's .github/workflows/ folder"; fi

# main's daily-update.yml (ADR 0011 row J2, I-prov): the post-cutover shape, or with --pre-cutover the old one
gate_step="Check main's history and the records-data head"
old_step="Open and merge the data pull request"
# one line per key; lists are job names joined by commas. Comment lines and trailing comments are dropped.
wf_awk='{ sub(/\r$/, "") }
/^[ \t]*#/ { next }
{ sub(/[ \t]+#.*$/, ""); sub(/[ \t]+$/, "") }
/^[^ \t]/ { injobs = ($0 ~ /^jobs:$/) }
/^permissions:/ { top = $0 }
/secrets([.]|\[)/ { sec = sec "," ((injobs && job != "") ? job : "top") }
!injobs { next }
/^  [A-Za-z0-9_-]+:$/ { job = $0; sub(/^  /, "", job); sub(/:$/, "", job); next }
/^[ \t]+attestations:[ \t]*write$/ { attw = attw "," job }
/^[ \t]+contents:[ \t]*write$/ { contw = contw "," job }
/^[ \t]+pull-requests:[ \t]*write$/ { prw = prw "," job }
/^[ \t]+id-token:[ \t]*write$/ { idw = idw "," job }
/^[ \t]+[A-Za-z0-9_-]+:[ \t]*.?write.?$/ { k = $0; sub(/^[ \t]+/, "", k); sub(/:.*$/, "", k); wr = wr "," job ":" k }
/^    environment:/ { envs = envs "," job }
/^    uses:/ { juses = juses "," job }
/^    permissions:[ \t]*[^ \t]/ && !/^    permissions:[ \t]*[{][}]$/ { inl = inl "," job }
/^[ \t]+(- )?name:/ { n = $0; sub(/^[ \t]+(- )?name:[ \t]*/, "", n)
  if (n == gs) gate = gate "," job; if (n == os) oldpr = oldpr "," job }
job == "push" && /^    needs:/ { pn = $0; sub(/^    needs:[ \t]*/, "", pn) }
END { printf "top=%s\ngate=%s\nattw=%s\ncontw=%s\nprw=%s\ninl=%s\noldpr=%s\npn=%s\n", top, substr(gate, 2),
  substr(attw, 2), substr(contw, 2), substr(prw, 2), substr(inl, 2), substr(oldpr, 2), pn
  printf "idw=%s\nwr=%s\nenvs=%s\njuses=%s\nsec=%s\n", substr(idw, 2), substr(wr, 2), substr(envs, 2),
  substr(juses, 2), substr(sec, 2) }'
if wf=$(read_at gh api "repos/$repo/contents/.github/workflows/daily-update.yml?ref=$wref" -H 'Accept: application/vnd.github.raw') \
   && [ -n "$wf" ] && shape=$(awk -v gs="$gate_step" -v os="$old_step" "$wf_awk" <<< "$wf"); then
  wfget() { sed -n "s/^$1=//p" <<< "$shape"; }
  top=$(wfget top); g=$(wfget gate); aw=$(wfget attw); cw=$(wfget contw); pw=$(wfget prw); ip=$(wfget inl)
  op=$(wfget oldpr); pn=$(wfget pn)
  echo "Main's daily-update.yml: workflow '$top'; gate step in '$g'; attestations: write in '$aw'; contents: write in '$cw'; pull-requests: write in '$pw'; inline job permissions in '$ip'; data pull request step in '$op'; push needs '$pn'"
  if [ "$pre" = 1 ]; then
    echo "--pre-cutover: main's daily-update.yml is checked as before the cutover (it still opens data pull requests); after the cutover merge, run this again without --pre-cutover"
    [ -n "$op" ] || problem "--pre-cutover, but main's daily-update.yml no longer has the data pull request step (the cutover is merged): run this again without --pre-cutover"
  else
    [ "$top" = "permissions: {}" ] || problem "main's daily-update.yml must set permissions: {} at the top (each job then names its own)"
    [ "$g" = gate ] || problem "main's daily-update.yml must run the step '$gate_step' in job gate, and only there (the post-cutover gate, ADR 0011)"
    [ "$aw" = push ] || problem "in main's daily-update.yml only job push may hold attestations: write (only J2 stores attestations, I-prov)"
    [ "$cw" = push ] || problem "in main's daily-update.yml only job push may hold contents: write"
    [ -z "$pw" ] || problem "no job in main's daily-update.yml may hold pull-requests: write"
    [ -z "$ip" ] || problem "no job in main's daily-update.yml may set its permissions inline (write-all, read-all or a { } map)"
    pnl=",$(tr -d '[] ' <<< "$pn"),"
    [[ "$pnl" == *,gate,* ]] || problem "job push in main's daily-update.yml must need gate"
    [ -z "$op" ] || problem "main's daily-update.yml still opens data pull requests (before the cutover): use --pre-cutover only at cutover step 4, before the cutover merge"
  fi
else unread "main's .github/workflows/daily-update.yml"; fi

# main's national-update.yml (ADR 0013 decision 6; main-protect-invariant.md note 2026-11-20), in both modes: the
# properties that let it sit on main beside daily-update.yml. Same reader (wf_awk) and strictness as daily-update.yml.
nat_step="Check the national-data head"
if wfn=$(read_at gh api "repos/$repo/contents/.github/workflows/national-update.yml?ref=$wref" -H 'Accept: application/vnd.github.raw') \
   && [ -n "$wfn" ] && nshape=$(awk -v gs="$nat_step" -v os="$old_step" "$wf_awk" <<< "$wfn"); then
  nget() { sed -n "s/^$1=//p" <<< "$nshape"; }
  ntop=$(nget top); ng=$(nget gate); naw=$(nget attw); ncw=$(nget contw); nidw=$(nget idw); npw=$(nget prw)
  nip=$(nget inl); nwr=$(nget wr); nenv=$(nget envs); nju=$(nget juses); nsec=$(nget sec); npn=$(nget pn)
  echo "Main's national-update.yml: workflow '$ntop'; gate step in '$ng'; attestations: write in '$naw'; contents: write in '$ncw'; id-token: write in '$nidw'; pull-requests: write in '$npw'; inline job permissions in '$nip'; writes '$nwr'; environments in '$nenv'; reusable workflows in '$nju'; secrets in '$nsec'; push needs '$npn'"
  [ "$ntop" = "permissions: {}" ] || problem "main's national-update.yml must set permissions: {} at the top (each job then names its own)"
  [ "$ng" = gate ] || problem "main's national-update.yml must run the step '$nat_step' in job gate, and only there (ADR 0013 decision 6)"
  [ "$naw" = push ] || problem "in main's national-update.yml only job push may hold attestations: write (its attestations name national-update.yml, never accepted for records-data)"
  [ "$ncw" = push ] || problem "in main's national-update.yml only job push may hold contents: write"
  [ "$nidw" = push ] || problem "in main's national-update.yml only job push may hold id-token: write"
  [ -z "$npw" ] || problem "no job in main's national-update.yml may hold pull-requests: write"
  [ -z "$nip" ] || problem "no job in main's national-update.yml may set its permissions inline (write-all, read-all or a { } map)"
  nbad=""
  for x in ${nwr//,/ }; do
    case "$x" in push:contents|push:id-token|push:attestations|report:issues) ;; *) nbad="$nbad,$x" ;; esac
  done
  [ -z "$nbad" ] || problem "in main's national-update.yml the only writes may be contents, id-token and attestations in job push and issues in job report, not '${nbad#,}'"
  [ -z "$nenv" ] || problem "no job in main's national-update.yml may name an environment (only daily-update's gated jobs deploy or send)"
  [ -z "$nju" ] || problem "no job in main's national-update.yml may call a reusable workflow (a job-level uses:)"
  [ -z "$nsec" ] || problem "main's national-update.yml may read no secret"
  npnl=",$(tr -d '[] ' <<< "$npn"),"
  [[ "$npnl" == *,gate,* ]] || problem "job push in main's national-update.yml must need gate"
else unread "main's .github/workflows/national-update.yml"; fi

if [ "$problems" = 0 ]; then
  echo "OK: main is protected (R1'', R-D, R-T as written, R2 off, auto-merge off, $owner the only writer, both environments main only)."
  exit 0
fi
echo "NOT OK: $problems problem(s) above. Run this from Brian's PC, signed in as $owner. Send this output to the team."
exit 1
