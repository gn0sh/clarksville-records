"""The V1'' probe (task V1 in docs/tasks/data-off-main.md; docs/architecture/v1-fail-2026-11-18.md section 4).

scripts/v1pp-probe.sh runs here against a stateful stub gh (tests/v1pp_stub_gh.py: refs, pull requests, runs, jobs,
annotations) and a stub protect-main. With PWSH set, every behavioural test also runs scripts/v1pp-probe.ps1, the one
Brian runs, against the same stubs (tests/pwsh_twin.py); without it the .ps1 is checked by its text only. The real
scripts are locked (v1pp-probe/run-once): the behavioural tests run a copy with the one documented line flipped."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import pwsh_twin

ROOT = Path(__file__).resolve().parent.parent
SH = ROOT / "scripts" / "v1pp-probe.sh"
PS1 = ROOT / "scripts" / "v1pp-probe.ps1"
PROBE_DIR = ROOT / "scripts" / "v1pp-probe"
STUB = ROOT / "tests" / "v1pp_stub_gh.py"
# the one lock line of each twin, and the unlocked form the enabling PR writes (here: a day far ahead)
LOCK = {"sh": ("v1pp_unlocked_until=none", "v1pp_unlocked_until=2099-12-31"),
        "ps1": ("$v1ppUnlockedUntil = 'none'", "$v1ppUnlockedUntil = '2099-12-31'")}
LOCK_DOC = ("v1pp_unlocked_until=none   ->   v1pp_unlocked_until=YYYY-MM-DD",
            "$v1ppUnlockedUntil = 'none'   ->   $v1ppUnlockedUntil = 'YYYY-MM-DD'")
MAIN, RD = "1" * 40, "2" * 40
G, B = ("W", "N", "D0"), ("WB", "NB", "D0B")
BRANCHES = ["probe/v1pp-w", "probe/v1pp-n", "probe/v1pp-d0", "probe/v1pp-w-bot", "probe/v1pp-n-bot",
            "probe/v1pp-d0-bot", "probe/v1pp-runner", "probe/v1pp-env"]
REFS = ["heads/" + b for b in BRANCHES] + ["tags/v1pp-probe"]
FILES = [".github/workflows/v1pp-canary.yml", "sitegen/v1pp-probe-canary.txt", "data/v1pp-probe-canary.txt",
         "sitegen/v1pp-push.txt", ".github/workflows/v1pp-probe.yml", ".github/workflows/v1pp-env.yml"]


def pytest_generate_tests(metafunc):
    if "twin" in metafunc.fixturenames:
        metafunc.parametrize("twin", pwsh_twin.TWINS)


# ------------------------------------------------------------------ the runner's log, as GitHub shows it
# The step's source is in the log too: its echo lines name the target by variable, so they never match.
_SOURCE = ('probe\tTry\t2026-11-21T15:00:00Z echo "V1PP-RESULT $t $s exit=$code $(flat "$out")"\n'
           'probe\tTry\t2026-11-21T15:00:00Z if [ "$code" = 0 ]; then echo "V1PP-MERGED $t $s"; exit 0; fi\n'
           'probe\tTry\t2026-11-21T15:00:00Z echo "V1PP-ERROR: no open pull request from $branch"; exit 1\n')
OPEN_NO = "1 gh: GitHub Actions is not permitted to create or approve pull requests. (HTTP 403)"
APPROVE_NO = "1 gh: GitHub Actions is not permitted to approve pull requests. (HTTP 422)"
SQUASH_NO = ("1 {\"message\":\"Repository rule violations found  At least 10 approving reviews are required by "
             "reviewers with write access.\"} gh: Repository rule violations found (HTTP 405)")
METHOD_NO = "1 gh: Merge method {m} is not allowed on this repository (HTTP 405)"
GQL_NO = "1 GraphQL: Repository rule violations found At least 10 approving reviews are required. (mergePullRequest)"
REST_PUSH_NO = "1 gh: Repository rule violations found  Changes must be made through a pull request. (HTTP 422)"
GIT_PUSH_NO = ("1 remote: error: GH013: Repository rule violations found for refs/heads/main.  remote: - Changes "
               "must be made through a pull request.  ! [remote rejected] HEAD -> main (push declined due to "
               "repository rule violations)")


def _line(text):
    return f"probe\tTry\t2026-11-21T15:00:01Z \x1b[36m{text}\x1b[0m\n"


def _pr_steps(t, over):
    """One pull request's lines: approve, squash, merge, rebase, GraphQL; a 0 answer merges and ends the run."""
    out = _line(f"V1PP-PR {t} #77 head {'c' * 40}")
    for s, default in (("approve", APPROVE_NO), ("squash", SQUASH_NO), ("merge", METHOD_NO.replace("{m}", "merge")),
                       ("rebase", METHOD_NO.replace("{m}", "rebase")), ("graphql", GQL_NO)):
        answer = over.get((t, s), default)
        if answer == "SKIP":
            continue
        out += _line(f"V1PP-RESULT {t} {s} exit={answer}")
        if answer.startswith("0") and s != "approve":
            return out + _line(f"V1PP-MERGED {t} {s}"), True
    return out, False


def runner_log(**kw):
    """The whole run, every try refused, unless kw gives (target, step) -> answer ("0 ..." goes through)."""
    over = {tuple(k.split("_")): v for k, v in kw.items()}
    out = _SOURCE
    for t in B:
        out += _line(f"V1PP-RESULT {t} open exit={over.get((t, 'open'), OPEN_NO)}")
    for t in G + B:
        if t in B and not over.get((t, "open"), OPEN_NO).startswith("0"):
            out += _line(f"V1PP-NOPR {t}")
            continue
        lines, ended = _pr_steps(t, over)
        out += lines
        if ended:
            return out
    for s, default in (("rest", REST_PUSH_NO), ("git", GIT_PUSH_NO)):
        answer = over.get(("PUSH", s), default)
        out += _line(f"V1PP-RESULT PUSH {s} exit={answer}")
        if answer.startswith("0"):
            return out + _line(f"V1PP-MERGED PUSH {s}")
    return out + _line("V1PP-DONE all")


