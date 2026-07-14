#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""两个问题：
1. 真共振(≤3%)时，MA entry 在回调 entry 上面还是下面？
2. MA-MA 之间共振（同标同日多MA触发），加入价格接近度后结论变不变？
用法: .venv/Scripts/python scripts/resonance_direction_ma2ma.py
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

# ═══════════════════════════════════════════════════════════════
# 问题1: MA 在回调 entry 上面还是下面？
# ═══════════════════════════════════════════════════════════════
print("=" * 90)
print("问题1: 真共振时，MA entry 在回调 entry 上面还是下面？")
print("=" * 90)

# 构建 MA 索引
ma_index = {}
for bp, df in ma_dfs.items():
    for _, r in df.iterrows():
        key = (r.code, r.sd)
        ma_index.setdefault(key, []).append({
            "bp": bp, "entry_price": r.entry_price, "reason": r.reason,
        })

def analyze_direction(g, label):
    g = g.copy()
    base = g.success.mean()

    ma_matches = []
    for _, r in g.iterrows():
        key = (r.code, r.sd)
        mas = ma_index.get(key, [])
        ma_matches.append(mas)
    g["ma_list"] = ma_matches
    g["ma_count"] = g["ma_list"].apply(len)
    g["has_ma"] = g.ma_count > 0

    def closest_ma_info(row):
        mas = row.ma_list
        if not mas:
            return None, None, None, None
        target = row.entry_price
        best = min(mas, key=lambda m: abs(m["entry_price"] - target))
        diff = best["entry_price"] - target  # 有符号：正=MA在上, 负=MA在下
        diff_pct = diff / target * 100
        abs_pct = abs(diff_pct)
        return best["bp"], best["entry_price"], round(diff_pct, 2), round(abs_pct, 1)

    g["closest_ma_bp"], g["closest_ma_price"], g["ma_price_gap_signed_pct"], g["ma_price_gap_pct"] = \
        zip(*g.apply(closest_ma_info, axis=1))

    g["resonance_type"] = "无MA"
    g.loc[(g.has_ma) & (g.ma_price_gap_pct <= 3), "resonance_type"] = "真共振(≤3%)"
    g.loc[(g.has_ma) & (g.ma_price_gap_pct > 3) & (g.ma_price_gap_pct <= 8), "resonance_type"] = "弱共振(3-8%)"
    g.loc[(g.has_ma) & (g.ma_price_gap_pct > 8), "resonance_type"] = "假共振(>8%)"

    print(f"\n{'─'*70}")
    print(f"  {label} (基线 {base*100:.1f}%)")

    # 真共振按方向分组
    tr = g[g.resonance_type == "真共振(≤3%)"]
    tr["ma_direction"] = "MA在上(正差距)"
    tr.loc[tr.ma_price_gap_signed_pct < 0, "ma_direction"] = "MA在下(负差距)"
    tr.loc[tr.ma_price_gap_signed_pct == 0, "ma_direction"] = "完全重合"

    for direction in ["MA在上(正差距)", "完全重合", "MA在下(负差距)"]:
        sub = tr[tr.ma_direction == direction]
        if len(sub) == 0:
            continue
        # 差距分布
        gaps = sub.ma_price_gap_pct
        print(f"\n    {direction}: n={len(sub)}")
        print(f"      胜率={sub.success.mean()*100:.1f}% 抬升={(sub.success.mean()-base)*100:+.1f}pp")
        print(f"      MFP均值={sub.mfp_pct.mean():.2f}% 平均PnL={sub.pnl_pct.mean():+.2f}%")
        print(f"      平均差距={gaps.mean():.1f}% 中位差距={gaps.median():.1f}%")

        # 更细的 gap 分段
        for max_gap in [0.5, 1, 1.5, 2, 2.5, 3]:
            sub2 = sub[sub.ma_price_gap_pct <= max_gap]
            if len(sub2) >= 5:
                print(f"        gap≤{max_gap:.1f}%: n={len(sub2)} 胜率={sub2.success.mean()*100:.1f}% "
                      f"抬升={(sub2.success.mean()-base)*100:+.1f}pp")

    # 按 MA 周期 × 方向
    print(f"\n    按MA周期×方向:")
    for p in [20, 55, 60, 120, 144, 240]:
        for direction in ["MA在上(正差距)", "MA在下(负差距)"]:
            sub = tr[(tr.closest_ma_bp.str.contains(str(p), na=False)) & (tr.ma_direction == direction)]
            if len(sub) >= 5:
                print(f"      MA{p} {direction}: n={len(sub)} 胜率={sub.success.mean()*100:.1f}% "
                      f"抬升={(sub.success.mean()-base)*100:+.1f}pp 平均gap={sub.ma_price_gap_pct.mean():.1f}%")

    # 举几个例子
    print(f"\n    2026年案例 (MA在上 vs MA在下):")
    for direction in ["MA在上(正差距)", "MA在下(负差距)"]:
        sub = tr[(tr.ma_direction == direction) & (tr.sd.str.startswith("2026"))]
        print(f"\n    [{direction}] TOP 3 by gap最小:")
        for _, r in sub.nsmallest(3, "ma_price_gap_pct").iterrows():
            arrow = "→" if r.ma_price_gap_signed_pct > 0 else "←"
            print(f"      {r.code} {r.sd} 回调={r.entry_price} {arrow} MA={r.closest_ma_price:.2f} "
                  f"(gap={r.ma_price_gap_signed_pct:+.2f}%) PnL={r.pnl_pct:+.2f}% {r.exit_reason}")

    return g

