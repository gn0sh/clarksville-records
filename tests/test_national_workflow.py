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
    # 12.3 #11 (S2b finding 4, S2c finding 1; 12.6): the collect job runs on a scheduled run's first attempt, or when
    # gn0sh both started and triggered it; the truth table is test_the_collect_if_caps_every_route_of_12_6
    assert " ".join(jobs["collect"]["if"].split()) == COLLECT_IF
    assert "status" not in jobs["push"]["if"] and "always()" not in jobs["push"]["if"]  # implied success(): a
    #                                                                       skipped collect skips the push too
    assert "github.ref == 'refs/heads/main'" in jobs["report"]["if"]


COLLECT_IF = ("needs.gate.outputs.ready == 'yes' && github.ref == 'refs/heads/main' && "
              "((github.event_name == 'schedule' && github.run_attempt == '1') || "
              "(github.actor == 'gn0sh' && github.triggering_actor == 'gn0sh'))")


def _expr(text: str, ctx: dict):
    """A GitHub Actions expression over `==`, `!=`, `&&`, `||`, `!`, parentheses, '...' literals and context names
    (dotted, read from `ctx`; a missing one is null), with GitHub's comparison rules: strings compare ignoring case,
    a string against a number is compared as a number. Anything else in the text is an error, so a new operator or
    function in the `if:` fails the test instead of being guessed at."""
    toks = re.findall(r"\s*(==|!=|&&|\|\||!|\(|\)|'(?:[^']|'')*'|[A-Za-z_][A-Za-z0-9_.-]*|\S)", text)
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def take(want=None):
        nonlocal pos
        tok = peek()
        assert tok is not None and (want is None or tok == want), (want, tok, text)
        pos += 1
        return tok

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return float("nan")

    def eq(a, b):
        if isinstance(a, str) and isinstance(b, str):
            return a.lower() == b.lower()
        if isinstance(a, (int, float)) or isinstance(b, (int, float)):
            return num(a) == num(b)
        return a == b

    def atom():
        tok = take()
        if tok == "(":
            v = disj()
            take(")")
            return v
        if tok == "!":
            return not atom()
        if tok.startswith("'"):
            return tok[1:-1].replace("''", "'")
        assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", tok) and tok not in ("true", "false", "null"), tok
        assert peek() != "(", f"function call {tok}() is not evaluated here"
        return ctx.get(tok)

    def comp():
        v = atom()
        while peek() in ("==", "!="):
            op = take()
            r = eq(v, atom())
            v = r if op == "==" else not r
        return v

    def conj():
        v = comp()
        while peek() == "&&":
            take()
            r = comp()
            v = v and r
        return v

    def disj():
        v = conj()
        while peek() == "||":
            take()
            r = conj()
            v = v or r
        return v

    v = disj()
    assert pos == len(toks), (toks[pos:], text)
    return bool(v)


def _route(event, attempt="1", actor="gn0sh", triggering="gn0sh", ref="refs/heads/main", ready="yes") -> dict:
    return {"github.event_name": event, "github.run_attempt": attempt, "github.actor": actor,
            "github.triggering_actor": triggering, "github.ref": ref, "needs.gate.outputs.ready": ready}


