"""补齐历史 daily_basic（市值）到全回测窗口。幂等：已缓存区间自动跳过。

用法:
    .venv/Scripts/python scripts/backfill_market_cap.py [START] [END]

默认 START=20230921, END=最新交易日。
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(PROJECT_ROOT, "src")
sys.path.insert(0, SRC)

from dotenv import load_dotenv
load_dotenv()

from marketreview.data.data_provider import DataProvider  # noqa: E402


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "20230921"
    end = sys.argv[2] if len(sys.argv) > 2 else None

    dp = DataProvider(tushare_token=os.getenv("TUSHARE_TOKEN"))
    if end is None:
        dates = dp.cache.get_daily_dates_in_range("20230921", "20991231")
        end = dates[-1] if dates else "20230921"

    print(f"补齐市值: {start} ~ {end}")

    def cb(kind, i, total, label):
        print(f"  [{kind}] {i}/{total} {label}")

    pages = dp._ensure_daily_basic_loaded(start, end, progress_cb=cb)
    print(f"完成，拉取 {pages} 页。")

    # 校验覆盖
    dates = dp.cache.get_daily_basic_dates_in_range(start, end)
    print(f"daily_basic 覆盖交易日: {len(dates)} 个，"
          f"{dates[0] if dates else '?'} ~ {dates[-1] if dates else '?'}")


if __name__ == "__main__":
    main()
