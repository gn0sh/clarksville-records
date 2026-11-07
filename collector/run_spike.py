"""M0: parse every cached minutes PDF and report Verified rates.

Usage: python3 -m collector.run_spike [--ocr]
Writes data/out/rollcalls.json (gitignored) and prints a summary.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .extract import cached_pages
from .parse import as_dict, canonical_officials, find_rollcalls, item_titles, parse_attendance

ROOT = Path(__file__).resolve().parent.parent


def load_docs():
    man = json.loads((ROOT / "data" / "manifest.json").read_text())
    for e in man:
        yield e, cached_pages(ROOT / "data" / "raw" / e["file"], ROOT / "data" / "text")


def run(use_ocr: bool = False) -> list[dict]:
    allrc = []
    for e, pages in load_docs():
        att = parse_attendance(pages)
        titles = item_titles(pages)
        rcs = find_rollcalls(pages, e["label"], att, titles)
        if use_ocr:
            from .ocr import reverify
            rcs = [reverify(rc, e, att, titles) if rc.status != "Verified" else rc for rc in rcs]
        print(f"{e['label']:<48} att={'ok' if att and att.verified else 'FAIL'} "
              f"rc={len(rcs):3d} verified={sum(r.status == 'Verified' for r in rcs):3d}"
              + ("" if att and att.verified else f"  {att.reasons if att else 'no header'}"))
        for rc in rcs:
            d = as_dict(rc)
            d["sha256"] = e["sha256"]
            d["url"] = e["url"]
            allrc.append(d)
    return allrc


def summary(allrc: list[dict]) -> None:
    n = len(allrc)
    v = sum(r["status"] == "Verified" for r in allrc)
    print(f"\nroll calls {n}, Verified {v} ({100 * v / max(n, 1):.1f}%)")
    causes = Counter()
    for r in allrc:
        if r["status"] != "Verified":
            for reason in r["reasons"]:
                causes[reason.split(":")[0].split("(")[0].split(" for ")[0][:60]] += 1
    print("failure reasons (count of roll calls hit):")
    for c, k in causes.most_common(20):
        print(f"  {k:3d}  {c}")
    canon = canonical_officials([m for r in allrc for m in r["votes"]])
    per = defaultdict(lambda: [0, 0, 0])
    for r in allrc:
        blamed = {canon.get(m, m) for x in r["reasons"] for m in r["votes"] if x.endswith(m)}
        for m in r["votes"]:
            c = canon[m]
            per[c][0] += 1
            per[c][1] += r["status"] != "Verified"
            per[c][2] += c in blamed
    rates = sorted(h / t for t, h, _ in per.values())
    median = rates[len(rates) // 2] if rates else 0
    print(f"held-back rate per official (G4); median {median:.3f}; flag if > 2x median:")
    print(f"  {'official':<24} held/total  rate  named-in-reason")
    for m, (tot, held, blame) in sorted(per.items(), key=lambda x: x[0].split()[-1]):
        flag = "  > 2x median" if median and held / tot > 2 * median else ""
        print(f"  {m:<24} {held:3d}/{tot:3d}   {held / tot:.2f}  {blame:3d}{flag}")


if __name__ == "__main__":
    out = run("--ocr" in sys.argv)
    (ROOT / "data" / "out").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "out" / "rollcalls.json").write_text(json.dumps(out, indent=1))
    summary(out)
