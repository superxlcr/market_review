#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回调一半深度分析 — 严格 vs 不严格 / 维度过滤 / 均线共振。
用法: .venv/Scripts/python scripts/half_retrace_analysis.py
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

DATA_DIR = ".winrate_data"

def _resolve_dir(data_dir: str) -> str:
    if glob.glob(os.path.join(data_dir, "*.csv")):
        return data_dir
    subdirs = [d for d in glob.glob(os.path.join(data_dir, "*")) if os.path.isdir(d)]
    runs = sorted(d for d in subdirs if glob.glob(os.path.join(d, "*.csv")))
    return runs[-1] if runs else data_dir

def load_data(data_dir: str) -> pd.DataFrame:
    resolved = _resolve_dir(data_dir)
    files = sorted(glob.glob(os.path.join(resolved, "*.csv")))
    if not files:
        sys.exit(f"[错误] {data_dir} 下没有 CSV。")
    if resolved != data_dir:
        print(f"[run] {resolved}\n")
    dfs = []
    for f in files:
        if "scan_timing" in os.path.basename(f) or "scan_meta" in os.path.basename(f):
            continue
        df = pd.read_csv(f, encoding="utf-8-sig")
        if df.empty:
            continue
        dfs.append(df)
    df = pd.concat(dfs, ignore_index=True)
    df["sd"] = df["signal_date"].astype(str)
    return df

print("=" * 90)
print("回调一半深度分析")
print("=" * 90)

df_all = load_data(DATA_DIR)
df_all = df_all[df_all.buy_point.notna()].copy()

# ── 数据准备 ──
half = df_all[df_all.buy_point == "回调一半"].copy()
half_strict = df_all[df_all.buy_point == "回调一半严格"].copy()
both = df_all[df_all.buy_point.isin(["回调一半", "回调一半严格"])].copy()

print(f"回调一半: {len(half)} 笔")
print(f"回调一半严格: {len(half_strict)} 笔")
print(f"日期: {both.sd.min()} ~ {both.sd.max()}\n")

# ═══════════════════════════════════════════════════════════════
# Part 1: 严格 vs 不严格 全面对比
# ═══════════════════════════════════════════════════════════════
print("=" * 90)
print("① 严格 vs 不严格 — 胜率·频率·赔率·持有期 全对比")
print("=" * 90)

def describe(g, label):
    n = len(g)
    return {
        "买点": label,
        "n": n,
        "胜率": round(g.success.mean() * 100, 1),
        "平均持有天": round(g.hold_days.mean(), 1),
        "平均MFP": round(g.mfp_pct.mean(), 2),
        "平均盈亏": round(g.pnl_pct.mean(), 2),
        "盈亏中位数": round(g.pnl_pct.median(), 2),
        "大胜利%": round((g.exit_reason == "大胜利").mean() * 100, 1),
        "小胜利%": round((g.exit_reason == "小胜利").mean() * 100, 1),
        "盘中止损%": round((g.exit_reason == "盘中止损").mean() * 100, 1),
        "收盘止损%": round((g.exit_reason == "收盘止损").mean() * 100, 1),
        "时间止损%": round((g.exit_reason == "时间止损").mean() * 100, 1),
        "MFP≥20%": round((g.mfp_pct >= 20).mean() * 100, 1),
        "MFP≥30%": round((g.mfp_pct >= 30).mean() * 100, 1),
        "覆盖股票数": g.code.nunique(),
    }

rows = [describe(half, "回调一半"), describe(half_strict, "回调一半严格")]
comp = pd.DataFrame(rows).set_index("买点").T
print(comp.to_string())

# 信号触发频率（同一只股票，严格版少发了多少信号）
print(f"\n信号频率对比（同一批股票）:")
half_codes = set(half.code.unique())
strict_codes = set(half_strict.code.unique())
common = half_codes & strict_codes
print(f"  回调一半覆盖: {len(half_codes)} 只")
print(f"  回调一半严格覆盖: {len(strict_codes)} 只")
print(f"  共同覆盖: {len(common)} 只")

