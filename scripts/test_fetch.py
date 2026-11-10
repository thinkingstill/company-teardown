#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_fin.py / factsheet.py 的回归用例。

为什么要有这一组用例
--------------------
v7b 的 PB 口径坑（中证发布 vs MRQ）暴露过一个模式：解析器不报错，但数字是错的。
财务序列更危险——营收与净利对不上、单位差 1e8、季度值混进年度值，这几种错
`validate.py` 一种都发现不了（它只查「有没有值、年份连不连续」）。

所以这里不测「函数返回值」，测的是**已知会出错的真实形态**：
    - 列序每次变（同一份数据两次返回列序不同）
    - 归属净利润 / 归母净利润 / 归属于母公司所有者的净利润 三种写法
    - 元 / 万元 / 亿元 / 万亿元 四种单位混在同一批
    - 三季报与中报混进年度表
    - 「营业总收入」与「营业收入」分别来自两个块
    - 毛利率为「--」（银行无口径）
    - 表头没写单位
    - 周期公司的相邻年倍数（不能被叙事自检误伤）

用法: python3 scripts/test_fetch.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_fin as F     # noqa: E402
import factsheet as FS    # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def parse(text):
    recs, warns = F.gather(text)
    comps = F.to_batch(recs, {})
    return {c["code"]: c for c in comps}, warns


@case("列序变化不影响取值")
def t_colorder():
    a = """| 证券代码 | 年份 | 营业总收入(亿元) | 归母净利润(亿元) | 销售毛利率(%) |
|---|---|---|---|---|
| 600519.SH | 2025 | 1688.38 | 823.20 | 91.18 |
"""
    b = """| 年份 | 销售毛利率(%) | 归母净利润(亿元) | 证券代码 | 营业总收入(亿元) |
|---|---|---|---|---|
| 2025 | 91.18 | 823.20 | 600519.SH | 1688.38 |
"""
    ra, _ = parse(a)
    rb, _ = parse(b)
    ya = ra["600519.SH"]["years"][0]
    yb = rb["600519.SH"]["years"][0]
    for k in ("rev", "np", "gm"):
        assert ya[k] == yb[k], f"{k} 随列序变了：{ya[k]} vs {yb[k]}"


@case("净利三种写法都能认")
def t_np_aliases():
    for alias in ("归母净利润", "归属净利润", "归属于母公司所有者的净利润"):
        text = (f"| 证券代码 | 年份 | 营业总收入(亿元) | {alias}(亿元) |\n"
                "|---|---|---|---|\n| 000333.SZ | 2025 | 4564.52 | 439.45 |\n")
        r, _ = parse(text)
        assert r["000333.SZ"]["years"][0]["np"] == 439.45, alias


@case("四种单位换算")
def t_units():
    text = """| 证券代码 | 年份 | 营业总收入(元) | 归母净利润(元) |
|---|---|---|---|
| 600028.SH | 2025 | 2783600000000 | 31809000000 |
"""
    r, _ = parse(text)
    y = r["600028.SH"]["years"][0]
    assert abs(y["rev"] - 27836.0) < 0.01, y["rev"]
    assert abs(y["np"] - 318.09) < 0.01, y["np"]

    text = """| 证券代码 | 年份 | 营业总收入(万元) | 归母净利润(亿元) |
|---|---|---|---|
| 600028.SH | 2025 | 278360000 | 318.09 |
"""
    r, _ = parse(text)
    y = r["600028.SH"]["years"][0]
    assert abs(y["rev"] - 27836.0) < 0.01, y["rev"]

    # 万亿元 必须优先于 亿元 命中，否则差 1e4
    text = """| 证券代码 | 年份 | 营业总收入(万亿元) | 归母净利润(亿元) |
|---|---|---|---|
| 600028.SH | 2025 | 2.7836 | 318.09 |
"""
    r, _ = parse(text)
    assert abs(r["600028.SH"]["years"][0]["rev"] - 27836.0) < 0.01


@case("季报/中报不得混入年度")
def t_skip_interim():
    text = """| 证券代码 | 年份 | 报告期 | 营业总收入(亿元) | 归母净利润(亿元) |
|---|---|---|---|---|
| 000333.SZ | 2025 | 2025-12-31 | 4564.52 | 439.45 |
| 000333.SZ | 2026 | 2026-09-30 | 3200.00 | 300.00 |
| 000333.SZ | 2027 | 2027中报 | 2000.00 | 200.00 |
"""
    r, _ = parse(text)
    ys = [y["y"] for y in r["000333.SZ"]["years"]]
    assert ys == [2025], ys


