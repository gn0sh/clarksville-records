# Security review: eef6ed0 (PR #66, merged without merge-reviewed) and the baseline move

Reviewer: security-engineer (opus/high), 2026-11-20, against origin/main. Verdict: **OK with follow-ups.** No critical or high findings. Moving `MAIN_PR_BASELINE` to eef6ed06 is the right and the smallest step.

## Checked
- History: `git log --first-parent 1922fda3..eef6ed06` is exactly 8d69778 then eef6ed0. eef6ed0's tree equals PR #66's head b0b3ffc.
- Trust roots: none touched. 17 paths: docs/design, site/static/style.css, site/templates (6), sitegen/build.py, sitegen/freshness.py, tests (6; layout, CSS, sign-up card). Nothing in .github, scripts, collector, config, schema, requirements or the sender. The I-pub tripwire reads data/ JSON, not HTML.
- CI, deploy, note, XSS: nothing new. The only workflow is daily-update.yml (schedule and dispatch). `freshness.own()` returns a dict copy; no I/O or imports. Morning note content and recipients unchanged. Autoescape on (build.py:157); no `|safe`, Markup or dunder access in new templates; CSS adds no url(), @import or http.
- Rollback: pins `--cutover-merge 8d69778` and checks the first-parent line, which does not change; it never reads the baseline's value. (.ps1 twin read at function level only.)

## Findings
1. medium `pr66-merged/unreviewed-head`: PR #66 has zero reviews, so the gate refusal is correct. Fix: every merge to main, the baseline PR included, goes through scripts/merge-reviewed. This report is the after-the-fact review of eef6ed0.
2. medium `pr66-merged/baseline-pr-proof` (daily-update.yml:122). Merge conditions for the baseline PR: (a) first-parent 1922fda3..eef6ed06 = [8d69778, eef6ed0]; (b) `git diff --quiet eef6ed06 b0b3ffc1` and no trust root in eef6ed0's paths; (c) 8d69778 meets the gate's checks (PR #65 merged by gn0sh User, OWNER COMMENTED at head 20c3b972 03:19:59Z before merged_at 03:20:01Z: verified); (d) the diff is that one value, RECORDS_DATA_SEED_DIGEST unchanged, exactly one anchored `MAIN_PR_BASELINE:` line (tests/test_cutover_data_off_main.py pin test passes); (e) the value is exactly eef6ed06; (f) `protect-main --check` prints OK just before the merge; (g) merged with merge-reviewed.
3. low `pr66-merged/cutover-recheck-dropped`: past the new baseline the gate no longer re-checks 8d69778. Recorded in ADR 0011 (note 2026-11-20 before Amendment (d)).
4. low `pr66-merged/baseline-comment-stale`: the line-122 comment now points to that ADR note.

Alternatives: baseline at 8d69778 still refuses; a revert still refuses; a review posted now fails `submitted_at <= merged_at`; rewriting history is hard stop 2.
