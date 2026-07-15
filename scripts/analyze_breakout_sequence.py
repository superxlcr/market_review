"""深挖族群效应的三个追问：
1. 为什么医药/计算机族群反而更差？
2. 分类标准是否与资金视角不一致？
3. 给出具体时间轴案例供验证
"""
import pandas as pd
import numpy as np
import os, sys
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from marketreview.data.data_provider import DataProvider
from dotenv import load_dotenv
load_dotenv()

RUN = '.winrate_data/20260715_140945'

df = pd.read_csv(os.path.join(RUN, '回调一半严格.csv'))
df['date_int'] = df['signal_date'].astype(str).str[:8].astype(int)

# ── 交易日历 ──
token = os.getenv('TUSHARE_TOKEN')
dp = DataProvider(tushare_token=token)
trade_dates = dp.cache.get_daily_dates_in_range('20200101', '20300101')
trade_dates = sorted(set(
    int(d.replace('-', '')[:8]) if '-' in str(d) else int(str(d)[:8])
    for d in trade_dates
))
date_to_idx = {d: i for i, d in enumerate(trade_dates)}

def trading_day_window(date_int, radius):
    if date_int not in date_to_idx:
        return []
    idx = date_to_idx[date_int]
    return [trade_dates[i] for i in range(max(0, idx-radius), min(len(trade_dates)-1, idx+radius)+1)]

# ── 族群密度（L1 ±3交易日）──
for idx, row in df.iterrows():
    w = trading_day_window(row['date_int'], 3)
    if w:
        mask = (df['industry_l1'] == row['industry_l1']) & (df['date_int'].isin(w)) & (df['code'] != row['code'])
        df.at[idx, 'cluster_size'] = mask.sum()
    else:
        df.at[idx, 'cluster_size'] = 0

df['is_cluster'] = df['cluster_size'] >= 3  # ≥3个同伴

# ═══════════════════════════════════════════════════════════
# 追问1：医药/计算机的族群为什么是负效应？
# ═══════════════════════════════════════════════════════════
print('='*70)
print('追问1：医药/计算机族群 = 负效应？看市场环境')
print('='*70)

for ind in ['医药生物', '计算机', '基础化工']:
    ind_df = df[df['industry_l1'] == ind]
    solo = ind_df[~ind_df['is_cluster']]
    group = ind_df[ind_df['is_cluster']]

    print(f'\n【{ind}】')
    print(f'  孤狼: n={len(solo)} WR={solo["success"].mean():.1%}')
    print(f'  族群: n={len(group)} WR={group["success"].mean():.1%}')

    if len(group) >= 10:
        # 看族群日子的市场环境
        print(f'  族群信号的 market cap 分布:')
        for cap in group['cap_bucket'].value_counts().index:
            sub = group[group['cap_bucket'] == cap]
            print(f'    {cap}: n={len(sub)} WR={sub["success"].mean():.1%}')

        print(f'  族群信号的 wave33 方向:')
        for wdir in ['up', 'down', 'flat']:
            sub = group[group['wave33_sma3_dir'] == wdir]
            if len(sub) >= 3:
                print(f'    w33={wdir}: n={len(sub)} WR={sub["success"].mean():.1%}')

        # 平均盈亏 vs 中位盈亏——是不是少数大涨拉高了均值？
        print(f'  盈亏分布: mean={group["pnl_pct"].mean():+.2f}% '
              f'median={group["pnl_pct"].median():+.2f}% '
              f'min={group["pnl_pct"].min():+.2f}% '
              f'max={group["pnl_pct"].max():+.2f}%')

        # 退出原因
        print(f'  退出原因:')
        for reason in group['exit_reason'].value_counts().index:
            sub = group[group['exit_reason'] == reason]
            print(f'    {reason}: {len(sub)} ({len(sub)/len(group)*100:.0f}%)')

        # 族群日期的市场总信号密度
        group_dates = group['date_int'].unique()
        print(f'  族群发生日期数: {len(group_dates)}')
        # 这些日期全市场的信号数
        date_market_counts = df.groupby('date_int').size()
        group_market_signal = [date_market_counts.get(d, 0) for d in group_dates]
        print(f'  族群日期全市场平均信号数: {np.mean(group_market_signal):.1f}')

