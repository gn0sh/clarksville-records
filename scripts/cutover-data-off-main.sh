#!/usr/bin/env bash
# Cut Daylight's collector data over from main to branch records-data (ADR 0011; docs/tasks/data-off-main.md D3, the
# Operator's order; consumer rows D, CFG, S4; PR #54 security review: drift, F2, F4, F5, F7). The bash twin of
# scripts/cutover-data-off-main.ps1, which is the one Brian runs. Brian's PC only: every ruleset, settings and
# workflow write is his (U3-0 = no), so it refuses to run in a cloud session or CI (except --plan, which writes
# nothing on GitHub).
#
# Run it from a checkout of the cutover PR at its reviewed head (so the checks below run reviewed code):
#   git fetch origin pull/<P>/head && git checkout --detach <reviewed head>
#   bash scripts/cutover-data-off-main.sh --pr <P> --sha <reviewed head> --apps claude|none --report <review> [...]
#        --apps: first open https://github.com/settings/installations and click Configure on each App: claude if the
#        Claude App (github.com/apps/claude) is the only one reaching this repository with any Read and write
#        permission and none of Administration, Variables, Secrets and Environments is Read and write (S1-2); none
#        if no App does. No token Brian holds can list Apps, so this is his hand check (ADR 0011 Amendment
#        2026-11-18 (b), invariant I-person). Any other answer is refused before anything changes, and protect-main
#        (which gets it in step 4) reports any other answer NOT OK.
#   bash scripts/cutover-data-off-main.sh --plan [--ref <git rev>]   read-only: the seed step 3 would push from
#        origin/main's data/, its checks, "SEED DIGEST <sha256>" for the cutover PR's RECORDS_DATA_SEED_DIGEST,
#        "BASELINE <sha>" (origin/main) for its MAIN_PR_BASELINE, and the runbook 4.7.1 window listing from
#        WINDOW_START to that sha, to paste into the PR (--ref: the cutover head whose config/ holds the moved inputs;
#        default HEAD). Only gh reads, no push.
#   bash scripts/cutover-data-off-main.sh --prepare   on the cutover PR's branch (team, any machine): stages data/
#        out of the index (git rm -r --cached: the files stay on disk), data/ into .gitignore and .github/CODEOWNERS
#        deleted. Commit that, then --plan, and pin its SEED DIGEST in the gate's RECORDS_DATA_SEED_DIGEST (the
#        sha256 of `git ls-tree -r -z <seed> -- data`, the gate's own bytes). No gh call, no commit, no push.
#   bash scripts/cutover-data-off-main.sh --rollback [--cutover-merge <sha> [--data-from <sha>]]   undo (below)
#   bash scripts/cutover-data-off-main.sh --rollback --merge <R> --sha <reviewed head> --cutover-merge <sha>
#        --report <review> [...]
#   bash scripts/cutover-data-off-main.sh --check-attested   read-only: step 8's check again, for a later run
#
# Steps (it stops at the first failure and prints the exact --rollback command):
#   1. Refuses, changing nothing, from 05:00 to 10:30 UTC (steps 7 and 8 must not meet the 09:07 cron), while a
#      daily-update run is not completed, or while the repository variable MORNING_NOTE_SEND exists (a refused or
#      failed read of actions/variables counts as set). Also unless PR <P> is open into main, authored by gn0sh,
#      from this repository, at <sha>, this checkout is at <sha> with no local change, the PR pins one 40-hex
#      MAIN_PR_BASELINE equal to origin/main (ADR 0011 Amendment (c)), its head contains that main, main still
#      tracks data/ and holds .github/CODEOWNERS and one empty MAIN_PR_BASELINE (what the early rollback needs),
#      the runbook 4.7.1 window listing from WINDOW_START to main passes (printed for the record), and the seed
#      (step 3) already passes its checks and equals the PR's pin. records-data must be absent, or exactly that
#      seed (a re-run).
#   2. Disables daily-update and reads it back; stops if a run started meanwhile.
#   3. Seeds records-data: main's data/ minus every moved input (the curated files, data/localities/*/transcripts/
#      and data/maps/, I-in) whose config/ copy on the cutover head is the same blob, as one parentless commit. A
#      moved input the PR does not carry stays in, and is refused. Stops if main moved off the pinned baseline, or
#      unless its listing (git ls-tree -r -z <seed> -- data) holds no transcripts/ folder, nothing under data/maps/
#      and no curated name, passes python -m collector.data_shape, its rpc.json passes
#      python -m tools.scrub_rpc_phones --check, and its sha256 equals the PR's RECORDS_DATA_SEED_DIGEST. Pushes it
#      (never forced) and reads it back.
#   4. Runs scripts/protect-main.sh --pre-cutover --apps <answer> (R1'', R-D, R-T, R2 off; main still holds the old
#      workflow); its last line must start "OK: main is protected".
#   5. Merges the cutover PR with scripts/merge-reviewed.sh (main must still be the pinned baseline, and records-data
#      still the seed, read again just before: S1-5); its last line
#      must be "Rule suite <id> for <merge sha>: bypass", the squash's one parent must be the pinned baseline (this
#      merge sets it), and main must then track no data/. Then a plain scripts/protect-main.sh --check --apps
#      <answer> (no writes, main's new workflow) must print OK too.
#   6. Re-enables daily-update and reads it back.
#   7. Dispatches collect=false; the run's gate job must log the history line for exactly 1 commit after the
#      baseline (verified), its deploy job must succeed, and the site's build-info.json must name the seed as data_sha.
#   8. Dispatches collect=true (the first run after the baseline that pushes); the gate must log the same line, the
#      deploy must succeed, and records-data must then have moved past the seed, with its listing verifying with
#      gh attestation verify (the gate's flags).
# --rollback refuses at entry while the repository variable MORNING_NOTE_SEND or MAIN_PR_BASELINE exists (finding
# F4: R2 on reopens the bot path; a refused or failed read counts as set). It picks its path by where the cutover
# merge is, never by whether main tracks data/:
#   - --cutover-merge <sha> on main's first-parent line (the sha step 5 printed): it refuses unless that merge's parent tracks data/ and
#     holds .github/CODEOWNERS and one empty MAIN_PR_BASELINE, then disables daily-update and opens PR R from a new
#     branch: data/ from records-data's head, the workflow and .github/CODEOWNERS as they were before the cutover
#     merge, data/ out of .gitignore; every config/ input and reader stays as the cutover PR left them. The cutover
#     merge must itself track no data/ and hold no CODEOWNERS. S1-3: the data/ source must pass the gate's I-prov
#     check (its listing attested by daily-update.yml on main) or be the seed the merge's workflow pins; else it
#     refuses, and --data-from <sha> picks an ancestor of records-data's head that does.
#   - --merge <R> --sha <R's reviewed head> --cutover-merge <sha>: it refuses unless R's data/ listing is attested
#     or the seed pinned on main (S1-3; the pin is read from main, never from R or its parent: N1), R's head is one
#     commit whose parent is on main's first-parent line (N1), R's workflow and .github/CODEOWNERS are those of the
#     commit before the cutover merge (on main's first-parent line; never taken from R alone:
#     docs/architecture/data-off-main-trust-roots.md T-R3), and R's head tracks data/ and holds .github/CODEOWNERS
#     and one empty MAIN_PR_BASELINE, disables daily-update, merges R with merge-reviewed (a bypass, under R1''),
#     then stops with R2 still off unless main is that merge, tracks data/, and its workflow, CODEOWNERS and data/
#     are R's, byte for byte, with one empty MAIN_PR_BASELINE (ADR 0011 Amendment (c) item 7). Only then R1' back, R2
#     on, the workflow on, in that order.
#   - otherwise (the cutover merge is not on main): it refuses unless main tracks data/ and holds .github/CODEOWNERS
#     and one empty MAIN_PR_BASELINE, then disables daily-update, puts R1' (scripts/main-ruleset-r1p.json) back,
#     turns R2 on and the workflow on.
# records-data is kept. Exit: 0 done, 1 refused (nothing changed), 2 stopped after a change (see the undo line; Ctrl+C
# from step 2 on too: "STOPPED at step N (interrupted)").
# Needs: git, gh signed in as gn0sh (gh auth login), jq, curl, Python 3 with requirements.txt installed.
set -uo pipefail
repo=gn0sh/clarksville-records
owner=gn0sh
wfname=daily-update.yml
site=https://daylight.gnoshcodes.com
here=$(cd "$(dirname "$0")" && pwd)
r1p="$here/main-ruleset-r1p.json"
me="bash scripts/cutover-data-off-main.sh"
export CO_OWNER=$owner CO_RULESET='main: pull request required' CO_DEPLOY=deploy CO_SEED_VAR=MORNING_NOTE_SEND
export CO_BASELINE_VAR=MAIN_PR_BASELINE CO_BASE=main
# ADR 0011 Amendment (c), runbook 4.7.1 (L-b, main-protect/window-start-gap): the window starts at main's sha read
# just before ruleset 27502319 (R1) was first written. That ruleset was created 2026-11-17T22:21:09Z (gh api
# rulesets/27502319 created_at). main was then 4c5cd910 (PR #31, merged 16:49:13Z by gn0sh) and did not move again
# until b5a3638d (PR #32, 00:02:13Z on 2026-11-18), so whatever the exact read, the start is 4c5cd910. Empty or wrong
# = step 1 refuses. Changed only by a reviewed PR.
WINDOW_START=4c5cd91022b74f5b7ad68ec94cdb863fcc444acd
# The two known bot merges (ADR 0010; runbook 4.7.1): each its own PR, merged by a Bot, changing only v1-canary.yml
KNOWN1=3ef440aea9e5ce7374cdb789a05d646d74a91ac3; KNOWN1_PR=40   # the V1 probe
KNOWN2=2b207042a53e4d11dadfee978b029392df63c376; KNOWN2_PR=49   # the V1' probe (2026-11-18)
# I-in: what must never be in the seed (B1b's collector/data_shape.py refuses the same; this guard does not wait
# for it). The curated names come from collector/data_shape.py CURATED_NAMES plus fin-books-accepted.yml.
CURATED='names\.yml|procedural-titles\.yml|corrections-log\.json|published-fact-changes\.yml|fin-books-accepted\.yml'
GUARD=$'\tdata/(([^/]*/)*transcripts/|maps/|([^/]*/)*('"$CURATED"')$)'
MOVED='^data/(localities/[^/]+/transcripts/|maps/|([^/]*/)*('"$CURATED"')$)'
RPC=data/localities/cmc-rpc/rpc.json
# The gate's I-prov flags (ADR 0011 decision 3), unchanged
ATTEST_ID="https://github.com/$repo/.github/workflows/daily-update.yml@refs/heads/main"
# The one whitelist (the same text as scripts/protect-main.sh and scripts/u3-toggle.sh)
wl='def wl: {name, target, enforcement, conditions,
  bypass_actors: ([.bypass_actors[]? | {actor_id, actor_type, bypass_mode}] | sort_by(.actor_type, .actor_id, .bypass_mode)),
  rules: ([.rules[]? | if .parameters == null then {type} else {type, parameters} end] | sort_by(.type))}; wl'

