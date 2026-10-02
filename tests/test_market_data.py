from datetime import datetime, timedelta

import pytest

from kite.market_data import MarketData, bucket_start
from kite.client import KiteSession

D = datetime(2026, 9, 30)


def t(h, m, s=0):
    return D + timedelta(hours=h, minutes=m, seconds=s)


def test_bucket_alignment():
    assert bucket_start(t(9, 15, 3), 5) == t(9, 15)
    assert bucket_start(t(9, 19, 59), 5) == t(9, 15)
    assert bucket_start(t(9, 20), 5) == t(9, 20)
    assert bucket_start(t(9, 44), 30) == t(9, 15)
    assert bucket_start(t(9, 45), 30) == t(9, 45)


def test_candle_built_and_closed_on_next_bucket():
    md = MarketData("5m")
    assert md.process_tick("X", 100, t(9, 15, 1), cum_volume=1000) is False
    assert md.process_tick("X", 102, t(9, 17), cum_volume=1500) is False
    assert md.process_tick("X", 99, t(9, 19), cum_volume=1700) is False
    assert md.process_tick("X", 101, t(9, 20, 1), cum_volume=2000) is True  # closes 09:15 candle
    c = md.candles("X")
    assert len(c) == 1
    row = c.iloc[0]
    assert (row.open, row.high, row.low, row.close) == (100, 102, 99, 99)
    assert row.volume == 700  # 500 + 200 (first tick has no baseline)
    assert md.get_ltp("X") == 101


def test_snapshot_contains_only_closed_candles_and_day_open_fallback():
    md = MarketData("5m")
    md.process_tick("X", 100, t(9, 15), cum_volume=10)
    md.process_tick("X", 101, t(9, 20), cum_volume=20)
    snap = md.snapshot("X", t(9, 20))
    assert len(snap.candles) == 1 and snap.ltp == 101
    assert snap.day_open == 100
    md.process_tick("X", 101, t(9, 21), prev_close=95, day_open=98)
    snap = md.snapshot("X")
    assert snap.prev_close == 95 and snap.day_open == 98


def test_ticks_outside_session_update_ltp_only():
    md = MarketData("5m")
    assert md.process_tick("X", 100, t(9, 5)) is False
    assert md.get_ltp("X") == 100
    assert md.candles("X").empty
    md.process_tick("X", 101, t(15, 35))
    assert md.candles("X").empty


def test_seed_history_and_forming_candle():
    md = MarketData("5m")
    hist = [{"ts": t(9, 15), "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10},
            {"ts": t(9, 20), "open": 2, "high": 3, "low": 2, "close": 3, "volume": 10},
            {"ts": t(9, 25), "open": 3, "high": 4, "low": 3, "close": 4, "volume": 5}]  # still forming
    assert md.seed("X", hist, now=t(9, 27)) == 2
    assert md.process_tick("X", 4.5, t(9, 28)) is False       # updates the forming 09:25 candle
    assert md.process_tick("X", 5, t(9, 30)) is True
    c = md.candles("X")
    assert len(c) == 3 and c["high"].iloc[-1] == 4.5


def test_history_limit():
    md = MarketData("5m", history_limit=3)
    for i in range(10):
        md.process_tick("X", 100 + i, t(9, 15 + 5 * i))
    assert len(md.candles("X")) == 3


def test_kite_wrapper_has_no_order_capability():
    assert not hasattr(KiteSession, "place_order")
    import pathlib
    for f in pathlib.Path(__file__).resolve().parent.parent.joinpath("kite").glob("*.py"):
        assert "place_order" not in f.read_text(), f


def test_kite_feed_converts_raw_ticks_and_survives_bad_ones():
    from kite.market_data import KiteFeed
    seen = []
    feed = KiteFeed("key", "token", {111: "RELIANCE"}, lambda *a: seen.append(a))
    ticks = [
        {"instrument_token": 111, "last_price": 1425.5, "volume_traded": 5000,
         "exchange_timestamp": D + timedelta(hours=9, minutes=15, seconds=3),
         "ohlc": {"open": 1420.0, "high": 1430.0, "low": 1418.0, "close": 1410.0}},
        {"instrument_token": 999, "last_price": 1.0},          # unknown instrument -> ignored
        {"instrument_token": 111, "last_price": None},          # no price -> ignored
    ]
    feed._on_ticks(None, ticks)
    assert seen == [("RELIANCE", 1425.5, D + timedelta(hours=9, minutes=15, seconds=3), 5000, 1410.0, 1420.0)]

    boom = KiteFeed("key", "token", {111: "X"}, lambda *a: 1 / 0)
    boom._on_ticks(None, [{"instrument_token": 111, "last_price": 10.0}])  # must not raise
