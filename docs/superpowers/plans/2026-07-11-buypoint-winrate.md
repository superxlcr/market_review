# 买点胜率回测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「战法回测」从"自选股票池的组合回测"改造为"全市场扫描、逐买点统计胜率"的新系统。

**Architecture:** 全新独立模块 `src/marketreview/winrate/`，旧 `backtest/` 不动。把条件单进场+出场逻辑抽成无仓位、无资金的**单笔交易模拟器**（纯函数）；扫描按单只股票 walk-forward、多线程并行；复用 `buy_points.py`/`band_analysis`/`technical`/`DataProvider`。重逻辑全部设计成纯函数、数据可注入，方便 pytest 单测。

**Tech Stack:** Python 3.11+，pandas，SQLite（`data/marketreview.db`），Streamlit，pytest（本次新引入），tushare（仅数据补齐用）。

关联 spec：`docs/superpowers/specs/2026-07-11-buypoint-winrate-design.md`

## Global Constraints

- **版本号**：完成后 `dashboard/services/dashboard_service.py` 的 `_AI_VERSION` 由 `"8.8.0"` → `"9.0.0"`（破坏性改动，递增主版本 X）。
- **日期格式**：一律 `YYYYMMDD` 字符串，DB 查询不用带横杠格式。
- **前复权**：K线先 `rows_to_df` 再 `DataProvider.raw_to_qfq()` 再算指标。
- **配色**：红涨绿跌（页面信号）。
- **市值单位**：tushare `total_mv` 为**万元**；亿 = `total_mv / 1e4`。
- **缓存读取**：按 `trade_date`/`code` 过滤，不用裸 `LIMIT N`。
- **无未来函数**：day T 只能用截至 T 的数据（walk-forward）。
- **市值档位**：微盘 `<100亿` / 小盘 `100~300` / 中盘 `300~600` / 大盘 `>600`。
- **出场分桶（exit_reason 取值固定）**：`大胜利 | 小胜利 | 盘中止损 | 收盘止损 | 时间止损 | 回测结束`。
- **测试**：纯逻辑模块全部 pytest TDD；页面层手动验证（重启 Streamlit）。测试文件放 `tests/winrate/`。

---

### Task 0: 引入 pytest 测试骨架

**Files:**
- Modify: `pyproject.toml`（追加 pytest 配置）
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/winrate/__init__.py`
- Create: `tests/winrate/test_smoke.py`

**Interfaces:**
- Produces: 可运行的 `pytest`，`tests/winrate/` 作为本功能测试目录；`conftest.py` 保证 `import marketreview.*` 可用。

- [ ] **Step 1: 安装 pytest**

Run: `pip install pytest`
Expected: 成功安装（`Successfully installed pytest-...`）。

- [ ] **Step 2: 在 pyproject.toml 追加 pytest 配置**

在 `pyproject.toml` 末尾追加：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-q"
```

- [ ] **Step 3: 建测试目录骨架**

`tests/__init__.py`：留空。
`tests/winrate/__init__.py`：留空。

`tests/conftest.py`：
```python
"""Ensure the src-layout package is importable during tests."""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
```

- [ ] **Step 4: 写冒烟测试**

`tests/winrate/test_smoke.py`：
```python
def test_import_marketreview():
    import marketreview  # noqa: F401
    assert True
```

- [ ] **Step 5: 运行冒烟测试**

Run: `python -m pytest tests/winrate/test_smoke.py -v`
Expected: PASS（1 passed）。

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/
git commit -m "test: bootstrap pytest for winrate module"
```

---

### Task 1: `winrate/config.py` — 配置解析

**Files:**
- Create: `src/marketreview/winrate/__init__.py`（留空）
- Create: `src/marketreview/winrate/config.py`
- Create: `config/winrate_config.txt`
- Test: `tests/winrate/test_config.py`

**Interfaces:**
- Produces:
  - `WinrateConfig`（dataclass，字段见下）
  - `default_winrate_config() -> WinrateConfig`
  - `parse_winrate_config(path: str | Path) -> WinrateConfig`
  - `cap_bucket(mv_yi: float) -> str`（"微盘"/"小盘"/"中盘"/"大盘"）

- [ ] **Step 1: 写失败测试**

`tests/winrate/test_config.py`：
```python
from pathlib import Path
from marketreview.winrate.config import (
    WinrateConfig, default_winrate_config, parse_winrate_config, cap_bucket,
)


def test_defaults():
    c = default_winrate_config()
    assert c.win_threshold_pct == 10.0
    assert c.big_win_pct == 20.0
    assert c.small_win_floor_pct == 5.0
    assert c.space_stop_pct == 5.0
    assert c.use_atr_stop is False
    assert c.atr_multiplier == 2.0
    assert c.time_stop_days == 20
    assert c.open_chase_cap_pct == 102.0
    assert c.long_ma_arrange == "多头"
    assert c.short_ma_arrange == "无关"
    assert c.buy_points == ["均线支撑", "回调一半", "波段50%"]


def test_cap_bucket():
    assert cap_bucket(50) == "微盘"
    assert cap_bucket(100) == "小盘"
    assert cap_bucket(299) == "小盘"
    assert cap_bucket(300) == "中盘"
    assert cap_bucket(599) == "中盘"
    assert cap_bucket(600) == "大盘"
    assert cap_bucket(1200) == "大盘"


def test_parse_overrides(tmp_path):
    p = tmp_path / "winrate_config.txt"
    p.write_text(
        "判赢阈值%=8\n"
        "启用ATR止损=是\n"
        "ATR倍数=3\n"
        "时间止损天数=15\n"
        "长期均线排列=空头\n"
        "市值下限亿=100\n"
        "行业白名单=电子|计算机\n"
        "上市最短天数=300\n",
        encoding="utf-8",
    )
    c = parse_winrate_config(p)
    assert c.win_threshold_pct == 8.0
    assert c.use_atr_stop is True
    assert c.atr_multiplier == 3.0
    assert c.time_stop_days == 15
    assert c.long_ma_arrange == "空头"
    assert c.mv_min_yi == 100.0
    assert c.industry_whitelist == ["电子", "计算机"]
    assert c.min_list_days == 300


