#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金融专用指标与估值补丁。

数据来源：同花顺 iFinD（get_security_indicators），口径见下方注释。
本脚本幂等：重复运行覆盖同名字段，不破坏其他字段。

金融指标（financial）：
- bank：净息差 nim、不良率 npl、成本收入比 cir、拨备覆盖率 cov、加权 ROE roe
- insurance：新业务价值 nbv（亿元）、内含价值 ev（亿元）、NBV 率 nbvm（%）

估值（valuation）：时点快照 2025-12-31，市盈率 PE(TTM)、市净率 PB、股息率 TTM。
周期股优先看 PB 与股息率，不机械用 PE。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "companies.json"

FINANCIAL = {
    "600036.SH": {
        "type": "bank",
        "metrics": ["净息差", "不良率", "成本收入比", "拨备覆盖率", "加权ROE"],
        "years": [
            {"y": 2021, "nim": 2.48, "npl": 0.91, "cir": 33.12, "cov": 483.87, "roe": 16.96},
            {"y": 2022, "nim": 2.40, "npl": 0.96, "cir": 32.88, "cov": 450.79, "roe": 17.06},
            {"y": 2023, "nim": 2.15, "npl": 0.95, "cir": 32.96, "cov": 437.70, "roe": 16.22},
            {"y": 2024, "nim": 1.98, "npl": 0.95, "cir": 31.89, "cov": 411.98, "roe": 14.49},
            {"y": 2025, "nim": 1.87, "npl": 0.94, "cir": 31.98, "cov": 391.79, "roe": 13.44},
        ],
    },
    "601318.SH": {
        "type": "insurance",
        "metrics": ["新业务价值", "内含价值", "NBV率"],
        "years": [
            {"y": 2021, "nbv": 378.98, "ev": 13955, "nbvm": 27.8},
            {"y": 2022, "nbv": 288.20, "ev": 14238, "nbvm": 24.1},
            {"y": 2023, "nbv": 310.80, "ev": 13901, "nbvm": 18.7},
            {"y": 2024, "nbv": 285.34, "ev": 14226, "nbvm": 18.5},
            {"y": 2025, "nbv": 368.97, "ev": 15043, "nbvm": 23.4},
        ],
    },
}

# 时点快照 2025-12-31（抽样覆盖，非全样本）
VALUATION = {
    "600519.SH": {"pe": 19.16, "pb": 6.68, "dy": 3.77},
    "600036.SH": {"pe": 7.13, "pb": 1.00, "dy": 4.79},
    "601088.SH": {"pe": 14.81, "pb": 1.86, "dy": 4.96},
    "601919.SH": {"pe": 6.18, "pb": 0.96, "dy": 6.59},
    "300750.SZ": {"pe": 26.28, "pb": 6.41, "dy": 2.17},
}
VALUATION_ASOF = "2025-12-31"


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    for c in data["companies"]:
        code = c["code"]
        if code in FINANCIAL:
            c["financial"] = FINANCIAL[code]
        if code in VALUATION:
            c["valuation"] = dict(VALUATION[code], asof=VALUATION_ASOF)
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已打补丁：金融指标 {len(FINANCIAL)} 家，估值 {len(VALUATION)} 家（{VALUATION_ASOF}）")


if __name__ == "__main__":
    main()
