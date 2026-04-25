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

app = Flask(__name__)

LOG_FILE = "alerts.log"

# Global manager and lock
_manager = None
_journal = None
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


def _get_open_orders_for(symbol: str):
    try:
        orders = _manager.get_open_orders()
    except Exception:
        return []
    return [o for o in orders if o.get("symbol") == symbol]


def _get_position_for(symbol: str):
    try:
        positions = _manager.get_positions()
    except Exception:
        return None
    for p in positions:
        if p.get("symbol") == symbol:
            return p
    return None


def _cancel_orders_for(symbol: str, logger: logging.Logger):
    open_orders = _get_open_orders_for(symbol)
    for o in open_orders:
        oid = o.get("orderId")
        try:
            _manager.cancel_order(int(oid))
            logger.info("Cancelled order %s for %s", oid, symbol)
        except Exception as exc:
            logger.error("Failed to cancel order %s for %s: %s", oid, symbol, exc)


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

        # If SELL alert arrives and there are pending orders, cancel them first
        if action == "SELL":
            try:
                open_orders = _get_open_orders_for(ticker)
            except Exception:
                open_orders = []

            if open_orders:
                logger.info("SELL alert: cancelling %d pending orders for %s", len(open_orders), ticker)
                _cancel_orders_for(ticker, logger)

            # If a position exists, close it (market)
            pos = _get_position_for(ticker)
            if pos and float(pos.get("position", 0)) != 0:
                try:
                    cfg = load_config(Path("config.json"))
                    tif = cfg.get("alert", {}).get("default_tif", "GTC")
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
            pos = _get_position_for(ticker)
            if pos and float(pos.get("position", 0)) != 0:
                logger.info("BUY alert for %s ignored: position already open", ticker)
                return {"status": "ignored", "reason": "position_exists"}

            # If there are pending orders for this ticker, don't duplicate
            pending = _get_open_orders_for(ticker)
            if pending:
                logger.info("BUY alert for %s ignored: pending orders present", ticker)
                return {"status": "ignored", "reason": "pending_orders"}

            # Determine quantity and TIF from config (fallback to 1 and GTC)
            cfg = load_config(Path("config.json"))
            qty = cfg.get("alert", {}).get("default_qty", 1)
            tif = cfg.get("alert", {}).get("default_tif", "GTC")
            try:
                order_id = _manager.place_order(symbol=ticker, action="BUY", quantity=float(qty), order_type="MKT", tif=tif)
                logger.info("Placed BUY market order %s for %s qty=%s tif=%s", order_id, ticker, qty, tif)
                _journal.record_trade(ticker, "BUY", float(qty), order_id)
                return {"status": "ok", "action": "placed_buy", "order_id": order_id}
            except Exception as exc:
                logger.error("Failed to place BUY order for %s: %s", ticker, exc)
                return {"status": "error", "error": str(exc)}


def run_server(host: str = "0.0.0.0", port: int = 5000):
    global _manager, _journal
    # load config and logging
    cfg = load_config(Path("config.json"))
    configure_logging(cfg)
    _manager = _init_manager(cfg)
    _journal = TradingJournal(cfg.get("logging", {}).get("journal_log", "logs/journal.log"))

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
