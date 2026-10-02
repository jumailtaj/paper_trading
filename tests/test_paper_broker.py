from datetime import datetime

import pytest

from trading.account import Account
from trading.paper_broker import FILLED, REJECTED, PaperBroker
from trading.positions import PositionManager, STOP_LOSS, TARGET

T0 = datetime(2026, 9, 30, 10, 0)


def test_buy_order_fills_at_price():
    b = PaperBroker()
    o = b.place_order("RELIANCE", "BUY", 10, 1425.5, "EMA-01", T0)
    assert (o.status, o.side, o.price, o.quantity, o.order_id) == (FILLED, "BUY", 1425.5, 10, "001")
    assert o.strategy_id == "EMA-01" and o.timestamp == T0


def test_sell_order_fills_and_ids_increment():
    b = PaperBroker()
    b.place_order("X", "BUY", 1, 10, "S", T0)
    o = b.place_order("X", "SELL", 1, 11, "S", T0)
    assert o.status == FILLED and o.order_id == "002" and len(b.orders) == 2


@pytest.mark.parametrize("side,qty,price", [("HOLD", 10, 100), ("BUY", 0, 100), ("BUY", 10, 0), ("BUY", 10, -1)])
def test_invalid_orders_are_rejected(side, qty, price):
    o = PaperBroker().place_order("X", side, qty, price, "S", T0)
    assert o.status == REJECTED and o.reason


def test_reject_order_is_recorded():
    b = PaperBroker()
    o = b.reject_order("INFY", "BUY", 10, 1520.0, "Maximum trades per day reached", "EMA-01", T0)
    assert o.status == REJECTED and b.orders == [o]


def test_broker_has_no_kite_dependency():
    import inspect
    import trading.paper_broker as mod
    lines = inspect.getsource(mod).splitlines()
    assert not [l for l in lines if l.startswith(("import kite", "from kite"))]
    assert not hasattr(PaperBroker(), "kite")


# ---------------------------------------------------------------- positions
def open_long(pm, **kw):
    o = PaperBroker().place_order("X", "BUY", 10, 100.0, "S", T0)
    return pm.open(o, stop_loss=99.0, target=102.0, **kw)


def test_position_created_after_fill():
    pm = PositionManager()
    p = open_long(pm)
    assert pm.has("X") and p.status == "OPEN" and p.entry_price == 100.0 and p.quantity == 10
    assert p.stop_loss == 99.0 and p.target == 102.0


def test_position_marks_to_market():
    pm = PositionManager()
    p = open_long(pm)
    pm.update("X", 101.0)
    assert p.unrealized_pnl == 10.0 and pm.total_unrealized() == 10.0


def test_position_closure_creates_trade_with_gross_pnl():
    pm, b, acc = PositionManager(), PaperBroker(), Account(100000)
    open_long(pm)
    acc.open_position(1000)
    exit_order = b.place_order("X", "SELL", 10, 102.0, "S", T0)
    t = pm.close("X", exit_order, TARGET)
    assert not pm.has("X")
    assert (t.entry_price, t.exit_price, t.gross_pnl, t.side, t.exit_reason) == (100.0, 102.0, 20.0, "BUY", TARGET)
    assert t.trade_id.startswith("20260930-")
    net = acc.close_position(1000, t.gross_pnl, 5.0)
    assert net == 15.0 and acc.cash == pytest.approx(100015.0) and acc.used_capital == 0
    assert acc.equity() == pytest.approx(100015.0)


def test_short_position_pnl_and_exit_levels():
    pm, b = PositionManager(), PaperBroker()
    o = b.place_order("X", "SELL", 10, 100.0, "S", T0)
    pm.open(o, stop_loss=101.0, target=98.0)
    pm.update("X", 99.0)
    assert pm.get("X").unrealized_pnl == 10.0 and pm.check_exit("X") is None
    pm.update("X", 101.0)
    assert pm.check_exit("X") == STOP_LOSS
    pm.update("X", 98.0)
    assert pm.check_exit("X") == TARGET


def test_stop_loss_and_target_detection_long():
    pm = PositionManager()
    open_long(pm)
    pm.update("X", 100.5)
    assert pm.check_exit("X") is None
    pm.update("X", 99.0)
    assert pm.check_exit("X") == STOP_LOSS
    pm.update("X", 102.0)
    assert pm.check_exit("X") == TARGET


def test_breakeven_moves_stop_to_entry_after_one_r():
    pm = PositionManager()
    p = open_long(pm, breakeven=True)
    pm.update("X", 100.5)
    assert p.stop_loss == 99.0
    pm.update("X", 101.0)  # +1R
    assert p.stop_loss == 100.0
    pm.update("X", 100.0)
    assert pm.check_exit("X") == STOP_LOSS


def test_trailing_stop_ratchets_up_only():
    pm = PositionManager()
    p = open_long(pm, trailing_stop=True)
    pm.update("X", 101.5)
    assert p.stop_loss == 100.5
    pm.update("X", 100.8)  # pullback must not lower the stop
    assert p.stop_loss == 100.5


def test_account_blocks_over_allocation():
    acc = Account(1000)
    with pytest.raises(ValueError):
        acc.open_position(1500)


def test_account_day_rollover_resets_counters():
    from datetime import date
    acc = Account(100000)
    acc.start_day(date(2026, 9, 30))
    acc.open_position(1000)
    assert acc.trades_today == 1
    acc.start_day(date(2026, 9, 30))
    assert acc.trades_today == 1
    acc.start_day(date(2026, 10, 1))
    assert acc.trades_today == 0
