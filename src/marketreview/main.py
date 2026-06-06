#!/usr/bin/env python
"""
A股复盘系统 — 手动触发入口。
用法: python -m src.marketreview.main 20250604
      或: python -m src.marketreview.main  (默认今天)
"""
import sys
import os
import warnings
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from marketreview.crew import Marketreview
from marketreview.tools.market_tools import init_data_provider

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")


def run(trade_date: str = None):
    """Run Agent 1 market analysis for the given trading date."""
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y%m%d")

    # Init data layer
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 环境变量未设置，请在 .env 文件中配置")
    init_data_provider(token)

    inputs = {
        "trade_date": trade_date,
    }

    print(f"\n{'='*60}")
    print(f"  Agent 1 大盘分析 — {trade_date}")
    print(f"{'='*60}\n")

    try:
        result = Marketreview().crew().kickoff(inputs=inputs)
        print(f"\n{'='*60}")
        print(f"  分析完成")
        print(f"{'='*60}\n")
        return result
    except Exception as e:
        raise Exception(f"Agent 1 运行失败: {e}")


if __name__ == "__main__":
    trade_date = sys.argv[1] if len(sys.argv) > 1 else None
    run(trade_date)
