#!/usr/bin/env bash
# Prints browsers.sha256 for a Playwright browsers folder (PLAYWRIGHT_BROWSERS_PATH), the file the daily update checks
# the installed Chromium against before anything runs it (security review bbc603a F1, ci-supply/browser-bytes-unverified).
#
# Usage: tests/playwright/browsers-sha256.sh <browsers folder> > tests/playwright/browsers.sha256
#
# Regenerate it whenever package-lock.json moves Playwright to a new browser revision: install that Playwright's
# chromium into an empty folder (PLAYWRIGHT_BROWSERS_PATH=<folder> PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS=1
# node_modules/.bin/playwright install chromium) from zips whose source you checked (2026-11-22: the two Chrome for
# Testing 153.0.8010.12 linux64 zips from storage.googleapis.com/chrome-for-testing-public, served to Playwright 1.63.0's
# own installer), then run this. It covers the chromium* folders only: ffmpeg is deleted unrun by the workflow.
set -euo pipefail
dir=${1:?usage: browsers-sha256.sh <browsers folder>}
cd "$dir"
shopt -s nullglob
set -- chromium-[0-9]* chromium_headless_shell-[0-9]*
[ "$#" = 2 ] || { echo "expected exactly one chromium-<rev> and one chromium_headless_shell-<rev> folder in $dir" >&2; exit 1; }
if [ -n "$(find "$@" ! -type d ! -type f -print -quit)" ]; then echo "non-regular files (symlinks?) under $dir" >&2; exit 1; fi
if find "$@" -type f | LC_ALL=C grep -qv '^[A-Za-z0-9._/@+-]*$'; then echo "a file name outside [A-Za-z0-9._/@+-]" >&2; exit 1; fi
find "$@" -type f -name DEPENDENCIES_VALIDATED | grep -q . && { echo "a browser in $dir has been launched (DEPENDENCIES_VALIDATED): use a fresh install" >&2; exit 1; }
find "$@" -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum
