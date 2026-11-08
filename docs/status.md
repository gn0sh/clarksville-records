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
| 2026-11-07 | qa-engineer | sonnet/medium | M1 QA at 95e1235 | FAIL on AC-P1 only (82.3%); spot check 20/20; key parse-accuracy/verified-rate |

| 2026-11-07 | backend-engineer | opus/high | raise verified rate | done, 345d497: 362/390 verified (92.8%), AC-P1 passes, 315 tests pass |
| 2026-11-07 | deep-researcher | sonnet/medium | district/ward map data | done, docs/research/district-ward-map-data.md (GIS hosts blocked by egress; used county vector PDFs) |
| 2026-11-07 | ux-designer | opus/medium | landing map, drawer, search, current/former officials | done, a85e0e6 docs/design/landing-search-nav.md |
| 2026-11-08 | code-reviewer | opus/high | review efbf38f..345d497 | request changes: 1 must-fix parse-accuracy/combine-ignores-unclean-dissent; should-fix outcome-crosses-clause, neutrality/derived-count-shown-as-stated; nit two-thirds |
| 2026-11-08 | backend-engineer | opus/high | fix review findings | done, 50b4bbf/0464107: 361/390 (92.6%), 327 pass |
| 2026-11-08 | code-reviewer | opus/high | delta re-review 0464107 | approve |
| 2026-11-08 | frontend-engineer | opus/medium | landing, drawer, officials, search, footer | done, 864b7e1: 412 pass; gaps: votes[].district, pre-2026 CZ titles lack applicant names |
| 2026-11-08 | code-reviewer | opus/high | review landing/search/seats at a552cd4 | request changes: must-fix provenance/derived-seat-dates-shown-as-term; should-fix qa-weakened/ext-link-any-host, qa-tool/layout-counts-year-tables (pre-existing), locality/hard-coded-text; 4 nits |
| 2026-11-08 | qa-engineer | sonnet/medium | QA landing/search/seats + spot-check newly verified | FAIL: landing/one-screen, attribution/seat-label-missing-former, attribution/seat-label-missing-meeting-history; AC-P1 361/390 PASS; spot-check 10/10 |
| 2026-11-08 | backend-engineer | opus/medium | rezoning applicant/location fields + search | done, e4dadf3: 74/88 CZ items have applicant or location, 431 pass |
| 2026-11-08 | software-architect | opus/high | provenance invariant + consumer list (loop rule) | done, 2c9dba6 |
| 2026-11-08 | backend-engineer | opus/medium | provenance B1-B3, seats.csv, seating page | done, 430c090/6e6c968: lines_effective stated (2022-08-30 oath date, 2022-09-12 minutes p37); 424 pass |
| 2026-11-08 | frontend-engineer | opus/medium | provenance F1-F6 + review/QA fixes + zoning on item pages | done, dd63506: 474 pass, site_checks all PASS, landing 667/667 phone, 800/800 desktop |
| 2026-11-08 | backend-engineer | opus/medium | (mis-resumed finished map-seats agent) | waste:duplicate |
| 2026-11-08 | code-reviewer | sonnet/medium | review rezoning fields | request changes: parse-accuracy/single-engine-misread-agrees, malformed-dissent-dropped; 3 nits |
| 2026-11-08 | software-architect | opus/medium | independent-readings invariant (loop rule, parse-accuracy 2nd hit) | done, e9c7502 |
| 2026-11-08 | backend-engineer | opus/high | independent-readings fixes + acreage printed + open-run check | done, ddf84e2..475bb60: verified 351/390 (0.900, gate passes, no headroom), zoning fields 289->218, 0 vote values changed, 458 pass |
| 2026-11-08 | frontend-engineer | sonnet/medium | merge readings fix, render acreage.printed, officials headings | done, 3471566: 487 pass, site_checks PASS |
| 2026-11-08 | code-reviewer | opus/high | fresh review d251fcb (readings + acreage) | request changes: must-fix parse-accuracy/reprint-dissent-unchecked (rate to 0.890), provenance/acreage-printed-uncorroborated; should-fix tests-miss-new-dissent, registry-walk-skips-dicts; nit a11y |
| 2026-11-08 | backend-engineer | opus/high | reprint dissent + acreage fixes, then headroom by better readings | done, b2d0d0f..42d763e: 347/390 after fixes, 354/390 (0.908) after headroom; 0 verified values changed; 26-2-6 p138 = 2 real roll calls; 0 titles fixed (glue not seen by both engines); 499 pass |
| 2026-11-08 | code-reviewer | opus/high | delta re-review of 42d763e | running |
| 2026-11-08 | frontend-engineer | sonnet/medium | name links site-wide + table row heights + not-confirmed chip | running |
| 2026-11-08 | code-reviewer | opus/high | delta re-review of landing fixes | approve with nits: a11y-headings/officials-sections; provenance/acreage-not-as-printed (3rd provenance hit, fresh review next); provenance/open-run-latest-mismatch (latent) |
| 2026-11-08 | qa-engineer | sonnet/medium | re-test landing bugs | PASS all; site_checks PASS incl. layout, provenance |
| 2026-11-08 | backend-engineer | opus/medium | map from county PDFs + seats.yml | done, 014b52b: 21 districts traced (19/20 swap verified), 49 seat records, 0 seat-check problems; wards unavailable (raster); 333 pass |

