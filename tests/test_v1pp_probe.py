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
# The committed line is either locked (`none`) or, on an unlock PR, a `YYYY-MM-DD` day; both are accepted.
# LOCK[tw] = (line template with {} for the value, regex matching the one lock line in either state)
LOCK = {"sh": ("v1pp_unlocked_until={}", r"v1pp_unlocked_until=(none|\d{4}-\d{2}-\d{2})"),
        "ps1": ("$v1ppUnlockedUntil = '{}'", r"\$v1ppUnlockedUntil = '(none|\d{4}-\d{2}-\d{2})'")}


def lock_re(tw):
    return re.compile("(?m)^" + LOCK[tw][1] + "$")
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


# ------------------------------------------------------------------ the runner's job log, as GitHub serves it
# (GET actions/jobs/<id>/logs: a timestamp per line, CRLF). The step's source is in the log too: its echo lines name
# the target by variable, so they never match.
_SOURCE = ('2026-11-21T15:00:00.0000000Z echo "V1PP-RESULT $t $s exit=$code $(flat "$out")"\r\n'
           '2026-11-21T15:00:00.0000000Z if [ "$code" = 0 ]; then echo "V1PP-MERGED $t $s"; exit 0; fi\r\n'
           '2026-11-21T15:00:00.0000000Z echo "V1PP-ERROR: no open pull request from $branch"; exit 1\r\n')
OPEN_NO = "1 gh: GitHub Actions is not permitted to create or approve pull requests. (HTTP 403)"
APPROVE_NO = "1 gh: GitHub Actions is not permitted to approve pull requests. (HTTP 422)"
SQUASH_NO = ("1 {\"message\":\"Repository rule violations found  At least 10 approving reviews are required by "
             "reviewers with write access.\"} gh: Repository rule violations found (HTTP 405)")
# try 1 (2026-11-21), as the job log showed them: the pull_request rule named require_last_push_approval, not the count
LAST_PUSHER = "New changes require approval from someone other than the last pusher."
SQUASH_LAST = ('1 {"message":"Repository rule violations found\\n\\n' + LAST_PUSHER + '\\n\\n","documentation_url":'
               '"https://docs.github.com/articles/about-protected-branches","status":"405"}gh: Repository rule '
               'violations found  ' + LAST_PUSHER + '   (HTTP 405)')
GQL_LAST = ('1 {"data":{"mergePullRequest":null},"errors":[{"type":"UNPROCESSABLE","path":["mergePullRequest"],'
            '"message":"Repository rule violations found\\n\\n' + LAST_PUSHER + '\\n\\n"}]}')
PAGES_400 = ('V1PP-RESULT PAGES api exit=1 {"message":"Unable to find artifact mathching the id","documentation_url":'
             '"https://docs.github.com/rest/pages/pages#create-a-github-pages-deployment","status":"400"}gh: Unable to '
             'find artifact mathching the id (HTTP 400)')
METHOD_NO = "1 gh: Merge method {m} is not allowed on this repository (HTTP 405)"
GQL_NO = "1 GraphQL: Repository rule violations found At least 10 approving reviews are required. (mergePullRequest)"
REST_PUSH_NO = "1 gh: Repository rule violations found  Changes must be made through a pull request. (HTTP 422)"
GIT_PUSH_NO = ("1 remote: error: GH013: Repository rule violations found for refs/heads/main.  remote: - Changes "
               "must be made through a pull request.  ! [remote rejected] HEAD -> main (push declined due to "
               "repository rule violations)")


