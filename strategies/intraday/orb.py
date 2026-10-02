"""ORB (Opening Range Breakout) strategy family. Own parameter schema, independent of EMA."""
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pandas as pd

from clock import parse_hhmm
from config import TIMEFRAME_MINUTES
from strategies.base import BUY, SELL, BaseStrategy, MarketSnapshot, Signal, risk_levels
from strategies.indicators import relative_volume, session_vwap, todays_candles

STOP_METHODS = ("range_opposite", "fixed_percent")
RVOL_LOOKBACK = 20


class ORBStrategy(BaseStrategy):
    REQUIRED_KEYS = BaseStrategy.REQUIRED_KEYS + (
        "orb_start", "orb_minutes", "breakout_buffer_percent", "allow_short", "stop_method",
        "target_rr", "exit_on_range_reentry",
    )

    def _validate(self) -> None:
        p = self.params
        tf = TIMEFRAME_MINUTES[p["timeframe"]]
        if p["orb_minutes"] <= 0 or p["orb_minutes"] % tf != 0:
            raise ValueError("orb_minutes must be a positive multiple of the timeframe")
        if p["stop_method"] not in STOP_METHODS:
            raise ValueError(f"stop_method must be one of {STOP_METHODS}")
        if p["stop_method"] == "fixed_percent" and not p.get("stop_percent"):
            raise ValueError("stop_method 'fixed_percent' needs 'stop_percent'")
        if p.get("volume_filter") and not p.get("rvol_threshold"):
            raise ValueError("volume_filter is enabled but 'rvol_threshold' is not set")
        if p["target_rr"] is not None and p["target_rr"] <= 0:
            raise ValueError("target_rr must be positive or None")
        self._tf = tf
        self._range_start = parse_hhmm(p["orb_start"])

    def min_candles(self) -> int:
        return self.params["orb_minutes"] // self._tf + 1

    def _range_end(self, day: datetime) -> datetime:
        start = datetime.combine(day.date(), self._range_start)
        return start + timedelta(minutes=self.params["orb_minutes"])

    def opening_range(self, candles: pd.DataFrame) -> Optional[Tuple[float, float, datetime]]:
        """(high, low, range_end) of today's opening range, or None if it is not complete yet."""
        today = todays_candles(candles)
        start = datetime.combine(today.index[-1].date(), self._range_start)
        end = self._range_end(today.index[-1])
        in_range = today[(today.index >= start) & (today.index < end)]
        if len(in_range) < self.params["orb_minutes"] // self._tf:
            return None
        if today.index[-1] < end:  # still inside the range window
            return None
        return float(in_range["high"].max()), float(in_range["low"].min()), end

    def generate_signal(self, data: MarketSnapshot) -> Signal:
        p, c = self.params, data.candles
        if not self.candles_are_current(data):
            return self.no_signal(data, "Candles are not from today")
        if len(c) < self.min_candles():
            return self.no_signal(data, "Not enough candles yet")
        if not self.in_entry_window(data.timestamp):
            return self.no_signal(data, "Outside entry window")
        rng = self.opening_range(c)
        if rng is None:
            return self.no_signal(data, "Opening range not complete")
        high, low, _ = rng
        buf = p["breakout_buffer_percent"] / 100
        up_level, down_level = high * (1 + buf), low * (1 - buf)
        close, prev_close = float(c["close"].iloc[-1]), float(c["close"].iloc[-2])

        if close > up_level and prev_close <= up_level:
            side = BUY
        elif p["allow_short"] and close < down_level and prev_close >= down_level:
            side = SELL
        else:
            return self.no_signal(data, "No breakout")

        if p.get("vwap_filter"):
            vwap = session_vwap(c)
            if vwap is None:
                return self.no_signal(data, "VWAP unavailable")
            if (side == BUY and close <= vwap) or (side == SELL and close >= vwap):
                return self.no_signal(data, "VWAP filter failed")
        if p.get("volume_filter"):
            rvol = relative_volume(c, RVOL_LOOKBACK)
            if rvol is None or rvol < p["rvol_threshold"]:
                return self.no_signal(data, "Volume filter failed")

        price = self.entry_price(data)
        if p["stop_method"] == "range_opposite":
            stop = low if side == BUY else high
        else:
            dist = price * p["stop_percent"] / 100
            stop = price - dist if side == BUY else price + dist
        stop, target = risk_levels(side, price, stop, p["target_rr"])
        return Signal(self.strategy_id, data.symbol, side, price=price, stop_loss=stop, target=target,
                      trailing_stop=bool(p.get("trailing_stop")), breakeven=bool(p.get("breakeven")),
                      reason=f"ORB {p['orb_minutes']}m breakout", timestamp=data.timestamp)

    def should_exit(self, data: MarketSnapshot, position_side: str) -> Optional[str]:
        if not self.params["exit_on_range_reentry"] or not self.candles_are_current(data):
            return None
        if len(data.candles) < self.min_candles():
            return None
        rng = self.opening_range(data.candles)
        if rng is None:
            return None
        high, low, _ = rng
        close = float(data.candles["close"].iloc[-1])
        if position_side == BUY and close < high:
            return "RANGE_REENTRY"
        if position_side == SELL and close > low:
            return "RANGE_REENTRY"
        return None
