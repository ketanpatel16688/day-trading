# IBKR Python Trading Bot

This repository contains a one-shot Python trading bot skeleton that uses Interactive Brokers (IBKR) APIs to fetch market data and place orders.

## Features

- Separate `IBKRManager` for data and order management
- `IndicatorCalculator` for SMA, RSI, ATR
- Strategy classes derived from a common base class
- One-shot daily execution (intended to run before market close)
- JSON config for account, risk, strategy, and logging settings
- Dedicated logging for execution, trade, and error events

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Update `config.json` with your IBKR connection details, supported tickers, account size, and risk settings.

3. Run the bot:

```bash
python main.py
```

## File structure

- `main.py` — one-shot daily runner
- `config.py` — JSON config loader and logging setup
- `ibkr_trading_bot/ibkr_manager.py` — IBKR connection and order management
- `ibkr_trading_bot/indicators.py` — technical indicator calculations
- `ibkr_trading_bot/strategy.py` — base strategy and concrete strategy implementation

## Notes

- This code is structured as a starter template, with placeholders for live trading logic.
- Position sizing is currently represented with pseudocode based on `account_value`, `risk_pct`, and `atr_multiplier`.
