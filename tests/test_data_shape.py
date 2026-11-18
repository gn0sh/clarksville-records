"""B1 (docs/tasks/data-off-main.md, rows D and CFG): data/ holds collector output only (I-data'', SHAPE''), the
curated inputs live in config/ and every reader takes them from there, and config/published-fact-changes.yml is a
valid, empty list."""
import json
import subprocess
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from collector import data_shape, facts, names, reviewed_lists
from qa import site_checks
from sitegen import views

ROOT = Path(__file__).resolve().parent.parent
PFC = ROOT / "config" / "published-fact-changes.yml"
PFC_SCHEMA = ROOT / "schema" / "published-fact-changes.schema.json"
BLOB = b"100644 blob " + b"0123456789abcdef0123" * 2 + b"\t"


def _listing(*paths: bytes, head: bytes = BLOB) -> bytes:
    return b"".join(head + p + b"\0" for p in paths)


def test_data_on_disk_holds_only_collector_output():
    """I-data'' on the data/ folder this run reads (filled by scripts/fetch-data, or the update job's checkout of
    records-data): every entry fits SHAPE'' and none is curated or config-owned. It reads the disk, not git's index of
    main, so it keeps working once data/ leaves main at the cutover (B1 review main-protect/data-test-breaks-at-cutover),
    and an empty data/ fails (problems() refuses it)."""
    assert data_shape.problems(data_shape.disk_listing(ROOT / "data")) == []


def test_disk_listing_matches_git(tmp_path):
    """disk_listing gives the bytes `git ls-tree -r -z HEAD -- data` gives for the same files (mode, blob id, path,
    order), caches left out, so the on-disk check is the gate's check."""
    repo = tmp_path / "repo"
    files = {"data/facts.json": b"{}\n", "data/localities/x/b.json": b"[1]", "data/localities/x/a.json": b"",
             "data/changes.jsonl": b'{"a": 1}\n', "data/run.sh": b"#!/bin/sh\n"}
    for rel, body in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(body)
    (repo / "data" / "run.sh").chmod(0o755)
    (repo / "data" / "link.json").symlink_to("facts.json")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q",
                    "-m", "x"], check=True)
    git = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "-z", "HEAD", "--", "data"], capture_output=True,
                         check=True).stdout
    for cache in data_shape.DATA_CACHES:                   # untracked caches on disk are not in the listing
        (repo / "data" / cache).mkdir()
        (repo / "data" / cache / "x.pdf").write_bytes(b"%PDF")
    assert data_shape.disk_listing(repo / "data") == git
    found = data_shape.problems(git)
    assert len(found) == 2 and found[0].endswith("?data/link.json") and found[1].endswith("?data/run.sh")
    assert data_shape.disk_listing(tmp_path / "none") == b"" and data_shape.problems(b"") == ["data/ holds no file"]


def test_the_cache_list_matches_gitignore():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert all(f"data/{c}/" in ignored for c in data_shape.DATA_CACHES)


def test_shape_bash_line_is_what_bash_gives_grep():
    """SHAPE_ERE is byte for byte what bash makes of $'SHAPE_BASH', so B2 can paste SHAPE_BASH into the workflow."""
    made = subprocess.run(["bash", "-c", "SHAPE=$'" + data_shape.SHAPE_BASH + "'\nprintf %s \"$SHAPE\""],
                          capture_output=True, check=True).stdout
    assert made == data_shape.SHAPE_ERE


@pytest.mark.parametrize("path", [b"data/facts.json", b"data/changes.jsonl", b"data/localities/clarksville-tn/wards.json",
                                  b"data/localities/clarksville-tn/transcripts.json", b"data/mapsx/manifest.json",
                                  b"data/localities/maps/manifest.json", b"data/county-agendas/changes.jsonl",
                                  b"data/a_b/x-1.v2.json"])
def test_collector_output_passes(path):
    assert data_shape.problems(_listing(path)) == []


@pytest.mark.parametrize("path", [b"data/x.yml", b"data/localities/a/finance.yml", b"data/run.sh", b"data/x.jsonl",
                                  b"data/xchanges.jsonl", b"data/changes.jsonl.sh", b"data/.hidden.json",
                                  b"data/a/../facts.json", b"data//facts.json", b"data/facts.json\n", b"data/f\xc3\xa9.json",
                                  b"config/names.yml", b"data/x.JSON"])
