# 如何新增一家公司

整条链路只有三步：取数 → 写一段 JSON → 重新构建。单家耗时约 10 分钟。

## 1. 取数

```bash
# 在 CodeBuddy 里调用同花顺数据（MCP），三组查询覆盖一家公司
1) 上市日期与主营：
   get_stock_summary("XX公司 上市日期 所属行业 主营业务")

2) 上市以来年度序列（分两段取，避免单次返回过长）：
   get_security_indicators(market="A股",
     query="XX公司 上市以来 各年度 营业收入 归母净利润 销售毛利率")
   get_security_indicators(market="A股",
     query="XX公司 2013年至2025年 各年度 营业收入 归母净利润 销售毛利率")

3) 口径与事件：
   search_notice(query="XX公司 年报 分部收入 收入确认", ...)
   search_news(query="XX公司 业绩 下滑 竞争", ...)
```

**只取 12 月 31 日那一行**（其余为季报累计值）。金额原始单位为元，除以 1e8 换成亿元，保留 1 位小数。

## 2. 写数据

在 `data/companies.json` 的 `companies` 数组里追加一段：

```json
{
  "code": "000001.SZ",
  "name": "平安银行",
  "industry": "银行",
  "sub": "股份制银行",
  "listed": "1991-04-03",
  "coverage": [1991, 2025],
  "verdict": "一句话结论：必须可证伪，写清什么情况下失效",
  "engine": {
    "main": "E6 支付金融（息差 + 手续费）",
    "desc": "这门生意靠什么收钱，收入确认方式是什么",
    "formula": "生息资产 × 净息差 + AUM × 费率 − 信用成本"
  },
  "mix": [["利息净收入", 70], ["手续费", 20], ["其他", 10]],
  "moat": "定价权来自哪，证据是什么",
  "payer": "开票方 → 决策方 → 最终付款方",
  "shift": "上市以来的三到四个阶段，每段一个转折点",
  "flags": ["已触发的异常", "!未触发的健康项（感叹号开头显示为正向）"],
  "years": [
    {"y": 1991, "rev": 3.2, "np": 0.4, "gm": null}
  ],
  "note": "口径说明：哪些数字是估算、哪年发生重述"
}
```

字段规则：

| 字段 | 约束 |
|---|---|
| `coverage` | 必须等于 `years` 的首末年 |
| `years` | 年份连续，无缺年；`rev` > 0；银行 `gm` 填 `null` |
| `mix` | 合计 99–101，按引擎而非财报分部 |
| `verdict` | ≥30 字，含失效条件 |
| `flags` | 最多 4 条，`!` 开头表示正向项 |

## 3. 构建与校验

```bash
python3 scripts/validate.py     # 必须 0 错误
python3 scripts/build_site.py   # 生成 index.html 与拆分文件
```

提交时**只带 `data/companies.json`**（唯一主数据源）。`data/companies/<code>.json` 与 `index.html` 都是 `build_site.py` 生成的构建产物，已在 `.gitignore` 中排除，由 CI（Pages 工作流）或本地构建生成，**不入库**。

## 常见错误

| 现象 | 原因 |
|---|---|
| 校验报 `coverage 与数据区间不一致` | 改了 `years` 忘了改 `coverage` |
| 页面曲线中间断掉 | 某年缺行，`years` 不连续 |
| CAGR 显示 `—` | 首年或末年营收 ≤0，或年份跨度 ≤0 |
| 五粮液式跳变 | 公司做过会计差错更正，需在 `note` 写明并考虑断开序列 |
