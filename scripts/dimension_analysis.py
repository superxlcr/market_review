#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""四个维度对所有买点的影响分析 — 行业 / 均线方向 / 市值 / 3浪3。
用法: .venv/Scripts/python scripts/dimension_analysis.py
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
print("维度影响分析 — 行业 / 均线方向 / 市值 / 3浪3 对所有买点的效果")
print("=" * 90)

df = load_data(DATA_DIR)
# 去掉 NaN buy_point (数据脏)
df = df[df.buy_point.notna()].copy()
# 只保留非 disabled 买点（不含随机基准）
EXCLUDE = ["随机基准"]
df_live = df[~df.buy_point.isin(EXCLUDE)].copy()

print(f"分析范围: {len(df_live)} 笔, {df_live.buy_point.nunique()} 个买点")
print(f"日期跨度: {df_live.sd.min()} ~ {df_live.sd.max()}\n")

# 买点分组
MA_BPS = ["扣抵量均线支撑", "5日均量均线支撑", "无量均线支撑",
          "MA20支撑", "MA55支撑", "MA60支撑", "MA120支撑", "MA144支撑", "MA240支撑"]
RETRACE_BPS = ["回调一半", "回调一半严格"]
BAND50_BPS = ["波段50%"]
VOLNODE_BPS = ["量价节点", "量价节点上浮2%", "量价节点严格", "量价节点严格上浮2%"]

def label_group(bp):
    if bp in MA_BPS: return "MA家族"
    if bp in RETRACE_BPS: return "回调一半"
    if bp in BAND50_BPS: return "波段50%"
    if bp in VOLNODE_BPS: return "量价节点"
    return "其他"

df_live["group"] = df_live["buy_point"].apply(label_group)

# ═══════════════════════════════════════════════════════════════
# 1. 各维度对各买点组的抬升效果（统一视角）
# ═══════════════════════════════════════════════════════════════
print("=" * 90)
print("① 维度抬升总览 — 每个维度对每个买点组的胜率抬升（pp vs 该组基线）")
print("=" * 90)

DIMS = {
    "industry_l1": "行业L1",
    "long_ma_state": "长均态",
    "short_ma_state": "短均态",
    "cap_bucket": "市值档",
    "wave33_direction": "3浪3方向",
}

for dim, dim_label in DIMS.items():
    print(f"\n{'─' * 80}")
    print(f"【{dim_label}】各取值 vs 各组基线胜率")
    print(f"{'─' * 80}")

    # 先算各组基线
    group_base = df_live.groupby("group").success.mean()

    # 各组 × 维度取值
    rows = []
    for grp in ["MA家族", "回调一半", "波段50%", "量价节点"]:
        g = df_live[df_live.group == grp]
        base = group_base[grp]
        dv = g.groupby(dim).agg(n=("success","size"), wr=("success","mean"))
        for val, r in dv.iterrows():
            if r.n < 50:
                continue
            rows.append({
                "买点组": grp, "取值": str(val),
                "n": int(r.n), "胜率%": round(r.wr*100, 1),
                "基线%": round(base*100, 1),
                "抬升pp": round((r.wr-base)*100, 1),
            })

    if not rows:
        continue
    t = pd.DataFrame(rows)
    # 按取值透视：行=买点组，列=取值，值=抬升pp
    pivot = t.pivot_table(index="买点组", columns="取值", values="抬升pp", aggfunc="first")
    # 把主要取值排前面
    col_order = []
    for preferred in ["电子", "通信", "计算机", "电力设备", "有色金属", "机械设备",
                       "银行", "食品饮料", "交通运输", "非银金融", "房地产",
                       "多头", "盘整", "空头",
                       "大盘", "中盘", "小盘",
                       "up", "down", "flat"]:
        if preferred in pivot.columns:
            col_order.append(preferred)
    for c in pivot.columns:
        if c not in col_order:
            col_order.append(c)
    pivot = pivot[col_order]
    print(pivot.round(1).to_string())

    # 极差：每个买点组内，最好和最差取值的抬升差
    print(f"\n  各买点组在此维度的极差（最好-最差，≥50样本的取值）:")
    for grp in ["MA家族", "回调一半", "波段50%", "量价节点"]:
        sub = t[t.买点组 == grp]
        if sub.empty:
            continue
        best = sub.loc[sub.抬升pp.idxmax()]
        worst = sub.loc[sub.抬升pp.idxmin()]
        spread = best["抬升pp"] - worst["抬升pp"]
        print(f"    {grp}: 最好={best['取值']}({best['抬升pp']:+.0f}pp)  "
              f"最差={worst['取值']}({worst['抬升pp']:+.0f}pp)  极差={spread:.0f}pp")