# ═══════════════════════════════════════════════════════════
# 追问1b：对比好行业的族群
# ═══════════════════════════════════════════════════════════
print(f'\n{"="*70}')
print('对比：电子/机械设备的族群 = 正效应')
print('='*70)

for ind in ['电子', '机械设备']:
    ind_df = df[df['industry_l1'] == ind]
    group = ind_df[ind_df['is_cluster']]
    if len(group) >= 10:
        print(f'\n【{ind}】族群 n={len(group)} WR={group["success"].mean():.1%}')
        print(f'  盈亏分布: mean={group["pnl_pct"].mean():+.2f}% '
              f'median={group["pnl_pct"].median():+.2f}% '
              f'max={group["pnl_pct"].max():+.2f}%')
        print(f'  退出原因:')
        for reason in group['exit_reason'].value_counts().index:
            sub = group[group['exit_reason'] == reason]
            print(f'    {reason}: {len(sub)} ({len(sub)/len(group)*100:.0f}%)')

# ═══════════════════════════════════════════════════════════
# 追问2：分类标准 vs 资金视角
# ═══════════════════════════════════════════════════════════
print(f'\n{"="*70}')
print('追问2：L1分类会不会跟资金视角不一致？')
print('='*70)

# 看看跨L1的相关性：当电子爆发时，是否也带动机器设备/通信？
# 如果两个L1频繁同时出信号，说明资金把它们当一个板块炒
l1_daily = df.groupby(['industry_l1', 'date_int']).size().reset_index(name='count')
l1_pivot = l1_daily.pivot_table(index='date_int', columns='industry_l1', values='count', fill_value=0)

# 对每个L1，找跟它同时出信号的L1
top_l1 = ['电子', '电力设备', '机械设备', '计算机', '通信', '汽车', '医药生物', '有色金属']
l1_pivot_binary = (l1_pivot[top_l1] > 0).astype(int)

print(f'\n  L1同时出现信号的Jaccard相似度（同一天出信号=资金同向）:')
print(f'  {"":<10s}', end='')
for l1 in top_l1:
    print(f'{l1:<6s}', end='')
print()
for l1_a in top_l1:
    print(f'  {l1_a:<10s}', end='')
    for l1_b in top_l1:
        if l1_a == l1_b:
            print(f'{"-":>6s}', end='')
            continue
        both = (l1_pivot_binary[l1_a] & l1_pivot_binary[l1_b]).sum()
        either = (l1_pivot_binary[l1_a] | l1_pivot_binary[l1_b]).sum()
        jac = both / either if either > 0 else 0
        print(f'{jac:.3f} ', end='')
    print()

# 也看看：有哪些票的L1分类可能"名不副实"
# 比如某个票归类为"电子"但它的涨幅跟"医药"板块同步
print(f'\n  L2子行业在L1内部的差异性:')
for l1 in ['电子', '医药生物', '计算机']:
    l2s = df[df['industry_l1'] == l1]['industry_l2'].value_counts().head(6)
    print(f'  {l1}: {dict(l2s)}')

# ═══════════════════════════════════════════════════════════
# 追问3：具体时间轴案例
# ═══════════════════════════════════════════════════════════
print(f'\n{"="*70}')
print('追问3：族群信号的具体案例（时间轴 + WR）')
print('='*70)

# 找L1行业在±3天内有大量信号的"族群爆发"
# 按(行业, 起始日期)聚合
from collections import defaultdict

cluster_events = defaultdict(list)
for idx, row in df.iterrows():
    w = trading_day_window(row['date_int'], 3)
    if not w:
        continue
    same_ind = df[(df['industry_l1'] == row['industry_l1']) & (df['date_int'].isin(w))]
    event_key = (row['industry_l1'], w[0])  # 用窗口第一天做key
    cluster_events[event_key].append(row)

