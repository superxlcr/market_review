"""
板块资金 — 东方财富主力资金流向（DB 回放）。
数据在控制台「应用」时拉取入库，此处从 SQLite 读取回放。
"""
import streamlit as st
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from services.dashboard_service import DashboardService
from rendering.styles import PAGE_CSS

st.markdown(PAGE_CSS, unsafe_allow_html=True)

_service = DashboardService()

# ── Page title ──
st.title("💰 板块资金")
st.caption("东方财富主力资金流向 ｜ 主力 = 超大单 + 大单 ｜ 控制台「应用」时入库")

# ══════════════════════════════════════════════
#  Guard: session trade_date
# ══════════════════════════════════════════════

_session_date = st.session_state.get("trade_date")
if not _session_date:
    st.warning("⚠️ 尚未选择日期，请前往「控制台」设置")
    st.stop()

trade_date = _session_date
try:
    _display_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
except (IndexError, TypeError):
    st.error("日期格式异常，请重新在控制台设置")
    st.stop()

# ── Trading day validation ──
if not _service.is_trading_day(trade_date):
    st.error(f"**{_display_date} 不是交易日**，请在控制台重新选择")
    st.stop()

# ══════════════════════════════════════════════
#  Mode + Refresh
# ══════════════════════════════════════════════

col_mode, col_refresh = st.columns([3, 1])
with col_mode:
    mode = st.radio(
        "板块类型", options=["概念板块", "行业板块"],
        horizontal=True, index=0, key="sf_mode",
    )
is_industry = (mode == "行业板块")

with col_refresh:
    if st.button("🔄 刷新", use_container_width=True, key="sf_refresh"):
        st.cache_data.clear()
        st.rerun()

# ── Status bar ──
today_str = datetime.now().strftime("%Y%m%d")
is_today = (trade_date == today_str)
has_db = _service.has_sector_flow(trade_date)

if has_db:
    status_text = "💾 已入库"
elif is_today:
    status_text = "🌐 实时拉取"
else:
    status_text = "⚠️ 无数据"

st.caption(f"交易日：{_display_date} ｜ 状态：{status_text}")

# ══════════════════════════════════════════════
#  Data Loading
# ══════════════════════════════════════════════

blocked = st.session_state.get("sf_blocked", set())

@st.cache_data(show_spinner=False)
def load_sector_flow(_trade_date: str, _industry: bool, _blocked_frozenset: frozenset) -> dict:
    svc = DashboardService()
    return svc.get_sector_flow_data(
        trade_date=_trade_date, industry=_industry,
        blocked_names=set(_blocked_frozenset) if _blocked_frozenset else None,
    )

with st.spinner("正在读取板块资金数据..."):
    data = load_sector_flow(trade_date, is_industry, frozenset(blocked))

series = data.get("series", [])
sectors = data.get("sectors", [])
last_time = data.get("last_time", "")

# ══════════════════════════════════════════════
#  No-data warning
# ══════════════════════════════════════════════

if not series and not is_today:
    st.warning(f"⚠️ **{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]} 无板块资金流数据。**\n\n"
               f"东方财富 API 只提供当天分时数据。要查看某天的板块资金流，需在当天收盘后在**控制台**点「应用」入库。\n\n"
               f"今天是 {today_str[:4]}-{today_str[4:6]}-{today_str[6:8]}，如需查看今日数据请将日期切换为今天。",
               icon="⚠️")
    st.stop()

# ══════════════════════════════════════════════
#  Summary Cards (4-up)
# ══════════════════════════════════════════════

top_in = next((s for s in series if s[2] >= 0), None)
top_out = next((s for s in reversed(series) if s[2] < 0), None)
nin = sum(1 for s in sectors if s.get("flow_yi", 0) >= 0)
nout = sum(1 for s in sectors if s.get("flow_yi", 0) < 0)

def _fmt(v: float) -> str:
    return f"{v:+.1f}亿"

cards_data = [
    ("最强流入", top_in[0] if top_in else "—", _fmt(top_in[2]) if top_in else "—", "#e53935"),
    ("最强流出", top_out[0] if top_out else "—", _fmt(top_out[2]) if top_out else "—", "#43a047"),
    ("数据时间", last_time or "—", data.get("kind", ""), "#888"),
    ("资金广度", f"{nin} / {nout}", f"净流入 {nin} · 净流出 {nout}", "#888"),
]

cols = st.columns(4)
for col, (label, value, meta, color) in zip(cols, cards_data):
    with col:
        st.html(f"""
        <div style="background:#fafafa;border:1px solid #e0e0e0;border-radius:10px;
                    padding:14px;text-align:center;">
            <div style="font-size:13px;color:#888;margin-bottom:4px;">{label}</div>
            <div style="font-size:22px;font-weight:800;color:{color};">{value}</div>
            <div style="font-size:12px;color:#999;margin-top:4px;">{meta}</div>
        </div>""")

st.divider()

# ══════════════════════════════════════════════
#  Playback + Chart
# ══════════════════════════════════════════════

