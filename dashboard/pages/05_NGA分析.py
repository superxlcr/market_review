"""
NGA 牛股计算器分析 — MACD 波段划分 + 斐波那契回调 + 搓揉线.

从 calc_index.html 移植:
  1. MACD 金叉/死叉 自动划分波段顶底 → 阶段高/低
  2. 斐波那契回调位 (0.382 常规买点 / 0.618 强防生死线 / 0.786 深坑)
  3. 观察模式信号 (无持仓成本, 只看价格位置)
  4. 搓揉线识别 (两日影线配对 + 趋势投票 → 8 种信号)
"""
import datetime as _dt
import logging
import streamlit as st
import pandas as pd
import numpy as np
import sys
import os

log = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from services.dashboard_service import DashboardService
from marketreview.tools.macd_swing import (
    find_macd_swing, calc_macd, calc_ema,
    calc_observation_signal, calculate_trend, classify_shadow, calculate_advice2,
    MacdSwingResult,
)
from rendering.styles import PAGE_CSS

st.set_page_config(page_title="NGA分析", page_icon="🧮", layout="wide")
st.markdown(PAGE_CSS, unsafe_allow_html=True)

svc = DashboardService()

st.title("🧮 NGA 牛股计算器分析")
st.caption("MACD 波段划分 + 斐波那契回调位 · 源自 NGA 策略 ｜ "
           f"AI v{DashboardService._AI_VERSION}")

# ── Trade date ──
latest_date = svc.get_latest_trade_date()
recent_dates = svc.get_recent_trading_dates(latest_date, count=120)
date_labels = [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in recent_dates]

# ── Stock selection ──
stocks_data = svc.get_watchlist_stocks()
watchlist = stocks_data.get("matched", [])
watchlist_codes = {s["ts_code"] for s in watchlist}

all_stocks = svc._dp.cache.get_stock_basic()
default_date = recent_dates[0] if recent_dates else latest_date
all_stocks = [s for s in all_stocks if s.get("list_date", "99999999") <= default_date]

wl_options: list[str] = []
other_options: list[str] = []
for s in all_stocks:
    label = f"{s['name']} ({s['ts_code']})"
    if s["ts_code"] in watchlist_codes:
        wl_options.append(label)
    else:
        other_options.append(label)
wl_options.sort()
other_options.sort()

stock_options = wl_options + other_options

# ── Controls ──
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    selected_label = st.selectbox(
        "📌 选择标的", stock_options,
        help="自选股排最前面。全 A 股可搜索。",
    )
    selected_code = selected_label.split("(")[-1].rstrip(")")
with col2:
    selected_date_label = st.selectbox(
        "📅 交易日", date_labels,
        help="选择分析截止交易日，默认为最新。",
    )
    selected_date = selected_date_label.replace("-", "")
with col3:
    display_tail = st.number_input(
        "图表K线数", min_value=50, max_value=500,
        value=50, step=50,
        help="图表展示最近多少根K线。",
    )

