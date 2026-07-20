# ETF/行业指数 买点胜率测试 — 设计文档

**日期**：2026-07-20
**状态**：设计待 review
**关联**：复用现有个股买点胜率引擎（`src/marketreview/winrate/` + `tools/buy_points.py`）

---

## 1. 背景与目标

### 1.1 用户背景

用户从**个股右侧重仓突破**转向 **ETF 左侧慢慢抄底多个 + 赛马等市场走出来 + 浮盈加仓**。原因：个股风险大，ETF 波动更小、更适合左侧分批。

### 1.2 本次要解决的核心问题

**第一版聚焦**：ETF/行业指数上，哪个买点信号靠谱？

- 形态同现有个股买点胜率测试（`06_买点胜率.py`）：给定一批标的，测各买点的胜率/盈亏比，横向对比。
- 标的池从"全市场个股"换成"中证行业/主题指数"。
- **不在本次范围**：分批建仓 + 浮盈加仓的完整策略模拟器。那是第二阶段，本次只做"买点对比"，为将来的策略选买点提供依据。

### 1.3 核心架构决策：方案 B（参数化复用）

对比三个方案后选定 **B**：

| 方案 | 做法 | 取舍 |
|------|------|------|
| A. 独立引擎 | copy 整套 `winrate/` → `winrate_etf/` | ❌ 违反 CLAUDE.md "复用别重写"规则，~600 行重复 |
| **B. 参数化复用** | **引擎不动，加 `asset_class` 维度；买点/波段分析零改动；模拟器参数化留分叉口；配置分两份** | ✅ 逻辑零重复，演进平滑，合规 |
| C. 策略插件 | 抽进场/止损/判赢策略对象 | ❌ 过度工程，YAGNI |

**原则一句话**：逻辑复用、配置隔离、模拟器参数化留分叉口。等真有逻辑分叉（非数值分叉）再 fork。

### 1.4 复用诊断（三层）

| 层 | 结论 |
|----|------|
| 波段分析 / 买点 checker | **完全复用，不 copy**。位置型买点逻辑与标的无关。 |
| 交易模拟器 `trade_sim` | **参数化，不 copy 全文**。现在差异只是数值（阈值%）+ 涨跌停规则。给 `simulate_trade` 加 `asset_class`，将来分叉点（收盘价进场）用参数预留。 |
| 扫描编排 `scan_engine` | **复用骨架，换数据源 + 标的池来源**。walk-forward 循环、多线程、持仓闸与标的无关。 |
| 配置 | **完全 copy 一份**。`winrate_config_etf.txt` 独立于 `winrate_config.txt`。 |

---

## 2. 数据层设计（第 1 节，已与用户对数据验证后锁定）

### 2.1 标的池来源

**全量中证指数拉取 → 过滤 → 缓存为可回测清单**。不再用独立 txt 文件手列标的。

数据源：`pro.index_basic(market='CSI')`（已验证返回 8000 条）。

### 2.2 过滤规则（6 条，已用真实数据验证：8000 → 674）

