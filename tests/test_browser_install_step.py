"""The daily update's browser install and Tests steps (daily-update.yml, job update): security review bbc603a F1-F5,
code review bbc603a #1, #2 and #6, and security re-check a84d19d R1-R3 (docs/architecture/
ci-download-verify-invariant.md, T1-T12). The install step puts exactly tests/playwright/package-lock.json (npm ci
--ignore-scripts) outside the checkout, then curls the two Chrome for Testing zips into a new, empty folder, checks them
against tests/playwright/browser-zips.sha256, and only then unzips them and checks the unpacked tree against
tests/playwright/browsers.sha256 before anything runs it: a mismatch fails the job, always; a download that keeps failing
is a warning and browsers=missing (the browser tests skip while the national switch is off; on main one issue says so).
The steps run here with stub npm, node, playwright, curl (serving zips built here), sleep, gh and python on PATH, and
the real unzip behind a logging stub; no test sends a request anywhere."""
import hashlib
import json
import os
import re
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DAILY_PATH = ROOT / ".github" / "workflows" / "daily-update.yml"
NATIONAL_PATH = ROOT / ".github" / "workflows" / "national-update.yml"
DAILY = yaml.safe_load(DAILY_PATH.read_text(encoding="utf-8"))
NATIONAL = yaml.safe_load(NATIONAL_PATH.read_text(encoding="utf-8"))
PW_DIR = ROOT / "tests" / "playwright"
MANIFEST = PW_DIR / "browsers.sha256"
ZIPLIST = PW_DIR / "browser-zips.sha256"
INSTALL = "Install Playwright and Chromium (browser tests)"
TESTS = "Tests (full suite, about 12 min, default settings)"
ISSUE = "Open or update the browser-tests-skipped issue"
BR_TITLE = "Daily update: browser tests skipped (Chromium not installed)"
# Playwright version in package-lock.json -> (its chromium revision in playwright-core browsers.json, the Chrome for
# Testing version it downloads). A lock bump without new folders, URL and both .sha256 files fails here, not on the runner.
REVISIONS = {"1.63.0": ("1243", "153.0.8010.12")}
CFT = "https://storage.googleapis.com/chrome-for-testing-public/{}/linux64"
ZIPS = ("chrome-linux64.zip", "chrome-headless-shell-linux64.zip")
PINNED_ZIPS = ("8aac35011c18f6e2d10696154af89a5728ac2ddd6dc6fad24ffdf243c3fcfd5a  chrome-linux64.zip\n"
               "a9da028861a0cf789ff25c2fed45f5f1aaf969ed9247835b6a7821a4f7af9d1d  chrome-headless-shell-linux64.zip\n")
CURL_FLAGS = "--fail --location --proto '=https' --proto-redir '=https' --max-time 300 --max-filesize 268435456"
BASH = ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c"]   # a run step's default shell on GitHub
LINE = re.compile(r"[0-9a-f]{64}  (chromium|chromium_headless_shell)-[0-9]+/[A-Za-z0-9._/@+-]+")


def _steps(job="update", wf=None) -> dict:
    return {s.get("name"): s for s in (wf or DAILY)["jobs"][job]["steps"]}


def _names(job="update") -> list:
    return [s.get("name") for s in DAILY["jobs"][job]["steps"]]


def _run_lines(step) -> list:
    return [ln.strip() for ln in step["run"].splitlines() if ln.strip() and not ln.strip().startswith("#")]


def _all_run_lines(wf) -> list:
    return [ln for spec in wf["jobs"].values() for s in spec.get("steps", []) if "run" in s for ln in _run_lines(s)]


# ------------------------------------------------------------------------------------------------ shape (F5 / CR #2)

