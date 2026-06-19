"""
Industry classification tools: split configuration, list builder, and
bottom-up market-cap-weighted index aggregation.

Uses Shenwan 2021 classification (申万 SW2021) queried via tushare
index_classify API.  The recursive split rule replaces certain L1
industries with their L2 children, and certain L2 with their L3 children.
"""

from marketreview.log_util import get_logger

log = get_logger(__name__)

# ── Split configuration ──
# L1 industries that are replaced by their L2 children
SPLIT_L1 = {'建筑材料', '有色金属', '汽车', '电力设备', '电子', '通信'}

# L2 industries that are further replaced by their L3 children
SPLIT_L2 = {'半导体', '元件', '光伏设备'}


def _fetch_sw_classification(level: str, api) -> list[dict]:
    """Fetch one level of Shenwan 2021 classification from tushare.

    Returns list of {index_code, industry_code, industry_name, parent_code}.
    """
    try:
        df = api.index_classify(level=level, src='SW2021')
        if df is None or df.empty:
            log.warning("index_classify(level=%s) returned empty", level)
            return []
        result = []
        for _, r in df.iterrows():
            result.append({
                "index_code": str(r.get("index_code", "")),
                "industry_code": str(r.get("industry_code", "")),
                "industry_name": str(r.get("industry_name", "")),
                "parent_code": str(r.get("parent_code", "")),
            })
        return result
    except Exception as e:
        log.warning("index_classify(level=%s) failed: %s", level, e)
        return []


def build_industry_list(api) -> list[dict]:
    """
    Build the final 63-industry list using recursive split rules.

    Returns list of dicts: [{code, name, level, parent_code}, ...]
      code = index_code from tushare (e.g. '801081.SI', '850814.SI')
        This is the code used with index_member API to get constituents.
      level = 'L1' | 'L2' | 'L3'
    """
    l1_all = _fetch_sw_classification("L1", api)
    l2_all = _fetch_sw_classification("L2", api)
    l3_all = _fetch_sw_classification("L3", api)

    # Build lookup: parent_code -> list of children
    l2_by_parent: dict[str, list[dict]] = {}
    for item in l2_all:
        pc = item["parent_code"]
        l2_by_parent.setdefault(pc, []).append(item)

    l3_by_parent: dict[str, list[dict]] = {}
    for item in l3_all:
        pc = item["parent_code"]
        l3_by_parent.setdefault(pc, []).append(item)

    result: list[dict] = []

    for l1 in l1_all:
        if l1["industry_name"] in SPLIT_L1:
            # Replace L1 with its L2 children
            l1_code = l1["industry_code"]
            children = l2_by_parent.get(l1_code, [])
            for l2 in children:
                if l2["industry_name"] in SPLIT_L2:
                    # Replace L2 with its L3 children
                    l2_code = l2["industry_code"]
                    grandchildren = l3_by_parent.get(l2_code, [])
                    for l3 in grandchildren:
                        result.append({
                            "code": l3["index_code"],
                            "name": l3["industry_name"],
                            "level": "L3",
                            "parent_code": l2_code,
                        })
                else:
                    result.append({
                        "code": l2["index_code"],
                        "name": l2["industry_name"],
                        "level": "L2",
                        "parent_code": l1_code,
                    })
        else:
            result.append({
                "code": l1["index_code"],
                "name": l1["industry_name"],
                "level": "L1",
                "parent_code": "",
            })

    l1_count = sum(1 for r in result if r["level"] == "L1")
    l2_count = sum(1 for r in result if r["level"] == "L2")
    l3_count = sum(1 for r in result if r["level"] == "L3")
    log.info("build_industry_list: %d L1 + %d L2 + %d L3 = %d total",
             l1_count, l2_count, l3_count, len(result))
    return result


def resolve_industry_label(
    l1_name: str,
    l2_name: str = "",
    l3_name: str = "",
) -> str:
    """
    Resolve the display label for a stock's industry classification
    using the recursive split rules.

    Priority: L3 (if L2 in SPLIT_L2) > L2 (if L1 in SPLIT_L1) > L1
    """
    if l1_name in SPLIT_L1 and l2_name:
        if l2_name in SPLIT_L2 and l3_name:
            return l3_name
        return l2_name
    return l1_name
