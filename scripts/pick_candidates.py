#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v7c-b：从现有 161 家的二级类目分布，算出「每个类目还该补几家」，并校验候选清单。

分层递进策略（2026-11 拍板）：
  1. 37 个单一类目 × 2 家 = 74 家 —— 解决「无横向可比」
  2. 32 个 2 家类目 × 1 家 = 32 家 —— 凑成 3 家可比
  3. 14 个 3 家类目补齐剩余缺口 —— 目标 300 家

本脚本只做两件事：
  A. `--plan`：生成 tmp/v8_plan.json 骨架（每个类目需要补几家 + 现有公司）
  B. `--check`：校验人工填好的候选清单（不重复、不在现有库、市值/ST/北交所口径）
     候选成分股本身靠 ifind 取数，不在这里发起查询。

用法：
    python3 scripts/pick_candidates.py --plan            # 生成计划骨架
    python3 scripts/pick_candidates.py --check tmp/v8_plan.json   # 校验填好的清单
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "companies.json"
PLAN = ROOT / "tmp" / "v8_plan.json"

TARGET = 300

# 寡头/垄断类目豁免：这些类目在 A 股没有足够多市值≥50亿的独立可比标的，
# 硬凑第二家只会引入「蹭概念」的公司，破坏横向可比性。豁免后不计入缺口。
# 判断依据：ifind 按申万行业查全量成分后，市值≥50亿的纯正标的不足 need 家。
MONOPOLY_EXEMPT = {
    "聚氨酯": "A股纯聚氨酯标的仅万华化学（全球MDI龙头），无第二家市值≥50亿的纯正标的",
    "钛白粉": "A股市值≥50亿的纯钛白粉仅龙佰集团、钛能化学两家，行业本身寡头",
    "旅游零售": "中国中免独占免税牌照（市占率90%+），王府井免税占比仅2.3%，无可比对象",
    "粮油加工": "金龙鱼一家独大，其余粮油标的市值均不足50亿或为贸易/乳品跨界",
    "房屋建设": "房建央企（中建/中铁/铁建/电建）已全部在库，剩余标的多为区域性或ST",
    "商业地产开发": "与「商业地产」是同一申万二级被 v7a 拆成两个标签，候选持续冲突，待合并后重开",
}


def load():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    return d["companies"]


def gap_table(cs):
    """返回每个二级类目：现有家数、现有公司、需补家数。"""
    sw2 = defaultdict(list)
    for c in cs:
        sw2[c.get("sw2", "")].append((c["code"], c["name"]))

    table = {}
    for k, v in sw2.items():
        table[k] = {"have": len(v), "companies": v, "need": 0}

    # 分层递进（四层，保证头部类目更厚、不随机）
    singles = sorted(k for k, v in table.items() if v["have"] == 1)
    twos = sorted(k for k, v in table.items() if v["have"] == 2)
    threes = sorted(k for k, v in table.items() if v["have"] == 3)

    # 第一优先：单一类目补 2 家（无横向可比 → 3 家可比）
    for k in singles:
        table[k]["need"] = 2
    filled = len(cs) + len(singles) * 2

    # 第二优先：2 家类目补 1 家（2 → 3 家可比）
    for k in twos:
        if filled >= TARGET:
            break
        table[k]["need"] = 1
        filled += 1

    # 第三优先：单一类目再补 1 家（3 → 4 家，头部类目更厚）
    for k in singles:
        if filled >= TARGET:
            break
        table[k]["need"] += 1
        filled += 1

    # 第四优先：3 家类目补 1 家（3 → 4 家）
    for k in threes:
        if filled >= TARGET:
            break
        table[k]["need"] = 1
        filled += 1

    return table, filled


def do_plan(cs):
    table, filled = gap_table(cs)
    ordered = sorted(table.items(), key=lambda kv: (-kv[1]["need"], kv[0]))
    plan = {
        "target": TARGET,
        "current": len(cs),
        "to_add": max(0, TARGET - len(cs)),
        "filled_after": filled,
        "rules": {
            "market_cap_min": 50,  # 亿元
            "exclude": ["ST", "*ST"],
            "keep_bj": True,
            "order": "总市值降序",
        },
        "categories": [
            {
                "sw2": k,
                "have": v["have"],
                "need": v["need"],
                "existing": [{"code": c[0], "name": c[1]} for c in v["companies"]],
                "candidates": [],   # 人工/子 Agent 填
            }
            for k, v in ordered if v["need"] > 0
        ],
    }
    PLAN.parent.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    need_total = sum(c["need"] for c in plan["categories"])
    print(f"[OK] 生成 {PLAN}")
    print(f"    现有 {plan['current']} 家，需补 {plan['to_add']} 家")
    print(f"    分层后应补 {need_total} 家（单一类目 {sum(1 for c in plan['categories'] if c['have']==1)} 个×2、"
          f"2家类目 {sum(1 for c in plan['categories'] if c['have']==2)} 个×1、"
          f"3家类目 {sum(1 for c in plan['categories'] if c['have']==3)} 个×1）")


