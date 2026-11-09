# Launch test plan: clarksville-records (Fri 2026-11-13, everything launches together)

Written by qa-engineer 2026-11-09; manager decisions on spec gaps at the end.
Scope: County, City Council (Agenda Center 2016 to May 2024 plus CivicClerk 2024+), finance/bids, exports, correction intake, Atom alerts, gnoshcodes branding, transcripts, GitHub Pages at records.gnoshcodes.com with a daily update. Definition of finished: docs/plan/one-week-finish.md.
Reuse, do not duplicate: cases already passed are referenced and re-run only as the regression pass in section 1.
- M1 plan: docs/qa/m1-test-plan.md (AC1.x, AC2.x, AC4.x, AC6.x, AC7.x, P*, N1-N6, G1-G7)
- Finance plan: docs/qa/finance-contracts-test-plan.md (AC-F1 to AC-F17)
Kinds: A automated, S script, M manual. BLOCK = failure blocks launch. "NEW" = case/test to be added. Verdict: PASS, PASS WITH MINOR ISSUES, FAIL; a PASS lists what was tried that could have failed.

## 0. Setup (launch SHA, clean worktree)
1. `git worktree add --detach <path> <sha>`; install; record `git rev-parse HEAD`.
2. `python -m pytest -q` (all green, no new skips), `python -m qa.site_checks` (all PASS), build the Pages copy.
3. Random samples use seed 20261113 and are listed in the report.
4. Widths for every visual check: 375, 768, 1280, narrow side panel 360. No horizontal scroll, no clipped/overlapping text, usable tap targets. Extend `site_checks hscroll` to 375/768/1280 (NEW); sample 3 pages per page type.

## 1. Regression of existing gates (BLOCK)
| Item | AC | How | Pass rule |
|---|---|---|---|
| County votes, attendance, items, collection | AC1.x-AC7.x, P1-P4, G4 | m1 plan final pass on the launch build | all prior PASS rows still PASS |
| Finance, bids, budget | AC-F1..F16 | finance plan setup + site_checks + test_fin_pages, test_budget_pages, test_finance_schema | no regression; AC-F1 re-sample 30, 0 mismatches |
| Verified rate | AC-P1 | build/report.json gates.verified_rate per body | County >= 90%. City: see decision 1 |

## 2. City Council votes (BLOCK)
| ID | AC | How | Pass rule |
|---|---|---|---|
| C1 | AC-P1 (city) | report.json per source | counts reported per source; held facts never shown as votes (tests/test_held_counts.py) |
| C2 | AC-P2 (city) | qa.spot_check: 20 Agenda Center (>=4 members, >=4 years) + 20 CivicClerk (>=4 members, >=2 years) vs source | 40/40; a mismatch blocks, rule fixed, re-sampled |
| C3 | AC-P3 (city) | collector/tests/test_verify.py hand-labelled set has >= 15 city roll calls (absence, abstain, recusal, odd layout) (NEW if not) | zero wrong votes |
| C4 | AC1.5, N1 | test_site_neutrality, test_council_pages: two members' pages identical skeleton | identical except data |
| C5 | Name-resolution invariant | test_council_pages + M: 10 ballots with a shared surname or titled non-member | no vote credited to the wrong person; run on a SHA after the fresh re-review of the titled-nonmember fix |
| C6 | Page numbers | 10 random city votes, `#page=N` lands on the roll call | 10/10 |
| C7 | Coverage sentence | exact-string check on city index | states meetings, years, Agenda Center vs CivicClerk |

## 3. Neutrality (BLOCK)
| ID | How | Pass rule |
|---|---|---|
| NE1 | Banned-word scan (finance plan list + best, worst, top, rank, score, grade, rating, most, least, often, tends, controversial, supports, opposes) over all rendered text incl. transcripts, alerts, About, excluding quoted source text | 0 hits outside quoted source; every hit inspected |
| NE2 | tests/test_site_neutrality.py + city equivalents | PASS |
| NE3 | Lists alphabetical by surname; no activity sort; no counts without denominator and date range | PASS |
| NE4 | Diff page skeletons of 3 random officials (2 county, 1 city) | identical structure |
| NE5 | Feeds/Alerts: item titles only, no editorial summary, no importance ranking (first 10 entries per feed) | PASS |
| NE6 | Transcripts: same layout for every speaker; no sentiment/summary text; call-on lists in time order only | PASS |
| NE7 | Footer/About: operator credit and support link are the only non-record content; no campaign link | PASS |

## 4. Source link on every fact (BLOCK)
`site_checks sources` tests 100%. Independent sample to prove the checker is not blind:
| Data type | Sample | Pass |
|---|---|---|
| County vote rows | 20 | 20/20 link resolves, page anchor valid, fetch date shown |
| City vote rows (both sources) | 20 | 20/20 |
| Attendance rows | 10 | 10/10 |
| Budget lines | 10 | 10/10 |
| Bid/contract rows | 10 | 10/10 |
| Transcript segments | 10 | 10/10 video link + meeting page link |
| Exported CSV/JSON rows | 20 | 20/20 source URL, page, fetch date non-empty |
NEW: build fails when any shown fact (county, city, transcript) lacks a link.

