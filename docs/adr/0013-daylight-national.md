# ADR 0013: National Daylight: a Census-keyed directory, a browser-only lookup, a per-tenant collector

Status: proposed (software-architect, 2026-11-19), feature `daylight-national`. Design only: nothing here collects,
deploys, sends or changes product code. Architecture and contracts: `docs/architecture/daylight-national.md`. Tasks:
`docs/tasks/daylight-national.md`. Spec: `docs/specs/daylight-national.md` (v1; v2 in progress: M1 = lookup,
statuses, "Request it", a "What we cover" list, Clarksville and Montgomery County covered, coming-up pages). Panel:
`docs/reviews/brain-trust-daylight-national.md` (Operator section and the Decisions table drive decisions 4 to 7).
Builds on ADR 0004 (morning note sender), 0006 (data guards), 0008 (GoatCounter), 0011 (data off `main`) and 0012
(city-only site, PR #62: Legistar and eScribe readers, `post_json`).

**Changed after the first draft (manager, relaying Brian, 2026-11-18 11:32 PM CT):** Buttondown capacity and the tag
add-on are no longer a constraint; Brian will upgrade when needed. So "Request it" collects an email (double opt-in,
one tag per body) as the main path, and the anonymous counter is optional (decision 5). The upgrade itself is still
Brian's action (hard stop 3); nothing in M1 needs it while the list is under the free cap.

## Context
The spec asks for one national page: a person types an address and sees every local government covering it, with an
honest status each, without Daylight ever seeing the address. Today Daylight is one locality: bodies are named in
`config/`, the address box uses the Census `locations` endpoint plus traced district lines, and the collector's
politeness state is keyed per site (`collector/fetch.py` `site_key`, `_blocked`, `_last`). Every Legistar client
shares one host, `webapi.legistar.com`, so one client's 403 would today stop every Legistar body for the run
(Operator finding). The daily workflow is late and often fails (Operator: last 6 runs started 15:42 to 19:29 UTC,
3 failed), and it belongs to another thread.

Facts verified for this ADR (2026-11-19; details in `docs/platform-facts.md`, "Census geocoder"): one `geographies`
query for 1 Public Sq, Clarksville returned layers named "Incorporated Places" (Clarksville city, GEOID 4715160,
FUNCSTAT A), "Counties" (Montgomery County, 47125, A), "County Subdivisions" ("District 5", 4712590886, FUNCSTAT N:
a commission district, not a government) and "Unified School Districts" (CMCSS, 4703030, FUNCSTAT E). Census docs:
`layers` takes names or IDs, `layers=all` works, `format=jsonp&callback=` is the browser path, no CORS, no published
rate limit. From our data: Montgomery County Commission upcoming agenda items are stored as printed (whitespace
joined); Clarksville City Council upcoming agendas are stored as documents only, with **no item-level text**
(0 item events from agenda sources in `data/localities/clarksville-tn/facts.json`).

## Decisions

### 1. The directory is keyed by Census GEOIDs, with a layer prefix; absent means "not covered yet"
- A government's id is `<layer>-<GEOID>`: `place-4715160`, `county-47125`, `cousub-<10 digits>`, `sdu-4703030`,
  `sds-<7>`, `sde-<7>`. The prefix is required because place and school district GEOIDs are both 7 digits and can
  collide. A body id is the government id while there is one body per government (spec A13); a second body later
  becomes `<gov id>.<slug>` (for example `place-4715160.planning`), so no id ever changes.
- The directory is curated code: `config/national/directory.yml`, reviewed like any code (ADR 0011 decision 2),
  never written by a workflow. Each entry has `gov`, `also` (other GEOIDs that name the same government:
  consolidated city-counties, independent cities), `body_name`, `status`, `official_url`, `checked` (date),
  `checked_url`, and per status: `platform` and its reader keys (covered), or `reason` plus `reason_url` (can't
  cover). A government with no entry is **not covered yet** (AC2.8). The build refuses an entry without its source
  link and date.
- **Statuses** (curated): `covered`, `cant-cover`. Reasons for `cant-cover` are a fixed list, each with one label in
  the label file: `blocks-readers`, `robots-disallow`, `scanned-only`, `not-posted`, `token-required`,
  `api-not-enabled`, `terms`. **Derived** (never curated, from collector health): `stale` (covered, last good read
  more than 3 days ago: shown as a line on the page, AC4.6; the status stays covered). A collector never changes a
  curated status: it writes an observation and a proposal (decision 6), and a person changes the directory by PR.
  So a 429 or a run-wide block can make a body stale but never "can't cover" (Brain Trust, Operator).
- **Government flags**: the lookup shows a returned unit only when it is a working government. The rule uses
  FUNCSTAT from the Census answer itself (A for places, counties and county subdivisions; E or A for school
  districts; observed values above), then `config/national/gov-flags.yml`, a hand table that overrides FUNCSTAT
  either way by GEOID or by state and layer. Seeded for CT and RI counties (no county government), the Massachusetts
  counties without a government, consolidated city-counties, and independent cities. New England and New York towns
  are county subdivisions with FUNCSTAT A, so the default rule shows them; the hand table is the backstop. The other
  FUNCSTAT codes (B, C, F, I, S) are from TIGER documentation not yet re-read: task B2 confirms them before the rule
  ships, and QA covers CT, MA, NY, PA, VA and Nashville test addresses.

### 2. The lookup runs only in the browser, through the Census geocoder's JSONP, in a sandboxed iframe
- Same pattern as today's address box (`site/static/address.js`, `site/templates/_geocode_frame.js`): on submit only,
  a hidden iframe per lookup with `sandbox="allow-scripts"` and no `allow-same-origin` loads
  `https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress?address=...&benchmark=Public_AR_Current&vintage=Current_Current&layers=<six layers>&format=jsonp&callback=crGeocode`
  and posts the answer back as JSON text; the page validates it as data and renders text only.
- **Layers requested**: Incorporated Places, Counties, County Subdivisions, Unified School Districts, Secondary
  School Districts, Elementary School Districts (by name, as the docs allow; IDs vary by service and are not used).
  Layers are read by exact name; congressional, legislative, CDP and statistical layers are never requested.
- **The directory travels to the browser before anything is typed**: the build embeds the directory as an inert
  `<script type="application/json">` block in the page. The browser matches GEOIDs locally, so no request to any
  Daylight host depends on the address, and `connect-src` stays as it is. Past about 200 KB the build splits it
  (decision recorded then; not needed while it holds tens of entries).
- **CSP** for the national page: `script-src 'self' '<sha256 of the frame script>'
  https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress` (a path without a trailing slash matches that
  exact path), `form-action 'self' https://buttondown.com` (for "Request it"), `connect-src` the GoatCounter origin
  only when counting is on. **Accepted risk**: JSONP runs Census-served script. It runs in an opaque-origin sandbox
  with no storage, cookies, top navigation or pop-ups; the worst a hostile answer can do is post a bad message,
  which the page parses as data and shows as text. The security-engineer re-checks this (task S1).
- **Privacy**: the address input has no `name` attribute and the form no action, so a submit without script sends
  nothing anywhere. The address never enters the URL, title, cookies or storage. Only body ids may be kept on the
  device. The Census non-endorsement notice is shown word for word (AC1.7). Timeout 15 s, then "Retry" (AC1.6). Several
  matches: each match already carries its geographies, so the person picks one with no second request (AC1.5).

### 3. M1 is static pages from data we already hold, built by the existing site build behind one switch
- `sitegen` gains a national module that writes, under `/us/`: the address page, the "What we cover" list, one
  coming-up page per covered body, and per-body feeds (decision 7). It runs only when `config/site.yml`
  `national.enabled` is true. **Clarksville byte-identical**: with the switch off, the build output equals today's
  byte for byte (a golden-diff test); with it on, the only changes are new files under `/us/` and the one front-page
  link (AC8.2). No workflow edit, no new host and no new collection in M1.
- Coming-up data in M1: the County Commission's agenda-only meetings (`data/county-agendas/agendas.json`, items as
  printed) and the City Council's posted meetings (`facts.json` and the CivicClerk listing). City items are **not**
  shown in M1: the meeting shows its official agenda link and the fixed label that items are on the agenda. A city
  agenda item reader is a separate, later task (task B9), reviewed on its own, because it changes Clarksville's
  collected data.
