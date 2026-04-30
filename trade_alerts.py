import math

from flask import Flask, request
import json
import datetime
import threading
import logging
import time
from pathlib import Path

from config import load_config, configure_logging
from ibkr_trading_bot.ibkr_manager import IBKRManager
from ibkr_trading_bot.trading_journal import TradingJournal
from risk_management import RiskManager

app = Flask(__name__)

LOG_FILE = "alerts.log"

# Global manager and lock
_manager = None
_journal = None
_risk_manager = None
_lock = threading.Lock()
_health_check_running = False
_config = None


def _init_manager(config):
    manager_cfg = config.get("ibkr", {})
    mgr = IBKRManager(
        host=manager_cfg.get("host", "127.0.0.1"),
        port=manager_cfg.get("port", 7497),
        client_id=manager_cfg.get("client_id", 1001),
    )
    mgr.connect()
    return mgr


def _log_alert(entry: dict):
    timestamp = entry.get("time") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry["time"] = timestamp
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _is_crypto_ticker(ticker: str, config) -> tuple[bool, dict]:
    """Check if ticker is a crypto and return its mapping if so."""
    crypto_mappings = config.get("crypto_mappings", {})
    if ticker in crypto_mappings:
        return True, crypto_mappings[ticker]
    return False, {}


def _get_position_for(symbol: str, is_crypto: bool = False, crypto_info: dict = None):
    logger = logging.getLogger("execution")
    try:
        positions = _manager.get_positions()
    except Exception as exc:
        logger.error("Failed to fetch positions for %s: %s", symbol, str(exc))
        return None
    actual_symbol = crypto_info["symbol"] if is_crypto and crypto_info else symbol
    for p in positions:
        if p.get("symbol") == actual_symbol:
            return p
    logger.debug("No position found for %s", actual_symbol)
    return None


def _get_open_orders_for(symbol: str, is_crypto: bool = False, crypto_info: dict = None):
    logger = logging.getLogger("execution")
    try:
        orders = _manager.get_open_orders()
    except Exception as exc:
        logger.error("Failed to fetch open orders for %s: %s", symbol, str(exc))
        return []
    actual_symbol = crypto_info["symbol"] if is_crypto and crypto_info else symbol
    return [o for o in orders if o.get("symbol") == actual_symbol]


def _cancel_orders_for(symbol: str, logger: logging.Logger, is_crypto: bool = False, crypto_info: dict = None):
    open_orders = _get_open_orders_for(symbol, is_crypto, crypto_info)
    actual_symbol = crypto_info["symbol"] if is_crypto and crypto_info else symbol
    for o in open_orders:
        oid = o.get("orderId")
        try:
            _manager.cancel_order(int(oid))
            logger.info("Cancelled order %s for %s", oid, actual_symbol)
        except Exception as exc:
            logger.error("Failed to cancel order %s for %s: %s", oid, actual_symbol, exc)


def _health_check_loop():
    logger = logging.getLogger("health_check")
    while _health_check_running:
        try:
            if _manager is None or _config is None:
                time.sleep(5)
                continue

            if not _manager.client.isConnected():
                logger.warning("IBKR connection lost, attempting to reconnect...")
                try:
                    _manager.disconnect()
                except Exception:
                    pass

                try:
                    ibkr_cfg = _config.get("ibkr")
                    if ibkr_cfg is None:
                        ibkr_cfg = {}
                    host = ibkr_cfg.get("host") or "127.0.0.1"
                    port = ibkr_cfg.get("port") or 7497
                    client_id = ibkr_cfg.get("client_id") or 1001
                    _manager.client.connect(
                        host=host,
                        port=port,
                        clientId=client_id
                    )
                    logger.info("IBKR reconnection successful")
                except Exception as exc:
                    logger.error("Failed to reconnect to IBKR: %s", str(exc))

            time.sleep(10)
        except Exception as exc:
            logger.error("Health check error: %s", str(exc))
            time.sleep(10)


