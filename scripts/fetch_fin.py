#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v7c 第一步：取数脚本化——从 MCP 返回的原始表格到 `tmp/batch_*.json` 全程无人手抄。

为什么要做这件事
----------------
前 161 家是「子 Agent 查数 → 手工转写进 tmp/batch_*.json → 手工写 narr_*.py」。
两处都要人眼对齐代码与年份，每批次都要专门写一段解析逻辑，而且每次列序变化就得改一次。
规模在 160 家时还能靠人工复核兜住，冲 300 家就会变成错误率问题：
一个代码错位，整家公司的序列就串到别人名下，而 `validate.py` 看不出「数字对不对」。

拆成两个脚本，各管一段，中间产物都是 JSON：

    scripts/fetch_fin.py      查询结果（原始表格文本）→ tmp/batch_*.json
    scripts/mk_narr_skeleton.py  tmp/batch_*.json → narr_*.py 骨架（已有）

本脚本只做第一段，并且**只接受「已经落盘的原始返回」**，不自己发起查询：
取数工具的返回格式（Markdown 表格 / JSON / 报错文本）不稳定，把它放在可复现的
解析器里比放在一次性的对话里更可靠。原始返回从 stdin 或文件进来。

解析规则（全部来自 docs/data-notes.md 记录过的坑）
------------------------------------------------
1. **列序每次都可能变**，必须逐行按所属表头定位，不能用固定下标；
2. 「营业收入」对券商/银行/保险会剔除利息净收入，必须改取「营业总收入」；
3. 单位有 元 / 万元 / 亿元 / 万亿元 四种，统一换算成亿元；
4. 同一年可能返回多条（年报 + 快报 + 更正），取**年报口径**且最新的那条；
5. 取不到就填 null，禁止插值、禁止用相邻年填充。

用法
----
    # 解析一段 Markdown 表格（含表头），输出到 tmp/batch_v8_1.json
    python3 scripts/fetch_fin.py --in raw.txt --out tmp/batch_v8_1.json

    # 从 stdin 读，同时校验「与已有公司不重复、代码在计划表里」
    cat raw.txt | python3 scripts/fetch_fin.py --expect tmp/v8_plan.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 单位倍数 → 亿元
UNIT = {"元": 1e-8, "万元": 1e-4, "千元": 1e-7, "亿元": 1.0, "万亿元": 1e4, "亿": 1.0, "万": 1e-4}

NUM_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
YEAR_RE = re.compile(r"(19\d{2}|20\d{2})")


