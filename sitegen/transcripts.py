"""Meeting video transcripts on a council's pages (spec AC6.3; transcripts from collector/transcripts.py).

Rules:
- Every transcript line is shown as the speech-recognition software wrote it, labelled "Transcript", with its time
  linked to that moment of the meeting's own video (`<video_url>#t=<whole seconds>`) when that video_url is an https
  .mp4 on a host in config.VIDEO_HOSTS with no "#" in it (video_ok); otherwise the times are text only, no links. Nothing is summarised,
  reworded or corrected; the page says the video is the record.
- Who speaks is never read from the voice. A "call-on" is found only in the transcript TEXT, under the call-on
  invariant (docs/architecture/city-council.md): a member's title and surname followed, in the same clause (only
  spaces and commas between), by "you're recognized" / "you are recognized" (or Whisper's "you recognized") that ends
  the clause (punctuation, the end of that line's text, or the reply "thank you" / "thanks" next), or the title and
  surname after "the chair recognizes" ("Councilman Chandler, you're recognized.", "the chair recognizes Councilwoman
  Smith"). Nothing else counts ("Councilwoman Smith recognized the students", "Councilman Smith. You are recognized",
  "Councilman Smith, you recognized that the budget was short" are not call-ons). The surname is resolved under
  the name resolution invariant (docs/architecture/city-council.md): exactly one entry of that meeting's own
  attendance list, as read from its minutes and shown on the site, has that surname, and that entry resolved to a
  member who is listed present. An entry that did not resolve blocks every word of its printed name and every
  registered surname inside it; an entry listed absent blocks its surname but never links. No minutes read, no
  attendance shown, no match or two matches: no link. Never a near spelling.
- Each member page lists the call-ons resolved to them, the same way for every member: the date, the time linked to
  the video, the matched call-on words verbatim, and about CALL_ON_SECONDS of transcript text after the call-on,
  verbatim, labelled as transcript text.

Files: one page per meeting with a transcript (<slug>/transcripts/<meeting id>.html), split into parts with the
year pages' part pattern when over config.PAGE_BYTES. A preview build over its file cap leaves these pages out
(build.py); the member lists and the video links stay.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit

from . import config, views

CALL_ON_SECONDS = 20
FOLDER = "transcripts"
LABEL = "Transcript"
NOTICE = ("Automatic transcript made by speech-recognition software from the city's video. It may contain errors. "
          "The video is the record.")
# Titles a presiding officer uses to give a member the floor. The surname is one word after the title.
TITLES = r"council(?:man|woman|person|member|lady)|chair(?:man|woman|person)?|vice[\s-]+chair(?:man|woman|person)?"
_NAME = r"(?P<name>[A-Za-z][A-Za-z'’-]*)"
_GAP = r"[\s,]*"      # one clause: no sentence break between the surname and the recognition
CALL_ON_PATTERNS = (
    # "Councilman Chandler, you're recognized" / "you are recognized" / Whisper's "you recognized". Only these: a bare
    # "recognized" ("Councilwoman Smith recognized the students") or "you recognize" is not a call-on. The phrase must
    # also end its clause (_ends_clause): "you recognized that the budget was short" is not a call-on.
    re.compile(r"\b(?P<title>" + TITLES + r")\s+" + _NAME + _GAP
               + r"(?P<you>you\s*['’]?\s*re|you\s+are|you)\s+recogni[sz]ed\b", re.I),
    # "the chair recognizes Councilwoman Smith"
    re.compile(r"\bthe\s+chair\s+recogni[sz]es\s+(?P<title>" + TITLES + r")\s+" + _NAME + r"\b", re.I),
)
# What may follow "you're recognized" for it to end its clause: punctuation, or the member's reply starting a new
# sentence that Whisper left unpunctuated ("thank you", "thanks", never "thanks to"). A comma ends it only after
# "you're" / "you are" (_CLAUSE_END_COMMA), never after a bare "you recognized" ("you recognized, I think, the
# problem"). The end of a line's text ends it only when the next line starts the same way (or there is none).
_CLAUSE_END = re.compile(r"\s*(?:[.;:!?]|thank\s+you\b|thanks\b(?!\s+to\b))", re.I)
_CLAUSE_END_COMMA = re.compile(r"\s*,")
# words that can follow a title but are never a surname
NOT_A_NAME = {"you", "your", "you're", "youre", "is", "are", "be", "she", "he", "the", "a", "from", "for", "of", "on",
              "and", "who", "that", "has", "have", "was", "were", "will", "would", "said", "says", "recognized",
              "recognize", "recognizes", "i", "we", "it", "to", "in", "at", "with", "if", "so", "but"}


class TranscriptLoadError(ValueError):
    pass


def video_ok(video_url) -> bool:
    """Whether timestamp links may be made to this video: https, a host in config.VIDEO_HOSTS (no user or port), a
    path ending .mp4, and no "#" already in it."""
    if not isinstance(video_url, str) or "#" in video_url:
        return False
    try:
        u = urlsplit(video_url)
        port = u.port
    except ValueError:
        return False
    return (u.scheme == "https" and u.hostname in config.VIDEO_HOSTS and u.netloc == u.hostname and port is None
            and u.path.lower().endswith(".mp4"))


def video_href(video_url: str, seconds: float) -> str | None:
    """The video at a moment: whole seconds, rounded down, so the link never starts after the words. None when the
    video_url is not one video_ok allows (the time is then shown as text only)."""
    if not video_ok(video_url):
        return None
    return f"{video_url}#t={int(math.floor(seconds))}"


def clock(seconds: float) -> str:
    s = int(math.floor(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def load(facts_path: Path, facts: dict) -> dict[str, dict]:
    """{meeting id: transcript} from <facts folder>/transcripts/index.json (none: {}). Every transcript must name a
    meeting of these facts and carry exactly that meeting's video_url; its segments [start, end, text]. (Whether its
    times link to the video is video_ok's rule.)"""
    folder = Path(facts_path).parent / FOLDER
    index_path = folder / "index.json"
    if not index_path.is_file():
        return {}
    meetings = {m["id"]: m for m in facts["meetings"]}
    out = {}
    for mid, entry in sorted(json.loads(index_path.read_text(encoding="utf-8")).items()):
        if mid not in meetings:
            raise TranscriptLoadError(f"{index_path}: transcript for {mid}, which is not a meeting in the facts")
        t = json.loads((folder / Path(entry["file"]).name).read_text(encoding="utf-8"))
        vu = meetings[mid].get("video_url")
        if t.get("meeting_id") != mid or not vu or t.get("video_url") != vu:
            raise TranscriptLoadError(f"{folder / entry['file']}: does not carry meeting {mid}'s video_url")
        for s in t["segments"]:
            if not (isinstance(s, list) and len(s) == 3 and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                                 and math.isfinite(x) and x >= 0 for x in s[:2])
                    and isinstance(s[2], str)):
                raise TranscriptLoadError(f"{folder / entry['file']}: malformed segment {s!r:.80}")
        out[mid] = t
    return out


