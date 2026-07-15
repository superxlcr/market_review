"""Analyze latest winrate run — directional dimensions."""
import pandas as pd
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

RUN = '.winrate_data/20260715_140945'

files = [f for f in os.listdir(RUN) if f.endswith('.csv') and f != 'scan_timing.csv']
all_df = pd.concat([pd.read_csv(os.path.join(RUN, f)) for f in files])
real = all_df[all_df['buy_point'] != '随机基准']

print(f'Total trades (excl random): {len(real)}')
print(f'Columns: {list(real.columns)}')

# ===== 1. Single dimension analysis =====
print('\n' + '='*80)
print('1. SINGLE DIMENSION: wave33_sma3_dir')
print('='*80)
for bp in sorted(real['buy_point'].unique()):
    bp_df = real[real['buy_point'] == bp]
    print(f'\n--- {bp} (n={len(bp_df)}) ---')
    for val in ['up', 'down', 'flat']:
        sub = bp_df[bp_df['wave33_sma3_dir'] == val]
        if len(sub) < 10:
            continue
        wr = sub['success'].mean()
        pnl = sub['pnl_pct'].mean()
        print(f'  wave33={val:<5s} n={len(sub):>5d} WR={wr:.1%} expect={pnl:+.2f}%')

print('\n' + '='*80)
print('2. SINGLE DIMENSION: kd80_sma3_dir')
print('='*80)
for bp in sorted(real['buy_point'].unique()):
    bp_df = real[real['buy_point'] == bp]
    print(f'\n--- {bp} (n={len(bp_df)}) ---')
    for val in ['up', 'down', 'flat']:
        sub = bp_df[bp_df['kd80_sma3_dir'] == val]
        if len(sub) < 10:
            continue
        wr = sub['success'].mean()
        pnl = sub['pnl_pct'].mean()
        print(f'  kd80={val:<5s} n={len(sub):>5d} WR={wr:.1%} expect={pnl:+.2f}%')

print('\n' + '='*80)
print('3. SINGLE DIMENSION: ind_l1_kd80_sma3_dir')
print('='*80)
for bp in sorted(real['buy_point'].unique()):
    bp_df = real[real['buy_point'] == bp]
    print(f'\n--- {bp} (n={len(bp_df)}) ---')
    for val in ['up', 'down', 'flat']:
        sub = bp_df[bp_df['ind_l1_kd80_sma3_dir'] == val]
        if len(sub) < 10:
            continue
        wr = sub['success'].mean()
        pnl = sub['pnl_pct'].mean()
        print(f'  L1_kd80={val:<5s} n={len(sub):>5d} WR={wr:.1%} expect={pnl:+.2f}%')

print('\n' + '='*80)
print('4. SINGLE DIMENSION: ind_l2_kd80_sma3_dir')
print('='*80)
for bp in sorted(real['buy_point'].unique()):
    bp_df = real[real['buy_point'] == bp]
    print(f'\n--- {bp} (n={len(bp_df)}) ---')
    for val in ['up', 'down', 'flat']:
        sub = bp_df[bp_df['ind_l2_kd80_sma3_dir'] == val]
        if len(sub) < 10:
            continue
        wr = sub['success'].mean()
        pnl = sub['pnl_pct'].mean()
        print(f'  L2_kd80={val:<5s} n={len(sub):>5d} WR={wr:.1%} expect={pnl:+.2f}%')

# ===== 2. wave33 + kd80 combo =====
print('\n' + '='*80)
print('5. COMBO: wave33_sma3_dir + kd80_sma3_dir')
print('='*80)
for w33 in ['up', 'down', 'flat']:
    for kd in ['up', 'down', 'flat']:
        sub = real[(real['wave33_sma3_dir'] == w33) & (real['kd80_sma3_dir'] == kd)]
        if len(sub) < 10:
            continue
        wr = sub['success'].mean()
        pnl = sub['pnl_pct'].mean()
        print(f'  w33={w33:<5s} kd80={kd:<5s} n={len(sub):>5d} WR={wr:.1%} expect={pnl:+.2f}%')

# ===== 3. wave33 + L1 combo =====
print('\n' + '='*80)
print('6. COMBO: wave33_sma3_dir + ind_l1_kd80_sma3_dir')
print('='*80)
for w33 in ['up', 'down', 'flat']:
    for l1 in ['up', 'down', 'flat']:
        sub = real[(real['wave33_sma3_dir'] == w33) & (real['ind_l1_kd80_sma3_dir'] == l1)]
        if len(sub) < 10:
            continue
        wr = sub['success'].mean()
        pnl = sub['pnl_pct'].mean()
        print(f'  w33={w33:<5s} L1={l1:<5s} n={len(sub):>5d} WR={wr:.1%} expect={pnl:+.2f}%')

