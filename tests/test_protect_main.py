"""scripts/protect-main.{sh,ps1} and scripts/merge-reviewed.{sh,ps1} under ADR 0011 (task D1; consumer rows R1, R-D,
R2, S1, S2; PR #54 security review findings F1, F2 and settings drift).

The .sh scripts run here against a stub gh (no GitHub call is ever made: the stub is first on PATH and the GitHub
tokens are removed from the environment). With PWSH set, every test that runs a script also runs its .ps1 twin against
the same stub (tests/pwsh_twin.py); the .ps1 twins are also pinned to the same filters, lines and refusals text by
text."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import pwsh_twin

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
PM_SH, PM_PS1 = SCRIPTS / "protect-main.sh", SCRIPTS / "protect-main.ps1"
MR_SH, MR_PS1 = SCRIPTS / "merge-reviewed.sh", SCRIPTS / "merge-reviewed.ps1"
REPO = "gn0sh/clarksville-records"
R = "repos/" + REPO
FILES = {"R1''": "main-ruleset.json", "R-D": "records-data-ruleset.json", "R-T": "main-tag-ruleset.json"}
BODY = {k: json.loads((SCRIPTS / v).read_text(encoding="utf-8")) for k, v in FILES.items()}
R1P = json.loads((SCRIPTS / "main-ruleset-r1p.json").read_text(encoding="utf-8"))
CLOUD = ("CLAUDE_CODE_REMOTE", "GITHUB_ACTIONS", "CI")
# S1-1: GitHub's REST schema (repository-rule-pull-request, github/rest-api-description, read 2026-11-19) gives
# required_approving_review_count minimum 0, maximum 10
MAX_APPROVALS = 10
WF_PATH = f"repos/{REPO}/contents/.github/workflows/daily-update.yml?ref=main"
GATE_STEP = "Check main's history and the records-data head"
OLD_STEP = "Open and merge the data pull request"
# The job and permission lines of daily-update.yml after B2/B3 (claude/data-off-main-b23 at 13598f76), with its
# comment traps: header comments that name attestations: write and a trailing comment on a permission line.
POST_WF = """# push job   : ... The only job with contents: write or attestations:
#              write; id-token: write is held by it and deploy only.
on:
  workflow_dispatch:
permissions: {}

jobs:
  # main-protect gate (ADR 0011): only the push job holds attestations: write
  gate:
    runs-on: ubuntu-24.04
    permissions:
      contents: read         # read the history and records-data (not contents: write)
      pull-requests: read    # read each commit's pull request and its reviews
      attestations: read     # read the attestations of records-data's listing (I-prov)
    steps:
      - name: Check out this run's commit
        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
      - name: Check main's history and the records-data head
        id: check
        run: |
          echo "attestations: write"
  update:
    needs: gate
    permissions:
      contents: read
    steps:
      - name: Check out the gate's commit
        run: true
  push:
    needs: [gate, update]
    # attestations: write; id-token: write is held only here
    permissions:
      contents: write        # push records-data: the only job that can write to the repository
      id-token: write        # sign the listing's attestation
      attestations: write    # store that attestation, which the gate's I-prov check reads
    steps:
      - name: Commit refreshed data on records-data
        run: true
      - name: Attest the records-data listing
        uses: actions/attest-build-provenance@v2
  deploy:
    needs: [gate, update, push]
    permissions:
      pages: write
      id-token: write
    steps:
      - name: Deploy to GitHub Pages
        run: true
  gate-failed:
    needs: gate
    permissions:
      issues: write
    steps:
      - name: Open or comment on the issue
        run: true
"""
# The job and permission lines of national-update.yml as merged in PR #69 (ADR 0013 decision 6), with comment traps
# (a header naming contents: write and a trailing comment on a permission line). Allowed on main beside
# daily-update.yml since 2026-11-20 (docs/architecture/main-protect-invariant.md, note 2026-11-20).
NAT_PATH = f"repos/{REPO}/contents/.github/workflows/national-update.yml?ref=main"
NAT_STEP = "Check the national-data head"
NAT_WF = """# push job   : ... The only job here with contents: write, id-token: write or
#              attestations: write.
name: National update

on:
  schedule:
    - cron: "23 4 * * *"
  workflow_dispatch:

concurrency:
  group: national-collect
  cancel-in-progress: false

permissions: {}

jobs:
  gate:
    runs-on: ubuntu-24.04
    permissions:
      contents: read         # read national-data (not contents: write)
      attestations: read     # read the attestations of national-data's listing
    steps:
      - name: Check out this run's commit
        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
      - name: Check the national-data head
        id: check
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          echo "contents: write"
  collect:
    needs: gate
    if: needs.gate.outputs.ready == 'yes' && github.ref == 'refs/heads/main'
    permissions:
      contents: read         # check out the code
    steps:
      - name: Collect
        run: true
  push:
    needs: [gate, collect]
    permissions:
      contents: write        # push national-data: the only job in this workflow that can write to the repository
      id-token: write        # sign the listing's attestation
      attestations: write    # store that attestation
    steps:
      - name: Attest the national-data listing
        uses: actions/attest-build-provenance@96278af6caaf10aea03fd8d33a09a777ca52d62f # v3.2.0
      - name: Push the data commit to national-data
        run: git push origin "HEAD:refs/heads/national-data"
  report:
    needs: [gate, collect, push]
    permissions:
      issues: write          # open or comment on one issue
    steps:
      - name: Open or update the national update issue
        run: true
"""
WORKFLOWS_OK = [["daily-update.yml", "file"], ["national-update.yml", "file"]]
# The real national-update.yml of this checkout (what main holds) and the blob sha both twins pin
# (main-protect/nat-shape-heuristic-bypass). The stub answers a file's .sha truthfully: git's blob sha of what it serves.
REAL_NAT = (ROOT / ".github" / "workflows" / "national-update.yml").read_text(encoding="utf-8")
NAT_BLOB = re.search(r"^nat_blob=([0-9a-f]{40}) ", (SCRIPTS / "protect-main.sh").read_text(encoding="utf-8"),
                     re.M).group(1)


def _blob(text):
    b = text.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()
PRE_WF = (POST_WF.replace("      - name: Check main's history and the records-data head\n",
                          "      - name: Check every change outside data/ reached main by a reviewed pull request\n")
          .replace("      attestations: write    # store that attestation, which the gate's I-prov check reads\n",
                   "      pull-requests: write   # open that pull request\n")
          .replace("      - name: Attest the records-data listing\n",
                   "      - name: Open and merge the data pull request\n"))

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is needed by the scripts and the stub")
TWIN = {"now": "sh"}


def pytest_generate_tests(metafunc):
    """Each test that runs a script (it takes tmp_path) runs once per twin: "sh", and "ps1" when PWSH is set."""
    if "tmp_path" in metafunc.fixturenames and metafunc.function.__name__ not in _NOT_A_SCRIPT_RUN:
        metafunc.parametrize("twin", pwsh_twin.TWINS, indirect=True)


@pytest.fixture(autouse=True)
def twin(request):
    TWIN["now"] = getattr(request, "param", "sh")
    yield TWIN["now"]
    TWIN["now"] = "sh"


_NOT_A_SCRIPT_RUN = {"test_a_calls_log_that_is_gone_is_an_error_never_no_calls",
                     "test_a_second_session_with_the_same_basetemp_stops"}
PS_FLAGS = {"--check": "-Check", "--pre-cutover": "-PreCutover", "--apps": "-Apps", "--main": "-Main"}


def _cmd(sh, args):
    """The command that runs <sh> with the .sh's <args>, or its .ps1 twin with the same ones."""
    if TWIN["now"] == "sh":
        return ["bash", str(sh), *args]
    return pwsh_twin.argv(sh.with_suffix(".ps1"), pwsh_twin.flags(args, PS_FLAGS))


def _as_sh(r):
    """The .ps1's output in the .sh's spelling, so one assertion holds for both: it names files scripts\\x and its
    parameters -Apps, -PreCutover and -Check. A refusal by PowerShell's own binder (stderr only) is read as stdout."""
    if TWIN["now"] == "ps1":
        out = r.stdout.replace("scripts\\", "scripts/")
        for sh_flag, ps_flag in PS_FLAGS.items():
            out = re.sub(r"(?<![\w-])%s\b" % re.escape(ps_flag), sh_flag, out)
        r.stdout = out if out.strip() else r.stderr
    return r