# 共同股票中，各自发了多少信号
if common:
    half_common = half[half.code.isin(common)]
    strict_common = half_strict[half_strict.code.isin(common)]
    print(f"  共同 {len(common)} 只股票中:")
    print(f"    回调一半: {len(half_common)} 个信号 (平均每只 {len(half_common)/len(common):.1f})")
    print(f"    严格版:   {len(strict_common)} 个信号 (平均每只 {len(strict_common)/len(common):.1f})")
    print(f"    严格版信号量 = 普通版 {len(strict_common)/len(half_common)*100:.0f}%")

# 重叠 (同一 code+signal_date 两版都触发)
half_sigs = set(zip(half.code, half.sd))
strict_sigs = set(zip(half_strict.code, half_strict.sd))
overlap = half_sigs & strict_sigs
only_half = half_sigs - strict_sigs
only_strict = strict_sigs - half_sigs
print(f"\n  两版都触发 (同日同标): {len(overlap)} 个")
print(f"  仅普通版触发: {len(only_half)} 个 (= 被严格版过滤掉的)")
print(f"  仅严格版触发: {len(only_strict)} 个")

# 关键：被严格版过滤掉的信号，胜率如何？
if only_half:
    only_half_df = half[half.apply(lambda r: (r.code, r.sd) in only_half, axis=1)]
    print(f"\n  ⚡ 被严格版过滤掉的信号 ({len(only_half_df)} 笔) 质量:")
    print(f"     胜率: {only_half_df.success.mean()*100:.1f}%")
    print(f"     平均MFP: {only_half_df.mfp_pct.mean():.2f}%")
    print(f"     平均盈亏: {only_half_df.pnl_pct.mean():.2f}%")
    print(f"     大胜利%: {(only_half_df.exit_reason=='大胜利').mean()*100:.1f}%")

# 两版同时触发的信号，各自表现
if overlap:
    overlap_half = half[half.apply(lambda r: (r.code, r.sd) in overlap, axis=1)]
    overlap_strict = half_strict[half_strict.apply(lambda r: (r.code, r.sd) in overlap, axis=1)]
    print(f"\n  两版同时触发的信号 ({len(overlap)} 笔) 各自表现:")
    print(f"    普通版胜率: {overlap_half.success.mean()*100:.1f}%  MFP: {overlap_half.mfp_pct.mean():.2f}%")
    print(f"    严格版胜率: {overlap_strict.success.mean()*100:.1f}%  MFP: {overlap_strict.mfp_pct.mean():.2f}%")
    print(f"    (同一信号, 差别来自进场价格不同——严格版对突破确认要求更高)")

# ═══════════════════════════════════════════════════════════════
# Part 2: 维度过滤 — 各维度对回调一半的抬升
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("② 维度过滤 — 严格 vs 普通 在各维度下的表现")
print("=" * 90)

DIMS = [
    ("industry_l1", "行业L1", 60),
    ("long_ma_state", "长均态", 30),
    ("cap_bucket", "市值档", 30),
    ("wave33_direction", "3浪3方向", 30),
]

for dim, dim_label, min_n in DIMS:
    print(f"\n── {dim_label} ──")
    rows2 = []
    for g, label in [(half, "普通"), (half_strict, "严格")]:
        base = g.success.mean()
        dv = g.groupby(dim).agg(n=("success","size"), wr=("success","mean"))
        for val, r in dv.iterrows():
            if r.n < min_n:
                continue
            rows2.append({
                "版本": label, "取值": str(val),
                "n": int(r.n), "胜率%": round(r.wr*100, 1),
                "抬升pp": round((r.wr-base)*100, 1),
            })
    t = pd.DataFrame(rows2)
    # 透视: 行=取值, 列=版本, 值=抬升pp
    if t.empty:
        continue
    pivot = t.pivot_table(index="取值", columns="版本", values="抬升pp", aggfunc="first")
    # 加 n 信息
    pivot_n = t.pivot_table(index="取值", columns="版本", values="n", aggfunc="first")
    for col in pivot.columns:
        pivot[col] = pivot[col].apply(lambda x: f"{x:+.0f}pp")
    for idx in pivot.index:
        for col in pivot.columns:
            n_val = pivot_n.loc[idx, col] if col in pivot_n.columns else 0
            if pd.notna(n_val):
                pivot.loc[idx, col] = f"{pivot.loc[idx, col]} (n={int(n_val)})"
    print(pivot.to_string())

