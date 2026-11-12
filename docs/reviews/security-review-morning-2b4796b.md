# Security review: morning note (Daylight M3), origin/claude/sqv6p9-morning @ 2b4796b

Diff: merge-base 81c2708 (origin/claude/project-thread-sqv6p9) .. 2b4796b, 26 files, +2855/-54.
Reviewer: security-engineer, 2026-11-10. Read-only on product code.

## Verdict: PASS WITH CONDITIONS
Release recommendation: **OK WITH FOLLOW-UPS**. No critical or high findings. The shipped state (enabled: false)
sends nothing and loosens nothing. Finding 1 must be fixed before `morning_note.enabled` is set to true.

Most serious problem: once the note is enabled, two privacy statements already on the site become false (finding 1).

## Findings

### 1. morning-security/privacy-text-matches-data-flow (MEDIUM, enabled state only; blocks enabling, not this merge)
- Location: site/templates/method.html.j2:20 ("It stays on your device and is never sent anywhere."),
  site/templates/index.html.j2:26 ("Nothing is sent anywhere and no cookies are used."), index.html.j2:37;
  versus site/templates/alerts.html.j2:24-25 and site/static/morning.js:80-84, which fill hidden
  metadata__district / metadata__ward inputs from localStorage `cr-your-seats` and post them to the provider.
  Confirmed in an enabled build (build/on): method.html and index.html still print both sentences.
- Exploit scenario: no attacker needed. A resident relies on "never sent anywhere", signs up, and their
  district and ward go to a third party next to their email address. That is a false privacy statement on a
  public site.
- Fix: make both sentences depend on note.enabled ("...never sent, unless you sign up for the morning note,
  which sends them to {provider}"). Add a Morning note paragraph to method.html: what is sent (email, lists,
  district, ward), to whom, how to unsubscribe, link privacy_url. Add a test: an enabled build has no
  "never sent anywhere" or "Nothing is sent anywhere" sentence. Also update the static/seats.js header comment.
- Owner: frontend-engineer (templates, test); technical-writer (wording).

### 2. morning-security/privacy-text-complete (LOW, enabled state only)
- Location: config/site.yml `morning_note.page.sent_line`; docs/architecture/morning-note.md:142 (Buttondown
  collects open/click data unless it is turned off).
- Exploit scenario: the sent line lists email, lists and seats, but the provider also gets the visitor's IP and
  browser details and, by default, open/click tracking. Because the form is an unauthenticated cross-origin POST,
  anyone can also sign up someone else's address (subscription bombing).
- Fix (launch preconditions, recorded in docs/platform-facts.md): turn on double opt-in at the provider and turn
  off open/click tracking; extend sent_line ("...and, like any website, your IP address"). The architecture
  already assumes double opt-in, so verify it at account setup.
- Owner: devops-engineer (provider setup checklist), technical-writer (sent_line).

### 3. morning-security/seat-consent (LOW, enabled state only)
- Location: site/templates/alerts.html.j2:24-25, site/static/morning.js:80-84.
- Exploit scenario: the stored seats go out silently in hidden fields. A visitor who once clicked a district on
  a shared or borrowed device sends a seat they never chose for this form.
- Fix: next to sent_line, show the values being sent ("District 5, Ward 3"), or add an "include my saved seats"
  checkbox that is ticked by default and visible. Without JS the inputs stay disabled; keep that.
- Owner: frontend-engineer.

### 4. morning-security/href-scheme-defense (LOW, defense in depth; same pattern as before this diff)
- Location: sitegen/morning.py `_rpc_documents` / `_agenda_only_documents` copy `s['url']` into entries;
  site/templates/morning.html.j2:22 renders `e.source.url` as an href; sitegen/feeds.py `_rpc_entries` as an
  Atom link. RPC facts (sitegen/rpc.py load) and county agendas (sitegen/county_agendas.py load) are not
  checked by build._is_https_uri, unlike facts.json and finance.json. qa/site_checks.py:458 skips any
  non-http(s) href instead of failing it. feeds._sub cleans element text, not attribute values.