def test_parse_missing_file_returns_defaults(tmp_path):
    c = parse_winrate_config(tmp_path / "nope.txt")
    assert c == default_winrate_config()
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/winrate/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: marketreview.winrate.config`）。

- [ ] **Step 3: 实现 config.py**

`src/marketreview/winrate/__init__.py`：留空。

`src/marketreview/winrate/config.py`：
```python
"""买点胜率回测配置解析。key=value 文本，# 注释，沿用项目风格。"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from pathlib import Path

ALL_BUY_POINTS = ["均线支撑", "回调一半", "波段50%"]


@dataclass
class WinrateConfig:
    buy_points: list[str] = field(default_factory=lambda: list(ALL_BUY_POINTS))
    # 判赢与止盈
    win_threshold_pct: float = 10.0
    big_win_pct: float = 20.0
    small_win_floor_pct: float = 5.0
    # 通用止损
    space_stop_pct: float = 5.0
    use_atr_stop: bool = False
    atr_multiplier: float = 2.0
    time_stop_days: int = 20
    # 进场
    open_chase_cap_pct: float = 102.0
    # 扫描范围
    start_date: str = "20230921"
    end_date: str = "now"
    # 过滤器
    short_ma_arrange: str = "无关"   # 多头 | 空头 | 无关
    long_ma_arrange: str = "多头"
    mv_min_yi: float = 0.0           # 0 = 不限下限
    mv_max_yi: float = 0.0           # 0 = 不限上限
    industry_whitelist: list[str] = field(default_factory=list)
    min_list_days: int = 250
    # 运行
    max_workers: int = 10


def default_winrate_config() -> WinrateConfig:
    return WinrateConfig()


def cap_bucket(mv_yi: float) -> str:
    if mv_yi < 100:
        return "微盘"
    if mv_yi < 300:
        return "小盘"
    if mv_yi < 600:
        return "中盘"
    return "大盘"


_KEY_MAP = {
    "判赢阈值%": ("win_threshold_pct", float),
    "大胜利止盈%": ("big_win_pct", float),
    "小胜利回落止盈%": ("small_win_floor_pct", float),
    "空间止损幅度%": ("space_stop_pct", float),
    "启用ATR止损": ("use_atr_stop", "bool"),
    "ATR倍数": ("atr_multiplier", float),
    "时间止损天数": ("time_stop_days", int),
    "开盘追高上限%": ("open_chase_cap_pct", float),
    "开始日期": ("start_date", str),
    "结束日期": ("end_date", str),
    "短期均线排列": ("short_ma_arrange", str),
    "长期均线排列": ("long_ma_arrange", str),
    "市值下限亿": ("mv_min_yi", float),
    "市值上限亿": ("mv_max_yi", float),
    "行业白名单": ("industry_whitelist", "list"),
    "上市最短天数": ("min_list_days", int),
    "并发数": ("max_workers", int),
}


def _coerce(kind, val: str):
    if kind == "bool":
        return val.strip() in ("是", "true", "True", "1", "yes")
    if kind == "list":
        return [x.strip() for x in val.split("|") if x.strip()]
    if kind is float:
        return float(val) if val.strip() != "" else 0.0
    if kind is int:
        return int(float(val)) if val.strip() != "" else 0
    return val.strip()


def parse_winrate_config(path: str | Path) -> WinrateConfig:
    path = Path(path)
    cfg = default_winrate_config()
    if not path.exists():
        return cfg
    updates = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            entry = _KEY_MAP.get(k.strip())
            if not entry:
                continue
            field_name, kind = entry
            updates[field_name] = _coerce(kind, v)
    return replace(cfg, **updates)
```

- [ ] **Step 4: 建默认配置文件**

`config/winrate_config.txt`（复制 spec §8 内容）：
```
# 买点胜率回测配置
# 判赢与止盈
判赢阈值%=10
大胜利止盈%=20
小胜利回落止盈%=5

# 通用止损（对三个买点统一）
空间止损幅度%=5
启用ATR止损=否
ATR倍数=2
时间止损天数=20

# 进场
开盘追高上限%=102

# 扫描范围
开始日期=20230921
结束日期=now

# 过滤器
短期均线排列=无关
长期均线排列=多头
市值下限亿=100
市值上限亿=
行业白名单=
上市最短天数=250

# 运行
并发数=10
```

- [ ] **Step 5: 运行验证通过**

Run: `python -m pytest tests/winrate/test_config.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 6: Commit**

```bash
git add src/marketreview/winrate/__init__.py src/marketreview/winrate/config.py config/winrate_config.txt tests/winrate/test_config.py
git commit -m "feat(winrate): config parser + market cap buckets"
```

---

### Task 2: `winrate/filters.py` — 候选池过滤器

**Files:**
- Create: `src/marketreview/winrate/filters.py`
- Test: `tests/winrate/test_filters.py`

**Interfaces:**
- Consumes: `WinrateConfig`（Task 1）；`calc_ma`/`ma_direction`（`marketreview.tools.technical`）。
- Produces:
  - `ma_group_state(df_asc, periods: list[int]) -> str`（"多头"/"空头"/"其他"）
  - `passes_ma_arrange(df_asc, want: str, periods: list[int]) -> bool`
  - `passes_market_cap(mv_yi: float, cfg: WinrateConfig) -> bool`
  - `passes_industry(l1: str, l2: str, whitelist: list[str]) -> bool`
  - `passes_list_age(list_date: str, on_date: str, min_days: int) -> bool`
  - `passes_all(df_asc, cfg, mv_yi, l1, l2, list_date, on_date) -> bool`

- [ ] **Step 1: 写失败测试**

`tests/winrate/test_filters.py`：
```python
import pandas as pd
from marketreview.winrate.config import WinrateConfig
from marketreview.winrate import filters as F


def _rising_df(n=260, base=10.0, step=0.05):
    # 单调上升 → 短/长均线都多头且向上
    closes = [base + i * step for i in range(n)]
    return pd.DataFrame({"close": closes})


def _falling_df(n=260, base=30.0, step=0.05):
    closes = [base - i * step for i in range(n)]
    return pd.DataFrame({"close": closes})


def test_ma_group_state_bull():
    df = _rising_df()
    assert F.ma_group_state(df, [5, 10, 20]) == "多头"
    assert F.ma_group_state(df, [60, 120, 240]) == "多头"


def test_ma_group_state_bear():
    df = _falling_df()
    assert F.ma_group_state(df, [5, 10, 20]) == "空头"


def test_ma_group_state_insufficient():
    df = _rising_df(n=30)
    assert F.ma_group_state(df, [60, 120, 240]) == "其他"


def test_passes_ma_arrange_dont_care_always_true():
    df = _falling_df()
    assert F.passes_ma_arrange(df, "无关", [60, 120, 240]) is True


def test_passes_ma_arrange_match():
    df = _rising_df()
    assert F.passes_ma_arrange(df, "多头", [60, 120, 240]) is True
    assert F.passes_ma_arrange(df, "空头", [60, 120, 240]) is False


def test_passes_market_cap_bounds():
    cfg = WinrateConfig(mv_min_yi=100, mv_max_yi=300)
    assert F.passes_market_cap(50, cfg) is False
    assert F.passes_market_cap(150, cfg) is True
    assert F.passes_market_cap(400, cfg) is False


def test_passes_market_cap_no_bounds():
    cfg = WinrateConfig(mv_min_yi=0, mv_max_yi=0)
    assert F.passes_market_cap(5, cfg) is True
    assert F.passes_market_cap(9999, cfg) is True


def test_passes_industry():
    assert F.passes_industry("电子", "半导体", []) is True          # 空=不限
    assert F.passes_industry("电子", "半导体", ["电子"]) is True
    assert F.passes_industry("电子", "半导体", ["半导体"]) is True   # L2 命中
    assert F.passes_industry("汽车", "整车", ["电子"]) is False


def test_passes_list_age():
    assert F.passes_list_age("20230101", "20240101", 250) is True   # ~365天
    assert F.passes_list_age("20231201", "20240101", 250) is False  # ~31天
    assert F.passes_list_age("", "20240101", 250) is False          # 缺失=不通过
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/winrate/test_filters.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现 filters.py**

`src/marketreview/winrate/filters.py`：
```python
"""候选池过滤器：均线多空排列、市值、行业、上市时长。全部纯函数。"""
from __future__ import annotations
from datetime import datetime
import numpy as np
import pandas as pd

from marketreview.tools.technical import calc_ma, ma_direction
from .config import WinrateConfig


def _latest_non_nan(vals: list[float]) -> float | None:
    for v in reversed(vals):
        if v is not None and not np.isnan(v):
            return float(v)
    return None


def ma_group_state(df_asc: pd.DataFrame, periods: list[int]) -> str:
    """periods 从快到慢（如 [5,10,20]）。返回 多头/空头/其他。
    多头 = 快>中>慢 且最快线向上；空头 = 快<中<慢 且最快线向下。"""
    mas = calc_ma(df_asc, periods)
    latest = []
    for p in periods:
        v = _latest_non_nan(mas[f"MA{p}"])
        if v is None:
            return "其他"
        latest.append(v)
    fast_dir = ma_direction(mas[f"MA{periods[0]}"])
    if all(latest[i] > latest[i + 1] for i in range(len(latest) - 1)):
        return "多头" if fast_dir == "↑" else "其他"
    if all(latest[i] < latest[i + 1] for i in range(len(latest) - 1)):
        return "空头" if fast_dir == "↓" else "其他"
    return "其他"


def passes_ma_arrange(df_asc: pd.DataFrame, want: str, periods: list[int]) -> bool:
    if want == "无关" or not want:
        return True
    return ma_group_state(df_asc, periods) == want


def passes_market_cap(mv_yi: float, cfg: WinrateConfig) -> bool:
    if cfg.mv_min_yi and mv_yi < cfg.mv_min_yi:
        return False
    if cfg.mv_max_yi and mv_yi > cfg.mv_max_yi:
        return False
    return True


def passes_industry(l1: str, l2: str, whitelist: list[str]) -> bool:
    if not whitelist:
        return True
    return (l1 in whitelist) or (l2 in whitelist)


def passes_list_age(list_date: str, on_date: str, min_days: int) -> bool:
    if not list_date or not on_date:
        return False
    try:
        d0 = datetime.strptime(list_date, "%Y%m%d")
        d1 = datetime.strptime(on_date, "%Y%m%d")
    except ValueError:
        return False
    return (d1 - d0).days >= min_days


def passes_all(df_asc: pd.DataFrame, cfg: WinrateConfig, mv_yi: float,
               l1: str, l2: str, list_date: str, on_date: str) -> bool:
    """便宜的先算：上市时长 → 市值 → 行业 → 均线（最贵）。"""
    if not passes_list_age(list_date, on_date, cfg.min_list_days):
        return False
    if not passes_market_cap(mv_yi, cfg):
        return False
    if not passes_industry(l1, l2, cfg.industry_whitelist):
        return False
    if not passes_ma_arrange(df_asc, cfg.short_ma_arrange, [5, 10, 20]):
        return False
    if not passes_ma_arrange(df_asc, cfg.long_ma_arrange, [60, 120, 240]):
        return False
    return True
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/winrate/test_filters.py -v`
Expected: PASS（9 passed）。

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/winrate/filters.py tests/winrate/test_filters.py
git commit -m "feat(winrate): universe filters (MA arrange / cap / industry / list-age)"
```

---

### Task 3: `winrate/trade_sim.py` — 单笔交易模拟器（心脏）

**Files:**
- Create: `src/marketreview/winrate/trade_sim.py`
- Test: `tests/winrate/test_trade_sim.py`

**Interfaces:**
- Consumes: `WinrateConfig`（Task 1）。
- Produces:
  - `board_limit_pct(code: str) -> float`
  - `BuyPointSignal`（dataclass）：`buy_point:str, target_price:float, close_stop_kind:str("entry"|"ma"), close_stop_period:int, reason:str`
  - `TradeResult`（dataclass，字段见 spec §5）
  - `simulate_trade(signal, signal_idx, klines_asc, cfg, code, name, atr_at_signal) -> TradeResult | None`
- 约定：`klines_asc` 每行 dict 含 `date/open/high/low/close` 及预算好的 `ma5..ma240`（键名 `ma{period}`）。返回 `None` 表示条件单未成交（不计样本）。

- [ ] **Step 1: 写失败测试**

`tests/winrate/test_trade_sim.py`：
```python
from marketreview.winrate.config import WinrateConfig
from marketreview.winrate.trade_sim import (
    BuyPointSignal, simulate_trade, board_limit_pct,
)


def _k(date, o, h, l, c, **ma):
    row = {"date": date, "open": o, "high": h, "low": l, "close": c}
    row.update({k: v for k, v in ma.items()})
    return row


def _entry_sig(target=10.0):
    # 回调一半类：收盘止损=跌破买入价
    return BuyPointSignal(buy_point="回调一半", target_price=target,
                          close_stop_kind="entry", close_stop_period=0,
                          reason="test")


def test_board_limit_pct():
    assert board_limit_pct("600000.SH") == 0.10
    assert board_limit_pct("300750.SZ") == 0.20
    assert board_limit_pct("688111.SH") == 0.20
    assert board_limit_pct("830799.BJ") == 0.30


def test_not_filled_returns_none():
    # 信号日收盘10；次日最低10.5，从未触及目标10 → 未成交
    cfg = WinrateConfig()
    klines = [
        _k("20240101", 10, 10, 10, 10.0),   # signal idx=0
        _k("20240102", 10.5, 11, 10.5, 10.8),  # never touches 10
    ]
    r = simulate_trade(_entry_sig(10.0), 0, klines, cfg, "600000.SH", "测试", atr_at_signal=0.3)
    assert r is None


def test_big_win_intraday():
    # 目标10成交，之后某日 high 达 12(=+20%) → 大胜利，卖在12
    cfg = WinrateConfig()
    klines = [
        _k("20240101", 10, 10, 10, 10.0),      # signal idx=0
        _k("20240102", 10, 10.2, 9.9, 10.0),   # entry@10 (low<=10<=high)
        _k("20240103", 10.5, 12.5, 10.4, 11.0),  # high 12.5 >= 12 → 大胜利 @12
    ]
    r = simulate_trade(_entry_sig(10.0), 0, klines, cfg, "600000.SH", "测试", atr_at_signal=0.3)
    assert r is not None
    assert r.entry_price == 10.0
    assert r.exit_reason == "大胜利"
    assert round(r.exit_price, 2) == 12.0
    assert r.success is True
    assert round(r.pnl_pct, 1) == 20.0


def test_small_win_pullback():
    # 摸到 +10%(mfp) 后回落到 +5% → 小胜利，卖在10.5
    cfg = WinrateConfig()
    klines = [
        _k("20240101", 10, 10, 10, 10.0),        # signal
        _k("20240102", 10, 10.0, 9.95, 10.0),    # entry@10
        _k("20240103", 10.5, 11.2, 10.4, 11.0),  # high11.2 → mfp=12% armed（未到20%）
        _k("20240104", 10.8, 10.9, 10.4, 10.6),  # low10.4 <= 10.5 → 小胜利 @10.5
    ]
    r = simulate_trade(_entry_sig(10.0), 0, klines, cfg, "600000.SH", "测试", atr_at_signal=0.3)
    assert r.exit_reason == "小胜利"
    assert round(r.exit_price, 2) == 10.5
    assert r.success is True


def test_space_stop_priority_over_take_profit():
    # 同日 low 破止损 且 high 达大胜利 → 先止损
    cfg = WinrateConfig(space_stop_pct=5.0)  # 止损价=10*0.95=9.5
    klines = [
        _k("20240101", 10, 10, 10, 10.0),
        _k("20240102", 10, 10.0, 9.96, 10.0),   # entry@10
        _k("20240103", 10, 12.5, 9.4, 10.0),    # low9.4<=9.5止损 且 high12.5>=12 → 先止损@9.5
    ]
    r = simulate_trade(_entry_sig(10.0), 0, klines, cfg, "600000.SH", "测试", atr_at_signal=0.3)
    assert r.exit_reason == "盘中止损"
    assert round(r.exit_price, 2) == 9.5


def test_close_stop_entry_kind():
    # 无止盈无空间止损触发，但收盘跌破买入价 → 收盘止损
    cfg = WinrateConfig(space_stop_pct=20.0)  # 止损价8，不触发
    klines = [
        _k("20240101", 10, 10, 10, 10.0),
        _k("20240102", 10, 10.1, 9.9, 10.0),    # entry@10
        _k("20240103", 9.9, 10.0, 9.6, 9.7),    # close9.7<entry10 → 收盘止损@9.7
    ]
    r = simulate_trade(_entry_sig(10.0), 0, klines, cfg, "600000.SH", "测试", atr_at_signal=0.3)
    assert r.exit_reason == "收盘止损"
    assert round(r.exit_price, 2) == 9.7
    assert r.success is False


def test_time_stop():
    cfg = WinrateConfig(space_stop_pct=50.0, time_stop_days=2)
    klines = [_k("20240101", 10, 10, 10, 10.0), _k("20240102", 10, 10.1, 9.9, 10.0)]  # entry idx1
    # 之后横盘，持有到第2天触发时间止损
    klines += [
        _k("20240103", 10, 10.1, 9.9, 10.0),  # hold_days=1
        _k("20240104", 10, 10.1, 9.9, 10.0),  # hold_days=2 → 时间止损@close10
    ]
    r = simulate_trade(_entry_sig(10.0), 0, klines, cfg, "600000.SH", "测试", atr_at_signal=0.3)
    assert r.exit_reason == "时间止损"
    assert r.hold_days == 2


def test_atr_stop_used_when_enabled():
    # 启用ATR：止损=entry-2*atr=10-2*0.3=9.4
    cfg = WinrateConfig(use_atr_stop=True, atr_multiplier=2.0)
    klines = [
        _k("20240101", 10, 10, 10, 10.0),
        _k("20240102", 10, 10.0, 9.96, 10.0),   # entry@10
        _k("20240103", 9.9, 10.0, 9.3, 9.8),    # low9.3<=9.4 → 盘中止损@9.4
    ]
    r = simulate_trade(_entry_sig(10.0), 0, klines, cfg, "600000.SH", "测试", atr_at_signal=0.3)
    assert r.exit_reason == "盘中止损"
    assert round(r.exit_price, 2) == 9.4
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/winrate/test_trade_sim.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现 trade_sim.py**

`src/marketreview/winrate/trade_sim.py`：
```python
"""单笔交易模拟器 — 条件单进场 + 逐日出场，无仓位无资金。纯函数。"""
from __future__ import annotations
from dataclasses import dataclass, field

from .config import WinrateConfig, cap_bucket  # noqa: F401  (cap_bucket 由 scan 用)


def board_limit_pct(code: str) -> float:
    """次日涨跌停幅度。"""
    c = code.split(".")[0]
    if c.startswith(("300", "301", "688")):
        return 0.20
    if c.startswith(("8", "4")):  # 北交所
        return 0.30
    return 0.10


@dataclass
class BuyPointSignal:
    buy_point: str
    target_price: float
    close_stop_kind: str = "entry"   # "entry" | "ma"
    close_stop_period: int = 0       # ma 时用（60/120/240）
    reason: str = ""


@dataclass
class TradeResult:
    buy_point: str
    code: str
    name: str
    signal_date: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    exit_reason: str
    mfp_pct: float
    hold_days: int
    pnl_pct: float
    success: bool
    # 上下文标签（由 scan_engine 回填）
    short_ma_state: str = ""
    long_ma_state: str = ""
    market_cap_yi: float = 0.0
    cap_bucket: str = ""
    industry_l1: str = ""
    industry_l2: str = ""


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def simulate_trade(signal: BuyPointSignal, signal_idx: int,
                   klines_asc: list[dict], cfg: WinrateConfig,
                   code: str, name: str, atr_at_signal: float) -> TradeResult | None:
    target = signal.target_price
    if target <= 0:
        return None
    sig_row = klines_asc[signal_idx]
    sig_close = _f(sig_row.get("close"))
    if sig_close <= 0:
        return None

    # ⑤ 挂单前涨跌停可达性：目标价必须落在次日涨跌停幅度内
    limit = board_limit_pct(code)
    if target < sig_close * (1 - limit) or target > sig_close * (1 + limit):
        return None

    entry_idx = signal_idx + 1
    if entry_idx >= len(klines_asc):
        return None

    # ② / ③ 成交
    er = klines_asc[entry_idx]
    o, h, l = _f(er.get("open")), _f(er.get("high")), _f(er.get("low"))
    cap_price = target * cfg.open_chase_cap_pct / 100.0
    if o > target and o <= cap_price:
        entry_price = o
    elif l <= target <= h:
        entry_price = target
    else:
        return None  # 未成交/跳空过上限

    entry_date = str(er.get("date"))
    # 空间止损价
    if cfg.use_atr_stop and atr_at_signal > 0:
        stop_price = entry_price - cfg.atr_multiplier * atr_at_signal
    else:
        stop_price = entry_price * (1 - cfg.space_stop_pct / 100.0)
    big_price = entry_price * (1 + cfg.big_win_pct / 100.0)
    small_price = entry_price * (1 + cfg.small_win_floor_pct / 100.0)

    # MFP 从建仓当日起（含 entry day high），但出场从 entry_idx+1 起（T+1）
    mfp = max(0.0, (h - entry_price) / entry_price * 100.0)
    armed = mfp >= cfg.win_threshold_pct

    def _mk(exit_idx, exit_price, reason):
        exit_row = klines_asc[exit_idx]
        mfp_final = max(mfp, (_f(exit_row.get("high")) - entry_price) / entry_price * 100.0)
        return TradeResult(
            buy_point=signal.buy_point, code=code, name=name,
            signal_date=str(sig_row.get("date")),
            entry_date=entry_date, entry_price=round(entry_price, 3),
            exit_date=str(exit_row.get("date")), exit_price=round(exit_price, 3),
            exit_reason=reason,
            mfp_pct=round(mfp_final, 2),
            hold_days=exit_idx - entry_idx,
            pnl_pct=round((exit_price - entry_price) / entry_price * 100.0, 2),
            success=mfp_final >= cfg.win_threshold_pct,
        )

    for i in range(entry_idx + 1, len(klines_asc)):
        row = klines_asc[i]
        oo, hh, ll, cc = _f(row.get("open")), _f(row.get("high")), _f(row.get("low")), _f(row.get("close"))

        # 开盘（先止损）
        if oo <= stop_price:
            return _mk(i, oo, "盘中止损")
        if oo >= big_price:
            return _mk(i, oo, "大胜利")
        if armed and oo <= small_price:
            return _mk(i, oo, "小胜利")

        # 盘中：先更新 MFP，再判（先止损）
        cur = (hh - entry_price) / entry_price * 100.0
        if cur > mfp:
            mfp = cur
        if mfp >= cfg.win_threshold_pct:
            armed = True
        if ll <= stop_price:
            return _mk(i, stop_price, "盘中止损")
        if hh >= big_price:
            return _mk(i, big_price, "大胜利")
        if armed and ll <= small_price:
            return _mk(i, small_price, "小胜利")

        # 收盘
        hold_days = i - entry_idx
        if hold_days >= cfg.time_stop_days:
            return _mk(i, cc, "时间止损")
        if signal.close_stop_kind == "ma":
            cs = _f(row.get(f"ma{signal.close_stop_period}"))
        else:
            cs = entry_price
        if cs > 0 and cc < cs:
            return _mk(i, cc, "收盘止损")

    # 数据到底仍持仓 → 末日收盘清仓
    last = len(klines_asc) - 1
    return _mk(last, _f(klines_asc[last].get("close")), "回测结束")
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/winrate/test_trade_sim.py -v`
Expected: PASS（8 passed）。

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/winrate/trade_sim.py tests/winrate/test_trade_sim.py
git commit -m "feat(winrate): single-trade simulator (entry/exit, take-profit tiers, stops)"
```

---

### Task 4: `winrate/buypoint_defs.py` — 买点适配器（walk-forward）

**Files:**
- Create: `src/marketreview/winrate/buypoint_defs.py`
- Test: `tests/winrate/test_buypoint_defs.py`

**Interfaces:**
- Consumes: `BuyPointSignal`（Task 3）；`analyze_band`（`marketreview.tools.band_analysis`）；`HalfRetraceChecker/Band50Checker/MAChecker`（`marketreview.tools.buy_points`）。
- Produces: `detect_buy_points(df_asc, band, selected: list[str]) -> list[BuyPointSignal]`

- [ ] **Step 1: 写失败测试**

`tests/winrate/test_buypoint_defs.py`：
```python
import pandas as pd
from marketreview.winrate.buypoint_defs import detect_buy_points
from marketreview.winrate.trade_sim import BuyPointSignal
from marketreview.tools.band_analysis import BandResult


class _FakeBand(BandResult):
    pass


def test_band50_maps_to_entry_stop():
    # 构造一个满足 Band50Checker 的 band：跌破62.5、v_qualified、回调>=13天
    band = BandResult()
    band.trigger_625_date = "20240101"
    band.v_qualified = True
    band.line_50 = 9.0
    band.line_625 = 9.5
    band.current_price = 8.5
    band.p_idx = 0
    band.rows_count = 20   # pullback = 20-1-0 = 19 >= 13
    df = pd.DataFrame({"amount": [1.0] * 20})
    sigs = detect_buy_points(df, band, ["波段50%"])
    assert len(sigs) == 1
    s = sigs[0]
    assert s.buy_point == "波段50%"
    assert s.target_price == 9.0
    assert s.close_stop_kind == "entry"


def test_selected_filters_out_unwanted():
    band = BandResult()
    band.trigger_625_date = "20240101"
    band.v_qualified = True
    band.line_50 = 9.0
    band.current_price = 8.5
    band.p_idx = 0
    band.rows_count = 20
    df = pd.DataFrame({"amount": [1.0] * 20})
    sigs = detect_buy_points(df, band, ["回调一半"])  # 只要回调一半
    assert all(s.buy_point == "回调一半" for s in sigs)
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/winrate/test_buypoint_defs.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现 buypoint_defs.py**

`src/marketreview/winrate/buypoint_defs.py`：
```python
"""把 buy_points.py 的 checker 包成可回测的 BuyPointSignal（触发价 + 收盘止损规则）。"""
from __future__ import annotations
import pandas as pd

from marketreview.tools.band_analysis import BandResult
from marketreview.tools.buy_points import (
    HalfRetraceChecker, Band50Checker, MAChecker,
)
from .trade_sim import BuyPointSignal

# 页面标签 → checker
_NAME_MAP = {
    "回调一半": ("half", HalfRetraceChecker()),
    "波段50%": ("band50", Band50Checker()),
    "均线支撑": ("ma", MAChecker()),
}


def detect_buy_points(df_asc: pd.DataFrame, band: BandResult,
                      selected: list[str]) -> list[BuyPointSignal]:
    out: list[BuyPointSignal] = []
    for name in selected:
        entry = _NAME_MAP.get(name)
        if entry is None:
            continue
        kind, checker = entry
        for bp in checker.check(df_asc, band):
            if kind == "ma":
                # 均线支撑：收盘止损 = 跌破 MA（该周期）；触发价 = MA 值
                try:
                    period = int(bp.position.replace("MA", ""))
                except ValueError:
                    period = 0
                out.append(BuyPointSignal(
                    buy_point="均线支撑", target_price=bp.price,
                    close_stop_kind="ma", close_stop_period=period,
                    reason=bp.reason,
                ))
            else:
                # 回调一半 / 波段50%：收盘止损 = 跌破买入价
                out.append(BuyPointSignal(
                    buy_point=name, target_price=bp.price,
                    close_stop_kind="entry", close_stop_period=0,
                    reason=bp.reason,
                ))
    return out
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/winrate/test_buypoint_defs.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/winrate/buypoint_defs.py tests/winrate/test_buypoint_defs.py
git commit -m "feat(winrate): buy-point adapters (half/band50/ma) → BuyPointSignal"
```

---

### Task 5: `winrate/scan_engine.py` — 单票 walk-forward + 并行

**Files:**
- Create: `src/marketreview/winrate/scan_engine.py`
- Test: `tests/winrate/test_scan_engine.py`

**Interfaces:**
- Consumes: `WinrateConfig`、`filters.passes_all`、`buypoint_defs.detect_buy_points`、`trade_sim.simulate_trade`、`analyze_band`、`calc_ma`/`calc_atr`/`rows_to_df`、`DataProvider.raw_to_qfq`。
- Produces:
  - `prepare_klines(rows_desc) -> list[dict]`（qfq + 预算 ma5..ma240 + 每行日期字符串）
  - `scan_stock(code, name, rows_desc, cfg, industry_l1, industry_l2, list_date, mv_series, band_lookback=300) -> list[TradeResult]`
  - `run_scan(dp, cfg, progress_cb=None) -> list[TradeResult]`

- [ ] **Step 1: 写失败测试（纯 scan_stock，喂合成数据，不碰 DB）**

`tests/winrate/test_scan_engine.py`：
```python
from marketreview.winrate.config import WinrateConfig
from marketreview.winrate import scan_engine as SE


def _row(date, o, h, l, c, amount=1.0):
    # 不复权价（raw_to_qfq 需 adj_factor），这里给 adj_factor=1 避免复权改动
    return {"date": date, "open": o, "high": h, "low": l, "close": c,
            "vol": 1.0, "amount": amount, "adj_factor": 1.0, "asset_type": "stock"}


def test_prepare_klines_adds_ma_keys():
    rows_desc = [_row(f"2024{m:02d}{d:02d}", 10, 10, 10, 10)
                 for m in range(1, 4) for d in range(1, 29)][::-1]  # DESC
    ks = SE.prepare_klines(rows_desc)
    assert ks[0]["date"] <= ks[-1]["date"]          # ASC
    assert "ma5" in ks[-1] and "ma20" in ks[-1]


def test_scan_stock_no_signal_when_flat_series():
    # 全平的序列不会触发任何买点 → 空结果，且不报错
    cfg = WinrateConfig(min_list_days=0, long_ma_arrange="无关",
                        short_ma_arrange="无关")
    rows_desc = [_row(f"202401{d:02d}", 10, 10, 10, 10) for d in range(1, 29)][::-1]
    trades = SE.scan_stock("600000.SH", "测试", rows_desc, cfg,
                           "电子", "半导体", "20200101",
                           mv_series={r["date"]: 150.0 for r in rows_desc})
    assert isinstance(trades, list)
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/winrate/test_scan_engine.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现 scan_engine.py**

`src/marketreview/winrate/scan_engine.py`：
```python
"""扫描引擎：单只股票 walk-forward（闸1持仓→闸2过滤+买点→模拟），多线程并行。"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed

