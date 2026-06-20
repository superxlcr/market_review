"""
Industry classification and split configuration.

The split logic follows a recursive replacement rule:
  - Default: show at L1 level (31 industries)
  - SPLIT_L1: these L1 are replaced by their L2 children
  - SPLIT_L2: these L2 are further replaced by their L3 children

This replaces the old hard-coded L1_OVERRIDE_L1 / L3_OVERRIDE_L3 lists.
"""

# ── Configuration (edit these sets to change split behaviour) ──

# L1 industries that should be split into their L2 children
SPLIT_L1 = {'建筑材料', '有色金属', '汽车', '电力设备', '电子', '通信'}

# L2 industries that should be further split into their L3 children
SPLIT_L2 = {'半导体', '元件', '光伏设备'}


# ── Resolution helpers ──

def resolve_industry_label(
    _l1_code: str = "",   # unused — kept for backward compatibility
    l1_name: str = "",
    _l2_code: str = "",
    l2_name: str = "",
    _l3_code: str = "",
    l3_name: str = "",
) -> str:
    """Apply recursive split logic to determine the display label.

    Args:
        l1_name: L1 industry name (e.g. '电子')
        l2_name: L2 industry name (e.g. '半导体')
        l3_name: L3 industry name (e.g. '数字芯片设计')

    Returns:
        The resolved display name at the appropriate level.
    """
    if l1_name in SPLIT_L1 and l2_name:
        if l2_name in SPLIT_L2 and l3_name:
            return l3_name
        return l2_name
    return l1_name


def resolve_industry_code(
    l1_code: str = "",
    l1_name: str = "",
    l2_code: str = "",
    l2_name: str = "",
    l3_code: str = "",
    l3_name: str = "",
) -> str:
    """Return the industry code that matches resolve_industry_label's choice.

    This is the code corresponding to whichever level was selected — used
    when aggregating by industry for drill-down purposes.
    """
    if l1_name in SPLIT_L1 and l2_code:
        if l2_name in SPLIT_L2 and l3_code:
            return l3_code
        return l2_code
    return l1_code


def get_split_summary() -> dict:
    """Return a summary of the split config for display in the console."""
    from marketreview.data.data_provider import DataProvider
    return {
        "split_l1": sorted(SPLIT_L1),
        "split_l2": sorted(SPLIT_L2),
        "kept_l1": 25,  # 31 - 6
        "l2_from_split": 24,
        "l3_from_split": 14,
        "total": 63,
    }
