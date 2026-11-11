"""What a run publishes, as a snapshot: every file of build/site (the Pages artifact) and of data/ (the data commit),
by content hash. conftest.py takes it before and after the test session and fails the session when they differ
(pipeline/tests-step-offline-run): in the daily workflow the tests run after the site checks and before the uploads,
so a test that rewrote either folder would change what is committed and deployed, unchecked.

Not covered: the git-ignored caches under data/ (the document store and derived text), which are never uploaded.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHES = ("store", "raw", "text", "ocr", "out")     # data/<name>: git-ignored, excluded from the data artifact


def snapshot(root: Path = ROOT) -> dict[str, str]:
    """{path relative to root: sha256} for build/site and data/ (caches left out). A missing folder is empty."""
    root = Path(root)
    out: dict[str, str] = {}
    for top in (root / "build" / "site", root / "data"):
        if not top.is_dir():
            continue
        for p in sorted(top.rglob("*")):
            rel = p.relative_to(root)
            if rel.parts[0] == "data" and len(rel.parts) > 1 and rel.parts[1] in CACHES:
                continue
            if p.is_file() and not p.is_symlink():
                out[rel.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
            elif p.is_symlink():
                out[rel.as_posix()] = "symlink"
    return out


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Paths added, removed or rewritten with other content between two snapshots."""
    return sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
