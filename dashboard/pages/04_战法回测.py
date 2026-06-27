"""战法回测 — 多策略对比."""
import streamlit as st
import plotly.graph_objects as go
from services.dashboard_service import DashboardService
from rendering.styles import PAGE_CSS

st.set_page_config(page_title="战法回测", page_icon="🔬", layout="wide")
st.markdown(PAGE_CSS, unsafe_allow_html=True)

svc = DashboardService()

st.title("🔬 战法回测")
st.caption(f"股票池 × 策略日线回测 — 多策略对比 ｜ AI v{DashboardService._AI_VERSION}")

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
    selected_strategy_names = st.multiselect(
        "策略对比（可多选）", strategy_names,
        default=strategy_names, key="bt_strategies",
    )

selected_pool = next(p for p in pools if p.name == selected_pool_name)
selected_strategies = [s for s in strategies if s.name in selected_strategy_names]

if not selected_strategies:
    st.info("请至少选择一个策略。")
    st.stop()

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
    codes = [s.code for s in selected_pool.stocks if s.code]

    if not codes:
        st.error("股票池中没有有效代码。")
    else:
        with st.spinner("正在加载K线数据..."):
            try:
                import datetime as _dt
                from marketreview.backtest.strategy_base import create_strategy

                # Determine date range
                all_dates = [s.entry_date for s in selected_pool.stocks if s.entry_date]
                min_entry = min(all_dates) if all_dates else "20240101"
                max_exit = svc.get_latest_trade_date()

                # Use max lookback across all selected strategies
                lookback = 60
                for sc in selected_strategies:
                    strat = create_strategy(sc.class_name)
                    if strat:
                        lookback = max(lookback, strat.lookback_trading_days)
                actual_buffer = max(365, int(lookback * 2.5))
                buff_dt = _dt.datetime.strptime(min_entry, "%Y%m%d") - _dt.timedelta(days=actual_buffer)
                start_date = buff_dt.strftime("%Y%m%d")

                svc._dp.ensure_data_loaded_for_codes(codes, start_date, max_exit)
                st.session_state.bt_data_loaded = True
                st.session_state.bt_codes = codes
                st.session_state.bt_start = start_date
                st.session_state.bt_end = max_exit
                st.success(
                    f"✅ 已加载 {len(codes)} 只股票, "
                    f"缓冲{actual_buffer}日历日, "
                    f"{start_date}~{max_exit}"
                )
            except Exception as e:
                st.error(f"加载失败: {e}")
                import traceback
                st.code(traceback.format_exc())

# ── Step 3: Run Comparison ──
run_disabled = not st.session_state.get("bt_data_loaded", False)
if st.button("▶ 运行对比", key="bt_run", type="primary", disabled=run_disabled):
    reports = {}
    progress = st.progress(0)
    total = len(selected_strategies)

    for i, strategy_cfg in enumerate(selected_strategies):
        progress.progress((i) / total, f"正在运行: {strategy_cfg.name}...")
        try:
            report = svc.run_backtest(selected_pool, strategy_cfg)
            reports[strategy_cfg.name] = report
        except Exception as e:
            st.error(f"❌ {strategy_cfg.name} 运行失败: {e}")
            import traceback
            st.code(traceback.format_exc())

    progress.progress(1.0, "对比完成")
    st.session_state.bt_reports = reports
    st.session_state.bt_has_reports = True

