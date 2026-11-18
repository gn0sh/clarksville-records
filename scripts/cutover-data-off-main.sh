#!/usr/bin/env bash
# Cut Daylight's collector data over from main to branch records-data (ADR 0011; docs/tasks/data-off-main.md D3, the
# Operator's order; consumer rows D, CFG, S4; PR #54 security review: drift, F2, F4, F5, F7). The bash twin of
# scripts/cutover-data-off-main.ps1, which is the one Brian runs. Brian's PC only: every ruleset, settings and
# workflow write is his (U3-0 = no), so it refuses to run in a cloud session or CI (except --plan, which writes
# nothing on GitHub).
#
# Run it from a checkout of the cutover PR at its reviewed head (so the checks below run reviewed code):
#   git fetch origin pull/<P>/head && git checkout --detach <reviewed head>
#   bash scripts/cutover-data-off-main.sh --pr <P> --sha <reviewed head> --report <review> [--report <review> ...]
#   bash scripts/cutover-data-off-main.sh --plan [--ref <git rev>]   read-only: the seed step 3 would push from
#        origin/main's data/, its checks and "SEED DIGEST <sha256>" for the cutover PR's RECORDS_DATA_SEED_DIGEST
#        (--ref: the cutover head whose config/ holds the moved inputs; default HEAD). No gh call, no push.
#   bash scripts/cutover-data-off-main.sh --rollback [--cutover-merge <sha>]       undo (below)
#   bash scripts/cutover-data-off-main.sh --rollback --merge <R> --sha <reviewed head> --report <review> [...]
#   bash scripts/cutover-data-off-main.sh --check-attested   read-only: step 8's check again, for a later run
#
# Steps (it stops at the first failure and prints the exact --rollback command):
#   1. Refuses, changing nothing, from 08:00 to 10:30 UTC, while a daily-update run is not completed, or while the
#      repository variable MORNING_NOTE_SEND exists (a refused or failed read of actions/variables counts as set).
#      Also unless PR <P> is open into main, authored by gn0sh, from this repository, at <sha>, this checkout is at
#      <sha> with no local change, main still tracks data/, and the seed (step 3) already passes its checks and
#      equals the PR's pin. records-data must be absent, or exactly that seed (a re-run).
#   2. Disables daily-update and reads it back; stops if a run started meanwhile.
#   3. Seeds records-data: main's data/ minus every moved input (the curated files, data/localities/*/transcripts/
#      and data/maps/, I-in) whose config/ copy on the cutover head is the same blob, as one parentless commit. A
#      moved input the PR does not carry stays in, and is refused. Stops unless its listing (git ls-tree -r -z
#      <seed> -- data) holds no transcripts/ folder, nothing under data/maps/ and no curated name, passes
#      python -m collector.data_shape, its rpc.json passes python -m tools.scrub_rpc_phones --check, and its
#      sha256 equals the PR's RECORDS_DATA_SEED_DIGEST. Pushes it (never forced) and reads it back.
#   4. Runs scripts/protect-main.sh (R1'', R-D, R-T, R2 off); its last line must start "OK: main is protected".
#   5. Merges the cutover PR with scripts/merge-reviewed.sh (main must not have moved since the seed); its last line
#      must be "Rule suite <id> for <merge sha>: bypass", and main must then track no data/.
#   6. Re-enables daily-update and reads it back.
#   7. Dispatches collect=false; the run's deploy job must succeed and the site's build-info.json must name the
#      seed as data_sha.
#   8. Dispatches collect=true; records-data must then have moved past the seed, and its listing must verify with
#      gh attestation verify (the gate's flags).
# --rollback refuses while MORNING_NOTE_SEND or MAIN_PR_BASELINE is set (finding F4: R2 on reopens the bot path; a
# refused or failed read counts as set; MAIN_PR_BASELINE as a variable or a non-empty value in main's workflow),
# then disables daily-update. If main still tracks data/ (the cutover PR was not merged): R1'
# (scripts/main-ruleset-r1p.json) back, R2 on, workflow on. Otherwise (needs --cutover-merge, printed by step 5) it
# opens PR R from a new branch: data/ from records-data's head, the workflow and .github/CODEOWNERS as they were
# before the cutover merge, data/ out of .gitignore; every config/ input and reader stays as the cutover PR left
# them. Once R is reviewed, --rollback --merge merges it with merge-reviewed (a bypass, under R1''), then puts R1'
# back, turns R2 on and re-enables the workflow, in that order (R2 goes on only once CODEOWNERS is back).
# records-data is kept. Exit: 0 done, 1 refused (nothing changed), 2 stopped after a change (see the undo line).
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
export CO_BASELINE_VAR=MAIN_PR_BASELINE
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

