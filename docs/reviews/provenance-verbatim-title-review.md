# Provenance check fix (PR #93) review

## Code review (code-reviewer, opus/high, fresh) at 19be435: APPROVE
1. should-fix provenance/verbatim-span-producers-unguarded qa/site_checks.py:1919, docs/architecture/clarksville-records.md:409: the regex exempts every bare data-item-title span (~28 producers in 7 templates); all hold record words today, nothing enforces it. Add a template registry test pinning each span's inner expression; reword doc/comment.
2. should-fix provenance/index-t-producers-misdocumented qa/site_checks.py:1920-1921: three more `t` producers (rpc.py:364-367, council.py:292 config fallback, views.py:1932 item_id). Fix comment; assert untitled_item / "Untitled item" carry no banned phrase.
3. nit provenance/vote-t-untested tests/test_provenance.py:229-231: add a k: vote case.
Checked: regex bypasses (spacing, attrs, case, nesting, newlines), search-index fields still scanned, test_provenance 51/51, real pages build check_provenance 0 problems over 89,161 seat texts.

Fixes for 1-3: 59a05ad (test_provenance + test_site_review_fixes 99 passed). Delta re-review pending.
