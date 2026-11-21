# Focus Group: Daylight national concept, 2026-11-19

Simulated personas, not real users. Results are hypotheses to check with real people. Five personas, sonnet/medium,
independent, neutral stimulus (concept text only). Rick was the assigned skeptic.

## Scorecard
| Persona | Would use |
|---|---|
| Maya, 34, big-city renter (Legistar city) | Probably, if covered |
| Gene, 71, small-town retiree, scanned PDFs, large text | Probably not |
| Denise, 42, unincorporated county parent | Probably |
| Rick, 55, PA township, skeptic | Probably not / No |
| Priya, 29, reporter, pays for AI transcripts | Probably not |

## Top themes (ranked by how many raised them)
1. **Show coverage before asking for anything (5/5).** "Tell me honestly on the first screen whether my town is in."
2. **"Not covered yet" with no date is a dead end (5/5).** "Is it a real roadmap or a black hole?"
3. **Verbatim agenda text is dense; want a plain hook and topic tags, not AI (3/5).**
4. **Weekly is too slow; want an alert when an item appears (3/5).**
5. **Who runs it and who pays, in plain words, up front (3/5).** Longevity worries for a free tool.
6. **The Census privacy wording confuses rather than reassures (3/5).** "Just tell me you won't sell my address."
7. **The letter feels like homework or trouble (3/5).** "The clerk is my neighbor."
8. Wants minutes and outcomes, not just agendas (3/5); neighborhood/district or keyword filters (2/5); large text,
   real text with headings for screen readers (2/5).

## Surprises and disagreements
- Gene: "it does the least for the people who need it most" (small towns lost their paper and post scanned PDFs).
- Rick would browse a plain list of covered governments but would not type an address or email at all.
- Priya's edge for Daylight: "the one-address, all-governments view plus honesty about what's covered."

## Raw answers (condensed)

Maya (big-city renter, Legistar city): Probably, if covered. Name covered cities up front / let me check before address. Verbatim = legalese; wants agenda title + topic tag (not AI). Weekly can miss a Tuesday hearing: wants alerts when an item appears. Citywide zoning feed is noise: district/neighborhood filter. Wants outcomes/votes. Who runs it, longevity. Spammy email = stop. Wants to verify address claim. Compares to city alerts, subreddit, Legistar, Councilmatic. Change: do a few cities well with topic+district filters before showing long uncovered lists.

Gene (small-town retiree, scanned PDFs, large text): Probably not. "Does the least for the people who need it most": small towns with scanned PDFs land in Can't cover. Jargon ("own words", "records system"). No timeline for Request it. Won't send form letter to clerk (his neighbor). Census wording worrying. Wants a person/phone, large-print robustness. Empty weekly emails, accounts, topic boxes = quit. Watching for bias. Change: do something for Can't-cover towns (show the scanned agenda link at least); say on first screen if the town is in.

Denise (unincorporated county parent): Probably. Coverage is the killer: "Not covered yet" with no date = gone. Unincorporated: make blank city clear. Wants plain hook ("rezoning 200 homes on Smith Rd"), street/subdivision/school keyword alerts. What happens after Request it? Weekly may miss agenda timing. Letter feels like homework. Census wording too technical; just "we won't sell your address". No minutes/votes/video. Stops if emails long/dull, looks 2005, needs account. Uses Facebook group + Nextdoor (wrong half the time but tells why to care). Doubts longevity of free tool. Change: show covered list up front; take email and notify the moment it opens.

Rick (skeptic, PA township): Probably not / No. Trust: who runs it and who pays, in plain words at the top, before asking anything. Can't verify "we never see your address". Fears list sold / political use; any lean = gone. Township posts agendas on a bulletin board. Won't send a letter with his name to the township. Change: browse coverage from a plain list without address or email; ownership/funding up front.

Priya (reporter/power user, pays for AI transcripts, screen reader): Probably not. Weekly too slow; wants same-day keyword alerts (street, developer), search across meetings, minutes and votes, revision/supplement tracking. Name the platform and list covered places before address. Request it needs roadmap/count. Explain how ticking works without address. Topic tagging quality worries. Accessibility: real text with headings, not PDF links. Edge: one-address, all-governments view + honesty about coverage. Change: same-day alerts + minutes/votes (or "coming next" label); covered list up front.

## Recommended changes
- A plain "What we cover" list, browsable without an address or email (PM, ux-designer).
- Who runs Daylight and who pays, in plain words, above the address box (PM, technical-writer).
- Plain-words privacy line first ("We never get your address and never sell anything"), the Census detail second (ux).
- "Request it" says what happens next honestly (PM).
- Agenda item title plus fixed topic tag, verbatim text below (ux; no AI).
- For "Can't cover", always link the official agenda page so the person still gets the document (PM).
- Large text and screen-reader checks in QA for every page (qa-engineer).

## Decisions this changed
| Finding | Decision changed | Scope | Owner |
|---|---|---|---|
| Show coverage before address | Yes: "What we cover" list page | adds (small) | product-manager |
| Who runs it, who pays | Yes: plain line above address box | adds (small) | technical-writer |
| Privacy wording confusing | Yes: plain sentence first | none | ux-designer |
| Can't-cover towns get nothing | Yes: always link the official agenda page | adds (small) | product-manager |
| Weekly too slow | Open, tied to email decision | | product-manager |
| Letter feels like homework | No: stays optional, M3 | | product-manager |

## Hypotheses to validate with real people
Coverage-first page lowers bounce; plain privacy line beats the technical one; people prefer an alert when an agenda
posts over a weekly note. Check after the January launch with GoatCounter page counts and request counts.
