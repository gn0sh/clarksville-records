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
| 10a shape: seconded by M | killed | test_real_2024_10_29_motion_13_the_lead_abstention_is_attributed |
| 10a shape: the motion was seconded by M | killed | test_each_shape_is_confirmed[text1] |
| 10a shape: M seconded | killed | test_in_favor_and_the_motion_failed_is_one_outcome |
| 10a shape: M seconded it / the motion | killed | test_each_shape_is_confirmed[text5] |
| 10a shape: with M second | killed | test_each_shape_is_confirmed[text4] |
| 10a shape: [with a ]second from M | killed | test_each_shape_is_confirmed[text6] |
| 10a shape: M voted nay | killed | test_each_shape_is_confirmed[text7] |
| 10a shape: M abstained | killed | test_each_shape_is_confirmed[text8] |
| 10a shape: M abstained from <case> | killed | test_real_2022_09_27_motion_16_an_abstention_on_its_own_case_is_read |
| 10a shape: all ... in favor | killed | test_real_2022_09_27_motion_16_an_abstention_on_its_own_case_is_read |
| 10a shape: others in favor | killed | test_each_shape_is_confirmed[text13] |
| 10a shape: except M who ... | killed | test_each_shape_is_confirmed[text9] |
| 10a shape: but M who ... | killed | test_each_shape_is_confirmed[text10] |
| 10a shape: outcome | killed | test_in_favor_and_the_motion_failed_is_one_outcome |
| 10a shape: consent agenda passes with approval | killed | test_each_shape_is_confirmed[text14] |
| 10a shape: cases were approved for deferral | killed | test_each_shape_is_confirmed[text15] |
| 10a shape: meeting was adjourned at H:MM p.m. | killed | test_each_shape_is_confirmed[text19] |
| 10a shape: with M voting nay | killed | test_each_shape_is_confirmed[text16] |
| 10b tail trigger: OUTCOME | killed | test_an_outcome_in_favor_or_motion_after_the_outcome_is_not_confirmed |
| 10b tail trigger: FAVOUR | killed | test_an_outcome_in_favor_or_motion_after_the_outcome_is_not_confirmed |
| 10b tail trigger: motion | killed | test_a_pulled_consent_case_after_the_vote_is_not_confirmed |
| 10b tail trigger: moved | killed | test_a_second_motion_after_the_outcome_is_not_confirmed |
| 10b tail trigger: seconded | killed | test_a_second_motion_after_the_outcome_is_not_confirmed |
| outcome words: free text instead of the vocabulary | killed | test_an_outcome_holds_only_its_vocabulary |
| body runs to an outcome-shaped sentence | killed | test_an_outcome_holds_only_its_vocabulary |
| rule 9: a vote word after the 'in favor' sentence in the body | killed | test_a_vote_word_after_the_in_favor_sentence_drops_it_as_the_outcome |
| polarity: table / postpone / continue | killed | test_an_outcome_of_another_kind_of_motion_is_not_confirmed |
| polarity: a mover naming no kind passes | killed | test_an_outcome_naming_a_kind_the_mover_did_not_is_not_confirmed |
| polarity: an election or adjournment passing for approval | killed | test_an_election_or_adjournment_passing_for_approval_is_confirmed |
| kind: table | killed | test_real_2025_03_25_motion_9_tabling_the_case_stays_confirmed |
| kind: postpone | killed | test_a_mover_and_outcome_of_one_kind_are_confirmed |
| kind: continue | killed | test_a_mover_and_outcome_of_one_kind_are_confirmed |
| kind: table needs the verb | killed | test_table_and_continue_as_nouns_are_not_a_kind |
| 10a mover clause: lack of a second | killed | test_a_lack_of_a_second_in_the_mover_clause_is_not_confirmed |
| 10c MEMBER_VOTE: abstain | killed | test_a_member_vote_in_the_lead_is_not_confirmed |
| 10c MEMBER_VOTE: recus | killed | test_a_member_vote_in_the_lead_is_not_confirmed |
| 10c MEMBER_VOTE: conflict | killed | test_a_member_vote_in_the_lead_is_not_confirmed |
| 10c MEMBER_VOTE: refrain | killed | test_a_member_vote_in_the_lead_is_not_confirmed |
| 10c MEMBER_VOTE: `\bna[yv]s?\b` | killed | test_a_member_vote_in_the_lead_is_not_confirmed |
| 10c MEMBER_VOTE: `\bvot(?:e\|es\|ed\|ing)\b` | killed | test_a_member_vote_in_the_lead_is_not_confirmed |
| 10a mover clause: titled name | killed | test_the_mover_clause_holds_no_title_or_vote_word[text0] |
| 10a mover clause: vote word | killed | test_the_mover_clause_holds_no_title_or_vote_word[text1] |
| 10a mover clause: exception word | killed | test_the_mover_clause_names_no_member_vote_word_or_exception[text3] |
| 10a mover clause: member surname | killed | test_the_mover_clause_names_no_member_vote_word_or_exception[text2] |
| 10a mover clause: election exception | killed | test_each_shape_is_confirmed[text20] |
| 10a order: one second | killed | test_the_clauses_come_in_their_order_once |
| 10a order: no vote after the outcome | killed | test_the_clauses_come_in_their_order_once |
| 10a order: one outcome | killed | test_the_clauses_come_in_their_order_once |
| 10a order: 'with' only after the outcome | killed | test_the_clauses_come_in_their_order_once |
| 10a an outcome clause is required | killed | test_an_outcome_inside_the_mover_clause_is_not_an_outcome_clause |
| 10c attribution: lead abstention attributed | killed | test_real_2024_10_29_motion_13_the_lead_abstention_is_attributed |
| 10c attribution: own case only | killed | test_a_lead_abstention_on_another_case_is_not_attributed |
| 10c attribution: first motion only | killed | test_an_abstention_between_two_motions_of_one_case_is_attributed_to_neither |
| 10c attribution: case section only | killed | test_an_abstention_before_a_caseless_disposing_motion_is_not_attributed |
| 10c attribution: disposing motion only | killed | test_an_abstention_before_a_list_motion_under_a_case_is_not_attributed |
| 10c heading line is a sentence of its own | killed | test_real_2024_10_29_motion_13_the_lead_abstention_is_attributed |
| 10c list scope: motionless case sections | killed | test_a_case_section_with_no_motion_is_a_list_motions_scope |
| 10d list part in the lead | killed | test_real_2026_06_23_motion_3_a_list_motion_with_one_case_abstention_is_not_confirmed |
| 10d body: own case is read | killed | test_real_2022_09_27_motion_16_an_abstention_on_its_own_case_is_read |
| 10d body: another listed case | killed | test_a_list_motion_abstention_on_another_listed_case_is_not_confirmed |
| 10d body: list-part member written nowhere | killed | test_a_list_motion_abstention_on_another_listed_case_is_not_confirmed |
| 10d body: another case on a caseless motion | killed | test_a_caseless_motion_abstention_naming_a_case_names_another_case |

**62 of 62 killed** (re-run at 071cd2c, after the delta review of 33e13a2, which added seven rows above. The 55 of 55 run
after the review of d76f361 added six. A mutant that fails to import is reported BROKEN and never counted as killed.
One mutant from this round, "polarity from the mover's words", survived: the words added nothing over the kind, so the code
was simplified to the kind and that mutant was dropped.)
