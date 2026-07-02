# 买点系统优化 — Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** BuyPoint 止损扩展、板块涨幅过滤、MA跌破episode统计、渲染改动。

**Architecture:** 4 文件改动：buy_points.py（核心逻辑）、band_section.py（渲染）、03_个股追踪.py（传参）、buy_point_config.txt（配置）。

**Tech Stack:** Python, numpy, dataclasses, Streamlit

## Global Constraints

- 止损规则严格按 spec 三实现
- 涨幅过滤：主板 20%, 创业/科创 40%
- MA episode: low 开始, close 结束, 逐日重算 MA
- trend direction 来自 wave33.compute_trend

---

### Task 1: BuyPoint 扩展 + 板块判断 + 配置

**Files:** `src/marketreview/tools/buy_points.py`, `config/buy_point_config.txt`

- [ ] 1.1 BuyPoint 新增 6 个止损字段
- [ ] 1.2 新增 `_get_board_threshold(ts_code) -> float` 
- [ ] 1.3 配置新增 ATR盘中止损上限=10, 均线盘中止损=5

### Task 2: 止损计算

**Files:** `src/marketreview/tools/buy_points.py`

- [ ] 2.1 新增 `_calc_intraday_stop(price, atr, bp_type) -> (float, float, str)`
- [ ] 2.2 新增 `_calc_close_stop(price, ma_val, bp_type, trend) -> (float, float, str)`
- [ ] 2.3 在 find_all_buy_points 中对每个 BuyPoint 计算止损

### Task 3: 涨幅过滤

**Files:** `src/marketreview/tools/buy_points.py`

- [ ] 3.1 find_all_buy_points 返回前过滤 distance_pct > threshold

### Task 4: MA 跌破 Episode 统计

**Files:** `src/marketreview/tools/buy_points.py`

- [ ] 4.1 新增 `find_ma_episodes(df, band, ma_periods) -> dict`
- [ ] 4.2 返回格式: `{60: [{start, end, days, max_penetration_pct}, ...], ...}`

### Task 5: find_all_buy_points 签名更新

**Files:** `src/marketreview/tools/buy_points.py`

- [ ] 5.1 新增参数: `ts_code`, `atr`, `trend_direction`

### Task 6: 渲染改动

**Files:** `dashboard/rendering/band_section.py`

- [ ] 6.1 render_buy_point_table 新增"盘中止损""收盘止损"列
- [ ] 6.2 标题旁小字说明
- [ ] 6.3 新增 render_ma_episodes 函数

### Task 7: 调用方更新

**Files:** `dashboard/pages/03_个股追踪.py`

- [ ] 7.1 传入 ts_code, atr, trend_direction 给 find_all_buy_points

### Task 8: Bump version + Commit
