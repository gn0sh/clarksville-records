# ruff: noqa: E501
"""AC-P2 spot check: pick 20 shown (verified) votes at random with a fixed seed, render each source page to PNG,
and write a sheet a person fills in by eye ("matches PDF? y/n").

    python -m qa.spot_check --facts data/facts.json            # pick, render, write build/qa/spot/sheet.md
    python -m qa.spot_check --facts data/facts.json --download # fetch missing PDFs politely (robots.txt, 10 s apart)
    python -m qa.spot_check --score build/qa/spot/sheet.md     # after filling in: 0 = 20/20, 1 = mismatch, 2 = blanks
    python -m qa.spot_check --self-test                        # no network, no real PDFs

AC-P2: 20 random shown votes across at least 4 commissioners and 4 years; all 20 must match the PDF exactly
(name, vote, motion, page). Any mismatch blocks release. For a fresh 20 after a fix, pass a new --seed.
Pages are rendered whole (the minutes are mostly scans, so a text search cannot locate the region reliably).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qa.common import FIXTURE, ROOT, find_pdf, load_facts, pdf_page_count, vote_label  # noqa: E402

DEFAULT_SEED = 20261107
MIN_OFFICIALS, MIN_YEARS = 4, 4
DPI = 110
CHECK_COLS = ("Name?", "Vote?", "Motion?", "Page?")


# ---------------------------------------------------------------- selection

def candidates(facts: dict) -> list[dict]:
    """Every shown vote: a vote by a resolved official in a Verified roll call from a minutes source."""
    sources = {s["id"]: s for s in facts["sources"]}
    meetings = {m["id"]: m for m in facts["meetings"]}
    items = {i["id"]: i for i in facts["items"]}
    motions = {m["id"]: m for m in facts["motions"]}
    officials = {o["id"]: o for o in facts["officials"]}
    out = []
    for rc in facts["roll_calls"]:
        if rc["verification"]["status"] != "verified":
            continue
        src = sources.get(rc["source_id"])
        if not src or src["kind"] != "minutes":
            continue
        meeting = meetings[rc["meeting_id"]]
        item = items.get(rc["item_id"]) or {}
        motion = motions.get(rc.get("motion_id")) or {}
        for v in rc["votes"]:
            if not v.get("official_id"):
                continue
            out.append({
                "fact_id": f"{rc['id']}/{v['official_id']}",
                "official_id": v["official_id"],
                "official": officials[v["official_id"]]["name"],
                "raw_name": v["raw_name"],
                "date": meeting["date"],
                "year": int(meeting["date"][:4]),
                "item": " ".join(x for x in (item.get("number"), item.get("title")) if x) or "(no item)",
                "motion": motion.get("text") or "(no motion text recorded)",
                "value": vote_label(v),
                "outcome": f"{rc['outcome']}: {rc['outcome_text']}",
                "page": rc["page"],
                "source_id": src["id"],
                "url": src["url"],
                "sha256": src["sha256"],
                "pages": src["pages"],
            })
    out.sort(key=lambda c: c["fact_id"])
    return out


def pick(cands: list[dict], n: int, seed: int, per_official_cap: int = 4, per_source_cap: int = 2) -> list[dict]:
    """Round-robin over years, random within a year, spreading across officials and documents.

    Deterministic for one (facts, seed). Tries successive derived seeds until the AC-P2 spread holds."""
    n = min(n, len(cands))
    best = None
    for attempt in range(200):
        rng = random.Random(f"{seed}/{attempt}")
        pool = cands[:]
        rng.shuffle(pool)
        years = sorted({c["year"] for c in pool})
        rng.shuffle(years)
        by_year = {y: [c for c in pool if c["year"] == y] for y in years}
        chosen: list[dict] = []
        o_n, s_n = Counter(), Counter()
        # strict pass first (caps), then relaxed pass to fill the quota
        for strict in (True, False):
            progress = True
            while len(chosen) < n and progress:
                progress = False
                for y in years:
                    if len(chosen) >= n:
                        break
                    for c in by_year[y]:
                        if c in chosen:
                            continue
                        if strict and (o_n[c["official_id"]] >= per_official_cap or s_n[c["source_id"]] >= per_source_cap):
                            continue
                        chosen.append(c)
                        o_n[c["official_id"]] += 1
                        s_n[c["source_id"]] += 1
                        progress = True
                        break
        score = (len({c["official_id"] for c in chosen}) >= MIN_OFFICIALS and len({c["year"] for c in chosen}) >= MIN_YEARS,
                 len({c["official_id"] for c in chosen}), len({c["year"] for c in chosen}))
        if best is None or score > best[0]:
            best = (score, chosen)
        if score[0]:
            break
    chosen = sorted(best[1], key=lambda c: (c["date"], c["fact_id"]))
    return chosen


def spread(picks: list[dict]) -> dict:
    return {"officials": len({p["official_id"] for p in picks}), "years": len({p["year"] for p in picks}),
            "meetings": len({(p["source_id"]) for p in picks})}


# ---------------------------------------------------------------- PDFs and rendering

def fetch_pdf(src_url: str, sha256: str, cache_dir: Path) -> Path:
    """Polite re-download (robots.txt, >= 10 s between requests, stop on 403/429). Hash must match the facts."""
    from collector.fetch import PoliteFetcher  # reads only; the collector's own rules apply

    global _FETCHER
    if _FETCHER is None:
        _FETCHER = PoliteFetcher()
    status, body, _ = _FETCHER.get(src_url)
    if status != 200:
        raise RuntimeError(f"HTTP {status} for {src_url}")
    got = hashlib.sha256(body).hexdigest()
    if got != sha256:
        raise RuntimeError(f"hash changed for {src_url}: facts say {sha256[:12]}, server gave {got[:12]}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = cache_dir / f"{sha256}.pdf"
    p.write_bytes(body)
    return p


_FETCHER = None


def render_page(pdf: Path, page: int, out_png: Path) -> str | None:
    """Render one page to out_png. Returns None on success or an error string."""
    n = pdf_page_count(pdf)
    if n is not None and not 1 <= page <= n:
        return f"page {page} outside PDF ({n} pages)"
    out_png.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(DPI), "-png", "-singlefile",
                        str(pdf), str(out_png.with_suffix(""))], capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not out_png.is_file():
        return f"pdftoppm failed: {r.stderr.strip()[:200]}"
    return None


def render_all(picks: list[dict], out_dir: Path, download: bool, store_extra=()) -> None:
    for i, p in enumerate(picks, 1):
        png = out_dir / f"pick-{i:02d}_{p['date']}_{p['official_id']}_p{p['page']}.png"
        p["image"] = None
        p["render_note"] = ""
        if p["url"].startswith("https://example.invalid") or ".invalid/" in p["url"]:
            p["render_note"] = "not rendered (example.invalid fixture source)"
            continue
        pdf = find_pdf(p["sha256"], store_extra)
        if pdf is None and download:
            try:
                pdf = fetch_pdf(p["url"], p["sha256"], ROOT / "build" / "qa" / "pdfcache")
            except Exception as exc:  # noqa: BLE001 - report on the sheet, keep going
                p["render_note"] = f"download failed: {exc}"
                continue
        if pdf is None:
            p["render_note"] = "PDF not in store; rerun with --download"
            continue
        err = render_page(pdf, p["page"], png)
        if err:
            p["render_note"] = err
        else:
            p["image"] = png.name


# ---------------------------------------------------------------- sheet

def esc(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).replace("|", "\\|").strip()


def write_sheet(picks: list[dict], out_dir: Path, facts_path, seed: int, facts_sha: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    sp = spread(picks)
    ok = sp["officials"] >= MIN_OFFICIALS and sp["years"] >= MIN_YEARS
    lines = [
        "# AC-P2 spot check sheet",
        "",
        f"- Facts: `{facts_path}` (sha256 {facts_sha[:12]}), seed {seed}, {len(picks)} votes.",
        f"- Spread: {sp['officials']} commissioners, {sp['years']} years, {sp['meetings']} minutes documents. "
        + ("Meets AC-P2 (at least 4 and 4)." if ok else f"**Does NOT meet AC-P2 (needs {MIN_OFFICIALS} commissioners and {MIN_YEARS} years).**"),
        "- How: open each image (or the PDF link, which opens at the page). Find the commissioner's name on that page, then fill in",
        "  `y` or `n` in each of Name, Vote, Motion, Page. Name = the page names this person; Vote = the recorded vote is the one",
        "  in the minutes for this item; Motion = the item/motion text matches; Page = the vote is on this page.",
        "- Any `n` blocks release (AC-P2): add a regression test for the failing pattern, then rerun with a new `--seed`.",
        "- Score: `python -m qa.spot_check --score build/qa/spot/sheet.md`",
        "",
        f"<!-- picks: {len(picks)} -->",
        "",
        "| # | Official | Date | Item | Motion | Recorded vote | Outcome | Page | PDF | Image | " + " | ".join(CHECK_COLS) + " | Notes |",
        "|---|---|---|---|---|---|---|---|---|---|" + "---|" * len(CHECK_COLS) + "---|",
    ]
    for i, p in enumerate(picks, 1):
        img = f"[{p['image']}]({p['image']})" if p.get("image") else esc(p.get("render_note") or "no image")
        pdf = f"[p. {p['page']}]({p['url']}#page={p['page']})"
        lines.append(
            f"| {i} | {esc(p['official'])} (as printed: {esc(p['raw_name'])}) | {p['date']} | {esc(p['item'])} | {esc(p['motion'])} | "
            f"**{esc(p['value'])}** | {esc(p['outcome'])} | {p['page']} | {pdf} | {img} |" + " |" * len(CHECK_COLS) + " |")
    lines += ["", "## Pages", ""]
    for i, p in enumerate(picks, 1):
        if p.get("image"):
            lines += [f"### {i}. {esc(p['official'])}, {p['date']}, p. {p['page']}", "", f"![pick {i}]({p['image']})", ""]
    sheet = out_dir / "sheet.md"
    sheet.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "picks.json").write_text(json.dumps(picks, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return sheet


def score(sheet: Path) -> int:
    text = sheet.read_text(encoding="utf-8")
    m = re.search(r"<!-- picks: (\d+) -->", text)
    expected = int(m.group(1)) if m else 20
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if cells and cells[0].isdigit() and len(cells) >= 10 + len(CHECK_COLS):
            rows.append((cells[0], cells[10:10 + len(CHECK_COLS)]))
    blank = [(n, c) for n, c in rows if any(x.lower() not in ("y", "n") for x in c)]
    bad = [(n, c) for n, c in rows if any(x.lower() == "n" for x in c)]
    print(f"rows {len(rows)} of {expected}; mismatches {len(bad)}; incomplete {len(blank)}")
    for n, c in bad:
        print(f"  MISMATCH pick {n}: " + ", ".join(f"{k}={v}" for k, v in zip(CHECK_COLS, c)))
    if len(rows) != expected:
        print("FAIL: sheet rows do not match the number of picks")
        return 2
    if bad:
        print("FAIL: any mismatch blocks release (AC-P2). Add a regression test, then rerun with a new --seed.")
        return 1
    if blank:
        print("INCOMPLETE: " + ", ".join(n for n, _ in blank))
        return 2
    print(f"PASS: {len(rows)}/{len(rows)} match")
    return 0


# ---------------------------------------------------------------- run / self-test

def run(facts_path, out_dir: Path, seed: int, n: int, download: bool, store_extra=(), require_spread=True) -> tuple[list[dict], bool]:
    facts = load_facts(facts_path)
    cands = candidates(facts)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    picks = pick(cands, n, seed)
    render_all(picks, out_dir, download, store_extra)
    sha = hashlib.sha256(Path(facts_path).read_bytes()).hexdigest()
    sheet = write_sheet(picks, out_dir, facts_path, seed, sha)
    sp = spread(picks)
    ok = len(picks) == n and sp["officials"] >= MIN_OFFICIALS and sp["years"] >= MIN_YEARS
    missing = [p for p in picks if not p.get("image") and "fixture" not in p.get("render_note", "")]
    print(f"{len(cands)} shown votes; picked {len(picks)}: {sp['officials']} commissioners, {sp['years']} years -> {sheet}")
    if missing:
        print(f"WARNING: {len(missing)} picks have no image: " + "; ".join(sorted({m['render_note'] for m in missing})))
    if not ok:
        print(f"WARNING: AC-P2 spread not met (need {n} votes, >= {MIN_OFFICIALS} commissioners, >= {MIN_YEARS} years)")
    return picks, ok and not missing


def _tiny_pdf(pages: int) -> bytes:
    """A valid minimal multi-page PDF (no libraries), for the render self-test."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{' '.join(f'{3 + i} 0 R' for i in range(pages))}] /Count {pages} >>"]
    for i in range(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents {3 + pages + i} 0 R "
                    f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>")
    for i in range(pages):
        s = f"BT /F1 24 Tf 20 100 Td (page {i + 1}) Tj ET"
        objs.append(f"<< /Length {len(s)} >>\nstream\n{s}\nendstream")
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return out


def _synthetic_facts(pdf_sha: str, pdf_pages: int) -> dict:
    """6 officials x 5 years, 30 verified roll calls a year, one source per year pointing at a real tiny PDF."""
    officials = [{"id": f"o{i}", "name": f"Official {i}", "surname": f"S{i}", "given": "G", "title": "Commissioner", "aliases": []}
                 for i in range(6)]
    f = {"officials": officials, "sources": [], "meetings": [], "items": [], "motions": [], "roll_calls": []}
    for y in range(2020, 2025):
        sid = f"src-{y}"
        f["sources"].append({"id": sid, "url": f"https://example.org/{y}.pdf", "sha256": pdf_sha, "kind": "minutes",
                             "meeting_date": f"{y}-03-01", "fetched_at": "2026-11-07", "pages": pdf_pages, "text_layer": "text"})
        for k in range(30):
            mid = f"{y}-03-{k % 9 + 1:02d}-formal"
            if not any(m["id"] == mid for m in f["meetings"]):
                f["meetings"].append({"id": mid, "date": mid[:10], "source_id": sid})
            f["items"].append({"id": f"i{y}{k}", "number": f"{y % 100}-1-{k}", "title": f"Item {k}"})
            f["roll_calls"].append({
                "id": f"rc-{y}-{k}", "meeting_id": mid, "item_id": f"i{y}{k}", "motion_id": None, "outcome": "passed",
                "outcome_text": "Adopted", "page": k % pdf_pages + 1, "source_id": sid,
                "verification": {"status": "verified" if k % 10 else "unverified", "checks": []},
                "votes": [{"official_id": o["id"], "raw_name": o["name"], "value": "yes" if (k + j) % 7 else "other",
                           "raw_value": "Recused"} for j, o in enumerate(officials)]})
    return f


def self_test() -> int:
    failures = []

    def check(cond, msg):
        print(("ok   " if cond else "FAIL ") + msg)
        if not cond:
            failures.append(msg)

    tmp = Path(tempfile.mkdtemp(prefix="spot-selftest-"))
    try:
        # 1. fixture: no PDFs, example.invalid sources are skipped; only Verified votes are picked
        facts = load_facts(FIXTURE)
        cands = candidates(facts)
        unver = {r["id"] for r in facts["roll_calls"] if r["verification"]["status"] != "verified"}
        check(cands and not any(c["fact_id"].split("/")[0] in unver for c in cands), "fixture: only Verified votes are candidates")
        picks, _ = run(FIXTURE, tmp / "fixture", DEFAULT_SEED, 20, False)
        sheet = (tmp / "fixture" / "sheet.md").read_text(encoding="utf-8")
        check(len(picks) == len(cands) and "example.invalid fixture source" in sheet, "fixture: sheet written, rendering skipped")
        check("<!-- picks:" in sheet and all(c in sheet for c in CHECK_COLS), "fixture: sheet has blank check columns")
        check(score(tmp / "fixture" / "sheet.md") == 2, "fixture: blank sheet scores as incomplete (2)")

        # 2. synthetic population: spread, determinism, seed sensitivity, unverified never picked
        pdf = tmp / "t.pdf"
        data = _tiny_pdf(3)
        pdf.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        store = tmp / "store"
        store.mkdir()
        shutil.copy(pdf, store / f"{sha}.pdf")
        fp = tmp / "synthetic.json"
        fp.write_text(json.dumps(_synthetic_facts(sha, 3)), encoding="utf-8")
        a, ok_a = run(fp, tmp / "s1", DEFAULT_SEED, 20, False, store_extra=[store])
        b, _ = run(fp, tmp / "s2", DEFAULT_SEED, 20, False, store_extra=[store])
        c, _ = run(fp, tmp / "s3", DEFAULT_SEED + 1, 20, False, store_extra=[store])
        check(len(a) == 20 and ok_a, "synthetic: 20 picks, all rendered, spread met")
        check(spread(a)["officials"] >= 4 and spread(a)["years"] >= 4, f"synthetic: spread {spread(a)}")
        check([x["fact_id"] for x in a] == [x["fact_id"] for x in b], "synthetic: same seed gives the same 20")
        check([x["fact_id"] for x in a] != [x["fact_id"] for x in c], "synthetic: a new seed gives a fresh 20")
        check(not any(x["fact_id"].startswith(("rc-2020-0/", "rc-2021-10/")) for x in a), "synthetic: held-back roll calls never picked")
        pngs = sorted((tmp / "s1").glob("pick-*.png"))
        check(len(pngs) == 20 and all(p.stat().st_size > 500 for p in pngs), "synthetic: 20 non-empty PNGs rendered")
        check(pngs and pngs[0].read_bytes()[:4] == b"\x89PNG", "synthetic: output is PNG")

        # 3. page outside the PDF is reported, not rendered
        bad = _synthetic_facts(sha, 3)
        bad["roll_calls"][1]["page"] = 99
        bp = tmp / "bad.json"
        bp.write_text(json.dumps(bad), encoding="utf-8")
        picks_bad, _ = run(bp, tmp / "s4", DEFAULT_SEED, 200, False, store_extra=[store])
        check(any("outside PDF" in p["render_note"] for p in picks_bad), "synthetic: page beyond the PDF is flagged")

        # 4. scoring: filled sheet passes, one n fails
        s = (tmp / "s1" / "sheet.md").read_text(encoding="utf-8")
        filled = re.sub(r"^(\| \d+ \|.*\|) \| \| \| \| \|$", r"\1 y | y | y | y |  |", s, flags=re.M)
        (tmp / "s1" / "full.md").write_text(filled, encoding="utf-8")
        check(score(tmp / "s1" / "full.md") == 0, "score: all y passes")
        (tmp / "s1" / "one_n.md").write_text(filled.replace("| y | y | y | y |", "| y | n | y | y |", 1), encoding="utf-8")
        check(score(tmp / "s1" / "one_n.md") == 1, "score: one n blocks (1)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("SELF-TEST " + ("FAILED: " + "; ".join(failures) if failures else "PASSED"))
    return 1 if failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m qa.spot_check", description=__doc__.split("\n\n")[0])
    ap.add_argument("--facts", default=str(ROOT / "data" / "facts.json"))
    ap.add_argument("--out", default=str(ROOT / "build" / "qa" / "spot"))
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--store", action="append", default=[], help="extra directory holding <sha256>.pdf (repeatable)")
    ap.add_argument("--download", action="store_true", help="fetch PDFs missing from the store (polite: robots.txt, 10 s apart)")
    ap.add_argument("--score", metavar="SHEET", help="score a filled-in sheet instead of picking")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.score:
        return score(Path(a.score))
    _, ok = run(a.facts, Path(a.out), a.seed, a.n, a.download, a.store)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
