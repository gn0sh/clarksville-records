# Unofficial-status audit, 2026-11-10

Scope: Daylight must not read as affiliated with, endorsed by, or run by the City of Clarksville, Montgomery County,
CMCSS or the Regional Planning Commission (RPC). Method: built the real site (`python -m sitegen --facts data/facts.json
--out build/site --target pages`, 444 pages, 41 feeds, 8 morning notes, plus `collector export`) and read every template
in `site/templates/`, `sitegen/feeds.py`, `sitegen/morning.py`, `sitegen/morning_page.py`, `config/site.yml`,
`site/static/` (brand files, CSS, JS), `collector/export.py` (read only), `docs/ops/launch-runbook.md`, and grepped the
built output. I did not open the four bodies' own sites, so "does not look like theirs" below is a judgment from our
own palette and layout, not a side-by-side comparison. This is not legal advice.

## What existed before this change
| Where | Wording | Verdict |
|---|---|---|
| `base.html.j2` (record pages only, via `official_record`) | "Unofficial copy. Official record: <link>" | Good, but only on pages that carry a record link |
| `who.html.j2:6` | "It is independent. It is not an official government site, and it is not run by, paid by or approved by the county, the city or any official, candidate, party or campaign." | Good, but one page, and silent on CMCSS and the RPC |
| `about.html.j2` operator section | "run by gnoshcodes ... private preview" | No disclaimer |
| Footer (every page) | "Provided as a free service by gnoshcodes." | No disclaimer. **Gap.** |
| Header / site name line | "Daylight / Clarksville-Montgomery County", then "<body> minutes, <dates>" | **Gap**: the place line sits where an official name might |
| `<title>`, meta description, Open Graph | title was `Daylight | <page>`; no description, no OG tags | **Gap** |
| Feeds (41) | subtitle was only "Each agenda and each set of minutes ..." | **Gap** |
| Morning note JSON, sign-up copy (`alerts.html`) | none | **Gap** (no sender exists in this repo yet) |
| Export (`data/*.csv`, `facts.json`) | none | **Gap** |
| 404 page | none exists (GitHub Pages serves its own unbranded default) | Nothing official-looking; carries no notice |

## Imitation check
- **Seals, logos, crests, official photos:** none. `site/static/brand/` holds only the gnoshcodes wordmarks, the
  favicon (gnoshcodes kit) and fonts. No `<img>` other than the gnoshcodes wordmark in any template. The CSS variable
  `--seal` is a colour name for an initials ring, not an image. The county map is our own SVG redrawn from boundary data
  (see lawyer list). Nothing to remove.
- **Colours / layout:** blue, orange and white "sky and sun" identity with a name plate; no government-style banner or
  ".gov" trust strip. Not matched to any official site (not compared).
- **"Official" about ourselves:** none found (`rg -i "our official|official site of"` over templates and build: 0). Every
  other use is "official minutes / official record" about the source documents. Correct.
- **Our name as "Clarksville Records":** not used on any published surface. Remaining uses: `sitegen/__init__.py` and
  `sitegen/__main__.py` (developer text, never published), the repo name `gn0sh/clarksville-records` and the interim
  `gn0sh.github.io/clarksville-records` preview URL, the collector's User-Agent (below), and `docs/ops/launch-runbook.md:87`
  where the uptime monitor entry was named "Clarksville Records". **Fixed:** now "Daylight".
- **Names that could read as official:** the nav labels "City Council" and "Planning Commission", and page names such as
  "County Commission District 7", name the body whose records the page holds. They are subject labels, not our name;
  now every such page has the footer notice. Left as is; listed for the lawyer.
- **Place line:** "Clarksville-Montgomery County" under the name is close to CMCSS and RPC's own names. Kept (it says where
  the records are from) but "Independent, unofficial" now sits directly under it on every page.

## Fix (this branch)
One config block, `unofficial:` in `config/site.yml`, read by `sitegen/unofficial.py`. Surfaces: footer of every page,
header tag, home intro, About section, `<title>`, `<meta description>`, `og:*`, every feed subtitle, each morning note's
JSON (`notice`, `email_line`), the sign-up card on Alerts, `data/README.txt` in the export, and the launch runbook.
Check: `qa/site_checks.py` line `unofficial/notice-on-every-page` (444 pages, 41 feeds, 8 notes on the real build).

## Not done, and why
- `facts.json` and the CSVs carry no in-file notice: the export code is in `collector/` (off limits for this task) and a
  CSV cannot hold a header line without breaking readers. A README sits beside them. A later collector task could add a
  `"notice"` key to `facts.json`.
- The mail sender does not exist in this repo (`sender/` is on another branch). It must print `notice` and `email_line`
  from the note JSON in every email's body and footer, and must not use an official-sounding From name or subject. Add
  the same check there.
- No 404.html: a root-relative one would break its CSS at depth. If one is added later it must extend `base.html.j2`.
- "How to report a correction" links `report.html`; until `corrections.github_repo` or `corrections.email` is set in
  `config/site.yml`, that page says corrections open at launch. Brian must pick a channel before go-live.

## For a lawyer to look at (specific, not advice)
1. Whether the notice is enough alongside the nominative use of the four bodies' names (nav labels, page titles, the
   place line, the notice itself).
2. "Daylight" trademark clearance (already flagged in `config/site.yml`).
3. The collector's User-Agent `clarksville-records research collector (+github url)` shows our repo name, not a government
   identity, in each body's server logs; confirm that is acceptable and whether CMCSS/RPC terms of service restrict the
   automated reads.
4. The map: district and ward lines come from county and RPC map files; confirm reuse and attribution terms.
5. Transcripts are machine-made from the city's own video; confirm terms for the video links and derived text.
6. The operator's tie to an elected office (docs/status.md: Brian's council seat, "he leaves it before anything goes live"):
   whether any disclosure is wise if the seat is still held at launch.
7. The repo `gn0sh/clarksville-records` is public and its name uses the city's name as a product-like title.
