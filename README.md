# Kite Paper Trading - V1

Paper trading only. Kite supplies login + live market data; **no order is ever sent to Kite**.
No database: runtime state lives in memory and completed trades go to `reports/weekly_trades.xlsx`.

## Setup
```
pip install -r requirements.txt
# put KITE_API_KEY and KITE_API_SECRET in .env (KITE_ACCESS_TOKEN optional)
python main.py
```
If `KITE_ACCESS_TOKEN` is empty, the app prints the Kite login URL and asks for the `request_token`
(the token stays in memory only; Kite tokens expire daily).

Kite's historical-candle API is a paid add-on. Without it the app still runs; indicators simply warm
up from live candles (EMA-01 needs ~24 five-minute candles, i.e. ~2 hours, before it can signal).

## Where things are changed (all hardcoded, edit then restart)
| What | Where |
|---|---|
| Position size, max trades/day, stock universe, charge rates, capital | `config.py` |
| Strategies and their parameters (EMA-01.., ORB-01..) | `strategies/registry.py` |

Add EMA-05: add one dict to `STRATEGIES["INTRADAY"]["EMA"]`. Nothing else changes.

## Flow
`Kite ticks -> MarketData (candles) -> Strategy -> Signal -> Engine -> Risk -> PaperBroker -> Position
-> Exit (SL / target / strategy / forced 15:15) -> Trade -> ChargeCalculator -> Net P&L -> Weekly Excel`

## Tests
`python -m pytest tests -q`
