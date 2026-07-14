#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""<-4% 信号：如果跳过 T+1，在回踩日（T+2+）重新入场，模拟结果。
用法: .venv/Scripts/python scripts/half_retrace_second_chance_sim.py
"""
from __future__ import annotations
import io, os, sys, sqlite3
import pandas as pd
import numpy as np

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, "src")

pd.set_option("display.width", 320)
pd.set_option("display.max_columns", 60)

DATA = ".winrate_data/20260714_171048"
DB = "data/marketreview.db"

# ── 加载 ──
strict = pd.read_csv(f"{DATA}/回调一半严格.csv", encoding="utf-8-sig")
strict["sd"] = strict["signal_date"].astype(str)
strict["ed"] = strict["entry_date"].astype(str)

# ── QFQ 准备 ──
db = sqlite3.connect(DB)
codes_all = list(set(strict.code))
latest_af = {}
for i in range(0, len(codes_all), 500):
    batch = codes_all[i:i+500]
    ph = ",".join(["?"]*len(batch))
    cur = db.execute(f"SELECT code, MAX(date) FROM tushare_cache WHERE code IN ({ph}) GROUP BY code", batch)
    for code, md in cur.fetchall():
        r2 = db.execute("SELECT adj_factor FROM tushare_cache WHERE code=? AND date=?", [code, md]).fetchone()
        if r2: latest_af[code] = r2[0]

sig_close_map = {}
for i in range(0, len(codes_all), 500):
    batch = codes_all[i:i+500]
    ph = ",".join(["?"]*len(batch))
    cur = db.execute(f"SELECT code, date, close, adj_factor FROM tushare_cache WHERE code IN ({ph})", batch)
    for row in cur:
        sig_close_map[(row[0], str(row[1]))] = {"close": row[2], "af": row[3]}

# ── 加载完整K线 ──
print("Loading kline data...")
kline_data = {}
for i in range(0, len(codes_all), 300):
    batch = codes_all[i:i+300]
    ph = ",".join(["?"]*len(batch))
    cur = db.execute(f"""
        SELECT code, date, open, high, low, close, adj_factor
        FROM tushare_cache WHERE code IN ({ph})
        ORDER BY code, date
    """, batch)
    for row in cur:
        code = row[0]
        if code not in kline_data:
            kline_data[code] = []
        kline_data[code].append({
            "date": str(row[1]), "open": row[2], "high": row[3],
            "low": row[4], "close": row[5], "adj_factor": row[6]
        })
db.close()
print(f"  {len(kline_data)} stocks, {sum(len(v) for v in kline_data.values())} klines\n")

# ── 筛选 <-4% 信号 ──
far_below = []
for _, r in strict.iterrows():
    sig = sig_close_map.get((r.code, r.sd))
    if not sig: continue
    laf = latest_af.get(r.code, 1) or 1
    saf = sig["af"] or 1
    sc = sig["close"] * saf / laf
    ep = r.entry_price
    dist = (sc - ep) / ep * 100
    if dist < -4:
        far_below.append({**r.to_dict(), "sig_close_qfq": sc, "dist_pct": dist})

print(f"<-4% 信号: {len(far_below)} 笔\n")

# ── 模拟函数（从 trade_sim 简化，可指定 entry_date）──
SPACE_STOP = 5.0
TIME_STOP = 20
WIN_THRESHOLD = 10.0
BIG_WIN = 20.0
SMALL_WIN = 5.0
CHASE_CAP = 102.0

def board_limit(code):
    c = code.split(".")[0]
    if c.startswith(("300","301","688")): return 0.20
    if c.startswith(("8","4")): return 0.30
    return 0.10

def simulate(code, target, signal_row_idx, kl):
    """从 signal_row_idx+1 开始尝试入场，跑完整交易。
    返回 dict 或 None。"""
    sig_row = kl[signal_row_idx]
    sig_close = sig_row["close"]

    # 涨跌停可达性
    limit = board_limit(code)
    if target < sig_close * (1-limit) or target > sig_close * (1+limit):
        return None

    entry_idx = signal_row_idx + 1
    if entry_idx >= len(kl):
        return None

    er = kl[entry_idx]
    o, h, l = er["open"], er["high"], er["low"]
    cap = target * CHASE_CAP / 100.0

    if o > target and o <= cap:
        ep = o
    elif l <= target <= h:
        ep = target
    else:
        return None  # 未成交

    stop_price = ep * (1 - SPACE_STOP / 100.0)
    big_price = ep * (1 + BIG_WIN / 100.0)
    small_price = ep * (1 + SMALL_WIN / 100.0)

    mfp = max(0.0, (h - ep) / ep * 100.0)
    armed = mfp >= WIN_THRESHOLD

    entry_date = kl[entry_idx]["date"]

    for i in range(entry_idx + 1, min(len(kl), entry_idx + 1 + TIME_STOP)):
        row = kl[i]
        oo, hh, ll, cc = row["open"], row["high"], row["low"], row["close"]

        if oo <= stop_price:
            return {"entry_date": entry_date, "exit_date": row["date"],
                    "entry_price": ep, "exit_price": oo,
                    "pnl": (oo-ep)/ep*100, "exit_reason": "盘中止损",
                    "mfp": mfp, "hold": i-entry_idx, "success": False}
        if oo >= big_price:
            return {"entry_date": entry_date, "exit_date": row["date"],
                    "entry_price": ep, "exit_price": oo,
                    "pnl": (oo-ep)/ep*100, "exit_reason": "大胜利",
                    "mfp": mfp, "hold": i-entry_idx, "success": True}
        if armed and oo <= small_price:
            return {"entry_date": entry_date, "exit_date": row["date"],
                    "entry_price": ep, "exit_price": oo,
                    "pnl": (oo-ep)/ep*100, "exit_reason": "小胜利",
                    "mfp": mfp, "hold": i-entry_idx, "success": True}

        cur = (hh - ep) / ep * 100.0
        if cur > mfp: mfp = cur
        if mfp >= WIN_THRESHOLD: armed = True

        if ll <= stop_price:
            return {"entry_date": entry_date, "exit_date": row["date"],
                    "entry_price": ep, "exit_price": stop_price,
                    "pnl": (stop_price-ep)/ep*100, "exit_reason": "盘中止损",
                    "mfp": mfp, "hold": i-entry_idx, "success": False}
        if hh >= big_price:
            return {"entry_date": entry_date, "exit_date": row["date"],
                    "entry_price": ep, "exit_price": big_price,
                    "pnl": (big_price-ep)/ep*100, "exit_reason": "大胜利",
                    "mfp": mfp, "hold": i-entry_idx, "success": True}
        if armed and ll <= small_price:
            return {"entry_date": entry_date, "exit_date": row["date"],
                    "entry_price": ep, "exit_price": small_price,
                    "pnl": (small_price-ep)/ep*100, "exit_reason": "小胜利",
                    "mfp": mfp, "hold": i-entry_idx, "success": True}

        hold_days = i - entry_idx
        if hold_days >= TIME_STOP:
            return {"entry_date": entry_date, "exit_date": row["date"],
                    "entry_price": ep, "exit_price": cc,
                    "pnl": (cc-ep)/ep*100, "exit_reason": "时间止损",
                    "mfp": mfp, "hold": hold_days, "success": False}
        if cc < ep:
            return {"entry_date": entry_date, "exit_date": row["date"],
                    "entry_price": ep, "exit_price": cc,
                    "pnl": (cc-ep)/ep*100, "exit_reason": "收盘止损",
                    "mfp": mfp, "hold": hold_days, "success": False}

    return None  # 数据不够

# ── 三种策略模拟 ──
# A: 原始 T+1 入场（从原信号日算）
# B: 在 T+2 回踩日入场（从 原entry_date 算）
# C: 在所有有回踩的<-4%中，等回踩再入场

results_a = []  # T+1 original entry
results_b = []  # T+2 second chance entry (for those that have it)
results_c = []  # Best available entry: T+2 if available, else skip

for fb in far_below:
    code = fb["code"]
    target = fb["entry_price"]
    sd = fb["sd"]

    kl = kline_data.get(code, [])
    if not kl: continue

    # QFQ 调整 K线
    laf = latest_af.get(code, 1) or 1
    kl_adj = []
    for k in kl:
        kaf = k["adj_factor"] or 1
        kl_adj.append({
            "date": k["date"],
            "open": k["open"] * kaf / laf,
            "high": k["high"] * kaf / laf,
            "low": k["low"] * kaf / laf,
            "close": k["close"] * kaf / laf,
        })

    # 找信号日索引
    sig_idx = next((j for j, k in enumerate(kl_adj) if k["date"] == sd), None)
    if sig_idx is None: continue

    # ── A: T+1 原始入场 ──
    res_a = simulate(code, target, sig_idx, kl_adj)
    if res_a:
        results_a.append({**fb, **res_a, "strategy": "A-T+1原始"})

    # ── B: 找 T+2 回踩日（原 entry_date 后第一个 low≤target 的交易日）──
    entry_idx = sig_idx + 1
    if entry_idx >= len(kl_adj): continue

    second_idx = None
    for j in range(entry_idx + 1, min(len(kl_adj), entry_idx + 21)):
        if kl_adj[j]["low"] <= target <= kl_adj[j]["high"]:
            second_idx = j
            break
        # 也接受：开盘直接跳过 target（chase）
        o2 = kl_adj[j]["open"]
        if o2 > target and o2 <= target * CHASE_CAP / 100.0:
            second_idx = j
            break

    if second_idx:
        # B: T+2 入场（从 second_idx-1 作为新信号日）
        res_b = simulate(code, target, second_idx - 1, kl_adj)
        if res_b:
            days_late = second_idx - entry_idx
            results_b.append({**fb, **res_b, "strategy": f"B-T+{days_late+1}回踩",
                              "days_late": days_late})
            results_c.append({**fb, **res_b, "strategy": "C-等回踩",
                              "days_late": days_late})

print(f"=" * 80)
print(f"策略A (T+1 原始): {len(results_a)} 笔")
print(f"策略B (T+2 回踩): {len(results_b)} 笔")
print(f"策略C (部分等):   {len(results_c)} 笔")
print()

# ── 对比 ──
for label, res in [("A: T+1 追进去", results_a),
                    ("B: 等回踩再入场", results_b),
                    ("C: 有回踩就等(跳过没回踩的)", results_c)]:
    if not res: continue
    df = pd.DataFrame(res)
    wr = df.success.mean()
    pnl_m = df.pnl.median()
    pnl_avg = df.pnl.mean()
    big = (df.exit_reason == "大胜利").mean()
    stop = (df.exit_reason.isin(["盘中止损", "收盘止损"])).mean()
    intraday_stop = (df.exit_reason == "盘中止损").mean()
    print(f"[{label}] n={len(df)}")
    print(f"  胜率={wr*100:.1f}%  PnL中位={pnl_m:+.2f}%  PnL均值={pnl_avg:+.2f}%")
    print(f"  大胜={big*100:.1f}%  止损={stop*100:.1f}%  (盘中={intraday_stop*100:.1f}%)")
    # 按 exit_reason 分布
    for reason in ["大胜利","小胜利","盘中止损","收盘止损","时间止损"]:
        n_r = (df.exit_reason == reason).sum()
        if n_r > 0:
            print(f"    {reason}: {n_r}笔 ({n_r/len(df)*100:.1f}%)")
    print()

# ── 配对对比：同一笔信号，A vs B ──
print("=" * 80)
print("配对对比：同一信号的 A vs B")
print("=" * 80)

# Build lookup for A
a_lookup = {(r["code"], r["sd"]): r for r in results_a}
paired = []
for rb in results_b:
    ra = a_lookup.get((rb["code"], rb["sd"]))
    if ra:
        paired.append({
            "code": rb["code"], "sd": rb["sd"],
            "a_success": ra["success"], "a_pnl": ra["pnl"], "a_exit": ra["exit_reason"],
            "b_success": rb["success"], "b_pnl": rb["pnl"], "b_exit": rb["exit_reason"],
            "days_late": rb.get("days_late", 0),
        })

if paired:
    pdf = pd.DataFrame(paired)
    # 四种情况
    a_win_b_win = ((pdf.a_success) & (pdf.b_success)).sum()
    a_win_b_lose = ((pdf.a_success) & (~pdf.b_success)).sum()
    a_lose_b_win = ((~pdf.a_success) & (pdf.b_success)).sum()
    a_lose_b_lose = ((~pdf.a_success) & (~pdf.b_success)).sum()
    total = len(pdf)

    print(f"\n  配对样本: {total} 笔")
    print(f"  T+1赢 → 回踩也赢:  {a_win_b_win:>5d} ({a_win_b_win/total*100:5.1f}%)")
    print(f"  T+1赢 → 回踩反输:  {a_win_b_lose:>5d} ({a_win_b_lose/total*100:5.1f}%)  ← 被回踩坑了")
    print(f"  T+1输 → 回踩翻身:  {a_lose_b_win:>5d} ({a_lose_b_win/total*100:5.1f}%)  ← 回踩救了")
    print(f"  T+1输 → 回踩也输:  {a_lose_b_lose:>5d} ({a_lose_b_lose/total*100:5.1f}%)")
    print(f"  T+1赢 → 回踩能赢:  {a_win_b_win/a_win_b_win+a_win_b_lose if (a_win_b_win+a_win_b_lose)>0 else 0*100:.0f}%（保留率）")
    print(f"  T+1输 → 回踩能翻:  {a_lose_b_win/(a_lose_b_win+a_lose_b_lose)*100 if (a_lose_b_win+a_lose_b_lose)>0 else 0:.0f}%（翻盘率）")

    # 按回踩天数细分
    print(f"\n  按回踩天数:")
    for d in sorted(pdf.days_late.unique()):
        sub = pdf[pdf.days_late == d]
        if len(sub) < 5: continue
        b_wr = sub.b_success.mean()
        a_wr = sub.a_success.mean()
        print(f"    T+{d+1}回踩: n={len(sub):>4d}  A胜率={a_wr*100:.1f}%  B胜率={b_wr*100:.1f}%  "
              f"B-A={b_wr-a_wr:+.1%}  B_PnL中位={sub.b_pnl.median():+.2f}%")

    # 翻盘案例
    print(f"\n  [回踩翻身案例: T+1输 → 回踩赢]")
    flips = pdf[(~pdf.a_success) & (pdf.b_success)]
    for _, r in flips.head(5).iterrows():
        print(f"    {r.code} {r.sd} T+1→{r.a_exit} PnL={r.a_pnl:+.2f}%  "
              f"等{r.days_late+1}天→{r.b_exit} PnL={r.b_pnl:+.2f}%")

    print(f"\n  [被回踩坑了案例: T+1赢 → 回踩输]")
    traps = pdf[(pdf.a_success) & (~pdf.b_success)]
    for _, r in traps.head(5).iterrows():
        print(f"    {r.code} {r.sd} T+1→{r.a_exit} PnL={r.a_pnl:+.2f}%  "
              f"等{r.days_late+1}天→{r.b_exit} PnL={r.b_pnl:+.2f}%")

print("\n完成。")
