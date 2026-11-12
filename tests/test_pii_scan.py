"""Out-of-repo leak scan (qa/pii_scan.py, privacy/transcript-private-addresses row 14).

Rules under test: needles are the spans the masker would mask in raw transcripts read from a folder outside the
repo; every tracked file (and an optional built site) is scanned case-insensitively with whitespace folded; the output
names path:line and counts only, never the matched text; a --raw folder inside the repo is refused; nothing is
written; a needle is public, not a hit, only as a whole token in a named public field (RPC case location, agenda item
title) or as exactly a listed public building.
All values are synthetic."""
import io
import json
import subprocess

import pytest

from qa import pii_scan

ADDRESS = "418 Example Court"
PHONE = "931-555-0142"


def _git_repo(path, files: dict[str, str]):
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    for rel, text in files.items():
        p = path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
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
    assert "PUBLIC tracked:data/rpc.json:1" in text and "PUBLIC tracked:fixtures/page.html:1" in text
    assert "HIT tracked:data/t/transcripts/x.json:1" in text and code == 1    # a transcript file is never source data
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
        assert f"HIT tracked:{rel}:1" in text, rel
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
    assert "PUBLIC tracked:data/county-agendas/agendas.json:1" in text
    assert "sample lane" not in text.lower() and "sample road" not in text.lower()


def test_a_merged_span_holding_a_public_place_and_another_number_is_a_hit(tmp_path):
    """Security review L1: PUBLIC_PLACES clear a needle by equality only, so "12 and <public place>" is a hit."""
    place = pii_scan.PUBLIC_PLACES[1].title()
    files = {"notes.md": f"x\nmy address is 12 and {place}, thanks\n", "office.md": f"{place}\n"}
    code, text = _scan_lines(tmp_path, files, [f"my address is 12 and {place}, thanks", f"meeting at {place} tonight"])
    assert code == 1 and "HIT tracked:notes.md:2" in text
    assert "PUBLIC tracked:office.md:1" in text and "(1 more public)" in text
    assert pii_scan.PUBLIC_PLACES[1] not in text.lower()
