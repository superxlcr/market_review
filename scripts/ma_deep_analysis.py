#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""均线买点深度分析 — 单条/多条/共振/过滤/赔率。
用法: .venv/Scripts/python scripts/ma_deep_analysis.py
"""
from __future__ import annotations
import glob, io, os, re, sys
import pandas as pd
import numpy as np

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

pd.set_option("display.width", 300)
pd.set_option("display.max_columns", 50)
pd.set_option("display.max_rows", 100)
pd.set_option("display.float_format", lambda x: f"{x:.1f}")

DATA_DIR = ".winrate_data"

# ──  helpers ──

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
    df["ym"] = df["sd"].str[:6]
    return df


# ──  MA 买点分类 ──

# 组合型（内部含 60/120/240 三个周期，需从 reason 拆分）
COMBO_MA = ["扣抵量均线支撑", "5日均量均线支撑", "无量均线支撑"]
# 单周期型
SINGLE_MA = ["MA20支撑", "MA55支撑", "MA60支撑", "MA120支撑", "MA144支撑", "MA240支撑"]
ALL_MA = COMBO_MA + SINGLE_MA

# 从 reason 提取均线周期
def extract_period(reason: str) -> int:
    """'MA240↑支撑...' → 240; 'MA60↑支撑...' → 60"""
    m = re.search(r"MA(\d+)", str(reason))
    return int(m.group(1)) if m else 0


def fmt_pct(x: float) -> str:
    return f"{x*100:.1f}%"


# ──  加载 ──

print("=" * 80)
print("均线买点深度分析")
print("=" * 80)

df_all = load_data(DATA_DIR)
print(f"总交易: {len(df_all)}  买点: {df_all.buy_point.nunique()}  日期: {df_all.sd.min()}~{df_all.sd.max()}")

# 只取均线买点
df_ma = df_all[df_all.buy_point.isin(ALL_MA)].copy()
print(f"均线交易: {len(df_ma)} ({len(df_ma)/len(df_all)*100:.1f}%)\n")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Part 1: 单条均线基线
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("=" * 80)
print("① 单条均线基线 — 按周期 × 量确认 拆开")
print("=" * 80)

# 先看单周期型（已拆好）
rows1 = []
for bp in SINGLE_MA:
    g = df_ma[df_ma.buy_point == bp]
    if g.empty:
        continue
    period = int(re.findall(r"\d+", bp)[0])
    rows1.append({
        "买点": bp, "周期": period, "量确认": "今日量",
        "n": len(g), "胜率": g.success.mean(), "平均持有天": g.hold_days.mean(),
        "平均MFP": g.mfp_pct.mean(), "大胜利%": (g.exit_reason=="大胜利").mean(),
        "盘中止损%": (g.exit_reason=="盘中止损").mean(),
    })

# 组合型：从 reason 拆出单周期
for bp in COMBO_MA:
    g = df_ma[df_ma.buy_point == bp]
    if g.empty:
        continue
    g = g.copy()
    g["period"] = g["reason"].apply(extract_period)
    # 量确认类型
    if "扣抵量" in bp:
        vol_type = "扣抵量"
    elif "5日均量" in bp:
        vol_type = "5日均量"
    else:
        vol_type = "无量"
    for p in [60, 120, 240]:
        gp = g[g.period == p]
        if gp.empty:
            continue
        rows1.append({
            "买点": f"{bp}→MA{p}", "周期": p, "量确认": vol_type,
            "n": len(gp), "胜率": gp.success.mean(), "平均持有天": gp.hold_days.mean(),
            "平均MFP": gp.mfp_pct.mean(), "大胜利%": (gp.exit_reason=="大胜利").mean(),
            "盘中止损%": (gp.exit_reason=="盘中止损").mean(),
        })

df1 = pd.DataFrame(rows1).sort_values("胜率", ascending=False)
# 打印时按周期分组
print("\n按周期汇总:")
for p in [20, 55, 60, 120, 144, 240]:
    sub = df1[df1.周期 == p].sort_values("胜率", ascending=False)
    if sub.empty:
        continue
    print(f"\n  ── MA{p} ──")
    for _, r in sub.iterrows():
        print(f"  {r['买点']:<28s}  n={r['n']:>6d}  胜率={r['胜率']:>5.1%}  "
              f"持有={r['平均持有天']:>4.1f}d  MFP={r['平均MFP']:>5.2f}%  "
              f"大胜利={r['大胜利%']:>4.1%}  盘中损={r['盘中止损%']:>4.1%}")

# 按周期 + 量确认透视表
print("\n\n周期 × 量确认 胜率矩阵:")
pivot = df1.pivot_table(index="周期", columns="量确认", values="胜率", aggfunc="first")
print((pivot * 100).round(1).to_string())

print("\n随机基准对比: 胜率=14.5%, MFP=4.34%, 大胜利=3.1%")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Part 2: 多条均线共振
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n\n" + "=" * 80)
print("② 多条均线共振 — 同日同标的 MA 信号数 vs 胜率")
print("=" * 80)

# 对每个 code+signal_date，统计有多少个 MA 买点触发了
ma_presence = df_ma.groupby(["code", "sd"]).agg(
    ma_count=("buy_point", "nunique"),
    ma_list=("buy_point", lambda x: sorted(x.unique())),
    success=("success", "max"),  # 至少一笔成功就算
    n_trades=("success", "size"),
    avg_pnl=("pnl_pct", "mean"),
    avg_mfp=("mfp_pct", "mean"),
).reset_index()

print(f"\n同日同标的 MA 信号组合分布:")
count_dist = ma_presence.groupby("ma_count").agg(
    n=("code", "size"),
    胜率=("success", "mean"),
    平均盈亏=("avg_pnl", "mean"),
    平均MFP=("avg_mfp", "mean"),
)
count_dist["占比%"] = (count_dist["n"] / len(ma_presence) * 100).round(1)
print(count_dist.to_string())

# 具体看哪些 MA 组合最常见
print("\n\n最常见的 MA 同时触发组合 (TOP 15):")
combo = ma_presence[ma_presence.ma_count >= 2].copy()
combo["combo_key"] = combo["ma_list"].apply(tuple)
combo_stats = combo.groupby("combo_key").agg(
    n=("code", "size"),
    胜率=("success", "mean"),
    平均盈亏=("avg_pnl", "mean"),
).sort_values("n", ascending=False)
print(combo_stats.head(15).to_string())

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Part 3: 维度过滤 — 能不能救均线胜率
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n\n" + "=" * 80)
print("③ 维度过滤 — 行业 / 市值 / 长均方向 / 3浪3形态")
print("=" * 80)

# 3.1 按买点看各维度抬升
MAIN_MA = ["MA240支撑", "MA60支撑", "MA120支撑", "MA144支撑",
           "MA55支撑", "MA20支撑",
           "扣抵量均线支撑", "5日均量均线支撑", "无量均线支撑"]

for bp in MAIN_MA:
    g = df_ma[df_ma.buy_point == bp]
    if g.empty:
        continue
    base = g.success.mean()
    print(f"\n── {bp} (基线 {base*100:.1f}%, n={len(g)}) ──")

    # 行业 TOP5/BOTTOM5
    ind = g.groupby("industry_l1").agg(n=("success","size"), wr=("success","mean"))
    ind = ind[ind.n >= 80].copy()
    ind["lift"] = ((ind.wr - base) * 100).round(1)
    if not ind.empty:
        top5 = ind.sort_values("lift", ascending=False).head(5)
        bot5 = ind.sort_values("lift").head(5)
        print(f"  行业TOP5: {' | '.join(f'{i}({r.lift:+.0f}pp,n={r.n:.0f})' for i,r in top5.iterrows())}")
        print(f"  行业BOT5: {' | '.join(f'{i}({r.lift:+.0f}pp,n={r.n:.0f})' for i,r in bot5.iterrows())}")

    # 市值
    cap = g.groupby("cap_bucket").agg(n=("success","size"), wr=("success","mean"))
    cap["lift"] = ((cap.wr - base) * 100).round(1)
    print(f"  市值: {' | '.join(f'{i}={r.wr*100:.1f}%(+{r.lift:.0f}pp,n={r.n:.0f})' for i,r in cap.iterrows())}")

    # 长均
    lm = g.groupby("long_ma_state").agg(n=("success","size"), wr=("success","mean"))
    lm["lift"] = ((lm.wr - base) * 100).round(1)
    print(f"  长均态: {' | '.join(f'{i}={r.wr*100:.1f}%(+{r.lift:.0f}pp,n={r.n:.0f})' for i,r in lm.iterrows())}")

    # 3浪3 方向
    wv = g.groupby("wave33_direction").agg(n=("success","size"), wr=("success","mean"))
    wv["lift"] = ((wv.wr - base) * 100).round(1)
    print(f"  3浪3方向: {' | '.join(f'{i}={r.wr*100:.1f}%(+{r.lift:.0f}pp,n={r.n:.0f})' for i,r in wv.iterrows())}")

    # 3浪3 streak（连续天数分段）
    if "wave33_streak" in g.columns:
        g2 = g.copy()
        g2["streak_bin"] = pd.cut(g2.wave33_streak, bins=[-1, 0, 2, 5, 100],
                                   labels=["0天(拐点)", "1-2天", "3-5天", "6+天"])
        sk = g2.groupby("streak_bin", observed=False).agg(n=("success","size"), wr=("success","mean"))
        sk["lift"] = ((sk.wr - base) * 100).round(1)
        print(f"  3浪3连续: {' | '.join(f'{i}={r.wr*100:.1f}%(+{r.lift:.0f}pp,n={r.n:.0f})' for i,r in sk.iterrows())}")

# 3.2 组合过滤：严格条件叠加
print("\n\n── 组合过滤: 逐步叠加条件看胜率变化 (以 MA240支撑 为例) ──")
bp_test = "MA240支撑"
g = df_ma[df_ma.buy_point == bp_test].copy()
base = g.success.mean()
print(f"  基线: n={len(g)} 胜率={base*100:.1f}%")

steps = [
    ("+长均多头", g.long_ma_state == "多头"),
    ("+电子/通信/计算机", g.industry_l1.isin(["电子", "通信", "计算机"])),
    ("+小盘中盘", g.cap_bucket.isin(["小盘", "中盘"])),
    ("+3浪3非下降", g.wave33_direction.isin(["up", "flat"])),
]
mask = pd.Series(True, index=g.index)
for label, cond in steps:
    mask = mask & cond
    sub = g[mask]
    if len(sub) >= 30:
        print(f"  {label:<20s}  n={len(sub):>5d}  胜率={sub.success.mean()*100:>5.1f}%  "
              f"(vs基线{base*100:.1f}% +{(sub.success.mean()-base)*100:+.1f}pp)")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Part 4: 赔率分析 — 胜率不行，赔率如何
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n\n" + "=" * 80)
print("④ 赔率分析 — PnL 分布 / 肥尾 / 期望值")
print("=" * 80)

# 对比: MA家族 vs 非MA(回调一半+波段50%+量价节点) vs 随机基准
df_all["group"] = "other"
df_all.loc[df_all.buy_point.isin(ALL_MA), "group"] = "MA家族"
df_all.loc[df_all.buy_point == "随机基准", "group"] = "随机基准"
df_all.loc[df_all.buy_point.isin(["回调一半", "回调一半严格", "波段50%"]), "group"] = "回调/波段"
df_all.loc[df_all.buy_point.str.contains("量价节点", na=False), "group"] = "量价节点家族"

print("\n各组 PnL 统计:")
pnl_stats = df_all.groupby("group").agg(
    n=("pnl_pct", "size"),
    平均盈亏=("pnl_pct", "mean"),
    盈亏中位数=("pnl_pct", "median"),
    标准差=("pnl_pct", "std"),
    胜率=("success", "mean"),
    最大盈利=("pnl_pct", "max"),
    最大亏损=("pnl_pct", "min"),
)
pnl_stats["盈亏比"] = (pnl_stats["平均盈亏"].abs() / pnl_stats["标准差"] * np.sqrt(pnl_stats["n"])).round(3)  # t-stat-like
print(pnl_stats.round(2).to_string())

# PnL 分位数分布
print("\n\nPnL 分位数分布:")
quantiles = [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]
for grp in ["MA家族", "回调/波段", "量价节点家族", "随机基准"]:
    sub = df_all[df_all.group == grp]
    if sub.empty:
        continue
    qs = sub.pnl_pct.quantile(quantiles)
    print(f"  {grp}: " + " | ".join(f"P{int(q*100):>2d}={v:>+6.2f}%" for q, v in zip(quantiles, qs)))

# 肥尾贡献: 20%+/30%+ 交易占多少
print("\n\n肥尾捕捉 (MFP ≥ 20% / ≥ 30%):")
for grp in ["MA家族", "回调/波段", "量价节点家族", "随机基准"]:
    sub = df_all[df_all.group == grp]
    if sub.empty:
        continue
    big20 = (sub.mfp_pct >= 20).mean()
    big30 = (sub.mfp_pct >= 30).mean()
    win20 = (sub.pnl_pct >= 20).mean()  # 实际兑现的
    win30 = (sub.pnl_pct >= 30).mean()
    print(f"  {grp}: MFP≥20%={big20*100:.1f}%  MFP≥30%={big30*100:.1f}%  |  "
          f"兑现≥20%={win20*100:.1f}%  兑现≥30%={win30*100:.1f}%  (n={len(sub)})")

# 大胜利 vs 其余出场原因的 PnL
print("\n\nMA家族 按出场原因的 PnL 分布:")
for reason in ["大胜利", "小胜利", "盘中止损", "收盘止损", "时间止损"]:
    sub = df_ma[df_ma.exit_reason == reason]
    if sub.empty:
        continue
    print(f"  {reason}: n={len(sub):>6d}  占比={len(sub)/len(df_ma)*100:>4.1f}%  "
          f"平均PnL={sub.pnl_pct.mean():>+6.2f}%  中位PnL={sub.pnl_pct.median():>+6.2f}%")

# 最关键的: MA家族里 大胜利的单子 能覆盖多少亏损
print("\n\n盈亏覆盖分析 (MA家族):")
ma_pnl = df_ma.pnl_pct
total_pnl = ma_pnl.sum()
big_win_pnl = df_ma[df_ma.exit_reason == "大胜利"].pnl_pct.sum()
small_win_pnl = df_ma[df_ma.exit_reason == "小胜利"].pnl_pct.sum()
stop_loss_pnl = df_ma[df_ma.exit_reason.isin(["盘中止损", "收盘止损"])].pnl_pct.sum()
time_stop_pnl = df_ma[df_ma.exit_reason == "时间止损"].pnl_pct.sum()

print(f"  总盈亏: {total_pnl:+.1f}%")
print(f"  大胜利贡献: {big_win_pnl:+.1f}% ({big_win_pnl/total_pnl*100:.0f}% of total)" if total_pnl != 0 else "  大胜利贡献: 0")
print(f"  小胜利贡献: {small_win_pnl:+.1f}%")
print(f"  止损亏损:   {stop_loss_pnl:+.1f}%")
print(f"  时间止损:   {time_stop_pnl:+.1f}%")

# 肥尾贡献: top N% 的盈利交易贡献了多少总正盈利
pos_trades = df_ma[df_ma.pnl_pct > 0].sort_values("pnl_pct", ascending=False)
total_pos = pos_trades.pnl_pct.sum()
if total_pos > 0:
    for top_pct in [0.01, 0.05, 0.10, 0.20]:
        top_n = max(1, int(len(pos_trades) * top_pct))
        top_sum = pos_trades.head(top_n).pnl_pct.sum()
        print(f"  Top {top_pct*100:.0f}% 盈利交易 ({top_n}笔) 贡献了 {top_sum/total_pos*100:.0f}% 的正收益")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Part 5: 汇总
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n\n" + "=" * 80)
print("⑤ 总结")
print("=" * 80)
print("待分析完成后手动填写。")
