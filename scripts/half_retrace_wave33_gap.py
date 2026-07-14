#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回调一半 × 3浪3 深度 + 跳空高开分析。
用法: .venv/Scripts/python scripts/half_retrace_wave33_gap.py
"""
from __future__ import annotations
import glob, io, os, sys, sqlite3
import pandas as pd
import numpy as np

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

pd.set_option("display.width", 320)
pd.set_option("display.max_columns", 60)
pd.set_option("display.max_rows", 200)

DATA = ".winrate_data/20260714_171048"
DB = "data/marketreview.db"

def load_csv(bp: str) -> pd.DataFrame:
    f = f"{DATA}/{bp}.csv"
    if not os.path.exists(f):
        return pd.DataFrame()
    df = pd.read_csv(f, encoding="utf-8-sig")
    if df.empty:
        return df
    df["sd"] = df["signal_date"].astype(str)
    df["ed"] = df["entry_date"].astype(str)
    return df

half = load_csv("回调一半")
half_strict = load_csv("回调一半严格")
print(f"回调一半: {len(half)} | 回调一半严格: {len(half_strict)}")

# ═══════════════════════════════════════════════════════════════
# Part 1: 3浪3 深度分析
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 90)
print("Part 1: 3浪3 × 回调一半 深度")
print("=" * 90)

for g, label in [(half, "普通"), (half_strict, "严格")]:
    base = g.success.mean()
    print(f"\n{'─'*70}")
    print(f"  {label} (基线 {base*100:.1f}%, n={len(g)})")

    # 1.1 方向 × streak 交叉
    print(f"\n  1.1 方向 × 连续天数:")
    g2 = g.copy()
    g2["streak_bin"] = pd.cut(g2.wave33_streak, bins=[-1, 0, 1, 3, 6, 100],
                               labels=["0天(拐点)","1天","2-3天","4-6天","7+天"])
    cross = g2.groupby(["wave33_direction","streak_bin"], observed=False).agg(
        n=("success","size"), wr=("success","mean"),
        mfp=("mfp_pct","mean"), pnl=("pnl_pct","mean"),
        bigwin=("exit_reason", lambda x: (x=="大胜利").mean()*100),
    )
    for (d, s), r in cross.iterrows():
        if r.n >= 15:
            flag = "✅" if r.wr > base*1.1 else "❌" if r.wr < base*0.85 else "  "
            print(f"    {flag} {d}_{s:<12s} n={int(r.n):>5d}  胜率={r.wr*100:>5.1f}%  "
                  f"抬升={(r.wr-base)*100:>+.0f}pp  MFP={r.mfp:.2f}%  "
                  f"大胜%={r.bigwin:.1f}%  盈亏中位={r.pnl:+.2f}%")

    # 1.2 streak 连续分布
    print(f"\n  1.2 streak 连续天数 vs 胜率 (slide window, min_n=30):")
    for d in ["up", "down", "flat"]:
        sub = g2[g2.wave33_direction == d]
        if len(sub) < 50:
            continue
        print(f"    [{d}]")
        for lo in range(0, 10):
            hi = lo + 2
            seg = sub[(sub.wave33_streak >= lo) & (sub.wave33_streak <= hi)]
            if len(seg) >= 30:
                print(f"      streak {lo}-{hi}: n={len(seg):>5d}  胜率={seg.success.mean()*100:>5.1f}%  "
                      f"抬升={(seg.success.mean()-base)*100:>+.0f}pp  MFP={seg.mfp_pct.mean():.2f}%")

    # 1.3 最高频的 wave33_label
    print(f"\n  1.3 wave33_label TOP/BOTTOM (n≥30):")
    labels = g2.groupby("wave33_label").agg(
        n=("success","size"), wr=("success","mean"),
        mfp=("mfp_pct","mean")).query("n >= 30")
    labels["lift"] = ((labels.wr - base) * 100).round(1)
    labels = labels.sort_values("lift", ascending=False)
    if len(labels) > 0:
        print(f"    ✅ TOP 10:")
        for lbl, r in labels.head(10).iterrows():
            print(f"       {lbl:<35s} n={int(r.n):>5d}  胜率={r.wr*100:>5.1f}%  抬升={r.lift:>+.0f}pp")
        print(f"    ❌ BOTTOM 10:")
        for lbl, r in labels.tail(10).iterrows():
            print(f"       {lbl:<35s} n={int(r.n):>5d}  胜率={r.wr*100:>5.1f}%  抬升={r.lift:>+.0f}pp")

# ═══════════════════════════════════════════════════════════════
# Part 2: 跳空高开分析
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("Part 2: 跳空高开 — 开盘价 vs 前收盘的 gap 对胜率的影响")
print("=" * 90)

# 从 DB 取 OHLC
db = sqlite3.connect(DB)
# 收集所有需要的 (code, date) 对
needed_pairs = set()
for g in [half, half_strict]:
    for _, r in g.iterrows():
        needed_pairs.add((r.code, r.sd))   # signal_date close
        needed_pairs.add((r.code, r.ed))   # entry_date open

print(f"需要查询 {len(needed_pairs)} 个 (code, date) 对...")

# 批量查询
codes = list(set(p[0] for p in needed_pairs))
dates = sorted(set(p[1] for p in needed_pairs))
print(f"  涉及 {len(codes)} 只股票, {len(dates)} 个日期")

# 分批查询避免 SQL 过长
BATCH = 500
ohlc = {}
for i in range(0, len(codes), BATCH):
    batch_codes = codes[i:i+BATCH]
    placeholders = ",".join(["?"] * len(batch_codes))
    # 获取这些股票在这些日期范围内的所有数据
    min_date = dates[0]
    max_date = dates[-1]
    cur = db.execute(f"""
        SELECT code, date, open, close, adj_factor
        FROM tushare_cache
        WHERE code IN ({placeholders}) AND date >= ? AND date <= ?
        ORDER BY code, date
    """, batch_codes + [min_date, max_date])
    for code, date, o, c, af in cur:
        ohlc[(code, str(date))] = {"open": o, "close": c, "adj_factor": af}
    print(f"  batch {i//BATCH+1}/{len(range(0,len(codes),BATCH))}: {len(ohlc)} rows")

db.close()
print(f"  共获取 {len(ohlc)} 条日线数据")

# 为每个 trade 计算 gap
def add_gap_metrics(g, label):
    g = g.copy()
    gaps = []
    sig_closes = []
    entry_opens = []
    entry_closes = []
    for _, r in g.iterrows():
        sig_row = ohlc.get((r.code, r.sd), None)
        ent_row = ohlc.get((r.code, r.ed), None)

        if sig_row and ent_row:
            sc = sig_row["close"]   # signal day close
            eo = ent_row["open"]    # entry day open
            # 前复权调整：用 entry_date 的 adj_factor 拉平
            af = ent_row.get("adj_factor", 1) or 1
            sig_af = sig_row.get("adj_factor", 1) or 1
            # QFQ: 统一到最新 adj_factor
            sc_adj = sc * sig_af / af if af > 0 else sc
            eo_adj = eo  # entry 本身已用 af

            # gap = entry_open / signal_close - 1
            gap_pct = (eo_adj - sc_adj) / sc_adj * 100 if sc_adj > 0 else 0
            gaps.append(round(gap_pct, 2))
            sig_closes.append(round(sc_adj, 3))
            entry_opens.append(round(eo_adj, 3))
        else:
            gaps.append(np.nan)
            sig_closes.append(np.nan)
            entry_opens.append(np.nan)

    g["sig_close"] = sig_closes
    g["entry_open"] = entry_opens
    g["gap_pct"] = gaps

    valid = g[g.gap_pct.notna()]
    print(f"\n  {label}: 有效 {len(valid)}/{len(g)} 笔 (有OHLC数据)")

    if len(valid) == 0:
        return g

    base = valid.success.mean()
    print(f"  基线胜率: {base*100:.1f}%")

    # 跳空方向分类
    g["gap_type"] = "无数据"
    g.loc[g.gap_pct > 3, "gap_type"] = "跳空>3%"
    g.loc[(g.gap_pct > 1) & (g.gap_pct <= 3), "gap_type"] = "跳空1-3%"
    g.loc[(g.gap_pct > 0) & (g.gap_pct <= 1), "gap_type"] = "跳空0-1%"
    g.loc[(g.gap_pct > -1) & (g.gap_pct <= 0), "gap_type"] = "平开/低开0-1%"
    g.loc[(g.gap_pct > -3) & (g.gap_pct <= -1), "gap_type"] = "低开1-3%"
    g.loc[g.gap_pct <= -3, "gap_type"] = "低开>3%"

    print(f"\n  跳空幅度 vs 胜率:")
    for gt in ["跳空>3%","跳空1-3%","跳空0-1%","平开/低开0-1%","低开1-3%","低开>3%"]:
        sub = g[g.gap_type == gt]
        if len(sub) >= 10:
            print(f"    {gt:<16s} n={len(sub):>5d}  胜率={sub.success.mean()*100:>5.1f}%  "
                  f"抬升={(sub.success.mean()-base)*100:>+.0f}pp  "
                  f"MFP={sub.mfp_pct.mean():.2f}%  大胜%={(sub.exit_reason=='大胜利').mean()*100:.1f}%  "
                  f"盈亏中位={sub.pnl_pct.median():>+.2f}%")

    # 更细粒度：1% 步长
    print(f"\n  细粒度 gap bins (1% step):")
    for lo in range(-5, 10):
        hi = lo + 1
        sub = valid[(valid.gap_pct > lo) & (valid.gap_pct <= hi)]
        if len(sub) >= 15:
            print(f"    gap {lo:+d}%~{hi:+d}%: n={len(sub):>5d}  胜率={sub.success.mean()*100:>5.1f}%  "
                  f"抬升={(sub.success.mean()-base)*100:>+.0f}pp  MFP={sub.mfp_pct.mean():.2f}%")

    # 跳空 × 均线方向
    print(f"\n  跳空 × 长均方向:")
    for gt in ["跳空>1%", "平开/低开0-1%", "低开>1%"]:
        sub = g[g.gap_type.isin(["跳空>3%","跳空1-3%"])] if gt == "跳空>1%" else \
              g[g.gap_type.isin(["低开1-3%","低开>3%"])] if gt == "低开>1%" else \
              g[g.gap_type == "平开/低开0-1%"]
        for lm in ["多头","盘整","空头"]:
            sub2 = sub[sub.long_ma_state == lm]
            if len(sub2) >= 10:
                print(f"      {gt}×{lm}: n={len(sub2):>5d}  胜率={sub2.success.mean()*100:>5.1f}%  "
                      f"抬升={(sub2.success.mean()-base)*100:>+.0f}pp")

    # 跳空 × 3浪3方向
    print(f"\n  跳空 × 3浪3方向:")
    for gt in ["跳空>1%", "平开/低开0-1%", "低开>1%"]:
        sub = g[g.gap_type.isin(["跳空>3%","跳空1-3%"])] if gt == "跳空>1%" else \
              g[g.gap_type.isin(["低开1-3%","低开>3%"])] if gt == "低开>1%" else \
              g[g.gap_type == "平开/低开0-1%"]
        for wv in ["up","down","flat"]:
            sub2 = sub[sub.wave33_direction == wv]
            if len(sub2) >= 10:
                print(f"      {gt}×{wv}: n={len(sub2):>5d}  胜率={sub2.success.mean()*100:>5.1f}%  "
                      f"抬升={(sub2.success.mean()-base)*100:>+.0f}pp")

    # 举例
    print(f"\n  跳空>3% 的成功案例 (2026年):")
    big_gap = g[(g.gap_type == "跳空>3%") & (g.sd.str.startswith("2026"))]
    for _, r in big_gap.nlargest(5, "pnl_pct").iterrows():
        print(f"    {r.code} {r.sd}→{r.ed} gap={r.gap_pct:+.1f}% "
              f"entry={r.entry_price} PnL={r.pnl_pct:+.2f}% {r.exit_reason}")
    print(f"\n  跳空>3% 的失败案例:")
    for _, r in big_gap.nsmallest(5, "pnl_pct").iterrows():
        print(f"    {r.code} {r.sd}→{r.ed} gap={r.gap_pct:+.1f}% "
              f"entry={r.entry_price} PnL={r.pnl_pct:+.2f}% {r.exit_reason}")

    return g

gap_half = add_gap_metrics(half, "回调一半 普通")
gap_half_strict = add_gap_metrics(half_strict, "回调一半 严格")

# ═══════════════════════════════════════════════════════════════
# Part 3: 跳空 × 3浪3 交叉
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("Part 3: 跳空 × 3浪3 双重筛选 (普通版)")
print("=" * 90)

g = gap_half[gap_half.gap_pct.notna()].copy()
base = g.success.mean()
print(f"基线: n={len(g)} 胜率={base*100:.1f}%")

# 最优组合路径
conditions = [
    ("基线", pd.Series(True, index=g.index)),
    ("3浪3方向=down", g.wave33_direction == "down"),
    ("3浪3 streak 1-5天", g.wave33_streak.between(1, 5)),
    ("跳空>1%", g.gap_pct > 1),
    ("跳空0-3%", (g.gap_pct > 0) & (g.gap_pct <= 3)),
    ("长均多头", g.long_ma_state == "多头"),
]

# 找最佳单条件
print("\n单条件过滤:")
for label, cond in conditions[1:]:
    sub = g[cond]
    if len(sub) >= 30:
        print(f"  {label}: n={len(sub)} 胜率={sub.success.mean()*100:.1f}% "
              f"抬升={(sub.success.mean()-base)*100:+.0f}pp")

# 叠加
print("\n叠加过滤 (baseline→逐步添加):")
mask = pd.Series(True, index=g.index)
for label, cond in [
    ("3浪3 down × streak1-5", g.wave33_direction.eq("down") & g.wave33_streak.between(1,5)),
    ("+跳空0-3%", (g.gap_pct > 0) & (g.gap_pct <= 3)),
    ("+长均多头", g.long_ma_state == "多头"),
    ("+电子/通信/计算机", g.industry_l1.isin(["电子","通信","计算机"])),
]:
    new_mask = mask & cond
    sub = g[new_mask]
    if len(sub) >= 20:
        print(f"  {label}: n={len(sub)} 胜率={sub.success.mean()*100:.1f}% "
              f"抬升={(sub.success.mean()-base)*100:+.0f}pp")
        mask = new_mask
    else:
        print(f"  {label}: n={len(sub)}  (样本不足)")

print("\n" + "=" * 90)
print("完成。")
