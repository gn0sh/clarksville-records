"""Legistar adapter proof of concept (collector/legistar.py) against synthetic fixtures; no network."""
import json
from datetime import date
from pathlib import Path

import pytest

from collector import legistar

FIX = Path(__file__).parent / "fixtures" / "legistar"
PACK = Path(__file__).resolve().parents[2] / "config" / "cities" / "salem-or" / "legistar.yml"


@pytest.fixture
def cfg():
    return legistar.load_config(PACK)


def test_city_pack_loads(cfg):
    assert cfg["client"] == "salem" and cfg["launch_days"] == 365
    assert legistar.allowed_hosts(cfg)[:2] == ("webapi.legistar.com", "salem.legistar.com")


def test_bad_pack_fails_loudly(tmp_path):
    p = tmp_path / "legistar.yml"
    p.write_text("city: x\nclient: Bad Name\n")
    with pytest.raises(legistar.ConfigError, match="missing"):
        legistar.load_config(p)


def test_unknown_vote_value_in_pack_is_refused(tmp_path):
    text = PACK.read_text().replace('"Aye": "yes"', '"Aye": "maybe"')
    p = tmp_path / "legistar.yml"
    p.write_text(text)
    with pytest.raises(legistar.ConfigError, match="vote_values"):
        legistar.load_config(p)


def test_launch_year_first_then_one_year_back_at_a_time():
    ws = legistar.launch_windows(date(2026, 11, 15), 365, date(2024, 6, 1))
    assert ws[0] == legistar.Window(date(2025, 11, 16), date(2026, 11, 16))
    assert ws[1] == legistar.Window(date(2024, 11, 16), date(2025, 11, 16))
    assert ws[-1].start == date(2024, 6, 1)
    assert all(a.start == b.end for a, b in zip(ws, ws[1:]))      # no gap, no overlap


def test_events_url_filters_one_body_and_window(cfg):
    url = legistar.events_url(cfg, legistar.Window(date(2025, 11, 16), date(2026, 11, 16)))
    assert url.startswith("https://webapi.legistar.com/v1/salem/events?")
    assert "EventBodyName%20eq%20%27City%20Council%27" in url
    assert "datetime%272025-11-16%27" in url and "datetime%272026-11-16%27" in url


def test_listing_rows_keep_one_body_and_only_https_links(cfg):
    rows = legistar.listing_rows(cfg, json.loads((FIX / "events.json").read_text()))
    assert [r["event_id"] for r in rows] == [101, 102]            # other body and bad date skipped
    first, second = rows
    assert first["kind"] == "regular" and first["minutes_url"].endswith("m101.pdf")
    assert second["kind"] == "work-session" and second["video_url"] is None   # bare path not guessed
    assert set(first) >= {"date", "title", "kind", "agenda_id", "agenda_url", "minutes_url", "source"}


def test_vote_rows_keep_raw_label_and_never_guess(cfg):
    rows = legistar.vote_rows(cfg, json.loads((FIX / "votes.json").read_text()))
    assert [(r["raw_name"], r["value"], r["raw_value"]) for r in rows] == [
        ("Member One", "yes", "Aye"), ("Member Two", "no", "Nay"),
        ("Member Three", "other", "Absent"), ("Member Four", "other", "Present")]
    assert all(r["official_id"] is None for r in rows)


def test_roll_call_items_only():
    items = [{"EventItemId": 1, "EventItemRollCallFlag": 1}, {"EventItemId": 2, "EventItemRollCallFlag": 0}]
    assert [i["EventItemId"] for i in legistar.roll_call_items(items)] == [1]