# ------------------------------------------------------------------ the harness
_PM = r'''#!/usr/bin/env bash
python3 -c 'import json,os,sys; open(os.environ["GH_CALLS"],"a").write(json.dumps(
  {"method":"SCRIPT","path":"protect-main","argv":sys.argv[1:]})+"\n")' "$@"
echo "CHECK ONLY: nothing is written; the checks below read the live settings."
if [ "${STUB_PM:-ok}" = ok ]; then echo "OK: main is protected (stub)."; exit 0; fi
if [ "$STUB_PM" = ok-exit1 ]; then echo "OK: main is protected (stub)."; exit 1; fi
echo "  NOT OK: R2 is on"; echo "NOT OK: 1 problem(s) above."; exit 1
'''
_PM_PS1 = pwsh_twin.param_block(ROOT / "scripts" / "protect-main.ps1") + r'''
$a = @()
if ($Check) { $a += '--check' }
if ($PSBoundParameters.ContainsKey('Apps')) { $a += @('--apps', $Apps) }
& bash (Join-Path $PSScriptRoot 'protect-main.sh') @a
exit $LASTEXITCODE
'''
_SLEEP = """#!/bin/sh
printf '{"method": "SLEEP", "path": "sleep", "argv": ["%s"]}\\n' "$1" >> "$GH_CALLS"
exit 0
"""


class Run:
    def __init__(self, r, tmp):
        self.r, self.out = r, r.stdout
        calls = tmp / "calls"
        self.calls = [json.loads(x) for x in calls.read_text().splitlines()] if calls.exists() else []
        self.state = json.loads((tmp / "state.json").read_text())
        found = sorted(tmp.glob("v1pp-probe-results-*.txt"))
        self.results = found[0].read_text() if found else ""

    def marks(self, kind):
        return [ln for ln in self.out.splitlines() if ln.startswith(kind + " ")]

    def writes(self):
        return [c for c in self.calls if c["method"] in ("POST", "PUT", "PATCH", "DELETE")]

    def gh(self):
        return [c for c in self.calls if c["method"] not in ("SLEEP", "SCRIPT")]

    def sleeps(self):
        return len([c for c in self.calls if c["method"] == "SLEEP"])


def probe(tmp, twin, cfg=None, args=("--apps", "claude"), env=None, locked=False, pm="ok", unlock="2099-12-31",
          refs=None):
    scripts, bindir = tmp / "scripts", tmp / "bin"
    scripts.mkdir()
    bindir.mkdir()
    for name, tw in ((SH.name, "sh"), (PS1.name, "ps1")):
        if tw != twin:
            continue
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        if not locked:   # the one documented line, flipped
            old, new = LOCK[tw]
            pat = re.compile("(?m)^" + re.escape(old) + "$")
            assert len(pat.findall(text)) == 1, name
            text = pat.sub(lambda _: new.replace("2099-12-31", unlock), text)
        (scripts / name).write_text(text, encoding="utf-8")
    (scripts / "v1pp-probe").symlink_to(PROBE_DIR)
    (scripts / "protect-main.sh").write_text(_PM)
    (scripts / "protect-main.ps1").write_text(_PM_PS1)
    (bindir / "gh").write_text(f'#!/bin/sh\nexec python3 "{STUB}" "$@"\n')
    (bindir / "sleep").write_text(_SLEEP)
    for f in ("gh", "sleep"):
        (bindir / f).chmod(0o755)
    cfg = {"runner_log": runner_log(), **(cfg or {})}
    (tmp / "cfg.json").write_text(json.dumps(cfg))
    state = {"refs": {"heads/main": MAIN, "heads/records-data": RD, **(refs or {})}}
    if cfg.get("tag_exists"):
        state["refs"]["tags/main"] = MAIN
    for b, n in cfg.get("bot_prs", {}).items():   # a pull request the runner's GITHUB_TOKEN opened
        state.setdefault("prs", {})[str(n)] = {"head": b, "state": "open", "merged": False}
    (tmp / "state.json").write_text(json.dumps(state))
    e = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_REMOTE", "GITHUB_ACTIONS", "CI")}
    e.update({"PATH": f"{bindir}:{os.environ['PATH']}", "GH_CFG": str(tmp / "cfg.json"),
              "GH_STATE": str(tmp / "state.json"), "GH_CALLS": str(tmp / "calls"), "RESULTS_DIR": str(tmp),
              "HOME": str(tmp), "STUB_PM": pm, **(env or {})})
    if twin == "sh":
        argv = ["bash", str(scripts / SH.name), *args]
    else:
        pwsh_twin.install(tmp, bindir)
        # the .ps1 writes its results file to [Environment]::GetFolderPath('MyDocuments'), which .NET on Linux
        # returns as '' unless HOME/Documents exists (Brian's Windows always has one)
        (tmp / "Documents").mkdir(exist_ok=True)
        e = pwsh_twin.env(e)
        argv = pwsh_twin.argv(scripts / PS1.name, pwsh_twin.flags(list(args), {"--apps": "-Apps", "--bogus": "-Bogus"}))
    r = subprocess.run(argv, env=e, capture_output=True, text=True, timeout=300)
    return Run(r, tmp)


def assert_cleaned(run):
    """Every probe ref deleted and read again as gone; every probe pull request closed and read again."""
    left = [r for r in REFS if r in run.state["refs"]]
    assert not left, left
    for r in REFS + ["tags/main"]:
        assert f"PASS after cleanup {r}: deleted" in run.out, r
    for n, pr in run.state.get("prs", {}).items():
        assert pr["state"] == "closed", n
    deletes = [c["path"] for c in run.calls if c["method"] == "DELETE"]
    for r in REFS:
        assert deletes.count("git/refs/" + r) == 2, r     # the leftovers pass, then cleanup
    assert deletes.count("git/refs/tags/main") == 1      # v1pp-probe/tag-main-cleanup: always, once
    # v1pp-probe/inflight-run-at-cleanup: every probe run reads completed before the first cleanup write
    first_close = next((i for i, c in enumerate(run.calls) if c["method"] == "PATCH"), None)
    if first_close is not None:
        for rid in run.state.get("cancelled", []):
            cancel = next(i for i, c in enumerate(run.calls) if c["path"] == f"actions/runs/{rid}/cancel")
            assert cancel < first_close, rid


