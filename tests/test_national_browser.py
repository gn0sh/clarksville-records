"""Daylight Digest privacy run in a real browser (daylight-national F3; architecture 3.8, 3.9, section 6 "Privacy").

Builds the fixture site with national.enabled on into a temp folder and runs tests/national_browser.js (Playwright,
chromium) over it: 12 recorded Census answers, plus a run with webdriver left true and a native-post run with fetch
removed. The fixture build normally leaves the counter off (sitegen/analytics.py settings returns None for a fixture),
so this build passes fixture=False to that one call to get the shipped counter tag. Missing node, Playwright or a
Chromium skips, unless the run is required: REQUIRE_BROWSER=1, or CI set while the national switch in the shipped
config/site.yml (national.enabled) is on, which fails instead. With the switch off (digest pages neither built nor
deployed) CI skips. The run must end with its JSON summary: checks > 0 and "failed":0."""
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from sitegen import analytics, build as build_mod, config

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "site" / "fixtures" / "facts.sample.json"


def _node_env() -> dict:
    env = dict(os.environ)
    if "NODE_PATH" not in env and shutil.which("npm"):
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    return env


def _browser_ok() -> bool:
    if not shutil.which("node"):
        return False
    probe = subprocess.run(["node", "-e", "const p=require('path');const r=[process.env.NODE_PATH,'/opt/node22/lib/"
                            "node_modules','/usr/local/lib/node_modules','/usr/lib/node_modules'].filter(Boolean);"
                            "let pw=null;for(const x of [''].concat(r)){try{pw=require(x?p.join(x,'playwright'):"
                            "'playwright');break}catch(e){}}if(!pw)process.exit(3);"
                            "process.exit(require('fs').existsSync(pw.chromium.executablePath())?0:4)"],
                           capture_output=True, text=True, env=_node_env(), timeout=60)
    return probe.returncode == 0


@pytest.fixture(scope="module")
def digest_site(tmp_path_factory, monkeypatch_module):
    out = tmp_path_factory.mktemp("national-browser") / "site"
    real = analytics.settings
    monkeypatch_module.setattr(analytics, "settings", lambda cfg=None, target="pages", fixture=False:
                               real(cfg, target=target, fixture=False))
    monkeypatch_module.setitem(config.SITE, "national", {"enabled": True})
    build_mod.build(FIXTURE, out, internal=True, seats_path=ROOT / "site" / "fixtures" / "seats.sample.yml",
                    districts_path=ROOT / "site" / "fixtures" / "districts.sample.json", target="pages",
                    today=date(2026, 11, 19))
    return out


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def _browser_required(env=None) -> bool:
    """True when a missing browser must fail: REQUIRE_BROWSER=1, or CI with the national switch on in the shipped
    config (read as the build does). NOTE: flipping the switch on needs daily-update.yml to install Playwright and
    Chromium (pinned) first, or every daily deploy fails here."""
    env = os.environ if env is None else env
    if env.get("REQUIRE_BROWSER") == "1":
        return True
    return bool(env.get("CI")) and bool(config.SITE.get("national", {}).get("enabled"))


def _need_browser():
    if _browser_ok():
        return
    why = "Playwright (node) or its Chromium not available"
    if _browser_required():
        pytest.fail(why + " (REQUIRE_BROWSER=1, or CI with config/site.yml national.enabled on: the browser run is required)")
    pytest.skip(why + " (browser run not required: national switch off in config/site.yml, REQUIRE_BROWSER not 1)")


@pytest.mark.parametrize("env,switch,required", [
    ({"CI": "1"}, False, False),
    ({"CI": "1"}, True, True),
    ({"REQUIRE_BROWSER": "1"}, False, True),
    ({}, False, False),
    ({}, True, False),
])
def test_browser_required_gate(monkeypatch, env, switch, required):
    monkeypatch.setitem(config.SITE, "national", {"enabled": switch})
    assert _browser_required(env) is required


def test_digest_privacy_in_a_browser(request):
    _need_browser()
    digest_site = request.getfixturevalue("digest_site")
    res = subprocess.run(["node", str(ROOT / "tests" / "national_browser.js"), str(digest_site)], capture_output=True,
                         text=True, timeout=600, cwd=ROOT, env={**_node_env(), "PYTHON": sys.executable})
    assert res.returncode == 0, res.stdout[-8000:] + res.stderr[-4000:]
    last = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""
    summary = json.loads(last) if last.startswith("{") else {}
    assert summary.get("failed") == 0 and summary.get("checks", 0) > 0 and '"failed":0' in last, res.stdout[-4000:]
    assert len(summary.get("cases", {})) == 12, summary.get("cases")
