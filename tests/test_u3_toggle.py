"""scripts/u3-toggle.{sh,ps1}: the U3 positive control (docs/ops/u3-positive-control.md, ADR 0011 decision 5).

The .sh runs here against a stub gh (no GitHub call is ever made); the .ps1 (no PowerShell here) is pinned to the
same filters, lines and refusals text by text."""
import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SH = ROOT / "scripts" / "u3-toggle.sh"
PS1 = ROOT / "scripts" / "u3-toggle.ps1"
R1P = json.loads((ROOT / "scripts" / "main-ruleset-r1p.json").read_text(encoding="utf-8"))
R1PP = json.loads((ROOT / "scripts" / "main-ruleset.json").read_text(encoding="utf-8"))
REPO = "gn0sh/clarksville-records"
RID = 27502319
MAIN0 = "0" * 40
HEAD = "b" * 40
MERGE = "c" * 40
READ_ONLY = {"id": RID, "source_type": "Repository", "source": REPO, "node_id": "RRS_x", "created_at": "2026-11-10T00:00:00Z",
             "updated_at": "2026-11-18T16:57:12Z", "_links": {"self": {"href": "https://api.github.com/x"}},
             "current_user_can_bypass": "pull_requests_only"}

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is needed by the script and the stub")

_GH = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
a = sys.argv[1:]
calls, statef = os.environ["GH_CALLS"], os.environ["GH_STATE"]
st = json.load(open(statef))
def save():
    json.dump(st, open(statef, "w"))
def log(entry):
    with open(calls, "a") as f:
        f.write(json.dumps(entry) + "\n")
def out(data):
    if "--jq" in a:
        r = subprocess.run(["jq", "-r", a[a.index("--jq") + 1]], input=json.dumps(data), capture_output=True, text=True)
        sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); sys.exit(r.returncode)
    print(json.dumps(data)); sys.exit(0)
R = "repos/gn0sh/clarksville-records"
if a[:2] == ["auth", "status"]:
    sys.exit(0)
assert a[0] == "api", a
args = [x for x in a[1:] if x not in ("--paginate", "--silent")]
method = "GET"
if args[0] == "-X":
    method, args = args[1], args[2:]
path = args[0]
log({"method": method, "path": path, "argv": a})
live = lambda: {**st["ruleset"], **st["read_only"]}
if path == R + "/rulesets/27502319":
    if method == "PUT":
        body = json.load(open(args[args.index("--input") + 1]))
        n = st["puts"] = st.get("puts", 0) + 1
        log({"put_body": body})
        if n in st.get("put_fail", []):
            sys.stderr.write("gh: Resource not accessible by integration (HTTP 403)\n"); save(); sys.exit(1)
        st["ruleset"] = body
        if n in st.get("mutate_put", []):
            st["ruleset"]["rules"][-1]["parameters"]["required_approving_review_count"] = 1
        save(); sys.exit(0)
    n = st["rs_reads"] = st.get("rs_reads", 0) + 1
    save()
    if n in st.get("rs_read_fail", []):
        sys.stderr.write("gh: HTTP 502\n"); sys.exit(1)
    out(live())
if path.startswith(R + "/actions/workflows/daily-update.yml/runs"):
    out({"workflow_runs": [{"status": s} for s in st["runs"]]})
if path == R + "/git/ref/heads/main":
    n = st["main_reads"] = st.get("main_reads", 0) + 1
    if n in st.get("main_fail", []) or (st.get("main_fail_from") and n >= st["main_fail_from"]):
        save(); sys.stderr.write("gh: HTTP 502\n"); sys.exit(1)
    if st.get("merge_at") and n >= st["merge_at"] and not st["pr"]["merged"]:
        st["pr"].update(merged=True, merged_by={"login": st.get("merger", "gn0sh")}, merge_commit_sha=st["merge_sha"])
        st["main"] = st.get("main_after", st["merge_sha"])
    if st.get("other_actor_at") and n >= st["other_actor_at"]:
        st["main"] = "e" * 40
    save()
    out({"object": {"sha": st["main"]}})
if path == R + "/pulls/%s/files?per_page=100" % st["pr_number"]:
    out(st["files"])
if path == R + "/pulls/%s/reviews" % st["pr_number"]:
    out({"commit_id": st["pr"]["head"]["sha"]})
if path == R + "/pulls/%s/merge" % st["pr_number"]:
    if st.get("merge_refuse"):
        st["moved_on"] = True; save()
        if st.get("refuse_moves_main"):
            st["main"] = "e" * 40; save()
        sys.stderr.write(st.get("merge_msg", "gh: At least 2 approving reviews are required by reviewers with write access. (HTTP 405)") + "\n")
        sys.exit(1)
    st["moved_on"] = True
    st["pr"].update(merged=True, merged_by={"login": "gn0sh"}, merge_commit_sha=st["merge_sha"], state="closed")
    st["main"] = st["merge_sha"]; save()
    out({"sha": st["merge_sha"]})
if path == R + "/pulls/%s" % st["pr_number"]:
    if st.get("head_after") and st.get("moved_on"):     # someone pushed P after the merge try or the comment
        st["pr"]["head"]["sha"] = st["head_after"]
    out(st["pr"])
if method == "DELETE":
    sys.exit(0)
if path == R + "/issues/%s/comments?per_page=100" % st["pr_number"]:
    st["moved_on"] = True; save()
    out(st.get("comments", []))
