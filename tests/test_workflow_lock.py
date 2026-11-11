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


# Every `secrets.` use in the workflow: (job, step, where, env name, expression). Only the note job's two steps, only
# as env values, each the exact expression (never inside a `run:`, `with:` or `if:`).
ALLOWED_SECRETS = [
    ("note", "Mask the canary ids", "env", "CANARY_IDS", "${{ secrets.MORNING_NOTE_CANARY_IDS }}"),
    ("note", "Deliver the morning note", "env", "BUTTONDOWN_API_KEY", "${{ secrets.BUTTONDOWN_API_KEY }}"),
    ("note", "Deliver the morning note", "env", "MORNING_NOTE_CANARY_IDS",
     "${{ secrets.MORNING_NOTE_CANARY_IDS }}"),
]


def _secret_uses(wf) -> list:
    out = []

    def walk(job, step, where, value, key=None):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(job, step, where if where else k, v, k)
        elif isinstance(value, list):
            for v in value:
                walk(job, step, where, v, key)
        elif "secrets." in str(value):
            out.append((job, step, where, key, str(value).strip()))
    for top, v in wf.items():
        if top != "jobs":
            walk("-", "-", str(top), v)
    for jname, job in wf["jobs"].items():
        for k, v in job.items():
            if k != "steps":
                walk(jname, "-", k, v)
        for s in job.get("steps", []):
            for k, v in s.items():
                walk(jname, s.get("name"), k, v, k)
    return out


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
    assert _secret_uses(WF) == ALLOWED_SECRETS          # only the note job, only as one step's env
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


# ------------------------------------------------------------------ least privilege, every workflow in the repo
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_job_states_its_own_permissions(path):
    wf = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert wf.get("permissions") == {}, "top-level permissions must be {} so each job grants only its own"
    for name, job in wf["jobs"].items():
        assert isinstance(job.get("permissions"), dict), f"{path.name}: job {name} has no explicit permissions"
        assert "write-all" not in str(job["permissions"])


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_untrusted_triggers_and_no_echoed_credentials(path):
    text = path.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    on = wf.get("on") or wf[True]
    assert not set(on) & {"pull_request_target", "workflow_run", "pull_request", "issue_comment"}
    assert _secret_uses(wf) == (ALLOWED_SECRETS if path.name == "daily-update.yml" else [])
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(("echo", "printf", "run: echo", "run: printf")):
            assert not re.search(r"github\.token|GH_TOKEN|GITHUB_TOKEN|ACTIONS_\w*TOKEN", s), line


def test_a_hard_failure_never_reaches_main_and_the_exit_codes_are_documented():
    """A failed fetch never deletes data: on any hard exit code the Collect step fails, so the data artifact is not
    uploaded and the push job (which needs a successful update) never runs. Only the RPC step's own codes pass:
    county 6 (partial) and county 5 (RPC failed; its files are restored by the step, everything else publishes)."""
    steps = {s.get("name"): s for s in WF["jobs"]["update"]["steps"]}
    assert steps["Upload refreshed data"]["if"].startswith("success() && ")
    assert WF["jobs"]["push"]["needs"] == "update" and "always()" not in WF["jobs"]["push"]["if"]
    script = steps["Collect (polite fetch, parse, verify)"]["run"]
    cases = [(0, 0, 0), (0, 6, 0), (0, 5, 0), (2, 0, 1), (5, 0, 1), (0, 2, 1), (0, 3, 1), (0, 4, 1), (2, 5, 1),
             (5, 6, 1)]
    for city, county, ok in cases:
        fake = script.replace("python -m collector city run; city=$?", f"city={city}").replace(
            "python -m collector run; county=$?", f"county={county}")
        r = subprocess.run(["bash", "-c", fake], env={**os.environ, "GITHUB_OUTPUT": os.devnull},
                           capture_output=True, text=True)
        assert (r.returncode != 0) == bool(ok), (city, county, r.stdout, r.stderr)
    runbook = (ROOT / "docs" / "ops" / "launch-runbook.md").read_text(encoding="utf-8")
    for phrase in ("**Hard failure**", "**Partial**", "county 6", "5 the RPC step failed",
                   "A failed fetch never deletes data", "at most 40 requests", "**RPC only**", "**RPC backlog**",
                   "repeats every day until someone acts", "python -m collector rpc fetch --limit 30"):
        assert phrase in runbook, phrase


def test_deploy_stays_locked_and_is_the_only_publishing_step():
    assert sum(TEXT.count(a) for a in ("actions/deploy-pages@", "peaceiris/", "gh-pages")) == 1
    assert _deploy_if().startswith(LOCK)
    assert "RECORDS_DEPLOY_ENABLED" not in "\n".join(s.get("run", "") for j in WF["jobs"].values()
                                                       for s in j["steps"])     # never set by the workflow itself


