"""Out-of-repo leak scan (qa/pii_scan.py, privacy/transcript-private-addresses row 14).

Rules under test: needles are the spans the masker would mask in raw transcripts read from a folder outside the
repo; every tracked file outside data/, every file of the data/ tree on disk (not git's index: it is off main, ADR
0011 row LS; an empty data/ is refused) and an optional built site are scanned case-insensitively with whitespace
folded; the output names path:line and counts only, never the matched text; a --raw folder inside the repo is
refused; nothing is written; a needle is public, not a hit, only as a whole token in a named public field (RPC case
location, agenda item title) or as exactly a listed public building.
All values are synthetic."""
import io
import json
import subprocess

import pytest

from collector import data_shape
from qa import pii_scan

ADDRESS = "418 Example Court"
PHONE = "931-555-0142"


def _git_repo(path, files: dict[str, str], data: dict[str, str] | None = None):
    """A repo with `files` tracked, plus `data` written to disk untracked (the fetched data/ tree; one clean
    collector file when not given, since the scan refuses an empty data/)."""
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    for rel, text in {"data/facts.json": "{}\n", **(data or {})}.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text, encoding="utf-8")
    for rel, text in files.items():
        p = path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "rm", "-q", "-r", "--cached", "--ignore-unmatch", "data"], check=True)
    return path


def _raw(folder, lines):
    folder.mkdir(parents=True)
    d = {"event_id": 1, "start": "2026-01-01", "segments": [{"start": i, "end": i + 1, "text": t}
                                                             for i, t in enumerate(lines)]}
    (folder / "2026-01-01_1.json").write_text(json.dumps(d), encoding="utf-8")
    return folder


RAW_LINES = ["Good evening.", f"Pat Example. My address is {ADDRESS}, Clarksville.", f"call me at {PHONE} please",
             "the zoning case at 1100 Sample Road is next", "I live at 515 so I'm right next to it"]


def _setup(tmp_path, files, site_files=None):
    repo = _git_repo(tmp_path / "repo", files)
    raw = _raw(tmp_path / "outside" / "raw", RAW_LINES)
    site = None
    if site_files is not None:
        site = tmp_path / "site"
        for rel, text in site_files.items():
            (site / rel).parent.mkdir(parents=True, exist_ok=True)
            (site / rel).write_text(text, encoding="utf-8")
    return repo, raw, site


def _scan(tmp_path, files, site_files=None):
    repo, raw, site = _setup(tmp_path, files, site_files)
    out = io.StringIO()
    return pii_scan.scan(raw, site, root=repo, out=out), out.getvalue(), repo


def _tree(root):
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts}


def test_a_planted_address_is_reported_by_path_and_line_without_its_text(tmp_path):
    files = {"clean.md": "nothing here\n",
             "notes/leak.md": "line one\nline two\nas said: my ADDRESS is 418   example\ncourt, see video\n",
             "tests/phone.py": 'X = 1\nY = "931 555 0142"\n',
             "spaced.txt": "hotline 9 3 1 5 5 5 0 1 4 2 now\n",
             "bare.txt": "the number 515 is everywhere and harmless\n"}
    repo, raw, site = _setup(tmp_path, files, site_files={"city/page.html": "<p>x</p>\n<p>418 Example Court</p>\n"})
    before = _tree(tmp_path)
    out = io.StringIO()
    code = pii_scan.scan(raw, site, root=repo, out=out)
    out = out.getvalue()
    assert _tree(tmp_path) == before                           # it writes nothing
    assert code == 1
    assert "HIT tracked:notes/leak.md:3" in out                 # split over two lines, any case: found at its start
    assert "HIT tracked:tests/phone.py:2" in out                # a phone in another form
    assert "HIT tracked:spaced.txt:1" in out                    # single digits apart
    assert "HIT site:city/page.html:2" in out
    assert "clean.md" not in out and "bare.txt" not in out      # a bare number is not a needle on its own
    lowered = out.lower()
    for secret in ("418", "example court", "555", "0142", "515", "pat example", "sample road"):
        assert secret not in lowered, secret                    # never the matched text
    assert out.strip().splitlines()[-1].startswith("pii_scan: ")
    assert "4 hits in 4 files" in out


