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


# main-protect/test-flake (root cause, reproduced 2026-11-18): two pytest sessions given the same --basetemp share it.
# Each session empties the folder when it starts and names its tmp_path folders the same way, so one session's
# state.json and calls files are deleted or overwritten under the other's running tests (protect-main's stub log read
# back empty: "0 writes, 3 expected"). A session therefore holds an exclusive lock beside its basetemp (not inside:
# pytest empties that) and a second session with the same --basetemp stops at once with a usage error.
def basetemp_lock_path(basetemp) -> Path:
    bt = Path(basetemp).resolve()
    return bt.with_name(bt.name + ".lock")


def pytest_configure(config):
    basetemp = config.getoption("basetemp", None)
    if not basetemp:
        return                             # pytest's default numbered folders never collide
    try:
        import fcntl
    except ImportError:                    # Windows: no flock; one session per folder by hand
        return
    lock = basetemp_lock_path(basetemp)
    lock.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock, "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        raise pytest.UsageError(f"another pytest session is using --basetemp={basetemp} (lock {lock}); give each "
                                "concurrent session its own folder") from None
    config._records_basetemp_lock = (f, lock)


def pytest_unconfigure(config):
    held = getattr(config, "_records_basetemp_lock", None)
    if held:
        f, lock = held
        lock.unlink(missing_ok=True)
        f.close()


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
