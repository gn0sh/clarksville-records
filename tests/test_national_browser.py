"""Daylight Digest privacy run in a real browser (daylight-national F3; architecture 3.8, 3.9, section 6 "Privacy").

Builds the fixture site with national.enabled on into a temp folder and runs tests/national_browser.js (Playwright,
chromium) over it: 12 recorded Census answers, plus a run with webdriver left true and a native-post run with fetch
removed. The fixture build normally leaves the counter off (sitegen/analytics.py settings returns None for a fixture),
so this build passes fixture=False to that one call to get the shipped counter tag. Skips when node, Playwright or a
Chromium is missing."""
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


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) or its Chromium not available")
def test_digest_privacy_in_a_browser(digest_site):
    res = subprocess.run(["node", str(ROOT / "tests" / "national_browser.js"), str(digest_site)], capture_output=True,
                         text=True, timeout=600, cwd=ROOT, env={**_node_env(), "PYTHON": sys.executable})
    assert res.returncode == 0, res.stdout[-8000:] + res.stderr[-4000:]
