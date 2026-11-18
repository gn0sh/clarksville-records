"""scripts/fetch-data.{sh,ps1} (ADR 0011 decision 1; task D2): fill data/ from origin/records-data, never commit.

The .sh runs here on throwaway local repositories (a bare origin in tmp_path; no network); the .ps1 (no PowerShell
here) is pinned to the same steps and lines text by text. Before the cutover data/ is tracked on main, so on this
checkout (and on any fresh clone of main today) fetch-data is the no-op: test_fetch_data_is_a_no_op_on_this_checkout."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SH = ROOT / "scripts" / "fetch-data.sh"
PS1 = ROOT / "scripts" / "fetch-data.ps1"

pytestmark = pytest.mark.skipif(shutil.which("tar") is None, reason="tar is needed by the script")


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",
                           "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def _write(base: Path, files: dict):
    for rel, text in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def _origin(tmp_path, main_files, data_files=None, extra_on_data=None):
    """A bare origin: main holds main_files; records-data (if data_files) is a parentless commit whose tree is
    data_files (plus extra_on_data, to test the refusal)."""
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    w = tmp_path / "seed"
    w.mkdir()
    _git(w, "init", "-q")
    _write(w, main_files)
    _git(w, "add", "-A")
    _git(w, "commit", "-q", "-m", "main")
    _git(w, "push", "-q", str(bare), "HEAD:refs/heads/main")
    if data_files is not None:
        _git(w, "checkout", "-q", "--orphan", "records-data")
        _git(w, "rm", "-rq", "--cached", ".")
        for p in list(w.iterdir()):
            if p.name != ".git":
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        _write(w, {**data_files, **(extra_on_data or {})})
        _git(w, "add", "-A", "-f")
        _git(w, "commit", "-q", "-m", "seed")
        _git(w, "push", "-q", str(bare), "HEAD:refs/heads/records-data")
    return bare


def _clone(tmp_path, bare):
    c = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(bare), str(c))
    return c


def _state(c):
    """Everything fetch-data must never change: HEAD, branches, index and the tracked tree's status."""
    return (_git(c, "rev-parse", "HEAD"), _git(c, "for-each-ref", "--format=%(refname)", "refs/heads"),
            _git(c, "ls-files", "-s"), _git(c, "status", "--porcelain"), _git(c, "log", "--all", "--format=%H"))


def _run(cwd, script=SH):
    env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
    return subprocess.run(["bash", str(script)], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)


AFTER_MAIN = {".gitignore": "data/\n", "sitegen/x.py": "x = 1\n"}
DATA = {"data/manifest.json": '{"a": 1}\n', "data/council/2026-11-17.json": "[]\n", "data/changes.jsonl": "{}\n"}


def test_fetch_data_fills_data_from_records_data_and_commits_nothing(tmp_path):
    bare = _origin(tmp_path, AFTER_MAIN, DATA)
    c = _clone(tmp_path, bare)
    before = _state(c)
    r = _run(c)
    assert r.returncode == 0, r.stdout + r.stderr
    d = _git(bare, "rev-parse", "records-data")
    assert r.stdout.strip().splitlines()[-1] == f"data/ is now records-data {d} (3 files). Nothing was committed."
    for rel, text in DATA.items():
        assert (c / rel).read_text() == text
    assert sorted(str(p.relative_to(c)) for p in (c / "data").rglob("*") if p.is_file()) == sorted(DATA)
    # HEAD, branches, index, status and history are as before; only the remote-tracking ref is new
    after = _state(c)
    assert after[:4] == before[:4]
    assert _git(c, "rev-parse", "refs/remotes/origin/records-data") == d
    work = c / ".git" / "fetch-data"
    assert not (work / "new" / "data").exists() and not (work / "data.tar").exists()


def test_fetch_data_keeps_the_previous_data_aside_and_replaces_it(tmp_path):
    bare = _origin(tmp_path, AFTER_MAIN, DATA)
    c = _clone(tmp_path, bare)
    _write(c, {"data/stale.json": "old\n", "data/manifest.json": "local edit\n"})
    r = _run(c)
    assert r.returncode == 0, r.stdout + r.stderr
    prev = c / ".git" / "fetch-data" / "previous"
    assert f"The data/ that was here is now at {prev} (replaced on the next run)." in r.stdout
    assert (prev / "stale.json").read_text() == "old\n" and not (c / "data" / "stale.json").exists()
    assert (c / "data" / "manifest.json").read_text() == DATA["data/manifest.json"]
    assert _git(c, "status", "--porcelain") == ""
    r = _run(c)                                          # a second run replaces the kept copy
    assert r.returncode == 0 and (prev / "manifest.json").read_text() == DATA["data/manifest.json"]