half_dir = analyze_direction(half, "回调一半 普通")
half_strict_dir = analyze_direction(half_strict, "回调一半 严格")

# ═══════════════════════════════════════════════════════════════
# 问题2: MA-MA 之间共振，加入价格接近度
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("问题2: MA-MA 共振 — 同日多MA触发，价格接近 vs 不接近")
print("=" * 90)

# 合并所有 MA 信号
all_ma = pd.concat([df for df in ma_dfs.values()], ignore_index=True)
print(f"总MA信号: {len(all_ma)} 笔")

# 按 (code, sd) 分组，看同标同日有多少MA触发，价格是否接近
ma_groups = all_ma.groupby(["code", "sd"])

# 对每组：统计MA数量、价格极差
group_stats = []
for (code, sd), grp in ma_groups:
    prices = grp.entry_price.values
    price_range = np.max(prices) - np.min(prices)
    mean_price = np.mean(prices)
    price_range_pct = price_range / mean_price * 100 if mean_price > 0 else 0
    group_stats.append({
        "code": code, "sd": sd,
        "ma_count": len(grp),
        "min_price": np.min(prices),
        "max_price": np.max(prices),
        "mean_price": mean_price,
        "price_range_pct": price_range_pct,
        "ma_bps": list(grp.buy_point.values),
        # 取该组第一条的 success/mfp/pnl/exit_reason（同一 signal_date 下应该一致）
        "success": grp.success.iloc[0],
        "mfp_pct": grp.mfp_pct.iloc[0],
        "pnl_pct": grp.pnl_pct.iloc[0],
        "exit_reason": grp.exit_reason.iloc[0],
    })

gs = pd.DataFrame(group_stats)
print(f"同日同标MA信号组: {len(gs)} 组")
print(f"  其中 1条MA: {(gs.ma_count==1).sum()} 组 ({(gs.ma_count==1).mean()*100:.0f}%)")
print(f"  其中 2条MA: {(gs.ma_count==2).sum()} 组")
print(f"  其中 3+条MA: {(gs.ma_count>=3).sum()} 组")

# 多条MA时，按价格接近度分类
multi = gs[gs.ma_count >= 2].copy()
base_all = gs.success.mean()
print(f"\n所有MA信号基线胜率: {base_all*100:.1f}%")

print(f"\n多MA共振组 (≥2条, n={len(multi)}) 按价格极差:")
# 价格极差分类
bins = [0, 1, 3, 5, 8, 15, 100]
labels = ["≤1%", "1-3%", "3-5%", "5-8%", "8-15%", ">15%"]
multi["price_range_bin"] = pd.cut(multi.price_range_pct, bins=bins, labels=labels)