usage="Usage: $me --pr <P> --sha <reviewed head> --report <review> [...] | --plan [--ref <rev>] | --rollback [--cutover-merge <sha>] | --rollback --merge <R> --sha <sha> --report <review> [...] | --check-attested"
mode=cutover; pr=""; sha=""; reports=(); ref=HEAD; cmerge=""; rpr=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --pr) pr="${2:-}"; shift 2 || { echo "$usage"; exit 1; } ;;
    --sha) sha="${2:-}"; shift 2 || { echo "$usage"; exit 1; } ;;
    --report) [ -n "${2:-}" ] || { echo "$usage"; exit 1; }; reports+=("$2"); shift 2 ;;
    --plan) mode=plan; shift ;;
    --ref) ref="${2:-}"; shift 2 || { echo "$usage"; exit 1; } ;;
    --rollback) mode=rollback; shift ;;
    --cutover-merge) cmerge="${2:-}"; shift 2 || { echo "$usage"; exit 1; } ;;
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
fail() {
  echo "STOPPED at step $step ($(utc)): $1"
  echo "Undo with: $undo"
  exit 2
}

if [ "$mode" != plan ]; then
  for v in CLAUDE_CODE_REMOTE GITHUB_ACTIONS CI; do
    [ -z "${!v:-}" ] || refuse "$v is set: the cutover runs only from Brian's PC (ruleset, settings and workflow writes are his)"
  done
fi
for t in git jq; do command -v "$t" >/dev/null 2>&1 || refuse "$t not found: install it, then run this again"; done
top=$(git rev-parse --show-toplevel 2>/dev/null) || refuse "run this inside the clarksville-records checkout"
cd "$top" || refuse "could not enter $top"
work=$(mktemp -d) || refuse "could not make a temporary folder"
trap 'rm -rf "$work"' EXIT
if command -v sha256sum >/dev/null 2>&1; then sha256() { sha256sum | cut -d' ' -f1; }
else sha256() { shasum -a 256 | cut -d' ' -f1; }; fi
py=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then py=$c; break; fi
done

