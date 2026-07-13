---
name: query-stock-industry
description: "How to query a stock's L1/L2/L3 industry classification from the command line"
metadata: 
  node_type: memory
  type: project
  tags: 
    - industry
    - dashboard
    - tools
  originSessionId: 48ae945a-00c7-4ec6-86d9-41082ccc8e80
---

# Query Stock Industry Classification

When you need to look up a stock's L1/L2/L3 industry, use this one-liner pattern:

```bash
set -a && source /i/AIcode/marketreview/.env && set +a && python -c "
import os; import sys; sys.stdout.reconfigure(encoding='utf-8')
from src.marketreview.data.data_provider import DataProvider
dp = DataProvider(tushare_token=os.environ['TUSHARE_TOKEN'])

# Put stock names or codes below:
names = ['中国电信', '长盛轴承']
out = os.path.expanduser('~/ind_query.txt')
with open(out, 'w', encoding='utf-8') as f:
    for name in names:
        df = dp._api.stock_basic(name=name)
        if df is not None and not df.empty:
            ts_code = df.iloc[0]['ts_code']
            ind = dp.get_stock_industries([ts_code])
            info = ind.get(ts_code, {})
            f.write(f'{name} ({ts_code}):\n')
            f.write(f'  L1: {info.get(\"l1_code\",\"?\")} {info.get(\"l1_name\",\"?\")}\n')
            f.write(f'  L2: {info.get(\"l2_code\",\"?\")} {info.get(\"l2_name\",\"?\")}\n')
            f.write(f'  L3: {info.get(\"l3_code\",\"?\")} {info.get(\"l3_name\",\"?\")}\n')
            f.write('\n')
        else:
            f.write(f'{name}: not found via stock_basic\n\n')
print('Done')
" && cat ~/ind_query.txt
```

**Key points:**
- `.env` must be sourced for `TUSHARE_TOKEN`
- Write to file + `cat` avoids Windows terminal encoding garbled output
- `sys.stdout.reconfigure(encoding='utf-8')` for Python side
- The `stock_basic` API call (not cached) resolves name → ts_code; `get_stock_industries` reads from cache

Related: [[industry-label-override]]
