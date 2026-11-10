"""Zoning trail spike measurements M1 to M6 (D0, 2026-11-10). A labelled spike script: read-only, committed data only,
no network, not product code. Run from the repo root:
    python3 -B docs/research/zoning-trail-spike/m1_m6_link_counts.py
"""
import json, re, random, collections, sys
sys.path.insert(0, ".")
from collector.rpc_minutes import link_key

city = json.load(open("data/localities/clarksville-tn/facts.json"))
rpc = json.load(open("data/localities/cmc-rpc/rpc.json"))
county = json.load(open("data/facts.json"))
C = collections.Counter
rmeet = {m["id"]: m for m in rpc["meetings"]}
cmeet = {m["id"]: m for m in city["meetings"]}

# ---- M1 RPC city cases
zc = collections.defaultdict(list)
for c in rpc["cases"]:
    if c["prefix"] in ("Z", "ZO"):
        zc[link_key(c["number"]) or c["number"]].append(c)
zkeys = sorted(k for k in zc if k.startswith("Z-"))
zokeys = sorted(k for k in zc if k.startswith("ZO-"))
print("M1 RPC agenda entries Z:", sum(len(zc[k]) for k in zkeys), "distinct Z numbers:", len(zkeys),
      "| ZO entries:", sum(len(zc[k]) for k in zokeys), "distinct ZO:", len(zokeys))
print("   distinct Z by case year:", sorted(C(k.split("-")[-1] for k in zkeys).items()))
print("   Z numbers that fail link_key:", [k for k in zc if link_key(k) is None][:10])

# ---- M2 printed (ordinance, case) pairs in the committed city record
PAIR = re.compile(r"ORDINANCE\s+(\d{1,3}-\d{4}-\d{2})\s*(?:\([^)]*\)\s*)?\[\s*(?:Zoning\s+Case\s*#?\s*)?([A-Z]{0,3})-?\s*(\d{1,3})-(\d{4})\s*\]\s*(?:\([^)]*\)\s*)?(.{0,160})", re.I | re.S)
pairs = collections.defaultdict(set); where = collections.defaultdict(set); noprefix = set(); tail = {}
for coll, fld in (("motions", "text"), ("item_events", "label")):
    for o in city[coll]:
        for m in PAIR.finditer(o[fld]):
            ordn, pre, n, y, rest = m.groups()
            d = cmeet[o["meeting_id"]]["date"] if "meeting_id" in o else o["date"]
            if not pre:
                noprefix.add((ordn, f"{n}-{y}", d)); continue
            k = link_key(f"{pre.upper()}-{n}-{y}")
            pairs[ordn].add(k); where[(ordn, k)].add((d, o.get("item_id"))); tail[(ordn, k)] = rest
items = {i["id"]: i for i in city["items"]}
print("\nM2 printed pairs (ordinance number, case number) in motions.text / item_events.label:", len(where))
print("   ordinances with >1 case:", [o for o, s in pairs.items() if len(s) > 1])
rev = collections.defaultdict(set)
for o, s in pairs.items():
    for k in s: rev[k].add(o)
print("   cases with >1 ordinance:", {k: sorted(v) for k, v in rev.items() if len(v) > 1})
ok = 0
for (o, k), w in sorted(where.items(), key=lambda x: sorted(x[1])[0]):
    d, iid = sorted(w)[0]
    on_rpc = k in zc
    item_ok = iid == "ordinance-" + o and iid in items
    rd = sorted(rmeet[c["meeting_id"]]["date"] for c in zc.get(k, []))
    app = [c["applicant"] for c in zc.get(k, [])]
    text = re.sub(r"\s+", " ", tail[(o, k)]).lower()
    app_in = any(a and re.sub(r"\s+", " ", a).lower().rstrip(".,") in text for a in app)
    ok += on_rpc and item_ok
    print(f"   {d} ORDINANCE {o} [{k}] item_id_matches={item_ok} on_rpc_agenda={on_rpc} rpc_dates={rd} "
          f"rpc_before_council={bool(rd) and rd[0] < d} applicant_printed_agrees={app_in}")
print("   pairs with the case on an RPC agenda and the item resolved:", ok, "of", len(where))
print("   bracket without a prefix (not a key as printed):", sorted(noprefix))

# ---- M3 sample of 40 distinct Z cases (seed 20261110) and all
linked = {k for (o, k) in where if k in zc}
random.seed(20261110)
sample = random.sample(zkeys, 40)
print("\nM3 sample of 40 distinct Z case numbers (seed 20261110): linked exactly =",
      sum(k in linked for k in sample), "of 40:", [k for k in sample if k in linked])
print("   all distinct Z:", sum(k in linked for k in zkeys), "of", len(zkeys),
      "| ZO:", sum(k in linked for k in zokeys), "of", len(zokeys))
print("   linked by case year:", sorted(C(k.split("-")[-1] for k in linked).items()))

# ---- M4 city side: how many council zoning votes exist in the RPC period, and how many print the heading
def is_zoning(t):
    return bool(re.search(r"zone change|RPC:\s|Zoning Ordinance and Map|zoning code and map", t, re.I))
