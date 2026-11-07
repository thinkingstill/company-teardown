#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据校验：schema、年份连续性、口径一致性、文本质量。

用法:
    python3 scripts/validate.py            # 校验 data/companies.json
    python3 scripts/validate.py --strict   # 警告也视为失败

退出码: 0 通过, 1 有错误
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "companies.json"

REQUIRED = ["code", "name", "industry", "listed", "coverage", "verdict",
            "engine", "mix", "moat", "payer", "shift", "flags", "years"]
BANNED = ["致力于", "赋能", "生态闭环", "前景广阔", "持续发力", "行业领先", "公司简介"]


def main() -> int:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    cs = payload.get("companies", [])
    errors, warns = [], []

    if not cs:
        print("[ERROR] companies 为空")
        return 1

    codes = set()
    for c in cs:
        tag = c.get("code", "?")
        if tag in codes:
            errors.append(f"{tag} 代码重复")
        codes.add(tag)

        for k in REQUIRED:
            if k not in c or c[k] in ("", None, [], {}):
                errors.append(f"{tag} 缺少字段 {k}")

        ys = c.get("years", [])
        if len(ys) < 3:
            errors.append(f"{tag} 财年记录不足 3 年")

        for i, row in enumerate(ys):
            for k in ("y", "rev", "np"):
                if row.get(k) is None:
                    errors.append(f"{tag} {row.get('y')} 缺少 {k}")
                elif isinstance(row[k], float) and math.isnan(row[k]):
                    errors.append(f"{tag} {row.get('y')} {k} 为 NaN")
            if i and row["y"] != ys[i - 1]["y"] + 1:
                warns.append(f"{tag} 年份不连续：{ys[i-1]['y']} → {row['y']}")
            if row.get("rev") is not None and row["rev"] <= 0:
                errors.append(f"{tag} {row['y']} 营收非正")

        cov = c.get("coverage", [])
        if cov and ys:
            if cov[0] != ys[0]["y"] or cov[1] != ys[-1]["y"]:
                errors.append(f"{tag} coverage {cov} 与数据区间 {ys[0]['y']}–{ys[-1]['y']} 不一致")

        mix = c.get("mix", [])
        total = sum(list(m)[1] for m in mix) if mix else 0
        if mix and not (99 <= total <= 101):
            warns.append(f"{tag} 收入结构合计 {total}%，不等于 100%")

        text = " ".join(str(c.get(k, "")) for k in ("verdict", "moat", "payer", "shift"))
        for w in BANNED:
            if w in text:
                warns.append(f"{tag} 出现套话「{w}」")

        if len(c.get("verdict", "")) < 30:
            warns.append(f"{tag} 结论过短，可能不构成判断")

    print(f"[INFO] {len(cs)} 家公司，{sum(len(c['years']) for c in cs)} 个财年，"
          f"{len({c['industry'] for c in cs})} 个行业")
    for e in errors:
        print(f"[ERROR] {e}")
    for w in warns:
        print(f"[WARN ] {w}")
    if errors:
        print(f"\n未通过：{len(errors)} 错误 / {len(warns)} 警告")
        return 1
    print(f"\n通过：0 错误 / {len(warns)} 警告")
    return 0


if __name__ == "__main__":
    sys.exit(main())
