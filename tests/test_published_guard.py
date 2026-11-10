"""pipeline/tests-step-offline-run: the session guard (conftest.py) sees any change to what a run publishes."""
from qa import published_guard as G


def tree(root):
    for rel, text in (("build/site/index.html", "a"), ("build/site/feeds/all.xml", "b"), ("data/facts.json", "{}"),
                      ("data/localities/x/changes.jsonl", "{}\n"), ("data/store/abc.pdf", "pdf"),
                      ("data/text/abc.txt", "t"), ("build/report.json", "{}")):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return G.snapshot(root)


def test_snapshot_covers_the_site_and_the_data_but_not_the_caches(tmp_path):
    snap = tree(tmp_path)
    assert sorted(snap) == ["build/site/feeds/all.xml", "build/site/index.html", "data/facts.json",
                            "data/localities/x/changes.jsonl"]
    assert G.snapshot(tmp_path / "missing") == {}


def test_a_rebuilt_site_or_rewritten_data_file_is_reported(tmp_path):
    before = tree(tmp_path)
    assert G.changed(before, G.snapshot(tmp_path)) == []
    (tmp_path / "build/site/index.html").write_text("a")                 # same bytes rewritten: not a change
    (tmp_path / "data/store/new.pdf").write_text("pdf")                  # the cache may grow
    assert G.changed(before, G.snapshot(tmp_path)) == []
    (tmp_path / "build/site/index.html").write_text("preview build")     # rebuilt in place
    (tmp_path / "build/site/feeds/all.xml").unlink()
    (tmp_path / "data/manifest.json").write_text("[]")
    assert G.changed(before, G.snapshot(tmp_path)) == ["build/site/feeds/all.xml", "build/site/index.html",
                                                       "data/manifest.json"]


def test_the_guard_is_active_in_this_session(request):
    assert "tests_leave_published_files_alone" in request.fixturenames