## 5. Vote attribution vs source PDFs (BLOCK)
C2 (40 city) + AC-P2 (20 county, re-draw) + AC-F1 (30 amounts). Adversarial extras: 5 votes by members with absences/recusals in the same meeting, 5 from 2016-2017 minutes, 5 from the newest CivicClerk meeting. One mismatch: stop, fix, re-draw same size.

## 6. Name-link rule (BLOCK)
Every official's name links to their vote history where the record shows the official acting; names inside item titles never link.
| ID | How | Pass |
|---|---|---|
| NL1 | Crawl; every official name outside item titles (rosters, attendance, vote tables, meeting pages, transcript speaker labels) is an `<a>` to that person; also test with an injected fixture (AC-F9 was vacuous) | zero unlinked |
| NL2 | Any official-page link inside an item-title element | zero |
| NL3 | 10 titles containing a member's surname (applicant with same name) | 0 links |
| NL4 | 10 shared names (county vs city, same surname) | 10/10 right person |

## 7. Downloads / exports (BLOCK)
| ID | How | Pass |
|---|---|---|
| E1 | collector/tests/test_run.py::test_export_contains_no_unverified_fact; held-leak fix 40ef363; city exports present | no held/unverified fact exported |
| E2 | Strict CSV parse, JSON parse; row counts equal page counts for 5 entities | equal |
| E3 | Formula-injection guard (security fix 1); NEW fixture with `=`,`+`,`-`,`@` cells | neutralised |
| E4 | UTF-8 round-trip of accented/apostrophe names | PASS |
| E5 | Every download link resolves, right filename/type, < 25 MB | PASS |

## 8. Correction intake (BLOCK)
| ID | How | Pass |
|---|---|---|
| R1 | tests/test_corrections.py; "Report an error" on every fact page type (county, city, finance, transcript) | 100% |
| R2 | Production, once corrections.github_repo is set: from a county vote, a city vote, a budget line, the issue form opens prefilled | 3/3 |
| R3 | One test issue (label `test`, closed after); Brian notified | arrives |
| R4 | No personal data beyond optional contact; no third-party script (tests/test_csp.py) | PASS |