zi = collections.defaultdict(set)
for o in city["motions"]:
    d = cmeet[o["meeting_id"]]["date"]
    if d >= "2022-02-01" and is_zoning(o["text"]) and (o.get("item_id") or "").startswith("ordinance-"):
        zi[d[:4]].add(o["item_id"])
allz = set().union(*zi.values())
withkey = {"ordinance-" + o for (o, k) in where}
print("\nM4 council ordinances whose kept motion text reads as a zoning case, from 2022-02:", len(allz),
      {y: len(s) for y, s in sorted(zi.items())})
print("   of these, with a printed case number in the kept text:", len(allz & withkey),
      "| keyed items outside this set:", len(withkey - allz))
print("   items with a non-empty title among them:", sum(bool(items[i]["title"]) for i in allz if i in items))
mm = [m for m in city["meetings"] if m["date"] >= "2022-02-01" and m["kind"] == "regular"]
print("   regular sessions from 2022-02:", len(mm), C(m["minutes_status"] for m in mm))

# ---- M5 composite candidate: applicant as printed + council date after the RPC date (shown to be ambiguous)
def norm(s): return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
APP = re.compile(r"application of (.+?),?\s+for\s+(?:a\s+)?zone change", re.I | re.S)
cands = []
for o in city["motions"]:
    d = cmeet[o["meeting_id"]]["date"]
    m = APP.search(o["text"])
    if d >= "2022-02-01" and m and "first reading" in o["text"].lower():
        cands.append((d, o["item_id"], norm(m.group(1))))
byapp = collections.defaultdict(list)
for k in zkeys:
    for c in zc[k]:
        byapp[norm(c["applicant"])].append((rmeet[c["meeting_id"]]["date"], k))
res = C(); wrong = []
truth = {"ordinance-" + o: k for (o, k) in where}
for d, iid, a in cands:
    hits = sorted({k for (rd, k) in byapp.get(a, []) if rd < d})
    near = sorted({k for (rd, k) in byapp.get(a, []) if rd < d and (int(d[:4]) * 12 + int(d[5:7])) - (int(rd[:4]) * 12 + int(rd[5:7])) <= 3})
    res["applicant exact, any earlier RPC date: " + ("none" if not hits else "one" if len(hits) == 1 else "several")] += 1
    res["applicant exact, RPC within 3 months: " + ("none" if not near else "one" if len(near) == 1 else "several")] += 1
    if iid in truth and near and near != [truth[iid]]: wrong.append((iid, truth[iid], near))
print("\nM5 first-reading zoning motions with a printed applicant, from 2022-02:", len(cands))
for k, v in sorted(res.items()): print("   ", k, v)
print("   against the printed key (truth): disagreements", wrong)
multi = {a: sorted({k for _, k in v}) for a, v in byapp.items() if a and len({k for _, k in v}) > 1}
print("   RPC applicants (exact string) with more than one distinct Z case:", len(multi), "applicants,",
      sum(len(v) for v in multi.values()), "of", len(zkeys), "cases; e.g.", list(multi.items())[:3])

# ---- M6 county
CP = ("CZ", "CZO")
ci = collections.defaultdict(list)
for it in county["items"]:
    k = link_key(it.get("number") or "")
    if k and k.split("-")[0] in CP: ci[k].append(it)
rc = collections.defaultdict(list)
for c in rpc["cases"]:
    if c["prefix"] in CP: rc[link_key(c["number"]) or c["number"]].append(c)
print("\nM6 county items with a CZ/CZO number:", sum(len(v) for v in ci.values()), "distinct keys:", len(ci),
      "| keys with >1 county item:", {k: [i["id"] for i in v] for k, v in ci.items() if len(v) > 1})
m = [k for k in ci if k in rc]
print("   county keys with an RPC agenda case:", len(m), "of", len(ci))
print("   unmatched county keys by case year:", sorted(C(k.split("-")[-1] for k in ci if k not in rc).items()))
print("   unmatched 2022+:", sorted(k for k in ci if k not in rc and k.split("-")[-1] >= "2022"))
print("   RPC CZ/CZO entries:", sum(len(v) for v in rc.values()), "distinct:", len(rc),
      "| with a county item:", sum(k in ci for k in rc), "| entries linked:", sum(len(rc[k]) for k in rc if k in ci))
print("   RPC county cases without a county item, by case year:", sorted(C(k.split("-")[-1] for k in rc if k not in ci).items()))
print("   county coverage:", county["coverage"], "| rpc coverage:", rpc["coverage"])
random.seed(20261110)
s2 = random.sample(sorted(rc), 30)
print("   sample of 30 distinct RPC CZ/CZO numbers (seed 20261110): linked", sum(k in ci for k in s2), "of 30; not linked:",
      [k for k in s2 if k not in ci])
# first RPC date of each unlinked RPC county case vs last county meeting
last = max(mt["date"] for mt in county["meetings"])
late = [k for k in rc if k not in ci and min(rmeet[c["meeting_id"]]["date"] for c in rc[k]) >= last[:7]]
print("   last county meeting held:", last, "| unlinked RPC county cases first heard in or after that month:", len(late))
print("   unlinked RPC county cases heard earlier:", sorted((k, min(rmeet[c['meeting_id']]['date'] for c in rc[k])) for k in rc if k not in ci and k not in late))