# ------------------------------------------------------------------ the issue steps, run with a stub `gh`
def _run_issue_step(tmp_path, step, open_issue="", run_log=None, extra_env=None):
    """Run a workflow step's script in tmp_path with a stub gh; return (gh calls, text of every body)."""
    work, bindir = tmp_path / "work", tmp_path / "bin"
    (work / "build").mkdir(parents=True, exist_ok=True)
    bindir.mkdir(exist_ok=True)
    if run_log is not None:
        (work / "build" / "run-log.json").write_text(run_log, encoding="utf-8")
    calls, bodies = tmp_path / "gh-calls", tmp_path / "bodies"
    gh = bindir / "gh"
    gh.write_text("#!/bin/bash\n"
                  f'echo "$@" >> "{calls}"\n'
                  f'if [ "$2" = list ]; then echo "{open_issue}"; fi\n'
                  'for ((i=1; i<=$#; i++)); do j=$((i+1)); '
                  f'if [ "${{!i}}" = --body-file ]; then cat "${{!j}}" >> "{bodies}"; fi; '
                  f'if [ "${{!i}}" = --body ]; then echo "${{!j}}" >> "{bodies}"; fi; done\n')
    gh.chmod(0o755)
    env = {**os.environ, **{k: v for k, v in (step.get("env") or {}).items() if "${{" not in str(v)},
           "PATH": f"{bindir}:{os.environ['PATH']}", "RUNNER_TEMP": str(tmp_path), "GITHUB_SERVER_URL": "https://x",
           "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "1", **(extra_env or {})}
    subprocess.run(["bash", "-c", step["run"]], cwd=work, env=env, check=True)
    return calls.read_text().splitlines(), (bodies.read_text() if bodies.exists() else "")


def _rpc_issue_step():
    return {s.get("name"): s for s in WF["jobs"]["update"]["steps"]}["Open or update the RPC issue"]


@pytest.mark.skipif(not shutil.which("jq"), reason="jq not installed")
def test_rpc_issue_strips_backticks_so_site_text_stays_in_the_fence(tmp_path):
    """ci/issue-markdown-fence: a status holding ``` (text from the site) cannot close the code fence."""
    import json
    status = "stopped: FetchFailed ```\n# injected heading\n``` https://www.cmcrpc.com/x.pdf"
    _, body = _run_issue_step(tmp_path, _rpc_issue_step(), run_log=json.dumps({"rpc": {"status": status}}))
    assert body.count("```") == 2                                      # only the step's own fence
    assert "injected heading" in body and "https://www.cmcrpc.com/x.pdf" in body


@pytest.mark.parametrize("run_log", [None, "{not json", '{"rpc": {}}'])
def test_rpc_issue_reason_is_unknown_without_a_readable_run_log(tmp_path, run_log):
    """ci/issue-reason-missing: no run-log.json, a broken one, or no status: the reason reads 'unknown'."""
    calls, body = _run_issue_step(tmp_path, _rpc_issue_step(), run_log=run_log)
    fenced = body.split("```")[1].strip()
    assert fenced == "unknown" and calls[-1].startswith("issue create")


@pytest.mark.parametrize("job", ["update", "push"])
@pytest.mark.parametrize("open_issue", ["", "42"])
def test_a_repeat_failure_comments_on_the_open_issue(tmp_path, job, open_issue):
    """ci/failure-issue-silent-repeat: the first failure opens "Daily update failed", a later one comments on it."""
    step = [s for s in WF["jobs"][job]["steps"] if s.get("name") == "Open an issue on failure"][0]
    assert "${{" not in step["run"]                                    # values come in through env only
    calls, body = _run_issue_step(tmp_path, step, open_issue=open_issue, extra_env={"CITY_EXIT": "2",
                                                                                     "COUNTY_EXIT": "0"})
    assert calls[0].startswith("issue list") and len(calls) == 2
    assert calls[1].startswith("issue comment 42" if open_issue else "issue create")
    assert "actions/runs/1" in body and "unchanged" in body
    if job == "update":
        assert "city=2, county=0" in body


# ------------------------------------------------------------------ the morning note (T4.5)
NOTE_IF = "github.event_name == 'schedule' && vars.MORNING_NOTE_SEND == 'true' && github.ref == 'refs/heads/main'"


def _note_steps():
    return {s.get("name"): s for s in WF["jobs"]["note"]["steps"]}


def test_note_job_is_locked_scheduled_on_main_and_after_deploy():
    note = WF["jobs"]["note"]
    assert " ".join(note["if"].split()) == NOTE_IF
    assert "always()" not in note["if"] and "cancelled()" not in note["if"]   # implicit success(): update and deploy
    assert note["needs"] == ["update", "deploy"]                                # deploy locked -> note skipped
    assert note["environment"] == "morning-note" and note["timeout-minutes"] <= 15
    # a manual run never sends: the if needs the schedule trigger, and only schedule and dispatch exist
    on = WF.get("on") or WF[True]
    assert set(on) == {"schedule", "workflow_dispatch"}


def test_note_job_has_a_timeout_and_shares_the_one_run_at_a_time_group():
    """Security (T4.8): never-twice across concurrent runs rests on one daily-update run at a time. The group is
    workflow-level, so it holds every job, the note job included; no job may set its own (it would leave the group)."""
    assert WF["concurrency"] == {"group": "daily-update", "cancel-in-progress": False}
    assert all("concurrency" not in job for job in WF["jobs"].values())
    assert isinstance(WF["jobs"]["note"]["timeout-minutes"], int) and 0 < WF["jobs"]["note"]["timeout-minutes"] <= 15
    assert all(isinstance(job.get("timeout-minutes"), int) for job in WF["jobs"].values())


def _note_if(event, var, ref):
    return event == "schedule" and var == "true" and ref == "refs/heads/main"


@pytest.mark.parametrize("event,var,ref", list(itertools.product(
    ["schedule", "workflow_dispatch"], [None, "", "false", "True", "true"], ["refs/heads/main", "refs/heads/x"])))
def test_note_runs_only_in_the_one_locked_case(event, var, ref):
    expr = " ".join(WF["jobs"]["note"]["if"].split())
    py = (expr.replace("github.event_name", repr(event)).replace("vars.MORNING_NOTE_SEND", repr(var))
          .replace("github.ref", repr(ref)).replace("&&", "and"))
    assert eval(py) == _note_if(event, var, ref)                                # noqa: S307  our own expression


@pytest.mark.parametrize("value", [
    "abc-1", "abc-1,def_2", "abc-1, def_2", "abc-1 def_2", "abc-1\ndef_2", " abc-1,\n def_2\tghi3 \n", "a*,b?\n[c]",
    "", "  \n",
    # note-job/mask-ifs-cr: a secret pasted with Windows line ends, and the other ASCII characters Python's \s splits on
    "abc-1\r\ndef_2\r\n", "abc-1,\r\ndef_2", "abc-1\rdef_2", "abc-1\vdef_2\fghi3", "abc-1\x1cdef_2\x1fghi3", "\r\n",
    # note-job/mask-unicode-ws: Unicode whitespace splits neither in bash nor in canary_ids (which then refuses)
    "abc-1\u00a0def_2", "\u00a0abc-1", "abc-1,\u2003def_2", "abc-1\u2028def_2", "abc-1\x85def_2",
])
def test_mask_step_masks_every_canary_id_deliver_accepts(value, tmp_path):
    """security-note-workflow L2: every id sender/deliver.py's canary_ids reads (commas or any whitespace, every
    line) is masked one by one, and nothing else is printed (no glob expansion of an id). The step runs in a folder
    holding files the glob ids would match (a1, bx, c), so dropping `set -f` fails this test."""
    from sender.deliver import PlanInvalid, canary_ids
    for name in ("a1", "bx", "c"):
        (tmp_path / name).write_text("")
    step = WF["jobs"]["note"]["steps"][0]
    r = subprocess.run(["bash", "-e", "-c", step["run"]], cwd=tmp_path, capture_output=True, text=True, check=True,
                       env={**os.environ, "CANARY_IDS": value})
    # split on "\n" only, as the runner reads workflow commands: splitlines() would also cut at \r, \x1c-\x1e,
    # \x85 or U+2028 inside an id (note-job/mask-ifs-cr)
    *lines, last = r.stdout.split("\n")
    assert last == ""                                       # every line ends with "\n" (or nothing is printed)
    masked = [line.removeprefix("::add-mask::") for line in lines]
    assert all(line.startswith("::add-mask::") for line in lines)
    expected = set(re.split(r"[ \t\n\r\v\f\x1c-\x1f,]+", value)) - {""}     # IFS: the comma and ASCII whitespace only
    assert set(masked) == expected
    if all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", p) for p in expected):
        assert set(masked) == canary_ids(value)
    else:                                                  # an id the step masked whole is refused, never sent
        with pytest.raises(PlanInvalid):
            canary_ids(value)


def test_note_job_least_privilege():
    note = WF["jobs"]["note"]
    assert note["permissions"] == {"contents": "read", "pull-requests": "read"}   # PR check: read only
    steps = note["steps"]
    assert steps[0]["name"] == "Mask the canary ids"                           # before anything else runs
    assert "::add-mask::" in steps[0]["run"]
    uses = [s["uses"] for s in steps if "uses" in s]
    assert [u.split("@")[0] for u in uses] == ["actions/checkout", "actions/setup-python", "actions/download-artifact"]
    co = _note_steps()["Check out this run's commit"]["with"]
    assert co == {"ref": "${{ github.sha }}", "persist-credentials": False}     # not needs.update.outputs.sha (L6)
    assert "cache" not in _note_steps()["Set up Python (standard library only, no pip step)"].get("with", {})
    assert _note_steps()["Download the morning note plan"]["with"]["path"] == "${{ runner.temp }}/morning-send"
    runs = "\n".join(s.get("run", "") for s in steps)
    assert not re.search(r"\bpip\b", runs) and "upload-artifact" not in str(steps) and "cache" not in str(uses)
    assert "GITHUB_STEP_SUMMARY" not in runs and "set -x" not in runs
    assert "${{" not in runs                                                     # nothing interpolated into bash
    assert "python -E -s -m sender deliver" in _note_steps()["Deliver the morning note"]["run"]


def test_the_api_key_is_in_exactly_one_step_and_live_needs_the_variable():
    key_steps = [s["name"] for j in WF["jobs"].values() for s in j["steps"]
                 if "BUTTONDOWN_API_KEY" in (s.get("env") or {})]
    assert key_steps == ["Deliver the morning note"]
    deliver = _note_steps()["Deliver the morning note"]
    assert deliver["env"]["MORNING_NOTE_SEND"] == "${{ vars.MORNING_NOTE_SEND }}"
    for var, live in (("true", True), ("", False), ("false", False), ("TRUE", False)):
        script = deliver["run"].replace("python -E -s -m sender deliver", "echo ARGS")
        r = subprocess.run(["bash", "-c", script], env={**os.environ, "MORNING_NOTE_SEND": var, "PLAN": "p.json"},
                           capture_output=True, text=True, check=True)
        assert ("--live" in r.stdout) == live, var
    # the job that parses untrusted PDFs holds no secret and no write token
    assert "secrets." not in str(WF["jobs"]["update"])


def test_the_plan_step_never_fails_the_daily_job():
    steps = {s.get("name"): s for s in WF["jobs"]["update"]["steps"]}
    plan = steps["Plan the morning note (dry run, no network)"]
    assert plan["continue-on-error"] is True and "--rehearse" in plan["run"]
    assert plan["env"] == {"RECORDS_SITE_URL": "https://daylight.gnoshcodes.com/"}         # no secret, the site URL only
    names = list(steps)
    assert names.index("Site checks") < names.index("Plan the morning note (dry run, no network)")
    up = steps["Upload the morning note plan"]
    assert up["if"] == "success() && steps.plan.outcome == 'success'" and up["with"]["if-no-files-found"] == "ignore"
    assert up["with"]["name"] == "morning-send" and up["with"]["retention-days"] == 2
    # the note job comes after deploy, so nothing it does can hold back push or deploy
    assert "note" not in str(WF["jobs"]["push"].get("needs")) and "note" not in str(WF["jobs"]["deploy"]["needs"])


def _validate_plan(tmp_path, layout: dict):
    """Run the note job's 'Validate the plan files' script over a plan folder built from {relative path: bytes}."""
    step = _note_steps()["Validate the plan files"]
    root = tmp_path / "runner"
    for rel, data in layout.items():
        p = root / "morning-send" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if data is None:
            p.symlink_to("/etc/hostname")
        else:
            p.write_bytes(data)
    (root / "morning-send").mkdir(parents=True, exist_ok=True)
    env_file = tmp_path / "env"
    env_file.write_text("")
    r = subprocess.run(["bash", "-c", step["run"]], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "RUNNER_TEMP": str(root), "GITHUB_ENV": str(env_file)})
    return r.returncode, env_file.read_text()


