"""
Agent 3 — 个股追踪页面（占位符）
展示关注个股的技术状态、关键点位、持仓管理。
"""
import streamlit as st
import sys
import os
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from rendering.styles import PAGE_CSS

st.markdown(PAGE_CSS, unsafe_allow_html=True)

# ── Date guard ──
_td = st.session_state.get("trade_date")
if not _td:
    st.warning("⚠️ 尚未选择日期，请前往「控制台」设置")
    st.stop()

st.title("📋 个股追踪")
st.caption("Agent 3 — 个股技术分析 & 持仓管理")

st.markdown(f"📅 当前日期：<span style='color:#e53935;font-weight:bold;'>{_td[:4]}-{_td[4:6]}-{_td[6:8]}</span>", unsafe_allow_html=True)

st.divider()

# ── Filters / Summary Bar ──
st.markdown("### 🔍 自选股概览")

# Mock summary metrics
m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    st.metric("自选股数", "12", "3 待评估")
with m2:
    st.metric("已持仓", "5", "仓位 42%")
with m3:
    st.metric("今日上涨", "8", "+2.3% avg")
with m4:
    st.metric("今日下跌", "3", "-1.1% avg")
with m5:
    st.metric("信号待触发", "4", "2 接近买点")

st.divider()

# ── Watchlist Table ──
st.subheader("📊 自选列表")

mock_stocks = [
    {"name": "中际旭创", "code": "300308.SZ", "industry": "通信设备", "state": "🔴 上升中", "state_color": "#c62828",
     "price": "142.50", "chg": "+4.32", "type": "left", "position": "未持仓", "signal": "等待回调至 MA20"},
    {"name": "宁德时代", "code": "300750.SZ", "industry": "电池", "state": "🟢 已回调8天", "state_color": "#2e7d32",
     "price": "218.30", "chg": "+1.25", "type": "left", "position": "已持仓 5%", "signal": "MA20 支撑 212 → 关注加仓"},
    {"name": "北方华创", "code": "002371.SZ", "industry": "半导体设备", "state": "🟡 等待突破", "state_color": "#ef6c00",
     "price": "385.00", "chg": "-0.82", "type": "right", "position": "未持仓", "signal": "回调16天 → 突破 392 可介入"},
    {"name": "贵州茅台", "code": "600519.SH", "industry": "食品饮料", "state": "⚫ 下跌中", "state_color": "#666",
     "price": "1520.00", "chg": "-0.35", "type": "left", "position": "未持仓", "signal": "MA60 向下 → 暂不关注"},
    {"name": "汇川技术", "code": "300124.SZ", "industry": "自动化设备", "state": "🟢 已回调5天", "state_color": "#2e7d32",
     "price": "68.20", "chg": "+2.15", "type": "left", "position": "已持仓 8%", "signal": "MA10 企稳 → 观察量能"},
    {"name": "金山办公", "code": "688111.SH", "industry": "计算机", "state": "🔴 上升中", "state_color": "#c62828",
     "price": "312.80", "chg": "+5.67", "type": "right", "position": "已持仓 12%", "signal": "放量突破 → 持有待涨"},
]

for s in mock_stocks:
    chg_color = "#e53935" if s["chg"].startswith("+") else "#43a047"
    type_badge = {"left": "🔵 左侧", "right": "🔶 右侧", "skip": "⏭ 跳过"}.get(s["type"], "?")

    with st.expander(f"{s['name']} ({s['code']}) — {s['industry']} | {s['state']}", expanded=False):
        c1, c2, c3 = st.columns([2, 1, 1])

        with c1:
            st.markdown(f"""
            **{s['name']}** `{s['code']}`
            行业: {s['industry']} | 基本面: {type_badge}
            技术状态: <span style="color:{s['state_color']};font-weight:bold;">{s['state']}</span>
            """, unsafe_allow_html=True)

        with c2:
            st.markdown(f"""
            **价格** <span style="color:{chg_color};">{s['price']} ({s['chg']}%)</span>
            **持仓**: {s['position']}
            """, unsafe_allow_html=True)

        with c3:
            st.markdown(f"""
            **信号**: {s['signal']}
            """)

        st.info("""
        🚧 **个股详情卡片待实现**

        计划内容：
        - K线图（复用指数同款）
        - 关键技术点位表（支撑/压力/突破位）
        - 持仓管理 tier card（成本分层止损止盈）
        - Agent 3 LLM 分析摘要
        """)

st.divider()

# ── Agent 3 Analysis Report ──
st.subheader("🤖 Agent 3 分析报告")
st.info("""
🚧 **Agent 3 尚未实现**

计划分析内容：
1. **自选股逐个扫描** — 每只股票独立 Agent 分析
2. **技术状态判定** — 🔴上升中 / 🟢回调中 / 🟡等待突破 / ⚫下跌中
3. **关键点位识别** — MA20/MA60/量能节点/缺口/前低支撑/前高压力
4. **持仓管理** — 成本分层止损止盈：
   - 0-10% 盈利：止损成本 -3~5%
   - 10-20% 盈利：移动止盈成本 +3%
   - 20%+ 盈利：MA20 跟踪止盈
5. **操作建议** — 关注/加仓/减仓/持有/观望

此处为占位符，后续 Agent 3 的 LLM 输出将直接渲染于此。
""")
