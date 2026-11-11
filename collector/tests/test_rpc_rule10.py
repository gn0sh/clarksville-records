"""RPC motion invariant rule 10 (docs/architecture/rpc-motion-invariant.md, `rpc-votes` hits 1-4): the motion's body
is an allowlist of sentence shapes (10a); after its outcome no outcome, "in favor" or motion (10b); before it, and for
a list motion in every case section with no motion of its own, no member's vote that is not attributed (10c); an
abstention naming a case belongs to that case only (10d). Sentences are the minutes' own (motion ids name them) or the
review's and QA's probes; each test pins the confirmed flag, the reason, and the nays and abstainers read."""
import pytest

from collector import rpc, rpc_minutes as R

PREFIXES = set(rpc.load_config().case_types)
MEMBERS = ("Wade Hadley", "Bryce Powers", "Stacey Streetman", "Bill Kimbrough", "Michael Long")
M = "Mr. Hadley made the motion for approval. Mr. Powers seconded. "
Z5 = "CASE NUMBER: Z-5-2026\n"


def read(text: str, extra=(), agenda=("Z-5-2026",), head: str = Z5) -> list[R.Motion]:
    """The probe's page (scratchpad probe.py `one()`): a members header, then `head` and `text`."""
    page = ("Members Present          Others Present\n" + "\n".join(MEMBERS + tuple(extra))
            + "\nMeeting was called to order.\n" + head + text)
    return R.read_minutes([page], set(agenda), PREFIXES).motions


def one(text: str, **kw) -> R.Motion:
    ms = read(text, **kw)
    assert len(ms) == 1, [m.para for m in ms]
    return ms[0]


def held(m: R.Motion, reason: str, nays=(), abstained=()):
    assert not m.confirmed and reason in m.reasons, m.reasons
    assert (m.nays, m.abstained) == (list(nays), list(abstained))


def ok(m: R.Motion, nays=(), abstained=()):
    assert m.confirmed, m.reasons
    assert (m.nays, m.abstained) == (list(nays), list(abstained))


# ------------------------------------------------------------------ 10a: not confirmed, a sentence the reader does not know
@pytest.mark.parametrize("votes", [
    # review #1: an exception printed after the outcome, or as "excepted"
    "All others voted in favor and the motion passed with the exception of Mr. Long.",
    "All others voted in favor. Motion passed with the exception of Mr. Long.",
    "All members voted in favor and the motion passed, Mr. Long excepted.",
    # review #2: the rest of an "in favor" sentence that no denylist word names
    "All members voted in favor, minus one.",
    "All members voted in favor, apart from one member.",
    "All members voted in favor, other than one.",
    "All members voted in favor, but one.",
    "All members voted in favor, except one.",
    "All members present voted in favor, with one member not voting.",
    "All voted in favor, 6-1.",
    "All members voted in favor, while Mr. Long was absent.",
    "All members voted in favor; Long was absent.",
    "All members voted in favor and the motion passed for a 30 day deferral, 5 to 1.",
    "All members voted in favor and the motion passed for a 30 day deferral 5 1.",
    "All members voted in favor and the motion passed for a 30 day deferral to the 4-1 meeting.",
    # consent wording
    "Motion was approved on the consent agenda, Mr. Long abstaining.",
    "Motion was approved on the consent agenda except for Mr. Long.",
    "Motion was approved on the consent agenda with Mr. Long recused.",
    "The case was removed from the consent agenda. Motion was approved on the consent agenda.",
])
def test_a_vote_sentence_outside_the_shapes_is_not_confirmed(votes):
    held(one(M + votes), R.WHY_UNLISTED)


def test_real_2022_03_29_motion_10_with_the_exception_of_is_not_confirmed():
    """2022-03-29-regular-motion-10 was confirmed with no nay and no abstainer: Mr. Powers' vote is not stated."""
    m = one("Mr. Rocconi made the motion for disapproval. The motion was seconded by Mrs. Streetman. All were in favor "
            "with the exception of Mr. Powers. Motion for disapproval passed.", extra=("Larry Rocconi",))
    held(m, R.WHY_UNLISTED)
    assert (m.mover_member, m.seconder_member) == ("Larry Rocconi", "Stacey Streetman")


