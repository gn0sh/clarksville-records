"""The daily-update workflow ships locked: its deploy job runs only when RECORDS_DEPLOY_ENABLED is 'true' (CEO hard
stop 1), nothing else may publish, and no secrets are used."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8")
WF = yaml.safe_load(TEXT)


def test_deploy_job_is_locked():
    assert WF["jobs"]["deploy"]["if"].strip() == "vars.RECORDS_DEPLOY_ENABLED == 'true'"
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
    assert (ROOT / "deploy" / "CNAME").read_text(encoding="utf-8").strip() == "records.gnoshcodes.com"
    assert "cp deploy/CNAME build/site/CNAME" in TEXT


def test_launch_overrides_are_read_from_the_environment(monkeypatch):
    import importlib

    from sitegen import config
    try:
        monkeypatch.setenv("RECORDS_SITE_URL", "https://records.gnoshcodes.com/")
        monkeypatch.setenv("RECORDS_BUILD_TARGET", "pages")
        importlib.reload(config)
        assert config.SITE["alerts"]["site_url"] == "https://records.gnoshcodes.com/"
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
