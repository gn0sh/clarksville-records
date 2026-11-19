"""Daylight Digest national collector (docs/architecture/daylight-national.md 2, 3.7, 4.5 and section 11; M2).

`legistar_upcoming` (task C2) reads one covered Legistar body's coming meetings into a `daylight-upcoming/1` feed.
The run around it (budget order, health, proposals file, never failing the run on one body) is task C3 (`run.py`).
"""
