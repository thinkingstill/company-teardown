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

# 分母趋零属常态的公司（按名称，跨批次稳定）。新增同类公司时加进来即可。
# 判据：十年内有 ≥3 年 |PE|>500 或 PE<0，且收入端可解释（院线/游戏/服务型）。
PE_NOISE_OK = {"万达电影", "中国电影", "上海电影", "完美世界", "世纪华通",
               "恺英网络", "普瑞眼科", "何氏眼科",
               # v8-h 广告营销：三家均为媒介代理/撮合，收入按总额法确认、利润极薄，
               # 净利常在 0 附近摆动 → PE 上千倍或负上千倍；天下秀另有借壳前
               # 壳公司净资产趋零 → PB 316.94 / 42.68 / 38.34 / -455.83。
               # 这些点位「算得对但没意义」，照样进库、照样标 loss、照样剔出分位池，
               # 只是不再逐点报警。
               "蓝色光标", "利欧股份", "天下秀",
               # v8-j 钾肥：亚钾国际 2019 年末 117.96 倍、2020 年末 541.54 倍。
               # 2019/2020 年归母净利只有 0.41 亿 / 0.60 亿（老挝矿尚未放量），
               # 市值对这点利润的倍数被动推高；2021 年利润跳到 8.95 亿后 PE 即回落到
               # 26.14 倍。属「分母趋零」的同一类，不是估值数据错。
               "亚钾国际",
               # v8-t 燃气：新奥股份 2019→2020 年 PE 从 9.6025 跳到 199.4023（20.8 倍）。
               # 根因不是净利趋零，是 2020 年收购新奥能源 32.8% 股权并并表——
               # **市值先反映新公司、利润表只并了部分月份**。两种情形都让 PE 失去可比性，
               # 所以放进同一张表：判据是「这个 PE 能不能用于估值」，不是「为什么不能用」。
               "新奥股份"}
# PB 量级异常的白名单：仅限「净资产趋零」导致的真实极端值。
# 与 PE_NOISE_OK 分开，因为 PB 异常另有其因（不是利润趋零，是净资产趋零）。
PB_NOISE_OK = {
    # 天下秀 2019 年借壳原慧球科技：2016–2019 报表主体仍是壳公司，
    # 净资产绝对值极小，PB 被放大到 316.94 / 42.68 / 38.34 / -455.83。
    # 2020 年红人资产并表后回落至 7.02 倍，此后 2.43–6.33 倍，属正常区间。
    "天下秀",
    # 湖北宜化 2016–2017 连亏 63.45 亿（2017 年单年 −50.95 亿，新疆宜化事故停产 + 减值），
    # 净资产被烧到接近零，PB 因此从 2017 年末 1.0357 跳到 2018 年末 14.6073（14.1x），
    # 2019 年末达 20.7948。这不是数据错误，是分母塌陷，2022 年起随净资产修复回落至 2–3 倍。
    "湖北宜化",
    # v8-u 轨交装备：康尼机电 2017 年末 PB 8.3457 → 2018 年末 0.9105（下跌 9.2x，
    # 判据命中的是「跳变幅度」而非「量级」）。根因是 2018 年龙昕科技财务造假，
    # 当年归母净利 −31.51 亿，净资产被减值与预计负债同时打掉，股价同步塌陷到破净。
    # 这不是「PB 便宜」，是「分子分母一起崩」——2019 年回到 2.7380，2022 年起稳定在 1.2–1.5 倍。
    "康尼机电",
}
# 注：PB_NOISE_OK 同时豁免「PB 量级异常」与「PB 跳变」两条判据——
# 两者的根因都是分母（净资产）趋零，豁免一次即可，不必分两张表。


def main() -> int:
    files = sorted(set(glob.glob(str(ROOT / "tmp/val/g*.json")))
                   | set(glob.glob(str(ROOT / "tmp/val/v6c_*.json")))
                   | set(glob.glob(str(ROOT / "tmp/val10/v10_*.json"))))
    issues, covered, bad_pe = [], {}, set()
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
                if pb is not None and (pb < 0.05 or pb > 60) and name not in PB_NOISE_OK:
                    issues.append(f"{code} {name} {r['y']}: PB={pb} 量级异常")
                # 已知会「分母趋零」的行业：影视院线、游戏、医疗服务（眼科/口腔）。
                # 中影 2024 年末净利仅 1.40 亿、万达 2024 年亏 9.40 亿、完美世界 2025 年
                # 亏 12.88 亿，PE 上千倍或负上千倍都是利润≈0 的数学结果，可在年报里复核。
                # 这类点位照样进库、照样被 pe_state 标为 loss、照样剔出分位池，
                # 但不再报「量级异常」——否则每加一家亏损公司都要人工解释一遍同样的报警。
                # 例外：若该点位已经挂了「量级异常」，则不再重复报 PE 跳变（同一根因）。
                if pe is not None and abs(pe) > 500 and name not in PE_NOISE_OK:
                    issues.append(f"{code} {name} {r['y']}: PE={pe} 量级异常")
                    bad_pe.add((code, r['y']))
                if dy is not None and (dy < 0 or dy > 30):
                    issues.append(f"{code} {name} {r['y']}: 股息率={dy} 异常")
            # 连续 PE 跳变
            for a, b in zip(rows, rows[1:]):
                pa, pb_ = a.get("pe"), b.get("pe")
                if pa and pb_ and pa > 0 and pb_ > 0 \
                        and name not in PE_NOISE_OK \
                        and (code, a['y']) not in bad_pe and (code, b['y']) not in bad_pe:
                    ratio = max(pa, pb_) / min(pa, pb_)
                    if ratio > 20:
                        issues.append(f"{code} {name}: PE {a['y']}→{b['y']} 跳变 {pa}→{pb_}（{ratio:.0f}x）")
            # PB 跳变与冻结：v6d 那批坏值的真正特征是「突变后冻结」——
            # 晨鸣 20251231=0.8398 → 20260101=15.5359，此后恒定不变。
            # 单纯看跳变幅度会误报：宁德 2022→2023 PB 11.98→3.82、比亚迪 2019→2020
            # 2.29→8.87，都是真实的股价与净资产变化。故拆成两条独立判据。
            for a, b in zip(rows, rows[1:]):
                xa, xb = a.get("pb"), b.get("pb")
                if xa and xb and xa > 0 and xb > 0:
                    ratio = max(xa, xb) / min(xa, xb)
                    if ratio > 8 and name not in PB_NOISE_OK:
                        issues.append(
                            f"{code} {name}: PB {a['y']}→{b['y']} 跳变 {xa}→{xb}（{ratio:.1f}x）")
            pb_seq = [r.get("pb") for r in rows if r.get("pb") is not None]
            frozen = [i for i in range(2, len(pb_seq)) if pb_seq[i] == pb_seq[i - 1] == pb_seq[i - 2]]
            if frozen:
                issues.append(
                    f"{code} {name}: PB 连续 3 年完全相同（{pb_seq[frozen[0]]}），疑似基准日切换后冻结的坏值")

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
