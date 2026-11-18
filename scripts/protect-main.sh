#!/usr/bin/env bash
# Protect main (ADR 0011 decisions 5-6; docs/tasks/data-off-main.md D1; consumer rows R1, R-D, R2, S1): the bash twin
# of scripts/protect-main.ps1, which is the one Brian runs. Brian's PC only: every ruleset and settings write is his
# (U3-0 = no), and the team proxy refuses several of the reads below, so it refuses to run in a cloud session or CI.
#
# Writes (each ruleset is created, or updated if one of that name exists; never a second one):
#   R1''  scripts/main-ruleset.json         main: 2 approvals, last-push approval, no code-owner review, squash only,
#                                           bypass = the admin role in pull_request mode
#   R-D   scripts/records-data-ruleset.json records-data: no deletion, no force push, no bypass
#   R-T   scripts/main-tag-ruleset.json     a tag named main: no creating, updating or deleting it (finding F2)
#   R2    "Allow GitHub Actions to create and approve pull requests" turned OFF (load-bearing for R1'')
# Then it reads everything back. OK only if: each ruleset reads back equal to its file, main's rules are deletion,
# non_fast_forward and one pull_request rule with 2 approvals and no code-owner review, R2 is off, auto-merge is off,
# gn0sh is the only writer (no other collaborator or pending invitation with write or more, no App installed on
# gn0sh's account with contents or administration write that reaches this repository, no deploy key with write:
# finding F1), and both environments (github-pages, morning-note) allow exactly one custom policy, main, of type
# branch (F2). Any refused or failed read is NOT OK, never skipped (the review's "settings drift").
# Run it after any settings change and right before MAIN_PR_BASELINE is set; it must print OK.
# Prints "Main before the rulesets: <sha>" first (main read before any write). Exit 0 OK, 1 refused or NOT OK.
# --check: no writes, only the checks (for a settings-drift re-check, or a dry look before the cutover).
# --apps: no token Brian holds can list installed GitHub Apps (user/installations needs a GitHub App token: HTTP 403
#   for gh's OAuth token, 2026-11-18), so Brian reads https://github.com/settings/installations and passes the Apps
#   that can write this repository (or none). Without --apps that check is NOT OK, never a silent pass. Only the Claude
#   App ($allowed_app, through which the team pushes branches) may be listed. With R2 off it is then the only approver
#   besides gn0sh, so any 2 approvals include gn0sh's (invariant I-person, ADR 0011 Amendment 2026-11-18 (b): at most
#   one non-gn0sh approver counts; two Apps, or R2 on plus one, would make 2 without gn0sh). No App may hold
#   Administration write (it could edit the rulesets) or bypass, and only J2 on main stores attestations. That no App
#   can bypass R1'', R-D or R-T is read, not confirmed: the bypass lists must equal the files.
# Needs: gh signed in as gn0sh (gh auth login) and jq. Run: bash scripts/protect-main.sh [--check] [--apps <names>|none]
set -uo pipefail
check=0
apps=""; apps_given=0
usage="Usage: bash scripts/protect-main.sh [--check] [--apps <App names>|none]"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --check) check=1; shift ;;
    --apps) [ "$#" -ge 2 ] || { echo "$usage"; exit 1; }; apps=$2; apps_given=1; shift 2 ;;
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

# ---------------------------------------------------------------------------------------------- writes
if [ "$check" = 1 ]; then
  echo "CHECK ONLY: nothing is written; the checks below read the live settings."