# ---------------------------------------------------------------------------------------------- the stub gh
_GH = r'''#!/usr/bin/env python3
import hashlib
import copy, io, json, os, subprocess, sys
a = sys.argv[1:]
statef = os.environ["GH_STATE"]
st = json.load(open(statef))
FROZEN = [False]   # a stale view (below) never saves
def save():
    if not FROZEN[0]:
        json.dump(st, open(statef, "w"))
def log(entry):
    with open(os.environ["GH_CALLS"], "a") as f:
        f.write(json.dumps(entry) + "\n")
def out(data):
    save()
    if "--jq" in a:
        r = subprocess.run(["jq", "-r", a[a.index("--jq") + 1]], input=json.dumps(data), capture_output=True, text=True)
        sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); sys.exit(r.returncode)
    print(json.dumps(data)); sys.exit(0)
def refuse():
    save(); sys.stderr.write("gh: Resource not accessible by integration (HTTP 403)\n"); sys.exit(1)
R = "repos/gn0sh/clarksville-records"
if a[:2] == ["auth", "status"]:
    sys.exit(0)
assert a[0] == "api", a
args = [x for x in a[1:] if x not in ("--paginate", "--silent")]
method = "GET"
if args[0] == "-X":
    method, args = args[1], args[2:]
path = args[0]
key = method + " " + path
n = st.setdefault("seen", {}).get(key, 0) + 1
st["seen"][key] = n
log({"method": method, "path": path, "argv": a})
f = st.get("fail", {}).get(key)
if f == "all" or (isinstance(f, list) and n in f):
    refuse()
def ruleset_view(rs):
    return {**rs, "source_type": "Repository", "source": "gn0sh/clarksville-records", "node_id": "RRS_x",
            "_links": {"self": {"href": "https://api.github.com/x"}}, "current_user_can_bypass": "pull_requests_only"}
# read-after-write (docs/architecture/read-after-write-invariant.md): lag_each {read path: N} makes the first write
# that arms that path take a snapshot of the state before it; the next N reads that would show something else show
# the snapshot instead (a read the write did not change is not counted). serve {path: {"body": B, "n": N}}: B for N
# reads (-1: every read).
def arms(path):
    if path == R + "/rulesets":
        return [R + "/rulesets?per_page=100", R + "/rules/branches/main"]
    if path.startswith(R + "/rulesets/"):
        return [path, R + "/rules/branches/main"]
    return [path]
def render(state, frozen):
    global st
    keep, st = st, state
    FROZEN[0] = frozen
    o, e = io.StringIO(), io.StringIO()
    so, se = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = o, e
    code = 0
    try:
        handle()
    except SystemExit as x:
        code = x.code if isinstance(x.code, int) else (0 if x.code is None else 1)
    finally:
        sys.stdout, sys.stderr = so, se
        st = keep
        FROZEN[0] = False
    return o.getvalue(), e.getvalue(), code
def handle():
    if path == R + "/git/ref/heads/main":
        out({"object": {"sha": st["main"]}})
    if path.startswith(R + "/contents/.github/workflows/daily-update.yml?ref="):   # ref=main, or --main's sha
        assert "Accept: application/vnd.github.raw" in a, a
        save(); sys.stdout.write(st["wf"]); sys.exit(0)
    if path.startswith(R + "/contents/.github/workflows/national-update.yml?ref="):   # ref=main, or --main's sha
        if "Accept: application/vnd.github.raw" not in a:      # --jq .sha: the blob sha (pin)
            out({"name": "national-update.yml", "type": "file", "sha": st.get("wfn_sha") or hashlib.sha1(
                b"blob %d\0" % len(st["wfn"].encode()) + st["wfn"].encode()).hexdigest()})
        save(); sys.stdout.write(st["wfn"]); sys.exit(0)
    if path == R + "/rulesets?per_page=100":
        if method == "POST":
            body = json.load(open(args[args.index("--input") + 1]))
            log({"post_body": body})
            st["next_id"] = st.get("next_id", 100) + 1
            st["rulesets"].append({"id": st["next_id"], **body}); save(); sys.exit(0)
        out([{"id": x["id"], "name": x["name"], "target": x["target"], "enforcement": x["enforcement"]}
             for x in st["rulesets"]])
    if path == R + "/rulesets":
        assert method == "POST", a
        body = json.load(open(args[args.index("--input") + 1]))
        log({"post_body": body})
        st["next_id"] = st.get("next_id", 100) + 1
        st["rulesets"].append({"id": st["next_id"], **body})
        out(ruleset_view(st["rulesets"][-1]))           # GitHub answers a POST with the new ruleset
    if path.startswith(R + "/rulesets/"):
        rid = int(path.rsplit("/", 1)[1])
        rs = [x for x in st["rulesets"] if x["id"] == rid]
        assert len(rs) == 1, (rid, st["rulesets"])
        if method == "PUT":
            body = json.load(open(args[args.index("--input") + 1]))
            log({"put_body": body, "id": rid})
            rs[0].clear(); rs[0].update({"id": rid, **body})
            save(); sys.exit(0)
        view = json.loads(json.dumps(ruleset_view(rs[0])))
        if st.get("mutate") == view["name"]:                 # GitHub stored something else than the body sent
            view["rules"][-1].setdefault("parameters", {})["required_approving_review_count"] = 1
        out(view)
    if path == R + "/rules/branches/main":
        rules = [dict(r, ruleset_id=x["id"], ruleset_source="gn0sh/clarksville-records", ruleset_source_type="Repository")
                 for x in st["rulesets"] if x["target"] == "branch" and x["enforcement"] == "active"
                 and "~DEFAULT_BRANCH" in x["conditions"]["ref_name"]["include"] for r in x["rules"]]
        out(rules + st.get("extra_main_rules", []))
    if path == R + "/actions/permissions/workflow":
        if method == "PUT":
            log({"r2_put": a})
            if not st.get("r2_sticks"):
                st["r2"] = "can_approve_pull_request_reviews=true" in a
            save(); sys.exit(0)
        out({"default_workflow_permissions": "read", "can_approve_pull_request_reviews": st["r2"]})
    if path == R:
        out({"full_name": "gn0sh/clarksville-records", "allow_auto_merge": st["auto"]})
    if path == R + "/collaborators?affiliation=all&per_page=100":
        out(st["collabs"])
    if path == R + "/invitations?per_page=100":
        out(st["invites"])
    if path.startswith("user/installations"):              # as GitHub answers gh's OAuth token (2026-11-18)
        save(); sys.stderr.write("gh: You must authenticate with an access token authorized to a GitHub App in order "
                                 "to list installations (HTTP 403)\n"); sys.exit(1)
    if path == R + "/keys?per_page=100":
        out(st["keys"])
    if path == R + "/pages":                                 # S1-6
        out({"url": "https://api.github.com/x", "build_type": st.get("pages", "workflow"), "cname": "x"})
    if path.startswith(R + "/contents/.github/workflows?ref="):  # S1-7
        out([{"name": n, "path": ".github/workflows/" + n, "type": k}
             for n, k in st.get("workflows", [["daily-update.yml", "file"], ["national-update.yml", "file"]])])
    if path.startswith(R + "/environments/"):
        rest = path[len(R + "/environments/"):]
        if rest.endswith("/deployment-branch-policies?per_page=100"):
            env = rest.split("/")[0]
            pols = st["env_policies"][env]
            out({"total_count": len(pols), "branch_policies": pols})
        out({"name": rest, "deployment_branch_policy": st["envs"][rest]})
    sys.stderr.write("stub: unexpected call %r\n" % a); sys.exit(9)
srv = st.get("serve", {}).get(path) if method == "GET" else None
if srv and srv["n"] != 0:
    srv["n"] -= 1
    out(srv["body"])
if method == "GET" and st.get("lag", {}).get(path):
    real = render(st, False)
    stale = render(st["snap"][path], True)
    res = real
    if stale != real:
        st["lag"][path] -= 1; save(); res = stale
    sys.stdout.write(res[0]); sys.stderr.write(res[1]); sys.exit(res[2])
if method != "GET":
    for rp in arms(path):
        n = st.get("lag_each", {}).get(rp)
        if n and rp not in st.get("snap", {}):
            st.setdefault("snap", {})[rp] = copy.deepcopy({k: v for k, v in st.items() if k not in ("lag", "snap", "seen")})
            st.setdefault("lag", {})[rp] = n
handle()
'''


# the stub sleep logs each call (read-after-write tests count the 3 s waits); it never waits
_SLEEP = """#!/bin/sh
[ -z "${GH_CALLS:-}" ] || printf '{"method": "SLEEP", "path": "sleep", "argv": ["%s"]}\\n' "$1" >> "$GH_CALLS"
exit 0
"""


def _perm(level):
    order = ["pull", "triage", "push", "maintain", "admin"]
    return {p: order.index(p) <= order.index(level) for p in order}


def _pm_state(**over):
    st = {"main": "1" * 40, "rulesets": [], "r2": True, "auto": False, "wf": POST_WF, "wfn": REAL_NAT,
          "collabs": [{"login": "gn0sh", "permissions": _perm("admin"), "role_name": "admin"}],
          "invites": [], "keys": [],
          "envs": {e: {"protected_branches": False, "custom_branch_policies": True}
                   for e in ("github-pages", "morning-note")},
          "env_policies": {e: [{"id": 1, "name": "main", "type": "branch"}] for e in ("github-pages", "morning-note")}}
    st.update(over)
    return st