- **School boards never show item text** anywhere in national Daylight, whatever the platform, until the allow-list
  re-plan in `docs/architecture/agenda-withhold-invariant.md` exists. A covered school board shows meetings, the
  agenda link and an item count only.

### 4. "Request it" collects an email at Buttondown, one tag per body; the morning note ignores those tags
- The button opens a small form: email only, posted from the browser to the existing Buttondown embed form
  (`daylight` newsletter), with one `tag` field `req-<body id>` per body requested. Double opt-in as today. No
  address, district or location text is posted (AC3.4). Confirmation copy says we may never cover it and never
  promises a date.
- **Tag namespaces on the one list**: `note-` (Clarksville morning note, unchanged), `req-` (requests), and later
  `wk-` and `wkt-` (national weekly bodies and topics). The morning note sender reads only `note-` tags
  (`sender/common.py` `read_tags`, `sender/deliver.py` `recipient`), and a subscriber whose selection is empty gets
  no email (ADR 0004 decision 2). So a requester gets no morning note. Task B7 pins this with a test.
- Request counts for "what opens next" are read from Buttondown tags in-session or from Brian's PC, never printed
  in public Actions logs (the repository is public; counts stay internal, spec open question 5). Not needed before
  January; the report is an M3 task.
- Unverified, checked by task Q2 with a team address before M1 goes live: whether a form post from an **already
  subscribed** address adds its new tags (platform-facts says it gets "successfully subscribed" and no confirmation
  email; metadata changes, tags not recorded), and whether Buttondown's confirmation email copy, which is one per
  newsletter, reads right for both a morning note sign-up and a request.

