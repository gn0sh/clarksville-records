#!/usr/bin/env bash
# Fill data/ from origin/records-data (ADR 0011 decision 1; docs/tasks/data-off-main.md D2): the bash twin of
# scripts/fetch-data.ps1. From the cutover on, main tracks no data/ (it is gitignored); the collector's output lives
# on branch records-data, whose tree is data/ only. Run this before the tests, a site build or a collector run.
#   - Before the cutover (data/ tracked on this checkout) it is a no-op and says so.
#   - It fetches records-data into refs/remotes/origin/records-data, refuses a tree holding anything besides data/,
#     extracts it with git archive into the git folder, checks the file count, then swaps it in for data/. The data/
#     that was there is kept at <git folder>/fetch-data/previous until the next run.
#   - It never commits, pushes, checks out a branch or touches the index, and refuses when data/ is neither tracked
#     nor ignored here (it could then be committed by mistake).
# Exit 0 done or no-op, 1 refused or failed (data/ unchanged). Needs git and tar. Run: bash scripts/fetch-data.sh
set -uo pipefail
top=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "Run this inside the clarksville-records checkout. Nothing was changed."; exit 1; }
cd "$top" || exit 1
if [ -n "$(git ls-files -- data | head -n 1)" ]; then
  echo "data/ is tracked on this checkout (before the ADR 0011 cutover): nothing to fetch. Nothing was changed."
  exit 0
fi
git check-ignore -q data/ \
  || { echo "data/ is neither tracked nor ignored on this checkout, so it could be committed by mistake. Nothing was changed. Send this output to the team."; exit 1; }
git fetch --quiet --no-tags origin "+refs/heads/records-data:refs/remotes/origin/records-data" \
  || { echo "Could not fetch records-data from origin. Nothing was changed."; exit 1; }
d=$(git rev-parse --verify --quiet "refs/remotes/origin/records-data^{commit}") \
  || { echo "origin has no records-data commit. Nothing was changed."; exit 1; }
names=$(git ls-tree --name-only "$d" | paste -sd, -)
if [ "$names" != data ]; then
  echo "records-data $d holds '$names', not only data/. Nothing was changed. Send this output to the team."; exit 1
fi
# data must be a real folder, and nothing under it a symlink (120000) or a submodule (160000): a symlinked data/ or
# file would point the site build, the tests or the collector outside the checkout
top_mode=$(git ls-tree "$d" data | cut -d' ' -f1)
if [ "$top_mode" != 040000 ]; then
  echo "records-data $d has data as mode $top_mode, not a folder (040000). Nothing was changed. Send this output to the team."; exit 1
fi
links=$(git ls-tree -r "$d" -- data | awk -F'\t' '$1 ~ /^(120000|160000) / { print $2 }' | head -n 5 | paste -sd, -)
if [ -n "$links" ]; then
  echo "records-data $d holds a symlink or submodule under data/ ($links). Nothing was changed. Send this output to the team."; exit 1
fi
want=$(git ls-tree -r --name-only "$d" -- data | wc -l | tr -d ' ')
gd=$(git rev-parse --absolute-git-dir) || exit 1
work="$gd/fetch-data"
rm -rf "$work/new" "$work/data.tar"
mkdir -p "$work/new" || { echo "Could not make $work. Nothing was changed."; exit 1; }
git archive --format=tar --output="$work/data.tar" "$d" data \
  || { echo "git archive of records-data $d failed. Nothing was changed."; exit 1; }
tar -xf "$work/data.tar" -C "$work/new" || { echo "Could not unpack records-data $d. Nothing was changed."; exit 1; }
rm -f "$work/data.tar"
got=$(cd "$work/new" && find data ! -type d | wc -l | tr -d ' ')
if [ "$got" != "$want" ]; then
  echo "Unpacked $got files from records-data $d, expected $want. Nothing was changed. Send this output to the team."; exit 1
fi
if [ -e data ] || [ -L data ]; then
  rm -rf "$work/previous"
  if [ -e "$work/previous" ] || [ -L "$work/previous" ]; then
    echo "Could not remove the old $work/previous. Nothing was changed. Send this output to the team."; exit 1
  fi
  mv data "$work/previous" || { echo "Could not move the current data/ aside. Nothing was changed."; exit 1; }
  echo "The data/ that was here is now at $work/previous (replaced on the next run)."
fi
mv "$work/new/data" data || { echo "Could not move the new data/ in place: the old one is at $work/previous. Send this output to the team."; exit 1; }
echo "data/ is now records-data $d ($want files). Nothing was committed."