GOOD = {"2026-11-12/plan.json": b"{}", "2026-11-12/edition-0123456789ab.html": b"x",
        "2026-11-12/edition-0123456789ab.txt": b"x"}


def test_the_plan_file_check_accepts_the_plan_stage_layout(tmp_path):
    code, env = _validate_plan(tmp_path, GOOD)
    assert code == 0 and env.strip().endswith("/morning-send/2026-11-12/plan.json")


@pytest.mark.parametrize("extra", [
    {"2026-11-12/run.sh": b"x"}, {"2026-11-12/edition-XYZ.html": b"x"}, {"2026-11-13/plan.json": b"{}"},
    {"notes.txt": b"x"}, {"2026-11-12/sub/plan.json": b"{}"}, {"2026-11-12/edition-0123456789ab.js": b"x"},
    {"2026-11-12/edition-aaaaaaaaaaaa.html": None},
])
def test_the_plan_file_check_refuses_anything_else(tmp_path, extra):
    code, env = _validate_plan(tmp_path, {**GOOD, **extra})
    assert code != 0 and env == ""


def test_the_plan_file_check_refuses_a_missing_plan_or_a_bad_day(tmp_path):
    assert _validate_plan(tmp_path / "a", {"2026-11-12/edition-0123456789ab.html": b"x"})[0] != 0
    assert _validate_plan(tmp_path / "b", {"latest/plan.json": b"{}"})[0] != 0
    assert _validate_plan(tmp_path / "c", {})[0] != 0