def _env(tmp_path, st, stub=_GH):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for name, text in (("gh", stub), ("sleep", _SLEEP)):
        (bindir / name).write_text(text)
        (bindir / name).chmod(0o755)
    (tmp_path / "state.json").write_text(json.dumps(st))
    (tmp_path / "calls").write_text("")     # made here, so a calls file gone later is an error, never "no calls"
    env = {k: v for k, v in os.environ.items() if k not in CLOUD + ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN")}
    env.update({"PATH": f"{bindir}:{os.environ['PATH']}", "GH_CALLS": str(tmp_path / "calls"),
                "GH_STATE": str(tmp_path / "state.json"), "HOME": str(tmp_path)})
    if TWIN["now"] == "ps1":
        pwsh_twin.install(tmp_path, bindir)
        env = pwsh_twin.env(env)
    return env


def _calls(tmp_path):
    """The stub's call log. _env makes the file, so a missing one means something else removed it (another session
    sharing this --basetemp, main-protect/test-flake): an error, never read as "no calls"."""
    p = tmp_path / "calls"
    assert p.is_file(), f"{p} is gone: another pytest session shares this --basetemp (conftest.py basetemp lock)"
    return [json.loads(ln) for ln in p.read_text().splitlines()]


def _pm(tmp_path, st=None, args=("--apps", "claude"), **env_over):
    env = {**_env(tmp_path, st or _pm_state()), **env_over}
    r = subprocess.run(_cmd(PM_SH, args), env=env, capture_output=True, text=True, timeout=120)
    return _as_sh(r), _calls(tmp_path)


def _writes(made):
    return [c for c in made if c.get("method") in ("POST", "PUT", "PATCH", "DELETE")]


def _ok(r):
    assert r.returncode == 0, r.stdout + r.stderr
    last = r.stdout.strip().splitlines()[-1]
    assert last.startswith("OK: main is protected") and "NOT OK" not in r.stdout, r.stdout


def _not_ok(r, says):
    assert r.returncode == 1, r.stdout + r.stderr
    last = r.stdout.strip().splitlines()[-1]
    assert last.startswith("NOT OK: ") and "OK: main is protected" not in r.stdout, r.stdout
    assert says in r.stdout, r.stdout


def _live(name, rid):
    return {"id": rid, **json.loads(json.dumps(BODY[name]))}


# ---------------------------------------------------------------------------------------------- protect-main: OK paths
def test_protect_main_creates_r1pp_rd_rt_and_turns_r2_off(tmp_path):
    r, made = _pm(tmp_path)
    _ok(r)
    posts = [c["post_body"] for c in made if "post_body" in c]
    assert posts == [BODY["R1''"], BODY["R-D"], BODY["R-T"]]          # each from its file, in this order
    assert not any("put_body" in c for c in made)
    w = _writes(made)
    assert [c["path"] for c in w] == [f"{R}/rulesets"] * 3 + [f"{R}/actions/permissions/workflow"]
    r2 = [c["r2_put"] for c in made if "r2_put" in c]
    assert len(r2) == 1 and "can_approve_pull_request_reviews=false" in r2[0]
    # main is read before any write, and printed first
    first_write = made.index(w[0])
    assert any(c.get("path") == f"{R}/git/ref/heads/main" for c in made[:first_write])
    assert r.stdout.splitlines()[0] == "Main before the rulesets: " + "1" * 40
    assert "R2 was on: turned off" in r.stdout
    for label, f in FILES.items():
        assert re.search(rf"^{re.escape(label)}: ruleset \d+ matches scripts/{re.escape(f)}$", r.stdout, re.M), label


def test_protect_main_updates_existing_rulesets_and_never_makes_a_second(tmp_path):
    """The live R1' (ruleset 27502319) is updated in place to R1''; R-D and R-T likewise when present."""
    st = _pm_state(rulesets=[{"id": 27502319, **json.loads(json.dumps(R1P))}, _live("R-D", 5), _live("R-T", 6)],
                   r2=False)
    r, made = _pm(tmp_path, st)
    _ok(r)
    puts = [(c["id"], c["put_body"]) for c in made if "put_body" in c]
    assert puts == [(27502319, BODY["R1''"]), (5, BODY["R-D"]), (6, BODY["R-T"])]
    assert not any("post_body" in c for c in made) and not any("r2_put" in c for c in made)
    assert "R2 already off" in r.stdout
    assert "Required approvals" not in r.stdout and "Ruleset 27502319" not in r.stdout   # no R1' checks left


def test_protect_main_ruleset_files_are_r1pp_rd_and_rt():
    r1pp = BODY["R1''"]
    pr = [x for x in r1pp["rules"] if x["type"] == "pull_request"][0]["parameters"]
    assert (pr["required_approving_review_count"], pr["require_last_push_approval"], pr["require_code_owner_review"],
            pr["dismiss_stale_reviews_on_push"], pr["allowed_merge_methods"]) == (MAX_APPROVALS, True, False, True, ["squash"])
    assert r1pp["bypass_actors"] == [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]
    assert r1pp["name"] == R1P["name"] == "main: pull request required"
    rd, rt = BODY["R-D"], BODY["R-T"]
    assert rd["target"] == "branch" and rd["conditions"]["ref_name"]["include"] == ["refs/heads/records-data"]
    assert sorted(x["type"] for x in rd["rules"]) == ["deletion", "non_fast_forward"] and rd["bypass_actors"] == []
    assert rt["target"] == "tag" and rt["conditions"]["ref_name"]["include"] == ["refs/tags/main"]
    assert sorted(x["type"] for x in rt["rules"]) == ["creation", "deletion", "update"] and rt["bypass_actors"] == []
    for body in BODY.values():
        assert body["enforcement"] == "active"
    for f in list(FILES.values()) + ["main-ruleset-r1p.json"]:     # BOM-less ASCII for PowerShell 5.1's reader
        raw = (SCRIPTS / f).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf") and raw.decode("ascii")
    assert not (SCRIPTS / "main-ruleset-r1pp.json").exists()        # one copy of R1''
    # R1' is kept for the D3 rollback: R1'' with only ADR 0011 decision 5's three values reverted
    p1 = [x for x in R1P["rules"] if x["type"] == "pull_request"][0]["parameters"]
    assert {**pr, "required_approving_review_count": 0, "require_last_push_approval": False,
            "require_code_owner_review": True} == p1


@pytest.mark.parametrize("st_over", [
    {"keys": [{"id": 3, "title": "ro", "read_only": True}]},
    {"collabs": [{"login": "gn0sh", "permissions": _perm("admin")}, {"login": "friend", "permissions": _perm("triage")}]},
    {"invites": [{"id": 4, "invitee": {"login": "friend"}, "permissions": "read"}]},
], ids=["read-only-key", "triage-collaborator", "read-invite"])
def test_protect_main_ok_with_non_writers(tmp_path, st_over):
    r, _ = _pm(tmp_path, _pm_state(**st_over))
    _ok(r)


# ---------------------------------------------------------------------------------------------- protect-main: each NOT OK
@pytest.mark.parametrize("st_over,says", [
    ({"r2_sticks": True}, "R2 is on"),
    ({"auto": True}, "auto-merge must be off"),
    ({"collabs": [{"login": "gn0sh", "permissions": _perm("admin")}, {"login": "friend", "permissions": _perm("push")}]},
     "the collaborators with write or more must be exactly gn0sh"),
    ({"collabs": [{"login": "gn0sh", "permissions": _perm("admin")}, {"login": "m", "permissions": _perm("maintain")}]},
     "the collaborators with write or more must be exactly gn0sh"),
    ({"collabs": []}, "the collaborators with write or more must be exactly gn0sh"),
    ({"invites": [{"id": 4, "invitee": {"login": "friend"}, "permissions": "write"}]},
     "a pending invitation with write or more: friend:write"),
    ({"keys": [{"id": 3, "title": "deploy", "read_only": False}]}, "a deploy key with write: 3:deploy"),
    ({"env_policies": {"github-pages": [{"id": 1, "name": "main", "type": "tag"}],
                       "morning-note": [{"id": 2, "name": "main", "type": "branch"}]}},
     "environment github-pages must allow exactly main, of type branch"),
    ({"env_policies": {"github-pages": [{"id": 1, "name": "main", "type": "branch"}],
                       "morning-note": [{"id": 2, "name": "main", "type": "branch"},
                                        {"id": 3, "name": "dev", "type": "branch"}]}},
     "environment morning-note must allow exactly main, of type branch"),
    ({"envs": {"github-pages": {"protected_branches": True, "custom_branch_policies": False},
               "morning-note": {"protected_branches": False, "custom_branch_policies": True}}},
     "environment github-pages must use custom deployment policies only"),
    ({"envs": {"github-pages": {"protected_branches": False, "custom_branch_policies": True}, "morning-note": None}},
     "environment morning-note must use custom deployment policies only"),
    ({"mutate": "main: pull request required"}, "R1'': ruleset 101 does not match scripts/main-ruleset.json"),
    ({"mutate": "records-data: no deletion or force push"},
     "R-D: ruleset 102 does not match scripts/records-data-ruleset.json"),
    ({"rulesets": [_live("R-T", 6), {**_live("R-T", 7)}]}, "R-T: 2 rulesets named 'tag main: blocked', expected exactly 1"),
    ({"extra_main_rules": [{"type": "pull_request", "parameters": {"required_approving_review_count": 0,
                                                                   "require_code_owner_review": True}}]},
     "main needs exactly one pull_request rule, with 10 approvals (the ruleset API maximum) and no code-owner review"),
    ({"extra_main_rules": [{"type": "required_signatures"}]},
     "main's rules must be deletion,non_fast_forward,pull_request"),
], ids=["r2-stays-on", "auto-merge", "write-collaborator", "maintain-collaborator", "no-collaborators",
        "write-invitation", "write-deploy-key", "tag-env-policy",
        "extra-env-policy", "protected-branches-env", "all-branches-env", "r1pp-differs", "rd-differs",
        "duplicate-rt", "extra-code-owner-rule", "extra-main-rule"])
def test_protect_main_not_ok(tmp_path, st_over, says):
    r, _ = _pm(tmp_path, _pm_state(**st_over))
    _not_ok(r, says)


_READS = [
    f"GET {R}/rulesets/101", f"GET {R}/rulesets/102", f"GET {R}/rulesets/103", f"GET {R}/rules/branches/main",
    f"GET {R}", f"GET {R}/collaborators?affiliation=all&per_page=100", f"GET {R}/invitations?per_page=100",
    f"GET {R}/keys?per_page=100", f"GET {R}/environments/github-pages", f"GET {R}/environments/morning-note",
    f"GET {R}/environments/github-pages/deployment-branch-policies?per_page=100",
    f"GET {R}/environments/morning-note/deployment-branch-policies?per_page=100",
    f"GET {WF_PATH}", f"GET {NAT_PATH}",
]


def test_a_calls_log_that_is_gone_is_an_error_never_no_calls(tmp_path):
    """main-protect/test-flake: the 403 test once read 0 writes because a second pytest session with the same
    --basetemp emptied this test's folder after the script ran. _env makes the log, so _calls refuses a missing one."""
    _env(tmp_path, _pm_state())
    assert _calls(tmp_path) == []
    (tmp_path / "calls").unlink()
    with pytest.raises(AssertionError, match="another pytest session shares this --basetemp"):
        _calls(tmp_path)


def test_a_second_session_with_the_same_basetemp_stops(tmp_path):
    """The root cause of main-protect/test-flake, closed in conftest.py: while one session holds --basetemp X, a
    second session given X stops with a usage error before it empties X (exit 4), and X's files stay."""
    fcntl = pytest.importorskip("fcntl")
    bt = tmp_path / "bt"
    (bt / "keep").mkdir(parents=True)
    lock = bt.with_name("bt.lock")                               # conftest.basetemp_lock_path: beside, not inside
    with open(lock, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--basetemp={bt}",
                            "tests/test_protect_main.py::test_protect_main_creates_r1pp_rd_rt_and_turns_r2_off"],
                           cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "another pytest session is using --basetemp=" in r.stdout + r.stderr and f"(lock {lock})" in r.stdout + r.stderr
    assert (bt / "keep").is_dir()                                # not emptied
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--basetemp={bt}",
                        "tests/test_protect_main.py::test_protect_main_creates_r1pp_rd_rt_and_turns_r2_off"],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr                # free again: it runs, and releases the lock
    with open(lock, "a+") as f:                                  # the file stays (no unlink race), but it is free
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize("key", _READS + ["checks: rulesets list", "checks: R2"])
def test_protect_main_a_403_on_any_check_read_is_not_ok(tmp_path, key):
    """Settings drift: the team proxy refuses actions/permissions, collaborators and environments; a refused or failed
    read is NOT OK, never skipped and never OK by default."""
    st = _pm_state()
    if key == "checks: rulesets list":                  # the writes list them three times; the 4th read is a check
        st["fail"] = {f"GET {R}/rulesets?per_page=100": list(range(4, 14))}   # read-after-write: 10 failed reads
    elif key == "checks: R2":                           # the first read decides the write; the second is the check
        st["fail"] = {f"GET {R}/actions/permissions/workflow": list(range(2, 12))}
    else:
        st["fail"] = {key: "all"}
    r, made = _pm(tmp_path, st)
    _not_ok(r, "could not read")
    assert "(a refused or failed read counts as NOT OK)" in r.stdout
    assert len([c for c in made if "post_body" in c]) == 3          # the writes all happened before the checks


_R2_NAME = "'Allow GitHub Actions to create and approve pull requests' (R2)"


@pytest.mark.parametrize("key,says", [
    (f"GET {R}/git/ref/heads/main", "Could not read main's commit. Nothing was changed."),
    (f"GET {R}/rulesets?per_page=100", "Could not list the rulesets"),
    (f"POST {R}/rulesets", "Creating R1'' failed"),
    (f"GET {R}/actions/permissions/workflow", "Could not read " + _R2_NAME),
    (f"PUT {R}/actions/permissions/workflow", "Turning off " + _R2_NAME + " failed"),
], ids=["main", "list", "post", "r2-read", "r2-put"])
def test_protect_main_a_failed_write_step_stops_not_ok(tmp_path, key, says):
    st = _pm_state(fail={key: "all"})
    r, made = _pm(tmp_path, st)
    assert r.returncode == 1 and says in r.stdout, r.stdout
    assert r.stdout.strip().splitlines()[-1].startswith("NOT OK") or "Nothing was changed" in r.stdout
    assert "OK: main is protected" not in r.stdout
    assert not any(c.get("path", "").startswith(f"{R}/collaborators") for c in made)   # stopped before the checks
    if key.endswith("heads/main") or key.endswith("rulesets?per_page=100"):
        assert not _writes(made)


def test_protect_main_a_failed_ruleset_put_stops(tmp_path):
    st = _pm_state(rulesets=[_live("R1''", 27502319)], fail={f"PUT {R}/rulesets/27502319": "all"})
    r, made = _pm(tmp_path, st)
    assert r.returncode == 1 and "Updating R1'' (ruleset 27502319) failed" in r.stdout
    assert not any("post_body" in c for c in made) and not any("r2_put" in c for c in made)


def _pm_args(tmp_path, args, st):
    r = subprocess.run(_cmd(PM_SH, args), env=_env(tmp_path, st), capture_output=True, text=True, timeout=120)
    return _as_sh(r), _calls(tmp_path)


def test_protect_main_check_only_writes_nothing(tmp_path):
    """--check (settings-drift re-check, or a dry look before the cutover): the same checks, no write at all."""
    done = _pm_state(rulesets=[_live("R1''", 27502319), _live("R-D", 5), _live("R-T", 6)], r2=False)
    r, made = _pm_args(tmp_path, ["--check", "--apps", "none"], done)
    _ok(r)
    assert not _writes(made) and r.stdout.splitlines()[0].startswith("CHECK ONLY: nothing is written")
    sub = tmp_path / "before"
    sub.mkdir()
    r, made = _pm_args(sub, ["--check"], _pm_state(rulesets=[{"id": 27502319, **json.loads(json.dumps(R1P))}]))
    _not_ok(r, "R1'': ruleset 27502319 does not match scripts/main-ruleset.json")   # today's R1', R2 on
    assert "R-D: 0 rulesets named" in r.stdout and "R2 is on" in r.stdout and not _writes(made)


# ---------------------------------------------------------------------------------------------- read-after-write
# docs/architecture/read-after-write-invariant.md (loop rule data-off-main/read-after-write, hit 2): a read that
# confirms this run's own write waits up to 10 reads, 3 s apart, for exactly what was written; --check reads once.
def _sleeps(made, seconds="3"):
    return len([c for c in made if c.get("method") == "SLEEP" and c.get("argv") == [seconds]])


def _n(made, method, path):
    return len([c for c in made if c.get("method") == method and c.get("path") == path])


