# Research: address lookup and map pin (deep-researcher, 2026-11-08)

- Best data, but restricted: the APSU-hosted county E911 address points (`apnsgis4.apsu.edu/.../CMCGIS/Address_Points`, updated weekly, with lat/lon fields). Their terms say: "not to be redistributed, republished, or repurposed without prior written consent from APSU". We would need written consent, which means an email from Brian (hard stop 4). We are not using this source.
- APSU also hosts GeocodeServers (Multirole, primary_pro, Secondary_pro). The same terms question applies, and CORS is unknown.
- Census geocoder (VERIFIED): `geocoding.geo.census.gov/geocoder/locations/onelineaddress?...&format=jsonp`. It does not support CORS, so a browser must use JSONP. The visitor's address goes to the Census Bureau, so the page needs a privacy note. Rural accuracy is weaker. The data is public domain (inferred).
- GoVoteTN: https://web.go-vote-tn.elections.tn.gov/ offers "Search By Address". Unverified whether it returns the county commission district. There is no public API, and we only link to it.
- Georeferencing: fit an affine transform from 6 or more control points (road interchanges, the KY state line, river crossings at the county line) between the PDF-space map and OSM/TIGER coordinates, and check residuals on a held-out point.

## Decision (manager, 2026-11-08)
- Show a plain GoVoteTN link beside the map now.
- The address pin uses the Census JSONP geocoder, with a privacy note, plus a point-in-polygon test against our own traced districts after georeferencing. No APSU data is used.
