"""
Agent 2 — 板块分析页面。
展示行业板块涨跌排名 + 技术分析，使用申万行业指数 sw_daily 数据。
"""
import streamlit as st
import os
import sys
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from services.dashboard_service import DashboardService
from rendering.styles import PAGE_CSS, up_down_color
from rendering.index_section import render_ohlcv_section

st.markdown(PAGE_CSS, unsafe_allow_html=True)

# ── Init ──
_service = DashboardService()

# ── Date guard ──
_trade_date = st.session_state.get("trade_date")
if not _trade_date:
    st.warning("⚠️ 尚未选择日期，请前往「控制台」设置")
    st.stop()

_display_date = f"{_trade_date[:4]}-{_trade_date[4:6]}-{_trade_date[6:8]}"

# ═══════════════════════════════════════════════════════════
#  Page Header
# ═══════════════════════════════════════════════════════════

st.title(f"🏭 板块分析 — {_display_date}")
st.caption("Agent 2 — 行业赚钱效应 & 轮动分析")

# ═══════════════════════════════════════════════════════════
#  1. AI 行业总结导语（Phase 3 接入，当前占位）
# ═══════════════════════════════════════════════════════════

# TODO(Phase 3): 接入 generate_ai_sector_analysis() → sector_summary 缓存
_ai_placeholder = st.empty()
with _ai_placeholder.container():
    st.info("🤖 AI 行业总结导语将在 Phase 3 接入，当前展示数据层面分析结果。")

st.divider()

# ═══════════════════════════════════════════════════════════
#  2. Data loading
# ═══════════════════════════════════════════════════════════

_ranking = _service.get_industry_ranking(_trade_date)
_analysis_set = _service.get_industry_analysis_set(_trade_date)

if not _ranking:
    st.warning("⚠️ 暂无行业数据，请先在「控制台」加载今日数据")
    st.stop()

# ═══════════════════════════════════════════════════════════
#  2. TOP 5 / BOTTOM 5 双列卡片
# ═══════════════════════════════════════════════════════════

st.subheader("📊 今日行业涨跌排名")

_top5 = _ranking[:5]
_bottom5 = _ranking[-5:][::-1] if len(_ranking) >= 5 else []

_col_left, _col_right = st.columns(2)


def _render_rank_card(col, items: list[dict], title: str, is_gainer: bool):
    """Render a ranked list of industry cards."""
    col.markdown(f"**{title}**")
    if not items:
        col.caption("暂无数据")
        return

    _rows = ""
    for i, r in enumerate(items):
        _pct = r["pct_change"]
        _pct_str = f"{_pct:+.2f}%"
        _pct_color = up_down_color(_pct)
        _amount_yi = r["amount"] / 1e5  # 千元 → 亿
        _medal = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i]
        _level_badge = {
            "L1": "[一级]", "L2": "[二级]", "L3": "[三级]",
        }.get(r["level"], "")

        _rows += f"""
        <tr>
            <td style="text-align:center;font-size:20px;">{_medal}</td>
            <td style="font-weight:600;">{_level_badge} {r['name']}</td>
            <td style="text-align:right;font-weight:bold;color:{_pct_color};">
                {_pct_str}</td>
            <td style="text-align:right;color:#888;font-size:14px;">
                {_amount_yi:,.0f}亿</td>
        </tr>"""

    col.html(f"""
    <table style="width:100%;font-size:16px;border-collapse:collapse;">
        <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;">
            <th style="text-align:center;width:40px;">#</th>
            <th style="text-align:left;">行业</th>
            <th style="text-align:right;">涨跌幅</th>
            <th style="text-align:right;">成交额</th>
        </tr></thead>
        <tbody>{_rows}</tbody>
    </table>
    """)


with _col_left:
    _render_rank_card(_col_left, _top5, "🔥 今日领涨 TOP 5", is_gainer=True)

with _col_right:
    _render_rank_card(_col_right, _bottom5, "❄️ 今日领跌 TOP 5", is_gainer=False)

st.divider()

# ═══════════════════════════════════════════════════════════
#  3. 行业详细分析 Expander 列表
# ═══════════════════════════════════════════════════════════

st.subheader(f"🔍 行业详细分析（共 {len(_analysis_set)} 个）")
st.caption("候选来源：涨幅 TOP 5 · 跌幅 TOP 5 · 权重贡献上榜 · 近5日频繁领涨/领跌（去重后）")

if not _analysis_set:
    st.info("暂无需要分析的行业")
else:
    for _entry in _analysis_set:
        _code = _entry["code"]
        _name = _entry["name"]
        _level = _entry["level"]
        _pct = _entry["pct_change"]
        _reasons = "  ".join(_entry.get("reasons", []))

        _pct_color = up_down_color(_pct)
        _level_tag = {"L1": "一级", "L2": "二级", "L3": "三级"}.get(_level, _level)

        # Info line above expander
        _info_line = (
            f"{_name}  ·  "
            f"<span style='color:{_pct_color};font-weight:bold;'>{_pct:+.2f}%</span>"
            f"  <span style='font-size:13px;color:#888;'>[{_level_tag}] {_reasons}</span>"
        )
        st.html(f"<div style='margin-bottom:2px;font-size:15px;'>{_info_line}</div>")

        with st.expander(f"{_name} ({_code})", expanded=False):
            # Load full K-line data for this industry
            _df = _service.get_industry_daily(_code, end_date=_trade_date, lookback=360)

            if _df.empty:
                st.warning(f"暂无 {_name}（{_code}）的日线数据")
                continue

            render_ohlcv_section(_df, _code, _name, _service, "industry",
                                 industry_level=_level)