for label in labels:
    sub = multi[multi.price_range_bin == label]
    if len(sub) == 0:
        continue
    avg_cnt = sub.ma_count.mean()
    print(f"  极差{label}: n={len(sub):>5d}  胜率={sub.success.mean()*100:>5.1f}%  "
          f"抬升={(sub.success.mean()-base_all)*100:+.0f}pp  "
          f"平均{avg_cnt:.1f}条MA  MFP={sub.mfp_pct.mean():.2f}%")

# 单条 vs 多条，按价格接近度
print(f"\n单条MA vs 多MA共振 (含价格接近度):")
single = gs[gs.ma_count == 1]
print(f"  单条MA: n={len(single)} 胜率={single.success.mean()*100:.1f}%")

# 多MA: 极差≤3%（真共振）vs >3%
tight_multi = multi[multi.price_range_pct <= 3]
loose_multi = multi[multi.price_range_pct > 3]
print(f"  多MA 极差≤3%(价格真共振): n={len(tight_multi)} 胜率={tight_multi.success.mean()*100:.1f}% "
      f"抬升={(tight_multi.success.mean()-base_all)*100:+.0f}pp")
print(f"  多MA 极差>3%(价格分散): n={len(loose_multi)} 胜率={loose_multi.success.mean()*100:.1f}% "
      f"抬升={(loose_multi.success.mean()-base_all)*100:+.0f}pp")

# 2条MA 真共振 vs 3+条MA 真共振
for cnt in [2, 3, 4, 5]:
    sub = tight_multi[tight_multi.ma_count == cnt]
    if len(sub) >= 5:
        print(f"    价格真共振 {cnt}条MA: n={len(sub)} 胜率={sub.success.mean()*100:.1f}% "
              f"抬升={(sub.success.mean()-base_all)*100:+.0f}pp")

# 按 MA 组合看
print(f"\n多MA共振(极差≤3%)的MA组合 TOP 15:")
tight_multi["ma_combo"] = tight_multi["ma_bps"].apply(lambda x: "+".join(sorted([
    b.replace("支撑","").replace("均线","") for b in x])))
combo_stats = tight_multi.groupby("ma_combo").agg(
    n=("success","size"), wr=("success","mean"),
    avg_gap=("price_range_pct","mean")).query("n >= 5").sort_values("n", ascending=False)
for combo, r in combo_stats.head(15).iterrows():
    print(f"  {combo:<40s} n={int(r.n):>4d} 胜率={r.wr*100:>5.1f}% 平均gap={r.avg_gap:.1f}%")

# 对比：单条MA × 周期
print(f"\n单条MA 各周期胜率（对照组）:")
for p in [20, 55, 60, 120, 144, 240]:
    sub = single[single.ma_bps.apply(lambda x: str(p) in str(x) if isinstance(x, list) else str(p) in x)]
    if len(sub) >= 50:
        print(f"  单条MA{p}: n={len(sub)} 胜率={sub.success.mean()*100:.1f}%")

# 极差≤1%（几乎完全重合）
ultra_tight = multi[multi.price_range_pct <= 1]
print(f"\n极差≤1%（几乎完全重合，n={len(ultra_tight)}）:")
print(f"  胜率={ultra_tight.success.mean()*100:.1f}% 抬升={(ultra_tight.success.mean()-base_all)*100:+.0f}pp")
print(f"  MFP={ultra_tight.mfp_pct.mean():.2f}% 大胜利={(ultra_tight.exit_reason=='大胜利').mean()*100:.1f}%")
# 例子
print(f"  案例:")
for _, r in ultra_tight.nsmallest(5, "price_range_pct").iterrows():
    print(f"    {r.code} {r.sd} MA={r.ma_combo} 极差={r.price_range_pct:.1f}% "
          f"PnL={r.pnl_pct:+.2f}% {r.exit_reason}")

print("\n" + "=" * 90)
print("完成。")
