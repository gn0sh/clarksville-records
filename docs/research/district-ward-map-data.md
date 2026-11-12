# Research: district and ward map data (deep-researcher, 2026-11-07)

Sources were queried live on 2026-11-07. Each item is marked verified (V) or inferred (I).

## Boundaries (geometry)
- County Commission districts, current 21 (V): APSU GIS `https://apnsgis4.apsu.edu/arcgis/rest/services/CMCGIS/MontElections/MapServer/2`. Fields: `district`, `commission`, `pic_links`. Service note: "Last Updated: 4/1/2022 MEC". Copyright: "APSU GIS". Formats: JSON, GeoJSON, PBF. Native CRS is EPSG:2274; query with `/query?where=1%3D1&outFields=*&outSR=4326&f=geojson`.
- City wards, current 12 (V): same service, layer 1. Fields: `district`, `councilmem`, `startterm`, `endterm`, `webpage`.
- County mirrors (attributes not compared): `https://gis.mcgtn.org/arcgis/rest/services/CountyDistricts/MapServer` (layer 0) and `.../CityWard/MapServer` (layer 1). They state no metadata.
- The `commission` names in the APSU layer are stale. Use only geometry and district number from it; take names from the rosters.
- Boundaries before 2022 exist only as PDFs. They are on `https://montgomerytn.gov/election/2021-redistricting`: "City of Clarksville Wards 2020.pdf", "Redistricting20211018.pdf" (proposed county map) and "CityRedistricting.pdf". The old county district map PDF was not found. No GIS layer for the old lines exists.
- Licence: neither service states terms. We treat the data as public record. Confirming reuse with the county or APSU would mean an email from Brian (hard stop 4), so it is not a blocker for the private preview.

## Redistricting dates
- The county map was approved on 2021-11-08 and kept 21 districts; numbers 19 and 20 were swapped by amendment (V, ClarksvilleNow). The first election on the new lines was 2022-08-04. Seating on 2022-09-01 (I, medium-high).
- The city map passed first reading 12-0 on 2021-11-04. New wards likely applied from the Nov 2022 election, with terms from Jan 2023 (I).

## Rosters
- Current county list: `https://montgomerytn.gov/storage/departments/election/Elected%20Officials%20List.pdf`. It is undated and gives no history.
- 2022 county results: ClarksvilleNow `?p=403377`. They cover only 14 districts.
- The best source for who held each seat and when is our own roll calls (who answered at each meeting), plus a roster file in config that maps official to district with start and end dates and the source of each row.
- City: the APSU layer gives current holders and terms. Its Ward 2 entry conflicts with the county PDF, which shows Ward 2 vacant. History must come from clarksvilletn.gov council pages, which have not been fetched yet.

## Base map
- The OSM tile policy allows small interactive use with attribution, but there is no SLA. Recommendation: no basemap. Render the simplified GeoJSON as inline SVG at build time, with no external dependency.

## Recommendation
- Geometry: APSU layers 1 and 2, fetched once and cached in the repo with a source URL and fetch date, in config per locality.
- Seat history after 2022-09-01: the roster file plus roll-call attendance. Before that date, district lines differed, so the old-district period links to the PDF map.