# ------------------------------------------------------------------ PASS
def test_pass_when_every_try_is_refused(tmp_path, twin):
    run = probe(tmp_path, twin)
    assert run.r.returncode == 0, run.out + run.r.stderr
    assert run.out.rstrip().splitlines()[-1].startswith("PASS (V1''): every step above was refused as expected")
    assert not run.marks("FAIL") and not run.marks("INCONCLUSIVE") and not run.marks("NOT-TRIED"), run.out
    passes = run.marks("PASS")
    for t in G:
        for s in ("approve", "squash", "merge", "rebase", "graphql"):
            assert any(ln.startswith(f"PASS {t} {s}: refused") for ln in passes), (t, s)
    for t in B:
        assert any(ln.startswith(f"PASS {t} open: refused") for ln in passes), t
        assert any(ln.startswith(f"PASS {t} pull request: none from") for ln in passes), t
        assert not any(ln.startswith(f"PASS {t} squash") for ln in passes), t   # nothing to merge
    for s in ("rest", "git"):
        assert any(ln.startswith(f"PASS PUSH {s}: refused") for ln in passes), s
    for label in ("branch probe/v1pp-env", "tag v1pp-probe"):
        for e in ("github-pages", "morning-note"):
            assert any(ln.startswith(f"PASS {label} {e}: refused") and "not allowed to deploy to " + e in ln
                       for ln in passes), (label, e)
        assert any(ln.startswith(f"PASS {label} pages-api: refused") for ln in passes), label
    assert any(ln.startswith("PASS tag main: refused") for ln in passes)
    assert "PASS tag main after: absent" in run.out and f"PASS main: unchanged at {MAIN}" in run.out
    for f in FILES:
        for ref in ("main", "records-data"):
            assert f"PASS {f} on {ref}: absent" in run.out, (f, ref)
    for n in ("77", "78", "79"):
        assert f"PASS pull request #{n}: unmerged" in run.out and f"PASS after cleanup #{n}: closed, unmerged" in run.out
    assert_cleaned(run)
    assert "r2_puts" not in run.state                                    # a PASS leaves R2 as it is
    # the record: the results file holds what was printed, and nothing is sent
    assert "PASS (V1'')" in run.results and "PASS tag main" in run.results
    # the guard ran first: protect-main --check with the same --apps answer, before any write
    assert run.calls[0]["method"] == "auth status" or run.calls[0]["path"] == "protect-main"
    pm = [i for i, c in enumerate(run.calls) if c["method"] == "SCRIPT"]
    assert [run.calls[i]["argv"] for i in pm] == [["--check", "--apps", "claude"]]
    assert pm[0] < run.calls.index(run.writes()[0])


def test_the_setup_is_what_section_4_asks_for(tmp_path, twin):
    run = probe(tmp_path, twin)
    files = run.state["files"]
    assert files == {"probe/v1pp-w": FILES[0], "probe/v1pp-n": FILES[1], "probe/v1pp-d0": FILES[2],
                     "probe/v1pp-w-bot": FILES[0], "probe/v1pp-n-bot": FILES[1], "probe/v1pp-d0-bot": FILES[2],
                     "probe/v1pp-env": FILES[5], "probe/v1pp-runner": FILES[4]}
    # every branch starts at main; gn0sh opens only set G; the tag v1pp-probe sits on the env branch's commit
    creates = [c for c in run.calls if c["method"] == "POST" and c["path"] == "git/refs"]
    for c in creates:
        assert f"sha={MAIN}" in c["argv"] or "ref=refs/tags/v1pp-probe" in c["argv"], c
    pulls = [c for c in run.calls if c["method"] == "POST" and c["path"] == "pulls"]
    assert [next(x for x in c["argv"] if x.startswith("head=")) for c in pulls] == \
        ["head=probe/v1pp-w", "head=probe/v1pp-n", "head=probe/v1pp-d0"]
    tag = next(c for c in creates if "ref=refs/tags/v1pp-probe" in c["argv"])
    env_head = next(c for c in run.calls if c["method"] == "PUT" and "branch=probe/v1pp-env" in c["argv"])
    assert run.calls.index(env_head) < run.calls.index(tag)
    # the runner is pushed last, after every pull request exists
    runner = next(c for c in run.calls if c["method"] == "PUT" and "branch=probe/v1pp-runner" in c["argv"])
    assert run.calls.index(runner) > max(run.calls.index(c) for c in pulls + [tag])
    # the tag named main is tried at main, by you
    tm = [c for c in creates if "ref=refs/tags/main" in c["argv"]]
    assert len(tm) == 1 and f"sha={MAIN}" in tm[0]["argv"]


def test_a_422_on_opening_a_pull_request_is_retried(tmp_path, twin):
    """read-after-write rule 6: POST pulls after a fresh push may get 422 (nothing was created), so only that retries."""
    run = probe(tmp_path, twin, {"pr_422": 2})
    assert run.r.returncode == 0, run.out
    assert len([c for c in run.calls if c["method"] == "POST" and c["path"] == "pulls"]) == 5
    assert sorted(run.state["prs"]) == ["77", "78", "79"]


def test_any_other_failure_opening_a_pull_request_is_not_retried(tmp_path, twin):
    run = probe(tmp_path, twin, {"fail": {"-X POST repos/gn0sh/clarksville-records/pulls": 1}})
    assert run.r.returncode == 1 and "INCONCLUSIVE setup: could not open the pull request for probe/v1pp-w" in run.out
    assert len([c for c in run.calls if c["method"] == "POST" and c["path"] == "pulls"]) == 1
    assert not [c for c in run.calls if "branch=probe/v1pp-runner" in c["argv"]]
    assert_cleaned(run)


