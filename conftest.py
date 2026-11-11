"""Session guard for both test folders (collector/tests and tests): the tests must leave build/site and data/ exactly
as they found them (qa/published_guard.py, pipeline/tests-step-offline-run)."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa import published_guard  # noqa: E402

OFFLINE_RUN_ENV = "RECORDS_OFFLINE_RUN_TEST"      # collector/tests/test_run.py: the opt-in real run may refresh data/


@pytest.fixture(scope="session", autouse=True)
def tests_leave_published_files_alone():
    if os.environ.get(OFFLINE_RUN_ENV) == "1":
        yield
        return
    before = published_guard.snapshot()
    yield
    diff = published_guard.changed(before, published_guard.snapshot())
    assert not diff, (f"the test session changed {len(diff)} files under build/site or data/, which the daily "
                      f"workflow uploads, commits and deploys after this step: {diff[:10]}. Tests must write to "
                      "tmp_path only.")
