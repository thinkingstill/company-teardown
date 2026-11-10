#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判词事实卡：把叙事里最容易「年久失修」的那几个数字从数据里重算一遍。

为什么需要它
------------
库里每家公司的 verdict / flags 都是写的时候对着当时的数据写的，文字本身不参与
任何校验——`validate.py` 只查结构、`check_valuation.py` 只查估值。于是有两个真问题：

1. **叙事先于数据**。写 verdict 时用的是查询结果，落库后序列可能又补过年份
   （v6b 跨市场补长、v6c 每行业加深、v7b 估值补十年）。文字里的「十六年」「CAGR 11.7%」
   不会自动跟着变。
2. **叙事里的数字来源不可复现**。有的来自营业收入，有的来自营业总收入，有的取自
   毛利额、有的取自毛利率。人工抄写时极容易把「营收 3.8 倍」写成「毛利 3.8 倍」。

本脚本不做判断，只把「区间倍数 / CAGR / 毛利率区间 / 亏损年 / 估值分位」这些
**可以从数据算出**的量摆出来，供人工逐条核对 narrative 里的说法。
凡是能从数据算的，就不该靠记忆。

用法
----
    python3 scripts/factsheet.py                # 全部公司，一行一家，Markdown 表格
    python3 scripts/factsheet.py 600519.SH      # 单家完整事实卡
    python3 scripts/factsheet.py 600519.SH --json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "companies.json"


def cagr(a, b, n):
    """n 年复合增速（%）。a<=0 或 b<0 时无意义——负数开分数次方会得出复数，
    起点亏损的公司算 CAGR 更是纯粹的算术陷阱，一律返回 None。"""
    if a is None or b is None or n <= 0 or a <= 0 or b < 0:
        return None
    return ((b / a) ** (1.0 / n) - 1.0) * 100.0


def band(x, lo=33.3, hi=66.7):
    if x is None:
        return None
    return "低" if x < lo else ("高" if x > hi else "中")


def facts(c):
    ys = c["years"]
    y0, y1 = ys[0]["y"], ys[-1]["y"]
    n = y1 - y0
    rev0, rev1 = ys[0]["rev"], ys[-1]["rev"]
    np0, np1 = ys[0]["np"], ys[-1]["np"]

    gms = [y["gm"] for y in ys if y["gm"] is not None]
    # 毛利率区间只在毛利率可比的公司里有意义；券商/银行/保险 gm 全为 null，
    # 直接用会得到空列表，必须在输出里显式标「无毛利率口径」而不是「—」。
    gm_range = (min(gms), max(gms)) if gms else None

    neg = [y["y"] for y in ys if y["np"] < 0]
    # 连续亏损段：单年亏损和连续多年亏损是两种不同的性质，只报「有几年亏损」会混淆
    runs, cur = [], []
    for y in ys:
        if y["np"] < 0:
            cur.append(y["y"])
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)

    peak = max(ys, key=lambda y: y["np"])
    trough = min(ys, key=lambda y: y["np"])

    v = c.get("valuation") or {}
    hist = v.get("history") or []
    pct = v.get("pct") or {}

    return {
        "code": c["code"],
        "name": c["name"],
        "industry": c.get("industry"),
        "sw2": c.get("sw2"),
        "listed": c.get("listed"),
        "span": [y0, y1, n],
        "rev": {"from": rev0, "to": rev1,
                "x": round(rev1 / rev0, 2) if rev0 else None,
                "cagr": None if cagr(rev0, rev1, n) is None else round(cagr(rev0, rev1, n), 1)},
        "np": {"from": np0, "to": np1,
               "x": round(np1 / np0, 2) if np0 and np0 > 0 else None,
               "cagr": None if cagr(np0, np1, n) is None else round(cagr(np0, np1, n), 1)},
        "gm": {"from": ys[0]["gm"], "to": ys[-1]["gm"],
               "range": None if not gm_range else [round(gm_range[0], 2), round(gm_range[1], 2)],
               "null_years": sum(1 for y in ys if y["gm"] is None)},
        "loss": {"years": neg, "runs": runs,
                 "peak": [peak["y"], peak["np"]],
                 "trough": [trough["y"], trough["np"]]},
        "valuation": {
            "asof": v.get("asof"),
            "pe": v.get("pe"), "pb": v.get("pb"), "dy": v.get("dy"),
            "window": [hist[0]["y"], hist[-1]["y"]] if hist else None,
            "n": len(hist),
            "pct": {k: (None if pct.get(k) is None else round(pct[k], 1)) for k in ("pe", "pb", "dy")},
            "band": {k: band(pct.get(k)) for k in ("pe", "pb", "dy")},
            "pe_state": v.get("pe_state"),
        },
        "checks": textual_checks(c, ys, y0, y1, n, rev0, rev1),
    }