def test_other_names_are_refused(path):
    assert data_shape.problems(_listing(path))


@pytest.mark.parametrize("head", [b"100755 blob " + b"a" * 40 + b"\t", b"120000 blob " + b"a" * 40 + b"\t",
                                  b"160000 commit " + b"a" * 40 + b"\t", b"100644 blob " + b"A" * 40 + b"\t"])
def test_only_regular_files_pass(head):
    assert data_shape.problems(_listing(b"data/facts.json", head=head))


@pytest.mark.parametrize("name", data_shape.CURATED_NAMES)
@pytest.mark.parametrize("folder", [b"data/", b"data/localities/clarksville-tn/"])
def test_curated_names_are_refused_at_any_depth(name, folder):
    found = data_shape.problems(_listing(b"data/facts.json", folder + name.encode()))
    assert len(found) == 1 and found[0].startswith("curated input in data/")


@pytest.mark.parametrize("path,why", [
    (b"data/maps/manifest.json", "map manifest in data/ (it belongs in config/maps/)"),
    (b"data/maps/x/changes.jsonl", "map manifest in data/ (it belongs in config/maps/)"),
    (b"data/localities/x/transcripts/a.json", "transcript in data/"),
    (b"data/localities/clarksville-tn/transcripts/index.json", "transcript in data/"),
    (b"data/transcripts/a.json", "transcript in data/"),
    (b"data/a/transcripts/b/c.json", "transcript in data/")])
def test_config_owned_inputs_are_refused_in_data(path, why):
    """I-in (ADR 0011 decision 2a, rows MP, TR and T): the map manifest and the transcripts live in config/; D refuses
    them at any depth, shown safely like the others."""
    found = data_shape.problems(_listing(b"data/facts.json", path))
    assert len(found) == 1 and found[0].startswith(why) and found[0].endswith(path.decode())


@pytest.mark.parametrize("folder", [b"data/", b"data/localities/clarksville-tn/", b"data/a/b/c/"])
def test_fin_books_accepted_is_refused_at_any_depth(folder):
    assert "fin-books-accepted.yml" in data_shape.CURATED_NAMES
    found = data_shape.problems(_listing(b"data/facts.json", folder + b"fin-books-accepted.yml"))
    assert len(found) == 1 and found[0].startswith("curated input in data/")


def test_a_config_owned_name_is_shown_without_raw_bytes():
    found = data_shape.problems(_listing(b"data/localities/\x1b[2Jx/transcripts/a.json"))
    assert len(found) == 1 and found[0].startswith("transcript in data/")
    assert all(0x20 <= ord(c) <= 0x7E for c in found[0])


def test_an_empty_data_tree_is_refused():
    assert data_shape.problems(b"") == ["data/ holds no file"]


def test_refused_names_are_shown_without_raw_bytes():
    found = data_shape.problems(_listing(b"data/\x1b[31mx.sh"))
    assert found and all(0x20 <= ord(c) <= 0x7E for c in found[0])


def test_cli_exit_codes(tmp_path, capsys):
    good, bad = tmp_path / "good", tmp_path / "bad"
    good.write_bytes(_listing(b"data/facts.json"))
    bad.write_bytes(_listing(b"data/facts.json", b"data/corrections-log.json"))
    assert data_shape.main([str(good)]) == 0
    assert data_shape.main([str(bad)]) == 1
    assert "corrections-log.json" in capsys.readouterr().out
    assert data_shape.main([str(tmp_path / "missing")]) == 2
    assert data_shape.main([]) == 2


def test_every_curated_input_is_in_config_and_none_in_data():
    for name in data_shape.CURATED_NAMES:
        assert (data_shape.CONFIG / name).is_file(), name
        assert not list((ROOT / "data").rglob(name)), name


def test_readers_take_curated_inputs_from_config(monkeypatch):
    config = ROOT / "config"
    assert names.NAMES == config / "names.yml"
    assert facts.PROCEDURAL == config / "procedural-titles.yml"
    assert views.CORRECTIONS_LOG == config / "corrections-log.json"
    seen = []
    real_is_file = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: seen.append(p) or real_is_file(p))
    site_checks.corrections_log_urls()
    assert seen == [config / "corrections-log.json"]


