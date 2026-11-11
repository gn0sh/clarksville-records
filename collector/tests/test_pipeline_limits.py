"""docs/architecture/pipeline-limits-invariant.md: every limit sits above the largest real input with margin, and a
limit trip is reported."""
import pytest

from collector import fetch, minutes
from collector.store import Store
from collector.tests.test_fetch import make


# ------------------------------------------------------------------ margins (L7, L16)

def test_fetch_stores_the_largest_real_file_and_refuses_one_over_the_cap(tmp_path):
    """L16: the 2021-10-28 city agenda is 52,041,095 B (the old 50 MiB cap refused it)."""
    big = b"%PDF-1.7\n" + b"x" * (52_041_095 - 9)
    f, _, _ = make({"https://h.example/a.pdf": (200, big)})
    status, body, headers = f.get("https://h.example/a.pdf")
    assert status == 200 and len(body) == 52_041_095
    store = Store(tmp_path / "manifest.json", root=tmp_path / "store", now=lambda: "2026-11-11T00:00:00+00:00")
    e, _ = store.put("https://h.example/a.pdf", body, headers, {"kind": "agenda"})
    assert store.path_for(e["sha256"]).stat().st_size == 52_041_095
    assert fetch.MAX_BYTES == 200 * 1024 * 1024 >= 2 * 52_041_095
    f, _, _ = make({"https://h.example/b.pdf": (200, b"x" * 1001)})
    f.max_bytes = 1000                       # cap + 1, scaled down so the test holds no 200 MiB body
    with pytest.raises(fetch.FetchFailed, match="larger than 1000 bytes"):
        f.get("https://h.example/b.pdf")


def test_county_minutes_page_cap_has_margin_over_621_pages(monkeypatch, tmp_path):
    """L7: a 621-page document is read; 1501 pages is a parse failure."""
    monkeypatch.setattr(minutes, "cached_pages", lambda pdf, cache: [""] * 621)
    assert minutes.parse_minutes(tmp_path / "m.pdf", {"sha256": "a" * 64}, use_ocr=False, text_cache=tmp_path)
    monkeypatch.setattr(minutes, "cached_pages", lambda pdf, cache: [""] * 1501)
    with pytest.raises(ValueError, match="over the 1500-page cap"):
        minutes.parse_minutes(tmp_path / "m.pdf", {"sha256": "a" * 64}, use_ocr=False, text_cache=tmp_path)