```python
# 过滤后：行业指数 185 + 主题指数 489 = 674 个可回测指数
# (数量随 index_basic 当日返回动态变化，674 为 2026-07-20 快照)

# 1. 只留主题/行业两类（砍债券2958/期货/基金/多资产/策略/风格/规模/综合）
df = df[df['category'].isin(['主题指数', '行业指数'])]

# 2. ts_code 不含币种后缀（砍 CNY/HKD/USD/EUR/JPY 计价衍生版）
df = df[~df['ts_code'].str.contains(r'(?:CNY|HKD|USD|EUR|JPY)', regex=True)]

# 3. name 不含全收益/净收益/(全)/(净) + 币种字样
#    (币种字样补 name 侧：ts_code 规则2抓不到 name 里带 USD/港元/人民币 的 54 个漏网变体)
df = df[~df['name'].str.contains(r'全收益|净收益|（全）|(?:全)|(?:净)|（净）|USD|CNY|HKD|港元|人民币|美元|港币', na=False, regex=True)]

# 4. name 不含港股/海外/跨市 + 新三板 + 港股通系列（A 股账户买不了/无对应ETF）
#    (三板=新三板, H300/HKT/港股通=港股通系列, 成分股是港股非A股主板)
df = df[~df['name'].str.contains(r'港股|香港|HK|SHS|海外|沪港|深港|沪通|深通|港通|AH|三板|H300|HKT|港股通', na=False, regex=True)]

# 5. name 不以纯数字规模前缀开头 + 不含企业属性/产业链/地域关键词
#    (修订: 原规则按"中证|上证|深证|国证"前缀一刀切，误杀了"中证软件/中证钢铁/上证光伏"等
#     正经行业指数；改为只砍纯数字规模前缀 + 企业属性/产业链/地域关键词)
df = df[~df['name'].str.match(r'^(?:1000|500|300|180|380|800|700|200|50|100)', na=False)]
df = df[~df['name'].str.contains(r'央企|民企|国企|地企|上游|中游|下游|长三角|珠三角|京津冀|湾区|城镇', na=False, regex=True)]

# 6. name 不含策略型残留（红利/低波/动量/价值/成长结尾/收结尾）
df = df[~df['name'].str.contains(r'收$|红利|分红|低波|动量|高贝|价值|成长$', na=False, regex=True)]
```

**验证结果**：用户的 4 个示例指数 + 中证系列行业指数全部保留——
- `931719.CSI` CS电池（主题）✅
- `931152.CSI` CS创新药（主题）✅
- `930851.CSI` 云计算（主题）✅
- `H30199.CSI` 电力指数（行业）✅
- `930601.CSI` 中证软件 ✅（修订后保留，原规则误杀）
- `930606.CSI` 中证钢铁 ✅（修订后保留，原规则误杀）

**已砍掉的"看着像行业但不是A股主板"系列**：
- `三板医药`/`三板消费`等 9 个——新三板指数，无对应 ETF
- `H300休闲`/`H300医药`等 162 个——港股通系列，成分股是港股

**完整名单**：`csi_index_pool_kept.txt`（674 个保留）+ `csi_index_pool_removed.txt`（2689 个被过滤）已导出到项目根目录，供用户 review。

**已知小尾巴（不处理）**：674 个里零星几个噪音（`中证新兴`/`中证龙头`等非纯行业、`证券时报ESG百强`等定制指数）。跑回测时 `n < 60` 自然淘汰，不值得为它们加规则。

### 2.3 指数清单缓存

新增表 `csi_index_pool`：

```sql
CREATE TABLE IF NOT EXISTS csi_index_pool (
    ts_code    TEXT PRIMARY KEY,   -- 指数代码 (931719.CSI ...)
    name       TEXT NOT NULL,      -- 简称
    category   TEXT NOT NULL,      -- 主题指数 / 行业指数
    list_date  TEXT                -- 发布日期 YYYYMMDD
);
```

加载方式：lazy-load，仿 `_ensure_industry_classify` 模式——首次访问时拉 `index_basic(market='CSI')` + 过滤 + upsert，之后读缓存。提供 `has_csi_pool()` 完整性检查。

### 2.4 K 线抓取

选中哪些指数就抓哪些，走 `index_daily`（已验证 4 个示例均能取到 OHLCV）。

- **复用现有抓取/缓存路径**：存进 `tushare_cache` 表，`asset_type='index'`，`adj_factor=1.0`。不新建表、不新建接口，复用 `upsert_daily_bulk` + `_normalize_index_batch`。
- 新增 `DataProvider.ensure_index_pool_loaded(codes, start, end)` 方法，内部调 `index_daily`，逻辑仿现有 `_ensure_indices_loaded`（覆盖检查 + 增量抓取）。
- **不复用 `_TRACKED_INDICES`**——那是 dashboard 市场全景页的宽基指数，与回测标的池是两回事。

### 2.5 复权安全（关键）

**指数不需要前复权**——指数发布方在成分股除权日调整除数，指数本身连续；tushare `index_daily` 返回的就是连续点位，`adj_factor=1.0`。

