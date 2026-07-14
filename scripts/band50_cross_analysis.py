#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""波段50%：MA共振 + 多维度交叉分析。
用法: .venv/Scripts/python scripts/band50_cross_analysis.py
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

band50 = pd.read_csv(f"{DATA}/波段50%.csv", encoding="utf-8-sig")
band50["sd"] = band50["signal_date"].astype(str)
band50["ed"] = band50["entry_date"].astype(str)
print(f"波段50%: {len(band50)} 笔\n")

# ── OHLC + QFQ ──
db = sqlite3.connect(DB)
needed = set()
for _, r in band50.iterrows():
    needed.add((r.code, r.sd))
    needed.add((r.code, r.ed))
codes = list(set(p[0] for p in needed))
min_date = min(p[1] for p in needed)
max_date = max(p[1] for p in needed)

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

ohlc = {}
for i in range(0, len(codes), BATCH):
    batch = codes[i:i+BATCH]
    ph = ",".join(["?"]*len(batch))
    cur = db.execute(f"SELECT code, date, open, high, low, close, adj_factor FROM tushare_cache WHERE code IN ({ph}) AND date >= ? AND date <= ?", batch + [min_date, max_date])
    for row in cur:
        ohlc[(row[0], str(row[1]))] = {"open": row[2], "high": row[3], "low": row[4], "close": row[5], "adj_factor": row[6]}
db.close()

# ── 构建分析表 ──
rows = []
for _, r in band50.iterrows():
    sig = ohlc.get((r.code, r.sd))
    ent = ohlc.get((r.code, r.ed))
    if not sig or not ent: continue
    laf = latest_af.get(r.code, 1) or 1
    sig_af, ent_af = sig["adj_factor"] or 1, ent["adj_factor"] or 1
    sig_close_qfq = sig["close"] * sig_af / laf
    ent_open_qfq = ent["open"] * ent_af / laf
    ent_high_qfq = ent["high"] * ent_af / laf
    ent_low_qfq = ent["low"] * ent_af / laf

    ep = r.entry_price
    gap = (sig_close_qfq - ep) / ep * 100
    entry_type = "突破" if sig_close_qfq < ep else "拉回"

    stop_price = ep * 0.95
    hit_stop = 1 if ent_low_qfq <= stop_price else 0

    rows.append({
        "code": r.code, "sd": r.sd, "ed": r.ed,
        "entry_type": entry_type,
        "gap": round(gap, 2),
        "gap_bin": (
            "突破<-5%" if gap < -5 else
            "突破-5~-2%" if gap < -2 else
            "突破-2~0%" if gap < 0 else
            "拉回0-2%" if gap < 2 else
            "拉回2-5%" if gap < 5 else
            "拉回>5%"
        ),
        "hit_stop_intraday": hit_stop,
        "success": r.success, "pnl_pct": r.pnl_pct, "mfp_pct": r.mfp_pct,
        "exit_reason": r.exit_reason, "hold_days": r.hold_days,
        "long_ma_state": r.long_ma_state,
        "short_ma_state": r.short_ma_state,
        "cap_bucket": r.cap_bucket,
        "market_cap_yi": r.market_cap_yi,
        "industry_l1": r.industry_l1,
        "wave33_direction": r.wave33_direction,
    })

df = pd.DataFrame(rows)
base_wr = df.success.mean()
print(f"有效样本: {len(df)}, 基线胜率: {base_wr*100:.1f}%\n")

# ═══════════════════════════════════════════════════════════════
# Part 1: 均线排列共振（长均 + 短均）
# ═══════════════════════════════════════════════════════════════
print("=" * 100)
print("Part 1: 均线排列共振")
print("=" * 100)

for lma in ["多头", "空头", "盘整"]:
    print(f"\n── 长均={lma} ──")
    print(f"{'短均':<6s} {'类型':<6s} {'n':>5s} {'胜率':>6s} {'PnL':>8s} {'MFP':>8s} {'大胜%':>6s} {'止损率':>7s} {'触止损':>7s} {'持仓天':>6s}")
    print("-" * 95)
    for sma in ["多头", "空头", "盘整"]:
        for et in ["突破", "拉回"]:
            sub = df[(df.long_ma_state == lma) & (df.short_ma_state == sma) & (df.entry_type == et)]
            if len(sub) < 10: continue
            stopped = sub[sub.exit_reason.isin(["盘中止损", "收盘止损"])]
            print(f"{sma:<6s} {et:<6s} {len(sub):>5d} {sub.success.mean()*100:>5.1f}% "
                  f"{sub.pnl_pct.median():>+7.2f}% {sub.mfp_pct.median():>+7.2f}% "
                  f"{(sub.exit_reason=='大胜利').mean()*100:>5.1f}% "
                  f"{len(stopped)/len(sub)*100:>6.1f}% "
                  f"{sub.hit_stop_intraday.mean()*100:>6.1f}% "
                  f"{sub.hold_days.median():>5.0f}天")

