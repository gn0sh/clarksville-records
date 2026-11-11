"""Limits invariant rule 3, the shrink guard (docs/architecture/pipeline-limits-invariant.md "Rule 3: the shrink guard",
G1-G4; problem key pipeline/shrink-guard-freezes-all): per source document and every meeting in it, by sha256; a kept
document is a warning (exit 7), never a freeze of every other source."""
import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import collector.__main__ as M
from collector import rpc

ROOT = Path(__file__).resolve().parents[2]
WF = yaml.safe_load((ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8"))
STEPS = {s.get("name"): s for s in WF["jobs"]["update"]["steps"]}
COLLECT = STEPS["Collect (polite fetch, parse, verify)"]
KEPT_ISSUE = STEPS["Open or update the county kept-meetings issue"]
RPC_ISSUE = STEPS["Open or update the RPC issue"]
CITY_LINE = "python -m collector city run; city=$?"
COUNTY_LINE = 'python -m collector run "${shrink[@]}"; county=$?'
BOOK = "src-7325525d58ca"                       # the committed five-minutes book with two meetings


def committed():
    return json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))


def of_source(facts, sid):
    """Every record of one source document, per list (the guard's unit)."""
    return {k: [r for r in facts[k] if r.get("source_id") == sid] for k in ("meetings", "roll_calls", "motions",
                                                                            "item_events")} | {
        "sources": [s for s in facts["sources"] if s["id"] == sid]}


def rehash(facts, sid):
    """The county posted new bytes for `sid`: a new sha256, so a new source id and new record ids (collector/facts.py
    id scheme), same meetings. Only the first 8 hex digits change, so a text replace is exact."""
    old8 = sid[4:12]
    new8 = "f" * 8 if old8 != "f" * 8 else "e" * 8
    text = json.dumps(facts)
    assert new8 not in text
    return json.loads(text.replace(old8, new8)), f"src-{new8}{sid[12:]}"


def one_meeting_source(facts):
    n = {}
    for m in facts["meetings"]:
        n[m["source_id"]] = n.get(m["source_id"], 0) + 1
    return next(s for s, c in sorted(n.items()) if c == 1 and any(
        r["source_id"] == s and r["verification"]["status"] == "verified" for r in facts["roll_calls"]))


def unverify(facts, sid, n=1):
    """A limit trip on `sid`: n of its verified roll calls lose a check (status and checks agree, as verify needs)."""
    rcs = [r for r in facts["roll_calls"] if r["source_id"] == sid and r["verification"]["status"] == "verified"]
    for r in rcs[:n]:
        r["verification"]["status"] = "unverified"
        r["verification"]["checks"].append({"check": "ocr_agrees", "ok": False, "detail": "limit tripped (test)"})
    return [r["id"] for r in rcs[:n]]


def gain(facts, avoid=(BOOK,)):
    """Another document's real change that is not a downgrade (never guarded): an unverified roll call verified."""
    r = next(r for r in facts["roll_calls"] if r["source_id"] not in avoid and r["verification"]["status"] != "verified")
    r["verification"] = {"status": "verified", "checks": [dict(c, ok=True) for c in r["verification"]["checks"]]}
    return r["source_id"], r["id"]


@pytest.fixture
def county(tmp_path, monkeypatch):
    """An online `collector run` with the committed facts on disk and every other step replaced: the build returns
    state['new'], finance/agendas/RPC/site/export record that they ran and what they saw."""
    import collector.export
    import sitegen.build
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(M.dumps(committed()), encoding="utf-8")
    report = {"gates": {"roll_calls": 1, "verified": 1, "verified_rate": 1.0, "held_back": 0,
                        "held_back_source_error": 0, "verified_rate_gate": {"min": 0.9, "pass": True},
                        "g4": {"status": "pass", "uniform_share": 0.0, "flagged": []}}, "pass": True}
    state = {"new": committed(), "report": report, "rpc": 0, "ran": [], "site_facts": None, "export_facts": None}

    class B:
        unresolved = {}
        source_errors = set()

    def build(store, log, use_ocr=True):
        log["parsed"] = 1
        rep = state["report"] if state["report"] is not None else M.gate_report(state["new"], set(), log)
        return copy.deepcopy(state["new"]), rep, B()

    def finance(store, log, offline, **kw):
        state["ran"].append("finance")
        return 0

    def run_rpc(log, offline, fetcher=None, allow_shrink=False):
        state["ran"].append(("rpc", allow_shrink))
        log["rpc"] = {"exit": state["rpc"], "status": "x"}
        return state["rpc"]

    def site(facts_path_arg, out, **kw):
        state["ran"].append("site")
        state["site_facts"] = json.loads(Path(facts_path_arg).read_text(encoding="utf-8"))

    def export(facts, out, **kw):
        state["export_facts"] = facts
        return []
    for name, value in (("FACTS", facts_path), ("BUILD", tmp_path / "build"), ("MANIFEST", tmp_path / "manifest.json"),
                        ("FINANCE", tmp_path / "finance.json"), ("cmd_build", build), ("run_finance", finance),
                        ("run_agendas", lambda log, offline, fetcher=None: state["ran"].append("agendas")),
                        ("run_rpc", run_rpc), ("cmd_fetch", lambda store, log, fetcher=None: None),
                        ("finance_fetcher", lambda: None), ("name_candidates", lambda b, roster: {}),
                        ("load_seat_rows", lambda: None)):
        monkeypatch.setattr(M, name, value)
    monkeypatch.setattr(sitegen.build, "build", site)
    monkeypatch.setattr(sitegen.build, "write_publish_manifest", lambda *a, **k: None)
    monkeypatch.setattr(collector.export, "export_site", export)
    state["path"] = facts_path
    state["log"] = lambda: json.loads((tmp_path / "build" / "run-log.json").read_text(encoding="utf-8"))
    return state


