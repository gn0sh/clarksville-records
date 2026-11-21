"""Node tests for static/us-count.js, the "Just count me" counter (daylight-national F4)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_us_count_node_tests_pass():
    res = subprocess.run(["node", str(ROOT / "tests" / "us_count.test.js")], capture_output=True, text=True,
                         timeout=60)
    assert res.returncode == 0, res.stdout + res.stderr