def textual_checks(c, ys, y0, y1, n, rev0, rev1):
    """把叙事文字里出现的「可比数字」与数据比对一遍。

    只做三件非常保守的事，宁可漏报也不误报：
      1. 文字里写了「XXXX–YYYY 营收 A 倍」，就用数据算的倍数核对；
      2. 文字里出现「CAGR x%」，用数据算的 CAGR 核对；
      3. 文字里写的年份若超出覆盖区间，说明叙事引用了库里没有的年份。
    这三类是可机检的；其余判断（如「护城河强不强」）不可机检，不做。
    """
    import re
    issues = []
    texts = []
    for k in ("verdict", "shift", "note"):
        if c.get(k):
            texts.append((k, c[k]))
    for i, f in enumerate(c.get("flags") or []):
        texts.append((f"flags[{i}]", f))

    # 3) 年份越界：只报「4 位年份 + 年」且明确落在覆盖区间外的
    for where, t in texts:
        for m in re.finditer(r"(19\d{2}|20\d{2})\s*年", t):
            y = int(m.group(1))
            if y < y0 or y > y1:
                issues.append(f"{where}: 提到 {y} 年，超出覆盖区间 {y0}–{y1}")
                break

    # 1) 「倍数」自检：文字声称的营收倍数与实算差 20% 以上才报。
    #    先认「YYYY–YYYY 年营收……N 倍」这种**自带区间**的写法，按区间内首末年实算；
    #    否则退回全区间。否则碧水源「2010–2017 年营收增长 27 倍」会被拿去和
    #    「2010–2025 全区间 15.57 倍」比，误报。区间写法本身是合法的。
    real_rev_x = (rev1 / rev0) if rev0 else None
    by_year = {y["y"]: y["rev"] for y in ys}
    for where, t in texts:
        if "营收" not in t:
            continue
        m = re.search(r"(19\d{2}|20\d{2})\s*[–—\-~至]\s*(19\d{2}|20\d{2})\s*年[^。；]{0,10}?营收"
                      r"[^。；，]{0,16}?([0-9]+(?:\.[0-9]+)?)\s*倍", t)
        if m:
            ya, yb, claim = int(m.group(1)), int(m.group(2)), float(m.group(3))
            if ya in by_year and yb in by_year and by_year[ya]:
                real = by_year[yb] / by_year[ya]
                # 「增长 N 倍」= 变为 N+1 倍，两种写法差 1，两边都认
                if abs(claim - real) / real > 0.2 and abs(claim + 1 - real) / real > 0.2:
                    issues.append(f"{where}: 称 {ya}–{yb} 营收 {claim} 倍，数据实为 {real:.2f} 倍")
            continue
        m = re.search(r"营收[^。；，]{0,12}?([0-9]+(?:\.[0-9]+)?)\s*倍", t)
        if m and real_rev_x:
            claim = float(m.group(1))
            # 1 倍起步与「增长 N 倍」两种写法差 1，容忍区间取宽
            if claim >= 1.2 and abs(claim - real_rev_x) / real_rev_x > 0.2 \
                    and abs(claim - (real_rev_x - 1)) / real_rev_x > 0.2:
                issues.append(
                    f"{where}: 文字称营收 {claim} 倍，数据实为 {real_rev_x:.2f} 倍")
    return issues


