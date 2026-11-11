# RPC motion rule 10: mutation run (`rpc-votes/tests-not-pinning`)

backend-engineer, 2026-11-11. Script: `tools/rpc_rule10_mutation.py <tree>`, run on a `git archive` copy of the branch.
Each row deletes one thing, one at a time: a SHAPES entry, a 10b tail trigger, a MEMBER_VOTE alternative, a 10a check,
or a 10c/10d attribution branch. It then runs `collector/tests/test_rpc_rule10.py` and `collector/tests/test_rpc_minutes.py`
(`-x`). A mutant counts as killed when at least one test fails.

The first run killed 40 of 51 mutants. The 11 survivors were handled as follows:
- 9 are now pinned by new tests: the mover clause's titled name and vote word, the four clause-order checks, the rule
  that an outcome clause is required, and lead attribution only to the section's own case.
- 2 were deleted because they are subsumed: MEMBER_VOTE "did not vote" and "not vot", which any vote form already matches.
- One test sentence ("Motion passed, motion carried.") was changed so that it reaches the clause it pins.

Final run:

| mutant | result | first failing test |
|---|---|---|
| 10a shape: seconded by M | killed | test_real_2024_10_29_motion_13_the_lead_abstention_is_attributed[Stacey |
| 10a shape: the motion was seconded by M | killed | test_each_shape_is_confirmed[text1-extra1-nays1-abstained1-CASE |
| 10a shape: M seconded | killed | test_in_favor_and_the_motion_failed_is_one_outcome |
| 10a shape: M seconded it / the motion | killed | test_each_shape_is_confirmed[text5-extra5-nays5-abstained5-CASE |
| 10a shape: with M second | killed | test_each_shape_is_confirmed[text4-extra4-nays4-abstained4-CASE |
| 10a shape: [with a ]second from M | killed | test_each_shape_is_confirmed[text6-extra6-nays6-abstained6-CASE |
| 10a shape: M voted nay | killed | test_each_shape_is_confirmed[text7-extra7-nays7-abstained7-CASE |
| 10a shape: M abstained | killed | test_each_shape_is_confirmed[text8-extra8-nays8-abstained8-CASE |
| 10a shape: M abstained from <case> | killed | test_real_2022_09_27_motion_16_an_abstention_on_its_own_case_is_read |
| 10a shape: all ... in favor | killed | test_real_2022_09_27_motion_16_an_abstention_on_its_own_case_is_read |
| 10a shape: others in favor | killed | test_each_shape_is_confirmed[text13-extra13-nays13-abstained13-CASE |
| 10a shape: except M who ... | killed | test_each_shape_is_confirmed[text9-extra9-nays9-abstained9-CASE |
| 10a shape: but M who ... | killed | test_each_shape_is_confirmed[text10-extra10-nays10-abstained10-CASE |
| 10a shape: outcome | killed | test_in_favor_and_the_motion_failed_is_one_outcome |
| 10a shape: consent agenda passes with approval | killed | test_each_shape_is_confirmed[text14-extra14-nays14-abstained14-] |
| 10a shape: cases were approved for deferral | killed | test_each_shape_is_confirmed[text15-extra15-nays15-abstained15-] |
| 10a shape: meeting was adjourned at H:MM p.m. | killed | test_each_shape_is_confirmed[text19-extra19-nays19-abstained19-CASE |
| 10a shape: with M voting nay | killed | test_each_shape_is_confirmed[text16-extra16-nays16-abstained16-CASE |
| 10b tail trigger: OUTCOME | killed | test_an_outcome_in_favor_or_motion_after_the_outcome_is_not_confirmed[Staff |
| 10b tail trigger: FAVOUR | killed | test_an_outcome_in_favor_or_motion_after_the_outcome_is_not_confirmed[Staff |
| 10b tail trigger: motion | killed | test_a_pulled_consent_case_after_the_vote_is_not_confirmed |
| 10b tail trigger: moved | killed | test_a_second_motion_after_the_outcome_is_not_confirmed[Mrs. |
| 10b tail trigger: seconded | killed | test_a_second_motion_after_the_outcome_is_not_confirmed[Mr. |
| outcome words: free text instead of the vocabulary | killed | test_an_outcome_holds_only_its_vocabulary[All |
| body runs to an outcome-shaped sentence | killed | test_an_outcome_holds_only_its_vocabulary[All |
| rule 9: a vote word after the 'in favor' sentence in the body | killed | test_a_vote_word_after_the_in_favor_sentence_drops_it_as_the_outcome |
| polarity: table / postpone / continue | killed | test_an_outcome_of_another_kind_of_motion_is_not_confirmed[All |
| polarity: a mover naming no kind passes | killed | test_an_outcome_naming_a_kind_the_mover_did_not_is_not_confirmed[text4] |
| kind: table | killed | test_real_2025_03_25_motion_9_tabling_the_case_stays_confirmed |
| kind: postpone | killed | test_a_mover_and_outcome_of_one_kind_are_confirmed[text0-Motion |
| kind: continue | killed | test_a_mover_and_outcome_of_one_kind_are_confirmed[text1-Motion |
| kind: table needs the verb | killed | test_table_and_continue_as_nouns_are_not_a_kind[for |
| polarity: an election or adjournment passing for approval | killed | test_an_election_or_adjournment_passing_for_approval_is_confirmed[text0-Motion |
| 10a mover clause: lack of a second | killed | test_a_lack_of_a_second_in_the_mover_clause_is_not_confirmed |
| kind: two kinds in the mover's words | killed | test_recommend_with_a_past_participle_of_another_kind_is_not_confirmed[made |
| kind: two kinds shown under the first | killed | test_recommend_with_a_past_participle_of_another_kind_is_not_confirmed[made |
| kind: recommend before another kind | killed | test_one_kind_named_through_another_kinds_words_is_confirmed[made |
| kind: recommend alone | killed | test_table_and_continue_as_nouns_are_not_a_kind[for |
| kind holds: consent agenda | killed | test_an_abstention_before_a_list_motion_under_a_case_is_not_attributed |
| kind holds: minutes | killed | test_a_case_section_with_no_motion_is_no_other_motions_scope |
| kind holds: deferrals hold defer | killed | test_each_shape_is_confirmed[text15-extra15-nays15-abstained15-] |
| kind holds: deferrals hold withdraw | killed | test_a_list_kind_holding_only_its_own_words_stays_confirmed[made |
| kind holds: deferrals hold approval | killed | test_each_shape_is_confirmed[text15-extra15-nays15-abstained15-] |
| polarity: postpone is its own | killed | test_table_postpone_and_continue_are_each_their_own_polarity[to |
| polarity: continue is its own | killed | test_table_postpone_and_continue_are_each_their_own_polarity[to |
| kind stems: table | killed | test_recommend_with_a_past_participle_of_another_kind_is_not_confirmed[made |
| kind stems: postpone | killed | test_recommend_with_a_past_participle_of_another_kind_is_not_confirmed[made |
| kind stems: continue | killed | test_continue_as_a_bare_verb_is_a_second_kind_of_the_two_kinds_check |
| kind stems: deny | killed | test_recommend_with_a_past_participle_of_another_kind_is_not_confirmed[made |
| kind stems: read for the two kinds | killed | test_continue_as_a_bare_verb_is_a_second_kind_of_the_two_kinds_check |
| kind nouns: Use Table | killed | test_table_and_continue_as_nouns_are_not_a_kind[for |
| kind nouns: continue as | killed | test_table_and_continue_as_nouns_are_not_a_kind[for |
| kind: a stem alone names no kind | killed | test_table_and_continue_as_nouns_are_not_a_kind[for |
| kind: the deferrals list names a deferral | killed | test_approving_a_withdrawal_is_not_the_deferrals_list[CASE |
| mover negation: in the kind's words | killed | test_a_negation_in_the_mover_clause_is_not_confirmed[made |
| mover negation: the whole clause when no kind | killed | test_a_negation_in_the_mover_clause_is_not_confirmed[made |
| mover negation: a negated kind anywhere | killed | test_a_negation_in_the_mover_clause_is_not_confirmed[made |
| mover negation: 'no' | killed | test_a_negation_in_the_mover_clause_is_not_confirmed[made |
| gate: minutes after CHECKED_THROUGH | killed | test_motions_of_minutes_after_the_gate_date_are_never_confirmed |
| 10c MEMBER_VOTE: abstain | killed | test_a_member_vote_in_the_lead_is_not_confirmed[Mr. |
| 10c MEMBER_VOTE: recus | killed | test_a_member_vote_in_the_lead_is_not_confirmed[Mr. |
| 10c MEMBER_VOTE: conflict | killed | test_a_member_vote_in_the_lead_is_not_confirmed[Mrs. |
| 10c MEMBER_VOTE: refrain | killed | test_a_member_vote_in_the_lead_is_not_confirmed[Mr. |
| 10c MEMBER_VOTE: \bna[yv]s?\b | killed | test_a_member_vote_in_the_lead_is_not_confirmed[Nays: |
| 10c MEMBER_VOTE: \bvot(?:e|es|ed|ing)\b | killed | test_a_member_vote_in_the_lead_is_not_confirmed[Mr. |
| 10a mover clause: titled name | killed | test_the_mover_clause_holds_no_title_or_vote_word[text0] |
| 10a mover clause: vote word | killed | test_the_mover_clause_holds_no_title_or_vote_word[text1] |
| 10a mover clause: exception word | killed | test_the_mover_clause_names_no_member_vote_word_or_exception[text3] |
| 10a mover clause: member surname | killed | test_the_mover_clause_names_no_member_vote_word_or_exception[text2] |
| 10a mover clause: election exception | killed | test_each_shape_is_confirmed[text20-extra20-nays20-abstained20-CASE |
| 10a order: one second | killed | test_the_clauses_come_in_their_order_once[Mr. |
| 10a order: no vote after the outcome | killed | test_the_clauses_come_in_their_order_once[Motion |
| 10a order: one outcome | killed | test_the_clauses_come_in_their_order_once[Motion |
| 10a order: 'with' only after the outcome | killed | test_the_clauses_come_in_their_order_once[All |
| 10a an outcome clause is required | killed | test_an_outcome_inside_the_mover_clause_is_not_an_outcome_clause |
| 10c attribution: lead abstention attributed | killed | test_real_2024_10_29_motion_13_the_lead_abstention_is_attributed[Stacey |
| 10c attribution: own case only | killed | test_a_lead_abstention_on_another_case_is_not_attributed |
| 10c attribution: first motion only | killed | test_an_abstention_between_two_motions_of_one_case_is_attributed_to_neither |
| 10c attribution: case section only | killed | test_an_abstention_before_a_caseless_disposing_motion_is_not_attributed |
| 10c attribution: disposing motion only | killed | test_an_abstention_before_a_list_motion_under_a_case_is_not_attributed |
| 10c heading line is a sentence of its own | killed | test_real_2024_10_29_motion_13_the_lead_abstention_is_attributed[Stacey |
| 10c list scope: motionless case sections | killed | test_a_case_section_with_no_motion_is_a_list_motions_scope |
| 10d list part in the lead | killed | test_real_2026_06_23_motion_3_a_list_motion_with_one_case_abstention_is_not_confirmed |
| 10d body: own case is read | killed | test_real_2022_09_27_motion_16_an_abstention_on_its_own_case_is_read |
| 10d body: another listed case | killed | test_a_list_motion_abstention_on_another_listed_case_is_not_confirmed |
| 10d body: list-part member written nowhere | killed | test_a_list_motion_abstention_on_another_listed_case_is_not_confirmed |
| 10d body: another case on a caseless motion | killed | test_a_caseless_motion_abstention_naming_a_case_names_another_case |

**87 of 87 killed** (re-run at the delta review of 44a6ade's fix, which added fourteen rows: each KIND_STEMS stem, the
stems read for the two-kinds check, both KIND_NOUNS, a stem alone naming no kind, the deferrals list needing
"deferral", the four mover-negation checks and the CHECKED_THROUGH gate in collector/rpc_agenda.py. The 73 of 73
run at 89ca713, after the delta review of 92a0c69..24422eb, added eleven rows: the two-kinds check, the "Motion" label, both "recommend" rules, each KIND_HOLDS entry and the postpone and continue
polarities. The 62 of 62 run at 071cd2c, after the delta review of 33e13a2, added seven. The 55 of 55 run
after the review of d76f361 added six. A mutant that fails to import is reported BROKEN and never counted as killed.
One mutant from the 33e13a2 round, "polarity from the mover's words", survived: the words added nothing over the kind, so the code
was simplified to the kind and that mutant was dropped.)