## 9. Alert feeds (BLOCK)
7 feeds (county meetings, city meetings, 5 topics) plus Alerts page.
| ID | How | Pass |
|---|---|---|
| F1 | Offline: feedparser bozo=0 + xmllint; NEW RFC 4287 RELAX NG check (vendored) | 7/7 valid |
| F2 | feed id, title, updated, author, self link; entry id (unique, stable across rebuilds), title, updated, link | present; ids stable over 2 builds |
| F3 | alerts.site_url = https://records.gnoshcodes.com/ on production; absolute links on that host | no github.io/localhost |
| F4 | NEW fixture with control chars in a title | still valid |
| F5 | 20 entries per topic feed hand-judged; zoning checked against 10 known zoning items | >= 18/20; no empty feed (non-blocking if not misleading) |
| F6 | Alerts page lists feeds; autodiscovery `<link rel="alternate" type="application/atom+xml">` on index | PASS |
| F7 | 2 feeds in a real reader (Brian's phone batch) | renders (non-blocking) |

## 10. gnoshcodes branding and footer (BLOCK B1, B2, B5)
| ID | How | Pass |
|---|---|---|
| B1 | Footer on every page: credit "gnoshcodes" linking gnoshcodes.com; no operator mention of Brian in rendered HTML, feeds, exports, About (his name appears only as public-record council data) | 100% |
| B2 | About names gnoshcodes as operator; G1 tests updated, not deleted | PASS |
| B3 | https://buymeacoffee.com/gnoshcodes returns 200 (M, production) | 200 (non-blocking) |
| B4 | gnoshcodes.com card (gn0sh/gnoshcodes-site claude/records-product 78afcb4) links https://records.gnoshcodes.com/ | right |
| B5 | No Preview banner in the production build | PASS |
| B6 | Footer fits at 375 and 360 | PASS |

## 11. Transcripts with timestamp links (BLOCK T2-T4 for any transcript shown)
| ID | How | Pass |
|---|---|---|
| T1 | Per-meeting coverage: transcript, or "no transcript yet" (NEW exact-string test) | PASS |
| T2 | 20 random segments across >= 5 meetings: video starts within +/-2 s and words match | >= 19/20; wrong meeting blocks |
| T3 | Script over all JSON: valid `#t=` (MP4) / `&t=` (YouTube) form, integer seconds, no time > media duration | 100% |
| T4 | "Automatic transcript, may contain errors" label on every transcript page, links to video and minutes | same wording everywhere |
| T5 | Speaker names follow section 6; no attribution the record doesn't support | PASS |
| T6 | Size/file limits with transcripts (section 14) | within |
| T7 | 5 random 60 s windows read against audio | note findings; non-blocking unless a wrong named person |

## 12. Accessibility (BLOCK A1-A3)
| ID | How | Pass |
|---|---|---|
| A1 | axe-core via Playwright from a vendored axe.min.js on 12 pages (index, county/city official, meeting, item, finance fund, contract, alerts, about, report, transcript, 404) | 0 serious/critical |
| A2 | Keyboard drawer at 375/360: Enter/Space opens, focus moves in, Escape closes, focus returns, visible ring (M + NEW Playwright test) | PASS |
| A3 | Skip link, landmarks, one h1, table headers/captions, meaningful link text | PASS |
| A4 | Contrast >= 4.5:1 light and dark | 0 (non-blocking warnings) |
| A5 | 200% zoom at 375 | non-blocking |

## 13. Devices and widths (BLOCK)
hscroll + screenshots at 375, 768, 1280, 360 for landing, index, official, meeting, item, finance fund, contracts, capital, alerts, transcript, report, about. Long text clamped with Show more (AC-F10). Brian's phone check (batched): iPhone Safari on 3 pages plus one feed.

## 14. File count and size (BLOCK for Pages)
| Target | Limit | How |
|---|---|---|
| GitHub Pages | site < 1 GB, no file > 100 MB; report any page > 5 MB; > 10 MB HTML blocks | du, find -size |
| Repo | no large binaries; data/ < 500 MB | git count-objects -vH |
| Preview artifact | 500 files (MAX_FILES), 255/64 MB per publish | non-blocking after launch (decision 3) |

## 15. Daily job politeness (BLOCK J1-J4, J7)
| ID | How | Pass |
|---|---|---|
| J1 | collector/tests/test_fetch.py robots/delay + NEW per new host (CivicClerk, cpmedia.azureedge.net) | no disallowed path; crawl delay honoured, >= 10 s on clarksvilletn.gov |
| J2 | Workflow User-Agent is the fixed descriptive string, no browser UA, no person's name/email | PASS |
| J3 | test_fetch.py::test_403_or_429_stops_the_host | stops host |
| J4 | Two runs on a quiet day: second changes nothing | no diff |
| J5 | workflow_dispatch dry run on a branch: publishes only if site_checks passes; failure keeps the old site | PASS |
| J6 | Daily, off-peak, concurrency group; daily job fetches only new meetings' media | PASS |
| J7 | Offline guard: never overwrites facts.json when inputs are missing | PASS |
| J8 | Only GITHUB_TOKEN; minimal permissions | security-engineer confirms |

## 16. Post-deploy smoke (within 15 min of go-live; any fail = roll back)
1. https://records.gnoshcodes.com/ over HTTPS, valid cert, HTTP redirects; no Preview banner.
2. Landing at 375: no horizontal scroll.
3. One county and one city official page: votes with source links; one link opens the PDF at the right page.
4. One CivicClerk meeting with transcript: a timestamp plays at the right second.
5. Finance fund and contract pages load with coverage sentence.
6. Footer "gnoshcodes" credit and support link.
7. County-meetings feed valid, links on records.gnoshcodes.com.
8. Download one CSV and one JSON.
9. Report an error opens a prefilled issue.
10. About page, operator gnoshcodes.
11. 404 works; robots.txt as intended; no stray noindex.
12. DNS resolves; Enforce HTTPS on.
13. Add the site to gn0sh/gnosh-uptime monitor.config.json (devops).
14. Trigger the daily workflow once; it succeeds and the site updates.

## Launch blockers summary
Blocks: sections 1-3, 4, 5, 6, 7 (E1-E3), 8, 9 (F1-F4), 10 (B1, B2, B5), 11 (T2-T4), 12 (A1-A3), 13, 14 (Pages), 15 (J1-J4, J7), 16.
Non-blocking: F5 if not misleading, F7, T7, A4/A5 warnings, page weight 3-10 MB, B3 if the provider is down, preview limits.

## Manager decisions on spec gaps (2026-11-09)
1. City verified rate (82.4% Agenda Center, 78.6% CivicClerk) is below the county's 90% gate. Waiver: the city launches with the rate disclosed in its coverage sentence; held roll calls are never shown as votes. Reason: held facts are hidden, not wrong, so the gate's purpose (no wrong votes shown) holds; C2/C5 still block.
2. Pass rules invented by QA for exports, alerts, transcripts, branding and hosting are accepted as the launch ACs.
3. Preview limits stop blocking once Pages is live.
4. Transcripts launch with whatever meetings are done by Friday, each meeting stating whether it has a transcript. Tolerance +/-2 s.
5. NE6/T5 are the transcript neutrality rules.
6. Alerts page states that per-ward/district feeds are not available yet.
7. User-Agent and schedule come from the devops workflow (in progress); J2/J6 check it.
8. G1/G7 tests and the CLAUDE.md wording are being updated (branding task; CLAUDE.md fixed).