def _line(text):
    return f"2026-11-21T15:00:01.0000000Z \x1b[36m{text}\x1b[0m\r\n"


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
        found = sorted([*tmp.glob("v1pp-probe-results-*.txt"), *tmp.glob("Documents/v1pp-probe-results-*.txt")])
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
        pat = lock_re(tw)
        assert len(pat.findall(text)) == 1, name
        # unlocked: flip the one line to the test's value; locked: force it to `none` even if committed as a date
        text = pat.sub(lambda _: LOCK[tw][0].format("none" if locked else unlock), text)
        (scripts / name).write_text(text, encoding="utf-8")
    (scripts / "v1pp-probe").symlink_to(PROBE_DIR)
    (scripts / "protect-main.sh").write_text(_PM)
    (scripts / "protect-main.ps1").write_text(_PM_PS1)
    (bindir / "gh").write_text(f'#!/bin/sh\nexec python3 "{STUB}" "$@"\n')
    if not (cfg or {}).get("no_git"):
        (bindir / "git").write_text(f'#!/bin/sh\nexec python3 "{STUB}" --git "$@"\n')
    (bindir / "sleep").write_text(_SLEEP)
    if (cfg or {}).get("date_no_d"):   # a date without GNU -d (BSD, busybox)
        real = shutil.which("date")
        (bindir / "date").write_text(f'#!/bin/sh\nfor x in "$@"; do [ "$x" = -d ] && exit 1; done\nexec {real} "$@"\n')
        (bindir / "date").chmod(0o755)
    for f in ("gh", "sleep") + (() if (cfg or {}).get("no_git") else ("git",)):
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
    e.update({"PATH": f"{bindir}:{(env or {}).get('PATH_TAIL') or os.environ['PATH']}", "GH_CFG": str(tmp / "cfg.json"),
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
    assert any(ln.startswith("PASS tag main git: refused") and "GH013" in ln for ln in passes)
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
    "tag-main-created": ({"tag_main": "create"}, ["FAIL tag main:", "FAIL tag main after",
                                                  "FAIL tag main git: tag main exists (git answered up-to-date"]),
    "tag-main-git-created": ({"git_tag": "create"}, ["PASS tag main: refused", "FAIL tag main git: git push created it",
                                                     "FAIL tag main after"]),
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
                            "INCONCLUSIVE W squash: refused, but not naming 'approving review|"),
    # v1pp-probe/squash-last-pusher: the last-pusher phrase counts only with the ruleset header
    "squash-last-pusher-bare": ({"runner_log": runner_log(N_squash="1 gh: " + LAST_PUSHER + " (HTTP 405)")},
                                "INCONCLUSIVE N squash: refused, but not naming"),
    "graphql-header-only": ({"runner_log": runner_log(D0_graphql="1 GraphQL: Repository rule violations found")},
                            "INCONCLUSIVE D0 graphql: refused, but not naming"),
    "approve-other-reason": ({"runner_log": runner_log(N_approve="1 gh: Server Error (HTTP 502)")},
                             "INCONCLUSIVE N approve: refused, but not naming"),
    "push-other-reason": ({"runner_log": runner_log(PUSH_git="1 fatal: unable to access (HTTP 500)")},
                          "INCONCLUSIVE PUSH git: refused, but not naming 'rule violation'"),
    # v1pp-probe/tag-main-unnamed-422: a bare 422 is PASS only with R-T's failing creation rule in the rule suite
    "tag-main-other": ({"tag_main": "other", "no_suite": True, "git_tag": "other"},
                       "INCONCLUSIVE tag main: failed without naming a rule, and no rule suite recorded this try"),
    "tag-main-502": ({"tag_main": "502", "no_suite": True},
                     "INCONCLUSIVE tag main: failed without naming a rule: "),
    "tag-main-suite-other-ruleset": (
        {"tag_main": "other", "suite_evals": [{"rule_source": {"type": "ruleset", "id": 1, "name": "x"},
                                               "enforcement": "active", "result": "fail", "rule_type": "creation"}]},
        "INCONCLUSIVE tag main: refused ("),
    "tag-main-suite-evaluate": (
        {"tag_main": "other", "suite_evals": [{"rule_source": {"type": "ruleset", "id": 27685093, "name": "x"},
                                               "enforcement": "evaluate", "result": "fail", "rule_type": "creation"}]},
        "INCONCLUSIVE tag main: refused"),
    "tag-main-suite-update-rule": (
        {"tag_main": "other", "suite_evals": [{"rule_source": {"type": "ruleset", "id": 27685093, "name": "x"},
                                               "enforcement": "active", "result": "fail", "rule_type": "update"}]},
        "INCONCLUSIVE tag main: refused"),
    "tag-main-suite-pass": ({"tag_main": "other", "suite_over": {"result": "pass"}}, "INCONCLUSIVE tag main: refused"),
    # v1pp-probe/tag-main-t0-unchecked: only the signed-in owner's try counts
    "tag-main-suite-other-actor": ({"tag_main": "other", "suite_over": {"actor_name": "github-actions[bot]"},
                                    "git_tag": "other"},
                                   "INCONCLUSIVE tag main: failed without naming a rule, and no rule suite"),
    # the git push try of the same tag (v1pp-probe/tag-main-unnamed-422, review should-fix)
    "tag-git-other": ({"git_tag": "other"}, "INCONCLUSIVE tag main git: git answered 128, but not from"),
    # v1pp-probe/tag-git-url-rewrite, tag-git-local-hooks, tag-git-exists-wording: only git's own answer from GitHub
    "tag-git-rewrite": ({"git_tag": "rewrite"}, "INCONCLUSIVE tag main git: git answered 1, but not from "
                                               "https://github.com/gn0sh/clarksville-records.git"),
    "tag-git-hook": ({"git_tag": "hook"}, "INCONCLUSIVE tag main git: refused, but no 'remote: error: GH013' line"),
    "tag-git-0-no-to": ({"git_tag": "create_no_to"}, "INCONCLUSIVE tag main git: git answered 0, but not from"),
    "tag-git-uptodate-alone": ({"git_tag": "uptodate"}, "INCONCLUSIVE tag main git: git answered 0, but not from"),
    "tag-git-fetch-failed": ({"git_tag": "fetch_fail"}, "INCONCLUSIVE tag main git: could not fetch main to push from"),
    "tag-main-suite-twice": ({"tag_main": "other", "suite_extra": [{"id": 901}]},
                             "INCONCLUSIVE tag main: refused ("),
    "tag-main-suite-old": ({"tag_main": "other", "suite_over": {"pushed_at": "2026-11-20T01:21:00Z"}, "git_tag": "other"},
                           "INCONCLUSIVE tag main: failed without naming a rule, and no rule suite"),
    "tag-main-suite-other-sha": ({"tag_main": "other", "suite_over": {"after_sha": "3" * 40}, "git_tag": "other"},
                                 "INCONCLUSIVE tag main: failed without naming a rule, and no rule suite"),
    "tag-main-suite-unreadable": ({"tag_main": "other", "suite_unreadable": True, "git_tag": "other"},
                                  "INCONCLUSIVE tag main: refused ("),
    "tag-main-suite-no-pushed-at": ({"tag_main": "other", "suite_over": {"pushed_at": None}, "git_tag": "other"},
                                    "INCONCLUSIVE tag main: failed without naming a rule, and no rule suite"),
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
                      "INCONCLUSIVE tag v1pp-probe pages-api: no answer in the job's log"),
    # v1pp-probe/run-log-missing: each job's own log, bounded
    "pages-log-never-ready": ({"log_lag": {"605": 99}},
                              "INCONCLUSIVE branch probe/v1pp-env pages-api: could not read the job's log (job 605)"),
    "pages-job-missing": ({"jobs": {"501": [
        {"id": 601, "name": "github-pages", "status": "completed", "conclusion": "failure", "steps": []},
        {"id": 602, "name": "morning-note", "status": "completed", "conclusion": "failure", "steps": []}]}},
                          "INCONCLUSIVE branch probe/v1pp-env pages-api: could not read the job"),
    "runner-log-never-ready": ({"log_lag": {"600": 99}}, "INCONCLUSIVE runner log: could not read job 600's log"),
    "runner-jobs-unread": ({"fail": {"actions/runs/500/jobs": -1}},
                           "INCONCLUSIVE runner log: could not read the run's jobs"),
    # v1pp-probe/pages-api-unreachable: the exemption is GitHub's exact artifact 400 only
    "pages-artifact-400-other-words": (
        {"env_logs": {"501": _line("V1PP-RESULT PAGES api exit=1 gh: Artifact expired (HTTP 400)")}},
        "INCONCLUSIVE branch probe/v1pp-env pages-api: artifact refused first"),
    "pages-unable-not-400": (
        {"env_logs": {"501": _line("V1PP-RESULT PAGES api exit=1 gh: Unable to find artifact mathching the id (HTTP 404)")}},
        "INCONCLUSIVE branch probe/v1pp-env pages-api: artifact refused first"),
    "pages-unreachable-plus-another": (
        {"env_logs": {"501": _line(PAGES_400), "502": _line(PAGES_400)},
         "runner_log": runner_log(W_merge="1 gh: Server Error (HTTP 502)")},
        "INCONCLUSIVE W merge: refused, but not naming"),
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


