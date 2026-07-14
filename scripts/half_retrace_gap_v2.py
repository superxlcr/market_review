#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回调一半 × 跳空高开 V2 — 区分追高买入 vs 正常target成交。
用法: .venv/Scripts/python scripts/half_retrace_gap_v2.py
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

def load_csv(bp: str) -> pd.DataFrame:
    f = f"{DATA}/{bp}.csv"
    if not os.path.exists(f):
        return pd.DataFrame()
    df = pd.read_csv(f, encoding="utf-8-sig")
    df["sd"] = df["signal_date"].astype(str)
    df["ed"] = df["entry_date"].astype(str)
    return df

half = load_csv("回调一半")
half_strict = load_csv("回调一半严格")

# ── 从 DB 获取 entry_date 的 OHLC ──
db = sqlite3.connect(DB)
print("Loading OHLC from DB...")
# Build a dict: (code, date) -> (open, close)
needed = set()
for g in [half, half_strict]:
    for _, r in g.iterrows():
        needed.add((r.code, r.sd))
        needed.add((r.code, r.ed))

codes = list(set(p[0] for p in needed))
min_date = min(p[1] for p in needed)
max_date = max(p[1] for p in needed)

ohlc = {}
BATCH = 500
for i in range(0, len(codes), BATCH):
    batch = codes[i:i+BATCH]
    ph = ",".join(["?"]*len(batch))
    cur = db.execute(f"""
        SELECT code, date, open, high, low, close
        FROM tushare_cache WHERE code IN ({ph}) AND date >= ? AND date <= ?
    """, batch + [min_date, max_date])
    for row in cur:
        ohlc[(row[0], str(row[1]))] = {"open": row[2], "high": row[3], "low": row[4], "close": row[5]}
db.close()
print(f"  {len(ohlc)} rows loaded.\n")

