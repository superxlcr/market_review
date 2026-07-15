"""按交易日口径分析：首次止损后，盯多少个交易日？
场景：买入→T+1止损→条件单挂着→盯X个交易日等再触发
"""
import pandas as pd
import numpy as np
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.stdout.reconfigure(encoding='utf-8')

from marketreview.data.data_provider import DataProvider
from dotenv import load_dotenv
load_dotenv()

RUN = '.winrate_data/20260715_140945'

# ── 加载数据 ──
df = pd.read_csv(os.path.join(RUN, '回调一半严格.csv'))
df['signal_date_dt'] = pd.to_datetime(df['signal_date'], format='%Y%m%d', errors='coerce')
df = df.sort_values(['code', 'signal_date_dt']).reset_index(drop=True)

# ── 获取交易日历 ──
token = os.getenv('TUSHARE_TOKEN')
if not token:
    print('ERROR: TUSHARE_TOKEN not set')
    sys.exit(1)
dp = DataProvider(tushare_token=token)
# 用最宽范围拿全量交易日
trade_dates = dp.cache.get_daily_dates_in_range('20200101', '20300101')
# 已经是 YYYYMMDD 或 YYYY-MM-DD，统一成 YYYYMMDD
trade_dates = [d.replace('-', '')[:8] if '-' in str(d) else str(d)[:8] for d in trade_dates]
trade_dates = sorted(set(trade_dates))
print(f'交易日历: {len(trade_dates)} 个交易日, {trade_dates[0]} ~ {trade_dates[-1]}')

# 建日期→序号映射
date_to_idx = {d: i for i, d in enumerate(trade_dates)}

def to_date_str(val):
    """Convert a date value to YYYYMMDD string."""
    import datetime as _dt
    if pd.isna(val):
        return None
    if isinstance(val, _dt.datetime):
        return val.strftime('%Y%m%d')
    if isinstance(val, (int, np.integer)):
        return str(int(val))[:8]
    if isinstance(val, str):
        return val.replace('-', '')[:8]
    return str(val)[:8]

def trading_days_between(d1_val, d2_val):
    """两个日期之间的交易日数"""
    d1 = to_date_str(d1_val)
    d2 = to_date_str(d2_val)
    if d1 is None or d2 is None:
        return None
    i1 = date_to_idx.get(d1)
    i2 = date_to_idx.get(d2)
    if i1 is None or i2 is None:
        return None
    return i2 - i1

# ── 找下一笔信号（同标的）──
df['next_signal'] = df.groupby('code')['signal_date'].shift(-1)
df['next_success'] = df.groupby('code')['success'].shift(-1)
df['next_pnl'] = df.groupby('code')['pnl_pct'].shift(-1)
df['next_exit'] = df.groupby('code')['exit_reason'].shift(-1)

# 计算交易日间隔
df['trade_days_to_next'] = df.apply(
    lambda r: trading_days_between(r['signal_date'], r['next_signal']) if pd.notna(r['next_signal']) else None,
    axis=1
)

print(f'\n总交易: {len(df)}  总标的: {df["code"].nunique()}  总胜率: {df["success"].mean():.1%}')

# ═══════════════════════════════════════════════════════════
# 只关注「首次失败」
# ═══════════════════════════════════════════════════════════
# 每个标的第一笔失败（在完整历史中的第一次失败）
failed = df[~df['success']].copy()
failed['fail_rank'] = failed.groupby('code').cumcount() + 1  # 第几次失败

# 首次失败
first_fail = failed[failed['fail_rank'] == 1].copy()
print(f'\n首次失败: {len(first_fail)} 笔 (来自 {first_fail["code"].nunique()} 个标的)')

has_next = first_fail['trade_days_to_next'].notna()
print(f'  有下一笔信号: {has_next.sum()} ({has_next.mean():.1%})')
print(f'  无后续: {(~has_next).sum()} ({(~has_next).mean():.1%})')

# ═══════════════════════════════════════════════════════════
# 1. 交易日分布
# ═══════════════════════════════════════════════════════════
print(f'\n{"="*60}')
print('【首次止损后 → 下一笔信号的交易日间隔】')
print(f'{"="*60}')

trading_bins = [0, 1, 2, 3, 5, 8, 13, 21, 34, 999]
trading_labels = ['当天', '1个交易日', '2个交易日', '3-5交易日', '6-8交易日', '9-13交易日', '14-21交易日', '22-34交易日', '34+交易日']

first_fail['gap_bin'] = pd.cut(first_fail['trade_days_to_next'], bins=trading_bins, labels=trading_labels, right=True)