# ── Step 4: Display Results ──
if st.session_state.get("bt_has_reports"):
    reports = st.session_state.bt_reports
    strategy_names_list = list(reports.keys())

    if not reports:
        st.info("未产生任何回测报告。")
    else:
        # ── 策略对比汇总表 ──
        st.subheader("📊 策略对比汇总")
        import datetime as _dt

        comp_rows = []
        for sname, report in reports.items():
            comp_rows.append({
                "策略": sname,
                "交易笔数": str(report.total_trades),
                "胜率": f"{report.win_rate:.1%}",
                "总收益": f"{report.total_return_pct:+.2f}%",
                "最大回撤": f"{report.max_drawdown_pct:.2f}%",
                "平均持仓": f"{report.avg_hold_days:.1f}天",
                "盈亏比": f"{report.profit_loss_ratio:.2f}",
            })
        st.dataframe(comp_rows, use_container_width=True, hide_index=True)

        # ── 净值曲线叠加图 ──
        st.subheader("📈 净值曲线对比")
        fig = go.Figure()

        # Color palette for strategies
        colors = ["#cf2c2c", "#2c6fcf", "#2c9f4f", "#e68a2e", "#8b5cf6", "#ec4899"]

        # Find common min entry date across pool for x-axis trim
        min_entry = min(
            (s.entry_date for s in selected_pool.stocks if s.entry_date),
            default=None
        )

        for i, sname in enumerate(strategy_names_list):
            report = reports[sname]
            if report.equity_curve:
                if min_entry:
                    curve = [pt for pt in report.equity_curve if pt["date"] >= min_entry]
                else:
                    curve = report.equity_curve

                if curve:
                    dates = [_dt.datetime.strptime(pt["date"], "%Y%m%d") for pt in curve]
                    net_values = [pt["return_pct"] / 100.0 + 1.0 for pt in curve]
                    color = colors[i % len(colors)]
                    fig.add_trace(go.Scatter(
                        x=dates, y=net_values, mode="lines",
                        line=dict(color=color, width=2),
                        name=sname,
                    ))

        # Baseline at 1.0
        fig.add_hline(y=1.0, line_dash="dash", line_color="gray", opacity=0.5)
        fig.update_layout(
            title="净值曲线（多策略叠加）",
            xaxis_title="日期",
            yaxis_title="净值",
            height=450,
            margin=dict(l=40, r=20, t=40, b=40),
            xaxis=dict(tickformat="%Y-%m", dtick="M1"),
        )
        st.plotly_chart(fig, use_container_width=True)

        # ── 各策略明细 ──
        st.subheader("📋 各策略明细")
        for sname in strategy_names_list:
            report = reports[sname]
            if report.total_trades == 0:
                with st.expander(f"🔹 {sname} — 无交易"):
                    st.caption("未产生任何交易。")
                continue

            with st.expander(
                f"🔹 {sname} — {report.total_trades}笔 "
                f"胜率{report.win_rate:.1%} "
                f"收益{report.total_return_pct:+.2f}% "
                f"回撤{report.max_drawdown_pct:.2f}%"
            ):
                # Mini summary
                mc1, mc2, mc3, mc4 = st.columns(4)
                with mc1:
                    st.metric("交易数", report.total_trades,
                              delta=f"赢{report.win_trades}/亏{report.lose_trades}")
                with mc2:
                    st.metric("胜率", f"{report.win_rate:.1%}")
                with mc3:
                    st.metric("总收益", f"{report.total_return_pct:+.2f}%")
                with mc4:
                    st.metric("最大回撤", f"{report.max_drawdown_pct:.2f}%")

                # Trade detail table
                st.markdown("**交易明细**")
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

                # Per-stock summary
                if report.stock_summaries:
                    st.markdown("**股票明细**")
                    for ss in report.stock_summaries:
                        # Skip stocks with zero activity at all
                        if ss.total_trades == 0 and ss.rejected_signals == 0:
                            continue

                        # Build expander label
                        if ss.total_trades > 0:
                            label = (
                                f"{'🟢' if ss.win_rate >= 0.5 else '🔴'} "
                                f"{ss.symbol_name} — {ss.total_trades}笔 "
                                f"胜率{ss.win_rate:.1%} 累计{ss.cumulative_pnl_pct:+.2f}%"
                            )
                            if ss.rejected_signals > 0:
                                label += f"  ⚠️{ss.rejected_signals}次信号未成交"
                        else:
                            label = (
                                f"⚠️ {ss.symbol_name} — "
                                f"0笔成交, {ss.rejected_signals}次信号未成交"
                            )

                        with st.expander(label):
                            # Show all trades (buy/sell/rejected) for this stock
                            stock_trades = [t for t in report.trades if t.symbol == ss.symbol]
                            srows = []
                            for t in stock_trades:
                                pnl_str = f"{t.pnl_pct:+.2f}%" if t.trade_type == "卖出" else ""
                                srows.append({
                                    "日期": t.date,
                                    "类型": t.trade_type,
                                    "价格": f"{t.price:.2f}",
                                    "盈亏": pnl_str,
                                    "原因": t.reason,
                                })
                            st.dataframe(srows, use_container_width=True, hide_index=True)
