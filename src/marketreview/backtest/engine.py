"""Backtest engine — daily loop over stocks, orchestrate buy/sell."""
from datetime import datetime, timedelta
import random
import pandas as pd
from .strategy_base import (
    BaseStrategy, DayContext, create_strategy, Position,
    ConditionalOrder,
)
from .broker import Broker, TradeRecord
from .reporter import Report, build_report
from .config import PoolConfig, StrategyConfig
from marketreview.tools.technical import rows_to_df, calc_ma
from marketreview.data.data_provider import DataProvider
from marketreview.log_util import get_logger

log = get_logger(__name__)


def get_limit_pct(code: str) -> float:
    """根据股票代码返回涨跌停幅度."""
    if code.startswith(("600", "601", "603", "605",
                        "000", "001", "002", "003")):
        return 0.10
    if code.startswith(("300", "301", "688")):
        return 0.20
    if code.startswith("8"):
        return 0.30
    return 0.10


class BacktestEngine:
    """Runs a backtest for one pool × one strategy."""

    def __init__(self, dp, pool: PoolConfig, strategy_cfg: StrategyConfig):
        self.dp = dp
        self.pool = pool
        self.strategy_cfg = strategy_cfg

        # Create strategy instance (import strategies to ensure registration)
        from .strategies import ma_breakthrough, ma60_breakthrough, ma120_breakthrough, ma60_volume, ma120_volume, half_retrace, half_retrace_simple, composite, ma20_breakthrough, ma30_breakthrough, ma60_breakthrough_optimized, ma60_breakthrough_atr  # noqa: F401

        self.strategy = create_strategy(strategy_cfg.class_name)
        if self.strategy is None:
            from .strategy_base import STRATEGY_REGISTRY
            raise ValueError(
                f"Unknown strategy: {strategy_cfg.class_name}. "
                f"Available: {list(STRATEGY_REGISTRY.keys())}"
            )

        # 注入量能阈值配置（仅对成交量限制战法生效）
        if hasattr(self.strategy, 'VOLUME_5D_THRESHOLD_PCT'):
            self.strategy.VOLUME_5D_THRESHOLD_PCT = strategy_cfg.volume_5d_threshold_pct
            self.strategy.VOLUME_10D_THRESHOLD_PCT = strategy_cfg.volume_10d_threshold_pct

        self.broker = Broker(
            position_pct=strategy_cfg.position_pct,
            max_positions=strategy_cfg.max_positions,
            space_stop_pct=strategy_cfg.space_stop_pct,
            new_position_threshold_pct=strategy_cfg.new_position_threshold_pct,
            tp_tier3_mfp=self.strategy.TP_TIER3_MFP_THRESHOLD,
            tp_tier3_protect=self.strategy.TP_TIER3_PROTECT_PCT,
            tp_tier2_mfp=self.strategy.TP_TIER2_MFP_THRESHOLD,
            tp_tier2_protect_ratio=self.strategy.TP_TIER2_PROTECT_PRICE_RATIO,
            strategy_name=strategy_cfg.name,
        )
        self._addon_threshold_pct = strategy_cfg.addon_threshold_pct

        # K-line cache: {code: list[dict]} sorted date ASC
        self._klines: dict[str, list[dict]] = {}

    def run(self, seed: int | None = None) -> Report:
        rng = random.Random(seed) if seed is not None else random

        # 1. Determine date range
        lookback = self.strategy.lookback_trading_days

        all_entry = []
        for s in self.pool.stocks:
            if s.entry_date:
                all_entry.append(s.entry_date)

        if not all_entry:
            log.warning("回测终止: 股票池中没有有效 entry_date")
            return Report()

        min_entry = min(all_entry)
        latest_date = self._latest_trade_date()
        # 始终用最新交易日作为截止日期（"now"的票应到今日，有明确exit_date的票由_in_window过滤）
        end_date = latest_date

        # Extend start by lookback calendar days
        start_dt = datetime.strptime(min_entry, "%Y%m%d")
        buffer_days = max(365, int(lookback * 2.5))
        buffer_dt = start_dt - timedelta(days=buffer_days)
        start_date = buffer_dt.strftime("%Y%m%d")

        log.info(
            "回测开始: 池=%s 策略=%s 日期=%s~%s 缓冲=%d日历日 lookback=%d交易日",
            self.pool.name, self.strategy_cfg.name,
            start_date, end_date, buffer_days, lookback,
        )

        # 2. Load data
        codes = [s.code for s in self.pool.stocks if s.code]
        log.info("加载K线: %d只股票, 范围=%s~%s", len(codes), start_date, end_date)
        self.dp.ensure_data_loaded_for_codes(codes, start_date, end_date)

        # 3. Load K-lines into memory & precompute MA60
        calendar_days = (datetime.strptime(end_date, "%Y%m%d") - buffer_dt).days
        lookback_days = max(calendar_days, 1000)

        loaded_count = 0
        empty_count = 0
        for s in self.pool.stocks:
            if not s.code:
                continue
            rows = self.dp.get_daily(s.code, end_date=end_date,
                                     lookback_days=lookback_days)
            if not rows:
                self._klines[s.code] = []
                empty_count += 1
                log.warning("无K线数据: %s %s", s.code, s.name)
                continue

            # rows come date DESC from DataProvider; convert to ASC DataFrame
            df = rows_to_df(rows)
            if df.empty:
                self._klines[s.code] = []
                empty_count += 1
                log.warning("K线DataFrame为空: %s %s", s.code, s.name)
                continue

            # Convert to 前复权 (QFQ) before any calculations
            df = DataProvider.raw_to_qfq(df)

            # Calculate MAs
            ma_result = calc_ma(df, [20, 30, 55, 60, 120, 144, 240])
            ma20_vals = ma_result.get("MA20", [])
            ma30_vals = ma_result.get("MA30", [])
            ma55_vals = ma_result.get("MA55", [])
            ma60_vals = ma_result.get("MA60", [])
            ma120_vals = ma_result.get("MA120", [])
            ma144_vals = ma_result.get("MA144", [])
            ma240_vals = ma_result.get("MA240", [])

            # Build list of dicts date ASC with all MAs
            klines_asc = []
            for i, (_, row) in enumerate(df.iterrows()):
                d = row.to_dict()
                d["ma20"] = ma20_vals[i] if i < len(ma20_vals) else None
                d["ma30"] = ma30_vals[i] if i < len(ma30_vals) else None
                d["ma55"] = ma55_vals[i] if i < len(ma55_vals) else None
                d["ma60"] = ma60_vals[i] if i < len(ma60_vals) else None
                d["ma120"] = ma120_vals[i] if i < len(ma120_vals) else None
                d["ma144"] = ma144_vals[i] if i < len(ma144_vals) else None
                d["ma240"] = ma240_vals[i] if i < len(ma240_vals) else None
                klines_asc.append(d)
            self._klines[s.code] = klines_asc
            loaded_count += 1
            log.debug("K线加载: %s %s → %d条 (%.10s~%.10s)",
                      s.code, s.name, len(klines_asc),
                      str(klines_asc[0].get("date", "?")),
                      str(klines_asc[-1].get("date", "?")))

        log.info("K线加载完成: %d只有数据, %d只无数据", loaded_count, empty_count)

        # 4. Get all trading dates in range
        trade_dates = self._trading_day_range(start_date, end_date)
        if not trade_dates:
            log.warning("无交易日期, 使用日历日期回退: %s~%s", start_date, end_date)
            trade_dates = self._generate_calendar_dates(start_date, end_date)
        log.info("交易日范围: %d个交易日, %s~%s", len(trade_dates),
                 trade_dates[0] if trade_dates else "?",
                 trade_dates[-1] if trade_dates else "?")

        # 5. Daily loop — 5 步模型
        #  ① 开盘卖出 → ② 开盘买入 → ③ 盘中买入
        #  → ④ 盘中+收盘卖出 → ⑤ 条件单设置
        equity_curve = []

        for date in trade_dates:
            stocks_today = list(self.pool.stocks)

            # 构建今日行情快照
            today_rows = self._build_today_rows(date)

            # ── ① 开盘卖出 ──
            # 先更新 MFP（用于止盈判断）
            for sym in list(self.broker.positions.keys()):
                row = today_rows.get(sym)
                if row:
                    self.broker.update_max_float_profit(sym, _safe_f(row.get("high")))
                    pos = self.broker.positions.get(sym)
                    if pos and pos.addon_shares > 0:
                        self.broker.update_addon_mfp(sym, _safe_f(row.get("high")))
            self.broker.execute_open_sells(date, today_rows)
            self._enrich_positions(date)

            # ── ② 开盘买入 ──
            if self.broker.pending_orders:
                log.info("[%s] ②开盘买入 %s: %d个条件单待触发",
                         self.strategy_cfg.name, date, len(self.broker.pending_orders))
            self.broker.process_open_orders(date, today_rows, rng)
            self._enrich_positions(date)

            # ── ③ 盘中买入 ──
            if self.broker.pending_orders:
                log.info("[%s] ③盘中买入 %s: %d个条件单待触发",
                         self.strategy_cfg.name, date, len(self.broker.pending_orders))
            self.broker.process_intraday_orders(date, today_rows, rng)
            self._enrich_positions(date)

            # ── 浮盈加仓（④之前，因为加仓可能是盘中触发）──
            for sym in list(self.broker.positions.keys()):
                pos = self.broker.positions.get(sym)
                if pos is None or pos.addon_count >= 1:
                    continue
                if self._addon_threshold_pct >= 999:
                    continue
                if pos.max_float_profit_pct < self._addon_threshold_pct:
                    continue
                row = today_rows.get(sym)
                if row is None:
                    continue
                trigger_price = pos.buy_price * (1 + self._addon_threshold_pct / 100.0)
                today_open = _safe_f(row.get("open"))
                today_high = _safe_f(row.get("high"))
                if today_open > trigger_price:
                    entry_price = today_open
                elif today_high >= trigger_price:
                    entry_price = trigger_price
                else:
                    entry_price = 0.0
                if entry_price > 0:
                    addon_shares = pos.shares // 2
                    self.broker.addon_buy(date, sym, entry_price, addon_shares)
                    self._enrich_positions(date)

            # ── ④ 盘中+收盘卖出 ──
            self.broker.execute_intraday_sells(date, today_rows)
            self._enrich_positions(date)

            # 策略卖出（收盘） + 时间止损
            for s in stocks_today:
                if not s.code or s.code not in self.broker.positions:
                    continue
                pos = self.broker.positions.get(s.code)
                # T+1: 今日买入的仓位不可卖出
                if pos and pos.buy_date == date:
                    continue
                ctx = self._build_ctx(date, s,
                    today_rows.get(s.code, {}), self._klines.get(s.code, []),
                    self._in_window(s, date))
                if ctx.position is None:
                    ctx.position = pos
                sell_sig = self.strategy.check_sell(ctx)
                if sell_sig:
                    label = "收盘卖出"
                    self.broker.sell(date, s.code, sell_sig.price,
                        f"{label}，{sell_sig.reason}")
                    self._enrich_positions(date)

            # ── ⑤ 条件单设置 ──
            self.broker.clear_orders()
            for s in stocks_today:
                if not s.code:
                    continue
                if s.code in self.broker.positions:
                    continue
                if not self._in_window(s, date):
                    continue
                klines = self._klines.get(s.code, [])
                today_row = today_rows.get(s.code)
                if today_row is None:
                    continue
                ctx = self._build_ctx(date, s, today_row, klines, True)
                ctx.position = None
                buy_sig = self.strategy.check_buy(ctx)
                if buy_sig is None:
                    # 检查量能过滤
                    vol_filter = getattr(self.strategy, '_last_volume_filter', None)
                    if vol_filter:
                        self.broker.report_volume_filter(
                            vol_filter["date"], vol_filter["symbol"],
                            vol_filter["symbol_name"], vol_filter["price"],
                            vol_filter["reason"],
                        )
                        self.strategy._last_volume_filter = None
                        log.info("[%s] ⑤设单 %s %s 量能过滤: %s",
                                 self.strategy_cfg.name, date, s.name,
                                 vol_filter["reason"])
                    else:
                        log.debug("[%s] ⑤设单 %s %s buy_sig=None O=%.2f H=%.2f L=%.2f C=%.2f MA=%.2f MA_yest=%.2f",
                                  self.strategy_cfg.name, date, s.name,
                                  ctx.open, ctx.high, ctx.low, ctx.close,
                                  ctx.ma60, ctx.ma60_yesterday)
                    continue

                # 判断明天能不能到（涨跌停限制）
                today_close = _safe_f(today_row.get("close"))
                target = buy_sig.price
                limit = get_limit_pct(s.code)
                if today_close * (1 - limit) > target or target > today_close * (1 + limit):
                    log.info("[%s] ⑤设单 %s %s 涨跌停过滤: C=%.2f target=%.2f limit=%.0f%%",
                             self.strategy_cfg.name, date, s.name,
                             today_close, target, limit * 100)
                    continue  # 明天到不了，不设单

                # 设条件单
                open_cap = target * self.strategy_cfg.open_chase_cap_pct / 100.0
                order = ConditionalOrder(
                    date_set=date,
                    symbol=s.code,
                    symbol_name=s.name,
                    target_price=target,
                    open_price_cap=open_cap,
                    reason=buy_sig.reason,
                    stop_price=buy_sig.atr_stop_price,
                )
                self.broker.add_order(order)
                self.broker.trades.append(TradeRecord(
                    date=date, symbol=s.code, symbol_name=s.name,
                    trade_type="设置条件单", price=target,
                    reason=f"目标价={target:.2f} 开盘上限≤{open_cap:.2f} {buy_sig.reason}",
                ))
                log.info("[%s] ⑤设单 %s %s 信号→条件单 target=%.2f cap=%.2f (%s)",
                         self.strategy_cfg.name, date, s.name,
                         target, open_cap, buy_sig.reason)

            # ── 日终权益快照 ──
            pos_prices_daily = {}
            for pcode in self.broker.positions:
                prow = today_rows.get(pcode)
                if prow:
                    pos_prices_daily[pcode] = _safe_f(prow.get("close"))
            market_eq = self.broker.get_market_equity(pos_prices_daily)
            equity_curve.append({
                "date": date,
                "equity": market_eq,
                "return_pct": (market_eq / self.broker.init_capital - 1) * 100.0,
            })

        # 5.5 回测结束 — 强制清仓所有持仓
        if self.broker.positions:
            last_date = trade_dates[-1] if trade_dates else end_date
            for pcode in list(self.broker.positions.keys()):
                prow = self._get_day(self._klines.get(pcode, []), last_date)
                close_price = _safe_f(prow.get("close")) if prow else 0.0
                if close_price > 0:
                    self.broker.sell(last_date, pcode, close_price, "回测结束(清仓)")
                    self._enrich_positions(last_date)
                    log.info("清仓: %s @ %.2f on %s", pcode, close_price, last_date)
                else:
                    log.warning("无法清仓 %s: 最后交易日无数据", pcode)
            # Update last equity point with realized cash
            if equity_curve:
                equity_curve[-1] = {
                    "date": equity_curve[-1]["date"],
                    "equity": self.broker.equity,
                    "return_pct": (self.broker.equity / self.broker.init_capital - 1) * 100.0,
                }

        # 6. Build report
        report = build_report(self.broker.trades, equity_curve)
        log.info(
            "回测完成: 总交易=%d笔 赢=%d 亏=%d 胜率=%.1f%% 总收益=%+.2f%% 最大回撤=%.2f%%",
            report.total_trades, report.win_trades, report.lose_trades,
            report.win_rate * 100, report.total_return_pct, report.max_drawdown_pct,
        )
        return report

    def _enrich_positions(self, date: str):
        """Build current price snapshot and attach to last trade record."""
        pos_prices = {}
        for pcode in self.broker.positions:
            prow = self._get_day(self._klines.get(pcode, []), date)
            if prow:
                pos_prices[pcode] = _safe_f(prow.get("close"))
        self.broker.enrich_last_trade(pos_prices)

    def _build_ctx(self, date, stock_entry, today_row, klines, in_window) -> DayContext:
        """Build DayContext for a given stock on a given date."""
        # Find today's index in klines
        idx = None
        for i, r in enumerate(klines):
            rd = r.get("date", "")
            if isinstance(rd, pd.Timestamp):
                rd = rd.strftime("%Y%m%d")
            if rd == date:
                idx = i
                break

        yesterday_ma20 = 0.0
        yesterday_ma30 = 0.0
        yesterday_ma55 = 0.0
        yesterday_ma60 = 0.0
        yesterday_ma120 = 0.0
        yesterday_ma144 = 0.0
        yesterday_ma240 = 0.0
        if idx is not None and idx >= 1:
            yesterday = klines[idx - 1]
            yesterday_ma20 = _safe_f(yesterday.get("ma20"))
            yesterday_ma30 = _safe_f(yesterday.get("ma30"))
            yesterday_ma55 = _safe_f(yesterday.get("ma55"))
            yesterday_ma60 = _safe_f(yesterday.get("ma60"))
            yesterday_ma120 = _safe_f(yesterday.get("ma120"))
            yesterday_ma144 = _safe_f(yesterday.get("ma144"))
            yesterday_ma240 = _safe_f(yesterday.get("ma240"))

        if idx is not None:
            hist = klines[:idx + 1]
        else:
            hist = klines

        return DayContext(
            date=date,
            symbol=stock_entry.code,
            symbol_name=stock_entry.name,
            open=_safe_f(today_row.get("open")),
            high=_safe_f(today_row.get("high")),
            low=_safe_f(today_row.get("low")),
            close=_safe_f(today_row.get("close")),
            volume=_safe_f(today_row.get("vol")),
            amount=_safe_f(today_row.get("amount")),
            ma20=_safe_f(today_row.get("ma20")),
            ma20_yesterday=yesterday_ma20,
            ma30=_safe_f(today_row.get("ma30")),
            ma30_yesterday=yesterday_ma30,
            ma60=_safe_f(today_row.get("ma60")),
            ma60_yesterday=yesterday_ma60,
            ma120=_safe_f(today_row.get("ma120")),
            ma120_yesterday=yesterday_ma120,
            ma240=_safe_f(today_row.get("ma240")),
            ma240_yesterday=yesterday_ma240,
            ma55=_safe_f(today_row.get("ma55")),
            ma55_yesterday=yesterday_ma55,
            ma144=_safe_f(today_row.get("ma144")),
            ma144_yesterday=yesterday_ma144,
            kline_history=hist,
            in_pool_window=in_window,
        )

    def _in_window(self, stock_entry, date: str) -> bool:
        """Check if date is within stock's discovery window."""
        if stock_entry.entry_date and date < stock_entry.entry_date:
            return False
        if stock_entry.exit_date and stock_entry.exit_date != "now":
            if date > stock_entry.exit_date:
                return False
        return True

    def _latest_trade_date(self) -> str:
        """Get latest trading day from cache."""
        try:
            return self.dp.get_latest_trade_date() or datetime.now().strftime("%Y%m%d")
        except Exception:
            return datetime.now().strftime("%Y%m%d")

    def _trading_day_range(self, start: str, end: str) -> list[str]:
        """Return all available trading dates between start and end."""
        return self.dp.cache.get_daily_dates_in_range(start, end)

    def _generate_calendar_dates(self, start: str, end: str) -> list[str]:
        """Fallback: generate all calendar dates in range."""
        dt = datetime.strptime(start, "%Y%m%d")
        end_dt = datetime.strptime(end, "%Y%m%d")
        dates = []
        while dt <= end_dt:
            dates.append(dt.strftime("%Y%m%d"))
            dt += timedelta(days=1)
        return dates

    def _build_today_rows(self, date: str) -> dict[str, dict]:
        """构建 {symbol: kline_row} 字典，供 broker 方法使用."""
        result: dict[str, dict] = {}
        for code, klines in self._klines.items():
            row = self._get_day(klines, date)
            if row is not None:
                result[code] = row
        return result

    def _get_day(self, klines: list[dict], date: str) -> dict | None:
        """Find a K-line row by date."""
        for r in klines:
            rd = r.get("date", "")
            if isinstance(rd, pd.Timestamp):
                rd = rd.strftime("%Y%m%d")
            if rd == date:
                return r
        return None


def _safe_f(v) -> float:
    """Safely convert a value to float."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        if isinstance(v, pd.Timestamp):
            return 0.0
        return 0.0
