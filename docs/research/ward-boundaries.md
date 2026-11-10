# Research: Clarksville City Council ward boundaries (backend-engineer, 2026-11-10)

Question: is there a public, free, citable source for the 12 current ward polygons (GeoJSON or ArcGIS FeatureServer)?
Short answer: **no machine-readable source is reachable from this sandbox.** One reachable, citable, vector-PDF source exists (RPC, Feb 2026). The best GeoJSON source (APSU/county ArcGIS) is blocked by the proxy.

Politeness: UA `ClarksvilleRecordsBot/0.1 (+https://github.com/gn0sh/clarksville-records)`, 10 s between requests per host, public pages only. Requests: www.cmcrpc.com 5 (robots x2 incl. redirect check, home, /maps/, one PDF), www.clarksvilletn.gov 2 (robots, home). cityofclarksville.com not touched.

## Reachability (proxy, 2026-11-10)
| Host | Result |
|---|---|
| www.cmcrpc.com, cmcrpc.com | reachable. robots.txt: `User-agent: *` `crawl-delay: 10` (we obeyed) |
| www.clarksvilletn.gov | reachable. robots.txt allows `/` except admin/search/map.asp(x)/RSS. Home page has no GIS or ward-data link (only an ArcGIS StoryMap) |
| montgomerytn.gov, comptroller.tn.gov | reachable, robots allow all. Not searched further: the comptroller and county pages have no ward layer (the earlier research found only PDFs there) |
| gis.mcgtn.org, apnsgis4.apsu.edu | **blocked (403 on CONNECT), needs allow-listing** |
| cmcrpc.maps.arcgis.com, experience.arcgis.com, www.arcgis.com, hub.arcgis.com, services.arcgis.com, services1.arcgis.com, tigerweb.geo.census.gov, gis.tn.gov, data.tn.gov | **blocked, need allow-listing** |

## Candidate A (best geometry, not fetchable here): APSU MontElections layer 1 (12 city wards)
- Service: `https://apnsgis4.apsu.edu/arcgis/rest/services/CMCGIS/MontElections/MapServer/1` (from `docs/research/district-ward-map-data.md`, verified 2026-11-07 by an earlier session; I could not re-verify).
- Fields `district`, `councilmem`, `startterm`, `endterm`, `webpage`. Service note "Last Updated: 4/1/2022 MEC", copyright "APSU GIS". No stated licence. The `councilmem` names are stale: use geometry and ward number only.
- Download (MapServer supports GeoJSON): `https://apnsgis4.apsu.edu/arcgis/rest/services/CMCGIS/MontElections/MapServer/1/query?where=1%3D1&outFields=district&outSR=4326&f=geojson`
- Count: 12 expected. Date 4/1/2022, so it predates RPC's Feb 2026 poster: **check it against the poster, since annexations since 2022 may have changed lines** (RPC also publishes `AnnexationMap_03262026.pdf`).
- Terms: APSU's address-point service forbids redistribution without written consent. This layer states no terms, but the same host and owner apply. Recommend asking APSU/RPC in writing before publishing this geometry (an email from Brian, hard stop 4). The county mirror `https://gis.mcgtn.org/arcgis/rest/services/CityWard/MapServer/1` states no metadata and needs the same check.
- Allow-list needed: `apnsgis4.apsu.edu` (and/or `gis.mcgtn.org`).

## Candidate B (fetched, usable now): RPC "City Council Wards" PDF map, updated 2026-02-25
- Page: `https://www.cmcrpc.com/maps/` ("City Council Wards", "Downloadable PDF Maps: City Wards 36x36 Poster, Updated February 25, 2026"; also an indexed 8.5x11 mapbook).
- Poster: `https://www.cmcrpc.com/wp2025/wp-content/uploads/2026/02/ClarksvilleCityWardsPoster.pdf` (200, application/pdf, 2,123,541 bytes, 1 page, 2592 x 2592 pt, created by Esri ArcGIS Pro 3.6.2 on 2026-02-25).
- Mapbook: `https://www.cmcrpc.com/wp2025/wp-content/uploads/2026/02/CityWardsMapBook.pdf` (not fetched).
- Format: **vector** PDF (about 275,000 path operators, plus a few small raster logos), with the text labels 1 to 12. There is no embedded georeference (no /VP or /Measure). The wards can be traced and georeferenced the same way as the county districts (see `config/localities/montgomery-tn/georef.json`: affine fit from 6+ control points, held-out residual check). Not done here.
- Currency: Feb 2026 is after the 2021-11 redistricting and the 2022 elections, so it is the current map. I did not trace it, so ward-by-ward agreement with the 12-ward layout is by labels only (labels 1 to 12 present).
- Licence: none stated on the page. It is a public government map. Citing it and tracing it is a derivative work. The county PDFs were handled the same way, so this is consistent with prior practice. Confirm reuse with RPC if we want certainty.
- Interactive viewer (not reachable): `https://cmcrpc.maps.arcgis.com/apps/webappviewer/index.html?id=35defc901f754475b758aedb768fcce5`. Its web map almost certainly points at an RPC-hosted FeatureServer on `services*.arcgis.com`, which would be the ideal citable source. To find it: allow-list `cmcrpc.maps.arcgis.com` and `www.arcgis.com`, read `https://www.arcgis.com/sharing/rest/content/items/35defc901f754475b758aedb768fcce5/data?f=json`, then query the layer's `/query?where=1%3D1&outFields=*&outSR=4326&f=geojson`. This is a guess, not verified.

## Not found
- clarksvilletn.gov: no ward GIS page reachable (home page links only a StoryMap). TN Comptroller and Census TIGERweb: wards are not in them (TIGER has no council wards; the comptroller site was not searched deeper). 2022 redistricting match was not confirmed from data.

## Recommendation
1. Ask the manager to allow-list `apnsgis4.apsu.edu` and `cmcrpc.maps.arcgis.com` + `www.arcgis.com` (+ `services.arcgis.com`, `services1.arcgis.com` if the web map uses them). Re-run the queries above, compare feature count (12) and shapes with the Feb 2026 poster.
2. If not allowed, trace Candidate B (cited, current, same method as the county map).
3. Either way, get written reuse confirmation from RPC/APSU before publishing if we want to ship the geometry (Brian's email, hard stop 4). Until then, the preview is internal.
