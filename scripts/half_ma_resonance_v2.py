#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回调一半 × MA 共振 V2 — 加入价格接近度判断。
真正的共振 = 同日触发 + 买点价格接近（说明回调目标位恰好与MA重合）。
用法: .venv/Scripts/python scripts/half_ma_resonance_v2.py
"""
from __future__ import annotations
import glob, io, os, sys
import pandas as pd
import numpy as np

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

pd.set_option("display.width", 320)
pd.set_option("display.max_columns", 60)
pd.set_option("display.max_rows", 200)

DATA = ".winrate_data/20260714_171048"

def load_csv(bp: str) -> pd.DataFrame:
    f = f"{DATA}/{bp}.csv"
    if not os.path.exists(f):
        return pd.DataFrame()
    df = pd.read_csv(f, encoding="utf-8-sig")
    if df.empty:
        return df
    df["sd"] = df["signal_date"].astype(str)
    return df

# ── 加载 ──
half = load_csv("回调一半")
half_strict = load_csv("回调一半严格")

MA_BPS = ["MA20支撑","MA55支撑","MA60支撑","MA120支撑","MA144支撑","MA240支撑",
          "扣抵量均线支撑","5日均量均线支撑","无量均线支撑"]

ma_dfs = {}
for bp in MA_BPS:
    df = load_csv(bp)
    if not df.empty:
        ma_dfs[bp] = df

print("=" * 90)
print("回调一半 × MA 共振 V2 — 加入价格接近度")
print("=" * 90)

# ── 构建 MA 索引: (code, sd) -> [(bp, entry_price, reason)] ──
# 用 entry_price 作为 MA 的触发价位（MA支撑的 entry_price = MA值）
ma_index = {}
for bp, df in ma_dfs.items():
    for _, r in df.iterrows():
        key = (r.code, r.sd)
        ma_index.setdefault(key, []).append({
            "bp": bp, "entry_price": r.entry_price, "reason": r.reason,
        })

def analyze_resonance(g, label):
    """分析一个回调一半版本与MA的共振效果。"""
    g = g.copy()
    base = g.success.mean()

    # 为每个信号找同日MA信号
    ma_matches = []
    for _, r in g.iterrows():
        key = (r.code, r.sd)
        mas = ma_index.get(key, [])
        ma_matches.append(mas)

    g["ma_list"] = ma_matches
    g["ma_count"] = g["ma_list"].apply(len)

    # 分类
    g["has_ma"] = g.ma_count > 0

    # 找价格最接近的 MA
    def closest_ma(row):
        mas = row.ma_list
        if not mas:
            return None, None, None
        target = row.entry_price
        best = min(mas, key=lambda m: abs(m["entry_price"] - target))
        diff_pct = abs(best["entry_price"] - target) / target * 100
        return best["bp"], best["entry_price"], round(diff_pct, 1)

    g["closest_ma_bp"], g["closest_ma_price"], g["ma_price_gap_pct"] = zip(*g.apply(closest_ma, axis=1))

    # 按价格 gap 分组
    g["resonance_type"] = "无MA"
    g.loc[(g.has_ma) & (g.ma_price_gap_pct <= 3), "resonance_type"] = "真共振(≤3%)"
    g.loc[(g.has_ma) & (g.ma_price_gap_pct > 3) & (g.ma_price_gap_pct <= 8), "resonance_type"] = "弱共振(3-8%)"
    g.loc[(g.has_ma) & (g.ma_price_gap_pct > 8), "resonance_type"] = "假共振(>8%)"

    print(f"\n{'='*80}")
    print(f"  {label} (基线 {base*100:.1f}%, n={len(g)})")
    print(f"{'='*80}")

    # 价格 gap 分布
    has_ma_g = g[g.has_ma]
    if len(has_ma_g) > 0:
        print(f"\n  MA信号的价格接近度分布 (回调entry vs 最近MA entry):")
        for pct in [1, 2, 3, 5, 8, 15, 100]:
            within = (has_ma_g.ma_price_gap_pct <= pct).sum()
            print(f"    gap ≤ {pct:>2d}%: {within:>5d} 个 ({within/len(has_ma_g)*100:>4.1f}%)")

    # 按共振类型分组看胜率
    print(f"\n  按共振类型 vs 胜率:")
    for rt in ["无MA", "真共振(≤3%)", "弱共振(3-8%)", "假共振(>8%)"]:
        sub = g[g.resonance_type == rt]
        if len(sub) == 0:
            continue
        print(f"    {rt:<16s}  n={len(sub):>5d}  胜率={sub.success.mean()*100:>5.1f}%  "
              f"抬升={((sub.success.mean()-base)*100):>+.0f}pp  "
              f"MFP均值={sub.mfp_pct.mean():.2f}%  "
              f"大胜利%={((sub.exit_reason=='大胜利').mean()*100):.1f}%  "
              f"平均PnL={sub.pnl_pct.mean():>+.2f}%")

    # 真共振中按 price gap 细分
    print(f"\n  真共振(gap≤3%)中按 gap 细分:")
    for max_gap in [1, 1.5, 2, 2.5, 3]:
        sub = g[(g.has_ma) & (g.ma_price_gap_pct <= max_gap)]
        if len(sub) >= 10:
            print(f"    gap≤{max_gap:.1f}%: n={len(sub):>5d}  胜率={sub.success.mean()*100:>5.1f}%  "
                  f"抬升={((sub.success.mean()-base)*100):>+.0f}pp  MFP={sub.mfp_pct.mean():.2f}%")

    # 真共振中按共振MA条数
    print(f"\n  真共振(gap≤3%)中按共振MA条数:")
    true_res = g[g.resonance_type == "真共振(≤3%)"]
    for cnt in sorted(true_res.ma_count.unique()):
        sub = true_res[true_res.ma_count == cnt]
        if len(sub) >= 5:
            print(f"    {int(cnt)}条MA: n={len(sub):>5d}  胜率={sub.success.mean()*100:>5.1f}%  "
                  f"抬升={((sub.success.mean()-base)*100):>+.0f}pp  MFP={sub.mfp_pct.mean():.2f}%")

    # 真共振中按 MA 周期
    print(f"\n  真共振(gap≤3%)中按最近MA周期:")
    for p in [20, 55, 60, 120, 144, 240]:
        sub = true_res[true_res.closest_ma_bp.str.contains(str(p), na=False)]
        if len(sub) >= 10:
            print(f"    MA{p}共振: n={len(sub):>5d}  胜率={sub.success.mean()*100:>5.1f}%  "
                  f"抬升={((sub.success.mean()-base)*100):>+.0f}pp")

    # 2026年真共振例子
    print(f"\n  2026年真共振(gap≤3%)实际案例 (TOP 5 by gap最小):")
    true_res_26 = true_res[true_res.sd.str.startswith("2026")].nsmallest(5, "ma_price_gap_pct")
    for _, r in true_res_26.iterrows():
        print(f"    {r.code} {r.name} | {r.sd}")
        print(f"      回调entry={r.entry_price}  MA={r.closest_ma_bp} entry={r.closest_ma_price}  gap={r.ma_price_gap_pct}%")
        print(f"      PnL={r.pnl_pct:+.2f}%  MFP={r.mfp_pct:.2f}%  {r.exit_reason}  success={r.success}")
        print(f"      回调reason: {r.reason[:80]}")

    return g

# ── 分析两个版本 ──
half_v2 = analyze_resonance(half, "回调一半 普通")
half_strict_v2 = analyze_resonance(half_strict, "回调一半 严格")

# ── 对比总结 ──
print(f"\n\n{'='*80}")
print("结论对比")
print(f"{'='*80}")

for g, label in [(half_v2, "普通"), (half_strict_v2, "严格")]:
    base = g.success.mean()
    print(f"\n  {label}:")
    for rt in ["无MA", "真共振(≤3%)", "弱共振(3-8%)", "假共振(>8%)"]:
        sub = g[g.resonance_type == rt]
        if len(sub) == 0:
            continue
        better = "✅" if sub.success.mean() > base else "❌"
        print(f"    {better} {rt}: n={len(sub):>5d} 胜率={sub.success.mean()*100:.1f}% (+{(sub.success.mean()-base)*100:+.1f}pp)")

print("\n" + "=" * 90)
print("完成。")
