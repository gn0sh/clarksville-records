# B4 review fixes: handoff (backend-engineer, 2026-11-19)

Branch: `claude/data-off-main` on origin at **5fee8d62**. It contains fix commit 1aeb9f4f plus a merge of f4d88591 (devops 7f05bd8a and ADR S1). The merge was clean. I did not touch the rollback seed-pin code in the cutover scripts.

| Item | Fix | Test |
|---|---|---|
| S1 held-issue-branch-runs | The deploy-held issue opens only when `github.ref == 'refs/heads/main'` | `test_the_held_issue_has_one_fixed_title_and_its_own_text_per_kind` |
| S1b | `MAX_WALK` is now 2, so only D or D+1 can be the live tree. L32 row corrected. The not-read issue text now names a reviewed code PR as the way out | `test_the_live_tree_is_only_d_or_d_plus_1`, and the not-read case of the issue test |
| S2 ipub-list-never-spent | Each entry pins `path`, `fact_id`, `change` and `value_sha256`. Schema bumped to 2.0. One entry per (`path`, `fact_id`). The hit line prints the four values to copy. Decision recorded in the `docs/tasks/data-off-main.md` B4 notes | `test_an_entry_lets_through_only_its_exact_change`, `test_an_entry_is_spent_once_the_live_site_shows_its_value`, `test_a_listed_change_passes`; schema tests in `tests/test_data_shape.py` |
| N1 | The tripwire report is replayed between `::stop-commands::<random 32-hex>` and `::<token>::` | `test_the_report_is_replayed_with_workflow_commands_stopped` |
| N2 | When one copy of a duplicate id disappears, it counts as a removal, whether the copy was shown or not | `test_removing_one_copy_of_a_duplicate_id_holds` |
| N3 test-flake | See below | `test_a_second_session_with_the_same_basetemp_stops`, `test_a_calls_log_that_is_gone_is_an_error_never_no_calls` |
| N4 | Runbook heading 6a and its two references now say V1'' | none (docs only) |

**N3 root cause (reproduced):** the failure appears when two pytest sessions run at once with the same `--basetemp`. Each session empties that folder when it starts and names its tmp folders the same way, so one session wipes the other's `state.json` and calls log. The stub's call log then reads back empty, which is the "0 == 3" assertion at `tests/test_protect_main.py:393`. Fix: `conftest.py` now locks `<basetemp>.lock`, so a second session on the same folder stops with exit 4. The protect-main test harness now creates the call log up front and treats a missing log as an error instead of "no calls". `docs/ops/preflight.md` now says to give each concurrent run its own basetemp folder.

**Tests:**
- Full suite at 1aeb9f4f: `6176 passed, 5 skipped in 3167.35s`.
- After the merge, the eight affected files (protect-main, cutover, u3-toggle, workflow-lock, tripwire, data-shape, staleness, pipeline-limits): `1045 passed in 428.14s`.
- Every file I changed passes `ruff`.

**Open:** a `removed` entry can match again only if the same fact comes back with the identical value and is then removed again. This is recorded in the B4 notes; spent entries should be deleted in a later PR.
