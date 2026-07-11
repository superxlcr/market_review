"""候选池过滤器：均线多空排列、市值、行业、上市时长。全部纯函数。"""
from __future__ import annotations
from datetime import datetime
import numpy as np
import pandas as pd

from marketreview.tools.technical import calc_ma, ma_direction
from .config import WinrateConfig


def _latest_non_nan(vals: list[float]) -> float | None:
    for v in reversed(vals):
        if v is not None and not np.isnan(v):
            return float(v)
    return None


def ma_group_state(df_asc: pd.DataFrame, periods: list[int]) -> str:
    """periods 从快到慢（如 [5,10,20]）。返回 多头/空头/其他。
    多头 = 快>中>慢 且最快线向上；空头 = 快<中<慢 且最快线向下。"""
    mas = calc_ma(df_asc, periods)
    latest = []
    for p in periods:
        v = _latest_non_nan(mas[f"MA{p}"])
        if v is None:
            return "其他"
        latest.append(v)
    fast_dir = ma_direction(mas[f"MA{periods[0]}"])
    if all(latest[i] > latest[i + 1] for i in range(len(latest) - 1)):
        return "多头" if fast_dir == "↑" else "其他"
    if all(latest[i] < latest[i + 1] for i in range(len(latest) - 1)):
        return "空头" if fast_dir == "↓" else "其他"
    return "其他"


def passes_ma_arrange(df_asc: pd.DataFrame, want: str, periods: list[int]) -> bool:
    if want == "无关" or not want:
        return True
    return ma_group_state(df_asc, periods) == want


def passes_market_cap(mv_yi: float, cfg: WinrateConfig) -> bool:
    if cfg.mv_min_yi and mv_yi < cfg.mv_min_yi:
        return False
    if cfg.mv_max_yi and mv_yi > cfg.mv_max_yi:
        return False
    return True


def passes_industry(l1: str, l2: str, whitelist: list[str]) -> bool:
    if not whitelist:
        return True
    return (l1 in whitelist) or (l2 in whitelist)


def passes_list_age(list_date: str, on_date: str, min_days: int) -> bool:
    if not list_date or not on_date:
        return False
    try:
        d0 = datetime.strptime(list_date, "%Y%m%d")
        d1 = datetime.strptime(on_date, "%Y%m%d")
    except ValueError:
        return False
    return (d1 - d0).days >= min_days


def passes_all(df_asc: pd.DataFrame, cfg: WinrateConfig, mv_yi: float,
               l1: str, l2: str, list_date: str, on_date: str) -> bool:
    """便宜的先算：上市时长 → 市值 → 行业 → 均线（最贵）。"""
    if not passes_list_age(list_date, on_date, cfg.min_list_days):
        return False
    if not passes_market_cap(mv_yi, cfg):
        return False
    if not passes_industry(l1, l2, cfg.industry_whitelist):
        return False
    if not passes_ma_arrange(df_asc, cfg.short_ma_arrange, [5, 10, 20]):
        return False
    if not passes_ma_arrange(df_asc, cfg.long_ma_arrange, [60, 120, 240]):
        return False
    return True