# ------------------------------------------------------------------ try 1 (2026-11-21): what now counts, and only that
def test_try_1_answers_now_pass_with_the_pages_api_lines_not_reachable(tmp_path, twin):
    """The answers try 1 got (docs/architecture/main-protect-invariant.md "V1'' try 1 inconclusive"): the last-pusher
    refusals PASS, the bare 422 on tag main PASSes on R-T's rule suite, the job logs are read per job, and the two
    artifact 400s are NOT-REACHABLE (not counted), so the verdict is PASS and says what it does not cover."""
    over = {f"{t}_{s}": (SQUASH_LAST if s == "squash" else GQL_LAST) for t in G for s in ("squash", "graphql")}
    run = probe(tmp_path, twin, {"runner_log": runner_log(**over), "tag_main": "other",
                                 "env_logs": {"501": _line(PAGES_400), "502": _line(PAGES_400)},
                                 "log_lag": {"605": 2, "600": 1}})
    assert run.r.returncode == 0, run.out + run.r.stderr
    for t in G:
        for s in ("squash", "graphql"):
            assert any(ln.startswith(f"PASS {t} {s}: refused") and LAST_PUSHER in ln for ln in run.marks("PASS")), (t, s)
    tm = [ln for ln in run.marks("PASS") if ln.startswith("PASS tag main: refused")]
    assert len(tm) == 1 and "Reference update failed" in tm[0], tm
    assert "rule suite 900: result=fail, R-T 27685093 creation=fail enforcement=active" in tm[0]
    nr = run.marks("NOT-REACHABLE")
    assert [ln.split(":")[0] for ln in nr] == ["NOT-REACHABLE branch probe/v1pp-env pages-api",
                                              "NOT-REACHABLE tag v1pp-probe pages-api"], nr
    last = run.out.rstrip().splitlines()[-1]
    assert last.startswith("PASS (V1''): every step above was refused as expected")
    assert "2 pages-api line(s) NOT-REACHABLE by design" in last and "U-pages" in last
    # the job logs were read per job, retried while not ready, and gh run view --log is never used
    logs = [c["path"] for c in run.calls if c["path"].startswith("actions/jobs/")]
    assert logs.count("actions/jobs/605/logs") == 3 and logs.count("actions/jobs/600/logs") == 2
    assert logs.count("actions/jobs/606/logs") == 1
    assert not [c for c in run.calls if c["method"] == "run view" and "--log" in c["argv"]]
    # the rule suite was read after the runs (judged once), and before cleanup deleted tags/main
    suites = [i for i, c in enumerate(run.calls) if c["path"].startswith("rulesets/rule-suites")]
    first_close = next(i for i, c in enumerate(run.calls) if c["method"] == "PATCH")
    assert len(suites) == 2 and suites[-1] < first_close
    # read before the git push try, whose own suite would be a second match
    git_push = next(i for i, c in enumerate(run.calls) if c["method"] == "git push")
    assert suites[-1] < git_push
    assert any(ln.startswith("PASS tag main git: refused") for ln in run.marks("PASS"))
    assert_cleaned(run)