def test_the_plan_file_check_uses_max_plan_bytes():
    from sender.common import MAX_PLAN_BYTES
    assert MAX_PLAN_BYTES > 2_000_000                                             # not the old 2 MB
    run = _note_steps()["Validate the plan files"]["run"]
    assert "from sender.common import MAX_PLAN_BYTES" in run


@pytest.mark.parametrize("open_issue", ["", "9"])
def test_note_failure_opens_its_own_issue_from_a_separate_job(tmp_path, open_issue):
    nf = WF["jobs"]["note-failed"]
    assert nf["needs"] == "note"
    assert nf["if"] == "always() && (needs.note.result == 'failure' || needs.note.result == 'cancelled')"
    assert nf["permissions"] == {"issues": "write"} and "issues" not in WF["jobs"]["note"]["permissions"]
    step = nf["steps"][0]
    assert step["env"]["NOTE_TITLE"] == "Daily update: morning note failed"
    assert "${{" not in step["run"]                                              # fixed text only
    calls, body = _run_issue_step(tmp_path, step, open_issue=open_issue)
    assert calls[1].startswith("issue comment 9" if open_issue else "issue create") and len(calls) == 2
    assert "not affected" in body and "morning-note.md" in body


def test_the_note_runbook_exists_with_the_switches():
    text = (ROOT / "docs" / "ops" / "morning-note.md").read_text(encoding="utf-8")
    for phrase in ("MORNING_NOTE_SEND", "BUTTONDOWN_API_KEY", "MORNING_NOTE_CANARY_IDS", "morning-note",
                   "T4.0", "Canary", "Go-live", "Rollback", "link_hosts", "canary_only", "Deployment branches"):
        assert phrase in text, phrase
    # main-protect/actions-bypass-reopens-M1: the runbook says who can reach the key and offers the one human lock
    for phrase in ("anyone with write or admin access to this repository can reach the Buttondown key",
                   "Keep collaborators to the minimum", "accident prevention plus an audit trail", "Required reviewers",
                   "Prevent self-review", "Review deployments", "Never leave a run waiting", PR_STEP):
        assert phrase in " ".join(text.split()), phrase


@pytest.mark.parametrize("result,fires", [("failure", True), ("cancelled", True), ("success", False),
                                          ("skipped", False)])