# ── Analyze button ──
if st.button("🔍 分析", type="primary", use_container_width=True):
    if not selected_code:
        st.error("请输入股票代码。")
    else:
        with st.spinner(f"加载 {selected_code} K线数据 + MACD 波段分析..."):
            try:
                # 拉取足够长的 K 线 (至少 180 日 → MACD 有足够上下文)
                fetch_days = 360
                buff_dt = _dt.datetime.strptime(selected_date, "%Y%m%d") - _dt.timedelta(days=fetch_days)
                start_date = buff_dt.strftime("%Y%m%d")
                svc._dp.ensure_data_loaded_for_codes([selected_code], start_date, selected_date)

                df = svc.get_index_data(selected_code, lookback=fetch_days, end_date=selected_date)
                if df.empty:
                    st.error(f"未找到 {selected_code} 的K线数据。")
                    st.stop()

                # 转为 rows (date ASC)
                rows_asc = df.to_dict("records")

                # 检测最后一根 K 线是否为盘中未收盘的
                today_str = f"{selected_date[:4]}-{selected_date[4:6]}-{selected_date[6:]}"
                last_bar_date = str(rows_asc[-1].get("date", ""))
                last_bar_incomplete = (last_bar_date == today_str)

                # ── MACD 波段分析 ──
                swing = find_macd_swing(rows_asc, window_size=30,
                                        last_bar_incomplete=last_bar_incomplete)

                # ── 当前价 + 是否新高 ──
                current_price = float(rows_asc[-1].get("close", 0) or 0)
                is_new_high = current_price > swing.high and swing.high > 0

                # ── 观察模式信号 ──
                signal_text, signal_class = calc_observation_signal(
                    swing, current_price, is_new_high
                )

                # ── 搓揉线 ──
                closes_full = [float(r.get("close", 0) or 0) for r in rows_asc]
                trend = calculate_trend(closes_full, current_price)

                advice2 = {"text": "数据不足", "className": "advice-normal"}
                if len(rows_asc) >= 2:
                    yesterday = rows_asc[-2]
                    today = rows_asc[-1]
                    advice2 = calculate_advice2(yesterday, today, trend)

                # ── 回调一半序列（从阶段顶开始，逐日 (high + running_low)/2，跌破0.618后才画）──
                half_retrace_series: list[dict] = []
                half_retrace_trigger_date: str = ""
                if swing.fibonacci_valid and swing.high > 0 and swing.f618 > 0:
                    # 找阶段顶部对应的 K 线（最后一次出现 high 的 bar）
                    peak_idx = -1
                    for idx in range(len(rows_asc) - 1, -1, -1):
                        if abs(float(rows_asc[idx].get("high", 0) or 0) - swing.high) < 0.01:
                            peak_idx = idx
                            break
                    if peak_idx >= 0:
                        running_low = float(rows_asc[peak_idx].get("low", swing.high) or swing.high)
                        triggered = False
                        for idx in range(peak_idx, len(rows_asc)):
                            bar_low = float(rows_asc[idx].get("low", 0) or 0)
                            bar_date = str(rows_asc[idx].get("date", ""))
                            if bar_low > 0 and bar_low < running_low:
                                running_low = bar_low
                            hr_price = round((swing.high + running_low) / 2.0, 2)
                            # 跌破 0.618 才激活
                            if not triggered and bar_low > 0 and bar_low < swing.f618:
                                triggered = True
                                half_retrace_trigger_date = bar_date
                            if triggered:
                                half_retrace_series.append({
                                    "date": bar_date,
                                    "price": hr_price,
                                })
                half_retrace_current = half_retrace_series[-1]["price"] if half_retrace_series else 0.0

                # ── 存 session ──
                st.session_state.nga_df = df
                st.session_state.nga_swing = swing
                st.session_state.nga_code = selected_code
                st.session_state.nga_signal = signal_text
                st.session_state.nga_signal_class = signal_class
                st.session_state.nga_is_new_high = is_new_high
                st.session_state.nga_current_price = current_price
                st.session_state.nga_trend = trend
                st.session_state.nga_advice2 = advice2
                st.session_state.nga_rows = rows_asc
                st.session_state.nga_last_incomplete = last_bar_incomplete
                st.session_state.nga_half_retrace_series = half_retrace_series
                st.session_state.nga_half_retrace_current = half_retrace_current

                st.success(f"✅ {selected_code} MACD 波段分析完成")

            except Exception as e:
                st.error(f"加载失败: {e}")
                import traceback
                st.code(traceback.format_exc())