def main(argv):
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    cs = payload["companies"]

    if len(argv) > 1 and not argv[1].startswith("-"):
        key = argv[1]
        hit = [c for c in cs if c["code"] == key or c["name"] == key]
        if not hit:
            print(f"[ERROR] 找不到 {key}")
            return 1
        f = facts(hit[0])
        if "--json" in argv:
            print(json.dumps(f, ensure_ascii=False, indent=1))
            return 0
        print(f"# {f['name']} {f['code']}  {f['industry']}/{f['sw2']}")
        print(f"上市 {f['listed']}  覆盖 {f['span'][0]}–{f['span'][1]}（{f['span'][2]} 年）")
        r, p = f["rev"], f["np"]
        print(f"营收 {r['from']} → {r['to']} 亿，{r['x']} 倍，CAGR {r['cagr']}%")
        print(f"净利 {p['from']} → {p['to']} 亿，{p['x']} 倍，CAGR {p['cagr']}%")
        g = f["gm"]
        print(f"毛利率 {g['from']}% → {g['to']}%，区间 {g['range']}"
              f"{'' if g['null_years'] == 0 else '  （%d 年无口径）' % g['null_years']}")
        L = f["loss"]
        print(f"亏损年 {L['years'] or '无'}；连续段 {L['runs'] or '无'}")
        print(f"净利峰 {L['peak'][0]} {L['peak'][1]} 亿；谷 {L['trough'][0]} {L['trough'][1]} 亿")
        v = f["valuation"]
        if v["asof"]:
            print(f"估值 {v['asof']}  PE {v['pe']} PB {v['pb']} 股息率 {v['dy']}")
            print(f"  分位（{v['window'][0]}–{v['window'][1]} 共 {v['n']} 年）"
                  f" PE {v['pct']['pe']}({v['band']['pe']})"
                  f" PB {v['pct']['pb']}({v['band']['pb']})"
                  f" 股息率 {v['pct']['dy']}({v['band']['dy']})  PE 状态 {v['pe_state']}")
        else:
            print("估值：无")
        if f["checks"]:
            print("\n[可机检的叙事不一致]")
            for x in f["checks"]:
                print("  -", x)
        return 0

    # 全量：一行一家
    allf = [facts(c) for c in cs]
    print("| 公司 | 代码 | 行业 | 覆盖 | 营收倍数 | 营收CAGR | 净利CAGR | 毛利率 | 亏损年 | PB分位 | 叙事不一致 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for f in allf:
        g = f["gm"]
        print("| {name} | {code} | {ind} | {s0}–{s1}({n}年) | {rx} | {rc}% | {pc}% | {gr} | {ly} | {pb} | {bad} |".format(
            name=f["name"], code=f["code"], ind=f["industry"],
            s0=f["span"][0], s1=f["span"][1], n=f["span"][2],
            rx="—" if f["rev"]["x"] is None else f"{f['rev']['x']}x",
            rc="—" if f["rev"]["cagr"] is None else f["rev"]["cagr"],
            pc="—" if f["np"]["cagr"] is None else f["np"]["cagr"],
            gr="无口径" if not g["range"] else f"{g['range'][0]}–{g['range'][1]}%",
            ly=len(f["loss"]["years"]) or "无",
            pb="—" if f["valuation"]["pct"]["pb"] is None else f"{f['valuation']['pct']['pb']}({f['valuation']['band']['pb']})",
            bad=len(f["checks"]) or "",
        ))
    nbad = sum(1 for f in allf if f["checks"])
    print(f"\n[INFO] {len(allf)} 家，其中 {nbad} 家有可机检的叙事不一致")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
