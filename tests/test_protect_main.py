"""scripts/protect-main.{sh,ps1} and scripts/merge-reviewed.{sh,ps1} under ADR 0011 (task D1; consumer rows R1, R-D,
R2, S1, S2; PR #54 security review findings F1, F2 and settings drift).

The .sh scripts run here against a stub gh (no GitHub call is ever made: the stub is first on PATH and the GitHub
tokens are removed from the environment); the .ps1 twins (no PowerShell here) are pinned to the same filters, lines
and refusals text by text."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

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

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is needed by the scripts and the stub")

# ---------------------------------------------------------------------------------------------- the stub gh
_GH = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
a = sys.argv[1:]
statef = os.environ["GH_STATE"]
st = json.load(open(statef))
def save():
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
if path == R + "/git/ref/heads/main":
    out({"object": {"sha": st["main"]}})
if path == R + "/rulesets?per_page=100":
    if method == "POST":
        body = json.load(open(args[args.index("--input") + 1]))
        log({"post_body": body})
        st["next_id"] = st.get("next_id", 100) + 1
        st["rulesets"].append({"id": st["next_id"], **body}); save(); sys.exit(0)
    out([{"id": x["id"], "name": x["name"], "target": x["target"], "enforcement": x["enforcement"]} for x in st["rulesets"]])
if path == R + "/rulesets":
    assert method == "POST", a
    body = json.load(open(args[args.index("--input") + 1]))
    log({"post_body": body})
    st["next_id"] = st.get("next_id", 100) + 1
    st["rulesets"].append({"id": st["next_id"], **body}); save(); sys.exit(0)
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
if path == "user/installations?per_page=100":
    out({"total_count": len(st["apps"]), "installations": st["apps"]})
if path.startswith("user/installations/") and path.endswith("/repositories?per_page=100"):
    iid = path.split("/")[2]
    out({"repositories": [{"full_name": x} for x in st["app_repos"].get(iid, [])]})
if path == R + "/keys?per_page=100":
    out(st["keys"])
if path.startswith(R + "/environments/"):
    rest = path[len(R + "/environments/"):]
    if rest.endswith("/deployment-branch-policies?per_page=100"):
        env = rest.split("/")[0]
        pols = st["env_policies"][env]
        out({"total_count": len(pols), "branch_policies": pols})
    out({"name": rest, "deployment_branch_policy": st["envs"][rest]})
sys.stderr.write("stub: unexpected call %r\n" % a); sys.exit(9)
'''


def _perm(level):
    order = ["pull", "triage", "push", "maintain", "admin"]
    return {p: order.index(p) <= order.index(level) for p in order}


def _pm_state(**over):
    st = {"main": "1" * 40, "rulesets": [], "r2": True, "auto": False,
          "collabs": [{"login": "gn0sh", "permissions": _perm("admin"), "role_name": "admin"}],
          "invites": [], "apps": [], "app_repos": {}, "keys": [],
          "envs": {e: {"protected_branches": False, "custom_branch_policies": True}
                   for e in ("github-pages", "morning-note")},
          "env_policies": {e: [{"id": 1, "name": "main", "type": "branch"}] for e in ("github-pages", "morning-note")}}
    st.update(over)
    return st


def _env(tmp_path, st, stub=_GH):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for name, text in (("gh", stub), ("sleep", "#!/bin/sh\nexit 0\n")):
        (bindir / name).write_text(text)
        (bindir / name).chmod(0o755)
    (tmp_path / "state.json").write_text(json.dumps(st))
    env = {k: v for k, v in os.environ.items() if k not in CLOUD + ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN")}
    env.update({"PATH": f"{bindir}:{os.environ['PATH']}", "GH_CALLS": str(tmp_path / "calls"),
                "GH_STATE": str(tmp_path / "state.json"), "HOME": str(tmp_path)})
    return env


def _calls(tmp_path):
    p = tmp_path / "calls"
    return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []


def _pm(tmp_path, st=None, **env_over):
    env = {**_env(tmp_path, st or _pm_state()), **env_over}
    r = subprocess.run(["bash", str(PM_SH)], env=env, capture_output=True, text=True, timeout=120)
    return r, _calls(tmp_path)


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
            pr["dismiss_stale_reviews_on_push"], pr["allowed_merge_methods"]) == (2, True, False, True, ["squash"])
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
    {"apps": [{"id": 7, "app_slug": "other-acct", "account": {"login": "someone"}, "repository_selection": "all",
               "permissions": {"contents": "write"}}]},
    {"apps": [{"id": 8, "app_slug": "elsewhere", "account": {"login": "gn0sh"}, "repository_selection": "selected",
               "permissions": {"contents": "write"}}], "app_repos": {"8": ["gn0sh/other"]}},
    {"apps": [{"id": 9, "app_slug": "reader", "account": {"login": "gn0sh"}, "repository_selection": "all",
               "permissions": {"contents": "read", "metadata": "read"}}]},
    {"keys": [{"id": 3, "title": "ro", "read_only": True}]},
    {"collabs": [{"login": "gn0sh", "permissions": _perm("admin")}, {"login": "friend", "permissions": _perm("triage")}]},
    {"invites": [{"id": 4, "invitee": {"login": "friend"}, "permissions": "read"}]},
], ids=["app-other-account", "app-other-repo", "app-read-only", "read-only-key", "triage-collaborator",
        "read-invite"])
def test_protect_main_ok_with_non_writers(tmp_path, st_over):
    r, _ = _pm(tmp_path, _pm_state(**st_over))
    _ok(r)


# ---------------------------------------------------------------------------------------------- protect-main: each NOT OK
_ADMIN_APP = {"id": 11, "app_slug": "admin-app", "account": {"login": "gn0sh"}, "repository_selection": "selected",
              "permissions": {"administration": "write", "contents": "read"}}


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
    ({"apps": [{"id": 7, "app_slug": "extra-app", "account": {"login": "gn0sh"}, "repository_selection": "all",
                "permissions": {"contents": "write"}}]}, "an installed App can write this repository: extra-app"),
    ({"apps": [{"id": 8, "app_slug": "picked", "account": {"login": "gn0sh"}, "repository_selection": "selected",
                "permissions": {"contents": "write"}}], "app_repos": {"8": ["gn0sh/other", REPO]}},
     "an installed App can write this repository: picked"),
    ({"apps": [_ADMIN_APP], "app_repos": {"11": [REPO]}}, "an installed App can write this repository: admin-app"),
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
     "main needs exactly one pull_request rule, with 2 approvals and no code-owner review"),
    ({"extra_main_rules": [{"type": "required_signatures"}]},
     "main's rules must be deletion,non_fast_forward,pull_request"),
], ids=["r2-stays-on", "auto-merge", "write-collaborator", "maintain-collaborator", "no-collaborators",
        "write-invitation", "extra-app-all", "extra-app-selected", "admin-app", "write-deploy-key", "tag-env-policy",
        "extra-env-policy", "protected-branches-env", "all-branches-env", "r1pp-differs", "rd-differs",
        "duplicate-rt", "extra-code-owner-rule", "extra-main-rule"])
def test_protect_main_not_ok(tmp_path, st_over, says):
    r, _ = _pm(tmp_path, _pm_state(**st_over))
    _not_ok(r, says)


_READS = [
    f"GET {R}/rulesets/101", f"GET {R}/rulesets/102", f"GET {R}/rulesets/103", f"GET {R}/rules/branches/main",
    f"GET {R}", f"GET {R}/collaborators?affiliation=all&per_page=100", f"GET {R}/invitations?per_page=100",
    "GET user/installations?per_page=100", "GET user/installations/8/repositories?per_page=100",
    f"GET {R}/keys?per_page=100", f"GET {R}/environments/github-pages", f"GET {R}/environments/morning-note",
    f"GET {R}/environments/github-pages/deployment-branch-policies?per_page=100",
    f"GET {R}/environments/morning-note/deployment-branch-policies?per_page=100",
]


@pytest.mark.parametrize("key", _READS + ["checks: rulesets list", "checks: R2"])
def test_protect_main_a_403_on_any_check_read_is_not_ok(tmp_path, key):
    """Settings drift: the team proxy refuses actions/permissions, collaborators and environments; a refused or failed
    read is NOT OK, never skipped and never OK by default."""
    st = _pm_state(apps=[{"id": 8, "app_slug": "picked", "account": {"login": "gn0sh"},
                          "repository_selection": "selected", "permissions": {"contents": "write"}}],
                   app_repos={"8": ["gn0sh/other"]})
    if key == "checks: rulesets list":                  # the writes list them three times; the 4th read is a check
        st["fail"] = {f"GET {R}/rulesets?per_page=100": [4]}
    elif key == "checks: R2":                           # the first read decides the write; the second is the check
        st["fail"] = {f"GET {R}/actions/permissions/workflow": [2]}
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
                 '"user/installations?per_page=100"', '"repos/$repo/keys?per_page=100"',
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
             "main needs exactly one pull_request rule, with 2 approvals and no code-owner review",
             "R2 is on: with R2 on, gn0sh plus the bot can approve a pull request (ADR 0011 decision 6)",
             "auto-merge must be off: Settings > General > Pull Requests > untick Allow auto-merge",
             "Collaborators with write or more: ", "the collaborators with write or more must be exactly $owner",
             "Pending invitations with write or more: ", "a pending invitation with write or more: ",
             "Installed Apps with contents or administration write on this repository: ",
             "an installed App can write this repository: ", "Deploy keys with write: ", "a deploy key with write: ",
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
    for want in ("$'false\\ttrue'", "$'main\\tbranch'", "$'2\\tfalse'"):
        assert want in sh, want
    for want in ('"false`ttrue"', '"main`tbranch"', '"2`tfalse"'):
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
    r = subprocess.run(["bash", str(MR_SH), *args], env=env, capture_output=True, text=True, timeout=60)
    p = tmp_path / "calls"
    made = [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []
    return r, [c for c in made if c[0] == "api"]


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
    assert r.returncode == 1 and ("Nothing done" in r.stdout or "Usage" in r.stdout), r.stdout
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