@pytest.mark.parametrize("case,why", [
    ("tag-main-suite-other-ruleset", "but not shown to be R-T: rule suite 900: result=fail, R-T 27685093 creation=none"),
    ("tag-main-suite-evaluate", "but not shown to be R-T: rule suite 900: result=fail, R-T 27685093 creation=fail enforcement=evaluate"),
    ("tag-main-suite-update-rule", "but not shown to be R-T: rule suite 900: result=fail, R-T 27685093 creation=none"),
    ("tag-main-suite-pass", "but not shown to be R-T: rule suite 900: result=pass"),
    ("tag-main-suite-twice", "but 2 rule suites match this try, not one"),
    ("tag-main-suite-unreadable", "but rule suite 900 could not be read"),
])
def test_why_a_rule_suite_does_not_prove_r_t(tmp_path, twin, case, why):
    run = probe(tmp_path, twin, INCONCLUSIVE[case][0])
    line = next(ln for ln in run.out.splitlines() if ln.startswith("INCONCLUSIVE tag main: refused ("))
    assert "Reference update failed" in line and why in line, line


@pytest.mark.parametrize("cfg,why", [
    ({"no_suite": True}, "and no rule suite recorded this try; R-T, which has no bypass actor, is shown refusing"),
    ({"suite_unreadable": True}, "and rule suite 900 could not be read; R-T, which has no bypass actor"),
], ids=["no-suite", "suite-unreadable"])
def test_a_missing_rule_suite_is_settled_by_the_git_line(tmp_path, twin, cfg, why):
    """Item 2 of the try 1 note: a suite that could not be seen or read is settled by a PASS git push line, so a
    lagging rule-suite record cannot force a third run; a suite that contradicts R-T never is (table above)."""
    run = probe(tmp_path, twin, {"tag_main": "other", **cfg})
    assert run.r.returncode == 0, run.out
    line = next(ln for ln in run.marks("PASS") if ln.startswith("PASS tag main: refused ("))
    assert "Reference update failed" in line and why in line, line


def test_a_contradicting_rule_suite_is_not_settled_by_the_git_line(tmp_path, twin):
    run = probe(tmp_path, twin, {"tag_main": "other", "suite_over": {"result": "pass"}})
    assert run.r.returncode == 1
    assert any(ln.startswith("PASS tag main git: refused") for ln in run.marks("PASS"))
    assert any(ln.startswith("INCONCLUSIVE tag main: refused (") for ln in run.out.splitlines())


def test_an_unchecked_start_time_reads_no_rule_suite(tmp_path):
    """v1pp-probe/tag-main-t0-unchecked + t0-gnu-date: a date without GNU -d gives no start time; the rule suite is
    not read (bash twin only: the .ps1 computes it with .NET)."""
    run = probe(tmp_path, "sh", {"tag_main": "other", "git_tag": "other", "date_no_d": True})
    assert run.r.returncode == 1
    assert not [c for c in run.calls if c["path"].startswith("rulesets/rule-suites")]
    line = next(ln for ln in run.out.splitlines() if ln.startswith("INCONCLUSIVE tag main: refused ("))
    assert "the start time could not be computed" in line, line


def test_the_git_push_runs_with_a_clean_git_environment(tmp_path, twin):
    """v1pp-probe/tag-git-env and tag-git-local-hooks: no trace, askpass or prompt, secrets redacted, no global config,
    no hooks, gh the only credential helper; and the caller's environment is not changed for anything else."""
    dirty = {"GIT_TRACE": "1", "GIT_TRACE2_EVENT": str(tmp_path / "t2"), "GIT_TRACE_CURL": "1",
             "GIT_CURL_VERBOSE": "1", "GIT_ASKPASS": "/bin/false", "SSH_ASKPASS": "/bin/false",
             "GIT_CONFIG_GLOBAL": str(tmp_path / "mine.gitconfig"), "GIT_TERMINAL_PROMPT": "1", "GIT_TRACE_REDACT": "0"}
    run = probe(tmp_path, twin, env=dirty)
    assert run.r.returncode == 0, run.out + run.r.stderr
    gits = [c for c in run.calls if c["method"].startswith("git ")]
    assert [c["method"] for c in gits] == ["git init", "git fetch", "git push"]
    for c in gits:
        e = c["env"]
        for k in ("GIT_TRACE", "GIT_TRACE2_EVENT", "GIT_TRACE_CURL", "GIT_CURL_VERBOSE", "GIT_ASKPASS", "SSH_ASKPASS"):
            assert k not in e, (c["method"], k)
        assert e["GIT_TRACE_REDACT"] == "1" and e["GIT_TERMINAL_PROMPT"] == "0"
        assert e["GIT_CONFIG_GLOBAL"].endswith("empty.gitconfig") and "mine" not in e["GIT_CONFIG_GLOBAL"]
        hooks = [x for x in c["argv"] if x.startswith("core.hooksPath=")]
        assert len(hooks) == 1 and hooks[0].endswith("no-hooks"), c["argv"]
        assert c["argv"][:6] == ["-c", hooks[0], "-c", "credential.helper=", "-c",
                                 "credential.helper=!gh auth git-credential"], c["argv"]
    assert "--no-verify" in gits[2]["argv"]
    # and put back: every gh call after the git push sees the caller's settings again, nothing more
    after = [c for c in run.calls[run.calls.index(gits[2]) + 1:] if "gitenv" in c]
    assert after
    for c in after:
        e = c["gitenv"]
        assert {k: e.get(k) for k in dirty} == dirty, (c["path"], e)


