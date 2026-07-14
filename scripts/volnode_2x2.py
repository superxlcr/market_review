#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""量价节点 2×2 对比：严格×上浮（strict × premium）。
用法: .venv/Scripts/python scripts/volnode_2x2.py
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

# ── 加载 4 个变体 ──
variants = {
    "量价节点":       {"strict": False, "prem": 1.04},
    "量价节点上浮2%":   {"strict": False, "prem": 1.02},
    "量价节点严格":     {"strict": True,  "prem": 1.04},
    "量价节点严格上浮2%": {"strict": True,  "prem": 1.02},
}

dfs = {}
for name in variants:
    path = f"{DATA}/{name}.csv"
    if os.path.exists(path):
        df = pd.read_csv(path, encoding="utf-8-sig")
        df["sd_key"] = df["code"] + "_" + df["signal_date"].astype(str)
        dfs[name] = df
        print(f"{name}: {len(df)} 笔")

# ── OHLC QFQ（只用信号日close，判断距离）──
db = sqlite3.connect(DB)
all_keys = set()
for name, df in dfs.items():
    for _, r in df.iterrows():
        all_keys.add((r.code, r.signal_date))

codes = list(set(p[0] for p in all_keys))
min_date = min(p[1] for p in all_keys)
max_date = max(p[1] for p in all_keys)

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

sig_close = {}
for i in range(0, len(codes), BATCH):
    batch = codes[i:i+BATCH]
    ph = ",".join(["?"]*len(batch))
    cur = db.execute(f"SELECT code, date, close, adj_factor FROM tushare_cache WHERE code IN ({ph}) AND date >= ? AND date <= ?", batch + [min_date, max_date])
    for row in cur:
        code, date, c, af = row
        laf = latest_af.get(code, 1) or 1
        saf = af or 1
        sig_close[(code, str(date))] = c * saf / laf
db.close()
print()

# ═══════════════════════════════════════════════════════════════
# Part 1: 2×2 总览
# ═══════════════════════════════════════════════════════════════
print("=" * 100)
print("Part 1: 2×2 总览")
print("=" * 100)

print(f"\n{'变体':<20s} {'n':>6s} {'胜率':>6s} {'PnL':>8s} {'MFP':>8s} {'大胜%':>6s} {'小胜%':>6s} {'止损%':>7s} {'盘中%':>7s} {'收盘%':>7s} {'时间%':>6s} {'持仓':>5s}")
print("-" * 100)

for name, meta in variants.items():
    df = dfs.get(name)
    if df is None: continue
    stopped = df[df.exit_reason.isin(["盘中止损", "收盘止损"])]
    intra = (df.exit_reason == "盘中止损").mean() * 100
    close_stop = (df.exit_reason == "收盘止损").mean() * 100
    time = (df.exit_reason == "时间止损").mean() * 100
    big = (df.exit_reason == "大胜利").mean() * 100
    small = (df.exit_reason == "小胜利").mean() * 100
    print(f"{name:<20s} {len(df):>6d} {df.success.mean()*100:>5.1f}% "
          f"{df.pnl_pct.median():>+7.2f}% {df.mfp_pct.median():>+7.2f}% "
          f"{big:>5.1f}% {small:>5.1f}% {len(stopped)/len(df)*100:>6.1f}% "
          f"{intra:>6.1f}% {close_stop:>6.1f}% {time:>5.1f}% "
          f"{df.hold_days.median():>4.0f}天")

# ═══════════════════════════════════════════════════════════════
# Part 2: 严格效应（控制 premium）
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 2: 严格效应 — strict vs non-strict（同 premium）")
print("=" * 100)

for prem_label, prem_val in [("4%", 1.04), ("2%", 1.02)]:
    strict_name = f"量价节点严格{'上浮2%' if abs(prem_val-1.02)<1e-9 else ''}"
    loose_name = f"量价节点{'上浮2%' if abs(prem_val-1.02)<1e-9 else ''}"
    s_df = dfs.get(strict_name)
    l_df = dfs.get(loose_name)
    if s_df is None or l_df is None: continue

    print(f"\n── premium={prem_label} ──")
    print(f"  严格:   n={len(s_df)} WR={s_df.success.mean()*100:.1f}% PnL={s_df.pnl_pct.median():+.2f}% "
          f"大胜={(s_df.exit_reason=='大胜利').mean()*100:.1f}% MFP={s_df.mfp_pct.median():+.2f}% "
          f"盘中止损={(s_df.exit_reason=='盘中止损').mean()*100:.1f}%")
    print(f"  不严格: n={len(l_df)} WR={l_df.success.mean()*100:.1f}% PnL={l_df.pnl_pct.median():+.2f}% "
          f"大胜={(l_df.exit_reason=='大胜利').mean()*100:.1f}% MFP={l_df.mfp_pct.median():+.2f}% "
          f"盘中止损={(l_df.exit_reason=='盘中止损').mean()*100:.1f}%")
    wr_diff = (s_df.success.mean() - l_df.success.mean()) * 100
    pnl_diff = s_df.pnl_pct.median() - l_df.pnl_pct.median()
    # 严格过滤掉了多少
    overlap = len(set(s_df.sd_key) & set(l_df.sd_key))
    print(f"  严格过滤: {len(l_df) - overlap} 笔被砍 ({ (1-overlap/len(l_df))*100:.1f}%)")
    print(f"  ΔWR={wr_diff:+.1f}pp  ΔPnL={pnl_diff:+.2f}%")

