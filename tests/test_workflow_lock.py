"""The daily-update workflow ships locked: its deploy job runs only when RECORDS_DEPLOY_ENABLED is 'true' (CEO hard
stop 1), nothing else may publish, and no secrets are used."""
import itertools
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8")
WF = yaml.safe_load(TEXT)


LOCK = "vars.RECORDS_DEPLOY_ENABLED == 'true' && github.ref == 'refs/heads/main'"
# pipeline/deploy-independent-of-push: the lock, then the results of the two jobs deploy needs. A status function
# (!cancelled()) replaces GitHub's implicit success(), which would also skip deploy on the rebuild-only run, where
# push is skipped by design (the runbook's rollback path).
DEPLOY_IF = (LOCK + " && !cancelled() && needs.update.result == 'success' && (needs.push.result == 'success' || "
             "(needs.push.result == 'skipped' && github.event_name == 'workflow_dispatch' && !inputs.collect))")


def _deploy_if() -> str:
    return " ".join(WF["jobs"]["deploy"]["if"].split())


def test_deploy_job_is_locked():
    cond = _deploy_if()
    assert cond == DEPLOY_IF
    assert cond.startswith(LOCK + " && ")                                    # the lock stays the first condition
    assert WF["jobs"]["deploy"]["needs"] == ["update", "push"]


def _holds(expr: str, ctx: dict) -> bool:
    """A GitHub Actions `if` of the small shape used here (==, &&, ||, !, parentheses, 'strings', contexts, cancelled())
    evaluated over a made-up context. Unknown names raise KeyError, so the table below must cover every name."""
    py = re.sub(r"cancelled\(\)", "ctx['cancelled']", expr)
    py = re.sub(r"\b(?:vars|github|needs|inputs)(?:\.\w+)+", lambda m: f"ctx[{m.group(0)!r}]", py)
    py = py.replace("&&", " and ").replace("||", " or ")
    py = re.sub(r"!(?!=)", " not ", py)
    return bool(eval(py, {"__builtins__": {}}, {"ctx": ctx}))               # the workflow file is ours, not input


def _ctx(**over) -> dict:
    """A scheduled run on main, deploy enabled, both needed jobs green."""
    ctx = {"vars.RECORDS_DEPLOY_ENABLED": "true", "github.ref": "refs/heads/main", "github.event_name": "schedule",
           "inputs.collect": None, "needs.update.result": "success", "needs.push.result": "success",
           "cancelled": False}
    return {**ctx, **{k.replace("__", "."): v for k, v in over.items()}}


def test_deploy_needs_a_successful_push():
    """pipeline/deploy-independent-of-push: no deploy when the push job failed (or was cancelled, or was skipped on a
    collecting run): the site must never go live from data that is not on main."""
    cond = _deploy_if()
    assert _holds(cond, _ctx())                                                           # the daily run
    for result in ("failure", "cancelled", "skipped"):
        assert not _holds(cond, _ctx(needs__push__result=result)), result
        assert not _holds(cond, _ctx(needs__push__result=result, github__event_name="workflow_dispatch",
                                     inputs__collect=True)), result
    for result in ("failure", "cancelled", "skipped"):
        assert not _holds(cond, _ctx(needs__update__result=result, needs__push__result="skipped")), result
    assert not _holds(cond, _ctx(cancelled=True))


def test_rebuild_only_run_still_deploys_without_a_push():
    """collect = false (the runbook's rollback and redeploy path) has no data to commit: push is skipped by its own
    `if`, and deploy runs from the committed data. A failed push never counts, whatever the inputs say."""
    cond = _deploy_if()
    rebuild = dict(github__event_name="workflow_dispatch", inputs__collect=False, needs__push__result="skipped")
    assert _holds(cond, _ctx(**rebuild))
    assert not _holds(cond, _ctx(**{**rebuild, "needs__push__result": "failure"}))
    assert not _holds(cond, _ctx(**{**rebuild, "needs__update__result": "failure"}))
    push_if = WF["jobs"]["push"]["if"]                    # the push job is skipped exactly when deploy allows 'skipped'
    assert not _holds(push_if, _ctx(**rebuild)) and _holds(push_if, _ctx())


def test_the_lock_and_main_only_hold_in_every_case():
    """Hard stop 1: whatever the job results and inputs, no deploy unless the variable is exactly 'true', on main."""
    cond = _deploy_if()
    results = ("success", "failure", "cancelled", "skipped")
    for var, ref in (("", "refs/heads/main"), ("false", "refs/heads/main"), ("True", "refs/heads/main"),
                     ("true", "refs/heads/other"), ("", "refs/heads/other")):
        for upd, push, event, collect, cancelled in itertools.product(
                results, results, ("schedule", "workflow_dispatch"), (None, True, False), (False, True)):
            ctx = _ctx(vars__RECORDS_DEPLOY_ENABLED=var, github__ref=ref, needs__update__result=upd,
                       needs__push__result=push, github__event_name=event, inputs__collect=collect,
                       cancelled=cancelled)
            assert not _holds(cond, ctx), ctx


