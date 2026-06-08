"""
Index weight contribution analysis.

Computes how much each constituent stock contributed to the index's daily
point change.  Used by Dashboard (display) and Agent 1 (LLM analysis).

Contribution formula (derivation):
  Let W_i = stock i's weight in the index (percentage, e.g. 3.12)
  Let R_i = stock i's daily return (percentage, e.g. +3.30)
  Let C   = index closing price

  Index daily return (%) approx Sigma (W_i / 100) x (R_i / 100)   ... in decimal
                          = Sigma W_i x R_i / 10000           ... in percentage

  Contribution of stock i in points:
    contrib_i = (W_i / 100) x (R_i / 100) x C
              = W_i x R_i x C / 10000  <- used in the code below
"""

from datetime import datetime, timedelta
from ..data.data_provider import DataProvider


# TODO: L1 industries where the L1 name is specific enough - use L1 directly.
# For all other industries, the more granular L2 name is shown.
# Add/remove codes here as needed based on real-world observation.
L1_OVERRIDE_L1 = {
    "801780.SI",  # 银行    -> "银行" is sufficient
    "801960.SI",  # 石油石化 -> "石油石化" is sufficient
}


def pick_industry_label(l1_code: str, l1_name: str, l2_name: str) -> str:
    """Choose the display label for a stock's industry (L1 or L2)."""
    if l1_code in L1_OVERRIDE_L1:
        return l1_name
    return l2_name


def build_index_contribution(
    index_code: str,
    trade_date: str,
    dp: DataProvider,
    top_n: int = 5,
) -> dict | None:
    """
    Build contribution analysis for an index on a given trading date.

    Args:
        index_code:  '000001.SH' or '399006.SZ'
        trade_date:  YYYYMMDD or YYYY-MM-DD
        dp:          DataProvider instance (single entry point for all data)
        top_n:       number of top gainers/losers to return (default 5)

    Returns:
        {
          "index": {close, pre_close, chg_pts, chg_pct},
          "gainers": [{code, name, industry, weight, chg_pct, contrib}],
          "losers":  [{code, name, industry, weight, chg_pct, contrib}],
        }
        or None if index/weight data is unavailable.
    """
    trade_date = trade_date.replace("-", "")

    # 1. Index OHLC
    idx_rows = dp.get_daily(index_code, end_date=trade_date, lookback_days=2)
    if not idx_rows or len(idx_rows) < 2:
        return None
    latest = idx_rows[0]
    prev = idx_rows[1]
    close = float(latest["close"])
    pre_close = float(prev["close"])
    chg_pts = round(close - pre_close, 2)
    chg_pct = round((close / pre_close - 1) * 100, 2)

    # 2. Constituent weights
    weights = dp.get_index_weights(index_code, trade_date)
    if not weights:
        return None

    # 3. Stock prices for all constituents
    all_codes = [w["con_code"] for w in weights]
    prices = dp.get_daily_batch(all_codes, trade_date)

    # 4. Compute contribution for each constituent
    items = []
    for w in weights:
        code = w["con_code"]
        p = prices.get(code)
        if p is None:
            continue
        chg = p["change_pct"]
        # contrib = weight% x chg% x index_close / 10000
        contrib = round(w["weight"] * chg * close / 10000, 2)
        items.append({
            "code": code,
            "weight": round(w["weight"], 2),
            "chg_pct": chg,
            "contrib": contrib,
        })

    if not items:
        return None

    # Sort by contribution descending (largest positive = top gainer,
    # largest negative = top loser)
    items.sort(key=lambda x: x["contrib"], reverse=True)

    gainers = items[:top_n]
    losers = items[-top_n:][::-1]  # most negative first

    # 5. Industry labels (only for the displayed 2*top_n stocks)
    display_codes = [g["code"] for g in gainers] + [l["code"] for l in losers]
    industries = dp.get_stock_industries(display_codes)

    def _attach_name_industry(item: dict) -> dict:
        ind = industries.get(item["code"], {})
        l1_code = ind.get("l1_code", "")
        l1_name = ind.get("l1_name", "")
        l2_name = ind.get("l2_name", "")
        return {
            "code": item["code"],
            "name": ind.get("name", item["code"]),
            "industry": pick_industry_label(l1_code, l1_name, l2_name),
            "weight": item["weight"],
            "chg_pct": item["chg_pct"],
            "contrib": item["contrib"],
        }

    return {
        "index": {
            "close": close,
            "pre_close": pre_close,
            "chg_pts": chg_pts,
            "chg_pct": chg_pct,
        },
        "gainers": [_attach_name_industry(g) for g in gainers],
        "losers": [_attach_name_industry(l) for l in losers],
    }
