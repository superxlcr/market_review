# 战法回测引擎 — 设计文档

> 创建日期: 2026-06-26
> 分支: feature/backtest-engine

## 1. 概述

在 Dashboard 中新增"战法回测"页面，让用户可以配置股票池+策略，对日线级别买卖信号进行回测，统计胜率、盈亏等指标。

核心原则：
- 复用现有 `DataProvider` 数据层，不新建数据库
- 策略层通过抽象接口定义，每次新战法只需实现一个类
- 通用交易规则（T+1、空间止损、仓位计算）在引擎层统一处理

---

## 2. 文件结构

```
config/
├── backtest_pools.txt              # 股票池配置
├── backtest_strategies.txt         # 策略参数配置
└── watchlist_industries.txt        # (已有)

src/marketreview/backtest/
├── __init__.py
├── engine.py                       # 回测引擎（日期遍历、撮合、持仓管理）
├── strategy_base.py                # 战法抽象接口
├── position.py                     # 持仓状态机
├── broker.py                       # 虚拟券商（T+1、仓位、资金管理）
├── reporter.py                     # 统计报表
└── strategies/
    ├── __init__.py
    ├── ma60_breakthrough.py        # 战法1: 突破+拉回MA60买入
    └── ma60_pullback_only.py       # 战法2: 仅拉回MA60买入

dashboard/pages/
└── 04_战法回测.py                  # 新增 Streamlit 页面

dashboard/app.py                    # 导航栏新增一项
```

---

## 3. 配置文件

### 3.1 `config/backtest_pools.txt` — 股票池

```
# 格式: [池名]
#       股票名 entry_date exit_date
# entry_date: 此日起可买入
# exit_date: 此日后不可买入（now = 最新交易日）

[电子元件池]
顺络电子 20260210 20260415
中钨高新 20260210 now

[白马池]
贵州茅台 20260301 now
平安银行 20260210 now
```

解析规则:
- 以 `[名字]` 开头的行为池名称
- 池名之后的每行: `股票名 entry_date exit_date`，以空格分隔
- `now` → 运行时替换为最新交易日
- 空行忽略
- 股票名通过 `stock_basic_cache` 表解析为 ts_code（如 `贵州茅台` → `600519.SH`）

### 3.2 `config/backtest_strategies.txt` — 策略参数

```
# 格式: 策略名 战法名 仓位% 空间止损%
# 空间止损%: 盘中触及即卖出，当日未止次日开盘卖

MA60_突破拉回_3止损 ma60_breakthrough 20 3
MA60_突破拉回_5止损 ma60_breakthrough 20 5
MA60_仅拉回_5止损 ma60_pullback_only 20 5
```

解析规则:
- 每行: `策略名 战法类名 仓位% 空间止损%`
- `#` 开头为注释
- 空行忽略

---

## 4. 核心概念

### 4.1 两层止损

| 层级 | 名称 | 来源 | 规则 |
|------|------|------|------|
| 通用层 | 空间止损 | 配置文件 `空间止损%` | 盘中触及止损价→立即卖出；当日未能止损→次日开盘卖出。卖出后当日出现买入信号可以再买入 |
| 战法层 | 战法止损/止盈 | 各策略类自行实现 | 如 MA60 战法的三级浮盈回落规则、跌破 MA60 卖出等 |

### 4.2 T+1 约束

引擎层统一处理: 买入后次日才能卖出。买入不受此限（卖出当日出现买入信号可再买入）。

### 4.3 仓位计算

- 总资金固定（引擎内部常量，如 100 万）
- 每次买入 = 总资金 × 仓位%
- 盈亏 = (卖出均价 - 买入均价) / 买入均价 × 仓位%
- 买入时从可用现金扣除，卖出时加回

### 4.4 股票发现窗口

每只股票有独立的 `entry_date ~ exit_date`:
- 只有在窗口内的日期才能**新开仓**买入该股票
- 已持仓的股票，即使超出 exit_date 仍可持有和卖出
- 超出 exit_date 且无持仓 → 不再产生买入信号

### 4.5 信号未成交

当买入信号触发但因已持仓或不在发现窗口内无法买入时，在交易明细中记录为"信号未成交"，混排在正常的买入/卖出记录之间。

---

## 5. 策略接口

### 5.1 BaseStrategy（抽象基类）