def test_only_the_deploy_job_can_publish():
    assert "pages" not in (WF["jobs"]["update"]["permissions"] or {})
    assert "id-token" not in (WF["jobs"]["update"]["permissions"] or {})
    assert WF["jobs"]["deploy"]["permissions"] == {"pages": "write", "id-token": "write"}
    assert TEXT.count("actions/deploy-pages@") == 1
    assert WF["permissions"] == {}                       # least privilege: each job grants its own


def test_no_secrets_and_pinned_actions():
    assert "secrets." not in TEXT
    for line in TEXT.splitlines():
        if line.strip().startswith(("- uses:", "uses:")):
            ref = line.split("uses:")[1].split("#")[0].strip().split("@")[1]
            assert len(ref) == 40 and set(ref) <= set("0123456789abcdef"), line


def test_runs_daily_and_on_demand():
    on = WF.get("on") or WF[True]
    assert on["schedule"] and "workflow_dispatch" in on


def test_cname_in_build_output():
    assert (ROOT / "deploy" / "CNAME").read_text(encoding="utf-8").strip() == "daylight.gnoshcodes.com"
    assert "cp deploy/CNAME build/site/CNAME" in TEXT


def test_launch_overrides_are_read_from_the_environment(monkeypatch):
    import importlib

    from sitegen import config
    try:
        monkeypatch.setenv("RECORDS_SITE_URL", "https://daylight.gnoshcodes.com/")
        monkeypatch.setenv("RECORDS_BUILD_TARGET", "pages")
        importlib.reload(config)
        assert config.SITE["alerts"]["site_url"] == "https://daylight.gnoshcodes.com/"
        assert config.max_files() == 3000
    finally:
        monkeypatch.undo()
        importlib.reload(config)
    assert config.max_files() == 500 and config.SITE["alerts"]["site_url"] == ""


def test_untrusted_parse_job_has_no_write_token():
    """pipeline/token-exposure-untrusted-parse: the update job parses downloaded PDFs, so it gets no write access and
    no persisted token; only the small push job (which parses nothing) can write to the repository."""
    jobs = WF["jobs"]
    assert jobs["update"]["permissions"] == {"contents": "read", "issues": "write"}
    checkout = [s for s in jobs["update"]["steps"] if "actions/checkout@" in s.get("uses", "")]
    assert checkout and all(s["with"]["persist-credentials"] is False for s in checkout)
    writers = [n for n, j in jobs.items() if (j.get("permissions") or {}).get("contents") == "write"]
    assert writers == ["push"]
    assert jobs["push"]["needs"] == "update"
    assert "git push" not in "\n".join(s.get("run", "") for s in jobs["update"]["steps"])
    assert not any("python" in s.get("run", "") for s in jobs["push"]["steps"])      # parses nothing
    assert jobs["deploy"]["needs"] == ["update", "push"]


def _push_run_text():
    return "\n".join(s.get("run", "") for s in WF["jobs"]["push"]["steps"])


def test_push_commits_on_the_update_sha_then_rebases():
    """pipeline/push-reverts-concurrent-data: a concurrent data/ edit on main must conflict, never be reverted."""
    jobs = WF["jobs"]
    assert jobs["update"]["outputs"]["sha"] == "${{ steps.checkout.outputs.commit }}"
    assert any(s.get("id") == "checkout" and "actions/checkout@" in s["uses"] for s in jobs["update"]["steps"])
    checkout = [s for s in jobs["push"]["steps"] if "actions/checkout@" in s.get("uses", "")]
    assert len(checkout) == 1 and checkout[0]["with"]["ref"] == "${{ needs.update.outputs.sha }}"
    run = _push_run_text()
    assert run.index("git commit") < run.index("git pull --rebase origin main") < run.index("git push origin HEAD:main")
    assert "--force" not in run and "-f " not in run


def test_push_validates_the_artifact_before_staging():
    """pipeline/push-unvalidated-artifact: no symlinks, only tracked file types, 50 MB cap, checked before git add."""
    steps = WF["jobs"]["push"]["steps"]
    names = [s.get("name", "") for s in steps]
    validate = steps[names.index("Validate refreshed data")]["run"]
    assert "! -type f ! -type d" in validate                      # symlinks and special files
    assert "*.json|*.yml|*/changes.jsonl) ;;" in validate          # allowlist: what data/ tracks, and the change logs
    assert validate.count(";;") == 2                               # that list and the refusing default, nothing else
    assert "-size +50M" in validate
    assert names.index("Validate refreshed data") < names.index("Commit refreshed data to main")
    assert names.index("Download refreshed data") < names.index("Validate refreshed data")
    assert "git add" not in validate


