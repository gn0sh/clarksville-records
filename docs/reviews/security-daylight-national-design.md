# Security review: Daylight Digest design (f8bb3f8), 2026-11-19

security-engineer, opus/high. **Verdict: OK WITH CHANGES.** No critical or high findings. Gates: R1 (M1 live) blocked
until 1, 2 (incl. the Q2 add-vs-replace tag test), 4, 5, 9 are done; H1 (first Legistar request) blocked until 3, 6, 7.
If Q2 shows a form post REPLACES tags, finding 2 becomes high and blocks R1.

## Medium
1. `national/csp-jsonp-gadget`: parent CSP allowing the Census JSONP path lets any HTML injection load a JSONP with an
   attacker callback. Fix: serve a static `/us/geo-frame.html` (sandbox allow-scripts, own meta CSP allowing only the
   Census path), address passed by postMessage after "ready"; parent script-src stays 'self'. Census path never on
   `/us/b/*` or `/us/cover/`. Follow-up: same for the existing landing box. Owner: frontend-engineer + architect.
2. `national/tags-existing-subscriber`: anyone can post req-/note-/wk- tags for a known email; existing subscribers get
   no confirmation. Inflated R8 counts, unwanted "it's open" emails, M4 wk- tag sign-ups. Fix: Q2 tests add vs replace
   (team address with note- tags posts only req-, read tags by API) and gates R1; counts are advisory to Brian's R8
   call; design consent for wk- tags before M4. Owners: qa-engineer, architect.
3. `national/feed-ics-injection`: CR/LF in Legistar text can inject ICS properties/VEVENTs. Fix: write ICS in Python,
   RFC 5545 3.3.11 escaping, strip controls (feeds.clean), fold at 75 octets; fixture with `\r\nBEGIN:VEVENT`.
   Owner: backend-engineer.
4. `national/url-scheme-untrusted`: API URLs (EventAgendaFile, EventInSiteURL, meeting_url, items[].source.url) reach
   JSON/ICS/Atom with no CSP. Fix: config.https_link + per-platform host allowlist, checked at collection and build;
   bad URL dropped, fall back to official_url. Owner: backend-engineer.
5. `privacy-withhold/national-prefix`: withhold keyed on sd* ids fails open for school/youth boards listed under a
   city or on a city's Legistar client (family already hit 3 times). Fix: directory field `items: shown|withheld`,
   default withheld; build refuses shown for sd*; collector reads no items unless shown; architect states the
   invariant and consumers before C2. Owners: architect, backend-engineer.
6. `national/writer-token-scope`: national-update.yml as a second contents:write writer parsing untrusted text. Fix:
   collect job read-only; push job writes only data/national/** to national-data; pin gate --cert-identity per
   workflow and branch; strict regex on ids before they become paths, in collector and builder. Owners: devops,
   backend.
7. `national/r5-not-enforced`: merging a covered Legistar entry makes the collector call that client; nothing enforces
   Brian's OK. Fix: `host_ok: {date, link}` required on non-daylight entries, build and collector refuse without it;
   directory checks (page/full_url regex, tz zoneinfo, client regex, exact final_statuses, yaml.safe_load); fix the
   checked_url example. Owners: backend, architect.

## Low
8. `national/tags-location-disclosure`: requested body ids reveal rough location at Buttondown; GoatCounter paths tie a
   body to an IP. Fix: AC9.2/9.3 copy says requested governments show roughly where you are; Method page lists
   GoatCounter paths. Owners: ux-designer, technical-writer.
9. `national/postmessage-hardening`: copy address.js checks (e.source, origin "null", string + length cap, JSON.parse),
   GEOID regex `^\d{5,10}$`, null-prototype lookups, directory via |tojson. Owner: frontend-engineer.
10. `national/tenant-key-normalize`: lowercase the Legistar client path segment before matching. Owner: backend.
11. `national/form-abuse`: scripted confirmation emails and unlimited tag names. Fix: confirm Buttondown firewall/IP
    filtering is on (free); request report ignores req- ids not in the directory. Owner: manager / qa (Q2).
12. `national/untrusted-size`: cap item text (~2,000 chars), items per meeting, meetings per body; strip bidi
    overrides and log. Owner: backend.
13. `national/unfiltered-send`: runbook line: every manual Buttondown send must be filtered. Owner: technical-writer.

## Checked and holding
srcdoc sandbox without allow-same-origin; no-referrer on frame and script; address input has no name, form no action;
count.js sends only pathname and honors DNT/GPC; no error reporting; Jinja autoescape on .j2; Atom via feeds.clean and
ElementTree; fetcher follows no redirects, https/443 only, allowlist enforced, stops on 403/429; PDFs linked only;
collector never changes status automatically; morning sender reads only note- tags.

## Needs verification
Census JSONP callback-name checking (proxy refused); Buttondown add vs replace (Q2); MAX_ANSWER fit for 20 matches x 6
layers.
