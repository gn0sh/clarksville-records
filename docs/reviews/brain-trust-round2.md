# Brain Trust, round 2: corrected operator facts (2026-11-07)

Same six members, opus/high, run independently on API credits. Each was told the first review wrongly assumed the
owner was a current candidate, what the first panel changed, and the owner's later decision to show failed-check roll
calls with an asterisk. Devil's advocate: the Opponent. Verdicts: Fix First 6 of 6 (no Go, so no pre-mortem round).

## Chair's summary
**Agreement (6 of 6): the asterisk rule needs one change.** Showing a parsed Yes/No for a roll call that failed the
checks puts a possibly wrong vote under a named person, which is what P3 was written to prevent; 69 of 390 roll calls
(about 1 in 6) would carry one; screenshots drop asterisks. Every member's insisted fix is the same: show the row,
the "not confirmed" note and the PDF page link, but **no vote value**. The spec text (P1, P3, P4, AC-P1) must then be
updated to match whatever is decided.
**Agreement (6 of 6): the governance steps stay.** Not being a candidate removes the campaign angle but not the
conflict: he appears as a voting member in City Council minutes, so at M4 a current or recent council member would
publish his colleagues' votes and his own. Disclosure (G1), mechanical rules (G2), same rules for his own record (G3),
skew check (G4, now on the asterisk rate) and open export (G5) all stay. Only the campaign-finance check is cut.
**Agreement (5 of 6): verify office status and ethics rules before M4.** His term dates (from city sources), and
whether the city ethics code says anything about a member publishing colleagues' records. No member asserted a rule.
**Agreement (6 of 6): transcripts are the riskiest future item.** A misattributed quote is worse than a wrong vote.
Keep them Later, behind a cost estimate and a hand check of speaker attribution; resolve the "no transcript hosting"
non-goal. CivicClerk's robots.txt disallows ClaudeBot by name: several members want the city asked in writing rather
than an internal ADR.
**Minority views:** Budget Hawk would turn G4 from a release blocker into a logged metric (skew is visible once
asterisks are public); Operator, Skeptic and Strategist want G4 kept as a blocker, and that side is stronger because
public asterisks make uneven rates more visible, not less. User wants the About page to state his council service and
dates, not just his name. Opponent and Strategist want the campaign-finance check back as a trigger if he files for
any office.
**Overall call:** Fix First. One owner decision: whether failed-check roll calls show a vote value.

## Decisions this changed
| Finding | Decision changed | Scope | Owner |
|---|---|---|---|
| No vote value on unconfirmed rows | Pending CEO card; preview built on the recommended no-value option | Cuts | frontend-engineer |
| Spec P1/P3/P4/AC-P1 contradict the asterisk rule | Yes: update to the decision | Neither | product-manager |
| G4 applies to the asterisk rate | Yes (already done in a991a10) | Neither | software-architect |
| G4 as metric, not blocker (Budget Hawk) | No: kept as blocker | Neither | manager |
| Verify term dates + city ethics code before M4 | Yes: added to M4 entry gate | Adds | product-manager |
| About page states council service and dates | Yes, after term dates verified | Adds | technical-writer |
| Ask city in writing about CivicClerk robots | Recorded for M4 ADR; contacting the city is a CEO hard stop | Neither | manager |
| Campaign-finance check as trigger on any filing | Yes | Adds | product-manager |
| Transcripts: cost estimate + attribution hand check | Yes, before any go | Adds | product-manager |

## Member answers (verbatim)

### Opponent
**Verdict: Fix First**

**What changed in my view:** The "campaign mouthpiece" attack is weaker now. A worse one replaces it. If he still sits on council, the headline becomes "Council member who lost his race builds AI site tracking his colleagues' votes." That reads as grudge or score-settling, and it doesn't need a campaign to stick. *Judgment call, medium-high confidence. Verify his seat, term end, and whether he plans to run again.*

**Biggest concern:** The asterisk decision reverses P3's own reasoning ("a wrong vote under a named person is the harm") just as the full corpus fell to 82% Verified, below AC-P1's 90% gate. Showing about 69 unconfirmed roll calls with names attached looks like lowering the bar instead of fixing the parser. Screenshots drop asterisks. *Evidence: 321/390 roll calls Verified; the spec still says P3 hold back, so it is now internally inconsistent. High confidence.*

