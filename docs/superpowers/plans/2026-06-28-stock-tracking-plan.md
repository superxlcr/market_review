# 个股追踪 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现个股追踪页面，复用 index/industry 的 render_ohlcv_section 模式，针对个股做 ATR 形态判定 + MA55/144 均线 + 去掉 BIAS/权重。

**Architecture:** 自底向上——先加 ATR 计算 → 改形态识别 → 扩展 render_ohlcv_section → 加 DashboardService 方法 → 改控制台 → 写页面 → 版本号。

**Tech Stack:** Python, Streamlit, Pandas, NumPy, Plotly

**Spec:** `docs/superpowers/specs/2026-06-28-stock-tracking-design.md`

## Global Constraints

- AI 版本号 X 递增：`_AI_VERSION` 从 `"1.2.1"` → `"2.0.0"`
- 颜色约定：红 = 看多/涨，绿 = 看空/跌（不可翻转）
- 日期格式：DB 查询永远 YYYYMMDD
- 缓存读必须 `WHERE trade_date = ?`
- 个股 BIAS 乖离率不展示
- 个股均线：MA5/MA10/MA20/MA55/MA144/MA240
- 指数/行业均线：MA5/MA10/MA20/MA60/MA120/MA240（不变）

---

### Task 1: 配置文件

**Files:**
- Create: `config/watchlist_stocks.txt`

**Interfaces:**
- Produces: `config/watchlist_stocks.txt` — 被 Task 6 `get_watchlist_stocks()` 读取

- [ ] **Step 1: 创建配置文件**

