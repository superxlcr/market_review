# 买点胜率 — 3浪3 市场趋势维度 设计文档

日期：2026-07-13
状态：待实现
版本：v9.8.0 → **v9.9.0**（feature，Y+1）
关联：
- [2026-07-13-winrate-data-prep-design.md](./2026-07-13-winrate-data-prep-design.md)（数据准备，本功能依赖其范围/门禁框架）
- [2026-07-11-buypoint-winrate-design.md](./2026-07-11-buypoint-winrate-design.md)（胜率引擎本体）
- `src/marketreview/tools/wave33.py`（3浪3 选股 + 趋势状态）
- `ARCHITECTURE.md §7.3`（wave33 两窗口缓存）

---

## 1. 背景与目标

买点胜率当前每笔交易带短/长期均线状态、市值、行业等上下文标签。新增一个**市场层**维度：买入信号日 T，全市场 3浪3 选股数的趋势状态（确认上升/暂时上升/下降盘整等）。用途：

- 作为 CSV 标签，事后切片研究"在不同 3浪3 市场状态下买点的胜率差异"。
- 为未来按此维度过滤铺路（类似市值过滤）。

### 目标
- 数据准备阶段预算 `[prep_start, prep_end]` 全部交易日的 wave33 选股数（写 wave33_cache，幂等）。
- 扫描时按 signal_date 查 21 天 count 序列算趋势状态，回填 TradeResult。
- CSV 导出 3 列：`wave33_direction` / `wave33_streak` / `wave33_label`。
- 「运行扫描」门禁增加 wave33 就绪校验：扫描窗每天都有 wave33 数据。

### 非目标
- **不**做按 wave33 维度过滤的 UI（YAGNI；CSV 已有 direction 字段，未来加过滤只是配置+filters.py 的事）。
- **不**改 wave33 选股逻辑或 `compute_trend` 算法。
- **不**算个股层 3浪3（本次只做市场层趋势状态）。

---

## 2. 3浪3 状态体系（既有，不改）

`compute_trend(counts)` 输入一段 count 序列（most-recent-first），返回 `{direction, streak, label}`：

| direction | streak | label 示例 |
|---|---|---|
| up | ≥5 | `确认上升，连续上升 N 天` |
| up | 3-4 | `暂时上升，连续上升 N 天` |
| up | 2 | `连续上涨2天` |
| up | 1 | `上涨第1天` |
| down | ≥5 | `确认下降，连续下降 N 天` |
| down | 3-4 | `暂时下降，连续下降 N 天` |
| down | 2 | `连续下跌2天` |
| down | 1 | `下跌第1天` |
| up/down（滞后未翻转） | — | `上升趋势，盘整中` / `下降趋势，盘整中` |
| flat | 0 | `维持，盘整中` |

判断逻辑：原始方向 + 连续天数 + 滞后翻转（3 天同向才翻）。判断 T 日状态需 T 及之前若干天序列——`raw_streak>=5` 要 5 天，滞后翻转窗口 +3 天，取 **21 天**序列足够稳定。

---

## 3. 数据流与架构

```
数据准备（点「数据准备」）:
  ① ensure_data_loaded(min_fetch_start=prep_start)        ← K线+复权（已有）
  ② scan_wave33([prep_start..prep_end 所有交易日], dp)     ← 🆕 预算每日 count，写 wave33_cache（幂等）
  ③ check_kline_coverage(...)                             ← 已有
  ④ check_wave33_coverage(start_date, end_date)           ← 🆕 门禁

运行扫描:
  scan_stock → simulate_trade → TradeResult
    _tag 回填：get_wave33_range(21, signal_date) → compute_trend → direction/streak/label

CSV 导出: 加 wave33_direction / wave33_streak / wave33_label 3 列
```

**关键复用**：
- `scan_wave33(dates, dp, progress_cb)` — 现成，幂等（`has_wave33_date` 跳过），progress_cb 4 phase
- `compute_trend(counts)` — 现成，取序列算状态
- `get_wave33_range(limit, end_date)` — 现成，取 end_date 之前 N 天（DESC）

**预算范围**：`[prep_start, prep_end]`（与 K 线一致）。prep_start 已前推 600 日历日，远超 21 天预热。扫描窗 `[start_date, end_date]` ⊂ 预算范围，signal_date 一定有数据（门禁保证）。

---

## 4. 数据准备阶段（`prepare_winrate_data`）

