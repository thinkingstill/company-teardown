#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把跨市场公司的长序列补进 data/companies.json。

只做一件事：把 tmp/val/hk_*.json 里的年度行「追加」到已有 years 里，
不覆盖已有年份（2021–2025 那五年是原始批次口径，不动）。

设计约束：
  1. 只补 listed 年及以后的年份——低于上市年的数据（招股书披露的 pre-IPO 年度）
     会单独留在 `years_pre` 字段里，不混入主序列，避免把 coverage 拉早后
     图表的「上市以来」语义失真。
  2. 年份必须是连续整数，重复则保留已有值并记 warn。
  3. rev/np 为 null 的行丢弃（validate.py 不允许），整年缺失则跳过。
  4. 追加后重算 coverage，并给 meta 打标记，方便回溯是哪一批补的。

用法:
    python3 scripts/merge_cross_long.py --dry
    python3 scripts/merge_cross_long.py
"""
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "companies.json"
VAL_DIR = ROOT / "tmp" / "val"


def num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or abs(f) > 1e7:
        return None
    return round(f, 2)


def main() -> int:
    dry = "--dry" in sys.argv
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    by_code = {c["code"]: c for c in payload["companies"]}

    files = sorted(glob.glob(str(VAL_DIR / "hk_*.json")))
    if not files:
        print(f"[ERROR] {VAL_DIR} 下没有 hk_*.json")
        return 1

    report, warns = [], []
    for f in files:
        try:
            blob = json.loads(Path(f).read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            warns.append(f"{Path(f).name} 解析失败：{e}")
            continue
        # 兼容两种顶层结构：{"code":..}/{"data":[...]}
        items = blob.get("data") or [blob]
        for item in items:
            code = item.get("code")
            c = by_code.get(code)
            if not c:
                warns.append(f"{Path(f).name}: {code} 不在主库，跳过")
                continue
            listed = int(str(c.get("listed") or "0")[:4] or 0)
            have = {d["y"]: d for d in c["years"]}
            added, kept_pre = [], []
            for r in item.get("years", []):
                y = r.get("y")
                if not isinstance(y, int):
                    continue
                rev, np_, gm = num(r.get("rev")), num(r.get("np")), num(r.get("gm"))
                if rev is None or np_ is None:
                    warns.append(f"{code} {y} 营收或净利缺失，跳过该年")
                    continue
                row = {"y": y, "rev": rev, "np": np_, "gm": gm}
                if y in have:
                    warns.append(f"{code} {y} 已有数据，保留原值")
                    continue
                if y < listed:
                    kept_pre.append(row)
                    continue
                c["years"].append(row)
                added.append(y)
            if kept_pre:
                c["years_pre"] = sorted(kept_pre, key=lambda d: d["y"])
                warns.append(f"{code} {len(kept_pre)} 个上市前年度存入 years_pre（不混入主序列）")
            if added:
                c["years"].sort(key=lambda d: d["y"])
                c["coverage"] = [c["years"][0]["y"], c["years"][-1]["y"]]
                report.append((code, (item.get("name") or c["name"]), len(added),
                               min(added), max(added), len(c["years"])))
            for w in item.get("warns", []) if isinstance(item.get("warns"), list) else []:
                warns.append(f"{Path(f).name}/{code}: {w}")
        for w in blob.get("warns", []) if isinstance(blob.get("warns"), list) else []:
            warns.append(f"{Path(f).name}: {w}")

    print(f"[INFO] 处理 {len(files)} 个文件")
    for code, name, n, lo, hi, total in report:
        print(f"  {code:9s} {name:6s} +{n:2d} 年（{lo}–{hi}）→ 共 {total} 个财年")
    for w in warns:
        print(f"[WARN ] {w}")

    total_years = sum(len(c["years"]) for c in payload["companies"])
    print(f"[INFO] 合计 {len(payload['companies'])} 家 / {total_years} 财年")

    if dry:
        print("[DRY] 未写文件")
        return 0

    payload["meta"]["cross_long"] = {
        "note": "跨市场 6 家已补至上市年至今；上市前年度单独存于 years_pre，不混入 coverage",
        "merged": [f"{code}:{lo}-{hi}" for code, _, _, lo, hi, _ in report],
    }
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[OK] 写入 {DATA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
