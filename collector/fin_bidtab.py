"""Adapter 2: a text bid-tab PDF's words -> bid tab fields and bidders (architecture A2, task F5).

Called only for a document the scan guard lets through (fin_checks.unreadable: a text layer, not a shared URL).

Fields: a line that starts with one of a finance.yml `bidtab.fields` label (a ":" right after the label is part of
it: "Department:"); the value is the rest of the line with "_" fill removed ("Bid Awarded to____McCoy Construction
&Forestry___" -> "McCoy Construction &Forestry"). The first line with a label wins.

Two lump-sum layouts are read; anything else is not_read with the reason (unit-price and itemised tabs, notes or
words in the amount column, a bidder without one printed total). No value is ever guessed.

Layout "table" (one line per bidder): the header line holds a `columns.name` label ("Bidder Name") and one
`columns.total` label ("Total", "Total Bid", "Lump Sum Bid") and only those plus `optional_columns`; any other header
word is another layout (itemised, unit price). Column bands come from the header words' x-positions (boundaries
halfway across the gaps); a word belongs to the band that holds its centre. Rows run from the header to the first
line that starts with a field label or a `table_end` label. A line with name-band words and a Total-band token starts
a bidder; a following line with name-band words and no total continues its name ("McCoy Construction &" /
"Forestry"). A Total cell that is one token with a digit but not a well-formed amount ("$3990.63", "$211,887.0O"), or
a lone "$" and one token ("$ 765,790.00"), is kept as printed and its value held (check amount-format). Anything else
(a total with no name, a name line before any total, no bidder, words in the Total column such as "$330.00 per load"
or notes running into it, any word in an optional column such as Notes, which would otherwise be dropped unseen, a
name continuation line not adjacent to the line above it: same page, within NAME_GAP word heights) means the layout
is not the one these rules read: not_read.

Layout "blocks" (`blocks`, the engineering tabs: "Contractor | Bid Bond | Bid Amount"): one block of labelled
amounts per bidder ("Base Bid: $49,124.00", "Add Alternate #1: $25,936.00", "Total Bid: $149,362.00"), the name in
the left column, addendum and bid-bond ticks between. The name column ends at the leftmost other header word
(including the addendum header lines just above and below the header). A block starts at the line whose first label
is `first_label`; every other word right of the name column is an amount, a tick (`marks`, or a word with no letter
or digit, before any label on its line), or a label word, and every label ends in ":" (else "NON RESPONSIVE" and the
like: not_read). Labels and amounts must alternate in reading order. A bidder's printed total is its one
`total_labels` amount (the last pair), or its `first_label` amount when that is its only amount; a bidder with base
bid and alternates but no printed total is not_read. A printed total whose parts do not add up to it is held (check
total-parts, fin_checks.parts_add_up). Name lines of one block must be adjacent (each within NAME_GAP word heights
of the one before), so a name is never joined across two bidders.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import fin_checks
from .fin_config import BidTabRules, BlockRules
from .pdfwords import Line, Word, lines as group_lines

AMOUNT = re.compile(r"^\$?(\d{1,3}(?:,\d{3})*)(?:\.(\d{2}))?$")
FILL = re.compile(r"_+")
NAME_GAP = 1.6           # word heights between two name lines of one block (the 8 real block tabs: under 1.2)
NO_HEADER = "no bidder table header the rules know (itemised or unit-price layout, not read in 1a)"


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
    layout: str | None = None          # table | blocks, when lump_sum


class NotRead(Exception):
    """This tab's layout is not one the rules read; the message is the reason."""


def cents(token: str) -> int | None:
    m = AMOUNT.match(token)
    if not m:
        return None
    return int(m.group(1).replace(",", "")) * 100 + int(m.group(2) or 0)


def clean(text: str) -> str:
    return " ".join(FILL.sub(" ", text).split())