# 12.6 routes 1-7 and 9 (12.3 #11 v2). On a scheduled run `actor` is the account the schedule is tied to (whoever
# last changed the cron), which may be any account with write access; `triggering_actor` is whoever started the attempt.
COLLECT_ROUTES = {
    "1-schedule-first-attempt": (_route("schedule", actor="bot", triggering="bot"), True),
    "1-schedule-first-attempt-tied-to-gn0sh": (_route("schedule"), True),
    "2-schedule-rerun-by-another": (_route("schedule", "2", actor="bot", triggering="mallory"), False),
    "2-schedule-rerun-by-another-tied-to-gn0sh": (_route("schedule", "2", triggering="mallory"), False),
    "2-schedule-rerun-by-the-tied-account": (_route("schedule", "2", actor="mallory", triggering="mallory"), False),
    "2-schedule-attempt-10-by-another": (_route("schedule", "10", actor="bot", triggering="mallory"), False),
    "3-schedule-rerun-by-gn0sh-tied-to-gn0sh": (_route("schedule", "2"), True),
    "3-schedule-rerun-by-gn0sh-tied-to-another": (_route("schedule", "2", actor="bot"), False),
    "4-dispatch-by-gn0sh": (_route("workflow_dispatch"), True),
    "4-dispatch-by-gn0sh-any-case": (_route("workflow_dispatch", actor="Gn0sh", triggering="GN0SH"), True),
    "5-dispatch-by-another": (_route("workflow_dispatch", actor="mallory", triggering="mallory"), False),
    "5-dispatch-named-like-gn0sh": (_route("workflow_dispatch", actor="gn0sh-bot", triggering="gn0sh-bot"), False),
    "6-gn0sh-dispatch-rerun-by-another": (_route("workflow_dispatch", "2", triggering="mallory"), False),
    "7-dispatch-rerun-by-gn0sh": (_route("workflow_dispatch", "2"), True),
    "9-schedule-other-ref": (_route("schedule", ref="refs/heads/x"), False),
    "9-dispatch-by-gn0sh-other-ref": (_route("workflow_dispatch", ref="refs/heads/x"), False),
    "9-dispatch-by-gn0sh-tag": (_route("workflow_dispatch", ref="refs/tags/main"), False),
    "gate-not-ready-schedule": (_route("schedule", ready="no"), False),
    "gate-not-ready-dispatch": (_route("workflow_dispatch", ready="no"), False),
    "gate-no-output-dispatch": (_route("workflow_dispatch", ready=None), False),
    # 12.6 route 10: the `if:` alone would pass any event gn0sh starts, so only `on:` keeps them out (next test)
    "10-other-event-by-gn0sh-if-alone": (_route("push"), True),
    "10-other-event-by-another-if-alone": (_route("push", actor="mallory", triggering="mallory"), False),
}


@pytest.mark.parametrize("route", sorted(COLLECT_ROUTES))
def test_the_collect_if_caps_every_route_of_12_6(route):
    """Architecture 12.6 (`national-budget`), 12.3 #11 v2: only a scheduled run's first attempt and runs gn0sh both
    started and triggered reach the collect job; every re-run of a scheduled run by another account is skipped."""
    ctx, runs = COLLECT_ROUTES[route]
    assert _expr(NAT["jobs"]["collect"]["if"], ctx) is runs


def test_the_expression_evaluator_reads_the_if_as_github_does():
    """The evaluator itself, so the truth table cannot pass through a parser that drops a clause."""
    assert _expr("a == '1'", {"a": "1"}) and not _expr("a == '1'", {"a": "2"}) and _expr("a == '1'", {"a": 1})
    assert not _expr("a == '1'", {}) and _expr("a != 'x'", {"a": "y"}) and _expr("!(a == 'x')", {"a": "y"})
    assert _expr("a == 'X' && b == 'y' || c == 'z'", {"c": "z"})
    assert not _expr("a == 'x' && (b == 'y' || c == 'z')", {"c": "z"})
    for bad in ("contains(a, 'x')", "a == 'x' || always()", "a == 'x' ||", "a = 'x'"):
        with pytest.raises(AssertionError):
            _expr(bad, {"a": "x"})


def test_on_holds_only_schedule_and_dispatch_and_the_budget_is_capped():
    """12.6 routes 10 and 14: no other event can start this file, and the run budget is the input, the variable or
    300, checked 1-360 in the step (test_a_bad_budget_collects_nothing runs the regex on 0 and 361)."""
    on = _on(NAT)
    assert set(on) == {"schedule", "workflow_dispatch"} and len(on["schedule"]) == 2
    assert set(on["workflow_dispatch"]) == {"inputs"} and set(on["workflow_dispatch"]["inputs"]) == {"budget"}
    step = _steps(NAT, "collect")[COLLECT_STEP]
    assert step["env"]["BUDGET"] == "${{ inputs.budget || vars.NATIONAL_REQUEST_BUDGET || '300' }}"


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
                    'for f in "${GITHUB_ENV:-}" "${GITHUB_PATH:-}" "${GITHUB_STATE:-}"; do\n'
                    '  [ -n "$f" ] && echo leak=1 >> "$f"\ndone\n'
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
# it passes only when one attestation matches the file's digest and every constraint the step passes. With
# `--format json --jq SOURCE_JQ` it prints, one per line, the source commit (sourceRepositoryDigest) of each matching
# attestation: its "source", or the commit checked out here when that is None (S2b finding 5).
SOURCE_JQ = ".[].verificationResult.signature.certificate.sourceRepositoryDigest"
_GH = '''#!/usr/bin/env python3
import hashlib, json, os, subprocess, sys
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
hits = [s for s in store if s["digest"] == digest and s["repo"] == opts.get("--repo")
        and s["identity"] == opts.get("--cert-identity") and s["source_ref"] == opts.get("--source-ref")
        and s["predicate"] == opts.get("--predicate-type") and (s["hosted"] or not opts.get("deny"))]
if not hits:
    print("no attestation matched", file=sys.stderr)
    sys.exit(1)
if "--format" in opts:
    assert opts["--format"] == "json" and opts["--jq"] == "%s", opts
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    for s in hits:
        print(head if s["source"] is None else s["source"])
else:
    print("Verification succeeded")
sys.exit(0)
''' % SOURCE_JQ