# ═══════════════════════════════════════════════════════════════
# 2. 3浪3 深度分析（新维度，需特别关注）
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("② 3浪3 深度分析 — 方向 × 连续天数 × 买点组")
print("=" * 90)

# 2.1 方向 + 连续天数组合
df_live["wv_combo"] = df_live["wave33_direction"].astype(str) + "_" + \
                       pd.cut(df_live["wave33_streak"], bins=[-1,0,2,5,100],
                              labels=["0d", "1-2d", "3-5d", "6+d"]).astype(str)

print("\n3浪3 方向×连续天数 交叉（各组胜率%）:")
for grp in ["MA家族", "回调一半", "波段50%", "量价节点"]:
    g = df_live[df_live.group == grp]
    base = g.success.mean()
    print(f"\n  {grp} (基线 {base*100:.1f}%):")
    cross = g.groupby(["wave33_direction", pd.cut(g["wave33_streak"],
                bins=[-1,0,2,5,100], labels=["0天","1-2天","3-5天","6+天"])],
                observed=False).agg(n=("success","size"), wr=("success","mean"))
    cross["抬升"] = ((cross.wr - base) * 100).round(1)
    cross["胜率%"] = (cross.wr * 100).round(1)
    for (d, s), r in cross.iterrows():
        if r.n >= 30:
            print(f"    {d}_{s}: n={r.n:>5d}  胜率={r['胜率%']:>5.1f}%  抬升={r['抬升']:>+5.0f}pp")

# 2.2 wave33_label 分析
print(f"\n\n3浪3 标签 (wave33_label) 对各组的影响:")
for grp in ["MA家族", "回调一半", "波段50%", "量价节点"]:
    g = df_live[df_live.group == grp]
    base = g.success.mean()
    labels = g.groupby("wave33_label").agg(n=("success","size"), wr=("success","mean"))
    labels = labels[labels.n >= 30].copy()
    labels["抬升"] = ((labels.wr - base) * 100).round(1)
    labels = labels.sort_values("抬升", ascending=False)
    if not labels.empty:
        print(f"\n  {grp} (基线 {base*100:.1f}%):")
        for label, r in labels.iterrows():
            print(f"    {label:<30s}  n={r.n:>5d}  胜率={r.wr*100:>5.1f}%  抬升={r['抬升']:>+5.0f}pp")

# ═══════════════════════════════════════════════════════════════
# 3. 维度独立性检验：好行业 × 好方向 交叉
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("③ 维度交叉 — 好行业 + 好均线方向 叠加效果")
print("=" * 90)

MOMENTUM = ["电子", "通信", "计算机", "电力设备", "有色金属", "机械设备", "国防军工", "传媒"]
DEFENSIVE = ["银行", "交通运输", "食品饮料", "非银金融", "公用事业", "钢铁", "房地产", "建筑装饰", "环保"]

for grp in ["MA家族", "回调一半", "波段50%", "量价节点"]:
    g = df_live[df_live.group == grp].copy()
    base = g.success.mean()
    g["ind_cat"] = "其他"
    g.loc[g.industry_l1.isin(MOMENTUM), "ind_cat"] = "动量板块"
    g.loc[g.industry_l1.isin(DEFENSIVE), "ind_cat"] = "防御板块"

    print(f"\n  {grp} (基线 {base*100:.1f}%):")
    cross2 = g.groupby(["ind_cat", "long_ma_state"], observed=False).agg(
        n=("success","size"), wr=("success","mean"))
    for (ind, lm), r in cross2.iterrows():
        if r.n >= 30:
            print(f"    {ind} × {lm}: n={r.n:>5d}  胜率={r.wr*100:>5.1f}%  "
                  f"抬升={((r.wr-base)*100):>+.0f}pp")