def test_note_failed_fires_on_failure_or_cancel_never_on_skip(result, fires):
    """note-failed/silent-noncompletion: a cancelled note job (by hand, or by GitHub) is not a silent day."""
    expr = WF["jobs"]["note-failed"]["if"]
    py = (expr.replace("always() && ", "").replace("needs.note.result", repr(result))
          .replace("||", "or").replace("&&", "and"))
    assert eval(py) == fires                                                     # noqa: S307  our own expression


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",
                           *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _stale_check(tmp_path, change: str) -> int:
    """Run the note job's main-match step in a checkout of commit A while origin/main is A plus `change`."""
    step = _note_steps()["Check this commit's sender and config are main's"]
    origin, src, work = tmp_path / "origin.git", tmp_path / "src", tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(tmp_path, "init", "-q", str(src))
    for rel in ("config/site.yml", "sender/deliver.py", "data/x.json", ".github/workflows/daily-update.yml"):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text("a\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "A")
    sha_a = _git(src, "rev-parse", "HEAD")
    if change:
        (src / change).write_text("b\n")
        _git(src, "commit", "-q", "-am", "B")
    _git(src, "push", "-q", f"file://{origin}", "HEAD:refs/heads/main")
    _git(tmp_path, "clone", "-q", "--depth=1", "--no-single-branch", f"file://{origin}", str(work))
    _git(work, "fetch", "-q", "--depth=1", "origin", sha_a)
    _git(work, "checkout", "-q", "--detach", sha_a)
    r = subprocess.run(["bash", "-c", step["run"]], cwd=work, capture_output=True, text=True)
    return r.returncode


@pytest.mark.parametrize("change,ok", [("", True), ("data/x.json", True), ("sender/deliver.py", False),
                                       ("config/site.yml", False), (".github/workflows/daily-update.yml", False)])
def test_note_refuses_an_older_commit_than_main(tmp_path, change, ok):
    """note-job/stale-rerun: re-running an older run checks out that day's github.sha (and runs that day's workflow
    file) while the plan is built from today's main; the note job must stop unless sender/, config/site.yml and the
    workflow file are main's (note-job/stale-rerun-workflow-gap). Data commits are fine."""
    names = [s.get("name") for s in WF["jobs"]["note"]["steps"]]
    assert names.index("Check out this run's commit") + 1 == names.index(
        "Check this commit's sender and config are main's")
    assert (_stale_check(tmp_path, change) == 0) == ok


# ------------------------------------------------------------------ main-protect/actions-bypass-reopens-M1
PR_STEP = "Check sender, config and workflow changes reached main by pull request"
STALE_STEP = "Check this commit's sender and config are main's"
PR_JQ = '[.[] | select(.merged_at != null and .base.ref == "main" and .merge_commit_sha == $ENV.SHA)] | length'
# note-job/pr-check-test-gap: the stub evaluates the step's own --jq filter with jq (gh uses gojq), so the cases
# test the filter the workflow runs, not a Python copy of it.
_PULLS_STUB = '''#!/usr/bin/env python3
import json, os, subprocess, sys
a = sys.argv[1:]
with open(os.environ["GH_CALLS"], "a") as f:
    f.write(" ".join(a) + "\\n")
if os.environ.get("GH_FAIL"):
    sys.exit(1)
assert len(a) == 4 and a[0] == "api" and a[2] == "--jq" and a[3] == os.environ["EXPECTED_JQ"], a
sha = a[1].removeprefix("repos/o/r/commits/").removesuffix("/pulls")
assert os.environ["SHA"] == sha and os.environ["GH_TOKEN"] == "t"
prs = json.load(open(os.environ["PULLS"])).get(sha, [])
r = subprocess.run(["jq", "-r", a[3]], input=json.dumps(prs), capture_output=True, text=True)
sys.stdout.write(r.stdout)
sys.stderr.write(r.stderr)
sys.exit(r.returncode)
'''
_ALL = ("config/site.yml", "sender/deliver.py", "data/x.json", ".github/workflows/daily-update.yml")


def _need_jq():
    """jq runs the PR check's filter in these tests: skip where it is missing locally, fail in CI (CI is set on
    GitHub's runners, which ship jq), so the check is never skipped quietly where it matters."""
    if not shutil.which("jq"):
        if os.environ.get("CI"):
            pytest.fail("jq is not installed on this CI runner: the PR check tests need it")
        pytest.skip("jq not installed")


def _pr(sha, merged=True, base="main"):
    return {"merged_at": "2026-11-11T00:00:00Z" if merged else None, "base": {"ref": base}, "merge_commit_sha": sha}


def _pr_check(tmp_path, ops, pulls, gh_fail=False, baseline="BASE"):
    """Build main from `ops`, check out its tip from a depth-1 clone (as actions/checkout does), run the stale-rerun
    step (its depth-1 fetch of main comes first in the job) and then the PR step. main starts with a commit BASE
    touching every checked path, with no PR (the history before go-live).
    ops: ("commit", label, paths) on main, or ("merge", label, branch_label, paths): a branch commit touching paths,
    merged into main with --no-ff. pulls: {label: [pr(sha_label or a literal sha), ...]}. baseline: the label (or a
    literal value) given as MAIN_PR_BASELINE. Returns (exit, gh calls, {label: sha})."""
    _need_jq()
    step = _note_steps()[PR_STEP]
    origin, src, work, bindir = tmp_path / "origin.git", tmp_path / "src", tmp_path / "work", tmp_path / "bin"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(origin, "config", "uploadpack.allowFilter", "true")   # as GitHub: --filter=blob:none is honoured, not ignored
    _git(tmp_path, "init", "-q", str(src))
    shas, n = {}, 0

    def touch(paths):
        nonlocal n
        for rel in paths:
            n += 1
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / rel).write_text(f"{n}\n")
        _git(src, "add", "-A")

    for op in [("commit", "BASE", _ALL), *ops]:
        if op[0] == "commit":
            touch(op[2])
            _git(src, "commit", "-q", "-m", op[1])
            shas[op[1]] = _git(src, "rev-parse", "HEAD")
        else:
            _, label, branch_label, paths = op
            _git(src, "checkout", "-q", "-b", branch_label)
            touch(paths)
            _git(src, "commit", "-q", "-m", branch_label)
            shas[branch_label] = _git(src, "rev-parse", "HEAD")
            _git(src, "checkout", "-q", "main")
            _git(src, "merge", "-q", "--no-ff", "-m", label, branch_label)
            shas[label] = _git(src, "rev-parse", "HEAD")
    _git(src, "push", "-q", f"file://{origin}", "main:refs/heads/main")
    _git(tmp_path, "clone", "-q", "--depth=1", f"file://{origin}", str(work))
    _git(work, "checkout", "-q", "--detach", shas[ops[-1][1]])
    assert _git(work, "rev-parse", "--is-shallow-repository") == "true"
    resolved = {shas[k]: [{**p, "merge_commit_sha": shas.get(p["merge_commit_sha"], p["merge_commit_sha"])}
                          for p in v] for k, v in pulls.items()}
    (tmp_path / "pulls.json").write_text(__import__("json").dumps(resolved))
    bindir.mkdir()
    (bindir / "gh").write_text(_PULLS_STUB)
    (bindir / "gh").chmod(0o755)
    calls = tmp_path / "gh-calls"
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_TOKEN": "t", "GITHUB_REPOSITORY": "o/r",
           "GH_CALLS": str(calls), "PULLS": str(tmp_path / "pulls.json"), "EXPECTED_JQ": PR_JQ,
           "MAIN_PR_BASELINE": shas.get(baseline, baseline), **({"GH_FAIL": "1"} if gh_fail else {})}
    stale = subprocess.run(["bash", "-c", _note_steps()[STALE_STEP]["run"]], cwd=work, capture_output=True, text=True)
    assert stale.returncode == 0, stale.stdout + stale.stderr                  # the step before it, on the same checkout
    r = subprocess.run(["bash", "-c", step["run"]], cwd=work, env=env, capture_output=True, text=True)
    assert "Traceback" not in r.stderr, r.stderr
    calls = calls.read_text().splitlines() if calls.exists() else []
    if calls:   # it read a PR, so it fetched main's whole history after the depth-1 fetch, without file contents
        assert _git(work, "rev-parse", "--is-shallow-repository") == "false"
        assert _git(work, "config", "--get", "remote.origin.partialclonefilter") == "blob:none"
        assert "filtering not recognized by server" not in r.stderr, r.stderr
    return r.returncode, calls, shas