def test_a_pulled_consent_case_after_the_vote_is_not_confirmed():
    m = one(M + "All members were in favor. Motion was approved on the consent agenda pulled by Mr. Long for separate "
                "vote.")
    held(m, R.WHY_TAIL_OUTCOME)
    assert m.outcome is None and R.WHY_FAVOUR_NOT_OUTCOME in m.reasons


def test_a_unanimous_outcome_with_a_tally_is_checked_against_the_nays():
    m = one(M + "All members were in favor and the motion passed unanimously 4-1.")
    held(m, "the printed tally does not match the members named as voting nay")


@pytest.mark.parametrize("text", [
    "Mr. Hadley made the motion for approval stating Mr. Long agreed. Mr. Powers seconded. All others were in favor. "
    "Motion passed.",
    "Mr. Hadley made the motion for approval with Mr. Long voting against. Mr. Powers seconded. All others were in "
    "favor. Motion passed.",
    "Mr. Hadley made the motion for approval stating Long agreed. Mr. Powers seconded. All others were in favor. "
    "Motion passed.",
    "Mr. Hadley made the motion for approval except as to lot 4. Mr. Powers seconded. All others were in favor. "
    "Motion passed.",
])
def test_the_mover_clause_names_no_member_vote_word_or_exception(text):
    held(one(text), R.WHY_UNLISTED)


# ------------------------------------------------------------------ 10b: after the outcome
@pytest.mark.parametrize("tail", [
    "Staff then presented the next case about the road widening plan. The motion failed.",      # review #3
    "Staff then presented the next case. Consent agenda passed.",                               # an outcome only
    "Staff then presented the plan. All others were in favor.",                                 # "in favor" only
    "Mr. Long asked about the motion.",                                                         # a motion only
])
def test_an_outcome_in_favor_or_motion_after_the_outcome_is_not_confirmed(tail):
    held(one(M + "All members voted in favor. Motion passed. " + tail), R.WHY_TAIL_OUTCOME)


def test_review_3_the_far_outcome_is_not_the_outcome():
    m = one(M + "All members voted in favor. Staff then presented the next case about the road widening plan. The "
                "motion failed.")
    held(m, R.WHY_TAIL_OUTCOME)


def test_a_reconsideration_after_the_outcome_is_not_confirmed():
    held(one(M + "All others were in favor. Motion passed. Mr. Long asked to reconsider the motion."), R.WHY_TAIL_OUTCOME)


def test_in_favor_and_the_motion_failed_is_one_outcome():
    m = one(M + "All others were in favor and the motion failed.")
    ok(m)
    assert m.outcome == "the motion failed"


def test_words_after_the_outcome_with_no_vote_stay_confirmed():
    ok(one(M + "All others were in favor and the motion passed. Mr. Long left the meeting."))


# ------------------------------------------------------------------ 10c: before the motion (`abstain-before-motion`)
@pytest.mark.parametrize("lead", ["Mr. Long voted nay.", "Mr. Long recused himself.",
                                  "Mrs. Streetman declared a conflict of interest.", "Mr. Long did not vote.",
                                  "Nays: Mr. Long.", "Mr. Long refrained.", "Mr. Long wished to abstain on the record.",
                                  "Mr. Long abstained from Z-5-2026 because of a conflict."])
def test_a_member_vote_in_the_lead_is_not_confirmed(lead):
    held(one(lead + " " + M + "All others were in favor. Motion passed."), R.WHY_LEAD_VOTE)


@pytest.mark.parametrize("lead", ["Mrs. Streetman stated she has no conflict of interest.",       # 2025-06-24-23
                                  "Mr. Powers noted the Commission is not voting on the cell tower."])  # 2022-05-24-22
def test_negative_controls_cost_a_confirmation_and_read_no_vote(lead):
    held(one(lead + " " + M + "All others were in favor. Motion passed."), R.WHY_LEAD_VOTE)


