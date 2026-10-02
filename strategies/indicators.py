"""Pure indicator functions. Candle frames have columns open/high/low/close/volume and a DatetimeIndex."""
from typing import Optional

import numpy as np
import pandas as pd


def price_series(candles: pd.DataFrame, source: str = "close") -> pd.Series:
    c = candles
    sources = {
        "close": lambda: c["close"],
        "open": lambda: c["open"],
        "high": lambda: c["high"],
        "low": lambda: c["low"],
        "hl2": lambda: (c["high"] + c["low"]) / 2,
        "hlc3": lambda: (c["high"] + c["low"] + c["close"]) / 3,
        "ohlc4": lambda: (c["open"] + c["high"] + c["low"] + c["close"]) / 4,
    }
    if source not in sources:
        raise ValueError(f"Unknown price_source '{source}'")
    return sources[source]()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    out = out.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    out = out.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return out


def atr(candles: pd.DataFrame, period: int) -> pd.Series:
    prev_close = candles["close"].shift(1)
    tr = pd.concat(
        [
            candles["high"] - candles["low"],
            (candles["high"] - prev_close).abs(),
            (candles["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def adx(candles: pd.DataFrame, period: int) -> pd.Series:
    up = candles["high"].diff()
    down = -candles["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr_ = atr(candles, period)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def todays_candles(candles: pd.DataFrame) -> pd.DataFrame:
    """Candles belonging to the same calendar day as the last candle."""
    last_day = candles.index[-1].normalize()
    return candles[candles.index.normalize() == last_day]


def session_vwap(candles: pd.DataFrame) -> Optional[float]:
    """VWAP of the current session (typical price weighted by volume). None if no volume."""
    today = todays_candles(candles)
    volume = today["volume"].sum()
    if volume <= 0:
        return None
    typical = (today["high"] + today["low"] + today["close"]) / 3
    return float((typical * today["volume"]).sum() / volume)


def relative_volume(candles: pd.DataFrame, lookback: int = 20) -> Optional[float]:
    """Last candle volume / average volume of the previous `lookback` candles."""
    if len(candles) < lookback + 1:
        return None
    avg = candles["volume"].iloc[-lookback - 1:-1].mean()
    if not avg or avg <= 0:
        return None
    return float(candles["volume"].iloc[-1] / avg)
