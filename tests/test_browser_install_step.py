"""The daily update's browser install and Tests steps (daily-update.yml, job update): security review bbc603a F1-F5 and
code review bbc603a #1, #2 and #6. The install step puts exactly tests/playwright/package-lock.json (npm ci
--ignore-scripts) outside the checkout, then Playwright's Chromium, and checks the installed tree against
tests/playwright/browsers.sha256 before anything runs it: a mismatch fails the job, always; a download that keeps failing
is a warning and browsers=missing, so the browser tests skip while the national switch is off. The steps run here with
stub npm, node, playwright, sleep and python on PATH; no test sends a request anywhere."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DAILY_PATH = ROOT / ".github" / "workflows" / "daily-update.yml"
DAILY = yaml.safe_load(DAILY_PATH.read_text(encoding="utf-8"))
PW_DIR = ROOT / "tests" / "playwright"
MANIFEST = PW_DIR / "browsers.sha256"
INSTALL = "Install Playwright and Chromium (browser tests)"
TESTS = "Tests (full suite, about 12 min, default settings)"
# Playwright version in package-lock.json -> its chromium revision (playwright-core browsers.json). A lock bump without a
# new browsers.sha256 (tests/playwright/browsers-sha256.sh) fails here, not on the runner.
REVISIONS = {"1.63.0": "1243"}
BASH = ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c"]   # a run step's default shell on GitHub
LINE = re.compile(r"[0-9a-f]{64}  (chromium|chromium_headless_shell)-[0-9]+/[A-Za-z0-9._/@+-]+")


def _steps(job="update") -> dict:
    return {s.get("name"): s for s in DAILY["jobs"][job]["steps"]}


def _names(job="update") -> list:
    return [s.get("name") for s in DAILY["jobs"][job]["steps"]]


def _run_lines(step) -> list:
    return [ln.strip() for ln in step["run"].splitlines() if ln.strip() and not ln.strip().startswith("#")]


# ------------------------------------------------------------------------------------------------ shape (F5 / CR #2)

def test_the_install_step_is_pinned_scoped_and_untokened():
    step = _steps()[INSTALL]
    run = step["run"]
    assert step["id"] == "browsers" and "continue-on-error" not in step and "if" not in step
    assert isinstance(step["timeout-minutes"], int) and 0 < step["timeout-minutes"] <= 60
    assert step["env"] == {"PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS": "1"}       # no token, no secret
    assert "${{" not in run and "secrets" not in run and "TOKEN" not in run.upper()
    assert 'pw="$RUNNER_TEMP/playwright"' in run and 'br="$RUNNER_TEMP/pw-browsers"' in run
    assert 'echo "PLAYWRIGHT_BROWSERS_PATH=$br" >> "$GITHUB_ENV"' in run and "GITHUB_PATH" not in run
    # only the two lock files leave the checkout, into the prefix; npm ci (never install) with no package scripts
    cps = [ln for ln in _run_lines(step) if re.match(r"(sudo )?cp\b", ln)]
    assert cps == ['cp tests/playwright/package.json tests/playwright/package-lock.json "$pw/"']
    assert run.count('npm ci --prefix "$pw" --ignore-scripts --no-audit --no-fund >') == 1
    assert run.count("npm ci --") == 1 and not re.findall(r"\bnpm (?!ci\b)\w", run)
    assert "npx" not in run and "--with-deps" not in run and "--only-shell" not in run and "curl" not in run
    assert run.count('"$pw/node_modules/.bin/playwright" install chromium') == 1
    assert run.count('"$pw/node_modules/.bin/playwright" install-deps chromium') == 1
    # F1: the tree check comes after the download and before the step says ok; the step is the one place it is said
    i_dl, i_check = run.index("install chromium;"), run.index("sha256sum --quiet --strict -c")
    assert i_dl < i_check < run.index('echo "browsers=ok" >> "$GITHUB_OUTPUT"')
    assert run.count("browsers=ok") == 1 and "set -euo pipefail" in run
    # F4: Node 20 or newer, its version printed; no setup-node anywhere in the job
    assert 'echo "node $(node --version)"' in run and '[ "$major" -ge 20 ]' in run
    assert not [s for s in DAILY["jobs"]["update"]["steps"] if "setup-node" in str(s.get("uses", ""))]


def test_the_install_step_comes_right_before_the_tests_and_after_the_site_checks():
    names = _names()
    assert names.index(INSTALL) + 1 == names.index(TESTS)
    assert names.index("Site checks") < names.index(INSTALL)
    # nothing before the check runs a browser: the only earlier site check is told not to
    assert "--no-browser" in _steps()["Site checks"]["run"]


def test_the_tests_step_finds_the_checked_playwright_and_reruns_failures_once():
    step = _steps()[TESTS]
    assert step["env"] == {"NODE_PATH": "${{ runner.temp }}/playwright/node_modules",
                           "BROWSERS": "${{ steps.browsers.outputs.browsers }}"}
    assert _run_lines(step) == [
        'if [ "${BROWSERS:-}" = ok ]; then PATH="$RUNNER_TEMP/playwright/node_modules/.bin:$PATH"; fi',
        'python -m pytest -q || { echo "::warning::tests failed once; rerunning the failures"; python -m pytest -q --lf; }']
    assert "GITHUB_PATH" not in step["run"] and " -x" not in step["run"] and "continue-on-error" not in step
    # the PATH and NODE_PATH prefixes are the install step's prefix
    assert 'pw="$RUNNER_TEMP/playwright"' in _steps()[INSTALL]["run"]


def test_no_other_step_puts_playwright_on_path_or_sets_the_browsers_path():
    for job, spec in DAILY["jobs"].items():
        for s in spec.get("steps", []):
            if s.get("name") in (INSTALL, TESTS):
                continue
            text = json.dumps(s)
            assert "GITHUB_PATH" not in text and "PLAYWRIGHT_BROWSERS_PATH" not in text, (job, s.get("name"))


def test_the_browsers_sha256_list_matches_the_locked_playwright():
    lock = json.loads((PW_DIR / "package-lock.json").read_text(encoding="utf-8"))
    version = lock["packages"]["node_modules/playwright-core"]["version"]
    assert lock["packages"]["node_modules/playwright"]["version"] == version and version in REVISIONS
    rev = REVISIONS[version]
    lines = MANIFEST.read_text(encoding="ascii").splitlines()
    assert lines and all(LINE.fullmatch(ln) for ln in lines)
    paths = [ln[66:] for ln in lines]
    assert paths == sorted(paths, key=lambda p: p.encode()) and len(set(paths)) == len(paths)
    assert {p.split("/")[0] for p in paths} == {f"chromium-{rev}", f"chromium_headless_shell-{rev}"}
    for p in (f"chromium-{rev}/chrome-linux64/chrome", f"chromium_headless_shell-{rev}/chrome-headless-shell-linux64/"
              "chrome-headless-shell", f"chromium-{rev}/INSTALLATION_COMPLETE"):
        assert p in paths, p
    assert not [p for p in paths if "DEPENDENCIES_VALIDATED" in p or "/../" in p]


# ------------------------------------------------------------------------------------------------ behaviour (F1, CR #1)

FAKE = {"chromium-1243/INSTALLATION_COMPLETE": "", "chromium-1243/chrome-linux64/chrome": "chrome bytes\n",
        "chromium-1243/chrome-linux64/locales/en-US.pak": "pak\n",
        "chromium_headless_shell-1243/INSTALLATION_COMPLETE": "",
        "chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell": "shell bytes\n"}


def _manifest(files: dict) -> str:
    return "".join(f"{hashlib.sha256(files[p].encode()).hexdigest()}  {p}\n" for p in sorted(files, key=str.encode))


def _stub(path: Path, text: str):
    path.write_text("#!/bin/bash\n" + text)
    path.chmod(0o755)


def _install(tmp_path, *, node="22.11.0", npm_fails=0, npm_integrity=False, deps_fails=0, dl_fails=0, tamper=None):
    """Runs the install step in a fake checkout with stubs; returns (process, outputs, env file, calls, browsers dir)."""
    work, bindir, runner = tmp_path / "work", tmp_path / "bin", tmp_path / "runner"
    (work / "tests" / "playwright").mkdir(parents=True)
    for name in ("package.json", "package-lock.json"):
        (work / "tests" / "playwright" / name).write_text((PW_DIR / name).read_text(encoding="utf-8"))
    (work / "tests" / "playwright" / "browsers.sha256").write_text(_manifest(FAKE))
    bindir.mkdir()
    runner.mkdir()
    tree = tmp_path / "tree"
    for rel, text in FAKE.items():
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_text(text)
    (tree / "ffmpeg-1011").mkdir()
    (tree / "ffmpeg-1011" / "ffmpeg-linux").write_text("unchecked\n")
    (tree / ".links").mkdir()
    (tree / ".links" / "0123abcd").write_text("/x/playwright-core")
    if tamper:
        tamper(tree)
    calls, count = tmp_path / "calls", tmp_path / "count"
    count.mkdir()
    # a stub fails its first N calls: count/<name> holds the calls so far
    fail_first = ('n=$(( $(cat "{c}/$1" 2>/dev/null || echo 0) + 1 )); echo "$n" > "{c}/$1"; '
                  '[ "$n" -gt "$2" ]').format(c=count)
    _stub(bindir / "attempt", fail_first + "\n")
    pwbin = ("#!/bin/bash\n"
             f'echo "playwright $*" >> "{calls}"\n'
             'case "$1" in\n'
             '  --version) echo "Version 1.63.0" ;;\n'
             f'  install-deps) {bindir}/attempt deps {deps_fails} ;;\n'
             f'  install) {bindir}/attempt dl {dl_fails} || exit 1; mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"; '
             f'cp -a "{tree}/." "$PLAYWRIGHT_BROWSERS_PATH/" ;;\n'
             'esac\n')
    _stub(bindir / "npm", f'echo "npm $*" >> "{calls}"\n'
                          + ('echo "npm error code EINTEGRITY"; exit 1\n' if npm_integrity else "")
                          + f'{bindir}/attempt npm {npm_fails} || {{ echo "npm error network"; exit 1; }}\n'
                          'mkdir -p "$3/node_modules/.bin"\n'
                          f"cat > \"$3/node_modules/.bin/playwright\" <<'EOF'\n{pwbin}EOF\n"
                          'chmod +x "$3/node_modules/.bin/playwright"\n')
    _stub(bindir / "node", f'if [ "$1" = --version ]; then echo "v{node}"; else echo "{node.split(".")[0]}"; fi\n')
    _stub(bindir / "sleep", f'echo "sleep $*" >> "{calls}"\n')
    out, envf = tmp_path / "out", tmp_path / "envfile"
    env = {"PATH": f"{bindir}:/usr/bin:/bin", "RUNNER_TEMP": str(runner), "GITHUB_OUTPUT": str(out),
           "GITHUB_ENV": str(envf), "HOME": str(tmp_path), **_steps()[INSTALL]["env"]}
    r = subprocess.run([*BASH, _steps()[INSTALL]["run"]], cwd=work, env=env, capture_output=True,
                       text=True, timeout=120)
    return r, _read(out), _read(envf), _read(calls).splitlines(), runner / "pw-browsers"


def _read(f: Path) -> str:
    return f.read_text() if f.exists() else ""


def test_a_good_install_is_checked_and_says_ok(tmp_path):
    r, out, envf, calls, br = _install(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out == "browsers=ok\n" and envf == f"PLAYWRIGHT_BROWSERS_PATH={br}\n"
    assert "Chromium checked: 5 files match" in r.stdout and "node v22.11.0" in r.stdout
    assert not (br / "ffmpeg-1011").exists() and (br / "chromium-1243" / "chrome-linux64" / "chrome").is_file()
    assert calls[0].startswith("npm ci --prefix ") and calls[0].endswith(" --ignore-scripts --no-audit --no-fund")
    assert calls[1:] == ["playwright --version", "playwright install-deps chromium", "playwright install chromium"]


def test_downloads_are_tried_three_times_30_then_90_seconds_apart(tmp_path):
    r, out, _e, calls, _b = _install(tmp_path, npm_fails=2, deps_fails=1, dl_fails=2)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out == "browsers=ok\n"
    assert [c for c in calls if c.startswith("sleep")] == ["sleep 30", "sleep 90", "sleep 30", "sleep 30", "sleep 90"]
    assert r.stdout.count("::warning::") == 5


@pytest.mark.parametrize("kw,why", [({"npm_fails": 3}, "npm ci failed three times."),
                                    ({"deps_fails": 3}, "the system libraries install failed three times."),
                                    ({"dl_fails": 3}, "the Chromium download failed three times."),
                                    ({"node": "18.20.4"}, "Node 20 or newer is needed (Playwright 1.63).")],
                         ids=["npm", "apt", "download", "old-node"])
def test_a_download_that_keeps_failing_is_a_warning_and_no_browser(tmp_path, kw, why):
    """Code review bbc603a #1 and the manager's resolution: after three tries the job goes on with no browser (the
    browser tests skip while the switch is off) and nothing unchecked is left behind."""
    r, out, _e, calls, br = _install(tmp_path, **kw)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out == "browsers=missing\n" and not br.exists()
    assert f"::warning::Browser tests: {why} The browser tests skip this run" in r.stdout
    assert "::error::" not in r.stdout
    if kw.get("dl_fails"):
        assert calls.count("playwright install chromium") == 3


def _add(rel, text="x\n"):
    def f(tree):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_text(text)
    return f


@pytest.mark.parametrize("tamper", [
    lambda t: (t / "chromium-1243" / "chrome-linux64" / "chrome").write_text("other bytes\n"),
    lambda t: (t / "chromium-1243" / "chrome-linux64" / "locales" / "en-US.pak").unlink(),
    _add("chromium-1243/chrome-linux64/extra.so"),
    _add("chromium-1243/DEPENDENCIES_VALIDATED", ""),
    _add("webkit-2359/x"),
    _add(".hidden"),
    lambda t: (t / ".links" / "sub").mkdir(),
    lambda t: ((t / "chromium-1243" / "chrome-linux64" / "chrome").unlink(),
               (t / "chromium-1243" / "chrome-linux64" / "chrome").symlink_to(t / "chromium_headless_shell-1243")),
    lambda t: (t / "chromium-1243" / "chrome-linux64" / "link").symlink_to("/etc/passwd"),
], ids=["changed", "missing", "extra-file", "launched-marker", "extra-folder", "extra-top-file", "links-dir",
        "symlink-swapped", "symlink-added"])
def test_any_difference_from_the_sha256_list_fails_the_step(tmp_path, tamper):
    """Security review bbc603a F1: hash mismatch = hard fail, always, never browsers=ok or a warning."""
    r, out, _e, _c, _b = _install(tmp_path, tamper=tamper)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "browsers=" not in out
    assert "::error::The installed Chromium does not match tests/playwright/browsers.sha256" in r.stdout


def test_a_malformed_sha256_list_fails_the_step(tmp_path):
    def bad(tree):   # run before the step: the step reads the fake checkout's list
        (tmp_path / "work" / "tests" / "playwright" / "browsers.sha256").write_text("not a list\n")
    r, out, _e, _c, _b = _install(tmp_path, tamper=bad)
    assert r.returncode == 1 and "the list is malformed" in r.stdout and "browsers=" not in out


def test_an_npm_integrity_failure_fails_the_step(tmp_path):
    r, out, _e, calls, _b = _install(tmp_path, npm_integrity=True)
    assert r.returncode == 1 and "browsers=" not in out
    assert "::error::npm ci: a package does not match its sha512" in r.stdout
    assert len([c for c in calls if c.startswith("npm ")]) == 1          # not retried


def _tests_step(tmp_path, browsers, fails):
    """The Tests step with a stub python that fails its first `fails` calls; returns (process, calls)."""
    bindir, calls = tmp_path / "bin", tmp_path / "calls"
    bindir.mkdir()
    _stub(bindir / "python", f'echo "$* | $PATH" >> "{calls}"\n'
                             f'n=$(wc -l < "{calls}"); [ "$n" -gt {fails} ]\n')
    env = {"PATH": f"{bindir}:/usr/bin:/bin", "RUNNER_TEMP": "/rt", "BROWSERS": browsers,
           "NODE_PATH": "/rt/playwright/node_modules"}
    r = subprocess.run([*BASH, _steps()[TESTS]["run"]], env=env, capture_output=True, text=True)
    return r, calls.read_text().splitlines()


@pytest.mark.parametrize("browsers,on_path", [("ok", True), ("missing", False), ("", False)])
def test_playwright_is_on_path_for_the_tests_only_when_its_browser_was_checked(tmp_path, browsers, on_path):
    r, calls = _tests_step(tmp_path, browsers, 0)
    assert r.returncode == 0 and len(calls) == 1 and calls[0].startswith("-m pytest -q | ")
    assert calls[0].split(" | ")[1].startswith("/rt/playwright/node_modules/.bin:") is on_path


@pytest.mark.parametrize("fails,rc,runs", [(0, 0, 1), (1, 0, 2), (2, 1, 2)])
def test_a_failed_run_is_rerun_once_on_its_failures(tmp_path, fails, rc, runs):
    r, calls = _tests_step(tmp_path, "ok", fails)
    assert (r.returncode != 0) is bool(rc) and len(calls) == runs
    if runs == 2:
        assert calls[1].startswith("-m pytest -q --lf | ") and "::warning::tests failed once" in r.stdout
