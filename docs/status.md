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
| 2026-11-08 | code-reviewer | opus/high | delta re-review of 42d763e | approve with nits: glyph-scope, narrow-pattern-drops-veto, schema-printed-null |
| 2026-11-08 | backend-engineer | opus/medium | 3 review nits | done, 98e6b21: 354/390 kept, 502 pass |
| 2026-11-08 | qa-engineer | sonnet/medium | verify b983bfb | PASS: 508 pass, site_checks PASS all (44,100 name links, row-height 4 widths); process/offline-build-clobbers-facts (low) |
| 2026-11-08 | code-reviewer | opus/high | fresh review frontend pass + nits at b983bfb | request changes: must-fix provenance/vote-on-rule-unpublished, parse-accuracy/narrow-pattern-drops-veto (staff pattern, repeat); nit suffix-swallows-range; should-fix neutrality/unconfirmed-vote-on-untested, perf/clamp-layout-thrash |
| 2026-11-08 | backend-engineer | opus/high | review fixes at b983bfb (all acreage patterns listed first) | done, 24dfba7..ccf6f95: label-bounded values rule + consumer list; 13 zoning fields published, 5 vetoed; 560 pass; 354/390 |
| 2026-11-08 | code-reviewer | opus/high | fresh review c2dda39..ccf6f95 | approve with nits: should-fix parse-accuracy/suffix-swallows-unit (latent, no data) |
| 2026-11-08 | backend-engineer | opus/high | suffix must hold a sign mark | done, 8e5fe69: 564 pass, no data change |
| 2026-11-08 | code-reviewer | opus/high | delta re-review 8e5fe69 | approve; latent nit: hyphenated unit word ("sq-ft") still a suffix |
| 2026-11-08 | frontend-engineer | sonnet/medium | name links site-wide + table row heights + not-confirmed chip + vote-on label | done, 8a50f58: 44,100 name links checked; row-height check at 4 widths; final full suite and site_checks not re-run after last tweak |
| 2026-11-08 | code-reviewer | opus/high | delta re-review of landing fixes | approve with nits: a11y-headings/officials-sections; provenance/acreage-not-as-printed (3rd provenance hit, fresh review next); provenance/open-run-latest-mismatch (latent) |
| 2026-11-08 | qa-engineer | sonnet/medium | re-test landing bugs | PASS all; site_checks PASS incl. layout, provenance |
| 2026-11-08 | frontend-engineer | sonnet/medium | GoVoteTN lookup line | done, 1d2fe84; review approve with 3 nits |
| 2026-11-08 | backend-engineer | opus/high | georeference district map (pin M1) | done, 187d5a4: 575 pass, held-out max 4.5 m |
| 2026-11-08 | frontend-engineer | opus/medium | address pin M2 (box, georef.js, Census JSONP) | done, b470a4f: 614 pass, site_checks PASS; live geocoder untested (blocked here) |
| 2026-11-08 | code-reviewer | opus/high | address pin 1a54ff0..8233541 | request changes: addr-pin/ambiguous-match, addr-pin/privacy-copy-not-config (medium); n6/jsonp-is-third-party-script, live-endpoint-unverified, geocoder-margin-judgment (low) |
| 2026-11-08 | security-engineer | opus/high | address lookup 187d5a4..8233541 | pass with conditions: third-party-script/jsonp-runs-in-origin (medium, public gate), no-csp, privacy/promise-incomplete, privacy/preview-csp-report, qa-guard/addr-config-silent-miss (low) |
| 2026-11-08 | frontend-engineer | opus/high | address pin review + security fixes (sandboxed iframe, CSP, ambiguity) | done, 468e27b: 636 pass, site_checks PASS both builds |
| 2026-11-08 | security-engineer | opus/high | fresh re-review 8233541..5fc4e82 | PASS; gate jsonp-runs-in-origin cleared (Chromium); low: srcdoc-csp-safari-unverified, frame-src-guard-unpinned, hostile-answer-freezes-tab (accept, document), dead-code |
| 2026-11-08 | code-reviewer (API agent.py) | opus/medium | delta re-review of address pin fixes | approve ($0.35; pytest not runnable in the API sandbox, node checks 8/8); nit: 20-match boundary untested |
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
| provenance | 4 (review 11-08 x2, delta, fresh b983bfb): invariant stated (2c9dba6); fresh review on next fix | derived-count-shown-as-stated, derived-seat-dates-shown-as-term, acreage-not-as-printed, open-run-latest-mismatch, vote-on-rule-unpublished |
| parse-accuracy | 3 (review 11-08, rezoning review, fresh review d251fcb): invariant stated e9c7502; implementation miss #2 of the re-plan at b983bfb (sibling staff-acreage pattern left out of the consumer list): every pattern consumer must now be listed before the fix; FYI to Brian, no ask | narrow-pattern-drops-veto, suffix-swallows-range, verified-rate, combine-ignores-unclean-dissent, outcome-crosses-clause, two-thirds-majority |

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
- Queued for the architect: a rule for glued title words ("ofthe"; 61 titles). Neither engine sees the break, so the shown-form rule can't fix it. Also queued: whether derived coverage.from/to may use "from/to" wording.
- Queued (Brian, 2026-11-07 10:48 PM ET): address search that drops a pin on the map and names the district. Plan: Census geocoder client-side with a privacy note, plus georeferencing the PDF-space map with control points. Starts after the table fixes.

