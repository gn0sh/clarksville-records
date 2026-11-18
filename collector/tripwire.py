"""I-pub, the content tripwire (ADR 0011 decision 4 and Amendment (c); docs/architecture/v1-fail-2026-11-18.md
"I-pub", rows J1 and J3).

A run deploys only if no vote, roll call or outcome already on the live site changes or disappears. "Live" is the
data tree the live site was built from, named by the site's own build-info.json (this module's build_info(): S as
`sha`, D as `data_sha`, and the sha256 of the data listing it deployed). This run's side is the data/ folder on disk
after collection: exactly what it deploys. The exceptions are the facts listed in the reviewed
config/published-fact-changes.yml (collector/reviewed_lists.py); allow_shrink never counts, and nothing here reads
it. There is one mode, and it always holds (Amendment (c) item 4): no flag, input or variable turns the hold off.

Published facts, per file (every facts.json and rpc.json under data/, keyed by path and id):
- facts.json roll_calls: each one is on the site (held ones marked); its outcome, stated tally and votes are shown only
  while it is verified. So any roll call that disappears is a removal, and one that was verified changes when it is
  no longer verified or its outcome, tally or votes (official, value) differ.
- rpc.json motions (the Regional Planning Commission): the same, "confirmed" standing for verified; outcome, tally,
  nays and abstentions are its values.
A new fact is never a hit. An id that appears more than once keeps every copy: a copy that disappears is a removal.
A listed entry lets through exactly one change (ADR 0011 B4 notes, S2): its path, fact_id, change and value_sha256 must
all match, where value_sha256 is the sha256 of the fact's view (value_view: the number of copies and the shown values)
after a "changed", or of the view that disappears for a "removed". The hit line prints that digest. Once the live site
shows that value the entry matches nothing new, so a later change of the same fact needs a new entry (it is spent).

Finding the live tree: build-info.json names D (the records-data head the live run started from) and the sha256 of
the listing it deployed. That is always D itself (a rebuild-only run, or no data change) or D+1, the push job's one
commit on D (a collecting run): the live tree is whichever of those two has the listing digest, never a later commit.

    python -m collector.tripwire check --url https://<site>/build-info.json --seed yes|no [--data data] [--repo .]
        exit 0 deploy (no hit, or the seed bootstrap), 1 hit, 3 build-info.json, the live tree or this run's facts
        could not be read or checked (a missing build-info.json counts, unless this run's D is the seed), 4 the
        reviewed list is not valid, 2 a bad call. Anything but 0 holds the deploy. Fact ids are printed only when they
        are plain ASCII (the schema's id characters); others are counted.
    python -m collector.tripwire build-info --sha S --data-sha D --out <site>/build-info.json [--data data]
        exit 0 written, 1 not written: data/ fails I-data'' (collector/data_shape.py), 2 a bad call.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import data_shape, reviewed_lists
from .fetch import USER_AGENT

PASS, HIT, BAD_CALL, NOT_READ, BAD_LIST = 0, 1, 2, 3, 4
SCHEMA = "build-info/1"
KEYS = {"schema", "sha", "data_sha", "listing_sha256"}
MAX_BUILD_INFO = 4096
MAX_WALK = 2              # D and D+1 (the push job's one commit on D): the only commits a live site is built from
_SHA1 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")
_URL = re.compile(r"https://[A-Za-z0-9.-]+(/[A-Za-z0-9._/-]*)?")
FACT_FILES = ("facts.json", "rpc.json")
RC = "refs/tripwire/records-data"


class NotRead(Exception):
    """build-info.json, the live tree or one of the facts files could not be read or checked: the deploy holds."""


def build_info(sha: str, data_sha: str, data_dir: Path) -> dict:
    """What the site carries as build-info.json: this run's code S, its records-data head D, and the sha256 of the
    data tree it deploys (data_shape.disk_listing: the bytes `git ls-tree -r -z <commit> -- data` gives for the
    commit the push job makes of it)."""
    if not (_SHA1.fullmatch(sha) and _SHA1.fullmatch(data_sha)):
        raise ValueError("sha and data_sha must be 40-hex commit ids")
    digest = hashlib.sha256(data_shape.disk_listing(Path(data_dir))).hexdigest()
    return {"schema": SCHEMA, "sha": sha, "data_sha": data_sha, "listing_sha256": digest}


def parse_build_info(raw: bytes) -> dict:
    try:
        info = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise NotRead("build-info.json is not JSON") from exc
    if not (isinstance(info, dict) and set(info) == KEYS and info["schema"] == SCHEMA
            and all(isinstance(info[k], str) for k in KEYS)
            and _SHA1.fullmatch(info["sha"]) and _SHA1.fullmatch(info["data_sha"])
            and _SHA256.fullmatch(info["listing_sha256"])):
        raise NotRead("build-info.json does not have the expected fields")
    return info


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not str(newurl).startswith("https://"):
            raise NotRead("build-info.json redirects off https")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_build_info(url: str, timeout: float = 30.0) -> bytes | None:
    """The live build-info.json, or None when the site answers 404 (a site built before this file existed). The
    query string busts the Pages cache (10 minutes), so a recent deploy is never compared as the one before it."""
    req = urllib.request.Request(f"{url}?tripwire={int(time.time())}",
                                 headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    opener = urllib.request.build_opener(_HttpsOnlyRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:        # noqa: S310  https site URL, checked by main()
            body = resp.read(MAX_BUILD_INFO + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise NotRead(f"build-info.json: HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise NotRead(f"build-info.json: {type(exc).__name__}") from exc
    if len(body) > MAX_BUILD_INFO:
        raise NotRead("build-info.json is too large")
    return body


def _git(repo: Path, *args: str) -> bytes:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True)
    if r.returncode != 0:
        raise NotRead(f"git {args[0]} failed")
    return r.stdout


def live_tree(repo: Path, info: dict) -> str:
    """The records-data commit the live site was built from: D or D+1 (the first commit after D on records-data),
    whichever has the recorded listing digest. Reads records-data once (trees only; the facts files' blobs come lazily
    from the same remote)."""
    _git(repo, "fetch", "--no-tags", "--filter=blob:none", "origin", f"+refs/heads/records-data:{RC}")
    d = info["data_sha"]
    on_branch = subprocess.run(["git", "merge-base", "--is-ancestor", d, RC], cwd=repo, capture_output=True)
    if on_branch.returncode != 0:
        raise NotRead("the live data_sha is not on records-data")
    later = _git(repo, "rev-list", "--reverse", "--ancestry-path", f"{d}..{RC}").decode().split()
    for sha in [d, *later][:MAX_WALK]:
        if hashlib.sha256(_git(repo, "ls-tree", "-r", "-z", sha, "--", "data")).hexdigest() == info["listing_sha256"]:
            return sha
    raise NotRead("neither the live data_sha nor the commit after it on records-data has the live listing")


def _fact_paths(names) -> list[str]:
    return sorted(n for n in names if n.startswith("data/") and n.rsplit("/", 1)[-1] in FACT_FILES)


def _json(raw: bytes, path: str, side: str):
    try:
        return json.loads(raw)
    except ValueError as exc:       # UnicodeDecodeError and JSONDecodeError both
        raise NotRead(f"{path} in {side} is not JSON") from exc


def read_live(repo: Path, sha: str) -> dict[str, object]:
    names = _git(repo, "ls-tree", "-r", "-z", "--name-only", sha, "--", "data").decode("utf-8", "replace").split("\0")
    return {path: _json(_git(repo, "show", f"{sha}:{path}"), path, "the live tree") for path in
            _fact_paths(n for n in names if n)}


def read_disk(data_dir: Path) -> dict[str, object]:
    """This run's facts files on disk (the caches left out, as in data_shape.disk_listing). A file that is not JSON
    holds: the build would have failed on it, and a broken file must never pass as "every fact removed"."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise NotRead("this run's data/ folder is missing")
    found = {}
    for dirpath, dirnames, filenames in os.walk(data_dir):
        rel = Path(dirpath).relative_to(data_dir)
        if rel == Path("."):
            dirnames[:] = [d for d in dirnames if d not in data_shape.DATA_CACHES]
        for name in filenames:
            if name in FACT_FILES:
                found[(Path("data") / rel / name).as_posix().replace("/./", "/")] = Path(dirpath) / name
    out = {}
    for path, full in sorted(found.items()):
        try:
            raw = full.read_bytes()
        except OSError as exc:
            raise NotRead(f"{path} in this run's data/ could not be read") from exc
        out[path] = _json(raw, path, "this run's data/")
    return out


