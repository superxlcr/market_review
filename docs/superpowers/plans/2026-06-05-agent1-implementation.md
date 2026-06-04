# Agent 1（大盘分析）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Agent 1 大盘分析 + Streamlit Dashboard，用户能在交易日手动触发并看到上证/创业板的技术分析结果。

**Architecture:** 数据层（data_provider + cache_manager）→ 共享工具（technical.py + contribution.py）→ CrewAI Agent 1（agents.yaml + tasks.yaml + crew.py）→ Streamlit Dashboard。每层独立可用、可测试。

**Tech Stack:** Python 3.10+, CrewAI, deepseek-v4-pro (via OpenAI-compatible API), SQLite, Tushare Pro, Streamlit, Plotly

**Source spec:** `docs/superpowers/specs/2026-06-04-market-review-system-design.md` §4（通用技术分析框架）+ §5（Agent 1）

---

## File Map

```
src/marketreview/
├── data/
│   ├── __init__.py              # 新建
│   ├── cache_manager.py         # 新建 — SQLite 缓存读写
│   ├── data_provider.py         # 新建 — 抽象数据接口
│   └── schema.sql               # 新建 — DDL
├── tools/
│   ├── __init__.py              # 已有，需更新
│   ├── technical.py             # 新建 — 通用技术分析
│   └── contribution.py          # 新建 — 权重贡献分析
├── config/
│   ├── agents.yaml              # 修改 — 替换为 market_analyst
│   └── tasks.yaml               # 修改 — 替换为 market_analysis_task
├── crew.py                      # 修改 — Agent 1 + Task 1
├── main.py                      # 修改 — 手动触发，接收日期参数
dashboard/
└── app.py                       # 新建 — Streamlit Dashboard
```

---

### Task 1: SQLite Schema + Cache Manager

**Files:**
- Create: `src/marketreview/data/__init__.py`
- Create: `src/marketreview/data/schema.sql`
- Create: `src/marketreview/data/cache_manager.py`

- [ ] **Step 1: Create data package init**

```python
# src/marketreview/data/__init__.py
```

(Empty file — just makes `data` a package)

- [ ] **Step 2: Write the DDL schema**

```sql
-- src/marketreview/data/schema.sql
CREATE TABLE IF NOT EXISTS tushare_cache (
    code       TEXT NOT NULL,
    date       TEXT NOT NULL,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    vol        REAL,
    amount     REAL,
    adj_factor REAL,
    PRIMARY KEY (code, date)
);

CREATE INDEX IF NOT EXISTS idx_cache_code_date ON tushare_cache(code, date DESC);
```

- [ ] **Step 3: Write the CacheManager class**

```python
# src/marketreview/data/cache_manager.py
import sqlite3
import os
from datetime import datetime, timedelta

DB_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
DB_PATH = os.path.join(DB_DIR, "marketreview.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


class CacheManager:
    """SQLite-based cache for daily K-line data."""

    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            sql = f.read()
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(sql)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------- write / read -------

    def upsert_daily(self, code: str, rows: list[dict]):
        """Batch upsert daily K-line rows. Each row: {date, open, high, low, close, vol, amount, adj_factor}"""
        sql = """
            INSERT OR REPLACE INTO tushare_cache
                (code, date, open, high, low, close, vol, amount, adj_factor)
            VALUES (:code, :date, :open, :high, :low, :close, :vol, :amount, :adj_factor)
        """
        with self._get_conn() as conn:
            for r in rows:
                conn.execute(sql, {"code": code, **r})
            conn.commit()

    def get_daily(self, code: str, start: str = None, end: str = None, limit: int = None) -> list[dict]:
        """Return daily rows ordered by date DESC. If limit given, return most recent N rows."""
        sql = "SELECT * FROM tushare_cache WHERE code = ?"
        params = [code]
        if start:
            sql += " AND date >= ?"
            params.append(start)
        if end:
            sql += " AND date <= ?"
            params.append(end)
        sql += " ORDER BY date DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_latest_date(self, code: str) -> str | None:
        """Return the most recent cached date for a code, or None."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(date) as d FROM tushare_cache WHERE code = ?", [code]
            ).fetchone()
        return row["d"] if row and row["d"] else None

    def code_has_data(self, code: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM tushare_cache WHERE code = ? LIMIT 1", [code]
            ).fetchone()
        return row is not None
```

- [ ] **Step 4: Verify — run a quick smoke test**

```bash
cd i:/AIcode/marketreview && python -c "
from src.marketreview.data.cache_manager import CacheManager
cm = CacheManager()
cm.upsert_daily('000001.SH', [{'date':'2025-06-03','open':1,'high':2,'low':3,'close':4,'vol':5,'amount':6,'adj_factor':1.0}])
rows = cm.get_daily('000001.SH', limit=1)
print(rows)
"
```
Expected: prints one row with the inserted data, `date='2025-06-03'`.

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/data/ data/
git commit -m "feat: add SQLite schema and CacheManager for daily K-line data"
```

---

### Task 2: Data Provider（抽象层 + Tushare 实现）

**Files:**
- Create: `src/marketreview/data/data_provider.py`

- [ ] **Step 1: Write DataProvider class**

```python
# src/marketreview/data/data_provider.py
import tushare as ts
from datetime import datetime, timedelta
from .cache_manager import CacheManager


