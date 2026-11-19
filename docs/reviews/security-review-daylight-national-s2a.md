# Security review S2(a): Daylight Digest national collector (C1, C2, C3, C4, D3) @ 5139ae6

Reviewer: security-engineer (opus/high), 2026-11-19. Read-only. D1/D2 (workflows) reviewed separately later.
**Verdict: PASS WITH FINDINGS.** No critical/high. OK WITH FOLLOW-UPS; finding 1 must land before H1.
Tests: collector/tests/test_fetch.py, test_fetch_tenant.py, tests/test_national_{run,legistar,feeds,guards}.py: 522 passed.

## Findings
1. **MEDIUM `fetch/403-body-parse-escapes`** (2nd hit in family `fetch/403-body-*`, after `fetch/403-body-read-escapes`).
   collector/fetch.py:255-259 `_json_object` (called :500) catches only UnicodeDecodeError/ValueError. A 403 body of
   nested JSON (`[`*60000, within BLOCK_BODY_BYTES) raises RecursionError inside the HTTPError handler before
   `_blocked`/`_tenant_blocked` are set. Proven: next get to another tenant was sent and got 200. Breaks "a block stops
   the host". Fix: fail closed (catch Exception -> host block); test: nested 403 body stops host, zero further calls.
2. **LOW `collector-input/json-depth-recursion`**: same RecursionError gap at legistar_upcoming.py:350-353 (_get_json,
   harmless), :268-271 (_sweep) and :288-291 (_cache_get: one nested cache file fails that body forever),
   run.py:406-409 (_load_json: a nested health.json aborts collect()). Fix: treat RecursionError as unreadable.
3. **LOW `fetch/error-body-unbounded`**: fetch.py:513 and 5xx retry return: non-403/429 error returns `e.read()` with
   no cap (proven: 3 MiB returned with max_bytes=1024). Fix: `e.read(max_bytes+1)` + same size trip.
4. **LOW `privacy-withhold/items-event-unbound`**: legistar_upcoming.py:163-179, :448: item rows never checked against
   the requested event (`EventItemEventId` unread). A Legistar bug or same-tenant redirect to a withheld event's items
   would publish them under a shown body. Fix: drop/count rows whose EventItemEventId != event_id; a meeting with any
   such row is unreadable; optionally refuse redirects on webapi reads.
5. **LOW `cache-confine/prune-fail-open`**: run.py:357-361: prune failure sets cache_root=None and continues; a now
   withheld body keeps cache item text on disk and it gets pushed. Fix: prune failure fails the run.
6. **LOW `national/url-unbounded`**: national_guards.py:84-105 `allowed_url`, legistar_upcoming.py:365-368, :436: URLs
   from answers have no length cap; free-text path/query reach bodies/*.json and proposals, even for withheld bodies.
   Fix: cap at MAX_URL (2000) in allowed_url; consider Legistar URL shape allowlist. Architect: row 23 wording
   (proposal `observed` is a source status name, allowed by 3.7).
7. **LOW `national/r5-self-attested`**: national_guards.py:111-133: host_ok is structural only; any https link, future
   dates, and `date.fromisoformat` accepting `20261119`/`2026-W47-4` pass. Fix: strict `^\d{4}-\d{2}-\d{2}$`, date <=
   today, link host limited to github.com/gn0sh and claude.ai; code-review checklist: open host_ok.link for
   directory.yml diffs.
8. **LOW `national/tenant-redirect-uncapped`**: fetch.py:407-408: `check_tenant_redirect` applies only to capped
   tenants (proven: uncapped fetcher followed salem -> other). run.py always caps, so C3 holds; other callers don't.
   Fix: refuse any redirect that changes tenant_key regardless of cap.

## Needs verification in D1/D2
- Fetcher built with `allowed_hosts=("webapi.legistar.com",)` and `max_bytes=lu.MAX_RESPONSE_BYTES` (default is 40x).
- Fetcher log / exception text carries 200 chars of 403 body, Server and Location headers: never print to public CI
  logs or commit.
- `_kept_feed` (run.py:178-191) does not re-run clean_feed/allowed_url: D2 copy step must run clean_feed then bind_feed.
- ICS/Atom writers trust input: M4 passes only bound feeds.
- `check_data_root` doesn't check parent `data/`: D1 checks out national-data at a path it controls.

## Checked and holding
Shared-path grammar (C1) refusals; every redirect hop re-checked; no request built from answer fields; withheld
entries make no items request and keep no item text; path/symlink confinement with O_EXCL|O_NOFOLLOW + os.replace;
health/proposals ids/kinds/counts only; D3 check before any fetcher/file access in run, collect and read_body; C4 ICS
escaping, folding and Atom via ElementTree.