```python
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Optional

@dataclass
class DayContext:
    """单日上下文 — 传给策略的完整信息"""
    date: str                          # YYYYMMDD
    symbol: str                        # 股票 ts_code
    symbol_name: str                   # 股票名称
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    ma60: float                        # 当日 MA60
    ma60_yesterday: float              # 昨日 MA60
    kline_history: list                # 截至当日的历史K线（含OHLCV+MA）
    in_pool_window: bool               # 是否在发现窗口内
    position: Optional["Position"]     # 当前持仓（如有）

@dataclass
class BuySignal:
    """买入信号"""
    date: str
    symbol: str
    price: float          # 建议买入价
    reason: str           # 信号原因，用于展示

@dataclass
class Position:
    """持仓状态 — 由引擎维护"""
    symbol: str
    buy_date: str
    buy_price: float
    shares: int
    max_float_profit_pct: float = 0.0  # 持仓期间盘中最大浮盈%，引擎每日更新

@dataclass
class SellSignal:
    """卖出信号"""
    date: str
    symbol: str
    price: float          # 建议卖出价
    reason: str           # 卖出原因: "止盈" | "空间止损" | "战法止损" | "战法卖出"
```

```python
class BaseStrategy(ABC):
    """战法抽象基类 — 每个战法只需实现两个方法"""

    @property
    @abstractmethod
    def name(self) -> str:
        """战法名称，用于显示"""
        ...

    @property
    def lookback_trading_days(self) -> int:
        """最少需要多少根日线才开始产生信号，默认 60"""
        return 60

    @abstractmethod
    def check_buy(self, ctx: DayContext) -> BuySignal | None:
        """检查当日是否触发买入信号，无信号返回 None"""
        ...

    @abstractmethod
    def check_sell(self, ctx: DayContext) -> SellSignal | None:
        """检查当日是否需要卖出（战法止损/止盈），无信号返回 None。
        注意：空间止损由引擎层处理，不需要在此返回。"""
        ...
```

### 5.2 本次实现两个战法

**战法1: `ma60_breakthrough` — 突破或拉回 MA60 买入**

```
买入:
  - 突破: 昨日收盘 < 昨日MA60，且今日盘中最高 >= 当日MA60
  - 拉回: 昨日收盘 > 昨日MA60，且今日盘中最低 <= 当日MA60

卖出（战法层）:
  - 跌破MA60: 收盘价 < 当日MA60 立即卖出（收盘前判断）

三级浮盈止盈（也是战法层 check_sell 实现）:
  1. 盘中最大浮盈 < 10%: 只看止损
  2. 盘中最大浮盈 >= 10%: 回落5%浮盈 → 止盈
  3. 盘中最大浮盈 >= 20%: 剩80%最大浮盈 → 止盈
```

**战法2: `ma60_pullback_only` — 仅拉回 MA60 买入**

买入只有拉回（规则同上），突破不算。卖出和止盈规则与战法1相同。

---

## 6. 引擎设计

### 6.1 BacktestEngine

```python
class BacktestEngine:
    def __init__(self, dp: DataProvider, pool_codes: list,
                 strategy: BaseStrategy, space_stop_pct: float,
                 position_pct: float):
        ...

    def run(self) -> Report:
        """遍历日期 → 每只股票检查 → 撮合 → 返回报告"""
        ...
```

### 6.2 每日遍历顺序（每只股票）

```
1. 更新持仓 max_float_profit_pct = max(昨日值, (今日最高 - 买入价) / 买入价)
2. 检查是否有持仓且今日开盘 → 执行昨日未完成的"次日开盘止损"
3. 检查策略 check_sell() → 战法止损/止盈（可读取 position.max_float_profit_pct）
3. 盘中检查空间止损（持仓成本 × (1 - 空间止损%)）
4. 如果以上卖出触发 → 执行卖出，更新持仓/资金
5. 如果无持仓 + 在发现窗口内 → 检查策略 check_buy()
   - 有买入信号 + 资金充足 → 买入
   - 有买入信号 + 已有持仓/资金不足 → 记录"信号未成交"
```

### 6.3 回测时间范围

- 起始日: min(所有股票 entry_date) - 策略 lookback_trading_days 个交易日
- 结束日: max(所有股票 exit_date 中非 now 的, 最新交易日)
- 只遍历交易日

### 6.4 数据加载

- 调用 `dp.ensure_data_loaded(codes=池中股票, start_date=起始日, end_date=结束日)`
- 加载后，用 `dp.get_daily()` 获取每只股票的 K 线 DataFrame
- 预计算 MA60（复用 `calc_ma(df, [60])`），保证回测期间高速访问

---

## 7. 报表设计

### 7.1 Reporter（统计输出）

```python
@dataclass
class Report:
    # 汇总
    total_trades: int          # 总交易笔数（完整买卖）
    win_trades: int            # 盈利笔数
    lose_trades: int           # 亏损笔数
    win_rate: float            # 胜率 0.584
    total_return_pct: float    # 累计收益率 %
    max_drawdown_pct: float    # 最大回撤 %
    avg_hold_days: float       # 平均持仓天数
    avg_win_pct: float         # 平均单笔盈利 %
    avg_lose_pct: float        # 平均单笔亏损 %
    profit_loss_ratio: float   # 盈亏比 (avg_win / avg_lose)

    # 按股票
    stock_summaries: list[StockSummary]
    # 交易明细
    trades: list[TradeRecord]
    # 信号未成交
    missed_signals: list[TradeRecord]
    # 每日资金曲线
    equity_curve: list[dict]   # [{date, equity, return_pct}, ...]
```