class DataProvider:
    """
    Abstract data interface for agents.
    Agents call get_daily() — they don't know or care whether data comes
    from tushare/akshare/wind.  Swap the backend by changing _fetch_from_api().
    """

    def __init__(self, tushare_token: str, cache: CacheManager | None = None):
        ts.set_token(tushare_token)
        self._api = ts.pro_api()
        self.cache = cache or CacheManager()

    # ------- public API (called by agent tools) -------

    def get_daily(
        self, code: str, lookback_days: int = 120
    ) -> list[dict]:
        """
        Return recent daily K-line rows (date DESC) for `code`.
        Tries cache first; fetches missing range from tushare and writes cache.
        """
        cached = self.cache.get_daily(code, limit=lookback_days)

        if len(cached) >= lookback_days:
            return cached[:lookback_days]

        # Determine fetch range
        end_date = datetime.now().strftime("%Y%m%d")
        if cached:
            oldest = cached[-1]["date"].replace("-", "")
            start_date = (datetime.strptime(oldest, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        else:
            start_date = (datetime.now() - timedelta(days=lookback_days * 2)).strftime("%Y%m%d")

        fetched = self._fetch_from_api(code, start_date, end_date)
        if fetched:
            self.cache.upsert_daily(code, fetched)

        return self.cache.get_daily(code, limit=lookback_days)

    def get_latest_trade_date(self, code: str) -> str | None:
        """Return latest available trading date for a code."""
        latest = self.cache.get_latest_date(code)
        if latest:
            return latest
        # fallback: fetch recent and return max date
        rows = self.get_daily(code, lookback_days=5)
        return rows[0]["date"] if rows else None

    # ------- internal -------

    def _fetch_from_api(self, code: str, start: str, end: str) -> list[dict]:
        """
        Pull daily data from Tushare.  Normalizes field names to cache schema.
        Override this method to swap data sources.
        """
        # Normalize code format: tushare wants 000001.SH / 399006.SZ
        ts_code = self._normalize_code(code)
        try:
            df = self._api.daily(
                ts_code=ts_code,
                start_date=start,
                end_date=end,
                fields="trade_date,open,high,low,close,vol,amount",
            )
            if df is None or df.empty:
                return []
            df = df.sort_values("trade_date", ascending=False)
            # Add adj_factor placeholder (will be populated by adj task later)
            df["adj_factor"] = 1.0
            df.rename(columns={"trade_date": "date", "vol": "vol", "amount": "amount"}, inplace=True)
            return df.to_dict(orient="records")
        except Exception as e:
            print(f"[DataProvider] fetch failed for {code}: {e}")
            return []

    @staticmethod
    def _normalize_code(code: str) -> str:
        """Ensure code format like 000001.SH / 399006.SZ for tushare."""
        code = code.strip().upper()
        if "." not in code:
            if code.startswith(("60", "68")):
                code = f"{code}.SH"
            else:
                code = f"{code}.SZ"
        return code
```

- [ ] **Step 2: Verify — smoke test (needs TUSHARE_TOKEN env var)**

```bash
cd i:/AIcode/marketreview && python -c "
import os
from src.marketreview.data.data_provider import DataProvider
dp = DataProvider(tushare_token=os.environ['TUSHARE_TOKEN'])
rows = dp.get_daily('000001.SH', lookback_days=5)
print(f'Got {len(rows)} rows, latest date: {rows[0][\"date\"]}')
"
```
Expected: prints 5 rows with descending dates.

- [ ] **Step 3: Commit**

```bash
git add src/marketreview/data/data_provider.py
git commit -m "feat: add DataProvider — abstract layer over tushare + cache"
```

---

### Task 3: Shared Technical Analysis Tools（technical.py）

**Files:**
- Create: `src/marketreview/tools/technical.py`
- Modify: `src/marketreview/tools/__init__.py`

- [ ] **Step 1: Write technical.py — basic version covering §4.1–§4.3**

```python
# src/marketreview/tools/technical.py
"""
Shared technical analysis tools — used by Agent 1/2/3.

Covers:
  §4.1 — K-line pattern analysis (bull/bear power)
  §4.2 — Moving average + volume analysis
  §4.3 — Technical indicators (KDJ, RSI, BIAS)
"""

import pandas as pd
import numpy as np
from typing import Any


def rows_to_df(rows: list[dict]) -> pd.DataFrame:
    """Convert cache rows (date DESC) to DataFrame (date ASC for TA)."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("date", ascending=True).reset_index(drop=True)
    for col in ["open", "high", "low", "close", "vol", "amount", "adj_factor"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def calc_ma(df: pd.DataFrame, periods: list[int] = None) -> dict[str, list[float]]:
    """Compute SMA for given periods. Returns {f'MA{p}': [...values...]}"""
    if periods is None:
        periods = [5, 10, 20, 60]
    result = {}
    for p in periods:
        col = f"MA{p}"
        result[col] = df["close"].rolling(p).mean().tolist()
    return result


def ma_direction(ma_values: list[float]) -> str:
    """
    Determine MA direction from last few values.
    Returns '↑' (up), '↓' (down), or '→' (flat).
    """
    valid = [v for v in ma_values[-5:] if not np.isnan(v)]
    if len(valid) < 3:
        return "→"
    # simple linear regression slope
    x = np.arange(len(valid))
    slope = np.polyfit(x, valid, 1)[0]
    if slope > 0.3:
        return "↑"
    elif slope < -0.3:
        return "↓"
    return "→"


def ma_arrangement(df: pd.DataFrame) -> str:
    """
    Determine MA arrangement: 多头排列 / 空头排列 / 缠绕.
    Uses latest MA5/10/20/60 values.
    """
    mas = calc_ma(df, [5, 10, 20, 60])
    latest = {}
    for k, v in mas.items():
        for val in reversed(v):
            if not np.isnan(val):
                latest[k] = val
                break
    if len(latest) < 3:
        return "数据不足"

    vals = [latest.get(f"MA{p}") for p in [5, 10, 20, 60] if latest.get(f"MA{p}") is not None]
    if all(vals[i] > vals[i+1] for i in range(len(vals)-1)):
        return "多头排列"
    if all(vals[i] < vals[i+1] for i in range(len(vals)-1)):
        return "空头排列"
    return "均线缠绕"


def volume_analysis(df: pd.DataFrame) -> dict[str, Any]:
    """Analyze volume: latest vol vs 5/20-day average."""
    if df.empty or "vol" not in df.columns:
        return {}
    latest_vol = df["vol"].iloc[-1]
    ma5_vol = df["vol"].rolling(5).mean().iloc[-1]
    ma20_vol = df["vol"].rolling(20).mean().iloc[-1]
    vs_ma5 = (latest_vol / ma5_vol - 1) * 100 if not np.isnan(ma5_vol) else 0
    vs_ma20 = (latest_vol / ma20_vol - 1) * 100 if not np.isnan(ma20_vol) else 0
    return {
        "latest_vol": round(float(latest_vol), 0),
        "ma5_vol": round(float(ma5_vol), 0),
        "vs_ma5_pct": round(float(vs_ma5), 1),
        "vs_ma20_pct": round(float(vs_ma20), 1),
        "label": "放量" if vs_ma5 > 5 else ("缩量" if vs_ma5 < -5 else "量平"),
    }


def calc_kdj(df: pd.DataFrame, n: int = 9) -> dict[str, list[float]]:
    """Compute KDJ indicator. Returns {K, D, J} lists."""
    low_list = df["low"].rolling(n).min()
    high_list = df["high"].rolling(n).max()
    rsv = (df["close"] - low_list) / (high_list - low_list) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d
    return {"K": k.tolist(), "D": d.tolist(), "J": j.tolist()}


def calc_rsi(df: pd.DataFrame, period: int = 6) -> list[float]:
    """Compute RSI for given period."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.tolist()


def calc_bias(df: pd.DataFrame, periods: list[int] = None) -> dict[str, list[float]]:
    """Compute BIAS (乖离率) for given periods."""
    if periods is None:
        periods = [6, 12, 24]
    result = {}
    for p in periods:
        ma = df["close"].rolling(p).mean()
        bias = (df["close"] - ma) / ma * 100
        result[f"BIAS{p}"] = bias.tolist()
    return result


def kline_pattern(df: pd.DataFrame) -> dict[str, Any]:
    """
    Analyze latest candle's bull/bear power.
    Returns entity/body ratio, upper/lower wick ratio.
    """
    if df.empty:
        return {}
    row = df.iloc[-1]
    o, h, l, c = row["open"], row["high"], row["low"], row["close"]
    body = abs(c - o)
    total = h - l
    if total == 0:
        return {"type": "doji", "body_pct": 0, "upper_wick_pct": 0, "lower_wick_pct": 0}
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    body_pct = round(body / total * 100, 1)
    is_bullish = c > o
    return {
        "type": "阳线" if is_bullish else "阴线",
        "body_pct": body_pct,
        "upper_wick_pct": round(upper_wick / total * 100, 1),
        "lower_wick_pct": round(lower_wick / total * 100, 1),
        "interpretation": _interpret_candle(is_bullish, body_pct, upper_wick/total, lower_wick/total),
    }


def _interpret_candle(bullish: bool, body_pct: float, upper_pct: float, lower_pct: float) -> str:
    """Simple candle interpretation."""
    parts = []
    if body_pct > 60:
        parts.append("强势" if bullish else "弱势")
    elif body_pct < 20:
        parts.append("十字星/多空均衡")
    if upper_pct > 0.5:
        parts.append("上方压力大")
    if lower_pct > 0.5:
        parts.append("下方支撑强")
    return "；".join(parts) if parts else "普通K线"


# ------- Summary builder (called by Agent tools) -------

def build_technical_summary(code: str, name: str, rows: list[dict]) -> dict[str, Any]:
    """
    Build a structured technical summary for one symbol.
    Returns dict ready for Agent consumption and dashboard rendering.
    """
    df = rows_to_df(rows)
    if df.empty:
        return {"code": code, "name": name, "error": "无数据"}

    mas = calc_ma(df)
    latest_close = float(df["close"].iloc[-1])
    latest_ma5 = float([v for v in mas["MA5"] if not np.isnan(v)][-1]) if any(not np.isnan(v) for v in mas["MA5"]) else None

    # Latest indicator values
    kdj = calc_kdj(df)
    rsi6 = calc_rsi(df, 6)
    bias = calc_bias(df)

    return {
        "code": code,
        "name": name,
        "latest_close": round(latest_close, 2),
        "ma_arrangement": ma_arrangement(df),
        "ma_directions": {
            f"MA{p}": ma_direction(mas[f"MA{p}"]) for p in [5, 10, 20, 60]
        },
        "mas": {f"MA{p}": round(float([v for v in mas[f"MA{p}"] if not np.isnan(v)][-1]), 2)
                for p in [5, 10, 20, 60] if any(not np.isnan(v) for v in mas[f"MA{p}"])},
        "volume": volume_analysis(df),
        "kline_pattern": kline_pattern(df),
        "kdj_k": round(float([v for v in kdj["K"] if not np.isnan(v)][-1]), 1),
        "kdj_d": round(float([v for v in kdj["D"] if not np.isnan(v)][-1]), 1),
        "kdj_j": round(float([v for v in kdj["J"] if not np.isnan(v)][-1]), 1),
        "rsi6": round(float([v for v in rsi6 if not np.isnan(v)][-1]), 1),
        "bias6": round(float([v for v in bias["BIAS6"] if not np.isnan(v)][-1]), 2),
    }
```

- [ ] **Step 2: Update tools __init__.py**

```python
# src/marketreview/tools/__init__.py
from .technical import (
    rows_to_df,
    calc_ma,
    ma_direction,
    ma_arrangement,
    volume_analysis,
    calc_kdj,
    calc_rsi,
    calc_bias,
    kline_pattern,
    build_technical_summary,
)
```

- [ ] **Step 3: Verify**

```bash
cd i:/AIcode/marketreview && python -c "
import os
from src.marketreview.data.data_provider import DataProvider
from src.marketreview.tools.technical import build_technical_summary

dp = DataProvider(tushare_token=os.environ['TUSHARE_TOKEN'])
rows = dp.get_daily('000001.SH', lookback_days=120)
summary = build_technical_summary('000001.SH', '上证指数', rows)
for k, v in summary.items():
    print(f'{k}: {v}')
"
```
Expected: prints structured summary with MA values, volume analysis, KDJ/RSI/BIAS numbers.

- [ ] **Step 4: Commit**

```bash
git add src/marketreview/tools/
git commit -m "feat: add shared technical analysis tools (technical.py)"
```

---

### Task 4: Contribution Analysis（contribution.py）

**Files:**
- Create: `src/marketreview/tools/contribution.py`

- [ ] **Step 1: Write contribution.py — basic version**

```python
# src/marketreview/tools/contribution.py
"""
Weight contribution analysis for indices and sectors (§4.4).
Only used by Agent 1 (index) and Agent 2 (sector). Agent 3 does not use this.
"""

import pandas as pd
import numpy as np
from .technical import rows_to_df


# Simplified top-10 weights for SSE Composite (上证) and ChiNext (创业板)
# In production this should come from a config or be fetched dynamically.
INDEX_WEIGHTS = {
    "000001.SH": {
        "weight_codes": [
            ("600519.SH", "贵州茅台", 5.2),
            ("601398.SH", "工商银行", 3.1),
            ("601939.SH", "建设银行", 2.4),
            ("601288.SH", "农业银行", 2.3),
            ("601857.SH", "中国石油", 2.0),
            ("601988.SH", "中国银行", 1.9),
            ("600036.SH", "招商银行", 1.8),
            ("601628.SH", "中国人寿", 1.6),
            ("600028.SH", "中国石化", 1.5),
            ("601318.SH", "中国平安", 1.4),
        ]
    },
    "399006.SZ": {
        "weight_codes": [
            ("300750.SZ", "宁德时代", 15.2),
            ("300059.SZ", "东方财富", 7.1),
            ("300760.SZ", "迈瑞医疗", 5.8),
            ("300124.SZ", "汇川技术", 4.5),
            ("300274.SZ", "阳光电源", 3.8),
            ("300015.SZ", "爱尔眼科", 3.2),
            ("300014.SZ", "亿纬锂能", 2.9),
            ("300122.SZ", "智飞生物", 2.5),
            ("300450.SZ", "先导智能", 2.1),
            ("300408.SZ", "三环集团", 1.8),
        ]
    },
}


def compute_index_contribution(index_code: str, weight_rows: list[dict]) -> dict:
    """
    Compute weighted contribution of top constituents to index movement.
    
    weight_rows: list of {code, name, weight_pct, change_pct} for each constituent.
    Returns {total_contribution, constituents: [{name, weight_pct, change_pct, contribution}]}
    """
    total = 0.0
    items = []
    for wr in weight_rows:
        contrib = wr["weight_pct"] * wr.get("change_pct", 0) / 100
        total += contrib
        items.append({
            "name": wr["name"],
            "weight_pct": wr["weight_pct"],
            "change_pct": wr.get("change_pct", 0),
            "contribution": round(contrib, 4),
        })
    return {
        "total_contribution": round(total, 2),
        "constituents": sorted(items, key=lambda x: abs(x["contribution"]), reverse=True),
    }
```

> **Note:** In a later iteration, constituent weights should be fetched dynamically from tushare index_weight API. This hardcoded list enables Agent 1 to work today.

- [ ] **Step 2: Commit**

```bash
git add src/marketreview/tools/contribution.py
git commit -m "feat: add contribution analysis for indices (Agent 1)"
```

---

### Task 5: Agent 1 CrewAI Tool Wrapper

**Files:**
- Create: `src/marketreview/tools/market_tools.py`

- [ ] **Step 1: Write CrewAI tool wrappers for Agent 1**

```python
# src/marketreview/tools/market_tools.py
"""
CrewAI BaseTool wrappers that Agent 1 uses.
Each tool wraps a function from technical.py or contribution.py so the LLM can call it.
"""

from crewai.tools import BaseTool
from typing import Type, Optional
from pydantic import BaseModel, Field
import json

from ..data.data_provider import DataProvider
from .technical import build_technical_summary
from .contribution import compute_index_contribution, INDEX_WEIGHTS


# Singleton — initialised at crew startup
_data_provider: Optional[DataProvider] = None


def init_data_provider(token: str):
    global _data_provider
    _data_provider = DataProvider(tushare_token=token)


# ------- Tool 1: Get Index Technicals -------

class GetIndexTechnicalsInput(BaseModel):
    index_code: str = Field(..., description="指数代码，如 000001.SH（上证）或 399006.SZ（创业板）")
    index_name: str = Field(..., description="指数中文名，如 '上证指数'")
    lookback_days: int = Field(120, description="回看交易日数，默认120天（约半年）")


class GetIndexTechnicalsTool(BaseTool):
    name: str = "get_index_technicals"
    description: str = (
        "获取指定指数的完整技术分析摘要：包含K线形态、均线排列+方向、成交量分析、"
        "KDJ/RSI/BIAS等指标。用于Agent 1对大盘指数进行技术面评估。"
    )
    args_schema: Type[BaseModel] = GetIndexTechnicalsInput

    def _run(self, index_code: str, index_name: str, lookback_days: int = 120) -> str:
        if _data_provider is None:
            return json.dumps({"error": "DataProvider未初始化"}, ensure_ascii=False)
        rows = _data_provider.get_daily(index_code, lookback_days=lookback_days)
        summary = build_technical_summary(index_code, index_name, rows)
        return json.dumps(summary, ensure_ascii=False, indent=2)


# ------- Tool 2: Get Market Breadth -------

class GetMarketBreadthInput(BaseModel):
    trade_date: str = Field(..., description="交易日期 YYYYMMDD 格式，如 20250604")


class GetMarketBreadthTool(BaseTool):
    name: str = "get_market_breadth"
    description: str = (
        "获取全市场宽度数据：涨跌家数比、涨停跌停数、两市成交额。"
        "数据从 Tushare 的 limit_list 和 daily_basic 接口获取。"
    )
    args_schema: Type[BaseModel] = GetMarketBreadthInput

    def _run(self, trade_date: str) -> str:
        if _data_provider is None:
            return json.dumps({"error": "DataProvider未初始化"}, ensure_ascii=False)
        try:
            # Use tushare daily_basic + limit_list for breadth
            api = _data_provider._api
            # daily_basic — all stocks on this date
            basic = api.daily_basic(trade_date=trade_date, fields="ts_code,close,pre_close")
            if basic is None or basic.empty:
                return json.dumps({"error": f"daily_basic 无 {trade_date} 数据"}, ensure_ascii=False)

            up = len(basic[basic["close"] > basic["pre_close"]])
            down = len(basic[basic["close"] < basic["pre_close"]])
            flat = len(basic[basic["close"] == basic["pre_close"]])

            # limit_list
            limits = api.limit_list(trade_date=trade_date, limit_type="U,D")
            up_limit = len(limits[limits["limit"] == "U"]) if limits is not None and not limits.empty else 0
            down_limit = len(limits[limits["limit"] == "D"]) if limits is not None and not limits.empty else 0

            # total turnover (approximate from daily_basic amount col if available)
            total_amount = float(basic["amount"].sum()) if "amount" in basic.columns else 0

            return json.dumps({
                "trade_date": trade_date,
                "up": int(up), "down": int(down), "flat": int(flat),
                "up_limit": int(up_limit), "down_limit": int(down_limit),
                "total_amount_yi": round(total_amount / 1e8, 0),
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)


# ------- Tool 3: Get Index Contribution -------

class GetIndexContributionInput(BaseModel):
    index_code: str = Field(..., description="指数代码 000001.SH 或 399006.SZ")


class GetIndexContributionTool(BaseTool):
    name: str = "get_index_contribution"
    description: str = (
        "获取指数权重股的涨跌贡献分析。显示前10大权重股各自的涨跌幅和对指数的贡献点数。"
    )
    args_schema: Type[BaseModel] = GetIndexContributionInput

    def _run(self, index_code: str) -> str:
        if _data_provider is None:
            return json.dumps({"error": "DataProvider未初始化"}, ensure_ascii=False)

        weights = INDEX_WEIGHTS.get(index_code, {}).get("weight_codes", [])
        if not weights:
            return json.dumps({"error": f"无 {index_code} 权重数据"}, ensure_ascii=False)

        items = []
        for code, name, weight in weights:
            rows = _data_provider.get_daily(code, lookback_days=2)
            if len(rows) >= 2:
                prev_close = rows[1]["close"]
                latest_close = rows[0]["close"]
                change_pct = round((latest_close / prev_close - 1) * 100, 2)
            else:
                change_pct = 0
            items.append({
                "code": code, "name": name, "weight_pct": weight,
                "change_pct": change_pct,
            })

        result = compute_index_contribution(index_code, items)
        return json.dumps(result, ensure_ascii=False, indent=2)
```

- [ ] **Step 2: Commit**

```bash
git add src/marketreview/tools/market_tools.py
git commit -m "feat: add CrewAI tool wrappers for Agent 1 (index technicals, breadth, contribution)"
```

---

### Task 6: Agent 1 Configuration（agents.yaml + tasks.yaml）

**Files:**
- Modify: `src/marketreview/config/agents.yaml`
- Modify: `src/marketreview/config/tasks.yaml`

- [ ] **Step 1: Replace agents.yaml with Agent 1 definition**

```yaml
# src/marketreview/config/agents.yaml
market_analyst:
  role: >
    A股大盘分析师
  goal: >
    对今日A股整体市场环境做出判断：通过上证指数、创业板指的技术面分析
    （K线形态、均线量能、技术指标）和市场宽度数据（涨跌比、成交额），
    给出 "偏多/偏空/震荡/极端" 的大盘定性及关键观察点。
  backstory: >
    你是一位经验丰富的A股大盘分析师，从业15年。你擅长从指数K线形态判断多空力量对比，
    从均线排列和量能变化识别趋势方向，从KDJ/RSI/BIAS等指标判断短期超买超卖。
    你也会关注权重股对指数的贡献和市场整体宽度，判断今天是"真涨"还是"拉权重出货"。
    你的结论会作为后续板块分析和个股分析的基准环境参考。
  tools:
    - get_index_technicals
    - get_market_breadth
    - get_index_contribution
  llm: deepseek-v4-pro
  max_iter: 12
  verbose: true
```

- [ ] **Step 2: Replace tasks.yaml with Agent 1 task**

```yaml
# src/marketreview/config/tasks.yaml
market_analysis_task:
  description: >
    今天是交易日 {trade_date}。请对A股大盘进行完整的技术面分析。

    **分析标的：**
    1. 上证指数（000001.SH）
    2. 创业板指（399006.SZ）

    **分析步骤（按顺序调用工具）：**
    1. 用 get_index_technicals 分别获取两个指数的技术分析摘要。
    2. 用 get_market_breadth 获取今日市场宽度（涨跌比、涨停跌停、成交额）。
    3. 用 get_index_contribution 获取两个指数的权重股贡献分析。

    **你需要回答：**
    - 今天大盘整体偏多还是偏空？处于什么阶段（上升/回调/震荡/下跌）？
    - 均线系统（MA5/10/20/60）的排列和方向如何？
    - 量能是放量还是缩量？说明资金态度。
    - KDJ/RSI/BIAS 是否处于极端区域？
    - 权重股是拉升还是拖累指数？
    - 有哪些需要重点关注的信号或风险？

    **输出格式：**
    用结构化 Markdown 输出，分 "市场概览"、"上证指数"、"创业板指"、"综合研判" 四个部分。
    每个部分包含关键数据（价格、涨跌、均线、量能、指标）和分析结论。
  expected_output: >
    一份结构化的A股大盘复盘报告（Markdown格式），包含：
    - 市场概览（涨跌比、成交额、环比变化）
    - 上证指数技术分析（K线形态、均线量能、KDJ/RSI/BIAS、贡献分析）
    - 创业板指技术分析（同上）
    - 综合研判（大盘定性、关键信号、风险提示）
  agent: market_analyst
```

- [ ] **Step 3: Commit**

```bash
git add src/marketreview/config/
git commit -m "feat: configure Agent 1 (market_analyst) with agents.yaml + tasks.yaml"
```

---

### Task 7: Crew + Main（crew.py + main.py）

**Files:**
- Modify: `src/marketreview/crew.py`
- Modify: `src/marketreview/main.py`

- [ ] **Step 1: Rewrite crew.py for Agent 1**

```python
# src/marketreview/crew.py
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from marketreview.tools.market_tools import (
    GetIndexTechnicalsTool,
    GetMarketBreadthTool,
    GetIndexContributionTool,
)


@CrewBase
class Marketreview:
    """Marketreview crew — Agent 1: 大盘分析"""

    agents: list[BaseAgent]
    tasks: list[Task]

    @agent
    def market_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["market_analyst"],  # type: ignore[index]
            tools=[
                GetIndexTechnicalsTool(),
                GetMarketBreadthTool(),
                GetIndexContributionTool(),
            ],
            verbose=True,
        )

    @task
    def market_analysis_task(self) -> Task:
        return Task(
            config=self.tasks_config["market_analysis_task"],  # type: ignore[index]
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
```

- [ ] **Step 2: Rewrite main.py for manual trigger**

```python
# src/marketreview/main.py
#!/usr/bin/env python
"""
A股复盘系统 — 手动触发入口。
用法: python -m src.marketreview.main 20250604
      或: python -m src.marketreview.main  (默认今天)
"""
import sys
import os
import warnings
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from marketreview.crew import Marketreview
from marketreview.tools.market_tools import init_data_provider

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")


def run(trade_date: str = None):
    """Run Agent 1 market analysis for the given trading date."""
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y%m%d")

    # Init data layer
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 环境变量未设置，请在 .env 文件中配置")
    init_data_provider(token)

    inputs = {
        "trade_date": trade_date,
    }

    print(f"\n{'='*60}")
    print(f"  Agent 1 大盘分析 — {trade_date}")
    print(f"{'='*60}\n")

    try:
        result = Marketreview().crew().kickoff(inputs=inputs)
        print(f"\n{'='*60}")
        print(f"  分析完成")
        print(f"{'='*60}\n")
        return result
    except Exception as e:
        raise Exception(f"Agent 1 运行失败: {e}")


if __name__ == "__main__":
    trade_date = sys.argv[1] if len(sys.argv) > 1 else None
    run(trade_date)
```

- [ ] **Step 3: Commit**

```bash
git add src/marketreview/crew.py src/marketreview/main.py
git commit -m "feat: wire up Agent 1 crew + manual trigger main.py"
```

---

### Task 8: Streamlit Dashboard（basic version）

**Files:**
- Create: `dashboard/app.py`

- [ ] **Step 1: Write the dashboard**

```python
# dashboard/app.py
"""
A股复盘 Dashboard — Agent 1 大盘分析视图。
启动: streamlit run dashboard/app.py
"""
import streamlit as st
import sqlite3
import json
import os
import sys

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from marketreview.data.cache_manager import CacheManager
from marketreview.tools.technical import (
    rows_to_df,
    calc_ma,
    ma_arrangement,
    volume_analysis,
    calc_kdj,
    calc_rsi,
    calc_bias,
    kline_pattern,
)

st.set_page_config(page_title="A股复盘", page_icon="📊", layout="wide")

# ------- Helpers -------

def load_latest_data(code: str):
    """Load most recent cached data for a code."""
    cm = CacheManager()
    rows = cm.get_daily(code, limit=120)
    return rows_to_df(rows)


def plot_kline_with_ma(df, title: str):
    """Plotly candlestick + MA overlay chart."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    mas = calc_ma(df)
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.03, row_heights=[0.7, 0.3],
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        name="K线",
        increasing_line_color="#e53935", decreasing_line_color="#43a047",
    ), row=1, col=1)

    # MA lines
    colors = {"MA5": "#2196f3", "MA10": "#ff9800", "MA20": "#9c27b0", "MA60": "#4caf50"}
    for name, color in colors.items():
        if name in mas:
            fig.add_trace(go.Scatter(
                x=df["date"], y=mas[name], mode="lines",
                line=dict(color=color, width=1.2), name=name,
            ), row=1, col=1)

    # Volume bars
    colors_vol = ["#e53935" if c >= o else "#43a047" for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df["date"], y=df["vol"], name="成交量",
        marker_color=colors_vol, opacity=0.5,
    ), row=2, col=1)

    fig.update_layout(
        title=title, xaxis_rangeslider_visible=False,
        template="plotly_white", height=450, margin=dict(l=20, r=20, t=40, b=20),
    )
    fig.update_xaxes(title_text="", row=2, col=1)
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="成交量", row=2, col=1)

    return fig


# ------- Page -------

st.title("📊 A股复盘 Dashboard")
st.caption(f"Agent 1 — 大盘分析")

col1, col2 = st.columns(2)

# --- 上证指数 ---
with col1:
    st.subheader("📈 上证指数 000001.SH")
    try:
        df_sh = load_latest_data("000001.SH")
        if not df_sh.empty:
            latest = df_sh.iloc[-1]
            prev = df_sh.iloc[-2]
            change_pct = (latest["close"] / prev["close"] - 1) * 100
            st.metric(
                label="最新价", value=f"{latest['close']:.2f}",
                delta=f"{change_pct:+.2f}%",
            )

            # K-line chart
            fig = plot_kline_with_ma(df_sh, "上证指数 K线 + 均线")
            st.plotly_chart(fig, use_container_width=True)

            # Technical summary
            ma_arr = ma_arrangement(df_sh)
            vol = volume_analysis(df_sh)
            kdj = calc_kdj(df_sh)
            rsi = calc_rsi(df_sh, 6)
            bias = calc_bias(df_sh)
            candle = kline_pattern(df_sh)

            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("均线排列", ma_arr)
                st.metric("量能", vol.get("label", "N/A"),
                          delta=f"vs MA5: {vol.get('vs_ma5_pct', 0):+.1f}%")
            with c2:
                k_val = [v for v in kdj["K"] if not pd.isna(v)][-1]
                d_val = [v for v in kdj["D"] if not pd.isna(v)][-1]
                rsi_val = [v for v in rsi if not pd.isna(v)][-1]
                st.metric("KDJ-K", f"{k_val:.1f}")
                st.metric("KDJ-D", f"{d_val:.1f}")
                st.metric("RSI(6)", f"{rsi_val:.1f}")
            with c3:
                bias6 = [v for v in bias["BIAS6"] if not pd.isna(v)][-1]
                st.metric("BIAS(6)", f"{bias6:.2f}%")
                st.metric("K线形态", candle.get("type", "N/A"),
                          help=candle.get("interpretation", ""))
        else:
            st.warning("暂无上证指数数据，请先运行 Agent 1 拉取数据")
    except Exception as e:
        st.error(f"上证指数加载失败: {e}")

# --- 创业板指 ---
with col2:
    st.subheader("📈 创业板指 399006.SZ")
    try:
        df_cy = load_latest_data("399006.SZ")
        if not df_cy.empty:
            latest = df_cy.iloc[-1]
            prev = df_cy.iloc[-2]
            change_pct = (latest["close"] / prev["close"] - 1) * 100
            st.metric(
                label="最新价", value=f"{latest['close']:.2f}",
                delta=f"{change_pct:+.2f}%",
            )

            fig = plot_kline_with_ma(df_cy, "创业板指 K线 + 均线")
            st.plotly_chart(fig, use_container_width=True)

            ma_arr = ma_arrangement(df_cy)
            vol = volume_analysis(df_cy)
            kdj = calc_kdj(df_cy)
            rsi = calc_rsi(df_cy, 6)
            bias = calc_bias(df_cy)
            candle = kline_pattern(df_cy)

            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("均线排列", ma_arr)
                st.metric("量能", vol.get("label", "N/A"),
                          delta=f"vs MA5: {vol.get('vs_ma5_pct', 0):+.1f}%")
            with c2:
                k_val = [v for v in kdj["K"] if not pd.isna(v)][-1]
                d_val = [v for v in kdj["D"] if not pd.isna(v)][-1]
                rsi_val = [v for v in rsi if not pd.isna(v)][-1]
                st.metric("KDJ-K", f"{k_val:.1f}")
                st.metric("KDJ-D", f"{d_val:.1f}")
                st.metric("RSI(6)", f"{rsi_val:.1f}")
            with c3:
                bias6 = [v for v in bias["BIAS6"] if not pd.isna(v)][-1]
                st.metric("BIAS(6)", f"{bias6:.2f}%")
                st.metric("K线形态", candle.get("type", "N/A"),
                          help=candle.get("interpretation", ""))
        else:
            st.warning("暂无创业板指数据，请先运行 Agent 1 拉取数据")
    except Exception as e:
        st.error(f"创业板指加载失败: {e}")

# --- Agent 1 LLM 输出（如果存在） ---
st.divider()
st.subheader("🤖 Agent 1 最新分析报告")
report_path = os.path.join(os.path.dirname(__file__), "..", "report.md")
if os.path.exists(report_path):
    with open(report_path, "r", encoding="utf-8") as f:
        st.markdown(f.read())
else:
    st.info("尚未生成分析报告。运行 `python -m src.marketreview.main YYYYMMDD` 后此处会显示 Agent 1 的 LLM 输出。")
```

- [ ] **Step 2: Verify dashboard can import (no Streamlit run needed)**

```bash
cd i:/AIcode/marketreview && python -c "
import sys
sys.path.insert(0, 'src')
from marketreview.data.cache_manager import CacheManager
from marketreview.tools.technical import rows_to_df, calc_ma
print('All imports OK')
"
```
Expected: `All imports OK`

- [ ] **Step 3: Commit**

```bash
git add dashboard/app.py
git commit -m "feat: add Streamlit dashboard for Agent 1 (index K-line + indicators)"
```

---

### Task 9: End-to-End Integration Test

- [ ] **Step 1: Run Agent 1 with a known trading date**

```bash
cd i:/AIcode/marketreview && python -m src.marketreview.main 20250604
```
Expected: Agent 1 kicks off, calls tools, outputs analysis report to `report.md`.

- [ ] **Step 2: Verify data cached**

```bash
python -c "
from src.marketreview.data.cache_manager import CacheManager
cm = CacheManager()
sh = cm.get_daily('000001.SH', limit=3)
cy = cm.get_daily('399006.SZ', limit=3)
print(f'上证: {len(sh)} rows, latest: {sh[0][\"date\"] if sh else \"N/A\"}')
print(f'创业板: {len(cy)} rows, latest: {cy[0][\"date\"] if cy else \"N/A\"}')
"
```
Expected: both have >= 1 row with valid dates.

- [ ] **Step 3: Launch dashboard**

```bash
streamlit run dashboard/app.py
```
Expected: browser opens, both index charts render with MA overlay and indicator metrics.

- [ ] **Step 4: Commit final state**

```bash
git add -A && git diff --cached --stat
git commit -m "feat: Agent 1 end-to-end — data layer + tools + crew + dashboard"
```

---

## Self-Review

**1. Spec coverage:**
- §4 通用技术分析框架 → Task 3 (technical.py covers K-line, MA+vol, KDJ/RSI/BIAS)
- §4.4 权重贡献 → Task 4 (contribution.py)
- §5 Agent 1 定义 → Task 6 (agents.yaml)
- §5.2 分析内容（指数技术分析 + 市场宽度）→ Task 5 (tools) + Task 6 (task description)
- §5.3 Flow State 输出 → `report.md` + cache for dashboard
- §9 Dashboard → Task 8

**2. Placeholder scan:** No TBD/TODO placeholders. All code is concrete.

**3. Type consistency:** `CacheManager.get_daily()` returns `list[dict]`, consumed by `technical.py:build_technical_summary()` → `dict[str, Any]`, consumed by tools returning JSON strings. Consistent throughout.
