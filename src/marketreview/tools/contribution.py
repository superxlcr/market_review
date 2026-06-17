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
from ..log_util import get_logger

log = get_logger(__name__)


# Industry label override logic:
#   默认 → L2
#   命中 L1_OVERRIDE_L1 (by L1 code) → L1 name
#   命中 L3_OVERRIDE_L3 (by L3 code) → L3 name
# L3 override 现在直接用 l3_code 做键，粒度最精确。

L1_OVERRIDE_L1 = {
    "801780.SI",  # 银行     -> "银行" is sufficient
    "801960.SI",  # 石油石化  -> "石油石化" is sufficient
    "801950.SI",  # 煤炭     -> "煤炭" is sufficient
    "801750.SI",  # 计算机   -> "计算机" is sufficient
    "801150.SI",  # 医药生物  -> "医药生物" is sufficient
    "801790.SI",  # 非银金融  -> "非银金融" is sufficient
    "801120.SI",  # 食品饮料  -> "食品饮料" is sufficient
    "801890.SI",  # 机械设备  -> "机械设备" is sufficient
}

L3_OVERRIDE_L3 = {
    "850781.SI",  # 机器人       (L2=自动化设备)
    "850814.SI",  # 数字芯片设计   (L2=半导体)
    "850813.SI",  # 半导体材料    (L2=半导体)
    "850818.SI",  # 半导体设备    (L2=半导体)
    "850817.SI",  # 集成电路封测   (L2=半导体)
    "850816.SI",  # 集成电路制造   (L2=半导体)
    "850812.SI",  # 分立器件      (L2=半导体)
    "850823.SI",  # 被动元件      (L2=元件)
    "850822.SI",  # 印制电路板    (L2=元件)
    "850543.SI",  # 锂           (L2=能源金属)
    "850542.SI",  # 钨           (L2=小金属)
    "857353.SI",  # 逆变器       (L2=光伏设备)
}


def pick_industry_label(l1_code: str, l1_name: str,
                        l2_code: str, l2_name: str,
                        l3_code: str = "", l3_name: str = "") -> str:
    """Choose the display label for a stock's industry (L1 / L2 / L3)."""
    if l1_code in L1_OVERRIDE_L1:
        return l1_name
    if l3_code in L3_OVERRIDE_L3:
        return l3_name or l2_name  # fall back to L2 if L3 is empty
    return l2_name


def pick_industry_code(l1_code: str, l2_code: str,
                       l3_code: str = "") -> str:
    """Return the industry code that matches pick_industry_label's choice.

    This is the code corresponding to whichever level was selected for
    display — used when aggregating by industry for drill-down purposes.
    """
    if l1_code in L1_OVERRIDE_L1:
        return l1_code
    if l3_code in L3_OVERRIDE_L3:
        return l3_code or l2_code
    return l2_code


