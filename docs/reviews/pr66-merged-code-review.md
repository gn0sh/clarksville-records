# Code review: eef6ed0 (PR #66, merged without merge-reviewed)

Reviewer: code-reviewer (opus/high), 2026-11-20. Verdict: **accept with follow-ups.** Moving `MAIN_PR_BASELINE` to eef6ed06 is safe without reverting anything first.

## Scope
`git log --first-parent 1922fda3..origin/main` = 8d69778 (#65), eef6ed0 (#66). #65 has gn0sh's COMMENTED review at head 20c3b97 before its merge. eef6ed0's tree equals #66's head b0b3ffc (based on 8d69778). 17 files: site/templates (6 + new `_note_invite.html.j2`), site/static/style.css, sitegen/build.py, sitegen/freshness.py, docs/design/front-page-v2.md, 6 test files. Nothing in .github/, scripts/, collector/, config/, data/, schema/, sender/, deploy/ or requirements.

## Published facts, mail, deploy, gate
Built the site from records-data at 8d69778 and at eef6ed0 and diffed: same file set; 9 files differ (style.css, home, montgomery-county, city, rpc, two city committees, county-committees, school-board). Every officials, vote and meeting page is byte-identical: no new text about named officials; votes still only from the record. Visible words unchanged except the morning-note invitation (same config text, same `alerts.html#note` link). Nothing sends mail, deploys or touches the gate.

## Findings
- should-fix `pr66-merged/disclosure-collapsed-limits` (site/templates/council_home.html.j2:10-11): "Minutes fetched between ..." is now inside the collapsed "About these dates" toggle; before it was always shown. Provenance, not a collection limit (judgment, medium).
- nit `pr66-merged/design-pending` (docs/design/front-page-v2.md:163): says pending the owner's yes, but it is live on main (Brian approved "deploy" Nov 19).
- nit `pr66-merged/css-not-complex` (style.css >=1440px): `:not(.find p)` needs Selectors 4; inside `:where()` older browsers drop the rule.

## Checks run on eef6ed0
6 changed test files: 114 passed. ruff: same counts as 8d69778 (116 repo-wide, pre-existing). Build + site_checks: FAIL "525 files > preview cap 500", same at 8d69778 (known follow-up, not #66). Full suite: not finished here; run before the baseline PR merges.
