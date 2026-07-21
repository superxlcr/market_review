"""ETF Rotation YTD Performance — ASCII-safe output"""
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
    'gem':    ('399006.SZ', 'ChiNext'),
    'nasdaq': ('159941.SZ', 'Nasdaq'),
    'gold':   ('518880.SH', 'Gold'),
}
RISK = ['gem', 'nasdaq', 'gold']

# Load data
dfs = {}
for key, (code, name) in POOL.items():
    if key == 'gem':
        conn = sqlite3.connect('data/marketreview.db')
        df = pd.read_sql(f"SELECT date, open, high, low, close FROM tushare_cache WHERE code='{code}' AND date>='20240901' ORDER BY date", conn)
        conn.close()
    else:
        df = pro.fund_daily(ts_code=code, start_date='20240901', end_date='20260722')
        df = df.sort_values('trade_date').reset_index(drop=True)
    date_col = 'date' if 'date' in df.columns else 'trade_date'
    df['date'] = pd.to_datetime(df[date_col], format='%Y%m%d')
    df = df.sort_values('date').reset_index(drop=True)
    df['high_20'] = df['high'].rolling(LOOKBACK).max().shift(1)
    df['low_20'] = df['low'].rolling(LOOKBACK).min().shift(1)
    df['close_20d'] = df['close'].shift(LOOKBACK)
    df['ret_20'] = (df['close'] - df['close_20d']) / df['close_20d'] * 100
    df['b_high'] = df['close'] > df['high_20']
    dfs[key] = df

def get_row(data, date):
    rows = data[data['date'] == date]
    return rows.iloc[0] if len(rows) > 0 else None

START = pd.Timestamp('2026-01-01')
END   = pd.Timestamp('2026-07-21')
all_dates = sorted(set.union(*[set(dfs[k]['date']) for k in POOL]))

# Simulate
position = 'bond'
entry_price = None
trades_2026 = []
pos_history = {}  # date -> position

for date in all_dates:
    if date < pd.Timestamp('2024-11-15'):
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

    # Exit
    if position in RISK and ranked[0]['key'] != position:
        ret = (rows[position]['close'] - entry_price) / entry_price
        if date >= START:
            trades_2026.append({'date': date, 'action': 'SELL',
                                'asset': POOL[position][1],
                                'price': rows[position]['close'], 'ret': ret})
        position = None; entry_price = None

    # Entry
    if position is None or position == 'bond':
        top = ranked[0]
        if top['b_high']:
            if position == 'bond' and entry_price is not None:
                ret = (rows['bond']['close'] - entry_price) / entry_price
                if date >= START:
                    trades_2026.append({'date': date, 'action': 'SELL',
                                        'asset': 'Bond',
                                        'price': rows['bond']['close'], 'ret': ret})
            if date >= START:
                trades_2026.append({'date': date, 'action': 'BUY',
                                    'asset': POOL[top['key']][1],
                                    'price': top['close'], 'ret': 0})
            position = top['key']; entry_price = top['close']
        elif position is None:
            if date >= START:
                trades_2026.append({'date': date, 'action': 'BUY',
                                    'asset': 'Bond',
                                    'price': rows['bond']['close'], 'ret': 0})
            position = 'bond'; entry_price = rows['bond']['close']

    if date >= START:
        pos_history[date] = position

# Current
last_row = get_row(dfs[position], all_dates[-1])
final_price = last_row['close']
unrealized = (final_price - entry_price) / entry_price if entry_price else 0

# Cumulative return
cumulative = 1.0
for t in trades_2026:
    if t['action'] == 'SELL':
        cumulative *= (1 + t['ret'])
cumulative *= (1 + unrealized)
total_ret = (cumulative - 1) * 100

# Benchmarks
bench = {}
for key in POOL:
    dfk = dfs[key]
    s = dfk[dfk['date'] >= START].iloc[0]['close']
    e = dfk[dfk['date'] <= END].iloc[-1]['close']
    bench[key] = (e - s) / s * 100

# Position days
pos_days = {}
for p in pos_history.values():
    pos_days[p] = pos_days.get(p, 0) + 1
total_td = sum(pos_days.values())

# ============================================================
# OUTPUT
# ============================================================
print()
print("=" * 60)
print("  ETF 20-Day Channel Breakout Rotation Strategy")
print("  2026 YTD Performance (Jan 1 -- Jul 21)")
print("=" * 60)
print()
print(f"  Final NAV:       {cumulative:.4f}")
print(f"  YTD Return:      {total_ret:+.2f}%")
print()
print(f"  {'-'*50}")
print(f"  {'Benchmark Comparison (Buy & Hold)':^50s}")
print(f"  {'-'*50}")
for key in ['gem', 'nasdaq', 'gold', 'bond']:
    m = ' <-- current' if key == position else ''
    print(f"  {POOL[key][1]:8s} ({POOL[key][0]:12s}): {bench[key]:+7.2f}%{m}")
best_bh = max(bench.values())
strat_beats = total_ret > best_bh
print(f"  {'-'*50}")
print(f"  {'Strategy':8s} {'':12s}  {total_ret:+7.2f}%{'  <-- BEATS ALL!' if strat_beats else ''}")
print()
print(f"  {'-'*50}")
print(f"  {'Position Time Distribution':^50s}")
print(f"  {'-'*50}")
for key in ['bond', 'gem', 'nasdaq', 'gold']:
    d = pos_days.get(key, 0)
    pct = d / total_td * 100
    bar = '#' * int(pct / 2)
    print(f"  {POOL[key][1]:8s}: {d:3d}d ({pct:5.1f}%) {bar}")
print(f"  Total trading days: {total_td}")
print()
print(f"  {'-'*50}")
print(f"  {'2026 Trade Log':^50s}")
print(f"  {'-'*50}")
total_real = 0
for t in trades_2026:
    if t['action'] == 'SELL':
        rp = t['ret'] * 100
        total_real += rp
        print(f"  {t['date'].strftime('%m-%d')} SELL {t['asset']:8s} @ {t['price']:>10.4f}  ({rp:+.2f}%)")
    else:
        print(f"  {t['date'].strftime('%m-%d')} BUY  {t['asset']:8s} @ {t['price']:>10.4f}")

closed = [t for t in trades_2026 if t['action'] == 'SELL']
wins = sum(1 for t in closed if t['ret'] > 0)
losses = sum(1 for t in closed if t['ret'] <= 0)
avg_win = np.mean([t['ret']*100 for t in closed if t['ret'] > 0]) if wins > 0 else 0
avg_loss = np.mean([t['ret']*100 for t in closed if t['ret'] <= 0]) if losses > 0 else 0
n_trades = len(closed)

print()
print(f"  Current Holding: {POOL[position][1]} @ {final_price:.4f}")
print(f"  Realized P&L:    {total_real:+.2f}%")
print(f"  Unrealized P&L:  {unrealized*100:+.2f}%")
print(f"  ---")
print(f"  Total Return:    {total_ret:+.2f}%")
print(f"  Win Rate:        {wins}/{n_trades} ({wins/n_trades*100:.1f}%)")
print(f"  Avg Win:         {avg_win:+.2f}%")
print(f"  Avg Loss:        {avg_loss:+.2f}%")
if avg_loss != 0 and avg_win != 0:
    print(f"  Profit Factor:   {abs(avg_win * wins / (avg_loss * losses)):.2f}" if losses > 0 else f"  Profit Factor:   infinite (no losses!)")
print()
print("=" * 60)