def build_index_contribution(
    index_code: str,
    trade_date: str,
    dp: DataProvider,
    top_n: int = 10,
) -> dict | None:
    """
    Build contribution analysis for an index on a given trading date.

    Args:
        index_code:  '000001.SH' or '399006.SZ'
        trade_date:  YYYYMMDD or YYYY-MM-DD
        dp:          DataProvider instance (single entry point for all data)
        top_n:       number of top gainers/losers to return (default 10)

    Returns:
        {
          "index": {close, pre_close, chg_pts, chg_pct},
          "gainers": [{code, name, industry, weight, chg_pct, contrib}],
          "losers":  [{code, name, industry, weight, chg_pct, contrib}],
        }
        or None if index/weight data is unavailable.
    """
    trade_date = trade_date.replace("-", "")

    # 0. Check cache — return if already computed for this (index, date, top_n)
    cached = dp.cache.get_index_contribution_cache(index_code, trade_date, top_n)
    if cached is not None:
        log.debug("build_index_contribution: %s @ %s (top_n=%d) — cache hit",
                  index_code, trade_date, top_n)
        return cached

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

    # 2. Constituent list (from latest index_weight, monthly list)
    cached_weights = dp.get_index_weights(index_code, trade_date)
    if not cached_weights:
        return None

    all_codes = [w["con_code"] for w in cached_weights]

    # 3. Stock prices for all constituents
    prices = dp.get_daily_batch(all_codes, trade_date)

    # 4. Compute weights from daily circ_mv (流通市值)
    #    Falls back to cached monthly weights if market-cap data is unavailable.
    #    circ_mv is preferred over total_mv because it reflects actual tradable
    #    shares — many A-share stocks have large non-tradable portions (state-owned,
    #    founder shares) that inflate total_mv without contributing to daily trading.
    market_caps = dp.get_circ_mv(trade_date)
    circ_mv_sum = sum(market_caps.get(code, 0) for code in all_codes)
    use_dynamic_weight = circ_mv_sum > 0
    weight_type = "dynamic" if use_dynamic_weight else "cached"
    if use_dynamic_weight:
        log.info("build_index_contribution: %s @ %s — using dynamic weights "
                 "(circ_mv_sum=%.0f万, constituents=%d)",
                 index_code, trade_date, circ_mv_sum, len(all_codes))
    else:
        log.warning("build_index_contribution: %s @ %s — "
                    "circ_mv unavailable, falling back to cached weights",
                    index_code, trade_date)

    # 5. Compute contribution for each constituent
    items = []
    for w in cached_weights:
        code = w["con_code"]
        p = prices.get(code)
        if p is None:
            continue
        chg = p["change_pct"]

        if use_dynamic_weight:
            mv = market_caps.get(code, 0)
            weight_pct = round(mv / circ_mv_sum * 100, 4) if mv > 0 else 0
        else:
            weight_pct = w["weight"]

        # contrib = weight% x chg% x index_close / 10000
        contrib = round(weight_pct * chg * close / 10000, 2)
        items.append({
            "code": code,
            "weight": round(weight_pct, 2),
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
        l2_code = ind.get("l2_code", "")
        l2_name = ind.get("l2_name", "")
        l3_code = ind.get("l3_code", "")
        l3_name = ind.get("l3_name", "")
        return {
            "code": item["code"],
            "name": ind.get("name") or "N/A",
            "industry": pick_industry_label(l1_code, l1_name,
                                            l2_code, l2_name,
                                            l3_code, l3_name) or "N/A",
            "industry_code": pick_industry_code(l1_code, l2_code, l3_code),
            "weight": item["weight"],
            "chg_pct": item["chg_pct"],
            "contrib": item["contrib"],
        }

    result = {
        "index": {
            "close": close,
            "pre_close": pre_close,
            "chg_pts": chg_pts,
            "chg_pct": chg_pct,
        },
        "gainers": [_attach_name_industry(g) for g in gainers],
        "losers": [_attach_name_industry(l) for l in losers],
    }

    # 6. Cache the result (only when dynamic weights succeeded —
    #    fallback results should not be cached so they can be
    #    recomputed once daily_basic data becomes available)
    if use_dynamic_weight:
        dp.cache.upsert_index_contribution_cache(
            index_code, trade_date, top_n, weight_type, result,
        )
    else:
        log.debug("Skipping cache — fallback weights should not be persisted")

    return result


def build_industry_frequency(
    index_code: str,
    trade_dates: list[str],
    dp: DataProvider,
    top_n: int = 10,
    min_days: int = 3,
    min_contrib_pct: float = 0.10,
    min_occurrence: int = 2,
) -> dict | None:
    """
    Count how often each industry appears in top-N gainers/losers
    across multiple trading dates.

    A day counts for an industry if EITHER of these is true:
      a) The sum of contribution points from that industry reaches
         min_contrib_pct of the day's total top-N contribution.
      b) The industry appears at least min_occurrence times among
         the day's top-N (captures breadth / sector-wide resonance).

    Args:
        index_code:     '000001.SH' or '399006.SZ'
        trade_dates:    list of YYYYMMDD strings, sorted most-recent-first
        dp:             DataProvider instance
        top_n:          top-N to consider per day (default 10)
        min_days:       only include industries appearing ≥ min_days (default 3)
        min_contrib_pct: min fraction of total top-N contrib (default 0.10 = 10%)
        min_occurrence:  min number of stocks in top-N to count a day (default 2)

    Returns:
        {
          "gainers": [{industry, code, days}, ...],  # sorted by days DESC
          "losers":  [{industry, code, days}, ...],
        }
        or None if no contribution data is available for any date.
    """
    from collections import Counter

    gainer_counter: Counter[tuple[str, str]] = Counter()
    loser_counter: Counter[tuple[str, str]] = Counter()

    for td in trade_dates:
        contrib = build_index_contribution(index_code, td, dp, top_n=top_n)
        if contrib is None:
            continue
        # Total contribution of all top-N gainers/losers for the day.
        total_gainer_contrib = sum(abs(g["contrib"]) for g in contrib["gainers"])
        total_loser_contrib = sum(abs(l["contrib"]) for l in contrib["losers"])

        # Group by industry per day: sum the contribution AND count occurrences.
        day_gainers: dict[tuple[str, str], dict] = {}
        day_losers: dict[tuple[str, str], dict] = {}
        for g in contrib["gainers"]:
            key = (g["industry"], g.get("industry_code", ""))
            entry = day_gainers.setdefault(key, {"contrib": 0.0, "count": 0})
            entry["contrib"] += abs(g["contrib"])
            entry["count"] += 1
        for l in contrib["losers"]:
            key = (l["industry"], l.get("industry_code", ""))
            entry = day_losers.setdefault(key, {"contrib": 0.0, "count": 0})
            entry["contrib"] += abs(l["contrib"])
            entry["count"] += 1

        # Count day if industry meets EITHER criterion.
        for key, entry in day_gainers.items():
            contrib_ok = (
                total_gainer_contrib > 0
                and entry["contrib"] / total_gainer_contrib >= min_contrib_pct
            )
            occur_ok = entry["count"] >= min_occurrence
            if contrib_ok or occur_ok:
                gainer_counter[key] += 1
        for key, entry in day_losers.items():
            contrib_ok = (
                total_loser_contrib > 0
                and entry["contrib"] / total_loser_contrib >= min_contrib_pct
            )
            occur_ok = entry["count"] >= min_occurrence
            if contrib_ok or occur_ok:
                loser_counter[key] += 1

    def _build_result(counter: Counter) -> list[dict]:
        return [
            {"industry": ind, "code": code, "days": count}
            for (ind, code), count in counter.most_common()
            if count >= min_days
        ]

    gainers = _build_result(gainer_counter)
    losers = _build_result(loser_counter)

    if not gainers and not losers:
        return None

    return {"gainers": gainers, "losers": losers}
