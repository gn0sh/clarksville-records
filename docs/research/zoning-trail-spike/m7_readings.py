"""M7: what the council side of a trail can show per linked item (readings attached to the ordinance item)."""
import json, re, collections
city = json.load(open("data/localities/clarksville-tn/facts.json"))
county = json.load(open("data/facts.json"))
cm = {m["id"]: m for m in city["meetings"]}
keyed = ["107-2022-23", "109-2022-23", "110-2022-23", "111-2022-23", "112-2022-23", "143-2022-23", "144-2022-23",
         "145-2022-23", "147-2022-23", "30-2023-24", "31-2023-24", "32-2023-24", "33-2023-24", "34-2023-24"]
rcs = collections.defaultdict(list)
for r in city["roll_calls"]:
    rcs[r["item_id"]].append(r)
n2 = 0
for o in keyed:
    rs = sorted(rcs["ordinance-" + o], key=lambda r: cm[r["meeting_id"]]["date"])
    desc = [(cm[r["meeting_id"]]["date"], r["outcome"], r["verification"]["status"],
             "second" if re.search(r"second reading", r["outcome_text"], re.I) else
             "first" if re.search(r"first reading", r["outcome_text"], re.I) else "reading not printed") for r in rs]
    n2 += len({d for d, *_ in desc}) > 1
    print(o, desc)
print("keyed items with roll calls at more than one meeting:", n2, "of", len(keyed))
# consent agenda roll calls naming several ordinances
multi = [r for r in city["roll_calls"] if cm[r["meeting_id"]]["date"] >= "2022-02-01" and (r["item_id"] or "").startswith("t-")]
print("roll calls on a heading item (consent agenda etc.) from 2022-02:", len(multi))
st = collections.Counter(r["verification"]["status"] for r in city["roll_calls"] if cm[r["meeting_id"]]["date"] >= "2022-02-01")
print("city roll call verification from 2022-02:", st)
# county: CZ items and their roll calls
cz = [i for i in county["items"] if re.match(r"CZO?-", i.get("number") or "")]
crc = collections.Counter(r["item_id"] for r in county["roll_calls"])
print("county CZ/CZO items:", len(cz), "| with at least one roll call:", sum(crc[i["id"]] > 0 for i in cz),
      "| with a zoning object:", sum("zoning" in i for i in cz))
print(json.dumps(cz[-1])[:600])
ev = collections.Counter(e["type"] for e in county["item_events"] if e["item_id"] in {i["id"] for i in cz})
print("county CZ item events by type:", ev)
