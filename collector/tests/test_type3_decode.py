"""collector/type3_decode.py and fin_facts.glyph_words: a text layer for Type 3 fonts with no Unicode map, from a glyph
table keyed by each glyph drawing's sha256 (the City of Clarksville FY2025 budget book; finance-contracts 10).

The PDFs here are built in the test: one Type 3 font whose glyphs are rectangles named "/0", "/1", ... with width 1,
placed one by one with TD, the way the FY2025 book draws its pages."""
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from collector import fin_facts, type3_decode
from collector.pdfwords import pdf_words

D1 = b"1 0 -10 -10 10 10 d1\n"
DRAWINGS = {"1": b"0.2 0 0.15 0.7 re f", ".": b"0.25 0 0.1 0.1 re f", "A": b"0 0 0.5 0.7 re f",
            "-": b"0.1 0.3 0.4 0.05 re f", " ": b"", "Z": b"0 0 0.6 0.1 re f"}
CHARS = list(DRAWINGS)                         # code i draws CHARS[i]


def sha(ch: str) -> str:
    return hashlib.sha256(D1 + DRAWINGS[ch]).hexdigest()


def table(path: Path, chars=("1", ".", "A", "-", " ", "Z")) -> Path:
    path.write_text(json.dumps({"glyphs": {sha(c): {"char": c, "advance": 0.6} for c in chars}}))
    return path


def build_pdf(path: Path, text: str, type3: bool = True, fontmatrix: bytes = b"1 0 0 1 0 0") -> Path:
    """One page: `text` at 10 pt from (72, 700), one glyph per Tj and a 0.6 em TD after it."""
    objs = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)
    if type3:
        procs = {c: add(b"<< /Length %d >>\nstream\n" % len(D1 + DRAWINGS[c]) + D1 + DRAWINGS[c] + b"\nendstream")
                 for c in CHARS}
        cp = b" ".join(b"/%d %d 0 R" % (i, procs[c]) for i, c in enumerate(CHARS))
        font = add(b"<< /Type /Font /Subtype /Type3 /FontBBox [-10 -10 10 10] /FontMatrix [" + fontmatrix + b"] "
                   b"/CharProcs << " + cp + b" >> /Encoding << /Type /Encoding /Differences [0 " +
                   b" ".join(b"/%d" % i for i in range(len(CHARS))) + b"] >> /FirstChar 0 /LastChar %d "
                   b"/Widths [%s] /Resources << /ProcSet [/PDF] >> >>" % (len(CHARS) - 1,
                                                                          b" ".join(b"1" for _ in CHARS)))
        body = b"BT /T1 1 Tf 10 0 0 10 72 700 Tm\n" + b"".join(
            b"<%02x> Tj .6 0 TD\n" % CHARS.index(c) for c in text) + b"ET"
    else:
        font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        body = b"BT /T1 10 Tf 72 700 Td (" + text.encode() + b") Tj ET"
    cs = add(b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream")
    page = add(b"PAGE")
    pages = add(b"<< /Type /Pages /Kids [%d 0 R] /Count 1 >>" % page)
    objs[page - 1] = (b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
                      b"/Resources << /Font << /T1 %d 0 R >> >> >>" % (pages, cs, font))
    cat = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages)
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for n, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % n + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, cat, xref)
    path.write_bytes(bytes(out))
    return path


def run_decoder(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(fin_facts.DECODER), *map(str, args)], capture_output=True,
                          timeout=60)


def test_without_the_table_the_text_layer_is_a_cipher(tmp_path):
    pdf = build_pdf(tmp_path / "b.pdf", "-11.1 A")
    assert "-11.1" not in " ".join(w.text for w in pdf_words(pdf))


def test_decoded_copy_reads_the_printed_text_at_the_printed_place(tmp_path):
    pdf = build_pdf(tmp_path / "b.pdf", "-11.1 A")
    out = tmp_path / "d.pdf"
    r = run_decoder(pdf, 1, 1, table(tmp_path / "t.json"), out)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"fonts": 1, "glyphs": 6, "pages": 1}
    words = pdf_words(out)
    assert [w.text for w in words] == ["-11.1", "A"]
    num, a = words
    # right edge = last glyph's place + its advance (0.6 em at 10 pt), as the budget reader aligns columns on it
    assert num.x0 == pytest.approx(72, abs=0.01) and num.x1 == pytest.approx(72 + 5 * 6, abs=0.01)
    assert a.x0 == pytest.approx(72 + 6 * 6, abs=0.01) and a.x1 == pytest.approx(72 + 7 * 6, abs=0.01)
    assert num.y1 - num.y0 < 2 * 10                         # sized as the page sets it (10 pt), not doubled
    assert pdf.read_bytes() == build_pdf(tmp_path / "again.pdf", "-11.1 A").read_bytes()    # source untouched


def test_a_glyph_not_in_the_table_reads_nothing(tmp_path):
    pdf = build_pdf(tmp_path / "b.pdf", "11")             # "Z" is never drawn, but its font defines it
    out = tmp_path / "d.pdf"
    r = run_decoder(pdf, 1, 1, table(tmp_path / "t.json", chars=("1", ".", "A", "-", " ")), out)
    assert r.returncode == type3_decode.UNKNOWN and not out.exists()
    assert f"glyph {sha('Z')[:12]} (code 5) is not in the table" in r.stderr.decode()


