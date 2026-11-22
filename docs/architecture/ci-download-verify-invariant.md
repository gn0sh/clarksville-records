# CI download-verify invariant (loop rule: `ci-supply/browser-bytes-unverified`, hit 2)
software-architect, 2026-11-22, on ee3764b. Hit 1: security review bbc603a F1 (Playwright checks a download's size only;
fix: the tree check against `tests/playwright/browsers.sha256`). Hit 2: security re-check a84d19d R1
(`docs/reviews/security-recheck-digest-ci-a84d19d.md`): the tree check runs *after* Playwright's own extractor has
unpacked three unverified zips, so a poisoned zip can write outside `$br` through a symlink entry, replace Playwright's
code before the check, or omit `chrome` and pass as `missing`. Checking an unpacker's output cannot protect the
unpacker: the check moves to the bytes as they arrive.

## The invariant
**No byte CI fetches in order to run it (a package, a browser, a tool) is unpacked, executed, cached or put on PATH
before its hash has been checked against a value committed in this repo (a sha256 list, a lockfile integrity hash, or
an action's pinned commit SHA); a mismatch fails the job, a download that keeps failing is reported as `missing`.**
Exceptions, closed list: bytes signed by a key the runner image already trusts (apt), and the runner image itself
(node, npm, curl, unzip, git, gh, Python in the tool cache). Data CI fetches to *read* (PDFs, listings, national API
replies, records-data and national-data commits, same-run artifacts) is never run; it is held by the data invariants
(`pipeline-limits-invariant.md`, `data-off-main-trust-roots.md`, the artifact shape checks), not by this one.

## Every consumer (both workflows; no other workflow exists, and they call no download script)
| # | Where | What it fetches | Verified today by | Holds? | Fix / accepted exception |
|---|---|---|---|---|---|
| 1 | daily 737 `npm ci --ignore-scripts` | playwright, playwright-core 1.63.0 | sha512 in `tests/playwright/package-lock.json`; EINTEGRITY = hard fail | holds | none |
| 2 | daily 746 `playwright install chromium` | 3 zips (CfT chromium, headless shell, ffmpeg) | tree check *after* Playwright unpacks | **no (R1)** | replace with section "R1 design" |
| 3 | daily 745 `playwright install-deps chromium` | apt packages (sudo apt-get) | Ubuntu archive signatures; the package list is in verified #1 | holds (exception) | accepted: signed by the image's apt keys |
| 4 | daily 468-469 `apt-get install poppler-utils tesseract-ocr` | apt packages | Ubuntu archive signatures | holds (exception) | accepted, same reason |
| 5 | daily 470, national 235 `pip install --require-hashes -r requirements.lock` | 15 pinned packages | sha256 per file in the lock | **partly** | a package with no cp312 wheel falls back to its sdist, whose isolated build fetches setuptools/maturin with no hash check. Fix F-pip below |
| 6 | daily 456-461 setup-python `cache: pip` (restore) | pip's HTTP/wheel cache | pip re-hashes every file it takes from the cache in hash mode | holds | with F-pip no locally built wheel exists to reuse |
| 7 | daily 456, 1625; national 213 setup-python | CPython 3.12 (tool cache; download only if absent) | pinned action SHA; the interpreter itself unhashed if downloaded | holds (exception) | accepted: GitHub-hosted image and actions/python-versions, same trust root as the runner |
| 8 | all `uses:` (checkout, cache, upload/download-artifact, attest, upload/deploy-pages, setup-python) | action code | full 40-hex commit SHA in the workflow | holds | daily: tests/test_workflow_lock.py:183 keeps them pinned; T1 adds the same check for national |
| 9 | daily 483-489 restore `data/store` | PDFs (data) | `Store.has_bytes`: sha256 == file name, else refetched (collector/store.py:62) | holds | data, re-checked on read |
| 10 | daily 498-506 restore `data/text`, `data/ocr` | derived readings (data) | key = tool versions + code + lock hash; saved on main only | holds (exception) | accepted (ci/derived-cache-integrity). Its real exposure was R1: unverified code ran in the same job before the `if: always()` saves (1267-1286). R1 closes it |
| 11 | no cache of browsers or zips exists | - | - | holds | rule: never add one for `pw-browsers`, `pw-zips` or `ms-playwright`; a test enforces it (T9) |
| 12 | daily 191, 228, 316; national 132, 162 `git fetch`; daily 390, 420 checkouts of D / N | git objects (data) | gate: I-data'', I-prov attestation, commit SHA | holds | data invariants own it |
| 13 | daily 1365, 1667; national 307 download-artifact | same-run artifacts (data) | shape checks (1375-1394, 1672+, national 315+); the sender is staged from git before the plan arrives | holds | none |
| 14 | `gh api` / `gh issue` (gate, issue steps) | JSON replies (data) | never executed | holds | none |
| 15 | curl / wget / `gh release download` | none anywhere today | - | holds | R1 adds the only curl; T1 pins it to two URLs |

## R1 design (devops-engineer; daily-update.yml install step only, national-update.yml untouched)
1. Commit `tests/playwright/browser-zips.sha256` (sha256sum format, exactly these two lines; the step checks the shape
   first, malformed = hard fail before any fetch): `8aac35011c18f6e2d10696154af89a5728ac2ddd6dc6fad24ffdf243c3fcfd5a
   chrome-linux64.zip`, `a9da028861a0cf789ff25c2fed45f5f1aaf969ed9247835b6a7821a4f7af9d1d  chrome-headless-shell-linux64.zip`.
2. Keep node >= 20, `npm ci`, `install-deps chromium` (tries x3) as they are. Add `command -v unzip || missing`.
3. `zips=$(mktemp -d "$RUNNER_TEMP/pw-zips.XXXXXXXXXX")` (new, empty). `download()`: `rm -f -- "$zips"/*`, then for each
   name in a fixed literal list: `curl --fail --location --proto '=https' --proto-redir '=https' --max-time 300
   --silent --show-error -o "$zips/<name>" "https://storage.googleapis.com/chrome-for-testing-public/153.0.8010.12/linux64/<name>"`.
   `tries "The Chromium download" download || missing "..."` (missing also removes `$zips`). No `-k`, no `--retry`.
4. `(cd "$zips" && sha256sum --quiet --strict -c "$PWD/tests/playwright/browser-zips.sha256")`, and `$zips` holds
   exactly the two files. Mismatch = `::error::` naming browser-zips.sha256, `rm -rf "$zips"`, exit 1. Never retried.
5. Only then: `rm -rf -- "$br"; mkdir -p "$br/chromium-1243" "$br/chromium_headless_shell-1243"`; `unzip -q -d` each zip
   into its folder (`chrome-linux64/`, `chrome-headless-shell-linux64/` land inside); `: > <folder>/INSTALLATION_COMPLETE`
   (empty, as in browsers.sha256); `rm -rf "$zips"`. An unzip failure on verified bytes = hard fail.
6. Keep the tree check, tightened: the top level is exactly the manifest's two folders (drop `.links` from the
   expected set and its `find` line; drop `rm -rf ffmpeg-*`, so any ffmpeg or `.links` folder is "a folder added").
