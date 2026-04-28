# IBKR Python Trading Bot

This repository contains a one-shot Python trading bot skeleton that uses Interactive Brokers (IBKR) APIs to fetch market data and place orders.

## Quick Start - Testing

```bash
# Before committing code, ALWAYS run:
python test_function.py

# Expected: All 41 tests pass
# [OK] ALL TESTS PASSED - REPO IS HEALTHY
```

## Features

- Separate `IBKRManager` for data and order management
- `IndicatorCalculator` for SMA, RSI, ATR
- Strategy classes derived from a common base class
- One-shot daily execution (intended to run before market close)
- JSON config for account, risk, strategy, and logging settings
- Dedicated logging for execution, trade, and error events
- **Crypto trading support** for cryptocurrencies via TradingView alerts
- Support for stocks, options, and crypto orders via command line
- **Comprehensive Error Handling** - parameter validation, input checks, proper error codes
- **41-Test Suite** - catches regressions before commit

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Update `config.json` with your IBKR connection details, supported tickers, account size, and risk settings. For crypto trading, set the maximum trade value:

```json
{
  "alert": {
    "crypto_max_trade_value": 500
  }
}
```

For crypto trading, the quantity is automatically calculated based on the `crypto_max_trade_value` setting. The formula is: `quantity = crypto_max_trade_value / current_price`.

If the TradingView webhook includes a `price` field, it uses that price. Otherwise, it fetches the current price from IBKR before placing the order.

3. For crypto trading, add crypto mappings in `config.json`:

```json
{
  "crypto_mappings": {
    "SOL": {
      "symbol": "SOL",
      "exchange": "PAXOS",
      "currency": "USD"
    },
    "BTC": {
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

## TradingView Integration

The bot includes a webhook endpoint (`trade_alerts.py`) that accepts alerts from TradingView. The webhook expects JSON payloads with:

- `action`: "buy", "sell", "long", or "short"
- `ticker`: The ticker symbol (maps to IBKR symbols via config)
- `price`: Optional price information

For crypto trading, the ticker must be configured in `crypto_mappings` in `config.json`.

Example webhook call:
```bash
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{"action": "buy", "ticker": "SOL", "price": 150.0}'
```

## Command Line Usage

### Crypto Orders

Place crypto orders directly:

```bash
# Simple market order
python main.py --crypto SOL --crypto-side buy --crypto-qty 0.1

# Limit order
python main.py --crypto BTC --crypto-side buy --crypto-qty 0.001 --crypto-limit 45000

# Bracket order with stop-loss and take-profit
python main.py --crypto ETH --crypto-side buy --crypto-qty 0.01 --crypto-sl 2800 --crypto-tp 3200
```

### Stock Orders

```bash
# Bracket order
python main.py --bracket AAPL --bracket-side buy --bracket-qty 10 --bracket-sl 180 --bracket-tp 200
```

### Option Orders

```bash
# Option order
python main.py --option "AAPL 20240821 C 170" --option-side buy --option-qty 1 --option-limit 2.50
```

## File structure

- `main.py` — one-shot daily runner and command-line interface
- `trade_alerts.py` — Flask webhook server for TradingView alerts
- `config.py` — JSON config loader and logging setup
- `ibkr_trading_bot/ibkr_manager.py` — IBKR connection and order management
- `ibkr_trading_bot/indicators.py` — technical indicator calculations
- `ibkr_trading_bot/strategy.py` — base strategy and concrete strategy implementation
- `ibkr_trading_bot/trading_journal.py` — trade logging and journaling

## Error Handling & Testing

### Run Tests Before Committing

```bash
python test_function.py
```

**Results**:
- ✅ If all 41 tests pass → Safe to commit
- ❌ If any test fails → Fix before committing

### What Gets Tested

**41 Comprehensive Tests** covering:
- Parameter validation (negative qty, invalid action, etc.)
- Connection requirements for all APIs
- Error handling and exception logging
- Type consistency across APIs
- Edge cases (very large/small quantities)
- Crypto-specific functionality
- Import and dependency checks

### Test Commands

```bash
# Run all tests
python test_function.py

# Run with verbose output
python test_function.py -v

# Test specific API
python test_function.py TestIBKRManagerParameterValidation
```

### Key Improvements Made

**Critical Bugs Fixed**:
1. Null pointer in `place_crypto_order()` - now checks position exists
2. Undefined variable `tp_price` in webhook - now defined before use
3. Missing webhook input validation - now validates required fields
4. Wrong HTTP status codes - now returns proper 4xx/5xx for errors
5. Silent exception swallowing - now logs all failures

**Parameter Validation Added**:
- `place_order()` - validates action, quantity, order_type, price
- `place_bracket_order()` - validates action, qty, stop_price, take_profit_price
- `place_option_order()` - validates right, strike, quantity
- `place_crypto_order()` - validates action, qty, position existence

**Error Handling Improved**:
- All exceptions now logged with context
- Proper HTTP status codes (200 success, 400 client error, 500 server error)
- Better error messages for debugging

### Pre-Commit Workflow

```bash
1. Make code changes
2. Run: python test_function.py
3. If all pass (41/41) → commit
4. If any fail → fix → go to step 2
```

## Notes

- This code is structured as a starter template, with placeholders for live trading logic.
- Position sizing is currently represented with pseudocode based on `account_value`, `risk_pct`, and `atr_multiplier`.
- Crypto trading uses PAXOS exchange by default, but can be configured per ticker in `crypto_mappings`.
- **Always run tests before committing** to catch regressions early.