usage="Usage: $me --pr <P> --sha <reviewed head> --apps claude|none --report <review> [...] | --plan [--ref <rev>] | --rollback [--cutover-merge <sha> [--data-from <sha>]] | --rollback --merge <R> --sha <sha> --cutover-merge <sha> --report <review> [...] | --check-attested"
mode=cutover; pr=""; sha=""; reports=(); ref=HEAD; cmerge=""; rpr=""; apps=""; datafrom=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --pr) pr="${2:-}"; shift 2 || { echo "$usage"; exit 1; } ;;
    --sha) sha="${2:-}"; shift 2 || { echo "$usage"; exit 1; } ;;
    --apps) apps="${2:-}"; shift 2 || { echo "$usage"; exit 1; } ;;
    --report) [ -n "${2:-}" ] || { echo "$usage"; exit 1; }; reports+=("$2"); shift 2 ;;
    --plan) mode=plan; shift ;;
    --prepare) mode=prepare; shift ;;
    --ref) ref="${2:-}"; shift 2 || { echo "$usage"; exit 1; } ;;
    --rollback) mode=rollback; shift ;;
    --cutover-merge) cmerge="${2:-}"; shift 2 || { echo "$usage"; exit 1; } ;;
    --data-from) datafrom="${2:-}"; shift 2 || { echo "$usage"; exit 1; } ;;
    --merge) rpr="${2:-}"; shift 2 || { echo "$usage"; exit 1; } ;;
    --check-attested) mode=attested; shift ;;
    *) echo "$usage"; exit 1 ;;
  esac
done

utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
shown() { LC_ALL=C tr -c '\040-\176\n' '?'; }   # never a raw byte outside printable ASCII in the output
step=0
undo="$me --rollback"
refuse() { echo "REFUSED: $1. Nothing was changed."; exit 1; }
merge_from=""   # main's sha just before the cutover merge call; set from then on
refresh_undo() {
  local now
  # After the merge call, main may have moved even when the call's output was not understood: the undo then needs
  # the merge sha (data-off-main/undo-line-after-merge).
  if [ -n "$merge_from" ] && [ "$undo" = "$me --rollback" ]; then
    if now=$(fetch_main 2>/dev/null) && [ "$now" != "$merge_from" ]; then undo="$me --rollback --cutover-merge $now"; fi
  fi
}
fail() {
  refresh_undo
  echo "STOPPED at step $step ($(utc)): $1"
  echo "Undo with: $undo"
  exit 2
}
# Ctrl+C or a stop signal (data-off-main/ps-ctrlc-exit-zero, the .ps1's finally block): steps 0 and 1 only read;
# from step 2 on, the stop line and the undo line fail prints for the step, and exit 2 (not 130)
interrupted() {
  trap - INT TERM HUP
  if [ "$step" -lt 2 ]; then
    echo "STOPPED (interrupted) ($(utc)) before any change. Nothing was written on GitHub."
    exit 1
  fi
  refresh_undo
  echo "STOPPED at step $step (interrupted) ($(utc)): Ctrl+C or a stop signal."
  echo "Undo with: $undo"
  exit 2
}

if [ "$mode" != plan ] && [ "$mode" != prepare ]; then
  for v in CLAUDE_CODE_REMOTE GITHUB_ACTIONS CI; do
    [ -z "${!v:-}" ] || refuse "$v is set: the cutover runs only from Brian's PC (ruleset, settings and workflow writes are his)"
  done
fi
for t in git jq; do command -v "$t" >/dev/null 2>&1 || refuse "$t not found: install it, then run this again"; done
top=$(git rev-parse --show-toplevel 2>/dev/null) || refuse "run this inside the clarksville-records checkout"
cd "$top" || refuse "could not enter $top"
work=$(mktemp -d) || refuse "could not make a temporary folder"
trap 'trap - INT TERM HUP; rm -rf "$work"' EXIT   # an intended exit is never reported as interrupted
trap interrupted INT TERM HUP
if command -v sha256sum >/dev/null 2>&1; then sha256() { sha256sum | cut -d' ' -f1; }
else sha256() { shasum -a 256 | cut -d' ' -f1; }; fi
py=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then py=$c; break; fi
done