def test_the_install_step_is_pinned_scoped_and_untokened():
    step = _steps()[INSTALL]
    run = step["run"]
    assert step["id"] == "browsers" and "continue-on-error" not in step and "if" not in step
    assert step["timeout-minutes"] == 70                                        # R2
    assert step["env"] == {"PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS": "1"}       # no token, no secret
    assert "${{" not in run and "secrets" not in run and "TOKEN" not in run.upper()
    assert 'pw="$RUNNER_TEMP/playwright"' in run and 'br="$RUNNER_TEMP/pw-browsers"' in run
    assert 'zips=$(mktemp -d "$RUNNER_TEMP/pw-zips.XXXXXXXXXX")' in run
    assert 'echo "PLAYWRIGHT_BROWSERS_PATH=$br" >> "$GITHUB_ENV"' in run and "GITHUB_PATH" not in run
    # only the two lock files leave the checkout, into the prefix; npm ci (never install) with no package scripts
    cps = [ln for ln in _run_lines(step) if re.match(r"(sudo )?cp\b", ln)]
    assert cps == ['cp tests/playwright/package.json tests/playwright/package-lock.json "$pw/"']
    assert run.count('npm ci --prefix "$pw" --ignore-scripts --no-audit --no-fund >') == 1
    assert run.count("npm ci --") == 1 and not re.findall(r"\bnpm (?!ci\b)\w", run)
    assert "npx" not in run and "--with-deps" not in run and "--only-shell" not in run
    assert run.count('"$pw/node_modules/.bin/playwright" install-deps chromium') == 1
    assert "command -v unzip > /dev/null || missing" in run
    assert run.count("browsers=ok") == 1 and "set -euo pipefail" in run
    # F4: Node 20 or newer, its version printed; no setup-node anywhere in the job
    assert 'echo "node $(node --version)"' in run and '[ "$major" -ge 20 ]' in run
    assert not [s for s in DAILY["jobs"]["update"]["steps"] if "setup-node" in str(s.get("uses", ""))]


def test_t1_no_playwright_install_and_exactly_two_pinned_curls():
    """R1: Playwright never fetches the browser; the only fetch is curl of two fixed https URLs, with all five flags."""
    for path in (DAILY_PATH, NATIONAL_PATH):
        text = path.read_text(encoding="utf-8")
        assert "install chromium" not in text and "playwright install " not in text, path.name
        assert "wget" not in text and "release download" not in text, path.name
    assert DAILY_PATH.read_text(encoding="utf-8").count("install-deps chromium") == 1
    assert "install-deps" not in NATIONAL_PATH.read_text(encoding="utf-8")
    run = _steps()[INSTALL]["run"]
    base = CFT.format(REVISIONS["1.63.0"][1])
    assert f'cft="{base}"' in run
    curls = [ln for ln in _all_run_lines(DAILY) + _all_run_lines(NATIONAL) if re.search(r"\bcurl\b", ln)]
    assert len(curls) == 2 and sum(len(re.findall(r"\bcurl\b", ln)) for ln in curls) == 2
    for ln, name in zip(curls, ZIPS):
        m = re.fullmatch(r"(?:&& )?curl (.*) --silent --show-error -o \"\$zips/([a-z0-9-]+\.zip)\" "
                         r"\"\$cft/([a-z0-9-]+\.zip)\"(?: \\)?", ln)
        assert m and m.group(1) == CURL_FLAGS and m.group(2) == m.group(3) == name, ln
    for bad in (" -k", "--insecure", "http://", "--retry", "-K ", "--config"):
        assert not [ln for ln in curls if bad in ln], bad
    assert "http://" not in run


def test_t2_the_bytes_are_checked_before_they_are_unpacked_and_the_tree_before_ok():
    run = _steps()[INSTALL]["run"]
    # in the order they run (download() is defined above, but only called by tries after the shape check)
    order = ["# browser-zips-shape", 'tries "npm ci" npm_ci', 'tries "The Chromium download" download',
             "# browser-zips-check",
             'sha256sum --quiet --strict -c "$zl"', "unzip -q", "# browser-tree-check",
             'sha256sum --quiet --strict -c "$man"', 'echo "browsers=ok" >> "$GITHUB_OUTPUT"']
    idx = [run.index(s) for s in order]
    assert idx == sorted(idx), list(zip(order, idx))
    assert run.index('tries "The system libraries install" deps') < run.index('tries "The Chromium download"')
    assert run.index("download() {") < run.index("# browser-zips-shape")
    assert run.count("download() {") == 1 and run.count('download || missing') == 1   # defined once, called once
    # the folders are made fresh, only after the zip check
    assert run.index('rm -rf -- "$br"\n') < run.index("zips=$(mktemp") < run.index('mkdir -p "$br/chromium-1243"')
    assert run.index('mkdir -p "$br/chromium-1243"') > run.index('sha256sum --quiet --strict -c "$zl"')


