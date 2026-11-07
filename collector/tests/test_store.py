"""Document store and manifest: content addressing and idempotency (AC4.5)."""
import json

import pytest

from collector.fetch import FetchFailed
from collector.store import Store, fetch_into_store


class FakeFetcher:
    def __init__(self, body=b"%PDF-1.4 one"):
        self.body = body
        self.calls = 0

    def get(self, url):
        self.calls += 1
        return 200, self.body, {"Content-Type": "application/pdf", "ETag": '"e1"'}


def make(tmp_path, stamp="2026-11-07T00:00:00+00:00"):
    return Store(tmp_path / "manifest.json", root=tmp_path / "store", now=lambda: stamp)


def test_put_stores_bytes_by_hash_and_writes_manifest(tmp_path):
    st = make(tmp_path)
    e, status = st.put("https://h/a", b"%PDF-1", {"Content-Type": "application/pdf"},
                       {"meeting_date": "2024-12", "label": "December 2024 Minutes"})
    st.save()
    assert status == "new"
    assert (tmp_path / "store" / f"{e['sha256']}.pdf").read_bytes() == b"%PDF-1"
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m[0]["first_fetched_at"] == "2026-11-07T00:00:00+00:00" and m[0]["kind"] == "minutes"


def test_restoring_identical_bytes_leaves_manifest_byte_identical(tmp_path):
    st = make(tmp_path)
    st.put("https://h/a", b"%PDF-1", {"ETag": "x"}, {"meeting_date": "2024-12"})
    st.save()
    before = (tmp_path / "manifest.json").read_bytes()
    for p in (tmp_path / "store").iterdir():         # a fresh container: empty store, later clock
        p.unlink()
    st2 = make(tmp_path, stamp="2027-01-01T00:00:00+00:00")
    f = FakeFetcher(b"%PDF-1")
    _, status = fetch_into_store(f, st2, "https://h/a", {"meeting_date": "2024-12"})
    st2.save()
    assert f.calls == 1 and status == "unchanged"
    assert (tmp_path / "manifest.json").read_bytes() == before


def test_cached_document_is_not_requested_again(tmp_path):
    st = make(tmp_path)
    f = FakeFetcher()
    fetch_into_store(f, st, "https://h/a")
    _, status = fetch_into_store(f, st, "https://h/a")
    assert f.calls == 1 and status == "cached"


def test_new_bytes_for_known_url_become_a_new_source_and_are_logged(tmp_path):
    st = make(tmp_path)
    old, _ = st.put("https://h/a", b"%PDF-old")
    new, status = st.put("https://h/a", b"%PDF-new")
    st.save()
    assert status == "changed"
    assert {e["sha256"] for e in st.entries} == {old["sha256"], new["sha256"]}
    rec = json.loads((tmp_path / "changes.jsonl").read_text().splitlines()[0])
    assert rec["old"] == old["sha256"] and rec["new"] == new["sha256"] and rec["source_url"] == "https://h/a"


def test_non_pdf_body_is_a_failure(tmp_path):
    with pytest.raises(FetchFailed):
        fetch_into_store(FakeFetcher(b"<html>"), make(tmp_path), "https://h/a")
