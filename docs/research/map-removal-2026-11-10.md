# Map removal: where the map is and what the address lookup needs (2026-11-10)

Owner decision (Brian, 2026-11-10): "the juice is not worth the squeeze with the map, especially on mobile." Remove the
district/ward map; address search is the front door. Investigated on `claude/hu3mew-unofficial` at 249cc47.

## Where the map appears (observed, by grep and reading)
- Landing (`site/templates/index.html.j2`): the "Map shows" layer switch, the inline SVG (`_map.html.j2` `county_map`,
  links=true: county outline, 21 district paths with number labels, 12 ward paths, river), the ward-lines source note,
  the "About this map" disclosure (district source, 19/20 numbering note, old-lines link), the "Not sure of your
  district?" line under the map, and copy: "find it on the map", "or a click on the map", "listed below the map".
- Seat pages (`district.html.j2`): a small outline SVG with that district hatched, plus its caption.
- Scripts: `static/map.js` (list-to-shape highlight, map only); `static/seats.js` (click on a map area saves a seat);
  `static/address.js` (reads the shapes from the SVG, draws a pin, marks `.is-found`).
- Python: `sitegen/views.py` `map_context` (SVG data for both pages), NAV label "Map (home)" and page name "Map".
- CSS: `.county-map`, `.district`, `.ward`, `.layer-switch`, `.landing-grid/.landing-map`, `.addr-pin`, `.map-about`,
  `.map-placeholder`, hatch, `body.show-wards` and the phone/desktop layout rules around them (`static/style.css`).
- Other copy: `council_home.html.j2` ("Find your ward by address on the map"), `method.html.j2` ("click a district on
  the map"), `about.html.j2` ("menu, map and search" scripts), `config/site.yml` (`geocoder_label` comment,
  `morning_note` `seats_hint` "on the map page", `district_layer`/`ward_layer`/`city_label`).
- Tests: `test_landing_search_nav.py` (map tests), `test_your_seats.py` (DOM order vs the SVG), `test_address_box.py`
  and `address_browser.js` (pin, `.is-found`, ward layer), `test_csp.py`/`csp_browser.js` (map hover highlight),
  `test_visual_refresh.py` (nav labels), `test_map_seats.py` (map file size and drawing checks).
  `qa/site_checks.py` has no map-only check: it allows the boundary sources' URLs as `data-ext="map"` links.
- Not on the map: search, nav (only its label), the seat lists, vote-history links. No tiles or image assets exist;
  the map is inline SVG only.

## Does the address lookup need the traced geometry? Yes.
`static/address.js` places the Census geocoder's point with `CRGeoref.districtFor` (`static/georef.js`, a port of
`sitegen/georef.py`): lon/lat -> Tennessee State Plane -> the fitted affine in `georef.json` -> even-odd
point-in-polygon against the **district paths and ward paths**. Today it reads those paths from the drawn SVG. So the
geometry must stay, shipped as data (no drawing) in the address box's settings block.

Files the lookup needs (keep):
- `config/localities/montgomery-tn/districts.json`: `districts[].path`, traced from the Montgomery County Election
  Commission's 2021 redistricting map PDF (`source_url` mcgtn.org .../Redistricting20211018.pdf, 19 and 20 swapped to
  the adopted numbers); `wards.wards[].path`, traced from the Clarksville-Montgomery County Regional Planning
  Commission's City Council Wards poster (updated 2026-02-25, cmcrpc.com) and moved into the same page space.
- `config/localities/montgomery-tn/georef.json`: projection and affine (fitted to TIGER outline corners).
- Build and provenance only (not read by the site build, kept): `wards-georef.json` (poster fit, read by
  `tools/extract_ward_poster.py` and `tests/test_ward_map.py`), `tools/` tracers, `data/maps/manifest.json`.
- Drawing-only fields inside `districts.json` (`viewBox`, `outline_path`, `river_path`, `label_xy`): no longer
  rendered, but `tests/test_map_seats.py` uses them to check the trace (label inside its own district, areas add up
  to the outline). Left in place: removing them would mean re-running the tracer and losing those checks.

Credit text on the site today: under the map, "Ward lines traced from <RPC poster title>, fetched 2026-11-10" and
"Current district lines. Boundaries: <county PDF title>, fetched 2026-11-08", plus the 19/20 note. With the map gone,
the same credits move next to the address box ("How the lookup works"), so the lookup's sources stay named and linked.

**Go-live ask still applies:** the site still republishes geometry traced from the RPC poster and the county's
redistricting PDF (in the landing page source), so the written OK to reuse the traced lines (RPC and county) stays in
the go-live batch. No geometry file can be deleted.