def cells(line):
    """Markdown 表格行 → 单元格列表。去掉首尾管道，保留空单元格。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [x.strip() for x in s.split("|")]


def is_sep(line):
    return bool(re.match(r"^\s*\|?[\s:|-]+\|?\s*$", line)) and "-" in line


def norm_header(cells_):
    """表头归一：去空格、去全角括号、去掉「（单位：元）」这类尾部限定。

    这一步是必需的，不是美化。实测同花顺同一列在不同批次的写法有
    「归属净利润」「归母净利润」「归属于母公司所有者的净利润」三种，
    「营业收入(元)」与「营业收入 (亿元)」的括号前是否有空格也不固定。
    不归一，`find_col` 的精确匹配就永远命中不了，只能退回模糊匹配，
    而模糊匹配会让「净利润」吃掉「营业总收入」之外的列。
    """
    out = []
    for h in cells_:
        s2 = h.replace(" ", "").replace("\u3000", "")
        s2 = s2.replace("（", "(").replace("）", ")")
        # 去掉单位限定：末尾的 "(元)"/"(亿元)"/"(单位：万元)" 及 "亿元" 等
        s2 = re.sub(r"\((单位[:：])?[^)]*元\)$", "", s2)
        s2 = re.sub(r"(单位[:：])?[^()]*元$", "", s2) if "元" in s2 and "(" not in s2 else s2
        out.append(s2)
    return out


def parse_number(v):
    """'1,234.56' → 1234.56；'--' / '' / '亏损' → None。"""
    r = parse_number_with_unit(v)
    return r[0] if r else None


def parse_number_with_unit(v):
    """'1,234.56' → (1234.56, None)；'21.59亿' → (21.59, '亿')；'--' → None。

    返回 (数值, 单元格自带单位后缀)。ifind 有个坑：表头写「（单位：元）」，
    单元格却写「21.5863亿」——表头单位与实际数据单位不一致。这种情况下必须以
    单元格的「亿」后缀为准，否则按表头的「元」换算会把 21 亿压成 0.0 亿（静默失真）。
    """
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("，", "")
    if not s or s in {"--", "-", "—", "N/A", "nan", "null", "None"}:
        return None
    m = re.match(r"^(-?[\d.]+)\s*(万亿元|万亿|亿元|亿|万元|万|千元|元)?$", s)
    if not m:
        return None
    try:
        return float(m.group(1)), m.group(2)
    except ValueError:
        return None


def detect_unit(header):
    """从表头文字里认单位。同花顺的写法有「(亿元)」「（单位：万元）」「(元)」多种。

    - 必须「万亿元」排最前：「亿元」是「万亿元」的子串，顺序反了会把万亿读成亿，
      差 4 个数量级（中国石化在 v4 踩过）。
    - 表头没写单位时返回 None，**不默认按元**。实测接口多数场景直接给亿元数值，
      按元换算会把 8218 亿压成 0.0 亿——只改小数位、不报错，是典型的静默失真。
      调用方拿到 None 要记 warn，逼人回去看原始表头。
    """
    for u in ("万亿元", "亿元", "万元", "千元", "元"):
        if u in header:
            return u
    return None


def find_col(hdr, *names):
    """按表头定位列下标。names 按优先级排列，先精确后模糊。

    必须按「所属表头」定位而不是全局找一次：同一次返回里，不同指标块
    （营业收入 / 归母净利润 / 毛利率）的表头是分开给的，列序可以各不相同。
    """
    for nm in names:
        for i, h in enumerate(hdr):
            if nm == h:
                return i
    for nm in names:
        for i, h in enumerate(hdr):
            if nm in h:
                return i
    return None


def blocks(text):
    """把文本切成若干「表头 + 数据行」的块。

    返回 [{"hdr": [...], "rows": [[...], ...]}]
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    blocks, cur = [], None
    for ln in lines:
        if "|" not in ln:
            # 非表格行（说明文字、分隔、错误信息）打断当前块
            if cur and cur["rows"]:
                blocks.append(cur)
                cur = None
            continue
        if is_sep(ln):
            continue
        cs = cells(ln)
        # 表头：含「证券代码 / 代码 / 年份 / 日期」这类标识列，且没有纯数字年份
        joined = "|".join(cs)
        looks_hdr = ("证券代码" in joined or "股票代码" in joined or "代码" in joined
                     or "年份" in joined or "报告期" in joined or "指标" in joined)
        if looks_hdr and not any(NUM_RE.match(c.replace(",", "")) and len(c) > 3 for c in cs):
            if cur and cur["rows"]:
                blocks.append(cur)
            cur = {"hdr": cs, "rows": []}
            continue
        if cur is None:
            continue
        cur["rows"].append(cs)
    if cur and cur["rows"]:
        blocks.append(cur)
    return blocks


def resolve_unit(cell_unit, header):
    """决定一条数值最终按什么单位换算成亿元。

    - 单元格自带「亿/万」后缀（如「21.5863亿」）优先：ifind 的表头常写「（单位：元）」
      但单元格值却带「亿」字，表头单位与实际数据不一致。以单元格后缀为准。
    - 单元格无后缀时，退回表头单位。
    """
    if cell_unit:
        for u in ("万亿元", "亿元", "万元", "千元", "元", "万亿", "亿", "万"):
            if cell_unit == u:
                return u
    return detect_unit(header)


