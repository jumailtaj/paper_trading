#!/usr/bin/env python3
"""Kite paper trading (V1) - command line interface.

PAPER TRADING ONLY. Kite is used for authentication and market data; no order is ever sent to Kite.
"""
import logging
import os
import sys
import threading
import time
from typing import Optional

from dotenv import load_dotenv

import config
from clock import now_ist
from engine.intraday_engine import RUNNING, STOPPED, STOPPING, IntradayEngine
from kite.client import KiteAuthError, KiteSession
from kite.market_data import KiteFeed
from reporting.weekly_excel import WeeklyExcel
from strategies import registry
from trading.account import Account
from trading.charge_calculator import ChargeCalculator
from trading.paper_broker import PaperBroker
from trading.positions import PositionManager
from trading.risk import RiskManager

log = logging.getLogger("paper_trader")
WIDTH = 38


# ====================================================================== logging
class SecretFilter(logging.Filter):
    """Belt and braces: mask any credential value that ever reaches a log line."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for name in (config.ENV_API_KEY, config.ENV_API_SECRET, config.ENV_ACCESS_TOKEN):
            secret = os.getenv(name)
            if secret and secret in msg:
                msg = msg.replace(secret, "***")
        record.msg, record.args = msg, ()
        return True


def setup_logging() -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    handler.addFilter(SecretFilter())
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    log.propagate = False


# ====================================================================== formatting
def inr(value: float, sign: bool = False, decimals: Optional[int] = None) -> str:
    """Rupee amount with Indian digit grouping, e.g. 100000 -> ₹1,00,000 ; 1425.5 -> ₹1,425.50"""
    value = float(value)
    if round(abs(value), 2) == 0:
        value = 0.0
    neg = value < 0
    v = abs(value)
    if decimals is None:
        decimals = 0 if round(v, 2) == round(v) else 2
    whole, _, frac = f"{v:.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail, groups = whole[:-3], whole[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    prefix = "-" if neg else ("+" if sign and v else "")
    return f"{prefix}₹{whole}" + (f".{frac}" if frac else "")


def box(title: str) -> str:
    return f"╔{'═' * WIDTH}╗\n║{title.center(WIDTH)}║\n╚{'═' * WIDTH}╝"


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def hhmmss(ts) -> str:
    return ts.strftime("%H:%M:%S")


# ====================================================================== application
class PaperTradingApp:
    def __init__(self):
        config.validate_config()
        registry.validate_registry()
        self.excel = WeeklyExcel()
        today = now_ist().date()
        try:
            already_today = self.excel.count_trades(today)
        except Exception:
            log.exception("Could not read the weekly report at startup")
            already_today = 0
        self.account = Account(config.STARTING_CAPITAL)
        strategy = registry.create_strategy(config.DEFAULT_STRATEGY_ID)
        self.engine = IntradayEngine(
            strategy, RiskManager(config.MAX_TRADES_PER_DAY), PaperBroker(),
            PositionManager(first_trade_number=already_today + 1), self.account,
            ChargeCalculator(), self.excel, universe=config.STOCK_UNIVERSE,
            position_size=config.POSITION_SIZE)
        self.engine.on_stopped = self._on_engine_stopped
        self.feed: Optional[KiteFeed] = None

    # ------------------------------------------------------------------ feed lifecycle
    def _on_engine_stopped(self) -> None:
        # called from the market-data thread: shut the socket down from a separate thread
        threading.Thread(target=self._stop_feed, daemon=True).start()

    def _stop_feed(self) -> None:
        if self.feed is not None:
            self.feed.stop()
            self.feed = None

    # ------------------------------------------------------------------ screens
    def main_screen(self) -> None:
        e, v = self.engine, self.engine.account_view()
        s = e.strategy
        print(box("KITE PAPER TRADING"))
        print()
        print(f"STATUS     : {e.status}")
        print(f"STRATEGY   : {s.strategy_id}")
        print(f"TYPE       : {s.strategy_type}")
        print(f"CAPITAL    : {inr(v['starting_capital'])}")
        print(f"EQUITY     : {inr(v['equity'])}")
        print(f"P&L        : {inr(v['total_pnl'], sign=True)}")
        print(f"POSITIONS  : {v['open_positions']}")
        print(f"TRADES     : {v['trades_today']}/{v['max_trades']}")
        print()
        for i, label in enumerate(["Start Paper Trading", "View Positions", "View Orders", "View Trades",
                                   "View Account", "Change Strategy", "Stop Trading", "Exit"], start=1):
            print(f"{i}. {label}")
        print()

    def live_screen_text(self) -> str:
        e, v = self.engine, self.engine.account_view()
        lines = [box("PAPER TRADING RUNNING" if e.status == RUNNING else f"PAPER TRADING {e.status}"), ""]
        lines += [f"Strategy       : {e.strategy.strategy_id}",
                  f"Position Size  : {e.position_size}",
                  f"Max Trades     : {v['max_trades']}",
                  f"Trades Today   : {v['trades_today']}/{v['max_trades']}", "",
                  f"Today's P&L    : {inr(v['day_pnl'], sign=True)}",
                  f"Positions      : {v['open_positions']}", "", "MARKET", "─" * 40]
        for sym, ltp in e.prices_view().items():
            lines.append(f"{sym:<14} {inr(ltp, decimals=2) if ltp else 'waiting...'}")
        lines += ["", "POSITIONS", "─" * 40]
        positions = e.positions_view()
        if not positions:
            lines.append("(none)")
        for p in positions:
            lines += [f"{p.symbol}  {p.side}  {p.quantity}", f"Entry: {inr(p.entry_price, decimals=2)}",
                      f"LTP:   {inr(p.current_price, decimals=2)}",
                      f"P&L:   {inr(p.unrealized_pnl, sign=True)}", ""]
        lines += ["LAST EVENT", "─" * 40]
        events = e.events_view(5)
        lines += events if events else ["Waiting for signal..."]
        lines += ["", "Ctrl+C returns to the menu (trading keeps running)."]
        return "\n".join(lines)

    def live_screen(self) -> None:
        try:
            while True:
                clear_screen()
                print(self.live_screen_text())
                time.sleep(2)
        except KeyboardInterrupt:
            print()

    def view_positions(self) -> None:
        print("\nOPEN POSITIONS\n" + "─" * 40)
        positions = self.engine.positions_view()
        if not positions:
            print("(none)")
        for p in positions:
            sl = inr(p.stop_loss, decimals=2)
            target = inr(p.target, decimals=2) if p.target is not None else "-"
            print(f"{p.symbol:<10} {p.side:<4} {p.quantity}\n"
                  f"  Entry     {inr(p.entry_price, decimals=2)}\n  LTP       {inr(p.current_price, decimals=2)}\n"
                  f"  SL        {sl}\n  Target    {target}\n"
                  f"  P&L       {inr(p.unrealized_pnl, sign=True)}\n  Strategy  {p.strategy_id}\n")

    def view_orders(self) -> None:
        print("\nPAPER ORDERS\n" + "─" * 40)
        orders = self.engine.orders_view()
        if not orders:
            print("(none)")
        for o in orders:
            extra = f"  ({o.reason})" if o.reason else ""
            print(f"{o.order_id}  {o.strategy_id:<7} {o.symbol:<10} {o.side:<4} {o.quantity:<4} "
                  f"{o.price:>9.2f}  {o.status:<8} {hhmmss(o.timestamp)}{extra}")

    def view_trades(self) -> None:
        print("\nCOMPLETED TRADES\n" + "─" * 40)
        trades = self.engine.trades_view()
        if not trades:
            print("(none)")
        for t in trades:
            print(f"{t.trade_id}  {t.strategy_id}  {t.symbol}  {t.side}\n"
                  f"  Entry: {inr(t.entry_price, decimals=2)}   Exit: {inr(t.exit_price, decimals=2)}   Qty: {t.quantity}\n"
                  f"  Gross P&L : {inr(t.gross_pnl, sign=True, decimals=2)}\n"
                  f"  Charges   : -{inr(t.total_charges, decimals=2)}\n"
                  f"  Net P&L   : {inr(t.net_pnl, sign=True, decimals=2)}\n"
                  f"  Exit      : {t.exit_reason}\n")

    def view_account(self) -> None:
        v = self.engine.account_view()
        print("\nVIRTUAL ACCOUNT\n" + "─" * 40)
        print(f"Starting Capital : {inr(v['starting_capital'])}")
        print(f"Available Cash   : {inr(v['available_cash'], decimals=2)}")
        print(f"Used Capital     : {inr(v['used_capital'], decimals=2)}")
        print(f"Realized P&L     : {inr(v['realized_pnl'], sign=True, decimals=2)}  (after charges)")
        print(f"Unrealized P&L   : {inr(v['unrealized_pnl'], sign=True, decimals=2)}")
        print(f"Total P&L        : {inr(v['total_pnl'], sign=True, decimals=2)}")
        print(f"Total Charges    : {inr(v['total_charges'], decimals=2)}")
        print(f"Current Equity   : {inr(v['equity'], decimals=2)}")
        print(f"Open Positions   : {v['open_positions']}")
        print(f"Trades Today     : {v['trades_today']}/{v['max_trades']}")

    # ------------------------------------------------------------------ actions
    def change_strategy(self) -> None:
        e = self.engine
        if e.status != STOPPED or e.positions_view():
            print("\nStop trading and wait for all positions to close before changing strategy.")
            return
        print("\n" + box("SELECT STRATEGY") + "\n")
        numbered, n = {}, 0
        for stype, families in registry.STRATEGIES.items():
            print(stype)
            if not any(families.values()):
                print("\n  No strategies available yet.\n")
                continue
            for family, configs in families.items():
                print(f"\n{family}")
                for sid, cfg in configs.items():
                    n += 1
                    numbered[n] = sid
                    print(f"  {n}. {sid}  - {cfg['name']}")
            print()
        print("0. Back")
        choice = input("\nSelect: ").strip()
        if choice in ("", "0"):
            return
        if not choice.isdigit() or int(choice) not in numbered:
            print("Invalid choice.")
            return
        try:
            e.set_strategy(registry.create_strategy(numbered[int(choice)]))
            print(f"✓ Strategy set to {numbered[int(choice)]}")
        except (RuntimeError, ValueError, KeyError) as exc:
            print(f"✗ {exc}")

    def start_trading(self) -> None:
        e = self.engine
        if e.status != STOPPED:
            self.live_screen()
            return
        s = e.strategy
        print("\nPAPER TRADING CONFIGURATION\n")
        print(f"Strategy       : {s.strategy_id}  ({s.name})")
        print(f"Type           : {s.strategy_type}")
        print(f"Timeframe      : {s.timeframe}\n")
        print("Stock Universe:")
        for sym in config.STOCK_UNIVERSE:
            print(f"  {sym}")
        print(f"\nPosition Size  : {config.POSITION_SIZE}")
        print(f"Max Trades/Day : {config.MAX_TRADES_PER_DAY}")
        print("Mode           : PAPER ONLY - no real orders are ever sent\n")
        if input("Start? [Y/N] ").strip().lower() not in ("y", "yes"):
            return

        print("\nConnecting to Kite...")
        session = KiteSession()
        try:
            request_token = None
            if not session.has_access_token:
                print(f"No {config.ENV_ACCESS_TOKEN} set. Log in here, then paste the request_token "
                      f"from the redirect URL:\n  {session.login_url()}")
                request_token = input("request_token: ").strip()
            session.authenticate(request_token)
            print("✓ Authentication successful")
            tokens = session.instrument_tokens(config.STOCK_UNIVERSE)
        except KiteAuthError as exc:
            print(f"✗ {exc}")
            return
        except Exception as exc:
            log.exception("Kite connection failed")
            print(f"✗ Could not connect to Kite ({type(exc).__name__}). See {config.LOG_FILE.name}.")
            return

        self._seed_history(session, tokens)
        today = now_ist().date()
        try:
            already = self.excel.count_trades(today)
        except Exception:
            already = 0
        current = self.account.trades_today if self.account.trading_date == today else 0
        self.account.set_trades_today(today, max(already, current))  # a restart must not reset the daily limit

        api_key, access_token = session.credentials_for_feed()
        self.feed = KiteFeed(api_key, access_token, {tok: sym for sym, tok in tokens.items()},
                             e.handle_tick)
        e.start()
        try:
            self.feed.start()
            deadline = time.time() + 15
            while not self.feed.connected and time.time() < deadline:
                time.sleep(0.25)
        except Exception:
            log.exception("WebSocket start failed")
        if not self.feed or not self.feed.connected:
            print("✗ WebSocket did not connect. Trading not started.")
            e.stop()
            self._stop_feed()
            return
        print("✓ WebSocket connected")
        print("✓ Market data connected")
        print("✓ Strategy loaded")
        print("✓ Paper broker ready")
        print("\nPAPER TRADING STARTED")
        time.sleep(1)
        self.live_screen()

    def _seed_history(self, session: KiteSession, tokens: dict) -> None:
        tf = self.engine.strategy.timeframe
        failed = []
        for sym, token in tokens.items():
            try:
                self.engine.seed_history(sym, session.historical_candles(token, tf))
            except Exception as exc:
                log.warning("History unavailable for %s (%s)", sym, type(exc).__name__)
                failed.append(sym)
        if failed:
            need = self.engine.strategy.min_candles()
            print(f"⚠ Historical candles unavailable for {', '.join(failed)} (Kite's historical-data "
                  f"access may not be enabled).\n  Indicators will warm up from live candles: "
                  f"~{need} candles of {tf} before signals can appear.")
        else:
            print("✓ Historical candles loaded")

    def stop_trading(self) -> None:
        e = self.engine
        if e.status == STOPPED:
            print("\nTrading is already stopped.")
            return
        state = e.stop()
        if state == STOPPING:
            print(f"\nNew entries stopped. {len(e.positions_view())} open position(s) are still being "
                  "managed (stop loss / target / strategy exit / forced exit).")
        else:
            print("\nTRADING STOPPED")

    def request_exit(self) -> bool:
        e = self.engine
        if e.status != STOPPED:
            print("\nTrading is still active. Choose 'Stop Trading' first"
                  + (" and let the open positions close." if e.positions_view() else "."))
            return False
        if e.positions_view():
            print("\nWARNING\n\nThere are currently open positions.\n\n"
                  "Close/manage positions before exiting the application.")
            if input("Type EXIT to quit anyway and LOSE this in-memory state: ").strip() != "EXIT":
                return False
        return True

    # ------------------------------------------------------------------ main loop
    def run(self) -> None:
        actions = {"1": self.start_trading, "2": self.view_positions, "3": self.view_orders,
                   "4": self.view_trades, "5": self.view_account, "6": self.change_strategy,
                   "7": self.stop_trading}
        while True:
            try:
                print()
                self.main_screen()
                choice = input("Select: ").strip()
                if choice == "8":
                    if self.request_exit():
                        break
                elif choice in actions:
                    actions[choice]()
                else:
                    print("Invalid choice.")
            except KeyboardInterrupt:
                print("\nUse option 8 to exit.")
            except EOFError:
                print("\nInput closed.")
                self.engine.stop()
                if self.engine.positions_view():
                    print("WARNING: open positions exist and their in-memory state will be lost.")
                break
            except Exception:
                log.exception("CLI error")
                print("Unexpected error; details were written to the log. The engine is unaffected.")
        self._stop_feed()
        print("Goodbye.")


def main() -> None:
    load_dotenv()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.system("")  # enables ANSI/VT handling on Windows consoles
    setup_logging()
    PaperTradingApp().run()


if __name__ == "__main__":
    main()
