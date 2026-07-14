#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""量价节点严格上浮2%：维度交叉 + MA共振（含价格接近度）。
用法: .venv/Scripts/python scripts/volnode_strict_dimensions.py
"""
from __future__ import annotations
import io, os, sys, sqlite3
import pandas as pd
import numpy as np

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

pd.set_option("display.width", 320)
pd.set_option("display.max_columns", 60)
pd.set_option("display.max_rows", 300)

DATA = ".winrate_data/20260714_171048"
DB = "data/marketreview.db"

# ── 加载数据 ──
volnode = pd.read_csv(f"{DATA}/量价节点严格上浮2%.csv", encoding="utf-8-sig")
volnode["sd"] = volnode["signal_date"].astype(str)
print(f"量价节点严格上浮2%: {len(volnode)} 笔, 基线胜率: {volnode.success.mean()*100:.1f}%\n")

# ── QFQ OHLC + MA ──
db = sqlite3.connect(DB)
needed_dates = set()
for _, r in volnode.iterrows():
    needed_dates.add((r.code, r.sd))
codes = list(set(p[0] for p in needed_dates))
min_date = min(p[1] for p in needed_dates)
max_date = max(p[1] for p in needed_dates)

# latest adj_factor
latest_af = {}
BATCH = 500
for i in range(0, len(codes), BATCH):
    batch = codes[i:i+BATCH]
    ph = ",".join(["?"]*len(batch))
    cur = db.execute(f"SELECT code, MAX(date) FROM tushare_cache WHERE code IN ({ph}) GROUP BY code", batch)
    for code, md in cur.fetchall():
        cur2 = db.execute("SELECT adj_factor FROM tushare_cache WHERE code=? AND date=?", [code, md])
        row2 = cur2.fetchone()
        if row2: latest_af[code] = row2[0]

# 取信号日 OHLC + 前60天kline（算MA）
# 简单方案：直接用行情数据算MA，不取全部kline
# 取信号日前后区间所有行情
ohlc = {}
for i in range(0, len(codes), BATCH):
    batch = codes[i:i+BATCH]
    ph = ",".join(["?"]*len(batch))
    # 取足够长的数据来算MA240
    cur = db.execute(
        f"SELECT code, date, open, high, low, close, adj_factor FROM tushare_cache WHERE code IN ({ph}) AND date >= ? AND date <= ? ORDER BY code, date",
        batch + [str(int(min_date) - 500), str(max_date)]
    )
    for row in cur:
        code, date, o, h, l, c, af = row
        laf = latest_af.get(code, 1) or 1
        saf = af or 1
        key = (code, int(date))
        if key not in ohlc:
            ohlc[key] = {}
        ohlc[key] = {'o': o*saf/laf, 'h': h*saf/laf, 'l': l*saf/laf, 'c': c*saf/laf}
db.close()

print("数据加载完成，计算 MA...")

# ── 为每只股票预计算 MA ──
MA_PERIODS = [20, 55, 60, 120, 144, 240]
ma_data = {}  # (code, date) -> {MA20: price, ...}
for code in codes:
    # 取该股票所有行情，按日期排序
    stock_data = []
    for (c, d), v in ohlc.items():
        if c == code:
            stock_data.append((d, v['c']))
    stock_data.sort()
    closes = np.array([x[1] for x in stock_data])
    dates_list = [x[0] for x in stock_data]

    for p in MA_PERIODS:
        if len(closes) < p:
            continue
        ma_vals = np.full(len(closes), np.nan)
        for i in range(p - 1, len(closes)):
            ma_vals[i] = closes[i-p+1:i+1].mean()
        for i, d in enumerate(dates_list):
            if not np.isnan(ma_vals[i]):
                if (code, d) not in ma_data:
                    ma_data[(code, d)] = {}
                ma_data[(code, d)][f"MA{p}"] = round(ma_vals[i], 2)

print(f"MA 计算完成，{len(ma_data)} 条记录\n")

# ── 构建分析行 ──
rows = []
for _, r in volnode.iterrows():
    sig_key = (r.code, int(r.sd))
    sig = ohlc.get(sig_key)
    ma = ma_data.get(sig_key, {})
    if sig is None:
        continue

    entry_price = r.entry_price
    cost = entry_price / 1.02
    close_qfq = sig['c']
    gap_to_entry = (close_qfq - entry_price) / entry_price * 100

    # MA 共振：信号日 close 是否接近各 MA 值
    # 同时检查 entry_price 是否接近各 MA（价格共振）
    ma_resonance = {}  # MA周期 -> close距MA的%
    ma_entry_resonance = {}  # MA周期 -> entry距MA的%
    for p in MA_PERIODS:
        ma_val = ma.get(f"MA{p}")
        if ma_val and ma_val > 0:
            ma_resonance[f"MA{p}"] = round((close_qfq - ma_val) / ma_val * 100, 2)
            ma_entry_resonance[f"MA{p}"] = round((entry_price - ma_val) / ma_val * 100, 2)

    # close 是否紧贴某条 MA（距离 ≤ 1.5%）
    close_near_ma = any(abs(v) <= 1.5 for v in ma_resonance.values())
    entry_near_ma = any(abs(v) <= 1.5 for v in ma_entry_resonance.values())

    # 最近的 MA 及距离
    nearest_ma_close = min(ma_resonance.items(), key=lambda x: abs(x[1])) if ma_resonance else (None, 999)
    nearest_ma_entry = min(ma_entry_resonance.items(), key=lambda x: abs(x[1])) if ma_entry_resonance else (None, 999)

    # close vs MA 方向：close 在MA上方/下方
    above_mas = sum(1 for v in ma_resonance.values() if v > 0)
    below_mas = sum(1 for v in ma_resonance.values() if v < 0)

    rows.append({
        "code": r.code, "sd": r.sd,
        "entry_price": entry_price, "cost": cost,
        "close_qfq": round(close_qfq, 2),
        "gap_to_entry": round(gap_to_entry, 2),
        "entry_type": "突破" if gap_to_entry < 0 else "拉回",
        "gap_bin": (
            "突破<-3%" if gap_to_entry < -3 else
            "突破-3~-1%" if gap_to_entry < -1 else
            "突破-1~0%" if gap_to_entry < 0 else
            "拉回0~2%" if gap_to_entry < 2 else
            "拉回2~5%" if gap_to_entry < 5 else
            "拉回5~10%" if gap_to_entry < 10 else
            "拉回>10%"
        ),
        "close_near_ma": close_near_ma,
        "entry_near_ma": entry_near_ma,
        "nearest_ma_close": nearest_ma_close[0],
        "nearest_ma_close_dist": nearest_ma_close[1],
        "nearest_ma_entry": nearest_ma_entry[0],
        "nearest_ma_entry_dist": nearest_ma_entry[1],
        "above_ma_count": above_mas,
        "below_ma_count": below_mas,
        "ma_resonance": ma_resonance,
        "ma_entry_resonance": ma_entry_resonance,
        "success": r.success, "pnl_pct": r.pnl_pct, "mfp_pct": r.mfp_pct,
        "exit_reason": r.exit_reason, "hold_days": r.hold_days,
        "long_ma_state": r.long_ma_state,
        "short_ma_state": r.short_ma_state,
        "cap_bucket": r.cap_bucket,
        "market_cap_yi": r.market_cap_yi,
        "industry_l1": r.industry_l1,
        "wave33_direction": r.wave33_direction,
    })

adf = pd.DataFrame(rows)
base_wr = adf.success.mean()
print(f"有效样本: {len(adf)}")

# ═══════════════════════════════════════════════════════════════
# Part 1: 维度单变量
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 100)
print("Part 1: 维度单变量效应")
print("=" * 100)

for dim, label in [("long_ma_state", "长均"), ("cap_bucket", "市值"),
                    ("wave33_direction", "3浪3"), ("industry_l1", "行业")]:
    print(f"\n── {label} ──")
    results = []
    for val in adf[dim].dropna().unique():
        sub = adf[adf[dim] == val]
        if len(sub) < 20:
            continue
        lift = (sub.success.mean() - base_wr) * 100
        results.append((val, len(sub), sub.success.mean(), lift,
                        sub.pnl_pct.median(), sub.mfp_pct.median(),
                        (sub.exit_reason == "大胜利").mean()))
    results.sort(key=lambda x: x[2], reverse=True)
    best, worst = results[0], results[-1]
    spread = (best[2] - worst[2]) * 100
    print(f"  最佳: {best[0]} WR={best[2]*100:.1f}% (n={best[1]}, lift={best[3]:+.1f}pp)")
    print(f"  最差: {worst[0]} WR={worst[2]*100:.1f}% (n={worst[1]}, lift={worst[3]:+.1f}pp)")
    print(f"  极差: {spread:.1f}pp")
    # top 5
    for val, n, wr, lift, pnl, mfp, big in results[:5]:
        print(f"    {str(val)[:20]:<20s} n={n:>5d} WR={wr*100:>5.1f}% lift={lift:>+5.1f}pp PnL={pnl:>+6.2f}% MFP={mfp:>+6.2f}% 大胜={big*100:>4.1f}%")

# ═══════════════════════════════════════════════════════════════
# Part 2: 长均 × 市值 × entry_type
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 2: 长均 × 市值 × 类型")
print("=" * 100)

for cap in ["小盘", "中盘", "大盘"]:
    print(f"\n── 市值={cap} ──")
    print(f"{'长均':<6s} {'类型':<6s} {'n':>5s} {'胜率':>6s} {'PnL':>8s} {'MFP':>8s} {'大胜%':>6s} {'止损%':>6s}")
    print("-" * 70)
    for lma in ["多头", "盘整"]:  # 严格版空头=0
        for et in ["突破", "拉回"]:
            sub = adf[(adf.cap_bucket == cap) & (adf.long_ma_state == lma) & (adf.entry_type == et)]
            if len(sub) < 10: continue
            stopped = sub[sub.exit_reason.isin(["盘中止损", "收盘止损"])]
            print(f"{lma:<6s} {et:<6s} {len(sub):>5d} {sub.success.mean()*100:>5.1f}% "
                  f"{sub.pnl_pct.median():>+7.2f}% {sub.mfp_pct.median():>+7.2f}% "
                  f"{(sub.exit_reason=='大胜利').mean()*100:>5.1f}% "
                  f"{len(stopped)/len(sub)*100:>5.1f}%")

# ═══════════════════════════════════════════════════════════════
# Part 3: 距离桶 × 长均
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 3: 距离桶 × 长均")
print("=" * 100)

print(f"\n{'距离桶':<14s} {'长均':<6s} {'n':>5s} {'胜率':>6s} {'PnL':>8s} {'MFP':>8s} {'大胜%':>6s} {'止损%':>6s}")
print("-" * 80)
for gb in ["突破<-3%", "突破-3~-1%", "突破-1~0%", "拉回0~2%", "拉回2~5%", "拉回5~10%", "拉回>10%"]:
    for lma in ["多头", "盘整"]:
        sub = adf[(adf.gap_bin == gb) & (adf.long_ma_state == lma)]
        if len(sub) < 10: continue
        stopped = sub[sub.exit_reason.isin(["盘中止损", "收盘止损"])]
        print(f"{gb:<14s} {lma:<6s} {len(sub):>5d} {sub.success.mean()*100:>5.1f}% "
              f"{sub.pnl_pct.median():>+7.2f}% {sub.mfp_pct.median():>+7.2f}% "
              f"{(sub.exit_reason=='大胜利').mean()*100:>5.1f}% "
              f"{len(stopped)/len(sub)*100:>5.1f}%")

# ═══════════════════════════════════════════════════════════════
# Part 4: MA 价格共振
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 4: MA 价格共振 — 信号日 close 接近 MA 值")
print("=" * 100)

for dist_threshold, label in [(1.0, "<=1%"), (1.5, "<=1.5%"), (2.0, "<=2%"), (3.0, "<=3%")]:
    near = adf[adf.nearest_ma_close_dist.abs() <= dist_threshold]
    far = adf[adf.nearest_ma_close_dist.abs() > dist_threshold]
    if len(near) < 20: continue
    print(f"\n── close距最近MA {label} ──")
    print(f"  共振: n={len(near)} ({len(near)/len(adf)*100:.1f}%) WR={near.success.mean()*100:.1f}% "
          f"PnL={near.pnl_pct.median():+.2f}% MFP={near.mfp_pct.median():+.2f}% "
          f"大胜={(near.exit_reason=='大胜利').mean()*100:.1f}%")
    print(f"  非共振: n={len(far)} WR={far.success.mean()*100:.1f}%")
    lift = (near.success.mean() - far.success.mean()) * 100
    print(f"  lift: {lift:+.1f}pp")

# 各MA单独共振
print(f"\n── 各MA单独共振（close距MA ≤ 1.5%）──")
print(f"{'MA':<10s} {'n':>5s} {'占比':>6s} {'胜率':>6s} {'lift':>8s} {'PnL':>8s} {'止损%':>6s}")
print("-" * 65)
for p in MA_PERIODS:
    ma_key = f"MA{p}"
    dists = []
    for _, r in adf.iterrows():
        d = r.ma_resonance.get(ma_key)
        if d is not None:
            dists.append(abs(d))

    near = adf[[abs(r.ma_resonance.get(ma_key, 999)) <= 1.5 for _, r in adf.iterrows()]]
    if len(near) < 10: continue
    lift = (near.success.mean() - adf.success.mean()) * 100
    stopped = near[near.exit_reason.isin(["盘中止损", "收盘止损"])]
    print(f"{ma_key:<10s} {len(near):>5d} {len(near)/len(adf)*100:>5.1f}% {near.success.mean()*100:>5.1f}% "
          f"{lift:>+7.1f}pp {near.pnl_pct.median():>+7.2f}% "
          f"{len(stopped)/len(near)*100:>5.1f}%")

# close在MA上方 vs 下方
print(f"\n── close在MA上方/下方（距离 ≤ 1.5%）──")
for ma_key in [f"MA{p}" for p in MA_PERIODS]:
    above = adf[[r.ma_resonance.get(ma_key, 0) >= 0 and abs(r.ma_resonance.get(ma_key, 999)) <= 1.5 for _, r in adf.iterrows()]]
    below = adf[[r.ma_resonance.get(ma_key, 0) < 0 and abs(r.ma_resonance.get(ma_key, 999)) <= 1.5 for _, r in adf.iterrows()]]
    if len(above) >= 10 or len(below) >= 10:
        a_wr = above.success.mean()*100 if len(above) >= 10 else 0
        b_wr = below.success.mean()*100 if len(below) >= 10 else 0
        print(f"  {ma_key}: 上方 n={len(above)} WR={a_wr:.1f}% | 下方 n={len(below)} WR={b_wr:.1f}%")

# ═══════════════════════════════════════════════════════════════
# Part 5: entry价 接近 MA（价格共振 — 用户强调的重点）
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 5: entry价格接近 MA（买入价共振）")
print("=" * 100)

for dist_threshold in [1.0, 1.5, 2.0, 3.0]:
    near = adf[adf.nearest_ma_entry_dist.abs() <= dist_threshold]
    far = adf[adf.nearest_ma_entry_dist.abs() > dist_threshold]
    if len(near) < 20: continue
    lift = (near.success.mean() - far.success.mean()) * 100
    print(f"\n  entry距最近MA ≤ {dist_threshold}%: n={len(near)} ({len(near)/len(adf)*100:.1f}%) "
          f"WR={near.success.mean()*100:.1f}% lift={lift:+.1f}pp "
          f"PnL={near.pnl_pct.median():+.2f}% 大胜={(near.exit_reason=='大胜利').mean()*100:.1f}%")

# 各MA单独 entry共振
print(f"\n── 各MA单独 entry共振（entry距MA ≤ 1.5%）──")
for p in MA_PERIODS:
    ma_key = f"MA{p}"
    near = adf[[abs(r.ma_entry_resonance.get(ma_key, 999)) <= 1.5 for _, r in adf.iterrows()]]
    if len(near) < 10: continue
    lift = (near.success.mean() - adf.success.mean()) * 100
    stopped = near[near.exit_reason.isin(["盘中止损", "收盘止损"])]
    print(f"  {ma_key:<10s} n={len(near):>5d} ({len(near)/len(adf)*100:>4.1f}%) "
          f"WR={near.success.mean()*100:>5.1f}% lift={lift:>+6.1f}pp "
          f"PnL={near.pnl_pct.median():>+6.2f}% 止损={len(stopped)/len(near)*100:>4.1f}%")

# ═══════════════════════════════════════════════════════════════
# Part 6: 综合多维度最佳/最差组合 (n≥30)
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 6: 综合最佳/最差多维度组合 (n≥30)")
print("=" * 100)

combos = []
for (lma, cap, gb, wv), grp in adf.groupby(["long_ma_state", "cap_bucket", "gap_bin", "wave33_direction"]):
    n = len(grp)
    if n < 30: continue
    wr = grp.success.mean()
    pnl = grp.pnl_pct.median()
    big = (grp.exit_reason == "大胜利").mean()
    stopped = grp[grp.exit_reason.isin(["盘中止损", "收盘止损"])]
    stop_rate = len(stopped) / n
    mfp = grp.mfp_pct.median()
    combos.append({
        "长均": lma, "市值": cap, "距离": gb, "3浪3": wv,
        "n": n, "WR": wr, "PnL": pnl, "大胜": big, "止损率": stop_rate, "MFP": mfp,
    })

combos_df = pd.DataFrame(combos)

print(f"\nTop 15 组合 (按胜率):")
print(f"{'长均':<6s} {'市值':<6s} {'距离':<14s} {'3浪3':<6s} {'n':>5s} {'胜率':>6s} {'PnL':>8s} {'MFP':>8s} {'大胜%':>6s} {'止损%':>6s}")
print("-" * 95)
for _, c in combos_df.nlargest(15, "WR").iterrows():
    print(f"{c['长均']:<6s} {c['市值']:<6s} {c['距离']:<14s} {c['3浪3']:<6s} "
          f"{int(c['n']):>5d} {c['WR']*100:>5.1f}% {c['PnL']:>+7.2f}% {c['MFP']:>+7.2f}% "
          f"{c['大胜']*100:>5.1f}% {c['止损率']*100:>5.1f}%")

print(f"\nBottom 10 组合 (按胜率):")
for _, c in combos_df.nsmallest(10, "WR").iterrows():
    print(f"{c['长均']:<6s} {c['市值']:<6s} {c['距离']:<14s} {c['3浪3']:<6s} "
          f"{int(c['n']):>5d} {c['WR']*100:>5.1f}% {c['PnL']:>+7.2f}% {c['MFP']:>+7.2f}% "
          f"{c['大胜']*100:>5.1f}% {c['止损率']*100:>5.1f}%")

# ═══════════════════════════════════════════════════════════════
# Part 7: 行业 × 长均 × 距离
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 7: 行业 × 长均 × 距离（Top 行业, n≥20）")
print("=" * 100)

top_ind = adf.industry_l1.value_counts().head(12).index
for ind in top_ind:
    ind_df = adf[adf.industry_l1 == ind]
    base_ind_wr = ind_df.success.mean()
    print(f"\n── {ind} (n={len(ind_df)}, WR={base_ind_wr*100:.1f}%) ──")
    for lma in ["多头", "盘整"]:
        for gb in ["拉回0~2%", "拉回2~5%", "拉回5~10%", "拉回>10%"]:
            sub = ind_df[(ind_df.long_ma_state == lma) & (ind_df.gap_bin == gb)]
            if len(sub) < 20: continue
            lift = (sub.success.mean() - base_ind_wr) * 100
            print(f"  {lma} {gb:<14s} n={len(sub):>4d} WR={sub.success.mean()*100:>5.1f}% lift={lift:>+5.1f}pp")

# ═══════════════════════════════════════════════════════════════
# Part 8: 结论摘要
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 8: 量价节点严格上浮2% 维度效应排序")
print("=" * 100)

def lift_spread(dim):
    results = []
    for val in adf[dim].dropna().unique():
        sub = adf[adf[dim] == val]
        if len(sub) < 20: continue
        results.append((val, len(sub), sub.success.mean()))
    if len(results) < 2: return 0
    results.sort(key=lambda x: x[2], reverse=True)
    best, worst = results[0], results[-1]
    spread = (best[2] - worst[2]) * 100
    print(f"  {dim}: 最佳={best[0]}({best[2]*100:.1f}%,n={best[1]}) 最差={worst[0]}({worst[2]*100:.1f}%,n={worst[1]}) 极差={spread:.1f}pp")
    return spread

print("\n单维度极差（越大说明维度越重要）:")
for dim in ["long_ma_state", "gap_bin", "industry_l1", "cap_bucket", "wave33_direction"]:
    lift_spread(dim)

print("\n完成。")
