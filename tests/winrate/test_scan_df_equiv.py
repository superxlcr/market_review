"""验证 scan_stock 用 pd.DataFrame(klines).iloc 切片 等价于 rows_to_df(klines[:i+1])。
数据层改动必须严格等价。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
for line in open(os.path.join(os.path.dirname(__file__), "..", "..", ".env"), encoding="utf-8"):
    if line.startswith("TUSHARE_TOKEN="):
        os.environ["TUSHARE_TOKEN"] = line.split("=", 1)[1].strip()

import pandas as pd
from marketreview.data.data_provider import DataProvider
from marketreview.winrate.scan_engine import prepare_klines
from marketreview.tools.technical import rows_to_df

dp = DataProvider(os.environ["TUSHARE_TOKEN"])


def test_df_upto_view_equivalent_to_rows_to_df():
    """pd.DataFrame(klines).iloc[:i+1] 与 rows_to_df(klines[:i+1]) 关键列等价。"""
    b = [x for x in dp.cache.get_stock_basic() if not x["is_st"]][0]
    rows_desc = dp.cache.get_daily(b["ts_code"], limit=2000)
    klines = prepare_klines(rows_desc)
    n = len(klines)
    assert n >= 60

    df_full = pd.DataFrame(klines)
    cols = ["open", "high", "low", "close", "vol", "amount", "adj_factor", "date"]
    mismatches = 0
    for i in [60, 200, 500, n - 1]:
        df_view = df_full.iloc[:i + 1].reset_index(drop=True)
        df_old = rows_to_df(klines[:i + 1])
        for col in cols:
            if col not in df_view.columns or col not in df_old.columns:
                continue
            a = df_view[col].tolist()
            c = df_old[col].tolist()
            # 数值列 NaN 比较
            if not (a == c or all((x != x and y != y) or x == y for x, y in zip(a, c))):
                mismatches += 1
                print(f"  i={i} col={col} 不一致")
    assert mismatches == 0, f"df 视图与 rows_todf 不等价: {mismatches}"
