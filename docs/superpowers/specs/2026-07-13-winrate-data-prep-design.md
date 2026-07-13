# 买点胜率 — 数据准备按钮 设计文档

日期：2026-07-13
状态：待实现
版本：v9.7.0 → **v9.8.0**（feature，Y+1）
关联：
- [2026-07-11-buypoint-winrate-design.md](./2026-07-11-buypoint-winrate-design.md)（胜率引擎本体）
- [2026-07-12-buypoint-winrate-analysis.md](./2026-07-12-buypoint-winrate-analysis.md)（方法论与运行记录）
- `ARCHITECTURE.md §5`（数据加载流水线）、`§5.11`（关键常量）

---

## 1. 背景与目标

用户要把买点胜率的**测试周期拉长**（回看更多年份），意味着单次扫描需要更长的日 K 历史。现有「买点胜率」页只有 `▶ 运行扫描` 按钮，直接调 `run_winrate_scan`，它依赖 cache 已就绪——但新电脑/新拉取时 cache 可能只有最近若干天数据，直接跑会让早期信号因前置数据不足（MA240、band lookback 算不出来）而**静默丢样本**，结果不可信。

### 目标
- 在「运行扫描」旁新增 **`📦 数据准备`** 按钮：按下后按胜率扫描所需范围拉取/校验全市场日 K + 复权因子。
- **数据未就绪时禁用「运行扫描」**（硬门禁），避免在缺数据状态下跑出误导性结果。
- 数据范围**跟随 `winrate_config.txt` 的扫描窗**（`开始日期` ~ `结束日期`），并前推预热缓冲。
- 复用项目既有数据加载主路径与滑动窗口规划，不重复造轮。

### 非目标
- 不改胜率引擎（`winrate/` 模块）本身的任何逻辑。
- 不改 `winrate_config.txt` 的字段集（仅复用现有 `开始日期/结束日期`）。
- 不做后台异步拉取（保持页面内同步进度条，与控制台风格一致）。
- 不引入 3浪3 维度本身（那是后续独立功能；本设计只确保其所需前置数据也被覆盖）。

---

## 2. 滑动窗口与预热缓冲

### 2.1 各计算维度的前置数据需求

胜率扫描在信号日 T 需要「截至 T」的历史来算指标，前置需求（交易日）：

| 维度 | 最长指标/窗口 | 前置（交易日） | 出处 |
|---|---|---|---|
| 胜率 MA240 收盘止损 | MA240 | 240 | `scan_engine._MA_PERIODS` 含 240 |
| 胜率 band 分析 | `band_lookback=300` | 300 | `scan_stock(band_lookback=300)` |
| 胜率 ATR(14) | ATR(14) | 14 | `calc_atr(period=14)` |
| 3浪3（后续引入） | WR(20)+SMA 收敛 | ~120 | `wave33.py` `earliest - 180cal` |

**瓶颈 = band 的 300 交易日**。3浪3 的 ~120 交易日被完全覆盖。

### 2.2 前推量定档：600 日历日

- 600 日历日 ≈ 400 交易日，盖住 band(300) + MA240 + 3浪3，给 band 留 100 根余量。
- 未来调大 `band_lookback` 或加更长周期指标也不至于立刻不够。
- 多拉 100 天成本可忽略。

### 2.3 数据准备范围

```
prep_start = start_date − 600 日历日
prep_end   = end_date（"now" 解析为数据最新日）
```

> scan_engine 读数据是 `get_daily(code, limit=2000)`（≈3000 日历日）。当 `start_date` 距 `end_date` 不超过 ~2000 交易日时，`limit=2000` 本就覆盖预热段；本设计仍统一前推 600 日历日作为**显式下限**，保证 `start_date` 当天的 MA240/band 一定有足够前置，不依赖 `limit=2000` 的隐式覆盖。

---

## 3. 方案选择：复用 `ensure_data_loaded` 主路径

**方案 A（采纳）**：给 `ensure_data_loaded` 加可选 `min_fetch_start` 参数，胜率页传入 `start_date - 600天`。主路径已处理 daily + adj_factor 分页拉取 + 覆盖率校验 + 行业/指数，复权因子不漏。

否决方案：
- B（增强 `ensure_data_loaded_for_codes`）：它只拉 K 线不拉 adj_factor、且串行无并发，补齐这两点等于重写主路径部分逻辑，重复造轮。
- C（winrate 专用新方法）：最灵活但代码量最大、最易偏离项目既有模式。

---

## 4. 数据层改动（`src/marketreview/data/`）

### 4.1 `data_provider.py` — `ensure_data_loaded` 加参数

签名增加 `min_fetch_start`：

```python
def ensure_data_loaded(
    self, end_date: str, progress_cb=None,
    extra_industry_codes: list[str] | None = None,
    min_fetch_start: str | None = None,   # 🆕 下限：fetch_start 不晚于此
) -> dict:
```

逻辑改动（fetch_start 压低 + 头部缺口判断同步收紧）：

