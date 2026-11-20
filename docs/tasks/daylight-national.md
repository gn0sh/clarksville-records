# Tasks: daylight-national

ADR 0013, architecture `docs/architecture/daylight-national.md` (v2), UX draft `docs/design/daylight-national.md`,
security review `docs/reviews/security-daylight-national-design.md` (finding numbers and problem keys below). Tests run
in session (`python -m pytest -q`, the node tests for `site/static/*.js`) and the output goes in the PR. Code starts
after the ADR 0011 cutover (spec A11). No task sends a request to a city, county or Legistar client endpoint unless it
says "needs Brian's host OK". Hard-stop column: what needs Brian before the task can finish.
**M1 adds no host, workflow, secret or spend**: the only outside hosts are the Census (browser), Buttondown (already
live) and GoatCounter (already live, code `daylight-gnosh`).
**Gates from the security review.** R1 (M1 live) waits for findings 1, 2, 4, 5, 9 (tasks F5, Q2, B14, B1, F1/F2).
H1 (first Legistar request) waits for findings 3, 6, 7 (tasks C4, D1, B1/D3). Low findings are items in the tasks named.

## M1: lookup, statuses, Request it, counter, What we cover, Clarksville coming-up

| Task | Owner | Depends on | Parallel | Needs Brian |
|---|---|---|---|---|
| U1 UX draft v1 (done 2026-11-19, `docs/design/daylight-national.md`); follow-ups: N4 counter wording, finding 8 copy, small focus group | ux-designer | none | yes | Who-runs-it facts (AC1.9), before live |
| B1 Directory + gov-flags + labels files, loader, build checks, `state`, `items`, `host_ok`, `lines` | backend-engineer | none | yes | no |
| B2 Confirm FUNCSTAT and class codes; seed gov-flags | backend-engineer | none | yes (with B1) | no |
| B14 Shared guards: `https_link` + host allowlist, id regex, size caps, control and bidi stripping | backend-engineer | B1 | yes (with B3) | no |
| B3 Clarksville adapter: council + county feeds in `daylight-upcoming/1` | backend-engineer | B1, B14 | yes (with F1, F5) | no |
| B4 National builder: `digest/` pages, per-government JSON, Menu group, front-page line, behind `national.enabled` | backend-engineer | B1, B3, B14, U1 | no | no |
| B13 Header variant and the two site checks (scoped to `digest/`), plus the `digest/csp` check | backend-engineer | B4 (page set) | yes (with F2) | no |
| B5 Byte-identical golden test (switch off: all files; on: only the allowed fragments) | backend-engineer | B4, B13 | no | no |
| B7 Morning note ignores `req-` tags (test only) | backend-engineer | none | yes | no |
| B12 `tools/national/request_report.py`: `req-` counts by government from Buttondown's API, ignores ids not in the directory | backend-engineer | B1 | yes | **Brian runs it on his PC with his key** (no key given to the team) |
| F1 `national.js` pure part: jsonpUrl, classify, governments, notes, device-list functions, hardening | frontend-engineer | B1 (pagedir shape), B2 | yes (with B3) | no |
| F5 `digest/geo-frame.html` and the postMessage protocol (4.0) | frontend-engineer | B1 | yes (with F1) | no |
| F4 `us-count.js` and `window.DaylightCount` (3.9) | frontend-engineer | none | yes | no |
| F2 Page wiring: frame, states, picker, list cards, in-card form with several `req-` tags, saved list, Forget, counter button | frontend-engineer | F1, F4, F5, U1, B4 | no | no |
| F3 Browser privacy test (network log, storage, URL and title) on 12 recorded answers | frontend-engineer | F2 | no | no |
| T1 Method page section "Daylight Digest" (three storage keys, counter event, GoatCounter paths, requested governments show rough location); runbook line "every manual Buttondown send is filtered" | technical-writer | U1, F2 | yes (with F3) | no |
| S1 Security review of the build: CSP and frame, form post, counter, storage, privacy claims, header exemptions | security-engineer | F2, B4, B13 | no | no |
| Q1 QA against AC1-AC4, AC8, AC9, AC12 with recorded answers | qa-engineer | F3, B5, T1 | no | no |
| Q2 Live checks with a team address (add-vs-replace, no-cors post, redirect, confirmation copy, firewall, counter event, one real lookup per test address) | qa-engineer + manager | S1 | no | **live preview OK** (Brian's device check); **Buttondown dashboard settings (Q-A)** |
| R1 Turn `national.enabled` on in a deploy | devops-engineer | Q1, Q2, S1 | no | **yes: deploy (hard stop 1)** |

Suggested order: B1, B2, B7, F4 together (U1 draft is done) -> B14, then B3, F1 and F5 together -> B4 -> B13 and F2 ->
B5, B12, T1 and F3 -> S1 -> Q1 -> Q2 -> R1. Q2's add-vs-replace test (finding 2) can run as soon as the form markup is
fixed (after F2's first slice), against a team address, because its outcome may change the plan; run it early.

Definitions of done:
- **U1** Done when (draft done): the design covers every M1 screen. Open: the counter Done text (architecture N4),
  AC9.2 and AC9.3 copy saying requested governments show roughly where a person is (finding 8,
  `national/tags-location-disclosure`), the Method wording for N2 (names and IDs of governments), and the small focus
  group the design recommends. Includes a newsletter-wide Buttondown confirmation text that reads right for both a
  morning note sign-up and a request.
- **B1** Done when: `config/national/{directory,gov-flags,labels}.yml` exist with entries for `place-4715160`,
  `county-47125` (covered, platform daylight, `items: shown`) and `sdu-4703030` (can't cover, blocks-readers,
  `checked_doc: docs/research/rpc-cmcss-sources.md` and cmcss.net); `sitegen/national.py load_directory` (via
  `yaml.safe_load`) refuses each bad case in architecture 3.2 with a test per case, including: `items: shown` on an
  `sd*` id (`privacy-withhold/national-prefix`), a missing `items` meaning withheld, a non-daylight entry with no
  `host_ok` (`national/r5-not-enforced`), a bad `full_url`/`page`, `client`, `tz` or `final_statuses`, and a missing
  `state`; the page directory (3.4) is produced by a pure function with a test, written with `|tojson`. Section 11
  v3: `shown` needs the entry's whole canonical entry, readable, in its `SHOWN_REVIEWED` row (tests 11.3 items 1-4: shipped
  digests equal their rows, the mutation sweep, the canonical form, one covered entry per source; 8: pagedir `alias`
  only from `also`, gov-flags cannot alias or name `items`; 10: single reader of `directory.yml`, the sender imports no
  `sitegen.national*`).
- **B14** Done when (finding 4, `national/url-scheme-untrusted`; finding 12, `national/untrusted-size`): one helper
  accepts an outside URL only if `config.https_link` passes and, for a non-daylight platform, its host is on that
  platform's allowlist, and is called at collection and at build; a bad URL becomes null and the page uses
  `official_url`; ids that become a path or tag match the id regex in builder and collector; item text is cut at 2,000
  characters (`cut: true`), 150 items per meeting, 60 meetings per government; bidi overrides and controls are stripped
  and counted; one test per rule, with `javascript:`, `http:`, a credentialed URL and a bidi string. Section 11 v3:
  `is_shown(entry)` and `bind_feed(feed, entry)` (BindError on another body id or platform; withheld or stale-review
  items stripped and counted) in `sitegen/national_guards.py`, tested per 11.3 item 6.
- **B2** Done when: the FUNCSTAT, COUNTYCC/PLACECC/COUSUBCC meanings used by `governments` are quoted with their
  TIGER/Line documentation source in `docs/platform-facts.md`; gov-flags seeded for CT and RI counties, the MA
  counties without government, Nashville (with its `lines: consolidated`), the VA independent-city pattern (with
  `lines: independent-city`), each with a source link; MAX_ANSWER sized for 20 matches x 6 layers (security "needs
  verification"); no request to any government host (Census documentation pages only).
- **B3** Done when: council and county feeds validate against `daylight-upcoming/1` (a JSON schema in `schema/`);
  county items equal `agendas.json` titles byte for byte (within the B14 caps); council meetings have `agenda.state`
  `not-read` or `not-posted`; no field outside the schema (test); `time` null; the `items_withheld` flag comes from
  the directory's `items` field, never from an id prefix (`privacy-withhold/national-prefix`); tests use the repo's
  real data files. Section 11 v3: items read only when `is_shown`, only on the fixed `COUNTY_BODY_KEY` route; feeds
  carry `review` and pass `bind_feed`; the schema requires `review` (null forces withheld) (11.3 item 5).
- **B7** Done when: a sender test shows a confirmed subscriber with only `req-` tags gets no morning note edition, and
  one with `note-` and `req-` tags gets exactly the note it would get without the `req-` tag.
- **B4** (revised) Done when: with `national.enabled: true` the build writes `digest/index.html`, `covered.html`,
  `requested.html`, `geo-frame.html`, and for each covered government `digest/<st>/<body id>.html` and `.json`
  (Clarksville City Council and Montgomery County Commission); CSP per architecture section 6 on each file; the Menu
  group and the front-page line are inserted by `apply_site_fragments` as fixed strings; ICS and Atom are not written
  (M4); every visible string is verbatim source text or from `labels.yml` (a test lists them, AC4.5, AC4.8), in
  "government" words; "Report an error" present; the coming-up page prints items only from the JSON, and a withheld
  government shows the fixed label (consumers 2 and 3 of architecture section 11, tested with the fixtures there);
  the JSON validates against a schema in `schema/` with no extra key. Section 11 v3: `.json` and `.html` only from
  `bind_feed` output for covered directory entries; the builder sweep of 11.3 item 7 (`SENTINEL-ITEM-TEXT` only in the
  bound shown government's files, including a copied file with a stale `review`).
- **B13** Done when: with `national.enabled` on, `qa/site_checks.py` passes on the whole build; `header/same-on-every-page`
  holds pages outside `digest/` to exactly the old rule and digest pages to the old header plus the three named
  substitutions (plate place, no moon, no `sky-in` span), and a digest page with the Clarksville header, or any other
  difference, fails (a test for each); `switch/on-every-page` still requires one switch with unchanged options on every
  non-digest page and zero on digest pages (a test for each); `digest/csp` checks the per-file policies of
  architecture section 6 and 4.0 (the Census appears in no CSP but the frame's; the parent has `script-src 'self'`);
  the PR lists any other check that flagged a digest page with the scoped exemption proposed, each naming the prefix.
  Gains 12.3 #9 (section 12, B-ISO-6): `dates/no-raw-utc-day` reads a coming-up page `digest/<st>/<id>.html` without
  its `<main>` (the feed text); a raw day there passes, the same day outside a coming-up page or in its footer fails
  (`tests/test_national_isolation.py`).
- **B5** (revised) Done when: a test builds with the switch off and compares every output file to a build of `main` at
  the same data, byte for byte (including every `static/count.js`, `_header` output and footer); with it on, removing
  the two fixed fragments (front-page line, Menu group) and the new `digest/` and `static/` files leaves a byte-equal
  tree, and the test fails if either fragment differs by one character or appears twice.
- **B12** Done when: the script (fixture tests on recorded API shapes) prints counts per government id for `req-<id>`
  tags among confirmed subscribers only, ignores ids not in the directory and lists how many it ignored (finding 11,
  `national/form-abuse`), says "advisory: anyone can tag a known email" in its header line (finding 2), reads the key
  from an environment variable, never writes it or any email to disk, and states in `--help` that it is run on Brian's
  PC. It does not read GoatCounter; the counter's taps are read in Brian's GoatCounter dashboard.
- **F1** Done when: node tests cover the recorded 1 Public Sq answer (verified shape in platform-facts) and synthetic
  answers for: no match, 3 matches, unincorporated (no place; note `no-city`), FUNCSTAT N subdivision (dropped), CT
  county (hidden; note `no-county`), coextensive town and city (one row), independent city (one row; note
  `independent-city`), consolidated city-county (note `consolidated`), school district "not defined" (dropped), an
  alias to a covered body, nothing listable; order is place, county, cousub, school districts. Hardening
  (finding 9, `national/postmessage-hardening`): GEOID regex `^\d{5,10}$`; lookups with null-prototype objects or `Map`,
  tested with ids `__proto__` and `constructor`; pagedir via `|tojson`; `textContent` only. Device list: `loadList`,
  `saveList`, `forget`, `markRequested`, `markCounted` tested with a fake storage, including bad and oversized stored
  values, a storage that throws, and that `forget` removes all three keys.
- **F5** Done when: `digest/geo-frame.html` is built with the meta CSP of 4.0 (inline-script hash computed at build,
  Census path only) and `sandbox="allow-scripts"` without `allow-same-origin`; the parent accepts a message only for
  the right source, origin `"null"`, string type, length cap and valid JSON (tests with a message from another window,
  an object, an oversize string and bad JSON, all ignored); the address reaches the frame only by postMessage after
  "ready"; no page but the frame names the Census in its CSP; the 15 s timeout and removal of the frame are tested
  (finding 1, `national/csp-jsonp-gadget`). A short note in the PR on whether the callback name check is needed (the
  proxy refused the probe, so unverified).
- **F4** Done when: `us-count.js` sends only `GET .../count?p=count-<id>&e=true&rnd=...` (a node test with a fake
  `fetch` asserts the exact URL and options), validates the id against the id regex, sends nothing under Do Not Track,
  Global Privacy Control, an automated browser, a non-https page or an empty or malformed code, sets
  `available: false` in each of those cases, resolves on send and rejects when `fetch` rejects; a test asserts its guard
  lines equal `count.js`'s; it reads no storage and no form field.
- **F2** Done when: the address input has no `name` and the form no `action`; submit only on press; 15 s timeout with
  Retry; the result is drawn on the same page and `location` and `document.title` never change; the request form sends
  only `email` and `tag` fields, one `req-<id>` per ticked government (own card's id always, others unticked by
  default), in one post by no-cors `fetch` with the native post as the fallback; every ticked card flips to Sent and
  its id is stored under `daylight.us.requested`; the email is never stored; the "Just count me" button shows only when
  `DaylightCount.available`, sends one event on a tap, shows the Done and Failed text, and stores the id under
  `daylight.us.counted`; "Your saved list" and "Forget this list" work (all three keys removed); everything works with
  analytics off; focus moves exactly once after each result.
- **F3** Done when: the browser test asserts, for each of 12 recorded answers, that only the Census request URL holds
  any address part, the page URL and title never do, storage holds no key but the three of architecture 3.8 with the
  shapes there, the Buttondown post (stubbed) holds exactly `email` and the expected `tag` fields, and the GoatCounter
  request after a tap (stubbed) holds exactly `p`, `e` and `rnd`.
- **T1** Done when: the Method page section lists the three storage keys and what each holds, the counter event and what
  GoatCounter sees (government id as an event name, plus the request's IP and browser, which it says it does not
  keep), and says plainly that requested governments show roughly where a person is (finding 8,
  `national/tags-location-disclosure`); the runbook gains the line that every manual Buttondown send must be filtered
  to its intended tag (finding 13, `national/unfiltered-send`); `slop-stopper` is not required (no marketing copy).
- **S1** Done when: review report committed by the manager; any high finding fixed; the findings 1, 2, 4, 5, 9 are each
  shown closed by test or by the Q2 result; accepted risks recorded (R-B, R-D).
- **Q1** Done when: QA report shows each M1 AC pass or a bug with a problem key.
- **Q2** Done when, recorded in `docs/platform-facts.md` (finding 2, `national/tags-existing-subscriber`, gates R1): (a)
  with a team address already holding `note-` tags, a form post carrying only `req-` tags ADDS them and keeps the
  `note-` tags (tags read by API, not the side panel); if it REPLACES them, stop: this is high, R1 is blocked, and the
  manager takes the fallbacks in architecture risk R-A to Brian; (b) a post from the live page by no-cors `fetch`
  subscribes a new team address (email arrives, tags present), else the native-post fallback is chosen and F2 is
  changed; (c) the confirmation email text, and whether the redirect can point to `digest/requested.html` (Q-A);
  (d) Buttondown's firewall and IP filtering are on (finding 11); (e) a counter tap shows in Brian's GoatCounter
  dashboard as `count-<id>`; (f) one live lookup each for the spec's test addresses plus CT, MA, NY, PA, VA, with the
  governments listed matching the expected lists; (g) M1's "done when" in the UX draft: Brian requests a government with
  a team address, confirms, and Brian sees it with B12 on his PC.
- **R1** Done when: Brian's typed OK is in the thread and the deploy shows `digest/`; Clarksville pages unchanged except
  the two fixed fragments (B5).

## M1.5 (after M1, independent)
| Task | Owner | Depends on | Needs Brian |
|---|---|---|---|
| B8 Superseded: the counter is in M1 as F4 (ADR 0013 decision 5 delta, architecture N3) | none | none | no |
| B10 Coverage share estimate: offline script writes `config/national/share.yml` ({pct, k, date}); builder prints the What we cover sentence only when the file exists | data-analyst + backend-engineer | M1 live | no (Census requests from our side use made-up addresses only; no Daylight user data) |
| F7 Move the existing landing-page address box to the static frame (finding 1 follow-up; changes Clarksville pages on purpose, own PR, own golden update) | frontend-engineer | F5, M1 live | no |
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
| C4 ICS writer in Python with RFC 5545 escaping (finding 3); Atom via `sitegen/feeds.py` (M4 ships them, the writer lands now) | backend-engineer | B3 schema | yes | no |
| D1 `national-update.yml`, concurrency `national-collect`, budget, push `national-data`, attest; read-only collect job, separate write-scoped push job, pinned `--cert-identity` (finding 6) | devops-engineer | C3, ADR 0011 cutover | no | **ruleset for `national-data` is Brian's PC (U3-0)** |
| D2 Daily deploy reads attested `national-data` (owning thread's file; gains 12.3 #8 and #9: the switch off ignores any `RECORDS_NATIONAL_DATA`, and the site checks pass feed text with raw days; `tests/test_national_isolation.py`) | devops-engineer | D1 | no | no |
| D3 Collector refuses a non-daylight entry without `host_ok` (finding 7); directory checks reused from B1 | backend-engineer | C3, B1 | no | no |
| A2 State the `national-isolation` invariant and consumers (architecture section 12, done 2026-11-20) | software-architect | S2b | no | no |
| B-ISO National isolation, backend (architecture 12.2: B-ISO-1 to -7; S2b findings 1, 2, nit b, new N2-N4) | backend-engineer (opus/high) | A2 | yes, with D-ISO | no |
| D-ISO National isolation, workflows (architecture 12.2: D-ISO-1 to -8; S2b findings 3, 4, 5 optional, nits a, d, e, new N1) | devops-engineer | A2 | yes, with B-ISO | **nit e only: `national-data` ruleset blocks force-push and deletion (Brian's PC, batched with U3-0)** |
| D-ISO-9 Daily issue on `national: degraded` or a degraded government (with S2b ruling 5's >20% stale issue) | devops-engineer | B-ISO | no | no |
| B-ISO-12..15 Row 6s (architecture 12.1 row 6s, 12.2 v3; S2d findings 1, 2, nit a): fixed-title rule, `host_ok.date` floor on `checked_at`, blanking only inside digest-meeting sections, exact ordered `digest/feed-text`; 12.3 #15 | backend-engineer (opus/high) | A2 v3 | yes, with D-ISO-16..17 | no |
| D-ISO-16..17 S2d nits b, c: one exact body-id rule in every copy (workflows, schema, `collector/national/run.py:76`); attestation warning text | devops-engineer | A2 v3 | yes, with B-ISO-12..15 | no |
| S2 Security review C1, C2, C4, D1, D2, D3 | security-engineer | D2, D3, C4 | no | no |
| P1 Terms check for the Legistar Web API; record in platform-facts | deep-researcher | none | yes | no |
| A1 State the `privacy-withhold` invariant and consumers (architecture section 11, done in v2) and review it before C2 | software-architect | none | yes | no |
| H1 First request to `webapi.legistar.com` for Salem only (probe mode, recorded as fixture) | backend-engineer | C1-C4, D1, D3, P1, S2 | no | **yes: host OK (R5); the date and link go in the entry's `host_ok`** |
| R2 Salem covered in directory + deploy | devops-engineer | H1, QA of the Salem page | no | **yes: deploy** |

H1 gates (security review): finding 3 (C4), finding 6 (D1), finding 7 (B1, D3).
- **B-ISO / D-ISO** (`national-isolation`, architecture section 12) Done when: every test of 12.3 passes in the
  PR output (#1-9 and #13 backend, #10-12 devops); each 12.1 row marked "breaks" cites its closing test; then a fresh
  code review and a fresh security review (the diffs touch CI). D-ISO-1 and D-ISO-2 land first (they hold the
  Clarksville deploy with the switch off); B-ISO and D-ISO-9 gate `national.enabled: true` with any collected entry.
  v3: B-ISO-12..15 and D-ISO-16..17 likewise gate the switch (not a release blocker); Done when 12.3 #15 and the
  extended D-ISO-10 test pass in the PR output, the switch-off fixture build is byte-identical to 30cb61d2, and a
  fresh security review passes (D-ISO-16 touches CI).
- **C1** Done when: tests show a 403 on `/v1/a/` blocks only tenant `a`; 403 from a second tenant, 429, a 403 on
  robots.txt and a non-JSON 403 each block the host; delay and caps stay per host; `/v1/Salem/` and `/v1/salem/` are
  one tenant (finding 10, `national/tenant-key-normalize`); existing fetch tests unchanged.
- **C2** Done when: fixture tests: a "Draft" agenda yields no items request and `not-final`; "Final" and "Final-Revised"
  yield items only for an entry with `items: shown`; an entry with `items: withheld` (including a `place-` entry for a
  youth council) makes no items request at all and its JSON and cache hold no item text, tested with one `sd*` and one
  such `place-` fixture (`privacy-withhold/national-prefix`); an unknown status yields `not-final` plus a proposal;
  agenda PDFs are linked, never requested; B14 caps and URL rules apply to every field read.
- **C3** Done when: a run with a synthetic budget of 10 records `budget-skipped` for the rest; a host stop marks the
  remaining bodies stale, never cant-cover; no curated status is written; ids matched against the id regex before they
  become paths; each run stamps when it checked each body, and that stamp (not a document's first fetch) is the
  feed's `checked_at` and, on success, `last_ok_at` (B4 review, `national-freshness/checked-at-is-first-fetch`).
- **C4** Done when (finding 3, `national/feed-ics-injection`): a title or item text holding `\r\nBEGIN:VEVENT`, a
  semicolon, a comma and a backslash comes out as one escaped, folded (75 octets) line of one VEVENT; a parser test reads
  the file back as exactly the expected events; control characters are stripped through `feeds.clean`; UIDs are stable.
- **D1** (added) Done when: the collect job declares `contents: read` and holds no token; the push job alone has
  `contents: write` and writes only `data/national/**` to `national-data`; the deploy gate pins `--cert-identity` per
  workflow and branch (an attestation from another workflow or branch is refused, tested); security re-confirms.
- **D3** Done when: the collector and the build both refuse a non-daylight entry with no `host_ok: {date, link}`, with a
  test each (finding 7, `national/r5-not-enforced`).

## M3 / M4 / M5 (outline; detailed when each starts)
- M3: "email me when it opens" send (Brian OKs each; every manual send filtered to its tag, finding 13); letter (spec
  US6) with contact fields in the directory. The request report itself is B12 in M1.
- M4: weekly edition mode in `sender/` with a merged metadata stamp (ADR 0013 decision 8); per-body item cap; ICS and
  Atom shipped from the C4 writer; JSON linked from Method; Follow block; sign-up page with a consent design for `wk-`
  tags before any build (finding 2: anyone can post tags for a known email); Brian approves sample, postal address,
  first send. PM rewords AC7.1 first.
- M5: platform order per ADR 0013 decision 9 (BoardDocs, eScribe, CivicClerk by requests; then Municode, PrimeGov).

## Asks for Brian (batched for the manager's card)
0. Before Q2 (Buttondown dashboard, free if available): set the confirmation redirect to `digest/requested.html` and
   edit the newsletter-wide confirmation text (U1 supplies it). Options: yes / skip. Recommended: yes (default: the
   label rides in the confirmation email as the design allows). Also confirm the who-runs-it facts (AC1.9, UX Q2) and
   run `tools\national\request_report.py` once on your PC with your Buttondown key (B12; the key never leaves your PC).
   Architecture N1 (Menu group on every page: accept / front-page line only; recommended accept) and N2 (device list
   keeps names with ids: accept; recommended accept) are the manager's to record; default if no answer: accept.
1. M1 live (R1): deploy `digest/` behind the switch after QA and security. Options: yes / not yet. Recommended: yes,
   once Q2 passes (default if no answer: stays off).
2. Host OK for `webapi.legistar.com`, Salem City Council only (H1). Options: yes / later. Recommended: yes, after S2
   (default: no request is made).
3. Postal address for email footers (M4 only, CAN-SPAM): LLC address / P.O. box / decide later. Recommended: decide
   later (default: no national email).
