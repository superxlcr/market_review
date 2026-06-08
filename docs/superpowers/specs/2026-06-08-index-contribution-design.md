# 指数权重贡献 — 设计规格书

> 日期：2026-06-08 | 状态：待评审

## 1. 概述

在 Dashboard 指数分析区（上证/创业板）的技术指标下方，新增"权重贡献"区块，展示当日对指数涨跌贡献最大/最小的 Top-5 权重股，帮助快速判断**今天是哪个行业在涨、哪个行业在跌**。

### 1.1 现有基础

- `contribution.py` 已有 `INDEX_WEIGHTS`（硬编码）和 `compute_index_contribution()`，但数据过时、权重未接入 API
- `market_tools.py` 已有 `GetIndexContributionTool` 供 Agent 1 调用
- **Dashboard 当前无贡献展示 UI**

---

## 2. 数据模型

### 2.1 新增表

#### `index_weight_cache` — 指数成分股权重

```sql
CREATE TABLE IF NOT EXISTS index_weight_cache (
    index_code   TEXT    NOT NULL,   -- '000001.SH'
    con_code     TEXT    NOT NULL,   -- '601288.SH'
    weight_date  TEXT    NOT NULL,   -- '20260529'  权重公布日（API 字段原名 trade_date，入库时 rename）
    weight       REAL    NOT NULL,   -- 3.12        权重百分比

    PRIMARY KEY (index_code, con_code, weight_date)
);
```

**数据来源**: `api.index_weight(index_code, trade_date=...)`  
**更新频率**: 月度（指数公司月末公布，次月生效）。同月内 API 返回同一 `weight_date`，缓存命中无需重拉。  
**过期判断**: 缓存的 `weight_date` 所在月份 < 请求 `trade_date` 的上一月 → 拉 API 确认；否则直接返回缓存。

#### `stock_industry_cache` — 股票申万行业分类

```sql
CREATE TABLE IF NOT EXISTS stock_industry_cache (
    ts_code   TEXT PRIMARY KEY,     -- '601288.SH'
    name      TEXT,                  -- '农业银行'
    l1_code   TEXT,                  -- '801780.SI'
    l1_name   TEXT,                  -- '银行'
    l2_code   TEXT,                  -- '801782.SI'
    l2_name   TEXT,                  -- '国有大型银行Ⅱ'
    l3_name   TEXT                   -- '国有大型银行Ⅲ'（存着备查）
);
```

**数据来源**: `api.index_member_all(ts_code=..., is_new='Y')`  
**更新策略**: 行业分类基本不变。缓存命中直接返回，未命中的股票（新上市/首次查询）调 API 补入。无需过期机制。

---

## 3. 数据层（DataProvider 新增方法）

### 3.1 `get_index_weights(index_code, trade_date) -> list[dict]`

```
输入: index_code="000001.SH", trade_date="20260608"

1. 查缓存: SELECT * FROM index_weight_cache
           WHERE index_code=? AND weight_date <= trade_date
           ORDER BY weight_date DESC

2. 过期判断:
   - 取 trade_date 上月末: 20260531
   - 缓存 weight_date="20260529" → "202605" >= "202605" → 有效 → 返回缓存

   (7月场景) trade_date="20260701" → 上月末 "20260630"
   - 缓存 weight_date="20260529" → "202605" < "202606" → 过期
   - 调 API: api.index_weight(index_code, trade_date="20260701")
   - API 返回 weight_date="20260630" → 写缓存 → 返回

3. 返回 [{con_code, weight, weight_date}, ...]
```

### 3.2 `get_daily_batch(codes, end_date) -> dict[str, dict]`

```
输入: codes=["601288.SH", "601857.SH", ...], end_date="20260608"

1. 逐个查 tushare_cache，区分命中/缺失
2. 缺失或不足的，调 api.daily(trade_date=end_date) 一次拉全市场
3. 写入 tushare_cache
4. 返回 {con_code: {close, pre_close, change_pct}, ...}
```

**注意**: 遵循 DataProvider 原则——外部只传入日期，内部处理缓存和 API 隔离。

### 3.3 `get_stock_industries(codes) -> dict[str, dict]`

```
输入: codes=["601288.SH", "601857.SH", ...]

1. 查 stock_industry_cache，区分命中/缺失
2. 缺失的调 api.index_member_all(ts_code=code)
3. 写缓存
4. 返回 {ts_code: {name, l1_code, l1_name, l2_name}, ...}
```

---

## 4. 业务层（contribution.py）

### 4.1 核心公式