```python
fetch_start = (end_dt - timedelta(days=_FETCH_DAYS)).strftime("%Y%m%d")
if min_fetch_start:
    floor = min_fetch_start.replace("-", "")
    if floor < fetch_start:
        fetch_start = floor
        log.info("ensure_data_loaded: fetch_start lowered to min_fetch_start=%s (orig via _FETCH_DAYS)", floor)
```

- 取 `min`（更早者）：`min_fetch_start` 是下限，fetch_start 不能晚于它。

**头部缺口判断必须同步收紧**（关键，否则漏拉前置段）：
现有逻辑（116-123 行）：`if proxy_earliest > check_start: 补 (fetch_start, proxy_earliest-1)`。
当 `min_fetch_start` 把 `fetch_start` 压低、但 `proxy_earliest` 介于 `min_fetch_start` 和 `check_start` 之间时，原判断不触发 → `[min_fetch_start, proxy_earliest)` 该补没补。修正为：

```python
# 头部缺口：缓存最早日若晚于「有效下限」就补
effective_floor = max(check_start, min_fetch_start) if min_fetch_start else check_start
if proxy_earliest_clean > effective_floor:
    missing_ranges.append((fetch_start, _yesterday(proxy_earliest_clean)))
```

即：传了 `min_fetch_start` 时，头部判断门槛从 `check_start` 放宽到 `min_fetch_start`（更早），确保 floor 之前的缺口也被识别并补齐。不传时 `effective_floor = check_start`，行为零变化。

- `check_start`（_CHECK_DAYS=500）变量本身**不变**，仍用于未传 floor 时的默认头部判断。
- `db_start`（市值，_DB_FETCH_DAYS=180）不动——市值过滤本就用补齐的历史 `daily_basic`，与 K 线前置解耦。
- `_validate_coverage(fetch_start, end)`（136 行）沿用压低后的 `fetch_start` → 覆盖率校验范围自动扩大到 `[min_fetch_start, end]`，这是期望行为（前置段也校验），无需额外改。
- 其余 daily + adj_factor + 指数/行业逻辑完全不动。
- 现有调用方（控制台）不传 `min_fetch_start`，行为零变化（回归安全）。

### 4.2 `data_provider.py` — 新增 `check_kline_coverage`

```python
def check_kline_coverage(self, start: str, end: str,
                         threshold: float = 0.9) -> dict:
    """检查 [start,end] 每个交易日的 K线覆盖率。
    分母 = get_stock_basic_count()（与 _validate_coverage 口径一致）。
    返回:
      {ready: bool, total_dates: int, covered_dates: int,
       missing_dates: list[str], min_ratio: float, error: str|None}
    - ready = (missing_dates 为空)
    - missing_dates = ratio < threshold 的日期，升序，最多保留前 50 个用于展示
    """
```

实现：调 cache_manager 新增的 `count_daily_by_date_range(start, end)`（一条 GROUP BY，返回 `{date: count}`），逐日算 `ratio = count / total`，收集 `< threshold` 的日期。total_dates = 返回的日期数。若 `stock_basic_count == 0` → `ready=False, error="stock_basic 为空"`。

### 4.3 `cache_manager.py` — 新增 `count_daily_by_date_range`

```python
def count_daily_by_date_range(self, start: str, end: str) -> dict[str, int]:
    """一条 GROUP BY 查 [start,end] 每个交易日行数。返回 {date: count}。"""
```

避免 N 次 `count_daily_date` 查询（N 可能 500~750）。SQL：`SELECT trade_date, COUNT(*) FROM tushare_cache WHERE trade_date BETWEEN ? AND ? GROUP BY trade_date`。

### 4.4 日志埋点

| 位置 | 级别 | 内容 |
|---|---|---|
| `ensure_data_loaded` 接收 min_fetch_start 且生效 | INFO | `fetch_start lowered to min_fetch_start=X (orig=Y)` |
| `check_kline_coverage` 入口/结果 | INFO | `start~end: total=N, covered=M, missing=K, min_ratio=R` |
| `missing_dates` 非空 | WARNING | 前 10 个缺口日期 + 总数 |
| 每日 count / ratio | DEBUG | 逐日明细 |
| `stock_basic` 为空 | WARNING | 引导先拉基础数据 |

---

## 5. 服务层改动（`dashboard/services/dashboard_service.py`）

新增两个方法，版本号 `_AI_VERSION` 由 `9.7.0` → `9.8.0`。

```python
def prepare_winrate_data(self, start: str, end: str, progress_cb=None) -> dict:
    """拉取/校验 [start,end] 全市场 K线+复权因子，复用 ensure_data_loaded 主路径。
    start 通常 = winrate start_date − 600 日历日（预热缓冲）。"""
    log.info("[AI v%s] prepare_winrate_data(%s~%s)", self._AI_VERSION, start, end)
    return self._dp.ensure_data_loaded(end, progress_cb=progress_cb,
                                       min_fetch_start=start)

def check_winrate_coverage(self, start: str, end: str) -> dict:
    """返回数据就绪状态，供页面门禁用。"""
    res = self._dp.check_kline_coverage(start, end)
    log.info("check_winrate_coverage(%s~%s): ready=%s, missing=%d",
             start, end, res.get("ready"), len(res.get("missing_dates", [])))
    return res
```