if not series:
    st.info("暂无分时数据（非交易时段或数据未就绪）")
else:
    # Gather all unique timestamps across all series
    all_times = sorted(set(t for _, pts, _ in series for t, _ in pts))
    if not all_times:
        st.info("暂无有效时间点")
    else:
        # ── Playback controls ──
        st.subheader("📈 主力资金净流入 · 累计分时曲线")
        st.caption("拖动时间轴或点击播放查看资金流向演变 ｜ 暖色=流入端 冷色=流出端")

        col_play, col_speed, col_label = st.columns([1, 1, 4])
        with col_play:
            play_btn = st.button("▶ 播放" if not st.session_state.get("sf_playing", False)
                                 else "⏸ 暂停", key="sf_play")
            if play_btn:
                st.session_state["sf_playing"] = not st.session_state.get("sf_playing", False)
        with col_speed:
            speed = st.selectbox("速度", ["1x", "2x", "4x"], index=0, key="sf_speed",
                                 label_visibility="collapsed")
            speed_map = {"1x": 1, "2x": 2, "4x": 4}
            step = speed_map.get(speed, 1)

        # ── Timeline slider ──
        max_idx = len(all_times) - 1

        # 播放推进：必须在 widget 渲染前修改 session_state
        if "sf_slider" not in st.session_state:
            st.session_state["sf_slider"] = max_idx

        if st.session_state.get("sf_playing", False):
            next_idx = st.session_state["sf_slider"] + step
            if next_idx >= max_idx:
                st.session_state["sf_playing"] = False
                next_idx = max_idx
            st.session_state["sf_slider"] = next_idx

        current_idx = st.slider(
            "时间轴", 0, max_idx,
            key="sf_slider",
        )
        current_time = all_times[current_idx]
        with col_label:
            st.html(f"""
            <div style="padding-top:14px;font-size:16px;font-weight:bold;color:#333;">
                当前：<span style="color:#e53935;">{current_time}</span>
            </div>""")

        # ── Trigger next frame ──
        if st.session_state.get("sf_playing", False):
            st.rerun()

        # ── Chart: truncate to current_time ──
        import plotly.graph_objects as go

        fig = go.Figure()
        n_series = len(series)

        for i, (name, pts, final) in enumerate(series):
            # Truncate to current_time
            truncated = [(t, v) for t, v in pts if t <= current_time]
            if not truncated:
                continue
            times = [p[0] for p in truncated]
            vals = [p[1] for p in truncated]

            # Warm-to-cool color gradient
            ratio = i / max(n_series - 1, 1)
            if ratio <= 0.2:
                color = "#e53935"
            elif ratio <= 0.4:
                color = "#ff9800"
            elif ratio <= 0.6:
                color = "#8bc34a"
            elif ratio <= 0.8:
                color = "#00bcd4"
            else:
                color = "#42a5f5"

            fig.add_trace(go.Scatter(
                x=times, y=vals,
                mode="lines",
                name=name,
                line=dict(color=color, width=1.8),
                hovertemplate=f"<b>{name}</b><br>时间: %{{x}}<br>累计: %{{y:+.2f}}亿<extra></extra>",
            ))

            # End-point annotation
            if truncated:
                last_t, last_v = truncated[-1]
                label = f"{name} {last_v:+.1f}亿"
                fig.add_annotation(
                    x=last_t, y=last_v, text=label,
                    showarrow=False, xanchor="left", xshift=6,
                    font=dict(size=10, color=color),
                )

        # ── Zeroline ──
        fig.add_hline(y=0, line=dict(color="#999", width=1, dash="solid"))

        fig.update_layout(
            template="plotly_white",
            height=500,
            margin=dict(l=40, r=200, t=10, b=40),
            showlegend=False,
            hovermode="x unified",
            xaxis=dict(title="", type="category", tickangle=45,
                       tickmode="auto", nticks=20),
            yaxis=dict(title="累计净流入（亿元）"),
            dragmode="pan",
        )

        st.plotly_chart(fig, use_container_width=True, key="sf_chart")

# ══════════════════════════════════════════════
#  Leaderboard
# ══════════════════════════════════════════════

st.divider()

col_in, col_out = st.columns(2)

with col_in:
    st.subheader("🔥 累计净流入榜")
    inflow = [s for s in series if s[2] >= 0][:8]
    if inflow:
        rows = "".join(
            f"<tr><td style='color:#e53935;'>▲ {name}</td>"
            f"<td style='text-align:right;color:#e53935;font-weight:bold;'>{final:+.1f}亿</td></tr>"
            for name, _, final in inflow
        )
        st.html(f"""
        <table style="width:100%;font-size:15px;border-collapse:collapse;">
            <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;">
                <th>板块</th><th style="text-align:right;">累计净流入</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>""")
    else:
        st.info("暂无净流入板块")