**两个真坑及对策**：
1. **全收益 vs 价格指数**：全收益含分红再投，点位偏高，与 ETF 脱节。→ 过滤规则 #3 排除。
2. **编制规则变更**：极少数指数中途改编制方法导致点位跳跃，tushare 不标记。→ 第一版不处理（罕见），记为已知限制。

**代码层面对策**：`scan_engine.prepare_klines` 按 `asset_class` 分流——
- `stock`：照旧调 `raw_to_qfq`（个股需前复权）
- `index`：**不调** `raw_to_qfq`，直接用 raw（指数 adj_factor=1.0、本身连续；调了是 no-op 但语义误导）

这是方案 B "参数化 fork" 的落点之一。

### 2.6 涨跌停规则

`trade_sim.board_limit_pct(code)` 现按个股代码判（300/301/688→20%，8/4北交所→30%，其余10%）。

**ETF/指数涨跌停**：多数行业指数无涨跌停（指数本身不交易），但 ETF 有。本次回测用**指数 K 线**，指数无涨跌停限制。

**对策**：`board_limit_pct` 按 `asset_class` 分流——
- `stock`：现有逻辑
- `index`：返回一个足够大的值（如 1.0 = 100%），等价于"不限制条件单可达性"。

> 注：现有引擎用涨跌停做"条件单可达性"检查（目标价须落在次日涨跌停幅度内）。指数无涨跌停，此检查对指数恒通过，语义正确。

---

## 3. 配置层设计（第 2 节）

### 3.1 配置完全独立

用户明确决定：**ETF 买点测试配置完全独立于个股，先照抄原值，后面再调数值**。

新增 `config/winrate_config_etf.txt`，内容照抄 `winrate_config.txt`，但：
- **去掉市值过滤**（指数无市值概念）：移除 `市值下限亿` / `市值上限亿` 行
- **保留**：判赢/止盈、止损、进场、扫描范围、均线排列过滤、上市最短天数（指数用"发布最短天数"）、并发数、调试标的

### 3.2 WinrateConfig 扩展

`WinrateConfig` dataclass 新增字段：

```python
asset_class: str = "stock"   # "stock" | "index"
index_pool: list[str] = field(default_factory=list)  # ETF 模式下选中的指数 ts_code 列表
```

- `parse_winrate_config` 加一个 `asset_class` 入参，决定读哪个 txt、走哪套默认值。
- `mv_min_yi` / `mv_max_yi` 在 `asset_class="index"` 时被忽略（`passes_all` 按 `asset_class` 跳过市值过滤分支）。

### 3.3 买点集合

ETF 版可测买点**独立定义**为 `ETF_BUY_POINTS`（见 §5.2，共 12 个：3 个非 MA + 9 个 MA 变体），不依赖个股版 `ALL_BUY_POINTS`——因为 MA 家族在个股版被 `disabled`，`ALL_BUY_POINTS` 会过滤掉它们，而 ETF 版要测全部 9 个 MA 变体。`BUY_POINT_STAGE`（stage 真相源）仍共用、不改动，个股版不受影响。ETF 页面绕过 stage 门槛，直接把买点名传给 `detect_buy_points`。

---

## 4. 交易模拟器设计（第 3 节）

### 4.1 参数化，不 copy 全文

`trade_sim.simulate_trade` 与 `board_limit_pct` 加 `asset_class` 维度，按 §2.5 / §2.6 分流。**核心逻辑（MFP 判赢 / 条件单进场 / 止盈止损）不动。**

### 4.2 进场方式：第一版保留条件单，预留收盘价进场

用户决定：**第一版保留条件单进场，但预留"收盘价进场"作为可切换维度**（将来加）。

设计：`WinrateConfig` 新增字段 `entry_mode: str = "limit"`（`"limit"`=条件单等回踩 | `"close"`=收盘价直接追）。`simulate_trade` 按 `entry_mode` 分支：
- `"limit"`：现有逻辑（次日开盘/回踩成交，追高上限 102%）
- `"close"`：信号日当日收盘价成交（T+1 出场从次日起）——第一版只留接口、不实现，spec 标注 TODO

> 留接口不实现，避免第一版过度复杂；等用户跑完第一轮、确认要收盘价进场再补。

