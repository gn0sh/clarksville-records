"""Adapter 2: a text bid-tab PDF's words -> bid tab fields and bidders (architecture A2, task F5).

Called only for a document the scan guard lets through (fin_checks.unreadable: a text layer, not a shared URL).

Fields: a line that starts with a finance.yml `bidtab.fields` label; the value is the rest of the line with "_" fill
removed ("Bid Awarded to____McCoy Construction &Forestry___" -> "McCoy Construction &Forestry"). The first line
with a label wins.
Bidder table: the header line holds the `columns` labels ("Bidder Name", "Total") and only those plus
`optional_columns`; any other header word is another layout (itemised, unit price) and the tab is not read. Column
bands come from the header words' x-positions (boundaries halfway across the gaps); a word belongs to the band that
holds its centre. Rows run from the header to the first line that starts with a field label or a `table_end`
label. A line with name-band words and a Total-band token starts a bidder; a following line with name-band words and
no total continues its name ("McCoy Construction &" / "Forestry"). A Total token that is not one amount is kept as
printed and its value held (check amount-format). Anything else (a total with no name, a name line before any total,
no bidder, words with no digit in the Total column) means the layout is not the one these rules read: not_read. No
value is ever guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .fin_config import BidTabRules
from .pdfwords import Line, Word, lines as group_lines

AMOUNT = re.compile(r"^\$?(\d{1,3}(?:,\d{3})*)(?:\.(\d{2}))?$")
FILL = re.compile(r"_+")


@dataclass
class Bidder:
    printed_order: int
    name: str
    total_as_printed: str | None
    total_cents: int | None
    page: int


@dataclass
class BidTabRead:
    tab_type: str                      # lump_sum | not_read
    reason: str | None                 # why not read (layout detail), None when lump_sum
    fields: dict = field(default_factory=dict)      # key -> (text, page); a missing label or empty value is absent
    bidders: list = field(default_factory=list)
    held: list = field(default_factory=list)        # [(field path, check)]


def cents(token: str) -> int | None:
    m = AMOUNT.match(token)
    if not m:
        return None
    return int(m.group(1).replace(",", "")) * 100 + int(m.group(2) or 0)


def clean(text: str) -> str:
    return " ".join(FILL.sub(" ", text).split())


def _starts_with(text: str, label: str) -> str | None:
    """The rest of `text` after `label` at its start (whole words, any case), else None."""
    lab = clean(label)
    if text.casefold() == lab.casefold():
        return ""
    if text.casefold().startswith(lab.casefold() + " "):
        return text[len(lab):].strip()
    return None


def _field_of(text: str, rules: BidTabRules) -> tuple[str, str] | None:
    for key, label in sorted(rules.fields.items(), key=lambda kv: -len(kv[1])):
        rest = _starts_with(text, label)
        if rest is not None:
            return key, rest
    return None


def _ends_table(text: str, rules: BidTabRules) -> bool:
    return _field_of(text, rules) is not None or any(_starts_with(text, e) is not None or text.startswith(e)
                                                     for e in rules.table_end)


def _find_seq(words: list[Word], label: str) -> list[Word] | None:
    parts = label.split()
    for i in range(len(words) - len(parts) + 1):
        if [w.text.casefold() for w in words[i:i + len(parts)]] == [p.casefold() for p in parts]:
            return words[i:i + len(parts)]
    return None


def _header(line: Line, rules: BidTabRules):
    """-> (bands [(key, lo, hi)], None) for the table header, (None, reason) for another layout, or None."""
    name = _find_seq(line.words, rules.columns["name"])
    total = _find_seq(line.words, rules.columns["total"])
    if not name or not total:
        return None
    cols = [("name", name), ("total", total)]
    used = set(map(id, name + total))
    for opt in rules.optional_columns:
        seq = _find_seq([w for w in line.words if id(w) not in used], opt)
        if seq:
            cols.append(("optional", seq))
            used |= set(map(id, seq))
    other = [w.text for w in line.words if id(w) not in used]
    if other:
        return None, f"header has other columns: {' '.join(other)!r}"
    spans = sorted(((k, min(w.x0 for w in ws), max(w.x1 for w in ws)) for k, ws in cols), key=lambda s: s[1])
    if [k for k, _, _ in spans].index("name") > [k for k, _, _ in spans].index("total"):
        return None, "Total column is left of the name column"
    bands = []
    for i, (k, x0, x1) in enumerate(spans):
        lo = float("-inf") if i == 0 else (spans[i - 1][2] + x0) / 2
        hi = float("inf") if i == len(spans) - 1 else (x1 + spans[i + 1][1]) / 2
        bands.append((k, lo, hi))
    return bands, None


def _band(w: Word, bands) -> str:
    return next(k for k, lo, hi in bands if lo <= w.xc < hi)


def read_bidtab(words: list[Word], rules: BidTabRules) -> BidTabRead:
    ls = group_lines(words)
    fields: dict = {}
    bands = header_at = None
    for i, ln in enumerate(ls):
        h = _header(ln, rules)
        if h is not None:
            bands, why = h
            if bands is None:
                return BidTabRead("not_read", why)
            header_at = i
            break
        f = _field_of(clean(ln.text), rules)
        if f and f[0] not in fields and f[1]:
            fields[f[0]] = (f[1], ln.page)
    if bands is None:
        return BidTabRead("not_read", "no bidder table header")
    bidders: list[Bidder] = []
    held: list = []
    end = len(ls)
    for j in range(header_at + 1, len(ls)):
        ln = ls[j]
        text = clean(ln.text)
        if not text:
            continue                                    # a fill-only line
        if _ends_table(text, rules):
            end = j
            break
        h = _header(ln, rules)
        if h is not None and h[0] is not None:
            continue                                    # the header repeated on a new page
        name = [w for w in ln.words if _band(w, bands) == "name" and clean(w.text)]
        total = [w for w in ln.words if _band(w, bands) == "total" and clean(w.text)]
        if total and not name:
            return BidTabRead("not_read", f"a total with no bidder name on page {ln.page}: {text!r}")
        if total:
            token = " ".join(w.text for w in total)
            if not any(c.isdigit() for c in token):
                return BidTabRead("not_read", f"words, not an amount, in the Total column on page {ln.page}: {text!r}")
            value = cents(token) if len(total) == 1 else None
            n = len(bidders) + 1
            if value is None:
                held.append((f"bid_tab.bidders[{n - 1}].total_cents", "amount-format"))
            bidders.append(Bidder(n, " ".join(clean(w.text) for w in name), token, value, ln.page))
        elif name:
            if not bidders:
                return BidTabRead("not_read", f"a name line before any total on page {ln.page}: {text!r}")
            bidders[-1].name += " " + " ".join(clean(w.text) for w in name)
    for ln in ls[end:]:
        f = _field_of(clean(ln.text), rules)
        if f and f[0] not in fields and f[1]:
            fields[f[0]] = (f[1], ln.page)
    if not bidders:
        return BidTabRead("not_read", "no bidder rows under the header")
    return BidTabRead("lump_sum", None, fields, bidders, held)
