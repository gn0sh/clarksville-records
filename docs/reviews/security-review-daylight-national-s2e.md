# Security review S2e: national-isolation v3 fixes, a8c5430..e6172fe

Reviewer: security-engineer (opus/high), 2026-11-20. Read-only at e6172fe; probes in scratch worktrees (removed).
Scope: D-ISO-16/17 (daily-update.yml, national-update.yml, schema/daylight-upcoming.schema.json, collector/national/run.py)
and B-ISO-12..15 (sitegen/national_copy.py, qa/site_checks.py, site/templates/digest/body.html.j2).

**Verdict: PASS WITH FINDINGS** (no critical/high/medium; one LOW). **Release: OK WITH FOLLOW-UPS**; finding 1 before
`national.enabled: true` with a collected Legistar entry.

Evidence: national_isolation/copy/workflow 351 passed; digest_site_checks 55 passed; with fetch-data, national_pages
real-data tests pass. Fixture builds a8c5430 vs e6172fe identical (switch off, and switch on with shipped config). Real
records-data build switch on (30a1dd06): digest/feed-text, provenance, dates/no-raw-utc-day, brand, digest/csp pass;
place-4715160.html 45 sections all matched by FEED_SECTION. Four unrelated failures (sources, rpc-export, unverified,
feeds) came from the partial local invocation without RPC/finance inputs, on pages this diff doesn't touch.

## Findings
1. **LOW `national-isolation/copy-step-raises-on-input`** (sitegen/national_copy.py:181-186, `not in ours` at :185).
   `title_ours: true` with a list/dict title passes clean_feed/bind_feed, then raises `TypeError: unhashable type`
   outside copy_feed's try blocks. Proven directly and in a full switch-on build: build `built`, page stale, warning
   `place-4799990: adapter-error (TypeError)` instead of `bad-file (TitleNotOurs)`. Breaks the "never raises" contract and
   misdirects on-call. Tier 1 (national_pages.py:452-458) catches it: Clarksville not held, no text leaks (type name only),
   digest checks equal baseline; row-12 invariant holds. Fix (backend): refuse when `title_ours is True and not
   (isinstance(t, str) and t in ours)`; add `[]`, `{}`, `["Meeting"]` to the B-ISO-12 parametrize expecting
   `bad-file (TitleNotOurs)`. Counting (judgment, high confidence): nit-level hit, not a third row-6 break.

## S2d status (re-confirmed)
- Finding 1 `feed-value-outside-wrapper`: closed. Hostile title_ours titles (brand colours, marks, "MEETING", "", None,
  numbers, True) -> bad-file (TitleNotOurs); zero-width/soft-hyphen/padded "Meeting" cleaned to "Meeting"; non-boolean
  title_ours -> SchemaRefused; unknown platform fails closed. checked_at 05:59:59Z (17th Chicago) -> bad-instant, 06:00Z
  copied; non-string -> SchemaRefused, no raise; epoch copied, prints no day. Load phase refuses host_ok.date <=
  lines_effective, covering both provenance-banned days.
- Finding 2 `exemption-blanks-own-text`: closed (outside `<p>` and footer untouched; inside-section values blanked; 15c/15d).
- Nit a: closed (duplicates, swaps, empty vs non-empty, prefix refused; symmetric normalisation; greedy earliest match is
  the right subsequence test; meeting_view keeps order).
- Nit b: closed (exact rule in all five copies; BODY_FILE_RE fullmatch + id_layer; real grep -zacE probes accept all six
  shapes and the cache path, refuse wrong lengths, unknown layers, `.json/x`, `.jsonx`, `Xjson`, newline, `../`; push
  validate gives ::error:: rc=1 on real trees). ID_RE and national.js keep `{5,10}` but also check per-layer length.
- Nit c: closed (empty `$src` prints the pinned text and continues; `$c` 40-hex checked).

## Probes on the blanking scope (all hold)
- Forged `</section><section class="digest-meeting">...` in title, time, status, item number and text: autoescaped,
  exactly one opening per meeting, all checks = baseline.
- Attribute injection via URLs (`">`, `'>`, `?</section>`, %-encoded): refused by allowed_url/https_link; label_html
  escapes href via Markup.format.
- No nested section in templates (if one existed, early lazy end leaves text unblanked = safe). Every data-feed in
  body.html.j2 (:31, :32, :48) is inside a section; a span outside is read raw and fails check (iv).
- Template change is a Jinja comment only.

## Checked and holding
- No new `${{ }}` in run: (every step parsed); permissions, timeouts, continue-on-error unchanged; `$'...'` quoting intact;
  `(sdu|sds|sde)` valid ERE and bash `=~`; lookup jq filter unchanged and pinned.
- S2d "Checked and holding" list still holds (FEED_SPAN bare spans, now section-only; own_text scope; gov_json_of;
  binding fails closed; feed_json_without_text unchanged; bad-file prints id/word/type only; D-ISO-10 by test).
- Not a finding (pre-existing): schema body.id pattern under re.search accepts a trailing `\n`; bind_feed overwrites
  body.id from the directory.
- Observation (pre-existing, out of scope): when `gh attestation verify` exits non-zero, that commit gets no per-commit
  line; only the final "No national-data commit ... attested" line prints.

## Ledger keys
`national-isolation/copy-step-raises-on-input` LOW (backend; nit-level hit). Closed: feed-value-outside-wrapper,
exemption-blanks-own-text, S2d nits a-c. No new hit in national-budget or data-prov. Security delta re-review enough.

## Delta re-confirm (d57de26..4a44508), 2026-11-20
**Verdict: PASS.** `copy-step-raises-on-input` closed: title_problem checks `isinstance(title, str) and title in ours`
before the frozenset lookup. Probes via copy_feed with title_ours true: lists (`["x"]`, `["Meeting"]`, nested, `[]`),
dicts (`{"a":1}`, `{"Meeting":1}`, nested, `{}`), scalars (5, None, True) each give one warning
`bad-file (TitleNotOurs)`, no raise; control "Meeting" copied. A str subclass with a raising `__hash__` can only be built
in-process (json.loads and clean_feed return plain str): not a finding. Tests 204 passed. No workflow/template/qa change
in range. Release: OK; carried gates unchanged.
