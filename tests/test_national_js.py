"""Node tests for static/national.js, the Daylight Digest lookup's pure part (daylight-national F1, F5), and the
numbers it copies from sitegen/national.py. Problem keys: national/postmessage-hardening, national/csp-jsonp-gadget."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sitegen import national as nat

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "site" / "static" / "national.js").read_text(encoding="utf-8")


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_national_node_tests_pass():
    res = subprocess.run(["node", str(ROOT / "tests" / "national.test.js")], capture_output=True, text=True,
                         timeout=120, cwd=ROOT, env={**os.environ, "PYTHON": sys.executable})
    assert res.returncode == 0, res.stdout + res.stderr


def js_number(name: str) -> int:
    m = re.search(rf"^\s*var {name} = (\d+);", JS, re.MULTILINE)
    assert m, f"national.js has no `var {name} = <number>;`"
    return int(m.group(1))


def test_max_answer_matches_the_build():
    assert js_number("MAX_ANSWER") == nat.MAX_ANSWER


def test_max_matches_matches_the_build():
    assert js_number("MAX_MATCHES") == nat.MAX_MATCHES


def test_storage_id_pattern_is_us_count_s():
    us = (ROOT / "site" / "static" / "us-count.js").read_text(encoding="utf-8")
    pat = r"/\^\(place\|county\|cousub\|sdu\|sds\|sde\)-\[0-9\]\{2,14\}\$/"
    assert re.search(r"var ID_RE = " + pat, JS) and re.search(r"var ID = " + pat, us)


def test_layers_and_geoid_lengths_match_the_build():
    got = dict(re.findall(r'layer: "(\w+)", name: "[^"]+", digits: (\d+)', JS))
    assert {k: int(v) for k, v in got.items()} == nat.GEOID_DIGITS
    assert list(got) == list(nat.LAYERS)