---

## 6. 页面层改动（`dashboard/pages/06_买点胜率.py`）

### 6.1 布局

```
配置区（现有）：买点多选、判赢阈值、均线排列、市值、开始日期、结束日期、…
─────────────────────────────────
🆕 prep_start = 开始日期 − 600 日历日   （只读展示）
🆕 [📦 数据准备] 按钮
🆕 数据就绪状态条：✅ 数据就绪，覆盖 N 个交易日 / ⚠️ 缺口 K 天（列前几个日期）/ 校验失败请重试
─────────────────────────────────
[▶ 运行扫描]   disabled = not ready
```

### 6.2 数据准备按钮行为

按下后：
1. 解析 `prep_start = start_date - 600日历日`，`prep_end = end_date`（"now" 传给主路径解析）。
2. `st.progress` + `st.empty` 多阶段进度（沿用控制台 `00_控制台.py` 的 progress_cb 风格）。
3. 完成后 `st.session_state.wr_cov_cache = svc.check_winrate_coverage(prep_start, prep_end)`，并记 `wr_cov_range = (prep_start, prep_end)`。
4. 失败 → 状态条显示错误，运行扫描保持禁用。

### 6.3 覆盖率缓存与门禁

- `wr_cov_cache` 存 `st.session_state`，页面 rerun 直接读，**不重查库**（解决实时校验卡顿）。
- 刷新时机：仅「数据准备」完成后刷新。
- **范围失效**：若 `start_date`/`end_date` 改变导致当前 `(prep_start, prep_end)` ≠ `wr_cov_range` → 状态条变灰「数据范围已变更，请重新准备」，运行扫描禁用。
- 门禁：`ready = wr_cov_cache 存在 且 范围一致 且 wr_cov_cache["ready"] 为 True 且 missing_dates 为空`。

### 6.4 进度展示

页面内进度条（非后台线程）。沿用 `run_winrate_scan` 现有的 `st.progress` + `st.empty` 文案模式。`ensure_data_loaded` 的 `progress_cb` 已支持阶段回调。

---

## 7. 错误处理与边界

| 情况 | 处理 |
|---|---|
| 数据准备中途某 chunk 失败 | 沿用主路径（WARNING + 继续）；完成后覆盖率校验自然发现缺口、门禁不放行 |
| `check_kline_coverage` 查询异常 | 返回 `{ready: False, error}`；页面显示「校验失败，请重试」，运行扫描禁用 |
| `stock_basic` 为空（新机首次） | `ready=False, error="stock_basic 为空"`；数据准备主路径 A4 `_fetch_stock_basic_once` 会顺带拉取，重跑即可 |
| start_date 早于某票上市日 | 该票早期日期天然无数据；分母用 stock_basic 总数 + threshold=0.9 容忍（与 `_validate_coverage` 一致） |
| end_date=now 且今天非交易日/数据未发 | 主路径代理股票法已处理尾部判断 |
| 600 日历日前推跨年 | 纯日期运算，无特殊处理 |
| 改了日期范围但没重跑准备 | 状态条变灰提示重新准备，运行扫描禁用 |

---

## 8. 测试

- `data_provider.check_kline_coverage`：空范围、全覆盖、部分缺口、stock_basic 为空 四种情况。
- `cache_manager.count_daily_by_date_range`：范围边界、空结果。
- `ensure_data_loaded(min_fetch_start=...)`：传比 `_FETCH_DAYS` 更早的 floor → fetch_start 被压低；不传 → 行为不变（回归）。
- 页面门禁：范围变更后自动失效；数据就绪后运行扫描可点。
- 复用 `tests/winrate/` 既有风格（纯函数 + fixture）。

---

## 9. 项目约定

- **版本号**：feature → Y+1，`9.7.0` → `9.8.0`。
- **日期**：一律 YYYYMMDD，不用带横杠格式做查询。
- **配色**：红涨绿跌（本功能不涉及）。
- **日志**：INFO 流程、DEBUG 数据、WARNING 异常。
- **缓存读取**：按 trade_date 过滤，不用裸 `LIMIT N`（`count_daily_by_date_range` 用 WHERE BETWEEN + GROUP BY）。
- **复用**：复用 `ensure_data_loaded` 主路径与 `_validate_coverage` 口径，不重写拉取/校验逻辑。

---

## 10. 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/marketreview/data/data_provider.py` | `ensure_data_loaded` 加 `min_fetch_start`；新增 `check_kline_coverage` |
| `src/marketreview/data/cache_manager.py` | 新增 `count_daily_by_date_range` |
| `dashboard/services/dashboard_service.py` | 新增 `prepare_winrate_data` / `check_winrate_coverage`；`_AI_VERSION` 9.7.0→9.8.0 |
| `dashboard/pages/06_买点胜率.py` | 数据准备按钮 + 状态条 + 运行扫描门禁 |
| `tests/winrate/` 或 `tests/data/` | 新增覆盖率/数据准备相关测试 |