7. Remove every `playwright install chromium`. Keep `PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS`, the env, no token.
8. Update the comment block (692-707) and `tests/playwright/browsers-sha256.sh`'s regeneration note: regenerate from the
   same curl, check, unzip and marker steps, never from `playwright install`. Bump procedure (Playwright lock moves):
   new CfT version + revision in the step, both .sha256 files, and `REVISIONS` in the test, in one PR.
9. Caches: nothing new is cached; store and derived saves are unchanged (safe once no unverified code runs in the job).
10. In-session proof before review: real zips through the step, "592 files match", then `REQUIRE_BROWSER=1` on
   `tests/test_national_browser.py` launches the unzipped Chromium (proves modes and layout, which sha256 does not).

**R2** (`daily-run/install-step-hard-dependency`): worst case = npm 3x(180+15) + deps 3x(300+15) + download 3x(2x300)
+ pauses 3x(30+90) + 300 s (unzip, both checks) = 3,990 s, 66.5 min, so `timeout-minutes: 70`. The comment states the
sum. Cost: 20 more minutes of the 355-minute job budget in the worst case only (a cold collect is 4-5 h); accepted.
**R3** (`ci-browser/probe-skips-silently`): new step right after Tests, `if: always() && github.ref ==
'refs/heads/main' && steps.browsers.outputs.browsers == 'missing'`, `continue-on-error: true`, `timeout-minutes: 5`,
step env `GH_TOKEN: ${{ github.token }}` and `BR_TITLE: "Daily update: browser tests skipped (Chromium not installed)"`;
the AGE_TITLE pattern (909-943): fixed text into `$RUNNER_TEMP/browser-issue.md`, list by exact title, create else
comment, `--body-file` only. The job already has `issues: write`; the install step stays token-free.

