# Security delta check: PR #69 merge commit 4653fac (main a24c6d4 into def3916)

Reviewer: security-engineer (opus/medium), 2026-11-20. Verdict: **PASS**. No findings.

- `git show --remerge-diff 4653fac` changes only docs/platform-facts.md: daily-update.yml, sitegen/build.py and
  docs/ops/morning-note.md auto-merged with no hand edits; no hunk reordered, duplicated or lost.
- def3916 -> 4653fac in workflows and sitegen is exactly main's own change since merge base 8d69778 (3 files,
  +11/-5): daily-update.yml:132 MAIN_PR_BASELINE 1922fda3 -> eef6ed0 (PR #66, ancestor of 4653fac; :221-238 still
  refuse an empty, malformed or off-first-parent baseline); sitegen/build.py freshness strips via the new pure
  fresh_mod.own() (sitegen/freshness.py:46, no I/O, no national path).
- Byte-identical to the reviewed head def3916: workflow permissions, triggers, push job write and attestation scope,
  the national read-only gate (D2 step from :273, soft, attestation identity pinned), the national-data tree helper
  (:285-311), national-update.yml and all sitegen/national*.py. Section 12 national-isolation and the attested-push
  trust roots stand as reviewed in security-review-daylight-national-s2e.md.

Process note (main-protect/baseline-merge-reviewed): daily-update.yml:84 requires every commit on main after
eef6ed0 to be merge-reviewed, so PR #69 must land through merge-reviewed.ps1.
