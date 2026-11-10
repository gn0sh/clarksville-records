"""Sample RPC agendas with a text layer (a few, not all): does the RPC print the council's ordinance number, a tax
map/parcel, or only hearing dates? Run from the repo root: python3 -B rpcpdf.py <store dir>/"""
import json, re, subprocess, sys, collections
store = sys.argv[1]
rpc = json.load(open("data/localities/cmc-rpc/rpc.json"))
src = [s for s in rpc["sources"] if s["kind"] == "agenda" and s["text_layer"] == "text" and s["format"] == "pdf"]
src.sort(key=lambda s: s["meeting_date"])
pick = [s for s in src if s["meeting_date"] in ("2022-03-22", "2023-04-25", "2023-09-26", "2024-08-27", "2025-07-29",
                                                "2025-09-23", "2026-03-24", "2026-09-22")]
if len(pick) < 6:
    pick = src[::max(1, len(src) // 8)][:8]
for s in pick:
    t = subprocess.run(["pdftotext", "-layout", f"{store}{s['sha256']}.pdf", "-"], capture_output=True, text=True).stdout
    c = collections.Counter()
    c["ORDINANCE nn-yyyy-yy"] = len(re.findall(r"ORDINANCE\s+\d{1,3}-\d{4}-\d{2}", t, re.I))
    c["word ordinance"] = len(re.findall(r"ordinance", t, re.I))
    c["tax map/plat"] = len(re.findall(r"TAX\s*(MAP|PLAT)", t, re.I))
    c["parcel"] = len(re.findall(r"PARCEL", t, re.I))
    c["council date lines"] = len(re.findall(r"CITY COUNCIL[^\n]{0,60}\d{1,2}/\d{1,2}/\d{4}", t, re.I))
    c["Z- numbers"] = len(set(re.findall(r"\bZ-\d{1,3}-20\d\d", t)))
    print(s["meeting_date"], s["id"], dict(c))
    for m in list(re.finditer(r"[^\n]*(TAX\s*(MAP|PLAT)|CITY COUNCIL|COUNTY COMMISSION)[^\n]*", t, re.I))[:4]:
        print("     |", re.sub(r"\s+", " ", m.group(0))[:170])
