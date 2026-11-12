"""Out-of-repo leak scan (privacy/transcript-private-addresses, docs/architecture/city-council.md row 14).

    python -m qa.pii_scan --raw <folder outside the repo> [--site build/site]

Reads the raw transcripts in --raw (the speech-recognition input, <date>_<event>.json with segments
[{start, end, text}], or the committed form with segments [start, end, text]; any folder depth) and, optionally, raw
RPC text layers (*.txt). It takes the spans collector/privacy.py would mask (and, in the text layers, every
rpc_agenda.PHONE match), keeps them in memory only, and looks for each in every `git ls-files` file of the repo and
in every file of --site, case-insensitively with whitespace folded (an address split over two lines of a file is
found). It prints `path:line` and counts only, never the matched text, and writes no file.

A needle that is a bare number ("my address is 515" masks "515") would match everywhere, so a needle with no letters
and under 8 characters carries up to three words of its raw context before it; a phone number is looked for by its
digits with any of space, ".", "-", "(" or ")" between them. The --raw folder must be outside the repo (its needles
must never be committed). Exit 0: no hits; 1: hits; 2: refused or unreadable.

The masker errs toward masking (an address read aloud from a zoning item, the council chambers' address), so a
needle is "public", not a hit, only when it is (a) a whole-token match (word boundaries on both sides: house 10 is not
cleared by house 110) inside one of the named public fields of the committed data outside the transcript folders,
PUBLIC_FIELDS (an RPC case's subject-property location, an agenda item's title: public case data the architecture keeps
shown), or (b) exactly one of PUBLIC_PLACES, a government building (a merged span holding one and another number is a
hit). It never clears a needle because the text is somewhere else in data/** (raw text copied into a data file would
whitelist itself; security review M1). Public matches are listed as `PUBLIC path:line` and counted apart; phone
numbers are never public. Review the PUBLIC list when it changes.

No guard test may grep the tree for real strings (it would commit them): this scan is the replacement. Run it after
each import and before each merge to `main`.
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import subprocess
import sys
from pathlib import Path

from collector import privacy, rpc_agenda

ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {".html", ".js", ".json", ".csv", ".xml", ".txt", ".ics", ".md", ".py", ".yml", ".yaml", ".j2",
                 ".css", ".toml", ".cfg", ".ini", ".sh", ".ps1", ".svg", ".tsv", ".lock", ".jsonl", ".geojson", ""}
SHORT = 8           # a needle with no letters under this many characters carries context
# Government buildings (where the bodies meet or keep office), already in tracked fixtures and tests: never a resident.
PUBLIC_PLACES = ("106 public square", "350 pageant lane")
# The only fields of data/**/*.json (outside the transcript folders) whose strings may clear a needle, as paths from the
# document root: the RPC case's subject-property location and the agenda item titles (city facts, county agendas).
PUBLIC_FIELDS = frozenset({".cases[].location", ".items[].title", ".meetings[].items[].title"})


class ScanError(ValueError):
    pass


def _fold(text: str) -> str:
    return " ".join(text.replace("’", "'").lower().split())


def repo_roots(root: Path = ROOT) -> list[Path]:
    """The repo's working tree and, for a git worktree, the main checkout's (both hold tracked copies)."""
    out = [Path(root).resolve()]
    try:
        common = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=True).stdout.strip()
        out.append(Path(common).resolve().parent)
    except (OSError, subprocess.CalledProcessError):
        pass
    return out


def _check_outside(raw: Path, roots: list[Path]) -> Path:
    raw = Path(raw).resolve()
    if not raw.is_dir():
        raise ScanError("--raw is not a folder")
    for r in roots:
        if raw == r or raw.is_relative_to(r):
            raise ScanError("--raw is inside the repo: raw text must stay outside it")
    return raw


def _segments(data) -> list[str]:
    segs = data.get("segments") if isinstance(data, dict) else None
    out = []
    for s in segs if isinstance(segs, list) else []:
        t = s.get("text") if isinstance(s, dict) else (s[2] if isinstance(s, list) and len(s) == 3 else None)
        if isinstance(t, str) and t.strip():
            out.append(" ".join(t.split()))
    return out


def needles(raw: Path) -> tuple[set[str], set[str], dict]:
    """(text needles, folded; phone digit strings; counts) from every raw file under raw. Held in memory only."""
    texts: set[str] = set()
    phones: set[str] = set()
    counts = {"files": 0, "spans": 0}
    for f in sorted(Path(raw).rglob("*")):
        if not f.is_file() or f.suffix.lower() not in (".json", ".txt"):
            continue
        body = f.read_text(encoding="utf-8", errors="replace")
        if f.suffix.lower() == ".json":
            try:
                lines = _segments(json.loads(body))
            except json.JSONDecodeError:
                continue
            if not lines:
                continue
            joined = " ".join(lines)
            found = [(a, b, joined[a:b], m) for a, b, m in privacy.spans(joined)]
        else:
            joined = body
            found = [(m.start(), m.end(), m.group(0), privacy.PHONE_MASK) for m in rpc_agenda.PHONE.finditer(body)]
        counts["files"] += 1
        for a, b, span, kind in found:
            counts["spans"] += 1
            digits = re.sub(r"\D", "", span)
            if kind == privacy.PHONE_MASK and len(digits) in (7, 10):
                phones.add(digits)
            if len(span) < SHORT and not re.search(r"[A-Za-z]", span):
                span = " ".join(joined[:a].split()[-3:] + [span])
            if len(_fold(span)) >= 3:
                texts.add(_fold(span))
    return texts, phones, counts


def public_text(root: Path = ROOT) -> list[str]:
    """The strings of the PUBLIC_FIELDS of the committed source data outside the transcript folders, folded."""
    out: list[str] = []

    def walk(v, path: str):
        if isinstance(v, str):
            if path in PUBLIC_FIELDS:
                out.append(_fold(v))
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{path}.{k}")
        elif isinstance(v, list):
            for x in v:
                walk(x, f"{path}[]")
    for p in tracked_files(root):
        rel = p.relative_to(root).as_posix()
        if rel.startswith("data/") and rel.endswith(".json") and "/transcripts/" not in rel:
            try:
                walk(json.loads(p.read_text(encoding="utf-8")), "")
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
    return out


def _whole(needle: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(needle) + r"(?!\w)")


def split_public(texts: set[str], root: Path = ROOT) -> tuple[set[str], set[str]]:
    """(private needles, public needles): public when a whole-token match inside a PUBLIC_FIELDS string, or exactly a
    PUBLIC_PLACES entry."""
    src = public_text(root)
    public = {n for n in texts if n in PUBLIC_PLACES or any(n in s and _whole(n).search(s) for s in src)}
    return texts - public, public


def _phone_rx(digits: str) -> re.Pattern:
    return re.compile(r"(?<!\d)" + r"[\s().-]{0,3}".join(digits) + r"(?!\d)")


def scan_text(body: str, texts: set[str], phone_rx: list[re.Pattern]) -> list[int]:
    """The 1-based line numbers where a needle starts, folded the same way as the needles (lines joined by a space)."""
    starts, parts, pos = [], [], 0
    for line in body.split("\n"):
        f = _fold(line)
        starts.append(pos)
        parts.append(f)
        pos += len(f) + 1
    flat = " ".join(parts)
    hits = []
    for n in texts:
        i = flat.find(n)
        while i != -1:
            hits.append(bisect.bisect_right(starts, i))
            i = flat.find(n, i + 1)
    for rx in phone_rx:
        hits += [bisect.bisect_right(starts, m.start()) for m in rx.finditer(flat)]
    return sorted(hits)


def _read(p: Path) -> str | None:
    try:
        data = p.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def tracked_files(root: Path = ROOT) -> list[Path]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout
    return [Path(root) / p for p in out.decode("utf-8").split("\0") if p]


def scan(raw: Path, site: Path | None = None, root: Path = ROOT, out=sys.stdout) -> int:
    raw = _check_outside(raw, repo_roots(root))
    texts, phones, counts = needles(raw)
    if not counts["files"]:
        raise ScanError("--raw holds no transcript (*.json with segments) or text layer (*.txt)")
    texts, public = split_public(texts, root)
    phone_rx = [_phone_rx(d) for d in sorted(phones)]
    groups = [("tracked", Path(root), tracked_files(root))]
    if site is not None:
        if not Path(site).is_dir():
            raise ScanError("--site is not a folder")
        groups.append(("site", Path(site), sorted(p for p in Path(site).rglob("*") if p.is_file())))
    total, hit_files, pub_total, scanned = 0, 0, 0, {}
    for label, base, files in groups:
        n = 0
        for p in files:
            if p.suffix.lower() not in TEXT_SUFFIXES or not p.is_file():
                continue
            body = _read(p)
            if body is None:
                continue
            n += 1
            rel = p.relative_to(base).as_posix()
            lines = scan_text(body, texts, phone_rx)
            if lines:
                hit_files += 1
                total += len(lines)
                for ln in sorted(set(lines)):
                    print(f"HIT {label}:{rel}:{ln}", file=out)
            pub = scan_text(body, public, []) if public else []
            pub_total += len(pub)
            for ln in sorted(set(pub)):
                print(f"PUBLIC {label}:{rel}:{ln}", file=out)
        scanned[label] = n
    print(f"pii_scan: {len(texts)} text needles ({len(public)} more public) and {len(phones)} phone numbers from "
          f"{counts['spans']} spans in {counts['files']} raw files; scanned {scanned.get('tracked', 0)} tracked files"
          + (f" and {scanned['site']} site files" if "site" in scanned else "")
          + f"; {total} hits in {hit_files} files; {pub_total} public matches", file=out)
    return 1 if total else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m qa.pii_scan", description=__doc__.splitlines()[0])
    ap.add_argument("--raw", required=True, type=Path, help="folder of raw transcripts, outside the repo")
    ap.add_argument("--site", type=Path, help="a built site to scan as well (e.g. build/site)")
    a = ap.parse_args(argv)
    try:
        return scan(a.raw, a.site)
    except ScanError as exc:
        print(f"pii_scan: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