def do_assemble():
    """从 tmp/candidates/sw_*.json 读取候选成分股，自动筛选后填入 v8_plan。

    筛选规则（与取数口径一致）：
      - 排除已在现有库中的公司
      - 排除 ST / *ST
      - 市值 >= 50 亿（mcap 为 None 的保留，人工补）
      - 按 mcap 降序，取前 need 家
    """
    cs = load()
    existing_codes = {c["code"] for c in cs}
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    cand_dir = ROOT / "tmp" / "candidates"

    filled = 0
    missing = []
    for cat in plan["categories"]:
        sw2 = cat["sw2"]
        # CXO 文件名是「医疗研发外包」不带 CXO 后缀
        fname = sw2.replace(" CXO", "")
        fp = cand_dir / f"sw_{fname}.json"
        if not fp.exists():
            missing.append(sw2)
            continue
        raw = json.loads(fp.read_text(encoding="utf-8"))
        # 寡头类目豁免：A 股没有足够可比标的，不强制补满
        exempt = MONOPOLY_EXEMPT.get(sw2)
        if exempt:
            cat["exempt"] = exempt
            # 只填已有的、去掉已在库的候选，不强制 need 家数
            valid = []
            for r in raw:
                code, name = r.get("code", ""), r.get("name", "")
                mcap = r.get("mcap")
                if code in existing_codes:
                    continue
                if "ST" in name or "st" in name.lower():
                    continue
                if mcap is not None and mcap < 50:
                    continue
                valid.append(r)
            valid.sort(key=lambda x: (x.get("mcap") is None, -(x.get("mcap") or 0)))
            cat["candidates"] = valid
            filled += len(valid)
            continue

        picks = []
        for r in raw:
            code, name = r.get("code", ""), r.get("name", "")
            mcap = r.get("mcap")
            # 排除已在库、ST、市值不足
            if code in existing_codes:
                continue
            if "ST" in name or "st" in name.lower():
                continue
            if mcap is not None and mcap < 50:
                continue
            picks.append(r)
        # 按市值降序，取前 need 家
        picks.sort(key=lambda x: (x.get("mcap") is None, -(x.get("mcap") or 0)))
        cat["candidates"] = picks[: cat["need"]]
        filled += len(cat["candidates"])

    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] 已装配 {len(plan['categories']) - len(missing)} 个类目，"
          f"填入 {filled} 个候选")
    if missing:
        print(f"[WARN] {len(missing)} 个类目缺成分股文件：{missing}")
    return 0


def do_check(path):
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    cs = load()
    existing_codes = {c["code"] for c in cs}
    issues = []

    total_picked = 0
    for cat in plan["categories"]:
        need = cat["need"]
        picks = cat.get("candidates", [])
        # 寡头类目豁免：不强制补满 need 家
        if cat.get("exempt"):
            continue
        # 每个 pick 结构：{code, name, sw2, sw3, mcap, reason}
        if len(picks) < need:
            issues.append(f"{cat['sw2']}: 需补 {need} 家，只填了 {len(picks)} 家")
        for p in picks:
            total_picked += 1
            code = p.get("code", "")
            name = p.get("name", "")
            # 重复检查
            if code in existing_codes:
                issues.append(f"{cat['sw2']}: {code} {name} 已在现有 161 家中")
            if code in {x["code"] for x in cat["existing"]}:
                issues.append(f"{cat['sw2']}: {code} {name} 与现有公司重复")
            # ST 检查
            if "ST" in name or "st" in name.lower():
                issues.append(f"{cat['sw2']}: {code} {name} 是 ST/退市风险股")
            # 市值检查
            mcap = p.get("mcap")
            if mcap is not None and mcap < 50:
                issues.append(f"{cat['sw2']}: {code} {name} 市值 {mcap} 亿 < 50 亿门槛")
            # 二级类目一致性
            if p.get("sw2") and p["sw2"] != cat["sw2"]:
                issues.append(f"{cat['sw2']}: {code} {name} 的 sw2={p['sw2']} 与类目不符")

    # 全局去重（跨类目）
    all_codes = [p["code"] for cat in plan["categories"] for p in cat.get("candidates", [])]
    dup = [c for c, n in Counter(all_codes).items() if n > 1]
    if dup:
        issues.append(f"跨类目重复代码：{dup}")

    print(f"[CHECK] 共选了 {total_picked} 个候选")
    if issues:
        print(f"[FAIL] {len(issues)} 个问题：")
        for i in issues:
            print("  -", i)
        return 1
    print("[OK] 候选清单通过校验")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="生成计划骨架")
    ap.add_argument("--assemble", action="store_true", help="从 tmp/candidates 装配候选")
    ap.add_argument("--check", metavar="PLAN", help="校验填好的候选清单")
    a = ap.parse_args()

    cs = load()
    if a.check:
        return do_check(a.check)
    if a.assemble:
        return do_assemble()
    do_plan(cs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