- 2026-11-08 ~late evening ET: preview v5 published at https://claude.ai/artifact/QkxSRXNSMiWXpHUoLj8ynj from 8e5fe69 (name links everywhere, compact tables with Show more, Vote on label explained on About, stricter acreage reading). site_checks PASS (159 files). Queued: GoVoteTN link, address pin (Census JSONP + georeferenced map, docs/research/address-lookup.md), latent nit suffix-swallows-unit (hyphenated unit words).
- 2026-11-08: GoVoteTN lookup line merged (1d2fe84, review approve with nits: config-comment/orphaned-support-note, landing-config/hardcoded-link-text, test-adequacy/qa-allowlist-untested) and published as preview v6 (index only). Link sits above the fold at 375x667 and 1280x800 (manager check). Address pin M1: backend-engineer georeferencing the district map (opus/high).
- 2026-11-08: address pin M1 merged (187d5a4): State Plane + affine fit, 7 county-corner control points from USGS National Map TIGER (Census hosts blocked by sandbox proxy), held-out max 4.5 m, boundary_margin_m 100. Unverified: Census geocoder accuracy/JSONP (unreachable here); artifact preview likely blocks census.gov script, so the pin must degrade to the GoVoteTN link there. M2 (UI + JS port) with frontend-engineer (opus/medium).
- Public-launch gates added 2026-11-08: (a) JSONP isolated in an opaque-origin sandboxed iframe plus a meta CSP, re-checked by a fresh security review at opus/high; (b) decide the public hosting origin (not a shared github.io origin with other gn0sh sites); (c) one live Census lookup checked on a device once the site is hosted outside the claude.ai preview. The preview is built with no address box (the preview sandbox blocks census.gov), so it shows only the GoVoteTN line.
- 2026-11-08 1:25 AM ET pacing (coordinator): one subagent at a time; self-contained work (QA re-checks, tests, docs, non-security reviews) goes through gnoshcodes scripts/api/agent.py (Sonnet for routine). Security reviews stay in-session.
- 2026-11-08 ~2:30 AM ET: preview v7 published from 5fc4e82, built with `sitegen --no-geocoder` (no address box; GoVoteTN line only) and CSP meta stripped from the preview copy (build/preview) because the claude.ai host has its own sandbox; site_checks PASS on build/site first. Queued (low): frame-src-guard-unpinned + dead-code (backend), hostile-answer-freezes-tab note (docs), 20-match test, suffix-swallows-unit hyphen nit, srcdoc-csp-safari-unverified (with gate c). agent.py needs bubblewrap + socat (installed with apt this session).
- 2026-11-08 ~1:45 PM ET: low follow-ups merged (0e0ece9; API agent.py sonnet, $0.15; 164 targeted tests pass; offline run in the backend worktree leaves facts.json unchanged at 354/390). API month to date $161 of $170, so the next worker tasks run in-session.
- HANDOVER (thread near the 250K context limit): the votes milestone, landing UX and address pin are done and reviewed. Preview v7 is at https://claude.ai/artifact/QkxSRXNSMiWXpHUoLj8ynj; the publish recipe is `sitegen --no-geocoder`, then export, then copy build/site to build/preview with the CSP meta stripped, then build/publish/index.html (head/body stripped) plus the files map. Next phase: finance and contracts (M2/M3: revenue and expenditure, contract awardees and amounts, capital projects, links to every source document; neutral). Still queued: architect rulings (glued title words, coverage.from/to wording, item-history exhibit reprint), M1.5 correction intake plus security review, and public-launch gates (G6 ethics check, hosting origin, a live Census check on a device including Safari CSP, AC-P1 already passes). City wards are still blocked (raster PDF only).

