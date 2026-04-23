import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional

# Colored printing helpers — try to use colorama when available for Windows compatibility
try:
    from colorama import init as _colorama_init
    _colorama_init()
except Exception:
    _colorama_init = None

YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


def print_colored(color: str, *args, sep: str = " ", end: str = "\n", **kwargs) -> None:
    text = sep.join(map(str, args))
    print(f"{color}{text}{RESET}", end=end, **kwargs)


def print_yellow(*args, **kwargs) -> None:
    print_colored(YELLOW, *args, **kwargs)


def print_red(*args, **kwargs) -> None:
    print_colored(RED, *args, **kwargs)

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
    parser = argparse.ArgumentParser(description="IBKR trading bot runner / debug helper")
    parser.add_argument("--debug-close", help="Fetch today's close for SYMBOL", metavar="SYMBOL")
    parser.add_argument("--debug-positions", help="Print open positions", action="store_true")
    parser.add_argument("--debug-orders", help="Print pending open orders", action="store_true")
    parser.add_argument(
        "--debug-watchlist",
        help=(
            "Print last daily close and daily gain/loss % for a predefined watchlist"
        ),
        action="store_true",
    )
    parser.add_argument("--bracket", help="Ticker to place bracket order for", metavar="TICKER")
    parser.add_argument("--bracket-side", help="buy or sell", choices=["buy", "sell"], default="buy")
    parser.add_argument("--bracket-qty", help="Quantity for bracket order", type=int, default=1)
    parser.add_argument("--bracket-limit", help="Limit price for parent order (optional)", type=float)
    parser.add_argument("--bracket-sl", help="Stop-loss price (required for bracket)", type=float)
    parser.add_argument("--bracket-tp", help="Take-profit price (required for bracket)", type=float)
    args = parser.parse_args()

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

        # Debug-only commands: if any debug arg supplied, run it and exit
        if (
            args.debug_close
            or args.debug_positions
            or args.debug_orders
            or args.debug_watchlist
            or args.bracket
        ):
            if args.debug_close:
                symbol = args.debug_close
                try:
                    close_price = manager.get_latest_close(symbol)
                    execution_logger.info("Latest close for %s: %s", symbol, close_price)
                    print_yellow(f"Latest close for {symbol}: {close_price}")
                except Exception as exc:
                    error_logger.error("Failed to fetch latest close for %s: %s", symbol, exc)
                    print_red(f"Failed to fetch latest close for {symbol}: {exc}")
            if args.debug_positions:
                try:
                    positions = manager.get_positions()
                    execution_logger.info("Open positions: %s", positions)
                    print_yellow("Open positions:")
                    for p in positions:
                        print_yellow(p)
                except Exception as exc:
                    error_logger.error("Failed to fetch positions: %s", exc)
                    print_red(f"Failed to fetch positions: {exc}")
            if args.debug_orders:
                try:
                    orders = manager.get_open_orders()
                    execution_logger.info("Open orders: %s", orders)
                    print_yellow("Open orders:")
                    for o in orders:
                        print_yellow(o)
                except Exception as exc:
                    error_logger.error("Failed to fetch open orders: %s", exc)
                    print_red(f"Failed to fetch open orders: {exc}")

            if args.debug_watchlist:
                watchlist = [
                    "MSFT",
                    "AAPL",
                    "AMZN",
                    "ORCL",
                    "PLTR",
                    "TSLA",
                    "HOOD",
                    "COIN",
                    "QQQ",
                    "SPY",
                ]
                print_yellow("Watchlist daily closes and % change:")
                print_yellow(f" TICKER   |   Close   |  Change% |")
                for sym in watchlist:
                    try:
                        bars = manager.fetch_historical_data(
                            symbol=sym,
                            duration="2 D",
                            bar_size="1 day",
                            what_to_show="TRADES",
                        )
                        if not bars:
                            error_logger.error("No historical bars for %s", sym)
                            print_red(f"No historical bars for {sym}")
                            continue

                        last_close = float(bars[-1].get("close", 0))
                        prev_close = None
                        if len(bars) >= 2:
                            prev_close = float(bars[-2].get("close", 0))

                        if prev_close is None or prev_close == 0:
                            pct = None
                        else:
                            pct = (last_close - prev_close) / prev_close * 100.0
                        if pct is None:
                            print_yellow(f"{sym} | {last_close} | (no prior close)")
                        else:
                            print_yellow(f"{sym:<10}   {last_close:<10.2f}    {pct:.1f}")
                    except Exception as exc:
                        error_logger.error("Failed to fetch daily data for %s: %s", sym, exc)
                        print_red(f"Failed to fetch daily data for {sym}: {exc}")

            if args.bracket:
                ticker = args.bracket
                side = args.bracket_side
                qty = int(args.bracket_qty)
                sl = args.bracket_sl
                tp = args.bracket_tp
                limit = args.bracket_limit

                if sl is None or tp is None:
                    error_logger.error("Both --bracket-sl and --bracket-tp are required for --bracket")
                    print_red("Both --bracket-sl and --bracket-tp are required for --bracket")
                    return

                try:
                    ids = manager.place_bracket_order(
                        symbol=ticker,
                        action=side,
                        quantity=qty,
                        stop_price=float(sl),
                        take_profit_price=float(tp),
                        limit_price=float(limit) if limit is not None else None,
                    )
                    trade_logger.info("Placed bracket order for %s: %s", ticker, ids)
                    print_yellow(f"Placed bracket order for {ticker}: parent={ids['parent']} tp={ids['tp']} sl={ids['sl']}")
                except Exception as exc:
                    error_logger.error("Failed to place bracket order for %s: %s", ticker, exc)
                    print_red(f"Failed to place bracket order for {ticker}: {exc}")

                return

        # Normal trading run
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
                print_red(f"Failed to fetch historical bars for {ticker}: {exc}")
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
                    quantity=float(position_size),
                    order_type="MKT",
                )
                trade_logger.info(
                    "Submitted %s order for %d shares of %s (order_id=%s)",
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
