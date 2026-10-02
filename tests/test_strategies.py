from datetime import datetime, timedelta

import pandas as pd
import pytest

from strategies import registry
from strategies.base import BUY, NO_SIGNAL, SELL, MarketSnapshot
from strategies.indicators import adx, atr, ema, relative_volume, rsi, session_vwap
from strategies.intraday.ema import EMAStrategy
from strategies.intraday.orb import ORBStrategy

START = datetime(2026, 9, 30, 9, 15)  # a Wednesday


def make_candles(closes, volumes=None, start=START, minutes=5):
    rows, prev = [], closes[0]
    for i, close in enumerate(closes):
        rows.append({
            "open": prev, "high": max(prev, close) + 0.1, "low": min(prev, close) - 0.1,
            "close": close, "volume": volumes[i] if volumes else 1000,
        })
        prev = close
    idx = pd.DatetimeIndex([start + timedelta(minutes=minutes * i) for i in range(len(closes))])
    return pd.DataFrame(rows, index=idx)


def snap(candles, minutes=5, **kw):
    ts = candles.index[-1].to_pydatetime() + timedelta(minutes=minutes)
    return MarketSnapshot("TEST", candles, float(candles["close"].iloc[-1]), ts, **kw)


def ema_cfg(**over):
    cfg = registry.get_config("EMA-01")
    cfg.update(over)
    return cfg


def bullish_closes():
    return [100 - 0.5 * i for i in range(30)] + [85 + 1.0 * i for i in range(30)]


def bearish_closes():
    return [100 + 0.5 * i for i in range(30)] + [115 - 1.0 * i for i in range(30)]


def first_cross(closes, strategy, side, start=25):
    """Index n such that candles[:n] is the first window whose last candle makes a cross."""
    for n in range(start, len(closes) + 1):
        sig = strategy.generate_signal(snap(make_candles(closes[:n])))
        if sig.side == side:
            return n
    return None


# ---------------------------------------------------------------- registry
def test_registry_valid_and_lists_all():
    registry.validate_registry()
    ids = [s["strategy_id"] for s in registry.list_strategies()]
    assert ids == ["EMA-01", "EMA-02", "EMA-03", "EMA-04", "ORB-01", "ORB-02"]
    assert registry.STRATEGIES["SWING"] == {}


def test_strategy_params_are_read_only():
    s = registry.create_strategy("EMA-01")
    with pytest.raises(TypeError):
        s.params["fast_ema"] = 5


def test_one_class_per_family():
    assert type(registry.create_strategy("EMA-03")) is EMAStrategy
    assert type(registry.create_strategy("EMA-04")) is EMAStrategy
    assert type(registry.create_strategy("ORB-02")) is ORBStrategy


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        EMAStrategy(ema_cfg(fast_ema=30))
    with pytest.raises(ValueError):
        EMAStrategy(ema_cfg(rsi_filter=True, rsi_period=None))


# ---------------------------------------------------------------- EMA signals
def test_buy_signal():
    s = EMAStrategy(ema_cfg())
    closes = bullish_closes()
    n = first_cross(closes, s, BUY)
    assert n is not None
    sig = s.generate_signal(snap(make_candles(closes[:n])))
    assert sig.side == BUY
    assert sig.stop_loss < sig.price < sig.target
    assert sig.target - sig.price == pytest.approx(2 * (sig.price - sig.stop_loss), abs=0.2)
    assert not first_cross(closes[:n - 1], s, BUY)  # no signal on the candle before


def test_sell_signal():
    s = EMAStrategy(ema_cfg())
    closes = bearish_closes()
    n = first_cross(closes, s, SELL)
    assert n is not None
    sig = s.generate_signal(snap(make_candles(closes[:n])))
    assert sig.side == SELL
    assert sig.target < sig.price < sig.stop_loss


def test_no_signal_without_crossover():
    s = EMAStrategy(ema_cfg())
    sig = s.generate_signal(snap(make_candles([100 + 0.1 * i for i in range(40)])))
    assert sig.side == NO_SIGNAL