### 7.2 汇总卡片（6 指标）

```
┌──────────────┬──────────────┬──────────────┐
│ 总交易笔数     │    胜率       │   总收益率    │
│    142       │   58.4%      │   +12.3%     │
│ 赢83 / 亏59  │              │              │
├──────────────┼──────────────┼──────────────┤
│  最大回撤     │ 平均持仓天    │    盈亏比     │
│   -8.2%      │   5.2天      │   1.6:1      │
└──────────────┴──────────────┴──────────────┘
```

### 7.3 盈亏曲线

Plotly 单色折线图: X 轴=日期, Y 轴=累计收益率%, 覆盖整个回测日期范围。

### 7.4 股票汇总表

按股票汇总，可点击展开交易明细：

```
股票      交易次数  胜率    累计盈亏%  平均持仓天  盈亏比
────────────────────────────────────────────────────
顺络电子     35    62.8%   +8.2%      4.8天     1.8:1  [▼展开]
  ├─ 20260210  买入   42.50
  ├─ 20260224  卖出   48.30   +13.6%  止盈
  ├─ 20260305  买入   45.10
  ├─ 20260308  卖出   43.20   -4.2%   空间止损
  ├─ 20260311  买入   44.80
  ├─ 20260315  信号未成交 43.55         已持仓
  ├─ 20260402  卖出   47.50   +6.0%   战法卖出
  └─ ...
```

交易明细按日期正序排列，买入/卖出/信号未成交混排。

卖出原因枚举: `止盈` | `空间止损` | `战法止损` | `战法卖出`

---

## 8. Dashboard 页面

### 8.1 导航栏新增

在 `dashboard/app.py` 的 `st.navigation()` 中新增:
```python
st.Page("pages/04_战法回测.py", title="战法回测", icon="🔬"),
```

### 8.2 页面交互流程

```
1. 选择股票池 + 策略  [两个下拉框]
2. 展开"股票池详情" expander 查看:
   - ✅ 顺络电子 → 002138.SZ  20260210 ~ 20260415
   - ✅ 中钨高新 → 000657.SZ  20260210 ~ now
   - ❌ 某股票 → 未找到
3. 点击 [📥 加载数据] → 显示加载状态
4. 数据就绪后点击 [▶ 运行回测] → 显示结果
```

### 8.3 数据加载

- 按钮触发后，先计算 lookback 缓冲日期
- 调 `DashboardService.ensure_backtest_data(codes, start, end)`
- 显示结果: `✅ 已加载 4只股票, 缓冲60交易日, 共8,432条K线`

---

## 9. DashboardService 新增方法

```python
class DashboardService:
    # 新增

    def load_backtest_pools(self) -> list[PoolConfig]:
        """从 config/backtest_pools.txt 解析股票池"""

    def load_backtest_strategies(self) -> list[StrategyConfig]:
        """从 config/backtest_strategies.txt 解析策略"""

    def resolve_stock_name(self, name: str) -> str | None:
        """股票名 → ts_code，从 stock_basic_cache 查"""

    def ensure_backtest_data(self, codes: list[str],
                             start_date: str, end_date: str) -> None:
        """加载指定股票的回测数据，复用 DataProvider"""

    def run_backtest(self, pool: PoolConfig, strategy_cfg: StrategyConfig) -> Report:
        """创建引擎，运行回测，返回报告"""
```

---

## 10. 复用清单

| 复用项 | 来源 | 用途 |
|--------|------|------|
| DataProvider | data_provider.py | 所有K线数据读取 |
| ensure_data_loaded | data_provider.py | 按 codes+日期范围加载数据 |
| stock_basic_cache | cache_manager.py (SQLite) | 股票名 → ts_code 解析 |
| calc_ma | tools/technical.py | 预计算 MA60 |
| rows_to_df | tools/technical.py | K线数据处理 |
| render_ohlcv_section | rendering/index_section.py | 可选：单股K线图 |
| PAGE_CSS / colors | rendering/styles.py | 页面配色统一 |
| get_latest_trade_date | dashboard_service.py | 解析 exit_date=now |

---

## 11. 后续可扩展

- 战法参数自定义（策略配置文件加字段）
- 通过条件筛选自动生成股票池（替代手动输入）
- 多策略对比模式（同时跑多个策略，并列展示结果）
- 导出回测报告为 CSV/Excel
