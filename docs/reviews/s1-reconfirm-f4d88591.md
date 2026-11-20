# Security re-confirm of S1 fixes at f4d88591 (security-engineer, opus/high, 2026-11-19)

Verdict: NOT OK (one Medium). S1-1, S1-2, S1-5, S1-6, S1-7 and the .ps1 false-pass fix: fixed. S1-3: partly. S1-4 deferred as planned. 297 tests passed (protect_main, u3_toggle, cutover_data_off_main); pwsh not installed, .ps1 static review only.

- N1 Medium `data-off-main/rollback-seedpin-untrusted` (cutover-data-off-main.sh:492 `seedpin=$(pinned_seed_digest "$sha^1")`; .ps1:643 `PinnedSeedDigest "$Sha^1"`). In --rollback --merge, the seed digest that data_verified trusts is read from R's parent commit, which the PR author controls; nothing checks $sha^1 is on main. A writer (claude[bot] has Contents write) opens R as two commits: X re-pins RECORDS_DATA_SEED_DIGEST to its own data listing, the head restores the workflow; the squash hides X; unverified data merges and R2 goes on. Fix: take the pin from trusted main ($m from rollback step 1); also refuse unless `git merge-base --is-ancestor "$sha^1" "$m"`; both twins; test where R's parent re-pins the digest.
- N2 Low `main-protect/stale-approval-wording`: "2 approvals" left in protect-main.sh:31/.ps1:35, u3-toggle.sh:36/.ps1:35, ADR lines 176, 195, 221 (covered by amendment (d)'s read-as note). Reword when next touched.

Most serious: N1, the only check that can pass with attacker-chosen input.
