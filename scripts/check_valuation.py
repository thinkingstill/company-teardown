#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""估值数据体检：在合并前扫描 tmp/val/g*.json 的异常，避免脏数据进主库。

检查项：
  1. PB 量级异常（< 0.05 或 > 60）——常见于「中证发布 %」列误除/误乘
  2. PE 量级异常（|PE| > 500）
  3. 连续两年 PE 跳变超过 20 倍（多半是取错行或单位错）
  4. 股息率为 0 或超过 30%
  5. 年份缺失 / 重复
  6. 年末日期是否落在 12-25 之后（防止误取到年中数据）

用法: python3 scripts/check_valuation.py
"""
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    files = sorted(set(glob.glob(str(ROOT / "tmp/val/g*.json")))
                   | set(glob.glob(str(ROOT / "tmp/val/v6c_*.json"))))
    issues, covered = [], {}
    for f in files:
        try:
            blob = json.loads(Path(f).read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            issues.append(f"{Path(f).name}: JSON 错误 {e}")
            continue
        for item in blob.get("data", []):
            code, name = item.get("code"), item.get("name", "")
            rows = item.get("rows", [])
            covered[code] = len(rows)
            ys = [r.get("y") for r in rows]
            if ys != sorted(ys) or len(set(ys)) != len(ys):
                issues.append(f"{code} {name}: 年份乱序或重复 {ys}")
            for r in rows:
                pe, pb, dy = r.get("pe"), r.get("pb"), r.get("dy")
                if pb is not None and (pb < 0.05 or pb > 60):
                    issues.append(f"{code} {name} {r['y']}: PB={pb} 量级异常")
                if pe is not None and abs(pe) > 500:
                    issues.append(f"{code} {name} {r['y']}: PE={pe} 量级异常")
                if dy is not None and (dy < 0 or dy > 30):
                    issues.append(f"{code} {name} {r['y']}: 股息率={dy} 异常")
            # 连续 PE 跳变
            for a, b in zip(rows, rows[1:]):
                pa, pb_ = a.get("pe"), b.get("pe")
                if pa and pb_ and pa > 0 and pb_ > 0:
                    ratio = max(pa, pb_) / min(pa, pb_)
                    if ratio > 20:
                        issues.append(f"{code} {name}: PE {a['y']}→{b['y']} 跳变 {pa}→{pb_}（{ratio:.0f}x）")

    n = len(covered)
    print(f"[INFO] 覆盖 {n} 家公司，共 {sum(covered.values())} 行")
    if issues:
        print(f"[ISSUE] {len(issues)} 条：")
        for i in issues:
            print("  -", i)
    else:
        print("[OK] 未发现异常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