```text
# 自选个股（一行一个股票名称，# 开头为注释）
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

- [ ] **Step 2: 验证文件存在**

```bash
cat config/watchlist_stocks.txt
```

- [ ] **Step 3: Commit**

```bash
git add config/watchlist_stocks.txt
git commit -m "feat: add watchlist_stocks.txt config"
```

---

### Task 2: ATR 计算

**Files:**
- Modify: `src/marketreview/tools/technical.py` — 在 `calc_bias()` 函数后面新增 `calc_atr()`

**Interfaces:**
- Produces: `calc_atr(df, period=14) -> list[float]` — 返回 ATR 值列表（与 df 等长），前 period-1 行为 NaN

- [ ] **Step 1: 新增 calc_atr 函数**

在 `src/marketreview/tools/technical.py` 的 `calc_bias()` 函数后面添加：

```python
def calc_atr(df: pd.DataFrame, period: int = 14) -> list[float]:
    """Compute ATR (Average True Range) for given period.

    Args:
        df: OHLCV DataFrame (date ASC), must have open/high/low/close columns.
        period: ATR lookback period (default 14).

    Returns:
        List of ATR values (same length as df), NaN for first period-1 rows.
    """
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)

    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    atr = np.full(n, np.nan)
    # Seed: first ATR = simple average of first period TRs
    if n > period:
        atr[period] = np.mean(tr[1:period + 1])
        # Wilder's smoothing for subsequent values
        for i in range(period + 1, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr.tolist()
```

- [ ] **Step 2: 验证函数可导入**

```python
# In Python REPL:
from marketreview.tools.technical import calc_atr
print("calc_atr imported OK")
```

- [ ] **Step 3: Commit**

```bash
git add src/marketreview/tools/technical.py
git commit -m "feat: add calc_atr(14) for stock ATR-normalised pattern detection"
```

---

### Task 3: K线形态 ATR 双方案

**Files:**
- Modify: `src/marketreview/tools/kline_patterns.py` — 改 `_candle_shape()` 和 `detect_patterns()`

**Interfaces:**
- Consumes: `calc_atr()` from Task 2
- Modifies: `_candle_shape(o, h, l, c, atr=None)` — 新增 atr 参数，stock 时用 ATR 判影线
- Modifies: `detect_patterns(df, obj_type)` — stock 时计算 ATR 并传入 classify_candle
- Produces: `classify_candle()` 中 stock 路径的 atr 传递完整

- [ ] **Step 1: 修改 _candle_shape 支持 ATR 影线判定**

在 `src/marketreview/tools/kline_patterns.py` 中修改 `_candle_shape()` 函数签名和影线判定逻辑：

```python
# 在文件头部新增 ATR 影线阈值常量（放在 LONG_SHADOW_BODY_RATIO 下方）
LONG_SHADOW_BODY_RATIO = 2.0
STOCK_SHADOW_ATR_RATIO = 0.3   # 个股：影线 ≥ ATR × 0.3 → 长影线


def _candle_shape(o: float, h: float, l: float, c: float,
                  atr: float | None = None) -> dict[str, Any]:
    """Analyze the shape of a single candle — body, shadows, etc.

    Args:
        atr: ATR(14) value. When provided (stock mode), shadow significance
             is judged by shadow_length / ATR instead of body ratio.
    """
    body = abs(c - o)
    total = h - l
    if total == 0:
        return {
            "body": 0.0, "total_range": 0.0,
            "upper_wick": 0.0, "lower_wick": 0.0,
            "body_pct": 0.0, "upper_pct": 0.0, "lower_pct": 0.0,
            "has_long_upper": False, "has_long_lower": False,
            "is_doji": True,
        }

    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    body_pct = round(body / total * 100, 1)
    upper_pct = round(upper_wick / total * 100, 1)
    lower_pct = round(lower_wick / total * 100, 1)

    # ── 影线判定 ──
    if atr is not None and atr > 0:
        # 个股模式：ATR 归一化
        has_long_upper = upper_wick >= atr * STOCK_SHADOW_ATR_RATIO
        has_long_lower = lower_wick >= atr * STOCK_SHADOW_ATR_RATIO
    else:
        # 指数/行业模式：固定比例
        has_long_upper = upper_wick >= body * LONG_SHADOW_BODY_RATIO
        has_long_lower = lower_wick >= body * LONG_SHADOW_BODY_RATIO

    return {
        "body": round(body, 4),
        "total_range": round(total, 4),
        "upper_wick": round(upper_wick, 4),
        "lower_wick": round(lower_wick, 4),
        "body_pct": body_pct,
        "upper_pct": upper_pct,
        "lower_pct": lower_pct,
        "has_long_upper": has_long_upper,
        "has_long_lower": has_long_lower,
        "is_doji": body_pct < 5.0,
    }
```

- [ ] **Step 2: 修改 classify_candle 传递 atr 到 _candle_shape**

在 `classify_candle()` 中修改 `_candle_shape` 调用：

```python
def classify_candle(
    row,
    prev_close: float | None = None,
    obj_type: str = "index",
    atr: float | None = None,
) -> dict[str, Any]:
    o = float(row["open"])
    h = float(row["high"])
    l = float(row["low"])
    c = float(row["close"])
    pc = prev_close if prev_close is not None else c

    entity = _entity_strength(o, c, pc, obj_type, atr)
    shape = _candle_shape(o, h, l, c, atr)   # ← 传入 atr

    return {**entity, **shape}
```

- [ ] **Step 3: 修改 detect_patterns 为 stock 计算 ATR 并传入各 detector**

在 `detect_patterns()` 函数开头添加 ATR 计算逻辑：

```python
def detect_patterns(
    df: pd.DataFrame, obj_type: str = "index",
) -> list[dict[str, Any]]:
    if df.empty or len(df) < 2:
        return []

    # ── 个股模式：计算 ATR(14) 用于实体强度 + 影线判定 ──
    atr = None
    if obj_type == "stock":
        from .technical import calc_atr
        atr_vals = calc_atr(df, period=14)
        # 取最后一根有效 ATR 值
        atr = next((v for v in reversed(atr_vals) if not np.isnan(v)), None)
        if atr is None or atr <= 0:
            atr = None  # 数据不足，退化为通用标签

    # ── 逐 candle 分类（带 ATR）──
    # ... (existing classify loop)

    # ── 运行 detector ──
    # ... (existing pattern matching)
```

然后在 `detect_patterns()` 的每个 detector 调用处，对使用 `_candle_shape` 的 detector（如 `detect_spinning_top`），需要确保其内部调用 `_candle_shape` 时也传入 atr。但由于 `_candle_shape` 已经支持 atr=None 的默认，且现有的 detector 内部硬编码了无 atr 调用——需要系统性修改。

**更简洁的方式**：每个 detector 内部调用 `_candle_shape()` 的地方，都改为接受可选的 atr 参数并在 stock 时传入。但最干净的方案是：在 `detect_patterns()` 中一次性做完 candle 分类，detector 直接用分类好的 candle label。

实际修改：在 `detect_patterns()` 中将 atr 传入需要 `_candle_shape` 的 detector 调用，为每个 detector 签名加 `atr=None` 参数。

修改每个 pattern detector 的函数签名，增加 `atr: float | None = None` 参数，并在内部 `_candle_shape()` 调用处传入：

```python
# detect_spinning_top 中：
shape = _candle_shape(
    float(curr["open"]), float(curr["high"]),
    float(curr["low"]), float(curr["close"]),
    atr=atr,  # ← 新增
)

# detect_bullish_engulfing_shadow 中：
prev_shape = _candle_shape(
    float(prev["open"]), float(prev["high"]),
    float(prev["low"]), float(prev["close"]),
    atr=atr,  # ← 新增
)

# detect_bearish_engulfing_shadow 中：
prev_shape = _candle_shape(
    float(prev["open"]), float(prev["high"]),
    float(prev["low"]), float(prev["close"]),
    atr=atr,  # ← 新增
)

# detect_high_level_long_yang 中：
# 使用 INDEX_LONG_PCT 固定阈值判定长阳，个股时改用 ATR
```

对于 `detect_high_level_long_yang`，需要针对 stock 改用 ATR 判定长阳：

```python
def detect_high_level_long_yang(
    df: pd.DataFrame, obj_type: str = "index",
    atr: float | None = None,
) -> dict[str, Any] | None:
    # ... (前面的高档判定不变)
    
    # ③ 长阳判定
    prev_close = float(df.iloc[-2]["close"])
    close = float(curr["close"])
    open_ = float(curr["open"])
    
    if obj_type == "stock" and atr and atr > 0:
        body = abs(close - open_)
        is_long = (body / atr) >= 0.5
    else:
        chg_pct = abs((close / prev_close - 1) * 100)
        is_long = chg_pct > INDEX_LONG_PCT
    
    if not is_long:
        return None
    # ... (其余不变)
```

修改所有 7 个 detector 的函数签名都加上 `atr=None`，`detect_patterns()` 中调用时传入 atr。

在 `_PATTERN_DETECTORS` 中保持不变（detector 本身已支持 atr 参数）。

- [ ] **Step 4: 验证各 detector 的 atr 传递不破坏现有行为**

当 `obj_type="index"` 且 `atr=None` 时，所有 detector 行为应与之前完全一致。

- [ ] **Step 5: Commit**

```bash
git add src/marketreview/tools/kline_patterns.py
git commit -m "feat: ATR dual scheme — entity + shadow normalisation for stocks"
```

---

### Task 4: ma_arrangement 支持自定义中长期周期

**Files:**
- Modify: `src/marketreview/tools/technical.py` — `ma_arrangement()` 函数

**Interfaces:**
- Consumes: nothing new
- Produces: `ma_arrangement(df, medium_long_periods=[60, 120, 240])` — 新增可选参数

- [ ] **Step 1: 修改 ma_arrangement 函数签名**

```python
def ma_arrangement(df: pd.DataFrame,
                   medium_long_periods: list[int] | None = None) -> str:
    """
    Determine MA arrangement by splitting into two groups:
      - 短期: MA5 / MA10 / MA20
      - 中长期: 默认 MA60 / MA120 / MA240，可自定义

    Each group is classified as 多头 / 空头 / 缠绕, then combined.
    """
    if medium_long_periods is None:
        medium_long_periods = [60, 120, 240]

    all_periods = [5, 10, 20] + list(medium_long_periods)
    mas = calc_ma(df, all_periods)

    def _latest(ma_key: str) -> float | None:
        for v in reversed(mas[ma_key]):
            if not np.isnan(v):
                return float(v)
        return None

    short = [v for v in (_latest(f"MA{p}") for p in [5, 10, 20]) if v is not None]
    medium_long = [v for v in (_latest(f"MA{p}") for p in medium_long_periods) if v is not None]

    # ... (rest unchanged: _judge, combine logic)
```

- [ ] **Step 2: 验证现有调用不受影响**

不传 `medium_long_periods` 时默认 `[60, 120, 240]`，行为不变。

- [ ] **Step 3: Commit**

```bash
git add src/marketreview/tools/technical.py
git commit -m "feat: ma_arrangement accepts custom medium_long_periods for stocks (MA55/MA144)"
```

---

### Task 5: render_ohlcv_section 支持 stock

**Files:**
- Modify: `dashboard/rendering/index_section.py`

**Interfaces:**
- Consumes: `calc_atr()` from Task 2, `ma_arrangement()` from Task 4, ATR patterns from Task 3
- Produces: `render_ohlcv_section(df, code, name, service, section_type, ...)` — `section_type` 新增 `"stock"`

**Changes:**
1. `section_type` validation 加入 `"stock"`
2. 均线 period 按类型选择
3. stock 类型跳过 BIAS section
4. stock 类型跳过 权重贡献/成分股 等 index/industry 专属 section
5. K线形态调用 `get_kline_patterns(df, obj_type="stock")`（需要 service 支持）

- [ ] **Step 1: 修改 section_type validation 和 MA periods 选择**

```python
if section_type not in ("index", "industry", "stock"):
    raise ValueError(
        f"section_type must be 'index', 'industry', or 'stock', "
        f"got {section_type!r}"
    )

# ── 根据类型选择均线周期 ──
if section_type == "stock":
    ma_periods = [5, 10, 20, 55, 144, 240]
    medium_long_periods = [55, 144, 240]
else:
    ma_periods = [5, 10, 20, 60, 120, 240]
    medium_long_periods = [60, 120, 240]
```

- [ ] **Step 2: 修改 ma_arrangement 调用**

```python
arrangement = ma_arrangement(df, medium_long_periods=medium_long_periods)
```

- [ ] **Step 3: 跳过 BIAS section（仅 stock）**

在 BIAS section 前加条件：

```python
if section_type != "stock":
    # ── BIAS Card ──
    st.markdown("**BIAS 乖离率**")
    # ... existing BIAS rendering code ...
```

- [ ] **Step 4: 修改 K线形态调用**

```python
# K线形态
patterns = service.get_kline_patterns(df, obj_type=section_type)
```

注意：需要在 DashboardService 中修改 `get_kline_patterns` 支持 `obj_type` 参数（Task 6 处理）。

- [ ] **Step 5: 跳过 index/industry 专属 section**

`section_type == "industry"` 的成分股分析保持不变。
`section_type == "index"` 的权重贡献保持不变。
stock 类型到达这些检查时自动跳过（条件已限定为 index/industry）。

- [ ] **Step 6: Commit**

```bash
git add dashboard/rendering/index_section.py
git commit -m "feat: render_ohlcv_section supports section_type='stock' with MA55/144 and no BIAS"
```

---

### Task 6: DashboardService 新增方法

**Files:**
- Modify: `dashboard/services/dashboard_service.py`

**Interfaces:**
- Produces: `get_watchlist_stocks() -> dict` — `{"matched": [...], "unmatched": [...]}`
- Produces: `get_kline_patterns(df, obj_type="index") -> list[dict]` — 新增 `obj_type` 参数

- [ ] **Step 1: 修改 get_kline_patterns 支持 obj_type**

```python
def get_kline_patterns(self, df, obj_type: str = "index") -> list[dict]:
    """
    Run all K-line pattern detectors and return matched patterns.
    
    Args:
        df: OHLCV DataFrame (date ASC).
        obj_type: "index", "industry", or "stock".
    """
    try:
        from marketreview.tools.kline_patterns import detect_patterns
        return detect_patterns(df, obj_type=obj_type)
    except Exception as e:
        log.warning("get_kline_patterns failed: %s", e)
        return []
```

- [ ] **Step 2: 新增 get_watchlist_stocks 方法**

```python
def get_watchlist_stocks(self) -> dict:
    """
    Read config/watchlist_stocks.txt and match against stock_basic_cache.
    
    Returns:
        {"matched": [{"ts_code": str, "name": str, "industry": str}, ...],
         "unmatched": [str, ...]}
    """
    import os as _os
    
    config_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "config", "watchlist_stocks.txt"
    )
    
    matched = []
    unmatched = []
    
    if not _os.path.exists(config_path):
        log.warning("watchlist_stocks.txt not found at %s", config_path)
        return {"matched": matched, "unmatched": unmatched}
    
    with open(config_path, "r", encoding="utf-8") as f:
        names = [
            line.strip() for line in f
            if line.strip() and not line.strip().startswith("#")
        ]
    
    # Batch lookup: get all stock basic info
    all_stocks = self._dp.cache.get_all_stocks()  # list of {ts_code, name, ...}
    name_map = {s["name"]: s for s in all_stocks}
    
    for name in names:
        stock = name_map.get(name)
        if stock:
            # Get industry
            industry_row = self._dp.cache.get_stock_industry(stock["ts_code"])
            industry = industry_row["L1"] if industry_row else "未知"
            matched.append({
                "ts_code": stock["ts_code"],
                "name": stock["name"],
                "industry": industry,
            })
        else:
            unmatched.append(name)
    
    log.info("get_watchlist_stocks: matched=%d unmatched=%d",
             len(matched), len(unmatched))
    return {"matched": matched, "unmatched": unmatched}