def _starts_with(text: str, label: str) -> str | None:
    """The rest of `text` after `label` at its start (whole words, any case; a ":" right after the label is part of
    it), else None."""
    lab = clean(label)
    if text.casefold() == lab.casefold():
        return ""
    if not text.casefold().startswith(lab.casefold()):
        return None
    rest = text[len(lab):]
    if rest.startswith(":"):
        return rest[1:].strip()
    return rest.strip() if rest.startswith(" ") else None


def _field_of(text: str, rules: BidTabRules) -> tuple[str, str] | None:
    labels = sorted(((k, lab) for k, labs in rules.fields.items() for lab in labs), key=lambda kv: -len(kv[1]))
    for key, label in labels:
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


def _find_any(words: list[Word], labels) -> list[Word] | None:
    """The first of `labels` (longest first) found in `words`."""
    for lab in sorted(labels, key=lambda s: -len(s.split())):
        seq = _find_seq(words, lab)
        if seq:
            return seq
    return None


def _header(line: Line, rules: BidTabRules):
    """-> (bands [(key, lo, hi)], None) for the table header, (None, reason) for another layout, or None."""
    name = _find_any(line.words, rules.columns["name"])
    total = _find_any(line.words, rules.columns["total"])
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


def _adjacent(prev: list[Word], nxt: list[Word]) -> bool:
    """Two name lines of one bidder: same page and the second within NAME_GAP word heights below the first."""
    if prev[0].page != nxt[0].page:
        return False
    h = min(w.h for w in prev + nxt)
    return sum(w.yc for w in nxt) / len(nxt) - sum(w.yc for w in prev) / len(prev) <= NAME_GAP * h


def _band(w: Word, bands) -> str:
    return next(k for k, lo, hi in bands if lo <= w.xc < hi)


def _block_header(line: Line, b: BlockRules):
    """-> (header word sequences, None) for the blocks header, (None, reason) for another layout, or None."""
    seqs = [_find_seq(line.words, h) for h in b.header]
    if not all(seqs):
        return None
    used = {id(w) for s in seqs for w in s}
    other = [w.text for w in line.words if id(w) not in used]
    if other:
        return None, f"header has other columns: {' '.join(other)!r}"
    if min(w.x0 for w in seqs[0]) > min(w.x0 for s in seqs[1:] for w in s):
        return None, f"the {b.header[0]!r} column is not the first column"
    return seqs, None


def _held_token(parts: list[str]) -> tuple[str, int | None]:
    """A total cell's text as printed and its value (None = held, amount-format)."""
    token = " ".join(parts)
    return token, (cents(token) if len(parts) == 1 else None)


# ------------------------------------------------------------------ layout "table"
def _read_table(ls: list[Line], header_at: int, bands, rules: BidTabRules) -> tuple[list, list, int]:
    bidders: list[Bidder] = []
    held: list = []
    end = len(ls)
    last_name: list[Word] = []                          # name words of the line the last bidder's name ends on
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
        notes = [w for w in ln.words if _band(w, bands) == "optional" and clean(w.text)]
        if notes:
            raise NotRead(f"words in an optional column (not read) on page {ln.page}: {text!r}")
        if total and not name:
            raise NotRead(f"a total with no bidder name on page {ln.page}: {text!r}")
        if total:
            parts = [w.text for w in total]
            one_token = len(parts) == 1 or (len(parts) == 2 and parts[0] == "$")     # "$ 765,790.00": held below
            if not one_token or not any(c.isdigit() for c in "".join(parts)):
                raise NotRead(f"words, not one amount, in the Total column on page {ln.page}: {text!r}")
            token, value = _held_token(parts)
            n = len(bidders) + 1
            if value is None:
                held.append((f"bid_tab.bidders[{n - 1}].total_cents", "amount-format"))
            bidders.append(Bidder(n, " ".join(clean(w.text) for w in name), token, value, ln.page))
            last_name = name
        elif name:
            if not bidders:
                raise NotRead(f"a name line before any total on page {ln.page}: {text!r}")
            if not _adjacent(last_name, name):
                raise NotRead(f"a name line not adjacent to the bidder above it on page {ln.page}: {text!r}")
            bidders[-1].name += " " + " ".join(clean(w.text) for w in name)
            last_name = name
    return bidders, held, end