# ------------------------------------------------------------------ FAIL
FAILS = {
    "w-squash-merged": ({"runner_log": runner_log(W_squash="0 "), "merged": [77]},
                        ["FAIL W squash", "FAIL pull request #77"]),
    "n-graphql-merged": ({"runner_log": runner_log(N_graphql="0 {\"data\":{}}"), "merged": [78]}, ["FAIL N graphql"]),
    "d0-rebase-merged": ({"runner_log": runner_log(D0_rebase="0 "), "on_main": [FILES[2]]},
                         ["FAIL D0 rebase", f"FAIL {FILES[2]} on main"]),
    "bot-approve-posted": ({"runner_log": runner_log(W_approve="0 APPROVED")}, ["FAIL W approve"]),
    "bot-opened-a-pr": ({"runner_log": runner_log(WB_open="0 90"), "bot_prs": {"probe/v1pp-w-bot": 90}},
                        ["FAIL WB open", "FAIL WB pull request", "PASS WB squash: refused",
                         "PASS after cleanup #90: closed, unmerged"]),
    "rest-push": ({"runner_log": runner_log(PUSH_rest="0 {}"), "on_main": [FILES[3]]}, ["FAIL PUSH rest"]),
    "git-push": ({"runner_log": runner_log(PUSH_git="0 ")}, ["FAIL PUSH git"]),
    "tag-main-created": ({"tag_main": "create"}, ["FAIL tag main:", "FAIL tag main after"]),
    "env-job-ran": ({"jobs": {"502": [{"id": 603, "name": "github-pages", "status": "completed",
                                       "conclusion": "success", "steps": [{"name": "run"}]},
                                      {"id": 604, "name": "morning-note", "status": "completed",
                                       "conclusion": "failure", "steps": []}]}},
                    ["FAIL tag v1pp-probe github-pages"]),
    "file-on-records-data": ({"on_rd": [FILES[1]]}, [f"FAIL {FILES[1]} on records-data"]),
    "file-on-main-no-merge-line": ({"on_main": [FILES[0]]}, [f"FAIL {FILES[0]} on main"]),
    "merged-after-cleanup": ({"merged_after_cleanup": [79]}, ["FAIL after cleanup #79: merged into main"]),
    # v1pp-probe/pages-api-coverage
    "pages-accepted": ({"env_logs": {"501": _line("V1PP-RESULT PAGES api exit=0 {\"status_url\": \"x\"}")}},
                       ["FAIL branch probe/v1pp-env pages-api: GitHub accepted a Pages deployment"]),
}


@pytest.mark.parametrize("case", list(FAILS))
def test_each_way_through_is_fail_and_turns_r2_off_at_once(tmp_path, twin, case):
    cfg, want = FAILS[case]
    run = probe(tmp_path, twin, cfg)
    assert run.r.returncode == 2, run.out + run.r.stderr
    assert "FAIL (V1''):" in run.out
    for w in want:
        assert any(ln.startswith(w) for ln in run.out.splitlines()), (w, run.out)
    # R2 off at once: one PUT false, before any cleanup write, confirmed by a read
    puts = [i for i, c in enumerate(run.calls) if c["method"] == "PUT" and c["path"] == "actions/permissions/workflow"]
    assert len(puts) == 1 and "can_approve_pull_request_reviews=false" in run.calls[puts[0]]["argv"]
    assert run.state["r2"] is False and "R2 reads off." in run.out
    first_close = next((i for i, c in enumerate(run.calls) if c["method"] == "PATCH"), len(run.calls))
    if case != "merged-after-cleanup":
        assert puts[0] < first_close
    assert "MAIN_PR_BASELINE past it" in run.out and "Leave MORNING_NOTE_SEND unset" in run.out
    assert "PASS (V1'')" not in run.out
    left = [r for r in REFS if r in run.state["refs"]]
    assert not left and "tags/main" not in run.state["refs"], left   # cleanup still ran, a tag main included


def test_a_merge_ends_the_run_and_every_later_step_is_not_tried(tmp_path, twin):
    run = probe(tmp_path, twin, {"runner_log": runner_log(N_squash="0 "), "merged": [78]})
    assert run.r.returncode == 2
    nt = [ln.split(":")[0] for ln in run.marks("NOT-TRIED")]
    assert nt == ["NOT-TRIED N merge", "NOT-TRIED N rebase", "NOT-TRIED N graphql",
                  "NOT-TRIED D0 approve", "NOT-TRIED D0 squash", "NOT-TRIED D0 merge", "NOT-TRIED D0 rebase",
                  "NOT-TRIED D0 graphql", "NOT-TRIED PUSH rest", "NOT-TRIED PUSH git"], nt
    # what ran before the merge still has its line, and the environment and tag checks still run
    assert any(ln.startswith("PASS W graphql: refused") for ln in run.marks("PASS"))
    assert any(ln.startswith("PASS tag v1pp-probe morning-note: refused") for ln in run.marks("PASS"))
    # the merged pull request is read merged; the others are closed unmerged
    assert "FAIL pull request #78: merged into main" in run.out
    assert "PASS after cleanup #77: closed, unmerged" in run.out