```

**注意**：`get_all_stocks()` 和 `get_stock_industry()` 这两个 cache 方法需要确认是否存在。如果不存在，需改用 `_dp` 的其他查询方法。实际实现时应检查 `DataProvider` 的 cache 接口，可能通过 SQL 直接查询 `stock_basic_cache` 和 `stock_industry_cache` 表。

- [ ] **Step 3: Commit**

```bash
git add dashboard/services/dashboard_service.py
git commit -m "feat: add get_watchlist_stocks() and obj_type param to get_kline_patterns()"
```

---

### Task 7: 控制台自选个股 expander

**Files:**
- Modify: `dashboard/pages/00_控制台.py`

**Interfaces:**
- Consumes: `get_watchlist_stocks()` from Task 6

- [ ] **Step 1: 在控制台页面添加自选个股 expander**

在"快速跳转"行之前（`st.markdown("---")` 前）添加：

```python
# ── 自选个股 ──
with st.expander("📋 自选个股", expanded=False):
    st.markdown("**配置文件：** `config/watchlist_stocks.txt`")

    _stocks_data = _service.get_watchlist_stocks()
    _stocks = _stocks_data["matched"]
    _stocks_unmatched = _stocks_data["unmatched"]

    if not _stocks and not _stocks_unmatched:
        st.caption("暂无自选个股，请在 `config/watchlist_stocks.txt` 中配置")
    else:
        if _stocks:
            _rows = ""
            for _i, _s in enumerate(_stocks):
                _rows += (
                    f"<tr>"
                    f"<td style='text-align:center;'>{_i + 1}</td>"
                    f"<td style='color:#888;font-size:14px;'>{_s['ts_code']}</td>"
                    f"<td style='font-weight:600;'>{_s['name']}</td>"
                    f"<td style='color:#888;'>{_s['industry']}</td>"
                    f"<td style='text-align:center;'>✅</td>"
                    f"</tr>"
                )
            st.html(f"""
            <table style="width:100%;font-size:15px;border-collapse:collapse;">
                <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;">
                    <th style="text-align:center;width:30px;">#</th>
                    <th style="text-align:left;">代码</th>
                    <th style="text-align:left;">名称</th>
                    <th style="text-align:left;">行业</th>
                    <th style="text-align:center;">状态</th>
                </tr></thead>
                <tbody>{_rows}</tbody>
            </table>
            """)
        if _stocks_unmatched:
            _names = "、".join(_stocks_unmatched)
            st.warning(f"⚠️ 以下 {len(_stocks_unmatched)} 个名称未匹配到数据库：**{_names}**，请检查拼写")