def _attestation(digest, **over):
    return {"digest": digest, "repo": REPO, "identity": NAT_ID, "source_ref": "refs/heads/main", "predicate": SLSA,
            "hosted": True, "source": None, **over}


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


def _later_main_commit(tmp_path) -> str:
    """A commit pushed to origin's main after the run's checkout (`_world`'s work clone): the ruleset-bypass race of
    S2b finding 5, an attesting run of a main commit that is not on the run's first-parent line."""
    src = tmp_path / "src"
    (src / "README").write_text("later\n")
    _git(src, "commit", "-qam", "later")
    _git(src, "push", "-q", f"file://{tmp_path / 'origin.git'}", "main:refs/heads/main")
    return _git(src, "rev-parse", "HEAD")


def _gate_world(tmp_path, commits, sources):
    """The national gate on N = commits[-1], attested once per entry of `sources` (a source commit, or "later" for
    a main commit pushed after the checkout)."""
    work, shas = _world(tmp_path, commits)
    later = _later_main_commit(tmp_path)
    digest = _listing_digest(shas["repo"], shas[len(commits) - 1])
    store = [_attestation(digest, source=later if src == "later" else src) for src in sources]
    step = _steps(NAT, "gate")[GATE_STEP]
    sha = _git(work, "rev-parse", "HEAD")
    r, outputs, calls = _run(tmp_path, work, step["run"],
                             {"SHA": sha, "NATIONAL_DATA_SEED_DIGEST": step["env"]["NATIONAL_DATA_SEED_DIGEST"]}, store)
    return r, outputs, calls, shas, sha


@pytest.mark.parametrize("sources", [["later"], ["f" * 40], [""], ["not-a-sha"]],
                         ids=["later-main-commit", "unknown-commit", "empty", "garbage"])
def test_the_gate_refuses_an_attestation_from_a_commit_off_this_run_s_line(tmp_path, sources):
    """12.2 D-ISO-4 (S2b finding 5): the attesting run's source commit must be on this commit's first-parent line."""
    r, outputs, calls, _s, _sha = _gate_world(tmp_path, [SEED_FILES, {"data/national/health.json": '{"a": 1}\n'}],
                                              sources)
    assert r.returncode == 2 and outputs == {} and "first-parent line" in r.stdout, (r.stdout, r.stderr)
    assert len(calls) == 1 and f"--format json --jq {SOURCE_JQ}" in calls[0]


def test_the_gate_accepts_when_one_attestation_s_source_is_on_this_run_s_line(tmp_path):
    r, outputs, _c, shas, sha = _gate_world(tmp_path, [SEED_FILES, {"data/national/health.json": '{"a": 1}\n'}],
                                            ["later", None])
    assert r.returncode == 0 and outputs == {"code": sha, "sha": shas[1], "ready": "yes"}, (r.stdout, r.stderr)


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


