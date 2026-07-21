"""ETF Rotation Strategy — Multi-Year Backtest (2017-2026)"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import pandas as pd, numpy as np, tushare as ts, sqlite3
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
ts.set_token(os.getenv('TUSHARE_TOKEN'))
pro = ts.pro_api()

LOOKBACK = 20
POOL = {
    'bond':   ('511010.SH', 'Bond'),
    'hs300':  ('000300.SH', 'CSI300'),
    'nasdaq': ('159941.SZ', 'Nasdaq'),
    'gold':   ('518880.SH', 'Gold'),
}
RISK = ['hs300', 'nasdaq', 'gold']

STOP_LOSS = True   # 20-day low stop loss: exit if close < 20d low

# ============================================================
# Load data (from 2016 for 2017 warmup)
# ============================================================
print("Loading data...")
dfs = {}
for key, (code, name) in POOL.items():
    if key == 'hs300':
        df = pro.index_daily(ts_code=code, start_date='20160101', end_date='20260722')
        df = df.rename(columns={'trade_date': 'date'})
        conn = sqlite3.connect('data/marketreview.db')
        df_db = pd.read_sql(f"SELECT date, open, high, low, close FROM tushare_cache WHERE code='{code}' AND date>='20160101' ORDER BY date", conn)
        conn.close()
        if len(df_db) > 0:
            df_db['date'] = pd.to_datetime(df_db['date'], format='%Y%m%d')
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
            df = pd.concat([df, df_db]).drop_duplicates(subset=['date'], keep='last').sort_values('date')
    else:
        df = pro.fund_daily(ts_code=code, start_date='20160101', end_date='20260722')
        df = df.sort_values('trade_date').reset_index(drop=True)
    date_col = 'date' if 'date' in df.columns else 'trade_date'
    df['date'] = pd.to_datetime(df[date_col], format='%Y%m%d')
    df = df.sort_values('date').reset_index(drop=True)

    # SPLIT ADJUSTMENT: 159941.SZ 4:1 split on 2022-07-05
    if code == '159941.SZ':
        split_date = pd.Timestamp('2022-07-05')
        ratio = 4.0
        pre_mask = df['date'] < split_date
        for col in ['open', 'high', 'low', 'close', 'pre_close']:
            if col in df.columns:
                df.loc[pre_mask, col] = df.loc[pre_mask, col] / ratio
        print(f"    Adjusted {pre_mask.sum()} pre-split rows for {code}")

    df['high_20'] = df['high'].rolling(LOOKBACK).max().shift(1)
    df['low_20'] = df['low'].rolling(LOOKBACK).min().shift(1)
    df['close_20d'] = df['close'].shift(LOOKBACK)
    df['ret_20'] = (df['close'] - df['close_20d']) / df['close_20d'] * 100
    df['b_high'] = df['close'] > df['high_20']
    df['b_low'] = df['close'] < df['low_20']
    dfs[key] = df
    print(f"  {name:8s} ({code:12s}): {len(df)} rows, {df['date'].min().strftime('%Y-%m-%d')} ~ {df['date'].max().strftime('%Y-%m-%d')}")

def get_row(data, date):
    rows = data[data['date'] == date]
    return rows.iloc[0] if len(rows) > 0 else None

all_dates = sorted(set.union(*[set(dfs[k]['date']) for k in POOL]))

# ============================================================
# Full simulation
# ============================================================
print("Simulating...")
position = 'bond'
entry_price = None
daily_nav = []
nav = 1.0

for date in all_dates:
    if date < pd.Timestamp('2016-11-15'):
        continue

    rows = {}
    valid = True
    for key in POOL:
        r = get_row(dfs[key], date)
        if r is None or pd.isna(r['high_20']) or pd.isna(r['ret_20']):
            valid = False; break
        rows[key] = r
    if not valid:
        continue

    ranked = []
    for key in RISK:
        ranked.append({'key': key, 'ret_20': rows[key]['ret_20'],
                       'b_high': rows[key]['b_high'], 'close': rows[key]['close']})
    ranked.sort(key=lambda x: x['ret_20'], reverse=True)

    # Track daily NAV
    if date >= pd.Timestamp('2016-12-31') and entry_price is not None:
        current_nav = nav * (rows[position]['close'] / entry_price)
        daily_nav.append((date, position, current_nav))

    # Stop Loss: exit if close < 20-day low
    if STOP_LOSS and position in RISK and rows[position]['b_low']:
        ret = (rows[position]['close'] - entry_price) / entry_price
        nav *= (1 + ret)
        position = 'bond'; entry_price = rows['bond']['close']

    # Exit: current no longer #1
    if position in RISK and ranked[0]['key'] != position:
        ret = (rows[position]['close'] - entry_price) / entry_price
        nav *= (1 + ret)
        position = None; entry_price = None

    # Entry: #1 must break 20-day high
    if position is None or position == 'bond':
        top = ranked[0]
        if top['b_high']:
            if position == 'bond' and entry_price is not None:
                ret = (rows['bond']['close'] - entry_price) / entry_price
                nav *= (1 + ret)
            position = top['key']; entry_price = top['close']
        elif position is None:
            position = 'bond'; entry_price = rows['bond']['close']

nav_df = pd.DataFrame(daily_nav, columns=['date', 'position', 'nav']).set_index('date')

# ============================================================
# Annual Returns
# ============================================================
years = [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]

print()
print("=" * 80)
print("  ETF 20-Day Channel Breakout Rotation -- Annual Performance (2017-2026)")
print("=" * 80)
print()
print(f"  {'Year':6s}  {'Strategy':>10s}  {'CSI300':>10s}  {'Nasdaq':>10s}  {'Gold':>10s}  {'Bond':>10s}  {'Best':>10s}")
print(f"  {'-'*6}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*10}")

annual_returns = {}

for year in years:
    if year == 2026:
        start_date = pd.Timestamp(f'{year}-01-01')
        end_date = pd.Timestamp('2026-07-21')
    else:
        start_date = pd.Timestamp(f'{year}-01-01')
        end_date = pd.Timestamp(f'{year}-12-31')

    # Strategy
    year_nav = nav_df[(nav_df.index >= start_date) & (nav_df.index <= end_date)]
    if len(year_nav) >= 2:
        strat_ret = (year_nav.iloc[-1]['nav'] - year_nav.iloc[0]['nav']) / year_nav.iloc[0]['nav'] * 100
    else:
        strat_ret = float('nan')

    # Benchmarks
    bh_rets = {}
    for key in POOL:
        dfk = dfs[key]
        s_rows = dfk[(dfk['date'] >= start_date) & (dfk['date'] <= end_date)]
        if len(s_rows) >= 2:
            bh_rets[key] = (s_rows.iloc[-1]['close'] - s_rows.iloc[0]['close']) / s_rows.iloc[0]['close'] * 100
        else:
            bh_rets[key] = float('nan')

    annual_returns[year] = {'strategy': strat_ret, 'benchmarks': bh_rets}

    # Determine best asset each year
    all_r = {'Strategy': strat_ret}
    for k in POOL:
        all_r[POOL[k][1]] = bh_rets[k]
    best_name = max(all_r, key=all_r.get)

    print(f"  {year:<6d}  {strat_ret:+9.2f}%  {bh_rets.get('hs300', 0):+9.2f}%  {bh_rets.get('nasdaq', 0):+9.2f}%  {bh_rets.get('gold', 0):+9.2f}%  {bh_rets.get('bond', 0):+9.2f}%  {best_name:>10s}")

# ============================================================
# Cumulative
# ============================================================
print()
print(f"  {'-'*80}")
start_nav = nav_df[nav_df.index >= pd.Timestamp('2017-01-01')].iloc[0]['nav']
end_nav = nav_df.iloc[-1]['nav']
total_ret = (end_nav - start_nav) / start_nav * 100
print(f"  Cumulative (2017-01-01 ~ 2026-07-21): {total_ret:+.2f}%")

for key in POOL:
    dfk = dfs[key]
    sr = dfk[dfk['date'] >= pd.Timestamp('2017-01-01')]
    er = dfk[dfk['date'] <= pd.Timestamp('2026-07-21')]
    if len(sr) > 0 and len(er) > 0:
        ret = (er.iloc[-1]['close'] - sr.iloc[0]['close']) / sr.iloc[0]['close'] * 100
        print(f"  {POOL[key][1]:8s} B&H:  {ret:+.2f}%")
print(f"  Strategy     {total_ret:+.2f}%")

# ============================================================
# Max Drawdown
# ============================================================
nav_series = nav_df['nav']
rolling_max = nav_series.cummax()
drawdown = (nav_series - rolling_max) / rolling_max * 100
max_dd = drawdown.min()
max_dd_date = drawdown.idxmin()
print(f"\n  Max Drawdown: {max_dd:.2f}% on {max_dd_date.strftime('%Y-%m-%d')}")

# ============================================================
# Yearly Trade Stats
# ============================================================
print()
print(f"  {'-'*80}")
print(f"  {'Yearly Trade Stats':^70s}")
print(f"  {'-'*80}")
print(f"  {'Year':6s}  {'Trades':>8s}  {'Wins':>6s}  {'Win%':>8s}  {'AvgWin':>8s}  {'AvgLoss':>8s}  {'PFactor':>8s}")

for year in years:
    if year == 2026:
        y_start = pd.Timestamp('2026-01-01')
        y_end = pd.Timestamp('2026-07-21')
    else:
        y_start = pd.Timestamp(f'{year}-01-01')
        y_end = pd.Timestamp(f'{year}-12-31')

    pos = 'bond'
    ep = None
    y_trades = []

    for date in all_dates:
        if date < pd.Timestamp('2016-11-15'): continue
        rows = {}
        valid = True
        for key in POOL:
            r = get_row(dfs[key], date)
            if r is None or pd.isna(r['high_20']): valid = False; break
            rows[key] = r
        if not valid: continue

        ranked = []
        for key in RISK:
            ranked.append({'key': key, 'ret_20': rows[key]['ret_20'],
                           'b_high': rows[key]['b_high'], 'close': rows[key]['close']})
        ranked.sort(key=lambda x: x['ret_20'], reverse=True)

        # Stop Loss
        if STOP_LOSS and pos in RISK and rows[pos]['b_low']:
            ret = (rows[pos]['close'] - ep) / ep
            if y_start <= date <= y_end:
                y_trades.append({'date': date, 'ret': ret})
            pos = 'bond'; ep = rows['bond']['close']

        if pos in RISK and ranked[0]['key'] != pos:
            ret = (rows[pos]['close'] - ep) / ep
            if y_start <= date <= y_end:
                y_trades.append({'date': date, 'ret': ret})
            pos = None; ep = None

        if pos is None or pos == 'bond':
            top = ranked[0]
            if top['b_high']:
                if pos == 'bond' and ep is not None:
                    ret = (rows['bond']['close'] - ep) / ep
                    if y_start <= date <= y_end:
                        y_trades.append({'date': date, 'ret': ret})
                pos = top['key']; ep = top['close']
            elif pos is None:
                pos = 'bond'; ep = rows['bond']['close']

    n = len(y_trades)
    w = sum(1 for t in y_trades if t['ret'] > 0)
    l = sum(1 for t in y_trades if t['ret'] <= 0)
    wr = w/n*100 if n > 0 else 0
    aw = np.mean([t['ret']*100 for t in y_trades if t['ret'] > 0]) if w > 0 else 0
    al = np.mean([t['ret']*100 for t in y_trades if t['ret'] <= 0]) if l > 0 else 0
    pf = abs(aw*w/(al*l)) if l > 0 and al != 0 else (999 if w > 0 else 0)
    print(f"  {year:<6d}  {n:>8d}  {w:>6d}  {wr:>7.1f}%  {aw:+7.2f}%  {al:+7.2f}%  {pf:>8.2f}")

# ============================================================
# CAGR
# ============================================================
years_elapsed = (pd.Timestamp('2026-07-21') - pd.Timestamp('2017-01-01')).days / 365.25
cagr = ((1 + total_ret/100) ** (1/years_elapsed) - 1) * 100
print(f"\n  CAGR (2017-2026): {cagr:.2f}%")
print(f"  Years: {years_elapsed:.1f}")

print()
print("=" * 80)
