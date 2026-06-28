# 个股追踪 — 功能设计

> 日期：2026-06-28 | 分支：待创建

---

## 概述

在现有"个股追踪"placeholder 页面上实现真正的个股技术分析功能。
复用宽基指数/行业指数的 `render_ohlcv_section()` 渲染模式，针对个股特征做差异化调整。

## 设计决策

### 1. 配置文件

**新建** `config/watchlist_stocks.txt`

格式跟 `watchlist_industries.txt` 一致——每行一个股票名称，`#` 开头为注释，空行忽略：

```
# 自选个股
天赐材料
石大胜华
恩捷股份
龙蟠科技
璞泰来
杉杉股份
融捷股份
多氟多
鼎盛新材
中钨高新
```

**匹配逻辑**：`DashboardService.get_watchlist_stocks()` 通过 `stock_basic_cache` 表按 `name` 字段匹配，返回 `(ts_code, name, industry)`。未匹配的名称通过 `st.warning()` 报警。

### 2. 控制台改动

**文件**：`dashboard/pages/00_控制台.py`

在"⭐ 自选行业" expander 下方新增"📋 自选个股" expander（默认收起），展示：

- 配置文件路径
- 个股列表表格（#、代码、名称、行业、状态 ✅）
- 未匹配名称警告
- 数据加载时 `ensure_data_loaded` 需确保自选个股的 K 线数据已就绪

### 3. render_ohlcv_section 扩展

**文件**：`dashboard/rendering/index_section.py`

新增 `section_type="stock"`，各 Section 差异如下：

| Section | index | industry | stock |
|---------|:-----:|:--------:|:-----:|
| K线图 + OHLC 数据 | ✅ | ✅ | ✅ |
| K线形态 | ✅ (固定%) | ✅ (固定%) | ✅ **(ATR 双方案)** |
| 均线分析（扣抵） | ✅ | ✅ | ✅ **(MA55/144)** |
| 成交额分析 | ✅ | ✅ | ✅ |
| KD 指标 | ✅ | ✅ | ✅ |
| RSI 指标 | ✅ | ✅ | ✅ |
| BIAS 乖离率 | ✅ | ✅ | ❌ |
| 大市值权重 / 异动股 | — | ✅ | ❌ |
| 权重贡献（领涨/领跌） | ✅ | — | ❌ |

### 4. 个股均线调整

**仅个股**使用不同中长周期：

| 周期 | 指数/行业 | 个股 |
|------|-----------|------|
| 短期 | MA5, MA10, MA20 | MA5, MA10, MA20（不变） |
| 中长期 | MA60, MA120, MA240 | **MA55, MA144**, MA240 |

**涉及函数**：

- `calc_ma(df, periods)` — 已支持自定义 periods，无需改动
- `ma_arrangement(df, medium_long_periods)` — 新增参数，index/industry 传 `[60,120,240]`，stock 传 `[55,144,240]`
- `render_ohlcv_section()` — 根据 `section_type` 选择 `ma_periods`
- `ma_direction()`、`get_ma_role()`、`get_offset_info()` — 按 period 数字走，自动适配

### 5. ATR 双方案（K线形态）

**文件**：`src/marketreview/tools/kline_patterns.py`、`technical.py`

**新增** `calc_atr(df, period=14)` 在 `technical.py` 中。

**方案 1 — 实体强度**（代码已有，WIP→正式启用）：

- `abs(body) / ATR(14)` ≥ 0.5 → 长阳/长阴
- ≥ 0.25 → 中阳/中阴
- < 0.25 → 小阳/小阴

**方案 2 — 影线判定**（新增）：

- 上影线 / ATR(14) ≥ 0.3 → 长上影线
- 下影线 / ATR(14) ≥ 0.3 → 长下影线
- 替代现有「影线 ≥ 实体 × 2」固定比例（仅个股；指数/行业保持不变）

`detect_patterns()` 传入 `obj_type="stock"` + ATR 值即可自动切换。

### 6. 个股追踪页面

**文件**：`dashboard/pages/03_个股追踪.py`（重写替换 placeholder）

结构：

- 无顶部概览卡片，直接进入个股列表
- 每只个股一个 `st.expander`，默认收起（`expanded=False`）
- expander 标题格式：`股票名 (代码) — 行业 | ±涨跌幅% | 状态标记`
  - 状态标记来自 ATR 实体判定：长阳/中阳/小阳/小阴/中阴/长阴
- 展开后调用 `render_ohlcv_section(df, code, name, service, section_type="stock")`

### 7. DashboardService 新增

**文件**：`dashboard/services/dashboard_service.py`

- `get_watchlist_stocks()` — 读取配置、匹配数据库、返回股票列表
- `ensure_data_loaded()` — 在现有数据加载流程中补上自选个股的 K 线数据拉取

---

## 改动文件清单

| 文件 | 操作 | 说明 |
|------|:----:|------|
| `config/watchlist_stocks.txt` | 新建 | 自选个股列表（10只） |
| `dashboard/pages/00_控制台.py` | 改 | 新增自选个股 expander |
| `dashboard/pages/03_个股追踪.py` | 重写 | 替换 placeholder，真实数据渲染 |
| `dashboard/rendering/index_section.py` | 改 | 支持 `section_type="stock"`，差异化 MA/去 BIAS/去权重 |
| `src/marketreview/tools/technical.py` | 改 | 新增 `calc_atr()`，`ma_arrangement()` 支持自定义周期 |
| `src/marketreview/tools/kline_patterns.py` | 改 | ATR 双方案正式启用（实体+影线） |
| `dashboard/services/dashboard_service.py` | 改 | 新增 `get_watchlist_stocks()`，数据加载补上个股 |