@case("营业总收入覆盖营业收入，反之不覆盖")
def t_rev_total_wins():
    text = """| 证券代码 | 年份 | 营业总收入(亿元) | 归母净利润(亿元) |
|---|---|---|---|
| 601398.SH | 2025 | 8380.00 | 3700.00 |

| 证券代码 | 年份 | 营业收入(亿元) |
|---|---|---|
| 601398.SH | 2025 | 8218.03 |
"""
    r, _ = parse(text)
    y = r["601398.SH"]["years"][0]
    assert y["rev"] == 8380.0, y["rev"]
    # 反过来：先给营业收入、再给营业总收入，应当被总收入覆盖
    text2 = text.split("\n\n")[1] + "\n" + text.split("\n\n")[0]
    r2, _ = parse(text2)
    assert r2["601398.SH"]["years"][0]["rev"] == 8380.0


@case("毛利率 -- 保持 None 而不是 0")
def t_gm_null():
    text = """| 证券代码 | 年份 | 营业总收入(亿元) | 归母净利润(亿元) | 销售毛利率(%) |
|---|---|---|---|---|
| 600036.SH | 2025 | 3375.32 | 1501.81 | -- |
"""
    r, _ = parse(text)
    assert r["600036.SH"]["years"][0]["gm"] is None


@case("毛利率小数与百分数都归一成百分数")
def t_gm_scale():
    for raw, want in (("91.18", 91.18), ("0.9118", 91.18)):
        text = (f"| 证券代码 | 年份 | 营业总收入(亿元) | 归母净利润(亿元) | 销售毛利率(%) |\n"
                f"|---|---|---|---|---|\n| 600519.SH | 2025 | 1688.38 | 823.20 | {raw} |\n")
        r, _ = parse(text)
        got = r["600519.SH"]["years"][0]["gm"]
        assert abs(got - want) < 0.01, (raw, got)


@case("毛利率跨盈亏平衡点：整块缩放而不是逐值猜")
def t_gm_block_scale():
    # 隆基 2025 年毛利率 0.81%、2024 年 13.1%，同一块里必须都按百分数读。
    # 逐值猜（|v|>1 才乘 100）会把 0.81 读成 81%，是最危险的一种静默失真。
    text = """| 证券代码 | 年份 | 营业总收入(亿元) | 归母净利润(亿元) | 销售毛利率(%) |
|---|---|---|---|---|
| 601012.SH | 2024 | 825.8 | -86.2 | 13.1 |
| 601012.SH | 2025 | 703.47 | -45.0 | 0.81 |
| 002299.SZ | 2015 | 69.4 | -3.88 | -0.08 |
"""
    r, _ = parse(text)
    gm = {y["y"]: y["gm"] for y in r["601012.SH"]["years"]}
    assert gm[2025] == 0.81, gm
    assert gm[2024] == 13.1, gm
    assert r["002299.SZ"]["years"][0]["gm"] == -0.08


@case("表头无单位要报警告")
def t_unit_warn():
    text = """| 证券代码 | 年份 | 营业收入 | 归母净利润 |
|---|---|---|---|
| 600028.SH | 2025 | 27836 | 318.09 |
"""
    _, warns = parse(text)
    assert any("未标注单位" in w for w in warns), warns


@case("缺年份不插值，断档留在 note 里")
def t_gap():
    text = """| 证券代码 | 年份 | 营业总收入(亿元) | 归母净利润(亿元) |
|---|---|---|---|
| 600000.SH | 2022 | 100.0 | 10.0 |
| 600000.SH | 2024 | 120.0 | 12.0 |
| 600000.SH | 2025 | 130.0 | 13.0 |
"""
    recs, _ = F.gather(text)
    comps = F.to_batch(recs, {})
    ys = [y["y"] for y in comps[0]["years"]]
    assert ys == [2022, 2024, 2025], ys
    assert comps[0]["_gaps"] == [[2022, 2024]], comps[0]["_gaps"]


@case("代码补市场后缀")
def t_code():
    text = """| 证券代码 | 年份 | 营业总收入(亿元) | 归母净利润(亿元) |
|---|---|---|---|
| 600519 | 2025 | 1688.38 | 823.20 |
| 000333 | 2025 | 4564.52 | 439.45 |
| 300750 | 2025 | 4000.00 | 500.00 |
| 688981 | 2025 | 600.00 | 50.00 |
"""
    r, _ = parse(text)
    assert set(r) == {"600519.SH", "000333.SZ", "300750.SZ", "688981.SH"}, set(r)


