#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 tmp/val/g*.json 的估值序列合并进 data/companies.json。

字段设计（向后兼容旧的 valuation 时点快照）：
  valuation = {
    "asof": "2025-12-31",
    "pe": 19.16, "pb": 6.68, "dy": 3.77,        # 最新年末值（= history 末项）
    "history": [{"y":2021,"pe":..,"pb":..,"dy":..}, ...],
    "pct": {"pe": 0.0, "pb": 0.0, "dy": 100.0},  # 当前值在 5 年窗口内的分位（0–100）
    "pct_years": [2021, 2025],
    "pe_valid_n": 5, "pb_valid_n": 5, "dy_valid_n": 4
  }

分位口径（百分位法，与 Wind/同花顺「历史分位」同义）：
  pct = 窗口中「严格小于当前值」的样本数 / (样本数 - 1) × 100
  —— 即最小值为 0%、最大值为 100%，衡量「现在的估值在历史上处于什么位置」。
  样本不足 3 个有效值时不计算分位（pct = null），避免 2 个点也能算出 0/100% 的假分位。

负 PE 的处理（关键）：
  亏损公司 PE(TTM) 为负，数学上「负 PE 比正 PE 更小」会让分位失真（万科 2025 年 PE=-0.93，
  若直接参与分位会算出「历史最低估值」这种荒谬结论）。因此：
    - pe <= 0 的样本一律剔除出分位计算池，但仍保留在 history 里供展示；
    - 若当前值 pe <= 0，则 pct.pe = null，并标记 pe_state = "loss"（亏损，PE 无意义）；
    - 因为 % 分位按「正 PE 池」算，pe_valid_n 会明显小于年份数，模板据此提示。

用法:
    python3 scripts/merge_valuation.py          # 合并并写回 data/companies.json
    python3 scripts/merge_valuation.py --dry    # 只统计，不写文件
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "companies.json"
VAL_DIR = ROOT / "tmp" / "val"

MIN_SAMPLES = 3   # 计算分位所需最少有效样本
PE_CAP = 300.0    # |PE| 超过此值视为「利润趋近零」，数学有效但无经济意义，作废
PB_CAP = 60.0     # PB 上限，超过多为单位换算错误


def sanitize(pe, pb, dy):
    """把无经济意义的极端值置空，避免污染分位与图表纵轴。

    PE 的极端值来自分母（净利）趋近于零：
      用友 2022 年净利 -20.61 亿但市值大，PE 算到 2008 倍；
      王府井 2025 年微亏，PE = -505。
    这两个数「算得对」但「没意义」，且会把 5 年图的纵轴拉平、把分位算成 0% 或 100%，
    因此统一作废——这类公司只能看 PB 与现金流。
    """
    if pe is not None and abs(pe) > PE_CAP:
        pe = None
    if pb is not None and (pb <= 0 or pb > PB_CAP):
        pb = None
    if dy is not None and (dy < 0 or dy > 30):
        dy = None
    return pe, pb, dy


def pct_rank(values, cur):
    """百分位：严格小于 cur 的占比（min→0, max→100）。"""
    vals = [v for v in values if v is not None]
    if cur is None or len(vals) < MIN_SAMPLES:
        return None
    below = sum(1 for v in vals if v < cur)
    return round(below / (len(vals) - 1) * 100, 1)


def build_history(rows):
    """清洗并排序估值序列。"""
    out = []
    for r in rows:
        y = r.get("y")
        if not isinstance(y, int):
            continue

        def num(k):
            v = r.get(k)
            if v is None:
                return None
            try:
                f = float(v)
            except (TypeError, ValueError):
                return None
            if f != f or abs(f) > 1e6:   # NaN / 明显异常值
                return None
            return round(f, 4)

        pe, pb, dy = sanitize(num("pe"), num("pb"), num("dy"))
        out.append({"y": y, "pe": pe, "pb": pb, "dy": dy, "pe_raw": num("pe")})
    out.sort(key=lambda d: d["y"])
    return out


