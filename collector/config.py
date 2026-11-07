"""Collector constants (provisional values recorded in the spec and architecture)."""

SKEW_FACTOR = 2.0            # G4: held rate > SKEW_FACTOR x max(peer median, SKEW_FLOOR) blocks release
SKEW_FLOOR = 0.02
MIN_ROLL_CALLS_FOR_SKEW = 50  # G4 (recalibrated 2026-11-07): only officials with at least this many roll calls
VERIFIED_RATE_MIN = 0.90     # AC-P1
UNIFORM_SHARE_REVIEW = 0.25  # G4 "review needed" (not a fail) when more holds than this sit outside it
BODY = "Montgomery County Commission"
YEARS = range(2020, 2027)     # 2020-2021 from the M0 store; 2022 to May 2026 from the production page
