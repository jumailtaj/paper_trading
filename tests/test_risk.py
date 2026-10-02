from types import SimpleNamespace

from trading.account import Account
from trading.risk import RiskManager


def sig(side="BUY", price=100.0, sl=99.0, target=102.0, symbol="X"):
    return SimpleNamespace(side=side, price=price, stop_loss=sl, target=target, symbol=symbol)


def check(signal, account=None, positions=(), qty=10, risk=None):
    return (risk or RiskManager(5)).check(signal, account or Account(100000), list(positions), qty)


def test_valid_signal_passes_all_checks():
    r = check(sig())
    assert r.approved
    assert r.passed == ["Daily trade limit", "Position rules", "Duplicate position check", "Position size"]


def test_max_trades_per_day_rejects():
    acc = Account(100000)
    acc.trades_today = 5
    r = check(sig(), acc)
    assert not r.approved and r.reason == "Maximum trades per day reached"
    acc.trades_today = 4
    assert check(sig(), acc).approved


def test_duplicate_position_rejected():
    r = check(sig(symbol="TCS"), positions=[SimpleNamespace(symbol="TCS")])
    assert not r.approved and "already open" in r.reason
    assert check(sig(symbol="INFY"), positions=[SimpleNamespace(symbol="TCS")]).approved


def test_position_size_checks():
    assert not check(sig(), qty=0).approved
    assert not check(sig(), qty=-5).approved
    r = check(sig(price=100.0), Account(500), qty=10)  # needs 1000, has 500
    assert not r.approved and "cash" in r.reason


def test_position_rules_stop_and_target_sides():
    assert not check(sig("BUY", sl=101.0)).approved          # long stop above entry
    assert not check(sig("BUY", sl=None)).approved           # stop required
    assert not check(sig("BUY", target=99.0)).approved       # long target below entry
    assert check(sig("SELL", price=100, sl=101, target=98)).approved
    assert not check(sig("SELL", price=100, sl=99, target=98)).approved
    assert not check(sig("HOLD")).approved
    assert not check(sig(price=0)).approved


def test_rejection_reports_which_checks_passed_before_failing():
    r = check(sig("BUY", sl=101.0))
    assert r.passed == ["Daily trade limit"]