# ------------------------------------------------------------------ layout "blocks"
def _norm_label(s: str) -> str:
    return " ".join(s.split()).casefold()


def _is_amount(text: str) -> bool:
    return any(c.isdigit() for c in text) and (text.startswith("$") or AMOUNT.match(text) is not None)


def _is_mark(text: str, b: BlockRules) -> bool:
    return text in b.marks or not any(c.isalnum() for c in text)


def _tokens(ln: Line, name_hi: float, b: BlockRules) -> tuple[list[Word], list]:
    """-> (name words, [("label", text) | ("amount", [words])] left to right). Ticks are dropped."""
    name = [w for w in ln.words if w.xc < name_hi and clean(w.text)]
    toks: list = []
    rest = [w for w in ln.words if w.xc >= name_hi]
    i = 0
    while i < len(rest):
        w = rest[i]
        if w.text == "$" and i + 1 < len(rest) and _is_amount(rest[i + 1].text):
            toks.append(("amount", [w, rest[i + 1]]))      # "$ 765,790.00": kept as printed, value held
            i += 2
            continue
        if _is_amount(w.text):
            toks.append(("amount", [w]))
        elif not toks and _is_mark(w.text, b):
            pass                                            # an addendum or bid-bond tick
        elif toks and toks[-1][0] == "label":
            toks[-1] = ("label", toks[-1][1] + " " + w.text)
        else:
            toks.append(("label", w.text))
        i += 1
    for kind, v in toks:
        if kind == "label" and not v.endswith(":"):
            raise NotRead(f"words, not one amount, in the {b.header[-1]} column on page {ln.page}: {clean(ln.text)!r}")
    return name, toks


def _zone_line(ln: Line, b: BlockRules) -> bool:
    """A line of only `header_words` and numbers ("Addendum Addendum", "No. 1 No. 2")."""
    allowed = {x.casefold() for x in b.header_words}
    return bool(ln.words) and all(w.text.casefold() in allowed or w.text.isdigit() for w in ln.words)


def _header_zone(ls: list[Line], at: int, b: BlockRules) -> tuple[list[Word], int]:
    """Header words of the addendum lines just above and below the header, and the first row line."""
    def zone(k):
        return 0 <= k < len(ls) and ls[k].page == ls[at].page and _zone_line(ls[k], b)
    words, start = [], at + 1
    if zone(at - 1):
        words += ls[at - 1].words
    if zone(at + 1):
        words += ls[at + 1].words
        start = at + 2
    return words, start


