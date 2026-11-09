"""Meeting video transcripts (AC6.3): import speech-recognition output into a compact, committed form.

    python -m collector transcripts import <dir> [--locality clarksville-tn]

Input: JSON files named <YYYY-MM-DD>_<eventId>.json, made outside the repo by speech-recognition software (Whisper)
from the city's public meeting videos (docs/platform-facts.md, "Meeting video"). Each has event_id, event_name,
start, video_url, model, model_version, created_at and segments [{start, end, text, words: [...]}].

Output, under <the council's facts folder>/transcripts/ (data/localities/<locality>/transcripts/):
- <meeting-id>.json: the provenance fields plus segments as [start, end, text] (word-level data dropped), one
  segment per line. Text is kept as the software wrote it, apart from whitespace runs folded to one space and
  control characters removed; it is never summarised, reworded or corrected.
- index.json: which meetings have a transcript ({meeting id: {file, segments, video_url, ...}}), rebuilt from the
  folder's files on every import, so it always names exactly the transcripts that are there.

Matching (each input to one meeting of the council's facts file):
1. by video_url: the one meeting whose video_url is exactly the transcript's; else
2. by date + kind: when the transcript has no video_url, the one meeting on its start date whose kind is the kind
   rule's reading of its event_name (agenda-center.yml kind_rules), and that meeting has a video_url.
When the meeting carries an event_id (the listing's event number), it must equal the transcript's event_id too.
A transcript whose video_url names no meeting's video, or a match that is not exactly one meeting, is skipped with
the reason; nothing is guessed. Every timestamp link on the site goes to the matched meeting's own video_url.
When two inputs match one meeting, the later created_at (then the later file name) is kept.
Every import also removes the transcript files already in the folder that no longer match a meeting of the facts file
(the meeting is gone, its video_url changed, or its event_id differs), so the index never names a stale transcript.

Deterministic and idempotent: the output depends only on the inputs and the facts file (no clock), files are
rewritten only when their text changes, and running the same import twice changes nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d+)\.json$")
PROVENANCE = ("event_id", "event_name", "start", "model", "model_version", "created_at")
# C0 and C1 control characters, and the Unicode line/paragraph separators and bidi controls, are removed from text
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f  ‪-‮⁦-⁩]")
_ID_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]+$")


class TranscriptError(ValueError):
    pass


def clean_text(text) -> str:
    """The segment's text as written, with control characters removed and whitespace runs folded to one space."""
    if not isinstance(text, str):
        raise TranscriptError("segment text is not a string")
    return " ".join(_CONTROL.sub(" ", text).split())


