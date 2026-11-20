"""The national workflow (D1, `.github/workflows/national-update.yml`) and the daily deploy's national-data lookup (D2,
`daily-update.yml`): docs/architecture/daylight-national.md 4.4.4 and 4.6, ADR 0013 decision 6, security finding 6
(`national/writer-token-scope`). The collect job is read-only and holds no token; only the push job writes, and only
data/national/** to national-data; every attestation check pins --cert-identity to one workflow file at
refs/heads/main, so an attestation by another workflow or from another branch is refused (run here against a `gh`
stub that matches every constraint the step passes). No test sends a request anywhere."""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from collector.national import __main__ as cli

ROOT = Path(__file__).resolve().parent.parent
NAT_PATH = ROOT / ".github" / "workflows" / "national-update.yml"
DAILY_PATH = ROOT / ".github" / "workflows" / "daily-update.yml"
NAT_TEXT = NAT_PATH.read_text(encoding="utf-8")
NAT = yaml.safe_load(NAT_TEXT)
DAILY = yaml.safe_load(DAILY_PATH.read_text(encoding="utf-8"))

REPO = "gn0sh/clarksville-records"
NAT_ID = f"https://github.com/{REPO}/.github/workflows/national-update.yml@refs/heads/main"
DAILY_ID = f"https://github.com/{REPO}/.github/workflows/daily-update.yml@refs/heads/main"
SLSA = "https://slsa.dev/provenance/v1"
HELPER_START = "# ---- national-data tree helper:"
HELPER_END = "# ---- end of the national-data tree helper ----"
GATE_STEP = "Check the national-data head"
COLLECT_STEP = "Collect (national, polite fetch)"
FETCH_STEP = "Install packages and check out the gate's national-data head (N)"
VALIDATE_STEP = "Validate the national data"
COMMIT_STEP = "Commit the national data on national-data"
PUSH_STEP = "Push the data commit to national-data"
LOOKUP_STEP = "Find the newest attested national-data"
PUT_STEP = "Put N's data/national beside the build"
SEED_FILES = {"data/national/health.json": "{}\n", "data/national/proposals.json": "[]\n"}


def _steps(wf, job) -> dict:
    return {s.get("name"): s for s in wf["jobs"][job]["steps"]}


def _on(wf):
    return wf.get("on") or wf[True]


def _git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t"}).stdout.strip()


# ------------------------------------------------------------------------------------------------ shape and pins

def test_triggers_concurrency_and_least_privilege():
    on = _on(NAT)
    assert set(on) == {"schedule", "workflow_dispatch"} and len(on["schedule"]) == 2      # twice daily
    assert NAT["concurrency"] == {"group": "national-collect", "cancel-in-progress": False}
    assert NAT["permissions"] == {}
    jobs = NAT["jobs"]
    assert list(jobs) == ["gate", "collect", "push", "report"]
    assert jobs["gate"]["permissions"] == {"contents": "read", "attestations": "read"}
    assert jobs["collect"]["permissions"] == {"contents": "read"}
    assert jobs["push"]["permissions"] == {"contents": "write", "id-token": "write", "attestations": "write"}
    assert jobs["report"]["permissions"] == {"issues": "write"}
    assert jobs["collect"]["needs"] == "gate" and jobs["push"]["needs"] == ["gate", "collect"]
    base = "needs.gate.outputs.ready == 'yes' && github.ref == 'refs/heads/main'"   # main only, never before U3-0
    assert " ".join(jobs["push"]["if"].split()) == base
    # 12.3 #11 (S2b finding 4): the collect job runs on the schedule, or when gn0sh both dispatched and triggered it
    assert " ".join(jobs["collect"]["if"].split()) == (
        base + " && (github.event_name == 'schedule' || (github.actor == 'gn0sh' && github.triggering_actor == 'gn0sh'))")
    assert "status" not in jobs["push"]["if"] and "always()" not in jobs["push"]["if"]  # implied success(): a
    #                                                                       skipped collect skips the push too
    assert "github.ref == 'refs/heads/main'" in jobs["report"]["if"]


def test_the_collect_job_holds_no_token():
    """Finding 6: contents: read, no persisted token, no token or secret in any step, no git push, no gh."""
    job = NAT["jobs"]["collect"]
    text = yaml.safe_dump(job)
    for word in ("github.token", "GH_TOKEN", "GITHUB_TOKEN", "secrets.", "git push", "gh "):
        assert word not in text, word
    checkouts = [s for s in job["steps"] if "actions/checkout@" in s.get("uses", "")]
    assert checkouts and all(s["with"]["persist-credentials"] is False for s in checkouts)
    assert all("env" not in s or not any("token" in str(v) for v in s["env"].values()) for s in job["steps"])


def test_only_the_push_job_writes_and_it_parses_nothing():
    jobs = NAT["jobs"]
    writers = [n for n, j in jobs.items() if "write" in (j["permissions"] or {}).values()
               and set(k for k, v in j["permissions"].items() if v == "write") - {"issues"}]
    assert writers == ["push"]
    run = "\n".join(s.get("run", "") for s in jobs["push"]["steps"])
    assert "python" not in run and "jq" not in run
    assert run.count("git push") == 1 and 'git push origin "HEAD:refs/heads/national-data"' in run
    assert "--force" not in run and "+HEAD" not in run and "refs/heads/main" not in run