def test_an_abstention_before_the_first_case_is_attributed_to_nothing():
    m = one("Mr. Long abstained. Mr. Hadley made a motion to approve the minutes. Mr. Powers seconded. Motion passed.\n"
            + Z5, head="")
    held(m, R.WHY_LEAD_VOTE)


def test_an_abstention_before_a_caseless_disposing_motion_is_not_attributed():
    m = one("Mr. Long abstained. Mr. Hadley made the motion for approval. Mr. Powers seconded. Motion passed.\n" + Z5,
            head="")
    held(m, R.WHY_LEAD_VOTE)
    assert R.WHY_SUBJECT in m.reasons


def test_an_abstention_between_two_motions_of_one_case_is_attributed_to_neither():
    first, second = read(M + "Motion passed. Mr. Long abstained. Mrs. Streetman made the motion to defer. "
                             "Mr. Kimbrough seconded. Motion passed.")
    held(second, R.WHY_LEAD_VOTE)
    assert R.WHY_TWO in second.reasons and R.WHY_TWO in first.reasons
    assert first.abstained == [] and not first.confirmed


def test_an_abstention_before_a_list_motion_under_a_case_is_not_attributed():
    m = one("Mr. Powers abstained from S-81-2022. Mr. Spigner made the motion for approval of consent agenda. "
            "Mrs. Streetman seconded. All were in favor and motion passed.", extra=("Thom Spigner",),
            agenda=("S-81-2022",), head="CASE NUMBER: S-81-2022\n")
    assert m.kind == "Motion to approve the consent agenda"
    held(m, R.WHY_LEAD_VOTE)


def test_a_case_section_with_no_motion_is_a_list_motions_scope():
    m = one("Mr. Hadley made a motion to approve the consent agenda. Mr. Powers seconded. Motion passed.\n"
            "CASE NUMBER: Z-5-2026\nMr. Long abstained.\n", head="")
    held(m, R.WHY_LEAD_VOTE)


def test_a_case_section_with_no_motion_is_no_other_motions_scope():
    m = one("Mr. Hadley made a motion to approve the minutes. Mr. Powers seconded. Motion passed.\n"
            "CASE NUMBER: Z-5-2026\nMr. Long abstained.\n", head="")
    ok(m)


@pytest.mark.parametrize("lead", ["Russell Harris spoke against stating concerns such as traffic.",
                                  "The proposed C-5 zoning can negatively affect the area.",
                                  "No one spoke in opposition.", "Chairman Swift asked for a motion."])
def test_lead_prose_with_no_member_vote_stays_confirmed(lead):
    ok(one(lead + " " + M + "All others were in favor. Motion passed."))


# ------------------------------------------------------------------ 10d: an abstention naming a case
CONSENT_2026_06_23 = ("Joe Smith made a motion to approve the consent agenda, seconded by Stacey Streetman. All members "
                      "voted in favor. Motion passes for approval.")


def test_real_2026_06_23_motion_3_a_list_motion_with_one_case_abstention_is_not_confirmed():
    m = one("Cindy Greene abstained from SR-42-2026. " + CONSENT_2026_06_23 + "\n" + Z5, head="",
            extra=("Cindy Greene", "Joe Smith"), agenda=("Z-5-2026", "SR-42-2026"))
    held(m, R.WHY_LIST_PART)
    assert R.WHY_LEAD_VOTE not in m.reasons


def test_a_list_motion_abstention_on_a_case_off_the_agenda_is_a_lead_doubt():
    m = one("Cindy Greene abstained from SR-42-2026. " + CONSENT_2026_06_23 + "\n" + Z5, head="",
            extra=("Cindy Greene", "Joe Smith"))
    held(m, R.WHY_LEAD_VOTE)
    assert R.WHY_LIST_PART not in m.reasons


SPIGNER = ("Mr. Spigner made the motion for approval of consent agenda. Mrs. Streetman seconded. Mr. Powers abstained "
           "from {case}. All were in favor and motion passed.")


def test_real_2022_09_27_motion_16_an_abstention_on_its_own_case_is_read():
    m = one(SPIGNER.format(case="S-81-2022"), extra=("Thom Spigner",), agenda=("S-81-2022",),
            head="CASE NUMBER: S-81-2022\n")
    ok(m, abstained=["Mr. Powers"])


