"""Minutes discovery from the county index page (saved fixture). No network."""
from pathlib import Path

import pytest

from collector import discover as D

FIX = Path(__file__).parent / "fixtures" / "minutes_index.html"


def test_lists_2020_2024_minutes_with_date_and_kind():
    found, skipped = D.discover(FIX.read_text())
    assert [(d["meeting_date"], d["kind"]) for d in found] == [
        ("2021-02", "formal"), ("2024-04-01", "special"), ("2024-04-08", "formal"), ("2024-12", "formal")]
    assert all(d["url"].startswith("https://montgomeryminutes.bisonline.com/viewpdf.php?id=") for d in found)
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


def test_index_non_200_fails_loudly():
    class F:
        def get(self, url):
            assert url == D.INDEX_URL           # only the known index URL, never a guessed host
            return 404, b"", {}
    with pytest.raises(D.DiscoveryError):
        D.fetch_index(F())