def test_a_clean_tree_reports_zero_hits(tmp_path):
    code, out, _ = _scan(tmp_path, {"a.md": "Pat Example. My address is [address omitted], Clarksville.\n"})
    assert code == 0 and "0 hits in 0 files" in out and "HIT" not in out


def test_source_data_and_public_places_are_public_not_hits(tmp_path):
    files = {"data/rpc.json": json.dumps({"cases": [{"location": "1100 Sample Road"}]}),
             "fixtures/page.html": f"<p>Office</p><p>{pii_scan.PUBLIC_PLACES[1].title()}</p>\n",
             "data/t/transcripts/x.json": json.dumps({"segments": [[0, 1, ADDRESS]]})}
    raw_lines = RAW_LINES + [f"meeting at {pii_scan.PUBLIC_PLACES[1].title()} tonight"]
    repo = _git_repo(tmp_path / "repo", files)
    raw = _raw(tmp_path / "outside" / "raw", raw_lines)
    out = io.StringIO()
    code = pii_scan.scan(raw, None, root=repo, out=out)
    text = out.getvalue()
    assert "PUBLIC data:data/rpc.json:1" in text and "PUBLIC tracked:fixtures/page.html:1" in text
    assert "HIT data:data/t/transcripts/x.json:1" in text and code == 1    # a transcript file is never source data
    assert "sample road" not in text.lower() and pii_scan.PUBLIC_PLACES[1] not in text.lower()


def test_a_raw_folder_inside_the_repo_is_refused(tmp_path, capsys):
    repo = _git_repo(tmp_path / "repo", {"a.md": "x\n"})
    raw = _raw(repo / "raw", RAW_LINES)
    with pytest.raises(pii_scan.ScanError, match="inside the repo"):
        pii_scan.scan(raw, None, root=repo, out=io.StringIO())
    inside = pii_scan.ROOT / "docs"
    assert pii_scan.main(["--raw", str(inside)]) == 2
    assert "inside the repo" in capsys.readouterr().err
    assert pii_scan.main(["--raw", str(tmp_path / "missing")]) == 2


def _scan_lines(tmp_path, files, raw_lines):
    repo = _git_repo(tmp_path / "repo", files)
    raw = _raw(tmp_path / "outside" / "raw", raw_lines)
    out = io.StringIO()
    return pii_scan.scan(raw, None, root=repo, out=out), out.getvalue()


def test_raw_text_copied_into_a_data_file_is_a_hit_not_public(tmp_path):
    """Security review M1: only the named public fields clear a needle, never any string of data/** (raw text copied
    into a data file, or into another field of the RPC data, would otherwise whitelist itself)."""
    files = {"data/notes.json": json.dumps({"note": RAW_LINES[1]}),
             "data/rpc.json": json.dumps({"cases": [{"location": "1100 Sample Road", "applicant": RAW_LINES[1]}]}),
             "data/facts.json": json.dumps({"items": [{"title": "Zoning case", "summary": RAW_LINES[1]}]})}
    code, text = _scan_lines(tmp_path, files, RAW_LINES)
    assert code == 1
    for rel in ("data/notes.json", "data/rpc.json", "data/facts.json"):
        assert f"HIT data:{rel}:1" in text, rel
    assert "1 more public" in text                      # the case location still clears its own needle
    assert "418" not in text and "example court" not in text.lower()


def test_a_public_location_clears_whole_tokens_only(tmp_path):
    """Security review M1: house 10 is not cleared by house 110 on the same street (word boundaries), while an
    agenda item title and the case location clear the exact address."""
    files = {"data/rpc.json": json.dumps({"cases": [{"location": "110 Sample Lane Clarksville TN"}]}),
             "data/county-agendas/agendas.json": json.dumps(
                 {"meetings": [{"items": [{"title": "Rezoning at 1100 Sample Road"}]}]}),
             "notes.md": "she lives at\n10 Sample Lane\n"}
    code, text = _scan_lines(tmp_path, files, ["My address is 10 Sample Lane.", RAW_LINES[3]])
    assert code == 1 and "HIT tracked:notes.md:2" in text
    assert "0 text needles" not in text and "(1 more public)" in text   # the agenda title clears 1100 only
    assert "PUBLIC data:data/county-agendas/agendas.json:1" in text
    assert "sample lane" not in text.lower() and "sample road" not in text.lower()