def test_the_lookup_skips_an_attestation_from_a_commit_off_this_run_s_line(tmp_path):
    """12.2 D-ISO-4 (S2b finding 5): the head's attestation comes from a main commit pushed after S, so it is not
    read; the older commit attested from S's own line is, with a warning."""
    commits = [SEED_FILES, {"data/national/health.json": '{"a": 1}\n'}, {"data/national/health.json": '{"a": 2}\n'}]
    work, shas = _world(tmp_path, commits)
    later = _later_main_commit(tmp_path)
    store = [_attestation(_listing_digest(shas["repo"], shas[2]), source=later),
             _attestation(_listing_digest(shas["repo"], shas[1]))]
    step = _steps(DAILY, "gate")[LOOKUP_STEP]
    r, outputs, calls = _run(tmp_path, work, step["run"], {"NATIONAL_LOOKBACK": step["env"]["NATIONAL_LOOKBACK"]},
                             store)
    assert r.returncode == 0 and outputs == {"sha": shas[1]}, (r.stdout, r.stderr)
    assert len(calls) == 2 and all(f"--format json --jq {SOURCE_JQ}" in c for c in calls)
    assert f"national-data {shas[2]} is attested, but by no run of a commit on this commit's first-parent line" \
        in r.stdout
    store = [_attestation(_listing_digest(shas["repo"], shas[2]), source=later)]
    (tmp_path / "b").mkdir()
    r, outputs, _c = _run(tmp_path / "b", work, step["run"], {"NATIONAL_LOOKBACK": "10"}, store)
    assert r.returncode == 0 and outputs == {"sha": ""}


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


def test_the_two_workflows_are_not_coupled():
    """Architecture 12.3 #10, 12.1 rows 21-23: nothing national-update.yml does or fails to do reaches a daily job.
    No daily job needs a job outside its own chain or a national-only step's outcome; neither workflow triggers the
    other; they share no concurrency group; national-update.yml saves or restores no cache and pushes only
    national-data."""
    daily_jobs = DAILY["jobs"]
    for name, job in daily_jobs.items():
        needs = job.get("needs") or []
        needs = [needs] if isinstance(needs, str) else needs
        assert set(needs) <= set(daily_jobs) and "national" not in " ".join(needs), (name, needs)
        cond = str(job.get("if", ""))
        assert "steps.national" not in cond and "national_sha" not in cond, name     # no job is gated on D2
    # the only daily steps that read D2's outcome are the soft ones that bring N beside the build
    readers = sorted(s["name"] for j in daily_jobs.values() for s in j["steps"]
                     if "national_sha" in str(s.get("if", "")) or "steps.national" in str(s.get("if", ""))
                     or "national_checkout" in str(s.get("env", "")))
    assert readers == sorted(["Check out the gate's national-data commit (N)", PUT_STEP])
    assert all(_steps(DAILY, "update")[n]["continue-on-error"] is True for n in readers)
    assert set(_on(NAT)) == {"schedule", "workflow_dispatch"} and "workflow_run" not in _on(DAILY)
    assert "workflow_call" not in _on(NAT) and "workflow_call" not in _on(DAILY)
    assert NAT["concurrency"]["group"] != DAILY["concurrency"]["group"]
    assert "concurrency" not in yaml.safe_dump(NAT["jobs"])
    for job in NAT["jobs"].values():
        for s in job["steps"]:
            assert "actions/cache" not in s.get("uses", ""), s.get("name")
            assert "cache" not in (s.get("with") or {}), s.get("name")
            assert "gh workflow run" not in s.get("run", "") and "dispatches" not in s.get("run", "")
    pushes = [ln.strip() for j in NAT["jobs"].values() for s in j["steps"] for ln in s.get("run", "").splitlines()
              if "git push" in ln]
    assert pushes == ['git push origin "HEAD:refs/heads/national-data"']


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


# ------------------------------------------------------------------------------------------------ D-ISO-9 issue

DEGRADED_STEP = "Open or update the national pages degraded issue"