**Other issues:**
- **Conflict of interest in corrections.** N5 routes every correction to Brian. For M4, a sitting member would personally receive and act on disputes about colleagues' records and his own. Mechanical rules (G2) help, but a reporter will ask who checks him. *Judgment call, medium confidence.*
- **Ethics exposure.** A sitting official running a site about fellow officials may fall under city ethics or conduct rules. Check the Clarksville code of ethics and the TN open meetings law on member-to-member communication. *I don't know the answer. Unverified; check before M4.*
- **Transcripts.** Speaker attribution from video makes misquotes likely, and misquotes are worse than vote errors. CivicClerk's robots.txt also disallows ClaudeBot and sets `ai-train=no`. "AI agents scraped a site that bans AI bots" writes itself. *Evidence: platform facts. High confidence that the story gets written.*

**One fix I'd insist on:** Before any public release, unconfirmed rows show **no vote value at all**: only "roll call not confirmed, see PDF p. N". The skew check (G4) must count asterisked rows the same way it counted held-back ones. Then update P3 and AC-P1 so the spec matches the decision.

**Cut:** None. Turn the dropped campaign-finance check into a trigger instead: re-run it automatically if he files for any office. Keep G1–G5 unchanged. Moving from candidate to sitting colleague raises the stakes on disclosure and mechanical rules rather than lowering them.

### Budget
**Verdict: Fix First**

**Biggest concern:** The asterisk decision quietly overturns P1/P3 ("only Verified facts are shown") and AC-P1's 90% gate. The full corpus sits at 82%, so about 69 failed-check roll calls would now appear under named people. If those rows show a parsed vote value, the spec's own "worst failure" is back in scope, and the spec text no longer matches what will be built.
*Evidence:* spec P1/P3/AC-P1 versus the new owner decision. *Confidence:* high on the contradiction. Medium on whether values are shown, because the decision doesn't say.

**Other issues**
- **The conflict concern shrank but didn't vanish.** Dropping the campaign-finance check is fine. But "ZACHARIAS" voting in council minutes means M4 would have a possibly sitting member publishing his own and his colleagues' votes. G1 (disclosure) and G3 (same rules for his own record) still earn their low cost. Verify his current term and end date on clarksvilletn.gov or the Montgomery County Election Commission before M4. *Judgment; medium-high.*
- **Video transcripts are the most expensive item now on the table.** They bring recurring ASR or token spend, speaker attribution that breaks whenever the chair skips a name, and new hosting and terms questions for YouTube. They also strain the "no transcript hosting" non-goal. Keep them in Later, behind a written cost estimate and a separate go decision. *Judgment; high.*
- **CivicClerk is the cheapest source in the project:** an OData API, text PDFs, no OCR. But its robots.txt disallows ClaudeBot by name. The planned ADR must make a real call, not a rationalization. If it's doubtful, ask the city or fall back to manual download links. *Evidence: platform-facts robots line; medium.*

**One fix I'd insist on:** Unconfirmed rows show **no parsed value**. They show only the date, the item label, "not confirmed," and a PDF page link. This is cheaper than parsing up to 90% and removes the wrong-vote risk entirely. Then rewrite P1/P3/AC-P1 to match, with the gate measured on confirmed rows being correct rather than on coverage.

**Cut:** G4 as a *release blocker*.
- Once unconfirmed rows are visible and counted per official under identical wording (P4), skew is self-disclosing.
- The blocker has already needed one recalibration and will keep costing maintenance.
- Keep the per-official rate as a logged metric, but stop it from blocking release.

### Operator
**Verdict: Fix First**

**Biggest concern:** The asterisk decision puts values from failed parses under named people. That brings back the exact harm P3 was written to prevent, and the spec text was never updated: P3 and AC-P1 still say hold back, with a 90% gate. The full corpus is at 82%, so the asterisk route effectively bypasses the gate. "0 wrong of 517" doesn't say whether any failing roll calls were among those checked. (Evidence: the figures you gave. Confidence: high that the spec contradicts the decision; medium on the accuracy exposure.)