def test_every_action_is_pinned_by_sha_and_matches_the_daily_pins():
    pins = {}
    for text in (NAT_TEXT, DAILY_PATH.read_text(encoding="utf-8")):
        for line in text.splitlines():
            if line.strip().startswith(("- uses:", "uses:")):
                action, ref = line.split("uses:")[1].split("#")[0].strip().split("@")
                assert len(ref) == 40 and set(ref) <= set("0123456789abcdef"), line
                assert pins.setdefault(action, ref) == ref, f"{action} pinned twice differently"
    assert {"actions/checkout", "actions/setup-python", "actions/upload-artifact", "actions/download-artifact",
            "actions/attest-build-provenance"} <= set(pins)


def test_the_job_timeout_and_step_timeouts_keep_the_cli_s_margin():
    """4.4.4: the collect job's timeout is the CLI's JOB_MINUTES; steps before the CLI at most 3 minutes, steps after
    at most 3, and the CLI's step has room for its deadline, one request in flight (6 min) and the writes (1 min)."""
    job = NAT["jobs"]["collect"]
    assert job["timeout-minutes"] == cli.JOB_MINUTES == 75
    names = [s["name"] for s in job["steps"]]
    i = names.index(COLLECT_STEP)
    mins = [s["timeout-minutes"] for s in job["steps"]]
    assert all(isinstance(m, int) and m >= 1 for m in mins)      # whole minutes only
    before, during, after = sum(mins[:i]), mins[i], sum(mins[i + 1:])
    assert before <= 3 and after <= 3, (before, after)
    assert during >= cli.RUN_SECONDS // 60 + 6 + 1
    assert before + during + after <= cli.JOB_MINUTES
    assert cli.MARGIN_MINUTES >= before + 6 + 1 + after
    for name in ("gate", "push", "report"):
        assert NAT["jobs"][name]["timeout-minutes"] <= 15
    assert all("timeout-minutes" in s for s in NAT["jobs"]["push"]["steps"])
    assert "cache" not in _steps(NAT, "collect")["Set up Python"].get("with", {})   # no post step to wait for


def test_the_data_path_is_a_fresh_folder_never_an_existing_data_tree():
    """4.6 "D1 data path": code and national-data each go into a new folder of the fresh workspace; the CLI's data root
    is national/data/national, and only that folder is uploaded."""
    steps = _steps(NAT, "collect")
    co = steps["Check out the gate's commit"]
    assert co["with"] == {"ref": "${{ needs.gate.outputs.code }}", "path": "code", "persist-credentials": False}
    fetch = steps[FETCH_STEP]["run"]
    assert 'root="$GITHUB_WORKSPACE/national"' in fetch and 'if [ -e "$root" ] || [ -L "$root" ]' in fetch
    assert 'git init -q "$root"' in fetch and '"$N"' in fetch and "rev-parse HEAD)\" != \"$N\"" in fetch
    assert steps[FETCH_STEP]["env"] == {"N": "${{ needs.gate.outputs.sha }}"}
    assert '"$GITHUB_WORKSPACE/national/data/national" --budget "$BUDGET"' in steps[COLLECT_STEP]["run"]
    up = steps["Upload the national data"]
    assert up["with"]["path"] == "national/data/national" and up["with"]["name"] == "national-data"
    assert "include-hidden-files" not in up["with"]


# ------------------------------------------------------------------------------------------------ logs

def test_no_log_leakage_in_any_step():
    """4.6 "D1 logs": no `set -x`, no `cat` or `tee` of anything, no step summary, no fetcher log, and the CLI's
    output is never redirected into a file or captured into a variable."""
    for job in NAT["jobs"].values():
        for s in job["steps"]:
            run = s.get("run", "")
            assert not re.search(r"\bset -[a-z]*x", run) and "set -o xtrace" not in run
            assert not re.search(r"(^|[\s|;(])(cat|tee)\s", run), s["name"]
            assert "GITHUB_STEP_SUMMARY" not in run.replace("-u GITHUB_STEP_SUMMARY", "")
            assert "fetcher.log" not in run and "--log" not in run
    collect = _steps(NAT, "collect")[COLLECT_STEP]["run"]
    cmd = [ln for ln in collect.splitlines() if "python -m collector.national" in ln]
    assert len(cmd) == 1 and not re.search(r"[>|]|\$\(", cmd[0]), cmd
    assert "env -u GITHUB_OUTPUT -u GITHUB_ENV -u GITHUB_PATH -u GITHUB_STATE -u GITHUB_STEP_SUMMARY \\" in collect
    assert "2>" not in collect and "&>" not in collect