def test_t3_the_zip_list_is_the_two_pinned_lines_and_agrees_with_the_lock_and_step():
    assert ZIPLIST.read_text(encoding="ascii") == PINNED_ZIPS
    lock = json.loads((PW_DIR / "package-lock.json").read_text(encoding="utf-8"))
    version = lock["packages"]["node_modules/playwright-core"]["version"]
    assert lock["packages"]["node_modules/playwright"]["version"] == version and version in REVISIONS
    rev, cft = REVISIONS[version]
    run = _steps()[INSTALL]["run"]
    assert f'cft="{CFT.format(cft)}"' in run
    for folder, name in ((f"chromium-{rev}", "chrome-linux64.zip"),
                         (f"chromium_headless_shell-{rev}", "chrome-headless-shell-linux64.zip")):
        assert f'unzip -q -n -d "$br/{folder}" "$zips/{name}"' in run
        assert f': > "$br/{folder}/INSTALLATION_COMPLETE"' in run
    assert set(re.findall(r"chromium(?:_headless_shell)?-\d+", run)) == {f"chromium-{rev}",
                                                                          f"chromium_headless_shell-{rev}"}
    assert cft in _steps()[INSTALL]["run"] and cft in DAILY_PATH.read_text(encoding="utf-8").split(INSTALL)[0]


def test_the_install_step_comes_right_before_the_tests_and_after_the_site_checks():
    names = _names()
    assert names.index(INSTALL) + 1 == names.index(TESTS)
    assert names.index(TESTS) + 1 == names.index(ISSUE)
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
    rev = REVISIONS[version][0]
    lines = MANIFEST.read_text(encoding="ascii").splitlines()
    assert lines and all(LINE.fullmatch(ln) for ln in lines)
    paths = [ln[66:] for ln in lines]
    assert paths == sorted(paths, key=lambda p: p.encode()) and len(set(paths)) == len(paths)
    assert {p.split("/")[0] for p in paths} == {f"chromium-{rev}", f"chromium_headless_shell-{rev}"}
    for p in (f"chromium-{rev}/chrome-linux64/chrome", f"chromium_headless_shell-{rev}/chrome-headless-shell-linux64/"
              "chrome-headless-shell", f"chromium-{rev}/INSTALLATION_COMPLETE",
              f"chromium_headless_shell-{rev}/INSTALLATION_COMPLETE"):
        assert p in paths, p
    empty = hashlib.sha256(b"").hexdigest()
    assert f"{empty}  chromium-{rev}/INSTALLATION_COMPLETE" in lines   # the step's markers are empty
    assert not [p for p in paths if "DEPENDENCIES_VALIDATED" in p or "/../" in p or ".links" in p or "ffmpeg" in p]


def test_the_regeneration_note_never_uses_playwright_install():
    note = (PW_DIR / "browsers-sha256.sh").read_text(encoding="utf-8")
    assert "never from `playwright install`" in note and "browser-zips.sha256" in note and "REVISIONS" in note
    assert "install chromium" not in note


def test_t9_no_cache_holds_a_browser_or_its_zips():
    for wf in (DAILY, NATIONAL):
        for spec in wf["jobs"].values():
            for s in spec.get("steps", []):
                if "actions/cache" in str(s.get("uses", "")):
                    path = str((s.get("with") or {}).get("path", "")).lower()
                    for word in ("pw-browsers", "pw-zips", "ms-playwright", "playwright"):
                        assert word not in path, (s.get("name"), word)


def test_t10_the_step_timeout_covers_the_worst_case():
    step = _steps()[INSTALL]
    run = step["run"]
    npm = [int(x) + int(y) for y, x in re.findall(r"timeout --kill-after=(\d+) (\d+) npm ci", run)]
    deps = [int(x) + int(y) for y, x in re.findall(r"timeout --kill-after=(\d+) (\d+) \"\$pw/node_modules/\.bin/playwright\""
                                                     r" install-deps", run)]
    curl = [int(x) for x in re.findall(r"curl [^\n]*--max-time (\d+)", run)]
    pauses = [int(x) for x in re.fullmatch(r"for pause in (\d+) (\d+) last; do", next(
        ln for ln in _run_lines(step) if ln.startswith("for pause in"))).groups()]
    assert len(npm) == 1 and len(deps) == 1 and len(curl) == 2
    worst = 3 * npm[0] + 3 * deps[0] + 3 * sum(curl) + 3 * sum(pauses) + 300
    assert worst == 3990 and worst <= step["timeout-minutes"] * 60
    assert "3,990 s" in DAILY_PATH.read_text(encoding="utf-8")


def test_each_zip_download_is_capped_at_256_mib():
    """Security review c562d60 L1 (ci-supply/download-size-unbounded): curl stops a download above 256 MiB (both zips
    were 196 MB and 120 MB on 2026-11-22), so a bad mirror cannot fill the runner's disk before the hash check."""
    curls = [ln for ln in _run_lines(_steps()[INSTALL]) if re.search(r"\bcurl\b", ln)]
    assert len(curls) == 2 and all(ln.count(" --max-filesize 268435456 ") == 1 for ln in curls)
    assert 268435456 == 256 * 1024 * 1024