**Other issues:**
- **His office status.** Being a non-candidate removes the campaign angle, not the conflict. If he sits on Council, a sitting member is publishing colleagues' records, including unconfirmed ones. Before M4:
  - Verify his term dates.
  - Check whether the Clarksville city ethics code or charter limits members operating such a site.
  - Check whether his own votes get any different handling, including what is held back or corrected.
  
  (Judgment call. Confidence: medium. I haven't checked those rules.)
- **Transcripts are the new high-risk surface.** Speech recognition plus attributing lines to speakers by name gets the speaker wrong more often than roll-call parsing. Also:
  - Check YouTube's terms on downloading and transcribing.
  - The non-goal "no transcript hosting" would need revising.
  - Require that a transcript line attributed to a person is shown only when a hand check of the speaker attribution passes.
  
  (Judgment call. Confidence: medium-high.)
- **Day-one breaks.**
  - Cloudflare already returned 403 from dev2. Collectors on free hosting usually run from shared cloud IP ranges, which may be blocked the same way, so test from the actual runner before relying on the schedule. (Confidence: medium.)
  - A4 still names dev2. Confirm where the 2020–21 minutes now come from.
  - The CivicClerk ADR is still owed. Its robots.txt disallows ClaudeBot and sets use=reference, and our agents are AI. Get it decided explicitly, ideally by email to the city clerk, not by our own interpretation.

**One fix I'd insist on:** An unconfirmed row shows no vote value. It shows only "Vote not confirmed: see PDF p.X," with the link. Then:
- Rewrite P3 and AC-P1 to match.
- Keep G4. Asterisk rates are now publicly visible per official, so measuring skew in them matters more, not less.
- Show the unconfirmed count per official with identical wording for everyone.

**Cut:** Only the campaign-finance check, which is already dropped. Keep G1–G5. They matter as much now that he is an official as when he was a candidate.

### Skeptic
**Verdict: Fix First**

**Biggest concern:** The asterisk decision puts unconfirmed votes under named people, and it skips the spec's own gate. The full corpus is at 82% verified against AC-P1's 90%, and P1/P3 still say "hold back." Failed-check rows are where parse errors cluster, so the 0-of-517 hand-check doesn't cover them unless those 517 included unconfirmed rows.
*Evidence:* the corpus numbers above. *Judgment* on where errors cluster. *Confidence:* high.

**Other issues**
- **An incumbent operator raises the stakes.** "Not a candidate" removes the campaign angle, but if he sits on the Council, a current official is publishing his colleagues' records and his own. That conflict peaks at M4. G1 disclosure and G2 mechanical rules matter more now, not less.
  - Check his term dates from city sources, not minutes.
  - Check the city's ethics code and Tennessee open-meetings rules for anything touching a member publishing on colleagues.
  - *Evidence:* "AYE: … ZACHARIAS" in council minutes. *Confidence:* medium.
- **Skew now shows publicly.** G4 measures *held-back* rates, but held-back rows are now visible asterisks. A commissioner whose rows are disproportionately asterisked looks less reliable on the site. G4 must apply to the asterisk rate, and P4 wording must change. *Judgment. Confidence:* medium.
- **Transcripts and CivicClerk carry real risk.**
  - Speaker attribution from auto-transcripts is a new named-person error source with no P2-style check.
  - The "no transcript hosting" non-goal conflicts with AC6.3.
  - CivicClerk explicitly disallows ClaudeBot, and AI agents build and run this collector. The planned ADR rationalising "we're not a training crawler" is the kind of call that looks bad later. Ask the city in writing first.
  - *Evidence:* the robots facts above. *Confidence:* medium-high.

**Pre-mortem weakest link:** a scheduled collector on free hosting, maintained with limited build capacity. One Cloudflare block (dev2 already returns 403) or a layout change silently freezes the data. Meanwhile visible "not confirmed" rows accumulate with no one fixing them. *Judgment. Confidence:* medium.

**One fix I'd insist on:** Unconfirmed roll calls show **no vote value**, only "Roll call not confirmed – see PDF p. X." Also:
- Update P1, P3, P4 and AC-P1 to match the new decision.
- Keep 90% verified as the gate for going public.

This keeps the transparency the owner wants without displaying a possibly wrong vote.

**Cut:** none. The campaign-finance check was rightly dropped. Every other step (disclosure, mechanical rules, owner-same-rules, skew check, open export, the G6 hard stop) protects against a conflict that the corrected facts make sharper.

### Strategist
**Verdict: Fix First**

**Biggest concern:** The corrected fact makes the operator's position harder to defend, not easier. He is apparently a sitting council member, not a private resident, and he has decided to show unconfirmed roll-call values under colleagues' names. About 69 of 390 county roll calls (18%, from your corpus figures) would carry an asterisk. A wrong vote shown under a named official, published by a fellow official, will be read as intent, not as an OCR error. The spec's P3 still says "hold back," so the spec and the owner's decision now contradict each other. *Evidence: the corpus pass rate and the P3 text. Perception is a judgment call. Confidence: high.*

**Other issues**
- **Unverified office status.** If he still holds office, M4 means he curates his own record next to his colleagues'. If his term ends soon, the site looks like positioning for a return run. In either case, verify his term dates and check the City of Clarksville ethics code and TN rules on sitting officials publishing records of colleagues. I am not asserting a specific rule exists. *Judgment call. Confidence: medium.*
- **Transcript comments.** These would commit him to video processing and speaker attribution indefinitely, and they conflict with the "no transcript hosting" non-goal. A misattributed quote of a colleague is worse than a wrong vote, because it puts words in someone's mouth. Also, the CivicClerk portal disallows ClaudeBot and signals `ai-train=no`. "A council member's AI agents scraped the city portal" is a bad headline even if the ADR is sound. *Evidence: the platform facts. Confidence: medium-high.*
- **Lock-in.** Once the site is public, he is its maintainer. "Handoff to a nonpartisan steward" sits on the Later list. If he runs again, the site becomes a de facto campaign asset, and the dropped campaign-finance question returns. *Judgment call. Confidence: medium.*

**One fix I'd insist on:** For unconfirmed roll calls, show only "Roll call not confirmed – see PDF page X," with no parsed Yes/No value. Then amend P3 to match. This keeps the transparency the owner wants without printing a possibly wrong vote under anyone's name.

**Cut:** None. The skew check (G4) matters more now that asterisks fall on named people, and disclosure (G1) matters more for a sitting official. Bring the campaign-finance check back as a trigger that runs automatically if he declares any candidacy.

### User
**Verdict: Fix First**

**Biggest concern:** The asterisk decision puts possibly wrong votes under named people, the harm P3 was written to prevent. It is also a way around the spec's own 90% gate: 321 of 390 county roll calls (82%) pass, so about 1 in 6 votes would carry an asterisk. As a resident, I'd read "Yes*" as a Yes and screenshot it without the asterisk. *Evidence: spec P1/P3/AC-P1 versus the new owner decision; 82% is the team's own number. The reading behaviour is a judgment call. Confidence: high on the conflict, medium on behaviour.*

**Other issues**
- **The operator was (or is) a council member.** The corrected fact changes the reason for disclosure, not the need. A footer that just names "Brian Zacharias" won't tell me he served on the council whose votes M4 shows. The About page should state his council service and dates, and point to his own page. Before writing it, verify from the city roster whether he still holds office and until when. *Evidence: "AYE: … ZACHARIAS" in CivicClerk minutes. Confidence: high.*
- **The spec now contradicts the decision.** P3 still says "held back", P4 still says "not shown", and AC-P1 still requires 90%. If the asterisk rule ships, the published rules (G2) won't match what I see, which is exactly the trust failure G2 exists to prevent. *Evidence: spec text. Confidence: high.*
- **Transcript-based "spoken comments" carry a new attribution risk.** Speech-recognition transcripts mislabel speakers, especially in crosstalk. A quote wrongly attributed to an official is worse than a wrong vote, because it reads as their words. Also, CivicClerk's robots.txt disallows ClaudeBot and sets ai-train=no. Settle that ADR before M4, not after. *Evidence: platform facts. Speaker-error risk is a judgment call. Confidence: medium.*

**One fix I'd insist on:** For roll calls that fail the checks, show the row (date, item, link to the exact PDF page) but **no vote value**. Use plain wording such as "Vote not read automatically, see page 14 of the minutes." Keep the per-official count of these rows (P4) and keep G4's skew check on that count. I still get full transparency, and no one sees an unconfirmed Yes or No next to a name.

**Cut:** none beyond the campaign-finance check already dropped. Disclosure, mechanical rules, the own-record rule, the skew check and open export all still apply. Disclosure arguably matters more now that the operator is a recent or current official rather than a candidate.