def _run_collect(tmp_path, rc, budget="300", prints=""):
    """The collect step with `python` replaced by a stub that prints `prints`, tries to set an output and a summary
    and to write every other file command (env, path, state: S2b nit a), and exits `rc`."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "python"
    stub.write_text("#!/bin/sh\n"
                    f"printf '%s\\n' '{prints}'\n"
                    'echo "$@" > "$ARGS_FILE"\n'
                    '[ -n "${GITHUB_OUTPUT:-}" ] && echo "flagged=no" >> "$GITHUB_OUTPUT"\n'
                    '[ -n "${GITHUB_STEP_SUMMARY:-}" ] && echo leak >> "$GITHUB_STEP_SUMMARY"\n'
                    'for f in "${GITHUB_ENV:-}" "${GITHUB_PATH:-}" "${GITHUB_STATE:-}"; do [ -n "$f" ] && echo leak=1 >> "$f"; done\n'
                    f"exit {rc}\n")
    stub.chmod(0o755)
    out, summary, args = tmp_path / "out", tmp_path / "summary", tmp_path / "args"
    out.write_text("")
    summary.write_text("")
    files = {k: tmp_path / k.lower() for k in ("GITHUB_ENV", "GITHUB_PATH", "GITHUB_STATE")}
    for f in files.values():
        f.write_text("")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(out),
           "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_WORKSPACE": "/ws",
           "BUDGET": budget, "ARGS_FILE": str(args), **{k: str(f) for k, f in files.items()}}
    r = subprocess.run(["bash", "-c", _steps(NAT, "collect")[COLLECT_STEP]["run"]], env=env, capture_output=True,
                       text=True)
    assert all(f.read_text() == "" for f in files.values())     # the CLI can write no env, path or state
    return r, out.read_text(), summary.read_text(), args.read_text() if args.exists() else ""


@pytest.mark.parametrize("rc,ok,flagged", [(0, True, "no"), (3, True, "yes"), (1, False, None), (2, False, None),
                                           (130, False, None)])
def test_the_collect_step_maps_the_cli_exit_codes(tmp_path, rc, ok, flagged):
    r, out, summary, args = _run_collect(tmp_path, rc, prints="::add-mask::x")
    assert (r.returncode == 0) == ok, (r.stdout, r.stderr)
    assert out == (f"flagged={flagged}\n" if ok else "")       # only the step writes its output, never the CLI
    assert summary == ""
    assert args.split() == ["-m", "collector.national", "/ws/national/data/national", "--budget", "300"]
    lines = r.stdout.splitlines()
    stop = next(i for i, ln in enumerate(lines) if ln.startswith("::stop-commands::"))
    token = lines[stop].split("::")[2]
    assert re.fullmatch(r"[0-9a-f]{32}", token)
    resume = lines.index(f"::{token}::")
    assert stop < lines.index("::add-mask::x") < resume       # the CLI's lines are inert
    if rc == 3:
        assert any(ln.startswith("::warning::") for ln in lines[resume:])


@pytest.mark.parametrize("budget", ["", "0", "abc", "1000", "3 --directory x", "-1", "361", "400", "999", "0360",
                                    "36 0", "360\n"])
def test_a_bad_budget_collects_nothing(tmp_path, budget):
    r, out, _s, args = _run_collect(tmp_path, 0, budget=budget)
    assert r.returncode != 0 and args == "" and out == ""


@pytest.mark.parametrize("budget", ["1", "9", "10", "99", "100", "299", "300", "359", "360"])
def test_a_budget_from_1_to_360_collects(tmp_path, budget):
    """12.3 #11: the step's range is the CLI's (argparse caps at 360), so a value the CLI would refuse never starts it."""
    r, out, _s, args = _run_collect(tmp_path, 0, budget=budget)
    assert r.returncode == 0 and args.split()[-1] == budget and out == "flagged=no\n"


def test_the_budget_comes_from_the_input_then_the_variable_then_300():
    env = _steps(NAT, "collect")[COLLECT_STEP]["env"]
    assert env == {"BUDGET": "${{ inputs.budget || vars.NATIONAL_REQUEST_BUDGET || '300' }}"}
    assert cli.DEFAULT_BUDGET == 300


# ------------------------------------------------------------------------------------------------ the tree helper

def _helper(run):
    assert run.count(HELPER_START) == 1 and run.count(HELPER_END) == 1
    return run[run.index(HELPER_START):run.index(HELPER_END)]


def test_one_national_data_tree_helper_in_all_three_places():
    gate = _helper(_steps(NAT, "gate")[GATE_STEP]["run"])
    push = _helper(_steps(NAT, "push")[COMMIT_STEP]["run"])
    daily = _helper(_steps(DAILY, "gate")[LOOKUP_STEP]["run"])
    assert gate == push == daily
    assert 'national_listing() { git ls-tree -r -z "$1" -- data; }' in gate


def _seed_repo(tmp_path, files=SEED_FILES) -> tuple[Path, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    repo = tmp_path / "seedrepo"
    _git(tmp_path, "init", "-q", str(repo))
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo, _git(repo, "rev-parse", "HEAD")


def _listing_digest(repo, sha) -> str:
    out = subprocess.run(["git", "ls-tree", "-r", "-z", sha, "--", "data"], cwd=repo, capture_output=True,
                         check=True).stdout
    return hashlib.sha256(out).hexdigest()


def test_the_pinned_seed_is_what_the_cli_writes_for_a_directory_with_nothing_to_read(tmp_path, monkeypatch):
    """The shipped directory has no covered Legistar entry, so a run sends no request at all and writes exactly the
    seed (health {} and proposals []): a clean no-op whose push finds no change. When a covered entry lands (R2),
    this test is updated on purpose."""
    import urllib.request

    def no_network(*a, **k):
        raise AssertionError("a request was attempted")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    root = tmp_path / "seedrepo" / "data" / "national"
    root.mkdir(parents=True)
    assert cli.main([str(root), "--budget", "10"]) == 0
    files = {p.relative_to(root.parent.parent).as_posix(): p.read_text() for p in root.rglob("*") if p.is_file()}
    assert files == SEED_FILES
    repo, sha = _seed_repo(tmp_path / "x")
    pinned = _steps(NAT, "gate")[GATE_STEP]["env"]["NATIONAL_DATA_SEED_DIGEST"]
    assert _listing_digest(repo, sha) == pinned


NAT_CHECK_CASES = {
    "seed": (SEED_FILES, True),
    "bodies-and-cache": ({**SEED_FILES, "data/national/bodies/place-4164900.json": "{}\n",
                          "data/national/cache/place-4164900/1234.json": "{}\n"}, True),
    "outside-national": ({**SEED_FILES, "data/facts.json": "{}\n"}, False),
    "outside-data": ({**SEED_FILES, "README.md": "x\n"}, False),
    "bad-body-name": ({**SEED_FILES, "data/national/bodies/place-41.json": "{}\n"}, False),
    "dotdot-name": ({**SEED_FILES, "data/national/bodies/.place-4164900.json.tmp": "{}\n"}, False),
    "yml": ({**SEED_FILES, "data/national/directory.yml": "x\n"}, False),
    "nested-cache": ({**SEED_FILES, "data/national/cache/place-4164900/x/1.json": "{}\n"}, False),
    "newline-name": ({**SEED_FILES, "data/national/bodies/place-4164900.json\nx": "{}\n"}, False),
}


@pytest.mark.parametrize("case", sorted(NAT_CHECK_CASES))
def test_the_tree_helper_accepts_only_the_collector_s_files(tmp_path, case):
    files, ok = NAT_CHECK_CASES[case]
    repo, sha = _seed_repo(tmp_path, files)
    script = _helper(_steps(NAT, "gate")[GATE_STEP]["run"]) + (
        f'if national_check {sha} "$PWD/../listing"; then echo PASS; else echo "FAIL $why"; fi\n')
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + script], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("PASS" if ok else "FAIL"), r.stdout


