"""
控制台 — 统一入口
选择分析日期，应用到所有页面。
"""
import streamlit as st
import sys
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from rendering.styles import PAGE_CSS
from services.dashboard_service import DashboardService

st.markdown(PAGE_CSS, unsafe_allow_html=True)

# ── Layout & styling ──
st.markdown("""
<style>
/* Date input */
div[data-testid="stDateInput"] {
    max-width: 230px;
    display: inline-block !important;
    vertical-align: bottom !important;
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
/* Button: inline with date input */
div[data-testid="stFormSubmitButton"] {
    display: inline-block !important;
    vertical-align: bottom !important;
    margin-left: 6px !important;
}
/* Hide form border */
div[data-testid="stForm"] {
    border: none !important;
    padding: 0 !important;
}
/* Collapse the wrapper blocks so inline works */
div[data-testid="stForm"] div[data-testid="stElementContainer"]:has(div[data-testid="stDateInput"]),
div[data-testid="stForm"] div[data-testid="stElementContainer"]:has(div[data-testid="stFormSubmitButton"]) {
    display: inline-block !important;
    vertical-align: bottom !important;
}
</style>
""", unsafe_allow_html=True)

st.title("🎛️ 控制台")
st.caption("选择交易日，应用到全部页面")

_service = DashboardService()

# ── Default date ──
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

# ── Form: no columns, CSS inline layout ──
with st.form("ctrl_form", clear_on_submit=False):
    selected_date = st.date_input(
        "📅 选择交易日",
        value=_default_date,
        max_value=datetime.now(),
        format="YYYY-MM-DD",
        key="ctrl_date_picker",
    )
    apply_btn = st.form_submit_button("✅ 应用", type="primary")

# ── Handle form submit ──
if apply_btn:
    _trade_date_str = selected_date.strftime("%Y%m%d")
    if _service.is_trading_day(_trade_date_str):
        # Two-phase: first set pending, rerun → load with spinner → set applied
        st.session_state.pending_load_date = _trade_date_str
        st.rerun()
    else:
        st.error(f"**{selected_date.strftime('%Y-%m-%d')} 不是交易日**")

# ── Phase 2: execute data loading (when pending_load_date is set) ──
_pending = st.session_state.pop("pending_load_date", None)
if _pending:
    with st.status(f"正在加载 {_pending[:4]}-{_pending[4:6]}-{_pending[6:8]} 市场数据...", expanded=True) as status:
        _total_chunks = [None]  # mutable box for closure
        def _progress(phase: str, current: int, total: int | None):
            if phase == "init":
                _total_chunks[0] = total
                status.update(label=f"准备拉取数据... (共 {total} 个日期段)")
            elif phase == "chunk":
                t = _total_chunks[0] or 1
                status.update(label=f"正在拉取股票数据... ({current}/{t} 日期段)")
            elif phase == "index":
                status.update(label=f"正在拉取指数数据... ({current}/{total} 个)")
            elif phase == "done":
                status.update(label="数据加载完成！", state="complete")

        result = _service.ensure_data_loaded(_pending, progress_cb=_progress)
        if result["status"] == "ok":
            status.update(
                label=f"✅ 数据加载完成！（{result['elapsed']:.0f}秒，"
                      f"K线 {result.get('raw_pages', '?')} 页，"
                      f"因子 {result.get('adj_pages', '?')} 页，"
                      f"指数 {result.get('index_chunks', 0)} 个）",
                state="complete",
            )
            st.session_state.trade_date = _pending
            # Clear stale caches so other pages pick up fresh data
            st.cache_data.clear()
            st.rerun()
        else:
            status.update(
                label=f"❌ 数据加载失败: {result.get('msg', '未知错误')}",
                state="error",
            )

st.markdown("---")
st.caption("快速跳转：左侧导航 → 市场全景 | 板块分析 | 个股追踪")
