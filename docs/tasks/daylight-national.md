# Tasks: daylight-national

ADR 0013, architecture `docs/architecture/daylight-national.md`. Tests run in session (`python -m pytest -q`, the node
tests for `site/static/*.js`) and the output goes in the PR. Code starts after the ADR 0011 cutover (spec A11).
No task sends a request to a city, county or Legistar client endpoint unless it says "needs Brian's host OK".
Hard-stop column: what needs Brian before the task can finish.

## M1: lookup, statuses, Request it, What we cover, Clarksville coming-up (no new host, no workflow change)

| Task | Owner | Depends on | Parallel | Needs Brian |
|---|---|---|---|---|
| U1 National page, list, request form, What we cover, coming-up page designs and labels | ux-designer | spec v2 | yes | no |
| B1 Directory + gov-flags + labels files, loader and build checks | backend-engineer | none | yes | no |
| B2 Confirm FUNCSTAT and class codes; seed gov-flags | backend-engineer | none | yes (with B1) | no |
| B3 Clarksville adapter: council + county feeds in `daylight-upcoming/1` | backend-engineer | B1 | yes (with F1) | no |
| B4 National builder: pages + JSON/ICS/Atom, behind `national.enabled` | backend-engineer | B1, B3, U1 | no | no |
| B5 Byte-identical golden test | backend-engineer | B4 | no | no |
| B7 Morning note ignores `req-` tags (test only) | backend-engineer | none | yes | no |
| F1 `national.js`: jsonpUrl, classify, governments (pure, node tests) | frontend-engineer | B1 (pagedir shape), B2 | yes (with B3) | no |
| F2 Page wiring: sandboxed iframe, states, pick list, request form, storage | frontend-engineer | F1, U1, B4 | no | no |
| F3 Browser privacy test (network log, storage) on 12 recorded answers | frontend-engineer | F2 | no | no |
| S1 Security review: CSP, JSONP sandbox, request form, privacy claims | security-engineer | F2, B4 | no | no |
| Q1 QA against AC1-AC4, AC8, AC9 with recorded answers | qa-engineer | F3, B5 | no | no |
| Q2 Live checks with a team address: re-submit tags, confirmation copy, one real lookup per test address | qa-engineer + manager | S1 | no | **live preview OK** (Brian's device check) |
| R1 Turn `national.enabled` on in a deploy | devops-engineer | Q1, Q2, S1 | no | **yes: deploy (hard stop 1)** |

Suggested order: B1, B2, B7, U1 together -> B3 and F1 together -> B4 -> B5 and F2 -> F3 -> S1 -> Q1 -> Q2 -> R1.

Definitions of done:
- **U1** Done when: `docs/design/daylight-national.md` covers the address page (privacy line before submit, Census
  notice, error, no-match, pick, list with three statuses and reasons, the note about boards not found by address,
  the "check with your local election office" link), the Request form and its confirmation copy (never promises a
  date), the What we cover page, the coming-up page (stale line, "Agenda not final yet", "may be incomplete",
  "items are on the agenda" for not-read, withheld school boards); every string in `labels.yml` form. Includes a
  newsletter-wide Buttondown confirmation text that reads right for both a morning note sign-up and a request.
- **B1** Done when: `config/national/{directory,gov-flags,labels}.yml` exist with entries for `place-4715160`,
  `county-47125` (covered, platform daylight) and `sdu-4703030` (can't cover, blocks-readers, source
  `docs/research/rpc-cmcss-sources.md` and cmcss.net); `sitegen/national.py load_directory` refuses each bad case in
  architecture 3.2 with a test per case; the page directory (3.4) is produced by a pure function with a test.
- **B2** Done when: the FUNCSTAT, COUNTYCC/PLACECC/COUSUBCC meanings used by `governments` are quoted with their
  TIGER/Line documentation source in `docs/platform-facts.md`; gov-flags seeded for CT and RI counties, the MA
  counties without government, Nashville, the VA independent-city pattern, each with a source link; no request to any
  government host (Census documentation pages only).
- **B3** Done when: council and county feeds validate against `daylight-upcoming/1` (a JSON schema in `schema/`);
  county items equal `agendas.json` titles byte for byte; council meetings have `agenda.state` `not-read` or
  `not-posted`; no field outside the schema (test); `time` null; tests use the repo's real data files.
- **B4** Done when: with `national.enabled: true` the build writes `/us/`, `/us/cover/`, two coming-up pages and their
  three feeds; the ICS validates (a parser test) with stable UIDs; Atom ids follow `sitegen/feeds.py` rules; CSP per
  ADR 0013 decision 2 on `/us/` only; every visible string is verbatim source text or from `labels.yml` (test lists
  them, AC4.5); the "Report an error" control is present; the front page gains one link.
- **B5** Done when: a test builds with the switch off and compares every output file to a build of `main` at the same
  data, byte for byte; with it on, the diff is exactly new `/us/` files plus the front-page link.
- **B7** Done when: a sender test shows a confirmed subscriber with only `req-` tags gets no morning note edition, and
  one with `note-` and `req-` tags gets exactly the note it would get without the `req-` tag.
- **F1** Done when: node tests cover the recorded 1 Public Sq answer (verified shape in platform-facts) and synthetic
  answers for: no match, 3 matches, unincorporated (no place), FUNCSTAT N subdivision (dropped), CT county (hidden),
  coextensive town and city (one row), independent city (one row), school district "not defined" (dropped), an alias
  to a covered body; order is place, county, cousub, school districts.
- **F2** Done when: the address input has no `name`; submit only on press; 15 s timeout with Retry; the iframe is
  removed after each lookup; ticking not-covered bodies and posting email sends only `email` and `req-` tags; requested
  ids stored only under `daylight.us.requested`; works with the counter off.
- **F3** Done when: the browser test asserts, for each of 12 recorded answers, that only the Census request URL holds
  any address part, the page URL and title never do, and storage holds no key but `daylight.us.requested`.
- **S1** Done when: review report committed by the manager; any high finding fixed; accepted JSONP risk recorded.
- **Q1** Done when: QA report shows each M1 AC pass or a bug with a problem key.
- **Q2** Done when: recorded in `docs/platform-facts.md`: whether an existing subscriber's re-submit adds tags; what
  the confirmation email says; one live lookup each for the spec's test addresses plus CT, MA, NY, PA, VA, with the
  bodies listed matching the expected lists.
- **R1** Done when: Brian's typed OK is in the thread and the deploy shows `/us/`; Clarksville pages unchanged.

## M1.5 (after M1, independent)
| Task | Owner | Depends on | Needs Brian |
|---|---|---|---|
| B8 Optional GoatCounter `request-<id>` event (ADR 0013 decision 5) | frontend-engineer | M1 live + a weak request rate | no |
| B9 City Council agenda item reader from stored CivicClerk agenda PDFs | backend-engineer, opus/high review | M1 | no (no new host: PDFs already stored) |

- **B9** Done when: council upcoming items are stored as printed (the county reader's whitespace rules) for agendas
  already in the store; no new request; the Clarksville site's existing pages are unchanged byte for byte except the
  intended new item text; 10 sampled items match the PDF.

## M2: Legistar wave 1 (Salem first)
| Task | Owner | Depends on | Parallel | Needs Brian |
|---|---|---|---|---|
| C1 Fetcher tenant rule (`tenant_key`, `TenantBlocked`, `limit_tenant`) | backend-engineer (opus/high: state) | none | yes | no |
| C2 Legistar upcoming reader on recorded fixtures (status-aware, EventBodyId, cache by LastPublished) | backend-engineer | B3 schema | yes | no |
| C3 National run: budget order, health, proposals, never fails the run on one body | backend-engineer | C1, C2 | no | no |
| D1 `national-update.yml`, concurrency `national-collect`, budget, push `national-data`, attest | devops-engineer | C3, ADR 0011 cutover | no | **ruleset for `national-data` is Brian's PC (U3-0)** |
| D2 Daily deploy reads attested `national-data` (owning thread's file) | devops-engineer | D1 | no | no |
| S2 Security review C1, D1, D2 | security-engineer | D2 | no | no |
| P1 Terms check for the Legistar Web API; record in platform-facts | deep-researcher | none | yes | no |
| H1 First request to `webapi.legistar.com` for Salem only (probe mode, recorded as fixture) | backend-engineer | C1-C3, P1, S2 | no | **yes: host OK (R5)** |
| R2 Salem covered in directory + deploy | devops-engineer | H1, QA of the Salem page | no | **yes: deploy** |

- **C1** Done when: tests show a 403 on `/v1/a/` blocks only tenant `a`; 403 from a second tenant, 429, a 403 on
  robots.txt and a non-JSON 403 each block the host; delay and caps stay per host; existing fetch tests unchanged.
- **C2** Done when: fixture tests: a "Draft" agenda yields no items request and `not-final`; "Final" and "Final-Revised"
  yield items; an unknown status yields `not-final` plus a proposal; agenda PDFs are linked, never requested.
- **C3** Done when: a run with a synthetic budget of 10 records `budget-skipped` for the rest; a host stop marks the
  remaining bodies stale, never cant-cover; no curated status is written.

## M3 / M4 / M5 (outline; detailed when each starts)
- M3: request report (in-session or Brian's PC, never Actions logs); "email me when it opens" send (Brian OKs each);
  letter (spec US6) with contact fields in the directory.
- M4: weekly edition mode in `sender/` with a merged metadata stamp (ADR 0013 decision 8); per-body item cap; Brian
  approves sample, postal address, first send. PM rewords AC7.1 first.
- M5: platform order per ADR 0013 decision 9 (BoardDocs, eScribe, CivicClerk by requests; then Municode, PrimeGov).

## Asks for Brian (batched for the manager's card)
1. M1 live (R1): deploy `/us/` behind the switch after QA and security. Options: yes / not yet. Recommended: yes,
   once Q2 passes (default if no answer: stays off).
2. Host OK for `webapi.legistar.com`, Salem City Council only (H1). Options: yes / later. Recommended: yes, after S2
   (default: no request is made).
3. Postal address for email footers (M4 only, CAN-SPAM): LLC address / P.O. box / decide later. Recommended: decide
   later (default: no national email).
