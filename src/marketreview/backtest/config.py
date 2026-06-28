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
    name: str                    # display name, e.g. "MA60_突破拉回_3止损"
    class_name: str              # strategy class key, e.g. "ma60_breakthrough"
    position_pct: float          # 0~100, e.g. 20 means 20% per trade
    max_positions: int           # max concurrent positions
    space_stop_pct: float        # 0~100, e.g. 3 means -3% stop loss
    new_position_threshold_pct: float = 0.0  # 现有持仓浮盈达此值才可开新仓
    addon_threshold_pct: float = 999.0        # 浮盈加仓阈值%，999=不启用
    open_chase_cap_pct: float = 102.0        # 开盘追高上限%
    volume_5d_threshold_pct: float = -10.0   # 量能过滤：昨额 vs 5日均量 最低%
    volume_10d_threshold_pct: float = -5.0   # 量能过滤：昨额 vs 10日均量 最低%
    total_capital: float = 2_500_000         # 总仓位资金（用于个股追踪仓位计算）


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

    新格式::

        # 全局默认
        仓位%=20
        开仓上限=2
        空间止损%=5
        开仓浮盈阈值%=10
        加仓阈值%=999

        ---

        # 策略列表（缩进行覆盖对应参数）
        MA60_突破拉回_时间止损 ma60_breakthrough

        MA60_突破拉回_时间止损_加仓 ma60_breakthrough
          加仓阈值%=10
    """
    path = CONFIG_DIR / "backtest_strategies.txt"
    if not path.exists():
        return []

    KEY_MAP = {
        "仓位%": "position_pct",
        "开仓上限": "max_positions",
        "空间止损%": "space_stop_pct",
        "开仓浮盈阈值%": "new_position_threshold_pct",
        "加仓阈值%": "addon_threshold_pct",
        "开盘追高上限%": "open_chase_cap_pct",
        "量能5均阈值%": "volume_5d_threshold_pct",
        "量能10均阈值%": "volume_10d_threshold_pct",
        "总仓位资金": "total_capital",
    }
    FIELD_TYPES = {
        "position_pct": float,
        "max_positions": int,
        "space_stop_pct": float,
        "new_position_threshold_pct": float,
        "addon_threshold_pct": float,
        "open_chase_cap_pct": float,
        "volume_5d_threshold_pct": float,
        "volume_10d_threshold_pct": float,
        "total_capital": float,
    }
    DEFAULTS = {
        "position_pct": 20.0,
        "max_positions": 2,
        "space_stop_pct": 5.0,
        "new_position_threshold_pct": 10.0,
        "addon_threshold_pct": 999.0,
        "open_chase_cap_pct": 102.0,
        "volume_5d_threshold_pct": -10.0,
        "volume_10d_threshold_pct": -5.0,
        "total_capital": 2_500_000,
    }

    global_defaults = dict(DEFAULTS)
    strategies: list[StrategyConfig] = []
    current_strategy: tuple[str, str, dict] | None = None  # (name, class_name, overrides)

    def _commit_current():
        nonlocal current_strategy
        if current_strategy is None:
            return
        name, class_name, overrides = current_strategy
        cfg = dict(global_defaults)
        cfg.update(overrides)
        strategies.append(StrategyConfig(
            name=name, class_name=class_name,
            position_pct=cfg["position_pct"],
            max_positions=cfg["max_positions"],
            space_stop_pct=cfg["space_stop_pct"],
            new_position_threshold_pct=cfg["new_position_threshold_pct"],
            addon_threshold_pct=cfg["addon_threshold_pct"],
            open_chase_cap_pct=cfg["open_chase_cap_pct"],
            volume_5d_threshold_pct=cfg["volume_5d_threshold_pct"],
            volume_10d_threshold_pct=cfg["volume_10d_threshold_pct"],
            total_capital=cfg["total_capital"],
        ))
        current_strategy = None

    def _parse_val(field: str, val: str):
        typ = FIELD_TYPES.get(field, float)
        return typ(val) if typ is int else typ(val)

    section = "global"
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            stripped = raw.strip()

            if not stripped or stripped.startswith("#"):
                continue

            if stripped == "---":
                section = "strategies"
                continue

            if section == "global":
                if "=" in stripped:
                    k, v = stripped.split("=", 1)
                    field = KEY_MAP.get(k.strip())
                    if field:
                        global_defaults[field] = _parse_val(field, v.strip())
                continue

            # section == "strategies"
            if raw.startswith((" ", "\t")):
                # 缩进行 → 当前策略的参数覆盖
                if "=" in stripped and current_strategy is not None:
                    k, v = stripped.split("=", 1)
                    field = KEY_MAP.get(k.strip())
                    if field:
                        current_strategy[2][field] = _parse_val(field, v.strip())
                continue

            # 非缩进行 → 新策略: "策略名 战法类名"
            parts = stripped.split()
            if len(parts) >= 2:
                _commit_current()
                current_strategy = (parts[0], parts[1], {})

        _commit_current()

    return strategies
