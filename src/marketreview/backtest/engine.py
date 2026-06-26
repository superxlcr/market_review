"""Backtest engine — daily loop over stocks, orchestrate buy/sell."""
from datetime import datetime, timedelta
import pandas as pd
from .strategy_base import (
    BaseStrategy, DayContext, create_strategy, Position,
)
from .broker import Broker
from .reporter import Report, build_report
from .config import PoolConfig, StrategyConfig
from marketreview.tools.technical import rows_to_df, calc_ma
from marketreview.log_util import get_logger

log = get_logger(__name__)


class BacktestEngine:
    """Runs a backtest for one pool × one strategy."""

    def __init__(self, dp, pool: PoolConfig, strategy_cfg: StrategyConfig):
        self.dp = dp
        self.pool = pool
        self.strategy_cfg = strategy_cfg

        # Create strategy instance (import strategies to ensure registration)
        from .strategies import ma60_breakthrough, ma60_pullback_only  # noqa: F401

        self.strategy = create_strategy(strategy_cfg.class_name)
        if self.strategy is None:
            from .strategy_base import STRATEGY_REGISTRY
            raise ValueError(
                f"Unknown strategy: {strategy_cfg.class_name}. "
                f"Available: {list(STRATEGY_REGISTRY.keys())}"
            )

        self.broker = Broker(
            position_pct=strategy_cfg.position_pct,
            max_positions=strategy_cfg.max_positions,
            space_stop_pct=strategy_cfg.space_stop_pct,
            new_position_threshold_pct=strategy_cfg.new_position_threshold_pct,
        )

        # K-line cache: {code: list[dict]} sorted date ASC
        self._klines: dict[str, list[dict]] = {}

    def run(self) -> Report:
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
        lookback_days = max(calendar_days, 500)

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

            # Calculate MA60
            ma_result = calc_ma(df, [60])
            ma60_vals = ma_result.get("MA60", [])

            # Build list of dicts date ASC with MA60
            klines_asc = []
            for i, (_, row) in enumerate(df.iterrows()):
                d = row.to_dict()
                d["ma60"] = ma60_vals[i] if i < len(ma60_vals) else None
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

        # 5. Daily loop
        equity_curve = []
        delayed_stop_symbols: set[str] = set()

        for date in trade_dates:
            for s in self.pool.stocks:
                if not s.code:
                    continue
                klines = self._klines.get(s.code, [])
                today_row = self._get_day(klines, date)
                if today_row is None:
                    continue

                in_window = self._in_window(s, date)

                # Build context
                ctx = self._build_ctx(date, s, today_row, klines, in_window)

                # ── Sell checks (if holding) ──
                if s.code in self.broker.positions:
                    # a) Update max float profit
                    self.broker.update_max_float_profit(
                        s.code, _safe_f(today_row.get("high"))
                    )

                    # b) Delayed stop from yesterday
                    if s.code in delayed_stop_symbols:
                        triggered = self.broker.check_delayed_stop(
                            date, s.code, _safe_f(today_row.get("open"))
                        )
                        if triggered:
                            delayed_stop_symbols.discard(s.code)
                            self._enrich_positions(date)
                            continue

                    # c) Space stop (intraday) — 盘中优先
                    triggered = self.broker.check_space_stop(
                        date, s.code, _safe_f(today_row.get("low"))
                    )
                    if triggered:
                        self._enrich_positions(date)
                        delayed_stop_symbols.discard(s.code)
                    else:
                        # Flag for next-open stop if stop price not reached intraday
                        pos = self.broker.positions.get(s.code)
                        if pos:
                            stop_price = pos.buy_price * (
                                1 - self.broker.space_stop_pct / 100.0
                            )
                            today_low = _safe_f(today_row.get("low"))
                            if stop_price > today_low and stop_price > 0:
                                delayed_stop_symbols.add(s.code)

                    # d) Strategy sell (MA60止损 / 跌破MA60 / 止盈)
                    ctx.position = self.broker.positions.get(s.code)
                    sell_sig = self.strategy.check_sell(ctx)
                    if sell_sig:
                        self.broker.sell(date, s.code, sell_sig.price, sell_sig.reason)
                        self._enrich_positions(date)
                        delayed_stop_symbols.discard(s.code)
                        continue

                # ── Buy check (if not holding + in window) ──
                else:
                    if in_window:
                        ctx.position = None
                        buy_sig = self.strategy.check_buy(ctx)
                        if buy_sig:
                            # Build current prices for rejection detail + enrich
                            pos_prices = {}
                            for pcode in self.broker.positions:
                                prow = self._get_day(
                                    self._klines.get(pcode, []), date
                                )
                                if prow:
                                    pos_prices[pcode] = _safe_f(prow.get("close"))
                            self.broker.buy(
                                date, s.code, s.name,
                                buy_sig.price, buy_sig.reason,
                                position_prices=pos_prices,
                            )
                            self._enrich_positions(date)

            # Record daily equity
            equity_curve.append({
                "date": date,
                "equity": self.broker.equity,
                "return_pct": (self.broker.equity / self.broker.init_capital - 1) * 100.0,
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

        yesterday_ma60 = 0.0
        if idx is not None and idx >= 1:
            yesterday = klines[idx - 1]
            yesterday_ma60 = _safe_f(yesterday.get("ma60"))

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
            ma60=_safe_f(today_row.get("ma60")),
            ma60_yesterday=yesterday_ma60,
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
