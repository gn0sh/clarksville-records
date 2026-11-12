"""Collector constants (provisional values recorded in the spec and architecture)."""

SKEW_FACTOR = 2.0            # G4: held rate > SKEW_FACTOR x max(peer median, SKEW_FLOOR) blocks release
SKEW_FLOOR = 0.02
MIN_ROLL_CALLS_FOR_SKEW = 50  # G4 (recalibrated 2026-11-07): only officials with at least this many roll calls
VERIFIED_RATE_MIN = 0.90     # AC-P1
UNIFORM_SHARE_REVIEW = 0.25  # G4 "review needed" (not a fail) when more holds than this sit outside it
BODY = "Montgomery County Commission"
YEARS = range(2020, 2027)     # 2020-2021 from the M0 store; 2022 to May 2026 from the production page
# The comma-enclosed phrases the minutes print between an outcome word and "by the following roll call vote"
# ("was Adopted, as Amended, by"). Only these: an open phrase pattern can cross a clause boundary
# ("Approved, and the main motion, failed by ...", parse-accuracy/outcome-crosses-clause). Add a phrase here when a
# new one is seen on a page.
OUTCOME_COMMA_PHRASES = ("as amended", "in its original state")
# AC-F16 coverage parity (architecture A5, provisional): a department with at least FIN_PARITY_MIN_ROWS archive rows
# whose bid-tab read share is outside FIN_PARITY_LOW x .. FIN_PARITY_HIGH x the overall share is flagged; a flag sets
# "review needed", which blocks release until the manager records the reason in docs/status.md.
FIN_PARITY_MIN_ROWS = 5
FIN_PARITY_LOW = 0.5
FIN_PARITY_HIGH = 2.0
