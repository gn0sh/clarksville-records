# Visual refresh: design spec

Feature slug: `visual-refresh`. Owner: frontend-engineer (about 2 hours). Designer: ux-designer, 2026-11-07.
Trigger: CEO on the preview: "do something about the presentation. It's boring."

Scope: CSS, templates and a few new fields in `sitegen/views.py`. No JS libraries, no external requests. Spec
rules N1-N6, the neutrality rules in `docs/architecture/clarksville-records.md` ("Neutrality enforced by
construction") and the current tests stay in force (see sections 6 to 8).

Two inputs shape this spec:
- **Neutrality rules (architecture):** no percentages, no sorting by a count, no highlighting, and a template lint
  that bans `rank`, `score`, `grade`, `missed`, `percent`, `%`, `best`, `worst`. Counts are written as "attended 41
  of 44 meetings". A proportional bar is allowed only when its counts are also written out as text.
- **CEO decision (2026-11-07, `docs/status.md`):** roll calls that are not confirmed are **no longer held back**. They
  are shown with an asterisk, a "not confirmed" note and a link to the exact PDF page. Totals keep confirmed and
  not-confirmed counts separate. A name that is not matched to an official is never guessed. Section 2.6 covers how
  this looks; everywhere this spec used to say "under review / not shown" for roll calls now follows 2.6.

## 1. Identity: "the county record book"

The subject is public minutes. The look borrows from a bound minute book and a clerk's ledger: warm paper, dark
ink, a serif masthead, hairline and double rules, small-caps labels, and citations set like footnotes. Colour comes
from one non-partisan accent (deep teal-green ink) used only for chrome and links, never to encode a vote.

### Palette (CSS tokens)

Replace the `:root` block in `site/static/style.css`. Keep the existing token names that other rules use (`--bg`,
`--fg`, `--muted`, `--border`, `--surface`, `--link`, `--link-visited`, `--focus`, `--banner-*`), and add the new ones.

```css
:root {
  --bg: #fbf9f4;          /* paper */
  --surface: #f1ede3;     /* card */
  --surface-2: #e8e3d6;   /* table head, band cells */
  --fg: #1f1d1a;          /* ink */
  --muted: #5b564d;
  --border: #cdc5b4;      /* decorative rules only */
  --link: #1d5c54;        /* accent ink */
  --link-visited: #5c3f7a;
  --focus: #1d5c54;
  --band-bg: #1d3b38;     /* masthead and at-a-glance band */
  --band-fg: #f6f1e4;
  --band-muted: #c9d6cf;
  --seal: #8a6417;        /* initials ring, small ornaments; never text on --band-bg */
  --mark: #33414b;        /* the one data-mark colour: bars, chips, timeline nodes */
  --mark-soft: #8a8272;   /* "Other" and "No vote recorded" fills */
  --banner-bg: #fff1b8;
  --banner-fg: #4a3800;
  --font-head: "Source Serif 4", Charter, "Bitstream Charter", "Sitka Text", Cambria, Georgia, serif;
  --font-body: "Public Sans", system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --gutter: 16px;
  --measure: 64rem;
  --radius: 6px;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { /* dark block below */ }
}
:root[data-theme="dark"] { /* same dark block */ }
```

Dark block (write it once in each of the two places above):

```css
  --bg: #161513; --surface: #211f1c; --surface-2: #2a2824; --fg: #ece7dc; --muted: #b4ad9f;
  --border: #45403a; --link: #82c9bb; --link-visited: #c9b0ec; --focus: #82c9bb;
  --band-bg: #0f2725; --band-fg: #efe9dc; --band-muted: #a9c2ba; --seal: #d6ad5c;
  --mark: #d8d1c3; --mark-soft: #8b8475; --banner-bg: #3a3000; --banner-fg: #ffe58a;
```

Measured contrast (WCAG 2.x formula), light / dark:

| Pair | Light | Dark | Need |
|---|---|---|---|
| `--fg` on `--bg` | 15.98 | 14.80 | 4.5 |
| `--fg` on `--surface` | 14.38 | 13.33 | 4.5 |
| `--muted` on `--surface` | 6.23 | 7.37 | 4.5 |
| `--link` on `--surface` | 6.63 | 8.63 | 4.5 |
| `--link-visited` on `--surface` | 7.34 | 8.54 | 4.5 |
| `--band-fg` on `--band-bg` | 10.73 | 12.98 | 4.5 |
| `--band-muted` on `--band-bg` | 8.07 | 8.31 | 4.5 |
| `--mark` on `--bg` (graphic) | 9.99 | 12.02 | 3.0 |
| `--mark-soft` on `--surface` (graphic) | 3.26 | 4.43 | 3.0 |
| `--seal` on `--surface` | 4.59 | 7.82 | 3.0 (decorative) |

`--border` (1.6:1) is for decorative rules only. Anything a reader needs to see (chip outlines, bar edges, the
Absent hollow segment) uses `--mark`. Do not put `--seal` on `--band-bg` in light mode (2.26:1).

Why these hues: no red, no blue, no green-for-yes. Teal-green ink and ochre are chrome only. Every vote value is
drawn in the same `--mark` ink and told apart by **pattern and text**, so no value looks "good" or "bad" and the
page reads the same in greyscale.

### Typefaces

- Headings, site name, big numbers: `--font-head` (serif). Numbers use `font-variant-numeric: tabular-nums lining-nums`.
- Body, tables, chips: `--font-body`.
- Fact ids: `--font-mono` (as now).
- Labels above numbers ("Meetings", "Roll calls"): body font, `font-variant-caps: all-small-caps; letter-spacing: .04em`.

Fonts are **self-hosted or not used**. The test
`test_every_page_has_operator_footer_fixture_banner_and_no_external_resources` forbids external `<link>`s, and N6
limits visitor tracking, so no Google Fonts request. Optional, if time allows: add `site/static/fonts/` with the
OFL woff2 files for Source Serif 4 (600) and Public Sans (400, 600), latin subset, and `@font-face` rules with
`font-display: swap`. Without them the system fallbacks above give the same feel (Charter / Georgia + system UI).

### Type scale (1.25 ratio, 16px base)

| Token | Size | Use |
|---|---|---|
| `--t-xs` | 0.8rem | citations, fact ids, chip text |
| `--t-sm` | 0.9rem | labels, table text |
| `--t-md` | 1rem | body |
| `--t-lg` | 1.25rem | h3, card names |
| `--t-xl` | 1.56rem | h2 |
| `--t-2xl` | 1.95rem | h1 (clamp to 1.6rem under 480px) |
| `--t-num` | 1.75rem | stat numbers in the band and header cards |

Line height 1.5 body, 1.2 headings. h2 gets a hairline rule under it (`border-bottom: 1px solid var(--border)`).

### Chrome

- **Masthead** (`.site-header`): full-width `--band-bg` strip, `--band-fg` text. Site name in serif 1.35rem; under
  it a one-line kicker in `--band-muted`: "{{ coverage.body }} minutes, {{ from }} to {{ to }}" (needs `coverage` in
  `site_context`, new). Nav links `--band-fg`, underline on hover/focus, `aria-current="page"` gets a 2px bottom
  border. Below the strip, a 3px double rule (`border-bottom: 3px double var(--border)` on a thin spacer).
- **Theme toggle** (optional, last task, and only after the architect updates N6 in the architecture doc, which
  allows only `static/filter.js` today; without it, the `[data-theme]` rules simply stay unused): a `<button id="theme-toggle" hidden>` in the masthead, shown by
  `static/theme.js` (about 15 lines): cycles system / light / dark, sets `document.documentElement.dataset.theme`,
  stores the choice in `localStorage` inside try/catch. Without JS the button stays hidden and the system setting
  applies. Label text says the current state ("Theme: system").
- **Citation line** (`.meta`, the `source` + `fact_meta` macros): keep the text exactly; restyle as `--t-xs`,
  `--muted`, with a leading "Source:" small-caps label. Fact id stays mono.
- **Footer**: same text, top double rule, `--muted`.

## 2. Shared components

### 2.1 Stat (`.stat`)
```html
<div class="stat"><span class="stat-num">64</span><span class="stat-label">meetings in the record</span></div>
```
Number above, label below. The label always says what is counted. Numbers never stand alone.

### 2.2 Stacked bar (`.bar`), pure CSS
```html
<div class="bar" aria-hidden="true">
  <span class="seg seg-yes" style="--n: 412"></span>
  <span class="seg seg-no" style="--n: 38"></span>
  ...every segment of this bar type, always, in fixed order...
</div>
<ul class="legend"> <li><span class="key seg-yes"></span> Yes: 412</li> ... </ul>
```
```css
.bar { display: flex; height: 18px; border: 1px solid var(--mark); border-radius: 3px; overflow: hidden; background: var(--bg); }
.seg { flex: var(--n) 0 0; min-width: 0; }
.seg + .seg { box-shadow: inset 1px 0 0 var(--bg); } /* 1px paper gap between segments */
.seg-yes, .seg-present { background: var(--mark); }
.seg-no { background: repeating-linear-gradient(45deg, var(--mark) 0 3px, transparent 3px 6px); }
.seg-abstain { background: radial-gradient(var(--mark) 1.2px, transparent 1.6px) 0 0 / 5px 5px; }
.seg-other, .seg-novote { background: var(--mark-soft); }
.seg-absent { background: transparent; } /* hollow: the bar's own border shows the space */
.key { display: inline-block; width: 14px; height: 14px; border: 1px solid var(--mark); vertical-align: -2px; }
```
Rules:
- Render **every** segment of the bar type every time, in the fixed order below, with `--n: 0` when empty
  (`flex-grow: 0` collapses it). Classes never depend on the data. This keeps the N1 skeleton identical.
- The bar is `aria-hidden`; the **legend is the data**: each legend item is "Label: count". The legend lists every
  value, including zeros, in the same order for everyone.
- The bar's denominator is stated in text right above it (see each use). Segments must add up to that number; add a
  test (section 6).
- Fixed orders: vote bars `Yes, No, Abstain, Other, Absent, No vote recorded`; attendance bars `Present, Absent`.
- Inline `style="--n: …"` is the only inline style allowed. It carries a number, never a colour.

### 2.3 Chip (`.chip`)
Small inline label, `--t-xs`, 600 weight, 2px 8px padding, `border-radius: 999px`, always with its text.
- Vote chips use the same patterns as the bar as a 12px square swatch before the word (`.chip .key`), text in `--fg`,
  border 1px `--mark`, background `--surface`. Same visual weight for Yes and No.
- Outcome chips (`Passed`, `Failed`, `Other`): `Passed` and `Failed` both `--surface` with 1px `--mark` border; the
  word carries the meaning. No tick or cross icons.
- Attendance chips: `Present` (solid swatch), `Absent` (hollow swatch).

### 2.4 Initials badge (`.badge`)
40px circle (56px on the official header), `--surface-2` fill, 2px `--seal` ring, serif initials in `--fg`,
`aria-hidden="true"` (the name is right next to it). **Identical colour for every official**: no per-person hues,
no photos.

### 2.5 Timeline (`.timeline`)
`<ol>` with `padding-left: 28px; position: relative`, a 2px `--border` rail at `left: 9px` (`::before` on the ol),
and each `li` with a 12px node (`::before`, `--mark`) on the rail. Node shape by type, always paired with the
visible type label:
- meeting: filled circle; roll call: filled circle; motion: filled diamond (rotated square); listed: hollow circle;
  other: small square; held-back event: dashed hollow circle and `--muted` text.

### 2.6 Confirmed and not-confirmed roll calls

"Confirmed" means the roll call passed the automatic checks (P2, `is_verified`). Both kinds are shown. Confirmed is
the plain default. Not confirmed is marked in **three ways at once**: an asterisk, the words "not confirmed", and
a dashed outline. It never depends on colour, and the two kinds use the same `--mark` ink.

| Place | Confirmed | Not confirmed |
|---|---|---|
| Roll-call block (meeting and item pages) | solid 4px left border; no extra label | dashed 4px left border; a status chip `* Not confirmed` after the h3 text; a note line under the tally (below) |
| Vote chip in that block | `■ Yes` | `■ Yes*`: the asterisk follows the word, the chip border is dashed |
| Vote bar on a roll-call block | solid 1px border | dashed 1px border; same patterns |
| History row (official page) | Record `Yes` | Record `Yes*`, with a second line `Not confirmed: check p. 12` (link to the PDF page) |
| Outcome chip | `Passed` | `Passed*` (the minutes' outcome, not confirmed by the checks) |

The note line on a not-confirmed block (fixed wording, the same for every roll call):

> \* Not confirmed: this roll call did not pass the automatic checks against the minutes. Check it on
> [p. 12 of the minutes](…#page=12).

Markup for the asterisk, so screen readers say the words rather than "star":
```html
<span class="nc-mark" aria-hidden="true">*</span><span class="sr-only"> (not confirmed)</span>
```
CSS: `.nc .bar, .nc .chip { border-style: dashed; }`, `.block.nc { border-left-style: dashed; }`,
`.nc-mark { font-weight: 700; margin-left: 1px; }`. The class `nc` is set from the `confirmed` field. On the official
page these marks appear only inside the history `tbody` and the vote-breakdown text, which the skeleton test does
not compare by content, so N1 holds; outside `tbody`, keep the same elements for both kinds (the note `<p>` is
present in confirmed blocks too, empty and `hidden`).

**Unmatched names.** A vote whose name did not resolve to an official (`person()` returns `href: None`) shows the
fixed text "Name not matched*" (manager amendment: raw OCR names never reach public pages, per the leak tests), no
link, no badge, plus the not-confirmed note with the PDF page link. It is counted in no official's totals. The meeting header
counts these: "N names not matched to an official" (always present, 0 included). Never offer a "did you mean".

Counting rule for every total in this spec: confirmed and not-confirmed are **always two separate numbers**, side
by side, never added into one figure. Wording: "{{ c }} confirmed and {{ u }} not confirmed* roll calls".

## 3. Home page (`index.html.j2`, `officials_index()`)

Order: band, officials, meetings.

### 3.1 At-a-glance band
Under the h1 "Officials", a `--surface` card with a 4-cell grid (`repeat(auto-fit, minmax(8.5rem, 1fr))`; 2x2 at
400px). Each cell is a `.stat`:

| Cell | Number | Label (exact) |
|---|---|---|
| Meetings | `glance.meetings` | "meetings in the record" |
| Confirmed | `glance.rc_confirmed` | "roll calls confirmed" |
| Not confirmed | `glance.rc_unconfirmed` | "roll calls shown but not confirmed*" |
| Period | `glance.from` to `glance.to` | "dates covered" (set the dates at `--t-lg`, not `--t-num`) |

Under the grid, one `--t-sm` `--muted` line, always present (same template text whatever the numbers):
"{{ rc_confirmed }} of {{ rc_total }} roll calls are confirmed; the other {{ rc_unconfirmed }} are shown with an
asterisk and a link to the page of the minutes. {{ motions_held }} motion attributions are under review.
{{ att_not_shown }} meetings have no attendance shown." (Motion attribution hold-back is unchanged by the CEO
decision, which covers roll calls; if the architect extends it to motions, use the same 2.6 pattern.) Link "data
rules" to `about.html`. The period cell keeps its place as the fourth cell. No percentage sign anywhere.

### 3.2 Officials as cards
Keep the h1, lede and the `aria-label="Officials, alphabetical by surname"` list, but the `<ul class="cards">` is a
grid (`repeat(auto-fill, minmax(15rem, 1fr))`, 1 column at 400px). Each `li` is a card (whole card clickable via the
name link's `::after` overlay, `position: relative` on the card):

```
[AH]  Arnold Hodges                 <- badge, name link (serif --t-lg)
      County Commissioner           <- --muted
      ---------------------------------------
      Present at 58 of 61 meetings with attendance shown
      Recorded vote on 290 confirmed and 3 not confirmed* roll calls
```
- District: **not in the data** (officials have `id, name, given, surname, title, aliases` only). Leave it out; do
  not add a placeholder. If a later task adds `district` to the facts, it goes after the title on every card.
- Both lines appear on every card, in this order and wording, with zero shown as "0". No bars on the home
  page (see Risks). No bold, colour or icon on any number.
- Order stays `name_key` (alphabetical by surname), computed in views.py as now.

### 3.3 Meetings as a timeline
h2 "Meetings", line "Newest first." then year jump links (`<nav aria-label="Meeting years">`, one link per year to
`#y2026` ...). Then per year: `<h3 id="y{{ year }}">{{ year }}</h3>` and an `<ol class="timeline">`. Each entry:

```
● 2026-05-11  Formal meeting                    <- date link (serif), kind label
  9 roll calls · 14 motions · 21 of 22 members present
```
The second line is `--t-sm` `--muted`. When attendance is not shown it says "attendance not shown" instead of the
count. Roll calls are written as "9 roll calls (1 not confirmed*)". The bracket is always shown, "(0 not
confirmed)" included, so the line has the same shape for every meeting. Grouping is done in views.py (templates
must not `groupby` or `sort`).

## 4. Official page (`official.html.j2`, `official()`)

### 4.1 Header card
`--surface` card: 56px badge, h1 name, title line, coverage sentence (existing `coverage_sentence`) in `--muted`.
Then a stat row (`auto-fit, minmax(7.5rem,1fr)`), six cells, same for everyone:

| Number | Label |
|---|---|
| `stats.meetings_listed` | "meetings with attendance shown" |
| `stats.present` | "recorded present" |
| `stats.rc_voted` | "confirmed roll calls with a recorded vote" |
| `stats.rc_voted_nc` | "not confirmed* roll calls with a recorded vote" |
| `stats.moved` | "motions moved" |
| `stats.seconded` | "motions seconded" |

### 4.2 Attendance bar
h2 "Attendance". Text: "Recorded present at {{present}} and absent at {{absent}} of {{meetings_listed}} meetings
with attendance shown, {{from}} to {{to}}." Then the attendance `.bar` (Present solid, Absent hollow) and legend.

### 4.3 Vote breakdown
h2 "Roll-call votes". Two rows, always both, in this order:
1. h3 "Confirmed roll calls". Text: "{{ rc_total }} confirmed roll calls at meetings where this person is listed in
   the attendance, or where a vote is recorded for them." Vote `.bar` (solid border), all six segments, legend
   "Yes: n · No: n · Abstain: n · Other: n · Absent: n · No vote recorded: n".
2. h3 "Not confirmed roll calls*". The same sentence with "not confirmed" and `rc_total_nc`, then the same legend
   from the `_nc` counts as **text only, no bar** (the bar is confirmed only, per section 10), then the 2.6
   explanation in one line: "* Shown as printed in the minutes; they did not pass the automatic checks. Each row in
   the history links to its page."
"Absent" means listed absent at that meeting and no vote recorded; "No vote recorded" means listed present and no
vote recorded. The two bars are never merged into one total.

### 4.4 Totals (unchanged words)
Keep the h2 "Totals" and the four `totals` sentences verbatim (they are pinned by `test_totals_wording_is_fixed`
and `test_attendance_totals_match_meeting_pages`). Restyle the list as a ruled ledger: no bullets, each sentence on
its own line with a top hairline, `--t-sm`. The second sentence (held-back roll calls) no longer
matches the CEO decision. Its new fixed wording is the architect's and backend's call (it is pinned by tests);
the design proposes: "{{ u }} roll calls in this period are shown but not confirmed, and are counted separately
above." Keep it a fixed sentence identical for everyone except the numbers.

### 4.5 History table, restyled
Same markup, roles and filter JS. Changes:
- `thead th`: `--surface-2`, small caps, `--t-xs`.
- Zebra: `tbody tr:nth-child(even) { background: var(--surface) }` (wide screens only).
- Type column: the type as a chip (`.chip`, text "Vote"/"Attendance"/"Moved"/"Seconded"); no colour per type.
- Record column: votes and attendance as vote/attendance chips (2.3); moved/seconded keep the motion type text.
  Not-confirmed votes follow 2.6 (`Yes*`, dashed chip, "Not confirmed: check p. n" link). The filters stay as
  they are (Type, Year); no "not confirmed" filter.
- Outcome column: outcome chip, tally under it as now.
- Source column: citation styling (`--t-xs`).
- The filter form sits in a `--surface` toolbar above the table.
- The phone stacked layout stays; each stacked row becomes a small card (`--surface`, radius, 10px padding, 8px gap).

## 5. Meeting page and item pages

### 5.1 Meeting header (`meeting.html.j2`)
Header card: h1 as now; kind chip; source line as now; stat row:
"{{ present }} of {{ listed }} members present" (or "attendance not shown" / "attendance under review", same
wording as today's states), "{{ motions }} motions", "{{ rc_confirmed }} confirmed and {{ rc_unconfirmed }} not
confirmed* roll calls", "{{ unmatched }} names not matched to an official". `held_roll_calls_text` goes away with
the hold-back.

### 5.2 Attendance
Keep the table (it carries a source per row and is pinned by tests). Restyle: Recorded column shows an attendance
chip with the word. Rows stay alphabetical. No separate "absent" list or grouping by status.

### 5.3 Roll-call blocks (macro `roll_call_block`, also used on item pages)
The `.block` card gets a left 4px `--mark` border for roll calls and a dashed one for motions, so the two kinds
read apart in greyscale.
```
Roll call: 24-1-3 Budget amendment for ...            <- h3 (unchanged text)
[Passed]  21 yes · 2 no · 1 absent                     <- outcome chip + existing tally string
[==========solid=========|//no//| ]                    <- vote .bar (aria-hidden), same six segments
Resolution. Moved by A, seconded by B.                  <- unchanged
Votes, alphabetical
  [Ann Allen  ■ Yes] [Bo Baker  ▨ No] [Cy Cole ■ Yes] ...   <- vote grid
Source: p. 12, fetched ... · Fact id ... · Report an error
```
- Vote grid: replace the two-column `vote_table` with `<ul class="vote-grid" aria-label="Votes by member">`,
  `grid-template-columns: repeat(auto-fill, minmax(10.5rem, 1fr))` (2 columns at 400px). Each `li`: name link, then a
  vote chip. Order stays as `_vote_rows` gives it (alphabetical). Long names wrap; nothing truncates.
- Not-confirmed blocks follow 2.6: dashed border, `* Not confirmed` chip, asterisks on each vote chip and on the
  outcome chip, and the note line with the PDF page link. Unmatched names follow 2.6.
- Bar segments come from the new `outcome.counts`. On a roll call "No vote recorded" is always 0 and "Absent" is 0
  when the meeting's attendance is not shown; render them anyway (fixed structure).
- Check `test_vote_rows_link_item_and_meeting` and `test_every_fact_row_links_to_its_pdf_page` still find what they
  look for; if they select `table.votes`, update the selector, not the rule.

### 5.4 Item history as a vertical timeline (`items_year.html.j2`)
`ol.events` becomes `ol.events.timeline`. Each event `li` sits on the rail with the node shape for its `e.type`
(class `ev-{{ e.type }}` from the fixed type list: roll_call, motion, listed, other). Event head: date (serif link),
type label as a chip. Roll calls inside use the block from 5.3 without the outer border. A not-confirmed roll call is no longer
a held-back event: it gets a dashed hollow node, the `* Not confirmed` chip, and the full block per 2.6. The item's number is set in mono small caps above its title; "Linked by number /
title" becomes a chip. The year table of contents stays (2 columns).

## 6. Data each element needs

| Element | Source today | New to compute (views.py) |
|---|---|---|
| Masthead kicker | `coverage` (in page contexts) | add `coverage` to `site_context()` |
| Band: meetings | `len(facts["meetings"])` | `glance` dict in `officials_index()` |
| Band: roll calls confirmed / not confirmed / total | `is_verified` over `roll_calls` | `glance.rc_confirmed`, `rc_unconfirmed`, `rc_total` |
| Band: motions held | `is_verified` over `motions` | `glance.motions_held` |
| Band: attendance not shown | `attendance_state()` | `glance.att_not_shown` (not_extracted + under_review) |
| Band: period | `coverage.from/to` | none |
| Card: initials | `given`, `surname` | `initials = given[:1] + surname[:1]` |
| Card / header: listed, present, absent | logic inside `totals_sentences()` | **extract** `official_counts(ix, oid)` returning `meetings_listed, present, absent, moved, seconded`, and the vote counts twice, once over confirmed and once over not-confirmed roll calls (`rc_voted, yes, no, abstain, other, rc_absent, rc_novote, rc_total` and the same names with `_nc`); use it in `totals_sentences()`, `official()` and `officials_index()` so the numbers cannot drift |
| Card: not-confirmed roll calls | was `held_counts()` | `rc_voted_nc` from `official_counts`; only votes whose `official_id` resolved count, never a name match |
| Official vote bar | votes in `official()` loop | `rc_absent`: verified roll calls at meetings whose shown attendance lists the person absent and with no vote for them; `rc_novote`: same but listed present; `rc_total = rc_voted + rc_absent + rc_novote` |
| Moved / seconded counts | rows in `official()` | from `official_counts` |
| Meeting timeline line | per-meeting facts | `meetings_by_year`: list of `{year, meetings: [{label, date, kind_label, href, rc_confirmed, rc_unconfirmed, motions, att_state, present, listed}]}`, newest first by date |
| Meeting header stats | `meeting()` | `present`, `listed`, `motions` (len of motions), `rc_confirmed`, `rc_unconfirmed`, `unmatched` (votes in this meeting's roll calls with no resolved `official_id`) |
| Not-confirmed blocks | `meeting()` and `_event()` drop unverified roll calls today | build `_roll_call_block` for every roll call and add `confirmed: is_verified(rc)`; `_event()` stops setting `held_back` for roll calls |
| History rows | `official()` skips unverified roll calls | include them, with `confirmed` on the row |
| Roll-call bar | `Index.outcome()` builds the tally string | add `counts: {yes, no, abstain, other, absent}` to its return (absent as today: listed absent, no vote, attendance shown; else 0) |
| Item timeline | `_event()` already has `type` | none |

Sorting: every new list is ordered by name or date only (`test_views_sort_keys_are_not_counts`).

New tests (frontend-engineer adds):
1. For every official, for confirmed and for `_nc` separately: `yes+no+abstain+other+rc_absent+rc_novote == rc_total`, and `present+absent == meetings_listed`,
   and `official_counts` agrees with the numbers in `totals_sentences`.
2. For every roll call: the bar's segment `--n` values equal `outcome.counts` and match the tally string.
3. Officials index cards appear in `name_key` order and every card has the same skeleton.
4. Every not-confirmed roll call on a public page has the asterisk, the words "not confirmed" and a link ending
   `#page=<its page>`; every unmatched name renders without a link and with the fixed note.
5. Existing tests pass, except those that pin the hold-back (`test_unverified_facts_only_on_review_page`, the
   held-back totals sentence): the architect rewrites those to the new rule; designers and engineers don't relax
   them ad hoc.
6. The rest (skeleton, banned words, no external resources, totals wording).

## 7. Layout and accessibility checks (QA)

- 400px wide: no horizontal page scroll on index, an official, a meeting, an items year (tables keep their own
  scroll box or stacked layout; vote grid 2 columns; band 2x2; cards 1 column).
- Greyscale screenshot of an official page and a meeting page: every vote value is still told apart (pattern +
  word).
- Text contrast per the table in section 1; focus ring visible on the band (use `--band-fg` outline inside the
  masthead).
- Bars are `aria-hidden`; screen readers get the caption sentence and the legend text.
- `prefers-color-scheme: dark` and `[data-theme]` both switch every token; `prefers-reduced-motion`: no animations
  are added at all.
- Template text contains no `%`, "percent", "rank", "score", "best", "worst", "missed".

## 8. Decisions and deviations from the brief

| Brief asked | This spec | Why |
|---|---|---|
| Attendance % on official cards | "Present at X of Y meetings with attendance shown" | N3 wants plain totals with denominators; a percentage per person reads as a score, and templates ban `%` |
| "Verified share" in the band | two cells: confirmed and not-confirmed counts, plus "c of t are confirmed" | no `%`; and the CEO decision keeps the two counts separate |
| Held-back records counted as now | not-confirmed roll calls shown with asterisk, note and page link (2.6) | CEO decision 2026-11-07 supersedes the hold-back display |
| District on cards | omitted | not in the facts data; never invent a field |
| Google Fonts pair | self-hosted OFL fonts (optional) or system fallbacks | external links break a test and N6 |
| Attendance bar on cards | none on the home page; bars only on a person's own page and per roll call | see Risk 1 |

## 9. Risks (most serious first)

1. **The card grid becomes an implicit leaderboard.** 33 identical cards side by side, each with an attendance
   number, invite scanning for the odd one out; with bars it would be a visual ranking of absences, which N3 and the
   non-goals forbid even if the list is alphabetical. Mitigation in this spec: no bars or meters on the home page,
   counts as plain sentences in muted body text, the same two lines on every card, alphabetical order, nothing
   highlighted. Residual risk remains (numbers are still side by side); if the reviewer or a panel judges it too
   comparative, drop the attendance line from the cards and keep only "Recorded vote on N roll calls". Confidence
   in the mitigation: medium (judgment call).
2. **Bars that don't add up.** A stacked bar implies a whole. If `rc_total` is defined loosely, a reader may take
   the hollow "Absent" part as missed votes in general, or not see that not-confirmed roll calls sit outside the
   bar. Mitigation: one `official_counts` function, a caption with the denominator that says "confirmed", the
   not-confirmed counts written right under it, and the sum test in section 6.
3. **Pattern-only distinctions at small size.** The hatch and dot fills can blur on low-DPI screens at 18px. The
   legend text carries the meaning, so this costs ease, not accuracy.
4. **The asterisk reads as an accusation or gets ignored.** A not-confirmed vote is a parsing doubt, not doubt about
   the person. The note says what failed (the automatic check against the minutes) and links the page, and the
   asterisk sits on the record, never on the person's name or card. If an official has many not-confirmed votes
   because of how their name is printed, the asterisks cluster on one page: the G4 skew check still runs and is
   the guard. Confidence: medium.
5. **Template churn breaking pinned tests** (skeleton, totals wording, link tests). Mitigation: keep fixed segment
   structure and the existing sentences; run the full suite before review.

## 10. Manager amendments (2026-11-07)
- CEO decision after this draft: unconfirmed roll calls are shown, not held back (see docs/status.md, Decisions). Wherever this spec says "under review and not shown", read "shown with an asterisk and 'Not confirmed'". Unconfirmed votes appear in the vote grid and history with an asterisk after the chip word and a link to the PDF page; they are NOT in the official's vote bar (bar = confirmed only, caption says so) and the band says "N of M roll calls confirmed; the rest are shown with an asterisk".
- Folded in by ux-designer: the CEO decision above is now designed in sections 2.6, 3.1-3.3, 4.3-4.5, 5.1, 5.3,
  5.4 and 6; the not-confirmed counts on the official page are text only, outside the bar.
- Risk 1 decision: keep the attendance line on cards. Participation is the CEO's stated goal, the line is a plain count with its denominator, the order is alphabetical and nothing is highlighted. code-reviewer checks it.

## UX pass: dropdowns and collapsed groups (2026-11-07)

CEO: "we've got some work to do as far as UX", "consider using dropdowns to keep menus clean". Native `<details>`/`<summary>` and CSS only; N6 still allows one script (`filter.js`).
- **Masthead:** Officials, an "Items" dropdown (years newest first) and a "More" dropdown (About, Changes, Review when internal). At 640px and narrower the wide nav is hidden and a single "Menu" dropdown shows instead (two `<nav>`s, CSS picks one, so assistive tech reads only the visible one). The two wide dropdowns share `name="main-nav"` so opening one closes the other where supported.
- **Home:** the year buttons became a "Jump to year" dropdown; meetings sit in one `<details>` per year, newest open. The jump link's id is on the list inside the group so the browser opens the group on navigation.
- **Items year pages:** the table of contents is grouped by month of the item's first appearance (my call: months give about 5 to 20 links per group, meetings would give many tiny groups), all collapsed. Grouping lives in `views._toc_groups`.
- **Official history:** one table per year inside a `<details>` (newest open); `views.official` returns `row_groups`. `filter.js` filters rows across all tables, hides groups with no match and opens the chosen year. The year label is a `<span>`, not a heading, so the page skeleton stays identical for every official (N1 test).