# ---------------------------------------------------------------------------------------------- named calls
# Each call to another script or another branch's contract is one function, so a change there is one edit here.
run_protect_main() { bash "$here/protect-main.sh" --pre-cutover --apps "$1"; }   # D1, before the merge: last line "OK: main is protected..."
run_protect_check() { bash "$here/protect-main.sh" --check --apps "$1"; }      # D1, after the merge: no writes, same OK line
run_merge_reviewed() { bash "$here/merge-reviewed.sh" "$@"; }                 # D1: last line "Rule suite <id> for <sha>: bypass"
run_data_shape() { "$py" -B -m collector.data_shape "$1"; }                   # B1/B1b: exit 0 = the listing passes
run_scrub_check() { "$py" -B -m tools.scrub_rpc_phones --check --path "$1"; } # B1b: read-only, exit 1 on a phone
pinned_seed_digest() {   # $1 rev: B2's gate env line RECORDS_DATA_SEED_DIGEST: "<64 hex>", exactly one, in its workflow
  local wf n v
  wf=$(git show "$1:.github/workflows/$wfname" 2>/dev/null) || return 1
  n=$(printf '%s\n' "$wf" | sed 's/\${RECORDS_DATA_SEED_DIGEST:-}//g' | grep -cE "RECORDS_DATA_SEED_DIGEST[\"']?[[:space:]]*:" || true)
  v=$(printf '%s\n' "$wf" | sed -nE 's/^[[:space:]]*RECORDS_DATA_SEED_DIGEST:[[:space:]]*"([0-9a-f]{64})".*$/\1/p')
  [ "$n" = 1 ] && [[ "$v" =~ ^[0-9a-f]{64}$ ]] && echo "$v"
}
pinned_baseline() {   # $1 rev: the gate env line MAIN_PR_BASELINE: "<40 hex>", exactly one (ADR 0011 Amendment (c))
  local wf n v
  wf=$(git show "$1:.github/workflows/$wfname" 2>/dev/null) || return 1
  n=$(printf '%s\n' "$wf" | sed 's/\${MAIN_PR_BASELINE:-}//g' | grep -cE "MAIN_PR_BASELINE[\"']?[[:space:]]*:" || true)
  v=$(printf '%s\n' "$wf" | sed -nE 's/^[[:space:]]*MAIN_PR_BASELINE:[[:space:]]*"([0-9a-f]{40})".*$/\1/p')
  [ "$n" = 1 ] && [[ "$v" =~ ^[0-9a-f]{40}$ ]] && echo "$v"
}
baseline_empty() {    # $1 rev: its workflow holds exactly one MAIN_PR_BASELINE line, and its value is "" (F4)
  local wf
  wf=$(git show "$1:.github/workflows/$wfname" 2>/dev/null) || return 1
  [ "$(printf '%s\n' "$wf" | sed 's/\${MAIN_PR_BASELINE:-}//g' | grep -cE "MAIN_PR_BASELINE[\"']?[[:space:]]*:" || true)" = 1 ] \
    && [ "$(printf '%s\n' "$wf" | grep -cE '^[[:space:]]*MAIN_PR_BASELINE:[[:space:]]*""([[:space:]]|$)' || true)" = 1 ]
}
gate_verified() {     # $1 run id, $2 baseline: B2's gate job succeeded and logged its history line for exactly 1 commit
  local g jid gc counts
  g=$(CO_JOB=gate gh api "repos/$repo/actions/runs/$1/jobs?per_page=100" --jq '.jobs[] | select(.name == $ENV.CO_JOB) | [(.id|tostring), (.conclusion|tostring)] | @tsv') || return 1
  IFS=$'\t' read -r jid gc <<< "$g" || true
  [[ "${jid:-}" =~ ^[0-9]+$ ]] && [ "${gc:-}" = success ] || { echo "The gate job reads '${gc:-missing}', not success."; return 1; }
  gh api "repos/$repo/actions/jobs/$jid/logs" > "$work/gate.log" || return 1
  counts=$(sed -nE "s/.*Every commit on main after $2 was merged by a person, reviewed at its head: *([0-9]+) commit\(s\)\..*/\1/p" "$work/gate.log" | paste -sd, -)
  [ "$counts" = 1 ] || { echo "The gate's history line after $2 reads '${counts:-missing}' commit(s), not exactly 1."; return 1; }
  echo "Gate: every commit on main after $2 was merged by a person, reviewed at its head: 1 commit(s) (verified)."
}
build_info_data_sha() {  # B4: the live site's build-info.json names D as data_sha (cache-busted: Pages caches 10 min)
  curl -fsS --max-time 30 "$site/build-info.json?cutover=$(date +%s)" | jq -r '.data_sha // empty'
}
verify_attested() {      # $1 listing file: the gate's I-prov check (ADR 0011 decision 3)
  gh attestation verify "$1" --repo "$repo" --cert-identity "$ATTEST_ID" --source-ref refs/heads/main \
    --predicate-type https://slsa.dev/provenance/v1 --deny-self-hosted-runners
}

# ---------------------------------------------------------------------------------------------- git helpers
fetch_main() { git fetch --quiet --no-tags origin "+refs/heads/main:refs/cutover/main" && git rev-parse --verify -q "refs/cutover/main^{commit}"; }
fetch_rd() {   # records-data's head on origin, "" when there is none; 1 when it could not be read
  local l
  l=$(git ls-remote origin refs/heads/records-data) || return 1
  [ -n "$l" ] || { echo ""; return 0; }
  git fetch --quiet --no-tags origin "+refs/heads/records-data:refs/cutover/records-data" || return 1
  git rev-parse --verify -q "refs/cutover/records-data^{commit}"
}
tracks_data() { [ -n "$(git ls-tree --name-only "$1" -- data)" ]; }
on_main_line() {   # $1 rev, $2 main (fetched): $1 is a commit on main's first-parent line (the gate's own test);
  # every trust root the rollback reads comes from such a commit (docs/architecture/data-off-main-trust-roots.md)
  local c
  c=$(git rev-parse --verify -q "$1^{commit}") || return 1
  [ "$(git rev-list --first-parent "$2" | grep -cxF -- "$c")" = 1 ]   # -c reads it all (no SIGPIPE under pipefail)
}
parents() { git cat-file commit "$1" | sed '/^$/q' | grep -c '^parent ' || true; }
listing_of() { git ls-tree -r -z "$1" -- data; }
gitignore_edit() {   # the rollback's one .gitignore edit: $1's .gitignore without its data/ lines, as a written blob
  # sha; "" when $1 has none; 1 on a failed read. The open path writes it into R, the merge path checks R holds it (L1)
  local gi
  gi=$(git rev-parse --verify -q "$1:.gitignore") || return 0
  git cat-file blob "$gi" | { grep -vE '^/?data/?(\*\*?)?[[:space:]]*$' || [ "$?" = 1 ]; } | git hash-object -w --stdin
}

build_seed() {   # $1 main rev, $2 cutover head: sets seed_tree, seed_digest, n_seed, n_left; writes $work/listing
  local rec meta path blob cb LC_ALL=C
  n_seed=0; n_left=0; seed_tree=""; seed_digest=""
  listing_of "$1" > "$work/main.z" || { why="could not read main's data/"; return 1; }
  : > "$work/seed.z"
  while IFS= read -r -d '' rec; do
    meta=${rec%%$'\t'*}; path=${rec#*$'\t'}; blob=${meta##* }
    if [[ "$path" =~ $MOVED ]]; then
      cb=$(git rev-parse --verify -q "$2:config/${path#data/}" 2>/dev/null) || cb=""
      if [ "$cb" = "$blob" ]; then
        n_left=$((n_left + 1)); echo "  left out (the cutover PR has it at config/${path#data/}): $path" | shown; continue
      fi
      echo "  kept, so refused below (the cutover PR has no same config/${path#data/}): $path" | shown
    fi
    printf '%s\0' "$rec" >> "$work/seed.z"; n_seed=$((n_seed + 1))
  done < "$work/main.z"
  rm -f "$work/index"
  GIT_INDEX_FILE="$work/index" git read-tree --empty && GIT_INDEX_FILE="$work/index" git update-index -z --index-info < "$work/seed.z" \
    && seed_tree=$(GIT_INDEX_FILE="$work/index" git write-tree) || { why="could not build the seed tree"; return 1; }
  listing_of "$seed_tree" > "$work/listing" || { why="could not read the seed's listing"; return 1; }
  cmp -s "$work/listing" "$work/seed.z" || { why="the seed's listing is not main's data/ minus the moved inputs"; return 1; }
  [ "$(git ls-tree --name-only "$seed_tree" | paste -sd, -)" = data ] || { why="the seed tree is not data/ only"; return 1; }
  seed_digest=$(sha256 < "$work/listing")
}
check_seed() {   # the checks of step 3 on $work/listing and $seed_tree; sets why
  local bad b
  bad=$(LC_ALL=C grep -zacE -- "$GUARD" "$work/listing") || [ $? = 1 ] || { why="could not check the seed's names"; return 1; }
  if [ "$bad" != 0 ]; then
    LC_ALL=C grep -zaE -m 20 -- "$GUARD" "$work/listing" | LC_ALL=C tr '\000' '\n' | cut -f2- | shown \
      | while IFS= read -r e; do echo "  not allowed in the seed (I-in: it belongs in config/): $e"; done
    why="the seed holds $bad entries under a transcripts/ folder, data/maps/ or a curated name (I-in)"; return 1
  fi
  echo "Seed names: no transcripts/ folder, nothing under data/maps/, no curated name."
  run_data_shape "$work/listing" || { why="the seed's listing fails python -m collector.data_shape (I-data'')"; return 1; }
  echo "Seed listing passes python -m collector.data_shape."
  b=$(git rev-parse --verify -q "$seed_tree:$RPC") || { why="the seed has no $RPC for the phone check"; return 1; }
  git cat-file blob "$b" > "$work/rpc.json" || { why="could not read the seed's $RPC"; return 1; }
  run_scrub_check "$work/rpc.json" || { why="the seed's $RPC has a phone number in a case location (tools/scrub_rpc_phones.py --check)"; return 1; }
  echo "Seed $RPC passes python -m tools.scrub_rpc_phones --check."
}
need_python() {
  [ -n "$py" ] || refuse "Python 3.10 or later not found (python3 or python): install it and requirements.txt, then run this again"
  "$py" -B -c 'import collector.data_shape, tools.scrub_rpc_phones' 2>/dev/null \
    || refuse "Python cannot load collector.data_shape and tools.scrub_rpc_phones here: run pip install -r requirements.txt, then this again"
}

# ---------------------------------------------------------------------------------------------- GitHub helpers
var_set() {   # $1 name: 0 when the repository variable exists or the list cannot be read (fail closed), 1 when absent
  local names
  names=$(gh api --paginate "repos/$repo/actions/variables?per_page=100" --jq '.variables[].name' 2>/dev/null) || return 0
  grep -qxF "$1" <<< "$names"
}
runs_busy() {   # prints the count of daily-update runs not completed; 1 on a failed read
  local st
  st=$(gh api "repos/$repo/actions/workflows/$wfname/runs?per_page=30" --jq '.workflow_runs[].status') || return 1
  printf '%s\n' "$st" | grep -cv -e '^completed$' -e '^$' || true
}
wf_state() { gh api "repos/$repo/actions/workflows/$wfname" --jq '.state'; }
wf_set() {   # $1 disable|enable, $2 expected state
  local s i
  gh api -X PUT "repos/$repo/actions/workflows/$wfname/$1" --silent || return 1
  # GitHub's read-back can lag the PUT by a few seconds (cutover run 4, 2026-11-19): read up to 10 times, 3 s apart
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if s=$(wf_state) && [ "$s" = "$2" ]; then return 0; fi
    [ "$i" = 10 ] || sleep 3
  done
  echo "daily-update reads '$s', not $2, after 10 reads."
  return 1
}
dispatch_run() {   # $1 collect value: dispatches on main, prints the new run's id
  local before id i
  before=$(gh api "repos/$repo/actions/workflows/$wfname/runs?event=workflow_dispatch&per_page=20" --jq '[.workflow_runs[].id] | max // 0') || return 1
  [[ "$before" =~ ^[0-9]+$ ]] || return 1
  gh api -X POST "repos/$repo/actions/workflows/$wfname/dispatches" -f ref=main -f "inputs[collect]=$1" --silent || return 1
  export CO_BEFORE=$before
  for i in $(seq 1 24); do
    sleep 5
    id=$(gh api "repos/$repo/actions/workflows/$wfname/runs?event=workflow_dispatch&branch=main&per_page=20" \
         --jq '[.workflow_runs[] | select(.id > ($ENV.CO_BEFORE | tonumber)) | .id] | min // empty' 2>/dev/null) || id=""
    [[ "$id" =~ ^[0-9]+$ ]] && { echo "$id"; return 0; }
  done
  return 1
}
wait_run() {   # $1 run id, $2 minutes: waits until it completes; prints its conclusion
  local end st fails=0 n=0
  end=$(( $(date +%s) + $2 * 60 ))
  while :; do
    st=$(gh api "repos/$repo/actions/runs/$1" --jq '[.status, (.conclusion|tostring)] | @tsv' 2>/dev/null) || st=""
    if [ -z "$st" ]; then fails=$((fails + 1)); [ "$fails" -lt 5 ] || return 1
    else
      fails=0
      [ "${st%%$'\t'*}" != completed ] || { echo "${st#*$'\t'}"; return 0; }
    fi
    [ "$(date +%s)" -lt "$end" ] || return 1
    n=$((n + 1)); [ $((n % 10)) != 0 ] || echo "  run $1 still ${st%%$'\t'*} ($(utc))" >&2
    sleep 30
  done
}
step8_wait() {   # minutes step 8 may wait: at most 360, and the wait ends before 09:00 UTC (data-off-main/window-vs-duration)
  local hm left
  hm=$(date -u +%H%M)
  [[ "$hm" =~ ^[0-9]{4}$ ]] || return 1
  left=$(( (540 - (10#${hm:0:2} * 60 + 10#${hm:2:2}) + 1440) % 1440 - 1 ))
  [ "$left" -ge 1 ] || left=1
  [ "$left" -lt 360 ] && echo "$left" || echo 360
}
job_conclusion() { CO_JOB=$2 gh api "repos/$repo/actions/runs/$1/jobs?per_page=100" --jq '.jobs[] | select(.name == $ENV.CO_JOB) | .conclusion'; }
put_r1p() {   # PUT main's scripts/main-ruleset-r1p.json (read at rollback step 1; whitelisted), read it back
  local ids
  ids=$(gh api --paginate "repos/$repo/rulesets?per_page=100" --jq '.[] | select(.name == $ENV.CO_RULESET) | .id') || { echo "Could not list the rulesets."; return 1; }
  [[ "$ids" =~ ^[0-9]+$ ]] || { echo "Expected exactly one ruleset named '$CO_RULESET', got: $(printf '%s' "$ids" | paste -sd, -)"; return 1; }
  jq -c "$wl" "$r1p" > "$work/r1p.json" || { echo "Could not read scripts/main-ruleset-r1p.json."; return 1; }
  gh api -X PUT "repos/$repo/rulesets/$ids" --input "$work/r1p.json" --silent || return 1
  gh api "repos/$repo/rulesets/$ids" > "$work/live.json" || return 1
  [ "$(jq -S -c "$wl" "$work/live.json")" = "$(jq -S -c "$wl" "$r1p")" ] || { echo "Ruleset $ids did not read back as R1'."; return 1; }
  echo "R1' back: ruleset $ids reads back equal to scripts/main-ruleset-r1p.json."
}
r2_on() {
  local v
  gh api -X PUT "repos/$repo/actions/permissions/workflow" -F can_approve_pull_request_reviews=true --silent || return 1
  v=$(gh api "repos/$repo/actions/permissions/workflow" --jq '.can_approve_pull_request_reviews') || return 1
  [ "$v" = true ] || { echo "R2 reads '$v', not true."; return 1; }
  echo "R2 on: GitHub Actions may create and approve pull requests (reads back true)."
}
need_gh() {
  for t in gh curl; do command -v "$t" >/dev/null 2>&1 || refuse "$t not found: install it, then run this again"; done
  gh auth status >/dev/null 2>&1 || refuse "not signed in: run gh auth login (as $owner)"
}
merged_line_ok() {   # $1 merge-reviewed output: prints the merge sha when its last line is a bypass rule suite for it
  local last m
  last=$(printf '%s\n' "$1" | grep . | tail -n 1)
  m=$(sed -nE 's/^Rule suite [0-9]+ for ([0-9a-f]{40}): bypass$/\1/p' <<< "$last")
  [ -n "$m" ] && echo "$m"
}
window_check() {   # $1 start, $2 end (fetched): the runbook 4.7.1 block; prints one line per commit and "checked N commits"
  local start=$1 end=$2 list c pr t files n=0
  [[ "$start" =~ ^[0-9a-f]{40}$ ]] || { why="the window start '$start' is not a 40-hex sha (WINDOW_START in this script; runbook 4.7.1: the manager supplies it, else the architect picks the window)"; return 1; }
  git merge-base --is-ancestor "$start" "$end" 2>/dev/null || { why="the window start $start is not an ancestor of main $end"; return 1; }
  list=$(git log --first-parent --format=%H "$start..$end" -- . ':(exclude)data/') || { why="could not list main's commits after $start"; return 1; }
  echo "Window (runbook 4.7.1): every commit outside data/ on main's first-parent line from $start to $end:"
  for c in $list; do
    pr=$(CO_COMMIT=$c gh api "repos/$repo/commits/$c/pulls" --jq '[.[] | select(.merged_at != null and .base.ref == $ENV.CO_BASE and .merge_commit_sha == $ENV.CO_COMMIT) | .number] | first // empty') \
      || { why="could not read the pull requests of $c"; return 1; }
    t=none
    if [ -n "$pr" ]; then
      [[ "$pr" =~ ^[0-9]+$ ]] || { why="could not read the pull requests of $c"; return 1; }
      t=$(gh api "repos/$repo/pulls/$pr" --jq '.merged_by.type // empty') || { why="could not read pull request #$pr"; return 1; }
      [ -n "$t" ] || t=none
    else
      pr=none
    fi
    n=$((n + 1))
    echo "$c PR #$pr merged_by.type=$t"
    if [ "$t" = Bot ] && { { [ "$c" = "$KNOWN1" ] && [ "$pr" = "$KNOWN1_PR" ]; } || { [ "$c" = "$KNOWN2" ] && [ "$pr" = "$KNOWN2_PR" ]; }; }; then
      files=$(git show --format= --name-only "$c" | grep .) || files=""
      if [ "$files" = .github/workflows/v1-canary.yml ]; then
        echo "KNOWN EXCEPTION: $c is PR #$pr, a V1/V1' probe canary (only .github/workflows/v1-canary.yml); name it in the cutover PR"
        continue
      fi
    fi
    [ "$t" = User ] || { why="$c (PR #$pr) was not merged by a person (merged_by.type=$t): treat it as an incident; the baseline is not set"; return 1; }
  done
  echo "checked $n commits"
  [ "$n" -gt 0 ] || { why="no commit in the window $start..$end (a wrong or placeholder start: the cutover PR's base at least is in it)"; return 1; }
}
data_verified() {   # $1 listing file, $2 the pinned seed digest or "": J2's attestation (I-prov) or the pinned seed (S1-3)
  if [ -n "$2" ] && [ "$(sha256 < "$1")" = "$2" ]; then echo "the pinned seed (RECORDS_DATA_SEED_DIGEST $2)"; return 0; fi
  verify_attested "$1" >&2 || return 1
  echo "attested by daily-update.yml on main"
}
restore_ok() {   # $1 rev: what R2 on needs there: data/ tracked, .github/CODEOWNERS, one empty MAIN_PR_BASELINE; sets why
  tracks_data "$1" || { why="$1 tracks no data/"; return 1; }
  git cat-file -e "$1:.github/CODEOWNERS" 2>/dev/null || { why="$1 has no .github/CODEOWNERS"; return 1; }
  baseline_empty "$1" || { why="$1's workflow sets MAIN_PR_BASELINE, or it is not exactly one empty value (counts as set)"; return 1; }
}

# ---------------------------------------------------------------------------------------------- --prepare
if [ "$mode" = prepare ]; then
  if [ -n "$(git ls-files -- data | head -n 1)" ]; then
    git rm -r -q --cached -- data || refuse "git rm -r --cached data failed"
    echo "Staged: data/ out of the index (the files stay on disk)."
  else
    echo "data/ is already out of the index."
  fi
  if ! git check-ignore -q data/; then
    printf '%s\n' "# ADR 0011: collector output lives on branch records-data (scripts/fetch-data fills data/)" "data/" >> .gitignore \
      && git add .gitignore || refuse "could not add data/ to .gitignore"
    echo "Staged: data/ in .gitignore."
  else
    echo "data/ is already ignored."
  fi
  if [ -n "$(git ls-files -- .github/CODEOWNERS)" ]; then
    git rm -q -- .github/CODEOWNERS || refuse "git rm .github/CODEOWNERS failed"
    echo "Staged: .github/CODEOWNERS deleted (ADR 0011 decision 5)."
  fi
  [ -z "$(git ls-files -- data | head -n 1)" ] && git check-ignore -q data/ \
    || refuse "data/ is still tracked or not ignored after --prepare"
  echo "PREPARED: commit this, then run $me --plan and set RECORDS_DATA_SEED_DIGEST in the gate step's env to its SEED DIGEST."
  exit 0
fi

# ---------------------------------------------------------------------------------------------- --plan
if [ "$mode" = plan ]; then
  need_python
  need_gh
  h=$(git rev-parse --verify -q "$ref^{commit}") || refuse "no commit '$ref' here"
  m=$(fetch_main) || refuse "could not fetch main from origin"
  tracks_data "$m" || refuse "main $m tracks no data/: nothing to seed"
  echo "PLAN (nothing is pushed or written): the seed from main $m's data/, against the cutover head $h's config/."
  build_seed "$m" "$h" || refuse "$why"
  echo "Seed: $n_seed files ($n_left moved inputs left out)."
  check_seed || refuse "$why"
  echo "SEED DIGEST $seed_digest"
  echo "BASELINE $m"
  stale=0
  if p=$(pinned_seed_digest "$h"); then
    if [ "$p" = "$seed_digest" ]; then echo "The cutover head pins this digest."
    else echo "The cutover head pins $p, not this digest: update RECORDS_DATA_SEED_DIGEST."; stale=1; fi
  else
    echo "The cutover head pins no RECORDS_DATA_SEED_DIGEST yet: set it to the digest above."
  fi
  if p=$(pinned_baseline "$h"); then
    if [ "$p" = "$m" ]; then echo "The cutover head pins this baseline."
    else echo "The cutover head pins MAIN_PR_BASELINE $p, not this baseline: update MAIN_PR_BASELINE."; stale=1; fi
  else
    echo "The cutover head pins no single 40-hex MAIN_PR_BASELINE yet: set it to the BASELINE above."
  fi
  git merge-base --is-ancestor "$m" "$h" || { echo "The cutover head $h does not contain main $m: update its branch from main."; stale=1; }
  echo "Paste everything from here to 'checked N commits' into the cutover PR (runbook 4.7.1):"
  window_check "$WINDOW_START" "$m" || refuse "the window check stopped: $why"
  exit "$stale"
fi

# ---------------------------------------------------------------------------------------------- --check-attested
check_attested() {   # $1 the seed sha or "": records-data moved past it, and its listing verifies
  local d
  d=$(fetch_rd) || { why="could not read records-data"; return 1; }
  [ -n "$d" ] || { why="records-data does not exist"; return 1; }
  [ "$(parents "$d")" -ge 1 ] || { why="records-data $d is still a parentless commit (the seed): no run has pushed yet"; return 1; }
  if [ -n "$1" ]; then
    git merge-base --is-ancestor "$1" "$d" || { why="records-data $d does not descend from the seed $1"; return 1; }
  fi
  listing_of "$d" > "$work/head-listing" || { why="could not read records-data's listing"; return 1; }
  verify_attested "$work/head-listing" || { why="records-data $d: its listing is not attested by daily-update.yml on main"; return 1; }
  echo "records-data $d (listing sha256 $(sha256 < "$work/head-listing")) is attested by daily-update.yml on main."
}
if [ "$mode" = attested ]; then
  need_gh
  check_attested "" || { echo "NOT ATTESTED: $why."; exit 1; }
  exit 0
fi

# ---------------------------------------------------------------------------------------------- --rollback
if [ "$mode" = rollback ]; then
  need_gh
  step=1
  echo "Rollback step 1 ($(utc)): refusals."
  var_set MORNING_NOTE_SEND && refuse "MORNING_NOTE_SEND is set, or the variables could not be read (counts as set): Brian deletes it first (Settings > Secrets and variables > Actions > Variables), because R2 on reopens the bot path (F4)"
  var_set MAIN_PR_BASELINE && refuse "the variable MAIN_PR_BASELINE is set, or the variables could not be read (counts as set): Brian deletes it first (F4)"
  m=$(fetch_main) || refuse "could not fetch main from origin"
  # L2 data-off-main/rollback-checkout-unpinned: R1' is main $m's scripts/main-ruleset-r1p.json, never this checkout's
  r1p="$work/main-ruleset-r1p.json"
  git cat-file blob "$m:scripts/main-ruleset-r1p.json" > "$r1p" 2>/dev/null && jq -e 'type == "object" and (.rules | type) == "array"' "$r1p" >/dev/null 2>&1 \
    || refuse "main $m holds no readable scripts/main-ruleset-r1p.json (R1' is read from main)"
  if [ -n "$rpr" ]; then
    path=merge
    [[ "$rpr" =~ ^[0-9]+$ ]] && [[ "$sha" =~ ^[0-9a-f]{40}$ ]] && [[ "$cmerge" =~ ^[0-9a-f]{40}$ ]] && [ "${#reports[@]}" -ge 1 ] \
      || refuse "--merge needs <R> --sha <reviewed head> --cutover-merge <sha> --report <review> (the open path prints the line)"
    git fetch --quiet --no-tags origin "+refs/pull/$rpr/head:refs/cutover/rollback" || refuse "could not fetch pull request #$rpr's head"
    [ "$(git rev-parse --verify -q "refs/cutover/rollback^{commit}")" = "$sha" ] || refuse "origin's pull/$rpr/head is not $sha"
    restore_ok "$sha" || refuse "the restore PR #$rpr at $sha does not give R2 what it needs: $why (F4)"
    # Trust roots T-R3: the workflow and CODEOWNERS R2 comes on over are pinned to the commit before the cutover merge,
    # on main's first-parent line, never taken from R alone (R's author controls R)
    on_main_line "$cmerge" "$m" || refuse "--cutover-merge $cmerge is not on main's first-parent line (give the merge sha step 5 printed)"
    tracks_data "$cmerge" && refuse "$cmerge tracks data/: that is not the cutover merge (give the merge sha step 5 printed)"
    git cat-file -e "$cmerge:.github/CODEOWNERS" 2>/dev/null && refuse "$cmerge holds .github/CODEOWNERS: that is not the cutover merge (give the merge sha step 5 printed)"
    before=$(git rev-parse --verify -q "$cmerge^1") || refuse "could not read $cmerge's parent"
    for f in ".github/workflows/$wfname" .github/CODEOWNERS; do
      a=$(git rev-parse --verify -q "$before:$f") || a=""
      b=$(git rev-parse --verify -q "$sha:$f") || b=""
      [ -n "$a" ] && [ "$a" = "$b" ] \
        || refuse "the restore PR #$rpr's $f (blob '${b:-none}') is not the one before the cutover merge $cmerge (blob '${a:-none}'; T-R3)"
    done
    # S1-3 data-off-main/rollback-unverified-data: R's data/ must be a verified records-data tree (its listing
    # attested by J2, or the seed pinned on main). N1 data-off-main/rollback-seedpin-untrusted: the pin is read from
    # main $m (fetched above), never from R or its parent, which R's author controls
    seedpin=$(pinned_seed_digest "$m") || seedpin=""
    listing_of "$sha" > "$work/r-listing" || refuse "could not read the restore PR's data/ listing"
    src_ok=$(data_verified "$work/r-listing" "$seedpin") \
      || refuse "the restore PR #$rpr's data/ (listing sha256 $(sha256 < "$work/r-listing")) is neither attested by daily-update.yml on main nor the pinned seed (S1-3): open a new one with --data-from <an attested records-data sha>"
    # N1: R is one commit on main's first-parent line, so the squash merges exactly the reviewed head's diff
    rp=$(git rev-parse --verify -q "$sha^1") || refuse "could not read the restore PR's parent"
    [ "$(parents "$sha")" = 1 ] && on_main_line "$rp" "$m" \
      || refuse "the restore PR #$rpr's parent $rp is not on main's first-parent line (N1: R must be one commit on main, as --rollback --cutover-merge opens it)"
    # L1 data-off-main/rollback-r-scope-unchecked: against its parent, R changes only data/, the workflow, CODEOWNERS
    # and .gitignore (plumbing, no rename detection, NUL-separated), and its .gitignore is the open path's edit
    git diff-tree -r --no-renames --name-only -z "$rp" "$sha" > "$work/r-scope" || refuse "could not list the restore PR's changes"
    beyond=""
    while IFS= read -r -d '' f; do
      case "$f" in data/*|".github/workflows/$wfname"|.github/CODEOWNERS|.gitignore) ;; *) beyond="$beyond $f" ;; esac
    done < "$work/r-scope"
    [ -z "$beyond" ] || refuse "the restore PR #$rpr changes files beyond data/, the workflow, .github/CODEOWNERS and .gitignore:$beyond (L1)"
    want_gi=$(gitignore_edit "$rp") || refuse "could not read the .gitignore of the restore PR's parent $rp"
    have_gi=$(git rev-parse --verify -q "$sha:.gitignore") || have_gi=""
    [ "$want_gi" = "$have_gi" ] \
      || refuse "the restore PR #$rpr's .gitignore (blob '${have_gi:-none}') is not its parent's without the data/ lines (blob '${want_gi:-none}'; L1)"
    echo "Restore PR #$rpr at $sha tracks data/, holds .github/CODEOWNERS and one empty MAIN_PR_BASELINE; its data/ is $src_ok."
    echo "Its workflow and .github/CODEOWNERS are those before the cutover merge $cmerge; its parent $rp is on main."
  elif [[ "$cmerge" =~ ^[0-9a-f]{40}$ ]] && on_main_line "$cmerge" "$m"; then
    path=open
    # main-protect/rollback-cutover-merge-unverified: the sha must look like the cutover merge itself
    tracks_data "$cmerge" && refuse "$cmerge tracks data/: that is not the cutover merge (run $me --rollback --cutover-merge <sha> with the merge sha step 5 printed)"
    git cat-file -e "$cmerge:.github/CODEOWNERS" 2>/dev/null && refuse "$cmerge holds .github/CODEOWNERS: that is not the cutover merge (run $me --rollback --cutover-merge <sha> with the merge sha step 5 printed)"
    before=$(git rev-parse --verify -q "$cmerge^1") || refuse "could not read $cmerge's parent"
    restore_ok "$before" || refuse "the commit before the cutover merge $cmerge does not give R2 what it needs: $why (F4; is $cmerge the cutover merge?)"
    d=$(fetch_rd) || refuse "could not read records-data"
    [ -n "$d" ] || refuse "records-data does not exist"
    # S1-3 data-off-main/rollback-unverified-data: the data/ R restores must pass the gate's I-prov check (or be the
    # pinned seed): records-data's head, or --data-from, an ancestor of it on records-data
    seedpin=$(pinned_seed_digest "$cmerge") || seedpin=""
    if [ -n "$datafrom" ]; then
      [[ "$datafrom" =~ ^[0-9a-f]{40}$ ]] || refuse "--data-from needs a 40-hex sha on records-data"
      git merge-base --is-ancestor "$datafrom" "$d" 2>/dev/null || refuse "--data-from $datafrom is not on records-data (not an ancestor of its head $d)"
      src=$datafrom
    else
      src=$d
    fi
    tracks_data "$src" || refuse "records-data $src holds no data/"
    listing_of "$src" > "$work/src-listing" || refuse "could not read records-data $src's listing"
    if ! src_ok=$(data_verified "$work/src-listing" "$seedpin"); then
      [ -n "$datafrom" ] && refuse "--data-from $datafrom is neither attested by daily-update.yml on main nor the pinned seed (S1-3)"
      refuse "records-data's head $d is neither attested by daily-update.yml on main nor the pinned seed (S1-3): run $me --rollback --cutover-merge $cmerge --data-from <sha>, an attested commit on records-data (for example the last head --check-attested accepted)"
    fi
    echo "The cutover merge $cmerge is on main; its parent $before tracks data/, holds .github/CODEOWNERS and one empty MAIN_PR_BASELINE."
    echo "R's data/ comes from records-data $src: $src_ok."
  else
    path=early
    [ -z "$cmerge" ] || echo "--cutover-merge $cmerge is not on main $m: taking the path for a cutover that is not merged."
    restore_ok "$m" || refuse "main $m does not give R2 what it needs: $why. If the cutover merge is on main, run $me --rollback --cutover-merge <sha> (the merge sha step 5 printed)"
    echo "main $m tracks data/, holds .github/CODEOWNERS and one empty MAIN_PR_BASELINE: the cutover merge is not on main."
  fi
  echo "MORNING_NOTE_SEND and MAIN_PR_BASELINE are unset."
  step=2
  wf_set disable disabled_manually || fail "could not disable daily-update"
  echo "Rollback step 2: daily-update disabled (reads back disabled_manually)."
  if [ "$path" = early ]; then
    step=3
    now=$(fetch_main) || fail "could not fetch main"
    [ "$now" = "$m" ] || fail "main moved to $now since step 1 (was $m): run the rollback again"
    put_r1p || fail "could not put R1' back"
    r2_on || fail "could not turn R2 on"
    wf_set enable active || fail "could not re-enable daily-update (R1' and R2 are back)"
    echo "ROLLBACK DONE $(utc): R1' back, R2 on, daily-update on. records-data is kept."
    exit 0
  fi
  if [ "$path" = open ]; then
    step=3
    # main's tree, with data/ from records-data (anything main still tracks under data/ is replaced), the workflow and
    # CODEOWNERS from before the cutover, data/ un-ignored
    rm -f "$work/index"; export GIT_INDEX_FILE="$work/index"
    git read-tree "$m" && git ls-files -z -- data | git update-index -z --force-remove --stdin \
      && git read-tree --prefix=data/ "$src:data" || { unset GIT_INDEX_FILE; fail "could not build the restore tree"; }
    for f in ".github/workflows/$wfname" .github/CODEOWNERS; do
      b=$(git rev-parse --verify -q "$before:$f") && git update-index --add --cacheinfo "100644,$b,$f" \
        || { unset GIT_INDEX_FILE; fail "could not restore $f"; }
    done
    b=$(gitignore_edit "$m") || { unset GIT_INDEX_FILE; fail "could not edit .gitignore"; }
    if [ -n "$b" ]; then
      git update-index --cacheinfo "100644,$b,.gitignore" || { unset GIT_INDEX_FILE; fail "could not edit .gitignore"; }
    fi
    t=$(git write-tree); rc=$?; unset GIT_INDEX_FILE
    [ "$rc" = 0 ] || fail "could not write the restore tree"
    c=$(git commit-tree "$t" -p "$m" -m "Roll back ADR 0011's cutover: data/ on main from records-data $src

data/ from records-data $src ($src_ok); .github/workflows/$wfname and .github/CODEOWNERS as before the cutover merge $cmerge;
data/ out of .gitignore. Every config/ input and its readers stay as the cutover PR left them.") || fail "could not commit the restore (git user.name and user.email set?)"
    restore_ok "$c" || fail "the restore commit $c does not give R2 what it needs: $why"
    br="rollback/data-on-main-$(date -u +%Y%m%d-%H%M%S)"
    git push --quiet origin "$c:refs/heads/$br" || fail "could not push $br (a workflow-file push needs: gh auth refresh -s workflow)"
    echo "Rollback step 3: pushed branch $br at $c (data/ from records-data $src)."
    n=$(gh api -X POST "repos/$repo/pulls" -f base=main -f head="$br" -f title="Roll back the data cutover: data/ on main from records-data" \
        -f body="Restores data/ on main from records-data $src ($src_ok), and .github/workflows/$wfname and .github/CODEOWNERS as before the cutover merge $cmerge (ADR 0011 rollback). config/ inputs stay. Opened by scripts/cutover-data-off-main.sh --rollback." \
        --jq '.number') || fail "could not open the pull request for $br"
    echo "ROLLBACK PR #$n opened for $br at $c. daily-update stays off; R2 stays off; the site stays as last deployed."
    echo "Next, once PR #$n is reviewed at $c: $me --rollback --merge $n --sha $c --cutover-merge $cmerge --report <review>"
    exit 0
  fi
  step=3
  out=$(run_merge_reviewed "$rpr" "$sha" "${reports[@]}" 2>&1); mrc=$?
  printf '%s\n' "$out"
  ms=$(merged_line_ok "$out") && [ "$mrc" = 0 ] || fail "merge-reviewed did not end with a bypass rule suite for PR #$rpr"
  m=$(fetch_main) || fail "could not fetch main after the merge"
  [ "$m" = "$ms" ] && tracks_data "$m" || fail "main is at $m (merge $ms) and must track data/ after the restore"
  echo "Rollback step 3: PR #$rpr merged as $ms; main tracks data/ again."
  step=4
  # ADR 0011 Amendment (c) item 7 and main-protect/rollback-r2-unchecked-codeowners: before R2 goes on, main must
  # hold R's workflow and CODEOWNERS byte for byte, with one empty MAIN_PR_BASELINE, and R's verified data/ tree
  # (S1-3). Else R2 stays off.
  for f in ".github/workflows/$wfname" .github/CODEOWNERS data; do
    a=$(git rev-parse --verify -q "$m:$f") || a=""
    b=$(git rev-parse --verify -q "$sha:$f") || b=""
    [ -n "$a" ] && [ "$a" = "$b" ] || fail "main $m does not hold the restore PR's $f (blob '${a:-none}', R has '${b:-none}'): R2 stays off"
  done
  restore_ok "$m" || fail "main $m does not give R2 what it needs: $why. R2 stays off"
  echo "main $m holds R's workflow, .github/CODEOWNERS and data/ byte for byte, with one empty MAIN_PR_BASELINE."
  put_r1p || fail "could not put R1' back (the restore PR is merged)"
  r2_on || fail "could not turn R2 on (R1' is back)"
  wf_set enable active || fail "could not re-enable daily-update (R1' and R2 are back)"
  echo "ROLLBACK DONE $(utc): data/ on main, R1' back, R2 on, daily-update on. records-data is kept."
  exit 0
fi

# ---------------------------------------------------------------------------------------------- the cutover
[[ "$pr" =~ ^[0-9]+$ ]] && [[ "$sha" =~ ^[0-9a-f]{40}$ ]] && [ "${#reports[@]}" -ge 1 ] || { echo "$usage"; exit 1; }
need_gh
need_python
step=1
echo "Step 1 ($(utc)): refusals and the planned seed (read-only)."
case "$apps" in
  claude|none) ;;
  *) refuse "--apps must be claude or none: first open https://github.com/settings/installations, click Configure on each App, and note each one that reaches clarksville-records with any Read and write permission; claude only if none of its Administration, Variables, Secrets and Environments permissions is Read and write (ADR 0011 Amendment (b), S1-2; protect-main needs the answer in step 4)" ;;
esac
echo "Installed Apps with write on this repository, by Brian's hand check at https://github.com/settings/installations: $apps."
hm=$(date -u +%H%M)
[[ "$hm" =~ ^[0-9]{4}$ ]] || refuse "could not read the UTC time"
if [ $((10#$hm)) -ge 500 ] && [ $((10#$hm)) -le 1030 ]; then
  refuse "it is ${hm:0:2}:${hm:2:2} UTC, inside the daily run's window (05:00-10:30, so steps 7 and 8 end before the 09:07 run); run it later"
fi
busy=$(runs_busy) || refuse "could not read the daily-update runs"
[ "$busy" = 0 ] || refuse "a daily-update run is queued or in progress; run it after that run completes"
var_set MORNING_NOTE_SEND && refuse "MORNING_NOTE_SEND is set, or the variables could not be read (counts as set): Brian deletes it first (settings drift)"
[ -f "$r1p" ] || refuse "scripts/main-ruleset-r1p.json is missing (the rollback needs it)"
prline=$(gh api "repos/$repo/pulls/$pr" --jq '[(.state|tostring), (.base.ref|tostring), (.user.login|tostring), (.head.repo.full_name|tostring), (.head.sha|tostring), (.draft|tostring)] | @tsv') \
  || refuse "could not read pull request #$pr"
IFS=$'\t' read -r p_state p_base p_user p_repo p_head p_draft <<< "$prline" || true
[ "${p_state:-}" = open ] && [ "${p_base:-}" = main ] || refuse "pull request #$pr is not open into main"
[ "${p_user:-}" = "$owner" ] || refuse "pull request #$pr is authored by '${p_user:-}', not $owner"
[ "${p_repo:-}" = "$repo" ] || refuse "pull request #$pr's branch is in '${p_repo:-}', not $repo"
[ "${p_draft:-}" = false ] || refuse "pull request #$pr is a draft"
[ "${p_head:-}" = "$sha" ] || refuse "pull request #$pr's head is ${p_head:-unknown}, not the reviewed $sha"
git fetch --quiet --no-tags origin "+refs/pull/$pr/head:refs/cutover/pr" || refuse "could not fetch pull request #$pr's head"
[ "$(git rev-parse --verify -q "refs/cutover/pr^{commit}")" = "$sha" ] || refuse "origin's pull/$pr/head is not $sha"
[ "$(git rev-parse HEAD)" = "$sha" ] || refuse "this checkout is not at $sha: git checkout --detach $sha, then run this again"
[ -z "$(git status --porcelain --untracked-files=no)" ] || refuse "this checkout has local changes: the checks must run the reviewed code"
git var GIT_COMMITTER_IDENT >/dev/null 2>&1 || refuse "git has no user.name/user.email here (the seed commit needs them)"
pinned=$(pinned_seed_digest "$sha") || refuse "the cutover PR's $wfname pins no single 64-hex RECORDS_DATA_SEED_DIGEST"
base=$(pinned_baseline "$sha") || refuse "the cutover PR's $wfname pins no single 40-hex MAIN_PR_BASELINE (ADR 0011 Amendment (c): set it to the BASELINE that --plan prints)"
m0=$(fetch_main) || refuse "could not fetch main from origin"
[ "$m0" = "$base" ] || refuse "main is at $m0, but the cutover PR pins MAIN_PR_BASELINE $base (main moved: re-run --plan after it, update both pins and the window listing, and review again)"
git merge-base --is-ancestor "$m0" "$sha" || refuse "the cutover PR at $sha does not contain main $m0 (update its branch from main, re-run --plan, review again)"
tracks_data "$m0" || refuse "main $m0 tracks no data/: the cutover PR looks merged already"
restore_ok "$m0" || refuse "main $m0 is not a commit the early rollback can put R2 on over: $why"
tracks_data "$sha" && refuse "the cutover PR at $sha still tracks data/ (run --prepare on its branch)"
git check-ignore -q data/ || refuse "the cutover PR at $sha does not gitignore data/ (run --prepare on its branch)"
window_check "$WINDOW_START" "$m0" || refuse "the window check stopped: $why"
build_seed "$m0" "$sha" || refuse "$why"
check_seed || refuse "$why"
[ "$seed_digest" = "$pinned" ] || refuse "the seed from main $m0 has listing sha256 $seed_digest, but the PR pins $pinned (main changed since: re-run --plan and update the PR)"
rd=$(fetch_rd) || refuse "could not read records-data"
if [ -n "$rd" ]; then
  [ "$(parents "$rd")" = 0 ] && [ "$(listing_of "$rd" | sha256)" = "$pinned" ] \
    || refuse "records-data already exists at $rd and is not this seed"
  echo "records-data already is this seed ($rd): step 3 keeps it."
fi
echo "Step 1 OK: PR #$pr at $sha, main $m0 = the PR's MAIN_PR_BASELINE, window checked, seed $n_seed files ($n_left moved inputs left out), listing sha256 $seed_digest = the PR's pin."

step=2
wf_set disable disabled_manually || fail "could not disable daily-update"
busy=$(runs_busy) || fail "could not read the daily-update runs (daily-update is disabled)"
[ "$busy" = 0 ] || fail "a daily-update run started before the disable; wait for it, then undo and start again"
echo "Step 2 OK: daily-update disabled (reads back disabled_manually); no run active."

step=3
m=$(fetch_main) || fail "could not fetch main"
[ "$m" = "$base" ] || fail "main moved to $m since step 1, off the PR's MAIN_PR_BASELINE $base: undo, re-run --plan after it, update both pins, review again"
[ "$seed_digest" = "$pinned" ] || fail "the seed from main $m has listing sha256 $seed_digest, but the PR pins $pinned"
if [ -n "$rd" ]; then
  seed=$rd
else
  seed=$(git commit-tree "$seed_tree" -m "records-data seed: data/ of main $m minus the moved inputs (ADR 0011)") || fail "could not commit the seed"
  git push --quiet origin "$seed:refs/heads/records-data" || fail "could not push the seed to records-data"
fi
got=$(fetch_rd) || fail "could not read records-data back"
[ "$got" = "$seed" ] && [ "$(parents "$got")" = 0 ] && [ "$(listing_of "$got" | sha256)" = "$pinned" ] \
  || fail "records-data reads $got, not the parentless seed $seed"
echo "Step 3 OK: records-data = seed $seed (parentless, $n_seed files, listing sha256 $pinned), from main $m."

step=4
echo "Step 4: scripts/protect-main.sh --pre-cutover --apps $apps (R1'', R-D, R-T, R2 off)."
out=$(run_protect_main "$apps" 2>&1); prc=$?
printf '%s\n' "$out"
last=$(printf '%s\n' "$out" | grep . | tail -n 1)
[ "$prc" = 0 ] && [ "${last#OK: main is protected}" != "$last" ] || fail "protect-main did not print OK"
echo "Step 4 OK: protect-main printed OK."

step=5
now=$(fetch_main) || fail "could not fetch main"
[ "$now" = "$base" ] || fail "main moved to $now since the seed was taken from $base, off the PR's MAIN_PR_BASELINE: nothing is merged"
# S1-5 data-off-main/seed-window: records-data had no ruleset between step 3's push and step 4's R-D, so read it
# again right before the merge
got=$(fetch_rd) || fail "could not read records-data before the merge"
[ "$got" = "$seed" ] && [ "$(parents "$got")" = 0 ] \
  || fail "records-data reads ${got:-nothing}, no longer the seed $seed pushed in step 3 (S1-5): nothing is merged"
echo "records-data is still the seed $seed."
echo "Step 5: scripts/merge-reviewed.sh $pr $sha (main $now = the pinned baseline)."
merge_from=$now
out=$(run_merge_reviewed "$pr" "$sha" "${reports[@]}" 2>&1); mrc=$?
printf '%s\n' "$out"
ms=$(merged_line_ok "$out") && [ "$mrc" = 0 ] || fail "merge-reviewed did not end with a bypass rule suite"
undo="$me --rollback --cutover-merge $ms"
m=$(fetch_main) || fail "could not fetch main after the merge"
[ "$m" = "$ms" ] || fail "main is at $m, not the merge $ms"
p1=$(git rev-parse --verify -q "$ms^1") || p1=""
[ "$(parents "$ms")" = 1 ] && [ "$p1" = "$base" ] \
  || fail "the squash $ms has parent ${p1:-none}, not the pinned MAIN_PR_BASELINE $base (the gate would check more than the cutover commit)"
tracks_data "$m" && fail "main $m still tracks data/ after the merge"
echo "Step 5: scripts/protect-main.sh --check --apps $apps (main's new workflow, no writes)."
out=$(run_protect_check "$apps" 2>&1); prc=$?
printf '%s\n' "$out"
last=$(printf '%s\n' "$out" | grep . | tail -n 1)
[ "$prc" = 0 ] && [ "${last#OK: main is protected}" != "$last" ] || fail "protect-main --check did not print OK after the merge"
echo "Step 5 OK: PR #$pr merged as $ms (rule suite bypass), parent = MAIN_PR_BASELINE $base; main tracks no data/; protect-main --check printed OK."
echo "The undo from here on: $undo"

step=6
wf_set enable active || fail "could not re-enable daily-update (or: gh workflow enable $wfname -R $repo)"
echo "Step 6 OK: daily-update enabled (reads back active)."

step=7
id=$(dispatch_run false) || fail "could not dispatch daily-update collect=false, or find its run"
echo "Step 7: run $id (collect=false): https://github.com/$repo/actions/runs/$id"
c=$(wait_run "$id" 120) || fail "run $id did not complete within 120 minutes"
gate_verified "$id" "$base" || fail "run $id's gate did not verify exactly the cutover commit after MAIN_PR_BASELINE $base"
dj=$(job_conclusion "$id" "$CO_DEPLOY") || dj=""
[ "$dj" = success ] || fail "run $id ended $c; its deploy job is '${dj:-missing}', not success"
bi=""
for i in $(seq 1 20); do
  bi=$(build_info_data_sha 2>/dev/null) || bi=""
  [ "$bi" = "$seed" ] && break
  [ "$i" = 20 ] || sleep 30
done
[ "$bi" = "$seed" ] || fail "the site's build-info.json names data_sha '${bi:-unread}', not the seed $seed"
echo "Step 7 OK: run $id deployed; $site/build-info.json names the seed $seed."

step=8
id=$(dispatch_run true) || fail "could not dispatch daily-update collect=true, or find its run"
echo "Step 8: run $id (collect=true): https://github.com/$repo/actions/runs/$id"
w=$(step8_wait) || w=1   # an unreadable clock: a 1-minute wait, which then stops with the --check-attested line
echo "Step 8: waiting up to $w minutes, so the wait ends before 09:00 UTC (the 09:07 daily run)."
c=$(wait_run "$id" "$w") || fail "run $id did not complete within $w minutes, and the wait ends before 09:00 UTC so it can't meet the 09:07 daily run (later: $me --check-attested)"
echo "Run $id ended $c."
gate_verified "$id" "$base" || fail "run $id's gate did not verify exactly the cutover commit after MAIN_PR_BASELINE $base"
check_attested "$seed" || fail "$why"
dj=$(job_conclusion "$id" "$CO_DEPLOY") || dj=""
[ "$dj" = success ] || fail "run $id ended $c; its deploy job is '${dj:-missing}', not success (records-data is attested)"
echo "Step 8 OK."
echo "CUTOVER DONE $(utc): PR #$pr merged as $ms, seed $seed, records-data moved by run $id and attested."
echo "Record in docs/status.md: the merge $ms, the seed $seed, run ids, and the first attested records-data head."
exit 0