def test_a_merged_span_holding_a_public_place_and_another_number_is_a_hit(tmp_path):
    """Security review L1: PUBLIC_PLACES clear a needle by equality only, so "12 and <public place>" is a hit."""
    place = pii_scan.PUBLIC_PLACES[1].title()
    files = {"notes.md": f"x\nmy address is 12 and {place}, thanks\n", "office.md": f"{place}\n"}
    code, text = _scan_lines(tmp_path, files, [f"my address is 12 and {place}, thanks", f"meeting at {place} tonight"])
    assert code == 1 and "HIT tracked:notes.md:2" in text
    assert "PUBLIC tracked:office.md:1" in text and "(1 more public)" in text
    assert pii_scan.PUBLIC_PLACES[1] not in text.lower()


def test_a_tracked_gzip_is_scanned_by_decompressing_it(tmp_path):
    """privacy/pii-scan-gzip-blind: the pinned test data is gzip (tests/fixtures/real-data-*.json.gz); an address in a
    tracked *.json.gz is a hit by path and line, never its text, and a clean one is scanned and counted."""
    import gzip
    repo, raw, _ = _setup(tmp_path, {"a.md": "nothing\n"})
    fx = repo / "tests" / "fixtures"
    fx.mkdir(parents=True)
    (fx / "leak.json.gz").write_bytes(gzip.compress(
        json.dumps({"x": 1}).encode() + b"\n" + json.dumps({"note": f"lives at {ADDRESS}"}).encode(), mtime=0))
    (fx / "clean.json.gz").write_bytes(gzip.compress(b'{"title": "Zoning case"}', mtime=0))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    out = io.StringIO()
    assert pii_scan.scan(raw, None, root=repo, out=out) == 1
    text = out.getvalue()
    assert "HIT tracked:tests/fixtures/leak.json.gz:2" in text and "clean.json.gz" not in text
    assert "418" not in text and "example court" not in text.lower()
    assert "scanned 3 tracked files" in text                       # a.md and both gzip files


def test_a_tracked_gzip_that_cannot_be_read_is_refused_not_skipped(tmp_path):
    repo, raw, _ = _setup(tmp_path, {"a.md": "nothing\n"})
    (repo / "bad.json.gz").write_bytes(b"not gzip at all")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    with pytest.raises(pii_scan.ScanError, match="bad.json.gz: not a readable gzip"):
        pii_scan.scan(raw, None, root=repo, out=io.StringIO())


def test_the_committed_pinned_data_is_readable_by_the_scan():
    from conftest import ROOT
    gz = sorted((ROOT / "tests" / "fixtures").glob("*.json.gz"))
    assert gz
    for p in gz:
        body = pii_scan._read(p)
        assert pii_scan._is_gzip(p) and body is not None and body.lstrip().startswith("{"), p.name


# ------------------------------------------------------------- B1b row LS: data/ is read on disk, never from git's index