def gather(text):
    """从全部表格块里收集 (code, year) → {rev, np, gm}，以及单位告警。"""
    out, warns = {}, []
    unknown_units = set()
    for b in blocks(text):
        # 保留原始表头判单位，归一后的表头用于定位列
        raw_hdr = b["hdr"]
        hdr = norm_header(raw_hdr)

        # 代码列：可能是「证券代码」也可能夹在「股票代码.市场」里
        ci = find_col(hdr, "证券代码", "股票代码", "代码")
        # 年份列：可能是「年份」，也可能是「报告期 / 日期 / 2025-12-31」这种
        # 「年份」列的优先级必须低于「报告期 / 日期」：只写了年份的列没有月日，
        # 无法判断是年报还是三季报；要是有「报告期」列就必须用它的完整日期。
        yi = find_col(hdr, "报告期", "日期", "时间", "年份")
        if ci is None or yi is None:
            # 这种块不是「按公司按年份」的长表，跳过（例如指标说明表）
            continue

        # 指标列：一个块可能同时有营收/净利/毛利率三列，也可能一次只有一列
        ri = find_col(hdr, "营业总收入", "营业收入")
        # 营收优先取营业总收入：券商/银行的「营业收入」剔除了利息净收入，会严重低估。
        # 用三档：先找营业总收入列，没有再退回营业收入列。
        r_is_total = ri is not None and "营业总收入" in hdr[ri]
        ni = find_col(hdr, "归母净利润", "归属于母公司所有者的净利润", "净利润")
        gi = find_col(hdr, "销售毛利率", "毛利率")

        # 两个列定位可能指向同一列（表头只写「净利润」时，「归母净利润」模糊匹配
        # 与「净利润」都会命中它）。这块只提供一个指标列时，宁可认不出来，也不能
        # 让同一列的数同时进营收和净利。
        if ni is not None and ri is not None and ni == ri:
            ni = None
        if gi is not None and gi in (ri, ni):
            gi = None

        gm_raw = []       # 本块的毛利率原始值，块尾统一判断量纲
        for row in b["rows"]:
            if ci >= len(row) or yi >= len(row):
                continue
            raw_code = row[ci].strip()
            m = re.match(r"^(\d{6})\.?(SH|SZ|BJ)?$", raw_code, re.I)
            if not m:
                continue
            code = m.group(1) + "." + (m.group(2) or guess_market(m.group(1))).upper()

            period = row[yi]
            # 只接受年报口径：报告期写 12-31，或只写了年份。
            # 三季报/半年报混进来会让「年度营收」变成 9 个月的数字，且没有任何字段能看出来。
            # 判定必须在「取年份」之前：报告期是 2026-09-30 而「年份」列写的是 2026，
            # 先取年份再判季报会漏，季度值直接混进 2026 年度。
            if re.search(r"-(0[1-9]|1[0-1])-", period) or re.search(
                    r"[QH]\s*[1-4]|中报|三季|半年", period):
                continue
            ym = YEAR_RE.search(period)
            if not ym:
                continue
            year = int(ym.group(1))

            rec = out.setdefault((code, year), {})
            if ni is not None and ni < len(row):
                r = parse_number_with_unit(row[ni])
                if r is not None:
                    u = resolve_unit(r[1], raw_hdr[ni])
                    if u is None:
                        unknown_units.add(raw_hdr[ni])
                        u = "元"
                    rec["np"] = round(r[0] * UNIT[u], 2)
            if gi is not None and gi < len(row):
                v = parse_number(row[gi])
                if v is not None:
                    # 毛利率只在**表格区间内**统一缩放，不能逐值判断。
                    # 逐值猜（|v|>1 就当百分数）会把隆基 2025 年 0.81% 的毛利率
                    # 读成 81%，把圣农 2015 年 -0.08% 读成 -8%——这两家恰好都在
                    # 盈亏平衡点附近，正是最需要看准的时候。
                    rec["gm"] = v
                    gm_raw.append(abs(v))
            if ri is not None and ri < len(row):
                r = parse_number_with_unit(row[ri])
                if r is not None:
                    u = resolve_unit(r[1], raw_hdr[ri])
                    if u is None:
                        unknown_units.add(raw_hdr[ri])
                        u = "元"
                    v = r[0] * UNIT[u]
                    # 同一 (代码, 年份) 可能被多个块覆盖：一块给「营业总收入」、
                    # 另一块只给「营业收入」。用营业总收入覆盖营业收入，反过来不覆盖——
                    # 否则后到的低口径值会把已经正确的营业总收入顶掉，净利却还是总收入口径的，
                    # 合计出一个「营收远小于净利」的荒谬行（工行测试里营收被压成 0.0 亿）。
                    if r_is_total or not rec.get("_rev_total"):
                        rec["rev"] = round(v, 2)
                        rec["_rev_total"] = bool(r_is_total)
                    if not r_is_total:
                        # 记录来源，供人工核对「这家是不是金融口径」
                        rec.setdefault("_rev_src", "营业收入")

        # 本块毛利率的量纲统一判断：整块最大值 <= 1 才认为是小数（0.9118），
        # 否则按百分数。用整块而非单值，才能正确处理「同一块里既有 0.81 又有 91.18」
        # 这种跨盈亏平衡点的组合——那种情况下 0.81 就是 0.81%，不是 81%。
        if gm_raw and max(gm_raw) <= 1.0:
            for row in b["rows"]:
                if ci >= len(row) or yi >= len(row):
                    continue
                m = re.match(r"^(\d{6})", row[ci].strip())
                ym = YEAR_RE.search(row[yi])
                if not m or not ym:
                    continue
                code = m.group(1) + "." + guess_market(m.group(1))
                key = (code, int(ym.group(1)))
                if key in out and out[key].get("gm") is not None:
                    out[key]["gm"] = round(out[key]["gm"] * 100, 2)
    if unknown_units:
        # 不抛错，但必须让人看见：单位没认出来时数字可能差 4–8 个数量级
        warns.append("表头未标注单位、已按「元」换算，请核对原始表头："
                     + "、".join(sorted(unknown_units)))
        unknown_units.clear()
    return out, warns


