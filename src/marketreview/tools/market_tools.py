"""
CrewAI BaseTool wrappers that Agent 1 uses.
Each tool wraps a function from technical.py or contribution.py so the LLM can call it.
"""

from crewai.tools import BaseTool
from typing import Type, Optional
from pydantic import BaseModel, Field
import json

from ..data.data_provider import DataProvider
from .technical import build_technical_summary
from .contribution import compute_index_contribution, INDEX_WEIGHTS


# Singleton — initialised at crew startup
_data_provider: Optional[DataProvider] = None


def init_data_provider(token: str):
    global _data_provider
    _data_provider = DataProvider(tushare_token=token)


# ------- Tool 1: Get Index Technicals -------

class GetIndexTechnicalsInput(BaseModel):
    index_code: str = Field(..., description="指数代码，如 000001.SH（上证）或 399006.SZ（创业板）")
    index_name: str = Field(..., description="指数中文名，如 '上证指数'")
    lookback_days: int = Field(360, description="回看交易日数，默认360天（约1.5年，覆盖年线MA240）")


class GetIndexTechnicalsTool(BaseTool):
    name: str = "get_index_technicals"
    description: str = (
        "获取指定指数的完整技术分析摘要：包含K线形态、均线排列+方向、成交量分析、"
        "KDJ/RSI/BIAS等指标。用于Agent 1对大盘指数进行技术面评估。"
    )
    args_schema: Type[BaseModel] = GetIndexTechnicalsInput

    def _run(self, index_code: str, index_name: str, lookback_days: int = 120) -> str:
        if _data_provider is None:
            return json.dumps({"error": "DataProvider未初始化"}, ensure_ascii=False)
        rows = _data_provider.get_daily(index_code, lookback_days=lookback_days)
        summary = build_technical_summary(index_code, index_name, rows)
        return json.dumps(summary, ensure_ascii=False, indent=2)


# ------- Tool 2: Get Market Breadth -------

class GetMarketBreadthInput(BaseModel):
    trade_date: str = Field(..., description="交易日期 YYYYMMDD 格式，如 20250604")


class GetMarketBreadthTool(BaseTool):
    name: str = "get_market_breadth"
    description: str = (
        "获取全市场宽度数据：涨跌家数比、涨停跌停数、各交易所成交额。"
        "数据通过 DataProvider 获取。"
    )
    args_schema: Type[BaseModel] = GetMarketBreadthInput

    def _run(self, trade_date: str) -> str:
        if _data_provider is None:
            return json.dumps({"error": "DataProvider未初始化"}, ensure_ascii=False)
        try:
            breadth = _data_provider.get_market_breadth(trade_date)
            if breadth is None:
                return json.dumps({"error": f"无 {trade_date} 市场宽度数据"}, ensure_ascii=False)

            breadth["up_down_ratio"] = f"{breadth['up']}:{breadth['down']}"
            return json.dumps(breadth, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)


# ------- Tool 3: Get Index Contribution -------

class GetIndexContributionInput(BaseModel):
    index_code: str = Field(..., description="指数代码 000001.SH 或 399006.SZ")


class GetIndexContributionTool(BaseTool):
    name: str = "get_index_contribution"
    description: str = (
        "获取指数权重股的涨跌贡献分析。显示前10大权重股各自的涨跌幅和对指数的贡献点数。"
    )
    args_schema: Type[BaseModel] = GetIndexContributionInput

    def _run(self, index_code: str) -> str:
        if _data_provider is None:
            return json.dumps({"error": "DataProvider未初始化"}, ensure_ascii=False)

        weights = INDEX_WEIGHTS.get(index_code, {}).get("weight_codes", [])
        if not weights:
            return json.dumps({"error": f"无 {index_code} 权重数据"}, ensure_ascii=False)

        items = []
        for code, name, weight in weights:
            rows = _data_provider.get_daily(code, lookback_days=2)
            if len(rows) >= 2:
                prev_close = rows[1]["close"]
                latest_close = rows[0]["close"]
                change_pct = round((latest_close / prev_close - 1) * 100, 2)
            else:
                change_pct = 0
            items.append({
                "code": code, "name": name, "weight_pct": weight,
                "change_pct": change_pct,
            })

        result = compute_index_contribution(index_code, items)
        return json.dumps(result, ensure_ascii=False, indent=2)