def test_an_empty_data_tree_is_refused_not_passed(tmp_path):
    """After the cutover git lists no data/: a scan of a checkout without fetched data must fail, not pass silently."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "a.md").write_text("nothing\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    raw = _raw(tmp_path / "outside" / "raw", RAW_LINES)
    with pytest.raises(pii_scan.ScanError, match="data/ holds no collector output"):
        pii_scan.scan(raw, None, root=repo, out=io.StringIO())
    (repo / "data" / "store").mkdir(parents=True)                       # only a cache: still empty
    (repo / "data" / "store" / "x.json").write_text("{}", encoding="utf-8")
    with pytest.raises(pii_scan.ScanError, match="data/ holds no collector output"):
        pii_scan.scan(raw, None, root=repo, out=io.StringIO())


def test_a_needle_planted_in_a_fetched_data_file_is_found(tmp_path):
    """A data/ file git does not track (filled by fetch-data from records-data) is scanned; the caches are not."""
    data = {"data/localities/x/facts.json": json.dumps({"meetings": [{"note": f"lives at {ADDRESS}"}]}),
            "data/text/abc.txt": f"public text layer {ADDRESS}\n"}
    repo = _git_repo(tmp_path / "repo", {"a.md": "nothing\n"}, data=data)
    raw = _raw(tmp_path / "outside" / "raw", RAW_LINES)
    listed = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True).stdout
    assert "data/" not in listed
    out = io.StringIO()
    assert pii_scan.scan(raw, None, root=repo, out=out) == 1
    text = out.getvalue()
    assert "HIT data:data/localities/x/facts.json:1" in text
    assert "data/text/" not in text and "scanned 1 tracked files, 2 data files" in text
    assert "418" not in text and "example court" not in text.lower()


def test_a_tracked_data_file_is_scanned_once(tmp_path):
    """Before the cutover data/ is still tracked: it is read from disk once, not again as a tracked file."""
    repo = _git_repo(tmp_path / "repo", {"a.md": "nothing\n"}, data={"data/n.json": json.dumps({"n": ADDRESS})})
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    raw = _raw(tmp_path / "outside" / "raw", RAW_LINES)
    out = io.StringIO()
    assert pii_scan.scan(raw, None, root=repo, out=out) == 1
    text = out.getvalue()
    assert text.count("data/n.json") == 1 and "HIT data:data/n.json:1" in text and "1 hits in 1 files" in text


def test_config_transcripts_are_scanned_as_tracked_files(tmp_path):
    repo = _git_repo(tmp_path / "repo", {"config/localities/x/transcripts/m.json":
                                         json.dumps({"segments": [[0, 1, f"at {ADDRESS}"]]})})
    raw = _raw(tmp_path / "outside" / "raw", RAW_LINES)
    out = io.StringIO()
    assert pii_scan.scan(raw, None, root=repo, out=out) == 1
    assert "HIT tracked:config/localities/x/transcripts/m.json:1" in out.getvalue()


def test_an_unstaged_config_transcript_is_scanned(tmp_path):
    """Review nit data-off-main/leak-scan-misses-unstaged-config: a new config transcript not yet `git add`ed is
    scanned; a git-ignored file is not."""
    repo = _git_repo(tmp_path / "repo", {".gitignore": "ignored/\n"})
    new = repo / "config/localities/x/transcripts/new.json"
    new.parent.mkdir(parents=True)
    new.write_text(json.dumps({"segments": [[0, 1, f"at {ADDRESS}"]]}), encoding="utf-8")
    (repo / "ignored").mkdir()
    (repo / "ignored/n.md").write_text(f"{ADDRESS}\n", encoding="utf-8")
    listed = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True).stdout
    assert "new.json" not in listed
    out = io.StringIO()
    assert pii_scan.scan(_raw(tmp_path / "outside" / "raw", RAW_LINES), None, root=repo, out=out) == 1
    text = out.getvalue()
    assert "HIT tracked:config/localities/x/transcripts/new.json:1" in text and "ignored/" not in text


@pytest.mark.parametrize("rel,executable", [("data/x/Maps/rpc.json", False), ("data/x/Transcripts/rpc.json", False),
                                            ("data/rpc.json", True)])
def test_a_data_file_outside_the_shape_never_clears_a_needle(tmp_path, rel, executable):
    """Review nit data-off-main/public-clear-from-untracked: only data/ files whose listing entry passes data_shape
    clear a needle as PUBLIC; a stray file (a maps/ or transcripts/ folder in any case, an executable) is a HIT."""
    repo = _git_repo(tmp_path / "repo", {"a.md": "nothing\n"},
                     data={rel: json.dumps({"cases": [{"location": "1100 Sample Road"}]})})
    if executable:
        (repo / rel).chmod(0o755)
    assert data_shape.problems(data_shape.disk_listing(repo / "data"))
    out = io.StringIO()
    assert pii_scan.scan(_raw(tmp_path / "outside" / "raw", RAW_LINES), None, root=repo, out=out) == 1
    text = out.getvalue()
    assert f"HIT data:{rel}:1" in text and "PUBLIC data:" not in text


def test_the_cache_list_matches_gitignore():
    from conftest import ROOT
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for c in pii_scan.DATA_CACHES:
        assert f"data/{c}/" in ignored, c