# ═══════════════════════════════════════════════════════════════
# 4. 排名：哪些维度的哪个取值最有效
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("④ 维度效果排序 — 跨所有买点，各维度取值的平均抬升（等权平均各组）")
print("=" * 90)

all_rows = []
for grp in ["MA家族", "回调一半", "波段50%", "量价节点"]:
    g = df_live[df_live.group == grp]
    base = g.success.mean()
    for dim in DIMS:
        dv = g.groupby(dim).agg(n=("success","size"), wr=("success","mean"))
        for val, r in dv.iterrows():
            if r.n < 50:
                continue
            all_rows.append({
                "group": grp, "dim": dim, "val": str(val),
                "n": int(r.n), "lift_pp": round((r.wr-base)*100, 1),
            })

at = pd.DataFrame(all_rows)
# 按 (dim, val) 汇总，算各组平均抬升
summary = at.groupby(["dim", "val"]).agg(
    avg_lift=("lift_pp", "mean"),
    total_n=("n", "sum"),
    n_groups=("group", "nunique"),
).reset_index()
# 只保留在 3+ 组里都有数据的
summary = summary[summary.n_groups >= 3].sort_values("avg_lift", ascending=False)

print("\nTOP 15 正向条件（各组平均抬升）:")
for _, r in summary.head(15).iterrows():
    dim_label = DIMS.get(r["dim"], r["dim"])
    print(f"  {dim_label}={r['val']:<12s}  平均抬升={r['avg_lift']:>+5.0f}pp  "
          f"总样本={r['total_n']:>7d}  覆盖{r['n_groups']}组")

print("\nBOTTOM 15 负向条件:")
for _, r in summary.tail(15).iterrows():
    dim_label = DIMS.get(r["dim"], r["dim"])
    print(f"  {dim_label}={r['val']:<12s}  平均拖累={r['avg_lift']:>+5.0f}pp  "
          f"总样本={r['total_n']:>7d}  覆盖{r['n_groups']}组")

# ═══════════════════════════════════════════════════════════════
# 5. 一致性检验：同维度不同买点组，抬升方向是否一致
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("⑤ 维度一致性 — 哪些维度对所有买点组效果方向一致？")
print("=" * 90)

for dim, dim_label in DIMS.items():
    # 对每个取值，看在不同组里的抬升符号是否一致
    vals = at[at.dim == dim].groupby("val").agg(
        lifts=("lift_pp", list),
        n_grp=("group", "nunique"),
        avg_lift=("lift_pp", "mean"),
    ).reset_index()
    vals = vals[vals.n_grp >= 3].copy()

    consistent_pos = vals[(vals.avg_lift > 0)].sort_values("avg_lift", ascending=False)
    consistent_neg = vals[(vals.avg_lift < 0)].sort_values("avg_lift")

    if len(consistent_pos) > 0:
        top = consistent_pos.head(3)
        items = [f"{r['val']}(+{r['avg_lift']:.0f}pp)" for _, r in top.iterrows()]
        print(f"  {dim_label}: 一致正向 → {', '.join(items)}")

    if len(consistent_neg) > 0:
        bot = consistent_neg.head(3)
        items = [f"{r['val']}({r['avg_lift']:.0f}pp)" for _, r in bot.iterrows()]
        print(f"  {dim_label}: 一致负向 → {', '.join(items)}")

    # 检查有没有取值在不同组里方向相反的情况
    mixed = []
    for val, grp_lifts in vals[["val", "lifts"]].values:
        if len(grp_lifts) >= 3:
            signs = [1 if l > 1 else -1 if l < -1 else 0 for l in grp_lifts]
            if len(set(signs)) > 1:
                mixed.append(val)
    if mixed:
        print(f"  {dim_label}: ⚠️ 方向不一致 → {mixed}")

print("\n" + "=" * 90)
print("完成。")