### 4.3 判赢/止盈逻辑

**完全复用现有**（用户决定）：MFP 盘中浮盈达阈值=胜，大胜利止盈，小胜利回落止盈，时间止损。数值照抄（判赢10%/大胜20%/小胜5%/时间13天），跑出第一版分布后再调。

### 4.4 止损

**完全复用现有**（用户决定）：空间止损 5%、ATR 止损（默认关）、时间止损 13 天。数值照抄，跑完再调。

> 用户原话："etf 整体止盈跟止损都跟原来个股不太一样"——这是预期中的将来分叉。第一版数值照抄，把"分叉"限制在数值层（配置隔离已解决），不提前在代码层 fork。

---

## 5. 买点适配设计（第 4 节）

### 5.1 四个买点，分两类

| 买点 | 类型 | ETF 上怎么处理 |
|------|------|----------------|
| 回调一半 | 位置型 | **完全复用** `HalfRetraceChecker`。注意：个股版 `pullback_days≥13` 对 ETF 可能偏严（ETF 波动小、波段短），第一版先复用原值，跑完看信号量再调。 |
| 波段50% | 位置型 | **完全复用** `Band50Checker`。同上。 |
| 均线支撑(MA) | 位置型 | **需先重新启用**。见 §5.2 —— 个股版 MA 家族全部 `disabled`（胜率仅比随机高 0.6~3.5pp），ETF 版要测必须先在 ETF 范围内重新启用。 |
| 量价节点 | 事件型 | **改良，不弃用**（用户判断：ETF 上"资金合力"有道理）。见 §5.3。 |

### 5.2 均线支撑(MA) — ETF 版需重新启用