from marketreview.tools.technical import rows_to_df, calc_ma, calc_atr
from marketreview.tools.band_analysis import analyze_band
from marketreview.data.data_provider import DataProvider
from marketreview.log_util import get_logger
from .config import WinrateConfig, cap_bucket
from .filters import passes_all, ma_group_state
from .buypoint_defs import detect_buy_points
from .trade_sim import simulate_trade, TradeResult

log = get_logger(__name__)

_MA_PERIODS = [5, 10, 20, 60, 120, 240]


def prepare_klines(rows_desc: list[dict]) -> list[dict]:
    """rows_desc(date DESC, raw) → date ASC、qfq、每行带 ma5..ma240 与 date 字符串。"""
    df = rows_to_df(rows_desc)
    if df.empty:
        return []
    df = DataProvider.raw_to_qfq(df)
    mas = calc_ma(df, _MA_PERIODS)
    out: list[dict] = []
    for i, (_, r) in enumerate(df.iterrows()):
        d = r.to_dict()
        d["date"] = str(r["date"]).replace("-", "")[:8] if not str(r["date"]).isdigit() else str(r["date"])
        for p in _MA_PERIODS:
            vals = mas[f"MA{p}"]
            d[f"ma{p}"] = float(vals[i]) if i < len(vals) and vals[i] == vals[i] else 0.0  # NaN→0
        out.append(d)
    return out