def test_no_git_is_refused_before_any_write(tmp_path):
    """v1pp-probe/tag-git-no-git-precheck: a missing git must never read as an answer (bash twin here; the .ps1 checks
    Get-Command git the same way, and sets $LASTEXITCODE to 99 before each git call)."""
    farm = tmp_path / "farm"
    farm.mkdir()
    for d in ("/usr/local/bin", "/usr/bin", "/bin"):   # these overlap on merged-/usr systems: first one wins
        for name in (sorted(os.listdir(d)) if os.path.isdir(d) else []):
            if not name.startswith("git") and not os.path.lexists(farm / name):
                (farm / name).symlink_to(os.path.join(d, name))
    run = probe(tmp_path, "sh", {"no_git": True}, env={"PATH_TAIL": str(farm)})
    assert run.r.returncode == 1 and "git not found" in run.out and "Nothing was changed." in run.out, run.out
    assert not run.writes() and not run.marks("FAIL")


def test_a_named_rule_refusal_of_tag_main_reads_no_rule_suite(tmp_path, twin):
    run = probe(tmp_path, twin)
    assert run.r.returncode == 0, run.out
    assert not [c for c in run.calls if c["path"].startswith("rulesets/rule-suites")]


def test_a_lagging_rule_suite_is_waited_for_within_the_bound(tmp_path, twin):
    run = probe(tmp_path, twin, {"tag_main": "other", "suite_lag": 2})
    assert run.r.returncode == 0, run.out
    assert len([c for c in run.calls if c["path"].startswith("rulesets/rule-suites?")]) == 3


def test_a_missing_rule_suite_stops_after_six_reads(tmp_path, twin):
    run = probe(tmp_path, twin, {"tag_main": "other", "no_suite": True, "git_tag": "other"})
    assert run.r.returncode == 1
    assert len([c for c in run.calls if c["path"].startswith("rulesets/rule-suites?")]) == 6
    assert not [c for c in run.calls if c["path"].startswith("rulesets/rule-suites/")]


def test_a_setup_failure_after_the_tag_try_still_judges_it_before_cleanup(tmp_path, twin):
    run = probe(tmp_path, twin, {"tag_main": "other", "fail": {"ref=refs/tags/v1pp-probe": 1}})
    assert run.r.returncode == 1 and "INCONCLUSIVE setup: could not create the tag v1pp-probe" in run.out
    assert any(ln.startswith("PASS tag main: refused") for ln in run.marks("PASS"))
    suite = max(i for i, c in enumerate(run.calls) if c["path"].startswith("rulesets/rule-suites"))
    delete_tag = max(i for i, c in enumerate(run.calls) if c["method"] == "DELETE" and c["path"] == "git/refs/tags/main")
    assert suite < delete_tag


def test_pages_accepted_is_still_fail_when_the_log_lags(tmp_path, twin):
    run = probe(tmp_path, twin, {"log_lag": {"606": 3},
                                 "env_logs": {"502": _line("V1PP-RESULT PAGES api exit=0 {\"status_url\": \"x\"}")}})
    assert run.r.returncode == 2
    assert any(ln.startswith("FAIL tag v1pp-probe pages-api: GitHub accepted") for ln in run.out.splitlines())


# ------------------------------------------------------------------ the job-log read invariant (I-log)
# docs/architecture/v1pp-job-log-invariant.md section 5, tests (a)-(h); v1pp-probe/job-log-unreadable
STORAGE = "https://productionresultssa1.blob.core.windows.net/..."
NEVER_SHOWN = ("sig=", "SECRETSIG", "?sv", "SECRETBODY", "SELFCHECK-BODY")   # the signed URL, a failed body, the check's log
NOT_JUDGED = "not judged: the run's log was not read (see the runner log line)"
JUDGED = re.compile(r"^[A-Z-]+ (W|N|D0|WB|NB|D0B|PUSH) (open|approve|squash|merge|rebase|graphql|rest|git):")


def assert_never_shown(run):
    for where, text in (("out", run.out), ("stderr", run.r.stderr), ("results", run.results)):
        for s in NEVER_SHOWN:
            assert s not in text, (where, s)


def test_an_unreadable_job_log_refuses_before_any_write(tmp_path, twin):
    """(a) v1pp-probe/log-read-selfcheck: the PC can't read a finished job's log, so nothing is written (not even the
    leftover deletes); the reason is in the results file, sanitized; the workflow scope is not even asked for
    (v1pp-probe/selfcheck-before-scope), so there is nothing to give back."""
    run = probe(tmp_path, twin, {"log_fail": {"701": "dns"}, "scopes": "Token scopes: 'gist', 'repo'"})
    assert run.r.returncode == 1, run.out + run.r.stderr
    line = next(ln for ln in run.out.splitlines() if ln.startswith("REFUSED: "))
    assert line == ("REFUSED: could not read the log of finished job 701 (daily-update run 700) after 6 reads (last: "
                    'gh exit 1: gh: Get "' + STORAGE + '": dial tcp: lookup productionresultssa1.blob.core.windows.net:'
                    " no such host); every answer is read from job logs, so the probe stops here "
                    "(v1pp-probe/job-log-unreadable). Nothing was changed. Send this file to the team."), line
    assert line in run.results and "gh exit 1:" in run.results and STORAGE in run.results
    assert "gh: gh version 2.89.0 (2026-11-01)." in run.results          # the header: gh, and the .ps1's PowerShell
    assert (". PowerShell " in run.results) == (twin == "ps1")
    assert not run.writes()
    assert [c["path"] for c in run.calls if c["path"].startswith("actions/jobs/")] == ["actions/jobs/701/logs"] * 6
    assert [c["method"] for c in run.calls].count("auth status") == 1   # the sign-in check only
    assert not [c for c in run.calls if c["method"] == "auth refresh"]
    assert "workflow scope" not in run.out
    assert "(V1'')" not in run.out
    assert_never_shown(run)