# ═══════════════════════════════════════════════════════════════
# Part 2: 长均 × 市值 × 类型
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 2: 长均 × 市值 × 类型")
print("=" * 100)

for cap in ["小盘", "中盘", "大盘"]:
    print(f"\n── 市值={cap} ──")
    print(f"{'长均':<6s} {'类型':<6s} {'n':>5s} {'胜率':>6s} {'PnL':>8s} {'大胜%':>6s} {'止损率':>7s} {'触止损':>7s}")
    print("-" * 75)
    for lma in ["多头", "空头", "盘整"]:
        for et in ["突破", "拉回"]:
            sub = df[(df.cap_bucket == cap) & (df.long_ma_state == lma) & (df.entry_type == et)]
            if len(sub) < 10: continue
            stopped = sub[sub.exit_reason.isin(["盘中止损", "收盘止损"])]
            print(f"{lma:<6s} {et:<6s} {len(sub):>5d} {sub.success.mean()*100:>5.1f}% "
                  f"{sub.pnl_pct.median():>+7.2f}% "
                  f"{(sub.exit_reason=='大胜利').mean()*100:>5.1f}% "
                  f"{len(stopped)/len(sub)*100:>6.1f}% "
                  f"{sub.hit_stop_intraday.mean()*100:>6.1f}%")

# ═══════════════════════════════════════════════════════════════
# Part 3: 长均 × 3浪3 × 类型
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 3: 长均 × 3浪3 × 类型")
print("=" * 100)

for wv in ["up", "down", "flat"]:
    print(f"\n── 3浪3={wv} ──")
    print(f"{'长均':<6s} {'类型':<6s} {'n':>5s} {'胜率':>6s} {'PnL':>8s} {'大胜%':>6s} {'止损率':>7s} {'触止损':>7s}")
    print("-" * 75)
    for lma in ["多头", "空头", "盘整"]:
        for et in ["突破", "拉回"]:
            sub = df[(df.wave33_direction == wv) & (df.long_ma_state == lma) & (df.entry_type == et)]
            if len(sub) < 10: continue
            stopped = sub[sub.exit_reason.isin(["盘中止损", "收盘止损"])]
            print(f"{lma:<6s} {et:<6s} {len(sub):>5d} {sub.success.mean()*100:>5.1f}% "
                  f"{sub.pnl_pct.median():>+7.2f}% "
                  f"{(sub.exit_reason=='大胜利').mean()*100:>5.1f}% "
                  f"{len(stopped)/len(sub)*100:>6.1f}% "
                  f"{sub.hit_stop_intraday.mean()*100:>6.1f}%")

# ═══════════════════════════════════════════════════════════════
# Part 4: 距离桶 × 长均 × 类型（深度交叉）
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 4: 距离桶 × 长均 × 类型（关键交叉）")
print("=" * 100)

print(f"\n{'距离桶':<14s} {'长均':<6s} {'类型':<6s} {'n':>5s} {'胜率':>6s} {'PnL':>8s} {'大胜%':>6s} {'止损率':>7s} {'触止损':>7s} {'持仓':>5s}")
print("-" * 95)

for gb in ["突破<-5%", "突破-5~-2%", "突破-2~0%", "拉回0-2%", "拉回2-5%", "拉回>5%"]:
    for lma in ["多头", "空头", "盘整"]:
        sub = df[(df.gap_bin == gb) & (df.long_ma_state == lma)]
        if len(sub) < 10: continue
        stopped = sub[sub.exit_reason.isin(["盘中止损", "收盘止损"])]
        et = "突破" if "突破" in gb else "拉回"
        print(f"{gb:<14s} {lma:<6s} {et:<6s} {len(sub):>5d} {sub.success.mean()*100:>5.1f}% "
              f"{sub.pnl_pct.median():>+7.2f}% "
              f"{(sub.exit_reason=='大胜利').mean()*100:>5.1f}% "
              f"{len(stopped)/len(sub)*100:>6.1f}% "
              f"{sub.hit_stop_intraday.mean()*100:>6.1f}% "
              f"{sub.hold_days.median():>4.0f}天")

# ═══════════════════════════════════════════════════════════════
# Part 5: 行业 × 长均 × 类型
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 5: 行业 × 长均 × 类型（Top 行业）")
print("=" * 100)

