# -*- coding: utf-8 -*-
"""把 tmp/batch*.json 的财务序列 + narr_*.py 的叙事合成条目，写入 data/companies.json"""
import json, io, importlib, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

P = os.path.join(ROOT, "data", "companies.json")
d = json.load(open(P, encoding="utf-8"))

BATCHES = ["batch1.json", "batch2.json", "batch2b.json", "batch2c.json"]
NARR_MODULES = ["narr_a", "narr_b", "narr_c"]

narr = {}
for m in NARR_MODULES:
    mod = importlib.import_module(m)
    for k, v in mod.__dict__.items():
        if k.startswith("NARR_"):
            narr.update(v)

raw = {}
for b in BATCHES:
    p = os.path.join(ROOT, "tmp", b)
    if not os.path.exists(p):
        continue
    for c in json.load(open(p, encoding="utf-8"))["companies"]:
        raw[c["code"]] = c

added, skipped = [], []
for code, c in raw.items():
    if code not in narr:
        skipped.append(code)
        continue
    n = narr[code]
    # 剔除任何字段为 null 的年份（如长城 2003/2004），保证序列连续可读
    years = [y for y in c["years"] if y["rev"] is not None and y["np"] is not None]
    if not years:
        skipped.append(code)
        continue
    entry = {
        "code": code,
        "name": c["name"],
        "industry": n["industry"],
        "sub": n["sub"],
        "listed": str(c["listed_year"]),
        "coverage": [years[0]["y"], years[-1]["y"]],
        "verdict": n["verdict"],
        "engine": n["engine"],
        "mix": n["mix"],
        "moat": n["moat"],
        "payer": n["payer"],
        "shift": n["shift"],
        "flags": n["flags"],
        "years": [{"y": y["y"], "rev": round(y["rev"], 2), "np": round(y["np"], 2),
                   "gm": None if y["gm"] is None else round(y["gm"], 2)} for y in years],
        "note": n["note"],
    }
    d["companies"] = [x for x in d["companies"] if x["code"] != code]
    d["companies"].append(entry)
    added.append(code)

d["companies"].sort(key=lambda c: (c["coverage"][0], c["code"]))
d["meta"]["batch"] = "v2 · %d 家 · 2026-11" % len(d["companies"])

with io.open(P, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
    f.write("\n")

print("新增:", len(added), added)
print("跳过(无叙事):", len(skipped), skipped)
print("合计:", len(d["companies"]), "家 /", sum(len(c["years"]) for c in d["companies"]), "财年 /",
      len({c["industry"] for c in d["companies"]}), "行业")