def collect(tmp_path, city=0, county=0, run_log=None, event="schedule", allow=""):
    """The Collect step's own script, the two collector calls replaced; returns (exit, outputs, county args)."""
    work = tmp_path / "collect"
    (work / "build").mkdir(parents=True, exist_ok=True)
    (work / "build" / "run-log.json").unlink(missing_ok=True)
    if run_log is not None:
        (work / "build" / "run-log.json").write_text(run_log, encoding="utf-8")
    args, out = tmp_path / "county-args", tmp_path / "gh-output"
    out.write_text("")
    script = COLLECT["run"].replace(CITY_LINE, f"city={city}").replace(
        COUNTY_LINE, f'printf "%s\\n" "${{shrink[@]}}" > "{args}"; county={county}')
    assert script != COLLECT["run"] and str(args) in script
    r = subprocess.run(["bash", "-c", script], cwd=work, capture_output=True, text=True,
                       env={**os.environ, "GITHUB_OUTPUT": str(out), "GITHUB_EVENT_NAME": event, "ALLOW_SHRINK": allow})
    outputs = dict(ln.split("=", 1) for ln in out.read_text().split())
    return r.returncode, outputs, args.read_text().split()


def issue_step(tmp_path, step, open_issue="", run_log=None):
    """A workflow issue step with a stub gh; returns (gh calls, bodies)."""
    if not shutil.which("jq"):
        pytest.skip("jq not installed")
    work, bindir = tmp_path / "work", tmp_path / "bin"
    (work / "build").mkdir(parents=True, exist_ok=True)
    bindir.mkdir(exist_ok=True)
    (work / "build" / "run-log.json").unlink(missing_ok=True)
    if run_log is not None:
        (work / "build" / "run-log.json").write_text(run_log, encoding="utf-8")
    calls, bodies = tmp_path / "gh-calls", tmp_path / "bodies"
    for f in (calls, bodies):
        f.unlink(missing_ok=True)
    gh = bindir / "gh"
    gh.write_text("#!/bin/bash\n"
                  f'echo "$@" >> "{calls}"\n'
                  f'if [ "$2" = list ]; then echo "{open_issue}"; fi\n'
                  'for ((i=1; i<=$#; i++)); do j=$((i+1)); '
                  f'if [ "${{!i}}" = --body-file ]; then cat "${{!j}}" >> "{bodies}"; fi; done\n')
    gh.chmod(0o755)
    env = {**os.environ, **{k: v for k, v in step["env"].items() if "${{" not in str(v)},
           "PATH": f"{bindir}:{os.environ['PATH']}", "RUNNER_TEMP": str(tmp_path), "GITHUB_SERVER_URL": "https://x",
           "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "1"}
    subprocess.run(["bash", "-c", step["run"]], cwd=work, env=env, check=True)
    return calls.read_text().splitlines(), bodies.read_text()


# ------------------------------------------------------------------ G1: scope, per source document, by sha256
@pytest.mark.parametrize("drop", [True, False])
def test_guard_correction_new_sha_wins(county, capsys, drop):
    """G1 (b): the same meeting under a new sha256 is a correction: the new reading is written and listed; exit 7
    when its verified count fell, 0 when it held."""
    sid = one_meeting_source(committed())
    new, new_sid = rehash(committed(), sid)
    lowered = unverify(new, new_sid) if drop else []
    county["new"] = new
    code = M.main(["run"])
    written = json.loads(county["path"].read_text())
    assert written == new and not of_source(written, sid)["meetings"]              # the new reading wins
    (c,) = county["log"]()["corrections"]
    n_old = sum(r["source_id"] == sid and r["verification"]["status"] == "verified" for r in committed()["roll_calls"])
    assert c["source_id"] == sid and c["new_source_ids"] == [new_sid]
    assert c["verified"] == [n_old, n_old - len(lowered)] and county["log"]()["kept_meetings"] == []
    assert code == (M.KEPT if drop else 0)
    out = capsys.readouterr().out
    assert (f"collector: correction: {', '.join(c['meeting_ids'])} source {sid[4:12]} -> {new_sid[4:12]}, "
            f"verified {n_old} -> {n_old - len(lowered)}") in out


def test_guard_transient_loss_keeps_only_that_document(county):
    """G1 (a), G2.1: same sha256, one roll call unverified: that document's records (both meetings of a two-meeting
    book) are byte-identical to the committed ones, and another document's change is written."""
    old = committed()
    new = copy.deepcopy(old)
    (lost,) = unverify(new, BOOK)
    other, changed = gain(new)                               # another document's change: published
    county["new"] = new
    assert M.main(["run"]) == M.KEPT
    written = json.loads(county["path"].read_text())
    book = of_source(old, BOOK)
    assert len(book["meetings"]) == 2 and of_source(written, BOOK) == book
    assert [M.dumps(r) for k in book for r in of_source(written, BOOK)[k]] == [M.dumps(r) for k in book for r in book[k]]
    assert of_source(written, other) == of_source(new, other) != of_source(old, other)
    assert next(r for r in written["roll_calls"] if r["id"] == changed)["verification"]["status"] == "verified"
    (k,) = county["log"]()["kept_meetings"]
    assert k["source_id"] == BOOK and k["ids"] == [lost] and k["meeting_ids"] == sorted(m["id"] for m in book["meetings"])
    # sorted as Builder.facts sorts them
    assert all(written[k] == sorted(written[k], key=lambda x: x["id"]) for k in book)


@pytest.mark.parametrize("why", ["parse failed", "not in the store"])
def test_guard_missing_source_kept(county, why):
    """G1 (c): the committed document is absent from the result (it failed to parse, or its bytes are not in the
    store) and its meetings with it: transient, kept as committed."""
    old = committed()
    sid = one_meeting_source(old)
    new = copy.deepcopy(old)
    for k in ("meetings", "roll_calls", "motions", "item_events"):
        new[k] = [r for r in new[k] if r["source_id"] != sid]
    new["sources"] = [s for s in new["sources"] if s["id"] != sid]
    county["new"] = new
    assert M.main(["run"]) == M.KEPT
    assert json.loads(county["path"].read_text()) == old
    (k,) = county["log"]()["kept_meetings"]
    assert k["source_id"] == sid and "not in the result" in k["reason"]


def test_guard_other_sources_still_publish(county, tmp_path, capsys):
    """I-2: the guard firing is a warning: finance, agendas and RPC run, the site and export are built from the merged
    facts, the exit is 7 not 3, and the Collect step passes (so city, county, finance and RPC files upload)."""
    new = copy.deepcopy(committed())
    unverify(new, BOOK)
    county["new"] = new
    assert M.main(["run"]) == M.KEPT
    merged = json.loads(county["path"].read_text())
    assert county["ran"] == ["finance", "agendas", ("rpc", False), "site"]
    assert county["site_facts"] == merged and county["export_facts"] == merged and merged == committed()
    assert "--body" in capsys.readouterr().out                       # the issue it would open (D1)
    code, outputs, _ = collect(tmp_path, county=M.KEPT, run_log=json.dumps({"rpc": {"exit": 0}}))
    assert code == 0 and outputs == {"city": "0", "county": "0", "kept": "yes", "rpc": "ok"}
    assert STEPS["Upload refreshed data"]["if"].startswith("success() && ")


def test_guard_gates_run_on_merged_facts(county):
    """G2.3: the new result fails the verified-rate gate (a limit tripped on a few big documents); the merged facts,
    with those documents kept, pass it: exit 7, not 3, and build/report.json holds the merged gates."""
    old = committed()
    new = copy.deepcopy(old)
    by_doc = {}
    for r in old["roll_calls"]:
        by_doc[r["source_id"]] = by_doc.get(r["source_id"], 0) + (r["verification"]["status"] == "verified")
    for sid, _ in sorted(by_doc.items(), key=lambda kv: -kv[1]):
        unverify(new, sid, n=10_000)
        if not M.gate_report(new, set(), {})["pass"]:
            break
    county["new"], county["report"] = new, None                        # the build's own report, on the new result
    assert not M.gate_report(new, set(), {})["pass"]
    assert M.main(["run"]) == M.KEPT
    report = json.loads((county["path"].parent / "build" / "report.json").read_text())
    assert report["pass"] and report["gates"]["verified_rate_gate"]["pass"]
    assert report["gates"]["verified"] == sum(r["verification"]["status"] == "verified" for r in old["roll_calls"])
    assert county["log"]()["held_back"] == report["gates"]["held_back"]


def test_guard_unit_assertion():
    """G1: a roll call whose source_id is not its meeting's (or a meeting with no source) means the unit stopped
    holding: the guard raises with a clear message instead of keeping the wrong records."""
    old = committed()
    new = copy.deepcopy(old)
    rc = new["roll_calls"][0]
    rc["source_id"] = next(s["id"] for s in new["sources"] if s["id"] != rc["source_id"])
    with pytest.raises(M.GuardUnitError, match=r"the unit \(one source document and every meeting in it\) does not "
                                               r"hold in the new result: 1 records, e\.g\. roll_calls " + rc["id"]):
        M.shrink_guard(new, old)
    new = copy.deepcopy(old)
    del new["meetings"][0]["source_id"]
    with pytest.raises(M.GuardUnitError, match="has no source_id"):
        M.shrink_guard(new, old)
    with pytest.raises(M.GuardUnitError, match="facts.json"):                        # the committed file too
        M.shrink_guard(old, new)
    assert M.shrink_guard(old, old) == {"kept": [], "corrections": []}


# ------------------------------------------------------------------ G2.4-G2.6: exit 7, run-log, workflow, issue
def test_kept_exit_7_and_issue(county, tmp_path):
    new = copy.deepcopy(committed())
    (lost,) = unverify(new, BOOK)
    county["new"] = new
    assert M.main(["run"]) == M.KEPT
    run_log = county["log"]()
    assert run_log["kept_meetings"][0]["ids"] == [lost] and "kept_facts" not in run_log
    code, outputs, _ = collect(tmp_path, county=M.KEPT, run_log=json.dumps(run_log))
    assert code == 0 and outputs["kept"] == "yes" and outputs["county"] == "0" and outputs["rpc"] == "ok"
    assert KEPT_ISSUE["if"] == "always() && steps.collect.outputs.kept == 'yes'"
    assert KEPT_ISSUE["env"]["KEPT_TITLE"] == "Daily update: county meetings kept"
    assert "${{" not in KEPT_ISSUE["run"] and "--body-file" in KEPT_ISSUE["run"] and "head -c" in KEPT_ISSUE["run"]
    run_log["kept_meetings"][0]["reason"] += " ```\n# injected heading\n```"           # text from a document
    calls, body = issue_step(tmp_path, KEPT_ISSUE, run_log=json.dumps(run_log))
    assert calls[0].startswith("issue list") and calls[1].startswith("issue create") and len(calls) == 2
    assert lost in body and BOOK in body and body.count("```") == 2                    # backticks stripped
    calls, body = issue_step(tmp_path, KEPT_ISSUE, open_issue="17", run_log=None)
    assert calls[1].startswith("issue comment 17") and "unknown" in body              # no run-log: unknown


@pytest.mark.parametrize("rpc_exit,rpc_out", [(5, "failed"), (rpc.STEP_FETCH, "failed"), (rpc.STEP_FILLING, "filling"),
                                              (None, "failed"), ("unreadable", "failed")])
def test_kept_with_rpc_failed_opens_both_issues(tmp_path, rpc_exit, rpc_out):
    """G2.6: one exit code cannot carry both; under 7 the RPC outcome is read from run-log.json .rpc.exit (unreadable
    counts as failed), so an RPC failure still opens its own issue beside the kept-meetings one."""
    run_log = "{not json" if rpc_exit == "unreadable" else json.dumps({"rpc": {"exit": rpc_exit}, "kept_meetings": []})
    code, outputs, _ = collect(tmp_path, county=M.KEPT, run_log=run_log)
    assert code == 0 and outputs["kept"] == "yes" and outputs["rpc"] == rpc_out
    assert RPC_ISSUE["if"] == "always() && steps.collect.outputs.rpc == 'failed'"     # fires on 7 with rpc=failed
    code, outputs, _ = collect(tmp_path, county=M.KEPT, run_log=None)                 # no run-log.json at all
    assert code == 0 and outputs["rpc"] == "failed"


def test_allow_shrink_dispatch_only(county, tmp_path):
    """G3: the input defaults to false; --allow-shrink reaches `collector run` only on workflow_dispatch with exactly
    true, never on schedule, never to the city run; with it the new result wins and the exit is 0."""
    on = WF.get("on") or WF[True]
    inp = on["workflow_dispatch"]["inputs"]["allow_shrink"]
    assert inp["type"] == "boolean" and inp["default"] is False and "manual runs only" in inp["description"]
    assert "allow_shrink" not in str(on.get("schedule"))
    assert COLLECT["env"]["ALLOW_SHRINK"] == "${{ inputs.allow_shrink }}" and "${{" not in COLLECT["run"]
    assert [ln.strip() for ln in COLLECT["run"].splitlines() if "collector city run" in ln] == [CITY_LINE]   # no guard
    for event, allow, passed in (("schedule", "true", False), ("schedule", "", False),
                                 ("workflow_dispatch", "false", False), ("workflow_dispatch", "", False),
                                 ("workflow_dispatch", "TRUE", False), ("workflow_dispatch", "true; rm -rf /", False),
                                 ("workflow_dispatch", "true", True)):
        code, _, args = collect(tmp_path, event=event, allow=allow)
        assert code == 0 and args == (["--allow-shrink"] if passed else []), (event, allow)
    push_if = WF["jobs"]["push"]["if"]
    assert "github.ref == 'refs/heads/main'" in push_if and "allow_shrink" not in push_if   # commits from main only
    new = copy.deepcopy(committed())
    unverify(new, BOOK)
    county["new"] = new
    assert M.main(["run", "--allow-shrink"]) == 0
    assert json.loads(county["path"].read_text()) == new and county["ran"][2] == ("rpc", True)
    assert county["log"]()["kept_meetings"] == [] and county["log"]()["allowed_shrink"][0]["source_id"] == BOOK


def test_repeated_trip_day_n_plus_1_not_frozen(county, tmp_path):
    """The bug: one repeated trip froze every source, every day. Now: two runs in a row with the same trip both exit
    7, the other documents' new data is published on day 1 and stays, facts.json is byte-identical after day 2 (no
    churn commit), and the kept-meetings issue is commented on day 2, not opened again."""
    old = committed()
    new = copy.deepcopy(old)
    unverify(new, BOOK)
    _, changed = gain(new)
    county["new"] = new
    assert M.main(["run"]) == M.KEPT
    day1 = county["path"].read_bytes()
    assert county["log"]()["facts_changed"] is True
    assert next(r for r in json.loads(day1)["roll_calls"] if r["id"] == changed)["verification"]["status"] == "verified"
    calls1, _ = issue_step(tmp_path, KEPT_ISSUE, run_log=json.dumps(county["log"]()))
    assert M.main(["run"]) == M.KEPT
    assert county["path"].read_bytes() == day1 and county["log"]()["facts_changed"] is False
    assert county["ran"].count("site") == 2
    calls2, _ = issue_step(tmp_path, KEPT_ISSUE, open_issue="17", run_log=json.dumps(county["log"]()))
    assert calls1[1].startswith("issue create") and calls2[1].startswith("issue comment 17")


# ------------------------------------------------------------------ G4: RPC
def test_rpc_motion_correction_not_a_loss():
    """G4 (i): an RPC motion confirmed in the committed record whose meeting's minutes source_id changed (new bytes)
    is a correction, not a loss; the same minutes losing it is still refused; hold_motions still skips the check."""
    def rec(minutes_sid, confirmed):
        return {"meetings": [{"id": "2026-05-26-regular", "documents": [
                    {"kind": "agenda", "source_id": "src-aaaaaaaaaaaa"}, {"kind": "minutes", "source_id": minutes_sid}]}],
                "motions": [{"id": "2026-05-26-regular-motion-1", "meeting_id": "2026-05-26-regular",
                             "source_id": minutes_sid, "confirmed": confirmed}]}
    old = rec("src-111111111111", True)
    corrected = rec("src-222222222222", False)
    assert rpc.shrink_reason(old, corrected) is None
    assert rpc.minutes_corrections(old, corrected) == [{
        "meeting_id": "2026-05-26-regular", "source_ids": ["src-111111111111"], "new_source_ids": ["src-222222222222"],
        "confirmed": [1, 0]}]
    lost = rec("src-111111111111", False)
    assert "2026-05-26-regular-motion-1" in rpc.shrink_reason(old, lost)
    assert rpc.minutes_corrections(old, lost) == []
    assert rpc.shrink_reason(old, lost, hold_motions=True) is None
    assert rpc.shrink_reason(old, lost, allow_shrink=True) is None
