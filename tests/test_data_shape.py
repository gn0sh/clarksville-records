"""B1 (docs/tasks/data-off-main.md, rows D and CFG): data/ holds collector output only (I-data'', SHAPE''), the
curated inputs live in config/ and every reader takes them from there, and config/published-fact-changes.yml is a
valid, empty list."""
import json
import subprocess
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from collector import data_shape, facts, names
from qa import site_checks
from sitegen import views

ROOT = Path(__file__).resolve().parent.parent
PFC = ROOT / "config" / "published-fact-changes.yml"
PFC_SCHEMA = ROOT / "schema" / "published-fact-changes.schema.json"
BLOB = b"100644 blob " + b"0123456789abcdef0123" * 2 + b"\t"


def _listing(*paths: bytes, head: bytes = BLOB) -> bytes:
    return b"".join(head + p + b"\0" for p in paths)


def test_tracked_data_holds_only_collector_output():
    """I-data'' on the committed tree: every `git ls-tree -r -z HEAD -- data` entry fits SHAPE'' and none is curated."""
    out = subprocess.run(["git", "ls-tree", "-r", "-z", "HEAD", "--", "data"], cwd=ROOT, capture_output=True,
                         check=True).stdout
    assert data_shape.problems(out) == []


def test_shape_bash_line_is_what_bash_gives_grep():
    """SHAPE_ERE is byte for byte what bash makes of $'SHAPE_BASH', so B2 can paste SHAPE_BASH into the workflow."""
    made = subprocess.run(["bash", "-c", "SHAPE=$'" + data_shape.SHAPE_BASH + "'\nprintf %s \"$SHAPE\""],
                          capture_output=True, check=True).stdout
    assert made == data_shape.SHAPE_ERE


@pytest.mark.parametrize("path", [b"data/facts.json", b"data/changes.jsonl", b"data/localities/clarksville-tn/wards.json",
                                  b"data/localities/clarksville-tn/transcripts/2026-01-06-executive.json",
                                  b"data/county-agendas/changes.jsonl", b"data/a_b/x-1.v2.json"])
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
    schema = json.loads(PFC_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_published_fact_changes_is_an_empty_valid_list(pfc_validator):
    data = yaml.safe_load(PFC.read_text(encoding="utf-8"))
    assert data == []
    assert list(pfc_validator.iter_errors(data)) == []


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
    {**GOOD, "listed_on": "18 Nov 2026"}, {**GOOD, "source_url": "http://example.org/x"},
    {**GOOD, "allow_shrink": True}, "rc-09962951-p101-0"])
def test_published_fact_change_entries_refused(pfc_validator, entry):
    assert list(pfc_validator.iter_errors([entry]))


def test_published_fact_changes_must_be_a_list(pfc_validator):
    assert list(pfc_validator.iter_errors({"changes": []}))