# ═══════════════════════════════════════════════════════════════
# Part 3: Premium 效应（控制 strict）
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 3: Premium 效应 — 4% vs 2%（同 strict）")
print("=" * 100)

for strict_label, strict_val in [("不严格", False), ("严格", True)]:
    p4_name = "量价节点" if not strict_val else "量价节点严格"
    p2_name = "量价节点上浮2%" if not strict_val else "量价节点严格上浮2%"
    p4_df = dfs.get(p4_name)
    p2_df = dfs.get(p2_name)
    if p4_df is None or p2_df is None: continue

    print(f"\n── strict={strict_label} ──")
    # 止损距离
    stop_dist_4 = (1 - 1/1.04) * 100  # ~3.85%
    stop_dist_2 = (1 - 1/1.02) * 100  # ~1.96%
    print(f"  4% (止损距≈{stop_dist_4:.1f}%): n={len(p4_df)} WR={p4_df.success.mean()*100:.1f}% "
          f"PnL={p4_df.pnl_pct.median():+.2f}% 大胜={(p4_df.exit_reason=='大胜利').mean()*100:.1f}% "
          f"盘中止损={(p4_df.exit_reason=='盘中止损').mean()*100:.1f}% 持仓={p4_df.hold_days.median():.0f}天")
    print(f"  2% (止损距≈{stop_dist_2:.1f}%): n={len(p2_df)} WR={p2_df.success.mean()*100:.1f}% "
          f"PnL={p2_df.pnl_pct.median():+.2f}% 大胜={(p2_df.exit_reason=='大胜利').mean()*100:.1f}% "
          f"盘中止损={(p2_df.exit_reason=='盘中止损').mean()*100:.1f}% 持仓={p2_df.hold_days.median():.0f}天")
    wr_diff = (p4_df.success.mean() - p2_df.success.mean()) * 100
    pnl_diff = p4_df.pnl_pct.median() - p2_df.pnl_pct.median()
    print(f"  ΔWR={wr_diff:+.1f}pp  ΔPnL={pnl_diff:+.2f}%")

# ═══════════════════════════════════════════════════════════════
# Part 4: PnL 分布对比
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 4: PnL 分布（percentile）")
print("=" * 100)

print(f"\n{'变体':<20s} {'P10':>7s} {'P25':>7s} {'P50':>7s} {'P75':>7s} {'P90':>7s} {'均值':>7s} {'止损PnL':>8s}")
print("-" * 80)
for name in ["量价节点严格", "量价节点", "量价节点严格上浮2%", "量价节点上浮2%"]:
    df = dfs.get(name)
    if df is None: continue
    stopped = df[df.exit_reason.isin(["盘中止损", "收盘止损"])]
    stop_pnl = stopped.pnl_pct.median() if len(stopped) > 0 else 0
    print(f"{name:<20s} {df.pnl_pct.quantile(0.1):>+6.2f}% {df.pnl_pct.quantile(0.25):>+6.2f}% "
          f"{df.pnl_pct.quantile(0.5):>+6.2f}% {df.pnl_pct.quantile(0.75):>+6.2f}% "
          f"{df.pnl_pct.quantile(0.9):>+6.2f}% {df.pnl_pct.mean():>+6.2f}% {stop_pnl:>+7.2f}%")

# ═══════════════════════════════════════════════════════════════
# Part 5: 维度效应
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 5: 维度效应（4变体 × 关键维度）")
print("=" * 100)

dims = ["long_ma_state", "cap_bucket", "wave33_direction", "industry_l1"]
dim_labels = {"long_ma_state": "长均", "cap_bucket": "市值", "wave33_direction": "3浪3", "industry_l1": "行业"}

for dim in dims:
    print(f"\n── {dim_labels[dim]} ──")
    # top values
    all_vals = set()
    for df in dfs.values():
        all_vals |= set(df[dim].dropna().unique())

    # 只看主要取值
    counts = {}
    for v in all_vals:
        counts[v] = sum(len(df[df[dim]==v]) for df in dfs.values())
    top_vals = sorted(counts, key=counts.get, reverse=True)[:10]

    header = f"{'取值':<12s}"
    for name in ["量价节点严格", "量价节点", "量价节点严格上浮2%", "量价节点上浮2%"]:
        header += f" {name[:8]:>10s}"
    print(header)
    print("-" * (12 + 10*4))

    for v in top_vals:
        row = f"{str(v)[:12]:<12s}"
        for name in ["量价节点严格", "量价节点", "量价节点严格上浮2%", "量价节点上浮2%"]:
            df = dfs.get(name)
            if df is None:
                row += f" {'-':>10s}"
                continue
            sub = df[df[dim] == v]
            if len(sub) < 20:
                row += f" {'-':>10s}"
            else:
                row += f" {len(sub):>4d}{sub.success.mean()*100:>5.1f}%"
        print(row)

