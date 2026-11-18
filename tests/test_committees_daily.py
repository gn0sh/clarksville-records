"""City committees in the daily update (milestone C2): the workflow step and the push job's data allowlist."""


def test_daily_workflow_runs_the_committees_before_the_site_build_as_a_warning_only():
    """C2 wiring: its own step before Collect (which builds the site), only new files (at most 40 a run), never
    failing the job; the push job's allowlist takes data/localities/clarksville-tn/committees/ (json files)."""
    import subprocess

    import yaml
    from conftest import ROOT
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["update"]["steps"]
    names = [s.get("name") for s in steps]
    i = names.index("Collect city committees (warning only)")
    assert names.index("Restore document store") < i < names.index("Collect (polite fetch, parse, verify)")
    step = steps[i]
    assert step["continue-on-error"] is True and step["if"] == "github.event_name == 'schedule' || inputs.collect"
    assert "python -m collector committees run --limit 40; rc=$?" in step["run"] and "env" not in step
    assert step["run"].lstrip().startswith("set +e")
    for rc in (0, 1, 2, 4):
        # the real command's exit, under the shell Actions uses (bash -e): the step still reads rc and warns
        fake = step["run"].replace("python -m collector committees run --limit 40", f"(exit {rc})")
        r = subprocess.run(["bash", "-e", "-c", fake], capture_output=True, text=True)
        assert r.returncode == 0 and (("::warning::" in r.stdout) is (rc != 0)), (rc, r.stdout, r.stderr)
        assert f"committees_exit={rc}" in r.stdout
    files = subprocess.run(["git", "ls-files", "data/localities/clarksville-tn/committees"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.split()
    assert files and all(f.endswith(".json") for f in files)     # the push job's allowlist: *.json|changes.jsonl
    validate = {s.get("name"): s for s in wf["jobs"]["push"]["steps"]}["Validate refreshed data"]["run"]
    assert "*.json|*/changes.jsonl) ;;" in validate
    assert "data/localities/clarksville-tn/committees/manifest.json" in (ROOT / "config" / "site.yml").read_text(
        encoding="utf-8")                                         # fetch days on the pages are site_timezone days
