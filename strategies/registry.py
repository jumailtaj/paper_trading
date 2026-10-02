"""Hardcoded strategy registry. This is configuration, not runtime user input.

Add a new strategy by adding one more dict below. The trading engine never changes.
Layout:  STRATEGY TYPE -> STRATEGY FAMILY -> STRATEGY ID -> PARAMETERS
"""
import copy
from typing import Dict, List

from strategies.base import BaseStrategy
from strategies.intraday.ema import EMAStrategy
from strategies.intraday.orb import ORBStrategy

STRATEGIES = {

    "INTRADAY": {

        "EMA": {

            "EMA-01": {
                "strategy_id": "EMA-01", "name": "EMA 9/21 Crossover",
                "family": "EMA", "type": "INTRADAY",
                "fast_ema": 9, "slow_ema": 21,
                "timeframe": "5m", "price_source": "close",
                "confirmation": "crossover",
                "minimum_ema_separation": None,
                "vwap_filter": False,
                "trend_filter": False, "trend_ema": None,
                "rsi_filter": False, "rsi_period": None,
                "adx_filter": False, "adx_period": None,
                "volume_filter": False, "rvol_threshold": None,
                "gap_filter": False,
                "atr_filter": False,
                "stop_method": "fixed_percent", "stop_percent": 0.5,
                "swing_lookback": None, "atr_period": None, "atr_multiplier": None,
                "target_rr": 2.0,
                "trailing_stop": False, "breakeven": False,
                "opposite_crossover_exit": True,
                "entry_window": "09:30-14:30", "forced_exit": "15:15",
            },

            "EMA-02": {
                "strategy_id": "EMA-02", "name": "EMA 9/21 + VWAP",
                "family": "EMA", "type": "INTRADAY",
                "fast_ema": 9, "slow_ema": 21,
                "timeframe": "5m", "price_source": "close",
                "confirmation": "crossover",
                "minimum_ema_separation": None,
                "vwap_filter": True,
                "trend_filter": False, "trend_ema": None,
                "rsi_filter": False, "rsi_period": None,
                "adx_filter": False, "adx_period": None,
                "volume_filter": False, "rvol_threshold": None,
                "gap_filter": False,
                "atr_filter": False,
                "stop_method": "fixed_percent", "stop_percent": 0.5,
                "swing_lookback": None, "atr_period": None, "atr_multiplier": None,
                "target_rr": 2.0,
                "trailing_stop": False, "breakeven": False,
                "opposite_crossover_exit": True,
                "entry_window": "09:30-14:30", "forced_exit": "15:15",
            },

            "EMA-03": {
                "strategy_id": "EMA-03", "name": "EMA 9/21 + RSI",
                "family": "EMA", "type": "INTRADAY",
                "fast_ema": 9, "slow_ema": 21,
                "timeframe": "5m", "price_source": "close",
                "confirmation": "crossover",
                "minimum_ema_separation": None,
                "vwap_filter": False,
                "trend_filter": False, "trend_ema": None,
                "rsi_filter": True, "rsi_period": 14,
                "adx_filter": False, "adx_period": None,
                "volume_filter": False, "rvol_threshold": None,
                "gap_filter": False,
                "atr_filter": False,
                "stop_method": "atr", "stop_percent": None,
                "swing_lookback": None, "atr_period": 14, "atr_multiplier": 1.5,
                "target_rr": 2.0,
                "trailing_stop": False, "breakeven": True,
                "opposite_crossover_exit": True,
                "entry_window": "09:30-14:30", "forced_exit": "15:15",
            },

            "EMA-04": {
                "strategy_id": "EMA-04", "name": "EMA 20/50 + Trend Filter",
                "family": "EMA", "type": "INTRADAY",
                "fast_ema": 20, "slow_ema": 50,
                "timeframe": "5m", "price_source": "close",
                "confirmation": "candle_confirm",
                "minimum_ema_separation": 0.02,
                "vwap_filter": False,
                "trend_filter": True, "trend_ema": 100,
                "rsi_filter": False, "rsi_period": None,
                "adx_filter": False, "adx_period": None,
                "volume_filter": False, "rvol_threshold": None,
                "gap_filter": False,
                "atr_filter": False,
                "stop_method": "swing", "stop_percent": None,
                "swing_lookback": 10, "atr_period": None, "atr_multiplier": None,
                "target_rr": 2.0,
                "trailing_stop": True, "breakeven": False,
                "opposite_crossover_exit": True,
                "entry_window": "09:30-14:30", "forced_exit": "15:15",
            },
        },

        "ORB": {

            "ORB-01": {
                "strategy_id": "ORB-01", "name": "Opening Range Breakout",
                "family": "ORB", "type": "INTRADAY",
                "timeframe": "5m",
                "orb_start": "09:15", "orb_minutes": 15,
                "breakout_buffer_percent": 0.0,
                "allow_short": True,
                "vwap_filter": False,
                "volume_filter": False, "rvol_threshold": None,
                "stop_method": "range_opposite", "stop_percent": None,
                "target_rr": 2.0,
                "trailing_stop": False, "breakeven": False,
                "exit_on_range_reentry": False,
                "entry_window": "09:30-14:00", "forced_exit": "15:15",
            },

            "ORB-02": {
                "strategy_id": "ORB-02", "name": "Opening Range Breakout + Volume",
                "family": "ORB", "type": "INTRADAY",
                "timeframe": "5m",
                "orb_start": "09:15", "orb_minutes": 15,
                "breakout_buffer_percent": 0.05,
                "allow_short": True,
                "vwap_filter": True,
                "volume_filter": True, "rvol_threshold": 1.5,
                "stop_method": "range_opposite", "stop_percent": None,
                "target_rr": 2.0,
                "trailing_stop": False, "breakeven": True,
                "exit_on_range_reentry": True,
                "entry_window": "09:30-14:00", "forced_exit": "15:15",
            },
        },
    },

    "SWING": {
        # Reserved for future. Not implemented in V1.
    },
}

# (type, family) -> strategy class. One class per FAMILY, never per parameter combination.
FAMILY_CLASSES = {
    ("INTRADAY", "EMA"): EMAStrategy,
    ("INTRADAY", "ORB"): ORBStrategy,
}


def list_strategies() -> List[Dict[str, str]]:
    rows = []
    for stype, families in STRATEGIES.items():
        for family, configs in families.items():
            for sid, cfg in configs.items():
                rows.append({"type": stype, "family": family, "strategy_id": sid, "name": cfg["name"]})
    return rows


def get_config(strategy_id: str) -> dict:
    for families in STRATEGIES.values():
        for configs in families.values():
            if strategy_id in configs:
                return copy.deepcopy(configs[strategy_id])
    raise KeyError(f"Unknown strategy id '{strategy_id}'")


def create_strategy(strategy_id: str) -> BaseStrategy:
    cfg = get_config(strategy_id)
    cls = FAMILY_CLASSES.get((cfg["type"], cfg["family"]))
    if cls is None:
        raise KeyError(f"No strategy engine for {cfg['type']}/{cfg['family']}")
    return cls(cfg)


def validate_registry() -> None:
    """Every registry entry must be self-consistent and construct successfully."""
    for stype, families in STRATEGIES.items():
        for family, configs in families.items():
            for sid, cfg in configs.items():
                if cfg["strategy_id"] != sid or cfg["family"] != family or cfg["type"] != stype:
                    raise ValueError(f"Registry entry {sid} does not match its position")
                create_strategy(sid)