def test_no_signal_with_too_few_candles_or_outside_window():
    s = EMAStrategy(ema_cfg())
    assert s.generate_signal(snap(make_candles([100, 101, 102]))).side == NO_SIGNAL
    closes = bullish_closes()
    n = first_cross(closes, s, BUY)
    late = make_candles(closes[:n], start=datetime(2026, 9, 30, 13, 0))  # ends after 14:30
    assert s.generate_signal(snap(late)).side == NO_SIGNAL


def test_stale_candles_ignored():
    s = EMAStrategy(ema_cfg())
    closes = bullish_closes()
    n = first_cross(closes, s, BUY)
    candles = make_candles(closes[:n])
    d = snap(candles)
    d.timestamp = d.timestamp + timedelta(days=1)
    assert s.generate_signal(d).side == NO_SIGNAL


# ---------------------------------------------------------------- filters on / off
def test_vwap_filter_disabled_vs_enabled():
    closes = bullish_closes()
    base = EMAStrategy(ema_cfg())
    n = first_cross(closes, base, BUY)
    # heavy opening volume at ~100 pulls session VWAP well above the 93 close
    data = snap(make_candles(closes[:n], volumes=[1_000_000] + [1000] * (n - 1)))
    assert base.generate_signal(data).side == BUY  # filter disabled -> ignored
    filtered = EMAStrategy(ema_cfg(vwap_filter=True))  # price is far below session VWAP
    sig = filtered.generate_signal(data)
    assert sig.side == NO_SIGNAL and "VWAP" in sig.reason


def test_trend_filter_enabled_blocks_counter_trend_buy():
    # long downtrend then a rebound: bullish 9/21 cross happens while price is below the 45 EMA
    closes = [200 - 2 * i for i in range(40)] + [122 + 1.5 * i for i in range(20)]
    n = first_cross(closes, EMAStrategy(ema_cfg()), BUY)
    assert n is not None
    data = snap(make_candles(closes[:n]))
    assert EMAStrategy(ema_cfg()).generate_signal(data).side == BUY  # filter disabled -> ignored
    sig = EMAStrategy(ema_cfg(trend_filter=True, trend_ema=45)).generate_signal(data)
    assert sig.side == NO_SIGNAL and "Trend" in sig.reason


def test_volume_filter_enabled_vs_disabled():
    closes = bullish_closes()
    n = first_cross(closes, EMAStrategy(ema_cfg()), BUY)
    flat = snap(make_candles(closes[:n]))  # constant volume -> RVOL = 1.0
    assert EMAStrategy(ema_cfg(volume_filter=True, rvol_threshold=2.0)).generate_signal(flat).side == NO_SIGNAL
    assert EMAStrategy(ema_cfg(volume_filter=True, rvol_threshold=0.5)).generate_signal(flat).side == BUY


def test_gap_filter_needs_data_and_direction():
    closes = bullish_closes()
    n = first_cross(closes, EMAStrategy(ema_cfg()), BUY)
    s = EMAStrategy(ema_cfg(gap_filter=True))
    candles = make_candles(closes[:n])
    assert s.generate_signal(snap(candles)).side == NO_SIGNAL  # no gap data -> fail safe
    assert s.generate_signal(snap(candles, prev_close=90, day_open=95)).side == BUY
    assert s.generate_signal(snap(candles, prev_close=95, day_open=90)).side == NO_SIGNAL


def test_atr_and_swing_stops():
    closes = bullish_closes()
    n = first_cross(closes, EMAStrategy(ema_cfg()), BUY)
    data = snap(make_candles(closes[:n]))
    atr_sig = EMAStrategy(ema_cfg(stop_method="atr", atr_period=14, atr_multiplier=1.5)).generate_signal(data)
    assert atr_sig.side == BUY and atr_sig.stop_loss < atr_sig.price
    swing_sig = EMAStrategy(ema_cfg(stop_method="swing", swing_lookback=5)).generate_signal(data)
    assert swing_sig.side == BUY and swing_sig.stop_loss < swing_sig.price