def scan_stock(code: str, name: str, rows_desc: list[dict], cfg: WinrateConfig,
               industry_l1: str, industry_l2: str, list_date: str,
               mv_series: dict[str, float], band_lookback: int = 300) -> list[TradeResult]:
    klines = prepare_klines(rows_desc)
    n = len(klines)
    if n < 60:
        return []

    dates = [k["date"] for k in klines]
    # 只在配置的时间窗内找信号
    start = cfg.start_date
    end = None if cfg.end_date in ("", "now") else cfg.end_date

    results: list[TradeResult] = []
    i = 1
    while i < n - 1:
        date_T = dates[i]
        if date_T < start or (end and date_T > end):
            i += 1
            continue

        df_upto = rows_to_df([  # 截至 T 的 DataFrame（已 qfq，用 klines 直接切）
            klines[j] for j in range(i + 1)
        ])
        mv_yi = mv_series.get(date_T, 0.0)

        if not passes_all(df_upto, cfg, mv_yi, industry_l1, industry_l2, list_date, date_T):
            i += 1
            continue

        band = analyze_band([klines[j] for j in range(i + 1)], peak_lookback=band_lookback)
        signals = detect_buy_points(df_upto, band, cfg.buy_points)
        if not signals:
            i += 1
            continue

        # ATR@T（用于 ATR 止损）
        atr_vals = calc_atr(df_upto, period=14)
        atr_T = float(atr_vals[-1]) if atr_vals and atr_vals[-1] == atr_vals[-1] else 0.0

        # 每个买点各自模拟；持仓中不重复建仓 → 取最早出场，游标跳到其后
        made: list[TradeResult] = []
        for sig in signals:
            tr = simulate_trade(sig, i, klines, cfg, code, name, atr_T)
            if tr is not None:
                _tag(tr, df_upto, mv_yi, industry_l1, industry_l2)
                made.append(tr)

        if not made:
            i += 1
            continue

        results.extend(made)
        # 跳到所有本轮成交里最晚的出场日之后（避免持仓期重复建仓）
        latest_exit = max(_date_idx(dates, t.exit_date) for t in made)
        i = max(i + 1, latest_exit + 1)

    return results


