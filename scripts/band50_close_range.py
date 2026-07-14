#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""波段50%：突破（close<target）vs 拉回（close>target）分解分析。
用法: .venv/Scripts/python scripts/band50_close_range.py
"""
from __future__ import annotations
import io, os, sys, sqlite3
import pandas as pd
import numpy as np

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

pd.set_option("display.width", 320)
pd.set_option("display.max_columns", 60)
pd.set_option("display.max_rows", 200)

DATA = ".winrate_data/20260714_171048"
DB = "data/marketreview.db"

# ── 加载 ──
band50 = pd.read_csv(f"{DATA}/波段50%.csv", encoding="utf-8-sig")
band50["sd"] = band50["signal_date"].astype(str)
band50["ed"] = band50["entry_date"].astype(str)
print(f"波段50%: {len(band50)} 笔\n")

# ── 从 DB 取 OHLC + adj_factor ──
db = sqlite3.connect(DB)
needed = set()
for _, r in band50.iterrows():
    needed.add((r.code, r.sd))
    needed.add((r.code, r.ed))

codes = list(set(p[0] for p in needed))
min_date = min(p[1] for p in needed)
max_date = max(p[1] for p in needed)

# 取每只股票最新的 adj_factor（用于 QFQ 调整）
latest_af = {}
BATCH = 500
for i in range(0, len(codes), BATCH):
    batch = codes[i:i+BATCH]
    ph = ",".join(["?"]*len(batch))
    cur = db.execute(f"""
        SELECT code, MAX(date) as max_date FROM tushare_cache
        WHERE code IN ({ph}) GROUP BY code
    """, batch)
    code_max_dates = {row[0]: row[1] for row in cur}
    for code, md in code_max_dates.items():
        cur2 = db.execute(
            "SELECT adj_factor FROM tushare_cache WHERE code=? AND date=?",
            [code, md])
        row2 = cur2.fetchone()
        if row2:
            latest_af[code] = row2[0]

# 取 OHLC
ohlc = {}
for i in range(0, len(codes), BATCH):
    batch = codes[i:i+BATCH]
    ph = ",".join(["?"]*len(batch))
    cur = db.execute(f"""
        SELECT code, date, open, high, low, close, adj_factor
        FROM tushare_cache WHERE code IN ({ph}) AND date >= ? AND date <= ?
    """, batch + [min_date, max_date])
    for row in cur:
        ohlc[(row[0], str(row[1]))] = {
            "open": row[2], "high": row[3], "low": row[4],
            "close": row[5], "adj_factor": row[6]
        }
db.close()
print(f"OHLC: {len(ohlc)} rows, latest_af: {len(latest_af)} stocks\n")

# ── 构建分析表 ──
rows = []
for _, r in band50.iterrows():
    sig = ohlc.get((r.code, r.sd))
    ent = ohlc.get((r.code, r.ed))
    if not sig or not ent:
        continue

    # QFQ 调整
    laf = latest_af.get(r.code, 1) or 1
    sig_af = sig["adj_factor"] or 1
    ent_af = ent["adj_factor"] or 1

    sig_close_qfq = sig["close"] * sig_af / laf
    sig_high_qfq = sig["high"] * sig_af / laf
    sig_low_qfq = sig["low"] * sig_af / laf
    sig_open_qfq = sig["open"] * sig_af / laf
    ent_open_qfq = ent["open"] * ent_af / laf
    ent_high_qfq = ent["high"] * ent_af / laf
    ent_low_qfq = ent["low"] * ent_af / laf
    ent_close_qfq = ent["close"] * ent_af / laf

    ep = r.entry_price  # CSV 中已是 QFQ 调整后的

    # 信号日收盘离 target 距离（正=上方/拉回，负=下方/突破）
    close_to_target_pct = (sig_close_qfq - ep) / ep * 100

    # 类型：突破（需上涨触发）vs 拉回（需下跌触发）
    entry_type = "突破" if sig_close_qfq < ep else "拉回"

    # 入场日盘中行为
    ent_high_vs_entry = (ent_high_qfq - ep) / ep * 100
    ent_close_vs_entry = (ent_close_qfq - ep) / ep * 100
    ent_retrace_from_high = (ent_close_qfq - ent_high_qfq) / ent_high_qfq * 100 if ent_high_qfq > 0 else 0

    # 入场日是否盘中触发止损
    stop_price = ep * 0.95
    hit_stop_intraday = 1 if ent_low_qfq <= stop_price else 0

    # 信号日上影
    sig_range = sig_high_qfq - sig_low_qfq
    sig_upper_shadow = (sig_high_qfq - max(sig_open_qfq, sig_close_qfq)) / sig_range if sig_range > 0 else 0
    sig_close_position = (sig_close_qfq - sig_low_qfq) / sig_range if sig_range > 0 else 0.5

    # 次日开盘跳空
    gap_open_vs_close = (ent_open_qfq - sig_close_qfq) / sig_close_qfq * 100

    rows.append({
        "code": r.code, "sd": r.sd, "ed": r.ed,
        "ep": ep,
        "entry_type": entry_type,
        "sig_close_qfq": sig_close_qfq,
        "close_to_target_pct": round(close_to_target_pct, 2),
        "sig_close_position": sig_close_position,
        "sig_upper_shadow": sig_upper_shadow,
        "ent_open_qfq": ent_open_qfq,
        "ent_high_vs_entry": round(ent_high_vs_entry, 2),
        "ent_close_vs_entry": round(ent_close_vs_entry, 2),
        "ent_retrace_from_high": round(ent_retrace_from_high, 2),
        "hit_stop_intraday": hit_stop_intraday,
        "gap_open_vs_close": round(gap_open_vs_close, 2),
        "success": r.success, "mfp_pct": r.mfp_pct,
        "pnl_pct": r.pnl_pct, "exit_reason": r.exit_reason,
        "hold_days": r.hold_days,
        "long_ma_state": r.long_ma_state,
        "market_cap_yi": r.market_cap_yi,
        "cap_bucket": r.cap_bucket,
        "industry_l1": r.industry_l1,
        "wave33_direction": r.wave33_direction,
    })

df = pd.DataFrame(rows)
print(f"有效样本: {len(df)} 笔\n")

# ═══════════════════════════════════════════════════════════════
# Part 1: 突破 vs 拉回 — 总览
# ═══════════════════════════════════════════════════════════════
print("=" * 90)
print("Part 1: 突破 vs 拉回 — 总览")
print("=" * 90)

for et in ["突破", "拉回"]:
    sub = df[df.entry_type == et]
    win = sub.success.mean()
    stopped = sub[sub.exit_reason.isin(["盘中止损", "收盘止损"])]
    print(f"\n{'─' * 50}")
    print(f"【{et}】n={len(sub)} ({len(sub)/len(df)*100:.1f}%)")
    print(f"  胜率: {win*100:.1f}%  |  PnL中位: {sub.pnl_pct.median():+.2f}%  |  MFP中位: {sub.mfp_pct.median():+.2f}%")
    print(f"  大胜率: {(sub.exit_reason=='大胜利').mean()*100:.1f}%  |  时间止损: {(sub.exit_reason=='时间止损').mean()*100:.1f}%")
    print(f"  止损率: {len(stopped)/len(sub)*100:.1f}% (盘中{stopped.exit_reason.value_counts().get('盘中止损',0)} + 收盘{stopped.exit_reason.value_counts().get('收盘止损',0)})")
    print(f"  持仓中位: {sub.hold_days.median():.0f}天  |  止损PnL中位: {stopped.pnl_pct.median():+.2f}%")
    print(f"  入场日盘中触止损: {sub.hit_stop_intraday.mean()*100:.1f}%")
    print(f"  入场日高位回落: {sub.ent_retrace_from_high.median():+.2f}%")
    print(f"  收盘距target中位: {sub.close_to_target_pct.median():+.2f}%")

# ═══════════════════════════════════════════════════════════════
# Part 2: 突破 — 收盘距 target 分桶
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("Part 2: 突破（close < target）— 收盘距 target 分桶")
print("=" * 90)

breakout = df[df.entry_type == "突破"]
base_wr = breakout.success.mean()

bins = [
    (-100, -5, "<-5%（很远）"), (-5, -3, "-5~-3%"),
    (-3, -2, "-3~-2%"), (-2, -1, "-2~-1%"),
    (-1, -0.5, "-1~-0.5%"), (-0.5, 0, "-0.5~0%"),
]

print(f"\n{'区间':<18s} {'n':>5s} {'占比':>6s} {'胜率':>6s} {'抬升':>6s} {'PnL中位':>8s} {'止损PnL':>8s} {'盘中触止损':>10s} {'大胜%':>6s} {'持仓天':>6s}")
print("-" * 105)

for lo, hi, label in bins:
    sub = breakout[(breakout.close_to_target_pct > lo) & (breakout.close_to_target_pct <= hi)]
    if len(sub) < 10:
        continue
    stopped = sub[sub.exit_reason.isin(["盘中止损", "收盘止损"])]
    stop_pnl = stopped.pnl_pct.median() if len(stopped) > 0 else float('nan')
    lift = (sub.success.mean() - base_wr) * 100
    print(f"{label:<18s} {len(sub):>5d} {len(sub)/len(breakout)*100:>5.1f}% "
          f"{sub.success.mean()*100:>5.1f}% {lift:>+5.1f}pp "
          f"{sub.pnl_pct.median():>+7.2f}% {stop_pnl:>+7.2f}% "
          f"{sub.hit_stop_intraday.mean()*100:>9.1f}% "
          f"{(sub.exit_reason=='大胜利').mean()*100:>5.1f}% "
          f"{sub.hold_days.median():>5.0f}天")

# ═══════════════════════════════════════════════════════════════
# Part 3: 拉回 — 收盘距 target 分桶
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("Part 3: 拉回（close > target）— 收盘距 target 分桶")
print("=" * 90)

pullback = df[df.entry_type == "拉回"]
base_wr_pb = pullback.success.mean()

bins_pb = [
    (0, 0.5, "0~0.5%"), (0.5, 1, "0.5~1%"),
    (1, 2, "1~2%"), (2, 3, "2~3%"),
    (3, 5, "3~5%"), (5, 100, ">5%"),
]

print(f"\n{'区间':<14s} {'n':>5s} {'占比':>6s} {'胜率':>6s} {'抬升':>6s} {'PnL中位':>8s} {'止损PnL':>8s} {'盘中触止损':>10s} {'大胜%':>6s} {'持仓天':>6s}")
print("-" * 100)

for lo, hi, label in bins_pb:
    sub = pullback[(pullback.close_to_target_pct > lo) & (pullback.close_to_target_pct <= hi)]
    if len(sub) < 10:
        continue
    stopped = sub[sub.exit_reason.isin(["盘中止损", "收盘止损"])]
    stop_pnl = stopped.pnl_pct.median() if len(stopped) > 0 else float('nan')
    lift = (sub.success.mean() - base_wr_pb) * 100
    print(f"{label:<14s} {len(sub):>5d} {len(sub)/len(pullback)*100:>5.1f}% "
          f"{sub.success.mean()*100:>5.1f}% {lift:>+5.1f}pp "
          f"{sub.pnl_pct.median():>+7.2f}% {stop_pnl:>+7.2f}% "
          f"{sub.hit_stop_intraday.mean()*100:>9.1f}% "
          f"{(sub.exit_reason=='大胜利').mean()*100:>5.1f}% "
          f"{sub.hold_days.median():>5.0f}天")

# ═══════════════════════════════════════════════════════════════
# Part 4: 长均排列 × 突破/拉回
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("Part 4: 长均排列 × 突破/拉回")
print("=" * 90)

print(f"\n{'长均':<6s} {'类型':<6s} {'n':>5s} {'占比':>6s} {'胜率':>6s} {'PnL中位':>8s} {'大胜%':>6s} {'止损率':>7s} {'盘中触止损':>10s}")
print("-" * 85)

for ma in ["多头", "空头", "盘整"]:
    for et in ["突破", "拉回"]:
        sub = df[(df.long_ma_state == ma) & (df.entry_type == et)]
        if len(sub) < 10:
            continue
        stopped = sub[sub.exit_reason.isin(["盘中止损", "收盘止损"])]
        print(f"{ma:<6s} {et:<6s} {len(sub):>5d} {len(sub)/len(df)*100:>5.1f}% "
              f"{sub.success.mean()*100:>5.1f}% {sub.pnl_pct.median():>+7.2f}% "
              f"{(sub.exit_reason=='大胜利').mean()*100:>5.1f}% "
              f"{len(stopped)/len(sub)*100:>6.1f}% "
              f"{sub.hit_stop_intraday.mean()*100:>9.1f}%")

# ═══════════════════════════════════════════════════════════════
# Part 5: 市值 × 突破/拉回
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("Part 5: 市值桶 × 突破/拉回")
print("=" * 90)

print(f"\n{'市值':<6s} {'类型':<6s} {'n':>5s} {'胜率':>6s} {'PnL中位':>8s} {'大胜%':>6s} {'止损率':>7s} {'盘中触止损':>10s}")
print("-" * 80)

for cap in ["微盘", "小盘", "中盘", "大盘"]:
    for et in ["突破", "拉回"]:
        sub = df[(df.cap_bucket == cap) & (df.entry_type == et)]
        if len(sub) < 10:
            continue
        stopped = sub[sub.exit_reason.isin(["盘中止损", "收盘止损"])]
        print(f"{cap:<6s} {et:<6s} {len(sub):>5d} {sub.success.mean()*100:>5.1f}% "
              f"{sub.pnl_pct.median():>+7.2f}% "
              f"{(sub.exit_reason=='大胜利').mean()*100:>5.1f}% "
              f"{len(stopped)/len(sub)*100:>6.1f}% "
              f"{sub.hit_stop_intraday.mean()*100:>9.1f}%")

# ═══════════════════════════════════════════════════════════════
# Part 6: 3浪3方向 × 突破/拉回
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("Part 6: 3浪3方向 × 突破/拉回")
print("=" * 90)

print(f"\n{'Wave33':<6s} {'类型':<6s} {'n':>5s} {'胜率':>6s} {'PnL中位':>8s} {'大胜%':>6s} {'止损率':>7s} {'盘中触止损':>10s}")
print("-" * 80)

for wv in ["up", "down", "flat"]:
    for et in ["突破", "拉回"]:
        sub = df[(df.wave33_direction == wv) & (df.entry_type == et)]
        if len(sub) < 10:
            continue
        stopped = sub[sub.exit_reason.isin(["盘中止损", "收盘止损"])]
        print(f"{wv:<6s} {et:<6s} {len(sub):>5d} {sub.success.mean()*100:>5.1f}% "
              f"{sub.pnl_pct.median():>+7.2f}% "
              f"{(sub.exit_reason=='大胜利').mean()*100:>5.1f}% "
              f"{len(stopped)/len(sub)*100:>6.1f}% "
              f"{sub.hit_stop_intraday.mean()*100:>9.1f}%")

# ═══════════════════════════════════════════════════════════════
# Part 7: 退出原因分布 — 突破 vs 拉回
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("Part 7: 退出原因分布")
print("=" * 90)

for et in ["突破", "拉回"]:
    sub = df[df.entry_type == et]
    print(f"\n【{et}】n={len(sub)}")
    vc = sub.exit_reason.value_counts()
    for reason in ["大胜利", "小胜利", "时间止损", "收盘止损", "盘中止损"]:
        cnt = vc.get(reason, 0)
        pct = cnt / len(sub) * 100
        marker = " ←" if reason in ["收盘止损", "盘中止损"] else ""
        print(f"  {reason}: {cnt:>5d} ({pct:>5.1f}%){marker}")

# ═══════════════════════════════════════════════════════════════
# Part 8: 综合结论
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("Part 8: 综合结论")
print("=" * 90)

# 计算各项对比
bo = df[df.entry_type == "突破"]
pb = df[df.entry_type == "拉回"]

bo_stopped = bo[bo.exit_reason.isin(["盘中止损", "收盘止损"])]
pb_stopped = pb[pb.exit_reason.isin(["盘中止损", "收盘止损"])]

print(f"""
┌─────────────────────────────────────────────────────────┐
│                    波段50% 突破 vs 拉回                    │
├──────────────┬──────────────────┬───────────────────────┤
│              │   突破 (需上涨)    │   拉回 (需下跌)         │
├──────────────┼──────────────────┼───────────────────────┤
│ 信号量       │  {len(bo):>5d} ({len(bo)/len(df)*100:>4.1f}%)    │  {len(pb):>5d} ({len(pb)/len(df)*100:>4.1f}%)       │
│ 胜率         │  {bo.success.mean()*100:>5.1f}%          │  {pb.success.mean()*100:>5.1f}%             │
│ PnL 中位     │  {bo.pnl_pct.median():>+6.2f}%          │  {pb.pnl_pct.median():>+6.2f}%             │
│ MFP 中位     │  {bo.mfp_pct.median():>+6.2f}%          │  {pb.mfp_pct.median():>+6.2f}%             │
│ 大胜率       │  {(bo.exit_reason=='大胜利').mean()*100:>5.1f}%          │  {(pb.exit_reason=='大胜利').mean()*100:>5.1f}%             │
│ 止损率       │  {len(bo_stopped)/len(bo)*100:>5.1f}%          │  {len(pb_stopped)/len(pb)*100:>5.1f}%             │
│ 入场触止损   │  {bo.hit_stop_intraday.mean()*100:>5.1f}%          │  {pb.hit_stop_intraday.mean()*100:>5.1f}%             │
│ 持仓中位     │  {bo.hold_days.median():>5.0f}天          │  {pb.hold_days.median():>5.0f}天             │
│ 收盘距target │  {bo.close_to_target_pct.median():>+5.2f}%          │  {pb.close_to_target_pct.median():>+5.2f}%             │
└──────────────┴──────────────────┴───────────────────────┘
""")

# 拉回方向的额外分析：距target越远是不是越安全？
print("拉回方向：距target越远 → ？")
print("-" * 50)
for lo, hi, label in [(0,1,"贴脸(0-1%)"), (1,2,"近(1-2%)"), (2,3,"中(2-3%)"), (3,5,"远(3-5%)"), (5,100,"很远(>5%)")]:
    sub = pullback[(pullback.close_to_target_pct > lo) & (pullback.close_to_target_pct <= hi)]
    if len(sub) < 10:
        continue
    print(f"  {label:<14s} n={len(sub):>4d}  胜率={sub.success.mean()*100:>5.1f}%  "
          f"PnL={sub.pnl_pct.median():>+6.2f}%  盘中触止损={sub.hit_stop_intraday.mean()*100:>4.1f}%")

# 突破方向：距target越远是不是越危险？
print("\n突破方向：距target越远 → ？")
print("-" * 50)
for lo, hi, label in [(-0.5, 0, "贴脸(-0.5~0%)"), (-1, -0.5, "近(-1~-0.5%)"),
                       (-2, -1, "中(-2~-1%)"), (-3, -2, "远(-3~-2%)"),
                       (-5, -3, "很远(-5~-3%)"), (-100, -5, "极远(<-5%)")]:
    sub = breakout[(breakout.close_to_target_pct > lo) & (breakout.close_to_target_pct <= hi)]
    if len(sub) < 10:
        continue
    print(f"  {label:<18s} n={len(sub):>4d}  胜率={sub.success.mean()*100:>5.1f}%  "
          f"PnL={sub.pnl_pct.median():>+6.2f}%  盘中触止损={sub.hit_stop_intraday.mean()*100:>4.1f}%  "
          f"大胜率={(sub.exit_reason=='大胜利').mean()*100:>4.1f}%")

print("\n完成。")