def test_curated_inputs_still_load():
    assert names.load_roster()
    assert facts.load_procedural()
    assert isinstance(views.corrections_log(), list)


@pytest.fixture(scope="module")
def pfc_validator():
    """The schema as collector/reviewed_lists.py applies it: with the format checker (listed_on is a real day)."""
    Draft202012Validator.check_schema(json.loads(PFC_SCHEMA.read_text(encoding="utf-8")))
    return reviewed_lists.validator(reviewed_lists.PUBLISHED_FACT_CHANGES)


def test_published_fact_changes_is_an_empty_valid_list(pfc_validator):
    data = yaml.safe_load(PFC.read_text(encoding="utf-8"))
    assert data == []
    assert list(pfc_validator.iter_errors(data)) == []
    assert reviewed_lists.load(reviewed_lists.PUBLISHED_FACT_CHANGES) == []


GOOD = {"fact_id": "rc-09962951-p101-0", "change": "changed", "listed_on": "2026-11-18",
        "reason": "The county corrected the vote in its amended minutes."}


@pytest.mark.parametrize("entry", [GOOD, {**GOOD, "change": "removed"},
                                   {**GOOD, "source_url": "https://www.mcgtn.org/minutes.pdf"}])
def test_published_fact_change_entries_pass(pfc_validator, entry):
    assert list(pfc_validator.iter_errors([entry])) == []


@pytest.mark.parametrize("entry", [
    {k: v for k, v in GOOD.items() if k != "fact_id"}, {k: v for k, v in GOOD.items() if k != "reason"},
    {k: v for k, v in GOOD.items() if k != "listed_on"}, {k: v for k, v in GOOD.items() if k != "change"},
    {**GOOD, "change": "added"}, {**GOOD, "fact_id": ""}, {**GOOD, "fact_id": "rc 1"}, {**GOOD, "reason": "  "},
    {**GOOD, "listed_on": "18 Nov 2026"}, {**GOOD, "listed_on": "2026-02-30"}, {**GOOD, "listed_on": "2026-13-01"},
    {**GOOD, "listed_on": "２０２６-11-18"}, {**GOOD, "source_url": "http://example.org/x"},
    {**GOOD, "allow_shrink": True}, "rc-09962951-p101-0"])
def test_published_fact_change_entries_refused(pfc_validator, entry):
    assert list(pfc_validator.iter_errors([entry]))


def test_published_fact_changes_must_be_a_list(pfc_validator):
    assert list(pfc_validator.iter_errors({"changes": []}))


def test_a_fact_listed_twice_is_refused(tmp_path):
    """pfc-schema/duplicate-fact-id: one entry per fact; a second entry for the same fact_id (even with another change
    or reason) is refused, and so is an unreal day, both naming the entry index, never a value."""
    twice = [GOOD, {**GOOD, "change": "removed", "reason": "Another reason."}]
    assert reviewed_lists.problems(reviewed_lists.PUBLISHED_FACT_CHANGES, twice) == [
        "entry 1: lists the same fact_id as entry 0"]
    assert reviewed_lists.problems(reviewed_lists.PUBLISHED_FACT_CHANGES,
                                   [GOOD, {**GOOD, "fact_id": "rc-09962951-p101-1"}]) == []
    f = tmp_path / "published-fact-changes.yml"
    f.write_text(yaml.safe_dump(twice), encoding="utf-8")
    with pytest.raises(reviewed_lists.ReviewedListError, match="entry 1: lists the same fact_id as entry 0"):
        reviewed_lists.load(reviewed_lists.PUBLISHED_FACT_CHANGES, path=f)
    f.write_text(yaml.safe_dump([{**GOOD, "listed_on": "2026-02-30"}]), encoding="utf-8")
    with pytest.raises(reviewed_lists.ReviewedListError, match="entry 0/listed_on: format check failed") as e:
        reviewed_lists.load(reviewed_lists.PUBLISHED_FACT_CHANGES, path=f)
    assert "2026-02-30" not in str(e.value)
    f.write_text("- fact_id: x\n  change: changed\n  listed_on: 2026-11-18\n  reason: r\n", encoding="utf-8")
    with pytest.raises(reviewed_lists.ReviewedListError, match="listed_on: type check failed"):   # unquoted: a date
        reviewed_lists.load(reviewed_lists.PUBLISHED_FACT_CHANGES, path=f)
