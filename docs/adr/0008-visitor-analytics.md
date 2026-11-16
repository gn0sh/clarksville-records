# ADR 0008: Cookie-free visitor counting (GoatCounter), off by default

Status: accepted (frontend-engineer, 2026-11-16), feature `analytics` (Daylight round 2, item I).
Brian said yes to cookie-free visitor analytics with no consent banner, on a free tool, plus a content stats page;
both later feed a private dashboard.

## Context
- Before this change the site counted nothing: no tracking code, no cookies, a Content-Security-Policy meta on every
  page with `script-src 'self'` and `connect-src 'none'` (`sitegen/views.py` `csp`), checked by `qa/site_checks.py`
  (`external`), and About's neutrality rule 6 saying "no ... visitor tracking".
- `static/search.js` keeps the search in the page address (`search.html?q=...`), and the landing address box sends
  what a visitor types to the Census geocoder. Neither may ever reach a counter.

## Decision
1. **Provider: GoatCounter** (goatcounter.com). Free for non-commercial and small sites, open source (EUPL), sets
   no cookies and stores no personal data (no consent banner needed), counts custom events, and has an API for the
   later private dashboard. Alternatives: Plausible and Fathom are paid (hard stop 3); Cloudflare Web Analytics needs
   the site on Cloudflare or their beacon script and has no custom events on the free plan; self-hosted Umami needs a
   server and database we do not run.
2. **No provider script. Our own `static/count.js` calls GoatCounter's documented `/count` endpoint.** The brief asked
   for the provider's `count.js` from `gc.zgo.at` with SRI. Concrete reasons not to: (a) its default page path is
   `location.pathname + location.search`, so `search.html?q=<what someone typed>` would be sent unless every page
   overrides it, and it sends `document.referrer` with its full path; (b) the site's rule N6 and the `external` QA
   check allow no third-party script, and a provider script can change under us (SRI pins one version, so a provider
   update silently stops counting). A 60-line first-party script sends exactly the fields listed below, is reviewed
   here, and keeps `script-src 'self'`.
3. **What is sent** (one GET per page view, `fetch` with `keepalive`, `credentials: "omit"`, `referrerPolicy:
   "no-referrer"`): `p` = `location.pathname` only (never the `?query` or `#fragment`); `r` = the origin of an
   outside page that linked here (never its path; nothing for links inside the site); `s` = screen width, height and
   pixel ratio. Events (`e=true`): `support-click` (any `a[data-ext="support"]`, the Buy Me a Coffee link) and
   `search` (once per page view, when the search form is used or search.html opens with a query). The script never
   reads a form field, `location.search` values, storage or cookies. Browsers sending Do Not Track or Global Privacy
   Control, automated browsers (`navigator.webdriver`) and non-https pages (local files, previews) send nothing.
   GoatCounter itself derives browser, system and country from the request; it stores no IP address.
4. **Off by default.** `config/site.yml` `analytics: {provider: goatcounter, code: ""}`. With an empty code no page
   loads `count.js`, the CSP is unchanged and no request leaves the visitor's browser. A code is accepted only as a
   GoatCounter site code (`^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$`); anything else fails the build. Only the `pages`
   target with real data emits it (never the claude.ai preview or a fixture build).
5. **CSP when on:** `connect-src https://<code>.goatcounter.com` on every page (instead of `'none'`); nothing else
   changes. `qa/site_checks.py` checks exactly that, and that no page names GoatCounter while the code is empty.
6. **Disclosure:** About's neutrality rule 6 and the Method page's privacy paragraph say what is counted, that there
   are no cookies, and name GoatCounter with its privacy policy, only while counting is on. Off, the old text stays.

## Consequences
- Brian creates the GoatCounter account himself (hard stop 4); turning counting on is a one-line PR setting the code
  (`docs/ops/analytics.md`).
- The private dashboard reads GoatCounter's API with a token Brian creates (hard stop 5 at that time).
- If GoatCounter ever rejects `keepalive` GET requests, swap the transport in `count.js` only; the data rules stay.
