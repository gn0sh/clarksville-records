# Brain Trust: clarksville-records spec (2026-11-07)

Panel: 6 members, opus/high, run independently on API credits (spec at 7671689). Devil's advocate: the Opponent.
Verdicts: Rethink 1 (Opponent), Fix First 5. No unanimous Go, so no pre-mortem round needed.

## Chair's summary
**Agreement (6 of 6):** the spec governs how the data looks but not who is seen running it. The owner is a local
political candidate, and the site has no operator disclosure, and every judgment call (held-back votes, name merges,
corrections) goes to him alone. That is the top risk to trust, ahead of any parsing problem.
**Agreement (6 of 6):** US6 "comment history" promises speech the county minutes don't contain (they record movers
and seconders only). Label it "Motions and seconds"; spoken comments would need video transcripts, the highest-risk source.
**Agreement (5 of 6):** held-back votes may cluster on certain officials (OCR quality varies by scan, year, name), which
reads as curation. Measure the held-back rate per official and gate release on it.
**Disagreement:** how far to cut M1. Budget Hawk and Operator: M1 = US1 + US2 + accuracy gates as a batch ingest, after
a parse spike; defer search, corrections, US6, US7 and the scheduler. Others didn't object to scope. Stronger side:
the spike-first cut, because the parse rate is the unknown that decides everything else. But US7 and automation were
explicit asks from the CEO, so they stay in M1 after the spike passes; search and the public correction form move to
before public launch.
**Minority view (Opponent, in full):** if disclosure, rule-based corrections, a skew check and a legal check can't be
done credibly, this owner shouldn't build it. Chair: the fixes below are cheap and make the strongest objection
answerable; the decision on disclosure is the CEO's.
**Strongest alternative, steelmanned:** don't build; point residents to the county's own minutes page and the paid
summaries service. It loses because neither shows per-member votes or links each fact to its source, which is the
whole goal. A narrower alternative (publish an open dataset only, no site) is cheaper but doesn't meet "click an
official" and "click an item".
**Overall call:** Fix First. The one question to answer before going public: how the site says who runs it.

## Top 3 changes
1. Add an "Operator and governance" section: disclosure decision (CEO), mechanical correction rules (the source PDF
   wins, every change logged publicly, no case-by-case calls), the same rules for the owner's own record if he holds
   office, an open data export, and a pre-public hard stop that includes a campaign-finance check with the Tennessee
   Registry of Election Finance (the panel asserted no rule; it is something to check).
2. Parse spike first: about 10 minutes PDFs across 2020-2024, measuring the Verified rate and held-back rate per
   official, before the rest of M1 is built. Below 90% Verified, or skewed, goes back to the CEO.
3. Rename US6 to "Motions and seconds"; get the roster from a source other than the minutes being checked; the private
   preview must be provably private (no public URL).

## Decisions this changed
| Finding | Decision changed | Scope | Owner |
|---|---|---|---|
| No operator disclosure; candidate controls judgment calls | Yes: governance section added; disclosure wording is the CEO's decision | Adds | product-manager (spec), CEO (disclosure) |
| US6 comments not in source | Yes: renamed "Motions and seconds"; transcripts stay Later | Cuts | product-manager |
| Held-back votes may skew by official | Yes: per-official held-back rate check gates release | Adds | software-architect, qa-engineer |
| M1 too big; parse rate unknown | Yes: parse spike first; search and public correction form move to pre-launch | Cuts | manager |
| Roster for P2 is circular | Yes: roster from the county's commissioner list or the minutes' own attendance header, cross-checked | Changes | software-architect |
| Private preview may leak on free public hosting | Yes: preview must have no public URL (private claude.ai page or local files) | Changes | software-architect |
| BIS Online robots/terms unverified, page anchors unknown | Checked 2026-11-07: no robots.txt (404), PDFs served directly so #page anchors work; terms still to read | None | software-architect |
| Brian's own record if elected | Yes: same rules, written in governance | Adds | product-manager |
| Exit plan / data export | Yes: open export in governance; steward handoff noted as Later | Adds | product-manager |
| Parsing must be deterministic code, not per-page LLM calls | Yes: recorded as an architecture constraint | None | software-architect |

## Member answers (verbatim)

### skeptic
**Verdict: Fix First**

