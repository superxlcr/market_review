#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回调一半严格：收盘离target距离 → 次日盘中走势 → 胜率赔率。
验证：收盘太远时，是否容易出现"盘中大拉升然后回落"的止损模式。
用法: .venv/Scripts/python scripts/half_retrace_close_range.py
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
strict = pd.read_csv(f"{DATA}/回调一半严格.csv", encoding="utf-8-sig")
strict["sd"] = strict["signal_date"].astype(str)
strict["ed"] = strict["entry_date"].astype(str)
print(f"回调一半严格: {len(strict)} 笔")

# ── 从 DB 取 OHLC + adj_factor ──
db = sqlite3.connect(DB)
needed = set()
for _, r in strict.iterrows():
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
for _, r in strict.iterrows():
    sig = ohlc.get((r.code, r.sd))
    ent = ohlc.get((r.code, r.ed))
    if not sig or not ent:
        continue

    # QFQ 调整：统一到最新 adj_factor
    laf = latest_af.get(r.code, 1) or 1
    sig_af = sig["adj_factor"] or 1
    ent_af = ent["adj_factor"] or 1

    sig_close_qfq = sig["close"] * sig_af / laf
    sig_high_qfq = sig["high"] * sig_af / laf
    sig_low_qfq = sig["low"] * sig_af / laf
    ent_open_qfq = ent["open"] * ent_af / laf
    ent_high_qfq = ent["high"] * ent_af / laf
    ent_low_qfq = ent["low"] * ent_af / laf
    ent_close_qfq = ent["close"] * ent_af / laf

    ep = r.entry_price  # CSV 中已是 QFQ 调整后的

    # 信号日收盘离 target 距离
    close_to_target_pct = (sig_close_qfq - ep) / ep * 100

    # 信号日：收盘在日内什么位置
    sig_range = sig_high_qfq - sig_low_qfq
    sig_close_position = (sig_close_qfq - sig_low_qfq) / sig_range if sig_range > 0 else 0.5

    # 信号日上影线（high - max(open, close)）/ range
    sig_upper_shadow = (sig_high_qfq - max(sig["open"]*sig_af/laf, sig_close_qfq)) / sig_range if sig_range > 0 else 0

    # 入场日：盘中最高 vs 入场价
    ent_high_vs_entry = (ent_high_qfq - ep) / ep * 100
    # 入场日：收盘 vs 入场价（衡量"拉升后回落"程度）
    ent_close_vs_entry = (ent_close_qfq - ep) / ep * 100
    # 入场日回落幅度：如果盘中最高打到很高，但收盘很低 → 典型的"拉升后回落"
    ent_retrace_from_high = (ent_close_qfq - ent_high_qfq) / ent_high_qfq * 100 if ent_high_qfq > 0 else 0

    # 入场日：是否盘中触发止损（low 跌破止损位）
    stop_price = ep * 0.95
    hit_stop_intraday = 1 if ent_low_qfq <= stop_price else 0

    # 入场日上影线
    ent_range = ent_high_qfq - ent_low_qfq
    ent_upper_shadow = (ent_high_qfq - max(ent_open_qfq, ent_close_qfq)) / ent_range if ent_range > 0 else 0

    rows.append({
        "code": r.code, "sd": r.sd, "ed": r.ed,
        "ep": ep,
        "sig_close_qfq": sig_close_qfq,
        "sig_high_qfq": sig_high_qfq,
        "sig_close_position": sig_close_position,
        "sig_upper_shadow": sig_upper_shadow,
        "close_to_target_pct": round(close_to_target_pct, 2),
        "ent_open_qfq": ent_open_qfq,
        "ent_high_qfq": ent_high_qfq,
        "ent_high_vs_entry": round(ent_high_vs_entry, 2),
        "ent_close_vs_entry": round(ent_close_vs_entry, 2),
        "ent_retrace_from_high": round(ent_retrace_from_high, 2),
        "ent_upper_shadow": ent_upper_shadow,
        "hit_stop_intraday": hit_stop_intraday,
        "success": r.success, "mfp_pct": r.mfp_pct,
        "pnl_pct": r.pnl_pct, "exit_reason": r.exit_reason,
        "hold_days": r.hold_days,
        "long_ma_state": r.long_ma_state,
        "gap_open_vs_close": round((ent_open_qfq - sig_close_qfq) / sig_close_qfq * 100, 2),
    })

df = pd.DataFrame(rows)
base = df.success.mean()
print(f"有效样本: {len(df)} (基线胜率 {base*100:.1f}%)\n")