def test_fetch_data_is_a_no_op_while_data_is_tracked(tmp_path):
    """Before the cutover main tracks data/: nothing is fetched or changed, even when origin has records-data."""
    bare = _origin(tmp_path, {"data/manifest.json": "tracked\n", "sitegen/x.py": "x = 1\n"}, DATA)
    c = _clone(tmp_path, bare)
    before = _state(c)
    r = _run(c)
    assert r.returncode == 0 and r.stdout.strip() == (
        "data/ is tracked on this checkout (before the ADR 0011 cutover): nothing to fetch. Nothing was changed.")
    assert _state(c) == before and (c / "data" / "manifest.json").read_text() == "tracked\n"
    refs = _git(c, "for-each-ref", "--format=%(refname) %(objectname)")
    _git(bare, "update-ref", "refs/heads/records-data", _git(bare, "rev-parse", "main"))   # origin moved: not fetched
    assert _run(c).returncode == 0 and _git(c, "for-each-ref", "--format=%(refname) %(objectname)") == refs
    assert not (c / ".git" / "fetch-data").exists()


def test_fetch_data_is_a_no_op_on_this_checkout():
    """D2's done-when before the cutover: on this checkout (data/ tracked) fetch-data changes nothing and makes no
    network call, so a fresh clone that runs it then runs the full suite exactly as without it."""
    tracked = subprocess.run(["git", "ls-files", "--", "data"], cwd=ROOT, capture_output=True, text=True).stdout
    if not tracked.strip():
        pytest.skip("data/ is no longer tracked here (after the cutover)")
    r = _run(ROOT)
    assert r.returncode == 0 and "nothing to fetch. Nothing was changed." in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("case,says", [
    ("extra-top-level", "holds 'data,sitegen', not only data/. Nothing was changed."),
    ("no-branch", "Could not fetch records-data from origin. Nothing was changed."),
    ("not-ignored", "data/ is neither tracked nor ignored on this checkout"),
])
def test_fetch_data_refuses_and_leaves_data_unchanged(tmp_path, case, says):
    main = AFTER_MAIN if case != "not-ignored" else {"sitegen/x.py": "x = 1\n"}
    data = None if case == "no-branch" else DATA
    extra = {"sitegen/evil.py": "boom\n"} if case == "extra-top-level" else None
    bare = _origin(tmp_path, main, data, extra)
    c = _clone(tmp_path, bare)
    _write(c, {"data/mine.json": "keep\n"})
    before = _state(c)
    r = _run(c)
    assert r.returncode == 1 and says in r.stdout, r.stdout + r.stderr
    assert (c / "data" / "mine.json").read_text() == "keep\n" and not (c / "data" / "manifest.json").exists()
    assert _state(c)[:3] == before[:3]
    assert not (c / "sitegen" / "evil.py").exists()


def test_fetch_data_scripts_never_commit_push_or_touch_the_index():
    for path in (SH, PS1):
        text = path.read_text(encoding="utf-8")
        code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        for bad in ("git commit", "git push", "git add", "git checkout", "git switch", "git reset", "git worktree",
                    "git stash", "update-ref", "read-tree", "gh "):
            assert bad not in code, (path.name, bad)
        assert "refs/heads/records-data:refs/remotes/origin/records-data" in code
        assert "git archive --format=tar" in code and "git check-ignore -q data/" in code


def test_fetch_data_ps1_matches_the_sh():
    sh, ps1 = SH.read_text(encoding="utf-8"), PS1.read_text(encoding="utf-8")
    lines = ["data/ is tracked on this checkout (before the ADR 0011 cutover): nothing to fetch. Nothing was changed.",
             "data/ is neither tracked nor ignored on this checkout, so it could be committed by mistake. "
             "Nothing was changed. Send this output to the team.",
             "Could not fetch records-data from origin. Nothing was changed.",
             "origin has no records-data commit. Nothing was changed.",
             "not only data/. Nothing was changed. Send this output to the team.",
             "failed. Nothing was changed.", "Could not unpack records-data $d. Nothing was changed.",
             "Nothing was changed. Send this output to the team.",
             "Could not move the current data/ aside. Nothing was changed.",
             "(replaced on the next run).", "($want files). Nothing was committed.",
             "git ls-files -- data", "git rev-parse --absolute-git-dir", "git ls-tree --name-only",
             "git ls-tree -r --name-only", "refs/remotes/origin/records-data^{commit}", "--no-tags",
             "has data as mode $", ", not a folder (040000). Nothing was changed. Send this output to the team.",
             "holds a symlink or submodule under data/ ($links). Nothing was changed. Send this output to the team.",
             "(120000|160000) ", "Could not remove the old $", ". Nothing was changed. Send this output to the team."]
    for ln in lines:
        assert ln in sh, ln
        assert ln in ps1, ln
    # the archive goes to a file, never through a PowerShell pipe (PowerShell 5.1 re-encodes piped bytes)
    assert '"--output=$tar"' in ps1 and "| tar" not in ps1 and "git archive" in ps1
    assert not re.search(r"git archive[^\n]*\|", ps1)
    assert "-ExecutionPolicy Bypass" not in ps1.replace("never -ExecutionPolicy Bypass", "")
    assert "$ErrorActionPreference = 'Continue'" in ps1


