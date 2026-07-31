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
/* Strategy selectbox — inline with form, purple border */
div[data-testid="stSelectbox"] {
    display: inline-block !important;
    vertical-align: bottom !important;
    border: 2px solid #7b1fa2 !important;
    border-radius: 8px !important;
    padding: 6px 10px !important;
}
div[data-testid="stSelectbox"]:hover {
    border-color: #6a1b9a !important;
}
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
st.caption(f"选择交易日，应用到全部页面 ｜ AI v{DashboardService._AI_VERSION}")

# ── 行业分类规则 ──
with st.expander("🏭 行业分类规则", expanded=False):
    from marketreview.tools.industry import SPLIT_L1, SPLIT_L2
    st.markdown(f"""
    **默认**按申万一级行业（31个）展示

    **拆分 L1→L2**：{"、".join(sorted(SPLIT_L1))}（共 {len(SPLIT_L1)} 个）

    **拆分 L2→L3**：{"、".join(sorted(SPLIT_L2))}（共 {len(SPLIT_L2)} 个）

    **最终板块数**：25 L1 + 24 L2 + 14 L3 = **63**
    """)

_service = DashboardService()

# ── 自选行业 ──
with st.expander("⭐ 自选行业", expanded=False):
    st.markdown("**配置文件：** `config/watchlist_industries.txt`")

    _wl_data = _service.get_watchlist_industries()
    _watchlist = _wl_data["matched"]
    _unmatched = _wl_data["unmatched"]

    if not _watchlist and not _unmatched:
        st.caption("暂无自选行业，请在 `config/watchlist_industries.txt` 中配置")
        st.caption("（参考 `config/watchlist_industries.example.txt`）")
    else:
        if _watchlist:
            _wl_rows = ""
            for _i, _w in enumerate(_watchlist):
                _wl_rows += (
                    f"<tr>"
                    f"<td style='text-align:center;'>{_i + 1}</td>"
                    f"<td>{_w['name']}</td>"
                    f"<td style='text-align:center;'>{_w['level']}</td>"
                    f"<td style='text-align:center;color:#888;font-size:13px;'>{_w['code']}</td>"
                    f"<td style='text-align:center;'>✅</td>"
                    f"</tr>"
                )
            st.html(f"""
            <table style="width:100%;font-size:15px;border-collapse:collapse;">
                <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;">
                    <th style="text-align:center;width:30px;">#</th>
                    <th style="text-align:left;">行业名称</th>
                    <th style="text-align:center;">Level</th>
                    <th style="text-align:center;">Code</th>
                    <th style="text-align:center;">状态</th>
                </tr></thead>
                <tbody>{_wl_rows}</tbody>
            </table>
            """)
        if _unmatched:
            _names = "、".join(_unmatched)
            st.warning(f"⚠️ 以下 {len(_unmatched)} 个名称未匹配到 SW2021 行业：**{_names}**，请检查拼写")

# ── 自选个股 ──
with st.expander("📋 自选个股", expanded=False):
    st.markdown("**配置文件：** `config/watchlist_stocks.txt`")

    _stocks_data = _service.get_watchlist_stocks()
    _stocks = _stocks_data["matched"]
    _stocks_unmatched = _stocks_data["unmatched"]

    if not _stocks and not _stocks_unmatched:
        st.caption("暂无自选个股，请在 `config/watchlist_stocks.txt` 中配置")
    else:
        if _stocks:
            _rows = ""
            for _i, _s in enumerate(_stocks):
                _rows += (
                    f"<tr>"
                    f"<td style='text-align:center;'>{_i + 1}</td>"
                    f"<td style='color:#888;font-size:14px;'>{_s['ts_code']}</td>"
                    f"<td style='font-weight:600;'>{_s['name']}</td>"
                    f"<td style='color:#888;'>{_s['industry']}</td>"
                    f"<td style='text-align:center;'>✅</td>"
                    f"</tr>"
                )
            st.html(f"""
            <table style="width:100%;font-size:15px;border-collapse:collapse;">
                <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;">
                    <th style="text-align:center;width:30px;">#</th>
                    <th style="text-align:left;">代码</th>
                    <th style="text-align:left;">名称</th>
                    <th style="text-align:left;">行业</th>
                    <th style="text-align:center;">状态</th>
                </tr></thead>
                <tbody>{_rows}</tbody>
            </table>
            """)
        if _stocks_unmatched:
            _names = "、".join(_stocks_unmatched)
            st.warning(f"⚠️ 以下 {len(_stocks_unmatched)} 个名称未匹配到数据库：**{_names}**，请检查拼写")

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

