"""
Shared color/style utilities for dashboard rendering.
"""


def vol_color_ramp(pct: float) -> str:
    """Volume comparison color: gray(#999) at 0%, fully saturated red/green at 20%+."""
    abs_pct = abs(pct)
    t = min(abs_pct / 20.0, 1.0)
    if pct > 0:
        r, g, b = 153 + 76 * t, 153 - 96 * t, 153 - 100 * t   # → red(229,57,53)
    else:
        r, g, b = 153 - 86 * t, 153 + 7 * t, 153 - 82 * t     # → green(67,160,71)
    return f"rgb({int(r)},{int(g)},{int(b)})"


def up_down_color(val: float) -> str:
    """Red for positive, green for negative, gray for zero."""
    if val > 0:
        return "#e53935"
    if val < 0:
        return "#43a047"
    return "#999"


PAGE_CSS = """
<style>
.streamlit-expanderHeader {
    font-size: 1.44em !important;
    font-weight: 600;
}
</style>
"""