@pytest.mark.parametrize("cfg", [
    {"selfcheck_run": "none"},
    {"jobs": {"700": [{"id": 701, "name": "gate", "status": "completed", "conclusion": "cancelled", "steps": []},
                      {"id": 702, "name": "push", "status": "in_progress", "conclusion": None, "steps": []}]}},
], ids=["no-run", "no-finished-job"])
def test_no_finished_daily_update_job_refuses_before_any_write(tmp_path, twin, cfg):
    """(b) nothing to test the read on: refused, nothing changed, no log read."""
    run = probe(tmp_path, twin, cfg)
    assert run.r.returncode == 1, run.out + run.r.stderr
    assert ("REFUSED: could not find a finished daily-update job to test the log read. Nothing was changed."
            in run.results)
    assert not run.writes() and not [c for c in run.calls if c["path"].startswith("actions/jobs/")]


def test_the_log_read_check_uses_the_newest_of_5_runs_with_a_finished_job(tmp_path, twin):
    """v1pp-probe/log-read-selfcheck: the newest completed run was cancelled before any job finished and the next
    one's jobs can't be read, so the third newest is used; older runs are not read."""
    jobs = {"698": [{"id": 690, "name": "gate", "status": "completed", "conclusion": "cancelled", "steps": []}]}
    run = probe(tmp_path, twin, {"selfcheck_runs": [698, 699, 700, 697], "jobs": jobs,
                                 "fail": {"actions/runs/699/jobs": -1}})
    assert run.r.returncode == 0, run.out + run.r.stderr
    assert "Log read check: job 701 of daily-update run 700 read (1 lines)." in run.results
    read = [c["path"] for c in run.calls if re.fullmatch(r"actions/runs/(69[0-9]|700)/jobs", c["path"])]
    assert read == ["actions/runs/698/jobs", "actions/runs/699/jobs", "actions/runs/700/jobs"], read
    assert not [c for c in run.calls if c["path"] in ("actions/jobs/690/logs", "actions/runs/697/jobs")]


def test_the_log_read_check_comes_before_the_first_write_and_shows_no_log_text(tmp_path, twin):
    """(c) the self-check reads before the first DELETE (the leftovers), and only its line count is shown."""
    run = probe(tmp_path, twin)
    assert run.r.returncode == 0, run.out + run.r.stderr
    check = next(i for i, c in enumerate(run.calls) if c["path"] == "actions/jobs/701/logs")
    assert check < run.calls.index(run.writes()[0]) and run.writes()[0]["method"] == "DELETE"
    assert "Log read check: job 701 of daily-update run 700 read (1 lines)." in run.results
    assert_never_shown(run)


def test_an_unread_runner_log_is_not_judged_and_says_why(tmp_path, twin):
    """(d) v1pp-probe/unread-not-absent + log-read-diag: 6 reads, then every line that needs the log is 'not
    judged', never PASS or 'no answer'; the checks without logs still run."""
    run = probe(tmp_path, twin, {"log_fail": {"600": "dns"}})
    assert run.r.returncode == 1, run.out + run.r.stderr
    assert ("INCONCLUSIVE runner log: could not read job 600's log after 6 reads (last: gh exit 1: gh: Get \"" + STORAGE
            + '": dial tcp: lookup productionresultssa1.blob.core.windows.net: no such host)') in run.out
    judged = [ln for ln in run.out.splitlines() if JUDGED.match(ln)]
    assert len(judged) == 3 + 3 * 5 + 2, judged   # bot opens; W, N, D0 x 5; PUSH rest and git
    assert all(ln.startswith("INCONCLUSIVE ") and ln.endswith(": " + NOT_JUDGED) for ln in judged), judged
    assert "no answer in the run's log" not in run.out
    assert [c["path"] for c in run.calls].count("actions/jobs/600/logs") == 6
    for t, b in zip(B, ("probe/v1pp-w-bot", "probe/v1pp-n-bot", "probe/v1pp-d0-bot")):
        assert f"PASS {t} pull request: none from {b}" in run.out
    assert f"PASS main: unchanged at {MAIN}" in run.out and "PASS pull request #77: unmerged" in run.out
    assert run.out.rstrip().splitlines()[-1].startswith("INCONCLUSIVE (V1''):")
    assert_never_shown(run)


def test_a_storage_403_on_the_pages_log_names_the_status_not_the_body(tmp_path, twin):
    """(e) the XML error body on stdout is never shown; gh's stderr line, cut to the host, is."""
    run = probe(tmp_path, twin, {"log_fail": {"605": "s403"}})
    assert run.r.returncode == 1, run.out + run.r.stderr
    assert ("INCONCLUSIVE branch probe/v1pp-env pages-api: could not read the job's log (job 605) after 6 reads (last: "
            "gh exit 1: gh: HTTP 403 (" + STORAGE + "))") in run.out   # the URL's ")" is kept
    assert "HTTP 403" in run.results
    assert_never_shown(run)


def test_an_empty_log_is_unread_not_absent(tmp_path, twin):
    """(f) exit 0 with no log line is a failed read (I-log 1)."""
    run = probe(tmp_path, twin, {"log_fail": {"600": "empty"}})
    assert run.r.returncode == 1, run.out + run.r.stderr
    assert ("INCONCLUSIVE runner log: could not read job 600's log after 6 reads (last: gh exit 0: no error text, 0 "
            "line(s) out)") in run.out
    judged = [ln for ln in run.out.splitlines() if JUDGED.match(ln)]
    assert judged and all(ln.endswith(": " + NOT_JUDGED) for ln in judged), judged
    assert "no answer in the run's log" not in run.out


