# Spec: finance-contracts (milestones M2 county budgets, M3 county contracts, capital projects)

Status: draft v1, 2026-11-08. Owner: product-manager. Parent spec: `docs/specs/clarksville-records.md` (goal, N1-N6,
G1-G7, P1-P4 apply unchanged). Source facts: `docs/platform-facts.md`, section "Finance and contracts sources".
Primary user: residents (confirmed by CEO, 2026-11-07). Only Brian sees the private preview.

## Problem
Residents who want to know where county money comes from, where it goes, and who is paid to supply it must dig through
a 119-page budget book and a purchasing page of ~91 solicitations, each with up to six separate PDFs. Nothing joins a
solicitation to its bidders, totals and awardee. Brian's goal (2026-11-07): "give people every opportunity" to look
into this themselves, with the site showing data and sources only. It never accuses, scores, ranks or comments.

## Scope in Brian's words
Finance = revenue and expenditures, contract awardees and amounts, capital projects, and links to every related
document. Nav already reserves Finance and Capital projects slots.

## User stories
- US-F1. As a resident, I want budget by fund, revenue by source and spending by department for three fiscal years, so I can see where money comes from and goes.
- US-F2. As a resident, I want every budget number to open the exact PDF page it came from, so I can check it myself.
- US-F3. As a resident, I want a contracts page listing each solicitation with all its documents, every bidder with its total, and the awardee, so I can see who bid and who won without opening six PDFs.
- US-F4. As a resident, I want to search and filter contracts by vendor name, title and date, so I can find one company or purchase.
- US-F5. As a resident, I want to see capital projects with the amounts the budget book lists for them, linked to their pages.
- US-F6. As a resident, I want to download the same data as CSV/JSON with sources (G5), so I can analyse it myself.
- US-F7. As a resident, when the site cannot read a number reliably, I want it to say so and link the page, so I never see a guessed amount.

## Slice 1 (thin, real data, private preview), split by Brain Trust 2026-11-08
**1a "Bids and awards"** (done-test: Brian opens a solicitation and sees every document and the bid-tab figures with sources).
- The purchasing archive index: all ~91 solicitations (2025-2026), each with every linked document (bid, RFP, bid tab, award letter, notice of intent, Q&A), a stage label and date per document, and fetch date.
- Bidders, "Bid total as printed" and the awardee come only from the text bid tabs (live count), with the awardee's source named. Solicitations without a bid tab are listed with documents only.
- Scanned award letters and notices are linked, with no value read from them. OCR is a later spike, not slice 1.
- No sums across solicitations, no per-vendor totals, no county-wide totals. Bonfire is link-only.

**1b Budget books** (own done-test: Brian opens a fund and a department and sees every number with its PDF page).
- FY2027 and FY2024-25 books to budget by fund, revenue by source and spending by department, plus the Capital Projects fund (171, FY2027 book pp. 102-114) on its own nav slot.
- Columns carry the book's own header plus its kind (actual / amended / budget); no trend lines, no "the years the books print" framing.
- Lines are detail rows; each printed subtotal is checked against its rows; transfers and available-funds rows are tagged by section.
- Totals are checked "to the printed dollar". A total that does not add up is shown "as printed, does not add up" with its lines, flagged, not hidden.
- Book edition stored per line; differing figures across books are shown both, never overwritten.
- No county-wide revenue or spending total is computed.