**Biggest concern:** The owner is a local candidate, and the spec routes every judgment call to him personally. Held-back roll calls (P3), merge rules (AC1.1), and correction reports (N5/AC5.2) all go to Brian, and Brian alone decides public launch timing. Neutral layout does not neutralise a candidate deciding which of his possible opponents' votes become visible, and when. The spec never states whether Brian is, was, or will run against anyone in the commission roster, and never requires the site to disclose who runs it.
*Evidence:* the stated facts plus P3, N5 and A1. *Confidence:* high that this is the most likely reputational failure. Whether it creates campaign-finance or ethics exposure is a judgment call. Check Tennessee Registry of Election Finance guidance; I am not asserting any rule.

**Other issues**

- **US6 promises what the source cannot deliver.** The platform facts say minutes "record no spoken comments or discussion," only movers and seconders. "See what they said" will either disappoint or push toward the transcripts the spec rules out. US6 and US7 were also added on the same day as the spec into a "thin slice," with limited build capacity.
  *Evidence:* platform facts. *Confidence:* high.

- **Held-back votes and excluded attendance are likely not random.** They will cluster in bad scans, odd layouts and certain years, so some officials' records will be shown less completely than others'. This undermines N1/N3 even with P4's count. In addition:
  - OCR errors in names and stated tallies can make P2 reject correct roll calls.
  - A 20-vote spot check cannot support a "0 wrong votes" claim across thousands of rows.

  *Evidence:* "scans with OCR text layer, which has errors." *Confidence:* medium. Measure the held-back rate per official before trusting the 90% gate.

- **The data will be stale and fragile at any launch.** Coverage stops at 2024, the 2025–26 minutes location is unknown, and the index sits on a dev host. In addition, a no-account error-report form needs a backend that free static hosting does not provide, and nothing addresses spam.
  *Evidence:* A3, A4, hosting plan. *Confidence:* medium-high.

**One fix I'd insist on**

Before design, add a conflict-and-disclosure section to the spec with three parts:

1. **State Brian's relationship to the data.** Record whether Brian appears in the roster or faces anyone in it.
2. **Add a required on-site ownership statement**, to be shown before any public launch.
3. **Give mechanical rules for anything touching a named official.** Release of held-back roll calls, name merges and corrections must follow published rules, applied identically and logged publicly. Brian may not decide them case by case.

### opponent
**Verdict: Rethink**

**Biggest concern:** The site is a database of named officials' votes and attendance, built and controlled by a sitting local candidate. Neutral display rules (N1–N6) do not change who owns it, and the spec has no ownership disclosure and no conflict-of-interest policy. A reporter's headline writes itself: "Candidate quietly builds attendance tracker on local officials." It will be read as opposition research no matter how neutral the layout is. *Evidence: owner facts; the spec has no disclosure requirement. Confidence: high that the framing lands. Whether the site counts as campaign activity under Tennessee rules is unknown; check with the TN Registry of Election Finance or an attorney.*

**Other issues:**
- **The candidate controls corrections and the held-back facts.** N5, AC5.2 and P3 route every error report and every held-back roll call to Brian alone. That makes a candidate the sole arbiter of which votes by his potential rivals get shown, fixed or held. An official who feels misrepresented will say exactly that. *Evidence: spec text. Confidence: high.*
- **US6 promises "comment history," but the source has none.** Platform-facts says the minutes "record no spoken comments or discussion." Under a "comments" heading, motions and seconds imply speech that didn't happen, and an empty section looks like "this official said nothing." *Evidence: platform-facts versus AC6.1. Confidence: high.*
- **Held-back votes may cluster on some officials, which looks like curation.** The minutes are scans with an OCR text layer that has known errors. If some names or layouts OCR badly, those officials get more votes held back. P4 then shows uneven "under review" counts per person, and a hostile reader calls it selective. Separately, US6 and US7 were added on the same day, on top of two other products. That invites a rushed, error-prone M1 where one wrong vote is the story. *Evidence: OCR fact plus P3/P4. The skew itself is a judgment call; medium confidence. Measure held-back rates per official.*

**One fix I'd insist on:** Before design, write a governance section and make it a hard requirement:
- Ownership and candidacy disclosed on every page.
- Corrections decided by fixed written rules: the source PDF wins, and every change is logged publicly.
- A per-official held-back rate check that blocks release if the rate is skewed.
- A documented legal check on candidate-operated sites.