def test_a_list_motion_abstention_on_another_listed_case_is_not_confirmed():
    m = one(SPIGNER.format(case="S-79-2022"), extra=("Thom Spigner",), agenda=("S-81-2022", "S-79-2022"),
            head="CASE NUMBER: S-81-2022\n")
    held(m, R.WHY_LIST_PART)
    assert R.WHY_OTHER_CASE not in m.reasons


def test_a_list_motion_abstention_on_a_case_off_the_agenda_names_another_case():
    m = one(SPIGNER.format(case="S-99-2022"), extra=("Thom Spigner",), agenda=("S-81-2022",),
            head="CASE NUMBER: S-81-2022\n")
    held(m, R.WHY_OTHER_CASE, abstained=["Mr. Powers"])
    assert R.WHY_LIST_PART not in m.reasons


def test_a_caseless_motion_abstention_naming_a_case_names_another_case():
    m = one("Mr. Hadley made a motion to approve the minutes. Mr. Powers seconded. Mr. Long abstained from Z-9-2026. "
            "Motion passed.\n" + Z5, head="")
    held(m, R.WHY_OTHER_CASE, abstained=["Mr. Long"])


@pytest.mark.parametrize("lead", ["Stacey Streetman abstained from voting.", "Stacey Streetman abstained from S-73-2024."])
def test_real_2024_10_29_motion_13_the_lead_abstention_is_attributed(lead):
    m = one(lead + " Bill Kimbrough made a motion for approval, seconded by Jeff Henley. All others voted in favor. "
            "Motion was approved on consent agenda.", extra=("Jeff Henley",), agenda=("S-73-2024",),
            head="CASE NUMBER: S-73-2024\n")
    ok(m, abstained=["Stacey Streetman"])
    assert m.outcome == "Motion was approved on consent agenda"


def test_an_attributed_abstainer_meets_the_body_checks():
    m = one("Mr. Hadley abstained. " + M + "All others were in favor. Motion passed.")
    held(m, R.WHY_NAY_IS_MOVER, abstained=["Mr. Hadley"])
    m = one("Mr. Hadley abstained. " + M + "All others were in favor.")            # rule 9: no outcome as printed
    held(m, R.WHY_FAVOUR_NOT_OUTCOME, abstained=["Mr. Hadley"])


