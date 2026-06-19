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
    _expected_guides = {"guide/sh_index", "guide/cz_index", "summary"}
    # Quick check — if K-line + daily_basic cache covers this date,
    # skip the heavy K-line loading, but still ensure wave33 is computed
    # with detailed progress.
    if _service.check_cache_coverage(_pending):
        with st.status("正在扫描 3浪3...", expanded=True) as status:
            def _w33_progress(phase: str, current: int, total: int | None, extra: str = None):
                if phase == "wave33_init":
                    date_str = extra or "?"
                    status.update(label=f"3浪3 扫描: {date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} | 共 {current} 只（共 {total} 天待扫）")
                elif phase == "wave33_load":
                    status.update(label=f"加载K线: {current}/{total} 只（共 {extra} 天待扫）")
                elif phase == "wave33_scan":
                    status.update(label=f"K线加载完成 ({current}/{total} 只)，开始逐日扫描（共 {extra} 天）...")
                elif phase == "wave33_cumprofit":
                    if current >= total:
                        status.update(label=f"预计算累计盈利完成（{current} 只，共 {extra} 天）")
                    else:
                        status.update(label=f"预计算累计盈利: {current}/{total} 只（共 {extra} 天）")
                elif phase == "wave33_date":
                    date_str = extra or "?"
                    status.update(label=f"3浪3 扫描: {date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} ({current}/{total} 天)")

            w33_result = _service.ensure_wave33_computed(_pending, progress_cb=_w33_progress)
            status.update(
                label=f"✅ 3浪3 扫描完成（扫描 {w33_result['scanned']} 天，"
                      f"已缓存 {w33_result['cached']} 天，{w33_result['elapsed']}秒）",
                state="complete",
            )
        # ── AI summary ──
        with st.status("正在生成 AI 总结...", expanded=True) as _ai_status:
            _cached = _service.get_ai_summary(_pending)
            if not _expected_guides.issubset(_cached.keys()):
                def _ai_progress(phase: str, label: str):
                    _ai_status.update(label=f"🤖 {label}")
                _service.generate_ai_summary(_pending, progress_cb=_ai_progress)
            # Sector AI
            _sector_cached = _service.get_ai_sector_summary(_pending)
            if _sector_cached is None:
                def _ai_sector_progress(phase: str, label: str):
                    _ai_status.update(label=f"🏭 {label}")
                _service.generate_ai_sector_analysis(
                    _pending, progress_cb=_ai_sector_progress,
                )
            _ai_status.update(label="✅ AI 总结已就绪", state="complete")
        st.session_state.trade_date = _pending
        st.cache_data.clear()
        st.rerun()

    with st.status(f"正在加载 {_pending[:4]}-{_pending[4:6]}-{_pending[6:8]} 市场数据...", expanded=True) as status:
        _total_chunks = [None]  # mutable box for closure
        def _progress(phase: str, current: int, total: int | None, extra: str = None):
            if phase == "init":
                _total_chunks[0] = total
                status.update(label=f"准备拉取数据... (共 {total} 个日期段)")
            elif phase == "chunk":
                t = _total_chunks[0] or 1
                date_range = extra or ""
                status.update(label=f"拉取 K线: {date_range} ({current}/{t} 日期段)")
            elif phase == "index":
                status.update(label=f"正在拉取指数数据... ({current}/{total} 个)")
            elif phase == "basic":
                date_range = extra or ""
                status.update(label=f"拉取市值数据: {date_range} ({current}/{total} 段)")
            elif phase == "wave33_init":
                date_str = extra or "?"
                status.update(label=f"3浪3 扫描: {date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} | 共 {current} 只（共 {total} 天待扫）")
            elif phase == "wave33_load":
                status.update(label=f"加载K线: {current}/{total} 只（共 {extra} 天待扫）")
            elif phase == "wave33_scan":
                status.update(label=f"K线加载完成 ({current}/{total} 只)，开始逐日扫描（共 {extra} 天）...")
            elif phase == "wave33_cumprofit":
                if current >= total:
                    status.update(label=f"预计算累计盈利完成（{current} 只，共 {extra} 天）")
                else:
                    status.update(label=f"预计算累计盈利: {current}/{total} 只（共 {extra} 天）")
            elif phase == "wave33_date":
                date_str = extra or "?"
                status.update(label=f"3浪3 扫描: {date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} ({current}/{total} 天)")
            elif phase == "industry_members":
                status.update(label=extra or "正在拉取行业成分股...")
            elif phase == "industry_daily":
                status.update(label=extra or "正在聚合行业日线...")
            elif phase == "validate":
                status.update(label=extra or "正在验证数据覆盖率...")
            elif phase == "done":
                status.update(label="数据加载完成！", state="complete")

        result = _service.ensure_data_loaded(_pending, progress_cb=_progress)

        # ── Wave33 scan (after K-line + market cap are cached) ──
        w33_result = _service.ensure_wave33_computed(_pending, progress_cb=_progress)

        if result["status"] == "ok":
            status.update(label="正在生成 AI 总结...")
            _cached = _service.get_ai_summary(_pending)
            if not _expected_guides.issubset(_cached.keys()):
                def _ai_progress2(phase: str, label: str):
                    status.update(label=f"🤖 {label}")
                _service.generate_ai_summary(_pending, progress_cb=_ai_progress2)
            # Sector AI
            _sector_cached = _service.get_ai_sector_summary(_pending)
            if _sector_cached is None:
                def _ai_sector_progress2(phase: str, label: str):
                    status.update(label=f"🏭 {label}")
                _service.generate_ai_sector_analysis(
                    _pending, progress_cb=_ai_sector_progress2,
                )
            ind_days = result.get("industry_days", 0)
            status.update(
                label=f"✅ 全部就绪！（数据 {result['elapsed']:.0f}秒，"
                      f"K线 {result.get('raw_pages', '?')} 页，"
                      f"因子 {result.get('adj_pages', '?')} 页，"
                      f"指数 {result.get('index_chunks', 0)} 个，"
                      f"市值 {result.get('db_pages', 0)} 页，"
                      f"行业 {ind_days} 天，"
                      f"3浪3 扫描 {w33_result['scanned']} 天（已缓存 {w33_result['cached']} 天，"
                      f"{w33_result['elapsed']:.0f}秒））",
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

# ── AI Summary Card ──
_current_td = st.session_state.get("trade_date")
if _current_td:
    _ai = _service.get_ai_summary(_current_td)
    if _ai and "summary" in _ai:
        st.markdown("---")
        st.markdown("### 🤖 市场全景总览")
        _summary_content = _ai["summary"]["content"]
        st.info(_summary_content)
        # Also show individual guides collapsed
        with st.expander("📋 查看各板块导语"):
            for _gk in ["guide/sh_index", "guide/cz_index"]:
                if _gk in _ai:
                    _label = {
                        "guide/sh_index": "上证指数",
                        "guide/cz_index": "创业板指",
                    }.get(_gk, _gk)
                    st.caption(f"**{_label}**")
                    st.text(_ai[_gk]["content"])
            # Sector guides
            _sector_ai = _service.get_ai_sector_summary(_current_td)
            if _sector_ai:
                st.caption("**🏭 行业总结**")
                st.text(_sector_ai["content"])
    elif _ai and "error" not in _ai:
        st.markdown("---")
        st.caption("🤖 AI 总结尚未生成（切换日期时将自动生成）")

# ── Industry Classification Rules ──
with st.expander("📋 行业分类规则", expanded=False):
    try:
        config = _service.get_industry_split_config()
        split_l1 = config["split_l1"]
        split_l2 = config["split_l2"]
        st.markdown(f"""
        **默认按申万一级行业（31个）展示**

        **拆分 L1 → L2：** {', '.join(split_l1)}

        **拆分 L2 → L3：** {', '.join(split_l2)}

        **最终板块数：** 25 L1 + 24 L2 + 14 L3 = **63**
        """)
    except Exception:
        st.caption("行业分类配置暂不可用")

st.markdown("---")
st.caption("快速跳转：左侧导航 → 市场全景 | 板块分析 | 个股追踪")