# ═══════════════════════════════════════════════════════════════
# 1. 收盘距 target 分桶 → 入场日盘中行为
# ═══════════════════════════════════════════════════════════════
print("=" * 90)
print("Part 1: 信号日收盘距 target → 入场日盘中行为")
print("=" * 90)

bins = [(-100, -4, "<-4%（很远下方）"), (-4, -2, "-4~-2%"),
        (-2, -1, "-2~-1%"), (-1, -0.5, "-1~-0.5%"),
        (-0.5, 0.5, "±0.5%（≈target）"),
        (0.5, 1, "0.5~1%"), (1, 2, "1~2%"), (2, 100, ">2%（上方）")]

print(f"\n{'区间':<20s} {'n':>5s} {'胜率':>6s} {'盈亏中位':>8s} {'入场日最高':>10s} {'入场日收盘':>10s} {'高位回落':>8s} {'盘中触止损':>10s} {'止损时亏损':>10s} {'信号日上影':>10s}")
print("-" * 110)

for lo, hi, label in bins:
    sub = df[(df.close_to_target_pct > lo) & (df.close_to_target_pct <= hi)]
    if len(sub) < 10:
        continue
    stopped = sub[sub.exit_reason.isin(["盘中止损", "收盘止损"])]
    stop_pnl = stopped.pnl_pct.median() if len(stopped) > 0 else float('nan')
    print(f"{label:<20s} {len(sub):>5d} {sub.success.mean()*100:>5.1f}% "
          f"{sub.pnl_pct.median():>+7.2f}% {sub.ent_high_vs_entry.median():>+9.2f}% "
          f"{sub.ent_close_vs_entry.median():>+9.2f}% {sub.ent_retrace_from_high.median():>+7.2f}% "
          f"{sub.hit_stop_intraday.mean()*100:>9.1f}% {stop_pnl:>+9.2f}% "
          f"{sub.sig_upper_shadow.median():>9.1%}")

# ═══════════════════════════════════════════════════════════════
# 2. 收盘距 target × 入场日拉升幅度 交叉
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("Part 2: 关键交叉 — 收盘远+入场日大幅拉升 → 是否必然回落？")
print("=" * 90)

# 入场日拉升幅度分桶
df["ent_surge"] = pd.cut(df.ent_high_vs_entry,
    bins=[-100, 0, 1, 2, 3, 5, 100],
    labels=["无拉升(≤0%)","微升(0-1%)","小升(1-2%)","中升(2-3%)","大升(3-5%)","巨升(>5%)"])

# 收盘距离分桶
df["close_dist"] = pd.cut(df.close_to_target_pct,
    bins=[-100, -4, -2, -0.5, 0.5, 2, 100],
    labels=["远下方<-4%","下方-4~-2%","近下方-2~-0.5%","≈target±0.5%","上方0.5~2%","远上方>2%"])

print(f"\n{'收盘位置':<18s} {'入场拉升':<14s} {'n':>5s} {'胜率':>6s} {'盈亏中位':>8s} {'高位回落':>8s} {'盘中触止损':>10s}")
print("-" * 85)

for cd in ["远下方<-4%", "下方-4~-2%", "近下方-2~-0.5%", "≈target±0.5%"]:
    for es in ["无拉升(≤0%)","微升(0-1%)","小升(1-2%)","中升(2-3%)","大升(3-5%)","巨升(>5%)"]:
        sub = df[(df.close_dist == cd) & (df.ent_surge == es)]
        if len(sub) < 10:
            continue
        print(f"{cd:<18s} {es:<14s} {len(sub):>5d} {sub.success.mean()*100:>5.1f}% "
              f"{sub.pnl_pct.median():>+7.2f}% {sub.ent_retrace_from_high.median():>+7.2f}% "
              f"{sub.hit_stop_intraday.mean()*100:>9.1f}%")

# ═══════════════════════════════════════════════════════════════
# 3. 信号日收盘位置（在日内高低的什么地方）
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("Part 3: 信号日收盘在日内位置 → 对次日的影响")
print("=" * 90)

# close_position: 0=收在最低, 1=收在最高
df["sig_close_pos_bin"] = pd.cut(df.sig_close_position,
    bins=[0, 0.2, 0.4, 0.6, 0.8, 1.01],
    labels=["底部(0-20%)","中低(20-40%)","中部(40-60%)","中高(60-80%)","顶部(80-100%)"])

print(f"\n信号日收在日内{'位置':<18s} {'n':>5s} {'胜率':>6s} {'盈亏中位':>8s} {'入场日高vs入场价':>12s} {'高位回落':>8s}")