def test_the_preflight_doc_and_claude_md_name_fetch_data():
    pre = (ROOT / "docs" / "ops" / "preflight.md").read_text(encoding="utf-8")
    assert "scripts/fetch-data.sh" in pre and "scripts\\fetch-data.ps1" in pre and "python -m pytest -q" in pre
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    this_repo = claude[claude.index("## This repo"):]
    assert "records-data" in this_repo and "scripts/fetch-data" in this_repo and "docs/ops/preflight.md" in this_repo


def _origin_with_tree(tmp_path, build):
    """A bare origin whose main ignores data/ and whose records-data tree is made by build(seed worktree)."""
    bare = _origin(tmp_path, AFTER_MAIN)
    w = tmp_path / "seed"
    _git(w, "checkout", "-q", "--orphan", "records-data")
    _git(w, "rm", "-rq", "--cached", ".")
    for p in list(w.iterdir()):
        if p.name != ".git":
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    build(w)
    _git(w, "commit", "-q", "-m", "seed")
    _git(w, "push", "-q", str(bare), "HEAD:refs/heads/records-data")
    return bare


def _symlinked_data(w):
    os.symlink("/etc", w / "data")
    _git(w, "add", "-A", "-f")


def _symlink_inside(w):
    _write(w, DATA)
    os.symlink("/etc/passwd", w / "data" / "council" / "leak.json")
    _git(w, "add", "-A", "-f")


def _submodule_inside(w):
    _write(w, DATA)
    _git(w, "add", "-A", "-f")
    _git(w, "update-index", "--add", "--cacheinfo", "160000," + "1" * 40 + ",data/vendor")


def _data_is_a_file(w):
    _write(w, {"data": "not a folder\n"})
    _git(w, "add", "-A", "-f")


@pytest.mark.parametrize("build,says", [
    (_symlinked_data, "has data as mode 120000, not a folder (040000). Nothing was changed."),
    (_data_is_a_file, "has data as mode 100644, not a folder (040000). Nothing was changed."),
    (_symlink_inside, "holds a symlink or submodule under data/ (data/council/leak.json). Nothing was changed."),
    (_submodule_inside, "holds a symlink or submodule under data/ (data/vendor). Nothing was changed."),
], ids=["data-symlink", "data-file", "symlink-inside", "submodule-inside"])
def test_fetch_data_refuses_symlinks_and_submodules(tmp_path, build, says):
    bare = _origin_with_tree(tmp_path, build)
    c = _clone(tmp_path, bare)
    _write(c, {"data/mine.json": "keep\n"})
    before = _state(c)
    r = _run(c)
    assert r.returncode == 1 and says in r.stdout, r.stdout + r.stderr
    assert (c / "data" / "mine.json").read_text() == "keep\n" and not (c / "data").is_symlink()
    assert _state(c)[:3] == before[:3]
    assert not (c / ".git" / "fetch-data" / "new" / "data").exists()


def test_fetch_data_ps1_checks_modes_like_the_sh():
    ps1 = PS1.read_text(encoding="utf-8")
    assert "$topMode = ((@(git ls-tree $d data)) -join '').Split(' ')[0]" in ps1
    assert "if ($topMode -cne '040000') {" in ps1
    assert "@(git ls-tree -r $d -- data) | Where-Object { $_ -cmatch '^(120000|160000) ' }" in ps1
    arch = ps1.index("git archive --format")
    assert ps1.index("$topMode") < arch and ps1.index("$links") < arch
    assert "if (Test-Path -LiteralPath $previous) {" in ps1
    assert ps1.index("if (Test-Path -LiteralPath $previous) {") < ps1.index("Move-Item -LiteralPath 'data'")


def test_fetch_data_fails_when_the_old_previous_cannot_be_removed(tmp_path):
    """A partly removed previous/ must not get data/ moved inside it (previous/data): fail, data/ unchanged. An rm
    on PATH that leaves previous/ in place stands in for a locked file (Windows) or a read-only folder."""
    bare = _origin(tmp_path, AFTER_MAIN, DATA)
    c = _clone(tmp_path, bare)
    _write(c, {"data/mine.json": "keep\n"})
    prev = c / ".git" / "fetch-data" / "previous"
    _write(prev, {"locked/old.json": "old\n"})
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "rm").write_text('#!/usr/bin/env bash\nfor a; do case "$a" in */previous) exit 1 ;; esac; done\n'
                             'exec /bin/rm "$@"\n')
    (shim / "rm").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
    env["PATH"] = f"{shim}:{env['PATH']}"
    r = subprocess.run(["bash", str(SH)], cwd=c, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and f"Could not remove the old {prev}. Nothing was changed." in r.stdout, r.stdout + r.stderr
    assert (c / "data" / "mine.json").read_text() == "keep\n" and not (prev / "data").exists()
    assert (prev / "locked" / "old.json").read_text() == "old\n"


def test_fetch_data_sh_checks_previous_is_gone_before_the_move():
    sh = SH.read_text(encoding="utf-8")
    assert '  if [ -e "$work/previous" ] || [ -L "$work/previous" ]; then' in sh
    assert sh.index('[ -L "$work/previous" ]') < sh.index('mv data "$work/previous"')