## Acceptance criteria
- AC-F1 **Amounts match source.** Spot check of 30 random shown dollar amounts (at least 10 budget, 10 bid-tab, 5 across both books, 5 awardee names from bid tabs) against the PDF: all 30 match exactly (digits, sign, parentheses to negative). Any mismatch blocks release; the failing pattern gets a regression test, then a fresh 30.
- AC-F2 **Budget checks (1b).** For every fund and year, each printed subtotal equals the sum of its detail rows to the printed dollar, with three outcomes (manager decision 2026-11-08, ADR 0002 point 4): "adds up", "adds up within rounding" (gap no more than about half a dollar per line; the FY2027 book's whole-dollar rounding gives 99 of 515 such totals) and "does not add up". A non-reconciling total is shown as printed, flagged "does not add up", with its lines; never hidden, never silently corrected. The run reports reconciled and flagged counts.
- AC-F3 **Every number is linked.** 100% of shown amounts, names and dates carry a source link to the document and page (N4) and a fetch date. A test fails the build on any shown amount without a link.
- AC-F4 **Bid tab arithmetic.** Each bid-tab total shown is read from the tab's printed total. Bidder count and the awardee listed in the tab agree with the award letter where one is readable. Disagreement: show the bid tab as printed and flag "Documents differ, read both" with both links, with no explanation.
- AC-F5 **No OCR values (1a).** No amount, awardee or date is read from a scanned award letter or notice; each is linked as "Scanned, read it yourself". A later OCR spike must meet P1-P4 (independent exact check, else Not confirmed*, link only) before any such value appears.
- AC-F6 **Hand-labelled set.** At least 10 solicitations (mixed: with and without bid tab, scanned award letter, multi-bidder, single bidder, lump-sum vs unit-price tab) hand-labelled by QA; zero wrong values; anything unreadable lands in Not confirmed*.
- AC-F7 **Document completeness.** For every purchasing archive row, 100% of its linked documents appear on its contracts entry (count of links in archive equals count shown); the run reports totals (the live counts; the architect counted 90 rows, 56 with a bid-tab link (2 .docx) and 71 with an award-type document on 2026-11-08).
- AC-F8 **Neutrality.** Vendors and departments use one layout and one ordering rule (alphabetical, or by date); no sorting or highlighting by amount-won counts, win rates, share of spend, year-over-year change arrows, or any computed judgment. Totals appear only as plain sums with scope and date range stated (N1-N3). A lint test fails the build on words from a banned list in templates (for example "overpaid", "suspicious", "top", "worst").
- AC-F9 **Names link to votes.** Every elected official's name anywhere in these pages (for example the budget committee roster) links to their vote-history page. A test finds zero unlinked names matching the official roster.
- AC-F10 **Compact tables.** Long text (titles, notes, line descriptions) is clipped with Show more; tested with no horizontal page scroll at 360 px and at narrow side-panel width.
- AC-F11 **Fetch hygiene.** The collector never requests a robots-disallowed path (test-enforced; Bonfire is never fetched); honors crawl delay; fails loudly on a changed page structure, on a proxy CONNECT refusal versus a server 403 (distinguished), and on a missing document.
- AC-F12 **No hard-coded locality.** County name, budget-book URLs, fund names, archive URL, fiscal-year labels and body names live in config or per-source adapters; a review check flags new "Montgomery" or "Clarksville" literals in code (not data or config).
- AC-F13 **Export.** CSV/JSON of budget lines, solicitations, bidders and documents, each row with source URL, page and fetch date (G5).
- AC-F14 **Corrections.** Every finance and contract page has the correction-report path (N5).
- AC-F15 **Coverage sentence.** Every contracts and budget page shows one fixed coverage sentence, tested by exact string (for example "32 of 91 solicitations have a bid tab; award letters are scans and are linked, not read"), with live counts and identical wording everywhere.
- AC-F16 **Coverage parity.** Each run reports bid-tab and document coverage by department and year (mirrors G4); a release is blocked or the skew explained in writing if one department's coverage differs sharply from the rest, so gaps cannot read as a pattern. Owners: product-manager, qa-engineer.
- AC-F17 **Usefulness test.** Brian finds three named contracts by vendor name, unaided; batched with his next device check.

## Requirements on design and architecture (Brain Trust)
- ux-designer: page named "Bids and awards"; column "Bid total as printed", never "contract amount"; stage label and date per document; awardee only with its source named.
- ux-designer: budget columns use the book's header plus its kind; no trend lines or arrows.
- ux-designer: a fixed neutral glossary for jargon, exempt from the banned-words lint.
- ux-designer: a fixed note on the capital page: fund lines are not project cost.
- software-architect: lines are detail rows; each printed subtotal checked against its rows; transfers and available-funds rows tagged by section.
- software-architect: "to the printed dollar" reconciliation; a non-reconciling total shown as printed, flagged, with its lines.
- software-architect: book edition stored per line; differing figures shown both, never overwritten.

## Public-launch gates (preview unchanged)
A vendor-correction path (a named company can report an error) and the G1 operator disclosure on every finance and contract page, both before any public URL (G6).

## Out of scope for now
Per-vendor or county-wide sums; OCR of award letters (later spike); chart explorer comparing over time (county vs city vs other counties; keep line data in a comparable shape); City of Clarksville budgets and contracts (M4 sources); comptroller audits and FY2024 actuals (unverified source, later); Bonfire collection (robots) ; commission resolution links (stretch below); alerts; any score, ranking, red flag, "unusual" marker or commentary; vendor ownership or political-donation joins; records-request submission; public URL (G6).

## Stretch (not slice 1)
- **Contract to commission vote:** where an award has a commission resolution already in our vote data, link the contract to that item-history page (and thus roll call and votes). Matching by number or amount is mechanical, exact only, and shown as "Related item" with no inference when not exact.
- Items with dollar amounts in minutes shown in the contract entry as text links.
- Award data from earlier years if the archive or another source holds it.

## Assumptions
- A-F1. Primary user residents (confirmed by CEO, 2026-11-07); the CEO is the only viewer of the preview.
- A-F2. **Focus Group skipped:** private preview, CEO only; revisit before any public launch. **A 3-member Brain Trust will run on this spec** (devil's advocate, a resident's seat, one lens on named-vendor accuracy), once.
- A-F3. Budget columns are those the two books print (FY2023 and FY2025 actuals, FY2026 amended, FY2027 budget), each labelled with the book's header and kind. FY2024 actuals are not in either book and are not shown (the page says "not in these books").
- A-F4. A vendor is shown by name as printed. No merging of similar names in slice 1 except by written mechanical rules applied identically (G2); the source wins.
- A-F5. Dollar amounts are shown as printed, with no inflation adjustment, per-capita figure or comparison.
- A-F6. Public documents only; no records requests (hard stop 4).
- A-F7. Scanned award letters are link-only in 1a; a later OCR spike measures what can be confirmed.
- A-F8. Comparing localities later is possible, so line items keep source account codes and labels as printed.

## Open questions (change the goal; defaults given)
1. **Are award amounts public beyond the bid tabs?** Of the 91 solicitations, only 32 have bid tabs. Default: show what exists, report the coverage count plainly ("32 of 91 have a bid tab"), and ask nothing. If Brian wants gaps filled, the team drafts a TN Public Records Act request for him to send (sending is his hard stop). Recommendation: decide after slice 1 shows the real gap.
2. **Contracts before 2025?** The archive begins in 2025. Default: slice 1 stays 2025-2026; older awards come only from sources found later.
3. **Is Show-as-printed enough for "every opportunity"?** Default: yes, plus export and source links; no derived analysis.

## Next roles
`software-architect` (adapter design for budget books and the purchasing archive, schema, tasks) and `ux-designer` (Finance, Contracts, Capital projects pages, compact tables), in parallel after the Brain Trust. OCR spike is deferred past 1a.
