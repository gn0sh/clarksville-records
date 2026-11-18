"""B1b (docs/tasks/data-off-main.md; ADR 0011 decision 2a, invariant I-in, rows TR and MP of
docs/architecture/v1-fail-2026-11-18.md): person-made inputs live under config/ and reach the build only as reviewed
files there. The transcript import and remask write only under config/localities/<locality>/transcripts/ (reading the
facts and event listing from data/); the build and the qa checks read transcripts only from config/, never a copy in
data/; tools/fetch_map.py writes its manifest only under config/maps/. (Kept city books, row FB:
collector/tests/test_fin_books.py; the scrub tool, row SC: collector/tests/test_rpc.py; the shape, row T:
tests/test_data_shape.py; the leak scan, row LS: tests/test_pii_scan.py.)"""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT
from collector import transcripts as ctx
from qa import site_checks
from sitegen import config
from sitegen import transcripts as tx
from sitegen.build import build
from test_transcripts import (CFG, LISTING, MEETING, SEGMENTS, city_facts, city_wards, kind_of, raw_transcript,
                              write_raw)

LOC = "clarksville-tn"
CONFIG_TX = ROOT / "config" / "localities" / LOC / "transcripts"
DATA_CITY = ROOT / "data" / "localities" / LOC


def _tree(root: Path) -> dict[str, str]:
    """{relative path: sha256} of every file under root (none: {})."""
    if not root.is_dir():
        return {}
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _changed(before: dict, after: dict) -> set[str]:
    return {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}


# ----------------------------------------------------------------------------------------------- transcripts (TR)

@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """A repository root in tmp_path: the council config and the city's data/ (pinned facts, the event listing), with
    sitegen.config pointed at it. -> (root, raw input folder)."""
    root = tmp_path / "repo"
    (root / "config" / "localities" / LOC).mkdir(parents=True)
    shutil.copy(ROOT / "config" / "localities" / LOC / "council.yml", root / "config" / "localities" / LOC)
    city = root / "data" / "localities" / LOC
    city.mkdir(parents=True)
    facts = city_facts()
    (city / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    shutil.copy(DATA_CITY / "civicclerk-listing.json", city / "civicclerk-listing.json")
    monkeypatch.setattr(config, "REPO_ROOT", root)
    monkeypatch.setattr(config, "CONFIG_DIR", root / "config")
    m = next(x for x in facts["meetings"] if x["id"] == MEETING)
    raw = tmp_path / "whisper"                       # outside the repo, as on Brian's PC
    write_raw(raw, raw_transcript(m, SEGMENTS))
    return root, raw


def test_import_and_remask_write_only_under_config(tmp_repo):
    root, raw = tmp_repo
    out = root / "config" / "localities" / LOC / "transcripts"
    assert config.load_council(LOC)["transcripts_path"] == out
    real = (_tree(ROOT / "data"), _tree(CONFIG_TX))
    before = _tree(root)
    assert ctx.main(["import", str(raw), "--locality", LOC]) == 0
    after = _tree(root)
    changed = _changed(before, after)
    assert changed == {f"config/localities/{LOC}/transcripts/{MEETING}.json",
                       f"config/localities/{LOC}/transcripts/index.json"}
    assert not (root / "data" / "localities" / LOC / "transcripts").exists()
    # remask (after a change to the masking rules): a committed line that is not masked is rewritten, in config/ only
    p = out / f"{MEETING}.json"
    t = json.loads(p.read_text(encoding="utf-8"))
    t["segments"][0][2] = "my address is 418 Example Court, thanks"
    p.write_text(json.dumps(t), encoding="utf-8")
    before = _tree(root)
    assert ctx.main(["remask", "--locality", LOC]) == 0
    changed = _changed(before, _tree(root))
    assert changed and all(c.startswith(f"config/localities/{LOC}/transcripts/") for c in changed)
    assert "418 Example Court" not in p.read_text(encoding="utf-8")
    assert (_tree(ROOT / "data"), _tree(CONFIG_TX)) == real            # the real checkout is untouched


def test_import_refuses_an_empty_data_tree(tmp_repo, capsys):
    root, raw = tmp_repo
    shutil.rmtree(root / "data")
    before = _tree(root)
    assert ctx.main(["import", str(raw), "--locality", LOC]) == 1
    assert "fill data/ from records-data first" in capsys.readouterr().err
    assert _tree(root) == before


def test_the_build_reads_the_committed_transcripts_from_config_only():
    """No data/.../transcripts/ folder exists; the build's council config and the qa checks name the config folder,
    and the committed transcripts load from it."""
    assert not (DATA_CITY / "transcripts").exists()
    assert [c["transcripts_path"] for c in config.COUNCILS if c["locality"] == LOC] == [CONFIG_TX]
    facts = json.loads((DATA_CITY / "facts.json").read_text(encoding="utf-8"))
    assert len(tx.load(CONFIG_TX, facts)) == 17
    cs = site_checks.councils({"fixture": False})
    assert [c["transcripts_dir"] for c in cs if c["locality"] == LOC] == [CONFIG_TX]


@pytest.fixture(scope="module")
def city_with_a_data_copy(tmp_path_factory):
    """A small city: facts and wards in data/-like d, with a transcript imported beside the facts (where it used to
    live) and an empty config transcripts folder."""
    from test_council_pages import subset
    sub = subset(city_facts(), ("2019-01-03-regular", MEETING))
    d = tmp_path_factory.mktemp("data-city")
    (d / "facts.json").write_text(json.dumps(sub), encoding="utf-8")
    wards = [w for w in city_wards() if w["meeting_id"] in ("2019-01-03-regular", MEETING)]
    (d / "wards.json").write_text(json.dumps(wards), encoding="utf-8")
    m = next(x for x in sub["meetings"] if x["id"] == MEETING)
    write_raw(d / "raw", raw_transcript(m, SEGMENTS))
    ctx.import_dir(d / "raw", sub, d / "transcripts", kind_of, LISTING)
    assert (d / "transcripts" / f"{MEETING}.json").is_file()
    cfg_tx = tmp_path_factory.mktemp("config-tx")
    return d, sub, cfg_tx


def test_a_transcript_copy_left_in_data_is_not_read(city_with_a_data_copy, tmp_path):
    d, sub, cfg_tx = city_with_a_data_copy
    assert tx.load(cfg_tx, sub) == {} and len(tx.load(d / "transcripts", sub)) == 1
    cfg = {**CFG, "facts_path": d / "facts.json", "wards_path": d / "wards.json", "transcripts_path": cfg_tx}
    out = tmp_path / "build" / "site"
    result = build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, councils=[cfg],
                   target="pages")
    assert result["transcript_pages"] == 0 and not (out / "city" / "transcripts").exists()
    # the same build with the folder in config/ has the page
    shutil.copytree(d / "transcripts", cfg_tx, dirs_exist_ok=True)
    out2 = tmp_path / "build2" / "site"
    r2 = build(FIXTURE, out2, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, councils=[cfg],
               target="pages")
    assert r2["transcript_pages"] == 1 and (out2 / "city" / "transcripts" / f"{MEETING}.html").is_file()
    for f in cfg_tx.iterdir():
        f.unlink()


