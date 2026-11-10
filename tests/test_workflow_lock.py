"""The daily-update workflow ships locked: its deploy job runs only when RECORDS_DEPLOY_ENABLED is 'true' (CEO hard
stop 1), nothing else may publish, and no secrets are used."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8")
WF = yaml.safe_load(TEXT)


def test_deploy_job_is_locked():
    cond = WF["jobs"]["deploy"]["if"].strip()
    assert cond == "vars.RECORDS_DEPLOY_ENABLED == 'true' && github.ref == 'refs/heads/main'"
    assert cond.startswith("vars.RECORDS_DEPLOY_ENABLED == 'true'")          # the lock stays the first condition
    assert WF["jobs"]["deploy"]["needs"] == "update"


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
    assert jobs["deploy"]["needs"] == "update"


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
    assert "*.json|*.yml" in validate                              # extension allowlist (what git ls-files data holds)
    assert "-size +50M" in validate
    assert names.index("Validate refreshed data") < names.index("Commit refreshed data to main")
    assert names.index("Download refreshed data") < names.index("Validate refreshed data")
    assert "git add" not in validate


def test_tracked_data_files_fit_the_allowlist():
    import subprocess
    files = subprocess.run(["git", "ls-files", "data"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    assert files and all(f.endswith((".json", ".yml")) for f in files)


def test_push_failure_opens_an_issue():
    """pipeline/push-failure-silent."""
    push = WF["jobs"]["push"]
    assert push["permissions"] == {"contents": "write", "issues": "write"}
    last = push["steps"][-1]
    assert last["if"] == "failure()" and "Daily update failed" in last["run"] and "gh issue" in last["run"]
    runbook = (ROOT / "docs" / "ops" / "launch-runbook.md").read_text(encoding="utf-8")
    assert "A failure in `update` or `push` opens" in runbook


def test_push_and_deploy_run_on_main_only():
    """pipeline/dispatch-non-main-ref: a manual run on another branch cannot commit to main or deploy."""
    assert "github.ref == 'refs/heads/main'" in WF["jobs"]["push"]["if"]
    assert "github.ref == 'refs/heads/main'" in WF["jobs"]["deploy"]["if"]
    assert "github.event_name == 'schedule' || inputs.collect" in WF["jobs"]["push"]["if"]