def _joined(segments: list) -> tuple[str, list[int]]:
    """The segments' text joined by single spaces, and each segment's start offset in it."""
    starts, parts, pos = [], [], 0
    for s in segments:
        starts.append(pos)
        parts.append(s[2])
        pos += len(s[2]) + 1
    return " ".join(parts), starts


def _seg_at(starts: list[int], offset: int) -> int:
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= offset:
            lo = mid
        else:
            hi = mid - 1
    return lo


def detect(segments: list) -> list[dict]:
    """Call-ons found in the transcript text, in time order: {seg, seconds, title, name, end_seg, matched, excerpt}.
    seg: the line where the title starts (the link's time); matched: the call-on words themselves, verbatim (shown
    with each entry so a reader can judge the match); excerpt: the text after the call-on words, verbatim,
    through the lines that start within CALL_ON_SECONDS of the line where those words end, and never past the next
    call-on."""
    text, starts = _joined(segments)
    line_end = {starts[i] + len(s[2].rstrip()): i for i, s in enumerate(segments)}

    def ends_clause(m) -> bool:
        b = m.end()
        if b in line_end:   # the end of a line: the next line must start a new clause (or there is none)
            i = line_end[b]
            if i + 1 == len(segments):
                return True
            b = starts[i + 1]
        if _CLAUSE_END.match(text, b):
            return True
        return m.group("you").lower() != "you" and bool(_CLAUSE_END_COMMA.match(text, b))

    hits = []
    for k, rx in enumerate(CALL_ON_PATTERNS):
        for m in rx.finditer(text):
            if m.group("name").lower().strip("'’") in NOT_A_NAME:
                continue
            if k == 0 and not ends_clause(m):
                continue   # "you recognized that ...": the phrase does not end its clause
            hits.append((m.start(), m.end(), m.group("title"), m.group("name")))
    hits.sort()
    kept = []
    for h in hits:   # one pattern's match inside another's is the same call-on
        if kept and h[0] < kept[-1][1]:
            continue
        kept.append(h)
    out = []
    for i, (a, b, title, name) in enumerate(kept):
        seg, end_seg = _seg_at(starts, a), _seg_at(starts, max(a, b - 1))
        limit = segments[end_seg][0] + CALL_ON_SECONDS
        last = end_seg
        while last + 1 < len(segments) and segments[last + 1][0] < limit:
            last += 1
        stop = starts[last] + len(segments[last][2])
        if i + 1 < len(kept):
            stop = min(stop, kept[i + 1][0])
        out.append({"seg": seg, "seconds": segments[seg][0], "title": title, "name": name, "end_seg": end_seg,
                    "matched": text[a:b], "excerpt": text[b:stop].strip(" ,.;:!?-")})
    return out