def test_requirements_lock_holds_no_option_lines():
    """An option line in the lock (--index-url, --extra-index-url, --trusted-host, --no-binary, -e, -r ...) would change
    where or how pip fetches, past the workflows' --require-hashes --only-binary :all: (F-pip, L1)."""
    lines = (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines()
    assert lines and not [ln for ln in lines if ln.startswith("-")]
    # the only indented options are the per-file hashes pip-compile writes under each pin
    hashes = re.compile(r"\s+--hash=sha256:[0-9a-f]{64}( \\)?")
    opts = [ln for ln in lines if ln.lstrip().startswith("-")]
    assert opts and all(hashes.fullmatch(ln) for ln in opts), [ln for ln in opts if not hashes.fullmatch(ln)]


def test_t12_both_pip_installs_take_hashed_wheels_only():
    for wf in (DAILY, NATIONAL):
        pips = [ln for ln in _all_run_lines(wf) if "pip install" in ln]
        assert len(pips) == 1 and "--require-hashes" in pips[0] and "--only-binary :all:" in pips[0], pips


# ------------------------------------------------------------------------------------------------ behaviour (F1, CR #1, R1)

FAKE = {"chromium-1243/INSTALLATION_COMPLETE": "", "chromium-1243/chrome-linux64/chrome": "chrome bytes\n",
        "chromium-1243/chrome-linux64/locales/en-US.pak": "pak\n",
        "chromium_headless_shell-1243/INSTALLATION_COMPLETE": "",
        "chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell": "shell bytes\n"}
ZIP_OF = {"chrome-linux64.zip": "chromium-1243/", "chrome-headless-shell-linux64.zip": "chromium_headless_shell-1243/"}


def _manifest(files: dict) -> str:
    return "".join(f"{hashlib.sha256(files[p].encode()).hexdigest()}  {p}\n" for p in sorted(files, key=str.encode))


def _stub(path: Path, text: str):
    path.write_text("#!/bin/bash\n" + text)
    path.chmod(0o755)


def _build_zips(src: Path, files: dict, extra=None):
    """The two test zips from files (markers excluded: the step makes them); extra(name, ZipFile) may add entries."""
    for name, prefix in ZIP_OF.items():
        with zipfile.ZipFile(src / name, "w") as z:
            for rel, text in files.items():
                if rel.startswith(prefix) and not rel.endswith("/INSTALLATION_COMPLETE"):
                    info = zipfile.ZipInfo(rel[len(prefix):])
                    info.external_attr = (stat.S_IFREG | 0o755) << 16
                    z.writestr(info, text)
            if extra:
                extra(name, z)


def _symlink_entry(z, name, target):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    z.writestr(info, target)


def _ziplist(src: Path) -> str:
    return "".join(f"{hashlib.sha256((src / n).read_bytes()).hexdigest()}  {n}\n" for n in ZIPS)


def _sysdir(tmp_path: Path, without=("unzip",)) -> Path:
    """A PATH folder with every system tool except `without`."""
    sysd = tmp_path / "sys"
    sysd.mkdir()
    for d in ("/usr/bin", "/bin"):
        for f in Path(d).iterdir():
            if f.name not in without and not (sysd / f.name).exists() and os.access(f, os.X_OK):
                (sysd / f.name).symlink_to(f)
    return sysd


def _install(tmp_path, *, node="22.11.0", npm_fails=0, npm_integrity=False, deps_fails=0, curl_fails=None,
             extra=None, after_zips=None, ziplist=None, curl_extra=False, unzip_absent=False, top_extra=None,
             manifest=None, tamper=None):
    """Runs the install step in a fake checkout with stubs; returns (process, outputs, env file, calls, runner)."""
    work, bindir, runner, src = tmp_path / "work", tmp_path / "bin", tmp_path / "runner", tmp_path / "src"
    (work / "tests" / "playwright").mkdir(parents=True)
    for name in ("package.json", "package-lock.json"):
        (work / "tests" / "playwright" / name).write_text((PW_DIR / name).read_text(encoding="utf-8"))
    files = dict(FAKE)
    if tamper:
        tamper(files)
    for d in (bindir, runner, src):
        d.mkdir()
    _build_zips(src, files, extra)
    (work / "tests" / "playwright" / "browsers.sha256").write_text(manifest if manifest is not None else _manifest(FAKE))
    (work / "tests" / "playwright" / "browser-zips.sha256").write_text(ziplist if ziplist is not None else _ziplist(src))
    if after_zips:
        after_zips(src)
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
             '  *) exit 9 ;;\n'
             'esac\n')
    _stub(bindir / "npm", f'echo "npm $*" >> "{calls}"\n'
                          + ('echo "npm error code EINTEGRITY"; exit 1\n' if npm_integrity else "")
                          + f'{bindir}/attempt npm {npm_fails} || {{ echo "npm error network"; exit 1; }}\n'
                          'mkdir -p "$3/node_modules/.bin"\n'
                          f"cat > \"$3/node_modules/.bin/playwright\" <<'EOF'\n{pwbin}EOF\n"
                          'chmod +x "$3/node_modules/.bin/playwright"\n')
    _stub(bindir / "node", f'if [ "$1" = --version ]; then echo "v{node}"; else echo "{node.split(".")[0]}"; fi\n')
    _stub(bindir / "sleep", f'echo "sleep $*" >> "{calls}"\n')
    # curl: serves the test zips by the URL's last part; a failing try leaves a partial file behind
    fails = curl_fails or {}
    _stub(bindir / "curl", f'out=""; url=""; args="$*"\n'
                           'while [ "$#" -gt 0 ]; do case "$1" in -o) out=$2; shift 2 ;; *) url=$1; shift ;; esac; done\n'
                           f'name=${{url##*/}}; echo "curl $name | $args" >> "{calls}"\n'
                           'case "$name" in\n'
                           + "".join(f'  {n}) {bindir}/attempt curl-{n} {k} || {{ echo partial > "$out"; exit 22; }} ;;\n'
                                     for n, k in fails.items())
                           + 'esac\n'
                           f'cp "{src}/$name" "$out"\n'
                           + ('echo planted > "$(dirname "$out")/extra.zip"\n' if curl_extra else ""))
    if not unzip_absent:
        hook = ""
        if top_extra:
            hook = f'mkdir -p "$(dirname "$d")/{top_extra}"; echo x > "$(dirname "$d")/{top_extra}/x"\n'
        _stub(bindir / "unzip", 'd=""; z=""; a=("$@")\n'
                                'for i in "${!a[@]}"; do [ "${a[$i]}" = -d ] && d=${a[$((i+1))]}; z=${a[$i]}; done\n'
                                f'echo "unzip ${{z##*/}} -> ${{d##*/}}" >> "{calls}"\n'
                                + hook + '/usr/bin/unzip "$@"\n')
    out, envf = tmp_path / "out", tmp_path / "envfile"
    path = f"{bindir}:{_sysdir(tmp_path)}" if unzip_absent else f"{bindir}:/usr/bin:/bin"
    env = {"PATH": path, "RUNNER_TEMP": str(runner), "GITHUB_OUTPUT": str(out),
           "GITHUB_ENV": str(envf), "HOME": str(tmp_path), **_steps()[INSTALL]["env"]}
    r = subprocess.run([*BASH, _steps()[INSTALL]["run"]], cwd=work, env=env, capture_output=True,
                       text=True, timeout=120)
    return r, _read(out), _read(envf), _read(calls).splitlines(), runner