# ---------------------------------------------------------------------------------------------- named calls
# Each call to another script or another branch's contract is one function, so a change there is one edit here.
run_protect_main() { bash "$here/protect-main.sh"; }                          # D1: last line "OK: main is protected..."
run_merge_reviewed() { bash "$here/merge-reviewed.sh" "$@"; }                 # D1: last line "Rule suite <id> for <sha>: bypass"
run_data_shape() { "$py" -B -m collector.data_shape "$1"; }                   # B1/B1b: exit 0 = the listing passes
run_scrub_check() { "$py" -B -m tools.scrub_rpc_phones --check --path "$1"; } # B1b: read-only, exit 1 on a phone
pinned_seed_digest() {   # $1 rev: B2's gate env line RECORDS_DATA_SEED_DIGEST: "<64 hex>", exactly one, in its workflow
  local wf n v
  wf=$(git show "$1:.github/workflows/$wfname" 2>/dev/null) || return 1
  n=$(printf '%s\n' "$wf" | grep -c 'RECORDS_DATA_SEED_DIGEST:' || true)
  v=$(printf '%s\n' "$wf" | sed -nE 's/^[[:space:]]*RECORDS_DATA_SEED_DIGEST:[[:space:]]*"([0-9a-f]{64})".*$/\1/p')
  [ "$n" = 1 ] && [[ "$v" =~ ^[0-9a-f]{64}$ ]] && echo "$v"
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
parents() { git cat-file commit "$1" | sed '/^$/q' | grep -c '^parent ' || true; }
listing_of() { git ls-tree -r -z "$1" -- data; }

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
  local s
  gh api -X PUT "repos/$repo/actions/workflows/$wfname/$1" --silent || return 1
  s=$(wf_state) || return 1
  [ "$s" = "$2" ] || { echo "daily-update reads '$s', not $2."; return 1; }
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
job_conclusion() { CO_JOB=$2 gh api "repos/$repo/actions/runs/$1/jobs?per_page=100" --jq '.jobs[] | select(.name == $ENV.CO_JOB) | .conclusion'; }
put_r1p() {   # PUT scripts/main-ruleset-r1p.json (whitelisted) into main's ruleset, read it back
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

# ---------------------------------------------------------------------------------------------- --plan
if [ "$mode" = plan ]; then
  need_python
  h=$(git rev-parse --verify -q "$ref^{commit}") || refuse "no commit '$ref' here"
  m=$(fetch_main) || refuse "could not fetch main from origin"
  tracks_data "$m" || refuse "main $m tracks no data/: nothing to seed"
  echo "PLAN (nothing is pushed): the seed from main $m's data/, against the cutover head $h's config/."
  build_seed "$m" "$h" || refuse "$why"
  echo "Seed: $n_seed files ($n_left moved inputs left out)."
  check_seed || refuse "$why"
  echo "SEED DIGEST $seed_digest"
  if p=$(pinned_seed_digest "$h"); then
    [ "$p" = "$seed_digest" ] && echo "The cutover head pins this digest." \
      || { echo "The cutover head pins $p, not this digest: update RECORDS_DATA_SEED_DIGEST."; exit 1; }
  else
    echo "The cutover head pins no RECORDS_DATA_SEED_DIGEST yet: set it to the digest above."
  fi
  exit 0
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
  [ -f "$r1p" ] || refuse "scripts/main-ruleset-r1p.json is missing"
  step=1
  echo "Rollback step 1 ($(utc)): refusals."
  var_set MORNING_NOTE_SEND && refuse "MORNING_NOTE_SEND is set, or the variables could not be read (counts as set): Brian deletes it first (Settings > Secrets and variables > Actions > Variables), because R2 on reopens the bot path (F4)"
  var_set MAIN_PR_BASELINE && refuse "the variable MAIN_PR_BASELINE is set, or the variables could not be read (counts as set): Brian deletes it first (F4)"
  m=$(fetch_main) || refuse "could not fetch main from origin"
  if ! git show "$m:.github/workflows/$wfname" > "$work/wf" 2>/dev/null; then refuse "could not read main's workflow (MAIN_PR_BASELINE counts as set)"; fi
  [ "$(grep -c 'MAIN_PR_BASELINE:' "$work/wf" || true)" = 1 ] \
    && [ "$(grep -cE '^[[:space:]]*MAIN_PR_BASELINE:[[:space:]]*""([[:space:]]|$)' "$work/wf" || true)" = 1 ] \
    || refuse "main's workflow sets MAIN_PR_BASELINE, or it is not exactly one empty value (counts as set): a reviewed PR empties it first (F4)"
  echo "MORNING_NOTE_SEND and MAIN_PR_BASELINE are unset."
  step=2
  wf_set disable disabled_manually || fail "could not disable daily-update"
  echo "Rollback step 2: daily-update disabled (reads back disabled_manually)."
  if tracks_data "$m"; then
    step=3
    echo "main $m still tracks data/: the cutover PR was not merged, so nothing on main to restore."
    put_r1p || fail "could not put R1' back"
    r2_on || fail "could not turn R2 on"
    wf_set enable active || fail "could not re-enable daily-update (R1' and R2 are back)"
    echo "ROLLBACK DONE $(utc): R1' back, R2 on, daily-update on. records-data is kept."
    exit 0
  fi
  if [ -z "$rpr" ]; then
    step=3
    [[ "$cmerge" =~ ^[0-9a-f]{40}$ ]] || fail "main tracks no data/: run $me --rollback --cutover-merge <sha> with the merge sha step 5 printed"
    git merge-base --is-ancestor "$cmerge" "$m" || fail "$cmerge is not on main"
    before=$(git rev-parse --verify -q "$cmerge^1") || fail "could not read $cmerge's parent"
    tracks_data "$before" || fail "$cmerge's parent tracks no data/: that is not the cutover merge"
    d=$(fetch_rd) || fail "could not read records-data"
    [ -n "$d" ] || fail "records-data does not exist"
    tracks_data "$d" || fail "records-data $d holds no data/"
    # main's tree, with data/ from records-data, the workflow and CODEOWNERS from before the cutover, data/ un-ignored
    rm -f "$work/index"; export GIT_INDEX_FILE="$work/index"
    git read-tree "$m" && git read-tree --prefix=data/ "$d:data" || { unset GIT_INDEX_FILE; fail "could not build the restore tree"; }
    for f in ".github/workflows/$wfname" .github/CODEOWNERS; do
      if b=$(git rev-parse --verify -q "$before:$f"); then git update-index --add --cacheinfo "100644,$b,$f"
      else git update-index --force-remove -- "$f"; fi || { unset GIT_INDEX_FILE; fail "could not restore $f"; }
    done
    if gi=$(git rev-parse --verify -q "$m:.gitignore"); then
      b=$(git cat-file blob "$gi" | grep -vE '^/?data/?(\*\*?)?[[:space:]]*$' | git hash-object -w --stdin) \
        && git update-index --cacheinfo "100644,$b,.gitignore" || { unset GIT_INDEX_FILE; fail "could not edit .gitignore"; }
    fi
    t=$(git write-tree); rc=$?; unset GIT_INDEX_FILE
    [ "$rc" = 0 ] || fail "could not write the restore tree"
    c=$(git commit-tree "$t" -p "$m" -m "Roll back ADR 0011's cutover: data/ on main from records-data $d

data/ from records-data $d; .github/workflows/$wfname and .github/CODEOWNERS as before the cutover merge $cmerge;
data/ out of .gitignore. Every config/ input and its readers stay as the cutover PR left them.") || fail "could not commit the restore (git user.name and user.email set?)"
    br="rollback/data-on-main-$(date -u +%Y%m%d-%H%M%S)"
    git push --quiet origin "$c:refs/heads/$br" || fail "could not push $br (a workflow-file push needs: gh auth refresh -s workflow)"
    echo "Rollback step 3: pushed branch $br at $c (data/ from records-data $d)."
    n=$(gh api -X POST "repos/$repo/pulls" -f base=main -f head="$br" -f title="Roll back the data cutover: data/ on main from records-data" \
        -f body="Restores data/ on main from records-data $d, and .github/workflows/$wfname and .github/CODEOWNERS as before the cutover merge $cmerge (ADR 0011 rollback). config/ inputs stay. Opened by scripts/cutover-data-off-main.sh --rollback." \
        --jq '.number') || fail "could not open the pull request for $br"
    echo "ROLLBACK PR #$n opened for $br at $c. daily-update stays off; the site stays as last deployed."
    echo "Next, once PR #$n is reviewed at $c: $me --rollback --merge $n --sha $c --report <review>"
    exit 0
  fi
  step=3
  [[ "$rpr" =~ ^[0-9]+$ ]] && [[ "$sha" =~ ^[0-9a-f]{40}$ ]] && [ "${#reports[@]}" -ge 1 ] || fail "--merge needs <R> --sha <reviewed head> --report <review>"
  out=$(run_merge_reviewed "$rpr" "$sha" "${reports[@]}" 2>&1); mrc=$?
  printf '%s\n' "$out"
  ms=$(merged_line_ok "$out") && [ "$mrc" = 0 ] || fail "merge-reviewed did not end with a bypass rule suite for PR #$rpr"
  m=$(fetch_main) || fail "could not fetch main after the merge"
  [ "$m" = "$ms" ] && tracks_data "$m" || fail "main is at $m (merge $ms) and must track data/ after the restore"
  echo "Rollback step 3: PR #$rpr merged as $ms; main tracks data/ again."
  step=4
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
hm=$(date -u +%H%M)
[[ "$hm" =~ ^[0-9]{4}$ ]] || refuse "could not read the UTC time"
if [ $((10#$hm)) -ge 800 ] && [ $((10#$hm)) -le 1030 ]; then
  refuse "it is ${hm:0:2}:${hm:2:2} UTC, inside the daily run's window (08:00-10:30); run it later"
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
m0=$(fetch_main) || refuse "could not fetch main from origin"
tracks_data "$m0" || refuse "main $m0 tracks no data/: the cutover PR looks merged already"
tracks_data "$sha" && refuse "the cutover PR at $sha still tracks data/"
build_seed "$m0" "$sha" || refuse "$why"
check_seed || refuse "$why"
[ "$seed_digest" = "$pinned" ] || refuse "the seed from main $m0 has listing sha256 $seed_digest, but the PR pins $pinned (main changed since: re-run --plan and update the PR)"
rd=$(fetch_rd) || refuse "could not read records-data"
if [ -n "$rd" ]; then
  [ "$(parents "$rd")" = 0 ] && [ "$(listing_of "$rd" | sha256)" = "$pinned" ] \
    || refuse "records-data already exists at $rd and is not this seed"
  echo "records-data already is this seed ($rd): step 3 keeps it."
fi
echo "Step 1 OK: PR #$pr at $sha, main $m0, seed $n_seed files ($n_left moved inputs left out), listing sha256 $seed_digest = the PR's pin."

step=2
wf_set disable disabled_manually || fail "could not disable daily-update"
busy=$(runs_busy) || fail "could not read the daily-update runs (daily-update is disabled)"
[ "$busy" = 0 ] || fail "a daily-update run started before the disable; wait for it, then undo and start again"
echo "Step 2 OK: daily-update disabled (reads back disabled_manually); no run active."

step=3
m=$(fetch_main) || fail "could not fetch main"
if [ "$m" != "$m0" ]; then
  echo "main moved to $m since step 1: building the seed again."
  build_seed "$m" "$sha" || fail "$why"
  check_seed || fail "$why"
fi
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
echo "Step 4: scripts/protect-main.sh (R1'', R-D, R-T, R2 off)."
out=$(run_protect_main 2>&1); prc=$?
printf '%s\n' "$out"
last=$(printf '%s\n' "$out" | grep . | tail -n 1)
[ "$prc" = 0 ] && [ "${last#OK: main is protected}" != "$last" ] || fail "protect-main did not print OK"
echo "Step 4 OK: protect-main printed OK."

step=5
now=$(fetch_main) || fail "could not fetch main"
if [ "$now" != "$m" ]; then
  build_seed "$now" "$sha" > /dev/null && [ "$seed_digest" = "$pinned" ] \
    || fail "main moved to $now since the seed was taken from $m, and its data/ no longer gives the seed"
fi
echo "Step 5: scripts/merge-reviewed.sh $pr $sha (main $now)."
out=$(run_merge_reviewed "$pr" "$sha" "${reports[@]}" 2>&1); mrc=$?
printf '%s\n' "$out"
ms=$(merged_line_ok "$out") && [ "$mrc" = 0 ] || fail "merge-reviewed did not end with a bypass rule suite"
undo="$me --rollback --cutover-merge $ms"
m=$(fetch_main) || fail "could not fetch main after the merge"
[ "$m" = "$ms" ] || fail "main is at $m, not the merge $ms"
tracks_data "$m" && fail "main $m still tracks data/ after the merge"
echo "Step 5 OK: PR #$pr merged as $ms (rule suite bypass); main tracks no data/."
echo "The undo from here on: $undo"

step=6
wf_set enable active || fail "could not re-enable daily-update (or: gh workflow enable $wfname -R $repo)"
echo "Step 6 OK: daily-update enabled (reads back active)."

step=7
id=$(dispatch_run false) || fail "could not dispatch daily-update collect=false, or find its run"
echo "Step 7: run $id (collect=false): https://github.com/$repo/actions/runs/$id"
c=$(wait_run "$id" 120) || fail "run $id did not complete within 120 minutes"
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
c=$(wait_run "$id" 360) || fail "run $id did not complete within 6 hours (later: $me --check-attested)"
echo "Run $id ended $c (deploy: $(job_conclusion "$id" "$CO_DEPLOY" 2>/dev/null || echo unread))."
check_attested "$seed" || fail "$why"
echo "Step 8 OK."
echo "CUTOVER DONE $(utc): PR #$pr merged as $ms, seed $seed, records-data moved by run $id and attested."
echo "Record in docs/status.md: the merge $ms, the seed $seed, run ids, and the first attested records-data head."
exit 0
