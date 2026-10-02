import pytest

from trading.charge_calculator import ChargeCalculator
from trading.positions import Trade
from datetime import datetime

calc = ChargeCalculator()
INTRA, DELIV = "EQUITY_INTRADAY", "EQUITY_DELIVERY"


def test_delivery_brokerage_is_zero():
    assert calc.calculate_charges(DELIV, "NSE", 10000, 10200).brokerage == 0.0


def test_intraday_brokerage_is_percent_per_order():
    # 0.03% of 10,000 = 3.00 ; 0.03% of 10,200 = 3.06 -> charged per executed order
    assert calc.calculate_charges(INTRA, "NSE", 10000, 10200).brokerage == pytest.approx(6.06)


def test_intraday_brokerage_cap_is_per_order_not_per_round_trip():
    # 0.03% of 1,000,000 = 300 -> capped at 20 on EACH of the two orders
    assert calc.calculate_charges(INTRA, "NSE", 1_000_000, 1_000_000).brokerage == pytest.approx(40.0)


def test_delivery_stt_both_sides():
    assert calc.calculate_charges(DELIV, "NSE", 10000, 10200).stt == pytest.approx(20.2)


def test_intraday_stt_sell_side_only():
    c = calc.calculate_charges(INTRA, "NSE", 10000, 10200)
    assert c.stt == pytest.approx(2.55)  # 0.025% of 10,200 only
    assert calc.calculate_charges(INTRA, "NSE", 10000, 0).stt == 0.0  # buy leg alone has no STT


def test_nse_transaction_charge():
    assert calc.calculate_charges(INTRA, "NSE", 1_000_000, 1_000_000).transaction_charges == pytest.approx(61.40)


def test_bse_transaction_charge_and_only_one_exchange_applied():
    bse = calc.calculate_charges(INTRA, "BSE", 1_000_000, 1_000_000)
    assert bse.transaction_charges == pytest.approx(75.0)
    nse = calc.calculate_charges(INTRA, "NSE", 1_000_000, 1_000_000)
    assert bse.transaction_charges != nse.transaction_charges


def test_sebi_scales_with_turnover():
    assert calc.calculate_charges(INTRA, "NSE", 5_000_000, 5_000_000).sebi == pytest.approx(10.0)  # 1 crore
    assert calc.calculate_charges(INTRA, "NSE", 1_000_000, 1_000_000).sebi == pytest.approx(2.0)


def test_gst_base_excludes_stt_and_stamp():
    c = calc.calculate_charges(INTRA, "NSE", 1_000_000, 1_000_000)
    assert c.gst == pytest.approx(round(0.18 * (40 + 2.0 + 61.4), 2))  # 18.61


def test_stamp_duty_buy_side_only():
    assert calc.calculate_charges(INTRA, "NSE", 1_000_000, 1_000_000).stamp_duty == pytest.approx(30.0)
    assert calc.calculate_charges(DELIV, "NSE", 10000, 10200).stamp_duty == pytest.approx(1.5)
    assert calc.calculate_charges(INTRA, "NSE", 0, 1_000_000).stamp_duty == 0.0


def test_total_charges_intraday_example():
    c = calc.calculate_charges(INTRA, "NSE", 10000, 10200)
    assert (c.brokerage, c.stt, c.transaction_charges, c.sebi, c.gst, c.stamp_duty) == \
        (6.06, 2.55, 0.62, 0.02, 1.21, 0.3)
    assert c.total == pytest.approx(10.76)
    assert c.total == pytest.approx(c.brokerage + c.stt + c.transaction_charges + c.sebi + c.gst + c.stamp_duty)


def test_total_charges_delivery_example():
    assert calc.calculate_charges(DELIV, "NSE", 10000, 10200).total == pytest.approx(22.46)


def _trade(side, entry, exit_, qty=10):
    gross = (exit_ - entry) * qty if side == "BUY" else (entry - exit_) * qty
    t0 = datetime(2026, 9, 30, 10, 0)
    return Trade("T1", "EMA-01", "X", side, qty, entry, exit_, t0, t0, gross, "TARGET")


def test_net_pnl_long():
    t = _trade("BUY", 1000, 1020)
    assert t.gross_pnl == 200
    t.apply_charges(calc.calculate(t))
    assert t.total_charges == pytest.approx(10.76)
    assert t.net_pnl == pytest.approx(189.24)


def test_short_trade_turnover_mapping():
    # short: sell 10,200 first, buy back 10,000 -> STT on the 10,200 sell, stamp on the 10,000 buy
    t = _trade("SELL", 1020, 1000)
    c = calc.calculate(t)
    assert c.stt == pytest.approx(2.55) and c.stamp_duty == pytest.approx(0.3)
    t.apply_charges(c)
    assert t.net_pnl == pytest.approx(200 - c.total)


def test_losing_trade_net_is_worse_than_gross():
    t = _trade("BUY", 1000, 990)
    t.apply_charges(calc.calculate(t))
    assert t.gross_pnl == -100 and t.net_pnl < -100


def test_unknown_instrument_or_exchange_raises():
    with pytest.raises(ValueError):
        calc.calculate_charges("OPTIONS", "NSE", 1, 1)
    with pytest.raises(ValueError):
        calc.calculate_charges(INTRA, "MCX", 1, 1)


def test_rates_come_from_config_not_code():
    custom = {INTRA: {**calc.charges[INTRA], "stt": {"buy_rate": 0.0, "sell_rate": 0.01}}}
    c = ChargeCalculator(charges=custom).calculate_charges(INTRA, "NSE", 10000, 10000)
    assert c.stt == pytest.approx(100.0)
