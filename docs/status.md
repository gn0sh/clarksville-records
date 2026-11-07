# Status

**Feature:** milestone 1, County Commission votes and attendance (private preview).
**Stage:** M0 passed. Build M1 (backend B1-B4, frontend F1-F5). **Pace:** top priority today (Brian 2026-11-07 18:52Z), normal pace, 2-3 agents in parallel.

## Waiting on the CEO
(none)

## Run ledger
| Date | Role | Model/effort | Task | Outcome |
|---|---|---|---|---|
| 2026-11-07 | product-manager | sonnet/medium | spec v1 | done, 23ad7c5 |
| 2026-11-07 | brain-trust x6 | opus/high (api) | spec review | 5 Fix First, 1 Rethink; ~$0.37 |
| 2026-11-07 | backend-engineer | opus/high | M0 parse spike | done, a9e1262: 95.8% Verified (138/144), 0 wrong of 380 hand-labelled votes |
| 2026-11-07 | software-architect | opus/high | M1 design, ADR 0001, tasks, schema | done, 2db2bde |
| 2026-11-07 | frontend-engineer | sonnet/high | F1-F5 site generator | done, 157e789 |
| 2026-11-07 | backend-engineer | opus/high | B1-B4 collector | done, b956334 (full corpus blocked by dev2 403) |
| 2026-11-07 | deep-researcher | sonnet/medium | find 2025-26 county + post-2024 city minutes | found prod clerk page + CivicClerk |
| 2026-11-07 | qa-engineer | sonnet/high | test plan + spot-check + site checks | done, 2a377d3 |
| 2026-11-07 | backend-engineer | opus/high | prod discovery, 2022-26 corpus, review fixes | done, e80ec75: 64 meetings, 336/413 verified |
| 2026-11-07 | code-reviewer | opus/high | fresh review e80ec75 | request changes: consent reprints not fixed (2nd item-history hit) |
| 2026-11-07 | software-architect | opus/high | one-vote invariant + fix (loop rule) | running |
| 2026-11-07 | qa-engineer | sonnet/high | final QA + spot check on 5b09728 | FAIL: 19/20 (OCR name in motion text), consent dupes, 81.4% verified |
| 2026-11-07 | frontend-engineer | sonnet/high | hide unverified motion text + raw outcome text | running |
| 2026-11-07 | code-reviewer | opus/high | review collector | request changes: 4 must-fix, 4 should-fix |
| 2026-11-07 | code-reviewer | opus/medium | review F1-F5 | request changes: 1 high, 2 medium, 4 low, 1 nit |
| 2026-11-07 | frontend-engineer | opus/high (stepped up) | fix review findings | done, 98c98c0 |
| 2026-11-07 | code-reviewer | opus/medium | delta re-review | request changes: neutrality 2nd hit, about page copy |
| 2026-11-07 | software-architect | opus/high | held-count invariant + fix (loop rule) | done, a8154fa |
| 2026-11-07 | code-reviewer | opus/medium | delta re-review x2 | approve (1 low passed to backend: g4-blind-to-uniform) |
| 2026-11-07 | code-reviewer | opus/high | delta re-review of consent fix 92213e8 | approve; nit: identical same-mover reconsideration would merge (no live case) |
| 2026-11-07 | frontend-engineer | sonnet/medium | verified motions show type + resolved Moved/Seconded names (0719820) | done, 262 tests pass |
| 2026-11-07 | code-reviewer | sonnet/medium | review 0719820 | request changes: leak-path/data-downloads, leak-path/raw-name-fallback, partial attribution, tests |
| 2026-11-07 | code-reviewer | sonnet/medium | delta re-review of leak fixes 07f990e | request changes: raw-ocr-leak/vote-raw-value |
| 2026-11-07 | ux-designer | opus/medium | visual refresh spec | done, docs/design/visual-refresh.md |
| 2026-11-07 | frontend-engineer | opus/high | unconfirmed votes shown with asterisk + invariant rewrite (a991a10) | done, 270 pass |
| 2026-11-07 | code-reviewer | opus/high | review a991a10 | request changes: 1 must-fix raw-ocr-leak/verification-detail; neutrality/held-count (3rd hit, attribution rule 6: decided unconfirmed motions never show names); raw-ocr-leak/qa-outcome-benign |
| 2026-11-07 | frontend-engineer | sonnet/high | visual refresh build (ca700ea) | done, 276 pass |
| 2026-11-07 | brain-trust x6 | opus/high (api) | round 2, corrected operator facts | 6 Fix First; unanimous: unconfirmed rows show no vote value (CEO card open) |
| 2026-11-07 | backend-engineer | opus/high | fix a991a10 findings + link-only switch (07be770) | done, 299 pass |
| 2026-11-07 | frontend-engineer | sonnet/low | not-confirmed chip style (95e1235) | done |
| 2026-11-07 | code-reviewer | opus/high | delta re-review 16ee1fc | approve with nits (doc drift fixed) |

## Decisions
- 2026-11-07 G1: footer line on every page + About page naming the operator (CEO, card).

## Problem keys
| Family | Hits | Keys |
|---|---|---|
| neutrality | 2 (review, delta): architect states invariant | held-count-by-resolved-id, under-review-mislabelled |
| verified-gate | 2 (review, QA motion-text-names): manager decision, show motion type only when unverified | motion-over-hidden |
| escape | 1 (review) | unsafe-url-scheme |
| contract | 1 (review) | no-referential-check |
| attribution | 1 (review) | motion-ignores-context, item-link-unchecked, name-pairing-no-margin, one-entry-per-official |
| item-history | 2 (review x2): architect states invariant | consent-reprint-duplicates, consent-pulled |
| politeness | 1 (review) | redirect-bypass |
| idempotence | 1 (review) | superseded-source |

## Skipped panels
- Architect recommended a 3-member Brain Trust on the facts schema and id scheme; skipped for today's preview (private, data regenerated from source each run, so the schema is cheap to change before public launch). Revisit at M1.5.
- M0 note: first index request got a 403 from the sandbox egress proxy (allowlist not yet live), not from the county; the engineer retried once. Fetcher must tell proxy CONNECT refusals apart from server 403s (B1).
- Private preview artifact: https://claude.ai/artifact/QkxSRXNSMiWXpHUoLj8ynj (v1 draft with 11 meetings, published from build/publish/index.html + build/site files; republish same path).

## Decisions (Brian, 2026-11-07 3:54 PM ET)
- Unverified roll calls are no longer held back. They are shown with an asterisk, "not confirmed", and a link to the exact PDF page. Totals split confirmed and unconfirmed. Unmatched names are never guessed. Supersedes the hold-back display rule (P2 still decides "confirmed"); G4 skew check still reported.

- Brian 2026-11-07 4:47 PM ET: unconfirmed roll calls show NO vote value, link only (card). SHOW_UNCONFIRMED_VALUES stays False.
