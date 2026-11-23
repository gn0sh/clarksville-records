# Provenance check fix (PR #93) review

## Code review (code-reviewer, opus/high, fresh) at 19be435: APPROVE
1. should-fix provenance/verbatim-span-producers-unguarded qa/site_checks.py:1919, docs/architecture/clarksville-records.md:409: the regex exempts every bare data-item-title span (~28 producers in 7 templates); all hold record words today, nothing enforces it. Add a template registry test pinning each span's inner expression; reword doc/comment.
2. should-fix provenance/index-t-producers-misdocumented qa/site_checks.py:1920-1921: three more `t` producers (rpc.py:364-367, council.py:292 config fallback, views.py:1932 item_id). Fix comment; assert untitled_item / "Untitled item" carry no banned phrase.
3. nit provenance/vote-t-untested tests/test_provenance.py:229-231: add a k: vote case.
Checked: regex bypasses (spacing, attrs, case, nesting, newlines), search-index fields still scanned, test_provenance 51/51, real pages build check_provenance 0 problems over 89,161 seat texts.

Fixes for 1-3: 59a05ad (test_provenance + test_site_review_fixes 99 passed). Delta re-review pending.

## Delta re-review (code-reviewer, opus/high) at 59a05ad: APPROVE
- provenance/verbatim-span-producers-unguarded: fixed for spans; registry test finds 24 template producers + 1 `<dd>` and fails on new literal spans, duplicate expressions, new subfolder templates, newlines in tags, and spans written in sitegen Python.
- provenance/index-t-producers-misdocumented: fixed; comment at qa/site_checks.py:1921-1928 names every item/vote producer (views.py:1924, :1932, council.py:292, rpc.py:364-367); fallback strings tested against BANNED.
- provenance/vote-t-untested: fixed; tests/test_provenance.py:225 parametrized over item and vote.
- NEW should-fix provenance/verbatim-span-producers-unguarded (family hit 2 in this PR), tests/test_provenance.py:273, site/templates/_macros.html.j2:75: the `item_title` macro pin is `{{ title }}` (its own parameter), so callers are unpinned; a caller passing site words passed the test. Fix: pin each `item_title(...)` caller's argument too (5 callers today, all record titles).
- Accepted: HTML assembled by Python string formatting would bypass the Python scan; no such producer exists; other-attribute spans fail safe.
- Tests: 99 passed (test_provenance + test_site_review_fixes), after scripts/fetch-data.sh.

Fix for the item_title caller pin: b5db47e4

## Delta re-review 2 (code-reviewer, opus/high) at a9a7c7ae: APPROVE
- provenance/verbatim-span-producers-unguarded (item_title callers): fixed; `test_every_item_title_caller_is_pinned` parses templates with Jinja and pins the 5 callers. Fails on a literal argument, split-line concatenation, `set` rename, import alias, module import and `{% call %}`. Not caught: subscript lookup `m["item_title"]` (none exists; noted in the test).
- No new problems. nit: 3 blank lines at tests/test_provenance.py:309. Pre-existing E501 at line 68.
- Tests: 100 passed (test_provenance + test_site_review_fixes).