def test_a_log_with_a_bom_still_passes(tmp_path, twin):
    """(g) F3: GitHub's log body starts with a UTF-8 BOM; the unanchored log-line match is not fooled by it."""
    run = probe(tmp_path, twin, {"log_fail": {"600": "bom", "701": "bom"}})
    assert run.r.returncode == 0, run.out + run.r.stderr
    assert any(ln.startswith("PASS W squash: refused") for ln in run.marks("PASS"))


HOST = "productionresultssa1.blob.core.windows.net"


@pytest.mark.parametrize("how, env, why", [
    ("schemeless", None, "gh: error reading " + HOST + "/... (EOF)"),
    ("jsonesc", None, 'gh: {"message":"Moved","url":"https:\\/\\/' + HOST + '/..."} (HTTP 403)'),
    ("userinfo", None, 'gh: Get "https://' + HOST + '/...": EOF'),
    ("controls", None, "gh: 31mbad gateway x (HTTP 502)"),
    ("dns", {"GH_DEBUG": "api", "DEBUG": "1"}, 'gh: Get "' + STORAGE + '": dial tcp: lookup ' + HOST + ": no such host"),
], ids=["schemeless-url", "json-escaped-url", "userinfo", "c1-and-bidi", "debug-env"])
def test_the_reason_keeps_no_path_query_userinfo_or_controls(tmp_path, twin, how, env, why):
    """v1pp-probe/log-read-diag-query, -userinfo, -controls, gh-debug-legacy: a URL with no scheme, or JSON-escaped,
    keeps only its host; userinfo is dropped; C1 and bidi controls are dropped; DEBUG is cleared with GH_DEBUG."""
    run = probe(tmp_path, twin, {"log_fail": {"701": how}}, env=env)
    assert run.r.returncode == 1, run.out + run.r.stderr
    line = next(ln for ln in run.out.splitlines() if ln.startswith("REFUSED: "))
    assert line[line.index("(last: ") + len("(last: "):line.index("); every answer")] == "gh exit 1: " + why, line
    assert line in run.results
    for text in (run.out, run.results):
        for bad in ("SECRETPASS", "gn0sh:", "actions-results", "DEBUGLINE", "\u009b", "\u0085", "\u202a",
                    "\u202e", "\u2066", "\u2069"):
            assert bad not in text, bad
    assert_never_shown(run)


@pytest.mark.parametrize("how", ["nested-c1", "nested-bidi"])
def test_nested_control_bytes_leave_no_live_control(tmp_path, twin, how):
    """v1pp-probe/log-read-diag-controls-nested: removing the inner control's bytes joins the outer bytes into a new
    control (xc2 xc2 x9b x9b -> U+009B, xe2 x80 xe2 x80 xae xae -> U+202E); it is removed too."""
    run = probe(tmp_path, twin, {"log_fail": {"701": how}})
    assert run.r.returncode == 1, run.out + run.r.stderr
    line = next(ln for ln in run.out.splitlines() if ln.startswith("REFUSED: "))
    assert "gh exit 1: gh: bad  gateway (HTTP 502)" in line, line
    assert line in run.results
    for text in (line, run.results):
        for bad in ("\u009b", "\u202e", "\u0085", "\u202a"):
            assert bad not in text, bad


def test_a_workflow_scope_that_cannot_be_added_is_in_the_results_file(tmp_path, twin):
    """The refusal is logged, not only shown, so the file Brian sends holds it (nothing was changed)."""
    run = probe(tmp_path, twin, {"scopes": "Token scopes: 'gist', 'repo'", "refresh_fail": True})
    assert run.r.returncode == 1, run.out + run.r.stderr
    msg = "Could not add the workflow scope (see above). Nothing was changed."
    assert msg in run.out and msg in run.results
    assert not run.writes()