def test_an_executable_or_a_symlink_fails_the_helper(tmp_path):
    for kind in ("exec", "link"):
        repo, _ = _seed_repo(tmp_path / kind)
        p = repo / "data" / "national" / "bodies" / "place-4164900.json"
        p.parent.mkdir()
        if kind == "exec":
            p.write_text("{}\n")
            p.chmod(0o755)
        else:
            os.symlink("../health.json", p)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", kind)
        script = _helper(_steps(NAT, "gate")[GATE_STEP]["run"]) + (
            'if national_check HEAD "$PWD/../listing"; then echo PASS; else echo FAIL; fi\n')
        r = subprocess.run(["bash", "-c", script], cwd=repo, capture_output=True, text=True)
        assert r.stdout.strip() == "FAIL", (kind, r.stdout, r.stderr)


# ------------------------------------------------------------------------------------------------ attestation gates

# `gh attestation verify FILE --flag value ...` as gh does it, against a store of attestations (ATTEST, a JSON list):
# it passes only when one attestation matches the file's digest and every constraint the step passes.
_GH = '''#!/usr/bin/env python3
import hashlib, json, os, sys
a = sys.argv[1:]
with open(os.environ["GH_CALLS"], "a") as f:
    f.write(" ".join(a) + "\\n")
if os.environ.get("GH_FAIL"):
    sys.exit(1)
assert a[:2] == ["attestation", "verify"] and os.environ.get("GH_TOKEN") == "t", a
digest = hashlib.sha256(open(a[2], "rb").read()).hexdigest()
opts, rest = {}, a[3:]
while rest:
    if rest[0] == "--deny-self-hosted-runners":
        opts["deny"], rest = True, rest[1:]
    else:
        opts[rest[0]], rest = rest[1], rest[2:]
store = json.load(open(os.environ["ATTEST"]))
ok = any(s["digest"] == digest and s["repo"] == opts.get("--repo") and s["identity"] == opts.get("--cert-identity")
         and s["source_ref"] == opts.get("--source-ref") and s["predicate"] == opts.get("--predicate-type")
         and (s["hosted"] or not opts.get("deny")) for s in store)
print("Verification succeeded" if ok else "no attestation matched", file=sys.stdout if ok else sys.stderr)
sys.exit(0 if ok else 1)
'''


def _attestation(digest, **over):
    return {"digest": digest, "repo": REPO, "identity": NAT_ID, "source_ref": "refs/heads/main", "predicate": SLSA,
            "hosted": True, **over}


ATTEST_OVERRIDES = {
    "national-main": ({}, True),
    "daily-update": ({"identity": DAILY_ID}, False),
    "other-branch": ({"identity": NAT_ID.replace("refs/heads/main", "refs/heads/x"), "source_ref": "refs/heads/x"},
                     False),
    "other-branch-same-id": ({"source_ref": "refs/heads/x"}, False),
    "other-repo": ({"repo": "someone/fork"}, False),
    "self-hosted": ({"hosted": False}, False),
    "other-predicate": ({"predicate": "https://example.com/other"}, False),
}