# ------------------------------------------------------------------ INCONCLUSIVE
INCONCLUSIVE = {
    "main-after-unread": ({"main_after": "FAIL"}, "INCONCLUSIVE main: could not read it after the probe"),
    "main-moved": ({"main_after": "3" * 40}, "INCONCLUSIVE main: moved during the probe"),
    "merged-unread": ({"fail": {"pulls/78 --jq .merged": 1}}, "INCONCLUSIVE pull request #78: could not read"),
    "file-unread": ({"fail": {"contents/data/v1pp-probe-canary.txt?ref=records-data": 1}},
                    "INCONCLUSIVE data/v1pp-probe-canary.txt on records-data: could not read it"),
    "jobs-unread": ({"fail": {"actions/runs/501/jobs": 1}},
                    "INCONCLUSIVE branch probe/v1pp-env github-pages: could not read the job"),
    "annotations-unread": ({"fail": {"check-runs/604/annotations": 1}},
                           "INCONCLUSIVE tag v1pp-probe morning-note: could not read the job's annotations"),
    "env-other-failure": ({"annotations": {"602": ["The job was not started because of a billing issue."]}},
                          "INCONCLUSIVE branch probe/v1pp-env morning-note: the job failed without the environment refusal"),
    "env-waiting": ({"jobs": {"501": [
        {"id": 601, "name": "github-pages", "status": "waiting", "conclusion": None, "steps": []},
        {"id": 602, "name": "morning-note", "status": "completed", "conclusion": "failure", "steps": []}]}},
                    "INCONCLUSIVE branch probe/v1pp-env github-pages: the job reads 'waiting' 'null'"),
    "run-not-finished": ({"run_status": {"500": "in_progress"}}, "INCONCLUSIVE runner: the run reads 'in_progress'"),
    "runner-never-started": ({"no_run": ["probe/v1pp-runner"]}, "INCONCLUSIVE runner: the probe run did not start"),
    "tag-run-never-started": ({"no_run": ["v1pp-probe"]}, "INCONCLUSIVE tag v1pp-probe github-pages: the run did not start"),
    "answer-missing": ({"runner_log": runner_log(D0_merge="SKIP")}, "INCONCLUSIVE D0 merge: no answer in the run's log"),
    "squash-other-reason": ({"runner_log": runner_log(W_squash="1 gh: Base branch was modified. (HTTP 405)")},
                            "INCONCLUSIVE W squash: refused, but not naming 'approving review'"),
    "approve-other-reason": ({"runner_log": runner_log(N_approve="1 gh: Server Error (HTTP 502)")},
                             "INCONCLUSIVE N approve: refused, but not naming"),
    "push-other-reason": ({"runner_log": runner_log(PUSH_git="1 fatal: unable to access (HTTP 500)")},
                          "INCONCLUSIVE PUSH git: refused, but not naming 'rule violation'"),
    "tag-main-other": ({"tag_main": "other"}, "INCONCLUSIVE tag main: failed without naming a rule"),
    "tag-main-unread": ({"tag_main_reads_fail": True}, "INCONCLUSIVE tag main after: could not read it"),
    "bot-list-unread": ({"fail": {"head=gn0sh:probe/v1pp-n-bot": 1}}, "INCONCLUSIVE NB pull request: could not list"),
    # v1pp-probe/unobserved-refusal-pass: a merge or rebase refused for another reason is not a PASS
    "merge-502": ({"runner_log": runner_log(N_merge="1 gh: Server Error (HTTP 502)")},
                  "INCONCLUSIVE N merge: refused, but not naming 'not allowed|approving review|rule violation'"),
    "rebase-502": ({"runner_log": runner_log(D0_rebase="1 gh: Server Error (HTTP 502)")},
                   "INCONCLUSIVE D0 rebase: refused, but not naming"),
    "pages-other": ({"env_logs": {"501": _line("V1PP-RESULT PAGES api exit=1 gh: Server Error (HTTP 502)")}},
                    "INCONCLUSIVE branch probe/v1pp-env pages-api: refused, but not on branch or environment grounds"),
    "pages-artifact-first": (
        {"env_logs": {"502": _line("V1PP-RESULT PAGES api exit=1 gh: Artifact not found (HTTP 404)")}},
        "INCONCLUSIVE tag v1pp-probe pages-api: artifact refused first; branch check not reached"),
    "tag-main-delete-failed": ({"delete_fail": ["tags/main"]},
                               "INCONCLUSIVE after cleanup tags/main: the delete answered 'failed:"),
    "pages-missing": ({"env_logs": {"502": _line("V1PP-ERROR: no OIDC token")}},
                      "INCONCLUSIVE tag v1pp-probe pages-api: no answer in the run's log"),
    # v1pp-probe/cleanup-absence-read: a cleanup write that failed is INCONCLUSIVE, even if the re-read agrees
    "close-failed": ({"close_fail": [78]}, "INCONCLUSIVE after cleanup #78: the close answered 'failed:"),
    "delete-failed": ({"delete_fail": ["heads/probe/v1pp-n"]},
                      "INCONCLUSIVE after cleanup heads/probe/v1pp-n: the delete answered 'failed:"),
}


@pytest.mark.parametrize("case", list(INCONCLUSIVE))
def test_a_failed_read_or_another_refusal_is_inconclusive(tmp_path, twin, case):
    cfg, want = INCONCLUSIVE[case]
    run = probe(tmp_path, twin, cfg)
    assert run.r.returncode == 1, run.out + run.r.stderr
    assert any(ln.startswith(want) for ln in run.out.splitlines()), (want, run.out)
    assert run.out.rstrip().splitlines()[-1].startswith("INCONCLUSIVE (V1''):")
    assert not run.marks("FAIL") and "r2_puts" not in run.state      # nothing went through: R2 untouched
    left = [r for r in REFS if r in run.state["refs"]]               # cleanup ran anyway
    assert left == (["heads/probe/v1pp-n"] if case == "delete-failed" else []), left
    assert "nothing was seen to go through" in run.out.rstrip().splitlines()[-1]


def test_a_run_still_going_at_the_deadline_is_cancelled_before_cleanup(tmp_path, twin):
    """v1pp-probe/unbounded-watch and inflight-run-at-cleanup: 72 reads, 10 s apart, then the cancel, then cleanup."""
    run = probe(tmp_path, twin, {"run_status": {"500": "in_progress"}})
    assert run.r.returncode == 1
    assert any(ln.startswith("INCONCLUSIVE runner: the run reads 'in_progress', not completed after 12 minutes")
               for ln in run.out.splitlines())
    reads = [c for c in run.calls if c["method"] == "run view" and "500" in c["argv"] and "--log" not in c["argv"]]
    assert len(reads) == 72 + 1 + 1          # the bounded wait, the read before the cancel, the read after it
    assert run.state["cancelled"] == ["500"] and "cancelling it before cleanup" in run.out
    assert_cleaned(run)
    assert not [c for c in run.calls if c["method"] == "run watch"]   # no unbounded gh run watch


def test_a_run_that_will_not_cancel_is_inconclusive_with_the_link(tmp_path, twin):
    run = probe(tmp_path, twin, {"run_status": {"502": "in_progress"}, "cancel_ignored": [502]})
    assert run.r.returncode == 1
    assert ("INCONCLUSIVE run 502: still 'in_progress' after the cancel: cancel it at "
            "https://github.com/gn0sh/clarksville-records/actions/runs/502") in run.out