If that can't be done credibly, this shouldn't be built by this owner.

### budget
**Verdict: Fix First**

**Biggest concern:** M1 is not a thin slice. It bundles a scheduled collector, OCR roll-call parsing, search (US3), a correction backend (US5), comment history (US6) and cross-document item threading (US7). All of it is for one viewer, on a 2020-2024 corpus that will not grow until someone finds where 2025+ minutes live. The scope is gated on a ≥90% Verified rate, and parse effort has no ceiling. *(Judgment call, high confidence. Evidence: the M1 definition, A3, and platform-facts "scans with OCR text layer, which has errors".)*

**Other issues:**
- **US6 has little to show.** Platform-facts says the minutes "record no spoken comments or discussion", only movers and seconders. A "comment history" is therefore a mover/seconder column already present in each roll-call row. Building a separate type, filter and history UI for that adds cost with near-zero return. *(Evidence: verified source fact. High confidence.)*
- **P2 needs a "roster for that date" that has no source.** Committee assignments and rosters sit on the Later list, and AC1.1 builds the commissioner list from roll calls themselves. That is circular. Either someone hand-builds a roster, which breaks Goal 3, or a new scraper is needed. Check whether the county publishes term and roster history before design. *(Evidence: spec cross-reference. Medium-high confidence.)*
- **US5 and the scheduler are premature.** The private preview has exactly one viewer, Brian, so a correction-report path adds a form or backend on "free static hosting" with nobody to report. A scheduler on a frozen minutes corpus mostly buys breakage. The dev-host index (A4) will raise alerts with nothing new to collect. Agendas update monthly, but a manual re-run covers the preview. *(Judgment call, medium-high confidence.)* Also confirm that parsing is deterministic code, not per-page LLM calls. The spec is silent, and re-parsing for regressions under AC-P2 multiplies any token spend. *(Unknown. Check with the architect.)*

**One fix I'd insist on:** Cut M1 to US1 + US2 + the AC-P accuracy gates, built as a one-off batch ingest of the 2020-2024 minutes. Front-load a time-boxed parse spike on about 10 sampled minutes PDFs from different years and measure the Verified rate. If the spike lands far below 90%, return to Brian with "Rethink" before building anything else. Move US3, US5, US6 (fold movers and seconders into the vote row), US7 and the scheduler into M1.5, conditional on the spike passing.

### user
**Verdict: Fix First**