# ===== 4. kd80 + L1 combo =====
print('\n' + '='*80)
print('7. COMBO: kd80_sma3_dir + ind_l1_kd80_sma3_dir')
print('='*80)
for kd in ['up', 'down', 'flat']:
    for l1 in ['up', 'down', 'flat']:
        sub = real[(real['kd80_sma3_dir'] == kd) & (real['ind_l1_kd80_sma3_dir'] == l1)]
        if len(sub) < 10:
            continue
        wr = sub['success'].mean()
        pnl = sub['pnl_pct'].mean()
        print(f'  kd80={kd:<5s} L1={l1:<5s} n={len(sub):>5d} WR={wr:.1%} expect={pnl:+.2f}%')

# ===== 5. Triple: wave33 flat = best, combine with KD80/L1 =====
print('\n' + '='*80)
print('8. TRIPLE: wave33_sma3_dir=flat + kd80_sma3_dir + ind_l1_kd80_sma3_dir')
print('='*80)
w33_flat = real[real['wave33_sma3_dir'] == 'flat']
for kd in ['up', 'down', 'flat']:
    for l1 in ['up', 'down', 'flat']:
        sub = w33_flat[(w33_flat['kd80_sma3_dir'] == kd) & (w33_flat['ind_l1_kd80_sma3_dir'] == l1)]
        if len(sub) < 10:
            continue
        wr = sub['success'].mean()
        pnl = sub['pnl_pct'].mean()
        print(f'  w33=flat kd80={kd:<5s} L1={l1:<5s} n={len(sub):>5d} WR={wr:.1%} expect={pnl:+.2f}%')

# ===== 6. L1 streak analysis =====
print('\n' + '='*80)
print('9. ind_l1_kd80_streak vs winrate')
print('='*80)
for s in sorted(real['ind_l1_kd80_streak'].dropna().unique()):
    sub = real[real['ind_l1_kd80_streak'] == s]
    if len(sub) < 20:
        continue
    wr = sub['success'].mean()
    pnl = sub['pnl_pct'].mean()
    print(f'  L1_streak={int(s):>3d} n={len(sub):>5d} WR={wr:.1%} expect={pnl:+.2f}%')

# ===== 7. L2 streak analysis =====
print('\n' + '='*80)
print('10. ind_l2_kd80_streak vs winrate')
print('='*80)
for s in sorted(real['ind_l2_kd80_streak'].dropna().unique()):
    sub = real[real['ind_l2_kd80_streak'] == s]
    if len(sub) < 20:
        continue
    wr = sub['success'].mean()
    pnl = sub['pnl_pct'].mean()
    print(f'  L2_streak={int(s):>3d} n={len(sub):>5d} WR={wr:.1%} expect={pnl:+.2f}%')

# ===== 8. wave33_sma3 numeric bins =====
print('\n' + '='*80)
print('11. wave33_sma3 value vs winrate')
print('='*80)
real['w33_sma3_bin'] = pd.cut(real['wave33_sma3'], bins=[0, 10, 30, 60, 100, 200, 500, 9999])
for b in real['w33_sma3_bin'].cat.categories:
    sub = real[real['w33_sma3_bin'] == b]
    if len(sub) < 20:
        continue
    wr = sub['success'].mean()
    pnl = sub['pnl_pct'].mean()
    print(f'  w33_sma3={str(b):>15s} n={len(sub):>5d} WR={wr:.1%} expect={pnl:+.2f}%')

# ===== 9. kd80_sma3 numeric bins =====
print('\n' + '='*80)
print('12. kd80_sma3 value vs winrate')
print('='*80)
real['kd80_sma3_bin'] = pd.cut(real['kd80_sma3'], bins=[0, 200, 400, 600, 800, 1000, 99999])
for b in real['kd80_sma3_bin'].cat.categories:
    sub = real[real['kd80_sma3_bin'] == b]
    if len(sub) < 20:
        continue
    wr = sub['success'].mean()
    pnl = sub['pnl_pct'].mean()
    print(f'  kd80_sma3={str(b):>15s} n={len(sub):>5d} WR={wr:.1%} expect={pnl:+.2f}%')

# ===== 10. Best buy point + best direction combo =====
print('\n' + '='*80)
print('13. BEST: 量价节点严格 + wave33_sma3_dir=flat')
print('='*80)
bp_best = real[(real['buy_point'] == '量价节点严格') & (real['wave33_sma3_dir'] == 'flat')]
print(f'  All: n={len(bp_best)} WR={bp_best["success"].mean():.1%} expect={bp_best["pnl_pct"].mean():+.2f}%')
for kd in ['up', 'down', 'flat']:
    sub = bp_best[bp_best['kd80_sma3_dir'] == kd]
    if len(sub) < 5:
        continue
    wr = sub['success'].mean()
    pnl = sub['pnl_pct'].mean()
    print(f'  + kd80={kd:<5s} n={len(sub):>5d} WR={wr:.1%} expect={pnl:+.2f}%')