print(f'\n{"间隔":<16s} {"笔数":>6s} {"占比":>7s} {"累计%":>7s} {"再信号WR":>8s} {"avg盈亏":>10s}')
print('-' * 65)
cum = 0
for label in trading_labels:
    mask = first_fail['gap_bin'] == label
    cnt = mask.sum()
    if cnt == 0:
        continue
    cum += cnt
    cum_pct = cum / has_next.sum() * 100
    pct = cnt / has_next.sum() * 100
    sub = first_fail[mask]
    wr = sub['next_success'].mean()
    pnl = sub['next_pnl'].mean()
    bar = '█' * max(1, int(pct / 2))
    print(f'{label:<16s} {cnt:>6d} {pct:>6.1f}% {cum_pct:>6.1f}% {wr:>7.1%} {pnl:>+9.2f}% {bar}')

no_next = (~has_next).sum()
print(f'{"(无后续)":<16s} {no_next:>6d} {"—":>7s} {"—":>7s} {"—":>8s} {"—":>10s}')

# ═══════════════════════════════════════════════════════════
# 2. 两档建议
# ═══════════════════════════════════════════════════════════
print(f'\n{"="*60}')
print('【实操建议】首次止损后盯多少个交易日？')
print(f'{"="*60}')

print(f'\n从{len(first_fail)}笔首次失败出发：')
print(f'{"盯N交易日":<12s} {"等到再信号":>10s} {"其中捕获成功":>12s} {"占首失%":>10s} {"再触发WR":>10s}')
print('-' * 65)

for td_limit in [3, 5, 8, 10, 13, 15, 21]:
    in_window = (first_fail['trade_days_to_next'].notna()) & (first_fail['trade_days_to_next'] <= td_limit)
    re_win = in_window & (first_fail['next_success'] == True)
    n_re = in_window.sum()
    n_win = re_win.sum()
    wr_in = first_fail.loc[in_window, 'next_success'].mean() if n_re > 0 else 0
    print(f'{td_limit:>5}个交易日    {n_re:>8d}      {n_win:>10d}      {n_win/len(first_fail):>9.1%}  {wr_in:>9.1%}')

# ═══════════════════════════════════════════════════════════
# 3. 按间隔区间的 WR 细节
# ═══════════════════════════════════════════════════════════
print(f'\n{"="*60}')
print('【质量维度】不同间隔区间的下一笔结果分布')
print(f'{"="*60}')

for label in trading_labels:
    mask = first_fail['gap_bin'] == label
    if mask.sum() < 5:
        continue
    sub = first_fail[mask]
    print(f'\n  {label} (n={mask.sum()}):')
    for reason in sub['next_exit'].value_counts().index:
        rsub = sub[sub['next_exit'] == reason]
        print(f'    {reason}: {len(rsub)} ({len(rsub)/len(sub)*100:.0f}%)')

# ═══════════════════════════════════════════════════════════
# 4. 第二次失败的情况（首次失败有后续→第二笔也失败了→再盯？）
# ═══════════════════════════════════════════════════════════
print(f'\n{"="*60}')
print('【追问】如果第二次也止损了，还值得盯吗？')
print(f'{"="*60}')

second_fail = failed[failed['fail_rank'] == 2].copy()
print(f'\n第二次失败: {len(second_fail)} 笔')
has_next2 = second_fail['trade_days_to_next'].notna()
print(f'  有第三笔信号: {has_next2.sum()} ({has_next2.mean():.1%})')

# 再触发的时间分布（简版）
for td_limit in [3, 5, 8, 13]:
    in_w = (second_fail['trade_days_to_next'].notna()) & (second_fail['trade_days_to_next'] <= td_limit)
    n_re2 = in_w.sum()
    n_win2 = (in_w & (second_fail['next_success'] == True)).sum()
    wr2 = second_fail.loc[in_w, 'next_success'].mean() if n_re2 > 0 else 0
    print(f'  盯{td_limit:>2}交易日: 等到{n_re2:>4d}个再信号, 捕获{n_win2:>3d}成功, WR={wr2:.1%}')

# ═══════════════════════════════════════════════════════════
# 5. 行业维度：好行业和差行业的再触发有区别吗？
# ═══════════════════════════════════════════════════════════
print(f'\n{"="*60}')
print('【行业维度】首次失败后再触发的胜率（按L1）')
print(f'{"="*60}')

for ind in first_fail['industry_l1'].value_counts().head(12).index:
    sub = first_fail[first_fail['industry_l1'] == ind]
    if len(sub) < 15:
        continue
    has_n = sub['trade_days_to_next'].notna()
    re_wr = sub.loc[has_n, 'next_success'].mean() if has_n.any() else 0
    in_8 = has_n & (sub['trade_days_to_next'] <= 8)
    wr_8 = sub.loc[in_8, 'next_success'].mean() if in_8.any() else 0
    print(f'  {ind:<8s} 首失={len(sub):>3d} 再触发率={has_n.mean():.0%} '
          f'再触发WR={re_wr:.1%} 8日内WR={wr_8:.1%}')

print(f'\n{"="*60}')
print('分析完成')
