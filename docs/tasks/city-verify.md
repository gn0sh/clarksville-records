# Tasks: city-verify (raise the city's verified rate without loosening a check)

Architecture: `docs/architecture/city-council.md`, "Verified-rate plan" (M1, D1, W1, W2, tests, estimate, launch
treatment). ADR 0005. Tests run in session (`python -m pytest -q`); paste the output in the PR. Fetches use only the
collector's PoliteFetcher.

| Task | Owner | Depends on | Parallel |
|---|---|---|---|
| V1 D1 listing: City Council Special Sessions under "General" | backend-engineer | none | yes |
| V2 W1 format characters in the city reader | backend-engineer | none | yes (city_minutes only) |
| V3 W2 break-free key (path N9) | backend-engineer | none | yes (city_build resolve paths) |
| V4 M1 `members` entry (path N10), Claunch entry | backend-engineer | V1 (stores fileId 3068) | after V1 |
| V5 Held-reason sentences per check, About page rate | frontend-engineer | Brian's launch decision (A or B) for wording on About; sentences can start now | yes |
| V6 Rebuild, report, review | backend-engineer, then code-reviewer (opus/high: name resolution), qa-engineer | V1-V4 | no |

- **V1** Done when: discovery also lists `General` / `Special Session` events from 2024-01-01 and keeps one only when
  page 1 prints "City Council - Special Session"; the 2026-02-11 meeting is built (2 roll calls); skipped events are
  named in the run report; the D1 tests pass.
- **V2** Done when: the W1 tests pass, including the real 2020-10-01 page 1 boxes; "J eff Henley" no longer appears in
  facts; county and RPC facts unchanged byte for byte.
- **V3** Done when: the W2 tests pass, `assert_name_invariant` checks `break_free` equality for every N9 match, and
  `build/city-report.json` has `word_break_matches`.
- **V4** Done when: `members` is parsed and refused per the config check; the `member_cited` build check passes for the
  Claunch entry; the M1 tests pass; Ward 2's seat starts 2026-02-19 with its source; the member page shows the name
  source line; schema gains optional `officials[].name_source`; `officials.csv` carries it with provenance.
- **V5** Done when: each held city roll call shows its check's sentence (table in the architecture doc), the same for
  every member, and site_checks pass.
- **V6** Done when: the data regression test lists the roll calls that changed (expected about +66 verified; D1 adds
  2 roll calls), no verified vote changed, the city report states the new rate, and review and QA (AC-P2 sample with at
  least 3 word-break matches and the Claunch meetings) pass.

Order: V1, V2, V3 and V5 in parallel; V4 after V1; V6 last.
