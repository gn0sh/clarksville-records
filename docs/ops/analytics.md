# Visitor counting (GoatCounter): how to turn it on

Decision and data rules: `docs/adr/0008-visitor-analytics.md`. Code: `sitegen/analytics.py`, `site/static/count.js`.

## What it counts
Visits (page path only, never the part after `?`), top pages, the outside site that linked here (its address, not
the page), browser, system, screen size and country (GoatCounter works these out; it keeps no IP address), and two
events: `support-click` (a Buy Me a Coffee link) and `search` (once per page view, never the words). Nothing typed
into the address box or the search box is ever sent. No cookies, no consent banner. Do Not Track and Global
Privacy Control browsers are not counted.

Content counts (meetings, votes, items, documents per body, what is still coming, last fetch day) are on the site's
own page `stats.html`, built from the data every day; they need no account.

## State today: OFF
`config/site.yml` has `analytics: {provider: goatcounter, code: ""}`. With the code empty no page loads the counter
and nothing leaves a visitor's browser.

## Brian: create the account (about 3 minutes, free)
1. Open https://www.goatcounter.com/signup on any device.
2. **Code**: type `daylight-gnoshcodes` (this becomes `https://daylight-gnoshcodes.goatcounter.com`, your dashboard;
   any lower-case letters, digits and dashes work, but tell us the exact one you typed).
3. **Site domain**: `daylight.gnoshcodes.com`.
4. **Email** and **Password**: your own. Leave everything else as it is. Tap **Sign up**.
5. Open the confirmation email from GoatCounter and tap its link. Done: you should see an empty dashboard.
6. Leave the dashboard private (the default). The later private dashboard will use an API key you create then.
7. Reply in the Daylight thread with one line: `GoatCounter code: daylight-gnoshcodes` (or the code you chose).

## The team: switch it on (one-line PR)
1. On a branch, edit `config/site.yml`: `analytics: {provider: goatcounter, code: "daylight-gnoshcodes"}`.
2. Run `python -m pytest -q tests/test_analytics.py tests/test_csp.py`; `test_config_ships_with_counting_off` fails
   by design: change its expected code in the same PR.
3. The next pages build loads `static/count.js` on every page, sets `connect-src https://<code>.goatcounter.com`, and
   About and Method name GoatCounter and what is counted. `qa/site_checks.py` (`external`) checks all of it.
4. Merge after review; the next daily build carries it (a deploy, so it follows the normal release go-ahead).
5. Check: open the site on a phone, wait a minute, refresh the GoatCounter dashboard: one visit on `/index.html`.

## Turning it off
Set `code: ""` again (one-line PR). Counting stops at the next build.
