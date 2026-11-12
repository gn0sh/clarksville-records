"""alerting/city-fetch-failures-exit-0: `collector city fetch|run` must end non-zero, with its own code, when a host or
policy refuses the collector, so the workflow's `[ "$city" = 0 ]` gate fails and the issue opens (spec AC4.4: never a
silent gap). A refusal is reported, never retried and never worked around."""
import json

import pytest

from collector import city_run, civicclerk
from collector.fetch import FetchFailed, HostBlocked, HostRefused, ProxyRefused, RobotsDisallowed


class Fetcher:
    log = []


def rows(n=1):
    return [{"date": f"2026-11-{5 + i:02d}", "title": "Regular Session", "kind": "regular",
             "minutes_url": f"https://x.test/m{i}.pdf", "agenda_url": None} for i in range(n)]


@pytest.fixture
def city(tmp_path, monkeypatch):
    """`collector city fetch` with the listings and the file fetch faked; nothing touches the network or data/."""
    d = tmp_path / "data"
    monkeypatch.setattr(city_run, "paths", lambda cfg, root=None: {
        "dir": d, "listing": d / "listing.json", "manifest": d / "manifest.json", "facts": d / "facts.json",
        "wards": d / "wards.json", "cc_listing": d / "cc.json", "report": tmp_path / "city-report.json"})
    state = {"rows": rows(), "raise": None, "calls": [], "listing_raise": None}
    monkeypatch.setattr(city_run, "PoliteFetcher", Fetcher)

    def discover(f, cfg, log, previous):
        if state["listing_raise"]:
            raise state["listing_raise"]
        return state["rows"]
    monkeypatch.setattr(city_run, "discover", discover)
    monkeypatch.setattr(civicclerk, "discover", lambda f, cc, kind_of, log, cache: [])

    def fetch(f, store, url, meta):
        state["calls"].append(url)
        if state["raise"]:
            raise state["raise"]
        return {}, "unchanged"
    monkeypatch.setattr(city_run, "fetch_into_store", fetch)
    state["report"] = lambda: json.loads((tmp_path / "city-report.json").read_text())
    return state


@pytest.mark.parametrize("error", [
    HostBlocked("x.test answered 429: stopped for this run"), HostBlocked("x.test answered 403"),
    HostRefused("x.test: not on the allowlist"), ProxyRefused("x.test: proxy refused"),
    RobotsDisallowed("https://x.test/m0.pdf")])
def test_a_refusal_while_fetching_files_exits_with_the_blocked_code(city, capsys, error):
    city["raise"] = error
    code = city_run.main(["fetch"])
    assert code == city_run.BLOCKED == 5
    assert code not in (0, 2, 3, 4)                           # its own code: not ok, listing, gate or offline refusal
    failures = city["report"]()["fetch"]["failures"]
    assert failures and all(f["stage"] == "fetch" and f["refused"] is True for f in failures)
    assert "REFUSED" in capsys.readouterr().err


def test_a_block_stops_the_host_for_the_run_and_is_not_retried(city):
    """Never work around a block: after the 429 no other file of that listing is requested, and none twice."""
    city["rows"] = rows(4)
    city["raise"] = HostBlocked("x.test answered 429: stopped for this run")
    assert city_run.main(["fetch"]) == city_run.BLOCKED
    assert city["calls"] == ["https://x.test/m0.pdf"]
    assert city["report"]()["fetch"]["fetched"] == {"not_tried": 3}


def test_a_blocked_listing_exits_with_the_blocked_code(city):
    city["listing_raise"] = HostBlocked("x.test answered 403")
    assert city_run.main(["fetch", "--source", "agenda-center"]) == city_run.BLOCKED
    assert city["calls"] == []


def test_an_unreadable_listing_still_exits_2(city):
    city["listing_raise"] = city_run.ListingError("the page has no meeting table")
    assert city_run.main(["fetch", "--source", "agenda-center"]) == city_run.LISTING_FAILED == 2


def test_one_skipped_file_is_logged_and_stays_exit_0(city):
    """Unchanged on purpose: a single bad file (a .docx behind a PDF link) is skipped, the rest are still fetched."""
    city["rows"] = rows(2)
    city["raise"] = FetchFailed("https://x.test/m0.pdf: not a PDF")
    assert city_run.main(["fetch"]) == 0
    assert len(city["calls"]) == 2
    assert not any(f.get("refused") for f in city["report"]()["fetch"]["failures"])


def test_a_clean_fetch_exits_0(city):
    assert city_run.main(["fetch"]) == 0 and city["report"]()["fetch"]["failures"] == []


def _gates(flagged):
    return {"roll_calls": 10, "verified": 7, "verified_rate": 0.7, "verified_rate_gate": {"min": 0.9, "pass": False},
            "g4": {"status": "fail" if flagged else "pass", "flagged": flagged, "pass": not flagged,
                   "uniform_share": 0.0}}


@pytest.mark.parametrize("flagged, code", [(["city-a-b"], 3), ([], 0)])
def test_the_g4_skew_gate_fails_the_city_build_and_the_verified_rate_only_reports(city, monkeypatch, capsys,
                                                                                  flagged, code):
    """city-verify/no-skew-gate: spec G4 blocks a release when an official is skewed, so a flag is the county's gate
    code 3 (any non-zero code fails the workflow's Collect step); a verified rate under 90% is reported, no code."""
    from collector import city_build
    monkeypatch.setattr(city_build, "build", lambda cfg, rows, store: (
        {"_wards": []}, {"gates": _gates(flagged), "pass": False}))
    assert city_run.main(["build"]) == code == (city_run.GATE_FAILED if flagged else 0)
    out = capsys.readouterr()
    assert "AC-P1 FAIL" in out.out and ("G4 skew gate FAILED" in out.err) == bool(flagged)
    assert city["report"]()["build"]["gates"]["g4"]["flagged"] == flagged