**F-pip (beyond R1-R3, low, `ci-supply/sdist-build-deps-unhashed`):** add `--only-binary :all:` to both pip installs
(daily 470, national 235), so a missing wheel fails as a download, never builds. Editing national-update.yml moves its
blob: update `$natBlob` in scripts/protect-main.ps1 (~513) and its twin in protect-main.sh (~408) in the same PR.

**Accepted risk (code review dd1606e #5, `ci-browser/environmental-unzip-hard-fails`):** an unzip failure on bytes that
already matched browser-zips.sha256 (most likely a full runner disk) fails the job, so that day's Clarksville publish is
held, not skipped to `missing`. Accepted: the bytes are verified, so the cause is the runner, not the network, and a
partial unpack must never be read as "no browser"; the next scheduled run retries on a fresh runner. Revisit if it ever
recurs.

## Tests (tests/test_browser_install_step.py; update the 28 existing, add these)
- T1 static: no `install chromium` in either workflow; `install-deps chromium` once; exactly two curl calls, each with
  the five flags, only the fixed https base; no `-k`, `--insecure`, `http://`.
- T2 order: shape check < curl < `browser-zips.sha256` check < unzip < tree check < `browsers=ok`.
- T3 `browser-zips.sha256` is the two pinned lines; `REVISIONS = {"1.63.0": ("1243", "153.0.8010.12")}` agrees with the
  step's folders and URL.
- T4 behaviour (stub curl serving test-built zips; real unzip behind a logging stub): good run ok, two folders and
  markers, no `.links`; a failed try's partial file is never checked or unzipped. T5 curl fails 3x on either zip:
  `missing`, no `$br`, no `$zips`, no `::error::`, pauses 30 then 90.
- T6 hash mismatch on either zip: exit 1, no `browsers=`, unzip never called, `$br` never made, curl not retried.
- T7 malformed list (3 lines, other name, uppercase hex): exit 1 before any curl. An extra file in `$zips`: exit 1.
- T8 matching zip with a symlink entry, or `.links` / `ffmpeg-1011` beside the folders: tree check fails; nothing
  written outside `$br`. Unzip absent: `missing`; unzip failing on verified zips: exit 1.
- T9 no `actions/cache` path in either workflow names pw-browsers, pw-zips, ms-playwright or playwright.
- T10 R2: the sum above, parsed from the step's `timeout` / `--max-time` values, is <= `timeout-minutes` x 60.
- T11 R3: the step's `if`, env, `--body-file` only; stub gh: no open issue = create, one open = comment.
- T12 F-pip: both pip lines carry `--require-hashes` and `--only-binary :all:`; the `$natBlob` test still passes.