# ------------------------------------------------------------------ one test per shape, each from a real para
@pytest.mark.parametrize("text,extra,nays,abstained,head", [
    (M + "All others were in favor. Motion passed.", (), [], [], Z5),                     # M seconded
    ("Mr. Hadley made the motion for approval. Motion was seconded by Mrs. Jiminez. All others were in favor. "
     "Motion passed.", ("Maria Jiminez",), [], [], Z5),                                     # the motion was seconded by
    ("Bill Kimbrough made a motion for approval, seconded by Jeff Henley. All others voted in favor. Motion passed.",
     ("Jeff Henley",), [], [], Z5),                                                         # , seconded by M
    ("Marcia Williams made a motion to approve. Seconded by David Smith. All members voted in favor. Motion passes "
     "for approval.", ("Marcia Williams", "David Smith"), [], [], Z5),                     # Seconded by M (cdrb)
    ("Mr. Hadley made the motion for approval with Mrs. Streetman second. All others were in favor. Motion passed.",
     (), [], [], Z5),                                                                       # with M second
    ("Bill Kimbrough made a motion for approval. Stacey Streetman seconded it. All others voted in favor and motion "
     "was passed.", (), [], [], Z5),                                                        # 2024-10-29-regular-motion-8
    ("Mr. Hadley made the motion for approval with a second from Mr. Powers. All were in favor and the motion passed.",
     (), [], [], Z5),                                                                       # second from M
    (M + "Mrs. Streetman voted nay. All others were in favor. Motion passed.", (), ["Mrs. Streetman"], [], Z5),
    ("Mrs. Streetman made the motion for approval. Mr. Rocconi seconded. Mr. Powers abstained and all others were in "
     "favor. Motion passed.", ("Larry Rocconi",), [], ["Mr. Powers"], Z5),
    ("Charlie Patterson made a motion for approval, seconded by Stacey Streetman. All members voted in favor, except "
     "Cindy Greene who abstained and Bill Kimbrough who voted against. Motion passes for approval 4-1.",
     ("Charlie Patterson", "Cindy Greene"), ["Bill Kimbrough"], ["Cindy Greene"], Z5),
    ("Stacey Streetman made a motion for approval. Seconded by Cindy Greene. All members voted in favor, but Michael "
     "Long who was against. Motion passes for approval 4-1.", ("Cindy Greene",), ["Michael Long"], [], Z5),
    ("Marcia Williams made a motion to approve. Seconded by David Smith. All members voted in favor, but Bert "
     "Singletary who abstained. Motion passes for approval.", ("Marcia Williams", "David Smith", "Bert Singletary"),
     [], ["Bert Singletary"], Z5),                                                          # 2026-07-27-cdrb-motion-7
    (M + "All were in favor and motion passed.", (), [], [], Z5),
    (M + "Mrs. Streetman voted nay, others in favor. Motion passed.", (), ["Mrs. Streetman"], [], Z5),
    ("Eric Huneycutt made a motion to approve the consent agenda, seconded by Stacey Streetman. All others voted in "
     "favor, consent agenda passes with approval.\n" + Z5, ("Eric Huneycutt",), [], [], ""),
    ("Bill Kimbrough made a motion to approve deferrals, seconded by Stacey Streetman. All voted in favor, cases were "
     "approved for deferral.\n" + Z5, (), [], [], ""),                                      # 2025-02-25-regular-motion-2
    ("Ms. Streetman made the motion for disapproval stating that the proposed zoning request is inconsistent with the "
     "adopted Land Use Plan. Mr. Huneycutt seconded. Motion for disapproval passed 4-2 with Mr. Kimbrough and Mr. Long "
     "voting nay.", ("Eric Huneycutt",), ["Mr. Kimbrough", "Mr. Long"], [], Z5),           # 2023-08-29-regular-motion-4
    ("Bill Kimbrough made a motion for a 30 day deferral, seconded by Stacey Streetman. All others voted in favor and "
     "the motion passed for a 30 day deferral.", (), [], [], Z5),                         # 2024-09-24-regular-motion-4
    ("Charlie Patterson made a motion to approve the minutes from 9/24/2024 meeting, seconded by Michael Long. All "
     "others voted in favor. Minutes were approved.\n" + Z5, ("Charlie Patterson",), [], [], ""),
    ("Bill Kimbrough made a motion to adjourn, seconded by Michael Long. All members voted in favor, meeting was "
     "adjourned at 4:48 p.m.", (), [], [], Z5),
    ("Mr. Kimbrough made the motion to nominate Mr. Swift as Chairman for 2024. Mr. Long seconded. All others were in "
     "favor. Motion passed.", ("Richard Swift",), [], [], Z5),                              # election
    ("Mr. Hadley made the motion for approval stating it is consistent with the adopted Land Use Plan. Mr. Powers "
     "seconded. All others were in favor. Motion passed.", (), [], [], Z5),                 # reason clause
])
def test_each_shape_is_confirmed(text, extra, nays, abstained, head):
    ok(one(text, extra=extra, head=head), nays=nays, abstained=abstained)


# ------------------------------------------------------------------ pins found by the mutation run
@pytest.mark.parametrize("text", [
    # a titled name that is no member (real 2024: "made a motion to endorse Mr. Tyndall's plan")
    "Mr. Hadley made a motion to endorse Mr. Tyndall's plan. Mr. Powers seconded. All others were in favor. Motion "
    "passed.",
    # a vote word with no name in the mover clause
    "Mr. Hadley made the motion for approval with one vote against. Mr. Powers seconded. All others were in favor. "
    "Motion passed.",
])
def test_the_mover_clause_holds_no_title_or_vote_word(text):
    held(one(text), R.WHY_UNLISTED)