with col_out:
    st.subheader("❄️ 累计净流出榜")
    outflow = [s for s in series if s[2] < 0][:8]
    if outflow:
        rows = "".join(
            f"<tr><td style='color:#43a047;'>▼ {name}</td>"
            f"<td style='text-align:right;color:#43a047;font-weight:bold;'>{final:+.1f}亿</td></tr>"
            for name, _, final in outflow
        )
        st.html(f"""
        <table style="width:100%;font-size:15px;border-collapse:collapse;">
            <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;">
                <th>板块</th><th style="text-align:right;">累计净流入</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>""")
    else:
        st.info("暂无净流出板块")

# ══════════════════════════════════════════════
#  Anomaly Detection (only meaningful for live)
# ══════════════════════════════════════════════

st.divider()
st.subheader("⚡ 近5分钟资金异动")
st.caption("比较当前与5分钟前的累计净流入变化，阈值：≥2亿 ｜ 仅盘中实时有意义")

trading_now = _service.is_market_trading_now()

if is_today and trading_now:
    # Maintain history in session_state
    if "sf_history" not in st.session_state:
        st.session_state.sf_history = []

    now_ts = datetime.now()
    st.session_state.sf_history.append({
        "t": now_ts,
        "snap": data.get("snapshot", {}),
    })
    # Prune older than 40 min
    cutoff = now_ts.timestamp() - 2400
    while st.session_state.sf_history and st.session_state.sf_history[0]["t"].timestamp() < cutoff:
        st.session_state.sf_history.pop(0)

    # Find 5-minute-ago snapshot
    five_min_ago = now_ts.timestamp() - 300
    prev_snap = None
    for h in reversed(st.session_state.sf_history):
        if h["t"].timestamp() <= five_min_ago:
            prev_snap = h["snap"]
            break

    if prev_snap:
        from marketreview.data.sector_flow import detect_anomalies
        inflows, outflows = detect_anomalies(data.get("snapshot", {}), prev_snap, top_n=3, floor_yi=2.0)

        col_anom_in, col_anom_out = st.columns(2)
        with col_anom_in:
            if inflows:
                rows = "".join(
                    f"<tr><td style='color:#e53935;'>⚡▲ {name}</td>"
                    f"<td style='text-align:right;color:#e53935;font-weight:bold;'>+{delta:.1f}亿/5min</td></tr>"
                    for name, delta, _ in inflows
                )
                st.html(f"""
                <table style="width:100%;font-size:15px;border-collapse:collapse;">
                    <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;">
                        <th>急流入</th><th style="text-align:right;">Δ净流入</th>
                    </tr></thead>
                    <tbody>{rows}</tbody>
                </table>""")
            else:
                st.info("近期无急流入异动")
        with col_anom_out:
            if outflows:
                rows = "".join(
                    f"<tr><td style='color:#43a047;'>⚡▼ {name}</td>"
                    f"<td style='text-align:right;color:#43a047;font-weight:bold;'>-{delta:.1f}亿/5min</td></tr>"
                    for name, delta, _ in outflows
                )
                st.html(f"""
                <table style="width:100%;font-size:15px;border-collapse:collapse;">
                    <thead><tr style="border-bottom:2px solid #e0e0e0;color:#888;">
                        <th>急流出</th><th style="text-align:right;">Δ净流入</th>
                    </tr></thead>
                    <tbody>{rows}</tbody>
                </table>""")
            else:
                st.info("近期无急流出异动")
    else:
        st.info("等待累积足够历史数据...（约5分钟）")
else:
    if not is_today:
        st.info("非当日数据，异动检测仅支持盘中实时")
    else:
        st.info("非交易时段，不计算异动")

# ══════════════════════════════════════════════
#  Blocked Sectors
# ══════════════════════════════════════════════

st.divider()
with st.expander("🚫 屏蔽板块（点击展开）", expanded=False):
    if "sf_blocked" not in st.session_state:
        st.session_state.sf_blocked = set()

    col_input, col_btn = st.columns([4, 1])
    with col_input:
        new_block = st.text_input("输入板块名", key="sf_block_input",
                                  label_visibility="collapsed",
                                  placeholder="输入板块名回车屏蔽")
    with col_btn:
        if st.button("屏蔽", key="sf_block_btn", use_container_width=True):
            if new_block and new_block.strip():
                st.session_state.sf_blocked.add(new_block.strip())
                st.cache_data.clear()
                st.rerun()

    if st.session_state.sf_blocked:
        chips_html = ""
        for name in sorted(st.session_state.sf_blocked):
            chips_html += (f"<span style='display:inline-block;background:#f0f0f0;"
                           f"border-radius:16px;padding:4px 10px;margin:3px;font-size:13px;'>"
                           f"{name}</span> ")
        st.html(f"<div>{chips_html}</div>")

        if st.button("清除全部屏蔽", key="sf_clear_blocked"):
            st.session_state.sf_blocked.clear()
            st.cache_data.clear()
            st.rerun()
    else:
        st.caption("未屏蔽任何板块")

# ══════════════════════════════════════════════
#  Footer
# ══════════════════════════════════════════════

st.divider()
st.caption("数据来源：东方财富 push2delay API → SQLite ｜ 主力 = 超大单 + 大单净额 ｜ 仅供研究，不构成投资建议")
