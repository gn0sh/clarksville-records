"""Minutes discovery from the county clerk's production page (real saved HTML, fetched 2026-11-07). No network."""
from collections import Counter
from pathlib import Path

import pytest

from collector import discover as D

FIX = Path(__file__).parent / "fixtures"
PROD = FIX / "minutes_index_production.html"     # https://montgomerytn.gov/clerk/county-commission-minutes


def test_index_is_the_production_page_not_the_dev_host():
    assert D.INDEX_URL == "https://montgomerytn.gov/clerk/county-commission-minutes"
    assert "dev2" not in D.INDEX_URL


def test_production_page_lists_minutes_2022_to_may_2026():
    found, skipped = D.discover(PROD.read_text(encoding="utf-8"))
    assert len(found) == 55 and skipped == []
    assert Counter(d["meeting_date"][:4] for d in found) == {"2022": 12, "2023": 12, "2024": 14, "2025": 12,
                                                            "2026": 5}
    assert found[0]["label"] == "January 2022 Minutes" and found[-1]["label"] == "May 2026 Minutes"
    assert all(d["url"].startswith("https://montgomeryminutes.bisonline.com/viewpdf.php?id=") for d in found)
    assert len({d["url"] for d in found}) == 55
    assert sorted(d["meeting_date"] for d in found if d["kind"] == "special") == ["2024-04-01", "2024-07-15"]


def test_label_dates_are_only_hints():
    """'December 2025 Minutes' gives a month, not a meeting: facts take the date from the document text."""
    found, _ = D.discover(PROD.read_text(encoding="utf-8"))
    dec = next(d for d in found if d["label"] == "December 2025 Minutes")
    assert dec["meeting_date"] == "2025-12"


def test_old_layout_fixture_still_parses():
    found, skipped = D.discover((FIX / "minutes_index.html").read_text())
    assert [(d["meeting_date"], d["kind"]) for d in found] == [
        ("2021-02", "formal"), ("2024-04-01", "special"), ("2024-04-08", "formal"), ("2024-12", "formal")]
    assert [s["label"] for s in skipped] == ["Minutes archive"]


def test_http_links_are_requested_by_https_on_the_same_host_only():
    assert D.https_same_host("http://montgomeryminutes.bisonline.com/viewpdf.php?id=x") == \
        "https://montgomeryminutes.bisonline.com/viewpdf.php?id=x"
    assert D.https_same_host("http://other.example/a") == "http://other.example/a"


@pytest.mark.parametrize("page", ["<html>moved</html>", ""])
def test_page_without_minutes_links_fails_loudly(page):
    with pytest.raises(D.DiscoveryError):
        D.discover(page)


def test_links_outside_the_years_fail_loudly():
    page = '<a href="https://montgomeryminutes.bisonline.com/viewpdf.php?id=a">May 2019 Minutes</a>'
    with pytest.raises(D.DiscoveryError):
        D.discover(page)


@pytest.mark.parametrize("status", [403, 404, 429])
def test_index_non_200_fails_loudly(status):
    class F:
        def get(self, url):
            assert url == D.INDEX_URL           # only the known index URL, never a guessed host
            return status, b"", {}
    with pytest.raises(D.DiscoveryError):
        D.fetch_index(F())