_RAW_ROWS = {
    # row: (lag path, state, the write, what the lag-10 run says)
    "row2-r2": (f"{R}/actions/permissions/workflow", {}, ("PUT", f"{R}/actions/permissions/workflow"),
                "R2 reads 'true', not 'false', after 10 reads."),
    "row4-post-ids": (f"{R}/rulesets?per_page=100", {}, ("POST", f"{R}/rulesets"),
                      "R1'': the rulesets named 'main: pull request required' reads '', not '101', after 10 reads."),
    "row4-put-body": (f"{R}/rulesets/27502319",
                      {"rulesets": [{"id": 27502319, **json.loads(json.dumps(R1P))}, _live("R-D", 5), _live("R-T", 6)]},
                      ("PUT", f"{R}/rulesets/27502319"), "R1'': ruleset 27502319 does not match scripts/main-ruleset.json"),
    "row5-rules-on-main": (f"{R}/rules/branches/main", {}, ("POST", f"{R}/rulesets"),
                           "Rules on main reads '', not 'deletion,non_fast_forward,pull_request', after 10 reads."),
}


@pytest.mark.parametrize("lag", [9, 10])
@pytest.mark.parametrize("row", sorted(_RAW_ROWS))
def test_raw_a_lagging_read_after_a_write_waits_then_fails_closed(tmp_path, row, lag):
    path, over, (wm, wp), says = _RAW_ROWS[row]
    st = _pm_state(**json.loads(json.dumps(over)))
    st["lag_each"] = {path: lag}
    r, made = _pm(tmp_path, st)
    writes = _n(made, wm, wp)
    assert writes == (3 if wp == f"{R}/rulesets" else 1), writes        # each write is sent once (3 POSTs: 3 rulesets)
    assert _sleeps(made) == 9, _sleeps(made)                              # lag 9: 9 waits; lag 10: no wait after the last
    if lag == 9:
        _ok(r)
    else:
        _not_ok(r, says)
        assert "after 10 reads." in r.stdout


def test_raw_a_failed_read_only_delays_and_a_third_value_never_passes(tmp_path):
    st = _pm_state(fail={f"GET {R}/actions/permissions/workflow": [2]})      # the check read of R2, once
    r, made = _pm(tmp_path, st)
    _ok(r)
    assert _sleeps(made) == 1
    sub = tmp_path / "third"
    sub.mkdir()
    st = _pm_state(serve={f"{R}/rules/branches/main": {"body": [{"type": "deletion"}], "n": -1}})
    r, made = _pm(sub, st)
    _not_ok(r, "Rules on main reads 'deletion', not 'deletion,non_fast_forward,pull_request', after 10 reads.")
    assert "Pull request rules on main reads '', not '10\tfalse', after 10 reads." in r.stdout
    assert _sleeps(made) == 18 and _n(made, "POST", f"{R}/rulesets") == 3


def test_raw_check_reads_once(tmp_path):
    """A plain --check wrote nothing, so nothing waits: real drift is reported at once, never after 27 s."""
    done = _pm_state(rulesets=[_live("R1''", 27502319), _live("R-D", 5), _live("R-T", 6)], r2=False,
                     fail={f"GET {R}/rules/branches/main": [1]})
    r, made = _pm_args(tmp_path, ["--check", "--apps", "none"], done)
    _not_ok(r, "could not read the rules on main")
    assert _sleeps(made) == 0 and not _writes(made)


def test_raw_r2_already_off_is_read_once(tmp_path):
    """R2 is read until false only if this run turned it off; already off, the check is one read."""
    st = _pm_state(r2=False, fail={f"GET {R}/actions/permissions/workflow": [2]})
    r, made = _pm(tmp_path, st)
    _not_ok(r, "could not read R2")
    assert _sleeps(made) == 0 and _n(made, "PUT", f"{R}/actions/permissions/workflow") == 0


_PIN = "1" * 40


@pytest.mark.parametrize("lag", [9, 10])
def test_raw_row10_main_pins_the_ref_and_reads_the_workflow_at_that_sha(tmp_path, lag):
    """Cutover step 5: --check --main <merge sha> reads main's ref until it is the merge, then main's workflow files at
    that sha (never at a lagging ?ref=main)."""
    done = _pm_state(rulesets=[_live("R1''", 27502319), _live("R-D", 5), _live("R-T", 6)], r2=False,
                     serve={f"{R}/git/ref/heads/main": {"body": {"object": {"sha": "2" * 40}}, "n": lag}})
    r, made = _pm_args(tmp_path, ["--check", "--apps", "none", "--main", _PIN], done)
    assert _sleeps(made) == 9 and not _writes(made)
    contents = [c["path"] for c in made if "/contents/" in c.get("path", "")]
    assert contents == [f"{R}/contents/.github/workflows?ref={_PIN}",
                        f"{R}/contents/.github/workflows/daily-update.yml?ref={_PIN}",
                        f"{R}/contents/.github/workflows/national-update.yml?ref={_PIN}",
                        f"{R}/contents/.github/workflows/national-update.yml?ref={_PIN}"], contents
    if lag == 9:
        _ok(r)
        assert f"Main: {_PIN} (--main); its workflow files are read at that commit." in r.stdout
    else:
        _not_ok(r, f"main is at '{'2' * 40}', not {_PIN} (--main)")
        assert f"main reads '{'2' * 40}', not '{_PIN}', after 10 reads." in r.stdout


@pytest.mark.parametrize("fails", [9, 10])
def test_raw_row10_a_failed_read_at_the_pinned_sha_is_not_yet(tmp_path, fails):
    done = _pm_state(rulesets=[_live("R1''", 27502319), _live("R-D", 5), _live("R-T", 6)], r2=False,
                     fail={f"GET {R}/contents/.github/workflows?ref={_PIN}": list(range(1, fails + 1))})
    r, made = _pm_args(tmp_path, ["--check", "--apps", "none", "--main", _PIN], done)
    assert _sleeps(made) == 9
    if fails == 9:
        _ok(r)
    else:
        _not_ok(r, "could not read main's .github/workflows/ folder")
    # without --main a failed read is NOT OK at once (one read)
    sub = tmp_path / "plain"
    sub.mkdir()
    done["fail"] = {f"GET {R}/contents/.github/workflows?ref=main": [1]}
    r, made = _pm_args(sub, ["--check", "--apps", "none"], done)
    _not_ok(r, "could not read main's .github/workflows/ folder")
    assert _sleeps(made) == 0


@pytest.mark.parametrize("value", ["main", "1" * 39, "G" * 40, ""])
def test_raw_main_takes_a_full_sha_only(tmp_path, value):
    r, made = _pm_args(tmp_path, ["--check", "--apps", "none", "--main", value], _pm_state())
    assert r.returncode == 1 and "takes main's full 40-hex commit sha" in r.stdout, r.stdout + r.stderr
    assert made == []


def test_protect_main_refuses_an_unknown_argument(tmp_path):
    for args in (["--force"], ["--apps"], ["--check", "x"]):
        r, made = _pm_args(tmp_path, args, _pm_state())
        usage = "Usage: bash scripts/protect-main.sh [--check] [--pre-cutover] [--apps <App names>|none]"
        if TWIN["now"] == "ps1":     # data-off-main/ps-unknown-args: named binding only, so PowerShell itself refuses
            usage = "parameter"
        assert r.returncode == 1 and usage in r.stdout, r.stdout
        assert made == []


@pytest.mark.parametrize("var", CLOUD)
def test_protect_main_refuses_in_a_cloud_session_or_ci(tmp_path, var):
    """All ruleset and settings writes are Brian's, from his PC (U3-0 = no): never from the cloud or a workflow."""
    r, made = _pm(tmp_path, **{var: "true"})
    assert r.returncode == 1 and f"REFUSED: {var} is set" in r.stdout and "Nothing was changed" in r.stdout
    assert made == []


# ---------------------------------------------------------------------------------------------- protect-main: .ps1 twin
def _jq_filters(text):
    return re.findall(r"--jq '([^']*)'", text)


def test_protect_main_ps1_has_the_same_filters_writes_and_lines():
    sh, ps1 = PM_SH.read_text(encoding="utf-8"), PM_PS1.read_text(encoding="utf-8")
    filters = _jq_filters(sh)
    assert len(filters) >= 12
    for f in filters:
        assert f"'{f}'" in ps1, f
    for path in ('"repos/$repo/git/ref/heads/main"', '"repos/$repo/rulesets?per_page=100"', '"repos/$repo/rulesets"',
                 '"repos/$repo/actions/permissions/workflow"', '"repos/$repo/rules/branches/main"', '"repos/$repo"',
                 '"repos/$repo/collaborators?affiliation=all&per_page=100"', '"repos/$repo/invitations?per_page=100"',
                 '"repos/$repo/keys?per_page=100"',
                 "-F can_approve_pull_request_reviews=false"):
        assert path in sh and path in ps1, path
    assert '"repos/$repo/environments/$env"' in sh and '"repos/$repo/environments/$envName"' in ps1
    assert ('"repos/$repo/environments/$env/deployment-branch-policies?per_page=100"' in sh
            and '"repos/$repo/environments/$envName/deployment-branch-policies?per_page=100"' in ps1)
    assert "can_approve_pull_request_reviews=true" not in sh + ps1
    for f in FILES.values():
        assert f in sh and f in ps1
    lines = ["REFUSED: $v is set. protect-main runs only from Brian's PC (ruleset and settings writes are his). "
             "Nothing was changed.",
             "Main before the rulesets: ", "no ruleset yet, creating it from scripts", "exists, updating it from scripts",
             "R2 already off", "R2 was on: turned off", "NOT OK: stopped before the checks.",
             "(a refused or failed read counts as NOT OK)", "Rules on main: ",
             "main's rules must be deletion,non_fast_forward,pull_request",
             "main needs exactly one pull_request rule, with 10 approvals (the ruleset API maximum) and no code-owner review",
             "R2 is on: with R2 on, gn0sh plus the bot can approve a pull request (ADR 0011 decision 6)",
             "auto-merge must be off: Settings > General > Pull Requests > untick Allow auto-merge",
             "Collaborators with write or more: ", "the collaborators with write or more must be exactly $owner",
             "Pending invitations with write or more: ", "a pending invitation with write or more: ",
             "Installed Apps with write on this repository: not confirmed",
             "so confirm them by hand: open https://github.com/settings/installations, click Configure on each App",
             "not read by this script; none with Administration, Variables, Secrets or Environments write)",
             "alone can write this repository (",
             "remove its access to clarksville-records, or the team amends ADR 0011 first",
             "takes one value, claude or none (", "(not claude or none)",
             "none (one value; any other App must first lose its access to clarksville-records, or the team amends "
             "ADR 0011).",
             "^(none|[a-z0-9][a-z0-9-]*(,[a-z0-9][a-z0-9-]*)*)$",
             "Deploy keys with write: ", "a deploy key with write: ",
             "must use custom deployment policies only (not protected branches, not all)",
             "must allow exactly main, of type branch", "expected exactly 1", "does not match scripts",
             "OK: main is protected (R1'', R-D, R-T as written, R2 off, auto-merge off, $owner the only writer, "
             "both environments main only).",
             "problem(s) above. Run this from Brian's PC, signed in as $owner. Send this output to the team."]
    for ln in lines:
        assert ln in sh, ln
        assert ln in ps1.replace("${label}", "$label"), ln
    for var in CLOUD:
        assert var in sh and f"'{var}'" in ps1
    assert "param([switch]$Check, [switch]$PreCutover, [string]$Apps = '', [string]$Main = '')" in ps1
    assert "if ($Check) {" in ps1
    assert 'if [ "$check" = 1 ]; then' in sh
    assert "CHECK ONLY: nothing is written; the checks below read the live settings." in sh and "CHECK ONLY" in ps1
    for want in ("$'false\\ttrue'", "$'main\\tbranch'", "$'10\\tfalse'"):
        assert want in sh, want
    for want in ('"false`ttrue"', '"main`tbranch"', '"10`tfalse"'):
        assert want in ps1, want
    # PowerShell 5.1: no double quote inside a gh argument, case-sensitive comparisons, never ExecutionPolicy Bypass
    assert not re.search(r"--jq '[^']*\"", ps1) and not re.search(r"Lines \"[^\"]+\" '[^']*\"", ps1)
    assert "-ExecutionPolicy Bypass" not in ps1.replace("never -ExecutionPolicy Bypass", "")
    assert " -eq 'true'" not in ps1 and " -ne 'false'" not in ps1
    # main is read before any write, the ruleset writes come before R2, the checks after every write
    for text, read_main in ((sh, 'main_sha=$(gh api'), (ps1, '$mainSha = (gh api')):
        assert text.index(read_main) < text.index("-X POST") < text.index("-X PUT \"repos/$repo/actions")
        assert text.index("-X PUT \"repos/$repo/actions") < text.index("- checks\n")