```python
# 成分股 i 对指数的贡献点数
# 公式推导:
#   指数涨跌幅(%) = Σ(权重_小数 × 个股涨跌幅_小数)
#   贡献点数 = 权重_小数 × 个股涨跌幅_小数 × 指数收盘价
#            = (权重% / 100) × (涨跌幅% / 100) × 指数收盘价
#            = 权重% × 涨跌幅% × 指数收盘价 / 10000
contrib_i = weight_pct * chg_pct * index_close / 10000
```

### 4.2 `build_index_contribution(index_code, trade_date, dp) -> dict`

```
输入: index_code="000001.SH", trade_date="20260608"

步骤:
1. idx = dp.get_daily(index_code, end_date=trade_date, lookback_days=2)
   → close, pre_close, chg_pts, chg_pct(%)

2. weights = dp.get_index_weights(index_code, trade_date)

3. prices = dp.get_daily_batch([w.con_code for w in weights], trade_date)

4. 逐只计算贡献:
   contrib = w.weight * p.chg_pct * idx.close / 10000
   排序，取前5（领涨）和后5（领跌）

5. top10_codes = [gainer codes] + [loser codes]
   industries = dp.get_stock_industries(top10_codes)

6. 组装返回:
   {
     "index": {close, pre_close, chg_pts, chg_pct},
     "gainers": [{code, name, industry, weight, chg_pct, contrib}],
     "losers":  [{code, name, industry, weight, chg_pct, contrib}],
   }
```

### 4.3 行业显示逻辑（TODO 标记）

```python
# TODO: 下面这些 L1 行业直接用 L1 名，其余情况用 L2 名
# 后续可根据实际观察增减
L1_OVERRIDE_L1 = {"801780.SI"}  # 银行 → L1 "银行" 已足够区分

def pick_industry_label(l1_code, l1_name, l2_name):
    """选择展示用的行业标签（L1 或 L2）。"""
    if l1_code in L1_OVERRIDE_L1:
        return l1_name
    return l2_name
```

---

## 5. Dashboard 展示层

### 5.1 位置

指数 Section 内，技术指标（KD/RSI/BIAS）下方，st.divider 隔开。

### 5.2 布局

左右两张表并排（`st.columns(2)`）：

**左表 — 🔥 领涨 Top 5**（红色标题）
| 代码 | 名称 | 行业 | 权重% | 涨幅% | 贡献 |
|---|---|---|---|---|---|
| 601288.SH | 农业银行 | 银行 | 3.12 | <span style="color:#e53935">+3.30</span> | <span style="color:#e53935">+4.07</span> |

**右表 — ❄️ 领跌 Top 5**（绿色标题）
| 代码 | 名称 | 行业 | 权重% | 跌幅% | 贡献 |
|---|---|---|---|---|---|
| 601138.SH | 工业富联 | 消费电子 | 2.25 | <span style="color:#43a047">-4.83</span> | <span style="color:#43a047">-4.31</span> |

颜色：红=涨=看多，绿=跌=看空（遵循 [[color-convention]]）。

### 5.3 数据流

```
render_index_section(service, code, name, end_date)
  │
  ├─ ... 现有 K线/均线/指标 ...
  │
  └─ contribution = service.get_index_contribution(code, end_date)
       → DashboardService.get_index_contribution()
         → build_index_contribution(code, trade_date, self._dp)
           → dp.get_daily(index_code, ...)
           → dp.get_index_weights(index_code, trade_date)
           → dp.get_daily_batch(all_codes, trade_date)
           → dp.get_stock_industries(top10_codes)
     │
     └─ 渲染两张表
```

---

## 6. 文件变更清单

| 文件 | 变更类型 | 内容 |
|---|---|---|
| `src/marketreview/data/data_provider.py` | 新增方法 | `get_index_weights()`, `get_daily_batch()`, `get_stock_industries()` |
| `src/marketreview/data/cache_manager.py` | 新增方法 | `index_weight` 表 CRUD, `stock_industry` 表 CRUD |
| `src/marketreview/data/schema.sql` | 新增 DDL | `index_weight_cache`, `stock_industry_cache` |
| `src/marketreview/tools/contribution.py` | 重写 | 替换硬编码，改为 `build_index_contribution()` |
| `src/marketreview/tools/market_tools.py` | 适配 | `GetIndexContributionTool` 使用新接口 |
| `dashboard/services/dashboard_service.py` | 新增方法 | `get_index_contribution()` |
| `dashboard/app.py` | 新增渲染 | `render_index_section()` 中加贡献表格 |

---

## 7. TODO / 后续

- [ ] 行业 L1/L2 切换逻辑（接入 `L1_OVERRIDE_L1` 集合），后续按实际效果调整
- [ ] `index_weight` 的积分要求（2000+），确保生产 token 够用
- [ ] 权重为非交易日（如月末恰逢周末）时的容错