def roster(meeting: dict, officials: dict) -> list[dict] | None:
    """One entry per line of the meeting's attendance as shown on the site: {official_id (None when the line did not
    resolve), names (casefolded words that match it), absent}. None when no attendance is shown (no minutes read, or
    attendance under review).
    A resolved line matches its member's surname. A line that did not resolve matches every word of its printed name
    and every registered surname (any official's) found inside the printed name with spaces removed, any case
    ("DaJaun Little m", "StaceyStreetman"): it blocks those names, never links them."""
    if not views.attendance_shown(meeting):
        return None
    surnames = {o["surname"].casefold() for o in officials.values() if o.get("surname")}
    out = []
    for a in meeting["attendance"]:
        o = officials.get(a["official_id"]) if a["official_id"] else None
        absent = a.get("status") == "absent"
        if o is not None:
            out.append({"official_id": o["id"], "names": frozenset({o["surname"].casefold()}), "absent": absent})
        else:
            raw = a.get("raw_name") or ""
            words = {w.strip("'’-").casefold() for w in re.findall(r"[A-Za-z'’-]+", raw)} - {""}
            squashed = "".join(raw.split()).casefold()
            words |= {s for s in surnames if s in squashed}
            out.append({"official_id": None, "names": frozenset(words), "absent": absent})
    return out


def resolve(name: str, entries: list[dict] | None) -> tuple[str | None, str]:
    """(official id, "") when exactly one roster entry matches the printed name (any case) and that entry is a
    member listed present; else (None, why)."""
    if entries is None:
        return None, "no attendance shown for this meeting"
    key = name.strip("'’").casefold()
    hits = [e for e in entries if key in e["names"]]
    if len(hits) != 1:
        return None, f"{len(hits)} attendance entries with this surname"
    if hits[0]["official_id"] is None:
        return None, "the attendance entry with this surname did not resolve to a member"
    if hits[0]["absent"]:
        return None, "the attendance entry with this surname is listed absent"
    return hits[0]["official_id"], ""