```python
def prepare_winrate_data(self, start, end, progress_cb=None):
    log.info("[AI v%s] prepare_winrate_data(%s~%s)", self._AI_VERSION, start, end)
    # 阶段1: K线 + 复权因子（已有）
    res = self._dp.ensure_data_loaded(end, progress_cb=progress_cb, min_fetch_start=start)
    # 阶段2: wave33 预算（新增）—— 幂等，已算日期跳过
    log.info("prepare_winrate_data: 阶段2 预算 wave33 [%s~%s]", start, end)
    from marketreview.tools.wave33 import scan_wave33
    trade_dates = self._dp.cache.get_daily_dates_in_range(start, end)
    if trade_dates:
        scan_wave33(trade_dates, self._dp, progress_cb=progress_cb)
        log.info("prepare_winrate_data: wave33 预算完成 %d 天", len(trade_dates))
    else:
        log.warning("prepare_winrate_data: [%s~%s] 无交易日，跳过 wave33", start, end)
    return res
```

**进度条**：`scan_wave33` 的 progress_cb 签名 `(phase, cur, total, date_str)`，与页面 `_prep_cb`（按 `args[1]/args[2]` 取 cur/total，`args[3]` 取 label）兼容。阶段1 显示 `[chunk]`/`[validate]`，阶段2 显示 `[wave33_load]`/`[wave33_date]`，无需改 `_prep_cb`。

---

## 5. wave33 就绪门禁

### 5.1 `DataProvider.check_wave33_coverage`

```python
def check_wave33_coverage(self, start: str, end: str) -> dict:
    """检查 [start,end] 每个交易日是否都有 wave33 数据。
    返回 {ready, total_dates, missing_dates, error}
    - ready = (missing_dates 为空)
    - missing_dates = 有 K线但无 wave33 的交易日（升序，前50）
    - 分母 = K线覆盖的交易日数（避开非交易日）
    """
```

实现：`get_daily_dates_in_range(start, end)` 取有 K线的交易日 → 逐个 `has_wave33_date` → 收集缺的。

### 5.2 `DashboardService.check_winrate_coverage` 合并两门禁

```python
def check_winrate_coverage(self, start, end) -> dict:
    kline = self._dp.check_kline_coverage(start, end)
    wave33 = self._dp.check_wave33_coverage(start, end)
    ready = bool(kline.get("ready") and wave33.get("ready"))
    log.info("check_winrate_coverage: kline_ready=%s wave33_ready=%s → ready=%s",
             kline.get("ready"), wave33.get("ready"), ready)
    return {
        "ready": ready,
        "kline": kline, "wave33": wave33,
    }
```

返回结构由扁平改嵌套（`kline`/`wave33` 子 dict）。页面状态条据此细化。

### 5.3 页面状态条

- K线缺口 → `⚠️ K线缺口 N 天（…）`
- wave33 缺口 → `⚠️ 3浪3 缺算 N 天（…）`
- 两者都缺 → 两行都显示
- 全就绪 → `✅ 数据就绪：K线覆盖 N 天，3浪3 全覆盖`
- 门禁：`_data_ready = kline_ready and wave33_ready`

---

## 6. 扫描阶段回填 wave33 状态

### 6.1 `TradeResult` 加 3 字段（trade_sim.py）

```python
wave33_direction: str = ""   # "up" | "down" | "flat"
wave33_streak: int = 0
wave33_label: str = ""       # "确认上升，连续上升 5 天" 等
```

### 6.2 `scan_engine` 改造

`scan_stock` 加 `cache` 参数（显式传依赖，不引入模块级状态）：

```python
def scan_stock(code, name, rows_desc, cfg, industry_l1, industry_l2,
               list_date, mv_series, band_lookback=300, cache=None):
    ...
    _tag(tr, df_upto, mv_yi, industry_l1, industry_l2, cache)
```

`_tag` 回填 wave33：

