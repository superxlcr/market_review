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
        )

        # K-line cache: {code: list[dict]} sorted date ASC
        self._klines: dict[str, list[dict]] = {}

    def run(self) -> Report:
        # 1. Determine date range
        lookback = self.strategy.lookback_trading_days

        all_entry = []
        all_exit = []
        for s in self.pool.stocks:
            if s.entry_date:
                all_entry.append(s.entry_date)
            if s.exit_date and s.exit_date != "now":
                all_exit.append(s.exit_date)

        if not all_entry:
            return Report()

        min_entry = min(all_entry)
        latest_date = self._latest_trade_date()
        max_exit = max(all_exit) if all_exit else latest_date

        # Extend start by lookback calendar days
        start_dt = datetime.strptime(min_entry, "%Y%m%d")
        buffer_dt = start_dt - timedelta(days=int(lookback * 1.6))
        start_date = buffer_dt.strftime("%Y%m%d")
        end_date = max_exit

        # 2. Load data
        codes = [s.code for s in self.pool.stocks if s.code]
        self.dp.ensure_data_loaded_for_codes(codes, start_date, end_date)

        # 3. Load K-lines into memory & precompute MA60
        calendar_days = (datetime.strptime(end_date, "%Y%m%d") - buffer_dt).days
        lookback_days = max(calendar_days, 500)

        for s in self.pool.stocks:
            if not s.code:
                continue
            rows = self.dp.get_daily(s.code, end_date=end_date,
                                     lookback_days=lookback_days)
            if not rows:
                self._klines[s.code] = []
                continue

            # rows come date DESC from DataProvider; convert to ASC DataFrame
            df = rows_to_df(rows)
            if df.empty:
                self._klines[s.code] = []
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

        # 4. Get all trading dates in range
        trade_dates = self._trading_day_range(start_date, end_date)
        if not trade_dates:
            trade_dates = self._generate_calendar_dates(start_date, end_date)

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
                            continue

                    # c) Strategy sell
                    ctx.position = self.broker.positions.get(s.code)
                    sell_sig = self.strategy.check_sell(ctx)
                    if sell_sig:
                        self.broker.sell(date, s.code, sell_sig.price, sell_sig.reason)
                        delayed_stop_symbols.discard(s.code)
                        continue

                    # d) Space stop (intraday)
                    triggered = self.broker.check_space_stop(
                        date, s.code, _safe_f(today_row.get("low"))
                    )
                    if triggered:
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

                # ── Buy check (if not holding + in window) ──
                else:
                    if in_window:
                        ctx.position = None
                        buy_sig = self.strategy.check_buy(ctx)
                        if buy_sig:
                            self.broker.buy(
                                date, s.code, s.name,
                                buy_sig.price, buy_sig.reason,
                            )

            # Record daily equity
            equity_curve.append({
                "date": date,
                "equity": self.broker.equity,
                "return_pct": (self.broker.equity / self.broker.init_capital - 1) * 100.0,
            })

        # 6. Build report
        return build_report(self.broker.trades, equity_curve)

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
