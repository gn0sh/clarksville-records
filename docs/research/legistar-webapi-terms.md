# Legistar Web API: terms check (P1, daylight-national M2)

Searched 2026-11-19 (deep-researcher, sonnet/medium). No request was made to any *.legistar.com host.

**Verdict:** unclear, leaning OK to read politely for Salem. No primary source states terms, rate limits or attribution.

## Observations (sourced)
- Tokens are per client (city). NYC requires a token by form (https://council.nyc.gov/legislation/api). A secondary source
  (https://apify.com/talcoe/legistar-agendas.md, undated) lists denver, seattle, lacounty, boston, phoenix as anonymous.
- A city must enable the API: a 2019 report shows Cleveland's client "not set up in InSite"
  (https://groups.google.com/g/open-civic-data/c/sMxWQs2JwZU). Unconfirmed.
- Granicus support describes the API without terms, limits or tokens
  (https://support.granicus.com/articles/en_US/Knowledge/Legistar).
- salem.legistar.com is a live portal. A search engine has indexed `webapi.legistar.com/v1/salem/matters/8174`.

## Inferences
- Salem's client is likely open without a token (medium).
- Each new council needs its own token check (high).
- No published limit, so keep the polite defaults: low budget, one fetch per body per day, cache by LastPublished,
  identifying User-Agent, stop on 403/429 (C1 tenant rule) (high on approach).

## Unknowns (fold into H1)
- robots.txt of webapi.legistar.com and salem.legistar.com: H1 reads it first and stops if disallowed.
- Granicus terms that may bind API users; https://webapi.legistar.com/Home/Examples not read.
- Whether Salem's Events/EventItems are fully populated.
- If H1 gets 400/403: treat Salem as token-only, record it, and ask before any other route.
