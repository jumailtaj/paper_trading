"""
Global configuration for the Kite paper-trading system (V1).

Everything here is HARDCODED on purpose. To change a value, edit this file and restart.
V1 is PAPER TRADING ONLY: nothing in this project ever sends an order to Kite.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------- trading rules
POSITION_SIZE = 10            # quantity (shares) per trade. Not derived from capital.
MAX_TRADES_PER_DAY = 5        # global limit on new entries per day

STOCK_UNIVERSE = [
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "SBIN",
]

EXCHANGE = "NSE"                      # exchange used for market data and for charges
INSTRUMENT_TYPE = "EQUITY_INTRADAY"   # key into CHARGES
STARTING_CAPITAL = 100000.0           # virtual capital (Rs)
DEFAULT_STRATEGY_ID = "EMA-01"

# ---------------------------------------------------------------- market data
HISTORY_DAYS = 5              # calendar days of history used to warm up indicators
CANDLE_HISTORY_LIMIT = 500    # closed candles kept in memory per symbol
TICK_SIZE = 0.05

# strategy timeframe -> minutes (candles are aligned to the 09:15 session open)
TIMEFRAME_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "60m": 60}
KITE_INTERVALS = {
    "1m": "minute", "3m": "3minute", "5m": "5minute", "10m": "10minute",
    "15m": "15minute", "30m": "30minute", "60m": "60minute",
}

# ---------------------------------------------------------------- files
REPORTS_DIR = BASE_DIR / "reports"
ARCHIVE_DIR = BASE_DIR / "archive"
WEEKLY_REPORT_PATH = REPORTS_DIR / "weekly_trades.xlsx"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "paper_trader.log"

# ---------------------------------------------------------------- credentials (env var NAMES only)
ENV_API_KEY = "KITE_API_KEY"
ENV_API_SECRET = "KITE_API_SECRET"
ENV_ACCESS_TOKEN = "KITE_ACCESS_TOKEN"

# ---------------------------------------------------------------- charges
# Project-supplied initial rates. Rates are fractions (0.001 = 0.1%) unless noted.
CHARGES = {

    "EQUITY_DELIVERY": {

        "brokerage": {
            "type": "ZERO",
            "rate": 0.0
        },

        "stt": {
            "buy_rate": 0.001,
            "sell_rate": 0.001
        },

        "transaction_charges": {
            "NSE": 0.0000307,
            "BSE": 0.0000375
        },

        "sebi": {
            "per_crore": 10.0
        },

        "stamp_duty": {
            "buy_rate": 0.00015
        },

        "gst": {
            "rate": 0.18
        }
    },

    "EQUITY_INTRADAY": {

        "brokerage": {
            "type": "PERCENT_OR_CAP",
            "rate": 0.0003,
            "max_per_executed_order": 20.0
        },

        "stt": {
            "buy_rate": 0.0,
            "sell_rate": 0.00025
        },

        "transaction_charges": {
            "NSE": 0.0000307,
            "BSE": 0.0000375
        },

        "sebi": {
            "per_crore": 10.0
        },

        "stamp_duty": {
            "buy_rate": 0.00003
        },

        "gst": {
            "rate": 0.18
        }
    }
}


def round_to_tick(price: float) -> float:
    """Round a price to the exchange tick size."""
    return round(round(price / TICK_SIZE) * TICK_SIZE, 2)


def validate_config() -> None:
    """Raise ValueError if the hardcoded configuration is unusable."""
    if not isinstance(POSITION_SIZE, int) or POSITION_SIZE <= 0:
        raise ValueError("POSITION_SIZE must be a positive integer")
    if not isinstance(MAX_TRADES_PER_DAY, int) or MAX_TRADES_PER_DAY <= 0:
        raise ValueError("MAX_TRADES_PER_DAY must be a positive integer")
    if not STOCK_UNIVERSE:
        raise ValueError("STOCK_UNIVERSE must not be empty")
    if len(set(STOCK_UNIVERSE)) != len(STOCK_UNIVERSE):
        raise ValueError("STOCK_UNIVERSE contains duplicates")
    if STARTING_CAPITAL <= 0:
        raise ValueError("STARTING_CAPITAL must be positive")
    if INSTRUMENT_TYPE not in CHARGES:
        raise ValueError(f"INSTRUMENT_TYPE '{INSTRUMENT_TYPE}' missing from CHARGES")
    for kind, cfg in CHARGES.items():
        for key in ("brokerage", "stt", "transaction_charges", "sebi", "stamp_duty", "gst"):
            if key not in cfg:
                raise ValueError(f"CHARGES['{kind}'] missing '{key}'")
        if EXCHANGE not in cfg["transaction_charges"]:
            raise ValueError(f"CHARGES['{kind}'] has no transaction rate for {EXCHANGE}")
