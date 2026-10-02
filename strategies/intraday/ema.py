"""EMA strategy family: ONE engine, many hardcoded configurations (EMA-01, EMA-02, ...).

Disabled filters are simply ignored. There is no class per parameter combination.
"""
from typing import Optional

import pandas as pd

from strategies.base import BUY, SELL, BaseStrategy, MarketSnapshot, Signal, risk_levels
from strategies.indicators import (adx, atr, ema, price_series, relative_volume, rsi,
                                   session_vwap)

CONFIRMATIONS = ("crossover", "candle_confirm")
STOP_METHODS = ("fixed_percent", "atr", "swing")
RSI_MID = 50.0              # BUY needs RSI above, SELL needs RSI below
DEFAULT_ADX_THRESHOLD = 20.0
DEFAULT_ATR_MIN_PERCENT = 0.15
RVOL_LOOKBACK = 20


class EMAStrategy(BaseStrategy):
    REQUIRED_KEYS = BaseStrategy.REQUIRED_KEYS + (
        "fast_ema", "slow_ema", "price_source", "confirmation", "stop_method", "target_rr",
        "opposite_crossover_exit",
    )

    def _validate(self) -> None:
        p = self.params
        if not p["fast_ema"] < p["slow_ema"]:
            raise ValueError("fast_ema must be smaller than slow_ema")
        if p["confirmation"] not in CONFIRMATIONS:
            raise ValueError(f"confirmation must be one of {CONFIRMATIONS}")
        if p["stop_method"] not in STOP_METHODS:
            raise ValueError(f"stop_method must be one of {STOP_METHODS}")
        price_series(pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1]}), p["price_source"])
        needs = {
            "trend_filter": ("trend_ema",), "rsi_filter": ("rsi_period",),
            "adx_filter": ("adx_period",), "volume_filter": ("rvol_threshold",),
            "atr_filter": ("atr_period",),
        }
        for flag, keys in needs.items():
            if p.get(flag):
                for k in keys:
                    if not p.get(k):
                        raise ValueError(f"{flag} is enabled but '{k}' is not set")
        if p["stop_method"] == "fixed_percent" and not p.get("stop_percent"):
            raise ValueError("stop_method 'fixed_percent' needs 'stop_percent'")
        if p["stop_method"] == "atr" and not (p.get("atr_period") and p.get("atr_multiplier")):
            raise ValueError("stop_method 'atr' needs 'atr_period' and 'atr_multiplier'")
        if p["stop_method"] == "swing" and not p.get("swing_lookback"):
            raise ValueError("stop_method 'swing' needs 'swing_lookback'")
        if p["target_rr"] is not None and p["target_rr"] <= 0:
            raise ValueError("target_rr must be positive or None")

    # ------------------------------------------------------------------ data needs
    def min_candles(self) -> int:
        p = self.params
        need = [p["slow_ema"] + 3]
        if p.get("trend_filter"):
            need.append(p["trend_ema"] + 1)
        if p.get("rsi_filter"):
            need.append(p["rsi_period"] + 2)
        if p.get("adx_filter"):
            need.append(p["adx_period"] * 2 + 1)
        if p.get("atr_filter") or p["stop_method"] == "atr":
            need.append((p.get("atr_period") or 14) + 2)
        if p["stop_method"] == "swing":
            need.append(p["swing_lookback"] + 1)
        if p.get("volume_filter"):
            need.append(RVOL_LOOKBACK + 1)
        return max(need)

    # ------------------------------------------------------------------ signals
    def _emas(self, candles: pd.DataFrame):
        src = price_series(candles, self.params["price_source"])
        return ema(src, self.params["fast_ema"]), ema(src, self.params["slow_ema"])

    def _crossover(self, fast: pd.Series, slow: pd.Series) -> Optional[str]:
        f1, f0 = fast.iloc[-1], fast.iloc[-2]
        s1, s0 = slow.iloc[-1], slow.iloc[-2]
        if self.params["confirmation"] == "crossover":
            if f0 <= s0 and f1 > s1:
                return BUY
            if f0 >= s0 and f1 < s1:
                return SELL
        else:  # candle_confirm: cross on the previous candle, still holding on the latest one
            f2, s2 = fast.iloc[-3], slow.iloc[-3]
            if f2 <= s2 and f0 > s0 and f1 > s1:
                return BUY
            if f2 >= s2 and f0 < s0 and f1 < s1:
                return SELL
        return None

    def _filter_failure(self, side: str, data: MarketSnapshot, fast: pd.Series,
                        slow: pd.Series) -> Optional[str]:
        """Return a reason string if an ENABLED filter rejects the signal, else None."""
        p, c = self.params, data.candles
        close = float(c["close"].iloc[-1])
        buy = side == BUY

        sep = p.get("minimum_ema_separation")
        if sep and abs(fast.iloc[-1] - slow.iloc[-1]) / close * 100 < sep:
            return "EMA separation too small"

        if p.get("vwap_filter"):
            vwap = session_vwap(c)
            if vwap is None:
                return "VWAP unavailable"
            if (buy and close <= vwap) or (not buy and close >= vwap):
                return "VWAP filter failed"

        if p.get("trend_filter"):
            trend = ema(c["close"], p["trend_ema"]).iloc[-1]
            if (buy and close <= trend) or (not buy and close >= trend):
                return "Trend filter failed"

        if p.get("rsi_filter"):
            value = rsi(c["close"], p["rsi_period"]).iloc[-1]
            if pd.isna(value) or (buy and value <= RSI_MID) or (not buy and value >= RSI_MID):
                return "RSI filter failed"

        if p.get("adx_filter"):
            value = adx(c, p["adx_period"]).iloc[-1]
            if pd.isna(value) or value < (p.get("adx_threshold") or DEFAULT_ADX_THRESHOLD):
                return "ADX filter failed"

        if p.get("volume_filter"):
            rvol = relative_volume(c, RVOL_LOOKBACK)
            if rvol is None or rvol < p["rvol_threshold"]:
                return "Volume filter failed"

        if p.get("gap_filter"):
            if data.prev_close is None or data.day_open is None:
                return "Gap data unavailable"
            if (buy and data.day_open <= data.prev_close) or (not buy and data.day_open >= data.prev_close):
                return "Gap filter failed"

        if p.get("atr_filter"):
            value = atr(c, p["atr_period"]).iloc[-1]
            if pd.isna(value) or value / close * 100 < (p.get("atr_min_percent") or DEFAULT_ATR_MIN_PERCENT):
                return "ATR filter failed"
        return None

    def _stop_price(self, side: str, price: float, candles: pd.DataFrame) -> Optional[float]:
        p = self.params
        buy = side == BUY
        if p["stop_method"] == "fixed_percent":
            dist = price * p["stop_percent"] / 100
        elif p["stop_method"] == "atr":
            value = atr(candles, p["atr_period"]).iloc[-1]
            if pd.isna(value):
                return None
            dist = value * p["atr_multiplier"]
        else:  # swing
            window = candles.iloc[-p["swing_lookback"]:]
            return float(window["low"].min() if buy else window["high"].max())
        return price - dist if buy else price + dist

    def generate_signal(self, data: MarketSnapshot) -> Signal:
        p = self.params
        if not self.candles_are_current(data):
            return self.no_signal(data, "Candles are not from today")
        if len(data.candles) < self.min_candles():
            return self.no_signal(data, "Not enough candles yet")
        if not self.in_entry_window(data.timestamp):
            return self.no_signal(data, "Outside entry window")

        fast, slow = self._emas(data.candles)
        side = self._crossover(fast, slow)
        if side is None:
            return self.no_signal(data, "No EMA crossover")
        failure = self._filter_failure(side, data, fast, slow)
        if failure:
            return self.no_signal(data, failure)

        price = self.entry_price(data)
        stop = self._stop_price(side, price, data.candles)
        if stop is None:
            return self.no_signal(data, "Stop loss unavailable")
        stop, target = risk_levels(side, price, stop, p["target_rr"])
        return Signal(self.strategy_id, data.symbol, side, price=price, stop_loss=stop, target=target,
                      trailing_stop=bool(p.get("trailing_stop")), breakeven=bool(p.get("breakeven")),
                      reason=f"EMA {p['fast_ema']}/{p['slow_ema']} {p['confirmation']}",
                      timestamp=data.timestamp)

    def should_exit(self, data: MarketSnapshot, position_side: str) -> Optional[str]:
        if not self.params["opposite_crossover_exit"]:
            return None
        if len(data.candles) < self.params["slow_ema"] + 3 or not self.candles_are_current(data):
            return None
        fast, slow = self._emas(data.candles)
        f1, f0, s1, s0 = fast.iloc[-1], fast.iloc[-2], slow.iloc[-1], slow.iloc[-2]
        if position_side == BUY and f0 >= s0 and f1 < s1:
            return "OPPOSITE_CROSSOVER"
        if position_side == SELL and f0 <= s0 and f1 > s1:
            return "OPPOSITE_CROSSOVER"
        return None