# ── Display results ──
if st.session_state.get("nga_swing"):
    swing: MacdSwingResult = st.session_state.nga_swing
    df: pd.DataFrame = st.session_state.nga_df
    code = st.session_state.get("nga_code", "")
    signal_text = st.session_state.get("nga_signal", "")
    signal_class = st.session_state.get("nga_signal_class", "")
    is_new_high = st.session_state.get("nga_is_new_high", False)
    current_price = st.session_state.get("nga_current_price", 0.0)
    trend = st.session_state.get("nga_trend", "side")
    advice2 = st.session_state.get("nga_advice2", {"text": "—", "className": "advice-normal"})
    rows_asc = st.session_state.get("nga_rows", [])
    last_incomplete = st.session_state.get("nga_last_incomplete", False)
    half_retrace_series = st.session_state.get("nga_half_retrace_series", [])
    half_retrace_current = st.session_state.get("nga_half_retrace_current", 0.0)

    if swing.block_reason:
        st.warning(f"⚠️ {swing.block_reason}")
        st.stop()

    # ═══════════════════════════════════════════════
    # Row 1 — 核心指标卡片
    # ═══════════════════════════════════════════════
    st.divider()
    st.subheader("📊 MACD 波段结构")

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("阶段顶部", f"{swing.high:.2f}", delta=f"来源: {swing.high_source}")
    with c2:
        st.metric("阶段底部", f"{swing.low:.2f}", delta=f"来源: {swing.low_source}")
    with c3:
        band_pct = swing.band_range_pct
        st.metric("波段幅度", f"{swing.band_range:.2f}",
                  delta=f"{band_pct:+.1f}%")
    with c4:
        st.metric("当前价", f"{current_price:.2f}",
                  delta=f"{'突破新高' if is_new_high else ''}")
    with c5:
        # 信号 badge
        signal_color = {
            "advice-danger": "#f5222d", "advice-warning": "#e6a23c",
            "advice-blue": "#1890ff", "advice-cyan": "#13c2c2",
            "advice-normal": "#bfbfbf", "advice-gold": "#faad14",
        }.get(signal_class, "#bfbfbf")
        st.html(f"""
        <div style="border:1px solid #e0e0e0;border-radius:0.5rem;padding:0.5rem 0.5rem;">
            <div style="font-size:0.75rem;color:#888;margin-bottom:0.25rem;">💡 操作建议</div>
            <div style="font-size:1.3rem;font-weight:700;color:{signal_color};">{signal_text}</div>
        </div>
        """)

    # ═══════════════════════════════════════════════
    # Row 2 — 斐波那契回调位
    # ═══════════════════════════════════════════════
    st.divider()
    if swing.fibonacci_valid:
        st.subheader("📐 斐波那契回调位")
    else:
        st.subheader("📐 斐波那契回调位 （⚠️ 上一波段 — 当前为筑底反弹，非回调）")

    # 始终显示斐波那契卡片 (无效时回退到上一个死叉波段)
    fc_half, fc1, fc2, fc3, fc4 = st.columns(5)
    with fc_half:
        if half_retrace_current > 0:
            dist_half = (current_price / half_retrace_current - 1) * 100
            st.html(f"""
            <div style="border-radius:0.5rem;padding:0.75rem;text-align:center;
                        background:linear-gradient(135deg,#fff3e0,#ffe0b2);border:2px solid #ff6d00;">
                <div style="font-size:0.75rem;color:#e65100;">回调一半</div>
                <div style="font-size:1.6rem;font-weight:700;color:#bf360c;">{half_retrace_current:.2f}</div>
                <div style="font-size:0.8rem;color:#888;">距现价 {dist_half:+.1f}%</div>
                <div style="font-size:0.7rem;color:#888;">(P + 当前最低) / 2</div>
            </div>
            """)
        else:
            st.html("""
            <div style="border-radius:0.5rem;padding:0.75rem;text-align:center;
                        background:#f5f5f5;border:1px dashed #ccc;">
                <div style="font-size:0.75rem;color:#888;">回调一半</div>
                <div style="font-size:1.2rem;font-weight:700;color:#999;">—</div>
                <div style="font-size:0.7rem;color:#999;">尚未跌破 0.618</div>
            </div>
            """)
    with fc1:
        dist_382 = (current_price / swing.f382 - 1) * 100 if swing.f382 > 0 else 0
        highlight_382 = abs(dist_382) <= 3.0
        bg_382 = "background:#e6f7ff;border:2px solid #13c2c2;" if highlight_382 else ""
        st.html(f"""
        <div style="border-radius:0.5rem;padding:0.75rem;text-align:center;{bg_382}">
            <div style="font-size:0.75rem;color:#888;">0.382 常规买点</div>
            <div style="font-size:1.6rem;font-weight:700;color:#13c2c2;">{swing.f382}</div>
            <div style="font-size:0.8rem;color:#888;">距现价 {dist_382:+.1f}%</div>
            <div style="font-size:0.7rem;color:#888;">强势龙头首阴/浅回踩</div>
        </div>
        """)

    with fc2:
        dist_618 = (current_price / swing.f618 - 1) * 100 if swing.f618 > 0 else 0
        highlight_618 = abs(dist_618) <= 3.0
        bg_618 = "background:#fffbe6;border:2px solid #faad14;" if highlight_618 else ""
        st.html(f"""
        <div style="border-radius:0.5rem;padding:0.75rem;text-align:center;{bg_618}">
            <div style="font-size:0.75rem;color:#888;">0.618 强防生死线 ⭐</div>
            <div style="font-size:1.6rem;font-weight:700;color:#faad14;">{swing.f618}</div>
            <div style="font-size:0.8rem;color:#888;">距现价 {dist_618:+.1f}%</div>
            <div style="font-size:0.7rem;color:#888;">波段多空生死线</div>
        </div>
        """)

    with fc3:
        dist_786 = (current_price / swing.f786 - 1) * 100 if swing.f786 > 0 else 0
        st.html(f"""
        <div style="border-radius:0.5rem;padding:0.75rem;text-align:center;">
            <div style="font-size:0.75rem;color:#888;">0.786 深坑</div>
            <div style="font-size:1.6rem;font-weight:700;color:#f5222d;">{swing.f786}</div>
            <div style="font-size:0.8rem;color:#888;">距现价 {dist_786:+.1f}%</div>
            <div style="font-size:0.7rem;color:#888;">套牢盘极重/放弃观察</div>
        </div>
        """)

    with fc4:
        dist_mid = (current_price / swing.mid_point - 1) * 100 if swing.mid_point > 0 else 0
        st.html(f"""
        <div style="border-radius:0.5rem;padding:0.75rem;text-align:center;">
            <div style="font-size:0.75rem;color:#888;">50% 中位线</div>
            <div style="font-size:1.6rem;font-weight:700;color:#909399;">{swing.mid_point}</div>
            <div style="font-size:0.8rem;color:#888;">距现价 {dist_mid:+.1f}%</div>
            <div style="font-size:0.7rem;color:#888;">参考中间位</div>
        </div>
        """)

    # ═══════════════════════════════════════════════
    # Row 3 — MACD 交叉统计 + 信号判定逻辑
    # ═══════════════════════════════════════════════
    st.divider()
    st.subheader("🔍 信号判定详情")

    detail_c1, detail_c2 = st.columns([1, 1])

    with detail_c1:
        st.markdown("**MACD 交叉统计**")
        cross_info = (
            f"- 金叉次数: **{swing.golden_cross_count}**\n"
            f"- 死叉次数: **{swing.death_cross_count}**\n"
            f"- 最后一次交叉: **{'金叉' if swing.last_cross_type == 'golden' else '死叉' if swing.last_cross_type == 'death' else '无'}**\n"
            f"- 顶部来源: `{swing.high_source}` ({swing.high:.2f})\n"
            f"- 底部来源: `{swing.low_source}` ({swing.low:.2f})\n"
            f"- 盘中未收盘K线: {'**是**（不参与交叉判定）' if last_incomplete else '否'}"
        )
        st.markdown(cross_info)

        st.markdown("**信号判定逻辑**")
        if swing.fibonacci_valid:
            f618_99 = swing.f618 * 0.99
            mid_102 = swing.mid_point * 1.02
            f382_103 = swing.f382 * 1.03
            logic_lines = [
                f"1. 现价 < 底部({swing.low:.2f})? → {'✅ 破位严禁' if current_price < swing.low else '否'}",
                f"2. 现价 < f786({swing.f786:.3f})? → {'✅ 放弃(极弱)' if current_price < swing.f786 else '否'}",
                f"3. 现价 < f618×0.99({f618_99:.3f})? → {'✅ 跌破618(弱)' if current_price < f618_99 else '否'}",
                f"4. 现价 ≤ 中位×1.02({mid_102:.3f})? → {'✅ 强防生死线' if current_price <= mid_102 else '否'}",
                f"5. 现价 ≤ f382×1.03({f382_103:.3f})? → {'✅ 常规买点' if current_price <= f382_103 else '否'}",
                f"6. 其他? → {'✅ 高位观望' if current_price > f382_103 else '—'}",
            ]
        else:
            logic_lines = [
                "⚠️ 斐波那契不适用（高在前低在后），仅判断破位：",
                f"1. 现价 < 底部({swing.low:.2f})? → {'✅ 破位严禁' if current_price < swing.low else '否'}",
                "2. 斐波那契回调位已禁用 — 等待死叉确认上升波段后再分析",
            ]
        st.markdown("\n".join(logic_lines))

    with detail_c2:
        st.markdown("**搓揉线分析**")
        if len(rows_asc) >= 2:
            yesterday = rows_asc[-2]
            today = rows_asc[-1]
            y_shadow = classify_shadow(yesterday)
            t_shadow = classify_shadow(today)
            t_open = float(today.get("open", 0) or 0)
            t_close = float(today.get("close", 0) or 0)
            t_color = "阳线 🔴" if t_close > t_open else ("阴线 🟢" if t_close < t_open else "十字星")

            st.markdown(
                f"- 趋势方向: **{trend}** "
                f"({'↑ 上升' if trend == 'up' else '↓ 下降' if trend == 'down' else '↔ 震荡'})\n"
                f"- 昨日影线: **{y_shadow}** "
                f"({'上影线' if y_shadow == 'upper' else '下影线' if y_shadow == 'lower' else '无显著影线'})\n"
                f"- 今日影线: **{t_shadow}** "
                f"({'上影线' if t_shadow == 'upper' else '下影线' if t_shadow == 'lower' else '无显著影线'})\n"
                f"- 今日K线: **{t_color}**\n"
                f"- 搓揉线配对: **{'是' if y_shadow != 'none' and t_shadow != 'none' and y_shadow != t_shadow else '否'}** "
                f"({'昨' + y_shadow + '→今' + t_shadow})"
            )

            advice_color = {
                "advice-danger": "#f5222d", "advice-warning": "#e6a23c",
                "advice-blue": "#1890ff", "advice-cyan": "#13c2c2",
                "advice-normal": "#bfbfbf", "advice-gold": "#faad14",
            }.get(advice2.get("className", ""), "#bfbfbf")

            st.markdown(
                f"**搓揉线信号**: "
                f"<span style='color:{advice_color};font-weight:bold;font-size:1.2rem;'>"
                f"{advice2.get('text', '—')}</span>",
                unsafe_allow_html=True,
            )

            st.caption(
                "搓揉线 = 连续两天影线方向相反（昨下影+今上影 或 昨上影+今下影），"
                "代表多空双方在两天内轮流试探对方防线，是\"主力洗盘/试盘\"的常见形态。"
            )
        else:
            st.caption("数据不足，无法分析搓揉线")

    # ═══════════════════════════════════════════════
    # Row 4 — K线图 + MACD 副图
    # ═══════════════════════════════════════════════
    st.divider()
    st.subheader(f"📈 {code} — MACD 波段 + 斐波那契回调位")

    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    plot_df = df.tail(display_tail).copy()
    # 短日期用于 x 轴 (20260609 → 0609)
    date_short = plot_df["date"].astype(str).str[4:]
    closes_full = [float(r.get("close", 0) or 0) for r in rows_asc]
    macd_full = calc_macd(closes_full)
    macd_tail = macd_full[-display_tail:] if len(macd_full) >= display_tail else macd_full

    # 涨跌幅用于 hover
    prev_close = df["close"].shift(1)
    chg_pct = ((df["close"] - prev_close) / prev_close * 100).round(2)
    chg_tail = chg_pct.tail(display_tail).to_numpy()

    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=[0.42, 0.13, 0.225, 0.225],
    )

    # ── Row 1: K线 + 斐波那契线 + 均线 ──
    fig.add_trace(go.Candlestick(
        x=date_short, open=plot_df["open"], high=plot_df["high"],
        low=plot_df["low"], close=plot_df["close"], name="K线",
        increasing_line_color="#e53935", decreasing_line_color="#43a047",
        customdata=chg_tail,
        hovertemplate=(
            "日期: %{x}<br>"
            "开: %{open:.2f} 高: %{high:.2f}<br>"
            "低: %{low:.2f} 收: %{close:.2f}<br>"
            "涨跌幅: %{customdata:+.2f}%<extra></extra>"
        ),
    ), row=1, col=1)

    # 均线 MA5 / MA10 / MA20 / MA60 / MA120 / MA240
    # 用全量数据计算 MA, 只截尾部 display_tail 根画图
    ma_configs = [
        (5, "#2196f3", 1.0),
        (10, "#ff9800", 1.0),
        (20, "#9c27b0", 1.2),
        (60, "#4caf50", 1.2),
        (120, "#795548", 1.0),
        (240, "#e91e63", 1.0),
    ]
    full_closes = df["close"].tolist()
    for period, color, width in ma_configs:
        if len(full_closes) >= period:
            # 全量计算 SMA
            ma_full = [sum(full_closes[max(0, i - period + 1):i + 1]) / min(i + 1, period)
                       for i in range(len(full_closes))]
            ma_tail = ma_full[-display_tail:]
            fig.add_trace(go.Scatter(
                x=date_short, y=ma_tail, mode="lines",
                line=dict(color=color, width=width), name=f"MA{period}",
                hovertemplate=f"MA{period}: %{{y:.2f}}<extra></extra>",
            ), row=1, col=1)

    # 回调一半动态线 (从阶段顶开始, 逐日 (high + running_low)/2)
    if half_retrace_series:
        hr_map = {p["date"]: p["price"] for p in half_retrace_series}
        hr_y = [hr_map.get(d, None) for d in plot_df["date"]]
        if any(v is not None for v in hr_y):
            fig.add_trace(go.Scatter(
                x=date_short, y=hr_y, mode="lines+markers",
                line=dict(color="#ff6d00", width=1.5), marker=dict(size=3, color="#ff6d00"),
                name=f"回调一半 {half_retrace_current:.2f}",
                connectgaps=False,
                hovertemplate="回调一半: %{y:.2f}<extra></extra>",
            ), row=1, col=1)

    # 斐波那契水平线 (始终显示, 无效时显示的是上一个上升波段)
    fib_configs = [
        (swing.f382, "0.382 常规买点", "#13c2c2"),
        (swing.f618, "0.618 强防生死线", "#faad14"),
        (swing.f786, "0.786 深坑", "#f5222d"),
        (swing.mid_point, "50% 中位", "#909399"),
    ]
    fib_dash = "dash" if swing.fibonacci_valid else "dot"  # 无效时点线区分
    for price, label, color in fib_configs:
        if price > 0:
            fig.add_hline(
                y=price, line=dict(color=color, width=1.2, dash=fib_dash),
                annotation_text=f"{label} {price:.2f}",
                annotation_position="top left",
                annotation_font=dict(color=color, size=10),
                row=1, col=1,
            )

    # 阶段顶/底 标识
    fig.add_hline(
        y=swing.high, line=dict(color="#cc96f8", width=1.5, dash="dot"),
        annotation_text=f"顶 {swing.high:.2f}",
        annotation_position="top left",
        annotation_font=dict(color="#cc96f8", size=10),
        row=1, col=1,
    )
    fig.add_hline(
        y=swing.low, line=dict(color="#ff5252", width=1.5, dash="dot"),
        annotation_text=f"底 {swing.low:.2f}",
        annotation_position="bottom left",
        annotation_font=dict(color="#ff5252", size=10),
        row=1, col=1,
    )

    # ── Row 2: 成交额 (亿) + MA5/MA10 ──
    amount_yi = plot_df["amount"].to_numpy() / 1e5  # 千元→亿
    amount_colors = [
        "#e53935" if plot_df.iloc[i]["close"] >= plot_df.iloc[i]["open"] else "#43a047"
        for i in range(len(plot_df))
    ]
    fig.add_trace(go.Bar(
        x=date_short, y=amount_yi, marker_color=amount_colors,
        name="成交额",
        hovertemplate="成交额: %{y:.1f}亿<extra></extra>",
    ), row=2, col=1)

    # 成交额 MA5 / MA10 (全量计算, 截尾画图)
    full_amount = df["amount"].to_numpy() / 1e5
    for period, color in [(5, "#ff9800"), (10, "#2196f3")]:
        if len(full_amount) >= period:
            amt_ma = [sum(full_amount[max(0, i - period + 1):i + 1]) / min(i + 1, period)
                      for i in range(len(full_amount))]
            amt_ma_tail = amt_ma[-display_tail:]
            fig.add_trace(go.Scatter(
                x=date_short, y=amt_ma_tail, mode="lines",
                line=dict(color=color, width=1.0), name=f"成交额MA{period}",
                hovertemplate=f"成交额MA{period}: %{{y:.1f}}亿<extra></extra>",
            ), row=2, col=1)

    # ── Row 3: MACD 柱 ──
    macd_x = date_short.tolist()
    macd_vals = [m["macd"] for m in macd_tail]
    # 红涨绿跌
    macd_colors = ["#e53935" if v >= 0 else "#43a047" for v in macd_vals]
    fig.add_trace(go.Bar(
        x=macd_x, y=macd_vals, marker_color=macd_colors,
        name="MACD 柱",
        hovertemplate="MACD: %{y:.4f}<extra></extra>",
    ), row=3, col=1)

    # ── Row 4: DIFF + DEA ──
    diff_vals = [m["diff"] for m in macd_tail]
    dea_vals = [m["dea"] for m in macd_tail]
    fig.add_trace(go.Scatter(
        x=macd_x, y=diff_vals, mode="lines",
        line=dict(color="#2196f3", width=1.2), name="DIFF",
        hovertemplate="DIFF: %{y:.4f}<extra></extra>",
    ), row=4, col=1)
    fig.add_trace(go.Scatter(
        x=macd_x, y=dea_vals, mode="lines",
        line=dict(color="#ff9800", width=1.2), name="DEA",
        hovertemplate="DEA: %{y:.4f}<extra></extra>",
    ), row=4, col=1)

    # 零轴
    fig.add_hline(y=0, line=dict(color="#888", width=0.5), row=3, col=1)
    fig.add_hline(y=0, line=dict(color="#888", width=0.5), row=4, col=1)

    # Lock y-axis range to visible K-lines
    y_min = plot_df["low"].min()
    y_max = plot_df["high"].max()
    y_pad = (y_max - y_min) * 0.12
    fig.update_yaxes(range=[y_min - y_pad, y_max + y_pad], row=1, col=1)

    fig.update_layout(
        xaxis_rangeslider_visible=False,
        template="plotly_white", height=850,
        margin=dict(l=20, r=20, t=10, b=20),
        legend=dict(orientation="h", yanchor="top", y=1.05, xanchor="left", x=0),
        hovermode="x unified",
    )
    fig.update_xaxes(title_text="", showticklabels=False, row=1, col=1)
    fig.update_xaxes(title_text="", showticklabels=False, row=2, col=1)
    fig.update_xaxes(title_text="", showticklabels=False, row=3, col=1)
    fig.update_xaxes(title_text="日期", showticklabels=True, row=4, col=1)
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="成交额（亿）", row=2, col=1)
    fig.update_yaxes(title_text="MACD 柱", row=3, col=1)
    fig.update_yaxes(title_text="DIFF / DEA", row=4, col=1)

    st.plotly_chart(fig, use_container_width=True)

st.divider()
st.caption(
    "💡 来源: NGA 牛股计算器 (calc_index.html) — "
    "MACD 金叉=下跌段结束取最低点为底, 死叉=上涨段结束取最高点为顶; "
    "盘中K线不参与交叉判定, 尾段双向追踪新极值。"
)