def _num(v, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
        raise TranscriptError(f"{what} is not a finite number >= 0: {v!r}")
    return round(float(v), 2)


def compact_segments(raw: list) -> list[list]:
    """[[start, end, text], ...] sorted by (start, end), source order kept for ties. A segment with no text is
    dropped; a malformed one (start/end not a number >= 0, end before start, text not a string) fails the file."""
    if not isinstance(raw, list):
        raise TranscriptError("segments is not a list")
    out = []
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            raise TranscriptError(f"segment {i} is not an object")
        start, end = _num(s.get("start"), f"segment {i} start"), _num(s.get("end"), f"segment {i} end")
        if end < start:
            raise TranscriptError(f"segment {i} ends before it starts")
        text = clean_text(s.get("text"))
        if text:
            out.append((start, end, i, text))
    out.sort()
    return [[a, b, t] for a, b, _, t in out]


def _str(v, what: str, required=True) -> str | None:
    if v is None and not required:
        return None
    if isinstance(v, bool) or not isinstance(v, (str, int)):
        raise TranscriptError(f"{what} is missing or not text")
    return clean_text(str(v))


def read_input(path: Path) -> dict:
    """One input file -> {provenance..., video_url, segments, source_file, source_sha256}."""
    m = NAME_RE.match(path.name)
    if not m:
        raise TranscriptError(f"{path.name}: not named <YYYY-MM-DD>_<eventId>.json")
    data = path.read_bytes()
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TranscriptError(f"{path.name}: not JSON ({exc})") from None
    if not isinstance(raw, dict):
        raise TranscriptError(f"{path.name}: not a JSON object")
    try:
        rec = {k: _str(raw.get(k), k) for k in PROVENANCE}
        rec["video_url"] = _str(raw.get("video_url") or None, "video_url", required=False)
        rec["segments"] = compact_segments(raw.get("segments"))
    except TranscriptError as exc:
        raise TranscriptError(f"{path.name}: {exc}") from None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", rec["start"]):
        raise TranscriptError(f"{path.name}: start {rec['start']!r} is not a date")
    if rec["start"][:10] != m.group(1) or str(rec["event_id"]) != m.group(2):
        raise TranscriptError(f"{path.name}: the file name does not match its start date and event_id")
    if not rec["segments"]:
        raise TranscriptError(f"{path.name}: no segments with text")
    rec["source_file"] = path.name
    rec["source_sha256"] = hashlib.sha256(data).hexdigest()
    return rec


def _event_differs(rec: dict, meeting: dict) -> bool:
    """True when the meeting carries an event_id and it is not the transcript's."""
    ev = meeting.get("event_id")
    return ev is not None and str(ev) != str(rec.get("event_id"))


def match(rec: dict, meetings: list[dict], kind_of) -> tuple[dict | None, str]:
    """(meeting, how) or (None, why not). See the module docstring for the rule."""
    if rec["video_url"]:
        hits = [m for m in meetings if m.get("video_url") and m["video_url"] == rec["video_url"]]
        if len(hits) != 1:
            return None, (f"video_url names {len(hits)} meetings" if hits else
                          "video_url is no meeting's video (not matched by date: the link would name another video)")
        how = "video_url"
    else:
        date, kind = rec["start"][:10], kind_of(rec["event_name"])
        hits = [m for m in meetings if m["date"] == date and m["kind"] == kind]
        if len(hits) != 1:
            return None, f"{len(hits)} meetings on {date} of kind {kind}"
        if not hits[0].get("video_url"):
            return None, f"meeting {hits[0]['id']} has no video_url to link to"
        how = "date_kind"
    if _event_differs(rec, hits[0]):
        return None, (f"meeting {hits[0]['id']} is event {hits[0]['event_id']}, the transcript is event "
                      f"{rec.get('event_id')}")
    return hits[0], how


def stale(t: dict, meetings: dict[str, dict]) -> str | None:
    """Why a committed transcript no longer matches a meeting of the facts file, or None when it still does."""
    m = meetings.get(t.get("meeting_id"))
    if m is None:
        return f"meeting {t.get('meeting_id')!r} is not in the facts file"
    if not m.get("video_url") or m["video_url"] != t.get("video_url"):
        return f"meeting {m['id']}'s video_url is not the transcript's"
    if _event_differs(t, m):
        return f"meeting {m['id']} is event {m['event_id']}, the transcript is event {t.get('event_id')}"
    return None


def render(rec: dict) -> str:
    """The committed form: sorted keys, one segment per line, no clock."""
    head = {k: v for k, v in rec.items() if k != "segments"}
    head = json.dumps(head, indent=1, sort_keys=True, ensure_ascii=False)
    segs = ",\n".join(json.dumps(s, ensure_ascii=False, separators=(",", ":")) for s in rec["segments"])
    return head[:-2] + ',\n "segments": [\n' + segs + "\n ]\n}\n"


def _write(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def build_index(out_dir: Path) -> dict:
    """{meeting id: summary} from the transcript files in out_dir (index.json excluded)."""
    idx = {}
    for p in sorted(out_dir.glob("*.json")):
        if p.name == "index.json":
            continue
        t = json.loads(p.read_text(encoding="utf-8"))
        idx[t["meeting_id"]] = {"file": p.name, "segments": len(t["segments"]), "video_url": t["video_url"],
                                "event_id": t["event_id"], "model": t["model"], "model_version": t["model_version"],
                                "created_at": t["created_at"], "source_file": t["source_file"]}
    return idx


def import_dir(src: Path, facts: dict, out_dir: Path, kind_of) -> dict:
    """Import every <date>_<event>.json in src, and remove the transcripts in out_dir that no longer match a meeting.
    Returns {"imported": [...], "unchanged": [...], "skipped": [...], "removed": [...]}."""
    meetings = facts["meetings"]
    chosen: dict[str, dict] = {}
    log = {"imported": [], "unchanged": [], "skipped": [], "removed": []}
    for path in sorted(Path(src).glob("*.json")):
        try:
            rec = read_input(path)
        except TranscriptError as exc:
            log["skipped"].append({"file": path.name, "why": str(exc)})
            continue
        m, how = match(rec, meetings, kind_of)
        if m is None:
            log["skipped"].append({"file": path.name, "why": how})
            continue
        if not _ID_RE.match(m["id"]):
            log["skipped"].append({"file": path.name, "why": f"meeting id {m['id']!r} is not a safe file name"})
            continue
        rec = {**rec, "meeting_id": m["id"], "matched_by": how, "video_url": m["video_url"]}
        prev = chosen.get(m["id"])
        if prev is not None:
            keep, drop = sorted([prev, rec], key=lambda r: (r["created_at"], r["source_file"]))[::-1]
            log["skipped"].append({"file": drop["source_file"],
                                   "why": f"{keep['source_file']} is a later transcript of {m['id']}"})
            rec = keep
        chosen[m["id"]] = rec
    for mid, rec in sorted(chosen.items()):
        changed = _write(out_dir / f"{mid}.json", render(rec))
        log["imported" if changed else "unchanged"].append({"file": rec["source_file"], "meeting_id": mid,
                                                             "matched_by": rec["matched_by"],
                                                             "segments": len(rec["segments"])})
    by_id = {m["id"]: m for m in meetings}
    for p in sorted(Path(out_dir).glob("*.json")) if Path(out_dir).is_dir() else []:
        if p.name == "index.json":
            continue
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
            why = stale(t, by_id) if isinstance(t, dict) else "not a transcript object"
        except (UnicodeDecodeError, json.JSONDecodeError):
            why = "not JSON"
        if why is None and p.name != f"{t['meeting_id']}.json":
            why = "file name is not its meeting id"
        if why is not None:
            p.unlink()
            log["removed"].append({"file": p.name, "why": why})
    out_dir.mkdir(parents=True, exist_ok=True)
    index = build_index(out_dir)
    _write(out_dir / "index.json", json.dumps(index, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    log["meetings_with_transcript"] = len(index)
    return log


def transcripts_dir(facts_path: Path) -> Path:
    """Where a council's transcripts live: beside its facts file."""
    return Path(facts_path).parent / "transcripts"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m collector transcripts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="import transcript JSON files from a folder")
    imp.add_argument("src", help="folder of <YYYY-MM-DD>_<eventId>.json files")
    imp.add_argument("--locality", default="clarksville-tn", help="the council (config/localities/<locality>/)")
    a = ap.parse_args(argv)
    from sitegen.config import load_council
    from .agenda_center import config_path, load_config
    cfg = load_council(a.locality)
    facts = json.loads(Path(cfg["facts_path"]).read_text(encoding="utf-8"))
    kind_of = load_config(config_path(a.locality)).kind_of
    if not Path(a.src).is_dir():
        print(f"transcripts: {a.src} is not a folder", file=sys.stderr)
        return 1
    log = import_dir(Path(a.src), facts, transcripts_dir(cfg["facts_path"]), kind_of)
    print(json.dumps(log, indent=1, sort_keys=True))
    return 0