# top 行业
top_ind = df.industry_l1.value_counts().head(10).index
for ind in top_ind:
    ind_df = df[df.industry_l1 == ind]
    for lma in ["多头", "空头", "盘整"]:
        for et in ["突破", "拉回"]:
            sub = ind_df[(ind_df.long_ma_state == lma) & (ind_df.entry_type == et)]
            if len(sub) < 20: continue
            stopped = sub[sub.exit_reason.isin(["盘中止损", "收盘止损"])]
            lift = (sub.success.mean() - df[df.industry_l1 == ind].success.mean()) * 100
            print(f"{ind:<10s} {lma:<6s} {et:<6s} n={len(sub):>4d} "
                  f"WR={sub.success.mean()*100:>5.1f}% lift={lift:>+5.1f}pp "
                  f"PnL={sub.pnl_pct.median():>+6.2f}% stop={sub.hit_stop_intraday.mean()*100:>4.1f}%")

# ═══════════════════════════════════════════════════════════════
# Part 6: 综合最佳/最差组合
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 6: 综合最佳/最差多维度组合 (n≥50)")
print("=" * 100)

combos = []
for (lma, sma, cap, wv, et), grp in df.groupby(["long_ma_state", "short_ma_state", "cap_bucket", "wave33_direction", "entry_type"]):
    n = len(grp)
    if n < 50: continue
    wr = grp.success.mean()
    pnl = grp.pnl_pct.median()
    big = (grp.exit_reason == "大胜利").mean()
    stopped = grp[grp.exit_reason.isin(["盘中止损", "收盘止损"])]
    stop_rate = len(stopped) / n
    hit = grp.hit_stop_intraday.mean()
    combos.append({
        "长均": lma, "短均": sma, "市值": cap, "3浪3": wv, "类型": et,
        "n": n, "WR": wr, "PnL": pnl, "大胜": big, "止损率": stop_rate, "触止损": hit,
    })

combos_df = pd.DataFrame(combos)
combos_df["score"] = combos_df["WR"] * 100 - combos_df["触止损"] * 0.3  # 胜率为主，惩罚高触止损

print("\n🏆 Top 15 组合 (按胜率):")
print(f"{'长均':<6s} {'短均':<6s} {'市值':<6s} {'3浪3':<6s} {'类型':<6s} {'n':>5s} {'胜率':>6s} {'PnL':>8s} {'大胜%':>6s} {'止损率':>7s} {'触止损':>7s}")
print("-" * 95)
for _, c in combos_df.nlargest(15, "WR").iterrows():
    print(f"{c['长均']:<6s} {c['短均']:<6s} {c['市值']:<6s} {c['3浪3']:<6s} {c['类型']:<6s} "
          f"{int(c['n']):>5d} {c['WR']*100:>5.1f}% {c['PnL']:>+7.2f}% "
          f"{c['大胜']*100:>5.1f}% {c['止损率']*100:>6.1f}% {c['触止损']*100:>6.1f}%")

print(f"\n📉 Bottom 10 组合 (按胜率):")
for _, c in combos_df.nsmallest(10, "WR").iterrows():
    print(f"{c['长均']:<6s} {c['短均']:<6s} {c['市值']:<6s} {c['3浪3']:<6s} {c['类型']:<6s} "
          f"{int(c['n']):>5d} {c['WR']*100:>5.1f}% {c['PnL']:>+7.2f}% "
          f"{c['大胜']*100:>5.1f}% {c['止损率']*100:>6.1f}% {c['触止损']*100:>6.1f}%")

# ═══════════════════════════════════════════════════════════════
# Part 7: 结论摘要
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("Part 7: 波段50% 维度效应排序")
print("=" * 100)

# 各维度单变量抬升
def lift_analysis(dim, label_map=None):
    results = []
    for val in df[dim].unique():
        sub = df[df[dim] == val]
        if len(sub) < 30: continue
        label = label_map.get(val, val) if label_map else val
        results.append((label, len(sub), sub.success.mean()))
    results.sort(key=lambda x: x[2], reverse=True)
    best, worst = results[0], results[-1]
    spread = (best[2] - worst[2]) * 100
    print(f"  {dim}: 最佳={best[0]}({best[2]*100:.1f}%) 最差={worst[0]}({worst[2]*100:.1f}%) 极差={spread:.1f}pp")
    return spread

print("\n单维度极差（越大说明维度越重要）:")
dims = [
    ("long_ma_state", None),
    ("short_ma_state", None),
    ("entry_type", None),
    ("cap_bucket", None),
    ("wave33_direction", None),
    ("gap_bin", None),
]
for dim, lm in dims:
    lift_analysis(dim, lm)

print("\n完成。")
