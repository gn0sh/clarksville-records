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


def test_superseded_document_change_line_matches_the_changes_schema(tmp_path):
    """CI run 43266569362: a replaced document wrote "page": null and the site build rejected changes.jsonl."""
    from sitegen.build import read_changes
    st = make(tmp_path)
    st.put("https://h/a", b"%PDF-old")
    st.put("https://h/a", b"%PDF-new")
    line = json.loads((tmp_path / "changes.jsonl").read_text().splitlines()[0])
    assert None not in line.values() and "page" not in line
    assert read_changes(tmp_path / "changes.jsonl")[0]["new"] == line["new"]


def test_rpc_locality_store_change_line_matches_the_changes_schema(tmp_path):
    """The RPC writes its own changes.jsonl beside data/localities/<x>/manifest.json, through the same Store."""
    from sitegen.build import read_changes
    d = tmp_path / "data" / "localities" / "rpc"
    st = Store(manifest_path=d / "manifest.json", root=tmp_path / "store", now=lambda: "2026-11-07T00:00:00+00:00")
    st.put("https://h/agenda.docx", b"PK-old")
    st.put("https://h/agenda.docx", b"PK-new")
    assert len(read_changes(d / "changes.jsonl")) == 1


def test_log_change_drops_none_values(tmp_path):
    st = make(tmp_path)
    st._log_change({"date": "2026-11-07", "note": "n", "page": None, "old": None, "source_url": "https://h/a"})
    assert json.loads((tmp_path / "changes.jsonl").read_text()) == {"date": "2026-11-07", "note": "n",
                                                                     "source_url": "https://h/a"}


@pytest.mark.parametrize("rec", [
    {"date": "2026-11-07", "source_url": "http://h/a"},       # the site only links https
    {"date": "2026-11-07", "page": 0},
    {"date": "7 Nov 2026"},
    {"note": "no date"},
    {"date": "2026-11-07", "extra": "x"},
])
def test_log_change_refuses_a_line_the_build_would_reject(tmp_path, rec):
    st = make(tmp_path)
    with pytest.raises(ValueError, match="changes.schema.json"):
        st._log_change(rec)
    assert not (tmp_path / "changes.jsonl").exists()


def test_non_pdf_body_is_a_failure(tmp_path):
    with pytest.raises(FetchFailed):
        fetch_into_store(FakeFetcher(b"<html>"), make(tmp_path), "https://h/a")


# ------------------------------------------------------------------ idempotence/superseded-source

def test_replaced_document_marks_the_old_entry_superseded_and_builds_read_only_the_latest(tmp_path):
    st = make(tmp_path)
    old, _ = st.put("https://h/a", b"%PDF-old", {}, {"meeting_date": "2024-12"})
    st.now = lambda: "2026-11-08T00:00:00+00:00"
    new, status = st.put("https://h/a", b"%PDF-new", {}, {"meeting_date": "2024-12"})
    st.save()
    assert status == "changed" and old["superseded_by"] == new["sha256"] and "superseded_by" not in new
    assert st.current() == [new] and st.superseded() == [old]
    again = Store(tmp_path / "manifest.json", root=tmp_path / "store")
    assert [e["sha256"] for e in again.current()] == [new["sha256"]]
    assert again.superseded()[0]["superseded_by"] == new["sha256"]


def test_a_missing_superseded_blob_does_not_fail_the_build(tmp_path, monkeypatch):
    from collector import __main__ as M
    from collector import minutes
    st = make(tmp_path)
    meta = {"meeting_date": "2024-12-09", "label": "December 2024 Minutes"}
    old, _ = st.put("https://h/a", b"%PDF-old", {}, meta)
    st.now = lambda: "2026-11-08T00:00:00+00:00"
    new, _ = st.put("https://h/a", b"%PDF-new", {}, meta)
    st.path_for(old["sha256"]).unlink()                       # the old bytes are gone (a fresh container)
    read = []

    def fake_parse(path, entry, use_ocr=True):
        read.append(entry["sha256"])
        return minutes.ParsedDocument(entry, 1, "text", [], [], [], [1])
    monkeypatch.setattr(minutes, "parse_minutes", fake_parse)
    log = {"failures": [], "parsed": 0, "held_back": None}
    M.cmd_build(st, log, use_ocr=False)
    assert read == [new["sha256"]]
    assert not [f for f in log["failures"] if f.get("url") == "https://h/a"]
    assert log["superseded"] == [{"url": "https://h/a", "sha256": old["sha256"], "superseded_by": new["sha256"]}]


def test_cache_restored_file_with_wrong_hash_is_deleted_and_refetched(tmp_path):
    """pipeline/cache-integrity: a stored file whose bytes do not hash to its name is not trusted."""
    st = make(tmp_path)
    e, _ = st.put("https://h/a", b"%PDF-1 good", {"Content-Type": "application/pdf"}, {"meeting_date": "2024-12"})
    p = st.path_for(e["sha256"])
    assert make(tmp_path).has_bytes(e["sha256"])             # an intact file is used
    p.write_bytes(b"%PDF-1 tampered")
    fresh = make(tmp_path)                                   # a new run: nothing verified yet
    assert not fresh.has_bytes(e["sha256"]) and not p.exists()      # mismatch: deleted, treated as missing
    f = FakeFetcher(body=b"%PDF-1 good")
    fetch_into_store(f, fresh, "https://h/a")
    assert f.calls == 1 and p.read_bytes() == b"%PDF-1 good"        # refetched
