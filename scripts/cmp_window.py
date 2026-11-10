#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量化 v7b 的影响：同一家公司在「近 5 年」与「近 10 年」窗口下的分位差多少。

这是 v7b 的核心验证——如果周期股的 5 年分位与 10 年分位相差很大，
说明旧窗口确实在给出误导性结论；如果几乎一样，那 v7b 就是白做。

用法: python3 tmp/cmp_window.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_SAMPLES = 3


def pct_rank(values, cur):
    vals = [v for v in values if v is not None]
    if cur is None or len(vals) < MIN_SAMPLES:
        return None
    below = sum(1 for v in vals if v < cur)
    return round(below / (len(vals) - 1) * 100, 1)


def calc(hist, key):
    """按给定子序列算末项分位。PE 只用正样本。"""
    if not hist:
        return None
    last = hist[-1].get(key)
    pool = [d[key] for d in hist if d.get(key) is not None]
    if key == "pe":
        pool = [v for v in pool if v > 0]
    return pct_rank(pool, last)


def main():
    d = json.loads((ROOT / "data/companies.json").read_text(encoding="utf-8"))
    rows = []
    for c in d["companies"]:
        v = c.get("valuation")
        if not v:
            continue
        h = v.get("history") or []
        if len(h) < 8:
            continue                      # 窗口本身不够长，不参与对比
        h5 = [x for x in h if x["y"] >= 2021]
        p5 = {k: calc(h5, k) for k in ("pe", "pb", "dy")}
        p10 = {k: calc(h, k) for k in ("pe", "pb", "dy")}
        diffs = {k: (None if p5[k] is None or p10[k] is None else round(p10[k] - p5[k], 1))
                 for k in ("pe", "pb", "dy")}
        rows.append({"name": c["name"], "ind": c["industry"], "n": len(h),
                     "p5": p5, "p10": p10, "d": diffs})

    if not rows:
        print("[ERROR] 没有窗口 >= 8 年的公司，先跑 merge_valuation.py")
        return 1

    print(f"[INFO] 参与对比 {len(rows)} 家（窗口 >= 8 年）\n")

    # 按 PB 分位变化绝对值排序——PB 是周期股最可靠的分位指标
    key = "pb"
    valid = [r for r in rows if r["d"][key] is not None]
    valid.sort(key=lambda r: -abs(r["d"][key]))

    print(f"=== PB 分位变化最大的 25 家（5年 → 10年）===")
    print(f"{'公司':<10}{'行业':<10}{'5年':>8}{'10年':>8}{'变化':>9}")
    for r in valid[:25]:
        print(f"{r['name']:<10}{r['ind']:<10}{r['p5'][key]:>8.0f}{r['p10'][key]:>8.0f}{r['d'][key]:>+9.0f}")

    # 直接可贴进文档的 markdown 表
    md = ["| 公司 | 行业 | 5 年窗口 | 10 年窗口 | 变化 |",
          "|---|---|---|---|---|"]
    for r in valid[:15]:
        md.append(f"| {r['name']} | {r['ind']} | {r['p5'][key]:.0f}% | {r['p10'][key]:.0f}% "
                  f"| {r['d'][key]:+.0f}pt |")
    (ROOT / "tmp" / "window_cmp.md").write_text("\n".join(md), encoding="utf-8")

    # 分档统计
    big = [r for r in valid if abs(r["d"][key]) >= 30]
    mid = [r for r in valid if 15 <= abs(r["d"][key]) < 30]
    small = [r for r in valid if abs(r["d"][key]) < 15]
    print(f"\n=== PB 分位漂移分布（{len(valid)} 家）===")
    print(f"  |变化| >= 30pt：{len(big):3d} 家  ({len(big)/len(valid)*100:.0f}%)  ← 结论会反转")
    print(f"  15–30pt      ：{len(mid):3d} 家  ({len(mid)/len(valid)*100:.0f}%)  ← 档位会跳")
    print(f"  < 15pt       ：{len(small):3d} 家  ({len(small)/len(valid)*100:.0f}%)  ← 基本不变")

    # 定性档位是否变化（低/中/高）
    def band(x):
        if x is None:
            return None
        return "低" if x < 33.3 else ("高" if x > 66.7 else "中")

    flip = [r for r in valid if band(r["p5"][key]) != band(r["p10"][key])]
    print(f"\n  定性档位（低/中/高）发生改变的：{len(flip)} 家 "
          f"({len(flip)/len(valid)*100:.0f}%)")
    print("  其中变化最大的 10 家：")
    for r in sorted(flip, key=lambda r: -abs(r["d"][key]))[:10]:
        print(f"    {r['name']:<10}{band(r['p5'][key])} → {band(r['p10'][key])}"
              f"  ({r['p5'][key]:.0f}% → {r['p10'][key]:.0f}%)")

    # 写出明细供文档引用
    out = ROOT / "tmp" / "window_cmp.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[OK] 明细写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
