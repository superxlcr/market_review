# ETF/行业指数 买点胜率测试 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有个股买点胜率引擎上加 `asset_class` 维度，支持用中证行业/主题指数（674 个）跑买点胜率回测，复用全部买点/波段/模拟器逻辑。

**Architecture:** 方案 B 参数化复用——引擎不动，加 `asset_class: "stock"|"index"` 维度分流；买点 checker / 波段分析 / `detect_buy_points` 零改动；模拟器按 `asset_class` 分流（指数不 qfq、涨跌停不限制）；配置文件分两份（个股/ETF 独立）。

**Tech Stack:** Python 3.10+, pandas, tushare, sqlite3, Streamlit, pytest。

## Global Constraints

- **AI 版本号**：每轮改动后 bump `_AI_VERSION`（`dashboard/services/dashboard_service.py`），Z+1。当前 `9.15.2`。见 `docs/memory/ai-version-number.md`。
- **日期格式**：所有 DB 查询用 YYYYMMDD（无横线），见 `docs/memory/date-format-convention.md`。
- **缓存读必须按日期过滤**：指数 K 线查询用 `WHERE date = ?` 或日期范围，见 `docs/memory/always-filter-by-date.md`。
- **Python 兼容**：项目用 `Optional[X]` 风格；`X | Y` 联合类型在注解里可用（文件已用 `from __future__ import annotations`），但 `isinstance`/运行时不能用。
- **不改的文件**（方案 B 核心）：`tools/buy_points.py`、`tools/band_analysis.py`、`winrate/buypoint_defs.py`、`dashboard/pages/06_买点胜率.py`。
- **过滤规则**：6 条规则见 spec §2.2，过滤后 674 个指数（行业 185 + 主题 489，2026-07-20 快照，数量随 API 动态变化）。
- **ETF 买点集**：`ETF_BUY_POINTS`（12 个）= 回调一半/波段50%/量价节点 + MA 家族 9 变体，绕过 `BUY_POINT_STAGE` 的 disabled 门槛。
- **回归保证**：`asset_class` 默认 `"stock"`，个股版 06 页面走原路径不受影响。

---

## File Structure

| 文件 | 责任 | 任务 |
|------|------|------|
| `config/winrate_config_etf.txt` | ETF 配置（照抄个股版，去市值/行业白名单） | Task 2 |
| `src/marketreview/winrate/config.py` | `WinrateConfig` 加 `asset_class`/`index_pool`/`entry_mode`；`ETF_BUY_POINTS`；`parse_winrate_config` 加 `asset_class` 入参 | Task 2 |
| `src/marketreview/data/schema.sql` | 新增 `csi_index_pool` 表 | Task 3 |
| `src/marketreview/data/cache_manager.py` | `csi_index_pool` 读写 + `has_csi_pool()`；`_EXPECTED_COLUMNS` 加条目 | Task 3 |
| `src/marketreview/data/data_provider.py` | `_ensure_csi_pool()` + `ensure_index_pool_loaded()` | Task 3 |
| `src/marketreview/winrate/filters.py` | `passes_all` 按 `asset_class` 分流（index 跳过市值/行业） | Task 4 |
| `src/marketreview/winrate/trade_sim.py` | `board_limit_pct` + `simulate_trade` 加 `asset_class` | Task 5 |
| `src/marketreview/winrate/scan_engine.py` | `prepare_klines` 按 `asset_class` 分流；`scan_stock`/`run_scan` 传 `asset_class` | Task 6 |
| `dashboard/services/dashboard_service.py` | `prepare_winrate_data_etf` + `check_winrate_coverage_etf` + `run_winrate_scan_etf`；bump 版本 | Task 7 |
| `dashboard/pages/07_ETF买点胜率.py` | 新页面 | Task 8 |
| `dashboard/app.py` | 注册 07 页面 | Task 8 |
| `tests/winrate/test_etf_config.py` | Task 2 测试 | Task 2 |
| `tests/winrate/test_etf_filters.py` | Task 4 测试 | Task 4 |
| `tests/winrate/test_etf_trade_sim.py` | Task 5 测试 | Task 5 |
| `tests/winrate/test_etf_scan_engine.py` | Task 6 测试 | Task 6 |

依赖顺序：Task 1（无依赖，独立）→ Task 2（config）→ Task 3（数据层）→ Task 4（filters）→ Task 5（trade_sim）→ Task 6（scan_engine，依赖 3/4/5）→ Task 7（service，依赖 6）→ Task 8（页面，依赖 7）→ Task 9（集成验证 + 版本）。

---

## Task 1: ETF 配置文件

**Files:**
- Create: `config/winrate_config_etf.txt`

**Interfaces:**
- Produces: ETF 配置文件，Task 2 的 `parse_winrate_config(asset_class="index")` 读取它。

- [ ] **Step 1: 创建 ETF 配置文件**

照抄 `config/winrate_config.txt`，移除市值上/下限 + 行业白名单行（指数无市值/本身就是行业）。完整内容：

```
# ETF/行业指数 买点胜率回测配置
# 判赢与止盈
判赢阈值%=10
大胜利止盈%=20
小胜利回落止盈%=5

# 通用止损（对四个买点统一）
空间止损幅度%=5
启用ATR止损=否
ATR倍数=2
时间止损天数=13

# 进场
开盘追高上限%=102

# 扫描范围
开始日期=20230101
结束日期=now

# 过滤器（均线排列可多选，| 分隔：多头|空头|盘整，留空=不限）
短期均线排列=
长期均线排列=
上市最短天数=250

# 运行
并发数=1

# 调试（填指数 ts_code 只跑单只，如 931152.CSI；留空=跑选中的指数池）
调试标的=
```

- [ ] **Step 2: 验证文件可读**

Run: `.venv/Scripts/python -c "print(open('config/winrate_config_etf.txt', encoding='utf-8').read())"`
Expected: 打印上述内容，无乱码。

- [ ] **Step 3: Commit**

```bash
git add config/winrate_config_etf.txt
git commit -m "feat(etf): 新增 ETF 买点胜率配置文件（照抄个股版，去市值/行业白名单）"
```

---

## Task 2: WinrateConfig 扩展 + ETF_BUY_POINTS + parse_winrate_config 分流

**Files:**
- Modify: `src/marketreview/winrate/config.py:9-29`（`BUY_POINT_STAGE` 后加 `ETF_BUY_POINTS`）、`:44-72`（dataclass 加字段）、`:74-76`（`default_winrate_config` 加 `asset_class` 入参）、`:122-139`（`parse_winrate_config` 加 `asset_class` 入参）
- Test: `tests/winrate/test_etf_config.py`

**Interfaces:**
- Consumes: Task 1 的 `config/winrate_config_etf.txt`。
- Produces: `WinrateConfig.asset_class` / `.index_pool` / `.entry_mode` 字段；`ETF_BUY_POINTS` 列表；`parse_winrate_config(path, asset_class="stock"|"index")`；`default_winrate_config(asset_class=...)`。后续 Task 4/5/6/8 依赖这些。

- [ ] **Step 1: 写失败测试**

Create `tests/winrate/test_etf_config.py`:

```python
from pathlib import Path
from marketreview.winrate.config import (
    WinrateConfig, default_winrate_config, parse_winrate_config, ETF_BUY_POINTS,
)


def test_etf_buy_points_has_12():
    # 3 非MA + 9 MA变体
    assert len(ETF_BUY_POINTS) == 12
    for n in ["回调一半", "波段50%", "量价节点",
              "MA20支撑", "MA55支撑", "MA60支撑", "MA120支撑", "MA144支撑", "MA240支撑",
              "扣抵量均线支撑", "5日均量均线支撑", "无量均线支撑"]:
        assert n in ETF_BUY_POINTS


def test_default_stock_asset_class():
    c = default_winrate_config()
    assert c.asset_class == "stock"
    assert c.index_pool == []
    assert c.entry_mode == "limit"


def test_default_index_asset_class():
    c = default_winrate_config(asset_class="index")
    assert c.asset_class == "index"
    # ETF 默认买点 = ETF_BUY_POINTS
    assert c.buy_points == ETF_BUY_POINTS


def test_parse_etf_config_ignores_market_cap(tmp_path):
    p = tmp_path / "winrate_config_etf.txt"
    p.write_text(
        "判赢阈值%=8\n"
        "上市最短天数=300\n",
        encoding="utf-8",
    )
    c = parse_winrate_config(p, asset_class="index")
    assert c.asset_class == "index"
    assert c.win_threshold_pct == 8.0
    assert c.min_list_days == 300
    # ETF 模式 buy_points 默认 = ETF_BUY_POINTS
    assert c.buy_points == ETF_BUY_POINTS


def test_parse_stock_config_default_asset_class(tmp_path):
    # 不传 asset_class → stock（回归保证）
    p = tmp_path / "winrate_config.txt"
    p.write_text("判赢阈值%=7\n", encoding="utf-8")
    c = parse_winrate_config(p)
    assert c.asset_class == "stock"
    assert c.win_threshold_pct == 7.0


def test_read_real_etf_config_file():
    # 读项目里的真实 ETF 配置文件
    p = Path("config/winrate_config_etf.txt")
    c = parse_winrate_config(p, asset_class="index")
    assert c.asset_class == "index"
    assert c.win_threshold_pct == 10.0
    assert c.space_stop_pct == 5.0
    assert c.time_stop_days == 13
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_etf_config.py -v`
Expected: FAIL，`ImportError: cannot import name 'ETF_BUY_POINTS'`。

