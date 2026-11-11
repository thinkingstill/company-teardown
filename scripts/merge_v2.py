# -*- coding: utf-8 -*-
"""把 tmp/batch*.json 的财务序列 + narr_*.py 的叙事合成条目，写入 data/companies.json"""
import json, io, importlib, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

P = os.path.join(ROOT, "data", "companies.json")
d = json.load(open(P, encoding="utf-8"))

BATCHES = ["batch1.json", "batch2.json", "batch2b.json", "batch2c.json",
           "batch_new1.json", "batch_new2.json", "batch_new3.json",
           "batch_new4.json", "batch_new5.json", "batch_new6.json",
           "batch_new7.json", "batch_new8.json",
           "batch_v6_1.json", "batch_v6_2.json", "batch_v6_3.json", "batch_v6_4.json",
           "batch_v6_5.json", "batch_v6_6.json", "batch_v6_7.json",
           "batch_v8_中药.json", "batch_v8_医疗器械.json"]
NARR_MODULES = ["narr_a", "narr_b", "narr_c", "narr_d", "narr_e", "narr_f", "narr_g", "narr_h",
                "narr_i", "narr_j", "narr_v8"]

BANK_METRICS = ["净息差", "不良率", "成本收入比", "拨备覆盖率", "加权ROE"]
INS_METRICS = ["新业务价值", "内含价值", "NBV率"]

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
    # 银行/保险的专用指标随条目一起带入（模板据此切换表格列）。
    # 模板只认 type=="bank" / 其它，非银组回传的 "ins" 必须归一为 "insurance"，
    # metrics 也按 type 补齐——否则会被当成保险渲染出满屏 undefined。
    if c.get("financial"):
        fin = dict(c["financial"])
        if fin.get("type") == "ins":
            fin["type"] = "insurance"
        fin.setdefault("metrics", BANK_METRICS if fin.get("type") == "bank" else INS_METRICS)
        entry["financial"] = fin
    # 保留已算好的估值（merge_valuation.py 的产物）。否则每次扩量重跑本脚本，
    # 已有公司的估值分位都会被抹掉，得重跑一遍估值合并才能恢复。
    _old = next((x for x in d["companies"] if x["code"] == code), None)
    if _old and _old.get("valuation"):
        entry["valuation"] = _old["valuation"]
    # 保留 v7a 打的申万二级标签（sw1/sw2/sw2_code）。merge 重建条目时若不继承，
    # 会把 tag_sw2.py 的产物抹掉，validate 会报「缺少 sw2」。
    if _old and _old.get("sw2"):
        entry["sw1"] = _old.get("sw1", n["industry"])
        entry["sw2"] = _old["sw2"]
        entry["sw2_code"] = _old["sw2_code"]

    d["companies"] = [x for x in d["companies"] if x["code"] != code]
    d["companies"].append(entry)
    added.append(code)

d["companies"].sort(key=lambda c: (c["coverage"][0], c["code"]))
d["meta"]["batch"] = "v2 · %d 家 · 2026-11" % len(d["companies"])

with io.open(P, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
    f.write("\n")

# 叙事骨架（tmp/mk_narr_skeleton.py 生成）会留下空字符串占位。
# 这类条目不拦下来，页面会出现「引擎描述空白、flags 空数组」的半成品，
# 而且 validate.py 只查数据不查叙事，很容易漏过去。
blank = [c["code"] + c["name"] for c in d["companies"]
         if not c.get("verdict") or not c.get("engine", {}).get("desc")]
if blank:
    print("[FAIL] %d 家叙事未完成：%s" % (len(blank), " ".join(blank)))
    sys.exit(1)

print("新增:", len(added), added)
print("跳过(无叙事):", len(skipped), skipped)
print("合计:", len(d["companies"]), "家 /", sum(len(c["years"]) for c in d["companies"]), "财年 /",
      len({c["industry"] for c in d["companies"]}), "行业")
