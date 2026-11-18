"""I-pub, the content tripwire (collector/tripwire.py; ADR 0011 decision 4 and Amendment (c); task B4): a published
vote, roll call or outcome that changes or disappears holds the deploy unless config/published-fact-changes.yml lists
it; allow_shrink never counts; a read that fails holds; a missing build-info.json passes only on the seed. Also the
update job's tripwire, issue and build-info steps, and the city-books issue text (row FB)."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from collector import data_shape, tripwire

ROOT = Path(__file__).resolve().parents[2]
WF = yaml.safe_load((ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8"))
UPDATE = {s.get("name"): s for s in WF["jobs"]["update"]["steps"]}
UPDATE_NAMES = [s.get("name") for s in WF["jobs"]["update"]["steps"]]
TRIPWIRE_STEP = "Check published facts against the live site (I-pub tripwire)"
HELD_ISSUE_STEP = "Open or update the deploy-held issue"
BUILD_INFO_STEP = "Write build-info.json into the site"
URL = "https://daylight.gnoshcodes.com/build-info.json"


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _rc(rid, outcome="passed", status="verified", votes=(("a", "yes"), ("b", "yes"), ("c", "no"))):
    return {"id": rid, "outcome": outcome, "stated_tally": {"yes": 2, "no": 1}, "verification": {"status": status},
            "votes": [{"official_id": o, "value": v, "raw_name": o.upper()} for o, v in votes], "page": 1}


def _motion(mid, confirmed=True, outcome="carried"):
    return {"id": mid, "outcome": outcome, "tally": "4-1", "nays": ["x"], "abstained": [], "confirmed": confirmed}


FACTS = {"schema_version": 1, "meetings": [{"id": "m1"}], "roll_calls": [_rc("rc-1"), _rc("rc-2"),
                                                                       _rc("rc-3", status="unverified")]}
CITY = {"schema_version": 1, "roll_calls": [_rc("rc-city-1")]}
RPC = {"schema": 1, "motions": [_motion("mo-1"), _motion("mo-2", confirmed=False)]}


def _tree(facts=FACTS, city=CITY, rpc=RPC) -> dict[str, object]:
    return {"data/facts.json": facts, "data/manifest.json": {"sources": []},
            "data/localities/clarksville-tn/facts.json": city, "data/localities/cmc-rpc/rpc.json": rpc}


def _write(folder: Path, files: dict[str, object]):
    for rel, doc in files.items():
        p = folder / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc, indent=1) if not isinstance(doc, str) else doc, encoding="utf-8")


class Repo:
    """origin (bare, main + records-data), a clone `work` standing for the update job's checkout of S, and this run's
    data/ folder on disk under `work`. records-data starts with one parentless commit D holding `live`."""

    def __init__(self, tmp_path: Path, live: dict[str, object]):
        self.origin, self.src, self.work = tmp_path / "origin.git", tmp_path / "src", tmp_path / "work"
        _git(tmp_path, "init", "-q", "--bare", str(self.origin))
        _git(self.origin, "config", "uploadpack.allowFilter", "true")
        _git(self.origin, "config", "uploadpack.allowAnySHA1InWant", "true")
        _git(tmp_path, "init", "-q", str(self.src))
        (self.src / "x.py").write_text("1\n")
        _git(self.src, "add", "-A")
        _git(self.src, "commit", "-q", "-m", "main")
        _git(self.src, "push", "-q", f"file://{self.origin}", "HEAD:refs/heads/main")
        _git(self.src, "checkout", "-q", "--orphan", "rd")
        _git(self.src, "rm", "-q", "-rf", "--cached", ".")
        (self.src / "x.py").unlink()
        self.d = self.commit(live)
        _git(tmp_path, "clone", "-q", "--depth=1", f"file://{self.origin}", str(self.work))
        self.data = self.work / "data"

    def commit(self, files: dict[str, object]) -> str:
        """One more commit on records-data whose data/ is exactly `files`; returns its sha."""
        subprocess.run(["rm", "-rf", str(self.src / "data")], check=True)
        _write(self.src, files)
        _git(self.src, "add", "-A", "--", "data")
        _git(self.src, "commit", "-q", "--allow-empty", "-m", "data")
        _git(self.src, "push", "-q", f"file://{self.origin}", "HEAD:refs/heads/records-data")
        return _git(self.src, "rev-parse", "HEAD")

    def run_data(self, files: dict[str, object]):
        subprocess.run(["rm", "-rf", str(self.data)], check=True)
        _write(self.work, files)

    def info(self, data_sha: str, files: dict[str, object] | None = None) -> bytes:
        """The build-info.json a run deploying `files` (default: the tree at data_sha) on data_sha would carry."""
        if files is None:
            listing = subprocess.run(["git", "ls-tree", "-r", "-z", data_sha, "--", "data"], cwd=self.src,
                                     capture_output=True, check=True).stdout
            digest = hashlib.sha256(listing).hexdigest()
        else:
            folder = self.work.parent / "deployed"
            subprocess.run(["rm", "-rf", str(folder)], check=True)
            _write(folder, files)
            digest = tripwire.build_info("a" * 40, data_sha, folder / "data")["listing_sha256"]
        return json.dumps({"schema": tripwire.SCHEMA, "sha": "a" * 40, "data_sha": data_sha,
                           "listing_sha256": digest}).encode()

    def listed(self, entries: list[dict]):
        (self.work / "config").mkdir(exist_ok=True)
        (self.work / "config" / "published-fact-changes.yml").write_text(yaml.safe_dump(entries), encoding="utf-8")

    def main(self, monkeypatch, raw: bytes | None | Exception, seed="no") -> int:
        def fake(url, timeout=30.0):
            assert url == URL
            if isinstance(raw, Exception):
                raise raw
            return raw
        monkeypatch.setattr(tripwire, "fetch_build_info", fake)
        return tripwire.main(["check", "--url", URL, "--seed", seed, "--data", str(self.data),
                              "--repo", str(self.work)])


@pytest.fixture
def repo(tmp_path):
    r = Repo(tmp_path, _tree())
    r.run_data(_tree())
    return r


def test_no_change_passes(repo, monkeypatch, capsys):
    assert repo.main(monkeypatch, repo.info(repo.d)) == tripwire.PASS
    assert "tripwire: pass: 0 published fact(s)" in capsys.readouterr().out


def test_a_changed_outcome_holds(repo, monkeypatch, capsys):
    facts = copy.deepcopy(FACTS)
    facts["roll_calls"][0]["outcome"] = "failed"
    repo.run_data(_tree(facts=facts))
    assert repo.main(monkeypatch, repo.info(repo.d)) == tripwire.HIT
    out = capsys.readouterr().out
    assert "tripwire: changed: rc-1 (data/facts.json)" in out and "tripwire: held: 1 published fact(s)" in out


@pytest.mark.parametrize("edit", ["vote", "tally", "unverified", "rpc-outcome", "rpc-unconfirmed", "rpc-nays",
                                  "city-vote"])
def test_every_shown_value_counts(repo, monkeypatch, edit):
    facts, city, rpc = copy.deepcopy(FACTS), copy.deepcopy(CITY), copy.deepcopy(RPC)
    {"vote": lambda: facts["roll_calls"][1]["votes"][2].update(value="yes"),
     "tally": lambda: facts["roll_calls"][1].update(stated_tally={"yes": 3, "no": 0}),
     "unverified": lambda: facts["roll_calls"][1]["verification"].update(status="unverified"),
     "rpc-outcome": lambda: rpc["motions"][0].update(outcome="failed"),
     "rpc-unconfirmed": lambda: rpc["motions"][0].update(confirmed=False),
     "rpc-nays": lambda: rpc["motions"][0].update(nays=[]),
     "city-vote": lambda: city["roll_calls"][0]["votes"].pop()}[edit]()
    repo.run_data(_tree(facts=facts, city=city, rpc=rpc))
    assert repo.main(monkeypatch, repo.info(repo.d)) == tripwire.HIT


def test_a_change_to_a_fact_not_shown_passes(repo, monkeypatch):
    """An unverified roll call or an unconfirmed motion shows no values: its values may change (it stays listed)."""
    facts, rpc = copy.deepcopy(FACTS), copy.deepcopy(RPC)
    facts["roll_calls"][2]["outcome"] = "failed"
    rpc["motions"][1]["outcome"] = "failed"
    repo.run_data(_tree(facts=facts, rpc=rpc))
    assert repo.main(monkeypatch, repo.info(repo.d)) == tripwire.PASS


@pytest.mark.parametrize("which", ["verified", "unverified", "rpc-motion", "whole-file"])
def test_a_removed_roll_call_holds(repo, monkeypatch, capsys, which):
    facts, rpc, tree = copy.deepcopy(FACTS), copy.deepcopy(RPC), None
    if which == "verified":
        del facts["roll_calls"][0]
    elif which == "unverified":
        del facts["roll_calls"][2]
    elif which == "rpc-motion":
        del rpc["motions"][1]
    tree = _tree(facts=facts, rpc=rpc)
    if which == "whole-file":
        del tree["data/localities/clarksville-tn/facts.json"]
    repo.run_data(tree)
    assert repo.main(monkeypatch, repo.info(repo.d)) == tripwire.HIT
    assert "tripwire: removed: " in capsys.readouterr().out


def test_a_listed_change_passes(repo, monkeypatch):
    facts = copy.deepcopy(FACTS)
    facts["roll_calls"][0]["outcome"] = "failed"
    del facts["roll_calls"][1]
    repo.run_data(_tree(facts=facts))
    repo.listed([{"fact_id": "rc-1", "change": "changed", "listed_on": "2026-11-18", "reason": "amended minutes"}])
    assert repo.main(monkeypatch, repo.info(repo.d)) == tripwire.HIT            # rc-2's removal is not listed
    repo.listed([{"fact_id": "rc-1", "change": "changed", "listed_on": "2026-11-18", "reason": "amended minutes"},
                 {"fact_id": "rc-2", "change": "removed", "listed_on": "2026-11-18", "reason": "a duplicate"}])
    assert repo.main(monkeypatch, repo.info(repo.d)) == tripwire.PASS


def test_a_listing_is_for_its_kind_of_change_only(repo, monkeypatch):
    """"changed" does not let the fact disappear, and "removed" does not let it change."""
    facts = copy.deepcopy(FACTS)
    del facts["roll_calls"][0]
    repo.run_data(_tree(facts=facts))
    repo.listed([{"fact_id": "rc-1", "change": "changed", "listed_on": "2026-11-18", "reason": "r"}])
    assert repo.main(monkeypatch, repo.info(repo.d)) == tripwire.HIT
    facts = copy.deepcopy(FACTS)
    facts["roll_calls"][0]["outcome"] = "failed"
    repo.run_data(_tree(facts=facts))
    repo.listed([{"fact_id": "rc-1", "change": "removed", "listed_on": "2026-11-18", "reason": "r"}])
    assert repo.main(monkeypatch, repo.info(repo.d)) == tripwire.HIT


def test_an_invalid_list_holds(repo, monkeypatch, capsys):
    repo.listed([{"fact_id": "rc-1", "change": "changed", "listed_on": "2026-02-30", "reason": "r"}])
    assert repo.main(monkeypatch, repo.info(repo.d)) == tripwire.BAD_LIST
    assert "tripwire: held: published-fact-changes.yml" in capsys.readouterr().out


def test_a_new_meeting_passes(repo, monkeypatch):
    facts, rpc = copy.deepcopy(FACTS), copy.deepcopy(RPC)
    facts["meetings"].append({"id": "m2"})
    facts["roll_calls"] += [_rc("rc-4"), _rc("rc-5", status="unverified")]
    rpc["motions"].append(_motion("mo-3"))
    tree = _tree(facts=facts, rpc=rpc)
    tree["data/localities/new-body/facts.json"] = {"roll_calls": [_rc("rc-new")]}
    repo.run_data(tree)
    assert repo.main(monkeypatch, repo.info(repo.d)) == tripwire.PASS


def test_a_held_roll_call_that_becomes_verified_passes(repo, monkeypatch):
    facts = copy.deepcopy(FACTS)
    facts["roll_calls"][2]["verification"]["status"] = "verified"
    repo.run_data(_tree(facts=facts))
    assert repo.main(monkeypatch, repo.info(repo.d)) == tripwire.PASS


def test_a_duplicate_id_never_hides_a_change(repo, monkeypatch):
    facts = copy.deepcopy(FACTS)
    facts["roll_calls"].append(copy.deepcopy(facts["roll_calls"][0]))
    facts["roll_calls"][-1]["outcome"] = "failed"
    repo.run_data(_tree(facts=facts))
    assert repo.main(monkeypatch, repo.info(repo.d)) == tripwire.HIT


@pytest.mark.parametrize("why", ["error", "http-500", "not-json", "bad-fields", "d-not-on-records-data",
                                 "no-matching-listing", "broken-run-file", "broken-live-file", "wrong-shape",
                                 "no-data-folder"])
def test_a_failed_read_holds(repo, monkeypatch, capsys, why):
    raw: bytes | Exception = repo.info(repo.d)
    if why == "error":
        raw = tripwire.NotRead("build-info.json: URLError")
    elif why == "http-500":
        raw = tripwire.NotRead("build-info.json: HTTP 500")
    elif why == "not-json":
        raw = b"<html>"
    elif why == "bad-fields":
        raw = json.dumps({**json.loads(raw), "d": "b" * 40}).encode()
    elif why == "d-not-on-records-data":
        raw = json.dumps({**json.loads(raw), "data_sha": "b" * 40}).encode()
    elif why == "no-matching-listing":
        raw = json.dumps({**json.loads(raw), "listing_sha256": "c" * 64}).encode()
    elif why == "broken-run-file":
        (repo.data / "facts.json").write_text("{", encoding="utf-8")
    elif why == "broken-live-file":
        d = repo.commit({**_tree(), "data/facts.json": "{"})
        raw = repo.info(d)
    elif why == "wrong-shape":
        repo.run_data({**_tree(), "data/facts.json": {"roll_calls": ["rc-1"]}})
    elif why == "no-data-folder":
        subprocess.run(["rm", "-rf", str(repo.data)], check=True)
    for seed in ("no", "yes"):          # a failed read holds on the seed too: only a missing file passes there
        assert repo.main(monkeypatch, raw, seed=seed) == tripwire.NOT_READ, why
    assert "tripwire: held: " in capsys.readouterr().out


def test_an_unforeseen_error_holds(repo, monkeypatch, capsys):
    monkeypatch.setattr(tripwire, "hits", lambda *a: 1 / 0)
    assert repo.main(monkeypatch, repo.info(repo.d)) == tripwire.NOT_READ
    assert "tripwire: held: the check stopped (ZeroDivisionError)" in capsys.readouterr().out


def test_the_seed_bootstrap_passes_and_only_the_seed(repo, monkeypatch, capsys):
    """The live site from before the cutover has no build-info.json (404): accepted only while this run's D is the
    seed (the gate's `seed` output)."""
    assert repo.main(monkeypatch, None, seed="yes") == tripwire.PASS
    assert repo.main(monkeypatch, None, seed="no") == tripwire.NOT_READ
    assert "build-info.json is missing and this run's D is not the seed" in capsys.readouterr().out


def test_the_live_tree_is_found_after_the_push(repo, monkeypatch):
    """A collecting run's build-info names the gate's D, but the site carries the push job's commit on D (the listing
    digest picks it). A later run (records-data moved on twice, the deploys held) still compares with that tree."""
    facts = copy.deepcopy(FACTS)
    facts["roll_calls"].append(_rc("rc-4"))
    deployed = _tree(facts=facts)
    d1 = repo.commit(deployed)                                     # the push job's commit on D, which was deployed
    raw = repo.info(repo.d, files=deployed)
    assert json.loads(raw)["listing_sha256"] == json.loads(repo.info(d1))["listing_sha256"]
    gone = copy.deepcopy(facts)
    del gone["roll_calls"][-1]
    repo.commit(_tree(facts=gone))                                 # a later run dropped rc-4 (held, still pushed)
    repo.run_data(_tree(facts=gone))
    assert repo.main(monkeypatch, raw) == tripwire.HIT             # rc-4 was live: dropping it holds
    repo.run_data(deployed)
    assert repo.main(monkeypatch, raw) == tripwire.PASS


def test_an_allow_shrink_run_that_drops_a_published_roll_call_still_holds(repo, monkeypatch):
    """F7: allow_shrink lets the collector replace kept documents, never the deploy past I-pub. The tripwire reads no
    allow_shrink, the step passes it nothing, and a dropped verified roll call holds with it set every way it can be."""
    facts = copy.deepcopy(FACTS)
    del facts["roll_calls"][0]                                     # what an allow_shrink run would write
    repo.run_data(_tree(facts=facts))
    (repo.work / "build").mkdir()
    (repo.work / "build" / "run-log.json").write_text(json.dumps({"allowed_shrink": ["src-1"]}), encoding="utf-8")
    for k, v in {"ALLOW_SHRINK": "true", "INPUT_ALLOW_SHRINK": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                 "TRIGGERING_ACTOR": "gn0sh"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(repo.work)
    assert repo.main(monkeypatch, repo.info(repo.d)) == tripwire.HIT
    src = (ROOT / "collector" / "tripwire.py").read_text(encoding="utf-8")
    code = src.split('"""', 2)[2]
    assert "shrink" not in code.lower() and "environ" not in code
    step = UPDATE[TRIPWIRE_STEP]
    assert "shrink" not in json.dumps(step).lower() and "inputs." not in json.dumps(step)


# ---- build-info.json ----

def test_build_info_matches_the_git_listing_of_the_same_files(tmp_path):
    """The digest build-info.json carries (from the data/ folder on disk) is the sha256 of the listing git gives for
    the push job's commit of those files, so the next run finds the live tree on records-data."""
    r = Repo(tmp_path, _tree())
    r.run_data(_tree())
    (r.data / "store").mkdir()
    (r.data / "store" / "x.pdf").write_bytes(b"%PDF")            # a cache: never in the listing
    out = r.work / "build-info.json"
    assert tripwire.main(["build-info", "--sha", "a" * 40, "--data-sha", r.d, "--out", str(out),
                          "--data", str(r.data)]) == 0
    info = json.loads(out.read_text(encoding="utf-8"))
    assert set(info) == {"schema", "sha", "data_sha", "listing_sha256"} and info["data_sha"] == r.d
    assert info == json.loads(r.info(r.d))
    assert tripwire.parse_build_info(out.read_bytes()) == info


@pytest.mark.parametrize("argv", [["--sha", "x", "--data-sha", "a" * 40], ["--sha", "a" * 40, "--data-sha", ""]])
def test_build_info_refuses_a_bad_sha(tmp_path, argv):
    _write(tmp_path, {"data/x.json": {}})
    assert tripwire.main(["build-info", *argv, "--out", str(tmp_path / "b.json"), "--data", str(tmp_path / "data")]) == 2
    assert not (tmp_path / "b.json").exists()


@pytest.mark.parametrize("bad", ["data/.hidden.json", "data/a.txt", "data/maps/manifest.json", "data/names.yml", None])
def test_build_info_refuses_data_the_push_job_would_not_commit_as_is(tmp_path, bad):
    """A hidden file (dropped by the artifact upload), a file the push job refuses, a person-made folder, or no
    data at all: the digest would name no records-data commit, so nothing is written (the step fails, no deploy)."""
    _write(tmp_path, {"data/x.json": {}, **({bad: "x"} if bad else {})})
    if bad is None:
        subprocess.run(["rm", "-rf", str(tmp_path / "data")], check=True)
    out = tmp_path / "b.json"
    assert tripwire.main(["build-info", "--sha", "a" * 40, "--data-sha", "b" * 40, "--out", str(out),
                          "--data", str(tmp_path / "data")]) == 1
    assert not out.exists()


@pytest.mark.parametrize("url", ["http://daylight.gnoshcodes.com/build-info.json", URL + "?x=1", "file:///etc/x",
                                 "https://a b/"])
def test_check_refuses_a_bad_url(url):
    assert tripwire.main(["check", "--url", url, "--seed", "no"]) == tripwire.BAD_CALL


def test_check_refuses_a_bad_call():
    assert tripwire.main(["check", "--url", URL]) == tripwire.BAD_CALL
    assert tripwire.main(["check", "--url", URL, "--seed", "maybe"]) == tripwire.BAD_CALL
    assert tripwire.main([]) == tripwire.BAD_CALL


class _Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n):
        return self.body[:n]


def test_fetch_build_info_404_is_missing_and_anything_else_fails(monkeypatch):
    import urllib.error
    seen = []

    def opener(answer):
        class Opener:
            def open(self, req, timeout):
                seen.append(req.full_url)
                if isinstance(answer, Exception):
                    raise answer
                return _Resp(answer)
        return lambda *handlers: Opener()
    monkeypatch.setattr(tripwire.urllib.request, "build_opener", opener(b'{"a": 1}'))
    assert tripwire.fetch_build_info(URL) == b'{"a": 1}'
    assert seen[-1].startswith(URL + "?tripwire=")                    # past the Pages cache
    monkeypatch.setattr(tripwire.urllib.request, "build_opener",
                        opener(urllib.error.HTTPError(URL, 404, "nf", {}, None)))
    assert tripwire.fetch_build_info(URL) is None
    for exc in (urllib.error.HTTPError(URL, 500, "x", {}, None), urllib.error.URLError("down"), TimeoutError()):
        monkeypatch.setattr(tripwire.urllib.request, "build_opener", opener(exc))
        with pytest.raises(tripwire.NotRead):
            tripwire.fetch_build_info(URL)
    monkeypatch.setattr(tripwire.urllib.request, "build_opener", opener(b"x" * (tripwire.MAX_BUILD_INFO + 1)))
    with pytest.raises(tripwire.NotRead):
        tripwire.fetch_build_info(URL)


def test_a_redirect_off_https_fails():
    h = tripwire._HttpsOnlyRedirect()
    with pytest.raises(tripwire.NotRead):
        h.redirect_request(None, None, 302, "Found", {}, "http://daylight.gnoshcodes.com/build-info.json")


# ---- the workflow's steps ----

def _run_tripwire_step(tmp_path, rc: int, seed="no", forge=False):
    """The update job's tripwire step with `python` faked: it exits `rc` (and, with forge, writes held=no to
    $GITHUB_OUTPUT itself if it can). Returns the step's outputs, last value per key as GitHub reads them."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "python").write_text("#!/bin/sh\necho \"tripwire: changed: rc-1 (data/facts.json)\"\n"
                                   + ("[ -n \"$GITHUB_OUTPUT\" ] && echo held=no >> \"$GITHUB_OUTPUT\"\n" if forge else "")
                                   + f"exit {rc}\n")
    (bindir / "python").chmod(0o755)
    out = tmp_path / "out"
    out.write_text("")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(out), "SEED": seed,
           "RUNNER_TEMP": str(tmp_path)}
    r = subprocess.run(["bash", "-e", "-c", UPDATE[TRIPWIRE_STEP]["run"]], env=env, capture_output=True, text=True,
                       cwd=tmp_path)
    assert r.returncode == 0, r.stderr                   # the step never fails the job: the data push still happens
    outputs = {}
    for ln in out.read_text().splitlines():
        k, _, v = ln.partition("=")
        outputs[k] = v
    return outputs, r.stdout


@pytest.mark.parametrize("rc,kind", [(0, "pass"), (1, "hit"), (2, "error"), (3, "not-read"), (4, "bad-list"),
                                     (5, "error"), (127, "error")])
def test_the_step_outputs_held_no_only_on_exit_0(tmp_path, rc, kind):
    """No path after a hit (or any non-zero exit) outputs held=no, even if the check itself writes to the outputs
    file; one mode, no input or variable that turns the hold off (Amendment (c) item 4)."""
    for forge in (False, True):
        outputs, _ = _run_tripwire_step(tmp_path, rc, forge=forge)
        assert outputs["held"] == ("no" if rc == 0 else "yes") and outputs["kind"] == kind, (rc, forge)


@pytest.mark.parametrize("seed,passed", [("yes", "yes"), ("no", "no"), ("", "no"), ("YES", "no"), ("x", "no")])
def test_the_step_passes_the_seed_only_when_the_gate_says_exactly_yes(tmp_path, seed, passed):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "python").write_text("#!/bin/sh\necho \"$@\" > \"$RUNNER_TEMP/argv\"\nexit 0\n")
    (bindir / "python").chmod(0o755)
    (tmp_path / "out").write_text("")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(tmp_path / "out"),
           "SEED": seed, "RUNNER_TEMP": str(tmp_path)}
    subprocess.run(["bash", "-e", "-c", UPDATE[TRIPWIRE_STEP]["run"]], env=env, check=True, capture_output=True,
                   cwd=tmp_path)
    argv = (tmp_path / "argv").read_text().split()
    assert argv[:3] == ["-m", "collector.tripwire", "check"] and argv[argv.index("--seed") + 1] == passed
    assert argv[argv.index("--url") + 1] == URL


def test_the_tripwire_runs_after_the_build_and_holds_deploy():
    step = UPDATE[TRIPWIRE_STEP]
    assert step["id"] == "tripwire" and step["if"] == "success()" and "continue-on-error" not in step
    assert step["env"] == {"SEED": "${{ needs.gate.outputs.seed }}"}
    names = UPDATE_NAMES
    assert names.index("Tests (full suite, about 12 min, default settings)") < names.index(TRIPWIRE_STEP)
    assert names.index(TRIPWIRE_STEP) < names.index(BUILD_INFO_STEP) < names.index("Upload Pages artifact")
    assert names.index(TRIPWIRE_STEP) < names.index("Upload refreshed data")   # the push still happens (data kept)
    assert WF["jobs"]["update"]["outputs"]["held"] == "${{ steps.tripwire.outputs.held }}"
    deploy_if = WF["jobs"]["deploy"]["if"]
    assert "needs.update.outputs.held == 'no'" in deploy_if and "needs.gate.outputs.verified == 'true'" in deploy_if
    assert "held" not in WF["jobs"]["push"]["if"]                  # a hold never stops the data push
    assert "deploy" in WF["jobs"]["note"]["needs"]                 # the note follows deploy: skipped when held
    assert "data_sha" not in json.dumps(WF[True]["workflow_dispatch"].get("inputs", {}))  # no data_sha input


def test_the_build_info_step_writes_s_and_d():
    step = UPDATE[BUILD_INFO_STEP]
    assert step["if"] == "success()"
    assert step["env"] == {"S": "${{ needs.gate.outputs.sha }}", "D": "${{ needs.gate.outputs.data_sha }}"}
    assert step["run"].strip() == ('python -m collector.tripwire build-info --sha "$S" --data-sha "$D" '
                                   "--out build/site/build-info.json")


def _issue_body(tmp_path, step_name: str, env: dict, files: dict[str, str] | None = None) -> tuple[str, list]:
    """Run an issue step with gh faked (no open issue); returns (the body file's text, gh's argument lists)."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    calls = tmp_path / "gh-calls"
    (bindir / "gh").write_text(f"#!/bin/sh\necho \"$*\" >> '{calls}'\n"
                               "for a in \"$@\"; do case \"$prev\" in --body-file) cp \"$a\" \"$RUNNER_TEMP/body-seen\";; "
                               "esac; prev=$a; done\nexit 0\n")
    (bindir / "gh").chmod(0o755)
    for rel, text in (files or {}).items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    full = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "RUNNER_TEMP": str(tmp_path),
            "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "1", **env}
    step = UPDATE[step_name]
    full.update({k: v for k, v in step.get("env", {}).items() if "${{" not in str(v)})
    r = subprocess.run(["bash", "-c", step["run"]], env=full, cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return (tmp_path / "body-seen").read_text(encoding="utf-8"), calls.read_text().splitlines()


@pytest.mark.parametrize("kind,says", [("hit", "config/published-fact-changes.yml"),
                                       ("not-read", "could not read"),
                                       ("bad-list", "config/published-fact-changes.yml is not valid"),
                                       ("error", "did not finish")])
def test_the_held_issue_has_one_fixed_title_and_its_own_text_per_kind(tmp_path, kind, says):
    step = UPDATE[HELD_ISSUE_STEP]
    assert step["if"] == "always() && steps.tripwire.outputs.held == 'yes'"
    assert step["continue-on-error"] is True
    assert step["env"]["HELD_TITLE"] == "Daily update: deploy held (published facts)"
    assert step["env"]["KIND"] == "${{ steps.tripwire.outputs.kind }}" and "${{" not in step["run"]
    body, calls = _issue_body(tmp_path, HELD_ISSUE_STEP, {"KIND": kind}, {
        "tripwire.txt": "tripwire: changed: rc-1 (data/facts.json)\n`evil` ```\nnot ours\n"})
    assert says in body and "The live site is unchanged" in body
    assert "allow_shrink" in body and "does not release" in body
    assert "--app github-actions" in calls[0] and calls[-1].startswith("issue create")
    if kind in ("hit", "not-read"):
        assert "tripwire: changed: rc-1 (data/facts.json)" in body and "not ours" not in body
    assert "`evil`" not in body


def test_the_city_books_issue_names_the_accepted_list_and_asks_for_no_data_commit(tmp_path):
    """Row FB (ADR 0011 decision 2a): a person reproduces the reading locally (fetch-data, fin-books fetch and build),
    then fixes the reader or lists the reading in config/fin-books-accepted.yml, both by PR. data/ is never
    committed."""
    step = UPDATE["Open or update the city budget books issue"]
    body, _ = _issue_body(tmp_path, "Open or update the city budget books issue", {},
                          {"build/run-log.json": json.dumps({"city_books": {"clarksville-tn": {"warning": "w1"}}})})
    for words in ("scripts/fetch-data", "python -m collector fin-books fetch --locality",
                  "python -m collector fin-books build --locality", "build/fin-books-", "config/fin-books-accepted.yml",
                  "pull request", "next daily run"):
        assert words in body, words
    assert "before it is committed" not in step["run"] and "Do not commit data/" in body
    assert body.index("scripts/fetch-data") < body.index("fin-books fetch") < body.index("fin-books build") \
        < body.index("config/fin-books-accepted.yml")
    assert "w1" in body


def test_the_update_job_builds_on_s_plus_d():
    """Row J1/K: S, then D's data/ into data/ (checked to be the gate's D), before any cache restore."""
    names = UPDATE_NAMES
    co = UPDATE["Check out the gate's records-data head (D)"]
    assert co["with"] == {"ref": "${{ needs.gate.outputs.data_sha }}", "path": ".records-data",
                          "persist-credentials": False}
    assert co["uses"] == UPDATE["Check out the gate's commit"]["uses"]
    put = UPDATE["Put D's data/ into data/"]
    assert put["env"] == {"D": "${{ needs.gate.outputs.data_sha }}"}
    order = ["Check out the gate's commit", "Check out the gate's records-data head (D)", "Put D's data/ into data/",
             "Restore document store", "Restore text and OCR caches"]
    assert [names.index(n) for n in order] == sorted(names.index(n) for n in order)


def _put_d(tmp_path, d_head: str, d_env: str, data_exists=False, empty=False):
    rd = tmp_path / ".records-data"
    rd.mkdir()
    _git(rd, "init", "-q")
    (rd / "data").mkdir()
    if not empty:
        (rd / "data" / "x.json").write_text("{}")
    else:
        (rd / "README").write_text("x")
    _git(rd, "add", "-A")
    _git(rd, "commit", "-q", "-m", "d")
    head = _git(rd, "rev-parse", "HEAD")
    if data_exists:
        (tmp_path / "data").mkdir()
    env = {**os.environ, "D": head if d_env == "head" else d_env}
    return subprocess.run(["bash", "-e", "-c", UPDATE["Put D's data/ into data/"]["run"]], cwd=tmp_path, env=env,
                          capture_output=True, text=True), head


@pytest.mark.parametrize("case", ["ok", "other-d", "bad-d", "data-exists", "empty"])
def test_putting_d_into_data(tmp_path, case):
    r, _ = _put_d(tmp_path, "", {"other-d": "b" * 40, "bad-d": "main"}.get(case, "head"),
                  data_exists=case == "data-exists", empty=case == "empty")
    if case == "ok":
        assert r.returncode == 0, r.stdout + r.stderr
        assert (tmp_path / "data" / "x.json").is_file() and not (tmp_path / ".records-data").exists()
    else:
        assert r.returncode != 0 and "::error::" in r.stdout, case


def test_the_tripwire_reads_the_same_facts_files_on_both_sides(tmp_path):
    """read_live (git) and read_disk (the folder) see the same paths for the same files, the caches left out."""
    r = Repo(tmp_path, _tree())
    r.run_data(_tree())
    (r.data / "store" / "x").mkdir(parents=True)
    (r.data / "store" / "x" / "facts.json").write_text("{", encoding="utf-8")   # a cache: never read
    _git(r.work, "fetch", "-q", "origin", "+refs/heads/records-data:refs/tripwire/records-data")
    assert sorted(tripwire.read_live(r.work, r.d)) == sorted(tripwire.read_disk(r.data)) == [
        "data/facts.json", "data/localities/clarksville-tn/facts.json", "data/localities/cmc-rpc/rpc.json"]
    assert data_shape.problems(data_shape.disk_listing(r.data)) == []