- [ ] **Step 3: 加 ETF_BUY_POINTS 常量**

在 `src/marketreview/winrate/config.py` 的 `BUY_POINT_STAGE = {...}` 字典之后、`_BUY_POINT_ORDER` 之前，插入：

```python
# ETF/行业指数 版可测买点（绕过 BUY_POINT_STAGE 的 disabled 门槛）。
# MA 家族在个股版被 disabled（胜率仅比随机高 0.6~3.5pp），ETF 版要测必须绕过门槛。
# 共 12 个：3 非MA + 9 MA变体。
ETF_BUY_POINTS = [
    "回调一半", "波段50%", "量价节点",
    "MA20支撑", "MA55支撑", "MA60支撑", "MA120支撑", "MA144支撑", "MA240支撑",
    "扣抵量均线支撑", "5日均量均线支撑", "无量均线支撑",
]
```

- [ ] **Step 4: WinrateConfig dataclass 加 3 字段**

在 `src/marketreview/winrate/config.py` 的 `WinrateConfig` dataclass 里，`debug_code: str = ""` 这一行之后，追加：

```python
    # 标的类型 / ETF 模式专用
    asset_class: str = "stock"       # "stock" | "index"
    index_pool: list[str] = field(default_factory=list)  # ETF 模式选中的指数 ts_code
    entry_mode: str = "limit"        # "limit"=条件单等回踩 | "close"=收盘价进场（预留，第一版不实现）
```

- [ ] **Step 5: default_winrate_config 加 asset_class 入参**

把 `default_winrate_config` 改为：

```python
def default_winrate_config(asset_class: str = "stock") -> WinrateConfig:
    cfg = WinrateConfig()
    if asset_class == "index":
        cfg = replace(cfg, asset_class="index", buy_points=list(ETF_BUY_POINTS))
    return cfg
```

（`replace` 已在文件顶部 import：`from dataclasses import dataclass, field, replace`）

- [ ] **Step 6: parse_winrate_config 加 asset_class 入参**

把 `parse_winrate_config` 改为：

```python
def parse_winrate_config(path: str | Path, asset_class: str = "stock") -> WinrateConfig:
    path = Path(path)
    cfg = default_winrate_config(asset_class)
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

（唯一改动：第 1 行加 `asset_class: str = "stock"`，第 2 行 `default_winrate_config()` → `default_winrate_config(asset_class)`）

- [ ] **Step 7: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_etf_config.py -v`
Expected: 6 个测试全 PASS。

- [ ] **Step 8: 跑回归——个股版 config 测试不受影响**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_config.py -v`
Expected: 全 PASS（`parse_winrate_config` 默认 `asset_class="stock"`，行为不变）。

- [ ] **Step 9: Commit**

```bash
git add src/marketreview/winrate/config.py tests/winrate/test_etf_config.py
git commit -m "feat(etf): WinrateConfig 加 asset_class/index_pool/entry_mode + ETF_BUY_POINTS + parse 分流"
```

---

## Task 3: 数据层 — csi_index_pool 表 + 缓存 + 抓取

**Files:**
- Modify: `src/marketreview/data/schema.sql`（末尾加表）
- Modify: `src/marketreview/data/cache_manager.py:73-79`（`_EXPECTED_COLUMNS` 加条目）+ 末尾加 4 个方法
- Modify: `src/marketreview/data/data_provider.py`（concept 方法附近加 `_ensure_csi_pool` + `ensure_index_pool_loaded`）
- Test: `tests/winrate/test_etf_data_layer.py`

**Interfaces:**
- Consumes: `pro.index_basic(market='CSI')`（tushare API）；`_normalize_index_batch`（已存在于 data_provider.py:1765）。
- Produces: `cache.has_csi_pool()` / `cache.upsert_csi_pool(rows)` / `cache.get_csi_pool()` / `cache.clear_csi_pool()`；`dp.ensure_csi_pool()` / `dp.ensure_index_pool_loaded(codes, start, end, progress_cb)`。Task 7/8 依赖。

- [ ] **Step 1: 写失败测试**

Create `tests/winrate/test_etf_data_layer.py`:

```python
import pandas as pd
from unittest.mock import MagicMock, patch
from marketreview.data.cache_manager import CacheManager


def test_csi_pool_table_roundtrip(tmp_path):
    cm = CacheManager(db_path=str(tmp_path / "t.db"))
    assert cm.has_csi_pool() is False
    cm.upsert_csi_pool([
        {"ts_code": "931152.CSI", "name": "CS创新药", "category": "主题指数", "list_date": "20190422"},
        {"ts_code": "H30199.CSI", "name": "电力指数", "category": "行业指数", "list_date": "20130715"},
    ])
    assert cm.has_csi_pool() is True
    rows = cm.get_csi_pool()
    assert len(rows) == 2
    codes = {r["ts_code"] for r in rows}
    assert "931152.CSI" in codes
    assert "H30199.CSI" in codes


def test_csi_pool_clear(tmp_path):
    cm = CacheManager(db_path=str(tmp_path / "t.db"))
    cm.upsert_csi_pool([{"ts_code": "931152.CSI", "name": "CS创新药",
                         "category": "主题指数", "list_date": "20190422"}])
    assert cm.has_csi_pool() is True
    cm.clear_csi_pool()
    assert cm.has_csi_pool() is False


def test_ensure_csi_pool_filters_and_caches(tmp_path):
    """_ensure_csi_pool 拉 index_basic(CSI) → 6条过滤 → 缓存，幂等。"""
    from marketreview.data.data_provider import DataProvider
    cm = CacheManager(db_path=str(tmp_path / "t.db"))
    dp = DataProvider.__new__(DataProvider)   # 跳过 __init__（不连 tushare）
    dp.cache = cm
    # mock api
    dp._api = MagicMock()
    dp._api.index_basic.return_value = pd.DataFrame([
        {"ts_code": "931152.CSI", "name": "CS创新药", "category": "主题指数", "list_date": "20190422"},
        # 被过滤：债券
        {"ts_code": "000012.CSI", "name": "国债指数", "category": "债券指数", "list_date": "20021231"},
        # 被过滤：全收益
        {"ts_code": "H20539.CSI", "name": "中证白酒全收益", "category": "主题指数", "list_date": "20150508"},
        # 被过滤：币种后缀
        {"ts_code": "931152USD210.CSI", "name": "CS创新药(全)USD", "category": "主题指数", "list_date": "20190422"},
        # 被过滤：三板
        {"ts_code": "899304.CSI", "name": "三板医药", "category": "主题指数", "list_date": "20190114"},
        # 被过滤：H300 港股通
        {"ts_code": "H30329.CSI", "name": "H300休闲", "category": "主题指数", "list_date": "20140521"},
    ])
    n = dp.ensure_csi_pool()
    assert n == 1  # 只剩 CS创新药
    rows = cm.get_csi_pool()
    assert len(rows) == 1
    assert rows[0]["ts_code"] == "931152.CSI"
    # 幂等：再调不重复拉
    dp._api.index_basic.return_value = pd.DataFrame()
    n2 = dp.ensure_csi_pool()
    assert n2 == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_etf_data_layer.py -v`
Expected: FAIL，`AttributeError: 'CacheManager' object has no attribute 'has_csi_pool'`。

- [ ] **Step 3: schema.sql 加表**

在 `src/marketreview/data/schema.sql` 末尾追加：

```sql

-- ── CSI (中证) 可回测指数池 ──

