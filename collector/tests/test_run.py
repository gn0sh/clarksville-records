"""CLI run: export holds no unverified fact, a re-run changes no committed file (AC4.5), exit codes 0/2/3."""
import copy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

import collector.__main__ as M
from collector.export import CSV_FILES, export
from collector.store import Store

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schema" / "facts.schema.json").read_text())


def public_schema():
    """The facts schema minus the raw OCR fields, which the public export drops (plus the motion's type_label)."""
    s = copy.deepcopy(SCHEMA)
    for k in ("motion", "person_ref", "attendance", "vote"):
        d = s["$defs"][k]
        d["required"] = [r for r in d["required"] if r not in ("text", "raw_name")]
    s["$defs"]["motion"]["properties"]["type_label"] = {"type": "string"}
    return s


def committed_facts():
    return json.loads((ROOT / "data" / "facts.json").read_text())


def test_export_contains_no_unverified_fact(tmp_path):
    facts = committed_facts()
    export(facts, tmp_path)
    out = json.loads((tmp_path / "data" / "facts.json").read_text())
    jsonschema.validate(out, public_schema())
    for key in ("roll_calls", "motions"):
        assert all(x["verification"]["status"] == "verified" for x in out[key])
    for m in out["meetings"]:
        if m["verification"]["status"] != "verified":
            assert m["attendance"] == []
    held = {x["id"] for k in ("roll_calls", "motions") for x in facts[k] if x["verification"]["status"] != "verified"}
    assert held, "the committed facts have held-back roll calls to test against"
    for name in CSV_FILES:
        text = (tmp_path / "data" / f"{name}.csv").read_text()
        assert not any(h in text for h in held), name
        header = text.splitlines()[0]
        if name not in ("officials", "sources"):
            assert all(c in header for c in ("source_url", "source_sha256", "page", "fetched_at")), name
    refs = {x["id"] for k in ("roll_calls", "motions") for x in out[k]}
    assert all(e["ref"] is None or e["ref"] in refs for e in out["item_events"])


def _digest(paths):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.exists()}


@pytest.mark.skipif(not all(Store().has_bytes(e["sha256"]) for e in Store().entries),
                    reason="the document store is empty in this checkout (run `python -m collector run` once)")
def test_second_offline_run_changes_no_committed_file():
    committed = [ROOT / "data" / "facts.json", ROOT / "data" / "manifest.json", ROOT / "data" / "changes.jsonl"]
    M.main(["run", "--offline"])
    before = _digest(committed)
    M.main(["run", "--offline"])
    assert _digest(committed) == before


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "FACTS", tmp_path / "facts.json")
    monkeypatch.setattr(M, "BUILD", tmp_path / "build")
    monkeypatch.setattr(M, "MANIFEST", tmp_path / "manifest.json")
    facts = committed_facts()
    report = {"gates": {"roll_calls": 1, "verified": 1, "verified_rate": 1.0, "held_back": 0,
                        "held_back_source_error": 0, "verified_rate_gate": {"min": 0.9, "pass": True},
                        "g4": {"status": "pass", "uniform_share": 0.0, "flagged": []}}, "pass": True}

    class B:
        unresolved = {}
    state = {"report": report, "fail": False}

    def fake_build(store, log, use_ocr=True):
        log["parsed"] = 1
        if state["fail"]:
            log["failures"].append({"stage": "parse", "error": "boom"})
        return facts, state["report"], B()
    monkeypatch.setattr(M, "cmd_build", fake_build)
    return state


@pytest.mark.parametrize("fail,gate_pass,code", [(False, True, 0), (True, True, 2), (False, False, 3)])
def test_exit_codes(sandbox, capsys, fail, gate_pass, code):
    sandbox["fail"] = fail
    sandbox["report"]["pass"] = gate_pass
    assert M.main(["run", "--offline"]) == code
    out = capsys.readouterr().out
    assert ("gh issue create --repo gn0sh/clarksville-records" in out) == (code != 0)


def test_discovery_block_is_a_logged_failure_not_a_crash(monkeypatch):
    from collector.fetch import HostBlocked

    def blocked(f):
        raise HostBlocked("dev2.montgomerytn.gov: HTTP 403 from the site")
    monkeypatch.setattr(M, "fetch_index", blocked)
    log = {"found": None, "new": [], "fetched": {}, "failures": []}

    class F:
        log = []
    M.cmd_fetch(Store(Path("/nonexistent/manifest.json")), log, fetcher=F())
    assert log["failures"][0]["stage"] == "discover" and "HostBlocked" in log["failures"][0]["error"]