```

- [ ] **Step 2: 验证页面可正常渲染**

控制台页面应显示"📋 自选个股" expander，列出 10 只自选股。

- [ ] **Step 3: Commit**

```bash
git add dashboard/pages/00_控制台.py
git commit -m "feat: add watchlist stocks expander to console"
```

---

### Task 8: 个股追踪页面

**Files:**
- Modify: `dashboard/pages/03_个股追踪.py` — 重写

**Interfaces:**
- Consumes: `DashboardService`, `render_ohlcv_section(section_type="stock")`, `get_watchlist_stocks()`

- [ ] **Step 1: 重写页面**

```python
"""
Agent 3 — 个股追踪页面
展示自选个股的技术分析，每只个股以 expander 形式展示。
"""
import streamlit as st
import sys
import os
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from rendering.styles import PAGE_CSS
from services.dashboard_service import DashboardService
from rendering.index_section import render_ohlcv_section

st.markdown(PAGE_CSS, unsafe_allow_html=True)

# ── Date guard ──
_td = st.session_state.get("trade_date")
if not _td:
    st.warning("⚠️ 尚未选择日期，请前往「控制台」设置")
    st.stop()

st.title("📋 个股追踪")
st.caption("Agent 3 — 个股技术分析")

st.markdown(
    f"📅 当前日期：<span style='color:#e53935;font-weight:bold;'>"
    f"{_td[:4]}-{_td[4:6]}-{_td[6:8]}</span>",
    unsafe_allow_html=True,
)

