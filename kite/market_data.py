"""Market data: tick -> candle building (pure, testable) and the Kite WebSocket feed.

MarketData never touches orders. It only stores prices/candles and hands out snapshots.
"""
import logging
from datetime import datetime, timedelta
from typing import Callable, Dict, Iterable, List, Optional

import pandas as pd

import config
from clock import now_ist, to_ist_naive
from strategies.base import MarketSnapshot

log = logging.getLogger("paper_trader")

SESSION_OPEN_MIN = 9 * 60 + 15
SESSION_CLOSE_MIN = 15 * 60 + 30
COLUMNS = ["open", "high", "low", "close", "volume"]


def bucket_start(ts: datetime, minutes: int) -> datetime:
    """Start of the candle containing ts. Candles are aligned to the 09:15 session open."""
    mod = ts.hour * 60 + ts.minute
    start = SESSION_OPEN_MIN + (mod - SESSION_OPEN_MIN) // minutes * minutes
    return ts.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)


class MarketData:
    def __init__(self, timeframe: str, history_limit: int = config.CANDLE_HISTORY_LIMIT):
        self.timeframe = timeframe
        self.minutes = config.TIMEFRAME_MINUTES[timeframe]
        self.history_limit = history_limit
        self._closed: Dict[str, List[dict]] = {}
        self._forming: Dict[str, dict] = {}
        self._last_cum: Dict[str, float] = {}
        self.ltp: Dict[str, float] = {}
        self.prev_close: Dict[str, float] = {}
        self.day_open: Dict[str, float] = {}
        self.last_ts: Dict[str, datetime] = {}

    # ------------------------------------------------------------------ history
    def seed(self, symbol: str, candles: Iterable[dict], now: Optional[datetime] = None) -> int:
        """Load historical candles. A still-forming last candle becomes the forming candle."""
        now = now or now_ist()
        delta = timedelta(minutes=self.minutes)
        closed = self._closed.setdefault(symbol, [])
        known = {c["ts"] for c in closed}
        for c in sorted(candles, key=lambda r: r["ts"]):
            if c["ts"] in known:
                continue
            if c["ts"] + delta <= now:
                closed.append(dict(c))
            else:
                self._forming[symbol] = dict(c)
        del closed[:-self.history_limit]
        if closed:
            self.ltp.setdefault(symbol, closed[-1]["close"])
        return len(closed)

    # ------------------------------------------------------------------ live ticks
    def process_tick(self, symbol: str, ltp: float, ts: datetime, cum_volume: Optional[float] = None,
                     prev_close: Optional[float] = None, day_open: Optional[float] = None) -> bool:
        """Update state with one tick. Returns True when a candle for `symbol` just CLOSED."""
        self.ltp[symbol] = ltp
        self.last_ts[symbol] = ts
        if prev_close:
            self.prev_close[symbol] = prev_close
        if day_open:
            self.day_open[symbol] = day_open

        volume = 0.0
        if cum_volume is not None:
            last = self._last_cum.get(symbol)
            if last is not None and cum_volume >= last:
                volume = cum_volume - last
            self._last_cum[symbol] = cum_volume

        minute = ts.hour * 60 + ts.minute
        if not SESSION_OPEN_MIN <= minute < SESSION_CLOSE_MIN:
            return False  # pre-open / closing-session ticks update LTP only

        bucket = bucket_start(ts, self.minutes)
        forming = self._forming.get(symbol)
        if forming is None:
            self._forming[symbol] = self._new_candle(bucket, ltp, volume)
            return False
        if bucket == forming["ts"]:
            forming["high"] = max(forming["high"], ltp)
            forming["low"] = min(forming["low"], ltp)
            forming["close"] = ltp
            forming["volume"] += volume
            return False
        if bucket > forming["ts"]:
            closed = self._closed.setdefault(symbol, [])
            closed.append(forming)
            del closed[:-self.history_limit]
            self._forming[symbol] = self._new_candle(bucket, ltp, volume)
            return True
        return False  # out-of-order tick

    @staticmethod
    def _new_candle(ts: datetime, price: float, volume: float) -> dict:
        return {"ts": ts, "open": price, "high": price, "low": price, "close": price, "volume": volume}

    # ------------------------------------------------------------------ reads
    def get_ltp(self, symbol: str) -> Optional[float]:
        return self.ltp.get(symbol)

    def candles(self, symbol: str) -> pd.DataFrame:
        rows = self._closed.get(symbol, [])
        if not rows:
            return pd.DataFrame(columns=COLUMNS, index=pd.DatetimeIndex([]))
        df = pd.DataFrame(rows).set_index("ts")
        df.index = pd.DatetimeIndex(df.index)
        return df[COLUMNS].astype(float)

    def snapshot(self, symbol: str, ts: Optional[datetime] = None) -> MarketSnapshot:
        candles = self.candles(symbol)
        ts = ts or self.last_ts.get(symbol) or now_ist()
        day_open = self.day_open.get(symbol)
        if day_open is None and len(candles):
            today = candles[candles.index.normalize() == pd.Timestamp(ts.date())]
            if len(today):
                day_open = float(today["open"].iloc[0])
        return MarketSnapshot(symbol=symbol, candles=candles, ltp=self.ltp.get(symbol), timestamp=ts,
                              prev_close=self.prev_close.get(symbol), day_open=day_open)

    def get_latest(self, symbol: str) -> MarketSnapshot:
        return self.snapshot(symbol)


