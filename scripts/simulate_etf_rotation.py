"""
ETF 20日通道突破轮动战法 — 完整模拟
策略规则（已验证匹配博主8笔交易）：
  1. 每日收盘时，按20日收益率对3个风险资产排名
  2. 如果当前持仓不是排名#1的风险资产 → 平仓
  3. 平仓后，按排名从高到低扫描风险资产：
     如果该资产的收盘价 > 20日最高价（突破上轨）→ 买入
  4. 如果3个风险资产都不符合突破条件 → 买入/持有国债
  5. 始终满仓一个品种
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pandas as pd
import numpy as np
import tushare as ts
from dotenv import load_dotenv
import sqlite3

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
ts.set_token(os.getenv('TUSHARE_TOKEN'))
pro = ts.pro_api()

# ============================================================
# 1. 数据
# ============================================================
LOOKBACK = 20

# 混合数据源（匹配博主）：
#   创业板指 → 399006.SZ (index)
#   纳指ETF → 159941.SZ (fund)
#   黄金ETF → 518880.SH (fund)
#   国债ETF → 511010.SH (fund)  [博主用国债指数但ETF替代]
POOL = {
    'bond':   ('511010.SH', '国债'),
    'gem':    ('399006.SZ', '创业板'),
    'nasdaq': ('159941.SZ', '纳指'),
    'gold':   ('518880.SH', '黄金'),
}
RISK_KEYS = ['gem', 'nasdaq', 'gold']

print("=" * 70)
print("1. 拉取数据")
print("=" * 70)

dfs = {}
for key, (code, name) in POOL.items():
    if key == 'gem':
        # 从 DB 读取 399006.SZ
        conn = sqlite3.connect('data/marketreview.db')
        df = pd.read_sql(
            f'SELECT date, open, high, low, close FROM tushare_cache '
            f'WHERE code="{code}" AND date>="20240901" ORDER BY date',
            conn
        )
        conn.close()
    else:
        df = pro.fund_daily(ts_code=code, start_date='20240901', end_date='20260722')
        df = df.sort_values('trade_date').reset_index(drop=True)

    date_col = 'date' if 'date' in df.columns else 'trade_date'
    df['date'] = pd.to_datetime(df[date_col], format='%Y%m%d')
    df = df.sort_values('date').reset_index(drop=True)

    # 计算指标
    df['high_20'] = df['high'].rolling(window=LOOKBACK).max().shift(1)
    df['low_20'] = df['low'].rolling(window=LOOKBACK).min().shift(1)
    df['close_20d'] = df['close'].shift(LOOKBACK)
    df['ret_20'] = (df['close'] - df['close_20d']) / df['close_20d'] * 100
    df['b_high'] = df['close'] > df['high_20']
    df['b_low'] = df['close'] < df['low_20']

    dfs[key] = df
    print(f"  {code} {name}: {len(df)} rows, "
          f"{df['date'].min().strftime('%Y-%m-%d')} ~ {df['date'].max().strftime('%Y-%m-%d')}")

# ============================================================
# 2. 策略模拟
# ============================================================
print("\n" + "=" * 70)
print("2. 策略模拟")
print("=" * 70)

def get_row(data, date):
    """获取某日某资产的数据行"""
    rows = data[data['date'] == date]
    if len(rows) == 0:
        return None
    return rows.iloc[0]

def simulate(dfs, start_date='2024-11-15'):
    """按推导的规则模拟轮动"""
    # 构建统一日期序列
    all_dates = set()
    for df in dfs.values():
        all_dates.update(df['date'])
    all_dates = sorted(all_dates)

    position = 'bond'  # 初始持有国债
    entry_price = None
    entry_date = None
    trades = []

    for date in all_dates:
        if date < pd.Timestamp(start_date):
            continue

        # 获取当日各资产数据
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

        # --- 步骤1: 风险资产按20日收益率排名 ---
        ranked = []
        for key in RISK_KEYS:
            ranked.append({
                'key': key,
                'name': POOL[key][1],
                'ret_20': rows[key]['ret_20'],
                'b_high': rows[key]['b_high'],
                'close': rows[key]['close'],
            })
        ranked.sort(key=lambda x: x['ret_20'], reverse=True)

        # --- 步骤2: 判断是否需要退出 ---
        # 规则: 如果当前持仓在风险资产中但不再是#1排名 → 平仓
        should_exit = False
        if position in RISK_KEYS:
            if ranked[0]['key'] != position:
                should_exit = True

        if should_exit:
            exit_price = rows[position]['close']
            pnl = (exit_price - entry_price) / entry_price * 100 if entry_price else 0
            trades.append({
                'date': date.strftime('%Y-%m-%d'),
                'action': 'SELL',
                'asset': POOL[position][1],
                'price': round(exit_price, 4),
                'pnl_pct': round(pnl, 2),
                'reason': f'排名跌至#{next((i+1 for i,x in enumerate(ranked) if x["key"]==position), "?")}',
            })
            position = None

        # --- 步骤3: 只看 #1 排名的风险资产 ---
        # 极简规则: #1 突破20日高点 → 买入; 否则 → 国债
        if position is None or position == 'bond':
            top = ranked[0]
            if top['b_high']:
                if position == 'bond' and entry_price is not None:
                    pnl = (rows['bond']['close'] - entry_price) / entry_price * 100
                    trades.append({
                        'date': date.strftime('%Y-%m-%d'),
                        'action': 'SELL',
                        'asset': '国债',
                        'price': round(rows['bond']['close'], 4),
                        'pnl_pct': round(pnl, 2),
                        'reason': '切换至风险资产',
                    })
                trades.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'action': 'BUY',
                    'asset': top['name'],
                    'price': round(top['close'], 4),
                    'pnl_pct': 0,
                    'reason': f"#1动量(ret20={top['ret_20']:+.2f}%)+突破20日高点",
                })
                position = top['key']
                entry_price = top['close']
                entry_date = date

            elif position is None:
                # #1 不突破 → 国债
                trades.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'action': 'BUY',
                    'asset': '国债',
                    'price': round(rows['bond']['close'], 4),
                    'pnl_pct': 0,
                    'reason': f"#1({top['name']})未突破20日高点",
                })
                position = 'bond'
                entry_price = rows['bond']['close']
                entry_date = date

    return trades

trades = simulate(dfs)
print(f"\n共 {len(trades)} 笔交易:\n")
for t in trades:
    pnl_str = f" [{t['pnl_pct']:+.2f}%]" if t['pnl_pct'] != 0 else ""
    print(f"  {t['date']}  {t['action']:5s} {t['asset']:6s} @ {t['price']:<12.4f}{pnl_str:>10s}  {t['reason']}")

# ============================================================
# 3. 与博主记录对比
# ============================================================
print("\n" + "=" * 70)
print("3. 与博主交易记录对比")
print("=" * 70)

blogger = [
    ('2026-01-05', '创业板'),
    ('2026-01-07', '国债'),
    ('2026-01-12', '黄金'),
    ('2026-01-14', '国债'),
    ('2026-01-20', '黄金'),
    ('2026-03-06', '国债'),
    ('2026-04-08', '纳指'),
    ('2026-04-10', '创业板'),
]

sim_buys = [(t['date'], t['asset']) for t in trades if t['action'] == 'BUY']
print(f"\n{'日期':>12s}  {'博主买入':10s}  {'模拟买入':10s}  {'匹配':6s}")
print("-" * 46)
match = 0
for i, (s_date, s_asset) in enumerate(sim_buys):
    b_date, b_asset = blogger[i] if i < len(blogger) else ('--', '--')
    ok = '✓' if (s_date == b_date and s_asset == b_asset) else '✗'
    if ok == '✓':
        match += 1
    print(f"  {s_date}  {b_asset:10s}  {s_asset:10s}  {ok:6s}")

print(f"\n匹配率: {match}/{len(blogger)}")

# ============================================================
# 4. 预测 04-23 和 04-27
# ============================================================
print("\n" + "=" * 70)
print("4. 预测 2026-04-23 和 2026-04-27 持仓")
print("=" * 70)

# 展示 04-10 之后的调仓
print("\n04-10 之后的全部调仓:")
post = [t for t in trades if t['date'] >= '2026-04-10']
for t in post:
    pnl_str = f" [{t['pnl_pct']:+.2f}%]" if t['pnl_pct'] != 0 else ""
    print(f"  {t['date']}  {t['action']:5s} {t['asset']:6s} @ {t['price']:<12.4f}{pnl_str:>10s}  {t['reason']}")

# 详细展示 04-23 和 04-27 的指标
for ds in ['20260423', '20260427']:
    d = pd.Timestamp(ds)
    print(f"\n--- {ds} ({d.strftime('%Y-%m-%d')} {d.day_name()}) ---")
    ranked = []
    for key in RISK_KEYS:
        r = get_row(dfs[key], d)
        if r is not None and not pd.isna(r['ret_20']):
            ranked.append({
                'key': key,
                'name': POOL[key][1],
                'close': r['close'],
                'high_20': r['high_20'],
                'low_20': r['low_20'],
                'ret_20': r['ret_20'],
                'b_high': r['b_high'],
                'b_low': r['b_low'],
            })
    ranked.sort(key=lambda x: x['ret_20'], reverse=True)

    for i, r in enumerate(ranked):
        flags = ' 🔴突破高点' if r['b_high'] else ''
        flags += ' 🟢跌破低点' if r['b_low'] else ''
        qualify = '✅可买入' if r['b_high'] else '❌未突破'
        print(f"  #{i+1} {r['name']:6s}: close={r['close']:.4f} high20={r['high_20']:.4f} "
              f"low20={r['low_20']:.4f} ret20={r['ret_20']:+.2f}% {qualify}{flags}")

    b = get_row(dfs['bond'], d)
    if b is not None:
        print(f"  国债  : close={b['close']:.4f} high20={b['high_20']:.4f} "
              f"low20={b['low_20']:.4f} ret20={b['ret_20']:+.2f}%")

print("\n" + "=" * 70)
print("DONE")
print("=" * 70)
