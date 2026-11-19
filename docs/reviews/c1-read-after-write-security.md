# C1 read-after-write fixes: security review (2026-11-19)

Reviewed head: **36e55feb9eaae6e2f6c659e14faa586f69487426** (PR #65).

## adfd307: OK with follow-ups (security-engineer, opus high)
- Low `data-off-main/disable-window-unobserved-run`: a run that starts and finishes inside the wait is not seen. Covered by the second runs read 30 s later (row 17), plus the `m == base` checks at steps 3 and 5.
- Rollback order is unchanged. A stale enable read fails safe.

## 8579a63b..1b809c9b: OK with follow-ups (security-engineer, opus high, fresh)
- No retry accepts a stale or partial read. The check is an exact match on what this run wrote, and it fails closed after 10 reads.
- `--main <sha>` doesn't weaken protect-main. Ruleset ids taken from the POST response must equal the name-filtered list exactly.
- Repeated 422 POSTs can't create duplicates.
- All protection checks still fail closed.
- Low findings:
  - `rollback-pr-422-message` (an open PR's 422 now stops at once): fixed in 36e55feb.
  - `r2put-uninitialised`: fixed in 36e55feb.
  - `main-protect/main-pin-ref-ambiguity` (a branch or tag named like a sha): needs verification and is a follow-up. GitHub is believed to refuse 40-hex ref names.