# ---------------------------------------------------------------------- Kite WebSocket
TickHandler = Callable[..., None]


class KiteFeed:
    """Thin wrapper around KiteTicker. Converts raw ticks into on_tick(symbol, ltp, ts, ...) calls.

    Errors inside the handler are logged and swallowed so one bad tick never kills the socket.
    """

    def __init__(self, api_key: str, access_token: str, token_to_symbol: Dict[int, str],
                 on_tick: TickHandler):
        self._api_key = api_key
        self._access_token = access_token
        self._tokens = dict(token_to_symbol)
        self._on_tick = on_tick
        self._ticker = None
        self.connected = False

    def start(self) -> None:
        from kiteconnect import KiteTicker  # lazy import
        ticker = KiteTicker(self._api_key, self._access_token)
        ticker.on_connect = self._on_connect
        ticker.on_ticks = self._on_ticks
        ticker.on_close = self._on_close
        ticker.on_error = self._on_error
        ticker.on_reconnect = lambda ws, attempts: log.warning("WEBSOCKET RECONNECTING attempt=%s", attempts)
        ticker.on_noreconnect = lambda ws: log.error("WEBSOCKET GAVE UP RECONNECTING")
        self._ticker = ticker
        ticker.connect(threaded=True)

    def stop(self) -> None:
        self.connected = False
        if self._ticker is not None:
            try:
                self._ticker.stop_retry()
                self._ticker.close()
            except Exception as exc:  # shutting down; nothing else to do
                log.warning("WEBSOCKET CLOSE ERROR %s", type(exc).__name__)
            self._ticker = None

    def _on_connect(self, ws, response):
        tokens = list(self._tokens)
        ws.subscribe(tokens)
        ws.set_mode(ws.MODE_FULL, tokens)
        self.connected = True
        log.info("MARKET DATA CONNECTED symbols=%d", len(tokens))

    def _on_close(self, ws, code, reason):
        self.connected = False
        log.warning("WEBSOCKET CLOSED code=%s", code)

    def _on_error(self, ws, code, reason):
        log.error("WEBSOCKET ERROR code=%s", code)

    def _on_ticks(self, ws, ticks):
        for tick in ticks:
            try:
                symbol = self._tokens.get(tick.get("instrument_token"))
                price = tick.get("last_price")
                if symbol is None or not price:
                    continue
                ts = tick.get("exchange_timestamp") or tick.get("last_trade_time") or now_ist()
                ohlc = tick.get("ohlc") or {}
                self._on_tick(symbol, float(price), to_ist_naive(ts), tick.get("volume_traded"),
                              ohlc.get("close"), ohlc.get("open"))
            except Exception:
                log.exception("TICK HANDLER ERROR")