# ═══════════════════════════════════════════════════════════════
# Part 3: 3浪3 深度（回调一半对趋势方向最敏感？）
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("③ 3浪3 深度 — 回调一半的趋势敏感度")
print("=" * 90)

for g, label in [(half, "普通"), (half_strict, "严格")]:
    base = g.success.mean()
    print(f"\n  {label} (基线 {base*100:.1f}%):")
    g2 = g.copy()
    g2["streak_bin"] = pd.cut(g2.wave33_streak, bins=[-1,0,2,5,100],
                               labels=["0天(拐点)", "1-2天", "3-5天", "6+天"])
    cross = g2.groupby(["wave33_direction", "streak_bin"], observed=False).agg(
        n=("success","size"), wr=("success","mean"))
    cross["抬升"] = ((cross.wr - base) * 100).round(1)
    cross["胜率%"] = (cross.wr * 100).round(1)
    for (d, s), r in cross.iterrows():
        if int(r.n) >= 20:
            flag = "✅" if r["抬升"] >= 2 else "❌" if r["抬升"] <= -2 else "  "
            print(f"    {flag} {d}_{str(s):<12s}  n={int(r.n):>5d}  胜率={r['胜率%']:>5.1f}%  抬升={r['抬升']:>+5.0f}pp")

# ═══════════════════════════════════════════════════════════════
# Part 4: 组合过滤 — 叠加条件推高胜率
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("④ 组合过滤 — 逐步叠加条件 (严格版)")
print("=" * 90)

g = half_strict.copy()
base = g.success.mean()
print(f"  基线: n={len(g)} 胜率={base*100:.1f}%")

# 找最优路径
MOMENTUM = ["电子", "通信", "计算机", "电力设备", "有色金属", "机械设备", "国防军工", "传媒"]

filters = [
    ("长均多头", g.long_ma_state == "多头"),
    ("动量行业", g.industry_l1.isin(MOMENTUM)),
    ("小盘中盘", g.cap_bucket.isin(["小盘", "中盘"])),
    ("3浪3下降", g.wave33_direction == "down"),
    ("3浪3连续1-5天", g.wave33_streak.between(1, 5)),
]

mask = pd.Series(True, index=g.index)
for label, cond in filters:
    new_mask = mask & cond
    sub = g[new_mask]
    if len(sub) >= 30:
        print(f"  +{label:<16s}  n={len(sub):>5d}  胜率={sub.success.mean()*100:>5.1f}%  "
              f"(vs基线{base*100:.1f}% +{(sub.success.mean()-base)*100:+.1f}pp)")
        mask = new_mask
    else:
        print(f"  +{label:<16s}  n={len(sub):>5d}  (样本不足,停止叠加)")

# ═══════════════════════════════════════════════════════════════
# Part 5: 均线共振
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("⑤ 均线共振 — 回调一半信号 + 同日MA支撑 = 更好还是更差？")
print("=" * 90)

MA_BPS = ["MA20支撑", "MA55支撑", "MA60支撑", "MA120支撑", "MA144支撑", "MA240支撑",
          "扣抵量均线支撑", "5日均量均线支撑", "无量均线支撑"]

# 找到同日同标有 MA 信号的回调一半
ma_sigs = set()
for bp in MA_BPS:
    sub = df_all[df_all.buy_point == bp]
    for _, r in sub.iterrows():
        ma_sigs.add((r.code, str(r.sd)))

