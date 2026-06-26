"""战法回测 — 股票池 × 策略日线回测."""
import streamlit as st
import plotly.graph_objects as go
from services.dashboard_service import DashboardService
from rendering.styles import PAGE_CSS

st.set_page_config(page_title="战法回测", page_icon="🔬", layout="wide")
st.markdown(PAGE_CSS, unsafe_allow_html=True)

svc = DashboardService()

st.title("🔬 战法回测")
st.caption(f"股票池 × 策略日线回测 ｜ AI v{DashboardService._AI_VERSION}")

# ── Step 1: Load configs ──
pools = svc.load_backtest_pools()
strategies = svc.load_backtest_strategies()

if not pools:
    st.warning("未找到股票池配置，请在 config/backtest_pools.txt 中配置。")
    st.stop()

if not strategies:
    st.warning("未找到策略配置，请在 config/backtest_strategies.txt 中配置。")
    st.stop()

pool_names = [p.name for p in pools]
strategy_names = [s.name for s in strategies]

col1, col2 = st.columns(2)
with col1:
    selected_pool_name = st.selectbox("股票池", pool_names, key="bt_pool")
with col2:
    selected_strategy_name = st.selectbox("策略", strategy_names, key="bt_strategy")

selected_pool = next(p for p in pools if p.name == selected_pool_name)

# ── Expander: 股票池详情 ──
with st.expander("📋 股票池详情", expanded=False):
    latest_td = svc.get_latest_trade_date()
    for s in selected_pool.stocks:
        if s.code:
            exit_display = s.exit_date if s.exit_date != "now" else f"至今({latest_td})"
            st.markdown(f"✅ **{s.name}** → `{s.code}`  {s.entry_date} ~ {exit_display}")
        else:
            st.markdown(f"❌ **{s.name}** → 未找到代码")

# ── Step 2: Load Data ──
if st.button("📥 加载数据", key="bt_load", type="primary"):
    selected_strategy_cfg = next(s for s in strategies if s.name == selected_strategy_name)
    codes = [s.code for s in selected_pool.stocks if s.code]

    if not codes:
        st.error("股票池中没有有效代码。")
    else:
        with st.spinner("正在加载K线数据..."):
            try:
                import datetime as _dt
                from marketreview.backtest.strategy_base import (
                    STRATEGY_REGISTRY, create_strategy,
                )

                # Determine date range
                all_dates = [s.entry_date for s in selected_pool.stocks if s.entry_date]
                min_entry = min(all_dates) if all_dates else "20240101"
                max_exit = svc.get_latest_trade_date()

                # lookback buffer
                strat = create_strategy(selected_strategy_cfg.class_name)
                lookback = strat.lookback_trading_days if strat else 60
                buff_dt = _dt.datetime.strptime(min_entry, "%Y%m%d") - _dt.timedelta(
                    days=max(365, int(lookback * 2.5))
                )
                start_date = buff_dt.strftime("%Y%m%d")

                svc._dp.ensure_data_loaded_for_codes(codes, start_date, max_exit)
                st.session_state.bt_data_loaded = True
                st.session_state.bt_codes = codes
                st.session_state.bt_start = start_date
                st.session_state.bt_end = max_exit
                actual_buffer = max(365, int(lookback * 2.5))
                st.success(
                    f"✅ 已加载 {len(codes)} 只股票, "
                    f"缓冲{actual_buffer}日历日, "
                    f"{start_date}~{max_exit}"
                )
            except Exception as e:
                st.error(f"加载失败: {e}")
                import traceback
                st.code(traceback.format_exc())

# ── Step 3: Run Backtest ──
run_disabled = not st.session_state.get("bt_data_loaded", False)
if st.button("▶ 运行回测", key="bt_run", type="primary", disabled=run_disabled):
    with st.spinner("回测运行中..."):
        try:
            selected_strategy_cfg = next(
                s for s in strategies if s.name == selected_strategy_name
            )
            report = svc.run_backtest(selected_pool, selected_strategy_cfg)
            st.session_state.bt_report = report
            st.session_state.bt_has_report = True
        except Exception as e:
            st.error(f"回测运行失败: {e}")
            import traceback
            st.code(traceback.format_exc())