class Transcripts:
    """A council's transcripts and the call-ons resolved in them. `pages`: whether transcript pages are built."""

    def __init__(self, cix, transcripts: dict[str, dict], pages: bool = True):
        self.cix, self.by_meeting, self.pages = cix, transcripts, pages
        self.part_of: dict[tuple[str, int], int] = {}     # (meeting id, segment index) -> part number
        self.call_ons: dict[str, list[dict]] = {}          # meeting id -> resolved call-ons
        for mid, t in transcripts.items():
            m = cix.meetings[mid]
            entries = roster(m, cix.officials)
            found = []
            for d in detect(t["segments"]):
                oid, _why = resolve(d["name"], entries)
                if oid is not None:
                    found.append({**d, "official_id": oid, "meeting_id": mid})
            self.call_ons[mid] = found

    def page_href(self, meeting_id: str, part: int = 1) -> str:
        return f"{self.cix.slug}/{FOLDER}/{meeting_id}{'' if part == 1 else f'-{part}'}.html"

    def line_href(self, meeting_id: str, seg: int) -> str:
        return f"{self.page_href(meeting_id, self.part_of.get((meeting_id, seg), 1))}#s{seg}"

    def meeting_entry(self, meeting_id: str) -> dict | None:
        """What a meeting's section shows: its transcript link (or why there is none on this copy)."""
        t = self.by_meeting.get(meeting_id)
        if t is None:
            return None
        return {"href": self.page_href(meeting_id) if self.pages else None, "lines": len(t["segments"]),
                "model": t["model"], "video_url": t["video_url"]}

    def member_rows(self, official_id: str) -> list[dict]:
        """The member's call-ons, oldest first: the same fields for every member."""
        rows = []
        for mid in sorted(self.call_ons, key=lambda k: (self.cix.meetings[k]["date"], k)):
            m = self.cix.meetings[mid]
            for d in self.call_ons[mid]:
                if d["official_id"] != official_id:
                    continue
                rows.append({"date": m["date"], "meeting_id": mid, "meeting_label": self.cix.meeting_label(m),
                             "meeting_href": self.cix.meeting_href(mid),
                             "time": clock(d["seconds"]),
                             "video_href": video_href(self.by_meeting[mid]["video_url"], d["seconds"]),
                             "line_href": self.line_href(mid, d["seg"]) if self.pages else None,
                             "matched": d["matched"], "excerpt": d["excerpt"]})
        return rows

    def lines(self, meeting_id: str) -> list[dict]:
        """Every line of a transcript page: {id, seg, time, href, text, call_on: {name, href} or None}."""
        t = self.by_meeting[meeting_id]
        marks: dict[int, list[dict]] = {}
        for d in self.call_ons.get(meeting_id, []):
            o = self.cix.officials[d["official_id"]]
            marks.setdefault(d["seg"], []).append({"name": o["name"], "href": self.cix.official_href(o["id"])})
        return [{"id": f"s{i}", "seg": i, "time": clock(s[0]), "href": video_href(t["video_url"], s[0]),
                 "text": s[2], "call_ons": marks.get(i, [])} for i, s in enumerate(t["segments"])]

    def page(self, meeting_id: str) -> dict:
        t = self.by_meeting[meeting_id]
        m = self.cix.meetings[meeting_id]
        src = self.cix.sources.get(m.get("source_id") or "") or {}
        doc = {"url": src["url"], "kind": src.get("kind") or "Minutes"} if src.get("url") else None
        return {"meeting": m, "doc": doc, "kind_label": self.cix.kind_labels[m["kind"]],
                "meeting_href": self.cix.meeting_href(meeting_id), "video_url": t["video_url"],
                "video_ok": video_ok(t["video_url"]),
                "notice": NOTICE, "label": LABEL, "model": t["model"], "model_version": t["model_version"],
                "created_at": t["created_at"], "call_on_count": len(self.call_ons.get(meeting_id, [])),
                "lines": self.lines(meeting_id)}
