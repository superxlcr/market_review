"""
Weight contribution analysis for indices and sectors (§4.4).
Only used by Agent 1 (index) and Agent 2 (sector). Agent 3 does not use this.
"""

import pandas as pd
import numpy as np
from .technical import rows_to_df


# Simplified top-10 weights for SSE Composite (上证) and ChiNext (创业板)
# In production this should come from a config or be fetched dynamically.
INDEX_WEIGHTS = {
    "000001.SH": {
        "weight_codes": [
            ("600519.SH", "贵州茅台", 5.2),
            ("601398.SH", "工商银行", 3.1),
            ("601939.SH", "建设银行", 2.4),
            ("601288.SH", "农业银行", 2.3),
            ("601857.SH", "中国石油", 2.0),
            ("601988.SH", "中国银行", 1.9),
            ("600036.SH", "招商银行", 1.8),
            ("601628.SH", "中国人寿", 1.6),
            ("600028.SH", "中国石化", 1.5),
            ("601318.SH", "中国平安", 1.4),
        ]
    },
    "399006.SZ": {
        "weight_codes": [
            ("300750.SZ", "宁德时代", 15.2),
            ("300059.SZ", "东方财富", 7.1),
            ("300760.SZ", "迈瑞医疗", 5.8),
            ("300124.SZ", "汇川技术", 4.5),
            ("300274.SZ", "阳光电源", 3.8),
            ("300015.SZ", "爱尔眼科", 3.2),
            ("300014.SZ", "亿纬锂能", 2.9),
            ("300122.SZ", "智飞生物", 2.5),
            ("300450.SZ", "先导智能", 2.1),
            ("300408.SZ", "三环集团", 1.8),
        ]
    },
}


def compute_index_contribution(index_code: str, weight_rows: list[dict]) -> dict:
    """
    Compute weighted contribution of top constituents to index movement.

    weight_rows: list of {code, name, weight_pct, change_pct} for each constituent.
    Returns {total_contribution, constituents: [{name, weight_pct, change_pct, contribution}]}
    """
    total = 0.0
    items = []
    for wr in weight_rows:
        contrib = wr["weight_pct"] * wr.get("change_pct", 0) / 100
        total += contrib
        items.append({
            "name": wr["name"],
            "weight_pct": wr["weight_pct"],
            "change_pct": wr.get("change_pct", 0),
            "contribution": round(contrib, 4),
        })
    return {
        "total_contribution": round(total, 2),
        "constituents": sorted(items, key=lambda x: abs(x["contribution"]), reverse=True),
    }