**现状冲突**：winrate 侧 `BUY_POINT_STAGE`（[config.py:19-28](src/marketreview/winrate/config.py#L19-L28)）把 MA 家族**全部 `disabled`**——MA20/55/60/120/144/240 + 扣抵量/5日均量/无量 共 9 个变体，原因是"胜率仅比随机高 0.6~3.5pp，无实用价值"（在**个股**上测的）。`ALL_BUY_POINTS` 过滤掉 disabled，所以页面当前**选不到任何 MA 买点**。

**用户假设**：ETF 跟踪指数、均线更规矩，MA 支撑在 ETF 上可能比个股更有效。要验证这个假设，必须先在 ETF 范围内重新启用 MA。

**设计选择**：用户决定 **MA 家族全部 9 个变体都测**（不只 3 个代表性周期）。

9 个变体（已在 `_NAME_MAP` 中，checker 可用）：

| 买点名 | periods | vol_mode |
|--------|---------|----------|
| MA20支撑 | [20] | today |
| MA55支撑 | [55] | today |
| MA60支撑 | [60] | today |
| MA120支撑 | [120] | today |
| MA144支撑 | [144] | today |
| MA240支撑 | [240] | today |
| 扣抵量均线支撑 | [60,120,240] | today |
| 5日均量均线支撑 | [60,120,240] | avg5 |
| 无量均线支撑 | [60,120,240] | none |

**实现方式**：不污染个股版的 `BUY_POINT_STAGE`。ETF 页面的买点可选列表**独立定义**：

```python
ETF_BUY_POINTS = [
    "回调一半", "波段50%", "量价节点",
    "MA20支撑", "MA55支撑", "MA60支撑", "MA120支撑", "MA144支撑", "MA240支撑",
    "扣抵量均线支撑", "5日均量均线支撑", "无量均线支撑",
]
```

不依赖 `ALL_BUY_POINTS`（它会过滤掉 disabled 的 MA）。`detect_buy_points` 本来就按名字查 `_NAME_MAP`，这些 MA 名字已在表中、checker 可用，只是 stage 门槛挡住了——ETF 页面绕过 stage 门槛直接传名字即可。

> 这是对 §3.3 "买点状态单一真相源共用" 的修正：**stage 真相源仍共用**（个股版不受影响），但 **ETF 版的可选买点列表独立**，绕过 disabled 门槛。`detect_buy_points` / checker 层零改动。

### 5.3 量价节点 ETF 改良版

**个股版逻辑**（`VolPriceNodeChecker`）：放量拉升（close[k]/close[k-1]>1.02 且 amount[k]/amount[k-1]>1.2）= 大资金进场，成本=两日最低，买拉回到成本×1.04。

**ETF 语境差异**：ETF 无"主力建仓"一说，放量更多是申赎/套利驱动。但**放量拉升反映板块资金关注度骤升**这个信号逻辑成立——用户判断保留。

**第一版处理**：先**完全复用** `VolPriceNodeChecker` 跑一轮，看 ETF 上量价节点的胜率/盈亏比。**不在第一版改逻辑**——先有数据再决定怎么改。spec 标注：量价节点改良是第二阶段任务，依据是第一版跑出来的 ETF 量价节点胜率分布。

> 理由：用户说"改一下"，但具体怎么改现在没有数据支撑。先用原逻辑跑，拿到 ETF 量价节点胜率/盈亏比后，对比其他三个位置型买点，再决定改良方向（可能是调 PRICE_RATIO/VOL_RATIO 阈值，也可能是换信号定义）。YAGNI——不提前猜。

### 5.3 买点检测入口

`buypoint_defs.detect_buy_points` 完全复用，不改动。它接收 `selected: list[str]` 买点名，ETF 页面传入四个买点名即可。checker 内部不感知标的类型——这正是"位置型买点与标的无关"的体现。

---

## 6. 扫描引擎设计（第 5 节）

### 6.1 复用骨架，换两处

`scan_engine.scan_stock` 与 `run_scan` 大部分复用。按 `asset_class` 换两处：

1. **数据源**：`scan_stock` 的 `prepare_klines` 按 §2.5 分流（index 不 qfq）。
2. **标的池来源**（`run_scan`）：
   - `stock`：现有逻辑（`get_stock_basic` → 过滤 is_st）
   - `index`：从 `cfg.index_pool`（UI 选中的指数列表）取，**无 is_st 过滤**（指数无 ST）

### 6.2 过滤器分流

`filters.passes_all` 按 `asset_class` 分流：
- `stock`：现有全部过滤器（均线排列、市值、行业白名单、上市天数）
- `index`：只保留**均线排列过滤** + **发布最短天数**；跳过市值、行业白名单（指数本身就是行业）

### 6.3 并发与性能

790 个指数全选时，单指数 K 线抓取 + 回测。并发数复用配置（默认 1）。预期比个股全市场（~5000只）快——标的数少 6 倍。

### 6.4 数据准备门禁

仿个股版 `prepare_winrate_data` + `check_winrate_coverage`，新增 ETF 版：
- `prepare_winrate_data_etf(start, end, index_pool)`：抓取选中指数的 K 线
- `check_winrate_coverage_etf(start, end)`：校验指数 K 线覆盖

页面 UI 仿个股版"数据准备"按钮 + 就绪状态显示。

---

## 7. 页面设计（第 6 节）

### 7.1 新增页面

新增 `dashboard/pages/07_ETF买点胜率.py`（仿 `06_买点胜率.py`）。**不改动 `06`**——个股版保持独立。

### 7.2 页面结构

```
🎯 ETF/行业指数 买点胜率回测  ｜ AI vX.Y.Z

[配置区]
  买点(多选): 回调一半 / 波段50% / 量价节点 + MA家族9个变体
  均线排列过滤 / 时间止损天数 / 并发数
  指数池(多选): 从 csi_index_pool 缓存选，默认全选 790 个
  开始日期 / 调试标的(单指数)

[数据准备]
  📦 数据准备按钮 + 就绪状态（覆盖检查）

[运行扫描]
  ▶ 运行扫描（数据就绪后启用）

[结果]
  📊 买点对比汇总表（胜率/大胜利率/止损率/期望收益）
  每买点独立区块（触发次数/大胜/小胜/止损/亏损）
  明细存 CSV（每买点一个）
```

### 7.3 配置区差异（vs 个股版）

| 项 | 个股版 06 | ETF版 07 |
|----|-----------|----------|
| 买点 | ALL_BUY_POINTS（含MA家族等） | ETF_BUY_POINTS 12个（3非MA + 9 MA变体） |
| 市值过滤 | 有 | **无** |
| 行业白名单 | 有 | **无**（换成指数池多选） |
| 标的池 | 全市场非ST | 选中指数 |
| 调试标的 | 个股下拉 | 指数下拉 |

---

## 8. 改动文件清单

| 文件 | 改动 | 新增/改 |
|------|------|---------|
| `src/marketreview/data/schema.sql` | 新增 `csi_index_pool` 表 | 新增 |
| `src/marketreview/data/cache_manager.py` | `csi_index_pool` 读写方法 + `has_csi_pool()` | 新增方法 |
| `src/marketreview/data/data_provider.py` | `_ensure_csi_pool()` + `ensure_index_pool_loaded()` | 新增方法 |
| `src/marketreview/winrate/config.py` | `WinrateConfig` 加 `asset_class`/`index_pool`/`entry_mode`；`parse_winrate_config` 加 `asset_class` 入参 | 改 |
| `src/marketreview/winrate/filters.py` | `passes_all` 按 `asset_class` 分流 | 改 |
| `src/marketreview/winrate/trade_sim.py` | `simulate_trade`/`board_limit_pct` 加 `asset_class`；`entry_mode` 预留 | 改 |
| `src/marketreview/winrate/scan_engine.py` | `prepare_klines` 按 `asset_class` 分流；`run_scan` 按 `asset_class` 选标的池 | 改 |
| `config/winrate_config_etf.txt` | 新增配置文件（照抄个股版，去市值） | 新增 |
| `dashboard/services/dashboard_service.py` | `prepare_winrate_data_etf` + `check_winrate_coverage_etf` + `run_winrate_scan_etf` | 新增方法 |
| `dashboard/pages/07_ETF买点胜率.py` | 新页面 | 新增 |

**不改**：`tools/buy_points.py`、`tools/band_analysis.py`、`winrate/buypoint_defs.py`（买点层零改动，方案 B 核心）、`dashboard/pages/06_买点胜率.py`（个股版独立）。

---

## 9. 不在本次范围（YAGNI）

- 分批建仓 + 浮盈加仓的完整策略模拟器（第二阶段）
- `entry_mode="close"` 收盘价进场实现（预留接口，第一版不实现）
- 量价节点 ETF 改良逻辑（先跑原版看数据再改）
- 指数编制规则变更导致的点位跳跃处理（罕见，已知限制）
- ETF 本身 K 线回测（`fund_daily`）——第一版只用底层指数
- 指数权重/成分贡献分析（`index_weight`）——将来可加，本次不需要

---

## 10. 验证计划

1. **数据层**：`_ensure_csi_pool()` 跑通，缓存 790 个指数；4 个示例指数 K 线能取到。
2. **配置层**：`parse_winrate_config(path, asset_class="index")` 正确读 ETF 配置、忽略市值。
3. **模拟器**：单指数（如 `931152.CSI`）调试模式跑通，`asset_class="index"` 时跳过 qfq、涨跌停不限制。
4. **买点**：4 个买点在单指数上都能触发（或确认信号量合理）。
5. **页面**：全流程跑通——数据准备 → 运行扫描 → 结果展示。先单指数验证，再小批量，最后全量 790。
6. **回归**：个股版 `06_买点胜率.py` 不受影响（`asset_class` 默认 `"stock"`，走原路径）。

---

## 11. 待 review 的开放问题

以下在设计中已做选择，但标注出来供 review 时确认：

1. **`entry_mode="close"` 第一版只留接口不实现**——✅ 用户接受
2. **量价节点第一版完全复用、不改逻辑**——✅ 用户接受
3. **过滤规则的 6 条**——✅ 用户确认（完整名单已导出 `csi_index_pool_kept.txt` / `csi_index_pool_removed.txt` 供核对；规则3 补 name 币种过滤，727 个保留）
4. **新页面编号 `07`**——✅ 用户确认
5. **MA 买点第一轮启用哪几个周期**——✅ 用户决定全部 9 个变体都测（见 §5.2）
