#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data/companies.json 注入 site/template.html，生成单文件 index.html；
同时把每家公司拆分存到 data/companies/<code>.json，便于逐家引用与增量维护。

用法:
    python3 scripts/build_site.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "companies.json"
TPL = ROOT / "site" / "template.html"
OUT = ROOT / "index.html"
SPLIT_DIR = ROOT / "data" / "companies"


def main() -> int:
    if not DATA.exists():
        print(f"[ERR] 缺少数据文件 {DATA}")
        return 1
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    companies = payload.get("companies", [])
    if not companies:
        print("[ERR] companies 为空")
        return 1

    # 按覆盖年数排序：上市越早的排前面（历史越长，信息量越大）
    companies.sort(key=lambda c: (c["coverage"][0], c["code"]))
    payload["companies"] = companies

    # 拆分存储
    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    for c in companies:
        p = SPLIT_DIR / f"{c['code'].replace('.', '_')}.json"
        p.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")

    tpl = TPL.read_text(encoding="utf-8")
    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    meta_js = json.dumps(payload.get("meta", {}), ensure_ascii=False, separators=(",", ":"))
    html = tpl.replace("__DATA_JSON__", data_js).replace("__META_JSON__", meta_js)

    leftovers = re.findall(r"\{\{[^}]{0,60}\}\}", html)
    if leftovers:
        print(f"[WARN] 模板残留占位符 {len(leftovers)} 处：{leftovers[:3]}")

    OUT.write_text(html, encoding="utf-8")
    size = len(html.encode("utf-8")) / 1024
    print(f"[OK] {OUT}  ({size:.0f} KB, {len(companies)} 家公司, "
          f"{sum(len(c['years']) for c in companies)} 个财年)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
