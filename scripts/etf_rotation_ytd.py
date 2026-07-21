"""
ETF 20日通道突破轮动战法 — 2026年至今收益率计算
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import pandas as pd, numpy as np, tushare as ts, sqlite3
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
ts.set_token(os.getenv('TUSHARE_TOKEN'))
pro = ts.pro_api()

LOOKBACK = 20

POOL = {
    'bond':   ('511010.SH', '国债ETF'),
    'gem':    ('399006.SZ', '创业板指'),
    'nasdaq': ('159941.SZ', '纳指ETF'),
    'gold':   ('518880.SH', '黄金ETF'),
}
RISK = ['gem', 'nasdaq', 'gold']

# ============================================================
# Load data
# ============================================================
dfs = {}
for key, (code, name) in POOL.items():
    if key == 'gem':
        conn = sqlite3.connect('data/marketreview.db')
        df = pd.read_sql(
            f"SELECT date, open, high, low, close FROM tushare_cache "
            f"WHERE code='{code}' AND date>='20240901' ORDER BY date", conn)
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

# ============================================================
# Full simulation
# ============================================================
START = pd.Timestamp('2026-01-01')
END   = pd.Timestamp('2026-07-21')

all_dates = sorted(set.union(*[set(dfs[k]['date']) for k in POOL]))

position = 'bond'
entry_price = None
trades_2026 = []

for date in all_dates:
    if date < pd.Timestamp('2024-11-15'):
        continue

    rows = {}
    valid = True
    for key in POOL:
        r = get_row(dfs[key], date)
        if r is None or pd.isna(r['high_20']) or pd.isna(r['ret_20']):
            valid = False
            break
        rows[key] = r
    if not valid:
        continue

    ranked = []
    for key in RISK:
        ranked.append({
            'key': key, 'name': POOL[key][1],
            'ret_20': rows[key]['ret_20'],
            'b_high': rows[key]['b_high'],
            'close': rows[key]['close']
        })
    ranked.sort(key=lambda x: x['ret_20'], reverse=True)

    # Exit check
    if position in RISK and ranked[0]['key'] != position:
        exit_price = rows[position]['close']
        ret = (exit_price - entry_price) / entry_price
        if date >= START:
            trades_2026.append({
                'date': date, 'action': 'SELL',
                'asset': POOL[position][1],
                'price': exit_price, 'ret': ret
            })
        position = None
        entry_price = None

    # Entry check
    if position is None or position == 'bond':
        top = ranked[0]
        if top['b_high']:
            if position == 'bond' and entry_price is not None:
                ret = (rows['bond']['close'] - entry_price) / entry_price
                if date >= START:
                    trades_2026.append({
                        'date': date, 'action': 'SELL',
                        'asset': '国债ETF',
                        'price': rows['bond']['close'], 'ret': ret
                    })
            if date >= START:
                trades_2026.append({
                    'date': date, 'action': 'BUY',
                    'asset': top['name'],
                    'price': top['close'], 'ret': 0
                })
            position = top['key']
            entry_price = top['close']
        elif position is None:
            if date >= START:
                trades_2026.append({
                    'date': date, 'action': 'BUY',
                    'asset': '国债ETF',
                    'price': rows['bond']['close'], 'ret': 0
                })
            position = 'bond'
            entry_price = rows['bond']['close']

# Current position
last_date = all_dates[-1]
last_row = get_row(dfs[position], last_date)
final_price = last_row['close']
unrealized_pnl = (final_price - entry_price) / entry_price if entry_price else 0

# ============================================================
# Calculate cumulative return
# ============================================================
cumulative = 1.0
for t in trades_2026:
    if t['action'] == 'SELL':
        cumulative *= (1 + t['ret'])
cumulative *= (1 + unrealized_pnl)
total_return = (cumulative - 1) * 100

# ============================================================
# Benchmark
# ============================================================
benchmarks = {}
for key in POOL:
    df = dfs[key]
    start_rows = df[df['date'] >= START]
    end_rows = df[df['date'] <= END]
    if len(start_rows) > 0 and len(end_rows) > 0:
        sp = start_rows.iloc[0]['close']
        ep = end_rows.iloc[-1]['close']
        benchmarks[key] = (ep - sp) / sp * 100

# ============================================================
# Print Report
# ============================================================
print()
print("=" * 65)
print("  ETF 20日通道突破轮动战法 — 2026年至今 (01-01 ~ 07-21)")
print("=" * 65)

print(f"\n  最终净值: {cumulative:.4f}")
print(f"  2026年收益率: {total_return:+.2f}%")
print()

# Benchmark comparison
print(f"  {'─' * 50}")
print(f"  {'Benchmark (Buy & Hold)':^50s}")
print(f"  {'─' * 50}")
for key in ['gem', 'nasdaq', 'gold', 'bond']:
    name = POOL[key][1]
    ret = benchmarks.get(key, 0)
    marker = " <<<" if key == position else ""
    print(f"  {name:8s}: {ret:+.2f}%{marker}")
print(f"  {'─' * 50}")
print(f"  {'策略轮动':8s}: {total_return:+.2f}%  {'<<<' if total_return > max(benchmarks.values()) else ''}")

# Time distribution
print(f"\n  {'─' * 50}")
print(f"  {'持仓时间分布':^50s}")
print(f"  {'─' * 50}")

# Count days per position
pos_days = {'bond': 0, 'gem': 0, 'nasdaq': 0, 'gold': 0}
pos = 'bond'
eprice = None
for date in all_dates:
    if date < START:
        rows = {}
        valid = True
        for key in POOL:
            r = get_row(dfs[key], date)
            if r is None or pd.isna(r['high_20']): valid = False; break
            rows[key] = r
        if not valid: continue
        ranked = []
        for key in RISK:
            ranked.append({'key': key, 'ret_20': rows[key]['ret_20'], 'b_high': rows[key]['b_high']})
        ranked.sort(key=lambda x: x['ret_20'], reverse=True)
        if pos in RISK and ranked[0]['key'] != pos:
            pos = None
        if pos is None or pos == 'bond':
            top = ranked[0]
            if top['b_high']:
                pos = top['key']
            elif pos is None:
                pos = 'bond'
        continue
    if date > END:
        break
    pos_days[pos] += 1
    rows = {}
    valid = True
    for key in POOL:
        r = get_row(dfs[key], date)
        if r is None or pd.isna(r['high_20']): valid = False; break
        rows[key] = r
    if not valid: continue
    ranked = []
    for key in RISK:
        ranked.append({'key': key, 'ret_20': rows[key]['ret_20'], 'b_high': rows[key]['b_high']})
    ranked.sort(key=lambda x: x['ret_20'], reverse=True)
    if pos in RISK and ranked[0]['key'] != pos:
        pos = None
    if pos is None or pos == 'bond':
        top = ranked[0]
        if top['b_high']:
            pos = top['key']
        elif pos is None:
            pos = 'bond'

total_days = sum(pos_days.values())
for key in ['bond', 'gem', 'nasdaq', 'gold']:
    days = pos_days[key]
    pct = days / total_days * 100 if total_days > 0 else 0
    bar = '#' * int(pct / 2)
    print(f"  {POOL[key][1]:8s}: {days:3d}天 ({pct:5.1f}%) {bar}")

# Trade log
print(f"\n  {'─' * 50}")
print(f"  {'2026年交易记录':^50s}")
print(f"  {'─' * 50}")

total_realized = 0
for t in trades_2026:
    if t['action'] == 'SELL':
        ret_pct = t['ret'] * 100
        total_realized += ret_pct
        print(f"  {t['date'].strftime('%m-%d')} {t['action']:4s} {t['asset']:8s} @ {t['price']:>10.4f}  ({ret_pct:+.2f}%)")
    else:
        print(f"  {t['date'].strftime('%m-%d')} {t['action']:4s} {t['asset']:8s} @ {t['price']:>10.4f}")

print(f"\n  当前持仓: {POOL[position][1]} @ {final_price:.4f}")
print(f"  已实现收益: {total_realized:+.2f}%")
print(f"  未实现浮动: {unrealized_pnl*100:+.2f}%")
print(f"  总收益率:   {total_return:+.2f}%")

# Win rate
closed = [t for t in trades_2026 if t['action'] == 'SELL']
wins = sum(1 for t in closed if t['ret'] > 0)
losses = sum(1 for t in closed if t['ret'] <= 0)
total_trades = wins + losses
if total_trades > 0:
    print(f"  胜率: {wins}/{total_trades} ({wins/total_trades*100:.1f}%)")
    avg_win = np.mean([t['ret']*100 for t in closed if t['ret'] > 0]) if wins > 0 else 0
    avg_loss = np.mean([t['ret']*100 for t in closed if t['ret'] <= 0]) if losses > 0 else 0
    print(f"  平均盈利: {avg_win:+.2f}% / 平均亏损: {avg_loss:+.2f}%")

print()
print("=" * 65)