CREATE TABLE IF NOT EXISTS csi_index_pool (
    ts_code    TEXT PRIMARY KEY,   -- 指数代码 (931719.CSI ...)
    name       TEXT NOT NULL,      -- 简称
    category   TEXT NOT NULL,      -- 主题指数 / 行业指数
    list_date  TEXT                -- 发布日期 YYYYMMDD
);
```

- [ ] **Step 4: _EXPECTED_COLUMNS 加条目**

在 `src/marketreview/data/cache_manager.py` 的 `_EXPECTED_COLUMNS` 字典里，`"concept_member"` 条目之后，加：

```python
        "csi_index_pool": {
            "ts_code", "name", "category", "list_date",
        },
```

- [ ] **Step 5: cache_manager 加 4 个方法**

在 `src/marketreview/data/cache_manager.py` 的 `get_concept_index` 方法之后（concept 区块末尾），加：

```python
    # ------- csi_index_pool (ETF 回测标的池) -------

    def has_csi_pool(self) -> bool:
        """Return True if csi_index_pool table has data (lazy-init guard)."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT 1 FROM csi_index_pool LIMIT 1").fetchone()
        return row is not None

    def upsert_csi_pool(self, rows: list[dict]):
        """Batch upsert CSI index pool rows.
        Each row: {ts_code, name, category, list_date}."""
        with self._get_conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO csi_index_pool "
                "(ts_code, name, category, list_date) "
                "VALUES (:ts_code, :name, :category, :list_date)",
                rows,
            )
            conn.commit()
        log.info("upsert_csi_pool: %d rows", len(rows))

    def get_csi_pool(self) -> list[dict]:
        """Return all CSI index pool rows ordered by category, name."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT ts_code, name, category, list_date "
                "FROM csi_index_pool ORDER BY category, name"
            ).fetchall()
        return [dict(r) for r in rows]

    def clear_csi_pool(self):
        """Delete all csi_index_pool rows to force re-fetch."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM csi_index_pool")
            conn.commit()
```

- [ ] **Step 6: data_provider 加过滤函数 + _ensure_csi_pool + ensure_index_pool_loaded**

在 `src/marketreview/data/data_provider.py` 的 `_ensure_concepts` 方法之后，加。先在文件顶部模块级（`_TRACKED_INDICES` 定义附近）加过滤函数，再加方法。

模块级函数（加在 `_normalize_index_batch` 函数之后）：

```python
def _filter_csi_index_pool(df) -> "list[dict]":
    """过滤 index_basic(CSI) 返回的 DataFrame → 可回测指数行列表。

    6 条规则（见 spec §2.2）：
    1. 只留主题/行业两类
    2. ts_code 不含币种后缀
    3. name 不含全收益/净收益/(全)/(净) + 币种字样
    4. name 不含港股/海外/跨市/三板/H300/HKT/港股通
    5. name 不以纯数字规模前缀开头 + 不含企业属性/产业链/地域关键词
    6. name 不含策略型残留
    """
    import re
    d = df[df["category"].isin(["主题指数", "行业指数"])].copy()
    d = d[~d["ts_code"].str.contains(r"(?:CNY|HKD|USD|EUR|JPY)", regex=True)]
    d = d[~d["name"].str.contains(
        r"全收益|净收益|（全）|(?:全)|(?:净)|（净）|USD|CNY|HKD|港元|人民币|美元|港币",
        na=False, regex=True)]
    d = d[~d["name"].str.contains(
        r"港股|香港|HK|SHS|海外|沪港|深港|沪通|深通|港通|AH|三板|H300|HKT|港股通",
        na=False, regex=True)]
    d = d[~d["name"].str.match(
        r"^(?:1000|500|300|180|380|800|700|200|50|100)", na=False)]
    d = d[~d["name"].str.contains(
        r"央企|民企|国企|地企|上游|中游|下游|长三角|珠三角|京津冀|湾区|城镇",
        na=False, regex=True)]
    d = d[~d["name"].str.contains(
        r"收$|红利|分红|低波|动量|高贝|价值|成长$", na=False, regex=True)]
    rows = []
    for _, r in d.iterrows():
        rows.append({
            "ts_code": str(r["ts_code"]),
            "name": str(r["name"]),
            "category": str(r["category"]),
            "list_date": str(r.get("list_date", "")) if r.get("list_date") is not None
                         and str(r.get("list_date")) != "nan" else "",
        })
    return rows
```

`DataProvider` 类方法（加在 `_ensure_concepts` 方法之后）：

```python
    # ── CSI 指数池（ETF 回测标的池）──

    def ensure_csi_pool(self, progress_cb=None) -> int:
        """Lazy-init: 拉 index_basic(market='CSI') → 6 条过滤 → 缓存到 csi_index_pool。
        幂等：已缓存则跳过。返回缓存指数数。"""
        if self.cache.has_csi_pool():
            n = len(self.cache.get_csi_pool())
            log.info("ensure_csi_pool: already cached (%d), skip", n)
            return n

        log.info("ensure_csi_pool: fetching index_basic(market=CSI) ...")
        try:
            df = self._api.index_basic(market="CSI")
        except Exception as e:
            log.warning("ensure_csi_pool: index_basic failed: %s", e)
            return 0
        if df is None or df.empty:
            log.warning("ensure_csi_pool: index_basic returned empty")
            return 0

        rows = _filter_csi_index_pool(df)
        log.info("ensure_csi_pool: %d indices after filter (raw=%d)",
                 len(rows), len(df))
        if rows:
            self.cache.upsert_csi_pool(rows)
        return len(rows)

    def ensure_index_pool_loaded(self, codes: list[str], start_date: str,
                                  end_date: str, progress_cb=None) -> int:
        """抓取选中指数的 K 线，存 tushare_cache（asset_type='index'）。
        逻辑仿 _ensure_indices_loaded：覆盖检查 + 增量抓取。
        返回抓取的指数数（非 index-days）。"""
        start_date = start_date.replace("-", "")
        end_date = end_date.replace("-", "")
        fetched = 0
        total = len(codes)
        for ii, idx_code in enumerate(codes):
            # 覆盖检查：latest>=end 且 earliest<=start → 跳过
            latest_cached = self.cache.get_latest_date(idx_code)
            if latest_cached and latest_cached.replace("-", "") >= end_date:
                earliest_cached = self.cache.get_earliest_date(idx_code)
                if earliest_cached and earliest_cached.replace("-", "") <= start_date:
                    if progress_cb:
                        progress_cb("etf_index", ii + 1, total)
                    continue
            try:
                df = self._api.index_daily(
                    ts_code=idx_code,
                    start_date=start_date,
                    end_date=end_date,
                    limit=_PAGE_SIZE,
                )
            except Exception as e:
                log.warning("index_daily(%s) failed: %s", idx_code, e)
                if progress_cb:
                    progress_cb("etf_index", ii + 1, total)
                continue
            if df is not None and not df.empty:
                rows = _normalize_index_batch(df)
                if rows:
                    self.cache.upsert_daily_bulk(rows)
                fetched += 1
            if progress_cb:
                progress_cb("etf_index", ii + 1, total)
        log.info("ensure_index_pool_loaded: fetched %d/%d indices", fetched, total)
        return fetched
```

> 注：方法名用 `ensure_csi_pool`（公开）而非 `_ensure_csi_pool`，因为页面/服务层要直接调。`ensure_index_pool_loaded` 同理公开。

- [ ] **Step 7: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_etf_data_layer.py -v`
Expected: 3 个测试全 PASS。

- [ ] **Step 8: 真实 API 冒烟（可选，验证过滤规则）**

Run: `.venv/Scripts/python -c "from marketreview.data.data_provider import DataProvider; from dotenv import load_dotenv; import os, tushare as ts; load_dotenv(); ts.set_token(os.environ['TUSHARE_TOKEN']); dp=DataProvider(os.environ['TUSHARE_TOKEN']); n=dp.ensure_csi_pool(); print(f'cached {n} indices'); print([r['name'] for r in dp.cache.get_csi_pool() if r['ts_code'] in ('931152.CSI','930851.CSI','931719.CSI','H30199.CSI')])"`
Expected: `cached ~674 indices`，4 个示例指数名字打印出来。

- [ ] **Step 9: Commit**

```bash
git add src/marketreview/data/schema.sql src/marketreview/data/cache_manager.py src/marketreview/data/data_provider.py tests/winrate/test_etf_data_layer.py
git commit -m "feat(etf): 数据层 — csi_index_pool 表+缓存+过滤+抓取(674个可回测指数)"
```

---

## Task 4: filters.passes_all 按 asset_class 分流

**Files:**
- Modify: `src/marketreview/winrate/filters.py:68-81`（`passes_all`）
- Test: `tests/winrate/test_etf_filters.py`

**Interfaces:**
- Consumes: `WinrateConfig.asset_class`（Task 2）。
- Produces: `passes_all` 在 `asset_class="index"` 时跳过市值/行业过滤，只留均线排列 + 上市天数。Task 6 依赖。

- [ ] **Step 1: 写失败测试**

Create `tests/winrate/test_etf_filters.py`:

```python
import pandas as pd
from marketreview.winrate.config import WinrateConfig
from marketreview.winrate import filters as F


def _rising_df(n=260, base=10.0, step=0.05):
    closes = [base + i * step for i in range(n)]
    return pd.DataFrame({"close": closes})


def test_index_skips_market_cap():
    # index 模式：即使设了市值下限，也不过滤（mv_yi=0 也能过）
    df = _rising_df()
    cfg = WinrateConfig(asset_class="index", mv_min_yi=9999, mv_max_yi=0,
                        long_ma_states=[], short_ma_states=[], min_list_days=0)
    assert F.passes_all(df, cfg, mv_yi=0.0, l1="电子", l2="半导体",
                        list_date="20100101", on_date="20260101") is True


def test_index_skips_industry_whitelist():
    # index 模式：行业白名单不生效
    df = _rising_df()
    cfg = WinrateConfig(asset_class="index",
                        industry_whitelist=["不存在行业"],
                        long_ma_states=[], short_ma_states=[], min_list_days=0)
    assert F.passes_all(df, cfg, mv_yi=0.0, l1="电子", l2="半导体",
                        list_date="20100101", on_date="20260101") is True


def test_index_keeps_ma_arrange_filter():
    # index 模式：均线排列过滤仍生效
    df = _rising_df()
    cfg_bull = WinrateConfig(asset_class="index", long_ma_states=["多头"],
                             short_ma_states=[], min_list_days=0)
    cfg_bear = WinrateConfig(asset_class="index", long_ma_states=["空头"],
                             short_ma_states=[], min_list_days=0)
    assert F.passes_all(df, cfg_bull, mv_yi=0.0, l1="", l2="",
                        list_date="20100101", on_date="20260101") is True
    assert F.passes_all(df, cfg_bear, mv_yi=0.0, l1="", l2="",
                        list_date="20100101", on_date="20260101") is False


def test_index_keeps_list_age_filter():
    # index 模式：发布天数过滤仍生效
    df = _rising_df()
    cfg = WinrateConfig(asset_class="index", min_list_days=250,
                        long_ma_states=[], short_ma_states=[])
    # 上市 100 天 < 250 → 不通过
    assert F.passes_all(df, cfg, mv_yi=0.0, l1="", l2="",
                        list_date="20250901", on_date="20260101") is False
    # 上市 400 天 ≥ 250 → 通过
    assert F.passes_all(df, cfg, mv_yi=0.0, l1="", l2="",
                        list_date="20241101", on_date="20260101") is True


def test_stock_path_unchanged():
    # 回归：stock 模式行为不变（市值过滤仍生效）
    df = _rising_df()
    cfg = WinrateConfig(asset_class="stock", mv_min_yi=9999,
                        long_ma_states=[], short_ma_states=[], min_list_days=0)
    assert F.passes_all(df, cfg, mv_yi=10.0, l1="", l2="",
                        list_date="20100101", on_date="20260101") is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_etf_filters.py -v`
Expected: 前 4 个 FAIL（index 模式现在走 stock 路径，市值/行业过滤拦住），最后 1 个 PASS。

- [ ] **Step 3: 改 passes_all 分流**

把 `src/marketreview/winrate/filters.py` 的 `passes_all` 改为：

```python
def passes_all(df_asc: pd.DataFrame, cfg: WinrateConfig, mv_yi: float,
               l1: str, l2: str, list_date: str, on_date: str) -> bool:
    """便宜的先算：上市时长 → 均线（最贵）。
    stock 模式额外过滤市值 + 行业白名单；index 模式跳过这两项（指数无市值、本身就是行业）。"""
    if not passes_list_age(list_date, on_date, cfg.min_list_days):
        return False
    if cfg.asset_class == "stock":
        if not passes_market_cap(mv_yi, cfg):
            return False
        if not passes_industry(l1, l2, cfg.industry_whitelist):
            return False
    if not passes_ma_arrange(df_asc, cfg.short_ma_states, [5, 10, 20]):
        return False
    if not passes_ma_arrange(df_asc, cfg.long_ma_states, [60, 120, 240]):
        return False
    return True
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_etf_filters.py -v`
Expected: 5 个测试全 PASS。

- [ ] **Step 5: 跑回归——个股版 filters 测试不受影响**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_filters.py -v`
Expected: 全 PASS（`WinrateConfig` 默认 `asset_class="stock"`）。

- [ ] **Step 6: Commit**

```bash
git add src/marketreview/winrate/filters.py tests/winrate/test_etf_filters.py
git commit -m "feat(etf): filters.passes_all 按 asset_class 分流（index 跳过市值/行业）"
```

---

## Task 5: trade_sim board_limit_pct + simulate_trade 加 asset_class

**Files:**
- Modify: `src/marketreview/winrate/trade_sim.py:8-15`（`board_limit_pct`）、`:63-77`（`simulate_trade` 签名 + 涨跌停调用）
- Test: `tests/winrate/test_etf_trade_sim.py`

**Interfaces:**
- Consumes: `WinrateConfig.asset_class`（Task 2）。
- Produces: `board_limit_pct(code, asset_class="stock")`；`simulate_trade(..., asset_class="stock")`。指数模式涨跌停恒通过（返回 1.0=100%）。Task 6 依赖。

- [ ] **Step 1: 写失败测试**

Create `tests/winrate/test_etf_trade_sim.py`:

```python
from marketreview.winrate.trade_sim import board_limit_pct, simulate_trade, BuyPointSignal
from marketreview.winrate.config import WinrateConfig


def test_board_limit_stock():
    assert board_limit_pct("000001.SZ") == 0.10
    assert board_limit_pct("300001.SZ") == 0.20
    assert board_limit_pct("688001.SH") == 0.20


def test_board_limit_index_no_limit():
    # 指数无涨跌停 → 返回 1.0（100%），条件单可达性恒通过
    assert board_limit_pct("931152.CSI", asset_class="index") == 1.0
    assert board_limit_pct("H30199.CSI", asset_class="index") == 1.0


def test_simulate_trade_index_no_qfq_implied():
    # 指数模式：条件单可达性不拦（即使 target 距收盘很远也能成交）
    # 构造 K 线：信号日 close=100，次日 open=99/low=95/high=101，target=95
    klines = [
        {"date": "20260101", "open": 100, "high": 101, "low": 99, "close": 100},
        {"date": "20260102", "open": 99, "high": 101, "low": 95, "close": 100},
        {"date": "20260103", "open": 100, "high": 110, "low": 99, "close": 108},
        {"date": "20260104", "open": 108, "high": 112, "low": 107, "close": 111},
    ]
    sig = BuyPointSignal(buy_point="波段50%", target_price=95.0,
                         close_stop_kind="entry")
    cfg = WinrateConfig(asset_class="index", win_threshold_pct=10.0,
                        big_win_pct=20.0, small_win_floor_pct=5.0,
                        space_stop_pct=5.0, time_stop_days=13,
                        open_chase_cap_pct=102.0)
    tr = simulate_trade(sig, signal_idx=0, klines_asc=klines, cfg=cfg,
                        code="931152.CSI", name="CS创新药", atr_at_signal=0.0,
                        asset_class="index")
    # 次日 low=95 <= target=95 <= high=101 → 成交@95
    assert tr is not None
    assert tr.entry_price == 95.0
    assert tr.entry_date == "20260102"


def test_simulate_trade_stock_still_uses_board_limit():
    # 回归：stock 模式仍用涨跌停可达性（target 远超 10% 涨停 → 不成交）
    klines = [
        {"date": "20260101", "open": 100, "high": 101, "low": 99, "close": 100},
        {"date": "20260102", "open": 100, "high": 101, "low": 99, "close": 100},
    ]
    sig = BuyPointSignal(buy_point="波段50%", target_price=200.0,
                         close_stop_kind="entry")  # target 翻倍，超涨跌停
    cfg = WinrateConfig(asset_class="stock", win_threshold_pct=10.0,
                        big_win_pct=20.0, small_win_floor_pct=5.0,
                        space_stop_pct=5.0, time_stop_days=13,
                        open_chase_cap_pct=102.0)
    tr = simulate_trade(sig, signal_idx=0, klines_asc=klines, cfg=cfg,
                        code="000001.SZ", name="平安银行", atr_at_signal=0.0)
    assert tr is None  # 涨跌停可达性拦截
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_etf_trade_sim.py -v`
Expected: FAIL，`board_limit_pct() got an unexpected keyword argument 'asset_class'`。

- [ ] **Step 3: 改 board_limit_pct 加 asset_class**

把 `src/marketreview/winrate/trade_sim.py` 的 `board_limit_pct` 改为：

```python
def board_limit_pct(code: str, asset_class: str = "stock") -> float:
    """次日涨跌停幅度。
    stock: 按板块（300/301/688→20%, 8/4北交所→30%, 其余10%）。
    index: 指数无涨跌停，返回 1.0（100%）= 条件单可达性恒通过。"""
    if asset_class == "index":
        return 1.0
    c = code.split(".")[0]
    if c.startswith(("300", "301", "688")):
        return 0.20
    if c.startswith(("8", "4")):  # 北交所
        return 0.30
    return 0.10
```

- [ ] **Step 4: 改 simulate_trade 加 asset_class 参数**

把 `src/marketreview/winrate/trade_sim.py` 的 `simulate_trade` 签名 + 涨跌停调用改。

签名（第 63-65 行）改为：

```python
def simulate_trade(signal: BuyPointSignal, signal_idx: int,
                   klines_asc: list[dict], cfg: WinrateConfig,
                   code: str, name: str, atr_at_signal: float,
                   asset_class: str = "stock") -> TradeResult | None:
```

涨跌停调用（原第 75-77 行 `limit = board_limit_pct(code)`）改为：

```python
    limit = board_limit_pct(code, asset_class=asset_class)
```

> 注：其余逻辑（成交、止损、MFP、出场）一字不动。`entry_mode` 第一版不实现——cfg 已有字段但不在此分支，留待将来。

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_etf_trade_sim.py -v`
Expected: 4 个测试全 PASS。

- [ ] **Step 6: 跑回归——个股版 trade_sim 测试不受影响**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_trade_sim.py -v`
Expected: 全 PASS（`simulate_trade` 默认 `asset_class="stock"`，`board_limit_pct` 同）。

- [ ] **Step 7: Commit**

```bash
git add src/marketreview/winrate/trade_sim.py tests/winrate/test_etf_trade_sim.py
git commit -m "feat(etf): trade_sim board_limit_pct/simulate_trade 加 asset_class（指数无涨跌停）"
```

---

## Task 6: scan_engine prepare_klines 分流 + scan_stock/run_scan 传 asset_class

**Files:**
- Modify: `src/marketreview/winrate/scan_engine.py:23-39`（`prepare_klines`）、`:42-46`（`scan_stock` 签名 + `passes_all`/`simulate_trade` 调用）、`:147-220`（`run_scan` 标的池分流）
- Test: `tests/winrate/test_etf_scan_engine.py`

**Interfaces:**
- Consumes: `WinrateConfig.asset_class`/`index_pool`（Task 2）；`DataProvider.ensure_index_pool_loaded`（Task 3）；`passes_all`（Task 4）；`simulate_trade`（Task 5）。
- Produces: `scan_stock(..., asset_class="stock")`；`run_scan` 在 `asset_class="index"` 时从 `cfg.index_pool` 取标的池、不查 stock_basic/industry/concept。Task 7 依赖。

- [ ] **Step 1: 写失败测试**

Create `tests/winrate/test_etf_scan_engine.py`:

```python
from marketreview.winrate.scan_engine import prepare_klines
from marketreview.winrate.config import WinrateConfig


def test_prepare_klines_index_no_qfq():
    """index 模式：adj_factor 不是 1.0 时也不做 qfq（直接用 raw close）。
    构造 raw close=100 但 adj_factor=0.5 → 若错误 qfq 会变 50，index 应保持 100。"""
    rows_desc = [
        {"date": "2026010%d" % i, "open": 100, "high": 101, "low": 99,
         "close": 100, "vol": 1000, "amount": 100000, "adj_factor": 0.5}
        for i in range(1, 70)
    ]
    klines = prepare_klines(rows_desc, asset_class="index")
    assert len(klines) > 0
    # index 不 qfq → close 保持 raw 100，不是 qfq 后的 50
    assert klines[-1]["close"] == 100


def test_prepare_klines_stock_does_qfq():
    """stock 模式：adj_factor=0.5 → qfq 后 close=50（乘法复权）。"""
    rows_desc = [
        {"date": "2026010%d" % i, "open": 100, "high": 101, "low": 99,
         "close": 100, "vol": 1000, "amount": 100000, "adj_factor": 0.5}
        for i in range(1, 70)
    ]
    klines = prepare_klines(rows_desc, asset_class="stock")
    assert klines[-1]["close"] == 50


def test_scan_stock_index_path_runs():
    """index 模式 scan_stock 端到端不报错（用合成 K 线，无真实买点触发也 OK）。"""
    from marketreview.winrate.scan_engine import scan_stock
    rows_desc = [
        {"date": "2026010%d" % i, "open": 100, "high": 101, "low": 99,
         "close": 100, "vol": 1000, "amount": 100000, "adj_factor": 1.0}
        for i in range(1, 320)
    ]
    cfg = WinrateConfig(asset_class="index", buy_points=["波段50%"],
                        long_ma_states=[], short_ma_states=[], min_list_days=0,
                        start_date="20260101", end_date="now",
                        time_stop_days=13)
    # 不应抛异常（可能返回空 list）
    results = scan_stock("931152.CSI", "CS创新药", rows_desc, cfg,
                         industry_l1="", industry_l2="", industry_l3="",
                         list_date="20190422", mv_series={},
                         asset_class="index")
    assert isinstance(results, list)


def test_run_scan_index_uses_index_pool(tmp_path, monkeypatch):
    """run_scan 在 index 模式从 cfg.index_pool 取标的，不查 stock_basic/industry/concept。"""
    from marketreview.winrate import scan_engine
    from marketreview.winrate.scan_engine import run_scan

    cfg = WinrateConfig(asset_class="index", index_pool=["931152.CSI"],
                        buy_points=["波段50%"], long_ma_states=[],
                        short_ma_states=[], min_list_days=0,
                        start_date="20260101", end_date="now",
                        time_stop_days=13, max_workers=1)

    # mock DataProvider：cache.get_daily 返回空（scan_stock 会因 n<60 返回 []）
    dp = scan_engine.DataProvider.__new__(scan_engine.DataProvider)
    dp.cache = type("C", (), {
        "get_daily": lambda self, code, limit=2000: [],
        "has_concepts": lambda self: False,
        "get_stock_basic": lambda self: [],
        "get_stock_industries": lambda self, codes: {},
    })()

    results = run_scan(dp, cfg)
    assert results == []  # 空 K 线 → 无交易
    # 关键：没调 get_stock_basic（否则会返回 [] 也行，但确认走 index 分支不依赖它）
    # 这里主要验证不抛异常 + 走 index_pool 路径
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_etf_scan_engine.py -v`
Expected: FAIL，`prepare_klines() got an unexpected keyword argument 'asset_class'`。

- [ ] **Step 3: 改 prepare_klines 加 asset_class 分流**

把 `src/marketreview/winrate/scan_engine.py` 的 `prepare_klines` 改为：

```python
def prepare_klines(rows_desc: list[dict], asset_class: str = "stock") -> list[dict]:
    """rows_desc(date DESC, raw) → date ASC、（stock:qfq / index:raw）、每行带 ma5..ma240 与 date 字符串。"""
    df = rows_to_df(rows_desc)
    if df.empty:
        return []
    if asset_class == "stock":
        df = DataProvider.raw_to_qfq(df)   # 个股需前复权
    # index: 不 qfq（adj_factor=1.0，指数本身连续；调了是 no-op 但语义误导）
    mas = calc_ma(df, _MA_PERIODS)
    out: list[dict] = []
    for i, (_, r) in enumerate(df.iterrows()):
        d = r.to_dict()
        raw_date = str(r["date"])
        d["date"] = raw_date if raw_date.isdigit() else raw_date.replace("-", "")[:8]
        for p in _MA_PERIODS:
            vals = mas[f"MA{p}"]
            d[f"ma{p}"] = float(vals[i]) if i < len(vals) and vals[i] == vals[i] else 0.0  # NaN→0
        out.append(d)
    return out
```

- [ ] **Step 4: 改 scan_stock 加 asset_class 参数 + 传给 prepare_klines/simulate_trade**

把 `scan_stock` 签名（第 42-46 行）改为：

```python
def scan_stock(code: str, name: str, rows_desc: list[dict], cfg: WinrateConfig,
               industry_l1: str, industry_l2: str, industry_l3: str,
               list_date: str, mv_series: dict[str, float],
               concept_info: dict | None = None,
               band_lookback: int = 300,
               asset_class: str = "stock") -> list[TradeResult]:
```

`scan_stock` 内部，`klines = prepare_klines(rows_desc)` 改为：

```python
    klines = prepare_klines(rows_desc, asset_class=asset_class)
```

`scan_stock` 内部，`tr = simulate_trade(sig, i, klines, cfg, code, name, atr_T)` 改为：

```python
            tr = simulate_trade(sig, i, klines, cfg, code, name, atr_T,
                                asset_class=asset_class)
```

> 注：`passes_all` 调用不动——它已读 `cfg.asset_class`（Task 4 改造）。

- [ ] **Step 5: 改 run_scan 按 asset_class 分流标的池**

把 `run_scan` 的标的池构建部分（第 154-167 行附近，从 `basics = dp.cache.get_stock_basic()` 到 `concept_map = ...`）改为：

```python
    if cfg.asset_class == "index":
        # ETF 模式：标的池来自 cfg.index_pool（UI 选中的指数），无 is_st/行业/概念
        codes = list(cfg.index_pool)
        universe = [{"ts_code": c, "name": c, "list_date": ""} for c in codes]
        ind_map = {}
        concept_map = {}
    else:
        basics = dp.cache.get_stock_basic()   # [{ts_code,name,list_date,is_st}]
        if cfg.debug_code:
            want = cfg.debug_code.strip().upper()
            universe = [b for b in basics
                        if b["ts_code"].upper() == want or b["ts_code"].split(".")[0] == want]
            if not universe:
                log.warning("调试标的 %s 未在 stock_basic 中找到，返回空", cfg.debug_code)
                return []
            log.info("调试模式：只扫描 %s（绕过 is_st 过滤）", universe[0]["ts_code"])
        else:
            universe = [b for b in basics if not b.get("is_st")]
        codes = [b["ts_code"] for b in universe]
        ind_map = dp.cache.get_stock_industries(codes)
        concept_map = dp._get_or_build_concept_map(codes) if dp.cache.has_concepts() else {}
```

然后 `_one` 函数里，`scan_stock(...)` 调用末尾加 `asset_class=cfg.asset_class`。找到 `_one` 里的：

```python
        trades = scan_stock(
            code, b.get("name", ""), rows_desc, cfg,
            ind.get("l1_name", ""), ind.get("l2_name", ""),
            ind.get("l3_name", ""),
            b.get("list_date", ""), mv_series,
            concept_info=ci,
        )
```

改为：

```python
        # index 模式 ind/ci/mv_series 为空 dict（指数无行业/概念/市值）
        ind = ind_map.get(code, {})
        ci = concept_map.get(code, {})
        mv_rows = dp.cache.get_daily_basic_for_code(code) if cfg.asset_class == "stock" else []
        mv_series = {r["trade_date"]: float(r["total_mv"]) / 1e4 for r in mv_rows}
        trades = scan_stock(
            code, b.get("name", ""), rows_desc, cfg,
            ind.get("l1_name", ""), ind.get("l2_name", ""),
            ind.get("l3_name", ""),
            b.get("list_date", ""), mv_series,
            concept_info=ci,
            asset_class=cfg.asset_class,
        )
```

> 注：原 `_one` 里已有 `mv_rows = dp.cache.get_daily_basic_for_code(code)` + `mv_series = {...}` 两行。上面把它包进 `if cfg.asset_class == "stock"`，index 模式直接空 mv_series（指数无市值）。`ind`/`ci` 原来也已在 `_one` 里取，这里合并并加 index 兜底。

- [ ] **Step 6: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_etf_scan_engine.py -v`
Expected: 4 个测试全 PASS。

- [ ] **Step 7: 跑回归——个股版 scan_engine 测试不受影响**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_scan_engine.py tests/winrate/test_smoke.py -v`
Expected: 全 PASS。

- [ ] **Step 8: Commit**

```bash
git add src/marketreview/winrate/scan_engine.py tests/winrate/test_etf_scan_engine.py
git commit -m "feat(etf): scan_engine prepare_klines 分流(index不qfq) + run_scan 按 asset_class 选标的池"
```

---

## Task 7: DashboardService ETF 方法 + 版本号

**Files:**
- Modify: `dashboard/services/dashboard_service.py:1870`（版本号）、`:1900` 后（加 3 个 ETF 方法）
- Test: `tests/winrate/test_service_winrate.py`（追加 ETF 用例）

**Interfaces:**
- Consumes: Task 3 `ensure_csi_pool`/`ensure_index_pool_loaded`；Task 6 `run_scan`（已支持 `asset_class`）。
- Produces: `prepare_winrate_data_etf(start, end, index_pool)`、`check_winrate_coverage_etf(start, end, index_pool)`、`run_winrate_scan_etf(cfg)`。Task 8 依赖。

- [ ] **Step 1: 写失败测试**

在 `tests/winrate/test_service_winrate.py` 末尾追加（若文件不存在则新建，参考现有 service 测试的 mock 风格）：

```python
def test_service_etf_methods_exist():
    """DashboardService 有 3 个 ETF 方法。"""
    from services.dashboard_service import DashboardService
    assert hasattr(DashboardService, "prepare_winrate_data_etf")
    assert hasattr(DashboardService, "check_winrate_coverage_etf")
    assert hasattr(DashboardService, "run_winrate_scan_etf")


def test_check_winrate_coverage_etf_returns_ready_flag(tmp_path, monkeypatch):
    """check_winrate_coverage_etf 调 ensure_csi_pool + 覆盖检查，返回 ready 标志。"""
    from services.dashboard_service import DashboardService
    from unittest.mock import MagicMock
    svc = DashboardService.__new__(DashboardService)
    svc._dp = MagicMock()
    svc._dp.ensure_csi_pool.return_value = 5
    # 模拟所有指数都已缓存 latest date
    svc._dp.cache.get_latest_date.return_value = "2026-07-19"
    svc._dp.cache.get_earliest_date.return_value = "2022-01-01"
    res = svc.check_winrate_coverage_etf("20230101", "now",
                                         index_pool=["931152.CSI"])
    assert "ready" in res
    assert "kline" in res
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_service_winrate.py::test_service_etf_methods_exist -v`
Expected: FAIL，`AttributeError: ... has no attribute 'prepare_winrate_data_etf'`。

- [ ] **Step 3: 加 3 个 ETF 方法**

在 `dashboard/services/dashboard_service.py` 的 `check_winrate_coverage` 方法之后（`generate_ai_summary` 之前），加：

```python
    # ── ETF/行业指数 买点胜率 ──

    def prepare_winrate_data_etf(self, start: str, end: str,
                                  index_pool: list[str], progress_cb=None) -> dict:
        """ETF 数据准备：① ensure_csi_pool（标的池缓存）② ensure_index_pool_loaded（K线）。
        index_pool: UI 选中的指数 ts_code 列表。"""
        log.info("[AI v%s] prepare_winrate_data_etf(%s~%s, %d indices)",
                 self._AI_VERSION, start, end, len(index_pool))
        # 阶段1: 标的池缓存（幂等）
        self._dp.ensure_csi_pool(progress_cb=progress_cb)
        # 阶段2: 选中指数的 K 线
        end_clean = end if end not in ("", "now") else \
            (self._dp.cache.get_latest_date("000001.SZ") or start).replace("-", "")
        start_clean = start.replace("-", "")
        self._dp.ensure_index_pool_loaded(index_pool, start_clean, end_clean,
                                          progress_cb=progress_cb)
        return {"status": "ok"}

    def check_winrate_coverage_etf(self, start: str, end: str,
                                    index_pool: list[str]) -> dict:
        """返回 ETF 数据就绪状态（选中指数 K线门禁）。"""
        start_clean = start.replace("-", "")
        end_clean = end if end not in ("", "now") else \
            (self._dp.cache.get_latest_date("000001.SZ") or start).replace("-", "")
        # 每个选中指数都要覆盖 [start, end]
        missing = []
        ready_count = 0
        for code in index_pool:
            latest = self._dp.cache.get_latest_date(code)
            earliest = self._dp.cache.get_earliest_date(code)
            if latest and earliest:
                if latest.replace("-", "") >= end_clean and \
                   earliest.replace("-", "") <= start_clean:
                    ready_count += 1
                    continue
            missing.append(code)
        ready = len(missing) == 0 and len(index_pool) > 0
        log.info("check_winrate_coverage_etf(%s~%s): %d/%d ready, missing=%d",
                 start, end, ready_count, len(index_pool), len(missing))
        return {"ready": ready,
                "kline": {"ready": ready, "total": len(index_pool),
                          "ready_count": ready_count,
                          "missing_dates": missing[:20]}}

    def run_winrate_scan_etf(self, cfg, progress_cb=None, timing_sink=None):
        """ETF 买点胜率扫描（复用 run_scan，cfg.asset_class 已是 index）。"""
        from marketreview.winrate.scan_engine import run_scan
        from marketreview.winrate.reporter import aggregate
        trades = run_scan(self._dp, cfg, progress_cb=progress_cb, timing_sink=timing_sink)
        stats = aggregate(trades)
        return stats, trades
```

- [ ] **Step 4: bump 版本号**

把 `dashboard/services/dashboard_service.py:1870` 的：

```python
    _AI_VERSION = "9.15.2"
```

改为：

```python
    _AI_VERSION = "9.16.0"
```

（新增 ETF 大功能 → Y+1，Z 归零。见 `docs/memory/ai-version-number.md`：Y=大板块内新增子版块。）

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/winrate/test_service_winrate.py -v`
Expected: 全 PASS（含新 ETF 用例）。

- [ ] **Step 6: 跑回归——所有 winrate 测试**

Run: `.venv/Scripts/python -m pytest tests/winrate/ -v`
Expected: 全 PASS。

- [ ] **Step 7: Commit**

```bash
git add dashboard/services/dashboard_service.py tests/winrate/test_service_winrate.py
git commit -m "feat(etf): DashboardService 加 prepare/check/run ETF 三方法 + 版本 9.16.0"
```

---

## Task 8: ETF 买点胜率页面 + 注册

**Files:**
- Create: `dashboard/pages/07_ETF买点胜率.py`
- Modify: `dashboard/app.py:25-32`（页面注册列表加 07）

**Interfaces:**
- Consumes: Task 2 `ETF_BUY_POINTS`/`parse_winrate_config(asset_class="index")`；Task 3 `ensure_csi_pool`/`get_csi_pool`；Task 7 `prepare_winrate_data_etf`/`check_winrate_coverage_etf`/`run_winrate_scan_etf`；`save_run`（reporter）。

- [ ] **Step 1: 创建 07 页面**

Create `dashboard/pages/07_ETF买点胜率.py`（仿 `06_买点胜率.py` 结构，去掉市值/行业，加指数池多选）：

```python
"""ETF/行业指数 买点胜率回测 — 用中证行业/主题指数测各买点胜率。"""
import os
import sys
from datetime import datetime, timedelta
import streamlit as st
from dataclasses import replace
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from rendering.styles import PAGE_CSS
from services.dashboard_service import DashboardService
from marketreview.winrate.config import parse_winrate_config, ETF_BUY_POINTS
from marketreview.winrate.reporter import save_run

st.set_page_config(page_title="ETF买点胜率", page_icon="📈", layout="wide")
st.markdown(PAGE_CSS, unsafe_allow_html=True)

svc = DashboardService()
st.title("📈 ETF/行业指数 买点胜率回测")
st.caption(f"中证行业/主题指数 · 单买点胜率 ｜ AI v{DashboardService._AI_VERSION}")

base = parse_winrate_config("config/winrate_config_etf.txt", asset_class="index")

# ── 标的池：从 csi_index_pool 缓存选（首次用拉取）──
svc._dp.ensure_csi_pool()
pool = svc._dp.cache.get_csi_pool()  # [{ts_code, name, category, list_date}]
pool_labels = {r["ts_code"]: f"{r['name']} ({r['ts_code']})" for r in pool}
pool_codes = [r["ts_code"] for r in pool]

# ── 配置区 ──
c1, c2, c3 = st.columns(3)
with c1:
    buy_points = st.multiselect("买点（可多选）", ETF_BUY_POINTS, default=list(ETF_BUY_POINTS))
    win_th = st.number_input("判赢阈值%（盘中浮盈）", 1.0, 50.0, base.win_threshold_pct)
with c2:
    short_ma = st.multiselect("短期均线排列（空=不限）", ["多头", "空头", "盘整"],
                              default=base.short_ma_states)
    long_ma = st.multiselect("长期均线排列（空=不限）", ["多头", "空头", "盘整"],
                             default=base.long_ma_states)
with c3:
    time_stop = st.number_input("时间止损天数", 1, 250, base.time_stop_days)
    workers = st.number_input("并发数", 1, 16, base.max_workers)

c4, c5 = st.columns(2)
with c4:
    start_date = st.text_input("开始日期(YYYYMMDD)", base.start_date)
with c5:
    # 指数池多选：默认全选
    sel_codes = st.multiselect(
        "指数池（默认全选 %d 个）" % len(pool_codes),
        pool_codes,
        default=pool_codes,
        format_func=lambda c: pool_labels.get(c, c),
    )

# 调试标的（单指数）
_ALL = "（跑选中的指数池）"
debug_options = [_ALL] + [pool_labels[c] for c in pool_codes]
debug_label = st.selectbox("🐞 调试标的（默认跑指数池；选中则只跑单只）", debug_options)
debug_code = "" if debug_label == _ALL else debug_label.split("(")[-1].rstrip(")")

cfg = replace(
    base, buy_points=buy_points, win_threshold_pct=win_th,
    short_ma_states=short_ma, long_ma_states=long_ma,
    start_date=start_date, time_stop_days=int(time_stop),
    max_workers=int(workers),
    index_pool=[debug_code] if debug_code else list(sel_codes),
    debug_code=debug_code.strip(),
)

# ── 数据准备 ──
_PREP_LOOKBACK_CAL = 600

def _prep_range(start_date: str, end_date: str) -> tuple[str, str]:
    sd = datetime.strptime(start_date.replace("-", ""), "%Y%m%d")
    prep_start = (sd - timedelta(days=_PREP_LOOKBACK_CAL)).strftime("%Y%m%d")
    prep_end = "" if end_date in ("", "now") else end_date.replace("-", "")
    if not prep_end:
        prep_end = svc._dp.cache.get_latest_date("000001.SZ") or start_date
        prep_end = prep_end.replace("-", "")
    return prep_start, prep_end

prep_start, prep_end = _prep_range(start_date, cfg.end_date)
st.caption(f"📦 数据准备范围：`{prep_start}` ~ `{prep_end}` "
           f"（扫描窗前推 {_PREP_LOOKBACK_CAL} 日历日预热）｜ 指数池 {len(cfg.index_pool)} 个")

_cov_range = st.session_state.get("etf_cov_range")
_cov_cache = st.session_state.get("etf_cov_cache")
_range_match = (_cov_range == (prep_start, prep_end))
_kline = (_cov_cache or {}).get("kline", {}) if _range_match else {}
_kline_ready = bool(_kline.get("ready"))
_data_ready = _kline_ready

if not _cov_cache:
    st.info("⏳ 数据未准备：请先点「数据准备」拉取选中指数的 K 线。")
elif not _range_match:
    st.warning("⚠️ 扫描日期或指数池已变更，数据准备结果失效，请重新点「数据准备」。")
elif _kline.get("error"):
    st.error(f"❌ 校验失败：{_kline.get('error')}，请重试「数据准备」。")
elif _data_ready:
    st.success(f"✅ 数据就绪：{len(cfg.index_pool)} 个指数 K线覆盖。")
else:
    miss = _kline.get("missing_dates", [])
    st.warning(f"⚠️ 数据未就绪：{len(miss)} 个指数 K线缺口。请重试「数据准备」补齐。")

col_prep, _ = st.columns([1, 3])
with col_prep:
    if st.button("📦 数据准备", help="拉取/校验选中指数的日 K"):
        prog = st.progress(0.0)
        status = st.empty()
        status.text("数据准备中（首次拉取选中指数可能几分钟）…")

        def _prep_cb(*args):
            if len(args) >= 3 and isinstance(args[1], (int, float)) and isinstance(args[2], (int, float)):
                cur, total = args[1], args[2]
                if total:
                    prog.progress(min(cur / total, 1.0))
                    status.text(f"数据准备中 [{args[0]}] {cur}/{total}")
                else:
                    status.text(f"数据准备中 [{args[0]}]…")
            elif args:
                status.text(f"数据准备中… {args[0]}")

        try:
            svc.prepare_winrate_data_etf(prep_start, prep_end, cfg.index_pool, progress_cb=_prep_cb)
        except Exception as e:
            st.error(f"数据准备出错：{e}")
        else:
            st.session_state.etf_cov_cache = svc.check_winrate_coverage_etf(prep_start, prep_end, cfg.index_pool)
            st.session_state.etf_cov_range = (prep_start, prep_end)
        prog.progress(1.0)
        status.empty()
        st.rerun()

# ── 运行扫描 ──
if st.button("▶ 运行扫描", type="primary",
             disabled=not (buy_points and cfg.index_pool and _data_ready),
             help="数据就绪后可用" if _data_ready else "请先完成「数据准备」"):
    prog = st.progress(0.0)
    status = st.empty()

    def cb(done, total):
        prog.progress(done / total)
        status.text(f"已扫描 {done}/{total} 个指数")

    timing_sink = []
    import time as _time
    _t0 = _time.perf_counter()
    with st.spinner("ETF 指数扫描中..."):
        stats, trades = svc.run_winrate_scan_etf(cfg, progress_cb=cb, timing_sink=timing_sink)
    _elapsed = _time.perf_counter() - _t0
    scan_meta = {"elapsed": round(_elapsed, 1),
                 "total_indices": len(cfg.index_pool),
                 "max_workers": cfg.max_workers, "trades_n": len(trades)}
    saved_dir = save_run(trades, cfg, scan_meta=scan_meta)
    prog.progress(1.0)
    status.empty()
    st.session_state.etf_stats = stats
    st.session_state.etf_saved_dir = saved_dir

# ── 结果 ──
if st.session_state.get("etf_stats"):
    stats = st.session_state.etf_stats
    saved_dir = st.session_state.get("etf_saved_dir", "")
    if saved_dir:
        st.success(f"✅ 明细已保存到 `{saved_dir}`（每买点一个 CSV + config_snapshot.txt）。")
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

    for bp, s in stats.items():
        st.markdown(f"### 🎯 {bp} — {s.n}次 胜率{s.win_rate:.1%}")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("大胜利", s.big_win_n)
        m2.metric("小胜利", s.small_win_n)
        m3.metric("盘中止损", s.stop_n)
        m4.metric("亏损", s.loss_n)
```

- [ ] **Step 2: 注册 07 页面**

把 `dashboard/app.py` 的页面列表（第 25-32 行）末尾 `06` 之后加 `07`：

```python
pg = st.navigation([
    st.Page("pages/00_控制台.py", title="控制台", icon="🎛️", default=True),
    st.Page("pages/01_市场全景.py", title="市场全景", icon="📊"),
    st.Page("pages/02_板块分析.py", title="板块分析", icon="🏭"),
    st.Page("pages/03_个股追踪.py", title="个股追踪", icon="📋"),
    st.Page("pages/04_波段分析.py", title="波段分析", icon="📐"),
    st.Page("pages/06_买点胜率.py", title="买点胜率", icon="🎯"),
    st.Page("pages/07_ETF买点胜率.py", title="ETF买点胜率", icon="📈"),
])
```

- [ ] **Step 3: 重启 Streamlit + 冒烟**

Run: `.venv/Scripts/python restart_streamlit.py`
Expected: `[OK] No startup errors` + Uvicorn started。

Run: `sleep 2 && curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://localhost:8501`
Expected: `HTTP 200`。

- [ ] **Step 4: 手动验证页面加载（冒烟）**

打开 http://localhost:8501 → 切到「ETF买点胜率」页 → 确认：
- 标题"📈 ETF/行业指数 买点胜率回测"显示
- AI 版本号显示 `9.16.0`
- 买点多选默认勾选 12 个
- 指数池多选有内容（674 个左右，首次加载会调 `ensure_csi_pool` 拉取，可能几十秒）
- 无 Streamlit 报错红框

- [ ] **Step 5: Commit**

```bash
git add dashboard/pages/07_ETF买点胜率.py dashboard/app.py
git commit -m "feat(etf): 新增 07_ETF买点胜率 页面 + 注册"
```

---

## Task 9: 集成验证 + 单指数端到端跑通

**Files:**
- 无新文件，验证已有改动。

**Interfaces:**
- 验证 Task 1-8 端到端联动。

- [ ] **Step 1: 跑全部 winrate 测试**

Run: `.venv/Scripts/python -m pytest tests/winrate/ -v`
Expected: 全 PASS（含 ETF 新测试 + 个股版回归测试）。

- [ ] **Step 2: 单指数端到端冒烟（调试模式）**

设 `config/winrate_config_etf.txt` 的 `调试标的=931152.CSI`（CS创新药），临时改 `开始日期=20240101` 缩小范围。

在 07 页面：
1. 买点选「波段50%」一个
2. 指数池默认（调试模式只跑单只）
3. 点「数据准备」→ 等 CS创新药 K 线拉取 → 显示就绪
4. 点「运行扫描」→ 等扫描完
5. 确认结果表有「波段50%」一行，触发次数 > 0（或确认信号量合理）

> 若调试模式下该指数在 2024 年无波段50%信号，换「回调一半」或换 `调试标的=930851.CSI`（云计算）重试。重点是流程跑通、不报错。

- [ ] **Step 3: 回归——个股版 06 页面不受影响**

在 06 页面随便选一个买点 + 单只调试标的 → 确认能正常跑（`asset_class` 默认 stock，走原路径）。

- [ ] **Step 4: 恢复调试配置**

把 `config/winrate_config_etf.txt` 的 `调试标的=` 改回空、`开始日期=20230101`。

- [ ] **Step 5: 最终版本号确认 + 提交（如有配置改动）**

Run: `.venv/Scripts/python -c "from services.dashboard_service import DashboardService; print(DashboardService._AI_VERSION)"`
（在 dashboard 目录下跑，或确保 sys.path 含 dashboard）
Expected: `9.16.0`。

```bash
git add config/winrate_config_etf.txt
git commit -m "chore(etf): 恢复 ETF 配置默认值（调试标的清空）" --allow-empty
```

（若 Task 9 没改任何文件，跳过此 commit。）

- [ ] **Step 6: 推送**

```bash
git push origin feature/trading-system-v2
```

---

## Self-Review Notes

**Spec coverage:**
- §2 数据层 → Task 3 ✅
- §2.5 复权分流 → Task 6 (prepare_klines) ✅
- §2.6 涨跌停分流 → Task 5 (board_limit_pct) ✅
- §3 配置层 → Task 1 (txt) + Task 2 (config.py) ✅
- §4 模拟器 → Task 5 ✅（entry_mode 留字段不实现，spec §9 已标 YAGNI）
- §5 买点适配 → Task 2 (ETF_BUY_POINTS) ✅；checker 零改动（方案B）✅
- §6 扫描引擎 → Task 6 ✅
- §7 页面 → Task 8 ✅
- §10 验证计划 → Task 9 ✅

**Placeholder scan:** 无 TBD/TODO。entry_mode 是 spec 明确的"留接口不实现"，非占位。

**Type consistency:** `asset_class: str = "stock"` 在 config/trade_sim/scan_engine/filters 全一致；`ensure_csi_pool`/`ensure_index_pool_loaded`/`has_csi_pool`/`get_csi_pool`/`upsert_csi_pool`/`clear_csi_pool` 命名一致；`prepare_winrate_data_etf`/`check_winrate_coverage_etf`/`run_winrate_scan_etf` 命名一致。

**已知风险:**
- Task 6 的 `run_scan` 改动较大（标的池分流 + `_one` 内 mv_series 分流），需重点跑 `test_scan_engine.py` 回归。
- `test_config.py::test_buy_point_three_state` **已在当前代码库上 FAIL**（已验证）——它断言 `BUY_POINT_STAGE["MA20支撑"] == "trial"`，但 config.py 实际是 `"disabled"`（MA 家族后来被禁用、测试没同步更新）。这是**预先存在**的历史问题，不是本计划引入。Task 2 Step 8 跑回归时会看到这 1 个 FAIL（4 passed/1 failed），**记录但不修**，除非用户明确要求修。Task 2 的回归目标只是确认"我的改动没新增 FAIL"，而非让整个文件变绿。
- Task 5 Step 6 的 `test_trade_sim.py` 回归同理：若有个股版测试因 `simulate_trade` 新增 `asset_class` 默认参数而 FAIL，要修；但因 `asset_class="stock"` 默认走原路径，理论上不应有新 FAIL。