def _world(tmp_path, commits):
    """origin (bare) with main and, when `commits` is not None, branch national-data built from `commits` (oldest
    first: {path: text or None}; the first is a parentless commit). Returns (work clone at main, {i: sha})."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    origin, src, work = tmp_path / "origin.git", tmp_path / "src", tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(origin, "config", "uploadpack.allowFilter", "true")
    _git(tmp_path, "init", "-q", "-b", "main", str(src))
    (src / "README").write_text("code\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "code")
    _git(src, "push", "-q", f"file://{origin}", "main:refs/heads/main")
    shas = {}
    if commits is not None:
        nsrc = tmp_path / "nsrc"
        _git(tmp_path, "init", "-q", str(nsrc))
        _git(nsrc, "checkout", "-q", "--orphan", "national-data")
        for i, files in enumerate(commits):
            for rel, text in files.items():
                p = nsrc / rel
                if text is None:
                    _git(nsrc, "rm", "-q", rel)
                else:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(text)
            _git(nsrc, "add", "-A")
            _git(nsrc, "commit", "-q", "--allow-empty", "-m", f"n{i}")
            shas[i] = _git(nsrc, "rev-parse", "HEAD")
        _git(nsrc, "push", "-q", f"file://{origin}", "HEAD:refs/heads/national-data")
        shas["repo"] = nsrc
    _git(tmp_path, "clone", "-q", "--depth=1", "--branch", "main", f"file://{origin}", str(work))
    return work, shas


def _run(tmp_path, work, run, step_env, store=(), gh_fail=False):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "gh").write_text(_GH)
    (bindir / "gh").chmod(0o755)
    attest, calls, out = tmp_path / "attest.json", tmp_path / "gh-calls", tmp_path / "github-output"
    attest.write_text(json.dumps(list(store)))
    out.write_text("")
    runner = tmp_path / "runner"
    runner.mkdir(exist_ok=True)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_TOKEN": "t", "GH_CALLS": str(calls),
           "ATTEST": str(attest), "GITHUB_OUTPUT": str(out), "RUNNER_TEMP": str(runner), **step_env,
           **({"GH_FAIL": "1"} if gh_fail else {})}
    r = subprocess.run(["bash", "-c", run], cwd=work, env=env, capture_output=True, text=True)
    outputs = dict(ln.split("=", 1) for ln in out.read_text().splitlines() if "=" in ln)
    return r, outputs, calls.read_text().splitlines() if calls.exists() else []


def _gate(tmp_path, commits, attest=(), seed=None, gh_fail=False):
    work, shas = _world(tmp_path, commits)
    step = _steps(NAT, "gate")[GATE_STEP]
    store = [_attestation(_listing_digest(shas["repo"], shas[i]), **over) for i, over in attest]
    env = {"SHA": _git(work, "rev-parse", "HEAD"),
           "NATIONAL_DATA_SEED_DIGEST": step["env"]["NATIONAL_DATA_SEED_DIGEST"] if seed is None else seed}
    r, outputs, calls = _run(tmp_path, work, step["run"], env, store, gh_fail)
    return r, outputs, calls, shas, env["SHA"]


def test_the_gate_step_reads_only_its_env_and_pins_the_national_identity():
    step = _steps(NAT, "gate")[GATE_STEP]
    assert set(step["env"]) == {"GH_TOKEN", "SHA", "NATIONAL_DATA_SEED_DIGEST"} and "${{" not in step["run"]
    run = " ".join(step["run"].replace("\\\n", " ").split())
    assert (f"--repo {REPO} --cert-identity {NAT_ID} --source-ref refs/heads/main --predicate-type {SLSA} "
            "--deny-self-hosted-runners") in run
    lookup = " ".join(_steps(DAILY, "gate")[LOOKUP_STEP]["run"].replace("\\\n", " ").split())
    assert (f"--repo {REPO} --cert-identity {NAT_ID} --source-ref refs/heads/main --predicate-type {SLSA} "
            "--deny-self-hosted-runners") in lookup
    # and the records-data gate never accepts the national identity
    assert NAT_ID not in _steps(DAILY, "gate")["Check main's history and the records-data head"]["run"]


def test_no_national_data_yet_is_a_clean_no_op(tmp_path):
    r, outputs, calls, _s, sha = _gate(tmp_path, None)
    assert r.returncode == 0, r.stderr
    assert outputs == {"code": sha, "sha": "", "ready": "no"} and calls == []


def test_the_seed_is_accepted_without_an_attestation(tmp_path):
    r, outputs, calls, shas, sha = _gate(tmp_path, [SEED_FILES])
    assert r.returncode == 0, r.stderr
    assert outputs == {"code": sha, "sha": shas[0], "ready": "yes"} and calls == []


def test_a_seed_shaped_commit_with_a_parent_needs_an_attestation(tmp_path):
    r, outputs, _c, _s, _sha = _gate(tmp_path, [SEED_FILES, {"data/national/health.json": "{}\n"}])
    assert r.returncode == 2 and outputs == {}, r.stdout


@pytest.mark.parametrize("case", sorted(ATTEST_OVERRIDES))
def test_the_gate_accepts_only_an_attestation_by_this_workflow_on_main(tmp_path, case):
    over, ok = ATTEST_OVERRIDES[case]
    commits = [SEED_FILES, {"data/national/bodies/place-4164900.json": "{}\n"}]
    r, outputs, calls, shas, sha = _gate(tmp_path, commits, attest=[(1, over)])
    if ok:
        assert r.returncode == 0 and outputs == {"code": sha, "sha": shas[1], "ready": "yes"}, r.stderr
    else:
        assert r.returncode == 2 and outputs == {} and "::error::" in r.stdout, (r.stdout, r.stderr)
    assert len(calls) == 1


def test_the_gate_refuses_an_attested_tree_with_files_outside_national(tmp_path):
    commits = [SEED_FILES, {"data/facts.json": "{}\n"}]
    r, outputs, calls, _s, _sha = _gate(tmp_path, commits, attest=[(1, {})])
    assert r.returncode == 2 and outputs == {} and calls == []


def test_the_gate_fails_closed_when_github_cannot_be_read(tmp_path):
    r, outputs, _c, _s, _sha = _gate(tmp_path, [SEED_FILES, {"data/national/proposals.json": "[1]\n"}],
                                     attest=[(1, {})], gh_fail=True)
    assert r.returncode == 2 and outputs == {}


def test_the_gate_refuses_a_checkout_that_is_not_the_run_s_commit(tmp_path):
    work, _ = _world(tmp_path, [SEED_FILES])
    step = _steps(NAT, "gate")[GATE_STEP]
    r, outputs, _c = _run(tmp_path, work, step["run"], {"SHA": "0" * 40, "NATIONAL_DATA_SEED_DIGEST": ""})
    assert r.returncode == 2 and outputs == {}


# ------------------------------------------------------------------------------------------------ D2 lookup

def _lookup(tmp_path, commits, attest=(), gh_fail=False):
    work, shas = _world(tmp_path, commits)
    step = _steps(DAILY, "gate")[LOOKUP_STEP]
    store = [_attestation(_listing_digest(shas["repo"], shas[i]), **over) for i, over in attest]
    r, outputs, calls = _run(tmp_path, work, step["run"], {"NATIONAL_LOOKBACK": step["env"]["NATIONAL_LOOKBACK"]},
                             store, gh_fail)
    assert r.returncode == 0, (r.stdout, r.stderr)       # soft: never fails the daily gate
    return outputs, calls, shas, r.stdout


def test_the_lookup_step_is_soft_and_cannot_hold_a_clarksville_run():
    gate = DAILY["jobs"]["gate"]
    step = _steps(DAILY, "gate")[LOOKUP_STEP]
    assert step["continue-on-error"] is True and step["timeout-minutes"] <= 3 and step["if"] == "success()"
    assert set(step["env"]) == {"GH_TOKEN", "NATIONAL_LOOKBACK"} and "${{" not in step["run"]
    assert gate["outputs"]["national_sha"] == "${{ steps.national.outputs.sha }}"
    assert gate["permissions"] == {"contents": "read", "pull-requests": "read", "attestations": "read"}
    assert DAILY["jobs"]["update"]["needs"] == "gate"            # no new job in the deploy's chain


def test_every_gate_step_has_a_timeout_and_the_gate_s_budget_holds_them_all():
    """Architecture 12.3 #10, 12.1 row 1 (`national-isolation/gate-timeout-budget`, S2b finding 3): a job timeout fails
    the job whatever continue-on-error says, so the gate's budget is at least the sum of its step timeouts plus one
    minute for setup and post steps. A slow D2 lookup then ends at its own timeout and the gate still succeeds."""
    gate = DAILY["jobs"]["gate"]
    mins = [s.get("timeout-minutes") for s in gate["steps"]]
    assert all(isinstance(m, int) and m >= 1 for m in mins), mins
    assert gate["timeout-minutes"] >= sum(mins) + 1, (gate["timeout-minutes"], mins)
    assert gate["timeout-minutes"] <= 15                       # still a short, read-only job


def test_the_lookup_reads_the_attested_head(tmp_path):
    outputs, _c, shas, _o = _lookup(tmp_path, [SEED_FILES, {"data/national/health.json": '{"a": 1}\n'}],
                                    attest=[(1, {})])
    assert outputs == {"sha": shas[1]}


def test_the_lookup_falls_back_to_the_newest_attested_commit_and_warns(tmp_path):
    commits = [SEED_FILES, {"data/national/health.json": '{"a": 1}\n'}, {"data/national/health.json": '{"a": 2}\n'}]
    outputs, _c, shas, out = _lookup(tmp_path, commits, attest=[(1, {})])
    assert outputs == {"sha": shas[1]} and "::warning::national-data's head" in out


@pytest.mark.parametrize("case", sorted(c for c, (_o, ok) in ATTEST_OVERRIDES.items() if not ok))
def test_the_lookup_refuses_an_attestation_by_another_workflow_or_branch(tmp_path, case):
    over, _ok = ATTEST_OVERRIDES[case]
    outputs, calls, _s, _o = _lookup(tmp_path, [SEED_FILES, {"data/national/health.json": '{"a": 1}\n'}],
                                     attest=[(1, over)])
    assert outputs == {"sha": ""} and len(calls) == 2           # both commits tried, neither accepted


def test_the_lookup_never_reads_the_seed(tmp_path):
    outputs, _c, _s, _o = _lookup(tmp_path, [SEED_FILES])
    assert outputs == {"sha": ""}


def test_the_lookup_skips_an_attested_tree_with_files_outside_national(tmp_path):
    commits = [SEED_FILES, {"data/national/health.json": '{"a": 1}\n'}, {"data/facts.json": "{}\n"}]
    outputs, calls, shas, out = _lookup(tmp_path, commits, attest=[(1, {}), (2, {})])
    assert outputs == {"sha": shas[1]} and len(calls) == 1 and "is not read" in out


def test_the_lookup_with_no_branch_or_no_github_is_no_national_data(tmp_path):
    outputs, calls, _s, _o = _lookup(tmp_path, None)
    assert outputs == {"sha": ""} and calls == []
    outputs, _c, _s, out = _lookup(tmp_path / "b", [SEED_FILES, {"data/national/health.json": '{"a": 1}\n'}],
                                   attest=[(1, {})], gh_fail=True)
    assert outputs == {"sha": ""}


def test_the_lookup_looks_back_at_most_the_configured_commits(tmp_path):
    commits = [SEED_FILES] + [{"data/national/health.json": f'{{"a": {i}}}\n'} for i in range(1, 13)]
    outputs, calls, _s, _o = _lookup(tmp_path, commits, attest=[(1, {})])      # 12 newer unattested commits
    assert outputs == {"sha": ""} and len(calls) == 10


# ------------------------------------------------------------------------------------------------ D2 in the update job

def test_the_update_job_reads_n_outside_data_and_passes_it_to_the_build_only():
    steps = _steps(DAILY, "update")
    names = list(steps)
    co = steps["Check out the gate's national-data commit (N)"]
    assert co["continue-on-error"] is True and co["if"] == "success() && needs.gate.outputs.national_sha != ''"
    assert names.index("Put D's data/ into data/") < names.index(co["name"]) < names.index(PUT_STEP) \
        < names.index("Collect (polite fetch, parse, verify)")
    put = steps[PUT_STEP]
    assert put["continue-on-error"] is True and put["id"] == "national"
    for name in ("Collect (polite fetch, parse, verify)", "Rebuild site from committed data"):
        assert steps[name]["env"]["RECORDS_NATIONAL_DATA"] == "${{ steps.national.outputs.root }}"
    users = [n for n, s in steps.items() if "RECORDS_NATIONAL_DATA" in (s.get("env") or {})]
    assert users == ["Collect (polite fetch, parse, verify)", "Rebuild site from committed data"]
    up = steps["Upload refreshed data"]["with"]["path"]
    assert ".national-data" not in up and "national" not in up.replace("records-data", "")


def test_every_continue_on_error_step_has_its_own_timeout():
    """Architecture 12.3 #10, 12.1 row 4 (`national-isolation/put-step-no-timeout`, N1): continue-on-error does not
    survive a job timeout, so a step that may fail softly must also end softly, well inside its job's budget. "Put
    N's data/national" ends within 2 minutes."""
    for wf in (DAILY, NAT):
        for jname, job in wf["jobs"].items():
            soft = [s for s in job["steps"] if s.get("continue-on-error")]
            for s in soft:
                m = s.get("timeout-minutes")
                assert isinstance(m, int) and 1 <= m < job["timeout-minutes"], (jname, s.get("name"), m)
    assert _steps(DAILY, "update")[PUT_STEP]["timeout-minutes"] == 2