# ═══════════════════════════════════════════════════════════════
# Part 6: 信号日收盘距 target
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 6: 信号日收盘距 target（突破/拉回）")
print("=" * 100)

for name in ["量价节点", "量价节点严格"]:
    df = dfs.get(name)
    if df is None: continue

    gaps = []
    for _, r in df.iterrows():
        c = sig_close.get((r.code, r.signal_date))
        if c is None or c <= 0: continue
        gap = (c - r.entry_price) / r.entry_price * 100
        gaps.append({"key": r.sd_key, "gap": gap, "success": r.success,
                     "pnl": r.pnl_pct, "exit": r.exit_reason})

    gdf = pd.DataFrame(gaps)
    if gdf.empty: continue
    breakthrough = gdf[gdf.gap < 0]   # close < target
    pullback = gdf[gdf.gap >= 0]      # close >= target

    print(f"\n【{name}】")
    print(f"  突破(需上涨): n={len(breakthrough)} ({len(breakthrough)/len(gdf)*100:.0f}%) "
          f"WR={breakthrough.success.mean()*100:.1f}% PnL={breakthrough.pnl.median():+.2f}%")
    print(f"  拉回(需下跌): n={len(pullback)} ({len(pullback)/len(gdf)*100:.0f}%) "
          f"WR={pullback.success.mean()*100:.1f}% PnL={pullback.pnl.median():+.2f}%")

    if len(breakthrough) >= 30:
        print(f"  突破分桶:")
        for lo, hi, label in [(-100, -5, "<-5%"), (-5, -3, "-5~-3%"), (-3, -1, "-3~-1%"), (-1, 0, "-1~0%")]:
            sub = breakthrough[(breakthrough.gap > lo) & (breakthrough.gap <= hi)]
            if len(sub) < 10: continue
            print(f"    {label:<12s} n={len(sub):>4d} WR={sub.success.mean()*100:>5.1f}% PnL={sub.pnl.median():>+6.2f}%")

# ═══════════════════════════════════════════════════════════════
# Part 7: 结论
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 7: 2×2 效应分解")
print("=" * 100)

# 严格效应：控制 premium
strict_4 = dfs["量价节点严格"]
loose_4 = dfs["量价节点"]
strict_2 = dfs["量价节点严格上浮2%"]
loose_2 = dfs["量价节点上浮2%"]

print(f"""
┌──────────────────────────────────────────────────────┐
│              量价节点 2×2 效应分解                      │
├────────────────────┬────────────────┬────────────────┤
│                    │   premium=4%   │   premium=2%   │
├────────────────────┼────────────────┼────────────────┤
│ strict (节点≥50%线) │ WR={strict_4.success.mean()*100:.1f}%      │ WR={strict_2.success.mean()*100:.1f}%      │
│                    │ n={len(strict_4):,}        │ n={len(strict_2):,}        │
│                    │ PnL={strict_4.pnl_pct.median():+.2f}%     │ PnL={strict_2.pnl_pct.median():+.2f}%     │
├────────────────────┼────────────────┼────────────────┤
│ non-strict         │ WR={loose_4.success.mean()*100:.1f}%      │ WR={loose_2.success.mean()*100:.1f}%      │
│                    │ n={len(loose_4):,}        │ n={len(loose_2):,}        │
│                    │ PnL={loose_4.pnl_pct.median():+.2f}%     │ PnL={loose_2.pnl_pct.median():+.2f}%     │
├────────────────────┼────────────────┼────────────────┤
│ Δ strict           │ +{(strict_4.success.mean()-loose_4.success.mean())*100:.1f}pp         │ +{(strict_2.success.mean()-loose_2.success.mean())*100:.1f}pp         │
├────────────────────┼────────────────┼────────────────┤
│ Δ 4%→2%            │ -{(loose_4.success.mean()-loose_2.success.mean())*100:.1f}pp         │ -{(strict_4.success.mean()-strict_2.success.mean())*100:.1f}pp         │
└────────────────────┴────────────────┴────────────────┘

止损机制差异:
  量价节点: 盘中/收盘止损 = 跌破节点成本（绝对价）
  4%版:   entry = 成本×1.04, 止损距 ≈ {(1-1/1.04)*100:.1f}%
  2%版:   entry = 成本×1.02, 止损距 ≈ {(1-1/1.02)*100:.1f}%
  回调一半: entry = target, 止损距 = 5.0%
""")

print("完成。")