def _read(f: Path) -> str:
    return f.read_text() if f.exists() else ""


def _kinds(calls, kind):
    return [c for c in calls if c.startswith(kind)]


def test_t4_a_good_install_is_checked_unpacked_and_says_ok(tmp_path):
    r, out, envf, calls, runner = _install(tmp_path)
    br = runner / "pw-browsers"
    assert r.returncode == 0, r.stdout + r.stderr
    assert out == "browsers=ok\n" and envf == f"PLAYWRIGHT_BROWSERS_PATH={br}\n"
    assert "Chromium zips checked: 2 files match" in r.stdout
    assert "Chromium checked: 5 files match" in r.stdout and "node v22.11.0" in r.stdout
    assert sorted(p.name for p in br.iterdir()) == ["chromium-1243", "chromium_headless_shell-1243"]
    assert (br / "chromium-1243" / "INSTALLATION_COMPLETE").read_bytes() == b""
    assert (br / "chromium_headless_shell-1243" / "INSTALLATION_COMPLETE").read_bytes() == b""
    assert (br / "chromium-1243" / "chrome-linux64" / "chrome").is_file() and not (br / ".links").exists()
    assert not list(runner.glob("pw-zips.*"))                                    # the zips are gone
    assert calls[0].startswith("npm ci --prefix ") and calls[0].endswith(" --ignore-scripts --no-audit --no-fund")
    base = CFT.format(REVISIONS["1.63.0"][1])
    assert calls[1:3] == ["playwright --version", "playwright install-deps chromium"]
    logged = CURL_FLAGS.replace("'", "")    # the stub logs the arguments without the shell's quotes
    for c, name in zip(calls[3:5], ZIPS):
        assert re.fullmatch(rf"curl {re.escape(name)} \| {re.escape(logged)} --silent --show-error -o "
                            rf"{re.escape(str(runner))}/pw-zips\.\w{{10}}/{re.escape(name)} {re.escape(base)}/"
                            rf"{re.escape(name)}", c), c
    assert calls[5:] == ["unzip chrome-linux64.zip -> chromium-1243",
                         "unzip chrome-headless-shell-linux64.zip -> chromium_headless_shell-1243"]
    assert not [c for c in calls if "playwright install chromium" in c]