# 合并重叠事件：同行业、窗口重叠的合并
# 简化：取每个(行业, signal_date)的信号数
event_summary = df.groupby(['industry_l1', 'date_int']).agg(
    n_signals=('code', 'count'),
    wr=('success', 'mean'),
    avg_pnl=('pnl_pct', 'mean'),
    codes=('code', lambda x: ', '.join(sorted(x)[:5])),
    names=('name', lambda x: ', '.join(x[:3])),
).reset_index()

# 找出 ≥4个信号的行业日
big_events = event_summary[event_summary['n_signals'] >= 4].sort_values('n_signals', ascending=False)

print(f'\n  "行业×日期"信号≥4的事件：共 {len(big_events)} 个')
print(f'\n  {"日期":<10s} {"行业":<8s} {"信号数":>6s} {"WR":>7s} {"盈亏":>8s} {"示例票":<30s}')
print(f'  {"-"*75}')

shown = 0
for _, evt in big_events.iterrows():
    if shown >= 30:
        break
    date_str = str(evt['date_int'])
    wr_str = f'{evt["wr"]:.0%}' if pd.notna(evt['wr']) else 'N/A'
    pnl_str = f'{evt["avg_pnl"]:+.1f}%' if pd.notna(evt['avg_pnl']) else 'N/A'
    name_str = str(evt['names'])[:30]
    ind_str = str(evt['industry_l1'])[:8]
    print(f'  {date_str:<10s} {ind_str:<8s} {int(evt["n_signals"]):>6d} {wr_str:>7s} {pnl_str:>8s} {name_str:<30s}')
    shown += 1

# ═══════════════════════════════════════════════════════════
# 追问3b：一个完整的族群案例深度展示
# ═══════════════════════════════════════════════════════════
print(f'\n{"="*70}')
print('深度案例：取几个族群爆发事件，展示完整信息')
print('='*70)

# 取 WR最高/最低的各2个案例
top_events = big_events.nlargest(5, 'wr')
bot_events = big_events.nsmallest(5, 'wr')
sample_events = pd.concat([top_events.head(3), bot_events.head(3)])

for _, evt in sample_events.iterrows():
    date_int = evt['date_int']
    ind = evt['industry_l1']
    print(f'\n  ── {ind} @ {date_int} ──')
    print(f'  信号数: {int(evt["n_signals"])}, WR: {evt["wr"]:.0%}, avg盈亏: {evt["avg_pnl"]:+.2f}%')

    # 取这个行业这个日期±3天的所有信号
    w = trading_day_window(date_int, 3)
    cluster_signals = df[(df['industry_l1'] == ind) & (df['date_int'].isin(w))]
    cluster_signals = cluster_signals.sort_values('pnl_pct')
    for _, sig in cluster_signals.iterrows():
        mark = '✓' if sig['success'] else '✗'
        print(f'    {mark} {sig["code"]} {sig["name"]:<8s} '
              f'买入{sig["entry_date"]} 盈亏{sig["pnl_pct"]:>+6.2f}% '
              f'持有{sig["hold_days"]}天 '
              f'{sig["exit_reason"]} '
              f'w33={sig["wave33_sma3_dir"]} '
              f'MFP={sig["mfp_pct"]:.1f}%')

    # 同期还有哪些行业也在爆发？
    same_dates = df[df['date_int'].isin(w)]
    other_inds = same_dates[same_dates['industry_l1'] != ind]
    if len(other_inds) > 0:
        other_summary = other_inds.groupby('industry_l1').agg(
            n=('code', 'count'), wr=('success', 'mean')
        ).sort_values('n', ascending=False)
        print(f'  同期其他行业:')
        for oi, orow in other_summary.head(5).iterrows():
            print(f'    {oi}: {int(orow["n"])}票 WR={orow["wr"]:.0%}')

print(f'\n{"="*70}')
print('分析完成')
