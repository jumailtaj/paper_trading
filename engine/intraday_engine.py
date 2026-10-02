"""Intraday trading engine: decides whether a strategy signal can become a (paper) trade.

    market data -> strategy -> signal -> risk -> paper broker -> position -> exit -> trade
                -> charge calculator -> net P&L -> weekly Excel

The engine owns no strategy logic, no charge maths and no Excel formatting; it only orchestrates.
Every public method is thread-safe so the CLI can inspect state while the WebSocket thread feeds ticks.
"""
import logging
import threading
from collections import deque
from dataclasses import replace
from datetime import datetime
from typing import Callable, Dict, List, Optional

import config
from kite.market_data import MarketData
from strategies.base import NO_SIGNAL, BaseStrategy
from trading.account import Account
from trading.charge_calculator import ChargeCalculator
from trading.paper_broker import FILLED, PaperBroker
from trading.positions import FORCED_EXIT, STOP_LOSS, TARGET, PositionManager
from trading.risk import RiskManager

log = logging.getLogger("paper_trader")

RUNNING = "RUNNING"
STOPPING = "STOPPING"   # no new entries; existing positions are still being managed
STOPPED = "STOPPED"

_EXIT_EVENT = {STOP_LOSS: "STOP LOSS HIT", TARGET: "TARGET HIT", FORCED_EXIT: "FORCED EXIT"}