# ── Step 4: Display Results ──
if st.session_state.get("bt_has_report"):
    report = st.session_state.bt_report
    if report.total_trades == 0:
        st.info("未产生任何交易。")
    else:
        # Summary cards
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric(
                "总交易笔数", report.total_trades,
                delta=f"赢{report.win_trades} / 亏{report.lose_trades}",
            )
        with c2:
            st.metric("胜率", f"{report.win_rate:.1%}")
        with c3:
            st.metric("总收益率", f"{report.total_return_pct:+.2f}%")

        c4, c5, c6 = st.columns(3)
        with c4:
            st.metric("最大回撤", f"{report.max_drawdown_pct:.2f}%")
        with c5:
            st.metric("平均持仓天", f"{report.avg_hold_days:.1f}天")
        with c6:
            st.metric("盈亏比", f"{report.profit_loss_ratio:.2f}:1")

        # Equity curve — net value, filtered from min entry date
        if report.equity_curve:
            import datetime as _dt
            # Find min entry date to trim flat buffer period
            min_entry = min(
                (s.entry_date for s in selected_pool.stocks if s.entry_date),
                default=None
            )
            if min_entry:
                curve = [pt for pt in report.equity_curve if pt["date"] >= min_entry]
            else:
                curve = report.equity_curve

            if curve:
                dates = [_dt.datetime.strptime(pt["date"], "%Y%m%d") for pt in curve]
                net_values = [pt["return_pct"] / 100.0 + 1.0 for pt in curve]
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=dates, y=net_values, mode="lines",
                    line=dict(color="#cf2c2c", width=2),
                    name="净值",
                ))
                # Add baseline at 1.0
                fig.add_hline(y=1.0, line_dash="dash", line_color="gray", opacity=0.5)
                fig.update_layout(
                    title="净值曲线",
                    xaxis_title="日期",
                    yaxis_title="净值",
                    height=400,
                    margin=dict(l=40, r=20, t=40, b=40),
                    xaxis=dict(tickformat="%Y-%m", dtick="M1"),
                )
                st.plotly_chart(fig, use_container_width=True)

        # ── Trade detail table ──
        st.subheader("交易明细")
        if report.trades:
            trade_rows = []
            for t in sorted(report.trades, key=lambda x: x.date):
                pnl_str = f"{t.pnl_pct:+.2f}%" if t.trade_type == "卖出" else ""
                trade_rows.append({
                    "日期": t.date,
                    "股票": t.symbol_name,
                    "类型": t.trade_type,
                    "价格": f"{t.price:.2f}",
                    "盈亏": pnl_str,
                    "原因": t.reason,
                    "当前持仓": t.positions_after,
                })
            st.dataframe(
                trade_rows, use_container_width=True, hide_index=True,
                column_config={
                    "日期": st.column_config.TextColumn(width="small"),
                    "股票": st.column_config.TextColumn(width="small"),
                    "类型": st.column_config.TextColumn(width="small"),
                    "价格": st.column_config.TextColumn(width="small"),
                    "盈亏": st.column_config.TextColumn(width="small"),
                    "原因": st.column_config.TextColumn(width="large"),
                    "当前持仓": st.column_config.TextColumn(width="large"),
                },
            )

        # Per-stock summary + trade detail
        st.subheader("股票明细")
        for ss in report.stock_summaries:
            with st.expander(
                f"{ss.symbol_name} — {ss.total_trades}笔 "
                f"胜率{ss.win_rate:.1%} 累计{ss.cumulative_pnl_pct:+.2f}%"
            ):
                stock_trades = [t for t in report.trades if t.symbol == ss.symbol]
                rows_data = []
                for t in stock_trades:
                    pnl_str = f"{t.pnl_pct:+.2f}%" if t.trade_type == "卖出" else ""
                    rows_data.append({
                        "日期": t.date,
                        "类型": t.trade_type,
                        "价格": f"{t.price:.2f}",
                        "盈亏": pnl_str,
                        "原因": t.reason,
                    })
                st.dataframe(rows_data, use_container_width=True, hide_index=True)
