#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回调一半严格 <-4% 信号：如果 T+1 不挂条件单，后续是否有回踩上车机会？
用法: .venv/Scripts/python scripts/half_retrace_second_chance.py
"""
from __future__ import annotations
import io, os, sys, sqlite3
import pandas as pd
import numpy as np

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

pd.set_option("display.width", 320)
pd.set_option("display.max_columns", 60)

DATA = ".winrate_data/20260714_171048"
DB = "data/marketreview.db"

# ── 加载信号 ──
strict = pd.read_csv(f"{DATA}/回调一半严格.csv", encoding="utf-8-sig")
strict["sd"] = strict["signal_date"].astype(str)
strict["ed"] = strict["entry_date"].astype(str)
print(f"回调一半严格: {len(strict)} 笔")

# ── 获取最新 adj_factor ──
db = sqlite3.connect(DB)
needed = set()
for _, r in strict.iterrows():
    needed.add((r.code, r.sd))
codes = list(set(p[0] for p in needed))

latest_af = {}
for i in range(0, len(codes), 500):
    batch = codes[i:i+500]
    ph = ",".join(["?"]*len(batch))
    cur = db.execute(f"SELECT code, MAX(date) FROM tushare_cache WHERE code IN ({ph}) GROUP BY code", batch)
    for code, md in cur.fetchall():
        r2 = db.execute("SELECT adj_factor FROM tushare_cache WHERE code=? AND date=?", [code, md]).fetchone()
        if r2:
            latest_af[code] = r2[0]

# ── 获取信号日 close ──
sig_close_map = {}
for i in range(0, len(codes), 500):
    batch = codes[i:i+500]
    ph = ",".join(["?"]*len(batch))
    cur = db.execute(f"SELECT code, date, close, adj_factor FROM tushare_cache WHERE code IN ({ph})", batch)
    for row in cur:
        sig_close_map[(row[0], str(row[1]))] = {"close": row[2], "af": row[3]}

# ── 批量获取后续K线（信号日后 1~20 天）──
# 先确定需要的日期范围
all_dates = set()
for _, r in strict.iterrows():
    all_dates.add(r.sd)

min_sd = min(all_dates)
# 最晚信号日 + 20天
max_sd = max(all_dates)
# 需要拉到 max_sd + 20 天

# 取所有相关股票的完整K线序列
print("Loading full kline data for all codes...")
kline_data = {}  # code -> list of {date, open, high, low, close, adj_factor}
for i in range(0, len(codes), 300):
    batch = codes[i:i+300]
    ph = ",".join(["?"]*len(batch))
    cur = db.execute(f"""
        SELECT code, date, open, high, low, close, adj_factor
        FROM tushare_cache WHERE code IN ({ph}) AND date >= ?
        ORDER BY code, date
    """, batch + [min_sd])
    for row in cur:
        code = row[0]
        if code not in kline_data:
            kline_data[code] = []
        kline_data[code].append({
            "date": str(row[1]), "open": row[2], "high": row[3],
            "low": row[4], "close": row[5], "adj_factor": row[6]
        })
db.close()
print(f"  {len(kline_data)} stocks loaded, total {sum(len(v) for v in kline_data.values())} klines")

# ── 筛选 <-4% 信号 ──
far_below = []
for _, r in strict.iterrows():
    sig = sig_close_map.get((r.code, r.sd))
    if not sig:
        continue
    laf = latest_af.get(r.code, 1) or 1
    sig_af = sig["af"] or 1
    sc = sig["close"] * sig_af / laf
    ep = r.entry_price
    dist_pct = (sc - ep) / ep * 100
    if dist_pct < -4:
        far_below.append({**r.to_dict(), "sig_close_qfq": sc, "dist_pct": dist_pct})

print(f"\n<-4% 信号: {len(far_below)} 笔")

# ── 分析：如果不挂条件单，后续是否有回踩上车机会 ──
# 对于每笔信号，从 T+1（原entry_date）开始往后看最多20天
# 条件：日内最低价 low ≤ target(entry_price)，即盘中能成交
# 只要有一天满足，就算"有二次机会"

results = []
for fb in far_below:
    code = fb["code"]
    target = fb["entry_price"]
    sd = fb["sd"]
    ed = fb["ed"]  # 原定 entry_date

    kl = kline_data.get(code, [])
    if not kl:
        continue

    # 找到信号日在K线序列中的位置
    sig_idx = None
    for j, k in enumerate(kl):
        if k["date"] == sd:
            sig_idx = j
            break
    if sig_idx is None:
        continue

    # 从 T+1（原ed）开始往后看
    # 先找 entry_date 的位置
    entry_idx = None
    for j in range(sig_idx + 1, len(kl)):
        if kl[j]["date"] == ed:
            entry_idx = j
            break
    if entry_idx is None:
        continue

    # 从 T+2 开始往后看 20 天
    # entry_idx = T+1（原入场日），我们决定跳过不挂条件单
    # 所以从 entry_idx+1 = T+2 开始看回踩

    second_chance_day = None
    second_chance_idx = None
    min_low_vs_target = float('inf')  # 期间最低价 vs target

    # 先看 T+1 当天（原入场日）的最低价（用于统计）
    k0 = kl[entry_idx]
    laf = latest_af.get(code, 1) or 1
    kaf0 = k0["adj_factor"] or 1
    t1_low = k0["low"] * kaf0 / laf
    min_low_vs_target = (t1_low - target) / target * 100

    # 从 T+2 开始看
    lookback_end = min(len(kl), entry_idx + 21)  # T+2 ~ T+20
    for j in range(entry_idx + 1, lookback_end):
        k = kl[j]
        # QFQ 调整
        laf = latest_af.get(code, 1) or 1
        kaf = k["adj_factor"] or 1
        lo = k["low"] * kaf / laf

        low_vs_target = (lo - target) / target * 100
        if low_vs_target < min_low_vs_target:
            min_low_vs_target = low_vs_target

        if lo <= target and second_chance_day is None:
            second_chance_day = k["date"]
            second_chance_idx = j

    # days_to_second: 从 T+1 算起，T+2=1天, T+3=2天...
    days_to_second = second_chance_idx - entry_idx if second_chance_idx is not None else None

    # 也看下如果在 second_chance 入场，后续表现（简化：只看是否高于target）
    # 这里不跑完整回测，只看有没有机会

    results.append({
        "code": code, "sd": sd, "ed": ed, "target": target,
        "dist_pct": fb["dist_pct"],
        "success": fb["success"], "pnl_pct": fb["pnl_pct"],
        "exit_reason": fb["exit_reason"],
        "mfp_pct": fb["mfp_pct"],
        "second_chance": second_chance_day is not None,
        "second_day": second_chance_day if second_chance_day else "",
        "days_to_second": days_to_second,
        "min_low_vs_target": round(min_low_vs_target, 2),
        "long_ma_state": fb.get("long_ma_state", ""),
    })

df = pd.DataFrame(results)
print(f"有效分析: {len(df)} 笔\n")

# ═══════════════════════════════════════════════════════════════
# 1. <-4% 信号的原始表现
# ═══════════════════════════════════════════════════════════════
print("=" * 80)
print("Part 1: <-4% 信号原始表现（就是之前那些）")
print("=" * 80)
print(f"  n={len(df)}  胜率={df.success.mean()*100:.1f}%  PnL中位={df.pnl_pct.median():+.2f}%")
for reason in ["大胜利","小胜利","盘中止损","收盘止损","时间止损"]:
    sub = df[df.exit_reason == reason]
    if len(sub) > 0:
        print(f"    {reason}: {len(sub)}笔 ({len(sub)/len(df)*100:.1f}%)")

# ═══════════════════════════════════════════════════════════════
# 2. 二次上车机会
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("Part 2: 不挂条件单 → 后续回踩 target 的机会")
print("=" * 80)

has_chance = df[df.second_chance]
no_chance = df[~df.second_chance]
print(f"\n  有二次机会（回踩到 target）: {len(has_chance)} 笔 ({len(has_chance)/len(df)*100:.1f}%)")
print(f"  无二次机会（20天内没回来）: {len(no_chance)} 笔 ({len(no_chance)/len(df)*100:.1f}%)")

if len(has_chance) > 0:
    print(f"\n  回踩时间分布（从原入场日 T+1 算起）:")
    for lo, hi, label in [(1, 1, "T+2(隔1天)"), (2, 2, "T+3(隔2天)"),
                           (3, 5, "T+4~6"), (5, 10, "T+6~11"), (10, 21, "T+11~21")]:
        sub = has_chance[(has_chance.days_to_second >= lo) & (has_chance.days_to_second <= hi)]
        print(f"    {label:<14s}: {len(sub):>4d} 笔 ({len(sub)/len(df)*100:>5.1f}%)  "
              f"[占二次机会的 {len(sub)/len(has_chance)*100:.1f}%]")

# ═══════════════════════════════════════════════════════════════
# 3. 有二次机会 vs 没有 × 原始胜负
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("Part 3: 有/无二次机会 与 原始交易结果的关系")
print("=" * 80)

for label, sub in [("有二次机会", has_chance), ("无二次机会", no_chance)]:
    print(f"\n  [{label}] n={len(sub)}")
    print(f"    原始胜率:   {sub.success.mean()*100:.1f}%")
    print(f"    原始PnL中位: {sub.pnl_pct.median():+.2f}%")
    print(f"    原始大胜%:   {(sub.exit_reason=='大胜利').mean()*100:.1f}%")
    print(f"    原始止损%:   {(sub.exit_reason.isin(['盘中止损','收盘止损'])).mean()*100:.1f}%")
    print(f"    期间最低 vs target: {sub.min_low_vs_target.median():+.2f}%")

# ═══════════════════════════════════════════════════════════════
# 4. 细分：回踩时机 × 原始结果
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("Part 4: 回踩天数 × 原始结果")
print("=" * 80)
print(f"\n{'回踩天数':<14s} {'n':>5s} {'原始胜率':>8s} {'原始PnL中位':>10s} {'原始大胜%':>8s} {'原始止损%':>8s}")
print("-" * 70)

# 没回踩的
print(f"{'无回踩':<14s} {len(no_chance):>5d} {no_chance.success.mean()*100:>7.1f}% "
      f"{no_chance.pnl_pct.median():>+9.2f}% {(no_chance.exit_reason=='大胜利').mean()*100:>7.1f}% "
      f"{(no_chance.exit_reason.isin(['盘中止损','收盘止损'])).mean()*100:>7.1f}%")

for lo, hi in [(0, 1), (1, 2), (2, 3), (3, 5), (5, 10), (10, 21)]:
    sub = has_chance[(has_chance.days_to_second >= lo) & (has_chance.days_to_second <= hi)]
    if len(sub) < 5:
        continue
    label = f"T+{lo}~{hi}"
    print(f"{label:<14s} {len(sub):>5d} {sub.success.mean()*100:>7.1f}% "
          f"{sub.pnl_pct.median():>+9.2f}% {(sub.exit_reason=='大胜利').mean()*100:>7.1f}% "
          f"{(sub.exit_reason.isin(['盘中止损','收盘止损'])).mean()*100:>7.1f}%")

# ═══════════════════════════════════════════════════════════════
# 5. 如果等回踩再上车，哪些能省下亏损？
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("Part 5: 策略对比")
print("=" * 80)

# 所有 <-4% 的信号
# 策略A: T+1 无脑挂条件单（当前回测）
# 策略B: T+1 不挂，等回踩到 target 再挂（但回踩当天也不知道第二天会不会继续跌）

# 先看：原始亏损的交易中，有多少有二次机会？
losers = df[~df.success]
losers_with_chance = losers[losers.second_chance]
print(f"\n  原始亏损交易: {len(losers)} 笔")
print(f"  其中有二次机会的: {len(losers_with_chance)} 笔 ({len(losers_with_chance)/len(losers)*100:.1f}%)")
print(f"    → 这些亏损如果能等回踩再进，可能避免或减轻亏损")

winners = df[df.success]
winners_no_chance = winners[~winners.second_chance]
print(f"\n  原始盈利交易: {len(winners)} 笔")
print(f"  其中无二次机会的: {len(winners_no_chance)} 笔 ({len(winners_no_chance)/len(winners)*100:.1f}%)")
print(f"    → 这些盈利如果不当天追就错过了")

# ═══════════════════════════════════════════════════════════════
# 6. 案例
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("Part 6: 典型案例")
print("=" * 80)

print(f"\n  [无二次机会 + 大胜利 — 错过就没了]")
sub = df[(~df.second_chance) & (df.exit_reason == "大胜利")]
for _, r in sub.head(5).iterrows():
    print(f"    {r.code} {r.sd} target={r.target:.2f} 收盘距={r.dist_pct:.1f}% "
          f"PnL={r.pnl_pct:+.2f}% {r.exit_reason}")

print(f"\n  [有二次机会 + 盘中止损 — 不追就能省下亏损]")
sub = df[(df.second_chance) & (df.exit_reason == "盘中止损")]
for _, r in sub.head(5).iterrows():
    print(f"    {r.code} {r.sd}→{r.ed} target={r.target:.2f} 收盘距={r.dist_pct:.1f}% "
          f"回踩={r.second_day} (T+{r.days_to_second}) PnL={r.pnl_pct:+.2f}%")

print(f"\n  [无二次机会 + 盘中止损 — 追了止损，不追也上不了车]")
sub = df[(~df.second_chance) & (df.exit_reason == "盘中止损")]
for _, r in sub.head(5).iterrows():
    print(f"    {r.code} {r.sd} target={r.target:.2f} 收盘距={r.dist_pct:.1f}% "
          f"PnL={r.pnl_pct:+.2f}% 最低vs目标={r.min_low_vs_target:+.1f}%")

print("\n完成。")