def published(files: dict[str, object]) -> dict[tuple[str, str], tuple[int, list]]:
    """{(path, fact id): (copies, sorted [shown values])} for every published roll call and RPC motion: one shown
    value per copy that shows its values (verified, or confirmed). Every copy of an id that appears twice is kept, so a
    duplicate never hides a change, and a copy that disappears is a removal. A file of the wrong shape holds."""
    out: dict[tuple[str, str], tuple[int, list]] = {}

    def add(key, shown, values):
        n, vals = out.get(key, (0, []))
        out[key] = (n + 1, vals + ([json.dumps(values, sort_keys=True)] if shown else []))
    try:
        for path, doc in files.items():
            if not isinstance(doc, dict):
                raise TypeError(path)
            for rc in doc.get("roll_calls") or []:
                votes = sorted((str(v.get("official_id")), str(v.get("value"))) for v in rc.get("votes") or [])
                add((path, str(rc.get("id"))), (rc.get("verification") or {}).get("status") == "verified",
                    [rc.get("outcome"), rc.get("stated_tally"), votes])
            for mo in (doc.get("motions") or []) if path.endswith("rpc.json") else []:
                add((path, str(mo.get("id"))), mo.get("confirmed") is True,
                    [mo.get("outcome"), mo.get("tally"), sorted(map(str, mo.get("nays") or [])),
                     sorted(map(str, mo.get("abstained") or []))])
    except (AttributeError, TypeError) as exc:
        raise NotRead("a facts file does not have the expected shape") from exc
    return {k: (n, sorted(v)) for k, (n, v) in out.items()}


