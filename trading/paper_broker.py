"""Paper broker: simulates market orders with an immediate fill at the given price.

It has NO connection to Kite and never sends a real order.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from clock import now_ist

FILLED = "FILLED"
REJECTED = "REJECTED"
VALID_SIDES = ("BUY", "SELL")


@dataclass
class Order:
    order_id: str
    strategy_id: str
    symbol: str
    side: str
    quantity: int
    price: float
    timestamp: datetime
    status: str
    reason: str = ""


class PaperBroker:
    def __init__(self):
        self.orders: List[Order] = []
        self._seq = 0

    def _next_id(self) -> str:
        self._seq += 1
        return f"{self._seq:03d}"

    def place_order(self, symbol: str, side: str, quantity: int, price: float,
                    strategy_id: str = "", timestamp: Optional[datetime] = None) -> Order:
        """Simulate a market order: FILLED immediately at `price`, or REJECTED if the inputs are invalid."""
        problem = ""
        if side not in VALID_SIDES:
            problem = f"Invalid side '{side}'"
        elif not isinstance(quantity, int) or quantity <= 0:
            problem = "Quantity must be a positive integer"
        elif not price or price <= 0:
            problem = "Invalid price"
        status = REJECTED if problem else FILLED
        order = Order(self._next_id(), strategy_id, symbol, side, quantity, price or 0.0,
                      timestamp or now_ist(), status, problem)
        self.orders.append(order)
        return order

    def reject_order(self, symbol: str, side: str, quantity: int, price: float, reason: str,
                     strategy_id: str = "", timestamp: Optional[datetime] = None) -> Order:
        """Record an order that risk refused, so it shows up in View Orders as REJECTED."""
        order = Order(self._next_id(), strategy_id, symbol, side, quantity, price,
                      timestamp or now_ist(), REJECTED, reason)
        self.orders.append(order)
        return order
