# QA Q1: Daylight Digest M1 vs spec v2.2 (1896a9e), 2026-11-19

qa-engineer, opus/high. **Verdict: FAIL** (2 major, 3 minor). Lookup privacy and behaviour held under every test (175 scripted checks, 3 fails = bugs below; targeted tests 592 + 19 passed; axe 0 serious/critical).
Setup: builds off, on (today 2026-11-19) and on with RECORDS_TODAY=2026-11-01; Playwright Chromium on a fake https origin; Census JSONP stubbed; Buttondown and GoatCounter stubbed (0 real requests).

| Criterion | Result |
|---|---|
| AC0.1 | PASS (partial: zoom approximated, no real screen reader) |
| AC1.1-1.8, 1.10 | PASS (only frame calls Census, no referrer; no address in any other request/storage/cookie/URL/title; timeout 15.4 s with Retry; error states) |
| AC1.9 | PASS (copy; Brian confirms facts) |
| AC2.1-2.10, 2.12, 2.13 | PASS |
| AC2.11 | FAIL minor (bug 5) |
| US3 | not in M1 (M4) |
| AC4.1-4.3, 4.5, 4.8-4.11 | PASS |
| AC4.4 | PASS (code path only) |
| AC4.6 | NOT MET, accepted deviation national-freshness/checked-at-is-first-fetch; spec must be amended |
| AC4.7 | FAIL (bug 1) |
| AC5.1, 5.6 | PASS |
| AC5.2 | FAIL minor (bug 3) |
| AC5.3-5.5 | Q2 / B12 |
| AC8.1-8.3 | PASS (off build has no digest/; on minus menu/front line equals off except static/pages.js) |
| AC9.1, 9.2 | PASS |
| AC9.3 | FAIL (bug 2) |
| AC12.1, 12.3 | PASS; AC12.2 count PASS, share M1.5 |

## Bugs
1. `national/topic-labels-missing` major: digest/tn/county-47125.html shows no topic labels; nothing in sitegen/national* or templates/digest mentions topics. No M1 task covers it.
2. `national/method-page-claims` major: with national on, method.html:64 still says "These two keys are all this site keeps in your browser" (digest adds 3 keys).
3. `national/mixed-form-labels` minor: Not-covered card + ticked Can't-cover government under "Also request" shows only the not-yet label (national.js openForm picks one label from the own card's status).
4. `national/official-url-not-meetings-page` minor: city `official_url` is the city home page but labelled "Official meetings page"; CMCSS "Official agenda page" points at cmcss.net home.
5. `national/new-england-town-slot` minor: spec puts New England towns in the city-or-town slot; UX doc puts them in township-or-town (Plymouth, MA).

Not tested: real Census answers; real Buttondown (no-cors post can't tell refusal from success, Q2); real screen reader; item text vs PDFs (compared to agendas.json).
