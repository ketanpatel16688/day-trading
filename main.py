import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional
import re

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
from ibkr_trading_bot.trading_journal import TradingJournal


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
            "Print last daily close and daily gain/loss %% for a predefined watchlist"
        ),
        action="store_true",
    )
    parser.add_argument("--bracket", help="Ticker to place bracket order for", metavar="TICKER")
    parser.add_argument("--bracket-side", help="buy or sell", choices=["buy", "sell"], default="buy")
    parser.add_argument("--bracket-qty", help="Quantity for bracket order", type=int, default=1)
    parser.add_argument("--bracket-limit", help="Limit price for parent order (optional)", type=float)
    parser.add_argument("--bracket-sl", help="Stop-loss price (required for bracket)", type=float)
    parser.add_argument("--bracket-tp", help="Take-profit price (required for bracket)", type=float)
    
    parser.add_argument("--option", help="Option contract string (e.g. 'AAPL 20240821 C 170' or 'AAPL-20240821-C-170')", metavar="OPTION")
    parser.add_argument("--option-side", help="buy or sell", choices=["buy", "sell"], default="buy")
    parser.add_argument("--option-qty", help="Quantity (contracts) for option order", type=int, default=1)
    parser.add_argument("--option-limit", help="Limit price for parent option order (optional)", type=float)
    parser.add_argument("--option-sl", help="Stop-loss price for option (optional)", type=float)
    parser.add_argument("--option-tp", help="Take-profit price for option (optional)", type=float)
    
    parser.add_argument("--crypto", help="Crypto ticker (e.g. SOL, BTC)", metavar="CRYPTO")
    parser.add_argument("--crypto-side", help="buy or sell", choices=["buy", "sell"], default="buy")
    parser.add_argument("--crypto-qty", help="Quantity for crypto order", type=float, default=0.001)
    parser.add_argument("--crypto-limit", help="Limit price for crypto order (optional)", type=float)
    parser.add_argument("--crypto-sl", help="Stop-loss price for crypto (optional)", type=float)
    parser.add_argument("--crypto-tp", help="Take-profit price for crypto (optional)", type=float)
    
    parser.add_argument("--day-order", help="Use DAY time-in-force instead of GTC (for day trading)", action="store_true")
    
    parser.add_argument("--cancel-order", help="Cancel a pending order by ORDER_ID", type=int)
    parser.add_argument("--close-position", help="Close position for SYMBOL (closes full size by default)", metavar="SYMBOL")
    parser.add_argument("--close-qty", help="Quantity to close (optional)", type=float)
    
    args = parser.parse_args()

    config_path = Path("config.json")
    config = load_config(config_path)
    loggers = configure_logging(config)
    execution_logger = loggers["execution"]
    trade_logger = loggers["trade"]
    error_logger = loggers["error"]

    journal = TradingJournal(config.get("logging", {}).get("journal_log", "logs/journal.log"))

    execution_logger.info(">>>>>>>> Starting Trading Bot <<<<<<<")

    ibkr_config = config.get("ibkr", {})

    manager = IBKRManager(
        host=ibkr_config.get("host", "127.0.0.1"),
        port=ibkr_config.get("port", 7497),
        client_id=ibkr_config.get("client_id", 1001),
    )
    
    # Determine time-in-force based on --day-order flag
    tif = "DAY" if args.day_order else "GTC"
    
    try:
        manager.connect()

        # Debug-only commands: if any debug arg supplied, run it and exit
        if any([
            args.debug_close,
            args.debug_positions,
            args.debug_orders,
            args.debug_watchlist,
            args.bracket,
            args.option,
            args.crypto,
            args.cancel_order is not None,
            args.close_position
        ]):
            if args.debug_close:
                symbol = args.debug_close
                try:
                    # Check crypto_mappings by key ("SOLUSD") or by symbol value ("SOL")
                    crypto_mappings = config.get("crypto_mappings", {})
                    crypto_info = crypto_mappings.get(symbol) or next(
                        (v for v in crypto_mappings.values() if v["symbol"] == symbol), None
                    )
                    if crypto_info:
                        close_price = manager.get_crypto_price(
                            crypto_info["symbol"], crypto_info["exchange"], crypto_info["currency"]
                        )
                    else:
                        close_price = manager.get_latest_close(symbol)
                    execution_logger.info("Latest close for %s: %s", symbol, close_price)
                    print_yellow(f"Latest close for {symbol}: {close_price}")
                except Exception as exc:
                    error_logger.error("Failed to fetch latest close for %s: %s", symbol, exc)
                    print_red(f"Failed to fetch latest close for {symbol}: {exc}")
                return
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
                return
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
                return

            if args.cancel_order is not None:  # Changed from 'if args.cancel_order:' to handle 0 correctly
                oid = args.cancel_order  # No need for int() since type=int already converts it
                try:
                    manager.cancel_order(oid)
                    trade_logger.info("Cancelled order %s", oid)
                    print_yellow(f"Cancelled order {oid}")
                except Exception as exc:
                    error_logger.error("Failed to cancel order %s: %s", oid, exc)
                    print_red(f"Failed to cancel order {oid}: {exc}")
                return

            if args.close_position:
                sym = args.close_position
                qty = args.close_qty
                try:
                    order_id = manager.close_position(sym, quantity=qty)
                    trade_logger.info("Submitted close order %s for %s qty=%s", order_id, sym, qty)
                    print_yellow(f"Submitted close order {order_id} for {sym} qty={qty if qty is not None else 'FULL'}")
                    # Record in journal
                    if qty is None:
                        positions = manager.get_positions()
                        qty_closed = 0
                        for p in positions:
                            if p.get("symbol") == sym:
                                qty_closed = abs(float(p.get("position", 0)))
                                break
                    else:
                        qty_closed = qty
                    journal.record_close(sym, qty_closed, order_id)
                except Exception as exc:
                    error_logger.error("Failed to close position for %s: %s", sym, exc)
                    print_red(f"Failed to close position for {sym}: {exc}")
                return
                return
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
                    return
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
                        tif=tif,
                    )
                    trade_logger.info("Placed bracket order for %s: %s", ticker, ids)
                    print_yellow(f"Placed bracket order for {ticker}: parent={ids['parent']} tp={ids['tp']} sl={ids['sl']}")
                except Exception as exc:
                    error_logger.error("Failed to place bracket order for %s: %s", ticker, exc)
                    print_red(f"Failed to place bracket order for {ticker}: {exc}")

                return

            if args.option:
                # parse option string into underlying, expiry(YYYYMMDD), right(C/P), strike
                opt = args.option
                def parse_option_string(s: str):
                    parts = [p for p in re.split(r"[^A-Za-z0-9\.]+", s) if p]
                    if len(parts) < 4:
                        return None
                    # attempt to find tokens: underlying (letters), expiry (8 digits), right (C/P), strike (digits)
                    underlying = None
                    expiry = None
                    right = None
                    strike = None
                    for p in parts:
                        if re.fullmatch(r"[A-Za-z]+", p) and underlying is None:
                            underlying = p
                            continue
                        if re.fullmatch(r"\d{8}", p) and expiry is None:
                            expiry = p
                            continue
                        if re.fullmatch(r"[CPcp]", p) and right is None:
                            right = p.upper()
                            continue
                        if re.fullmatch(r"\d+(?:\.\d+)?", p) and strike is None:
                            strike = float(p)
                            continue
                    if None in (underlying, expiry, right, strike):
                        return None
                    return (underlying, expiry, strike, right)

                parsed = parse_option_string(opt)
                if not parsed:
                    error_logger.error("Failed to parse option contract string: %s", opt)
                    print_red("Failed to parse option contract string. Example formats: 'AAPL 20240821 C 170' or 'AAPL-20240821-C-170'")
                    return

                underlying, expiry, strike, right = parsed
                side = args.option_side
                qty = int(args.option_qty)
                limit = args.option_limit
                sl = args.option_sl
                tp = args.option_tp

                try:
                    if sl is not None and tp is not None:
                        ids = manager.place_option_bracket(
                            underlying=underlying,
                            expiry=expiry,
                            strike=float(strike),
                            right=right,
                            action=side,
                            quantity=qty,
                            stop_price=float(sl),
                            take_profit_price=float(tp),
                            limit_price=float(limit) if limit is not None else None,
                            tif=tif,
                        )
                        trade_logger.info("Placed option bracket for %s: %s", opt, ids)
                        print_yellow(f"Placed option bracket for {opt}: parent={ids['parent']} tp={ids['tp']} sl={ids['sl']}")
                    else:
                        oid = manager.place_option_order(
                            underlying=underlying,
                            expiry=expiry,
                            strike=float(strike),
                            right=right,
                            action=side,
                            quantity=qty,
                            order_type="LMT" if limit is not None else "MKT",
                            price=float(limit) if limit is not None else None,
                            tif=tif,
                        )
                        trade_logger.info("Placed option order for %s: %s", opt, oid)
                        print_yellow(f"Placed option order for {opt}: order_id={oid}")
                except Exception as exc:
                    error_logger.error("Failed to place option order for %s: %s", opt, exc)
                    print_red(f"Failed to place option order for {opt}: {exc}")

                return

            if args.crypto:
                ticker = args.crypto
                side = args.crypto_side
                qty = float(args.crypto_qty)
                sl = args.crypto_sl
                tp = args.crypto_tp
                limit = args.crypto_limit

                # Load config to get crypto mapping
                cfg = load_config(config_path)
                crypto_mappings = cfg.get("crypto_mappings", {})
                if ticker not in crypto_mappings:
                    error_logger.error("Crypto ticker %s not found in config crypto_mappings", ticker)
                    print_red(f"Crypto ticker {ticker} not found in config crypto_mappings")
                    return

                crypto_info = crypto_mappings[ticker]

                try:
                    if sl is not None and tp is not None:
                        # Place bracket order
                        ids = manager.place_crypto_bracket_order(
                            symbol=crypto_info["symbol"],
                            exchange=crypto_info["exchange"],
                            currency=crypto_info["currency"],
                            action=side,
                            quantity=qty,
                            stop_price=float(sl),
                            take_profit_price=float(tp),
                            limit_price=float(limit) if limit is not None else None,
                            tif="IOC",
                        )
                        trade_logger.info("Placed crypto bracket order for %s: %s", ticker, ids)
                        print_yellow(f"Placed crypto bracket order for {ticker}: parent={ids['parent']} tp={ids['tp']} sl={ids['sl']}")
                    else:
                        # Place simple order
                        oid = manager.place_crypto_order(
                            symbol=crypto_info["symbol"],
                            exchange=crypto_info["exchange"],
                            currency=crypto_info["currency"],
                            action=side,
                            quantity=qty,
                            order_type="LMT" if limit is not None else "MKT",
                            price=float(limit) if limit is not None else None,
                            tif="IOC",
                        )
                        trade_logger.info("Placed crypto order for %s: %s", ticker, oid)
                        print_yellow(f"Placed crypto order for {ticker}: order_id={oid}")
                except Exception as exc:
                    error_logger.error("Failed to place crypto order for %s: %s", ticker, exc)
                    print_red(f"Failed to place crypto order for {ticker}: {exc}")

                return

    finally:
        manager.disconnect()
        execution_logger.info(">>>End of Trading Bot operation<<<")

if __name__ == "__main__":
    main()