# ── 日期 ──
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
    _expected_sector = {"sector_summary"}
    # Also require watchlist industry guides (否则旧缓存的 sector_summary
    # 会阻止重新生成，导致新增的自选行业没有 AI 导语)
    _wl = _service.get_watchlist_industries()["matched"]
    for _w in _wl:
        _expected_sector.add(f"sector/{_w['code']}")

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
            elif phase == "ind_classify":
                status.update(label=f"加载行业分类层级... ({current} 条)")
            elif phase == "ind_daily":
                note = extra or ""
                status.update(label=f"补齐行业日线数据: {note} ({current}/{total})")
            elif phase == "stock_industry":
                status.update(label=f"补齐个股行业分类: {current}/{total} 只")
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

            # ── Sector AI guides ──
            _sector_cached = _service.get_ai_summary(
                _pending, summary_type="sector_analysis")
            if not _expected_sector.issubset(_sector_cached.keys()):
                def _ai_sector_progress(phase: str, label: str):
                    status.update(label=f"🤖 [行业] {label}")
                _service.generate_ai_sector_analysis(
                    _pending, progress_cb=_ai_sector_progress)

            # ── 生成数据 MD 供 Claude Code 复盘读取 ──
            _journal_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "journal")
            try:
                _service.generate_data_md(_pending, _journal_dir)
            except Exception as _md_err:
                # Don't block dashboard for MD generation failure
                pass

            status.update(
                label=f"✅ 全部就绪！（数据 {result['elapsed']:.0f}秒，"
                      f"K线 {result.get('raw_pages', '?')} 页，"
                      f"因子 {result.get('adj_pages', '?')} 页，"
                      f"指数 {result.get('index_chunks', 0)} 个，"
                      f"市值 {result.get('db_pages', 0)} 页，"
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

        # Sector guides expander
        _sector_ai = _service.get_ai_summary(_current_td,
                                              summary_type="sector_analysis")
        if _sector_ai:
            with st.expander("📋 查看各行业导语"):
                if "sector_summary" in _sector_ai:
                    st.caption("**行业总览**")
                    st.text(_sector_ai["sector_summary"]["content"])
                # Build watchlist lookup (for ⭐ marker + name resolution)
                _wl_data = _service.get_watchlist_industries()
                _wl_codes = {w["code"] for w in _wl_data.get("matched", [])}
                _industry_names = {
                    r["code"]: r["name"] for r in _service.get_industry_list()
                }
                # 补上自选行业名称（展示行业列表不一定包含所有自选行业）
                for _w in _wl_data.get("matched", []):
                    if _w["code"] not in _industry_names:
                        _industry_names[_w["code"]] = _w["name"]
                for _gk in sorted(_sector_ai.keys()):
                    if _gk == "sector_summary":
                        continue
                    _sc = _sector_ai[_gk].get("content", "")
                    if _sc and _sc != "AI 摘要暂时不可用":
                        _ind_code = _gk.replace("sector/", "")
                        _ind_name = _industry_names.get(_ind_code, _ind_code)
                        _star = " ⭐" if _ind_code in _wl_codes else ""
                        st.caption(f"**{_ind_name}（{_ind_code}）{_star}**")
                        st.text(_sc)
    elif _ai and "error" not in _ai:
        st.markdown("---")
        st.caption("🤖 AI 总结尚未生成（切换日期时将自动生成）")

st.markdown("---")
st.caption("快速跳转：左侧导航 → 市场全景 | 板块分析 | 个股追踪")
