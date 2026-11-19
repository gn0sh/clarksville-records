# National Daylight: open facts (deep-researcher, 2026-11-19, docs pages only)

Manager notes on top (2026-11-19):
- CONFLICT: the researcher infers tags are a paid $9 add-on, but our own sign-up test on Buttondown's free plan
  (docs/platform-facts.md, Nov 18) saw tags applied. Treat our test as the stronger evidence; re-check on the account
  before relying on tags past 100 subscribers.
- Geocoder: keep the browser JSONP call (as Daylight does today). A server proxy would make us receive addresses,
  which breaks the privacy promise. Show the Census non-endorsement notice.

## Q1 Buttondown
- API emails take `filters` (tag rules, and/or). Old included_tags/excluded_tags removed in API 2024-08-15. https://docs.buttondown.com/api-emails-create
- No documented per-day send quota. Pricing "assumes at most one email a day to your entire subscriber base"; more needs usage pricing. https://buttondown.com/pricing
- Django-style templates with `subscriber.tags` and `subscriber.metadata`, e.g. `{% if "berlin" in subscriber.tags %}`: one send can carry per-subscriber sections. https://docs.buttondown.com/template-variables ; https://buttondown.com/blog/tags-in-email-body
- Rate limits: 600 requests/min; POST /v1/subscribers 100/day (bulk via imports). https://docs.buttondown.com/api-rate-limits
- Pricing page now uses add-ons: free first 100 subscribers; tagging & segmentation listed as a $9/mo add-on; per-count prices did not render in fetch. API version 2026-04-01+ needs `X-Buttondown-Live-Dangerously` on first about_to_send per key.
- Implication: ONE weekly send with per-subscriber conditional sections, not one send per body.

## Q2 Census Geocoder
- `returntype=geographies`; default layers include County, Congressional and State Legislative Districts, Census Designated Places, County Subdivisions, Incorporated Places. School districts need `layers=` (IDs to test). https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html
- No CORS; `format=jsonp&callback=` works from a browser. No key; no published rate limit. Benchmarks: Public_AR_Current (4), vintage Current_Current. https://geocoding.geo.census.gov/geocoder/benchmarks
- Census API terms (assumed to apply): "as is", may block excess use, non-endorsement notice. https://www.census.gov/data/developers/about/terms-of-service.html

## Q3 Legistar
- No public list of client names; slug usually matches the city's *.legistar.com subdomain (exceptions exist). https://groups.google.com/g/open-civic-data/c/sMxWQs2JwZU
- "Some clients require an API token"; some clients have the API not enabled (error names InSite connection string). 1000 rows per query; page with $top/$skip; no terms or rate policy published. https://webapi.legistar.com/Home/Examples
- Count: "70% of the largest cities and counties" (Granicus brochure); total unknown.
- Implication: per-body states "token required" and "API not enabled" are first-class; discovery is per body, on request.

## Q4 Officials' contacts
- Google Civic Information "representatives" endpoint retired April 30, 2025; docs now list elections, voterinfo, divisions only. https://developers.google.com/civic-information/docs/v2
- No free local-officeholder API found (Cicero, Ballotpedia, BallotReady are paid). Implication: record each body's clerk contact by hand from its own site, with source and date.