@case("叙事自检：周期股相邻年倍数不误报")
def t_narrative_cycle():
    # 旗滨 2022 净利腰斩、2021 顶峰，相邻年 PB 4 倍以上——都不能算「叙事不一致」
    c = {
        "code": "601636.SH", "name": "旗滨集团", "industry": "建筑材料",
        "coverage": [2011, 2025],
        "years": [{"y": 2011, "rev": 20.0, "np": 1.0, "gm": 20.0},
                  {"y": 2021, "rev": 145.0, "np": 42.34, "gm": 50.24},
                  {"y": 2025, "rev": 160.0, "np": 3.83, "gm": 15.51}],
        "shift": "2011 年上市，2021 年净利 42.34 亿为周期顶，2025 年只剩 3.83 亿。",
        "flags": ["净利 42.34 亿 → 3.83 亿，跌幅 91%"],
        "verdict": "周期股，看 PB 不看 PE，因为盈利在周期底部会趋近于零。",
        "valuation": None,
    }
    f = FS.facts(c)
    assert not f["checks"], f["checks"]


@case("叙事自检：能抓出「营收倍数」写错")
def t_narrative_wrong_multiple():
    c = {
        "code": "000708.SZ", "name": "中信特钢", "industry": "钢铁",
        "coverage": [1997, 2025],
        "years": [{"y": 1997, "rev": 18.73, "np": 1.48, "gm": 19.29},
                  {"y": 2025, "rev": 1073.73, "np": 59.29, "gm": 14.94}],
        "shift": "1997 年上市。",
        # 全区间 57 倍，文字却说 5.8 倍——这正是 v7c 实际抓到的那条
        "flags": ["2019 年借壳注入造成营收 5.8 倍跳变"],
        "verdict": "特钢的认证壁垒高于普钢，但借壳造成序列断点，跨 2019 年不可比。",
        "valuation": None,
    }
    f = FS.facts(c)
    assert any("营收" in x and "倍" in x for x in f["checks"]), f["checks"]


@case("表头写元、单元格写亿：以单元格后缀为准")
def t_header_unit_mismatch():
    # ifind 实际返回形态：表头标注「（单位：元）」，单元格却写「21.5863亿」。
    # 若按表头的「元」换算，21.5863 × 1e-8 = 0.0 亿，静默失真。
    text = """| 证券代码 | 日期 | 归属于母公司所有者的净利润（单位：元） | 营业总收入（单位：元） | 销售毛利率（单位：%） |
|---|---|---|---|---|---|
| 600436.SH | 20251231 | 21.5863亿 | 90.0141亿 | 36.4266 |
| 600436.SH | 20241231 | 29.77亿 | 107.8786亿 | 42.7353 |
"""
    comps, warns = parse(text)
    yrs = comps["600436.SH"]["years"]
    assert yrs[1]["y"] == 2025 and abs(yrs[1]["np"] - 21.59) < 0.01, yrs[1]
    assert abs(yrs[1]["rev"] - 90.01) < 0.01, yrs[1]
    assert abs(yrs[1]["gm"] - 36.43) < 0.01, yrs[1]


@case("叙事自检：带区间的倍数按区间算，不与全区间比")
def t_narrative_range():
    c = {
        "code": "300070.SZ", "name": "碧水源", "industry": "环保",
        "coverage": [2010, 2025],
        "years": [{"y": 2010, "rev": 5.0, "np": 1.77, "gm": 48.61},
                  {"y": 2017, "rev": 137.7, "np": 25.09, "gm": 25.0},
                  {"y": 2025, "rev": 77.84, "np": 0.61, "gm": 24.53}],
        "shift": "2010 年上市，2017 年净利 25.09 亿见顶。",
        "flags": ["2010–2017 年营收增长 27 倍，是 PPP 模式下的垫资式增长"],
        "verdict": "PPP 垫资式增长的典型样本，2017 年后利润一路下滑到不足 1 亿。",
        "valuation": None,
    }
    f = FS.facts(c)
    assert not f["checks"], f["checks"]


def main():
    ok = 0
    for name, fn in CASES:
        try:
            fn()
            print(f"[PASS] {name}")
            ok += 1
        except AssertionError as e:
            print(f"[FAIL] {name}: {e}")
        except Exception as e:                      # noqa: BLE001
            print(f"[ERR ] {name}: {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(CASES)} 通过")
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
