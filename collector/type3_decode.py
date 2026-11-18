"""Give the Type 3 fonts of a PDF's pages a text layer from a committed glyph table (a copy; the source is untouched).

Some books print their pages in Type 3 fonts whose glyphs are drawings with meaningless names ("/0", "/12") and no
Unicode map, so pdftotext reads a cipher (the City of Clarksville FY2025 budget book, pp. 43-133). Each glyph is a
drawing (its CharProc content stream). The same drawing prints the same character wherever it appears, so a table
keyed by the drawing's sha256 gives each glyph its character and its advance (in em). The table is made once per book
by hand, from the drawings themselves, and committed (config/localities/<id>/<book>-glyphs.json; how it was made and
checked: docs/research/city-budget-fy2025-glyphs-2026-11-18.md). Nothing here guesses a character.

decode() writes a copy of the PDF in which every Type 3 font used on pages first..last gets:
- `/ToUnicode`: each code's character from the table, so pdftotext reads the words;
- `/Widths`: each code's advance from the table (the source gives every glyph 1 em and places glyphs one by one, so
  without this a word's right edge, which the budget reader aligns columns on, would sit too far right);
- one extra code named `m`, an empty drawing 0.6 em wide that no page draws: poppler sizes a Type 3 font's words from
  its `m` glyph's width / 0.6, so this makes the size the one the page sets (a 6 pt row is 6 pt high).
Fail closed: a glyph on those pages that is not in the table, or a Type 3 font that is not built from /Differences and
/CharProcs, stops the whole copy (exit 3, the reason on stderr); the caller reads nothing from the book.

Run as a separate process under a timeout (pipeline/parser-dos-untimed): fin_facts runs
`python -I collector/type3_decode.py <pdf> <first> <last> <table.json> <out.pdf>`. Standard library and pypdf only, so
it runs isolated (-I: no current directory or script directory on the import path).
"""
from __future__ import annotations

import hashlib
import json
import sys

UNKNOWN = 3       # exit code: a glyph not in the table, or a font this decoder does not read
M_WIDTH = 0.6     # poppler's TextOutputDev divides the Type 3 'm' width by 0.6 to size the font's words


class DecodeError(Exception):
    pass


def glyph_sha(stream) -> str:
    return hashlib.sha256(stream.get_object().get_data()).hexdigest()


def font_codes(font) -> dict:
    """{code: glyph name} from a Type 3 font's /Encoding /Differences."""
    enc = font.get("/Encoding")
    enc = enc.get_object() if enc is not None else None
    if enc is None or not hasattr(enc, "get") or "/Differences" not in enc or "/CharProcs" not in font:
        raise DecodeError("a Type 3 font without /Encoding /Differences and /CharProcs")
    out, code = {}, None
    for d in enc["/Differences"]:
        if isinstance(d, int):
            code = int(d)
        elif code is None:
            raise DecodeError("a Type 3 font whose /Differences starts with a name")
        else:
            out[code] = str(d)
            code += 1
    return out


def cmap(pairs: list) -> bytes:
    """A ToUnicode CMap for one-byte codes: [(code, char), ...]."""
    body = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
            "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
            "1 begincodespacerange", "<00> <FF>", "endcodespacerange"]
    for i in range(0, len(pairs), 100):          # at most 100 entries per block (PDF reference 5.9.2)
        chunk = pairs[i:i + 100]
        body.append(f"{len(chunk)} beginbfchar")
        body += [f"<{c:02X}> <{''.join(f'{u:04X}' for u in _utf16(ch))}>" for c, ch in chunk]
        body.append("endbfchar")
    body += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return "\n".join(body).encode("ascii")


def _utf16(ch: str) -> list:
    b = ch.encode("utf-16-be")
    return [int.from_bytes(b[i:i + 2], "big") for i in range(0, len(b), 2)]


def decode(pdf: str, first: int, last: int, table: dict, out: str) -> dict:
    """Write the decoded copy; -> {fonts, glyphs, pages}. Raises DecodeError (nothing written)."""
    from pypdf import PdfWriter
    from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject,
                               NumberObject)
    w = PdfWriter(clone_from=pdf)
    if not 1 <= first <= last <= len(w.pages):
        raise DecodeError(f"pages {first}-{last} outside the file's {len(w.pages)} pages")
    done, used = set(), set()
    for pn in range(first, last + 1):
        res = w.pages[pn - 1].get("/Resources")
        fonts = res.get_object().get("/Font") if res is not None else None
        for name, ref in (fonts.get_object().items() if fonts is not None else ()):
            font = ref.get_object()
            if font.get("/Subtype") != "/Type3":
                continue                       # a font with its own text layer: left as it is
            key = getattr(ref, "idnum", None) or id(font)
            if key in done:
                continue
            done.add(key)
            codes = font_codes(font)
            procs = font["/CharProcs"].get_object()
            pairs, widths = [], {}
            for code, gname in sorted(codes.items()):
                if gname not in procs:
                    raise DecodeError(f"page {pn} font {name}: code {code} names a glyph it does not draw")
                sha = glyph_sha(procs[gname])
                g = table.get(sha)
                if g is None:
                    raise DecodeError(f"page {pn} font {name}: glyph {sha[:12]} (code {code}) is not in the table")
                used.add(sha)
                pairs.append((code, g["char"]))
                widths[code] = g["advance"]
            free = next(c for c in range(256) if c not in codes) if len(codes) < 256 else None
            if free is None:
                raise DecodeError(f"page {pn} font {name}: no free code for the sizing glyph")
            empty = DecodedStreamObject()
            empty.set_data(f"{M_WIDTH:g} 0 d0".encode("ascii"))
            new_procs = DictionaryObject({NameObject(f"/g{c}"): procs.raw_get(codes[c]) for c in codes})
            new_procs[NameObject("/m")] = w._add_object(empty)
            widths[free] = M_WIDTH
            diffs = ArrayObject()
            for c in sorted(widths):
                diffs += [NumberObject(c), NameObject("/m" if c == free else f"/g{c}")]
            lo, hi = min(widths), max(widths)
            font[NameObject("/CharProcs")] = new_procs
            font[NameObject("/Encoding")] = DictionaryObject({NameObject("/Type"): NameObject("/Encoding"),
                                                              NameObject("/Differences"): diffs})
            font[NameObject("/FirstChar")] = NumberObject(lo)
            font[NameObject("/LastChar")] = NumberObject(hi)
            font[NameObject("/Widths")] = ArrayObject(FloatObject(widths.get(c, 0)) for c in range(lo, hi + 1))
            tu = DecodedStreamObject()
            tu.set_data(cmap(pairs))
            font[NameObject("/ToUnicode")] = w._add_object(tu)
    if not done:
        raise DecodeError(f"pages {first}-{last} use no Type 3 font")
    with open(out, "wb") as fh:
        w.write(fh)
    return {"fonts": len(done), "glyphs": len(used), "pages": last - first + 1}


def load_table(path: str) -> dict:
    """{sha256: {char, advance}} from the committed table (fin_config checks its form when the config loads)."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["glyphs"]


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 5:
        print("usage: type3_decode.py <pdf> <first> <last> <table.json> <out.pdf>", file=sys.stderr)
        return 2
    pdf, first, last, table, out = argv
    try:
        stats = decode(pdf, int(first), int(last), load_table(table), out)
    except DecodeError as e:
        print(f"type3_decode: {e}", file=sys.stderr)
        return UNKNOWN
    print(json.dumps(stats, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