DATA = ("data/x.json",)
SENDER = ("sender/deliver.py",)
# case: (ops on main after BASE, pulls, sends?, the commits whose PRs are read, newest first)
PR_CASES = {
    # the PR-merged commit, then daily data/ commits pushed by the push job without a PR: sends
    "pr-then-data-days": ([("commit", "A", _ALL), ("commit", "D1", DATA), ("commit", "D2", DATA)],
                          {"A": [_pr("A")]}, True, ["A"]),
    # two PRs: every one is read, sends
    "pr-then-pr": ([("commit", "A", _ALL), ("commit", "D", DATA), ("commit", "P", SENDER)],
                   {"A": [_pr("A")], "P": [_pr("P")]}, True, ["P", "A"]),
    # a merge-commit PR (the branch commit itself has no PR of its own), then a data day: sends
    "merge-commit-pr": ([("commit", "A", _ALL), ("merge", "M", "B", SENDER), ("commit", "D", DATA)],
                        {"A": [_pr("A")], "M": [_pr("M")]}, True, ["M", "A"]),
    # pushed straight to main (the Actions bypass, or an unprotected push): refused
    "direct-sender": ([("commit", "A", _ALL), ("commit", "X", SENDER), ("commit", "D", DATA)],
                      {"A": [_pr("A")]}, False, ["X"]),
    "direct-config": ([("commit", "A", _ALL), ("commit", "X", ("config/site.yml",))], {"A": [_pr("A")]}, False,
                      ["X"]),
    "direct-other-workflow": ([("commit", "A", _ALL), ("commit", "X", (".github/workflows/other.yml",))],
                              {"A": [_pr("A")]}, False, ["X"]),
    # main-protect/pr-check-last-commit-only: A (PR) -> X (direct) -> P (PR) is still refused: the later PR does not
    # launder the direct push, whatever the later PR touches
    "pr-direct-pr": ([("commit", "A", _ALL), ("commit", "X", SENDER), ("commit", "P", ("config/site.yml",))],
                     {"A": [_pr("A")], "P": [_pr("P")]}, False, ["P", "X"]),
    "pr-direct-merge-pr": ([("commit", "A", _ALL), ("commit", "X", (".github/workflows/other.yml",)),
                            ("merge", "M", "B", SENDER), ("commit", "D", DATA)],
                           {"A": [_pr("A")], "M": [_pr("M")]}, False, ["M", "X"]),
    # the commit belongs to a PR that is still open, merged elsewhere, or merged as another commit: refused
    "open-pr": ([("commit", "A", _ALL), ("commit", "X", SENDER)],
                {"A": [_pr("A")], "X": [_pr("X", merged=False)]}, False, ["X"]),
    "pr-into-other-branch": ([("commit", "A", _ALL), ("commit", "X", SENDER)],
                             {"A": [_pr("A")], "X": [_pr("X", base="dev")]}, False, ["X"]),
    "pr-merged-as-another-commit": ([("commit", "A", _ALL), ("commit", "X", SENDER)],
                                    {"A": [_pr("A")], "X": [_pr("f" * 40)]}, False, ["X"]),
    # a merge pushed straight to main whose merged-in side is a PR's commit: main's own commit (first parent) counts
    "pushed-merge-of-pr-commit": ([("commit", "A", _ALL), ("merge", "M", "E", SENDER)],
                                  {"A": [_pr("A")], "E": [_pr("E")]}, False, ["M"]),
    # no PR at all after the baseline (the team's earlier merges without PRs): refused from go-live
    "no-pr-history": ([("commit", "A", _ALL), ("commit", "D", DATA)], {}, False, ["A"]),
}


