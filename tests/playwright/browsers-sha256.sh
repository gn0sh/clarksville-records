#!/usr/bin/env bash
# Prints browsers.sha256 for a Playwright browsers folder (PLAYWRIGHT_BROWSERS_PATH), the file the daily update checks
# the installed Chromium against before anything runs it (security review bbc603a F1, ci-supply/browser-bytes-unverified).
#
# Usage: tests/playwright/browsers-sha256.sh <browsers folder> > tests/playwright/browsers.sha256
#
# Regenerate it whenever package-lock.json moves Playwright to a new browser revision, never from `playwright install`
# (security re-check a84d19d R1; docs/architecture/ci-download-verify-invariant.md). Use the daily update's own steps:
# curl the two Chrome for Testing linux64 zips for that Playwright's version (2026-11-22: 153.0.8010.12, from
# https://storage.googleapis.com/chrome-for-testing-public/<version>/linux64/) into a new, empty folder, check them
# against their source, write their sha256sum lines to tests/playwright/browser-zips.sha256 (chrome-linux64.zip, then
# chrome-headless-shell-linux64.zip), unzip -q each into <folder>/chromium-<rev> and <folder>/chromium_headless_shell-<rev>
# of an empty folder, create an empty INSTALLATION_COMPLETE in each, then run this before anything launches the browser.
# The bump is one pull request: the version in the step's URL, <rev> in its two folder names, both .sha256 files, and
# REVISIONS in tests/test_browser_install_step.py. The list covers the chromium* folders only (no ffmpeg, no .links).
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