def _date_idx(dates: list[str], d: str) -> int:
    try:
        return dates.index(d)
    except ValueError:
        return len(dates) - 1


def _tag(tr: TradeResult, df_upto, mv_yi, l1, l2):
    tr.short_ma_state = ma_group_state(df_upto, [5, 10, 20])
    tr.long_ma_state = ma_group_state(df_upto, [60, 120, 240])
    tr.market_cap_yi = round(mv_yi, 1)
    tr.cap_bucket = cap_bucket(mv_yi) if mv_yi > 0 else ""
    tr.industry_l1 = l1
    tr.industry_l2 = l2


def run_scan(dp: DataProvider, cfg: WinrateConfig, progress_cb=None) -> list[TradeResult]:
    """全市场并行扫描。数据须已预加载到 cache。"""
    basics = dp.cache.get_stock_basic()   # [{ts_code,name,list_date,is_st}]
    universe = [b for b in basics if not b.get("is_st")]
    codes = [b["ts_code"] for b in universe]
    ind_map = dp.cache.get_stock_industries(codes)  # {code:{l1_name,l2_name,...}}

    def _one(b: dict) -> list[TradeResult]:
        code = b["ts_code"]
        rows_desc = dp.cache.get_daily(code, limit=2000)
        if not rows_desc:
            return []
        mv_rows = dp.cache.get_daily_basic_for_code(code)  # Task 6 新增
        mv_series = {r["trade_date"]: float(r["total_mv"]) / 1e4 for r in mv_rows}
        ind = ind_map.get(code, {})
        return scan_stock(
            code, b.get("name", ""), rows_desc, cfg,
            ind.get("l1_name", ""), ind.get("l2_name", ""),
            b.get("list_date", ""), mv_series,
        )

    all_trades: list[TradeResult] = []
    total = len(universe)
    done = 0
    with ThreadPoolExecutor(max_workers=cfg.max_workers) as ex:
        futs = {ex.submit(_one, b): b for b in universe}
        for fut in as_completed(futs):
            done += 1
            try:
                all_trades.extend(fut.result())
            except Exception as e:  # noqa: BLE001
                log.warning("scan_stock 失败 %s: %s", futs[fut].get("ts_code"), e)
            if progress_cb:
                progress_cb(done, total)
    log.info("扫描完成: %d只股票, 共 %d 笔交易", total, len(all_trades))
    return all_trades
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/winrate/test_scan_engine.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/winrate/scan_engine.py tests/winrate/test_scan_engine.py
git commit -m "feat(winrate): per-stock walk-forward scan engine + parallel run_scan"
```

---

### Task 6: `CacheManager.get_daily_basic_for_code` — 单票市值序列

**Files:**
- Modify: `src/marketreview/data/cache_manager.py`（新增一个方法）
- Test: `tests/winrate/test_cache_market_cap.py`

**Interfaces:**
- Produces: `CacheManager.get_daily_basic_for_code(code: str) -> list[dict]`（`[{trade_date, total_mv, circ_mv}]`，按 trade_date 升序）。被 `run_scan` 调用。

- [ ] **Step 1: 写失败测试（用临时 DB）**

`tests/winrate/test_cache_market_cap.py`：
```python
from marketreview.data.cache_manager import CacheManager