if path.startswith(R + "/rulesets/rule-suites?"):
    assert "ref=main" in path, path
    out(st.get("suites", []))
if path.startswith(R + "/rulesets/rule-suites/"):
    out(st["suite"])
sys.stderr.write("stub: unexpected call %r\n" % a); sys.exit(9)
'''

_DATE = r'''#!/bin/sh
for x in "$@"; do
  [ "$x" = "+%H%M" ] && { echo "$FAKE_HM"; exit 0; }
  if [ "$x" = "+%s" ] && [ -n "${FAKE_S_STEP:-}" ]; then
    n=$(cat "$GH_STATE.s" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$GH_STATE.s"
    echo $((1000000 + n * FAKE_S_STEP)); exit 0
  fi
done
exec /bin/date "$@"
'''


def _state(**over):
    pr = {"number": 60, "state": "open", "base": {"ref": "main"}, "user": {"login": "gn0sh"}, "draft": False,
          "mergeable": True, "changed_files": 1, "merged": False, "merged_by": None, "merge_commit_sha": None,
          "head": {"sha": HEAD, "ref": "claude/u3-pr-p", "repo": {"full_name": REPO}}}
    st = {"ruleset": json.loads(json.dumps(R1P)), "read_only": dict(READ_ONLY), "runs": ["completed"] * 3,
          "main": MAIN0, "pr_number": 60, "pr": pr, "files": [{"filename": "docs/platform-facts.md"}],
          "merge_sha": MERGE, "suites": [{"id": 777, "after_sha": MERGE, "result": "bypass"}],
          "suite": {"id": 777, "result": "bypass", "rule_evaluations": [
              {"rule_source": {"type": "ruleset", "id": RID, "name": "main: pull request required"},
               "enforcement": "active", "result": "fail", "rule_type": "pull_request"},
              {"rule_source": {"type": "ruleset", "id": RID}, "enforcement": "active", "result": "pass",
               "rule_type": "deletion"}]}}
    for k, v in over.items():
        if k == "pr":
            st["pr"].update(v)
        else:
            st[k] = v
    return st


def _env(tmp_path, st, hm="1400"):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for name, text in (("gh", _GH), ("date", _DATE), ("sleep", "#!/bin/sh\nexec /bin/sleep ${STUB_SLEEP:-0}\n")):
        (bindir / name).write_text(text)
        (bindir / name).chmod(0o755)
    (tmp_path / "state.json").write_text(json.dumps(st))
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_CALLS": str(tmp_path / "calls"),
            "GH_STATE": str(tmp_path / "state.json"), "FAKE_HM": hm, "HOME": str(home)}


def _run(tmp_path, args, st=None, hm="1400", timeout=60, script=SH, **env_over):
    env = {**_env(tmp_path, st or _state(), hm), **env_over}
    r = subprocess.run(["bash", str(script), *args], env=env, capture_output=True, text=True, timeout=timeout)
    return r, _calls(tmp_path)


def _calls(tmp_path):
    p = tmp_path / "calls"
    return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []


def _puts(made):
    return [c["put_body"] for c in made if "put_body" in c]


def _wl(o):
    """The whitelist the scripts must apply, in Python (rules sorted by type, actors by type/id/mode)."""
    return {"name": o["name"], "target": o["target"], "enforcement": o["enforcement"], "conditions": o["conditions"],
            "bypass_actors": sorted(({k: b[k] for k in ("actor_id", "actor_type", "bypass_mode")}
                                     for b in o["bypass_actors"]),
                                    key=lambda b: (b["actor_type"], b["actor_id"], b["bypass_mode"])),
            "rules": sorted(({"type": r["type"], **({"parameters": r["parameters"]} if r.get("parameters") is not None
                                                    else {})} for r in o["rules"]), key=lambda r: r["type"])}


def _verdict(out):
    lines = [ln for ln in out.splitlines() if ln.startswith("U3 VERDICT ")]
    assert len(lines) == 1, out
    return lines[0]


def _assert_restored(r, made, verdict):
    """The window opened, R1'' went in first, R1' (the whitelisted backup) went in last and read back; then the
    verdict line, after RESTORED."""
    out = r.stdout
    puts = _puts(made)
    assert puts and puts[0] == _wl(R1PP) and puts[-1] == _wl(R1P), puts
    assert "RESTORED " in out and "RESTORE FAILED" not in out, out
    assert out.index("RESTORED ") < out.index("U3 VERDICT "), out
    line = _verdict(out)
    assert line.startswith(f"U3 VERDICT {verdict} "), line
    assert r.returncode == (0 if verdict == "PASS" else 2), (r.returncode, out, r.stderr)
    return line


# ---------------------------------------------------------------------------------------------- R1'' json, ADR 0011


def test_r1pp_json_is_adr_0011_decision_5_and_otherwise_r1_prime():
    adr = (ROOT / "docs" / "adr" / "0011-data-off-main.md").read_text(encoding="utf-8")
    d5 = adr[adr.index("5. **Ruleset R1'' on `main`:**"):adr.index("6. **R2 off")]
    for s in ("`required_approving_review_count: 2`", "`dismiss_stale_reviews_on_push: true`",
              "`require_last_push_approval: true`", "`require_code_owner_review: false`", "squash only",
              "bypass Repository admin role", "`pull_request` mode"):
        assert s in d5, s
    pr = [x for x in R1PP["rules"] if x["type"] == "pull_request"][0]["parameters"]
    assert pr["required_approving_review_count"] == 2 and pr["dismiss_stale_reviews_on_push"] is True
    assert pr["require_last_push_approval"] is True and pr["require_code_owner_review"] is False
    assert pr["allowed_merge_methods"] == ["squash"]
    assert R1PP["bypass_actors"] == [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]
    # everything else is R1' unchanged: other rules, conditions, bypass, name, and the other pull_request parameters
    changed = {"required_approving_review_count", "require_last_push_approval", "require_code_owner_review"}
    prime = [x for x in R1P["rules"] if x["type"] == "pull_request"][0]["parameters"]
    assert set(pr) == set(prime) and {k for k in pr if pr[k] != prime[k]} == changed
    strip = lambda o: {**o, "rules": [x for x in o["rules"] if x["type"] != "pull_request"]}
    assert strip(R1PP) == strip(R1P)
    for p in ("main-ruleset-r1p.json", "main-ruleset.json"):   # BOM-less ASCII, read by both scripts
        raw = (ROOT / "scripts" / p).read_bytes()
        assert raw[:1] == b"{" and all(b < 0x80 for b in raw), p
    for script in (SH, PS1):
        text = script.read_text(encoding="utf-8")
        assert "main-ruleset.json" in text and "main-ruleset-r1p.json" in text, script.name


# ---------------------------------------------------------------------------------------------- the whitelist


def test_the_whitelist_drops_every_read_only_field(tmp_path):
    get = {**READ_ONLY, **json.loads(json.dumps(R1P))}
    get["bypass_actors"] = [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]
    get["rules"] = list(reversed(get["rules"]))                        # GitHub's order does not matter
    (tmp_path / "get.json").write_text(json.dumps(get))
    r = subprocess.run(["bash", str(SH), "--show-body", str(tmp_path / "get.json")], capture_output=True, text=True,
                       env={**os.environ, "PATH": f"/nonexistent-gh:{os.environ['PATH']}"})
    assert r.returncode == 0, r.stderr
    body = json.loads(r.stdout)
    assert body == _wl(R1P)
    assert list(body) == ["name", "target", "enforcement", "conditions", "bypass_actors", "rules"]
    for k in READ_ONLY:
        assert f'"{k}"' not in r.stdout, k


def test_every_put_body_is_whitelisted(tmp_path):
    r, made = _run(tmp_path, ["--pr", "60", "--merge", "--report", "docs/reviews/x.md"])
    assert r.returncode == 0, r.stdout + r.stderr
    for body in _puts(made):
        assert set(body) == {"name", "target", "enforcement", "conditions", "bypass_actors", "rules"}, body
    # every PUT of the ruleset is an --input file, never a pipe or -f fields
    for c in made:
        if c.get("method") == "PUT" and c["path"].endswith("/rulesets/27502319"):
            assert "--input" in c["argv"] and not any(x.startswith(("-f", "-F")) for x in c["argv"]), c
    backup = next(Path(p) for p in (tmp_path / "home").iterdir() if p.name.startswith("u3-ruleset-backup-"))
    assert json.loads(backup.read_text()) == _wl(R1P)
    assert re.search(rf"^U3 WINDOW OPEN \d{{4}}-\d\d-\d\dT\d\d:\d\d:\d\dZ BACKUP {re.escape(str(backup))}$", r.stdout, re.M)
    assert f"\nBACKUP {backup}\n" in r.stdout


# ---------------------------------------------------------------------------------------------- verdicts


def test_pass_team_path(tmp_path):
    r, made = _run(tmp_path, ["--pr", "60", "--merge", "--report", "docs/reviews/x.md"])
    line = _assert_restored(r, made, "PASS")
    assert "rule-suite 777:" in line and f"merged by gn0sh as {MERGE}" in line
    assert "result=bypass pull_request=fail enforcement=active" in line
    merges = [c for c in made if c.get("path", "").endswith("/pulls/60/merge")]
    assert len(merges) == 1 and f"sha={HEAD}" in merges[0]["argv"]
    # R1'' was in force at the merge: the merge comes after the R1'' PUT and before the restore PUT
    order = [("put" if "put_body" in c else c.get("path")) for c in made]
    first_put, last_put = order.index("put"), len(order) - 1 - order[::-1].index("put")
    assert first_put < order.index(f"repos/{REPO}/pulls/60/merge") < last_put


def test_pass_brians_path_waits_for_main_to_move(tmp_path):
    st = _state(merge_at=4)
    r, made = _run(tmp_path, ["--pr", "60"], st)
    _assert_restored(r, made, "PASS")
    assert "type U3 go" in r.stdout
    assert not any(c.get("path", "").endswith("/merge") for c in made)          # the team merges, not this script


@pytest.mark.parametrize("suite_result", ["bypass", "pass"])
def test_fail_rule_when_the_pull_request_evaluation_reads_pass(tmp_path, suite_result):
    """v1-probe/u3-false-pass-on-pr-eval-pass: a pass evaluation means 2 approvals did not bind, so a bypass suite
    with it must never read PASS."""
    st = _state(suites=[{"id": 778, "after_sha": MERGE, "result": suite_result}])
    st["suite"]["result"] = suite_result
    st["suite"]["rule_evaluations"][0]["result"] = "pass"
    r, made = _run(tmp_path, ["--pr", "60", "--merge", "--report", "x"], st)
    line = _assert_restored(r, made, "FAIL-RULE")
    assert "rule-suite 778:" in line and f"result={suite_result} pull_request=pass" in line


def _suite_shape(suite_result=None, evals=None, enforcement=None):
    st = _state()
    if suite_result:
        st["suite"]["result"] = suite_result
    if enforcement:
        st["suite"]["rule_evaluations"][0]["enforcement"] = enforcement
    if evals is not None:
        st["suite"]["rule_evaluations"] = evals
    return st


_PR_EVAL = {"rule_source": {"type": "ruleset", "id": RID}, "enforcement": "active", "result": "fail",
            "rule_type": "pull_request"}


@pytest.mark.parametrize("st,why", [
    (_suite_shape("pass"), "not bypass+fail"),                                       # pass + fail
    (_suite_shape("fail"), "not bypass+fail"),
    (_suite_shape(enforcement="evaluate"), "was not enforced"),
    (_suite_shape(evals=[]), "got 0"),
    (_suite_shape(evals=[_PR_EVAL, _PR_EVAL]), "got 2"),
    (_suite_shape(evals=[{**_PR_EVAL, "rule_source": {"type": "ruleset", "id": 1}}]), "got 0"),   # another ruleset
], ids=["pass-fail", "fail-fail", "evaluate-mode", "no-evaluation", "two-evaluations", "other-ruleset"])
def test_any_other_suite_shape_is_inconclusive(tmp_path, st, why):
    r, made = _run(tmp_path, ["--pr", "60", "--merge", "--report", "x"], st)
    line = _assert_restored(r, made, "INCONCLUSIVE")
    assert why in line and "rule suite 777 result=" in line, line


def test_fail_u3_team_merge_refused_restores(tmp_path):
    r, made = _run(tmp_path, ["--pr", "60", "--merge", "--report", "x"], _state(merge_refuse=True))
    line = _assert_restored(r, made, "FAIL-U3")
    assert "HTTP 405" in line and "rule-suite none" in line


_LATE = "2999-01-01T00:00:00Z"
_REFUSED = "U3 merge refused: gh: At least 2 approving reviews are required (HTTP 405)"


def test_fail_u3_brians_path_from_the_teams_refusal_comment(tmp_path):
    st = _state(comments=[{"user": {"login": "someone"}, "created_at": _LATE, "body": "U3 merge refused: fake 405 review"},
                          {"user": {"login": "gn0sh"}, "created_at": _LATE, "body": _REFUSED + "\nsecond line"}],
                pr={"merge_commit_sha": "d" * 40})        # GitHub's test merge sha on an open PR: fields must not shift
    r, made = _run(tmp_path, ["--pr", "60"], st)
    line = _assert_restored(r, made, "FAIL-U3")
    assert "(HTTP 405)" in line and "fake" not in line and f"at {HEAD} was refused" in line


@pytest.mark.parametrize("comment,pr,why", [
    ("Note: U3 merge refused (HTTP 405) reviews", {}, "no merge in the 20-minute window"),   # must START with it
    ("U3 merge refused: gh: something else (HTTP 502)", {}, "without a ruleset refusal"),
    ("U3 merge refused: gh: Not allowed (HTTP 405)", {}, "without a ruleset refusal"),     # 405 naming no review
    (_REFUSED, {"head": {"sha": "f" * 40, "ref": "x", "repo": {"full_name": REPO}}}, "head is now " + "f" * 40),
], ids=["not-at-start", "not-405", "405-no-review", "head-moved"])
def test_a_refusal_comment_reads_fail_u3_only_when_it_holds(tmp_path, comment, pr, why):
    st = _state(comments=[{"user": {"login": "gn0sh"}, "created_at": _LATE, "body": comment}])
    if pr:   # the head moves once the comment is read: the preflight saw HEAD
        st["head_after"] = pr["head"]["sha"]
    r, made = _run(tmp_path, ["--pr", "60"], st)
    assert why in _assert_restored(r, made, "INCONCLUSIVE")


@pytest.mark.parametrize("over,why", [
    ({"merge_msg": "gh: Base branch was modified. Review and try the merge again. (HTTP 405)"},
     "without a ruleset refusal"),                                       # v1-probe/u3-405-wording
    ({"refuse_moves_main": True}, "main is at " + "e" * 40),
], ids=["base-modified-405", "main-moved"])
def test_a_team_405_that_is_not_the_approval_rule_is_inconclusive(tmp_path, over, why):
    r, made = _run(tmp_path, ["--pr", "60", "--merge", "--report", "x"], _state(merge_refuse=True, **over))
    assert why in _assert_restored(r, made, "INCONCLUSIVE")


def test_a_team_refusal_at_a_moved_head_is_inconclusive(tmp_path):
    st = _state(merge_refuse=True, head_after="f" * 40)
    r, made = _run(tmp_path, ["--pr", "60", "--merge", "--report", "x"], st)
    assert "head is now" in _assert_restored(r, made, "INCONCLUSIVE")


def test_an_old_refusal_comment_does_not_count(tmp_path):
    st = _state(merge_at=3, comments=[{"user": {"login": "gn0sh"}, "created_at": "2000-01-01T00:00:00Z",
                                       "body": "U3 merge refused: from an earlier run"}])
    r, made = _run(tmp_path, ["--pr", "60"], st)
    _assert_restored(r, made, "PASS")


@pytest.mark.parametrize("over,why", [
    ({}, "no merge in the 20-minute window"),
    ({"main_fail_from": 2}, "main could not be read four times running"),             # read failure
    ({"other_actor_at": 3}, "is not merged (another actor)"),
    ({"merge_at": 2, "main_after": "e" * 40}, "(another actor)"),
    ({"merge_at": 2, "merger": "github-actions[bot]"}, "not gn0sh"),
    ({"merge_at": 2, "suites": []}, "no rule suite listed it within the window"),
    ({"merge_at": 2, "rs_read_fail": [3]}, "could not be read at the end of the window"),
], ids=["no-merge", "read-failure", "main-moved-unmerged", "main-not-merge-commit", "bot-merged", "no-suite",
        "ruleset-unread"])
def test_inconclusive_still_restores(tmp_path, over, why):
    r, made = _run(tmp_path, ["--pr", "60"], _state(**over))
    line = _assert_restored(r, made, "INCONCLUSIVE")
    assert why in line, line


def test_no_bypass_and_no_pass_is_inconclusive(tmp_path):
    st = _state()
    st["suite"]["result"] = "fail"
    st["suite"]["rule_evaluations"][0]["result"] = "fail"
    r, made = _run(tmp_path, ["--pr", "60", "--merge", "--report", "x"], st)
    assert "not bypass+fail and not a pull_request pass" in _assert_restored(r, made, "INCONCLUSIVE")


def test_readback_mismatch_closes_the_window_and_restores(tmp_path):
    r, made = _run(tmp_path, ["--pr", "60", "--merge", "--report", "x"], _state(mutate_put=[1]))
    line = _assert_restored(r, made, "INCONCLUSIVE")
    assert "R1'' did not read back as written" in line and "U3 WINDOW OPEN" not in r.stdout
    assert not any(c.get("path", "").endswith("/merge") for c in made)


def test_a_refused_r1pp_put_is_still_restored(tmp_path):
    r, made = _run(tmp_path, ["--pr", "60", "--merge", "--report", "x"], _state(put_fail=[1]))
    assert "U3 WINDOW OPEN" not in r.stdout and "RESTORED " in r.stdout
    assert _verdict(r.stdout).startswith("U3 VERDICT INCONCLUSIVE ") and r.returncode == 2


def test_a_failed_restore_is_loud_and_never_pass(tmp_path):
    r, made = _run(tmp_path, ["--pr", "60", "--merge", "--report", "x"], _state(put_fail=[2, 3, 4]))
    assert "RESTORE FAILED" in r.stdout and "--restore" in r.stdout and r.returncode == 3
    failed = next(ln for ln in r.stdout.splitlines() if ln.startswith("RESTORE FAILED"))
    assert re.search(r"BACKUP \S+u3-ruleset-backup-\d{8}-\d{6}\.json", failed), failed
    line = _verdict(r.stdout)
    assert line.startswith("U3 VERDICT INCONCLUSIVE ") and "restore was not verified" in line


def test_ctrl_c_in_the_window_restores(tmp_path):
    env = _env(tmp_path, _state(), "1400")
    env["STUB_SLEEP"] = "0.2"
    p = subprocess.Popen(["bash", str(SH), "--pr", "60"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True)
    seen = []
    deadline = time.time() + 30
    while time.time() < deadline:
        ln = p.stdout.readline()
        seen.append(ln)
        if ln.startswith("U3 WINDOW OPEN"):
            break
    for b in (tmp_path / "home").glob("u3-ruleset-backup-*"):     # u3-restore-source: memory, not the file
        b.unlink()
    time.sleep(0.3)
    p.send_signal(signal.SIGINT)
    rest, err = p.communicate(timeout=60)
    r = subprocess.CompletedProcess(p.args, p.returncode, "".join(seen) + rest, err)
    line = _assert_restored(r, _calls(tmp_path), "INCONCLUSIVE")
    assert "interrupted" in line


# ---------------------------------------------------------------------------------------------- refusals


def _refused(r, made, text):
    assert r.returncode == 1 and "REFUSED" in r.stdout and text in r.stdout, r.stdout + r.stderr
    assert not _puts(made) and not any(c.get("method") in ("PUT", "POST", "DELETE", "PATCH") for c in made)
    assert "U3 WINDOW OPEN" not in r.stdout and "U3 VERDICT" not in r.stdout


@pytest.mark.parametrize("hm", ["0730", "0759", "0800", "0907", "1030"])
def test_refused_from_0730_to_1030_utc(tmp_path, hm):
    """main-protect/window-over-20-min: a start at 07:30 or later could run (30 min) into 08:00-10:30."""
    r, made = _run(tmp_path, ["--pr", "60", "--merge", "--report", "x"], hm=hm)
    _refused(r, made, "could reach the daily run's window (08:00-10:30)")
    assert not made                                       # refused before any GitHub read, too


@pytest.mark.parametrize("hm", ["0729", "1031", "0000", "2359"])
def test_runs_just_outside_the_window(tmp_path, hm):
    r, made = _run(tmp_path, ["--pr", "60", "--merge", "--report", "x"], hm=hm)
    _assert_restored(r, made, "PASS")


@pytest.mark.parametrize("status", ["in_progress", "queued", "waiting"])
def test_refused_while_a_daily_run_is_active(tmp_path, status):
    r, made = _run(tmp_path, ["--pr", "60"], _state(runs=["completed", status]))
    _refused(r, made, "queued or in progress")


def _ruleset(mut):
    rs = json.loads(json.dumps(R1P))
    mut(rs)
    return rs


@pytest.mark.parametrize("over,text", [
    ({"ruleset": _ruleset(lambda r: r["rules"][-1]["parameters"].update(required_approving_review_count=1))},
     "is not R1'"),
    ({"ruleset": _ruleset(lambda r: r["rules"][-1]["parameters"].update(require_code_owner_review=False))},
     "is not R1'"),
    ({"ruleset": _ruleset(lambda r: r.update(enforcement="evaluate"))}, "is not R1'"),
    ({"ruleset": _ruleset(lambda r: r["bypass_actors"].append({"actor_id": 1, "actor_type": "OrganizationAdmin",
                                                                "bypass_mode": "always"}))}, "is not R1'"),
    ({"ruleset": _ruleset(lambda r: r["conditions"]["ref_name"]["include"].append("refs/heads/x"))}, "is not R1'"),
    ({"ruleset": _ruleset(lambda r: r["rules"].pop(0))}, "is not R1'"),
    ({"ruleset": json.loads(json.dumps(R1PP))}, "is not R1'"),                 # stuck on R1'' from a run before
    ({"ruleset": _ruleset(lambda r: r["rules"][0].update(ruleset_id=1))}, "fields this script does not write"),
    ({"read_only": {**READ_ONLY, "current_user_can_bypass": "never"}}, "current_user_can_bypass is 'never'"),
    ({"rs_read_fail": [1]}, "could not read ruleset"),
], ids=["approvals", "code-owner", "enforcement", "extra-bypass", "conditions", "rule-missing", "already-r1pp",
        "nested-extra", "cannot-bypass", "unread"])
def test_refused_unless_the_live_ruleset_is_r1_prime(tmp_path, over, text):
    r, made = _run(tmp_path, ["--pr", "60"], _state(**over))
    _refused(r, made, text)


@pytest.mark.parametrize("over,text", [
    ({"files": [{"filename": "docs/a.md"}, {"filename": "scripts/u3-toggle.sh"}], "pr": {"changed_files": 2}},
     "outside docs/"),
    ({"files": [{"filename": "docs/a.md", "previous_filename": ".github/CODEOWNERS"}]}, "outside docs/"),
    ({"files": [{"filename": "docsx/a.md"}]}, "outside docs/"),
    ({"files": [{"filename": "docs/a.md"}], "pr": {"changed_files": 2}}, "GitHub counts '2'"),
    ({"files": [], "pr": {"changed_files": 0}}, "lists 0 file(s)"),
    ({"pr": {"user": {"login": "github-actions[bot]"}}}, "not gn0sh"),
    ({"pr": {"head": {"sha": HEAD, "ref": "x", "repo": {"full_name": "someone/fork"}}}}, "not gn0sh/clarksville"),
    ({"pr": {"draft": True}}, "is a draft"),
    ({"pr": {"state": "closed"}}, "is not open into main"),
    ({"pr": {"base": {"ref": "records-data"}}}, "is not open into main"),
    ({"pr": {"mergeable": False}}, "is not mergeable"),
    ({"pr": {"mergeable": None}}, "is not mergeable (null)"),
], ids=["code-file", "rename-from-outside", "prefix-lookalike", "count-mismatch", "no-files", "bot-author", "fork",
        "draft", "closed", "wrong-base", "conflict", "still-computing"])
def test_refused_unless_pr_p_is_a_docs_only_pr_of_gn0sh(tmp_path, over, text):
    r, made = _run(tmp_path, ["--pr", "60", "--merge", "--report", "x"], _state(**over))
    _refused(r, made, text)


@pytest.mark.parametrize("args", [[], ["--pr", "x"], ["--pr", "60", "--merge"], ["--bogus"]])
def test_usage_errors_change_nothing(tmp_path, args):
    r, made = _run(tmp_path, args)
    assert r.returncode == 1 and not _puts(made)


# ---------------------------------------------------------------------------------------------- --restore, --noop


def test_restore_puts_r1_prime_and_reads_it_back(tmp_path):
    r, made = _run(tmp_path, ["--restore"], _state(ruleset=json.loads(json.dumps(R1PP))))
    assert r.returncode == 0 and "RESTORED " in r.stdout, r.stdout
    assert _puts(made) == [_wl(R1P)]


def test_restore_from_a_backup_file_and_a_failed_restore(tmp_path):
    (tmp_path / "b.json").write_text(json.dumps(_wl(R1P)))
    r, made = _run(tmp_path, ["--restore", str(tmp_path / "b.json")], _state(put_fail=[1, 2, 3]))
    assert r.returncode == 3 and "RESTORE FAILED" in r.stdout and len(_puts(made)) == 3


def test_noop_writes_the_live_body_back_unchanged(tmp_path):
    r, made = _run(tmp_path, ["--noop"])
    assert r.returncode == 0 and "NOOP OK" in r.stdout, r.stdout
    assert _puts(made) == [_wl(R1P)]


@pytest.mark.parametrize("over,code,text", [({"put_fail": [1]}, 1, "NOOP REFUSED"),
                                            ({"mutate_put": [1]}, 3, "NOOP CHANGED")])
def test_noop_reports_a_refusal_or_a_change(tmp_path, over, code, text):
    r, made = _run(tmp_path, ["--noop"], _state(**over))
    assert r.returncode == code and text in r.stdout, r.stdout


# ---------------------------------------------------------------------------------------------- the .ps1 twin


def _jq_filters(text):
    return sorted(set(re.findall(r"--jq '([^']*)'", text)))


def test_ps1_is_ascii_bom_less_and_51_safe():
    raw = PS1.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and all(b < 0x80 for b in raw)
    assert all(b < 0x80 for b in SH.read_bytes())
    ps1 = raw.decode("ascii")
    assert "ExecutionPolicy" not in ps1
    assert not re.search(r"--jq '[^']*\"", ps1)                       # no double quote reaches gh (PS 5.1)
    assert not re.search(r"\|\s*gh\b", ps1)                            # nothing is piped into gh (BOM)
    for bad in ("??", "?.", "&&", "||", "-AsHashtable", "ConvertFrom-Json -Depth"):   # PowerShell 7 only
        assert bad not in ps1, bad
    assert "New-Object Text.UTF8Encoding $false" in ps1 and "[IO.File]::WriteAllText($path, $json, $utf8)" in ps1


def test_ps1_uses_the_same_gh_filters_as_the_sh():
    assert _jq_filters(PS1.read_text(encoding="utf-8")) == _jq_filters(SH.read_text(encoding="utf-8"))


def test_ps1_has_the_same_steps_lines_and_refusals():
    ps1 = PS1.read_text(encoding="utf-8")
    sh = SH.read_text(encoding="utf-8")
    for s in ("U3 WINDOW OPEN $opened BACKUP $($script:backup)", "RESTORED ", "U3 VERDICT ", "RESTORE FAILED",
              "U3 REHEARSAL WINDOW OPEN ", "U3 REHEARSAL DONE", "U3 REHEARSAL FAILED", "[switch]$Rehearse",
              "BACKUP $($script:backup)", "[DateTime]::UtcNow.AddMinutes(20)", "[DateTime]::UtcNow -ge $deadline",
              "$hm -ge 730 -and $hm -le 1030", "if (-not (PinOk))", "$script:backupObj = $live",
              "$suiteResult -ceq 'bypass' -and $prEval -ceq 'fail'", "$prEnf -cne 'active'", "$ev.Count -ne 3",
              "$script:prSt[3] -cne $head", "'(?i)approving review'", "$m -cne $mainBefore", "startswith($ENV.U3_REFUSED)", "$env:U3_REFUSED = 'U3 merge refused'",
              "'PASS'", "'FAIL-U3'", "'FAIL-RULE'", "'INCONCLUSIVE'", "NOOP OK", "NOOP REFUSED", "NOOP CHANGED",
              "Start-Sleep -Seconds 15", "$i -le 80", "$fails -ge 4",
              "-cne 'completed'", "'pull_requests_only'", "'always'", "StartsWith('docs/', [StringComparison]::Ordinal)",
              "U3 merge refused", "HTTP 405", "merge-reviewed.ps1", "$rid = '27502319'",
              "gh api -X PUT \"repos/$repo/rulesets/$rid\" --input $path --silent", "Wl $o",
              "Remove-TypeData System.Array"):
        assert s in ps1, s
    for s in ("U3 WINDOW OPEN $opened BACKUP $backup", "-ge 730 ] && [ $((10#$hm)) -le 1030", "sleep 15",
              "U3 REHEARSAL WINDOW OPEN", "U3 REHEARSAL DONE", "U3 REHEARSAL FAILED", "deadline=$(( $(date +%s) + 1200 ))",
              '[ "$suite_result" = bypass ] && [ "$pr_eval" = fail ]', '[ "$pr_enf" != active ]', "pin_ok ||",
              '[ "$h" = "$head" ]', 'U3_REFUSED="U3 merge refused"', 'backup_json=$(jq -c "$wl" "$work/live.json")',
              "seq 1 80", '"$fails" -lt 4', "merge-reviewed.sh", "rid=27502319", "U3 merge refused", "HTTP 405"):
        assert s in sh, s
    # exactly one PUT of the ruleset in each script, and it sends the whitelisted body file
    hint = "gh api -X PUT repos/$repo/rulesets/$rid --input '$backup'"
    assert ps1.count("-X PUT") == 2 and sh.count("-X PUT") == 2 and hint in sh
    assert "gh api -X PUT repos/$repo/rulesets/$rid --input '$($script:backup)'" in ps1
    # every refusal message of the .sh is in the .ps1 (the shared text after "refuse"/"Refuse")
    for msg in set(re.findall(r'refuse "([^"$]{12,})', sh)) - {"could not read the UTC time"}:   # Get-Date can't fail
        assert msg.split("'")[0].split("(")[0].strip() in ps1, msg
    # the restore runs in finally, after RunWindow, and the window is armed before the first PUT
    body = ps1[ps1.index("function RunWindow"):]
    assert body.index("$script:armed = $true") < body.index("PutVerify (ReadJsonFile $r1pp)")
    assert re.search(r"try \{\s*RunWindow\s*\} finally \{\s*if \(\$script:armed\) \{ CloseWindow \}\s*\}", ps1)
    close = ps1[ps1.index("function CloseWindow"):]
    assert close.index("RestoreFrom $src $label") < close.index("U3 REHEARSAL DONE") < close.index("U3 VERDICT")
    assert "$src = $script:backupObj" in close and "$src = ReadJsonFile $r1p" in close
    # the whitelist keeps exactly the fields the .sh keeps
    wl = ps1[ps1.index("function Wl("):ps1.index("function Canon(")]
    for k in ("name = $o.name", "target = $o.target", "enforcement = $o.enforcement", "conditions = $o.conditions",
              "bypass_actors = $actors", "rules = $rules", "actor_id = $a.actor_id", "actor_type = $a.actor_type",
              "bypass_mode = $a.bypass_mode", "type = $x.type; parameters = $x.parameters"):
        assert k in wl, k
    assert "current_user_can_bypass" not in wl and "_links" not in wl


# ---------------------------------------------------------------------------------------------- window bound, pin, rehearsal


def test_the_window_ends_20_minutes_after_it_opened(tmp_path):
    """main-protect/u3-window-bound: a wall-clock deadline (each date +%s here is 5 minutes later), not 80 sleeps."""
    r, made = _run(tmp_path, ["--pr", "60"], _state(), FAKE_S_STEP="300")
    assert "no merge in the 20-minute window" in _assert_restored(r, made, "INCONCLUSIVE")
    assert sum(1 for c in made if c.get("path", "").endswith("/git/ref/heads/main")) < 8


def test_the_deadline_also_bounds_the_rule_suite_reads(tmp_path):
    r, made = _run(tmp_path, ["--pr", "60", "--merge", "--report", "x"], _state(suites=[]), FAKE_S_STEP="700")
    assert "no rule suite listed it within the window" in _assert_restored(r, made, "INCONCLUSIVE")
    assert sum(1 for c in made if "rule-suites?" in c.get("path", "")) < 8


@pytest.mark.parametrize("change", [
    lambda pp: pp.update(dismiss_stale_reviews_on_push=False),        # a fourth parameter changed
    lambda pp: pp.update(required_approving_review_count=1),           # one of the three, wrong value
    lambda pp: pp.update(allowed_merge_methods=["squash", "merge"]),
], ids=["fourth-param", "wrong-count", "merge-methods"])
def test_refused_unless_r1pp_is_pinned_to_adr_0011(tmp_path, change):
    """v1-probe/u3-r1pp-pin: the preflight itself checks R1'' = R1' plus exactly the three decision-5 values."""
    sdir = tmp_path / "scripts"
    sdir.mkdir()
    for name in ("u3-toggle.sh", "main-ruleset-r1p.json", "merge-reviewed.sh"):
        shutil.copy(ROOT / "scripts" / name, sdir / name)
    rs = json.loads(json.dumps(R1PP))
    change([x for x in rs["rules"] if x["type"] == "pull_request"][0]["parameters"])
    (sdir / "main-ruleset.json").write_text(json.dumps(rs))
    r, made = _run(tmp_path, ["--pr", "60"], script=sdir / "u3-toggle.sh")
    _refused(r, made, "is not R1' with only ADR 0011 decision 5's three changes")


def test_rehearsal_puts_r1_prime_twice_and_prints_no_verdict(tmp_path):
    """v1-probe/ps1-never-executed: the whole preflight, a window that changes nothing, the real restore path."""
    r, made = _run(tmp_path, ["--pr", "60", "--rehearse"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert _puts(made) == [_wl(R1P), _wl(R1P)]
    out = r.stdout
    assert "U3 REHEARSAL WINDOW OPEN " in out and "BACKUP " in out and "RESTORED " in out
    assert out.index("U3 REHEARSAL WINDOW OPEN") < out.index("RESTORED ") < out.index("U3 REHEARSAL DONE")
    assert "U3 VERDICT" not in out and "U3 WINDOW OPEN" not in out
    assert not any(c.get("path", "").endswith("/merge") or "rule-suites" in c.get("path", "") for c in made)


def test_rehearsal_runs_the_same_preflight(tmp_path):
    r, made = _run(tmp_path, ["--pr", "60", "--rehearse"], _state(files=[{"filename": "sitegen/x.py"}]))
    _refused(r, made, "outside docs/")
    sub = tmp_path / "b"
    sub.mkdir()
    r, made = _run(sub, ["--pr", "60", "--rehearse"], hm="0900")
    _refused(r, made, "could reach the daily run's window")


def test_rehearsal_ctrl_c_restores(tmp_path):
    env = _env(tmp_path, _state(), "1400")
    env["STUB_SLEEP"] = "0.3"
    p = subprocess.Popen(["bash", str(SH), "--pr", "60", "--rehearse"], env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    seen = []
    while True:
        ln = p.stdout.readline()
        seen.append(ln)
        if not ln or ln.startswith("U3 REHEARSAL WINDOW OPEN"):
            break
    time.sleep(0.2)
    p.send_signal(signal.SIGINT)
    rest, err = p.communicate(timeout=60)
    out = "".join(seen) + rest
    assert p.returncode == 0 and "RESTORED " in out and "U3 REHEARSAL DONE" in out and "interrupted" in out, out + err
    assert _puts(_calls(tmp_path)) == [_wl(R1P), _wl(R1P)]


def test_a_failed_rehearsal_restore_is_loud(tmp_path):
    r, made = _run(tmp_path, ["--pr", "60", "--rehearse"], _state(put_fail=[2, 3, 4]))
    assert r.returncode == 3 and "U3 REHEARSAL FAILED" in r.stdout and "RESTORE FAILED" in r.stdout