def test_a_setup_failure_looks_up_and_cancels_a_run_it_started(tmp_path, twin):
    """The env branch was pushed (its run may be going), then the tag failed: the run is found and cancelled."""
    run = probe(tmp_path, twin, {"fail": {"ref=refs/tags/v1pp-probe": 1}, "run_status": {"501": "queued"}})
    assert run.r.returncode == 1 and "INCONCLUSIVE setup: could not create the tag v1pp-probe" in run.out
    assert run.state["cancelled"] == ["501"]
    assert not [c for c in run.calls if c["method"] == "run list" and "probe/v1pp-runner" in c["argv"]]
    assert_cleaned(run)


def test_a_tag_main_left_behind_says_a_person_edits_r_t(tmp_path, twin):
    """Delta review: a plain DELETE of tags/main is refused by R-T, so the hint is the ruleset edit, not the command."""
    run = probe(tmp_path, twin, {"delete_fail": ["tags/main"]})
    assert run.r.returncode == 1
    line = next(ln for ln in run.out.splitlines() if ln.startswith("INCONCLUSIVE after cleanup tags/main"))
    assert "a person removes it by editing the R-T ruleset" in line and "gh api -X DELETE" not in line


def test_runs_are_settled_before_the_merged_reads_and_r2_before_cleanup(tmp_path, twin):
    """Delta review: settle_runs first, so a merge by a late run is read, and R2 goes off, before any cleanup write."""
    run = probe(tmp_path, twin, {"fail": {"ref=refs/tags/v1pp-probe": 1}, "run_status": {"501": "queued"},
                                 "bot_prs": {"probe/v1pp-w-bot": 90}, "merged": [90]})
    assert run.r.returncode == 2
    idx = lambda pred: next(i for i, c in enumerate(run.calls) if pred(c))   # noqa: E731
    cancel = idx(lambda c: c["path"] == "actions/runs/501/cancel")
    read = idx(lambda c: c["path"] == "pulls/90" and c["method"] == "GET")
    put = idx(lambda c: c["path"] == "actions/permissions/workflow" and c["method"] == "PUT")
    first_close = idx(lambda c: c["method"] == "PATCH")
    assert cancel < read < put < first_close


def test_a_tag_main_delete_refused_by_r_t_is_done(tmp_path, twin):
    """v1pp-probe/tag-main-cleanup: R-T may refuse deleting a tag main that isn't there; the re-read decides."""
    run = probe(tmp_path, twin, {"tag_main_delete": "rule"})
    assert run.r.returncode == 0, run.out
    assert "PASS after cleanup tags/main: deleted" in run.out


def test_a_merged_pr_found_only_at_cleanup_is_read_before_cleanup(tmp_path, twin):
    """v1pp-probe/r2-after-cleanup: a bot PR first seen by finish's listing: its merged flag is read (FAIL, R2 off)
    before any cleanup write."""
    run = probe(tmp_path, twin, {"fail": {"branch=probe/v1pp-w-bot": 1}, "bot_prs": {"probe/v1pp-w-bot": 90},
                                 "merged": [90]})
    assert run.r.returncode == 2
    assert "FAIL pull request #90: merged into main" in run.out
    read = next(i for i, c in enumerate(run.calls) if c["path"] == "pulls/90" and c["method"] == "GET")
    put = next(i for i, c in enumerate(run.calls) if c["path"] == "actions/permissions/workflow" and c["method"] == "PUT")
    first_close = next(i for i, c in enumerate(run.calls) if c["method"] == "PATCH")
    assert read < put < first_close


def test_an_expired_unlock_is_refused(tmp_path, twin):
    """v1pp-probe/lock-window: an unlock left in place stops working after its day."""
    run = probe(tmp_path, twin, unlock="2000-01-01")
    assert run.r.returncode == 1 and "unlock expired after 2000-01-01" in run.out and not run.calls


def test_a_rerun_deletes_the_leftovers_of_an_earlier_try_first(tmp_path, twin):
    """S3: after a closed window the runbook says run it again; the leftover branches and tag go first."""
    left = {r: "9" * 40 for r in REFS}
    run = probe(tmp_path, twin, refs=left)
    assert run.r.returncode == 0, run.out
    first_create = next(i for i, c in enumerate(run.calls) if c["method"] == "POST" and c["path"] == "git/refs")
    for r in REFS:
        d = next(i for i, c in enumerate(run.calls) if c["method"] == "DELETE" and c["path"] == "git/refs/" + r)
        assert d < first_create, r
    assert_cleaned(run)


def test_a_setup_failure_is_inconclusive_and_still_cleans_up(tmp_path, twin):
    run = probe(tmp_path, twin, {"fail": {"branch=probe/v1pp-d0-bot": 1}})
    assert run.r.returncode == 1
    assert "INCONCLUSIVE setup: could not push probe/v1pp-d0-bot" in run.out
    assert not [c for c in run.calls if "branch=probe/v1pp-runner" in c["argv"]]   # no runner: nothing ran as the bot
    assert not [c for c in run.calls if c["path"] == "pulls"]
    assert_cleaned(run)


# ------------------------------------------------------------------ cleanup, read again
def test_a_ref_still_there_after_cleanup_is_inconclusive_with_the_command(tmp_path, twin):
    run = probe(tmp_path, twin, {"delete_ignored": ["heads/probe/v1pp-env"]})
    assert run.r.returncode == 1
    assert ("INCONCLUSIVE after cleanup heads/probe/v1pp-env: the delete answered 'done', it reads 'present': delete "
            "it with gh api -X DELETE repos/gn0sh/clarksville-records/git/refs/heads/probe/v1pp-env") in run.out
    assert run.sleeps() >= 9


def test_a_lagging_read_after_cleanup_waits_and_passes(tmp_path, twin):
    run = probe(tmp_path, twin, {"ref_lag": {"tags/v1pp-probe": 3}})
    assert run.r.returncode == 0, run.out
    deletes = [c for c in run.calls if c["method"] == "DELETE" and c["path"] == "git/refs/tags/v1pp-probe"]
    assert len(deletes) == 2                                         # the delete is never retried
    reads = [c for c in run.calls if c["path"] == "git/ref/tags/v1pp-probe"]
    assert len(reads) == 4                                           # 3 lagging reads, then the 404


