# PR #62 review, T0-T4 (city-only site), commit 54088d37

## code-reviewer (opus/high): approve with nits
Ran T0-T4 tests (200 pass), full suite (5879 pass, 5 skipped), and the real-data build (`data/facts.json`, 684 files) at base, head and head `--city clarksville-tn`: `diff -r` empty both ways. T0 digests stable across RECORDS_TODAY values.
1. should-fix `city-only/denied-host-never-linked`: site-file URLs (primary.record.url, seat_basis.url, unofficial.bodies[].url) not checked against denied hosts (cities/registry.py `_check_primary`).
2. should-fix (process) `city-only/clarksville-identical`: PR body lacked the real-data diff; T0 builds skip finance/RPC/agendas/committees; assert county path constants.
3. nit `city-only/no-county-leak`: RECORDS_SITE_URL overrides a new city's alerts.site_url (T6).
4. nit: two PRIMARY_KEYS constants differ (sitegen/config.py vs registry).
5. nit: "city None" error text; `--city=` empty falls through.
6. nit: PLACE_NAME_RE rejects apostrophes.
7. nit: T0 test doesn't clear RECORDS_SITE_URL / DAYLIGHT_CITY.

## security-engineer (opus/high): OK with follow-ups (no critical/high)
1. MEDIUM `city-file/unlocked-trust-keys`: a city file can set corrections.github_repo, analytics.code, geocoder_url, alerts.site_url. Fix: allowlist of city-owned keys.
2. LOW `city-file/path-outside-city-dir`: site_file, corrections_log, locality accept absolute paths and `..`.
3. LOW `city-file/regex-dollar-newline`: `.match` + `$` accepts a trailing newline.
4. LOW `fetch-host/trailing-dot-denied`: trailing-dot hosts miss DENIED_HOSTS (still refused by the allowlist).
5. LOW `sitegen-city/deploy-not-pinned`: Pages build doesn't pin `--city`; add a guard that `pages` refuses a non-live city. Workflow pin is a follow-up for the ADR 0011 owner.
Checked and holding: brand keys locked, YAML safe_load, fetch order unchanged, slug can't escape config/cities/, place_name escaped.