st.divider()

_service = DashboardService()

# ── 加载自选个股 ──
_stocks_data = _service.get_watchlist_stocks()
_stocks = _stocks_data["matched"]
_unmatched = _stocks_data["unmatched"]

if _unmatched:
    _names = "、".join(_unmatched)
    st.warning(f"⚠️ {len(_unmatched)} 个名称未匹配：**{_names}**")

if not _stocks:
    st.info("暂无自选个股，请在 `config/watchlist_stocks.txt` 中配置")
    st.stop()

# ── 逐只渲染 ──
for s in _stocks:
    code = s["ts_code"]
    name = s["name"]
    industry = s["industry"]

    # 加载个股 K 线
    df = _service.get_index_data(code, lookback=360, end_date=_td)

    if df.empty:
        with st.expander(f"{name} ({code}) — {industry} | ⚠️ 无数据", expanded=False):
            st.warning(f"暂无 {name} 的 K 线数据")
        continue

    # 计算涨跌幅用于标题
    latest_close = float(df["close"].iloc[-1])
    if len(df) >= 2:
        prev_close = float(df["close"].iloc[-2])
        chg_pct = (latest_close / prev_close - 1) * 100
    else:
        chg_pct = 0.0

    chg_sign = "+" if chg_pct >= 0 else ""
    chg_color = "#e53935" if chg_pct >= 0 else "#43a047"

    # ── 实体判定（ATR）用于标题状态 ──
    from marketreview.tools.technical import calc_atr
    atr_vals = calc_atr(df, period=14)
    atr = next((v for v in reversed(atr_vals) if not np.isnan(v)), None)

    if atr and atr > 0:
        body = abs(float(df["close"].iloc[-1]) - float(df["open"].iloc[-1]))
        entity_atr = body / atr
        if entity_atr >= 0.5:
            entity_label = "长阳" if chg_pct >= 0 else "长阴"
        elif entity_atr >= 0.25:
            entity_label = "中阳" if chg_pct >= 0 else "中阴"
        else:
            entity_label = "小阳" if chg_pct >= 0 else "小阴"
    else:
        entity_label = "阳线" if chg_pct >= 0 else "阴线"

    # ── Expander 标题 ──
    title_html = f"""
    {name} ({code}) — {industry} |
    <span style="color:{chg_color};">{chg_sign}{chg_pct:.2f}%</span> |
    {entity_label}
    """

    with st.expander(title_html, expanded=False):
        render_ohlcv_section(df, code, name, _service, section_type="stock")