## Finance and contracts phase (thread "Add finance and contracts to records site", started 2026-11-08)
- Sources verified 2026-11-08 (platform-facts, last section): two budget books with text tables; purchasing archive table of 91 solicitations (2025-2026), 32 text bid tabs, award letters are scans; Bonfire robots disallows all (link only).
- Spec docs/specs/finance-contracts.md (774a31e). Brain Trust (3, sonnet) docs/reviews/brain-trust-finance-contracts.md changed the plan: slice 1a "Bids and awards" with values only from text bid tabs (no OCR values), slice 1b budget books + capital fund; no cross-solicitation or county-wide sums.
- Now: software-architect (opus/high) and ux-designer (sonnet/medium) in parallel. API credits nearly spent, so workers run in-session.
- Run ledger: 2026-11-08 product-manager sonnet/medium spec v1 + BT fold-in: done | brain-trust x3 sonnet/medium: devil, resident, finance; all critical, plan changed (see table).
- 2026-11-08 evening: architecture (ADR 0002, tasks F0-F15) and design merged; F0 schema+fixture, F1-F5c collector (live fetch, polite, no blocks: 90 archive rows, 295 documents, 53 scanned), F6-F7 Bids and awards pages merged (257faf5, 886 tests pass). Only 5 of 56 bid tabs read as lump-sum; widening now. Slice 1b budget reader running in parallel.
- Fixed in passing: tests/test_address_box.py referenced ADDR_CONFIG removed in 0e0ece9 (2 failing tests since the last thread); fixed in 7dd4c82.
- Queued for frontend after widening: coverage sentence must use the live scan count (28 of 70 award letters have text); cite bid/award dates (schema page field); held-path indexing; raise MAX_FILES (91 contract pages); confirm new fixed wording in config/finance_text.yml with design.
- Run ledger: architect opus/high design: done (subtotal rounding finding: 410 exact, 99 within $1-4, 6 off) | ux sonnet/medium design: done | backend opus/medium F0: done | frontend opus/medium F6-F7: done, 33 tests | backend opus/high F1-F5c: done, 12 commits, +1324 source lines (over the 900 estimate).
- 2026-11-08 4:26 PM ET pacing (usage thread): weekly usage 91%; ONE subagent at a time from now. Two were already running (frontend fixes, 1b delta re-review); no new spawns until both finish.
- Review reports 1a and 1b (opus/high): REQUEST CHANGES; all backend findings fixed in f0b7bdb (1b: p103 scope-class fix; FY2025 kind override recorded in ADR 0002). AC-F4 award-letter agreement deferred to slice 1a.2 (manager decision).
- 2026-11-08: slice 1a delta re-review APPROVE WITH NITS (118b5e5); slice 1b budget delta re-review APPROVE (f0b7bdb). Next (one agent at a time): frontend F13/F14 budget + capital pages with the held-sentence fix and MAX_FILES 500; then QA spot check; then preview v8.
- Run ledger: code-reviewer opus/high 1a: request changes (1 must, 5 should) -> delta approve w/ nits | code-reviewer opus/high 1b: request changes (1 must, 4 should) -> delta approve | backend opus/high widen: 5->16 tabs | backend opus/high 1b F9-F12: done | backend opus/high review fixes: 12 fixed | frontend sonnet/medium 1a fixes: done.
- 2026-11-08: QA (sonnet/medium) PASS WITH MINOR ISSUES (a15bf8c): 0 of 30 spot-check mismatches; full sweep of all 3,846 budget rows and 80 bid-tab rows: 0 mismatches; 24 hand-labelled solicitations. Bugs: B1-B3 note wording (frontend, fixing now), B4 parity by department is near-vacuous because department is known only from a read tab (known limit, product-manager to revisit in 1a.2), B5 doc fixed. Danger noted: `collector run --offline` without the minutes PDFs overwrites data/facts.json; backend to guard it (queued, key provenance/offline-run-overwrites-facts).
- 2026-11-08 ~6:00 PM ET: preview v8 published at https://claude.ai/artifact/QkxSRXNSMiWXpHUoLj8ynj (artifact versions 8-9, two publishes because of the 255-files-per-call limit) from 3d wording merge on top of 94397ba: Bids and awards (90 solicitations, 16 bid tabs read), Finance (7 fund pages, both budget books, 3,846 lines), Capital projects, glossary. site_checks PASS (263 files). Old finance.html and capital-projects.html removed. Note: the artifact reports sharing "Anyone with the link" (unchanged by us); asked Brian whether to restrict it.
- Next (queued, one agent at a time): F8/F15 exports (flip EXPORTS_READY), slice 1a.2 (unit-price tabs, award-letter agreement AC-F4, department from archive titles for parity), guard `collector run --offline` from overwriting facts.json, contract-to-commission-vote links (stretch). Waiting on CEO: AC-F17 usefulness test (find 3 contracts by vendor), batched with his next check.
- 2026-11-09 ~7 PM ET (Nov 8 local): Brian asked for a note explaining each total that doesn't add up. Done (frontend sonnet/medium e8b6af8/c6e008a + manager wording tweak): per column, printed total, sum of lines, and 'The printed total is N higher/lower'; no-lines and within-rounding cases worded. site_checks PASS; republished as artifact version 10.
- 2026-11-09: Brian (relayed by coordinator): council seat is not a factor. Dropped the council-ethics hold: Buy Me a Coffee footer link enabled (support_enabled true), per-page operator disclosure requirement removed from the finance spec; G1 footer stays. Remaining public-launch gates: correction intake, hosting origin, live Census check.
