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
    try:
        positions = _manager.get_positions()
    except Exception:
        return None
    actual_symbol = crypto_info["symbol"] if is_crypto and crypto_info else symbol
    for p in positions:
        if p.get("symbol") == actual_symbol:
            return p
    return None


def _get_open_orders_for(symbol: str, is_crypto: bool = False, crypto_info: dict = None):
    try:
        orders = _manager.get_open_orders()
    except Exception:
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


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    action_raw = (data.get("action") or "").strip().lower()
    ticker = (data.get("ticker") or "").strip().upper()
    price = data.get("price")

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
        return {"status": "ignored", "reason": "unknown action"}

    # Acquire lock for sequential handling per process
    with _lock:
        logger = logging.getLogger("execution")

        cfg = load_config(Path("config.json"))
        is_crypto, crypto_info = _is_crypto_ticker(ticker, cfg)

        # If SELL alert arrives and there are pending orders, cancel them first
        if action == "SELL":
            try:
                open_orders = _get_open_orders_for(ticker, is_crypto, crypto_info)
            except Exception:
                open_orders = []

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
                    
                    qty_closed = abs(float(pos.get("position", 0)))
                    logger.info("Submitted close (sell) order %s for %s tif=%s", order_id, ticker, tif)
                    _journal.record_close(ticker, qty_closed, order_id)
                    return {"status": "ok", "action": "closed_position", "order_id": order_id}
                except Exception as exc:
                    logger.error("Failed to close position for %s: %s", ticker, exc)
                    return {"status": "error", "error": str(exc)}

            # No position open — ignore SELL
            logger.info("SELL alert for %s ignored: no open position", ticker)
            return {"status": "ignored", "reason": "no_position"}

        # BUY handling
        if action == "BUY":
            pos = _get_position_for(ticker, is_crypto, crypto_info)
            if pos and float(pos.get("position", 0)) != 0:
                logger.info("BUY alert for %s ignored: position already open", ticker)
                return {"status": "ignored", "reason": "position_exists"}

            # If there are pending orders for this ticker, don't duplicate
            pending = _get_open_orders_for(ticker, is_crypto, crypto_info)
            if pending:
                logger.info("BUY alert for %s ignored: pending orders present", ticker)
                return {"status": "ignored", "reason": "pending_orders"}

            # Get risk params
            tif = cfg.get("alert", {}).get("default_tif", "GTC")
            timeframe = data.get("timeframe", "1 day")
            qty, sl_price = _risk_manager.get_risk_params(ticker, "BUY", timeframe, is_crypto, crypto_info)
            if qty is None or sl_price is None:
                logger.error("Failed to calculate risk params for %s", ticker)
                return {"status": "error", "error": "Risk calculation failed"}

            # Place order
            try:
                if is_crypto:
                    # For crypto, use bare market order
                    order_id = _manager.place_crypto_order(
                        symbol=crypto_info["symbol"],
                        exchange=crypto_info["exchange"],
                        currency=crypto_info["currency"],
                        action="BUY",
                        quantity=float(round(qty, 4)),
                        order_type="MKT",
                        tif="IOC"
                    )
                else:
                    # For stocks, use bracket order with SL
                    tp_price = 999999  # Never hit
                    order_ids = _manager.place_bracket_order(
                        symbol=ticker,
                        action="BUY",
                        quantity=float(round(qty, 4)),
                        stop_price=sl_price,
                        take_profit_price=tp_price,
                        tif=tif
                    )
                    order_id = order_ids["parent"]
                logger.info("Placed BUY bracket order %s for %s qty=%s sl=%s tif=%s", order_id, ticker, qty, sl_price, tif)
                _journal.record_trade(ticker, "BUY", float(qty), order_id)
                return {"status": "ok", "action": "placed_buy", "order_id": order_id}
            except Exception as exc:
                logger.error("Failed to place BUY order for %s: %s", ticker, exc)
                return {"status": "error", "error": str(exc)}


def run_server(host: str = "0.0.0.0", port: int = 5000):
    global _manager, _journal, _risk_manager
    # load config and logging
    cfg = load_config(Path("config.json"))
    configure_logging(cfg)
    _manager = _init_manager(cfg)
    _journal = TradingJournal(cfg.get("logging", {}).get("journal_log", "logs/journal.log"))
    _risk_manager = RiskManager(_manager, cfg)

    try:
        # Flask's built-in server in threaded mode is acceptable for this webhook receiver
        app.run(host=host, port=port, threaded=True)
    finally:
        try:
            _manager.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    run_server()