- Exploit scenario: a bad URL in those files (a collector bug or a hand edit) such as `javascript:...` would
  become a clickable link on the preview page and in feeds. Not exploitable today: the collectors only keep
  https URLs on allowed hosts (collector/rpc.py:81, collector/county_agenda.py:113), and Jinja autoescape stops
  attribute breakout (tested: a `"` in a URL renders as &#34;).
- Fix: in morning_page.preview (and feeds._rpc_entries), drop a source URL unless it passes build._is_https_uri,
  or validate RPC and agenda source URLs at load. Make site_checks fail on any href scheme other than
  http/https/relative.
- Owner: backend-engineer.

### 5. morning-security/csp-origin-self-validating (LOW / informational)
- Location: sitegen/morning_page.py:39-52 (`enabled()`, `form_origin()`).
- Exploit scenario: form_origin() trusts that morning.problems() has already rejected bad values. Called
  directly, it returns `https://evil.com;script-src *` for that form_action (tested), which would inject a CSP
  directive. Not reachable: build.py:409 always runs problems(), and its `_HTTPS` regex rejects it (tested
  `;`, space, `*`, userinfo, http, newline, U+2028; all rejected).
- Fix: in form_origin(), require morning._HTTPS.fullmatch(form_action) and return None otherwise.
- Owner: backend-engineer.

### 6. Needs verification: CSP form-action and the provider's redirect
- Chrome applies form-action to redirects after the POST. If the provider's thank-you or confirm redirect leaves
  the form_action origin, the submit is blocked. This is a functional problem, not a security one. Test one real
  submit at enable time; the right fix is the provider's same-origin redirect, not a wider CSP.

## What I checked, and why it holds
- CSP off: built `--target pages` from the committed data. All 444 pages carry the base policy (form-action
  'self', connect-src 'none'). alerts.html has no <form>, no action and no email input, and its checkboxes have
  no name attribute, so nothing can be submitted. The morning/index.html picker has no name either.
- CSP enabled: built with enabled: true, Buttondown form_action and privacy_url (scratch config, restored).
  Exactly one page (alerts.html) differs: `form-action 'self' https://buttondown.com`. connect-src stays 'none'
  and script-src is unchanged. All other 442 pages, the landing page (geocoder hash) and morning/index.html are
  unchanged.
- Config gate (morning.problems): enabled must be a bool; a form_action while disabled is refused; enabled needs
  provider, an https form_action and an https privacy_url (the `_HTTPS` host class blocks CSP metacharacters);
  form_fields must be plain field names. Tested with hostile values.
- No mail or provider traffic while disabled: grep for smtplib/sendmail/provider names/urlopen/requests.post
  outside the collector found nothing. No workflow or deploy change in the diff. morning.js has no fetch, XHR,
  beacon or WebSocket (tests/test_morning_page.py:106 enforces this).
- Personal data on the device: no new storage key. Seats are read-only from `cr-your-seats` (two integers 1-999,
  parsed by seats.js num(); morning.js num() again). Picks live only in the #lists= fragment and browser history,
  and are never sent (fragments are not sent in requests). Retention is the same as before: until Forget, or the
  history is cleared.
- morning.js parser: parseLists is a strict anchored regex `[a-z0-9,_-]*` filtered to known keys (tested `<img>`,
  %2C, __proto__, newline, missing #). No innerHTML. setAttribute only with config-derived base + known keys.
  hidden/checked toggles only. No open redirect: no location assignment; replaceState uses the same fragment only.
- Templates: autoescape is on for *.j2 (build.make_env). I rendered morning.html.j2 with a hostile title, body
  name, data-* attributes, source URL and unplaced text; all were escaped. External source links use
  target=_blank with rel=noopener noreferrer.
- Feeds: ElementTree escapes; feeds.clean drops XML-illegal characters from text; tests/test_alerts.py:119 covers
  markup in titles. Finance and facts source URLs are schema-checked https.
- Published morning/*.json: built data only, no visitor data. Entries carry no person names (design M2).
- Third-party requests: none added in either state, besides the form POST itself when enabled.
- Tests: full suite 1128 passed, 4 skipped. qa/site_checks on the pages build: RESULT PASS (41 feeds, 1246 entries).
- Not checked: the sender job and API key (they do not exist yet; a separate review before they are added);
  the provider's actual settings.

## Delta re-review 1d638db (origin/claude/sqv6p9-morning-sec, fa9e9b0..1d638db, 4 commits), 2026-11-10

### Verdict: PASS. Release recommendation: OK WITH FOLLOW-UPS (one new low finding). Email stays off in committed config (tests/test_morning_page.py test_committed_config_keeps_email_off).

### Status of each finding
- 1 privacy-text-matches-data-flow: **CLOSED.**
  - Built enabled with the Buttondown values (scratch config, restored): no page prints "never sent anywhere" or "Nothing is sent anywhere".
  - index.html and method.html print `seats_sent`, and method.html gains a Morning note section (what is sent, to whom, unsubscribe, privacy link).
  - The off build keeps the original sentences. Tests cover both states.
- 2 privacy-text-complete: **MOVED TO THE RUNBOOK; ACCEPTED.** docs/ops/launch-runbook.md now lists double opt-in, tracking off, the sent_line wording, platform-facts, the real-submit redirect test and a sender review, all before `enabled: true`. That is adequate because nothing is sent while off. The runbook cites docs/reviews/security-review-morning-2b4796b.md, which the manager must keep in step with this delta.
- 3 seat-consent: **CLOSED.**
  - A visible box shows the numbers ("District 5, Ward 3"). The seat fields are posted only while it is ticked (seatPost needs include === true), and never without JS.
  - The box itself has no name, so it is never posted. The browser test covers unticked, re-ticked, district-only and no-seats cases.
- 4 href-scheme-defense: **CLOSED.**
  - morning_page._source_url and feeds._source_link drop any URL that is not https, using build._is_https_uri.
  - site_checks.bad_scheme now fails other schemes in links, resources and feed links. It strips tabs, newlines and control characters first, as browsers do.
- 5 csp-origin-self-validating: **CLOSED.** form_origin() checks `morning._HTTPS.fullmatch` itself (morning_page.py:54).

### (a) The site_checks allowance: it holds
I tested check_external against mutated copies of an enabled build (Buttondown action):

| Mutation | Result |
|---|---|
| A second CSP origin on alerts | FAIL |
| A wrong CSP origin | FAIL |
| `https:` wildcard | FAIL |
| Provider origin added to about.html's CSP | FAIL |
| The same form on about.html | FAIL |
| A different action path on alerts | FAIL |
| A second off-site form on alerts | FAIL |
| connect-src loosened | FAIL |
| A second CSP meta | FAIL |
| The enabled build checked against the committed (off) config | FAIL |

- The CSP comparison is exact list equality, and the allowance is keyed on `rel == "alerts.html"` and an exact match on the action.
- Off state: `note_action` is None, so the checks are the same as before plus the new scheme checks; it is stricter. The privacy URL is allowed only while enabled.
- The enabled build passes qa.site_checks (RESULT PASS).
- Limit: QA compares against config, so a wrong origin typed into config itself would pass. The runbook's real-submit step is the human check for that.

### (b) The seats box ticked by default: acceptable (judgment call, medium confidence)
- The numbers are printed next to the box before sending, and the sent line and Method page disclose it.
- The default lists ("Zoning near me", "My two seats") only work with seats, so an unticked default would make most sign-ups get silently empty notes.
- The data is a coarse district or ward number, and the site is US-only with no EU opt-in duty. This is a judgment call, not legal advice.
- Condition: the box must stay visible whenever seats would be posted. Tests enforce this today.
- Optional: say near the box that the zoning and seat lists need it ticked.

### New finding
- **morning-security/qa-formaction-gap** (LOW): qa/site_checks.py:439 records `<form action>` but not `formaction` on `<button>` or `<input>`. Tested: `<button formaction="https://buttondown.com/other">` on alerts.html passes check_external.
  - Limit on harm: the CSP still keeps any such post on the provider's origin on alerts.html, and on 'self' on every other page.
  - Fix: add a formaction attribute to `resources` (tag "form") so the exact-action rule applies. Owner: qa-engineer or backend-engineer.
