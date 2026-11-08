# Code review: slice 1b budget books (e809572, base 257faf5), opus/high

Verdict: REQUEST CHANGES (1 must-fix, 4 should-fix, 2 nits). Tests 983 passed; rebuild byte-identical (3,846 lines). Spot check 18 lines across both books: all match. All 27 does-not-add-up totals traced: 26 real book errors, 1 ours (finding 1).

1. must-fix fin_budget.py:327 budget-reconcile/subtotal-scope-class: subtotal scope ignores account class; FY2025 p103 "Capital Expenditures" (57xxx) wrongly flagged. Scope by code-class regex per subtotal label; regression test on p103.
2. should-fix fin_checks.py:114 budget-reconcile/held-counted-as-book-error: held totals counted as does_not_add_up. Use not_checked; count separately.
3. should-fix fin_facts.py:209, fin_run.py:197 provenance/book-missing-drops-lines: missing book silently drops lines, exit 0. Make it a guard (exit 2, nothing written).
4. should-fix finance.yml kind_words column-kind/budget-year-kind: "FY 25 Projection" in the approved FY2025 book is the adopted budget year; "FY 2026 Projections" in FY2027 is an estimate. Per-book kind override.
5. should-fix fin_budget.py:210 column-kind/derived-band-spill: tokens in derived bands unchecked; hold the line when one spills.
6. nit fin_budget.py:323 held label-less row keeps dollars; null them.
7. nit fin_checks.py:112 rounding n counts "-" cells; consider nonzero only; no mixed-class test.

Manager decision on 4: per-book override; FY2025 book "FY 25 Projection" = kind adopted (header still shown as printed); FY2027 "Projections" stays projected. Record in ADR 0002.