st.divider()
st.caption("编辑自选个股：修改 `config/watchlist_stocks.txt` 后刷新页面")
```

- [ ] **Step 2: 验证页面渲染**

启动 dashboard 确认：
1. 显示 10 只个股的 expander 列表
2. 每个 expander 标题显示名称、代码、行业、涨跌幅、实体标签
3. 展开后显示完整技术分析（K线图 + 均线 + 成交额 + KD + RSI，无 BIAS/权重）

- [ ] **Step 3: Commit**

```bash
git add dashboard/pages/03_个股追踪.py
git commit -m "feat: rewrite stock tracking page with real data and ATR-based analysis"
```

---

### Task 9: 版本号升级

**Files:**
- Modify: `dashboard/services/dashboard_service.py` — `_AI_VERSION`

- [ ] **Step 1: 升级版本号**

```python
_AI_VERSION = "2.0.0"  # was "1.2.1"
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/services/dashboard_service.py
git commit -m "chore: bump AI version to 2.0.0 — 个股追踪上线"
```

---

## 改动文件总结

| # | 文件 | 操作 | 说明 |
|---|------|:----:|------|
| 1 | `config/watchlist_stocks.txt` | 新建 | 10 只自选个股 |
| 2 | `src/marketreview/tools/technical.py` | 改 | 新增 `calc_atr()`，`ma_arrangement()` 加参数 |
| 3 | `src/marketreview/tools/kline_patterns.py` | 改 | ATR 双方案：实体强度 + 影线判定 |
| 4 | `dashboard/rendering/index_section.py` | 改 | 支持 `section_type="stock"` |
| 5 | `dashboard/services/dashboard_service.py` | 改 | `get_watchlist_stocks()`，`get_kline_patterns(obj_type)`，版本号 2.0.0 |
| 6 | `dashboard/pages/00_控制台.py` | 改 | 新增自选个股 expander |
| 7 | `dashboard/pages/03_个股追踪.py` | 重写 | 真实数据 + ATR 分析 |