## Decisions
- 2026-11-07 G1: footer line on every page + About page naming the operator (CEO, card).

## Problem keys
| Family | Hits | Keys |
|---|---|---|
| neutrality | 3 (review, delta, review 11-08): architect states invariant | held-count-by-resolved-id, under-review-mislabelled, derived-count-shown-as-stated |
| verified-gate | 2 (review, QA motion-text-names): manager decision, show motion type only when unverified | motion-over-hidden |
| escape | 1 (review) | unsafe-url-scheme |
| contract | 1 (review) | no-referential-check |
| attribution | 1 (review) | motion-ignores-context, item-link-unchecked, name-pairing-no-margin, one-entry-per-official |
| item-history | 2 (review x2): architect states invariant | consent-reprint-duplicates, consent-pulled |
| politeness | 1 (review) | redirect-bypass |
| idempotence | 1 (review) | superseded-source |
| provenance | 3 (review 11-08 x2, delta): invariant stated (2c9dba6); fresh review on next fix | derived-count-shown-as-stated, derived-seat-dates-shown-as-term, acreage-not-as-printed, open-run-latest-mismatch |
| parse-accuracy | 3 (review 11-08, rezoning review, fresh review d251fcb): invariant stated e9c7502; implementation miss #1 of the re-plan (escalate to Brian only after 2) | verified-rate, combine-ignores-unclean-dissent, outcome-crosses-clause, two-thirds-majority |

## Skipped panels
- Architect recommended a 3-member Brain Trust on the facts schema and id scheme; skipped for today's preview (private, data regenerated from source each run, so the schema is cheap to change before public launch). Revisit at M1.5.
- M0 note: first index request got a 403 from the sandbox egress proxy (allowlist not yet live), not from the county; the engineer retried once. Fetcher must tell proxy CONNECT refusals apart from server 403s (B1).
- Private preview artifact: https://claude.ai/artifact/QkxSRXNSMiWXpHUoLj8ynj (v1 draft with 11 meetings, published from build/publish/index.html + build/site files; republish same path).

## Decisions (Brian, 2026-11-07 3:54 PM ET)
- Unverified roll calls are no longer held back. They are shown with an asterisk, "not confirmed", and a link to the exact PDF page. Totals split confirmed and unconfirmed. Unmatched names are never guessed. Supersedes the hold-back display rule (P2 still decides "confirmed"); G4 skew check still reported.

- Brian 2026-11-07 4:47 PM ET: unconfirmed roll calls show NO vote value, link only (card). SHOW_UNCONFIRMED_VALUES stays False.

- 2026-11-07 ~5:25 PM ET: preview republished (version 2) at https://claude.ai/artifact/QkxSRXNSMiWXpHUoLj8ynj: visual refresh, 64 meetings 2020-02-10 to 2026-05-11, link-only unconfirmed roll calls, public data export. QA at 95e1235: 20/20 spot check, site checks pass, CEO decision holds; FAIL only on AC-P1 (82.3% verified < 90%), which gates public launch, not the private preview. Next: raise verified rate (backend; start with outcome_consistent failures, e.g. rc-09962951-p101-1), then M1.5.

## Next after votes (Brian, 2026-11-07 5:32 PM ET)
Once votes and voting records are done: finance. Revenue and expenditures, who got contracts and for how much, capital projects, and links to every related city and county document. Goal in his words: give residents "every opportunity" to dig in themselves. The site stays neutral: data, totals, source links and open downloads, never accusations. This is M2 (budgets/finance) + M3 (contracts) + capital projects; product-manager to fold it into the spec when M2 starts. Known gap: county minutes don't name vendors; award sources (Bonfire, purchasing archive, budget books, comptroller audits) still to verify.

