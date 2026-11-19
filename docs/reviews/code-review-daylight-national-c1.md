# Code review: daylight-national C1 fetcher tenant rule (8f71812)
Reviewer: code-reviewer, opus/high, 2026-11-19. Verdict: APPROVE WITH NITS, findings 1-2 to land before H1.

1. should-fix `national/tenant-block-escape` (fetch.py tenant_key ~188-206; test_fetch_tenant.py:38): `/V1/salem/`,
   `/v1/%73alem/` and absolute `.../v1/ta/../tb/` redirects escape a tenant block or cap (proved by probe). Fix:
   case-insensitive `/v1/`; refuse (no request) any shared-host /v1/ path whose client has `%` or any dot segment.
2. should-fix `national/tenant-robots-host-block` (robots() ~482-500, _tenant_only_block ~472): robots.txt redirect to a
   tenant JSON 403 raises TenantBlocked, caches nothing, re-requests robots.txt every get(). Fix: robots() calls
   _raw_get(..., _tenant_ok=False).
3. nit `national/tenant-json-body`: UTF-8 BOM makes it a host block (fails safe); decode utf-8-sig.
4. nit handoff to C3 `national/tenant-caller-order`: catch TenantBlocked before HostBlocked.

Checked and sound: check order in _raw_get, second-tenant escalation, 429/robots/non-tenant/non-object JSON host blocks,
cap semantics, cross-tenant and cross-host redirect refusal, per-host delay and robots, unchanged non-shared-host behaviour.

## Delta 3974975 (resumed reviewer): APPROVE WITH NITS
Findings 1-4 fixed and hold (probe re-run). New:
5. nit `national/tenant-block-escape` (2nd hit): `//v1/salem/events` and `/%2fv1/salem/events` reach a blocked tenant
   (fetch.py ambiguous_tenant_path ~236). Loop rule: architect states the invariant first.
6. nit `national/tenant-robots-host-block`: robots() hop into a capped tenant raises RequestCapReached, nothing cached.

## Fresh review b8a89bf..479f874 (3rd-hit rule, new reviewer, opus/high): APPROVE WITH NITS
No route found to a blocked or capped tenant. Probe: scratchpad c1-fresh/probe.py.
1. should-fix `fetch/403-body-read-escapes` (fetch.py:482, pre-existing): a failing e.read() escapes before any block
   is recorded, so the next get() re-asks a host that said 403. Fix: catch OSError/HTTPException, empty body (fails closed).
2. nit `national/tenant-cap-redirect` (fetch.py:610-612 vs robots() 543-548): robots redirect chain can hop tenant to tenant.
3. nit `national/tenant-robots-host-block` (552-554): a tenant cap hit during robots caps every tenant for the run.
4. nit `national/tenant-block-escape` (shared_path :221): subdomains of a shared host skip the tenant rules.
   Related, for C3/H1: salem.legistar.com is not stopped by a webapi tenant block.
Decision (manager): fix 1-4 now; 3 -> only a host cap sets _robots_capped; 4 -> refuse subdomains of a shared host.
salem.legistar.com: C3 treats a webapi tenant block as stopping that city's other Legistar hosts too (note for C3).
