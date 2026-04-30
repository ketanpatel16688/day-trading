# IBKR Python Trading Bot

A Python trading bot using Interactive Brokers (IBKR) APIs to receive TradingView alerts, fetch market data, and place orders for stocks, options, and crypto.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run all unit tests before committing
python test_function.py
# Expected: All tests pass

# Start the webhook server
python main.py
```

## Features

- `IBKRManager` for connection, data, and order management via **ib_async**
- `IndicatorCalculator` for SMA, RSI, ATR
- Strategy classes derived from a common base class
- Flask webhook server for TradingView alerts
- JSON config for account, risk, strategy, and logging settings
- Crypto trading support via PAXOS exchange
- Bracket orders for stocks and options
- Trading journal with weekly CSV export
- Comprehensive parameter validation and error handling
- Test suite to catch regressions before commit

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

Key dependencies:
- `ib-async` — synchronous wrapper for Interactive Brokers API
- `flask` — webhook server for TradingView alerts
- `pandas` — data handling for indicators

2. Update `config.json` with your IBKR connection details, account size, and risk settings:

```json
{
  "alert": {
    "default_tif": "GTC",
    "crypto_max_trade_value": 500
  }
}
```

3. For crypto trading, add crypto mappings in `config.json`:

```json
{
  "crypto_mappings": {
    "SOLUSD": {
      "symbol": "SOL",
      "exchange": "PAXOS",
      "currency": "USD"
    },
    "BTCUSD": {
      "symbol": "BTC",
      "exchange": "PAXOS",
      "currency": "USD"
    }
  }
}
```

4. Run the bot:

```bash
python main.py
```

## File Structure

- `main.py` — one-shot daily runner and command-line interface
- `trade_alerts.py` — Flask webhook server for TradingView alerts (includes health check loop)
- `config.py` — JSON config loader and logging setup
- `ibkr_trading_bot/ibkr_manager.py` — IBKR connection and order management (uses ib_async)
- `ibkr_trading_bot/indicators.py` — technical indicator calculations
- `ibkr_trading_bot/strategy.py` — base strategy and concrete strategy implementation
- `ibkr_trading_bot/trading_journal.py` — trade logging and journaling
- `test_function.py` — unit test suite (no IBKR connection needed)
- `test_live_ibkr.py` — live integration test (requires TWS/Gateway running)

## Architecture

### IBKR Connection Layer

The bot uses **ib_async**, a synchronous-friendly wrapper around the native IBKR API. All IB calls run on a single dedicated worker thread that owns the event loop, preventing deadlocks when called from Flask worker threads.

**Key design:**
- `IBKRManager._ib(fn)` — dispatches any callable to the IB worker thread and blocks until done
- `IBKRManager.ib` — `IB()` instance from ib_async
- `IBKRManager._placed_orders` — order dict for cancel operations
- Order IDs are allocated via `self.ib.client.getReqId()`, which is kept in sync with the gateway's `nextValidId` automatically on connect

**Why ib_async over native ibapi:**
- No manual threading or event synchronization needed
- Clean, Pythonic synchronous API
- Exceptions propagate naturally instead of being trapped in callbacks
- Automatic connection management and order ID tracking

### Order Acknowledgment

Every `placeOrder` call waits for a gateway acknowledgment before returning (via `_wait_for_order_ack`). If the gateway rejects the order (e.g. duplicate ID, invalid contract, bad quantity), a `RuntimeError` is raised immediately so the caller gets a real error instead of silent failure.

Fatal error codes caught: 103 (duplicate ID), 200 (bad contract), 201/202 (order rejected), 203, 321, 322.

## TradingView Webhook

The webhook endpoint in `trade_alerts.py` accepts alerts from TradingView.

**Endpoint:** `POST /webhook`

**Payload:**
```json
{
  "action": "buy",
  "ticker": "SOLUSD",
  "price": 150.0
}
```

- `action`: `"buy"`, `"sell"`, `"long"`, or `"short"`
- `ticker`: symbol as configured in `crypto_mappings` (crypto) or plain symbol (stocks)
- `price`: optional

**Example:**
```bash
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{"action": "buy", "ticker": "SOLUSD", "price": 150.0}'
```

**BUY flow:** calculates qty and stop-loss via `RiskManager`, places bracket order (stock) or entry order (crypto).

**SELL flow:** cancels any pending orders for the ticker, then closes the open position with a market order.

## Command Line Usage

### Crypto Orders

```bash
# Market order
python main.py --crypto SOL --crypto-side buy --crypto-qty 0.1

# Limit order
python main.py --crypto BTC --crypto-side buy --crypto-qty 0.001 --crypto-limit 45000

# With stop-loss and take-profit
python main.py --crypto ETH --crypto-side buy --crypto-qty 0.01 --crypto-sl 2800 --crypto-tp 3200
```

### Stock Orders

```bash
python main.py --bracket AAPL --bracket-side buy --bracket-qty 10 --bracket-sl 180 --bracket-tp 200
```

### Option Orders

```bash
python main.py --option "AAPL 20240821 C 170" --option-side buy --option-qty 1 --option-limit 2.50
```

## Trading Journal

Trades are logged automatically to a weekly CSV file in `logs/`.

### Files

- `logs/journal.log` — raw JSON log (internal)
- `logs/trading_journal_YYYY_WXX.csv` — weekly CSV (e.g. `trading_journal_2025_W18.csv`)

### CSV Columns

| Column | Description |
|--------|-------------|
| `trade_id` | Unique trade identifier |
| `timestamp_entry` | Order placement time (ISO) |
| `timestamp_exit` | Position close time (ISO) |
| `ticker` | Symbol |
| `order_type` | `webalert` or `manual` |
| `quantity` | Shares / coins |
| `entry_price` | Entry price |
| `exit_price` | Exit price |
| `pnl` | Profit/Loss in dollars |
| `pnl_percent` | Return % of entry cost |
| `duration_minutes` | Hold duration |
| `status` | `OPEN` or `CLOSED` |
| `order_id_entry` | Entry order ID |
| `order_id_exit` | Exit order ID |
| `notes` | Additional notes |

A new CSV file is created every Monday (ISO week). Previous weeks are preserved in `logs/` for manual archival.

### View Stats

```bash
python view_trading_journal.py
```

### Programmatic Access

```python
from ibkr_trading_bot.trading_journal import TradingJournal

journal = TradingJournal("logs/journal.log")
stats = journal.get_journal_stats()
print(f"Win Rate: {stats['win_rate']}%")
print(f"Total P&L: ${stats['total_pnl']}")
```

## Testing

### Unit Tests (no IBKR connection needed)

```bash
python test_function.py

# Verbose output
python test_function.py -v

# Specific test class
python test_function.py TestIBKRManagerParameterValidation
```

Tests cover parameter validation, connection requirements, error handling, type consistency, edge cases, and crypto-specific functionality. All manager tests mock `IBKRManager.ib`.

### Live Integration Test

```bash
# Requires TWS or IB Gateway running on 127.0.0.1:7497
python test_live_ibkr.py
```

Tests real connection, position fetching, and graceful disconnection.

### Pre-Commit Workflow

```
1. Make code changes
2. python test_function.py
3. All pass → commit
4. Any fail → fix → go to step 2
```

## Notes

- Crypto orders use `cashQty=500` (configured via `crypto_max_trade_value`) for BUY; SELL reads the actual position from the gateway.
- IBKR does not support bracket orders for CRYPTO — only the entry order is placed. Close via SELL alert.
- Crypto uses PAXOS exchange by default; configurable per ticker in `crypto_mappings`.
- Times in the journal are stored in ISO format (UTC).
