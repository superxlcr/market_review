"""
Agent 2 — 板块分析页面（占位符）
分析行业板块的赚钱效应，给出仓位策略建议。
"""
import streamlit as st
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from rendering.styles import PAGE_CSS

st.markdown(PAGE_CSS, unsafe_allow_html=True)

st.title("🏭 板块分析")
st.caption("Agent 2 — 行业赚钱效应 & 仓位策略")

# ── Date indicator ──
_td = st.session_state.get("trade_date")
if _td:
    st.markdown(f"📅 当前日期：<span style='color:#e53935;font-weight:bold;'>{_td[:4]}-{_td[4:6]}-{_td[6:8]}</span>", unsafe_allow_html=True)
else:
    st.warning("⚠️ 尚未选择日期，请前往「控制台」设置")

st.divider()

# ── Row 1: 板块涨跌排名 ──
st.subheader("📊 行业板块涨跌排名")

rank_col, heat_col = st.columns([3, 2])

with rank_col:
    # Mock sector performance table
    st.markdown("**今日领涨板块**")
    mock_gainers = [
        ("半导体", "+4.32%", "🔥🔥🔥", "国产替代+AI芯片需求"),
        ("计算机", "+3.87%", "🔥🔥🔥", "信创+数据要素"),
        ("通信设备", "+3.15%", "🔥🔥", "5G-A商用推进"),
        ("自动化设备", "+2.93%", "🔥🔥", "机器人概念持续"),
        ("医药生物", "+2.51%", "🔥🔥", "创新药出海"),
    ]
    gain_html = ""
    for name, chg, heat, reason in mock_gainers:
        gain_html += f"""<tr>
            <td style="font-weight:600;">{name}</td>
            <td style="color:#e53935;font-weight:bold;text-align:right;">{chg}</td>
            <td style="text-align:center;">{heat}</td>
            <td style="color:#888;font-size:14px;">{reason}</td>
        </tr>"""
    st.html(f"""
    <table style="width:100%;font-size:16px;border-collapse:collapse;">
        <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;">
            <th style="text-align:left;">板块</th>
            <th style="text-align:right;">涨幅</th>
            <th style="text-align:center;">热度</th>
            <th style="text-align:left;">驱动逻辑</th>
        </tr></thead>
        <tbody>{gain_html}</tbody>
    </table>
    """)

    st.markdown("")
    st.markdown("**今日领跌板块**")
    mock_losers = [
        ("石油石化", "-1.23%", "国际油价回落"),
        ("煤炭", "-0.98%", "煤价弱势震荡"),
        ("银行", "-0.76%", "净息差压力"),
        ("食品饮料", "-0.54%", "消费复苏不及预期"),
        ("非银金融", "-0.42%", "市场情绪偏谨慎"),
    ]
    lose_html = ""
    for name, chg, reason in mock_losers:
        lose_html += f"""<tr>
            <td style="font-weight:600;">{name}</td>
            <td style="color:#43a047;font-weight:bold;text-align:right;">{chg}</td>
            <td style="color:#888;font-size:14px;">{reason}</td>
        </tr>"""
    st.html(f"""
    <table style="width:100%;font-size:16px;border-collapse:collapse;">
        <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;">
            <th style="text-align:left;">板块</th>
            <th style="text-align:right;">跌幅</th>
            <th style="text-align:left;">原因</th>
        </tr></thead>
        <tbody>{lose_html}</tbody>
    </table>
    """)

with heat_col:
    st.info("""
    🚧 **行业热力图**

    计划用 Plotly heatmap 或 treemap 展示：
    - 申万一级行业 × 涨跌幅
    - 颜色深浅 = 涨跌幅度
    - 大小 = 成交额占比

    此处为占位符，待 Agent 2 实现后接入真实数据。
    """)

st.divider()

# ── Row 2: 赚钱效应 + 仓位 ──
st.subheader("💰 赚钱效应 & 仓位策略")

eff_col, pos_col = st.columns(2)

with eff_col:
    st.markdown("**市场赚钱效应**")
    st.html("""
    <div style="background:#fafafa;border:1px solid #e0e0e0;border-radius:10px;padding:20px;">
        <div style="font-size:15px;color:#888;margin-bottom:10px;">赚钱效应指标</div>
        <table style="width:100%;font-size:16px;border-collapse:collapse;">
            <tr><td style="color:#888;">板块上涨比例</td>
                <td style="font-weight:bold;text-align:right;color:#e53935;">72% (23/32)</td></tr>
            <tr><td style="color:#888;">涨停家数占比</td>
                <td style="font-weight:bold;text-align:right;color:#e53935;">3.2% (168/5200)</td></tr>
            <tr><td style="color:#888;">连板高度</td>
                <td style="font-weight:bold;text-align:right;">6板 (XX股份)</td></tr>
            <tr><td style="color:#888;">炸板率</td>
                <td style="font-weight:bold;text-align:right;color:#e53935;">18% (较低)</td></tr>
            <tr><td style="color:#888;">北向资金</td>
                <td style="font-weight:bold;text-align:right;color:#e53935;">净流入 +42.5亿</td></tr>
        </table>
    </div>
    """)

with pos_col:
    st.markdown("**建议仓位**")
    st.html("""
    <div style="background:#fafafa;border:1px solid #e0e0e0;border-radius:10px;padding:20px;">
        <div style="font-size:40px;font-weight:bold;color:#e53935;text-align:center;">65<span style="font-size:16px;color:#888;">%</span></div>
        <div style="text-align:center;color:#888;font-size:15px;margin-bottom:12px;">建议仓位（偏积极）</div>
        <table style="width:100%;font-size:15px;border-collapse:collapse;">
            <tr><td style="color:#888;">进攻仓位</td>
                <td style="text-align:right;font-weight:bold;color:#e53935;">40%</td>
                <td style="color:#888;font-size:13px;">半导体 / 计算机 / 通信</td></tr>
            <tr><td style="color:#888;">防守仓位</td>
                <td style="text-align:right;font-weight:bold;">25%</td>
                <td style="color:#888;font-size:13px;">医药生物 / 银行</td></tr>
            <tr><td style="color:#888;">现金保留</td>
                <td style="text-align:right;font-weight:bold;color:#888;">35%</td>
                <td style="color:#888;font-size:13px;">等待回调机会</td></tr>
        </table>
    </div>
    """)

st.divider()

# ── Row 3: Agent 2 Analysis Report ──
st.subheader("🤖 Agent 2 分析报告")
st.info("""
🚧 **Agent 2 尚未实现**

计划分析内容：
1. **板块轮动识别** — 哪些板块启动、哪些见顶、哪些在蓄力
2. **赚钱效应评估** — 涨停家数、连板高度、炸板率、北向资金流向
3. **主线 vs 支线判断** — 当前市场主线板块是否有持续性
4. **仓位策略** — 根据赚钱效应给出进攻/防守/现金比例
5. **风险提示** — 需要警惕的板块和事件

此处为占位符，后续 Agent 2 的 LLM 输出将直接渲染于此。
""")
