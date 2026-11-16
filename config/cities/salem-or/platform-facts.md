# Platform facts: Salem, OR

Draft city. Record here every fact the collection depends on, with how it was verified (fetch date, page, who
checked). Copy each check into the host's `robots` and `terms` lines in `city.yml`, so `python -m cities check
salem-or` can see it.

## Hosts

| Host | robots.txt | Terms of use | Notes |
|---|---|---|---|
| webapi.legistar.com | not checked | not checked | Legistar's public Web API (`/v1/salem/...`) |
| salem.legistar.com | not checked | not checked | the city's Legistar site; agenda and minutes files may sit on another host (often `<client>.legistar1.com`): add it when seen |

## Portal

- Legistar. Seen 2026-11-15: `https://webapi.legistar.com/v1/salem/matters/8174` answered JSON with
  `MatterBodyName` "City Council". Body list, vote labels, official title and earliest year: not checked.

## Never collect

- (none known yet)