```python
def _tag(tr, df_upto, mv_yi, l1, l2, cache):
    tr.short_ma_state = ma_group_state(df_upto, [5, 10, 20])
    tr.long_ma_state = ma_group_state(df_upto, [60, 120, 240])
    tr.market_cap_yi = round(mv_yi, 1)
    tr.cap_bucket = cap_bucket(mv_yi) if mv_yi > 0 else ""
    tr.industry_l1 = l1
    tr.industry_l2 = l2
    w33 = _wave33_state(cache, tr.signal_date)
    tr.wave33_direction = w33["direction"]
    tr.wave33_streak = w33["streak"]
    tr.wave33_label = w33["label"]


def _wave33_state(cache, signal_date: str) -> dict:
    """取 signal_date 及之前 21 天 wave33 count 序列，算趋势状态。
    缺数据 → 空状态（门禁已保证就绪；此处防御性返回空）。"""
    from marketreview.tools.wave33 import compute_trend
    if cache is None:
        return {"direction": "", "streak": 0, "label": ""}
    rows = cache.get_wave33_range(limit=21, end_date=signal_date)  # DESC
    if len(rows) < 2:
        log.warning("_wave33_state: signal_date=%s wave33 序列不足(%d)，留空",
                    signal_date, len(rows))
        return {"direction": "", "streak": 0, "label": ""}
    counts = [r["count"] for r in rows]   # most-recent-first（compute_trend 要求）
    return compute_trend(counts)
```

`run_scan` 调 `scan_stock` 时传 `dp.cache`。

**性能**：每笔交易一次 `get_wave33_range(21)`（一条 SQL）。几万笔 = 几万次小查询，可接受。如嫌慢后续可加 per-date 缓存，先简单做。

---

## 7. CSV 导出

`reporter._EXPORT_FIELDS` 加 3 列（industry_l2 后）：

```python
_EXPORT_FIELDS = [
    "buy_point", "reason", "code", "name", "signal_date", "entry_date", "entry_price",
    "exit_date", "exit_price", "exit_reason", "mfp_pct", "hold_days", "pnl_pct",
    "success", "short_ma_state", "long_ma_state", "market_cap_yi", "cap_bucket",
    "industry_l1", "industry_l2",
    "wave33_direction", "wave33_streak", "wave33_label",
]
```

`export_csv` / `save_run` / `export_rows` 由 `_EXPORT_FIELDS` 驱动，`asdict(t)` 已含新字段，无需改逻辑。

---

## 8. 日志埋点

| 位置 | 级别 | 内容 |
|---|---|---|
| `prepare_winrate_data` 阶段2 入口 | INFO | `阶段2 预算 wave33 [start~end]` |
| `prepare_winrate_data` 阶段2 完成 | INFO | `wave33 预算完成 N 天` |
| 无交易日跳过 | WARNING | 原因 |
| `check_wave33_coverage` 结果 | INFO | `total=N missing=K` |
| `check_winrate_coverage` 合并 | INFO | `kline_ready/wave33_ready/ready` |
| `_wave33_state` 序列不足 | WARNING | `signal_date 序列不足` |
| `scan_wave33` 内部 | INFO | 既有（Phase1 done / 每日 count） |

---

## 9. 测试

- `tests/winrate/test_wave33_state.py`：`_wave33_state` 给定 count 序列 → 验证 direction/streak/label（确认上升/暂时上升/盘整/缺数据/无 cache 五种）
- `tests/winrate/test_data_prep.py` 加：`check_wave33_coverage` 全就绪/有缺口两种
- `tests/winrate/test_service_winrate.py`：`check_winrate_coverage` 返回嵌套结构（kline+wave33）
- `tests/winrate/test_trade_sim.py`：TradeResult 新字段默认值

---

## 10. 项目约定

- 版本 9.8.0 → 9.9.0（feature，Y+1）
- 日期 YYYYMMDD
- 日志：INFO 流程、DEBUG 数据、WARNING 异常
- 缓存读取按 trade_date 过滤（`get_wave33_range` 用 `WHERE trade_date <= ?`）
- 复用 `scan_wave33` / `compute_trend` / `get_wave33_range`，不重写

---

## 11. 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/marketreview/winrate/trade_sim.py` | `TradeResult` 加 3 字段 |
| `src/marketreview/winrate/scan_engine.py` | `scan_stock` 加 cache 参数；`_tag` 回填 wave33；新增 `_wave33_state`；`run_scan` 传 cache |
| `src/marketreview/winrate/reporter.py` | `_EXPORT_FIELDS` 加 3 列 |
| `src/marketreview/data/data_provider.py` | 新增 `check_wave33_coverage` |
| `dashboard/services/dashboard_service.py` | `prepare_winrate_data` 加 scan_wave33 阶段；`check_winrate_coverage` 合并；版本 9.9.0 |
| `dashboard/pages/06_买点胜率.py` | 状态条细化（kline/wave33 分别显示） |
| `tests/winrate/` | 新增 wave33_state / coverage / service 结构测试 |