def test_tracked_data_files_fit_the_allowlist():
    import subprocess
    files = subprocess.run(["git", "ls-files", "data"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    assert files and all(f.endswith((".json", ".yml")) or f.endswith("/changes.jsonl") for f in files)


def _validate(folder: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    """The push job's own "Validate refreshed data" script, run over `folder` standing for the downloaded artifact."""
    step = next(s for s in WF["jobs"]["push"]["steps"] if s.get("name") == "Validate refreshed data")
    runner = tmp_path / "runner"
    art = runner / "records-data"
    shutil.copytree(folder, art, symlinks=True)
    return subprocess.run(["bash", "-c", step["run"]], env={**os.environ, "RUNNER_TEMP": str(runner)},
                          capture_output=True, text=True)


def test_a_changed_document_passes_the_push_validation(tmp_path):
    """pipeline/changes-jsonl-rejected: when a document changes, collector/store.py appends to changes.jsonl beside the
    manifest. The push job must accept that data folder, or the change is never committed and repeats every day."""
    from collector.tests.test_fin_fetch import ARCHIVE, FIXTURE_HTML, _fin_fetch
    data = tmp_path / "data"            # stands for data/: manifest.json and changes.jsonl side by side
    data.mkdir()
    routes = {ARCHIVE: (200, FIXTURE_HTML, {"Content-Type": "text/html"})}
    _fin_fetch(data, routes)                                                   # day 1: first collection
    routes[ARCHIVE] = (200, FIXTURE_HTML.replace(b"MAY 4, 2026", b"MAY 5, 2026"), {"Content-Type": "text/html"})
    log, _, _, _ = _fin_fetch(data, routes)                                    # day 2: the county edits one row
    assert log["archive"]["status"] == "changed"
    shutil.rmtree(data / "store", ignore_errors=True)                          # the artifact excludes data/store
    for p in list(data.rglob("*.pdf")) + list(data.rglob("*.part")):
        p.unlink()
    assert (data / "changes.jsonl").is_file() and (data / "manifest.json").is_file()
    r = _validate(data, tmp_path)
    assert r.returncode == 0, "the push job refuses the refreshed data: " + r.stdout.replace(str(tmp_path), "<tmp>")


def test_every_change_log_the_collector_writes_passes(tmp_path):
    """Each Store writes changes.jsonl beside its own manifest (county, city, county agendas, RPC): all are allowed."""
    data = tmp_path / "data"
    for sub in ("", "localities/clarksville-tn", "county-agendas", "localities/clarksville-tn/rpc"):
        (data / sub).mkdir(parents=True, exist_ok=True)
        (data / sub / "manifest.json").write_text("[]\n")
        (data / sub / "changes.jsonl").write_text("{}\n")
    (data / "names.yml").write_text("[]\n")
    assert _validate(data, tmp_path).returncode == 0


@pytest.mark.parametrize("name", ["run.sh", "notes.jsonl", "changes.jsonl.sh", "x.pdf", "changes.jsonl/evil.py",
                                  "localities/a/audit.jsonl", "xchanges.jsonl", ".gitattributes"])
def test_other_file_types_are_still_refused(tmp_path, name):
    """The allowlist stays an allowlist: only *.json, *.yml and files named exactly changes.jsonl."""
    data = tmp_path / "data"
    (data / name).parent.mkdir(parents=True, exist_ok=True)
    (data / name).write_text("x\n")
    (data / "manifest.json").write_text("[]\n")
    r = _validate(data, tmp_path)
    assert r.returncode == 1 and "file type not allowed in data/" in r.stdout


def test_a_symlinked_change_log_is_still_refused(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "manifest.json").write_text("[]\n")
    (data / "changes.jsonl").symlink_to("/etc/passwd")
    r = _validate(data, tmp_path)
    assert r.returncode == 1 and "not a regular file or directory" in r.stdout


def test_push_failure_opens_an_issue():
    """pipeline/push-failure-silent."""
    push = WF["jobs"]["push"]
    assert push["permissions"] == {"contents": "write", "issues": "write"}
    last = push["steps"][-1]
    assert last["if"] == "failure()" and "Daily update failed" in last["run"] and "gh issue" in last["run"]
    runbook = (ROOT / "docs" / "ops" / "launch-runbook.md").read_text(encoding="utf-8")
    assert "A failure in `update` or `push` opens" in runbook
    assert "`deploy` needs both" in runbook               # pipeline/deploy-independent-of-push: the text is now true


def test_push_and_deploy_run_on_main_only():
    """pipeline/dispatch-non-main-ref: a manual run on another branch cannot commit to main or deploy."""
    assert "github.ref == 'refs/heads/main'" in WF["jobs"]["push"]["if"]
    assert "github.ref == 'refs/heads/main'" in WF["jobs"]["deploy"]["if"]
    assert "github.event_name == 'schedule' || inputs.collect" in WF["jobs"]["push"]["if"]