def test_get_daily_basic_for_code(tmp_path):
    db = tmp_path / "t.db"
    cache = CacheManager(str(db))
    cache.upsert_daily_basic_bulk([
        {"ts_code": "600000.SH", "trade_date": "20240102", "total_mv": 2_000_000.0, "circ_mv": 1_800_000.0},
        {"ts_code": "600000.SH", "trade_date": "20240101", "total_mv": 1_000_000.0, "circ_mv": 900_000.0},
        {"ts_code": "000001.SZ", "trade_date": "20240101", "total_mv": 5_000_000.0, "circ_mv": 4_000_000.0},
    ])
    rows = cache.get_daily_basic_for_code("600000.SH")
    assert [r["trade_date"] for r in rows] == ["20240101", "20240102"]  # 升序
    assert rows[0]["total_mv"] == 1_000_000.0
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/winrate/test_cache_market_cap.py -v`
Expected: FAIL（`AttributeError: 'CacheManager' object has no attribute 'get_daily_basic_for_code'`）。

- [ ] **Step 3: 实现方法**

在 `cache_manager.py` 的 `get_daily_basic(self, trade_date)` 方法之后新增：
```python
    def get_daily_basic_for_code(self, code: str) -> list[dict]:
        """Return a single code's market-cap series ascending by trade_date."""
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT trade_date, total_mv, circ_mv FROM daily_basic_cache "
                "WHERE ts_code = ? ORDER BY trade_date ASC",
                (code,),
            ).fetchall()
        return [dict(r) for r in rows]
```
（确认文件顶部已 `import sqlite3`；若 `_get_conn` 用法不同，参照同文件既有方法的连接写法。）

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/winrate/test_cache_market_cap.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/data/cache_manager.py tests/winrate/test_cache_market_cap.py
git commit -m "feat(cache): get_daily_basic_for_code for per-stock market-cap series"
```

---

### Task 7: `winrate/reporter.py` — 汇总统计 + 分买点导出

**Files:**
- Create: `src/marketreview/winrate/reporter.py`
- Test: `tests/winrate/test_reporter.py`

**Interfaces:**
- Consumes: `TradeResult`（Task 3）、`WinrateConfig`（Task 1）。
- Produces:
  - `BuyPointStats`（dataclass）
  - `aggregate(trades: list[TradeResult]) -> dict[str, BuyPointStats]`（键=买点名）
  - `export_rows(trades, buy_point) -> list[dict]`（按 code、signal_date 排序的明细行）
  - `export_csv(trades, cfg, buy_point, path) -> None`（顶部写配置注释块 + 明细）

- [ ] **Step 1: 写失败测试**

`tests/winrate/test_reporter.py`：
```python
from marketreview.winrate.config import WinrateConfig
from marketreview.winrate.trade_sim import TradeResult
from marketreview.winrate import reporter as R


def _tr(bp, code, reason, pnl, mfp, success, hold=3):
    return TradeResult(
        buy_point=bp, code=code, name="x", signal_date="20240101",
        entry_date="20240102", entry_price=10.0, exit_date="20240105",
        exit_price=10 * (1 + pnl / 100), exit_reason=reason, mfp_pct=mfp,
        hold_days=hold, pnl_pct=pnl, success=success,
    )


def test_aggregate_counts_and_rates():
    trades = [
        _tr("均线支撑", "A.SH", "大胜利", 20, 22, True),
        _tr("均线支撑", "B.SH", "小胜利", 5, 12, True),
        _tr("均线支撑", "C.SH", "盘中止损", -5, 3, False),
        _tr("均线支撑", "D.SH", "收盘止损", -2, 4, False),
        _tr("回调一半", "E.SH", "大胜利", 20, 25, True),
    ]
    stats = R.aggregate(trades)
    ma = stats["均线支撑"]
    assert ma.n == 4
    assert ma.big_win_n == 1
    assert ma.small_win_n == 1
    assert ma.stop_n == 1          # 盘中止损
    assert ma.loss_n == 1          # 收盘止损且 pnl<0
    assert round(ma.win_rate, 3) == 0.5     # (1+1)/4
    assert round(ma.expectancy_pct, 2) == round((20 + 5 - 5 - 2) / 4, 2)
    assert stats["回调一半"].n == 1


def test_export_rows_sorted_by_code(tmp_path):
    trades = [
        _tr("均线支撑", "B.SH", "大胜利", 20, 22, True),
        _tr("均线支撑", "A.SH", "小胜利", 5, 12, True),
        _tr("回调一半", "Z.SH", "大胜利", 20, 22, True),  # 应被过滤掉
    ]
    rows = R.export_rows(trades, "均线支撑")
    assert [r["code"] for r in rows] == ["A.SH", "B.SH"]


def test_export_csv_writes_config_header(tmp_path):
    cfg = WinrateConfig()
    trades = [_tr("均线支撑", "A.SH", "大胜利", 20, 22, True)]
    out = tmp_path / "x.csv"
    R.export_csv(trades, cfg, "均线支撑", out)
    text = out.read_text(encoding="utf-8-sig")
    assert "判赢阈值" in text or "win_threshold_pct" in text
    assert "A.SH" in text
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/winrate/test_reporter.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现 reporter.py**

`src/marketreview/winrate/reporter.py`：
```python
"""汇总每个买点的统计；按买点分开导出带配置的明细。"""
from __future__ import annotations
import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path

from .config import WinrateConfig
from .trade_sim import TradeResult


@dataclass
class BuyPointStats:
    buy_point: str
    n: int
    win_rate: float
    big_win_n: int
    small_win_n: int
    stop_n: int
    loss_n: int
    avg_hold_days: float
    expectancy_pct: float


def aggregate(trades: list[TradeResult]) -> dict[str, BuyPointStats]:
    groups: dict[str, list[TradeResult]] = {}
    for t in trades:
        groups.setdefault(t.buy_point, []).append(t)

    out: dict[str, BuyPointStats] = {}
    for bp, ts in groups.items():
        n = len(ts)
        big = sum(1 for t in ts if t.exit_reason == "大胜利")
        small = sum(1 for t in ts if t.exit_reason == "小胜利")
        stop = sum(1 for t in ts if t.exit_reason == "盘中止损")
        loss = sum(1 for t in ts
                   if t.exit_reason in ("收盘止损", "时间止损", "回测结束") and t.pnl_pct < 0)
        wins = sum(1 for t in ts if t.success)
        out[bp] = BuyPointStats(
            buy_point=bp, n=n,
            win_rate=(wins / n) if n else 0.0,
            big_win_n=big, small_win_n=small, stop_n=stop, loss_n=loss,
            avg_hold_days=(sum(t.hold_days for t in ts) / n) if n else 0.0,
            expectancy_pct=(sum(t.pnl_pct for t in ts) / n) if n else 0.0,
        )
    return out


_EXPORT_FIELDS = [
    "buy_point", "code", "name", "signal_date", "entry_date", "entry_price",
    "exit_date", "exit_price", "exit_reason", "mfp_pct", "hold_days", "pnl_pct",
    "success", "short_ma_state", "long_ma_state", "market_cap_yi", "cap_bucket",
    "industry_l1", "industry_l2",
]


def export_rows(trades: list[TradeResult], buy_point: str) -> list[dict]:
    rows = [asdict(t) for t in trades if t.buy_point == buy_point]
    rows.sort(key=lambda r: (r["code"], r["signal_date"]))
    return rows