@pytest.mark.parametrize("case", list(PR_CASES))
def test_note_refuses_unless_sender_config_and_workflows_reached_main_by_pr(tmp_path, case):
    ops, pulls, ok, read = PR_CASES[case]
    code, calls, shas = _pr_check(tmp_path, ops, pulls)
    assert (code == 0) == ok, (case, code)
    assert calls == [f"api repos/o/r/commits/{shas[c]}/pulls --jq {PR_JQ}" for c in read]   # main's own commits only


def test_the_pr_check_ignores_history_up_to_the_baseline(tmp_path):
    """The baseline (main at go-live, checked by hand) and everything before it are not read: a direct push X before
    it does not refuse; the same history with the baseline before X does."""
    ops = [("commit", "X", SENDER), ("commit", "G", DATA), ("commit", "P", (".github/workflows/daily-update.yml",))]
    (tmp_path / "g").mkdir()
    code, calls, shas = _pr_check(tmp_path / "g", ops, {"P": [_pr("P")]}, baseline="G")
    assert code == 0 and calls == [f"api repos/o/r/commits/{shas['P']}/pulls --jq {PR_JQ}"]
    (tmp_path / "base").mkdir()
    code, calls, shas = _pr_check(tmp_path / "base", ops, {"P": [_pr("P")]}, baseline="BASE")
    assert code == 2 and calls == [f"api repos/o/r/commits/{shas[c]}/pulls --jq {PR_JQ}" for c in ("P", "X")]


@pytest.mark.parametrize("baseline", ["", "not-a-sha", "A" * 40, "a" * 40, "B", "P"])
def test_the_pr_check_fails_closed_without_a_valid_baseline(tmp_path, baseline):
    """main-protect/pr-check-last-commit-only: unset (the committed value until go-live), not a sha, a sha that is not
    in the history, a commit of a merged-in branch (not on main's first-parent line), or a baseline with no checked
    change after it (the commit that set it always is one): refused without reading any PR."""
    ops = [("commit", "A", _ALL), ("merge", "M", "B", SENDER), ("commit", "P", SENDER)]
    code, calls, _ = _pr_check(tmp_path, ops, {"A": [_pr("A")], "M": [_pr("M")], "P": [_pr("P")]},
                               baseline=baseline)
    assert code == 2 and calls == []


def test_the_committed_baseline_is_unset_or_a_sha():
    """Until go-live MAIN_PR_BASELINE is empty, so the note job refuses every send; go-live sets it (runbook 4.7)."""
    env = _note_steps()[PR_STEP]["env"]
    assert env["MAIN_PR_BASELINE"] == "" or re.fullmatch(r"[0-9a-f]{40}", env["MAIN_PR_BASELINE"])
    runbook = (ROOT / "docs" / "ops" / "morning-note.md").read_text(encoding="utf-8")
    assert "MAIN_PR_BASELINE" in runbook


def test_the_pr_check_fails_closed_when_github_cannot_be_read(tmp_path):
    code, calls, _ = _pr_check(tmp_path, [("commit", "A", _ALL)], {"A": [_pr("A")]}, gh_fail=True)
    assert code != 0 and len(calls) == 1


def test_the_pr_check_jq_filter_with_real_jq():
    """The --jq expression gh evaluates (gojq), run through jq where it is installed: counts only a merged PR into
    main whose merge commit is this commit."""
    import json
    _need_jq()
    sha = "a" * 40
    for prs, want in (([_pr(sha)], "1"), ([_pr(sha, merged=False)], "0"), ([_pr(sha, base="dev")], "0"),
                      ([_pr("b" * 40)], "0"), ([], "0"), ([_pr("b" * 40), _pr(sha)], "1")):
        r = subprocess.run(["jq", PR_JQ], input=json.dumps(prs), capture_output=True, text=True, check=True,
                           env={**os.environ, "SHA": sha})
        assert r.stdout.strip() == want, prs


