# Code review: daylight-national C3 national run (6ac69c3)
Reviewer: code-reviewer, opus/high, 2026-11-19. Verdict: REQUEST CHANGES.
1. must-fix `national-confine/data-root-symlink-late` (run.py:386-393, :366-368): symlink check only in write_outputs;
   read_previous, prune and cache writes already went through the link (proved). Refuse at top of collect().
2. should-fix `national-proposal/streak-not-per-kind` (304-307): cant-cover proposal counts any failure kind.
3. should-fix `national-stop/robots-5xx-not-host-stop` (209-210, :285): robots 5xx -> disallow_all -> every body
   `robots` -> cant-cover proposals. Should be host-stopped.
4. nit `national-run/raise-outside-try` (269-270, 301-310, 139-146): bookkeeping outside per-body except.
5. nit `national-proposal/previous-text-unchecked` (169-172): previous observed/evidence_url not re-checked.
Holds: budget accounting, budget-skip, host stop, tenant order and <client>.legistar.com deny, per-body exceptions,
ids, freshness stamps, withheld kept feed has no item text, write confinement.
Open for manager: C2 feed keeps `full_url: None` vs 3.7 "minus full_url".