def _degraded(tmp_path, run_log, open_issue=""):
    """The D-ISO-9 step with a `gh` stub that records its calls and the body file; returns (calls, body)."""
    work, bindir = tmp_path / "work", tmp_path / "bin"
    (work / "build").mkdir(parents=True)
    bindir.mkdir()
    if run_log is not None:
        (work / "build" / "run-log.json").write_text(run_log if isinstance(run_log, str) else json.dumps(run_log))
    calls, body = tmp_path / "calls", tmp_path / "body"
    (bindir / "gh").write_text("#!/bin/bash\n"
                               f'echo "$@" >> "{calls}"\n'
                               f'if [ "$2" = list ]; then echo "{open_issue}"; fi\n'
                               'for ((i=1; i<=$#; i++)); do j=$((i+1)); '
                               f'if [ "${{!i}}" = --body-file ]; then cp "${{!j}}" "{body}"; fi; done\n')
    (bindir / "gh").chmod(0o755)
    step = _steps(DAILY, "update")[DEGRADED_STEP]
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "RUNNER_TEMP": str(tmp_path),
           "GITHUB_SERVER_URL": "https://x", "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "1", "GH_TOKEN": "t",
           "NAT_TITLE": step["env"]["NAT_TITLE"]}
    r = subprocess.run(["bash", "-c", step["run"]], cwd=work, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return (calls.read_text().splitlines() if calls.exists() else []), (body.read_text() if body.exists() else "")


def test_the_degraded_issue_step_is_soft_main_only_and_fixed_text():
    step = _steps(DAILY, "update")[DEGRADED_STEP]
    assert step["if"] == "always() && github.ref == 'refs/heads/main'"
    assert step["continue-on-error"] is True and step["timeout-minutes"] <= 5 and "${{" not in step["run"]
    assert step["env"] == {"GH_TOKEN": "${{ github.token }}", "NAT_TITLE": "Daily update: national pages degraded"}
    assert "--app github-actions" in step["run"] and "--body-file" in step["run"]
    names = list(_steps(DAILY, "update"))
    assert names.index("Site checks") < names.index(DEGRADED_STEP) < names.index("Upload refreshed data")


@pytest.mark.skipif(not __import__("shutil").which("jq"), reason="jq not installed")
@pytest.mark.parametrize("run_log", [None, "{not json", {}, {"national": "off"}, {"national": "built"},
                                     {"national": "built", "national_states": {}}, {"rpc": {"exit": 0}}],
                         ids=["no-log", "not-json", "empty", "off", "built", "built-no-states", "no-key"])
def test_no_degrade_opens_nothing(tmp_path, run_log):
    calls, _b = _degraded(tmp_path, run_log)
    assert calls == []


@pytest.mark.skipif(not __import__("shutil").which("jq"), reason="jq not installed")
@pytest.mark.parametrize("open_issue", ["", "9"])
def test_a_degraded_build_opens_or_comments_on_one_issue(tmp_path, open_issue):
    calls, body = _degraded(tmp_path, {"national": "degraded"}, open_issue=open_issue)
    assert calls[-1].startswith("issue comment 9" if open_issue else
                                "issue create --repo o/r --title Daily update: national pages degraded")
    assert len(calls) == 2 and "national: degraded; governments degraded: 0" in body and "https://x/o/r/actions/runs/1" \
        in body


@pytest.mark.skipif(not __import__("shutil").which("jq"), reason="jq not installed")
def test_a_degraded_government_is_named_by_id_and_state_word_only(tmp_path):
    """The body holds only ids and state words that pass the step's checks: any other text is "unknown"."""
    sentinel = "SENTINEL-ITEM-TEXT"
    states = {"place-4715160": "withheld-items", "county-47125": "adapter-error",
              f"place-1 {sentinel}": "bad-date", "place-0000001": f"bad-date {sentinel}",
              "sde-12345": {"x": sentinel}, "cousub-123456\n- injected: line": "render-error"}
    calls, body = _degraded(tmp_path, {"national": "built", "national_states": states})
    assert calls[-1].startswith("issue create")
    assert sentinel not in body and "injected" not in body
    assert "- place-4715160: withheld-items\n" in body and "- county-47125: adapter-error\n" in body
    assert "- unknown: unknown\n" in body and "- place-0000001: unknown\n" in body and "- sde-12345: unknown\n" in body
    rows = [ln for ln in body.splitlines() if ln.startswith("- ")]
    assert all(re.fullmatch(r"- [a-z0-9-]+: [a-z-]+", ln) for ln in rows), rows
    assert "national: built; governments degraded: " in body
    many = {f"place-{1000000 + i}": "bad-instant" for i in range(60)}
    _c, body = _degraded(tmp_path / "many", {"national": "degraded", "national_states": many})
    assert "governments degraded: 60" in body and body.count(": bad-instant\n") == 50


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
    # 12.3 #12 (S2b nit d): the body is fixed text, with no "not affected" claim until 12.3 #1-9 pass on main
    body = [ln.strip() for ln in step["run"].splitlines() if ln.strip().startswith("echo ")]
    assert body == ['echo "The national update needs a look: $GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/'
                    '$GITHUB_RUN_ID"', 'echo ""',
                    'echo "gate: $(word "$GATE"); collect: $(word "$COLLECT"); push: $(word "$PUSH"); flagged (exit 3):'
                    ' $flagged."', 'echo ""',
                    'echo "A failed collect or push changes nothing on national-data; a flagged run still pushed its'
                    ' outputs."']
    assert "not affected" not in step["run"].lower()