def compute(hist):
    """算分位与状态。返回 (pct, meta)。"""
    if not hist:
        return None, {}
    last = hist[-1]

    pe_pool = [d["pe"] for d in hist if d["pe"] is not None and d["pe"] > 0]
    pb_pool = [d["pb"] for d in hist if d["pb"] is not None and d["pb"] > 0]
    dy_pool = [d["dy"] for d in hist if d["dy"] is not None]

    pe_state = "loss" if (last["pe"] is not None and last["pe"] <= 0) else "ok"
    # 极端 PE 被清洗成 None 时，若原文是负值，仍要标记为亏损（否则会显示"分位 —"却不解释原因）
    if last["pe"] is None and last.get("pe_raw") is not None and last["pe_raw"] <= 0:
        pe_state = "loss"
    # 当年 PE 因「利润趋近零」被作废，或有效正 PE 样本不足 → 单独标记，模板给出解释
    elif last["pe"] is None:
        pe_state = "void"

    pe_pool = [d["pe"] for d in hist if d["pe"] is not None and d["pe"] > 0]
    if pe_state == "ok" and len(pe_pool) < MIN_SAMPLES:
        pe_state = "thin"
    pct_pe = None if pe_state == "loss" else pct_rank(pe_pool, last["pe"])

    pct = {
        "pe": pct_pe,
        "pb": pct_rank(pb_pool, last["pb"]),
        "dy": pct_rank(dy_pool, last["dy"]),
    }
    meta = {
        "pe_valid_n": len(pe_pool),
        "pb_valid_n": len(pb_pool),
        "dy_valid_n": len(dy_pool),
        "pe_state": pe_state,
    }
    return pct, meta


def main() -> int:
    dry = "--dry" in sys.argv
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    by_code = {c["code"]: c for c in payload["companies"]}

    # v6c 批次文件名形如 v6c_g3.json / v6c_s56.json，需与早期 g*.json 一并纳入
    files = sorted(set(VAL_DIR.glob("g*.json")) | set(VAL_DIR.glob("v6c_*.json")))
    if not files:
        print(f"[ERROR] {VAL_DIR} 下没有 g*.json / v6c_*.json")
        return 1

    merged, warns = {}, []
    for f in files:
        try:
            blob = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            warns.append(f"{f.name} JSON 解析失败：{e}")
            continue
        for item in blob.get("data", []):
            code = item.get("code")
            if code not in by_code:
                warns.append(f"{f.name}: 代码 {code} 不在主数据中，已跳过")
                continue
            hist = build_history(item.get("rows", []))
            if hist:
                merged[code] = hist
        for w in blob.get("warns", []):
            warns.append(f"{f.name}: {w}")

    hit = skipped = 0
    for code, hist in merged.items():
        c = by_code[code]
        pct, meta = compute(hist)
        clean = [{k: d[k] for k in ("y", "pe", "pb", "dy")} for d in hist]
        last = hist[-1]
        c["valuation"] = {
            "asof": f"{last['y']}-12-31",
            "pe": last["pe"],
            "pb": last["pb"],
            "dy": last["dy"],
            "history": clean,
            "pct": pct,
            "pct_years": [hist[0]["y"], hist[-1]["y"]],
            **meta,
        }
        hit += 1
    skipped = len(by_code) - hit

    print(f"[INFO] 合并 {len(files)} 个文件，覆盖 {hit} 家，未覆盖 {skipped} 家")
    for w in warns:
        print(f"[WARN ] {w}")

    if dry:
        print("[DRY] 未写文件")
        return 0

    payload["meta"]["valuation"] = {
        "window": "近 5 个年度末",
        "pct_method": "百分位法（严格小于当前值的样本占比，min=0 / max=100）",
        "pe_rule": "PE<=0 的样本剔除出分位池；当前 PE<=0 时不计算 PE 分位",
    }
    # 未覆盖的公司在页面上是「估值分位」整块消失，不是显示为空——
    # 扩量后如果忘了补取数，读者只会以为这家公司没估值数据。
    # 所以在 meta 里显式记下名单，页面顶部据此提示。
    payload["meta"]["valuation_missing"] = sorted(
        c["code"] for c in payload["companies"] if not c.get("valuation")
    )
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[OK] 写入 {DATA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
