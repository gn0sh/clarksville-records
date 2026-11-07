"""Shared helpers for the M1 QA tools (read-only: nothing here touches collector/ or sitegen/)."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "site" / "fixtures" / "facts.sample.json"
OPERATOR = "Brian Zacharias"

VOTE_LABEL = {"yes": "Yes", "no": "No", "abstain": "Abstain"}


def load_facts(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def vote_label(vote: dict) -> str:
    """N2 wording: Yes / No / Abstain, or 'Other: <minutes' wording>'."""
    if vote["value"] in VOTE_LABEL:
        return VOTE_LABEL[vote["value"]]
    return f"Other: {vote.get('raw_value') or '?'}"


def store_dirs(extra=()) -> list[Path]:
    """Places a cached minutes PDF (named <sha256>.pdf) may live."""
    dirs = [Path(p) for p in extra]
    if os.environ.get("RECORDS_STORE"):
        dirs.append(Path(os.environ["RECORDS_STORE"]))
    dirs += [ROOT / "data" / "store", ROOT / "data" / "raw", ROOT / "build" / "qa" / "pdfcache"]
    return dirs


def find_pdf(sha256: str, extra=()) -> Path | None:
    for d in store_dirs(extra):
        p = d / f"{sha256}.pdf"
        if p.is_file():
            return p
    return None


def pdf_page_count(pdf: Path) -> int | None:
    try:
        out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else None
