"""The landing's first screen says the site is independent and unofficial (review unofficial/first-screen-untested):
before any address lookup, the header tag and the short home line naming all four bodies are visible and end within
the first 375x667 phone screen (and the 1280x800 desktop one), on the real data. Kept apart from
tests/test_address_box.py so the address box's own fit test can change without touching this one."""
import json
import os
import shutil
import subprocess

import pytest

from conftest import ROOT, build
from sitegen import unofficial


def _browser_ok() -> bool:
    return bool(shutil.which("node")) and (os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright")))


@pytest.fixture(scope="module")
def real_site(tmp_path_factory):
    out = tmp_path_factory.mktemp("real-unofficial") / "build" / "site"
    build(ROOT / "data" / "facts.json", out)
    return out


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_tag_and_short_line_are_on_the_first_screen(real_site):
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    res = subprocess.run(["node", str(ROOT / "tests" / "unofficial_first_screen.js"), str(real_site / "index.html")],
                         capture_output=True, text=True, timeout=300, env=env)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    u = unofficial.load()
    assert set(out) == {"375x667", "1280x800"}
    for vp, m in out.items():
        assert m["formShown"], (vp, m)   # the address box is laid out, as a visitor sees it
        for key in ("tag", "intro"):
            assert m[key] and m[key]["visible"], (vp, key, m)
            assert 0 <= m[key]["top"] and m[key]["bottom"] <= m["innerHeight"], (vp, key, m)
        assert m["tag"]["text"] == u["tag"], (vp, m)
        assert u["short"] in " ".join(m["intro"]["text"].split()), (vp, m)