@app.route("/webhook", methods=["POST"])
def webhook():  # type: ignore[misc]
    try:
        data = request.get_json(force=True)
    except Exception:
        return {"status": "error", "error": "Invalid JSON"}, 400

    action_raw = (data.get("action") or "").strip().lower()
    ticker = (data.get("ticker") or "").strip().upper()
    price = data.get("price")
    timeframe = data.get("timeframe", "1 day")

    # Validate required fields
    if not action_raw:
        return {"status": "error", "error": "Missing 'action' field"}, 400
    if not ticker:
        return {"status": "error", "error": "Missing 'ticker' field"}, 400

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log_entry = {"time": timestamp, "action": action_raw, "ticker": ticker, "price": price}
    print("Alert received:", log_entry)
    _log_alert(log_entry)

    # Normalise actions
    if action_raw in {"buy", "long"}:
        action = "BUY"
    elif action_raw in {"sell", "short"}:
        action = "SELL"
    else:
        # Unknown action — ignore
        logger = logging.getLogger("execution")
        logger.info("Unknown action: %s", action_raw)
        return {"status": "ignored", "reason": "unknown action"}, 200

    # Acquire lock for sequential handling per process
    with _lock:
        logger = logging.getLogger("execution")

        try:
            cfg = load_config(Path("config.json"))
        except Exception as exc:
            logger.error("Failed to load config: %s", str(exc))
            return {"status": "error", "error": "Config load failed"}, 500

        is_crypto, crypto_info = _is_crypto_ticker(ticker, cfg)

        # If SELL alert arrives and there are pending orders, cancel them first
        if action == "SELL":
            open_orders = _get_open_orders_for(ticker, is_crypto, crypto_info)

            if open_orders:
                logger.info("SELL alert: cancelling %d pending orders for %s", len(open_orders), ticker)
                _cancel_orders_for(ticker, logger, is_crypto, crypto_info)

            # If a position exists, close it (market)
            pos = _get_position_for(ticker, is_crypto, crypto_info)
            if pos and float(pos.get("position", 0)) != 0:
                try:
                    tif = cfg.get("alert", {}).get("default_tif", "GTC")

                    if is_crypto:
                        order_id = _manager.close_crypto_position(
                            crypto_info["symbol"],
                            crypto_info["exchange"],
                            crypto_info["currency"],
                            tif=tif
                        )
                    else:
                        order_id = _manager.close_position(ticker, tif=tif)

                    entry_price = None
                    exit_price = None
                    qty_closed = 0.0
                    try:
                        position = pos.get("position") or 0
                        qty_closed = abs(float(str(position)))
                    except (ValueError, TypeError):
                        pass
                    try:
                        avg_cost = pos.get("avgCost")
                        if avg_cost is not None:
                            entry_price = float(avg_cost)
                    except (ValueError, TypeError):
                        pass
                    try:
                        market_price = pos.get("marketPrice")
                        if market_price is not None:
                            exit_price = float(market_price)
                    except (ValueError, TypeError):
                        pass
                    logger.info("Submitted close (sell) order %s for %s tif=%s", order_id, ticker, tif)
                    _journal.record_close(ticker, qty_closed, order_id, entry_price=entry_price, exit_price=exit_price)
                    return {"status": "ok", "action": "closed_position", "order_id": order_id}, 200
                except Exception as exc:
                    logger.error("Failed to close position for %s: %s", ticker, str(exc))
                    return {"status": "error", "error": str(exc)}, 500

            # No position open — ignore SELL
            logger.info("SELL alert for %s ignored: no open position", ticker)
            return {"status": "ignored", "reason": "no_position"}, 200

        # BUY handling
        if action == "BUY":
#            pos = _get_position_for(ticker, is_crypto, crypto_info)
#            if pos and float(pos.get("position", 0)) != 0:
#                logger.info("BUY alert for %s ignored: position already open", ticker)
#                return {"status": "ignored", "reason": "position_exists"}, 200

            # If there are pending orders for this ticker, don't duplicate
            pending = _get_open_orders_for(ticker, is_crypto, crypto_info)
            if pending:
                logger.info("BUY alert for %s ignored: pending orders present", ticker)
                return {"status": "ignored", "reason": "pending_orders"}, 200

            # Get risk params
            tif = cfg.get("alert", {}).get("default_tif", "GTC")

            qty, sl_price = _risk_manager.get_risk_params(ticker, "BUY", timeframe, is_crypto, crypto_info)
            if qty is None or sl_price is None:
                logger.error("Failed to calculate risk params for %s", ticker)
                return {"status": "error", "error": "Risk calculation failed"}, 500
            logger.info("Calculated risk params for %s order: qty=%s sl=%s", ticker, qty, sl_price)
            # Place order
            try:
                if is_crypto:
                    # For crypto, use bracket order with calculated SL
                    tp_price = 999999  # Never hit for crypto
                    order_id = _manager.place_crypto_bracket_order(
                        symbol=crypto_info["symbol"],
                        exchange=crypto_info["exchange"],
                        currency=crypto_info["currency"],
                        action="BUY",
                        quantity=qty,
                        stop_price=sl_price,
                        take_profit_price=tp_price,
                        tif="IOC"
                    )

                else:
                    # For stocks, use bracket order with SL
                    tp_price = 999999  # Never hit
                    order_ids = _manager.place_bracket_order(
                        symbol=ticker,
                        action="BUY",
                        quantity=qty,
                        stop_price=sl_price,
                        take_profit_price=tp_price,
                        tif=tif
                    )
                    order_id = order_ids["parent"]
                logger.info("Placed BUY bracket order %s for %s qty=%s sl=%s tif=%s", order_id, ticker, qty, sl_price, tif)
                _journal.record_trade(ticker, "BUY", float(qty), order_id, order_type="webalert")
                return {"status": "ok", "action": "placed_buy", "order_id": order_id}, 200
            except Exception as exc:
                logger.error("Failed to place BUY order for %s: %s", ticker, str(exc))
                return {"status": "error", "error": str(exc)}, 500


def run_server(host: str = "0.0.0.0", port: int = 5000):
    global _manager, _journal, _risk_manager, _health_check_running, _config
    logger = logging.getLogger("execution")

    # load config and logging
    cfg = load_config(Path("config.json"))
    _config = cfg
    configure_logging(cfg)
    _manager = _init_manager(cfg)
    _journal = TradingJournal(cfg.get("logging", {}).get("journal_log", "logs/journal.log"))
    _risk_manager = RiskManager(_manager, cfg)

    # Start health check thread
    _health_check_running = True
    health_thread = threading.Thread(target=_health_check_loop, daemon=True)
    health_thread.start()
    logger.info("IBKR connection health check thread started (checks every 5 seconds)")

    try:
        # Flask's built-in server in threaded mode is acceptable for this webhook receiver
        app.run(host=host, port=port, threaded=True)
    finally:
        _health_check_running = False
        logger.info("Stopping health check thread...")
        health_thread.join(timeout=2)
        try:
            _manager.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    run_server()