def test_a_pull_request_that_will_not_close_is_inconclusive(tmp_path, twin):
    run = probe(tmp_path, twin, {"close_ignored": [78]})
    assert run.r.returncode == 1
    assert ("INCONCLUSIVE after cleanup #78: the close answered 'open\tfalse', it reads 'open\tfalse': close it with "
            "gh pr close 78 --repo gn0sh/clarksville-records") in run.out


# ------------------------------------------------------------------ refusals before anything changes
def test_the_shipped_scripts_are_locked(tmp_path, twin):
    run = probe(tmp_path, twin, locked=True)
    assert run.r.returncode == 1 and "REFUSED: the V1'' probe is locked (v1pp-probe/run-once)" in run.out
    assert not run.calls


@pytest.mark.parametrize("var", ["CLAUDE_CODE_REMOTE", "GITHUB_ACTIONS", "CI"])
def test_refused_in_a_cloud_session_or_ci(tmp_path, twin, var):
    run = probe(tmp_path, twin, env={var: "true"})
    assert run.r.returncode == 1 and f"REFUSED: {var} is set" in run.out and not run.calls


@pytest.mark.parametrize("args", [[], ["--apps"], ["--apps", "other"], ["--apps", "claude", "--bogus"],
                                  ["--bogus", "x"]], ids=["none", "apps-no-value", "apps-other", "extra", "unknown"])
def test_unknown_or_missing_arguments_are_refused(tmp_path, twin, args):
    run = probe(tmp_path, twin, args=args)
    assert run.r.returncode != 0 and not run.calls, run.out + run.r.stderr


@pytest.mark.parametrize("pm", ["not-ok", "ok-exit1"])
def test_refused_unless_protect_main_check_prints_ok(tmp_path, twin, pm):
    run = probe(tmp_path, twin, pm=pm)
    assert run.r.returncode == 1 and "REFUSED: protect-main --check did not print OK" in run.out
    assert [c["argv"] for c in run.calls if c["method"] == "SCRIPT"] == [["--check", "--apps", "claude"]]
    assert not run.writes()


@pytest.mark.parametrize("cfg,why", [
    ({"fail": {"git/ref/heads/main": 1}}, "REFUSED: could not read main."),
    ({"fail": {"git/ref/heads/records-data": 1}}, "REFUSED: could not read records-data."),
    ({"tag_exists": True}, "REFUSED: a tag named main exists"),
    ({"fail": {"git/ref/tags/main": 1}}, "REFUSED: a tag named main exists or could not be read"),
], ids=["main", "records-data", "tag-main-exists", "tag-main-unread"])
def test_a_failed_pre_read_refuses_with_nothing_changed(tmp_path, twin, cfg, why):
    run = probe(tmp_path, twin, cfg)
    assert run.r.returncode == 1 and why in run.out and "Nothing was changed." in run.out, run.out
    assert not run.writes()


def test_the_workflow_scope_is_added_after_the_guard_and_given_back_last(tmp_path, twin):
    run = probe(tmp_path, twin, {"scopes": "Token scopes: 'gist', 'repo'"})
    assert run.r.returncode == 0, run.out
    refresh = [i for i, c in enumerate(run.calls) if c["method"] == "auth refresh"]
    assert len(refresh) == 2 and "-s" in run.calls[refresh[0]]["argv"] and "--remove-scopes" in run.calls[refresh[1]]["argv"]
    pm = next(i for i, c in enumerate(run.calls) if c["method"] == "SCRIPT")
    assert pm < refresh[0] < run.calls.index(run.writes()[0])
    assert refresh[1] == len(run.calls) - 1


# ------------------------------------------------------------------ text pins (both twins)
def _jq_filters(text):
    return sorted(set(re.findall(r"--jq '([^']*)'", text)))