def value_view(view: tuple[int, list] | None) -> str:
    """The sha256 a published-fact-changes.yml entry pins: of the fact's (copies, shown values), canonical JSON."""
    n, shown = view if view is not None else (0, [])
    return hashlib.sha256(json.dumps({"copies": n, "shown": shown}, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def hits(live: dict[str, object], new: dict[str, object], listed: list[dict]) -> list[tuple[str, str, str, str]]:
    """[(change, path, fact id, value_sha256)] for each published fact that changed, lost a copy or disappeared and
    is not listed for exactly that change (path, fact_id, change and value_sha256)."""
    allowed = {(e["path"], e["fact_id"], e["change"], e["value_sha256"]) for e in listed}
    before, after = published(live), published(new)
    out = []
    for key, (copies, shown) in sorted(before.items()):
        path, fid = key
        if key not in after or after[key][0] < copies:
            change, digest = "removed", value_view(before[key])
        elif shown and after[key][1] != shown:
            change, digest = "changed", value_view(after[key])
        else:
            continue
        if (path, fid, change, digest) not in allowed:
            out.append((change, path, fid, digest))
    return out


def check(repo: Path, data_dir: Path, raw_info: bytes | None, seed: bool, listed: list[dict]) -> tuple[int, list]:
    """The verdict without the network: (exit code, hits). Raises NotRead when anything could not be read."""
    if raw_info is None:
        if seed:
            return PASS, []
        raise NotRead("build-info.json is missing and this run's D is not the seed")
    info = parse_build_info(raw_info)
    found = hits(read_live(repo, live_tree(repo, info)), read_disk(data_dir), listed)
    return (HIT if found else PASS), found


def _check_main(args) -> int:
    if not _URL.fullmatch(args.url):
        print("tripwire: --url must be a plain https URL (no query)", file=sys.stderr)
        return BAD_CALL
    try:
        listed = reviewed_lists.load(reviewed_lists.PUBLISHED_FACT_CHANGES, root=Path(args.repo))
    except reviewed_lists.ReviewedListError as exc:
        print(f"tripwire: held: {exc}")
        return BAD_LIST
    try:
        code, found = check(Path(args.repo), Path(args.data), fetch_build_info(args.url), args.seed == "yes", listed)
    except NotRead as exc:
        print(f"tripwire: held: {exc}")
        return NOT_READ
    except Exception as exc:          # noqa: BLE001  anything unforeseen holds too, never "no hit"
        print(f"tripwire: held: the check stopped ({type(exc).__name__})")
        return NOT_READ
    unprintable = 0
    for change, path, fid, digest in found:
        if _ID.fullmatch(fid) and re.fullmatch(r"[A-Za-z0-9/._-]+", path):
            print(f"tripwire: {change}: {fid} ({path}) value_sha256 {digest}")
        else:
            unprintable += 1
    if unprintable:
        print(f"tripwire: {unprintable} more fact(s) with ids that are not plain ASCII")
    print(f"tripwire: {'held' if found else 'pass'}: {len(found)} published fact(s) changed or removed, not listed in "
          "config/published-fact-changes.yml")
    return code


def _build_info_main(args) -> int:
    """Refuses (exit 1) a data/ folder that fails I-data'': the push job would not commit that tree as it is (the
    artifact drops hidden files, the push job's check refuses the rest), so the digest would name no records-data
    commit and every later run would hold."""
    found = data_shape.problems(data_shape.disk_listing(Path(args.data)))
    if found:
        for p in found[:20]:
            print(f"tripwire: build-info.json not written: {p}")
        return HIT
    try:
        info = build_info(args.sha, args.data_sha, Path(args.data))
    except ValueError as exc:
        print(f"tripwire: {exc}", file=sys.stderr)
        return BAD_CALL
    Path(args.out).write_text(json.dumps(info, sort_keys=True) + "\n", encoding="utf-8")
    print(f"tripwire: build-info.json: data_sha {info['data_sha']}, listing sha256 {info['listing_sha256']}")
    return PASS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m collector.tripwire")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--url", required=True)
    c.add_argument("--seed", required=True, choices=("yes", "no"))
    c.add_argument("--data", default="data")
    c.add_argument("--repo", default=".")
    b = sub.add_parser("build-info")
    b.add_argument("--sha", required=True)
    b.add_argument("--data-sha", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--data", default="data")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return BAD_CALL
    return _check_main(args) if args.cmd == "check" else _build_info_main(args)


if __name__ == "__main__":
    sys.exit(main())