def test_protect_main_whitelist_is_the_u3_toggle_one():
    """One comparison rule for rulesets across the scripts (the one the U3 control read back live)."""
    for ext in ("sh", "ps1"):
        pm = (SCRIPTS / f"protect-main.{ext}").read_text(encoding="utf-8")
        u3 = (SCRIPTS / f"u3-toggle.{ext}").read_text(encoding="utf-8")
        if ext == "sh":
            blocks = [re.search(r"^wl='.*?wl'$", t, re.M | re.S).group(0) for t in (pm, u3)]
            blocks += [re.search(r"^extras='.*?join\(\",\"\)'$", t, re.M | re.S).group(0) for t in (pm, u3)]
            assert blocks[0] == blocks[1] and blocks[2] == blocks[3]
        else:
            for fn in ("Wl", "Canon", "Extras"):
                pat = rf"^function {fn}\(.*?^\}}$"
                assert (re.search(pat, pm, re.M | re.S).group(0) == re.search(pat, u3, re.M | re.S).group(0)), fn


# ---------------------------------------------------------------------------------------------- merge-reviewed
SHA, MERGED = "b" * 40, "a" * 40


def _mr_state(**over):
    pr = {"number": 31, "state": "open", "base": {"ref": "main"}, "user": {"login": "gn0sh"},
          "head": {"sha": SHA, "ref": "claude/x", "repo": {"full_name": REPO}}}
    st = {"pr": pr, "kept": SHA, "suites": [{"id": 777, "after_sha": MERGED, "result": "bypass"},
                                            {"id": 776, "after_sha": "9" * 40, "result": "pass"}]}
    for k, v in over.items():
        if k == "pr":
            st["pr"].update(v)
        else:
            st[k] = v
    return st


_MR_GH = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
a = sys.argv[1:]
st = json.load(open(os.environ["GH_STATE"]))
with open(os.environ["GH_CALLS"], "a") as f:
    f.write(json.dumps(a) + "\n")
def out(data):
    r = subprocess.run(["jq", "-r", a[a.index("--jq") + 1]], input=json.dumps(data), capture_output=True, text=True)
    sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); sys.exit(r.returncode)
R = "repos/gn0sh/clarksville-records"
if a[:2] == ["auth", "status"]:
    sys.exit(0)
path = [x for x in a if x.startswith("repos/")][0]
if path in st.get("fail", []):
    sys.stderr.write("gh: HTTP 403\n"); sys.exit(1)
if path == R + "/pulls/31":
    out(st["pr"])
if path == R + "/pulls/31/reviews":
    out({"commit_id": st["kept"]})
if path == R + "/pulls/31/merge":
    out({"sha": "a" * 40, "merged": True})
if "-X" in a and "DELETE" in a:
    sys.exit(0)
if path.startswith(R + "/rulesets/rule-suites?"):
    assert "ref=main" in path, path
    out(st["suites"])
sys.stderr.write("stub: unexpected %r\n" % a); sys.exit(9)
'''


def _mr(tmp_path, args, st=None):
    env = _env(tmp_path, st or _mr_state(), stub=_MR_GH)
    r = subprocess.run(_cmd(MR_SH, args), env=env, capture_output=True, text=True, timeout=60)
    return _as_sh(r), [c for c in _calls(tmp_path) if isinstance(c, list) and c[0] == "api"]   # not the sleeps


def test_merge_reviewed_reviews_merges_deletes_then_prints_the_bypass_rule_suite(tmp_path):
    r, made = _mr(tmp_path, ["31", SHA, "docs/reviews/code-review-x.md", "docs/reviews/qa-x.md"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert made[0][:2] == ["api", f"{R}/pulls/31"]
    review, merge, delete, suites = made[1], made[2], made[3], made[4]
    assert review[:4] == ["api", "-X", "POST", f"{R}/pulls/31/reviews"]
    assert f"commit_id={SHA}" in review and "event=COMMENT" in review
    body = next(x for x in review if x.startswith("body="))
    assert SHA in body and "docs/reviews/code-review-x.md" in body and "docs/reviews/qa-x.md" in body
    assert merge[:4] == ["api", "-X", "PUT", f"{R}/pulls/31/merge"]
    assert "merge_method=squash" in merge and f"sha={SHA}" in merge
    assert delete[:4] == ["api", "-X", "DELETE", f"{R}/git/refs/heads/claude/x"]
    assert suites[1].startswith(f"{R}/rulesets/rule-suites?ref=main") and len(made) == 5
    lines = r.stdout.strip().splitlines()
    assert lines[-2] == f"Merged pull request #31 (reviewed at {SHA}) as {MERGED}."
    assert lines[-1] == f"Rule suite 777 for {MERGED}: bypass"


@pytest.mark.parametrize("pr,says", [
    ({"user": {"login": "github-actions[bot]"}}, "is authored by 'github-actions[bot]', not gn0sh"),
    ({"user": {"login": "someone"}}, "is authored by 'someone', not gn0sh"),
    ({"head": {"sha": SHA, "ref": "x", "repo": {"full_name": "someone/clarksville-records"}}},
     "head is in 'someone/clarksville-records', not gn0sh/clarksville-records"),
    ({"head": {"sha": SHA, "ref": "x", "repo": None}}, "head is in 'null', not gn0sh/clarksville-records"),
    ({"head": {"sha": "c" * 40, "ref": "claude/x", "repo": {"full_name": REPO}}}, "changed after the review"),
    ({"state": "closed"}, "is not open into main"),
    ({"base": {"ref": "dev"}}, "is not open into main"),
], ids=["bot-author", "other-author", "fork-head", "deleted-fork-head", "moved-head", "closed", "not-main"])
def test_merge_reviewed_refuses_without_reviewing_or_merging(tmp_path, pr, says):
    r, made = _mr(tmp_path, ["31", SHA, "report"], _mr_state(pr=pr))
    assert r.returncode == 1 and says in r.stdout and "Nothing done" in r.stdout, r.stdout
    assert not any("-X" in c for c in made)


@pytest.mark.parametrize("args", [["31", "b" * 7, "report"], ["31", "B" * 40, "report"], ["31", SHA], ["x", SHA, "r"]],
                         ids=["short-sha", "upper-sha", "no-report", "bad-pr"])
def test_merge_reviewed_refuses_bad_arguments(tmp_path, args):
    r, made = _mr(tmp_path, args)
    # the .ps1's report is a mandatory parameter: its binder refuses (a console would prompt for it)
    said = ("Nothing done", "Usage", "missing mandatory parameters: Reports")
    assert r.returncode == 1 and any(x in r.stdout for x in said), r.stdout
    assert not any("-X" in c for c in made)


def test_merge_reviewed_refuses_when_the_pr_cannot_be_read(tmp_path):
    r, made = _mr(tmp_path, ["31", SHA, "report"], _mr_state(fail=[f"{R}/pulls/31"]))
    assert r.returncode == 1 and "Could not read pull request #31. Nothing done." in r.stdout
    assert not any("-X" in c for c in made)


def test_merge_reviewed_does_not_merge_when_the_review_lands_elsewhere(tmp_path):
    r, made = _mr(tmp_path, ["31", SHA, "report"], _mr_state(kept="d" * 40))
    assert r.returncode == 1 and not any(c[3].endswith("/merge") for c in made if len(c) > 3)


@pytest.mark.parametrize("suites,says", [
    ([{"id": 777, "after_sha": MERGED, "result": "pass"}], "Rule suite 777 for " + MERGED + ": pass"),
    ([{"id": 776, "after_sha": "9" * 40, "result": "bypass"}], "Rule suite for " + MERGED + ": not found"),
], ids=["pass-not-bypass", "not-found"])
def test_merge_reviewed_exits_2_unless_the_rule_suite_is_bypass(tmp_path, suites, says):
    r, made = _mr(tmp_path, ["31", SHA, "report"], _mr_state(suites=suites))
    assert r.returncode == 2 and says in r.stdout and "Tell the team" in r.stdout.replace("tell the team", "Tell the team")
    assert f"as {MERGED}." in r.stdout                                  # the merge itself is reported
    reads = [c for c in made if "rule-suites?" in c[1]]
    assert len(reads) == (1 if "pass" in says else 5)                   # a bounded wait, then it says so


def test_merge_reviewed_ps1_matches_the_sh():
    sh, ps1 = MR_SH.read_text(encoding="utf-8"), MR_PS1.read_text(encoding="utf-8")
    for f in _jq_filters(sh):
        assert f"'{f}'" in ps1, f
    for s in ("event=COMMENT", "merge_method=squash", "-X DELETE", "@tsv", "changed after the review",
              "rulesets/rule-suites?ref=main&time_period=hour&per_page=100", "$ENV.MR_AFTER",
              "never bypass-merged (ADR 0011). Nothing done.", "not found (Insights > Rule suites shows it). Tell the team.",
              "The merge was not a bypass (", "Could not read pull request #"):
        assert s in sh and s in ps1, s
    assert "commit_id=$Sha" in ps1 and "sha=$Sha" in ps1
    assert "is authored by '" in sh and "is authored by '" in ps1
    assert "head is in '" in sh and "head is in '" in ps1
    assert "$f[5] -cne $owner" in ps1 and "$f[4] -cne $repo" in ps1 and "$f[2] -cne $Sha" in ps1
    assert "$i -le 5" in ps1 and "for i in 1 2 3 4 5; do" in sh
    assert not re.search(r"--jq '[^']*\"", ps1)          # no double quote inside a --jq argument (PowerShell 5.1)
    assert "-ExecutionPolicy Bypass" not in ps1


# ---------------------------------------------------------------------------------------------- protect-main: Apps
def test_protect_main_never_reads_installations_and_is_not_ok_without_the_hand_confirmation(tmp_path):
    """No token Brian holds can list installed Apps (user/installations: HTTP 403 for gh's OAuth token on his PC,
    2026-11-18). The script never tries, and without --apps the check is NOT OK with the exact steps: never a silent
    pass."""
    r, made = _pm(tmp_path, args=())
    _not_ok(r, "Installed Apps with write on this repository: not confirmed")
    assert "open https://github.com/settings/installations, click Configure on each App" in r.stdout
    assert "--apps none" in r.stdout and "Only claude may be listed" in r.stdout
    assert "1 problem(s) above" in r.stdout                   # everything else is OK
    assert not any("installations" in c.get("path", "") for c in made)
    for script in (PM_SH, PM_PS1):
        assert "gh api --paginate \"user/installations" not in script.read_text(encoding="utf-8")
        assert 'Lines "user/installations' not in script.read_text(encoding="utf-8")


@pytest.mark.parametrize("apps", ["claude", "none"])
def test_protect_main_records_the_hand_confirmed_apps(tmp_path, apps):
    """Only the Claude App (the team's branch pushes) may hold write: with R2 off it is the only approver besides
    gn0sh, so R1'''s required approvals (the ruleset maximum, 10) can't be met without gn0sh (I-person);
    whether any App can bypass is read from the bypass lists."""
    r, _ = _pm(tmp_path, args=("--apps", apps))
    _ok(r)
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("Installed Apps with write on this repository: ")]
    assert len(line) == 1 and line[0].startswith(f"Installed Apps with write on this repository: {apps} (confirmed "
                                                 "by hand by gn0sh on ")
    assert line[0].endswith("not read by this script; none with Administration, Variables, Secrets or Environments write)")


@pytest.mark.parametrize("apps,says", [
    ("claude,other-app", "an installed App other than claude alone can write this repository (claude,other-app)"),
    ("other-app", "an installed App other than claude alone can write this repository (other-app)"),
    ("Claude App", "--apps takes one value, claude or none ('Claude App' is not one)"),
    ("", "--apps takes one value, claude or none ('' is not one)"),
    ("claude other-app", "--apps takes one value, claude or none ('claude other-app' is not one)"),
    ("none,claude", "an installed App other than claude alone can write this repository (none,claude)"),
], ids=["claude-plus-another", "another", "display-name", "empty", "space-joined", "none-and-claude"])
def test_protect_main_not_ok_for_other_apps(tmp_path, apps, says):
    r, _ = _pm(tmp_path, args=("--apps", apps))
    _not_ok(r, says[:-1] if says.endswith("is not one)") else says)   # the .ps1 adds a note on PowerShell's a,b


def test_protect_main_an_app_in_a_bypass_list_is_not_ok(tmp_path):
    """The security question for Apps is bypass, and that is read: an Integration bypass actor on R1'' or R-D (here
    added by GitHub's side after the write) makes the ruleset differ from its file."""
    st = _pm_state(rulesets=[_live("R1''", 27502319), _live("R-D", 5), _live("R-T", 6)], r2=False)
    r, made = _pm(tmp_path, st, args=("--check", "--apps", "claude"))
    _ok(r)
    for rs in st["rulesets"][:2]:
        rs["bypass_actors"] = rs["bypass_actors"] + [{"actor_id": 1234, "actor_type": "Integration",
                                                      "bypass_mode": "always"}]
    sub = tmp_path / "b"
    sub.mkdir()
    r, _ = _pm(sub, st, args=("--check", "--apps", "claude"))
    _not_ok(r, "R1'': ruleset 27502319 does not match scripts/main-ruleset.json")
    assert "R-D: ruleset 5 does not match scripts/records-data-ruleset.json" in r.stdout
    assert re.search(r'"actor_type": ?"Integration"', r.stdout), r.stdout      # the .sh's jq, the .ps1's compact Canon


def test_protect_main_ps1_takes_apps_the_same_way():
    ps1 = PM_PS1.read_text(encoding="utf-8")
    assert "param([switch]$Check, [switch]$PreCutover, [string]$Apps = '', [string]$Main = '')" in ps1
    assert "$PSBoundParameters.ContainsKey('Apps')" in ps1
    assert "$allowedApp = 'claude'" in ps1 and "allowed_app=claude" in PM_SH.read_text(encoding="utf-8")
    assert "$Apps -cne 'none' -and $Apps -cne $allowedApp" in ps1 and "-Apps none" in ps1
    assert "typed at a PowerShell prompt, a,b arrives as 'a b')" in ps1
    for script in (ps1, PM_SH.read_text(encoding="utf-8")):    # the I-person reason, not "one App adds at most one"
        flat = " ".join(ln.lstrip("# ").strip() for ln in script.splitlines() if ln.lstrip().startswith("#"))
        reason = ("so R1'''s required approvals (the ruleset maximum, 10, S1-1) can't be met without gn0sh "
                  "(invariant I-person")
        assert reason in flat and "any 2 approvals" not in flat and "adds at most one" not in flat


# ---------------------------------------------------------------------------------------------- protect-main: workflow
def _wf_line(r):
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("Main's daily-update.yml: ")]
    assert len(line) == 1, r.stdout
    return line[0]