def test_a_transcript_copy_in_data_is_never_source_text(tmp_path, monkeypatch):
    """qa check (c): a line equal to a string of the collector data is not transcript-only text. A transcripts/ folder
    under data/ is never that data (else a stray copy would clear every line)."""
    root = tmp_path / "repo"
    (root / "data" / "localities" / "x" / "transcripts").mkdir(parents=True)
    (root / "data" / "localities" / "x" / "transcripts" / "m.json").write_text(
        json.dumps({"segments": [[0, 1, "a line only a transcript holds"]]}), encoding="utf-8")
    (root / "data" / "facts.json").write_text(json.dumps({"items": [{"title": "An item title read aloud"}]}),
                                              encoding="utf-8")
    monkeypatch.setattr(site_checks, "ROOT", root)
    text = site_checks._source_text([])
    assert "An item title read aloud" in text and "a line only a transcript holds" not in text


# ------------------------------------------------------------------------------------------------ map manifest (MP)

def test_the_map_manifest_is_in_config_and_the_build_reads_it_there():
    import yaml
    site = yaml.safe_load((ROOT / "config" / "site.yml").read_text(encoding="utf-8"))
    assert "config/maps/manifest.json" in site["fetch_manifests"]
    assert not any(m.startswith("data/maps/") for m in site["fetch_manifests"])
    assert (ROOT / "config" / "maps" / "manifest.json").is_file() and not (ROOT / "data" / "maps" / "manifest.json").exists()
    rows = json.loads((ROOT / "config" / "maps" / "manifest.json").read_text(encoding="utf-8"))
    assert rows and all(r["kind"] == "map" for r in rows)


def test_fetch_map_writes_only_under_config_maps(tmp_path, monkeypatch, capsys):
    from tools import fetch_map
    maps = tmp_path / "repo" / "config" / "maps"
    monkeypatch.setattr(fetch_map, "MAPS_DIR", maps)
    monkeypatch.setattr(fetch_map, "MAPS_MANIFEST", maps / "manifest.json")
    monkeypatch.setenv("RECORDS_STORE", str(tmp_path / "store"))           # the uncommitted document store
    asked = []

    class Stub:
        log = []

        def __init__(self, **kw):
            pass

        def get(self, url):
            asked.append(url)
            return 200, b"%PDF-1.7 map", {"Content-Type": "application/pdf"}
    monkeypatch.setattr(fetch_map, "PoliteFetcher", Stub)
    real = (_tree(ROOT / "data"), _tree(ROOT / "config"))
    url = "https://www.cmcrpc.com/maps/wards.pdf"
    assert fetch_map.main([url, "--label", "Wards poster"]) == 0
    assert asked == [url]
    assert set(_tree(tmp_path / "repo")) <= {"config/maps/manifest.json", "config/maps/changes.jsonl"}
    assert "config/maps/manifest.json" in _tree(tmp_path / "repo")
    assert json.loads((maps / "manifest.json").read_text())[0]["url"] == url
    # any other manifest (data/, or outside config/maps/) is refused before a request
    for bad in (tmp_path / "repo" / "data" / "maps" / "manifest.json", tmp_path / "repo" / "config" / "m.json",
                maps / ".." / "x.json"):
        assert fetch_map.main([url, "--label", "x", "--manifest", str(bad)]) == 2
    assert asked == [url] and not (tmp_path / "repo" / "data").exists()
    assert "--manifest must be under" in capsys.readouterr().err
    assert (_tree(ROOT / "data"), _tree(ROOT / "config")) == real


def test_fetch_map_defaults_to_config_maps():
    from tools import fetch_map
    assert fetch_map.MAPS_MANIFEST == ROOT / "config" / "maps" / "manifest.json"
    assert fetch_map.MAPS_DIR == ROOT / "config" / "maps"