def export_csv(trades: list[TradeResult], cfg: WinrateConfig,
               buy_point: str, path: str | Path) -> None:
    rows = export_rows(trades, buy_point)
    path = Path(path)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(f"# winrate export | buy_point={buy_point}\n")
        f.write("# config=" + json.dumps(asdict(cfg), ensure_ascii=False) + "\n")
        writer = csv.DictWriter(f, fieldnames=_EXPORT_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in _EXPORT_FIELDS})
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/winrate/test_reporter.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/winrate/reporter.py tests/winrate/test_reporter.py
git commit -m "feat(winrate): reporter aggregation + per-buypoint CSV export"
```

---

### Task 8: `scripts/backfill_market_cap.py` — 补齐历史市值

**Files:**
- Create: `scripts/backfill_market_cap.py`
- Test: 无（一次性数据脚本，用运行输出验证）

**Interfaces:**
- Consumes: `DataProvider._ensure_daily_basic_loaded(start, end)`（已存在）。

- [ ] **Step 1: 写脚本**

`scripts/backfill_market_cap.py`：
```python
"""补齐历史 daily_basic（市值）到全回测窗口。幂等：已缓存区间自动跳过。

用法: python scripts/backfill_market_cap.py [START] [END]
默认 START=20230921, END=最新交易日。
"""
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
load_dotenv()