class IntradayEngine:
    def __init__(self, strategy: BaseStrategy, risk: RiskManager, broker: PaperBroker,
                 positions: PositionManager, account: Account, charge_calculator: ChargeCalculator,
                 weekly_excel=None, universe: Optional[List[str]] = None,
                 position_size: int = config.POSITION_SIZE):
        self.strategy = strategy
        self.risk = risk
        self.broker = broker
        self.positions = positions
        self.account = account
        self.charges = charge_calculator
        self.excel = weekly_excel
        self.universe = list(universe if universe is not None else config.STOCK_UNIVERSE)
        self.position_size = position_size
        self.market_data = MarketData(strategy.timeframe)
        self.trades = []
        self.status = STOPPED
        self.on_stopped: Optional[Callable[[], None]] = None
        self._events = deque(maxlen=200)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ lifecycle
    @property
    def accepting_entries(self) -> bool:
        return self.status == RUNNING

    def set_strategy(self, strategy: BaseStrategy) -> None:
        with self._lock:
            if self.status != STOPPED or self.positions.all_open():
                raise RuntimeError("Stop trading and close all positions before changing strategy")
            self.strategy = strategy
            self.market_data = MarketData(strategy.timeframe)
            self._event(f"STRATEGY LOADED {strategy.strategy_id}")

    def seed_history(self, symbol: str, candles) -> int:
        with self._lock:
            return self.market_data.seed(symbol, candles)

    def start(self) -> bool:
        with self._lock:
            if self.status != STOPPED:
                return False
            self.status = RUNNING
            self._event(f"TRADING STARTED strategy={self.strategy.strategy_id} "
                        f"symbols={','.join(self.universe)} size={self.position_size}")
            return True

    def stop(self) -> str:
        """Stop accepting NEW entries. Existing positions keep being managed until they close."""
        with self._lock:
            if self.status == STOPPED:
                return STOPPED
            if self.positions.all_open():
                self.status = STOPPING
                self._event(f"TRADING STOPPING open_positions={len(self.positions.all_open())}")
            else:
                self._finish_stop()
            return self.status

    def _finish_stop(self) -> None:
        self.status = STOPPED
        self._event("TRADING STOPPED")
        if self.on_stopped:
            try:
                self.on_stopped()
            except Exception:
                log.exception("on_stopped callback failed")

    # ------------------------------------------------------------------ tick entry point
    def handle_tick(self, symbol: str, ltp: float, ts: datetime, cum_volume: Optional[float] = None,
                    prev_close: Optional[float] = None, day_open: Optional[float] = None) -> None:
        if symbol not in self.universe or not ltp or ltp <= 0:
            return
        with self._lock:
            if self.status == STOPPED:
                return
            self.account.start_day(ts.date())
            candle_closed = self.market_data.process_tick(symbol, ltp, ts, cum_volume, prev_close, day_open)

            self.positions.update(symbol, ltp)
            reason = self.positions.check_exit(symbol)
            if reason:
                self._close_position(symbol, ltp, ts, reason)
            self._forced_exit_if_due(ts)

            if candle_closed:
                self._on_candle_close(symbol, ts)

            if self.status == STOPPING and not self.positions.all_open():
                self._finish_stop()

    # ------------------------------------------------------------------ internals
    def _forced_exit_if_due(self, ts: datetime) -> None:
        if ts.time() < self.strategy.forced_exit_time:
            return
        for pos in self.positions.all_open():
            self._close_position(pos.symbol, pos.current_price, ts, FORCED_EXIT)

    def _on_candle_close(self, symbol: str, ts: datetime) -> None:
        snap = self.market_data.snapshot(symbol, ts)
        pos = self.positions.get(symbol)
        try:
            if pos is not None:
                reason = self.strategy.should_exit(snap, pos.side)
                if reason and snap.ltp:
                    self._close_position(symbol, snap.ltp, ts, reason)
                return
            if not self.accepting_entries or ts.time() >= self.strategy.forced_exit_time:
                return
            signal = self.strategy.generate_signal(snap)
        except Exception:
            log.exception("STRATEGY ERROR symbol=%s (no trade taken)", symbol)
            return
        if signal.side == NO_SIGNAL:
            return
        self._handle_signal(signal, ts)

    def _handle_signal(self, signal, ts: datetime) -> None:
        self._event(f"SIGNAL Strategy={signal.strategy_id} Symbol={signal.symbol} Side={signal.side} "
                    f"Price={signal.price:.2f}", ts)
        result = self.risk.check(signal, self.account, self.positions.all_open(), self.position_size)
        if not result.approved:
            self.broker.reject_order(signal.symbol, signal.side, self.position_size, signal.price,
                                     result.reason, signal.strategy_id, ts)
            self._event(f"RISK CHECK FAILED Symbol={signal.symbol} Reason={result.reason}", ts)
            self._event(f"SIGNAL REJECTED Strategy={signal.strategy_id} Symbol={signal.symbol} "
                        f"Side={signal.side} Reason={result.reason}", ts)
            return
        self._event(f"RISK CHECK PASSED Symbol={signal.symbol} ({', '.join(result.passed)})", ts)

        order = self.broker.place_order(signal.symbol, signal.side, self.position_size, signal.price,
                                        signal.strategy_id, ts)
        self._event(f"PAPER ORDER CREATED {order.side} {order.symbol} qty={order.quantity} "
                    f"price={order.price:.2f}", ts)
        if order.status != FILLED:
            self._event(f"PAPER ORDER REJECTED {order.symbol} Reason={order.reason}", ts)
            return
        self._event(f"PAPER ORDER FILLED id={order.order_id} {order.side} {order.symbol}", ts)

        self.account.open_position(order.quantity * order.price)
        pos = self.positions.open(order, signal.stop_loss, signal.target, signal.trailing_stop,
                                  signal.breakeven)
        target = f"{pos.target:.2f}" if pos.target is not None else "none"
        self._event(f"POSITION OPENED {pos.symbol} {pos.side} qty={pos.quantity} entry={pos.entry_price:.2f} "
                    f"SL={pos.stop_loss:.2f} Target={target}", ts)

    def _close_position(self, symbol: str, price: float, ts: datetime, reason: str) -> None:
        pos = self.positions.get(symbol)
        if pos is None:
            return
        if reason in _EXIT_EVENT:
            self._event(f"{_EXIT_EVENT[reason]} {symbol} price={price:.2f}", ts)
        exit_side = "SELL" if pos.side == "BUY" else "BUY"
        order = self.broker.place_order(symbol, exit_side, pos.quantity, price, pos.strategy_id, ts)
        if order.status != FILLED:
            self._event(f"EXIT ORDER REJECTED {symbol} Reason={order.reason} (position stays open)", ts)
            return
        entry_notional = pos.entry_price * pos.quantity
        trade = self.positions.close(symbol, order, reason)
        self._event(f"POSITION CLOSED {symbol} reason={reason}", ts)

        breakdown = self.charges.calculate(trade)
        trade.apply_charges(breakdown)
        self.account.close_position(entry_notional, trade.gross_pnl, trade.total_charges)
        self.trades.append(trade)
        self._event(f"CHARGES CALCULATED total={trade.total_charges:.2f}", ts)
        self._event(f"TRADE COMPLETED {trade.trade_id} gross={trade.gross_pnl:+.2f} "
                    f"charges={trade.total_charges:.2f} net={trade.net_pnl:+.2f}", ts)

        if self.excel is not None:
            try:
                self.excel.save_trade(trade)
                self._event("EXCEL UPDATED", ts)
            except Exception as exc:  # the trade stays in memory; never crash the engine over a report
                log.exception("EXCEL UPDATE FAILED")
                self._event(f"EXCEL UPDATE FAILED ({type(exc).__name__}: {exc})", ts)

    def _event(self, text: str, ts: Optional[datetime] = None) -> None:
        log.info(text)
        stamp = (ts or datetime.now()).strftime("%H:%M:%S")
        self._events.append(f"{stamp} {text}")

    # ------------------------------------------------------------------ read-only views (for the CLI)
    def positions_view(self):
        with self._lock:
            return [replace(p) for p in self.positions.all_open()]

    def orders_view(self):
        with self._lock:
            return list(self.broker.orders)

    def trades_view(self):
        with self._lock:
            return list(self.trades)

    def prices_view(self) -> Dict[str, Optional[float]]:
        with self._lock:
            return {s: self.market_data.get_ltp(s) for s in self.universe}

    def events_view(self, n: int = 5) -> List[str]:
        with self._lock:
            return list(self._events)[-n:]

    def account_view(self) -> dict:
        with self._lock:
            unrealized = self.positions.total_unrealized()
            acc = self.account
            return {
                "starting_capital": acc.starting_capital,
                "available_cash": acc.available_cash,
                "used_capital": acc.used_capital,
                "realized_pnl": acc.realized_pnl,
                "unrealized_pnl": unrealized,
                "total_pnl": acc.realized_pnl + unrealized,
                "equity": acc.equity(unrealized),
                "day_pnl": acc.day_pnl + unrealized,
                "open_positions": len(self.positions.all_open()),
                "trades_today": acc.trades_today,
                "max_trades": self.risk.max_trades_per_day,
                "total_charges": acc.total_charges,
            }