def test_a_long_token_is_redacted_and_the_reason_is_capped(tmp_path, twin):
    """I-log 4: the first non-blank stderr line only; a run of 32+ token characters becomes <redacted>; 200 chars."""
    run = probe(tmp_path, twin, {"log_fail": {"701": "token"}})
    assert run.r.returncode == 1, run.out + run.r.stderr
    line = next(ln for ln in run.out.splitlines() if ln.startswith("REFUSED: "))
    why = line[line.index("(last: gh exit 1: ") + len("(last: gh exit 1: "):line.index("); every answer")]
    assert why.startswith("gh: bad credentials <redacted> word word") and len(why) == 200, why
    assert "AAAAAAAAAAAAAAAA" not in run.out + run.results and "second line" not in run.out


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
    check = next(i for i, c in enumerate(run.calls) if c["path"] == "actions/jobs/701/logs")
    assert pm < check < refresh[0] < run.calls.index(run.writes()[0])   # v1pp-probe/selfcheck-before-scope
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
                     "nothing was seen to go through", "unlock expired after", "pushed, but no run seen yet",
                     # try 1 decisions (main-protect-invariant.md "V1'' try 1 inconclusive")
                     "'approving review|Repository rule violations found.*New changes require approval from someone "
                     "other than the last pusher'", "rulesets/rule-suites?ref=refs/tags/main&time_period=day&per_page=100",
                     "27685093", "creation", "HTTP 422", "/actions/jobs/$", "/logs", "Unable to find artifact",
                     "'V1PP-RESULT PAGES api exit=[0-9]'", "'V1PP-(RESULT|MERGED|NOPR) (W|N|D0|WB|NB|D0B|PUSH) '",
                     "NOT-REACHABLE by design", "U-pages", "V1'' try 1 inconclusive",
                     "tag main git", "credential.helper=!gh auth git-credential", ":refs/tags/main",
                     "--depth=1", "GIT_TERMINAL_PROMPT", "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
                     "shown refusing the same tag on the git line above",
                     "--no-verify", "core.hooksPath=", "GIT_CONFIG_GLOBAL", "empty.gitconfig", "GIT_TRACE_REDACT",
                     "GIT_ASKPASS", "SSH_ASKPASS", "GIT_CURL_VERBOSE", "'^remote: error: GH013: Repository rule "
                     "violations found for refs/tags/main'", "Everything up-to-date", "git not found",
                     "tag main exists (git answered up-to-date after the REST try created it)",
                     # (h) the job-log read invariant (docs/architecture/v1pp-job-log-invariant.md, I-log)
                     "'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]+)?Z '", "log-read-selfcheck",
                     "not judged: the run's log was not read (see the runner log line)", "GH_DEBUG", "<redacted>",
                     "[A-Za-z0-9%+/=_-]{32,}", "/...", "daily-update.yml/runs?status=completed&per_page=5",
                     "could not find a finished daily-update job to test the log read. Nothing was changed.",
                     "(v1pp-probe/job-log-unreadable). Nothing was changed. Send this file to the team.",
                     "after 6 reads (last: ", "no error text, ", "Log read check: job ",
                     # the try-4 review follow-ups
                     "log-read-diag-query", "log-read-diag-controls", "gh-debug-legacy", "selfcheck-before-scope",
                     "DEBUG", "?..."):
            assert part in s, part
        assert "--log" not in s.replace("gh run view --log gave", "")   # v1pp-probe/run-log-missing
        assert "GH013|rule violation" not in s   # v1pp-probe/tag-git-local-hooks: GitHub's remote line only
        for f in FILES:
            assert f in s, f
        assert "-ExecutionPolicy Bypass" not in s
    # v1pp-probe/pages-api-unreachable: one place makes a NOT-REACHABLE line, in the pages-api judge, and it is not
    # counted against PASS; nothing else is exempt
    assert len(re.findall(r"\bmark NOT-REACHABLE\b", sh)) == 1 and len(re.findall(r"Mark 'NOT-REACHABLE'", ps1)) == 1
    assert sh.index("mark NOT-REACHABLE") > sh.index("pages_refused() {")
    assert ps1.index("Mark 'NOT-REACHABLE'") > ps1.index("function PagesRefused(")
    assert "NOT-REACHABLE) unreach=$((unreach + 1)) ;;" in sh
    # v1pp-probe/pages-jid-pipefail: the jobs are read into a variable first, never piped from the read
    assert 'jobs=$(run_jobs "$2") || jobs=""   # v1pp-probe/pages-jid-pipefail' in sh
    assert not re.search(r'run_jobs "[^"]*"\)?\s*\|(?!\|)', sh)
    assert "elseif ($kind -ceq 'NOT-REACHABLE') { $script:unreach++ }" in ps1
    # the lock: one line flips it, documented in both headers, before anything else runs
    for tw, text in (("sh", sh), ("ps1", ps1)):
        pat = lock_re(tw)
        code_lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
        lock_lines = [ln for ln in code_lines if pat.match(ln)]
        assert len(lock_lines) == 1 and len(pat.findall(text)) == 1, tw   # one lock line, in code not comments
        old = lock_lines[0]
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
        for g in ("CLAUDE_CODE_REMOTE", "protect-main", "tags/main", "records-data", "git not found"):
            assert text.index(g) < w, g
    # v1pp-probe/log-read-selfcheck: the log read check comes before the leftover deletes, the first write; GH_DEBUG is
    # cleared before it
    for text, clear, check, deletes in (
            (sh, "unset GH_DEBUG", 'job_log "$sc_jid" "$log_line"',
             'api_quiet -X DELETE "repos/$repo/git/refs/$r"; done   # leftovers of an earlier try'),
            (ps1, "Remove-Item Env:GH_DEBUG", "JobLog $scJid $logLine",
             'Quiet -X DELETE "repos/$repo/git/refs/$r" }   # leftovers of an earlier try')):
        assert text.index(clear) < text.index(check) < text.index(deletes)
    # PS 5.1: the job-log read keeps stderr apart by type, never by 2>$null (which lost try 3's reason)
    assert 'gh api "repos/$repo/actions/jobs/$jid/logs" 2>&1)' in ps1 and "[Management.Automation.ErrorRecord]" in ps1
    assert "$ErrorActionPreference = 'Continue'" in ps1 and "$ErrorActionPreference = 'Stop'" not in ps1
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
    # v1pp-probe/env-wf-comment-stale: the header says what the probe now does with each answer
    header = envwf_text[:envwf_text.index("\nname:")]
    for part in ("NOT-REACHABLE, not counted", "v1pp-probe/pages-api-unreachable", "exit 0 is FAIL",
                 "own log (v1pp-probe/run-log-missing)"):
        assert part in header, part
    assert "refused for the artifact is INCONCLUSIVE" not in header
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
