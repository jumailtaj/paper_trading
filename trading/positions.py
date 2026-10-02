"""Positions and completed trades."""
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from config import round_to_tick

BUY = "BUY"
SELL = "SELL"

STOP_LOSS = "STOP_LOSS"
TARGET = "TARGET"
FORCED_EXIT = "FORCED_EXIT"


def gross_pnl(side: str, entry: float, exit_: float, quantity: int) -> float:
    return (exit_ - entry) * quantity if side == BUY else (entry - exit_) * quantity


@dataclass
class Position:
    strategy_id: str
    symbol: str
    side: str
    quantity: int
    entry_price: float
    current_price: float
    stop_loss: float
    target: Optional[float]
    entry_time: datetime
    unrealized_pnl: float = 0.0
    status: str = "OPEN"
    trailing_stop: bool = False
    breakeven: bool = False
    entry_order_id: str = ""
    initial_stop: float = 0.0
    best_price: float = 0.0
    breakeven_done: bool = False

    def __post_init__(self):
        if not self.initial_stop:
            self.initial_stop = self.stop_loss
        if not self.best_price:
            self.best_price = self.entry_price


@dataclass
class Trade:
    trade_id: str
    strategy_id: str
    symbol: str
    side: str
    quantity: int
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    gross_pnl: float
    exit_reason: str
    brokerage: float = 0.0
    stt: float = 0.0
    transaction_charges: float = 0.0
    sebi_charges: float = 0.0
    gst: float = 0.0
    stamp_duty: float = 0.0
    total_charges: float = 0.0
    net_pnl: float = 0.0

    def apply_charges(self, breakdown) -> None:
        """Copy a ChargeBreakdown onto the trade and compute net P&L."""
        self.brokerage = breakdown.brokerage
        self.stt = breakdown.stt
        self.transaction_charges = breakdown.transaction_charges
        self.sebi_charges = breakdown.sebi
        self.gst = breakdown.gst
        self.stamp_duty = breakdown.stamp_duty
        self.total_charges = breakdown.total
        self.net_pnl = round(self.gross_pnl - self.total_charges, 2)


class PositionManager:
    def __init__(self, first_trade_number: int = 1):
        self._open: Dict[str, Position] = {}
        self._trade_no = first_trade_number

    def has(self, symbol: str) -> bool:
        return symbol in self._open

    def get(self, symbol: str) -> Optional[Position]:
        return self._open.get(symbol)

    def all_open(self) -> List[Position]:
        return list(self._open.values())

    def total_unrealized(self) -> float:
        return round(sum(p.unrealized_pnl for p in self._open.values()), 2)

    def open(self, order, stop_loss: float, target: Optional[float], trailing_stop: bool = False,
             breakeven: bool = False) -> Position:
        if order.symbol in self._open:
            raise ValueError(f"Position already open for {order.symbol}")
        pos = Position(order.strategy_id, order.symbol, order.side, order.quantity, order.price,
                       order.price, stop_loss, target, order.timestamp,
                       trailing_stop=trailing_stop, breakeven=breakeven, entry_order_id=order.order_id)
        self._open[order.symbol] = pos
        return pos

    def update(self, symbol: str, price: float) -> None:
        """Mark to market and apply breakeven / trailing-stop adjustments."""
        pos = self._open.get(symbol)
        if pos is None:
            return
        pos.current_price = price
        pos.unrealized_pnl = round(gross_pnl(pos.side, pos.entry_price, price, pos.quantity), 2)
        long = pos.side == BUY
        pos.best_price = max(pos.best_price, price) if long else min(pos.best_price, price)

        risk = abs(pos.entry_price - pos.initial_stop)
        if risk <= 0:
            return
        favorable = (pos.best_price - pos.entry_price) if long else (pos.entry_price - pos.best_price)
        if pos.breakeven and not pos.breakeven_done and favorable >= risk:
            pos.stop_loss = max(pos.stop_loss, pos.entry_price) if long else min(pos.stop_loss, pos.entry_price)
            pos.breakeven_done = True
        if pos.trailing_stop and favorable > 0:
            trail = round_to_tick(pos.best_price - risk if long else pos.best_price + risk)
            pos.stop_loss = max(pos.stop_loss, trail) if long else min(pos.stop_loss, trail)

    def check_exit(self, symbol: str) -> Optional[str]:
        """STOP_LOSS / TARGET if the latest price hit a level, else None."""
        pos = self._open.get(symbol)
        if pos is None:
            return None
        price = pos.current_price
        if pos.side == BUY:
            if price <= pos.stop_loss:
                return STOP_LOSS
            if pos.target is not None and price >= pos.target:
                return TARGET
        else:
            if price >= pos.stop_loss:
                return STOP_LOSS
            if pos.target is not None and price <= pos.target:
                return TARGET
        return None

    def close(self, symbol: str, exit_order, reason: str) -> Trade:
        pos = self._open.pop(symbol, None)
        if pos is None:
            raise ValueError(f"No open position for {symbol}")
        pos.status = "CLOSED"
        pos.current_price = exit_order.price
        trade = Trade(
            trade_id=f"{exit_order.timestamp:%Y%m%d}-{self._trade_no:03d}",
            strategy_id=pos.strategy_id, symbol=symbol, side=pos.side, quantity=pos.quantity,
            entry_price=pos.entry_price, exit_price=exit_order.price,
            entry_time=pos.entry_time, exit_time=exit_order.timestamp,
            gross_pnl=round(gross_pnl(pos.side, pos.entry_price, exit_order.price, pos.quantity), 2),
            exit_reason=reason,
        )
        self._trade_no += 1
        return trade