from marketreview.data.data_provider import DataProvider  # noqa: E402


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "20230921"
    end = sys.argv[2] if len(sys.argv) > 2 else None

    dp = DataProvider(tushare_token=os.getenv("TUSHARE_TOKEN"))
    if end is None:
        end = dp.cache.get_daily_dates_in_range("20230921", "20991231")[-1]

    print(f"补齐市值: {start} ~ {end}")

    def cb(kind, i, total, label):
        print(f"  [{kind}] {i}/{total} {label}")

    pages = dp._ensure_daily_basic_loaded(start, end, progress_cb=cb)
    print(f"完成，拉取 {pages} 页。")

    # 校验覆盖
    dates = dp.cache.get_daily_basic_dates_in_range(start, end)
    print(f"daily_basic 覆盖交易日: {len(dates)} 个，"
          f"{dates[0] if dates else '?'} ~ {dates[-1] if dates else '?'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行脚本补齐数据**

Run: `python scripts/backfill_market_cap.py`
Expected: 打印补齐进度；最后 `daily_basic 覆盖交易日: N 个, 20230921 ~ ...`（N 与日线交易日数量接近）。

- [ ] **Step 3: 校验（sqlite 直查）**

Run:
```bash
python -c "import sqlite3; c=sqlite3.connect('data/marketreview.db'); print(c.execute(\"SELECT MIN(trade_date), MAX(trade_date), COUNT(DISTINCT trade_date) FROM daily_basic_cache\").fetchone())"
```
Expected: MIN 约 `20230921`，日期数与日线接近（数百）。

- [ ] **Step 4: Commit**

```bash
git add scripts/backfill_market_cap.py
git commit -m "feat(scripts): backfill historical market cap for winrate filters"
```

---

### Task 9: `DashboardService.run_winrate_scan` + 版本号

**Files:**
- Modify: `dashboard/services/dashboard_service.py`（新增方法 + `_AI_VERSION` 8.8.0→9.0.0）
- Test: `tests/winrate/test_service_winrate.py`

**Interfaces:**
- Produces: `DashboardService.run_winrate_scan(cfg: WinrateConfig, progress_cb=None) -> tuple[dict[str, BuyPointStats], list[TradeResult]]`

- [ ] **Step 1: 写失败测试（打桩 run_scan，避免真实全市场）**

`tests/winrate/test_service_winrate.py`：
```python
from unittest.mock import patch
from marketreview.winrate.config import WinrateConfig
from marketreview.winrate.trade_sim import TradeResult


def _fake_trade(bp="均线支撑"):
    return TradeResult(
        buy_point=bp, code="A.SH", name="x", signal_date="20240101",
        entry_date="20240102", entry_price=10.0, exit_date="20240105",
        exit_price=12.0, exit_reason="大胜利", mfp_pct=22.0, hold_days=3,
        pnl_pct=20.0, success=True,
    )


def test_run_winrate_scan_returns_stats_and_trades():
    from services.dashboard_service import DashboardService
    svc = DashboardService()
    cfg = WinrateConfig(buy_points=["均线支撑"])
    with patch("marketreview.winrate.scan_engine.run_scan",
               return_value=[_fake_trade(), _fake_trade()]):
        stats, trades = svc.run_winrate_scan(cfg)
    assert len(trades) == 2
    assert stats["均线支撑"].n == 2
    assert stats["均线支撑"].win_rate == 1.0
```

> 注：测试需能 `import services.dashboard_service`。若 `dashboard/` 不在包路径，在 `tests/conftest.py` 追加 `dashboard/` 到 `sys.path`（见下一步）。

- [ ] **Step 2: 补 conftest 路径 + 运行验证失败**

在 `tests/conftest.py` 末尾追加：
```python
DASH = Path(__file__).resolve().parent.parent / "dashboard"
if DASH.exists() and str(DASH) not in sys.path:
    sys.path.insert(0, str(DASH))
```

Run: `python -m pytest tests/winrate/test_service_winrate.py -v`
Expected: FAIL（`AttributeError: ... has no attribute 'run_winrate_scan'`）。

- [ ] **Step 3: 实现 service 方法 + 版本号**

在 `dashboard/services/dashboard_service.py` 中：

(a) 把 `_AI_VERSION = "8.8.0"` 改为 `_AI_VERSION = "9.0.0"`。

(b) 在类中新增方法（放在其它 backtest 方法附近）：
```python
    def run_winrate_scan(self, cfg, progress_cb=None):
        """运行买点胜率全市场扫描，返回 (每买点统计, 全部交易明细)。"""
        from marketreview.winrate.scan_engine import run_scan
        from marketreview.winrate.reporter import aggregate
        trades = run_scan(self._dp, cfg, progress_cb=progress_cb)
        stats = aggregate(trades)
        return stats, trades
```
（确认 `self._dp` 是本类持有的 `DataProvider` 实例——旧回测方法已用 `self._dp`，沿用。）

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/winrate/test_service_winrate.py -v`
Expected: PASS。

- [ ] **Step 5: 全量测试回归**

Run: `python -m pytest tests/winrate -v`
Expected: 全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add dashboard/services/dashboard_service.py tests/winrate/test_service_winrate.py tests/conftest.py
git commit -m "feat(winrate): DashboardService.run_winrate_scan + bump AI version 9.0.0"
```

---

### Task 10: 页面 `dashboard/pages/06_买点胜率.py`（手动验证）

**Files:**
- Create: `dashboard/pages/06_买点胜率.py`
- 验证：重启 Streamlit + 浏览器手验（无 pytest）

**Interfaces:**
- Consumes: `DashboardService.run_winrate_scan`、`WinrateConfig`、`parse_winrate_config`、`aggregate`、`export_rows`/`export_csv`、`cap_bucket`。

- [ ] **Step 1: 写页面**

`dashboard/pages/06_买点胜率.py`：
```python
"""买点胜率回测 — 全市场扫描单买点胜率。"""
import io
import streamlit as st

from services.dashboard_service import DashboardService
from rendering.styles import PAGE_CSS
from marketreview.winrate.config import parse_winrate_config, WinrateConfig, ALL_BUY_POINTS
from marketreview.winrate.reporter import aggregate, export_rows
from dataclasses import replace

st.set_page_config(page_title="买点胜率", page_icon="🎯", layout="wide")
st.markdown(PAGE_CSS, unsafe_allow_html=True)

svc = DashboardService()
st.title("🎯 买点胜率回测")
st.caption(f"全市场扫描 · 单买点胜率 ｜ AI v{DashboardService._AI_VERSION}")

base = parse_winrate_config("config/winrate_config.txt")

# ── 配置区 ──
c1, c2, c3 = st.columns(3)
with c1:
    buy_points = st.multiselect("买点（可多选）", ALL_BUY_POINTS, default=base.buy_points)
    win_th = st.number_input("判赢阈值%（盘中浮盈）", 1.0, 50.0, base.win_threshold_pct)
with c2:
    short_ma = st.selectbox("短期均线排列", ["无关", "多头", "空头"],
                            index=["无关", "多头", "空头"].index(base.short_ma_arrange))
    long_ma = st.selectbox("长期均线排列", ["无关", "多头", "空头"],
                           index=["无关", "多头", "空头"].index(base.long_ma_arrange))
with c3:
    mv_min = st.number_input("市值下限(亿)", 0.0, 100000.0, base.mv_min_yi)
    mv_max = st.number_input("市值上限(亿, 0=不限)", 0.0, 100000.0, base.mv_max_yi)

c4, c5, c6 = st.columns(3)
with c4:
    start_date = st.text_input("开始日期(YYYYMMDD)", base.start_date)
with c5:
    time_stop = st.number_input("时间止损天数", 1, 250, base.time_stop_days)
with c6:
    workers = st.number_input("并发数", 1, 16, base.max_workers)

cfg = replace(
    base, buy_points=buy_points, win_threshold_pct=win_th,
    short_ma_arrange=short_ma, long_ma_arrange=long_ma,
    mv_min_yi=mv_min, mv_max_yi=mv_max, start_date=start_date,
    time_stop_days=int(time_stop), max_workers=int(workers),
)

if st.button("▶ 运行扫描", type="primary", disabled=not buy_points):
    prog = st.progress(0.0)
    status = st.empty()

    def cb(done, total):
        prog.progress(done / total)
        status.text(f"已扫描 {done}/{total} 只股票")

    with st.spinner("全市场扫描中..."):
        stats, trades = svc.run_winrate_scan(cfg, progress_cb=cb)
    prog.progress(1.0)
    status.empty()
    st.session_state.wr_stats = stats
    st.session_state.wr_trades = trades

# ── 结果 ──
if st.session_state.get("wr_stats"):
    stats = st.session_state.wr_stats
    trades = st.session_state.wr_trades

    st.subheader("📊 买点对比汇总")
    st.dataframe([{
        "买点": s.buy_point, "触发次数": s.n,
        "胜率": f"{s.win_rate:.1%}",
        "大胜利率": f"{(s.big_win_n / s.n if s.n else 0):.1%}",
        "小胜利率": f"{(s.small_win_n / s.n if s.n else 0):.1%}",
        "止损率": f"{(s.stop_n / s.n if s.n else 0):.1%}",
        "亏损率": f"{(s.loss_n / s.n if s.n else 0):.1%}",
        "平均持有天": f"{s.avg_hold_days:.1f}",
        "期望收益": f"{s.expectancy_pct:+.2f}%",
    } for s in stats.values()], use_container_width=True, hide_index=True)

    # 每个买点独立区块
    for bp, s in stats.items():
        st.markdown(f"### 🎯 {bp} — {s.n}次 胜率{s.win_rate:.1%}")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("大胜利", s.big_win_n)
        m2.metric("小胜利", s.small_win_n)
        m3.metric("盘中止损", s.stop_n)
        m4.metric("亏损", s.loss_n)

        rows = export_rows(trades, bp)
        # 导出
        import csv as _csv
        buf = io.StringIO()
        if rows:
            w = _csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        st.download_button(
            f"⬇ 导出 {bp} 明细CSV", buf.getvalue().encode("utf-8-sig"),
            file_name=f"winrate_{bp}_{cfg.start_date}.csv", mime="text/csv",
            key=f"dl_{bp}",
        )
        # 明细（默认收起，按股票分组）
        with st.expander(f"📋 {bp} 逐笔明细（按股票分组）", expanded=False):
            by_code: dict[str, list] = {}
            for r in rows:
                by_code.setdefault(r["code"], []).append(r)
            for code, crows in by_code.items():
                name = crows[0].get("name", "")
                st.markdown(f"**{name} {code}** — {len(crows)}笔")
                st.dataframe([{
                    "信号日": r["signal_date"], "进场": f'{r["entry_date"]}@{r["entry_price"]}',
                    "出场": f'{r["exit_date"]}@{r["exit_price"]}', "原因": r["exit_reason"],
                    "浮盈%": r["mfp_pct"], "盈亏%": r["pnl_pct"], "持有": r["hold_days"],
                    "短均": r["short_ma_state"], "长均": r["long_ma_state"], "市值": r["cap_bucket"],
                } for r in crows], use_container_width=True, hide_index=True)
```

- [ ] **Step 2: 重启 Streamlit（按 streamlit-cache-clear 规范）**

Run（参照 `scripts/kill_port.py` / restart 脚本）：
```bash
python scripts/kill_port.py 8501 || true
# 清 __pycache__ 后重启（见 memory: streamlit-cache-clear）
```
然后启动 dashboard（见 memory: dashboard-setup，端口 8501）。

- [ ] **Step 3: 浏览器手动验证**

- 侧边栏出现「🎯 买点胜率」，且**不再有**「战法回测」（Task 11 隐藏）。
- 选默认买点 + 长期多头 + 市值下限100，点「运行扫描」→ 进度条推进到 100%。
- 出现对比汇总表 + 每买点独立区块（大/小胜利/止损/亏损）+ 导出按钮 + 折叠明细（按股票分组）。
- 抽查一只票：点开明细，进出场/原因/浮盈合理；日志 `logs/` 有「扫描完成: N只股票, 共 M 笔」。

- [ ] **Step 4: Commit**

```bash
git add dashboard/pages/06_买点胜率.py
git commit -m "feat(winrate): 买点胜率 dashboard page"
```

---

### Task 11: 隐藏旧「战法回测」入口

**Files:**
- Move: `dashboard/pages/05_战法回测.py` → `dashboard/_archived/05_战法回测.py`
- Create: `dashboard/_archived/README.md`（说明为何归档）

**Interfaces:** 无（仅移动文件，代码保留）。

- [ ] **Step 1: 移动文件**

```bash
mkdir -p dashboard/_archived
git mv dashboard/pages/05_战法回测.py dashboard/_archived/05_战法回测.py
```

- [ ] **Step 2: 写归档说明**

`dashboard/_archived/README.md`：
```markdown
# 归档页面

`05_战法回测.py` — 旧的组合级回测（自选股票池 × 战法系统），已被
`pages/06_买点胜率.py`（全市场买点胜率）取代。代码保留备查；从
`pages/` 移出即从侧边栏隐藏。相关 service 方法（load_backtest_pools 等）与
`src/marketreview/backtest/` 均保留。
```

- [ ] **Step 3: 验证侧边栏**

重启 Streamlit（同 Task 10 Step 2），确认侧边栏**无**「战法回测」、**有**「买点胜率」，其余页面正常。

- [ ] **Step 4: Commit**

```bash
git add dashboard/_archived/ dashboard/pages/
git commit -m "chore: archive old 战法回测 page (hidden from sidebar, code kept)"
```

---

## Self-Review

**1. Spec coverage**（逐节核对）：
- §2 概念（band/episode/成功/大小胜利）→ Task 3（simulate_trade 判赢+分档）、Task 4（band 复用）✅
- §3 模块结构 → Task 1~7 覆盖 config/filters/buypoint_defs/trade_sim/scan_engine/reporter；backfill=Task 8；page=Task 10 ✅
- §4 两阶段日模型（先止损、开盘/盘中/收盘、T+1、时间止损、涨跌停可达性）→ Task 3 全覆盖，测试含 priority/close-stop/time-stop ✅
- §5 TradeResult + 标签 → Task 3 dataclass + Task 5 `_tag` 回填 ✅
- §6 过滤器（短/长均线、市值上下限、行业、上市时长）→ Task 2 ✅（注：市值改回上下限，四档转为标签，Task 5 `cap_bucket` 打标签）
- §7 买点接入（3个，收盘止损映射）→ Task 4 ✅
- §8 配置 → Task 1 + `config/winrate_config.txt` ✅
- §9 输出/页面（并发+loading、按买点分块、按股票分组明细、导出）→ Task 10 ✅
- §9.1 导出（分买点、带配置、按股票排序）→ Task 7 `export_csv`/`export_rows` + Task 10 下载按钮 ✅
- §10 补齐市值 → Task 8 ✅
- §11 隐藏旧页 → Task 11 ✅
- §13 版本号 9.0.0 → Task 9 ✅

**2. Placeholder scan**：无 TBD/TODO；每个代码步骤含完整代码。✅

**3. Type consistency**：`BuyPointSignal`/`TradeResult`/`WinrateConfig` 字段在 Task 3 定义，Task 4/5/7/9/10 一致引用；`run_scan`/`aggregate`/`export_rows` 签名跨任务一致。`get_daily_basic_for_code` 在 Task 6 定义、Task 5 调用（Task 5 先写但依赖 Task 6——执行时**先做 Task 6 再做 Task 5**，或按此顺序：Task 6 提前）。⚠️ 见下方执行提示。

> **执行顺序提示**：Task 5 的 `run_scan` 调用 Task 6 的 `get_daily_basic_for_code`。建议执行顺序：0 → 1 → 2 → 3 → 4 → **6 → 5** → 7 → 8 → 9 → 10 → 11。`scan_stock`（Task 5 单测）不依赖 Task 6，可先过；但 `run_scan` 集成需 Task 6 就位。