def test_protect_main_reads_mains_post_cutover_workflow(tmp_path):
    """After B2/B3: the gate step in job gate, push the only job with attestations: write and contents: write. The
    comment traps (headers naming attestations: write, a trailing comment on a permission line) count for nothing."""
    r, made = _pm(tmp_path)
    _ok(r)
    assert _wf_line(r) == ("Main's daily-update.yml: workflow 'permissions: {}'; gate step in 'gate'; attestations: "
                           "write in 'push'; contents: write in 'push'; pull-requests: write in ''; inline job "
                           "permissions in ''; data pull request step in ''; push needs '[gate, update]'")
    assert [c for c in made if c.get("path") == WF_PATH][0]["method"] == "GET"
    assert OLD_STEP not in PM_SH.read_text(encoding="utf-8").split("old_step=")[0].split("Needs:")[1]


_POST_BAD = [
    ("no-gate-step", lambda w: w.replace(GATE_STEP, "Check main's history"),
     f"must run the step '{GATE_STEP}' in job gate, and only there"),
    ("gate-step-twice", lambda w: w.replace("      - name: Check out the gate's commit\n",
                                            f"      - name: {GATE_STEP}\n"),
     f"must run the step '{GATE_STEP}' in job gate, and only there"),
    ("gate-step-commented", lambda w: w.replace(f"      - name: {GATE_STEP}\n", f"      # - name: {GATE_STEP}\n"),
     f"must run the step '{GATE_STEP}' in job gate, and only there"),
    ("attest-in-deploy", lambda w: w.replace("      pages: write\n", "      pages: write\n      attestations: write\n"),
     "only job push may hold attestations: write (only J2 stores attestations, I-prov)"),
    ("no-attest-in-push", lambda w: w.replace("      attestations: write    # store", "      attestations: read    # store"),
     "only job push may hold attestations: write"),
    ("contents-write-update", lambda w: w.replace("  update:\n    needs: gate\n    permissions:\n      contents: read\n",
                                                  "  update:\n    needs: gate\n    permissions:\n      contents: write\n"),
     "only job push may hold contents: write"),
    ("pr-write", lambda w: w.replace("      id-token: write        # sign",
                                     "      pull-requests: write\n      id-token: write        # sign"),
     "no job in main's daily-update.yml may hold pull-requests: write"),
    ("inline-write-all", lambda w: w.replace("    permissions:\n      issues: write\n", "    permissions: write-all\n"),
     "may set its permissions inline (write-all, read-all or a { } map)"),
    ("inline-map", lambda w: w.replace("    permissions:\n      issues: write\n",
                                       "    permissions: { contents: write, attestations: write }\n"),
     "may set its permissions inline"),
    ("push-not-after-gate", lambda w: w.replace("    needs: [gate, update]\n", "    needs: [update]\n"),
     "job push in main's daily-update.yml must need gate"),
    ("push-needs-gate-failed", lambda w: w.replace("    needs: [gate, update]\n", "    needs: [gate-failed, update]\n"),
     "job push in main's daily-update.yml must need gate"),
    ("top-write-all", lambda w: w.replace("permissions: {}\n", "permissions: write-all\n"),
     "must set permissions: {} at the top"),
    ("top-missing", lambda w: w.replace("permissions: {}\n", ""), "must set permissions: {} at the top"),
    ("empty", lambda w: "", "could not read main's .github/workflows/daily-update.yml"),
]


@pytest.mark.parametrize("change,says", [(c, s_) for _, c, s_ in _POST_BAD], ids=[i for i, _, _ in _POST_BAD])
def test_protect_main_not_ok_for_a_workflow_off_the_post_cutover_shape(tmp_path, change, says):
    r, _ = _pm(tmp_path, _pm_state(wf=change(POST_WF)))
    _not_ok(r, says)


def test_protect_main_crlf_workflow_reads_the_same(tmp_path):
    r, _ = _pm(tmp_path, _pm_state(wf=POST_WF.replace("\n", "\r\n")))
    _ok(r)


def test_protect_main_the_old_workflow_is_not_ok_without_pre_cutover(tmp_path):
    """The workflow on main before B2/B3 (the data pull request step) is not the post-cutover shape."""
    r, _ = _pm(tmp_path, _pm_state(wf=PRE_WF))
    _not_ok(r, "still opens data pull requests (before the cutover): use --pre-cutover only at cutover step 4, "
               "before the cutover merge")
    assert "pull-requests: write in 'push'" in _wf_line(r) and "data pull request step in 'push'" in _wf_line(r)


def test_protect_main_pre_cutover_wants_the_old_workflow(tmp_path):
    """Cutover step 4 runs before the cutover merge, so main still holds the old workflow: --pre-cutover accepts
    exactly that, and refuses once the cutover is merged (both directions fail closed)."""
    r, _ = _pm(tmp_path, _pm_state(wf=PRE_WF), args=("--pre-cutover", "--apps", "claude"))
    _ok(r)
    assert "--pre-cutover: main's daily-update.yml is checked as before the cutover" in r.stdout
    sub = tmp_path / "post"
    sub.mkdir()
    r, _ = _pm(sub, _pm_state(), args=("--pre-cutover", "--apps", "claude"))
    _not_ok(r, "--pre-cutover, but main's daily-update.yml no longer has the data pull request step (the cutover "
               "is merged): run this again without --pre-cutover")