for pos in ["底部(0-20%)","中低(20-40%)","中部(40-60%)","中高(60-80%)","顶部(80-100%)"]:
    sub = df[df.sig_close_pos_bin == pos]
    if len(sub) < 10:
        continue
    print(f"  {pos:<18s} {len(sub):>5d} {sub.success.mean()*100:>5.1f}% "
          f"{sub.pnl_pct.median():>+7.2f}% {sub.ent_high_vs_entry.median():>+11.2f}% "
          f"{sub.ent_retrace_from_high.median():>+7.2f}%")

# ═══════════════════════════════════════════════════════════════
# 4. 最优范围：综合胜率+赔率+信号量
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("Part 4: 范围建议 — 综合胜率·赔率·止损成本·信号量")
print("=" * 90)

# 用更细的桶来画"性价比曲线"
print(f"\n{'收盘距target':<16s} {'n':>5s} {'n占比':>6s} {'胜率':>6s} {'抬升':>6s} {'PnL中位':>8s} {'止损PnL':>8s} {'大胜%':>6s} {'评分':>6s}")
print("-" * 90)

ranges = [
    (-100, -6, "<-6%"),
    (-6, -4, "-6~-4%"),
    (-4, -3, "-4~-3%"),
    (-3, -2, "-3~-2%"),
    (-2, -1.5, "-2~-1.5%"),
    (-1.5, -1, "-1.5~-1%"),
    (-1, -0.5, "-1~-0.5%"),
    (-0.5, 0, "-0.5~0%"),
    (0, 0.5, "0~0.5%"),
    (0.5, 1, "0.5~1%"),
    (1, 1.5, "1~1.5%"),
    (1.5, 2, "1.5~2%"),
    (2, 3, "2~3%"),
    (3, 100, ">3%"),
]

for lo, hi, label in ranges:
    sub = df[(df.close_to_target_pct > lo) & (df.close_to_target_pct <= hi)]
    if len(sub) < 15:
        continue
    stopped = sub[sub.exit_reason.isin(["盘中止损", "收盘止损"])]
    stop_pnl = stopped.pnl_pct.median() if len(stopped) > 0 else 0
    # 评分 = 抬升pp - |止损PnL|/2（止损越疼扣分越多）
    lift = (sub.success.mean() - base) * 100
    score = lift - abs(stop_pnl) * 10  # 止损每多亏1%扣10分
    # 更简单的评分：PnL中位为正就加分
    simple_score = sub.pnl_pct.median()
    print(f"{label:<16s} {len(sub):>5d} {len(sub)/len(df)*100:>5.1f}% "
          f"{sub.success.mean()*100:>5.1f}% {lift:>+5.1f}pp "
          f"{sub.pnl_pct.median():>+7.2f}% {stop_pnl:>+7.2f}% "
          f"{(sub.exit_reason=='大胜利').mean()*100:>5.1f}% "
          f"{simple_score:>+6.2f}%")

# ═══════════════════════════════════════════════════════════════
# 5. 叠加高开
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("Part 5: 收盘范围 × 次日高开 → 叠加效果")
print("=" * 90)

df["gap_bin"] = pd.cut(df.gap_open_vs_close,
    bins=[-100, 0, 1, 2, 100],
    labels=["无高开(≤0%)","微高开(0-1%)","高开(1-2%)","强高开(>2%)"])

print(f"\n{'收盘距target':<16s} {'高开':<14s} {'n':>5s} {'胜率':>6s} {'PnL中位':>8s} {'高位回落':>8s} {'盘中触止损':>10s}")
print("-" * 85)

for cd_label, cd_lo, cd_hi in [("近下方-2~0%", -2, 0), ("±0.5%", -0.5, 0.5),
                                 ("下方-4~-2%", -4, -2), ("下方<-4%", -100, -4)]:
    cd_sub = df[(df.close_to_target_pct > cd_lo) & (df.close_to_target_pct <= cd_hi)]
    for gb in ["无高开(≤0%)","微高开(0-1%)","高开(1-2%)","强高开(>2%)"]:
        sub = cd_sub[cd_sub.gap_bin == gb]
        if len(sub) < 10:
            continue
        lift = (sub.success.mean() - base) * 100
        print(f"{cd_label:<16s} {gb:<14s} {len(sub):>5d} {sub.success.mean()*100:>5.1f}% "
              f"{sub.pnl_pct.median():>+7.2f}% {sub.ent_retrace_from_high.median():>+7.2f}% "
              f"{sub.hit_stop_intraday.mean()*100:>9.1f}%")

print("\n完成。")