def test_the_pr_check_runs_before_any_secret_step_with_a_read_only_token():
    steps = WF["jobs"]["note"]["steps"]
    names = [s.get("name") for s in steps]
    i = names.index(PR_STEP)
    assert names.index("Check this commit's sender and config are main's") + 1 == i
    assert i < names.index("Deliver the morning note")
    step = steps[i]
    assert set(step["env"]) == {"GH_TOKEN", "MAIN_PR_BASELINE"}   # the read-only token and the baseline only
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert [s["name"] for s in steps if "GH_TOKEN" in (s.get("env") or {})] == [PR_STEP]
    assert "sender/ config/site.yml .github/" in step["run"] and "--first-parent" in step["run"]
    assert PR_JQ in " ".join(step["run"].split())
    assert WF["jobs"]["note"]["permissions"] == {"contents": "read", "pull-requests": "read"}


# ------------------------------------------------------------------ the main ruleset scripts (runbook step 2.0.6)
_GH_STUB = '''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
with open(os.environ["GH_CALLS"], "a") as f:
    f.write(" ".join(a) + "\\n")
if a[:2] == ["auth", "status"] or "-X" in a:
    sys.exit(0)
path = [x for x in a if x.startswith("repos/")][0]
jq = a[a.index("--jq") + 1]
if path.endswith("/rulesets"):
    assert jq == ".[] | select(.name == $ENV.RULESET_NAME) | .id", jq
    assert os.environ["RULESET_NAME"] == "main: pull request required"
    for i in os.environ["EXISTING"].split():
        print(i)
elif path.endswith("/rules/branches/main"):
    print("pull_request\\ndeletion\\nnon_fast_forward")
elif jq == ".enforcement":
    print("active")
else:
    print("Integration\\t15368")
'''


@pytest.mark.parametrize("existing", ["", "42", "42 43"])
def test_protect_main_creates_once_and_updates_after(tmp_path, existing):
    """note-runbook/ruleset-flow: a ruleset of that name already there is updated (PUT), never duplicated (POST)."""
    bindir, calls = tmp_path / "bin", tmp_path / "gh-calls"
    bindir.mkdir()
    (bindir / "gh").write_text(_GH_STUB)
    (bindir / "gh").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_CALLS": str(calls), "EXISTING": existing}
    r = subprocess.run(["bash", str(ROOT / "scripts" / "protect-main.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "OK: main is protected" in r.stdout, r.stdout + r.stderr
    lines = calls.read_text().splitlines()
    posts = [c for c in lines if "-X POST" in c]
    puts = [c.split()[3] for c in lines if "-X PUT" in c]
    if existing:
        assert not posts and puts == [f"repos/gn0sh/clarksville-records/rulesets/{i}" for i in existing.split()]
    else:
        assert len(posts) == 1 and not puts
    assert all("main-ruleset.json" in c for c in lines if " -X " in f" {c}")


def test_protect_main_scripts_share_one_ruleset_body():
    import json
    body = json.loads((ROOT / "scripts" / "main-ruleset.json").read_text(encoding="utf-8"))
    assert body["name"] == "main: pull request required" and body["enforcement"] == "active"
    assert body["bypass_actors"] == [{"actor_id": 15368, "actor_type": "Integration", "bypass_mode": "always"}]
    assert sorted(r["type"] for r in body["rules"]) == ["deletion", "non_fast_forward", "pull_request"]
    assert body["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    for name in ("protect-main.ps1", "protect-main.sh"):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "main-ruleset.json" in text and "main: pull request required" in text and "-X PUT" in text, name
    ps1 = (ROOT / "scripts" / "protect-main.ps1").read_text(encoding="utf-8")
    # no double quote inside a --jq argument: Windows PowerShell 5.1 strips them on the way to gh
    assert not re.search(r"--jq '[^']*\"", ps1) and "$ENV.RULESET_NAME" in ps1


# ------------------------------------------------------------------ deps/transitive-unpinned: the hashed lock
def _lock_pins() -> dict:
    """{name: (version, [hashes])} from requirements.lock (pip-compile --generate-hashes output)."""
    pins, name = {}, None
    for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s\\;]+)", line)
        if m:
            name = m.group(1).lower().replace("_", "-")
            pins[name] = (m.group(2), [])
        h = re.search(r"--hash=sha256:([0-9a-f]{64})", line)
        if h and name:
            pins[name][1].append(h.group(1))
    return pins


def test_the_update_job_installs_only_hashed_pins_from_the_lock():
    steps = {s.get("name"): s for s in WF["jobs"]["update"]["steps"]}
    run = steps["Install system tools and Python packages"]["run"]
    assert "python -m pip install --require-hashes -r requirements.lock" in run and "requirements.txt" not in run
    assert re.findall(r"pip install -[^\n]*", TEXT) == ["pip install --require-hashes -r requirements.lock"]
    pins = _lock_pins()
    assert pins and all(hashes for _, hashes in pins.values()), "every locked package carries its sha256"


def test_the_lock_matches_requirements_txt_and_the_runner_python():
    pins = _lock_pins()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            name, version = line.split("==")
            assert pins[name.lower().replace("_", "-")][0] == version, f"{name}: rerun pip-compile (requirements.lock)"
    py = {s["with"]["python-version"] for j in WF["jobs"].values() for s in j["steps"]
          if s.get("uses", "").startswith("actions/setup-python")}
    assert py == {"3.12"}                                                         # the Python the lock was compiled on
    head = (ROOT / "requirements.lock").read_text(encoding="utf-8")[:400]
    assert "pip-compile with Python 3.12" in head and "--generate-hashes" in head
