"""In-memory virtual account. No persistence: Excel is the persistent trade record."""
from datetime import date
from typing import Optional

import config


class Account:
    def __init__(self, starting_capital: float = config.STARTING_CAPITAL):
        self.starting_capital = starting_capital
        self.cash = starting_capital
        self.used_capital = 0.0
        self.realized_pnl = 0.0       # net of charges
        self.total_charges = 0.0
        self.day_pnl = 0.0            # realized (net) today
        self.trades_today = 0
        self.trading_date: Optional[date] = None

    @property
    def available_cash(self) -> float:
        return self.cash

    def equity(self, unrealized_pnl: float = 0.0) -> float:
        return self.cash + self.used_capital + unrealized_pnl

    def start_day(self, day: date) -> None:
        """Reset daily counters when the date changes."""
        if self.trading_date == day:
            return
        if self.trading_date is not None:
            self.trades_today = 0
            self.day_pnl = 0.0
        self.trading_date = day

    def set_trades_today(self, day: date, count: int) -> None:
        self.trading_date = day
        self.trades_today = max(0, int(count))

    def open_position(self, notional: float) -> None:
        # Simplification: a short also blocks its full notional as capital.
        if notional > self.cash + 1e-9:
            raise ValueError("Insufficient virtual cash")
        self.cash -= notional
        self.used_capital += notional
        self.trades_today += 1

    def close_position(self, entry_notional: float, gross_pnl: float, charges: float) -> float:
        net = gross_pnl - charges
        self.cash += entry_notional + net
        self.used_capital -= entry_notional
        self.realized_pnl += net
        self.day_pnl += net
        self.total_charges += charges
        return net
