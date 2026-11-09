# Code review: exports, offline guard, finance page split (61658a1..5d2e560), 2026-11-09
Verdict: REQUEST CHANGES (one medium).
- MEDIUM fin-export/held-leak, collector/fin_export.py:166-168, 225: when the awardee is held, awardee_match (bidder:N) is kept, so a reader can join it to bidders.csv and recover the held awardee. Fix: null it, and add a test. Today's data has no held awardee.
- LOW offline-guard/id-change: a parser fix that renames meeting ids is refused as "drop". The refusal message should name that cause.
- INFO: online runs have no shrink guard; exports total 35.6 MB.
Checked: 2 real held totals export as null plus the check name; 40 unread tabs export nothing; every finance row has a source; 3 budget lines match; nothing is sorted by amount and nothing is summed; finance/101 shows 2,780 lines exactly once across 5 parts; 0 broken links; the guard is gated on offline.