def test_downloads_are_tried_three_times_30_then_90_seconds_apart(tmp_path):
    r, out, _e, calls, _rt = _install(tmp_path, npm_fails=2, deps_fails=1,
                                      curl_fails={"chrome-headless-shell-linux64.zip": 2})
    assert r.returncode == 0, r.stdout + r.stderr
    assert out == "browsers=ok\n"
    assert _kinds(calls, "sleep") == ["sleep 30", "sleep 90", "sleep 30", "sleep 30", "sleep 90"]
    assert r.stdout.count("::warning::") == 5
    # each try fetches both again; the failed tries' partial files were never checked or unzipped
    assert len(_kinds(calls, "curl chrome-linux64.zip")) == 3 and len(_kinds(calls, "curl chrome-headless")) == 3
    assert len(_kinds(calls, "unzip")) == 2 and calls.index(_kinds(calls, "unzip")[0]) > calls.index(
        _kinds(calls, "curl chrome-headless")[-1])


@pytest.mark.parametrize("kw,why", [({"npm_fails": 3}, "npm ci failed three times."),
                                    ({"deps_fails": 3}, "the system libraries install failed three times."),
                                    ({"curl_fails": {"chrome-linux64.zip": 3}}, "the Chromium download failed three times."),
                                    ({"curl_fails": {"chrome-headless-shell-linux64.zip": 3}},
                                     "the Chromium download failed three times."),
                                    ({"node": "18.20.4"}, "Node 20 or newer is needed (Playwright 1.63)."),
                                    ({"unzip_absent": True}, "unzip is not on this runner.")],
                         ids=["npm", "apt", "download-chrome", "download-shell", "old-node", "no-unzip"])
def test_t5_a_download_that_keeps_failing_is_a_warning_and_no_browser(tmp_path, kw, why):
    """Code review bbc603a #1 and the manager's resolution: after three tries the job goes on with no browser (the
    browser tests skip while the switch is off) and nothing unchecked is left behind."""
    r, out, _e, calls, runner = _install(tmp_path, **kw)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out == "browsers=missing\n" and not (runner / "pw-browsers").exists()
    assert not list(runner.glob("pw-zips.*"))
    assert f"::warning::Browser tests: {why} The browser tests skip this run" in r.stdout
    assert "::error::" not in r.stdout and not _kinds(calls, "unzip")
    if "curl_fails" in kw:
        assert _kinds(calls, "sleep") == ["sleep 30", "sleep 90"]
        name = next(iter(kw["curl_fails"]))
        assert len(_kinds(calls, f"curl {name}")) == 3
    if "unzip_absent" in kw or "node" in kw:
        assert not _kinds(calls, "npm") and not _kinds(calls, "curl")


def _flip(name):
    def f(src):
        p = src / name
        p.write_bytes(p.read_bytes() + b"\0")
    return f


@pytest.mark.parametrize("name", ZIPS)
def test_t6_a_zip_that_does_not_match_its_sha256_fails_and_is_never_unpacked(tmp_path, name):
    r, out, _e, calls, runner = _install(tmp_path, after_zips=_flip(name))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "browsers=" not in out
    assert ("::error::The downloaded Chromium does not match tests/playwright/browser-zips.sha256 (a zip's sha256 "
            "differs)") in r.stdout
    assert not _kinds(calls, "unzip") and not (runner / "pw-browsers").exists()
    assert len(_kinds(calls, "curl")) == 2 and not _kinds(calls, "sleep")        # never retried
    assert not list(runner.glob("pw-zips.*"))