def _read_blocks(ls: list[Line], at: int, seqs, rules: BidTabRules) -> tuple[list, list, int]:
    b = rules.blocks
    zone, start = _header_zone(ls, at, b)
    others = [w for s in seqs[1:] for w in s] + zone
    name_hi = min(w.x0 for w in others)
    if name_hi <= max(w.x1 for w in seqs[0]):
        raise NotRead(f"the {b.header[0]!r} column overlaps the next column")
    blocks: list[list] = []                  # per bidder: [(line, name words, tokens)]
    end = len(ls)
    skip = set()
    for j in range(start, len(ls)):
        ln = ls[j]
        text = clean(ln.text)
        if not text or j in skip:
            continue
        if _ends_table(text, rules):
            end = j
            break
        h = _block_header(ln, b)
        if h is not None and h[0] is not None:          # the header repeated on a new page, with its addendum lines
            skip.add(_header_zone(ls, j, b)[1] - 1)
            continue
        if _zone_line(ln, b) and j + 1 < len(ls) and ls[j + 1].page == ln.page \
                and (_block_header(ls[j + 1], b) or (None,))[0]:
            continue                                    # the addendum line above a repeated header
        name, toks = _tokens(ln, name_hi, b)
        if toks and toks[0][0] == "label" and _norm_label(toks[0][1]) == _norm_label(b.first_label):
            blocks.append([])
        elif not blocks:
            if name or toks:
                raise NotRead(f"a line before the first {b.first_label!r} on page {ln.page}: {text!r}")
            continue
        blocks[-1].append((ln, name, toks))
    bidders: list[Bidder] = []
    held: list = []
    totals = {_norm_label(x) for x in b.total_labels}
    for blk in blocks:
        named = [(ln, nm) for ln, nm, _ in blk if nm]
        if not named:
            raise NotRead(f"a block with no bidder name on page {blk[0][0].page}: {clean(blk[0][0].text)!r}")
        for (l1, n1), (l2, n2) in zip(named, named[1:]):
            h = min(w.h for w in n1 + n2)
            if l1.page != l2.page or (sum(w.yc for w in n2) / len(n2) - sum(w.yc for w in n1) / len(n1)) > NAME_GAP * h:
                raise NotRead(f"name lines of one block are not adjacent on page {l2.page}: {clean(l2.text)!r}")
        who = " ".join(clean(w.text) for _, nm in named for w in nm)
        seq = [t for _, _, toks in blk for t in toks]
        kinds = [k for k, _ in seq]
        if not seq or kinds != ["label", "amount"] * (len(seq) // 2):
            raise NotRead(f"labels and amounts do not pair for {who!r} on page {blk[0][0].page}")
        pairs = [(seq[i][1], seq[i + 1][1]) for i in range(0, len(seq), 2)]
        at_total = [i for i, (lab, _) in enumerate(pairs) if _norm_label(lab) in totals]
        if at_total == [len(pairs) - 1]:
            total, parts = pairs[-1][1], [amt for _, amt in pairs[:-1]]
        elif not at_total and len(pairs) == 1 and _norm_label(pairs[0][0]) == _norm_label(b.first_label):
            total, parts = pairs[0][1], []
        else:
            raise NotRead(f"no one printed total for {who!r} on page {blk[0][0].page}: "
                          f"{'; '.join(lab for lab, _ in pairs)}")
        token, value = _held_token([w.text for w in total])
        n = len(bidders) + 1
        if value is None:
            held.append((f"bid_tab.bidders[{n - 1}].total_cents", "amount-format"))
        elif parts and not fin_checks.parts_add_up([_held_token([w.text for w in p])[1] for p in parts], value):
            held.append((f"bid_tab.bidders[{n - 1}].total_cents", "total-parts"))
            value = None
        bidders.append(Bidder(n, who, token, value, total[0].page))
    return bidders, held, end


# ------------------------------------------------------------------ entry point
def read_bidtab(words: list[Word], rules: BidTabRules) -> BidTabRead:
    ls = group_lines(words)
    fields: dict = {}
    found = None
    unit_price = None
    for i, ln in enumerate(ls):
        h = _header(ln, rules)
        if h is not None:
            if h[0] is None:
                return BidTabRead("not_read", h[1])
            found = ("table", i, h[0])
            break
        if rules.blocks:
            bh = _block_header(ln, rules.blocks)
            if bh is not None:
                if bh[0] is None:
                    return BidTabRead("not_read", bh[1])
                found = ("blocks", i, bh[0])
                break
        if unit_price is None and _find_any(ln.words, rules.columns["name"]):
            unit_price = clean(ln.text)
        f = _field_of(clean(ln.text), rules)
        if f and f[0] not in fields and f[1]:
            fields[f[0]] = (f[1], ln.page)
    if found is None:
        if unit_price:
            return BidTabRead("not_read", f"no bidder table header with a total column (unit-price layout): "
                                          f"{unit_price!r}")
        return BidTabRead("not_read", NO_HEADER)
    layout, at, header = found
    try:
        read = _read_table if layout == "table" else _read_blocks
        bidders, held, end = read(ls, at, header, rules)
    except NotRead as e:
        return BidTabRead("not_read", str(e))
    for ln in ls[end:]:
        f = _field_of(clean(ln.text), rules)
        if f and f[0] not in fields and f[1]:
            fields[f[0]] = (f[1], ln.page)
    if not bidders:
        return BidTabRead("not_read", "no bidder rows under the header")
    return BidTabRead("lump_sum", None, fields, bidders, held, layout)
