"""Collector constants (provisional values recorded in the spec and architecture)."""

SKEW_FACTOR = 2.0            # G4: held rate > SKEW_FACTOR x max(peer median, SKEW_FLOOR) blocks release
SKEW_FLOOR = 0.02
MIN_ROLL_CALLS_FOR_SKEW = 50  # G4 (recalibrated 2026-11-07): only officials with at least this many roll calls
VERIFIED_RATE_MIN = 0.90     # AC-P1
BODY = "Montgomery County Commission"
YEARS = range(2020, 2025)