### 5. Optional anonymous counter: a GoatCounter event; no new account and no server
- If wanted, "Request it" also sends one GoatCounter event, path `request-<body id>`, through the existing
  `static/count.js` (ADR 0008; site code `daylight-gnosh`). Nothing else on the national page sends a body id: not
  on lookup, not on render. It obeys the same Do Not Track and GPC opt-outs as every other count, and ad blockers
  drop it, so it is a lower bound. Its counts are in Brian's GoatCounter dashboard (reading them by API needs a new
  key: hard stop 5). **Recommendation: build it as one small task after M1, only if the email path shows people
  avoid giving an email** (a high lookup-to-request drop). Alternatives rejected: a GitHub issue per request (needs an
  account), Google Forms or Formspree (a new third party and account), any self-run counter (a server, a host),
  storing requesters at Buttondown only by counter tags (no longer needed now capacity is not a constraint).

### 6. The national collector: per-tenant state on shared hosts, its own workflow, budget and data branch
- **Per-tenant block state.** `PoliteFetcher` gains a tenant rule for shared hosts: for `webapi.legistar.com` the
  tenant is the first path segment after `/v1/` (the Legistar client). The crawl delay, robots.txt and the run's
  request cap stay **per host** (we are one visitor to one host). The block is per tenant: a 403 on a client's path
  stops that client for the run. The whole host stops for the run on: any 429 (a rate limit is about us, not the
  client), a 403 on robots.txt or a path outside `/v1/<client>/`, a 403 whose body is not a Legistar JSON error, or
  403s from two different clients in one run. A host stop makes every body not yet read this run **stale**, never
  "can't cover". No retry by another route, as today.