GOOD_A = "8aac35011c18f6e2d10696154af89a5728ac2ddd6dc6fad24ffdf243c3fcfd5a"
GOOD_B = "a9da028861a0cf789ff25c2fed45f5f1aaf969ed9247835b6a7821a4f7af9d1d"


@pytest.mark.parametrize("text", [
    PINNED_ZIPS + f"{GOOD_A}  chrome-linux64.zip\n",
    f"{GOOD_A}  chrome-linux64.zip\n{GOOD_B}  other.zip\n",
    f"{GOOD_A.upper()}  chrome-linux64.zip\n{GOOD_B}  chrome-headless-shell-linux64.zip\n",
    f"{GOOD_A}  chrome-linux64.zip\n",
    PINNED_ZIPS.replace("\n", "\r\n"),
    f"{GOOD_A} *chrome-linux64.zip\n{GOOD_B}  chrome-headless-shell-linux64.zip\n",
    f"{GOOD_A}  ../chrome-linux64.zip\n{GOOD_B}  chrome-headless-shell-linux64.zip\n",
    "",
], ids=["three-lines", "other-name", "uppercase-hex", "one-line", "crlf", "binary-mode", "path", "empty"])
def test_t7_a_malformed_zip_list_fails_before_any_fetch(tmp_path, text):
    r, out, _e, calls, runner = _install(tmp_path, ziplist=text)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "browser-zips.sha256 (the list is malformed)" in r.stdout and "browsers=" not in out
    assert not _kinds(calls, "curl") and not _kinds(calls, "npm") and not _kinds(calls, "unzip")


def test_t7_a_missing_zip_list_fails_before_any_fetch(tmp_path):
    r, out, _e, calls, _rt = _install(tmp_path, after_zips=lambda src: (tmp_path / "work" / "tests" / "playwright" /
                                                                         "browser-zips.sha256").unlink())
    assert r.returncode == 1 and "the list is malformed" in r.stdout and not _kinds(calls, "curl")