def test_a_font_scale_other_than_1_to_1_is_refused(tmp_path):
    # the table's advances are in the text space units of a 1:1 font; a 0.001 font (the usual Type 3 scale) is refused
    pdf = build_pdf(tmp_path / "b.pdf", "1A", fontmatrix=b"0.001 0 0 0.001 0 0")
    r = run_decoder(pdf, 1, 1, table(tmp_path / "t.json"), tmp_path / "out.pdf")
    assert r.returncode == type3_decode.UNKNOWN and not (tmp_path / "out.pdf").exists()
    assert b"FontMatrix [0.001, 0.0, 0.0, 0.001, 0.0, 0.0] is not [1 0 0 1 0 0]" in r.stderr


def test_pages_with_no_type3_font_are_refused(tmp_path):
    pdf = build_pdf(tmp_path / "b.pdf", "11.1", type3=False)
    with pytest.raises(type3_decode.DecodeError, match="use no Type 3 font"):
        type3_decode.decode(str(pdf), 1, 1, {}, str(tmp_path / "d.pdf"))
    with pytest.raises(type3_decode.DecodeError, match="outside the file"):
        type3_decode.decode(str(pdf), 1, 2, {}, str(tmp_path / "d.pdf"))


def test_cmap_blocks_hold_at_most_100_entries():
    text = type3_decode.cmap([(i, "A") for i in range(150)]).decode()
    assert "100 beginbfchar" in text and "50 beginbfchar" in text and "<00> <0041>" in text


def _spec(tmp_path, chars=("1", ".", "A", "-", " ", "Z")):
    return types.SimpleNamespace(id="fy-test", first_page=1, last_page=1,
                                 glyph_map=str(table(tmp_path / "t.json", chars)))


def test_glyph_words_reads_the_decoded_copy(tmp_path):
    pdf = build_pdf(tmp_path / "b.pdf", "-11.1 A")
    problems = []
    words = fin_facts.glyph_words(pdf, _spec(tmp_path), pdf_words, problems)
    assert [w.text for w in words] == ["-11.1", "A"] and problems == []


def test_glyph_words_fails_closed_with_a_guard_problem(tmp_path):
    pdf = build_pdf(tmp_path / "b.pdf", "11")
    problems = []
    assert fin_facts.glyph_words(pdf, _spec(tmp_path, ("1",)), pdf_words, problems) is None
    assert len(problems) == 1 and problems[0].startswith("book fy-test: type3_decode: page 1 font /T1: glyph ")
    assert problems[0].endswith(f"not read ({fin_facts.GLYPH_KEY})")


def test_a_decoder_timeout_is_a_reported_limit_and_reads_nothing(tmp_path, monkeypatch):
    from collector import limits
    pdf = build_pdf(tmp_path / "b.pdf", "11")
    monkeypatch.setattr(fin_facts, "DECODE_TIMEOUT", 0.001)
    since = limits.mark()
    problems = []
    assert fin_facts.glyph_words(pdf, _spec(tmp_path), pdf_words, problems) is None
    assert "glyph decode failed" in problems[0] and problems[0].endswith("(glyph-decode)")
    assert limits.tripped(since) == ["limit fin_facts.DECODE_TIMEOUT: b.pdf 0.001s+ > 0.001s"]


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_AS is set on Linux only")
def test_the_decoder_runs_under_an_address_space_cap_and_reads_nothing_past_it(tmp_path, monkeypatch):
    # pipeline/parser-dos-unbounded-memory: a decoder that needs more than DECODE_MAX_AS fails, the book is not read
    pdf = build_pdf(tmp_path / "b.pdf", "11")
    assert fin_facts.glyph_words(pdf, _spec(tmp_path), pdf_words, []) is not None   # fits under the real cap
    monkeypatch.setattr(fin_facts, "DECODE_MAX_AS", 32 * 1024 ** 2)                 # too small to load pypdf
    problems = []
    assert fin_facts.glyph_words(pdf, _spec(tmp_path), pdf_words, problems) is None
    assert len(problems) == 1 and problems[0].endswith(f"not read ({fin_facts.GLYPH_KEY})")
    assert len(problems[0]) < 400                                                   # the stderr tail, one line


def test_only_the_tail_of_the_decoder_stderr_is_read(tmp_path, monkeypatch):
    noisy = tmp_path / "noisy.py"
    noisy.write_text("import sys\nsys.stderr.write('x' * 1_000_000 + '\\nlast line\\n')\nsys.exit(3)\n")
    monkeypatch.setattr(fin_facts, "DECODER", noisy)
    problems = []
    assert fin_facts.glyph_words(build_pdf(tmp_path / "b.pdf", "11"), _spec(tmp_path), pdf_words, problems) is None
    assert problems == [f"book fy-test: last line, not read ({fin_facts.GLYPH_KEY})"]
