"""scripts/cutover-data-off-main.{sh,ps1}: the one-session cutover in the Operator's order, and its rollback (ADR 0011;
docs/tasks/data-off-main.md D3; PR #54 security review: drift, F4, F5, F7).

The .sh runs here against a stub gh, a stub curl and stub protect-main / merge-reviewed scripts (no GitHub call is
ever made: the stubs are first on PATH, the tokens are removed, and "origin" is a bare repository in tmp_path). The
seed is built for real with git, and its checks run the real collector.data_shape and tools.scrub_rpc_phones. With
PWSH set, every test that runs the script also runs the .ps1 twin against the same stubs (tests/pwsh_twin.py); the
.ps1 is also pinned to the same steps, filters and lines text by text."""
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from collector import data_shape
import pwsh_twin

ROOT = Path(__file__).resolve().parent.parent
SH = ROOT / "scripts" / "cutover-data-off-main.sh"
PS1 = ROOT / "scripts" / "cutover-data-off-main.ps1"
REPO = "gn0sh/clarksville-records"
R = "repos/" + REPO
CLOUD = ("CLAUDE_CODE_REMOTE", "GITHUB_ACTIONS", "CI")
R1P = json.loads((ROOT / "scripts" / "main-ruleset-r1p.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is needed by the script and the stub")


def pytest_generate_tests(metafunc):
    """Each test that runs the script (it takes tmp_path) runs once per twin: "sh", and "ps1" when PWSH is set."""
    if "tmp_path" in metafunc.fixturenames:
        metafunc.parametrize("twin", pwsh_twin.TWINS, indirect=True)


@pytest.fixture(autouse=True)
def twin(request):
    Fx.twin_default = getattr(request, "param", "sh")
    yield Fx.twin_default
    Fx.twin_default = "sh"


# the .sh's flags as the .ps1's parameters
PS_FLAGS = {"--plan": "-Plan", "--prepare": "-Prepare", "--rollback": "-Rollback", "--cutover-merge": "-CutoverMerge",
            "--data-from": "-DataFrom", "--merge": "-Merge", "--sha": "-Sha", "--report": "-Report", "--pr": "-Pr",
            "--apps": "-Apps", "--ref": "-Ref", "--check-attested": "-CheckAttested"}

# ---------------------------------------------------------------------------------------------- stubs
_GH = r'''#!/usr/bin/env python3
import hashlib, json, os, re, subprocess, sys
a = sys.argv[1:]
statef = os.environ["GH_STATE"]
st = json.load(open(statef))
origin = os.environ["STUB_ORIGIN"]
def save():
    json.dump(st, open(statef, "w"))
def log(entry):
    with open(os.environ["GH_CALLS"], "a") as f:
        f.write(json.dumps(entry) + "\n")
def git(*args, **kw):
    return subprocess.run(["git", "--git-dir", origin, *args], capture_output=True, text=True, check=True, **kw).stdout.strip()
def out(data):
    if "--jq" in a:
        r = subprocess.run(["jq", "-r", a[a.index("--jq") + 1]], input=json.dumps(data), capture_output=True, text=True)
        sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); sys.exit(r.returncode)
    print(json.dumps(data)); sys.exit(0)
def refuse(path):
    if path in st.get("refuse", []):
        save(); sys.stderr.write("gh: Resource not accessible by integration (HTTP 403)\n"); sys.exit(1)
def rd_head():
    r = subprocess.run(["git", "--git-dir", origin, "rev-parse", "--verify", "-q", "refs/heads/records-data"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""
if a[:2] == ["auth", "status"]:
    sys.exit(0)
if a[:2] == ["attestation", "verify"]:
    log({"method": "ATTEST", "path": "attestation verify", "argv": a})
    digest = hashlib.sha256(open(a[2], "rb").read()).hexdigest()
    sys.exit(0 if digest in st.get("attested", []) else 1)
assert a[0] == "api", a
args = [x for x in a[1:] if x not in ("--paginate", "--silent")]
method = "GET"
if args[0] == "-X":
    method, args = args[1], args[2:]
path = args[0]
log({"method": method, "path": path, "argv": a, "records_data": rd_head()})
refuse(path)
R = "repos/gn0sh/clarksville-records"
W = R + "/actions/workflows/daily-update.yml"
if path == R + "/actions/variables?per_page=100":
    out({"variables": [{"name": n, "value": "x"} for n in st["vars"]]})
if path.startswith(W + "/runs?"):
    runs = st["runs"]
    if "event=workflow_dispatch" in path:
        runs = [r for r in runs if r.get("event") == "workflow_dispatch"]
    out({"workflow_runs": sorted(runs, key=lambda r: -r["id"])})
if path == W and method == "GET":
    out({"state": st["wf_state"]})
if path in (W + "/disable", W + "/enable") and method == "PUT":
    if path.endswith("/disable"):
        st["wf_state"] = "disabled_manually"
        for cmd in st.get("on_disable", []):          # a late change to main, between steps 1 and 3
            subprocess.run(cmd, shell=True, check=True)
        if st.get("run_starts_on_disable"):
            st["runs"].append({"id": 5, "status": "in_progress", "event": "schedule"})
    else:
        st["wf_state"] = "active"
    save(); sys.exit(0)
if path == W + "/dispatches" and method == "POST":
    collect = [x for x in a if x.startswith("inputs[collect]=")][0].split("=", 1)[1]
    rid = max([r["id"] for r in st["runs"]] + [100]) + 1
    st["runs"].append({"id": rid, "status": "completed", "conclusion": "success", "event": "workflow_dispatch",
                       "collect": collect})
    st.setdefault("jobs", {})[str(rid)] = [{"name": "gate", "id": rid * 10, "conclusion": st.get("gate", "success")},
                                           {"name": "deploy", "conclusion": st.get("deploy", "success")}]
    # B2's gate on main: with a pinned baseline, it logs the count of first-parent commits after it
    wf = git("show", "refs/heads/main:.github/workflows/daily-update.yml")
    mb = re.search(r'MAIN_PR_BASELINE:\s*"([0-9a-f]{40})"', wf)
    if mb:
        n = st.get("gate_n") or len(git("rev-list", "--first-parent", mb.group(1) + "..refs/heads/main").split())
        log_text = ("2026-11-19T00:00:01.0Z Every commit on main after %s was merged by a person, reviewed at its "
                    "head: %d commit(s).\n" % (mb.group(1), n))
    else:
        log_text = "2026-11-19T00:00:01.0Z ::warning::MAIN_PR_BASELINE is not set\n"
    st.setdefault("logs", {})[str(rid * 10)] = st.get("gate_log", log_text)
    if collect == "true" and st.get("collect_moves", True):
        head = rd_head()
        idx = os.environ["GH_STATE"] + ".idx"
        env = {**os.environ, "GIT_INDEX_FILE": idx}
        subprocess.run(["git", "--git-dir", origin, "read-tree", head], env=env, check=True)
        blob = git("hash-object", "-w", "--stdin", input='{"new": 1}\n')
        subprocess.run(["git", "--git-dir", origin, "update-index", "--add", "--cacheinfo", "100644,%s,data/new.json" % blob],
                       env=env, check=True)
        tree = subprocess.run(["git", "--git-dir", origin, "write-tree"], env=env, capture_output=True, text=True,
                              check=True).stdout.strip()
        c = git("-c", "user.name=bot", "-c", "user.email=bot@x", "commit-tree", tree, "-p", head, "-m", "data")
        git("update-ref", "refs/heads/records-data", c)
        listing = subprocess.run(["git", "--git-dir", origin, "ls-tree", "-r", "-z", c, "--", "data"],
                                 capture_output=True, check=True).stdout
        if st.get("attest", True):
            st.setdefault("attested", []).append(hashlib.sha256(listing).hexdigest())
    st["build_info"] = rd_head() if st.get("deploy", "success") == "success" else st.get("build_info", "")
    save(); sys.exit(0)
if path.startswith(R + "/actions/jobs/") and path.endswith("/logs"):
    sys.stdout.write(st["logs"][path.split("/")[-2]]); sys.exit(0)
if path.startswith(R + "/commits/") and path.endswith("/pulls"):    # the 4.7.1 window: one merged PR per commit
    c = path.split("/")[-2]
    if c in st.get("no_pr", []):
        out([])
    n = st.setdefault("pr_map", {}).get(c) or str(1000 + len(st["pr_map"]))
    st["pr_map"][c] = n; save()
    out([{"number": int(n), "merged_at": "2026-11-18T00:00:00Z", "base": {"ref": "main"}, "merge_commit_sha": c},
         {"number": 7, "merged_at": None, "base": {"ref": "main"}, "merge_commit_sha": c}])
if path.startswith(R + "/pulls/") and path[len(R + "/pulls/"):] in st.get("pr_map", {}).values():
    c = [k for k, v in st["pr_map"].items() if v == path[len(R + "/pulls/"):]][0]
    out({"number": int(path.rsplit("/", 1)[-1]), "merged_by": {"type": "Bot" if c in st.get("bot", []) else "User"}})
if path.startswith(R + "/actions/runs/"):
    rest = path[len(R + "/actions/runs/"):]
    rid = rest.split("/")[0]
    if rest.endswith("/jobs?per_page=100"):
        out({"jobs": st["jobs"][rid]})
    out([r for r in st["runs"] if str(r["id"]) == rid][0])
if path == R + "/pulls/%s" % st["pr"]["number"]:
    out(st["pr"])
if path == R + "/pulls" and method == "POST":
    st["opened"] = [x for x in a if x.startswith(("head=", "base="))]; save()
    head = [x for x in a if x.startswith("head=")][0].split("=", 1)[1]
    git("update-ref", "refs/pull/99/head", git("rev-parse", "refs/heads/" + head))
    out({"number": 99})
if path == R + "/rulesets?per_page=100":
    out([{"id": 27502319, "name": "main: pull request required"}])
if path == R + "/rulesets/27502319":
    if method == "PUT":
        st["ruleset"] = json.load(open(args[args.index("--input") + 1])); save(); sys.exit(0)
    out({**st.get("ruleset", {}), "id": 27502319, "_links": {}})
if path == R + "/actions/permissions/workflow":
    if method == "PUT":
        st["r2"] = "can_approve_pull_request_reviews=true" in a; save(); sys.exit(0)
    out({"can_approve_pull_request_reviews": st.get("r2", False)})
sys.stderr.write("stub: unexpected call %r\n" % a); sys.exit(9)
'''

_CURL = r'''#!/usr/bin/env python3
import json, os, sys
st = json.load(open(os.environ["GH_STATE"]))
with open(os.environ["GH_CALLS"], "a") as f:
    f.write(json.dumps({"method": "CURL", "path": sys.argv[-1]}) + "\n")
assert sys.argv[-1].startswith("https://daylight.gnoshcodes.com/build-info.json?cutover="), sys.argv
print(json.dumps({"sha": "s", "data_sha": st.get("build_info", "")}))
'''

_PROTECT = r'''#!/usr/bin/env bash
python3 -c 'import json,os,sys; open(os.environ["GH_CALLS"],"a").write(json.dumps({"method":"SCRIPT","path":"protect-main","argv":sys.argv[1:]})+"\n")' "$@"
echo "Main before the rulesets: $(git --git-dir "$STUB_ORIGIN" rev-parse refs/heads/main)"
old=$(git --git-dir "$STUB_ORIGIN" ls-tree --name-only refs/heads/main -- data)
pre=0; for a in "$@"; do [ "$a" = --pre-cutover ] && pre=1; done
if [ "$pre" = 1 ] && [ -n "${STUB_PM_BLOCK:-}" ]; then : > "$STUB_PM_BLOCK"; exec /bin/sleep 60; fi   # a Ctrl+C test
if [ "$pre" = 1 ] && [ -z "$old" ]; then echo "  NOT OK: --pre-cutover, but the cutover is merged"; echo "NOT OK: 1 problem(s) above."; exit 1; fi
if [ "$pre" = 0 ] && [ -n "$old" ]; then echo "  NOT OK: main's workflow still opens data pull requests"; echo "NOT OK: 1 problem(s) above."; exit 1; fi
if [ "$pre" = 1 ] && [ -n "${STUB_PM_MOVE_RD:-}" ]; then   # someone pushes onto records-data before R-D binds (S1-5)
  g="git --git-dir $STUB_ORIGIN"; rd=$($g rev-parse refs/heads/records-data)
  x=$($g -c user.name=x -c user.email=x@x commit-tree "$rd^{tree}" -p "$rd" -m "late push"); $g update-ref refs/heads/records-data "$x"
fi
want=ok; [ "$pre" = 1 ] && want=${STUB_PM:-ok}; [ "$pre" = 0 ] && want=${STUB_PM_CHECK:-ok}
if [ "$want" = ok ]; then echo "OK: main is protected (stub)."; exit 0; fi
echo "  NOT OK: R2 is on"; echo "NOT OK: 1 problem(s) above."; exit 1
'''

_MERGE = r'''#!/usr/bin/env bash
python3 -c 'import json,os,sys; open(os.environ["GH_CALLS"],"a").write(json.dumps({"method":"SCRIPT","path":"merge-reviewed","argv":sys.argv[1:]})+"\n")' "$@"
g="git --git-dir $STUB_ORIGIN"
if [ -n "${STUB_MR_MOVE:-}" ]; then   # another commit lands on main just before the squash
  x=$($g -c user.name=g -c user.email=g@x commit-tree "refs/heads/main^{tree}" -p refs/heads/main -m "late")
  $g update-ref refs/heads/main "$x"
fi
m=$($g -c user.name=gn0sh -c user.email=g@x commit-tree "${STUB_MR_TREE:-$2}^{tree}" -p refs/heads/main -m "squash #$1")
$g update-ref refs/heads/main "$m"
if [ -n "${STUB_MR_BLOCK:-}" ]; then : > "$STUB_MR_BLOCK"; exec /bin/sleep 60; fi   # a Ctrl+C test, main moved
echo "Merged pull request #$1 (reviewed at $2) as $m."
if [ "${STUB_MR:-bypass}" = bypass ]; then echo "Rule suite 9 for $m: bypass"; exit 0; fi
if [ "${STUB_MR}" = garbled ]; then echo "gh: HTTP 502"; exit 1; fi
echo "Rule suite 9 for $m: pass"; echo "The merge was not a bypass (pass): tell the team."; exit 2
'''

# the .ps1 twin calls protect-main.ps1 and merge-reviewed.ps1: these bind as the real ones (their param blocks) and
# run the stubs above with the .sh's arguments
_PROTECT_PS1 = pwsh_twin.param_block(ROOT / "scripts" / "protect-main.ps1") + r'''
$a = @()
if ($PreCutover) { $a += '--pre-cutover' }
if ($Check) { $a += '--check' }
if ($PSBoundParameters.ContainsKey('Apps')) { $a += @('--apps', $Apps) }
& bash (Join-Path $PSScriptRoot 'protect-main.sh') @a
exit $LASTEXITCODE
'''
_MERGE_PS1 = pwsh_twin.param_block(ROOT / "scripts" / "merge-reviewed.ps1") + r'''
& bash (Join-Path $PSScriptRoot 'merge-reviewed.sh') $Pr $Sha @Reports
exit $LASTEXITCODE
'''

_DATE = r'''#!/bin/sh
for x in "$@"; do [ "$x" = "+%H%M" ] && { echo "$FAKE_HM"; exit 0; }; done
exec /bin/date "$@"
'''

RPC_OK = {"cases": [{"id": "SR-1", "location": "100 Main St"}]}
RPC_PHONE = {"cases": [{"id": "SR-1", "location": "100 Main St, 931-555-0100"}]}
MAIN_DATA = {
    "data/facts.json": '{"meetings": []}\n',
    "data/changes.jsonl": "{}\n",
    "data/localities/cmc-rpc/rpc.json": json.dumps(RPC_OK),
    "data/localities/clarksville-tn/wards.json": "{}\n",
    "data/localities/clarksville-tn/transcripts/2026-01-06-council.json": '{"masked": true}\n',
    "data/maps/manifest.json": "[]\n",
    "data/names.yml": "names: []\n",
    "data/procedural-titles.yml": "titles: []\n",
    "data/corrections-log.json": "[]\n",
}
MOVED = [p for p in MAIN_DATA if "/transcripts/" in p or p.startswith("data/maps/") or p.endswith((".yml", "log.json"))]
# The real workflow's bash also names both keys followed by ':' (base="${MAIN_PR_BASELINE:-}" and the seed's
# twin), so the fixture does too: only the env key lines may count (third cutover run, 2026-11-19).
OLD_WF = ('jobs:\n  gate:\n    steps:\n      - run: |\n          base="${MAIN_PR_BASELINE:-}"\n'
          '          seed="${RECORDS_DATA_SEED_DIGEST:-}"\n    env:\n      MAIN_PR_BASELINE: ""   # T4.10.8\n')
CODEOWNERS = "* @gn0sh\n/data/\n"


def _git(cwd, *args, env=None, input=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, env=env, input=input, check=True)
    return r.stdout


def _write(base, files):
    for rel, text in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            if p.exists():
                p.unlink()
        else:
            p.write_text(text)


def _seed_listing(work, rev, moved):
    """`git ls-tree -r -z <rev> -- data` minus the moved entries: the listing the script must push."""
    out = _git(work, "ls-tree", "-r", "-z", rev, "--", "data")
    keep = [e for e in out.split(b"\0") if e and e.split(b"\t", 1)[1].decode() not in moved]
    return b"".join(e + b"\0" for e in keep)


class Fx:
    """origin (bare), and a checkout at the cutover PR's head P (child of main M). twin: run the .sh or the .ps1."""
    twin_default = "sh"

    def __init__(self, tmp_path, main_extra=None, pr_extra=None, pin=None, skip_config=(), baseline=None,
                 window=None, pr_off_main=False):
        self.twin = Fx.twin_default
        self.script = SH if self.twin == "sh" else PS1
        self.tmp = tmp_path
        self.origin = tmp_path / "origin.git"
        self.work = tmp_path / "work"
        ident = {"GIT_AUTHOR_NAME": "gn0sh", "GIT_AUTHOR_EMAIL": "g@x", "GIT_COMMITTER_NAME": "gn0sh",
                 "GIT_COMMITTER_EMAIL": "g@x"}
        self.genv = {**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")}, **ident}
        _git(tmp_path, "init", "-q", "--bare", str(self.origin), env=self.genv)
        _git(tmp_path, "init", "-q", "-b", "main", str(self.work), env=self.genv)
        w = self.work
        g = lambda *a, **k: _git(w, *a, env=self.genv, **k)
        # the window start S (WINDOW_START), then main M, the commit the seed is cut from and the PR's baseline
        (w / "README").write_text("start\n")
        g("add", "README"); g("commit", "-q", "-m", "start")
        self.start = g("rev-parse", "HEAD").decode().strip()
        (w / "collector").symlink_to(ROOT / "collector")
        (w / "tools").symlink_to(ROOT / "tools")
        (w / "scripts").mkdir()
        text = SH.read_text(encoding="utf-8")
        assert re.search(r"(?m)^WINDOW_START=[0-9a-f]{40}$", text)
        (w / "scripts" / SH.name).write_text(
            re.sub(r"(?m)^WINDOW_START=.*$", "WINDOW_START=" + (self.start if window is None else window), text))
        if self.twin == "ps1":
            self.set_window(self.start if window is None else window)
            for name, text in (("protect-main.ps1", _PROTECT_PS1), ("merge-reviewed.ps1", _MERGE_PS1)):
                (w / "scripts" / name).write_text(text)
        shutil.copy(ROOT / "scripts" / "main-ruleset-r1p.json", w / "scripts")
        for name, text in (("protect-main.sh", _PROTECT), ("merge-reviewed.sh", _MERGE)):
            (w / "scripts" / name).write_text(text)
        data = {**MAIN_DATA, **(main_extra or {})}
        _write(w, {**data, ".github/workflows/daily-update.yml": OLD_WF, ".github/CODEOWNERS": CODEOWNERS,
                   ".gitignore": "build/\n"})
        g("add", "-A"); g("commit", "-q", "-m", "main")
        self.main = g("rev-parse", "HEAD").decode().strip()
        moved = [p for p in MOVED if p not in skip_config]
        cfg = {"config/" + p[len("data/"):]: data[p] for p in moved}
        listing = _seed_listing(w, self.main, set(moved))
        self.listing = listing
        self.digest = hashlib.sha256(listing).hexdigest()
        g("rm", "-q", "-r", "--cached", "data")
        shutil.rmtree(w / "data")
        self.baseline = self.main if baseline is None else baseline
        new_wf = (OLD_WF.replace('MAIN_PR_BASELINE: ""', 'MAIN_PR_BASELINE: "%s"' % self.baseline)
                  + '      RECORDS_DATA_SEED_DIGEST: "%s"   # ADR 0011\n' % (pin or self.digest))
        _write(w, {**cfg, ".github/workflows/daily-update.yml": new_wf, ".github/CODEOWNERS": None,
                   ".gitignore": "build/\ndata/\n", **(pr_extra or {})})
        g("add", "-A"); g("commit", "-q", "-m", "cutover PR")
        self.head = g("rev-parse", "HEAD").decode().strip()
        if pr_off_main:   # the same tree, but based on S: the head does not contain main
            self.head = g("commit-tree", self.head + "^{tree}", "-p", self.start, "-m", "cutover PR").decode().strip()
        g("remote", "add", "origin", str(self.origin))
        g("push", "-q", "origin", f"{self.main}:refs/heads/main", f"{self.head}:refs/pull/60/head")
        g("checkout", "-q", "--detach", self.head)
        self.bindir = tmp_path / "bin"
        self.bindir.mkdir()
        for name, text in (("gh", _GH), ("curl", _CURL), ("date", _DATE), ("sleep", "#!/bin/sh\nexit 0\n")):
            (self.bindir / name).write_text(text)
            (self.bindir / name).chmod(0o755)
        if self.twin == "ps1":
            pwsh_twin.install(tmp_path, self.bindir)
        self.state = {"vars": [], "runs": [{"id": 1, "status": "completed", "event": "schedule"}],
                      "wf_state": "active", "r2": True,
                      "pr": {"number": 60, "state": "open", "base": {"ref": "main"}, "user": {"login": "gn0sh"},
                             "draft": False, "head": {"sha": self.head, "repo": {"full_name": REPO}}}}

    def set_window(self, sha):
        """The twin's WINDOW_START in this checkout's copy of the script."""
        if self.twin == "sh":
            p = self.work / "scripts" / SH.name
            p.write_text(re.sub(r"(?m)^WINDOW_START=.*$", "WINDOW_START=" + sha, p.read_text()))
        else:
            p = self.work / "scripts" / PS1.name
            src = p.read_text(encoding="utf-8") if p.exists() else PS1.read_text(encoding="utf-8")
            p.write_bytes(re.sub(r"(?m)^\$WINDOW_START = '.*'$", "$WINDOW_START = '%s'" % sha, src).encode("ascii"))

    def cmd(self, text):
        """A command line the .sh prints (its undo or next line), as the twin under test prints it."""
        if self.twin == "sh":
            return text
        text = text.replace("bash scripts/cutover-data-off-main.sh", "powershell -NoProfile -File scripts\\" + PS1.name)
        return re.sub(r"--[a-z-]+", lambda m: PS_FLAGS.get(m.group(0), m.group(0)), text)

    def og(self, *args):
        return _git(self.tmp, "--git-dir", str(self.origin), *args, env=self.genv).decode().strip()

    def run(self, args, hm="1400", **env_over):
        cmd, env = self._argv_env(args, hm, env_over)
        r = subprocess.run(cmd, cwd=self.work, env=env, capture_output=True, text=True, timeout=300)
        self.state = json.loads((self.tmp / "state.json").read_text())
        return r

    def interrupt(self, args, flag, hm="1400", **env_over):
        """Run in its own process group until a stub touches <flag>, then SIGINT the group (Ctrl+C in a console)."""
        cmd, env = self._argv_env(args, hm, env_over)
        p = subprocess.Popen(cmd, cwd=self.work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             start_new_session=True)
        try:
            deadline = time.time() + 240
            while not flag.exists() and p.poll() is None and time.time() < deadline:
                time.sleep(0.05)
            assert flag.exists(), "the stub never blocked"
            time.sleep(0.3)
            os.killpg(p.pid, signal.SIGINT)
            out, err = p.communicate(timeout=120)
        finally:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
                p.communicate()
        self.state = json.loads((self.tmp / "state.json").read_text())
        return subprocess.CompletedProcess(cmd, p.returncode, out, err)

    def _argv_env(self, args, hm, env_over):
        (self.tmp / "state.json").write_text(json.dumps(self.state))
        env = {k: v for k, v in self.genv.items() if k not in CLOUD + ("GH_TOKEN", "GITHUB_TOKEN")}
        env.update({"PATH": f"{self.bindir}:{os.environ['PATH']}", "GH_CALLS": str(self.tmp / "calls"),
                    "GH_STATE": str(self.tmp / "state.json"), "STUB_ORIGIN": str(self.origin), "FAKE_HM": hm,
                    "HOME": str(self.tmp)}, **env_over)
        if self.twin == "sh":
            cmd = ["bash", "scripts/" + SH.name, *args]
        else:
            env = pwsh_twin.env(env)
            cmd = pwsh_twin.argv("scripts/" + PS1.name, pwsh_twin.flags(args, PS_FLAGS))
        return cmd, env

    def calls(self):
        p = self.tmp / "calls"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def cut_args(self, apps="none"):
        return ["--pr", "60", "--sha", self.head, "--apps", apps, "--report", "docs/reviews/x.md"]

    def cut(self, **kw):
        return self.run(self.cut_args(kw.pop("apps", "none")), **kw)

    def rd(self):
        r = subprocess.run(["git", "--git-dir", str(self.origin), "rev-parse", "--verify", "-q",
                            "refs/heads/records-data"], capture_output=True, text=True)
        return r.stdout.strip()


WRITES = ("PUT", "POST", "DELETE", "PATCH", "SCRIPT")


def _writes(calls):
    return [c for c in calls if c["method"] in WRITES]


def _refused(r, fx, text):
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REFUSED: " in r.stdout and "Nothing was changed." in r.stdout and text in r.stdout, r.stdout + r.stderr
    assert _writes(fx.calls()) == [] and fx.rd() == "", fx.calls()


# ---------------------------------------------------------------------------------------------- the dry run


def test_dry_run_walks_every_step_in_the_operators_order(tmp_path):
    fx = Fx(tmp_path)
    r = fx.cut()
    out = r.stdout
    assert r.returncode == 0, out + r.stderr
    idx = [out.index(f"Step {n} OK") for n in range(1, 9)]
    assert idx == sorted(idx) and "CUTOVER DONE" in out
    # the order of the writes: disable, seed (before protect-main), protect-main, merge, enable, dispatch x2
    seq = [(c["method"], c["path"].rsplit("/", 1)[-1]) for c in _writes(fx.calls())]
    assert seq == [("PUT", "disable"), ("SCRIPT", "protect-main"), ("SCRIPT", "merge-reviewed"),
                   ("SCRIPT", "protect-main"), ("PUT", "enable"), ("POST", "dispatches"), ("POST", "dispatches")], seq
    pm = [c for c in fx.calls() if c["path"] == "protect-main"]
    assert [c["argv"] for c in pm] == [["--pre-cutover", "--apps", "none"], ["--check", "--apps", "none"]]
    # the pre-cutover run comes before the merge, the plain --check after it and before the workflow is on again
    names = [c["path"] for c in _writes(fx.calls())]
    assert names.index("protect-main") < names.index("merge-reviewed") < len(names) - 1 - names[::-1].index("protect-main")
    seed = re.search(r"Step 3 OK: records-data = seed ([0-9a-f]{40})", out).group(1)
    # F5: main is protected before the cutover merge; the seed was pushed before protect-main ran
    disable_i = next(i for i, c in enumerate(fx.calls()) if c["path"].endswith("/disable"))
    assert fx.calls()[disable_i]["records_data"] == "" and pm
    # the seed: parentless, data/ only, the pinned listing, which passes data_shape (the test that reads data/)
    assert fx.og("cat-file", "-p", seed).count("parent ") == 0
    assert fx.og("ls-tree", "--name-only", seed) == "data"
    listing = _git(tmp_path, "--git-dir", str(fx.origin), "ls-tree", "-r", "-z", seed, "--", "data")
    assert listing == fx.listing and hashlib.sha256(listing).hexdigest() == fx.digest
    assert data_shape.problems(listing) == []
    names = {e.split(b"\t", 1)[1].decode() for e in listing.split(b"\0") if e}
    assert names == {p for p in MAIN_DATA if p not in MOVED}
    # step 5: merge-reviewed got the PR, the reviewed sha and the report; main tracks no data/ after it
    mr = [c for c in fx.calls() if c["path"] == "merge-reviewed"][0]
    assert mr["argv"] == ["60", fx.head, "docs/reviews/x.md"]
    assert fx.og("ls-tree", "--name-only", "refs/heads/main", "--", "data") == ""
    # step 7 then 8: collect=false deployed the seed, collect=true moved records-data and it verified
    runs = [x for x in fx.state["runs"] if x.get("event") == "workflow_dispatch"]
    assert [x["collect"] for x in runs] == ["false", "true"]
    assert "build-info.json names the seed " + seed in out
    att = [c for c in fx.calls() if c["method"] == "ATTEST"][0]["argv"]
    for flag in ("--repo", REPO, "--cert-identity",
                 "https://github.com/gn0sh/clarksville-records/.github/workflows/daily-update.yml@refs/heads/main",
                 "--source-ref", "refs/heads/main", "--predicate-type", "https://slsa.dev/provenance/v1",
                 "--deny-self-hosted-runners"):
        assert flag in att, flag
    head = fx.rd()
    assert head != seed and fx.og("rev-parse", head + "^") == seed
    assert fx.cmd("--rollback --cutover-merge ") in out


def test_the_left_out_inputs_are_exactly_the_moved_ones(tmp_path):
    fx = Fx(tmp_path)
    r = fx.run(["--plan"])
    assert r.returncode == 0, r.stdout + r.stderr
    left = re.findall(r"left out \(the cutover PR has it at (config/\S+)\): (\S+)", r.stdout)
    assert sorted(p for _, p in left) == sorted(MOVED)
    assert all(c == "config/" + p[5:] for c, p in left)
    assert f"SEED DIGEST {fx.digest}" in r.stdout and "The cutover head pins this digest." in r.stdout
    assert f"BASELINE {fx.main}\n" in r.stdout and "The cutover head pins this baseline." in r.stdout
    assert re.search(rf"^{fx.main} PR #\d+ merged_by.type=User$", r.stdout, re.M) and "checked 1 commits" in r.stdout
    assert _writes(fx.calls()) == [] and fx.rd() == ""          # --plan: gh reads only, no push


def test_plan_reports_a_stale_baseline_pin(tmp_path):
    fx = Fx(tmp_path, baseline="1" * 40)
    r = fx.run(["--plan"])
    assert r.returncode == 1 and f"BASELINE {fx.main}" in r.stdout and "update MAIN_PR_BASELINE" in r.stdout
    assert "checked 1 commits" in r.stdout and _writes(fx.calls()) == []


def test_plan_reports_a_stale_pin(tmp_path):
    fx = Fx(tmp_path, pin="a" * 64)
    r = fx.run(["--plan"])
    assert r.returncode == 1 and f"SEED DIGEST {fx.digest}" in r.stdout and "update RECORDS_DATA_SEED_DIGEST" in r.stdout


def test_plan_runs_in_a_cloud_session(tmp_path):
    fx = Fx(tmp_path)
    r = fx.run(["--plan"], CLAUDE_CODE_REMOTE="true")
    assert r.returncode == 0, r.stdout + r.stderr


def test_prepare_untracks_data_ignores_it_and_deletes_codeowners(tmp_path):
    """The cutover PR's own change (B2's gate refuses a tracked data/): staged, never committed, files kept."""
    fx = Fx(tmp_path)
    w = fx.work
    _git(w, "checkout", "-q", "--detach", fx.main, env=fx.genv)
    r = fx.run(["--prepare"], CLAUDE_CODE_REMOTE="true")
    assert r.returncode == 0 and "PREPARED" in r.stdout, r.stdout + r.stderr
    assert _git(w, "ls-files", "--", "data", env=fx.genv) == b""
    assert subprocess.run(["git", "check-ignore", "-q", "data/"], cwd=w).returncode == 0
    assert _git(w, "ls-files", "--", ".github/CODEOWNERS", env=fx.genv) == b""
    assert (w / "data" / "facts.json").exists()                          # the files stay on disk
    assert _git(w, "rev-parse", "HEAD", env=fx.genv).decode().strip() == fx.main   # nothing committed
    staged = _git(w, "diff", "--cached", "--name-status", env=fx.genv).decode()
    assert "M\t.gitignore" in staged and "D\t.github/CODEOWNERS" in staged and "D\tdata/facts.json" in staged
    r = fx.run(["--prepare"])
    assert r.returncode == 0 and "already out of the index" in r.stdout and "already ignored" in r.stdout
    assert fx.calls() == []


def test_the_pin_is_the_sha256_of_the_gates_listing_bytes(tmp_path):
    """RECORDS_DATA_SEED_DIGEST = sha256 of `git ls-tree -r -z <seed> -- data` (the gate's data_listing)."""
    fx = Fx(tmp_path)
    r = fx.cut()
    seed = re.search(r"Step 3 OK: records-data = seed ([0-9a-f]{40})", r.stdout).group(1)
    raw = _git(tmp_path, "--git-dir", str(fx.origin), "ls-tree", "-r", "-z", seed, "--", "data")
    pin = re.search(r'RECORDS_DATA_SEED_DIGEST: "([0-9a-f]{64})"',
                    _git(fx.work, "show", fx.head + ":.github/workflows/daily-update.yml", env=fx.genv).decode()).group(1)
    assert hashlib.sha256(raw).hexdigest() == pin


def test_step1_refuses_a_cutover_head_that_does_not_ignore_data(tmp_path):
    fx = Fx(tmp_path, pr_extra={".gitignore": "build/\n"})
    _refused(fx.cut(), fx, "does not gitignore data/")


# ---------------------------------------------------------------------------------------------- step 1 refusals


@pytest.mark.parametrize("hm", ["0500", "0759", "0907", "1030"])
def test_step1_refuses_in_the_daily_window(tmp_path, hm):
    """data-off-main/window-vs-duration: from 05:00, so steps 7 and 8 can't meet the 09:07 cron."""
    fx = Fx(tmp_path)
    _refused(fx.cut(hm=hm), fx, "inside the daily run's window (05:00-10:30")


@pytest.mark.parametrize("hm", ["0459", "1031"])
def test_step1_allows_outside_the_window(tmp_path, hm):
    fx = Fx(tmp_path)
    assert fx.cut(hm=hm).returncode == 0


def test_step1_refuses_while_a_run_is_active(tmp_path):
    fx = Fx(tmp_path)
    fx.state["runs"].append({"id": 2, "status": "in_progress", "event": "schedule"})
    _refused(fx.cut(), fx, "a daily-update run is queued or in progress")


def test_step1_refuses_with_morning_note_send_set(tmp_path):
    fx = Fx(tmp_path)
    fx.state["vars"] = ["RECORDS_DEPLOY_ENABLED", "MORNING_NOTE_SEND"]
    _refused(fx.cut(), fx, "MORNING_NOTE_SEND is set")


def test_step1_a_403_on_the_variables_read_counts_as_set(tmp_path):
    fx = Fx(tmp_path)
    fx.state["refuse"] = [R + "/actions/variables?per_page=100"]
    _refused(fx.cut(), fx, "MORNING_NOTE_SEND is set, or the variables could not be read (counts as set)")


@pytest.mark.parametrize("var", CLOUD)
def test_refuses_in_a_cloud_session_or_ci(tmp_path, var):
    fx = Fx(tmp_path)
    _refused(fx.cut(**{var: "true"}), fx, f"{var} is set")
    r = fx.run(["--rollback"], **{var: "true"})
    assert r.returncode == 1 and f"{var} is set" in r.stdout and _writes(fx.calls()) == []


@pytest.mark.parametrize("change,text", [
    (lambda fx: {"user": {"login": "someone"}}, "authored by 'someone'"),
    (lambda fx: {"head": {"sha": "f" * 40, "repo": {"full_name": REPO}}}, "not the reviewed"),
    (lambda fx: {"head": {"sha": fx.head, "repo": {"full_name": "x/fork"}}}, "branch is in 'x/fork'"),
    (lambda fx: {"state": "closed"}, "is not open into main"),
    (lambda fx: {"draft": True}, "is a draft"),
], ids=["author", "head", "fork", "closed", "draft"])
def test_step1_refuses_a_pr_that_is_not_the_reviewed_one(tmp_path, change, text):
    fx = Fx(tmp_path)
    fx.state["pr"].update(change(fx))
    _refused(fx.cut(), fx, text)


@pytest.mark.parametrize("apps", ["", "Claude", "claude,other", "other-app", "none,claude", "x;y"])
def test_step1_refuses_unless_apps_is_claude_or_none(tmp_path, apps):
    """ADR 0011 Amendment (b): Brian's installations hand check is claude or none; anything else stops at once."""
    fx = Fx(tmp_path)
    r = fx.cut(apps=apps)
    _refused(r, fx, "--apps must be claude or none: first open https://github.com/settings/installations")


def test_step1_refuses_without_apps(tmp_path):
    fx = Fx(tmp_path)
    r = fx.run(["--pr", "60", "--sha", fx.head, "--report", "x"])
    _refused(r, fx, "--apps must be claude or none")


def test_the_apps_answer_reaches_protect_main(tmp_path):
    fx = Fx(tmp_path)
    r = fx.cut(apps="claude", STUB_PM="notok")
    assert "by Brian's hand check at https://github.com/settings/installations: claude." in r.stdout
    assert [c["argv"] for c in fx.calls() if c["path"] == "protect-main"] == [["--pre-cutover", "--apps", "claude"]]


def test_step5_stops_when_the_plain_check_after_the_merge_is_not_ok(tmp_path):
    """After the merge, protect-main runs without --pre-cutover (main's new workflow) and must print OK."""
    fx = Fx(tmp_path)
    r = fx.cut(STUB_PM_CHECK="notok")
    assert r.returncode == 2 and "STOPPED at step 5" in r.stdout and "protect-main --check did not print OK" in r.stdout
    assert [c["argv"] for c in fx.calls() if c["path"] == "protect-main"][-1] == ["--check", "--apps", "none"]
    assert fx.state["wf_state"] == "disabled_manually"           # step 6 never ran
    assert fx.cmd("Undo with: bash scripts/cutover-data-off-main.sh --rollback --cutover-merge ") in r.stdout


def test_step1_refuses_a_checkout_not_at_the_reviewed_head(tmp_path):
    fx = Fx(tmp_path)
    (fx.work / "README").write_text("x")
    _git(fx.work, "add", "README", env=fx.genv)
    _refused(fx.cut(), fx, "this checkout has local changes")


def test_step1_refuses_a_pin_that_differs_from_the_seed(tmp_path):
    fx = Fx(tmp_path, pin="a" * 64)
    _refused(fx.cut(), fx, "but the PR pins " + "a" * 64)


def test_step1_refuses_an_existing_records_data_that_is_not_the_seed(tmp_path):
    fx = Fx(tmp_path)
    fx.og("update-ref", "refs/heads/records-data", fx.main)
    r = fx.cut()
    assert r.returncode == 1 and "records-data already exists at" in r.stdout and _writes(fx.calls()) == []


# ---------------------------------------------------------------------------------------------- step 1: baseline and window


def test_step1_prints_the_window_listing_for_the_record(tmp_path):
    fx = Fx(tmp_path)
    r = fx.cut()
    assert r.returncode == 0, r.stdout + r.stderr
    w = r.stdout[r.stdout.index("Window (runbook 4.7.1)"):r.stdout.index("Step 1 OK")]
    assert f"from {fx.start} to {fx.main}:" in w
    assert re.search(rf"^{fx.main} PR #\d+ merged_by.type=User$", w, re.M) and "checked 1 commits" in w
    assert w.index("checked 1 commits") < r.stdout.index("Step 1 OK")


def test_the_shipped_window_start_is_mains_sha_before_the_ruleset():
    """4c5cd910 (PR #31): main when ruleset 27502319 was created (2026-11-17T22:21:09Z); see the D3 notes."""
    start = "4c5cd91022b74f5b7ad68ec94cdb863fcc444acd"
    assert re.search(rf"(?m)^WINDOW_START={start}$", SH.read_text(encoding="utf-8"))
    assert f"$WINDOW_START = '{start}'" in PS1.read_text(encoding="utf-8")
    for s in ("3ef440aea9e5ce7374cdb789a05d646d74a91ac3", "2b207042a53e4d11dadfee978b029392df63c376",
              ".github/workflows/v1-canary.yml", "KNOWN EXCEPTION: ", "checked ", "merged_by.type=",
              "--is-ancestor", ":(exclude)data/", "--first-parent"):
        assert s in SH.read_text(encoding="utf-8") and s in PS1.read_text(encoding="utf-8"), s


@pytest.mark.parametrize("baseline,text", [
    ("1" * 40, "but the cutover PR pins MAIN_PR_BASELINE " + "1" * 40),
    ("", "pins no single 40-hex MAIN_PR_BASELINE"),
    ("main~", "pins no single 40-hex MAIN_PR_BASELINE"),
], ids=["other-sha", "empty", "not-hex"])
def test_step1_refuses_unless_main_equals_the_pinned_baseline(tmp_path, baseline, text):
    fx = Fx(tmp_path, baseline=baseline)
    _refused(fx.cut(), fx, text)


def test_step1_refuses_a_pr_head_that_does_not_contain_main(tmp_path):
    """main-protect/r2-on-without-codeowners fix (a): the squash must not leave a later main's data/ tracked."""
    fx = Fx(tmp_path, pr_off_main=True)
    _refused(fx.cut(), fx, f"does not contain main {fx.main}")


@pytest.mark.parametrize("window,text", [
    ("", "the window start '' is not a 40-hex sha"),
    ("f" * 40, "is not an ancestor of main"),
    (None, "no commit in the window"),             # start = main: N = 0
], ids=["empty", "not-ancestor", "n0"])
def test_step1_refuses_a_bad_window_start(tmp_path, window, text):
    fx = Fx(tmp_path, window=window if window is not None else "MAIN")
    if window is None:   # main's sha is known only after the fixture's commit: edit the copy, hide it from status
        fx.set_window(fx.main)
        _git(fx.work, "update-index", "--assume-unchanged", "scripts/" + fx.script.name, env=fx.genv)
    _refused(fx.cut(), fx, text)


@pytest.mark.parametrize("how,text", [
    ("bot", "was not merged by a person (merged_by.type=Bot)"),
    ("no_pr", "was not merged by a person (merged_by.type=none)"),
    ("refuse", "could not read the pull requests of"),
], ids=["unknown-bot", "no-pr", "read-refused"])
def test_step1_window_stops_on_a_bot_no_pr_or_a_refused_read(tmp_path, how, text):
    fx = Fx(tmp_path)
    if how == "refuse":
        fx.state["refuse"] = [R + "/commits/" + fx.main + "/pulls"]
    else:
        fx.state[how] = [fx.main]
    _refused(fx.cut(), fx, text)


# ---------------------------------------------------------------------------------------------- step 3 stops (I-in, phones)

BAD_SEEDS = {
    "transcripts": ({"data/localities/clarksville-tn/meetings/transcripts/b.json": "{}\n"}, (),
                    "under a transcripts/ folder, data/maps/ or a curated name"),
    "maps": ({"data/maps/extra.json": "{}\n"}, (), "under a transcripts/ folder, data/maps/ or a curated name"),
    "maps-not-moved": ({}, ("data/maps/manifest.json",), "under a transcripts/ folder, data/maps/ or a curated name"),
    "phone": ({"data/localities/cmc-rpc/rpc.json": json.dumps(RPC_PHONE)}, (), "has a phone number in a case location"),
}


@pytest.mark.parametrize("case", sorted(BAD_SEEDS))
def test_the_seed_checks_stop_before_anything_changes(tmp_path, case):
    extra, skip, text = BAD_SEEDS[case]
    fx = Fx(tmp_path, main_extra=extra, skip_config=skip)
    _refused(fx.cut(), fx, text)


@pytest.mark.parametrize("extra", [{"data/late.json": "{}\n"}, BAD_SEEDS["transcripts"][0]], ids=["data", "transcripts"])
def test_step3_stops_when_main_moved_after_step1(tmp_path, extra):
    """main gains a commit between step 1 and step 3: it is off the PR's MAIN_PR_BASELINE, so step 3 stops, pushes
    nothing (Amendment (c): the squash's parent must be the pinned baseline)."""
    fx = Fx(tmp_path)
    late = tmp_path / "late"
    _git(tmp_path, "clone", "-q", "-b", "main", str(fx.origin), str(late), env=fx.genv)
    _write(late, extra)
    fx.state["on_disable"] = [f"cd {late} && git add -A && git -c user.name=g -c user.email=g@x commit -q -m late "
                              f"&& git push -q origin HEAD:main"]
    r = fx.cut()
    assert r.returncode == 2 and "STOPPED at step 3" in r.stdout and "off the PR's MAIN_PR_BASELINE " + fx.main in r.stdout
    assert fx.cmd("Undo with: bash scripts/cutover-data-off-main.sh --rollback\n") in r.stdout
    assert fx.rd() == "" and [c["path"] for c in _writes(fx.calls())] == [R + "/actions/workflows/daily-update.yml/disable"]


def test_step2_stops_when_a_run_started_before_the_disable(tmp_path):
    fx = Fx(tmp_path)
    fx.state["run_starts_on_disable"] = True
    r = fx.cut()
    assert r.returncode == 2 and "STOPPED at step 2" in r.stdout and fx.cmd("--rollback") in r.stdout and fx.rd() == ""


def test_step4_stops_unless_protect_main_prints_ok(tmp_path):
    fx = Fx(tmp_path)
    r = fx.cut(STUB_PM="notok")
    assert r.returncode == 2 and "STOPPED at step 4" in r.stdout and "protect-main did not print OK" in r.stdout
    assert not [c for c in fx.calls() if c["path"] == "merge-reviewed"]
    assert fx.cmd("Undo with: bash scripts/cutover-data-off-main.sh --rollback\n") in r.stdout


def test_step5_stops_unless_the_merge_is_a_bypass(tmp_path):
    fx = Fx(tmp_path)
    r = fx.cut(STUB_MR="pass")
    assert r.returncode == 2 and "STOPPED at step 5" in r.stdout and "bypass" in r.stdout
    assert fx.state["wf_state"] == "disabled_manually"
    # data-off-main/undo-line-after-merge: main moved in the call, so the undo names the new main
    undo = fx.cmd("Undo with: bash scripts/cutover-data-off-main.sh --rollback --cutover-merge ")
    assert undo + fx.og("rev-parse", "refs/heads/main") in r.stdout


def test_step5_undo_names_the_new_main_when_the_merge_output_is_not_understood(tmp_path):
    fx = Fx(tmp_path)
    r = fx.cut(STUB_MR="garbled")
    assert r.returncode == 2 and "STOPPED at step 5" in r.stdout
    undo = fx.cmd("Undo with: bash scripts/cutover-data-off-main.sh --rollback --cutover-merge ")
    assert undo + fx.og("rev-parse", "refs/heads/main") in r.stdout


def test_step5_stops_when_the_squash_parent_is_not_the_pinned_baseline(tmp_path):
    fx = Fx(tmp_path)
    r = fx.cut(STUB_MR_MOVE="1")
    m = fx.og("rev-parse", "refs/heads/main")
    assert r.returncode == 2 and "STOPPED at step 5" in r.stdout and f"not the pinned MAIN_PR_BASELINE {fx.main}" in r.stdout
    assert fx.cmd(f"Undo with: bash scripts/cutover-data-off-main.sh --rollback --cutover-merge {m}") in r.stdout
    assert fx.state["wf_state"] == "disabled_manually"


@pytest.mark.parametrize("over", [{"gate_log": "verified=false\n"}, {"gate_n": 2}, {"gate": "failure"}],
                         ids=["unverified", "two-commits", "gate-failed"])
def test_step7_stops_unless_the_gate_verified_exactly_one_commit(tmp_path, over):
    fx = Fx(tmp_path)
    fx.state.update(over)
    r = fx.cut()
    assert r.returncode == 2 and "STOPPED at step 7" in r.stdout and "gate did not verify exactly the cutover commit" in r.stdout
    assert fx.cmd("Undo with: bash scripts/cutover-data-off-main.sh --rollback --cutover-merge ") in r.stdout
    assert [x["collect"] for x in fx.state["runs"] if x.get("event") == "workflow_dispatch"] == ["false"]


def test_step7_stops_when_the_deploy_did_not_succeed(tmp_path):
    fx = Fx(tmp_path)
    fx.state["deploy"] = "skipped"
    r = fx.cut()
    assert r.returncode == 2 and "STOPPED at step 7" in r.stdout and "'skipped', not success" in r.stdout
    assert fx.cmd("--rollback --cutover-merge ") in r.stdout.split("STOPPED")[1]


def test_step8_stops_when_records_data_is_not_attested(tmp_path):
    fx = Fx(tmp_path)
    fx.state["attest"] = False
    r = fx.cut()
    assert r.returncode == 2 and "STOPPED at step 8" in r.stdout and "is not attested" in r.stdout


def test_step8_stops_when_records_data_did_not_move(tmp_path):
    fx = Fx(tmp_path)
    fx.state["collect_moves"] = False
    r = fx.cut()
    assert r.returncode == 2 and "STOPPED at step 8" in r.stdout and "still a parentless commit" in r.stdout


def test_a_rerun_keeps_an_existing_seed(tmp_path):
    fx = Fx(tmp_path)
    r = fx.cut(STUB_PM="notok")
    seed = fx.rd()
    assert r.returncode == 2 and seed
    fx.state["wf_state"] = "active"
    open(tmp_path / "calls", "w").close()
    r = fx.cut()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "records-data already is this seed" in r.stdout and f"records-data = seed {seed}" in r.stdout


# ---------------------------------------------------------------------------------------------- --rollback


@pytest.mark.parametrize("var", ["MORNING_NOTE_SEND", "MAIN_PR_BASELINE"])
def test_rollback_refuses_with_each_variable_set(tmp_path, var):
    fx = Fx(tmp_path)
    fx.state["vars"] = [var]
    r = fx.run(["--rollback"])
    assert r.returncode == 1 and f"{var} is set" in r.stdout and "Nothing was changed." in r.stdout
    assert _writes(fx.calls()) == []


def test_rollback_a_403_on_the_variables_read_counts_as_set(tmp_path):
    fx = Fx(tmp_path)
    fx.state["refuse"] = [R + "/actions/variables?per_page=100"]
    r = fx.run(["--rollback"])
    assert r.returncode == 1 and "could not be read (counts as set)" in r.stdout and _writes(fx.calls()) == []


def _commit_on(fx, ref, files, msg, push_to=None):
    """A commit on origin's <ref> with <files> written (None deletes); pushed to <push_to> (default: ref). Its sha."""
    d = fx.tmp / ("c-" + hashlib.sha1((ref + msg).encode()).hexdigest()[:8])
    _git(fx.tmp, "clone", "-q", str(fx.origin), str(d), env=fx.genv)
    co = "origin/" + ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
    _git(d, "checkout", "-q", "--detach", co, env=fx.genv)
    for rel, text in files.items():
        p = d / rel
        if text is None:
            _git(d, "rm", "-q", "-r", rel, env=fx.genv)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
    _git(d, "add", "-A", "-f", "--", *[r for r, t in files.items() if t is not None], env=fx.genv)
    _git(d, "commit", "-q", "-m", msg, env=fx.genv)
    c = _git(d, "rev-parse", "HEAD", env=fx.genv).decode().strip()
    _git(d, "push", "-q", "-f", "origin", f"HEAD:{push_to or ref}", env=fx.genv)
    return c


SET_WF = OLD_WF.replace('MAIN_PR_BASELINE: ""', 'MAIN_PR_BASELINE: "' + "1" * 40 + '"')


def test_rollback_refuses_while_mains_workflow_sets_the_baseline(tmp_path):
    """Before the cutover merge: main's workflow must hold one empty MAIN_PR_BASELINE (F4), checked at entry."""
    fx = Fx(tmp_path)
    _commit_on(fx, "refs/heads/main", {".github/workflows/daily-update.yml": SET_WF}, "baseline", "refs/heads/main")
    r = fx.run(["--rollback"])
    assert r.returncode == 1 and "workflow sets MAIN_PR_BASELINE" in r.stdout and _writes(fx.calls()) == []


def test_rollback_without_the_merge_sha_refuses_when_main_has_no_codeowners(tmp_path):
    """main-protect/r2-on-without-codeowners: a squash over a later data commit leaves main tracking data/ with
    CODEOWNERS gone. The rollback never picks the early path (R2 on) by data/ alone."""
    fx = Fx(tmp_path)
    r = fx.cut()
    assert r.returncode == 0
    merge = re.search(fx.cmd("--rollback --cutover-merge ") + "([0-9a-f]{40})", r.stdout).group(1)
    _commit_on(fx, "refs/heads/main", {"data/late.json": "{}\n"}, "late data", "refs/heads/main")
    assert fx.og("ls-tree", "--name-only", "refs/heads/main", "--", "data") == "data"
    fx.state["r2"] = False
    open(tmp_path / "calls", "w").close()
    for extra in ([], ["--cutover-merge", "e" * 40]):              # absent, or not on main
        r = fx.run(["--rollback", *extra])
        assert r.returncode == 1 and "has no .github/CODEOWNERS" in r.stdout and "--cutover-merge <sha>" in r.stdout
        assert _writes(fx.calls()) == [] and fx.state["r2"] is False
    # with the merge sha it opens the restore PR, whose data/ is records-data's (main's late file replaced)
    r = fx.run(["--rollback", "--cutover-merge", merge])
    assert r.returncode == 0 and "ROLLBACK PR #99 opened" in r.stdout, r.stdout + r.stderr
    c = re.search(r"pushed branch \S+ at ([0-9a-f]{40})", r.stdout).group(1)
    assert fx.og("rev-parse", c + ":data") == fx.og("rev-parse", fx.rd() + ":data")
    assert fx.og("show", c + ":.github/CODEOWNERS") == CODEOWNERS.strip() and fx.state["r2"] is False


def test_rollback_open_refuses_when_the_commit_before_the_merge_sets_the_baseline(tmp_path):
    """main-protect/f4-wrong-workflow, call 1: R restores the workflow of the merge's parent, so that one is checked."""
    fx = Fx(tmp_path)
    x = _commit_on(fx, "refs/heads/main", {".github/workflows/daily-update.yml": SET_WF}, "set", "refs/heads/main")
    y = _commit_on(fx, x, {"data": None, ".github/CODEOWNERS": None}, "a cutover-like squash", "refs/heads/main")
    r = fx.run(["--rollback", "--cutover-merge", y])
    assert r.returncode == 1 and "the commit before the cutover merge" in r.stdout and "MAIN_PR_BASELINE" in r.stdout
    assert _writes(fx.calls()) == []


@pytest.mark.parametrize("case", ["tracks-data", "has-codeowners"])
def test_rollback_open_refuses_a_cutover_merge_sha_that_is_not_the_cutover_merge(tmp_path, case):
    """main-protect/rollback-cutover-merge-unverified: the --cutover-merge sha itself must track no data/ and hold no
    .github/CODEOWNERS (the cutover squash), not just have a parent that passes."""
    fx = Fx(tmp_path)
    if case == "tracks-data":            # before the cutover: a later commit on main whose parent M passes
        y = _commit_on(fx, "refs/heads/main", {"README": "y\n"}, "later", "refs/heads/main")
        text = y + " tracks data/: that is not the cutover merge"
    else:                                # after the cutover: a commit that puts CODEOWNERS back, data/ still off main
        assert fx.cut().returncode == 0
        y = _commit_on(fx, "refs/heads/main", {".github/CODEOWNERS": CODEOWNERS}, "codeowners", "refs/heads/main")
        text = y + " holds .github/CODEOWNERS: that is not the cutover merge"
    open(tmp_path / "calls", "w").close()
    r = fx.run(["--rollback", "--cutover-merge", y])
    assert r.returncode == 1 and text in r.stdout and "Nothing was changed." in r.stdout, r.stdout + r.stderr
    assert _writes(fx.calls()) == []


@pytest.mark.parametrize("hm,minutes", [("0430", 269), ("0459", 240), ("0300", 359), ("1400", 360), ("2330", 360)])
def test_step8_waits_at_most_until_before_0900_utc(tmp_path, hm, minutes):
    """data-off-main/window-vs-duration: step 8's wait is capped so it ends before 09:00 UTC (the 09:07 run)."""
    fx = Fx(tmp_path)
    r = fx.cut(hm=hm)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"Step 8: waiting up to {minutes} minutes, so the wait ends before 09:00 UTC" in r.stdout
    assert 'fail "run $id did not complete within $w minutes, and the wait ends before 09:00 UTC' in SH.read_text()


def _opened_restore(fx):
    r = fx.cut()
    assert r.returncode == 0, r.stdout + r.stderr
    merge = re.search(fx.cmd("--rollback --cutover-merge ") + "([0-9a-f]{40})", r.stdout).group(1)
    fx.state["r2"] = False
    r = fx.run(["--rollback", "--cutover-merge", merge])
    assert r.returncode == 0, r.stdout + r.stderr
    br, c = re.search(r"pushed branch (rollback/data-on-main-\S+) at ([0-9a-f]{40})", r.stdout).groups()
    open(fx.tmp / "calls", "w").close()
    return merge, br, c


def test_rollback_merge_refuses_a_restore_head_that_sets_the_baseline(tmp_path):
    """main-protect/f4-wrong-workflow, call 2: R's head is checked before anything changes."""
    fx = Fx(tmp_path)
    merge, br, c = _opened_restore(fx)
    c2 = _commit_on(fx, c, {".github/workflows/daily-update.yml": SET_WF}, "set", "refs/pull/99/head")
    r = fx.run(["--rollback", "--merge", "99", "--sha", c2, "--cutover-merge", merge, "--report", "x"])
    assert r.returncode == 1 and "the restore PR #99 at " + c2 in r.stdout and "MAIN_PR_BASELINE" in r.stdout
    assert _writes(fx.calls()) == [] and fx.state["r2"] is False
    # pull/99/head is c2 now
    r = fx.run(["--rollback", "--merge", "99", "--sha", c, "--cutover-merge", merge, "--report", "x"])
    assert r.returncode == 1 and "origin's pull/99/head is not " + c in r.stdout and _writes(fx.calls()) == []


@pytest.mark.parametrize("files,text", [
    ({".github/CODEOWNERS": None}, "does not hold the restore PR's .github/CODEOWNERS"),
    ({".github/workflows/daily-update.yml": SET_WF}, "does not hold the restore PR's .github/workflows/daily-update.yml"),
    ({"data/facts.json": '{"meetings": [1]}\n'}, "does not hold the restore PR's data"),          # S1-3
], ids=["no-codeowners", "other-workflow", "other-data"])
def test_rollback_merge_keeps_r2_off_unless_main_holds_rs_files(tmp_path, files, text):
    """main-protect/rollback-r2-unchecked-codeowners and Amendment (c) item 7: after R merges, main must hold R's
    workflow and CODEOWNERS byte for byte (one empty baseline) before R1' or R2 change."""
    fx = Fx(tmp_path)
    merge, br, c = _opened_restore(fx)
    other = _commit_on(fx, c, files, "drift", "refs/heads/other")
    r = fx.run(["--rollback", "--merge", "99", "--sha", c, "--cutover-merge", merge, "--report", "x"], STUB_MR_TREE=other)
    assert r.returncode == 2 and "STOPPED at step 4" in r.stdout and text in r.stdout and "R2 stays off" in r.stdout
    seq = [x["path"].rsplit("/", 1)[-1] for x in _writes(fx.calls())]
    assert seq == ["disable", "merge-reviewed"], seq
    assert fx.state["r2"] is False and fx.state["wf_state"] == "disabled_manually"


def _cut_then_unattested_push(fx):
    """A full cutover, then a writer fast-forwards records-data with a tree no run attested (S1-3's case)."""
    r = fx.cut()
    assert r.returncode == 0, r.stdout + r.stderr
    merge = re.search(fx.cmd("--rollback --cutover-merge ") + "([0-9a-f]{40})", r.stdout).group(1)
    good = fx.rd()
    bad = _commit_on(fx, "refs/heads/records-data", {"data/facts.json": '{"meetings": ["forged"]}\n'}, "forged",
                     "refs/heads/records-data")
    fx.state["r2"] = False
    open(fx.tmp / "calls", "w").close()
    return merge, good, bad


def test_s1_3_rollback_refuses_an_unattested_records_data_head(tmp_path):
    """data-off-main/rollback-unverified-data: the open path checks I-prov on records-data's head first."""
    fx = Fx(tmp_path)
    merge, good, bad = _cut_then_unattested_push(fx)
    r = fx.run(["--rollback", "--cutover-merge", merge])
    assert r.returncode == 1 and f"records-data's head {bad} is neither attested by daily-update.yml on main nor the " \
        "pinned seed (S1-3)" in r.stdout and fx.cmd(f"--cutover-merge {merge} --data-from <sha>") in r.stdout, r.stdout
    assert _writes(fx.calls()) == [] and fx.state["wf_state"] == "active"


def test_s1_3_data_from_an_attested_ancestor_opens_r_with_that_tree_and_merges(tmp_path):
    fx = Fx(tmp_path)
    merge, good, bad = _cut_then_unattested_push(fx)
    r = fx.run(["--rollback", "--cutover-merge", merge, "--data-from", good])
    assert r.returncode == 0 and "ROLLBACK PR #99 opened" in r.stdout, r.stdout + r.stderr
    assert f"R's data/ comes from records-data {good}: attested by daily-update.yml on main." in r.stdout
    c = re.search(r"pushed branch \S+ at ([0-9a-f]{40})", r.stdout).group(1)
    assert fx.og("rev-parse", c + ":data") == fx.og("rev-parse", good + ":data") != fx.og("rev-parse", bad + ":data")
    open(tmp_path / "calls", "w").close()
    r = fx.run(["--rollback", "--merge", "99", "--sha", c, "--cutover-merge", merge, "--report", "x"])
    assert r.returncode == 0 and "its data/ is attested by daily-update.yml on main." in r.stdout, r.stdout + r.stderr
    assert "holds R's workflow, .github/CODEOWNERS and data/ byte for byte" in r.stdout and fx.state["r2"] is True


@pytest.mark.parametrize("which,text", [
    ("bad", "is neither attested by daily-update.yml on main nor the pinned seed (S1-3)"),
    ("off", "is not on records-data (not an ancestor of its head"),
    ("short", "--data-from needs a 40-hex sha on records-data"),
], ids=["unattested", "not-an-ancestor", "not-a-sha"])
def test_s1_3_data_from_must_be_an_attested_ancestor(tmp_path, which, text):
    fx = Fx(tmp_path)
    merge, good, bad = _cut_then_unattested_push(fx)
    pick = {"bad": bad, "off": fx.main, "short": good[:12]}[which]
    r = fx.run(["--rollback", "--cutover-merge", merge, "--data-from", pick])
    assert r.returncode == 1 and text in r.stdout and _writes(fx.calls()) == [], r.stdout


def test_s1_3_the_pinned_seed_is_accepted_as_r_data(tmp_path):
    """Before any run pushed (a stop at step 7), records-data is the seed: not attested, but the pinned seed."""
    fx = Fx(tmp_path)
    fx.state["deploy"] = "skipped"
    r = fx.cut()
    assert r.returncode == 2 and "STOPPED at step 7" in r.stdout
    merge = re.search(fx.cmd("--rollback --cutover-merge ") + "([0-9a-f]{40})", r.stdout).group(1)
    seed = fx.rd()
    assert fx.og("cat-file", "-p", seed).count("parent ") == 0
    r = fx.run(["--rollback", "--cutover-merge", merge])
    assert r.returncode == 0 and f"R's data/ comes from records-data {seed}: the pinned seed (RECORDS_DATA_SEED_DIGEST " \
        f"{fx.digest})." in r.stdout, r.stdout + r.stderr


def test_s1_3_merge_refuses_a_restore_pr_whose_data_is_not_verified(tmp_path):
    fx = Fx(tmp_path)
    merge, br, c = _opened_restore(fx)
    c2 = _commit_on(fx, c, {"data/facts.json": '{"meetings": ["forged"]}\n'}, "forged", "refs/pull/99/head")
    r = fx.run(["--rollback", "--merge", "99", "--sha", c2, "--cutover-merge", merge, "--report", "x"])
    assert r.returncode == 1 and "the restore PR #99's data/ (listing sha256 " in r.stdout
    assert "is neither attested by daily-update.yml on main nor the pinned seed (S1-3)" in r.stdout
    assert _writes(fx.calls()) == [] and fx.state["r2"] is False


def _listing_digest(fx, rev):
    out = subprocess.run(["git", "--git-dir", str(fx.origin), "ls-tree", "-r", "-z", rev, "--", "data"],
                         capture_output=True, check=True).stdout
    return hashlib.sha256(out).hexdigest()


def test_n1_merge_refuses_when_rs_parent_re_pins_the_seed_digest(tmp_path):
    """data-off-main/rollback-seedpin-untrusted (N1): R is opened as X1 (forged data/), X2 (the workflow pins X1's
    listing as RECORDS_DATA_SEED_DIGEST), then a head that restores R's workflow. The pin is read from main, never
    from R's parent, so the forged data/ is neither the pinned seed nor attested."""
    fx = Fx(tmp_path)
    merge, br, c = _opened_restore(fx)
    x1 = _commit_on(fx, c, {"data/facts.json": '{"meetings": ["forged"]}\n'}, "x1", "refs/heads/x1")
    forged = _listing_digest(fx, x1)
    wf = OLD_WF + '      RECORDS_DATA_SEED_DIGEST: "%s"   # re-pinned\n' % forged
    x2 = _commit_on(fx, x1, {".github/workflows/daily-update.yml": wf}, "x2", "refs/heads/x2")
    h = _commit_on(fx, x2, {".github/workflows/daily-update.yml": OLD_WF}, "head", "refs/pull/99/head")
    wfp = ":.github/workflows/daily-update.yml"
    assert fx.og("rev-parse", h + wfp) == fx.og("rev-parse", c + wfp)
    r = fx.run(["--rollback", "--merge", "99", "--sha", h, "--cutover-merge", merge, "--report", "x"])
    assert r.returncode == 1 and f"(listing sha256 {forged}) is neither attested" in r.stdout, r.stdout + r.stderr
    assert _writes(fx.calls()) == [] and fx.state["r2"] is False and "REFUSED: " in r.stdout


def test_n1_merge_refuses_a_restore_pr_whose_parent_is_not_on_main(tmp_path):
    """N1: R's head must be one commit on main's first-parent line, so the squash hides no other commit. Here R's data/
    is the verified tree and its workflow is right, but its parent is a side commit."""
    fx = Fx(tmp_path)
    merge, br, c = _opened_restore(fx)
    y = _commit_on(fx, c, {"notes.txt": "side\n"}, "side", "refs/heads/side")
    h = _commit_on(fx, y, {"notes2.txt": "head\n"}, "head", "refs/pull/99/head")
    r = fx.run(["--rollback", "--merge", "99", "--sha", h, "--cutover-merge", merge, "--report", "x"])
    assert r.returncode == 1 and f"the restore PR #99's parent {y} is not on main's first-parent line" in r.stdout, \
        r.stdout + r.stderr
    assert _writes(fx.calls()) == [] and fx.state["r2"] is False and "REFUSED: " in r.stdout


def test_n1_merge_accepts_the_seed_pinned_on_main(tmp_path):
    """The happy path with the seed as R's data/: the pin comes from main's workflow (the cutover merge's)."""
    fx = Fx(tmp_path)
    fx.state["deploy"] = "skipped"
    r = fx.cut()
    assert r.returncode == 2 and "STOPPED at step 7" in r.stdout
    merge = re.search(fx.cmd("--rollback --cutover-merge ") + "([0-9a-f]{40})", r.stdout).group(1)
    fx.state["r2"] = False
    r = fx.run(["--rollback", "--cutover-merge", merge])
    assert r.returncode == 0, r.stdout + r.stderr
    c = re.search(r"pushed branch \S+ at ([0-9a-f]{40})", r.stdout).group(1)
    assert not re.search(r"(?m)^\s*RECORDS_DATA_SEED_DIGEST:", fx.og("show", c + ":.github/workflows/daily-update.yml"))
    open(tmp_path / "calls", "w").close()
    r = fx.run(["--rollback", "--merge", "99", "--sha", c, "--cutover-merge", merge, "--report", "x"])
    assert r.returncode == 0 and f"its data/ is the pinned seed (RECORDS_DATA_SEED_DIGEST {fx.digest})" in r.stdout, \
        r.stdout + r.stderr
    assert "ROLLBACK DONE" in r.stdout and fx.state["r2"] is True


def _amend(fx, rev, files, push_to):
    """<rev> amended with <files> written (same parent): its sha, pushed to <push_to>."""
    d = fx.tmp / ("a-" + hashlib.sha1((rev + push_to).encode()).hexdigest()[:8])
    _git(fx.tmp, "clone", "-q", str(fx.origin), str(d), env=fx.genv)
    _git(d, "fetch", "-q", "origin", rev, env=fx.genv)
    _git(d, "checkout", "-q", "--detach", rev, env=fx.genv)
    _write(d, files)
    _git(d, "add", "-A", "-f", "--", *files, env=fx.genv)
    _git(d, "commit", "-q", "--amend", "--no-edit", env=fx.genv)
    c = _git(d, "rev-parse", "HEAD", env=fx.genv).decode().strip()
    _git(d, "push", "-q", "-f", "origin", f"HEAD:{push_to}", env=fx.genv)
    return c


@pytest.mark.parametrize("files,what", [
    ({".github/workflows/daily-update.yml": OLD_WF + "      EXTRA: \"1\"\n"}, ".github/workflows/daily-update.yml"),
    ({".github/CODEOWNERS": "* @someone-else\n"}, ".github/CODEOWNERS"),
], ids=["workflow", "codeowners"])
def test_t_r3_merge_refuses_a_workflow_or_codeowners_not_from_before_the_cutover(tmp_path, files, what):
    """Trust roots T-R3: R's parent is on main and its data/ is verified, but its workflow (one empty baseline, so
    restore_ok passes) or CODEOWNERS is not the pre-cutover one. The expected blobs come from main, never from R."""
    fx = Fx(tmp_path)
    merge, br, c = _opened_restore(fx)
    h = _amend(fx, c, files, "refs/pull/99/head")
    assert fx.og("rev-parse", h + "^1") == fx.og("rev-parse", c + "^1")
    r = fx.run(["--rollback", "--merge", "99", "--sha", h, "--cutover-merge", merge, "--report", "x"])
    assert r.returncode == 1 and f"the restore PR #99's {what} (blob " in r.stdout, r.stdout + r.stderr
    assert f"is not the one before the cutover merge {merge}" in r.stdout
    assert _writes(fx.calls()) == [] and fx.state["r2"] is False


@pytest.mark.parametrize("which,text", [
    ("none", "--merge needs <R> --sha <reviewed head> --cutover-merge <sha> --report <review>"),
    ("off", "is not on main's first-parent line"),
    ("parent", "tracks data/: that is not the cutover merge"),
], ids=["missing", "not-on-main", "not-the-cutover-merge"])
def test_t_r3_merge_needs_the_cutover_merge_on_main(tmp_path, which, text):
    fx = Fx(tmp_path)
    merge, br, c = _opened_restore(fx)
    extra = {"none": [], "off": ["--cutover-merge", fx.head],
             "parent": ["--cutover-merge", fx.og("rev-parse", merge + "^1")]}
    r = fx.run(["--rollback", "--merge", "99", "--sha", c, *extra[which], "--report", "x"])
    assert r.returncode == 1 and text in r.stdout, r.stdout + r.stderr
    assert _writes(fx.calls()) == [] and fx.state["r2"] is False


# ---------------------------------------------------------------------------------------------- security review e4bae340


def test_m1_rollback_refuses_when_the_fetch_of_main_fails(tmp_path):
    """data-off-main/ps-fetchmain-stale (M1): a failed fetch never falls back to a stale refs/cutover/main (here one
    left by the cutover run, at the commit before a later main)."""
    fx = Fx(tmp_path)
    fx.cut(STUB_PM="notok")
    stale = fx.og("rev-parse", "refs/heads/main")
    assert _git(fx.work, "rev-parse", "refs/cutover/main", env=fx.genv).decode().strip() == stale
    before = dict(fx.state)
    open(tmp_path / "calls", "w").close()
    gone = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "url.%s.insteadOf" % (tmp_path / "gone.git"),
            "GIT_CONFIG_VALUE_0": str(fx.origin)}   # origin's url now points nowhere: the fetch fails
    r = fx.run(["--rollback"], **gone)
    assert r.returncode == 1 and "REFUSED: could not fetch main from origin. Nothing was changed." in r.stdout, \
        r.stdout + r.stderr
    assert _writes(fx.calls()) == [] and fx.state == before


def test_m1_ps1_fetchmain_returns_null_on_a_failed_fetch_and_no_git_exit_code_is_dropped():
    """Without PWSH the M1 test above runs only the .sh, so the .ps1 is also pinned by text: FetchMain checks the
    fetch's exit code (the .sh's `git fetch ... && git rev-parse`), every caller refuses on $null, and no GitRun result
    goes to Out-Null."""
    ps1 = PS1.read_text(encoding="utf-8")
    fm = ps1[ps1.index("function FetchMain"):ps1.index("function FetchRd")]
    assert "if ((GitRun @('fetch', '--quiet', '--no-tags', 'origin', '+refs/heads/main:refs/cutover/main')).Code -ne 0) " \
        "{ return $null }" in fm and "Out-Null" not in fm
    calls = [m.start() for m in re.finditer(r"= FetchMain\n", ps1)]
    assert len(calls) == 9
    for at in calls:
        nxt = ps1[at:at + 300].split("\n")
        assert re.search(r"if \(-not \$(m|m0|now)\) \{ (Refuse|Fail) |if \(\$now -and ", "\n".join(nxt[:3])), nxt[:3]
    for line in ps1.splitlines():
        assert not ("GitRun" in line and "Out-Null" in line), line
    gi = ps1[ps1.index("function GitignoreEdit"):]
    gi = gi[:gi.index("\n}\n")]
    assert "if ($r.Code -ne 0) { return $null }" in gi and "$hr.Code -ne 0" in gi


def _open_restore_over(fx, files):
    """R amended with <files> (same parent, verified data/ unchanged), pushed as pull/99/head."""
    merge, br, c = _opened_restore(fx)
    return merge, c, _amend(fx, c, files, "refs/pull/99/head")


@pytest.mark.parametrize("files,text", [
    ({"scripts/evil.sh": "echo hi\n"}, "changes files beyond data/, the workflow, .github/CODEOWNERS and .gitignore: "
                                        "scripts/evil.sh (L1)"),
    ({"README": None}, "changes files beyond data/, the workflow, .github/CODEOWNERS and .gitignore: README (L1)"),
    ({".github/workflows/other.yml": "on: push\n"}, ".gitignore: .github/workflows/other.yml (L1)"),
    ({".gitignore": "build/\nsecret/\n"}, "is not its parent's without the data/ lines"),
    ({".gitignore": None}, ".gitignore (blob 'none') is not its parent's without the data/ lines"),
], ids=["added-file", "deleted-file", "other-workflow", "other-gitignore", "no-gitignore"])
def test_l1_merge_refuses_a_restore_pr_that_changes_more_than_the_restore(tmp_path, files, text):
    """data-off-main/rollback-r-scope-unchecked (L1): R's parent is on main, its data/ is verified, its workflow and
    CODEOWNERS are the pre-cutover ones, but it also changes another file or its own .gitignore."""
    fx = Fx(tmp_path)
    merge, c, h = _open_restore_over(fx, files)
    r = fx.run(["--rollback", "--merge", "99", "--sha", h, "--cutover-merge", merge, "--report", "x"])
    assert r.returncode == 1 and "the restore PR #99" in r.stdout and text in r.stdout, r.stdout + r.stderr
    assert "REFUSED: " in r.stdout and _writes(fx.calls()) == [] and fx.state["r2"] is False


def test_l1_the_open_path_and_the_merge_check_share_one_gitignore_edit(tmp_path):
    """The open path's R passes the merge path's check (both use gitignore_edit), also for a .gitignore of only data/
    lines and one without a final newline."""
    for gi in ("data/\n/data\ndata/**\n", "build/\ndata/"):
        t = tmp_path / str(len(gi))
        t.mkdir()
        fx = Fx(t, pr_extra={".gitignore": gi})
        merge, br, c = _opened_restore(fx)
        want = "" if gi.startswith("data/") else "build/"
        assert fx.og("show", c + ":.gitignore") == want
        r = fx.run(["--rollback", "--merge", "99", "--sha", c, "--cutover-merge", merge, "--report", "x"])
        assert r.returncode == 0 and "ROLLBACK DONE" in r.stdout, r.stdout + r.stderr
    sh = SH.read_text(encoding="utf-8")
    assert sh.count("gitignore_edit \"$") == 2 and "git diff-tree -r --no-renames --name-only -z \"$rp\" \"$sha\"" in sh
    ps1 = PS1.read_text(encoding="utf-8")
    assert ps1.count("GitignoreEdit $") == 2
    assert "@('diff-tree', '-r', '--no-renames', '--name-only', '-z', $rp, $Sha)" in ps1
    assert "(L1)" in ps1 and "not its parent's without the data/ lines" in ps1


def test_l2_rollback_puts_mains_r1_prime_not_the_checkouts(tmp_path):
    """data-off-main/rollback-checkout-unpinned (L2): R1' comes from main $m, so an edited or stale checkout copy is
    never written; main without a readable copy refuses before any change."""
    fx = Fx(tmp_path)
    fx.cut(STUB_PM="notok")
    fx.state["r2"] = False
    bad = json.loads(json.dumps(R1P))
    bad["bypass_actors"].append({"actor_id": 1, "actor_type": "OrganizationAdmin", "bypass_mode": "always"})
    (fx.work / "scripts" / "main-ruleset-r1p.json").write_text(json.dumps(bad))
    open(tmp_path / "calls", "w").close()
    r = fx.run(["--rollback"])
    assert r.returncode == 0 and "ROLLBACK DONE" in r.stdout, r.stdout + r.stderr
    assert fx.state["ruleset"]["bypass_actors"] == R1P["bypass_actors"]
    assert fx.state["ruleset"]["rules"] == sorted(R1P["rules"], key=lambda x: x["type"])
    for text in ("not json\n", None):
        _commit_on(fx, "refs/heads/main", {"scripts/main-ruleset-r1p.json": text}, f"r1p {text}", "refs/heads/main")
        open(tmp_path / "calls", "w").close()
        r = fx.run(["--rollback"])
        assert r.returncode == 1 and "holds no readable scripts/main-ruleset-r1p.json (R1' is read from main)" in r.stdout
        assert _writes(fx.calls()) == [], r.stdout
    ps1 = PS1.read_text(encoding="utf-8")
    assert "@('cat-file', 'blob', \"${m}:scripts/main-ruleset-r1p.json\")" in ps1
    assert "$want = $script:r1pWant" in ps1 and "ReadAllText($r1p" not in ps1


def _true_merge(fx, side, msg):
    """main becomes a true merge of itself (first parent, tree kept) and <side> (second parent). Its sha."""
    d = fx.tmp / ("m-" + hashlib.sha1((side + msg).encode()).hexdigest()[:8])
    _git(fx.tmp, "clone", "-q", str(fx.origin), str(d), env=fx.genv)
    _git(d, "fetch", "-q", "origin", side, env=fx.genv)
    _git(d, "checkout", "-q", "--detach", "origin/main", env=fx.genv)
    _git(d, "merge", "-q", "--no-ff", "-s", "ours", "-m", msg, side, env=fx.genv)
    c = _git(d, "rev-parse", "HEAD", env=fx.genv).decode().strip()
    _git(d, "push", "-q", "origin", "HEAD:refs/heads/main", env=fx.genv)
    return c


def test_l3_a_second_parent_commit_is_never_on_main(tmp_path):
    """data-off-main/first-parent-untested (L3): main holds true merges whose second parents are an ancestor of main
    but not on its first-parent line: X (looks like a cutover merge) and Y (R's parent). Both are refused; with
    --is-ancestor both would pass."""
    fx = Fx(tmp_path)
    merge, br, c = _opened_restore(fx)
    x = _commit_on(fx, fx.main, {"data": None, ".github/CODEOWNERS": None}, "cutover-like", "refs/heads/side-x")
    y = _commit_on(fx, merge, {"notes.txt": "side\n"}, "side", "refs/heads/side-y")
    _true_merge(fx, x, "merge x")
    _true_merge(fx, y, "merge y")
    for rev in (x, y):
        assert subprocess.run(["git", "--git-dir", str(fx.origin), "merge-base", "--is-ancestor", rev, "refs/heads/main"]
                              ).returncode == 0
        assert rev not in fx.og("rev-list", "--first-parent", "refs/heads/main").split()
    # X as --cutover-merge: the open path is not taken (the early path refuses: main has no CODEOWNERS) ...
    r = fx.run(["--rollback", "--cutover-merge", x])
    assert r.returncode == 1 and f"--cutover-merge {x} is not on main " in r.stdout and "REFUSED: " in r.stdout, r.stdout
    assert _writes(fx.calls()) == []
    # ... and the merge path refuses it
    r = fx.run(["--rollback", "--merge", "99", "--sha", c, "--cutover-merge", x, "--report", "x"])
    assert r.returncode == 1 and f"--cutover-merge {x} is not on main's first-parent line" in r.stdout, r.stdout
    assert _writes(fx.calls()) == []
    # Y as R's parent: R is the restore's tree plus notes.txt (so only the parent differs), one commit on Y
    d = fx.tmp / "rp"
    _git(fx.tmp, "clone", "-q", str(fx.origin), str(d), env=fx.genv)
    _git(d, "fetch", "-q", "origin", c, env=fx.genv)
    _git(d, "checkout", "-q", "--detach", c, env=fx.genv)
    (d / "notes.txt").write_text("side\n")
    _git(d, "add", "notes.txt", env=fx.genv)
    t = _git(d, "write-tree", env=fx.genv).decode().strip()
    h = _git(d, "commit-tree", t, "-p", y, "-m", "R on Y", env=fx.genv).decode().strip()
    _git(d, "push", "-q", "-f", "origin", f"{h}:refs/pull/99/head", env=fx.genv)
    r = fx.run(["--rollback", "--merge", "99", "--sha", h, "--cutover-merge", merge, "--report", "x"])
    assert r.returncode == 1 and f"the restore PR #99's parent {y} is not on main's first-parent line" in r.stdout, \
        r.stdout + r.stderr
    assert _writes(fx.calls()) == [] and fx.state["r2"] is False


def test_s1_5_step5_stops_when_records_data_moved_after_the_seed(tmp_path):
    """data-off-main/seed-window: records-data is read again right before the merge; nothing is merged."""
    fx = Fx(tmp_path)
    r = fx.cut(STUB_PM_MOVE_RD="1")
    assert r.returncode == 2 and "STOPPED at step 5" in r.stdout, r.stdout + r.stderr
    assert "no longer the seed " in r.stdout and "pushed in step 3 (S1-5): nothing is merged" in r.stdout
    assert not [c for c in fx.calls() if c["path"] == "merge-reviewed"]
    assert fx.og("rev-parse", "refs/heads/main") == fx.main
    assert fx.cmd("Undo with: bash scripts/cutover-data-off-main.sh --rollback\n") in r.stdout


# ---------------------------------------------------------------------------------------------- Ctrl+C


def _interrupted(r, step):
    """data-off-main/ps-ctrlc-exit-zero: a Ctrl+C after a change stops as a failure does: exit 2, the stop line and
    the undo line (before the fix the .ps1 exited 0 and the .sh 130, neither with an undo line)."""
    out = r.stdout + r.stderr
    assert r.returncode == 2, out
    assert f"STOPPED at step {step} (interrupted) (" in r.stdout, out
    assert r.stdout.count("Undo with: ") == 1, out
    assert "CUTOVER DONE" not in r.stdout and f"Step {step} OK" not in r.stdout, out


def test_ctrl_c_after_the_seed_push_prints_the_undo_line_and_exits_2(tmp_path):
    """SIGINT to the whole process group (a console's Ctrl+C) while step 4's protect-main runs, after step 3 pushed
    the seed."""
    fx = Fx(tmp_path)
    r = fx.interrupt(fx.cut_args(), tmp_path / "blocked", STUB_PM_BLOCK=str(tmp_path / "blocked"))
    _interrupted(r, 4)
    assert fx.cmd("Undo with: bash scripts/cutover-data-off-main.sh --rollback\n") in r.stdout
    assert "Step 3 OK: records-data = seed " in r.stdout and fx.rd()
    assert not [c for c in fx.calls() if c["path"] == "merge-reviewed"]
    assert fx.og("rev-parse", "refs/heads/main") == fx.main


def test_ctrl_c_after_the_merge_names_the_merge_in_the_undo_line(tmp_path):
    """SIGINT to the process group while merge-reviewed runs, after main moved to the squash: the undo line names
    main's new head, as Fail's does (data-off-main/undo-line-after-merge)."""
    fx = Fx(tmp_path)
    r = fx.interrupt(fx.cut_args(), tmp_path / "blocked", STUB_MR_BLOCK=str(tmp_path / "blocked"))
    _interrupted(r, 5)
    merged = fx.og("rev-parse", "refs/heads/main")
    assert merged != fx.main
    undo = fx.cmd(f"Undo with: bash scripts/cutover-data-off-main.sh --rollback --cutover-merge {merged}\n")
    assert undo in r.stdout, r.stdout
    assert fx.state["wf_state"] == "disabled_manually"          # step 6 never ran


def test_only_named_arguments_bind(tmp_path):
    """data-off-main/ps-unknown-args, kept by the .ps1's non-advanced form (a dot-sourced binding block): a positional,
    unknown or incomplete argument exits 1 before anything runs."""
    fx = Fx(tmp_path)
    for args in (["60"], ["--bogus"], ["--pr"], ["--pr", "60", "x"]):
        r = fx.run(args)
        assert r.returncode == 1, (args, r.stdout + r.stderr)
        if fx.twin == "ps1":
            assert "REFUSED: " in r.stdout and "Named parameters only" in r.stdout, r.stdout + r.stderr
        assert fx.calls() == []
    r = fx.run(["--check-attested"])                     # a switch and named values still bind (the other tests too)
    assert "NOT ATTESTED" in r.stdout and r.returncode == 1, r.stdout + r.stderr


def test_ps1_is_not_advanced_and_marks_every_intended_exit():
    """In an advanced script the exit code set in a finally block is lost after Ctrl+C (pwsh 7.4 on Linux: exit 0),
    so the .ps1 binds its parameters in a dot-sourced block and is not advanced itself; every intended exit sets
    $script:done first, so the finally block reports only a real interruption."""
    ps1 = PS1.read_text(encoding="utf-8")
    assert not re.search(r"(?m)^\[CmdletBinding", ps1) and not re.search(r"(?m)^param\(", ps1)
    assert "    . {\n        [CmdletBinding(PositionalBinding = $false)]\n        param(\n" in ps1 and "    } @args\n" in ps1
    body = ps1[ps1.index("\ntry {\n# ---"):ps1.rindex("\n} finally {")]
    exits = re.findall(r"(.{0,24})\bexit\b", body)
    assert exits and all(e.endswith("$script:done = $true; ") for e in exits), exits
    for fn in ("function Refuse", "function Fail"):
        f = ps1[ps1.index(fn):ps1.index("\n}", ps1.index(fn))] if fn == "function Fail" else ps1[ps1.index(fn):]
        f = f[:f.index("exit") + 6]
        assert "$script:done = $true" in f, fn
    fin = ps1[ps1.rindex("\n} finally {"):]
    assert "if (-not $script:done)" in fin and "exit 2" in fin and "$u = UndoLine" in fin
    sh = SH.read_text(encoding="utf-8")
    assert "trap interrupted INT TERM HUP" in sh and "refresh_undo" in sh


def test_ps1_checks_return_only_the_exit_code():
    """A .ps1 function's output is its return value: the check's printed lines go to Out-Host, so a failing
    data_shape, phone scrub or attestation check (which print lines) can't read as true."""
    ps1 = PS1.read_text(encoding="utf-8")
    assert "& $py[0] @pre -B @PyArgs | Out-Host" in ps1
    assert "--deny-self-hosted-runners | Out-Host" in ps1
    for s in ("[string]$DataFrom = ''", "-DataFrom", "function DataVerified", "PinnedSeedDigest $CutoverMerge",
              "PinnedSeedDigest $m\n", "OnMainLine $rp $m", "OnMainLine $CutoverMerge $m",
              "records-data is still the seed", "'.github/CODEOWNERS', 'data')"):
        assert s in ps1, s


def test_rollback_before_the_merge_puts_r1_prime_back_and_r2_on(tmp_path):
    fx = Fx(tmp_path)
    fx.cut(STUB_PM="notok")
    fx.state["r2"] = False
    open(tmp_path / "calls", "w").close()
    r = fx.run(["--rollback"])
    assert r.returncode == 0 and "ROLLBACK DONE" in r.stdout, r.stdout + r.stderr
    seq = [c["path"].rsplit("/", 1)[-1] for c in _writes(fx.calls())]
    assert seq == ["disable", "27502319", "workflow", "enable"], seq
    assert fx.state["ruleset"]["rules"] == sorted(R1P["rules"], key=lambda x: x["type"])
    assert fx.state["r2"] is True and fx.state["wf_state"] == "active"


def test_rollback_after_the_merge_opens_a_restore_pr_then_merges_it(tmp_path):
    fx = Fx(tmp_path)
    r = fx.cut()
    assert r.returncode == 0
    merge = re.search(fx.cmd("--rollback --cutover-merge ") + "([0-9a-f]{40})", r.stdout).group(1)
    rd = fx.rd()
    fx.state["r2"] = False
    open(tmp_path / "calls", "w").close()
    r = fx.run(["--rollback"])                      # the merge is on main: never the early path
    assert r.returncode == 1 and "--cutover-merge <sha>" in r.stdout and _writes(fx.calls()) == []
    r = fx.run(["--rollback", "--cutover-merge", merge])
    assert r.returncode == 0 and "ROLLBACK PR #99 opened" in r.stdout, r.stdout + r.stderr
    assert r.stderr == "", r.stderr       # data-off-main/ps-fatal-noise: no git "fatal:" line on a correct rollback
    br = re.search(r"pushed branch (rollback/data-on-main-\S+) at ([0-9a-f]{40})", r.stdout)
    c = br.group(2)
    assert fx.state["wf_state"] == "disabled_manually" and fx.state["r2"] is False      # nothing else yet
    # the restore: data/ = records-data's data/; workflow and CODEOWNERS from before the merge; config/ kept
    assert fx.og("rev-parse", c + ":data") == fx.og("rev-parse", rd + ":data")
    assert fx.og("rev-parse", c + ":.github/workflows/daily-update.yml") == \
        fx.og("rev-parse", merge + "^:.github/workflows/daily-update.yml")
    assert fx.og("show", c + ":.github/CODEOWNERS") == CODEOWNERS.strip()
    assert fx.og("show", c + ":.gitignore") == "build/"
    assert fx.og("rev-parse", c + ":config") == fx.og("rev-parse", merge + ":config")
    assert fx.og("rev-parse", c + "^") == merge
    assert fx.cmd(f"--rollback --merge 99 --sha {c} --cutover-merge {merge} --report <review>") in r.stdout
    # phase 2: merge (bypass), then R1', then R2 on, then the workflow
    open(tmp_path / "calls", "w").close()
    r = fx.run(["--rollback", "--merge", "99", "--sha", c, "--cutover-merge", merge, "--report", "docs/reviews/rb.md"])
    assert r.returncode == 0 and "ROLLBACK DONE" in r.stdout, r.stdout + r.stderr
    assert r.stderr == "", r.stderr
    seq = [c2["path"].rsplit("/", 1)[-1] for c2 in _writes(fx.calls())]
    assert seq == ["disable", "merge-reviewed", "27502319", "workflow", "enable"], seq
    assert fx.og("ls-tree", "--name-only", "refs/heads/main", "--", "data") == "data"
    assert fx.rd() == rd                                    # records-data is kept
    assert fx.state["r2"] is True and fx.state["wf_state"] == "active"


def test_every_stop_prints_the_rollback_command(tmp_path):
    text = SH.read_text(encoding="utf-8")
    assert 'echo "Undo with: $undo"' in text
    assert text.count("fail \"") >= 30


# ---------------------------------------------------------------------------------------------- the .ps1 twin


def _jq_filters(text):
    return sorted(set(re.findall(r"--jq '([^']*)'", text)))


def test_ps1_is_ascii_bom_less_and_51_safe():
    raw = PS1.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and all(b < 0x80 for b in raw)
    assert all(b < 0x80 for b in SH.read_bytes())
    ps1 = raw.decode("ascii")
    assert "ExecutionPolicy Bypass" not in ps1 and "-ExecutionPolicy" not in ps1
    assert not re.search(r"--jq '[^']*\"", ps1)                       # no double quote reaches gh (PS 5.1)
    assert not re.search(r"\|\s*gh\b", ps1)                            # nothing is piped into gh (BOM)
    for bad in ("??", "?.", "&&", "||", "-AsHashtable", "ConvertFrom-Json -Depth"):   # PowerShell 7 only
        assert bad not in ps1, bad


def test_ps1_gitrun_starts_git_with_a_preamble_free_stdin_encoding():
    """ps-stdin-bom (2026-11-19 -Plan on Brian's PC): under Windows PowerShell 5.1 on a UTF-8 console (chcp 65001)
    .NET Framework's Process.Start writes [Console]::InputEncoding's BOM into git's stdin before GitRun's bytes, and
    update-index refused ("malformed index info"). GitRun swaps in a preamble-free UTF8Encoding around Start only,
    and puts the console's encoding back in a finally. pwsh 7 can't show the bug (it strips the preamble): text pin."""
    ps1 = PS1.read_text(encoding="ascii")
    body = ps1[ps1.index("function GitRun("):ps1.index("function GitText(")]
    swap = body.index("[Console]::InputEncoding = New-Object Text.UTF8Encoding($false)")
    start = body.index("$p = [Diagnostics.Process]::Start($psi)")
    restore = body.index("finally { if ($null -ne $ie) { try { [Console]::InputEncoding = $ie }")
    assert "GetPreamble().Length -gt 0" in body[:swap] and swap < start < restore
    # ps51-stdin-bom-swap-fail-open (review of 2af5731): if the swap did not take, git is never started (Code 1), so
    # no caller (hash-object -w --stdin in GitignoreEdit) can store BOM'd bytes as its own; an unreadable encoding
    # counts as a BOM.
    check = body.index("try { $bom = [Console]::InputEncoding.GetPreamble().Length -gt 0 } catch { $bom = $true }")
    refuse = body.index("return New-Object PSObject -Property @{ Code = 1; Out = [byte[]]@() }")
    assert swap < check < refuse < start and "$bom = $true" in body[swap:check]
    assert body.count("[Diagnostics.Process]::Start(") == 1
    assert ps1.count("[Diagnostics.Process]::Start(") == 1 and ps1.count("RedirectStandardInput") == 1


def test_no_ps1_pipes_text_into_a_native_command_and_only_gitrun_starts_a_process():
    """docs/architecture/ps51-stdin-invariant.md, across scripts/*.ps1: under 5.1 a pipe into gh or git carries a BOM
    and CRLF, so body text goes as a BOM-less --input file and raw bytes only through cutover GitRun."""
    for f in sorted((ROOT / "scripts").glob("*.ps1")):
        text = f.read_text(encoding="ascii")
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        assert not re.search(r"\|\s*&?\s*(gh|git)(\.exe)?\b", code), f.name
        assert not re.search(r"\|\s*&\s*\$", code), f.name        # nor into & $gitExe / & $py[0]
        assert ("Process]::Start(" in code) == (f.name == "cutover-data-off-main.ps1"), f.name


def test_ps1_uses_the_same_gh_filters_as_the_sh():
    assert _jq_filters(PS1.read_text(encoding="utf-8")) == _jq_filters(SH.read_text(encoding="utf-8"))


def test_the_pin_readers_count_only_env_key_lines_of_the_real_workflow():
    """Third cutover run (2026-11-19) refused: an unanchored 'KEY:' also matched the bash "${KEY:-}" lines, so each
    reader saw 2 lines and returned nothing. Each twin selects key lines anchored at the line start, and the real
    workflow holds exactly one such line per key."""
    wf = (ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8")
    for key in ("MAIN_PR_BASELINE", "RECORDS_DATA_SEED_DIGEST"):
        assert len(re.findall(r"(?m)^\s*%s:" % key, wf)) == 1, key
        assert "${%s:-}" % key in wf, key   # the trap the anchoring is for is really there
    ps1 = PS1.read_text(encoding="utf-8")
    sh = SH.read_text(encoding="utf-8")
    for key in ("MAIN_PR_BASELINE", "RECORDS_DATA_SEED_DIGEST"):
        assert f"-match '{key}:'" not in ps1 and f"grep -c '{key}:'" not in sh, key
        assert ps1.count(f"Where-Object {{ $_ -cmatch '^\\s*{key}:' }}") == (2 if key == "MAIN_PR_BASELINE" else 1)
        assert sh.count(f"grep -cE '^[[:space:]]*{key}:'") == (2 if key == "MAIN_PR_BASELINE" else 1)


def test_ps1_has_the_same_steps_refusals_and_calls():
    ps1 = PS1.read_text(encoding="utf-8")
    sh = SH.read_text(encoding="utf-8")
    for n in range(1, 9):
        assert f"Step {n} OK" in ps1 and f"Step {n} OK" in sh, n
    for s in ("CUTOVER DONE", "ROLLBACK DONE", "ROLLBACK PR #", "STOPPED at step ", "Undo with: ", "SEED DIGEST ",
              "REFUSED: ", "Nothing was changed.", "OK: main is protected", "Rule suite ", ": bypass",
              "RECORDS_DATA_SEED_DIGEST:", "MAIN_PR_BASELINE:", "disabled_manually", "inputs[collect]=",
              "refs/cutover/main", "refs/cutover/pr", "refs/cutover/records-data", "refs/heads/records-data",
              "collector.data_shape", "tools.scrub_rpc_phones", "--check", "--path", "update-index", "--index-info",
              "commit-tree", "write-tree", "read-tree", "--deny-self-hosted-runners", "https://slsa.dev/provenance/v1",
              "--source-ref", "build-info.json?cutover=", "main-ruleset-r1p.json", "protect-main", "merge-reviewed",
              "can_approve_pull_request_reviews=true", "CLAUDE_CODE_REMOTE", "GITHUB_ACTIONS", "rollback/data-on-main-",
              "data/localities/cmc-rpc/rpc.json", "fin-books-accepted", ".github/CODEOWNERS", "--cutover-merge"):
        assert s in ps1, s
        assert s in sh, s
    assert "-PreCutover -Apps $a" in ps1 and "-Check -Apps $a" in ps1
    assert 'protect-main.sh" --pre-cutover --apps "$1"' in sh and 'protect-main.sh" --check --apps "$1"' in sh
    for s in ("[switch]$Rollback", "[switch]$Plan", "[switch]$CheckAttested", "-CutoverMerge", "$hm -ge 500 -and $hm -le 1030",
              "protect-main.ps1", "merge-reviewed.ps1", "New-Object Text.UTF8Encoding $false",
              "-cnotmatch '^/?data/?(\\*\\*?)?\\s*$'"):          # data-off-main/ps1-case
        assert s in ps1, s
    assert "$((10#$hm)) -ge 500 ] && [ $((10#$hm)) -le 1030" in sh
    # Amendment (c) and the D3 review fixes, the same in both
    for s in ("BASELINE ", "pinned MAIN_PR_BASELINE", "R2 stays off", "--is-ancestor",
              "Every commit on main after ", "was merged by a person, reviewed at its head: ", "/logs",
              "refs/cutover/rollback", "--force-remove", "byte for byte",
              "Step 8: waiting up to ", "the wait ends before 09:00 UTC so it can't meet the 09:07 daily run",
              "(540 - (", "% 1440", "tracks data/: that is not the cutover merge",
              "holds .github/CODEOWNERS: that is not the cutover merge"):
        assert s in ps1 and s in sh, s
    # every refusal of the .sh is in the .ps1 (the fixed text before any variable)
    for msg in set(re.findall(r'refuse "([^"$]{16,})', sh)) - {"could not read the UTC time"}:   # Get-Date can't fail
        assert msg.split("'")[0].split("(")[0].split(":")[0].strip() in ps1, msg
    for msg in set(re.findall(r'fail "([^"$]{16,})', sh)):
        assert msg.split("'")[0].split("(")[0].split(":")[0].strip() in ps1, msg
    # the step order is the same: each step's writes come between the same OK lines
    order = ["Step 1 OK", "disable", "Step 2 OK", "commit-tree", "Step 3 OK", "protect-main", "Step 4 OK",
             "merge-reviewed", "Step 5 OK", "enable", "Step 6 OK", "Step 7 OK", "Step 8 OK", "CUTOVER DONE"]
    for text in (sh, ps1):
        at = text.rindex("Step 1 (")
        for k in order:
            nxt = text.find(k, at)
            assert nxt > at, (k, text[at:at + 80])
            at = nxt
