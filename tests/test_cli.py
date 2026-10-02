from datetime import timedelta, datetime

import pytest

import main
from engine.intraday_engine import RUNNING, STOPPED
from strategies.base import BUY, Signal


def test_inr_indian_grouping_and_signs():
    assert main.inr(100000) == "₹1,00,000"
    assert main.inr(1425.5) == "₹1,425.50"
    assert main.inr(1234567.891, decimals=2) == "₹12,34,567.89"
    assert main.inr(420, sign=True) == "+₹420"
    assert main.inr(-285.4, sign=True) == "-₹285.40"
    assert main.inr(0, sign=True) == "₹0"
    assert main.inr(-0.001, sign=True) == "₹0"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(main.config, "WEEKLY_REPORT_PATH", tmp_path / "w.xlsx")
    a = main.PaperTradingApp.__new__(main.PaperTradingApp)
    # build normally but with a temp report location
    import reporting.weekly_excel as wx
    monkeypatch.setattr(main, "WeeklyExcel", lambda: wx.WeeklyExcel(tmp_path / "w.xlsx", tmp_path / "arch"))
    return main.PaperTradingApp()


def test_main_screen_shows_spec_fields(app, capsys):
    app.main_screen()
    out = capsys.readouterr().out
    for text in ("KITE PAPER TRADING", "STATUS     : STOPPED", "STRATEGY   : EMA-01", "TYPE       : INTRADAY",
                 "CAPITAL    : ₹1,00,000", "EQUITY     : ₹1,00,000", "P&L        : ₹0",
                 "POSITIONS  : 0", "TRADES     : 0/5", "1. Start Paper Trading", "8. Exit"):
        assert text in out


def test_views_with_data(app, capsys):
    e = app.engine
    e.start()
    e.handle_tick("RELIANCE", 1425.5, datetime(2026, 9, 30, 9, 15, 5))
    app.view_positions(); app.view_orders(); app.view_trades(); app.view_account()
    out = capsys.readouterr().out
    assert "(none)" in out and "Starting Capital : ₹1,00,000" in out
    assert "Current Equity" in out
    live = app.live_screen_text()
    assert "PAPER TRADING RUNNING" in live and "RELIANCE" in live and "₹1,425.50" in live


def test_exit_blocked_while_running_and_allowed_when_stopped(app, capsys):
    app.engine.start()
    assert app.request_exit() is False
    assert "still active" in capsys.readouterr().out
    app.engine.stop()
    assert app.request_exit() is True


def test_exit_warns_with_open_positions(app, monkeypatch, capsys):
    from trading.positions import Position
    e = app.engine
    e.status = STOPPED
    e.positions.open(e.broker.place_order("X", "BUY", 10, 100.0, "S"), 99.0, 102.0)
    monkeypatch.setattr("builtins.input", lambda *_: "no")
    assert app.request_exit() is False
    assert "open positions" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda *_: "EXIT")
    assert app.request_exit() is True


def test_change_strategy_flow(app, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *_: "5")  # ORB-01
    app.change_strategy()
    out = capsys.readouterr().out
    assert "No strategies available yet." in out and "ORB-01" in out
    assert app.engine.strategy.strategy_id == "ORB-01"


def test_change_strategy_refused_while_running(app, capsys):
    app.engine.start()
    app.change_strategy()
    assert app.engine.strategy.strategy_id == "EMA-01"
    assert "Stop trading" in capsys.readouterr().out


def test_start_without_credentials_fails_cleanly(app, monkeypatch, capsys):
    for var in ("KITE_API_KEY", "KITE_API_SECRET", "KITE_ACCESS_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("builtins.input", lambda *_: "y")
    app.start_trading()
    out = capsys.readouterr().out
    assert "KITE_API_KEY is not set" in out
    assert app.engine.status == STOPPED


def test_secret_filter_masks_credentials(monkeypatch):
    import logging
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "supersecrettoken123")
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "token is supersecrettoken123 ok", (), None)
    main.SecretFilter().filter(rec)
    assert "supersecret" not in rec.getMessage() and "***" in rec.getMessage()


def test_no_sqlite_or_database_anywhere():
    import pathlib
    root = pathlib.Path(main.__file__).parent
    assert not list(root.rglob("database.py")) and not list(root.rglob("*.db"))
    for f in root.rglob("*.py"):
        if "tests" in f.parts:
            continue
        assert "sqlite" not in f.read_text().lower(), f
