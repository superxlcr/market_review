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
        horizontal=True, index=1, key="sf_mode",
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

# Card colors — use warm for inflow, cool for outflow (matching chart gradient)
CARD_IN_COLOR = "#ff6f83"
CARD_OUT_COLOR = "#39d9ff"

cols = st.columns(4)
for col, (label, value, meta, orig_color) in zip(cols, cards_data):
    # Map card colors to the dark theme palette
    if label == "最强流入":
        accent = CARD_IN_COLOR
    elif label == "最强流出":
        accent = CARD_OUT_COLOR
    else:
        accent = "#90a7cf"
    with col:
        st.html(f"""
        <div style="
            background: linear-gradient(160deg, rgba(20,34,69,0.92), rgba(12,21,44,0.92));
            border: 1px solid rgba(125,154,211,0.18);
            border-radius: 16px;
            padding: 15px 16px;
            text-align: center;
            position: relative;
            overflow: hidden;
        ">
            <div style="
                position: absolute;
                inset: auto -30px -40px auto;
                width: 110px; height: 110px;
                border-radius: 50%;
                background: radial-gradient(circle, {accent}22, transparent 68%);
                pointer-events: none;
            "></div>
            <div style="font-size: 12px; color: #90a7cf; margin-bottom: 8px; position: relative; z-index: 1;">
                {label}
            </div>
            <div style="font-size: 24px; font-weight: 800; color: {accent}; line-height: 1.1; position: relative; z-index: 1;">
                {value}
            </div>
            <div style="font-size: 12px; color: #bdd1f2; margin-top: 7px; line-height: 1.5; position: relative; z-index: 1;">
                {meta}
            </div>
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
        # ── Timeline slider ──
        st.subheader("📈 主力资金净流入 · 累计分时曲线")
        st.caption("拖动时间轴查看资金流向演变 ｜ 暖色=流入端 冷色=流出端")

        max_idx = len(all_times) - 1
        if "sf_slider" not in st.session_state:
            st.session_state["sf_slider"] = max_idx

        current_idx = st.slider(
            "时间轴", 0, max_idx,
            key="sf_slider",
        )
        current_time = all_times[current_idx]
        st.caption(f"当前：**{current_time}**")

        # ── Chart: truncate to current_time ──
        import plotly.graph_objects as go
        import math

        # ── HSL → hex (same as reference HTML) ──
        def _hsl_hex(h: float, s: float = 0.70, l: float = 0.60) -> str:
            """h in [0,360], s/l in [0,1] → #rrggbb"""
            c = (1 - abs(2 * l - 1)) * s
            hp = (h % 360) / 60.0
            x = c * (1 - abs(hp % 2 - 1))
            m = l - c / 2
            sector = int(hp)
            if sector == 0:   r, g, b = c, x, 0
            elif sector == 1: r, g, b = x, c, 0
            elif sector == 2: r, g, b = 0, c, x
            elif sector == 3: r, g, b = 0, x, c
            elif sector == 4: r, g, b = x, 0, c
            else:             r, g, b = c, 0, x
            return "#{:02x}{:02x}{:02x}".format(
                round((r + m) * 255), round((g + m) * 255), round((b + m) * 255))

        fig = go.Figure()
        n_series = len(series)
        # Warm (hue=0, red) for top-inflow → cool (hue=215, blue) for top-outflow
        hue_base = 215.0

        # ── Build label list for anti-collision ──
        label_entries: list[dict] = []

        for i, (name, pts, final) in enumerate(series):
            # Truncate to current_time
            truncated = [(t, v) for t, v in pts if t <= current_time]
            if not truncated:
                continue
            times = [p[0] for p in truncated]
            vals = [p[1] for p in truncated]

            hue = hue_base * (i / max(n_series - 1, 1))
            color = _hsl_hex(hue)

            fig.add_trace(go.Scatter(
                x=times, y=vals,
                mode="lines",
                name=name,
                line=dict(color=color, width=2.0, shape="linear"),
                hovertemplate=(
                    f"<b>{name}</b><br>"
                    f"时间: %{{x}}<br>"
                    f"累计: %{{y:+.2f}}亿<extra></extra>"
                ),
            ))

            # Record label for anti-collision layout
            if truncated:
                last_t, last_v = truncated[-1]
                label_entries.append({
                    "name": name, "t": last_t, "v_raw": last_v,
                    "v_str": f"{last_v:+.1f}亿", "color": color,
                    "rank": i,
                })

        # ── Anti-collision: spread labels on y-axis if too close ──
        if label_entries:
            # Sort by y-value for collision detection
            label_entries.sort(key=lambda e: e["v_raw"])
            y_range = max(e["v_raw"] for e in label_entries) - min(e["v_raw"] for e in label_entries)
            min_gap = y_range / max(len(label_entries), 1) * 0.85  # minimum gap
            if min_gap < 0.2:
                min_gap = 2.0  # absolute floor for tight clusters

            # Push apart from top to bottom
            for k in range(1, len(label_entries)):
                prev = label_entries[k - 1]
                cur = label_entries[k]
                needed = prev["v_raw"] + min_gap
                if cur["v_raw"] < needed:
                    cur["v_raw"] = needed

            # If pushing caused overflow at the top, compress from the bottom instead
            overflow = label_entries[-1]["v_raw"] - max(e["v_raw"] for e in label_entries)
            if overflow > min_gap:
                for e in label_entries:
                    e["v_raw"] -= overflow * 0.5

            for e in label_entries:
                label_text = f"<b>{e['name']}</b> {e['v_str']}"
                fig.add_annotation(
                    x=e["t"], y=e["v_raw"],
                    text=label_text,
                    showarrow=False,
                    xanchor="left", xshift=8,
                    font=dict(size=12, color=e["color"]),
                    bgcolor="rgba(8,14,27,0.82)",
                    borderpad=2,
                )

        # ── Zeroline ──
        fig.add_hline(
            y=0, line=dict(color="rgba(125,154,211,0.45)", width=1.2, dash="solid"),
        )

        # ── Layout ──
        fig.update_layout(
            template="plotly_dark",
            height=800,
            margin=dict(l=56, r=28, t=10, b=40),
            paper_bgcolor="rgba(8,17,31,0.95)",
            plot_bgcolor="rgba(8,17,31,0.92)",
            showlegend=True,
            legend=dict(
                orientation="v",
                yanchor="top", y=0.98,
                xanchor="left", x=1.01,
                bgcolor="rgba(8,14,27,0.75)",
                bordercolor="rgba(125,154,211,0.18)",
                font=dict(size=11, color="#90a7cf"),
                itemclick="toggle",
                itemdoubleclick="toggleothers",
            ),
            hovermode="x unified",
            hoverlabel=dict(
                bgcolor="rgba(8,14,27,0.94)",
                bordercolor="rgba(123,156,221,0.28)",
                font=dict(size=13, color="#d5e6ff"),
            ),
            xaxis=dict(
                title="", type="category", tickangle=45,
                tickmode="auto", nticks=20,
                tickfont=dict(size=11, color="#7e93b8"),
                gridcolor="rgba(125,154,211,0.08)",
                zeroline=False,
            ),
            yaxis=dict(
                title=dict(text="累计净流入（亿元）", font=dict(size=13, color="#90a7cf")),
                tickfont=dict(size=12, color="#7e93b8"),
                gridcolor="rgba(125,154,211,0.13)",
                zeroline=False,
            ),
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
