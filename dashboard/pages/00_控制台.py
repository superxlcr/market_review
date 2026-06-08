"""
控制台 — 统一入口
选择分析日期，应用到所有页面。
"""
import streamlit as st
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from rendering.styles import PAGE_CSS
from services.dashboard_service import DashboardService

st.markdown(PAGE_CSS, unsafe_allow_html=True)

# ── Date input styling ──
st.markdown("""
<style>
div[data-testid="stDateInput"] {
    max-width: 240px;
}
div[data-testid="stDateInput"] input {
    border: 2px solid #1976d2 !important;
    border-radius: 8px !important;
    padding: 10px 14px !important;
    font-size: 17px !important;
    font-weight: 600 !important;
    cursor: pointer !important;
}
div[data-testid="stDateInput"] input:hover {
    border-color: #1565c0 !important;
}
/* Hide form border */
div[data-testid="stForm"] {
    border: none !important;
    padding: 0 !important;
}
</style>
""", unsafe_allow_html=True)

st.title("🎛️ 控制台")
st.caption("选择交易日，应用到全部页面")

_service = DashboardService()

# ── Default date: session_state > latest trading day ──
_default_str = st.session_state.get("trade_date")
if _default_str:
    _default_date = datetime.strptime(_default_str, "%Y%m%d")
else:
    latest = _service.get_latest_trade_date()
    if latest:
        _default_date = datetime.strptime(latest.replace("-", ""), "%Y%m%d")
    else:
        _default_date = datetime.now()

# ── Current applied ──
_current = st.session_state.get("trade_date")
if _current:
    _cd = f"{_current[:4]}-{_current[4:6]}-{_current[6:8]}"
    st.markdown(
        f"**当前生效：** <span style='color:#e53935;font-size:22px;font-weight:bold;'>{_cd}</span>"
        f" &nbsp;<span style='color:#888;font-size:14px;'>← 全部页面统一使用此日期</span>",
        unsafe_allow_html=True,
    )

st.markdown("---")

# ── Form: date picker + apply button (batched, no auto-rerun on pick) ──
with st.form("ctrl_form", clear_on_submit=False):
    c1, c2 = st.columns([3, 1])

    with c1:
        selected_date = st.date_input(
            "📅 选择交易日",
            value=_default_date,
            max_value=datetime.now(),
            format="YYYY-MM-DD",
            key="ctrl_date_picker",
        )

    with c2:
        st.markdown("")  # small spacer
        apply_btn = st.form_submit_button(
            "▶ 应用",
            type="primary",
            use_container_width=True,
        )

# ── Handle form submit ──
if apply_btn:
    _trade_date_str = selected_date.strftime("%Y%m%d")
    if _service.is_trading_day(_trade_date_str):
        st.session_state.trade_date = _trade_date_str
        st.rerun()
    else:
        st.error(f"**{selected_date.strftime('%Y-%m-%d')} 不是交易日**")

st.markdown("---")
st.caption("快速跳转：左侧导航 → 市场全景 | 板块分析 | 个股追踪")
