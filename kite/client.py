"""Kite authentication and read-only market-data helpers.

SAFETY: this wrapper deliberately exposes NO order functionality. V1 never sends an order to Kite.
Credentials come from environment variables only and are never printed or logged.
"""
import logging
import os
from datetime import timedelta
from typing import Dict, List, Optional

import config
from clock import now_ist, to_ist_naive

log = logging.getLogger("paper_trader")


class KiteAuthError(Exception):
    pass


class KiteSession:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None,
                 access_token: Optional[str] = None):
        self._api_key = api_key or os.getenv(config.ENV_API_KEY, "")
        self._api_secret = api_secret or os.getenv(config.ENV_API_SECRET, "")
        self._access_token = access_token or os.getenv(config.ENV_ACCESS_TOKEN, "")
        self._kite = None

    # ------------------------------------------------------------------ auth
    def _client(self):
        if not self._api_key:
            raise KiteAuthError(f"{config.ENV_API_KEY} is not set (put it in .env)")
        if self._kite is None:
            from kiteconnect import KiteConnect  # lazy import keeps tests independent of the SDK
            self._kite = KiteConnect(api_key=self._api_key)
        return self._kite

    def login_url(self) -> str:
        return self._client().login_url()

    @property
    def has_access_token(self) -> bool:
        return bool(self._access_token)

    def authenticate(self, request_token: Optional[str] = None) -> str:
        """Authenticate and return the Kite user name. Raises KiteAuthError on failure."""
        kite = self._client()
        try:
            if self._access_token:
                kite.set_access_token(self._access_token)
            elif request_token:
                if not self._api_secret:
                    raise KiteAuthError(f"{config.ENV_API_SECRET} is not set (put it in .env)")
                data = kite.generate_session(request_token, api_secret=self._api_secret)
                self._access_token = data["access_token"]  # kept in memory only
                kite.set_access_token(self._access_token)
            else:
                raise KiteAuthError("No access token available; a request_token is required")
            profile = kite.profile()  # also validates the token
        except KiteAuthError:
            raise
        except Exception as exc:
            raise KiteAuthError(f"Kite authentication failed: {type(exc).__name__}") from exc
        return profile.get("user_name") or profile.get("user_id") or "Kite user"

    # ------------------------------------------------------------------ data
    def credentials_for_feed(self):
        """(api_key, access_token) for the WebSocket feed. Used internally only."""
        if not self._access_token:
            raise KiteAuthError("Not authenticated")
        return self._api_key, self._access_token

    def instrument_tokens(self, symbols: List[str], exchange: str = config.EXCHANGE) -> Dict[str, int]:
        rows = self._client().instruments(exchange)
        wanted = set(symbols)
        found = {r["tradingsymbol"]: r["instrument_token"] for r in rows
                 if r["tradingsymbol"] in wanted and r.get("instrument_type") == "EQ"}
        missing = wanted - set(found)
        if missing:
            raise KiteAuthError(f"Instruments not found on {exchange}: {sorted(missing)}")
        return found

    def historical_candles(self, token: int, timeframe: str, days: int = config.HISTORY_DAYS) -> List[dict]:
        """Recent candles as dicts: ts, open, high, low, close, volume (naive IST timestamps)."""
        end = now_ist()
        rows = self._client().historical_data(token, end - timedelta(days=days), end,
                                              config.KITE_INTERVALS[timeframe])
        return [{"ts": to_ist_naive(r["date"]), "open": r["open"], "high": r["high"],
                 "low": r["low"], "close": r["close"], "volume": r.get("volume", 0)} for r in rows]
