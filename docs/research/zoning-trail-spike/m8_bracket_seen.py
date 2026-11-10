"""M8: is the absence of a bracket observed (heading kept, no bracket) or unknown (heading not kept)? Plus the
2025-08-07 fixture check against rpc.json."""
import json, re, collections
city = json.load(open("data/localities/clarksville-tn/facts.json"))
rpc = json.load(open("data/localities/cmc-rpc/rpc.json"))
cm = {m["id"]: m for m in city["meetings"]}
rm = {m["id"]: m for m in rpc["meetings"]}
def is_zoning(t):
    return bool(re.search(r"zone change|RPC:\s|Zoning Ordinance and Map|zoning code and map", t, re.I))
seen = {}
for o in city["motions"]:
    d = cm[o["meeting_id"]]["date"]
    iid = o.get("item_id") or ""
    if d < "2022-02-01" or not is_zoning(o["text"]) or not iid.startswith("ordinance-"):
        continue
    t = o["text"]
    head = bool(re.match(r"\s*ORDINANCE\s+\d", t))
    br = bool(re.search(r"\[[^\]]*\d{1,3}-\d{4}\s*\]", t))
    state = "bracket printed" if br else "heading kept, no bracket" if head else "heading not kept (unknown)"
    rank = {"bracket printed": 0, "heading kept, no bracket": 1, "heading not kept (unknown)": 2}
    if iid not in seen or rank[state] < rank[seen[iid][0]]:
        seen[iid] = (state, d)
tab = collections.defaultdict(collections.Counter)
for iid, (s, d) in seen.items():
    tab[d[:4] + ("-H1" if d[5:7] <= "06" else "-H2")][s] += 1
for k in sorted(tab): print(k, dict(tab[k]))
print("total", collections.Counter(s for s, _ in seen.values()))
for num in ("Z-29-2025", "Z-30-2025"):
    cs = [c for c in rpc["cases"] if c["number"] == num]
    print(num, [(rm[c["meeting_id"]]["date"], c["applicant"]) for c in cs],
          [h["printed"] for c in cs for h in rm[c["meeting_id"]].get("hearings", []) if "FIRST READING" in h["printed"].upper()])
it = {i["id"] for i in city["items"]}
print("council items ordinance-05-2025-26 / 06-2025-26 in facts:", "ordinance-05-2025-26" in it, "ordinance-06-2025-26" in it)
# RPC meetings whose agenda prints a council first reading date, and whether we hold a council meeting on that date
dates = {m["date"]: m for m in city["meetings"] if m["kind"] == "regular"}
n = hit = mins = 0
for m in rpc["meetings"]:
    for h in m.get("hearings", []):
        if "FIRST READING" in h["printed"].upper():
            n += 1; hit += h["date"] in dates; mins += h["date"] in dates and dates[h["date"]]["minutes_status"] == "read"
print("RPC agendas printing a council first-reading date:", n, "| we hold a regular council meeting on that date:", hit,
      "| with minutes read:", mins)
