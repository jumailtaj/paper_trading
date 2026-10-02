"""Shared strategy contract: Signal, MarketSnapshot and BaseStrategy.

A strategy answers ONE question: BUY, SELL or NO_SIGNAL?
It never places orders, touches cash/positions, checks trade limits, or computes charges.
"""
from dataclasses import dataclass
from datetime import datetime, time
from types import MappingProxyType
from typing import Optional

import pandas as pd

from clock import parse_hhmm, parse_window
from config import TIMEFRAME_MINUTES, round_to_tick

BUY = "BUY"
SELL = "SELL"
NO_SIGNAL = "NO_SIGNAL"


@dataclass
class Signal:
    strategy_id: str
    symbol: str
    side: str = NO_SIGNAL
    price: float = 0.0
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    trailing_stop: bool = False
    breakeven: bool = False
    reason: str = ""
    timestamp: Optional[datetime] = None

    @property
    def is_actionable(self) -> bool:
        return self.side in (BUY, SELL)


@dataclass
class MarketSnapshot:
    """What a strategy sees. `candles` holds CLOSED candles only."""
    symbol: str
    candles: pd.DataFrame
    ltp: Optional[float]
    timestamp: datetime
    prev_close: Optional[float] = None
    day_open: Optional[float] = None


def risk_levels(side: str, price: float, stop_price: float, target_rr: Optional[float]):
    """Return (stop, target) rounded to tick size. target is None when target_rr is None."""
    risk = abs(price - stop_price)
    target = None
    if target_rr:
        target = price + target_rr * risk if side == BUY else price - target_rr * risk
        target = round_to_tick(target)
    return round_to_tick(stop_price), target


class BaseStrategy:
    REQUIRED_KEYS: tuple = ("strategy_id", "name", "family", "type", "timeframe",
                            "entry_window", "forced_exit")

    def __init__(self, params):
        missing = [k for k in self.REQUIRED_KEYS if k not in params]
        if missing:
            raise ValueError(f"Strategy config missing keys: {missing}")
        self.params = MappingProxyType(dict(params))  # read-only while running
        if self.params["timeframe"] not in TIMEFRAME_MINUTES:
            raise ValueError(f"Unsupported timeframe '{self.params['timeframe']}'")
        self._window = parse_window(self.params["entry_window"])
        self.forced_exit_time: time = parse_hhmm(self.params["forced_exit"])
        self._validate()

    # -- to be provided by subclasses
    def _validate(self) -> None:
        pass

    def min_candles(self) -> int:
        raise NotImplementedError

    def generate_signal(self, data: MarketSnapshot) -> Signal:
        raise NotImplementedError

    def should_exit(self, data: MarketSnapshot, position_side: str) -> Optional[str]:
        """Strategy-defined exit. Return an exit reason string, or None to hold."""
        return None

    # -- shared helpers
    @property
    def strategy_id(self) -> str:
        return self.params["strategy_id"]

    @property
    def name(self) -> str:
        return self.params["name"]

    @property
    def timeframe(self) -> str:
        return self.params["timeframe"]

    @property
    def strategy_type(self) -> str:
        return self.params["type"]

    def in_entry_window(self, ts: datetime) -> bool:
        return self._window[0] <= ts.time() <= self._window[1]

    @staticmethod
    def candles_are_current(data: MarketSnapshot) -> bool:
        """Guard against evaluating yesterday's candles as if they were today's."""
        return len(data.candles) > 0 and data.candles.index[-1].date() == data.timestamp.date()

    def no_signal(self, data: MarketSnapshot, reason: str) -> Signal:
        return Signal(self.strategy_id, data.symbol, NO_SIGNAL, reason=reason, timestamp=data.timestamp)

    @staticmethod
    def entry_price(data: MarketSnapshot) -> float:
        if data.ltp and data.ltp > 0:
            return float(data.ltp)
        return float(data.candles["close"].iloc[-1])
