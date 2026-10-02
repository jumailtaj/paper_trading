"""Basic global risk rules. The strategy proposes; risk decides whether it may become a trade."""
from dataclasses import dataclass, field
from typing import List

import config

BUY = "BUY"
SELL = "SELL"


@dataclass
class RiskResult:
    approved: bool
    reason: str = ""
    passed: List[str] = field(default_factory=list)


class RiskManager:
    def __init__(self, max_trades_per_day: int = config.MAX_TRADES_PER_DAY):
        self.max_trades_per_day = max_trades_per_day

    def check(self, signal, account, open_positions, quantity: int) -> RiskResult:
        passed: List[str] = []

        def fail(reason: str) -> RiskResult:
            return RiskResult(False, reason, passed)

        # 1. daily trade limit
        if account.trades_today >= self.max_trades_per_day:
            return fail("Maximum trades per day reached")
        passed.append("Daily trade limit")

        # 2. position rules: valid side/price and sane stop loss / target
        if signal.side not in (BUY, SELL):
            return fail("Invalid signal side")
        if not signal.price or signal.price <= 0:
            return fail("Invalid signal price")
        if signal.stop_loss is None or signal.stop_loss <= 0:
            return fail("Stop loss missing")
        long = signal.side == BUY
        if (long and signal.stop_loss >= signal.price) or (not long and signal.stop_loss <= signal.price):
            return fail("Stop loss is on the wrong side of the entry price")
        if signal.target is not None and ((long and signal.target <= signal.price)
                                          or (not long and signal.target >= signal.price)):
            return fail("Target is on the wrong side of the entry price")
        passed.append("Position rules")

        # 3. duplicate position
        if any(p.symbol == signal.symbol for p in open_positions):
            return fail(f"Position already open for {signal.symbol}")
        passed.append("Duplicate position check")

        # 4. position size / available virtual cash
        if not isinstance(quantity, int) or quantity <= 0:
            return fail("Invalid position size")
        if quantity * signal.price > account.available_cash:
            return fail("Insufficient virtual cash for position size")
        passed.append("Position size")

        return RiskResult(True, "", passed)
