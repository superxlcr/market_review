#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""买点胜率数据分析器 — 对 .winrate_data/ 下的回测 CSV 做条件胜率挖掘。

配套方法论与历次结论见:
    docs/superpowers/specs/2026-07-12-buypoint-winrate-analysis.md

用法(从项目根目录运行):
    .venv/Scripts/python scripts/winrate_analysis.py
    .venv/Scripts/python scripts/winrate_analysis.py --data-dir .winrate_data
    .venv/Scripts/python scripts/winrate_analysis.py --min-n 200

指标约定:
    胜率(success) = 该笔交易的峰值浮盈(mfp_pct)是否曾摸到 判赢阈值(默认+10%)。
    它衡量的是「最差情况地板」——买了这个信号、机械持有,至少给过一次 +10% 浮盈机会的概率。
    注意:止损松紧会改变胜率本身(收得越紧越多单在摸到+10%前被扫出),
          所以「止损调参」不能靠本脚本挖现有 CSV,必须重跑扫描。见文档结尾。

对齐:交易系统目标=捕捉30%+趋势行情,实盘先筛标的+评估行情(memory: trading-system-design-goal)。
"""
from __future__ import annotations
import argparse
import glob
import io
import os
import sys

import pandas as pd

# Windows 控制台按 UTF-8 输出中文,避免 GBK 乱码
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 200)

# 动量/成长板块白名单(先验,非数据挖出;用于「买点竞争」的行业过滤对比)。
# 这不是焊死的榜单——样本外测试证明「躲开防御板块」最稳,领涨板块会轮动。
MOMENTUM_INDUSTRIES = [
    "电子", "通信", "计算机", "电力设备", "有色金属", "机械设备", "国防军工", "传媒",
]


def _resolve_dir(data_dir: str) -> str:
    """若 data_dir 下直接有 CSV 就用它；否则取最新的 run 子文件夹（YYYYMMDD_HHMMSS）。"""
    if glob.glob(os.path.join(data_dir, "*.csv")):
        return data_dir
    subdirs = [d for d in glob.glob(os.path.join(data_dir, "*")) if os.path.isdir(d)]
    runs = sorted(d for d in subdirs if glob.glob(os.path.join(d, "*.csv")))
    return runs[-1] if runs else data_dir


def load_data(data_dir: str) -> pd.DataFrame:
    resolved = _resolve_dir(data_dir)
    files = sorted(glob.glob(os.path.join(resolved, "*.csv")))
    if not files:
        sys.exit(f"[错误] {data_dir} 下没有 CSV。先在「买点胜率」页跑一次。")
    if resolved != data_dir:
        print(f"[run] 使用最新 run: {resolved}")
    df = pd.concat([pd.read_csv(f, encoding="utf-8-sig") for f in files], ignore_index=True)
    # 引擎已 position-less 且不再产出「回测结束」右删失单，分析层无需再清洗。
    df["sd"] = df["signal_date"].astype(str)
    df["ym"] = df["sd"].str[:6]
    print(f"载入 {len(files)} 个文件, 共 {len(df)} 笔交易, 买点: {df['buy_point'].unique().tolist()}")
    print(f"信号日期跨度: {df['sd'].min()} ~ {df['sd'].max()}\n")
    return df


def section1_baseline(df: pd.DataFrame) -> None:
    print("=" * 72)
    print("① 基线画像  (胜率 = 峰值浮盈曾摸到 +10%)")
    print("=" * 72)
    base = df.groupby("buy_point").agg(
        n=("success", "size"),
        胜率=("success", "mean"),
        平均持有天=("hold_days", "mean"),
        平均峰值浮盈=("mfp_pct", "mean"),
    )
    base["胜率"] = (base["胜率"] * 100).round(1)
    base["平均持有天"] = base["平均持有天"].round(1)
    base["平均峰值浮盈"] = base["平均峰值浮盈"].round(2)
    print(base.sort_values("胜率", ascending=False).to_string())

    print("\n  出场原因分布 (占比%):")
    er = pd.crosstab(df["buy_point"], df["exit_reason"], normalize="index") * 100
    print(er.round(1).to_string())
    print()


def _lift_table(df: pd.DataFrame, bp: str, dim: str, min_n: int) -> pd.DataFrame:
    """某买点下,dim 各取值的胜率 vs 该买点基线胜率的抬升(百分点)。"""
    g = df[df.buy_point == bp]
    base = g.success.mean()
    t = g.groupby(dim).agg(n=("success", "size"), wr=("success", "mean"))
    t = t[t.n >= min_n].copy()
    t["胜率%"] = (t.wr * 100).round(1)
    t["基线%"] = round(base * 100, 1)
    t["抬升pp"] = ((t.wr - base) * 100).round(1)
    return t[["n", "胜率%", "基线%", "抬升pp"]].sort_values("抬升pp", ascending=False)


def section2_handles(df: pd.DataFrame, min_n: int) -> None:
    print("=" * 72)
    print("② 手段胜率抬升  (pp=百分点, +为抬升; 唯一大杠杆通常是行业)")
    print("=" * 72)
    for bp in df.buy_point.unique():
        print(f"\n--- {bp} ---")
        for dim, label, mn in [
            ("industry_l1", "行业L1", max(100, min_n - 30)),
            ("cap_bucket", "市值档", min_n),
            ("long_ma_state", "长均态", min_n),
            ("short_ma_state", "短均态", min_n),
        ]:
            t = _lift_table(df, bp, dim, mn)
            if t.empty:
                continue
            if dim == "industry_l1":
                print(f"  [{label}] 抬升TOP5:")
                print(t.head(5).to_string())
                print(f"  [{label}] 拖累BOTTOM5:")
                print(t.tail(5).to_string())
            else:
                print(f"  [{label}]:")
                print(t.to_string())


def section3_oos(df: pd.DataFrame, min_n: int) -> None:
    print("\n" + "=" * 72)
    print("③ 行业杠杆 样本外稳健性  (H1 选行业 → H2 应用)")
    print("=" * 72)
    mid = df["sd"].sort_values().iloc[len(df) // 2]
    h1, h2 = df[df.sd < mid], df[df.sd >= mid]
    print(f"  H1 {h1.sd.min()}~{h1.sd.max()} n={len(h1)} 胜率{h1.success.mean()*100:.1f}%"
          f"  |  H2 {h2.sd.min()}~{h2.sd.max()} n={len(h2)} 胜率{h2.success.mean()*100:.1f}%")

    h1b = h1.success.mean()
    h1i = h1.groupby("industry_l1").agg(n=("success", "size"), wr=("success", "mean"))
    h1i = h1i[h1i.n >= min_n - 30]
    good = h1i[h1i.wr >= h1b].sort_values("wr", ascending=False).index.tolist()
    print(f"\n  H1 选出的'好行业'({len(good)}个): {good}")

    h2b = h2.success.mean()
    hg = h2[h2.industry_l1.isin(good)]
    hbd = h2[~h2.industry_l1.isin(good)]
    print("\n  【样本外结果 in H2】")
    print(f"    基线全部     n={len(h2):>5}  胜率={h2b*100:5.1f}%")
    print(f"    ∈H1好行业    n={len(hg):>5}  胜率={hg.success.mean()*100:5.1f}%"
          f"  (样本外抬升 {(hg.success.mean()-h2b)*100:+.1f}pp)")
    print(f"    ∈H1差行业    n={len(hbd):>5}  胜率={hbd.success.mean()*100:5.1f}%")

    comp = pd.DataFrame({
        "H1_wr": h1.groupby("industry_l1").success.mean(),
        "H2_wr": h2.groupby("industry_l1").success.mean(),
        "H1_n": h1.groupby("industry_l1").size(),
        "H2_n": h2.groupby("industry_l1").size(),
    })
    comp = comp[(comp.H1_n >= min_n - 30) & (comp.H2_n >= min_n - 30)]
    # 排名后取 Pearson = Spearman(免 scipy)
    rho = comp["H1_wr"].rank().corr(comp["H2_wr"].rank())
    print(f"\n  行业胜率 H1 vs H2 秩相关(Spearman) = {rho:.2f}  (越接近1越稳定; 头尾稳、中间轮动)")
    comp["H1胜率"] = (comp.H1_wr * 100).round(1)
    comp["H2胜率"] = (comp.H2_wr * 100).round(1)
    print(comp[["H1_n", "H1胜率", "H2_n", "H2胜率"]].sort_values("H1胜率", ascending=False).to_string())


def section4_competition(df: pd.DataFrame) -> None:
    print("\n" + "=" * 72)
    print(f"④ 买点竞争  (行业过滤 = 动量板块白名单 {MOMENTUM_INDUSTRIES})")
    print("=" * 72)
    rows = []
    for bp in df.buy_point.unique():
        g = df[df.buy_point == bp]
        gf = g[g.industry_l1.isin(MOMENTUM_INDUSTRIES)]
        rows.append({
            "买点": bp, "基线n": len(g), "基线胜率%": round(g.success.mean() * 100, 1),
            "动量n": len(gf),
            "动量胜率%": round(gf.success.mean() * 100, 1) if len(gf) else float("nan"),
            "抬升pp": round((gf.success.mean() - g.success.mean()) * 100, 1) if len(gf) else float("nan"),
            "覆盖股票数": g.code.nunique(),
        })
    print(pd.DataFrame(rows).sort_values("基线胜率%", ascending=False).to_string(index=False))

    print("\n  买点重叠 (同一 code+signal_date 触发) — Jaccard%:")
    sets = {bp: set(zip(df[df.buy_point == bp].code, df[df.buy_point == bp].sd))
            for bp in df.buy_point.unique()}
    bps = list(sets.keys())
    mat = pd.DataFrame(index=bps, columns=bps, dtype=float)
    for a in bps:
        for b in bps:
            u = len(sets[a] | sets[b])
            i = len(sets[a] & sets[b])
            mat.loc[a, b] = round(100 * i / u, 1) if u else 0.0
    print(mat.to_string())
    print("\n  注:高重叠(>70%)的两买点是冗余,应择一保留;低重叠(<5%)是互补,可并用。")


def main() -> None:
    ap = argparse.ArgumentParser(description="买点胜率数据分析器")
    ap.add_argument("--data-dir", default=".winrate_data",
                    help="run 文件夹或含 CSV 的目录 (默认 .winrate_data，自动取最新 run)")
    ap.add_argument("--min-n", type=int, default=150, help="切片最小样本阈值 (默认150)")
    args = ap.parse_args()

    df = load_data(args.data_dir)
    section1_baseline(df)
    section2_handles(df, args.min_n)
    section3_oos(df, args.min_n)
    section4_competition(df)

    print("\n" + "=" * 72)
    print("⑤ 下一阶段提示")
    print("=" * 72)
    print("  止损幅度 / 收盘止损开关 / ATR 止损 —— 这些改的是离场,会改变胜率本身,")
    print("  不能靠本脚本挖现有 CSV,必须以不同配置重跑扫描,得到「止损松紧 ↔ 胜率 vs 尾亏」权衡曲线。")


if __name__ == "__main__":
    main()
