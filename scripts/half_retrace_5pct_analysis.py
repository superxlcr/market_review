"""
分析回调一半严格 vs 严格5% — 为什么5%过滤反而更差
"""
import csv, os
from collections import defaultdict

BASE = ".winrate_data/20260715_095337"

def load(bp):
    trades = []
    path = os.path.join(BASE, f"{bp}.csv")
    with open(path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            trades.append(row)
    return trades

strict = load("回调一半严格")
strict5 = load("回调一半严格5%")

# ── 1. 被5%过滤掉的207个信号的详细分析 ──
strict_codes = {(t["code"], t["signal_date"]) for t in strict}
strict5_codes = {(t["code"], t["signal_date"]) for t in strict5}
filtered_codes = strict_codes - strict5_codes

filtered_out = [t for t in strict if (t["code"], t["signal_date"]) in filtered_codes]
kept = [t for t in strict if (t["code"], t["signal_date"]) not in filtered_codes]

print("=" * 60)
print("一、5%过滤砍掉的207个信号表现")
print("=" * 60)
n = len(filtered_out)
wins = sum(1 for t in filtered_out if t["success"] == "True")
big = sum(1 for t in filtered_out if t["exit_reason"] == "大胜利")
small = sum(1 for t in filtered_out if t["exit_reason"] == "小胜利")
stop = sum(1 for t in filtered_out if t["exit_reason"] == "盘中止损")
loss = sum(1 for t in filtered_out if t["exit_reason"] in ("收盘止损", "时间止损"))
pnl = sum(float(t["pnl_pct"]) for t in filtered_out) / n
hold = sum(int(t["hold_days"]) for t in filtered_out) / n

print(f"N={n}, WR={wins/n*100:.1f}%")
print(f"大胜利={big}, 小胜利={small}, 止损={stop}, 其他亏损={loss}")
print(f"期望={pnl:.1f}%, 平均持仓={hold:.1f}天")

# 跟保留的1646个对比
n2 = len(kept)
wins2 = sum(1 for t in kept if t["success"] == "True")
pnl2 = sum(float(t["pnl_pct"]) for t in kept) / n2
print(f"\n保留的1646个: WR={wins2/n2*100:.1f}%, 期望={pnl2:.1f}%")

print()

# ── 2. 被过滤信号的 PnL 分布 ──
print("=" * 60)
print("二、被过滤信号的 PnL 分布")
print("=" * 60)
pnls = sorted([float(t["pnl_pct"]) for t in filtered_out])
print(f"Min={pnls[0]:.1f}%, P25={pnls[n//4]:.1f}%, Median={pnls[n//2]:.1f}%, P75={pnls[3*n//4]:.1f}%, Max={pnls[-1]:.1f}%")

# PnL bucket
buckets = defaultdict(lambda: {"n":0, "wins":0, "pnl_sum":0.0})
for t in filtered_out:
    p = float(t["pnl_pct"])
    if p <= -5: bk = "<= -5%"
    elif p <= -3: bk = "-5~-3%"
    elif p <= 0: bk = "-3~0%"
    elif p <= 3: bk = "0~3%"
    elif p <= 5: bk = "3~5%"
    elif p <= 10: bk = "5~10%"
    else: bk = ">10%"
    buckets[bk]["n"] += 1
    if t["success"] == "True":
        buckets[bk]["wins"] += 1
    buckets[bk]["pnl_sum"] += p

for bk in ["<= -5%", "-5~-3%", "-3~0%", "0~3%", "3~5%", "5~10%", ">10%"]:
    b = buckets[bk]
    if b["n"] == 0: continue
    print(f"  {bk:>8s}: N={b['n']:>3d}, WR={b['wins']/b['n']*100:.1f}%, avgPnL={b['pnl_sum']/b['n']:.1f}%")

print()

# ── 3. 退出原因分布对比 ──
print("=" * 60)
print("三、退出原因分布")
print("=" * 60)
for label, trades in [("回调一半严格(全)", strict), ("  被过滤的207", filtered_out), ("  保留的1639", kept)]:
    n = len(trades)
    reasons = defaultdict(int)
    for t in trades:
        reasons[t["exit_reason"]] += 1
    print(f"\n{label}:")
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {r}: {c} ({c/n*100:.1f}%)")

print()

# ── 4. 短期均线状态维度 ──
print("=" * 60)
print("四、short_ma_state 维度")
print("=" * 60)
for label, trades in [("被过滤的207", filtered_out), ("保留的1639", kept)]:
    n = len(trades)
    sma = defaultdict(list)
    for t in trades:
        sma[t["short_ma_state"]].append(float(t["pnl_pct"]))
    print(f"\n{label}: N={n}")
    for s, plist in sorted(sma.items()):
        w = sum(1 for p in plist if p > 0)
        print(f"  {s}: N={len(plist)}, WR={w/len(plist)*100:.1f}%, avgPnL={sum(plist)/len(plist):.1f}%")

print()

# ── 5. 长期均线状态维度 ──
print("=" * 60)
print("五、long_ma_state 维度")
print("=" * 60)
for label, trades in [("被过滤的207", filtered_out), ("保留的1639", kept)]:
    n = len(trades)
    lma = defaultdict(list)
    for t in trades:
        lma[t["long_ma_state"]].append(float(t["pnl_pct"]))
    print(f"\n{label}:")
    for s, plist in sorted(lma.items()):
        w = sum(1 for p in plist if p > 0)
        print(f"  {s}: N={len(plist)}, WR={w/len(plist)*100:.1f}%, avgPnL={sum(plist)/len(plist):.1f}%")

print()

# ── 6. 市值维度 ──
print("=" * 60)
print("六、市值桶维度")
print("=" * 60)
for label, trades in [("被过滤的207", filtered_out), ("保留的1639", kept)]:
    cb = defaultdict(list)
    for t in trades:
        cb[t["cap_bucket"]].append(float(t["pnl_pct"]))
    print(f"\n{label}:")
    for s, plist in sorted(cb.items()):
        w = sum(1 for p in plist if p > 0)
        print(f"  {s}: N={len(plist)}, WR={w/len(plist)*100:.1f}%, avgPnL={sum(plist)/len(plist):.1f}%")
