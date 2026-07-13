---
name: qfq-vs-tongdaxin
description: 我们前复权(乘法adj_factor)与通达信前复权(减现金分红)会差一点点，不是bug；raw已核对faithful
metadata: 
  node_type: memory
  type: reference
  originSessionId: d3d3f1ba-7940-40e1-ae7e-2b3f04781e74
---

# 前复权口径差异：我们 vs 通达信

**症状**：dashboard 某历史K线价格和通达信前复权对不上一点点（例：002709.SZ 天赐材料 20260309 收盘 我们 43.12 vs 通达信 43.06，差 0.06）。

**结论：不是 bug，不用改。**

## 三个数分清楚
- **raw / 不复权**（DB `tushare_cache` 只存不展示）= 真实成交价，如 43.36。已用 tushare `api.daily` 核对，我们存的 raw 与 tushare **完全一致**。
- **我们展示的前复权**（乘法）= `raw × adj_factor(T) / adj_factor(锚点)`，锚点=窗口内最大adj（=最新日）。见 `raw_to_qfq` [data_provider.py]，展示链路 `get_index_data` 必调。
- **通达信前复权**（减法）= 除权前每根K线直接减掉后续累计现金分红。

## 差异根因
现金分红两种复权算法不同：
- **乘法（我们/tushare adj_factor，量化标准）**：按比例缩放，**保证历史每日涨跌幅完全不变** → 对 MA/KD/波段(P+V)/2/买点这些比值类分析更正确。
- **减法（通达信默认对纯现金分红）**：一刀切减固定金额，会轻微扭曲除权前涨跌幅。
- 例：002709.SZ 20260429 除权，现金分红 0.30元/股。除权前 43.36：乘法减 0.24→43.12，减法减 0.30→43.06。差 0.06 全来自此。**除权日当天两法相等；除权日之后完全一致；最新价永远一致**。

## 易混点
锚点是"窗口内最新"，所以**若分析截止日选在某次除权之前**，该窗口内无分红，qfq==raw（如 20260320 截止看 20260309 会显示 43.36）。这是前复权锚定窗口末端的正常行为，不是显示了不复权。

## 想验证 raw
把通达信切「不复权」，应显示 = 我们DB raw（43.36），即可确认原始数据无误。

[[data-layer-architecture]] [[database-schema-reference]]