def _put(tmp_path, checkout="success", n=None, data=True, dest_exists=False):
    work = tmp_path / "ws"
    work.mkdir()
    nd = work / ".national-data"
    _git(tmp_path, "init", "-q", str(nd))
    if data:
        (nd / "data" / "national").mkdir(parents=True)
        (nd / "data" / "national" / "health.json").write_text("{}\n")
    _git(nd, "commit", "-q", "--allow-empty", "-m", "n")
    sha = _git(nd, "rev-parse", "HEAD")
    runner = tmp_path / "runner"
    runner.mkdir()
    if dest_exists:
        (runner / "national").mkdir()
    out = tmp_path / "out"
    out.write_text("")
    env = {**os.environ, "N": n or sha, "CHECKOUT": checkout, "RUNNER_TEMP": str(runner), "GITHUB_OUTPUT": str(out)}
    r = subprocess.run(["bash", "-c", _steps(DAILY, "update")[PUT_STEP]["run"]], cwd=work, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert not nd.exists()                                  # the checkout is always removed
    return out.read_text(), runner


def test_the_put_step_moves_n_s_national_folder_outside_the_checkout(tmp_path):
    out, runner = _put(tmp_path)
    assert out == f"root={runner / 'national'}\n" and (runner / "national" / "health.json").read_text() == "{}\n"


@pytest.mark.parametrize("kw", [{"checkout": "failure"}, {"n": "f" * 40}, {"data": False}, {"dest_exists": True}],
                         ids=["checkout-failed", "not-n", "no-data", "dest-exists"])
def test_the_put_step_gives_no_root_on_anything_unexpected(tmp_path, kw):
    out, _r = _put(tmp_path, **kw)
    assert out == ""


# ------------------------------------------------------------------------------------------------ push job

def _push_world(tmp_path, artifact: dict):
    """origin with national-data at the seed N, a checkout of N (as actions/checkout leaves it), and the artifact
    folder in RUNNER_TEMP. Returns (work, origin, runner, N)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    repo, n = _seed_repo(tmp_path)
    _git(repo, "push", "-q", f"file://{origin}", "HEAD:refs/heads/national-data")
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", "--branch", "national-data", f"file://{origin}", str(work))
    _git(work, "checkout", "-q", "--detach", n)
    runner = tmp_path / "runner"
    art = runner / "national-data"
    art.mkdir(parents=True)
    for rel, text in artifact.items():
        (art / rel).parent.mkdir(parents=True, exist_ok=True)
        (art / rel).write_text(text)
    return work, origin, runner, n


def _push_run(tmp_path, work, runner, name, env):
    out = tmp_path / "out"
    out.write_text("")
    full = {**os.environ, "RUNNER_TEMP": str(runner), "GITHUB_OUTPUT": str(out), **env,
            "GIT_AUTHOR_DATE": "2026-11-20T00:00:00Z", "GIT_COMMITTER_DATE": "2026-11-20T00:00:00Z"}
    r = subprocess.run(["bash", "-c", _steps(NAT, "push")[name]["run"]], cwd=work, env=full, capture_output=True,
                       text=True)
    return r, dict(ln.split("=", 1) for ln in out.read_text().splitlines() if "=" in ln)


GOOD_ARTIFACT = {"health.json": '{"place-4164900": {}}\n', "proposals.json": "[]\n",
                 "bodies/place-4164900.json": "{}\n", "cache/place-4164900/77.json": "{}\n"}


def test_the_push_job_commits_only_data_national_on_n_and_pushes_national_data(tmp_path):
    work, origin, runner, n = _push_world(tmp_path, GOOD_ARTIFACT)
    r, _o = _push_run(tmp_path, work, runner, VALIDATE_STEP, {})
    assert r.returncode == 0, r.stdout
    r, outputs = _push_run(tmp_path, work, runner, COMMIT_STEP, {"N": n})
    assert r.returncode == 0 and outputs["committed"] == "yes", (r.stdout, r.stderr)
    sha = outputs["sha"]
    assert _git(work, "rev-parse", f"{sha}^") == n
    changed = _git(work, "diff-tree", "-r", "--no-commit-id", "--name-only", n, sha).splitlines()
    assert changed and all(p.startswith("data/national/") for p in changed)
    assert _git(work, "ls-tree", "--name-only", sha) == "data"
    listing = runner / "national-data-listing"
    assert hashlib.sha256(listing.read_bytes()).hexdigest() == _listing_digest(work, sha)
    r, _o = _push_run(tmp_path, work, runner, PUSH_STEP, {"SHA": sha})
    assert r.returncode == 0, r.stderr
    assert _git(origin, "rev-parse", "refs/heads/national-data") == sha
    assert _git(origin, "for-each-ref", "--format=%(refname)") == "refs/heads/national-data"


def test_no_change_commits_attests_and_pushes_nothing(tmp_path):
    work, origin, runner, n = _push_world(tmp_path, {"health.json": "{}\n", "proposals.json": "[]\n"})
    r, outputs = _push_run(tmp_path, work, runner, COMMIT_STEP, {"N": n})
    assert r.returncode == 0 and "committed" not in outputs and "No national data changes." in r.stdout
    steps = _steps(NAT, "push")
    for name in ("Attest the national-data listing", PUSH_STEP):
        assert steps[name]["if"] == "steps.commit.outputs.committed == 'yes'"
    assert list(steps).index("Attest the national-data listing") < list(steps).index(PUSH_STEP)


@pytest.mark.parametrize("extra", [{"directory.yml": "x"}, {"bodies/bad.json": "{}"}, {"notes.txt": "x"},
                                   {"cache/place-4164900/a/1.json": "{}"}, {"bodies/.place-4164900.json.tmp": "{}"},
                                   {"bodies/place-4164900 .json": "{}"}],
                         ids=["yml", "bad-id", "txt", "nested", "temp-file", "space"])
def test_the_validation_refuses_anything_but_the_collector_s_files(tmp_path, extra):
    work, _o, runner, _n = _push_world(tmp_path, {**GOOD_ARTIFACT, **extra})
    r, _x = _push_run(tmp_path, work, runner, VALIDATE_STEP, {})
    assert r.returncode != 0 and "::error::" in r.stdout


def test_the_validation_refuses_a_symlink_or_missing_health(tmp_path):
    work, _o, runner, _n = _push_world(tmp_path, GOOD_ARTIFACT)
    os.symlink("/etc/passwd", runner / "national-data" / "bodies" / "place-4100001.json")
    r, _x = _push_run(tmp_path, work, runner, VALIDATE_STEP, {})
    assert r.returncode != 0
    work, _o, runner, _n = _push_world(tmp_path / "b", {"proposals.json": "[]\n"})
    r, _x = _push_run(tmp_path / "b", work, runner, VALIDATE_STEP, {})
    assert r.returncode != 0 and "no health.json" in r.stdout


def test_the_commit_step_refuses_a_checkout_that_is_not_n(tmp_path):
    work, _o, runner, _n = _push_world(tmp_path, GOOD_ARTIFACT)
    r, outputs = _push_run(tmp_path, work, runner, COMMIT_STEP, {"N": "0" * 40})
    assert r.returncode != 0 and outputs == {}


def test_a_concurrent_push_to_national_data_fails_loudly(tmp_path):
    work, origin, runner, n = _push_world(tmp_path, GOOD_ARTIFACT)
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", "--branch", "national-data", f"file://{origin}", str(other))
    (other / "data" / "national" / "proposals.json").write_text("[1]\n")
    _git(other, "commit", "-qam", "moved")
    _git(other, "push", "-q", "origin", "HEAD:refs/heads/national-data")
    r, outputs = _push_run(tmp_path, work, runner, COMMIT_STEP, {"N": n})
    r, _x = _push_run(tmp_path, work, runner, PUSH_STEP, {"SHA": outputs["sha"]})
    assert r.returncode != 0


def test_the_attestation_subject_is_the_commit_s_listing():
    attest = _steps(NAT, "push")["Attest the national-data listing"]
    assert attest["uses"].startswith("actions/attest-build-provenance@96278af6caaf10aea03fd8d33a09a777ca52d62f")
    assert attest["with"] == {"subject-path": "${{ runner.temp }}/national-data-listing"}
    assert 'listing="$RUNNER_TEMP/national-data-listing"' in _steps(NAT, "push")[COMMIT_STEP]["run"]


# ------------------------------------------------------------------------------------------------ report job

def test_the_report_issue_is_fixed_text_and_job_results_only():
    job = NAT["jobs"]["report"]
    cond = " ".join(job["if"].split())
    for want in ("always()", "needs.collect.result == 'failure'", "needs.collect.result == 'cancelled'",
                 "needs.push.result == 'failure'", "needs.gate.result == 'failure'",
                 "needs.collect.outputs.flagged == 'yes'"):
        assert want in cond, want
    step = job["steps"][0]
    assert len(job["steps"]) == 1 and "uses" not in step and "${{" not in step["run"]
    assert "--app github-actions" in step["run"] and "--body-file" in step["run"]
    assert step["env"]["NATIONAL_TITLE"] == "National update: run failed or flagged"