def test_the_twins_agree():
    sh, ps1 = SH.read_text(encoding="utf-8"), PS1.read_text(encoding="utf-8")
    assert _jq_filters(sh) == _jq_filters(ps1)
    for s in (sh, ps1):
        for part in ("V1PP-(RESULT|MERGED|NOPR) (W|N|D0|WB|NB|D0B|PUSH)( .*)?$", "not permitted to create",
                     "not permitted to (create or )?approve pull requests", "approving review", "rule violation",
                     "not allowed to deploy to", "refs/tags/main", "can_approve_pull_request_reviews=false",
                     "MAIN_PR_BASELINE past it", "HTTP 404", "HTTP 422", "probe/v1pp-w-bot", "probe/v1pp-d0",
                     "probe/v1pp-env", "probe/v1pp-runner", "v1pp-probe-results-", "OK: main is protected",
                     "CLAUDE_CODE_REMOTE", "GITHUB_ACTIONS", "'CI'" if s is ps1 else " CI;", "NOT-TRIED",
                     "PASS (V1'')", "FAIL (V1'')", "INCONCLUSIVE (V1'')", "BEGIN-REFUSAL-LOCK", "END-REFUSAL-LOCK",
                     # the review fixes (v1pp-probe/*): the same rule text in both twins
                     "'not allowed|approving review|rule violation'", "V1PP-RESULT PAGES api exit=[0-9]+( .*)?$",
                     "'not allowed to deploy|protection rule'", "artifact refused first; branch check not reached",
                     "Reference does not exist", "/actions/runs/$", "/cancel", "not completed after 12 minutes",
                     "nothing was seen to go through", "unlock expired after", "pushed, but no run seen yet"):
            assert part in s, part
        for f in FILES:
            assert f in s, f
        assert "-ExecutionPolicy Bypass" not in s
    # the lock: one line flips it, documented in both headers, before anything else runs
    for tw, text in (("sh", sh), ("ps1", ps1)):
        old, new = LOCK[tw]
        code_lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
        assert code_lines.count(old) == 1 and not [ln for ln in code_lines if new in ln], tw
        assert all(d in text for d in LOCK_DOC), tw
        assert "v1pp-probe/lock-window" in text and "expired" in text, tw
        lock = text.index("\n" + old + "\n")
        assert text.index("BEGIN-REFUSAL-LOCK") < lock < text.index("END-REFUSAL-LOCK")
        # nothing that calls GitHub comes before the lock (comments aside)
        code = [ln for ln in text[:text.index("END-REFUSAL-LOCK")].splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")]
        assert all(not re.search(r"\bgh\b", ln) for ln in code), tw
    # every guard comes before the first write, in each twin
    for text, first_write in ((sh, '-X POST "repos/$repo/git/refs"'), (ps1, '-X POST "repos/$repo/git/refs"')):
        w = text.index(first_write)
        for g in ("CLAUDE_CODE_REMOTE", "protect-main", "tags/main", "records-data"):
            assert text.index(g) < w, g
    assert "scripts\\protect-main.ps1" in ps1 and "-Check -Apps $Apps" in ps1
    # Windows PowerShell 5.1: no double quote inside a --jq filter, ASCII only, no BOM
    assert not re.search(r"--jq '[^']*\"", ps1)
    raw = PS1.read_bytes()
    assert raw.isascii() and not raw.startswith(b"\xef\xbb\xbf")
    assert SH.read_bytes().isascii()


def test_read_until_is_the_one_helper_text():
    def block(text, start):
        i = text.index("# read-after-write (docs/architecture/read-after-write-invariant.md)")
        assert text.index(start, i) - i < 800, start
        return text[i:text.index("\n}\n", i) + 3]
    pm_sh = (ROOT / "scripts" / "protect-main.sh").read_text(encoding="utf-8")
    pm_ps1 = (ROOT / "scripts" / "protect-main.ps1").read_text(encoding="utf-8")
    assert block(SH.read_text(encoding="utf-8"), "read_until() {") == block(pm_sh, "read_until() {")
    assert block(PS1.read_text(encoding="utf-8"), "function ReadUntil(") == block(pm_ps1, "function ReadUntil(")


def test_the_probe_workflows_are_inert_and_least_privilege():
    canary = yaml.safe_load((PROBE_DIR / "v1pp-canary.yml").read_text(encoding="utf-8"))
    assert (canary.get("on") or canary[True]) == "workflow_dispatch" and canary["permissions"] == {}
    assert [j["if"] for j in canary["jobs"].values()] == [False]
    envwf_text = (PROBE_DIR / "v1pp-env.yml").read_text(encoding="utf-8")
    envwf = yaml.safe_load(envwf_text)
    assert (envwf.get("on") or envwf[True]) == {"push": {"branches": ["probe/v1pp-env"], "tags": ["v1pp-probe"]}}
    assert envwf["permissions"] == {}
    jobs = envwf["jobs"]
    assert {k: (j["name"], j.get("environment"), j["permissions"]) for k, j in jobs.items()} == {
        "github-pages": ("github-pages", "github-pages", {}), "morning-note": ("morning-note", "morning-note", {}),
        "pages-api": ("pages-api", None, {"pages": "write", "id-token": "write"})}
    for k in ("github-pages", "morning-note"):
        j = jobs[k]
        assert [list(s) for s in j["steps"]] == [["run"]] and j["steps"][0]["run"].startswith("echo ")
    # v1pp-probe/pages-api-coverage: one call, a made-up artifact, the OIDC token masked, the answer printed
    (step,) = jobs["pages-api"]["steps"]
    run = step["run"]
    assert '"repos/$GITHUB_REPOSITORY/pages/deployments" -F artifact_id=1' in run and "::add-mask::$tok" in run
    assert 'echo "V1PP-RESULT $t $s exit=$code' in run and "t=PAGES; s=api" in run
    assert not re.search(r"V1PP-RESULT PAGES\b", envwf_text)
    for text in (envwf_text, (PROBE_DIR / "v1pp-canary.yml").read_text(encoding="utf-8")):
        assert "secrets." not in text and "uses:" not in text
    text = (PROBE_DIR / "v1pp-probe.yml").read_text(encoding="utf-8")
    runner = yaml.safe_load(text)
    assert (runner.get("on") or runner[True]) == {"push": {"branches": ["probe/v1pp-runner"]}}
    assert runner["permissions"] == {}
    (job,) = runner["jobs"].values()
    assert job["permissions"] == {"contents": "write", "pull-requests": "write"}
    assert "secrets." not in text and "uses:" not in text and "environment" not in job
    run = job["steps"][0]["run"]
    # the order of section 4: bot pull requests, then per pull request approve and the merge tries, then the push
    order = ["-X POST \"repos/$repo/pulls\"", "event=APPROVE", "for s in squash merge rebase", "gh api graphql",
             "-X PATCH \"repos/$repo/git/refs/heads/main\"", "HEAD:refs/heads/main"]
    assert [run.index(x) for x in order] == sorted(run.index(x) for x in order)
    assert "for pair in WB:probe/v1pp-w-bot NB:probe/v1pp-n-bot D0B:probe/v1pp-d0-bot; do" in run
    assert ("for pair in W:probe/v1pp-w N:probe/v1pp-n D0:probe/v1pp-d0 WB:probe/v1pp-w-bot NB:probe/v1pp-n-bot "
            "D0B:probe/v1pp-d0-bot; do") in run
    assert "mergePullRequest(input: {pullRequestId: $id, expectedHeadOid: $oid, mergeMethod: SQUASH})" in run
    assert '-f sha="$head"' in run and '-f commit_id="$head"' in run and "-F force=false" in run
    assert "::add-mask::$auth" in run
    # the markers in the step's own text never match the probe script's pattern (the log shows the source)
    assert not re.search(r"V1PP-(RESULT|MERGED|NOPR) (W|N|D0|WB|NB|D0B|PUSH)\b", text)
    for name in ("v1pp-probe.yml", "v1pp-env.yml", "v1pp-canary.yml"):
        assert not (ROOT / ".github" / "workflows" / name).exists()


def test_the_runner_log_fixture_matches_the_runner():
    """The fixture's line shapes are the runner's echo lines (a drift here would make the tests prove nothing)."""
    run = yaml.safe_load((PROBE_DIR / "v1pp-probe.yml").read_text(encoding="utf-8"))["jobs"]["probe"]["steps"][0]["run"]
    for shape in ('echo "V1PP-RESULT $t $s exit=$code $(flat "$out")"', 'echo "V1PP-MERGED $t $s"',
                  'echo "V1PP-NOPR $t"', 'echo "V1PP-PR $t #$num head $head"'):
        assert shape in run, shape
    assert shutil.which("jq"), "the stub gh applies --jq with jq"