## Design constraint (Brian, 2026-11-07 5:38 PM ET)
Keep in mind while coding: a possible future free app where anyone enters a ZIP code and gets the same (or configurable) information for their locality. Do NOTHING toward it now; just avoid hard-coding Clarksville/Montgomery assumptions where a config value or per-source adapter costs the same (body names, rosters, URLs, branding text in config, sources as adapters). Reviewers flag new hard-coding.
- 2026-11-07 ~5:40 PM ET: preview v3 published (dropdown menus, collapsed years, Esc/outside-click close). UX pass reviewed (approve after delta).

## UX direction (Brian, 2026-11-07 5:54-6:00 PM ET)
- Landing is one screen: a map of the county commission districts and city wards. Clicking a seat shows everyone who held it and how they voted.
- Search must have filters, because people will search for rezoning applicants.
- The menu reserves space for Finance and Capital projects. A finance-over-time chart explorer (county against city and other counties) comes later.
- The main menu is a top-left navigation drawer.
- Current members are shown apart from former ones, and every name carries a seat label (District N, Ward N, Mayor).
- Footer reads "Provided as a free service by Brian Zacharias." The Buy Me a Coffee link stays in config and is empty until Brian sends his page URL. The ethics check (G6) runs before the link goes public, because he sits on Council until January.
- Manager decisions on the design questions: Q3 uses a first-party JSON search index (no Pagefind yet, to keep under the file budget). Q6 amends N6 to allow first-party static scripts. Q10 orders current officials by seat number. Q9 skips the focus group while the site is private.
- Map source: the GIS hosts are blocked by the sandbox egress, and the allowlist prompt failed twice and was dropped. Boundaries are extracted from the county's own vector redistricting PDFs on mcgtn.org.
- 2026-11-08: the county district map is traced from the county's own vector PDF (Redistricting20211018.pdf), with numbers 19 and 20 swapped per the 2021-11-08 amendment. The swap was verified against the 2026 roster and the per-district maps. City wards are unavailable: the city PDF is raster. The fallback is the APSU layer once that host is allowed.
- Open parser finding (item-history family, 3rd hit): the 2024-09-09 minutes on p50 reprint the 2020 roll call for item 20-9-14 as an exhibit. It is filed as a 2024 unverified roll call. The architect must restate the invariant before the fix (loop rule). Seat derivation uses verified roll calls only, so seats are unaffected.
- Backlog (from frontend, 2026-11-08): rezoning items (CZ-) before 2026 carry only the case number as their title, so searching by applicant name finds only the newer ones. backend-engineer to pull applicant and street from the item text. This is the owner's named search use case.
- 2026-11-08 manager decisions: a name on a date with no roster record is labelled "seat not recorded". Seats are published as seats.csv. Zoning codes are not glyph-corrected (misread codes stay null).
- Open parser finding (item-history family): the 2024-09-09 minutes on p50 reprint a 2020 roll call as an exhibit, and it is filed as a 2024 unverified roll call. The architect must restate the invariant before the fix.
- 2026-11-08: the independent-readings rule took verified roll calls to 351/390, exactly 90.0%. It passes AC-P1 with no headroom. Manager decisions: a lone "-" beside a vote stays non-malformed, because the invariant does not list it (counting it would give 0.846). The reprint gap is queued for the architect: a printing held only because of its tesseract reading does not veto a reprint of the same table.
- Next to win back headroom: the mid-row district-token misread (rc-84fcd6d8-p70-0) and the tesseract-garbled stated tallies (6 roll calls).
- 2026-11-08 ~9:50 PM ET: preview v4 published at https://claude.ai/artifact/QkxSRXNSMiWXpHUoLj8ynj (map landing, drawer, seats, search, rezoning fields, public build, review.html removed). It was built from data/facts.json at d251fcb with sitegen plus collector.export; the publish recipe is build/publish/index.html (head/body stripped) plus a files map of build/site/*.
- 2026-11-08 manager decision: apply the independent-readings rule fully, including dissent from reprints, even though the verified rate drops to about 0.890, below the AC-P1 gate. The gate only blocks going public, not the private preview. Headroom is to be won back only by more correct readings, never by relaxing checks.
