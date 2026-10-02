"""Trading charge calculation. All rates come from config.CHARGES; nothing is hardcoded here.

Strategies, the engine and risk know NOTHING about charges. The flow is:
completed Trade -> ChargeCalculator -> ChargeBreakdown -> Net P&L.
"""
from dataclasses import asdict, dataclass

import config

COMPONENTS = ("brokerage", "stt", "transaction_charges", "sebi", "gst", "stamp_duty")


@dataclass
class ChargeBreakdown:
    brokerage: float = 0.0
    stt: float = 0.0
    transaction_charges: float = 0.0
    sebi: float = 0.0
    gst: float = 0.0
    stamp_duty: float = 0.0
    total: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


class ChargeCalculator:
    def __init__(self, charges: dict = None, instrument_type: str = config.INSTRUMENT_TYPE,
                 exchange: str = config.EXCHANGE):
        self.charges = charges if charges is not None else config.CHARGES
        self.instrument_type = instrument_type
        self.exchange = exchange

    def _brokerage_for_order(self, cfg: dict, turnover: float) -> float:
        """Brokerage for ONE executed order."""
        if turnover <= 0:
            return 0.0
        kind = cfg["type"]
        if kind == "ZERO":
            return 0.0
        if kind == "PERCENT_OR_CAP":
            return min(cfg["rate"] * turnover, cfg["max_per_executed_order"])
        raise ValueError(f"Unknown brokerage type '{kind}'")

    def calculate_charges(self, instrument_type: str, exchange: str, buy_turnover: float,
                          sell_turnover: float) -> ChargeBreakdown:
        """Charges for a round trip made of ONE buy order and ONE sell order."""
        if instrument_type not in self.charges:
            raise ValueError(f"Unknown instrument type '{instrument_type}'")
        cfg = self.charges[instrument_type]
        if exchange not in cfg["transaction_charges"]:
            raise ValueError(f"No transaction charge configured for exchange '{exchange}'")
        if buy_turnover < 0 or sell_turnover < 0:
            raise ValueError("Turnover cannot be negative")

        total_turnover = buy_turnover + sell_turnover

        # brokerage is per executed order: the entry order and the exit order are charged separately
        brokerage = (self._brokerage_for_order(cfg["brokerage"], buy_turnover)
                     + self._brokerage_for_order(cfg["brokerage"], sell_turnover))
        stt = cfg["stt"]["buy_rate"] * buy_turnover + cfg["stt"]["sell_rate"] * sell_turnover
        # exactly one exchange rate is applied, never both
        transaction = cfg["transaction_charges"][exchange] * total_turnover
        sebi = cfg["sebi"]["per_crore"] * total_turnover / 1e7
        gst = cfg["gst"]["rate"] * (brokerage + sebi + transaction)   # STT and stamp duty excluded
        stamp = cfg["stamp_duty"]["buy_rate"] * buy_turnover          # buy side only

        parts = {
            "brokerage": round(brokerage, 2), "stt": round(stt, 2),
            "transaction_charges": round(transaction, 2), "sebi": round(sebi, 2),
            "gst": round(gst, 2), "stamp_duty": round(stamp, 2),
        }
        parts["total"] = round(sum(parts.values()), 2)
        return ChargeBreakdown(**parts)

    def calculate(self, trade) -> ChargeBreakdown:
        """Charges for a completed Trade (long or short)."""
        entry_value = trade.entry_price * trade.quantity
        exit_value = trade.exit_price * trade.quantity
        if trade.side == "BUY":      # bought first, sold to exit
            buy_turnover, sell_turnover = entry_value, exit_value
        else:                        # short: sold first, bought back to exit
            buy_turnover, sell_turnover = exit_value, entry_value
        return self.calculate_charges(self.instrument_type, self.exchange, buy_turnover, sell_turnover)