- **Allowlist**: only `webapi.legistar.com` is added for Legistar (one host OK from Brian covers it; R5 still needs
  his OK per batch of bodies). `<client>.legistar.com` and agenda PDF hosts are **linked, never fetched**, which
  narrows PR #62's `legistar.allowed_hosts` (it adds the client host). Robots.txt of `webapi.legistar.com` is read
  once per run.
- **Status-aware reading** (Legistar): one events query per body per run, filtered by `EventBodyId` (from the
  directory, stable when a body is renamed; PR #62 filters by name) for today minus one day to today plus 28 days in
  the body's time zone. Read `EventAgendaStatusName`, `EventTime`, `EventAgendaFile`, `EventInSiteURL`,
  `EventAgendaLastPublishedUTC`. Items are requested and shown **only when the agenda is final**: the status name
  matches `^final\b` (case-insensitive) or a per-body list in the directory. Any other or empty status shows the
  meeting with "Agenda not final yet" and its link when one exists. Unknown status names are logged as proposals.
  Items are re-read only when `EventAgendaLastPublishedUTC` changes. Each Legistar meeting with items shows the fixed
  line "This list may be incomplete. The official agenda is the full record." because the API returns only items
  marked public. `EventTime` is shown as posted; none posted reads "Time not posted".
- **Its own workflow** (devops builds later; this ADR does not edit workflows): `national-update.yml`, concurrency
  group `national-collect` (never cancels a run in progress), twice daily, timeout 75 min, request budget
  `NATIONAL_REQUEST_BUDGET` (default 300) on `webapi.legistar.com` via `limit_hosts`, plus at most 12 requests per
  tenant. Order inside a run: bodies with a meeting in the next 7 days whose agenda is not final, then bodies not
  read longest. A body skipped for budget records `budget-skipped`. At a 10 s floor, 300 requests is about 50 min and
  about 100 bodies a run at about 3 requests each; growth past about 200 bodies needs a new decision, never a
  shorter delay without Brian.
- **Output** goes to its own branch `national-data` (tree `data/national/` only), with the ADR 0011 pattern: ruleset
  against deletion and force-push, an attested tree listing, and the gate verifying it before a deploy reads it.
  Files: `bodies/<body id>.json` (the feed below), `health.json` (per body: last attempt, last good read, consecutive
  failures, last error kind), `proposals.json` (suggested status changes and unknown agenda statuses, for a person).
  The Pages deploy stays in `daily-update.yml` and reads the newest attested `national-data`; a national failure never
  holds a Clarksville deploy (stale national data shows "last checked"). That workflow change belongs to the thread
  that owns `daily-update.yml` and comes after the ADR 0011 cutover (task D2).
- **Tests use recorded fixtures only.** No test or design step sends a request to a Legistar client endpoint.

### 7. Feeds per body: JSON (the contract the app and the email read), ICS and Atom
`/us/b/<body id>/upcoming.json` (schema `daylight-upcoming/1`), `upcoming.ics` and `upcoming.xml` (Atom, as
`sitegen/feeds.py` writes today). Same content, same source links; ids never change. Contract in the architecture doc.

### 8. Email (M4, after capacity is settled): editions through the existing sender, not one send with conditionals
Weighed (sizes are judgment calls, medium confidence; no Buttondown limit on email size is documented):

| Option | Size and render risk | Other risk | Verdict |
|---|---|---|---|
| A. One weekly send, per-subscriber `{% if %}` sections per body and topic | The source holds every covered body's sections: about 300 bodies x 15 items x 250 B is over 1 MB of template, with body-by-topic nesting. Render time and email-size limits unknown. The web archive and "view in browser" render as whom? | Relies on `subscriber.tags` in templates at our plan (unverified); one bad template breaks every subscriber's email | Fallback only |
| B. One send per body | Small emails | Breaks "one email a week" (several bodies = several emails) | Rejected |
| C. Editions (ADR 0004 pattern): plan computes each subscriber's exact content from `wk-`/`wkt-` tags, groups identical results, one stamped, filtered email per edition | Each email holds only its readers' content; capped per body (15 items, then "and N more on the official agenda") to stay under Gmail's 102 KB clip | Many emails a week at scale (one per distinct selection); the metadata stamp is shared with the morning note | **Recommended** |
| D. Feeds only (JSON, ICS, Atom) | none | No inbox delivery | Ships in M1 regardless |

Option C needs one change first: Buttondown `PATCH` replaces the whole metadata object (platform-facts), so a second
sender writing its own stamp would wipe the morning note's. The weekly note therefore lives in the same `sender`
package, writes one merged metadata object, and shares the morning note's concurrency group. The spec's AC7.1 says
"one Buttondown send with per-subscriber sections"; the promise to the reader is one email a week, which C keeps.
**Ask the product-manager to reword AC7.1** to "at most one Daylight weekly email per subscriber per week". CAN-SPAM
needs a postal address in the footer: Brian's decision before M4.

### 9. Platform order after Legistar
Legistar (M2, Salem first) then, ordered by real requests: **BoardDocs**, eScribe, CivicClerk; then Municode and
PrimeGov. BoardDocs leads ties because every address has a school district and school boards are the commonest
gap; but under decision 3 a school board shows meetings and agenda links only, so BoardDocs adds dates and links,
not items. Each platform needs a terms and robots check and Brian's OK per host before any request. BoardDocs reads
by POST, so it uses PR #62's narrow `post_json` (an allowlist of host and path pairs).

## Alternatives considered
- **A server-side lookup proxy** (better errors, caching): Daylight would receive addresses. Breaks R7. Rejected.
- **Keying the directory by city name or Legistar slug**: names repeat across states and change; the Census answer
  gives GEOIDs, so any other key needs a fuzzy match. Rejected.
- **Fetch the directory after the lookup, by state**: smaller pages, but a request to our host would then depend on
  the address (its state). Rejected while the whole directory is small.
- **Keep host-level block state for Legistar**: one token client's 403 stops every Legistar body (Operator).
  Rejected.
- **Collect national bodies inside `daily-update.yml`**: shares a late, failing schedule and another thread's file;
  a slow host would delay Clarksville. Rejected.
- **Auto-set "can't cover" from collector errors**: a transient 403 or 429 would show a false reason and, in M3,
  offer a letter blaming the government. Rejected: proposals only.
- **Don't build national now** (Brain Trust minority): steelmanned in the panel report. Brian chose to build; this
  design keeps every M1 step static and reversible, with no new host.

## Consequences
- M1 needs no new host, no workflow change, no new secret and no spend. It adds `/us/` pages behind one switch.
- `collector/fetch.py` gains a tenant rule (one more state key); its existing tests keep passing because no current
  host is a shared host.
- A second data branch (`national-data`) doubles the ADR 0011 provenance surface: the security-engineer reviews D1
  and D2 as hard-stop-adjacent.
- The directory and gov-flags table are hand work that grows one body at a time; no bulk scraping (spec non-goals).
- City Council items stay off the national page until task B9 ships; the page says so plainly.
- Reversible: `national.enabled: false` removes every national page in one build; the directory and feeds are
  additive files.

## Amendment A (2026-11-19, after the design security review and UX reconcile)
Recorded by the manager from docs/architecture/daylight-national.md v2 and docs/reviews/security-daylight-national-design.md.
- Decision 2: the Census lookup runs in a static `digest/geo-frame.html` with its own meta CSP; the parent page keeps
  `script-src 'self'`; `connect-src` adds buttondown.com for the request form.
- Decision 5: the anonymous counter is in M1 as a GoatCounter event `count-<gov id>` from a separate `us-count.js`.
- Decision 9: item withholding is a directory field `items: shown|withheld` (default withheld), not an `sd*` id rule.
- Accepted: N1 (one fixed Menu fragment in the shared footer, enforced by an exact-string test) and N2 (device storage
  keeps government ids plus Census names).
