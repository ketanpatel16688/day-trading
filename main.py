import logging
from pathlib import Path
from typing import Dict, List, Optional

from config import configure_logging, load_config
from ibkr_trading_bot.ibkr_manager import IBKRManager
from ibkr_trading_bot.indicators import IndicatorCalculator
from ibkr_trading_bot.strategy import get_strategy_class


def calculate_position_size(
    account_value: float,
    risk_pct: float,
    atr: float,
    atr_multiplier: float,
) -> Optional[int]:
    if atr <= 0 or risk_pct <= 0 or account_value <= 0:
        return None

    risk_amount = account_value * risk_pct
    stop_distance = atr * atr_multiplier

    # Pseudocode position sizing:
    # position_size = risk_amount / stop_distance
    # It is typical to round down to a whole number of shares.
    position_size = int(risk_amount / stop_distance)
    return max(position_size, 0)


def main() -> None:
    config_path = Path("config.json")
    config = load_config(config_path)
    loggers = configure_logging(config)
    execution_logger = loggers["execution"]
    trade_logger = loggers["trade"]
    error_logger = loggers["error"]

    execution_logger.info("Starting one-shot IBKR trading bot run")

    ibkr_config = config.get("ibkr", {})
    tickers: List[str] = config.get("supported_tickers", [])

    if not tickers:
        error_logger.error("No supported tickers defined in config.json")
        return

    strategy_name = config.get("strategy", {}).get("name", "SMARsiAtrStrategy")
    strategy_class = get_strategy_class(strategy_name)
    strategy = strategy_class(IndicatorCalculator(), config)

    manager = IBKRManager(
        host=ibkr_config.get("host", "127.0.0.1"),
        port=ibkr_config.get("port", 7497),
        client_id=ibkr_config.get("client_id", 1001),
    )

    try:
        manager.connect()

        for ticker in tickers:
            execution_logger.info("Fetching data for %s", ticker)
            try:
                bars = manager.fetch_historical_data(
                    symbol=ticker,
                    duration="2 D",
                    bar_size="30 mins",
                    what_to_show="TRADES",
                )
            except Exception as exc:
                error_logger.error("Failed to fetch historical bars for %s: %s", ticker, exc)
                continue

            if len(bars) < 15:
                error_logger.error("Not enough bars to calculate indicators for %s", ticker)
                continue

            highs = [bar["high"] for bar in bars]
            lows = [bar["low"] for bar in bars]
            closes = [bar["close"] for bar in bars]

            signal_payload = strategy.generate_signal(ticker, highs, lows, closes)
            execution_logger.info("Signal for %s: %s", ticker, signal_payload)

            atr_value = signal_payload.get("atr")
            account_value = float(config.get("account_value", 0))
            risk_pct = float(config.get("risk_pct", 0))
            atr_multiplier = float(config.get("atr_multiplier", 1))
            position_size = calculate_position_size(account_value, risk_pct, atr_value, atr_multiplier)

            if position_size is None or position_size <= 0:
                execution_logger.warning(
                    "Position sizing skipped for %s because the calculated size is invalid: %s",
                    ticker,
                    position_size,
                )
                continue

            trade_action = signal_payload.get("signal")
            if trade_action in {"long", "short"}:
                order_action = "BUY" if trade_action == "long" else "SELL"
                order_id = manager.place_order(
                    symbol=ticker,
                    action=order_action,
                    quantity=position_size,
                    order_type="MKT",
                )
                trade_logger.info(
                    "Submitted %s order for %s shares of %s (order_id=%s)",
                    order_action,
                    position_size,
                    ticker,
                    order_id,
                )
            elif signal_payload.get("exit_long"):
                trade_logger.info("Exit-long condition met for %s", ticker)
            elif signal_payload.get("exit_short"):
                trade_logger.info("Exit-short condition met for %s", ticker)
            else:
                execution_logger.info("No trade action for %s", ticker)

    finally:
        manager.disconnect()
        execution_logger.info("IBKR trading bot run complete")


if __name__ == "__main__":
    main()