for g, label in [(half, "普通"), (half_strict, "严格")]:
    base = g.success.mean()
    g2 = g.copy()
    g2["has_ma"] = g2.apply(lambda r: (r.code, r.sd) in ma_sigs, axis=1)

    with_ma = g2[g2.has_ma]
    without_ma = g2[~g2.has_ma]

    print(f"\n  {label} (基线 {base*100:.1f}%):")
    print(f"    有MA共振: n={len(with_ma):>5d}  胜率={with_ma.success.mean()*100:>5.1f}%  "
          f"抬升={((with_ma.success.mean()-base)*100):>+.0f}pp  MFP均值={with_ma.mfp_pct.mean():.2f}%")
    print(f"    无MA共振: n={len(without_ma):>5d}  胜率={without_ma.success.mean()*100:>5.1f}%  "
          f"抬升={((without_ma.success.mean()-base)*100):>+.0f}pp  MFP均值={without_ma.mfp_pct.mean():.2f}%")

    # 按 MA 周期细分
    print(f"    按共振MA周期细分:")
    for p in [20, 55, 60, 120, 144, 240]:
        period_sigs = set()
        for bp in MA_BPS:
            if str(p) in bp:
                sub = df_all[df_all.buy_point == bp]
                for _, r in sub.iterrows():
                    period_sigs.add((r.code, str(r.sd)))
        g2["has_ma_p"] = g2.apply(lambda r: (r.code, r.sd) in period_sigs, axis=1)
        sub = g2[g2.has_ma_p]
        if len(sub) >= 20:
            print(f"      MA{p}共振: n={len(sub):>5d}  胜率={sub.success.mean()*100:>5.1f}%  "
                  f"抬升={((sub.success.mean()-base)*100):>+.0f}pp")

    # MA 共振数量 vs 胜率 (优化：预建索引)
    print(f"    按共振MA条数:")
    # 预建 MA 信号索引: (code, sd) -> set of MA buy_points
    ma_index = {}
    for bp in MA_BPS:
        sub = df_all[df_all.buy_point == bp]
        for _, r in sub.iterrows():
            key = (r.code, str(r.sd))
            ma_index.setdefault(key, set()).add(bp)
    # 对每个 回调一半 信号，查 MA 索引
    def _count_ma(row):
        bps = ma_index.get((row.code, row.sd), set())
        return len(bps)
    g2["ma_resonance_count"] = g2.apply(_count_ma, axis=1)
    for cnt in sorted(g2.ma_resonance_count.unique()):
        sub = g2[g2.ma_resonance_count == cnt]
        if len(sub) >= 10:
            print(f"      {int(cnt)}条MA共振: n={len(sub):>5d}  胜率={sub.success.mean()*100:>5.1f}%  "
                  f"抬升={((sub.success.mean()-base)*100):>+.0f}pp")

# ═══════════════════════════════════════════════════════════════
# Part 6: 肥尾分析
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("⑥ 肥尾分析 — PnL分布 / 盈亏比 / 极端值")
print("=" * 90)

for g, label in [(half, "普通"), (half_strict, "严格")]:
    print(f"\n  {label}:")
    # PnL 分位数
    qs = [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]
    qvals = g.pnl_pct.quantile(qs)
    print(f"    PnL分位: " + " | ".join(f"P{int(q*100):>2d}={v:>+6.2f}%" for q, v in zip(qs, qvals)))

    # 盈亏覆盖
    total_pnl = g.pnl_pct.sum()
    big_win_pnl = g[g.exit_reason == "大胜利"].pnl_pct.sum()
    small_win_pnl = g[g.exit_reason == "小胜利"].pnl_pct.sum()
    stop_loss_pnl = g[g.exit_reason.isin(["盘中止损", "收盘止损"])].pnl_pct.sum()
    time_stop_pnl = g[g.exit_reason == "时间止损"].pnl_pct.sum()
    print(f"    总盈亏: {total_pnl:+.1f}%")
    if total_pnl != 0:
        print(f"    大胜利贡献: {big_win_pnl:+.1f}% ({big_win_pnl/abs(total_pnl)*100:.0f}% of |total|)")
    print(f"    小胜利贡献: {small_win_pnl:+.1f}%")
    print(f"    止损亏损:    {stop_loss_pnl:+.1f}%")
    print(f"    时间止损:    {time_stop_pnl:+.1f}%")

    # 肥尾贡献比例
    pos = g[g.pnl_pct > 0].sort_values("pnl_pct", ascending=False)
    total_pos = pos.pnl_pct.sum()
    if total_pos > 0:
        for top_pct in [0.05, 0.10, 0.20]:
            top_n = max(1, int(len(pos) * top_pct))
            print(f"    Top{top_pct*100:.0f}%盈利交易({top_n}笔)贡献了{pos.head(top_n).pnl_pct.sum()/total_pos*100:.0f}%的正收益")

print("\n" + "=" * 90)
print("完成。")