def test_protect_main_accepts_this_checkouts_workflow(tmp_path):
    """The real .github/workflows/daily-update.yml of this checkout: the old one needs --pre-cutover, and once B2/B3
    is merged here the post-cutover one passes without it."""
    wf = (ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8")
    post = f"- name: {GATE_STEP}" in wf
    args = ("--apps", "claude") if post else ("--pre-cutover", "--apps", "claude")
    r, _ = _pm(tmp_path, _pm_state(wf=wf), args=args)
    _ok(r)


def test_protect_main_ps1_reads_the_workflow_the_same_way():
    sh, ps1 = PM_SH.read_text(encoding="utf-8"), PM_PS1.read_text(encoding="utf-8")
    call = ('gh api "repos/$repo/contents/.github/workflows/daily-update.yml?ref=$wref" '
            "-H 'Accept: application/vnd.github.raw'")
    assert call in sh and call in ps1
    assert "wref=main; tries=1" in sh and "$wref = 'main'; $tries = 1" in ps1
    assert f'gate_step="{GATE_STEP}"' in sh and f'$gateStep = "{GATE_STEP}"' in ps1
    assert f'old_step="{OLD_STEP}"' in sh and f"$oldStep = '{OLD_STEP}'" in ps1
    for want in ("^[ \\t]+attestations:[ \\t]*write$", "^[ \\t]+contents:[ \\t]*write$",
                 "^[ \\t]+pull-requests:[ \\t]*write$", "^    permissions:[ \\t]*[^ \\t]",
                 "^    permissions:[ \\t]*[{][}]$", "^[ \\t]*#", "[ \\t]+#.*$", "^  [A-Za-z0-9_-]+:$",
                 "^[ \\t]+(- )?name:", "^    needs:[ \\t]*", "^jobs:$", "^permissions:"):
        assert want in sh, want
        assert want.replace("^  [A-Za-z0-9_-]+:$", "^  ([A-Za-z0-9_-]+):$") in ps1, want
    for ln in ["Main's daily-update.yml: workflow '$top'; gate step in '$g'; attestations: write in '$aw'; "
               "contents: write in '$cw'; pull-requests: write in '$pw'; inline job permissions in '$ip'; data pull "
               "request step in '$op'; push needs '$pn'",
               "main's daily-update.yml must set permissions: {} at the top (each job then names its own)",
               "main's daily-update.yml must run the step '$", "' in job gate, and only there (the post-cutover gate, "
               "ADR 0011)",
               "in main's daily-update.yml only job push may hold attestations: write (only J2 stores attestations, "
               "I-prov)",
               "in main's daily-update.yml only job push may hold contents: write",
               "no job in main's daily-update.yml may hold pull-requests: write",
               "no job in main's daily-update.yml may set its permissions inline (write-all, read-all or a { } map)",
               "job push in main's daily-update.yml must need gate",
               "main's daily-update.yml still opens data pull requests (before the cutover): use ",
               " only at cutover step 4, before the cutover merge",
               ": main's daily-update.yml is checked as before the cutover (it still opens data pull requests); after "
               "the cutover merge, run this again without ",
               ", but main's daily-update.yml no longer has the data pull request step (the cutover is merged): run "
               "this again without ",
               "nread \"main's .github/workflows/daily-update.yml\""]:
        assert ln in sh, ln
        assert ln in ps1, ln
    assert ps1.count("-PreCutover") >= 4 and "--pre-cutover" not in ps1.split("param(")[1]
    assert "if ($PreCutover) {" in ps1 and 'if [ "$pre" = 1 ]; then' in sh
    assert ".TrimEnd(\"`r\")" in ps1 and 'sub(/\\r$/, "")' in sh


# ---------------------------------------------------------------------------------------------- S1 security review
def test_s1_1_r1pp_asks_for_the_ruleset_api_maximum_of_approvals(tmp_path):
    """main-protect/approval-margin: R1'' needs 10 approvals (the API maximum), so gn0sh plus one App can't merge
    without a bypass; a live R1'' still at 2 is NOT OK, in both twins."""
    pr = [x for x in BODY["R1''"]["rules"] if x["type"] == "pull_request"][0]["parameters"]
    assert pr["required_approving_review_count"] == MAX_APPROVALS == 10
    st = _pm_state(rulesets=[_live("R1''", 27502319), _live("R-D", 5), _live("R-T", 6)], r2=False)
    st["rulesets"][0]["rules"][-1]["parameters"]["required_approving_review_count"] = 2
    r, _ = _pm(tmp_path, st, args=("--check", "--apps", "claude"))
    _not_ok(r, "main needs exactly one pull_request rule, with 10 approvals (the ruleset API maximum)")
    assert "Pull request rules on main (approvals, code-owner review): 2 false" in r.stdout
    assert "$'10\\tfalse'" in PM_SH.read_text(encoding="utf-8") and '"10`tfalse"' in PM_PS1.read_text(encoding="utf-8")
    for s in (PM_SH, PM_PS1):
        assert "$'2\\tfalse'" not in s.read_text(encoding="utf-8") and '"2`tfalse"' not in s.read_text(encoding="utf-8")


def test_s1_2_the_app_hand_check_covers_variables_secrets_and_environments(tmp_path):
    """golive-switch/app-scope-hand-check: claude means none of Administration, Variables, Secrets and Environments
    is Read and write; the request (no --apps) and the recorded answer both say so, in both twins."""
    r, _ = _pm(tmp_path, args=())
    _not_ok(r, "and only if none of its Administration, Variables, Secrets and Environments permissions is Read and "
               "write (any other answer is NOT OK)")
    sub = tmp_path / "b"
    sub.mkdir()
    r, _ = _pm(sub, args=("--apps", "claude"))
    _ok(r)
    assert "none with Administration, Variables, Secrets or Environments write)" in r.stdout
    for s in (PM_SH, PM_PS1, SCRIPTS / "cutover-data-off-main.sh", SCRIPTS / "cutover-data-off-main.ps1"):
        flat = " ".join(s.read_text(encoding="utf-8").split())
        assert "Administration, Variables, Secrets and Environments" in flat and "S1-2" in flat, s
        assert "and Administration is not Read and write;" not in flat, s


@pytest.mark.parametrize("over,says", [
    ({"pages": "legacy"}, "GitHub Pages must build from a workflow (build_type workflow, Settings > Pages > Source: "
                          "GitHub Actions), not 'legacy'"),
    ({"pages": None}, "not 'none'"),
    ({"fail": {"GET repos/gn0sh/clarksville-records/pages": "all"}},
     "could not read the GitHub Pages settings (repos/gn0sh/clarksville-records/pages)"),
], ids=["legacy", "no-build-type", "refused"])
def test_s1_6_pages_must_build_from_a_workflow(tmp_path, over, says):
    """main-protect/pages-source-unchecked: build_type workflow only; a refused read is NOT OK."""
    r, _ = _pm(tmp_path, _pm_state(**over))
    _not_ok(r, says)
    assert "1 problem(s) above" in r.stdout


def test_s1_6_and_s1_7_ok_lines(tmp_path):
    r, made = _pm(tmp_path)
    _ok(r)
    assert "GitHub Pages build type: workflow" in r.stdout and "Main's .github/workflows/: daily-update.yml:file,national-update.yml:file" in r.stdout
    assert {c.get("path") for c in made} >= {R + "/pages", R + "/contents/.github/workflows?ref=main"}
    for s in ("repos/$repo/pages", "repos/$repo/contents/.github/workflows?ref=$wref", "'.build_type // empty'",
              "'.[] | [.name, .type] | @tsv'", "GitHub Pages build type: ", "Main's .github/workflows/: ",
              "main's .github/workflows/ must hold exactly daily-update.yml and national-update.yml"):
        assert s in PM_SH.read_text(encoding="utf-8") and s in PM_PS1.read_text(encoding="utf-8"), s


_WF_SET = "main's .github/workflows/ must hold exactly daily-update.yml and national-update.yml"


@pytest.mark.parametrize("over,says", [
    ({"workflows": WORKFLOWS_OK + [["other.yml", "file"]]}, _WF_SET),
    ({"workflows": [["daily-update.yml", "file"], ["other.yml", "file"]]}, _WF_SET),
    ({"workflows": WORKFLOWS_OK + [["sub", "dir"]]}, _WF_SET),
    ({"workflows": [["daily-update.yml", "file"], ["national-update.yml", "dir"]]}, _WF_SET),
    ({"workflows": [["daily-update.yml", "file"]]}, _WF_SET),
    ({"workflows": [["national-update.yml", "file"]]}, _WF_SET),
    ({"workflows": [["national-update.yml", "file"], ["daily-update.yml", "file"]]}, _WF_SET),
    ({"workflows": [["daily-update.yml", "file"], ["national-update.yaml", "file"]]}, _WF_SET),
    ({"workflows": [["v1-canary.yml", "file"]]}, _WF_SET),
    ({"fail": {"GET repos/gn0sh/clarksville-records/contents/.github/workflows?ref=main": "all"}},
     "could not read main's .github/workflows/ folder"),
], ids=["third-file", "other-for-national", "subfolder", "national-a-dir", "daily-only", "national-only",
        "out-of-order", "yaml-suffix", "other-only", "refused"])
def test_s1_7_daily_and_national_update_are_the_only_workflows_on_main(tmp_path, over, says):
    """main-protect/wf-shape-heuristic: main's .github/workflows/ is exactly daily-update.yml and national-update.yml
    (note 2026-11-20); any other file, either one missing, or a folder, is NOT OK, in both modes."""
    for i, args in enumerate((("--apps", "claude"), ("--pre-cutover", "--apps", "claude"))):
        sub = tmp_path / str(i)
        sub.mkdir()
        st = _pm_state(**over, **({"wf": PRE_WF} if "--pre-cutover" in args else {}))
        r, _ = _pm(sub, st, args=args)
        _not_ok(r, says)
        assert "1 problem(s) above" in r.stdout, r.stdout


# ---------------------------------------------------------------------------------------------- protect-main: national
def _nat_line(r):
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("Main's national-update.yml: ")]
    assert len(line) == 1, r.stdout
    return line[0]


_NAT_OK_LINE = ("Main's national-update.yml: workflow 'permissions: {}'; gate step in 'gate'; attestations: write in "
                "'push'; contents: write in 'push'; id-token: write in 'push'; pull-requests: write in ''; inline job "
                "permissions in ''; writes 'push:contents,push:id-token,push:attestations,report:issues'; environments "
                "in ''; reusable workflows in ''; secrets in ''; push needs '[gate, collect]'")


def test_protect_main_reads_mains_national_workflow(tmp_path):
    """Note 2026-11-20: national-update.yml is read at the same ref, with the same reader, and passes; the comment
    traps count for nothing. Checked in --pre-cutover mode too."""
    r, made = _pm(tmp_path)
    _ok(r)
    assert _nat_line(r) == _NAT_OK_LINE
    assert [c for c in made if c.get("path") == NAT_PATH][0]["method"] == "GET"
    sub = tmp_path / "pre"
    sub.mkdir()
    r, _ = _pm(sub, _pm_state(wf=PRE_WF), args=("--pre-cutover", "--apps", "claude"))
    _ok(r)
    assert _nat_line(r) == _NAT_OK_LINE


_NAT_BAD = [
    ("no-gate-step", lambda w: w.replace(NAT_STEP, "Check national-data"),
     f"main's national-update.yml must run the step '{NAT_STEP}' in job gate, and only there"),
    ("gate-step-twice", lambda w: w.replace("      - name: Collect\n", f"      - name: {NAT_STEP}\n"),
     f"main's national-update.yml must run the step '{NAT_STEP}' in job gate, and only there"),
    ("daily-gate-step-name", lambda w: w.replace(NAT_STEP, GATE_STEP),
     f"main's national-update.yml must run the step '{NAT_STEP}' in job gate, and only there"),
    ("top-write-all", lambda w: w.replace("permissions: {}\n", "permissions: write-all\n"),
     "main's national-update.yml must set permissions: {} at the top"),
    ("top-missing", lambda w: w.replace("permissions: {}\n", ""),
     "main's national-update.yml must set permissions: {} at the top"),
    ("attest-in-report", lambda w: w.replace("      issues: write ", "      attestations: write\n      issues: write "),
     "in main's national-update.yml only job push may hold attestations: write"),
    ("no-attest-in-push", lambda w: w.replace("      attestations: write    # store", "      attestations: read    # store"),
     "in main's national-update.yml only job push may hold attestations: write"),
    ("contents-write-collect", lambda w: w.replace("      contents: read         # check out the code",
                                                   "      contents: write        # check out the code"),
     "in main's national-update.yml only job push may hold contents: write"),
    ("contents-write-quoted", lambda w: w.replace("      contents: read         # check out the code",
                                                  "      contents: 'write'"),
     "the only writes may be contents, id-token and attestations in job push and issues in job report, not "
     "'collect:contents'"),
    ("id-token-in-gate", lambda w: w.replace("      attestations: read     # read the",
                                             "      id-token: write\n      attestations: read     # read the"),
     "in main's national-update.yml only job push may hold id-token: write"),
    ("pr-write", lambda w: w.replace("      id-token: write        # sign",
                                     "      pull-requests: write\n      id-token: write        # sign"),
     "no job in main's national-update.yml may hold pull-requests: write"),
    ("pages-write", lambda w: w.replace("      id-token: write        # sign",
                                        "      pages: write\n      id-token: write        # sign"),
     "the only writes may be contents, id-token and attestations in job push and issues in job report, not "
     "'push:pages'"),
    ("actions-write-report", lambda w: w.replace("      issues: write ", "      actions: write\n      issues: write "),
     "not 'report:actions'"),
    ("inline-write-all", lambda w: w.replace("    permissions:\n      issues: write          # open or comment on one issue\n",
                                             "    permissions: write-all\n"),
     "no job in main's national-update.yml may set its permissions inline"),
    ("environment", lambda w: w.replace("  push:\n    needs: [gate, collect]\n",
                                        "  push:\n    needs: [gate, collect]\n    environment: github-pages\n"),
     "no job in main's national-update.yml may name an environment"),
    ("reusable-workflow", lambda w: w.replace("  collect:\n    needs: gate\n",
                                              "  collect:\n    needs: gate\n    uses: someone/x/.github/workflows/y.yml@v1\n"),
     "no job in main's national-update.yml may call a reusable workflow"),
    ("secret-in-step", lambda w: w.replace("          GH_TOKEN: ${{ github.token }}",
                                           "          GH_TOKEN: ${{ secrets.BUTTONDOWN_API_KEY }}"),
     "main's national-update.yml may read no secret"),
    ("secret-tojson", lambda w: w.replace("          GH_TOKEN: ${{ github.token }}",
                                          "          ALL: ${{ toJSON(secrets) }}"),
     "main's national-update.yml may read no secret"),
    ("secret-bare", lambda w: w.replace("        run: true\n  push:", "        run: echo ${{ secrets }}\n  push:"),
     "main's national-update.yml may read no secret"),
    ("secret-at-top", lambda w: w.replace("permissions: {}\n", "permissions: {}\nenv:\n  K: ${{ secrets['K'] }}\n"),
     "main's national-update.yml may read no secret"),
    ("push-not-after-gate", lambda w: w.replace("    needs: [gate, collect]\n", "    needs: [collect]\n"),
     "job push in main's national-update.yml must need gate"),
    ("empty", lambda w: "", "could not read main's .github/workflows/national-update.yml"),
]


