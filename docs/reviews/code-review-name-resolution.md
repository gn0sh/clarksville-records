# Code review: name resolution (fresh, independent)

Date: 2026-11-09. Reviewer: code-reviewer (opus/high). Read-only. Verdict: **REQUEST CHANGES**.

## Findings

1. **city-votes/titled-nonmember (MEDIUM-HIGH, reproduced).** `collector/city_minutes.py:451-484`, `city_build.py:421-430`.
   NOT_SITTING_RE only catches "former"/"late" directly before the title. Missed forms (confirmed via `titled_names()`):
   "former City Councilman David Allen", "then-Councilman Bill Powers", "Former Ward 7 Councilwoman ...",
   "County Mayor Wes Golden", plain "a resolution honoring Councilman X".
   Repro: 2025-01-02 full-name list; 2025-08-07 with ALLEN replacing REYNOLDS in surname list plus text
   "honored former City Councilman David Allen" -> ALLEN resolves to city-david-allen and the roll call is verified.
   Stored data: N4 already picks up non-members ("Jim Durrett" 2019-05-02, 2020-03-23/04-21/06-04/08-06, likely the
   County Mayor; "Bill Powers" 2019-06-20) and junk ("Pro Tem", "Smith With", "Allen Seconded").
   Suggested fix: a titled name counts only when corroborated (by the book, or by an action context: moved, seconded,
   led the Pledge); otherwise hold. Test gap: test_n4 only checks the "former Councilman" form.
2. **city-votes/alias-in-votes (LOW, docs).** Architecture doc N2 row says aliases apply in N7, but `resolve()`
   (`city_build.py:83`) never canonicalizes vote/mover/seconder tokens. Fails safe (held). Fix docs or canonicalize.
3. **city-votes/empty-book-2027 (LOW/INFO).** Attendance prints surnames only since 2025-03, so the replaced-seat rule
   can't fire and after the 2027-01-01 seating the window holds no full-name lists. Residual risk is wider than stated:
   a successor sharing the surname of any member who left since 2025-02-06 resolves to that member.

## What was checked
RosterBook.for_meeting window/seat/cut rules and held reasons; resolve_surnames; resolve(); mover/seconder and presiding
mayor paths; duplicate surnames; Tim Chandler across terms; misspellings held; seating config basis (wholesale changes
2017/2019/2021/2023/2025 Januaries). 12 name tests pass; mental reverts each caught except `d == last` for a ward-less
entry. Spot check of 7 verified 2026 roll calls against pdftotext: all exact. Full suite not run (timeout).

## Delta re-review of 15dd2e4 (fixes c2324d0, 063e098): REQUEST CHANGES
1. city-votes/titled-nonmember still open (MEDIUM): ACTING_*_RE match prose ("WHEREAS, Councilman David Allen moved to Clarksville in 1985", "presided over the Finance Committee", "presentation was made by", "honoring ..., seconded by the Council", Pledge led by a former member, "Mayor Wes Golden of Montgomery County"). Reproduced end to end: ALLEN -> city-david-allen verified.
2. city-votes/presiding-guest (LOW, pre-existing): resolve_surnames adds the presiding name unchecked; a County Mayor chairing a joint session would become a city official titled Mayor.
3. alias-in-votes RESOLVED. 4. empty-book-2027 RESOLVED (docs).
Holds: widened NOT_SITTING_RE, NOT_NAME_WORDS junk filter, earlier repro held, `d == last` pinned. 68 name tests pass.

**Manager decision:** stop inferring from prose. Titled names in minutes text never add a candidate; surnames resolve only via the roster book or a cited config entry; an unknown presiding name is held. Fix run at opus/xhigh (escalated).