# ── 分析函数 ──
def analyze_gap(g, label):
    """进场机制分类：
    - 追高买入: entry_price ≈ entry_day.open (open > target 但在2%内)
    - 正常买入: entry_price ≠ entry_day.open (target 在日内范围)
    """
    g = g.copy()
    rows = []
    for _, r in g.iterrows():
        sig = ohlc.get((r.code, r.sd))
        ent = ohlc.get((r.code, r.ed))
        if not sig or not ent:
            continue
        sig_close = sig["close"]
        ent_open = ent["open"]
        ent_high = ent["high"]
        ent_low = ent["low"]
        ep = r.entry_price

        # 追高判定: entry_price 等于 ent_open（经过 open_chase）
        is_chase = abs(ep - ent_open) < 0.005
        # 正常买入: target 在日内范围
        is_normal = not is_chase and ent_low <= ep <= ent_high

        # gap: 次日开盘 vs 信号日收盘
        gap_vs_close = (ent_open - sig_close) / sig_close * 100 if sig_close > 0 else 0
        # 对于追高买入: 追高幅度 = (ep - target) / target, target 不知道
        # 但 entry_price = open, 所以 open vs sig_close 包含了 target_vs_close + chase
        # 下限估计: target 至少 = open / 1.02, 所以 chase 最多 2%

        rows.append({
            "is_chase": is_chase,
            "is_normal": is_normal,
            "gap_open_vs_close": round(gap_vs_close, 2),
            "ep": ep, "ent_open": ent_open,
            "code": r.code, "sd": r.sd, "ed": r.ed,
            "success": r.success, "mfp_pct": r.mfp_pct,
            "pnl_pct": r.pnl_pct, "exit_reason": r.exit_reason,
            "hold_days": r.hold_days,
            "long_ma_state": r.long_ma_state,
            "short_ma_state": r.short_ma_state,
            "wave33_direction": r.wave33_direction,
            "wave33_streak": r.wave33_streak,
            "industry_l1": r.industry_l1,
            "cap_bucket": r.cap_bucket,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    base = df.success.mean()
    n_chase = df.is_chase.sum()
    n_normal = df.is_normal.sum()
    # 无法判断的（既不是追高也不是正常——应该极少或没有）
    n_other = len(df) - n_chase - n_normal

    print(f"\n{'='*70}")
    print(f"  {label} (基线 {base*100:.1f}%, n={len(df)})")
    print(f"{'='*70}")
    print(f"  追高买入(entry=open): {n_chase}笔 ({n_chase/len(df)*100:.1f}%)")
    print(f"  正常买入(entry=target): {n_normal}笔 ({n_normal/len(df)*100:.1f}%)")
    if n_other > 0:
        print(f"  其他(无法判定): {n_other}笔")

    # ── 核心对比：追高 vs 正常 ──
    print(f"\n  ╔══════════════════════════════════════════════════╗")
    print(f"  ║  追高买入 vs 正常买入 — 胜率·赔率·持有期        ║")
    print(f"  ╚══════════════════════════════════════════════════╝")

    for name, sub in [("追高买入(entry=open)", df[df.is_chase]),
                       ("正常买入(entry=target)", df[df.is_normal])]:
        if len(sub) == 0:
            continue
        print(f"\n  [{name}] n={len(sub)}")
        print(f"    胜率:        {sub.success.mean()*100:>5.1f}%  (基线{base*100:.1f}%, "
              f"抬升{(sub.success.mean()-base)*100:+.1f}pp)")
        print(f"    MFP均值:     {sub.mfp_pct.mean():>5.2f}%")
        print(f"    盈亏均值:    {sub.pnl_pct.mean():>+5.2f}%")
        print(f"    盈亏中位:    {sub.pnl_pct.median():>+5.2f}%")
        print(f"    大胜利:      {(sub.exit_reason=='大胜利').mean()*100:>5.1f}%")
        print(f"    盘中止损:    {(sub.exit_reason=='盘中止损').mean()*100:>5.1f}%")
        print(f"    收盘止损:    {(sub.exit_reason=='收盘止损').mean()*100:>5.1f}%")
        print(f"    平均持有天:  {sub.hold_days.mean():>5.1f}天")

    # ── 追高买入中：按 gap_open_vs_close 细分 ──
    chase = df[df.is_chase]
    if len(chase) >= 10:
        print(f"\n  ── 追高买入 按 gap(open/sig_close-1) 细分 ──")
        for lo, hi in [(0, 1), (1, 2), (2, 3), (3, 5), (5, 10)]:
            sub = chase[(chase.gap_open_vs_close > lo) & (chase.gap_open_vs_close <= hi)]
            if len(sub) >= 5:
                print(f"    gap {lo}-{hi}%: n={len(sub):>4d}  胜率={sub.success.mean()*100:>5.1f}%  "
                      f"抬升={(sub.success.mean()-base)*100:>+.0f}pp  "
                      f"MFP={sub.mfp_pct.mean():.2f}%  盈亏中位={sub.pnl_pct.median():>+.2f}%")

    # ── 追高 × 维度 ──
    if len(chase) >= 30:
        print(f"\n  ── 追高买入 × 维度交叉 ──")
        for dim, vals in [("long_ma_state", ["多头","盘整","空头"]),
                          ("wave33_direction", ["up","down","flat"])]:
            print(f"    [{dim}]:")
            for v in vals:
                sub = chase[chase[dim] == v]
                if len(sub) >= 5:
                    print(f"      {v}: n={len(sub):>4d}  胜率={sub.success.mean()*100:>5.1f}%  "
                          f"抬升={(sub.success.mean()-base)*100:>+.0f}pp")

    # ── 正常买入中：按 open vs entry_price 关系 ──
    # 开盘高于 target（但没到触发追高——说明 target 可能 > open 但实际上...）
    # 等等：如果 o > target 但 o > cap_price, 那就不会成交
    # 所以正常买入一定是 o ≤ target 或者 target 在日内范围内
    normal = df[df.is_normal]
    normal["open_vs_entry"] = normal["ent_open"] - normal["ep"]
    # 开盘高于入场价（target）→ 开盘跳过了target，但后来跌回来了
    normal["open_above_target"] = normal["open_vs_entry"] > 0.01
    # 开盘低于入场价 → 开盘在target下方，后来涨上去了
    normal["open_below_target"] = normal["open_vs_entry"] < -0.01
    # 开盘≈入场价 → target ≈ open（微跳空但在范围内）

    print(f"\n  ── 正常买入中：开盘 vs target 关系 ──")
    for name2, cond in [("开盘>target(开盘跳过,后回落)", normal.open_above_target),
                          ("开盘≈target(开盘即target)", ~normal.open_above_target & ~normal.open_below_target),
                          ("开盘<target(开盘低于,后上涨)", normal.open_below_target)]:
        sub = normal[cond]
        if len(sub) >= 10:
            print(f"    {name2}: n={len(sub):>5d}  胜率={sub.success.mean()*100:>5.1f}%  "
                  f"抬升={(sub.success.mean()-base)*100:>+.0f}pp  MFP={sub.mfp_pct.mean():.2f}%")

    # ── 案例 ──
    print(f"\n  ── 追高买入案例 (2026年, PnL top/bottom 3) ──")
    chase_26 = chase[chase.sd.str.startswith("2026")]
    for _, r in chase_26.nlargest(3, "pnl_pct").iterrows():
        print(f"    ✅ {r.code} {r.sd}→{r.ed} open={r.ent_open} entry={r.ep} "
              f"gap={r.gap_open_vs_close:+.1f}% PnL={r.pnl_pct:+.2f}% {r.exit_reason}")
    for _, r in chase_26.nsmallest(3, "pnl_pct").iterrows():
        print(f"    ❌ {r.code} {r.sd}→{r.ed} open={r.ent_open} entry={r.ep} "
              f"gap={r.gap_open_vs_close:+.1f}% PnL={r.pnl_pct:+.2f}% {r.exit_reason}")

    return df

gap_half = analyze_gap(half, "回调一半 普通")
gap_half_strict = analyze_gap(half_strict, "回调一半 严格")

# ── 总结 ──
print(f"\n\n{'='*70}")
print("结论")
print(f"{'='*70}")

for g, label in [(gap_half, "普通"), (gap_half_strict, "严格")]:
    base = g.success.mean()
    chase = g[g.is_chase]
    normal = g[g.is_normal]
    print(f"\n  {label}: 追高 {len(chase)}笔 vs 正常 {len(normal)}笔")
    if len(chase) >= 10:
        print(f"    追高胜率={chase.success.mean()*100:.1f}% (+{(chase.success.mean()-base)*100:+.0f}pp)")
    print(f"    正常胜率={normal.success.mean()*100:.1f}% (+{(normal.success.mean()-base)*100:+.0f}pp)")
    print(f"    差异={(chase.success.mean()-normal.success.mean())*100:+.1f}pp")

print("\n完成。")
