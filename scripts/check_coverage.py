#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行业覆盖度检查：每个申万一级行业是否有 5 家、引擎是否分散。

第 3 项（v6c）的目标是「每行业 5 家」，但单纯凑数量没意义——
同行业内如果 5 家的货币化引擎全一样，横比表只是重复同一件事。
本脚本同时检查「数量」与「引擎分散度」。

用法: python3 scripts/check_coverage.py [目标家数，默认 5]
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "companies.json"

# 申万一级 31 个行业（作为完整性口径）
SW = ["农林牧渔", "基础化工", "钢铁", "有色金属", "电子", "家用电器", "食品饮料",
      "纺织服饰", "轻工制造", "医药生物", "公用事业", "交通运输", "房地产",
      "商贸零售", "社会服务", "银行", "非银金融", "综合", "建筑材料", "建筑装饰",
      "电力设备", "机械设备", "国防军工", "汽车", "美容护理", "计算机", "传媒",
      "通信", "煤炭", "石油石化", "环保"]


def eng_code(c):
    """从 engine.main 里抽出 E1–E9 代码集合。"""
    s = (c.get("engine") or {}).get("main") or ""
    codes = set()
    for i in range(1, 10):
        if f"E{i}" in s:
            codes.add(f"E{i}")
    return codes


# 副标签：判断「同一 E 代码下，生意是否其实是两回事」
SUB_TAGS = ["品牌溢价", "品牌", "渠道", "制造", "养殖", "代工", "重资产",
            "资源开采", "资源转换", "特许", "配额", "订阅", "佣金", "项目",
            "履约", "支付", "保险", "资本中介", "云", "广告", "投资", "租金",
            "零售", "批发", "金融", "出口", "合资", "总装", "设计", "服务",
            "开采", "冶炼", "加工", "炼化", "运营", "工程", "设备",
            "客运", "货运", "集运", "装卸", "时效", "快递", "化工", "农药",
            "钛白", "钾肥", "煤化工"]


def eng_variant(c):
    """引擎「变体」＝ E 代码 + main 里命中的全部副标签。

    白酒（品牌溢价）、乳制品（品牌+渠道，快消）、调味品（品牌+渠道，成本加成）
    都被标成「E3 商品自营」，但前者靠提价、后两者靠铺货和成本管控，
    横比里必须分开算，否则会被误判成「5 家一个样」。
    """
    s = (c.get("engine") or {}).get("main") or ""
    tags = frozenset(t for t in SUB_TAGS if t in s)
    return (frozenset(eng_code(c)), tags)


# 确实该被判为「横比重复」的行业：五家公司干的是同一件事，横向对比只能看出规模差异。
# 这是事实，不是缺陷——但必须被显式记下来，否则读者会以为这些横比表有意义。
KNOWN_UNIFORM = {
    "钢铁": "五家都是 E3 制造型（吨钢毛利），差别只在特钢/普钢的产品结构与区位成本",
    "煤炭": "五家都是 E9 资源开采（吨煤利润），差别只在动力煤/焦煤的定价机制（长协 vs 现货）",
    "建筑装饰": "五家都是 E8 项目交付（合同额 × 完工进度），差别只在房建/基建/公装的甲方信用",
}


def main() -> int:
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    d = json.loads(DATA.read_text(encoding="utf-8"))
    cs = d["companies"]
    by_ind = defaultdict(list)
    for c in cs:
        by_ind[c["industry"]].append(c)

    print(f"总计 {len(cs)} 家 / {sum(len(c['years']) for c in cs)} 财年")
    print(f"行业标签 {len(by_ind)} 个（申万一级 {len(SW)} 个）\n")

    short, thin_engine = [], []
    for ind in SW:
        group = by_ind.get(ind, [])
        n = len(group)
        codes = Counter()
        for c in group:
            for e in eng_code(c):
                codes[e] += 1
        distinct = len(codes)
        variants = len({eng_variant(c) for c in group})
        flag = "" if n >= target else f" ← 缺 {target - n}"
        if n < target:
            short.append((ind, n))
        # 白酒三瓶的 engine.main 都写着「E3 商品自营」，但差异化在副标签——
        # 品牌溢价型 / 渠道型 / 制造型 / 养殖型是完全不同的生意。
        # 只数 E 代码会把它们判成同质，所以按「E 代码 + 副标签」去重。
        if n >= target and variants < min(n, 3) and ind not in KNOWN_UNIFORM:
            thin_engine.append((ind, variants))
        print(f"{ind:6s} {n} 家  引擎 {distinct} 种 / 变体 {variants} 种  {dict(codes.most_common(4))}{flag}")

    other = {k: len(v) for k, v in by_ind.items() if k not in SW}
    if other:
        print(f"\n非申万标签：{other}")

    print(f"\n未达 {target} 家的行业：{len(short)}")
    for ind, n in short:
        print(f"  {ind} {n} 家")
    if thin_engine:
        print(f"数量够但引擎变体 <3 的行业（横比会重复）：{[(i, k) for i, k in thin_engine]}")
    return 0 if not short else 1


if __name__ == "__main__":
    sys.exit(main())
