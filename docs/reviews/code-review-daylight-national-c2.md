# Code review: daylight-national C2 Legistar upcoming reader (699678b)
Reviewer: code-reviewer, opus/high, 2026-11-19. Verdict: REQUEST CHANGES (one must-fix). Privacy gate holds.
1. must-fix `cache-confine/symlinked-body-folder` (legistar_upcoming.py:368-369, _sweep :232, _cache_put :274): a shown
   body's cache folder that is a symlink is followed: outside files deleted and item text written outside (proved).
2. nit `cache-confine/root-symlink` (:217): symlinked cache_root is emptied by prune_cache.
3. nit `legistar-cache/item-count-drift` (:187, :274): fresh 160 vs cached 150.
4. nit `legistar-window/no-upper-bound` (:385): nothing past today+28 dropped client-side.
5. nit docs: ADR 0013 still says ^final\b; add amendment for exact final_statuses.
Checked and holds: no items request or item text for withheld entries (feed, cache, proposals, errors, logs); Draft and
unknown status never request items; only webapi.legistar.com/v1 requested; B14 guards before every write; odd ids safe.

## Delta 8a30fe3 (resumed): APPROVE WITH NITS
All 5 closed (probe re-run). New nit for C3: `cache-confine/put-error-kind`: _cache_put raises bare ValueError; C3 should map it to FeedError/ReadError.