@pytest.mark.parametrize("votes,nays", [
    ("Mr. Long seconded. All others were in favor. Motion passed.", []),           # a second second
    ("Motion passed, Mrs. Streetman voted nay.", ["Mrs. Streetman"]),              # a vote after the outcome
    ("Motion passed, motion carried.", []),                                         # a second outcome
    ("All others were in favor with Mr. Long voting nay. Motion passed.", ["Mr. Long"]),   # "with" before the outcome
])
def test_the_clauses_come_in_their_order_once(votes, nays):
    held(one(M + votes), R.WHY_UNLISTED, nays=nays)


def test_an_outcome_inside_the_mover_clause_is_not_an_outcome_clause():
    m = one("Mr. Hadley moved approval and the motion carried.")
    held(m, R.WHY_UNLISTED)


def test_a_lead_abstention_on_another_case_is_not_attributed():
    m = one("Mr. Long abstained from Z-9-2026. " + M + "All others were in favor. Motion passed.",
            agenda=("Z-5-2026", "Z-9-2026"))
    held(m, R.WHY_LEAD_VOTE)


# ------------------------------------------------------------------ review of d76f361
# rpc-votes/outcome-words-swallow: an outcome's words are a fixed vocabulary, so no vote word hides inside one
@pytest.mark.parametrize("votes", [
    "All others voted in favor. Motion passed for approval but Long voted nay.",
    "All others voted in favor. Motion passed for approval except one.",
    "All others voted in favor. Motion passed for approval minus one nay vote.",
    "Motion for approval with Long abstaining passed.",
    "All members voted in favor. Motion passed for approval and one member abstaining.",
    "All others were in favor. The motion passed for approval over the objection of Long.",
    "All others were in favor. Motion passed for approval of the request Long dissenting.",
    "All others were in favor. Motion passes for approval to the planning department staff except long.",
])
def test_an_outcome_holds_only_its_vocabulary(votes):
    m = one(M + votes)
    held(m, R.WHY_UNLISTED)
    assert m.outcome is None or R.FAVOUR.fullmatch(m.outcome), m.outcome      # never the unread sentence


@pytest.mark.parametrize("words", ["approval", "disapproval", "denial", "a one month deferral", "a 30 day deferral",
                                   "a thirty-day deferral", "approval of consent agenda", "approval of variances"])
def test_the_outcome_vocabulary_is_read(words):
    m = one(M + f"All others were in favor. Motion passed for {words}.")
    assert m.outcome == f"Motion passed for {words}", (m.outcome, m.reasons)


# rpc-votes/tail-second-motion: a second motion after the outcome
@pytest.mark.parametrize("tail", ["Mrs. Streetman then moved to deny, seconded by Mr. Long.",
                                  "Mrs. Streetman then moved to deny.", "Mr. Long had seconded it as well."])
def test_a_second_motion_after_the_outcome_is_not_confirmed(tail):
    held(one(M + "All others were in favor. Motion passed. " + tail), R.WHY_TAIL_OUTCOME)


# rpc-votes/outcome-other-motion: an outcome naming a motion to table, postpone or continue
@pytest.mark.parametrize("votes", ["All members present voted in favor. Motion to table passed.",
                                   "Motion to table the request carried.", "Motion to postpone passed.",
                                   "Motion to continue passed."])
def test_an_outcome_of_another_kind_of_motion_is_not_confirmed(votes):
    held(one(M + votes), "the outcome names another kind of motion")


def test_real_2025_03_25_motion_9_tabling_the_case_stays_confirmed():
    m = one("Joe Smith made a motion to table the case, seconded by Stacey Streetman. All others voted in favor, "
            "motion passes to table the case indefinitely.", extra=("Joe Smith",))
    ok(m)
    assert (m.kind, m.outcome) == ("Motion", "motion passes to table the case indefinitely")


def test_a_vote_word_after_the_in_favor_sentence_drops_it_as_the_outcome():
    """rule 9 with the body running to the unread outcome sentence: the 'in favor' sentence is never stored."""
    m = one(M + "All others voted in favor. Motion passed for approval but Long voted nay.")
    held(m, R.WHY_FAVOUR_NOT_OUTCOME)
    assert m.outcome is None
