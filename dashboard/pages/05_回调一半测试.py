"""回调一半战法 — 可视化测试页面.

对每天计算半分位价格，连成「回调一半线」叠加在K线图上，
纵轴=价格，横轴=时间，像均线一样观察半分位变化。
"""
import datetime as _dt
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from services.dashboard_service import DashboardService
from rendering.styles import PAGE_CSS

st.set_page_config(page_title="回调测试", page_icon="🔍", layout="wide")
st.markdown(PAGE_CSS, unsafe_allow_html=True)

svc = DashboardService()

st.title("🔍 回调一半战法 — 可视化测试")
st.caption(f"每天算一个半分位价格 → 连成线 → 叠加K线 ｜ AI v{DashboardService._AI_VERSION}")


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _safe_float(v) -> float:
    """Convert to float, return 0.0 on failure."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def _compute_hr_series(rows_asc: list[dict], variant: str,
                       peak_lookback: int = 126) -> list[dict]:
    """逐日计算「回调一半」半分位，返回时间序列。

    完全复刻 half_retrace / half_retrace_simple 的 check_buy 逻辑，
    对每一天判断是否满足条件，满足则记录半分位价格。

    Args:
        peak_lookback: 波峰回溯交易日数，策略默认126（~6个月）。

    Returns:
        [{date, midpoint, peak_high, peak_date, lowest_low, triggered}, ...]
    """
    PULLBACK_MIN = 13

    if len(rows_asc) < PULLBACK_MIN + 2:
        return []

    points: list[dict] = []

    for today_idx in range(PULLBACK_MIN + 1, len(rows_asc)):
        # ── 1. 找波段新高 P ──
        lookback_start = max(0, today_idx - peak_lookback)
        peak_high, peak_idx = 0.0, -1
        for i in range(lookback_start, today_idx + 1):
            h = _safe_float(rows_asc[i].get("high"))
            if h > peak_high:
                peak_high = h
                peak_idx = i

        if peak_idx < 0 or peak_high <= 0:
            continue
        if today_idx - peak_idx < PULLBACK_MIN:
            continue

        # ── 2. 找前低 V ──
        if variant == "half_retrace":
            valley_low = float("inf")
            for i in range(0, peak_idx):
                lv = _safe_float(rows_asc[i].get("low"))
                if lv < valley_low:
                    valley_low = lv

            if valley_low >= peak_high or valley_low <= 0:
                continue

            # ── 3. V 资格校验 ──
            midpoint_pv = (peak_high + valley_low) / 2.0
            line_625 = valley_low + 0.625 * (peak_high - valley_low)
            if midpoint_pv * 1.1 >= line_625:
                continue
        else:
            valley_low = peak_high / 2.33
            line_625 = valley_low + 0.625 * (peak_high - valley_low)

        # ── 4. 必须已跌破过 62.5% 线 ──
        has_broken = False
        for i in range(peak_idx, today_idx + 1):
            if _safe_float(rows_asc[i].get("low")) <= line_625:
                has_broken = True
                break
        if not has_broken:
            continue

        # ── 5. 找 P 至今最低 low L，算半分位 ──
        lowest_low = float("inf")
        for i in range(peak_idx, today_idx + 1):
            lv = _safe_float(rows_asc[i].get("low"))
            if lv < lowest_low:
                lowest_low = lv

        midpoint = (peak_high + lowest_low) / 2.0

        # ── 6. 触发条件 ──
        yesterday_close = _safe_float(rows_asc[today_idx - 1].get("close"))

        points.append({
            "date": str(rows_asc[today_idx].get("date", "")),
            "midpoint": round(midpoint, 2),
            "peak_high": round(peak_high, 2),
            "peak_date": str(rows_asc[peak_idx].get("date", "")),
            "lowest_low": round(lowest_low, 2),
            "triggered": yesterday_close < midpoint,
        })

    return points


def _diagnose_latest(rows_asc: list[dict], variant: str,
                     peak_lookback: int = 126) -> str:
    """诊断最新交易日为何未产生半分位（复刻 half_retrace.diagnose_buy）。

    Returns:
        空字符串 = 正常触发；非空 = 阻断原因。
    """
    PULLBACK_MIN = 13

    if len(rows_asc) < PULLBACK_MIN + 2:
        return f"K线不足（需≥{PULLBACK_MIN + 2}日，当前{len(rows_asc)}日）"

    today_idx = len(rows_asc) - 1

    # 1. 找波峰 P
    lookback_start = max(0, today_idx - peak_lookback)
    peak_high, peak_idx = 0.0, -1
    for i in range(lookback_start, today_idx + 1):
        h = _safe_float(rows_asc[i].get("high"))
        if h > peak_high:
            peak_high, peak_idx = h, i

    if peak_idx < 0 or peak_high <= 0:
        return f"近{peak_lookback}日内未找到有效波峰"

    peak_date = str(rows_asc[peak_idx].get("date", "?"))
    days_since = today_idx - peak_idx
    if days_since < PULLBACK_MIN:
        return (
            f"P={peak_high:.2f}（{peak_date}）距今仅{days_since}日，"
            f"需≥{PULLBACK_MIN}日"
        )

    # 2. 找前低 V
    if variant == "half_retrace":
        valley_low = float("inf")
        for i in range(0, peak_idx):
            lv = _safe_float(rows_asc[i].get("low"))
            if lv < valley_low:
                valley_low = lv

        if valley_low >= peak_high or valley_low <= 0:
            return f"P={peak_high:.2f}（{peak_date}），波峰前未找到有效波谷"

        midpoint_pv = (peak_high + valley_low) / 2.0
        line_625 = valley_low + 0.625 * (peak_high - valley_low)
        if midpoint_pv * 1.1 >= line_625:
            return (
                f"P={peak_high:.2f} V={valley_low:.2f} "
                f"50%×1.1={midpoint_pv * 1.1:.2f} ≥ 62.5%={line_625:.2f}，V资格不成立"
            )
    else:
        valley_low = peak_high / 2.33
        line_625 = valley_low + 0.625 * (peak_high - valley_low)

    # 4. 跌破 62.5% 线？
    has_broken = any(
        _safe_float(rows_asc[i].get("low")) <= line_625
        for i in range(peak_idx, today_idx + 1)
    )
    if not has_broken:
        # 把计算过程全亮出来
        return (
            f"P={peak_high:.2f}（{peak_date}）→ V=P/2.33={valley_low:.2f} "
            f"→ 62.5%线={line_625:.2f}，"
            f"峰后最低价未跌破此线，不触发监控"
        )

    # 5. 最低 L → 半分位
    lowest_low = min(
        (_safe_float(rows_asc[i].get("low")) for i in range(peak_idx, today_idx + 1)),
        default=float("inf"),
    )
    midpoint = (peak_high + lowest_low) / 2.0

    # 6. 触发条件
    yesterday_close = _safe_float(rows_asc[today_idx - 1].get("close"))
    if yesterday_close >= midpoint:
        return (
            f"P={peak_high:.2f} L={lowest_low:.2f} → 半分位={midpoint:.2f}，"
            f"昨收{yesterday_close:.2f} ≥ 半分位，未触发"
        )

    return ""  # 正常触发


def _plot_kline_with_hr(df: pd.DataFrame, hr_points: list[dict],
                         display_tail: int = 200) -> go.Figure | None:
    """K线（蜡烛图）+ 回调一半线叠加（无成交量）。

    Args:
        df: K-line DataFrame (date ASC), needs columns: date,open,high,low,close.
        hr_points: [{date, midpoint, ...}, ...] from _compute_hr_series().
        display_tail: show last N bars on chart.
    """
    if df.empty:
        return None

    for col in ["open", "high", "low", "close"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    plot_df = df.tail(display_tail)

    # Filter hr_points to display range
    min_date = str(plot_df["date"].iloc[0])
    max_date = str(plot_df["date"].iloc[-1])
    hr_in_range = [p for p in hr_points if min_date <= p["date"] <= max_date]

    fig = go.Figure()

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=plot_df["date"], open=plot_df["open"], high=plot_df["high"],
        low=plot_df["low"], close=plot_df["close"], name="K线",
        increasing_line_color="#e53935", decreasing_line_color="#43a047",
    ))

    if hr_in_range:
        hr_dates_raw = [p["date"] for p in hr_in_range]
        hr_vals_raw = [p["midpoint"] for p in hr_in_range]
        peak_vals_raw = [p["peak_high"] for p in hr_in_range]
        low_vals_raw = [p["lowest_low"] for p in hr_in_range]
        trigger_dates = [p["date"] for p in hr_in_range if p["triggered"]]
        trigger_vals = [p["midpoint"] for p in hr_in_range if p["triggered"]]

        # ── 日期断层处插入 None，断开连线 ──
        def _break_gaps(dates, vals, max_gap=4):
            """Insert None at date gaps > max_gap calendar days."""
            if len(dates) < 2:
                return dates, vals
            x, y = [dates[0]], [vals[0]]
            for i in range(1, len(dates)):
                try:
                    d_prev = _dt.datetime.strptime(dates[i-1], "%Y%m%d")
                    d_curr = _dt.datetime.strptime(dates[i], "%Y%m%d")
                    if (d_curr - d_prev).days > max_gap:
                        x.append(None)
                        y.append(None)
                except ValueError:
                    pass
                x.append(dates[i])
                y.append(vals[i])
            return x, y

        hr_dates, hr_vals = _break_gaps(hr_dates_raw, hr_vals_raw)
        _, peak_vals = _break_gaps(hr_dates_raw, peak_vals_raw)
        _, low_vals = _break_gaps(hr_dates_raw, low_vals_raw)

        # 波峰P线
        fig.add_trace(go.Scatter(
            x=hr_dates, y=peak_vals, mode="lines",
            line=dict(color="#e53935", width=1.5, dash="dot"),
            name="波峰P",
            hovertemplate="%{x}<br>波峰P: %{y:.2f}<extra></extra>",
        ))

        # 回调一半线
        fig.add_trace(go.Scatter(
            x=hr_dates, y=hr_vals, mode="lines",
            line=dict(color="#fdd835", width=2.2),
            name="回调一半线",
            hovertemplate="%{x}<br>半分位: %{y:.2f}<extra></extra>",
        ))

        # 最低L线
        fig.add_trace(go.Scatter(
            x=hr_dates, y=low_vals, mode="lines",
            line=dict(color="#2196f3", width=1.2, dash="dot"),
            name="最低L",
            hovertemplate="%{x}<br>最低L: %{y:.2f}<extra></extra>",
        ))

        if trigger_dates:
            fig.add_trace(go.Scatter(
                x=trigger_dates, y=trigger_vals, mode="markers",
                marker=dict(color="#8b5cf6", size=8, symbol="star"),
                name="触发买入日",
                hovertemplate="%{x}<br>触发: %{y:.2f}<extra></extra>",
            ))

    fig.update_layout(
        xaxis_rangeslider_visible=False,
        template="plotly_white", height=480,
        margin=dict(l=20, r=20, t=20, b=20),
        legend=dict(orientation="h", yanchor="top", y=1.10, xanchor="left", x=0),
        hovermode="x unified",
        yaxis_title="价格",
    )

    return fig


# ═══════════════════════════════════════════════════════════════════
# Page UI
# ═══════════════════════════════════════════════════════════════════

pools = svc.load_backtest_pools()

if not pools:
    st.warning("未找到股票池配置，请在 config/backtest_pools.txt 中配置。")
    st.stop()

pool_names = [p.name for p in pools]

col1, col2, col3 = st.columns(3)
with col1:
    selected_pool_name = st.selectbox("股票池", pool_names, key="hr_pool")
with col2:
    variant = st.radio(
        "战法变体",
        ["half_retrace", "half_retrace_simple"],
        format_func=lambda x: {
            "half_retrace": "原版（真实前低V）",
            "half_retrace_simple": "简化版（V=P/2.33）",
        }[x],
        horizontal=True,
        key="hr_variant",
    )
with col3:
    peak_lookback = st.number_input(
        "PEAK_LOOKBACK（交易日）", min_value=60, max_value=500,
        value=300, step=10,
        help="波峰回溯窗口，策略默认126（~6个月）。调大可抓到更早期高点。",
        key="hr_peak_lookback",
    )

selected_pool = next(p for p in pools if p.name == selected_pool_name)

codes = [s.code for s in selected_pool.stocks if s.code]
missing = [s.name for s in selected_pool.stocks if not s.code]

st.caption(f"共 **{len(codes)}** 只有效代码" +
           (f"，**{len(missing)}** 只未解析: {', '.join(missing)}" if missing else ""))

# ── Load data ──
if st.button("📥 加载数据并分析", key="hr_load", type="primary"):
    if not codes:
        st.error("股票池中没有有效代码。")
    else:
        with st.spinner("正在加载K线数据..."):
            try:
                min_entry = min(
                    (s.entry_date for s in selected_pool.stocks if s.entry_date),
                    default="20240101",
                )
                max_exit = svc.get_latest_trade_date()

                actual_buffer = 1500  # ~4年，确保能找到前低V
                buff_dt = _dt.datetime.strptime(min_entry, "%Y%m%d") - _dt.timedelta(
                    days=actual_buffer
                )
                start_date = buff_dt.strftime("%Y%m%d")

                svc._dp.ensure_data_loaded_for_codes(codes, start_date, max_exit)
                st.session_state.hr_data_loaded = True
                st.session_state.hr_codes = codes
                st.session_state.hr_start = start_date
                st.session_state.hr_end = max_exit
                st.success(
                    f"✅ 已加载 {len(codes)} 只股票, "
                    f"缓冲{actual_buffer}日历日, "
                    f"{start_date}~{max_exit}"
                )
            except Exception as e:
                st.error(f"加载失败: {e}")
                import traceback
                st.code(traceback.format_exc())

# ── Compute & display ──
if st.session_state.get("hr_data_loaded"):
    max_exit = st.session_state.hr_end

    buff_dt = _dt.datetime.strptime(st.session_state.hr_start, "%Y%m%d")
    calendar_days = (_dt.datetime.strptime(max_exit, "%Y%m%d") - buff_dt).days
    lookback_days = max(calendar_days, 1500)  # 与 ensure buffer 对齐，确保拿到足够历史数据

    # ── Compute for all stocks ──
    from marketreview.data.data_provider import DataProvider as _DP

    stock_data: dict[str, dict] = {}  # code → {name, df_qfq, hr_series, ...}
    for s in selected_pool.stocks:
        if not s.code:
            continue
        rows = svc._dp.get_daily(s.code, end_date=max_exit,
                                  lookback_days=lookback_days)
        if not rows:
            stock_data[s.code] = {"name": s.name, "error": "无K线数据"}
            continue

        # Build DataFrame, apply 前复权
        df = pd.DataFrame(list(reversed(rows)))  # date ASC
        if not df.empty:
            df = _DP.raw_to_qfq(df)

        # Convert back to list[dict] for _compute_hr_series
        rows_asc = df.to_dict("records") if not df.empty else []
        hr_series = _compute_hr_series(rows_asc, variant, peak_lookback)

        # Latest point + diagnosis
        latest = hr_series[-1] if hr_series else None
        diagnosis = _diagnose_latest(rows_asc, variant, peak_lookback) if rows_asc else "无K线数据"

        stock_data[s.code] = {
            "name": s.name,
            "df_qfq": df,          # 前复权 DataFrame，用于画图
            "hr_series": hr_series,
            "latest": latest,
            "diagnosis": diagnosis,
            "series_len": len(hr_series),
        }

    # ══════════════════════════════════════════════════════
    # Individual K-line + 回调一半线 charts
    # ══════════════════════════════════════════════════════
    st.subheader("📈 个股K线 + 回调一半线")

    for code, sd in stock_data.items():
        name = sd["name"]
        hr_series = sd.get("hr_series", [])
        df_qfq = sd.get("df_qfq")
        latest = sd.get("latest")
        error = sd.get("error", "")

        # Build label
        if error:
            label = f"⚠️ {name} — {error}"
        elif latest and latest["triggered"]:
            label = f"✅ {name} — 触发买入 半分位{latest['midpoint']:.2f}"
        elif latest:
            label = f"🔸 {name} — 半分位{latest['midpoint']:.2f}（未触发）"
        else:
            diag = sd.get("diagnosis", "条件不满足")
            label = f"⚪ {name} — {diag}"

        with st.expander(label):
            if df_qfq is not None and not df_qfq.empty:
                fig = _plot_kline_with_hr(df_qfq, hr_series)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)

                # Key metrics
                if latest:
                    nc1, nc2, nc3, nc4 = st.columns(4)
                    with nc1:
                        st.metric("当前半分位", f"{latest['midpoint']:.2f}")
                    with nc2:
                        st.metric("波峰P", f"{latest['peak_high']:.2f}",
                                 delta=f"{latest['peak_date']}")
                    with nc3:
                        st.metric("最低L", f"{latest['lowest_low']:.2f}")
                    with nc4:
                        days = len(hr_series)
                        trigger_days = sum(1 for p in hr_series if p["triggered"])
                        st.metric("序列天数", f"{days}日",
                                 delta=f"触发{trigger_days}日")
            else:
                st.caption("无K线数据可用")
