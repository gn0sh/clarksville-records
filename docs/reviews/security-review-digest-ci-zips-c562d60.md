# Security review: Digest CI, Chromium zips verified before unpack (c562d60)

Reviewer: security-engineer (opus, high), 2026-11-22. Read-only. Scope: `git diff ee3764b c562d60` (fixes R1, R2, R3 and
F-pip from `security-recheck-digest-ci-a84d19d.md`). Fresh full review because the change touches CI. Family
`ci-supply/browser-bytes-unverified` (2nd hit) checked against `docs/architecture/ci-download-verify-invariant.md`.

**Verdict: OK.** R1 fixed and reproduced; R2, R3, F-pip fixed. No critical, high or medium issues.

**Most serious problem found:** L1, curl has no size cap, so a hostile download server could fill the runner disk for one
run (fails the run; cannot run code; hash check still holds).

## Findings
| # | Sev | Key | Where | Finding / fix |
|---|---|---|---|---|
| L1 | low | `ci-supply/download-size-unbounded` | daily-update.yml:766-767 | No size cap on the CfT curls. Fix: `--max-filesize 268435456` (real zips 195.8 MB, 119.8 MB) + extend T1. Owner devops. **Taken.** |
| I1 | info | `ci-supply/check-inputs-in-workspace` | :726, :791 | Hash lists read from the checkout after untrusted PDF parsing in the same job; an attacker there already runs code. Accepted residual. |
| I2 | info | - | :787-788 | `: > INSTALLATION_COMPLETE` follows symlinks before the tree check; safe because pinned zips hold 590 files, 5 dirs, no symlinks, no `..`/absolute paths, no setuid. Re-check at each version bump. |
| I3 | info | - | runtime | Playwright writes `DEPENDENCIES_VALIDATED` after the tree check; re-running the tree check after a launch would fail. Nothing does that. |

## Checked and holding
- **Order:** shape check (:770-771) before node/npm/curl; curl only into a fresh 0700 `mktemp -d`; each try empties it;
  exactly two regular files (`find` without `-L`); `sha256sum --strict -c` then unzip; mismatch = exit 1, never retried,
  zips deleted. No `playwright install` remains; no cache path names browser or zip dirs.
- **Hash list shape:** exactly 2 lines, regex `^[0-9a-f]{64}  chrome(-headless-shell)?-linux64\.zip$`, fixed order; no
  trailing newline, CRLF, uppercase or third line all fail closed.
- **Pinned values:** both zips downloaded with the step's flags; sha256 byte-identical to `browser-zips.sha256`.
- **End to end:** step's own run block on real zips: "Chromium zips checked: 2 files match", "Chromium checked: 592 files
  match"; `browsers=ok`; `REQUIRE_BROWSER=1 pytest tests/test_national_browser.py` 12 passed.
- **unzip (Info-ZIP 6.00, `-q -n -d`, hostile zips built by reviewer):** dir-symlink then `link/file` -> checkdir error rc=2
  (hard fail, nothing outside); file-symlink then same-name file -> skipped by `-n`; `../../x` and `/abs` stripped; setuid
  dropped as root. Needs verification on the ubuntu-24.04 runner build (defence in depth only).
- **TOCTOU:** same path, 0700 dir written only by this step; only in-job code could swap (I1).
- **curl:** `--fail --location --proto '=https' --proto-redir '=https' --max-time 300 --silent --show-error -o <fixed>`;
  no `-k`, `--retry`, `-J`, `-O`. Short/failed transfer -> `missing` after 3 tries; wrong file -> hard fail.
- **R2:** 70 min (4,200 s) > worst case 3,990 s (npm 585 + deps 945 + curl 1,800 + pauses 360 + 300).
- **R3:** `if: always() && github.ref == 'refs/heads/main' && steps.browsers.outputs.browsers == 'missing'`; GH_TOKEN in
  step env only; existing `contents: read`, `issues: write`; fixed body via `--body-file`; exact title + `--app
  github-actions`; no `${{ }}` in run; `continue-on-error`, 5 min timeout.
- **F-pip:** `--only-binary :all:` at daily :470 and national :235; lock has no option lines; no `PIP_*`/pip.conf; all 15
  pinned packages fetched as hashed cp312 manylinux wheels.
- **Blob pin:** `7ce9473ded75de4dfabb7bac5c29a31655df9e9e` = git hash-object = protect-main.ps1:513 = protect-main.sh:408.
- **New surface:** no new `uses:`, `permissions:` or `secrets.`; only new `${{ }}` is `GH_TOKEN: ${{ github.token }}`.
- **Failure paths:** unzip fail, mismatch, `missing` all leave nothing unchecked; `if: always()` cache saves cover only
  `data/store` and derived readings.
- **Tests:** test_browser_install_step.py 56 passed; with test_workflow_lock.py 570 passed, 3 failed only for empty `data/`
  (sandbox setup, unrelated).

## Family ledger
- `ci-supply/browser-bytes-unverified`: closed by c562d60.
- `ci-supply/download-size-unbounded` (L1): new, low; taken by devops.
- `daily-run/install-step-hard-dependency` (R2), `ci-browser/probe-skips-silently` (R3),
  `ci-supply/sdist-build-deps-unhashed` (F-pip): closed.

## Decisions this changed
| Finding | Decision changed | Scope | Owner |
|---|---|---|---|
| L1 size cap | yes (add flag) | adds 2 flags + 1 test | devops-engineer |
| Suggestion: test lock has no option lines | yes | adds 1 test | devops-engineer |
| I1-I3 | no (accepted, documented) | none | - |