def test_t7_an_extra_file_beside_the_zips_fails(tmp_path):
    r, out, _e, calls, runner = _install(tmp_path, curl_extra=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "browser-zips.sha256 (a file added or missing)" in r.stdout and "browsers=" not in out
    assert not _kinds(calls, "unzip") and not list(runner.glob("pw-zips.*"))


def _outside_untouched(tmp_path):
    outside = tmp_path / "outside"
    return not outside.exists() or not any(outside.iterdir())


@pytest.mark.parametrize("extra", [
    lambda n, z: _symlink_entry(z, "chrome-linux64/link", "/etc/passwd") if n == ZIPS[0] else None,
    lambda n, z: (_symlink_entry(z, "chrome-linux64/evil", "../../../outside"),
                  z.writestr("chrome-linux64/evil/planted", "x\n")) if n == ZIPS[0] else None,
    lambda n, z: z.writestr("../../outside/planted", "x\n") if n == ZIPS[1] else None,
], ids=["symlink-entry", "symlink-write-through", "dot-dot-entry"])
def test_t8_a_matching_zip_with_a_link_or_escape_fails_and_writes_nothing_outside(tmp_path, extra):
    (tmp_path / "outside").mkdir()
    r, out, _e, _c, runner = _install(tmp_path, extra=extra)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "browsers=" not in out and "::error::" in r.stdout
    assert _outside_untouched(tmp_path) and not (runner / "outside").exists()


@pytest.mark.parametrize("top", [".links", "ffmpeg-1011", "webkit-2359"])
def test_t8_a_folder_beside_the_two_fails_the_tree_check(tmp_path, top):
    r, out, _e, _c, _rt = _install(tmp_path, top_extra=top)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "browsers.sha256 (a folder added or missing)" in r.stdout and "browsers=" not in out


def test_t8_unzip_failing_on_checked_zips_fails_the_step(tmp_path):
    def replace(src):   # bytes that match the list (written from them) but are no zip
        (src / ZIPS[1]).write_bytes(b"not a zip\n")
        (tmp_path / "work" / "tests" / "playwright" / "browser-zips.sha256").write_text(_ziplist(src))
    r, out, _e, calls, runner = _install(tmp_path, after_zips=replace)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "::error::unzip failed on the checked Chromium zips" in r.stdout and "browsers=" not in out
    assert len(_kinds(calls, "unzip")) == 2 and not list(runner.glob("pw-zips.*"))


def _add(rel, text="x\n"):
    def f(files):
        files[rel] = text
    return f


def _drop(rel):
    def f(files):
        del files[rel]
    return f


def _change(rel):
    def f(files):
        files[rel] = "other bytes\n"
    return f


@pytest.mark.parametrize("tamper", [
    _change("chromium-1243/chrome-linux64/chrome"),
    _drop("chromium-1243/chrome-linux64/locales/en-US.pak"),
    lambda files: (files.pop("chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell"),
                   files.update({"chromium_headless_shell-1243/chrome-headless-shell-linux64/other": "x\n"})),
    _add("chromium-1243/chrome-linux64/extra.so"),
    _add("chromium-1243/DEPENDENCIES_VALIDATED", ""),
    _add("chromium-1243/.hidden"),
], ids=["changed", "missing", "shell-missing", "extra-file", "launched-marker", "hidden-file"])
def test_any_difference_from_the_sha256_list_fails_the_step(tmp_path, tamper):
    """Security review bbc603a F1: the zips match their list, but the unpacked tree must match browsers.sha256 too:
    a hash mismatch is a hard fail, always, never browsers=ok or a warning (a zip that omits chrome is no `missing`)."""
    r, out, _e, _c, _rt = _install(tmp_path, tamper=tamper)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "browsers=" not in out and "::warning::Browser tests" not in r.stdout
    assert "::error::The installed Chromium does not match tests/playwright/browsers.sha256" in r.stdout


def test_a_malformed_sha256_list_fails_the_step(tmp_path):
    r, out, _e, _c, _rt = _install(tmp_path, manifest="not a list\n")
    assert r.returncode == 1 and "browsers.sha256 (the list is malformed)" in r.stdout and "browsers=" not in out


def test_an_npm_integrity_failure_fails_the_step(tmp_path):
    r, out, _e, calls, _rt = _install(tmp_path, npm_integrity=True)
    assert r.returncode == 1 and "browsers=" not in out
    assert "::error::npm ci: a package does not match its sha512" in r.stdout
    assert len(_kinds(calls, "npm ")) == 1 and not _kinds(calls, "curl")        # not retried, nothing fetched


# ------------------------------------------------------------------------------------------------ Tests step

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


# ------------------------------------------------------------------------------------------------ R3 issue step

def test_t11_the_skipped_issue_step_is_main_only_scoped_and_body_file_only():
    step = _steps()[ISSUE]
    assert step["if"] == ("always() && github.ref == 'refs/heads/main' && "
                          "steps.browsers.outputs.browsers == 'missing'")
    assert step["continue-on-error"] is True and step["timeout-minutes"] == 5
    assert step["env"] == {"GH_TOKEN": "${{ github.token }}", "BR_TITLE": BR_TITLE}
    run = step["run"]
    assert "${{" not in run and 'body="$RUNNER_TEMP/browser-issue.md"' in run
    gh = [ln for ln in _run_lines(step) if re.search(r"\bgh issue (create|comment)\b", ln)]
    assert len(gh) == 2 and all(ln.endswith('--body-file "$body"') for ln in gh)
    assert "--body " not in run and "--body=" not in run


def _issue(tmp_path, listed):
    bindir, calls = tmp_path / "bin", tmp_path / "calls"
    bindir.mkdir()
    _stub(bindir / "gh", f'echo "gh $*" >> "{calls}"\n'
                         f'if [ "$1 $2" = "issue list" ]; then echo "{listed}"; fi\n')
    env = {"PATH": f"{bindir}:/usr/bin:/bin", "RUNNER_TEMP": str(tmp_path), "GITHUB_SERVER_URL": "https://github.com",
           "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "7", **{k: "x" if k == "GH_TOKEN" else v
                                                              for k, v in _steps()[ISSUE]["env"].items()}}
    r = subprocess.run([*BASH, _steps()[ISSUE]["run"]], env=env, capture_output=True, text=True, timeout=30)
    return r, _read(calls).splitlines(), _read(tmp_path / "browser-issue.md")


def test_t11_no_open_issue_creates_one(tmp_path):
    r, calls, body = _issue(tmp_path, "")
    assert r.returncode == 0, r.stderr
    assert calls[0].startswith("gh issue list --repo o/r --state open --app github-actions")
    assert calls[1] == f"gh issue create --repo o/r --title {BR_TITLE} --body-file {tmp_path}/browser-issue.md"
    assert len(calls) == 2 and "https://github.com/o/r/actions/runs/7" in body


def test_t11_an_open_issue_gets_a_comment(tmp_path):
    r, calls, _body = _issue(tmp_path, "42")
    assert r.returncode == 0, r.stderr
    assert calls[1:] == [f"gh issue comment 42 --repo o/r --body-file {tmp_path}/browser-issue.md"]
