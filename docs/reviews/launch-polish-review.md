# Review: launch polish (PR 96)

Branch `claude/launch-polish`. Reviewer: code-reviewer (sonnet, medium). Security review not required: no auth, secrets, CI, deploy or external input touched (static templates, CSS, one JS listener, tests).

## Round 1, b77a8bf: APPROVE WITH NITS
| Key | Sev | Finding | Outcome |
|---|---|---|---|
| a11y/dom-vs-visual-order | should-fix | `grid-auto-flow: row dense` moved the morning-note card visually ahead of the Digest line while DOM order stayed address, Digest, note | Fixed b565469: `sitegen/national_pages.py` inserts the Digest line after `.note-invite`; `dense` dropped |
| a11y/clamped-links-focusable | nit | Keyboard focus could land on a link clipped by the clamp | Fixed e33cb12: `clamp.js` expands on `focusin` |
| clamp/scope | nit | Clamp applies at every width, not only phones | No change: `clamp.js` clamps only spans that overflow |
| tests/coverage-gap | nit | No test for the built 404 page | Fixed e08c347: test in tests/test_unofficial.py |
| pages/404-special-case | nit | 404 root special case hand-copied in tests | Fixed 1e64102: `ROOT_ABSOLUTE_PAGES` / `root_prefix` in tests/conftest.py |
| lint | nit | two E501 lines in sitegen/build.py | Fixed 9d545a0 |

## Round 2 (delta), b77a8bf..1e64102: APPROVE WITH NITS
All round-1 findings closed. `_with_front_line` regex checked: anchored `.match`, non-nested section, falls back to right after the address card when there is no invite. Nits (tests/weak-ordering, style/conftest-placement, style/comment-indent) carried in 315ad15.

## Full-suite follow-up, 2c5602a
The first full run found 10 page-wide tests that assumed every link is relative; fixed test-side with `root_prefix` (no site check loosened for other pages). 493bed9 merges main (PR 95), clean.

## Preflight (combined head b23db1d, which contains this branch)
pytest 9045 passed, 547 skipped, 4 failed (the `[sh]` Ctrl-C timing tests in test_cutover_data_off_main.py and test_u3_toggle.py: fail only under full-suite load, pass alone here and on main, touch no file in this PR). Pages build + export + `qa.site_checks --no-browser`: 38 checks, PASS.