else
  # main is read before anything is written, so the printed sha is where main stood when protection began.
  main_sha=$(gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha') || main_sha=""
  [[ "$main_sha" =~ ^[0-9a-f]{40}$ ]] || { echo "Could not read main's commit. Nothing was changed. Run this again; send this output to the team if it repeats."; exit 1; }
  echo "Main before the rulesets: $main_sha"
  for s in $sets; do
    label=${s%%|*}; file=${s#*|}
    ids=$(ids_of "$here/$file") || stop "Could not list the rulesets (signed in as $owner?). $label was not written."
    if [ -z "$ids" ]; then
      echo "$label: no ruleset yet, creating it from scripts/$file."
      gh api -X POST "repos/$repo/rulesets" --input "$here/$file" --silent \
        || stop "Creating $label failed (see the message above)."
    else
      for id in $ids; do
        echo "$label: ruleset $id exists, updating it from scripts/$file."
        gh api -X PUT "repos/$repo/rulesets/$id" --input "$here/$file" --silent \
          || stop "Updating $label (ruleset $id) failed (see the message above); it may be unchanged."
      done
    fi
  done
  r2=$(gh api "repos/$repo/actions/permissions/workflow" --jq '.can_approve_pull_request_reviews') || r2=""
  if [ "$r2" = false ]; then
    echo "R2 already off"
  elif [ "$r2" = true ]; then
    gh api -X PUT "repos/$repo/actions/permissions/workflow" -F can_approve_pull_request_reviews=false --silent \
      || stop "Turning off 'Allow GitHub Actions to create and approve pull requests' (R2) failed (see above); the rulesets are written."
    echo "R2 was on: turned off"
  else
    stop "Could not read 'Allow GitHub Actions to create and approve pull requests' (R2) ('$r2'); it was not changed (the rulesets are written)."
  fi
fi

# ---------------------------------------------------------------------------------------------- checks
problems=0
problem() { echo "  NOT OK: $1"; problems=$((problems + 1)); }
unread() { problem "could not read $1 (a refused or failed read counts as NOT OK)"; }

same_as() {   # $1 live json, $2 expected json: exact equality on every whitelisted field, no unknown nested fields
  local x
  x=$(jq -r "$extras" "$1" 2>/dev/null) || return 1
  if [ -n "$x" ]; then echo "  The ruleset has fields this script does not write: $x"; return 1; fi
  [ "$(jq -S -c "$wl" "$1")" = "$(jq -S -c "$wl" "$2")" ] && return 0
  echo "  It differs from $(basename "$2") (- expected, + live):"
  diff <(jq -S "$wl" "$2") <(jq -S "$wl" "$1") | grep '^[<>]' | sed 's/^</    -/; s/^>/    +/'
  return 1
}
for s in $sets; do
  label=${s%%|*}; file=${s#*|}
  if ! ids=$(ids_of "$here/$file"); then unread "the rulesets"; continue; fi
  n=$(printf '%s' "$ids" | grep -c . || true)
  if [ "$n" != 1 ]; then problem "$label: $n rulesets named '$(jq -r .name "$here/$file")', expected exactly 1"; continue; fi
  if ! gh api "repos/$repo/rulesets/$ids" > "$work/live.json" 2>/dev/null || ! jq -e '.id' "$work/live.json" >/dev/null 2>&1; then
    unread "ruleset $ids ($label)"; continue
  fi
  if same_as "$work/live.json" "$here/$file"; then echo "$label: ruleset $ids matches scripts/$file"
  else problem "$label: ruleset $ids does not match scripts/$file"; fi
done

if rules=$(gh api "repos/$repo/rules/branches/main" --jq '.[].type'); then
  rules=$(printf '%s\n' "$rules" | sort -u | paste -sd, -)
  echo "Rules on main: $rules"
  [ "$rules" = "deletion,non_fast_forward,pull_request" ] || problem "main's rules must be deletion,non_fast_forward,pull_request"
else unread "the rules on main"; fi
# every pull_request rule on main, from any ruleset: exactly one, 2 approvals, no code-owner review (CODEOWNERS is gone)
if prr=$(gh api "repos/$repo/rules/branches/main" \
         --jq '.[] | select(.type == $ENV.PM_PR) | [(.parameters.required_approving_review_count|tostring), (.parameters.require_code_owner_review|tostring)] | @tsv'); then
  echo "Pull request rules on main (approvals, code-owner review): $(printf '%s' "$prr" | tr '\t\n' ' ;')"
  [ "$prr" = $'2\tfalse' ] || problem "main needs exactly one pull_request rule, with 2 approvals and no code-owner review"
else unread "main's pull_request rules"; fi

r2=$(gh api "repos/$repo/actions/permissions/workflow" --jq '.can_approve_pull_request_reviews') || r2="unread"
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
  problem "installed Apps can't be read with this token (GitHub's user/installations needs a GitHub App token), so confirm them by hand: open https://github.com/settings/installations, click Configure on each App, and note each one that reaches clarksville-records (All repositories, or listed) with any Read and write permission. Then run this again with --apps claude or --apps none (one value; any other App must first lose its access to clarksville-records, or the team amends ADR 0011). Only $allowed_app may be listed, and only if its Administration permission is not Read and write"
elif ! [[ "$apps" =~ ^(none|[a-z0-9][a-z0-9-]*(,[a-z0-9][a-z0-9-]*)*)$ ]]; then
  echo "Installed Apps with write on this repository: '$apps' (not claude or none)"
  problem "--apps takes one value, claude or none ('$apps' is not one)"
else
  echo "Installed Apps with write on this repository: $apps (confirmed by hand by $owner on $(date -u +%Y-%m-%d), not read by this script; none with Administration write)"
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

if [ "$problems" = 0 ]; then
  echo "OK: main is protected (R1'', R-D, R-T as written, R2 off, auto-merge off, $owner the only writer, both environments main only)."
  exit 0
fi
echo "NOT OK: $problems problem(s) above. Run this from Brian's PC, signed in as $owner. Send this output to the team."
exit 1