def test_signal_carries_trailing_and_breakeven_flags():
    closes = bullish_closes()
    n = first_cross(closes, EMAStrategy(ema_cfg()), BUY)
    sig = EMAStrategy(ema_cfg(trailing_stop=True, breakeven=True)).generate_signal(snap(make_candles(closes[:n])))
    assert sig.trailing_stop and sig.breakeven


# ---------------------------------------------------------------- strategy exit
def test_opposite_crossover_exit():
    s = EMAStrategy(ema_cfg())
    closes = bullish_closes() + [115 - 2.0 * i for i in range(30)]
    reasons = []
    for n in range(40, len(closes) + 1):
        r = s.should_exit(snap(make_candles(closes[:n])), BUY)
        if r:
            reasons.append(r)
    assert reasons == ["OPPOSITE_CROSSOVER"]
    assert EMAStrategy(ema_cfg(opposite_crossover_exit=False)).should_exit(
        snap(make_candles(closes)), BUY) is None


# ---------------------------------------------------------------- ORB
def orb_cfg(**over):
    cfg = registry.get_config("ORB-01")
    cfg.update(over)
    return cfg


def orb_candles(last_close, volumes=None):
    # range candles 09:15-09:25 (high 101.1 / low 98.9), then 09:30 inside, then breakout candle
    closes = [100, 100.5, 100, 100.2, last_close]
    return make_candles(closes, volumes=volumes)


def test_orb_buy_and_sell_and_none():
    s = ORBStrategy(orb_cfg())
    buy = s.generate_signal(snap(orb_candles(102)))
    assert buy.side == BUY and buy.stop_loss < buy.price < buy.target
    sell = s.generate_signal(snap(orb_candles(98)))
    assert sell.side == SELL and sell.target < sell.price < sell.stop_loss
    assert s.generate_signal(snap(orb_candles(100.3))).side == NO_SIGNAL
    assert ORBStrategy(orb_cfg(allow_short=False)).generate_signal(snap(orb_candles(98))).side == NO_SIGNAL


def test_orb_not_ready_before_range_complete():
    s = ORBStrategy(orb_cfg())
    candles = make_candles([100, 101, 102])  # only 3 candles -> range just completed, nothing to break
    assert s.generate_signal(snap(candles)).side == NO_SIGNAL


def test_orb_volume_filter():
    vols_low = [1000, 1000, 1000, 1000, 1000]
    vols_high = [1000, 1000, 1000, 1000, 1000]
    s_off = ORBStrategy(orb_cfg())
    assert s_off.generate_signal(snap(orb_candles(102, vols_low))).side == BUY
    s_on = ORBStrategy(orb_cfg(volume_filter=True, rvol_threshold=1.5))
    # fewer than 21 candles -> RVOL unavailable -> fail safe
    assert s_on.generate_signal(snap(orb_candles(102, vols_high))).side == NO_SIGNAL


def test_orb_range_reentry_exit():
    s = ORBStrategy(orb_cfg(exit_on_range_reentry=True))
    assert s.should_exit(snap(orb_candles(100.3)), BUY) == "RANGE_REENTRY"
    assert s.should_exit(snap(orb_candles(102)), BUY) is None
    assert ORBStrategy(orb_cfg()).should_exit(snap(orb_candles(100.3)), BUY) is None


# ---------------------------------------------------------------- indicators
def test_indicators_basic():
    candles = make_candles([100 + i for i in range(40)])
    assert ema(candles["close"], 5).iloc[-1] < candles["close"].iloc[-1]
    assert rsi(candles["close"], 14).iloc[-1] == 100.0
    assert atr(candles, 14).iloc[-1] > 0
    assert adx(candles, 14).iloc[-1] > 20
    assert relative_volume(candles) == pytest.approx(1.0)
    assert session_vwap(candles) is not None
