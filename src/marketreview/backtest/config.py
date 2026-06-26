"""Parse backtest pool & strategy configuration files."""
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"


@dataclass
class StockEntry:
    """A single stock in a pool with its discovery window."""
    name: str          # user-facing name, e.g. "顺络电子"
    code: str = ""     # resolved ts_code, e.g. "002138.SZ"
    entry_date: str = ""    # YYYYMMDD
    exit_date: str = ""     # YYYYMMDD or "now"


@dataclass
class PoolConfig:
    """A named stock pool."""
    name: str
    stocks: list[StockEntry] = field(default_factory=list)


@dataclass
class StrategyConfig:
    """A named strategy configuration."""
    name: str             # display name, e.g. "MA60_突破拉回_3止损"
    class_name: str       # strategy class key, e.g. "ma60_breakthrough"
    position_pct: float   # 0~100, e.g. 20 means 20% per trade
    max_positions: int    # max concurrent positions
    space_stop_pct: float # 0~100, e.g. 3 means -3% stop loss


def load_pools(dp) -> list[PoolConfig]:
    """Parse backtest_pools.txt, resolve stock names to ts_code via dp."""
    path = CONFIG_DIR / "backtest_pools.txt"
    if not path.exists():
        return []

    pools: list[PoolConfig] = []
    current_pool: PoolConfig | None = None

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                name = line[1:-1]
                current_pool = PoolConfig(name=name)
                pools.append(current_pool)
                continue
            if current_pool is not None:
                parts = line.split()
                if len(parts) >= 2:
                    name = parts[0]
                    entry_date = parts[1]
                    exit_date = parts[2] if len(parts) > 2 else "now"
                    code = _resolve_stock_name(dp, name)
                    current_pool.stocks.append(
                        StockEntry(name=name, code=code,
                                   entry_date=entry_date, exit_date=exit_date)
                    )
    return pools


def _resolve_stock_name(dp, name: str) -> str:
    """Resolve a Chinese stock name to ts_code via stock_basic_cache."""
    rows = dp.cache.get_stock_basic()
    for r in rows:
        if r.get("name") == name:
            return r.get("ts_code", "")
    # fallback: if name already looks like a code (e.g. "000001.SZ"), use as-is
    if "." in name and len(name) == 9:
        return name
    return ""  # unresolved — caller should check and report


def load_strategies() -> list[StrategyConfig]:
    """Parse backtest_strategies.txt.
    Format: 策略名 战法类名 仓位% 开仓上限 空间止损%
    """
    path = CONFIG_DIR / "backtest_strategies.txt"
    if not path.exists():
        return []

    strategies: list[StrategyConfig] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 5:
                strategies.append(StrategyConfig(
                    name=parts[0],
                    class_name=parts[1],
                    position_pct=float(parts[2]),
                    max_positions=int(parts[3]),
                    space_stop_pct=float(parts[4]),
                ))
    return strategies