**Biggest concern:** The site is owned by a local candidate, yet the spec never says who runs it or how a visitor learns that. If I find out from a neighbour or a news story that a candidate built a page tallying commissioners' absences, I'll read it as opposition research no matter how neutral the layout is. N1–N6 govern how the data looks, not who stands behind it. *(Evidence: the owner context plus the absence of any disclosure requirement in the spec. Whether disclosure is legally required is something to check with Tennessee campaign or election rules, not something I'm asserting. Confidence: high that it damages trust; legal side unknown.)*

**Other issues:**
- **"Comment history" promises something the data can't deliver.** US6 says I'll "see what they did and said." Platform facts state the minutes "record no spoken comments or discussion," only who moved and seconded. If I click "comments" and get "Moved" and "Seconded" rows, I'll feel misled or assume something was hidden. *(Evidence: platform-facts. Confidence: high.)*
- **The newest data is about two years old.** It's November 2026 and M1 stops at 2024 minutes. The commissioners I most want to look up are current ones, including anyone seated after 2024, and they'll show little or nothing. Check the actual seating dates of current members. A stale page also undercuts "come back." *(Evidence: A3. Confidence: high on the gap; its impact depends on roster turnover.)*
- **Held-back votes may land unevenly across officials.** OCR errors on particular names or page layouts could hold back more of one member's votes than another's. A resident comparing "3 not shown" with "14 not shown" will suspect bias, even though P4's wording is identical for everyone. Separately, P2 verifies tallies but not motion text, so garbled OCR item labels could appear verbatim. *(Judgment call. Confidence: medium. Check the held-back distribution per member in the M1 run.)*

Also a minor confusion: the name "clarksville-records" suggests city council, but M1 covers only the County Commission.

**One fix I'd insist on:** Add a neutrality rule, N7, requiring a plain "Who runs this site" statement on every page. It should name the owner's candidacy and state the data rules (sources only, no selection, same treatment for all members). Its wording should be decided and reviewed before public launch, not after. Without it, everything else in the spec that builds trust can be undone by one discovery.

### operator
**Verdict: Fix First**

**Biggest concern:** Free static hosting is typically public by default. The spec has no confirmed access control for the "private preview," so a candidate-built record of named officials could become public before Brian decides to launch. That would also expose the unaddressed question of whether a site run by a candidate counts as campaign activity under Tennessee election rules. *Evidence: the spec defers preview access to "architect proposes cheapest no-spend option," and the owner is a candidate per context. The campaign-law question is a judgment call; check it with the TN Registry of Election Finance or an attorney before launch. Confidence: high on the hosting gap, medium on the legal exposure.*

**Other issues:**
- **P2 depends on a roster that has no source.** The check "names match the roster for that date" needs an authoritative roster by date. The minutes' OCR has name errors, and deriving the roster from those same minutes is circular. Building it by hand conflicts with Goal 3. Without a roster source, nothing reaches Verified. *Evidence: platform facts (OCR errors) and the spec. Confidence: high.*
- **US6 promises comments the source does not contain.** The minutes record movers and seconders but "no spoken comments or discussion." A "comment history" populated only with motions and seconds misdescribes the record of named people. Label it "Motions and seconds." *Evidence: platform facts. Confidence: high.*
- **BIS Online is the least-verified dependency on the critical path.** Its robots.txt is unverified, its terms of use are unchecked, the index sits on a dev host, and nobody has confirmed that `viewpdf.php?id=` URLs support page anchors. If they don't, AC1.3 forces mirroring the PDFs, which raises licensing and storage questions. Verify all of this before design. Also cut M1 scope: build collector, then attendance, then votes. Defer US6, US7 and search until AC-P1 and AC-P2 pass, given build capacity is shared with two other products. *Evidence: spec A4 and platform facts; the scope cut is a judgment call. Confidence: medium.*

**One fix I'd insist on:** Before design starts, the architect names a zero-cost hosting setup that provably blocks non-Brian access, plus a correction-report intake that works without visitor tracking (N6). The spec should also add a hard stop: no public URL until (a) a campaign-finance and conflict review is done and (b) an operator-disclosure statement is decided.

### strategist
**Verdict: Fix First**

**Biggest concern:** The spec controls what the site *says* about officials, but not *who is seen saying it*. A sitting candidate publishing named attendance and vote records of the officials he may be running against will be read as opposition research, whatever N1–N6 enforce. The spec has no requirement on operator disclosure or the candidate conflict, so "no campaign link" becomes the only defense, and a weak one once someone discovers who runs it. *(Judgment call, high confidence.)*

**Other issues**
- **US6 cannot deliver what Brian asked for.** Platform facts say the minutes record movers and seconders but "no spoken comments or discussion." Labeling motions and seconds as "comments" over-promises. It also creates pressure to add YouTube transcripts next, the highest-risk source for attributing words to named people. Rename the feature to "motions and seconds" and drop the "what they said" framing. *(Evidence: platform-facts, high confidence.)*
- **Uneven held-back counts can look like bias.** OCR errors are documented. If they cluster on certain names or years, P4's "N not shown under review" will differ by official. A visibly larger gap for an opponent invites a bias charge. Report held-back rates per official internally before any public decision. *(Judgment call, medium confidence.)*
- **Scope and lock-in.** US6 and US7 make M1 no longer a thin slice, on a team already running two products. Once public, the site creates obligations: handling disputes from officials, keeping it current, and showing Brian's own record identically if he is elected. Taking it down later will read as hiding something. *(Judgment call, medium-high confidence.)*

**One fix I'd insist on:** Before design starts, add an "Operator and conflict" requirement section with these parts:
1. **Disclosure:** a decision on how the site discloses who operates it, made now, because it affects the domain, the About page and the footer.
2. **Brian's own record:** a commitment that his record appears under identical rules if he takes office.
3. **Pre-public checks (hard stop):** before going public, Brian checks with the Tennessee Registry of Election Finance whether a candidate-run site covering incumbents counts as a campaign expenditure or contribution. He also checks election-calendar timing for the race he is in. I am not asserting a rule either way; verify both.
4. **Exit plan:** export the data openly and identify a possible handoff to a nonpartisan steward, so the site is not tied to his candidacy.
