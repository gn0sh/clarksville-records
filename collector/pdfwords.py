"""Words with positions from `pdftotext -bbox` (poppler, already required), grouped into lines (architecture A1).

A word is {page, x0, x1, y0, y1, text} in PDF points (y grows down the page, as pdftotext prints it). Lines are
built per page from word centres: a word joins the line whose centre is within LINE_TOL of its height of the word's
centre, so a tall header cell and the shorter first row under it (whose boxes overlap) stay two lines. Words in a
line are left to right. Deterministic: the same PDF gives the same words and lines.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

PARSE_TIMEOUT = 120       # seconds; TimeoutExpired is a parse failure for that document (pipeline/parser-dos)
LINE_TOL = 0.35          # fraction of the smaller word height


@dataclass(frozen=True)
class Word:
    page: int
    x0: float
    x1: float
    y0: float
    y1: float
    text: str

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def h(self) -> float:
        return self.y1 - self.y0


@dataclass
class Line:
    page: int
    words: list = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def yc(self) -> float:
        return sum(w.yc for w in self.words) / len(self.words)

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)


class _Bbox(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.page = 0
        self.pages = 0
        self.words: list[Word] = []
        self._w = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "page":
            self.page += 1
            self.pages += 1
        elif tag == "word":
            self._w = [float(a["xmin"]), float(a["xmax"]), float(a["ymin"]), float(a["ymax"]), ""]

    def handle_endtag(self, tag):
        if tag == "word" and self._w is not None:
            x0, x1, y0, y1, text = self._w
            if text.strip():
                self.words.append(Word(self.page, x0, x1, y0, y1, text.strip()))
            self._w = None

    def handle_data(self, d):
        if self._w is not None:
            self._w[4] += d


def parse_bbox(xhtml: str) -> tuple[list[Word], int]:
    """(words, page count) from `pdftotext -bbox` output."""
    p = _Bbox()
    p.feed(xhtml)
    p.close()
    return p.words, p.pages


def bbox_text(pdf: Path, first: int | None = None, last: int | None = None) -> str:
    cmd = ["pdftotext", "-bbox", "-enc", "UTF-8"]
    if first:
        cmd += ["-f", str(first)]
    if last:
        cmd += ["-l", str(last)]
    return subprocess.run(cmd + [str(pdf), "-"], check=True, capture_output=True,
                          timeout=PARSE_TIMEOUT).stdout.decode("utf-8", "replace")


def pdf_words(pdf: Path, first: int | None = None, last: int | None = None) -> list[Word]:
    words, _ = parse_bbox(bbox_text(pdf, first, last))
    if first and first > 1:                 # pdftotext numbers pages of a range from 1; give the PDF page index
        words = [Word(w.page + first - 1, w.x0, w.x1, w.y0, w.y1, w.text) for w in words]
    return words


def lines(words: list[Word]) -> list[Line]:
    """Words grouped into lines, per page top to bottom, each line left to right."""
    out: list[Line] = []
    for page in sorted({w.page for w in words}):
        open_lines: list[Line] = []
        for w in sorted((w for w in words if w.page == page), key=lambda w: (w.yc, w.x0)):
            best = None
            for ln in open_lines:
                tol = LINE_TOL * min(w.h, min(x.h for x in ln.words))
                if abs(ln.yc - w.yc) <= tol and (best is None or abs(ln.yc - w.yc) < abs(best.yc - w.yc)):
                    best = ln
            if best is None:
                best = Line(page)
                open_lines.append(best)
            best.words.append(w)
        for ln in open_lines:
            ln.words.sort(key=lambda w: (w.x0, w.y0))
        out.extend(sorted(open_lines, key=lambda ln: (ln.yc, ln.x0)))
    return out