def guess_market(code):
    """6 位代码 → 交易所。SH: 60/68/90/50/11；BJ: 43/83/87/92；其余 SZ。"""
    if code[:2] in {"60", "68", "90", "50", "11"}:
        return "SH"
    if code[:2] in {"43", "83", "87", "92"}:
        return "BJ"
    return "SZ"


def to_batch(recs, names):
    """(code, year) → {rev,np,gm} 转成 tmp/batch_*.json 的 companies 形状。

    缺年份不许插值：某年 rev 或 np 为 None 就整行不带——merge_v2.py 只取有值年份，
    年份不连续会在 validate.py 里报出来，这比悄悄填一个数更诚实。
    """
    by_code = {}
    for (code, year), rec in recs.items():
        by_code.setdefault(code, []).append((year, rec))

    companies = []
    for code in sorted(by_code):
        rows = sorted(by_code[code])
        # 只保留 rev 与 np 都有值的年份
        years = [{"y": y, "rev": r["rev"], "np": r["np"], "gm": r.get("gm")}
                 for y, r in rows if r.get("rev") is not None and r.get("np") is not None]
        if not years:
            continue
        # 连续性检查：断档要显式记进 note，不能让它静默断开
        gaps = [[a["y"], b["y"]] for a, b in zip(years, years[1:]) if b["y"] != a["y"] + 1]
        companies.append({
            "code": code,
            "name": names.get(code, ""),
            "listed_year": years[0]["y"],
            "years": years,
            "_gaps": gaps,
            "_dropped": [y for y, r in rows
                         if r.get("rev") is None or r.get("np") is None],
        })
    return companies


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", help="原始返回文件（默认 stdin）")
    ap.add_argument("--out", dest="out", help="输出 batch json")
    ap.add_argument("--names", help="代码→名称的 json（可选）")
    ap.add_argument("--expect", help="计划表 json（[{code,name}]），用于核对有没有漏/"
                                    "串号")
    a = ap.parse_args()

    text = Path(a.inp).read_text(encoding="utf-8") if a.inp else sys.stdin.read()
    names = json.loads(Path(a.names).read_text(encoding="utf-8")) if a.names else {}
    recs, unit_warns = gather(text)
    companies = to_batch(recs, names)

    if not companies:
        print("[ERROR] 没解析出任何公司。返回内容可能不是按公司按年份的长表，"
              "或者列名变了——请贴原始表格（含表头）而不是结论。")
        return 1

    warns = list(unit_warns)
    for c in companies:
        if c["_gaps"]:
            warns.append(f"{c['code']} {c['name']} 年份断档 {c['_gaps']}，未插值")
        if c["code"].startswith(("60", "00", "30")) and c["years"] and c["years"][-1]["y"] < 2025:
            warns.append(f"{c['code']} {c['name']} 末年为 {c['years'][-1]['y']}，"
                         f"若未退市则缺 2025 年报")

    if a.expect:
        want = {x["code"] for x in json.loads(Path(a.expect).read_text(encoding="utf-8"))}
        got = {c["code"] for c in companies}
        missing = sorted(want - got)
        extra = sorted(got - want)
        if missing:
            warns.append(f"计划内未取到 {len(missing)} 家：{missing}")
        if extra:
            warns.append(f"计划外多出 {len(extra)} 家：{extra}")

    payload = {"companies": [{k: v for k, v in c.items() if not k.startswith("_")}
                             for c in companies],
               "warns": warns}

    out = json.dumps(payload, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(out + "\n", encoding="utf-8")
        print(f"[OK] {a.out}  {len(companies)} 家 / "
              f"{sum(len(c['years']) for c in companies)} 财年")
    else:
        print(out)
    for w in warns:
        print(f"[WARN] {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