@pytest.mark.parametrize("change,says", [(c, s_) for _, c, s_ in _NAT_BAD], ids=[i for i, _, _ in _NAT_BAD])
def test_protect_main_not_ok_for_a_national_workflow_off_its_shape(tmp_path, change, says):
    bad = change(NAT_WF)
    assert bad != NAT_WF
    r, _ = _pm(tmp_path, _pm_state(wfn=bad, wfn_sha=NAT_BLOB))
    _not_ok(r, says)


def test_protect_main_national_comment_lines_count_for_nothing(tmp_path):
    """A secret, an environment or a write named only in a comment is not a finding (the same rule as daily-update)."""
    wf = NAT_WF.replace("  push:\n", "  # environment: github-pages ${{ secrets.X }} pages: write\n  push:\n")
    r, _ = _pm(tmp_path, _pm_state(wfn=wf.replace("\n", "\r\n"), wfn_sha=NAT_BLOB))
    _ok(r)
    assert _nat_line(r) == _NAT_OK_LINE


def test_protect_main_a_refused_national_read_is_not_ok(tmp_path):
    r, _ = _pm(tmp_path, _pm_state(fail={f"GET {NAT_PATH}": "all"}))
    _not_ok(r, "could not read main's .github/workflows/national-update.yml")


def test_protect_main_accepts_this_checkouts_workflows(tmp_path):
    """The real .github/workflows/ of this checkout: exactly the two files, and its national-update.yml passes."""
    names = sorted(p.name for p in (ROOT / ".github" / "workflows").iterdir())
    assert names == [n for n, _ in WORKFLOWS_OK]
    wfn = (ROOT / ".github" / "workflows" / "national-update.yml").read_text(encoding="utf-8")
    assert f"- name: {NAT_STEP}" in wfn
    r, _ = _pm(tmp_path, _pm_state(wfn=wfn))
    _ok(r)
    line = _nat_line(r)
    assert "writes 'push:contents,push:id-token,push:attestations,report:issues'" in line, line


def test_protect_main_ps1_reads_the_national_workflow_the_same_way():
    sh, ps1 = PM_SH.read_text(encoding="utf-8"), PM_PS1.read_text(encoding="utf-8")
    call = ('gh api "repos/$repo/contents/.github/workflows/national-update.yml?ref=$wref" '
            "-H 'Accept: application/vnd.github.raw'")
    assert call in sh and call in ps1
    assert f'nat_step="{NAT_STEP}"' in sh and f"$natStep = '{NAT_STEP}'" in ps1
    assert "$'daily-update.yml\\tfile\\nnational-update.yml\\tfile'" in sh
    assert '$wfs.Count -ne 2 -or $wfs[0] -cne "daily-update.yml`tfile" -or $wfs[1] -cne "national-update.yml`tfile"' in ps1
    assert "$wfs.Count -ne 1" not in ps1 and "$'daily-update.yml\\tfile' ]" not in sh
    for want in ("^[ \\t]+id-token:[ \\t]*write$", "^    environment:", "^    uses:",
                 "(^|[^A-Za-z0-9_])secrets([^A-Za-z0-9_]|$)"):
        assert want in sh and want in ps1, want
    assert "/^[ \\t]+[A-Za-z0-9_-]+:[ \\t]*.?write.?$/" in sh
    assert "'^[ \\t]+([A-Za-z0-9_-]+):[ \\t]*.?write.?$'" in ps1
    assert "push:contents|push:id-token|push:attestations|report:issues)" in sh
    assert "@('push:contents', 'push:id-token', 'push:attestations', 'report:issues') -cnotcontains $x" in ps1
    assert "awk -v gs=\"$nat_step\" -v os=\"$old_step\" \"$wf_awk\"" in sh and "WfShape $wfn $natStep" in ps1
    assert "WfShape $wf $gateStep" in ps1 and "if ($n -ceq $gs)" in ps1
    for ln in ["Main's national-update.yml: workflow '$ntop'; gate step in '$ng'; attestations: write in '$naw'; "
               "contents: write in '$ncw'; id-token: write in '$nidw'; pull-requests: write in '$npw'; inline job "
               "permissions in '$nip'; writes '$nwr'; environments in '$nenv'; reusable workflows in '$nju'; secrets "
               "in '$nsec'; push needs '$npn'",
               "main's national-update.yml must set permissions: {} at the top (each job then names its own)",
               "main's national-update.yml must run the step '$nat", "' in job gate, and only there (ADR 0013 decision 6)",
               "in main's national-update.yml only job push may hold attestations: write (its attestations name "
               "national-update.yml, never accepted for records-data)",
               "in main's national-update.yml only job push may hold contents: write",
               "in main's national-update.yml only job push may hold id-token: write",
               "no job in main's national-update.yml may hold pull-requests: write",
               "no job in main's national-update.yml may set its permissions inline (write-all, read-all or a { } map)",
               "in main's national-update.yml the only writes may be contents, id-token and attestations in job push "
               "and issues in job report, not '",
               "no job in main's national-update.yml may name an environment (only daily-update's gated jobs deploy "
               "or send)",
               "no job in main's national-update.yml may call a reusable workflow (a job-level uses:)",
               "main's national-update.yml may read no secret",
               "job push in main's national-update.yml must need gate",
               "nread \"main's .github/workflows/national-update.yml\""]:
        assert ln in sh, ln
        assert ln in ps1, ln
    raw = PM_PS1.read_bytes()
    assert raw.isascii() and not raw.startswith(b"\xef\xbb\xbf")
    # no double quote inside a --jq argument (Windows PowerShell 5.1 mangles them)
    for m in re.finditer(r"--jq '([^']*)'", ps1):
        assert '"' not in m.group(1), m.group(0)


# ---------------------------------------------------------------------------------------------- national: the pin
def test_the_national_pin_is_this_checkouts_file_in_both_twins():
    """main-protect/nat-shape-heuristic-bypass: both twins pin git hash-object of this checkout's national-update.yml,
    so any change to that workflow fails here until a reviewed PR updates protect-main (and this note: I-wf)."""
    got = subprocess.run(["git", "hash-object", str(ROOT / ".github" / "workflows" / "national-update.yml")],
                         capture_output=True, text=True, check=True).stdout.strip()
    assert got == NAT_BLOB == _blob(REAL_NAT), (got, NAT_BLOB)
    ps1 = PM_PS1.read_text(encoding="utf-8")
    assert f"$natBlob = '{NAT_BLOB}'" in ps1 and ps1.count(NAT_BLOB) == 1
    assert PM_SH.read_text(encoding="utf-8").count(NAT_BLOB) == 1
    call = 'gh api "repos/$repo/contents/.github/workflows/national-update.yml?ref=$wref" --jq .sha'
    assert call in PM_SH.read_text(encoding="utf-8")
    assert "Lines \"repos/$repo/contents/.github/workflows/national-update.yml?ref=$wref\" '.sha'" in ps1
    for ln in ["Main's national-update.yml blob: ",
               "main's national-update.yml is not the reviewed one (blob ",
               "a changed national-update.yml needs a reviewed protect-main update (main-protect-invariant.md, I-wf)",
               "nread \"main's .github/workflows/national-update.yml blob sha\""]:
        assert ln in PM_SH.read_text(encoding="utf-8") and ln in ps1, ln


def test_protect_main_ok_with_the_pinned_national_workflow(tmp_path):
    r, _ = _pm(tmp_path, _pm_state(wfn=REAL_NAT))
    _ok(r)
    assert f"Main's national-update.yml blob: {NAT_BLOB} (reviewed: {NAT_BLOB})" in r.stdout


_PIN_SAYS = "main's national-update.yml is not the reviewed one (blob "
# Each passes the shape regexes (the security review's bypasses); only the pin catches it.
_NAT_BYPASS = [
    ("job-props-6-spaces", lambda w: w.replace("  push:\n    needs: [gate, collect]\n",
                                               "  push:\n      environment: morning-note\n      needs: [gate, collect]\n")),
    ("flow-style-job", lambda w: w.replace("\njobs:\n", "\njobs:\n  x: {runs-on: ubuntu-24.04, environment: "
                                           "github-pages, steps: [{run: echo}]}\n")),
    ("quoted-key", lambda w: w.replace("  push:\n    needs: [gate, collect]\n",
                                       "  push:\n    needs: [gate, collect]\n    \"environment\": github-pages\n")),
    ("spaced-colon", lambda w: w.replace("      contents: read         # check out the code",
                                         "      contents : write")),
    ("one-byte", lambda w: w + "\n"),
]


@pytest.mark.parametrize("change", [c for _, c in _NAT_BYPASS], ids=[i for i, _ in _NAT_BYPASS])
def test_protect_main_not_ok_for_any_change_to_the_national_workflow(tmp_path, change):
    bad = change(REAL_NAT)
    assert bad != REAL_NAT
    r, _ = _pm(tmp_path, _pm_state(wfn=bad))
    _not_ok(r, _PIN_SAYS + _blob(bad) + ", reviewed " + NAT_BLOB + "): a changed national-update.yml needs a reviewed "
               "protect-main update")


def test_protect_main_a_refused_pin_read_is_not_ok(tmp_path):
    r, _ = _pm(tmp_path, _pm_state(fail={f"GET {NAT_PATH}": [2]}))       # the raw read works, the .sha read fails
    _not_ok(r, "could not read main's .github/workflows/national-update.yml blob sha")
    assert "1 problem(s) above" in r.stdout


def test_secrets_word_rule_spares_other_words(tmp_path):
    wf = NAT_WF.replace("          GH_TOKEN: ${{ github.token }}",
                        "          GH_TOKEN: ${{ github.token }}\n          my_secrets_dir: x\n          a: secretsx")
    r, _ = _pm(tmp_path, _pm_state(wfn=wf, wfn_sha=NAT_BLOB))
    _ok(r)
