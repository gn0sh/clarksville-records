"""scripts/cutover-data-off-main.{sh,ps1}: the one-session cutover in the Operator's order, and its rollback (ADR 0011;
docs/tasks/data-off-main.md D3; PR #54 security review: drift, F4, F5, F7).

The .sh runs here against a stub gh, a stub curl and stub protect-main / merge-reviewed scripts (no GitHub call is
ever made: the stubs are first on PATH, the tokens are removed, and "origin" is a bare repository in tmp_path). The
seed is built for real with git, and its checks run the real collector.data_shape and tools.scrub_rpc_phones. The
.ps1 twin (no PowerShell here) is pinned to the same steps, filters and lines text by text."""
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from collector import data_shape

ROOT = Path(__file__).resolve().parent.parent
SH = ROOT / "scripts" / "cutover-data-off-main.sh"
PS1 = ROOT / "scripts" / "cutover-data-off-main.ps1"
REPO = "gn0sh/clarksville-records"
R = "repos/" + REPO
CLOUD = ("CLAUDE_CODE_REMOTE", "GITHUB_ACTIONS", "CI")
R1P = json.loads((ROOT / "scripts" / "main-ruleset-r1p.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is needed by the script and the stub")

# ---------------------------------------------------------------------------------------------- stubs
_GH = r'''#!/usr/bin/env python3
import hashlib, json, os, subprocess, sys
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
    st.setdefault("jobs", {})[str(rid)] = [{"name": "deploy", "conclusion": st.get("deploy", "success")}]
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
if [ "${STUB_PM:-ok}" = ok ]; then echo "OK: main is protected (stub)."; exit 0; fi
echo "  NOT OK: R2 is on"; echo "NOT OK: 1 problem(s) above."; exit 1
'''

_MERGE = r'''#!/usr/bin/env bash
python3 -c 'import json,os,sys; open(os.environ["GH_CALLS"],"a").write(json.dumps({"method":"SCRIPT","path":"merge-reviewed","argv":sys.argv[1:]})+"\n")' "$@"
g="git --git-dir $STUB_ORIGIN"
m=$($g -c user.name=gn0sh -c user.email=g@x commit-tree "$2^{tree}" -p refs/heads/main -m "squash #$1")
$g update-ref refs/heads/main "$m"
echo "Merged pull request #$1 (reviewed at $2) as $m."
if [ "${STUB_MR:-bypass}" = bypass ]; then echo "Rule suite 9 for $m: bypass"; exit 0; fi
echo "Rule suite 9 for $m: pass"; echo "The merge was not a bypass (pass): tell the team."; exit 2
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
OLD_WF = 'jobs:\n  gate:\n    env:\n      MAIN_PR_BASELINE: ""   # T4.10.8\n'
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
    """origin (bare), and a checkout at the cutover PR's head P (child of main M)."""

    def __init__(self, tmp_path, main_extra=None, pr_extra=None, pin=None, skip_config=()):
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
        (w / "collector").symlink_to(ROOT / "collector")
        (w / "tools").symlink_to(ROOT / "tools")
        (w / "scripts").mkdir()
        shutil.copy(SH, w / "scripts" / SH.name)
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
        new_wf = OLD_WF + '      RECORDS_DATA_SEED_DIGEST: "%s"   # ADR 0011\n' % (pin or self.digest)
        _write(w, {**cfg, ".github/workflows/daily-update.yml": new_wf, ".github/CODEOWNERS": None,
                   ".gitignore": "build/\ndata/\n", **(pr_extra or {})})
        g("add", "-A"); g("commit", "-q", "-m", "cutover PR")
        self.head = g("rev-parse", "HEAD").decode().strip()
        g("remote", "add", "origin", str(self.origin))
        g("push", "-q", "origin", f"{self.main}:refs/heads/main", f"{self.head}:refs/pull/60/head")
        g("checkout", "-q", "--detach", self.head)
        self.bindir = tmp_path / "bin"
        self.bindir.mkdir()
        for name, text in (("gh", _GH), ("curl", _CURL), ("date", _DATE), ("sleep", "#!/bin/sh\nexit 0\n")):
            (self.bindir / name).write_text(text)
            (self.bindir / name).chmod(0o755)
        self.state = {"vars": [], "runs": [{"id": 1, "status": "completed", "event": "schedule"}],
                      "wf_state": "active", "r2": True,
                      "pr": {"number": 60, "state": "open", "base": {"ref": "main"}, "user": {"login": "gn0sh"},
                             "draft": False, "head": {"sha": self.head, "repo": {"full_name": REPO}}}}

    def og(self, *args):
        return _git(self.tmp, "--git-dir", str(self.origin), *args, env=self.genv).decode().strip()

    def run(self, args, hm="1400", **env_over):
        (self.tmp / "state.json").write_text(json.dumps(self.state))
        env = {k: v for k, v in self.genv.items() if k not in CLOUD + ("GH_TOKEN", "GITHUB_TOKEN")}
        env.update({"PATH": f"{self.bindir}:{os.environ['PATH']}", "GH_CALLS": str(self.tmp / "calls"),
                    "GH_STATE": str(self.tmp / "state.json"), "STUB_ORIGIN": str(self.origin), "FAKE_HM": hm,
                    "HOME": str(self.tmp)}, **env_over)
        r = subprocess.run(["bash", "scripts/" + SH.name, *args], cwd=self.work, env=env, capture_output=True,
                           text=True, timeout=180)
        self.state = json.loads((self.tmp / "state.json").read_text())
        return r

    def calls(self):
        p = self.tmp / "calls"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def cut(self, **kw):
        return self.run(["--pr", "60", "--sha", self.head, "--apps", kw.pop("apps", "none"), "--report",
                         "docs/reviews/x.md"], **kw)

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
    assert seq == [("PUT", "disable"), ("SCRIPT", "protect-main"), ("SCRIPT", "merge-reviewed"), ("PUT", "enable"),
                   ("POST", "dispatches"), ("POST", "dispatches")], seq
    pm = [c for c in fx.calls() if c["path"] == "protect-main"]
    assert [c["argv"] for c in pm] == [["--apps", "none"]]
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
    assert "--rollback --cutover-merge " in out


def test_the_left_out_inputs_are_exactly_the_moved_ones(tmp_path):
    fx = Fx(tmp_path)
    r = fx.run(["--plan"])
    assert r.returncode == 0, r.stdout + r.stderr
    left = re.findall(r"left out \(the cutover PR has it at (config/\S+)\): (\S+)", r.stdout)
    assert sorted(p for _, p in left) == sorted(MOVED)
    assert all(c == "config/" + p[5:] for c, p in left)
    assert f"SEED DIGEST {fx.digest}" in r.stdout and "The cutover head pins this digest." in r.stdout
    assert fx.calls() == [] and fx.rd() == ""          # --plan: no gh call, no push


def test_plan_reports_a_stale_pin(tmp_path):
    fx = Fx(tmp_path, pin="a" * 64)
    r = fx.run(["--plan"])
    assert r.returncode == 1 and f"SEED DIGEST {fx.digest}" in r.stdout and "update RECORDS_DATA_SEED_DIGEST" in r.stdout


def test_plan_runs_in_a_cloud_session(tmp_path):
    fx = Fx(tmp_path)
    r = fx.run(["--plan"], CLAUDE_CODE_REMOTE="true")
    assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------------------------------------- step 1 refusals


@pytest.mark.parametrize("hm", ["0800", "0907", "1030"])
def test_step1_refuses_in_the_daily_window(tmp_path, hm):
    fx = Fx(tmp_path)
    _refused(fx.cut(hm=hm), fx, "inside the daily run's window (08:00-10:30)")


@pytest.mark.parametrize("hm", ["0759", "1031"])
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


@pytest.mark.parametrize("apps", ["", "Claude", "a,,b", "x;y"])
def test_step1_refuses_without_a_well_formed_apps_answer(tmp_path, apps):
    fx = Fx(tmp_path)
    _refused(fx.cut(apps=apps), fx, "--apps takes the App names")


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


@pytest.mark.parametrize("case", sorted(BAD_SEEDS))
def test_step3_stops_on_a_seed_that_changed_after_step1(tmp_path, case):
    """main gains the bad entry between step 1 and step 3: step 3 rebuilds the seed, stops, pushes nothing."""
    extra, skip, text = BAD_SEEDS[case]
    if skip:
        pytest.skip("a config/ copy missing from the PR cannot appear after step 1")
    fx = Fx(tmp_path)
    late = tmp_path / "late"
    _git(tmp_path, "clone", "-q", "-b", "main", str(fx.origin), str(late), env=fx.genv)
    _write(late, extra)
    fx.state["on_disable"] = [f"cd {late} && git add -A && git -c user.name=g -c user.email=g@x commit -q -m late "
                              f"&& git push -q origin HEAD:main"]
    r = fx.cut()
    assert r.returncode == 2 and "STOPPED at step 3" in r.stdout and text in r.stdout, r.stdout + r.stderr
    assert "Undo with: bash scripts/cutover-data-off-main.sh --rollback" in r.stdout
    assert fx.rd() == "" and [c["path"] for c in _writes(fx.calls())] == [R + "/actions/workflows/daily-update.yml/disable"]


def test_step2_stops_when_a_run_started_before_the_disable(tmp_path):
    fx = Fx(tmp_path)
    fx.state["run_starts_on_disable"] = True
    r = fx.cut()
    assert r.returncode == 2 and "STOPPED at step 2" in r.stdout and "--rollback" in r.stdout and fx.rd() == ""


def test_step4_stops_unless_protect_main_prints_ok(tmp_path):
    fx = Fx(tmp_path)
    r = fx.cut(STUB_PM="notok")
    assert r.returncode == 2 and "STOPPED at step 4" in r.stdout and "protect-main did not print OK" in r.stdout
    assert not [c for c in fx.calls() if c["path"] == "merge-reviewed"]
    assert "Undo with: bash scripts/cutover-data-off-main.sh --rollback\n" in r.stdout


def test_step5_stops_unless_the_merge_is_a_bypass(tmp_path):
    fx = Fx(tmp_path)
    r = fx.cut(STUB_MR="pass")
    assert r.returncode == 2 and "STOPPED at step 5" in r.stdout and "bypass" in r.stdout
    assert fx.state["wf_state"] == "disabled_manually"


def test_step7_stops_when_the_deploy_did_not_succeed(tmp_path):
    fx = Fx(tmp_path)
    fx.state["deploy"] = "skipped"
    r = fx.cut()
    assert r.returncode == 2 and "STOPPED at step 7" in r.stdout and "'skipped', not success" in r.stdout
    assert "--rollback --cutover-merge " in r.stdout.split("STOPPED")[1]


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


def test_rollback_refuses_while_mains_workflow_sets_the_baseline(tmp_path):
    fx = Fx(tmp_path)
    r = fx.cut()
    assert r.returncode == 0
    late = tmp_path / "late"
    _git(tmp_path, "clone", "-q", "-b", "main", str(fx.origin), str(late), env=fx.genv)
    wf = late / ".github/workflows/daily-update.yml"
    wf.write_text(wf.read_text().replace('MAIN_PR_BASELINE: ""', 'MAIN_PR_BASELINE: "' + "1" * 40 + '"'))
    _git(late, "commit", "-q", "-am", "baseline", env=fx.genv)
    _git(late, "push", "-q", "origin", "HEAD:main", env=fx.genv)
    open(tmp_path / "calls", "w").close()
    r = fx.run(["--rollback"])
    assert r.returncode == 1 and "main's workflow sets MAIN_PR_BASELINE" in r.stdout and _writes(fx.calls()) == []


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
    merge = re.search(r"--rollback --cutover-merge ([0-9a-f]{40})", r.stdout).group(1)
    rd = fx.rd()
    fx.state["r2"] = False
    open(tmp_path / "calls", "w").close()
    r = fx.run(["--rollback"])
    assert r.returncode == 2 and "--cutover-merge <sha>" in r.stdout
    r = fx.run(["--rollback", "--cutover-merge", merge])
    assert r.returncode == 0 and "ROLLBACK PR #99 opened" in r.stdout, r.stdout + r.stderr
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
    assert f"--rollback --merge 99 --sha {c} --report <review>" in r.stdout
    # phase 2: merge (bypass), then R1', then R2 on, then the workflow
    open(tmp_path / "calls", "w").close()
    r = fx.run(["--rollback", "--merge", "99", "--sha", c, "--report", "docs/reviews/rb.md"])
    assert r.returncode == 0 and "ROLLBACK DONE" in r.stdout, r.stdout + r.stderr
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


def test_ps1_uses_the_same_gh_filters_as_the_sh():
    assert _jq_filters(PS1.read_text(encoding="utf-8")) == _jq_filters(SH.read_text(encoding="utf-8"))


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
    for s in ("[switch]$Rollback", "[switch]$Plan", "[switch]$CheckAttested", "-CutoverMerge", "$hm -ge 800 -and $hm -le 1030",
              "protect-main.ps1", "merge-reviewed.ps1", "New-Object Text.UTF8Encoding $false"):
        assert s in ps1, s
    assert "$((10#$hm)) -ge 800 ] && [ $((10#$hm)) -le 1030" in sh
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
